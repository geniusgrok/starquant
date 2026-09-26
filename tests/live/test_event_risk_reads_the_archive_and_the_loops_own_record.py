"""#8.10: event risk is read off the archive and off the loop's own record, and it pages on nothing.

`starquant_live.report_events.event_risk` puts three readings in the daily report: USDC/USDT on Binance spot, what the
loop recorded going wrong on its way to the venue, and the market's newest hourly moves in units of its own
volatility.  These tests pin the places each could be quietly wrong:

* THE PEG ON REAL BARS.  Two slices cut verbatim from `spot_klines/USDCUSDT`.  USDC's own depeg, from the first bar
  after the pair's 3,996-hour hole: its open and high read 1.0 and its low 0.882, so a reading off the close or the
  high would say far less.  And 2025-10-10, whose 21:00Z bar printed 0.985 while no close strayed 44 bps.
* THE RECORD'S OWN SHAPES.  The failed cycle and the restart after it are `tests/fixtures/mq03`'s verbatim rows; the
  other eight failures copy the record's error texts and bars.  A rejected order is written by `execute_order`
  itself.  The failure count is M-001's, and is checked against `health.cycle_health` on the same rows.
* THE MARKET AGAINST AN INDEPENDENT READ.  BTCUSDT's closes around 2025-10-10, verbatim, scored again by pandas
  here; the basket on the August 2026 fixture, averaged by hand.
* WHERE THE ARCHIVE STOPS, what one broken block costs, and that the section sits beside the G4 tail without
  reaching `daily_alerts`.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_data.store import SPOT_KLINE_KIND, KlineStore
from starquant_live.execution import execute_order
from starquant_live.health import cycle_health
from starquant_live.rebalancer import PlannedOrder
from starquant_live.report_events import (
    ARCHIVE_SLACK_BARS,
    INCIDENT_DAYS,
    PEG_PAIR,
    SIGNALS,
    _event_risk_lines,
    event_risk,
    market_extremes,
    stablecoin_peg,
    venue_incidents,
)
from starquant_live.reports import daily_alerts, daily_markdown, daily_payload
from starquant_live.scheduler import BACKOFF_REASON, MISSED_REBALANCE_REASON
from starquant_live.state import StateStore
from starquant_shared.types import Side, VenueError
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "event_risk"
MQ03 = ROOT / "tests" / "fixtures" / "mq03" / "cycles_2026-09-23T15.jsonl"
HOUR = 3_600_000
DAY = 24 * HOUR

#: The nine ERROR rows of `.starquant/live/cycles.jsonl` as of 2026-09-25 (copy taken 08:25Z): bar and error, verbatim.
RECORDED_FAILURES = (
    ("2026-09-08T05:00:00+00:00", "ProxyError: 503 Service Unavailable"),
    ("2026-09-09T10:00:00+00:00", "ConnectError: All connection attempts failed"),
    ("2026-09-14T20:00:00+00:00", "ConnectTimeout: "),
    ("2026-09-15T08:00:00+00:00", "ProxyError: 503 Service Unavailable"),
    ("2026-09-16T04:00:00+00:00", "ProxyError: 503 Service Unavailable"),
    ("2026-09-16T11:00:00+00:00", "ProxyError: 503 Service Unavailable"),
    ("2026-09-21T17:00:00+00:00", "ProxyError: 503 Service Unavailable"),
    (
        "2026-09-21T20:00:00+00:00",
        "VenueError: GET /fapi/v2/positionRisk failed after 4 attempts: 503 Service Unavailable",
    ),
    ("2026-09-23T15:00:00+00:00", "ProxyError: 503 Service Unavailable"),
)


def _ms(iso: str) -> int:
    return int(pd.Timestamp(iso).value // 1_000_000)


def _iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def _slice(name: str) -> pd.DataFrame:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return pd.DataFrame(payload["rows"], columns=payload["columns"])


def _spot_root(tmp_path: Path, frame: pd.DataFrame) -> Path:
    root = tmp_path / "data"
    KlineStore(root, kind=SPOT_KLINE_KIND).append(PEG_PAIR, "1h", frame)
    return root


def _real_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in MQ03.read_text(encoding="utf-8").splitlines() if line.strip()]


def _failed(bar_iso: str, error: str) -> dict[str, Any]:
    """The recorded ERROR row of 2026-09-23T15:00Z with its bar and its error replaced, every other key as written."""
    row = dict(_real_rows()[0])
    bar = _ms(bar_iso)
    row.update(bar=bar_iso, bar_open_ms=bar, at=_iso(bar + HOUR + 61_000), error=error)
    return row


def _traded(bar: int, **extra: Any) -> dict[str, Any]:
    """A completed cycle, with the keys the readings here look at."""
    return {
        "at": _iso(bar + HOUR + 30_000),
        "bar": _iso(bar),
        "bar_open_ms": bar,
        "as_of_ms": bar,
        "dry_run": False,
        "equity": 10_000.0,
        "guard_reasons": [],
        "skip": False,
        "orders": [],
        "quarantined": [],
        "dropped_inputs": {"after": 1, "flattened": [], "held": [], "symbols": []},
        "universe_update": None,
        **extra,
    }


def _store(tmp_path: Path, rows: list[dict[str, Any]]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for row in rows:
        store.append_cycle(row)
    return store


def _the_record(first: str, last: str) -> list[dict[str, Any]]:
    """Every hour from `first` to `last` traded, except the nine the record failed on, which carry their rows."""
    failures = {_ms(bar): error for bar, error in RECORDED_FAILURES}
    return [
        _failed(_iso(bar), failures[bar]) if bar in failures else _traded(bar)
        for bar in range(_ms(first), _ms(last) + HOUR, HOUR)
    ]


# --- 1. the peg ---------------------------------------------------------------------------------------------


def test_the_usdc_depeg_reads_below_zero_from_the_first_bar_back(tmp_path: Path) -> None:
    frame = _slice("USDCUSDT_spot_2023-03-11.json")
    anchor = _ms("2023-03-11T23:00:00+00:00")
    block = stablecoin_peg(anchor, root=_spot_root(tmp_path, frame), decision_ms=anchor)

    assert block["measured"] is True and block["lag_bars"] == 0 and block["last_bar"] == _iso(anchor)
    day = block["windows"]["24h"]
    # The pair came back at 14:00Z: ten of the window's 24 bars exist, and the block says ten.
    assert (day["bars"], day["of"]) == (10, 24)
    first = frame.iloc[0]
    assert (first["open"], first["high"], first["low"]) == (1.0, 1.0, 0.882)
    assert day["max_deviation_bar"] == "2023-03-11T14:00:00+00:00"
    assert day["max_deviation_bps"] == pytest.approx((0.882 - 1.0) * 1e4, abs=1e-9)
    inside = frame[(frame["open_time"] > anchor - DAY) & (frame["open_time"] <= anchor)]
    assert day["median_abs_close_bps"] == pytest.approx(float((inside["close"] - 1.0).abs().median()) * 1e4, rel=1e-12)
    last_close = float(inside["close"].iloc[-1])
    assert block["last_close"] == last_close and block["last_deviation_bps"] == pytest.approx((last_close - 1) * 1e4)
    assert block["last_deviation_bps"] < -200, "USDC still well under USDT at the day's close: the negative side"
    # The 30-day window is the same ten bars: the hole before them holds nothing to read.
    assert (
        block["windows"]["30d"]["bars"] == 10
        and block["windows"]["30d"]["max_deviation_bps"] == day["max_deviation_bps"]
    )


def test_a_one_bar_wick_counts_where_every_close_stayed_near_one(tmp_path: Path) -> None:
    frame = _slice("USDCUSDT_spot_2025-10-10.json")
    anchor = _ms("2025-10-10T23:00:00+00:00")
    block = stablecoin_peg(anchor, root=_spot_root(tmp_path, frame), decision_ms=anchor)

    day = block["windows"]["24h"]
    assert (day["bars"], day["max_deviation_bar"]) == (24, "2025-10-10T21:00:00+00:00")
    assert day["max_deviation_bps"] == pytest.approx((0.985 - 1.0) * 1e4, abs=1e-9)
    closes = frame[(frame["open_time"] > anchor - DAY) & (frame["open_time"] <= anchor)]["close"]
    assert float((closes - 1.0).abs().max()) * 1e4 < 45.0, "no close strayed as far as the wick"
    assert day["median_abs_close_bps"] < 10.0


def test_a_usdt_side_wick_reads_above_zero_off_the_high(tmp_path: Path) -> None:
    """2026-05-28T04:00Z printed 1.0219 and closed at 1.00125: the side a USDT depeg moves the pair to."""
    frame = _slice("USDCUSDT_spot_2026-05-28.json")
    anchor = _ms("2026-05-28T23:00:00+00:00")
    day = stablecoin_peg(anchor, root=_spot_root(tmp_path, frame), decision_ms=anchor)["windows"]["24h"]

    wick = frame[frame["open_time"] == _ms("2026-05-28T04:00:00+00:00")].iloc[0]
    assert (wick["high"], wick["close"]) == (1.0219, 1.00125)
    assert day["max_deviation_bar"] == "2026-05-28T04:00:00+00:00"
    assert day["max_deviation_bps"] == pytest.approx((1.0219 - 1.0) * 1e4, abs=1e-9)


def test_the_windows_end_at_the_archives_newest_bar_and_say_how_far_behind_it_is(tmp_path: Path) -> None:
    frame = _slice("USDCUSDT_spot_2025-10-10.json")  # ends 2025-10-11T23:00Z
    root = _spot_root(tmp_path, frame)
    decision = _ms("2025-10-12T15:00:00+00:00")
    block = stablecoin_peg(decision, root=root, decision_ms=decision)

    assert block["last_bar"] == "2025-10-11T23:00:00+00:00" and block["lag_bars"] == 16
    assert block["windows"]["24h"]["bars"] == 24, "a full window behind the lag, not the 8 bars before the decision"
    # No traded cycle that day: the windows end at the day's last bar and no lag is claimed.
    assert stablecoin_peg(decision, root=root, decision_ms=None)["lag_bars"] is None
    # Past the slack the archive is not read as today's: the block says where it stopped.
    later = _ms("2025-10-11T23:00:00+00:00") + (ARCHIVE_SLACK_BARS + 1) * HOUR
    stale = stablecoin_peg(later, root=root, decision_ms=later)
    assert stale["measured"] is False and "2025-10-11T23:00:00+00:00" in stale["reason"]
    assert f"早 {ARCHIVE_SLACK_BARS + 1} 根" in stale["reason"]
    gone = stablecoin_peg(later + 900 * HOUR, root=root, decision_ms=None)
    assert gone["measured"] is False and "归档最新一根：2025-10-11T23:00:00+00:00" in gone["reason"]


def test_a_loop_that_is_down_does_not_stop_the_readings_with_it(tmp_path: Path) -> None:
    """The windows end at the day's newest archived bar, not at the loop's last traded one."""
    root = _spot_root(tmp_path, _slice("USDCUSDT_spot_2025-10-10.json"))  # ends 2025-10-11T23:00Z
    last_traded = _ms("2025-10-10T05:00:00+00:00")
    block = event_risk(_store(tmp_path, [_traded(last_traded)]), "2025-10-11", root=root)

    assert block["decision_bar"] == _iso(last_traded)
    peg = block["stablecoin"]
    assert peg["last_bar"] == "2025-10-11T23:00:00+00:00" and peg["lag_bars"] == -42
    # The 2025-10-10T21:00Z wick is still inside the last 720 bars the archive holds, whatever the loop did.
    assert peg["windows"]["30d"]["max_deviation_bar"] == "2025-10-10T21:00:00+00:00"
    assert "比决策 bar 晚 42 根：循环在那之后没有成交过" in _event_risk_lines(block)["USDC/USDT 归档截至"]


# --- 2. the venue path ---------------------------------------------------------------------------------------


def test_the_recorded_failure_and_the_restart_over_its_bar_are_one_incident_bar(tmp_path: Path) -> None:
    failure, restart = _real_rows()
    assert (failure["phase"], restart["phase"], restart["reason"]) == ("ERROR", "SKIPPED", MISSED_REBALANCE_REASON)
    block = venue_incidents(_store(tmp_path, [failure, restart]), "2026-09-23")

    day = block["windows"]["1d"]
    assert (day["bars"], day["incident_bars"]) == (1, 1), "a restart is not a venue incident"
    assert day["counts"] == {**dict.fromkeys(SIGNALS, 0), "failed_cycles": 1}
    assert (day["failed_by_type"], day["failed_with_503"], day["longest_failure_run_bars"]) == ({"ProxyError": 1}, 1, 1)
    assert block["last_incident"] == {
        "bar": "2026-09-23T15:00:00+00:00",
        "at": "2026-09-23T16:01:02+00:00",
        "signal": "failed_cycles",
        "detail": "ProxyError: 503 Service Unavailable",
    }


def test_the_records_nine_failures_by_window_and_the_count_is_m001s(tmp_path: Path) -> None:
    rows = _the_record("2026-09-03T00:00:00+00:00", "2026-09-25T07:00:00+00:00")
    block = venue_incidents(_store(tmp_path, rows), "2026-09-25")

    month, week, day = (block["windows"][f"{days}d"] for days in (30, 7, 1))
    assert month["failed_by_type"] == {"ConnectError": 1, "ConnectTimeout": 1, "ProxyError": 6, "VenueError": 1}
    assert (month["counts"]["failed_cycles"], month["failed_with_503"], month["incident_bars"]) == (9, 7, 9)
    assert month["bars"] == len(rows) == 22 * 24 + 8
    assert week["failed_by_type"] == {"ProxyError": 2, "VenueError": 1} and week["bars"] == 6 * 24 + 8
    assert (day["incident_bars"], day["bars"]) == (0, 8)
    # One definition of a failed cycle: M-001's, the one `live status --check` pages on.
    day_end = _ms("2026-09-26T00:00:00+00:00")
    for days in INCIDENT_DAYS:
        health = cycle_health(
            rows, now=pd.Timestamp(day_end, unit="ms", tz="UTC").to_pydatetime(), window_hours=24.0 * days
        )
        assert block["windows"][f"{days}d"]["counts"]["failed_cycles"] == health.failures
    assert block["last_incident"]["bar"] == "2026-09-23T15:00:00+00:00"


async def test_every_signal_is_a_row_the_loop_already_writes(tmp_path: Path) -> None:
    base = _ms("2026-09-24T00:00:00+00:00")
    rows = [
        _traded(base),
        _failed(_iso(base + HOUR), "ProxyError: 503 Service Unavailable"),
        _failed(_iso(base + 2 * HOUR), "ConnectTimeout: "),
        {  # what `_record_missed_rebalance` writes for a bar the failure backoff slept through
            "at": _iso(base + 4 * HOUR + 5_000),
            "bar": _iso(base + 3 * HOUR),
            "bar_open_ms": base + 3 * HOUR,
            "dry_run": False,
            "late_seconds": 3605.0,
            "missed_rebalances": 1,
            "orders": [],
            "phase": "SKIPPED",
            "reason": BACKOFF_REASON,
            "targets": {},
            "window_seconds": 86.2,
        },
        _traded(base + 5 * HOUR, guard_reasons=["STALE_MARKET_DATA"], skip=True),
        _traded(
            base + 6 * HOUR, dropped_inputs={"after": 3, "flattened": [], "held": ["LSKUSDT"], "symbols": ["LSKUSDT"]}
        ),
        _traded(base + 7 * HOUR, quarantined=["AKEUSDT"]),
        _traded(
            base + 8 * HOUR, universe_update={"error": "ProxyError: 503 Service Unavailable", "universe": ["BTCUSDT"]}
        ),
        # A restart over an already-traded bar, a dry run and a kill switch are not the venue failing.
        {**_real_rows()[1], "bar": _iso(base + 9 * HOUR), "bar_open_ms": base + 9 * HOUR, "at": _iso(base + 10 * HOUR)},
        {**_failed(_iso(base + 10 * HOUR), "ProxyError: 503 Service Unavailable"), "dry_run": True},
        _traded(base + 11 * HOUR, guard_reasons=["KILL_SWITCH"]),
        # The two cycles that placed the orders below: every order's bar has its cycle's row.
        _traded(base + 12 * HOUR),
        _traded(base + 13 * HOUR),
        _traded(base + 14 * HOUR),
    ]
    store = _store(tmp_path, rows)
    rejected = PlannedOrder(
        symbol="BTCUSDT",
        side=Side.BUY,
        quantity=Decimal("0.010"),
        reduce_only=False,
        client_order_id=f"bd-{base + 12 * HOUR}-BTCUSDT",
        target_weight=0.05,
        current_notional=0.0,
        target_notional=600.0,
        price=60_000.0,
    )
    venue = FakeVenue()
    venue.errors_to_inject.append(VenueError("Internal error; unable to process your request.", code=-1001))
    report = await execute_order(venue, rejected, FakeClock(base + 13 * HOUR))
    assert report.status == "REJECTED"
    store.append_trade(
        {"bar_open_ms": base + 12 * HOUR, "late_seconds": 31.0, "decision_close": 60_000.0, **report.to_dict()}
    )
    filled = replace(rejected, client_order_id=f"bd-{base + 13 * HOUR}-BTCUSDT")
    first = await execute_order(venue, filled, FakeClock(base + 14 * HOUR))
    again = await execute_order(venue, filled, FakeClock(base + 14 * HOUR + 60_000))
    assert (first.status, again.error) == ("FILLED", "already submitted for this bar")
    for placed in (first, again):
        store.append_trade({"bar_open_ms": base + 13 * HOUR, "late_seconds": 30.0, **placed.to_dict()})
    # A restart that finds an order whose own row was never written: FILLED, with the marker in `error`.
    lost = replace(rejected, client_order_id=f"bd-{base + 14 * HOUR}-BTCUSDT")
    await execute_order(venue, lost, FakeClock(base + 15 * HOUR))
    found = await execute_order(venue, lost, FakeClock(base + 15 * HOUR + 60_000))
    assert (found.status, found.error) == ("FILLED", "already submitted for this bar")
    store.append_trade({"bar_open_ms": base + 14 * HOUR, "late_seconds": 2400.0, **found.to_dict()})

    day = venue_incidents(store, "2026-09-24")["windows"]["1d"]
    assert day["counts"] == {
        "failed_cycles": 2,
        "backoff_missed_bars": 1,
        "stale_data_skips": 1,
        "inputs_dropped": 1,
        "orders_not_filled": 1,
        "quarantines": 1,
        "pool_refresh_errors": 1,
    }
    assert day["longest_failure_run_bars"] == 2 and day["failed_with_503"] == 1
    # Bars 1-3, 5-8 and the rejection's 12.  Not the restart's 9, the kill switch's 11, nor the two fills whose
    # error field carries the already-submitted marker (13, 14).  The dry run's 10 is not a bar the loop ran at all.
    assert day["incident_bars"] == 8 and day["bars"] == 13
    block = venue_incidents(store, "2026-09-24")
    assert block["last_incident"]["signal"] == "orders_not_filled"
    assert (
        block["last_incident"]["detail"]
        == "BTCUSDT REJECTED: Internal error; unable to process your request. (code -1001)"
    )


# --- 3. the market -----------------------------------------------------------------------------------------


def _btc_closes() -> pd.Series:
    frame = _slice("BTCUSDT_1h_close_2025-10-10.json")
    return pd.Series(frame["close"].to_numpy(dtype=float), index=frame["open_time"].to_numpy(dtype="int64"))


def test_btc_on_2025_10_10_is_scored_against_the_30_days_before_the_last_24_hours(tmp_path: Path) -> None:
    closes = _btc_closes()
    anchor = _ms("2025-10-10T23:00:00+00:00")
    block = market_extremes(
        _store(tmp_path, []),
        "2025-10-10",
        anchor,
        closes={"BTCUSDT": closes}.__getitem__,
        root=tmp_path,
        decision_ms=anchor,
    )
    btc = block["series"]["BTCUSDT"]

    logs = np.log(closes).diff()
    recent = logs[(logs.index > anchor - DAY) & (logs.index <= anchor)]
    baseline = logs[(logs.index > anchor - DAY - 720 * HOUR) & (logs.index <= anchor - DAY)]
    sigma = float(baseline.std())
    assert btc["baseline_bars"] == 720 and btc["recent_bars"] == 24
    assert btc["sigma_1h"] == pytest.approx(sigma, rel=1e-12)
    worst = _ms("2025-10-10T20:00:00+00:00")
    assert btc["max_z_bar"] == _iso(worst)
    assert btc["max_z"] == pytest.approx(float(recent.loc[worst]) / sigma, rel=1e-12)
    assert btc["max_z_return"] == pytest.approx(closes.loc[worst] / closes.loc[worst - HOUR] - 1.0, rel=1e-9)
    assert btc["max_z"] < -6.0
    assert btc["last_z"] == pytest.approx(float(recent.loc[anchor]) / sigma, rel=1e-12)
    assert btc["return_24h"] == pytest.approx(closes.loc[anchor] / closes.loc[anchor - DAY] - 1.0, rel=1e-9)
    assert btc["z_24h"] == pytest.approx(float(recent.sum()) / (sigma * math.sqrt(24)), rel=1e-12)
    # The scored day stays out of its own ruler: in it, the crash would have widened the sigma it is read with.
    assert float(logs[(logs.index > anchor - DAY - 720 * HOUR) & (logs.index <= anchor)].std()) > sigma * 1.05
    assert block["series"]["basket"]["measured"] is False and block["lag_bars"] == 0


def test_the_basket_is_the_members_mean_log_return_and_a_missing_member_is_named(
    tmp_path: Path, august_dir: Path
) -> None:
    root = tmp_path / "data"
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"):
        (root / "klines" / symbol).mkdir(parents=True)
        shutil.copy(august_dir / symbol / "1h.parquet", root / "klines" / symbol / "1h.parquet")
    anchor = _ms("2026-08-30T23:00:00+00:00")
    members = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "NOPEUSDT"]
    store = _store(tmp_path, [_traded(anchor, universe=members)])
    block = market_extremes(store, "2026-08-30", anchor, closes=None, root=root, decision_ms=anchor)

    assert block["missing"] == ["NOPEUSDT"] and block["universe"] == 4
    basket = block["series"]["basket"]
    assert (basket["members"], basket["printed_last_bar"]) == (3, 3)
    frames = {s: pd.read_parquet(august_dir / s / "1h.parquet") for s in members[:3]}
    logs = pd.DataFrame(
        {s: np.log(f["close"].astype(float).to_numpy()) for s, f in frames.items()},
        index=frames["ETHUSDT"]["open_time"].to_numpy(dtype="int64"),
    ).diff()
    by_hand = (logs["ETHUSDT"] + logs["BNBUSDT"] + logs["SOLUSDT"]) / 3.0
    baseline = by_hand[by_hand.index <= anchor - DAY].dropna()
    assert basket["baseline_bars"] == len(baseline) == 720 - 24 - 1, "the fixture's first close has no return"
    assert basket["sigma_1h"] == pytest.approx(float(baseline.std()), rel=1e-12)
    recent = by_hand[by_hand.index > anchor - DAY]
    assert basket["z_24h"] == pytest.approx(float(recent.sum()) / (float(baseline.std()) * math.sqrt(24)), rel=1e-12)
    lines = _event_risk_lines({"market": block})
    assert "universe 等权篮子（3/4 个）" in lines and lines["归档里没有的成员"] == "NOPEUSDT"


def test_a_market_archive_past_the_slack_is_not_read_as_today(tmp_path: Path) -> None:
    closes = _btc_closes()  # ends 2025-10-11T23:00Z
    last = int(closes.index[-1])
    store = _store(tmp_path, [])
    behind = market_extremes(
        store,
        "2025-10-12",
        last + 5 * HOUR,
        closes={"BTCUSDT": closes}.__getitem__,
        root=tmp_path,
        decision_ms=last + 5 * HOUR,
    )
    assert behind["measured"] is True and behind["lag_bars"] == 5
    assert behind["series"]["BTCUSDT"]["recent_bars"] == 24, "the windows end at the archive's bar, not the decision's"
    later = last + (ARCHIVE_SLACK_BARS + 1) * HOUR
    stale = market_extremes(
        store, "2025-10-19", later, closes={"BTCUSDT": closes}.__getitem__, root=tmp_path, decision_ms=later
    )
    assert stale["measured"] is False and _iso(last) in stale["reason"]


# --- 4. on the page --------------------------------------------------------------------------------------------


def test_the_daily_report_prints_it_after_the_tail_and_pages_on_nothing(tmp_path: Path) -> None:
    anchor = _ms("2025-10-10T23:00:00+00:00")
    root = tmp_path / "data"
    KlineStore(root, kind=SPOT_KLINE_KIND).append(PEG_PAIR, "1h", _slice("USDCUSDT_spot_2025-10-10.json"))
    btc = _slice("BTCUSDT_1h_close_2025-10-10.json")
    KlineStore(root).append("BTCUSDT", "1h", btc)
    rows = [_traded(anchor - HOUR, universe=["BTCUSDT"]), _failed(_iso(anchor), "ProxyError: 503 Service Unavailable")]
    payload = daily_payload(_store(tmp_path, rows), "2025-10-10", data_root=root)

    keys = list(payload)
    assert keys.index("event_risk") == keys.index("tail") + 1
    block = payload["event_risk"]
    assert block["decision_bar"] == _iso(anchor - HOUR)
    assert block["stablecoin"]["windows"]["24h"]["max_deviation_bps"] == pytest.approx(-150.0, abs=1e-9)
    assert block["market"]["series"]["BTCUSDT"]["max_z_bar"] == "2025-10-10T20:00:00+00:00"
    assert block["venue"]["windows"]["1d"]["counts"]["failed_cycles"] == 1
    markdown = daily_markdown(payload)
    tail, here = (
        markdown.index("## Tail beside the sigma ruler (G4)"),
        markdown.index("## Event risk (#8.10, reported only)"),
    )
    assert tail < here < markdown.index("## Exit counterfactuals")
    section = markdown[here:].split("\n## ", 1)[0]
    assert "| USDC/USDT 近 24 根 | 最大偏离 -150.0 bps（bar 2025-10-10T21:00:00+00:00）" in section
    assert "| 交易所事故，当日 | 有事故的 bar 1/2：周期失败 1（ProxyError 1；含 503 的 1；最长连续 1 根） |" in section
    assert "只报告，不告警" in section
    without = {key: value for key, value in payload.items() if key != "event_risk"}
    assert daily_alerts(payload) == daily_alerts(without), "reported only: it must not reach alerts or notices"


def test_one_broken_block_costs_its_own_block_not_the_others(tmp_path: Path) -> None:
    anchor = _ms("2025-10-10T23:00:00+00:00")
    root = _spot_root(tmp_path, _slice("USDCUSDT_spot_2025-10-10.json"))
    # A garbled row: `dropped_inputs` written as a list.  The venue reading cannot walk it; the peg does not read it.
    store = _store(tmp_path, [_traded(anchor, dropped_inputs=["LSKUSDT"])])
    block = event_risk(store, "2025-10-10", root=root)

    assert block["venue"]["measured"] is False and block["venue"]["reason"].startswith("AttributeError")
    assert block["stablecoin"]["measured"] is True
    assert block["market"]["measured"] is False and "FileNotFoundError" in block["market"]["reason"]
    lines = _event_risk_lines(block)
    assert lines["交易所事故"].startswith("读不出：AttributeError")
    assert lines["极端行情"].startswith("读不出：FileNotFoundError")
    assert "脱锚读法" in lines and "交易所事故读法" in lines and "极端行情读法" in lines
