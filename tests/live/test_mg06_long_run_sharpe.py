"""M-G06: the lagging half of §19 Q2's "持续盈利" ruling, which until now was zero code.

The 2026-09-08 governance plan resolved Q2 into two criteria and shipped one.  M-010 - the leading half,
"没炸", live Sharpe not worse than the backtest's q10 - has existed since 2026-09-07.  M-G06 is the
lagging half: per strategy, on attributed P&L in M-010's own units, the annualised Sharpe over a window
in which `canonical_construction` has not changed for 18 months, point estimate >= 0, Newey-West t
REPORTED and not a gate (the same disposition D-P2 gave t), failure action "该策略退出 main".

Every clause of that is a decision already taken, so none of it is chosen here.  What this module must
not do is soften any of them to produce a number today, and the shape it has to get right is the one it
will hold for the next year and a half: **the answer today is INSUFFICIENT_DATA, and that is the correct
answer, not a gap**.  The current construction started 2026-09-04T14:00Z and 18 months from there is
2028-03-04.  A criterion whose window is 18 months and whose record is five days does not get to say
anything about the strategy, and a verdict computed on five days would be the exact failure this metric
exists to prevent - at five days the annualised-Sharpe standard error is about 8.5, so the point
estimate is compatible with nearly any truth.  What it CAN say, and does, is how much longer.

Elapsed time is counted in BARS UNDER THE CONSTRUCTION rather than off a wall clock, which is M-010's
own reading ("M-010 5.00/30 天") and the only one that cannot be satisfied by a loop that was down.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starquant_live.reports import M_G06_WINDOW_MONTHS, long_run_sharpe
from starquant_live.state import StateStore

HOUR_MS = 3_600_000
START_MS = 1_788_530_400_000  # 2026-09-04T14:00Z - where the live canonical construction actually begins
DIGEST = "0dcd044d0158c6aec263429eab9cdba9449dba0b55b07807dfd0e3d3a3a9b6e0"
OLDER = "1111111111111111111111111111111111111111111111111111111111111111"
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    """Bulk-write a ledger.  `StateStore._append` fsyncs per row, which an 18-month record cannot afford."""
    path.write_text("".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in records), encoding="utf-8")


def _store(
    tmp_path: Path,
    *,
    bars: int,
    per_bar: Any = None,
    construction: str = DIGEST,
    start: int = START_MS,
) -> StateStore:
    """A record of `bars` hourly cycles under one construction, with one attribution row each."""
    store = StateStore(tmp_path)
    cycles = []
    attributions = []
    for index in range(bars):
        bar = start + index * HOUR_MS
        cycles.append(
            {
                "bar_open_ms": bar,
                "at": datetime.fromtimestamp(bar / 1000, tz=UTC).isoformat(),
                "equity": 10_000.0,
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
                "construction": construction,
            }
        )
        if per_bar is not None:
            value = per_bar(index)
            attributions.append({"bar_open_ms": bar, "total": value, "by_strategy": {"tsmom": value}, "by_symbol": {}})
    _write(store.cycles_path, cycles)
    if attributions:
        _write(store.attribution_path, attributions)
    return store


def _series(bars: int, *, mean: float, sd: float = 3.0, seed: int = 20260909) -> Any:
    """A noisy attributed-P&L series whose SAMPLE mean is exactly `mean`.

    Noisy rather than a repeating pattern on purpose: a perfectly alternating series has a lag-1
    autocovariance of exactly -gamma0, which drives the Newey-West variance to zero and makes
    `newey_west_tstat` return None - so it would test the estimator's degenerate corner instead of the
    criterion.  Re-centring afterwards is what lets a test pin the point estimate's SIGN, which is the
    whole of M-G06's rule, without depending on a draw.
    """
    import random

    rng = random.Random(seed)
    values = [rng.gauss(0.0, sd) for _ in range(bars)]
    shift = mean - sum(values) / len(values)
    values = [value + shift for value in values]
    return lambda index: values[index]


# 18 months from 2026-09-04 is 2028-03-04, i.e. 547 whole days, i.e. this many hourly bars.
CLOSED = 547 * 24 + 24


def test_five_days_of_record_is_insufficient_and_says_how_much_longer(tmp_path: Path) -> None:
    """Today's real answer.  The window is 18 months and the construction is five days old."""
    block = long_run_sharpe(_store(tmp_path, bars=120, per_bar=_series(120, mean=1.0)), equity=10_000.0, now=NOW)

    assert block["status"] == "INSUFFICIENT_DATA"
    assert block["window_months"] == M_G06_WINDOW_MONTHS == 18
    assert block["construction"] == "0dcd044d0158"
    assert block["since"].startswith("2026-09-04T14:00")
    assert block["judgeable_from"].startswith("2028-03-04T14:00")
    assert block["elapsed_days"] == 5.0
    assert block["required_days"] == 547
    assert block["days_remaining"] == 542.0
    assert block["by_strategy"]["tsmom"]["status"] == "INSUFFICIENT_DATA"


