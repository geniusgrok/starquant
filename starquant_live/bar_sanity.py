"""Is each bar a cycle hands the model plausible as a price?  Alert only (G6, 2026-09-23).

The loop's standing checks ask whether data is THERE and FRESH: a stale feed skips the cycle
(`guards.py`), an archive month is checksummed (`starquant_data/archive.py`).  None of them looks at the
price.  A contract redenominated under the same symbol keeps its history, so every one of those
checks passes while the model reads a move that never traded: BNXUSDT came back on 2023-02-22 14:00
at 1/55 of its last close after a 518-bar halt, and tsmom's horizons and the inverse-vol divisor
would both read that as a market move for as long as it sat in their windows.

Three checks, one question each:

* ``ohlc``   - the bar contradicts itself: low above min(open, close), high below max(open, close),
  or a price that is not a finite positive number.
* ``frozen`` - ``FROZEN_BARS`` or more consecutive bars with open == high == low == close and zero
  volume: a halted or dead market, or a feed repeating itself.
* ``jump``   - ``|ln(close / previous close)| > MAX_LOG_RETURN``.  The flag carries whether any trade
  bridged the two closes (no missing bar, volume on both sides), because that is what separates a
  price that changed while nothing traded from a real crash - see the measurements below.

**Alert only, by construction.**  `model_inputs` stores the result on `ModelInputs.sanity`, the engine
writes it into the cycle row under ``bar_sanity``, and the daily report is its only reader.  Nothing
here reaches the model, the guards or the planner, and nothing here raises: a frame the check cannot
read becomes an entry under ``errors``, a failure of the whole pass becomes ``error``, and the cycle
trades exactly as it would have without it - the contract `_snapshot_metrics` keeps, for the same
reason: collecting a reading may never be the reason a book stops trading.

**Thresholds, measured** by ``scratchpad/bar_sanity_archive_scan.py`` over every 1h file in the
archive (878 files, 15,127,202 bars, 866,126 of them on PIT-member days):

* ``ohlc``: 0 bars.  Any hit in the live feed is a data error.
* ``frozen``: zero-volume bars are always flat in this archive (1,273,085 of both).  On member days
  the runs are 1 bar long 17 times - all at 2024-10-28 20:00, one venue-wide hour shared by 299
  symbols - then 15 (LUNAUSDT's 2022-05-12 halt), then the FTT and ALPACA dead tails.  Nothing
  between 2 and 14, so any threshold in that range flags the same member runs; 2 is the smallest
  that ignores a single venue-wide hour, and it says so soonest when a market stops.
* ``jump``: ln 2, a doubling or halving inside one bar.  It flags 86 bars archive-wide.  The 8
  with no trade bridging the two closes are the artifacts: BNX back from its halt at x1/55, KORU
  and CRWD reopening at x0.049 and x0.26 after zero-volume hours, and PUMP, LIT, AERGO, MAVIA and
  CVX coming back from a hole at x0.11 to x6.3.  The other 78 are real hours (LUNA, OM, TAC).  On
  member days it flags 15 bars on 9 days, all real: about 2.6 a year at the live universe's size.
  ln 3 would drop CVX and keep 25 real hours; ln 1.5 would add three reopenings (CTK x0.51, TLM
  x0.57, AIA x1.63) and 311 more real hours.

A real hour flagged is not a false alarm - a halving inside one hour in a name the book holds is worth
reading - but since the operator's ruling of 2026-09-23 it is a notice, not a page (`sanity_findings`):
what pages is what no real market produces.  The flag says which kind it is either way.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.panel import interval_seconds

logger = logging.getLogger(__name__)

#: ``|ln(close / previous close)|`` above this flags a ``jump``.  Measured, see the module docstring.
MAX_LOG_RETURN = math.log(2.0)
#: This many consecutive flat, zero-volume bars flag a ``frozen`` run.  Measured, see the docstring.
FROZEN_BARS = 2
#: Flags written per check per cycle, newest first.  ``counts`` stays exact; the list is for reading.
LISTED_PER_CHECK = 10
CHECKS = ("ohlc", "frozen", "jump")


def _open_times(frame: pd.DataFrame) -> np.ndarray:
    """Bar open times in epoch ms: the feed's ``open_time`` column, or a panel's DatetimeIndex."""
    if "open_time" in frame.columns:
        return frame["open_time"].to_numpy(dtype=np.int64)
    if isinstance(frame.index, pd.DatetimeIndex):
        return frame.index.to_numpy(dtype="datetime64[ms]").astype(np.int64)
    raise ValueError("frame carries neither an open_time column nor a DatetimeIndex")


def _ohlc_flags(
    symbol: str, times: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray
) -> list[dict[str, Any]]:
    with np.errstate(invalid="ignore"):
        reasons = {
            "non_finite": ~(np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c)),
            "non_positive": (o <= 0) | (h <= 0) | (lo <= 0) | (c <= 0),
            "low_above_body": lo > np.minimum(o, c),
            "high_below_body": h < np.maximum(o, c),
        }
    hit = np.logical_or.reduce(list(reasons.values()))
    return [
        {
            "symbol": symbol,
            "check": "ohlc",
            "open_time": int(times[i]),
            "reasons": [name for name, mask in reasons.items() if mask[i]],
            "ohlc": [float(o[i]), float(h[i]), float(lo[i]), float(c[i])],
        }
        for i in np.flatnonzero(hit)
    ]


def _frozen_flags(
    symbol: str, times: np.ndarray, o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, v: np.ndarray
) -> list[dict[str, Any]]:
    flat = (o == h) & (h == lo) & (lo == c) & (v == 0)
    edges = np.flatnonzero(np.diff(np.concatenate(([False], flat, [False])).astype(np.int8)))
    return [
        {
            "symbol": symbol,
            "check": "frozen",
            "open_time": int(times[start]),
            "last_open_time": int(times[end - 1]),
            "bars": int(end - start),
            "price": float(c[start]),
        }
        for start, end in zip(edges[0::2], edges[1::2], strict=True)
        if end - start >= FROZEN_BARS
    ]


def _jump_flags(
    symbol: str, times: np.ndarray, o: np.ndarray, c: np.ndarray, v: np.ndarray, step_ms: int
) -> list[dict[str, Any]]:
    with np.errstate(divide="ignore", invalid="ignore"):
        log_return = np.log(c[1:] / c[:-1])
        open_gap = np.log(o[1:] / c[:-1])
    flags = []
    for i in np.flatnonzero(np.abs(log_return) > MAX_LOG_RETURN):
        gap_bars = int((times[i + 1] - times[i]) // step_ms) - 1
        flags.append(
            {
                "symbol": symbol,
                "check": "jump",
                "open_time": int(times[i + 1]),
                "log_return": round(float(log_return[i]), 4),
                "open_gap": round(float(open_gap[i]), 4),
                "gap_bars": gap_bars,
                # A trade bridged the two closes: nothing missing between them, volume on both sides.
                "continuous": bool(gap_bars == 0 and v[i] > 0 and v[i + 1] > 0),
                "previous_close": float(c[i]),
                "close": float(c[i + 1]),
            }
        )
    return flags


def _check_frame(symbol: str, frame: pd.DataFrame, step_ms: int) -> list[dict[str, Any]]:
    times = _open_times(frame)
    o, h, lo, c, v = (frame[column].to_numpy(dtype=float) for column in ("open", "high", "low", "close", "volume"))
    return [
        *_ohlc_flags(symbol, times, o, h, lo, c),
        *_frozen_flags(symbol, times, o, h, lo, c, v),
        *_jump_flags(symbol, times, o, c, v, step_ms),
    ]


def check_bars(bars: Mapping[str, pd.DataFrame], interval: str = "1h") -> dict[str, Any]:
    """The cycle's reading of its own closed bars.  Pure, JSON-ready, and never raises."""
    started = time.perf_counter()
    try:
        step_ms = interval_seconds(interval) * 1000
        flags: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        rows = 0
        for symbol in sorted(bars):
            frame = bars[symbol]
            try:
                flags.extend(_check_frame(symbol, frame, step_ms))
                rows += len(frame)
            except Exception as exc:  # one unreadable frame costs its own reading, not the others'
                errors[symbol] = f"{type(exc).__name__}: {exc}"
        by_check = {check: [flag for flag in flags if flag["check"] == check] for check in CHECKS}
        listed = [
            flag
            for check in CHECKS
            for flag in sorted(by_check[check], key=lambda f: -int(f["open_time"]))[:LISTED_PER_CHECK]
        ]
        return {
            "symbols": len(bars),
            "bars": rows,
            "counts": {check: len(found) for check, found in by_check.items()},
            "flags": listed,
            "errors": errors,
            "limits": {"max_log_return": round(MAX_LOG_RETURN, 6), "frozen_bars": FROZEN_BARS},
            "seconds": round(time.perf_counter() - started, 6),
        }
    except Exception as exc:
        logger.warning("bar sanity check failed and was skipped: %s", exc, exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}", "seconds": round(time.perf_counter() - started, 6)}


