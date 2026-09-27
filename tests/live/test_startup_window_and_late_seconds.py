"""DL-L4: a restart always reconciles; it only rebalances if it is still on time.

``deploy/run_live.sh`` passes ``--immediate`` unconditionally, so every restart re-runs the last
closed bar - which is how 90 of 119 fills landed a median 21.6 minutes after the close (E-18).  The
09-05 prescription was "only go immediate if ``now - last_close < 120s``", and KILL-R6 took it apart:
a 143-second catch-up would become a 57-minute stale book, a flatten-then-restart an hour of no
positions, and a crash up to 59 minutes with nobody reconciling the account.

So the two halves are separated, which is what the fix should always have been.

* **Reconciliation always runs.**  It is read-only, it is what discovers foreign positions and
  orphaned orders, and there is no window in which skipping it is safer.
* **Rebalancing is what the window gates**, and the window is *derived* rather than picked: the
  grace period the scheduler already waits, plus launchd's ThrottleInterval, plus how long this
  process actually took to start.  Outside it the bar is skipped and counted - the count is the
  point, because L1-01's error was measuring the fills that happened rather than the ones that
  should not have.
"""

from __future__ import annotations

from starquant_live.scheduler import rebalance_window_seconds, within_rebalance_window
from starquant_live.verify import SETTLE_SECONDS


def test_the_loop_waits_for_the_venue_to_finish_aggregating_the_bar() -> None:
    """Two numbers that have to be read together, in files that never mentioned each other.

    `SETTLE_SECONDS` was measured on 2026-09-12: the venue is still finalising `taker_buy_quote` and
    `quote_volume` for about fifteen seconds after a bar closes, and `flow` is the only book that reads
    them.  `grace_seconds` was 5.0 the whole time, so the loop fetched EVERY bar inside that window -
    not 56% of them, which is what measuring the cycle's row-WRITE time says; the fetch is the first
    thing the cycle does after waking at close + grace.

    The book was never wrong in a way it could act on (the worst target difference those unsettled
    reads produced was 441x below the no-trade band).  What it cost was M-011, which went red on a
    known-benign cause often enough to hide a real one.

    Asserted as an inequality against the measurement rather than as `== 20.0`, so that re-measuring
    the settle window moves this with it instead of leaving a stale constant behind.
    """
    from tests.live.helpers_construction import live_config_for_profile

    assert live_config_for_profile().grace_seconds > SETTLE_SECONDS


def test_waiting_longer_widens_the_rebalance_window_by_exactly_the_same_amount() -> None:
    """The DL-L4 window is DERIVED from the grace, so the grace cannot move quietly.

    This one passes trivially whenever the grace has not moved - it is not a defect detector and is
    not claimed as one.  Its job is to fail if the window ever stops being a straight sum of its
    parts, which is the property KILL-R6 bought when 120s stopped being a picked number.
    """
    from tests.live.helpers_construction import live_config_for_profile

    grace = live_config_for_profile().grace_seconds
    before = rebalance_window_seconds(grace_seconds=5.0, throttle_interval=60.0, startup_seconds=5.687)
    after = rebalance_window_seconds(grace_seconds=grace, throttle_interval=60.0, startup_seconds=5.687)

    assert after - before == grace - 5.0


def test_the_window_is_derived_from_the_parts_not_chosen() -> None:
    """grace + ThrottleInterval + startup cost.  120 was a guess; this is an addition."""
    assert rebalance_window_seconds(grace_seconds=5.0, throttle_interval=60.0, startup_seconds=90.0) == 155.0


def test_a_prompt_restart_still_rebalances() -> None:
    """The 143-second catch-up KILL-R6 used as its counter-example must stay inside the window."""
    window = rebalance_window_seconds(grace_seconds=5.0, throttle_interval=60.0, startup_seconds=90.0)

    assert within_rebalance_window(seconds_since_close=143.0, window_seconds=window) is True


def test_an_hour_late_does_not_rebalance() -> None:
    window = rebalance_window_seconds(grace_seconds=5.0, throttle_interval=60.0, startup_seconds=90.0)

    assert within_rebalance_window(seconds_since_close=3_600.0, window_seconds=window) is False


def test_the_boundary_is_inclusive_so_a_window_of_exactly_n_still_trades() -> None:
    assert within_rebalance_window(seconds_since_close=155.0, window_seconds=155.0) is True
    assert within_rebalance_window(seconds_since_close=155.1, window_seconds=155.0) is False


def test_a_negative_age_is_inside_the_window() -> None:
    """Clock skew between host and venue must not turn into a skipped bar (D-030)."""
    assert within_rebalance_window(seconds_since_close=-2.0, window_seconds=155.0) is True


def test_late_seconds_is_derived_from_the_bar_not_from_a_wall_clock_guess() -> None:
    from starquant_live.scheduler import late_seconds

    bar_open_ms = 1_757_145_600_000
    interval_ms = 3_600_000
    close_ms = bar_open_ms + interval_ms

    assert late_seconds(bar_open_ms, interval_ms, at_ms=close_ms + 21_600) == 21.6
    assert late_seconds(bar_open_ms, interval_ms, at_ms=close_ms) == 0.0


def test_a_fill_before_the_close_reports_zero_not_a_negative() -> None:
    """`late_seconds` measures lateness; earliness is not negative lateness, it is none."""
    from starquant_live.scheduler import late_seconds

    bar_open_ms = 1_757_145_600_000
    interval_ms = 3_600_000

    assert late_seconds(bar_open_ms, interval_ms, at_ms=bar_open_ms + interval_ms - 5_000) == 0.0
