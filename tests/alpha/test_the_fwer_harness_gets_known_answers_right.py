"""The Q4b harness is checked against families whose answer is known before it judges one that is not.

`scripts/q4b_liji_fwer.py` decides whether Li & Ji's N_eff gives this gate its declared 5%.  A verdict
from an unvalidated instrument is worth nothing, and this round has already had to write that sentence
about `effective_trials` itself - so the instrument gets the same treatment.

Two families with known answers:

* **676 independent columns.**  N_eff must come out at 676, and the gate at n = 676 must reject at
  alpha, because that is the case the gate's own null describes.  This is the only check that can
  catch a sampler that is silently wrong.
* **676 columns spanning 20 directions.**  Correlation can only make the maximum smaller, so the gate
  at the RAW count must reject at most alpha.  A control above alpha means the sampler is wrong and
  nothing else it prints may be read - which is why the script refuses on it rather than reporting it.

The second family also shows why the question was worth asking.  Li & Ji returns 32 there, and a gate
built on 32 rejects about 38% of the time - the maximum of 676 unit-variance marginals is nothing like
the maximum of 32, however few directions they span.  That is not a prediction about the real matrix,
whose collinearity is far milder; it is the reason the real matrix has to be measured rather than
assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from q4b_liji_fwer import ALPHA, _fwer, _n_for_rate, _sample_max

from starquant_alpha.validation.multiple_testing import effective_trials_from_correlation

DRAWS = 20_000
SEED = 20260914


def _collinear(columns: int = 676, directions: int = 20, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    loadings = rng.normal(size=(columns, directions))
    covariance = loadings @ loadings.T + 0.05 * np.eye(columns)
    scale = np.sqrt(np.diag(covariance))
    return covariance / np.outer(scale, scale)


def test_an_independent_family_gets_its_own_column_count_back() -> None:
    assert effective_trials_from_correlation(np.eye(676)) == pytest.approx(676.0, abs=1e-9)


def test_the_gate_rejects_at_alpha_when_the_family_really_is_independent() -> None:
    """The gate's null stated as a test: this is the case `max_sharpe_quantile` was derived for."""
    maxima, clipped = _sample_max(np.eye(676), DRAWS, SEED)

    assert clipped == pytest.approx(0.0, abs=1e-12), "an identity matrix needs no eigenvalue clipping"
    assert _fwer(maxima, 676) == pytest.approx(ALPHA, abs=0.005)


def test_the_empirical_n_for_an_independent_family_is_its_column_count() -> None:
    maxima, _ = _sample_max(np.eye(676), DRAWS, SEED)

    assert _n_for_rate(maxima) == pytest.approx(676, rel=0.10)


def test_correlation_can_only_lower_the_rejection_rate_at_the_raw_count() -> None:
    """The script's control, and the reason it is a control: a value above alpha means the sampler is wrong."""
    maxima, _ = _sample_max(_collinear(), DRAWS, SEED)

    assert _fwer(maxima, 676) <= ALPHA


def test_li_and_ji_is_far_too_permissive_on_a_strongly_collinear_family() -> None:
    """Not a prediction about the real matrix - the reason the real matrix must be measured."""
    correlation = _collinear()
    maxima, _ = _sample_max(correlation, DRAWS, SEED)
    n_eff = round(effective_trials_from_correlation(correlation))

    assert n_eff < 60, f"20 directions should collapse 676 columns hard, got {n_eff}"
    assert _fwer(maxima, n_eff) > 0.20, "a gate at this N_eff admits noise many times over"
    assert _n_for_rate(maxima) > 10 * n_eff, "and the empirical answer is an order of magnitude larger"
