"""``starquant research validate``：走 walk-forward 与 CPCV 的完整判定，并写 ledger。

它是唯一一条会计费的主路径。不显式传 `--grid`（与在架指针一致）或 `--charge N` 就拒跑——
那不是礼貌，是 family gate 的名额：一次误用默认 16 格网格花掉过约 35% 的 headroom。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import click
import numpy as np
import pandas as pd

from starquant_alpha.backtest import BacktestResult, CostModel, benchmark_returns, run_backtest
from starquant_alpha.registry import StrategyEntry, evidence_construction_digest
from starquant_alpha.report import render_markdown
from starquant_alpha.validation.cpcv import cpcv_evaluate, cpcv_splits
from starquant_alpha.validation.ledger import (
    TrialRecord,
    all_trials,
    dsr_inputs,
    ledger_scope,
    parse_ledger,
    resolve_ledger_path,
    unique_trials,
)
from starquant_alpha.validation.metrics import (
    sharpe,
)
from starquant_alpha.validation.multiple_testing import (
    multiple_testing_report,
    oos_selection_threshold,
)
from starquant_alpha.validation.pipeline import layers_applied, score_book
from starquant_alpha.validation.stability import (
    REGIME_VOL_WINDOW_DAYS,
    break_even_cost_multiple,
    cost_stress,
    parameter_neighborhood,
    regime_split_sharpes,
    slippage_levels,
    slippage_stress,
    time_split_sharpes,
    trailing_benchmark_vol,
)
from starquant_alpha.validation.verdict import decide
from starquant_alpha.validation.walk_forward import param_key, walk_forward_evaluate, walk_forward_folds
from starquant_cli import research
from starquant_cli.research_book_eval import (
    _book_guards,
    _embargo_bars,
    _exit_params,
    _stressed_oos_gate,
)
from starquant_cli.research_grids import (
    DEFAULT_GRIDS,
    _grid,
    _selected_key,
)
from starquant_cli.research_ledger_io import (
    _charge_signal_search,
    _construction_digest,
    _overlay_digest,
    _preregistration,
    _refuse_an_undeclared_charge,
    _search_space_version,
    _symbol_set_hash,
)
from starquant_cli.research_options import (
    _common_options,
    _embargo_option,
)

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_cli.research_panel import (
    _entry,
    _funding_facts,
    _load,
    _membership,
    _model,
    _require_funding,
    _resolve_symbols,
    _wants_metrics,
    _wants_spot,
)
from starquant_cli.research_report import (
    _MARGIN_BUFFER_NOTE,
    _break_even_row,
    _caliber_note,
    _embargo_note,
    _fmt,
    _full_sample_tail_note,
    _grid_table,
    _pbo_note,
    _power_rows,
    _regime_rows,
    _stamp,
    _write,
)
from starquant_data.manifest import build_manifest
from starquant_governance.policy import Policy
from starquant_live.composition import (
    cost_model,
    impact_model,
)
from starquant_shared.config import load_yaml


@research.command("validate")
@_common_options
@click.option("--grid", default="", help="JSON {param: [values...]} (default grid per strategy)")
@click.option(
    "--select",
    "select",
    default="",
    help=(
        "JSON {param: value} naming the ONE grid cell a pre-registered rule chose, reported as "
        "`best_params` instead of the full-sample argmax.  Requires --prereg; the argmax is recorded "
        "beside it either way."
    ),
)
@click.option(
    "--charge",
    default=None,
    type=int,
    help=(
        "how many rows this run appends to the strategy's ledger bucket, stated out loud.  Required "
        "when the strategy is an enabled registry entry and the grid is not the one its cited evidence "
        "used; `undeclared_charge` carries the run that made this a check rather than a RUNBOOK line."
    ),
)
@click.option("--folds", default=5, show_default=True)
@click.option("--min-train", default=4000, show_default=True, help="bars before the first test fold")
@click.option("--purge", default=50, show_default=True)
@_embargo_option
@click.option("--cpcv-groups", default=6, show_default=True)
@click.option(
    "--prior-trials",
    default=0,
    show_default=True,
    help="configurations of this strategy already tried in earlier rounds (added to the DSR denominator)",
)
@click.option(
    "--holdout-months",
    default=0,
    show_default=True,
    help="reserve the last N months (KILL-006), cut before folds; unused by choice, see docs/RESEARCH_LOG.md",
)
@click.option(
    "--guards/--no-guards",
    default=True,
    show_default=True,
    help="replay the book-level guards the live loop applies (gross cap + daily-loss pause)",
)
@click.option(
    "--exits/--no-exits",
    default=True,
    show_default=True,
    help="apply the profile's exit overlay, as the live loop does (D-012)",
)
@click.option(
    "--capital",
    default=0.0,
    show_default=True,
    help=(
        "USDT the book runs, for the DL-C1 impact model.  0 keeps the flat, scale-free cost model "
        "every archived report was produced under; a positive value charges the square-root law on top."
    ),
)
@click.option(
    "--prereg",
    default="",
    help=(
        "git commit that pre-registered this run (DL-K3/DL-G9).  Recorded with its commit time so "
        "'pre-registration came first' is a fact in the artefact rather than in RESEARCH_LOG prose."
    ),
)
def research_validate(
    strategy: str,
    params: str,
    prereg: str,
    capital: float,
    root: str,
    symbols: str,
    interval: str,
    start: str | None,
    end: str | None,
    profile: str,
    registry_path: str,
    costs_path: str,
    execution: str,
    funding: bool,
    out: str,
    min_history: int | None,
    universe_mode: str,
    min_tenure: int,
    grid: str,
    select: str,
    charge: int | None,
    folds: int,
    min_train: int,
    purge: int,
    embargo: int | None,
    cpcv_groups: int,
    prior_trials: int,
    holdout_months: int,
    grids: str,
    guards: bool,
    exits: bool,
) -> None:
    """Walk-forward + CPCV + DSR/PBO + stability for one strategy; writes the evidence report for the registry."""
    profile_payload = load_yaml(profile)
    entry = _entry(strategy, registry_path, params, grids)
    # Priced before the panel is loaded, because what a run costs is decided by the grid and the grid is
    # already known here - afterwards the only thing left to do about it is to have not run it.
    combos = _grid(strategy, grid, entry.params)
    _refuse_an_undeclared_charge(strategy, registry_path, grid, len(combos), charge)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    # DL-D4 and DL-D5: carry the metrics or spot columns only when this strategy declares it reads
    # them, so a run that reads none does not pay for the alignment - and does not carry the one place
    # a look-ahead could enter data it never uses.
    # `_entry` above already ran `_resolve_mined` + `get_signal`, so a mined id is registered by now
    # and answers for itself.  Params are deliberately not passed: both predicates are derived from the
    # expression tree, so they cannot depend on which grid cell is being scored.
    panel = _load(
        root,
        chosen,
        interval,
        start,
        end,
        funding,
        metrics=_wants_metrics(strategy, {}),
        spot=_wants_spot(strategy, {}),
    )
    # KILL-006: the reserved tail is cut here, before folds, membership or costs touch it, so nothing in this
    # run can see it.  It is recorded in the report, which is what makes the reservation checkable later:
    # a promise in prose is not a holdout, and every OOS number produced without one has been selected on.
    holdout: dict[str, Any] | None = None
    if holdout_months > 0:
        last = pd.Timestamp(panel.index[-1])
        cutoff = last - pd.DateOffset(months=holdout_months)
        held = panel.slice(start=cutoff)
        panel = panel.slice(end=cutoff)
        if len(panel.index) < 2:
            raise click.ClickException(f"--holdout-months {holdout_months} leaves no training data")
        holdout = {
            "months": holdout_months,
            "start": str(cutoff),
            "end": str(last),
            "bars_reserved": len(held.index),
            "bars_used": len(panel.index),
        }
        click.echo(
            f"holdout: reserving {holdout['bars_reserved']} bars from {cutoff.date()} to {last.date()} "
            f"({holdout_months} months); this run sees {holdout['bars_used']} bars"
        )
    membership = _membership(root, universe_mode, panel, min_tenure)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    impact = impact_model(load_yaml(costs_path), capital=capital)
    # the combos, not `entry.params`: a grid may set the funding term to 0 in every arm it evaluates
    _require_funding([StrategyEntry(id=strategy, params=combo) for combo in combos], panel)
    bpy = panel.bars_per_year
    # The two layers the loop applies after the model, replayed here so the evidence describes the book
    # that trades (2026-09-08 audit).  `--no-guards --no-exits` reproduces every report written before.
    book_guards = _book_guards(profile_payload, guards)
    exit_params = _exit_params(profile_payload, exits, interval)
    nets: dict[str, pd.Series] = {}
    params_by_key: dict[str, dict[str, Any]] = {}
    results: dict[str, BacktestResult] = {}
    decisions: dict[str, pd.DataFrame] = {}  # post-overlay decision weights, so the re-runs below layer once
    click.echo(f"evaluating {len(combos)} parameter sets on {len(panel.symbols)} symbols x {len(panel.index)} bars")
    for combo in combos:
        key = param_key(combo)
        model = _model(StrategyEntry(id=strategy, params=combo), profile_payload, interval, min_history)
        weights, _c, _p = model.evaluate(panel, membership)
        result, decisions[key] = score_book(
            panel, weights, cost, execution=execution, guards=book_guards, exits=exit_params, impact=impact
        )
        results[key] = result
        nets[key] = result.portfolio_net
        params_by_key[key] = combo
    common_index = None
    for series in nets.values():
        common_index = series.index if common_index is None else common_index.intersection(series.index)
    assert common_index is not None
    nets = {key: series.reindex(common_index).fillna(0.0) for key, series in nets.items()}
    n_bars = len(common_index)
    fold_list = walk_forward_folds(n_bars, folds, min_train=min(min_train, max(n_bars // 2, 2)), purge=purge)
    wf = walk_forward_evaluate(nets, params_by_key, fold_list, bpy)
    wf_summary = wf.summary(bpy)
    embargo_bars = _embargo_bars(purge, embargo)
    cpcv = cpcv_evaluate(
        nets, cpcv_splits(n_bars, n_groups=cpcv_groups, n_test_groups=2, purge=purge, embargo=embargo_bars), bpy
    )
    full_sharpes_raw: dict[str, float | None] = {key: sharpe(series, bpy) for key, series in nets.items()}
    full_sharpes: dict[str, float] = {
        key: (value if value is not None else -np.inf) for key, value in full_sharpes_raw.items()
    }
    argmax_key = max(full_sharpes, key=lambda k: full_sharpes[k])
    best_key = _selected_key(select, params_by_key, prereg) or argmax_key
    matrix = np.column_stack([nets[key].to_numpy(dtype=float) for key in nets])
    # D-024: the construction the numbers were produced by, named once and used by both the report and
    # the ledger signature, so the two can never describe different books.
    _run_portfolio = _model(
        StrategyEntry(id=strategy, params=combos[0]), profile_payload, interval, min_history
    ).portfolio.__dict__
    ledger_path = resolve_ledger_path(out=out)
    # Charged BEFORE the denominator below is read, which is the whole difference between this and the
    # way `mine` charges.  A shortlist is not a verdict, so `mine` can write its rows at the end; this
    # command decides a PASS/FAIL, and a verdict computed under a denominator that excludes the run's
    # own search is the un-charged number shipping while the next run pays for this one's selection.
    signal_search = _charge_signal_search(
        strategy,
        panel,
        combos,
        ledger_path,
        range_start=str(common_index[0]),
        range_end=str(common_index[-1]),
    )
    ledger_lines = ledger_path.read_text(encoding="utf-8").splitlines() if ledger_path.exists() else []
    # R0 is a CALIBER, not a number, so the field that names it has to be the thing this line obeys.
    # `gate_scope` sat in `policy_digest()` - promising that an edit to it would be visible - while
    # `ledger_scope` was called unconditionally, so editing it moved the digest and changed nothing.
    # Refusing rather than silently falling back: the alternative caliber fails the incumbent on an
    # honest grid (KILL-AR-01), which is a decision to take deliberately or not at all.
    scope = Policy().gate_scope
    if scope != "per_strategy_bucket":
        raise click.ClickException(
            f"policy.gate_scope is {scope!r} and this command only implements 'per_strategy_bucket'.  "
            "Changing R0's caliber is a rule-version change with its own evidence, not a flag."
        )
    prior_records = parse_ledger(ledger_lines, ledger_scope(strategy))
    # R0: the other caliber, reported and never applied.  The gate is the strategy bucket; this says what
    # the whole library would have asked for, so the choice stays arguable instead of merely stated.
    whole_library = (
        len(
            unique_trials(
                all_trials(ledger_lines), range_end_granularity_days=Policy().trial_range_end_granularity_days
            )
        )
        or 1
    )
    period_sharpes = {
        key: (None if value is None else value / math.sqrt(bpy)) for key, value in full_sharpes_raw.items()
    }
    pooled = dsr_inputs(
        prior_records,
        period_sharpes,
        bpy,
        manual_prior_trials=prior_trials,
        current_range=(str(common_index[0]), str(common_index[-1]), len(panel.symbols)),
        # The other half of the signature.  Built here rather than defaulted: an exclusion set shorter
        # than a signature matches nothing, which turns D-024's "a replay is one trial" into silent
        # double charging.
        current_context=(
            _construction_digest(_run_portfolio, cost, execution, impact),
            # The overlay slot used to be a hardcoded "" because `validate` applied no overlays.  It does
            # now, so the exclusion has to name the same stack the ledger rows are written with - a
            # signature that does not match its own rows excludes nothing and charges the run twice.
            _overlay_digest(book_guards, exit_params),
            _symbol_set_hash(panel.symbols),
            _search_space_version(strategy, grids),
        ),
        range_end_granularity_days=Policy().trial_range_end_granularity_days,
    )
    mt = multiple_testing_report(
        nets[best_key].to_numpy(dtype=float),
        matrix,
        bars_per_year=bpy,
        prior_trials=prior_trials,
        pooled_n_trials=pooled["n_trials"],
        pooled_sharpe_variance=pooled["sharpe_variance"] if pooled["pooled_sharpes"] >= 2 else None,
    )
    mt["ledger_trials"] = pooled["ledger_trials"]

    def evaluate_params(candidate: Mapping[str, Any]) -> float | None:
        # 走 `score_book`，与上面那条计价路径同一台机器。此前这里是 `_overlaid` + `run_backtest` 的
        # 两步写法：**今天它算的是同一件事**——`score_book` 的套层那行与 `_overlaid` 字符级相同，而
        # 这里不传 `impact`，`score_book` 的默认也是 `None`。所以这不是修一个读数错，是拆掉一条会漂
        # 的缝：`score_book` 一旦改套层顺序或再加一层，邻域探针不会自己跟上，于是同一份报告里
        # 「最优那一格」与「它周围的格子」会按两种口径算，而没有任何东西会说出来。
        model = _model(StrategyEntry(id=strategy, params=dict(candidate)), profile_payload, interval, min_history)
        weights, _c, _p = model.evaluate(panel, membership)
        priced, _overlay = score_book(panel, weights, cost, execution=execution, guards=book_guards, exits=exit_params)
        return sharpe(priced.portfolio_net, bpy)

    neighbourhood = parameter_neighborhood(
        evaluate_params, params_by_key[best_key], numeric_keys=tuple(sorted(DEFAULT_GRIDS.get(strategy, {})))
    )
    # `decisions[best_key]`, not `results[best_key].weights.shift(-1)`: the executed frame is post-guard,
    # so inverting it would re-price a book the guards had already trimmed and then trim it again.
    best_weights = decisions[best_key]

    # DL-C1, 2026-09-09: `impact=impact` here and in `slippage_stress` below.  Without it a report whose
    # header says `impact_model: {capital: 100000}` had its walk-forward priced under the square-root law
    # and `cost_stress` priced flat - and `cost_stress.x2` is a GATE that `verdict.decide` reads, so the
    # artefact's own label did not describe the number the verdict turned on.  The error ran in the
    # permissive direction (flat is cheaper than flat+impact), which is the direction that matters.
    # The multiplier scales the fee rates (`turnover_bps`; `carry_bps_per_bar`, 0 from costs.yaml), never impact.
    def _priced(multiplier: float) -> pd.Series:
        return run_backtest(
            panel,
            best_weights,
            CostModel(cost.turnover_bps * multiplier, cost.carry_bps_per_bar * multiplier, cost.use_funding),
            execution=execution,  # type: ignore[arg-type]
            guards=book_guards,
            impact=impact,
        ).portfolio_net

    stressed_nets = {multiplier: _priced(multiplier) for multiplier in (1.0, 1.5, 2.0)}
    stress = cost_stress(stressed_nets, bpy)
    # The same stressed series re-asked against D-028's gate.  `cost_stress` is a FULL-SAMPLE Sharpe and
    # the gate compares an OUT-OF-SAMPLE one, so the two are not subtractable - and the 2026-09-14 audit
    # caught exactly that subtraction, setting the gate's +0.0426 margin against a cost-doubling effect
    # measured on a different series.  Nothing in the report answered "does it still clear the gate if
    # costs double"; this does, on the same folds and the same trials count.
    # `.reindex(common_index)` is load-bearing and not tidiness: `fold_list` was cut against
    # `len(common_index)`, while a fresh `run_backtest` returns its own longer index, so slicing the raw
    # series by those folds silently reads different bars.  It showed up as an x1 cell that did not equal
    # `best_key_oos_sharpe` (6.90 against 6.02 on the fixture).  `cost_stress` above is deliberately left
    # on the UNreindexed series: its `x2` cell is a gate `verdict.decide` reads and every archived report
    # carries it, so it keeps the series it has always had.
    stress_gate = {
        f"x{multiplier:g}": _stressed_oos_gate(
            net.reindex(common_index).fillna(0.0), fold_list, bpy, pooled["n_trials"]
        )
        for multiplier, net in stressed_nets.items()
    }

    # G8: how far costs can rise before mean net return is zero, on the two series priced just above.
    # Reported, never enforced: `decide` reads `cost_stress.x2` and no key of this block.
    def _oos(net: pd.Series) -> pd.Series:
        aligned = net.reindex(common_index).fillna(0.0)
        oos: pd.Series = pd.concat([aligned.iloc[fold.test_slice] for fold in fold_list])
        return oos

    break_even = {
        "full_sample": break_even_cost_multiple(_priced, stressed_nets),
        "oos": break_even_cost_multiple(_priced, stressed_nets, _oos),
        "basis": {
            "multiple": "on turnover_bps and carry_bps_per_bar together, as cost_stress; funding and impact unscaled",
            "zero_of": "mean per-bar net return, i.e. the Sharpe's zero: not D-028's threshold, not compounded return",
            "full_sample": "the series cost_stress prices",
            "oos": "the series cost_stress_gate prices: best_key re-priced, on common_index, fold test slices",
        },
    }
    costs_payload = load_yaml(costs_path)
    fee_bps = float(costs_payload.get("taker_fee_bps", 5.0))
    levels = slippage_levels(
        taker_fee_bps=fee_bps, levels=[float(v) for v in costs_payload.get("slippage_stress_bps", []) or []]
    )
    slippage_nets = {
        level: run_backtest(
            panel,
            best_weights,
            CostModel(total, cost.carry_bps_per_bar, cost.use_funding),
            execution=execution,  # type: ignore[arg-type]
            guards=book_guards,
            impact=impact,
        ).portfolio_net
        for level, total in levels.items()
    }
    slippage = slippage_stress(slippage_nets, bpy)
    # D-028's gate on the slippage grid, which is the grid the question is actually about.
    #
    # `cost_stress_gate` above answers "does it still clear if COSTS scale", and scaling costs scales
    # the taker fee with them.  The fee is a contract constant - VIP0 taker is 5.0 bps whatever happens
    # to execution - so `x1.5` charges 7.5 bps of fee that no venue will ever bill, and its margin is
    # therefore not the margin of a slippage assumption being wrong.  `slippage_levels`' docstring has
    # made that argument since the grid was added; what was missing is that only the multiplier grid
    # had a gate attached, so the artefact could answer the question it was not asked and not the one
    # it was.  (The two grids coincide numerically wherever the totals match - `x1.5` and `slip5.5` are
    # both 10.5 bps - which is exactly why the labels have to be right: reading `x1.5` as a slippage
    # result is correct by accident at one cell and wrong at every other.)
    #
    # Same `.reindex(common_index)` as above, and load-bearing for the same reason: `fold_list` was cut
    # against `len(common_index)` while a fresh `run_backtest` returns its own longer index.
    slippage_gate = {
        f"slip{level:g}": _stressed_oos_gate(net.reindex(common_index).fillna(0.0), fold_list, bpy, pooled["n_trials"])
        for level, net in sorted(slippage_nets.items())
    }
    # The convention the default drops: `open_to_close` never earns close_t -> open_{t+1}, and the loop
    # holds through every one of those.  Measured on the pit book it is worth -0.029 OOS Sharpe, i.e. the
    # dropped component is mildly ADVERSE to this book, so "conservative" is true of the entry price and
    # not of the holding return.  Priced here as a comparator rather than adopted (adopting it would
    # break comparability with every report back to the August 2026 baseline).
    other_execution = "close_to_close" if execution == "open_to_close" else "open_to_close"
    comparison = run_backtest(panel, best_weights, cost, execution=other_execution, guards=book_guards).summary()  # type: ignore[arg-type]
    # GAP-SF02 (docs/analysis/2026-09-17-strategy-factor-belief-deep-analysis.md).  Until this block every
    # split a report made of its returns was by calendar - folds, `time_split_sharpes`, the window q10 -
    # and on 2026-09-17 "no report shows it earning in any state" was read as "it earns in no state"
    # (analysis-calibration.md).  The benchmark is held to the run's own `membership`, so the state is
    # the volatility of what the book could hold; it is taken over the whole panel rather than
    # `common_index`, so the first OOS bar's label has its full trailing window behind it.  Reported
    # only: `decide` never reads it.
    bench = benchmark_returns(panel, execution, panel.symbols, membership)  # type: ignore[arg-type]
    regime_vol = trailing_benchmark_vol(bench, bpy, REGIME_VOL_WINDOW_DAYS)
    report: dict[str, Any] = {
        "kind": "validation",
        "strategy": strategy,
        "interval": interval,
        "universe_mode": universe_mode,
        "min_tenure": min_tenure,
        "holdout": holdout,
        "symbols": panel.symbols,
        "range": {"start": str(common_index[0]), "end": str(common_index[-1]), "bars": n_bars},
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts([StrategyEntry(id=strategy, params=c) for c in combos], panel),
        "execution": execution,
        "grid_size": len(combos),
        "grid": json.loads(grid) if grid else DEFAULT_GRIDS.get(strategy, {}),
        # D-024: a strategy's numbers are produced by a portfolio construction, so the report has to say which
        # one.  Without this a band or half-life change in the profile silently detaches the live book from its
        # cited evidence, and the startup gate cannot see it because it compares signal params only.
        "portfolio": _run_portfolio,
        # ...and by the two layers applied after it.  `null` is a statement ("this run applied none"), not an
        # absence: `registry.construction_problems` refuses a null here against a loop that runs the layer,
        # and skips a report that carries no key at all.
        "book_guards": None if book_guards is None else dict(vars(book_guards)),
        "exits": None if exit_params is None else dict(vars(exit_params)),
        # The same two, plus the band convention, in the shape every other report kind now carries.
        # Kept BESIDE the two above rather than replacing them: `registry.construction_problems` reads
        # `book_guards` and `exits` by name out of archived reports, and moving them would make every
        # report written from here on unreadable to the startup gate.
        "layers": layers_applied(band="model", guards=book_guards, exits=exit_params),
        # The data this verdict was computed from.  Everything else here already names itself - the report
        # has a digest, the registry a fingerprint, the construction another - but the dataset did not, and
        # on 2026-09-04 the membership table was rebuilt monthly -> daily while the profile still described
        # it as monthly.  A verdict that cannot say which data produced it is a pointer waiting to go stale.
        "dataset": build_manifest(root, interval).to_dict(),
        "folds": folds,
        "min_train": min_train,
        "purge": purge,
        # D-024 asks that the fold vector be reproducible from the report alone, and until now the
        # report said `purge` and let a reader assume the CPCV embargo equalled it.  It did - that is
        # exactly the 2026-09-13 finding - but "it happened to" and "the artefact says so" are
        # different facts.  Reports written before this key exists simply do not carry it; every
        # reader has to treat its absence as "embargo == purge", which is what they were.
        "embargo": embargo_bars,
        "cpcv_groups": cpcv_groups,
        "prior_trials_declared": prior_trials,
        "trial_sharpes": {key: full_sharpes_raw[key] for key in nets},
        "ledger": {
            **{
                key: pooled[key]
                for key in ("ledger_trials", "ledger_rows", "duplicate_rows", "replayed_rows", "pooled_sharpes")
            },
            "whole_library_trials": whole_library,
        },
        # What the signal's own search cost, where the verdict can be read next to it.  Absent for the
        # eight signals that search nothing, which is why it is spread in rather than written as null:
        # "this signal ran no search" and "its search found nothing" are different facts (DL-K2).
        **({"signal_search": signal_search} if signal_search is not None else {}),
        "best_params": params_by_key[best_key],
        # Which rule picked that, and what the other one would have picked.  `validate` has always
        # chosen by full-sample Sharpe, and round 7 recorded the consequence: a candidate that wins on
        # a PRE-REGISTERED rule but is a shade lower on the full sample can never be a grid report's
        # `best_params`, so adopting one meant issuing a second, single-configuration report (H-001's
        # `020459Z` is that report).  Naming the cell is the cheaper half; recording the argmax beside
        # it is what keeps the naming honest, because a reader can see both and `--select` cannot
        # quietly become "whichever cell looks best afterwards" - it needs a `--prereg` commit whose
        # timestamp is in the artefact.
        "best_params_selected_by": "pre-registered rule (--select)" if select else "full-sample argmax",
        "full_sample_argmax_params": params_by_key[argmax_key],
        "full_sample": results[best_key].summary(),
        # F3 (KILL-Q2): `best_params` is the full-sample argmax and is what reaches the registry,
        # while `walk_forward.oos_sharpe` belongs to whatever each fold chose.  When the two differ
        # the headline describes a mixture no configuration ever was, so the shipped configuration's
        # own walk-forward number is recorded next to it rather than left for a reader to assume.
        "best_key_oos_sharpe": wf.oos_sharpe_for(best_key, fold_list, bpy),
        "walk_forward": wf_summary,
        # D-028: the OOS Sharpe a strategy must clear given how many configurations were tried on it.
        "oos_selection": oos_selection_threshold(
            wf.oos_returns.to_numpy(dtype=float), n_trials=pooled["n_trials"], bars_per_year=bpy
        ),
        # R0 (DL-G1): the same gate at the whole-library N, REPORTED and never enforced.  `verdict.decide`
        # reads `oos_selection` and nothing else, and a test holds that.  Two numbers rather than one
        # because "which N" was the single most consequential open choice in the governance rules, and an
        # artefact that carries only the caliber that was chosen cannot be used to re-open the choice.
        **(
            {
                "oos_selection_whole_library": oos_selection_threshold(
                    wf.oos_returns.to_numpy(dtype=float), n_trials=whole_library, bars_per_year=bpy
                )
            }
            if Policy().report_whole_library_n
            else {}
        ),
        "cpcv": cpcv,
        "multiple_testing": mt,
        "stability": {
            "time_split_sharpes": time_split_sharpes(wf.oos_returns, 4, bpy),
            "regime_split_sharpes": regime_split_sharpes(wf.oos_returns, regime_vol, bpy),
            # What the three rows were computed from, in the artefact: "it happened to be 30 days" and
            # "the report says 30 days" are different facts (the `embargo` key's lesson, 2026-09-13).
            "regime_split_basis": {
                "series": "walk_forward oos_returns, the series time_split_sharpes splits",
                "state": "annualised std, over vol_window_days, of benchmark_returns: equal-weight, zero cost, "
                "over the symbols the book could hold at each bar (pit members; every panel symbol if static)",
                "vol_window_days": REGIME_VOL_WINDOW_DAYS,
                "label_on_bar_t_reads": "benchmark bars through t-1: what was known when bar t's position was decided",
                "cut_points": "this sample's own terciles: the state is ex-ante, the cut points are not.  Volatility "
                "trends over years, so a tercile is partly a calendar period: read it against time_split_sharpes",
            },
            "parameter_neighborhood": neighbourhood,
        },
        "cost_stress": stress,
        "cost_stress_gate": stress_gate,
        "cost_break_even": break_even,
        # The fee is a contract constant and the slippage assumption is the half the loop measures, so
        # this varies only the second one at declared levels (`costs.yaml: slippage_stress_bps`).
        "slippage_stress": slippage,
        "slippage_stress_gate": slippage_gate,
        "execution_comparison": {"execution": other_execution, **comparison},
        # DL-G9.  Two fields that exist so a machine can read what a person used to read in prose.
        # `preregistration` is null when the run declared none - a statement, not an absence, the same
        # distinction `book_guards`/`exits` make above.  `evidence_construction` is over exactly the
        # blocks `registry.construction_problems` compares, so a later reader can check "evidence
        # construction == live construction" with a string comparison instead of a config they no
        # longer have.  It is NOT the ledger's `construction_digest` (`_construction_digest` above),
        # which also folds in costs and execution because those make two runs two TRIALS; this one
        # answers a different question and folding the two would break both.
        "preregistration": _preregistration(prereg),
        "evidence_construction": evidence_construction_digest(
            _run_portfolio,
            None if book_guards is None else dict(vars(book_guards)),
            None if exit_params is None else dict(vars(exit_params)),
        ),
        # DL-C1: what size this verdict assumes.  `capital: 0` is the flat, scale-free cost model every
        # archived report was produced under, and saying so is the point - it is an assumption the
        # reports have always carried silently.  This line was claimed as delivered on 2026-09-08 and
        # was not: it was eaten when the surrounding edit was replayed, and no test asked for it.
        # `test_a_validation_report_names_the_size_it_assumed` now does.
        "impact_model": dict(vars(impact)),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    verdict, reasons = decide(report)
    report["verdict"] = verdict
    report["reasons"] = reasons
    markdown = render_markdown(
        f"Validation: {strategy} — {verdict}",
        [
            ("Range", report["range"]),
            (
                "Holdout (KILL-006)",
                holdout or {"months": 0, "note": "no tail reserved: every bar was available to this run"},
            ),
            (
                "Book guards / exits (the layers the loop applies)",
                {"guards": report["book_guards"], "exits": report["exits"], "margin_buffer": _MARGIN_BUFFER_NOTE},
            ),
            ("Best params (full sample)", params_by_key[best_key]),
            ("Full sample", report["full_sample"]),
            (
                "Walk-forward (out of sample)",
                {
                    **{k: v for k, v in wf_summary.items() if k != "chosen_params"},
                    "best_key_oos_sharpe": report["best_key_oos_sharpe"],
                    "selection_exercised": _full_sample_tail_note(wf_summary.get("oos_is_full_sample_tail")),
                },
            ),
            ("CPCV", {**{k: v for k, v in cpcv.items() if k != "chosen"}, "embargo": _embargo_note(embargo_bars)}),
            ("Multiple testing", {**mt, "pbo_is_informative": _pbo_note(mt.get("grid_trials"))}),
            # Immediately above the gate it moves, because at 19,578 candidates against a four-cell grid
            # the search IS the denominator and a reader who sees only `n_trials` cannot tell where it
            # came from.  The per-configuration facts stay in the JSON; this is the headline.
            *(
                [
                    (
                        "Signal's own search (DL-K2)",
                        {k: v for k, v in signal_search.items() if k != "configurations"},
                    )
                ]
                if signal_search is not None
                else []
            ),
            (
                "Selection-deflated OOS threshold (D-028)",
                {
                    **{k: v for k, v in report["oos_selection"].items() if k != "power"},
                    "caliber": _caliber_note(report["oos_selection"], report.get("oos_selection_whole_library")),
                },
            ),
            # The same gate read the other way round.  Pulled out of the spread above rather than left
            # as one nested cell: `render_markdown` would print it as a Python dict on a single row,
            # and this is the block the 2026-09-18 analysis says has been missing from every answer to
            # "is the bar too high" (Q-SY1).
            (
                "Power of that gate (D-020 + D-028): what it would have detected",
                _power_rows(report["oos_selection"].get("power")),
            ),
            # R0's other caliber, in the artefact rather than only in the payload.  It is the block DL-G1
            # added so that "which N" stays arguable, and until now the Markdown dropped it.
            *(
                [("The other caliber (R0: reported, never enforced)", report["oos_selection_whole_library"])]
                if report.get("oos_selection_whole_library")
                else []
            ),
            (
                "Cost stress against that gate (same folds, same N, best_key basis)",
                {
                    level: f"oos={_fmt(v['oos_sharpe'])} threshold={_fmt(v['threshold'])} "
                    f"margin={_fmt(v['margin'])} clears={_fmt(v['clears'])}"
                    for level, v in stress_gate.items()
                },
            ),
            (
                "Slippage stress against that gate (fee held fixed - the grid the question is about)",
                {
                    level: f"oos={_fmt(v['oos_sharpe'])} threshold={_fmt(v['threshold'])} "
                    f"margin={_fmt(v['margin'])} clears={_fmt(v['clears'])}"
                    for level, v in slippage_gate.items()
                },
            ),
            (
                "Stability",
                {
                    "time_split_sharpes": report["stability"]["time_split_sharpes"],
                    "worst_neighbour_degradation": neighbourhood["worst_degradation"],
                    "parameter_neighbourhood": {
                        key: f"down={_fmt(value.get('down'))} base={_fmt(neighbourhood['base'])} up={_fmt(value.get('up'))}"
                        for key, value in (neighbourhood.get("neighbours") or {}).items()
                    },
                },
            ),
            (
                "Sharpe by benchmark-volatility regime (reported, never enforced)",
                _regime_rows(report["stability"]["regime_split_sharpes"], report["stability"]["regime_split_basis"]),
            ),
            ("Grid (full-sample Sharpe per configuration)", _grid_table(params_by_key, full_sharpes_raw)),
            (
                "Cost stress (Sharpe)",
                {**stress, "break-even multiple m* (never enforced)": _break_even_row(break_even)},
            ),
            ("Slippage stress (Sharpe; fee fixed)", slippage),
            (f"Same book under {other_execution}", {"annualized_sharpe": comparison["annualized_sharpe"]}),
            ("Verdict", {"verdict": verdict, "reasons": reasons or ["-"]}),
        ],
    )
    path, digest = _write(out, f"{strategy}-validation-{_stamp()}", report, markdown)
    stamp = datetime.now(UTC).isoformat()
    with ledger_path.open("a", encoding="utf-8") as handle:
        for key in nets:
            handle.write(
                TrialRecord(
                    strategy=strategy,
                    param_key=key,
                    sharpe_annual=full_sharpes_raw[key],
                    bars_per_year=bpy,
                    recorded_at=stamp,
                    range_start=str(common_index[0]),
                    range_end=str(common_index[-1]),
                    symbols=len(panel.symbols),
                    run_id=path.stem,
                    construction_digest=_construction_digest(_run_portfolio, cost, execution, impact),
                    symbol_set_hash=_symbol_set_hash(panel.symbols),
                    search_space_version=_search_space_version(strategy, grids),
                    # D-024: the same params under a different overlay stack are a different trial, not a
                    # replay.  Without this a `--no-guards` re-run would dedupe onto the guarded row.
                    overlay_digest=_overlay_digest(book_guards, exit_params),
                ).to_json()
                + "\n"
            )
    click.echo(
        f"trials ledger: {ledger_path} (+{len(nets)}; {pooled['ledger_trials']} already in ledger, {prior_trials} declared pre-ledger)"
    )
    if signal_search is not None:
        # Where the cost is incurred, as `mine` prints its own: this run's denominator is mostly this
        # line, and reading it off `multiple_testing.n_trials` afterwards is how it stayed invisible.
        click.echo(
            f"signal search ({signal_search['bucket']}): {signal_search['candidates']} candidates examined, "
            f"{signal_search['selected']} traded; +{signal_search['charged']} charged now, "
            f"family prior {signal_search['family_prior']['before']} -> {signal_search['family_prior']['after']}"
        )
    click.echo(f"best params: {params_by_key[best_key]}")
    click.echo(
        f"walk-forward OOS sharpe={_fmt(wf_summary['oos_sharpe'])} return={wf_summary['oos_return']:.4f} consistency={_fmt(wf_summary['fold_consistency'])}"
    )
    if wf_summary["oos_is_full_sample_tail"]:
        # KILL-Q2: said out loud, because the number above reads like an out-of-sample estimate of a
        # selection procedure and here no fold had a choice to make.
        click.echo(
            "  NOTE: no fold had a choice (single configuration, or every fold picked the same one), "
            "so this OOS is the tail of one full-sample series, not a selection's out-of-sample record"
        )
    elif report["best_key_oos_sharpe"] is not None:
        click.echo(
            f"  the shipped configuration's own walk-forward OOS is {_fmt(report['best_key_oos_sharpe'])} "
            "(the headline above is the fold-selected mixture)"
        )
    click.echo(
        f"cpcv mean={_fmt(cpcv['oos_sharpe_mean'])} q05={_fmt(cpcv['oos_sharpe_q05'])} negative={_fmt(cpcv['fraction_negative'])}"
    )
    click.echo(
        f"dsr p={_fmt(mt['dsr_p_value'])} pbo={_fmt(mt['pbo'])} cost_stress={ {k: _fmt(v) for k, v in stress.items()} }"
    )
    click.echo(
        f"oos selection threshold={_fmt(report['oos_selection']['threshold_annual'])} "
        f"at {report['oos_selection']['n_trials']} trials, alpha={report['oos_selection']['alpha']}, "
        f"p_family={_fmt(report['oos_selection']['p_family'])} (D-028)"
    )
    power = report["oos_selection"].get("power")
    if power:
        detected = "  ".join(f"SR{d['true_sharpe_annual']:.1f}->{d['power']:.1%}" for d in power["detects"])
        click.echo(
            f"power of that gate ({power['gate_annual']:.4f}, {power['binding']} binds, "
            f"se={power['se_annual']:.4f}): {detected}  "
            "(selection + pass line only; CPCV/PBO/fold/cost x2 make the joint power LOWER)"
        )
    click.echo(
        f"grid of {mt['grid_trials']} is worth {_fmt(mt.get('grid_effective_trials'))} independent trials "
        "(reported; the gate's denominator is the raw ledger count)"
    )
    click.echo(f"VERDICT: {verdict} {reasons if reasons else ''}")
    click.echo(f"report: {path} sha256={digest}")
    click.echo("registry evidence block:")
    click.echo(f"    evidence: {{report: {path}, sha256: {digest}, verdict: {verdict}}}")
