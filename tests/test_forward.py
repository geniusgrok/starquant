"""Forward account safety. The venue here is in-process; it is not a Demo month."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from btc_perp.bars import MinuteBar, completed_hour_channels, inspect_bars
from btc_perp.binance_client import AlgoEndpointRequired, UnknownExecution, UsdMClient, redact
from btc_perp.config import load_config
from btc_perp.gates import entry_block_reason, load_limits
from btc_perp.machine import protections_cover
from btc_perp.model import AlgoOrder, Filters, Intent, Limits, RestingOrder, Snapshot
from btc_perp.runner import run_cycle as _real_run_cycle
from btc_perp.store import Store
from btc_perp.stream import hint_from_event

_FILTERS = Filters(0.1, 0.001, 0.001, 100.0, 0.1, 1_000_000.0)


def run_cycle(store: Store, venue: FakeVenue, **kwargs: object):
    """The fake venue reads its account at the cycle's own clock, so quotes are fresh.

    The production default clock is the wall clock. Tests pin it to ``now_ms``
    unless a case passes its own.
    """
    now = int(kwargs["now_ms"])  # type: ignore[call-overload]
    venue.read_ms = now
    kwargs.setdefault("clock", lambda: now)
    return _real_run_cycle(store, venue, **kwargs)  # type: ignore[arg-type]


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
    return Snapshot(**base)  # type: ignore[arg-type]


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
            **kwargs,  # type: ignore[arg-type]
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
    return run_cycle(store, venue, **args)  # type: ignore[arg-type]


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


def test_an_unanswered_reduce_is_resent_once_with_the_same_id(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.01, entry_price=100.0))
    store = Store(tmp_path, "demo")
    store.insert_intent(
        Intent("rdresend0000000000001", "reduce", "unknown", "SELL", "0.010", True, False, "", "demo", now, "timeout")
    )
    book = store.load_book()
    book.side, book.qty, book.entry, book.units = 1, 0.01, 100.0, 1
    store.save_book(book)
    try:
        for step in range(3):
            _run(store, venue, bar, now + step, mode="flatten")
        assert venue.market_ids == ["rdresend0000000000001"]
        item = next(item for item in store.intents() if item.client_id == "rdresend0000000000001")
        assert item.attempts == 2
        assert item.phase == "filled"
    finally:
        store.close()


def test_a_note_cannot_reopen_the_retry_budget(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.01, entry_price=100.0))
    store = Store(tmp_path, "demo")
    store.insert_intent(
        Intent("enfixed00000000000001", "enter", "unknown", "BUY", "0.010", False, False, "", "demo", now, "retried")
    )
    store.mark_intent("enfixed00000000000001", "unknown", "anything-else")
    try:
        for step in range(3):
            _run(store, venue, bar, now + step)
        assert "enfixed00000000000001" not in venue.market_ids
    finally:
        store.close()


def test_a_reject_is_terminal_and_a_later_bar_uses_a_new_id(tmp_path: Path) -> None:
    first, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    venue.market_body = {"code": -2019, "msg": "Margin is insufficient."}
    store, _report = _cycle(tmp_path, venue, (first,), now)
    try:
        assert store.intents()[0].phase == "rejected"
        rejected = venue.market_ids[0]
        bars = []
        for index in range(0, 61):
            open_ms, _stamp = _clock(index)
            bars.append(MinuteBar(open_ms, 100.0, 100.0, 100.0, 100.0, 1_000_000.0, True))
        later = bars[-1].open_ms + 61_000
        venue.snap = dataclasses.replace(venue.snap, server_time_ms=later)
        run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=later,
            bars=tuple(bars),
            channels=_channels(bars[-1].open_ms, 50.0, 1.0, 1.0e9, 1.0),
            fx=7.0,
            mode="run",
            prod_enabled=False,
        )
        assert len(venue.market_ids) == 2
        assert venue.market_ids[1] != rejected
        assert venue.market_ids[1].startswith("en")
        assert any(item.client_id == rejected and item.phase == "rejected" for item in store.intents())
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


def test_a_cancel_that_actually_filled_is_not_sent_again(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.0, entry_price=0.0))
    store = Store(tmp_path, "demo")
    client_id = "rdcancelrace000000000001"
    store.insert_intent(Intent(client_id, "reduce", "unknown", "SELL", "0.010", True, False, "", "demo", now, ""))
    venue.orders[client_id] = {"status": "FILLED", "executedQty": "0.010"}
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
        assert store.intents()[0].phase == "filled"
    finally:
        store.close()


def test_a_flat_book_cancels_the_leftover_protection(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    leftover = AlgoOrder(
        "stleftover0000000000001", "STOP_MARKET", "SELL", 90.0, True, False, 0.0, "NEW", "CONTRACT_PRICE"
    )
    venue = FakeVenue(_snap(server_time_ms=now, algos=(leftover,)))
    store = Store(tmp_path, "demo")
    store.insert_intent(
        Intent(leftover.client_algo_id, "stop", "acked", "SELL", "", False, True, "90.0", "demo", now, "")
    )
    try:
        _run(store, venue, _bar(100.0)[0], now, bars=(), channels=None)
        assert leftover.client_algo_id in venue.cancels
        assert all(algo.status != "NEW" for algo in venue.snap.algos)
    finally:
        store.close()


def test_a_flat_book_leaves_a_foreign_conditional_order_alone(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    foreign = AlgoOrder("someone-elses-stop", "STOP_MARKET", "SELL", 90.0, True, False, 0.0, "NEW", "CONTRACT_PRICE")
    venue = FakeVenue(_snap(server_time_ms=now, algos=(foreign,)))
    store = Store(tmp_path, "demo")
    try:
        report = _run(store, venue, _bar(100.0)[0], now, bars=(), channels=None)
        assert venue.cancels == []
        assert report.frozen
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


def test_manual_position_freezes_until_takeover(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.02, entry_price=100.0))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert report.frozen
        assert venue.market_ids == []
        assert "实仓" in report.reason
        taken = run_cycle(
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
            mode="takeover",
            prod_enabled=False,
        )
        assert taken.frozen
        assert venue.market_ids == []
        assert store.load_book().manual
    finally:
        store.close()


def test_two_processes_cannot_share_a_state_directory(tmp_path: Path) -> None:
    first = Store(tmp_path, "demo")
    try:
        with pytest.raises(RuntimeError, match="另一个进程"):
            Store(tmp_path, "demo")
    finally:
        first.close()


def test_a_directory_is_stuck_to_one_environment(tmp_path: Path) -> None:
    store = Store(tmp_path, "demo")
    store.close()
    with pytest.raises(RuntimeError, match="demo"):
        Store(tmp_path, "prod")


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


def test_clock_drift_blocks_a_new_order(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now + 10_000))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert venue.market_ids == []
        assert "时间" in report.reason
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


def test_a_foreign_order_freezes_entries(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    foreign = RestingOrder("someone-else", "BUY", "LIMIT", 1.0, 0.0, False, "NEW")
    venue = FakeVenue(_snap(server_time_ms=now, orders=(foreign,)))
    store, report = _cycle(tmp_path, venue, (bar,), now)
    try:
        assert venue.market_ids == []
        assert "外来" in report.reason
    finally:
        store.close()


def test_reverse_waits_until_the_old_position_is_flat(tmp_path: Path) -> None:
    bar, now = _bar(90.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.01, entry_price=100.0, mark_price=90.0, last_price=90.0))
    store = Store(tmp_path, "demo")
    book = store.load_book()
    book.side = 1
    book.qty = 0.01
    book.entry = 100.0
    book.units = 1
    book.extreme = 100.0
    book.last_add = 100.0
    book.stop = 85.0
    store.save_book(book)
    try:
        report = run_cycle(
            store,
            venue,
            environment="demo",
            limits=Limits(None, None, None, None),
            max_notional=200.0,
            cfg=load_config(),
            now_ms=now,
            bars=(bar,),
            channels=_channels(bar.open_ms, 1.0e9, 95.0, 1.0e9, 95.0),
            fx=7.0,
            mode="run",
            prod_enabled=False,
        )
        assert venue.market_ids[0].startswith("rd")
        assert len(venue.market_ids) == 2
        assert venue.market_ids[1].startswith("en")
        assert report.position_qty < 0
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


def test_empty_limits_refuse_production_entries() -> None:
    reason = entry_block_reason("prod", Limits(None, None, None, None), 10.0, prod_enabled=True)
    assert "capital_usdt" in reason
    assert entry_block_reason("demo", Limits(None, None, None, None), None, prod_enabled=False)


def test_check_does_not_place(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
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
            mode="check",
            prod_enabled=False,
        )
        assert venue.market_ids == []
        assert venue.algo_ids == []
        lines = (tmp_path / "journal.jsonl").read_text().splitlines()
        assert lines
        row = json.loads(lines[-1])
        assert row["kind"] == "cycle"
        assert row["mode"] == "check"
        assert row["position_qty"] == 0.0
        assert "api" not in lines[-1].lower()
    finally:
        store.close()


def test_stream_hint_does_not_change_the_book_and_rest_is_the_position(tmp_path: Path) -> None:
    kind, client = hint_from_event({"e": "ALGO_UPDATE", "o": {"caid": "st1", "q": "5"}})
    assert kind == "algo"
    assert client == "st1"
    assert hint_from_event({"e": "listenKeyExpired"})[0] == "expired"
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=0.01, entry_price=100.0))
    store, report = _cycle(tmp_path, venue, (bar,), now, stream_expired=True)
    try:
        assert report.position_qty == pytest.approx(0.01)
        assert any("REST" in item for item in report.alerts)
        assert store.load_book().qty != 5
    finally:
        store.close()


def test_a_trailed_stop_above_entry_can_cover_and_a_reversed_pair_cannot() -> None:
    def pair(stop: float, take: float, last: float) -> tuple[bool, str]:
        stop_order = AlgoOrder("st", "STOP_MARKET", "SELL", stop, True, False, 0.0, "NEW", "CONTRACT_PRICE")
        take_order = AlgoOrder("tp", "TAKE_PROFIT_MARKET", "SELL", take, True, False, 0.0, "NEW", "CONTRACT_PRICE")
        snap = _snap(
            position_qty=0.01, entry_price=100.0, last_price=last, mark_price=last, algos=(stop_order, take_order)
        )
        return protections_cover(snap)

    assert pair(105.0, 200.0, 110.0)[0]
    assert not pair(115.0, 200.0, 110.0)[0]
    assert not pair(120.0, 110.0, 130.0)[0]


def test_demo_client_rejects_the_production_host() -> None:
    class Transport:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            raise AssertionError(url)

    with pytest.raises(RuntimeError, match="demo 客户端不能使用生产域名"):
        UsdMClient("demo", "key", "secret", Transport(), base_url="https://fapi.binance.com")


def test_algo_endpoint_error_does_not_change_host() -> None:
    seen: list[str] = []

    class Transport:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            seen.append(url)
            return 400, b'{"code":-4120,"msg":"use algo"}'

    client = UsdMClient("demo", "topsecret-demo-key", "topsecret-demo-secret", Transport())
    with pytest.raises(AlgoEndpointRequired):
        client.place_market(client_id="en0123456789abcdef0123", side="BUY", qty="0.001", reduce_only=False)
    assert client.base_url == "https://demo-fapi.binance.com"
    assert seen and seen[0].startswith("https://demo-fapi.binance.com/")
    assert "/fapi/v1/order" in seen[0]


def test_close_position_rejects_quantity_before_the_socket() -> None:
    class Transport:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            raise AssertionError("socket")

    client = UsdMClient("demo", "k", "s", Transport())
    with pytest.raises(ValueError, match="closePosition"):
        client.place_algo(
            client_id="st0123456789abcdef0123",
            side="SELL",
            order_type="STOP_MARKET",
            trigger_price="90",
            close_position=True,
            qty="0.01",
            reduce_only=True,
        )


def test_timeout_text_is_redacted() -> None:
    class Transport:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            raise TimeoutError("failed topsecret-demo-key")

    client = UsdMClient("demo", "topsecret-demo-key", "topsecret-demo-secret", Transport())
    with pytest.raises(UnknownExecution) as caught:
        client.place_market(client_id="en0123456789abcdef0123", side="BUY", qty="0.002", reduce_only=False)
    assert "topsecret-demo-key" not in str(caught.value)
    assert redact("a topsecret-demo-secret b", ("topsecret-demo-secret",)) == "a [redacted] b"


def test_client_has_no_withdraw_or_transfer() -> None:
    assert not hasattr(UsdMClient, "withdraw")
    assert not hasattr(UsdMClient, "transfer")


def test_default_cli_does_not_trade(capsys: pytest.CaptureFixture[str]) -> None:
    from btc_perp.__main__ import main

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "不会下单" in out
    assert "生产增仓默认关闭" in out


def test_cli_refuses_to_run_without_keys(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from btc_perp.__main__ import main

    monkeypatch.delenv("STARQUANT_PROD_API_KEY", raising=False)
    monkeypatch.delenv("STARQUANT_PROD_API_SECRET", raising=False)
    code = main(["run", "--environment", "prod", "--max-notional-usdt", "10", "--once"])
    assert code == 2
    assert "STARQUANT_PROD_API_KEY" in capsys.readouterr().out


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


def test_shipped_limits_are_empty() -> None:
    limits = load_limits()
    assert limits.capital_usdt is None
    assert limits.max_notional_usdt is None
