"""Representative offline account execution cases; no exchange connection."""
from __future__ import annotations

import dataclasses
from pathlib import Path
import pytest
from btc_perp.bars import MinuteBar, completed_hour_channels, inspect_bars
from btc_perp.binance_client import UnknownExecution
from btc_perp.config import load_config
from btc_perp.model import AlgoOrder, Filters, Intent, Limits, RestingOrder, Snapshot
from btc_perp.runner import run_cycle as _real_run_cycle
from btc_perp.store import Store
_FILTERS = Filters(0.1, 0.001, 0.001, 100.0, 0.1, 1_000_000.0)


def run_cycle(store: Store, venue: FakeVenue, **kwargs: object):
    """The fake venue reads its account at the cycle's own clock, so quotes are fresh.

    The production default clock is the wall clock. Tests pin it to ``now_ms``
    unless a case passes its own.
    """
    now = int(kwargs["now_ms"])
    venue.read_ms = now
    kwargs.setdefault("clock", lambda: now)
    return _real_run_cycle(store, venue, **kwargs)


def _snap(**kwargs: object) -> Snapshot:
    base: dict[str, object] = {
        "known": True,
        "reason": "",
        "position_qty": 0.0,
        "entry_price": 0.0,
        "wallet_usdt": 10_000.0,
        "available_usdt": 10_000.0,
        "mark_price": 100.0,
        "last_price": 100.0,
        "liquidation_price": 0.0,
        "one_way": True,
        "isolated": True,
        "leverage": 20,
        "symbol_status": "TRADING",
        "server_time_ms": 0,
        "can_trade": True,
        "fee_taker": 0.0004,
        "filters": _FILTERS,
        "brackets_ok": True,
        "recent_trades_ok": True,
        "funding_ok": True,
        "auto_add_margin_off": True,
    }
    base.update(kwargs)
    return Snapshot(**base)


class FakeVenue:
    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap
        self.market_ids: list[str] = []
        self.algo_ids: list[str] = []
        self.cancels: list[str] = []
        self.fail_market: Exception | None = None
        self.market_body: dict[str, object] | None = None
        self.orders: dict[str, dict[str, object]] = {}
        self.order_ids: dict[str, dict[str, object]] = {}
        self.algos: dict[str, dict[str, object]] = {}
        self.read_ms = 0

    def snapshot(self) -> Snapshot:
        return dataclasses.replace(self.snap, read_ms=self.read_ms) if self.read_ms else self.snap

    def place_market(self, *, client_id: str, side: str, qty: str, reduce_only: bool) -> dict[str, object]:
        self.market_ids.append(client_id)
        if self.fail_market is not None:
            exc = self.fail_market
            self.fail_market = None
            raise exc
        if self.market_body is not None:
            body = dict(self.market_body)
            self.orders[client_id] = body
            self.market_body = None
            status = str(body.get("status", ""))
            if status in {"FILLED", "PARTIALLY_FILLED"}:
                filled = float(str(body.get("executedQty", qty)))
                signed = filled if side == "BUY" else -filled
                self.snap = dataclasses.replace(
                    self.snap,
                    position_qty=self.snap.position_qty + signed,
                    entry_price=self.snap.mark_price or 100.0,
                )
            return body
        filled = float(qty)
        delta = filled if side == "BUY" else -filled
        new_qty = self.snap.position_qty - filled if reduce_only and self.snap.position_qty > 0 else None
        if new_qty is None and reduce_only and self.snap.position_qty < 0:
            new_qty = self.snap.position_qty + filled
        if new_qty is None:
            new_qty = self.snap.position_qty + delta
        if abs(new_qty) < 1e-8:
            self.snap = dataclasses.replace(self.snap, position_qty=0.0, entry_price=0.0)
        else:
            self.snap = dataclasses.replace(self.snap, position_qty=new_qty, entry_price=self.snap.mark_price or 100.0)
        body = {"status": "FILLED", "executedQty": qty}
        self.orders[client_id] = body
        return body

    def place_algo(
        self,
        *,
        client_id: str,
        side: str,
        order_type: str,
        trigger_price: str,
        close_position: bool,
        qty: str = "",
        reduce_only: bool = False,
    ) -> dict[str, object]:
        self.algo_ids.append(client_id)
        algo = AlgoOrder(
            client_id,
            order_type,
            side,
            float(trigger_price),
            close_position,
            reduce_only,
            float(qty or 0),
            "NEW",
            "CONTRACT_PRICE",
        )
        self.snap = dataclasses.replace(self.snap, algos=(*self.snap.algos, algo))
        body = {"algoStatus": "NEW", "clientAlgoId": client_id}
        self.algos[client_id] = body
        return body

    def cancel_order(self, client_id: str) -> dict[str, object]:
        self.cancels.append(client_id)
        self.snap = dataclasses.replace(
            self.snap,
            orders=tuple(order for order in self.snap.orders if order.client_id != client_id),
        )
        return {"status": "CANCELED"}

    def cancel_algo(self, client_id: str) -> dict[str, object]:
        self.cancels.append(client_id)
        kept = []
        for algo in self.snap.algos:
            if algo.client_algo_id == client_id:
                kept.append(dataclasses.replace(algo, status="CANCELED"))
            else:
                kept.append(algo)
        self.snap = dataclasses.replace(self.snap, algos=tuple(kept))
        return {"algoStatus": "CANCELED"}

    def query_order(self, client_id: str) -> dict[str, object]:
        return self.orders.get(client_id, {"code": -2013, "msg": "Order does not exist."})

    def query_order_id(self, order_id: str) -> dict[str, object]:
        return self.order_ids.get(order_id, {"code": -2013, "msg": "Order does not exist."})

    def query_algo(self, client_id: str) -> dict[str, object]:
        return self.algos.get(client_id, {"code": -2013, "msg": "Order does not exist."})


