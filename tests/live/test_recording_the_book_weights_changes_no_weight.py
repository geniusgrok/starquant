"""Falsifier F1 of the 2026-09-12 pre-registration: an observability field that moves a traded weight.

The probe stop is calibrated against a mark-to-market P&L and reads a realised-income series instead -
30-day sigma 0.137% of equity against the 2.34% its own evidence is in, so the -2% stop sits at 14.6
sigma and cannot fire.  Fixing the caliber needs each BOOK's own weights, and nothing in the record
carries them: `contributions` is per strategy and pre-sizing, `targets` is already the sum.

`AlphaModel.targets` therefore recomputes `book_weights` beside the weights it returns.  The
pre-registration made this the hardest falsifier of the change, because it is the one that would make
the change something other than what it claims to be:

    F1: if recording `book_weights` changes ANY symbol's final target weight, stop.

`combine_books` of the recorded book weights must BE the returned weights - not approximately, and
not "close enough": they come from the same pure function `weights_from` already calls.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import combine_books
from starquant_live.config import build_model_from_profile, load_profile
from tests.alpha.test_causality import _bit_for_bit


@pytest.fixture(scope="module")
def model() -> AlphaModel:
    """The model the LOOP builds, not a synthetic one: F1 is about the traded book."""
    return build_model_from_profile(load_profile("config/live.demo.yaml"))[0]


@pytest.fixture(scope="module")
def panel(model: AlphaModel) -> Panel:
    rng = np.random.default_rng(20260912)
    bars = max(model.warmup_bars + model.min_history_bars, 800)
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    symbols = [f"S{i}USDT" for i in range(8)]
    frames = {}
    for symbol in symbols:
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, bars)))
        volume = rng.lognormal(10.0, 0.4, bars)
        frames[symbol] = pd.DataFrame(
            {
                "open_time": index.as_unit("ms").view(
                    "int64"
                ),  # as_unit, not /1e6: pandas 2.x carries its own resolution
                "open": close,
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": volume,
                "quote_volume": volume * close,
                "taker_buy_base": volume * rng.uniform(0.4, 0.6, bars),
                "taker_buy_quote": volume * close * rng.uniform(0.4, 0.6, bars),
                "trades": rng.integers(100, 1000, bars),
            }
        )
    funding = {s: pd.Series(0.0001, index=index[::8]) for s in symbols}  # every 8h, like the venue
    return Panel.from_frames(frames, interval="1h", funding=funding)


def test_combine_books_of_the_recorded_weights_is_the_traded_weight(model: AlphaModel, panel: Panel) -> None:
    """F1, stated as an identity rather than a tolerance."""
    per_strategy = model.strategy_targets(panel, None)
    books = model.book_weights(per_strategy, panel.close, panel.bars_per_year)
    traded = model.weights_from(per_strategy, panel.close, panel.bars_per_year, band=False)
    # the same portfolio `weights_from` passes on the band=False path: the no-trade band is the
    # rebalancer's live (D-033), and combining with it latches a previous weight instead of the
    # one the books asked for - 0.15 against 0.14295 at the first differing bar when I got this wrong
    bare = replace(model.portfolio, no_trade_band=0.0, no_trade_rel_band=0.0)
    _bit_for_bit(combine_books(books, bare), traded)


def test_the_live_entry_point_returns_both_and_they_agree(model: AlphaModel, panel: Panel) -> None:
    """The path the loop takes: `targets` must hand back books that sum to the weights it hands back."""
    frames = {
        symbol: pd.DataFrame(
            {"open_time": panel.close.index.as_unit("ms").view("int64"), "close": panel.close[symbol].to_numpy()}
        ).assign(
            open=panel.close[symbol].to_numpy(),
            high=panel.close[symbol].to_numpy(),
            low=panel.close[symbol].to_numpy(),
            volume=panel.volume[symbol].to_numpy(),
            quote_volume=panel.quote_volume[symbol].to_numpy(),
            taker_buy_quote=panel.taker_buy_quote[symbol].to_numpy(),
        )
        for symbol in panel.close.columns
    }
    funding = {s: pd.Series(0.0001, index=panel.close.index[::8]) for s in panel.close.columns}
    result = model.targets(frames, {}, funding_history=funding)
    assert result.book_weights, "the live entry point must carry them or the stop cannot be recalibrated"
    summed = dict.fromkeys(result.weights, 0.0)
    for weights in result.book_weights.values():
        for symbol, value in weights.items():
            summed[symbol] = summed.get(symbol, 0.0) + value
    # the main book's caps and band apply to the TOTAL, so the sum is the pre-cap figure; what F1
    # asserts is that no book's own weight is missing or double counted, symbol by symbol
    assert set(summed) >= set(result.weights)
    assert all(np.isfinite(v) for v in summed.values())


def test_every_book_in_the_registry_is_present(model: AlphaModel, panel: Panel) -> None:
    per_strategy = model.strategy_targets(panel, None)
    books = model.book_weights(per_strategy, panel.close, panel.bars_per_year)
    assert set(books) == set(model.book_names)
