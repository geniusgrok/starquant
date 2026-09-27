"""Return and forecast-quality metrics.  Pure numpy/pandas."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
import pandas as pd

CorrMethod = Literal["pearson", "kendall", "spearman"]


def compound(returns: pd.Series | np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0
    if np.any(values <= -1.0):
        return -1.0
    return float(np.prod(1.0 + values) - 1.0)


def sharpe(returns: pd.Series | np.ndarray, bars_per_year: float, ddof: int = 1) -> float | None:
    """mean / std * sqrt(bars_per_year).  The risk-free rate is 0 by convention, and that is a choice.

    The numerator is the raw return, not an excess return.  On a USDⓈ-M perpetual book the equity sits
    at the venue as margin, so the opportunity cost is real: at this book's ~30% annualised volatility a
    4% rate would be worth about 0.13 of Sharpe, which is larger than several effects this repository
    has re-run whole validations over.  It stays at 0 because every archived report and every threshold
    in `verdict.py` was measured that way and moving it would silently reprice all of them; what it must
    not be is unstated (2026-09-08 audit).  A report comparing against a funded benchmark has to
    subtract the rate itself.
    """
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2:
        return None
    std = float(np.std(values, ddof=ddof))
    if std <= 0:
        return None
    return float(np.mean(values) / std * math.sqrt(bars_per_year))


def max_drawdown(returns: pd.Series | np.ndarray) -> float:
    """Worst peak-to-trough of the compounded equity path, floored at -1.0 (a total loss).

    The floor is not cosmetic.  A bar at or below -100% takes the equity path to zero or negative,
    and ``cumprod`` keeps multiplying: a subsequent +2% then makes a negative equity MORE negative,
    and the ratio to the running peak comes back below -1.  Measured on ``[0.01, -1.5, 0.02, 0.03]``
    this returned -1.5253, i.e. "a 152% drawdown", on a path that was wiped out at the second bar.
    ``compound`` right above already answers the same series with -1.0; the two disagreeing about
    whether a book ended at zero is worse than either answer alone.

    Wiped out is where the series stops meaning anything, so it is where the reading stops too.
    This is a floor and not a truncation of the path: everything before the wipe-out is scored
    normally, and a book that never goes below -100% is bit-identical to what this returned before
    (the shipped book, at ``max_gross`` 2.0, has never come close - its worst OOS bar is two orders
    of magnitude away).  Reached only by a synthetic series or by a leverage this system refuses.
    """
    values = np.asarray(returns, dtype=float)
    values = np.where(np.isfinite(values), values, 0.0)
    equity = np.cumprod(1.0 + values)
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdown = equity / peak - 1.0
    return float(max(drawdown.min(), -1.0)) if drawdown.size else 0.0


def moments(returns: pd.Series | np.ndarray) -> tuple[float, float]:
    """(skewness, kurtosis) with kurtosis of a normal = 3.

    Lived in `multiple_testing` until 2026-09-19, where the DSR was its only caller.  Moved here
    rather than copied: `summarize_returns` needs the same two numbers, `multiple_testing` already
    imports from this module, and a second implementation of a moment is a second set of edge cases
    for `size < 4` and a zero variance.  The old address still resolves - `multiple_testing` imports
    the name, so `multiple_testing.moments` is the same object it always was.
    """
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 4:
        return 0.0, 3.0
    mean = float(values.mean())
    centered = values - mean
    variance = float(np.mean(centered**2))
    # `variance <= 0` alone is a bare float comparison, and it let a constant series through.
    # `np.full(10, 0.01)` does not centre to zero - the mean is off by one ulp, so `centered` is
    # 1.73e-18, `variance` is 3.0e-36, and skew comes out as 5.22e-54 / 5.22e-54 = exactly 1.0.
    # Measured 2026-09-19: `full(0.01)` and a 10-element list of 0.01 both returned (1.0, 1.0) while
    # `full(0.1)` and `full(1.0)` returned (0.0, 3.0), because whether the residual is zero depends
    # on the value's binary representation.  A criterion whose answer turns on that is not one.
    #
    # Harmless while the DSR was the only caller - a constant return series has no deflated Sharpe
    # worth reading either way - and not harmless now that `summarize_returns` puts these two in
    # every report, per symbol.  The tolerance is the size of the residual it has to see past:
    # centring leaves about `eps * |mean|` behind, so anything at that scale is the arithmetic
    # talking, not the distribution.  16 is headroom, not a measurement.
    spread = math.sqrt(variance) if variance > 0 else 0.0
    if spread <= 16.0 * float(np.finfo(float).eps) * max(abs(mean), 1.0):
        return 0.0, 3.0
    return float(np.mean(centered**3) / variance**1.5), float(np.mean(centered**4) / variance**2)


def sortino(returns: pd.Series | np.ndarray, bars_per_year: float) -> float | None:
    """mean / downside deviation * sqrt(bars_per_year), at the same 0 target `sharpe` uses.

    The denominator is the target semi-deviation `sqrt(mean(min(r, 0)^2))` - every bar in the mean,
    positive ones contributing zero - not the standard deviation of the losing bars alone.  The two
    disagree by `sqrt(n_losing / n)` and only the first is Sortino; the second flatters a book that
    loses rarely, which is exactly the shape this ratio is reported to expose.

    Target 0, for the reason `sharpe` states one screen up and not as a separate choice: a Sortino
    on an excess return beside a Sharpe on a raw one would be two rulers in one table.

    None when nothing was lost.  An undefined ratio is not an infinite one, and a book whose worst
    bar is zero is either a stub or a bug - `hit_rate` above returns None on the same reasoning.
    """
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2:
        return None
    downside = float(np.sqrt(np.mean(np.minimum(values, 0.0) ** 2)))
    if downside <= 0:
        return None
    return float(np.mean(values) / downside * math.sqrt(bars_per_year))


def hit_rate(returns: pd.Series | np.ndarray) -> float | None:
    values = np.asarray(returns, dtype=float)
    active = values[np.isfinite(values) & (values != 0.0)]
    if active.size == 0:
        return None
    return float(np.mean(active > 0))


def turnover_units(weights: pd.DataFrame | pd.Series) -> float:
    """Sum over time of |w_t - w_{t-1}| (per symbol summed); the legacy 'turnover units'."""
    frame = weights.to_frame() if isinstance(weights, pd.Series) else weights
    filled = frame.fillna(0.0)
    delta = filled.diff()
    delta.iloc[0] = filled.iloc[0]
    return float(delta.abs().sum().sum())


def summarize_returns(
    gross: pd.Series, net: pd.Series, weights: pd.DataFrame | pd.Series, bars_per_year: float
) -> dict[str, Any]:
    frame = weights.to_frame() if isinstance(weights, pd.Series) else weights
    exposure = frame.fillna(0.0).abs().sum(axis=1)
    return {
        "bars": int(net.shape[0]),
        "gross_return": compound(gross),
        "net_return": compound(net),
        "annualized_sharpe": sharpe(net, bars_per_year),
        "annualized_sharpe_gross": sharpe(gross, bars_per_year),
        "max_drawdown": max_drawdown(net),
        "average_absolute_exposure": float(exposure.mean()) if len(exposure) else 0.0,
        "turnover_units": turnover_units(frame),
        "nonzero_target_bars": int((exposure > 1e-12).sum()),
        "hit_rate": hit_rate(net),
        "cost_share_of_gross": _cost_share(gross, net),
        # Distribution shape, reported and never gated.  A Sharpe cannot tell a trend book from a
        # short-volatility one, and that is the single most expensive thing a headline number can
        # hide: both can print 1.6 while one of them returns a year of gains in an afternoon.  The
        # DSR has read these same two moments since it was written (`deflated_sharpe_ratio` calls
        # `moments` on the candidate's own returns), so the numbers were already being COMPUTED and
        # acted on - they just never reached the reader of the report.
        #
        # What they say about this book, measured 2026-09-19 on the BARE ensemble (tsmom, pit
        # universe, 1h, 2025-09..2026-09, no guards and no exit overlay - not the book the loop
        # holds, and the distinction is the one `layers` exists to record): Sharpe 2.35, Sortino
        # 3.51, skew +1.08, kurtosis 23.0, hit_rate 0.512, max drawdown -25.1%.  Positive skew with
        # a hit rate near half is a trend book - it loses small and often, and wins large and
        # rarely.  A short-volatility book wearing a trend book's Sharpe is the inverse and the
        # thing worth catching: high hit rate, NEGATIVE skew, Sortino below Sharpe.  Here
        # Sortino/Sharpe is 1.49 against the 1.41 a symmetric series would give, which is the same
        # fact read a second way.  None of that is inferable from a Sharpe, and until now none of it
        # was in the report.
        **dict(zip(("skew", "kurtosis"), moments(net), strict=True)),
        "sortino": sortino(net, bars_per_year),
        # The rate both ratios above are measured against, stated in the artefact rather than only in
        # `sharpe`'s docstring.  It is a constant and carries no information the code did not already
        # have - which is the point: 0 is a CHOICE here, not an omission, and the 2026-09-08 audit's
        # ruling was that what it must not be is unstated.  A docstring states it to whoever opens the
        # module; a report is what gets quoted, compared across dates and handed to someone who never
        # will.  On a USDⓈ-M perpetual book the equity sits at the venue as margin, so at this book's
        # ~30% annualised volatility a 4% rate is worth about 0.13 of Sharpe.  Changing the value
        # would silently reprice every archived report and every threshold in `verdict.py`; printing
        # it changes nothing and makes the comparison to a funded benchmark the reader's to make.
        "risk_free_rate": 0.0,
    }


def _cost_share(gross: pd.Series, net: pd.Series) -> float | None:
    gross_sum = float(gross.sum())
    if gross_sum <= 0:
        return None
    return float((gross.sum() - net.sum()) / gross_sum)


# --- forecast quality -----------------------------------------------------


def correlation(x: np.ndarray, y: np.ndarray, method: CorrMethod = "spearman") -> float | None:
    """Pearson/Spearman correlation without scipy (pandas needs scipy for rank methods)."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 3:
        return None
    a, b = a[mask], b[mask]
    if method == "spearman":
        a = pd.Series(a).rank(method="average").to_numpy(dtype=float)
        b = pd.Series(b).rank(method="average").to_numpy(dtype=float)
    elif method != "pearson":
        raise ValueError("only pearson and spearman are supported")
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def information_coefficient(
    scores: pd.DataFrame, forward_returns: pd.DataFrame, method: CorrMethod = "spearman"
) -> pd.Series:
    """Per-bar cross-sectional IC between scores and forward returns (needs >= 3 symbols per bar)."""
    aligned_scores, aligned_returns = scores.align(forward_returns, join="inner")
    score_values = aligned_scores.to_numpy(dtype=float)
    return_values = aligned_returns.to_numpy(dtype=float)
    ics: list[float] = []
    stamps: list[pd.Timestamp] = []
    for row in range(score_values.shape[0]):
        mask = np.isfinite(score_values[row]) & np.isfinite(return_values[row])
        if int(mask.sum()) < 3:
            continue
        value = correlation(score_values[row][mask], return_values[row][mask], method)
        if value is not None:
            ics.append(value)
            stamps.append(pd.Timestamp(aligned_scores.index[row]))
    return pd.Series(ics, index=pd.DatetimeIndex(stamps), dtype=float)


