"""#8, block 2: this symbol's own mean return in this hour of the UTC day.

The hypothesis is that crypto has a repeating intraday shape - funding settles at 00/08/16Z, sessions
open and close - and that the shape differs by symbol.  Per symbol is the point and also the risk: 24
buckets per name is a lot of parameters chasing a weak effect, which is why it enters as a candidate
rather than as a belief.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining.expr import Dim, ExprError, HourOfDay
from starquant_alpha.panel import Panel
from tests.alpha.test_causality import _bit_for_bit


def _panel(bars: int = 24 * 80, seed: int = 7) -> Panel:
    index = pd.date_range("2026-01-01", periods=bars, freq="1h", tz="UTC")
    rng = np.random.default_rng(seed)
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.005, (bars, 3)), axis=0)),
        index=index,
        columns=["A", "B", "C"],
    )
    volume = pd.DataFrame(1.0, index=index, columns=close.columns)
    return Panel(close=close, open=close, high=close, low=close, volume=volume, interval="1h")


def test_it_is_a_mean_return_so_the_type_system_makes_every_shape_normalise_it() -> None:
    assert HourOfDay(14).dim is Dim.RETURN


def test_one_occurrence_is_not_an_average() -> None:
    with pytest.raises(ExprError):
        HourOfDay(1)


def test_the_estimate_excludes_the_bar_it_scores() -> None:
    """The property that keeps this from being `ret(1)` wearing a seasonality label.

    The causality contract only forbids reading bars AFTER t.  A mean that included bar t's own
    return would obey it and still be part momentum - and the family multiplies this leaf BY
    momentum, so without the shift that interaction would be partly a squared return, which is a
    volatility estimate rather than a seasonal one.
    """
    panel = _panel()
    scored = HourOfDay(14).evaluate(panel)
    returns = panel.close.pct_change()

    row = len(panel.close.index) - 1
    hour = panel.close.index[row].hour
    same_hour = np.asarray(panel.close.index.hour) == hour
    history = returns.loc[same_hour].iloc[-15:-1]  # the 14 occurrences BEFORE this one
    expected = history.mean()

    _bit_for_bit(scored.iloc[row], expected, check_names=False)
    # ...and it is NOT the mean that includes this bar
    including = returns.loc[same_hour].iloc[-14:].mean()
    assert not np.allclose(scored.iloc[row].to_numpy(), including.to_numpy())


def test_no_node_reads_the_future() -> None:
    """The shared causality contract: replacing data after a cutoff moves nothing before it."""
    panel = _panel()
    cutoff = 1200
    rng = np.random.default_rng(99)
    tampered = panel.close.copy()
    tampered.iloc[cutoff:] *= 1.0 + rng.normal(0, 0.2, size=tampered.iloc[cutoff:].shape)

    before = HourOfDay(14).evaluate(panel).iloc[:cutoff]
    after = (
        HourOfDay(14)
        .evaluate(Panel(**{**vars(panel), "close": tampered, "open": tampered, "high": tampered, "low": tampered}))
        .iloc[:cutoff]
    )
    _bit_for_bit(before, after)


def test_nothing_is_scored_before_the_hour_has_happened_enough_times() -> None:
    days = 14
    scored = HourOfDay(days).evaluate(_panel())
    first = int(scored.notna().all(axis=1).argmax())
    assert first == days * 24 + 1, "one occurrence per day, plus the one the shift steps back over"
    assert scored.iloc[: days * 24].isna().all().all()
    assert HourOfDay(days).lookback() >= first, "lookback must reserve at least what warmup consumes"


def test_the_effect_is_per_symbol_because_a_panel_wide_one_could_not_be_traded() -> None:
    """A single hour effect shared by every name is constant across the row, and
    `cross_sectional_rank` flattens a constant row to nothing a book can hold."""
    scored = HourOfDay(14).evaluate(_panel()).dropna()
    spread = scored.max(axis=1) - scored.min(axis=1)
    assert (spread > 0).all(), "every scored row must vary across symbols"


def test_every_arm_of_the_pre_registered_grid_is_actually_searchable() -> None:
    """The first draft's third arm was silently dropped, and a rejection tally is not a failure.

    `hod(60)` reserves `(60 + 1) * 24 = 1464` against a `max_lookback` of 1400, so all eighteen of
    its shapes left as `too_long` while the grid still said three windows.  A pre-registration that
    reports three and searches two is not a pre-registration.
    """
    import inspect

    from starquant_alpha.mining.search import enumerate_candidates

    grid = inspect.signature(enumerate_candidates).parameters["hod_days"].default
    cap = inspect.signature(enumerate_candidates).parameters["max_lookback"].default
    for days in grid:
        assert HourOfDay(days).lookback() <= cap, f"hod({days}) cannot be searched under max_lookback {cap}"

    result = enumerate_candidates(include_funding=False, include_panel_nodes=False, include_metrics=False)
    assert result.rejected["too_long"] == 0
