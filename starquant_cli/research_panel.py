"""Turning command-line arguments into a scored-on panel - the research layer that is not a command.

A sibling module rather than a `starquant_cli.research` package, because that name is already the click
group in `starquant_cli/__init__.py` and a package would shadow it.

M6 step 1 (2026-09-17; `docs/analysis/2026-09-13-full-repo-review.md`'s M6, and layer 0 ② of
`2026-09-17-alpha-module-deep-analysis.md`).  `research_cmd.py` had grown to 3,500 lines holding nine
commands, their click plumbing and every helper all three of those need; this is the first seam taken
out of it, and it is chosen rather than convenient.

**Why this seam first, measured.**  Twenty-nine scripts under `scratchpad/` - the reproductions behind
D-035's ladder bootstrap, P26, P29, P32, D-039's band sweep and the exit reachability tables - open
with `from starquant_cli.research_cmd import _load, _membership, _resolve_symbols`.  That is the evidence
base of this repository importing three private functions out of a CLI module, and it is the concrete
form of what the analysis recorded as "reproducing a validation report means importing CLI privates".
Splitting the nine COMMANDS apart would not have touched it; this layer is what those scripts actually
want, and it is the same layer the sink step moves again, out of `starquant_cli` altogether.

**Nothing moves twice without saying so.**  `research_cmd` re-exports every name below, so the
twenty-nine scripts, the tests and any branch in flight keep working unchanged.  That shim is
temporary by design: when `evaluate_book` sinks into `starquant_alpha.validation`, these go with it and
the scripts get a home that is not a command-line tool.  Until then a re-export is the honest state -
the code has one definition and two addresses, which is a different thing from having two copies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import click
import pandas as pd

from starquant_alpha.mining.search import enumerate_candidates, to_signal
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import SIGNALS, get_signal
from starquant_alpha.signals import register as register_signal
from starquant_cli.research_feature_store import with_feature_store
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars, tenure_mask
from starquant_data.store import SPOT_KLINE_KIND, FundingStore, KlineStore, MetricsStore
from starquant_live.composition import load_panel, load_registry, portfolio_params, read_universe

#: The names `research_cmd` re-exports.  Underscored because they are moved verbatim - renaming them
#: would touch twenty-nine scratchpad scripts and a dozen tests in a commit whose whole claim is that
#: nothing changed but the address.  They lose the underscore when they leave `starquant_cli` for good.
__all__ = [
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
]


def _membership_table(root: str) -> pd.DataFrame:
    path = Path(root) / MEMBERSHIP_FILE
    if not path.exists():
        raise click.ClickException(f"{path} is missing; run `starquant data pool history` first")
    table = pd.read_parquet(path)
    index = pd.DatetimeIndex(table.index)
    table.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return table.astype(bool)


def _resolve_symbols(root: str, symbols: str, interval: str, universe_mode: str = "static") -> list[str]:
    if symbols:
        return [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if universe_mode == "pit":
        table = _membership_table(root)
        union = [str(s) for s in table.columns[table.any(axis=0)]]
        stored = set(KlineStore(root).symbols(interval))
        missing = sorted(set(union) - stored)
        if missing:
            click.echo(f"pit universe: {len(missing)} member symbols have no {interval} klines yet: {missing[:10]}...")
        return [s for s in union if s in stored]
    universe = read_universe(root)
    return universe or KlineStore(root).symbols(interval)


def _membership(root: str, universe_mode: str, panel: Panel, min_tenure: int = 0) -> pd.DataFrame | None:
    """Bars x symbols boolean mask for ``--universe pit``; ``None`` keeps the static behaviour."""
    if universe_mode != "pit":
        return None
    return membership_at_bars(tenure_mask(_membership_table(root), min_tenure), panel.index)


def _resolve_mined(strategy: str, grids: str = "") -> None:
    """Make a ``mined_<hash>`` id addressable in this process by re-deriving it from the search.

    This is what the canonical hash is for.  Enumeration is deterministic and touches no data, so a
    candidate does not need persisting to be referred to across commands - and re-deriving rather than
    storing means a hash that no longer enumerates is reported as gone instead of silently resolving to
    a stale definition.
    """
    if not strategy.startswith("mined_"):
        return
    wanted = strategy.removeprefix("mined_")
    for candidate in enumerate_candidates(**(json.loads(grids) if grids else {})).candidates:
        if candidate.hash == wanted:
            register_signal(to_signal(candidate))
            return
    raise click.ClickException(f"no candidate hashes to {wanted} in the current search space")


def _entry(strategy: str, registry_path: str, params: str, grids: str = "") -> StrategyEntry:
    # Every command resolves its strategy id through here, so a mined candidate is addressable wherever
    # a hand-written one is.  It used to be wired into `correlate` alone: `research validate --strategy
    # mined_<hash>` raised a bare KeyError, which is precisely the wall an operator hits the moment the
    # shortlist hands them something worth validating.  A no-op for every id that is not `mined_`.
    _resolve_mined(strategy, grids)
    get_signal(strategy)
    base: dict[str, Any] = dict(SIGNALS[strategy].default_params)
    registry_file = Path(registry_path)
    if registry_file.exists():
        for candidate in load_registry(registry_file).strategies:
            if candidate.id == strategy:
                base.update(candidate.params)
    if params:
        base.update(json.loads(params))
    return StrategyEntry(id=strategy, params=base)


def _model(entry: StrategyEntry, profile: dict[str, Any], interval: str, min_history: int | None = None) -> AlphaModel:
    if min_history is None:
        min_history = int((profile.get("portfolio", {}) or {}).get("min_history_bars", 720))
    # `with_feature_store` is the identity unless STARQUANT_FEATURE_STORE is set (research only, #9.6).
    return with_feature_store(
        AlphaModel(
            entries=(entry,), portfolio=portfolio_params(profile), interval=interval, min_history_bars=min_history
        )
    )


def _load(
    root: str,
    symbols: list[str],
    interval: str,
    start: str | None,
    end: str | None,
    funding: bool,
    metrics: bool = False,
    spot: bool = False,
) -> Panel:
    """The research panel.  ``metrics`` and ``spot`` are opt-in and default off, deliberately.

    Loading them means reading a parquet per symbol and aligning every bucket, which is real work for a
    run whose signals read none of it - and the alignment is where the only look-ahead in this data
    lives, so a run that does not need the columns is better off not carrying them at all.  Callers
    turn them on when a strategy declares `needs_metrics` / `needs_spot`, and `research mine` turns both
    on always, because the candidates it is about to enumerate are exactly what decides the answer.

    ``spot`` was the missing half of DL-D5 until 2026-09-09 and the shape of the miss is worth keeping:
    every part of the spot path existed - the store, the ingest command, the alignment contract, the
    `basis` leaf, `load_panel`'s own `spot_store` parameter, and `mine`'s narrowing on
    `Panel.spot_symbols` - and nothing built the store here, so `spot_symbols` was 0 on every panel this
    module could construct and the narrowing switched the family off on every run.  Eighteen shapes,
    zero enumerated, and the artefact said `include_basis: false` truthfully.  That is the same defect
    DL-D4 had one feed over, arriving through the panel rather than through the flag.

    What is still NOT wired, named rather than left for the next reader to discover: `backtest`, `book`,
    `diagnose`, `correlate` and `overlay` pass neither `metrics` nor `spot`, so a mined `oi`, `lsr` or
    `basis` candidate that survives `validate` cannot yet be run through them.  One predicate per site
    fixes it; it is a separate change because it is the metrics feed's gap too and the two should move
    together rather than leave the pipeline half-asymmetric in a new place.
    """
    store = KlineStore(root)
    return load_panel(
        store,
        symbols,
        interval,
        funding_store=FundingStore(root) if funding else None,
        metrics_store=MetricsStore(root) if metrics else None,
        spot_store=KlineStore(root, kind=SPOT_KLINE_KIND) if spot else None,
        start=start,
        end=end,
    )


def _wants_metrics(strategy: str, params: Mapping[str, Any]) -> bool:
    """Does this strategy declare it reads a metrics column?  Unknown ids answer no, not crash.

    `research validate` is handed a strategy id from the command line, and a mined id that no longer
    enumerates is reported as gone elsewhere rather than here; this only decides whether to carry the
    columns, and carrying them for a signal that reads none is waste, not danger.
    """
    try:
        spec = get_signal(strategy)
    except (KeyError, ValueError):
        return False
    predicate = getattr(spec, "needs_metrics", None)
    return bool(predicate(params)) if predicate is not None else False


def _wants_spot(strategy: str, params: Mapping[str, Any]) -> bool:
    """Does this strategy declare it reads `panel.spot` (DL-D5)?  Unknown ids answer no, not crash.

    A second function rather than a parameterised one, exactly as `LiveEngine` keeps
    `strategies_needing_metrics` and `strategies_needing_spot` apart: the two answer for different
    stores and a caller that asked for "the extra columns" would carry a metrics alignment it never
    reads on every basis run, and vice versa.
    """
    try:
        spec = get_signal(strategy)
    except (KeyError, ValueError):
        return False
    predicate = getattr(spec, "needs_spot", None)
    return bool(predicate(params)) if predicate is not None else False


def _funding_consumers(entries: Sequence[StrategyEntry]) -> list[str]:
    return sorted({entry.id for entry in entries if get_signal(entry.id).needs_funding(entry.params)})


def _require_funding(entries: Sequence[StrategyEntry], panel: Panel) -> None:
    """Refuse a run whose signals consume funding against a panel that carries none (E-040 / KILL-027).

    ``AlphaModel.strategy_targets`` refuses the same thing and is the guard that cannot be forgotten;
    this one exists for three reasons it cannot cover.  ``research diagnose`` computes the signal directly
    and never builds a model, so nothing else would stop it.  The operator asked for ``--no-funding``, so
    the answer belongs at the flag - which strategy, which flag - rather than in a library traceback.

    And ``--funding`` is the DEFAULT, which is the case the library guard is blind to by construction.
    ``FundingStore.load`` returns an empty frame for a symbol with no archive, so an unsynced root yields
    a funding frame of all zeros rather than ``None``; tsmom's crowding rank then reads every symbol as
    uncrowded and the run writes the exact report E-040 is about, at exit 0, with nothing said anywhere.
    A signal that reads no settlement at all is as inert as one handed no frame, so it is refused alike.
    """
    hungry = _funding_consumers(entries)
    if not hungry:
        return
    settled, total = panel.settled_symbols, len(panel.symbols)
    if panel.funding is None:
        raise click.ClickException(
            f"{', '.join(hungry)} consumes funding history under these params, so --no-funding would run the "
            "signal on inputs it was never judged on (E-040 / KILL-027). Pass --funding, or choose params "
            "that read none (tsmom: crowding_window 0) to run the control arm deliberately."
        )
    if settled == 0:
        raise click.ClickException(
            f"{', '.join(hungry)} consumes funding history, but the archive under this root holds no "
            f"settlement for any of the {total} symbols in the panel, so the signal would read zeros and be "
            "as inert as it is under --no-funding (E-040 / KILL-027). Run `starquant data sync` first."
        )
    if settled < total:
        click.echo(
            f"warning: {', '.join(hungry)} reads funding and only {settled}/{total} symbols have any "
            "settlement stored; the rest read as zero, which the signal cannot tell from calm funding."
        )


def _funding_facts(entries: Sequence[StrategyEntry], panel: Panel) -> dict[str, Any]:
    """What the signals required of funding, beside what the panel actually carried.

    Recorded as ``funding_inputs``, deliberately not ``funding``: a report already carries
    ``dataset.funding`` (D-040), which counts FILES IN THE ARCHIVE, and both blocks would then hold a
    ``symbols`` key meaning different things - 2 files on disk against a 4-symbol panel.  On a
    partially-synced root the two numbers even coincide by accident, which is the worst kind of
    collision to leave in the artifact an operator reads to decide whether to trust a strategy.

    Reports recorded the *cost model's* ``use_funding`` and nothing about the signals' own requirement, so
    a reader could not tell a modifier that was absent from one that ran on nothing.  ``_require_funding``
    now refuses both of the wholly-inert cases, which leaves this to record the partial one it lets run:
    a symbol with no archive contributes a zero column that tsmom's crowding rank reads as uncrowded, so
    ``symbols_settled`` is what keeps a thinner modifier legible on disk rather than merely quieter.
    """
    return {
        "required_by": _funding_consumers(entries),
        "panel_carried": panel.funding is not None,
        "symbols_settled": panel.settled_symbols,
        "panel_symbols": len(panel.symbols),
    }
