"""Is the live book's return the market's, or the signal's?  (D-045)

The question this answers came from the operator on 2026-09-19, and the first four answers this
repository produced to it were all different -- not because the arithmetic changed but because the
benchmark did.  Each trap below cost a wrong answer before it was found, so each one is a rule here
rather than a caller's option.

**The benchmark has to be point-in-time.**  A fixed basket -- "the symbols that have a price for the
whole window" -- silently drops every symbol that left the universe partway through.  Measured
2026-09-07..09-18: that rule dropped AKEUSDT, CYSUSDT and TUTUSDT, and AKEUSDT was *up 26.4%* over the
part of the window it was held.  The fixed basket read +3.43% where the point-in-time basket reads
+11.31%, i.e. it understated the market by 7.88pp and handed the whole difference to alpha.  A
benchmark built with hindsight about who survived is not a benchmark.

**The t has to be Newey-West.**  Hourly equity is strongly autocorrelated and OLS does not know it.
Same window: OLS put alpha at t=1.83, NW(48h) at t=0.61.  The first number is an artefact of treating
257 overlapping hours as 257 independent draws.

**Beta is not constant when the operator changes `vol_target`.**  On 2026-09-14 (`96d659ae`) it went
0.30 -> 0.60 and net exposure went 0.9x -> 2.0x.  A constant-beta regression cannot see that, so it
books the extra exposure as alpha -- which is exactly what "the alpha is concentrated in the last three
days" meant in the first pass.  `conditional` below multiplies the market return by the exposure the
loop actually carried into each bar, which is the same regression with the operator's decision taken
out of the residual.

**The signal's own state decides whether an alpha term is even meaningful.**  `contributions` takes
values in {+1, -1} (5,379 / 514 over 09-04..09-18), so the book's entire discretion is which side each
symbol is on.  From 09-16 onward every one of the 17 symbols is +1: over those bars the book IS the
constant-long comparator, and no decomposition can find signal alpha in a stretch where the signal made
no distinction.  `signal_state` reports this because a reader who does not have it will read a beta
number as though a choice had been made.

Pure functions.  The callers do the I/O (`report beta` and the daily report, both through
`beta_reading`), and nothing here writes.  This measures; it changes nothing and gates nothing --
11 days cannot settle whether the book has alpha (M-G06's window runs to 2028-03-17), and a report
that pretended otherwise would be the failure this repository keeps finding.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np

HOURS_PER_YEAR = 24 * 365
# Bandwidth for the Newey-West correction, in bars.  48 rather than a rule-of-thumb n^(1/4) (which
# gives 4 here) because the autocorrelation being corrected for is a two-day trend, not a one-bar
# echo: t falls 1.83 -> 0.61 between them and stops moving after 48 (NW(72h) reads 0.61 as well).
NW_LAGS = 48
MIN_BARS = 48  # two days; below this the regression is describing noise and says so instead
SIGNIFICANT_T = 2.0  # below this an alpha estimate is not annualised; see `_regression`
# The bandwidth cannot be a fixed 48 on every window, and the two constants above being the SAME
# NUMBER is how that stayed hidden: a window that just clears `MIN_BARS` ran a Bartlett kernel whose
# span was the entire sample.  Newey-West's asymptotics need the bandwidth to grow slower than n, and
# at lags/n near 1 the long-lag autocovariance terms are estimated off a handful of products each -
# the estimator stops correcting and starts inventing.
#
# Measured 2026-09-22 on the live series (349 usable bars), by taking the last n of it and reading the
# alpha t at four bandwidths.  The question is not which is "right" - it is where they stop agreeing:
#
#     n     48/n   t@48   t@n/4   t@n/8   t@OLS
#     48    1.00   5.30    2.52    2.19    2.45
#     80    0.60   3.23    2.17    1.85    2.19
#    140    0.34   2.76    2.71    2.90    3.14
#    192    0.25   0.08    0.08    0.09    0.12
#    349    0.14   0.34    0.39    0.34    0.44
#
# At 0.25 and below the four readings agree to within 0.05.  Above it they diverge, and `t@48` is the
# largest every time - i.e. the unclamped bandwidth is the ALPHA-CLAIMING direction, which is the one
# that has to be defended against.  The concrete near-miss: a 55-bar window read alpha t = 5.49 at
# NW(48) and 2.23 at OLS, because the correction SHRANK the standard error threefold instead of
# widening it.
#
# So the ceiling is the measured boundary, not a rule of thumb.  What it costs is stated rather than
# hidden: under about 4 x 48 = 192 bars the correction can no longer reach the two-day trend `NW_LAGS`
# was sized for, and `_regression` says so in `nw_covers_intended_horizon` instead of returning a
# number that looks like the long-window one.
MAX_LAG_SHARE = 0.25


def _design(x: Sequence[float]) -> Any:
    return np.column_stack([np.ones(len(x)), np.asarray(x, dtype=float)])


def nw_covariance(design: Any, resid: Any, lags: int) -> tuple[Any, int] | None:
    """Newey-West covariance of OLS coefficients on any design, Bartlett weights, and the bandwidth used.

    `None` when the design is degenerate (no more rows than columns, or rank-deficient).  Split out of
    `_nw_se` on 2026-09-25 so the multi-factor reading (`factor_loadings`) runs D-045's own estimator
    and its own `MAX_LAG_SHARE` clamp rather than a second copy of them; on a two-column design these
    are `_nw_se`'s operations in `_nw_se`'s order.
    """
    n, width = len(resid), design.shape[1]
    if n <= width or np.linalg.matrix_rank(design) < width:
        return None
    used = max(0, min(lags, int(n * MAX_LAG_SHARE), n - 1))
    inverse = np.linalg.inv(design.T @ design)
    scores = resid[:, None] * design
    meat = scores.T @ scores
    for lag in range(1, used + 1):
        gamma = scores[lag:].T @ scores[:-lag]
        meat = meat + (1.0 - lag / (used + 1)) * (gamma + gamma.T)
    return inverse @ meat @ inverse, used


def _nw_se(x: Sequence[float], resid: Any, lags: int) -> tuple[float, float, int]:
    """Newey-West standard errors for the intercept and slope of ``y ~ 1 + x``, Bartlett weights.

    Returns ``(se_intercept, se_slope, lags_used)``, or ``(inf, inf, 0)`` when the design is
    degenerate -- the callers turn that into a refusal rather than into a t of zero.

    `lags_used` is the third return value rather than something the caller recomputes, because it can
    differ from `lags`: `MAX_LAG_SHARE` clamps the bandwidth to a quarter of the sample, and a
    correction that silently ran at a different width than the one named in the constant is the same
    class of defect as a percentage whose numerator and denominator come from two different series.
    The Bartlett weights use the bandwidth actually in force, so the kernel stays a proper one.
    """
    found = nw_covariance(_design(x), resid, lags)
    if found is None:
        return math.inf, math.inf, 0
    covariance, used = found
    se = np.sqrt(np.diag(covariance))
    return float(se[0]), float(se[1]), used


def _compound(logs: Sequence[float]) -> float:
    return math.expm1(sum(logs))


def pit_benchmark(
    bars: Sequence[int],
    universe: Mapping[int, Sequence[str]],
    prices: Mapping[str, Mapping[int, float]],
) -> dict[str, Any]:
    """Equal-weight long basket rebuilt every bar from the universe the loop actually held.

    A symbol contributes to a bar's return only when it was in the universe at BOTH ends of that bar
    and has a price at both, so a symbol entering or leaving never shows up as a jump.  The count of
    symbols that had to be skipped for want of a price is reported, not absorbed: a basket quietly
    thinning out is the fixed-basket bug wearing a different hat.
    """
    level = [1.0]
    used: list[int] = []
    skipped = 0
    for prev, cur in pairwise(bars):
        held = set(universe.get(prev) or ()) & set(universe.get(cur) or ())
        rets = []
        for symbol in sorted(held):
            series = prices.get(symbol) or {}
            p0, p1 = series.get(prev), series.get(cur)
            if p0 is None or p1 is None or p0 <= 0:
                skipped += 1
                continue
            rets.append(p1 / p0 - 1.0)
        used.append(len(rets))
        level.append(level[-1] * (1.0 + (sum(rets) / len(rets) if rets else 0.0)))
    return {
        "level": level,
        "symbols_per_bar": (sum(used) / len(used)) if used else 0.0,
        "prices_missing": skipped,
    }


def signal_state(
    rows: Sequence[Mapping[str, Any]], strategy: str = "tsmom", bars: Sequence[int] = ()
) -> dict[str, Any]:
    """How much distinction the signal was making, over the SAME bars the decomposition used.

    `bars` is not optional in practice.  `contributions` appears on cycles older than the first one
    carrying `collateral.usdt_equity`, so reading every row puts a longer window in this table than
    in the one above it (356 vs 259 on 2026-09-19) and dilutes the share that matters.

    `all_long_bars` is the one a reader needs first.  Over those bars the book is the constant-long
    comparator by construction, so any "alpha" a regression reports for them is a statement about the
    portfolio construction or the universe, never about the signal.

    `short_positions` counts (bar, symbol) PAIRS over the whole window, not positions held now, and
    2026-09-22 showed that the distinction is not pedantic: the operator read "空头持仓数 394" as a
    standing position count and asked why it was frozen.  It was frozen because the count is
    cumulative and had simply stopped growing - the last negative signal was 2026-09-16T00:00Z, when
    the only two shorts (CYSUSDT, TUTUSDT) left the universe on a 30-day-volume re-rank rather than on
    a signal flip.  So `shorts_last_bar` is reported beside it, and the report labels the cumulative
    one for what it is.

    Neither number can say how CLOSE the signal is to a short, and nothing here should be read that
    way: the live `conviction_mode` is `sign` (H-001), so every actionable score arrives here already
    replaced by +1 or -1.  The margin lives in the raw score against `entry_threshold`, which this
    record does not carry.
    """
    values: dict[str, int] = {}
    all_long = 0
    counted = 0
    shorts = 0
    shorts_last_bar = 0
    window = set(bars)
    for row in rows:
        if window and int(row.get("bar_open_ms") or 0) not in window:
            continue
        contributions = (row.get("contributions") or {}).get(strategy) or {}
        if not contributions:
            continue
        counted += 1
        short_here = 0
        for raw in contributions.values():
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            key = f"{value:+.1f}"
            values[key] = values.get(key, 0) + 1
            if value < 0:
                short_here += 1
        shorts += short_here
        # Overwritten each iteration, so it holds the LAST counted bar's tally when the walk ends.
        # The rows arrive in order and a duplicate bar's later record is the one that stood.
        shorts_last_bar = short_here
        if short_here == 0:
            all_long += 1
    if not counted:
        return {"measured": False, "reason": "no cycle carried this strategy's contributions"}
    return {
        "measured": True,
        "bars": counted,
        "all_long_bars": all_long,
        "all_long_share": all_long / counted,
        # Cumulative over the window - (bar, symbol) pairs, not positions.  The report labels it so.
        "short_positions": shorts,
        # What is actually short right now, which is the question "空头持仓数" reads as.
        "shorts_last_bar": shorts_last_bar,
        "values": dict(sorted(values.items())),
    }


def series_from_cycles(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The series a decomposition needs, keyed by bar, from what the loop already writes.

    The equity line is `collateral.usdt_equity` -- the venue's own USDT `marginBalance` -- and not
    total equity, because A-GB01 (2026-09-15) settled that the operator reads the USDT line and
    because collateral repricing moves total equity without the book having traded.  Measured
    09-07..09-18: collateral moved +13.38 U across 259 cycles while USDT equity moved +1,026.07.

    Prices come from each cycle's own `closes`, so the benchmark is priced on the same clock the loop
    traded on.  A caller with the parquet archive can fill in bars older than `closes` (the field is
    newer than the loop); `pit_benchmark` skips any bar it still has no price for and says how many.

    Exposure is the SIGNED sum of `targets`, rescaled from total equity to the USDT line so it is in
    the same unit as the return series above.  Duplicate bars keep their last record: a restart writes
    the same bar twice and the second one is the one that traded.  `gross` is the unsigned sum on the
    same rescaling; D-045 does not read it, the multi-factor reading scales its long-short sorts by it.
    """
    keep: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        collateral = row.get("collateral") or {}
        usdt = collateral.get("usdt_equity")
        if isinstance(usdt, int | float) and float(usdt) > 0:
            keep[int(row.get("bar_open_ms") or 0)] = row
    bars = sorted(keep)
    prices: dict[str, dict[int, float]] = {}
    equity: list[float] = []
    exposure: list[float] = []
    gross: list[float] = []
    universe: dict[int, list[str]] = {}
    for bar in bars:
        row = keep[bar]
        collateral = row.get("collateral") or {}
        usdt = float(collateral["usdt_equity"])
        equity.append(usdt)
        universe[bar] = list(row.get("universe") or ())
        total = float(collateral.get("equity") or row.get("equity") or usdt)
        weights = row.get("targets") or {}
        net = sum(float(v) for v in weights.values() if isinstance(v, int | float))
        exposure.append(net * total / usdt)
        gross.append(sum(abs(float(v)) for v in weights.values() if isinstance(v, int | float)) * total / usdt)
        for symbol, price in (row.get("closes") or {}).items():
            if isinstance(price, int | float) and float(price) > 0:
                prices.setdefault(str(symbol), {})[bar] = float(price)
    return {
        "bars": bars,
        "equity": equity,
        "exposure": exposure,
        "gross": gross,
        "universe": universe,
        "prices": prices,
    }


