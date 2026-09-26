"""AC-L4's other half: the numbers land in `cycles.jsonl` and the daily report never mentions them.

DL-L4 gave every restart two facts - how late it woke relative to the bar close, and whether that cost
a rebalance - and wrote them into the cycle row.  The acceptance criterion asks for them in the DAILY
REPORT, because that is where an operator sees them; in the JSONL they are read by nobody.

RISK-P2 is why they exist at all: every deployment restart is assumed to cost late fills and 7bps of
gross, and the plan asked for that assumption to be COUNTED rather than carried.  L1-01's error was the
same shape in reverse - measuring the fills that happened rather than the ones that should not have.

2026-09-09 audit, and what changed here.  The numbers reached the markdown and stopped: nothing compared
them to anything, and `daily_alerts` did not read `restarts` at all.  M-Q03's thresholds were not missing
either - the 2026-09-06 remediation plan's own row carries "<= 5% / 0" and "查重启原因" - they simply had
no reader, so they are now in `config/live.demo.yaml` beside M-Q08's and this module judges against them.

Wiring the judgement first required fixing what it would have judged.  `missed_rebalances` was
reconstructed from the engine's per-process RUNNING TOTAL, which cannot see three consecutive processes
that each missed exactly one: on the real record for 2026-09-09 it read 1 where three separate restarts
had each written a miss row.  Every miss appends exactly one cycle row, so the rows ARE the count, and
the reconstruction was a strictly worse estimator of the same thing (it also charged a process that
spanned midnight with yesterday's misses).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starquant_live.reports import restart_cost
from starquant_live.risk_budget import RiskBudgetParams

MISSED = "restart outside the rebalance window"
HOUR_MS = 3_600_000
BAR = 1_789_016_400_000  # 2026-09-10T05:00:00Z

# 2026-09-10: `restart_cost` stopped reading the late share off `late_seconds` (which only restart rows
# ever carried, so a metric named "迟到周期占比" was reporting restart frequency) and now computes each
# SCHEDULED cycle's wake-up from the `at` and `bar_open_ms` every row has always written.  The fixtures
# below carry those fields for that reason; a row of `{"bar": "t1"}` no longer describes anything the
# engine writes.  See test_the_late_share_measures_wake_ups_not_restarts.py.


def _iso(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _cycle(index: int, woke_seconds_after_close: float = 14.0, window: float = 73.7) -> dict[str, Any]:
    """A completed cycle as the engine writes it, punctual unless told otherwise."""
    bar = BAR + index * HOUR_MS
    return {
        "bar": _iso(bar),
        "bar_open_ms": bar,
        "at": _iso(bar + HOUR_MS + int(woke_seconds_after_close * 1000)),
        "window_seconds": window,
        "skip": False,
    }


def _miss(bar: str, late: float, counter: int, window: float = 73.7) -> dict[str, Any]:
    """A row exactly as `engine._record_missed_rebalance` writes it."""
    return {
        "bar": bar,
        "phase": "SKIPPED",
        "reason": MISSED,
        "late_seconds": late,
        "window_seconds": window,
        "missed_rebalances": counter,
    }


def test_a_clean_day_costs_nothing() -> None:
    cost = restart_cost([_cycle(0), _cycle(1)])

    assert cost["missed_rebalances"] == 0
    assert cost["skipped_bars"] == 0
    assert cost["worst_late_seconds"] is None
    assert cost["late_bars"] == 0
    assert cost["late_cycle_share"] == 0.0
    assert cost["status"] == "OK"
    assert cost["reasons"] == []


def test_a_late_restart_is_counted_not_assumed() -> None:
    """The real row from restart #1: 972.8s after the close, one rebalance skipped."""
    rows = [_cycle(0), _miss("t2", 972.814, 1)]

    cost = restart_cost(rows)

    assert cost["missed_rebalances"] == 1
    assert cost["skipped_bars"] == 1
    # 2026-09-10: a restart's lateness is reported under its own name.  It was never a late WAKE-UP -
    # nobody scheduled it - and while it shared `worst_late_seconds` with the wake-ups, that field
    # could hold nothing else, which is how the share came to measure restart frequency.
    assert cost["worst_restart_late_seconds"] == 972.814
    assert cost["restarts"] == 1
    assert cost["late_bars"] == 0


