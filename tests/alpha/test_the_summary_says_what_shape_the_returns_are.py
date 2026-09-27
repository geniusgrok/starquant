"""`summarize_returns` reports distribution shape, and `moments` survives a constant series.

Neither `summarize_returns` nor `moments` had a test before 2026-09-19.  `moments` had a caller that
masked its one defect - the DSR, which no one reads on a constant return series - and
`summarize_returns` had no caller that looked at anything but the Sharpe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation import multiple_testing
from starquant_alpha.validation.metrics import moments, sharpe, sortino, summarize_returns

HOURLY = 365.0 * 24.0


def test_the_old_address_of_moments_still_resolves() -> None:
    """It moved to `metrics`; `multiple_testing.moments` is the same object, not a copy."""
    assert multiple_testing.moments is moments


def test_moments_reads_a_normal_series_as_normal() -> None:
    values = np.random.default_rng(0).standard_normal(20_000)
    skew, kurtosis = moments(values)
    assert abs(skew) < 0.1
    assert 2.9 < kurtosis < 3.1


def test_moments_sees_a_left_tail() -> None:
    """The shape the field exists for: a book that wins often and loses enormously."""
    rng = np.random.default_rng(1)
    values = np.where(rng.random(20_000) < 0.97, 0.001, -0.05)
    skew, kurtosis = moments(values)
    assert skew < -3.0, skew
    assert kurtosis > 10.0, kurtosis


def test_a_constant_series_is_not_read_as_skewed() -> None:
    """The defect the tolerance closes, pinned at the value that exposed it.

    `np.full(10, 0.01)` does not centre to zero: the mean is off by one ulp, the residual is
    1.73e-18, and the bare `variance <= 0` test let it through to return skew of exactly 1.0.
    Whether it happened depended on the value - 0.1 and 1.0 centred exactly and were fine - so the
    regression has to name the values, not just the idea.
    """
    for value in (0.01, 0.1, 1.0, 0.0, 1e-7, 123.456):
        assert moments(np.full(10, value)) == (0.0, 3.0), value
    assert moments(np.array([0.01] * 10)) == (0.0, 3.0)


def test_the_tolerance_does_not_swallow_a_real_series() -> None:
    """It has to see past float residue without calling a small real dispersion constant."""
    rng = np.random.default_rng(2)
    for scale in (0.005, 1e-6):  # an hourly return, and one far below it
        skew, kurtosis = moments(rng.standard_normal(20_000) * scale)
        assert abs(skew) < 0.1, scale
        assert 2.8 < kurtosis < 3.2, scale


def test_sortino_divides_by_the_semi_deviation_not_by_the_losers_std() -> None:
    """The two differ by sqrt(n_losing / n), and only the first one is Sortino.

    Built so the distinction is unambiguous: nine bars at +1% and one at -1%.  The losing bars'
    own standard deviation is 0 (there is one of them), which would make the ratio infinite; the
    semi-deviation is sqrt(0.0001/10) and gives a finite, correct answer.
    """
    values = np.array([0.01] * 9 + [-0.01])
    expected = float(np.mean(values) / np.sqrt(np.mean(np.minimum(values, 0.0) ** 2)) * np.sqrt(HOURLY))
    assert sortino(values, HOURLY) == expected
    assert np.isfinite(sortino(values, HOURLY))


def test_sortino_is_none_when_nothing_was_lost() -> None:
    """Undefined is not infinite, and `hit_rate` answers the same shape the same way."""
    assert sortino(np.full(10, 0.01), HOURLY) is None
    assert sortino(np.array([0.01]), HOURLY) is None


def test_sortino_and_sharpe_agree_on_a_symmetric_series() -> None:
    """Zero-mean and symmetric, the semi-deviation is sigma/sqrt(2), so the ratio is sqrt(2)."""
    values = np.random.default_rng(3).standard_normal(50_000) * 0.01
    ratio = sortino(values, HOURLY) / sharpe(values, HOURLY)
    assert abs(ratio - np.sqrt(2.0)) < 0.02, ratio


def test_the_summary_carries_the_three_new_fields() -> None:
    index = pd.date_range("2026-01-01", periods=500, freq="h", tz="UTC")
    net = pd.Series(np.random.default_rng(4).standard_normal(500) * 0.01, index=index)
    weights = pd.DataFrame({"BTCUSDT": np.full(500, 0.1)}, index=index)
    summary = summarize_returns(net, net, weights, HOURLY)
    assert {"skew", "kurtosis", "sortino"} <= set(summary)
    assert summary["skew"] == moments(net)[0]
    assert summary["kurtosis"] == moments(net)[1]
    assert summary["sortino"] == sortino(net, HOURLY)


def test_a_symbol_that_never_traded_reports_a_shape_instead_of_a_nonsense() -> None:
    """`per_symbol_summary` calls this for every column, including the ones held at zero all along."""
    index = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    flat = pd.Series(0.0, index=index)
    summary = summarize_returns(flat, flat, pd.DataFrame({"X": np.zeros(200)}, index=index), HOURLY)
    assert (summary["skew"], summary["kurtosis"]) == (0.0, 3.0)
    assert summary["sortino"] is None


def test_the_summary_states_the_rate_its_ratios_are_measured_against() -> None:
    """0 is a choice here, and the 2026-09-08 ruling was that it must not be an unstated one.

    Pinned as a value, not as presence: a report that stopped carrying the field, or started
    carrying a different rate without every archived threshold being repriced, is the thing this
    catches.  `sharpe` and `sortino` both use it, so the three have to agree.
    """
    index = pd.date_range("2026-01-01", periods=300, freq="h", tz="UTC")
    net = pd.Series(np.random.default_rng(5).standard_normal(300) * 0.01, index=index)
    summary = summarize_returns(net, net, pd.DataFrame({"X": np.full(300, 0.1)}, index=index), HOURLY)
    assert summary["risk_free_rate"] == 0.0
    # the ratios beside it are the raw-return ones, i.e. computed at exactly that rate
    assert summary["annualized_sharpe"] == sharpe(net, HOURLY)
    assert summary["sortino"] == sortino(net, HOURLY)
