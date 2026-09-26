"""Plan gaps closed on 2026-09-04: T-L04 partial fills, the guard alert and the failed-cycle record.

The first two are Test Contract items from the refactor plan that had no assertion
behind them; the third is the asymmetry that made the -1023 outage on 2026-09-04
leave no durable trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import SYMBOLS, _config, _model, _prices


class RecordingAlerts:
    """A webhook that records instead of posting."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def clear(self, key: str) -> None:
        pass

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        self.sent.append(text)
        return True


def _world(august_panel: Panel, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    alerts = RecordingAlerts()
    engine = LiveEngine(
        _config(tmp_path, **overrides),
        model=_model(),
        market=market,
        venue=venue,
        clock=clock,
        store=store,
        alerts=alerts,
    )
    return {
        "market": market,
        "venue": venue,
        "clock": clock,
        "store": store,
        "engine": engine,
        "alerts": alerts,
        "cursor": cursor,
    }


async def test_partial_fill_is_re_derived_from_the_real_position(august_panel: Panel, tmp_path: Path) -> None:
    """T-L04: the next cycle sizes from the position the venue actually holds, not from what was requested."""
    world = _world(august_panel, tmp_path)
    engine, venue, market = world["engine"], world["venue"], world["market"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    venue.fill_ratios = dict.fromkeys(SYMBOLS, 0.5)  # every venue fill comes back half done
    first = await engine.run_cycle(bar)
    opened = [o for o in first["orders"] if o["status"] == "PARTIAL"]
    assert opened, "the crafted venue should report partial fills"
    victim = opened[0]["symbol"]
    requested = float(opened[0]["quantity"])
    held = venue.qty[victim]
    assert 0 < abs(held) < requested, "the venue holds only part of what was asked for"

    venue.fill_ratios = {}  # the book can fill normally again
    market.cursor += 1
    second = await engine.run_cycle(bar + 3_600_000)
    follow_up = [o for o in second["orders"] if o["symbol"] == victim]
    assert follow_up, "the shortfall must be re-ordered, not forgotten"
    # the follow-up closes the gap between the real position and the target, not the original request
    target_weight = second["targets"][victim]
    price = venue.prices[victim]
    target_qty = target_weight * second["equity"] / price
    assert abs(venue.qty[victim] - target_qty) < abs(held - target_qty), "the position moved towards its target"
    assert float(follow_up[0]["quantity"]) < requested, "it re-derives the delta rather than repeating the order"


async def test_guard_state_change_alerts_once_in_each_direction(august_panel: Panel, tmp_path: Path) -> None:
    """M-001: a guard that stops the book must be announced, and so must its clearing; neither may repeat."""
    world = _world(august_panel, tmp_path)
    engine, market, alerts = world["engine"], world["market"], world["alerts"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    await engine.run_cycle(bar)
    assert alerts.sent == [], "a clean cycle says nothing"

    engine.config.kill_switch_path.write_text("engaged\n", encoding="utf-8")
    market.cursor += 1
    await engine.run_cycle(bar + 3_600_000)
    assert len(alerts.sent) == 1 and "KILL_SWITCH" in alerts.sent[0]
    assert engine.state.last_guard_reasons == ["KILL_SWITCH"]

    market.cursor += 1
    await engine.run_cycle(bar + 2 * 3_600_000)
    assert len(alerts.sent) == 1, "the same guard must not alert every hour"

    engine.config.kill_switch_path.unlink()
    market.cursor += 1
    await engine.run_cycle(bar + 3 * 3_600_000)
    assert len(alerts.sent) == 2 and "风控解除" in alerts.sent[1]
    assert engine.state.last_guard_reasons == []


async def test_a_failed_cycle_leaves_a_durable_row(august_panel: Panel, tmp_path: Path) -> None:
    """The heartbeat is overwritten by the next cycle, so an outage has to be recorded in cycles.jsonl."""
    world = _world(august_panel, tmp_path)
    engine, market, store, alerts = world["engine"], world["market"], world["store"], world["alerts"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    ok = await engine.run_cycle(bar)
    engine._finish_cycle(ok, {})

    async def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("venue unreachable")

    engine.run_cycle = boom  # type: ignore[method-assign]
    market.cursor += 1
    assert await engine.guarded_cycle(bar + 3_600_000) is None

    rows = [json.loads(line) for line in store.cycles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = [r for r in rows if r.get("phase") == "ERROR"]
    assert len(failed) == 1, "the failure must be visible in cycles.jsonl, not only in the log"
    assert failed[0]["bar_open_ms"] == bar + 3_600_000  # buckets into the right day
    assert "venue unreachable" in failed[0]["error"] and failed[0]["consecutive_errors"] == 1
    assert "equity" not in failed[0], "no equity, so the drift check keeps ignoring it"
    assert failed[0]["targets"] == ok["targets"], "the targets still in force are carried"
    assert any("StarQuant周期失败" in text for text in alerts.sent)


async def test_the_score_behind_every_position_survives_in_the_append_only_log(
    august_panel: Panel, tmp_path: Path
) -> None:
    """T-L07: (bar, strategy, score, weight) must be reconstructable after state.json has been overwritten."""
    world = _world(august_panel, tmp_path)
    engine, market, store = world["engine"], world["market"], world["store"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    first = await engine.run_cycle(bar)
    market.cursor += 1
    await engine.run_cycle(bar + 3_600_000)  # state.json now holds only the second cycle's contributions

    rows = [json.loads(line) for line in store.cycles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(r for r in rows if r["bar_open_ms"] == bar)
    assert row["contributions"], "the first cycle's scores must still be readable"
    traced = {
        symbol: (row["bar"], strategy, score, row["targets"].get(symbol))
        for strategy, scores in row["contributions"].items()
        for symbol, score in scores.items()
    }
    assert traced, "at least one position traces back to a strategy and its score"
    for symbol, (_bar, _strategy, score, weight) in traced.items():
        assert score != 0.0 and weight is not None, symbol
    assert set(row["contributions"]) == set(first["contributions"])
    # And which BOOK each of those strategies belongs to (2026-09-12).  `contributions` keys by
    # strategy, and two instruments that ask a question about one book - M-015's compression and
    # M-Q08's slippage - were both answering it on the sum of two because no reader has the registry.
    assert row["books"], "a completed cycle records the strategy -> book map it ran under"
    assert set(row["books"]) >= set(row["contributions"]), "every scoring strategy names its book"
    assert all(isinstance(book, str) and book for book in row["books"].values())


async def test_failed_cycles_back_off_exponentially_up_to_an_hour(august_panel: Panel, tmp_path: Path) -> None:
    """M-004: the loop paces its own retries; launchd's ThrottleInterval only paces process restarts."""
    world = _world(august_panel, tmp_path)
    engine, clock = world["engine"], world["clock"]
    await engine.startup()

    async def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("venue unreachable")

    engine.run_cycle = boom  # type: ignore[method-assign]
    slept: list[float] = []
    original = clock.sleep

    async def record(seconds: float) -> None:
        slept.append(seconds)
        await original(0.0)

    clock.sleep = record  # type: ignore[method-assign]
    bar = world["market"].bar_open_ms(world["cursor"] - 1)
    for i in range(5):
        assert await engine.guarded_cycle(bar + i * 3_600_000) is None
    assert slept == [60.0, 120.0, 240.0, 480.0, 960.0]

    engine.consecutive_errors = 30  # a long outage must not sleep past the cap
    assert engine.backoff_seconds() == 3600.0


async def test_a_restart_is_counted(august_panel: Panel, tmp_path: Path) -> None:
    """M-004: 'restarts < 3/day' needs a counter; a first start is not a restart."""
    world = _world(august_panel, tmp_path)
    engine, market = world["engine"], world["market"]
    assert engine.state.restarts == 0 and engine.state.restarted_at is None
    await engine.startup()
    await engine.run_cycle(market.bar_open_ms(world["cursor"] - 1))

    revived = LiveEngine(
        engine.config,
        model=_model(),
        market=market,
        venue=world["venue"],
        clock=world["clock"],
        store=StateStore(tmp_path / "live"),
    )
    assert revived.state.restarts == 1 and revived.state.restarted_at is not None


def test_per_order_notional_cap_limits_a_single_order(august_panel: Panel) -> None:
    """T-E02: §10.2 put a per-order notional cap in the guard; it actually lives in the rebalancer, untested."""
    from decimal import Decimal

    from starquant_live.rebalancer import RebalanceParams, plan_rebalance
    from tests.fakes.fake_venue import DEFAULT_RULES

    equity = 100_000.0
    prices = {"BTCUSDT": 50_000.0}
    rules = {"BTCUSDT": DEFAULT_RULES["BTCUSDT"]}
    uncapped, _ = plan_rebalance(
        {"BTCUSDT": 0.10},
        managed_symbols=["BTCUSDT"],
        equity=equity,
        positions={},
        prices=prices,
        rules=rules,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=0.0),
    )
    assert uncapped and float(uncapped[0].quantity) * prices["BTCUSDT"] == pytest.approx(10_000.0, rel=1e-3)

    capped, _ = plan_rebalance(
        {"BTCUSDT": 0.10},
        managed_symbols=["BTCUSDT"],
        equity=equity,
        positions={},
        prices=prices,
        rules=rules,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=0.0, max_order_notional=2_500.0),
    )
    assert capped, "the cap trims the order, it does not drop it"
    assert float(capped[0].quantity) * prices["BTCUSDT"] <= 2_500.0
    assert capped[0].quantity < uncapped[0].quantity

    # a cap below one step cannot produce a valid order and must be reported, not silently rounded to zero
    dropped, skipped = plan_rebalance(
        {"BTCUSDT": 0.10},
        managed_symbols=["BTCUSDT"],
        equity=equity,
        positions={},
        prices=prices,
        rules=rules,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=0.0, max_order_notional=float(Decimal("0.00001") * 50_000)),
    )
    assert dropped == [] and skipped and skipped[0]["reason"] == "ORDER_CAP_BELOW_STEP"


async def test_startup_re_asserts_leverage_that_the_record_already_claims(august_panel: Panel, tmp_path: Path) -> None:
    """The venue never reports its leverage back, so the record must not be allowed to skip the POST.

    Reproduces the 2026-09-04 case: the loop believed it had set 5x on every symbol, the demo account
    was reset back to the venue default underneath it, and because `state.leverage_set` still agreed
    with the derived value nothing was ever re-sent.
    """
    world = _world(august_panel, tmp_path, leverage_mode="auto", margin_cap=0.4)
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    assert engine.state.leverage_set["BTCUSDT"] == 5

    venue.leverage.clear()  # the venue forgot; nothing in its API can tell the loop that
    venue.calls.clear()
    revived = LiveEngine(
        engine.config,
        model=_model(),
        market=world["market"],
        venue=venue,
        clock=world["clock"],
        store=StateStore(tmp_path / "live"),  # the record survives the restart and still says 5
    )
    assert revived.state.leverage_set["BTCUSDT"] == 5, "the cache is what used to suppress the POST"
    await revived.startup()
    assert venue.leverage["BTCUSDT"] == 5, "startup must put the venue back where the record says it is"
    assert sum(1 for call in venue.calls if call.startswith("set_leverage:")) == len(SYMBOLS)


def test_the_no_trade_band_records_what_it_suppressed(august_panel: Panel) -> None:
    """The band's three outcomes have to be distinguishable; before this they were one silent `continue`.

    CYSUSDT is the case that motivated it: a -41 USDT target against a 54 USDT absolute band, scored
    every cycle for a day, ordered never, and named by no instrument in the system.
    """
    from starquant_live.rebalancer import RebalanceParams, plan_rebalance
    from starquant_shared.types import Position
    from tests.fakes.fake_venue import DEFAULT_RULES

    equity = 10_000.0
    price = 100.0
    rules = {symbol: DEFAULT_RULES[symbol] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")}
    prices = dict.fromkeys(rules, price)
    held = {
        # a resize far too small to cross the band, and a position too small to be closed through it
        "ETHUSDT": Position("ETHUSDT", qty=10.0, entry_price=price, mark_price=price, unrealized_pnl=0.0),
        "SOLUSDT": Position("SOLUSDT", qty=0.3, entry_price=price, mark_price=price, unrealized_pnl=0.0),
    }
    orders, skipped = plan_rebalance(
        {"BTCUSDT": 0.002, "ETHUSDT": 0.1001, "SOLUSDT": 0.0, "BNBUSDT": 0.0},
        managed_symbols=sorted(rules),
        equity=equity,
        positions=held,
        prices=prices,
        rules=rules,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=0.005),
    )
    assert orders == [], "every symbol here is inside the band"
    by_symbol = {row["symbol"]: row["reason"] for row in skipped}
    assert by_symbol == {
        "BTCUSDT": "BAND_BLOCKS_ENTRY",  # 20 USDT wanted against a 50 USDT band: unreachable from flat
        "ETHUSDT": "NO_TRADE_BAND",  # an ordinary suppressed resize
        "SOLUSDT": "BAND_BLOCKS_EXIT",  # 30 USDT held, wants zero, cannot get there
    }, "BNBUSDT is flat and wants flat, which is not a gap and must stay silent"
    assert all(abs(row["delta_notional"]) < row["threshold"] for row in skipped)


def test_the_daily_report_names_the_symbols_the_band_blocked(tmp_path: Path) -> None:
    """T-L07's rule applied to the planner: an outcome that is not in the report did not happen."""
    from starquant_live.reports import plan_gaps

    store = StateStore(tmp_path / "live")
    for bar in ("2026-09-04T06:00:00+00:00", "2026-09-04T07:00:00+00:00"):
        store.append_cycle(
            {
                "bar": bar,
                "bar_open_ms": 1_788_501_600_000,
                "equity": 10_000.0,
                "skipped": [
                    {"symbol": "CYSUSDT", "reason": "BAND_BLOCKS_ENTRY", "delta_notional": -41.4, "threshold": 53.9},
                    {"symbol": "BTCUSDT", "reason": "NO_TRADE_BAND", "delta_notional": 6.0, "threshold": 145.9},
                ],
            }
        )
    gaps = plan_gaps(store, "2026-09-04")
    assert gaps["blocked_entry"] == ["CYSUSDT"], "the stuck symbol is named once, not once per cycle"
    assert gaps["blocked_exit"] == []
    assert gaps["band_held"] == 2, "the suppressed resizes are counted: P10 cell B's turnover falsifier"
    assert gaps["by_reason"] == {"BAND_BLOCKS_ENTRY": 2, "NO_TRADE_BAND": 2}
