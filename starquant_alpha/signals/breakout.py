"""ATR-normalised Donchian breakout with volume/breadth confirmation (port of ``BreakoutAlpha``).

distance = (close - prior_high) / ATR   (or -(prior_low - close) / ATR when the downside is larger)
normalized = clip(distance / distance_scale, -1, 1)
confirmation = clip(0.65 * max(0, vol_ratio - 1) + 0.35 * max(0, 2 * breadth - 1), 0, 1)
penalty      = clip(0.65 * max(0, 1 - vol_ratio) + 0.35 * max(0, 1 - 2 * breadth), 0, 1)
score = clip(normalized * (0.5 + 0.5 * confirmation) * (1 - penalty), -1, 1)

breadth = share of universe symbols currently above their own prior channel
high (for up-moves) or below the prior low (for down-moves).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import atr, donchian, volume_ratio, within_reference
from starquant_alpha.panel import Panel


@dataclass(frozen=True)
class BreakoutParams:
    window: int = 48
    atr_window: int = 14
    distance_scale: float = 2.0
    volume_window: int = 20
    entry_threshold: float = 0.20

    def __post_init__(self) -> None:
        if self.window < 5 or self.atr_window < 2 or self.distance_scale <= 0 or self.volume_window < 2:
            raise ValueError("invalid breakout parameters")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> BreakoutParams:
        return cls(**dict(params))

    @property
    def warmup_bars(self) -> int:
        return max(self.window, self.atr_window, self.volume_window) + 2


def breakout_scores(panel: Panel, params: BreakoutParams | None = None) -> pd.DataFrame:
    p = params or BreakoutParams()
    upper, lower = donchian(panel.high, panel.low, p.window)
    average_range = atr(panel.high, panel.low, panel.close, p.atr_window)
    up = (panel.close - upper) / average_range.where(average_range > 0)
    down = (lower - panel.close) / average_range.where(average_range > 0)
    distance = up.where(up >= down, -down)
    normalized = (distance / p.distance_scale).clip(-1.0, 1.0)
    vol_ratio = volume_ratio(panel.volume, p.volume_window).fillna(1.0)
    above = (panel.close > upper).astype(float).where(upper.notna())
    below = (panel.close < lower).astype(float).where(lower.notna())
    # P1-01: breadth is a share of the reference population, not of whichever columns were loaded.
    breadth_up = within_reference(above, panel.reference).mean(axis=1)
    breadth_down = within_reference(below, panel.reference).mean(axis=1)
    # Built against ``distance``'s own labels: this frame is assembled positionally, so it must not
    # assume the intermediate carries the panel's column order (it did not - see ``true_range``).
    breadth = pd.DataFrame(
        np.where(distance >= 0, breadth_up.to_numpy()[:, None], breadth_down.to_numpy()[:, None]),
        index=distance.index,
        columns=distance.columns,
    )
    volume_confirmation = (vol_ratio - 1.0).clip(-1.0, 1.0)
    breadth_confirmation = 2.0 * breadth - 1.0
    confirmation = (0.65 * volume_confirmation.clip(lower=0.0) + 0.35 * breadth_confirmation.clip(lower=0.0)).clip(
        0.0, 1.0
    )
    penalty = (0.65 * (-volume_confirmation).clip(lower=0.0) + 0.35 * (-breadth_confirmation).clip(lower=0.0)).clip(
        0.0, 1.0
    )
    score = normalized * (0.5 + 0.5 * confirmation) * (1.0 - penalty)
    return score.clip(-1.0, 1.0).where(distance.notna())


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return breakout_scores(panel, BreakoutParams.from_mapping(params))
