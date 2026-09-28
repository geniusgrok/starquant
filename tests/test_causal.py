"""Causal fill timing. The full-sample numbers are produced by ``python -m btc_perp causal``."""

from __future__ import annotations

import numpy as np
import pytest

from btc_perp.causal import validate_minutes
from btc_perp.costs import ENTRY_SCALE, ENTRY_SCALE_BELOW, FLATTEN_RATIO


def test_a_gap_or_a_bad_bar_is_unverified() -> None:
    ts = np.array([0, 60_000, 180_000], np.int64)
    price = np.array([1.0, 1.0, 1.0])
    assert validate_minutes(ts, price, price, price, price, price)
    ts = np.array([0, 60_000], np.int64)
    high = np.array([1.0, 1.0])
    low = np.array([2.0, 1.0])
    assert any("low" in item for item in validate_minutes(ts, high, high, low, high, high))


def test_defer_fills_on_the_next_open_and_not_on_the_signal_close() -> None:
    from scripts.frontier import initial_state, resume, run

    opens = np.array([100.0, 110.0, 110.0])
    closes = np.array([100.0, 110.0, 110.0])
    highs = np.maximum(opens, closes)
    lows = np.minimum(opens, closes)
    hh = np.array([50.0, 1.0e9, 1.0e9])
    ll = np.full(3, 1.0)
    xh = np.full(3, 1.0e9)
    xl = np.full(3, 1.0)
    fund = np.zeros(3)
    fx = np.full(3, 7.0)
    gate = np.ones(3, np.int8)
    qv = np.empty(1)
    eq_out = np.empty(1)
    trace = np.zeros((3, 5))
    run(
        opens,
        highs,
        lows,
        closes,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        0.05,
        0.30,
        0.05,
        1,
        0.50,
        0.99,
        1.0,
        0,
        0.0,
        0.0,
        0.0,
        FLATTEN_RATIO,
        ENTRY_SCALE_BELOW,
        ENTRY_SCALE,
        gate,
        qv,
        eq_out,
        trace,
    )
    assert trace[1, 4] == pytest.approx(100.01, rel=1e-4)

    state = initial_state(7.0)
    deferred = np.zeros((3, 5))
    resume(
        state,
        0,
        3,
        opens,
        highs,
        lows,
        closes,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        0.05,
        0.30,
        0.05,
        1,
        0.50,
        0.99,
        1.0,
        0,
        0.0,
        0.0,
        0.0,
        0.0,
        ENTRY_SCALE_BELOW,
        ENTRY_SCALE,
        gate,
        qv,
        eq_out,
        deferred,
        1,
    )
    assert deferred[0, 0] == 0.0
    assert deferred[1, 0] == 1.0
    assert deferred[1, 4] == pytest.approx(110.011, rel=1e-4)
    assert state[17] == 0.0


def test_a_signal_on_the_last_bar_does_not_fill() -> None:
    from scripts.frontier import initial_state, resume

    prices = np.array([100.0])
    state = initial_state(7.0)
    trace = np.zeros((1, 5))
    resume(
        state,
        0,
        1,
        prices,
        prices,
        prices,
        prices,
        np.zeros(1),
        np.full(1, 7.0),
        np.array([50.0]),
        np.full(1, 1.0),
        np.full(1, 1.0e9),
        np.full(1, 1.0),
        0.05,
        0.30,
        0.05,
        1,
        0.50,
        0.99,
        1.0,
        0,
        0.0,
        0.0,
        0.0,
        0.0,
        ENTRY_SCALE_BELOW,
        ENTRY_SCALE,
        np.ones(1, np.int8),
        np.empty(1),
        np.empty(1),
        trace,
        1,
    )
    assert trace[0, 0] == 0.0
    assert state[17] == 1.0
