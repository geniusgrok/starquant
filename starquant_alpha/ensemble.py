"""Combine per-strategy targets into one conviction frame; snapshot the latest row for live use."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class TargetWeights:
    """Latest-bar output of the alpha model (structurally matches ``starquant_live.ports.TargetSet``)."""

    as_of: pd.Timestamp
    weights: dict[str, float]
    contributions: dict[str, dict[str, float]] = field(default_factory=dict)
    combined: dict[str, float] = field(default_factory=dict)
    # Observability, not part of the trading contract (``starquant_live.ports.TargetSet`` does not
    # require it): the stage-1 sizing divisor at this bar, so a report can say what each symbol's
    # market was doing when the weight was chosen instead of re-deriving it from a separate archive.
    asset_vol: dict[str, float] = field(default_factory=dict)
    # Observability, same standing as `asset_vol`: each BOOK's own weights at this bar, before
    # `combine_books` sums them.  The probe stop is calibrated against a mark-to-market P&L and reads
    # a realised-income series instead (2026-09-12: 30-day sigma 0.137% against the 2.34% its own
    # evidence is in), and a sleeve's mark-to-market P&L cannot be computed at all without these -
    # `contributions` is per STRATEGY and pre-sizing, and `weights` is already the sum.
    book_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    # Observability, same standing as the two above, and the two quantities the construction could not
    # state about ITSELF.  `portfolio_vol` is the ex-ante annualised volatility of the weights as they
    # leave the model - after the caps and after the sleeves are summed - which is the only reading
    # that answers whether the book the loop holds is at the vol target it declares: stage 2 targets
    # the vol of stage 1, `combine_books` sums sleeves without re-targeting (a 1/3 sleeve took the
    # 2026-09-07 book from 32.24% to 35.66%), and `max_weight` then takes some of it back off.
    # `clipped_risk_share` is how much the per-symbol cap removed on this bar (GAP-AM02).
    # `None` means "this model did not compute it", which is not the same fact as 0.0.
    portfolio_vol: float | None = None
    clipped_risk_share: float | None = None


def combine_targets(
    targets_by_strategy: Mapping[str, pd.DataFrame],
    strategy_weights: Mapping[str, float],
    *,
    method: str = "mean",
    zscore_window: int = 500,
) -> pd.DataFrame:
    """Weighted mean of per-strategy targets; strategies without a value at a bar are excluded from that bar."""
    if not targets_by_strategy:
        raise ValueError("no strategy targets to combine")
    if method not in {"mean", "rolling_zscore"}:
        raise ValueError(f"unknown ensemble method {method!r}")
    numerator: pd.DataFrame | None = None
    denominator: pd.DataFrame | None = None
    for strategy, frame in targets_by_strategy.items():
        weight = float(strategy_weights.get(strategy, 1.0))
        if weight <= 0:
            continue
        values = frame
        if method == "rolling_zscore":
            rolling = frame.rolling(zscore_window, min_periods=max(20, zscore_window // 5))
            std = rolling.std(ddof=0)
            values = ((frame - rolling.mean()) / std.where(std > 0)).clip(-3.0, 3.0) / 3.0
        present = values.notna().astype(float) * weight
        contribution = values.fillna(0.0) * weight
        numerator = contribution if numerator is None else numerator.add(contribution, fill_value=0.0)
        denominator = present if denominator is None else denominator.add(present, fill_value=0.0)
    if numerator is None or denominator is None:
        raise ValueError("all strategy weights are zero")
    return (numerator / denominator.where(denominator > 0)).clip(-1.0, 1.0)


def snapshot(
    weights: pd.DataFrame,
    combined: pd.DataFrame,
    targets_by_strategy: Mapping[str, pd.DataFrame],
    asset_vol: pd.Series | None = None,
    book_weights: Mapping[str, pd.DataFrame] | None = None,
    portfolio_vol: float | None = None,
    clipped_risk_share: float | None = None,
) -> TargetWeights:
    """Latest row of the model outputs with NaN treated as flat."""
    as_of = pd.Timestamp(weights.index[-1])
    last_weights = weights.iloc[-1].fillna(0.0)
    return TargetWeights(
        as_of=as_of,
        weights={str(symbol): float(value) for symbol, value in last_weights.items()},
        contributions={
            strategy: {str(symbol): float(value) for symbol, value in frame.iloc[-1].fillna(0.0).items()}
            for strategy, frame in targets_by_strategy.items()
        },
        combined={str(symbol): float(value) for symbol, value in combined.iloc[-1].fillna(0.0).items()},
        asset_vol={}
        if asset_vol is None
        else {str(symbol): float(value) for symbol, value in asset_vol.dropna().items()},
        book_weights={}
        if book_weights is None
        else {
            str(book): {str(symbol): float(value) for symbol, value in frame.iloc[-1].fillna(0.0).items()}
            for book, frame in book_weights.items()
        },
        portfolio_vol=portfolio_vol,
        clipped_risk_share=clipped_risk_share,
    )
