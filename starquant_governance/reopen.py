"""The reopen conditions, with a reader.  Until 2026-09-10 they had thirteen authors and none.

The 2026-09-09 audit found `REFUTED` written 69 times in `RESEARCH_LOG.md` and thirteen blocks headed
「重开条件」 - carefully worded, each naming what would have to become true for a closed hypothesis to
be looked at again.  A full-tree grep for `REFUTED` and `reopen` across `starquant_governance/` and
`governance_cmd.py` returned nothing.  Nothing read them, nothing tracked them, and nothing would ever
say that one had come true.

So the mechanism was a convention.  The concrete cost, measured the same day: carry's condition is
"块 1 的数据宽度", and `data spot`, `data index`, `data onchain` and `data macro` all landed between
2026-09-09 and 2026-09-10.  Whether that IS the width carry meant is a judgement - but nothing had
told anybody there was a judgement to make.  A hypothesis stays closed by neglect rather than by
evidence, which is the same failure as a control that does not control, pointed the other way.

**What this module refuses to do.**  Nine of the thirteen conditions cannot be asked of a machine:
they need a named ruling, a decision to pay for a data source, or a piece of research nobody has done.
Those are `operator`, and they are reported as `NEEDS A PERSON` - never as met, never as unmet, and
always counted, because a summary that read "0 met" over a list that is two-thirds unaskable would be
this file committing the very defect it exists to fix.  Turning a judgement into a predicate that
happens to be checkable is how a gate becomes decoration.

The conditions are quoted verbatim from the log.  Paraphrasing one would be loosening or tightening it
on the operator's behalf.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LIST = "governance/reopen.yaml"

MET = "MET"
NOT_MET = "NOT MET"
NEEDS_A_PERSON = "NEEDS A PERSON"
RESOLVED = "RESOLVED"
UNREADABLE = "UNREADABLE"

#: Checks a machine can answer.  Anything not here is a judgement, and `operator` says so out loud.
MACHINE_CHECKS = ("equity_at_least", "data_columns", "date_after")


@dataclass(frozen=True)
class Entry:
    """One closed hypothesis and what would reopen it."""

    id: str
    subject: str
    ruled: str
    verdict: str
    condition: str
    check: str
    args: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""
    log: str = ""


@dataclass(frozen=True)
class Status:
    entry: Entry
    state: str
    why: str

    @property
    def actionable(self) -> bool:
        """MET is the only state that asks for anything today."""
        return self.state == MET


def load(path: Path) -> list[Entry]:
    """Through `starquant_shared`, because `governance -> alpha, shared` and pyyaml is shared's to hold.

    That rule is why the file's top level is a mapping (`entries:`) rather than a bare list: `load_yaml`
    refuses anything else, and bending the loader to fit the file would put a second yaml reader in the
    tree to save one line in a data file.
    """
    from starquant_shared.config import load_yaml

    payload = load_yaml(path).get("entries") or []
    out: list[Entry] = []
    for row in payload:
        out.append(
            Entry(
                id=str(row.get("id", "")),
                subject=str(row.get("subject", "")),
                ruled=str(row.get("ruled", "")),
                verdict=str(row.get("verdict", "")),
                condition=" ".join(str(row.get("condition", "")).split()),
                check=str(row.get("check", "operator")),
                args=dict(row.get("args") or {}),
                note=" ".join(str(row.get("note", "")).split()),
                log=str(row.get("log", "")),
            )
        )
    return out


def evaluate(entry: Entry, facts: Mapping[str, Any]) -> Status:
    """One entry against today's facts.  Absent facts make a check UNREADABLE, never MET."""
    if entry.check == "resolved":
        return Status(entry, RESOLVED, entry.note or "already reopened")
    if entry.check == "operator":
        return Status(entry, NEEDS_A_PERSON, "a named ruling, a purchase, or research nobody has done")
    if entry.check not in MACHINE_CHECKS:
        return Status(entry, UNREADABLE, f"unknown check {entry.check!r}")

    # Each branch names its own locals.  They used to share `want` and `have`, which costs nothing at
    # runtime - the branches are exclusive and each returns - but reads to a type checker as one variable
    # that is a float here and a list of columns ten lines down.  Names only, no behaviour.
    if entry.check == "equity_at_least":
        want_usdt = float(entry.args.get("usdt", 0.0))
        have_equity = facts.get("equity")
        if not isinstance(have_equity, int | float):
            return Status(entry, UNREADABLE, "no equity in the live record")
        return Status(
            entry,
            MET if float(have_equity) >= want_usdt else NOT_MET,
            f"equity {float(have_equity):,.0f} vs {want_usdt:,.0f} USDT",
        )

    if entry.check == "data_columns":
        want_columns = [str(c) for c in entry.args.get("columns", ())]
        have_columns = {str(c) for c in facts.get("columns", ())}
        missing = [c for c in want_columns if c not in have_columns]
        return Status(
            entry,
            MET if not missing else NOT_MET,
            f"{len(want_columns) - len(missing)}/{len(want_columns)} present"
            + (f"; missing {', '.join(missing)}" if missing else ""),
        )

    when = str(entry.args.get("date", ""))
    now = facts.get("now")
    if not isinstance(now, datetime):
        now = datetime.now(UTC)
    try:
        due = datetime.fromisoformat(when)
    except ValueError:
        return Status(entry, UNREADABLE, f"unreadable date {when!r}")
    days = (due - now).total_seconds() / 86_400.0
    return Status(
        entry, MET if now >= due else NOT_MET, f"{when[:10]}" + (f", {days:.1f} days away" if days > 0 else "")
    )


def survey(entries: Iterable[Entry], facts: Mapping[str, Any]) -> list[Status]:
    return [evaluate(entry, facts) for entry in entries]


def render(statuses: Sequence[Status], hidden: int = 0) -> str:
    order = {MET: 0, NOT_MET: 1, UNREADABLE: 2, NEEDS_A_PERSON: 3, RESOLVED: 4}
    lines: list[str] = []
    for status in sorted(statuses, key=lambda s: (order.get(s.state, 9), s.entry.id)):
        lines.append(f"{status.state:<15s} {status.entry.id:<26s} {status.why}")
        lines.append(f"{'':15s} {status.entry.subject} - {status.entry.verdict} ({status.entry.ruled})")
        lines.append(f"{'':15s} 重开条件：{status.entry.condition}")
        if status.entry.note:
            lines.append(f"{'':15s} 注：{status.entry.note}")
        lines.append("")
    counts = {state: sum(1 for s in statuses if s.state == state) for state in order}
    # `hidden` is the RESOLVED entries the caller filtered out before surveying.  Without it the
    # summary read "12 条 ... RESOLVED 0" over a file holding thirteen, one of them resolved - a count
    # that is true of what was surveyed and false of what exists, which is the one thing a summary
    # line must not be.
    lines.append(
        f"{len(statuses) + hidden} 条：MET {counts[MET]}, NOT MET {counts[NOT_MET]}, "
        f"NEEDS A PERSON {counts[NEEDS_A_PERSON]}, RESOLVED {counts[RESOLVED] + hidden}, "
        f"UNREADABLE {counts[UNREADABLE]}" + (f"（其中 {hidden} 条 RESOLVED 未列出，用 --all 看）" if hidden else "")
    )
    if counts[NEEDS_A_PERSON]:
        # Said every time, because it is the number that decides whether this command is worth reading:
        # a machine cannot close these, and a summary that omitted them would read as an all-clear.
        lines.append(f"{counts[NEEDS_A_PERSON]} 条机器答不了——需要一次具名裁定、一次付费决定，或一次没人做过的研究。")
    return "\n".join(lines)
