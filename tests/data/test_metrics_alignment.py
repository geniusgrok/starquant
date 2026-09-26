"""DL-D2 / KILL-Q11: two sources, two timestamp conventions, and a silent 5-minute look-ahead.

Research eats the T+1 daily archive; live can only read the 30-day REST window.  Measured against the
venue on 2026-09-07, they carry the SAME numbers under DIFFERENT stamps:

    archive `create_time` == rest `timestamp` - 5 minutes     (166/166 exact at -5min; 0/165 at 0)

So a join on `create_time == timestamp` is wrong for every bucket, and wrong in the direction that
flatters: research would see a value five minutes before live could have read it.  One bucket's open
interest moves a median 0.090% and a p95 1.15% - small, systematic, and always favourable.

A second measurement settles which stamp is which, because guessing would be the same mistake one
level down: re-reading the three newest REST buckets six minutes apart returned byte-identical values,
so the newest row is a COMPLETE bucket and its timestamp is the bucket CLOSE.  The archive's is
therefore the bucket OPEN.  There is no partial-bucket hazard.

This module fixes ONE canonical stamp - `open_time`, the same convention the kline store already uses -
and makes the look-ahead unrepresentable: what a bar may read is decided by the bucket's CLOSE, never
its open.
"""

from __future__ import annotations

import pandas as pd
import pytest

FIVE_MIN_MS = 5 * 60 * 1000
HOUR_MS = 60 * 60 * 1000


