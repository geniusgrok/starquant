"""A restart that found a bar a failed cycle had already lost took the failure's charge over (🟡, 2026-09-23).

Restart #56, read off the record.  The scheduled cycle for the 2026-09-23T15:00Z bar failed at 16:01:02Z
on the proxy, and the 16:10Z hourly check said what had happened: one bar lost to a failed cycle, look at
the path to the venue, not at a restart - and it paged, because a lost bar is an hour with no stop check
(`daily_alerts`, 2026-09-16).  At 16:41:45Z restart #56's `--immediate` cycle found that same bar
unrebalanced, 2,505s past its close, and wrote the miss row a late restart writes.  From 17:11Z the same
one miss read as the restart's - "最迟的一次在 bar 收盘后 2505 秒；失败动作：查重启原因" - and the page
stopped, with seven hourly checks of the day still to run.

The cause was one set.  `restart_cost` put a skip row's bar in the set that excuses a failed bar, which is
meant for bars that got their rebalance after all.  So the second row did not add a charge; it took the
first one over.  The count was right, one bar and one miss.  The attribution was wrong, and the
attribution is the part that sends someone somewhere.  The record holds this shape twice: 2026-09-08T05:00
failed on the same proxy and a restart found it 17 minutes later.

What stays as it was: the restart is still a restart, counted, with its 2,505s; and a restart that finds a
bar ALREADY rebalanced still excuses a failure on it, because that bar did get its book set.

The two rows are the record's, verbatim, in `tests/fixtures/mq03/`, and are checked against the record
where it exists (the main checkout; CI and worktrees skip that one test).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from starquant_live.reports import daily_alerts, daily_payload, restart_cost
from starquant_live.scheduler import MISSED_REBALANCE_REASON
from starquant_live.state import StateStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mq03" / "cycles_2026-09-23T15.jsonl"
RECORD = ROOT / ".starquant" / "live" / "cycles.jsonl"
BAR = 1_790_175_600_000  # 2026-09-23T15:00:00Z


def _rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def test_the_fixture_is_the_failure_and_then_the_restart() -> None:
    """What every test below leans on, so an edit to the fixture cannot quietly change the case."""
    failed, skipped = _rows()

    assert (failed["bar_open_ms"], skipped["bar_open_ms"]) == (BAR, BAR)
    assert (failed["phase"], failed["error"], failed["orders"]) == ("ERROR", "ProxyError: 503 Service Unavailable", [])
    assert (skipped["phase"], skipped["reason"], skipped["late_seconds"]) == (
        "SKIPPED",
        MISSED_REBALANCE_REASON,
        2505.204,
    )


def test_the_bar_stays_a_failed_bar_after_the_restart_skips_it() -> None:
    cost = restart_cost(_rows())

    assert cost["failed_bars"] == 1, "the cycle failed on this bar 40 minutes before the restart"
    assert cost["missed_rebalances"] == 1, "one bar, one miss: the restart's row is not a second one"
    assert cost["skipped_bars"] == 0, "and the one miss is the failure's, not the restart's"
    assert cost["failed_bar_error"] == "ProxyError: 503 Service Unavailable"


def test_the_reason_sends_the_reader_to_the_path_not_to_the_restart() -> None:
    """16:10Z's reason, word for word, which 17:11Z replaced with the restart's."""
    (reason,) = restart_cost(_rows())["reasons"]

    assert reason == (
        "漏掉 1 次再平衡（M-Q03 阈值 0）；其中 1 根是周期失败（ProxyError: 503 Service Unavailable）；"
        "失败动作：查这条路径，不是重启"
    )


def test_the_restart_is_still_counted_with_its_own_lateness() -> None:
    cost = restart_cost(_rows())

    assert cost["restarts"] == 1
    assert cost["worst_restart_late_seconds"] == 2505.204
    assert cost["widest_window_seconds"] == 86.184
    # The failed cycle woke 62s after the close, inside its 86.184s window; restarts stay out of the share.
    assert (cost["scheduled_cycles"], cost["late_bars"], cost["late_cycle_share"]) == (1, 0, 0.0)


def test_the_restart_row_alone_is_still_a_restart_miss() -> None:
    """The control: with no failed cycle before it, the restart's row is the whole story."""
    _, skipped = _rows()
    cost = restart_cost([skipped])

    assert (cost["missed_rebalances"], cost["skipped_bars"], cost["failed_bars"]) == (1, 1, 0)
    (reason,) = cost["reasons"]
    assert reason.endswith("最迟的一次在 bar 收盘后 2505 秒；失败动作：查重启原因")


def test_the_failed_bar_pages_through_the_daily_report(tmp_path: Path) -> None:
    """The production path: the rows in a store, `daily_payload` picking the day's rows, `daily_alerts`."""
    store = StateStore(tmp_path)
    shutil.copyfile(FIXTURE, store.cycles_path)

    alerts, notices = daily_alerts(daily_payload(store, "2026-09-23", {}))

    assert [line for line in alerts if line.startswith("M-Q03")] == [
        "M-Q03 周期失败丢掉 1 根 bar（这些小时没有再平衡，也没有退出检查）："
        "ProxyError: 503 Service Unavailable；失败动作：查到交易所的这条路径"
    ]
    assert [line for line in notices if line.startswith("M-Q03")] == [
        "M-Q03 迟到成交：漏掉 1 次再平衡（M-Q03 阈值 0）；其中 1 根是周期失败（ProxyError: 503 Service Unavailable）；"
        "失败动作：查这条路径，不是重启"
    ]


@pytest.mark.skipif(not RECORD.exists(), reason="the live record is not in this checkout (CI and worktrees)")
def test_the_fixture_is_the_record_verbatim() -> None:
    """A fixture nobody can compare to its source is a fixture someone could have made up."""
    lines = []
    for line in RECORD.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("bar_open_ms") == BAR:
                lines.append(line)
        except ValueError:
            continue

    assert lines == FIXTURE.read_text(encoding="utf-8").splitlines()
