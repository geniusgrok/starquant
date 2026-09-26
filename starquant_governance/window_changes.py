"""Construction changes waiting for a batch window, with a reader.  Same shape as `reopen.py`, same reason.

§8's Phase 4a is "块 4 必改项**一次改完** → 重启 → 攒 30 天干净窗口" - a plan that presumes a LIST of
construction changes applied together in one window.  That list never existed.  Each change was
decided in a log entry, and the log has no reader, so on the day a window opens nobody is told what it
was supposed to carry.  The 2026-09-10 audit found the same shape in thirteen reopen conditions; this
is it in the other direction - not a closed hypothesis nobody reopens, but an open decision nobody
applies.

The concrete cost, measured 2026-09-12: the probe stop's caliber was ruled, recalibrated, and all four
of its falsifiers passed - and it cannot ship, because `max_loss` is inside `construction_fingerprint`
and changing it clears M-010's window.  So it waits for 2026-10-03.  Without this file, the record of
"what to apply, with which measured values, and why it waited" would be one log entry among thirty.

**This module applies nothing.**  A batch window is an operator running `governance apply` through a
transaction; a command that could apply its own queue on a date is exactly the shape R10 forbids.  What
a machine can answer here is only whether the date has arrived - everything else (is the change still
right? has the measurement gone stale? is this the window to spend?) is a judgement, and the entries
say so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LIST = "governance/window_changes.yaml"

DUE = "DUE"
WAITING = "WAITING"
APPLIED = "APPLIED"
UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class Change:
    """One construction change decided outside a window, and what it is waiting for."""

    id: str
    subject: str
    queued: str = ""
    earliest_window: str = ""
    change: str = ""
    measured: str = ""
    why_it_waits: str = ""
    cost: str = ""
    prereg: str = ""
    verdict: str = ""
    applied: str = ""  # the transaction that carried it, once one has
    note: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Status:
    change: Change
    state: str
    why: str


def load(path: Path) -> list[Change]:
    """Through `starquant_shared`, because `governance -> alpha, shared` and pyyaml is shared's to hold."""
    from starquant_shared.config import load_yaml

    payload = load_yaml(path).get("entries") or []
    out: list[Change] = []
    for row in payload:
        known = {
            f: str(row.get(f, "") or "")
            for f in (
                "id",
                "subject",
                "queued",
                "earliest_window",
                "change",
                "measured",
                "why_it_waits",
                "cost",
                "prereg",
                "verdict",
                "applied",
                "note",
            )
        }
        out.append(Change(**known, extra={k: v for k, v in row.items() if k not in known}))
    return out


def evaluate(change: Change, now: datetime) -> Status:
    """Only the date is a machine's to answer.  Absent or unparseable is UNREADABLE, never DUE."""
    if change.applied:
        return Status(change, APPLIED, f"applied by {change.applied}")
    if not change.earliest_window:
        return Status(change, UNREADABLE, "no earliest window recorded")
    try:
        window = datetime.fromisoformat(change.earliest_window)
    except ValueError:
        return Status(change, UNREADABLE, f"unreadable window {change.earliest_window!r}")
    if window.tzinfo is None:
        window = window.replace(tzinfo=UTC)
    days = (window - now).total_seconds() / 86_400.0
    if days <= 0:
        return Status(change, DUE, f"window opened {-days:.1f} days ago ({change.earliest_window})")
    return Status(change, WAITING, f"{change.earliest_window}, {days:.1f} days away")


def survey(changes: Iterable[Change], now: datetime) -> list[Status]:
    return [evaluate(change, now) for change in changes]


def render(statuses: Sequence[Status]) -> str:
    order = {DUE: 0, UNREADABLE: 1, WAITING: 2, APPLIED: 3}
    lines: list[str] = []
    for status in sorted(statuses, key=lambda s: (order.get(s.state, 9), s.change.id)):
        change = status.change
        lines.append(f"{status.state:<10s} {change.id:<24s} {status.why}")
        lines.append(f"{'':10s} {change.subject}（{change.queued} 决定）")
        for label, value in (
            ("改什么", change.change),
            ("量到的", change.measured),
            ("为什么等", change.why_it_waits),
            ("代价", change.cost),
        ):
            if value:
                lines.append(f"{'':10s} {label}：{value}")
        pointers = "  ".join(f"{k} {v}" for k, v in (("预登记", change.prereg), ("裁定", change.verdict)) if v)
        if pointers:
            lines.append(f"{'':10s} {pointers}")
        if change.note:
            lines.append(f"{'':10s} 注：{change.note}")
        lines.append("")
    counts = {state: sum(1 for s in statuses if s.state == state) for state in order}
    lines.append(
        f"{len(statuses)} 条：DUE {counts[DUE]}, WAITING {counts[WAITING]}, "
        f"APPLIED {counts[APPLIED]}, UNREADABLE {counts[UNREADABLE]}"
    )
    if counts[DUE]:
        # Said every time there is one, because the whole point is that a window opens and nobody is told.
        lines.append(f"{counts[DUE]} 条的窗口已经开了——本命令不改任何东西，应用是一次 `governance apply` 事务。")
    return "\n".join(lines)


__all__ = [
    "APPLIED",
    "DUE",
    "LIST",
    "UNREADABLE",
    "WAITING",
    "Change",
    "Status",
    "evaluate",
    "load",
    "render",
    "survey",
]
