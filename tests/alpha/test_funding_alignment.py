"""A settlement belongs to the bar that contains it, not to a bar whose open time it equals.

Binance stamps ``fundingTime`` one to forty-seven milliseconds past the hour and does so unevenly
over the years.  Matching on equality therefore dropped 43.7% of the 1,010,914-settlement archive
onto a silent zero: ``use_actual_funding`` backtests under-charged funding by roughly half, and a
funding-consuming signal (carry, tsmom's crowding modifier) saw half its input while looking
perfectly healthy.  These tests fail on the equality form.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.panel import Panel
from starquant_alpha.signals.carry import CarryParams, carry_scores

BARS = 400
INDEX = pd.date_range("2024-01-01", periods=BARS, freq="h", tz="UTC")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "BNBUSDT")


def _panel(funding: pd.DataFrame | None) -> Panel:
    frames = {}
    for j, symbol in enumerate(SYMBOLS):
        close = 100.0 * np.exp(np.cumsum(np.full(BARS, 0.0001 * (j + 1))))
        frames[symbol] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": np.full(BARS, 1000.0),
            },
            index=INDEX,
        )
    return Panel.from_frames(frames, "1h", funding=funding)


def _settlements(offsets_ms: list[int], rate: float = 0.0001) -> pd.DataFrame:
    """Eight-hourly settlements, each stamped ``offsets_ms[k]`` past its bar open."""
    stamps, rates = [], []
    for k, bar in enumerate(INDEX[::8]):
        stamps.append(bar + pd.Timedelta(milliseconds=offsets_ms[k % len(offsets_ms)]))
        rates.append(rate)
    return pd.DataFrame(dict.fromkeys(SYMBOLS, rates), index=pd.DatetimeIndex(stamps))


def test_a_settlement_stamped_past_the_hour_still_lands_on_its_bar() -> None:
    exact = _panel(_settlements([0]))
    offset = _panel(_settlements([5]))  # the shape the venue actually returns
    assert exact.funding is not None and offset.funding is not None
    assert int((exact.funding != 0).sum().sum()) == BARS // 8 * len(SYMBOLS)
    pd.testing.assert_frame_equal(offset.funding, exact.funding)


def test_the_real_offset_distribution_is_not_silently_halved() -> None:
    """1-47 ms is the observed range; the archive's mix of exact and offset stamps must all survive."""
    mixed = _panel(_settlements([0, 1, 5, 47, 12, 0, 3]))
    assert mixed.funding is not None
    assert int((mixed.funding != 0).sum().sum()) == BARS // 8 * len(SYMBOLS)


def test_two_settlements_inside_one_bar_are_summed() -> None:
    stamps = [INDEX[8] + pd.Timedelta(milliseconds=4), INDEX[8] + pd.Timedelta(minutes=30)]
    funding = pd.DataFrame({symbol: [0.0001, 0.0002] for symbol in SYMBOLS}, index=pd.DatetimeIndex(stamps))
    panel = _panel(funding)
    assert panel.funding is not None
    assert panel.funding.loc[INDEX[8], "BTCUSDT"] == pytest.approx(0.0003)


def test_a_dropped_settlement_would_understate_the_funding_a_backtest_charges() -> None:
    """The alignment is a cost, not a detail: this is the half of the funding bill research was missing."""
    weights = pd.DataFrame(1.0, index=INDEX, columns=list(SYMBOLS))
    cost = CostModel(turnover_bps=0.0, use_funding=True)
    charged = run_backtest(_panel(_settlements([5])), weights, cost).portfolio_net.sum()
    dropped = run_backtest(_panel(None), weights, cost).portfolio_net.sum()
    assert dropped - charged == pytest.approx(len(SYMBOLS) * (BARS // 8 - 1) * 0.0001, rel=0.05)


def test_carry_scores_the_offset_settlements_instead_of_seeing_an_unfunded_universe() -> None:
    panel = _panel(_settlements([7]))
    params = CarryParams(window_bars=72)
    scores = carry_scores(panel.funding, panel.close.index, panel.close.columns, params)
    assert scores.notna().any().any(), "carry saw no settled funding at all"
    assert scores.iloc[-1].notna().all()


def test_funding_indexed_by_position_is_refused_rather_than_zeroed() -> None:
    positional = pd.DataFrame({symbol: np.zeros(BARS) for symbol in SYMBOLS})
    with pytest.raises(ValueError, match="settlement time"):
        _panel(positional)
