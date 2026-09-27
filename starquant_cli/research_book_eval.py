"""把一本书变成读数：套退出层、定价、切 fold、过三道限额、和在跑的书比。

套层与定价的唯一实现在 `starquant_alpha.validation.pipeline.score_book`；这里是研究侧围绕它的
那一圈——fold 切法、限额、合并 sleeve、netting。`_overlaid` 只剩一个地址的用途，见它自己的
docstring；这个包里再没有第二处「先套层再定价」。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.backtest import BacktestResult, CostModel, run_backtest
from starquant_alpha.model import AlphaModel, FundingUnavailable
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel, interval_seconds
from starquant_alpha.portfolio import PortfolioParams, banded, cap_gross, combine_books
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.book_limits import (
    DECISION_SLIPPAGE_BPS,
    correlations_with_running,
    marginal_metrics,
    max_correlation,
    slippage_stress_decision,
    turnover_per_gross,
    turnover_ratio_to_main,
)
from starquant_alpha.validation.cpcv import cpcv_evaluate, cpcv_splits
from starquant_alpha.validation.ledger import (
    TrialRecord,
    dsr_inputs,
    ledger_scope,
    parse_ledger,
)
from starquant_alpha.validation.metrics import (
    compound,
    max_drawdown,
    sharpe,
    yearly_breakdown,
)
from starquant_alpha.validation.multiple_testing import (
    multiple_testing_report,
    oos_selection_threshold,
)
from starquant_alpha.validation.pipeline import layers_applied
from starquant_alpha.validation.stability import (
    cost_stress,
)
from starquant_alpha.validation.verdict import decide
from starquant_alpha.validation.walk_forward import Fold, param_key, walk_forward_evaluate, walk_forward_folds
from starquant_cli.research_feature_store import with_feature_store
from starquant_cli.research_ledger_io import _trial_signature

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_governance.policy import Policy
from starquant_live.composition import (
    load_registry,
    portfolio_params,
)


def _book_guards(profile: Mapping[str, Any], enabled: bool) -> BookGuardParams | None:
    """The two book-level guards the loop applies after the model (D-004), read off the same profile."""
    portfolio = profile.get("portfolio", {}) or {}
    return (
        BookGuardParams(
            max_weight=float(portfolio.get("max_weight", 0.15)),
            max_gross=float(portfolio.get("max_gross", 2.0)),
            daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
        )
        if enabled
        else None
    )


def _exit_params(profile: Mapping[str, Any], enabled: bool, interval: str) -> ExitParams | None:
    """The exit overlay the loop applies per symbol (D-012); ``None`` when off or when the profile disables it."""
    if not enabled:
        return None
    bars_per_day = max(1, 86_400 // interval_seconds(interval))
    params = ExitParams.from_mapping({**(profile.get("exits", {}) or {}), "bars_per_day": bars_per_day})
    return params if params.enabled else None


def _overlaid(weights: pd.DataFrame, close: pd.DataFrame, exits: ExitParams | None) -> pd.DataFrame:
    """套退出层——**不要在新代码里用它**，用 `starquant_alpha.validation.pipeline.score_book`。

    它今天还在，只因为一个地址：`scratchpad/p32f_embargo_and_decay.py` 从 `starquant_cli.research_cmd`
    导入它。那些脚本是**记录**（`pyproject.toml` 把 `scratchpad/*.py` 排除出格式化，理由逐字是
    「Reformatting either edits a record of what happened」），所以改它们等于改一份已经发生过的记录。

    2026-09-17 之前 `validate` 的邻域探针也走这里，于是「先套层再定价」在这个仓库里有两份表达。
    两份算的是同一件事，所以没有读数差——它是一条会漂的缝，不是一个 bug。探针已改走 `score_book`，
    剩下的就只有这个地址。
    """
    return weights if exits is None else apply_exits(weights, close, exits).weights


def _embargo_bars(purge: int, embargo: int | None) -> int:
    """The embargo a run actually uses.  `None` means "whatever `--purge` is", bit for bit.

    Every archived report was produced with `embargo == purge`, so the fallback is what keeps this
    change invisible to them.  Adopting a real embargo moves `cpcv.fraction_negative`, which is one of
    D-020's four hard gates, and moving a gate is the operator's decision plus a ledger row.
    """
    return purge if embargo is None else embargo


def _stressed_oos_gate(net: pd.Series, folds: Sequence[Any], bars_per_year: float, n_trials: int) -> dict[str, Any]:
    """D-028's gate re-derived on a stressed cost assumption, so the two numbers are the same kind.

    The gate is an out-of-sample Sharpe against a threshold; `cost_stress` reports a full-sample
    Sharpe.  A reader who wants to know whether doubling costs would have cost the strategy its
    verdict has, until now, had to subtract one from the other - which is comparing a number measured
    on 49,240 bars with a bar measured on 45,240 of them, and is how a +0.0426 margin got weighed
    against a -0.1175 effect.  Same folds, same N, stressed series.

    BASIS, because it is not the headline's: these levels are re-priced from `best_weights`, so the
    series is ONE configuration's - `best_key_oos_sharpe` (F3), not the fold-selected mixture that
    `oos_selection` and `verdict.decide` read.  The x1 cell therefore reproduces `best_key_oos_sharpe`
    exactly and NOT `oos_selection.oos_sharpe_annual`, and the two differ whenever the folds did not
    all choose the same configuration.  That is the right basis for this question - the registry ships
    a configuration, not a mixture - but it is a different number, so it is named rather than assumed.
    Re-pricing the whole grid at each stress level would make them the same number and cost three more
    full grid backtests; not bought.
    """
    oos = pd.concat([net.iloc[fold.test_slice] for fold in folds])
    selection = oos_selection_threshold(oos.to_numpy(dtype=float), n_trials=n_trials, bars_per_year=bars_per_year)
    achieved, threshold = selection.get("oos_sharpe_annual"), selection.get("threshold_annual")
    if achieved is None or threshold is None:
        return {"oos_sharpe": achieved, "threshold": threshold, "margin": None, "clears": None}
    return {
        "oos_sharpe": achieved,
        "threshold": threshold,
        "margin": achieved - threshold,
        "clears": achieved >= threshold,
    }


def _overlay_metrics(result: BacktestResult, folds: int, min_train: int, bars_per_year: float) -> dict[str, Any]:
    net = result.portfolio_net
    n = len(net)
    fold_list = walk_forward_folds(n, folds, min_train=min(min_train, max(n // 2, 2)))
    oos = net.iloc[fold_list[0].test_start :]
    return {
        "full_sharpe": sharpe(net, bars_per_year),
        "full_mdd": max_drawdown(net),
        "oos_sharpe": sharpe(oos, bars_per_year),
        "oos_mdd": max_drawdown(oos),
        "oos_return": compound(oos),
        "fold_sharpes": [sharpe(net.iloc[f.test_slice], bars_per_year) for f in fold_list],
        "turnover_units": float(result.turnover.sum()),
        "average_absolute_exposure": float(result.weights.abs().sum(axis=1).mean()),
    }


# D-018: pre-registered acceptance for running a strategy as an independent sleeve (a "small book") next to the
# main book.  Fixed before the first run and never widened after seeing results; every threshold is written into
# the report.  Passing this rule is a *portfolio* decision; it does not create a registry verdict for the sleeve.
BOOK_RULE: dict[str, float] = {
    "min_delta_oos_sharpe": 0.10,  # total book OOS Sharpe minus main-only OOS Sharpe
    "max_oos_mdd_worsening": 0.01,  # total OOS max drawdown may not be worse than main-only by more than 1pp
    "min_fold_win_rate": 0.6,  # total beats main-only in >= 3 of 5 walk-forward folds
    "max_cpcv_negative": 0.10,  # sleeve alone: share of CPCV paths with a negative Sharpe
    "min_cost_x2_sharpe": 0.5,  # sleeve alone: Sharpe with doubled costs
    "min_robustness_delta": 0.0,  # on the robustness universe the sleeve must not subtract OOS Sharpe
}


def _fold_metrics(net: pd.Series, fold_list: Sequence[Fold], bpy: float) -> dict[str, Any]:
    oos = net.iloc[fold_list[0].test_start :]
    return {
        "full_sharpe": sharpe(net, bpy),
        "full_mdd": max_drawdown(net),
        "oos_sharpe": sharpe(oos, bpy),
        "oos_return": compound(oos),
        "oos_mdd": max_drawdown(oos),
        "fold_sharpes": [sharpe(net.iloc[f.test_slice], bpy) for f in fold_list],
    }


def _combine_books(
    main: pd.DataFrame, sleeve: pd.DataFrame, params: PortfolioParams
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Sum two books (``combine_books``: the main book's caps and band on the total) plus cap-binding diagnostics."""
    total = combine_books({"main": main, "sleeve": sleeve}, params)
    columns = main.columns.union(sleeve.columns)
    b = sleeve.reindex(columns=columns)
    raw = main.reindex(columns=columns).fillna(0.0) + b.fillna(0.0)
    gross = raw.clip(-params.max_weight, params.max_weight).abs().sum(axis=1)
    active = b.fillna(0.0) != 0.0
    n_active = max(1, int(active.to_numpy().sum()))
    binding = {
        "symbol_cap_share": float(((raw.abs() > params.max_weight + 1e-12) & active).to_numpy().sum() / n_active),
        "gross_cap_share": float((gross > params.max_gross + 1e-12).mean()),
    }
    return total, binding


