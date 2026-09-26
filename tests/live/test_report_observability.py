"""M-007 and D-025: the daily report must not read 0.00% while the book is carrying margin.

Three separate blind spots the 2026-09-04 system check found, one test file:

* M-007's "peak margin usage" measured what a cycle's *new orders* asked for, not what the *held* book
  consumes, so it printed 0.00% on a day whose only margin-consuming order predated the evidence window
  while fifteen positions held 577 USDT of initial margin;
* the host clock was a full hour behind the venue and nothing in the report said so, although every
  timestamp in it - including the day it is named after - is the host's;
* CYSUSDT was traded live for sixteen hours with no 1h klines in the research store, so every backtest
  silently ran without it and only a log line nobody reads mentioned it.
"""

from __future__ import annotations

import json

from starquant_live.reconciler import Snapshot
from starquant_live.reports import clock_health, data_coverage, margin_and_rejections
from starquant_live.state import StateStore
from starquant_shared.types import AccountState, Position

LEVERAGE = {"BTCUSDT": 5, "ETHUSDT": 5}
# _day_of buckets a cycle by the bar its data carried, so these have to be real 2026-09-04 timestamps
BAR_0000Z, BAR_0100Z, BAR_0500Z = 1_788_480_000_000, 1_788_483_600_000, 1_788_498_000_000


def _snapshot(equity: float = 10_000.0) -> Snapshot:
    account = AccountState(
        wallet_balance=equity, available_balance=0.0, equity=equity, positions={}, margin_fields_reliable=False
    )
    positions = {
        "BTCUSDT": Position("BTCUSDT", qty=0.05, entry_price=60_000.0, mark_price=60_000.0),  # 3,000 notional
        "ETHUSDT": Position("ETHUSDT", qty=-0.50, entry_price=3_000.0, mark_price=3_000.0),  # -1,500 notional
    }
    return Snapshot(account=account, positions=positions, prices={"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0})


def test_standing_margin_is_measured_from_positions_not_from_the_venues_broken_field() -> None:
    snapshot = _snapshot()
    # 4,500 gross at 5x = 900 initial margin on 10,000 equity
    assert snapshot.initial_margin(LEVERAGE) == 900.0
    assert snapshot.margin_usage(LEVERAGE) == 0.09
    # the leverage the loop set wins over the venue's own field, which reads 0 on this venue
    assert snapshot.initial_margin({}, default_leverage=1) == 4_500.0
    assert Snapshot(account=AccountState(0.0, 0.0, 0.0, {}), positions={}, prices={}).margin_usage() == 0.0


def _write_cycles(tmp_path, rows: list[dict]) -> StateStore:
    store = StateStore(tmp_path)
    store.cycles_path.parent.mkdir(parents=True, exist_ok=True)
    store.cycles_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return store


def test_a_cycle_that_places_no_order_still_reports_the_margin_the_book_is_carrying(tmp_path) -> None:
    """The bug: a day of hold-everything cycles reported peak usage 0.00% with the book fully invested."""
    rows = [
        {"bar_open_ms": BAR_0000Z, "equity": 10_000.0, "margin_usage": 0.09},
        {"bar_open_ms": BAR_0100Z, "equity": 10_000.0, "margin_usage": 0.11},
    ]
    margin = margin_and_rejections(_write_cycles(tmp_path, rows), since_ms=None)
    assert margin["peak_margin_usage"] == 0.0  # no cycle asked for new margin, and that is a true statement
    assert margin["peak_standing_usage"] == 0.11  # ... but the book was carrying 11%
    assert margin["last_standing_usage"] == 0.11
    assert margin["over_budget"] is False


def test_the_budget_verdict_follows_the_standing_book(tmp_path) -> None:
    rows = [{"bar_open_ms": BAR_0000Z, "equity": 10_000.0, "margin_usage": 0.62}]
    assert margin_and_rejections(_write_cycles(tmp_path, rows), since_ms=None)["over_budget"] is True


def test_older_cycles_without_the_field_report_nothing_rather_than_zero(tmp_path) -> None:
    rows = [{"bar_open_ms": BAR_0000Z, "equity": 10_000.0}]
    margin = margin_and_rejections(_write_cycles(tmp_path, rows), since_ms=None)
    assert margin["peak_standing_usage"] is None
    assert margin["standing_cycles"] == 0


def test_the_report_says_how_far_its_own_timestamps_are_from_the_venue(tmp_path) -> None:
    """Measured 2026-09-04: the venue was +3,611,984 ms from the host, i.e. every label is an hour early."""
    rows = [{"bar_open_ms": BAR_0500Z, "clock": {"skew_ms": 3_611_984.5, "alignment_ms": 11_984.5, "jumped": False}}]
    clock = clock_health(_write_cycles(tmp_path, rows), "2026-09-04")
    assert clock["label_skew_hours"] == 1.0
    assert clock["labels_reliable"] is False  # a whole hour off: trading is fine, the labels are not
    assert clock["worst_distance_from_bar_boundary_seconds"] == 12.0  # ... and this is what is guarded
    assert clock["jumped_cycles"] == 0


def test_a_day_with_no_clock_probe_says_so_instead_of_claiming_zero_skew(tmp_path) -> None:
    rows = [{"bar_open_ms": BAR_0500Z}]
    clock = clock_health(_write_cycles(tmp_path, rows), "2026-09-04")
    assert clock == {"cycles_probed": 0, "labels_reliable": None}


def test_a_live_symbol_with_no_research_klines_is_named(tmp_path) -> None:
    store = StateStore(tmp_path)
    state = store.load()
    state.universe = ["BTCUSDT", "CYSUSDT"]
    store.save(state)
    root = tmp_path / "data"
    (root / "klines" / "BTCUSDT").mkdir(parents=True)
    (root / "klines" / "BTCUSDT" / "1h.parquet").write_bytes(b"")
    coverage = data_coverage(store, root=root)
    assert coverage["missing_klines"] == ["CYSUSDT"]
    assert coverage["live_symbols"] == 2
