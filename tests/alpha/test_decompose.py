"""D-024: signal-vs-construction decomposition runs the same pipeline on controlled convictions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_alpha.validation.decompose import VARIANTS, decompose_book, variant_targets


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, no_trade_rel_band=0.25),
        interval="1h",
        min_history_bars=0,
    )


def test_variant_targets_are_controlled_convictions() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    targets = pd.DataFrame({"A": [np.nan, 0.6, -0.3, 0.0], "B": [np.nan, np.nan, 0.2, 0.9]}, index=index)
    eligible = pd.DataFrame({"A": [False, True, True, True], "B": [False, False, True, True]}, index=index)
    variants = variant_targets(targets, eligible)
    assert set(variants) == set(VARIANTS)
    assert variants["constant_long"]["A"].tolist()[1:] == [1.0, 1.0, 1.0]
    assert np.isnan(variants["constant_long"]["A"].iloc[0])
    assert variants["constant_long"]["B"].tolist()[1:] == [0.0, 1.0, 1.0]  # not eligible -> flat, never NaN
    assert variants["sign_only"]["A"].tolist()[1:] == [1.0, -1.0, 0.0]
    assert variants["long_only"]["A"].tolist()[1:] == [0.6, 0.0, 0.0]
    assert variants["short_only"]["A"].tolist()[1:] == [0.0, -0.3, 0.0]
    assert variants["equal_notional"]["B"].iloc[3] == 0.9 / 2 and variants["equal_notional"]["A"].iloc[1] == 0.6


def test_decompose_reproduces_the_full_book_and_reports_increments(august_panel: Panel) -> None:
    model = _model()
    cost = CostModel(turnover_bps=7.0)
    payload = decompose_book(model, august_panel, cost, folds=3, min_train=300, purge=5)
    rows = payload["variants"]
    assert set(rows) == set(VARIANTS) and payload["strategy"] == "tsmom"
    weights, _c, _p = model.evaluate(august_panel)
    direct = run_backtest(august_panel, weights, cost).summary()
    assert abs(rows["full"]["full_sharpe"] - direct["annualized_sharpe"]) < 1e-9
    assert abs(rows["full"]["turnover_units"] - direct["turnover_units"]) < 1e-9
    assert rows["constant_long"]["average_absolute_exposure"] > 0
    assert all(len(row["fold_sharpes"]) == 3 for row in rows.values())
    assert set(payload["increments"]) == {
        "signal_over_construction",
        "magnitude_over_direction",
        "construction_over_signal",
    }
    assert (
        payload["legs"]["share_of_long_symbol_bars"] is None or 0 <= payload["legs"]["share_of_long_symbol_bars"] <= 1
    )
    assert payload["benchmark"]["net_return"] is not None
