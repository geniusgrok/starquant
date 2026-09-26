"""Every registered signal: causal, bounded, and directionally sane on synthetic data (incl. T-A07 carry)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_alpha.signals import SIGNALS
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.carry import CarryParams, carry_scores
from starquant_alpha.signals.meanrev import MeanrevParams, meanrev_scores
from starquant_alpha.signals.residual import ResidualParams, residual_scores
from starquant_alpha.signals.xsmom import XsmomParams, xsmom_scores
from tests.alpha.test_causality import _bit_for_bit


def _synthetic_panel(
    seed: int = 0, n_symbols: int = 6, n_bars: int = 800, with_funding: bool = True, correlated: bool = False
) -> Panel:
    """``correlated`` gives two symbols a common factor, and it defaults OFF on purpose.

    A signal DEFINED on correlation - `pairs` needs a mutually-nearest neighbour above `min_corr` -
    produces nothing on six independent random walks, which the causality test's emptiness assertion
    reads as a broken signal.  So that test asks for structure.  Every OTHER caller keeps the panel it
    already had: `test_round6_hold_and_warmup` pins a 1e-8 window-length tolerance against this
    fixture, and a common factor makes the covariance more ill-conditioned and the EWMA scalar slower
    to settle - measured 1.08e-7 - so turning it on for everybody would have loosened somebody else's
    pinned number to accommodate a change of mine.  That is the wrong direction, so it is a flag.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    symbols = ["BTCUSDT", *[f"S{i}USDT" for i in range(1, n_symbols)]]
    steps = rng.normal(0.0, 0.01, size=(n_bars, n_symbols))
    if correlated and n_symbols >= 3:
        common = rng.normal(0.0, 0.01, size=n_bars)
        steps[:, 1] = 0.8 * common + 0.2 * steps[:, 1]
        steps[:, 2] = 0.8 * common + 0.2 * steps[:, 2]
    close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    frames = {}
    for j, symbol in enumerate(symbols):
        c = close[:, j]
        o = np.concatenate(([c[0]], c[:-1]))
        volume = rng.uniform(100, 200, size=n_bars)
        frames[symbol] = pd.DataFrame(
            {
                "open_time": ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy(),
                "open": o,
                "high": np.maximum(o, c) * 1.002,
                "low": np.minimum(o, c) * 0.998,
                "close": c,
                "volume": volume,
                "quote_volume": volume * c,
                "trades": 10,
                "taker_buy_base": volume * rng.uniform(0.3, 0.7, size=n_bars),
                "taker_buy_quote": volume * c * rng.uniform(0.3, 0.7, size=n_bars),
            }
        )
    funding = None
    if with_funding:
        funding = pd.DataFrame(0.0, index=index, columns=symbols)
        funding.iloc[::8] = rng.normal(0.0001, 0.0002, size=(len(funding.iloc[::8]), n_symbols))
    return Panel.from_frames(frames, "1h", funding=funding)


def _live_params() -> list[tuple[str, dict]]:
    """Every enabled entry of the registry, so the suite covers the params the loop actually holds.

    KILL-AR-15's fix sized the panel from `warmup_for`, which was right, and then read the warmup off
    `default_params` - and the defaults are not what runs.  Measured 2026-09-09: tsmom's defaults warm
    up in 101 bars, the registry runs `horizons: [168, 336, 720]` with `vol_window: 400` for a warmup
    of 721; flow is 49 against the same 721.  So the causality, boundedness and non-vacuity checks were
    all being made about a configuration this system decided against in round 6, and the one it trades
    had never been through them.  The parametrisation below closes that: defaults AND the registry.
    """
    from starquant_alpha.registry import parse_registry
    from starquant_shared.config import load_yaml

    registry = parse_registry(load_yaml("config/alpha_registry.yaml"))
    return [(entry.id, dict(entry.params)) for entry in registry.strategies if entry.enabled and entry.params]


CASES = [(signal_id, {}, "defaults") for signal_id in sorted(SIGNALS)] + [
    (signal_id, params, "live") for signal_id, params in _live_params()
]


