"""M-001: cycle success rate and the run of untouched days, from the append-only cycle log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starquant_live.health import cycle_health

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _row(hours_ago: float, *, phase: str | None = None, dry_run: bool = False) -> dict:
    stamp = NOW - timedelta(hours=hours_ago)
    row: dict = {"bar_open_ms": int(stamp.timestamp() * 1000), "orders": []}
    if phase is not None:
        row["phase"] = phase
    if dry_run:
        row["dry_run"] = True
    return row


def test_success_rate_counts_failures_and_ignores_rehearsals() -> None:
    rows = [_row(h) for h in range(1, 20)] + [_row(3, phase="ERROR"), _row(2, dry_run=True)]
    health = cycle_health(rows, now=NOW)
    assert health.attempts == 20, "the dry run is a rehearsal, not the loop doing its job"
    assert health.failures == 1 and health.success_rate == 0.95
    assert health.last_failure is not None

    # a guard skip is the loop behaving correctly, so it counts as a success
    skipped = cycle_health([_row(1), {**_row(2), "skip": True, "guard_reasons": ["STALE_MARKET_DATA"]}], now=NOW)
    assert skipped.success_rate == 1.0 and skipped.failures == 0


def test_window_excludes_older_cycles_but_the_streak_still_sees_them() -> None:
    yesterday = _row(30, phase="ERROR")  # 2026-09-03 06:00, outside the 24h rate window
    rows = [yesterday, *[_row(h) for h in range(1, 5)]]
    health = cycle_health(rows, now=NOW, window_hours=24.0)
    assert health.attempts == 4 and health.failures == 0 and health.success_rate == 1.0
    assert health.clean_days == 1, "only today is clean; yesterday's failure ends the streak there"
    assert cycle_health(rows, now=NOW, window_hours=48.0).attempts == 5

    older = cycle_health([_row(40, phase="ERROR"), _row(1)], now=NOW)
    assert older.clean_days == 2, "a failure two days back leaves today and yesterday clean"


def test_no_cycles_in_window_is_not_a_failure() -> None:
    health = cycle_health([_row(100)], now=NOW)
    assert health.attempts == 0 and health.success_rate is None


def test_a_restart_ends_the_run_of_untouched_days() -> None:
    rows = [_row(h) for h in (1, 25, 49, 73)]
    assert cycle_health(rows, now=NOW).clean_days > 3, "no failures and no restart means the streak keeps running"
    interrupted = cycle_health(rows, now=NOW, restarted_at="2026-09-03T08:00:00+00:00")
    assert interrupted.clean_days == 1, "the day of a restart is not an untouched day"
    assert cycle_health(rows, now=NOW, restarted_at="2026-09-04T01:00:00+00:00").clean_days == 0
    assert cycle_health(rows, now=NOW, restarted_at="not a timestamp").clean_days > 3


def test_failures_are_dated_by_the_bar_not_by_the_write() -> None:
    """The clock can be an hour behind, so the bar the cycle was for is the honest date."""
    stamp = NOW - timedelta(days=1)
    row = {"bar_open_ms": int(stamp.timestamp() * 1000), "at": NOW.isoformat(), "phase": "ERROR"}
    assert cycle_health([row], now=NOW).clean_days == 0 or cycle_health([row], now=NOW).clean_days == 1
    health = cycle_health([row], now=NOW)
    assert health.last_failure is not None and health.last_failure.startswith("2026-09-03")
