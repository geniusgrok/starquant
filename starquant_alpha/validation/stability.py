"""Robustness checks: time-split, parameter neighbourhood, cost and slippage stress, break-even cost multiple, regime split."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.model import FundingUnavailable
from starquant_alpha.validation.metrics import sharpe


def time_split_sharpes(net: pd.Series, n_splits: int, bars_per_year: float) -> list[float | None]:
    if n_splits <= 0:
        raise ValueError("n_splits must be positive")
    pieces = np.array_split(net.to_numpy(dtype=float), n_splits)
    return [sharpe(piece, bars_per_year) for piece in pieces]


def parameter_neighborhood(
    evaluate: Callable[[Mapping[str, Any]], float | None],
    base_params: Mapping[str, Any],
    *,
    perturb_pct: float = 0.10,
    numeric_keys: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Evaluate ±perturb_pct around every numeric parameter; report the worst relative degradation."""
    base = evaluate(base_params)
    results: dict[str, dict[str, float | None]] = {}
    candidates = numeric_keys or tuple(base_params)
    keys = tuple(
        k
        for k in candidates
        if isinstance(base_params.get(k), int | float) and not isinstance(base_params.get(k), bool)
    )
    for key in keys:
        value = base_params[key]
        neighbours: dict[str, float | None] = {}
        for label, factor in (("down", 1.0 - perturb_pct), ("up", 1.0 + perturb_pct)):
            perturbed = dict(base_params)
            candidate = value * factor
            perturbed[key] = round(candidate) if isinstance(value, int) else candidate
            if perturbed[key] == value:
                perturbed[key] = value + (1 if label == "up" else -1) if isinstance(value, int) else candidate
            try:
                neighbours[label] = evaluate(perturbed)
            except FundingUnavailable:
                raise  # the run has no funding; that is not this perturbation being unscoreable
            except ValueError:
                neighbours[label] = None
        results[key] = neighbours
    scores = [v for group in results.values() for v in group.values() if v is not None]
    worst = min(scores) if scores else None
    return {
        "base": base,
        "neighbours": results,
        "worst_neighbour": worst,
        "worst_degradation": (None if base is None or worst is None or base == 0 else (base - worst) / abs(base)),
    }


def cost_stress(net_by_multiplier: Mapping[float, pd.Series], bars_per_year: float) -> dict[str, float | None]:
    return {f"x{multiplier:g}": sharpe(series, bars_per_year) for multiplier, series in net_by_multiplier.items()}


#: How close to zero a re-priced mean must land, in multiples: |mean net| <= this x `cost_per_multiple`.
#: Four orders finer than m* is ever read, and far above what float summation leaves on 50,000 bars.
BREAK_EVEN_TOLERANCE = 1e-6


def break_even_cost_multiple(
    price: Callable[[float], pd.Series],
    priced: Mapping[float, pd.Series],
    view: Callable[[pd.Series], pd.Series] = lambda net: net,
    *,
    max_repricings: int = 6,
) -> dict[str, Any]:
    """m*: the multiple on `turnover_bps` and `carry_bps_per_bar` at which mean net return is zero.

    ``priced`` is the book's net return at multiples already priced (`validate`'s cost_stress cells),
    ``price`` re-prices the same book at any m >= 0, and ``view`` picks the bars the mean is taken
    over.  Reported, never enforced.

    Why a secant and then re-pricing, rather than solving on the cells alone.  For a FIXED executed book
    the mean is exactly affine in m: the scaled charge is m times turnover and gross, while funding and
    impact are charged on that book whatever m is, so they sit in the intercept - they move m* without
    bending the line (on the book below, holding funding rather than scaling it is worth 1.3 of m*).
    The book is not fixed.  The daily-loss pause reads equity net of the scaled costs, so a dearer run
    pauses on more bars and trades a different book.  On the shipped tsmom book (pit, to 2026-09-22)
    481 pause bars at x1 became 643 at m* = 15.46, and the line through x1 and x2 missed that zero by
    0.008 of a multiple (0.013 out of sample, m* = 14.48).  The x1.5 cell sat 5e-5 off the line and
    could not show it: the drift builds up past x2, where no cell is priced.  So the secant through the
    outermost cells is only the first guess, kept as `linear_estimate`, and the book is re-priced at
    each guess until the mean is within `BREAK_EVEN_TOLERANCE` of zero.

    The mean's zero is the Sharpe's, so on the series `cost_stress` prices, "x2 >= 0" and "m* >= 2" are
    one statement wherever the mean falls with m.  It is not the gate's headroom: D-028's threshold is
    a positive Sharpe, reached at a far lower m.  Compounded return, too, reaches zero before m*.
    """
    lo, hi = min(priced), max(priced)
    means = {m: float(view(priced[m]).mean()) for m in (lo, hi)}
    slope = (means[hi] - means[lo]) / (hi - lo)
    out: dict[str, Any] = {"multiple": None, "converged": False, "linear_estimate": None, "cost_per_multiple": -slope}
    out.update(mean_net_at_multiple=None, repricings=0)
    if not slope < 0:
        return {**out, "why": f"mean net does not fall with m: {means[lo]:.3g} at x{lo:g}, {means[hi]:.3g} at x{hi:g}"}
    multiple = out["linear_estimate"] = lo - means[lo] / slope
    if multiple < 0:
        return {**out, "why": "mean net is below zero before any cost is scaled"}
    previous = (hi, means[hi])
    for count in range(1, max_repricings + 1):
        mean = float(view(price(multiple)).mean())
        out.update(multiple=multiple, mean_net_at_multiple=mean, repricings=count)
        if abs(mean) <= BREAK_EVEN_TOLERANCE * -slope:
            out["converged"] = True
            break
        (m0, f0), previous = previous, (multiple, mean)
        if mean == f0:
            break
        multiple -= mean * (multiple - m0) / (mean - f0)
        if not multiple >= 0:
            break
    return out


