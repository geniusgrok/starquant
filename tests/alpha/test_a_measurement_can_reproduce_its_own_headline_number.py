"""Q4b: the measurement must persist what would let someone disagree with it.

The 2026-09-14 `--measure` run cost 45 minutes and wrote one scalar: `effective_trials: 193.0`.
Everything that could be used to check that number - the correlation structure it came from - was
discarded when the process exited.  Validating Li & Ji against this ledger therefore needs the 45
minutes spent again, and that is not a limitation of the estimator, it is a defect in the artefact.

It is also the exact failure this whole round has been about.  `all_trials`'s docstring says it best:
a number nobody can see is a number nobody can argue with.  A number that cannot be recomputed from
the artefact that reports it is the same thing one step further on.

So two changes, and the second is what makes the first mean anything:

* `effective_trials_from_correlation` - Li & Ji's count taken from a correlation matrix rather than
  from a returns matrix, so the estimator has ONE implementation and the artefact's matrix feeds the
  same code the run used.  `effective_trials` becomes the returns-shaped front door to it.
* `--measure` persists the correlation matrix beside the report, with its sha256 and shape recorded.

The assertion that matters is the round trip: feed the persisted matrix back in and get the reported
number.  Anything weaker would let the two drift, which is how a stored threshold outlives the rule
that made it (KILL-Q3, one floor down).
"""

from __future__ import annotations

import numpy as np
import pytest

from starquant_alpha.validation.multiple_testing import effective_trials, effective_trials_from_correlation


def _returns(columns: int, *, copies: int = 0, seed: int = 20260914) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(size=(600, columns))
    if copies:
        base[:, -copies:] = base[:, :1]
    return base


def test_the_two_front_doors_agree_on_independent_columns() -> None:
    values = _returns(40)

    from_returns = effective_trials(values)
    from_correlation = effective_trials_from_correlation(np.corrcoef(values, rowvar=False))

    # approx, not equality: the two build the same correlation matrix from differently-laid-out
    # arrays, so BLAS takes a different path and the last bits differ.  1e-9 is far tighter than
    # anything that could change a gate and far looser than the ~1e-14 the layouts actually cost.
    assert from_returns == pytest.approx(from_correlation, abs=1e-9)


def test_the_two_front_doors_agree_when_the_family_is_mostly_copies() -> None:
    """The case the estimator exists for: 30 of 40 columns are the same column."""
    values = _returns(40, copies=30)

    assert effective_trials(values) == pytest.approx(
        effective_trials_from_correlation(np.corrcoef(values, rowvar=False)), abs=1e-9
    )
    assert effective_trials(values) < 40.0


def test_a_column_that_never_varies_is_counted_as_itself() -> None:
    """`never_traded` candidates have no correlation to contribute and must not be silently dropped."""
    values = _returns(10)
    values[:, 3] = 0.0
    live = np.corrcoef(np.delete(values, 3, axis=1), rowvar=False)

    assert effective_trials(values) == pytest.approx(effective_trials_from_correlation(live, dead=1), abs=1e-9)


def test_the_count_is_an_integer_up_to_floating_point_and_not_beyond() -> None:
    """It is an integer in exact arithmetic, and it is NOT one in the artefact.  Both halves matter.

    `trace(correlation) == n` exactly and the floors sum to an integer, so Li & Ji's count is an
    integer mathematically.  `eigvalsh` does not deliver exact arithmetic: 40 independent columns
    return 39.99999999999999, and the 2026-09-14 measurement reported **193.00000000000009**.

    Written this way because the looser claim was made out loud first - "193.0 is not a rounding
    artefact, the count must be an integer" - which is true of the estimator and false of the number
    the artefact carries.  A reported value off an integer by 1e-13 is numerical noise in the
    eigendecomposition, not structure, and the right assertion says exactly that much.
    """
    for columns in (5, 17, 40):
        value = effective_trials(_returns(columns, seed=columns))
        assert value == pytest.approx(round(value), abs=1e-9), f"{columns} columns gave {value}"


def test_a_degenerate_correlation_matrix_is_refused_rather_than_guessed() -> None:
    """A matrix that is not finite says nothing; falling back to the column count is the safe direction."""
    broken = np.array([[1.0, np.nan], [np.nan, 1.0]])

    assert effective_trials_from_correlation(broken) == 2.0


def test_an_empty_matrix_is_zero_not_one() -> None:
    assert effective_trials_from_correlation(np.zeros((0, 0))) == 0.0
