"""T-X04, T-P03, T-P05, T-S01..T-S03: exits, pool refresh, leverage and sizing inside the live loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from starquant_alpha.overlays.exits import COOLDOWN, STOP_LOSS, ExitParams, ExitState
from starquant_alpha.panel import Panel
from starquant_data.pool import UniverseUpdate
from starquant_live.engine import LiveEngine
from starquant_live.exits import ExitOverlay
from starquant_live.leverage import derive_leverage, scale_orders_to_margin
from starquant_live.rebalancer import PlannedOrder, RebalanceParams, plan_rebalance
from starquant_live.reports import exit_and_pool_events
from starquant_live.state import StateStore
from starquant_shared.types import InstrumentRules, Position, Side, VenueError
from tests.fakes.fake_venue import DEFAULT_RULES, FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import SYMBOLS, _config, _model, _prices


class FakePool:
    def __init__(self, plan: list[list[str] | Exception]) -> None:
        self.plan = list(plan)
        self.calls: list[list[str]] = []

    async def select(self, previous: Sequence[str], rules: Mapping[str, InstrumentRules]) -> UniverseUpdate:
        self.calls.append(list(previous))
        step = self.plan.pop(0) if self.plan else list(previous)
        if isinstance(step, Exception):
            raise step
        before, after = set(previous), set(step)
        return UniverseUpdate(tuple(step), tuple(sorted(after - before)), tuple(sorted(before - after)), 1, {})


def _world(august_panel: Panel, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    pool = overrides.pop("pool", None)
    sink: list[Any] = []
    engine = LiveEngine(
        _config(tmp_path, **overrides),
        model=_model(),
        market=market,
        venue=venue,
        clock=clock,
        store=store,
        pool=pool,
        universe_sink=sink.append,
    )
    return {
        "market": market,
        "venue": venue,
        "clock": clock,
        "store": store,
        "engine": engine,
        "sink": sink,
        "cursor": cursor,
    }


# --- T-S01..T-S03 -------------------------------------------------------------------------------


def test_derive_leverage_from_gross_cap_and_brackets() -> None:
    assert derive_leverage(2.0, 0.4, 5) == 5
    assert derive_leverage(2.0, 0.4, 20) == 5
    assert derive_leverage(2.0, 0.4, 5, bracket_max=3) == 3
    assert derive_leverage(1.0, 0.5, 5) == 2
    assert derive_leverage(2.0, 1.0, 5) == 2
    assert derive_leverage(0.5, 0.9, 5) == 1
    with pytest.raises(ValueError):
        derive_leverage(0.0, 0.4, 5)


def _order(symbol: str, qty: str, price: float, reduce_only: bool = False) -> PlannedOrder:
    return PlannedOrder(symbol, Side.BUY, Decimal(qty), reduce_only, f"bd-1-{symbol}", 0.1, 0.0, 100.0, price)


def test_margin_scaling_shrinks_only_risk_adding_orders() -> None:
    """T-S02: two ~1,000 USDT adds at 5x need ~392 of margin; 300 available x 0.9 buffer -> factor ~0.689."""
    orders = [
        _order("ETHUSDT", "0.333", 3_000.0),
        _order("BTCUSDT", "0.016", 60_000.0),
        _order("SOLUSDT", "10", 150.0, reduce_only=True),
    ]
    kept, info = scale_orders_to_margin(orders, 300.0, {"ETHUSDT": 5, "BTCUSDT": 5}, DEFAULT_RULES, buffer=0.10)
    assert info["scaled"] and abs(info["factor"] - 270.0 / (999.0 / 5 + 960.0 / 5)) < 1e-9
    by_symbol = {order.symbol: order for order in kept}
    assert by_symbol["SOLUSDT"].quantity == Decimal("10") and by_symbol["SOLUSDT"].note == ""
    assert by_symbol["ETHUSDT"].quantity < Decimal("0.333") and "MARGIN_SCALED" in by_symbol["ETHUSDT"].note
    assert by_symbol["BTCUSDT"].quantity == Decimal("0.011")  # 0.016 * 0.689 rounds down to the 0.001 step
    untouched, info2 = scale_orders_to_margin(orders, 10_000.0, {}, DEFAULT_RULES)
    assert untouched == orders and not info2["scaled"]
    tiny, info3 = scale_orders_to_margin([_order("BTCUSDT", "0.002", 60_000.0)], 20.0, {"BTCUSDT": 5}, DEFAULT_RULES)
    assert tiny == [] and info3["dropped"][0]["reason"] == "MARGIN_SCALED_BELOW_MIN"


def test_participation_cap_limits_risk_adding_orders() -> None:
    """T-S03: with 2% of a 10,000 USDT hourly tape a 1,500 USDT target is cut to 200 USDT."""
    orders, _skipped = plan_rebalance(
        {"BTCUSDT": 0.15},
        managed_symbols=["BTCUSDT"],
        equity=10_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(max_participation=0.02),
        liquidity={"BTCUSDT": 10_000.0},
    )
    assert orders and orders[0].note == "PARTICIPATION_CAPPED" and orders[0].notional <= 200.0 + 1e-9
    orders2, _ = plan_rebalance(
        {"BTCUSDT": 0.15},
        managed_symbols=["BTCUSDT"],
        equity=10_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=0,
        params=RebalanceParams(max_participation=0.02),
        liquidity={"BTCUSDT": 1_000_000.0},
    )
    assert orders2[0].note == "" and orders2[0].notional > 1_400.0


def test_a_capped_order_is_finished_over_the_following_bars() -> None:
    """Block 4 #42 (VWAP), 2026-09-09: the loop already IS a rate-limited multi-bar schedule.

    This is why #42 was refused for capacity as well as for cost.  `plan_rebalance` re-derives
    ``delta`` every bar from the venue's *actual* position, so a truncated order is not a lost order -
    the residual is simply the next bar's delta, and the participation cap turns one oversized target
    into a stream of cap-sized clips without an execution layer, a child-order state machine, or a
    partial-fill protocol.  Asserted here because nothing did: the sibling test above proves one order
    gets cut and stops there, which is consistent with the residual being dropped on the floor.

    It also pins where the convergence actually stops, which is the honest limit of the free version:
    not at the target but at the first clip the min-notional rule refuses, 1,440 of a 1,500 target
    here.  A real VWAP would not fix that either - it is the instrument's floor, not the schedule's.
    """
    held = 0.0
    clips: list[float] = []
    for bar in range(20):
        position = {"BTCUSDT": Position("BTCUSDT", held, 60_000.0, 60_000.0)} if held else {}
        orders, skipped = plan_rebalance(
            {"BTCUSDT": 0.15},
            managed_symbols=["BTCUSDT"],
            equity=10_000.0,
            positions=position,
            prices={"BTCUSDT": 60_000.0},
            rules=DEFAULT_RULES,
            bar_open_ms=bar,
            params=RebalanceParams(max_participation=0.02),
            liquidity={"BTCUSDT": 10_000.0},
        )
        if not orders:
            assert skipped and skipped[0]["reason"] == "MIN_NOTIONAL"
            break
        assert orders[0].note == "PARTICIPATION_CAPPED" and orders[0].notional <= 200.0 + 1e-9
        clips.append(orders[0].notional)
        held += float(orders[0].quantity)
    else:  # pragma: no cover - only reached if the residual never converges
        raise AssertionError("a capped target never finished: the schedule does not terminate")

    assert len(clips) == 8, f"expected the 1,500 target to be walked in cap-sized clips, got {clips}"
    assert 1_400.0 < held * 60_000.0 < 1_500.0


# --- T-X04 ----------------------------------------------------------------------------------------


def test_live_exit_overlay_adopts_venue_entry_and_drops_stale_state() -> None:
    """T-X04: after a restart the venue's entry price is the reference; a phantom held state is reset."""
    overlay = ExitOverlay(ExitParams(stop_loss=1.0, cooldown_bars=2, vol_halflife=48), interval_ms=3_600_000)
    # +-1% alternation (about 4.9% daily vol) for 60 bars, then a 10% gap: 10 / (~7.6 unit) > 1 sigma_1d
    closes = [100.0 * (1.01 if i % 2 else 1.0) for i in range(60)] + [90.0]
    frame = pd.DataFrame({"close": closes, "volume": 1.0})
    position = Position("BTCUSDT", qty=1.0, entry_price=100.0, mark_price=90.0)
    adjusted, states, events = overlay.apply(
        {"BTCUSDT": 0.1}, positions={"BTCUSDT": position}, bars={"BTCUSDT": frame}, states={}, bar_open_ms=10
    )
    assert adjusted["BTCUSDT"] == 0.0 and events[0]["rule"] == STOP_LOSS and events[0]["entry_price"] == 100.0
    assert states["BTCUSDT"]["cooldown_until"] == 10 + 2 * 3_600_000
    phantom = ExitState(direction=1, entry_price=50.0, extreme=50.0, unit=0.02).to_dict()
    adjusted2, states2, events2 = overlay.apply(
        {"BTCUSDT": 0.1}, positions={}, bars={"BTCUSDT": frame}, states={"BTCUSDT": phantom}, bar_open_ms=20
    )
    assert adjusted2["BTCUSDT"] == 0.1 and not events2 and states2["BTCUSDT"]["entry_price"] == 90.0


