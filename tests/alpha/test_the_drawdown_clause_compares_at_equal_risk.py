"""Operator ruling 2026-09-14 (Q3): D-018's drawdown clause compares two books at the same risk.

D-018 asks what a sleeve ADDS, and prices it by subtracting the main book's out-of-sample drawdown
from the total book's.  Those two books do not carry the same risk.  Measured 2026-09-07 on the
`594a12f9` sleeve at fraction 1/3: adding a stream correlated 0.236 took the book's annualised vol
from 32.24% to 35.66%, +10.6%.  **Any sleeve that can add Sharpe adds vol, and therefore adds
drawdown**, so the 1pp allowance was being charged against a bigger book than the one it was written
for.  Scaling the total back to the main book's vol kept the Sharpe gain intact (+0.288, to the digit)
and moved the drawdown cost from +4.27pp to +1.87pp.

That was recorded as a finding about the RULE, not about that candidate - and deliberately left
unexecuted, because the candidate had just failed and changing a rule you have just failed is the
thing this apparatus exists to refuse.  The ruling is now made on its own terms.

**It applies to later candidates only, and that is enforced structurally rather than by a date.**  The
equal-risk number exists only in reports that carry it; `marginal_checks` reads it when it is there and
the raw difference when it is not.  So no archived verdict moves, and nothing has to remember a
cut-off.  It also does not rescue `594a12f9`: at equal risk that sleeve still costs +1.87pp against a
1pp allowance, which is why the ruling could be made without deciding its case.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from starquant_alpha.validation.book_limits import marginal_checks, marginal_metrics

RULE = {"min_delta_oos_sharpe": 0.1, "max_oos_mdd_worsening": 0.01, "min_fold_win_rate": 0.6}


def _book(returns: pd.Series, *, oos_sharpe: float = 1.8, folds: list[float] | None = None) -> dict:
    equity = (1.0 + returns).cumprod()
    drawdown = float((equity / equity.cummax() - 1.0).min())
    return {
        "full_sharpe": oos_sharpe,
        "full_mdd": drawdown,
        "oos_sharpe": oos_sharpe,
        "oos_return": float(equity.iloc[-1] - 1.0),
        "oos_mdd": drawdown,
        "fold_sharpes": folds or [1.0, 1.0, 1.0],
    }


def _streams() -> tuple[pd.Series, pd.Series]:
    """A main book, and a total book that is the same path 10.6% larger - E-012's measured shape."""
    rng = np.random.default_rng(20260914)
    main = pd.Series(rng.normal(0.0004, 0.01, 4000))
    total = main * 1.106
    return main, total


def test_the_raw_difference_is_still_reported() -> None:
    """The old number does not go away: a ruling that deletes its own evidence cannot be argued with."""
    main_net, total_net = _streams()

    out = marginal_metrics(_book(total_net, oos_sharpe=2.1), _book(main_net), total_oos=total_net, main_oos=main_net)

    assert "oos_mdd_worsening" in out
    assert out["oos_mdd_worsening"] > 0, "the bigger book does draw down more"


def test_equal_risk_costs_less_than_the_raw_difference_for_a_sleeve_that_adds_vol() -> None:
    main_net, total_net = _streams()

    out = marginal_metrics(_book(total_net, oos_sharpe=2.1), _book(main_net), total_oos=total_net, main_oos=main_net)

    assert out["oos_mdd_worsening_equal_risk"] < out["oos_mdd_worsening"]


def test_a_book_that_adds_no_vol_is_charged_the_same_either_way() -> None:
    """Equal risk is not a discount; it only removes the part that is scale."""
    main_net, _ = _streams()

    out = marginal_metrics(_book(main_net), _book(main_net), total_oos=main_net, main_oos=main_net)

    assert out["oos_mdd_worsening_equal_risk"] == out["oos_mdd_worsening"] == 0.0


def test_the_check_reads_the_equal_risk_number_when_the_report_carries_it() -> None:
    marginal = {
        "delta_oos_sharpe": 0.3,
        "fold_win_rate": 1.0,
        "oos_mdd_worsening": 0.0255,
        "oos_mdd_worsening_equal_risk": 0.005,
    }

    assert marginal_checks(marginal, RULE)["oos_mdd_worsening"] is True


def test_an_archived_report_without_the_field_is_judged_exactly_as_before() -> None:
    """The whole of "later candidates only": no date, no migration, no verdict moves."""
    marginal = {"delta_oos_sharpe": 0.3, "fold_win_rate": 1.0, "oos_mdd_worsening": 0.0255}

    assert marginal_checks(marginal, RULE)["oos_mdd_worsening"] is False


def test_the_ruling_does_not_rescue_the_candidate_it_came_from() -> None:
    """+1.87pp at equal risk against a 1pp allowance - which is why it could be ruled on separately."""
    marginal = {
        "delta_oos_sharpe": 0.288,
        "fold_win_rate": 1.0,
        "oos_mdd_worsening": 0.0427,
        "oos_mdd_worsening_equal_risk": 0.0187,
    }

    assert marginal_checks(marginal, RULE)["oos_mdd_worsening"] is False


def test_streams_are_optional_so_every_existing_caller_keeps_working() -> None:
    main_net, total_net = _streams()

    out = marginal_metrics(_book(total_net, oos_sharpe=2.1), _book(main_net))

    assert "oos_mdd_worsening" in out
    assert "oos_mdd_worsening_equal_risk" not in out
