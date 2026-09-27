"""Which families would ship if D-028 were switched off, and which would still not.

The operator has asked five times whether the verdict is simply too strict.  The first four
answers were a word; the fifth (PR #66) made the *power* of the gate a number.  This file
answers the other half - **which candidates the gate is actually holding back** - and it
exists because the answer was read wrong on 2026-09-18.

The 2026-09-17 nine-family rerun is written up under a heading that says "只差 selection gate
的只有 residual".  The body of that same section, at `docs/RESEARCH_LOG.md:11567`, says:

    真正「只被多重检验门拦住」的是 flow（0.65 对 1.33，只挂这一条）与 residual。

Two, not one.  An analysis quoted the heading, concluded the operator's suspicion was REFUTED,
and only an adversarial review caught it.  A sentence cannot stop that happening again; a test
over the real reports can, because it recomputes the count instead of restating it.

**The counterfactual needs no new code.**  `VerdictThresholds(enforce_oos_selection=False)` is
exactly "the D-028 gate at 0.00" - it drops both the deflated-threshold reason and the
completeness reason that fires when a report predates the current gate.  Everything else in
`decide` stays where it is, which is the point: a family that still fails is failing on
fold consistency, CPCV, PBO, cost stress or the 0.5 Sharpe floor, none of which are D-028.

**"Ship" is the operator's caliber, ruled 2026-09-18.**  `registry.py` admits
`{"PASS", "WEAK_PASS"}`, so WEAK_PASS ships and the count is taken against that set - not
against PASS alone.  Under the narrower reading the count is 1 and the suspicion looks refuted;
under the shipped one it is 2 and it does not.  The ruling is a fact about this repository, so
it is asserted here rather than left to whoever reads the table next.

What this file does NOT claim: that the gate should be relaxed.  Alpha is operator-signed at
0.05, and six of the nine families fail for reasons D-028 never touches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starquant_alpha.validation.verdict import VerdictThresholds, decide

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports" / "research"

# The 2026-09-17 rerun: every hand-written signal on one pipeline, `--universe pit`, 206 symbols
# x 50,033 bars.  Where a family has more than one report from that run, the most favourable one
# is taken - a family is only "held back" if its BEST available evidence is held back.
RERUN_GLOB = "*-validation-20260917T09*.json"

# What ships, per `starquant_alpha/registry.py`.  Operator ruling 2026-09-18.
SHIPS = frozenset({"PASS", "WEAK_PASS"})

# The two the gate alone is holding back, and the six it is not.  Written out rather than
# derived so that a change in either direction fails loudly instead of quietly re-deriving.
GATE_ALONE = frozenset({"flow", "residual"})
FAIL_ANYWAY = frozenset({"breakout", "carry", "chanlun", "meanrev", "pairs", "xsmom"})


def _best_report_per_family() -> dict[str, dict]:
    """Highest OOS Sharpe per family among that run's reports."""
    best: dict[str, dict] = {}
    for path in sorted(REPORTS.glob(RERUN_GLOB)):
        family = path.name.split("-validation-")[0]
        report = json.loads(path.read_text())
        oos = (report.get("walk_forward") or {}).get("oos_sharpe")
        if oos is None:
            continue
        current = best.get(family)
        if current is None or oos > (current.get("walk_forward") or {}).get("oos_sharpe", float("-inf")):
            report["_path"] = path.name
            best[family] = report
    return best


@pytest.fixture(scope="module")
def rerun() -> dict[str, dict]:
    reports = _best_report_per_family()
    if len(reports) < 9:
        pytest.skip(f"the 2026-09-17 rerun is not in this checkout ({len(reports)} families found)")
    return reports


def _is_selection_reason(reason: str) -> bool:
    return "deflated threshold" in reason or "oos_selection gate is" in reason


def test_every_family_in_the_rerun_is_failing_before_the_gate_is_switched_off(rerun: dict[str, dict]) -> None:
    """The baseline the counterfactual is measured against: only the incumbent clears today."""
    shipping = {name for name, report in rerun.items() if decide(report)[0] in SHIPS}
    assert shipping == {"tsmom"}, f"expected only the incumbent to ship today, got {sorted(shipping)}"


def test_switching_off_d028_lets_exactly_flow_and_residual_ship(rerun: dict[str, dict]) -> None:
    """The count that was read as 1 and is 2.  `docs/RESEARCH_LOG.md:11567` agrees."""
    off = VerdictThresholds(enforce_oos_selection=False)
    flipped = {
        name for name, report in rerun.items() if decide(report)[0] not in SHIPS and decide(report, off)[0] in SHIPS
    }
    assert flipped == GATE_ALONE, (
        f"expected {sorted(GATE_ALONE)} to be held back by D-028 alone, got {sorted(flipped)}. "
        "If this changed because new evidence landed, update the constant and say so in "
        "docs/RESEARCH_LOG.md; if it changed because a threshold moved, that is an R10 rule change."
    )


def test_the_narrower_reading_of_pass_is_what_made_the_count_look_like_one(rerun: dict[str, dict]) -> None:
    """Why the caliber had to be ruled on rather than assumed.

    Under `{"PASS"}` alone the count is 1 (residual), which reads as "the gate is not the
    problem".  Under what `registry.py` actually admits it is 2.  Both numbers are correct
    arithmetic over the same reports; only one of them is the question the operator asked.
    """
    off = VerdictThresholds(enforce_oos_selection=False)
    strict = {
        name for name, report in rerun.items() if decide(report)[0] not in SHIPS and decide(report, off)[0] == "PASS"
    }
    assert strict != GATE_ALONE, "the two calibers no longer differ; this test has nothing left to guard"
    assert len(strict) < len(GATE_ALONE), f"the strict reading should be the smaller one, got {sorted(strict)}"


def test_the_other_six_fail_for_reasons_d028_never_touches(rerun: dict[str, dict]) -> None:
    """Six of nine are not a gate story, and this says what each one IS."""
    off = VerdictThresholds(enforce_oos_selection=False)
    for name in sorted(FAIL_ANYWAY):
        verdict, reasons = decide(rerun[name], off)
        assert verdict == "FAIL", f"{name} was expected to fail with D-028 off, got {verdict}"
        assert reasons, f"{name} failed with no reasons given"
        leftovers = [r for r in reasons if _is_selection_reason(r)]
        assert not leftovers, f"{name} still carries a selection-gate reason with the gate off: {leftovers}"


def test_flow_and_residual_carry_the_selection_gate_and_nothing_else_today(rerun: dict[str, dict]) -> None:
    """The positive form of the same fact, one family at a time.

    `decide` returns every reason it found, so "held back by the gate alone" is checkable
    directly: the live verdict's reason list is exactly one selection-gate entry.
    """
    for name in sorted(GATE_ALONE):
        verdict, reasons = decide(rerun[name])
        assert verdict == "FAIL", f"{name} is not failing today, so this file's premise is stale"
        assert [r for r in reasons if _is_selection_reason(r)] == reasons, (
            f"{name} carries more than the selection gate: {reasons}"
        )