def slippage_levels(*, taker_fee_bps: float, levels: Sequence[float]) -> dict[float, float]:
    """``{slippage bps: total turnover bps}`` - the fee held fixed, only the uncertain half varied.

    ``cost_stress`` scales the SUM of the two, which doubles a contract constant on its way to asking a
    question about execution.  The fee is not in doubt; the slippage assumption is the thing the live
    loop measures, so the stress is anchored on declared slippage values (``costs.yaml``'s
    ``slippage_stress_bps``, each with its provenance beside it) rather than on a multiplier.

    ``cost_stress`` is deliberately left alone: ``verdict.decide`` reads its ``x2`` cell and every
    archived report carries it, so changing what x2 means would move a gate without moving a threshold.
    """
    if any(level < 0 for level in levels):
        raise ValueError("slippage levels must be non-negative bps")
    return {level: taker_fee_bps + level for level in sorted({float(v) for v in levels})}


def slippage_stress(net_by_slippage: Mapping[float, pd.Series], bars_per_year: float) -> dict[str, float | None]:
    """Sharpe per declared slippage level, keyed by the bps it was priced at rather than by a multiplier."""
    return {f"slip{level:g}": sharpe(series, bars_per_year) for level, series in sorted(net_by_slippage.items())}


# Thirty days: the window this repository already reads volatility over outside the signals - the
# impact model's sigma (`costs.yaml: vol_window_bars: 720`, 30 days of 1h bars) and the live risk
# budget's realised vol (`live.demo.yaml: vol_window_days: 30`).  Chosen, not tuned, and deliberately
# not a CLI option: a window picked by looking at which one splits a strategy most flatteringly is a
# search, and this table is a description.
REGIME_VOL_WINDOW_DAYS = 30


def trailing_benchmark_vol(
    benchmark: pd.Series, bars_per_year: float, window_days: float = REGIME_VOL_WINDOW_DAYS
) -> pd.Series:
    """Annualised rolling volatility of ``benchmark``, shifted one bar: the value at t reads bars <= t-1.

    The shift is the causality.  A net return is indexed by the bar it was EARNED over, from a position
    decided at the previous bar's close (`run_backtest` executes ``weights.shift(1)``), so an unshifted
    label on bar t would contain that bar's own benchmark move: a crash bar would label itself high-vol
    and the split would be partly by outcome.  Shifted, the label is what was on the screen when the
    position was chosen.  ``min_periods`` is a quarter of the window, the floor `impact_costs` uses.
    """
    window = max(2, round(window_days * bars_per_year / 365.0))
    return benchmark.rolling(window, min_periods=max(2, window // 4)).std().shift(1) * math.sqrt(bars_per_year)


def regime_split_sharpes(
    net: pd.Series, benchmark_vol: pd.Series, bars_per_year: float, n_buckets: int = 3
) -> dict[str, dict[str, Any]]:
    """Sharpe by trailing benchmark-volatility tercile (low/mid/high), with each tercile's bars and vol range.

    Equal-count terciles of ``benchmark_vol`` over the bars being split.  The STATE is ex-ante when the
    vol is (`trailing_benchmark_vol`); the CUT POINTS are not - they are this sample's own terciles - so
    the table says where the sample earned, not what a gate on it would have earned.  The range is kept
    so that "high" carries a number: market volatility trends over years, a tercile's level moves with
    the window a report covers, and two reports' "high" rows are comparable only if that is visible.
    """
    aligned = pd.concat([net, benchmark_vol], axis=1, join="inner").dropna()
    if len(aligned) < n_buckets * 10:
        return {}
    returns, vol = aligned.iloc[:, 0], aligned.iloc[:, 1]
    buckets = pd.qcut(vol.rank(method="first"), n_buckets, labels=False)
    labels = ["low", "mid", "high"] if n_buckets == 3 else [str(i) for i in range(n_buckets)]
    return {
        labels[int(b)]: {
            "sharpe": sharpe(returns[buckets == b], bars_per_year),
            "bars": int((buckets == b).sum()),
            "vol_from": float(vol[buckets == b].min()),
            "vol_to": float(vol[buckets == b].max()),
        }
        for b in sorted(set(buckets))
    }
