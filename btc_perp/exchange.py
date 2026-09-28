"""In-process venue used by the historical session mirror.

The forward Demo and production adapter is ``btc_perp.binance_client``. This
simulator does not speak to Binance. ``BinanceExchange`` remains a closed stub
so an old import cannot send an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _step(qty: float) -> float:
    # Lot size is 0.001. Truncate toward zero, but a value that is already on a
    # lot can be a hair under that lot in float (0.008 * 1000 is not 8).
    scaled = qty * 1000.0
    nearest = round(scaled)
    if abs(scaled - nearest) < 1e-4:
        scaled = nearest
    return float(int(scaled) / 1000.0)


@dataclass
class Protection:
    kind: str  # "stop" or "take_profit"
    side: int
    qty: float
    price: float
    active: bool = True
    close_position: bool = True
    reduce_only: bool = False
    trigger_source: str = "contract"


@dataclass
class AccountView:
    connected: bool
    known: bool
    position_qty: float
    protections: tuple[Protection, ...]
    free_qty_unprotected: float


@dataclass
class SimExchange:
    """In-process venue. Protections live here, not in the session process."""

    partial_ratio: float = 1.0
    defer_remainder: bool = False
    connected: bool = True
    wallet_known: bool = True
    orders_known: bool = True
    position_qty: float = 0.0
    protections: list[Protection] = field(default_factory=list)
    late: list[tuple[int, float, float, float]] = field(default_factory=list)
    submits: int = 0

    def healthy(self) -> bool:
        return self.connected and self.wallet_known and self.orders_known

    def view(self) -> AccountView:
        covered = sum(p.qty for p in self.protections if p.kind == "stop")
        exposed = max(0.0, abs(self.position_qty) - covered)
        known = self.healthy() and self.protection_covers_position()
        return AccountView(self.connected, known, self.position_qty, tuple(self.protections), exposed)

    def protection_covers_position(self) -> bool:
        # A remainder that has not printed yet is an open order. The book is
        # not covered, long or flat, until that print arrives.
        if self.late:
            return False
        net = abs(self.position_qty)
        if net < 0.001:
            return not self.protections
        stops = [p for p in self.protections if p.kind == "stop"]
        takes = [p for p in self.protections if p.kind == "take_profit"]
        if len(stops) != 1 or len(takes) != 1:
            return False
        pos_side = 1 if self.position_qty > 0 else -1
        stop, take = stops[0], takes[0]
        for order in (stop, take):
            if order.side != pos_side or order.price <= 0.0 or not order.active:
                return False
            if not order.close_position and not order.reduce_only:
                return False
            if abs(order.qty - net) >= 1e-9:
                return False
            if order.trigger_source not in {"contract", "mark"}:
                return False
        if pos_side > 0:
            return stop.price < take.price
        return stop.price > take.price

    def submit_market(self, side: int, qty: float, stop: float, take_profit: float) -> float:
        if not self.connected:
            raise ConnectionError("exchange disconnected")
        if not self.wallet_known or not self.orders_known:
            raise RuntimeError("account state is not known")
        self.submits += 1
        qty = _step(qty)
        filled = _step(qty * self.partial_ratio)
        if filled >= 0.001:
            self._apply(side, filled, stop, take_profit)
        remain = _step(qty - filled)
        if remain >= 0.001 and self.defer_remainder:
            self.late.append((side, remain, stop, take_profit))
        return filled

    def deliver_late_fills(self) -> None:
        if not self.connected or not self.late:
            return
        pending = self.late
        self.late = []
        for side, qty, stop, take_profit in pending:
            self._apply(side, qty, stop, take_profit)

    def update_protection(self, stop: float, take_profit: float) -> None:
        if not self.connected:
            raise ConnectionError("exchange disconnected")
        net = abs(self.position_qty)
        if net < 0.001:
            return
        side = 1 if self.position_qty > 0 else -1
        self.protections = [
            Protection("stop", side, net, stop),
            Protection("take_profit", side, net, take_profit),
        ]

    def disconnect(self) -> None:
        self.connected = False
        self.wallet_known = False
        self.orders_known = False

    def reconnect(self) -> None:
        self.connected = True
        self.wallet_known = True
        self.orders_known = True

    def _apply(self, side: int, qty: float, stop: float, take_profit: float) -> None:
        self.position_qty = _step(self.position_qty + side * qty)
        net = abs(self.position_qty)
        if net < 0.001:
            self.position_qty = 0.0
            self.protections = []
            return
        pside = 1 if self.position_qty > 0 else -1
        self.protections = [
            Protection("stop", pside, net, stop),
            Protection("take_profit", pside, net, take_profit),
        ]


class BinanceExchange:
    """Research adapter. It never sends an order."""

    def allowed(self) -> bool:
        return False

    def submit_market(self, side: int, qty: float, stop: float, take_profit: float) -> float:
        raise RuntimeError("这个旧接口不会发送订单。前向订单走 btc_perp.binance_client，生产闸默认关闭")
