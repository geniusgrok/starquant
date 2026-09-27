"""Cross-sectional momentum / relative strength (vectorised port of ``RelativeStrengthAlpha``, hardened).

Two measured facts shape this version (see docs/RESEARCH_LOG.md):

* 1-24h returns are *reversal* at hourly resolution, so the lookback skips the
  most recent ``skip_bars`` bars: r_h = close[t-skip] / close[t-skip-h] - 1
  (the classic "12-1" construction of Jegadeesh & Titman / Asness).
* Cross-sectional vol dispersion is enormous, so with ``risk_adjusted`` the
  excess return is divided by the symbol's trailing vol * sqrt(h) before it is
  scored; the ranking then compares t-statistics rather than raw moves.

relative = sum_h w_h * tanh(x_h / scale) / sum_h w_h,   x_h = excess (raw) or excess / (vol * sqrt(h)) (risk adjusted)
rank     = cross-sectional rank of x_H at the primary (last) horizon, in [-1, 1]
score    = clip(0.75 * relative + 0.25 * rank, -1, 1)

The benchmark is the equal-weight cross-sectional mean, so the book is
market-neutral by construction.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import (
    apply_numpy,
    cross_sectional_rank,
    realized_vol,
    realized_vol_warmup,
    within_reference,
)
from starquant_alpha.panel import Panel


@dataclass(frozen=True)
class XsmomParams:
    horizons: tuple[int, ...] = (168, 336, 720)
    horizon_weights: tuple[float, ...] = (0.2, 0.3, 0.5)
    skip_bars: int = 24
    risk_adjusted: bool = True
    score_scale: float = 0.15  # raw-return mode: excess return per unit of tanh
    z_scale: float = 1.5  # risk-adjusted mode: excess t-statistic per unit of tanh
    vol_window: int = 336
    relative_weight: float = 0.75
    rank_weight: float = 0.25
    entry_threshold: float = 0.20
    min_symbols: int = 3

    def __post_init__(self) -> None:
        if len(self.horizons) != len(self.horizon_weights) or not self.horizons:
            raise ValueError("horizons and horizon_weights must align")
        if self.score_scale <= 0 or self.z_scale <= 0 or sum(self.horizon_weights) <= 0:
            raise ValueError("scales must be positive")
        if self.skip_bars < 0 or self.vol_window < 10:
            raise ValueError("skip_bars must be >= 0 and vol_window >= 10")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> XsmomParams:
        values = dict(params)
        for key in ("horizons", "horizon_weights"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)

    @property
    def warmup_bars(self) -> int:
        """The skipped lookback, and - in risk-adjusted mode - the trailing vol that is also shifted by the skip.

        The old form compared the horizon term against ``vol_window`` itself, which happens to be
        conservative for every configuration that has been run but is not so in general: the vol needs
        only half its window, yet it is shifted by ``skip_bars``, which the comparison ignored.
        """
        base = max(self.horizons) + self.skip_bars + 1
        if not self.risk_adjusted:
            return base
        return max(base, realized_vol_warmup(self.vol_window) + self.skip_bars)


def skipped_returns(close: pd.DataFrame, horizon: int, skip: int) -> pd.DataFrame:
    """Return over ``horizon`` bars ending ``skip`` bars ago: close[t-skip] / close[t-skip-horizon] - 1."""
    return close.shift(skip) / close.shift(skip + horizon) - 1.0


def xsmom_scores(
    close: pd.DataFrame, params: XsmomParams | None = None, reference: pd.DataFrame | None = None
) -> pd.DataFrame:
    """``reference``: the cross-sectional population the excess return and rank are taken over (DL-Q1)."""
    p = params or XsmomParams()
    weight_total = float(sum(p.horizon_weights))
    relative = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    valid = pd.DataFrame(True, index=close.index, columns=close.columns)
    vol = realized_vol(close, p.vol_window, ddof=0).shift(p.skip_bars) if p.risk_adjusted else None
    signal_primary: pd.DataFrame | None = None
    for horizon, weight in zip(p.horizons, p.horizon_weights, strict=True):
        ret = skipped_returns(close, horizon, p.skip_bars)
        excess = ret.sub(within_reference(ret, reference).mean(axis=1), axis=0)
        if vol is not None:
            denominator = (vol * math.sqrt(horizon)).where(vol > 0)
            x = excess / denominator
            scale = p.z_scale
        else:
            x = excess
            scale = p.score_scale
        valid &= x.notna()
        relative = relative + apply_numpy(x / scale, np.tanh).fillna(0.0) * weight
        signal_primary = x
    assert signal_primary is not None
    relative = relative / weight_total
    rank = cross_sectional_rank(signal_primary, reference)
    enough = within_reference(close, reference).notna().sum(axis=1) >= p.min_symbols
    score = (p.relative_weight * relative + p.rank_weight * rank.fillna(0.0)) / (p.relative_weight + p.rank_weight)
    return score.clip(-1.0, 1.0).where(valid).where(enough, other=np.nan)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return xsmom_scores(panel.close, XsmomParams.from_mapping(params), panel.reference)
