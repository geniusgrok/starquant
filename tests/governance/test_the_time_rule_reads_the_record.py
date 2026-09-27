"""T-G6′: the time rule's events, derived from `cycles.jsonl` instead of typed by a person.

`lifecycle.py` shipped knowing what `WINDOW_SURVIVED` and `PNL_STOP` mean and nothing produced
either, so the state machine was complete and unreachable: no probe could reach main and no main
sleeve could be sent back without somebody asserting the event by hand -- the one thing §3's "all
machine-driven" was written to remove.

These tests are about the derivation only.  What the events then DO is `lifecycle`'s, and
`test_the_rules_hold_over_any_sequence.py` already holds that end.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from click.testing import CliRunner

from starquant_cli import main as cli
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.state import write as write_state
from starquant_governance.tenure import books_in, flow_contaminated, tenure

START = "2026-09-03T00:00:00+00:00"
ANCHOR = START  # the batch calendar; global, not per sleeve
CLEAN: dict[str, Any] = {"by_type": {}, "rebaselined": False, "rows": 0, "total": 0.0}


def _cycle(day: float, *, stop: bool = False, flows: dict[str, Any] | None = None, book: str = "flow_short") -> dict:
    at = datetime.fromisoformat(START) + timedelta(days=day)
    return {
        "at": at.isoformat(),
        "probes": [
            {
                "book": book,
                "strategy": "flow",
                "stop": stop,
                "status": "STOP" if stop else "OK",
                "pnl_pct": -0.03 if stop else 0.001,
            }
        ],
        "external_flows": dict(flows or CLEAN),
    }


def _at(days: float) -> datetime:
    return datetime.fromisoformat(START) + timedelta(days=days)


def test_three_clean_windows_are_three_survived_windows() -> None:
    """T-G6′-1.  A window closes because the calendar moved, not because a cycle said so."""
    rows = [_cycle(d) for d in (1, 15, 31, 45, 61, 75, 91)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(100))

    assert out.windows_survived == 3
    assert [e.event for e in out.events] == [Event.WINDOW_SURVIVED] * 3
    assert out.stopped_at is None
    assert out.skipped == ()


def test_a_stop_ends_the_derivation_and_the_windows_before_it_still_count() -> None:
    """T-G6′-2.  A sleeve that ran two clean windows and then stopped survived two windows."""
    rows = [_cycle(1), _cycle(31), _cycle(65, stop=True), _cycle(70)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(100))

    assert out.windows_survived == 2
    assert [e.event for e in out.events] == [Event.WINDOW_SURVIVED, Event.WINDOW_SURVIVED, Event.PNL_STOP]
    assert out.stopped_at == _cycle(65)["at"]
    assert "attributed -3.0000%" in out.events[-1].why
    # Window 2 spans days 60-90 and the stop lands inside it, so it is NOT survived even though the
    # sleeve was still running on day 70.  A window is survived or it is not; there is no partial.
    closes = [e.at for e in out.events if e.event is Event.WINDOW_SURVIVED]
    assert closes == ["2026-10-03T00:00:00+00:00", "2026-11-02T00:00:00+00:00"]  # windows 0 and 1 only
    # Every in-range row is still read - the per-window cycle counts need them.  Only the FIRST
    # counted stop produces an event; later ones belong to a tenure this module cannot see.
    assert out.cycles_read == 4


@pytest.mark.parametrize(
    ("flows", "expected"),
    [
        ({**CLEAN, "total": -5000.0, "by_type": {"TRANSFER": -5000.0}}, "external flow -5000.00"),
        ({**CLEAN, "rebaselined": True}, "equity was rebaselined"),
    ],
)
def test_a_stop_on_a_transfer_cycle_is_recorded_and_not_counted(flows: dict, expected: str) -> None:
    """T-G6′-3.  The demo account resets as a TRANSFER row with no fills; the attributed window then
    shows a loss nobody traded.  Refusing it is the point; recording the refusal is the discipline."""
    rows = [_cycle(10, stop=True, flows=flows)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert out.stopped_at is None
    assert len(out.skipped) == 1
    assert expected in out.skipped[0].why
    assert out.skipped[0].why.startswith("T-G6′-3")
    # And the consequence that makes the refusal mean something: the window the refused stop sits in
    # is SURVIVED.  A refusal that still cost the sleeve its window would be a refusal in name only.
    assert [e.event for e in out.events] == [Event.WINDOW_SURVIVED]
    assert out.windows_survived == 1


def test_skipping_a_contaminated_stop_cannot_lose_a_real_one() -> None:
    """The property that makes the exclusion safe rather than lenient.

    `probe_status` recomputes a TRAILING window every cycle, so a stop that is real is still true on
    the next uncontaminated cycle.  The exclusion delays a genuine stop by the flow's own cycles and
    refuses a spurious one outright -- it never swallows one.
    """
    flows = {**CLEAN, "total": -5000.0, "by_type": {"TRANSFER": -5000.0}}
    rows = [_cycle(10, stop=True, flows=flows), _cycle(11, stop=True)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert len(out.skipped) == 1
    assert Event.PNL_STOP in [e.event for e in out.events]
    assert out.stopped_at == _cycle(11)["at"]


def test_rows_before_the_start_belong_to_whatever_ran_there_before() -> None:
    """A sleeve's tenure starts when it was accepted, not when the log did."""
    rows = [_cycle(-10, stop=True), _cycle(1), _cycle(31)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert out.stopped_at is None
    assert out.windows_survived == 1
    assert out.cycles_read == 2


def test_a_window_the_loop_spent_down_is_not_a_window_the_sleeve_survived() -> None:
    """Absent knowledge is not survival.

    The third condition, and the one easiest to leave out: with no cycles inside a window there was
    nothing that could have reported a stop, so counting it would credit the sleeve for a month the
    record cannot speak to.
    """
    rows = [_cycle(1), _cycle(65)]  # nothing at all inside window 1 (days 30-60)
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(100))

    assert out.windows_survived == 2  # windows 0 and 2, not 1
    assert [e.at for e in out.events] == ["2026-10-03T00:00:00+00:00", "2026-12-02T00:00:00+00:00"]


