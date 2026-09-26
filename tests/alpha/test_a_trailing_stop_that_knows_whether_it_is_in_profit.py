"""EXP-AE3: the activation threshold the operator's 「移动止盈」 needs, which this repository did not have.

`trailing_stop` measures the retracement from `extreme`, and `_enter` initialises `extreme` to the
ENTRY price.  So for a long, `extreme >= entry` on every bar and therefore `retrace >= adverse` on
every bar: today's trailing stop fires while the position is still LOSING, and it gets there before
`stop_loss` does.  That is the mechanism behind two things already written down - `config/live.demo.yaml`'s
"a future trailing experiment must take `k_tr > 6`", and the measurement that `sl0/tr4/tp0` and
`sl4/tr4/tp0` produce an identical 1.6132 over an identical 904 exits, i.e. `k_tr <= k_sl` turns
`stop_loss` into dead code.  It is why EXP-AE1's third cell (`trailing_stop` 2.0) was withdrawn on
2026-09-17 rather than run: it would have scored a book whose stop was silently off.

`trailing_activate` changes exactly one thing: the rule may not fire until the position has been that
far in profit.  The two tests that carry the whole argument are the pair below on an identical price
path - the same `sl 6 / tr 2` that today exits at -2 sigma exits at -6 sigma once armed at +1.5, which
is `stop_loss` doing its job again.

What it does NOT promise: a profitable exit.  Armed at +a and trailing by b > a still leaves below
entry, and the third test pins that so nobody reads the name as a guarantee.

Shipped at 0.0 - arm from entry, today's behaviour - and `docs/RESEARCH_LOG.md` 2026-09-08 recorded
this shape as "仍未实现、未测".  It is now implemented and still untested: EXP-AE3 is the evidence,
and it cannot run before 2026-10-13T19:00Z (the freeze, K-EX14).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.overlays.exits import ExitParams, apply_exits

#: One unit is exactly one price point: sigma 0.01 against an entry of 100.  The cooldown below is
#: longer than every path here on purpose: with 0 the machine correctly re-enters on the next bar and
#: exits again, which is right and says nothing about the rule under test.
ENTRY = 100.0
SIGMA = 0.01


def _run(prices: list[float], params: ExitParams) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(prices), freq="h", tz="UTC")
    close = pd.DataFrame({"S": prices}, index=index)
    weights = pd.DataFrame({"S": [0.1] * len(prices)}, index=index)
    vol = pd.DataFrame({"S": [SIGMA] * len(prices)}, index=index)
    return apply_exits(weights, close, params, sigma_1d=vol).events


#: Enters at 100 and never comes back: -2 sigma, then -6 sigma.  The two rules disagree about it.
STRAIGHT_DOWN = [ENTRY, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0]


def test_today_a_trailing_stop_fires_on_a_position_that_was_never_in_profit() -> None:
    """The defect, pinned rather than described: `k_tr <= k_sl` reaches the exit first, at a loss."""
    events = _run(STRAIGHT_DOWN, ExitParams(stop_loss=6.0, trailing_stop=2.0, cooldown_bars=99))
    assert list(events["rule"]) == ["TRAILING_STOP"]
    assert events["price"].iloc[0] == 98.0, "it fired two sigma down, four sigma before the stop"


def test_arming_it_hands_the_same_path_back_to_the_stop_loss() -> None:
    """Same prices, same thresholds, one field: the trailing rule cannot pre-empt a stop it never armed."""
    params = ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=1.5, cooldown_bars=99)
    events = _run(STRAIGHT_DOWN, params)
    assert list(events["rule"]) == ["STOP_LOSS"]
    assert events["price"].iloc[0] == 94.0, "six sigma, which is the distance the profile declares"


def test_once_it_has_been_in_profit_the_trail_is_live_again() -> None:
    """+2 sigma arms a 1.5 threshold; a 2 sigma retracement from the extreme then exits."""
    events = _run(
        [ENTRY, 101.0, 102.0, 101.0, 100.0, 99.0],
        ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=1.5, cooldown_bars=99),
    )
    assert list(events["rule"]) == ["TRAILING_STOP"]
    assert events["price"].iloc[0] == 100.0, "measured from the extreme (102), not from entry"


def test_being_armed_is_not_a_promise_that_the_exit_is_profitable() -> None:
    """Armed at +a and trailing by b > a exits below entry.  The name says nothing about the price."""
    events = _run(
        [ENTRY, 101.0, 100.0, 99.0, 98.0],
        ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=1.0, cooldown_bars=99),
    )
    assert list(events["rule"]) == ["TRAILING_STOP"]
    assert events["price"].iloc[0] == 99.0 < ENTRY


def test_the_shipped_value_reaches_no_new_branch_at_all() -> None:
    """0.0 must be bit-identical, and the guard that makes it so is a short circuit, not a comparison.

    A state whose `extreme` came back NaN from disk is the case the comparison would get wrong, so the
    property is asserted where it matters: the excursion is never read when the threshold is off.
    """
    assert ExitParams().trailing_activate == 0.0
    for prices in (STRAIGHT_DOWN, [ENTRY, 101.0, 102.0, 101.0, 100.0, 99.0]):
        default = _run(prices, ExitParams(stop_loss=6.0, trailing_stop=2.0, cooldown_bars=99))
        explicit = _run(prices, ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=0.0, cooldown_bars=99))
        pd.testing.assert_frame_equal(default, explicit, check_exact=True)


def test_a_short_arms_on_its_own_side() -> None:
    """The excursion is signed by the position, so 「in profit」 means down here and up above."""
    index = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
    close = pd.DataFrame({"S": [ENTRY, 99.0, 98.0, 99.0, 100.0, 101.0]}, index=index)
    weights = pd.DataFrame({"S": [-0.1] * 6}, index=index)
    vol = pd.DataFrame({"S": [SIGMA] * 6}, index=index)
    params = ExitParams(stop_loss=6.0, trailing_stop=2.0, trailing_activate=1.5, cooldown_bars=99)
    events = apply_exits(weights, close, params, sigma_1d=vol).events
    assert list(events["rule"]) == ["TRAILING_STOP"]
    assert events["price"].iloc[0] == 100.0, "armed at 98 (+2 for a short), exited two sigma back up"


def test_arming_a_rule_that_is_switched_off_is_refused() -> None:
    """`turnover_penalty`'s precedent: a value that is parsed, hashed and read by nothing looks adopted."""
    with pytest.raises(ValueError, match="trailing_activate arms"):
        ExitParams(stop_loss=6.0, trailing_stop=0.0, trailing_activate=2.0)
    with pytest.raises(ValueError, match="trailing_activate must be >= 0"):
        ExitParams(trailing_stop=2.0, trailing_activate=-1.0)


def test_the_live_profile_ships_it_off() -> None:
    """Turning it on is a construction change and belongs to the operator, after the freeze."""
    from starquant_shared.config import load_yaml

    exits = load_yaml("config/live.demo.yaml").get("exits", {})
    assert float(exits.get("trailing_activate", 0.0)) == 0.0
    assert np.isclose(float(exits.get("trailing_stop", 0.0)), 0.0), "the shipped book trails nothing yet"
