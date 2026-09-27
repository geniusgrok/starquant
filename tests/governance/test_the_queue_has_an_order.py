"""§3 requires a candidate to be "队首" before it may enter probe, and nothing recorded an order.

`queue_head`'s first version was honest about it - it refused whenever two candidates were queued,
rather than breaking the tie by dictionary order - but the consequence was a gate that **can never
open**, not one that is strict.  That is the half of the state machine the 2026-09-09 audit counted as
missing (eight of nine transitions implemented, this one half).

The order is FIFO by the instant a candidate entered QUEUED, recorded in `Policy.queue_order` so that
changing it is a rule version change (R10).  Every alternative - marginal Sharpe, evidence date,
fraction - is a SELECTION rule that would need its own pre-registration, and would let a candidate
improve its place by being re-scored.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starquant_governance.admission import queue_head
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.state import dump, load


def _queued(name: str, at: str) -> Candidate:
    return Candidate(id=name, state=State.QUEUED, queued_at=at)


def _book(*candidates: Candidate) -> Book:
    return Book(candidates={c.id: c for c in candidates})


def test_two_queued_candidates_now_have_a_head() -> None:
    """The shape that used to refuse forever."""
    book = _book(_queued("beta", "2026-09-11T10:00:00+00:00"), _queued("alpha", "2026-09-12T10:00:00+00:00"))
    assert [c.id for c in book.queue] == ["beta", "alpha"], "arrival order, not alphabetical"
    head, why = queue_head(book, "beta")
    assert head and "head of 2 queued" in why
    blocked, why_not = queue_head(book, "alpha")
    assert not blocked and "ahead of it: beta" in why_not


def test_an_unstamped_pair_is_still_refused_rather_than_ordered_by_name() -> None:
    """Legacy state carries no stamp, and a tie broken by dictionary order is the rule nobody wrote."""
    book = _book(_queued("alpha", ""), _queued("beta", ""))
    head, why = queue_head(book, "alpha")
    assert not head and "no order is recorded" in why


def test_an_unknown_arrival_sorts_behind_a_known_one() -> None:
    """ "I do not know when it arrived" is not a claim to the front of a queue."""
    book = _book(_queued("legacy", ""), _queued("stamped", "2026-09-12T10:00:00+00:00"))
    assert [c.id for c in book.queue] == ["stamped", "legacy"]
    assert queue_head(book, "stamped")[0] is True
    assert queue_head(book, "legacy")[0] is False


def test_the_stamp_is_written_where_the_transition_happens() -> None:
    book = Book(candidates={"c": Candidate(id="c", state=State.BOOKED)})
    moment = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
    after, decision = apply(book, "c", Event.PARITY, Facts(parity_met=True), Policy(), now=moment)
    assert decision.state is State.QUEUED
    assert after.candidates["c"].queued_at == moment.isoformat()


def test_leaving_the_queue_sends_a_candidate_to_the_back_when_it_returns() -> None:
    """R7 gives three lives; it must not also hand back a front-of-queue seat."""
    moment = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
    book = Book(candidates={"c": Candidate(id="c", state=State.BOOKED)})
    book, _ = apply(book, "c", Event.PARITY, Facts(parity_met=True), Policy(), now=moment)
    first = book.candidates["c"].queued_at
    promoted, decision = apply(
        book,
        "c",
        Event.PROMOTE,
        Facts(window_open=True, is_queue_head=True, canary_healthy=True, clean_days_under_current_construction=30),
        Policy(),
        now=moment,
    )
    assert decision.state is State.PROBE
    assert promoted.candidates["c"].queued_at == "", "the stamp is cleared on the way out"
    assert first != ""


def test_the_stamp_survives_the_state_file() -> None:
    """An order that does not round-trip is an order that resets every time the process does."""
    book = _book(_queued("beta", "2026-09-11T10:00:00+00:00"), _queued("alpha", "2026-09-12T10:00:00+00:00"))
    assert [c.id for c in load(dump(book)).queue] == ["beta", "alpha"]


def test_policy_records_which_order_it_is() -> None:
    assert Policy().queue_order == "fifo"
