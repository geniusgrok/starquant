"""A `research validate` against an enabled registry entry has to say what it will spend (2026-09-17).

Every grid cell appends one ledger row, and the strategy's bucket is the denominator of the D-028
threshold that same strategy's cited evidence has to clear.  `family_gate`'s docstring states the
consequence in four words - "searching more retires your own incumbents" - so the number of cells is
not a performance detail, it is how much of the incumbent's remaining margin the command spends.

What made it a check.  On 2026-09-17 a two-arm A/B was priced to the operator at "2 trials", ran
without `--grid`, and got `DEFAULT_GRIDS["tsmom"]`: sixteen cells per arm, 32 charged.  tsmom's gate
went N 259 -> 293, threshold 1.5572 -> 1.5715, and the incumbent's margin +0.0347 -> +0.0204 - about
35% of the headroom, from a default nobody typed.  The RUNBOOK already said to pass `--grid`.

Scoped to the SHARED ledger on purpose: a redirected run (`STARQUANT_TRIALS_LEDGER`) spends nothing any
gate reads, and `tests/conftest.py` redirects every test, so the guard stays off the suite's back
without an exemption list.  The refusal below therefore has to un-redirect - and it is asserted to
happen BEFORE any data is loaded, which is also what keeps that safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from starquant_alpha.validation.ledger import undeclared_charge
from starquant_cli import main
from starquant_cli.research_cmd import DEFAULT_GRIDS, _grid_of, _incumbent_grid, _refuse_an_undeclared_charge

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = str(ROOT / "config" / "alpha_registry.yaml")
CITED = {"crowding_window": [0, 72]}
DEFAULT_CELLS = len(_grid_of(DEFAULT_GRIDS["tsmom"]))


def test_the_shipped_pointer_still_cites_a_grid_this_can_be_compared_against() -> None:
    """The guard is only as good as the pointer it reads; nine archived reports carry no `grid` at all.

    It used to also assert the default grid was WIDER than the pointer's, so that the shipped registry
    itself could demonstrate the refusal.  That stopped being true on 2026-09-19, when the pointer moved
    to `tsmom-validation-20260919T081914Z.json` - a run ON the 16-cell default grid, so cited == default.

    The guard did not break; it correctly does not fire.  Reproducing the cited grid is the same
    experiment the charge was already paid for and D-024 dedupes it, which
    `test_reproducing_the_cited_grid_needs_no_declaration` right below has always said.  What broke is
    this file's ability to demonstrate the refusal with the SHIPPED pointer, so the demonstration moved
    to a synthetic one and this test now records the relationship instead of requiring a direction.
    """
    incumbent, cited = _incumbent_grid(REGISTRY, "tsmom")
    assert incumbent, "tsmom is not an enabled registry entry any more - re-aim this test"
    assert cited is not None, "the cited report carries no `grid`, so the guard falls back to 'undeclared'"
    cells = len(_grid_of(dict(cited)))
    if cells < DEFAULT_CELLS:  # the pre-2026-09-19 shape: the shipped pointer can demonstrate it itself
        assert undeclared_charge(
            strategy="tsmom", cells=DEFAULT_CELLS, grid=DEFAULT_GRIDS["tsmom"], cited_grid=dict(cited), declared=None
        )
    else:
        assert cells == DEFAULT_CELLS, (cells, DEFAULT_CELLS)
        assert (
            undeclared_charge(
                strategy="tsmom",
                cells=DEFAULT_CELLS,
                grid=DEFAULT_GRIDS["tsmom"],
                cited_grid=dict(cited),
                declared=None,
            )
            == ""
        ), "cited == default, so running the default IS reproducing the evidence and must not be refused"


def test_reproducing_the_cited_grid_needs_no_declaration() -> None:
    """The same experiment as the evidence: the charge was already paid and D-024 dedupes it."""
    assert undeclared_charge(strategy="tsmom", cells=2, grid=CITED, cited_grid=CITED, declared=None) == ""


def test_the_default_grid_against_that_pointer_is_undeclared() -> None:
    problem = undeclared_charge(
        strategy="tsmom", cells=DEFAULT_CELLS, grid=DEFAULT_GRIDS["tsmom"], cited_grid=CITED, declared=None
    )
    assert f"--charge {DEFAULT_CELLS}" in problem and "2 cell(s)" in problem


def test_the_exact_number_declared_is_what_gets_through() -> None:
    kwargs: dict[str, Any] = {"strategy": "tsmom", "cells": DEFAULT_CELLS, "grid": DEFAULT_GRIDS["tsmom"]}
    assert undeclared_charge(**kwargs, cited_grid=CITED, declared=DEFAULT_CELLS) == ""
    wrong = undeclared_charge(**kwargs, cited_grid=CITED, declared=2)
    assert "does not match this run" in wrong, "a declaration that is not the number is how the 32 was written up"


def test_a_pointer_that_cannot_be_compared_counts_as_undeclared() -> None:
    """Missing, unreadable or pre-`grid` evidence resolves the doubt the way the ledger does: charge more."""
    problem = undeclared_charge(
        strategy="flow", cells=4, grid={"window": [24, 72, 168, 336]}, cited_grid=None, declared=None
    )
    assert "cannot be compared" in problem


def test_a_strategy_that_is_not_an_enabled_entry_is_not_guarded() -> None:
    """The margin being protected belongs to a book that is running; a disabled id has none to spend."""
    incumbent, _ = _incumbent_grid(REGISTRY, "meanrev")
    assert not incumbent


def test_a_redirected_ledger_is_named_and_not_guarded(capsys: pytest.CaptureFixture[str]) -> None:
    """`ledger_redirection` exists so a redirected run cannot look like a charged one - so say which."""
    _refuse_an_undeclared_charge("tsmom", REGISTRY, "", DEFAULT_CELLS, None)  # autouse fixture redirects
    out = capsys.readouterr().out
    assert f"charge: {DEFAULT_CELLS} row(s)" in out and "redirected ledger" in out


def test_the_shared_ledger_refuses_the_default_grid_before_any_data_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End to end, with the redirection removed - and it must refuse before `_load` touches a store.

    `--root` points at an empty directory: if the refusal ever moved below the panel load this test
    would fail with a data error instead of the charge message, which is the property that makes
    running it against the real registry safe.
    """
    # 守卫里调 `ledger_redirection()` 的是 `_refuse_an_undeclared_charge`，它住在 research_ledger_io。
    # M6 之后这个名字读在哪就打在哪：`research_cmd` 只是它的历史地址，打在再导出上不会影响真正的调用点。
    monkeypatch.setattr("starquant_cli.research_ledger_io.ledger_redirection", lambda: "")
    # A registry whose pointer cites a NARROWER grid than the default - which the shipped one did until
    # 2026-09-19 and no longer does.  Synthetic on purpose: the property under test is "the refusal
    # happens, and happens before any data is read", and tying that to whichever report the operator
    # happens to have pointed at makes the guard untestable the day the pointer moves.  `--root` is an
    # empty directory, so a refusal that ever slipped below `_load` would surface as a data error here.
    narrow = tmp_path / "registry.yaml"
    narrow.write_text(
        Path(REGISTRY)
        .read_text(encoding="utf-8")
        .replace(
            "reports/research/tsmom-validation-20260919T081914Z.json",
            str(ROOT / "reports" / "research" / "tsmom-validation-20260913T182325Z.json"),
        ),
        encoding="utf-8",
    )
    _, cited = _incumbent_grid(str(narrow), "tsmom")
    assert cited is not None and len(_grid_of(dict(cited))) < DEFAULT_CELLS, "fixture is not narrower"

    result = CliRunner().invoke(
        main,
        ["research", "validate", "--strategy", "tsmom", "--root", str(tmp_path), "--registry", str(narrow)],
    )
    assert result.exit_code != 0
    assert f"--charge {DEFAULT_CELLS}" in result.output, result.output
    assert "2026-09-17" in result.output, "the message has to carry the run that made it a check"