@pytest.mark.parametrize(
    ("signal_id", "overrides", "label"), CASES, ids=[f"{name}-{label}" for name, _p, label in CASES]
)
def test_signals_are_causal_and_bounded(signal_id: str, overrides: dict, label: str) -> None:
    """KILL-AR-15 / T-S51-1: the panel is sized from the SIGNAL's warmup, not from a constant.

    It used to be 800 bars with the cutoff at 600, and that made this test vacuous for any signal
    whose warmup exceeds 600: every score before the cutoff was NaN, so the comparison was NaN
    against NaN and a signal that read the future would have passed.  tsmom's 720-bar horizon was
    already in that range, and chanlun's is too.  Sizing both from `warmup_for` keeps the test
    non-vacuous as warmups grow, and the assertion below makes the emptiness a failure rather than
    a silent pass.

    The comparison is bit for bit for the same reason.  Until 2026-09-23 it was `assert_frame_equal`'s
    default, rtol 1e-5 / atol 1e-8, and a signal that leaked less than that passed.
    """
    spec = SIGNALS[signal_id]
    params = {**spec.default_params, **overrides}
    warmup = spec.warmup_for(params)
    panel = _synthetic_panel(n_bars=warmup + 600, correlated=True)
    scores = spec.compute(panel, params)
    assert scores.shape == panel.close.shape
    assert ((scores.abs() <= 1.0) | scores.isna()).all().all()
    assert scores.iloc[-50:].notna().any().any(), f"{signal_id} produced no scores"
    cutoff = warmup + 300
    assert scores.iloc[:cutoff].notna().any().any(), (
        f"{signal_id} ({label}, warmup {warmup}): every score before the cutoff is NaN, so the "
        "causality comparison below would be NaN against NaN - the exact way this test was vacuous "
        "before KILL-AR-15"
    )
    shuffled = _synthetic_panel(seed=99, n_bars=len(panel.index), correlated=True)
    mixed_frames = {}
    for symbol in panel.symbols:
        mixed_frames[symbol] = pd.DataFrame(
            {
                field: np.concatenate(
                    [
                        getattr(panel, field)[symbol].to_numpy()[:cutoff],
                        getattr(shuffled, field)[symbol].to_numpy()[cutoff:],
                    ]
                )
                for field in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "quote_volume",
                    "trades",
                    "taker_buy_base",
                    "taker_buy_quote",
                )
            },
            index=panel.index,
        )
    funding = None
    if panel.funding is not None and shuffled.funding is not None:
        funding = pd.concat([panel.funding.iloc[:cutoff], shuffled.funding.iloc[cutoff:]])
    mixed = Panel.from_frames(mixed_frames, "1h", funding=funding)
    later = spec.compute(mixed, params)
    _bit_for_bit(scores.iloc[:cutoff], later.iloc[:cutoff])


def test_carry_direction_and_missing_funding() -> None:
    """T-A07: constant positive funding -> short; missing funding -> NaN, never 0."""
    index = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
    columns = pd.Index(["A", "B"])
    funding = pd.DataFrame(0.0, index=index, columns=columns)
    funding.loc[funding.index[::8], "A"] = 0.0001
    scores = carry_scores(funding, index, columns, CarryParams(window_bars=24, cross_sectional=False))
    assert (scores["A"].dropna() < 0).all()
    assert scores["B"].dropna().eq(0.0).all()  # zero funding observed -> flat, but B never settles -> NaN
    assert scores["B"].isna().all()
    assert carry_scores(None, index, columns).isna().all().all()
    relative = carry_scores(funding, index, columns, CarryParams(window_bars=24, cross_sectional=True))
    assert (relative["A"].dropna() < 0).all()


def test_meanrev_trades_against_dislocation_and_exits() -> None:
    index = pd.date_range("2024-01-01", periods=300, freq="h", tz="UTC")
    base = np.full(300, 100.0)
    base[200] = 130.0  # spike up: expect a short entry, then exit as the window absorbs it
    close = pd.DataFrame({"A": base + np.sin(np.arange(300)) * 0.5}, index=index)
    scores = meanrev_scores(close, MeanrevParams(window=48, z_entry=1.5, z_exit=0.5, trend_gate_z=50.0))
    assert scores["A"].iloc[200] < 0
    targets = scores_to_targets(scores, 0.2)
    assert targets["A"].iloc[200] < 0
    assert targets["A"].iloc[-1] == 0.0  # explicit exit once |z| < z_exit


def test_xsmom_ranks_relative_winners() -> None:
    index = pd.date_range("2024-01-01", periods=400, freq="h", tz="UTC")
    trend = np.exp(np.linspace(0, 0.5, 400))
    wiggle = 1.0 + 0.001 * np.sin(np.arange(400))  # a truly constant series has zero vol and no risk-adjusted score
    close = pd.DataFrame({"UP": 100 * trend, "FLAT": 100.0 * wiggle, "DOWN": 100 / trend}, index=index)
    scores = xsmom_scores(
        close, XsmomParams(horizons=(24, 72, 168), horizon_weights=(0.2, 0.3, 0.5), skip_bars=0, vol_window=100)
    )
    last = scores.iloc[-1]
    assert last["UP"] > last["FLAT"] > last["DOWN"]
    assert last["UP"] > 0 > last["DOWN"]


