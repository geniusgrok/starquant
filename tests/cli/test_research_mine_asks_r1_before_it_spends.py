"""R1's mine-round limit was reported by one command and asked by none.

Found 2026-09-10, while pricing a fifth round in a window that allows four.  `governance next` reads
`window_spend` and prints `4/4 mine rounds`; `scheduler.next_action` consumes `mine_refusals`.  Neither
is `research mine`, which imports nothing from `starquant_governance.budget` and has never asked whether
the window had a round left.  So R1's round limit was advisory: the number was correct, printed, and
attached to no gate - the twenty-first instance of the shape the 2026-09-09 audit is named for.

R2 was never advisory, which is the contrast worth stating.  It refuses in `research mine` itself and
carries `--reauthorize` as a named, recorded override.  R1 had the refusal written (`mine_refusals`),
the calendar written (`admission.window_start`), and no call site.

**Asked before the panel loads, not after enumeration.**  R2's check needs `search.space_digest` and
therefore has to come after enumeration; R1 needs only the ledger and the calendar, so a run that is
not allowed to happen is refused before it scores 243 candidates over 49,000 bars.

The override is `--reauthorize` too, deliberately: one flag for "the operator has ruled this run
happens anyway", recorded in the shortlist report either way.  A second flag would let a run bypass
R1 while looking untouched to R2.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from starquant_cli.research_cmd import research
from starquant_governance.budget import mine_refusals, window_spend
from starquant_governance.policy import Policy

MINED = "mined"


def _row(run: int, trial: int, at: str) -> str:
    """One trials-ledger row, with the fields `TrialRecord.from_json` actually requires."""
    return json.dumps(
        {
            "strategy": MINED,
            "param_key": f"expr={run}-{trial}",
            "sharpe_annual": 0.1,
            "bars_per_year": 8760.0,
            "recorded_at": at,
            "range_start": "2021-01-01T00:00:00+00:00",
            "range_end": "2026-09-08T16:00:00+00:00",
            "symbols": 18,
            "run_id": f"run-{run}",
        }
    )


def _ledger(path: Path, rounds: int, *, at: str = "2026-09-05T00:00:00+00:00") -> None:
    """`rounds` distinct mine runs in the current window; a round is one `run_id`.

    Callers pass `Policy().max_mine_rounds_per_window` rather than a literal.  Hard-coding 4 made these
    pass in isolation and fail in the suite the hour the policy went to 5 - a test that asserts a
    refusal has to exhaust whatever the rule currently allows, or it is asserting the old rule.
    """
    path.write_text(
        "\n".join(_row(run, trial, at) for run in range(rounds) for trial in range(3)) + "\n",
        encoding="utf-8",
    )


def test_the_refusal_the_command_had_never_asked_for() -> None:
    """`mine_refusals` itself, so the test below is about the CALL SITE rather than the arithmetic."""
    spent = window_spend(
        [_row(run, 0, "2026-09-05T00:00:00+00:00") for run in range(4)],
        window_start=datetime(2026, 9, 3, tzinfo=UTC),
        policy=Policy(max_mine_rounds_per_window=4),
    )

    assert spent.mine_rounds == 4
    assert mine_refusals(spent), "four rounds of four is exhausted"


def test_a_window_with_rounds_left_is_not_refused() -> None:
    spent = window_spend(
        [_row(0, 0, "2026-09-05T00:00:00+00:00")],
        window_start=datetime(2026, 9, 3, tzinfo=UTC),
        policy=Policy(max_mine_rounds_per_window=4),
    )

    assert mine_refusals(spent) == ()


def test_research_mine_refuses_an_exhausted_window(tmp_path: Path, monkeypatch: Any) -> None:
    """The call site.  Before 2026-09-10 this run started, loaded a panel and scored the whole space."""
    ledger = tmp_path / "trials.jsonl"
    _ledger(ledger, rounds=Policy().max_mine_rounds_per_window)

    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(ledger))

    result = CliRunner().invoke(research, ["mine", "--strategy", "tsmom", "--root", str(tmp_path / "nodata")])

    assert result.exit_code != 0
    assert "R1" in result.output
    assert "mine round" in result.output


def test_the_refusal_lands_before_anything_is_loaded(tmp_path: Path, monkeypatch: Any) -> None:
    """`--root` points at nothing.  A run that got as far as the panel would fail on the store instead.

    That is what makes this an assertion about ORDER rather than about the message: the refusal has to
    be the first thing that stops it, or it is refusing after paying for the run it refuses.
    """
    ledger = tmp_path / "trials.jsonl"
    _ledger(ledger, rounds=Policy().max_mine_rounds_per_window)

    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(ledger))

    result = CliRunner().invoke(research, ["mine", "--strategy", "tsmom", "--root", str(tmp_path / "nodata")])

    assert "R1" in result.output
    assert "no such" not in result.output.lower() and "not found" not in result.output.lower()


def test_reauthorize_carries_the_operator_past_r1_as_well(tmp_path: Path, monkeypatch: Any) -> None:
    """One override for both rules, and it is recorded either way.

    The run still fails here - there is no data under `--root` - but it must fail on the DATA, which
    is proof it got past R1 rather than being stopped by it.
    """
    ledger = tmp_path / "trials.jsonl"
    _ledger(ledger, rounds=Policy().max_mine_rounds_per_window)

    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(ledger))

    result = CliRunner().invoke(
        research,
        [
            "mine",
            "--strategy",
            "tsmom",
            "--root",
            str(tmp_path / "nodata"),
            "--reauthorize",
            "D-test: the operator ruled a fifth round",
        ],
    )

    assert "R1" not in result.output
