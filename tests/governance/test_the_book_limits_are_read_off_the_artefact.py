"""`validated -> booked` has four conditions; three of them were a literal `True` until today.

`starquant_governance/replay.py` built its `Facts` for a book report with `slippage_stress_pass=True`,
`max_correlation_with_running=0.0` and `turnover_ratio_to_main=0.0` - the passing value of every one -
and listed them as suspended.  That was honest about the blind spot and it also meant the state
machine's own comment ("Absent knowledge is False, never assumed true") described nothing that ran:
the only condition an artefact could fail at this transition was D-018's verdict.

These tests hold the three properties the fix has to have, and the third is the one that is easy to
get wrong: a report that carries the block must be JUDGED on it, a report that does not must be
SUSPENDED, and a value of `null` inside the block must suspend rather than read as 0.0 - because 0.0
is the passing value for both of the numeric limits, so "nobody measured it" and "it correlates with
nothing" would otherwise be spelled the same way.
"""

from __future__ import annotations

from typing import Any

from starquant_governance.lifecycle import Book, Candidate, Event, State, evaluate
from starquant_governance.policy import Policy
from starquant_governance.replay import JUDGEABLE, SUSPENDED, _facts_for, replay_adoptions

PASSING_LIMITS: dict[str, Any] = {
    "slippage_stress": {"decision_slippage_bps": 5.5, "pass": True, "reasons": []},
    "correlation_with_running": {"main": 0.26, "flow_short": 0.31},
    "max_correlation_with_running": 0.31,
    "turnover_ratio_to_main": 0.56,
}


def _book(**limits: Any) -> dict[str, Any]:
    """An ACCEPT book report with `book_limits` overridden field by field."""
    report: dict[str, Any] = {
        "kind": "book",
        "book_verdict": "ACCEPT",
        "sleeve": {"strategy": "x"},
        "generated_at": "2026-10-01T00:00:00+00:00",
    }
    report["book_limits"] = {**PASSING_LIMITS, **limits}
    return report


def _decide(report: dict[str, Any]) -> tuple[Any, tuple[str, ...]]:
    event, facts, suspended = _facts_for(report, acknowledged=False)
    assert event is Event.BOOK
    return evaluate(Book(), Candidate(id="x", state=State.VALIDATED), event, facts, Policy()), suspended


def test_a_book_report_carrying_the_three_fields_is_judged_on_them() -> None:
    decision, suspended = _decide(_book())
    assert decision.allowed and decision.state is State.BOOKED
    assert suspended == (), "nothing is suspended once the artefact carries the fields"


def test_a_report_without_the_block_is_suspended_rather_than_waved_through() -> None:
    """The six archived book reports.  They still pass - but the replay now says which conditions it
    did not apply, one per condition, instead of hiding three of them behind one hardcoded `True`."""
    decision, suspended = _decide(_book())  # sanity: the modern shape
    assert decision.allowed
    legacy = {"kind": "book", "book_verdict": "ACCEPT", "generated_at": "2026-09-08T10:53:22+00:00"}
    decision, suspended = _decide(legacy)
    assert decision.allowed, "suspension is not refusal; a rule that was not applied says nothing"
    assert suspended == (
        "§3 滑点压力 5.5 档",
        "§3 与在跑的书 corr < 0.5",
        "§3 换手 ≤ 3x 主账本",
    )
    named = {condition.condition for condition in SUSPENDED}
    assert set(suspended) <= named, "a suspension the SUSPENDED table does not explain is a hole"


def test_each_limit_refuses_on_its_own() -> None:
    """One per condition, so a fix that wires up one field and leaves two hardcoded cannot pass."""
    stressed = _book(slippage_stress={"decision_slippage_bps": 5.5, "pass": False, "reasons": ["delta_oos_sharpe"]})
    decision, suspended = _decide(stressed)
    assert not decision.allowed and suspended == ()
    assert decision.reasons == ("D-018: slippage stress at 5.5 bps does not hold",)

    crowded = _book(max_correlation_with_running=0.62)
    decision, suspended = _decide(crowded)
    assert not decision.allowed and suspended == ()
    assert decision.reasons == ("§3: correlation with a running book >= 0.5",)

    churning = _book(turnover_ratio_to_main=4.0)
    decision, suspended = _decide(churning)
    assert not decision.allowed and suspended == ()
    assert decision.reasons == ("§3: turnover above 3x the main book",)


def test_a_null_measurement_suspends_and_is_never_read_as_zero() -> None:
    """`max_correlation_with_running: null` means no running book was measurable.

    0.0 is the passing value, so reading a null as 0.0 would turn "we could not compare it against
    anything" into "it is uncorrelated with everything" - a fail-open dressed as a measurement, and
    exactly the shape the hardcoded `0.0` had.
    """
    decision, suspended = _decide(_book(max_correlation_with_running=None, turnover_ratio_to_main=None))
    assert suspended == ("§3 与在跑的书 corr < 0.5", "§3 换手 ≤ 3x 主账本")
    assert decision.allowed, "suspended, which is what the SUSPENDED table is for - not silently judged"

    # And the slippage gate's own null (no 5.5 level declared in costs.yaml) suspends the same way.
    _decision, suspended = _decide(_book(slippage_stress={"decision_slippage_bps": 5.5, "pass": None}))
    assert suspended == ("§3 滑点压力 5.5 档",)


def test_a_boolean_is_not_a_correlation() -> None:
    """`True` is an `int` in Python, and `True < 0.5` is False - a corrupt field must not pass."""
    _decision, suspended = _decide(_book(max_correlation_with_running=True, turnover_ratio_to_main=True))
    assert suspended == ("§3 与在跑的书 corr < 0.5", "§3 换手 ≤ 3x 主账本")


def test_the_replay_reports_how_many_pointers_each_condition_can_now_decide() -> None:
    """The artefact has to show the split, or "Phase 1 delivered it" is a claim with no number."""
    reports = {
        "reports/research/book-new.json": _book(),
        "reports/research/book-old.json": {"kind": "book", "book_verdict": "ACCEPT"},
    }
    adoptions = {"reports/research/book-new.json": "2026-10-01", "reports/research/book-old.json": "2026-09-08"}
    result = replay_adoptions(reports, adoptions)
    assert result.passes_ac_g0
    for condition in JUDGEABLE[Event.BOOK]:
        assert any(
            line.startswith(f"{condition}：1 份指针**已可判定**") and "另有 1 份" in line for line in result.reproduced
        ), f"{condition} is not reported as judged-vs-suspended: {result.reproduced}"


def test_a_real_limit_breach_is_a_finding_and_not_a_blind_spot() -> None:
    """AC-G0's teeth: an adopted pointer the rules would have refused has to fail the replay.

    Filing "the correlation was 0.62" under "we could not tell" is the wastebasket `Difference.attributed`
    was tightened to stop, and it is the failure mode this whole change would have if a breach were
    routed back into the suspension list.
    """
    reports = {"reports/research/book-crowded.json": _book(max_correlation_with_running=0.62)}
    result = replay_adoptions(reports, {"reports/research/book-crowded.json": "2026-10-01"})
    assert [d.rules_say for d in result.differences] == ["§3: correlation with a running book >= 0.5"]
    assert not result.passes_ac_g0
