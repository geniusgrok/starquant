"""T-A02 / T-A03: no lookahead in signals; backtest executes at t+1 and random signals do not earn."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.panel import Panel
from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores


def _shuffle_future(panel: Panel, cutoff: int, seed: int = 7) -> Panel:
    rng = np.random.default_rng(seed)
    fields = {}
    for field in ("open", "high", "low", "close", "volume"):
        frame = getattr(panel, field).copy()
        future = frame.iloc[cutoff:].to_numpy().copy()
        rng.shuffle(future, axis=0)
        frame.iloc[cutoff:] = future * rng.uniform(0.5, 1.5, size=future.shape)
        fields[field] = frame
    return Panel(interval=panel.interval, **fields)


def _bit_for_bit(
    before: pd.DataFrame | pd.Series,
    after: pd.DataFrame | pd.Series,
    *,
    check_names: bool = True,
    check_freq: bool = True,
) -> None:
    """How a test here says "bit for bit": `check_exact` for a readable first difference, then the uint64 view.

    Not `assert_frame_equal`'s default, which compares floats at rtol 1e-5 / atol 1e-8.  On the venv's
    pandas 3.0.5 `df` against `df + 1e-9` passes, so any leak inside that tolerance passed every
    causality test that compared at the default.  `scratchpad/causal_tests_bit_for_bit_planted_leaks.py`
    measured it on the 13 comparisons that did until 2026-09-23 - the signal suite's 11 cases, tsmom and
    GARCH: a leak of 1e-9 of the next bar's return, which moves the last bar before the cutoff by 4e-11 to
    8e-10, passed all 13 at the default and fails all 13 here.  The last test in this file keeps one.
    The same day 26 more call sites moved here: 11 more shuffled- or truncated-future comparisons, and 15
    whose name or docstring already said bit for bit, exactly, or "an identity rather than a tolerance".

    `check_exact` still treats every NaN as the same NaN and 0.0 as -0.0; the view does not, which is the
    difference between "the same numbers" and "the same computation".  So a comparison against a negation
    does not belong here: `-x` flips the sign bit of every NaN and every zero.  `test_mining.py`'s
    reversal test compares one, and stays on `assert_frame_equal`.

    The view is taken column by column, on every float64 column.  A frame that mixes dtypes - an exit
    overlay's `events`, with its prices beside symbols and timestamps - becomes `object` under
    `to_numpy()`, and one whole-frame view would skip its floats.

    `check_names` and `check_freq` pass through.  They relax labels, never values or their order, so the
    view still compares the cells `check_exact` did.
    """
    if isinstance(before, pd.Series):
        pd.testing.assert_series_equal(before, after, check_exact=True, check_names=check_names, check_freq=check_freq)
    else:
        pd.testing.assert_frame_equal(before, after, check_exact=True, check_names=check_names, check_freq=check_freq)
    columns = [frame.to_frame() if isinstance(frame, pd.Series) else frame for frame in (before, after)]
    for (name, left), (_, right) in zip(columns[0].items(), columns[1].items(), strict=True):
        if left.dtype == np.float64:
            assert np.array_equal(left.to_numpy().view(np.uint64), right.to_numpy().view(np.uint64)), (
                f"{name!r}: equal values, different bits"
            )


def test_tsmom_is_causal(august_panel: Panel) -> None:
    cutoff = 300
    params = TsmomParams(vol_window=100)
    before = tsmom_scores(august_panel.close, params).iloc[:cutoff]
    after = tsmom_scores(_shuffle_future(august_panel, cutoff).close, params).iloc[:cutoff]
    _bit_for_bit(before, after)


def test_backtest_executes_next_bar(august_panel: Panel) -> None:
    idx = august_panel.close.index
    weights = pd.DataFrame(0.0, index=idx, columns=august_panel.symbols)
    weights.iloc[100, 0] = 1.0  # decide at bar 100 on BTC
    result = run_backtest(august_panel, weights, CostModel(turnover_bps=0.0), execution="open_to_close")
    executed = result.weights
    assert executed.loc[idx[101], "BTCUSDT"] == 1.0
    assert executed.loc[idx[100], "BTCUSDT"] == 0.0 if idx[100] in executed.index else True
    expected = august_panel.close.loc[idx[101], "BTCUSDT"] / august_panel.open.loc[idx[101], "BTCUSDT"] - 1.0
    assert abs(result.gross.loc[idx[101], "BTCUSDT"] - expected) < 1e-12
    assert result.gross.drop(index=idx[101]).abs().sum().sum() == 0.0


def test_random_signals_do_not_earn_after_costs(august_panel: Panel) -> None:
    rng = np.random.default_rng(42)
    nets = []
    for _ in range(50):
        weights = (
            pd.DataFrame(
                rng.choice([-1.0, 0.0, 1.0], size=august_panel.close.shape),
                index=august_panel.close.index,
                columns=august_panel.symbols,
            )
            / 4.0
        )
        nets.append(run_backtest(august_panel, weights, CostModel(turnover_bps=7.0)).summary()["net_return"])
    assert float(np.mean(nets)) < 0.0


def test_a_look_ahead_below_the_default_tolerance_is_caught_only_bit_for_bit(august_panel: Panel) -> None:
    """Why `test_tsmom_is_causal` compares bits: a small enough look-ahead passes the default comparison.

    The leak adds 1e-9 of the next bar's return, so it reaches one compared bar - the last before the
    cutoff - and moves it by at most 6.4e-10, against the default atol of 1e-8.
    """
    cutoff = 300
    params = TsmomParams(vol_window=100)

    def leaky(close: pd.DataFrame) -> pd.DataFrame:
        return tsmom_scores(close, params) + 1e-9 * close.pct_change().shift(-1)

    before = leaky(august_panel.close).iloc[:cutoff]
    after = leaky(_shuffle_future(august_panel, cutoff).close).iloc[:cutoff]
    pd.testing.assert_frame_equal(before, after)
    _bit_for_bit(before.iloc[:-1], after.iloc[:-1])
    with pytest.raises(AssertionError):
        _bit_for_bit(before, after)
