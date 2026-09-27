"""Forward-return labels and overlap handling."""

from __future__ import annotations

import pandas as pd


def forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Label for decision bar t: close_{t+h} / close_t - 1 (available only at t+h)."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    return close.shift(-horizon) / close - 1.0


def execution_forward_returns(open_: pd.DataFrame, close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Execution-consistent label: fill at open_{t+1}, mark at close_{t+h}."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    return close.shift(-horizon) / open_.shift(-1) - 1.0


def non_overlapping(frame: pd.DataFrame | pd.Series, horizon: int, offset: int = 0) -> pd.DataFrame | pd.Series:
    """Every ``horizon``-th row so that h-bar labels do not overlap (D-011)."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    return frame.iloc[offset::horizon]
