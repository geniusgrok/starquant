"""D-018/D-019: books in the registry and the model, and the probe-book evidence gate."""

from __future__ import annotations

from dataclasses import asdict, replace

import pandas as pd
import pytest

from starquant_alpha.ensemble import combine_targets
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, build_weights, combine_books
from starquant_alpha.registry import StrategyEntry, evidence_problems, parse_registry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams

TSMOM = {**TsmomParams(vol_window=100).__dict__, "horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
BREAKOUT = {**asdict(BreakoutParams()), "entry_threshold": 0.05}


def test_registry_books_parse_and_validate() -> None:
    registry = parse_registry(
        {
            "version": 1,
            "books": {"flow_short": {"fraction": 0.333333}},
            "strategies": [
                {"id": "tsmom"},
                {"id": "flow", "book": "flow_short", "probe": {"accepted_by": "operator"}},
            ],
        }
    )
    assert registry.fraction("flow_short") == pytest.approx(0.333333) and registry.fraction("main") == 1.0
    assert registry.strategies[0].book == "main" and registry.strategies[0].probe is None
    assert registry.strategies[1].book == "flow_short" and registry.strategies[1].probe == {"accepted_by": "operator"}
    with pytest.raises(ValueError):
        parse_registry({"strategies": [{"id": "x", "book": "ghost"}]})
    with pytest.raises(ValueError):
        parse_registry({"books": {"b": {"fraction": 1.5}}, "strategies": []})
    with pytest.raises(ValueError):
        parse_registry({"books": {"main": {"fraction": 0.5}}, "strategies": []})


def test_evidence_gate_for_probe_books() -> None:
    report = {"kind": "book", "book_verdict": "ACCEPT", "sleeve": {"strategy": "flow"}, "fraction": 1.0 / 3.0}
    base = {"report": "book.json", "sha256": "a" * 64, "verdict": "ACCEPT"}
    probe = {"accepted_by": "operator", "accepted_on": "2026-09-03", "stop": {"window_days": 30, "max_loss": 0.01}}
    ok = StrategyEntry("flow", evidence=base, book="flow_short", probe=probe)

    def check(entry: StrategyEntry, payload: dict = report, fraction: float | None = 0.333333) -> list[str]:
        return evidence_problems(
            entry,
            exists=lambda _: True,
            sha256_of=lambda _: "a" * 64,
            read_report=lambda _: payload,
            book_fraction=fraction,
        )

    assert check(ok) == []
    assert check(StrategyEntry("flow", evidence=base, probe=probe))  # ACCEPT cannot run in the main book
    assert check(replace(ok, probe=None))  # ...nor without an explicit probe block
    assert check(replace(ok, probe={"accepted_by": "operator", "accepted_on": "x", "stop": {"window_days": 0}}))
    assert check(ok, fraction=0.5)  # the registry fraction must match the evidence
    assert check(ok, payload={**report, "sleeve": {"strategy": "xsmom"}})  # ...about this sleeve
    assert check(ok, payload={**report, "book_verdict": "REJECT"})  # ...and ACCEPTed
    assert check(replace(ok, evidence={**base, "verdict": "FAIL"}))  # a signal-level FAIL is still refused
    assert check(replace(ok, evidence={**base, "verdict": "PASS"})) == []  # PASS never needed the probe block
    # without a report reader only the structural rules apply
    assert evidence_problems(ok, exists=lambda _: True, sha256_of=lambda _: "a" * 64) == []


def test_single_main_book_path_is_unchanged(august_panel: Panel) -> None:
    entry = StrategyEntry("tsmom", params=TSMOM)
    params = PortfolioParams(covariance_halflife=48, vol_halflife=24, no_trade_band=0.005, no_trade_rel_band=0.25)
    model = AlphaModel(entries=(entry,), portfolio=params, interval="1h", min_history_bars=0)
    assert model.book_names == ("main",)
    weights, combined, per = model.evaluate(august_panel)
    direct = build_weights(combine_targets(per, {"tsmom": 1.0}), august_panel.close, august_panel.bars_per_year, params)
    pd.testing.assert_frame_equal(weights, direct)
    bare = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    single = combine_books(
        {"main": build_weights(combined, august_panel.close, august_panel.bars_per_year, bare)}, params
    )
    pd.testing.assert_frame_equal(single, direct)


def test_two_books_are_summed_then_capped_and_banded(august_panel: Panel) -> None:
    main = StrategyEntry("tsmom", params=TSMOM)
    sleeve = StrategyEntry("breakout", params=BREAKOUT, book="sleeve")
    params = PortfolioParams(
        covariance_halflife=48, vol_halflife=24, max_weight=0.10, max_gross=0.5, no_trade_band=0.005
    )
    with pytest.raises(ValueError):
        AlphaModel(entries=(main, sleeve), portfolio=params, interval="1h", min_history_bars=0)
    model = AlphaModel(
        entries=(main, sleeve), portfolio=params, interval="1h", min_history_bars=0, books={"sleeve": 0.5}
    )
    assert model.book_names == ("main", "sleeve") and model.fraction("sleeve") == 0.5
    weights, _combined, per = model.evaluate(august_panel)
    bpy = august_panel.bars_per_year
    bare = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    expected = combine_books(
        {
            "main": build_weights(per["tsmom"], august_panel.close, bpy, bare),
            "sleeve": build_weights(per["breakout"], august_panel.close, bpy, bare) * 0.5,
        },
        params,
    )
    pd.testing.assert_frame_equal(weights, expected)
    valid = weights.dropna(how="all")
    assert (valid.abs() <= 0.10 + 1e-12).all().all() and (valid.abs().sum(axis=1) <= 0.5 + 1e-9).all()
    assert per["breakout"].dropna(how="all").abs().gt(0).any().any(), "the sleeve should take positions in August"
    only_main = model.without_books(["sleeve"])
    assert [e.id for e in only_main.entries] == ["tsmom"] and only_main.books == {}
    reference = AlphaModel(entries=(main,), portfolio=params, interval="1h", min_history_bars=0)
    pd.testing.assert_frame_equal(only_main.weights(august_panel), reference.weights(august_panel))
    with pytest.raises(ValueError):
        model.without_books(["main"])
    frames = {symbol: august_panel.close[[symbol]].rename(columns={symbol: "close"}) for symbol in august_panel.symbols}
    for symbol, frame in frames.items():
        for field in ("open", "high", "low", "volume"):
            frame[field] = getattr(august_panel, field)[symbol]
    target = model.targets(frames, {})
    last = per["breakout"].iloc[-1].fillna(0.0)
    assert set(target.contributions) == {"tsmom", "breakout"}
    for symbol, value in target.contributions["breakout"].items():
        assert value == pytest.approx(float(last[symbol]))  # unscaled: the fraction enters via strategy_weights
    for symbol, value in target.weights.items():
        assert value == pytest.approx(float(weights[symbol].iloc[-1]))
