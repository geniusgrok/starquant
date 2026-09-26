"""Vectorised feature primitives on wide frames (time x symbol).  All functions are causal."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd


def apply_numpy(frame: pd.DataFrame, function: Callable[[np.ndarray], np.ndarray]) -> pd.DataFrame:
    """Apply an elementwise numpy function and keep the frame's index/columns."""
    return pd.DataFrame(function(frame.to_numpy(dtype=float)), index=frame.index, columns=frame.columns)


def returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Simple return over ``horizon`` bars: close_t / close_{t-h} - 1."""
    return close / close.shift(horizon) - 1.0


def log_returns(close: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    return apply_numpy(close / close.shift(horizon), np.log)


def _realized_vol_min_periods(window: int) -> int:
    return max(2, window // 2)


def realized_vol(close: pd.DataFrame, window: int | None = 48, ddof: int = 0) -> pd.DataFrame:
    """Std of 1-bar simple returns; ``window=None`` uses an expanding window (legacy TrendAlpha convention)."""
    simple = close.pct_change()
    if window is None:
        return simple.expanding().std(ddof=ddof)
    return simple.rolling(window, min_periods=_realized_vol_min_periods(window)).std(ddof=ddof)


def realized_vol_warmup(window: int | None) -> int:
    """Close bars before ``realized_vol`` is non-NaN: it rolls over *returns*, so one bar more than its min_periods.

    A signal that divides by this vol is NaN until it resolves, so this belongs in that signal's declared
    warmup.  ``TsmomParams.warmup_bars`` used to report only ``max(horizons) + 1`` and understated the
    default configuration by 50 bars; the live request window is sized from that number (D-022).
    """
    return 2 if window is None else _realized_vol_min_periods(window) + 1


def ewm_vol(close: pd.DataFrame, halflife: int = 24) -> pd.DataFrame:
    simple = close.pct_change()
    return simple.pow(2).ewm(halflife=halflife, min_periods=halflife).mean().pow(0.5)


def annualize_vol(vol: pd.DataFrame, bars_per_year: float) -> pd.DataFrame:
    return vol * math.sqrt(bars_per_year)


# The anchor every re-fit cadence is measured from.  Absolute on purpose: see `refit_boundaries`.
REFIT_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def refit_boundaries(index: pd.DatetimeIndex, refit_bars: int, min_bars: int = 0) -> list[int]:
    """Positions at which a periodic re-fit fires, anchored on the UNIX epoch and NOT on the panel.

    `range(start, n, refit_bars)` reads the cadence off the panel's first row, so the same calendar
    bar falls on a re-fit boundary in one window and inside a block in another.  That is D-033's shape
    exactly - "the live recursion is rebuilt on a request window that slides one bar per cycle, so the
    latch point is an artefact of where the window starts" - and it is worse live than in research:
    the loop asks for a rolling 1,442-bar window every hour, so a positional cadence re-fits on a
    different calendar hour every cycle, forever.

    Anchoring on 1970-01-01 UTC instead makes the boundary set a property of the CALENDAR, so
    `f(panel)` and `f(panel.slice(start=...))` agree bar for bar wherever both have the inputs (the
    slice-invariance test in `tests/alpha/test_refit_boundaries_are_a_calendar_not_an_offset.py`).
    Any absolute anchor would do; the epoch is the one nobody has to look up.

    `min_bars` is the panel-side floor - how many rows must exist before the first fit - and it is a
    FLOOR on the boundary, never a new origin for the cadence.  Per-symbol sufficiency ("has this
    symbol observed enough bars?") is a different question and stays where it was, with the caller.

    The bar width is measured as the MODAL gap rather than taken from the first pair: a panel index is
    the union of every symbol's bar times, so one venue outage widens a gap and one stray sub-interval
    archive row narrows one, and neither should be allowed to redefine the grid.  An index that cannot
    name a width - fewer than two rows, or no positive gap at all - falls back to the positional
    cadence, because a calendar anchor with no calendar is not more correct, only less predictable.
    """
    n_bars = len(index)
    start, every = max(int(min_bars), 0), max(int(refit_bars), 1)
    if start >= n_bars:
        return []
    stamps = pd.DatetimeIndex(index)
    if stamps.tz is None:
        stamps = stamps.tz_localize("UTC")
    gaps = pd.Series(stamps).diff().dropna()
    gaps = gaps[gaps > pd.Timedelta(0)]
    if gaps.empty:
        return list(range(start, n_bars, every))
    period = pd.Timedelta(gaps.mode().iloc[0]) * every
    aligned = np.asarray((stamps - REFIT_EPOCH) % period == pd.Timedelta(0))
    return [int(position) for position in np.flatnonzero(aligned) if position >= start]


# GARCH(1,1) is fitted on a two-parameter grid rather than by a general optimiser, because the third
# parameter is pinned by VARIANCE TARGETING: omega = sigma_bar^2 * (1 - alpha - beta), where sigma_bar^2
# is the trailing-window mean of r^2.  That is the standard identification for a long-horizon fit and it
# removes the one direction in which Gaussian QMLE is badly scaled.  What is left is a persistence
# (alpha + beta) and the share of it that is news (alpha / (alpha + beta)); the grid below spans the range
# reported for high-frequency crypto - EWMA's RiskMetrics point sits at persistence 1.0, news share 0.06,
# i.e. just off the top-left of this grid, so an estimated GARCH that collapses onto EWMA will show up as
# the fit sitting at the boundary rather than as an invisible tie.
GARCH_PERSISTENCE = (0.90, 0.95, 0.98, 0.995)
GARCH_NEWS_SHARE = (0.02, 0.05, 0.10, 0.20)


def _garch_loglik(
    r2: np.ndarray, omega: np.ndarray, alpha: np.ndarray, beta: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian QMLE log-likelihood of each parameter row, and the conditional variance it ends on.

    Accumulated inside the loop rather than returned as a path: the fitting grid is
    (n_grid, n_symbols) and materialising a variance path for it over five years of hourly bars is
    1.3 GB, which is the whole reason this is a hand-rolled filter instead of a library call.

    The final ``h`` costs nothing here and is what makes the caller's state window-determined: it is
    the forecast for the boundary bar under the very parameters the likelihood just scored, filtered
    from the unconditional level across the whole fitting window.
    """
    h = np.broadcast_to(omega / np.maximum(1.0 - alpha - beta, 1e-9), omega.shape).astype(float).copy()
    total = np.zeros(h.shape)
    for row in r2:
        seen = ~np.isnan(row)
        shock = np.where(seen, row, 0.0)
        total += np.where(seen, -0.5 * (np.log(h) + shock / h), 0.0)
        h = np.where(seen, omega + alpha * shock + beta * h, h)
    return total, h


def garch_forecast_vol(
    close: pd.DataFrame,
    *,
    fit_bars: int = 8760,
    refit_bars: int = 720,
    min_obs: int = 720,
) -> pd.DataFrame:
    """One-step-ahead GARCH(1,1) volatility: the value at bar ``t`` forecasts bar ``t+1``.

    This is deliberately NOT the same quantity as ``ewm_vol``.  ``ewm_vol`` reports a level *at* t
    (an EWMA of squared returns through t); this reports the conditional standard deviation *of t+1*,
    formed at t.  Both are known at t, so both are causal, and the difference is the entire point:
    ``backtest.run_backtest`` executes the weight decided at t on bar t+1, so the divisor's job is to
    forecast the bar that will be traded, not to describe the bar that just closed.

    Causality, stated because it is the part a reader has to trust: parameters are re-fitted every
    ``refit_bars`` on the trailing ``fit_bars``, and a fit at boundary b sees only bars strictly before
    b.  The filter recursion is causal by construction.  Bars before the first boundary are NaN rather
    than filtered with block 0's parameters - using them there would be a fit reading its own sample,
    and it would be invisible because those bars are all inside every walk-forward training window.

    SLICE INVARIANCE, which is the other half of "causal" and used to be missing.  Two things used to
    make a bar's forecast depend on where the panel happened to START rather than on the calendar:
    the boundaries were ``range(max(refit_bars, min_obs), n, refit_bars)`` counted off row 0, and the
    filter state ``h`` was carried across a re-fit, so it was a function of every bar since the symbol
    first qualified.  Both are now window-determined - `refit_boundaries` anchors the cadence on the
    epoch, and ``h`` at a boundary is the state `_garch_loglik` ended the FITTING WINDOW on, under the
    parameters that window just chose.  ``f(panel)`` and ``f(panel.slice(...))`` therefore agree
    exactly on every bar whose block's fitting window both frames carry.  Nothing shipped moves:
    ``vol_model`` defaults to ``ewma`` and #35 is REFUTED.  What this buys is that re-opening it will
    not hand the live loop - which re-requests a window that slides one bar per cycle - a different
    re-fit hour every hour (D-033).

    Carrying ``h`` across a re-fit was also propagating a state through a parameter CHANGE: the level
    handed to the new block had been produced by the old block's alpha/beta.  Re-deriving it from the
    fitting window is both the slice-invariant answer and the internally consistent one.

    A symbol with fewer than ``min_obs`` observed returns in the trailing window gets NaN for that
    block, and its filter restarts at the unconditional variance when it next qualifies.  ``min_obs``
    defaults to 720 to match ``AlphaModel.min_history_bars``: a symbol this refuses to size is a symbol
    the model already refuses to trade, so the option does not silently change the traded universe.
    It is also the floor on the first boundary - a fit needs that many rows to exist at all - where the
    positional cadence used ``max(refit_bars, min_obs)``, a number the cadence's origin made necessary
    and the calendar anchor does not.
    """
    simple = close.pct_change()
    r2 = simple.pow(2).to_numpy(dtype=float)
    n_bars, n_symbols = r2.shape
    persistence = np.array([p for p in GARCH_PERSISTENCE for _ in GARCH_NEWS_SHARE], dtype=float)[:, None]
    share = np.array([s for _ in GARCH_PERSISTENCE for s in GARCH_NEWS_SHARE], dtype=float)[:, None]
    alpha_grid, beta_grid = persistence * share, persistence * (1.0 - share)
    boundaries = refit_boundaries(pd.DatetimeIndex(close.index), refit_bars, min_obs)
    out = np.full((n_bars, n_symbols), np.nan)
    if not boundaries:
        return pd.DataFrame(out, index=close.index, columns=close.columns)
    columns = np.arange(n_symbols)
    for position, boundary in enumerate(boundaries):
        window = r2[max(0, boundary - fit_bars) : boundary]
        present = ~np.isnan(window)
        observed = present.sum(axis=0)
        # Hand-rolled rather than `np.nanmean`, which warns on an all-NaN column - and a symbol that has
        # not listed yet is exactly that column, on most bars, for most of this panel.
        target = np.where(observed > 0, np.where(present, window, 0.0).sum(axis=0) / np.maximum(observed, 1), 1.0)
        qualified = (observed >= min_obs) & np.isfinite(target) & (target > 0)
        # A symbol whose window is entirely flat has target 0, which makes omega 0 and log(h) -inf; it is
        # already disqualified, but the likelihood is evaluated for every column at once, so it has to be
        # given a finite placeholder rather than left to poison a warning-free run.  Real on this panel:
        # a handful of symbol-windows print no price change at all.
        safe = np.where(qualified, target, 1.0)
        loglik, state = _garch_loglik(window, safe * (1.0 - alpha_grid - beta_grid), alpha_grid, beta_grid)
        best = np.argmax(loglik, axis=0)
        alpha, beta = alpha_grid[best, 0], beta_grid[best, 0]
        omega = np.where(qualified, target * (1.0 - alpha - beta), np.nan)
        # The state the winning row ended the FITTING WINDOW on, not the one carried out of the previous
        # block: that carry was what made a bar's forecast depend on where the panel started, and it also
        # fed a level built under the previous block's alpha/beta into this block's recursion.
        h = np.where(qualified, state[best, columns], np.nan)
        end = boundaries[position + 1] if position + 1 < len(boundaries) else n_bars
        for t in range(boundary, end):
            row = r2[t]
            seen = ~np.isnan(row)
            h = np.where(seen, omega + alpha * np.where(seen, row, 0.0) + beta * h, h)
            out[t] = h
    return pd.DataFrame(np.sqrt(out), index=close.index, columns=close.columns)


def true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Max of (high-low, |high-prev close|, |low-prev close|) per symbol, in the input's column order.

    The ``groupby`` returns its groups sorted, so without the reindex the output columns come
    back alphabetically - which is a different order from the panel whenever a name like
    ``S10USDT`` sorts before ``S1USDT``.  Arithmetic realigns by label and hides it, but any
    caller that rebuilds a frame positionally (``np.where`` + ``columns=panel.close.columns``,
    as ``breakout`` did) then attaches each value to the wrong symbol.
    """
    previous_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
        keys=["hl", "hc", "lc"],
    )
    return ranges.T.groupby(level=1).max().T.reindex(columns=high.columns)


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    return true_range(high, low, close).rolling(window, min_periods=window).mean()


def donchian(high: pd.DataFrame, low: pd.DataFrame, window: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Highest high / lowest low of the *previous* ``window`` bars (excludes the current bar)."""
    upper = high.shift(1).rolling(window, min_periods=window).max()
    lower = low.shift(1).rolling(window, min_periods=window).min()
    return upper, lower


def zscore(frame: pd.DataFrame, window: int, ddof: int = 0) -> pd.DataFrame:
    rolling = frame.rolling(window, min_periods=window)
    std = rolling.std(ddof=ddof)
    return (frame - rolling.mean()) / std.where(std > 0)


def robust_zscore(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    """(x - median) / (1.4826 * MAD) over a rolling window."""
    rolling = frame.rolling(window, min_periods=window)
    median = rolling.median()
    mad = (frame - median).abs().rolling(window, min_periods=window).median() * 1.4826
    return (frame - median) / mad.where(mad > 0)


def robust_zscore_warmup(window: int) -> int:
    """Bars before ``robust_zscore`` is non-NaN: the MAD rolls over a deviation that is itself rolling."""
    return 2 * window - 1


def within_reference(frame: pd.DataFrame, reference: pd.DataFrame | None) -> pd.DataFrame:
    """``frame`` with everything outside the cross-sectional population blanked (P1-01 / DL-Q1).

    Only the *statistic* is restricted: callers pass the whole frame, compute the rank,
    mean or share over this masked view, and keep their own rows.  Masking the panel
    instead would truncate the time series a rolling window reads.
    """
    if reference is None:
        return frame
    mask = reference.reindex(index=frame.index, columns=frame.columns).fillna(False).astype(bool)
    return frame.where(mask)


def cross_sectional_rank(frame: pd.DataFrame, reference: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rank across the reference population per bar, mapped to [-1, 1]; NaN stays NaN.

    Ranking over "whatever columns the caller loaded" is P1-01: with n=15 a
    ``rank >= 0.7`` cut always marks three names (20%), with n>=100 it marks 15%.
    """
    population = within_reference(frame, reference)
    ranks = population.rank(axis=1, method="average")
    count = population.notna().sum(axis=1)
    scaled = (ranks.sub(1.0, axis=0)).div((count - 1.0).where(count > 1), axis=0)
    return scaled * 2.0 - 1.0


def cross_sectional_zscore(frame: pd.DataFrame, reference: pd.DataFrame | None = None) -> pd.DataFrame:
    population = within_reference(frame, reference)
    mean = population.mean(axis=1)
    std = population.std(axis=1, ddof=0)
    return population.sub(mean, axis=0).div(std.where(std > 0), axis=0)


def demean_cross_section(frame: pd.DataFrame, reference: pd.DataFrame | None = None) -> pd.DataFrame:
    population = within_reference(frame, reference)
    return population.sub(population.mean(axis=1), axis=0)


def rolling_beta(asset_returns: pd.DataFrame, benchmark_returns: pd.Series, window: int) -> pd.DataFrame:
    """OLS beta of each column on the benchmark over a rolling window."""
    bench = benchmark_returns.reindex(asset_returns.index)
    cov = asset_returns.rolling(window, min_periods=window).cov(bench)
    var = bench.rolling(window, min_periods=window).var()
    return cov.div(var.where(var > 0), axis=0)


def residual_returns(asset_returns: pd.DataFrame, benchmark_returns: pd.Series, beta: pd.DataFrame) -> pd.DataFrame:
    return asset_returns - beta.mul(benchmark_returns.reindex(asset_returns.index), axis=0)


def volume_ratio(volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Current bar volume relative to the trailing mean of the previous ``window`` bars."""
    baseline = volume.shift(1).rolling(window, min_periods=window).mean()
    return volume / baseline.where(baseline > 0)


def taker_buy_ratio(taker_buy_quote: pd.DataFrame, quote_volume: pd.DataFrame, window: int = 1) -> pd.DataFrame:
    """Share of taker-buy quote volume, smoothed over ``window`` bars; 0.5 is balanced."""
    buys = taker_buy_quote.rolling(window, min_periods=window).sum()
    total = quote_volume.rolling(window, min_periods=window).sum()
    return buys / total.where(total > 0)


def funding_per_bar_to_8h(funding: pd.DataFrame, window_bars: int) -> pd.DataFrame:
    """Sum of settled funding over a trailing window (fraction), e.g. 24 bars of 1h = 3 settlements."""
    return funding.rolling(window_bars, min_periods=1).sum()


def clip_unit(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.clip(-1.0, 1.0)