def test_declaring_it_gets_past_the_guard_and_then_the_ordinary_run_begins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The escape hatch is a sentence, not a flag: `--charge N` must be the number, and then it proceeds."""
    # 守卫里调 `ledger_redirection()` 的是 `_refuse_an_undeclared_charge`，它住在 research_ledger_io。
    # M6 之后这个名字读在哪就打在哪：`research_cmd` 只是它的历史地址，打在再导出上不会影响真正的调用点。
    monkeypatch.setattr("starquant_cli.research_ledger_io.ledger_redirection", lambda: "")
    args = ["research", "validate", "--strategy", "tsmom", "--root", str(tmp_path), "--registry", REGISTRY]
    result = CliRunner().invoke(main, [*args, "--charge", str(DEFAULT_CELLS)])
    assert f"--charge {DEFAULT_CELLS}" not in result.output, result.output
    assert "charge: " in result.output, "the price is still printed when it is declared"


def test_the_grid_the_guard_prices_is_the_grid_validate_runs() -> None:
    """One enumeration, two readers: a guard counting cells a different way is a guard about nothing."""
    from starquant_cli.research_cmd import _grid

    for strategy, grid in DEFAULT_GRIDS.items():
        assert len(_grid(strategy, "", {})) == len(_grid_of(grid)), strategy
    assert len(_grid("tsmom", json.dumps(CITED), {})) == 2