def _running_book_nets(
    registry_path: str,
    profile_payload: dict[str, Any],
    panel: Panel,
    membership: pd.DataFrame | None,
    cost: CostModel,
    *,
    interval: str,
    min_history: int,
    exclude_strategy: str,
) -> tuple[dict[str, pd.Series], list[str]]:
    """Each book the registry says is running, as a net-return stream on this panel.

    "在跑的书" is read off the REGISTRY rather than off `.starquant/live/state.json`, and the difference
    matters enough to say: the registry is the governed decision (a write goes through
    `governance apply` and can be rolled back), a state file is what one machine happens to hold, and a
    research artefact has to be reproducible on a machine that has never run the loop.

    A book containing the candidate itself is SKIPPED and named.  `book-tsmom-flow` re-run today would
    otherwise correlate `flow` against the running `flow_short` book, get 1.0, and refuse every
    re-validation of a sleeve already running - a self-correlation is not the crowding this limit is
    about.  Skipping it is recorded in `running_books_notes` rather than left implicit, because an
    exclusion that nobody can see is indistinguishable from a limit that does not bite.
    """
    path = Path(registry_path)
    if not path.exists():
        return {}, [f"{registry_path} does not exist: no running book to correlate against"]
    registry = load_registry(path)
    portfolio = portfolio_params(profile_payload)
    nets: dict[str, pd.Series] = {}
    notes: list[str] = []
    for name in sorted({entry.book for entry in registry.enabled}):
        entries = tuple(entry for entry in registry.enabled if entry.book == name)
        if any(entry.id == exclude_strategy for entry in entries):
            notes.append(f"{name}: skipped - the candidate `{exclude_strategy}` is a member of this book")
            continue
        try:
            model = with_feature_store(
                AlphaModel(
                    entries=entries,
                    portfolio=portfolio,
                    interval=interval,
                    ensemble_method=registry.ensemble_method,
                    min_history_bars=min_history,
                    books={name: registry.fraction(name)} if name in registry.books else {},
                )
            )
            weights, _c, _p = model.evaluate(panel, membership)
        except (FundingUnavailable, KeyError, ValueError) as exc:
            notes.append(f"{name}: not evaluable on this panel ({type(exc).__name__}: {exc})")
            continue
        nets[name] = run_backtest(panel, weights, cost).portfolio_net
    return nets, notes