def test_the_two_sources_land_on_one_stamp() -> None:
    """The whole point: the same bucket from either source is the same row."""
    from starquant_data.metrics import bucket_open_from_archive, bucket_open_from_rest

    # measured pair: archive 2026-09-05 10:15:00 carries the value REST stamps 10:20:00
    archive = bucket_open_from_archive("2026-09-05 10:15:00")
    rest = bucket_open_from_rest(pd.Timestamp("2026-09-05 10:20:00", tz="UTC").value // 1_000_000, FIVE_MIN_MS)

    assert archive == rest


def test_a_naive_join_would_have_been_wrong_for_every_bucket() -> None:
    """Pinning the defect itself, so a future 'simplification' back to it fails loudly."""
    from starquant_data.metrics import bucket_open_from_rest

    stamp = pd.Timestamp("2026-09-05 10:20:00", tz="UTC").value // 1_000_000

    assert bucket_open_from_rest(stamp, FIVE_MIN_MS) != stamp


def test_a_bucket_is_not_usable_before_it_closes() -> None:
    """The look-ahead guard.  A bucket [T, T+5m) does not exist until T+5m."""
    from starquant_data.metrics import usable_from_ms

    open_ms = pd.Timestamp("2026-09-05 10:15:00", tz="UTC").value // 1_000_000

    assert usable_from_ms(open_ms, FIVE_MIN_MS) == open_ms + FIVE_MIN_MS


def test_an_hourly_bar_reads_only_buckets_that_closed_by_its_own_close() -> None:
    """The join research and live must both use.

    A bar opening 10:00 closes at 11:00.  The 10:55 bucket closes at 11:00 and counts; the 11:00
    bucket closes at 11:05 and does not - taking it would be the five minutes this file is about.
    """
    from starquant_data.metrics import align_to_bars

    opens = [pd.Timestamp("2026-09-05 10:00", tz="UTC").value // 1_000_000 + i * FIVE_MIN_MS for i in range(14)]
    metrics = pd.DataFrame({"open_time": opens, "sum_open_interest": range(len(opens))})
    bars = pd.DatetimeIndex([pd.Timestamp("2026-09-05 10:00", tz="UTC"), pd.Timestamp("2026-09-05 11:00", tz="UTC")])

    aligned = align_to_bars(metrics, bars, interval_ms=HOUR_MS, period_ms=FIVE_MIN_MS)

    # the 10:00 bar closes at 11:00; the last bucket closing by then opened at 10:55 (index 11).
    # 12 opens at 11:00 and closes at 11:05 - taking it would be the five minutes.
    assert aligned.loc[bars[0], "sum_open_interest"] == 11
    # the 11:00 bar closes at 12:00, by which point every bucket in this frame has closed (13 is last)
    assert aligned.loc[bars[1], "sum_open_interest"] == 13


def test_a_bar_with_no_closed_bucket_yet_gets_nothing_rather_than_the_nearest() -> None:
    """Nearest-value fill is how a look-ahead gets reintroduced by someone being helpful."""
    from starquant_data.metrics import align_to_bars

    later = pd.Timestamp("2026-09-05 12:00", tz="UTC").value // 1_000_000
    metrics = pd.DataFrame({"open_time": [later], "sum_open_interest": [7]})
    bars = pd.DatetimeIndex([pd.Timestamp("2026-09-05 10:00", tz="UTC")])

    aligned = align_to_bars(metrics, bars, interval_ms=HOUR_MS, period_ms=FIVE_MIN_MS)

    assert pd.isna(aligned.loc[bars[0], "sum_open_interest"])


def test_the_archive_csv_parses_to_the_canonical_shape() -> None:
    from starquant_data.metrics import parse_archive_csv

    csv = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2026-09-05 10:15:00,BTCUSDT,107239.507,1.0,2.0,3.0,4.0,5.0\n"
    )

    frame = parse_archive_csv(csv)

    assert list(frame["open_time"]) == [pd.Timestamp("2026-09-05 10:15:00", tz="UTC").value // 1_000_000]
    assert frame["sum_open_interest"].iloc[0] == pytest.approx(107239.507)
    assert "create_time" not in frame.columns  # one convention, not two


def test_rest_rows_parse_to_the_same_shape() -> None:
    from starquant_data.metrics import parse_rest_rows

    stamp = pd.Timestamp("2026-09-05 10:20:00", tz="UTC").value // 1_000_000
    frame = parse_rest_rows([{"symbol": "BTCUSDT", "sumOpenInterest": "107239.507", "timestamp": stamp}], FIVE_MIN_MS)

    assert list(frame["open_time"]) == [pd.Timestamp("2026-09-05 10:15:00", tz="UTC").value // 1_000_000]
    assert frame["sum_open_interest"].iloc[0] == pytest.approx(107239.507)


def test_the_two_parsers_agree_row_for_row() -> None:
    """The regression that would have caught the defect: same bucket, two sources, one row."""
    from starquant_data.metrics import parse_archive_csv, parse_rest_rows

    csv = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2026-09-05 10:15:00,BTCUSDT,107239.507,1.0,2.0,3.0,4.0,5.0\n"
    )
    stamp = pd.Timestamp("2026-09-05 10:20:00", tz="UTC").value // 1_000_000
    rest = parse_rest_rows([{"symbol": "BTCUSDT", "sumOpenInterest": "107239.507", "timestamp": stamp}], FIVE_MIN_MS)

    a = parse_archive_csv(csv)
    assert a["open_time"].tolist() == rest["open_time"].tolist()
    assert a["sum_open_interest"].tolist() == rest["sum_open_interest"].tolist()


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_the_bar_index_resolution_does_not_change_the_answer(unit: str) -> None:
    """A DatetimeIndex carries its own resolution in pandas 2.x.

    The first implementation did `bars.view("int64") // 1_000_000`, which is right for nanoseconds and
    silently wrong for microseconds - and a `DatetimeIndex([Timestamp(...)])` is microseconds.  Every
    bar came back NaN.  Same family as the two stamps this module exists for: a unit assumed rather
    than converted.
    """
    from starquant_data.metrics import align_to_bars

    opens = [pd.Timestamp("2026-09-05 10:00", tz="UTC").value // 1_000_000 + i * FIVE_MIN_MS for i in range(14)]
    metrics = pd.DataFrame({"open_time": opens, "sum_open_interest": range(len(opens))})
    bars = pd.DatetimeIndex(
        [pd.Timestamp("2026-09-05 10:00", tz="UTC"), pd.Timestamp("2026-09-05 11:00", tz="UTC")]
    ).as_unit(unit)

    aligned = align_to_bars(metrics, bars, interval_ms=HOUR_MS, period_ms=FIVE_MIN_MS)

    assert aligned["sum_open_interest"].iloc[0] == 11
