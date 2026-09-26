"""A bar whose close is missing must not re-anchor the entry, because that turns the stop off.

Found 2026-09-13.  `exit_step`'s guard was `held != 0 and not isnan(entry_price) and price > 0`, so a
NaN close failed `price > 0`, fell PAST the whole exit block, and reached `_enter` - which anchored a
brand-new `ExitState` at the NaN price.  The next priced bar then saw `isnan(entry_price)`, missed the
block again, and ran `_enter` a SECOND time, landing the anchor on the far side of the gap.  The stop
was silently off for the whole segment that followed.

The reproduction below is the one that was measured, with stop_loss = take_profit = 6, sigma_1d = 0.02
and an entry at 100, so one k-unit is 2.0 points.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from starquant_alpha.overlays.exits import STOP_LOSS, ExitParams, ExitState, apply_exits, exit_step

PARAMS = ExitParams(stop_loss=6.0, take_profit=6.0)


def _frames(path: list[float]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=len(path), freq="h", tz="UTC")
    return (
        pd.DataFrame({"A": 0.1}, index=index),
        pd.DataFrame({"A": path}, index=index),
        pd.DataFrame({"A": 0.02}, index=index),
    )


def test_a_nan_bar_does_not_move_the_entry_anchor() -> None:
    """100 -> 89 -> 87 is 6.5 adverse units and stops; inserting one NaN bar must not change that."""
    weights, close, vol = _frames([100.0, 100.0, 89.0, 87.0])
    clean = apply_exits(weights, close, PARAMS, sigma_1d=vol)
    assert clean.weights["A"].tolist() == [0.1, 0.1, 0.1, 0.0]
    assert len(clean.events) == 1 and clean.events.iloc[0]["rule"] == STOP_LOSS
    assert clean.events.iloc[0]["entry_price"] == 100.0

    weights, close, vol = _frames([100.0, 100.0, math.nan, 89.0, 87.0])
    gapped = apply_exits(weights, close, PARAMS, sigma_1d=vol)
    # Before the fix this read [0.1, 0.1, 0.1, 0.1, 0.1] with zero events: the NaN bar re-anchored to
    # nan, the 89 bar re-anchored to 89, and 100 -> 87 was measured as 89 -> 87, only 1.0 unit adverse.
    assert len(gapped.events) == 1 and gapped.events.iloc[0]["rule"] == STOP_LOSS
    assert gapped.events.iloc[0]["entry_price"] == 100.0  # the anchor survived the gap
    assert gapped.events.iloc[0]["units"] == clean.events.iloc[0]["units"]
    assert gapped.weights["A"].tolist() == [0.1, 0.1, 0.1, 0.1, 0.0]  # held through the gap, then flat


def test_the_gap_bar_holds_the_previous_weight_rather_than_trading() -> None:
    """`build_weights` fills a missing target with 0, so passing the target through would flatten and
    re-enter around every gap - turnover the backtest would pay for and the live loop never saw."""
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    close = pd.DataFrame({"A": [100.0, 101.0, math.nan, 102.0]}, index=index)
    vol = pd.DataFrame({"A": 0.02}, index=index)
    weights = pd.DataFrame({"A": [0.1, 0.1, 0.0, 0.1]}, index=index)  # the gap bar's target is 0
    result = apply_exits(weights, close, PARAMS, sigma_1d=vol)
    assert result.weights["A"].tolist() == [0.1, 0.1, 0.1, 0.1]
    assert len(result.events) == 0


def test_a_gap_while_flat_neither_enters_nor_burns_the_cooldown() -> None:
    """Out of a position the gap bar is still "no information": no entry at a NaN price, and the
    cooldown is not consumed, because a bar the overlay could not judge is not a bar it waited out."""
    state = ExitState()
    after, weight, reason = exit_step(state, 0.1, math.nan, 0.02, 0, PARAMS)
    assert after == state and math.isnan(weight) and reason == ""

    # Held, first unjudgable bar: everything but the counter is untouched, weight is "no decision".
    held, _, _ = exit_step(ExitState(), 0.1, 100.0, 0.02, 0, PARAMS)
    for bad in (math.nan, math.inf, -math.inf, 0.0, -5.0):
        same, weight, reason = exit_step(held, 0.1, bad, 0.02, 1, PARAMS)
        assert same == replace(held, stale_bars=1) and math.isnan(weight) and reason == ""


def test_the_carry_is_bounded_and_running_out_gives_up_without_re_entering() -> None:
    """`stale_carry_bars=2`: two missing bars are waited out, the third gives the position up.

    Bounded because the alternative is not: a bar with no price and a series that has ENDED are the
    same observation at the moment they happen, so an unbounded carry holds a delisted symbol to the
    end of the panel.  Same shape as `guards.stale_bars_max: 2` in the live profile - wait a fixed
    number of bars, then call it gone - and causal for the same reason: it only ever reads the past.
    """
    state, _, _ = exit_step(ExitState(), 0.1, 100.0, 0.02, 0, PARAMS)
    assert PARAMS.stale_carry_bars == 2
    for bar in (1, 2):
        state, weight, reason = exit_step(state, 0.0, math.nan, 0.02, bar, PARAMS)
        assert math.isnan(weight) and reason == "" and state.direction == 1
        assert state.entry_price == 100.0 and state.stale_bars == bar

    given_up, weight, reason = exit_step(state, 0.0, math.nan, 0.02, 3, PARAMS)
    assert weight == 0.0 and reason == ""  # a decision, not an abstention - and not an exit RULE
    assert given_up.direction == 0 and math.isnan(given_up.entry_price) and given_up.stale_bars == 0
    assert given_up.cooldown_until == state.cooldown_until  # running out of data is not an exit

    # Nothing re-anchors at the missing price: the next priced bar is a fresh entry at ITS price.
    reopened, weight, _ = exit_step(given_up, 0.1, 80.0, 0.02, 4, PARAMS)
    assert reopened.entry_price == 80.0 and weight == 0.1


def test_a_bar_with_a_price_ends_the_run_so_only_CONSECUTIVE_gaps_count() -> None:
    params = replace(PARAMS, stale_carry_bars=1)
    weights, close, vol = _frames([100.0, math.nan, 100.0, math.nan, 100.0, math.nan, 99.0])
    result = apply_exits(weights, close, params, sigma_1d=vol)
    assert result.weights["A"].tolist() == [0.1] * 7  # every run is length 1, so nothing is given up
    assert len(result.events) == 0


def test_a_gap_does_not_advance_the_trailing_extreme() -> None:
    """The trailing stop measures from the best close since entry; a bar with no close is not a close."""
    params = ExitParams(trailing_stop=2.0, cooldown_bars=100)
    state, _, _ = exit_step(ExitState(), 0.1, 100.0, 0.02, 0, params)
    state, _, _ = exit_step(state, 0.1, 110.0, 0.02, 1, params)
    assert state.extreme == 110.0
    state, _, _ = exit_step(state, 0.1, math.nan, 0.02, 2, params)
    assert state.extreme == 110.0  # not nan, and not reset to the gap price
    _, weight, reason = exit_step(state, 0.1, 105.5, 0.02, 3, params)
    assert reason == "TRAILING_STOP" and weight == 0.0  # 110 -> 105.5 is 2.25 units off the extreme


PROPERTY_PARAMS = ExitParams(stop_loss=3.0, trailing_stop=2.0, take_profit=4.0, cooldown_bars=0, stale_carry_bars=3)


@st.composite
def _scenario(draw: st.DrawFn) -> tuple[list[float], list[float], dict[int, int]]:
    size = draw(st.integers(min_value=24, max_value=80))
    steps = draw(st.lists(st.floats(-0.08, 0.08, allow_nan=False), min_size=size, max_size=size))
    signs = draw(st.lists(st.sampled_from((-1.0, 0.0, 1.0)), min_size=size, max_size=size))
    # Runs of at most `stale_carry_bars`, because that is the width of the claim: within the bound the
    # overlay waits and the anchor survives.  A longer run is the overlay deciding the symbol is gone,
    # which is a different sequence on purpose and has its own test above.
    cuts = draw(
        st.dictionaries(
            st.integers(min_value=1, max_value=size - 1),
            st.integers(min_value=1, max_value=PROPERTY_PARAMS.stale_carry_bars),
            max_size=6,
        )
    )
    path = [float(price) for price in 100.0 * np.exp(np.cumsum(steps))]
    return path, [0.1 * sign for sign in signs], cuts


def _with_gaps(
    path: list[float], targets: list[float], cuts: dict[int, int]
) -> tuple[list[float], list[float], list[int]]:
    """Insert `cuts[i]` missing bars before bar `i`; `marks[i]` is where clean bar `i` ended up."""
    prices: list[float] = []
    wanted: list[float] = []
    marks: list[int] = []
    for i, (price, target) in enumerate(zip(path, targets, strict=True)):
        for _ in range(cuts.get(i, 0)):
            prices.append(math.nan)
            wanted.append(0.0)  # what `build_weights` puts there
        marks.append(len(prices))
        prices.append(price)
        wanted.append(target)
    return prices, wanted, marks


def _run(prices: list[float], targets: list[float], params: ExitParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=len(prices), freq="h", tz="UTC")
    close = pd.DataFrame({"A": prices}, index=index)
    weights = pd.DataFrame({"A": targets}, index=index)
    vol = pd.DataFrame({"A": 0.02}, index=index)  # held fixed: the property is about the anchor, not
    result = apply_exits(weights, close, params, sigma_1d=vol)  # about how an EWMA crosses a gap
    return result.weights, result.events


@settings(max_examples=150, deadline=None)
@given(scenario=_scenario())
def test_inserting_missing_bars_anywhere_leaves_the_exit_sequence_alone(
    scenario: tuple[list[float], list[float], dict[int, int]],
) -> None:
    """The review's property, at the width the bounded carry gives it: the same price path with runs of
    up to `stale_carry_bars` missing bars inserted anywhere must exit the same.

    `cooldown_bars=0` on purpose.  A cooldown is counted in BARS, and an inserted bar is a bar, so a
    NaN landing inside a cooldown window lets the re-entry happen one priced bar sooner - a real and
    accepted consequence of the units the cooldown is written in, not the anchor bug this is about.
    """
    path, targets, cuts = scenario
    params = PROPERTY_PARAMS
    clean_weights, clean_events = _run(path, targets, params)
    prices, wanted, marks = _with_gaps(path, targets, cuts)
    gapped_weights, gapped_events = _run(prices, wanted, params)

    columns = ["symbol", "rule", "entry_price", "price", "units", "direction"]
    pd.testing.assert_frame_equal(clean_events[columns], gapped_events[columns])
    clean_at = [clean_weights.index.get_loc(t) for t in clean_events["time"]]
    gapped_at = [gapped_weights.index.get_loc(t) for t in gapped_events["time"]]
    assert gapped_at == [marks[i] for i in clean_at]  # same bars, only renumbered
    assert gapped_weights["A"].to_numpy()[marks].tolist() == clean_weights["A"].tolist()
