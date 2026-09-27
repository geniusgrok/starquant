"""G10: how many days the point-in-time membership table trails today, and why the alert line is 14.

Operator ruling 2026-09-23: the table stays rebuilt by hand, never on a schedule, because a rebuild moves
a BLOCKING field of the dataset manifest and the armed start then refuses until the evidence is re-issued.
What it gets instead is an alert saying how far behind it has fallen.  Research forward-fills the last
row onto every later bar (``membership_at_bars``), so the lag is the number of days run on a frozen pool.

The fixture is the real table, copied 2026-09-23 from ``.starquant/data/membership.parquet`` (sha256
``aced3630...``, rebuilt 2026-09-18 13:17Z, 2,056 daily rows 2021-01-31 .. 2026-09-17).  The 669 columns
that were never a member are dropped: that moves no row, no row size and no entry or exit, so it moves
no number read here.  The second test re-measures from it every number the threshold's docstring cites,
so the constant cannot drift away from its argument without this file going red.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from starquant_data.pool import MEMBERSHIP_ALERT_DAYS, membership_lag

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pit_membership_2026_09_17" / "membership.parquet"


def _real() -> pd.DataFrame:
    return pd.read_parquet(FIXTURE)


def _missed(members: np.ndarray, k: int) -> np.ndarray:
    """Per frozen row s: names the pit rule holds on day s+k that row s does not."""
    return (members[k:] & ~members[:-k]).sum(axis=1)


def _window_share(members: np.ndarray, k: int, window: int = 30) -> float:
    """Mean share of wrong member slots in a ``window``-day window whose last ``k`` days borrow one row."""
    sizes = np.concatenate([[0], np.cumsum(members.sum(axis=1))])
    frozen = np.arange(max(0, window - 1 - k), len(members) - k)  # every s with a whole window ending s+k
    wrong = sum((members[frozen + j] & ~members[frozen]).sum(axis=1) for j in range(1, k + 1))
    slots = sizes[frozen + k + 1] - sizes[frozen + k + 1 - window]
    return float(np.mean(wrong / slots))


def test_the_real_table_trails_by_whole_utc_days_and_a_fresh_rebuild_reads_one() -> None:
    table = _real()
    rebuilt = membership_lag(table, "2026-09-18T13:17:00Z")  # the rebuild's own day
    assert (rebuilt.status, rebuilt.lag_days, rebuilt.gap_days) == ("OK", 1, 1.0)
    assert rebuilt.last == pd.Timestamp("2026-09-17", tz="UTC")  # the last CLOSED daily bar, yesterday's
    assert membership_lag(table, "2026-09-23T08:26:00Z").lag_days == 6  # the day this was written
    under = membership_lag(table, "2026-09-30T23:59:59Z")
    assert (under.status, under.lag_days) == ("OK", 13)
    first = membership_lag(table, "2026-10-01T00:10:00Z")  # the first hourly run past the line
    assert (first.status, first.lag_days) == ("STALE", 14)
    assert membership_lag(table, "2026-09-23", alert_days=6).status == "STALE"  # the line is a parameter


def test_the_line_is_the_first_lag_past_three_percent_of_a_30_day_window() -> None:
    """Every number in ``MEMBERSHIP_ALERT_DAYS``'s docstring, re-measured on the real table."""
    table = _real()
    members = table.to_numpy(dtype=bool)
    assert round(float(np.abs(np.diff(members.astype(int), axis=0)).sum(axis=1).mean()), 2) == 0.36
    assert round(float(members.sum(axis=1).mean()), 1) == 17.6
    assert round(float(_missed(members, 7).mean()), 1) == 1.2
    assert round(float(_missed(members, 14).mean()), 1) == 2.3

    whole = {k: _window_share(members, k) for k in (13, 14)}
    assert (round(whole[13], 4), round(whole[14], 4)) == (0.0298, 0.0342)
    assert len(np.arange(30 - 1 - 14, len(members) - 14)) == 2_027  # the windows the mean is over
    recent = members[pd.DatetimeIndex(table.index) >= table.index[-1] - pd.Timedelta(days=365)]
    last_year = {k: _window_share(recent, k) for k in (13, 14)}
    assert (round(last_year[13], 4), round(last_year[14], 4)) == (0.0295, 0.0338)

    # RESEARCH_LOG P12 stage 0: a membership change under 3% of slots is too small to backtest.
    assert whole[MEMBERSHIP_ALERT_DAYS - 1] < 0.03 <= whole[MEMBERSHIP_ALERT_DAYS]
    assert last_year[MEMBERSHIP_ALERT_DAYS - 1] < 0.03 <= last_year[MEMBERSHIP_ALERT_DAYS]


def test_a_table_that_cannot_vouch_for_freshness_is_named_and_not_read_as_ok() -> None:
    days = pd.date_range("2026-09-01", periods=3, freq="D", tz="UTC")
    daily = pd.DataFrame({"BTCUSDT": [True] * 3, "ETHUSDT": [True, False, True]}, index=days)
    assert membership_lag(daily, "2026-09-05").status == "OK"
    jittered = daily.set_axis(days + pd.to_timedelta([0, 1, 2], unit="s"))  # median gap: a day and a second
    assert membership_lag(jittered, "2026-09-05").status == "OK"  # is still a daily table

    assert membership_lag(daily.iloc[:0], "2026-09-05").status == "EMPTY"
    assert membership_lag(daily.loc[:, []], "2026-09-05").status == "EMPTY"
    # `pool history` without `--refresh D`: five days old, and every bar in it borrows a row up to a month old
    monthly = pd.DataFrame({"BTCUSDT": [True] * 3}, index=pd.date_range("2026-07-01", periods=3, freq="MS", tz="UTC"))
    reading = membership_lag(monthly, "2026-09-06")
    assert (reading.status, reading.lag_days, reading.gap_days) == ("NOT_DAILY", 5, 31.0)
    # a last row after today means the clock or the table is wrong, so the lag is not a lag
    assert membership_lag(daily, "2026-08-31T23:00:00Z").status == "AHEAD"


def test_the_days_are_utc_days_on_both_sides() -> None:
    """A naive index is UTC, as ``research_panel._membership_table`` reads it; so is a local ``today``.

    The host runs at +08:00.  Normalised in local time instead, 09:00 on 09-05 becomes local midnight -
    16:00 UTC on 09-04 - and the lag reads a day short from 08:00 to 24:00 local, sixteen hours a day.
    """
    naive = pd.DataFrame({"BTCUSDT": [True] * 3}, index=pd.date_range("2026-09-01", periods=3, freq="D"))
    reading = membership_lag(naive, pd.Timestamp("2026-09-05T09:00:00+08:00"))  # 2026-09-05 01:00 UTC
    assert (reading.status, reading.last, reading.lag_days) == ("OK", pd.Timestamp("2026-09-03", tz="UTC"), 2)
