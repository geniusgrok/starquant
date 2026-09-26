"""DL-R3: the acceptance the FWER gate shipped without, and the N_eff it owes.

KILL-R25 made the objection that the 2026-09-06 gate never answered: its own acceptance condition
was "125 independent nulls clear the gate at most 5% of the time", and that is true *by
construction* - the threshold solves ``Phi(x)^N = 1 - alpha`` for exactly that null.  The ledger's
trials are not independent (24 exact duplicates and a long tail of near-duplicates), so the test
that means something is the correlated one, and the property it should establish is the one the
gate's docstring claims: with correlated trials the gate is **conservative**, not merely correct.

``effective_trials`` is the other half of the debt.  It is reported, never gated - substituting an
N_eff for N would *lower* the bar, and lowering a bar on the strength of an estimator nobody has
validated on this ledger is the mistake this whole round exists to stop.  Reported, it lets a
reader see how much of the search cost is duplication.
"""

from __future__ import annotations

import numpy as np
import pytest

from starquant_alpha.validation.multiple_testing import (
    _li_ji_count,
    effective_trials,
    max_sharpe_quantile,
    sampling_variance,
    sharpe_per_period,
)


def _correlated_nulls(rng: np.random.Generator, n_trials: int, n_obs: int, rho: float) -> np.ndarray:
    """``n_obs x n_trials`` zero-mean noise with a common factor: pairwise correlation ``rho``."""
    factor = rng.standard_normal((n_obs, 1))
    idio = rng.standard_normal((n_obs, n_trials))
    return math_sqrt(rho) * factor + math_sqrt(1.0 - rho) * idio


def math_sqrt(x: float) -> float:
    return float(np.sqrt(x))


def _false_positive_rate(rho: float, *, n_trials: int, n_obs: int, replications: int, seed: int) -> float:
    """How often the best of ``n_trials`` pure-noise curves clears the gate."""
    rng = np.random.default_rng(seed)
    variance = sampling_variance(0.0, n_obs)
    threshold = max_sharpe_quantile(n_trials, variance, alpha=0.05)
    cleared = 0
    for _ in range(replications):
        curves = _correlated_nulls(rng, n_trials, n_obs, rho)
        best = max(sharpe_per_period(curves[:, i]) or 0.0 for i in range(n_trials))
        cleared += best >= threshold
    return cleared / replications


def test_independent_nulls_clear_the_gate_at_the_declared_alpha() -> None:
    """The construction check: it has to land on alpha before the correlated case means anything."""
    rate = _false_positive_rate(0.0, n_trials=125, n_obs=1500, replications=300, seed=7)

    assert 0.02 <= rate <= 0.09  # 5% +- Monte-Carlo error at 300 replications


def test_correlated_nulls_clear_the_gate_less_often_than_alpha() -> None:
    """The acceptance KILL-R25 asked for: with a real ledger's duplication the gate is conservative.

    This is the direction the gate's docstring claims and the safe one to be wrong in: using the raw
    ledger count asks for more than the evidence strictly requires.
    """
    rate = _false_positive_rate(0.5, n_trials=125, n_obs=1500, replications=300, seed=11)

    assert rate <= 0.05


def test_a_ledger_of_duplicates_is_the_extreme_case() -> None:
    """rho = 0.95 is the shape of 24 exact duplicates plus near-duplicates: barely any family at all."""
    rate = _false_positive_rate(0.95, n_trials=125, n_obs=1500, replications=300, seed=13)

    assert rate <= 0.01


def test_effective_trials_counts_independent_columns() -> None:
    rng = np.random.default_rng(3)
    independent = rng.standard_normal((2000, 40))

    assert effective_trials(independent) == pytest.approx(40, rel=0.15)


def test_effective_trials_collapses_a_wall_of_copies_to_one() -> None:
    rng = np.random.default_rng(5)
    single = rng.standard_normal((2000, 1))
    copies = np.repeat(single, 40, axis=1)

    assert effective_trials(copies) == pytest.approx(1.0, abs=0.5)


