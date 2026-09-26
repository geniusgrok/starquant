"""Q4b: does Li & Ji's N_eff give this family's gate its declared false-positive rate?

Pre-registered in docs/RESEARCH_LOG.md before this ran (2026-09-14, section "Q4b 预登记").  It answers
one question and nothing else:

    The gate is `max_sharpe_quantile(n, var, alpha) = sqrt(var) * Phi^-1((1-alpha)^(1/n))` - the
    1-alpha quantile of the maximum of n INDEPENDENT N(0, var) draws.  Under this family's REAL
    correlation structure, does the threshold computed at n = N_eff actually reject 5% of the time?

Three things worth knowing before reading the numbers.

**The variance cancels.**  Every column of the correlation matrix has unit variance, and the threshold
is `sqrt(var) * z`, so `P(max_i sqrt(var) * X_i >= sqrt(var) * z) = P(max_i X_i >= z)`.  The FWER of
this gate is a property of the correlation structure and n alone - it does not depend on the
candidate's sampling variance at all.  So this script never needs `var`, and the answer is the same
for every candidate the family could produce.

**The real matrix, not a same-spectrum surrogate.**  Li & Ji reads only the eigenvalues, so a matrix
built from those eigenvalues on a random orthogonal basis has the same N_eff - and a different
distribution of the maximum, because that reads the eigenvectors too.  Validating against a surrogate
would validate a different family.  This loads the matrix `research mine --measure` persisted.

**The control is the check on the simulation, not a result.**  Correlation can only make the maximum
of n draws smaller, so the threshold at the RAW count must reject at most 5% - if the control comes
out above 5%, the sampler is wrong and nothing below it may be read.

Sampling is done through the eigendecomposition rather than a Cholesky factor: the matrix is built from
676 highly collinear streams and is numerically near-singular, so `cholesky` is not reliable on it.
Eigenvalues are clipped at zero, which is the only place this script rounds anything, and the size of
that clip is reported.

Usage:

    .venv/bin/python scripts/q4b_liji_fwer.py reports/research/mine-measurement-<stamp>.json
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.validation.multiple_testing import (
    effective_trials_from_correlation,
    normal_ppf,
)

ALPHA = 0.05
DRAWS = 20_000
SEED = 20260914
#: Pre-registered acceptance band for the measured FWER at n = N_eff.  +/- 0.010 absolute, which at
#: DRAWS = 20,000 is about 6.5 standard errors of a 0.05 rate - far wider than Monte Carlo noise, and
#: a meaningful practical tolerance (a gate firing at 4-6% rather than 5%).
BAND = (0.040, 0.060)


def _threshold_z(n_trials: int, alpha: float = ALPHA) -> float:
    """The gate's threshold in units of the per-trial standard deviation (the variance cancels)."""
    return normal_ppf((1.0 - alpha) ** (1.0 / max(1, n_trials)))


def _sample_max(correlation: np.ndarray, draws: int, seed: int) -> tuple[np.ndarray, float]:
    """`draws` maxima of a correlated standard-normal vector with this correlation, and the clip size."""
    eigenvalues, vectors = np.linalg.eigh(correlation)
    clipped = float(-min(eigenvalues.min(), 0.0))
    root = vectors * np.sqrt(np.clip(eigenvalues, 0.0, None))
    rng = np.random.default_rng(seed)
    out = np.empty(draws, dtype=float)
    step = 2_000  # the full (draws x n) array would be ~100 MB; this keeps it to a tenth of that
    for start in range(0, draws, step):
        block = rng.standard_normal((min(step, draws - start), correlation.shape[0]))
        out[start : start + block.shape[0]] = (block @ root.T).max(axis=1)
    return out, clipped


def _fwer(maxima: np.ndarray, n_trials: int) -> float:
    return float((maxima >= _threshold_z(n_trials)).mean())


def _n_for_rate(maxima: np.ndarray, target: float = ALPHA) -> int:
    """The smallest n whose threshold rejects at most `target` - the empirical answer to "which N?"."""
    low, high = 1, 10_000_000
    while low < high:
        mid = (low + high) // 2
        if _fwer(maxima, mid) <= target:
            high = mid
        else:
            low = mid + 1
    return low


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    block = report["measurement"]["correlation"]
    matrix_path = Path(block["path"])
    raw = matrix_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != block["sha256"]:
        print(f"REFUSED: {matrix_path} sha256 {digest[:12]} != the {block['sha256'][:12]} the report recorded")
        return 2

    correlation = np.load(matrix_path).astype(float)
    dead = int(block["dead_columns"])
    n_raw = correlation.shape[0] + dead
    n_eff = effective_trials_from_correlation(correlation, dead=dead)
    reported = report["effective_trials"]
    if not math.isclose(n_eff, reported, abs_tol=1e-9):
        print(f"REFUSED: the matrix gives {n_eff}, the report says {reported}")
        return 2

    maxima, clipped = _sample_max(correlation, DRAWS, SEED)
    control = _fwer(maxima, n_raw)
    tested = _fwer(maxima, round(n_eff))
    exact = _n_for_rate(maxima)
    standard_error = math.sqrt(ALPHA * (1 - ALPHA) / DRAWS)

    print(f"matrix        {matrix_path.name}  sha256 {digest[:12]}  {correlation.shape} + {dead} dead")
    print(f"N_eff         {n_eff:.6f}  (reproduced from the matrix; report says {reported:.6f})")
    print(f"draws         {DRAWS:,}  seed {SEED}  eigenvalue clip {clipped:.3e}")
    print(f"control  n={n_raw:<8d} threshold z={_threshold_z(n_raw):.4f}  FWER {control:.4f}  (must be <= {ALPHA})")
    print(f"tested   n={round(n_eff):<8d} threshold z={_threshold_z(round(n_eff)):.4f}  FWER {tested:.4f}")
    print(f"N_exact  n={exact:<8d} threshold z={_threshold_z(exact):.4f}  FWER {_fwer(maxima, exact):.4f}")
    print(f"SE of a {ALPHA} rate at this many draws: {standard_error:.4f}; pre-registered band {BAND}")

    if control > ALPHA:
        print("VERDICT: simulation INVALID - correlation cannot raise the maximum above the independent case")
        return 3
    if BAND[0] <= tested <= BAND[1]:
        print(f"VERDICT: SUPPORTED - the gate at N_eff rejects {tested:.4f}, inside {BAND}")
        return 0
    direction = "too permissive (N_eff too small)" if tested > BAND[1] else "too strict (N_eff too large)"
    print(f"VERDICT: REFUTED, {direction} - {tested:.4f} is outside {BAND}; the empirical answer is n={exact}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
