"""The live twin of `tests/alpha/test_a_price_gap_neither_closes_the_position_nor_moves_the_anchor`.

`ExitOverlay.apply` already skipped a symbol whose frame was absent or too short, but `float(
frame["close"].iloc[-1])` could still hand `_reconcile` and `exit_step` a NaN - and `_reconcile` writes
the entry anchor, so a NaN close could overwrite a live position's entry reference with nan before
`exit_step` ever saw it.  The engine merges `new_states` into the stored map, so skipping the symbol is
what keeps the anchor: `{**self.state.exit_states, **exit_states}` leaves an untouched symbol alone.
"""

from __future__ import annotations

import math

import pandas as pd

from starquant_alpha.overlays.exits import ExitParams
from starquant_live.exits import ExitOverlay
from starquant_shared.types import Position


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _position(qty: float, entry: float) -> Position:
    return Position(symbol="BTCUSDT", qty=qty, entry_price=entry, mark_price=entry)


def test_a_nan_close_leaves_the_state_and_the_target_untouched() -> None:
    overlay = ExitOverlay(ExitParams(stop_loss=6.0, take_profit=6.0), interval_ms=3_600_000)
    stored = {"BTCUSDT": {"direction": 1, "entry_price": 100.0, "extreme": 100.0, "unit": 0.02}}
    adjusted, states, events = overlay.apply(
        {"BTCUSDT": 0.1},
        positions={"BTCUSDT": _position(1.0, 100.0)},
        bars={"BTCUSDT": _bars([100.0, 101.0, math.nan])},
        states=stored,
        bar_open_ms=0,
    )
    assert adjusted == {"BTCUSDT": 0.1}  # the overlay did not fire and did not resize
    assert states == {}  # nothing written, so the engine's merge keeps the 100.0 anchor
    assert events == []


def test_the_anchor_that_survived_the_gap_still_stops_on_the_next_priced_bar() -> None:
    """One k-unit is 2.0 points here, so 100 -> 87 is 6.5 units adverse and must stop."""
    overlay = ExitOverlay(ExitParams(stop_loss=6.0, take_profit=6.0), interval_ms=3_600_000)
    stored = {"BTCUSDT": {"direction": 1, "entry_price": 100.0, "extreme": 100.0, "unit": 0.02}}
    adjusted, states, events = overlay.apply(
        {"BTCUSDT": 0.1},
        positions={"BTCUSDT": _position(1.0, 100.0)},
        bars={"BTCUSDT": _bars([100.0, 101.0, 87.0])},
        states=stored,
        bar_open_ms=3_600_000,
    )
    assert adjusted == {"BTCUSDT": 0.0}
    assert len(events) == 1 and events[0]["rule"] == "STOP_LOSS" and events[0]["entry_price"] == 100.0
    assert states["BTCUSDT"]["direction"] == 0
