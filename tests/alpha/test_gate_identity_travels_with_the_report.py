"""A report must say WHICH gate produced its threshold (2026-09-08 audit).

`decide()` compares the OOS Sharpe against `oos_selection.threshold_annual` as stored in the report,
not against a freshly computed one.  When KILL-Q3 replaced E[max] with the (1-alpha) quantile, every
report already on disk kept the number the old gate produced - including the one the registry cites,
written three hours and twenty minutes before the fix landed.  Its stored 1.1446 reproduces
`expected_max_sharpe` to ten decimal places; the current gate gives 1.4684 for the same inputs.  The
headline cleared both, so nothing was wrong with the verdict - but nothing in the artefact said which
ruler it was measured with, and the sha256 pin makes that silence durable.

The fix is one field and one refusal: the threshold carries the name of the function that produced it,
and a report whose gate `decide()` does not recognise cannot PASS on that comparison.
"""

from __future__ import annotations

import math

import numpy as np

from starquant_alpha.validation.multiple_testing import SELECTION_GATE, oos_selection_threshold
from starquant_alpha.validation.verdict import decide

BPY = 8760.0


def _returns(sharpe_annual: float, n: int = 44_995, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 0.01, size=n)
    values = values - values.mean()
    return values + sharpe_annual / math.sqrt(BPY) * values.std(ddof=1)


def _report(selection: dict[str, object], oos: float = 1.8) -> dict[str, object]:
    return {
        "walk_forward": {"oos_sharpe": oos, "oos_t_stat": 4.0, "fold_consistency": 1.0},
        "multiple_testing": {"pbo": 0.1, "grid_trials": 8},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.5},
        "oos_selection": selection,
    }


def test_the_threshold_names_the_function_that_produced_it() -> None:
    result = oos_selection_threshold(_returns(1.6), n_trials=125, bars_per_year=BPY)

    assert result["gate"] == SELECTION_GATE == "max_sharpe_quantile"


def test_a_report_written_under_the_retired_gate_cannot_pass_on_it() -> None:
    """The shape of tsmom-validation-20260906T093705Z: a threshold with no gate named."""
    verdict, reasons = decide(_report({"threshold_annual": 1.1446, "n_trials": 125}))

    assert verdict == "FAIL"
    assert any("gate" in reason for reason in reasons)


def test_a_report_carrying_the_current_gate_is_judged_on_its_number() -> None:
    verdict, reasons = decide(_report({"threshold_annual": 1.1446, "n_trials": 125, "gate": SELECTION_GATE}))

    assert (verdict, reasons) == ("PASS", [])


def test_an_unrecognised_gate_is_refused_rather_than_trusted() -> None:
    verdict, reasons = decide(_report({"threshold_annual": 1.1446, "n_trials": 125, "gate": "something_else"}))

    assert verdict == "FAIL"
    assert any("something_else" in reason for reason in reasons)


def test_the_refusal_is_about_the_gate_and_not_about_the_number() -> None:
    """A stale gate whose threshold the candidate misses is still reported as a miss, not only as stale."""
    verdict, reasons = decide(_report({"threshold_annual": 2.5, "n_trials": 125}, oos=1.0))

    assert verdict == "FAIL"
    assert any("gate" in reason for reason in reasons)
    assert any("deflated threshold" in reason for reason in reasons)