def test_residual_is_zero_for_a_pure_beta_follower() -> None:
    rng = np.random.default_rng(1)
    index = pd.date_range("2024-01-01", periods=800, freq="h", tz="UTC")
    bench = np.exp(np.cumsum(rng.normal(0, 0.01, 800)))
    close = pd.DataFrame({"BTCUSDT": 100 * bench, "FOLLOWER": 50 * bench**1.5}, index=index)
    scores = residual_scores(close, ResidualParams(horizons=(24, 72), beta_window=200, scale=0.05))
    assert scores["BTCUSDT"].isna().all()
    assert scores["FOLLOWER"].iloc[-100:].abs().max() < 0.05


def test_explicit_zero_exit_semantics() -> None:
    index = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    scores = pd.DataFrame({"A": [np.nan, 0.5, 0.1, 0.0, np.nan]}, index=index)
    held = scores_to_targets(scores, 0.2)
    assert held["A"].tolist()[1:] == [0.5, 0.5, 0.0, 0.0]
    assert np.isnan(held["A"].iloc[0])


def test_xsmom_skip_bars_ignores_the_most_recent_returns() -> None:
    """With skip_bars=k the latest score must not depend on the last k bars (1-24h is reversal)."""
    rng = np.random.default_rng(11)
    index = pd.date_range("2024-01-01", periods=1200, freq="h", tz="UTC")
    base = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (1200, 5)), axis=0)), index=index, columns=list("ABCDE")
    )
    params = XsmomParams(horizons=(168, 336), horizon_weights=(0.4, 0.6), skip_bars=24, vol_window=200)
    reference = xsmom_scores(base, params).iloc[-1]
    shocked = base.copy()
    shocked.iloc[-24:] *= rng.uniform(0.7, 1.3, size=(24, 5))  # rewrite the last 24 bars only
    assert np.allclose(xsmom_scores(shocked, params).iloc[-1].to_numpy(), reference.to_numpy(), equal_nan=True)
    exposed = xsmom_scores(
        shocked, XsmomParams(horizons=(168, 336), horizon_weights=(0.4, 0.6), skip_bars=0, vol_window=200)
    ).iloc[-1]
    assert not np.allclose(exposed.to_numpy(), reference.to_numpy(), equal_nan=True)


def test_xsmom_risk_adjustment_favours_the_calmer_winner() -> None:
    rng = np.random.default_rng(12)
    index = pd.date_range("2024-01-01", periods=1500, freq="h", tz="UTC")
    n = len(index)
    drift = 0.0004
    calm = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, n)))
    wild = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.03, n)))
    flat = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    close = pd.DataFrame({"CALM": calm, "WILD": wild, "FLAT": flat, "F2": flat * 1.01, "F3": flat * 0.99}, index=index)
    scores = xsmom_scores(
        close, XsmomParams(horizons=(168, 336), horizon_weights=(0.4, 0.6), skip_bars=24, vol_window=200)
    )
    tail = scores.iloc[-200:].mean()
    assert tail["CALM"] > 0
    assert abs(tail["CALM"]) > abs(tail["WILD"]) * 0.5  # the calm winner is at least as convincing


def test_carry_rank_mode_is_immune_to_one_extreme_name() -> None:
    from starquant_alpha.signals.carry import CarryParams, carry_scores

    index = pd.date_range("2024-01-01", periods=240, freq="h", tz="UTC")
    columns = pd.Index(["A", "B", "C", "D", "E", "MEME"])
    funding = pd.DataFrame(0.0, index=index, columns=columns)
    settle = funding.index[::8]
    # C settles at a tiny but non-zero rate: an all-zero window is indistinguishable from "no funding data"
    funding.loc[settle, ["A", "B", "C", "D", "E"]] = [[0.0001, 0.00005, 0.000001, -0.00005, -0.0001]] * len(settle)
    funding.loc[settle, "MEME"] = 0.02  # absurd: 2% per settlement
    scores = carry_scores(funding, index, columns, CarryParams(window_bars=72, mode="rank"))
    last = scores.iloc[-1]
    assert last["MEME"] == -1.0 and last["E"] == 1.0
    assert last["A"] < last["B"] < last["C"] < last["D"]
    assert ((scores.abs() <= 1.0) | scores.isna()).all().all()
    level = carry_scores(funding, index, columns, CarryParams(window_bars=72, mode="level", winsor_pct=0.10))
    assert level.iloc[-1]["A"] < 0 < level.iloc[-1]["E"]  # median-centred: the outlier cannot flip A's sign
    assert level.iloc[-1]["MEME"] <= level.iloc[-1]["A"]  # still the most negative name


