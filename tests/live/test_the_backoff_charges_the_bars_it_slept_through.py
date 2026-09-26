"""A bar eaten by the failure backoff reached no counter at all, against a threshold of zero (🟡, 2026-09-13).

`backoff_seconds` is 60s doubling per consecutive error, capped at 3600s, with
`max_consecutive_errors` 12.  From the seventh failure each sleep is a whole 1h bar, and the running
total by then is about 7,380s - two bars.  What those bars left behind: nothing.  The ERROR row belongs
to the bar that FAILED, `wait_for_bar_close` returns the next bar still to close and never mentions the
ones already gone, and `_record_missed_rebalance` - the only thing that moves `missed_rebalances` - was
reachable from the restart path alone.  Meanwhile `config/live.demo.yaml` sets
`max_missed_rebalances: 0` (M-Q03).  A threshold of zero that a whole path cannot move is not a
threshold; it is a number that happens to be zero.

The wiring is one reason constant.  `reports.restart_cost` already charges every SKIPPED row whose
reason is not `ALREADY_REBALANCED_REASON`, so naming the reason in `scheduler.py` is the whole of it -
the reporter is untouched, and this module asserts that by reading through it.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.reports import restart_cost
from starquant_live.scheduler import BACKOFF_REASON
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices

HOUR_MS = 3_600_000


def _world(august_panel: Panel, tmp_path: Path) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor)),
        clock=clock,
        store=store,
        # `run()` sets this before the first cycle; a directly driven cycle has to be told.
    )
    engine.rebalance_window = 73.7
    return {"engine": engine, "market": market, "clock": clock, "store": store, "bar": market.bar_open_ms(cursor - 1)}


def _skipped(store: StateStore) -> list[dict[str, Any]]:
    return [row for row in store.read_jsonl(store.cycles_path) if row.get("phase") == "SKIPPED"]


async def test_a_short_backoff_eats_no_bar_and_writes_no_row(august_panel: Panel, tmp_path: Path) -> None:
    """The control.  The first failure sleeps 60s, the next bar has not closed, nothing was missed."""
    world = _world(august_panel, tmp_path)
    engine, market, store = world["engine"], world["market"], world["store"]
    await engine.startup()
    market.fail_next = 1

    assert await engine.guarded_cycle(world["bar"]) is None
    assert world["clock"].sleeps[-1] == 60.0

    assert _skipped(store) == []
    assert engine.missed_rebalances == 0


async def test_an_hour_long_backoff_charges_the_bar_it_slept_through(august_panel: Panel, tmp_path: Path) -> None:
    """The seventh consecutive failure sleeps a whole bar.  That bar now has a row and a count."""
    world = _world(august_panel, tmp_path)
    engine, market, store = world["engine"], world["market"], world["store"]
    await engine.startup()
    engine.consecutive_errors = 6  # the failure below makes it the seventh
    market.fail_next = 1

    await engine.guarded_cycle(world["bar"])

    assert world["clock"].sleeps[-1] == 3600.0, "capped at an hour, unchanged (M-004)"
    rows = _skipped(store)
    assert len(rows) == 1
    assert rows[0]["reason"] == BACKOFF_REASON
    assert rows[0]["bar_open_ms"] == world["bar"] + HOUR_MS, (
        "the bar that closed while we slept, not the one that failed"
    )
    assert engine.missed_rebalances == 1


async def test_the_reporter_counts_it_with_no_change_on_its_side(august_panel: Panel, tmp_path: Path) -> None:
    """M-Q03's `max_missed_rebalances: 0` can finally see this path - through the reporter.

    This asserted 1 until 2026-09-16, when the reporter began charging the bar that FAILED as well as
    the bars slept through - the other half this module's own docstring left open.  One failure here
    costs TWO bars: the one whose cycle raised, and the one whose close went by while the loop slept.
    The 1 was never the number of bars lost; it was the number of them anything counted.
    """
    world = _world(august_panel, tmp_path)
    engine, market, store = world["engine"], world["market"], world["store"]
    await engine.startup()
    engine.consecutive_errors = 6
    market.fail_next = 1

    await engine.guarded_cycle(world["bar"])

    cost = restart_cost(store.read_jsonl(store.cycles_path))
    assert (cost["failed_bars"], cost["skipped_bars"]) == (1, 1), "the bar that failed, and the one slept through"
    assert cost["missed_rebalances"] == 2
    assert cost["status"] == "ALERT", "against the shipped threshold of 0 this is a finding, not a footnote"


async def test_two_bars_slept_through_are_two_rows(august_panel: Panel, tmp_path: Path) -> None:
    """One row per bar.  A single row for a long outage would under-report it by exactly the outage."""
    world = _world(august_panel, tmp_path)
    engine, market, store, clock = world["engine"], world["market"], world["store"], world["clock"]
    await engine.startup()
    engine.consecutive_errors = 6
    market.fail_next = 1
    # The venue was down for two bars, not one: the backoff caps at 3600s, so reaching two bars takes
    # a second failure - which is exactly how the real 7,380s total accumulates.
    await engine.guarded_cycle(world["bar"])
    market.fail_next = 1
    await engine.guarded_cycle(world["bar"] + HOUR_MS)

    rows = _skipped(store)
    assert [row["bar_open_ms"] for row in rows] == [world["bar"] + HOUR_MS, world["bar"] + 2 * HOUR_MS]
    assert all(row["reason"] == BACKOFF_REASON for row in rows)
    assert engine.missed_rebalances == 2
    assert clock.now_ms() >= world["bar"] + 3 * HOUR_MS


async def test_a_failed_cycle_still_says_what_the_process_is_running(august_panel: Panel, tmp_path: Path) -> None:
    """The ERROR heartbeat overwrites the one that carried the digests, so it has to carry them itself.

    Measured 2026-09-15, twelve minutes after the restart that shipped the readers: the loop came up at
    08:49:16Z, wrote a SKIPPED heartbeat that correctly said `1db80a06f281` / `d62ac59fa95c`, and then
    the 09:00Z cycle died on a proxy 503.  The ERROR heartbeat replaced it with four keys, none of them
    a digest, and the only cycle row carrying one predated the restart - so both instruments went to
    "还没有任何周期记录过 digest" for the whole hour.  Silence is honest and still blind, and this is
    the exact window DL-Q0 / R9 exist for.

    Asserted through the engine rather than by reading the source: `bc986ec3` proved a source grep sees
    a field written and cannot see whether anything is left holding it.
    """
    world = _world(august_panel, tmp_path)
    engine, market, store = world["engine"], world["market"], world["store"]
    await engine.startup()
    market.fail_next = 1

    assert await engine.guarded_cycle(world["bar"]) is None, "the cycle was supposed to fail"

    heartbeat = store.read_heartbeat()
    assert heartbeat is not None and heartbeat["phase"] == "ERROR"
    assert heartbeat["registry"] and heartbeat["governance"]
    assert heartbeat["dry_run"] is False


def test_a_skipped_heartbeat_still_says_what_the_process_is_running() -> None:
    """The restart heartbeat has to carry DL-Q0's digests, because it is the only one written
    before a cycle completes - and a restart is exactly when the answer just changed.

    Measured 2026-09-13 on the real loop: an intentional restart at 11:03Z wrote a SKIPPED heartbeat
    with no `registry`, `live status --check` fell back to the previous process's cycle row, and
    reported a disagreement the restart had just resolved.  It stayed non-zero until the next bar
    closed at 12:00Z; the hourly check job runs at :10, inside that window every time.
    """
    source = Path(inspect.getfile(LiveEngine)).read_text(encoding="utf-8")
    body = source.split("def _record_missed_rebalance(")[1].split("\n    async def ")[0]
    assert '"registry"' in body and '"construction"' in body
    # ...and R9's digest beside DL-Q0's, plus the flag that says whose reading this is.  Added
    # 2026-09-15 with the reader that finally consults this heartbeat: bc986ec3 wrote the two digests
    # for this window and changed no reader, so for two days the write was dead and the window it was
    # meant to close stayed open.  The CLI test asserts the read half.
    assert '"governance"' in body and '"dry_run"' in body
