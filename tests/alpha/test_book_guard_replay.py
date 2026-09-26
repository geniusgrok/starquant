"""M1: the two book-level guards, replayed on the backtest's own equity path.

The test that matters is the first one.  At the shipped vol target neither guard is reachable - 5.6
years of the live book produced a worst UTC day of -3.5% against a -5% pause, and gross never crossed
2.0 - so if the replay is not provably inert there, every number this project has published would move
for no reason.  The rest check that it stops being inert exactly where it should.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, ParticipationModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams, clamp_book, hold_or_reduce
from starquant_alpha.panel import Panel
from tests.alpha.test_causality import _bit_for_bit

BARS = 240
SYMBOLS = ["AAAUSDT", "BBBUSDT"]


def _panel(returns: np.ndarray, quote_volume: float = 1.0) -> Panel:
    index = pd.date_range("2024-01-01", periods=BARS, freq="1h", tz="UTC")
    close = pd.DataFrame(100.0 * np.cumprod(1.0 + returns, axis=0), index=index, columns=SYMBOLS)
    frames = {
        symbol: pd.DataFrame(
            {
                "open": close[symbol].shift(1).fillna(100.0),
                "high": close[symbol],
                "low": close[symbol],
                "close": close[symbol],
                "volume": 1.0,
                "quote_volume": quote_volume,
            },
            index=index,
        )
        for symbol in SYMBOLS
    }
    return Panel.from_frames(frames, interval="1h")


def test_replay_is_bit_for_bit_inert_when_neither_guard_binds() -> None:
    rng = np.random.default_rng(7)
    panel = _panel(rng.normal(0.0, 0.002, size=(BARS, len(SYMBOLS))))
    weights = pd.DataFrame(0.05, index=panel.close.index, columns=SYMBOLS)
    cost = CostModel(turnover_bps=7.0)
    off = run_backtest(panel, weights, cost)
    on = run_backtest(panel, weights, cost, guards=BookGuardParams())
    _bit_for_bit(off.weights, on.weights)
    _bit_for_bit(off.portfolio_net, on.portfolio_net)
    guards = on.summary()["guards"]
    # gross 0.10 against the default 0.5% maintenance rate: the requirement is 5 bp of equity
    assert guards.pop("min_margin_buffer") > 1000.0
    assert guards == {
        "replayed": True,
        "gross_capped_bars": 0,
        "daily_loss_pause_bars": 0,
        "bars": len(on.weights),
        "liquidation_touches": 0,
    }
    assert off.summary().get("guards") is None


def test_a_losing_day_stops_the_book_adding_risk_for_the_rest_of_that_utc_day() -> None:
    returns = np.zeros((BARS, len(SYMBOLS)))
    returns[30:36, :] = -0.02  # a -11.4% stretch inside the second UTC day
    panel = _panel(returns)
    weights = pd.DataFrame(0.5, index=panel.close.index, columns=SYMBOLS)
    # caps wide enough to leave the 0.5 weights alone, so the pause is the only guard under test
    guards = BookGuardParams(max_weight=0.5, max_gross=2.0)
    result = run_backtest(panel, weights, CostModel(turnover_bps=0.0), guards=guards)
    events = result.guard_events
    assert events is not None
    paused = events["daily_loss_pause"]
    assert paused.any(), "the pause never fired on a -11% day"
    fired = paused[paused].index
    # The day is the DECISION bar's, not the execution bar's - the live loop rolls `day_start_equity`
    # in `_roll_day(bar_open_ms, ...)`, i.e. on the bar the weights were decided on.  So the last paused
    # execution bar is 00:00 of the next day, whose decision bar is 23:00 of the losing one.  Asserting
    # on execution timestamps here would demand the off-by-one-bar bug instead of catching it.
    decisions = fired - pd.Timedelta(hours=1)
    assert decisions.normalize().nunique() == 1
    assert fired.normalize().nunique() == 2
    held = result.weights.loc[fired]
    assert (held.abs() <= 0.5 + 1e-12).all().all()


def test_the_gross_cap_binds_and_is_recorded() -> None:
    panel = _panel(np.zeros((BARS, len(SYMBOLS))))
    weights = pd.DataFrame(0.14, index=panel.close.index, columns=SYMBOLS)
    result = run_backtest(
        panel, weights, CostModel(turnover_bps=0.0), guards=BookGuardParams(max_weight=0.15, max_gross=0.2)
    )
    assert result.guard_events is not None
    assert result.guard_events["gross_capped"].all()
    assert result.weights.abs().sum(axis=1).max() == pytest.approx(0.2)


def test_clamp_and_hold_or_reduce_are_the_primitives_live_shares() -> None:
    row, capped = clamp_book(np.array([0.3, -0.3]), 0.15, 2.0)
    assert row.tolist() == [0.15, -0.15] and not capped
    row, capped = clamp_book(np.array([0.15, -0.15]), 0.15, 0.2)
    assert capped and abs(row).sum() == pytest.approx(0.2)
    # only moves toward zero: same sign and smaller, or flat
    moved = hold_or_reduce(np.array([0.2, 0.05, -0.1, 0.1]), np.array([0.1, 0.1, 0.2, -0.1]))
    assert moved.tolist() == [0.1, 0.05, 0.0, 0.0]


def test_margin_buffer_is_recorded_and_never_touches_liquidation_on_the_shipped_book() -> None:
    """M-016: the claim "liquidation is unreachable at gross 2.0" becomes a number.

    It was true before this instrument existed - `margin_cap` 0.40, `max_weight` 0.15 and the -5% pause
    all sit far in front of it - but nothing stated it, and D-037 is the standing lesson that a correct
    fact no instrument reports is indistinguishable from an unproven one.
    """
    rng = np.random.default_rng(7)
    panel = _panel(rng.normal(0.0, 0.002, size=(BARS, len(SYMBOLS))))
    weights = pd.DataFrame(0.05, index=panel.close.index, columns=SYMBOLS)
    result = run_backtest(panel, weights, CostModel(turnover_bps=7.0), guards=BookGuardParams())
    events = result.guard_events
    assert events is not None
    assert "margin_buffer" in events.columns
    guards = result.summary()["guards"]
    assert guards["liquidation_touches"] == 0
    # gross 0.10 at the default 0.5% maintenance rate -> equity is ~2000x the requirement
    assert guards["min_margin_buffer"] > 100.0


def test_the_margin_buffer_collapses_and_records_a_touch_when_maintenance_eats_the_equity() -> None:
    """The instrument has to be able to fire, or reporting 0 touches proves nothing.

    Drives it from the maintenance rate rather than the book: at a rate this absurd the requirement is
    0.9x equity, so an ordinary adverse bar crosses it.  This is the test that stops `liquidation_touches`
    from being zero by construction.
    """
    returns = np.zeros((BARS, len(SYMBOLS)))
    returns[40, 0] = -0.15  # one leg of a gross-2.0 book -> a -15% book return
    panel = _panel(returns)
    weights = pd.DataFrame(1.0, index=panel.close.index, columns=SYMBOLS)
    result = run_backtest(
        panel,
        weights,
        CostModel(turnover_bps=0.0),
        guards=BookGuardParams(max_weight=1.0, max_gross=2.0),
        maintenance_margin_rate=0.45,
    )
    events = result.guard_events
    assert events is not None
    guards = result.summary()["guards"]
    assert guards["liquidation_touches"] >= 1, "a -15% bar against a 0.9x requirement must touch"
    assert guards["min_margin_buffer"] < 1.0
    touched = events["margin_buffer"] <= 1.0
    assert touched.any() and events.loc[touched, "margin_buffer"].min() == pytest.approx(0.85 / 0.9, rel=1e-6)


def test_a_flat_book_has_no_maintenance_requirement_and_so_infinite_buffer() -> None:
    panel = _panel(np.zeros((BARS, len(SYMBOLS))))
    weights = pd.DataFrame(0.0, index=panel.close.index, columns=SYMBOLS)
    result = run_backtest(panel, weights, CostModel(turnover_bps=0.0), guards=BookGuardParams())
    guards = result.summary()["guards"]
    assert guards["liquidation_touches"] == 0
    assert guards["min_margin_buffer"] == float("inf")


def test_the_participation_instrument_does_not_move_the_book() -> None:
    """M-017: it measures what live would refuse.  It must not change what the backtest scores.

    `max_participation` is out of scope as a *constraint* (config/live.demo.yaml:31-38: k must be
    re-derived under an impact-aware cost model, recorded as not done).  This is the measurement that
    says how urgent that is, so it is only honest if it leaves every published number where it was.
    """
    rng = np.random.default_rng(7)
    panel = _panel(rng.normal(0.0, 0.002, size=(BARS, len(SYMBOLS))), quote_volume=1_000.0)
    weights = pd.DataFrame(0.05, index=panel.close.index, columns=SYMBOLS)
    cost = CostModel(turnover_bps=7.0)
    off = run_backtest(panel, weights, cost, guards=BookGuardParams())
    on = run_backtest(
        panel,
        weights,
        cost,
        guards=BookGuardParams(),
        participation=ParticipationModel(capital=10_000.0, max_participation=0.02),
    )
    pd.testing.assert_frame_equal(off.weights, on.weights)
    pd.testing.assert_series_equal(off.portfolio_net, on.portfolio_net)
    assert off.summary()["guards"].get("participation_capped_bars") is None
    assert on.summary()["guards"]["participation_capped_bars"] >= 1


def test_the_refused_share_is_the_notional_live_would_have_truncated() -> None:
    """Constant weights, so the only order is the opening one: the arithmetic is checkable by hand."""
    panel = _panel(np.zeros((BARS, len(SYMBOLS))), quote_volume=1_000.0)
    weights = pd.DataFrame(0.05, index=panel.close.index, columns=SYMBOLS)
    result = run_backtest(
        panel,
        weights,
        CostModel(turnover_bps=0.0),
        guards=BookGuardParams(),
        # allowed = 0.02 x 1,000 = 20 per symbol; wanted = 0.05 x 10,000 = 500
        participation=ParticipationModel(capital=10_000.0, max_participation=0.02),
    )
    guards = result.summary()["guards"]
    assert guards["participation_capped_bars"] == 1
    assert guards["refused_turnover_share"] == pytest.approx((500.0 - 20.0) / 500.0)


def test_a_full_exit_is_never_refused_because_live_exempts_closes() -> None:
    """rebalancer.py:128 -- `closing` is target==0 while holding, and :154 exempts exactly that.

    Getting out is always executable; a partial adjustment is not.  The instrument has to reproduce
    that asymmetry or it would overstate what live refuses.
    """
    panel = _panel(np.zeros((BARS, len(SYMBOLS))), quote_volume=1_000.0)
    weights = pd.DataFrame(0.05, index=panel.close.index, columns=SYMBOLS)
    weights.iloc[120:] = 0.0
    result = run_backtest(
        panel,
        weights,
        CostModel(turnover_bps=0.0),
        guards=BookGuardParams(),
        participation=ParticipationModel(capital=10_000.0, max_participation=0.02),
    )
    events = result.guard_events
    assert events is not None
    exit_bar = events.index[events["desired_notional"] > 0][-1]
    assert events.loc[exit_bar, "desired_notional"] == pytest.approx(2 * 0.05 * 10_000.0)
    assert events.loc[exit_bar, "refused_notional"] == 0.0
    assert result.summary()["guards"]["participation_capped_bars"] == 1  # only the opening bar
