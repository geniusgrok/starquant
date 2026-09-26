"""Operator ruling 2026-09-23: a failed family gate sends a main back to probe, and something now says so.

`Event.FAMILY_GATE_FAILED` had a definition, a handler that RETIRED, and no producer.  The 2026-09-23
checklist (`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`) found the 09-19 refusal of
tsmom - OOS 1.2306 against 1.5238 - sitting in `governance/verdicts.jsonl` with no consequence.  The
operator ruled the consequence is demotion, not retirement.  These tests pin the three halves: what the
rule does, where the event comes from, and that `advance` folds it in time order.  The last one is the
easy one to get wrong: a refusal folded after a later window sits behind the watermark and never counts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from click.testing import CliRunner

from starquant_cli.governance_cmd import governance
from starquant_governance.family_gate import VERDICT_KIND, refusals
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.state import read as read_state
from starquant_governance.state import write as write_state
from starquant_governance.verdicts import ALLOW, REFUSE, Verdict, record

POLICY = Policy()
#: Far enough back that every window below has closed against the real clock `tenure` reads.
ANCHOR = "2024-01-01T00:00:00+00:00"
CLEAN: dict[str, Any] = {"by_type": {}, "rebaselined": False, "rows": 0, "total": 0.0}
REASON = ("OOS 1.2306 vs 1.5238 at N=183 (adopted against 1.5129 at N=167)",)


def _main_book(**fields: Any) -> Book:
    return Book(candidates={"tsmom": Candidate("tsmom", State.MAIN, **fields)})


# --- the rule ---------------------------------------------------------------------------------


def test_a_main_that_fails_the_gate_goes_back_to_probe_without_spending_a_life() -> None:
    book, decision = apply(_main_book(windows_survived=4), "tsmom", Event.FAMILY_GATE_FAILED, Facts(), POLICY)
    held = book.candidates["tsmom"]
    assert decision.allowed and held.state is State.PROBE, decision
    assert decision.reasons[0].startswith("R0"), "a demotion names its rule like a refusal does"
    assert held.windows_survived == 0, "it re-earns main from zero, like a main that touched its P&L stop"
    assert held.probe_entries == 0, "R7's lives move on queued -> probe; a demotion is not an entry"


def test_a_probe_that_fails_the_gate_stays_a_probe() -> None:
    """Retiring here would turn the ruling into a delay: the next failing reading retires the demoted main."""
    probe = Book(candidates={"tsmom": Candidate("tsmom", State.PROBE)})
    book, decision = apply(probe, "tsmom", Event.FAMILY_GATE_FAILED, Facts(), POLICY)
    assert not decision.allowed and book.candidates["tsmom"].state is State.PROBE, decision
    assert decision.reasons[0].startswith("R0")


def test_a_demoted_main_comes_back_through_nine_windows_with_the_gate_passing() -> None:
    book, _ = apply(_main_book(), "tsmom", Event.FAMILY_GATE_FAILED, Facts(), POLICY)
    book, _ = apply(book, "tsmom", Event.FAMILY_GATE_FAILED, Facts(), POLICY)  # still failing a day later
    assert book.candidates["tsmom"].state is State.PROBE
    passing = Facts(family_gate_still_passes=True)
    for _ in range(POLICY.windows_to_main - 1):
        book, _ = apply(book, "tsmom", Event.WINDOW_SURVIVED, passing, POLICY)
    assert book.candidates["tsmom"].state is State.PROBE, "one window short of §3's count is not main"
    book, decision = apply(book, "tsmom", Event.WINDOW_SURVIVED, passing, POLICY)
    assert decision.allowed and book.candidates["tsmom"].state is State.MAIN, decision


# --- where the event comes from ---------------------------------------------------------------


def _verdict(at: str, *, ruling: str = REFUSE, kind: str = VERDICT_KIND, subject: str = "tsmom") -> Verdict:
    return Verdict(
        id=f"{kind}-{subject}-{ruling}-{at}", at=at, kind=kind, subject=subject, ruling=ruling, reasons=REASON
    )


def test_only_this_strategys_family_gate_refusals_become_events_oldest_first() -> None:
    rows = [
        _verdict("2026-09-21T02:30:00+00:00"),
        _verdict("2026-09-19T18:30:06+00:00"),
        _verdict("2026-09-18T18:04:21+00:00", ruling=ALLOW),  # passing again promotes nothing
        _verdict("2026-09-20T02:30:00+00:00", subject="flow"),
        _verdict("2026-09-20T03:00:00+00:00", kind="admission"),
    ]
    events = refusals(rows, "tsmom")
    assert [event.at for event in events] == ["2026-09-19T18:30:06+00:00", "2026-09-21T02:30:00+00:00"]
    assert {event.event for event in events} == {Event.FAMILY_GATE_FAILED}
    assert all(event.why.startswith("R0") for event in events)


# --- advance folds it, once, in time order ----------------------------------------------------


def _cycle(day: float) -> dict[str, Any]:
    at = datetime.fromisoformat(ANCHOR) + timedelta(days=day)
    return {
        "at": at.isoformat(),
        "probes": [{"book": "main", "strategy": "tsmom", "stop": False, "status": "OK", "pnl_pct": 0.001}],
        "external_flows": dict(CLEAN),
    }


def _checkout(tmp_path: Path, *, refused_on_day: float | None) -> Path:
    """Four windows with a cycle in each; optionally one refusal written the way `governance gate` writes it."""
    root = tmp_path / "checkout"
    (root / "governance").mkdir(parents=True)
    write_state(root / "governance" / "governance_state.json", _main_book())
    rows = [_cycle(index * POLICY.window_days + 1) for index in range(4)]
    (root / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    registry = {
        "version": 1,
        "ensemble": {"method": "mean", "turnover_penalty": 0.0},
        "strategies": [{"id": "tsmom", "enabled": True, "weight": 1.0}],
    }
    (root / "registry.yaml").write_text(yaml.safe_dump(registry), encoding="utf-8")
    if refused_on_day is not None:
        record(
            root / "governance" / "verdicts.jsonl",
            kind=VERDICT_KIND,
            subject="tsmom",
            ruling=REFUSE,
            reasons=REASON,
            now=datetime.fromisoformat(ANCHOR) + timedelta(days=refused_on_day),
        )
    return root


def _run(root: Path, *extra: str) -> Any:
    return CliRunner().invoke(
        governance,
        [
            "advance",
            "--root",
            str(root),
            "--cycles",
            str(root / "cycles.jsonl"),
            "--registry",
            str(root / "registry.yaml"),
            "--anchor",
            ANCHOR,
            *extra,
        ],
    )


def _held(root: Path) -> Candidate:
    return read_state(root / "governance" / "governance_state.json").candidates["tsmom"]


def test_the_refusal_folds_between_the_windows_it_fell_between(tmp_path: Path) -> None:
    """Day 45 is inside window 1: window 0 closed on a main and does not count, windows 1-3 closed on a probe.

    Folded after the windows instead, the watermark would already stand at day 120, the refusal at day 45
    would read as already folded, and the demotion would silently never happen.
    """
    root = _checkout(tmp_path, refused_on_day=45)
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output
    assert _held(root).state is State.PROBE, result.output
    assert _held(root).windows_survived == 3, result.output
    assert "family_gate_failed" in result.output


def test_the_refusal_folds_once_however_often_advance_runs(tmp_path: Path) -> None:
    root = _checkout(tmp_path, refused_on_day=45)
    assert _run(root, "--commit").exit_code == 0
    once = (root / "governance" / "governance_state.json").read_bytes()
    again = _run(root, "--commit")
    assert again.exit_code == 0, again.output
    assert (root / "governance" / "governance_state.json").read_bytes() == once, again.output


def test_without_a_refusal_in_the_ledger_the_main_stays_main(tmp_path: Path) -> None:
    """The control: the demotion above comes from the ledger row and from nothing else in the record."""
    root = _checkout(tmp_path, refused_on_day=None)
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output
    assert _held(root).state is State.MAIN, result.output
