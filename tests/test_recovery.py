"""Durable order identity, partial protection fills, and risk reduction."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import pytest
from test_forward import FakeVenue, _bar, _clock, _run, _snap
from btc_perp.binance_client import UnknownExecution
from btc_perp.config import load_config
from btc_perp.model import AlgoOrder, Book, Intent, Limits, Trade
from btc_perp.runner import EntryContext, _entry_gate
from btc_perp.store import Store
NOW = _clock()[1]


class Crash(BaseException):
    """A process death. It is not an Exception so nothing in the cycle can swallow it."""


class CrashVenue(FakeVenue):
    """Dies around the network boundary of the first market order."""

    def __init__(self, snap, where: str) -> None:
        super().__init__(snap)
        self.where = where

    def place_market(self, *, client_id: str, side: str, qty: str, reduce_only: bool) -> dict[str, object]:
        if self.where == "before_send":
            self.where = ""
            raise Crash
        body = super().place_market(client_id=client_id, side=side, qty=qty, reduce_only=reduce_only)
        if self.where == "after_send":
            self.where = ""
            body["orderId"] = 7001
            self.orders[client_id] = body
            raise Crash
        return body


def _store(tmp: Path) -> Store:
    return Store(tmp, "demo")


def _fresh(**over: object):
    values: dict[str, object] = {"server_time_ms": NOW, "read_ms": NOW}
    values.update(over)
    return _snap(**values)


def _covered(position: float = 2.0, entry: float = 100.0):
    side = "SELL" if position > 0 else "BUY"
    stop, take = (entry * 0.968, entry * 10) if position > 0 else (entry * 1.032, entry / 10)
    algos = (
        AlgoOrder("st1", "STOP_MARKET", side, stop, True, False, 0.0, "NEW", "CONTRACT_PRICE"),
        AlgoOrder("tp1", "TAKE_PROFIT_MARKET", side, take, True, False, 0.0, "NEW", "CONTRACT_PRICE"),
    )
    return _fresh(position_qty=position, entry_price=entry, algos=algos)


def _book(**over: object) -> Book:
    book = Book()
    book.peak_equity_cny = book.close_peak_cny = 70_000.0
    for key, value in over.items():
        setattr(book, key, value)
    return book


def _entry_cycle(tmp: Path, venue: FakeVenue, store: Store | None = None):
    bar, now = _bar(100.0)
    opened = store or _store(tmp)
    return opened, _run(opened, venue, bar, now)


def test_a_crash_after_the_commit_and_before_the_send_never_adds_a_second_order(tmp_path: Path) -> None:
    venue = CrashVenue(_snap(server_time_ms=_bar(100.0)[1]), "before_send")
    store = _store(tmp_path)
    with pytest.raises(Crash):
        _entry_cycle(tmp_path, venue, store)
    store.close()
    store = _store(tmp_path)
    try:
        (held,) = store.intents()
        assert held.phase == "sent" and held.action == "enter"
        for step in range(3):
            _bar_now = _bar(100.0, step)
            _run(store, venue, _bar_now[0], _bar_now[1])
        assert venue.market_ids == []
        assert store.intents()[0].phase == "unknown"
        assert store.intents()[0].attempts == 1
    finally:
        store.close()


def test_a_crash_after_the_send_is_found_by_the_original_identity(tmp_path: Path) -> None:
    venue = CrashVenue(_snap(server_time_ms=_bar(100.0)[1]), "after_send")
    store = _store(tmp_path)
    with pytest.raises(Crash):
        _entry_cycle(tmp_path, venue, store)
    store.close()
    store = _store(tmp_path)
    try:
        bar, now = _bar(100.0, 1)
        venue.snap = dataclasses.replace(venue.snap, server_time_ms=now)
        report = _run(store, venue, bar, now)
        (placed,) = venue.market_ids
        item = next(entry for entry in store.intents() if entry.client_id == placed)
        assert item.phase == "filled" and item.order_id == "7001"
        assert len(venue.market_ids) == 1
        assert report.position_qty == pytest.approx(2.0)
        assert not report.frozen
    finally:
        store.close()


def test_stop_goes_first_and_take_waits_until_the_stop_is_confirmed(tmp_path: Path) -> None:
    class StopTimesOut(FakeVenue):
        def place_algo(self, **kwargs: object) -> dict[str, object]:
            if kwargs["order_type"] == "STOP_MARKET":
                self.algo_ids.append(str(kwargs["client_id"]))
                raise UnknownExecution("timeout")
            return super().place_algo(**kwargs)

    bar, now = _bar(100.0)
    venue = StopTimesOut(_snap(server_time_ms=now, position_qty=2.0, entry_price=100.0))
    store = _store(tmp_path)
    try:
        book = Book()
        book.side, book.qty, book.entry, book.units, book.stop = 1, 2.0, 100.0, 1, 96.8
        book.peak_equity_cny = book.close_peak_cny = 70_000.0
        store.save_book(book)
        store.put_json("book", {**json.loads(json.dumps(store.get_json("book"))), "swaps": {"trade_cursor": "0"}})
        report = _run(store, venue, bar, now, bars=())
        assert len(venue.algo_ids) == 1, "the take order must wait for a confirmed stop"
        assert not report.covered
        first = next(item for item in store.intents() if item.action == "stop")
        assert first.phase == "unknown"
    finally:
        store.close()


def _held_book(qty: float = 0.01) -> Book:
    book = _book(side=1, qty=qty, entry=100.0, units=1, stop=96.8, last_add=100.0)
    book.swaps["trade_cursor"] = "10"
    return book


def _finished_parent(venue: FakeVenue, child: dict[str, object]) -> None:
    venue.algos["st1"] = {"algoStatus": "FINISHED", "actualOrderId": "88", "symbol": "BTCUSDT"}
    body = {"symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "orderId": "88"}
    body.update(child)
    venue.order_ids["88"] = body


def test_a_confirmed_partial_stop_updates_the_remainder_and_keeps_protection(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    snap = dataclasses.replace(
        _fresh(position_qty=0.008, entry_price=100.0),
        trades=(Trade(11, "88", "SELL", 0.002, now - 500),),
        server_time_ms=now,
    )
    venue = FakeVenue(snap)
    _finished_parent(venue, {"status": "PARTIALLY_FILLED", "executedQty": "0.002"})
    store = _store(tmp_path)
    try:
        store.save_book(_held_book())
        store.insert_intent(
            Intent("st1", "stop", "acked", "SELL", "", False, True, "96.8", "demo", now - 5_000, "", 1, True)
        )
        report = _run(store, venue, bar, now)
        assert not report.frozen
        assert store.load_book().qty == pytest.approx(0.008)
        child = next(item for item in store.intents() if item.client_id == "st1")
        assert child.order_id == "88"
        assert float(child.executed) == pytest.approx(0.002)
        assert child.phase == "partial"
        assert venue.algo_ids  # the remaining position gets protection again
        assert store.load_book().swaps["trade_cursor"] == "11"
        again = _run(store, venue, bar, now)
        assert again.position_qty == pytest.approx(0.008)
        assert store.load_book().units == 1
    finally:
        store.close()


def test_an_expired_decision_still_allows_a_reduce(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    snap = dataclasses.replace(_covered(2.0), server_time_ms=now, clock_offset_ms=0, clock_rtt_ms=1)
    venue = FakeVenue(snap)
    store = _store(tmp_path)
    try:
        for name, action in (("st1", "stop"), ("tp1", "take")):
            store.insert_intent(
                Intent(name, action, "acked", "SELL", "", False, True, "", "demo", now - 1_000, "", 1, True)
            )
        store.save_book(_book(side=1, qty=2.0, entry=100.0, units=1, stop=96.8, last_add=100.0))
        _run(
            store,
            venue,
            bar,
            now,
            clock=lambda: now + 45_000,
            channels=(50.0, 1.0, 1.0e9, 200.0, bar.open_ms - 3_600_000),
        )
        assert venue.market_ids  # the channel exit is a reduce, and the age check does not block it
    finally:
        store.close()


def _ctx(**over: object) -> EntryContext:
    base: dict[str, object] = {
        "environment": "demo",
        "limits": Limits(None, None, None, None),
        "cli_cap": 200.0,
        "cap": 200.0,
        "prod_enabled": False,
        "clock": lambda: NOW,
    }
    base.update(over)
    return EntryContext(**base)


@pytest.mark.parametrize(("current", "book"), [
    (_fresh(), _book(dd_locked=True)),
    (_fresh(), _book(cooldown_until_ms=NOW + 1)),
    (_fresh(), _book(swaps={"flow_frozen": "1"})),
    (_fresh(), _book(manual=True)),
    (_fresh(read_ms=NOW - 60_000), _book()),
    (_fresh(read_ms=NOW + 45_000), _book()),
])
def test_new_risk_gate_refuses_unsafe_state(tmp_path: Path, current, book) -> None:
    with Store(tmp_path, "demo") as store:
        assert _entry_gate(store, current, book, load_config(), _ctx(), NOW)
