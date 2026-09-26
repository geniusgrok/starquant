"""`flow`'s volume-expansion warm-up: the aggressive fill is now a named knob, and its default is today.

`expansion` is in (0, 1] and multiplies the imbalance, so `fillna(1.0)` scores the un-warm bars as
though volume had expanded as much as it ever can - the upper bound, not a neutral value.  Two facts
have to be held at once, and this file asserts both rather than picking the comfortable one:

* the default is unchanged and bit-identical, because `flow_short` is ENABLED and the live loop
  re-presents the head of a sliding 1,442-bar window every cycle, where `scores_to_targets` can carry
  a value forward to the bar actually being traded;
* the fill IS reachable under the shipped registry, but not through the door the review named.
  `window` 168 against `volume_window` 48 closes the warm-up head entirely; measured on the
  point-in-time panel (205 symbols x 49,937 bars), all 4,284 bars it reaches come from
  `volume_ratio`'s other NaN - a trailing 48-bar mean volume of exactly zero - so what is being
  scored as "maximum volume expansion" is a symbol that has stopped quoting.  238 of the 4,284 are
  inside the eligible/point-in-time mask.

Adopting `None` is therefore an operator decision with its own evidence, and this file's job is to make
sure it is available as a config edit and that choosing it is visible rather than silent.
"""

from __future__ import annotations

from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from starquant_alpha.features import apply_numpy, taker_buy_ratio, volume_ratio
from starquant_alpha.panel import Panel
from starquant_alpha.signals import get_signal
from starquant_alpha.signals.flow import FlowParams, flow_scores
from tests.alpha.test_causality import _bit_for_bit

DEFAULTS = FlowParams()


def _panel(n: int = 300, k: int = 4, seed: int = 7) -> Panel:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-02-01", periods=n, freq="h", tz="UTC")
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.006, size=(n, k)), axis=0)),
        index=index,
        columns=[f"S{i}" for i in range(k)],
    )
    quote = pd.DataFrame(rng.lognormal(12.0, 0.8, size=(n, k)), index=index, columns=close.columns)
    share = pd.DataFrame(rng.uniform(0.3, 0.7, size=(n, k)), index=index, columns=close.columns)
    frames = {
        symbol: pd.DataFrame(
            {
                "open_time": index,
                "open": close[symbol].to_numpy(),
                "high": (close[symbol] * 1.002).to_numpy(),
                "low": (close[symbol] * 0.998).to_numpy(),
                "close": close[symbol].to_numpy(),
                "volume": (quote[symbol] / close[symbol]).to_numpy(),
                "quote_volume": quote[symbol].to_numpy(),
                "trades": 100.0,
                "taker_buy_base": (quote[symbol] * share[symbol] / close[symbol]).to_numpy(),
                "taker_buy_quote": (quote[symbol] * share[symbol]).to_numpy(),
            }
        )
        for symbol in close.columns
    }
    return Panel.from_frames(frames, interval="1h")


def test_the_default_multiplier_on_the_un_warm_bars_is_still_exactly_one() -> None:
    """The old expression, rebuilt on the bars where it was the only thing acting.  Bit for bit."""
    params = replace(DEFAULTS, window=24, volume_window=48, cross_sectional=False, short_gate=0.0)
    panel = _panel()
    expansion = volume_ratio(panel.volume, params.volume_window).clip(upper=1.0)
    gap = panel.index[params.window : params.volume_window]
    assert expansion.loc[gap].isna().to_numpy().all(), "these are exactly the bars the fill reaches"
    imbalance = taker_buy_ratio(panel.taker_buy_quote, panel.quote_volume, params.window) - 0.5
    old = apply_numpy(imbalance / params.scale, np.tanh).clip(-1.0, 1.0).where(imbalance.notna())
    _bit_for_bit(flow_scores(panel, params).loc[gap], old.loc[gap])


