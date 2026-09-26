"""In-memory venue used by live-loop tests.

Semantics mirror Binance USDⓈ-M one-way mode closely enough for the loop's
invariants: step/min-notional validation, immediate market fills at the
configured price, reduce-only clamping, duplicate client-id rejection,
optional ambiguous-outcome injection (the order *does* execute but the call
raises :class:`OrderOutcomeUnknown`) and per-fill income records.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from typing import Any

from starquant_shared.types import (
    AccountState,
    InstrumentRules,
    OrderAck,
    OrderOutcomeUnknown,
    OrderRequest,
    Position,
    Side,
    VenueError,
)

DEFAULT_RULES: dict[str, InstrumentRules] = {
    "BTCUSDT": InstrumentRules("BTCUSDT", Decimal("0.10"), Decimal("0.001"), Decimal("0.001"), Decimal("100")),
    "ETHUSDT": InstrumentRules("ETHUSDT", Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("20")),
    "SOLUSDT": InstrumentRules("SOLUSDT", Decimal("0.0100"), Decimal("1"), Decimal("1"), Decimal("5")),
    "BNBUSDT": InstrumentRules("BNBUSDT", Decimal("0.010"), Decimal("0.01"), Decimal("0.01"), Decimal("5")),
}
DEFAULT_PRICES: dict[str, float] = {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 150.0, "BNBUSDT": 600.0}


class FakeVenue:
    def __init__(
        self,
        *,
        rules: dict[str, InstrumentRules] | None = None,
        balance: float = 10_000.0,
        prices: dict[str, float] | None = None,
        hedge_mode: bool = False,
        fee_rate: float = 0.0005,
    ) -> None:
        self._rules = dict(rules or DEFAULT_RULES)
        self.balance = balance
        self.prices: dict[str, float] = dict(prices or DEFAULT_PRICES)
        self.hedge_mode = hedge_mode
        self.fee_rate = fee_rate
        self.qty: dict[str, float] = {}
        self.entry: dict[str, float] = {}
        self.leverage: dict[str, int] = {}
        self.orders: dict[str, OrderAck] = {}
        self.order_log: list[OrderRequest] = []
        self.income_log: list[dict[str, Any]] = []
        self.unknown_outcomes_to_inject = 0
        self.fill_ratios: dict[str, float] = {}  # symbol -> fraction of the requested qty that fills (T-L04)
        self.errors_to_inject: list[Exception] = []
        self.calls: list[str] = []
        self._next_order_id = 1000

    # --- test helpers -------------------------------------------------
    def inject_unknown_outcome(self, count: int = 1) -> None:
        self.unknown_outcomes_to_inject += count

    def inject_error(self, error: Exception) -> None:
        self.errors_to_inject.append(error)

    def set_price(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price

    def _unrealized(self, symbol: str) -> float:
        qty = self.qty.get(symbol, 0.0)
        if qty == 0.0:
            return 0.0
        return qty * (self.prices[symbol] - self.entry[symbol])

    # --- Venue protocol -----------------------------------------------
    async def rules(self) -> dict[str, InstrumentRules]:
        self.calls.append("rules")
        return dict(self._rules)

    async def account(self) -> AccountState:
        self.calls.append("account")
        positions = await self.positions()
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        margin_used = sum(abs(p.notional) / max(self.leverage.get(p.symbol, 1), 1) for p in positions.values())
        return AccountState(
            wallet_balance=self.balance,
            available_balance=self.balance + unrealized - margin_used,
            equity=self.balance + unrealized,
            positions=positions,
            hedge_mode=self.hedge_mode,
        )

    async def positions(self) -> dict[str, Position]:
        self.calls.append("positions")
        result: dict[str, Position] = {}
        for symbol, qty in self.qty.items():
            if qty == 0.0:
                continue
            result[symbol] = Position(
                symbol=symbol,
                qty=qty,
                entry_price=self.entry[symbol],
                mark_price=self.prices[symbol],
                unrealized_pnl=self._unrealized(symbol),
                leverage=self.leverage.get(symbol, 0),
            )
        return result

    async def mark_prices(self, symbols: Sequence[str]) -> dict[str, float]:
        self.calls.append("mark_prices")
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        self.calls.append(f"set_leverage:{symbol}:{leverage}")
        self.leverage[symbol] = leverage
        return leverage

    async def place_order(self, request: OrderRequest) -> OrderAck:
        self.calls.append(f"place_order:{request.client_order_id}")
        if self.errors_to_inject:
            raise self.errors_to_inject.pop(0)
        if request.client_order_id in self.orders:
            raise VenueError("Duplicate clientOrderId", code=-4116, retryable=False)
        rules = self._rules.get(request.symbol)
        if rules is None or not rules.tradable:
            raise VenueError(f"unknown symbol {request.symbol}", code=-1121)
        if request.quantity % rules.step_size != 0:
            raise VenueError("Precision is over the maximum defined for this asset", code=-1111)
        if request.quantity < rules.min_qty:
            raise VenueError("quantity below minQty", code=-4003)
        price = self.prices[request.symbol]
        current = self.qty.get(request.symbol, 0.0)
        qty = float(request.quantity)
        if request.reduce_only:
            if current == 0.0 or (current > 0) == (request.side is Side.BUY):
                raise VenueError("ReduceOnly Order is rejected", code=-2022)
            qty = min(qty, abs(current))
        elif Decimal(str(price)) * request.quantity < rules.min_notional:
            raise VenueError("Order's notional must be no smaller than minNotional", code=-4164)
        ratio = self.fill_ratios.get(request.symbol, 1.0)
        filled = float(Decimal(str(qty * ratio)).quantize(rules.step_size, rounding=ROUND_DOWN))
        signed = filled * request.side.sign
        self.order_log.append(request)
        if filled > 0:
            self._fill(request.symbol, signed, price)
        self._next_order_id += 1
        ack = OrderAck(
            symbol=request.symbol,
            client_order_id=request.client_order_id,
            order_id=str(self._next_order_id),
            side=request.side,
            # a market order that could not be fully filled comes back CANCELED with a part done
            status="FILLED" if filled >= qty else "CANCELED",
            executed_qty=Decimal(str(filled)).quantize(rules.step_size, rounding=ROUND_DOWN),
            avg_price=price,
            reduce_only=request.reduce_only,
        )
        self.orders[request.client_order_id] = ack
        if self.unknown_outcomes_to_inject > 0:
            self.unknown_outcomes_to_inject -= 1
            raise OrderOutcomeUnknown(
                "timeout after send", client_order_id=request.client_order_id, symbol=request.symbol
            )
        return ack

    def _fill(self, symbol: str, signed_qty: float, price: float) -> None:
        current = self.qty.get(symbol, 0.0)
        new = current + signed_qty
        fee = abs(signed_qty) * price * self.fee_rate
        self.balance -= fee
        self.income_log.append({"symbol": symbol, "incomeType": "COMMISSION", "income": -fee})
        if current != 0.0 and (current > 0) != (signed_qty > 0):
            closed = min(abs(current), abs(signed_qty)) * (1 if current > 0 else -1)
            realized = closed * (price - self.entry[symbol])
            self.balance += realized
            self.income_log.append({"symbol": symbol, "incomeType": "REALIZED_PNL", "income": realized})
        if new == 0.0:
            self.qty.pop(symbol, None)
            self.entry.pop(symbol, None)
            return
        if current == 0.0 or (current > 0) != (new > 0):
            self.entry[symbol] = price
        elif abs(new) > abs(current):
            self.entry[symbol] = (self.entry[symbol] * abs(current) + price * abs(signed_qty)) / abs(new)
        self.qty[symbol] = new

    async def query_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        self.calls.append(f"query_order:{client_order_id}")
        ack = self.orders.get(client_order_id)
        return ack if ack is not None and ack.symbol == symbol else None

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        self.calls.append(f"cancel_order:{client_order_id}")
        return None

    async def open_orders(self, symbol: str | None = None) -> list[OrderAck]:
        self.calls.append("open_orders")
        return []

    async def income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Rows are handed out once (the real endpoint is queried by a moving time cursor)."""
        self.calls.append("income")
        rows, self.income_log = self.income_log, []
        return rows
