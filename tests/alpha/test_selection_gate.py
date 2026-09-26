"""D-028: the verdict gains a condition that is actually sensitive to cross-round selection."""

from __future__ import annotations

import math

import numpy as np

from starquant_alpha.validation.multiple_testing import SELECTION_GATE, oos_selection_threshold, sampling_variance
from starquant_alpha.validation.verdict import VerdictThresholds, decide

BPY = 8760.0


def _returns(sharpe_annual: float, n: int = 44_995, seed: int = 0) -> np.ndarray:
    """A return series with (very nearly) the requested annualised Sharpe."""
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 0.01, size=n)
    values = values - values.mean()
    return values + sharpe_annual / math.sqrt(BPY) * values.std(ddof=1)


def test_threshold_rises_with_the_number_of_configurations_tried() -> None:
    returns = _returns(1.6)
    thresholds = [
        oos_selection_threshold(returns, n_trials=n, bars_per_year=BPY)["threshold_annual"] for n in (1, 10, 50, 100)
    ]
    assert thresholds[0] == 0.0, "a single trial cannot be a selection"
    assert thresholds[1] < thresholds[2] < thresholds[3], "each extra configuration raises the bar"
    assert 0.8 < thresholds[3] < 1.5, "50-100 trials on five years of hourly data is about one Sharpe point"


def test_threshold_falls_as_the_out_of_sample_window_grows() -> None:
    """More evidence, not more configurations, is what lowers the bar."""
    short = oos_selection_threshold(_returns(1.6, n=8_760), n_trials=50, bars_per_year=BPY)["threshold_annual"]
    long = oos_selection_threshold(_returns(1.6, n=44_995), n_trials=50, bars_per_year=BPY)["threshold_annual"]
    assert short > long
    assert math.isclose(
        oos_selection_threshold(_returns(1.6), n_trials=50, bars_per_year=BPY)["variance"],
        sampling_variance(1.6 / math.sqrt(BPY), 44_995),
        rel_tol=0.2,
    )


def test_degenerate_inputs_do_not_produce_a_threshold() -> None:
    empty = oos_selection_threshold(np.array([]), n_trials=50, bars_per_year=BPY)
    assert empty["threshold_annual"] is None and empty["n_obs"] == 0
    flat = oos_selection_threshold(np.zeros(1000), n_trials=50, bars_per_year=BPY)
    assert flat["threshold_annual"] is None


def _report(oos: float, threshold: float | None, **over: object) -> dict:
    report = {
        "walk_forward": {"oos_sharpe": oos, "oos_t_stat": 3.5, "fold_consistency": 1.0},
        "multiple_testing": {"dsr_p_value": 0.9, "pbo": None, "grid_trials": 1},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.2},
    }
    if threshold is not None:
        # `gate` because a threshold without one is refused since 2026-09-08; these tests are about
        # the comparison, so they hand `decide` the well-formed block `oos_selection_threshold` writes.
        report["oos_selection"] = {"threshold_annual": threshold, "n_trials": 90, "gate": SELECTION_GATE}
    report.update(over)
    return report


def test_a_strategy_that_only_clears_d020_is_refused_once_enough_configurations_were_tried() -> None:
    """The case D-020 alone would pass: OOS 1.05 over five years, after ninety configurations."""
    verdict, reasons = decide(_report(1.05, 1.10))
    assert verdict == "FAIL" and any("deflated threshold" in r for r in reasons)
    assert decide(_report(1.05, None))[0] == "PASS", "without the block the old rule stands"
    assert decide(_report(1.60, 1.10))[0] == "PASS", "a real margin still passes"


def test_the_gate_can_be_turned_off_but_is_on_by_default() -> None:
    assert VerdictThresholds().enforce_oos_selection is True
    off = VerdictThresholds(enforce_oos_selection=False)
    assert decide(_report(1.05, 1.10), off)[0] == "PASS"


def test_the_t_statistic_is_documented_as_a_short_sample_guard_not_a_second_gate() -> None:
    """It is Sharpe x sqrt(years) to within 0.1% on hourly returns, so it cannot be independent.

    D-P2 (2026-09-06) stopped enforcing it: a guard that fails a candidate is a gate whatever the
    docstring calls it.  The selection threshold is what carries the deflation now.  Full contract
    in tests/alpha/test_t_stat_reported_not_enforced.py.
    """
    import starquant_alpha.validation.verdict as module

    assert "short-sample guard" in (module.__doc__ or "")
    verdict, reasons = decide(_report(1.60, 1.10, walk_forward={"oos_sharpe": 1.60, "oos_t_stat": 1.2}))
    assert verdict == "PASS" and not reasons