def foreign_bars(attribution: Sequence[Mapping[str, Any]]) -> list[int]:
    """Bars whose P&L is not the book's, so the regression must not see them (D-032).

    `foreign` lives on the attribution rows, not on the cycle records -- the split matters here
    because reading it off the wrong file silently returns "none" and lets the operator's own trades
    into the strategy's series.  The 2026-09-10T04:00Z flatten was the operator (RESEARCH_LOG, §12 Q4)
    and put +268.83 U through one bar; three smaller ones follow it, +19.72 U being the largest.
    """
    out = []
    for row in attribution:
        total = ((row.get("foreign") or {}).get("total")) or 0.0
        try:
            if float(total) != 0.0:
                out.append(int(row.get("bar_open_ms") or 0))
        except (TypeError, ValueError):
            continue
    return out


def _regression(y: Sequence[float], x: Sequence[float], label: str) -> dict[str, Any]:
    design = _design(x)
    observed = np.asarray(y, dtype=float)
    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    intercept, slope = float(coefficients[0]), float(coefficients[1])
    resid = observed - design @ coefficients
    se_a, se_b, nw_lags = _nw_se(x, resid, NW_LAGS)
    # Whether the correction could reach the autocorrelation it was sized for.  `NW_LAGS` is 48
    # because the thing being corrected is a two-day trend; a window short enough to be clamped gets
    # a kernel that cannot see two days, so its standard error is answering a narrower question than
    # the constant's name claims.  Carried with the number rather than left for the reader to derive
    # from `bars`, for the same reason `attributed_drawdown_state` carries `ruler`.
    covers = nw_lags >= NW_LAGS
    ss_tot = float(((observed - observed.mean()) ** 2).sum())
    ss_res = float((resid**2).sum())
    market_part = slope * float(np.sum(x))
    total = float(observed.sum())
    return {
        "label": label,
        "beta": slope,
        "beta_t": slope / se_b if se_b else None,
        "alpha_bps_per_hour": intercept * 1e4,
        "alpha_t": intercept / se_a if se_a else None,
        # Which bandwidth actually produced `alpha_t` and `beta_t`, and whether it was the one
        # `NW_LAGS` names.  See `MAX_LAG_SHARE` for what a clamped window costs.
        "nw_lags": nw_lags,
        "nw_lags_requested": NW_LAGS,
        "nw_covers_intended_horizon": covers,
        # Annualised only when the estimate carries a signal AND the correction behind that signal
        # reached the horizon it was sized for.  Two separate refusals, and the second was added
        # 2026-09-22 after the first one alone let a 55-bar window read t = 5.49: |t| >= 2 is a
        # question about the estimate, `covers` is a question about the ruler that produced it, and
        # a ruler that could not see the autocorrelation it exists to correct does not get to clear
        # a significance bar.  11 days of noise at |t| < 2 compounds to numbers like +1766%
        # (measured 2026-09-19, t=0.73), and a reader who sees that number has been handed a
        # decision the data did not make.
        "alpha_annualised": (
            math.expm1(intercept * HOURS_PER_YEAR)
            if se_a and covers and abs(intercept / se_a) >= SIGNIFICANT_T
            else None
        ),
        "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
        "market_part": math.expm1(market_part),
        "residual_part": math.expm1(total - market_part),
    }


