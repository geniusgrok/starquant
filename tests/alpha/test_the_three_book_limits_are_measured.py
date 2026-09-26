"""The three §3 limits, each measured on its own, against numbers that are not the code's own.

Three of the four conditions on `validated -> booked` were a literal `True` / `0.0` / `0.0` in
`starquant_governance/replay.py` from Phase 0 until today, and the reason was never that the arithmetic
was hard - it was that no book report carried the fields, so there was nothing to read.  These tests
are what stops that from being true again: one per number, on inputs small enough to check by hand,
plus one that reads the numbers back off an ARCHIVED book report so the turnover definition is pinned
against a real 49,096-bar run rather than against a fixture that agrees with it by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.validation.book_limits import (
    DECISION_SLIPPAGE_BPS,
    correlations_with_running,
    marginal_checks,
    marginal_metrics,
    max_correlation,
    slippage_stress_decision,
    turnover_per_gross,
    turnover_ratio_to_main,
)

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_BOOK = ROOT / "reports" / "research" / "book-tsmom-flow-20260908T105322Z.json"

# D-018's three marginal bars, copied rather than imported: a test that reads the same constant as the
# code cannot notice the constant moving.
RULE = {"min_delta_oos_sharpe": 0.10, "max_oos_mdd_worsening": 0.01, "min_fold_win_rate": 0.6}


def _folds(oos: float, mdd: float, sharpes: list[float | None]) -> dict[str, object]:
    return {"full_sharpe": oos, "oos_sharpe": oos, "oos_mdd": mdd, "oos_return": 0.0, "fold_sharpes": sharpes}


# --- 1. slippage stress at 5.5 bps ------------------------------------------------------------


def test_the_slippage_gate_reads_the_5_5_level_and_not_the_baseline() -> None:
    """A book admitted at 2.0 bps has to survive being priced at what the fills actually cost.

    The two rows differ only in cost, which is the whole point: 2.0 is the model's assumption and 5.5
    is the notional-weighted slippage of 101 filled demo orders.  A gate that read the cheaper row
    would be a re-statement of the decision it is supposed to stress.
    """
    by_level = {
        2.0: marginal_metrics(_folds(1.6, -0.20, [0.3, 0.4, 0.5]), _folds(1.2, -0.20, [0.1, 0.2, 0.3])),
        5.5: marginal_metrics(_folds(1.24, -0.20, [0.3, -0.4, -0.5]), _folds(1.2, -0.20, [0.1, 0.2, 0.3])),
    }
    decision = slippage_stress_decision(by_level, RULE, level=DECISION_SLIPPAGE_BPS)
    assert decision["pass"] is False
    # delta 0.04 < 0.10, and only two of three folds won: the stress names both, not just the first.
    assert decision["reasons"] == ["delta_oos_sharpe", "fold_win_rate"]
    assert slippage_stress_decision(by_level, RULE, level=2.0)["pass"] is True, "the baseline row still passes"


def test_a_book_that_survives_the_measured_slippage_passes() -> None:
    by_level = {5.5: marginal_metrics(_folds(1.6, -0.20, [0.3, 0.4, 0.5]), _folds(1.2, -0.205, [0.1, 0.2, 0.3]))}
    decision = slippage_stress_decision(by_level, RULE)
    assert decision["pass"] is True and decision["reasons"] == []
    assert decision["decision_slippage_bps"] == 5.5


def test_an_undeclared_level_is_null_rather_than_a_verdict() -> None:
    """`costs.yaml` could stop declaring 5.5; that is a suspension for the reader, not a pass."""
    decision = slippage_stress_decision(
        {2.0: marginal_metrics(_folds(1.6, -0.2, [1.0]), _folds(1.2, -0.2, [0.1]))}, RULE
    )
    assert decision["pass"] is None, "None so `replay` suspends the condition instead of deciding it"
    assert decision["reasons"] and "5.5" in decision["reasons"][0]


def test_the_stress_uses_the_same_bars_as_the_decision_it_stresses() -> None:
    """`marginal_checks` is shared, so a stress cannot quietly grade on a looser rule."""
    marginal = marginal_metrics(_folds(1.29, -0.2, [0.3, 0.4, 0.5]), _folds(1.2, -0.2, [0.1, 0.2, 0.3]))
    assert marginal_checks(marginal, RULE) == slippage_stress_decision({5.5: marginal}, RULE)["checks"]


# --- 2. correlation with every running book --------------------------------------------------


def test_the_maximum_is_over_every_running_book_not_only_the_main_one() -> None:
    """The limit the archived reports could not answer: they carry corr against MAIN and nothing else.

    A candidate uncorrelated with the main book and 0.9 with a running probe is exactly the crowding
    §3 refuses, and reading the main-only number would have admitted it.
    """
    index = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    sleeve = pd.Series([(-1.0) ** i * 0.01 + i * 1e-5 for i in range(200)], index=index)
    running = {
        "main": pd.Series([0.01 * (i % 7) for i in range(200)], index=index),
        "probe_a": sleeve * 2.0,  # a re-parameterisation of the candidate: corr 1.0
    }
    correlations = correlations_with_running(sleeve, running)
    # approx, not ==: a perfect correlation comes back 1 ulp short on some BLAS builds.  The
    # claim here is "perfectly correlated", and 1e-6 keeps every wrong answer this test can
    # produce (a main-only reading, or one dragged down by non-overlapping bars) far outside.
    assert correlations["probe_a"] == pytest.approx(1.0)
    assert abs(correlations["main"]) < 0.5
    assert max_correlation(correlations) == pytest.approx(1.0)


def test_a_diversifier_is_not_a_violation() -> None:
    """Signed, not absolute: -0.9 against a running book is what the rule is looking for."""
    index = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
    sleeve = pd.Series([0.01 * (i % 5) for i in range(100)], index=index)
    correlations = correlations_with_running(sleeve, {"main": -sleeve})
    assert correlations["main"] == pytest.approx(-1.0)
    assert max_correlation(correlations) == pytest.approx(-1.0), "abs() here would refuse the best possible sleeve"


def test_nothing_measured_is_none_and_not_zero() -> None:
    """0.0 is the PASSING value, so 'no running book' must not be spelled the same way as 'uncorrelated'."""
    index = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    sleeve = pd.Series([0.01 * (i % 3) for i in range(50)], index=index)
    assert max_correlation(correlations_with_running(sleeve, {})) is None
    # A constant stream has no correlation with anything; pandas answers NaN and NaN must not survive.
    flat = pd.Series([0.0] * 50, index=index)
    assert correlations_with_running(sleeve, {"flat": flat}) == {"flat": None}
    assert max_correlation({"flat": None}) is None


def test_only_the_overlapping_bars_are_correlated() -> None:
    index = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
    sleeve = pd.Series([0.01 * (i % 5) for i in range(100)], index=index)
    assert correlations_with_running(sleeve, {"late": sleeve.iloc[60:]})["late"] == pytest.approx(1.0)
    assert correlations_with_running(sleeve, {"disjoint": sleeve.shift(freq="1000h")})["disjoint"] is None


# --- 3. turnover against the main book --------------------------------------------------------


def test_the_gated_ratio_is_the_one_every_preregistration_used() -> None:
    """Read off an archived run, so the definition is pinned against a real book and not a fixture.

    `book-tsmom-flow-20260908T105322Z` carries both `turnover_units` already - which is why this
    particular limit is the one of the three that CAN be back-computed for the six archived reports.
    """
    report = json.loads(ARCHIVED_BOOK.read_text(encoding="utf-8"))
    decision = report["universes"][report["universe_mode"]]
    main = decision["main_only"]["summary"]
    sleeve = decision["sleeve_standalone"]["full_sample"]

    ratio = turnover_ratio_to_main(sleeve, main)
    assert ratio is not None and round(ratio, 3) == 0.557, "208.58 / 374.81 units"
    assert ratio <= 3.0, "flow passes §3's limit on the pre-registered reading"


def test_the_scale_free_reading_disagrees_and_is_reported_beside_it() -> None:
    """The two readings differ by 3.7x on a real book, which is why both are in the artefact.

    Per unit of the book's own gross exposure flow trades 2.04x as fast as tsmom; on raw units it is
    0.56x, because flow runs at a quarter of tsmom's exposure.  Neither is wrong; the gated one is the
    one the operator has been pre-registering against, and the other is in the report so nobody reads
    "0.56x" as "this sleeve trades slowly".
    """
    report = json.loads(ARCHIVED_BOOK.read_text(encoding="utf-8"))
    decision = report["universes"][report["universe_mode"]]
    main = turnover_per_gross(decision["main_only"]["summary"])
    sleeve = turnover_per_gross(decision["sleeve_standalone"]["full_sample"])
    assert main is not None and sleeve is not None
    assert round(sleeve / main, 2) == 2.04


def test_the_scale_free_reading_does_not_move_with_the_fraction() -> None:
    """`sleeve_scaled_summary` is the same sleeve at 1/3; the per-gross rate has to be the same number.

    This is the property that makes the scale-free reading worth reporting at all, and it is measured
    rather than asserted in a comment: scaling changes turnover and exposure together.
    """
    report = json.loads(ARCHIVED_BOOK.read_text(encoding="utf-8"))
    decision = report["universes"][report["universe_mode"]]
    unscaled = turnover_per_gross(decision["sleeve_standalone"]["full_sample"])
    scaled = turnover_per_gross(decision["sleeve_scaled_summary"])
    assert unscaled is not None and scaled is not None
    assert abs(unscaled - scaled) / unscaled < 0.001


def test_turnover_is_none_when_the_main_book_never_traded() -> None:
    assert turnover_ratio_to_main({"turnover_units": 10.0}, {"turnover_units": 0.0}) is None
    assert turnover_ratio_to_main({}, {"turnover_units": 10.0}) is None
    assert turnover_per_gross({"turnover_units": 10.0, "bars": 100}) is None
