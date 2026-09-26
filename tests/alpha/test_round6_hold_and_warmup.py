"""Round 6 (E-042 / KILL-027): warmup under registry params, the NO_ACTION hold seed, live == research parity."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import get_signal
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores
from starquant_live.composition import build_model, load_registry
from starquant_shared.config import load_yaml
from tests.alpha.test_signal_suite import _synthetic_panel

ROOT = Path(__file__).resolve().parents[2]
WEEKLY = {"horizons": [168, 336, 720], "horizon_weights": [0.2, 0.3, 0.5]}
HOURLY = {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}


def _frames(panel: Panel) -> dict[str, pd.DataFrame]:
    """Per-symbol frames the live loop would hand to ``AlphaModel.targets`` (no funding)."""
    fields = ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote")
    out: dict[str, pd.DataFrame] = {}
    for symbol in panel.symbols:
        out[symbol] = pd.DataFrame(
            {field: getattr(panel, field)[symbol] for field in fields if getattr(panel, field) is not None}
        )
    return out


def test_warmup_follows_registry_params_not_signal_defaults() -> None:
    weekly = AlphaModel(entries=(StrategyEntry("tsmom", params=WEEKLY),), portfolio=PortfolioParams(), interval="1h")
    hourly = AlphaModel(entries=(StrategyEntry("tsmom", params=HOURLY),), portfolio=PortfolioParams(), interval="1h")
    assert get_signal("tsmom").warmup_for(WEEKLY) == 721 and get_signal("tsmom").warmup_for(HOURLY) == 101
    assert weekly.warmup_bars == 722  # a 720-bar horizon, plus one bar for the first decision
    assert hourly.warmup_bars == 102  # 5/20/50 horizons, but vol_window 200 needs 101 bars before any score
    shipped = build_model(load_registry(ROOT / "config/alpha_registry.yaml"), load_yaml(ROOT / "config/live.demo.yaml"))
    assert shipped.warmup_bars == 722  # the live window is sized from this number (E-042); 721 still dominates


@pytest.mark.parametrize(
    ("signal_id", "params"),
    [
        ("tsmom", {}),  # vol_window 200 binds, not the 5/20/50 horizons
        ("tsmom", {"vol_window": None}),  # the expanding legacy std is defined from the first return
        ("tsmom", {**WEEKLY, "vol_window": 400}),  # what runs live: the horizon binds
        ("meanrev", {}),  # the MAD is a rolling median of a rolling deviation: two windows less one
        ("meanrev", {"window": 30, "vol_window": 300}),  # ...unless vol_window is made the binding term
        ("xsmom", {}),
        ("xsmom", {"horizons": (10,), "horizon_weights": (1.0,), "vol_window": 20, "skip_bars": 24}),
        ("carry", {}),
        ("breakout", {}),
        ("flow", {}),
        ("residual", {}),
    ],
)
def test_declared_warmup_covers_the_first_bar_the_signal_can_actually_score(
    signal_id: str, params: dict[str, object]
) -> None:
    """The live request window is sized from ``warmup_for`` (D-022), so under-declaring shortens it silently.

    Chained rolling windows were the gap: ``realized_vol`` needs half its window *of returns* and
    ``robust_zscore``'s MAD rolls over an already-rolling deviation, so tsmom declared 51 bars against a
    first score at 101 and meanrev declared 49 against 95.
    """
    spec = get_signal(signal_id)
    panel = _synthetic_panel(seed=11, n_symbols=6, n_bars=1600, with_funding=True)
    scores = spec.compute(panel, {**spec.default_params, **params})
    scored = scores.notna().any(axis=1).to_numpy()
    assert scored.any(), "pick a panel long enough for this configuration to produce a score"
    first_scoreable_bar = int(scored.argmax()) + 1
    assert spec.warmup_for({**spec.default_params, **params}) >= first_scoreable_bar


def test_hold_seed_keeps_the_previous_target_through_a_sub_threshold_window() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    scores = pd.DataFrame(
        {"A": [0.1, 0.15, -0.1, 0.05], "B": [np.nan, np.nan, 0.3, 0.1], "C": [np.nan] * 4}, index=index
    )
    plain = scores_to_targets(scores, 0.2)
    assert plain["A"].tolist() == [0.0, 0.0, 0.0, 0.0]  # nothing actionable in the window -> flat
    seeded = scores_to_targets(scores, 0.2, initial={"A": 0.5, "B": -0.4, "C": 0.9})
    assert seeded["A"].tolist() == [0.5, 0.5, 0.5, 0.5]  # held from before the window (D-005)
    assert seeded["B"].iloc[:2].isna().all() and seeded["B"].tolist()[2:] == [0.3, 0.3]  # actionable overrides
    assert seeded["C"].isna().all()  # never scored -> not tradable whatever the seed
    exits = scores.copy()
    exits.loc[index[1], "A"] = 0.0
    assert scores_to_targets(exits, 0.2, initial={"A": 0.5})["A"].tolist() == [0.5, 0.0, 0.0, 0.0]  # explicit exit
    assert scores_to_targets(scores, 0.2, hold=False, initial={"A": 0.5})["A"].tolist() == [0.0] * 4


def test_live_targets_hold_previous_strategy_targets(august_panel: Panel) -> None:
    entry = StrategyEntry("tsmom", params={**TsmomParams(vol_window=100).__dict__, **HOURLY, "entry_threshold": 1.0})
    model = AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=0,
    )
    frames = _frames(august_panel)
    flat = model.targets(frames, {})
    assert all(value == 0.0 for value in flat.contributions["tsmom"].values())  # |score| >= 1.0 never happens
    held = model.targets(frames, {}, previous={"tsmom": {"BTCUSDT": 0.5}, "stale_strategy": {"ETHUSDT": 1.0}})
    assert held.contributions["tsmom"]["BTCUSDT"] == 0.5 and held.weights["BTCUSDT"] > 0
    assert held.contributions["tsmom"]["ETHUSDT"] == 0.0 and held.weights["ETHUSDT"] == 0.0


def test_shipped_registry_live_path_matches_research_path() -> None:
    """KILL-027 guard: the live path must produce the research path's targets and weights.

    Weights are compared against the research construction with its no-trade band switched off,
    because that band is the *position* recursion and live gets it from the rebalancer instead
    (D-033).  Everything else - conviction, vol targeting, caps, book fractions - must be identical.

    ``funding_history`` is passed because the shipped registry consumes it (``crowding_window`` 72,
    re-enabled 2026-09-05), exactly as ``LiveEngine._cycle`` passes ``inputs.funding_history``.  Before
    that it was omitted, and this docstring said "no funding frame" - which is the state KILL-027 exists
    to make impossible: a funding-consuming registry whose live path silently runs without funding.
    Omit it here and ``AlphaModel.targets`` raises, which is the guard working, not a fixture defect.
    """
    registry = load_registry(ROOT / "config/alpha_registry.yaml")
    model = build_model(registry, load_yaml(ROOT / "config/live.demo.yaml"))
    panel = _synthetic_panel(seed=3, n_symbols=6, n_bars=1600, with_funding=True)
    weights, _combined, per_strategy = model.evaluate(panel, band=False)
    live = model.targets(_frames(panel), {}, funding_history=panel.funding)
    assert live.as_of == panel.index[-1]
    for strategy, frame in per_strategy.items():
        expected = frame.iloc[-1].fillna(0.0)
        for symbol in panel.symbols:
            assert live.contributions[strategy][symbol] == pytest.approx(float(expected[symbol]), abs=1e-12), (
                strategy,
                symbol,
            )
    last = weights.iloc[-1].fillna(0.0)
    for symbol in panel.symbols:
        assert live.weights[symbol] == pytest.approx(float(last[symbol]), abs=1e-12)
    banded = model.weights_from(per_strategy, panel.close, panel.bars_per_year)
    assert not np.allclose(banded.iloc[-1].fillna(0.0), last), "pick a panel where the band actually binds"


def test_live_weights_do_not_depend_on_the_length_of_the_request_window() -> None:
    """D-033: the model's output must be a function of the data, not of where the request window starts.

    ``apply_no_trade_band`` is a path-dependent recursion.  The live loop rebuilds it from scratch every
    cycle over a window that slides by one bar, so while it ran there the latch point was an artefact of
    the window: on the shipped book 1,442 bars against 1,443 moved one symbol's weight by 14% of itself,
    and nothing downstream could tell that apart from a real change of view.
    """
    model = build_model(load_registry(ROOT / "config/alpha_registry.yaml"), load_yaml(ROOT / "config/live.demo.yaml"))
    panel = _synthetic_panel(seed=5, n_symbols=6, n_bars=1800, with_funding=True)
    frames = _frames(panel)

    def live(n: int) -> dict[str, float]:
        return model.targets(
            {symbol: frame.iloc[-n:] for symbol, frame in frames.items()},
            {},
            funding_history=panel.funding,
        ).weights

    def gap(left: dict[str, float], right: dict[str, float]) -> float:
        return max(abs(left[symbol] - right[symbol]) for symbol in panel.symbols)

    base = live(1000)
    # One more bar of history is exactly what every cycle's slide amounts to; it must change nothing.
    # With the band still in the model this same step moved a weight by 1.4e-3 (2.2% of itself).
    assert gap(base, live(1001)) < 1e-8
    # Over 500 extra bars only the EWMA vol burn-in remains: smooth, shrinking, and far under the
    # rebalancer's 0.005-of-equity band.  It was 4.2e-3 with the band in the model.
    assert gap(base, live(1500)) < 1e-4


def test_tsmom_vol_scaled_mode_penalises_the_noisier_path_with_the_same_return() -> None:
    n = 400
    t = np.arange(n)
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    smooth = 100.0 * np.exp(0.0005 * t)
    noisy = smooth * (1.0 + 0.02 * np.where(t % 2 == 0, 1.0, -1.0))  # identical returns over every even horizon
    close = pd.DataFrame({"A": smooth, "B": noisy}, index=index)
    horizons = {"horizons": (10, 20, 50), "horizon_weights": (0.2, 0.3, 0.5), "vol_window": 100}
    fixed = tsmom_scores(close, TsmomParams(momentum_mode="fixed", **horizons))
    scaled = tsmom_scores(close, TsmomParams(momentum_mode="vol_scaled", return_scale=1.0, **horizons))
    assert fixed["A"].iloc[-1] == pytest.approx(fixed["B"].iloc[-1])  # the validated form ignores the path's vol
    assert scaled["A"].iloc[-1] > scaled["B"].iloc[-1] > 0.0  # the t-statistic form does not
    assert (scaled.abs().dropna() <= 1.0).all().all()
    with pytest.raises(ValueError):
        TsmomParams(momentum_mode="bogus")
