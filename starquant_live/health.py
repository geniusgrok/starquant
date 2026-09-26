"""M-001: how much of the loop's own job it actually did, from the append-only cycle log.

The plan promised two numbers and neither existed: a cycle success rate with a 95%
floor, and a run of days without intervention.  Both are computed here as pure
functions over ``cycles.jsonl`` rows so the threshold can be enforced wherever the
operator looks, and so the definitions are testable rather than implied.

"Unattended" is not directly observable - nobody records a human decision - so what
is measured is its closest honest proxy: a day is *clean* when every cycle that ran
that day completed and no restart happened.  A restart is either a crash or an
operator acting; either way the run of untouched days ends, which is exactly what the
metric is for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

#: When a run of ERROR cycles stops being the proxy blinking and becomes an incident.  `live status
#: --check` fails on `phase == "ERROR" and consecutive_errors >= 3`, which is the alarm that pages the
#: operator, and §5 L3's streak bar is the same number by construction: a week that contained an
#: incident the hourly check was paging about is not a week that proved unattended operation.  Defined
#: here rather than as a literal in each reader so the two cannot drift apart - if L3 and the hourly
#: check ever disagree about what "stuck" means, one of them has invented a number (KILL-R6).
STUCK_IN_ERROR_STREAK = 3


@dataclass(frozen=True)
class CycleHealth:
    attempts: int
    failures: int
    window_hours: float
    success_rate: float | None  # None when nothing ran in the window
    clean_days: int
    last_failure: str | None

    def restarts_note(self) -> str:
        return "无失败记录" if self.last_failure is None else f"最近一次失败在 {self.last_failure}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "failures": self.failures,
            "window_hours": self.window_hours,
            "success_rate": self.success_rate,
            "clean_days": self.clean_days,
            "last_failure": self.last_failure,
        }


def _stamp(row: Mapping[str, Any]) -> datetime | None:
    bar = row.get("bar_open_ms")
    if isinstance(bar, int | float):
        return datetime.fromtimestamp(float(bar) / 1000, tz=UTC)
    at = row.get("at")
    if at:
        try:
            return datetime.fromisoformat(str(at))
        except ValueError:
            return None
    return None


def cycle_health(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    window_hours: float = 24.0,
    restarted_at: str | None = None,
) -> CycleHealth:
    """Success rate over the trailing window, and the run of days with no failure and no restart.

    A failed cycle is a row with ``phase == "ERROR"`` (written since 2026-09-04); a
    guard-skipped cycle counts as a success, because the loop did the right thing.
    Dry-run rows are excluded: they are rehearsals, not the loop doing its job.
    """
    cutoff = now - timedelta(hours=window_hours)
    attempts = failures = 0
    failure_days: set[str] = set()
    last_failure: str | None = None
    for row in rows:
        if row.get("dry_run"):
            continue
        stamp = _stamp(row)
        if stamp is None:
            continue
        failed = str(row.get("phase", "")) == "ERROR"
        if failed:
            failure_days.add(stamp.strftime("%Y-%m-%d"))
            last_failure = stamp.isoformat()
        if stamp >= cutoff:
            attempts += 1
            failures += int(failed)
    rate = None if attempts == 0 else 1.0 - failures / attempts
    return CycleHealth(
        attempts=attempts,
        failures=failures,
        window_hours=window_hours,
        success_rate=rate,
        clean_days=_clean_days(now, failure_days, restarted_at),
        last_failure=last_failure,
    )


def _clean_days(now: datetime, failure_days: set[str], restarted_at: str | None) -> int:
    """Whole UTC days back from today with no failed cycle and no restart."""
    restart_day: str | None = None
    if restarted_at:
        try:
            restart_day = datetime.fromisoformat(restarted_at).astimezone(UTC).strftime("%Y-%m-%d")
        except ValueError:
            restart_day = None
    days = 0
    while True:
        day = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        if day in failure_days or day == restart_day:
            return days
        days += 1
        if days > 3650:  # a decade of clean days means the inputs are wrong, not that the loop is perfect
            return days


__all__ = ["CycleHealth", "cycle_health"]
