"""`governance next`: DL-G8's decision function, given something to decide about.

`scheduler.next_action` was written, tested and unreachable - it and `budget` were both in the module
reachability guard's EXEMPT list, 227 lines holding R1 and the whole research pipeline order that no
command could run.  The assembler is what makes AC-G8 attemptable at all.

These tests drive the COMMAND rather than `assemble`, deliberately.  The defect this repository kept
finding all week is a control with no caller, and on 2026-09-09 it arrived inside the fix for itself:
`governance canary` was added to give `canary.evaluate` a caller and shipped broken, because the test
exercised the module and not the command.  A test that imports `assemble` and never types the command
name reproduces exactly that.

The load-bearing test is the third one.  Every count in `Context` has a `> 0` branch, so a field that
could not be read and is defaulted to 0 does not fail - it answers, confidently, one step further down
the pipeline than the evidence supports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from starquant_cli.governance_cmd import governance
from starquant_governance.lifecycle import Book, Candidate, State
from starquant_governance.policy import Policy
from starquant_governance.state import dump

ANCHOR = "2026-09-03T00:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]


def _row(param_key: str, *, strategy: str = "tsmom", run_id: str = "r") -> str:
    return json.dumps(
        {
            "strategy": strategy,
            "param_key": param_key,
            "sharpe_annual": 1.0,
            "bars_per_year": 8760.0,
            "recorded_at": "2026-09-05T00:00:00+00:00",
            "range_start": "a",
            "range_end": "b",
            "symbols": 15,
            "run_id": run_id,
        }
    )


def _checkout(
    tmp_path: Path,
    ledger: Path,
    *,
    shortlist: dict[str, Any] | None = None,
    reports: dict[str, dict[str, Any]] | None = None,
    ledger_rows: int = 1,
    book: Book | None = None,
    daily: dict[str, Any] | None = None,
) -> Path:
    """A checkout holding only what `governance next` reads: reports, the ledger and the state.

    `ledger` is `conftest.isolated_trials_ledger`, which every test gets whether it asks or not: the
    ledger's address is fixed in production (DL-K1) and the fixture redirects it so a command that
    appends cannot reach the real one.  It has to be written through here rather than into the
    checkout, or `resolve_ledger_path` reads the redirect and finds nothing.
    """
    root = tmp_path / "checkout"
    research = root / "reports" / "research"
    research.mkdir(parents=True)
    (root / "governance").mkdir(parents=True)
    if shortlist is not None:
        (research / "mine-shortlist-20260909T000000Z.json").write_text(json.dumps(shortlist), encoding="utf-8")
    for name, payload in (reports or {}).items():
        (research / name).write_text(json.dumps(payload), encoding="utf-8")
    ledger.write_text("\n".join(_row(f"k{i}") for i in range(ledger_rows)) + "\n", encoding="utf-8")
    (root / "governance" / "governance_state.json").write_text(json.dumps(dump(book or Book())), encoding="utf-8")
    if daily is not None:
        (root / "reports" / "daily").mkdir(parents=True)
        (root / "reports" / "daily" / "2026-09-09.json").write_text(json.dumps(daily), encoding="utf-8")
    return root


def _shortlist(hashes: list[str], *, digest: str = "space-a", include_basis: bool | None = False) -> dict[str, Any]:
    run: dict[str, Any] = {
        "top": len(hashes),
        "ranked_by": "baseline_marginal_sharpe",
        "max_complexity": 10,
        "max_lookback": 1400,
        "include_funding": True,
        "grids": {},
    }
    if include_basis is not None:
        run["include_basis"] = include_basis
    return {
        "kind": "mine-shortlist",
        "search_space_digest": digest,
        "run": run,
        "candidates": [{"hash": h, "baseline_marginal_sharpe": 1.0 - index / 100} for index, h in enumerate(hashes)],
    }


def _invoke(root: Path, *extra: str) -> Any:
    return CliRunner().invoke(governance, ["next", "--root", str(root), "--anchor", ANCHOR, *extra])


# --- the command runs, on this repository's own artefacts ---------------------------------------


def test_the_command_answers_on_the_repositorys_own_reports(isolated_trials_ledger: Path) -> None:
    """No fixtures: the real shortlists, the real reports, the real state, through the real CLI.

    The point is not the particular answer - it moves as research runs - but that every field prints
    where it came from and the scheduler reaches a verdict on artefacts nobody wrote for a test.

    The real ledger's ROWS are used and its path is not: `isolated_trials_ledger` redirects the address
    for every test in the suite, so the rows are copied into the redirect.  Reading it in place would
    work today and is the wrong habit - this command reads the ledger, and the next one to be written
    beside it may append to it.
    """
    isolated_trials_ledger.write_text(
        (REPO / "reports" / "research" / "trials.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = _invoke(REPO)
    assert result.exit_code == 0, result.output
    for field in ("search_space_digest", "shortlist_candidates", "validated_unbooked", "parity_met_unqueued"):
        assert field in result.output, result.output
    assert "scheduler " in result.output
    assert f"digest={Policy().digest()}" in result.output


# --- what it cannot read, it says -----------------------------------------------------------------


def test_a_knob_the_report_did_not_record_makes_the_space_unreadable_rather_than_changed(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """R2 compares two digests, so both have to be taken at the same knobs.

    `research mine` narrows the space by what its panel carries - `include_basis` is
    `panel.spot_symbols > 0`, false on every panel this repository can build - so reading today's space
    at the bare defaults reports "changed" on a narrowing that happened months ago.  With the knob
    unrecorded, "the space widened" and "the knob was guessed" are the same disagreement, and the field
    is unknown rather than resolved in the direction that spends a mine round.
    """
    root = _checkout(tmp_path, isolated_trials_ledger, shortlist=_shortlist(["aa"], include_basis=None), book=Book())
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    line = next(row for row in result.output.splitlines() if "search_space_digest" in row)
    assert line.lstrip().startswith("?"), line
    assert "include_basis" in line and "same disagreement" in line


def test_an_unreadable_field_that_decides_the_answer_turns_it_into_wait(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """The whole reason the fields carry a `known` flag rather than only a value.

    With nothing left to validate the scheduler reaches its mine branch, where the answer IS the space
    comparison - so an unreadable digest stops being a footnote.  The control is the second half: the
    same fixture with the knob recorded answers WAIT on R2 instead, from the scheduler rather than from
    the assembler refusing to speak for it.
    """
    validated = {"kind": "validation", "strategy": "mined_aa", "verdict": "FAIL", "generated_at": "2026-09-08"}
    blind = _checkout(
        tmp_path / "blind",
        isolated_trials_ledger,
        shortlist=_shortlist(["aa"], include_basis=None),
        reports={"mined_aa-validation-20260908T000000Z.json": validated},
    )
    result = _invoke(blind)
    assert result.exit_code == 0, result.output
    assert "next      WAIT" in result.output, result.output
    assert "search_space_digest" in result.output.split("next      WAIT")[1]

    # ...and with the knob recorded, the same shape is answered by the scheduler, not refused.
    seeing = _checkout(
        tmp_path / "seeing",
        isolated_trials_ledger,
        shortlist=_shortlist(["aa"], include_basis=False),
        reports={"mined_aa-validation-20260908T000000Z.json": validated},
    )
    seen = _invoke(seeing)
    assert seen.exit_code == 0, seen.output
    assert "next      WAIT" not in seen.output, "with every field readable the assembler has nothing to add"
    assert "scheduler MINE" in seen.output or "R2" in seen.output, seen.output


# --- the pipeline order, read off real artefact shapes -------------------------------------------


def test_a_rejected_book_report_is_not_a_candidate_waiting_in_a_queue(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """§3's `booked` is an ACCEPT.  A REJECT was measured beside the book and refused.

    Not hypothetical: every book report in this repository today is a REJECT, including the one for the
    sleeve that is actually running (D-029's acknowledged pointer).  Counting those as booked would
    have `governance next` demand parity evidence for six candidates nobody proposed.
    """
    root = _checkout(
        tmp_path,
        isolated_trials_ledger,
        shortlist=_shortlist(["aa"]),
        reports={
            "mined_aa-validation-1.json": {
                "kind": "validation",
                "strategy": "mined_aa",
                "verdict": "PASS",
                "generated_at": "2026-09-08",
            },
            "book-tsmom-mined_aa-1.json": {
                "kind": "book",
                "book_verdict": "REJECT",
                "sleeve": {"strategy": "mined_aa"},
                "generated_at": "2026-09-08",
            },
        },
    )
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    assert "booked_without_parity    0" in result.output
    assert "parity_met_unqueued      0" in result.output
    assert "no ACCEPT book report" in result.output


def test_an_accepted_book_waits_for_the_parity_status_rather_than_assuming_it(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """M-011 is produced by `starquant report daily`, and a research machine may not have one.

    With a candidate actually sitting in `booked`, the missing status is load-bearing and the answer is
    WAIT; with the status present and met, the same candidate is queued.  Absent knowledge is not
    parity - `parity_satisfied` refuses to call a missing report an agreement, and this refuses to
    schedule past it.
    """
    reports = {
        "mined_aa-validation-1.json": {
            "kind": "validation",
            "strategy": "mined_aa",
            "verdict": "PASS",
            "generated_at": "2026-09-08",
        },
        "book-tsmom-mined_aa-1.json": {
            "kind": "book",
            "book_verdict": "ACCEPT",
            "sleeve": {"strategy": "mined_aa"},
            "generated_at": "2026-09-08",
        },
    }
    blind = _checkout(tmp_path / "blind", isolated_trials_ledger, shortlist=_shortlist(["aa"]), reports=reports)
    result = _invoke(blind)
    assert "next      WAIT" in result.output, result.output
    assert "booked_without_parity" in result.output.split("next      WAIT")[1]

    met = _checkout(
        tmp_path / "met",
        isolated_trials_ledger,
        shortlist=_shortlist(["aa"]),
        reports=reports,
        daily={"metrics_parity": {"enforced": True, "symbols_compared": 18, "worst_differing_rate": 0.0}},
    )
    queued = _invoke(met)
    assert "scheduler QUEUE" in queued.output, queued.output
    assert "next      WAIT" not in queued.output


def test_a_candidate_the_state_already_carries_is_not_scheduled_again(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """`tsmom` has a PASS validation and will never have a `book-x-tsmom` report: it IS the book."""
    reports = {
        "tsmom-validation-1.json": {
            "kind": "validation",
            "strategy": "tsmom",
            "verdict": "PASS",
            "generated_at": "2026-09-09",
        }
    }
    loose = _checkout(tmp_path / "loose", isolated_trials_ledger, shortlist=_shortlist([]), reports=reports)
    assert "validated_unbooked       1" in _invoke(loose).output

    seeded = _checkout(
        tmp_path / "seeded",
        isolated_trials_ledger,
        shortlist=_shortlist([]),
        reports=reports,
        book=Book(candidates={"tsmom": Candidate("tsmom", State.MAIN)}),
    )
    assert "validated_unbooked       0" in _invoke(seeded).output


# --- R1, asked for the first time -----------------------------------------------------------------


def test_the_window_budget_is_asked_before_a_validate_is_scheduled(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """R1 had no production reader at all: `research mine` and `research validate` consult no budget.

    The scheduler is where it is asked, and until this command existed nothing built the context to ask
    it with.  The control is the first half - the same fixture inside the budget schedules the work.
    """
    policy = Policy()
    inside = _checkout(tmp_path / "inside", isolated_trials_ledger, shortlist=_shortlist(["aa"]), ledger_rows=10)
    assert "scheduler VALIDATE" in _invoke(inside).output

    spent = _checkout(
        tmp_path / "spent",
        isolated_trials_ledger,
        shortlist=_shortlist(["aa"]),
        ledger_rows=policy.max_ledger_rows_per_window,
    )
    result = _invoke(spent)
    assert "scheduler WAIT" in result.output, result.output
    assert "R1" in result.output and str(policy.max_ledger_rows_per_window) in result.output


def test_an_absent_ledger_is_refused_rather_than_read_as_an_untouched_budget(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """The empty-book failure, one file over: a missing ledger reads as 'nothing spent'."""
    root = _checkout(tmp_path, isolated_trials_ledger, shortlist=_shortlist(["aa"]))
    isolated_trials_ledger.unlink()
    result = _invoke(root)
    assert result.exit_code != 0
    assert "R1 cannot be asked" in result.output


def test_check_exits_non_zero_only_when_there_is_work(tmp_path: Path, isolated_trials_ledger: Path) -> None:
    """What a `deploy/` timer would run.  Non-zero means "there is something to do", not "broken"."""
    work = _checkout(tmp_path / "work", isolated_trials_ledger, shortlist=_shortlist(["aa"]))
    assert _invoke(work, "--check").exit_code != 0

    idle = _checkout(
        tmp_path / "idle", isolated_trials_ledger, shortlist=_shortlist(["aa"], include_basis=None), ledger_rows=1
    )
    (idle / "reports" / "research" / "mined_aa-validation-1.json").write_text(
        json.dumps({"kind": "validation", "strategy": "mined_aa", "verdict": "FAIL", "generated_at": "2026-09-08"}),
        encoding="utf-8",
    )
    result = _invoke(idle, "--check")
    assert result.exit_code == 0, result.output
    assert "WAIT" in result.output
