"""Purged, embargoed walk-forward evaluation over a parameter grid.

Signals are causal, so each parameter set is backtested once over the whole
panel; folds then slice the resulting net-return series.  Parameter selection
uses only the training slice (purged by ``purge`` bars before the test block).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.validation.metrics import (
    DECAY_WINDOW_DAYS,
    compound,
    max_drawdown,
    newey_west_tstat,
    sharpe,
    window_sharpes,
)


@dataclass(frozen=True)
class Fold:
    train_start: int
    train_end: int  # exclusive
    test_start: int
    test_end: int  # exclusive

    @property
    def train_slice(self) -> slice:
        return slice(self.train_start, self.train_end)

    @property
    def test_slice(self) -> slice:
        return slice(self.test_start, self.test_end)


def walk_forward_folds(
    n_bars: int,
    n_folds: int,
    *,
    min_train: int,
    purge: int = 0,
    embargo: int = 0,
    expanding: bool = True,
    train_window: int | None = None,
) -> list[Fold]:
    """Split ``[min_train, n_bars)`` into ``n_folds`` contiguous test blocks.

    ``purge`` bars immediately before each test block are dropped from training
    (labels overlapping the test period).  ``embargo`` is accepted for API
    symmetry with CPCV but has no effect here: in walk-forward the training
    window always precedes the test block, so no training sample follows it.
    """
    if n_folds <= 0 or min_train <= 0 or n_bars <= min_train:
        raise ValueError("invalid fold specification")
    test_total = n_bars - min_train
    block = test_total // n_folds
    if block <= 0:
        raise ValueError("not enough bars for the requested folds")
    folds: list[Fold] = []
    for k in range(n_folds):
        test_start = min_train + k * block
        test_end = n_bars if k == n_folds - 1 else test_start + block
        train_end = max(0, test_start - purge)
        train_start = 0 if expanding or train_window is None else max(0, train_end - train_window)
        if train_end - train_start < 2:
            raise ValueError("training window collapsed; reduce purge/embargo or folds")
        folds.append(Fold(train_start, train_end, test_start, test_end))
    return folds


@dataclass
class FoldOutcome:
    fold: Fold
    chosen_params: dict[str, Any]
    train_sharpe: float | None
    test_sharpe: float | None
    test_return: float
    test_drawdown: float


@dataclass
class WalkForwardResult:
    folds: list[FoldOutcome]
    oos_returns: pd.Series
    param_keys: list[str]
    is_sharpes: dict[str, list[float | None]] = field(default_factory=dict)
    oos_sharpes: dict[str, list[float | None]] = field(default_factory=dict)
    # kept so one configuration's own OOS series can be rebuilt after the fact (F3)
    net_returns_by_params: dict[str, pd.Series] = field(default_factory=dict)

    def oos_sharpe_for(self, key: str, folds: Sequence[Fold], bars_per_year: float) -> float | None:
        """The walk-forward OOS Sharpe of ONE configuration, rather than of the fold-selected mixture.

        F3: ``best_params`` is picked by full-sample argmax and is what reaches the registry, while
        the headline OOS belongs to whatever each fold chose.  When those differ, the number that
        describes the shipped configuration is this one, and a report that prints only the headline
        invites the reader to attribute a mixture's performance to a single parameter set.
        """
        series = self.net_returns_by_params.get(key) if self.net_returns_by_params else None
        if series is None:
            return None
        parts = [series.iloc[fold.test_slice] for fold in folds]
        return sharpe(pd.concat(parts), bars_per_year) if parts else None

    def summary(self, bars_per_year: float) -> dict[str, Any]:
        test_sharpes = [f.test_sharpe for f in self.folds if f.test_sharpe is not None]
        # D-020: the OOS mean return's Newey-West t-statistic is the verdict's significance test
        significance = newey_west_tstat(self.oos_returns)
        # KILL-Q2 / F1: with one grid point - or with every fold choosing the same one - no fold had a
        # choice to make, so the "walk-forward OOS" is the tail of a single full-sample series rather
        # than an out-of-sample estimate of a selection procedure.  Every tsmom report since
        # 2026-09-04 was of that shape while the artefact said only "oos_sharpe".
        chosen = [param_key(outcome.chosen_params) for outcome in self.folds]
        consistent = len(set(chosen)) <= 1
        # The distribution the adopted decay rule compares the live period against (report 4.2 Ⅰ).  It is
        # emitted HERE, from the evidence run, rather than computed once and written beside the registry:
        # a quantile only describes the construction it was measured under, and a hand-placed number would
        # go stale silently at the next construction change - the D-026 failure, twice already.  A run too
        # short to hold a whole window reports None, not a quantile of nothing.
        # 30 DAYS, not "a month": `bars_per_year / 12` is 730 hourly bars and the live side counts 720.
        # A ten-bar difference sounds like rounding, but the two numbers are the two halves of one
        # comparison - the live window and the distribution it is judged against - and windows of
        # different lengths have different Sharpe dispersion.  Same family as the archive/REST stamp:
        # two conventions for one quantity, and the mismatch does not raise, it just biases.
        window = round(DECAY_WINDOW_DAYS * bars_per_year / 365.0)
        windows = [
            v
            for v in window_sharpes(self.oos_returns, bars_per_window=window, bars_per_year=bars_per_year)
            if v is not None
        ]
        return {
            "folds": len(self.folds),
            "oos_sharpe": sharpe(self.oos_returns, bars_per_year),
            "oos_windows": len(windows),
            "oos_window_sharpe_q10": float(np.quantile(windows, 0.10)) if windows else None,
            "oos_return": compound(self.oos_returns),
            "oos_max_drawdown": max_drawdown(self.oos_returns),
            "oos_bars": len(self.oos_returns),
            "oos_t_stat": significance["t_stat"],
            "oos_t_lags": significance["lags"],
            "fold_sharpes": [f.test_sharpe for f in self.folds],
            "fold_consistency": (float(np.mean([s > 0 for s in test_sharpes])) if test_sharpes else None),
            "chosen_params": [f.chosen_params for f in self.folds],
            "selection_consistent": consistent,
            "oos_is_full_sample_tail": consistent or len(self.param_keys) <= 1,
        }


def param_key(params: Mapping[str, Any]) -> str:
    return "|".join(f"{key}={params[key]}" for key in sorted(params))


def walk_forward_evaluate(
    net_returns_by_params: Mapping[str, pd.Series],
    params_by_key: Mapping[str, Mapping[str, Any]],
    folds: Sequence[Fold],
    bars_per_year: float,
    select: Callable[[pd.Series, float], float | None] = sharpe,
) -> WalkForwardResult:
    """Pick the best parameter set per fold on training data; concatenate its test returns."""
    keys = list(net_returns_by_params)
    if not keys:
        raise ValueError("no parameter sets supplied")
    length = len(next(iter(net_returns_by_params.values())))
    outcomes: list[FoldOutcome] = []
    oos_parts: list[pd.Series] = []
    is_table: dict[str, list[float | None]] = {key: [] for key in keys}
    oos_table: dict[str, list[float | None]] = {key: [] for key in keys}
    for fold in folds:
        if fold.test_end > length:
            raise ValueError("fold exceeds series length")
        best_key: str | None = None
        best_score = -np.inf
        for key in keys:
            series = net_returns_by_params[key]
            train_score = select(series.iloc[fold.train_slice], bars_per_year)
            test_score = select(series.iloc[fold.test_slice], bars_per_year)
            is_table[key].append(train_score)
            oos_table[key].append(test_score)
            if train_score is not None and train_score > best_score:
                best_score = train_score
                best_key = key
        chosen = best_key or keys[0]
        test_series = net_returns_by_params[chosen].iloc[fold.test_slice]
        oos_parts.append(test_series)
        outcomes.append(
            FoldOutcome(
                fold=fold,
                chosen_params=dict(params_by_key[chosen]),
                train_sharpe=None if best_key is None else float(best_score),
                test_sharpe=select(test_series, bars_per_year),
                test_return=compound(test_series),
                test_drawdown=max_drawdown(test_series),
            )
        )
    oos = pd.concat(oos_parts) if oos_parts else pd.Series(dtype=float)
    return WalkForwardResult(
        folds=outcomes,
        oos_returns=oos,
        param_keys=keys,
        is_sharpes=is_table,
        oos_sharpes=oos_table,
        net_returns_by_params=dict(net_returns_by_params),
    )