def test_the_countdown_is_in_record_days_and_the_calendar_is_reported_beside_it(tmp_path: Path) -> None:
    """`judgeable_from` is a DATE while the countdown is in bars; the gap between them is downtime.

    Given only one of the two units a reader would reasonably assume they are the same, and they are
    equal only while the loop misses nothing.  Here the calendar has run 5.04 days and the record covers
    5.00 of them, so the date slips by the difference and the report says so rather than implying a
    deadline the record is not on track for.
    """
    block = long_run_sharpe(_store(tmp_path, bars=120, per_bar=_series(120, mean=1.0)), equity=10_000.0, now=NOW)

    assert round(block["calendar_days"], 2) == 5.04
    assert round(block["downtime_days"], 2) == 0.04
    assert block["elapsed_days"] == 5.0


def test_the_point_estimate_is_shown_but_can_never_be_a_verdict_early(tmp_path: Path) -> None:
    """Reported so a reader can see where it stands; labelled so nobody can read it as the criterion.

    The pairing that makes this safe is `sharpe_standard_error`: at five days it is about 8.5, which is
    what "this number means nothing yet" looks like written down.  It falls to the plan's own 0.82 only
    when the window closes.
    """
    store = _store(tmp_path, bars=120, per_bar=_series(120, mean=1.0))

    row = long_run_sharpe(store, equity=10_000.0, now=NOW)["by_strategy"]["tsmom"]

    assert row["sharpe_so_far"] is not None and row["sharpe_so_far"] > 0
    assert round(row["sharpe_standard_error"], 1) == 8.5
    assert row["status"] == "INSUFFICIENT_DATA"
    assert row["action"] is None
    assert "2028-03-04" in row["why"]


def test_a_construction_change_restarts_the_window_and_the_countdown(tmp_path: Path) -> None:
    """ "按 `canonical_construction` 计时" - a different book is not more evidence about this one."""
    store = StateStore(tmp_path)
    rows = [
        {"bar_open_ms": START_MS - (48 - i) * HOUR_MS, "equity": 10_000.0, "construction": OLDER} for i in range(48)
    ]
    rows += [{"bar_open_ms": START_MS + i * HOUR_MS, "equity": 10_000.0, "construction": DIGEST} for i in range(24)]
    _write(store.cycles_path, rows)

    block = long_run_sharpe(store, equity=10_000.0, now=NOW)

    assert block["construction"] == "0dcd044d0158"
    assert block["since"].startswith("2026-09-04T14:00")
    assert block["elapsed_days"] == 1.0
    assert block["judgeable_from"].startswith("2028-03-04")


def test_a_renamed_fingerprint_field_does_not_restart_the_countdown(tmp_path: Path) -> None:
    """The v2/v3/v4 aliases: the digest moved three times while the book was byte-identical.

    Reading raw digests here would hand the operator a fresh 18-month wait for a field rename, which is
    the failure `CONSTRUCTION_ALIASES` was written to close for M-010's 30 days.
    """
    from starquant_live.construction import CONSTRUCTION_ALIASES

    alias = next(key for key, target in CONSTRUCTION_ALIASES.items() if target == DIGEST)
    store = StateStore(tmp_path)
    rows = [{"bar_open_ms": START_MS + i * HOUR_MS, "equity": 10_000.0, "construction": DIGEST} for i in range(24)]
    rows += [
        {"bar_open_ms": START_MS + (24 + i) * HOUR_MS, "equity": 10_000.0, "construction": alias} for i in range(24)
    ]
    _write(store.cycles_path, rows)

    block = long_run_sharpe(store, equity=10_000.0, now=NOW)

    assert block["since"].startswith("2026-09-04T14:00")
    assert block["elapsed_days"] == 2.0


