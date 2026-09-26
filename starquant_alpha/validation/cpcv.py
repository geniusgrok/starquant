"""Combinatorial purged cross-validation splits (López de Prado 2018, ch. 12)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.validation.metrics import sharpe


@dataclass(frozen=True)
class Split:
    train_index: np.ndarray
    test_index: np.ndarray
    test_groups: tuple[int, ...]


def cpcv_splits(
    n_bars: int, n_groups: int = 6, n_test_groups: int = 2, purge: int = 0, embargo: int = 0
) -> list[Split]:
    """Every `n_test_groups`-of-`n_groups` combination, with `purge` bars dropped before each test
    block and `embargo` bars dropped after it.

    The two numbers block two different leaks, and unlike walk-forward, CPCV has both.  A CPCV
    training set is chosen by COMBINATION, so it contains groups that lie after the test block as
    well as before it:

        purge   - training bars BEFORE the test block, whose labels reach forward into it;
        embargo - training bars AFTER the test block, whose FEATURE LOOKBACK reaches back into it.

    Only the second one is live in this pipeline, and it is the one that was set wrong.  What gets
    split here is a realised net-return series, so there is no forward label anywhere - the audit of
    2026-09-08 said so (`docs/analysis/2026-09-08-backtest-guard-external-audit.md:309`) and
    concluded the embargo carries nothing.  That conclusion is correct for `walk_forward_folds`,
    where the training window always ends before the test block, and WRONG here: every bar of this
    series was produced by a model whose feature window looks BACK, so a training bar sitting `k`
    bars after the test block was computed from a window covering that block whenever `k < lookback`
    - and `cpcv_evaluate` picks its parameters on exactly those bars.  The returns stay causal, so
    this is not a look-ahead; it is selection contamination, and it makes a gate such as D-020's
    `fraction_negative <= 0.10` easier to pass than it should be.

    So `embargo` should be sized by the model's FEATURE LOOKBACK, never by a label horizon:
    `AlphaModel.warmup_bars` (1,442 under the registry shipped on 2026-09-13), or at the very least
    the longest lookback in it - `max(horizons)` = 720 for tsmom.

    What the callers actually pass today is `embargo = purge = 50` (`starquant_cli/research_validate_cmd.py`
    and `research_book_cmd.py`), which leaves roughly 670 of those ~720 contaminated
    bars inside the training set of every "after" group.  This boundary is therefore OPEN, on the
    record rather than by argument: see the orange entry in
    `docs/analysis/2026-09-13-full-repo-review.md`.  `--embargo` exists so the operator can close it;
    its default is still `--purge` because adopting a real embargo means a pre-registered re-run that
    charges the trials ledger, which is a decision, not a refactor.
    """
    if n_groups < 2 or not 0 < n_test_groups < n_groups or n_bars < n_groups * 2:
        raise ValueError("invalid CPCV specification")
    bounds = np.linspace(0, n_bars, n_groups + 1, dtype=int)
    groups = [(int(bounds[i]), int(bounds[i + 1])) for i in range(n_groups)]
    splits: list[Split] = []
    for chosen in combinations(range(n_groups), n_test_groups):
        test_mask = np.zeros(n_bars, dtype=bool)
        blocked = np.zeros(n_bars, dtype=bool)
        for g in chosen:
            start, end = groups[g]
            test_mask[start:end] = True
            blocked[max(0, start - purge) : start] = True
            blocked[end : min(n_bars, end + embargo)] = True
        train_mask = ~test_mask & ~blocked
        splits.append(Split(np.flatnonzero(train_mask), np.flatnonzero(test_mask), tuple(chosen)))
    return splits


def cpcv_evaluate(
    net_returns_by_params: Mapping[str, pd.Series],
    splits: Sequence[Split],
    bars_per_year: float,
) -> dict[str, Any]:
    """For each split, pick the best parameters on train and record their test Sharpe."""
    keys = list(net_returns_by_params)
    if not keys:
        raise ValueError("no parameter sets supplied")
    oos: list[float] = []
    chosen_keys: list[str] = []
    for split in splits:
        best_key, best_score = keys[0], -np.inf
        for key in keys:
            values = net_returns_by_params[key].to_numpy(dtype=float)
            score = sharpe(values[split.train_index], bars_per_year)
            if score is not None and score > best_score:
                best_key, best_score = key, score
        test_values = net_returns_by_params[best_key].to_numpy(dtype=float)[split.test_index]
        test_sharpe = sharpe(test_values, bars_per_year)
        oos.append(float("nan") if test_sharpe is None else test_sharpe)
        chosen_keys.append(best_key)
    array = np.asarray(oos, dtype=float)
    finite = array[np.isfinite(array)]
    return {
        "paths": len(splits),
        "oos_sharpe_mean": float(finite.mean()) if finite.size else None,
        "oos_sharpe_q05": float(np.quantile(finite, 0.05)) if finite.size else None,
        "oos_sharpe_min": float(finite.min()) if finite.size else None,
        "fraction_negative": float(np.mean(finite < 0)) if finite.size else None,
        "chosen": chosen_keys,
    }
