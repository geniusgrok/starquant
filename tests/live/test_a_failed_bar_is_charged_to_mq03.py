"""The bar a cycle FAILED on reached no counter either, against the same threshold of zero (🟡, 2026-09-16).

`test_the_backoff_charges_the_bars_it_slept_through` closed one half of this in 2026-09-13: the bars
the failure backoff *sleeps through* now write a SKIPPED row and are charged.  The other half was left
open, and its own docstring says so - "the ERROR row belongs to the bar that FAILED".  Nothing charges
that bar, so `max_missed_rebalances: 0` still cannot see the commonest outage this loop actually has.

What it costs, measured on the armed loop 2026-09-16.  A failed cycle does not retry inside its bar:
`backoff_seconds()` sleeps 60s and `wait_for_bar_close` then returns the NEXT bar, so with a 1h
interval the failed bar is simply gone.  Four bars since 2026-09-08 have no successful cycle at all -
2026-09-09T10:00, 09-14T20:00, 09-15T08:00, 09-16T04:00 - every one of them a transport error on the
path to the venue.  M-Q03 reported zero misses on each of those days.  The only instrument that saw
them was `live status`'s 95% success rate, which over ~25 attempts a day tolerates exactly one lost
bar per day - a different number from the zero written in `config/live.demo.yaml`, reached by nobody's
decision.

And it is not "one rebalance skipped": the exit overlay never rests an order at the venue, it is
evaluated inside the cycle and closed with MARKET reduceOnly.  A lost bar is an hour with no stop
check.

Charged on the READER side, for the reason the reporter already gives for counting rows rather than
the engine's running total: the counter resets on restart, and these outages are exactly when restarts
happen.  Reading rows also charges the four bars already in the record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starquant_alpha.panel import Panel
from starquant_live.reports import restart_cost
from starquant_live.scheduler import ALREADY_REBALANCED_REASON, BACKOFF_REASON, MISSED_REBALANCE_REASON
from starquant_live.soak import no_decisions

HOUR_MS = 3_600_000
BAR = 1_789_531_200_000  # 2026-09-16T04:00:00Z, one of the four


def _failed(bar_open_ms: int = BAR, **decided: Any) -> dict[str, Any]:
    """The row `guarded_cycle` writes, in the shape it writes it."""
    return {
        "bar_open_ms": bar_open_ms,
        "bar": "2026-09-16T04:00:00+00:00",
        "phase": "ERROR",
        "error": "ProxyError: 503 Service Unavailable",
        "consecutive_errors": 1,
        "window_seconds": 87.1,
        "targets": {"BTCUSDT": 0.1},
        "dry_run": False,
        **(no_decisions() | decided),
    }


def _completed(bar_open_ms: int = BAR) -> dict[str, Any]:
    """A cycle that finished.  Completed rows carry no `phase` at all."""
    return {"bar_open_ms": bar_open_ms, "window_seconds": 87.1, "orders": [], "equity": 10_000.0}


def _skipped(bar_open_ms: int, reason: str) -> dict[str, Any]:
    return {
        "bar_open_ms": bar_open_ms,
        "phase": "SKIPPED",
        "reason": reason,
        "late_seconds": 41.0,
        "window_seconds": 87.1,
    }


def test_a_failed_bar_that_decided_nothing_is_a_missed_rebalance() -> None:
    cost = restart_cost([_failed()])

    assert cost["missed_rebalances"] == 1
    assert cost["failed_bars"] == 1
    assert cost["status"] == "ALERT", "against the shipped threshold of 0 this is a finding"


def test_the_breach_names_the_transport_rather_than_sending_someone_to_read_restart_logs() -> None:
    """The old reason said "查重启原因" for every miss.  No restart happened here; a request failed."""
    (reason,) = restart_cost([_failed()])["reasons"]

    assert "查重启原因" not in reason, "there was no restart to go and read the reason of"
    assert "ProxyError: 503 Service Unavailable" in reason, "the failure is the thing to look at"


def test_a_failed_cycle_that_already_placed_orders_did_not_miss_its_rebalance() -> None:
    """`run_cycle` places orders and only then quarantines, summarizes and finishes.

    A raise in any of those three leaves fills on the venue - the book WAS rebalanced, and charging
    that bar a miss would report the opposite of what happened.  This is the same distinction
    `soak._decided` already draws, read through the same five keys.
    """
    cost = restart_cost([_failed(orders=[{"symbol": "BTCUSDT", "qty": 0.01}])])

    assert cost["missed_rebalances"] == 0
    assert cost["failed_bars"] == 0
    assert cost["status"] == "OK"


def test_a_bar_that_failed_and_then_completed_is_not_charged() -> None:
    """2026-09-08T05:00 is in the record twice: it failed, and a restart reconciled it 17 minutes later.

    The question M-Q03 asks is about the BAR, not the attempt, so a bar that got there in the end
    costs nothing - however many rows it took.
    """
    assert restart_cost([_failed(), _completed()])["missed_rebalances"] == 0


def test_a_failed_bar_a_late_restart_then_skipped_is_charged_once_to_the_failure() -> None:
    """The same 2026-09-08 bar, but reconciled by a restart OUTSIDE the window, which writes its own
    miss row.  Two rows, one lost bar, one charge - the failure's.  Until 2026-09-24 the skip row took
    that charge over; see `test_a_restart_does_not_take_over_a_bar_a_failed_cycle_lost`."""
    cost = restart_cost([_failed(), _skipped(BAR, MISSED_REBALANCE_REASON)])

    assert cost["missed_rebalances"] == 1
    assert (cost["failed_bars"], cost["skipped_bars"]) == (1, 0)
    assert cost["restarts"] == 1, "the restart is still counted as a restart"


def test_a_failed_bar_whose_restart_found_it_already_rebalanced_is_not_charged() -> None:
    """`ALREADY_REBALANCED_REASON` is the engine saying this bar's book did get set.  It outranks the
    ERROR row for the same reason it outranks the skip: a bar cannot have missed what it got."""
    assert restart_cost([_failed(), _skipped(BAR, ALREADY_REBALANCED_REASON)])["missed_rebalances"] == 0


def test_skipped_bars_still_counts_only_skip_rows() -> None:
    """`missed_rebalances` and `skipped_bars` were the same rows and the docstring said a future engine
    could separate them.  This is that separation: an ERROR bar is a miss and is not a skip."""
    cost = restart_cost([_failed(), _skipped(BAR + HOUR_MS, BACKOFF_REASON)])

    assert cost["missed_rebalances"] == 2
    assert cost["skipped_bars"] == 1, "one SKIPPED row"
    assert cost["failed_bars"] == 1, "one ERROR bar"


def test_a_clean_day_is_still_clean() -> None:
    """The control.  Nothing above may turn an ordinary day into an alert."""
    cost = restart_cost([_completed(BAR), _completed(BAR + HOUR_MS)])

    assert cost["missed_rebalances"] == 0 and cost["failed_bars"] == 0
    assert cost["status"] == "OK"


async def test_the_reporter_charges_what_the_engine_actually_writes(august_panel: Panel, tmp_path: Path) -> None:
    """Read through the engine, not through a row this test wrote: `bc986ec3` proved a hand-built row
    can assert a shape nothing produces."""
    from starquant_live.engine import LiveEngine
    from starquant_live.state import StateStore
    from tests.fakes.fake_venue import FakeVenue
    from tests.live.fakes import FakeClock, FakeMarketData
    from tests.live.test_live_loop import _config, _model, _prices

    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor)),
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=store,
    )
    engine.rebalance_window = 87.1
    await engine.startup()
    market.fail_next = 1

    assert await engine.guarded_cycle(market.bar_open_ms(cursor - 1)) is None, "the cycle was supposed to fail"

    cost = restart_cost(store.read_jsonl(store.cycles_path))
    assert cost["missed_rebalances"] == 1
    assert cost["failed_bars"] == 1
    assert cost["status"] == "ALERT"
