"""Beta-neutral residual momentum (port of ``ResidualMomentumAlpha`` without the artifact ceremony).

beta      = rolling OLS beta of 1-bar log returns on the benchmark (BTCUSDT if present, else the equal-weight mean)
residual_h = logret_asset,h - beta * logret_bench,h     for each horizon h  (log returns are additive across horizons)
score      = tanh(mean_h residual_h / scale)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import apply_numpy, log_returns, rolling_beta
from starquant_alpha.panel import Panel


@dataclass(frozen=True)
class ResidualParams:
    horizons: tuple[int, ...] = (24, 72, 168)
    beta_window: int = 336
    scale: float = 0.05
    benchmark: str = "BTCUSDT"
    entry_threshold: float = 0.20

    def __post_init__(self) -> None:
        if not self.horizons or self.beta_window < 20 or self.scale <= 0:
            raise ValueError("invalid residual momentum parameters")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> ResidualParams:
        values = dict(params)
        if "horizons" in values:
            values["horizons"] = tuple(values["horizons"])
        return cls(**values)

    @property
    def warmup_bars(self) -> int:
        return max(max(self.horizons), self.beta_window) + 1


def residual_scores(close: pd.DataFrame, params: ResidualParams | None = None) -> pd.DataFrame:
    p = params or ResidualParams()
    one_bar = log_returns(close, 1)
    benchmark_bar = one_bar[p.benchmark] if p.benchmark in close.columns else one_bar.mean(axis=1)
    beta = rolling_beta(one_bar, benchmark_bar, p.beta_window)
    total = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    valid = pd.DataFrame(True, index=close.index, columns=close.columns)
    for horizon in p.horizons:
        asset = log_returns(close, horizon)
        bench = asset[p.benchmark] if p.benchmark in close.columns else asset.mean(axis=1)
        residual = asset - beta.mul(bench, axis=0)
        valid &= residual.notna()
        total = total + residual.fillna(0.0)
    score = apply_numpy(total / len(p.horizons) / p.scale, np.tanh)
    if p.benchmark in score.columns:
        score[p.benchmark] = np.nan  # the benchmark has no residual against itself
    return score.clip(-1.0, 1.0).where(valid)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return residual_scores(panel.close, ResidualParams.from_mapping(params))
