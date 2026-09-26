"""What the live book loaded on besides the market: BTC, size, low volatility, funding (#6.4 / #6.9).

D-045 (`benchmark.py`) asks one question with one regressor - how much of the book's return was the
market's - and on 2026-09-19 its answer was all of it (RESEARCH_LOG, "F4 的结构命题第一次有了测量").
Checklist items 6.4 and 6.9 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`
asked the next question and found nobody computing it.  This module reads it under D-045's four
rules rather than beside them:

1. **Point in time.**  Every factor is built over the universe the loop held at that bar (the cycle
   record's `universe`), never over a panel's symbols.  A point-in-time panel carries every name that
   was EVER a member, and the names chosen later carried an equal-weight Sharpe of +2.32 over the bars
   before they were chosen (RESEARCH_LOG 2026-09-23, the GAP-SF02 section's `bb1b9262` note).  A sort
   key at bar t reads only klines that closed by t's close and funding settled before it, and the
   return it is paid is t -> t+1.  The sort is taken over bar t's universe alone: a sort that also
   asked who was still a member at t+1 would rank with a piece of t+1.
2. **Newey-West**, through `benchmark.nw_covariance`: D-045's estimator and its bandwidth clamp.
3. **Exposure-conditioned.**  Each factor is multiplied by the exposure the loop carried into the bar:
   net for the market and BTC, as D-045 does, gross for the three long-short sorts.  That is a
   simplification, stated rather than hidden.  One number per bar stands in for how the weights sat
   across the terciles, so the loading assumes the book's shape held while its size moved.  The
   unconditioned regression is reported beside it, as D-045 reports both.
4. **No alpha over bars where the signal made no distinction.**  A bar whose record holds no short
   (`signal_state`'s all-long test, which also covers a bar with no contributions at all) gets an
   intercept of its own, and only the other bars' intercept is reported as alpha.

The factors, each a log return so that the market one is D-045's regressor exactly:

    market    the point-in-time equal-weight basket: `pit_benchmark` on `window_prices`
    btc       BTCUSDT
    size      top third by trailing 30-day quote volume minus the bottom third - big minus small,
              the opposite sign of the textbook SMB
    low_vol   bottom third by trailing 30-day realised volatility minus the top third
    funding   top third by trailing 7-day summed funding rate minus the bottom third

Funding is SUMMED over the week because intervals differ: on 2026-09-24 LSKUSDT settled 168 times in
seven days, HYPEUSDT 42 and BTCUSDT 21, so a mean per settlement would rank a price of carry by how
often it is charged.  The legs are equal-weight and their returns are price returns.  The funding the
legs would have paid is not in them, while the book's USDT line pays its own, so the book's funding
lands in the residual.

The archive is synced once a day (`deploy/com.starquant.data.plist`, 17:20Z) while the loop runs every
hour.  At 17:20Z the archive ends at the 16:00Z bar, and by 17:00Z the next day the loop is 24 bars past
it.  A key at a bar after the archive's last reads a window short of its newest klines and settlements,
so it is provisional: the next sync fills the window in and can move the legs.  `archive` says where the
archive stopped and how many bars short of the sample's end, and both readers print it.

`factor_reading` is pure.  `archive_history` and `archive_funding` are the archive adapters its two
callers share, so the daily block and `report beta` cannot read the archive two ways.  Nothing here
writes, gates or pages.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_data.store import FundingStore, KlineStore
from starquant_live.benchmark import (
    HOURS_PER_YEAR,
    MIN_BARS,
    NW_LAGS,
    SIGNIFICANT_T,
    foreign_bars,
    nw_covariance,
    pit_benchmark,
    series_from_cycles,
    signal_state,
    window_prices,
)

BTC = "BTCUSDT"
FACTORS = ("market", "btc", "size", "low_vol", "funding")
#: factor -> (sort key, whether the long leg is the HIGH third)
SORTS = {"size": ("turnover", True), "low_vol": ("volatility", False), "funding": ("funding", True)}
DAY_MS = 86_400_000
KEY_WINDOW_DAYS = 30  # size and low_vol
FUNDING_WINDOW_DAYS = 7
MIN_KEY_SHARE = 0.5  # a 30-day key read off under half its window is a different measurement


def sort_keys(
    bars: Sequence[int],
    universe: Mapping[int, Sequence[str]],
    history: Callable[[str], pd.DataFrame],
    funding: Callable[[str], pd.DataFrame],
    step_ms: int = 3_600_000,
) -> dict[str, pd.DataFrame]:
    """Each bar's three sort keys for the symbols in that bar's universe, from what had closed by its close.

    Frames are bar x symbol.  NaN puts a symbol out of that bar's sort: it was not in the bar's
    universe, the archive holds under `MIN_KEY_SHARE` of the key's window, or no funding settled in
    the week.  `history(symbol)` is the kline archive (`open_time`, `close`, `quote_volume`) and
    `funding(symbol)` the funding archive (`funding_time`, `funding_rate`); a symbol either cannot
    give is a gap, as in `window_prices`.

    Bar t closes at t + step_ms.  By then the kline opened at t has closed, and a funding event
    stamped earlier has settled.  Nothing later is read: the rolling windows only look back, and the
    grid ends at the last bar.  `tests/live/test_factor_loadings_read_only_what_each_bar_knew.py`
    shuffles everything after t and compares the keys at t bit for bit.
    """
    window = KEY_WINDOW_DAYS * DAY_MS // step_ms
    least = int(window * MIN_KEY_SHARE)
    grid = np.arange(bars[0] - window * step_ms, bars[-1] + step_ms, step_ms, dtype="int64")
    closes_at = np.asarray(bars, dtype="int64") + step_ms
    members = sorted({symbol for names in universe.values() for symbol in names})
    keys: dict[str, dict[str, pd.Series]] = {"turnover": {}, "volatility": {}, "funding": {}}
    for symbol in members:
        try:
            frame = history(symbol)
            frame = frame[frame["open_time"].between(grid[0], grid[-1])]
            frame = frame.drop_duplicates("open_time", keep="last").set_index("open_time").reindex(grid)
            close = frame["close"].astype(float)
            keys["turnover"][symbol] = frame["quote_volume"].astype(float).rolling(window, min_periods=least).mean()
            logs = pd.Series(np.log(close.where(close > 0).to_numpy()), index=grid)
            keys["volatility"][symbol] = logs.diff().rolling(window, min_periods=least).std()
        except Exception:  # a missing or unreadable parquet is a gap here, not a failure
            pass
        try:
            events = funding(symbol).dropna(subset=["funding_time", "funding_rate"])
        except Exception:
            continue
        times = events["funding_time"].to_numpy(dtype="int64")
        order = np.argsort(times, kind="stable")
        times, rates = times[order], events["funding_rate"].to_numpy(dtype=float)[order]
        # Settled strictly before the bar's close, and within the week before it.  A running sum makes
        # this one subtraction per bar; it only ever adds what settled earlier, so later rows cannot
        # reach it.
        upper = np.searchsorted(times, closes_at, side="left")
        lower = np.searchsorted(times, closes_at - FUNDING_WINDOW_DAYS * DAY_MS, side="left")
        running = np.concatenate([[0.0], np.cumsum(rates)])
        keys["funding"][symbol] = pd.Series(
            np.where(upper > lower, running[upper] - running[lower], np.nan), index=list(bars)
        )
    sets = [set(universe.get(bar) or ()) for bar in bars]
    held = pd.DataFrame({symbol: [symbol in names for names in sets] for symbol in members}, index=list(bars))
    out: dict[str, pd.DataFrame] = {}
    for key, found in keys.items():
        frame = pd.DataFrame({s: v.reindex(list(bars)) for s, v in found.items()}, index=list(bars), columns=members)
        out[key] = frame.astype(float).where(held)
    return out


def _thirds(values: Mapping[str, float]) -> tuple[list[str], list[str]]:
    """The top and bottom thirds of one bar's sort key.  Ties break by symbol so the split is deterministic."""
    ranked = sorted((value, symbol) for symbol, value in values.items() if not math.isnan(value))
    k = len(ranked) // 3
    return [s for _, s in ranked[len(ranked) - k :]] if k else [], [s for _, s in ranked[:k]]


