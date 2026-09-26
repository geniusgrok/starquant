"""DL-X1's other half: the three functions B1 wrote had no call site.

`tests/live/test_liquidation_observability.py` pins the *arithmetic* - what a distance means, what a
venue zero means, what the margin assertion refuses.  All of it passed while `min_liquidation_distance`
and `margin_mode_problems` were called by nothing at all, so `cycles.jsonl` carried no liquidation
field, startup asserted nothing, and a liquidation's own income row was dropped on the floor.  A tested
function with no caller is not an instrument; this file is the part that makes it one.

Four call sites, one test group each:

* the cycle record carries `min_liq_distance`, foreign positions included - cross margin liquidates the
  account, not the managed subset of it;
* startup refuses an account whose margin mode is not the one the evidence was produced on;
* `INSURANCE_CLEAR` reaches attribution instead of being silently skipped, which is the one income row
  that only ever appears when the thing this whole item is about has already happened;
* `force_orders()` asks the endpoint A-P2 confirmed (verified against demo-fapi 2026-09-07: it answers,
  `limit` caps at 100, and an account that has never been liquidated gets `[]`).
"""

from __future__ import annotations

import pytest

from starquant_live.attribution import INCOME_TYPES, summarize_income
from starquant_shared.types import Position

# --- the cycle row ------------------------------------------------------------------------------


def _position(symbol: str, qty: float, *, mark: float, liquidation: float | None) -> Position:
    return Position(
        symbol=symbol,
        qty=qty,
        entry_price=mark,
        mark_price=mark,
        unrealized_pnl=0.0,
        leverage=5,
        liquidation_price=liquidation,
    )


def test_the_cycle_record_carries_the_liquidation_view() -> None:
    from starquant_live.engine import liquidation_view

    view = liquidation_view(
        positions=[_position("BTCUSDT", 0.1, mark=60_000.0, liquidation=48_000.0)],
        daily_vol={"BTCUSDT": 0.02},
    )

    # 20% away at 2%/day is ten days of ordinary movement.
    assert view["min_distance"] == pytest.approx(10.0)
    assert view["symbol"] == "BTCUSDT"
    assert view["measured"] == 1
    assert view["unreachable"] == 0


def test_a_foreign_position_is_in_the_view_because_cross_margin_does_not_respect_our_universe() -> None:
    """The loop leaves foreign positions alone (D-014).  It does not get to ignore their liquidation."""
    from starquant_live.engine import liquidation_view

    view = liquidation_view(
        positions=[
            _position("BTCUSDT", 0.1, mark=60_000.0, liquidation=48_000.0),
            _position("DOGEUSDT", 1000.0, mark=0.10, liquidation=0.099),  # foreign, and much closer
        ],
        daily_vol={"BTCUSDT": 0.02, "DOGEUSDT": 0.05},
    )

    assert view["symbol"] == "DOGEUSDT"
    assert view["min_distance"] == pytest.approx(0.2)


def test_a_book_of_unreachable_longs_reports_the_count_not_a_missing_metric() -> None:
    """The live account's actual shape: 14 of 14 longs report liquidationPrice 0 (A-P2)."""
    from starquant_live.engine import liquidation_view

    view = liquidation_view(
        positions=[_position(f"S{i}USDT", 1.0, mark=100.0, liquidation=None) for i in range(14)],
        daily_vol={f"S{i}USDT": 0.03 for i in range(14)},
    )

    assert view["unreachable"] == 14
    assert view["measured"] == 0
    assert view["min_distance"] is None


def test_no_volatility_estimate_is_not_the_same_fact_as_no_liquidation_price() -> None:
    """`asset_vol` covers the universe; a foreign position has no entry in it.

    Both cases made `liquidation_distance` return None, so both were counted as ``unreachable`` - and
    the whole reason that field exists is that "the venue says this can never be liquidated" and "the
    instrument has nothing to say" must not look like one number.  The bug the field was invented to
    prevent, reintroduced one level up.
    """
    from starquant_live.engine import liquidation_view

    view = liquidation_view(
        positions=[
            _position("BTCUSDT", 0.1, mark=60_000.0, liquidation=None),  # venue: out of reach
            _position("PEPEUSDT", 1e6, mark=1e-5, liquidation=9e-6),  # foreign: reachable, no vol
        ],
        daily_vol={"BTCUSDT": 0.02},
    )

    assert view["unreachable"] == 1
    assert view["unmeasurable"] == 1
    assert view["measured"] == 0