def beta_decomposition(
    strategy_level: Sequence[float],
    benchmark_level: Sequence[float],
    exposure: Sequence[float],
    excluded_bars: Sequence[int] = (),
    bars: Sequence[int] = (),
) -> dict[str, Any]:
    """Split the book's realised return into the market's part and what is left.

    Two regressions, deliberately reported side by side.  `constant` is the textbook one and is the
    number a reader will compare to other books.  `conditional` multiplies the market by the net
    exposure the book carried into each bar, which is the only one of the two that survives an
    operator changing `vol_target` mid-window -- and the difference between them is worth printing,
    because it is the size of the mistake the textbook one makes here.

    `exposure` is the exposure entering each bar, so it is one element shorter than the levels, or
    equal length with the last element unused.  `excluded_bars` drops bars whose P&L is not the book's
    (D-032 foreign fills: the operator's own 2026-09-10 flatten put +288.35 U through one bar).
    """
    if len(strategy_level) != len(benchmark_level):
        return {"measured": False, "reason": "strategy and benchmark levels differ in length"}
    drop = set(excluded_bars)
    rs: list[float] = []
    rm: list[float] = []
    ex: list[float] = []
    for i in range(1, len(strategy_level)):
        if bars and bars[i] in drop:
            continue
        if strategy_level[i - 1] <= 0 or benchmark_level[i - 1] <= 0:
            continue
        rs.append(math.log(strategy_level[i] / strategy_level[i - 1]))
        rm.append(math.log(benchmark_level[i] / benchmark_level[i - 1]))
        ex.append(exposure[i - 1] if i - 1 < len(exposure) else 1.0)
    if len(rs) < MIN_BARS:
        return {"measured": False, "reason": f"needs {MIN_BARS} usable bars, has {len(rs)}"}
    constant = _regression(rs, rm, "constant beta")
    conditional = _regression(rs, [e * m for e, m in zip(ex, rm, strict=True)], "exposure x market")
    return {
        "measured": True,
        "bars": len(rs),
        "excluded_bars": len(drop),
        "strategy_return": _compound(rs),
        "benchmark_return": _compound(rm),
        "exposure_mean": sum(ex) / len(ex),
        "exposure_max": max(ex),
        "constant": constant,
        "conditional": conditional,
    }


