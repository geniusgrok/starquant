"""Binance futures metrics, in ONE timestamp convention (DL-D2 / KILL-Q11).

Research eats the T+1 daily archive; live can only read the 30-day REST window.  Measured against the
venue on 2026-09-07, those two carry the SAME numbers under DIFFERENT stamps:

    archive `create_time` == rest `timestamp` - 5 minutes    (166/166 exact at -5min; 0/165 at 0, +-10)

A join on ``create_time == timestamp`` is therefore wrong for every bucket, and wrong in the direction
that flatters: research would see a value five minutes before live could have read it.  One bucket of
open interest moves a median 0.090% and a p95 1.15% - small, systematic, and always favourable.  That
is KILL-027's shape, and it is the reason this module exists before any ingestion does.

Which stamp is which was measured rather than guessed, because guessing would be the same mistake one
level down: re-reading the three newest REST buckets six minutes apart returned byte-identical values,
so the newest row is a COMPLETE bucket and its timestamp is the bucket CLOSE.  The archive's is the
bucket OPEN, and there is no partial-bucket hazard.

Publication latency, from the same session: the archive for a day appears at about T+1 06:45-07:00
UTC (three consecutive days: 06:58, 06:52, 06:43); a REST bucket is served roughly two to three
minutes after it closes.

The canonical stamp here is ``open_time``, the same convention ``KlineStore`` already uses, and the
look-ahead is made unrepresentable rather than merely documented: what a bar may read is decided by
the bucket's CLOSE.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

# The columns the daily archive carries, in the order it writes them.
ARCHIVE_COLUMNS = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
VALUE_COLUMNS = tuple(c for c in ARCHIVE_COLUMNS if c not in ("create_time", "symbol"))

# REST spells the same quantities in camelCase, ACROSS FIVE ENDPOINTS, and the same key means a
# different column depending on which one answered.  A flat map cannot express that, and the flat map
# this replaces had two consequences, both measured 2026-09-12:
#
# 1. `snapshot_metrics` polled `/futures/data/openInterestHist` alone, which serves only the two open
#    interest fields - so the four ratio columns were NaN in EVERY live snapshot row while the research
#    archive had them.  That is why #17 read "research yes, live no": a plumbing gap, not evidence.
# 2. `longAccount` was mapped to `count_toptrader_long_short_ratio`, and it is the wrong quantity -
#    `longAccount` is the long ACCOUNT SHARE (0.6298 live right now) while that archive column is a
#    RATIO (BTCUSDT median 1.5249, range 0.4993-5.3241).  It never fired only because the endpoint that
#    returns `longAccount` was never polled.  Verified against the archive before the change:
#      count_toptrader_long_short_ratio  <- topLongShortAccountRatio.longShortRatio    1.7012
#      sum_toptrader_long_short_ratio    <- topLongShortPositionRatio.longShortRatio   2.1974
#      count_long_short_ratio            <- globalLongShortAccountRatio.longShortRatio 1.6323
#      sum_taker_long_short_vol_ratio    <- takerlongshortRatio.buySellRatio           0.3691
#    each of which lands inside its own column's archived range and outside the others'.
REST_SOURCES: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "/futures/data/openInterestHist",
        {"sumOpenInterest": "sum_open_interest", "sumOpenInterestValue": "sum_open_interest_value"},
    ),
    ("/futures/data/topLongShortAccountRatio", {"longShortRatio": "count_toptrader_long_short_ratio"}),
    ("/futures/data/topLongShortPositionRatio", {"longShortRatio": "sum_toptrader_long_short_ratio"}),
    ("/futures/data/globalLongShortAccountRatio", {"longShortRatio": "count_long_short_ratio"}),
    ("/futures/data/takerlongshortRatio", {"buySellRatio": "sum_taker_long_short_vol_ratio"}),
)

#: Kept for the one caller that reads a single open-interest page; see `REST_SOURCES` for the rest.
REST_TO_ARCHIVE = dict(REST_SOURCES[0][1])

PERIOD_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000}


def period_ms(period: str) -> int:
    try:
        return PERIOD_MS[period]
    except KeyError:
        raise ValueError(f"unsupported metrics period {period!r}; known: {sorted(PERIOD_MS)}") from None


def bucket_open_from_archive(create_time: str | pd.Timestamp) -> int:
    """The archive stamps a bucket by its OPEN, so this is already canonical."""
    stamp = pd.Timestamp(create_time)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return int(stamp.value // 1_000_000)


def bucket_open_from_rest(timestamp_ms: int, period: int) -> int:
    """REST stamps a bucket by its CLOSE; one period back is the same bucket the archive names."""
    return int(timestamp_ms) - int(period)


def usable_from_ms(open_time_ms: int, period: int) -> int:
    """The earliest instant a bucket exists at all: its close.

    Deliberately the close and not close-plus-latency.  The measured two-to-three minutes is a
    property of the venue on one day, and baking an observation into a correctness boundary would make
    the boundary quietly wrong the day the venue gets faster or slower.  The close is arithmetic.
    """
    return int(open_time_ms) + int(period)


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["open_time", "symbol", *VALUE_COLUMNS])
    frame["open_time"] = frame["open_time"].astype("int64")
    for column in VALUE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("open_time", ignore_index=True)


def parse_archive_csv(text: str) -> pd.DataFrame:
    """One day of the archive, in the canonical shape.  ``create_time`` does not survive the call.

    Dropping the source column is the point: two names for one instant is how the five minutes got in,
    and a frame that carries both invites a future join on the wrong one.
    """
    raw = pd.read_csv(io.StringIO(text))
    missing = [c for c in ("create_time", "symbol") if c not in raw.columns]
    if missing:
        raise ValueError(f"archive metrics csv is missing {missing}; got {list(raw.columns)}")
    rows = [
        {
            "open_time": bucket_open_from_archive(row["create_time"]),
            "symbol": str(row["symbol"]),
            **{c: row.get(c) for c in VALUE_COLUMNS},
        }
        for _, row in raw.iterrows()
    ]
    return _frame(rows)


def parse_rest_rows(
    rows: Iterable[Mapping[str, Any]],
    period: int,
    mapping: Mapping[str, str] | None = None,
    *,
    symbol: str = "",
) -> pd.DataFrame:
    """A REST page, in the same canonical shape, with the close-stamp converted once and here.

    ``mapping`` says which of THIS endpoint's keys are which archive column; the default is the open
    interest page, which is what every caller before 2026-09-12 meant.  ``symbol`` is needed because
    `/futures/data/takerlongshortRatio` is the one page that does not echo it back.
    """
    columns = dict(mapping or REST_TO_ARCHIVE)
    out = []
    for row in rows:
        values = {archive: row.get(rest) for rest, archive in columns.items()}
        out.append(
            {
                "open_time": bucket_open_from_rest(int(row["timestamp"]), period),
                "symbol": str(row.get("symbol") or symbol),
                **{c: values.get(c) for c in VALUE_COLUMNS},
            }
        )
    return _frame(out)


def align_to_bars(metrics: pd.DataFrame, bars: pd.DatetimeIndex, *, interval_ms: int, period_ms: int) -> pd.DataFrame:
    """For each bar, the latest metrics bucket that had CLOSED by the bar's own close.

    The bar opening at 10:00 closes at 11:00, so it may read the bucket opening 10:55 (which closes at
    11:00) and may not read the one opening 11:00 (which closes at 11:05).  Reading by bucket OPEN
    instead would take that second one, and that is the five minutes.

    A bar with nothing closed yet gets NaN rather than the nearest value: a nearest-value fill is how a
    look-ahead gets reintroduced by somebody being helpful.
    """
    columns = [c for c in metrics.columns if c not in ("open_time", "symbol")]
    if metrics.empty:
        return pd.DataFrame(index=bars, columns=columns, dtype=float)
    ordered = metrics.sort_values("open_time")
    closes = ordered["open_time"].to_numpy(dtype="int64") + int(period_ms)
    # `as_unit("ms").asi8`, not `view("int64") // 1_000_000`: a DatetimeIndex carries its own
    # resolution in pandas 2.x, so the raw view is nanoseconds OR microseconds depending on how the
    # index was built - a `DatetimeIndex([Timestamp(...)])` is microseconds - while `Timestamp.value`
    # is always nanoseconds.  The first version divided by a constant and returned NaN for every bar.
    # Dividing by a constant assumes a unit; converting states it.  Same family as the two stamps
    # above, which is why it is spelled out rather than left as an idiom.  (`astype` cannot be used
    # here: pandas refuses tz-aware -> tz-naive.)
    bar_closes = np.asarray(bars.as_unit("ms").view("int64")) + int(interval_ms)
    # searchsorted on the bucket CLOSE, side="right": the last bucket whose close is <= the bar's close
    position = pd.Series(closes).searchsorted(bar_closes, side="right") - 1
    frame = pd.DataFrame(index=bars, columns=columns, dtype=float)
    for column in columns:
        values = ordered[column].to_numpy(dtype=float)
        frame[column] = [values[i] if i >= 0 else float("nan") for i in position]
    return frame
