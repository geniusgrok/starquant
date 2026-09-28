"""Drawdown lock visibility, rearm, and the stress inputs of the replay."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from test_forward import FakeVenue, _bar, _run, _snap

from btc_perp.causal import lockout
from btc_perp.config import load_config
from btc_perp.model import Book, Intent
from btc_perp.store import Store


def test_lockout_reports_a_flat_account_below_the_line() -> None:
    equity = np.array([10_000.0, 20_000.0, 9_000.0, 9_000.0, 9_000.0])
    side = np.array([0.0, 1.0, 1.0, 0.0, 0.0])
    days = np.array([1, 2, 3, 4, 5])
    found = lockout(equity, side, days, 0.47, 10_000.0)
    assert found["locked_at_end"] is True
    assert found["last_position_day"] == 3
    assert found["flat_days_at_end"] == pytest.approx(2 / 1440.0)


def test_lockout_is_not_set_while_a_position_is_open_or_above_the_line() -> None:
    days = np.arange(4)
    held = lockout(np.array([10.0, 20.0, 9.0, 9.0]), np.array([0.0, 1.0, 1.0, 1.0]), days, 0.47, 10.0)
    assert held["locked_at_end"] is False
    healthy = lockout(np.array([10.0, 20.0, 19.0, 19.0]), np.array([0.0, 1.0, 0.0, 0.0]), days, 0.47, 10.0)
    assert healthy["locked_at_end"] is False


def _locked_store(tmp: Path) -> Store:
    store = Store(tmp, "demo")
    book = Book()
    book.peak_equity_cny = 200_000.0
    book.close_peak_cny = 200_000.0
    book.swaps["peak_unit"] = "CNY"
    book.swaps["peak_fx"] = repr(7.0)
    store.save_book(book)
    return store


def test_a_locked_flat_account_says_so_and_does_not_enter(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _locked_store(tmp_path)
    try:
        report = _run(store, venue, bar, now)
        assert report.locked
        assert venue.market_ids == []
        assert any("rearm" in item for item in report.alerts)
    finally:
        store.close()


def test_rearm_moves_the_baseline_and_trading_resumes(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _locked_store(tmp_path)
    try:
        report = _run(store, venue, bar, now, mode="rearm", bars=())
        assert report.settled
        assert venue.market_ids == [] and venue.algo_ids == [] and venue.cancels == []
        book = store.load_book()
        assert book.close_peak_cny == pytest.approx(70_000.0)
        assert book.peak_equity_cny == pytest.approx(70_000.0)
        again = _run(store, venue, bar, now)
        assert not again.locked
        assert len(venue.market_ids) == 1
    finally:
        store.close()


def test_rearm_refuses_with_a_position_or_open_order(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    held = FakeVenue(_snap(server_time_ms=now, position_qty=1.0, entry_price=100.0))
    store = _locked_store(tmp_path / "held")
    try:
        assert not _run(store, held, bar, now, mode="rearm", bars=()).settled
        assert store.load_book().close_peak_cny == pytest.approx(200_000.0)
    finally:
        store.close()

    flat = FakeVenue(_snap(server_time_ms=now))
    store = _locked_store(tmp_path / "busy")
    store.insert_intent(Intent("en" + "0" * 20, "enter", "sent", "BUY", "1.000", False, False, "", "demo", now, ""))
    try:
        assert not _run(store, flat, bar, now, mode="rearm", bars=()).settled
    finally:
        store.close()


def test_rearm_dry_run_writes_nothing(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = _locked_store(tmp_path)
    try:
        report = _run(store, venue, bar, now, mode="rearm", bars=(), dry_run=True)
        assert not report.settled
        assert store.load_book().close_peak_cny == pytest.approx(200_000.0)
    finally:
        store.close()


def test_the_cli_wants_an_explicit_yes(capsys: pytest.CaptureFixture[str]) -> None:
    from btc_perp.__main__ import main

    assert main(["rearm", "--environment", "demo"]) == 2
    assert "--yes" in capsys.readouterr().out


def _tape() -> dict[str, np.ndarray]:
    opens = np.array([100.0, 100.0, 100.0, 100.0])
    closes = np.array([100.0, 100.0, 95.0, 95.0])
    highs = np.array([100.0, 100.0, 100.0, 95.0])
    lows = np.array([100.0, 100.0, 90.0, 95.0])
    return {
        "O": opens,
        "H": highs,
        "L": lows,
        "C": closes,
        "fund": np.zeros(4),
        "fx": np.full(4, 7.0),
        "hh": np.array([50.0, 1.0e9, 1.0e9, 1.0e9]),
        "ll": np.full(4, 1.0),
        "xh": np.full(4, 1.0e9),
        "xl": np.full(4, 1.0),
        "gate": np.ones(4, np.int8),
        "qv": np.empty(1),
    }


def _replay_tape(stop_extra: float, taker: float = 0.0) -> float:
    from scripts.frontier import initial_state, resume

    cfg = load_config()
    tape = _tape()
    state = initial_state(7.0)
    state[22] = stop_extra
    state[23] = taker
    return resume(
        state,
        0,
        4,
        tape["O"],
        tape["H"],
        tape["L"],
        tape["C"],
        tape["fund"],
        tape["fx"],
        tape["hh"],
        tape["ll"],
        tape["xh"],
        tape["xl"],
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
        tape["gate"],
        tape["qv"],
        np.empty(1),
        np.zeros((4, 5)),
        1,
    )[0]


def test_a_worse_stop_fill_and_a_higher_fee_cost_money_and_zero_changes_nothing() -> None:
    base = _replay_tape(0.0)
    assert _replay_tape(0.0, 0.0) == base
    assert _replay_tape(0.01) < base
    assert _replay_tape(0.0, 0.002) < base


def test_the_replay_reads_the_dataclass_fields_it_perturbs() -> None:
    cfg = load_config()
    names = {field.name for field in dataclasses.fields(cfg)}
    from btc_perp.robustness import NEIGHBOUR_FIELDS

    assert set(NEIGHBOUR_FIELDS) <= names
