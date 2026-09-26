"""R8's first rung could not place an order, and neither half of the record said so (2026-09-14).

`Policy.drawdown_ladder`'s first rung takes `vol_target` 0.30 -> 0.225, which is a scalar of 0.75 on
every weight the cycle produces.  A position standing at its unthrottled target therefore needs an
order worth 0.25 x |current notional|, and `no_trade_rel_band` is 0.40 x |current notional|
(config/live.demo.yaml).  `plan_rebalance`'s relative band does not distinguish a resize that ADDS risk
from one that SHEDS it, so the de-escalation was swallowed whole: 0.25 < 0.40, every cycle, for as long
as the attributed drawdown stayed between the two rungs.  Only the second rung (0.15 / 0.30 = 0.50, a
half-sized book) cleared the band, so the two-rung ladder had one rung that could reach the venue.

0.30 is what the loop ran from R8's wiring (1112fe97, 2026-09-09) until the 0.60 restart on
2026-09-13T18:00Z - 96d659ae wrote 0.60 into the profile, 72034790 moved the cited evidence so the
startup gate would accept it, and the newest cycle carries construction 46b8d731530a.  At 0.60 the
rungs are 0.375 and 0.25 and both clear the band, so nothing is broken at the k running TODAY.  That is
a property of that k and not of the rule: 96d659ae rejected restating the rungs proportionally to the
wider budget (O-3) precisely because it put the first rung back at 0.75.  The tests below therefore pin
the RULE at a given scalar rather than any profile's k.

2026-09-14, after this fix landed: O-3 WAS adopted - the rungs are now ((-0.49, 0.45), (-0.70, 0.30))
against the -70% budget, so the first rung is back at 0.75 exactly as 96d659ae feared.  It is safe
because of the fix this file is about, which is the order the two changes had to happen in: the
exemption first, the rescale second.  Had they landed the other way round the ladder would have gone
back to having one reachable rung, and nothing in the record would have said so.

Both halves of the record read normal on their own.  `risk_ladder.acting` was true - the ladder DID
de-escalate, it produced a smaller target - and `skipped[]` carried an ordinary `NO_TRADE_BAND`, the
same row a quiet symbol writes on a quiet bar.  The two only contradict each other when read together,
which is the same shape as the defect the ladder itself closed: a thing that looks like a control and
controls nothing.

The fix leaves the band's ordinary semantics untouched and makes the exception the ladder's own state:
`plan_rebalance(..., deescalating=True)` drops the RELATIVE band for same-direction reductions only.
The absolute band stays, so the exemption cannot manufacture dust.  This is the narrow half of the
choice.  The wide half - a `RebalanceParams` knob shaped like `exempt_reductions` - would move every
ordinary cycle and every backtest number, because `no_trade_rel_band`'s other half is
`starquant_alpha.portfolio.apply_no_trade_band` and the two are one recursion (D-033).  The ladder has no
backtest half at all: `starquant_alpha` contains no `drawdown_ladder` and no `throttle_scalar`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_live.state import StateStore
from starquant_shared.types import Position, Side
from tests.fakes.fake_venue import DEFAULT_RULES, FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData

EQUITY = 100_000.0
PRICE = 50_000.0
BAND = 0.005  # config/live.demo.yaml: no_trade_band
REL_BAND = 0.40  # config/live.demo.yaml: no_trade_rel_band
# The two rungs as scalars.  Unchanged by the 2026-09-14 rescale: both the rungs and k doubled, so
# 0.225/0.30 and 0.45/0.60 are the same 0.75.  Spelled out rather than
# read from `Policy()` and the profile on purpose: this file is about what `plan_rebalance` does with a
# scalar, and the profile's own k moved to 0.60 while this was being written.
FIRST_RUNG_SCALAR = 0.75  # 0.225 / 0.30, and 0.45 / 0.60
SECOND_RUNG_SCALAR = 0.50  # 0.150 / 0.30
HELD_WEIGHT = 0.10  # 10,000 USDT of a 100,000 USDT book, so the relative band is 4,000 USDT


def _plan(
    target_weight: float,
    *,
    deescalating: bool = False,
    rel_band: float = REL_BAND,
) -> tuple[list, list[dict[str, object]]]:
    qty = HELD_WEIGHT * EQUITY / PRICE
    return plan_rebalance(
        {"BTCUSDT": target_weight},
        managed_symbols=["BTCUSDT"],
        equity=EQUITY,
        positions={"BTCUSDT": Position("BTCUSDT", qty, PRICE, PRICE)},
        prices={"BTCUSDT": PRICE},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=BAND, no_trade_rel_band=rel_band),
        deescalating=deescalating,
    )


def test_the_first_rung_reaches_the_venue_when_the_ladder_is_acting() -> None:
    """The defect, reproduced: 0.10 -> 0.075 is the whole of what the first rung asks for."""
    orders, skipped = _plan(HELD_WEIGHT * FIRST_RUNG_SCALAR, deescalating=True)

    assert len(orders) == 1, skipped
    assert orders[0].reduce_only is True
    assert orders[0].side is Side.SELL
    assert orders[0].target_notional == pytest.approx(7_500.0)
    # The whole 2,500 USDT cut, down to the 0.001 BTC lot step - one step is 50 USDT at this price,
    # and `quantize_qty` floors, so the range rather than a number nobody would recognise.
    assert 2_450.0 <= orders[0].notional <= 2_500.0


def test_without_the_ladder_the_same_reduction_is_still_held_by_the_band() -> None:
    """The control row: the band's ordinary semantics do not move, which is the point of this shape."""
    orders, skipped = _plan(HELD_WEIGHT * FIRST_RUNG_SCALAR)

    assert orders == []
    assert [row["reason"] for row in skipped] == ["NO_TRADE_BAND"]
    assert skipped[0]["threshold"] == pytest.approx(REL_BAND * HELD_WEIGHT * EQUITY)  # 4,000 > 2,500


