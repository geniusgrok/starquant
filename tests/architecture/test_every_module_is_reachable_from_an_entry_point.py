"""The third general guard, and the one that would have caught the biggest defect of 2026-09-09.

Two guards already exist for this repository's recurring shape - a thing that looks like a control
and controls nothing.  `test_every_threshold_has_a_consumer` holds every `Policy` field to having a
production reader; `test_the_digest_sees_every_live_knob` holds every registry leaf to moving a digest.
Both passed all day while `governance apply` wrote the registry without asking a single governance
rule, because both ask their question one level too low.

`test_every_threshold_has_a_consumer` searches for the field's NAME in the production packages, and
`starquant_governance` is one of them.  So `max_concurrent_probes` had a reader - `lifecycle.evaluate`.
And `lifecycle.evaluate` was called by `replay` and by tests.  And `scheduler`, which was to have
driven it, had no caller at all.  The field-level hole was closed; the module-level one was not, and
that is where R1, R3, R4, R5, R7 and K-EX14 were all sitting.

So: every production module must be reachable from a CLI entry point by following imports.  Not
"someone imports it" - `budget` was imported, by `scheduler`, which nothing could reach.  Reachable
from the thing a person or a launchd job actually runs.

Exemptions are NAMED, never counted, and each name carries what it is waiting for.  A count would let
the next unreachable module in silently, which is the failure mode the whole file exists to prevent.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    "starquant_alpha",
    "starquant_cli",
    "starquant_data",
    "starquant_exchange",
    "starquant_governance",
    "starquant_live",
    "starquant_shared",
)

#: What `starquant` actually runs.  `__main__` registers the groups; the four command modules are the
#: leaves launchd and the operator reach through it.
ENTRY_POINTS = (
    "starquant_cli.__main__",
    "starquant_cli.data_cmd",
    "starquant_cli.governance_cmd",
    "starquant_cli.live_cmd",
    "starquant_cli.research_cmd",
)

#: Each name says what would make it reachable, so an exemption is an argument rather than a shrug.
#: EMPTY since 2026-09-16, which is the strongest state this file has ever been able to report: every
#: production module in the tree can be reached from a `starquant` command.  It held two entries until
#: then, both for #19's liquidation ingest:
#:
#:     "starquant_data.liquidations"        #19 判定不可用 (2026-09-09): Binance publishes no USDⓈ-M
#:                                       liquidation history, and the only coin-margined archive
#:                                       stopped 23 months before the live period, so the parity
#:                                       obligation is unmeetable and RISK-G3 keeps the column out of
#:                                       live.  "The module stays as the record of what was checked;
#:                                       a CLI for it would be a command that can only fail."
#:     "starquant_data.liquidation_archive" "The archive half of #19; same ruling, same reason."
#:
#: The operator withdrew both.  The argument that retired them is the one their own exemption made:
#: a module kept "as the record of what was checked" is a record, and a record belongs in the log and
#: in git history, not in the import graph where it costs non-alpha lines against a ratchet at zero
#: headroom.  `docs/RESEARCH_LOG.md` and `git show 0b306e5b` hold what they checked.
#:
#: An empty dict is deliberate rather than a tidy-up: `test_the_exemptions_are_named_rather_than_counted`
#: refuses an entry naming a module that no longer exists, so these two had to go the moment the files
#: did - the same pruning rule that deleted the three data-feed exemptions in 2026-09-10.  Do not
#: replace this with a count; the whole file exists because a count lets the next one in silently.
EXEMPT: dict[str, str] = {}
# Retired 2026-09-10: `starquant_data.onchain`, `starquant_data.index_price` and `starquant_data.macro` became
# reachable through `starquant data onchain|index|macro`, so their exemptions were DELETED rather than
# annotated - `test_the_exemptions_are_named_rather_than_counted` enforces that from the other side,
# because an exemption list nobody prunes stops being a list of decisions.
#
# WITHDRAWN 2026-09-16, and the distinction is the point of this file.  The operator withdrew all three
# feeds: modules, commands and tests are gone from the tree, so there is nothing here to exempt and
# nothing here to reach.  This guard answers "can every module in the tree be run", and a module that
# is not in the tree is outside its question entirely - which is why the right edit was to delete the
# three assertions in `test_the_guard_can_fail` below, not to add three exemptions back.  An exemption
# would have said "unreachable and that is acceptable"; the truth is "absent".  They were built, they
# were reachable the whole time, and nothing ever read a column from them - `research_cmd._load` joins
# only `metrics` and `spot`, and `run_data.sh` had held all three out of the schedule since the day
# they landed, with its reasons written out.  `git show 71863e9e` is where they are if they come back.


def _modules() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            out[name.removesuffix(".__init__")] = path
    return out


def _edges(modules: dict[str, Path]) -> dict[str, set[str]]:
    """Import edges, including `from X import Y` where Y is itself a module.

    That last case is not a detail: `signals/__init__` imports its nine signal modules exactly that
    way, and a walker that records only `X` reports all nine as dead code.  A guard whose first run
    produces nine false positives is a guard nobody will keep.
    """
    edges: dict[str, set[str]] = collections.defaultdict(set)
    for name, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a file that cannot parse fails elsewhere first
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                edges[name].add(node.module)
                edges[name].update(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                edges[name].update(alias.name for alias in node.names)
    return edges


def _reachable() -> set[str]:
    modules = _modules()
    edges = _edges(modules)
    seen: set[str] = set()
    stack = list(ENTRY_POINTS)
    while stack:
        current = stack.pop()
        if current in seen or current not in modules:
            continue
        seen.add(current)
        stack.extend(target for target in edges[current] if target in modules and target not in seen)
    return seen


def test_no_production_module_is_unreachable_from_a_command() -> None:
    modules = _modules()
    seen = _reachable()
    # A package `__init__` is a namespace shim: production imports the submodule directly, so the
    # shim can be unreached while everything under it runs.  Its cost is caught by the line budget.
    dead = sorted(
        name for name, path in modules.items() if name not in seen and name not in EXEMPT and path.name != "__init__.py"
    )
    assert not dead, (
        f"these modules cannot be reached from any `starquant` command: {dead}.  Give one an entry point, "
        "or name it in EXEMPT with what it is waiting for.  A module nothing can run is not a control."
    )


def test_the_exemptions_are_named_rather_than_counted() -> None:
    """Every exemption has to be argued for on its own, and has to still be unreachable to earn one."""
    modules, seen = _modules(), _reachable()
    assert all(reason.strip() for reason in EXEMPT.values())
    unknown = sorted(name for name in EXEMPT if name not in modules)
    assert not unknown, f"EXEMPT names modules that no longer exist: {unknown}"
    stale = sorted(name for name in EXEMPT if name in seen)
    assert not stale, (
        f"these are reachable now and no longer need an exemption: {stale}.  Delete the entry - an "
        "exemption list nobody prunes stops being a list of decisions."
    )


def test_the_guard_can_fail() -> None:
    """Its own negative control: the walk has to actually walk, or every module is trivially dead."""
    seen = _reachable()
    assert "starquant_governance.lifecycle" in seen, "the state machine is reached through governance_cmd"
    assert "starquant_governance.canary" in seen, "wired 2026-09-09 by `governance canary`"
    # The two this file was written about.  `scheduler` was DL-G8 with no assembler and `budget` held
    # R1 behind it; `governance next` builds the context and `governance advance` folds what the
    # record already did, which is what `lifecycle.apply` and `state.write` had been waiting for.
    assert "starquant_governance.scheduler" in seen, "wired 2026-09-10 by `governance next`"
    assert "starquant_governance.budget" in seen, "R1 reaches a command through the scheduler's context"
    assert "starquant_alpha.signals.tsmom" in seen, "reached only via `from starquant_alpha.signals import tsmom`"
    assert "starquant_live.engine" in seen and "starquant_data.spot" in seen
    # `starquant_data.onchain|index_price|macro` were asserted here from 2026-09-10 until they were
    # withdrawn on 2026-09-16.  The assertions went with the modules rather than becoming exemptions;
    # the note beside EXEMPT says why "absent" and "unreachable" are not the same answer.  Nothing is
    # asserted in their place ON PURPOSE: a guard that fails when a module is ABSENT would block the
    # re-add it is supposedly protecting, and the dead-code test above already covers a module that
    # comes back without a command.  `starquant_data.spot`, asserted one line up, is the surviving member
    # of that same 2026-09-10 batch - it stayed because something reads it.