def _netting(main: pd.DataFrame, sleeve: pd.DataFrame) -> dict[str, float]:
    """How much of the sleeve's exposure cancels or stacks on the main book (diagnostic)."""
    columns = main.columns.union(sleeve.columns)
    a = main.reindex(columns=columns).fillna(0.0)
    b = sleeve.reindex(columns=columns).fillna(0.0)
    active = b != 0.0
    n_active = max(1, int(active.to_numpy().sum()))
    opposing = int(((np.sign(a) == -np.sign(b)) & active & (a != 0.0)).to_numpy().sum())
    same = int(((np.sign(a) == np.sign(b)) & active).to_numpy().sum())
    cancelled = float((a.abs() + b.abs() - (a + b).abs()).to_numpy().sum())
    sleeve_gross = max(float(b.abs().to_numpy().sum()), 1e-12)
    return {
        "sleeve_symbol_bars": float(n_active),
        "opposing_main_share": opposing / n_active,
        "same_direction_share": same / n_active,
        "main_flat_share": 1.0 - (opposing + same) / n_active,
        "cancelled_gross_share": cancelled / sleeve_gross,
    }


def _standalone_block(
    strategy: str,
    params: Mapping[str, Any],
    decision_weights: pd.DataFrame,
    result: BacktestResult,
    panel: Panel,
    cost: CostModel,
    fold_list: Sequence[Fold],
    *,
    purge: int,
    embargo: int,
    cpcv_groups: int,
    prior_trials: int,
    ledger_path: Path,
) -> tuple[dict[str, Any], TrialRecord]:
    """The sleeve on its own, exactly as `research validate` would score a single configuration."""
    bpy = panel.bars_per_year
    net = result.portfolio_net
    key = param_key(dict(params))
    nets = {key: net}
    wf = walk_forward_evaluate(nets, {key: dict(params)}, list(fold_list), bpy).summary(bpy)
    cpcv = cpcv_evaluate(
        nets, cpcv_splits(len(net), n_groups=cpcv_groups, n_test_groups=2, purge=purge, embargo=embargo), bpy
    )
    full = sharpe(net, bpy)
    record = TrialRecord(
        strategy=strategy,
        param_key=key,
        sharpe_annual=full,
        bars_per_year=bpy,
        recorded_at=datetime.now(UTC).isoformat(),
        range_start=str(net.index[0]),
        range_end=str(net.index[-1]),
        symbols=len(panel.symbols),
        run_id="",
    )
    records = (
        parse_ledger(ledger_path.read_text(encoding="utf-8").splitlines(), ledger_scope(strategy))
        if ledger_path.exists()
        else []
    )
    # an exact replay of a recorded configuration on the same data is one trial, not two
    prior_records = [r for r in records if _trial_signature(r) != _trial_signature(record)]
    pooled = dsr_inputs(
        prior_records,
        {key: None if full is None else full / math.sqrt(bpy)},
        bpy,
        manual_prior_trials=prior_trials,
        range_end_granularity_days=Policy().trial_range_end_granularity_days,
    )
    values = net.to_numpy(dtype=float)
    mt = multiple_testing_report(
        values,
        values.reshape(-1, 1),
        bars_per_year=bpy,
        prior_trials=prior_trials,
        pooled_n_trials=pooled["n_trials"],
        pooled_sharpe_variance=pooled["sharpe_variance"] if pooled["pooled_sharpes"] >= 2 else None,
    )
    mt["ledger_trials"] = pooled["ledger_trials"]
    mt["replayed_trial"] = len(prior_records) != len(records)
    stress = cost_stress(
        {
            multiplier: run_backtest(
                panel,
                decision_weights,
                CostModel(cost.turnover_bps * multiplier, cost.carry_bps_per_bar * multiplier, cost.use_funding),
            ).portfolio_net
            for multiplier in (1.0, 1.5, 2.0)
        },
        bpy,
    )
    block: dict[str, Any] = {
        "params": dict(params),
        "full_sample": result.summary(),
        "walk_forward": {k: v for k, v in wf.items() if k != "chosen_params"},
        "cpcv": {k: v for k, v in cpcv.items() if k != "chosen"},
        "multiple_testing": mt,
        "cost_stress": stress,
    }
    verdict, reasons = decide(block)
    block["verdict"] = verdict
    block["reasons"] = reasons
    return block, record