def test_a_sleeve_that_entered_mid_window_does_not_get_that_window() -> None:
    """A window is survived from its open, not from whenever the sleeve happened to arrive."""
    rows = [_cycle(d) for d in (20, 40, 70)]
    out = tenure(rows, book="flow_short", started_at=_at(15).isoformat(), window_anchor=ANCHOR, now=_at(100))

    assert out.windows_survived == 2  # windows 1 and 2; window 0 opened before the sleeve existed
    assert [e.at for e in out.events] == ["2026-11-02T00:00:00+00:00", "2026-12-02T00:00:00+00:00"]


def test_a_book_the_record_never_mentions_yields_nothing_rather_than_surviving() -> None:
    rows = [_cycle(d, book="other") for d in (1, 31)]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert out.stopped_at is None
    assert books_in(rows) == ("other",)


def test_the_older_mapping_shaped_probes_field_still_reads() -> None:
    """Cycles written before the probe rows became a list recorded `{book: status}`."""
    rows = [
        {"at": _at(5).isoformat(), "probes": {"flow_short": "OK"}},
        {"at": _at(6).isoformat(), "probes": {"flow_short": "STOP"}},
    ]
    out = tenure(rows, book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert [e.event for e in out.events] == [Event.PNL_STOP]
    assert books_in(rows) == ("flow_short",)


def test_a_cycle_with_no_flow_record_is_not_treated_as_contaminated() -> None:
    """Absent knowledge is False here too: no `external_flows` field is not a transfer."""
    assert flow_contaminated({"at": "x"}) is None
    assert flow_contaminated({"external_flows": CLEAN}) is None


def test_the_result_carries_the_strategy_id_the_state_is_keyed_on() -> None:
    """The record keys probes on the BOOK ("flow_short"); `governance_state.json` on the registry
    entry id ("flow").  The first version of the command looked the candidate up by book, so the
    "state holds N" annotation -- the only thing that would show the derivation disagreeing with the
    stored count -- silently never printed."""
    out = tenure([_cycle(1)], book="flow_short", started_at=START, window_anchor=ANCHOR, now=_at(40))

    assert out.book == "flow_short"
    assert out.strategy == "flow"
    assert out.as_dict()["strategy"] == "flow"


def test_nine_survived_windows_are_what_the_state_machine_needs_for_main() -> None:
    """The seam: these events are the ones `lifecycle.apply` consumes, folded here end to end.

    Nine because Q3 made the window a month and §3 kept the pre-registered strength (3 quarters =
    9 months); a `windows_to_main` this test hard-coded would pass while the rule silently weakened.
    """
    policy = Policy()
    rows = [_cycle(d * policy.window_days + 1) for d in range(policy.windows_to_main + 1)]
    out = tenure(
        rows,
        book="flow_short",
        started_at=START,
        window_anchor=ANCHOR,
        policy=policy,
        now=_at(policy.window_days * 12),
    )
    assert out.windows_survived >= policy.windows_to_main

    # §3 puts three conditions on this edge.  Nine windows and no stop are the two `tenure` can see;
    # the third is R0 recomputed at today's bucket, which is a fact about the LEDGER and reaches the
    # state machine as a fact rather than as an event (`family_gate.recheck`).  Both halves below,
    # because the branch was added on 2026-09-09 and a test that only exercises the happy path would
    # pass just as well with the condition deleted again.
    surviving = Facts(family_gate_still_passes=True)
    book = Book(candidates={"flow": Candidate(id="flow", state=State.PROBE, fraction=1 / 3)})
    for event in out.events[: policy.windows_to_main]:
        book, decision = apply(book, "flow", event.event, surviving, policy)
        assert decision.allowed, decision.reasons
    assert book.candidates["flow"].state is State.MAIN


def test_nine_survived_windows_do_not_reach_main_on_a_gate_nobody_asked() -> None:
    """The same nine windows, with the gate unmeasured: the sleeve stays in probe.

    "Could not be computed" is not "passed" - the rule the drawdown ladder and the canary already
    follow.  A probe that sits in probe costs a delayed promotion; a probe promoted on an unasked
    question costs the thing R0 exists for.
    """
    policy = Policy()
    rows = [_cycle(d * policy.window_days + 1) for d in range(policy.windows_to_main + 1)]
    out = tenure(
        rows,
        book="flow_short",
        started_at=START,
        window_anchor=ANCHOR,
        policy=policy,
        now=_at(policy.window_days * 12),
    )
    book = Book(candidates={"flow": Candidate(id="flow", state=State.PROBE, fraction=1 / 3)})
    for event in out.events[: policy.windows_to_main]:
        book, decision = apply(book, "flow", event.event, Facts(), policy)
    assert book.candidates["flow"].state is State.PROBE
    assert any("quantile gate" in reason for reason in decision.reasons), decision.reasons


def test_the_command_says_when_a_main_sleeve_cannot_be_seen_at_all(tmp_path: Any) -> None:
    """The edge this module does NOT close, said out loud where the operator is already looking.

    `probes_from_registry` excludes the main book, so no cycle ever reports a stop for a main sleeve,
    and §3's `main -> probe` is unreachable from the record exactly as `probe -> main` was before
    this module existed.  Closing it changes what can halt the live main book -- an operator's
    decision, not a side effect of adding a reader -- so the command reports it instead.
    """
    record = tmp_path / "cycles.jsonl"
    record.write_text("\n".join(json.dumps(_cycle(d)) for d in (1, 31)), encoding="utf-8")
    (tmp_path / "governance").mkdir()
    write_state(
        tmp_path / "governance" / "governance_state.json",
        Book(
            candidates={
                "tsmom": Candidate(id="tsmom", state=State.MAIN),
                "flow": Candidate(id="flow", state=State.PROBE, fraction=1 / 3),
            }
        ),
    )

    result = CliRunner().invoke(
        cli, ["governance", "tenure", "--root", str(tmp_path), "--cycles", str(record), "--anchor", START]
    )
    assert result.exit_code == 0, result.output
    assert "tsmom sits in main" in result.output
    assert "main -> probe cannot fire from it" in result.output
    # and the annotation that only prints when the lookup is keyed on the strategy, not the book
    assert "state holds 0" in result.output


def test_a_main_sleeve_that_does_carry_a_stop_is_not_reported_as_invisible(tmp_path: Any) -> None:
    """The note above was stale for hours after the main book got a stop, and nothing said so.

    `books_in` reads the record's probe rows, which are keyed on the BOOK ("main"), and
    `governance_state.json` keys on the registry entry id ("tsmom").  Comparing one namespace against
    the other made a sleeve that WAS in the record read as absent from it - the same book-vs-strategy
    mismatch this command already got wrong once, in the other direction.
    """
    record = tmp_path / "cycles.jsonl"
    rows = []
    for day in (1, 31):
        row = _cycle(day)
        row["probes"] = [
            {"book": "main", "strategy": "tsmom", "stop": False, "status": "OK"},
            {"book": "flow_short", "strategy": "flow", "stop": False, "status": "OK"},
        ]
        rows.append(row)
    record.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / "governance").mkdir()
    write_state(
        tmp_path / "governance" / "governance_state.json",
        Book(
            candidates={
                "tsmom": Candidate(id="tsmom", state=State.MAIN),
                "flow": Candidate(id="flow", state=State.PROBE, fraction=1 / 3),
            }
        ),
    )
    result = CliRunner().invoke(
        cli, ["governance", "tenure", "--root", str(tmp_path), "--cycles", str(record), "--anchor", START]
    )
    assert result.exit_code == 0, result.output
    assert "main" in result.output
    assert "cannot fire" not in result.output, result.output
