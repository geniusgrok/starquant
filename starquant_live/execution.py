"""Idempotent order execution: query-before-submit, unknown-outcome recovery, bounded polling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starquant_live.ports import Clock, Venue
from starquant_live.rebalancer import PlannedOrder
from starquant_shared.types import OrderAck, OrderOutcomeUnknown, OrderRequest, VenueError


@dataclass
class ExecutionReport:
    order: PlannedOrder
    status: str  # FILLED | PARTIAL | REJECTED | UNKNOWN | CANCELED | SKIPPED_EXISTING
    ack: OrderAck | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.order.to_dict(),
            "status": self.status,
            "order_id": None if self.ack is None else self.ack.order_id,
            "venue_status": None if self.ack is None else self.ack.status,
            "executed_qty": None if self.ack is None else str(self.ack.executed_qty),
            "avg_price": None if self.ack is None else self.ack.avg_price,
            "error": self.error,
        }


async def execute_order(
    venue: Venue,
    order: PlannedOrder,
    clock: Clock,
    *,
    poll_attempts: int = 5,
    poll_interval_seconds: float = 1.0,
) -> ExecutionReport:
    existing = await venue.query_order(order.symbol, order.client_order_id)
    if existing is not None:
        return ExecutionReport(order, _status_of(existing), existing, "already submitted for this bar")
    request = OrderRequest(
        order.symbol, order.side, order.quantity, order.client_order_id, reduce_only=order.reduce_only
    )
    try:
        ack: OrderAck | None = await venue.place_order(request)
    except OrderOutcomeUnknown as exc:
        ack = await _poll(venue, order, clock, poll_attempts, poll_interval_seconds)
        if ack is None:
            return ExecutionReport(order, "UNKNOWN", None, f"outcome unknown after {poll_attempts} queries: {exc}")
    except VenueError as exc:
        return ExecutionReport(order, "REJECTED", None, f"{exc} (code {exc.code})")
    if ack is not None and not ack.is_terminal:
        latest = await _poll(venue, order, clock, poll_attempts, poll_interval_seconds, until_terminal=True)
        ack = latest or ack
        if not ack.is_terminal:
            canceled = await venue.cancel_order(order.symbol, order.client_order_id)
            final = await venue.query_order(order.symbol, order.client_order_id)
            ack = final or canceled or ack
    assert ack is not None
    ack = await _resolve_fill_price(venue, order, ack)
    return ExecutionReport(order, _status_of(ack), ack)


async def _resolve_fill_price(venue: Venue, order: PlannedOrder, ack: OrderAck) -> OrderAck:
    """A MARKET ack can carry ``avgPrice=0`` even after filling; query once for the settled price.

    Attribution and traded-notional accounting are only as good as the fill
    price, so an ack that reports a fill without a price is re-read rather
    than silently falling back to the decision-time mark.
    """
    if not ack.filled or ack.avg_price > 0:
        return ack
    settled = await venue.query_order(order.symbol, order.client_order_id)
    if settled is not None and settled.avg_price > 0:
        return settled
    return ack


async def _poll(
    venue: Venue, order: PlannedOrder, clock: Clock, attempts: int, interval: float, *, until_terminal: bool = False
) -> OrderAck | None:
    found: OrderAck | None = None
    for _ in range(max(1, attempts)):
        await clock.sleep(interval)
        found = await venue.query_order(order.symbol, order.client_order_id)
        if found is not None and (not until_terminal or found.is_terminal):
            return found
    return found


def _status_of(ack: OrderAck) -> str:
    if ack.status == "FILLED":
        return "FILLED"
    if ack.status in {"CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}:
        return "PARTIAL" if ack.executed_qty > 0 else "CANCELED"
    if ack.status == "REJECTED":
        return "REJECTED"
    return "PARTIAL" if ack.executed_qty > 0 else "UNKNOWN"
