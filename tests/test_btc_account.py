"""Contracts the account replay has to keep, without the full market tape."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from btc_perp.config import ROOT, load_config
from btc_perp.costs import (
    ENTRY_SCALE,
    ENTRY_SCALE_BELOW,
    FX_FEE,
    IMPACT_Y,
    LEVERAGE,
    MARGIN_BRACKETS,
    SLIP_BASE,
    START_CNY,
    TAKER,
    new_entry_scale,
)
from btc_perp.exchange import BinanceExchange
from scripts.frontier import _clamp_stop, _liq_from, _liq_price, _mmr_cum, _slip_amt, causal_fx, run


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
    assert cfg.start_cny == START_CNY
    assert cfg.live_orders is False


def test_maintenance_brackets_match_the_published_table() -> None:
    for cap, rate, amount in MARGIN_BRACKETS:
        got_rate, got_amount = _mmr_cum(cap)
        assert got_rate == rate
        assert got_amount == amount
    assert _mmr_cum(50_000.01) == (0.005, 50.0)
    assert _mmr_cum(800_000.0) == (0.01, 1_300.0)


def test_liquidation_price_uses_the_bracket_at_that_price() -> None:
    # Mark notional is just inside the 1% tier. The liquidation notional falls
    # into the 0.5% tier, so the price has to be solved there.
    entry = 100.0
    qty = 2_500.01
    isolated = entry * qty / LEVERAGE
    mark_rate, mark_cum = _mmr_cum(entry * qty)
    assert mark_rate == 0.01
    inconsistent = _liq_from(1, entry, qty, isolated, mark_rate, mark_cum)
    assert _mmr_cum(qty * inconsistent)[0] == 0.005
    rate, cum = _mmr_cum(qty * inconsistent)
    consistent = _liq_from(1, entry, qty, isolated, rate, cum)
    assert _liq_price(1, entry, qty, isolated, entry) == pytest.approx(consistent)
    assert consistent != pytest.approx(inconsistent)


def test_a_stop_cannot_sit_through_liquidation() -> None:
    # 800k notional is in the 1% bracket. A stop 10% below entry is past liquidation.
    entry = 100_000.0
    qty = 8.0
    isolated = entry * qty / LEVERAGE
    liq = _liq_price(1, entry, qty, isolated, entry)
    assert liq == pytest.approx((entry * qty - isolated - 1_300.0) / (qty * 0.99))
    clamped = _clamp_stop(1, entry * 0.90, entry, qty, isolated, entry)
    assert clamped == pytest.approx(liq * 1.001)
    assert clamped > liq


def test_impact_stays_inside_the_completed_bar() -> None:
    calm = _slip_amt(100.0, 1.0, 100.1, 99.9, 1_000_000.0)
    empty = _slip_amt(100.0, 1.0, 110.0, 90.0, 0.0)
    assert empty == pytest.approx(SLIP_BASE + IMPACT_Y * 0.2)
    assert calm < empty


def test_fx_fixing_is_applied_only_after_its_date() -> None:
    rates = {dt.date(2020, 1, 2): 7.0, dt.date(2020, 1, 3): 8.0}
    days = [dt.date(2020, 1, 2), dt.date(2020, 1, 3), dt.date(2020, 1, 4)]
    assert list(causal_fx(days, rates, fallback=6.5)) == [6.5, 7.0, 8.0]


@pytest.mark.skipif(not (ROOT / "data" / "usdcny_frankfurter.json").exists(), reason="FX file is not in the tree")
def test_replay_fx_does_not_use_the_same_days_fixing() -> None:
    from scripts.frontier import load_hourly

    _o, _h, _l, _c, _fund, fx, days = load_hourly()
    # 2020-01-02 is the first stored fixing after the New Year holiday.
    # The bar on that date still uses the 2019-12-31 rate.
    jan2 = np.where(days == 20200102)[0]
    jan3 = np.where(days == 20200103)[0]
    assert fx[jan2[0]] == pytest.approx(6.9615)
    assert fx[jan3[0]] == pytest.approx(6.9638)


def test_a_stop_uses_the_previous_minutes_impact() -> None:
    # Bar 2 is calm. Bar 3 gaps through the stop and has an empty book.
    # The fill must pay the calm bar's slippage, not the empty bar's.
    n = 4
    # Bullish stop bar: open, then low, so the low is tested before any new high.
    # The close is back inside the channel, so the same bar does not re-enter.
    open_ = np.array([100.0, 101.0, 101.0, 99.0])
    high = np.array([100.0, 101.0, 101.0, 100.0])
    low = np.array([100.0, 101.0, 101.0, 70.0])
    close = np.array([100.0, 101.0, 101.0, 100.0])
    qv = np.array([1.0e7, 1.0e7, 1.0e7, 0.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(open_, high, low, close, np.zeros(n), qv=qv)
    assert n_long == 1
    assert n_stop == 1
    assert end == pytest.approx(_stopped_equity(), rel=0, abs=1e-6)


def test_funding_liquidation_closes_at_the_mark_and_keeps_free_cash() -> None:
    # A 4.9% funding charge uses up the 5% posted margin. The close is at the
    # open, not a confiscation of whatever margin is left after the charge.
    open_ = np.array([100.0, 101.0, 101.0, 100.0])
    close = np.array([100.0, 101.0, 100.0, 100.0])
    high = np.maximum(open_, close)
    low = np.minimum(open_, close)
    fund = np.array([0.0, 0.0, 0.049, 0.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(open_, high, low, close, fund, max_units=1)
    assert n_long == 1
    assert n_stop == 1
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q, fill_in, fee_in = _entry(wallet0)
    isolated = q * fill_in / LEVERAGE
    pay = q * 101.0 * 0.049
    fill_out = 101.0 * (1.0 - SLIP_BASE)
    fee_out = q * fill_out * TAKER
    raw = (fill_out - fill_in) * q - fee_out
    delta = raw - pay
    assert delta > -isolated
    wallet = wallet0 - fee_in + delta
    expected = wallet * 7.0 * (1.0 - FX_FEE)
    assert end == pytest.approx(expected, rel=0, abs=1e-4)
    confiscated = (wallet0 - fee_in - isolated) * 7.0 * (1.0 - FX_FEE)
    assert end > confiscated + 1.0


def test_unrealized_profit_covers_funding_so_the_position_stays_open() -> None:
    open_ = np.array([101.0, 130.0, 130.0])
    close = open_.copy()
    fund = np.array([0.0, 0.05, 0.0])
    end, _ratio, n_long, _n_short, n_stop, _min_i = _replay(open_, close, close, close, fund, max_units=1)
    assert n_long == 1
    assert n_stop == 0
    wallet0 = 10000.0 / (7.0 * (1.0 + FX_FEE))
    q, fill_in, fee_in = _entry(wallet0, price=101.0)
    pay = q * 130.0 * 0.05
    equity = wallet0 - fee_in - pay + (130.0 - fill_in) * q
    expected = equity * 7.0 * (1.0 - FX_FEE)
    assert end == pytest.approx(expected, rel=0, abs=1e-4)


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
    qv: np.ndarray | None = None,
    max_units: int = 3,
) -> tuple[float, float, int, int, int, int]:
    n = len(close)
    if trace is None:
        trace = np.empty((1, 4))
    if qv is None:
        qv = np.empty(1)
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
        max_units,
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
        qv,
        np.empty(1),
        trace,
        np.empty(1),
    )
