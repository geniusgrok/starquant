"""Two undeclared conventions, declared (2026-09-08 audit).

Both were correct and neither was written down, which in this repository is the failure mode with its
own entry in the log: a fact that is true and unstated reads exactly like an assumption nobody checked.

* `sharpe` has no risk-free term.  At 30% annualised volatility a 4% rate is worth about 0.13 of
  Sharpe - larger than several effects this repository has re-run whole validations over - and the
  book's equity sits at the venue as margin, so the opportunity cost is real.  The number stays as it
  is (changing it would break comparability with every archived report); what changes is that it says so.
* `backtest`'s module docstring called `open_to_close` "conservative".  That is true of the entry price
  and false of the holding return: the convention silently drops close_t -> open_{t+1} on every held
  bar, worth 2.36% of total absolute price movement, and re-earning it costs -0.029 OOS Sharpe on the
  shipped book - the dropped component is adverse, not favourable.

Asserted rather than trusted, the same way `test_selection_gate` pins "short-sample guard": a paragraph
nothing reads is a paragraph that gets deleted by the next person who tidies the file.
"""

from __future__ import annotations

import starquant_alpha.backtest as backtest_module
from starquant_alpha.portfolio import ewma_portfolio_vol
from starquant_alpha.validation.metrics import compound, max_drawdown, newey_west_tstat, sharpe


def test_the_sharpe_convention_names_its_risk_free_rate() -> None:
    doc = sharpe.__doc__ or ""
    assert "risk-free" in doc
    assert "0" in doc, "the convention is that the rate is zero; say which zero"


def test_the_execution_convention_separates_the_entry_price_from_the_holding_return() -> None:
    doc = backtest_module.__doc__ or ""
    assert "conservative about the entry price" in doc, "the claim survives, scoped to where it holds"
    assert "not about the holding return" in doc, "and the half where it does not is stated"
    assert "-0.029" in doc, "with the size of what is dropped, measured rather than called negligible"


def test_a_validation_report_names_the_size_it_assumed() -> None:
    """DL-C1: `capital: 0` is an assumption, and a report that does not state it states it silently.

    This exists because the field was claimed as delivered on 2026-09-08 and was not - it was eaten
    when the surrounding edit was replayed, and nothing asked for it, so the next report went out
    without it and said so to nobody.  The three fields are checked together because they were added
    for one reason: a verdict has to carry the assumptions that produced it, not just its number.
    """
    import inspect

    from starquant_cli import research_cmd

    # click wraps the function in a Command; the original is on .callback
    source = inspect.getsource(research_cmd.research_validate.callback)
    for field in ('"impact_model"', '"preregistration"', '"evidence_construction"'):
        assert field in source, f"the validation report no longer carries {field}"


def test_a_wiped_out_book_does_not_report_a_drawdown_past_a_total_loss() -> None:
    """2026-09-17: `compound` and `max_drawdown` used to disagree about the same wipe-out.

    A bar at or below -100% takes the compounded path to zero or negative and `cumprod` keeps going,
    so a later +2% makes a negative equity more negative and the ratio to the running peak falls below
    -1.  `compound` has always floored at -1.0; this one did not, and returned -1.5253 on the series
    below - "a 152% drawdown" on a book that was gone at the second bar.
    """
    wiped = [0.01, -1.5, 0.02, 0.03]

    assert compound(wiped) == -1.0
    assert max_drawdown(wiped) == -1.0, "the two must agree that a wipe-out is a wipe-out"

    # The floor is a floor, not a truncation: an ordinary path is untouched, to the last digit.
    ordinary = [0.02, -0.05, 0.01, -0.03]
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for r in ordinary:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    assert max_drawdown(ordinary) == worst


def test_the_covariance_says_what_a_missing_return_means() -> None:
    """`fillna(0.0)` reads a hole in the archive as a flat bar, which biases the scalar UP."""
    doc = ewma_portfolio_vol.__doc__ or ""
    assert "FLAT bar" in doc, "the assumption is named"
    assert "biased UP" in doc, "and so is its direction - a bias with no sign is not a disclosure"
    assert "1,005 symbol-bars" in doc, "with the size of what is carried, measured"


def test_the_hac_bandwidth_says_which_series_its_default_is_for() -> None:
    """The default suits per-bar portfolio returns and not an overlapping-label series."""
    doc = newey_west_tstat.__doc__ or ""
    assert "max_lags=horizon" in doc, "the caller that must override it is named"
    assert "no longer gates anything" in doc, "and why it was left alone rather than tuned"
