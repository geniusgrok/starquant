"""DL-X1: the loop can finally see how close it is to a liquidation - and when it cannot.

Report §4.2 Ⅴ listed "no liquidation observability at runtime" and L1-05 found ``INSURANCE_CLEAR``
and its neighbours being dropped on the floor by ``attribute``.  The A-P2 probe (2026-09-06, demo,
read-only) settled how to read the field, and the answer is the reason this file exists:

    liq == 0 for **14 of 14 longs**, non-zero for **4 of 4 shorts**

Under cross margin with a large equity, a long's liquidation price computes at or below zero and
Binance reports ``0``.  So ``0`` means *unreachable at this equity*, not *at liquidation* - and a
distance metric that reads it as a price would alarm on every long, forever.  That is the same shape
as E-37, where the 18-unit disaster stop was un-placeable on 7 of 18 symbols for the same reason.

The margin-mode assertion is KILL-R19's: the loop refuses to start against an account whose
``marginType``/``multiAssetsMargin`` differ from the ones its validation assumed, rather than
quietly trading a different risk model.  It asserts; it never sets.
"""

from __future__ import annotations

import pytest

from starquant_shared.types import Position


def _pos(symbol: str, qty: float, mark: float, liq: float | None) -> Position:
    return Position(symbol=symbol, qty=qty, entry_price=mark, mark_price=mark, liquidation_price=liq)


def test_a_long_with_no_reachable_liquidation_reports_no_distance() -> None:
    """The 14/14 case.  Not zero distance - no distance."""
    from starquant_live.liquidation import liquidation_distance

    assert liquidation_distance(_pos("BTCUSDT", 0.1, 80_000.0, None), daily_vol=0.03) is None


def test_a_zero_from_the_venue_is_read_as_unreachable_not_as_now() -> None:
    """The bug this test exists to prevent: an alarm on every long, every cycle, forever."""
    from starquant_live.liquidation import liquidation_distance

    assert liquidation_distance(_pos("BTCUSDT", 0.1, 80_000.0, 0.0), daily_vol=0.03) is None


def test_a_short_measures_the_distance_upward_in_daily_vol_units() -> None:
    """TRUMPUSDT on the probe: mark 2.308, liq 206.7 - 89x away, which is 'never' in vol units."""
    from starquant_live.liquidation import liquidation_distance

    distance = liquidation_distance(_pos("TRUMPUSDT", -51.85, 2.0, 2.6), daily_vol=0.10)

    assert distance == pytest.approx(3.0, rel=1e-3)  # 30% away at 10% daily vol


def test_a_long_measures_the_distance_downward() -> None:
    from starquant_live.liquidation import liquidation_distance

    distance = liquidation_distance(_pos("ETHUSDT", 1.0, 2_000.0, 1_800.0), daily_vol=0.05)

    assert distance == pytest.approx(2.0, rel=1e-3)


def test_zero_volatility_is_not_a_division() -> None:
    from starquant_live.liquidation import liquidation_distance

    assert liquidation_distance(_pos("X", 1.0, 100.0, 90.0), daily_vol=0.0) is None


def test_a_flat_symbol_has_no_liquidation_distance() -> None:
    from starquant_live.liquidation import liquidation_distance

    assert liquidation_distance(_pos("X", 0.0, 100.0, 90.0), daily_vol=0.05) is None


def test_the_minimum_ignores_the_unreachable_ones() -> None:
    """M-Q06 must read 'the closest position that HAS a liquidation price', or it reads 0 forever."""
    from starquant_live.liquidation import min_liquidation_distance

    positions = [
        _pos("BTCUSDT", 0.1, 80_000.0, None),  # long, unreachable
        _pos("TRUMPUSDT", -51.85, 2.0, 2.6),  # 3.0 units
        _pos("TUTUSDT", -100.0, 1.0, 1.5),  # 5.0 units
    ]

    result = min_liquidation_distance(positions, {"TRUMPUSDT": 0.10, "TUTUSDT": 0.10, "BTCUSDT": 0.03})

    assert result["min_distance"] == pytest.approx(3.0, rel=1e-3)
    assert result["symbol"] == "TRUMPUSDT"
    assert result["unreachable"] == 1
    assert result["measured"] == 2


def test_all_unreachable_is_reported_as_such_not_as_a_missing_metric() -> None:
    """'Every position is out of reach' is information; a null is a gap in the instrument."""
    from starquant_live.liquidation import min_liquidation_distance

    result = min_liquidation_distance([_pos("BTCUSDT", 0.1, 80_000.0, None)], {"BTCUSDT": 0.03})

    assert result["min_distance"] is None
    assert result["unreachable"] == 1
    assert result["measured"] == 0


def test_the_margin_mode_assertion_accepts_what_validation_assumed() -> None:
    from starquant_live.account_shape import margin_mode_problems

    assert margin_mode_problems(multi_assets=True, isolated_symbols=[], expect_multi_assets=True) == []


def test_an_isolated_position_is_refused() -> None:
    """§7.3(a): isolated margin manufactures liquidations the strategy never asked for."""
    from starquant_live.account_shape import margin_mode_problems

    problems = margin_mode_problems(multi_assets=True, isolated_symbols=["ETHUSDT"], expect_multi_assets=True)

    assert len(problems) == 1
    assert "ETHUSDT" in problems[0] and "CROSSED" in problems[0]


def test_a_changed_collateral_mode_is_refused() -> None:
    """Equity that floats with BTC is a different book from the one the evidence describes."""
    from starquant_live.account_shape import margin_mode_problems

    problems = margin_mode_problems(multi_assets=False, isolated_symbols=[], expect_multi_assets=True)

    assert len(problems) == 1
    assert "multiAssetsMargin" in problems[0]


def test_the_assertion_never_offers_to_fix_it() -> None:
    """Changing an account's margin mode under an open book is not a thing a startup check may do."""
    import inspect

    from starquant_live import account_shape

    source = inspect.getsource(account_shape.margin_mode_problems)
    assert "post" not in source.lower() and "set_margin" not in source