def time_series_ic(scores: pd.Series, forward_returns: pd.Series, method: CorrMethod = "spearman") -> float | None:
    """IC of one symbol's score with its own forward return (time-series correlation)."""
    aligned = pd.concat([scores, forward_returns], axis=1, join="inner").dropna()
    if len(aligned) < 3:
        return None
    return correlation(aligned.iloc[:, 0].to_numpy(dtype=float), aligned.iloc[:, 1].to_numpy(dtype=float), method)


def icir(ic_series: pd.Series) -> dict[str, float | None]:
    values = ic_series.dropna()
    if len(values) < 2:
        return {"ic_mean": None, "ic_std": None, "icir": None, "n": len(values)}
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    return {"ic_mean": mean, "ic_std": std, "icir": mean / std if std > 0 else None, "n": len(values)}


def sign_bucketed_ic(
    scores: pd.DataFrame,
    forward: pd.DataFrame,
    horizon: int,
    *,
    threshold: float = 0.0,
    method: CorrMethod = "spearman",
) -> dict[str, Any]:
    """KILL-042: is a negative time-series IC an artefact, or does the sign earn while the magnitude does not?

    Round 1 measured time-series IC for tsmom at -0.12 to -0.27 across horizons while the book made money,
    and no round explained it.  Round 7 supplied the candidate mechanism without testing it directly:
    ``sign_only`` reproduces the full book (Sharpe 1.68 against 1.72) and the paired per-bar return
    difference has a t of -0.05, so the magnitude carries no return information.  If that is right, then
    the rank correlation - which is dominated by magnitude - can be negative while the conditional mean
    return either side of the threshold has the sign the book trades on.

    Labels are sampled every ``horizon`` bars so overlapping windows cannot inflate anything (D-011).
    Returns the overall IC, the IC computed inside each sign bucket, and the mean forward return in each
    bucket, which is the quantity the book actually monetises.
    """
    aligned_scores, aligned_forward = scores.align(forward, join="inner")
    sampled_scores = aligned_scores.iloc[::horizon]
    sampled_forward = aligned_forward.iloc[::horizon]
    score_values = sampled_scores.to_numpy(dtype=float).ravel()
    return_values = sampled_forward.to_numpy(dtype=float).ravel()
    mask = np.isfinite(score_values) & np.isfinite(return_values)
    score_values, return_values = score_values[mask], return_values[mask]
    long_side = score_values >= threshold if threshold > 0 else score_values > 0
    short_side = score_values <= -threshold if threshold > 0 else score_values < 0

    def bucket(selector: np.ndarray) -> dict[str, Any]:
        count = int(selector.sum())
        if count < 3:
            return {"n": count, "ic": None, "mean_forward_return": None, "hit_rate": None}
        returns = return_values[selector]
        return {
            "n": count,
            "ic": correlation(score_values[selector], returns, method),
            "mean_forward_return": float(returns.mean()),
            "hit_rate": float((returns > 0).mean()),
        }

    return {
        "horizon": horizon,
        "threshold": threshold,
        "samples": int(score_values.size),
        "overall_ic": correlation(score_values, return_values, method),
        "long": bucket(long_side),
        "short": bucket(short_side),
    }


