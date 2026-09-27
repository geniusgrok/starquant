"""KILL-AR-06's grandfather, written down -- because an empty book PERMITS, it does not refuse.

`state.py` says an unreadable state is an empty book, and that this is safe because "an empty book has
no probes, so every rule that could act on it refuses for want of a candidate".  That is true only of
the candidate being evaluated.  Every rule that reads the book for CONSTRAINTS reads an empty one as
headroom: `len(book.probes)` is 0 against R3's 2, and `book.probe_fraction` is 0.0 against the 1/3
cap.  Measured 2026-09-09 with no state file on the trading machine: a second 1/3 probe was ALLOWED
on top of the flow probe that was already running live -- 2/3 of the book against a 1/3 cap, and no
rule anywhere would have said a word.

So the two sleeves the plan grandfathered have to be IN the state, not merely true of the world.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, evaluate
from starquant_governance.policy import Policy
from starquant_governance.state import read as read_state

STATE = Path("governance/governance_state.json")


def test_the_shipped_state_holds_the_two_sleeves_the_plan_grandfathered() -> None:
    """KILL-AR-06: tsmom is main and flow is a probe, both from the registry's effective date."""
    book = read_state(STATE)
    assert set(book.candidates) >= {"tsmom", "flow"}, "the running sleeves are not in the governance state"
    assert book.candidates["tsmom"].state is State.MAIN
    assert book.candidates["flow"].state is State.PROBE
    # flow occupies one of R3's two slots AND the whole 1/3 share; §3 says a second probe therefore
    # has to wait for it to leave or come in at 1/6 with its own book report.
    assert book.candidates["flow"].fraction == Policy().probe_budget_share
    assert book.candidates["flow"].probe_entries == 1, "R7 counts entries on entry, and flow has entered once"


def test_without_the_seed_a_second_full_probe_would_be_admitted() -> None:
    """The measurement the seed exists for, kept executable so it cannot quietly stop being true."""
    policy = Policy()
    facts = Facts(window_open=True, is_queue_head=True, canary_healthy=True, clean_days_under_current_construction=30)
    newcomer = Candidate(id="newcomer", state=State.QUEUED, fraction=policy.probe_budget_share)

    empty = evaluate(Book(candidates={"newcomer": newcomer}), newcomer, Event.PROMOTE, facts, policy)
    assert empty.allowed, "if this now refuses, the seed is no longer what is holding R3 up - say so"

    seeded = evaluate(read_state(STATE), newcomer, Event.PROMOTE, facts, policy)
    assert not seeded.allowed
    assert any("R3" in reason for reason in seeded.reasons), seeded.reasons


def test_the_state_file_is_tracked_rather_than_ignored() -> None:
    """A record one disk failure from never having existed is not a record.

    The first version of the autonomy-switch ignore took the whole `governance/` directory, and with
    it the transaction chain (`closed(log)` is what proves no registry change happened outside a
    transaction) and R7's lifetime `probe_entries`, which nothing else can reconstruct.
    """
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "\ngovernance/ENABLED\n" in ignore, "the switch must stay per-checkout"
    assert "\ngovernance/\n" not in ignore, "ignoring the directory takes the transaction chain with it"


def test_the_state_on_disk_is_plain_enough_to_read_during_an_incident() -> None:
    payload = json.loads(STATE.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload["candidates"]) >= {"tsmom", "flow"}
