"""M-007's bar was the plan's 50%, while the policy that governs the same quantity is `margin_cap` 0.40.

Two numbers for one quantity, and the looser one was doing the judging - the `max_slippage_bps` shape the
profile already records ("A fee-inclusive budget judging a fee-exclusive number, at 2.5x the stated bar,
could not fail").  Realized standing margin could sit anywhere in 40-50%, above the configured policy,
and M-007 would read OK.

The second half is that it could not have been read anyway: `over_budget` was computed, rendered into the
daily markdown, and never routed - `daily_alerts` had no margin branch at all, so the finding reached
neither the alert list nor the notice list.  D-038's shape once more.

The plan's 50% is kept beside the bar rather than deleted, because what it was wrong ABOUT is the record.
"""

from __future__ import annotations

from pathlib import Path

from starquant_live.reports import daily_alerts, margin_and_rejections
from starquant_live.state import StateStore

BASE = 1_788_000_000_000
HOUR = 3_600_000


def _store(tmp_path: Path, standing: list[float]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for i, usage in enumerate(standing):
        store.append_cycle({"bar_open_ms": BASE + i * HOUR, "equity": 10_000.0, "margin_usage": usage})
    return store


def test_the_bar_is_the_configured_margin_cap_not_the_plans_fifty_percent(tmp_path: Path) -> None:
    """45% standing margin is inside the plan's 50% and outside the 40% the profile actually declares."""
    store = _store(tmp_path, [0.11, 0.45, 0.12])

    result = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert result["peak_standing_usage"] == 0.45
    assert result["budget"] == 0.40, "the bar is the policy, not the plan-era constant"
    assert result["over_budget"] is True


def test_the_plans_number_is_recorded_beside_the_bar_rather_than_deleted(tmp_path: Path) -> None:
    """Correcting a ruler without keeping the old one hides what the correction was about."""
    result = margin_and_rejections(_store(tmp_path, [0.45]), since_ms=None, margin_cap=0.40)

    assert result["plan_budget"] == 0.50


def test_without_a_configured_cap_the_reading_is_what_it_was(tmp_path: Path) -> None:
    """A caller that cannot supply the policy still gets the plan's bar, not a silently stricter one."""
    result = margin_and_rejections(_store(tmp_path, [0.45]), since_ms=None)

    assert result["budget"] == 0.50 and result["over_budget"] is False


def test_the_bar_survives_a_book_that_also_has_rejections(tmp_path: Path) -> None:
    """Regression: the budget was a local named `bar`, and the rejection loop below rebinds `bar` to
    `bar_open_ms`.  With any trade row present, `over_budget` compared a margin share against a
    millisecond timestamp and was therefore always False - a silent pass, invisible to a fixture that
    records no trades.  mypy caught it; this pins it.
    """
    store = _store(tmp_path, [0.45])
    store.append_trade({"bar_open_ms": BASE, "status": "REJECTED", "error": "-1111: Precision"})

    result = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert result["budget"] == 0.40, "the budget is not the last bar timestamp the loop saw"
    assert result["over_budget"] is True
    assert result["rejections"]["-1111"] == 1


def test_a_breach_reaches_the_operator_instead_of_only_being_rendered() -> None:
    """`over_budget` had no reader.  It is a notice, not an alert - see the routing comment for why."""
    alerts, notices = daily_alerts({"margin": {"over_budget": True, "peak_standing_usage": 0.45, "budget": 0.40}})

    assert any("M-007" in line for line in notices), notices
    assert not alerts, "a breach self-corrects at the next rebalance; it is read at review, not paged"


def test_a_book_inside_the_policy_says_nothing() -> None:
    """The other half of a routed finding: silence when there is nothing to say."""
    alerts, notices = daily_alerts({"margin": {"over_budget": False, "peak_standing_usage": 0.11, "budget": 0.40}})

    assert not alerts and not any("M-007" in line for line in notices)
