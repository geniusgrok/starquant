"""Small account/clock counterexamples behind the current safety contract."""

from __future__ import annotations

import dataclasses
import datetime as dt
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from btc_perp.binance_client import _state_key
from btc_perp.causal import validate_minutes
from btc_perp.config import load_config
from btc_perp.machine import foreign_ids, freeze_for_manual, promote_protection
from btc_perp.model import AlgoOrder, Book, Filters, Intent, Limits, RestingOrder, Snapshot, Trade
from btc_perp.runner import (
    EntryContext,
    Outcome,
    _act,
    _coverage_problem,
    _entry_gate,
    _own_remaining,
    _rearm,
    _reconcile,
    _record_outcome,
    _sync_book,
)
from btc_perp.store import Store

NOW = 1_700_000_000_000


def snap(**changes: object) -> Snapshot:
    fields = {
        "known": True,
        "reason": "",
        "position_qty": 0.0,
        "entry_price": 0.0,
        "wallet_usdt": 10000.0,
        "available_usdt": 10000.0,
        "mark_price": 100.0,
        "last_price": 100.0,
        "liquidation_price": 0.0,
        "one_way": True,
        "isolated": True,
        "leverage": 20,
        "symbol_status": "TRADING",
        "server_time_ms": NOW,
        "can_trade": True,
        "fee_taker": 0.0004,
        "filters": Filters(0.1, 0.001, 0.001, 100.0, 0.1, 1_000_000.0),
        "brackets_ok": True,
        "recent_trades_ok": True,
        "funding_ok": True,
        "auto_add_margin_off": True,
        "read_ms": NOW,
    }
    fields.update(changes)
    return Snapshot(**fields)  # type: ignore[arg-type]


def test_unknown_old_protection_blocks_new_risk_and_stop_completion(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("st_old", "stop", "unknown", "SELL", "", False, True, "96.8", "demo", NOW))
        current = snap()
        ctx = EntryContext("demo", Limits(None, None, None, None), 200, 200, False, lambda: NOW)
        assert "保护" in _entry_gate(store, current, Book(), load_config(), ctx, NOW)
        assert "st_old" in "|".join(_own_remaining(store, current, entries_only=True))
        store.mark_intent("st_old", "canceled", absorbed=True)
        assert _entry_gate(store, current, Book(), load_config(), ctx, NOW) == ""


def test_unknown_old_protection_survives_stop_and_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_forward import FakeVenue, _bar, _run, _snap

    from btc_perp.model import Action

    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("st_old", "stop", "unknown", "SELL", "", False, True, "90", "demo", now, attempts=2))
        stopped = _run(store, venue, bar, now, mode="stop")
        assert not stopped.settled and "st_old" in "|".join(stopped.remaining)
        monkeypatch.setattr("btc_perp.runner.decide", lambda *_a, **_k: Action("enter", 1, 2.0))
        _run(store, venue, bar, now)
        assert venue.market_ids == []


