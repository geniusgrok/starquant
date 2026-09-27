"""Venue truth: account, positions, prices, foreign positions and stale open orders."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from starquant_live.ports import Venue
from starquant_shared.types import AccountState, OrderAck, Position


@dataclass
class Snapshot:
    account: AccountState
    positions: dict[str, Position]
    prices: dict[str, float]
    foreign_positions: dict[str, Position] = field(default_factory=dict)
    open_orders: list[OrderAck] = field(default_factory=list)

    @property
    def equity(self) -> float:
        return self.account.equity

    def weights(self) -> dict[str, float]:
        if self.account.equity <= 0:
            return {}
        return {symbol: position.notional / self.account.equity for symbol, position in self.positions.items()}

    def initial_margin(self, leverage_by_symbol: Mapping[str, int] | None = None, default_leverage: int = 1) -> float:
        """Initial margin the standing book consumes, at the leverage the loop set (managed + foreign).

        Computed from ``positionRisk`` rather than read from the account payload: the venue's own
        ``totalInitialMargin`` is the field that came back as an int64 overflow (D-027), and the
        ``leverage`` field on a position reads 0 on this venue, so ``state.leverage_set`` is the record.
        """
        levered = 0.0
        for symbol, position in (*self.positions.items(), *self.foreign_positions.items()):
            leverage = (leverage_by_symbol or {}).get(symbol) or position.leverage or default_leverage
            levered += abs(position.notional) / max(int(leverage), 1)
        return levered

    def margin_usage(self, leverage_by_symbol: Mapping[str, int] | None = None, default_leverage: int = 1) -> float:
        """M-007: standing initial margin as a fraction of equity.  0.0 when equity is not positive."""
        if self.equity <= 0:
            return 0.0
        return self.initial_margin(leverage_by_symbol, default_leverage) / self.equity

    def available_margin(self, leverage_by_symbol: Mapping[str, int] | None = None, default_leverage: int = 1) -> float:
        """Margin headroom for new risk, from the venue when its arithmetic holds and from us when it does not.

        The venue's ``availableBalance`` is authoritative while the account payload is internally
        consistent.  When it is not (D-027: demo-fapi returned an int64 overflow as totalInitialMargin and
        then derived availableBalance 0 from it), trusting it would scale every risk-adding order to zero and
        silently turn the loop into a reduce-only book.  The fallback subtracts the initial margin the
        positions actually consume, at the leverage the loop set, and never reports more than the equity.
        """
        if self.account.margin_fields_reliable:
            return self.account.available_balance
        return max(0.0, self.equity - self.initial_margin(leverage_by_symbol, default_leverage))

    def gross_notional(self) -> float:
        """Sum of |notional| over the managed positions, from ``positionRisk`` — the loop's only position truth.

        Not ``AccountState.gross_notional()``: the venue's account payload does not always carry a
        positions array, and when it does not that method silently returns 0.0, which made a fully
        invested book look flat in ``cycles.jsonl``.
        """
        return sum(abs(position.notional) for position in self.positions.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "equity": self.account.equity,
            "wallet_balance": self.account.wallet_balance,
            "available_balance": self.account.available_balance,
            "positions": {
                s: {"qty": p.qty, "entry": p.entry_price, "mark": p.mark_price, "upnl": p.unrealized_pnl}
                for s, p in self.positions.items()
            },
            "foreign_positions": sorted(self.foreign_positions),
            "open_orders": len(self.open_orders),
        }


async def take_snapshot(venue: Venue, managed_symbols: Sequence[str]) -> Snapshot:
    # `account` and `positions` do not depend on each other, so they overlap; `mark_prices` needs the
    # symbol set `positions` returns and stays behind both.  One saved round trip per cycle, on a path
    # that goes through a system proxy that intermittently 503s.
    #
    # `return_exceptions=False` on purpose: a failed call must still raise out of here rather than
    # arrive as a value nobody inspects.  The one thing this does NOT preserve is *which* failure
    # surfaces when both calls fail - `gather` propagates the one that fails first in time, while the
    # sequential version always surfaced `account()`'s because `positions()` never ran.  `gather`
    # starts its children in argument order, so `account` still wins whenever both fail before
    # awaiting I/O; a late `account` failure against an immediate `positions` failure is the case that
    # can now report the other one.  Return values are unchanged either way.
    account, positions = await asyncio.gather(venue.account(), venue.positions(), return_exceptions=False)
    prices = await venue.mark_prices(list({*managed_symbols, *positions}))
    managed = set(managed_symbols)
    inside = {symbol: position for symbol, position in positions.items() if symbol in managed}
    foreign = {symbol: position for symbol, position in positions.items() if symbol not in managed}
    for symbol, position in positions.items():
        prices.setdefault(symbol, position.mark_price)
    return Snapshot(account=account, positions=inside, prices=prices, foreign_positions=foreign)


# The client-id prefixes this loop issues: `bd-` for rebalances (RebalanceParams.tag) and `bdflat-`
# for flattens.  Anything else on the account belongs to someone else.
OWN_ORDER_PREFIXES = ("bd-", "bdflat-")


def is_own_order(client_order_id: str) -> bool:
    """Did this system place that order?  The separator is part of the prefix (`bdx-` is not ours)."""
    return any(str(client_order_id).startswith(prefix) for prefix in OWN_ORDER_PREFIXES)


async def startup_reconcile(
    venue: Venue, managed_symbols: Sequence[str], *, cancel_stale_orders: bool = True
) -> Snapshot:
    """Exchange positions are the only truth; this loop's own stale orders are cancelled.

    L1-09 / E-31: this used to cancel *every* open order on the account.  Harmless on demo, where
    nothing else trades and the loop only sends market orders - and exactly wrong on an account with
    a hand-placed order, or once anything protective is resting on the book, because a restart would
    remove it without a word.  Orders are filtered by ``is_own_order`` instead of by existence.
    """
    snapshot = await take_snapshot(venue, managed_symbols)
    open_orders = await venue.open_orders()
    snapshot.open_orders = list(open_orders)
    if cancel_stale_orders:
        for order in open_orders:
            if is_own_order(order.client_order_id):
                await venue.cancel_order(order.symbol, order.client_order_id)
    return snapshot
