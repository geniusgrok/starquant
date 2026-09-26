"""M-Q03's late half, ruled 2026-09-10: the share is over SCHEDULED wake-ups, computed from the record.

Two things were wrong with it, found while restarting the system on 2026-09-10.

**One: it could only ever see restarts.**  The engine writes `late_seconds` into a cycle row in exactly
one place - `_record_missed_rebalance`, which runs only on an `--immediate` startup outside the window.
So every member of the numerator was a restart, and a metric named "迟到周期占比" was reporting how
often somebody restarted the loop.  Its denominator was every cycle, so the number moved when the loop
ran MORE, and it could not see the thing it is named for: the audit counted 33 cycles in the record
that landed more than 60s after their bar close, and not one of them was in this share.

**Two: a restart that cost nothing was in it.**  That was the operator's question, and the answer is
no.  A startup reconciliation is not a wake-up; it happens when a person or launchd starts a process.
Counting it measures restart frequency, and `restarts` reports that separately and honestly.

The fix needed no new field.  Every cycle row already carries `at` and `bar_open_ms` - 202 of 202 on
the live record - so the lateness of every cycle was recorded from the beginning and only the reader
was missing.  That is this repository's most-repeated defect, in its most literal form.

**The bar is not invented.**  A cycle counts as late when it woke outside the rebalance window the
ENGINE allowed, read off the rows (`window_seconds`) rather than recomputed here - the same refusal
`widest_window_seconds` already makes.  When the record holds no window at all, the share is `None`
rather than a number: a day with nothing to measure against is not a day nothing was late on.
"""

from __future__ import annotations

from typing import Any

from starquant_live.reports import restart_cost
from starquant_live.scheduler import ALREADY_REBALANCED_REASON, MISSED_REBALANCE_REASON

HOUR_MS = 3_600_000
BAR = 1_789_016_400_000  # 2026-09-10T05:00:00Z


WINDOW = 106.09  # what the engine allowed on 2026-09-10; it writes this onto every cycle row


def _cycle(bar_open_ms: int, woke_seconds_after_close: float, window: float | None = WINDOW) -> dict[str, Any]:
    """A scheduled cycle as the engine writes it since 2026-09-10: `at`, `bar_open_ms`, `window_seconds`.

    `window=None` is the shape of a row written BEFORE the engine started stating its window - the
    historical record - and those rows fall back to the widest window the day holds.
    """
    at_ms = bar_open_ms + HOUR_MS + int(woke_seconds_after_close * 1000)
    row: dict[str, Any] = {"bar_open_ms": bar_open_ms, "at": _iso(at_ms), "skip": False}
    if window is not None:
        row["window_seconds"] = window
    return row


def _restart(bar_open_ms: int, late: float, reason: str, window: float = 106.09) -> dict[str, Any]:
    at_ms = bar_open_ms + HOUR_MS + int(late * 1000)
    return {
        "bar_open_ms": bar_open_ms,
        "at": _iso(at_ms),
        "phase": "SKIPPED",
        "reason": reason,
        "late_seconds": late,
        "window_seconds": window,
    }


