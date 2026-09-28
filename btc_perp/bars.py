"""Completed-minute rules. An unfinished minute is not a signal."""

from __future__ import annotations

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
        if nxt.open_ms - prev.open_ms != 60_000:
            return BarStatus(False, f"分钟不连续：{prev.open_ms} -> {nxt.open_ms}", (), cursor_ms)
        if nxt.open_ms == prev.open_ms:
            return BarStatus(False, "分钟时间戳重复", (), cursor_ms)
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
            continue
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

    if not isinstance(rows, list):
        return None
    highs: list[float] = []
    lows: list[float] = []
    last_open = 0
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        close_ms = int(row[6])
        if close_ms > now_ms:
            continue
        highs.append(float(row[2]))
        lows.append(float(row[3]))
        last_open = int(row[0])
    if not highs:
        return None
    high = np.asarray(highs, dtype=np.float64)
    low = np.asarray(lows, dtype=np.float64)
    hh = float("inf") if len(high) < entry_hours else float(rolling_max(high, entry_hours)[-1])
    ll = float("-inf") if len(low) < entry_hours else float(rolling_min(low, entry_hours)[-1])
    xh = float("inf") if len(high) < exit_hours else float(rolling_max(high, exit_hours)[-1])
    xl = float("-inf") if len(low) < exit_hours else float(rolling_min(low, exit_hours)[-1])
    return hh, ll, xh, xl, last_open
