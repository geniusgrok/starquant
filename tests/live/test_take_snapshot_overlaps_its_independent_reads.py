"""`take_snapshot` awaited three REST calls in a row, two of which do not need each other.

`account` and `positions` are independent; `mark_prices` needs the symbol set `positions` returns and
has to stay behind them.  On this deployment the path to the venue goes through a system proxy that
intermittently 503s, so a saved round trip per cycle is worth having, and the loop runs hourly with a
startup window - it is not free latency, it is one fewer chance to hit the proxy.

Nothing about the snapshot's contents may change, which is the first test here.  The second pins the
part `asyncio.gather` does NOT preserve for free: the sequential version always surfaced `account()`'s
failure, because `positions()` never ran.  `gather` raises whichever child fails first in time, and it
starts its children in argument order, so `account` still wins when both fail before awaiting I/O.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from starquant_live.reconciler import take_snapshot
from starquant_shared.types import AccountState, Position


class _SlowVenue:
    """Each read takes one `sleep(0)` round of the loop, and records when it started and finished."""

    def __init__(self, *, fail: set[str] | None = None, hops: int = 3) -> None:
        self.fail = fail or set()
        self.hops = hops
        self.order: list[str] = []

    async def _hop(self, name: str) -> None:
        self.order.append(f"{name}:start")
        for _ in range(self.hops):
            await asyncio.sleep(0)
        if name in self.fail:
            raise RuntimeError(f"{name} failed")
        self.order.append(f"{name}:done")

    async def account(self) -> AccountState:
        await self._hop("account")
        return AccountState(wallet_balance=10_000.0, available_balance=9_000.0, equity=10_000.0, positions={})

    async def positions(self) -> dict[str, Position]:
        await self._hop("positions")
        return {
            "BTCUSDT": Position("BTCUSDT", 0.02, 60_000.0, 60_000.0),
            "DOGEUSDT": Position("DOGEUSDT", -1_000.0, 0.10, 0.10),
        }

    async def mark_prices(self, symbols: Sequence[str]) -> dict[str, float]:
        await self._hop("mark_prices")
        return dict.fromkeys(symbols, 1.0)


async def test_the_snapshot_is_unchanged() -> None:
    snapshot = await take_snapshot(_SlowVenue(), ["BTCUSDT", "ETHUSDT"])

    assert snapshot.equity == 10_000.0
    assert set(snapshot.positions) == {"BTCUSDT"}
    assert set(snapshot.foreign_positions) == {"DOGEUSDT"}, "an unmanaged position is still split out"
    assert set(snapshot.prices) == {"BTCUSDT", "ETHUSDT", "DOGEUSDT"}


async def test_the_two_independent_reads_overlap_and_the_dependent_one_does_not() -> None:
    venue = _SlowVenue()
    await take_snapshot(venue, ["BTCUSDT"])

    started = venue.order.index("positions:start")
    assert started < venue.order.index("account:done"), "positions must start before account finishes"
    assert venue.order.index("mark_prices:start") > venue.order.index("positions:done"), (
        "mark_prices needs the symbols positions returned, so it cannot be part of the gather"
    )


async def test_a_failing_read_still_raises_rather_than_arriving_as_a_value() -> None:
    """`return_exceptions=False`, asserted: the alternative silently hands the loop a corrupt snapshot."""
    with pytest.raises(RuntimeError, match="positions failed"):
        await take_snapshot(_SlowVenue(fail={"positions"}), ["BTCUSDT"])


async def test_when_both_reads_fail_it_is_still_the_account_error_that_surfaces() -> None:
    """The sequential version could only ever raise `account()`'s.  Same here, for the same reason
    the old code had: `account` goes first.  `gather` starts its children in argument order, so with
    both failing at the same depth `account`'s exception is set first and is the one propagated."""
    with pytest.raises(RuntimeError, match="account failed"):
        await take_snapshot(_SlowVenue(fail={"account", "positions"}), ["BTCUSDT"])