def test_the_view_is_observability_and_cannot_stop_a_cycle() -> None:
    """Same contract as `asset_vol` and `_crowding_effect`: an instrument may not refuse to trade."""
    from starquant_live.engine import liquidation_view

    class Exploding:
        @property
        def qty(self) -> float:
            raise RuntimeError("boom")

    view = liquidation_view(positions=[Exploding()], daily_vol={})  # type: ignore[list-item]

    assert view["error"].startswith("RuntimeError")
    assert view["measured"] == 0


def test_daily_vol_comes_from_the_annualised_divisor_the_book_actually_sized_with() -> None:
    """`asset_vol` is annualised (portfolio.py); a distance in daily units has to divide it down."""
    from starquant_live.engine import daily_vol_from_annual

    # 365 calendar days: the same convention `starquant_alpha.portfolio.asset_vol` annualises with.
    assert daily_vol_from_annual({"BTCUSDT": 0.3819}) == pytest.approx({"BTCUSDT": 0.02}, rel=1e-3)


def test_a_floored_or_absent_annual_vol_yields_no_distance_rather_than_a_wrong_one() -> None:
    from starquant_live.engine import daily_vol_from_annual

    assert daily_vol_from_annual({"BTCUSDT": 0.0}) == {}
    assert daily_vol_from_annual({"BTCUSDT": float("nan")}) == {}


# --- the startup assertion ----------------------------------------------------------------------