# --- the daily report's side ------------------------------------------------------------------------


def _identity(flag: Mapping[str, Any]) -> tuple[str, str, Any]:
    return str(flag.get("symbol")), str(flag.get("check")), flag.get("open_time")


def sanity_status(
    rows: Sequence[dict[str, Any]], day: str, *, day_of: Callable[[dict[str, Any]], str | None]
) -> dict[str, Any]:
    """What the day's cycles saw, split into flags first seen today and flags already seen before.

    A flagged bar stays in the model's window for as long as the window is (1,442 bars live), so
    every cycle re-reports it.  Paging on each report would page for sixty days; paging on bars that
    CLOSED today would miss the case this exists for - a symbol entering the pool with a
    redenomination already in its history.  "First seen today" pages once for both.
    """
    earlier: set[tuple[str, str, Any]] = set()
    today: list[Mapping[str, Any]] = []
    for row in rows:
        block, row_day = row.get("bar_sanity"), day_of(row)
        if not isinstance(block, Mapping) or row_day is None or row_day > day:
            continue
        if row_day < day:
            earlier.update(_identity(flag) for flag in block.get("flags") or [])
        else:
            today.append(block)
    new: dict[tuple[str, str, Any], Mapping[str, Any]] = {}
    standing: set[tuple[str, str, Any]] = set()
    for block in today:
        for flag in block.get("flags") or []:
            key = _identity(flag)
            if key in earlier:
                standing.add(key)
            else:
                new.setdefault(key, flag)
    failures = [
        str(block.get("error") or "；".join(f"{s}: {e}" for s, e in (block.get("errors") or {}).items()))
        for block in today
        if block.get("error") or block.get("errors")
    ]
    seconds = [float(block["seconds"]) for block in today if isinstance(block.get("seconds"), int | float)]
    return {
        "cycles": len(today),
        "new": [dict(flag) for flag in new.values()],
        "standing": len(standing),
        "errors": len(failures),
        "first_error": failures[0] if failures else None,
        "max_seconds": max(seconds) if seconds else None,
    }