def _evaluate_book(
    universe_mode: str,
    panel: Panel,
    membership: pd.DataFrame | None,
    main_entry: StrategyEntry,
    sleeve_entry: StrategyEntry,
    portfolio: PortfolioParams,
    fractions: Sequence[float],
    cost: CostModel,
    *,
    interval: str,
    min_history: int,
    folds: int,
    min_train: int,
    purge: int,
    embargo: int,
    cpcv_groups: int,
    prior_trials: int,
    ledger_path: Path,
    with_limits: bool = False,
    running_nets: Mapping[str, pd.Series] | None = None,
    running_notes: Sequence[str] = (),
    slippage_totals: Mapping[float, float] | None = None,
) -> tuple[dict[str, Any], TrialRecord]:
    """Main book alone vs main + fraction x sleeve on one universe; fractions[0] is the decision fraction.

    ``with_limits`` computes §3's three limits (`book_limits`) beside D-018's six checks.  Only the
    decision universe gets them: they answer "may this sleeve join the running book", and the
    robustness universe is a sensitivity arm of the evidence, not a second book to admit.
    """
    bpy = panel.bars_per_year
    bare = replace(portfolio, no_trade_band=0.0, no_trade_rel_band=0.0)
    main_model = with_feature_store(
        AlphaModel(entries=(main_entry,), portfolio=bare, interval=interval, min_history_bars=min_history)
    )
    sleeve_model = with_feature_store(
        AlphaModel(entries=(sleeve_entry,), portfolio=bare, interval=interval, min_history_bars=min_history)
    )
    w_main, _mc, _mp = main_model.evaluate(panel, membership)
    w_sleeve, _sc, _sp = sleeve_model.evaluate(panel, membership)

    # Each arm banded as the construction bands that book, every knob.  Until 2026-09-23 these two passed
    # neither D2 nor D3 and the combined arm D2 alone, so D-018's marginal carried a band difference.
    main_decision = banded(w_main, portfolio)
    main_result = run_backtest(panel, main_decision, cost)
    sleeve_decision = banded(w_sleeve, portfolio)
    sleeve_result = run_backtest(panel, sleeve_decision, cost)
    # P30's cap applies to the sleeve AS IT ENTERS THE BOOK, before the fraction, and deliberately not
    # to `sleeve_decision` above: that block is the signal-level evidence (D-020's verdict, its own DSR)
    # and has to stay comparable with the runs that came before this knob existed.  F5 of the
    # pre-registration is exactly this line - the standalone block must come out bit-identical.
    w_sleeve_in_book = cap_gross(w_sleeve, portfolio.sleeve_max_gross)
    totals: dict[float, tuple[BacktestResult, dict[str, float]]] = {}
    decisions: dict[float, pd.DataFrame] = {}
    for fraction in fractions:
        combined, binding = _combine_books(w_main, w_sleeve_in_book * fraction, portfolio)
        decisions[fraction] = combined
        totals[fraction] = (run_backtest(panel, combined, cost), binding)
    index = main_result.portfolio_net.index
    for total_result, _binding in totals.values():
        index = index.intersection(total_result.portfolio_net.index)
    index = index.intersection(sleeve_result.portfolio_net.index)
    n_bars = len(index)
    fold_list = walk_forward_folds(n_bars, folds, min_train=min(min_train, max(n_bars // 2, 2)), purge=purge)
    main_net = main_result.portfolio_net.reindex(index).fillna(0.0)
    sleeve_net = sleeve_result.portfolio_net.reindex(index).fillna(0.0)
    main_metrics = _fold_metrics(main_net, fold_list, bpy)
    standalone, record = _standalone_block(
        sleeve_entry.id,
        sleeve_entry.params,
        sleeve_decision,
        sleeve_result,
        panel,
        cost,
        fold_list,
        purge=purge,
        embargo=embargo,
        cpcv_groups=cpcv_groups,
        prior_trials=prior_trials,
        ledger_path=ledger_path,
    )
    oos_start = fold_list[0].test_start
    by_fraction: dict[str, dict[str, Any]] = {}
    for fraction, (total_result, binding) in totals.items():
        total_net = total_result.portfolio_net.reindex(index).fillna(0.0)
        total_metrics = _fold_metrics(total_net, fold_list, bpy)
        by_fraction[f"{fraction:.4f}"] = {
            "fraction": fraction,
            "total": {**total_metrics, "summary": total_result.summary()},
            "cap_binding": binding,
            # Q3: the OOS streams, so the block also carries the equal-risk drawdown cost.  Sliced at
            # `oos_start` rather than handed whole - the clause is about out-of-sample drawdown, and a
            # vol ratio taken over the training period would rescale by a number the verdict never sees.
            "marginal": marginal_metrics(
                total_metrics,
                main_metrics,
                total_oos=total_net.iloc[oos_start:],
                main_oos=main_net.iloc[oos_start:],
            ),
        }
    sleeve_scaled = run_backtest(panel, banded(w_sleeve_in_book * fractions[0], portfolio), cost)
    raw_gross = w_sleeve.abs().sum(axis=1)
    in_book_gross = w_sleeve_in_book.abs().sum(axis=1)
    decided = raw_gross[w_sleeve.notna().any(axis=1)]
    payload: dict[str, Any] = {
        "universe_mode": universe_mode,
        # D-018's protocol, declared: `bare` weights plus the band, no guards and no overlay.  That is
        # not the book the loop holds and it is not a defect - the rule was pre-registered on this
        # ruler and every archived book verdict was measured with it - but until now the file did not
        # say so, and an overlay report's 1.85 and a validation report's 1.59 were quoted against each
        # other for exactly that reason.
        "layers": layers_applied(band="after_bare", guards=None, exits=None),
        "symbols": panel.symbols,
        "range": {"start": str(index[0]), "end": str(index[-1]), "bars": n_bars, "oos_start": str(index[oos_start])},
        "main_only": {**main_metrics, "summary": main_result.summary()},
        "sleeve_standalone": standalone,
        "sleeve_scaled_summary": sleeve_scaled.summary(),
        # P30.  The quantity the cap acts on, reported whether or not a cap is set, because F2 asks
        # whether the cap bought anything a uniform fraction would not: the exposure-matched fraction is
        # `mean_capped / mean_raw` times this run's fraction, and it cannot be read off a Sharpe.
        "sleeve_gross": {
            "cap": portfolio.sleeve_max_gross,
            "mean_raw": float(decided.mean()),
            "mean_in_book": float(in_book_gross[decided.index].mean()),
            "p95_raw": float(decided.quantile(0.95)),
            "binding_share": float((decided > portfolio.sleeve_max_gross).mean())
            if portfolio.sleeve_max_gross
            else 0.0,
            "exposure_matched_fraction": float(fractions[0] * in_book_gross[decided.index].mean() / decided.mean()),
        },
        "correlation": {
            "full": float(main_net.corr(sleeve_net)),
            "oos": float(main_net.iloc[oos_start:].corr(sleeve_net.iloc[oos_start:])),
        },
        "netting": _netting(w_main, w_sleeve_in_book * fractions[0]),
        "by_fraction": by_fraction,
        "yearly_marginal": {
            year: {"main": main_row["return"], "total": total_row["return"], "sleeve_alone": sleeve_row["return"]}
            for (year, main_row), total_row, sleeve_row in zip(
                yearly_breakdown(main_net, bpy).items(),
                yearly_breakdown(totals[fractions[0]][0].portfolio_net.reindex(index).fillna(0.0), bpy).values(),
                yearly_breakdown(sleeve_net * fractions[0], bpy).values(),
                strict=True,
            )
        },
    }
    if with_limits:
        payload["book_limits"] = _book_limits(
            panel=panel,
            cost=cost,
            main_decision=main_decision,
            sleeve_decision=sleeve_decision,
            total_decision=decisions[fractions[0]],
            index=index,
            fold_list=fold_list,
            bpy=bpy,
            main_metrics=main_metrics,
            main_summary=payload["main_only"]["summary"],
            sleeve_summary=standalone["full_sample"],
            sleeve_net=sleeve_net,
            running_nets=running_nets or {},
            running_notes=running_notes,
            slippage_totals=slippage_totals or {},
        )
    return payload, record


def _book_limits(
    *,
    panel: Panel,
    cost: CostModel,
    main_decision: pd.DataFrame,
    sleeve_decision: pd.DataFrame,
    total_decision: pd.DataFrame,
    index: pd.Index,
    fold_list: Sequence[Fold],
    bpy: float,
    main_metrics: Mapping[str, Any],
    main_summary: Mapping[str, Any],
    sleeve_summary: Mapping[str, Any],
    sleeve_net: pd.Series,
    running_nets: Mapping[str, pd.Series],
    running_notes: Sequence[str],
    slippage_totals: Mapping[float, float],
) -> dict[str, Any]:
    """§3's three limits, off the streams this run already holds (nothing is re-fitted).

    The slippage arm re-prices weights that are already decided, exactly as `research validate`'s own
    `slippage_stress` does: the fee is a contract constant and only the half the loop measures moves.
    Nine backtests over decided weights, no model evaluation - which is why this belongs in the book
    run rather than in a separate command whose report has nothing linking it back here.  That missing
    link is the whole reason two of these three limits had never been measured for a book at all.
    """
    levels: dict[str, float | None] = {}
    by_level: dict[float, dict[str, Any]] = {}
    for level, total_bps in sorted(slippage_totals.items()):
        stressed = CostModel(total_bps, cost.carry_bps_per_bar, cost.use_funding)
        main_stressed = run_backtest(panel, main_decision, stressed).portfolio_net.reindex(index).fillna(0.0)
        total_stressed = run_backtest(panel, total_decision, stressed).portfolio_net.reindex(index).fillna(0.0)
        sleeve_stressed = run_backtest(panel, sleeve_decision, stressed).portfolio_net.reindex(index).fillna(0.0)
        main_at_level = _fold_metrics(main_stressed, fold_list, bpy)
        levels[f"slip{level:g}"] = sharpe(sleeve_stressed, bpy)
        by_level[level] = {
            **marginal_metrics(
                _fold_metrics(total_stressed, fold_list, bpy),
                main_at_level,
                total_oos=total_stressed.iloc[fold_list[0].test_start :],
                main_oos=main_stressed.iloc[fold_list[0].test_start :],
            ),
            "total_cost_bps": total_bps,
            "main_oos_sharpe": main_at_level["oos_sharpe"],
        }
    correlations = correlations_with_running(sleeve_net, running_nets)
    main_per_gross = turnover_per_gross(main_summary)
    sleeve_per_gross = turnover_per_gross(sleeve_summary)
    return {
        # `Facts.slippage_stress_pass`.  `sleeve_standalone_sharpe` is the same shape validation reports
        # have carried since 2026-09-08 (`stability.slippage_stress`), so the two artefacts can be read
        # against each other; the gate is on the marginal, for the reason in `slippage_stress_decision`.
        "slippage_stress": {
            "sleeve_standalone_sharpe": levels,
            "marginal_by_level": {f"slip{level:g}": row for level, row in sorted(by_level.items())},
            "baseline_cost_bps": cost.turnover_bps,
            **slippage_stress_decision(by_level, BOOK_RULE, level=DECISION_SLIPPAGE_BPS),
        },
        # `Facts.max_correlation_with_running`.  Null when nothing measurable was compared - which is
        # the case worth naming, because 0.0 is the PASSING value and would read as "correlates with
        # nothing" where the truth is "nothing was measured".
        "correlation_with_running": correlations,
        "max_correlation_with_running": max_correlation(correlations),
        "running_books": sorted(running_nets),
        "running_books_notes": list(running_notes),
        # `Facts.turnover_ratio_to_main`.  Both readings, one gated; see `book_limits.turnover_ratio_to_main`.
        "turnover_ratio_to_main": turnover_ratio_to_main(sleeve_summary, main_summary),
        "turnover": {
            "main_units": main_summary.get("turnover_units"),
            "sleeve_units": sleeve_summary.get("turnover_units"),
            "bars": main_summary.get("bars"),
            "main_per_gross": main_per_gross,
            "sleeve_per_gross": sleeve_per_gross,
            "per_gross_ratio": (
                None if sleeve_per_gross is None or not main_per_gross else sleeve_per_gross / main_per_gross
            ),
            "basis": "sleeve standalone (unscaled) turnover units / main book turnover units, same bars",
        },
        "main_oos_sharpe": main_metrics["oos_sharpe"],
        "rule": {
            "slippage_bps": DECISION_SLIPPAGE_BPS,
            "max_correlation_with_running": 0.5,
            "max_turnover_ratio_to_main": 3.0,
            "note": "the two limits are §3's and are ENFORCED by starquant_governance.lifecycle, not here: "
            "this report measures them so the state machine can read them off an artefact "
            "instead of being handed a literal True",
        },
    }
