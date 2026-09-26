"""Operator ruling 2026-09-14 (Q4): price the N_eff experiment, which needs a run that charges nothing.

`effective_trials` (Li & Ji) has been "reported, never substituted" since it was written, and the debt
is documented as owed rather than guessed: the ledger stores Sharpes, not return series, so a
ledger-wide N_eff cannot be computed from anything the gate is given.  Computing it needs the space
re-scored with the per-candidate streams kept - and under R1/R2 that is a mine round, which charges
676 rows and raises the very bar the number is about.

So the measurement cannot be bought with the thing it is measuring.  `--measure` is the way out: score
the space, keep the matrix, compute N_eff, write NO ledger rows and make NO selection.

Three properties, and the middle one is what keeps this from becoming the loophole it looks like:

* **it charges nothing** - no row reaches the ledger, so the family's denominator does not move;
* **it selects nothing** - the report carries no ranked shortlist, only distribution-level readings, so
  it cannot be used to look at 676 candidates and then declare one.  "Free to look" would be a
  multiple-testing hole with a flag on it; "free to count" is not;
* **it is not an enumeration** - a different `kind`, so R2 does not see it as having spent the space
  and a later real round is not refused because a measurement happened.

The 2026-09-08 precedent is the reason the first property is asserted rather than described: a command
whose docstring said it charged nothing was charging 514 rows, and nobody found out until someone
counted.  A claim about cost that no test can fail is not a claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from starquant_cli import main
from tests.cli.test_ledger_is_one_book import _mine_args, _store_from_fixtures


def _rows(ledger: Path) -> list[str]:
    """The ledger does not exist until something charges it, and "absent" is zero rows, not an error."""
    return ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []


def _measured(out: Path) -> dict:
    return json.loads(sorted(out.glob("mine-*.json"))[-1].read_text(encoding="utf-8"))


def test_a_measurement_run_writes_no_ledger_row(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    """The 2026-09-08 shape, asserted: a claim about cost that no test can fail is not a claim."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    before = _rows(isolated_trials_ledger)

    result = CliRunner().invoke(main, _mine_args(root, tmp_path / "m", "--measure"))

    assert result.exit_code == 0, result.output
    after = _rows(isolated_trials_ledger)
    assert after == before, f"a measurement run appended {len(after) - len(before)} row(s)"


def test_a_measurement_run_reports_the_effective_trial_count(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    CliRunner().invoke(main, _mine_args(root, tmp_path / "m", "--measure"))
    payload = _measured(tmp_path / "m")

    assert payload["kind"] == "mine-measurement"
    assert isinstance(payload["effective_trials"], float)
    assert 1.0 <= payload["effective_trials"] <= payload["evaluated"], payload["effective_trials"]


def test_a_measurement_run_ranks_nothing(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    """Free to COUNT, never free to LOOK: a ranked shortlist here would be a selection nobody charged."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    CliRunner().invoke(main, _mine_args(root, tmp_path / "m", "--measure"))
    payload = _measured(tmp_path / "m")

    assert "candidates" not in payload, "a measurement that hands back candidates is a free selection"


def test_a_measurement_does_not_spend_the_space_for_a_later_real_round(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """R2 refuses a re-enumeration; a measurement is not one, or measuring would cost a round."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    CliRunner().invoke(main, _mine_args(root, tmp_path / "m", "--measure"))
    after = CliRunner().invoke(main, _mine_args(root, tmp_path / "r"))

    assert after.exit_code == 0, after.output


def test_an_ordinary_round_still_charges(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    """The control: without the flag nothing about this round changes."""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    before = len(_rows(isolated_trials_ledger))

    CliRunner().invoke(main, _mine_args(root, tmp_path / "r"))

    assert len(_rows(isolated_trials_ledger)) > before


def test_the_artefact_reproduces_its_own_headline_number(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """Q4b: the persisted matrix must give back the reported count, or the two can drift apart.

    The first `--measure` run wrote `effective_trials: 193.0` and nothing else, so checking it meant
    re-running 45 minutes of scoring.  A number that cannot be recomputed from the artefact reporting
    it is a number nobody can argue with - KILL-Q3's shape, one floor down.
    """
    import numpy as np

    from starquant_alpha.validation.multiple_testing import effective_trials_from_correlation

    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    CliRunner().invoke(main, _mine_args(root, tmp_path / "m", "--measure"))
    payload = _measured(tmp_path / "m")
    block = payload["measurement"]["correlation"]

    matrix = np.load(block["path"]).astype(float)
    assert list(matrix.shape) == block["shape"]
    recomputed = effective_trials_from_correlation(matrix, dead=block["dead_columns"])
    assert recomputed == payload["effective_trials"], "the artefact does not reproduce its own number"
