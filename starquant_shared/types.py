"""Shared value types.

Only plain dataclasses, enums and exceptions live here.  Nothing in this
module performs I/O or imports third-party packages, so every other package
can depend on it without inheriting anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

TERMINAL_ORDER_STATUSES: frozenset[str] = frozenset({"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"})


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY

    @staticmethod
    def for_delta(delta_qty: float) -> Side:
        """Side that moves a position by ``delta_qty`` base units."""
        return Side.BUY if delta_qty > 0 else Side.SELL


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    """Venue trading rules for one symbol (from exchangeInfo filters)."""

    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    status: str = "TRADING"
    contract_type: str = "PERPETUAL"
    quote_asset: str = "USDT"

    @property
    def tradable(self) -> bool:
        return self.status == "TRADING" and self.contract_type == "PERPETUAL"


@dataclass(frozen=True, slots=True)
class Position:
    """Signed position in base units; ``qty > 0`` is long."""

    symbol: str
    qty: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float = 0.0
    leverage: int = 0
    venue_notional: float | None = None  # the venue's own figure, when it supplies one
    # None means "no reachable liquidation at this equity", which is what the venue reports as 0 for
    # a cross-margin long (measured 2026-09-06: 14/14 longs zero, 4/4 shorts non-zero).  Reading that
    # zero as a price would put every long at distance zero forever (DL-X1).
    liquidation_price: float | None = None

    @property
    def notional(self) -> float:
        """Signed notional: the venue's own number when given, else qty x mark.

        demo-fapi's /fapi/v2/account rows carry a correct ``notional`` but no
        ``markPrice``, so deriving it from the mark silently produced zero for every
        account-derived position - which is why ``gross_notional()`` read 0 while
        fifteen positions were open.
        """
        if self.venue_notional is not None:
            return self.venue_notional
        return self.qty * self.mark_price

    @property
    def is_flat(self) -> bool:
        return self.qty == 0.0


@dataclass(frozen=True, slots=True)
class AccountState:
    """Account facts read from the venue in one signed query."""

    wallet_balance: float
    available_balance: float
    equity: float
    positions: dict[str, Position]
    hedge_mode: bool = False
    can_trade: bool = True
    # False when the venue's margin arithmetic is self-inconsistent, so ``available_balance`` cannot be
    # trusted and a caller holding the real positions must compute the margin headroom itself.
    margin_fields_reliable: bool = True
    # L1-10: the USDT slice of `equity`.  On multi-assets margin the rest is collateral valued at mark,
    # so it moves with BTC on bars the book did nothing.  Reported, never subtracted from what the book
    # sizes on - that denominator is a construction decision, not a parsing one.  ``None`` when the venue
    # did not report a per-asset breakdown, because 0.0 would read as "all of it is collateral".
    usdt_equity: float | None = None

    def gross_notional(self) -> float:
        return sum(abs(position.notional) for position in self.positions.values())


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str
    side: Side
    quantity: Decimal
    client_order_id: str
    reduce_only: bool = False
    order_type: str = "MARKET"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not self.client_order_id or len(self.client_order_id) > 36:
            raise ValueError("client_order_id must be 1..36 characters")


@dataclass(frozen=True, slots=True)
class OrderAck:
    symbol: str
    client_order_id: str
    order_id: str
    side: Side
    status: str
    executed_qty: Decimal
    avg_price: float
    reduce_only: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ORDER_STATUSES

    @property
    def filled(self) -> bool:
        return self.executed_qty > 0


class VenueError(Exception):
    """A venue call failed with a known outcome (nothing ambiguous happened)."""

    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OrderOutcomeUnknown(VenueError):
    """A write was sent but its outcome is unknown (timeout after send, 5xx)."""

    def __init__(self, message: str, *, client_order_id: str, symbol: str) -> None:
        super().__init__(message, retryable=False)
        self.client_order_id = client_order_id
        self.symbol = symbol
