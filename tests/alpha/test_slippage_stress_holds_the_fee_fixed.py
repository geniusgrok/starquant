"""The cost stress must vary the half that can vary (2026-09-08 audit).

`cost_stress` scales `turnover_bps` - the taker fee and the slippage assumption together - by
1x / 1.5x / 2x.  Only one of those halves is uncertain: the fee is a contract constant, and the loop
has been measuring the other one.  Scaling the sum answers "what if everything cost more", which is
not the question the venue has been asking; 101 demo fills put price slippage at 5.60 bps against the
model's 2.0, with a 95% interval of [2.01, 9.19].

`cost_stress` itself is untouched: `verdict.decide` reads its `x2` cell and every archived report
carries it, so redefining what x2 means would silently move a gate and break comparability.  This is a
second instrument beside it, anchored on declared slippage levels instead of on a multiplier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation.stability import slippage_levels, slippage_stress

BPY = 8760.0


def _net(sharpe_annual: float, n: int = 5_000, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 0.01, size=n)
    values = values - values.mean()
    return pd.Series(values + sharpe_annual / np.sqrt(BPY) * values.std(ddof=1))


def test_a_level_is_the_fee_plus_that_slippage_not_a_multiple_of_the_sum() -> None:
    assert slippage_levels(taker_fee_bps=5.0, levels=(2.0, 5.5, 9.2)) == {2.0: 7.0, 5.5: 10.5, 9.2: 14.2}


def test_the_fee_is_never_scaled() -> None:
    """The failure mode being fixed: x2 on `turnover_bps` doubles a contract constant."""
    doubled_slippage = slippage_levels(taker_fee_bps=5.0, levels=(4.0,))
    assert doubled_slippage[4.0] == 9.0, "5 + 2*2, not 2 * (5 + 2)"


def test_the_report_block_names_the_slippage_each_number_was_priced_at() -> None:
    out = slippage_stress({2.0: _net(1.8), 5.5: _net(1.5), 9.2: _net(1.2)}, BPY)

    assert sorted(out) == ["slip2", "slip5.5", "slip9.2"]
    assert out["slip2"] > out["slip5.5"] > out["slip9.2"]


def test_levels_are_deduplicated_and_ordered_so_a_repeated_config_value_cannot_double_a_run() -> None:
    assert list(slippage_levels(taker_fee_bps=5.0, levels=(9.2, 2.0, 2.0))) == [2.0, 9.2]


def test_a_negative_level_is_refused_rather_than_priced() -> None:
    try:
        slippage_levels(taker_fee_bps=5.0, levels=(-1.0,))
    except ValueError as error:
        assert "non-negative" in str(error)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("a negative slippage level must be refused")
