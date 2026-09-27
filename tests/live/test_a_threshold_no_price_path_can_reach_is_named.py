"""The `1/sigma` ceiling, on the rule KILL-TL04 did not cover, and the reading that surfaces it.

KILL-TL04 (2026-09-07) derived `retrace <= 1/sigma` for the trailing stop and measured the grid it
empties.  The same bound lands on `stop_loss` through the same price floor, and nothing in the tree
said so until 2026-09-17 - which is why the first live instance was found by an operator reading a
margin figure off a phone app rather than by anything that runs.

The first test pins the ARITHMETIC rather than the reading: a long whose sigma is 0.4517 has a
ceiling of 2.21 sigma, so the shipped `stop_loss` 6.0 cannot fire on it even when the price is driven
to essentially zero.  If that ever stops being true the reading below is measuring nothing, and a test
of the reading alone would still pass.
"""

from __future__ import annotations

import math
from pathlib import Path

from starquant_alpha.overlays.exits import STOP_LOSS, ExitParams, ExitState, exit_step
from starquant_live.reports import exit_reachability
from starquant_live.state import LiveState, StateStore

LSK_SIGMA = 0.4517  # LSKUSDT's entry sigma in `.starquant/live/state.json`, 2026-09-17
CEILING = 1.0 / LSK_SIGMA  # 2.2139...


def _walk_a_long_to_zero(stop_loss: float) -> str:
    """Hold a long from 1.0 and halve the close 200 times.  The rule that fires, if any.

    Geometric rather than linear on purpose: `1/sigma` is a SUPREMUM, not a maximum - `price > 0`
    always, so `adverse` approaches the ceiling without reaching it.  A linear march to 0.001 only gets
    to 2.2116 against a ceiling of 2.2139 and would let a threshold in that gap look unreachable when
    it merely had not been driven far enough.
    """
    params = ExitParams(stop_loss=stop_loss, trailing_stop=0.0, take_profit=0.0)
    state = ExitState(direction=1, entry_price=1.0, extreme=1.0, unit=LSK_SIGMA)
    price = 1.0
    for bar in range(1, 201):
        price /= 2.0
        state, _, reason = exit_step(state, 0.01, price, LSK_SIGMA, bar, params)
        if reason:
            return reason
    return ""


def test_a_long_stop_beyond_one_over_sigma_cannot_fire_however_far_the_price_falls() -> None:
    """`adverse = (entry - price) / (sigma * entry)` and `price >= 0`, so `adverse <= 1/sigma`."""
    assert CEILING < 6.0  # the premise: the shipped stop is beyond this symbol's ceiling
    # The whole entry price given up bar by bar, down to 2**-200, and the shipped stop never fires.
    assert _walk_a_long_to_zero(6.0) == ""
    # Not vacuous: the same walk on the same symbol DOES stop once the threshold is inside the ceiling.
    assert _walk_a_long_to_zero(2.0) == STOP_LOSS
    # And the ceiling is exactly where it is claimed to be, by the definition of a supremum: every
    # threshold strictly below it is reached, and every threshold strictly above it never is.
    assert _walk_a_long_to_zero(math.nextafter(CEILING, 0.0)) == STOP_LOSS
    assert _walk_a_long_to_zero(math.nextafter(CEILING, math.inf)) == ""


def test_the_daily_reading_names_the_position_whose_stop_is_arithmetic(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")
    store.save(
        LiveState(
            exit_states={
                # the live shape: one loud long past its ceiling, one quiet long well inside it
                "LSKUSDT": {"direction": 1, "entry_price": 0.30, "extreme": 0.30, "unit": LSK_SIGMA},
                "BTCUSDT": {"direction": 1, "entry_price": 60_000.0, "extreme": 60_000.0, "unit": 0.0156},
                "GONEUSDT": {"direction": 0, "entry_price": None, "extreme": None, "unit": None},  # flat: not checked
            }
        )
    )
    reading = exit_reachability(store, ExitParams(stop_loss=6.0, trailing_stop=0.0, take_profit=6.0))
    assert reading["checked"] == 2  # the flat symbol has no threshold to be unreachable
    assert [row["symbol"] for row in reading["unreachable"]] == ["LSKUSDT"]
    assert reading["unreachable"][0]["rule"] == STOP_LOSS
    assert reading["unreachable"][0]["ceiling"] == CEILING


def test_a_long_take_profit_is_left_out_because_it_has_no_ceiling_rather_than_a_clear_one(tmp_path: Path) -> None:
    """`favourable`'s numerator is unbounded above on a long, so silence about it is the honest output.

    Reporting it as reachable would say a measurement was taken.  The distinction matters because the
    mirror case - a SHORT's take-profit - does have the ceiling, and a reader has to be able to tell
    which of the two a missing row means.
    """
    store = StateStore(tmp_path / "live")
    store.save(exit_states := LiveState(exit_states={"LOUDUSDT": {"direction": 1, "entry_price": 1.0, "unit": 0.9}}))
    assert exit_states.exit_states["LOUDUSDT"]["unit"] == 0.9  # 1/sigma = 1.11, under every shipped k
    only_take_profit = exit_reachability(store, ExitParams(stop_loss=0.0, trailing_stop=0.0, take_profit=6.0))
    assert only_take_profit["checked"] == 0 and only_take_profit["unreachable"] == []
    # The same symbol held SHORT is the mirror, and it is reported.
    store.save(LiveState(exit_states={"LOUDUSDT": {"direction": -1, "entry_price": 1.0, "unit": 0.9}}))
    shorted = exit_reachability(store, ExitParams(stop_loss=0.0, trailing_stop=0.0, take_profit=6.0))
    assert [row["symbol"] for row in shorted["unreachable"]] == ["LOUDUSDT"]