def test_startup_refuses_an_isolated_symbol() -> None:
    """KILL-R19: the book is sized for CROSSED.  Refuse; never set."""
    from starquant_live.engine import margin_mode_refusal

    refusal = margin_mode_refusal(
        {"multi_assets": True, "isolated_symbols": ["BTCUSDT"]},
        expect_multi_assets=True,
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert refusal is not None
    assert "ISOLATED" in refusal
    assert "BTCUSDT" in refusal


def test_startup_refuses_a_changed_collateral_mode() -> None:
    from starquant_live.engine import margin_mode_refusal

    refusal = margin_mode_refusal(
        {"multi_assets": False, "isolated_symbols": []},
        expect_multi_assets=True,
        symbols=["BTCUSDT"],
    )

    assert refusal is not None
    assert "multiAssetsMargin" in refusal


def test_an_isolated_symbol_the_book_will_never_touch_does_not_stop_the_loop() -> None:
    """736 positionRisk rows come back; the book trades 18 of them.  Scope the refusal to those."""
    from starquant_live.engine import margin_mode_refusal

    refusal = margin_mode_refusal(
        {"multi_assets": True, "isolated_symbols": ["SOMECOINUSDT"]},
        expect_multi_assets=True,
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert refusal is None


def test_the_healthy_account_starts() -> None:
    from starquant_live.engine import margin_mode_refusal

    assert (
        margin_mode_refusal(
            {"multi_assets": True, "isolated_symbols": []},
            expect_multi_assets=True,
            symbols=["BTCUSDT"],
        )
        is None
    )


async def test_the_engine_refuses_to_start_when_the_venue_reports_isolated_margin() -> None:
    """The whole point: a refusal that is not wired into `startup()` refuses nothing."""
    from tests.live.helpers_liquidation import engine_with_margin_mode

    engine = engine_with_margin_mode({"multi_assets": True, "isolated_symbols": ["BTCUSDT"]})

    with pytest.raises(RuntimeError, match="ISOLATED"):
        await engine.startup()


async def test_a_venue_that_cannot_report_its_margin_mode_still_starts() -> None:
    """Same optional-probe shape as `hedge_mode`: paper and fake venues do not implement it."""
    from tests.live.helpers_liquidation import engine_with_margin_mode

    engine = engine_with_margin_mode(None)

    await engine.startup()  # must not raise


# --- INSURANCE_CLEAR ----------------------------------------------------------------------------


def test_insurance_clear_is_no_longer_dropped_on_the_floor() -> None:
    """T-X1-3.  It is the one row that exists only after a liquidation has already happened."""
    assert "INSURANCE_CLEAR" in INCOME_TYPES

    summary = summarize_income(
        [
            {"incomeType": "REALIZED_PNL", "symbol": "BTCUSDT", "income": "-100.0"},
            {"incomeType": "INSURANCE_CLEAR", "symbol": "BTCUSDT", "income": "-3.5"},
        ]
    )

    assert summary["BTCUSDT"]["INSURANCE_CLEAR"] == pytest.approx(-3.5)
    assert summary["BTCUSDT"]["total"] == pytest.approx(-103.5)


def test_insurance_clear_is_not_mistaken_for_an_external_flow() -> None:
    """It is a trading cost, not a deposit: it must not re-base the day's equity (E-044's path)."""
    from starquant_live.attribution import external_flows

    flows = external_flows([{"incomeType": "INSURANCE_CLEAR", "symbol": "BTCUSDT", "income": "-3.5"}])

    assert flows["rows"] == 0
    assert flows["total"] == 0.0


# --- force_orders -------------------------------------------------------------------------------


async def test_force_orders_asks_the_liquidation_endpoint_once() -> None:
    from tests.live.helpers_liquidation import recording_venue

    venue, seen = recording_venue(response=[])
    rows = await venue.force_orders(1_000, 2_000)

    assert rows == []
    assert len(seen) == 1
    path, params = seen[0]
    assert path == "/fapi/v1/forceOrders"
    assert params["startTime"] == 1_000
    assert params["endTime"] == 2_000
    # The venue caps this endpoint at 100 rows; asking for 1000 (what `_paged` does) is a 400.
    assert params["limit"] == 100


async def test_margin_mode_reads_the_boolean_not_the_spelling() -> None:
    """demo-fapi spells it lowercase `cross` (2026-09-07); `marginType == "CROSSED"` matches nothing."""
    from tests.live.helpers_liquidation import margin_mode_venue

    venue = margin_mode_venue(
        multi_assets=True,
        rows=[
            {"symbol": "BTCUSDT", "positionAmt": "0.1", "marginType": "cross", "isolated": False},
            {"symbol": "ETHUSDT", "positionAmt": "1.0", "marginType": "isolated", "isolated": True},
            {"symbol": "SOLUSDT", "positionAmt": "0", "marginType": "cross", "isolated": False},
            # Flat today, tradable tomorrow: margin mode is a per-symbol setting that outlives the
            # position, so a flat isolated symbol is a hazard the moment the book opens it.
            {"symbol": "XRPUSDT", "positionAmt": "0", "marginType": "isolated", "isolated": True},
        ],
    )

    mode = await venue.margin_mode()

    assert mode == {"multi_assets": True, "isolated_symbols": ["ETHUSDT", "XRPUSDT"]}


# --- M-Q06's failure action ---------------------------------------------------------------------


def test_a_book_far_from_liquidation_says_nothing() -> None:
    """Measured on the live account 2026-09-07: the nearest is TUTUSDT at 242 daily-vol units.

    24x the M-Q06 threshold, which is why wiring the alert cannot turn into an hourly noise source.
    """
    from starquant_live.engine import liquidation_alert

    assert liquidation_alert({"min_distance": 242.0, "symbol": "TUTUSDT", "measured": 4}, threshold=10.0) is None


def test_a_book_inside_the_threshold_says_so() -> None:
    from starquant_live.engine import liquidation_alert

    message = liquidation_alert({"min_distance": 4.5, "symbol": "TUTUSDT", "measured": 4}, threshold=10.0)

    assert message is not None
    assert "TUTUSDT" in message
    assert "4.5" in message


def test_every_position_being_out_of_reach_is_not_an_alarm() -> None:
    """The account's ordinary state: 14 of 18 report no reachable liquidation price at all."""
    from starquant_live.engine import liquidation_alert

    assert liquidation_alert({"min_distance": None, "symbol": None, "measured": 0}, threshold=10.0) is None


def test_the_instruments_own_failure_is_not_an_alarm_about_the_book() -> None:
    """`liquidation_view` records its own exception in the row; that is a bug report, not a margin call."""
    from starquant_live.engine import liquidation_alert

    assert liquidation_alert({"min_distance": None, "error": "RuntimeError: boom"}, threshold=10.0) is None


async def test_the_cycle_actually_sends_the_alert(august_panel: object, tmp_path: object) -> None:
    """The point of this whole file: a threshold nothing evaluates is a threshold nothing enforces."""
    from tests.live.helpers_liquidation import cycle_with_liquidation_price

    # 0.1% from the mark: inside the floor at any volatility this panel can produce.
    sent = await cycle_with_liquidation_price(august_panel, tmp_path, liquidation_fraction=0.001)

    assert any("最近的强平距离" in message for message in sent)


async def test_a_healthy_book_sends_nothing(august_panel: object, tmp_path: object) -> None:
    from tests.live.helpers_liquidation import cycle_with_liquidation_price

    # 98% away, which is what the live longs look like when they have a price at all.
    sent = await cycle_with_liquidation_price(august_panel, tmp_path, liquidation_fraction=0.98)

    assert not any("最近的强平距离" in message for message in sent)