def test_none_leaves_the_un_warm_bars_missing_which_is_what_warmup_bars_already_promised() -> None:
    params = replace(DEFAULTS, window=24, volume_window=48)
    panel = _panel()
    filled, unfilled = flow_scores(panel, params), flow_scores(panel, replace(params, volume_warmup_fill=None))
    gap = panel.index[params.window : params.volume_window]  # bars 25-48: imbalance warm, expansion not
    assert len(gap) == 24
    assert filled.loc[gap].notna().to_numpy().any(), "the aggressive fill really does score these bars"
    assert not unfilled.loc[gap].notna().to_numpy().any(), "`None` must leave them missing"
    after = panel.index[params.volume_window + 1 :]
    pd.testing.assert_frame_equal(filled.loc[after], unfilled.loc[after])
    # The fill is an upper bound, so dropping it can only shrink |score| - a strictly less aggressive
    # book, which is the direction the review named.
    assert (filled.loc[gap].abs().to_numpy() >= 0).all()


def test_under_the_shipped_windows_the_fill_is_reached_by_a_symbol_that_stopped_quoting() -> None:
    """The measured door, which is not the one the shape suggests.

    `window` 168 > `volume_window` 48 does close the warm-up head: the imbalance mask covers every bar
    the head fill could touch.  But `volume_ratio` has a second NaN - `baseline.where(baseline > 0)` -
    and on the point-in-time panel that one accounts for all 4,284 bars the shipped registry actually
    reaches.  A symbol whose trailing volume is zero is being scored as maximally expanding.
    """
    shipped = replace(DEFAULTS, window=168, volume_window=48, cross_sectional=False)
    panel = _panel(n=400)
    pd.testing.assert_frame_equal(
        flow_scores(panel, shipped), flow_scores(panel, replace(shipped, volume_warmup_fill=None))
    )
    stopped = panel.volume.copy()
    stopped.iloc[300:, 0] = 0.0  # S0 stops printing; its trailing mean reaches zero 48 bars later
    quiet = Panel(**{**panel.__dict__, "volume": stopped})
    filled = flow_scores(quiet, shipped)
    unfilled = flow_scores(quiet, replace(shipped, volume_warmup_fill=None))
    dead = (filled.notna() & unfilled.isna()).to_numpy()
    assert dead.sum() > 0, "a zero-volume stretch must reach the fill even with window > volume_window"
    assert not dead[:, 1:].any(), "only the symbol that stopped quoting is affected"
    # And on those bars the multiplier is exactly 1: the score is the raw imbalance, at full size.
    imbalance = taker_buy_ratio(quiet.taker_buy_quote, quiet.quote_volume, shipped.window) - 0.5
    at_full_size = apply_numpy(imbalance / shipped.scale, np.tanh).clip(-1.0, 1.0)
    np.testing.assert_array_equal(filled.to_numpy()[dead], at_full_size.to_numpy()[dead])


def test_the_knob_survives_from_mapping_and_shows_up_in_the_canonical_params() -> None:
    """Phase-4a shape: adopting it must be a config edit, and the registry digest must be able to see it."""
    assert FlowParams.from_mapping({"volume_warmup_fill": None}).volume_warmup_fill is None
    assert FlowParams.from_mapping({"volume_warmup_fill": 0.5}).volume_warmup_fill == 0.5
    assert "volume_warmup_fill" in asdict(DEFAULTS)
    canonical = get_signal("flow").canonical_params({"window": 168})
    assert canonical["volume_warmup_fill"] == 1.0
    assert (
        get_signal("flow").canonical_params({"window": 168, "volume_warmup_fill": None})["volume_warmup_fill"] is None
    )
    for bad in (0.0, 1.5, -1.0):
        try:
            FlowParams(volume_warmup_fill=bad)
        except ValueError:
            continue
        raise AssertionError(f"volume_warmup_fill={bad} is outside expansion's range and should not construct")
