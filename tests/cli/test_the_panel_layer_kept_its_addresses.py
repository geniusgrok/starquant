"""M6 step 1: the panel layer left `research_cmd`, and every caller's address survived it.

The seam was chosen by measurement rather than by tidiness.  Twenty-nine scripts under `scratchpad/` -
the reproductions behind D-035's ladder bootstrap, P26, P29, P32, D-039's band sweep and the exit
reachability tables - open with `from starquant_cli.research_cmd import _load, _membership,
_resolve_symbols`.  The evidence base of this repository imports three private functions out of a
command-line module, which is the concrete form of "reproducing a validation report means importing
CLI privates".  Splitting the nine COMMANDS apart, the other reading of M6, would not have touched it.

So this commit moves definitions and keeps addresses: one definition, two names for it, asserted here
rather than promised in a docstring.  The shim is temporary - when `evaluate_book` sinks into
`starquant_alpha.validation` these go with it and the scripts get a home that is not a CLI - and the
tests below are what will fail loudly if that second move forgets one of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from starquant_cli import research_cmd, research_panel

ROOT = Path(__file__).resolve().parents[2]

#: What `scratchpad/` and the tests actually import from `research_cmd` today.
MOVED = (
    "_entry",
    "_funding_consumers",
    "_funding_facts",
    "_load",
    "_membership",
    "_membership_table",
    "_model",
    "_require_funding",
    "_resolve_mined",
    "_resolve_symbols",
    "_wants_metrics",
    "_wants_spot",
)


@pytest.mark.parametrize("name", MOVED)
def test_the_old_address_still_resolves_to_the_one_definition(name: str) -> None:
    """Not merely present at both names - the SAME object, so there is no second copy to drift."""
    assert getattr(research_cmd, name) is getattr(research_panel, name)


def test_the_module_declares_exactly_what_it_re_exports() -> None:
    """A shim that drifts from its own `__all__` is how a name quietly stops being re-exported."""
    assert tuple(sorted(research_panel.__all__)) == MOVED


def test_the_scripts_that_made_this_the_first_seam_still_import() -> None:
    """The count is the argument, so it is asserted rather than left in prose."""
    scripts = sorted(ROOT.glob("scratchpad/*.py"))
    importers = [p for p in scripts if "from starquant_cli.research_cmd import" in p.read_text(encoding="utf-8")]
    assert len(importers) >= 25, f"only {len(importers)} scripts import it; re-read the seam argument"
    for path in importers:
        body = path.read_text(encoding="utf-8")
        for name in ("_load", "_membership", "_resolve_symbols"):
            if f"import {name}" in body or f", {name}" in body or f"{name}," in body:
                assert hasattr(research_cmd, name), f"{path.name} would stop importing {name}"


def test_a_package_named_research_would_have_shadowed_the_click_group() -> None:
    """Why this is a sibling module and not `starquant_cli/research/`: the name is taken by the group."""
    from starquant_cli import research

    assert callable(research) and not Path(ROOT / "starquant_cli" / "research").is_dir()


def test_the_definitions_left_and_the_commands_stayed() -> None:
    """The structural claim, which a line count cannot make.

    A count would read a merge that lands another command's option as the move being undone; what the
    move actually asserts is that the twelve definitions are no longer HERE and are still reachable
    from here.  The command functions staying is the other half - M6's direction is that this module
    becomes click assembly, not that it becomes empty.
    """
    body = (ROOT / "starquant_cli" / "research_cmd.py").read_text(encoding="utf-8")
    for name in MOVED:
        assert f"def {name}(" not in body, f"{name} is defined in research_cmd.py again; the move was undone"
    for command in ("research_validate", "research_backtest", "research_book", "research_mine"):
        assert hasattr(research_cmd, command)
