"""DL-G6′: the time rule's events, derived from the live record rather than asserted by hand.

`lifecycle.py` already decides what `WINDOW_SURVIVED` and `PNL_STOP` mean.  Nothing produced them.
The state machine was therefore complete and unreachable: a probe could not reach main, and a main
sleeve could not be sent back, because the only way to move either was for a person to type the event
-- which is exactly the hand-driven promotion §3 exists to remove.

This module is the missing half and nothing more.  It reads `cycles.jsonl`, which is append-only and
carries per cycle the three things the rule needs -- `at`, each probe's `stop`, and `external_flows`
-- and returns the ordered events that record implies.  It decides nothing, writes nothing, and asks
the venue nothing; `evaluate`/`apply` still hold every rule.

**Why it lives here and not in `scheduler.py`.**  The scheduler must never touch `.starquant/live` (its
own docstring says so, and the reason is that a research run's timing would otherwise become a
function of what the book happens to be doing).  The time rule is the opposite: it is a statement
ABOUT the live record.  So it runs on the trading machine, beside the transaction that would act on
it, and reaches the research machine the way everything else does -- through the ledger and the repo.

**The TRANSFER exclusion (T-G6′-3), and why skipping is safe.**  This account is a demo account whose
resets show up as TRANSFER income rows with no fills; equity jumps and the attributed window shows a
loss nobody traded.  A stop reported on such a cycle is not evidence the sleeve lost money, so it is
recorded as skipped, with the reason, instead of counted.

Skipping cannot lose a real stop.  `probe_status` recomputes a TRAILING window every cycle, so a stop
that is real is still true on the next uncontaminated cycle and is counted there.  The exclusion
therefore delays a genuine stop by at most the flow's own cycles, and refuses a spurious one
outright.  That asymmetry is the whole reason it is a skip list rather than a filter: what was
refused, and why, stays readable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from starquant_governance.lifecycle import Event
from starquant_governance.policy import Policy

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Derived:
    """One event the record implies, with the row that implies it."""

    at: str
    event: Event
    why: str


@dataclass(frozen=True)
class Skipped:
    """A stop the record reported and this module refused to count, and the reason."""

    at: str
    why: str


@dataclass(frozen=True)
class Tenure:
    """What the record says about one sleeve, in order."""

    book: str
    strategy: str  # the registry entry id; `governance_state.json` keys on THIS, not on the book name
    events: tuple[Derived, ...]
    skipped: tuple[Skipped, ...]
    windows_survived: int
    stopped_at: str | None
    cycles_read: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "book": self.book,
            "strategy": self.strategy,
            "windows_survived": self.windows_survived,
            "stopped_at": self.stopped_at,
            "cycles_read": self.cycles_read,
            "events": [{"at": e.at, "event": str(e.event), "why": e.why} for e in self.events],
            "skipped": [{"at": s.at, "why": s.why} for s in self.skipped],
        }


def _parsed(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def flow_contaminated(row: Mapping[str, Any], policy: Policy | None = None) -> str | None:
    """Why this cycle's attributed P&L cannot be read as trading, or None when it can.

    Two independent signals, because they fail in different directions: a non-zero flow total means
    money entered or left inside the attributed window, and `rebaselined` means the engine itself
    decided the equity mark it was measuring against had moved.  Either one is enough.

    The rebaseline clause reads `policy.no_decision_on_rebaseline` rather than assuming it: that field
    is inside `policy_digest()`, so the digest promised an edit to it would be visible, and until this
    argument existed an edit changed nothing at all.
    """
    flows = row.get("external_flows")
    if not isinstance(flows, Mapping):
        return None
    if flows.get("rebaselined") and (policy or Policy()).no_decision_on_rebaseline:
        return "equity was rebaselined on an external flow"
    try:
        total = float(flows.get("total", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if total != 0.0:
        by_type = flows.get("by_type") or {}
        kinds = ",".join(sorted(str(k) for k in by_type)) if isinstance(by_type, Mapping) else ""
        return f"external flow {total:+.2f} in this cycle" + (f" ({kinds})" if kinds else "")
    return None


def _probe_row(row: Mapping[str, Any], book: str) -> Mapping[str, Any] | None:
    probes = row.get("probes")
    if isinstance(probes, Mapping):  # older rows recorded a {book: status} mapping
        status = probes.get(book)
        return {"book": book, "status": status, "stop": status == "STOP"} if status is not None else None
    if not isinstance(probes, Sequence):
        return None
    for entry in probes:
        if isinstance(entry, Mapping) and str(entry.get("book")) == book:
            return entry
    return None


def windows(anchor: datetime, *, policy: Policy, now: datetime) -> list[tuple[int, datetime, datetime]]:
    """The batch windows that have CLOSED, as `(index, opened, closed)`, counted from one anchor.

    Global, not per sleeve.  §3's window is the batch window -- the same calendar R4 counts one
    queued->probe and one probe->main against -- so anchoring it on each sleeve's own start would
    give every sleeve a private calendar and make `Book.window` mean nothing.  A sleeve that entered
    mid-window simply does not get that window; see `tenure`.
    """
    span = timedelta(days=policy.window_days)
    out: list[tuple[int, datetime, datetime]] = []
    index = 0
    opened = anchor
    while opened + span <= now:
        out.append((index, opened, opened + span))
        index += 1
        opened = opened + span
    return out


def tenure(
    rows: Sequence[Mapping[str, Any]],
    *,
    book: str,
    started_at: str,
    window_anchor: str,
    policy: Policy | None = None,
    now: datetime | None = None,
) -> Tenure:
    """The events `cycles.jsonl` implies for one sleeve, from `started_at` to the first counted stop.

    A window counts as survived only when all three are true, and the third is the one that is easy
    to leave out:

    1. it closed before `now`;
    2. the sleeve was already running when it OPENED -- a sleeve promoted mid-window does not get
       credit for the part it was not there for;
    3. the record has at least one cycle inside it.  A window the loop spent down is not a window
       the sleeve survived, and with no cycles there is nothing that could have reported a stop.
       Absent knowledge is not survival.

    Event derivation stops at the first counted stop on purpose (the rows are still all read, for
    the per-window cycle counts).  What follows that stop is a DIFFERENT tenure -- the
    state machine sends a stopped main back to probe and a stopped probe out -- and deriving both
    sides from one pass would need this module to know which branch `evaluate` took.  It does not,
    and it must not: the caller folds the stop through `apply` and, if the sleeve is still alive,
    calls again with the new start.
    """
    policy = policy or Policy()
    start = _parsed(started_at)
    anchor = _parsed(window_anchor)
    if start is None or anchor is None:
        raise ValueError(f"tenure needs ISO timestamps for {book}, got {started_at!r} / {window_anchor!r}")
    horizon = now or datetime.now(UTC)

    events: list[Derived] = []
    skipped: list[Skipped] = []

    # One pass over the record: the first counted stop, and the cycles each window actually saw.
    stopped_at: str | None = None
    stopped_when: datetime | None = None
    strategy = ""
    read = 0
    seen: dict[int, int] = {}
    closed = windows(anchor, policy=policy, now=horizon)
    for row in rows:
        stamp = _parsed(row.get("at"))
        if stamp is None or stamp < start or stamp > horizon:
            continue
        read += 1
        for index, opened, shut in closed:
            if opened <= stamp < shut:
                seen[index] = seen.get(index, 0) + 1
                break
        probe = _probe_row(row, book)
        if probe is not None and not strategy and probe.get("strategy"):
            strategy = str(probe["strategy"])
        if stopped_at is not None or probe is None or not probe.get("stop"):
            continue
        contamination = flow_contaminated(row, policy)
        if contamination is not None:
            skipped.append(Skipped(at=str(row.get("at")), why=f"T-G6\u2032-3: {contamination}"))
            continue
        stopped_at, stopped_when = str(row.get("at")), stamp

    survived = 0
    for index, opened, shut in closed:
        if stopped_when is not None and stopped_when < shut:
            break  # the stop lands inside (or before) this window; it was not survived
        if opened < start or not seen.get(index):
            continue
        survived += 1
        events.append(
            Derived(
                at=shut.isoformat(),
                event=Event.WINDOW_SURVIVED,
                why=(
                    f"\u00a73: batch window {index} closed with the sleeve running "
                    f"({seen[index]} cycles); {survived}/{policy.windows_to_main} survived"
                ),
            )
        )
    if stopped_at is not None:
        probe_pct = None
        for row in rows:
            if str(row.get("at")) == stopped_at:
                entry = _probe_row(row, book) or {}
                probe_pct = entry.get("pnl_pct")
                break
        detail = f" (attributed {float(probe_pct):+.4%})" if isinstance(probe_pct, int | float) else ""
        events.append(
            Derived(at=stopped_at, event=Event.PNL_STOP, why=f"\u00a73: the pre-registered P&L stop fired{detail}")
        )

    return Tenure(
        book=book,
        strategy=strategy,
        events=tuple(events),
        skipped=tuple(skipped),
        windows_survived=survived,
        stopped_at=stopped_at,
        cycles_read=read,
    )


def books_in(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Every book the record has ever reported a probe row for, in first-seen order."""
    seen: dict[str, None] = {}
    for row in rows:
        probes = row.get("probes")
        if isinstance(probes, Mapping):
            for name in probes:
                seen.setdefault(str(name), None)
        elif isinstance(probes, Sequence):
            for entry in probes:
                if isinstance(entry, Mapping) and entry.get("book") is not None:
                    seen.setdefault(str(entry["book"]), None)
    return tuple(seen)


__all__ = ["DAY_MS", "Derived", "Skipped", "Tenure", "books_in", "flow_contaminated", "tenure", "windows"]
