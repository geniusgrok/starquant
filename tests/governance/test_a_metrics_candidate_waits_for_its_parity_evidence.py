"""T-D4-2 / M-011: a candidate that reads a metrics column may not reach the queue on an unproven column.

Research eats a T+1 daily archive; the live loop can only read a 30-day REST window.  The two carry
the same numbers under different stamps, and the whole same-source contract is one question - do they
agree on the buckets they share?  `metrics_parity` has answered it since DL-D2 and, until DL-D4,
nothing called it.

The obligation is to have SHOWN parity.  A missing report, an unmeasurable one, and a symbol with no
overlapping buckets are all "no" - not "not yet disproved" - because the failure mode they share is a
snapshot stream that stopped recording, which looks healthiest exactly when it is most broken.
"""

from __future__ import annotations

from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.scheduler import parity_satisfied

CLEAN = {"enforced": True, "symbols_compared": 18, "unmeasurable": [], "worst_differing_rate": 0.0}


def test_a_clean_parity_report_lets_the_candidate_through() -> None:
    ok, reason = parity_satisfied(CLEAN)
    assert ok and "18 symbols agree" in reason


def test_no_report_is_no_rather_than_not_yet_disproved() -> None:
    assert parity_satisfied(None) == (False, "M-011: no metrics parity report")
    assert not parity_satisfied({})[0]


def test_an_unmeasurable_report_is_not_a_pass() -> None:
    """Zero disagreements out of zero comparisons is not agreement."""
    ok, reason = parity_satisfied({"enforced": False, "reason": "no overlapping buckets for any of 18 symbols"})
    assert not ok and "not measurable" in reason


def test_one_symbol_without_overlap_blocks_the_whole_universe() -> None:
    """A book trades a universe: parity the thinnest symbol does not have is not parity."""
    ok, reason = parity_satisfied({**CLEAN, "unmeasurable": ["CYSUSDT"]})
    assert not ok and "1 symbols have no overlapping buckets" in reason


def test_any_disagreement_at_all_blocks() -> None:
    assert not parity_satisfied({**CLEAN, "worst_differing_rate": 0.001})[0]
    assert not parity_satisfied({**CLEAN, "worst_differing_rate": None})[0]


def test_t_d4_2_the_candidate_stays_in_booked_until_parity_is_shown() -> None:
    """The state machine end of it: `booked -> queued` is the transition M-011 guards."""
    policy = Policy()
    book = Book(candidates={"mined_x": Candidate("mined_x", State.BOOKED)})

    blocked, decision = apply(book, "mined_x", Event.PARITY, Facts(parity_met=False), policy)
    assert blocked.candidates["mined_x"].state is State.BOOKED
    assert decision.reasons == ("M-011: the panel parity obligation is unmet",)

    allowed, decision = apply(book, "mined_x", Event.PARITY, Facts(parity_met=parity_satisfied(CLEAN)[0]), policy)
    assert allowed.candidates["mined_x"].state is State.QUEUED
    assert decision.allowed
