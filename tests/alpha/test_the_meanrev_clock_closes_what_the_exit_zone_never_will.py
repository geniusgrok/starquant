"""The time stop round 1 asked for on 2026-09-03 and nobody built until 2026-09-17.

`docs/RESEARCH_LOG.md:12` measured meanrev's information and its problem in the same sentence: the 1h
and 4h ICs are significantly positive "但 meanrev 的等名义回测亏损（尾部趋势延续时持仓亏大钱），需要
时间止损与更强趋势门".  :23 and :60 wrote the prescription twice (12-24 bars).  The pit diagnostics on
2026-09-17 reproduced both halves on 206 symbols - 1h cross-sectional IC +0.0159 at NW t 7.64, and an
equal-notional zero-cost Sharpe of -0.62 - and a grep for `max_hold` / `hold_bars` / `time_stop` /
`TimeExit` across the three packages returned nothing.  Fourteen days, two write-ups, zero lines.

What these tests hold is the one property that makes the stop mean anything: **an expired leg stays
flat until the signal lets go.**  The failure mode this signal dies of is a dislocation that keeps
widening, and on such a bar `|z| >= z_entry` is still true - so a stop that emitted one 0.0 and let the
next bar re-open would pay turnover and hold the same tail.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.meanrev import MeanrevParams, _expire, meanrev_scores

INDEX = pd.date_range("2021-01-01", periods=12, freq="h", tz="UTC")


def _frame(values: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame({"A": [np.nan if v is None else v for v in values]}, index=INDEX[: len(values)])


def _out(values: list[float | None], max_hold_bars: int) -> list[float | None]:
    expired = _expire(_frame(values), MeanrevParams(max_hold_bars=max_hold_bars))
    return [None if pd.isna(v) else round(float(v), 4) for v in expired["A"]]


def test_off_by_default_is_bit_for_bit() -> None:
    """Every archived meanrev report was produced without this parameter and must still reproduce."""
    values = [-0.4, None, None, None, None, 0.0, 0.3, None]
    assert _out(values, 0) == [-0.4, None, None, None, None, 0.0, 0.3, None]


def test_the_clock_dates_the_held_position_not_the_scored_bar() -> None:
    """NaN is a hold, so the trade is older than its last scored bar - that is the whole point."""
    assert _out([-0.4, None, None, None, None], 3) == [-0.4, None, None, 0.0, 0.0]


def test_restating_the_same_side_does_not_reset_the_clock() -> None:
    """A dislocation widening 2.0 -> 2.5 adds to the open trade.  It is the case the stop exists for."""
    assert _out([-0.4, None, None, -0.5, None, None], 3) == [-0.4, None, None, 0.0, 0.0, 0.0]


def test_an_expired_leg_stays_flat_while_the_signal_keeps_shouting() -> None:
    """The property the whole rule rests on: re-opening would cost turnover and hold the same tail."""
    assert _out([-0.4, -0.45, -0.5, -0.55, -0.6, -0.65], 2) == [-0.4, -0.45, 0.0, 0.0, 0.0, 0.0]


def test_the_exit_zone_releases_the_leg_and_a_later_entry_is_a_new_trade() -> None:
    assert _out([-0.4, None, 0.0, None, -0.5, None, None, None], 3) == [
        -0.4,
        None,
        0.0,
        None,
        -0.5,
        None,
        None,
        0.0,
    ]


def test_crossing_to_the_other_side_is_a_new_trade() -> None:
    assert _out([-0.4, None, None, 0.4, None, None, None], 3) == [-0.4, None, None, 0.4, None, None, 0.0]


def test_a_sub_threshold_bar_is_not_an_action_and_does_not_reset_the_clock() -> None:
    """`scores_to_targets` ignores |score| < entry_threshold (E-022); the clock must agree with it.

    The sub-threshold bar neither restarts the clock nor counts as flat: the trade opened at bar 0 and
    bar 3 is its fourth bar, so that is where it expires - not bar 2, which is where it would expire if
    0.05 had been read as a fresh action and not as the no-action E-022 says it is.
    """
    assert _out([-0.4, 0.05, None, None, None], 3) == [-0.4, 0.05, None, 0.0, 0.0]


def test_the_clock_agrees_with_the_hold_it_is_dating() -> None:
    """The age is counted on `scores_to_targets(hold=True)`'s position, so the two must not drift."""
    params = MeanrevParams(max_hold_bars=3)
    values = [-0.4, None, None, None, None, None, None, None]
    held = scores_to_targets(_frame(values), params.entry_threshold, hold=True)
    assert [round(float(v), 4) for v in held["A"]] == [-0.4] * 8, "the untouched hold carries it forever"
    stopped = scores_to_targets(_expire(_frame(values), params), params.entry_threshold, hold=True)
    assert [round(float(v), 4) for v in stopped["A"]] == [-0.4, -0.4, -0.4, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_warmup_covers_the_clock_so_a_live_window_can_see_the_open() -> None:
    """A window shorter than the stop would date a position from its own first bar and hold it past."""
    assert MeanrevParams(max_hold_bars=5_000).warmup_bars == 5_001
    assert MeanrevParams().warmup_bars == MeanrevParams(max_hold_bars=0).warmup_bars


def test_a_negative_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="max_hold_bars"):
        MeanrevParams(max_hold_bars=-1)


def test_the_warmup_rows_are_left_alone() -> None:
    """Before the z-score exists there is no position to date, and NaN must not become an exit."""
    close = pd.DataFrame({"A": np.linspace(100.0, 120.0, len(INDEX))}, index=INDEX)
    scores = meanrev_scores(close, MeanrevParams(window=10, vol_window=10, max_hold_bars=2))
    assert scores.iloc[0].isna().all()
