"""缠论 (Chan theory) structure: merged bars -> fractals -> pens -> segments -> centres -> buy/sell points.

The 51st strategy, and the one the operator named first.  Chan theory is a family of formalisations
rather than one algorithm, so §7 of the governance plan pre-registered exactly ONE and this module
implements that one.  The rule that matters more than any of the choices below: they were written
down before this file existed, and "whichever variant scores better" is not available.

**Pre-registered formalisation** (docs/analysis/2026-09-08-autonomous-governance-51-strategies-plan.md §7):

* 包含关系 - merged left to right; while the preceding direction is up an engulfing pair becomes
  (higher high, higher low), while it is down it becomes (lower low, lower high).  Only bars <= t.
* 分型 - a top fractal at merged bar i needs bar i+1 to exist, so it is CONFIRMED at i+1's close and
  every structure is stamped with the bar that confirmed it, never with the bar that formed it.
* 笔 - between adjacent opposite confirmed fractals with at least ``min_bars`` merged bars between
  them; confirmed when the next opposite fractal confirms.
* 线段 - at least three pens that overlap (pen 1's range against pen 3's).
* 中枢 - the overlap of three consecutive segments; ZG = min of their highs, ZD = max of their lows.
* 买卖点 - a third-type buy (price left the centre upward and the pullback did not re-enter it) scores
  +1; a third-type sell scores -1; a first-type (背驰, MACD area ratio below ``div_ratio``) scores an
  explicit 0.0, which `scores_to_targets` reads as CLOSE rather than as reverse; everything else is
  deliberately sub-threshold, which the same function reads as HOLD.
* 级别 - structure is built on 1h bars, or on 4h bars when ``level`` says so.

**Causality.**  One forward pass; at every t the score is a function of the state as of t and nothing
else.  Unconfirmed structure at the right edge never scores, and a structure that is revised later
never back-fills a score that was already emitted - which is the single way a Chan implementation
usually reads the future, because the textbook draws its lines with the whole chart visible.

At the 4h level a bar's score becomes available only on the 1h bar that CLOSES it, for the same
reason: at 01:00 the 04:00 bar does not exist yet.

**Expected result, recorded before running it.**  Negative, or positive-and-highly-correlated with
tsmom.  On hourly crypto perpetuals this is trend following with a structure filter, and the
pre-registered falsifier is correlation >= 0.5 with tsmom - which would make it "tsmom rewritten"
rather than a second book.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel

LEVELS: dict[str, str] = {"1h": "1h", "4h": "4h"}
#: Sub-threshold, so `scores_to_targets` holds.  Signed only so a reader can see what the structure
#: says; it is never actionable and must stay well under any sane `entry_threshold`.
HOLD = 0.05


@dataclass(frozen=True)
class ChanlunParams:
    level: str = "1h"
    min_bars: int = 4
    div_ratio: float = 0.8
    entry_threshold: float = 0.2

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {sorted(LEVELS)}")
        if self.min_bars < 2:
            raise ValueError("min_bars must be at least 2")
        if not 0 < self.div_ratio <= 1:
            raise ValueError("div_ratio must be in (0, 1]")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> ChanlunParams:
        return cls(**dict(params))

    @property
    def warmup_bars(self) -> int:
        """720 base bars, whatever the level.

        Pre-registered as an upper bound rather than derived: how many bars it takes for three
        segments to overlap is a property of the price path, not of the parameters, so a derived
        number would be a guess wearing a formula.  720 is a conservative estimate for forming a
        centre plus a third-type point at the 4h level, and it stays inside the venue's 1,500-bar
        request ceiling (E-042) with room for the loop's own history.
        """
        return 720


@dataclass
class _Merged:
    high: float
    low: float
    index: int  # the ORIGINAL bar index this merged bar ends on


def _merge(highs: np.ndarray, lows: np.ndarray, upto: int) -> list[_Merged]:
    """包含关系, left to right.  Only bars <= ``upto`` are ever read."""
    merged: list[_Merged] = []
    direction = 1
    for i in range(upto + 1):
        high, low = float(highs[i]), float(lows[i])
        if not merged:
            merged.append(_Merged(high, low, i))
            continue
        last = merged[-1]
        contains = high >= last.high and low <= last.low
        contained = high <= last.high and low >= last.low
        if not (contains or contained):
            direction = 1 if high > last.high else -1
            merged.append(_Merged(high, low, i))
            continue
        if direction > 0:
            last.high, last.low = max(high, last.high), max(low, last.low)
        else:
            last.high, last.low = min(high, last.high), min(low, last.low)
        last.index = i
    return merged


def _fractals(merged: Sequence[_Merged]) -> list[tuple[int, int, float, int]]:
    """(kind, merged position, price, confirming ORIGINAL index).  ``kind`` is +1 top, -1 bottom.

    The confirming index is the bar after the peak, because that is when the peak is knowable.
    """
    out: list[tuple[int, int, float, int]] = []
    for i in range(1, len(merged) - 1):
        left, here, right = merged[i - 1], merged[i], merged[i + 1]
        if here.high > left.high and here.high > right.high:
            out.append((1, i, here.high, right.index))
        elif here.low < left.low and here.low < right.low:
            out.append((-1, i, here.low, right.index))
    return out


@dataclass(frozen=True)
class _Leg:
    """A pen or a segment: a directed move with a range and the bar that confirmed it."""

    direction: int
    high: float
    low: float
    confirmed_at: int


def _pens(fractals: Sequence[tuple[int, int, float, float]], min_bars: int) -> list[_Leg]:
    pens: list[_Leg] = []
    if not fractals:
        return pens
    anchor = fractals[0]
    for candidate in fractals[1:]:
        kind, position, price, confirm = candidate
        anchor_kind, anchor_position, anchor_price, _ = anchor
        if kind == anchor_kind:
            # Same-side fractal: keep the more extreme one, which is the textbook's "取更高的顶".
            if (kind > 0 and price > anchor_price) or (kind < 0 and price < anchor_price):
                anchor = candidate
            continue
        if position - anchor_position < min_bars:
            continue
        pens.append(
            _Leg(
                direction=1 if kind > 0 else -1,
                high=max(price, anchor_price),
                low=min(price, anchor_price),
                confirmed_at=int(confirm),
            )
        )
        anchor = candidate
    return pens


def _segments(pens: Sequence[_Leg]) -> list[_Leg]:
    """At least three pens whose first and third ranges overlap, taken as one directed move."""
    segments: list[_Leg] = []
    i = 0
    while i + 2 < len(pens):
        first, third = pens[i], pens[i + 2]
        if min(first.high, third.high) > max(first.low, third.low):
            window = pens[i : i + 3]
            segments.append(
                _Leg(
                    direction=first.direction,
                    high=max(leg.high for leg in window),
                    low=min(leg.low for leg in window),
                    confirmed_at=window[-1].confirmed_at,
                )
            )
            i += 3
        else:
            i += 1
    return segments


def _centres(segments: Sequence[_Leg]) -> list[tuple[float, float, int]]:
    """(ZG, ZD, confirming index) for every three consecutive segments that overlap."""
    out: list[tuple[float, float, int]] = []
    for i in range(len(segments) - 2):
        window = segments[i : i + 3]
        zg = min(leg.high for leg in window)
        zd = max(leg.low for leg in window)
        if zg > zd:
            out.append((zg, zd, window[-1].confirmed_at))
    return out


def _macd_area(close: pd.Series) -> pd.Series:
    """|MACD histogram| per bar, 12/26/9.  Areas are summed over a move to compare two moves."""
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    macd = fast - slow
    return (macd - macd.ewm(span=9, adjust=False).mean()).abs()


def _score_symbol(high: pd.Series, low: pd.Series, close: pd.Series, params: ChanlunParams) -> pd.Series:
    """One symbol, one forward pass.  Every emitted value uses only bars at or before its own index.

    Every layer of this algorithm is a left-to-right accumulation - merging only ever mutates the most
    recent merged bar, a fractal is decided by three consecutive merged bars, a pen by the last
    fractal, a segment by the last three pens, a centre by the last three segments - so the whole
    thing is one pass and the causality property is structural rather than argued: a single forward
    pass cannot see the future because it has not read it yet.

    The first version rebuilt every structure from bar 0 at each step, which was also causally safe
    (each rebuild sees a prefix) and measured 0.20s / 0.83s / 3.49s at 2k / 4k / 8k bars - textbook
    quadratic, extrapolating to about 132 seconds per symbol on the 49,096-bar archive and roughly
    7.5 hours for ONE backtest of the 205-symbol universe.  This produces the same structures in
    linear time.  `test_truncating_the_panel_does_not_change_the_scores_that_survive` is what holds
    the two claims together.
    """
    highs, lows = high.to_numpy(dtype=float), low.to_numpy(dtype=float)
    area = _macd_area(close).to_numpy(dtype=float)
    cumulative = np.concatenate([[0.0], np.cumsum(area)])
    n = len(close)
    scores = np.full(n, np.nan, dtype=float)
    if n < 8:
        return pd.Series(scores, index=close.index, dtype=float)

    merged: list[_Merged] = []
    direction = 1
    fractals: list[tuple[int, int, float, int]] = []
    anchor: tuple[int, int, float, int] | None = None
    pens: list[_Leg] = []
    segment_start = 0
    segments: list[_Leg] = []
    centre: tuple[float, float, int] | None = None
    side = 0
    previous_extreme: tuple[int, float] | None = None
    window = 4 * params.min_bars

    for i in range(n):
        high_i, low_i = float(highs[i]), float(lows[i])
        if not merged:
            merged.append(_Merged(high_i, low_i, i))
        else:
            last = merged[-1]
            contains = high_i >= last.high and low_i <= last.low
            contained = high_i <= last.high and low_i >= last.low
            if contains or contained:
                if direction > 0:
                    last.high, last.low = max(high_i, last.high), max(low_i, last.low)
                else:
                    last.high, last.low = min(high_i, last.high), min(low_i, last.low)
                last.index = i
            else:
                direction = 1 if high_i > last.high else -1
                merged.append(_Merged(high_i, low_i, i))
                # A fractal at the bar BEFORE the one just appended is now decidable, and this is the
                # bar that decides it (§7: stamped with the confirming bar, never the forming one).
                if len(merged) >= 3:
                    left, here, right = merged[-3], merged[-2], merged[-1]
                    found: tuple[int, int, float, int] | None = None
                    if here.high > left.high and here.high > right.high:
                        found = (1, len(merged) - 2, here.high, right.index)
                    elif here.low < left.low and here.low < right.low:
                        found = (-1, len(merged) - 2, here.low, right.index)
                    if found is not None:
                        fractals.append(found)
                        anchor, pen = _extend_pen(anchor, found, params.min_bars)
                        if pen is not None:
                            pens.append(pen)
                            segment_start, segment = _extend_segment(pens, segment_start)
                            if segment is not None:
                                segments.append(segment)
                                if len(segments) >= 3:
                                    window3 = segments[-3:]
                                    zg = min(leg.high for leg in window3)
                                    zd = max(leg.low for leg in window3)
                                    if zg > zd:
                                        centre = (zg, zd, window3[-1].confirmed_at)

        if centre is None:
            continue
        zg, zd, centre_at = centre
        after = [leg for leg in segments if leg.confirmed_at > centre_at]
        emitted = HOLD * side if side else HOLD
        if len(after) >= 2:
            departure, pullback = after[-2], after[-1]
            if departure.low > zg and pullback.low > zg:
                side = 1
                emitted = 1.0
            elif departure.high < zd and pullback.high < zd:
                side = -1
                emitted = -1.0
            elif side:
                # First-type (背驰): the move that just completed carries less MACD area than the
                # previous same-direction one, so the trend is exhausting.  An explicit 0.0, which
                # `scores_to_targets` reads as CLOSE - never as a reversal (§7).
                current = float(cumulative[i + 1] - cumulative[max(0, i - window)])
                exhausted = (
                    previous_extreme is not None
                    and previous_extreme[0] == pullback.direction
                    and previous_extreme[1] > 0
                    and current / previous_extreme[1] < params.div_ratio
                )
                if exhausted:
                    side = 0
                    emitted = 0.0
                previous_extreme = (pullback.direction, current)
        scores[i] = emitted
    return pd.Series(scores, index=close.index, dtype=float)


def _extend_pen(
    anchor: tuple[int, int, float, int] | None, candidate: tuple[int, int, float, int], min_bars: int
) -> tuple[tuple[int, int, float, int] | None, _Leg | None]:
    """The pen rule of `_pens`, one fractal at a time."""
    if anchor is None:
        return candidate, None
    kind, position, price, confirm = candidate
    anchor_kind, anchor_position, anchor_price, _ = anchor
    if kind == anchor_kind:
        # Same-side fractal: keep the more extreme one, the textbook's 取更高的顶.
        more_extreme = (kind > 0 and price > anchor_price) or (kind < 0 and price < anchor_price)
        return (candidate if more_extreme else anchor), None
    if position - anchor_position < min_bars:
        return anchor, None
    pen = _Leg(
        direction=1 if kind > 0 else -1,
        high=max(price, anchor_price),
        low=min(price, anchor_price),
        confirmed_at=int(confirm),
    )
    return candidate, pen


def _extend_segment(pens: Sequence[_Leg], start: int) -> tuple[int, _Leg | None]:
    """The segment rule of `_segments`, advanced by whatever the new pen made possible."""
    while start + 2 < len(pens):
        first, third = pens[start], pens[start + 2]
        if min(first.high, third.high) > max(first.low, third.low):
            window = pens[start : start + 3]
            return start + 3, _Leg(
                direction=first.direction,
                high=max(leg.high for leg in window),
                low=min(leg.low for leg in window),
                confirmed_at=window[-1].confirmed_at,
            )
        start += 1
    return start, None


def chanlun_scores(panel: Panel, params: ChanlunParams | None = None) -> pd.DataFrame:
    p = params or ChanlunParams()
    high, low, close = panel.high, panel.low, panel.close
    if p.level != "1h":
        # `closed="right"` is deliberate, and the grid it produces is NOT the venue's.  The panel is
        # indexed by bar OPEN time, so this groups the opens in (00:00, 04:00] - the 01/02/03/04 bars,
        # real time 01:00-05:00 - and stamps them at 04:00.  Causally that is the correct stamp: the
        # group's last input is the 04:00 bar, which closes at 05:00, and 05:00 is exactly where the
        # information set of the DECISION bar 04:00 ends, so the `ffill` below can never land a value on
        # a bar that predates its own inputs.  `closed="left"` would group 00/01/02/03 and stamp 00:00,
        # which is Binance's own 4h candle and a one-bar look-ahead unless it is also shifted.
        #
        # The price: these are the 01-05, 05-09, ... buckets, so a `level: "4h"` structure will not line
        # up with a 4h chart, and the disagreement is the grid rather than the algorithm.  Changing it is
        # a STRATEGY change (different pens, different segments, different scores), not a tidy-up -
        # `tests/alpha/test_the_four_hour_grid_is_pinned.py` pins the grouping so that "surely this
        # should be label='left'" fails a test instead of quietly re-deciding a signal.  chanlun is not
        # enabled today, which is why this is written down rather than acted on.
        rule = LEVELS[p.level]
        high = panel.high.resample(rule, label="right", closed="right").max()
        low = panel.low.resample(rule, label="right", closed="right").min()
        close = panel.close.resample(rule, label="right", closed="right").last()
    out = pd.DataFrame(np.nan, index=close.index, columns=panel.close.columns, dtype=float)
    for symbol in panel.close.columns:
        valid = close[symbol].notna()
        if not valid.any():
            continue
        out[symbol] = _score_symbol(high[symbol], low[symbol], close[symbol], p)
    if p.level != "1h":
        # A 4h bar's score is knowable only once that bar has closed, and `label="right"` stamps it at
        # the close.  Reindexing forward from there onto the 1h grid therefore never lands a value on a
        # bar that predates its own inputs; a `nearest` or a backward fill would.
        out = out.reindex(panel.close.index, method="ffill")
    return out.reindex(columns=panel.close.columns)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return chanlun_scores(panel, ChanlunParams.from_mapping(params))
