"""Ownership, protection replacement, and conservative recovery."""
from __future__ import annotations

import dataclasses
from pathlib import Path
import pytest
from btc_perp.machine import promote_protection
from btc_perp.model import AlgoOrder, Book, Filters, Intent, Snapshot, Trade
from btc_perp.runner import _rearm
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
    return Snapshot(**fields)


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


def test_rearm_refuses_unreadable_fills_and_unowned_flat_roundtrip(tmp_path: Path) -> None:
    with Store(tmp_path, "demo") as store:
        book = Book(peak_equity_cny=20_000, close_peak_cny=20_000, swaps={"trade_cursor": "0"})
        assert not _rearm(store, book, snap(recent_trades_ok=False), 1.0, [], False)
        assert not _rearm(store, book, snap(funding_ok=False), 1.0, [], False)
        trades = (Trade(1, "external", "BUY", 1, NOW - 100), Trade(2, "external", "SELL", 1, NOW))
        assert not _rearm(store, book, snap(trades=trades), 1.0, [], False)
        assert book.close_peak_cny == 20_000
