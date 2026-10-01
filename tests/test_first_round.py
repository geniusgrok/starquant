"""Risk promotion and the long-only causal counterfactual."""

from copy import deepcopy
from unittest.mock import patch

import numpy as np

from btc_perp.config import load_config
from btc_perp.first_round import choose
from btc_perp.robustness import _replay


def test_a_high_return_candidate_cannot_win_after_a_stress_lock() -> None:
    row = {"cagr": 1.0, "end_cny": 100000.0, "breaches_half_peak_line": False, "locked_at_end": False}
    results = {
        name: {"base": deepcopy(row), "stress": deepcopy(row)}
        for name in ("baseline", "half-risk", "no-adds", "half-risk-no-adds")
    }
    results["no-adds"]["stress"].update(cagr=1.4, locked_at_end=True)
    results["half-risk"]["stress"]["cagr"] = 0.9
    results["half-risk-no-adds"]["base"]["cagr"] = 0.7
    assert choose(results)["selected"] == "half-risk"


def test_long_only_suppresses_short_entry_in_the_real_causal_kernel() -> None:
    n = 4
    o = np.full(n, 100.0)
    c = np.array([100.0, 100.0, 95.0, 95.0])
    prepared = (
        o,
        o.copy(),
        np.minimum(o, c),
        c,
        np.empty(1),
        np.zeros(n),
        np.full(n, 7.0),
        np.full(n, 20200101),
        np.arange(n),
        np.full(n, 1e9),
        np.full(n, 150.0),
        np.full(n, 1e9),
        np.full(n, 1.0),
        np.ones(n, np.int8),
    )
    with patch("btc_perp.measure._prepare", return_value=prepared):
        original = _replay(load_config())
        long_only = _replay(load_config(), long_only=True)
    assert original["n_short"] >= 1
    assert long_only["n_short"] == 0
    assert np.all(long_only["_side"] >= 0)