def describe_flag(flag: Mapping[str, Any]) -> str:
    """One flag as the operator reads it: symbol, bar, and which kind of anomaly it is."""
    stamp = datetime.fromtimestamp(int(flag.get("open_time") or 0) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%MZ")
    symbol, check = flag.get("symbol"), flag.get("check")
    if check == "jump":
        log_return = min(max(float(flag.get("log_return") or 0.0), -700.0), 700.0)  # exp() raises past ~709
        if flag.get("continuous"):
            bridge = "两根之间有连续成交，像真实行情"
        elif int(flag.get("gap_bars") or 0) > 0:
            bridge = f"与上一根之间缺 {flag.get('gap_bars')} 根、开盘即跳 ln {float(flag.get('open_gap') or 0.0):+.2f}"
        else:
            bridge = f"前后有一根零成交、开盘即跳 ln {float(flag.get('open_gap') or 0.0):+.2f}"
        return f"{symbol} {stamp} 跳变 ×{math.exp(log_return):.3g}（ln {log_return:+.2f}；{bridge}）"
    if check == "frozen":
        return f"{symbol} {stamp} 起连续 {flag.get('bars')} 根 OHLC 全等且零成交（价 {flag.get('price')}）"
    return f"{symbol} {stamp} OHLC 自相矛盾（{'、'.join(str(r) for r in flag.get('reasons') or [])}）"


def is_traded_through(flag: Mapping[str, Any]) -> bool:
    """A jump both of whose bars traded: it reads as a real market, not as a broken price."""
    return flag.get("check") == "jump" and bool(flag.get("continuous"))


def _listed(flags: list[Mapping[str, Any]]) -> str:
    more = f"；另有 {len(flags) - 5} 处" if len(flags) > 5 else ""
    return "；".join(describe_flag(flag) for flag in flags[:5]) + more


def sanity_findings(block: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(alerts, notices) for `daily_alerts`: a new flag pages; a check that could not run is read at review.

    Operator ruling 2026-09-23: a jump that traded through (`is_traded_through`) is read at review, not
    paged.  At ln 2 the archive's member days carry about 2.6 of those a year, every one a real move.
    What still pages is what a real market cannot produce: a jump across a gap (BNX's re-denomination),
    an OHLC contradiction, a frozen run.
    """
    alerts: list[str] = []
    notices: list[str] = []
    new = [flag for flag in block.get("new") or [] if not is_traded_through(flag)]
    market = [flag for flag in block.get("new") or [] if is_traded_through(flag)]
    if new:
        alerts.append(f"bar sanity：今天首次出现 {len(new)} 处可疑 bar（只告警，交易照常）：{_listed(new)}")
    if market:
        notices.append(
            f"bar sanity：今天首次出现 {len(market)} 处有连续成交的跳变（像真实行情，只提示）：{_listed(market)}"
        )
    if block.get("errors"):
        notices.append(
            f"bar sanity 检查今天有 {block['errors']} 个周期没读完（只记录，交易照常）：{block.get('first_error')}"
        )
    return alerts, notices


def sanity_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """The daily markdown's block.  Says so when no cycle carried the reading, rather than printing zeros."""
    if not block.get("cycles"):
        return {"cycles_checked": 0, "why": "今天没有周期写 bar_sanity（循环还在跑加这项检查之前的代码）"}
    return {
        "cycles_checked": block["cycles"],
        "first_seen_today": "；".join(describe_flag(flag) for flag in block.get("new") or []) or "none",
        "seen_before_still_in_window": block.get("standing"),
        "check_errors": block.get("errors"),
        "first_error": block.get("first_error") or "none",
        "max_seconds": block.get("max_seconds"),
    }
