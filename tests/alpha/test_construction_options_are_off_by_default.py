"""Block 4's two construction options (#35 GARCH, #48 HRP): off by default, causal, and separable.

Every test here answers one of three questions, and they are deliberately not mixed:

* does turning the option OFF leave the shipped construction untouched (bit for bit, not "close")
* is the option CAUSAL
* does the estimator do what its name says on data where the answer is known

Whether either helps on 1h crypto perpetuals is not a question a unit test can answer, and this file
does not pretend to: that is measured in `scratchpad/block4_garch_hrp_increment.py` and judged against
the pre-registration in RESEARCH_LOG.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from starquant_alpha.features import ewm_vol, garch_forecast_vol
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, asset_vol, build_weights, hrp_budget, risk_budget
from tests.alpha.test_causality import _bit_for_bit

BARS_PER_YEAR = 8760.0


def _garch_panel(n: int = 12_000, k: int = 4, seed: int = 11) -> pd.DataFrame:
    """Closes whose returns really are GARCH(1,1): persistence 0.98, news share 0.0816."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 1e-6, 0.08, 0.90
    returns = np.zeros((n, k))
    h = np.full(k, omega / (1.0 - alpha - beta))
    for t in range(n):
        returns[t] = np.sqrt(h) * rng.normal(0.0, 1.0, k)
        h = omega + alpha * returns[t] ** 2 + beta * h
    index = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(100.0 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"S{i}" for i in range(k)])


