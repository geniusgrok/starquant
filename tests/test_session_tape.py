"""Manual sessions are the only way the measurement walks a tape."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from btc_perp.config import load_config
from btc_perp.measure import position_intents, walk_tape

pytest.importorskip("numba")


def test_position_intents_close_reduce_and_leave_a_stop_amend() -> None:
    opened = position_intents(0, 0.0, 0.0, 0.0, 1, 0.010, 90.0, 100.0, 10.0)
    assert [(i.side, i.qty) for i in opened] == [(1, 0.010)]
    assert opened[0].take_profit == 1000.0

    closed = position_intents(1, 0.010, 90.0, 100.0, 0, 0.0, 0.0, 0.0, 10.0)
    assert [(i.side, i.qty) for i in closed] == [(0, 0.010)]

    flipped = position_intents(1, 0.010, 90.0, 100.0, -1, 0.008, 110.0, 98.0, 10.0)
    assert [(i.side, i.qty) for i in flipped] == [(0, 0.010), (-1, 0.008)]
    assert flipped[1].take_profit == 9.8

    reopened = position_intents(1, 0.010, 90.0, 100.0, 1, 0.004, 91.0, 101.0, 10.0)
    assert [(i.side, i.qty) for i in reopened] == [(0, 0.010), (1, 0.004)]

    reduced = position_intents(1, 0.010, 90.0, 100.0, 1, 0.004, 91.0, 100.0, 10.0)
    assert [(i.side, i.qty) for i in reduced] == [(-1, 0.006)]

    amended = position_intents(1, 0.010, 90.0, 100.0, 1, 0.010, 92.0, 100.0, 10.0)
    assert [(i.side, i.qty, i.stop) for i in amended] == [(1, 0.0, 92.0)]

    assert position_intents(1, 0.010, 90.0, 100.0, 1, 0.010, 90.0, 100.0, 10.0) == ()


def _book(n: int, close: np.ndarray, hh: np.ndarray, ll: np.ndarray, xh: np.ndarray, xl: np.ndarray):
    return (
        np.full(n, 100.0),
        np.full(n, 100.5),
        np.full(n, 99.5),
        close,
        np.empty(1),
        np.zeros(n),
        np.full(n, 7.0),
        hh,
        ll,
        xh,
        xl,
        np.ones(n, np.int8),
    )


def _hold_then_exit():
    # Bar 5 closes back through the exit channel and stays inside the entry channel,
    # so the long is closed by the later session and is not replaced.
    n = 6
    close = np.full(n, 100.0)
    close[5] = 98.0
    hh = np.full(n, 90.0)
    hh[5] = 100.0
    ll = np.full(n, 10.0)
    xh = np.full(n, 1_000.0)
    xl = np.full(n, 10.0)
    xl[5] = 99.0
    low = np.full(n, 99.5)
    low[5] = 98.0
    arrays = _book(n, close, hh, ll, xh, xl)
    return (*arrays[:2], low, *arrays[3:])


def _flip_same_bar():
    n = 2
    close = np.array([100.0, 98.5])
    hh = np.array([90.0, 200.0])
    ll = np.array([50.0, 99.0])
    xh = np.full(n, 1_000.0)
    xl = np.array([10.0, 99.0])
    low = np.array([99.5, 98.5])
    arrays = _book(n, close, hh, ll, xh, xl)
    return (*arrays[:2], low, *arrays[3:])


def _run_direct(cfg, arrays, equity: np.ndarray):
    from scripts.frontier import run

    o, h, low, c, qv, fund, fx, hh, ll, xh, xl, gate = arrays
    return run(
        o,
        h,
        low,
        c,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        cfg.stop,
        cfg.trail,
        cfg.add_step,
        cfg.max_units,
        cfg.risk,
        cfg.dd_flat,
        cfg.iso_frac,
        cfg.cooldown_hours * 60,
        cfg.ratchet_gain,
        cfg.ratchet_trail,
        cfg.heat,
        gate,
        qv,
        equity,
        np.empty((1, 4)),
    )


def test_minute_slices_match_one_call() -> None:
    from scripts.frontier import initial_state, resume

    cfg = load_config()
    arrays = _hold_then_exit()
    c = arrays[3]
    n = len(c)
    direct_eq = np.empty(n)
    direct = _run_direct(cfg, arrays, direct_eq)
    state = initial_state(float(arrays[6][0]))
    sliced_eq = np.empty(n)
    o, h, low, _c, qv, fund, fx, hh, ll, xh, xl, gate = arrays
    sliced = None
    for i in range(n):
        sliced = resume(
            state,
            i,
            i + 1,
            o,
            h,
            low,
            c,
            fund,
            fx,
            hh,
            ll,
            xh,
            xl,
            cfg.stop,
            cfg.trail,
            cfg.add_step,
            cfg.max_units,
            cfg.risk,
            cfg.dd_flat,
            cfg.iso_frac,
            cfg.cooldown_hours * 60,
            cfg.ratchet_gain,
            cfg.ratchet_trail,
            cfg.heat,
            gate,
            qv,
            sliced_eq,
            np.empty((1, 4)),
        )
    assert sliced is not None
    assert sliced[0] == direct[0]
    assert sliced[1:] == direct[1:]
    assert np.array_equal(sliced_eq, direct_eq)


def test_sessions_match_the_kernel_and_close_on_a_later_session() -> None:
    cfg = load_config()
    arrays = _hold_then_exit()
    n = len(arrays[3])
    direct_eq = np.empty(n)
    direct = _run_direct(cfg, arrays, direct_eq)
    walked = walk_tape(cfg, *arrays)
    assert walked.end == direct[0]
    assert walked.min_ratio == direct[1]
    assert (walked.n_long, walked.n_short, walked.n_stop, walked.min_i) == tuple(direct[2:])
    assert np.array_equal(walked.equity, direct_eq)
    assert walked.n_long == 1
    assert walked.closes == 1
    assert walked.sessions == 2
    assert walked.polls == 120
    assert walked.first_step_clock == (55.0, 55.0)
    assert walked.position_at_session_end[0] != 0.0
    assert walked.position_at_session_end[1] == 0.0
    assert walked.submits == 2


def test_a_same_bar_reversal_is_a_close_and_then_an_entry() -> None:
    cfg = load_config()
    arrays = _flip_same_bar()
    n = len(arrays[3])
    direct_eq = np.empty(n)
    direct = _run_direct(cfg, arrays, direct_eq)
    walked = walk_tape(cfg, *arrays)
    assert walked.end == direct[0]
    assert np.array_equal(walked.equity, direct_eq)
    assert (walked.n_long, walked.n_short) == (int(direct[2]), int(direct[3]))
    assert walked.n_long == 1
    assert walked.n_short == 1
    assert walked.closes == 1
    assert walked.submits == 3
    assert walked.sessions == 1
    assert walked.first_step_clock == (55.0,)
    assert walked.position_at_session_end[0] < 0.0


def test_a_poll_that_does_not_divide_a_minute_is_refused() -> None:
    cfg = replace(load_config(), poll_seconds=7)
    arrays = _hold_then_exit()
    with pytest.raises(RuntimeError, match="poll_seconds"):
        walk_tape(cfg, *arrays)