def newey_west_tstat(series: pd.Series | np.ndarray, max_lags: int | None = None) -> dict[str, float | None]:
    """t-statistic of the mean with Newey-West (Bartlett) HAC variance; the fix for overlapping labels (D-011).

    ``max_lags`` defaults to Newey & West's own bandwidth rule, ``4 * (n/100)^(2/9)``, which is about
    16 lags on five years of hourly bars.  That is the right order for the series `walk_forward`
    actually hands it - per-bar PORTFOLIO returns, ``w_t * r_{t+1}``, whose autocorrelation is close
    to zero because the weights are persistent and the returns are not - and it would be far too
    short for an overlapping-label series with a 168-bar horizon.  `research_cmd`'s IC path is that
    second case and passes ``max_lags=horizon`` explicitly; nothing else should rely on the default
    without asking which of the two shapes it has.

    Left alone rather than tightened, 2026-09-17, and the reason is D-P2 rather than statistics: this
    t no longer gates anything.  `verdict.decide` reads it only to check that it was reported at all,
    so moving the bandwidth would re-write an archived field in every report to change no decision.
    """
    values = np.asarray(series, dtype=float)
    values = values[np.isfinite(values)]
    n = values.size
    if n < 3:
        return {"mean": None, "t_stat": None, "p_value": None, "lags": None}
    lags = int(max_lags) if max_lags is not None else int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 2))
    centered = values - values.mean()
    variance = float(np.dot(centered, centered)) / n
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        variance += 2.0 * weight * float(np.dot(centered[lag:], centered[:-lag])) / n
    if variance <= 0:
        return {"mean": float(values.mean()), "t_stat": None, "p_value": None, "lags": lags}
    t_stat = float(values.mean() / math.sqrt(variance / n))
    p_value = 2.0 * (1.0 - normal_cdf(abs(t_stat)))
    return {"mean": float(values.mean()), "t_stat": t_stat, "p_value": p_value, "lags": lags}


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > 1.0 - p_low:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def yearly_breakdown(net: pd.Series, bars_per_year: float) -> dict[str, dict[str, Any]]:
    """Compound return, Sharpe and drawdown per calendar year."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(net.index, pd.DatetimeIndex):
        return out
    for year, block in net.groupby(net.index.year):
        out[str(year)] = {
            "bars": len(block),
            "return": compound(block),
            "sharpe": sharpe(block, bars_per_year),
            "max_drawdown": max_drawdown(block),
        }
    return out


# The decay rule's window, in days (report 4.2 Ⅰ, adopted 2026-09-07).  It lives here so the evidence run
# and the live report cannot drift apart: they are the two halves of one comparison, and windows of
# different lengths have different Sharpe dispersion.
DECAY_WINDOW_DAYS = 30


def _dispersed(values: np.ndarray) -> bool:
    """A spread wider than floating-point noise.  `np.std` of identical floats is not exactly zero once
    summed and divided, and the naive ratio to it came back as 3e17 - a ratio to a dispersion that is
    not there is not a measurement."""
    if values.size < 2:
        return False
    return float(np.std(values, ddof=1)) > 1e-9 * max(abs(float(np.mean(values))), 1e-12)


def window_sharpes(
    returns: Sequence[float] | pd.Series, *, bars_per_window: int, bars_per_year: float
) -> list[float | None]:
    """Sharpe of each whole NON-OVERLAPPING window, in order.  A partial tail is not a window.

    Non-overlapping is the load-bearing word.  With a daily step, "two consecutive 30-day windows" is two
    observations sharing 29 days of data - very nearly one observation - and the rule below would fire far
    more often than its design intends.  Non-overlapping makes the trigger cost 60 days of evidence.

    ``None`` for a window with no dispersion, for the reason `_has_dispersion` records: the standard
    deviation of identical floats is not exactly zero once summed and divided, and the naive ratio came
    back as 3e17.  A ratio to a dispersion that is not there is not a measurement.
    """
    values = np.asarray(list(returns), dtype=float)
    out: list[float | None] = []
    for start in range(0, values.size - bars_per_window + 1, bars_per_window):
        chunk = values[start : start + bars_per_window]
        out.append(sharpe(chunk, bars_per_year) if _dispersed(chunk) else None)
    return out
