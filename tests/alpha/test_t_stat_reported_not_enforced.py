"""D-P2 (2026-09-06): the Newey-West t is reported, never enforced.

The deep-analysis report's KILL-R17 said it three times and the code kept the gate anyway: on
hourly net returns the NW t equals the Sharpe times the square root of years to within 0.1%, so
``t >= 2`` beside ``Sharpe >= 1`` over a five-year window is not a second condition - it is the
first one restated, and it only bites below four years.  Keeping it there let a report fail for a
reason that was already counted, and made ``PASS`` look like it had cleared two independent bars.

What is *not* dropped: a report that carries no ``oos_t_stat`` at all still cannot pass.  That is a
completeness requirement on the artefact, not a significance test - "reported" means it has to be
reported.  25 of the 47 archived reports predate the field and this guard is what keeps them out.

Pre-registered before the change (T-R1-3, docs/analysis/2026-09-06-remediation-execution-plan.md):
recomputing every archived report under these semantics must flip zero verdicts.  Measured: 47
reports, 0 flips.  ``test_no_archived_verdict_changes`` is that measurement, kept as a test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starquant_alpha.validation.multiple_testing import SELECTION_GATE
from starquant_alpha.validation.verdict import VerdictThresholds, decide

ROOT = Path(__file__).resolve().parents[2]

# When D-043 landed: commit 86a9f673, which added `cap_unselected_at_weak`.  From this instant a
# report's stored `verdict` is the CAPPED one, and before it the uncapped one - so the archive holds
# two kinds and every guard below has to say which it is judging.  The first two reports written on
# the far side of it are the 2026-09-17 embargo arms, whose stored verdict is WEAK_PASS rather than
# the PASS every earlier tsmom report at `grid_size` 2 carries; without this line they read as ten
# flips plus two verdicts that "changed for no reason", which is the guard mistaking a rule that has
# landed for a rule that is leaking.  A timestamp rather than a name list, because the set of reports
# on the far side grows with every run and a list would have to be edited by every future one.
D043_LANDED = datetime(2026, 9, 16, 17, 30, 28, tzinfo=UTC)

# D-043 (2026-09-17): the ten archived reports whose stored PASS the unselected-evidence cap turns
# into WEAK_PASS.  Listed by name rather than counted, because the guard below is pre-registered and
# "how many flipped" is the one thing a widened guard can hide.  Every entry is tsmom at grid_size 2:
# eight carry `oos_is_full_sample_tail: true`, two carry a PBO the small grid exempted.  Re-deriving
# any of them under a real grid is what takes it OFF this list - the list shrinking is the repair.
D043_CAPPED = frozenset(
    {
        "tsmom-validation-20260903T181803Z.json",
        "tsmom-validation-20260904T020211Z.json",
        "tsmom-validation-20260908T105259Z.json",
        "tsmom-validation-20260908T182204Z.json",
        "tsmom-validation-20260909T055023Z.json",
        "tsmom-validation-20260909T055957Z.json",
        "tsmom-validation-20260913T182325Z.json",
        "tsmom-validation-20260913T201638Z.json",
        "tsmom-validation-20260914T174319Z.json",
        "tsmom-validation-20260914T174503Z.json",
    }
)
# The same rules with D-043 switched off: what `decide` said the day before it existed.  Used to
# prove the cap is the ONLY thing that moved, rather than asserting that nothing moved at all.
BEFORE_D043 = VerdictThresholds(cap_unselected_at_weak=False)


def _written_after_d043(report: dict[str, Any]) -> bool:
    """Was this report's stored `verdict` produced with the cap already on?

    A report with no readable `generated_at` is treated as older, which is the safe direction: it
    keeps the pre-registered "nothing flips" guard applying to it rather than exempting it.
    """
    try:
        return datetime.fromisoformat(str(report.get("generated_at", ""))) >= D043_LANDED
    except ValueError:
        return False


def _rules_that_produced(report: dict[str, Any]) -> VerdictThresholds | None:
    """The thresholds a report's own stored verdict was decided under.  `None` means today's."""
    return None if _written_after_d043(report) else BEFORE_D043


def _clean(**walk_forward: Any) -> dict[str, Any]:
    """A report that clears every gate except whatever the caller overrides."""
    wf = {"oos_sharpe": 1.5, "oos_t_stat": 3.0, "fold_consistency": 0.8, **walk_forward}
    return {
        "walk_forward": wf,
        "multiple_testing": {"dsr_p_value": 0.9, "pbo": None, "grid_trials": 1},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.2},
    }


def test_a_low_t_no_longer_fails_a_candidate_that_clears_every_other_gate() -> None:
    """The old rule failed this at t 1.2 for a reason the Sharpe gate had already counted."""
    verdict, reasons = decide(_clean(oos_t_stat=1.2))

    assert verdict == "PASS"
    assert not any("oos_t_stat" in r for r in reasons)


def test_the_strong_pass_no_longer_requires_the_t_statistic() -> None:
    """t 1.8 used to cap a Sharpe 1.5 book at WEAK_PASS; the cap was the Sharpe restated."""
    assert decide(_clean(oos_t_stat=1.8))[0] == "PASS"


def test_a_weak_sharpe_is_still_only_a_weak_pass() -> None:
    """Demoting the t must not promote anything: the Sharpe gate is untouched."""
    assert decide(_clean(oos_sharpe=0.8, oos_t_stat=4.0))[0] == "WEAK_PASS"


def test_a_report_without_the_t_statistic_still_cannot_pass() -> None:
    """Completeness, not significance - and the reason has to say which."""
    report = _clean()
    del report["walk_forward"]["oos_t_stat"]

    verdict, reasons = decide(report)

    assert verdict == "FAIL"
    assert any("oos_t_stat" in r and "not reported" in r for r in reasons)


def test_the_thresholds_no_longer_carry_a_t_bar() -> None:
    """A threshold nothing reads is a rule that looks enforced.  Net rule change <= 0 (KILL-R17)."""
    from starquant_alpha.validation.verdict import VerdictThresholds

    assert not hasattr(VerdictThresholds(), "pass_oos_t")
    assert not hasattr(VerdictThresholds(), "weak_oos_t")


def test_the_family_p_value_is_in_the_selection_reason() -> None:
    """A verdict that says only 'below the threshold' cannot say how surprising the number is."""
    report = _clean(oos_sharpe=1.2)
    report["oos_selection"] = {
        "threshold_annual": 1.5,
        "n_trials": 125,
        "alpha": 0.05,
        "p_family": 0.42,
    }

    verdict, reasons = decide(report)

    assert verdict == "FAIL"
    selection = [r for r in reasons if "deflated threshold" in r]
    assert len(selection) == 1
    assert "p_family=0.42" in selection[0]


def test_a_selection_reason_survives_a_report_without_p_family() -> None:
    """Reports written before the field exists still have to produce a readable reason."""
    report = _clean(oos_sharpe=1.2)
    report["oos_selection"] = {"threshold_annual": 1.5, "n_trials": 93}

    verdict, reasons = decide(report)

    assert verdict == "FAIL"
    assert any("deflated threshold" in r for r in reasons)


def _archived_reports(with_gate: bool | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Every archived report written under the current rules - the ones carrying an ``oos_selection`` block.

    ``with_gate`` narrows to reports that name their gate (True) or cannot (False); ``None`` keeps
    both.  The first report to name one is tsmom-validation-20260908T105259Z, re-derived the day the
    gate got its name, so from then on the archive holds both kinds and a test has to say which it
    is about - a pin written for "none of them can" went vacuous-by-inversion the moment one could.
    """
    out = []
    for path in sorted(ROOT.glob("reports/research/**/*-validation-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        selection = report.get("oos_selection") or {}
        if not selection.get("n_trials"):
            continue
        if with_gate is not None and bool(selection.get("gate")) != with_gate:
            continue
        out.append((path.name, report))
    return out


def test_no_archived_verdict_changes_for_any_reason_but_the_gate_rename() -> None:
    """T-R1-3, pre-registered: 47 archived reports, 0 flips - re-stated once the gate got a name.

    Anchored to the stored ``verdict`` of every report written under the current rules - the ones
    carrying an ``oos_selection`` block.  Older reports are excluded because the rules they were
    judged by no longer exist (9 of them already disagree with ``decide`` today, and did before
    this change); excluding them here is not a way to hide a flip: the pre-registered measurement
    covered all 47 and found none.

    2026-09-08: ``decide`` now refuses a threshold whose gate it cannot name, and no archived report
    carries one, so judged as-is every one of them FAILs.  That flip is the point of the change and is
    asserted separately below.  Dropping these reports from the check instead would have left the
    pre-registered guard asserting nothing at all, so the comparison is made on the one axis the
    change does not touch: supply the gate, and the stored verdict must still come back.

    2026-09-17 (D-043): judged with the unselected-evidence cap switched OFF, which is what "for no
    reason but" now means.  The cap's own flips are asserted by name in the two tests below rather
    than absorbed here - a guard that silently grows a new exemption every time a rule lands is a
    guard that has stopped being pre-registered.
    """
    checked = 0
    for name, report in _archived_reports():
        checked += 1
        with_gate = {**report, "oos_selection": {**report["oos_selection"], "gate": SELECTION_GATE}}
        assert decide(with_gate, _rules_that_produced(report))[0] == report["verdict"], name

    assert checked >= 12


def test_d043_flips_exactly_the_reports_it_was_measured_on() -> None:
    """The cap's blast radius, pinned by name: 10 reports, all PASS -> WEAK_PASS, nothing else moves.

    Both directions are asserted.  A report on the list that stops flipping has either been
    re-derived under a real grid (the repair) or the cap has gone quietly vacuous; a report off the
    list that starts flipping is a rule reaching further than it was measured to.  Either way the
    list is the thing that has to be edited, in the commit that says why.
    """
    flipped: set[str] = set()
    for path in sorted(ROOT.glob("reports/research/**/*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or "verdict" not in report:
            continue
        walk_forward = report.get("walk_forward")
        if not isinstance(walk_forward, dict) or "oos_sharpe" not in walk_forward:
            continue
        if _written_after_d043(report):
            # Written with the cap already on, so it cannot be one of the reports the cap FLIPPED -
            # its stored verdict is the capped one.  That it agrees with `decide` is asserted by the
            # two guards above; asserting it here as well would make the list grow by one per run and
            # stop meaning "the blast radius D-043 was measured on".
            continue
        before = decide(report, BEFORE_D043)[0]
        after, reasons = decide(report)
        if before == after:
            continue
        flipped.add(path.name)
        assert (before, after) == ("PASS", "WEAK_PASS"), f"{path.name}: {before} -> {after}"
        assert reasons, f"{path.name}: a cap with no reason is indistinguishable from the Sharpe bar"

    assert flipped == D043_CAPPED, (
        f"unexpected: {sorted(flipped - D043_CAPPED)}, missing: {sorted(D043_CAPPED - flipped)}"
    )


def test_the_archive_holds_reports_from_both_sides_of_d043() -> None:
    """The split above is only doing work while both sides are populated.

    `_written_after_d043` returning False for everything would silently restore the pre-D-043 file
    and every guard in it would still pass - the vacuous-by-inversion shape this module already hit
    once, when a pin written for "no archived report names its gate" survived the first one that did.
    So both sides are asserted, and the far side is asserted to carry a WEAK_PASS earned by the cap
    rather than by the Sharpe bar: that is what makes it a different case from the near side at all.
    """
    reports = _archived_reports()
    after = [(name, r) for name, r in reports if _written_after_d043(r)]
    before = [(name, r) for name, r in reports if not _written_after_d043(r)]

    assert before, "no report predates D-043; the pre-registered guard has nothing to guard"
    assert after, "no report postdates D-043; the split is vacuous and the file has silently reverted"

    for name, report in after:
        # Stored verdict == today's rules, which is what `_rules_that_produced` claims for this side.
        assert decide(report)[0] == report["verdict"], name
        if report["verdict"] == "WEAK_PASS" and report["walk_forward"].get("oos_sharpe", 0.0) >= 1.0:
            assert decide(report, BEFORE_D043)[0] == "PASS", f"{name}: uncapped it should have been PASS"


def test_the_report_the_live_registry_cites_is_one_of_them() -> None:
    """Stated on its own because it is the finding, not a side effect.

    The shipped tsmom evidence clears every numeric gate and is still a single-configuration
    backtest: 5 folds, `grid_size` 2, every fold picking the same point, `selection_consistent`
    true.  `oos_is_full_sample_tail` said so in the artefact from the day the field existed, and
    `research validate` printed the sentence to the terminal - `decide` was the only reader that
    could not see it, which is why the registry could carry a PASS the report itself qualified.
    """
    cited = ROOT / "reports/research/tsmom-validation-20260913T182325Z.json"
    report = json.loads(cited.read_text(encoding="utf-8"))
    assert report["walk_forward"]["oos_is_full_sample_tail"] is True
    assert decide(report, BEFORE_D043)[0] == "PASS"
    verdict, reasons = decide(report)
    assert verdict == "WEAK_PASS"
    assert any("full_sample_tail" in reason for reason in reasons)


def test_every_archived_report_is_refused_on_the_gate_it_cannot_name() -> None:
    """The 2026-09-08 finding, kept as a test: these thresholds outlived the rule that produced them.

    Scoped to the reports that cannot name their gate.  The ones re-derived the same day DO name
    it and are judged on their numbers - asserted next, so this pin cannot go quietly vacuous once
    the archive turns over.
    """
    reports = _archived_reports(with_gate=False)
    assert reports, "no archived report lacks a gate name"
    for name, report in reports:
        verdict, reasons = decide(report)
        assert verdict == "FAIL", name
        assert any("gate" in reason for reason in reasons), name


def test_a_report_that_names_its_gate_is_judged_on_its_numbers() -> None:
    """The other half of the same finding: naming the gate is what lets ``decide`` read the threshold.

    On the numbers, with D-043 off (`D043_CAPPED` owns the cap's flips).  The assertion this test
    exists for is the gate one below it: no report that names its gate may be refused FOR the gate.
    """
    reports = _archived_reports(with_gate=True)
    assert reports, "no archived report names its gate yet"
    for name, report in reports:
        verdict, reasons = decide(report, _rules_that_produced(report))
        assert verdict == report["verdict"], name
        assert not any("gate" in reason for reason in reasons), name
