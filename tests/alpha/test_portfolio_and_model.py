from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.ensemble import combine_targets
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, apply_no_trade_band, build_weights
from starquant_alpha.registry import StrategyEntry, evidence_problems, parse_registry
from starquant_alpha.signals.tsmom import TsmomParams


def test_build_weights_respects_caps(august_panel: Panel) -> None:
    targets = pd.DataFrame(1.0, index=august_panel.index, columns=august_panel.symbols)
    params = PortfolioParams(vol_target=0.15, max_weight=0.15, max_gross=0.5)
    weights = build_weights(targets, august_panel.close, august_panel.bars_per_year, params).dropna()
    assert (weights.abs() <= 0.15 + 1e-12).all().all()
    assert (weights.abs().sum(axis=1) <= 0.5 + 1e-9).all()
    assert (weights >= 0).all().all()


def test_no_trade_band_holds_small_changes_but_allows_exits() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.10, 0.102, 0.0, 0.05]}, index=index)
    banded = apply_no_trade_band(weights, 0.005)
    assert banded["A"].tolist() == [0.10, 0.10, 0.0, 0.05]


def test_combine_targets_excludes_missing_strategies_per_bar() -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    a = pd.DataFrame({"X": [1.0, np.nan, -1.0]}, index=index)
    b = pd.DataFrame({"X": [0.0, 0.5, 1.0]}, index=index)
    combined = combine_targets({"a": a, "b": b}, {"a": 1.0, "b": 1.0})
    assert combined["X"].tolist() == [0.5, 0.5, 0.0]


def test_registry_parse_and_evidence_gate() -> None:
    registry = parse_registry(
        {
            "version": 1,
            "ensemble": {"method": "mean"},
            "strategies": [
                {"id": "tsmom", "enabled": True, "params": {"entry_threshold": 0.2}, "evidence": None},
                {"id": "off", "enabled": False},
            ],
        }
    )
    assert [entry.id for entry in registry.enabled] == ["tsmom"]
    problems = evidence_problems(registry.enabled[0], exists=lambda _: False, sha256_of=lambda _: "")
    assert problems == ["tsmom: enabled without evidence"]
    ok = StrategyEntry("tsmom", evidence={"report": "r.json", "sha256": "a" * 64, "verdict": "PASS"})
    assert evidence_problems(ok, exists=lambda _: True, sha256_of=lambda _: "a" * 64) == []
    assert evidence_problems(ok, exists=lambda _: True, sha256_of=lambda _: "b" * 64)


def test_model_end_to_end_on_august(august_panel: Panel) -> None:
    entry = StrategyEntry(
        "tsmom",
        params={**TsmomParams(vol_window=100).__dict__, "horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]},
    )
    model = AlphaModel(
        entries=(entry,), portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24), interval="1h"
    )
    weights, _combined, per_strategy = model.evaluate(august_panel)
    assert set(per_strategy) == {"tsmom"}
    assert weights.shape == august_panel.close.shape
    frames = {symbol: august_panel.close[[symbol]].rename(columns={symbol: "close"}) for symbol in august_panel.symbols}
    for symbol, frame in frames.items():
        for field in ("open", "high", "low", "volume"):
            frame[field] = getattr(august_panel, field)[symbol]
    target = model.targets(frames, {})
    assert target.as_of == august_panel.index[-1]
    assert set(target.weights) == set(august_panel.symbols)
    assert all(abs(value) <= 0.15 + 1e-9 for value in target.weights.values())


def test_relative_band_suppresses_small_resizes_only() -> None:
    index = pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")
    weights = pd.DataFrame({"A": [0.10, 0.11, 0.14, -0.05, 0.0, 0.02]}, index=index)
    banded = apply_no_trade_band(weights, 0.0, relative=0.25)
    assert banded["A"].tolist() == [0.10, 0.10, 0.14, -0.05, 0.0, 0.02]


def test_min_history_filter_blocks_new_listings(august_panel: Panel) -> None:
    entry = StrategyEntry(
        "tsmom",
        params={**TsmomParams(vol_window=100).__dict__, "horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]},
    )
    model = AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=300,
    )
    targets = model.strategy_targets(august_panel)["tsmom"]
    assert targets.iloc[:299].isna().all().all()
    assert targets.iloc[300:].notna().any().any()


def test_shipped_registry_is_loadable_and_uses_a_supported_ensemble() -> None:
    from pathlib import Path

    from starquant_alpha.ensemble import combine_targets
    from starquant_shared.config import load_yaml

    registry = parse_registry(load_yaml(Path(__file__).resolve().parents[2] / "config" / "alpha_registry.yaml"))
    assert registry.enabled, "at least one strategy must be enabled"
    index = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    frame = pd.DataFrame({"X": [0.1, 0.2, 0.3]}, index=index)
    combine_targets(
        {entry.id: frame for entry in registry.enabled},
        {entry.id: entry.weight for entry in registry.enabled},
        method=registry.ensemble_method,
    )
    for entry in registry.strategies:
        from starquant_alpha.signals import get_signal

        get_signal(entry.id)
