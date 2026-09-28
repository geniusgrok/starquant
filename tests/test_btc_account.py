"""Contracts the account replay has to keep, without the full market tape."""

from __future__ import annotations

import numpy as np
import pytest

from btc_perp.config import load_config
from btc_perp.costs import (
    ENTRY_SCALE,
    ENTRY_SCALE_BELOW,
    FX_FEE,
    IMPACT_Y,
    LEVERAGE,
    SLIP_BASE,
    TAKER,
    new_entry_scale,
)
from btc_perp.exchange import BinanceExchange
from scripts.frontier import run


def test_market_files_are_read_from_the_repo_data_dir() -> None:
    from btc_perp.config import ROOT
    from scripts.frontier import DATA_DIR

    assert DATA_DIR == ROOT / "data"


def test_yaml_fees_match_the_replay_constants() -> None:
    cfg = load_config()
    assert cfg.taker == TAKER
    assert cfg.slip_base == SLIP_BASE
    assert cfg.impact_y == IMPACT_Y
    assert cfg.fx_fee == FX_FEE
    assert cfg.leverage == LEVERAGE
    assert cfg.live_orders is False


def test_new_entry_is_halved_only_below_the_close_peak_line() -> None:
    assert new_entry_scale(ENTRY_SCALE_BELOW) == 1.0
    assert new_entry_scale(ENTRY_SCALE_BELOW - 1e-12) == ENTRY_SCALE
    assert new_entry_scale(1.0) == 1.0


def test_live_flag_cannot_open_the_adapter() -> None:
    venue = BinanceExchange(True, True, True, "k")
    assert venue.allowed() is False


def test_drawdown_gate_blocks_entries_and_leaves_the_open_position() -> None:
    # dd_flat 0.01 blocks a new entry once equity/peak <= 0.99. The open long
    # must still be there: the gate does not flatten.
    n = 3
    close = np.array([100.0, 101.0, 100.5])
    end, _ratio, n_long, n_short, n_stop, _min_i = _replay(close, close, close, close, np.zeros(n), dd_flat=0.01)
    assert n_long == 1
    assert n_short == 0
    assert n_stop == 0
    assert end > 0.0


def test_stop_loss_matches_the_hand_ledger() -> None:
    close = np.array([100.0, 101.0, 90.0, 90.0])
    open_ = np.array([100.0, 101.0, 101.0, 101.0])
    high = np.array([100.0, 101.0, 101.0, 101.0])
    low = np.array([100.0, 101.0, 90.0, 90.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(open_, high, low, close, np.zeros(4))
    assert n_long == 1
    assert n_stop == 1
    assert end == pytest.approx(_stopped_equity(), rel=0, abs=1e-6)


def test_a_gap_through_the_stop_loses_only_isolated_margin() -> None:
    close = np.array([100.0, 101.0, 50.0, 50.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(close, close, close, close, np.zeros(4))
    assert n_long == 1
    assert n_stop == 1
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q, fill_in, fee_in = _entry(wallet0)
    isolated = q * fill_in / LEVERAGE
    expected = (wallet0 - fee_in - isolated) * 7.0 * (1.0 - FX_FEE)
    assert end == pytest.approx(expected, rel=0, abs=1e-6)


def test_funding_is_debited_once() -> None:
    close = np.array([100.0, 101.0, 101.0, 101.0])
    fund = np.array([0.0, 0.0, 0.001, 0.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(close, close, close, close, fund)
    assert n_long == 1
    assert n_stop == 0
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q, fill_in, fee_in = _entry(wallet0)
    pay = q * 101.0 * 0.001
    equity = wallet0 - fee_in - pay + (101.0 - fill_in) * q
    expected = equity * 7.0 * (1.0 - FX_FEE)
    assert end == pytest.approx(expected, rel=0, abs=1e-6)


def test_a_deep_loss_halves_the_next_entry() -> None:
    # One large stop leaves close-to-close equity under 82% of the peak.
    # The next signal must use the halved multiplier. dd_flat stays out of the way.
    close = np.array([100.0, 101.0, 90.0, 101.0, 101.0])
    open_ = np.array([100.0, 101.0, 101.0, 101.0, 101.0])
    high = open_.copy()
    low = np.array([100.0, 101.0, 90.0, 101.0, 101.0])
    trace = np.empty((5, 5))
    _replay(open_, high, low, close, np.zeros(5), risk=0.20, iso_frac=0.50, heat=0.0, trace=trace)
    second_qty = trace[4, 1]
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q1, fill_in, fee_in = _entry(wallet0, risk=0.20, iso_frac=0.50, heat=0.0)
    stop_px = fill_in * (1.0 - 0.032)
    fill_out = stop_px * (1.0 - SLIP_BASE)
    fee_out = q1 * fill_out * TAKER
    wallet1 = wallet0 - fee_in + (fill_out - fill_in) * q1 - fee_out
    ratio = wallet1 * 7.0 * (1.0 - FX_FEE) / 10000.0
    assert ratio < ENTRY_SCALE_BELOW
    dist = 101.0 * 0.032
    expected = np.floor(wallet1 * 0.20 * new_entry_scale(ratio) / dist * 1000.0) / 1000.0
    assert second_qty == pytest.approx(expected)
    assert expected < q1


def _entry(
    wallet: float,
    risk: float = 0.048,
    iso_frac: float = 0.28,
    heat: float = 0.6,
    price: float = 101.0,
    stop: float = 0.032,
) -> tuple[float, float, float]:
    dist = price * stop
    q = np.floor(wallet * risk / dist * 1000.0) / 1000.0
    capn = wallet * iso_frac * LEVERAGE
    if heat > 0.0:
        capn = min(capn, wallet * heat / 0.16)
    if q * price > capn:
        q = np.floor(capn / price * 1000.0) / 1000.0
    fill = price * (1.0 + SLIP_BASE)
    fee = q * fill * TAKER
    return float(q), float(fill), float(fee)


def _stopped_equity() -> float:
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q, fill_in, fee_in = _entry(wallet0)
    stop_px = fill_in * (1.0 - 0.032)
    fill_out = stop_px * (1.0 - SLIP_BASE)
    fee_out = q * fill_out * TAKER
    wallet = wallet0 - fee_in + (fill_out - fill_in) * q - fee_out
    return float(wallet * 7.0 * (1.0 - FX_FEE))


def _replay(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    fund: np.ndarray,
    dd_flat: float = 0.47,
    risk: float = 0.048,
    iso_frac: float = 0.28,
    heat: float = 0.6,
    trace: np.ndarray | None = None,
) -> tuple[float, float, int, int, int, int]:
    n = len(close)
    if trace is None:
        trace = np.empty((1, 4))
    return run(
        open_.astype(np.float64),
        high.astype(np.float64),
        low.astype(np.float64),
        close.astype(np.float64),
        fund.astype(np.float64),
        np.full(n, 7.0),
        np.full(n, 100.0),
        np.full(n, 50.0),
        np.full(n, 1_000.0),
        np.full(n, 10.0),
        0.032,
        0.16,
        0.05,
        3,
        risk,
        dd_flat,
        iso_frac,
        0,
        0,
        0.0,
        0.35,
        0.07,
        1,
        0,
        0.0,
        1,
        1.0,
        heat,
        0.0,
        np.ones(n, np.int8),
        np.empty(1),
        np.empty(1),
        trace,
        np.empty(1),
    )
