"""In-process paper venue: real market data in, simulated fills at the current mark price, no exchange writes.

Used by ``starquant live run --paper`` so the whole loop (targets -> plan ->
execute -> reconcile -> attribute -> report) can run 24h without credentials.
Marks come from the market-data feed's latest closed bars, so paper equity
tracks mainnet prices.  It is NOT a substitute for demo execution evidence.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from starquant_shared.binance_rules import parse_exchange_info
from starquant_shared.types import (
    AccountState,
    InstrumentRules,
    OrderAck,
    OrderRequest,
    Position,
    Side,
    VenueError,
)


class PaperVenue:
    def __init__(
        self,
        *,
        rules: dict[str, InstrumentRules],
        balance: float = 10_000.0,
        fee_rate: float = 0.0005,
        state_path: Path | None = None,
    ) -> None:
        self._rules = dict(rules)
        self.balance = balance
        self.fee_rate = fee_rate
        self.prices: dict[str, float] = {}
        self.qty: dict[str, float] = {}
        self.entry: dict[str, float] = {}
        self.leverage: dict[str, int] = {}
        self.orders: dict[str, OrderAck] = {}
        self.income_log: list[dict[str, Any]] = []
        self._state_path = state_path
        self._next_id = 1
        if state_path is not None and state_path.exists():
            self._load(state_path)

    @classmethod
    def from_exchange_info(cls, payload: dict[str, Any], **kwargs: Any) -> PaperVenue:
        return cls(rules=parse_exchange_info(payload), **kwargs)

    # --- persistence ----------------------------------------------------------
    def _load(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        self.balance = float(payload.get("balance", self.balance))
        self.qty = {k: float(v) for k, v in payload.get("qty", {}).items()}
        self.entry = {k: float(v) for k, v in payload.get("entry", {}).items()}
        self.prices = {k: float(v) for k, v in payload.get("prices", {}).items()}
        self._next_id = int(payload.get("next_id", 1))
        self.orders = {
            k: OrderAck(**{**v, "side": Side(v["side"]), "executed_qty": Decimal(str(v["executed_qty"]))})
            for k, v in payload.get("orders", {}).items()
        }

    def save(self) -> None:
        if self._state_path is None:
            return
        payload = {
            "balance": self.balance,
            "qty": self.qty,
            "entry": self.entry,
            "prices": self.prices,
            "next_id": self._next_id,
            "orders": {
                k: {
                    "symbol": a.symbol,
                    "client_order_id": a.client_order_id,
                    "order_id": a.order_id,
                    "side": a.side.value,
                    "status": a.status,
                    "executed_qty": str(a.executed_qty),
                    "avg_price": a.avg_price,
                    "reduce_only": a.reduce_only,
                }
                for k, a in list(self.orders.items())[-2000:]
            },
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._state_path)

    # --- marks ----------------------------------------------------------------
    def mark(self, prices: dict[str, float]) -> None:
        self.prices.update({k: float(v) for k, v in prices.items() if v})

    def _unrealized(self, symbol: str) -> float:
        qty = self.qty.get(symbol, 0.0)
        return 0.0 if qty == 0.0 else qty * (self.prices.get(symbol, self.entry[symbol]) - self.entry[symbol])

    # --- Venue protocol --------------------------------------------------------
    async def rules(self) -> dict[str, InstrumentRules]:
        return dict(self._rules)

    async def account(self) -> AccountState:
        positions = await self.positions()
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        margin = sum(abs(p.notional) / max(self.leverage.get(p.symbol, 1), 1) for p in positions.values())
        return AccountState(self.balance, self.balance + unrealized - margin, self.balance + unrealized, positions)

    async def positions(self) -> dict[str, Position]:
        return {
            symbol: Position(
                symbol,
                qty,
                self.entry[symbol],
                self.prices.get(symbol, self.entry[symbol]),
                self._unrealized(symbol),
                self.leverage.get(symbol, 0),
            )
            for symbol, qty in self.qty.items()
            if qty != 0.0
        }

    async def mark_prices(self, symbols: Sequence[str]) -> dict[str, float]:
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        self.leverage[symbol] = leverage
        return leverage

    async def place_order(self, request: OrderRequest) -> OrderAck:
        if request.client_order_id in self.orders:
            raise VenueError("Duplicate clientOrderId", code=-4116)
        rule = self._rules.get(request.symbol)
        price = self.prices.get(request.symbol)
        if rule is None or price is None:
            raise VenueError(f"no rules/price for {request.symbol}", code=-1121)
        qty = float(request.quantity)
        current = self.qty.get(request.symbol, 0.0)
        if request.reduce_only:
            if current == 0.0 or (current > 0) == (request.side is Side.BUY):
                raise VenueError("ReduceOnly Order is rejected", code=-2022)
            qty = min(qty, abs(current))
        elif Decimal(str(price)) * request.quantity < rule.min_notional:
            raise VenueError("Order's notional must be no smaller than minNotional", code=-4164)
        self._fill(request.symbol, qty * request.side.sign, price)
        ack = OrderAck(
            request.symbol,
            request.client_order_id,
            str(self._next_id),
            request.side,
            "FILLED",
            Decimal(str(qty)).quantize(rule.step_size, rounding=ROUND_DOWN),
            price,
            request.reduce_only,
        )
        self._next_id += 1
        self.orders[request.client_order_id] = ack
        self.save()
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
        if abs(new) < 1e-12:
            self.qty.pop(symbol, None)
            self.entry.pop(symbol, None)
            return
        if current == 0.0 or (current > 0) != (new > 0):
            self.entry[symbol] = price
        elif abs(new) > abs(current):
            self.entry[symbol] = (self.entry[symbol] * abs(current) + price * abs(signed_qty)) / abs(new)
        self.qty[symbol] = new

    async def query_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        ack = self.orders.get(client_order_id)
        return ack if ack is not None and ack.symbol == symbol else None

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderAck | None:
        return None

    async def open_orders(self, symbol: str | None = None) -> list[OrderAck]:
        return []

    async def income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        rows, self.income_log = self.income_log, []
        return rows