def test_the_second_rung_always_cleared_the_band_which_is_why_this_stayed_invisible() -> None:
    """Half the book is a 50% cut, above the 40% band, so the deeper rung never needed the exemption."""
    for deescalating in (False, True):
        orders, skipped = _plan(HELD_WEIGHT * SECOND_RUNG_SCALAR, deescalating=deescalating)
        assert len(orders) == 1, f"deescalating={deescalating}: {skipped}"
        assert 4_950.0 <= orders[0].notional <= 5_000.0


def test_a_same_direction_increase_still_gets_the_relative_band() -> None:
    """The ladder only ever shrinks the book, so a target that GREW is ordinary rebalancing."""
    for deescalating in (False, True):
        orders, skipped = _plan(HELD_WEIGHT * 1.25, deescalating=deescalating)
        assert orders == [], f"deescalating={deescalating}"
        assert [row["reason"] for row in skipped] == ["NO_TRADE_BAND"]


def test_the_absolute_band_still_holds_so_the_exemption_cannot_make_dust() -> None:
    """0.5% of equity is 500 USDT; a 400 USDT reduction is dust whoever asked for it.

    The threshold in the skipped row is also how this test proves the relative band was dropped rather
    than merely cleared: 500, not 4,000.
    """
    orders, skipped = _plan(HELD_WEIGHT - 0.004, deescalating=True)

    assert orders == []
    assert [row["reason"] for row in skipped] == ["NO_TRADE_BAND"]
    assert skipped[0]["threshold"] == pytest.approx(BAND * EQUITY)


def test_the_exemption_does_nothing_when_the_relative_band_is_off() -> None:
    """`no_trade_rel_band = 0` is the default and most profiles' value; the flag must not resurrect it."""
    for deescalating in (False, True):
        orders, skipped = _plan(HELD_WEIGHT * FIRST_RUNG_SCALAR, deescalating=deescalating, rel_band=0.0)
        assert len(orders) == 1, f"deescalating={deescalating}: {skipped}"
        assert 2_450.0 <= orders[0].notional <= 2_500.0


SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )


def _world(panel: Panel, tmp_path: Path, cursor: int = 400) -> tuple[LiveEngine, FakeMarketData, FakeVenue]:
    market = FakeMarketData(panel, cursor)
    venue = FakeVenue(
        balance=10_000.0,
        prices={symbol: float(panel.close[symbol].iloc[cursor - 1]) for symbol in SYMBOLS},
    )
    config = LiveConfig(
        interval="1h",
        history_bars=300,
        universe=tuple(SYMBOLS),
        leverage=2,
        rebalance=RebalanceParams(no_trade_band=BAND, no_trade_rel_band=REL_BAND),
        guards=GuardParams(),
        kill_switch_path=tmp_path / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
        # `_risk_ladder` divides the rung by this, so it is what makes the first rung a 0.75 scalar
        # here as it is live.  Nothing else in the loop reads it (the model carries its own).
        # 0.60 since 2026-09-14: the rungs are absolute vol targets derived for that k, and
        # `_risk_ladder` now clamps a scalar above 1 rather than letting a ladder add size, so at
        # 0.30 the first rung (0.45) would read as "no cut" and this test would observe nothing.
        portfolio=PortfolioParams(vol_target=0.60),
    )
    engine = LiveEngine(
        config,
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    return engine, market, venue


async def _second_cycle(engine: LiveEngine, market: FakeMarketData, venue: FakeVenue, *, deescalated: bool) -> dict:
    """Open the book on one bar, then run the next bar with the ladder standing or clear.

    `deescalated` puts the loop in R8's acting state through R8's own inputs: an attribution row deep
    enough to sit between the two rungs, and a carried cycle count past the grace.  Faking the block
    itself would test nothing about the ladder.
    """
    await engine.startup()
    await engine.run_cycle(market.bar_open_ms(market.cursor - 1))
    if deescalated:
        rows = engine.store.read_jsonl(engine.store.cycles_path)
        bar = int(rows[-1]["bar_open_ms"])
        engine.store.append_attribution(
            {"bar_open_ms": bar, "until_ms": bar + 3_600_000, "total": -0.55 * float(rows[0]["equity"])}
        )
        engine.state.risk_ladder = {"cycles": 3, "rung": 0.45, "acting": True, "since_bar_ms": bar}
    market.cursor += 1
    for symbol in SYMBOLS:
        venue.set_price(symbol, float(market.panel.close[symbol].iloc[market.cursor - 1]))
    return await engine.run_cycle(market.bar_open_ms(market.cursor - 1))


async def test_the_loop_hands_the_ladders_own_state_to_the_rebalancer(august_panel: Panel, tmp_path: Path) -> None:
    """A keyword argument nothing passes is this defect again, one layer up.

    `Policy.throttle_scalar` sat unread for weeks because the rung was written down and never wired;
    an exemption the engine does not pass would be the same silence with an extra test to point at.
    """
    engine, market, venue = _world(august_panel, tmp_path)
    record = await _second_cycle(engine, market, venue, deescalated=True)

    assert record["risk_ladder"]["acting"] is True
    assert record["risk_ladder"]["scalar"] == pytest.approx(FIRST_RUNG_SCALAR)
    reductions = [order for order in record["orders"] if order.get("reduce_only")]
    assert reductions, f"the ladder acted and nothing left the loop: {record['skipped']}"


async def test_the_same_bar_without_a_standing_ladder_sends_no_reduction(august_panel: Panel, tmp_path: Path) -> None:
    """The paired control: the drift between two adjacent bars is inside the band, so nothing is due.

    Without it the test above would pass on any cycle that happened to want an order anyway.
    """
    engine, market, venue = _world(august_panel, tmp_path)
    record = await _second_cycle(engine, market, venue, deescalated=False)

    assert record["risk_ladder"]["acting"] is False
    assert [order for order in record["orders"] if order.get("reduce_only")] == []