def window_prices(series: Mapping[str, Any], closes: Callable[[str], Any]) -> dict[str, dict[int, float]]:
    """Each universe symbol's price at the window's bars: the cycle's own `closes`, the archive for the rest.

    `closes(symbol)` is the parquet archive as a series indexed by bar open time.  The cycle records'
    own `closes` is newer than the loop, so the archive fills in the bars that predate it.  A symbol the
    archive cannot give is a gap, not an error: `pit_benchmark` counts every symbol-bar it skipped.
    Only the window's bars are copied out of the archive, because `pit_benchmark` looks up nothing
    else.  The CLI used to copy the whole history: the same numbers for 121 ms instead of 7 ms on
    2026-09-23 (710,252 archive rows over 20 symbols), a cost the daily report would pay every hour.

    Out of `beta_reading` since 2026-09-25, when the multi-factor reading needed the same prices: its
    market factor is this basket, so it takes this fill rather than a copy (see `beta_reading`).
    """
    bars = series["bars"]
    prices = {symbol: dict(points) for symbol, points in series["prices"].items()}
    for symbol in {s for names in series["universe"].values() for s in names}:
        try:
            archive = closes(symbol)
        except Exception:  # a missing or half-written parquet is a gap here, not a failure
            continue
        archive = archive[archive.index.isin(bars)]
        archived = prices.setdefault(symbol, {})
        for stamp, price in zip(archive.index.astype("int64"), archive.astype(float), strict=True):
            archived.setdefault(int(stamp), float(price))
    return prices