def test_a_prompt_restart_is_late_but_not_missed() -> None:
    """Restart #2 landed inside the window, so it traded and the engine wrote it as an ordinary cycle.

    2026-09-10: the row this used to assert on - `{"bar": "t1", "late_seconds": 7.4}` - is not a shape
    the engine produces.  A restart inside the window takes the normal path and writes a normal cycle;
    only one outside it goes through `_record_missed_rebalance`.  The fixture now says that, and the
    claim is unchanged: prompt is not missed, and being 7.4s after the close is not being late.
    """
    cost = restart_cost([_cycle(0, woke_seconds_after_close=7.4)])

    assert cost["late_bars"] == 0
    assert cost["worst_late_seconds"] is None
    assert cost["missed_rebalances"] == 0
    assert cost["skipped_bars"] == 0


def test_every_miss_writes_its_own_row_so_the_rows_are_the_count() -> None:
    """Two misses inside one process's life, and the running total agrees with the rows."""
    rows = [_miss("t1", 900.0, 1), _miss("t2", 1_000.0, 2)]

    assert restart_cost(rows)["missed_rebalances"] == 2


def test_three_processes_that_each_missed_one_are_three_and_not_one() -> None:
    """The real 2026-09-09 shape, and the reason this stopped reading the engine's counter.

    `missed_rebalances` is reset by every restart, so three consecutive processes that each missed
    exactly once write the column 1, 1, 1.  The old reconstruction looked for a DROP to detect a new
    process, found none, and reported 1 - undercounting by two on the very day the metric was first
    given a threshold.  Rows cannot lie about this: `_record_missed_rebalance` appends one per miss.
    """
    rows = [_miss("t1", 527.484, 1), _miss("t2", 1_114.144, 1), _miss("t3", 2_115.631, 1)]

    cost = restart_cost(rows)

    assert cost["missed_rebalances"] == 3
    assert cost["worst_restart_late_seconds"] == 2_115.631


def test_a_process_that_spans_midnight_does_not_charge_today_with_yesterdays_misses() -> None:
    """The other direction the running total was wrong in, and the one a day-scoped report cares about."""
    rows = [_miss("t1", 900.0, 4)]  # this process had already missed three, on an earlier day

    assert restart_cost(rows)["missed_rebalances"] == 1


def test_a_guard_skipped_cycle_is_not_a_missed_rebalance() -> None:
    """A cycle the guards skipped is the loop doing the right thing, not a restart costing something."""
    rows = [{"bar": "t1", "skip": True, "guard_reasons": ["DAILY_LOSS_PAUSE"]}, {"bar": "t2", "skip": False}]

    cost = restart_cost(rows)

    assert cost["missed_rebalances"] == 0
    assert cost["skipped_bars"] == 0
    assert cost["status"] == "OK"


# --- the judgement.  M-Q03's thresholds existed in a document and nothing compared anything to them --


def test_the_plans_bar_of_zero_missed_rebalances_is_enforced() -> None:
    """ "<= 5% / 0" - the second half is exactly zero, so one miss is a breach."""
    rows = [_cycle(i) for i in range(40)] + [_miss("t40", 972.814, 1)]

    cost = restart_cost(rows, params=RiskBudgetParams())

    assert cost["missed_rebalances"] == 1
    assert cost["late_cycle_share"] < cost["limits"]["late_cycle_share"]  # the share half passes
    assert cost["status"] == "ALERT"
    assert any("漏掉" in reason for reason in cost["reasons"])


def test_the_late_share_is_judged_per_cycle_against_the_five_percent_bar() -> None:
    """2026-09-09's shape: three restarts in one morning, and fifteen cycles that woke on time.

    2026-09-10 changed what this asserts, and the change is the ruling.  It used to read 16.7% -
    3 restart rows over 18 total rows - and call the day late.  Fifteen of those cycles woke within
    seconds of their close; not one of them was late.  What the day actually held was three restarts,
    one of which cost a rebalance, and M-Q03's two halves now say exactly that: `missed_rebalances` 3
    breaches the zero bar, and the share over SCHEDULED wake-ups is 0%.

    The old reading was not merely generous, it was unfalsifiable in the wrong direction: with the
    numerator restricted to restart rows and the denominator every row, running the loop MORE lowered
    the number, and a genuinely late wake-up could not raise it at all.
    """
    rows = [_cycle(i) for i in range(15)]
    rows += [_miss("t15", 527.484, 1), _miss("t16", 1_114.144, 1), _miss("t17", 2_115.631, 1)]

    cost = restart_cost(rows, params=RiskBudgetParams())

    assert cost["cycles"] == 18
    assert cost["restarts"] == 3
    assert cost["late_cycle_share"] == 0.0
    assert cost["missed_rebalances"] == 3
    assert cost["status"] == "ALERT"
    assert any("漏掉 3 次再平衡" in reason for reason in cost["reasons"])
    assert not any("迟到周期占比" in reason for reason in cost["reasons"])


