"""The gate between `governance apply` and the registry: R3/R4/R5/R7 and K-EX14, asked before the write.

Found by the 2026-09-09 audit, and it is the largest instance of this repository's recurring defect:
a rule written down, versioned, hashed into `policy_digest()`, printed by `governance status` - and
consulted by nothing on the path that actually changes the book.

`governance apply` asked exactly two questions before writing: is the autonomy switch on, and does the
startup gate accept the result.  That gate (`registry_evidence_problems`) verifies evidence pointers,
their sha256 and the construction they were produced under.  It does not count probe slots, does not
sum fractions, does not know the book is frozen, and has never heard of a lifetime entry limit.  So
every constraint §3 lists as a precondition of `queued -> probe` was decorative on the one code path
that promotes.  Measured: raising `books.flow_short.fraction` from 0.333 to 0.9 in the proposed YAML
was accepted, 0.9 of the book to an unproven sleeve against a cap of 1/3, and the transaction log
recorded it as a clean APPLY by actor `machine`.

Two layers, because they fail differently:

* **the registry check** is a statement about the FILE - probe slots and the budget share, computed
  from the proposed bytes with no reference to any state.  It holds even when `governance_state.json`
  is missing or wrong, which matters because `state.load` reads an absent file as an EMPTY book and an
  empty book is headroom, not safety (that docstring records the same measurement).
* **the lifecycle check** is a statement about the TRANSITION, and it needs the state.  It runs per
  candidate whose exposure grows, and it is the only place R4/R5/R7 and K-EX14 can be asked.

Facts this module cannot measure are False, never defaulted True, and the refusal says which fact was
missing rather than which rule failed.  "Could not be computed" is not "passed" - the same rule the
drawdown ladder follows when no attribution row lands on a cycle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from starquant_alpha.registry import MAIN_BOOK, Registry
from starquant_governance.canary import evaluate as evaluate_canary
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, evaluate
from starquant_governance.policy import Policy


@dataclass(frozen=True)
class Admission:
    """Whether the write may happen, and everything that was measured to say so."""

    allowed: bool
    reasons: tuple[str, ...] = ()
    promoting: tuple[str, ...] = ()
    measured: Mapping[str, Any] = field(default_factory=dict)


def exposure(registry: Registry) -> dict[str, tuple[str, float]]:
    """Enabled strategy -> (book, the share of the main book it moves).

    The main book's own strategies are 1.0 by construction: they are the book.  A sleeve's share is
    its book's `fraction`, which is what `composition.build_model` scales its targets by, so this is
    the same number R3 budgets rather than a second reading of it.
    """
    out: dict[str, tuple[str, float]] = {}
    for entry in registry.strategies:
        if not entry.enabled:
            continue
        if entry.book == MAIN_BOOK:
            out[entry.id] = (MAIN_BOOK, 1.0)
            continue
        spec = registry.books.get(entry.book)
        out[entry.id] = (entry.book, float(spec.fraction) if spec is not None else 1.0)
    return out


def registry_refusals(after: Registry, policy: Policy) -> tuple[str, ...]:
    """R3 asked of the proposed file alone, so a missing or stale state cannot make it pass.

    This is deliberately NOT read off the lifecycle state.  R3 is a property of what the loop will
    hold after the restart, and the loop reads the registry - so the registry is the thing to measure.
    """
    sleeves = {name: share for name, (book, share) in exposure(after).items() if book != MAIN_BOOK}
    problems: list[str] = []
    if len(sleeves) > policy.max_concurrent_probes:
        problems.append(
            f"R3: {len(sleeves)} sleeves enabled ({', '.join(sorted(sleeves))}), "
            f"the cap is {policy.max_concurrent_probes}"
        )
    total = sum(sleeves.values())
    if total > policy.probe_budget_share + 1e-9:
        problems.append(
            f"R3: sleeve budget share {total:.4f} exceeds {policy.probe_budget_share:.4f} "
            f"({', '.join(f'{name}={share:.4f}' for name, share in sorted(sleeves.items()))})"
        )
    return tuple(problems)


def grew(before: Registry, after: Registry) -> tuple[str, ...]:
    """Strategies whose exposure the proposal increases - the ones a promotion rule has to answer for.

    Newly enabled, moved from the main book into a sleeve, or handed a larger share of the same book.
    A change that only REDUCES exposure is not a promotion and is never blocked here: §3's fast paths
    (a stop, a family-gate failure) go the other way and must not need a window to run in.
    """
    old, new = exposure(before), exposure(after)
    out = []
    for name, (_book, share) in sorted(new.items()):
        if name not in old or share > old[name][1] + 1e-9:
            out.append(name)
    return tuple(out)


def clean_days(
    cycles: Sequence[Mapping[str, Any]],
    *,
    aliases: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[float, str]:
    """K-EX14's clock: days since the CANONICAL construction last changed, read off the live record.

    The record is the only place this can be read.  `construction_fingerprint` is a hash, so the
    registry cannot say how long the current one has stood; only a series of cycles can.

    Canonical, not raw, and the difference is 4.2 days as of 2026-09-09: the raw digest has moved
    three times since 09-04 for changes that altered no behaviour (`unit_mode`, four `regime_*`
    fields), and `CONSTRUCTION_ALIASES` is where that was declared - on the READ side, before the new
    digest was ever written, so the declaration cannot be made to fit a digest after seeing it.  A
    clock on the raw digest would reset M-010 for a renamed field and hand the operator a 30-day wait
    for nothing; reading it here without the aliases would silently do exactly that.
    """
    resolve = dict(aliases or {})
    stamped = [
        (str(row.get("at")), resolve.get(str(row.get("construction")), str(row.get("construction"))))
        for row in cycles
        if row.get("construction")
    ]
    if not stamped:
        return 0.0, "no cycle carries a construction digest"
    current = stamped[-1][1]
    since = stamped[-1][0]
    for at, digest in reversed(stamped):
        if digest != current:
            break
        since = at
    try:
        started = datetime.fromisoformat(since)
    except ValueError:
        return 0.0, f"unreadable cycle timestamp {since!r}"
    moment = now or datetime.now(UTC)
    days = (moment - started).total_seconds() / 86_400.0
    return days, f"construction {current} unbroken since {since}"


def canary_health(
    shadow: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    *,
    gate_refusals: int = 0,
) -> tuple[bool, str]:
    """L4 as a fact the promotion rule can read, or the reason it is not one.

    An absent soak is False with its own sentence rather than a failed check, because "the canary
    never ran" and "the canary ran and found the deployment sick" are different operator actions.
    """
    if not shadow:
        return False, "L4: no shadow record; run deploy/run_shadow.sh first"
    result = evaluate_canary(shadow, baseline, gate_refusals=gate_refusals)
    if result.healthy:
        return True, f"L4: {len(result.checks)} checks pass over {result.soaked} soaked cycles"
    return False, "L4: " + "; ".join(f"{check.name} ({check.detail})" for check in result.failures)


#: The calendar §3's monthly windows are counted from: the day the current registry took effect, and
#: the same instant `governance tenure` anchors its window count on.  Not a threshold, so not in
#: `Policy`: it is a fact about this deployment, and moving it does not change any rule.
WINDOW_ANCHOR = "2026-09-03T00:00:00+00:00"


def window_index(policy: Policy, *, anchor: str = WINDOW_ANCHOR, now: datetime | None = None) -> int:
    """Which batch window we are in.  A calendar, not a counter, so nothing has to remember to tick it.

    `Book.open_next_window()` is the counter version and it is why this is a calendar: that method has
    never had a production caller, so `promotions_this_window` has read 0 since the state file was
    written by hand and would have counted a second promotion in the same hour as the first.  Derived
    from the clock, the same book rolls forward whether or not anybody remembered to roll it.
    """
    moment = now or datetime.now(UTC)
    elapsed = moment - datetime.fromisoformat(anchor)
    return max(0, int(elapsed / timedelta(days=policy.window_days)))


def window_start(policy: Policy, *, anchor: str = WINDOW_ANCHOR, now: datetime | None = None) -> datetime:
    """When the current window opened.  R1's budget is counted from here, off the same calendar.

    Here rather than in `budget.py` so there is exactly one calendar: R1 counts rows per window and
    R4 counts promotions per window, and if those two ever disagreed about where a window begins the
    disagreement would be invisible - each rule would keep passing its own tests.
    """
    return datetime.fromisoformat(anchor) + timedelta(days=policy.window_days) * window_index(
        policy, anchor=anchor, now=now
    )


def rolled(book: Book, policy: Policy, *, anchor: str = WINDOW_ANCHOR, now: datetime | None = None) -> tuple[Book, str]:
    """The book with its calendar caught up - per-window counters cleared for a window it has not seen.

    Rolling forward here rather than mutating the file means a stale state cannot BLOCK a promotion
    that the calendar allows, and cannot allow one it does not: the counters are re-derived every time
    the gate is asked.
    """
    index = window_index(policy, anchor=anchor, now=now)
    if book.window >= index:
        return book, f"window {book.window}, {book.promotions_this_window}/{policy.max_queued_to_probe_per_window} used"
    fresh = replace(book, window=index, promotions_this_window=0, to_main_this_window=0)
    return fresh, f"window {index} (state held {book.window}); per-window counters reset by the calendar"


def queue_head(book: Book, candidate_id: str) -> tuple[bool, str]:
    """§3's queue head, in the order the state now records (`Candidate.queued_at`, FIFO).

    Until 2026-09-12 the state stored no order at all, so this refused outright whenever two
    candidates were queued - honest about not inventing an order, but the consequence was a gate that
    could never open rather than one that was strict.  `apply` now stamps the arrival where the
    transition happens and `Book.queue` orders by it; `Policy.queue_order` records that the order is
    FIFO so that changing it is a rule version change (R10).

    The refusal is KEPT for the one case that still cannot be ordered: two or more queued candidates
    that all predate the stamp.  A tie broken by dictionary order would be the rule nobody wrote.
    """
    queue = book.queue
    others = [c.id for c in queue if c.id != candidate_id]
    if not others:
        return True, "no other candidate is queued"
    if all(c.queued_at == "" for c in queue):
        return False, (
            f"§3: {len(others)} other candidates are also queued ({', '.join(sorted(others))}); "
            "none carries an arrival stamp, so no order is recorded"
        )
    if queue[0].id == candidate_id:
        return True, f"head of {len(queue)} queued, arrived {queue[0].queued_at}"
    ahead = [c.id for c in queue if c.id != candidate_id][:3]
    return False, f"§3: not at the head of the queue; ahead of it: {', '.join(ahead)}"


def admit(
    before: Registry,
    after: Registry,
    *,
    book: Book,
    policy: Policy | None = None,
    cycles: Sequence[Mapping[str, Any]] = (),
    shadow: Sequence[Mapping[str, Any]] = (),
    aliases: Mapping[str, str] | None = None,
    anchor: str = WINDOW_ANCHOR,
    gate_refusals: int = 0,
    now: datetime | None = None,
) -> Admission:
    """May this registry change be written?  Both layers, with everything measured reported back."""
    policy = policy or Policy()
    reasons = list(registry_refusals(after, policy))
    promoting = grew(before, after)
    book, window_why = rolled(book, policy, anchor=anchor, now=now)

    days, days_why = clean_days(cycles, aliases=aliases, now=now)
    healthy, canary_why = canary_health(shadow, cycles, gate_refusals=gate_refusals)
    measured = {
        "clean_days": round(days, 3),
        "clean_days_detail": days_why,
        "canary": canary_why,
        "window": window_why,
        "sleeve_share": round(sum(s for b, s in exposure(after).values() if b != MAIN_BOOK), 6),
        "probes_in_state": len(book.probes),
    }

    for name in promoting:
        candidate = book.candidates.get(name) or Candidate(id=name)
        head, head_why = queue_head(book, name)
        share = exposure(after).get(name, (MAIN_BOOK, 0.0))[1]
        facts = Facts(
            # A calendar window is always open; what R4 limits is how many promotions happen inside
            # one, and `rolled` has already reset that counter if the calendar moved on.
            window_open=True,
            is_queue_head=head,
            canary_healthy=healthy,
            clean_days_under_current_construction=int(days),
        )
        decision = evaluate(
            book,
            # The fraction the proposal ASKS for, not the one the state remembers: R3's budget check
            # has to price the change, and a candidate at 0.0 in the state would price it as free.
            Candidate(
                id=candidate.id,
                state=candidate.state,
                probe_entries=candidate.probe_entries,
                windows_survived=candidate.windows_survived,
                fraction=share if share < 1.0 else candidate.fraction,
                cooldown_until_window=candidate.cooldown_until_window,
            ),
            Event.PROMOTE,
            facts,
            policy,
        )
        if not decision.allowed:
            reasons.extend(f"{name}: {reason}" for reason in decision.reasons)
            # The rule that failed names itself; the fact behind it does not, so it is carried out
            # separately.  "not at the head of the queue" and "two candidates are queued and nobody
            # said which is first" are the same refusal and different operator actions.
            measured.setdefault(f"{name}_queue", head_why)
    return Admission(not reasons, tuple(reasons), promoting, measured)
