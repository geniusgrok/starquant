"""Signal-versus-construction attribution of one strategy's book (round 7, D-024).

A full-pipeline Sharpe mixes two things: the information in the signal and the
work done by portfolio construction (vol targeting, caps, band).  The same
pipeline is therefore re-run with controlled conviction inputs:

    full            the strategy's own targets (what the live loop runs)
    constant_long   +1 on every eligible symbol: construction only, no signal
    sign_only       sign(target): the direction of the signal without its magnitude
    long_only       targets clipped at zero from below (shorts flat)
    short_only      targets clipped at zero from above (longs flat)
    equal_notional  targets / N without vol targeting or caps: the signal without construction

``sharpe(full) - sharpe(constant_long)`` is what the signal adds on top of a
vol-managed long book; ``sharpe(full) - sharpe(sign_only)`` is what the score's
magnitude adds on top of its direction; ``sharpe(full) - sharpe(equal_notional)``
is what construction adds on top of the raw signal.  Pure functions; the CLI
does the I/O.  This is a diagnostic: nothing here is a selection, so nothing
here is charged to the trials ledger.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.backtest import BacktestResult, CostModel, benchmark_basket, benchmark_returns, run_backtest
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import build_weights
from starquant_alpha.validation.metrics import compound, max_drawdown, sharpe, yearly_breakdown
from starquant_alpha.validation.walk_forward import walk_forward_folds

VARIANTS: tuple[str, ...] = ("full", "constant_long", "sign_only", "long_only", "short_only", "equal_notional")


def variant_targets(targets: pd.DataFrame, eligible: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Conviction frames for every variant, aligned to ``targets`` (NaN before the first decision)."""
    started = targets.notna().any(axis=1).cummax()
    aligned_eligible = eligible.reindex(index=targets.index, columns=targets.columns).fillna(False).astype(bool)
    constant = pd.DataFrame(
        np.where(aligned_eligible.to_numpy(), 1.0, 0.0), index=targets.index, columns=targets.columns
    ).where(started)
    n_eligible = aligned_eligible.sum(axis=1).astype(float).replace(0.0, np.nan)
    return {
        "full": targets,
        "constant_long": constant,
        "sign_only": pd.DataFrame(np.sign(targets.to_numpy(dtype=float)), index=targets.index, columns=targets.columns),
        "long_only": targets.clip(lower=0.0),
        "short_only": targets.clip(upper=0.0),
        "equal_notional": targets.div(n_eligible, axis=0),
    }


def decompose_book(
    model: AlphaModel,
    panel: Panel,
    cost: CostModel,
    *,
    membership: pd.DataFrame | None = None,
    strategy: str | None = None,
    folds: int = 5,
    min_train: int = 4000,
    purge: int = 50,
) -> dict[str, Any]:
    """Backtest every variant through the model's portfolio construction and report the attribution."""
    strategy_id = strategy or model.entries[0].id
    per_strategy = model.strategy_targets(panel, membership)
    if strategy_id not in per_strategy:
        raise KeyError(f"strategy {strategy_id!r} is not in the model")
    targets = per_strategy[strategy_id]
    eligible = model.eligible(panel, membership)
    bpy = panel.bars_per_year
    convictions = variant_targets(targets, eligible)
    weights = {
        name: (frame if name == "equal_notional" else build_weights(frame, panel.close, bpy, model.portfolio))
        for name, frame in convictions.items()
    }
    results: dict[str, BacktestResult] = {name: run_backtest(panel, frame, cost) for name, frame in weights.items()}
    common: pd.Index | None = None
    for result in results.values():
        common = result.portfolio_net.index if common is None else common.intersection(result.portfolio_net.index)
    assert common is not None
    nets = {name: result.portfolio_net.reindex(common).fillna(0.0) for name, result in results.items()}
    bench = benchmark_returns(panel, "open_to_close", panel.symbols, membership).reindex(common).fillna(0.0)
    n_bars = len(common)
    fold_list = walk_forward_folds(n_bars, folds, min_train=min(min_train, max(n_bars // 2, 2)), purge=purge)
    oos_start = fold_list[0].test_start
    rows: dict[str, dict[str, Any]] = {}
    for name, net in nets.items():
        summary = results[name].summary()
        rows[name] = {
            "full_sharpe": sharpe(net, bpy),
            "net_return": compound(net),
            "max_drawdown": max_drawdown(net),
            "oos_sharpe": sharpe(net.iloc[oos_start:], bpy),
            "fold_sharpes": [sharpe(net.iloc[fold.test_slice], bpy) for fold in fold_list],
            "turnover_units": summary["turnover_units"],
            "average_absolute_exposure": summary["average_absolute_exposure"],
            "cost_share_of_gross": summary["cost_share_of_gross"],
            "correlation_with_full": _corr(net, nets["full"]),
            "correlation_with_benchmark": _corr(net, bench),
            "yearly": {year: row["return"] for year, row in yearly_breakdown(net, bpy).items()},
        }
    full = results["full"]
    long_leg = full.net.where(full.weights > 0, 0.0).sum(axis=1).reindex(common).fillna(0.0)
    short_leg = full.net.where(full.weights < 0, 0.0).sum(axis=1).reindex(common).fillna(0.0)
    active = int((full.weights != 0).to_numpy().sum())
    legs = {
        "long": {"net_return": compound(long_leg), "sharpe": sharpe(long_leg, bpy)},
        "short": {"net_return": compound(short_leg), "sharpe": sharpe(short_leg, bpy)},
        "share_of_long_symbol_bars": (float((full.weights > 0).to_numpy().sum() / active) if active else None),
    }
    full_sharpe = rows["full"]["full_sharpe"]
    return {
        "strategy": strategy_id,
        "range": {"start": str(common[0]), "end": str(common[-1]), "bars": n_bars, "oos_start": str(common[oos_start])},
        "folds": folds,
        "min_train": min_train,
        "purge": purge,
        "benchmark": {
            "full_sharpe": sharpe(bench, bpy),
            "net_return": compound(bench),
            "max_drawdown": max_drawdown(bench),
            "oos_sharpe": sharpe(bench.iloc[oos_start:], bpy),
            "basket": benchmark_basket(membership),
        },
        "variants": rows,
        "legs": legs,
        "increments": {
            "signal_over_construction": _diff(full_sharpe, rows["constant_long"]["full_sharpe"]),
            "magnitude_over_direction": _diff(full_sharpe, rows["sign_only"]["full_sharpe"]),
            "construction_over_signal": _diff(full_sharpe, rows["equal_notional"]["full_sharpe"]),
        },
    }


def _corr(a: pd.Series, b: pd.Series) -> float | None:
    if a.std() == 0 or b.std() == 0:
        return None
    return float(a.corr(b))


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b
