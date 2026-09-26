"""q10 must come OUT of the evidence run, not be pasted next to it.

The adopted decay rule (report 4.2 Ⅰ) compares the live 30-day Sharpe to the backtest's distribution of
same-length windows.  That quantile is only meaningful for the construction it was computed under, so
computing it once and writing it into the registry by hand would go stale, silently, at the next
construction change - the D-026 failure this repository has already had twice.  Emitting it from
`walk_forward.summary()` ties it to the evidence by construction: a new evidence run carries a new q10,
and a construction with no evidence has no q10 rather than a stale one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation.metrics import window_sharpes


def test_the_quantile_is_taken_over_whole_non_overlapping_windows() -> None:
    rng = np.random.default_rng(20260907)
    returns = pd.Series(rng.normal(0.0, 0.01, 7_200))
    windows = window_sharpes(returns, bars_per_window=720, bars_per_year=8760.0)
    assert len(windows) == 10
    values = sorted(v for v in windows if v is not None)
    assert len(values) == 10
    # q10 of a zero-mean series must sit well below zero: that is the whole reason the rule uses a
    # distribution instead of comparing to a point estimate.
    assert float(np.quantile(values, 0.10)) < 0.0


def test_the_summary_carries_the_quantile_and_the_window_count() -> None:
    from starquant_alpha.validation.walk_forward import WalkForwardResult

    rng = np.random.default_rng(1)
    oos = pd.Series(rng.normal(0.0002, 0.01, 3_600))
    result = WalkForwardResult(folds=[], oos_returns=oos, param_keys=["a"])
    out = result.summary(8760.0)
    assert out["oos_windows"] == 5
    assert out["oos_window_sharpe_q10"] is not None
    assert out["oos_window_sharpe_q10"] < out["oos_sharpe"]


def test_too_short_a_history_reports_no_quantile_rather_than_a_made_up_one() -> None:
    from starquant_alpha.validation.walk_forward import WalkForwardResult

    result = WalkForwardResult(
        folds=[], oos_returns=pd.Series(np.random.default_rng(2).normal(0, 0.01, 100)), param_keys=["a"]
    )
    out = result.summary(8760.0)
    assert out["oos_windows"] == 0
    assert out["oos_window_sharpe_q10"] is None
