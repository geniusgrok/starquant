"""The gate was attached to the grid that answers a different question.

`cost_stress_gate` re-asks D-028's threshold while scaling `turnover_bps`, which scales the taker fee
with it.  The fee is a contract constant - VIP0 taker is 5.0 bps whatever happens to execution - so
`x1.5` bills 7.5 bps of fee that no venue will ever charge, and its margin is not the margin of a
slippage assumption being wrong.  `slippage_levels`' docstring has made that argument since the grid
was added; what was missing is that only the multiplier grid had a gate, so the artefact answered the
question it was not asked and stayed silent on the one it was.

The trap this closes is subtle rather than absent: the two grids COINCIDE wherever their totals match
(`x1.5` and `slip5.5` are both 10.5 bps), so reading a slippage answer off `x1.5` is correct by
accident at one cell and wrong at every other - including at 4.43, the measured value, which has no
multiplier cell at all and sits exactly where the gate is crossed.
"""

from __future__ import annotations

import math

import pandas as pd

from starquant_alpha.validation.stability import cost_stress, slippage_levels, slippage_stress
from starquant_shared.config import load_yaml

COSTS = "config/costs.yaml"
BPY = 8760.0


def _payload() -> dict:
    return load_yaml(COSTS)


def test_the_measured_centre_has_a_cell_of_its_own() -> None:
    """4.43 is the notional-weighted centre of the 81 decision-close fills `costs.yaml` records."""
    levels = [float(v) for v in _payload()["slippage_stress_bps"]]

    assert 4.43 in levels, "the measured slippage has no cell, so its gate answer stays an interpolation"
    assert levels == sorted(levels), "the grid reads as a ladder and must stay ordered"
    # The assumption itself is unchanged: this is a stress cell, not a new best estimate.
    assert float(_payload()["slippage_bps"]) == 2.0


def test_the_slippage_grid_holds_the_fee_fixed_and_the_multiplier_grid_does_not() -> None:
    """The difference is in the DECOMPOSITION, not in the total - which is what makes it easy to miss.

    `x1.5` and `slip5.5` are both 10.5 bps (pinned in the test below).  What differs is what each one
    claims that 10.5 is made of: the multiplier's semantics scale both components, so its cell is a
    world where the taker fee is 7.5; the slippage grid holds the fee at `taker_fee_bps` and puts the
    whole increase where the uncertainty actually is.  Only one of those worlds is reachable - the
    VIP0 taker fee does not move when execution gets worse.
    """
    fee = float(_payload()["taker_fee_bps"])
    levels = slippage_levels(taker_fee_bps=fee, levels=[2.0, 4.43, 5.5, 9.2])

    # Every slippage cell bills exactly `fee` of fee, by construction.
    for slip, total in levels.items():
        assert total - slip == fee

    # The multiplier's does not: at x1.5 the implied fee is 7.5, a number no venue will ever bill.
    assert fee * 1.5 != fee
    assert fee * 1.5 == 7.5


def test_the_two_grids_agree_exactly_where_their_totals_do() -> None:
    """The coincidence that makes a mislabelled reading survive review: x1.5 and slip5.5 are one number."""
    fee = float(_payload()["taker_fee_bps"])
    base = fee + 2.0  # 7.0, the shipped turnover_bps
    net = pd.Series([0.001, -0.002, 0.003, 0.0005, -0.001] * 40)

    by_multiplier = cost_stress({1.0: net, 1.5: net * 0.9, 2.0: net * 0.8}, BPY)
    by_slippage = slippage_stress({2.0: net, 5.5: net * 0.9, 9.2: net * 0.8}, BPY)

    assert math.isclose(base * 1.5, slippage_levels(taker_fee_bps=fee, levels=[5.5])[5.5])
    assert by_multiplier["x1.5"] == by_slippage["slip5.5"], "same total, same series, same Sharpe"
    # ... and 4.43 has no multiplier twin, which is the whole point of adding the cell.
    total_443 = slippage_levels(taker_fee_bps=fee, levels=[4.43])[4.43]
    assert base < total_443 < base * 1.5, "the measured value sits strictly between x1 and x1.5"


def test_the_measured_cell_lands_where_the_gate_is_crossed() -> None:
    """Pinned from the 2026-09-17 embargo arms: x1 cleared by +0.03 and x1.5 missed by -0.03.

    That is what makes 4.43 worth a backtest rather than a ratio: the crossing is inside the interval
    it falls in, so no reading of the neighbouring cells settles it.  If a future run moves both cells
    to the same side of the threshold this test should be deleted, not widened - the question it
    describes would no longer exist.
    """
    fee = float(_payload()["taker_fee_bps"])
    base = fee + 2.0
    measured = slippage_levels(taker_fee_bps=fee, levels=[4.43])[4.43]

    assert (measured - base) / (base * 0.5) < 1.0, "4.43 must fall inside the x1..x1.5 interval"
    assert measured == 9.43