def _leg_return(
    leg: Sequence[str], prices: Mapping[str, Mapping[int, float]], prev: int, cur: int
) -> tuple[float | None, int]:
    """Equal-weight simple return of one leg, and how many of its names had no price at an end."""
    rets = []
    for symbol in leg:
        series = prices.get(symbol) or {}
        p0, p1 = series.get(prev), series.get(cur)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        rets.append(p1 / p0 - 1.0)
    return (sum(rets) / len(rets) if rets else None), len(leg) - len(rets)


def factor_returns(
    bars: Sequence[int],
    universe: Mapping[int, Sequence[str]],
    prices: Mapping[str, Mapping[int, float]],
    keys: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Each factor's log return over each consecutive pair of bars; None where it could not be formed.

    The legs are chosen at the pair's first bar from that bar's keys, and paid its move to the second.
    A leg name without a price at either end is skipped and counted, as `pit_benchmark` counts its own.
    """
    level = pit_benchmark(bars, universe, prices)["level"]
    by_bar = {key: frame.to_dict("index") for key, frame in keys.items()}
    series: dict[str, list[float | None]] = {name: [] for name in FACTORS}
    ranked = dict.fromkeys(SORTS, 0)
    per_leg = dict.fromkeys(SORTS, 0)
    unpriced = dict.fromkeys(SORTS, 0)
    btc = prices.get(BTC) or {}
    for i, (prev, cur) in enumerate(pairwise(bars), start=1):
        series["market"].append(math.log(level[i] / level[i - 1]) if level[i - 1] > 0 and level[i] > 0 else None)
        p0, p1 = btc.get(prev), btc.get(cur)
        series["btc"].append(math.log(p1 / p0) if p0 and p1 and p0 > 0 and p1 > 0 else None)
        for name, (key, long_high) in SORTS.items():
            values = {str(s): float(v) for s, v in (by_bar[key].get(prev) or {}).items() if not math.isnan(v)}
            high, low = _thirds(values)
            ranked[name] += len(values)
            per_leg[name] += len(high)
            long_ret, long_miss = _leg_return(high if long_high else low, prices, prev, cur)
            short_ret, short_miss = _leg_return(low if long_high else high, prices, prev, cur)
            unpriced[name] += long_miss + short_miss
            spread = None if long_ret is None or short_ret is None else long_ret - short_ret
            series[name].append(math.log1p(spread) if spread is not None and spread > -1.0 else None)
    pairs = max(1, len(bars) - 1)
    return {
        "series": series,
        "sorts": {
            name: {
                "ranked_per_bar": ranked[name] / pairs,
                "names_per_leg": per_leg[name] / pairs,
                "leg_names_without_price": unpriced[name],
            }
            for name in SORTS
        },
    }


def _fit(y: Sequence[float], regressors: Mapping[str, Sequence[float]], all_long: Sequence[bool]) -> dict[str, Any]:
    """OLS of the book on the regressors, NW t, and an intercept of their own for the all-long bars.

    The intercept printed as alpha is the one for bars where the signal held a short.  When every bar
    is all-long there is none: the book is `constant_long` there by construction (D-045's fourth rule).
    """
    names = list(regressors)
    observed = np.asarray(y, dtype=float)
    split = 0 < sum(all_long) < len(all_long)
    columns = [np.ones(len(observed)), *([np.asarray(all_long, dtype=float)] if split else [])]
    design = np.column_stack([*columns, *(np.asarray(regressors[name], dtype=float) for name in names)])
    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    resid = observed - design @ coefficients
    found = nw_covariance(design, resid, NW_LAGS)
    if found is None:
        return {"measured": False, "reason": "设计矩阵退化：回归元完全共线，或样本不多于回归元"}
    covariance, lags = found
    se = np.sqrt(np.diag(covariance))
    first = len(columns)
    covers = lags >= NW_LAGS
    ss_res = float((resid**2).sum())
    ss_tot = float(((observed - observed.mean()) ** 2).sum())
    explained = sum(float(coefficients[first + j]) * float(np.sum(design[:, first + j])) for j in range(len(names)))
    distinct = len(all_long) - sum(all_long)
    alpha, alpha_t = float(coefficients[0]), (float(coefficients[0] / se[0]) if se[0] else None)
    why = None
    if distinct == 0:
        why = f"全部 {len(all_long)} 根 bar 信号都没有空头，书就是 constant_long。截距说的是构造与 universe，不是信号"
    elif distinct < MIN_BARS:
        why = f"信号有空头的 bar 只有 {distinct} 根，不到 {MIN_BARS} 根"
    matrix = np.corrcoef(design[:, first:], rowvar=False).reshape(len(names), len(names))
    pair = max(combinations(range(len(names)), 2), key=lambda ij: abs(matrix[ij]), default=None)
    return {
        "measured": True,
        "loadings": {
            name: {
                "loading": float(coefficients[first + j]),
                "t": float(coefficients[first + j] / se[first + j]) if se[first + j] else None,
            }
            for j, name in enumerate(names)
        },
        "alpha_bars": distinct,
        "alpha_why": why,
        "alpha_bps_per_hour": alpha * 1e4 if why is None else None,
        "alpha_t": alpha_t if why is None else None,
        # D-045's two refusals, unchanged: a signal in the estimate, and a ruler that reached its horizon.
        "alpha_annualised": (
            math.expm1(alpha * HOURS_PER_YEAR)
            if why is None and alpha_t is not None and covers and abs(alpha_t) >= SIGNIFICANT_T
            else None
        ),
        "nw_lags": lags,
        "nw_lags_requested": NW_LAGS,
        "nw_covers_intended_horizon": covers,
        "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else None,
        "residual_vol_annualised": math.sqrt(ss_res / (len(observed) - design.shape[1]) * HOURS_PER_YEAR),
        "factor_part": math.expm1(explained),
        "residual_part": math.expm1(float(observed.sum()) - explained),
        # Between the factors as they entered the regression.  A high pair splits one move between two
        # loadings, and neither t says how much of it the pair explains together.
        "collinearity": {
            "max_pair": [names[pair[0]], names[pair[1]]] if pair else [],
            "max_abs_correlation": float(abs(matrix[pair])) if pair else None,
            "vif": dict(zip(names, (float(v) for v in np.diag(np.linalg.inv(matrix))), strict=True))
            if len(names) > 1
            else {names[0]: 1.0},
        },
    }


def _archive_reach(
    frames: Mapping[str, pd.DataFrame | Exception], held: Sequence[str], end: int | None, step_ms: int
) -> dict[str, Any]:
    """Where the kline archive stops for the names the last bar held, and how many bars short of the sample's end.

    The earliest stop among those names, because one name that stopped early is enough to leave its keys
    provisional.  Names no longer held are not asked: their keys are no longer read, and the sync, which
    refreshes the current pool, may have left them behind (CYSUSDT and TUTUSDT stop at 2026-09-23T15:00Z).
    """
    stops = [
        int(frame["open_time"].max())
        for symbol, frame in frames.items()
        if symbol in held and not isinstance(frame, Exception) and len(frame)
    ]
    if not stops:
        return {"last_bar": None, "bars_behind_sample_end": None}
    return {
        "last_bar": datetime.fromtimestamp(min(stops) / 1000, UTC).isoformat(),
        "bars_behind_sample_end": None if end is None else max(0, (end - min(stops)) // step_ms),
    }


def factor_reading(
    cycles: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    history: Callable[[str], pd.DataFrame],
    funding: Callable[[str], pd.DataFrame],
    strategy: str = "tsmom",
    step_ms: int = 3_600_000,
) -> dict[str, Any]:
    """The multi-factor reading from what the loop wrote: `report beta`'s factor page and the daily block.

    The book is D-045's series: `series_from_cycles`' USDT line, the D-032 bars `foreign_bars` drops,
    and the exposure the loop carried into each bar.  A bar pair where any factor could not be formed
    leaves the sample and is counted by factor.  `archive` is `_archive_reach` against the last bar the
    sample reaches.
    """
    series = series_from_cycles(cycles)
    bars = series["bars"]
    if len(bars) < 2:
        return {"measured": False, "reason": "周期记录里还没有两根带 usdt_equity 的 bar，无法分解"}
    frames: dict[str, pd.DataFrame | Exception] = {}

    def archived(symbol: str) -> pd.DataFrame:
        if symbol not in frames:
            try:
                frames[symbol] = history(symbol)
            except Exception as exc:
                frames[symbol] = exc
        found = frames[symbol]
        if isinstance(found, Exception):
            raise found
        return found

    def closes(symbol: str) -> pd.Series:
        frame = archived(symbol)
        return pd.Series(frame["close"].to_numpy(dtype=float), index=frame["open_time"].to_numpy(dtype="int64"))

    keys = sort_keys(bars, series["universe"], archived, funding, step_ms)
    built = factor_returns(bars, series["universe"], window_prices(series, closes), keys)
    drop = set(foreign_bars(attribution))
    rows_at: dict[int, list[Mapping[str, Any]]] = {}
    for row in cycles:
        rows_at.setdefault(int(row.get("bar_open_ms") or 0), []).append(row)
    equity, net, gross = series["equity"], series["exposure"], series["gross"]
    y: list[float] = []
    raw: dict[str, list[float]] = {name: [] for name in FACTORS}
    conditioned: dict[str, list[float]] = {name: [] for name in FACTORS}
    all_long: list[bool] = []
    entry: list[int] = []
    end: int | None = None  # the last bar the sample reaches
    excluded = short_of_factors = 0
    missing = dict.fromkeys(FACTORS, 0)
    for i in range(1, len(bars)):
        if bars[i] in drop:
            excluded += 1
            continue
        values = {name: built["series"][name][i - 1] for name in FACTORS}
        if any(value is None for value in values.values()):
            short_of_factors += 1
            for name, value in values.items():
                missing[name] += value is None
            continue
        y.append(math.log(equity[i] / equity[i - 1]))
        for name in FACTORS:
            value = float(values[name] or 0.0)
            raw[name].append(value)
            conditioned[name].append((net if name in ("market", "btc") else gross)[i - 1] * value)
        state = signal_state(rows_at.get(bars[i - 1], ()), strategy)
        all_long.append(state["all_long_bars"] == state["bars"] if state["measured"] else True)
        entry.append(bars[i - 1])
        end = bars[i]
    out: dict[str, Any] = {
        "window": {
            "from": datetime.fromtimestamp(bars[0] / 1000, UTC).isoformat(),
            "to": datetime.fromtimestamp(bars[-1] / 1000, UTC).isoformat(),
            "days": (bars[-1] - bars[0]) / 86_400_000,
            "cycles": len(bars),
        },
        "archive": _archive_reach(frames, series["universe"][bars[-1]], end, step_ms),
        "sorts": built["sorts"],
        "signal": signal_state(cycles, strategy, entry) if entry else {"measured": False, "reason": "no usable bar"},
    }
    counts = {
        "bars": len(y),
        "excluded_bars": excluded,
        # Steps dropped because a factor could not be formed, once each; by factor, a step can count twice.
        "short_of_factors_bars": short_of_factors,
        "factor_missing_bars": missing,
    }
    if len(y) < MIN_BARS:
        out["regression"] = {"measured": False, "reason": f"needs {MIN_BARS} usable bars, has {len(y)}", **counts}
        return out
    conditional = _fit(y, conditioned, all_long)
    # Fitted with `conditional`'s intercepts, the all-long one included, so the R^2 gap between the two is the
    # other four factors' and nothing else.  Without that intercept it is D-045's conditional regression to the
    # bit (the dummy-off test), and the gap would mix the dummy in.  The label says which of the two it is.
    market_only = _fit(y, {"market": conditioned["market"]}, all_long)
    out["regression"] = {
        "measured": bool(conditional.get("measured")),
        **({"reason": conditional["reason"]} if "reason" in conditional else {}),
        **counts,
        "all_long_bars": sum(all_long),
        "conditional": conditional,
        "constant": _fit(y, raw, all_long),
        "market_only": {
            "loading": ((market_only.get("loadings") or {}).get("market") or {}).get("loading"),
            "t": ((market_only.get("loadings") or {}).get("market") or {}).get("t"),
            "r2": market_only.get("r2"),
        },
    }
    return out


def archive_history(root: str | Path, interval: str) -> Callable[[str], pd.DataFrame]:
    """The kline archive, three columns of it, through the store's own layout."""
    store = KlineStore(root)
    return lambda symbol: pd.read_parquet(store.path(symbol, interval), columns=["open_time", "close", "quote_volume"])


def archive_funding(root: str | Path) -> Callable[[str], pd.DataFrame]:
    """The funding archive, through the store's own layout.  A symbol with no file raises, and is a gap."""
    store = FundingStore(root)
    return lambda symbol: pd.read_parquet(store.path(symbol), columns=["funding_time", "funding_rate"])
