"""Drawdown throttle: scale gross exposure down as equity falls from its high-water mark (D-015).

scalar(dd) = 1                          for dd <= start
           = floor + (1 - floor) * (stop - dd) / (stop - start)   between
           = floor                      for dd >= stop

One scalar multiplies the whole weight row, so the book's shape (and the
vol-targeting that produced it) is untouched; only its size changes.  The
live loop applies the same function to venue equity against a persisted
high-water mark.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DrawdownThrottleParams:
    start: float = 0.05
    stop: float = 0.20
    floor: float = 0.25
    enabled: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.stop or not 0 < self.floor <= 1:
            raise ValueError("need 0 <= start < stop and 0 < floor <= 1")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DrawdownThrottleParams:
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        return cls(**known)


def drawdown_scalar(drawdown: float, params: DrawdownThrottleParams) -> float:
    """``drawdown`` is a non-negative fraction below the high-water mark."""
    if not params.enabled:
        return 1.0
    dd = max(0.0, float(drawdown))
    if dd <= params.start:
        return 1.0
    if dd >= params.stop:
        return params.floor
    return params.floor + (1.0 - params.floor) * (params.stop - dd) / (params.stop - params.start)


def apply_drawdown_throttle(
    weights: pd.DataFrame, portfolio_returns: pd.Series, params: DrawdownThrottleParams
) -> tuple[pd.DataFrame, pd.Series]:
    """Scale decision-time weights by the throttle implied by the *throttled* equity path.

    ``portfolio_returns[t]`` is the unthrottled net return realised on the bar
    *after* decision ``t-1`` (i.e. aligned to decision index, shifted by one
    execution bar in the caller's frame); the throttled path is
    ``equity_t = equity_{t-1} * (1 + scalar_{t-1} * r_t)``.  Returns the scaled
    weights and the per-bar scalar series.
    """
    if not params.enabled:
        return weights.copy(), pd.Series(1.0, index=weights.index)
    rets = portfolio_returns.reindex(weights.index).fillna(0.0).to_numpy(dtype=float)
    scalars = np.ones(len(rets))
    equity = 1.0
    peak = 1.0
    scalar = 1.0
    for t in range(len(rets)):
        equity *= 1.0 + scalar * rets[t]
        peak = max(peak, equity)
        scalar = drawdown_scalar(1.0 - equity / peak, params)
        scalars[t] = scalar
    series = pd.Series(scalars, index=weights.index)
    return weights.mul(series, axis=0), series


@dataclass(frozen=True)
class BookGuardParams:
    """The two guards that bind the *book* rather than a symbol (D-004), as one shared definition.

    ``starquant_live.guards.evaluate_guards`` and the backtest replay both call the primitives below, so
    the two cannot drift.  That is the whole point of putting them here: at ``vol_target 0.15`` neither
    guard was reachable - 5.6 years of the shipped book produced a worst UTC day of -3.5% against a -5%
    pause, and gross never crossed 2.0 - so a divergence between what the backtest scored and what the
    loop would actually do was invisible.  Raising the vol target makes both reachable (measured at
    ``vol_target 0.30``: about one pause a year and 0.72% of bars capped), which is KILL-027's shape and
    the reason this had to move before the target did.
    """

    max_weight: float = 0.15
    max_gross: float = 2.0
    daily_loss_pause: float = -0.05

    def __post_init__(self) -> None:
        if self.max_weight <= 0 or self.max_gross <= 0:
            raise ValueError("max_weight and max_gross must be positive")
        if self.daily_loss_pause > 0:
            raise ValueError("daily_loss_pause is a negative return threshold")


def clamp_book(values: np.ndarray, max_weight: float, max_gross: float) -> tuple[np.ndarray, bool]:
    """Per-symbol cap then the gross cap.  Returns the row and whether the gross cap bound."""
    clamped = np.clip(np.nan_to_num(values, nan=0.0), -max_weight, max_weight)
    gross = float(np.abs(clamped).sum())
    if max_gross > 0 and gross > max_gross:
        return clamped * (max_gross / gross), True
    return clamped, False


def hold_or_reduce(target: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Only moves toward zero: same sign and smaller magnitude, or flat.  Never adds risk."""
    same_sign = (np.sign(target) == np.sign(current)) & (current != 0.0) & (target != 0.0)
    smaller = np.abs(target) < np.abs(current)
    return np.where(same_sign, np.where(smaller, target, current), 0.0)
