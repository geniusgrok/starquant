"""``Venue`` implementation for Binance USDⓈ-M (demo/testnet) on top of :class:`BinanceRestClient`."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.rules import format_decimal
from starquant_shared.binance_rules import parse_exchange_info
from starquant_shared.types import AccountState, InstrumentRules, OrderAck, OrderRequest, Position, Side, VenueError

logger = logging.getLogger(__name__)

RULES_TTL_SECONDS = 3600.0
ORDER_NOT_FOUND = -2013
# /fapi/v1/forceOrders caps `limit` here, unlike the 1000 the paged endpoints accept.
FORCE_ORDERS_LIMIT = 100
PAGE_LIMIT = 1000
MAX_PAGES = 50
# The per-row id each paged endpoint supplies.  Having one is what makes `_paged`'s overlapping cursor
# safe; an endpoint absent from this map is walked the conservative way instead (see `_paged`).
PAGE_ID_FIELDS = {"/fapi/v1/income": "tranId", "/fapi/v1/userTrades": "id"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_order_ack(payload: dict[str, Any]) -> OrderAck:
    executed = Decimal(str(payload.get("executedQty", "0") or "0"))
    return OrderAck(
        symbol=str(payload.get("symbol", "")),
        client_order_id=str(payload.get("clientOrderId", "")),
        order_id=str(payload.get("orderId", "")),
        side=Side(str(payload.get("side", "BUY"))),
        status=str(payload.get("status", "")),
        executed_qty=executed,
        avg_price=_float(payload.get("avgPrice")),
        reduce_only=bool(payload.get("reduceOnly", False)),
        raw=dict(payload),
    )


def parse_position(payload: dict[str, Any]) -> Position | None:
    """One position from either /fapi/v2/positionRisk or a /fapi/v2/account row.

    The two payloads disagree in ways that are silent rather than loud, so nothing here
    derives a number the venue did not supply (observed on demo-fapi 2026-09-04):

    * account rows carry ``notional`` but no ``markPrice``; computing the notional from a
      missing mark gave zero for every position while fifteen were open;
    * account rows spell it ``unrealizedProfit``, positionRisk ``unRealizedProfit``;
    * ``leverage`` reads "0" in both, so it is not a usable record of what was set -
      ``state.leverage_set`` is.
    """
    qty = _float(payload.get("positionAmt"))
    if qty == 0.0:
        return None
    raw_notional = payload.get("notional")
    unrealized = payload.get("unRealizedProfit")
    if unrealized is None:
        unrealized = payload.get("unrealizedProfit")
    return Position(
        symbol=str(payload.get("symbol", "")),
        qty=qty,
        entry_price=_float(payload.get("entryPrice")),
        mark_price=_float(payload.get("markPrice")),
        unrealized_pnl=_float(unrealized),
        leverage=int(_float(payload.get("leverage"), 0.0)),
        venue_notional=None if raw_notional is None else _float(raw_notional),
        # DL-X1: the venue writes 0 when there is no reachable liquidation price, which under cross
        # margin is every long with enough equity behind it (measured on demo 2026-09-06: 14/14 longs
        # zero, 4/4 shorts non-zero).  0 is not a price; carrying it as one would put every long at
        # distance zero.  Account rows do not carry the field at all, hence the None default.
        liquidation_price=(lambda v: v if v and v > 0 else None)(_float(payload.get("liquidationPrice"), 0.0)),
    )


class BinanceUsdmVenue:
    def __init__(self, client: BinanceRestClient) -> None:
        self._client = client
        self._rules: dict[str, InstrumentRules] = {}
        self._rules_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def sync_clock(self) -> int:
        return await self._client.sync_clock()

    def venue_time_ms(self) -> int:
        """Now, on the venue's clock, from the offset the signed-request path already maintains.

        Signed requests are immune to a wrong host clock: a -1021 makes the client resync and retry, so
        their ``timestamp`` is venue-correct.  Query *parameters* are not: ``startTime``/``endTime`` on
        /fapi/v1/income are passed through untouched, so a host clock an hour behind (measured
        2026-09-04) asks for an hour-old window and cannot see anything that has happened since.  This is
        the accessor the income watermark uses so both ends of that window are on the venue's clock.
        """
        return int(time.time() * 1000) + self._client.clock_offset_ms

    async def rules(self) -> dict[str, InstrumentRules]:
        if not self._rules or time.monotonic() - self._rules_at > RULES_TTL_SECONDS:
            payload = await self._client.get("/fapi/v1/exchangeInfo")
            self._rules = parse_exchange_info(payload)
            self._rules_at = time.monotonic()
        return dict(self._rules)

    async def hedge_mode(self) -> bool:
        payload = await self._client.get("/fapi/v1/positionSide/dual", signed=True)
        return bool(payload.get("dualSidePosition", False))

    async def account(self) -> AccountState:
        payload = await self._client.get("/fapi/v2/account", signed=True)
        positions: dict[str, Position] = {}
        for row in payload.get("positions", []):
            position = parse_position(row)
            if position is not None:
                positions[position.symbol] = position
        equity = _float(payload.get("totalMarginBalance"))
        initial_margin = _float(payload.get("totalInitialMargin"))
        # Observed on demo-fapi 2026-09-04: totalInitialMargin comes back as 92233720368.54775807, which is
        # int64 max scaled by 1e8 - an overflow sentinel, not a number.  The venue then derives
        # availableBalance and maxWithdrawAmount as 0 from it, which would make the margin scaler drop every
        # risk-adding order while the account is in fact 95% free.  Maintenance margin and margin balance stay
        # sane, so the corruption is detectable: initial margin can never exceed the margin balance.
        reliable = equity <= 0 or initial_margin <= equity
        # L1-10: keep the per-asset breakdown instead of discarding it.  `assets` is already in this
        # payload; without it nobody could tell how much of a drawdown reading was BTC collateral.
        usdt_equity: float | None = None
        for asset in payload.get("assets") or []:
            if str(asset.get("asset", "")).upper() == "USDT":
                usdt_equity = _float(asset.get("marginBalance"))
                break
        return AccountState(
            wallet_balance=_float(payload.get("totalWalletBalance")),
            available_balance=_float(payload.get("availableBalance")),
            equity=equity,
            positions=positions,
            hedge_mode=False,
            can_trade=bool(payload.get("canTrade", True)),
            margin_fields_reliable=reliable,
            usdt_equity=usdt_equity,
        )

    async def positions(self) -> dict[str, Position]:
        payload = await self._client.get("/fapi/v2/positionRisk", signed=True)
        result: dict[str, Position] = {}
        for row in payload:
            position = parse_position(row)
            if position is not None:
                result[position.symbol] = position
        return result

    async def mark_prices(self, symbols: Sequence[str]) -> dict[str, float]:
        wanted = set(symbols)
        payload = await self._client.get("/fapi/v1/premiumIndex")
        return {str(row["symbol"]): _float(row.get("markPrice")) for row in payload if str(row.get("symbol")) in wanted}

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        payload = await self._client.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)})
        return int(_float(payload.get("leverage"), float(leverage)))

    async def leverage_brackets(self) -> dict[str, int]:
        """Maximum initial leverage of the smallest notional tier per symbol (``/fapi/v1/leverageBracket``)."""
        payload = await self._client.get("/fapi/v1/leverageBracket", signed=True)
        out: dict[str, int] = {}
        for row in payload if isinstance(payload, list) else [payload]:
            brackets = row.get("brackets") or []
            if brackets:
                out[str(row.get("symbol", ""))] = int(_float(brackets[0].get("initialLeverage"), 1.0))
        return out

    async def place_order(self, request: OrderRequest) -> OrderAck:
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": request.order_type,
            "quantity": format_decimal(request.quantity),
            "newClientOrderId": request.client_order_id,
            "newOrderRespType": "RESULT",
        }
        if request.reduce_only:
            params["reduceOnly"] = "true"
        payload = await self._client.post("/fapi/v1/order", params)
        return parse_order_ack(payload)

    async def query_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        try:
            payload = await self._client.get(
                "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_order_id}, signed=True
            )
        except VenueError as exc:
            if exc.code == ORDER_NOT_FOUND:
                return None
            raise
        return parse_order_ack(payload)

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        try:
            payload = await self._client.delete(
                "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_order_id}
            )
        except VenueError as exc:
            if exc.code == ORDER_NOT_FOUND:
                return None
            raise
        return parse_order_ack(payload)

    async def open_orders(self, symbol: str | None = None) -> list[OrderAck]:
        params = {"symbol": symbol} if symbol else {}
        payload = await self._client.get("/fapi/v1/openOrders", params, signed=True)
        return [parse_order_ack(row) for row in payload]

    async def income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return await self._paged("/fapi/v1/income", start_ms, end_ms)

    async def user_trades(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Fills in the window, across all symbols (D-032).

        An income row names a ``tradeId`` but not the order that produced it, so income alone cannot tell
        a fill the loop placed from one the operator placed by hand.  A userTrades row carries both ``id``
        (that same trade id) and ``orderId``, which is the join back to what the loop recorded in
        trades.jsonl.  Verified against demo-fapi 2026-09-04: the endpoint accepts a window with no
        ``symbol`` and returned all 68 fills of the hour.
        """
        return await self._paged("/fapi/v1/userTrades", start_ms, end_ms)

    async def force_orders(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Liquidation and ADL orders in the window (DL-X1, the A-P2 half that was never probed).

        Verified against demo-fapi 2026-09-07: the endpoint answers a signed GET with no ``symbol``,
        and an account that has never been liquidated returns ``[]``.  That empty list is the useful
        answer - it is what distinguishes "no liquidations" from "we never looked", which is the state
        this loop was in.

        One GET, not ``_paged``: this endpoint caps ``limit`` at 100 where the paged ones take 1000,
        and a window that returns a full page is not a paging problem to solve quietly - it means
        something happened that reading page two will not explain.
        """
        rows = await self._client.get(
            "/fapi/v1/forceOrders",
            {"startTime": int(start_ms), "endTime": int(end_ms), "limit": FORCE_ORDERS_LIMIT},
            signed=True,
        )
        return list(rows)

    async def margin_mode(self) -> dict[str, Any]:
        """Account collateral mode and the symbols set to ISOLATED margin (KILL-R19).

        Reads the ``isolated`` boolean rather than ``marginType``.  demo-fapi spells that field
        lowercase - ``cross`` / ``isolated``, all 18 open positions checked 2026-09-07 - so the
        obvious ``marginType == "CROSSED"`` assertion would have matched nothing and refused every
        startup, or, written the other way round, refused nothing.  A spelling change is silent; a
        boolean going missing is loud.

        Every row is inspected, including flat ones: margin mode is a per-symbol setting that outlives
        the position, so a symbol that is flat today is still isolated when the book opens it tomorrow.
        """
        multi = await self._client.get("/fapi/v1/multiAssetsMargin", signed=True)
        rows = await self._client.get("/fapi/v2/positionRisk", signed=True)
        isolated = sorted({str(row.get("symbol", "")) for row in rows if bool(row.get("isolated", False))})
        return {"multi_assets": bool(multi.get("multiAssetsMargin", False)), "isolated_symbols": isolated}

    async def _paged(self, path: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Every row of ``[start_ms, end_ms]``, in the order the venue returned them.

        The cursor OVERLAPS: the next page restarts at the last row's own timestamp rather than one
        millisecond past it, and whatever comes back twice is dropped by id.  Stepping to ``last + 1``
        (what this did until 2026-09-13) silently dropped every row that shared the final millisecond
        of a full page, and income shares a millisecond by rule rather than by accident - one funding
        settlement writes one row per held symbol, all stamped with the same ``fundingTime``.  A full
        page lying entirely inside one millisecond was worse: ``last <= cursor`` broke the loop and
        truncated the window there.  Neither case wrote a log line, and these rows are the money -
        D-021 and D-032 attribute from them.

        None of it has been seen yet because a one-hour window on this account does not reach 1,000
        rows.  D-030's first catch-up window and the one after a restart are not one hour.

        Paging stops on an empty page, on a short page, or on a full page that is entirely rows
        already collected, and in any case at ``MAX_PAGES``.  The last two are logged: "the window
        ended" and "this loop stopped asking" are different answers and must not look alike.
        """
        id_field = PAGE_ID_FIELDS.get(path)
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        cursor = int(start_ms)
        for _ in range(MAX_PAGES):
            page = await self._client.get(
                path, {"startTime": cursor, "endTime": int(end_ms), "limit": PAGE_LIMIT}, signed=True
            )
            if not page:
                return rows
            fresh = 0
            for row in page:
                if id_field is not None:
                    # Keyed on the id AND the row behind it.  The id alone is the right key only for as
                    # long as it really is one-per-row, and `tranId` is not obviously that (a single fill
                    # writes a COMMISSION row and a REALIZED_PNL row).  Folding the row in costs nothing
                    # and makes this incapable of dropping anything the venue did not send twice.
                    key = (str(row.get(id_field, "")), json.dumps(row, sort_keys=True, default=str))
                    if key in seen:
                        continue
                    seen.add(key)
                rows.append(row)
                fresh += 1
            if len(page) < PAGE_LIMIT:
                return rows
            last = int(page[-1].get("time", cursor))
            if id_field is None:
                # Nothing to de-duplicate on, so an overlapping cursor would double-count rather than
                # recover them.  Keep the exclusive step: it can still drop rows sharing the last
                # millisecond of a full page, but a caller counting money would rather be short than
                # double, and the warning below says the window was not walked to its end.
                if last <= cursor:
                    break
                cursor = last + 1
                continue
            if fresh == 0:
                # A whole page of rows already held: the venue cannot get past this millisecond and
                # neither can this loop - /fapi/v1/income has no `fromId` to continue from.  Stop
                # rather than spin, and say so.
                break
            cursor = max(last, cursor)
        logger.warning(
            "%s: stopped paging [%d, %d] at cursor %d holding %d row(s); the window may be incomplete",
            path,
            int(start_ms),
            int(end_ms),
            cursor,
            len(rows),
        )
        return rows