def test_once_the_window_closes_a_non_negative_point_estimate_passes(tmp_path: Path) -> None:
    """ "点估计 >= 0" and nothing else: t is reported beside it and does not decide anything."""
    store = _store(tmp_path, bars=CLOSED, per_bar=_series(CLOSED, mean=0.5))

    block = long_run_sharpe(store, equity=10_000.0, now=datetime(2028, 4, 1, tzinfo=UTC))
    row = block["by_strategy"]["tsmom"]

    assert block["status"] == "OK"
    assert row["status"] == "OK"
    assert row["sharpe_so_far"] > 0
    assert row["nw_t"] is not None  # reported
    assert row["action"] is None
    # the plan's own arithmetic: 18 months buys a standard error of about 0.82, and no more
    assert round(row["sharpe_standard_error"], 2) == 0.82


def test_a_negative_point_estimate_after_18_months_retires_the_sleeve(tmp_path: Path) -> None:
    """The registered failure action, spelled out where the operator reads it."""
    store = _store(tmp_path, bars=CLOSED, per_bar=_series(CLOSED, mean=-0.5))

    block = long_run_sharpe(store, equity=10_000.0, now=datetime(2028, 4, 1, tzinfo=UTC))
    row = block["by_strategy"]["tsmom"]

    assert block["status"] == "FAIL"
    assert row["sharpe_so_far"] < 0
    assert row["status"] == "FAIL"
    assert "退出 main" in row["action"]


def test_the_t_statistic_never_moves_the_verdict(tmp_path: Path) -> None:
    """D-P2's disposition: t is reported, not a gate.  A pass with a hopeless t is still a pass.

    18 months buys a Sharpe standard error of 0.82, so a weak t on a passing sleeve is the EXPECTED
    outcome rather than a surprise; a gate on t would make M-G06 unreachable and quietly turn the
    lagging criterion off.
    """
    store = _store(tmp_path, bars=CLOSED, per_bar=_series(CLOSED, mean=0.01))

    row = long_run_sharpe(store, equity=10_000.0, now=datetime(2028, 4, 1, tzinfo=UTC))["by_strategy"]["tsmom"]

    assert abs(row["nw_t"]) < 2.0
    assert row["status"] == "OK"


def test_no_equity_refuses_rather_than_dividing(tmp_path: Path) -> None:
    block = long_run_sharpe(_store(tmp_path, bars=48, per_bar=_series(48, mean=1.0)), equity=None, now=NOW)

    assert block["status"] == "INSUFFICIENT_DATA"
    assert "equity" in block["why"]


def test_an_empty_record_says_there_is_no_construction_to_time(tmp_path: Path) -> None:
    block = long_run_sharpe(StateStore(tmp_path), equity=10_000.0, now=NOW)

    assert block["status"] == "INSUFFICIENT_DATA"
    assert block["construction"] is None


# --- the reader.  M-G06 was zero code, so it was also zero readers ----------------------------------


def test_the_daily_report_renders_it(tmp_path: Path) -> None:
    from starquant_live.reports import daily_markdown, daily_payload

    store = _store(tmp_path, bars=120, per_bar=_series(120, mean=1.0))
    text = daily_markdown(daily_payload(store, "2026-09-04", {}))

    assert "M-G06" in text
    assert "INSUFFICIENT_DATA" in text
    assert "2028-03-04" in text


def test_insufficient_data_is_silent_and_a_failure_is_a_notice(tmp_path: Path) -> None:
    """A criterion 542 days from being answerable must not print a finding every day for 542 days.

    When it does answer FAIL, the action is "该策略退出 main" - a governance transition taken through
    `lifecycle.apply` at review, not something to do inside the hour - so it is a notice and not a page.
    """
    from starquant_live.reports import daily_alerts, daily_payload

    store = _store(tmp_path, bars=120, per_bar=_series(120, mean=1.0))
    payload = daily_payload(store, "2026-09-04", {})
    alerts, notices = daily_alerts(payload)

    assert not any("M-G06" in line for line in alerts)
    assert not any("M-G06" in line for line in notices)

    payload["long_run_sharpe"] = {
        "status": "FAIL",
        "by_strategy": {"tsmom": {"status": "FAIL", "sharpe_so_far": -0.4, "action": "该策略退出 main"}},
    }
    alerts, notices = daily_alerts(payload)

    assert not any("M-G06" in line for line in alerts)
    assert any("M-G06" in line and "tsmom" in line for line in notices)
