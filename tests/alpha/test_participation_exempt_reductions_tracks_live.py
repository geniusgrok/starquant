"""The backtest half of `exempt_reductions`, held to the live half's rule (2026-09-13 review).

`ParticipationModel` is an instrument for the live cap, so it is only honest while it replays the same
exemption `plan_rebalance` applies.  Both halves grew the knob at once for that reason, and the last
test here is the one that actually couples them: it asks the live rebalancer whether each (held,
target) pair is `reduce_only` and requires the replay to refuse exactly the pairs that are not.

The default path is asserted to be untouched, because flipping this changes every published number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, ParticipationModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.types import Position
from tests.fakes.fake_venue import DEFAULT_RULES

BARS = 48
SYMBOL = "BTCUSDT"
CAPITAL = 10_000.0
PRICE = 60_000.0
QUOTE_VOLUME = 1_000.0  # cap = 0.02 x 1,000 = 20 USDT per bar, far below any transition below
SWITCH = 24


def _flat_panel() -> Panel:
    """Zero returns, constant volume: equity stays 1.0, so the refused notional is checkable by hand."""
    index = pd.date_range("2024-01-01", periods=BARS, freq="1h", tz="UTC")
    close = pd.Series(PRICE, index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": QUOTE_VOLUME / PRICE,
            "quote_volume": QUOTE_VOLUME,
        },
        index=index,
    )
    return Panel.from_frames({SYMBOL: frame}, interval="1h")


def _refused_at_the_switch(held: float, target: float, *, exempt: bool) -> float:
    panel = _flat_panel()
    weights = pd.DataFrame(held, index=panel.close.index, columns=[SYMBOL])
    weights.iloc[SWITCH:] = target
    result = run_backtest(
        panel,
        weights,
        CostModel(turnover_bps=0.0),
        guards=BookGuardParams(),
        participation=ParticipationModel(capital=CAPITAL, max_participation=0.02, exempt_reductions=exempt),
    )
    events = result.guard_events
    assert events is not None
    # weights are decided at t and executed at t+1, and the replay drops the first execution bar
    switch_bar = events.index[events["desired_notional"] > 0][-1]
    assert events.loc[switch_bar, "desired_notional"] == pytest.approx(abs(target - held) * CAPITAL)
    return float(events.loc[switch_bar, "refused_notional"])


def _live_calls_it_reduce_only(held: float, target: float) -> bool:
    orders, _skipped = plan_rebalance(
        {SYMBOL: target},
        managed_symbols=[SYMBOL],
        equity=CAPITAL,
        positions={SYMBOL: Position(SYMBOL, held * CAPITAL / PRICE, PRICE, PRICE)} if held else {},
        prices={SYMBOL: PRICE},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(max_participation=0.0),
        liquidity=None,
    )
    assert len(orders) == 1, f"the fixture needs one order for held={held} target={target}"
    return orders[0].reduce_only


def test_the_default_still_refuses_a_pure_reduction() -> None:
    """Today's number, pinned: 0.12 -> 0.04 wants 800 USDT, the cap allows 20, 780 is refused."""
    assert _refused_at_the_switch(0.12, 0.04, exempt=False) == pytest.approx(800.0 - 20.0)


def test_with_the_knob_on_the_same_reduction_is_not_refused() -> None:
    assert _refused_at_the_switch(0.12, 0.04, exempt=True) == 0.0


def test_a_risk_adding_step_is_refused_with_the_knob_on() -> None:
    for exempt in (False, True):
        assert _refused_at_the_switch(0.04, 0.12, exempt=exempt) == pytest.approx(800.0 - 20.0)


def test_the_instrument_still_does_not_move_the_book_with_the_knob_on() -> None:
    """M-017's contract: `ParticipationModel` measures, it never changes what is scored."""
    panel = _flat_panel()
    rng = np.random.default_rng(11)
    weights = pd.DataFrame(rng.normal(0.0, 0.05, size=(BARS, 1)), index=panel.close.index, columns=[SYMBOL])
    cost = CostModel(turnover_bps=7.0)
    off = run_backtest(panel, weights, cost, guards=BookGuardParams())
    on = run_backtest(
        panel,
        weights,
        cost,
        guards=BookGuardParams(),
        participation=ParticipationModel(CAPITAL, 0.02, exempt_reductions=True),
    )
    pd.testing.assert_frame_equal(off.weights, on.weights)
    pd.testing.assert_series_equal(off.portfolio_net, on.portfolio_net)


def test_the_replays_exemption_is_the_rebalancers_reduce_only() -> None:
    """The coupling test.  Live decides, the replay has to agree - including on the flips.

    A flip gets the position smaller on the way through zero and then keeps going, so it is not
    `reduce_only` and the cap still binds it.  A replay that exempted "any step towards zero" would
    disagree with live here, and nothing else in either suite would notice.
    """
    pairs = [
        (0.12, 0.04),  # long, shrinking
        (0.04, 0.12),  # long, growing
        (0.12, 0.0),  # long, closed
        (0.0, 0.12),  # entered from flat
        (0.12, -0.04),  # flipped long -> short
        (-0.12, -0.04),  # short, shrinking
        (-0.04, -0.12),  # short, growing
        (-0.12, 0.0),  # short, closed
        (-0.12, 0.04),  # flipped short -> long
    ]
    for held, target in pairs:
        reduce_only = _live_calls_it_reduce_only(held, target)
        refused = _refused_at_the_switch(held, target, exempt=True)
        assert (refused == 0.0) is reduce_only, (
            f"held={held} target={target}: live reduce_only={reduce_only}, replay refused {refused}"
        )


def test_the_default_is_off_on_both_halves() -> None:
    assert ParticipationModel(CAPITAL, 0.02).exempt_reductions is False
    assert RebalanceParams().exempt_reductions is False
