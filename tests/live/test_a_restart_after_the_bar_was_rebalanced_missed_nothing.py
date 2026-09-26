"""M-Q03 counted an operator restart as a missed rebalance on a bar that had already been rebalanced.

Measured on the live record, 2026-09-10.  The 05:00 bar closed and the loop rebalanced it at 06:00:27Z
with 18 orders - inside the 106s window, nothing late about it.  The operator then restarted the loop at
06:01:28Z; the new process woke at 06:02:05Z, 125.1s after the close, outside its own 71.6s window, and
`_record_missed_rebalance` wrote a miss row.  M-Q03 went from 1 to 2 and stayed ALERT.

Nothing was missed.  That bar's rebalance had happened ninety seconds earlier, in the outgoing process,
and is in the record with its eighteen fills.  What the incoming process skipped was a SECOND rebalance
of a bar already traded, which is the behaviour anyone would want.

Why it is worth a fix rather than a footnote: M-Q03's failure action is `查重启原因`, and an alarm that
fires on every correctly-executed restart cannot distinguish the two restarts this same day.  At 04:52
the loop woke 3135s after a close whose rebalance never happened - a real miss, from a proxy 503 killing
`exchangeInfo` at startup.  At 06:02 it woke 125s after a close that had been rebalanced.  Counting both
as `missed_rebalances` teaches the operator that the number means "somebody restarted something", and
the loud half of KILL-R6's lesson is that a metric which always fires is the same defect as one that
never does.

**What is deliberately NOT changed here.**  The row still carries `late_seconds`, so it still counts in
`late_cycle_share`.  Whether a startup reconciliation should be in that denominator at all is a question
about M-Q03's caliber, and re-calibrating a metric because today's reading was inconvenient is the move
the mine pre-registrations forbid.  This fix changes one thing only: a bar that was already rebalanced
cannot have had its rebalance missed.  That is a fact about the word, not a threshold.
"""

from __future__ import annotations

from typing import Any

from starquant_live.reports import restart_cost
from starquant_live.scheduler import ALREADY_REBALANCED_REASON, MISSED_REBALANCE_REASON, restart_reason

BAR = 1_789_016_400_000  # 2026-09-10T05:00:00Z, the bar in the record above


def _row(reason: str, late: float, window: float = 71.6) -> dict[str, Any]:
    """A row as `engine._record_missed_rebalance` writes it, for either reason."""
    return {
        "bar": "2026-09-10T05:00:00+00:00",
        "phase": "SKIPPED",
        "reason": reason,
        "late_seconds": late,
        "window_seconds": window,
    }


# --- the predicate: which of the two things happened ------------------------------------------------


def test_a_bar_the_loop_already_traded_missed_nothing() -> None:
    assert restart_reason(bar_open_ms=BAR, last_traded_bar_ms=BAR) == ALREADY_REBALANCED_REASON


def test_a_bar_the_loop_never_traded_is_a_real_miss() -> None:
    """04:52 today: the process woke on the 03:00 bar with 04:00 as the last one it had traded."""
    assert restart_reason(bar_open_ms=BAR, last_traded_bar_ms=BAR - 3_600_000) == MISSED_REBALANCE_REASON


def test_a_loop_with_no_history_at_all_is_a_real_miss() -> None:
    """A first start, or a state file that lost its bar.  Absent knowledge does not excuse the miss."""
    assert restart_reason(bar_open_ms=BAR, last_traded_bar_ms=None) == MISSED_REBALANCE_REASON


def test_a_state_bar_ahead_of_this_one_is_not_treated_as_this_one() -> None:
    """Only equality means THIS bar was traded; a later bar in state means the clocks disagree."""
    assert restart_reason(bar_open_ms=BAR, last_traded_bar_ms=BAR + 3_600_000) == MISSED_REBALANCE_REASON


# --- the count: what M-Q03 reports -------------------------------------------------------------------


def test_the_restart_on_an_already_rebalanced_bar_is_late_but_not_missed() -> None:
    cost = restart_cost([{"bar": "t1", "skip": False}, _row(ALREADY_REBALANCED_REASON, 125.1)])

    assert cost["missed_rebalances"] == 0
    assert cost["skipped_bars"] == 0
    # Reported under its own name since the same day's second ruling: a restart's lateness is a fact
    # about a restart, not about a wake-up.  See test_the_late_share_measures_wake_ups_not_restarts.py.
    assert cost["worst_restart_late_seconds"] == 125.1, "the lateness is still a fact and is still reported"
    assert cost["restarts"] == 1
    assert cost["late_bars"] == 0


def test_the_real_miss_still_counts() -> None:
    """The guard has to keep catching the thing it was built for, or it is worth nothing."""
    cost = restart_cost([{"bar": "t1", "skip": False}, _row(MISSED_REBALANCE_REASON, 3_135.4, 106.1)])

    assert cost["missed_rebalances"] == 1
    assert cost["status"] == "ALERT"


def test_both_restarts_in_one_day_are_told_apart() -> None:
    """Today's record: one proxy-crash restart that missed, one operator restart that did not."""
    rows = [
        {"bar": "t0", "skip": False},
        _row(MISSED_REBALANCE_REASON, 3_135.4, 106.1),
        {"bar": "t1", "skip": False},
        _row(ALREADY_REBALANCED_REASON, 125.1),
    ]

    cost = restart_cost(rows)

    assert cost["missed_rebalances"] == 1
    assert cost["restarts"] == 2
    assert cost["worst_restart_late_seconds"] == 3_135.4
    # The window is read off the rows rather than recomputed, and both rows carry a real one.
    assert cost["widest_window_seconds"] == 106.1


def test_an_already_rebalanced_row_alone_does_not_raise_the_alarm() -> None:
    """The whole point: a clean operator restart leaves M-Q03's missed-rebalance half at zero."""
    rows = [{"bar": f"t{i}", "skip": False} for i in range(40)] + [_row(ALREADY_REBALANCED_REASON, 125.1)]

    assert restart_cost(rows)["missed_rebalances"] == 0
