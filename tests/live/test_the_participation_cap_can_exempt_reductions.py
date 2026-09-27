"""T-S03's cap truncated reductions too, and its own comment said it did not (2026-09-13 review).

`RebalanceParams.max_participation` was documented as a cap "on a risk-adding order", but the exemption
in `plan_rebalance` was `not closing` - a full close only.  A 15% -> 5% pure reduction was truncated by
`max_participation x trailing volume`, which is the number that shrinks in exactly the bar where
getting smaller matters: the second pass of the review named this as one of three things that make the
exit channel contract with liquidity.

Widening it changes live fills and every backtest number, so it is `exempt_reductions`, default False,
and the default path has to stay bit-identical.  That is what the first test here pins.  The knob's
other half is `starquant_alpha.backtest.ParticipationModel.exempt_reductions`; the two must be flipped
together, and `tests/alpha/test_participation_exempt_reductions_tracks_live.py` is the test that holds
them to the same rule.
"""

from __future__ import annotations

from decimal import Decimal

from starquant_live.rebalancer import PlannedOrder, RebalanceParams, plan_rebalance
from starquant_shared.types import Position
from tests.fakes.fake_venue import DEFAULT_RULES

EQUITY = 10_000.0
PRICE = 60_000.0
# 2% of a 10,000 USDT hourly tape: any order above 200 USDT of notional is truncated
LIQUIDITY = {"BTCUSDT": 10_000.0}


def _plan(target: float, held_qty: float, *, exempt: bool) -> tuple[list[PlannedOrder], list[dict[str, object]]]:
    positions = {"BTCUSDT": Position("BTCUSDT", held_qty, PRICE, PRICE)} if held_qty else {}
    return plan_rebalance(
        {"BTCUSDT": target},
        managed_symbols=["BTCUSDT"],
        equity=EQUITY,
        positions=positions,
        prices={"BTCUSDT": PRICE},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(max_participation=0.02, exempt_reductions=exempt),
        liquidity=LIQUIDITY,
    )


def test_the_default_still_truncates_a_pure_reduction() -> None:
    """Today's behaviour, pinned: 15% -> 5% is a reduction and the cap cuts it to 200 USDT anyway."""
    orders, _skipped = _plan(0.05, 0.025, exempt=False)

    assert len(orders) == 1
    assert orders[0].reduce_only is True, "same side and smaller: the rebalancer already calls this reduce-only"
    assert orders[0].note == "PARTICIPATION_CAPPED"
    assert orders[0].quantity == Decimal("0.003")  # 200 / 60,000 down to the 0.001 step
    assert orders[0].notional <= 200.0 + 1e-9


def test_with_the_knob_on_the_same_reduction_goes_out_whole() -> None:
    orders, _skipped = _plan(0.05, 0.025, exempt=True)

    assert len(orders) == 1
    assert orders[0].note == ""
    assert orders[0].quantity == Decimal("0.016")  # the full 1,000 USDT delta, 0.0166.. down to the step
    assert orders[0].notional > 900.0


def test_a_full_close_is_exempt_either_way() -> None:
    """`closing` was always exempt; the knob must not disturb that half."""
    for exempt in (False, True):
        orders, _skipped = _plan(0.0, 0.025, exempt=exempt)
        assert len(orders) == 1 and orders[0].note == "", f"exempt_reductions={exempt}"
        assert orders[0].quantity == Decimal("0.025")


def test_a_risk_adding_order_is_still_capped_with_the_knob_on() -> None:
    """The whole point of the cap, which the knob must not touch: entering from flat is still clipped."""
    orders, _skipped = _plan(0.15, 0.0, exempt=True)

    assert len(orders) == 1 and orders[0].note == "PARTICIPATION_CAPPED"
    assert orders[0].notional <= 200.0 + 1e-9


def test_a_flip_is_still_capped_with_the_knob_on() -> None:
    """Long 15% into short 5% crosses zero, so it is not reduce_only: half of it opens new risk.

    This is the case that says why the knob is spelled `reduce_only` rather than "the order gets
    smaller": a flip does get the position smaller on the way through, and then keeps going.
    """
    orders, _skipped = _plan(-0.05, 0.025, exempt=True)

    assert len(orders) == 1
    assert orders[0].reduce_only is False
    assert orders[0].note == "PARTICIPATION_CAPPED"
    assert orders[0].notional <= 200.0 + 1e-9


def test_the_knob_changes_nothing_when_the_cap_is_off() -> None:
    """`max_participation = 0` disables the whole branch, and the knob must not resurrect it."""
    for exempt in (False, True):
        orders, _skipped = plan_rebalance(
            {"BTCUSDT": 0.05},
            managed_symbols=["BTCUSDT"],
            equity=EQUITY,
            positions={"BTCUSDT": Position("BTCUSDT", 0.025, PRICE, PRICE)},
            prices={"BTCUSDT": PRICE},
            rules=DEFAULT_RULES,
            bar_open_ms=0,
            params=RebalanceParams(max_participation=0.0, exempt_reductions=exempt),
            liquidity=LIQUIDITY,
        )
        assert len(orders) == 1 and orders[0].note == "", f"exempt_reductions={exempt}"
        assert orders[0].quantity == Decimal("0.016")


def test_the_default_is_off_because_flipping_it_is_the_operators_call() -> None:
    """K-EX14: a live behaviour change that moves backtest numbers ships as a knob, not as a fix."""
    assert RebalanceParams().exempt_reductions is False