# --- engine integration: exits, pool refresh, leverage --------------------------------------------


async def test_engine_stops_out_and_respects_cooldown(august_panel: Panel, tmp_path: Path) -> None:
    world = _world(august_panel, tmp_path, exits=ExitParams(stop_loss=0.5, cooldown_bars=3, vol_halflife=24))
    engine, venue, market = world["engine"], world["venue"], world["market"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    first = await engine.run_cycle(bar)
    longs = [s for s, w in first["targets"].items() if w > 0 and venue.qty.get(s, 0.0) > 0]
    assert longs, "the august panel should open at least one long"
    victim = longs[0]
    crafted = {}
    for field in ("open", "high", "low", "close", "volume"):
        frame = getattr(august_panel, field).copy()
        if field != "volume":
            frame.loc[frame.index[world["cursor"]], victim] *= 0.7  # one 30% flash-crash bar after the entry
        crafted[field] = frame
    market.panel = Panel(interval="1h", **crafted)
    market.cursor += 1
    second = await engine.run_cycle(bar + 3_600_000)
    events = {event["symbol"]: event["rule"] for event in second["exit_events"]}
    assert events.get(victim) == STOP_LOSS and second["targets"][victim] == 0.0
    closing = [o for o in second["orders"] if o["symbol"] == victim]
    assert closing and closing[0]["reduce_only"] and closing[0]["status"] == "FILLED"
    assert venue.qty.get(victim, 0.0) == 0.0
    market.cursor += 1
    third = await engine.run_cycle(bar + 2 * 3_600_000)
    assert {e["symbol"]: e["rule"] for e in third["exit_events"]}.get(victim) == COOLDOWN
    assert third["targets"][victim] == 0.0 and venue.qty.get(victim, 0.0) == 0.0
    assert engine.state.exit_states[victim]["cooldown_direction"] == 1


async def test_engine_refreshes_universe_daily_and_flattens_what_leaves(august_panel: Panel, tmp_path: Path) -> None:
    """T-P03/T-P05: a symbol that leaves the pool is flattened; a failing refresh keeps the previous pool."""
    pool = FakePool([list(SYMBOLS), [s for s in SYMBOLS if s != "SOLUSDT"], RuntimeError("mainnet down")])
    world = _world(august_panel, tmp_path, pool=pool, universe_refresh=True, leverage_mode="auto", margin_cap=0.4)
    engine, venue, market = world["engine"], world["venue"], world["market"]
    await engine.startup()
    assert all(venue.leverage[s] == derive_leverage(2.0, 0.4, 5) for s in SYMBOLS)  # T-S01 applied at startup
    bar = market.bar_open_ms(world["cursor"] - 1)
    first = await engine.run_cycle(bar)
    assert first["universe_update"]["entered"] == [] and pool.calls[0] == list(SYMBOLS)
    if venue.qty.get("SOLUSDT", 0.0) == 0.0:  # make sure SOL holds something to flatten
        venue.qty["SOLUSDT"], venue.entry["SOLUSDT"] = 5.0, venue.prices["SOLUSDT"]
    next_day = bar + 24 * 3_600_000
    market.cursor += 24
    second = await engine.run_cycle(next_day)
    assert second["universe_update"]["left"] == ["SOLUSDT"] and "SOLUSDT" not in engine.universe
    assert "SOLUSDT" in second["leaving"] and second["targets"]["SOLUSDT"] == 0.0
    sol_orders = [o for o in second["orders"] if o["symbol"] == "SOLUSDT"]
    assert sol_orders and sol_orders[0]["reduce_only"] and venue.qty.get("SOLUSDT", 0.0) == 0.0
    assert world["sink"] and list(world["sink"][-1].symbols) == [s for s in SYMBOLS if s != "SOLUSDT"]
    assert engine.state.universe == [s for s in SYMBOLS if s != "SOLUSDT"]
    market.cursor += 24
    third = await engine.run_cycle(next_day + 24 * 3_600_000)
    assert "error" in third["universe_update"] and engine.universe == [s for s in SYMBOLS if s != "SOLUSDT"]
    assert "SOLUSDT" not in third["leaving"]  # flat now, so it is no longer managed
    # a restart picks the persisted universe up again
    fresh = LiveEngine(
        replace(engine.config),
        model=_model(),
        market=market,
        venue=venue,
        clock=world["clock"],
        store=StateStore(tmp_path / "live"),
        pool=FakePool([]),
    )
    assert fresh.universe == [s for s in SYMBOLS if s != "SOLUSDT"]


async def test_a_symbol_the_venue_keeps_rejecting_is_quarantined(august_panel: Panel, tmp_path: Path) -> None:
    """D-031: rejected on N consecutive cycles and the symbol leaves the pool; a venue-wide refusal does not."""
    world = _world(august_panel, tmp_path, quarantine_after=3, universe_refresh=True, pool=FakePool([]))
    engine, venue, market = world["engine"], world["venue"], world["market"]
    await engine.startup()
    accepted = venue.place_order
    refused: set[str] = set()

    async def refuse(request: Any) -> Any:
        if request.symbol in refused:
            raise VenueError("Order's notional must be no smaller than minNotional", code=-4164)
        return await accepted(request)

    venue.place_order = refuse  # type: ignore[method-assign]

    # Every symbol refused: an account-wide condition the guards own, so no streak is built at all.
    refused.update(SYMBOLS)
    bar = market.bar_open_ms(world["cursor"] - 1)
    record = await engine.run_cycle(bar)
    assert [o["status"] for o in record["orders"]] == ["REJECTED"] * len(record["orders"]) and record["orders"]
    assert record["quarantined"] == [] and engine.state.reject_streak == {}

    # Only SOL refused, and the venue demonstrably works for the others: three cycles and it is out.
    refused.clear()
    refused.add("SOLUSDT")
    for step in range(1, 4):
        market.cursor += 1
        record = await engine.run_cycle(bar + step * 3_600_000)
        assert [o["symbol"] for o in record["orders"] if o["status"] == "REJECTED"] == ["SOLUSDT"]
    assert record["quarantined"] == ["SOLUSDT"]
    assert "SOLUSDT" not in engine.universe and engine.state.universe == engine.universe
    assert "SOLUSDT" in engine.state.leaving and engine.state.reject_streak == {}

    # It is exit-only now: the target is zero and the order is reduce-only, whatever the signal wants.
    market.cursor += 1
    after = await engine.run_cycle(bar + 4 * 3_600_000)
    assert after["targets"]["SOLUSDT"] == 0.0
    assert all(o["reduce_only"] for o in after["orders"] if o["symbol"] == "SOLUSDT")
    assert exit_and_pool_events(world["store"], str(after["bar"])[:10])["pool_quarantined"] == ["SOLUSDT"]


async def test_leverage_refusal_does_not_stop_startup(august_panel: Panel, tmp_path: Path) -> None:
    """A venue that refuses the derived leverage for one symbol keeps the old setting; the loop still starts."""
    world = _world(august_panel, tmp_path, leverage_mode="auto", margin_cap=0.4)
    engine, venue = world["engine"], world["venue"]
    original = venue.set_leverage

    async def refuse(symbol: str, leverage: int) -> int:
        if symbol == "ETHUSDT":
            raise RuntimeError("Leverage 5 is not valid for this symbol (-4028)")
        return await original(symbol, leverage)

    venue.set_leverage = refuse  # type: ignore[method-assign]
    await engine.startup()
    assert engine.state.leverage_set.get("BTCUSDT") == 5 and "ETHUSDT" not in engine.state.leverage_set
    record = await engine.run_cycle(world["market"].bar_open_ms(world["cursor"] - 1))
    assert not record["skip"]
