"""DL-D4 / T-D4-1: the metrics columns reach a signal, and the look-ahead cannot come with them.

The five minutes is the whole subject.  Measured against the venue on 2026-09-07, the T+1 archive's
`create_time` equals the REST `timestamp` minus five minutes on 166 of 166 buckets, so a join on
equal stamps would let research see a value five minutes before the loop could have read it - a median
0.090% of open interest, p95 1.15%, small, systematic and always favourable.  KILL-027's shape.

`starquant_data.metrics.align_to_bars` is where that rule lives, together with the measurement.  What
this file holds is the boundary: `starquant_alpha` may not import `starquant_data`, so `Panel` takes ALREADY
ALIGNED frames and REFUSES anything else rather than reindexing helpfully.  A reindex here would be a
second implementation of a look-ahead rule, and the two would drift.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining.expr import ExprError, LongShortRatio, OpenInterest, Ret
from starquant_alpha.mining.search import to_signal
from starquant_alpha.panel import Panel

BARS = pd.date_range("2024-01-01", periods=200, freq="h", tz="UTC")
SYMBOLS = ("AAAUSDT", "BBBUSDT")


def _frames() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(11)
    out = {}
    for symbol in SYMBOLS:
        close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.005, len(BARS))))
        out[symbol] = pd.DataFrame(
            {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1_000.0},
            index=BARS,
        )
    return out


def _metrics(index: pd.DatetimeIndex = BARS) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(12)
    return {
        "sum_open_interest": pd.DataFrame(
            rng.uniform(1_000, 2_000, size=(len(index), len(SYMBOLS))), index=index, columns=list(SYMBOLS)
        ),
        "count_long_short_ratio": pd.DataFrame(
            rng.uniform(1.5, 2.5, size=(len(index), len(SYMBOLS))), index=index, columns=list(SYMBOLS)
        ),
    }


def test_a_frame_that_is_not_on_the_bar_index_is_refused_rather_than_reindexed() -> None:
    """The refusal that makes "aligned by the caller" safe.  Being helpful here restores the bug."""
    shifted = BARS + pd.Timedelta(minutes=5)
    with pytest.raises(ValueError, match="align_to_bars"):
        Panel.from_frames(_frames(), "1h", metrics=_metrics(shifted))


def test_a_panel_without_metrics_answers_none_rather_than_zero() -> None:
    """A metric nobody ingested and a metric that is genuinely zero are different facts."""
    panel = Panel.from_frames(_frames(), "1h")
    assert panel.metric("sum_open_interest") is None
    with pytest.raises(ExprError, match="does not carry"):
        OpenInterest(24).evaluate(panel)


def test_the_leaves_read_the_columns_and_say_that_they_do() -> None:
    panel = Panel.from_frames(_frames(), "1h", metrics=_metrics())
    assert OpenInterest(24).reads_metrics() == ("sum_open_interest",)
    assert LongShortRatio(24).reads_metrics() == ("count_long_short_ratio",)
    assert Ret(24).reads_metrics() == ()
    for node in (OpenInterest(24), LongShortRatio(24)):
        values = node.evaluate(panel)
        assert values.shape == panel.close.shape
        assert values.iloc[-1].notna().all(), f"{node} produced nothing at the right edge"


def test_a_metrics_reading_candidate_tells_the_loop_so() -> None:
    """`metrics_refusal` has nothing to refuse on if the spec does not declare the need.

    The live loop can only read a 30-day REST window while research eats a T+1 archive, so a candidate
    that reads a column and says it does not is the KILL-027 shape one field over from the funding
    case that already has this guard.
    """
    from starquant_alpha.mining.search import Candidate

    def candidate(node: object) -> Candidate:
        return Candidate(expr=node, hash=node.canonical_hash(), lookback=node.lookback(), complexity=node.complexity())

    reading, plain = candidate(OpenInterest(24)), candidate(Ret(24))
    assert to_signal(reading).needs_metrics is not None
    assert to_signal(reading).needs_metrics({}) is True
    assert to_signal(plain).needs_metrics({}) is False


def test_reads_metrics_does_not_move_any_existing_expression_hash() -> None:
    """It is a METHOD, not a field: `signature()` reads `vars(self)`, and a field would rehash the world."""
    assert Ret(24).canonical_hash() == Ret(24).canonical_hash()
    assert "reads_metrics" not in str(Ret(24).signature())
    assert OpenInterest(24).canonical_hash() != LongShortRatio(24).canonical_hash()


def test_the_open_interest_leaf_is_a_change_and_the_ratio_leaf_is_a_deviation() -> None:
    """Both are relative on purpose: a level leaf would rank symbols by contract size or venue habit."""
    flat = {
        name: pd.DataFrame(value, index=BARS, columns=list(SYMBOLS))
        for name, value in (("sum_open_interest", 1_500.0), ("count_long_short_ratio", 2.0))
    }
    panel = Panel.from_frames(_frames(), "1h", metrics=flat)
    assert OpenInterest(24).evaluate(panel).iloc[-1].abs().max() == pytest.approx(0.0)
    assert LongShortRatio(24).evaluate(panel).iloc[-1].abs().max() == pytest.approx(0.0)