def _iso(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _day(*offsets: float) -> list[dict[str, Any]]:
    return [_cycle(BAR + i * HOUR_MS, late) for i, late in enumerate(offsets)]


# --- the share is over scheduled wake-ups ------------------------------------------------------------


def test_a_punctual_day_with_one_harmless_restart_is_not_a_late_day() -> None:
    """Today's record: cycles at +14s and +27s, and a restart that cost nothing."""
    rows = [*_day(14.0, 27.0, 13.0), _restart(BAR + 3 * HOUR_MS, 125.1, ALREADY_REBALANCED_REASON)]

    cost = restart_cost(rows)

    assert cost["late_cycle_share"] == 0.0, "three punctual wake-ups; the restart is not a wake-up"
    assert cost["late_bars"] == 0
    assert cost["missed_rebalances"] == 0
    assert cost["restarts"] == 1, "the restart is still counted, just not as lateness"
    assert cost["status"] == "OK"


def test_a_cycle_that_woke_outside_the_window_is_late() -> None:
    """The thing the metric is named for, and could not see until now: a genuinely late wake-up."""
    rows = [*_day(14.0, 3_576.0, 13.0, 20.0), _restart(BAR + 4 * HOUR_MS, 125.1, ALREADY_REBALANCED_REASON)]

    cost = restart_cost(rows)

    assert cost["late_bars"] == 1
    assert cost["late_cycle_share"] == 0.25, "one of four SCHEDULED cycles, not one of five rows"
    assert cost["worst_late_seconds"] == 3_576.0


def test_a_restart_that_missed_is_still_a_miss_and_still_not_in_the_share() -> None:
    """Both halves keep their own job: the miss is counted, the share stays about wake-ups."""
    rows = [*_day(14.0, 20.0), _restart(BAR + 2 * HOUR_MS, 3_135.4, MISSED_REBALANCE_REASON)]

    cost = restart_cost(rows)

    assert cost["missed_rebalances"] == 1
    assert cost["restarts"] == 1
    assert cost["late_cycle_share"] == 0.0
    assert cost["status"] == "ALERT", "the miss alone breaches M-Q03's zero"


def test_the_five_percent_bar_is_judged_against_scheduled_cycles() -> None:
    rows = [*_day(*([14.0] * 19), 3_600.0), _restart(BAR + 20 * HOUR_MS, 125.1, ALREADY_REBALANCED_REASON)]

    cost = restart_cost(rows)

    assert cost["late_cycle_share"] == 0.05, "1/20 is exactly the bar"
    assert cost["status"] == "OK", "M-Q03 says <= 5%, so the bar itself passes"


def test_one_more_late_cycle_breaches_it() -> None:
    rows = _day(*([14.0] * 18), 3_600.0, 3_600.0)

    cost = restart_cost(rows)

    assert cost["late_cycle_share"] == 0.1
    assert cost["status"] == "ALERT"


# --- refusals ----------------------------------------------------------------------------------------


def test_a_record_with_no_window_anywhere_reports_no_share_rather_than_a_clean_zero() -> None:
    """Nothing to measure against is not evidence that nothing was late.

    This is the shape of a day recorded before 2026-09-10: no cycle stated its window, and no restart
    happened to leave one behind.  Such a day reports `None`, and days after it report a number.
    """
    old_rows = [_cycle(BAR + i * HOUR_MS, late, window=None) for i, late in enumerate((14.0, 6_000.0))]

    cost = restart_cost(old_rows)

    assert cost["late_cycle_share"] is None
    assert cost["widest_window_seconds"] is None
    assert cost["status"] == "OK", "and an unmeasurable day does not raise the alarm either"


def test_an_old_row_borrows_the_widest_window_the_day_actually_holds() -> None:
    """One restart in the day is enough to give every pre-2026-09-10 row a bar it can be judged by."""
    rows = [
        _cycle(BAR, 14.0, window=None),
        _cycle(BAR + HOUR_MS, 6_000.0, window=None),
        _restart(BAR + 2 * HOUR_MS, 125.1, ALREADY_REBALANCED_REASON),
    ]

    cost = restart_cost(rows)

    assert cost["widest_window_seconds"] == 106.09
    assert cost["late_bars"] == 1
    assert cost["late_cycle_share"] == 0.5


def test_a_day_of_nothing_but_restarts_reports_no_share() -> None:
    """The denominator is scheduled cycles; a day with none of them has no share to report."""
    cost = restart_cost([_restart(BAR, 125.1, ALREADY_REBALANCED_REASON)])

    assert cost["late_cycle_share"] is None
    assert cost["restarts"] == 1


def test_a_row_that_cannot_say_when_it_woke_is_left_out_rather_than_guessed() -> None:
    """A torn row is not a punctual cycle; it is a cycle whose punctuality is unknown."""
    torn = {"bar_open_ms": BAR + 2 * HOUR_MS, "at": "not-a-timestamp", "skip": False, "window_seconds": WINDOW}
    rows = [*_day(14.0, 20.0), torn]

    cost = restart_cost(rows)

    assert cost["cycles"] == 3, "the row is still a cycle"
    assert cost["late_bars"] == 0
    assert cost["late_cycle_share"] == 0.0, "over the two that could be read"
    assert cost["unreadable_wakes"] == 1