def test_tsmom_crowding_modifier_shrinks_only_crowded_same_direction_scores() -> None:
    from starquant_alpha.signals.tsmom import TsmomParams, apply_crowding_modifier

    index = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
    columns = pd.Index(["A", "B", "C", "D", "E"])
    score = pd.DataFrame(0.5, index=index, columns=columns)
    score["E"] = -0.5
    funding = pd.DataFrame(0.0, index=index, columns=columns)
    funding.loc[funding.index[::8], :] = [[0.001, 0.0001, 0.00005, -0.00005, -0.001]] * len(funding.index[::8])
    params = TsmomParams(crowding_window=72, crowding_cut=0.7, crowding_penalty=0.5)
    out = apply_crowding_modifier(score, funding, params)
    last = out.iloc[-1]
    assert last["A"] == 0.25  # crowded long (highest funding, long score) -> halved
    assert last["E"] == -0.25  # crowded short (most negative funding, short score) -> halved
    assert last["B"] == 0.5 and last["C"] == 0.5 and last["D"] == 0.5
    assert apply_crowding_modifier(score, funding, TsmomParams()).equals(score)  # disabled by default
    assert apply_crowding_modifier(score, None, params).equals(score)  # no funding -> untouched


def test_flow_short_gate_drops_only_shorts_against_strong_uptrends() -> None:
    """Round 5: perp taker selling into a spot-led rally is not informed flow; longs into downtrends are untouched."""
    from starquant_alpha.signals.flow import FlowParams, flow_scores

    n_bars = 400
    index = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    open_time = ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy()
    rng = np.random.default_rng(3)

    def frame(drift: float, taker_share: float) -> pd.DataFrame:
        close = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.002, size=n_bars)))
        open_ = np.concatenate(([close[0]], close[:-1]))
        volume = np.full(n_bars, 100.0)
        return pd.DataFrame(
            {
                "open_time": open_time,
                "open": open_,
                "high": np.maximum(open_, close),
                "low": np.minimum(open_, close),
                "close": close,
                "volume": volume,
                "quote_volume": volume * close,
                "trades": 10,
                "taker_buy_base": volume * taker_share,
                "taker_buy_quote": volume * close * taker_share,
            }
        )

    # UP: strong uptrend with net taker selling; DOWN: strong downtrend with net taker buying.
    panel = Panel.from_frames({"UP": frame(0.004, 0.35), "DOWN": frame(-0.004, 0.65)}, "1h")
    base = FlowParams(window=24, volume_window=48, cross_sectional=True)
    gated = FlowParams(
        window=24,
        volume_window=48,
        cross_sectional=True,
        short_gate=0.3,
        gate_horizons=(24, 48, 96),
        gate_weights=(0.2, 0.3, 0.5),
        gate_vol_window=100,
    )
    raw = flow_scores(panel, base).iloc[-100:]
    out = flow_scores(panel, gated).iloc[-100:]
    assert (raw["UP"] < 0).all() and (raw["DOWN"] > 0).all()
    assert (out["UP"] == 0.0).all()  # short blocked -> explicit exit
    pd.testing.assert_series_equal(out["DOWN"], raw["DOWN"])  # the long leg is not gated
    assert gated.warmup_bars == 97 and base.warmup_bars == 49
    with pytest.raises(ValueError):
        FlowParams(short_gate=1.5)


def test_flow_short_only_drops_longs_but_keeps_buy_signals_as_exits() -> None:
    from starquant_alpha.signals.flow import FlowParams, flow_scores

    panel = _synthetic_panel(seed=11, n_symbols=4)
    both = flow_scores(panel, FlowParams(window=24))
    short_only = flow_scores(panel, FlowParams(window=24, long_side=False))
    assert (short_only.where(both > 0) == 0.0).sum().sum() == (both > 0).sum().sum()  # longs -> explicit exit
    pd.testing.assert_frame_equal(short_only.where(both <= 0), both.where(both <= 0))
