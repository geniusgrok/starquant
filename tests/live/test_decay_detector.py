"""The edge-decay rule the operator adopted on 2026-09-07 (report section 4.2 Ⅰ, ruling in 12.9).

The report asked what statistic would detect decay in the live period and proposed one; it went
unanswered until now.  The adopted rule: **M-010's 30-day rolling Sharpe against the backtest's
distribution of same-length windows, two consecutive windows below q10 -> review.**

Three things are pinned here rather than left to the reader, because each of them is a way the rule
would quietly get looser after the fact:

* **Windows do not overlap.**  "Two consecutive 30-day windows" with a daily step is two observations
  sharing 29 days of data - very nearly one observation, and it fires far more often than the design
  intends.  Non-overlapping means the trigger costs 60 days of evidence.
* **The comparison is to an empirical distribution, not to a point estimate.**  A strategy with a 1.7
  annualised Sharpe has enormous dispersion over 30 days; its q10 is likely well below zero.  Comparing
  the live number to `oos_sharpe` with a normal standard error is a different and much weaker test -
  `drift_vs_expectation` already does that one, and the two coexist rather than replace each other.
* **A missing q10 is INSUFFICIENT_DATA, never OK.**  The quantile has to come from the same construction
  and is not computed yet.  Reporting OK because there is nothing to compare against is how a detector
  that has never worked looks healthiest - the `metrics_parity` `rate: None` lesson.

It cannot fire before roughly 2026-11-05: the construction froze on 2026-09-06 and the rule needs two
whole non-overlapping windows after that.  Writing it now, before any window exists, is the point -
a decay rule authored after seeing the decay is not a rule.
"""

from __future__ import annotations

import math

from starquant_live.reports import decay_verdict, window_sharpes


def test_windows_do_not_overlap_and_a_partial_tail_is_dropped() -> None:
    values = [0.01] * 250
    out = window_sharpes(values, bars_per_window=100, bars_per_year=8760.0)
    assert len(out) == 2  # 250 // 100, the trailing 50 bars are not a window


def test_a_window_without_dispersion_is_not_given_a_sharpe() -> None:
    """A constant series has no ratio; 3e17 is what the naive version returned (the _has_dispersion bug)."""
    out = window_sharpes([0.01] * 200, bars_per_window=100, bars_per_year=8760.0)
    assert all(v is None or math.isfinite(v) for v in out)


def test_two_consecutive_windows_below_q10_ask_for_a_review() -> None:
    out = decay_verdict(live_windows=[0.9, -0.4, -0.5], q10=-0.3)
    assert out["status"] == "REVIEW"
    assert out["below"] == 2


def test_one_window_below_q10_is_not_enough() -> None:
    assert decay_verdict(live_windows=[0.9, 0.2, -0.5], q10=-0.3)["status"] == "OK"


def test_a_recovery_resets_the_count() -> None:
    """Two bad windows then a good one is not "two consecutive"; the rule is about the latest run."""
    assert decay_verdict(live_windows=[-0.5, -0.4, 0.8], q10=-0.3)["status"] == "OK"


def test_a_missing_q10_is_insufficient_data_and_never_ok() -> None:
    out = decay_verdict(live_windows=[-0.9, -0.9], q10=None)
    assert out["status"] == "INSUFFICIENT_DATA"
    assert "q10" in out["why"]


def test_too_few_windows_is_insufficient_data_and_never_ok() -> None:
    out = decay_verdict(live_windows=[-0.9], q10=-0.3)
    assert out["status"] == "INSUFFICIENT_DATA"
    assert out["status"] != "OK"
