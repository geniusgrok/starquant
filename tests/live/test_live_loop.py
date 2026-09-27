"""T-L01..T-L07: the live loop against the fake venue and fake market data."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.attribution import attribute
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.execution import execute_order
from starquant_live.guards import GuardParams, evaluate_guards
from starquant_live.rebalancer import RebalanceParams, client_order_id, plan_rebalance
from starquant_live.state import StateStore
from starquant_shared.types import InstrumentRules, Position, Side, VenueError
from tests.fakes.fake_venue import DEFAULT_RULES, FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    entry = StrategyEntry("tsmom", params=params)
    return AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )


def _config(tmp_path: Path, **overrides: object) -> LiveConfig:
    base: dict[str, object] = {
        "interval": "1h",
        "history_bars": 300,
        "universe": tuple(SYMBOLS),
        "leverage": 2,
        "rebalance": RebalanceParams(no_trade_band=0.002),
        "guards": GuardParams(),
        "kill_switch_path": tmp_path / "KILL_SWITCH",
        "strategy_weights": {"tsmom": 1.0},
        "poll_interval_seconds": 0.0,
        "grace_seconds": 1.0,
    }
    base.update(overrides)
    return LiveConfig(**base)  # type: ignore[arg-type]


def _prices(panel: Panel, position: int) -> dict[str, float]:
    return {symbol: float(panel.close[symbol].iloc[position - 1]) for symbol in SYMBOLS}


@pytest.fixture
def world(august_panel: Panel, tmp_path: Path) -> dict:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(_config(tmp_path), model=_model(), market=market, venue=venue, clock=clock, store=store)
    return {
        "panel": august_panel,
        "market": market,
        "venue": venue,
        "clock": clock,
        "store": store,
        "engine": engine,
        "bar": market.bar_open_ms(cursor - 1),
    }


async def test_cycle_places_orders_and_is_idempotent_within_bar(world: dict) -> None:
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    record = await engine.run_cycle(world["bar"])
    assert not record["skip"]
    first_orders = len(venue.order_log)
    assert first_orders > 0
    assert all(order.client_order_id.startswith("bd-") for order in venue.order_log)
    positions = await venue.positions()
    assert positions
    # same bar again: nothing new hits the venue (T-L01)
    record2 = await engine.run_cycle(world["bar"])
    assert len(venue.order_log) == first_orders
    assert (
        all(
            o["status"] in {"SKIPPED_EXISTING", "FILLED"} or o["status"] == "SKIPPED_EXISTING"
            for o in record2["orders"]
        )
        or record2["orders"] == []
    )


async def test_restart_reconciles_and_does_not_double_open(world: dict, tmp_path: Path) -> None:
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    await engine.run_cycle(world["bar"])
    before = len(venue.order_log)
    positions_before = dict(venue.qty)
    # a fresh process with the same state directory and venue (T-L02)
    fresh = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=world["market"],
        venue=venue,
        clock=world["clock"],
        store=StateStore(tmp_path / "live"),
    )
    await fresh.startup()
    assert fresh.state.cycles == 1 and fresh.state.last_bar_ms == world["bar"]
    await fresh.run_cycle(world["bar"])
    assert len(venue.order_log) == before
    assert venue.qty == positions_before


async def test_unknown_outcome_is_recovered_by_query(world: dict) -> None:
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    venue.inject_unknown_outcome(1)
    record = await engine.run_cycle(world["bar"])
    statuses = [o["status"] for o in record["orders"]]
    assert "FILLED" in statuses and "UNKNOWN" not in statuses
    assert any(call.startswith("query_order:") for call in venue.calls)


async def test_rejection_is_recorded_and_loop_continues(world: dict) -> None:
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    venue.inject_error(VenueError("Margin is insufficient", code=-2019))
    record = await engine.run_cycle(world["bar"])
    assert any(o["status"] == "REJECTED" for o in record["orders"])
    assert engine.state.cycles == 1


async def test_market_failure_increments_errors_but_does_not_crash(world: dict) -> None:
    engine, market = world["engine"], world["market"]
    await engine.startup()
    market.fail_next = 1
    assert await engine.guarded_cycle(world["bar"]) is None
    assert engine.consecutive_errors == 1
    assert (await engine.guarded_cycle(world["bar"])) is not None
    assert engine.consecutive_errors == 0


async def test_stale_market_data_skips_cycle(world: dict) -> None:
    engine, market, venue = world["engine"], world["market"], world["venue"]
    await engine.startup()
    market.lag_bars = 5
    record = await engine.run_cycle(world["bar"])
    assert record["skip"] and "STALE_MARKET_DATA" in record["guard_reasons"]
    assert venue.order_log == []


async def test_kill_switch_only_allows_reductions(world: dict, tmp_path: Path) -> None:
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    await engine.run_cycle(world["bar"])
    (tmp_path / "KILL_SWITCH").write_text("x")
    market = world["market"]
    market.cursor += 1
    before = {s: abs(q) for s, q in venue.qty.items()}
    record = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))
    assert "KILL_SWITCH" in record["guard_reasons"]
    for order in venue.order_log[len(before) :]:
        assert order.reduce_only
    for symbol, size in venue.qty.items():
        assert abs(size) <= before.get(symbol, 0.0) + 1e-12


async def test_attribution_records_strategy_pnl(world: dict) -> None:
    engine, venue, market, store = world["engine"], world["venue"], world["market"], world["store"]
    await engine.startup()
    await engine.run_cycle(world["bar"])
    market.cursor += 1
    for symbol in SYMBOLS:
        venue.set_price(symbol, float(market.panel.close[symbol].iloc[market.cursor - 1]))
    await engine.run_cycle(market.bar_open_ms(market.cursor - 1))
    rows = store.read_jsonl(store.attribution_path)
    assert rows and "tsmom" in rows[-1]["by_strategy"]
    trades = store.read_jsonl(store.trades_path)
    assert all("client_order_id" in row and "target_weight" in row for row in trades)


def test_plan_rebalance_band_min_notional_and_reduce_only() -> None:
    rules = DEFAULT_RULES
    prices = {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 150.0, "BNBUSDT": 600.0}
    positions = {
        "ETHUSDT": Position("ETHUSDT", 1.0, 3_000.0, 3_000.0),
        "SOLUSDT": Position("SOLUSDT", -10.0, 150.0, 150.0),
    }
    targets = {"BTCUSDT": 0.10, "ETHUSDT": 0.15, "SOLUSDT": 0.0, "BNBUSDT": 0.0004}
    orders, _skipped = plan_rebalance(
        targets,
        managed_symbols=SYMBOLS,
        equity=10_000.0,
        positions=positions,
        prices=prices,
        rules=rules,
        bar_open_ms=1,
        params=RebalanceParams(no_trade_band=0.005),
    )
    by_symbol = {order.symbol: order for order in orders}
    assert (
        by_symbol["BTCUSDT"].side is Side.BUY
        and by_symbol["BTCUSDT"].quantity == Decimal("0.016")
        and not by_symbol["BTCUSDT"].reduce_only
    )
    assert (
        by_symbol["ETHUSDT"].side is Side.SELL
        and by_symbol["ETHUSDT"].reduce_only
        and by_symbol["ETHUSDT"].quantity == Decimal("0.5")
    )
    assert (
        by_symbol["SOLUSDT"].side is Side.BUY
        and by_symbol["SOLUSDT"].reduce_only
        and by_symbol["SOLUSDT"].quantity == Decimal("10")
    )
    assert "BNBUSDT" not in by_symbol  # 0.04% of equity is inside the band
    tiny = plan_rebalance(
        {"BTCUSDT": 0.001},
        managed_symbols=["BTCUSDT"],
        equity=10_000.0,
        positions={},
        prices=prices,
        rules=rules,
        bar_open_ms=1,
        params=RebalanceParams(no_trade_band=0.0),
    )
    assert tiny[0] == [] and tiny[1][0]["reason"] in {"MIN_NOTIONAL", "QUANTITY_ROUNDS_TO_ZERO"}
    assert client_order_id("bd", "BTCUSDT", 1_700_000_000_000) == "bd-1700000000000-BTCUSDT"


def test_guards_daily_loss_and_caps() -> None:
    decision = evaluate_guards(
        {"A": 0.5, "B": -0.5},
        current_weights={"A": 0.2, "B": 0.0},
        kill_switch=False,
        equity=9_000.0,
        day_start_equity=10_000.0,
        latest_bar_ms=100,
        expected_bar_ms=100,
        interval_ms=10,
        params=GuardParams(daily_loss_pause=-0.05, max_weight=0.15, max_gross=0.2),
    )
    assert not decision.allow_increase and "DAILY_LOSS_PAUSE" in decision.reasons
    assert decision.targets["A"] == pytest.approx(0.1) and decision.targets["B"] == 0.0


async def test_execute_order_skips_existing_and_reports_rejections() -> None:
    venue = FakeVenue()
    clock = FakeClock(0)
    orders, _ = plan_rebalance(
        {"BTCUSDT": 0.05},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=7,
        params=RebalanceParams(no_trade_band=0.0),
    )
    first = await execute_order(venue, orders[0], clock)
    assert first.status == "FILLED"
    again = await execute_order(venue, orders[0], clock)
    assert again.status == "FILLED" and "already submitted" in again.error
    venue.inject_error(VenueError("nope", code=-4164))
    orders2, _ = plan_rebalance(
        {"BTCUSDT": 0.10},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=8,
        params=RebalanceParams(no_trade_band=0.0),
    )
    rejected = await execute_order(venue, orders2[0], clock)
    assert rejected.status == "REJECTED" and "-4164" in rejected.error


def test_attribute_income_shares() -> None:
    rows = [
        {"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL", "income": "10"},
        {"symbol": "BTCUSDT", "incomeType": "COMMISSION", "income": "-1"},
        {"symbol": "ETHUSDT", "incomeType": "FUNDING_FEE", "income": "-0.5"},
    ]
    result = attribute(
        rows, {"a": {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, "b": {"BTCUSDT": 0.5, "ETHUSDT": 1.0}}, {"a": 1.0, "b": 1.0}
    )
    assert result["by_strategy"]["a"] == pytest.approx(4.5) and result["by_strategy"]["b"] == pytest.approx(4.0)
    assert result["total"] == pytest.approx(8.5)


def test_instrument_rules_tradable() -> None:
    assert InstrumentRules("X", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("5")).tradable
    assert not InstrumentRules("X", Decimal("1"), Decimal("1"), Decimal("1"), Decimal("5"), status="BREAK").tradable
    assert isinstance(pd.Timestamp.now(tz="UTC"), pd.Timestamp)


def test_rebalance_relative_band_only_for_same_direction_resizes() -> None:
    rules = DEFAULT_RULES
    prices = {"BTCUSDT": 60_000.0}
    positions = {"BTCUSDT": Position("BTCUSDT", 0.1, 60_000.0, 60_000.0)}  # 6,000 notional
    params = RebalanceParams(no_trade_band=0.0, no_trade_rel_band=0.25)
    small, _ = plan_rebalance(
        {"BTCUSDT": 0.07},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions=positions,
        prices=prices,
        rules=rules,
        bar_open_ms=1,
        params=params,
    )
    assert small == []  # 7,000 vs 6,000 is a 17% resize -> suppressed
    big, _ = plan_rebalance(
        {"BTCUSDT": 0.09},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions=positions,
        prices=prices,
        rules=rules,
        bar_open_ms=1,
        params=params,
    )
    assert big and big[0].side is Side.BUY
    flip, _ = plan_rebalance(
        {"BTCUSDT": -0.05},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions=positions,
        prices=prices,
        rules=rules,
        bar_open_ms=1,
        params=params,
    )
    assert flip and flip[0].side is Side.SELL and not flip[0].reduce_only


async def test_zero_avg_price_ack_is_requeried_for_the_settled_fill_price() -> None:
    """A MARKET ack with avgPrice=0 must not leave the trade log priceless."""
    venue = FakeVenue()
    clock = FakeClock(0)
    orders, _ = plan_rebalance(
        {"BTCUSDT": 0.05},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=11,
        params=RebalanceParams(no_trade_band=0.0),
    )
    real_place = venue.place_order

    async def place_without_price(request):  # type: ignore[no-untyped-def]
        ack = await real_place(request)
        stripped = replace(ack, avg_price=0.0)
        venue.orders[request.client_order_id] = ack  # the venue itself still knows the price
        return stripped

    venue.place_order = place_without_price  # type: ignore[assignment]
    report = await execute_order(venue, orders[0], clock)
    assert report.status == "FILLED"
    assert report.ack is not None and report.ack.avg_price == 60_000.0
    assert any(call.startswith("query_order:") for call in venue.calls)
