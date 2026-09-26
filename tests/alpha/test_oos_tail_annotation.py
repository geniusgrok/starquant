"""KILL-Q2 / F1+F3: a validation report must say when its "OOS" had nothing to select between.

`walk_forward_evaluate` picks the best parameter set per fold on the training slice and
concatenates that set's test slice.  With one grid point - or with every fold choosing the
same point - there is no selection freedom left, so the "walk-forward OOS" is simply the
tail of one full-sample series.  Every tsmom report since 2026-09-04 was of that shape, and
nothing in the artefact said so while the verdict read PASS off the number.

Two annotations, no new gate (the holdout half of the original prescription was withdrawn:
it contradicts the operator's KILL-006 ruling):

* ``oos_is_full_sample_tail`` - true when no fold had a choice to make;
* ``selection_consistent`` + ``best_key_oos_sharpe`` - F3: ``best_params`` is chosen by
  full-sample argmax, while the headline OOS is the fold-selected mixture.  When they differ,
  the shipped configuration's own out-of-sample number is the one a reader wants.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.validation.walk_forward import walk_forward_evaluate, walk_forward_folds

BPY = 8760.0


def _series(sharpe_annual: float, n: int, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = rng.normal(sharpe_annual / BPY * 100.0, 0.01, size=n)
    return pd.Series(values, index=pd.RangeIndex(n))


def _switching_grid(seed: int) -> tuple[dict[str, pd.Series], dict[str, dict[str, int]]]:
    """Two configurations whose EXPANDING training mean changes hands part-way through.

    Walk-forward trains on everything up to the fold, so an early edge keeps winning unless a
    later one is big enough to move the cumulative mean - which is what makes a real selection.
    """
    n = 2000
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.004, size=n)
    early = pd.Series(noise.copy())
    late = pd.Series(noise.copy())
    early.iloc[:700] += 0.003
    late.iloc[700:] += 0.009
    return {"a": early, "b": late}, {"a": {"x": 1}, "b": {"x": 2}}


def _folds(n: int) -> list:
    return walk_forward_folds(n, 5, min_train=400, purge=10)


def test_single_configuration_is_marked_as_a_full_sample_tail() -> None:
    n = 2000
    nets = {"only": _series(1.5, n, seed=1)}
    params = {"only": {"x": 1}}

    summary = walk_forward_evaluate(nets, params, _folds(n), BPY).summary(BPY)

    assert summary["oos_is_full_sample_tail"] is True
    assert summary["selection_consistent"] is True


def test_a_grid_whose_folds_all_pick_the_same_point_is_also_a_tail() -> None:
    """Two configurations, but one dominates every training slice: still no selection happened."""
    n = 2000
    nets = {"good": _series(2.5, n, seed=2), "bad": _series(-1.0, n, seed=3)}
    params = {"good": {"x": 1}, "bad": {"x": 2}}

    result = walk_forward_evaluate(nets, params, _folds(n), BPY)
    summary = result.summary(BPY)

    assert len({str(p) for p in summary["chosen_params"]}) == 1, "fixture must have one winner"
    assert summary["oos_is_full_sample_tail"] is True


def test_a_grid_that_actually_switches_is_not_a_tail() -> None:
    """Two configurations that trade places across folds: the OOS really is a mixture."""
    nets, params = _switching_grid(seed=11)

    summary = walk_forward_evaluate(nets, params, _folds(2000), BPY).summary(BPY)

    assert len({str(p) for p in summary["chosen_params"]}) > 1, "fixture must switch"
    assert summary["oos_is_full_sample_tail"] is False
    assert summary["selection_consistent"] is False


def test_the_shipped_configuration_gets_its_own_out_of_sample_number() -> None:
    """F3: the headline is the fold-selected mixture; `best_key` may be a different series."""
    nets, params = _switching_grid(seed=12)
    result = walk_forward_evaluate(nets, params, _folds(2000), BPY)

    own = result.oos_sharpe_for("b", _folds(2000), BPY)

    assert own is not None
    assert own != pytest.approx(result.summary(BPY)["oos_sharpe"]), "a mixture is not the configuration"


def test_an_unknown_key_has_no_out_of_sample_number() -> None:
    n = 2000
    nets = {"only": _series(1.5, n, seed=4)}
    result = walk_forward_evaluate(nets, {"only": {"x": 1}}, _folds(n), BPY)

    assert result.oos_sharpe_for("missing", _folds(n), BPY) is None
