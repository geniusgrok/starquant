"""试验身份与计费：构造摘要、签名、预登记、写 ledger，以及拒绝一次说不出价钱的 validate。

为什么这些归一处：`family gate` 按今天的 N 重算，每一笔 tsmom 桶的试验都在退休在位者。
「这次花多少」「花在哪个桶」「凭什么说它和上次是同一笔」是同一个问题的三个面。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from starquant_alpha.mining import enumerate_candidates
from starquant_alpha.mining.search import SearchResult, scoring_reproduction
from starquant_alpha.panel import Panel
from starquant_alpha.signals import get_signal
from starquant_alpha.validation.ledger import (
    TrialRecord,
    ledger_redirection,
    parse_ledger,
    undeclared_charge,
    unique_trials,
)
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_grids import DEFAULT_GRIDS
from starquant_cli.research_report import (
    _durable,
    _stamp,
)

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_governance.policy import Policy
from starquant_live.composition import (
    load_registry,
)


def _incumbent_grid(registry_path: str, strategy: str) -> tuple[bool, Mapping[str, Any] | None]:
    """Is this strategy an ENABLED registry entry, and what grid did the evidence it cites use?

    Read off the registry rather than off a flag, for the reason `_running_book_nets` reads it: the
    registry is the governed decision about what runs, and "am I about to spend the incumbent's
    margin" is a question about that decision and not about how the command was typed.

    ``None`` for the grid is not "no grid": it is "this cannot be compared" - the pointer is missing,
    unreadable, or predates the `grid` field (nine archived reports do).  The caller treats that as
    undeclared, which is the conservative direction and the one the ledger is already resolved in
    (`unique_trials` charges more when it cannot tell two runs apart).
    """
    path = Path(registry_path)
    if not path.exists():
        return False, None
    for candidate in load_registry(path).enabled:
        if candidate.id != strategy:
            continue
        report = Path(str((candidate.evidence or {}).get("report", "")))
        if not report.is_file():
            return True, None
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True, None
        cited = payload.get("grid") if isinstance(payload, Mapping) else None
        return True, cited if isinstance(cited, Mapping) else None
    return False, None


def _refuse_an_undeclared_charge(
    strategy: str, registry_path: str, grid_json: str, cells: int, declared: int | None
) -> None:
    """Say what this run will spend, and refuse an undeclared spend against an enabled entry.

    Two halves, and only the second one can refuse.  The echo is unconditional because a price nobody
    is told is a price nobody can decline, and it names where the rows are going: `ledger_redirection`
    exists precisely so a redirected run cannot look like a charged one.

    The refusal is scoped to the SHARED ledger.  A redirected run spends nothing that any gate reads,
    so guarding it would be ceremony - and the autouse fixture in `tests/conftest.py` redirects every
    test, which is what keeps this check off the suite's back without an exemption list.
    """
    where = ledger_redirection()
    click.echo(
        f"charge: {cells} row(s) to " + (f"the redirected ledger {where}" if where else "the shared trials ledger")
    )
    if where:
        return
    incumbent, cited = _incumbent_grid(registry_path, strategy)
    if not incumbent:
        return
    problem = undeclared_charge(
        strategy=strategy,
        cells=cells,
        grid=json.loads(grid_json) if grid_json else DEFAULT_GRIDS.get(strategy, {}),
        cited_grid=cited,
        declared=declared,
    )
    if problem:
        raise click.ClickException(problem)


def _trial_signature(record: TrialRecord) -> tuple[Any, ...]:
    return record.signature


def _short_digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def _preregistration(commit: str) -> dict[str, str] | None:
    """DL-G9: resolve a pre-registration commit to a fact the artefact can carry.

    DL-K3 asks that the pre-registration be earlier than the report.  Until now the only record of
    that was a RESEARCH_LOG paragraph and a reader willing to run `git show`, so the Phase 0 replay
    had to suspend the condition for all 48 archived reports.  Recording the commit's own timestamp -
    not the moment `--prereg` was typed - is what makes the ordering checkable afterwards.

    An unresolvable ref is an error, not a silent null: a run that claims a pre-registration it cannot
    name is worse than one that claims none.
    """
    if not commit.strip():
        return None
    result = subprocess.run(
        ["git", "show", "-s", "--format=%H|%cI", commit.strip()], capture_output=True, text=True, check=False
    )
    if result.returncode != 0 or "|" not in result.stdout:
        raise click.BadParameter(f"--prereg {commit!r} is not a commit in this checkout")
    sha, committed_at = result.stdout.strip().split("|", 1)
    return {"commit": sha, "committed_at": committed_at}


def _construction_digest(portfolio: Mapping[str, Any], cost: Any, execution: str, impact: Any = None) -> str:
    """DL-K1: what turned a signal into weights, and what it cost to hold them.

    The research twin of D-026's live ``construction_fingerprint``, for the same reason it exists
    there: the same parameters under a different vol target, a different band or a different cost
    model are different trials, and the old signature could not tell them apart - so P10 cell B moving
    the band from 0.25 to 0.40 re-priced every weight in the book while the ledger recorded a replay.

    ``impact`` joined it on 2026-09-09 and only when it is ON.  DL-C1's first two runs re-priced tsmom
    under the square-root law and the ledger folded both onto the flat rows as replays: `spent` did not
    move, so the DSR denominator did not either - and §19 had written down that adopting the cost model
    would charge rows.  Running one configuration under two cost models and keeping whichever passes is
    the selection DSR exists to expose, so it has to be counted.  Conditional because unconditional
    would give every future FLAT run a signature no archived row shares, which would charge genuine
    replays as new trials - the same shape, in the other direction.
    """
    payload: dict[str, Any] = {"portfolio": dict(portfolio), "costs": dict(vars(cost)), "execution": execution}
    if impact is not None and getattr(impact, "enabled", False):
        payload["impact"] = dict(vars(impact))
    return _short_digest(payload)


def _symbol_set_hash(symbols: Sequence[str]) -> str:
    """WHICH symbols.  The ledger's ``symbols`` is a count, and two disjoint 146-name universes
    were the same trial to it - which is exactly the pit/static comparison this repository runs."""
    return _short_digest(sorted(str(symbol) for symbol in symbols))


def _prior_search(search: SearchResult, reports_dir: Path) -> str | None:
    """R2: has this exact space been enumerated before?

    Exact when the earlier report carries `search_space_digest` - the set of canonical expression
    hashes, which two different parameterisations of the same space share and a widened space does not.
    Reports written before that field fall back to `evaluated`, and that comparison is WEAKER: it is a
    count, and two different 514-wide spaces would collide.  Stated rather than silently relied on,
    because the fallback is exactly the case the rule was written for and it will age out on its own.
    """
    if not reports_dir.exists():
        return None
    for path in sorted(reports_dir.glob("mine-shortlist-*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        recorded = payload.get("search_space_digest")
        if recorded == search.space_digest:
            return path.name
        if recorded is None and payload.get("evaluated") == search.evaluated:
            return f"{path.name} (matched on `evaluated` only - it predates `search_space_digest`)"
    return None


def _reproduction_of(rows: list[dict[str, Any]], prior_run: str | None, reports_dir: Path) -> dict[str, Any]:
    """What this round's scores say against the round whose space it re-enumerated.

    `prior_run` is `_prior_search`'s answer and may carry a parenthesised caveat, so only the leading
    filename is used.  A round with no predecessor gets `compared: 0` and `bought_nothing: false` -
    nothing to reproduce is not the same fact as reproducing everything, and the vacuous true would
    fire on exactly the rounds doing the work.
    """
    if not prior_run:
        return scoring_reproduction([], rows) | {"of": None}
    name = prior_run.split(" ", 1)[0]
    try:
        payload = json.loads((reports_dir / name).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return scoring_reproduction([], rows) | {"of": None, "unreadable": name}
    previous = payload.get("candidates") if isinstance(payload, dict) else None
    return scoring_reproduction(previous if isinstance(previous, list) else [], rows) | {"of": name}


def _search_space_version(strategy: str, grids: str = "") -> str:
    """For a mined id, how wide the search that produced it was.  Empty for hand-written strategies.

    B2 took the default space 267 -> 514 without changing a single expression's canonical hash - the
    property the frozen-hash regression exists to guarantee.  That stability is exactly what makes this
    field necessary rather than redundant: the id is the same and the cost of finding it is not, so the
    same hash validated before and after B2 is two trials at two prices.
    """
    if not strategy.startswith("mined_"):
        return ""
    return str(enumerate_candidates(**(json.loads(grids) if grids else {})).evaluated)


def _overlay_digest(*parts: Any) -> str:
    """Exits and throttle, when a run applied any.  Empty means "none", not "unknown"."""
    payload = [dict(vars(part)) for part in parts if part is not None]
    return _short_digest(payload) if payload else ""


def _charge_signal_search(
    strategy: str,
    panel: Panel,
    combos: Sequence[Mapping[str, Any]],
    ledger_path: Path,
    *,
    range_start: str,
    range_end: str,
) -> dict[str, Any] | None:
    """DL-K2 for a search the SIGNAL runs: one ledger row per candidate it examined.  None if it runs none.

    `pairs` chose which symbol pairs to trade out of every pair its formation window could form and paid
    nothing for it: the 2026-09-08 report recorded `n_trials: 4` - its four-cell parameter grid - for a
    run that had examined 19,578 distinct pairs.  The reason is the one `mine`'s docstring gives, one
    level down: a search that costs nothing is a DSR denominator wrong in the direction that flatters it.

    The rows carry **no construction or overlay digest and no Sharpe**, and neither omission is laziness.
    The pair search runs on `panel.close` before any weight exists, so it enumerates the identical
    candidates under every vol target, cost model and exit stack; stamping the construction on would
    charge the same hypotheses again for every re-run at a new target - two prices for one selection,
    which is the mirror of the under-charging this fixes.  `sharpe_annual` is None because these
    candidates were never scored one at a time (they are selected on formation-window correlation, not
    on their own P&L), and `dsr_inputs` pools only rows that have one: the census moves N and leaves the
    Sharpe dispersion to the configurations that really were scored.  `mine` already writes None-Sharpe
    rows for its never-traded candidates, so this is the established shape rather than a new one.

    The union over the grid, not one census per cell: the grid's two `z_window` values search almost the
    same 19,578 pairs, and a pair looked at under both is one hypothesis (DL-K2's rule for a widened
    space).  `parameter_neighborhood` re-runs the search under perturbed windows and is deliberately NOT
    charged - nothing selects on a neighbourhood, its numbers are reported and never kept.
    """
    census_of = get_signal(strategy).selection
    bucket = get_signal(strategy).selection_bucket
    if census_of is None or not bucket:
        return None
    per_configuration = {param_key(dict(combo)): census_of(panel, combo) for combo in combos}
    candidates = sorted({candidate for census in per_configuration.values() for candidate in census.candidates})
    selected = sorted({candidate for census in per_configuration.values() for candidate in census.selected})
    stamp = datetime.now(UTC).isoformat()
    charged = _record_trials(
        ledger_path,
        [
            TrialRecord(
                strategy=bucket,
                param_key=candidate,
                sharpe_annual=None,
                bars_per_year=panel.bars_per_year,
                recorded_at=stamp,
                range_start=range_start,
                range_end=range_end,
                symbols=len(panel.symbols),
                run_id=f"{strategy}-search-{_stamp()}",
                symbol_set_hash=_symbol_set_hash(panel.symbols),
            )
            for candidate in candidates
        ],
    )
    # Read back off the file through the fold the denominator applies, exactly as `mine` reports its
    # family prior - `charged` is what this run added, and the two part ways as soon as the range moves.
    family_prior = (
        len(
            unique_trials(
                parse_ledger(ledger_path.read_text(encoding="utf-8").splitlines(), bucket),
                range_end_granularity_days=Policy().trial_range_end_granularity_days,
            )
        )
        if ledger_path.exists()
        else 0
    )
    return {
        "bucket": bucket,
        "charged": charged,
        "candidates": len(candidates),
        "selected": len(selected),
        "configurations": {key: census.facts for key, census in per_configuration.items()},
        "family_prior": {"strategy": bucket, "before": family_prior - charged, "after": family_prior},
    }


def _record_trials(ledger_path: Path, records: Sequence[TrialRecord]) -> int:
    """Append every record whose signature is not already in the ledger, reading the file once.

    `_record_trial` re-parses the whole ledger per row, which is fine for the one or two a validation
    writes and quadratic for the 514 a mine writes.  Same dedup rule, one pass.
    """
    if not records:
        return 0
    strategies = {record.strategy for record in records}
    existing = (
        {r.signature for r in parse_ledger(ledger_path.read_text(encoding="utf-8").splitlines(), strategies)}
        if ledger_path.exists()
        else set()
    )
    fresh = []
    for record in records:
        if record.signature in existing:
            continue
        existing.add(record.signature)
        fresh.append(record)
    if not fresh:
        return 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        for record in fresh:
            handle.write(record.to_json() + "\n")
        _durable(handle)
    return len(fresh)


def _record_trial(ledger_path: Path, record: TrialRecord) -> bool:
    """Append a trial unless the identical configuration on the identical data is already in the ledger."""
    existing = (
        parse_ledger(ledger_path.read_text(encoding="utf-8").splitlines(), record.strategy)
        if ledger_path.exists()
        else []
    )
    if any(_trial_signature(r) == _trial_signature(record) for r in existing):
        return False
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")
        _durable(handle)
    return True
