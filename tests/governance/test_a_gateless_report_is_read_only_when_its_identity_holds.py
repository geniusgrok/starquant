"""Operator ruling 2026-09-14 (Q1): a pre-`gate` report may be recomputed, but only if it proves its rule.

KILL-Q3 put `gate` into `oos_selection` so a stored threshold could not outlive the rule that made it,
and `read_gate` refuses any block that does not carry it.  That refusal is correct and it is also
total: all seven mined validation reports predate the field, so the production recheck has no opinion
about any of them - including `mined_594a12f9307a15d9`, the only candidate this pipeline has ever
passed, whose admissibility is the subject of an open ruling.

The operator's ruling is that the identity may stand in for the label, and the reason it may is that
the identity is FALSIFIABLE.  `threshold_annual` is the raw quantile times `sqrt(bars_per_year)`, so
`threshold_annual / max_sharpe_quantile(n, variance, alpha)` recovers the annualisation - and if the
threshold had been produced by any other rule, that ratio is not `sqrt(bars_per_year)`.

Measured on the seven, before the rule was written:

    594a12f9  1h  implied 93.594872  =  sqrt(8760) to 0.000e+00   <- the quantile rule
    three 1h  1h  implied 75.362971  =  0.8052 x sqrt(8760)
    three 1d  1d  implied 15.317012  =  0.8017 x sqrt(365)

~0.805 is `E[max] / quantile(0.95)`: those six were written under the EXPECTATION, which is what
KILL-Q3 replaced because it "admitted pure noise at 43.5%".  So the check does not wave the seven
through - it admits the one report that was produced under today's rule and refuses the six that were
not, which is precisely the discrimination the `gate` field exists to make.  Recovering it from the
numbers is only possible because the alternative rule leaves a different fingerprint.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from starquant_alpha.validation.multiple_testing import SELECTION_GATE, max_sharpe_quantile
from starquant_governance.family_gate import PASS, UNREADABLE, read_gate

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

REPORTS = Path("reports/research")


def _block(*, n_trials: int = 575, variance: float = 2.200184145624143e-05, scale: float, gate: str | None) -> dict:
    quantile = max_sharpe_quantile(n_trials, variance, 0.05)
    block: dict[str, object] = {
        "oos_sharpe_annual": 1.786223252863809,
        "variance": variance,
        "threshold_annual": quantile * scale,
        "n_trials": n_trials,
        "alpha": 0.05,
    }
    if gate is not None:
        block["gate"] = gate
    return {"oos_selection": block, "ledger": {"ledger_trials": 0}, "interval": "1h"}


def test_a_labelled_report_is_still_read_without_consulting_the_identity() -> None:
    """The label wins where it exists; this ruling only covers its absence."""
    report = _block(scale=math.sqrt(8760), gate=SELECTION_GATE)

    assert read_gate("mined_x", report, [], range_end_granularity_days=FOLD_DAYS).status == PASS


def test_a_gateless_report_whose_identity_holds_is_now_read() -> None:
    report = _block(scale=math.sqrt(8760), gate=None)

    reading = read_gate("mined_x", report, [], range_end_granularity_days=FOLD_DAYS)

    assert reading.status == PASS, reading.why


def test_a_gateless_report_whose_identity_fails_is_still_refused() -> None:
    """0.8052 x sqrt(8760): the `expected_max` fingerprint the six pre-KILL-Q3 reports carry."""
    report = _block(scale=0.8052 * math.sqrt(8760), gate=None)

    reading = read_gate("mined_x", report, [], range_end_granularity_days=FOLD_DAYS)

    assert reading.status == UNREADABLE
    assert "75.3" in reading.why or "annualisation" in reading.why, reading.why


def test_a_gateless_report_with_no_interval_is_refused() -> None:
    """Without the interval there is no `sqrt(bars_per_year)` to compare against, so nothing is proven."""
    report = _block(scale=math.sqrt(8760), gate=None)
    del report["interval"]

    assert read_gate("mined_x", report, [], range_end_granularity_days=FOLD_DAYS).status == UNREADABLE


def test_a_report_labelled_with_some_other_gate_is_refused_identity_or_not() -> None:
    """An explicit wrong label is a statement; the identity does not get to overrule it."""
    report = _block(scale=math.sqrt(8760), gate="expected_max_sharpe")

    assert read_gate("mined_x", report, [], range_end_granularity_days=FOLD_DAYS).status == UNREADABLE


def test_the_ruling_admits_exactly_one_of_the_seven_real_reports() -> None:
    """The whole point of the ruling, on the artefacts it was made about."""
    readable = {}
    for path in sorted(REPORTS.glob("mined_*-validation-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = path.name.split("-validation")[0]
        readable[name] = read_gate(name, payload, [], range_end_granularity_days=FOLD_DAYS).status

    admitted = [name for name, status in readable.items() if status != UNREADABLE]
    assert admitted == ["mined_594a12f9307a15d9"], (
        "the identity must admit the one report written under today's rule and refuse the six written "
        f"under the expectation it replaced: {readable}"
    )
