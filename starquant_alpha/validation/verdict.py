"""Promotion verdict from a validation report (pure rules; thresholds are explicit inputs).

D-020 (2026-09-04, operator decision): the verdict is out-of-sample first.  The walk-forward
OOS Sharpe and the Newey-West t-statistic of the OOS net returns decide PASS / WEAK_PASS;
fold consistency, CPCV negative-path share, PBO (for grids of >= 4) and the doubled-cost
Sharpe are hard gates.  The deflated Sharpe ratio stays in every report but no longer vetoes:
it haircuts the *in-sample* Sharpe for selection, while walk-forward selection already happens
inside the training folds.

D-028 (2026-09-04) closes what that left open.  The Newey-West t was never a second condition:
on hourly net returns it equals the Sharpe times the square root of years to within 0.1%, so over
a five-year window "t >= 2" is looser than the "Sharpe >= 1" beside it, and it only bites below
four years - it is a short-sample guard, and is documented as one.

D-P2 (2026-09-06, operator ruling; docs/analysis/2026-09-06-remediation-execution-plan.md) finishes
that sentence: a short-sample guard that is *enforced* is a second gate no matter what the docstring
calls it, so the t no longer decides anything.  It is reported by the artefact and printed by the
CLI; ``decide`` reads it only to check that it is there at all.  That completeness check is what
keeps the 25 archived reports written before the field existed from passing - "reported" means it
has to be reported.  Pre-registered before the change and measured on all 47 archived reports:
zero verdicts move (T-R1-3; tests/alpha/test_t_stat_reported_not_enforced.py).

The condition that is actually
sensitive to selection deflates the *out-of-sample* Sharpe against the number of distinct
configurations in the strategy's ledger, using the sampling distribution of an OOS Sharpe estimate
as the null rather than the ledger's pooled dispersion.  Reports written before this field exists
carry no ``oos_selection`` block and are not judged by it.  Before D-020 the DSR p-value (<= 0.05 / 0.10) was a veto, and its pooled
variance was degenerate in both directions (near-zero with near-duplicate trials, inflated by
legacy configurations); see docs/RESEARCH_LOG.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starquant_alpha.validation.multiple_testing import SELECTION_GATE


@dataclass(frozen=True)
class VerdictThresholds:
    pass_oos_sharpe: float = 1.0
    weak_oos_sharpe: float = 0.5
    # No t bar: the Newey-West t is reported, never enforced (D-P2).  A threshold nothing reads
    # would still look like a rule to the next person to open this file.
    min_fold_consistency: float = 0.6
    max_cpcv_negative: float = 0.10  # share of CPCV paths with a negative OOS Sharpe
    max_pbo: float = 0.30
    min_cost_stress_sharpe: float = 0.0
    min_trials_for_pbo: int = 4
    enforce_oos_selection: bool = True  # D-028: the OOS Sharpe must clear the deflated threshold
    # D-043 (2026-09-17).  Evidence in which no selection was ever exercised is capped at WEAK_PASS
    # rather than failed.  See `_unselected` for the two shapes and why the cap is not a FAIL.
    cap_unselected_at_weak: bool = True


def _unselected(wf: dict[str, Any], mt: dict[str, Any], t: VerdictThresholds) -> list[str]:
    """D-043: the ways a report can clear every gate without any selection having been exercised.

    Both shapes below were already MEASURED and already REPORTED; neither reached `decide`, so a
    report could carry its own disclaimer and still come back PASS.  They are one rule rather than
    two patches, because they are the same sentence at two levels: the walk-forward never chose a
    parameter, and the grid was too small for CSCV to rank one.  What is missing in both is the
    selection that `oos_sharpe` is being read AS the out-of-sample record of.

    Why a cap and not a FAIL.  A single-configuration backtest is not invalid evidence - it is
    evidence of a fixed rule's performance, which is exactly what WEAK_PASS already means elsewhere
    in this file ("the number is real, the case for it is not the strongest one").  Failing it would
    also retire the shipped tsmom book on a rule about its EVIDENCE rather than about its returns,
    and `registry.evidence_problems` admits WEAK_PASS to live use, so the cap says what it means without
    stopping a loop that is holding positions.

    Blast radius, measured on all 60 archived reports carrying a `walk_forward` block before the
    rule was written (2026-09-17; the glob is recursive, which an earlier count of this was not):
      * `oos_is_full_sample_tail` is absent in 47, True in 10, False in 3.  Eight of the ten are
        PASS today and become WEAK_PASS - every one of them tsmom at `grid_size` 2, including
        `tsmom-validation-20260913T182325Z.json`, which is the report the live registry cites.
        The other two already FAIL for D-020 reasons and are untouched by this.
      * the PBO exemption catches two more (0.5484 and 0.7472 at `grid_trials` 2), both retired
        2026-09-03/04 tsmom runs that nothing points at.  No report trips both.
    Ten flips total, every one PASS -> WEAK_PASS, asserted by name in
    `test_d043_flips_exactly_the_reports_it_was_measured_on`.  A report with neither field is
    untouched, the same way `oos_t_stat` and `oos_selection` leave the reports written before they
    existed alone.  Nothing becomes FAIL, so no verdict in the archive stops allowing live use.
    """
    if not t.cap_unselected_at_weak:
        return []
    out: list[str] = []
    if wf.get("oos_is_full_sample_tail") is True:
        out.append(
            "oos_is_full_sample_tail: no fold had a choice to make (single configuration, or every "
            "fold picked the same one), so this OOS is the tail of one full-sample series"
        )
    pbo, grid_trials = mt.get("pbo"), mt.get("grid_trials", mt.get("n_trials"))
    if pbo is not None and pbo > t.max_pbo and grid_trials is not None and int(grid_trials) < t.min_trials_for_pbo:
        # The exemption below in `decide` stays - CSCV genuinely cannot rank two configurations - but
        # it used to be silent, so shrinking a grid both lowered the DSR denominator and switched this
        # gate off, and the artefact recorded neither as having happened.
        out.append(
            f"pbo {pbo:.2f} > {t.max_pbo} was exempted at {int(grid_trials)} grid trials "
            f"(< {t.min_trials_for_pbo}): the gate did not run rather than passed"
        )
    return out


def decide(report: dict[str, Any], thresholds: VerdictThresholds | None = None) -> tuple[str, list[str]]:
    t = thresholds or VerdictThresholds()
    wf = report.get("walk_forward", {}) or {}
    mt = report.get("multiple_testing", {}) or {}
    cpcv = report.get("cpcv", {}) or {}
    stress = report.get("cost_stress", {}) or {}
    reasons: list[str] = []
    oos = wf.get("oos_sharpe")
    oos_t = wf.get("oos_t_stat")
    consistency = wf.get("fold_consistency")
    negative = cpcv.get("fraction_negative")
    pbo = mt.get("pbo")
    stress_x2 = stress.get("x2")
    if oos is None:
        return "FAIL", ["no out-of-sample Sharpe"]
    if oos < t.weak_oos_sharpe:
        reasons.append(f"oos_sharpe {oos:.2f} < {t.weak_oos_sharpe}")
    if oos_t is None:
        # Completeness, not significance: the value no longer gates, but a report that never
        # measured it predates D-020 and is not judged by these rules at all.
        reasons.append("oos_t_stat not reported: a report that predates D-020 cannot pass")
    selection = report.get("oos_selection") or {}
    threshold = selection.get("threshold_annual")
    gate = selection.get("gate")
    if t.enforce_oos_selection and threshold is not None and gate != SELECTION_GATE:
        # The threshold is read from the artefact, so it outlives the rule that produced it.  KILL-Q3
        # replaced E[max] with the quantile on 2026-09-06 and every report written before that keeps a
        # number ~0.32 lower with nothing in it saying which rule made it.  Completeness, like the
        # `oos_t_stat` refusal above: judged by a gate this function cannot name is not judged.
        reasons.append(
            f"oos_selection gate is {gate!r}, not {SELECTION_GATE!r}: "
            "the threshold predates the current gate and must be re-derived"
        )
    if t.enforce_oos_selection and threshold is not None and oos < threshold:
        p_family = selection.get("p_family")
        surprise = f", p_family={p_family:.4f}" if isinstance(p_family, (int, float)) else ""
        reasons.append(
            f"oos_sharpe {oos:.2f} < the deflated threshold {threshold:.2f} "
            f"at {selection.get('n_trials')} trials{surprise}"
        )
    if consistency is not None and consistency < t.min_fold_consistency:
        reasons.append(f"fold_consistency {consistency:.2f} < {t.min_fold_consistency}")
    if negative is not None and negative > t.max_cpcv_negative:
        reasons.append(f"cpcv fraction_negative {negative:.2f} > {t.max_cpcv_negative}")
    grid_trials = mt.get("grid_trials", mt.get("n_trials"))
    if pbo is not None and pbo > t.max_pbo:
        if grid_trials is not None and int(grid_trials) < t.min_trials_for_pbo:
            # CSCV needs several strategies to rank; with two configurations PBO is a coin flip that only
            # says the two trade places across sub-periods.  Reported, not enforced.
            pass
        else:
            reasons.append(f"pbo {pbo:.2f} > {t.max_pbo}")
    if stress_x2 is not None and stress_x2 < t.min_cost_stress_sharpe:
        reasons.append(f"cost stress x2 sharpe {stress_x2:.2f} < {t.min_cost_stress_sharpe}")
    if reasons:
        return "FAIL", reasons
    if oos < t.pass_oos_sharpe:
        return "WEAK_PASS", []
    # D-043: PASS is the claim that a selection procedure survived out of sample.  When no selection
    # was exercised the number stands and the claim does not, so the cap carries its own reasons -
    # a WEAK_PASS with an empty list would be indistinguishable from one earned on the Sharpe bar.
    unselected = _unselected(wf, mt, t)
    return ("WEAK_PASS", unselected) if unselected else ("PASS", [])
