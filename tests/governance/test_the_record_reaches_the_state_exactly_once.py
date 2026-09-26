"""`governance advance`: the first production caller `lifecycle.apply` and `state.write` ever had.

Until 2026-09-10 the state machine could refuse a promotion and could not record one.  `tenure` derived
`WINDOW_SURVIVED` and `PNL_STOP` from `cycles.jsonl`, `evaluate` knew what they meant, and the two were
never introduced: `governance_state.json` was maintained by hand (one commit in `git log`), so R4's
`promotions_this_window`, R5's `consecutive_probe_stops` and R7's `probe_entries` were typed numbers
that no record had to agree with.

The tests here are mostly about running it TWICE.  Folding is not idempotent by nature - the counters
this writes are cumulative - and the counter usually named is not the one at risk: `probe_entries`
moves on `queued -> probe`, which no event derived from the record produces.  What a second fold moves
is `windows_survived`, which reaches main in four and a half windows instead of nine, and
`consecutive_probe_stops`, where one stop counted twice is R5's two and freezes promotion for six
windows.  Both are pinned below, byte for byte.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from starquant_cli.governance_cmd import governance
from starquant_governance.lifecycle import Book, Candidate, State
from starquant_governance.policy import Policy
from starquant_governance.state import read as read_state
from starquant_governance.state import write as write_state

POLICY = Policy()
#: Far enough back that `policy.windows_to_main` windows have closed against the real clock, which is
#: what `tenure` compares against: this command reads a record rather than being handed a `now`.
ANCHOR = "2024-01-01T00:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]
CLEAN: dict[str, Any] = {"by_type": {}, "rebaselined": False, "rows": 0, "total": 0.0}


def _cycle(day: float, *, stop: bool = False, book: str = "flow_short", strategy: str = "flow") -> dict[str, Any]:
    at = datetime.fromisoformat(ANCHOR) + timedelta(days=day)
    return {
        "at": at.isoformat(),
        "probes": [
            {
                "book": book,
                "strategy": strategy,
                "stop": stop,
                "status": "STOP" if stop else "OK",
                "pnl_pct": -0.03 if stop else 0.001,
            }
        ],
        "external_flows": dict(CLEAN),
    }


def _windows(count: int, *, stop_in: int | None = None) -> list[dict[str, Any]]:
    """One cycle inside each of `count` windows.  A window with no cycle is not one the sleeve survived."""
    return [_cycle(index * POLICY.window_days + 1, stop=index == stop_in) for index in range(count)]


def _gate_report(*, sharpe: float = 2.0, threshold: float = 1.0) -> dict[str, Any]:
    """An evidence report `family_gate.read_gate` can recompute against an empty ledger.

    `ledger_trials: 0` matters: the recomputation adds today's bucket MINUS the bucket the report
    recorded, so with both zero the only thing that moves is nothing, and the test is about the branch
    rather than about the arithmetic (`test_the_family_gate_is_recomputed_at_todays_n` owns that).
    """
    return {
        "kind": "validation",
        "strategy": "flow",
        "verdict": "PASS",
        "oos_selection": {
            "gate": "max_sharpe_quantile",
            "oos_sharpe_annual": sharpe,
            "variance": 0.01,
            "threshold_annual": threshold,
            "n_trials": 100,
            "alpha": 0.05,
        },
        "ledger": {"ledger_trials": 0},
    }


def _checkout(tmp_path: Path, *, book: Book, rows: list[dict[str, Any]], gate: dict[str, Any] | None = None) -> Path:
    root = tmp_path / "checkout"
    (root / "governance").mkdir(parents=True)
    (root / "reports" / "research").mkdir(parents=True)
    write_state(root / "governance" / "governance_state.json", book)
    (root / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    strategies: list[dict[str, Any]] = [{"id": "tsmom", "enabled": True, "weight": 1.0}]
    if gate is not None:
        (root / "reports" / "research" / "flow-validation.json").write_text(json.dumps(gate), encoding="utf-8")
        strategies.append(
            {
                "id": "flow",
                "enabled": True,
                "weight": 1.0,
                "book": "flow_short",
                "evidence": {"report": "reports/research/flow-validation.json"},
            }
        )
    (root / "registry.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "ensemble": {"method": "mean", "turnover_penalty": 0.0},
                "books": {"flow_short": {"fraction": 1 / 3}},
                "strategies": strategies,
            }
        ),
        encoding="utf-8",
    )
    return root


def _probe_book() -> Book:
    return Book(candidates={"flow": Candidate("flow", State.PROBE, probe_entries=1, fraction=1 / 3)})


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


def _state(root: Path) -> Path:
    return root / "governance" / "governance_state.json"


# --- the write side exists at all ------------------------------------------------------------


def test_a_survived_window_the_record_shows_reaches_the_state_file(tmp_path: Path) -> None:
    """Before this command nothing on any production path called `lifecycle.apply` or `state.write`."""
    root = _checkout(tmp_path, book=_probe_book(), rows=_windows(3))
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output
    assert read_state(_state(root)).candidates["flow"].windows_survived == 3, result.output
    assert "window_survived" in result.output


def test_a_dry_run_is_the_default_and_writes_nothing(tmp_path: Path) -> None:
    root = _checkout(tmp_path, book=_probe_book(), rows=_windows(3))
    before = _state(root).read_bytes()
    result = _run(root)
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert _state(root).read_bytes() == before, "the default must not touch the file"
    assert "window_survived" in result.output, "...and must still say what it would have done"


# --- twice ------------------------------------------------------------------------------------


def test_the_same_record_folded_twice_leaves_the_state_byte_identical(tmp_path: Path) -> None:
    """The watermark, tested the only way that means anything: run the command again.

    Nine windows is not an arbitrary number here - it is `windows_to_main`, so a second fold of the
    same three windows is the first half of a promotion §3 did not authorise.
    """
    root = _checkout(tmp_path, book=_probe_book(), rows=_windows(3))
    assert _run(root, "--commit").exit_code == 0
    once = _state(root).read_bytes()

    again = _run(root, "--commit")
    assert again.exit_code == 0, again.output
    assert _state(root).read_bytes() == once, again.output
    assert read_state(_state(root)).candidates["flow"].windows_survived == 3
    assert "already folded" in again.output, "the reason has to be legible, not merely true"
    assert "nothing to write" in again.output


def test_one_stop_stays_one_stop_however_often_the_command_runs(tmp_path: Path) -> None:
    """R5 freezes promotion after two CONSECUTIVE stops, so a stop counted twice freezes on one.

    Six windows of freeze on an event that happened once, and `frozen_until_window` is not something a
    later run recomputes - it is written down.
    """
    root = _checkout(tmp_path, book=_probe_book(), rows=_windows(4, stop_in=2))
    assert _run(root, "--commit").exit_code == 0
    once = read_state(_state(root))
    assert once.consecutive_probe_stops == 1
    assert once.candidates["flow"].state is State.QUEUED, "a stopped probe is demoted, not retired"
    assert not once.frozen()

    assert _run(root, "--commit").exit_code == 0
    twice = read_state(_state(root))
    assert twice.consecutive_probe_stops == 1, "one stop, twice folded, is R5's freeze on a single event"
    assert not twice.frozen()
    assert twice == once


def test_a_stop_ends_one_tenure_and_the_record_after_it_is_still_read(tmp_path: Path) -> None:
    """`tenure` stops deriving at the first counted stop and hands the continuation to its caller.

    A main sleeve that touches the stop goes back to probe and starts counting windows again, so a
    caller that folded one tenure and stopped would go blind on everything after the first stop -
    forever, since the derivation re-reads the whole record from the same start every run.
    """
    book = Book(candidates={"flow": Candidate("flow", State.MAIN, probe_entries=1, fraction=1 / 3)})
    root = _checkout(tmp_path, book=book, rows=_windows(6, stop_in=1))
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output

    after = read_state(_state(root))
    assert after.candidates["flow"].state is State.PROBE, "main + stop -> probe"
    assert after.candidates["flow"].windows_survived > 0, (
        "the windows after the stop are a new tenure and were not read at all before the re-derivation"
    )
    assert _run(root, "--commit").exit_code == 0
    assert read_state(_state(root)) == after, "and the continuation is idempotent too"


# --- §3's third condition on probe -> main ------------------------------------------------------


def test_the_ninth_window_does_not_reach_main_on_a_gate_nobody_could_read(tmp_path: Path) -> None:
    """R0 recomputed is a condition of `probe -> main`, and an unreadable gate is not a passed one.

    The control is the second half: the same nine windows with a readable, passing report DO reach
    main, so the refusal above is the gate and not some other rule quietly blocking the edge.
    """
    windows = _windows(POLICY.windows_to_main)
    blind = _checkout(tmp_path / "blind", book=_probe_book(), rows=windows)
    result = _run(blind, "--commit")
    assert result.exit_code == 0, result.output
    assert read_state(_state(blind)).candidates["flow"].state is State.PROBE
    assert "quantile gate" in result.output, result.output

    seeing = _checkout(tmp_path / "seeing", book=_probe_book(), rows=windows, gate=_gate_report())
    passed = _run(seeing, "--commit")
    assert passed.exit_code == 0, passed.output
    assert "PASS       flow" in passed.output, passed.output
    assert read_state(_state(seeing)).candidates["flow"].state is State.MAIN, passed.output


def test_a_gate_that_no_longer_passes_holds_the_sleeve_in_probe(tmp_path: Path) -> None:
    """Searching more retires your own incumbents - the same report, with the bar above the record."""
    root = _checkout(
        tmp_path,
        book=_probe_book(),
        rows=_windows(POLICY.windows_to_main),
        gate=_gate_report(sharpe=1.0, threshold=2.0),
    )
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output
    assert "FAIL       flow" in result.output, result.output
    assert read_state(_state(root)).candidates["flow"].state is State.PROBE


# --- what it refuses to do ----------------------------------------------------------------------


def test_a_candidate_the_state_does_not_carry_is_refused_rather_than_invented(tmp_path: Path) -> None:
    """An empty book is HEADROOM, so inventing the sleeve the record names is not the safe direction."""
    root = _checkout(tmp_path, book=Book(candidates={"tsmom": Candidate("tsmom", State.MAIN)}), rows=_windows(3))
    result = _run(root, "--commit")
    assert result.exit_code == 0, result.output
    assert "NOT IN THE STATE" in result.output
    assert "flow" not in read_state(_state(root)).candidates


def test_an_empty_state_file_is_refused_rather_than_seeded_from_the_record(tmp_path: Path) -> None:
    root = _checkout(tmp_path, book=Book(), rows=_windows(3))
    result = _run(root, "--commit")
    assert result.exit_code != 0
    assert "HEADROOM" in result.output


# --- and on the record this deployment actually has ---------------------------------------------


def test_it_runs_on_the_armed_loops_own_record_without_writing(tmp_path: Path) -> None:
    """The real `cycles.jsonl` shape, the real registry, the real state - and the honest answer today.

    No batch window has closed since the 2026-09-03 anchor and no cycle carries a stop, so the record
    implies no event at all.  The test asserts the command runs and writes nothing, not that the state
    is unchanged forever: the first window closes 2026-10-03 and this then starts having something to
    say, which is the point of wiring it before that date rather than after.

    Skipped where the record is absent, which is every checkout but the trading machine's - `.starquant/`
    is ignored, so no test can carry it.  Said rather than quietly passed on an empty list: a green
    tick for a command that read nothing is the shape of defect this whole file is about.
    """
    record = REPO / ".starquant" / "live" / "cycles.jsonl"
    if not record.exists():
        pytest.skip(f"no armed record at {record}; this asserts against the trading machine's own file")
    rows = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line.strip()]
    root = tmp_path / "checkout"
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "governance_state.json").write_text(
        (REPO / "governance" / "governance_state.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    result = CliRunner().invoke(
        governance,
        [
            "advance",
            "--root",
            str(root),
            "--cycles",
            str(root / "cycles.jsonl"),
            "--registry",
            str(REPO / "config" / "alpha_registry.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "-> flow" in result.output or "NOT IN THE STATE" in result.output
