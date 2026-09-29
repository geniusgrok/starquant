"""Shared records for the forward account. No network and no strategy parameters."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Filters:
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float
    min_price: float
    max_price: float
    max_qty: float = 0.0


@dataclass(frozen=True)
class AlgoOrder:
    client_algo_id: str
    order_type: str
    side: str
    trigger_price: float
    close_position: bool
    reduce_only: bool
    qty: float
    status: str
    working_type: str


@dataclass(frozen=True)
class RestingOrder:
    client_id: str
    side: str
    order_type: str
    qty: float
    filled: float
    reduce_only: bool
    status: str
    price: float = 0.0
    order_id: str = ""


@dataclass(frozen=True)
class Trade:
    """One own fill from the exchange, used to say who moved the position."""

    trade_id: int
    order_id: str
    side: str
    qty: float
    time_ms: int


@dataclass(frozen=True)
class Income:
    """One income row. Transfers and deposits are not something this program does."""

    kind: str
    amount: float
    time_ms: int


@dataclass(frozen=True)
class Snapshot:
    """One REST read of the account. ``known`` is false when the read failed."""

    known: bool
    reason: str
    position_qty: float
    entry_price: float
    wallet_usdt: float
    available_usdt: float
    mark_price: float
    last_price: float
    liquidation_price: float
    one_way: bool
    isolated: bool
    leverage: int
    symbol_status: str
    server_time_ms: int
    orders: tuple[RestingOrder, ...] = ()
    algos: tuple[AlgoOrder, ...] = ()
    can_trade: bool = False
    fee_taker: float | None = None
    filters: Filters | None = None
    brackets_ok: bool = False
    recent_trades_ok: bool = False
    funding_ok: bool = False
    clock_offset_ms: int | None = None
    clock_rtt_ms: int | None = None
    other_exposure: str = ""
    multi_assets: bool = False
    auto_add_margin_off: bool = False
    trades: tuple[Trade, ...] = ()
    income: tuple[Income, ...] = ()
    read_ms: int = 0

    @property
    def position_side(self) -> int:
        if self.position_qty > 0:
            return 1
        if self.position_qty < 0:
            return -1
        return 0


@dataclass
class Intent:
    client_id: str
    action: str
    phase: str
    side: str
    qty: str
    reduce_only: bool
    close_position: bool
    trigger_price: str
    environment: str
    created_ms: int
    note: str = ""
    attempts: int = 1
    absorbed: bool = True
    order_id: str = ""
    executed: str = ""


@dataclass
class Command:
    op: str
    client_id: str
    side: str = ""
    qty: str = ""
    reduce_only: bool = False
    close_position: bool = False
    trigger_price: str = ""
    order_type: str = ""
    working_type: str = "CONTRACT_PRICE"


@dataclass
class Book:
    """Strategy memory. The exchange snapshot is the position; this is the rest."""

    side: int = 0
    qty: float = 0.0
    entry: float = 0.0
    units: int = 0
    extreme: float = 0.0
    last_add: float = 0.0
    stop: float = 0.0
    cooldown_until_ms: int = 0
    peak_equity_cny: float = 0.0
    close_peak_cny: float = 0.0
    cursor_ms: int = 0
    entries_frozen: bool = False
    freeze_reason: str = ""
    unprotected_since_ms: int | None = None
    day_key: str = ""
    day_realized_usdt: float = 0.0
    manual: bool = False
    dd_locked: bool = False
    swaps: dict[str, str] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Limits:
    capital_usdt: float | None
    max_notional_usdt: float | None
    max_daily_loss_usdt: float | None
    max_unprotected_seconds: int | None


@dataclass(frozen=True)
class Action:
    kind: str
    side: int = 0
    qty: float = 0.0
    stop: float = 0.0
    disaster_take: float = 0.0
    reason: str = ""
    scale: float = 1.0
