"""D-045: an exit the venue did not execute keeps saying flat instead of re-anchoring as a new entry.

`exit_step` drops the anchors when a rule fires, which is right in a backtest - weight 0 IS flat on
the next bar - and is not enough live, where the close can fail to land: `plan_rebalance` refuses one
inside the absolute band (`BAND_BLOCKS_EXIT`), below `minNotional`, or on a venue rejection.  The next
cycle used to see `direction` 0 against a held position and take the "direction changed" branch, which
rebuilds `unit` from the CURRENT bar's sigma.  That is not "k daily sigmas fixed at entry" (D-012), and
it misses in the dangerous direction: sigma rises, the stop widens, and the position that just failed
to close is the one whose stop just got looser.
"""

from __future__ import annotations

import pandas as pd

from starquant_alpha.overlays.exits import COOLDOWN, ExitParams, ExitState
from starquant_live.exits import ExitOverlay
from starquant_shared.types import Position

HOUR = 3_600_000
# A long entered at 100 and marked well below it, i.e. a position a 6-sigma stop has already fired on.
ENTRY, MARK = 100.0, 87.0


def _overlay() -> ExitOverlay:
    return ExitOverlay(ExitParams(stop_loss=6.0, take_profit=6.0, cooldown_bars=24), interval_ms=HOUR)


def _position() -> Position:
    return Position(symbol="BTCUSDT", qty=1.0, entry_price=ENTRY, mark_price=MARK)


def _calm_then_wild(sigma_target: float) -> pd.DataFrame:
    """Closes whose trailing EWMA daily vol lands near ``sigma_target`` - the re-anchor's input."""
    step = sigma_target / (24**0.5)
    closes = [ENTRY * (1 + step * (-1) ** i) for i in range(80)]
    return pd.DataFrame({"close": [*closes, MARK]})


def _fired_state(bar: int) -> dict[str, object]:
    """What `exit_step` leaves behind after a stop fires: anchors gone, cooldown naming the side."""
    fired = ExitState(direction=0, cooldown_until=bar + 24 * HOUR, cooldown_direction=1)
    assert fired.entry_price != fired.entry_price, "the fired state must carry no anchor"
    return fired.to_dict()


def test_a_position_that_failed_to_close_is_not_re_entered_inside_the_cooldown() -> None:
    overlay = _overlay()
    bar = 10 * HOUR
    adjusted, states, events = overlay.apply(
        {"BTCUSDT": 0.1},  # the model still wants the long; the overlay must keep overriding it
        positions={"BTCUSDT": _position()},
        bars={"BTCUSDT": _calm_then_wild(0.08)},
        states={"BTCUSDT": _fired_state(bar)},
        bar_open_ms=bar + HOUR,
    )

    assert adjusted == {"BTCUSDT": 0.0}, "the overlay must keep asking the rebalancer to close"
    assert [e["rule"] for e in events] == [COOLDOWN]
    assert states["BTCUSDT"]["direction"] == 0
    # No anchor was written, so nothing was re-entered and no `unit` was taken from this bar's sigma.
    assert states["BTCUSDT"]["entry_price"] is None and states["BTCUSDT"]["unit"] is None


def test_past_the_cooldown_a_position_still_standing_is_a_fresh_holding_decision() -> None:
    """The cap is bounded on purpose: after the window the overlay stops second-guessing the venue."""
    overlay = _overlay()
    bar = 10 * HOUR
    adjusted, states, _ = overlay.apply(
        {"BTCUSDT": 0.1},
        positions={"BTCUSDT": _position()},
        bars={"BTCUSDT": _calm_then_wild(0.08)},
        states={"BTCUSDT": _fired_state(bar)},
        bar_open_ms=bar + 25 * HOUR,  # one bar past `cooldown_until`
    )

    assert states["BTCUSDT"]["direction"] == 1
    assert states["BTCUSDT"]["entry_price"] == ENTRY  # the venue's own cost, never this bar's close
    assert adjusted["BTCUSDT"] != 0.0


def test_the_re_anchor_this_prevents_would_have_released_the_stop() -> None:
    """Why it matters, as an inequality rather than a story.

    Same position, same bar, two volatility regimes.  Re-anchoring takes ``unit`` from the bar it
    happens on, so the 6-sigma stop sits 6 * unit * entry away from a 100.0 entry: about 6 points when
    sigma reads 0.01 and about 48 when it reads 0.08.  The position is 13 points under water, so the
    quiet regime stops it and the loud one does not - and the loud one is where a close is most likely
    to have failed in the first place.
    """
    overlay = _overlay()
    bar = 10 * HOUR
    quiet = overlay._reconcile(ExitState(), _position(), MARK, 0.01, bar)
    loud = overlay._reconcile(ExitState(), _position(), MARK, 0.08, bar)

    adverse = ENTRY - MARK
    assert quiet.unit * ENTRY * 6.0 < adverse, "a quiet re-anchor still stops the position"
    assert loud.unit * ENTRY * 6.0 > adverse, "a loud re-anchor releases it - this is the bias"
    # Inside the cooldown neither happens: the fired decision stands and no anchor is written at all.
    held = overlay._reconcile(ExitState.from_dict(_fired_state(bar)), _position(), MARK, 0.08, bar + HOUR)
    assert held.direction == 0 and held.unit != held.unit
