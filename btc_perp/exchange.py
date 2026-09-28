"""Exchange surface for one one-way isolated BTCUSDT account.

The simulator is the stand-in used for fill, protection, disconnect, and late-fill
checks. The Binance adapter does not send orders: live trading stays closed until
the full-sample measurement and these checks have both passed, and a key exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _step(qty: float) -> float:
    return float(int(qty * 1000.0 + 1e-9) / 1000.0)


@dataclass
class Protection:
    kind: str  # "stop" or "take_profit"
    side: int
    qty: float
    price: float


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
        net = abs(self.position_qty)
        if net < 0.001:
            return not self.protections and not self.late
        stops = [p for p in self.protections if p.kind == "stop"]
        takes = [p for p in self.protections if p.kind == "take_profit"]
        if len(stops) != 1 or len(takes) != 1:
            return False
        return abs(stops[0].qty - net) < 1e-9 and abs(takes[0].qty - net) < 1e-9

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
    """Research adapter. It never sends an order.

    The constructor still accepts the old gate flags so existing call sites keep
    working. ``allowed`` does not consult them: live trading is prohibited by
    LICENSE, not deferred until a later check.
    """

    def __init__(self, live_orders: bool, measurement_passed: bool, checks_passed: bool, api_key: str | None):
        self.live_orders = live_orders
        self.measurement_passed = measurement_passed
        self.checks_passed = checks_passed
        self.api_key = api_key

    def allowed(self) -> bool:
        return False

    def submit_market(self, side: int, qty: float, stop: float, take_profit: float) -> float:
        raise RuntimeError("live orders are disabled: this project is private research and must not send live orders")
