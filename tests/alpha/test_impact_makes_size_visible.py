"""DL-C1 / KILL-A: the backtest stops pretending a 40 USDT order and a 4M one cost the same.

Everything else in `backtest.py` is scale-free, and that is arithmetic rather than a finding: gross
P&L, turnover cost and funding are all linear in the weights, so scaling every weight by k leaves the
Sharpe unchanged to the last digit.  The flat 7 bps is what makes that true, it is a good
approximation at demo notional (40-800 USDT), and it is the assumption KILL-Q12 has held real capital
out of scope on since 2026-09-05.

What is asserted here is the SHAPE, never a cost number.  The coefficient is an assumption this system
cannot calibrate - its only fills are demo, and the 5.52 bps measured across them is spread and fee
with no separable impact content - so a test that pinned a bps figure would be pinning a literature
constant and calling it a measurement.  The shape is what has to hold: off by default, the flat model
as the exact limit, monotone in size, superlinear in size, and causal.

(The docstring here used to say "order/ADV around 1e-8, where the model predicts under a hundredth of
a basis point".  That was DL-C1's pre-run estimate and DL-C1's own run retracted it; measured per fill
on 121 real fills it is order/ADV 4.3e-07 median and 0.48 bps notional-weighted - see the 2026-09-09
VWAP section of RESEARCH_LOG.  The retraction had reached the scratchpad script and the log but not
the three places a reader actually looks, of which this was one.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, ImpactModel, impact_costs, run_backtest
from starquant_alpha.panel import Panel
from tests.alpha.test_causality import _bit_for_bit


def _panel(bars: int = 900, symbols: tuple[str, ...] = ("AAA", "BBB"), volume: float = 1_000.0) -> Panel:
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    rng = np.random.default_rng(7)
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, size=(bars, len(symbols))), axis=0)),
        index=index,
        columns=list(symbols),
    )
    volumes = pd.DataFrame(volume, index=index, columns=list(symbols))
    return Panel(
        interval="1h",
        open=close.shift(1).bfill(),
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=volumes,
        quote_volume=volumes * close,
    )


def _weights(panel: Panel) -> pd.DataFrame:
    """A book that trades every bar, so turnover is never zero and the charge is always exercised."""
    sign = pd.Series(np.where(np.arange(len(panel.close)) % 2 == 0, 0.4, -0.4), index=panel.close.index)
    return pd.DataFrame(dict.fromkeys(panel.close.columns, sign))


def test_it_is_off_by_default_so_every_archived_report_still_reproduces() -> None:
    panel = _panel()
    weights = _weights(panel)
    flat = run_backtest(panel, weights, CostModel(turnover_bps=7.0))
    explicit_zero = run_backtest(panel, weights, CostModel(turnover_bps=7.0), impact=ImpactModel(capital=0.0))
    assert flat.costs.equals(explicit_zero.costs)


def test_the_flat_model_is_this_models_own_limit_rather_than_a_separate_branch() -> None:
    """T-C1-1.  The charge is continuous in size and vanishes at zero - no branch, no discontinuity.

    Stated as the exact square-root relation rather than as "small at small capital", because "small"
    depends on the panel's ADV and would make this test a statement about the fixture.  What matters is
    that the extra charge over the flat model scales as sqrt(capital) all the way down, so capital = 0
    is the limit of the same expression rather than a separate code path.
    """
    panel = _panel()
    weights = _weights(panel)
    base = run_backtest(panel, weights, CostModel(turnover_bps=7.0)).costs.to_numpy().sum()
    charged = [
        run_backtest(panel, weights, CostModel(turnover_bps=7.0), impact=ImpactModel(capital=c)).costs.to_numpy().sum()
        for c in (1.0, 100.0, 10_000.0)
    ]
    assert all(value > base for value in charged)
    assert np.isclose(charged[1] - base, (charged[0] - base) * 10.0, rtol=1e-9)
    assert np.isclose(charged[2] - base, (charged[0] - base) * 100.0, rtol=1e-9)


@pytest.mark.parametrize("factor", [4.0, 9.0, 100.0])
def test_the_charge_grows_with_the_square_root_of_size(factor: float) -> None:
    """Doubling capital does not double impact; quadrupling it does.  That is the whole point of size."""
    panel = _panel()
    rets = panel.close / panel.open - 1.0
    turnover = _weights(panel).diff().abs().fillna(0.4)
    columns = list(panel.close.columns)
    small = impact_costs(turnover, rets, panel, columns, ImpactModel(capital=1_000.0)).to_numpy().sum()
    large = impact_costs(turnover, rets, panel, columns, ImpactModel(capital=1_000.0 * factor)).to_numpy().sum()
    assert np.isclose(large / small, np.sqrt(factor), rtol=1e-9)


@pytest.mark.parametrize("slices", [2, 4, 10])
def test_slicing_an_order_is_exactly_a_smaller_coefficient(slices: int) -> None:
    """Block 4 #42 (VWAP), 2026-09-09: the whole benefit of child orders is one constant.

    Under the square-root law, N equal children cost
    ``N * (Q/N) * c * sigma * sqrt((Q/N)/ADV) = impact(Q) / sqrt(N)``, so a PERFECT N-way VWAP - zero
    timing risk, zero leakage, every child at the arrival price - is arithmetically the same run as
    ``coefficient / sqrt(N)``.  That is what let #42 be priced without building an execution layer:
    the best case an execution layer could ever reach is a move in a parameter that is declared E5 and
    that this venue cannot calibrate, so the benefit sits inside its own generating assumption's error
    bar and could never be verified as having arrived.

    This test is the refusal's premise, not its conclusion.  If the impact model ever stops being
    sqrt-concave - a linear term, a fixed per-order cost, a spread component - the identity breaks
    here, and #42 has to be re-decided rather than staying refused by a stale argument.
    """
    panel = _panel()
    rets = panel.close / panel.open - 1.0
    turnover = _weights(panel).diff().abs().fillna(0.4)
    columns = list(panel.close.columns)
    capital = 1_000_000.0

    sliced = (
        slices * impact_costs(turnover / slices, rets, panel, columns, ImpactModel(capital=capital)).to_numpy().sum()
    )
    cheaper_coefficient = (
        impact_costs(turnover, rets, panel, columns, ImpactModel(capital=capital, coefficient=1.0 / np.sqrt(slices)))
        .to_numpy()
        .sum()
    )
    assert np.isclose(sliced, cheaper_coefficient, rtol=1e-12)

    # And the recovered share is 1 - 1/sqrt(N) everywhere at once: it does not depend on ADV, on sigma
    # or on capital.  So there is no thin corner of the universe where slicing pays for itself while
    # the rest does not - "just slice the illiquid names" buys the same fraction as slicing everything.
    whole = impact_costs(turnover, rets, panel, columns, ImpactModel(capital=capital))
    per_cell = whole - slices * impact_costs(turnover / slices, rets, panel, columns, ImpactModel(capital=capital))
    share = (per_cell / whole.where(whole > 0)).stack().dropna()
    assert np.allclose(share.to_numpy(), 1.0 - 1.0 / np.sqrt(slices), atol=1e-12)


def test_it_reads_no_bar_the_decision_could_not_have() -> None:
    """Both inputs are trailing and shifted; replacing the future must not move a single charge."""
    panel = _panel()
    weights = _weights(panel)
    columns = list(panel.close.columns)
    rets = panel.close / panel.open - 1.0
    turnover = weights.diff().abs().fillna(0.4)
    model = ImpactModel(capital=1_000_000.0)
    before = impact_costs(turnover, rets, panel, columns, model)

    cutoff = 700
    tampered = _panel()
    tampered.close.iloc[cutoff:] *= 3.0
    tampered.volume.iloc[cutoff:] *= 50.0
    if tampered.quote_volume is not None:
        tampered.quote_volume.iloc[cutoff:] *= 150.0
    after = impact_costs(turnover, rets, tampered, columns, model)
    _bit_for_bit(before.iloc[:cutoff], after.iloc[:cutoff])


def test_a_thinner_market_costs_more_for_the_same_order() -> None:
    """The quantity being modelled is participation, so ADV has to be in the denominator."""
    thick, thin = _panel(), _panel(volume=10.0)
    columns = list(thick.close.columns)
    rets = thick.close / thick.open - 1.0
    turnover = _weights(thick).diff().abs().fillna(0.4)
    model = ImpactModel(capital=1_000_000.0)
    assert (
        impact_costs(turnover, rets, thin, columns, model).to_numpy().sum()
        > impact_costs(turnover, rets, thick, columns, model).to_numpy().sum()
    )


def test_negative_parameters_are_refused() -> None:
    with pytest.raises(ValueError):
        ImpactModel(capital=-1.0)
    with pytest.raises(ValueError):
        ImpactModel(coefficient=-1.0)


def test_the_stress_arms_carry_the_charge_the_headline_carries() -> None:
    """`cost_stress` is a GATE (`verdict.decide` reads x2), so it has to be priced as the run is labelled.

    Found 2026-09-09 on the first AC-C1 artefact: its header said `impact_model: {capital: 100000}`, its
    walk-forward was priced under the square-root law, and both stress blocks were priced flat - within
    0.002 Sharpe of the flat report produced the day before.  The error ran in the permissive direction.

    The property is what the fix relies on: the impact charge composes with a SCALED `CostModel` rather
    than being scaled by it.  A multiplier on `turnover_bps` is a question about fees, and impact is not
    a fee.
    """
    panel = _panel()
    weights = _weights(panel)
    impact = ImpactModel(capital=5_000_000.0)
    for multiplier in (1.0, 1.5, 2.0):
        cost = CostModel(turnover_bps=7.0 * multiplier)
        flat = run_backtest(panel, weights, cost).costs.to_numpy().sum()
        charged = run_backtest(panel, weights, cost, impact=impact).costs.to_numpy().sum()
        assert charged > flat, f"x{multiplier}: the stress arm ignored the impact model"
    # and the charge itself does not move with the fee multiplier - it is size, not price
    charges = [
        run_backtest(panel, weights, CostModel(turnover_bps=7.0 * m), impact=impact).costs.to_numpy().sum()
        - run_backtest(panel, weights, CostModel(turnover_bps=7.0 * m)).costs.to_numpy().sum()
        for m in (1.0, 1.5, 2.0)
    ]
    assert max(charges) - min(charges) < 1e-9, f"the impact charge scaled with the fee multiplier: {charges}"


def test_a_priced_run_is_a_different_trial_from_a_flat_one() -> None:
    """The ledger folded DL-C1's impact-priced tsmom onto the flat rows as a replay, so `spent` never moved.

    Running one configuration under two cost models and keeping whichever passes is the selection DSR
    exists to expose, and §19 had already written down that adopting the cost model would charge rows.
    Conditional on `enabled`, because an unconditional field would give every future FLAT run a
    signature no archived row shares - charging genuine replays as new trials, the same defect mirrored.
    """
    from starquant_cli.research_cmd import _construction_digest

    portfolio = {"vol_target": 0.30, "no_trade_band": 0.002}
    cost = CostModel(turnover_bps=7.0)
    flat = _construction_digest(portfolio, cost, "open_to_close")
    off = _construction_digest(portfolio, cost, "open_to_close", ImpactModel(capital=0.0))
    priced = _construction_digest(portfolio, cost, "open_to_close", ImpactModel(capital=100_000.0))
    bigger = _construction_digest(portfolio, cost, "open_to_close", ImpactModel(capital=1_000_000.0))

    assert off == flat, "an archived flat row must keep its signature, or every replay is charged as new"
    assert priced != flat, "an impact-priced run is a different trial"
    assert bigger != priced, "and so is the same law at a different size"
