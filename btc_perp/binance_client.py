"""USDⓈ-M REST client. Demo and production hosts are fixed and never swapped.

Conditional orders go to ``/fapi/v1/algoOrder``. A ``-4120`` from the plain
order route freezes the caller; it does not retry on the other environment.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from btc_perp.gates import assert_host_matches, hosts
from btc_perp.machine import check_algo_shape
from btc_perp.model import AlgoOrder, Filters, RestingOrder, Snapshot


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        """Return the status code and the body."""


MAX_BODY_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A signed request is never replayed against another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class UrllibTransport:
    def __init__(self) -> None:
        self.last_retry_after: float = 0.0
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        req = urllib.request.Request(url, method=method, headers=dict(headers))
        try:
            with self._opener.open(req, timeout=timeout) as response:
                return int(response.status), _capped(response)
        except urllib.error.HTTPError as exc:
            self.last_retry_after = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            return int(exc.code), _capped(exc)


def _capped(handle: object) -> bytes:
    data: bytes = handle.read(MAX_BODY_BYTES + 1)  # type: ignore[attr-defined]
    if len(data) > MAX_BODY_BYTES:
        raise OSError("交易所响应超过上限")
    return data


def _retry_after(raw: str | None) -> float:
    try:
        return max(float(raw), 0.0) if raw is not None else 0.0
    except ValueError:
        return 0.0


class UnknownExecution(RuntimeError):
    """The write may have reached the exchange. Query the original id."""


class AlgoEndpointRequired(RuntimeError):
    """Plain /order refused a conditional type. Do not change host."""


class WriteRefused(RuntimeError):
    """Nothing was sent: the client is read-only or the request budget is spent."""


def redact(text: str, secrets: tuple[str, ...]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


@dataclass
class UsdMClient:
    environment: str
    api_key: str
    api_secret: str
    transport: Transport
    base_url: str | None = None
    timeout: float = 10.0
    read_only: bool = False

    def __post_init__(self) -> None:
        official, self.ws_base = hosts(self.environment)
        self.base_url = (self.base_url or official).rstrip("/")
        assert_host_matches(self.environment, self.base_url)
        self._offset_ms = 0
        self._rtt_ms = 0
        self._cooldown_until = 0.0
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, ttl: float, load: Callable[[], object]) -> object:
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        value = load()
        self._cache[key] = (now, value)
        return value

    def _signed(
        self,
        path: str,
        params: dict[str, str],
        method: str,
        *,
        priority: bool = False,
    ) -> tuple[int, dict[str, object]]:
        if method in {"POST", "DELETE"} and self.read_only:
            raise WriteRefused("这个客户端是只读的，没有发送任何写请求")
        if time.monotonic() < self._cooldown_until and not priority:
            raise WriteRefused("交易所限流冷却中，本次请求没有发送")
        query = dict(params)
        query["timestamp"] = str(int(time.time() * 1000) + self._offset_ms)
        query["recvWindow"] = "5000"
        payload = urllib.parse.urlencode(query)
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{payload}&signature={signature}"
        try:
            status, body = self.transport.request(
                method,
                url,
                {"X-MBX-APIKEY": self.api_key},
                self.timeout,
            )
        except (TimeoutError, OSError) as exc:
            if method in {"POST", "DELETE"}:
                raise UnknownExecution(redact(str(exc), (self.api_key, self.api_secret))) from exc
            raise
        if status in {418, 429}:
            wait = float(getattr(self.transport, "last_retry_after", 0.0) or 0.0)
            self._cooldown_until = time.monotonic() + (wait if wait > 0 else (120.0 if status == 418 else 30.0))
        text = redact(body.decode("utf-8", "replace"), (self.api_key, self.api_secret))
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            if method in {"POST", "DELETE"}:
                raise UnknownExecution("交易所返回无法解析") from exc
            raise RuntimeError("交易所返回无法解析") from exc
        if not isinstance(parsed, dict):
            return status, {"raw": parsed}
        if parsed.get("code") == -4120:
            raise AlgoEndpointRequired("条件单必须走 /fapi/v1/algoOrder，不会改域名重试")
        return status, parsed

    def _read(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
        """A signed GET whose failure is an error. An empty list stays a valid empty answer."""
        status, parsed = self._signed(path, dict(params or {}), "GET")
        code = parsed.get("code")
        if status >= 400 or (isinstance(code, int | float) and not isinstance(code, bool) and code < 0):
            raise RuntimeError(f"{path} -> HTTP {status} code={code}")
        return parsed

    def _public(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        status, body = self.transport.request("GET", url, {}, self.timeout)
        if status >= 400:
            raise RuntimeError(f"{path} -> {status}")
        parsed = json.loads(body.decode("utf-8", "replace") or "{}")
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}

    def sync_time(self) -> int:
        started = time.time() * 1000
        payload = self._public("/fapi/v1/time")
        finished = time.time() * 1000
        server = _int(payload.get("serverTime"))
        self._rtt_ms = max(int(finished - started), 0)
        self._offset_ms = int(server - (started + finished) / 2)
        return server

    def _write(self, path: str, params: dict[str, str], method: str, *, priority: bool) -> dict[str, object]:
        status, parsed = self._signed(path, params, method, priority=priority)
        if status >= 500 or status == 429 or status == 418 or status == 0:
            raise UnknownExecution(f"{path} -> {status}")
        if status >= 400 and "code" not in parsed:
            raise UnknownExecution(f"{path} -> {status}")
        return parsed

    def place_market(self, *, client_id: str, side: str, qty: str, reduce_only: bool) -> dict[str, object]:
        if not client_id or not qty or qty == "0":
            raise ValueError("市价单需要客户端身份和数量")
        return self._write(
            "/fapi/v1/order",
            {
                "symbol": "BTCUSDT",
                "side": side,
                "type": "MARKET",
                "quantity": qty,
                "reduceOnly": "true" if reduce_only else "false",
                "newClientOrderId": client_id,
                "positionSide": "BOTH",
                "newOrderRespType": "RESULT",
            },
            "POST",
            priority=reduce_only,
        )

    def place_algo(
        self,
        *,
        client_id: str,
        side: str,
        order_type: str,
        trigger_price: str,
        close_position: bool,
        qty: str = "",
        reduce_only: bool = False,
    ) -> dict[str, object]:
        if order_type not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            raise ValueError("只通过 Algo 接口发送止损和止盈市价单")
        check_algo_shape(close_position=close_position, qty=qty, reduce_only=reduce_only)
        params = {
            "algoType": "CONDITIONAL",
            "symbol": "BTCUSDT",
            "side": side,
            "type": order_type,
            "triggerPrice": trigger_price,
            "workingType": "CONTRACT_PRICE",
            "clientAlgoId": client_id,
            "positionSide": "BOTH",
        }
        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = qty
            params["reduceOnly"] = "true"
        return self._write("/fapi/v1/algoOrder", params, "POST", priority=True)

    def cancel_order(self, client_id: str) -> dict[str, object]:
        return self._write(
            "/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": client_id}, "DELETE", priority=True
        )

    def cancel_algo(self, client_id: str) -> dict[str, object]:
        return self._write("/fapi/v1/algoOrder", {"clientAlgoId": client_id}, "DELETE", priority=True)

    def query_order(self, client_id: str) -> dict[str, object]:
        return self._signed("/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": client_id}, "GET")[1]

    def query_algo(self, client_id: str) -> dict[str, object]:
        return self._signed("/fapi/v1/algoOrder", {"clientAlgoId": client_id}, "GET")[1]

    def create_listen_key(self) -> str:
        parsed = self._listen("POST")
        key = parsed.get("listenKey")
        if not isinstance(key, str) or not key:
            raise RuntimeError("listenKey 缺失")
        return key

    def keepalive_listen_key(self) -> None:
        self._listen("PUT")

    def close_listen_key(self) -> None:
        self._listen("DELETE")

    def _listen(self, method: str) -> dict[str, object]:
        url = f"{self.base_url}/fapi/v1/listenKey"
        try:
            status, body = self.transport.request(method, url, {"X-MBX-APIKEY": self.api_key}, self.timeout)
        except (TimeoutError, OSError) as exc:
            raise RuntimeError(redact(str(exc), (self.api_key, self.api_secret))) from exc
        text = redact(body.decode("utf-8", "replace"), (self.api_key, self.api_secret))
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError("listenKey 响应无法解析") from exc
        if not isinstance(parsed, dict) or status >= 400 or parsed.get("code") not in (None, 0):
            raise RuntimeError("listenKey 请求失败")
        return parsed

    def klines(self, interval: str, limit: int, start_ms: int | None = None) -> list[object]:
        params = {"symbol": "BTCUSDT", "interval": interval, "limit": str(limit)}
        if start_ms is not None:
            params["startTime"] = str(start_ms)
        payload = self._public("/fapi/v1/klines", params)
        raw = payload.get("raw")
        if isinstance(raw, list):
            return raw
        return []

    def snapshot(self) -> Snapshot:
        try:
            for _attempt in range(3):
                built = self._read_once()
                if built is not None:
                    break
            else:
                return _unknown("读取期间账户一直在变化，快照不可信")
        except UnknownExecution:
            return _unknown("签名请求超时，结果未知")
        except WriteRefused as exc:
            return _unknown(str(exc))
        except (OSError, TimeoutError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            return _unknown(redact(str(exc), (self.api_key, self.api_secret))[:300])
        if not built.known:
            return built
        last = self._last_price()
        fee, brackets, trades, funding = self._slow_checks()
        return dataclasses.replace(
            built,
            last_price=last,
            fee_taker=fee,
            brackets_ok=brackets,
            recent_trades_ok=trades,
            funding_ok=funding,
            clock_offset_ms=self._offset_ms,
            clock_rtt_ms=self._rtt_ms,
        )

    def _read_once(self) -> Snapshot | None:
        """One pass over the account endpoints. ``None`` means the account moved while reading."""
        server = self.sync_time()
        info = self._cached("exchangeInfo", 60.0, lambda: self._public("/fapi/v1/exchangeInfo", {"symbol": "BTCUSDT"}))
        dual = self._cached("dual", 30.0, lambda: self._read("/fapi/v1/positionSide/dual"))
        account = self._read("/fapi/v2/account")
        orders = self._read("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
        algos = self._read("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"})
        positions = self._read("/fapi/v2/positionRisk", {"symbol": "BTCUSDT"})
        built = _snapshot_from(server, info, account, dual, orders, algos, positions)  # type: ignore[arg-type]
        if not built.known:
            return built
        again_positions = self._read("/fapi/v2/positionRisk", {"symbol": "BTCUSDT"})
        again_orders = self._read("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
        if _moved(positions, again_positions) or _order_key(orders) != _order_key(again_orders):
            return None
        return built

    def _last_price(self) -> float:
        try:
            ticker = self._public("/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        except (OSError, TimeoutError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, ValueError):
            return 0.0
        value = _num(ticker.get("price"))
        return value if value is not None and value > 0 else 0.0

    def _slow_checks(self) -> tuple[float | None, bool, bool, bool]:
        """Fee, brackets, trades, and income change slowly. A good answer is reused for five minutes."""

        def fee() -> object:
            found = self._optional_fee()
            if found is None:
                raise LookupError
            return found

        def probe(path: str, params: dict[str, str]) -> Callable[[], object]:
            def run() -> object:
                if not self._optional_ok(path, params):
                    raise LookupError
                return True

            return run

        def keep(key: str, load: Callable[[], object]) -> object | None:
            try:
                return self._cached(key, 300.0, load)
            except LookupError:
                return None

        rate = keep("fee", fee)
        return (
            float(rate) if isinstance(rate, float) else None,
            keep("brackets", probe("/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"})) is True,
            keep("trades", probe("/fapi/v1/userTrades", {"symbol": "BTCUSDT", "limit": "5"})) is True,
            keep(
                "income",
                probe("/fapi/v1/income", {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "limit": "5"}),
            )
            is True,
        )

    def _optional_fee(self) -> float | None:
        try:
            body = self._read("/fapi/v1/commissionRate", {"symbol": "BTCUSDT"})
        except (UnknownExecution, WriteRefused, OSError, TimeoutError, RuntimeError, json.JSONDecodeError):
            return None
        rate = _num(body.get("takerCommissionRate"))
        return rate if rate is not None and 0.0 <= rate < 0.01 else None

    def _optional_ok(self, path: str, params: dict[str, str]) -> bool:
        try:
            self._read(path, params)
        except (UnknownExecution, WriteRefused, OSError, TimeoutError, RuntimeError, json.JSONDecodeError):
            return False
        return True


def _unknown(reason: str) -> Snapshot:
    return Snapshot(
        known=False,
        reason=reason,
        position_qty=0.0,
        entry_price=0.0,
        wallet_usdt=0.0,
        available_usdt=0.0,
        mark_price=0.0,
        last_price=0.0,
        liquidation_price=0.0,
        one_way=False,
        isolated=False,
        leverage=0,
        symbol_status="",
        server_time_ms=0,
    )


def _rows(payload: object) -> list[dict[str, object]]:
    """A list endpoint answer. A dict that is not a wrapped list is an error, not an empty list."""
    if isinstance(payload, dict):
        for key in ("raw", "orders"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("交易所返回的不是订单列表")


def _moved(first: object, second: object) -> bool:
    def key(payload: object) -> list[tuple[str, str, str]]:
        return sorted(
            (str(r.get("symbol")), str(r.get("positionAmt")), str(r.get("entryPrice"))) for r in _rows(payload)
        )

    return key(first) != key(second)


def _order_key(payload: object) -> list[tuple[str, str, str]]:
    return sorted(
        (str(r.get("clientOrderId")), str(r.get("status")), str(r.get("executedQty"))) for r in _rows(payload)
    )


def _snapshot_from(
    server: int,
    info: dict[str, object],
    account: dict[str, object],
    dual: dict[str, object],
    orders: dict[str, object],
    algos: dict[str, object],
    positions: dict[str, object],
) -> Snapshot:
    symbols = info.get("symbols")
    if not isinstance(symbols, list):
        return _unknown("exchangeInfo 没有 symbols")
    matches = [
        item
        for item in symbols
        if isinstance(item, dict)
        and item.get("symbol") == "BTCUSDT"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
    ]
    if len(matches) != 1:
        return _unknown(f"exchangeInfo 里 BTCUSDT 永续有 {len(matches)} 条，需要恰好一条")
    symbol = matches[0]
    raw_filters = symbol.get("filters")
    if not isinstance(raw_filters, list):
        return _unknown("过滤器缺失")
    filters = {str(item.get("filterType")): item for item in raw_filters if isinstance(item, dict)}
    lot = filters.get("LOT_SIZE")
    market_lot = filters.get("MARKET_LOT_SIZE") or lot
    price = filters.get("PRICE_FILTER")
    notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
    if not (isinstance(lot, dict) and isinstance(market_lot, dict) and isinstance(price, dict)):
        return _unknown("过滤器缺失")
    if not isinstance(notional, dict):
        return _unknown("过滤器缺失")
    tick = _num(price.get("tickSize"))
    step = _num(lot.get("stepSize"))
    min_qty = _num(lot.get("minQty"))
    min_notional = _num(notional.get("notional"))
    if tick is None or step is None or min_qty is None or min_notional is None:
        return _unknown("过滤器字段不是有限数字")
    parsed_filters = Filters(
        tick_size=tick,
        step_size=step,
        min_qty=min_qty,
        min_notional=min_notional,
        min_price=_num(price.get("minPrice")) or 0.0,
        max_price=_num(price.get("maxPrice")) or 0.0,
        max_qty=_num(market_lot.get("maxQty")) or 0.0,
    )

    pos_rows = [row for row in _rows(positions) if row.get("symbol") == "BTCUSDT"]
    one_way = not bool(dual.get("dualSidePosition"))
    if one_way:
        pos_rows = [row for row in pos_rows if str(row.get("positionSide", "BOTH")) == "BOTH"]
        if len(pos_rows) != 1:
            return _unknown(f"positionRisk 里 BTCUSDT 单向行有 {len(pos_rows)} 条，需要恰好一条")
    elif not pos_rows:
        return _unknown("positionRisk 里没有 BTCUSDT")
    row = pos_rows[0]
    qty = _num(row.get("positionAmt"))
    entry = _num(row.get("entryPrice"))
    mark = _num(row.get("markPrice"))
    liquidation = _num(row.get("liquidationPrice")) or 0.0
    if qty is None or entry is None or mark is None:
        return _unknown("持仓字段不是有限数字")

    resting = tuple(
        RestingOrder(
            client_id=str(item.get("clientOrderId", "")),
            side=str(item.get("side", "")),
            order_type=str(item.get("type", "")),
            qty=_f(item.get("origQty")),
            filled=_f(item.get("executedQty")),
            reduce_only=str(item.get("reduceOnly", "")).lower() == "true",
            status=str(item.get("status", "")),
            price=_f(item.get("price")),
        )
        for item in _rows(orders)
        if item.get("symbol", "BTCUSDT") == "BTCUSDT"
    )
    algo_rows = tuple(
        AlgoOrder(
            client_algo_id=str(item.get("clientAlgoId", "")),
            order_type=str(item.get("orderType", item.get("type", ""))),
            side=str(item.get("side", "")),
            trigger_price=_f(item.get("triggerPrice")),
            close_position=str(item.get("closePosition", "")).lower() == "true",
            reduce_only=str(item.get("reduceOnly", "")).lower() == "true",
            qty=_f(item.get("quantity")),
            status=str(item.get("algoStatus", item.get("status", ""))),
            working_type=str(item.get("workingType", "")),
        )
        for item in _rows(algos)
        if item.get("symbol", "BTCUSDT") == "BTCUSDT"
    )

    assets = account.get("assets")
    usdt = None
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("asset") == "USDT":
                usdt = asset
    if usdt is None:
        return _unknown("账户里读不到 USDT 资产")
    wallet = _num(usdt.get("walletBalance"))
    available = _num(usdt.get("availableBalance"))
    if wallet is None or available is None:
        return _unknown("USDT 余额不是有限数字")
    others: list[str] = []
    all_positions = account.get("positions")
    if isinstance(all_positions, list):
        for item in all_positions:
            if not isinstance(item, dict) or item.get("symbol") == "BTCUSDT":
                continue
            amount = _num(item.get("positionAmt"))
            if amount is None or amount != 0.0:
                others.append(str(item.get("symbol", "?")))
    return Snapshot(
        known=True,
        reason="",
        position_qty=qty,
        entry_price=entry,
        wallet_usdt=wallet,
        available_usdt=available,
        mark_price=mark,
        last_price=0.0,
        liquidation_price=liquidation,
        one_way=one_way,
        isolated=str(row.get("marginType", "")).lower() == "isolated",
        leverage=int(_num(row.get("leverage")) or 0),
        symbol_status=str(symbol.get("status", "")),
        server_time_ms=server,
        orders=resting,
        algos=algo_rows,
        can_trade=bool(account.get("canTrade")),
        fee_taker=None,
        filters=parsed_filters,
        other_exposure=",".join(others[:5]),
        multi_assets=bool(account.get("multiAssetsMargin")),
    )


def _num(value: object) -> float | None:
    """A finite number, or ``None``. Booleans, blanks, NaN, and infinity are not numbers."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: object) -> int:
    number = _num(value)
    if number is None:
        raise ValueError("时间字段不是有限数字")
    return int(number)


def _f(value: object, default: float = 0.0) -> float:
    number = _num(value)
    return default if number is None else number


def account_problems(snapshot: Snapshot, filters_ok: bool) -> str:
    if not snapshot.known:
        return snapshot.reason or "账户未知"
    if snapshot.symbol_status != "TRADING":
        return "BTCUSDT 不在交易状态"
    if not snapshot.one_way:
        return "账户不是单向持仓"
    if not snapshot.isolated:
        return "BTCUSDT 不是逐仓"
    if snapshot.leverage != 20:
        return f"杠杆是 {snapshot.leverage}，配置是 20，不会自动修改"
    if snapshot.multi_assets:
        return "账户是联合保证金模式，不在这个程序的模型内"
    if snapshot.other_exposure:
        return "账户在别的合约上有持仓：" + snapshot.other_exposure
    if not snapshot.can_trade:
        return "API 没有交易权限"
    if not filters_ok:
        return "交易所过滤器不可用"
    return ""