def beta_reading(
    cycles: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    closes: Callable[[str], Any],
    strategy: str = "tsmom",
) -> dict[str, Any]:
    """The whole D-045 reading from what the loop wrote: `report beta`'s page and the daily report's block.

    One function for both callers.  Until 2026-09-23 this sat inside the CLI command, so the reading
    existed only when somebody ran it by hand.  The daily report now takes it every hour, and a second
    copy of the fill (`window_prices`) is how the two would stop agreeing - the first four answers to
    this question differed because the BENCHMARK did (module docstring).

    Fewer than two bars carrying `collateral.usdt_equity` returns a refusal (`measured`, `reason`)
    in place of the four blocks: there is no return to split.
    """
    series = series_from_cycles(cycles)
    bars = series["bars"]
    if len(bars) < 2:
        return {"measured": False, "reason": "周期记录里还没有两根带 usdt_equity 的 bar，无法分解"}
    prices = window_prices(series, closes)
    benchmark = pit_benchmark(bars, series["universe"], prices)
    return {
        "window": {
            "from": datetime.fromtimestamp(bars[0] / 1000, UTC).isoformat(),
            "to": datetime.fromtimestamp(bars[-1] / 1000, UTC).isoformat(),
            "days": (bars[-1] - bars[0]) / 86_400_000,
            "cycles": len(bars),
        },
        "benchmark": {k: v for k, v in benchmark.items() if k != "level"},
        "signal": signal_state(cycles, strategy, bars),
        "decomposition": beta_decomposition(
            series["equity"], benchmark["level"], series["exposure"], excluded_bars=foreign_bars(attribution), bars=bars
        ),
    }