def test_healthy_resting_protections_allow_an_add(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        for kind in ("stop", "take"):
            store.insert_intent(
                Intent(kind, kind, "acked", "SELL", "", False, True, "90" if kind == "stop" else "200", "demo", NOW)
            )
        current = snap(
            position_qty=1.0,
            entry_price=100.0,
            algos=(
                AlgoOrder("stop", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE"),
                AlgoOrder("take", "TAKE_PROFIT_MARKET", "SELL", 200, True, False, 0, "NEW", "CONTRACT_PRICE"),
            ),
        )
        book = Book(side=1, qty=1, entry=100)
        ctx = EntryContext("demo", Limits(None, None, None, None), 200, 200, False, lambda: NOW)
        assert _entry_gate(store, current, book, load_config(), ctx, NOW) == ""


def test_flat_account_cannot_reenter_before_old_live_protection_is_cleared(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("st_old", "stop", "acked", "SELL", "", False, True, "90", "demo", NOW))
        current = snap(algos=(AlgoOrder("st_old", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE"),))
        ctx = EntryContext("demo", Limits(None, None, None, None), 200, 200, False, lambda: NOW)
        assert "保护" in _entry_gate(store, current, Book(), load_config(), ctx, NOW)
        assert "st_old" in "|".join(_own_remaining(store, current, entries_only=True))


def test_child_fill_and_unabsorbed_marker_are_one_durable_update(tmp_path: Path) -> None:
    store = Store(tmp_path, "demo")
    store.insert_intent(Intent("st", "stop", "acked", "SELL", "", False, True, "90", "demo", NOW))
    _record_outcome(store, store.intents()[0], Outcome("filled", 1.0, "77"))
    store.close()
    with Store(tmp_path, "demo") as restored:
        item = restored.intents()[0]
        assert (item.phase, item.absorbed, item.order_id, item.executed) == ("filled", False, "77", "1.00000000")
        assert (
            freeze_for_manual(
                Book(side=1, qty=2),
                snap(position_qty=1.0, entry_price=100.0, trades=(Trade(1, "77", "SELL", 1, NOW),)),
                restored.intents(),
                restored.own_order_ids(),
                0,
            )
            == ""
        )


def test_foreign_position_is_not_an_automatic_exit(tmp_path: Path) -> None:
    from btc_perp.model import Action

    class NoWrite:
        def place_market(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("foreign position was traded")

    with Store(tmp_path, "demo") as store:
        book = Book(side=1, qty=1, entry=100)
        ctx = EntryContext("demo", Limits(None, None, None, None), 200, 200, False, lambda: NOW)
        message = _act(
            Action("exit"),
            store,
            NoWrite(),
            snap(position_qty=2, entry_price=100),
            book,
            load_config(),
            ctx,
            [],
            [],
            [],
            False,
            NOW,
            NOW - 60_000,
        )  # type: ignore[arg-type]
        assert "归属未确认" in message


def test_foreign_position_does_not_advance_strategy_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_forward import FakeVenue, _bar, _run, _snap

    from btc_perp.model import Action

    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, position_qty=2, entry_price=100))
    with Store(tmp_path, "demo") as store:
        store.save_book(Book(side=1, qty=1, entry=100, extreme=100, stop=90))
        monkeypatch.setattr("btc_perp.runner.decide", lambda *_a, **_k: Action("exit"))
        result = _run(store, venue, bar, now)
        actual = store.load_book()
        assert result.frozen and not venue.market_ids
        assert actual.cursor_ms == 0 and actual.extreme == 100 and actual.stop == 90


@pytest.mark.parametrize("mode", ["run", "stop"])
def test_foreign_fill_arriving_during_cycle_cannot_trigger_old_stop_exit(tmp_path: Path, mode: str) -> None:
    from test_forward import FakeVenue, _bar, _run, _snap

    bar, now = _bar(100.0)

    class ChangingVenue(FakeVenue):
        reads = 0

        def snapshot(self) -> Snapshot:
            self.reads += 1
            if self.reads == 2:
                self.snap = dataclasses.replace(
                    self.snap,
                    position_qty=2,
                    trades=(Trade(1, "external", "BUY", 1, now),),
                )
            return super().snapshot()

    venue = ChangingVenue(_snap(server_time_ms=now, position_qty=1, entry_price=100))
    with Store(tmp_path, "demo") as store:
        store.save_book(Book(side=1, qty=1, entry=100, stop=110, extreme=100, swaps={"trade_cursor": "0"}))
        result = _run(store, venue, bar, now, mode=mode)
        assert result.position_qty == 2
        assert venue.market_ids == []
        if mode == "run":
            assert store.load_book().cursor_ms == 0


def test_stop_does_not_call_foreign_position_settled_just_because_close_all_orders_cover_it(tmp_path: Path) -> None:
    from test_forward import FakeVenue, _bar, _run, _snap

    bar, now = _bar(100.0)
    stops = (
        AlgoOrder("st_own", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE"),
        AlgoOrder("tp_own", "TAKE_PROFIT_MARKET", "SELL", 1000, True, False, 0, "NEW", "CONTRACT_PRICE"),
    )
    current = _snap(
        server_time_ms=now,
        position_qty=2,
        entry_price=100,
        trades=(Trade(1, "external", "BUY", 1, now),),
        algos=stops,
    )
    venue = FakeVenue(current)
    with Store(tmp_path, "demo") as store:
        store.save_book(Book(side=1, qty=1, entry=100, swaps={"trade_cursor": "0"}))
        for client_id, action, trigger in (("st_own", "stop", "90"), ("tp_own", "take", "1000")):
            store.insert_intent(Intent(client_id, action, "acked", "SELL", "", False, True, trigger, "demo", now))
        result = _run(store, venue, bar, now, mode="stop")
        assert not result.settled
        assert any("归属未确认" in item for item in result.remaining)
        assert venue.market_ids == []


def test_stop_does_not_confirm_held_position_when_trade_history_is_unreadable(tmp_path: Path) -> None:
    from test_forward import FakeVenue, _bar, _run, _snap

    bar, now = _bar(100.0)
    current = _snap(
        server_time_ms=now,
        position_qty=1,
        entry_price=100,
        recent_trades_ok=False,
        algos=(
            AlgoOrder("st_own", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE"),
            AlgoOrder("tp_own", "TAKE_PROFIT_MARKET", "SELL", 1000, True, False, 0, "NEW", "CONTRACT_PRICE"),
        ),
    )
    with Store(tmp_path, "demo") as store:
        store.save_book(Book(side=1, qty=1, entry=100))
        for client_id, action, trigger in (("st_own", "stop", "90"), ("tp_own", "take", "1000")):
            store.insert_intent(Intent(client_id, action, "acked", "SELL", "", False, True, trigger, "demo", now))
        result = _run(store, FakeVenue(current), bar, now, mode="stop")
        assert not result.settled
        assert any("归属未确认" in item for item in result.remaining)


def test_old_reduce_is_not_resent_before_foreign_fill_is_checked(tmp_path: Path) -> None:
    class Venue:
        def query_order(self, _client_id: str) -> dict[str, object]:
            return {"code": -2013, "msg": "Order does not exist"}

        def place_market(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("旧减仓单平掉了外来持仓")

    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("rd_old", "reduce", "unknown", "SELL", "1", True, False, "", "demo", NOW))
        book = Book(side=1, qty=1, entry=100, swaps={"trade_cursor": "0"})
        current = snap(
            position_qty=1,
            entry_price=100,
            trades=(Trade(1, "external", "BUY", 1, NOW - 1), Trade(2, "external", "SELL", 1, NOW)),
        )
        alerts: list[str] = []
        _reconcile(store, Venue(), current, book, [], alerts, allow="all", now_ms=NOW, dry_run=False)  # type: ignore[arg-type]
        assert store.intents()[0].attempts == 1
        assert store.intents()[0].phase == "unknown"
        assert any("外来" in item or "不是本程序" in item for item in alerts)


def test_old_reduce_with_obsolete_qty_is_not_resent(tmp_path: Path) -> None:
    class Venue:
        def query_order(self, _client_id: str) -> dict[str, object]:
            return {"code": -2013, "msg": "Order does not exist"}

        def place_market(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("旧数量的减仓单被重放")

    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("rd_old", "reduce", "unknown", "SELL", "2", True, False, "", "demo", NOW))
        _reconcile(
            store,
            Venue(),
            snap(position_qty=1, entry_price=100),
            Book(side=1, qty=1, entry=100),
            [],
            [],
            allow="all",
            now_ms=NOW,
            dry_run=False,
        )  # type: ignore[arg-type]
        assert store.intents()[0].phase == "unknown" and store.intents()[0].attempts == 1


def test_old_protection_is_not_sent_to_flat_or_changed_position(tmp_path: Path) -> None:
    class Venue:
        def place_algo(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("旧 closePosition 条件单被重放")

    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("st_old", "stop", "planned", "SELL", "", False, True, "90", "demo", NOW))
        book = Book(side=1, qty=1, entry=100)
        for current in (snap(), snap(position_qty=-1, entry_price=100)):
            _reconcile(store, Venue(), current, book, [], [], allow="reduce", now_ms=NOW, dry_run=False)  # type: ignore[arg-type]
        assert store.intents()[0].phase == "planned"


def test_old_stop_with_crossed_trigger_is_not_replayed(tmp_path: Path) -> None:
    class Venue:
        def query_algo(self, _client_id: str) -> dict[str, object]:
            return {"code": -2013, "msg": "Order does not exist"}

        def place_algo(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("已越过触发价的旧止损被重放")

    with Store(tmp_path, "demo") as store:
        store.insert_intent(Intent("st_old", "stop", "unknown", "SELL", "", False, True, "90", "demo", NOW))
        book = Book(side=1, qty=1, entry=100)
        _reconcile(
            store,
            Venue(),
            snap(position_qty=1, entry_price=100, last_price=80),
            book,
            [],
            [],
            allow="reduce",
            now_ms=NOW,
            dry_run=False,
        )  # type: ignore[arg-type]
        assert store.intents()[0].attempts == 1
        assert store.intents()[0].phase == "unknown"


@pytest.mark.parametrize(
    "bad_leg",
    (
        {"side": "BUY"},
        {"working_type": "MARK_PRICE"},
        {"close_position": False},
        {"trigger_price": 94.0},
        {"qty": 0.5},
    ),
)
def test_bad_new_stop_never_retires_healthy_old_stop(bad_leg: dict[str, object]) -> None:
    old = AlgoOrder("st_old", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE")
    new = dataclasses.replace(
        AlgoOrder("st_new", "STOP_MARKET", "SELL", 95, True, False, 0, "NEW", "CONTRACT_PRICE"),
        **bad_leg,
    )
    current = snap(position_qty=1, entry_price=100, algos=(old, new))
    intents = [Intent("st_new", "stop", "acked", "SELL", "", False, True, "95", "demo", NOW)]
    commands, swaps, warnings = promote_protection(
        current,
        {"stop_id": "st_old", "stop_next": "st_new"},
        {"st_old", "st_new"},
        intents,
        stop_price=95,
        take_price=1000,
    )
    assert [item.client_id for item in commands] == ["st_new"]
    assert swaps["stop_id"] == "st_old" and swaps["stop_next"] == "st_new"
    assert warnings


def test_verified_new_stop_retires_old_stop() -> None:
    old = AlgoOrder("st_old", "STOP_MARKET", "SELL", 90, True, False, 0, "NEW", "CONTRACT_PRICE")
    new = AlgoOrder("st_new", "STOP_MARKET", "SELL", 95, True, False, 0, "NEW", "CONTRACT_PRICE")
    current = snap(position_qty=1, entry_price=100, algos=(old, new))
    intents = [Intent("st_new", "stop", "acked", "SELL", "", False, True, "95", "demo", NOW)]
    commands, swaps, warnings = promote_protection(
        current,
        {"stop_id": "st_old", "stop_next": "st_new"},
        {"st_old", "st_new"},
        intents,
        stop_price=95,
        take_price=1000,
    )
    assert [item.client_id for item in commands] == ["st_old"]
    assert swaps["stop_id"] == "st_new" and "stop_next" not in swaps and not warnings


def test_takeover_tracks_real_position_and_releases_without_resetting_peak(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        book = Book(side=1, qty=2, entry=100, units=1, manual=True, peak_equity_cny=20_000, close_peak_cny=20_000)
        current = snap(position_qty=1, entry_price=100)
        _sync_book(store, book, current, load_config(), NOW)
        assert book.qty == 1
        _sync_book(store, book, dataclasses.replace(current, position_qty=0, entry_price=0), load_config(), NOW)
        assert book.qty == 0
        alerts: list[str] = []
        assert _rearm(store, book, snap(), 1.0, alerts, False)
        assert not book.manual and book.close_peak_cny == 20_000


def test_known_native_child_does_not_adopt_a_different_order() -> None:
    current = snap(
        orders=(
            RestingOrder("other-client", "SELL", "MARKET", 1, 0.2, True, "PARTIALLY_FILLED", order_id="88"),
            RestingOrder("unknown", "SELL", "MARKET", 1, 0, True, "NEW", order_id="89"),
        )
    )
    assert foreign_ids(current, {"parent"}, {"88"}) == ["unknown"]


def test_snapshot_identity_ignores_price_only_but_catches_margin_and_position_change() -> None:
    position = {
        "symbol": "BTCUSDT",
        "positionAmt": "1",
        "entryPrice": "100",
        "isolatedWallet": "5",
        "isolatedMargin": "6",
        "marginType": "isolated",
        "leverage": "20",
        "markPrice": "101",
    }
    account = {"assets": [{"asset": "USDT", "walletBalance": "100"}]}
    original = _state_key({"raw": [position]}, {"raw": []}, {"raw": []}, account, None)
    price_only = {**position, "markPrice": "102", "isolatedMargin": "7"}
    assert _state_key({"raw": [price_only]}, {"raw": []}, {"raw": []}, account, None) == original
    assert (
        _state_key({"raw": [{**price_only, "isolatedWallet": "6"}]}, {"raw": []}, {"raw": []}, account, None)
        != original
    )
    assert _state_key({"raw": [{**position, "positionAmt": "2"}]}, {"raw": []}, {"raw": []}, account, None) != original


def test_research_window_and_nonfinite_bars_are_rejected() -> None:
    ts = np.array([0, 60_000], np.int64)
    prices = np.array([100.0, float("nan")])
    assert any("非有限" in reason for reason in validate_minutes(ts, prices, prices, prices, prices, prices))
    prices[:] = 100
    assert any(
        "冻结" in reason
        for reason in validate_minutes(ts, prices, prices, prices, prices, prices, official_window=True)
    )
    assert validate_minutes(ts + 1, prices, prices, prices, prices, prices)


def test_generalization_requires_valid_tapes_and_perpetual_funding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from btc_perp import tapes

    (tmp_path / "assets").mkdir()
    ts = np.arange(60, dtype=np.int64) * 60_000
    np.savez(
        tmp_path / "assets" / "eth_1m.npz",
        ts=ts,
        o=ts * 0 + 100,
        h=ts * 0 + 100,
        l=ts * 0 + 100,
        c=ts * 0 + 100,
        qv=ts * 0 + 1,
    )
    monkeypatch.setattr(tapes, "DATA", tmp_path)
    with pytest.raises(ValueError, match="资金费"):
        tapes.load_tape("eth")
    tape = tapes.Tape("eth", ts, *(np.ones(60) for _ in range(8)))
    tape.fx[0] = float("nan")
    problems = tapes.validate_tape(tape)
    assert any("窗口" in problem for problem in problems)
    assert any("汇率" in problem for problem in problems)


def test_uncovered_trade_or_income_history_stays_frozen() -> None:
    book = Book(swaps={"trade_seen_ms": str(NOW - 8 * 86_400_000), "income_cursor_ms": str(NOW)})
    assert "七天" in _coverage_problem(book, snap())
    book.swaps["trade_seen_ms"] = str(NOW - 1_000)
    rows = tuple(Trade(i, str(i), "BUY", 0.001, NOW - 100) for i in range(1000))
    assert "1000" in _coverage_problem(book, snap(trades=rows))


def test_takeover_tracks_position_but_does_not_erase_uncovered_history(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        marker = str(NOW - 8 * 86_400_000)
        book = Book(side=1, qty=2, entry=100, manual=True, swaps={"trade_seen_ms": marker, "trade_cursor": "12"})
        _sync_book(store, book, snap(position_qty=0), load_config(), NOW)
        assert book.qty == 0 and book.swaps["trade_seen_ms"] == marker and book.swaps["trade_cursor"] == "12"
        assert not _rearm(store, book, snap(), 1.0, [], False)


def test_rearm_refuses_unreadable_fills_and_unowned_flat_roundtrip(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        book = Book(peak_equity_cny=20_000, close_peak_cny=20_000, swaps={"trade_cursor": "0"})
        assert not _rearm(store, book, snap(recent_trades_ok=False), 1.0, [], False)
        assert not _rearm(store, book, snap(funding_ok=False), 1.0, [], False)
        trades = (Trade(1, "external", "BUY", 1, NOW - 100), Trade(2, "external", "SELL", 1, NOW))
        assert not _rearm(store, book, snap(trades=trades), 1.0, [], False)
        assert book.close_peak_cny == 20_000


def test_long_running_store_makes_a_consistent_backup_on_new_utc_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from btc_perp import store as storage

    day = [29]

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return dt.datetime(2026, 9, day[0], tzinfo=tz)

    monkeypatch.setattr(storage, "dt", SimpleNamespace(datetime=Clock, UTC=dt.UTC))
    with Store(tmp_path, "demo") as store:
        assert not list((tmp_path / "backups").glob("account-*.sqlite"))
        store.save_book(Book(peak_equity_cny=1234, close_peak_cny=1234))
        store.insert_intent(Intent("backup-id", "stop", "unknown", "SELL", "", False, True, "90", "demo", NOW))
        store.archive_if_due()
        day[0] = 30
        store.archive_if_due()
        store.archive_if_due()
        assert len(list((tmp_path / "backups").glob("account-*.sqlite"))) == 2
    with sqlite3.connect(tmp_path / "backups" / "account-20260930.sqlite") as backup:
        assert backup.execute("pragma quick_check").fetchone() == ("ok",)
        assert backup.execute("select client_id from intents").fetchone() == ("backup-id",)
        assert "1234" in backup.execute("select value from kv where key='book'").fetchone()[0]


def test_old_stop_only_during_bar_then_new_trail_eligible_next_bar() -> None:
    from scripts.frontier import initial_state, resume

    cfg = load_config()
    state = initial_state(1.0)
    for index, value in {
        0: 10000,
        1: 1,
        2: 1,
        3: 100,
        4: 5,
        5: 96.8,
        6: 110,
        7: 1,
        8: 100,
        10: 10000,
        11: 10000,
    }.items():
        state[index] = value
    o = np.array([110.0, 110.0])
    h = np.array([120.0, 120.0])
    low = np.array([99.0, 99.0])
    c = np.array([109.0, 109.0])
    arrays = (
        o,
        h,
        low,
        c,
        np.zeros(2),
        np.ones(2),
        np.full(2, np.inf),
        np.full(2, -np.inf),
        np.full(2, np.inf),
        np.full(2, -np.inf),
    )
    tail = (
        cfg.stop,
        cfg.trail,
        cfg.add_step,
        cfg.max_units,
        cfg.risk,
        cfg.dd_flat,
        cfg.iso_frac,
        cfg.cooldown_hours * 60,
        cfg.ratchet_gain,
        cfg.ratchet_trail,
        cfg.heat,
        cfg.flatten_ratio,
        cfg.entry_scale_below,
        cfg.entry_scale,
        np.zeros(2, np.int8),
        np.full(2, 1e9),
        np.empty(2),
        np.empty((2, 5)),
        1,
    )
    resume(state, 1, 2, *arrays, *tail)
    assert state[1] == 1 and state[5] > 96.8
    state[5] = 105  # A previously resting stop really does trigger on this bar.
    resume(state, 1, 2, *arrays, *tail)
    assert state[1] == 0
