"""§8's Phase 4a presumes a list of construction changes applied together, and the list never existed.

"块 4 必改项**一次改完** → 重启 → 攒 30 天干净窗口" only makes sense if something holds what "必改项"
are.  Each was decided in a log entry; the log has no reader; so on the day a window opens nothing tells
anybody what it was supposed to carry.  Same shape as the thirteen reopen conditions found on
2026-09-10, pointed the other way - not a closed hypothesis nobody reopens, but an open decision nobody
applies.

The concrete cost, measured 2026-09-12: the probe stop's caliber was ruled, recalibrated, and all four
falsifiers passed, and it cannot ship because `max_loss` is inside `construction_fingerprint`.  Without
this list, "what to apply, with which measured values, and why it waited" would be one log entry among
thirty by the time 2026-10-03 arrives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from starquant_governance.window_changes import (
    APPLIED,
    DUE,
    LIST,
    UNREADABLE,
    WAITING,
    Change,
    evaluate,
    load,
    render,
    survey,
)

NOW = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)


def test_a_waiting_change_says_how_far_away_its_window_is() -> None:
    change = Change(id="x", subject="s", earliest_window="2026-10-03")
    status = evaluate(change, NOW)
    assert status.state == WAITING and "20." in status.why


def test_the_day_the_window_opens_it_says_so() -> None:
    """The whole point: a window opens and nobody is told."""
    change = Change(id="x", subject="s", earliest_window="2026-10-03")
    assert evaluate(change, datetime(2026, 10, 3, 1, tzinfo=UTC)).state == DUE
    assert evaluate(change, datetime(2026, 10, 2, 23, tzinfo=UTC)).state == WAITING


def test_an_applied_change_stops_being_a_todo_and_names_what_carried_it() -> None:
    change = Change(id="x", subject="s", earliest_window="2026-10-03", applied="transaction abc123")
    status = evaluate(change, datetime(2026, 11, 1, tzinfo=UTC))
    assert status.state == APPLIED and "abc123" in status.why


def test_a_change_with_no_window_is_unreadable_never_due() -> None:
    """Absent knowledge is not a date that has arrived."""
    assert evaluate(Change(id="x", subject="s"), NOW).state == UNREADABLE
    assert evaluate(Change(id="x", subject="s", earliest_window="soon"), NOW).state == UNREADABLE


def test_the_live_queue_carries_the_probe_stop_change_with_its_measurements() -> None:
    """The entry has to survive three weeks of other work and still be actionable on 2026-10-03."""
    changes = {c.id: c for c in load(Path(LIST))}
    stop = changes["probe-stop-caliber"]
    assert stop.earliest_window == "2026-10-03"
    assert "7.5%" in stop.change and "11.2%" in stop.change, "the new thresholds, not a pointer to them"
    assert "3.239%" in stop.measured and "14.6" in stop.measured
    assert "construction_fingerprint" in stop.why_it_waits
    assert "M-010" in stop.cost and "M-G06" in stop.cost
    assert stop.prereg and stop.verdict, "the commits are the pointers (先写后跑)"


def test_the_summary_shouts_when_a_window_has_opened() -> None:
    changes = load(Path(LIST))
    quiet = render(survey(changes, NOW))
    assert "DUE 0" in quiet and "窗口已经开了" not in quiet
    loud = render(survey(changes, datetime(2026, 10, 5, tzinfo=UTC)))
    assert "窗口已经开了" in loud and "本命令不改任何东西" in loud


def test_every_entry_names_what_it_costs() -> None:
    """A queue that lists changes without their price is a wish list."""
    for change in load(Path(LIST)):
        assert change.cost, change.id
        assert change.why_it_waits, change.id
        assert change.earliest_window, change.id