def test_the_defaults_are_the_shipped_construction_and_nothing_else() -> None:
    params = PortfolioParams()
    assert (params.vol_model, params.budget_mode) == ("ewma", "inverse_vol")
    # `from_mapping` has to reach them, because adopting either one in Phase 4a must be a config edit
    # plus evidence.  A construction option only a code change can turn on is a code change under time
    # pressure, which is the shape D-026 was written about.
    tuned = PortfolioParams.from_mapping({"vol_model": "garch", "budget_mode": "hrp", "hrp_refit_bars": 168})
    assert (tuned.vol_model, tuned.budget_mode, tuned.hrp_refit_bars) == ("garch", "hrp", 168)
    for bad in ({"vol_model": "egarch"}, {"budget_mode": "hierarchical"}, {"hrp_refit_bars": 0}):
        try:
            PortfolioParams.from_mapping(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should not construct")


def test_asset_vol_on_the_defaults_is_still_exactly_the_ewma_divisor(august_panel: Panel) -> None:
    expected = (ewm_vol(august_panel.close, halflife=48) * math.sqrt(BARS_PER_YEAR)).clip(lower=0.10)
    _bit_for_bit(asset_vol(august_panel.close, PortfolioParams(), BARS_PER_YEAR), expected)


def test_the_budget_branch_reproduces_stage_one_but_is_not_the_branch_that_ships(august_panel: Panel) -> None:
    """The general budget path and the literal `vol_target / sigma` agree to rounding, not to bits.

    That gap is the reason `build_weights` keeps the literal expression for the default rather than
    routing everything through `risk_budget`: the shipped book is compared bit for bit against a frozen
    baseline, and "the same modulo 1e-16" is a book that changed.
    """
    params = PortfolioParams(vol_target=0.30)
    sigma = asset_vol(august_panel.close, params, BARS_PER_YEAR)
    targets = pd.DataFrame(1.0, index=august_panel.index, columns=august_panel.symbols)
    general = (
        targets
        * risk_budget(sigma, august_panel.close.pct_change(), params).mul((1.0 / sigma).sum(axis=1), axis=0)
        * params.vol_target
    )
    literal = targets * (params.vol_target / sigma)
    difference = (general - literal).abs().to_numpy()
    assert np.nanmax(difference / np.maximum(np.abs(literal.to_numpy()), 1e-30)) < 1e-12


def test_hrp_with_uncorrelated_assets_is_exactly_the_inverse_variance_budget() -> None:
    """The tilt is 1 when there is nothing to cluster, which is what makes it a tilt.

    It also names the trap this decomposition exists for: HRP is NOT the shipped inverse-vol budget
    even at zero correlation, because recursive bisection allocates on inverse VARIANCE.  Reading a
    single HRP-vs-shipped number would credit the clustering with that convention change.
    """
    cov = np.diag([0.01, 0.04, 0.09])
    inverse_variance = (1.0 / np.diag(cov)) / (1.0 / np.diag(cov)).sum()
    np.testing.assert_allclose(hrp_budget(cov), inverse_variance, atol=1e-12)
    inverse_vol = (1.0 / np.sqrt(np.diag(cov))) / (1.0 / np.sqrt(np.diag(cov))).sum()
    assert np.abs(hrp_budget(cov) - inverse_vol).max() > 0.15


def test_hrp_is_a_budget_and_it_moves_when_the_correlation_moves() -> None:
    rng = np.random.default_rng(3)
    loadings = rng.normal(size=(12, 3))
    cov = loadings @ loadings.T + np.diag(rng.uniform(0.2, 1.0, 12))
    budget = hrp_budget(cov)
    assert budget.shape == (12,) and (budget >= 0).all() and abs(budget.sum() - 1.0) < 1e-12
    independent = np.diag(np.diag(cov))
    assert np.abs(budget - hrp_budget(independent)).max() > 1e-6, "clustering must change something"


def test_garch_is_causal_under_a_shuffled_future() -> None:
    """T-A02's rule applied to the divisor: a fit that reads its own future is invisible in a backtest.

    Sized so the pre-cutoff region is non-empty on purpose - KILL-AR-15 was a causality test comparing
    NaN against NaN, which passes for any implementation at all.  Compared bit for bit for the sibling
    reason: the default rtol 1e-5 passes any refit that leaked less than that.
    """
    close = _garch_panel()
    cutoff = 6_000
    rng = np.random.default_rng(5)
    shuffled = close.copy()
    future = shuffled.iloc[cutoff:].to_numpy().copy()
    rng.shuffle(future, axis=0)
    shuffled.iloc[cutoff:] = future
    kwargs = {"fit_bars": 8_000, "refit_bars": 2_000, "min_obs": 720}
    before = garch_forecast_vol(close, **kwargs).iloc[:cutoff]
    after = garch_forecast_vol(shuffled, **kwargs).iloc[:cutoff]
    assert before.notna().sum().sum() > 10_000, "the comparison must not be NaN against NaN"
    _bit_for_bit(before, after)


def test_garch_forecasts_better_than_ewma_when_the_data_really_is_garch() -> None:
    """An estimator test, not a claim about crypto: QLIKE on the bar the weight will be executed on.

    QLIKE (x - log x - 1 with x = realised r^2 over the forecast variance) rather than MSE, because
    MSE on a variance is dominated by the few largest shocks and ranks by tail luck.
    """
    close = _garch_panel()
    realised = close.pct_change().pow(2).shift(-1)
    forecast = garch_forecast_vol(close, fit_bars=8_000, refit_bars=2_000, min_obs=720)
    level = ewm_vol(close, halflife=48)
    seen = forecast.notna() & level.notna() & realised.notna()

    def qlike(estimate: pd.DataFrame) -> float:
        ratio = realised[seen] / estimate[seen].pow(2)
        return float((ratio - np.log(ratio.where(ratio > 0)) - 1.0).stack().mean())

    assert qlike(forecast) < qlike(level)


def test_neither_option_changes_the_book_while_it_is_off(august_panel: Panel) -> None:
    rng = np.random.default_rng(19)
    targets = pd.DataFrame(
        rng.choice([-1.0, 0.0, 1.0], size=august_panel.close.shape),
        index=august_panel.index,
        columns=august_panel.symbols,
    )
    shipped = build_weights(targets, august_panel.close, BARS_PER_YEAR, PortfolioParams(vol_target=0.30))
    for switched_off in (
        PortfolioParams(vol_target=0.30, garch_fit_bars=4_380, garch_refit_bars=168, hrp_refit_bars=24),
        PortfolioParams(vol_target=0.30, vol_model="ewma", budget_mode="inverse_vol"),
    ):
        _bit_for_bit(build_weights(targets, august_panel.close, BARS_PER_YEAR, switched_off), shipped)
