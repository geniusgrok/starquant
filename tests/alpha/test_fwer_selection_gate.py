"""KILL-Q3 / F2: the D-028 gate is a quantile of the null's maximum, not its expectation.

`oos_selection_threshold` returned ``expected_max_sharpe`` - E[max of N nulls].  A single
noise curve exceeds the expectation of the maximum roughly half the time, so as a gate it
admits noise at ~43.5%, measured on the shipped report's own null.  The fix is one line of
mathematics: solve Phi(x)^N = 1 - alpha for x, which is the alpha-level family-wise bound.

`expected_max_sharpe` itself is deliberately NOT changed - the DSR uses it as a benchmark
Sharpe, where the expectation is the right object.  Only the gate moves.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from starquant_alpha.validation.metrics import normal_cdf
from starquant_alpha.validation.multiple_testing import expected_max_sharpe, oos_selection_threshold
from starquant_alpha.validation.verdict import VerdictThresholds, decide

BPY = 8760.0


def _returns(sharpe_annual: float, n: int = 44_995, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 0.01, size=n)
    values = values - values.mean()
    return values + sharpe_annual / math.sqrt(BPY) * values.std(ddof=1)


def _noise_pass_rate(threshold_annual: float, sigma_annual: float, n_trials: int) -> float:
    """P(max of n_trials independent nulls exceeds the threshold)."""
    return 1.0 - normal_cdf(threshold_annual / sigma_annual) ** n_trials


def test_the_gate_admits_noise_at_the_declared_alpha_not_at_one_half() -> None:
    """The defect, stated as a number: E[max] lets ~43.5% of pure noise through."""
    result = oos_selection_threshold(_returns(1.6), n_trials=93, bars_per_year=BPY, alpha=0.05)
    sigma = math.sqrt(result["variance"] * BPY)

    admitted = _noise_pass_rate(result["threshold_annual"], sigma, 93)

    assert admitted == pytest.approx(0.05, abs=0.005), "the gate must admit noise at alpha, not at half"


def test_the_quantile_threshold_is_strictly_above_the_expectation() -> None:
    """A gate at the expectation of the maximum is below the maximum half the time."""
    returns = _returns(1.6)
    result = oos_selection_threshold(returns, n_trials=93, bars_per_year=BPY, alpha=0.05)
    expectation = expected_max_sharpe(93, result["variance"]) * math.sqrt(BPY)

    assert result["threshold_annual"] > expectation
    assert result["expected_max_annual"] == pytest.approx(expectation, rel=1e-9), "report both, gate on one"


def test_alpha_is_explicit_and_tightening_it_raises_the_bar() -> None:
    returns = _returns(1.6)
    lenient = oos_selection_threshold(returns, n_trials=93, bars_per_year=BPY, alpha=0.10)["threshold_annual"]
    default = oos_selection_threshold(returns, n_trials=93, bars_per_year=BPY)["threshold_annual"]
    strict = oos_selection_threshold(returns, n_trials=93, bars_per_year=BPY, alpha=0.01)["threshold_annual"]

    assert lenient < default < strict
    assert oos_selection_threshold(returns, n_trials=93, bars_per_year=BPY)["alpha"] == 0.05


def test_the_family_p_value_is_reported_so_the_verdict_can_say_why() -> None:
    """`p_family`: the probability that N nulls produce a maximum this large."""
    strong = oos_selection_threshold(_returns(1.9), n_trials=93, bars_per_year=BPY)
    weak = oos_selection_threshold(_returns(0.9), n_trials=93, bars_per_year=BPY)

    assert 0.0 <= strong["p_family"] < 0.05 < weak["p_family"] <= 1.0
    assert strong["p_family"] < weak["p_family"]


def test_one_trial_is_still_not_a_selection() -> None:
    """D-028's own convention, kept: with nothing to select between there is nothing to deflate."""
    result = oos_selection_threshold(_returns(1.6), n_trials=1, bars_per_year=BPY)
    assert result["threshold_annual"] == 0.0
    assert result["p_family"] is not None


def test_the_shipped_book_still_clears_the_stricter_gate() -> None:
    """The change must not be judged only on the strategy it was built to catch.

    tsmom's re-issued evidence is OOS 1.7662 against a null whose annual SD is ~0.44 at 125
    trials.  If the stricter gate rejected it, the honest reading would be that the book has
    no case - so this asserts the number, and would fail loudly if it stopped holding.
    """
    returns = _returns(1.7662)
    result = oos_selection_threshold(returns, n_trials=125, bars_per_year=BPY)

    assert result["threshold_annual"] < 1.7662, "the shipped book must clear its own gate"
    assert result["p_family"] < 0.01


def test_verdict_fails_a_candidate_below_the_quantile_threshold() -> None:
    """The gate has to be wired, not merely computed."""
    report = {
        "walk_forward": {"oos_sharpe": 1.2, "oos_t_stat": 3.0, "fold_consistency": 1.0},
        "cpcv": {"fraction_negative": 0.0},
        "cost_stress": {"x2": 1.0},
        "multiple_testing": {"pbo": 0.1, "grid_trials": 2},
        "oos_selection": {"threshold_annual": 1.45, "n_trials": 125, "p_family": 0.3},
    }
    verdict, reasons = decide(report, VerdictThresholds())

    assert verdict == "FAIL"
    assert any("deflated threshold" in reason for reason in reasons)
