"""The state machine of §3: candidate -> validated -> booked -> queued -> probe -> main, and back.

Pure and total.  Every transition is a function of the current state, one event and a context of
facts read off artefacts - never of anything this module fetches for itself.  That is what makes the
same code usable for the live decision and for the Phase 0 replay of decisions already taken.

Three properties the shape enforces rather than documents:

* **A refusal names a rule.**  Every reason string starts with the rule or condition that produced
  it, because the replay's whole job is to attribute a difference to something; "not promoted" with
  no rule attached is exactly the unattributed item AC-G0 forbids.
* **RETIRED is absorbing.**  R7 gives a candidate three lives, and a fourth would have to come from
  somewhere; there is no event that leaves RETIRED.
* **A no-decision cycle produces no state change at all.**  A demo-account reset arrives as a
  TRANSFER row with no fills and the path to the venue answers 503 in bursts; letting either count
  would let the plumbing retire a strategy (KILL-AR-20).

Persistence is deliberately absent in Phase 0.  These functions decide; nothing here writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from starquant_governance.policy import Policy


class State(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    BOOKED = "booked"
    QUEUED = "queued"
    PROBE = "probe"
    MAIN = "main"
    RETIRED = "retired"


class Event(StrEnum):
    VALIDATE = "validate"  # a validation report exists for this candidate
    BOOK = "book"  # a book report places it beside the running book
    PARITY = "parity"  # its inputs carry the live/research parity obligation (M-011)
    PROMOTE = "promote"  # the window is open and it is the head of the queue
    WINDOW_SURVIVED = "window_survived"  # a batch window closed with it still running
    PNL_STOP = "pnl_stop"  # the pre-registered P&L stop fired
    FAMILY_GATE_FAILED = "family_gate_failed"  # the quantile gate no longer passes on recomputation


@dataclass(frozen=True)
class Facts:
    """What the artefacts say.  Absent knowledge is False, never assumed true."""

    # candidate -> validated (DL-K3, D-020/D-028, KILL-AR-07)
    verdict_pass: bool = False
    prereg_before_report: bool = False
    quantile_gate_pass: bool = False
    evidence_construction_matches_live: bool = False
    # validated -> booked (D-018's six checks and the three limits beside them)
    book_checks_pass: bool = False
    slippage_stress_pass: bool = False
    max_correlation_with_running: float = 1.0
    turnover_ratio_to_main: float = 99.0
    # booked -> queued
    parity_met: bool = False
    # queued -> probe
    window_open: bool = False
    is_queue_head: bool = False
    canary_healthy: bool = False
    clean_days_under_current_construction: int = 0
    # probe -> main: R0 recomputed at today's bucket size (§3).  False by default like every other
    # fact here - a window that could not ask the question does not get to answer it.
    family_gate_still_passes: bool = False
    # a cycle that must not decide anything (KILL-AR-20)
    no_decision: bool = False


@dataclass(frozen=True)
class Candidate:
    id: str
    state: State = State.CANDIDATE
    probe_entries: int = 0  # R7: lifetime, not current
    windows_survived: int = 0
    fraction: float = 0.0  # share of the main book this sleeve moves, 0 outside probe/main
    cooldown_until_window: int = -1
    #: The last derived event this candidate has already absorbed, as the ISO instant the record
    #: stamps it with.  Bookkeeping, never a rule: nothing in `evaluate` reads it.  It exists because
    #: `probe_entries` is R7's LIFETIME count and `windows_survived` is monotone, so folding the same
    #: `cycles.jsonl` twice would spend a life the sleeve never used.  Held per candidate rather than
    #: per book because each sleeve's tenure starts and stops on its own clock.
    folded_through: str = ""
    #: When this candidate entered QUEUED, as an ISO instant.  §3's `queued -> probe` requires it to be
    #: "队首", and until 2026-09-12 nothing recorded an order at all - `queue_head` therefore refused
    #: outright whenever two candidates were queued, which is a gate that can never open rather than one
    #: that is strict.  Empty for a candidate that is not queued, and for any state written before this
    #: field existed; an unknown entry time sorts LAST, because "I do not know when it arrived" is not a
    #: claim to the front of a queue.
    queued_at: str = ""


@dataclass(frozen=True)
class Book:
    """The whole population, because R3/R4/R5 are properties of the book and not of a candidate."""

    window: int = 0
    candidates: Mapping[str, Candidate] = field(default_factory=dict)
    promotions_this_window: int = 0
    to_main_this_window: int = 0
    consecutive_probe_stops: int = 0
    frozen_until_window: int = -1

    @property
    def probes(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates.values() if c.state is State.PROBE)

    @property
    def queue(self) -> tuple[Candidate, ...]:
        """Queued candidates in the order §3's "队首" means: the order they arrived.

        FIFO is chosen because it is the definitional reading of a queue, and because every
        alternative - by marginal Sharpe, by evidence date, by fraction - is a SELECTION rule that
        would need its own pre-registration and would let a candidate improve its place by being
        re-scored.  `Policy.queue_order` records the choice so that changing it is a rule version
        change (R10) rather than an edit.

        Candidates with no recorded arrival sort last, then by id so the order is total and stable.
        """
        queued = [c for c in self.candidates.values() if c.state is State.QUEUED]
        return tuple(sorted(queued, key=lambda c: (c.queued_at == "", c.queued_at, c.id)))

    @property
    def probe_fraction(self) -> float:
        return sum(c.fraction for c in self.probes)

    def frozen(self) -> bool:
        return self.window <= self.frozen_until_window

    def open_next_window(self) -> Book:
        """Roll the calendar.  Per-window counters reset; the freeze counts down with it."""
        return replace(self, window=self.window + 1, promotions_this_window=0, to_main_this_window=0)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    state: State
    reasons: tuple[str, ...] = ()


def _guard(checks: list[tuple[bool, str]]) -> tuple[str, ...]:
    return tuple(reason for ok, reason in checks if not ok)


def evaluate(book: Book, candidate: Candidate, event: Event, facts: Facts, policy: Policy) -> Decision:
    """What the rules say about one event, without applying it.

    Split from `apply` so the replay can ask "what would the machine have said" about a decision a
    person already took, which is the only way a difference list can exist.
    """
    if facts.no_decision:
        return Decision(False, candidate.state, ("no-decision: ERROR phase or rebaselined cycle (KILL-AR-20)",))
    if candidate.state is State.RETIRED:
        return Decision(False, State.RETIRED, ("R7: retired is absorbing",))

    if event is Event.VALIDATE and candidate.state is State.CANDIDATE:
        blocked = _guard(
            [
                (facts.prereg_before_report, "DL-K3: pre-registration is not earlier than the report"),
                (facts.verdict_pass, "D-020: verdict is not PASS"),
                (facts.quantile_gate_pass, "R0: OOS Sharpe below the quantile gate on the strategy bucket"),
                (
                    facts.evidence_construction_matches_live,
                    "KILL-AR-07: the evidence was produced under a different construction than the loop holds",
                ),
            ]
        )
        return Decision(not blocked, State.VALIDATED if not blocked else candidate.state, blocked)

    if event is Event.BOOK and candidate.state is State.VALIDATED:
        blocked = _guard(
            [
                (facts.book_checks_pass, "D-018: the book-level checks do not pass"),
                (facts.slippage_stress_pass, "D-018: slippage stress at 5.5 bps does not hold"),
                (facts.max_correlation_with_running < 0.5, "§3: correlation with a running book >= 0.5"),
                (facts.turnover_ratio_to_main <= 3.0, "§3: turnover above 3x the main book"),
            ]
        )
        return Decision(not blocked, State.BOOKED if not blocked else candidate.state, blocked)

    if event is Event.PARITY and candidate.state is State.BOOKED:
        blocked = _guard([(facts.parity_met, "M-011: the panel parity obligation is unmet")])
        return Decision(not blocked, State.QUEUED if not blocked else candidate.state, blocked)

    if event is Event.PROMOTE and candidate.state is State.QUEUED:
        room = policy.probe_budget_share - book.probe_fraction
        blocked = _guard(
            [
                (facts.window_open, "§3: outside a batch window"),
                (not book.frozen(), f"R5: promotion frozen until window {book.frozen_until_window}"),
                (book.window >= candidate.cooldown_until_window, "R7: still inside the post-demotion cooldown"),
                (len(book.probes) < policy.max_concurrent_probes, "R3: probe slots full"),
                (candidate.fraction <= room + 1e-9, "R3: probe budget share would exceed 1/3"),
                (
                    book.promotions_this_window < policy.max_queued_to_probe_per_window,
                    "R4: a promotion already happened this window",
                ),
                (facts.is_queue_head, "§3: not at the head of the queue"),
                (facts.canary_healthy, "L4: the canary soak did not pass"),
                (
                    facts.clean_days_under_current_construction >= policy.min_clean_days_before_promotion,
                    "K-EX14: M-010 has not yet run 30 clean days under the current construction",
                ),
                (candidate.probe_entries < policy.max_probe_entries_lifetime, "R7: three probe entries already used"),
            ]
        )
        return Decision(not blocked, State.PROBE if not blocked else candidate.state, blocked)

    if event is Event.WINDOW_SURVIVED and candidate.state is State.PROBE:
        survived = candidate.windows_survived + 1
        if survived < policy.windows_to_main:
            return Decision(True, State.PROBE, (f"§3: {survived}/{policy.windows_to_main} windows survived",))
        blocked = _guard(
            [
                (
                    book.to_main_this_window < policy.max_probe_to_main_per_window,
                    "R4: a probe already reached main this window",
                ),
                # §3 lists three conditions on this edge and this one had no branch until 2026-09-09.
                # It is the only one that can go the other way while the sleeve does nothing: the gate
                # is a function of the bucket's trial count, which every search in the family raises.
                (
                    facts.family_gate_still_passes,
                    "R0: the quantile gate no longer passes at today's bucket size (family_gate.recheck)",
                ),
            ]
        )
        return Decision(not blocked, State.MAIN if not blocked else State.PROBE, blocked)

    if event is Event.PNL_STOP and candidate.state in (State.PROBE, State.MAIN):
        # A main sleeve that stops goes back to probe and recounts; a probe that stops is out.  R7
        # decides whether "out" means retired now or a queue it may re-enter twice more.
        if candidate.state is State.MAIN:
            return Decision(True, State.PROBE, ("§3: main touched the P&L stop, back to probe",))
        exhausted = candidate.probe_entries >= policy.max_probe_entries_lifetime
        return Decision(True, State.RETIRED if exhausted else State.QUEUED, ("§3: probe hit the P&L stop",))

    # Operator ruling 2026-09-23: a failed recomputation sends a main back to probe, the way its P&L
    # stop does, and it re-earns main through the WINDOW_SURVIVED edge above, whose third condition is
    # this same gate.  It used to retire.  A probe that fails stays a probe instead of retiring, or the
    # next failing reading would retire the main just demoted: retirement with a delay, not demotion.
    if event is Event.FAMILY_GATE_FAILED and candidate.state is State.MAIN:
        return Decision(True, State.PROBE, ("R0: the quantile gate no longer passes on recomputation, back to probe",))
    if event is Event.FAMILY_GATE_FAILED and candidate.state is State.PROBE:
        return Decision(False, State.PROBE, ("R0: already probe, and this reading already blocks probe -> main",))

    return Decision(False, candidate.state, (f"§3: {event.value} is not a legal event in {candidate.state.value}",))


def apply(
    book: Book,
    candidate_id: str,
    event: Event,
    facts: Facts,
    policy: Policy,
    *,
    now: datetime | None = None,
) -> tuple[Book, Decision]:
    """Evaluate, then fold the consequence into the book's counters.

    The counters are the reason this is not simply `evaluate` plus a dict write.  R4 counts
    promotions per window; R5 counts *consecutive* probe stops, so a probe reaching main resets it;
    and R7's lifetime count increments on entry rather than on exit, so a candidate cannot buy a
    fourth life by being demoted before the counter moves.

    One asymmetry worth stating, because it looks like a bug: a survived window advances
    `windows_survived` even when the move to main is refused.  R4's one-per-window limit is about the
    promotion slot, not about the record - the window WAS survived, and a candidate held back by
    another candidate's promotion is first in line next window rather than sent back a window.
    """
    candidate = book.candidates[candidate_id]
    decision = evaluate(book, candidate, event, facts, policy)
    if facts.no_decision:
        return book, decision

    updated = candidate
    promotions = book.promotions_this_window
    to_main = book.to_main_this_window
    stops = book.consecutive_probe_stops
    frozen_until = book.frozen_until_window

    if event is Event.WINDOW_SURVIVED and candidate.state is State.PROBE:
        updated = replace(updated, windows_survived=candidate.windows_survived + 1)

    if decision.allowed and decision.state is not candidate.state:
        updated = replace(updated, state=decision.state)
        # The arrival stamp §3's "队首" needs.  Written where the transition happens, so the order is
        # a fact of the record rather than of whoever reads it later; cleared on the way out, so a
        # candidate that leaves the queue and comes back takes its place at the BACK - which is what
        # R7's "three lives" would otherwise quietly hand back as a front-of-queue seat.
        if decision.state is State.QUEUED:
            updated = replace(updated, queued_at=(now or datetime.now(UTC)).isoformat())
        elif candidate.state is State.QUEUED:
            updated = replace(updated, queued_at="")
        if decision.state is State.PROBE and candidate.state is State.QUEUED:
            promotions += 1
            updated = replace(updated, probe_entries=candidate.probe_entries + 1, windows_survived=0)
        elif decision.state is State.MAIN:
            to_main += 1
            stops = 0
        elif candidate.state is State.PROBE and event is Event.PNL_STOP:
            stops += 1
            updated = replace(
                updated,
                fraction=0.0,
                windows_survived=0,
                cooldown_until_window=book.window + policy.demotion_cooldown_windows,
            )
            if stops >= policy.freeze_after_consecutive_stops:
                frozen_until = book.window + policy.freeze_windows
        elif candidate.state is State.MAIN and event in (Event.PNL_STOP, Event.FAMILY_GATE_FAILED):
            updated = replace(updated, windows_survived=0)
        if decision.state is State.RETIRED:
            updated = replace(updated, fraction=0.0)

    if updated == candidate:
        return book, decision
    candidates = dict(book.candidates)
    candidates[candidate_id] = updated
    return (
        replace(
            book,
            candidates=candidates,
            promotions_this_window=promotions,
            to_main_this_window=to_main,
            consecutive_probe_stops=stops,
            frozen_until_window=frozen_until,
        ),
        decision,
    )