def test_the_count_does_not_hinge_on_which_way_the_eigensolver_rounded() -> None:
    """40 identical columns have eigenvalue exactly 40, and Li & Ji's ``frac`` is discontinuous there.

    Red on CI and green on this laptop from the same commit, same seed (2026-09-16): `eigvalsh` returned
    40.000000000000014 here and a hair below 40 there, so `floor` took 40 in one place and 39 in the
    other, and the estimator published 1.0000000000001767 against 2.0000000000001084 - twice the
    independence, from a rounding direction.  The test above cannot catch that: it asks the BLAS that
    happens to be running.  What the estimator needs is that BOTH sides of the integer give the same
    count, which is a property of the arithmetic and can be pinned without a random matrix at all.
    """
    below = np.array([40.0 - 2e-14] + [0.0] * 39)
    above = np.array([40.0 + 2e-14] + [0.0] * 39)
    exact = np.array([40.0] + [0.0] * 39)

    assert _li_ji_count(below) == pytest.approx(1.0, abs=1e-9)
    assert _li_ji_count(above) == pytest.approx(1.0, abs=1e-9)
    assert _li_ji_count(exact) == pytest.approx(1.0, abs=1e-9)


def test_the_snap_leaves_a_genuinely_fractional_eigenvalue_alone() -> None:
    """The tolerance must only move values already sitting on a discontinuity, never real structure."""
    spread = np.array([2.5, 1.5, 0.7, 0.3])

    # (1 + 0.5) + (1 + 0.5) + (0 + 0.7) + (0 + 0.3)
    assert _li_ji_count(spread) == pytest.approx(4.0)


def test_effective_trials_never_exceeds_the_column_count() -> None:
    """It is only ever allowed to say the search was smaller than the ledger claims."""
    rng = np.random.default_rng(9)
    for rho in (0.0, 0.3, 0.7, 0.99):
        columns = _correlated_nulls(rng, 30, 1000, rho)
        assert 1.0 <= effective_trials(columns) <= 30.0


def test_effective_trials_is_monotone_in_correlation() -> None:
    rng = np.random.default_rng(17)
    low = effective_trials(_correlated_nulls(rng, 30, 4000, 0.1))
    high = effective_trials(_correlated_nulls(rng, 30, 4000, 0.8))

    assert high < low


def test_effective_trials_handles_degenerate_input() -> None:
    assert effective_trials(np.zeros((10, 3))) == 3.0  # no variance to share: nothing to collapse
    assert effective_trials(np.ones((10, 1))) == 1.0
    assert effective_trials(np.empty((0, 0))) == 0.0


def test_the_gate_still_uses_the_raw_count() -> None:
    """N_eff is reported, not substituted: it would lower the bar, and that is not this round's job."""
    import inspect

    from starquant_alpha.validation import multiple_testing

    source = inspect.getsource(multiple_testing.oos_selection_threshold)
    assert "effective_trials" not in source


def test_the_report_states_what_this_run_s_grid_is_actually_worth() -> None:
    """A 16-point grid of near-copies is not 16 trials, and the artefact should say so.

    Scoped to the grid on purpose: the ledger stores Sharpes, not return series, so a ledger-wide
    N_eff cannot be computed from anything this function is given.  That is the concrete reason the
    debt stays open, and naming the field ``grid_effective_trials`` keeps it from being read as one.
    """
    from starquant_alpha.validation.multiple_testing import multiple_testing_report

    rng = np.random.default_rng(23)
    base = rng.standard_normal((1200, 1)) * 0.01
    near_copies = base + rng.standard_normal((1200, 8)) * 0.0005

    report = multiple_testing_report(base[:, 0], near_copies, bars_per_year=8760.0)

    assert report["grid_trials"] == 8
    assert report["grid_effective_trials"] < 3.0
    assert report["n_trials"] == 8  # the gate's denominator is untouched
