"""flow's gate is UNREADABLE, and the ruling of 2026-09-10 is that this already blocks it - proven here.

`governance gate` reads flow as UNREADABLE: its evidence report carries no `oos_selection` block, so
the D-028 quantile gate cannot be recomputed at today's bucket size at all.  tsmom's report has one and
reads PASS.  The obvious temptations are to treat "cannot ask" as "no objection", or to backfill the
block by re-running flow's validation - which would charge the ledger and raise the whole family's bar,
twenty-one months before the question is due.

Neither is needed, because absent knowledge is already False in both places it has to be:

* `GateReading.passes` is True only for PASS, so UNREADABLE and FAIL are alike to every caller.
* `Facts.family_gate_still_passes` defaults to False, and `governance advance` sets it from exactly
  that property, so an unreadable strategy reaches `lifecycle.apply` with the fact absent.

This file is the control that says so.  Writing "it is blocked" in a document is what §3's third
condition had instead of a branch for the eight months before 2026-09-09; the point of the whole audit
is that a claim with no executing check is not a control.

**The obligation, dated.**  flow's ninth surviving window is 2027-06.  Before then its evidence has to
carry an `oos_selection` block written under the gate in force - `research validate` produces one - or
flow cannot leave probe.  That is a deadline for the operator, not a defect: nothing is broken today,
and the loop is refusing in the safe direction.
"""

from __future__ import annotations

from starquant_governance.family_gate import FAIL, PASS, UNREADABLE, GateReading, failures
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State
from starquant_governance.policy import Policy


def _reading(status: str) -> GateReading:
    return GateReading("flow", status, "why")


def test_only_a_pass_passes() -> None:
    assert _reading(PASS).passes is True
    assert _reading(FAIL).passes is False
    assert _reading(UNREADABLE).passes is False, "cannot ask is not no objection"


def test_unreadable_is_not_reported_as_a_failed_gate() -> None:
    """The two are different operator actions: one re-validates evidence, one retires a book."""
    readings = (_reading(UNREADABLE), GateReading("tsmom", PASS, "why"))

    assert [reading.strategy for reading in failures(readings)] == []


def _every_other_condition_met() -> dict[str, object]:
    """Every §3 condition on `probe -> main` satisfied, so only the gate is left to decide.

    Built from `Facts`' own fields rather than a hand-listed set: a condition added later is then met
    here too, and this file keeps isolating the one variable it is about instead of quietly turning
    into a test that passes because something else refuses.
    """
    import dataclasses

    facts = {field.name: True for field in dataclasses.fields(Facts) if field.name != "no_decision"}
    facts["clean_days_under_current_construction"] = 999
    return facts


def _promote(**overrides: object) -> tuple[bool, str, tuple[str, ...]]:
    from starquant_governance.lifecycle import apply as apply_event

    book = Book(candidates={"flow": Candidate(id="flow", state=State.PROBE, windows_survived=9)})
    given = Facts(**{**_every_other_condition_met(), **overrides})  # type: ignore[arg-type]
    _, decision = apply_event(book, "flow", Event.WINDOW_SURVIVED, given, Policy())
    return decision.allowed, decision.state.value, tuple(decision.reasons)


def test_the_control_a_readable_passing_gate_does_reach_main() -> None:
    """Without this the refusal below proves nothing: it could be any of the other conditions."""
    allowed, state, reasons = _promote(family_gate_still_passes=True)

    assert (allowed, state, reasons) == (True, "main", ())


def test_a_probe_whose_gate_cannot_be_read_does_not_reach_main() -> None:
    """flow today.  One variable moved, and it is the only thing the refusal cites."""
    allowed, state, reasons = _promote(family_gate_still_passes=False)

    assert allowed is False
    assert state == "probe"
    assert reasons == ("R0: the quantile gate no longer passes at today's bucket size (family_gate.recheck)",)


def test_the_fact_defaults_to_absent_so_forgetting_to_pass_it_refuses() -> None:
    """The direction a missing argument has to fail in, checked rather than assumed."""
    assert Facts().family_gate_still_passes is False
