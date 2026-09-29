"""Completed-minute rules. An unfinished minute is not a signal."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np


@dataclass(frozen=True)
class MinuteBar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float
    closed: bool


@dataclass(frozen=True)
class BarStatus:
    fresh: bool
    reason: str
    new_bars: tuple[MinuteBar, ...]
    last_open_ms: int


def inspect_bars(bars: tuple[MinuteBar, ...], now_ms: int, cursor_ms: int, *, max_lag_ms: int = 15_000) -> BarStatus:
    closed = tuple(bar for bar in bars if bar.closed and bar.open_ms + 60_000 <= now_ms)
    if not closed:
        return BarStatus(False, "没有已完成的分钟", (), cursor_ms)
    for bar in closed:
        values = (bar.open, bar.high, bar.low, bar.close, bar.quote_volume)
        if not all(math.isfinite(value) for value in values):
            return BarStatus(False, "K 线含 NaN 或无穷大", (), cursor_ms)
        if bar.open_ms % 60_000 != 0:
            return BarStatus(False, "K 线开盘时间不在分钟边界上", (), cursor_ms)
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            return BarStatus(False, "K 线价格无效", (), cursor_ms)
        if bar.high + 1e-9 < max(bar.open, bar.close, bar.low):
            return BarStatus(False, "K 线 high 低于其他价格", (), cursor_ms)
        if bar.low - 1e-9 > min(bar.open, bar.close, bar.high):
            return BarStatus(False, "K 线 low 高于其他价格", (), cursor_ms)
        if bar.quote_volume < 0:
            return BarStatus(False, "成交额为负", (), cursor_ms)
    ordered = tuple(sorted(closed, key=lambda bar: bar.open_ms))
    for prev, nxt in pairwise(ordered):
        if nxt.open_ms == prev.open_ms:
            return BarStatus(False, "分钟时间戳重复", (), cursor_ms)
        if nxt.open_ms - prev.open_ms != 60_000:
            return BarStatus(False, f"分钟不连续：{prev.open_ms} -> {nxt.open_ms}", (), cursor_ms)
    last = ordered[-1]
    expected = (now_ms // 60_000) * 60_000 - 60_000
    if last.open_ms < expected - max_lag_ms:
        return BarStatus(False, "行情滞后", (), cursor_ms)
    if last.open_ms > now_ms:
        return BarStatus(False, "行情时间超前", (), cursor_ms)
    fresh = tuple(bar for bar in ordered if bar.open_ms > cursor_ms)
    if cursor_ms and fresh and fresh[0].open_ms - cursor_ms != 60_000:
        return BarStatus(False, "游标与新 K 线之间有缺口", (), cursor_ms)
    return BarStatus(True, "", fresh, last.open_ms)


def bars_from_kline_rows(rows: object, now_ms: int) -> tuple[MinuteBar, ...]:
    """Binance kline rows. The forming minute stays ``closed=False``."""
    if not isinstance(rows, list):
        return ()
    bars: list[MinuteBar] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise ValueError("分钟 K 线里有格式不对的行")
        open_ms = int(row[0])
        close_ms = int(row[6])
        bars.append(
            MinuteBar(
                open_ms=open_ms,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                quote_volume=float(row[7]),
                closed=close_ms <= now_ms,
            )
        )
    return tuple(bars)


HOUR_MS = 3_600_000


def hour_rows_from_klines(rows: object, now_ms: int) -> tuple[tuple[int, float, float], ...] | None:
    """Completed hours as (open_ms, high, low), or ``None`` if the series cannot be trusted.

    A missing, repeated, unordered, misaligned or non-finite hour makes every
    channel that spans it wrong, so the whole series is refused rather than
    patched. An empty or absent series is also ``None``.
    """
    if not isinstance(rows, list):
        return None
    found: list[tuple[int, float, float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            return None
        try:
            open_ms, close_ms = int(row[0]), int(row[6])
            high, low = float(row[2]), float(row[3])
        except (TypeError, ValueError):
            return None
        if close_ms > now_ms:
            continue
        if not (math.isfinite(high) and math.isfinite(low)) or low <= 0 or high < low:
            return None
        if open_ms % HOUR_MS != 0 or close_ms != open_ms + HOUR_MS - 1:
            return None
        found.append((open_ms, high, low))
    if not found:
        return None
    for prev, nxt in pairwise(found):
        if nxt[0] - prev[0] != HOUR_MS:
            return None
    return tuple(found)


def completed_hour_channels(
    rows: object,
    now_ms: int,
    entry_hours: int,
    exit_hours: int,
) -> tuple[float, float, float, float, int] | None:
    """Entry and exit levels from completed hourly klines only.

    The returned hour open is the last completed hour. Levels include that
    hour. A minute may use them only when its own hour begins after that hour
    ends (the runner checks this); a minute inside hour H never sees hour H.
    """
    from scripts.frontier import rolling_max, rolling_min

    found = hour_rows_from_klines(rows, now_ms)
    if found is None:
        return None
    last_open = found[-1][0]
    high = np.asarray([item[1] for item in found], dtype=np.float64)
    low = np.asarray([item[2] for item in found], dtype=np.float64)
    hh = float("inf") if len(high) < entry_hours else float(rolling_max(high, entry_hours)[-1])
    ll = float("-inf") if len(low) < entry_hours else float(rolling_min(low, entry_hours)[-1])
    xh = float("inf") if len(high) < exit_hours else float(rolling_max(high, exit_hours)[-1])
    xl = float("-inf") if len(low) < exit_hours else float(rolling_min(low, exit_hours)[-1])
    return hh, ll, xh, xl, last_open
