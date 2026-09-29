"""Round-five audit fixes, one group at a time (S01-S15).

Each test drives the real call chain: ``run_cycle``, the entry gate, the store,
the client parser. The venue is an in-process fake; none of this talks to an
exchange.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from pathlib import Path

import pytest
from test_audit_fixes import ACCOUNT, INFO, POSITION, _client, _routes
from test_forward import FakeVenue, _bar, _clock, _run, _snap

from btc_perp.bars import MinuteBar, hour_rows_from_klines, inspect_bars
from btc_perp.binance_client import UnknownExecution, _snapshot_from, account_problems
from btc_perp.config import ConfigError, load_config
from btc_perp.machine import (
    foreign_trades,
    freeze_for_manual,
    plan_protection,
    position_bounds,
    protections_cover,
)
from btc_perp.model import Action, AlgoOrder, Book, Income, Intent, Limits, RestingOrder, Trade
from btc_perp.permissions import prod_uid_block
from btc_perp.reportio import completion, publish
from btc_perp.runner import (
    EntryContext,
    _act,
    _cancel,
    _entry_gate,
    _maybe_open_after_flat,
    classify,
    resolve_intent,
)
from btc_perp.store import Store

NOW = _clock()[1]


class Crash(BaseException):
    """A process death. It is not an Exception so nothing in the cycle can swallow it."""


class CrashVenue(FakeVenue):
    """Dies around the network boundary of the first market order."""

    def __init__(self, snap, where: str) -> None:  # type: ignore[no-untyped-def]
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
    return EntryContext(**base)  # type: ignore[arg-type]


def _fresh(**over: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {"server_time_ms": NOW, "read_ms": NOW}
    values.update(over)
    return _snap(**values)


def _covered(position: float = 2.0, entry: float = 100.0):  # type: ignore[no-untyped-def]
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


# S01: one gate for every new-risk path -------------------------------------------------


def test_the_gate_is_open_only_when_everything_it_checks_is_fine(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        assert _entry_gate(store, _fresh(), _book(), load_config(), _ctx(), NOW) == ""
    finally:
        store.close()


def _unknown_entry(store: Store) -> None:
    store.insert_intent(
        Intent("en1", "enter", "unknown", "BUY", "1.0", False, False, "", "demo", NOW - 5_000, "", 1, False)
    )


@pytest.mark.parametrize(
    ("label", "snap", "book", "ctx", "prepare"),
    [
        ("authorization revoked", _fresh(), _book(), _ctx(environment="prod"), None),
        ("quota missing", _fresh(), _book(), _ctx(cli_cap=None, cap=None), None),
        ("drawdown lock", _fresh(), _book(dd_locked=True), _ctx(), None),
        ("stale quote", _fresh(read_ms=NOW - 60_000), _book(), _ctx(), None),
        ("never read", _fresh(read_ms=0), _book(), _ctx(), None),
        ("cooldown", _fresh(), _book(cooldown_until_ms=NOW + 1), _ctx(), None),
        ("frozen", _fresh(), _book(entries_frozen=True, freeze_reason="x"), _ctx(), None),
        ("taken over", _fresh(), _book(manual=True), _ctx(), None),
        ("funds moved", _fresh(), _book(swaps={"flow_frozen": "1"}), _ctx(), None),
        ("unknown entry outstanding", _fresh(), _book(), _ctx(), _unknown_entry),
        (
            "foreign order resting",
            _fresh(orders=(RestingOrder("theirs", "BUY", "LIMIT", 1.0, 0.0, False, "NEW"),)),
            _book(),
            _ctx(),
            None,
        ),
        (
            "position without protection",
            _fresh(position_qty=2.0, entry_price=100.0),
            _book(side=1, qty=2.0),
            _ctx(),
            None,
        ),
        (
            "position not ours",
            _fresh(position_qty=-3.0, entry_price=100.0),
            _book(side=1, qty=1.0),
            _ctx(),
            _unknown_entry,
        ),
        ("account unknown", dataclasses.replace(_fresh(), known=False, reason="读不到"), _book(), _ctx(), None),
        ("decision too old", _fresh(), _book(), _ctx(clock=lambda: NOW + 40_000), None),
    ],
)
def test_the_gate_refuses(label: str, snap, book, ctx, prepare, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    try:
        if prepare is not None:
            prepare(store)
        assert _entry_gate(store, snap, book, load_config(), ctx, NOW) != "", label
    finally:
        store.close()


def test_a_stop_request_closes_the_gate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        (tmp_path / "stop.request").write_text(json.dumps({"environment": "demo"}))
        assert "停机" in _entry_gate(store, _fresh(), _book(), load_config(), _ctx(), NOW)
        (tmp_path / "stop.request").write_text(json.dumps({"environment": "prod"}))
        assert _entry_gate(store, _fresh(), _book(), load_config(), _ctx(), NOW) == ""
    finally:
        store.close()


@pytest.mark.parametrize("path", ["enter", "add", "reverse", "restarted plan"])
def test_no_new_risk_path_gets_around_a_closed_gate(path: str, tmp_path: Path) -> None:
    store = _store(tmp_path)
    venue = FakeVenue(_covered() if path == "add" else _fresh())
    venue.read_ms = NOW
    book = _book(dd_locked=True)
    sent: list[str] = []
    alerts: list[str] = []
    try:
        if path in {"enter", "add"}:
            book.side, book.qty, book.units = (1, 2.0, 1) if path == "add" else (0, 0.0, 0)
            note = _act(
                Action(path, 1, 1.0),
                store,
                venue,
                venue.snapshot(),
                book,
                load_config(),
                _ctx(),
                sent,
                [],
                alerts,
                False,
                NOW,
                0,
            )
            assert "回撤锁" in note
        elif path == "reverse":
            book.swaps.update({"after_flat": "SELL", "after_flat_ms": "0"})
            _maybe_open_after_flat(store, venue, venue.snapshot(), book, load_config(), _ctx(), sent, alerts, NOW)
            assert any("回撤锁" in item for item in alerts)
        else:
            store.insert_intent(
                Intent("en9", "enter", "planned", "BUY", "1.0", False, False, "", "demo", NOW - 1, "", 1, False)
            )
            from btc_perp.runner import _reconcile

            _reconcile(store, venue, venue.snapshot(), book, sent, alerts, allow="all", now_ms=NOW, dry_run=False)
            assert store.intents()[0].phase == "canceled"
        assert venue.market_ids == []
    finally:
        store.close()


def _entry_cycle(tmp: Path, venue: FakeVenue, store: Store | None = None):  # type: ignore[no-untyped-def]
    bar, now = _bar(100.0)
    opened = store or _store(tmp)
    return opened, _run(opened, venue, bar, now)


def test_a_crash_before_the_commit_leaves_no_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    venue = FakeVenue(_snap(server_time_ms=_bar(100.0)[1]))
    store = _store(tmp_path)

    def dies(*_a: object, **_k: object) -> None:
        raise Crash

    monkeypatch.setattr(store, "record_send", dies)
    with pytest.raises(Crash):
        _entry_cycle(tmp_path, venue, store)
    try:
        assert venue.market_ids == []
        assert store.intents() == []
    finally:
        store.close()


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


# S02: missing, unknown and rejected are different facts --------------------------------


def test_a_missing_entry_stays_unknown_however_long_it_takes(tmp_path: Path) -> None:
    venue = CrashVenue(_snap(server_time_ms=_bar(100.0)[1]), "before_send")
    store = _store(tmp_path)
    with pytest.raises(Crash):
        _entry_cycle(tmp_path, venue, store)
    store.close()
    store = _store(tmp_path)
    try:
        for hours in (0, 1, 24, 72):
            bar, now = _bar(100.0, hours * 60 + 1)
            venue.snap = dataclasses.replace(venue.snap, server_time_ms=now)
            _run(store, venue, bar, now)
            assert store.intents()[0].phase == "unknown"
        assert venue.market_ids == []
    finally:
        store.close()


def test_resolve_only_releases_what_the_exchange_says_is_absent(tmp_path: Path) -> None:
    venue = CrashVenue(_snap(server_time_ms=_bar(100.0)[1]), "before_send")
    store = _store(tmp_path)
    with pytest.raises(Crash):
        _entry_cycle(tmp_path, venue, store)
    try:
        held = store.intents()[0].client_id
        venue.orders[held] = {"status": "FILLED", "executedQty": "2.0", "orderId": 5}
        released, why = resolve_intent(store, venue, held)
        assert not released and "查得到" in why
        assert store.intents()[0].phase == "filled"
        assert resolve_intent(store, venue, "nope")[0] is False
    finally:
        store.close()
    store = _store(tmp_path / "second")
    try:
        store.insert_intent(
            Intent("en2", "enter", "unknown", "BUY", "1.0", False, False, "", "demo", NOW - 5_000, "", 1, False)
        )
        released, _why = resolve_intent(store, FakeVenue(_fresh()), "en2")
        assert released and store.intents()[0].phase == "canceled"
    finally:
        store.close()


def test_a_cancel_that_finds_nothing_is_not_an_expiry(tmp_path: Path) -> None:
    store = _store(tmp_path)

    class Gone(FakeVenue):
        def cancel_order(self, client_id: str) -> dict[str, object]:
            return {"code": -2013, "msg": "Order does not exist."}

    try:
        store.insert_intent(
            Intent("en3", "enter", "acked", "BUY", "1.0", False, False, "", "demo", NOW - 5_000, "", 1, False)
        )
        from btc_perp.model import Command

        alerts: list[str] = []
        _cancel(store, Gone(_fresh()), Command("cancel_order", "en3"), [], alerts)
        assert store.intents()[0].phase == "unknown"
        assert any("查不到" in item for item in alerts)
    finally:
        store.close()


@pytest.mark.parametrize(
    ("body", "cancel", "phase"),
    [
        ({"code": -2013, "msg": "Order does not exist."}, False, "missing"),
        ({"code": -2010, "msg": "rejected"}, False, "rejected"),
        ({"code": -4164, "msg": "min notional"}, False, "rejected"),
        ({"code": -4116, "msg": "ClientOrderId is duplicated."}, False, "unknown"),
        ({"code": -9999, "msg": "brand new"}, False, "unknown"),
        ({"code": "weird"}, False, "unknown"),
        ({"algoStatus": "FINISHED"}, False, "unknown"),
        ({"algoStatus": "FINISHED", "actualOrderId": "88"}, False, "filled"),
        ({"status": "CANCELED", "executedQty": "0.5"}, False, "filled"),
        ({"status": "EXPIRED", "executedQty": "0"}, False, "expired"),
        ({"status": "FILLED", "executedQty": "1", "orderId": 4}, False, "filled"),
        ({"code": 200, "msg": "success"}, True, "canceled"),
        ({"garbage": 1}, False, "unknown"),
    ],
)
def test_the_answer_classifier(body: dict[str, object], cancel: bool, phase: str) -> None:
    assert classify(body, cancel=cancel).phase == phase


# S03: who moved the position -----------------------------------------------------------


def _held(side: int = 1, qty: float = 2.0) -> Book:
    return _book(side=side, qty=qty, entry=100.0, units=1)


def test_a_position_move_is_bounded_by_what_our_own_orders_could_do() -> None:
    snap = _fresh(position_qty=-3.0, entry_price=100.0)
    inflight = [Intent("ad1", "add", "sent", "BUY", "1.0", False, False, "", "demo", NOW - 1, "", 1, False)]
    assert freeze_for_manual(_held(1, 1.0), snap, inflight) != ""
    plausible = _fresh(position_qty=3.0, entry_price=100.0)
    assert freeze_for_manual(_held(1, 2.0), plausible, inflight) == ""


def test_our_own_stop_firing_is_not_a_manual_change() -> None:
    fired = Intent("st1", "stop", "filled", "SELL", "", False, True, "97", "demo", NOW - 9_000, "", 1, False, "55")
    flat = _fresh(position_qty=0.0)
    assert freeze_for_manual(_held(1, 2.0), flat, [fired], frozenset({"55"}), 0) == ""
    assert position_bounds(_held(1, 2.0), [fired])[0] == pytest.approx(-2.0)


def test_a_flat_and_reopen_of_the_same_size_by_hand_is_caught_by_fill_identity() -> None:
    snap = dataclasses.replace(
        _fresh(position_qty=2.0, entry_price=101.0),
        trades=(Trade(11, "manual-1", "SELL", 2.0, NOW - 2_000), Trade(12, "manual-2", "BUY", 2.0, NOW - 1_000)),
    )
    assert foreign_trades(snap, [], frozenset(), 0) == [11, 12]
    reason = freeze_for_manual(_held(1, 2.0), snap, [], frozenset(), 0)
    assert "不是本程序订单" in reason


def test_our_own_fills_and_the_cursor_do_not_freeze() -> None:
    snap = dataclasses.replace(
        _fresh(position_qty=2.0), trades=(Trade(5, "77", "BUY", 2.0, NOW - 1_000), Trade(6, "78", "SELL", 1.0, NOW))
    )
    assert foreign_trades(snap, [], frozenset({"77"}), 5) == [6]
    assert foreign_trades(snap, [], frozenset({"77", "78"}), 0) == []
    assert foreign_trades(snap, [], frozenset(), 6) == []


# S04: protection -----------------------------------------------------------------------


def test_both_legs_must_be_placeable_before_an_entry_is_sent(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    tight = dataclasses.replace(_snap().filters, max_price=150.0)  # the 10x take is outside the band
    venue = FakeVenue(_snap(server_time_ms=now, filters=tight))
    store = _store(tmp_path)
    try:
        report = _run(store, venue, bar, now)
        assert venue.market_ids == [] and venue.algo_ids == []
        assert any("预检" in item for item in report.alerts)
    finally:
        store.close()


def test_stop_goes_first_and_take_waits_until_the_stop_is_confirmed(tmp_path: Path) -> None:
    class StopTimesOut(FakeVenue):
        def place_algo(self, **kwargs: object) -> dict[str, object]:
            if kwargs["order_type"] == "STOP_MARKET":
                self.algo_ids.append(str(kwargs["client_id"]))
                raise UnknownExecution("timeout")
            return super().place_algo(**kwargs)  # type: ignore[arg-type]

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


def test_a_protection_that_is_not_ours_is_never_reused() -> None:
    foreign = AlgoOrder("theirs", "STOP_MARKET", "SELL", 96.8, True, False, 0.0, "NEW", "CONTRACT_PRICE")
    snap = _fresh(position_qty=2.0, entry_price=100.0, algos=(foreign,))
    commands, swaps = plan_protection(snap, {}, stop_price=96.8, take_price=1000.0, known={"st1"})
    assert [command.order_type for command in commands] == ["STOP_MARKET", "TAKE_PROFIT_MARKET"]
    assert "stop_id" not in swaps


def test_protection_needs_both_legs_and_allows_several_valid_ones() -> None:
    snap = _covered()
    assert protections_cover(snap)[0]
    only_stop = dataclasses.replace(snap, algos=snap.algos[:1])
    assert not protections_cover(only_stop)[0]
    extra = AlgoOrder("st2", "STOP_MARKET", "SELL", 95.0, True, False, 0.0, "NEW", "CONTRACT_PRICE")
    assert protections_cover(dataclasses.replace(snap, algos=(*snap.algos, extra)))[0]


# S05 / S06: strict completion and exits ------------------------------------------------


def test_flatten_reports_a_foreign_order_instead_of_a_clean_account(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    theirs = RestingOrder("theirs", "BUY", "LIMIT", 1.0, 0.0, False, "NEW", 90.0)
    venue = FakeVenue(_covered(2.0))
    venue.snap = dataclasses.replace(venue.snap, server_time_ms=now, orders=(theirs,))
    store = _store(tmp_path)
    try:
        report = _run(store, venue, bar, now, mode="flatten")
        assert report.position_qty == 0.0
        assert not report.settled
        assert any("外来订单" in item and "theirs" in item for item in report.remaining)
    finally:
        store.close()


def test_flatten_settles_when_only_our_things_were_there(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(dataclasses.replace(_covered(2.0), server_time_ms=now))
    store = _store(tmp_path)
    try:
        for name, action in (("st1", "stop"), ("tp1", "take")):
            store.insert_intent(
                Intent(name, action, "acked", "SELL", "2.0", True, False, "", "demo", now - 1_000, "", 1, True)
            )
        report = _run(store, venue, bar, now, mode="flatten")
        assert report.settled and report.remaining == ()
        assert not any(algo.status == "NEW" for algo in venue.snap.algos)
    finally:
        store.close()


def test_stop_leaves_a_covered_position_settled_and_names_what_is_open(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(dataclasses.replace(_covered(2.0), server_time_ms=now))
    store = _store(tmp_path)
    try:
        store.insert_intent(
            Intent("en5", "enter", "unknown", "BUY", "1.0", False, False, "", "demo", now - 1_000, "", 1, False)
        )
        report = _run(store, venue, bar, now, mode="stop")
        assert not report.settled
        assert any("en5" in item for item in report.remaining)
    finally:
        store.close()


def test_a_control_request_from_another_environment_is_ignored(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _store(tmp_path)
    try:
        (tmp_path / "stop.request").write_text(json.dumps({"environment": "prod"}))
        report = _run(store, venue, bar, now)
        assert report.mode == "run"
        assert any("另一个环境" in item for item in report.alerts)
        assert len(venue.market_ids) == 1
        (tmp_path / "stop.request").write_text(json.dumps({"environment": "demo"}))
        again = _run(store, venue, bar, now)
        assert again.mode == "stop"
    finally:
        store.close()


def test_resume_removes_only_the_requests_of_its_own_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from btc_perp.__main__ import _resume

    (tmp_path / "stop.request").write_text(json.dumps({"environment": "demo"}))
    (tmp_path / "flatten.request").write_text(json.dumps({"environment": "prod"}))
    assert _resume(tmp_path, "demo") == 0
    assert not (tmp_path / "stop.request").exists()
    assert (tmp_path / "flatten.request").exists()
    assert "不解除" in capsys.readouterr().out


def test_resume_does_not_touch_account_freezes(tmp_path: Path) -> None:
    from btc_perp.__main__ import _resume

    store = _store(tmp_path)
    try:
        book = _book(entries_frozen=True, freeze_reason="发现过资金划转")
        book.swaps["flow_frozen"] = "1"
        store.save_book(book)
    finally:
        store.close()
    (tmp_path / "stop.request").write_text("{}")
    _resume(tmp_path, "demo")
    store = _store(tmp_path)
    try:
        kept = store.load_book()
        assert kept.entries_frozen and kept.swaps["flow_frozen"] == "1"
    finally:
        store.close()


def test_stop_and_flatten_never_wait_for_strategy_klines(tmp_path: Path) -> None:
    from btc_perp.__main__ import _one_cycle

    class Client(FakeVenue):
        def klines(self, *_a: object, **_k: object) -> list[object]:
            raise AssertionError("stop and flatten must not read strategy klines")

    store = _store(tmp_path)
    try:
        found = argparse.Namespace(environment="demo", max_notional_usdt=200.0, fx=0.0, dry_run=False)
        client = Client(dataclasses.replace(_covered(2.0), server_time_ms=NOW))
        client.read_ms = NOW
        for mode in ("stop", "flatten", "check"):
            _one_cycle(found, store, client, None, load_config(), Limits(None, None, None, None), mode, NOW)  # type: ignore[arg-type]
    finally:
        store.close()


# S07: account scope --------------------------------------------------------------------


def test_the_state_follows_the_uid_not_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARQUANT_LOCK_DIR", str(tmp_path / "locks"))
    first = _store(tmp_path / "a")
    first.bind_credential("key-one", "1001")
    first.close()
    rotated = _store(tmp_path / "a")
    try:
        rotated.bind_credential("key-two", "1001")
        assert rotated.get_json("account")["id"] == "uid:1001"  # type: ignore[index]
        assert len(rotated.get_json("account")["keys"]) == 2  # type: ignore[index]
    finally:
        rotated.close()
    other = _store(tmp_path / "a")
    try:
        with pytest.raises(RuntimeError, match="另一个账户 UID"):
            other.bind_credential("key-two", "2002")
        with pytest.raises(RuntimeError, match="没有见过"):
            other.bind_credential("key-three", "")
    finally:
        other.close()


def test_two_directories_cannot_drive_one_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARQUANT_LOCK_DIR", str(tmp_path / "locks"))
    one = _store(tmp_path / "a")
    two = _store(tmp_path / "b")
    try:
        one.bind_credential("k", "1001")
        with pytest.raises(RuntimeError, match="同一账户"):
            two.bind_credential("k2", "1001")
    finally:
        one.close()
        two.close()


def test_auto_add_margin_must_be_confirmed_off() -> None:
    dual = {"dualSidePosition": False}
    for flag, off in (("false", True), ("true", False), (None, False)):
        row = dict(POSITION[0])
        if flag is not None:
            row["isAutoAddMargin"] = flag
        snap = _snapshot_from(1, INFO, ACCOUNT, dual, {"raw": []}, {"raw": []}, {"raw": [row]})  # type: ignore[arg-type]
        assert snap.known and snap.auto_add_margin_off is off
        if not off:
            assert "自动追加保证金" in account_problems(snap, True)


def test_the_production_uid_check() -> None:
    class Spot:
        def __init__(self, status: int, payload: dict[str, object]) -> None:
            self.answer = (status, json.dumps(payload).encode())

        def request(self, *_a: object) -> tuple[int, bytes]:
            return self.answer

    assert prod_uid_block("k", "s", Spot(200, {"uid": 1001}), "1001", now_ms=1) == ""  # type: ignore[arg-type]
    assert "不一致" in prod_uid_block("k", "s", Spot(200, {"uid": 9}), "1001", now_ms=1)  # type: ignore[arg-type]
    assert "必须设置" in prod_uid_block("k", "s", Spot(200, {"uid": 1001}), "", now_ms=1)  # type: ignore[arg-type]
    assert "读不到" in prod_uid_block("k", "s", Spot(401, {"code": -2015}), "1001", now_ms=1)  # type: ignore[arg-type]


# S08: input validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("stop", float("nan")),
        ("stop", float("inf")),
        ("stop", 1.5),
        ("stop", True),
        ("entry_hours", 0),
        ("entry_hours", 9999),
        ("entry_hours", 5.5),
        ("dd_flat", 1.0),
        ("risk", -0.1),
        ("max_units", 0),
        ("leverage", 20.0),
        ("stop", 0.06),
    ],
)
def test_the_config_refuses_bad_values(key: str, value: object, tmp_path: Path) -> None:
    import yaml

    from btc_perp.config import DEFAULT_PATH

    raw = yaml.safe_load(DEFAULT_PATH.read_text())
    raw[key] = value
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_config(path)


def _hour(start: int, index: int, high: float = 10.0, low: float = 9.0) -> list[object]:
    open_ms = start + index * 3_600_000
    return [open_ms, "1", str(high), str(low), "1", "1", open_ms + 3_599_999, "1"]


def test_hour_rows_refuse_gaps_duplicates_nan_and_misalignment() -> None:
    start = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000
    now = start + 10 * 3_600_000
    good = [_hour(start, i) for i in range(4)]
    assert hour_rows_from_klines(good, now) is not None
    assert hour_rows_from_klines([good[0], good[2], good[3]], now) is None
    assert hour_rows_from_klines([good[0], good[1], good[1]], now) is None
    assert hour_rows_from_klines([good[1], good[0]], now) is None
    assert hour_rows_from_klines([_hour(start, 0, high=math.nan)], now) is None
    assert hour_rows_from_klines([[start + 5, "1", "2", "1", "1", "1", start + 3_600_004, "1"]], now) is None
    assert hour_rows_from_klines("nope", now) is None
    assert hour_rows_from_klines([], now) is None


def test_minute_bars_with_nan_or_off_boundary_time_are_refused() -> None:
    now = 1_700_000_100_000
    open_ms = now - now % 60_000 - 60_000
    assert inspect_bars((MinuteBar(open_ms, 1, 1, 1, 1, 1, True),), now, 0).fresh
    assert not inspect_bars((MinuteBar(open_ms, math.nan, 1, 1, 1, 1, True),), now, 0).fresh
    assert not inspect_bars((MinuteBar(open_ms + 7, 1, 1, 1, 1, 1, True),), now, 0).fresh


def test_a_gap_in_the_hourly_series_gives_no_new_signal(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _store(tmp_path)
    try:
        report = _run(store, venue, bar, now, channels=None, hour_rows=None)
        assert venue.market_ids == [] and report.position_qty == 0
    finally:
        store.close()


def test_lot_filters_that_disagree_make_the_snapshot_unknown() -> None:
    info = json.loads(json.dumps(INFO))
    filters = info["symbols"][0]["filters"]
    filters[1] = {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.0015", "minQty": "0.001", "maxQty": "120"}
    dual = {"dualSidePosition": False}
    snap = _snapshot_from(1, info, ACCOUNT, dual, {"raw": []}, {"raw": []}, {"raw": POSITION})  # type: ignore[arg-type]
    assert not snap.known


# S09: snapshot consistency -------------------------------------------------------------


def test_an_account_that_moves_while_it_is_read_is_not_trusted() -> None:
    moving = [
        (200, [{**POSITION[0], "positionAmt": "0"}]),
        (200, [{**POSITION[0], "positionAmt": "0.5"}]),
    ]
    routes = _routes(**{"/fapi/v2/positionRisk": moving})
    client, _transport = _client(routes)
    snap = client.snapshot()
    assert isinstance(snap.known, bool)
    stable, _t = _client(_routes())
    assert stable.snapshot().known


# S10: one account basis ----------------------------------------------------------------


def test_a_transfer_freezes_new_risk_until_rearm(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _store(tmp_path)
    try:
        _run(store, venue, bar, now, bars=())
        bar2, now2 = _bar(100.0, 1)
        venue.snap = dataclasses.replace(venue.snap, income=(Income("TRANSFER", 500.0, now + 1),), server_time_ms=now2)
        report = _run(store, venue, bar2, now2)
        assert report.frozen and "资金划转" in report.reason
        assert venue.market_ids == []
        again = _run(store, venue, bar2, now2)
        assert again.frozen
        venue.snap = dataclasses.replace(venue.snap, income=())
        rearm = _run(store, venue, bar2, now2, mode="rearm", bars=())
        assert rearm.settled
        after = _run(store, venue, bar2, now2)
        assert not after.frozen
    finally:
        store.close()


def test_rearm_refuses_with_a_resting_order_or_an_open_intent_and_keeps_the_performance_peak(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _store(tmp_path)
    try:
        book = _book(dd_locked=True)
        book.swaps["perf_peak"] = "90000.0"
        store.save_book(book)
        venue.snap = dataclasses.replace(
            venue.snap, orders=(RestingOrder("en1", "BUY", "LIMIT", 1.0, 0.0, False, "NEW", 90.0),)
        )
        assert not _run(store, venue, bar, now, mode="rearm", bars=()).settled
        venue.snap = dataclasses.replace(venue.snap, orders=())
        _unknown_entry(store)
        assert not _run(store, venue, bar, now, mode="rearm", bars=()).settled
        store.mark_intent("en1", "canceled")
        done = _run(store, venue, bar, now, mode="rearm", bars=())
        assert done.settled
        assert float(store.load_book().swaps["perf_peak"]) >= 90_000.0
    finally:
        store.close()


# S11: time attribution -----------------------------------------------------------------


def test_the_fill_minute_is_not_counted_as_held(tmp_path: Path) -> None:
    from btc_perp.bars import BarStatus
    from btc_perp.runner import _walk_bars

    store = _store(tmp_path)
    try:
        since = NOW - 5 * 60_000 + 20_000
        book = _book(side=1, qty=2.0, entry=100.0, units=1, extreme=100.0, stop=96.8)
        book.swaps["pos_since_ms"] = str(since)
        fill_minute = (since // 60_000) * 60_000
        bars = tuple(MinuteBar(fill_minute + k * 60_000, 100.0, 120.0 - k, 99.0, 100.0, 1e6, True) for k in range(3))
        status = BarStatus(True, "", bars, bars[-1].open_ms)
        snap = _covered(2.0)
        _walk_bars(
            book, snap, status, (1e9, -1e9, 1e9, -1e9, 0), None, load_config(), 7.0, 200.0, NOW, store,
            FakeVenue(snap), _ctx(), [], [], [], True,
        )  # fmt: skip
        assert book.extreme == pytest.approx(119.0), "the fill minute's 120 high is before the position was held"
    finally:
        store.close()


def test_a_backlog_minute_does_not_open_risk(tmp_path: Path) -> None:
    open_ms, _now = _clock(0)
    bar = MinuteBar(open_ms, 100.0, 100.0, 100.0, 100.0, 1e6, True)
    late = open_ms + 60_000 + 5 * 60_000
    venue = FakeVenue(_snap(server_time_ms=late))
    store = _store(tmp_path)
    try:
        _run(store, venue, bar, late, bars=(bar,))
        assert venue.market_ids == []
    finally:
        store.close()


# S13: persistence ----------------------------------------------------------------------


def test_a_book_that_reads_back_as_nonsense_stops_new_risk_and_is_not_a_new_account(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._db.execute("update kv set value=? where key='book'", ('{"side":3,"qty":NaN}',))
    store._db.execute("insert or ignore into kv(key, value) values('book', ?)", ('{"side":3,"qty":NaN}',))
    store._db.commit()
    store.close()
    with pytest.raises(RuntimeError, match="策略记忆"):
        _store(tmp_path)
    fresh = _store(tmp_path / "other")
    try:
        assert fresh.load_book().side == 0
    finally:
        fresh.close()


def test_record_send_is_one_transaction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        intent = Intent("en7", "enter", "sent", "BUY", "1.0", False, False, "", "demo", NOW, "", 1, False)
        book = _book()
        book.qty = float("nan")
        with pytest.raises(ValueError, match=r"not JSON compliant"):
            store.record_send(intent, book)
        assert store.intents() == []
        good = _book()
        store.record_send(intent, good)
        assert [item.client_id for item in store.intents()] == ["en7"]
        assert store.load_book().close_peak_cny == 70_000.0
    finally:
        store.close()


def test_backups_are_dated_and_kept_and_the_journal_keeps_several_files(tmp_path: Path) -> None:
    import btc_perp.store as store_module

    store = _store(tmp_path)
    try:
        assert list((tmp_path / "backups").glob("account-*.sqlite"))
        assert store.restore_latest_backup() is not None
        old = store_module.JOURNAL_MAX_BYTES
        store_module.JOURNAL_MAX_BYTES = 200
        try:
            for index in range(40):
                store.append_journal({"row": index, "pad": "x" * 150})
        finally:
            store_module.JOURNAL_MAX_BYTES = old
        rotated = sorted(path.name for path in tmp_path.glob("journal.jsonl.*"))
        assert len(rotated) >= 3
    finally:
        store.close()


def test_a_changed_config_digest_is_visible() -> None:
    from btc_perp.__main__ import _config_digest

    cfg = load_config()
    limits = Limits(None, None, None, None)
    base = _config_digest(cfg, limits, 200.0)
    assert base == _config_digest(cfg, limits, 200.0)
    assert base != _config_digest(dataclasses.replace(cfg, risk=0.04), limits, 200.0)
    assert base != _config_digest(cfg, limits, 300.0)


# S15: reports --------------------------------------------------------------------------


def test_a_failed_run_never_replaces_the_formal_report(tmp_path: Path) -> None:
    pointer = tmp_path / "reports" / "r.json"
    good = {
        "verified": True,
        "value": 1,
        "completion": completion(data_validated=True, path_complete=True, economic_pass=False),
    }
    where = publish(pointer, good)
    assert where == pointer
    first = json.loads(pointer.read_text())
    assert first["run_id"] and first["completion"]["execution_closed"] is False
    bad = {"verified": False, "value": 2}
    assert publish(pointer, bad) == pointer.with_suffix(".unverified.json")
    assert json.loads(pointer.read_text())["value"] == 1
    half = {
        "verified": True,
        "value": 3,
        "completion": completion(data_validated=True, path_complete=False, economic_pass=False),
    }
    assert publish(pointer, half) == pointer.with_suffix(".unverified.json")
    assert json.loads(pointer.read_text())["value"] == 1
    runs = list((tmp_path / "reports" / "runs").glob("r-*.json"))
    assert len(runs) == 3 and len({path.name for path in runs}) == 3
