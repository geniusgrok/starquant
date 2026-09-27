"""Funding-rate carry (new; E-024 showed the old system never used funding).

Perpetual longs pay positive funding to shorts, so high funding pushes the
book short and negative funding pushes it long.  Round-1 diagnostics showed
the *ranking* is right (cross-sectional IC t ≈ 4-5 at every horizon) while a
level-based equal-notional book lost money: a handful of extreme-funding
names (usually fresh meme listings mid-squeeze) dominate the magnitudes.
This version therefore

* sums settled funding over a longer window (default 72 bars = 9 settlements),
* scores by cross-sectional **rank** by default (``mode="rank"``), which is
  immune to outliers, and
* in ``mode="level"`` centres on the cross-sectional *median* (an outlier cannot
  flip the others' signs), winsorises at the 10th/90th percentile, then
  ``-tanh(funding / (scale * settlements))``.

Symbols with no settled funding in the window get NaN, never 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from starquant_alpha.features import apply_numpy, cross_sectional_rank, within_reference
from starquant_alpha.panel import Panel

SETTLEMENT_BARS_1H = 8


@dataclass(frozen=True)
class CarryParams:
    window_bars: int = 72
    mode: Literal["rank", "level"] = "rank"
    scale: float = 0.0001  # level mode: funding per settlement that maps to tanh(1)
    cross_sectional: bool = True
    winsor_pct: float = 0.10
    entry_threshold: float = 0.20
    min_symbols: int = 5

    def __post_init__(self) -> None:
        if self.window_bars <= 0 or self.scale <= 0:
            raise ValueError("window_bars and scale must be positive")
        if self.mode not in ("rank", "level"):
            raise ValueError("mode must be 'rank' or 'level'")
        if not 0 <= self.winsor_pct < 0.5:
            raise ValueError("winsor_pct must be in [0, 0.5)")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> CarryParams:
        return cls(**dict(params))

    @property
    def warmup_bars(self) -> int:
        return self.window_bars

    @property
    def settlements(self) -> float:
        return max(1.0, self.window_bars / SETTLEMENT_BARS_1H)


def carry_scores(
    funding: pd.DataFrame | None,
    index: pd.Index,
    columns: pd.Index,
    params: CarryParams | None = None,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """``reference``: the cross-sectional population (P1-01 / DL-Q1); ``None`` = every column."""
    p = params or CarryParams()
    if funding is None:
        return pd.DataFrame(np.nan, index=index, columns=columns)
    aligned = funding.reindex(index=index, columns=columns)
    trailing = aligned.rolling(p.window_bars, min_periods=p.window_bars).sum()
    observed = aligned.abs().rolling(p.window_bars, min_periods=p.window_bars).sum() > 0
    trailing = trailing.where(observed)
    population = within_reference(trailing, reference)
    enough = population.notna().sum(axis=1) >= p.min_symbols
    if p.mode == "rank":
        score = -cross_sectional_rank(trailing, reference)
        return score.where(observed).where(enough, other=np.nan)
    if p.cross_sectional:
        # robust centring: an outlier must not drag the cross-sectional mean and flip everyone else's sign
        trailing = trailing.sub(population.median(axis=1), axis=0)
        population = within_reference(trailing, reference)
    if p.winsor_pct > 0:
        lower = population.quantile(p.winsor_pct, axis=1)
        upper = population.quantile(1.0 - p.winsor_pct, axis=1)
        trailing = trailing.clip(lower=lower, upper=upper, axis=0)
    score = -apply_numpy(trailing / (p.scale * p.settlements), np.tanh)
    return score.where(observed).where(enough, other=np.nan)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return carry_scores(
        panel.funding, panel.close.index, panel.close.columns, CarryParams.from_mapping(params), panel.reference
    )