def test_no_cycles_reports_no_share_rather_than_a_clean_zero() -> None:
    """A day the loop never ran is not a day it was never late; the whole file's refusal shape."""
    cost = restart_cost([], params=RiskBudgetParams())

    assert cost["late_cycle_share"] is None
    assert cost["status"] == "OK"


def test_the_fill_half_is_reported_and_never_judged() -> None:
    """M-Q03 is named "迟到成交" and the fills carry their own lateness; nothing has ever been late.

    Reported without a threshold on purpose.  Inventing a seconds bar for a fill is exactly the picked
    number KILL-R6 refuted, and the record says the question is not live anyway: across every fill ever
    written the worst is 26.3s, well inside the 72-98s rebalance windows the engine actually used.
    """
    trades = [{"late_seconds": 4.2}, {"late_seconds": 26.282}, {"avg_price": 1.0}]

    cost = restart_cost([{"bar": "t1"}], trades, RiskBudgetParams())

    assert cost["worst_late_fill_seconds"] == 26.282
    assert cost["fills_measured"] == 2
    assert not any("成交" in reason for reason in cost["reasons"])


# --- the reader.  `daily_alerts` did not look at `restarts` at all -----------------------------------


def _store_with_a_missed_rebalance(tmp_path: Path) -> Any:
    from starquant_live.state import StateStore

    base = 1_756_800_000_000  # 2025-09-02T08:00Z
    store = StateStore(tmp_path)
    # `at` is set explicitly.  `StateStore._append` stamps `utc_now_iso()` unless the record carries
    # one, so a fixture with a 2025 `bar_open_ms` and no `at` describes a cycle that woke a year after
    # its bar - which read as 32,221,562s of lateness the moment the share started reading these two
    # fields.  The engine writes both from the same cycle, so the fixture must too.
    store.append_cycle(
        {
            "bar_open_ms": base,
            "at": _iso(base + HOUR_MS + 14_000),
            "window_seconds": 73.7,
            "equity": 10_000.0,
            "skip": False,
            "guard_reasons": [],
            "targets": {},
            "orders": [],
        }
    )
    store.append_cycle(
        {
            "bar_open_ms": base + 3_600_000,
            "at": _iso(base + 2 * HOUR_MS + 972_814),
            "equity": 10_000.0,
            "skip": False,
            "guard_reasons": [],
            "targets": {},
            "orders": [],
            **_miss("t2", 972.814, 1),
        }
    )
    return store


def test_the_daily_report_carries_it(tmp_path: Path) -> None:
    """Through the real path, not a hand-built payload: a store, the report, the rendered section."""
    from starquant_live.reports import daily_markdown, daily_payload

    payload = daily_payload(_store_with_a_missed_rebalance(tmp_path), "2025-09-02", {})

    assert payload["restarts"]["missed_rebalances"] == 1
    assert payload["restarts"]["worst_restart_late_seconds"] == 972.814
    text = daily_markdown(payload)
    assert "missed_rebalances" in text
    assert "972.8" in text
    assert "M-Q03" in text
    assert "ALERT" in text


def test_the_breach_reaches_the_notices_rather_than_the_webhook(tmp_path: Path) -> None:
    """The plan's registered failure action is "查重启原因" - an investigation at review, not an act now.

    A missed rebalance is already past by the time the report runs, and `live status --check` already
    pages when the loop is actually DOWN.  Putting this on the paging path would hold the hourly check
    red for the rest of the UTC day after a single planned deployment restart, which is the repeated
    alert `alerts.py` says buries the one that matters.  Making it loud is moving one append.
    """
    from starquant_live.reports import daily_alerts, daily_payload

    alerts, notices = daily_alerts(daily_payload(_store_with_a_missed_rebalance(tmp_path), "2025-09-02", {}))

    assert not any("M-Q03" in line for line in alerts)
    assert any("M-Q03" in line for line in notices)