def _clock(index: int = 0) -> tuple[int, int]:
    hour = 1_700_000_000_000
    hour -= hour % 3_600_000
    open_ms = hour + 59 * 60_000 + index * 60_000
    return open_ms, open_ms + 61_000


def _bar(price: float, index: int = 0, *, high: float | None = None, low: float | None = None) -> tuple[MinuteBar, int]:
    open_ms, now = _clock(index)
    return MinuteBar(
        open_ms, price, high if high is not None else price, low if low is not None else price, price, 1_000_000.0, True
    ), now


def _channels(open_ms: int, hh: float, ll: float, xh: float, xl: float) -> tuple[float, float, float, float, int]:
    return hh, ll, xh, xl, open_ms - 3_600_000


def _cycle(tmp: Path, venue: FakeVenue, bars: tuple[MinuteBar, ...], now: int, **kwargs: object):
    store = Store(tmp, "demo")
    try:
        report = run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=bars,
            channels=_channels(bars[-1].open_ms if bars else now, 50.0, 1.0, 1.0e9, 1.0),
            fx=7.0,
            mode="run",
            prod_enabled=False,
            **kwargs,
        )
        return store, report
    except Exception:
        store.close()
        raise


def test_a_long_entry_rests_a_stop_and_a_disaster_take(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert report.position_qty == pytest.approx(2.0)
        assert report.covered
        assert len(venue.market_ids) == 1
        assert venue.market_ids[0].startswith("en")
        kinds = {algo.order_type for algo in venue.snap.algos if algo.status == "NEW"}
        assert kinds == {"STOP_MARKET", "TAKE_PROFIT_MARKET"}
        assert all(algo.close_position and not algo.reduce_only for algo in venue.snap.algos)
        phases = {item.client_id: item.phase for item in store.intents()}
        assert phases[venue.market_ids[0]] == "filled"
    finally:
        store.close()


def _run(store: Store, venue: FakeVenue, bar: MinuteBar, now: int, **kwargs: object):
    args: dict[str, object] = {
        "environment": "demo",
        "limits": Limits(None, None, None, None),
        "max_notional": 200.0,
        "cfg": load_config(),
        "now_ms": now,
        "bars": (bar,),
        "channels": _channels(bar.open_ms, 50.0, 1.0, 1.0e9, 1.0),
        "fx": 7.0,
        "mode": "run",
        "prod_enabled": False,
    }
    args.update(kwargs)
    return run_cycle(store, venue, **args)


def test_an_unanswered_entry_is_never_sent_twice(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    venue.fail_market = UnknownExecution("timed out")
    store, first = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert first.position_qty == 0
        held = venue.market_ids[0]
        assert store.intents()[0].phase == "unknown"
        for step in range(4):
            _run(store, venue, bar, now + step)
        assert venue.market_ids == [held]
        assert store.intents()[0].phase == "unknown"
        assert store.intents()[0].attempts == 1
    finally:
        store.close()


def test_an_entry_that_did_fill_is_found_by_the_original_id(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    venue.fail_market = UnknownExecution("timed out")
    store, _first = _cycle(tmp_path, venue, (bar,), now)
    try:
        held = venue.market_ids[0]
        venue.orders[held] = {"status": "FILLED", "executedQty": "2.0"}
        venue.snap = dataclasses.replace(venue.snap, position_qty=2.0, entry_price=100.0)
        _run(store, venue, bar, now)
        assert venue.market_ids == [held]
        assert next(item for item in store.intents() if item.client_id == held).phase == "filled"
        assert store.load_book().manual is False
        assert store.load_book().qty == pytest.approx(2.0)
    finally:
        store.close()


def test_restart_queries_the_saved_id_and_does_not_mint_another(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.01, entry_price=100.0))
    store = Store(tmp_path, "demo")
    store.insert_intent(
        Intent("enrestart00000000000001", "enter", "sent", "BUY", "0.010", False, False, "", "demo", now, "")
    )
    venue.orders["enrestart00000000000001"] = {"status": "FILLED", "executedQty": "0.010"}
    store.close()
    store = Store(tmp_path, "demo")
    try:
        run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=(),
            channels=None,
            fx=7.0,
            mode="run",
            prod_enabled=False,
        )
        assert venue.market_ids == []
        saved = next(item for item in store.intents() if item.action == "enter")
        assert saved.phase == "filled"
    finally:
        store.close()


def test_a_partial_fill_does_not_open_a_second_order(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    venue.market_body = {"status": "PARTIALLY_FILLED", "executedQty": "1.000"}
    store, _report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert venue.snap.position_qty == pytest.approx(1.0)
        entered = next(item for item in store.intents() if item.action == "enter")
        assert entered.phase == "partial"
        run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=(bar,),
            channels=_channels(bar.open_ms, 50.0, 1.0, 1.0e9, 1.0),
            fx=7.0,
            mode="run",
            prod_enabled=False,
        )
        assert venue.market_ids == [venue.market_ids[0]]
    finally:
        store.close()


def test_stop_cancels_risk_orders_and_keeps_protection(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    stop = AlgoOrder("stkeep000000000000000001", "STOP_MARKET", "SELL", 96.8, True, False, 0.0, "NEW", "CONTRACT_PRICE")
    take = AlgoOrder(
        "tpkeep000000000000000001", "TAKE_PROFIT_MARKET", "SELL", 1000.0, True, False, 0.0, "NEW", "CONTRACT_PRICE"
    )
    plain = RestingOrder("enrisk00000000000000001", "BUY", "LIMIT", 1.0, 0.0, False, "NEW", 90.0)
    venue = FakeVenue(
        _snap(server_time_ms=now, position_qty=0.01, entry_price=100.0, orders=(plain,), algos=(stop, take))
    )
    store = Store(tmp_path, "demo")
    store.insert_intent(Intent(plain.client_id, "enter", "acked", "BUY", "1.0", False, False, "", "demo", now, ""))
    for algo in (stop, take):
        store.insert_intent(
            Intent(algo.client_algo_id, "stop", "acked", "SELL", "", False, True, "90.0", "demo", now, "")
        )
    try:
        report = run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=(),
            channels=None,
            fx=7.0,
            mode="stop",
            prod_enabled=False,
        )
        assert plain.client_id in venue.cancels
        assert stop.client_algo_id not in venue.cancels
        assert take.client_algo_id not in venue.cancels
        assert report.frozen
    finally:
        store.close()


def test_two_processes_cannot_share_a_state_directory(tmp_path: Path) -> None:
    first = Store(tmp_path, "demo")
    try:
        with pytest.raises(RuntimeError, match="另一个进程"):
            Store(tmp_path, "demo")
    finally:
        first.close()


def test_stale_bars_do_not_add_risk(tmp_path: Path) -> None:
    bar, _now = _bar(100.0)
    now = bar.open_ms + 120_000
    venue = FakeVenue(_snap(server_time_ms=now))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert venue.market_ids == []
        assert report.frozen
        assert "滞后" in report.reason
    finally:
        store.close()


def test_unknown_snapshot_sends_nothing(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(known=False, reason="断开", server_time_ms=0))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert venue.market_ids == []
        assert report.frozen
    finally:
        store.close()


def test_production_without_the_gate_does_not_send(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    limits = Limits(100.0, 200.0, 50.0, 30)
    store = Store(tmp_path, "prod")
    try:
        report = run_cycle(
            store,
            venue,
            environment="prod",
            limits=limits,
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=(bar,),
            channels=_channels(bar.open_ms, 50.0, 1.0, 1.0e9, 1.0),
            fx=7.0,
            mode="run",
            prod_enabled=False,
        )
        assert venue.market_ids == []
        assert any("生产增仓已关闭" in item for item in report.alerts)
    finally:
        store.close()


def test_incomplete_minutes_and_gaps_are_rejected() -> None:
    now = 1_700_000_060_000
    open_ms = now - 30_000
    forming = MinuteBar(open_ms, 1, 1, 1, 1, 1, False)
    assert inspect_bars((forming,), now, 0).fresh is False
    first = MinuteBar(1_700_000_000_000, 1, 1, 1, 1, 1, True)
    third = MinuteBar(1_700_000_120_000, 1, 1, 1, 1, 1, True)
    status = inspect_bars((first, third), third.open_ms + 61_000, 0)
    assert status.fresh is False


def test_channels_ignore_the_forming_hour() -> None:
    start = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000
    done = [start, "1", "10", "1", "9", "1", start + 3_600_000 - 1, "1"]
    forming = [start + 3_600_000, "1", "99", "1", "98", "1", start + 7_200_000 - 1, "1"]
    now = start + 3_600_000 + 1_000
    levels = completed_hour_channels([done, forming], now, 1, 1)
    assert levels is not None
    assert levels[0] == pytest.approx(10.0)
