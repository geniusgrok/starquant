"""P1: `apply_exits` runs a vectorised engine, and it has to be `exit_step` to the last bit.

`exit_step` stays the single source of truth - the live loop calls it per symbol, which is D-012's
"the backtest loop and the live loop call the same exit_step" - so `_run_vectorised` is a SECOND
implementation of the same state machine and is only allowed to exist while this file holds it to
bit-for-bit equality with `_run_stepwise`, weights and events alike.

Bit for bit, not `approx`: the exits evidence is read with a paired ruler whose fold-level standard
error is 0.026-0.086, and a 1e-12 drift in a threshold comparison flips an exit, which moves a whole
segment of the path.  "The same modulo rounding" is a different overlay.

Two nets, because they catch different things.  The hypothesis net searches for the input that makes
the two disagree - prices INCLUDING NaN, targets including NaN and zero, and parameter sets that turn
on trailing, `unit_mode="current"` and `regime_window>0`.  The fixed-seed net is a handful of larger
panels, big enough that the cooldown and the re-entry actually get exercised many times over.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from starquant_alpha.overlays.exits import ExitParams, _apply_exits, _run_stepwise, _run_vectorised, apply_exits

# The four axes the two engines could plausibly disagree on, plus the shipped configuration itself.
PARAM_SETS = [
    ExitParams(stop_loss=6.0, take_profit=6.0),  # shipped
    ExitParams(stop_loss=2.0, trailing_stop=1.5, take_profit=3.0, cooldown_bars=5),
    ExitParams(trailing_stop=2.0, cooldown_bars=0),  # trailing alone, no cooldown
    ExitParams(stop_loss=2.0, take_profit=3.0, unit_mode="current"),
    ExitParams(stop_loss=2.0, take_profit=3.0, regime_window=6, regime_side="low"),
    ExitParams(stop_loss=2.0, take_profit=3.0, regime_window=6, regime_side="high", unit_mode="current"),
    ExitParams(take_profit=1.0, cooldown_bars=50),  # a cooldown longer than most of the panels below
    # The bounded carry, on both sides of its edge: give up on the first unjudgable bar, carry one,
    # carry far enough that the runs punched below never reach the bound.
    ExitParams(stop_loss=2.0, take_profit=3.0, stale_carry_bars=0),
    ExitParams(stop_loss=2.0, take_profit=3.0, stale_carry_bars=1),
    ExitParams(stop_loss=2.0, take_profit=3.0, stale_carry_bars=12),
    # EXP-AE3's branch, on both sides of its edge: armed from entry (the shipped 0.0, which must not
    # reach the comparison at all), armed only after a profit, and armed so far out that nothing in
    # the panels below ever reaches it.
    ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=1.5),
    ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=0.0),
    ExitParams(trailing_stop=1.0, trailing_activate=40.0, cooldown_bars=3),
    # EXP-SL1's branch, on both sides of its edge, the same shape as the three above.  The shipped 0.0
    # must not reach the arithmetic at all (every other row here carries it); 0.5 binds on the loud
    # bars these panels generate; 100.0 takes the branch and loses the `min` every time, which is the
    # case that would hide a reciprocal or a sign error from the other two.
    ExitParams(stop_loss=6.0, take_profit=6.0, stop_loss_price_cap=0.5),
    ExitParams(stop_loss=2.0, take_profit=3.0, stop_loss_price_cap=0.9, unit_mode="current"),
    ExitParams(stop_loss=6.0, take_profit=6.0, stop_loss_price_cap=100.0),
]


def _frames(prices: np.ndarray, targets: np.ndarray, symbols: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = [f"S{i}" for i in range(symbols)]
    index = pd.date_range("2024-01-01", periods=len(prices), freq="h", tz="UTC")
    close = pd.DataFrame(prices, index=index, columns=columns)
    weights = pd.DataFrame(targets, index=index, columns=columns)
    vol = pd.DataFrame(
        np.abs(np.diff(np.log(np.where(np.isnan(prices), 1.0, prices)), axis=0, prepend=0.0)) + 0.004,
        index=index,
        columns=columns,
    )
    return weights, close, vol


def _both(weights: pd.DataFrame, close: pd.DataFrame, vol: pd.DataFrame, params: ExitParams) -> None:
    slow = _apply_exits(weights, close, params, vol, _run_stepwise)
    fast = _apply_exits(weights, close, params, vol, _run_vectorised)
    # `assert_frame_equal` with check_exact stops at the first difference; the uint64 view is the
    # claim in full - every weight is the same 64 bits, NaN payloads included.
    assert np.array_equal(slow.weights.to_numpy().view(np.uint64), fast.weights.to_numpy().view(np.uint64)), (
        "the vectorised engine emitted a different weight"
    )
    pd.testing.assert_frame_equal(slow.events, fast.events, check_exact=True)


@st.composite
def _panel(draw: st.DrawFn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars = draw(st.integers(min_value=2, max_value=60))
    symbols = draw(st.integers(min_value=1, max_value=4))
    price = st.one_of(
        st.floats(min_value=0.5, max_value=5_000.0, allow_nan=False, allow_infinity=False),
        st.just(float("nan")),  # the gap bar, which is the branch the other net cannot reach on purpose
    )
    target = st.one_of(
        st.floats(min_value=-0.4, max_value=0.4, allow_nan=False, allow_infinity=False),
        st.just(0.0),
        st.just(float("nan")),
    )
    size = bars * symbols
    prices = np.array(draw(st.lists(price, min_size=size, max_size=size))).reshape(bars, symbols)
    targets = np.array(draw(st.lists(target, min_size=size, max_size=size))).reshape(bars, symbols)
    return _frames(prices, targets, symbols)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(panel=_panel(), params=st.sampled_from(PARAM_SETS))
def test_the_two_engines_agree_on_anything_hypothesis_can_build(
    panel: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], params: ExitParams
) -> None:
    weights, close, vol = panel
    _both(weights, close, vol, params)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("params", PARAM_SETS, ids=lambda p: f"sl{p.stop_loss}tr{p.trailing_stop}tp{p.take_profit}")
def test_the_two_engines_agree_on_a_panel_big_enough_to_cool_down_and_re_enter(seed: int, params: ExitParams) -> None:
    """400 bars x 12 symbols of random walk, 2% of the bars punched out, ~8% of the targets flat."""
    rng = np.random.default_rng(seed)
    bars, symbols = 400, 12
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, size=(bars, symbols)), axis=0))
    prices[rng.random((bars, symbols)) < 0.02] = np.nan
    targets = np.round(rng.normal(0.0, 0.1, size=(bars, symbols)), 4)
    targets[rng.random((bars, symbols)) < 0.08] = 0.0
    targets[: symbols // 2, 0] = np.nan  # a column that starts with nothing to say
    weights, close, vol = _frames(prices, targets, symbols)
    _both(weights, close, vol, params)


@pytest.mark.parametrize("params", PARAM_SETS, ids=lambda p: f"carry{p.stale_carry_bars}sl{p.stop_loss}")
def test_the_two_engines_agree_across_the_stale_carry_boundary(params: ExitParams) -> None:
    """Missing bars in RUNS of 1..6, so every panel straddles `stale_carry_bars` in both directions.

    Scattering NaNs independently mostly produces runs of one, which never reaches a bound above 0;
    the boundary is where the two engines have a counter to disagree about, so it gets its own panel.
    """
    rng = np.random.default_rng(97)
    bars, symbols = 500, 8
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, size=(bars, symbols)), axis=0))
    for j in range(symbols):
        start = int(rng.integers(0, 30))
        while start < bars:
            prices[start : start + int(rng.integers(1, 7)), j] = np.nan
            start += int(rng.integers(8, 40))
    targets = np.round(rng.normal(0.0, 0.1, size=(bars, symbols)), 4)
    weights, close, vol = _frames(prices, targets, symbols)
    runs = close.isna().sum().sum()
    assert runs > bars  # the panel really is full of holes
    _both(weights, close, vol, params)


def test_the_public_entry_point_runs_the_vectorised_engine_and_still_matches() -> None:
    """`apply_exits` is the one callers use, and it takes the fast path; prove it lands in the same place.

    This is also the only case where `sigma_1d` is left out, so `daily_vol` and `regime_tp_scale` are
    computed from `close` inside `_apply_exits` - the shared preparation both engines are handed.
    """
    rng = np.random.default_rng(11)
    bars, symbols = 300, 5
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.015, size=(bars, symbols)), axis=0))
    prices[rng.random((bars, symbols)) < 0.01] = np.nan
    targets = np.round(rng.normal(0.0, 0.1, size=(bars, symbols)), 4)
    weights, close, _ = _frames(prices, targets, symbols)
    params = ExitParams(stop_loss=2.0, trailing_stop=2.0, take_profit=3.0, regime_window=24)
    public = apply_exits(weights, close, params)
    reference = _apply_exits(weights, close, params, None, _run_stepwise)
    assert len(public.events) > 0  # the panel actually exercised the exits
    assert np.array_equal(public.weights.to_numpy().view(np.uint64), reference.weights.to_numpy().view(np.uint64))
    pd.testing.assert_frame_equal(public.events, reference.events, check_exact=True)
