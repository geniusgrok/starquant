"""`scale_orders_to_margin` charged a flip for margin it releases (2026-09-13 review).

A long-into-short order is not `reduce_only` - it ends on the other side - so the whole quantity,
`|current| + |target|`, counted towards `needed`.  The `|current|` half closes the standing position
and gives margin back.  `needed` was therefore too large, and an account that could fund the book got
its risk-adding orders shrunk pro-rata for nothing.

Fixed directly rather than behind a knob, because this function is a PRE-CHECK: its reason for
existing is "instead of letting the venue reject them one by one (-2019)".  Correcting an
over-estimate only makes the pre-check agree with the venue; it can never send more than
`plan_rebalance` already decided, and the venue's own margin check is still the backstop.  The
direction of the change is less shrinking, never more.
"""

from __future__ import annotations

from decimal import Decimal

from starquant_live.leverage import scale_orders_to_margin
from starquant_live.rebalancer import PlannedOrder, RebalanceParams, plan_rebalance
from starquant_shared.types import Position, Side
from tests.fakes.fake_venue import DEFAULT_RULES

PRICE = 60_000.0


def _flip(quantity: str, current: float, target: float) -> PlannedOrder:
    return PlannedOrder(
        symbol="BTCUSDT",
        side=Side.SELL if target < current else Side.BUY,
        quantity=Decimal(quantity),
        reduce_only=False,
        client_order_id="bd-1-BTCUSDT",
        target_weight=target / 10_000.0,
        current_notional=current,
        target_notional=target,
        price=PRICE,
    )


def test_only_the_opening_half_of_a_flip_counts_towards_the_budget() -> None:
    """Long 1,200 into short 600: 1,800 of notional, of which only 600 is new exposure."""
    order = _flip("0.030", current=1_200.0, target=-600.0)
    assert order.notional == 1_800.0

    # at 5x, the whole notional would ask for 360 of margin; the opening half asks for 120
    _kept, info = scale_orders_to_margin([order], 200.0, {"BTCUSDT": 5}, DEFAULT_RULES)

    assert info["needed_margin"] == 120.0
    assert info["scaled"] is False, "180 of budget covers the 120 the flip really needs"
    assert _kept == [order] and _kept[0].note == ""


def test_the_flip_is_still_shrunk_when_the_opening_half_alone_does_not_fit() -> None:
    """The trigger condition, kept live: a flip whose *target* side is bigger than the budget."""
    order = _flip("0.045", current=1_200.0, target=-1_500.0)
    assert order.notional == 2_700.0

    kept, info = scale_orders_to_margin([order], 200.0, {"BTCUSDT": 5}, DEFAULT_RULES)

    assert info["needed_margin"] == 300.0  # 1,500 / 5, not 2,700 / 5
    assert info["scaled"] is True and info["factor"] == 180.0 / 300.0
    assert kept and "MARGIN_SCALED" in kept[0].note


def test_a_plain_add_is_unchanged() -> None:
    """The half of the arithmetic that was already right, pinned so the flip case cannot eat it.

    An add's notional IS its new exposure, so subtracting `|current|` there would be the same defect
    pointed the other way.  0.016 at 60,000 is 960 of notional and 192 of margin at 5x.
    """
    add = PlannedOrder("BTCUSDT", Side.BUY, Decimal("0.016"), False, "bd-1-BTCUSDT", 0.15, 500.0, 1_460.0, PRICE)
    _kept, info = scale_orders_to_margin([add], 1_000.0, {"BTCUSDT": 5}, DEFAULT_RULES)
    assert info["needed_margin"] == 192.0

    entry = PlannedOrder("BTCUSDT", Side.BUY, Decimal("0.016"), False, "bd-1-BTCUSDT", 0.10, 0.0, 960.0, PRICE)
    _kept2, info2 = scale_orders_to_margin([entry], 1_000.0, {"BTCUSDT": 5}, DEFAULT_RULES)
    assert info2["needed_margin"] == 192.0


def test_a_truncated_flip_is_charged_for_what_it_actually_opens() -> None:
    """A flip cut by the participation cap may not even reach zero, and then it opens nothing.

    This is why the correction is `notional - |current|` rather than a flat `|target|`: the flat form
    would charge a 200 USDT clip for a 1,500 USDT target it cannot reach this bar, which would be a
    worse over-estimate than the one being fixed.
    """
    orders, _skipped = plan_rebalance(
        {"BTCUSDT": -0.15},
        managed_symbols=["BTCUSDT"],
        equity=10_000.0,
        positions={"BTCUSDT": Position("BTCUSDT", 0.020, PRICE, PRICE)},
        prices={"BTCUSDT": PRICE},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(max_participation=0.02),
        liquidity={"BTCUSDT": 10_000.0},
    )
    assert orders and orders[0].note == "PARTICIPATION_CAPPED"
    assert orders[0].notional <= 200.0 + 1e-9 and orders[0].current_notional == 1_200.0

    _kept, info = scale_orders_to_margin(orders, 1.0, {"BTCUSDT": 5}, DEFAULT_RULES)

    assert info["needed_margin"] == 0.0, "a clip smaller than the position it is closing opens nothing"
    assert info["scaled"] is False


def test_a_reduce_only_order_is_still_free() -> None:
    reduce = PlannedOrder("BTCUSDT", Side.SELL, Decimal("0.010"), True, "bd-1-BTCUSDT", 0.05, 1_200.0, 600.0, PRICE)
    kept, info = scale_orders_to_margin([reduce], 0.0, {"BTCUSDT": 5}, DEFAULT_RULES)
    assert kept == [reduce] and info["scaled"] is False and info["needed_margin"] == 0.0
