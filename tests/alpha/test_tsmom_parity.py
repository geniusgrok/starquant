"""T-A01 / T-A05: the vectorised tsmom port reproduces the frozen August 2026 baseline, then fixes its bug."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, benchmark_returns, run_backtest
from starquant_alpha.panel import Panel
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores

LEGACY_PARAMS = TsmomParams(vol_window=None)  # expanding population std, as OfflineAlphaApp did
LEGACY_COST = CostModel(turnover_bps=6.0, carry_bps_per_bar=0.125)  # 4+1+1 bps turnover; 0.01%/8h adverse funding
TOLERANCE = 1e-9


def _legacy_weights(panel: Panel) -> pd.DataFrame:
    """The E-022 bug semantics: the raw score is traded, sub-threshold or not."""
    return tsmom_scores(panel.close, LEGACY_PARAMS)


def test_portfolio_parity_with_frozen_baseline(august_panel: Panel, august_baseline: dict) -> None:
    weights = _legacy_weights(august_panel) / 4.0  # equal-capital four-sleeve average
    result = run_backtest(august_panel, weights, LEGACY_COST, execution="open_to_close")
    expected = august_baseline["portfolio"]
    summary = result.summary()
    assert result.weights.shape[0] == expected["bars"] == 669
    assert math.isclose(summary["gross_return"], expected["gross_return"], abs_tol=TOLERANCE)
    assert math.isclose(summary["net_return"], expected["net_return"], abs_tol=TOLERANCE)
    assert math.isclose(summary["max_drawdown"], expected["max_drawdown"], abs_tol=TOLERANCE)
    assert math.isclose(summary["annualized_sharpe"], expected["annualized_hourly_sharpe"], abs_tol=1e-6)
    assert math.isclose(summary["average_absolute_exposure"], expected["average_absolute_position"], abs_tol=TOLERANCE)
    # legacy reports the per-symbol turnover averaged over the four sleeves; ours sums the /4 sleeves -> identical
    assert math.isclose(summary["turnover_units"], expected["turnover_units"], abs_tol=1e-6)
    bench = benchmark_returns(august_panel, "open_to_close").reindex(result.weights.index)
    assert math.isclose(float((1 + bench).prod() - 1), expected["benchmark"]["gross_return"], abs_tol=TOLERANCE)


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"])
def test_per_symbol_parity(august_panel: Panel, august_baseline: dict, symbol: str) -> None:
    weights = _legacy_weights(august_panel)[[symbol]]
    result = run_backtest(august_panel, weights, LEGACY_COST, execution="open_to_close")
    expected = august_baseline["per_symbol"][symbol]["metrics"]
    summary = result.per_symbol_summary()[symbol]
    for key_ours, key_theirs in (
        ("gross_return", "gross_return"),
        ("net_return", "net_return"),
        ("max_drawdown", "max_drawdown"),
        ("turnover_units", "turnover_units"),
        ("average_absolute_exposure", "average_absolute_position"),
    ):
        assert math.isclose(summary[key_ours], expected[key_theirs], abs_tol=TOLERANCE), (key_ours, symbol)
    assert math.isclose(summary["annualized_sharpe"], expected["annualized_hourly_sharpe"], abs_tol=1e-6)
    sub_threshold = int(((weights[symbol].abs() > 1e-12) & (weights[symbol].abs() < 0.20)).iloc[50:-1].sum())
    assert sub_threshold == august_baseline["per_symbol"][symbol]["subthreshold_nonzero_targets"]


def test_hold_semantics_cut_turnover_and_record_new_baseline(august_panel: Panel, august_baseline: dict) -> None:
    """T-A05: NO_ACTION keeps the previous position; turnover collapses versus the raw-score bug."""
    scores = tsmom_scores(august_panel.close, LEGACY_PARAMS)
    held = scores_to_targets(scores, LEGACY_PARAMS.entry_threshold, hold=True) / 4.0
    flat = scores_to_targets(scores, LEGACY_PARAMS.entry_threshold, hold=False) / 4.0
    buggy = scores / 4.0
    held_result = run_backtest(august_panel, held, LEGACY_COST)
    buggy_result = run_backtest(august_panel, buggy, LEGACY_COST)
    flat_result = run_backtest(august_panel, flat, LEGACY_COST)
    assert held_result.summary()["turnover_units"] < 0.5 * buggy_result.summary()["turnover_units"]
    assert flat_result.summary()["turnover_units"] >= 0.0
    # every held position is either zero or an actionable forecast at some earlier bar
    actionable = scores.abs() >= LEGACY_PARAMS.entry_threshold
    assert int(((held.abs() * 4 > 1e-12) & ~actionable.cummax()).sum().sum()) == 0
    # the corrected August numbers become the new reference (recorded, not asserted for direction)
    summary = held_result.summary()
    assert summary["bars"] == 669
    assert (
        summary["cost_share_of_gross"] is None
        or summary["cost_share_of_gross"] < buggy_result.summary()["cost_share_of_gross"]
    )
