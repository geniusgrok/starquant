"""P30: a per-bar gross cap on a non-main book, applied before its fraction (2026-09-12).

P21 rejected `mined_594a12f9307a15d9` on one check of six - `oos_mdd_worsening` 4.98pp against a 1pp
gate - and diagnosed it as construction rather than parameter: the sleeve's mean absolute exposure is
1.372 against tsmom's 0.859, so a third of that sleeve is not a third of the main book's risk budget,
and "drawdown follows exposure rather than the budget".

The cap is deliberately narrow, and each of the three tests below pins one of the three properties the
pre-registration fixed BEFORE any P&L was computed:

* it applies to non-main books only (the main book's own gross is `max_gross`'s job, and the two must
  not stack);
* it applies BEFORE the fraction, so `fraction` keeps the meaning D-019 claims for it - a proportion of
  the main book's risk budget - instead of quietly becoming a proportion of an arbitrarily sized book;
* off is off.  `sleeve_max_gross = 0` must leave every weight bit-identical, because this change ships
  into a loop that is holding positions: F1 of the pre-registration, and the same shape as the F1 that
  guarded `book_weights` reaching disk four days ago.
"""

from __future__ import annotations

from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, build_weights, cap_gross, combine_books
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams
from tests.alpha.test_causality import _bit_for_bit

TSMOM = {**TsmomParams(vol_window=100).__dict__, "horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
BREAKOUT = {**asdict(BreakoutParams()), "entry_threshold": 0.05}
FRACTION = 0.5


def _model(params: PortfolioParams) -> tuple[AlphaModel, StrategyEntry, StrategyEntry]:
    main = StrategyEntry("tsmom", params=TSMOM)
    sleeve = StrategyEntry("breakout", params=BREAKOUT, book="sleeve")
    model = AlphaModel(
        entries=(main, sleeve),
        portfolio=params,
        interval="1h",
        min_history_bars=0,
        books={"sleeve": FRACTION},
    )
    return model, main, sleeve


def test_cap_gross_only_scales_down_and_leaves_nan_rows_alone() -> None:
    frame = pd.DataFrame(
        [[0.4, -0.4], [0.1, 0.1], [np.nan, np.nan]],
        columns=["A", "B"],
        index=pd.RangeIndex(3),
    )
    capped = cap_gross(frame, 0.5)
    assert capped.iloc[0].abs().sum() == pytest.approx(0.5)  # 0.8 -> 0.5
    assert capped.iloc[0]["A"] / capped.iloc[0]["B"] == pytest.approx(-1.0)  # shape preserved
    pd.testing.assert_series_equal(capped.iloc[1], frame.iloc[1])  # 0.2 is under the cap: untouched
    assert capped.iloc[2].isna().all()  # a row with no decision stays undecided
    pd.testing.assert_frame_equal(cap_gross(frame, 0.0), frame)  # 0 is off, not "cap everything to zero"


def test_the_cap_is_off_by_default_and_the_two_book_path_stays_bit_identical(august_panel: Panel) -> None:
    """F1.  The pre-registration's hardest condition: adding the knob moves no weight while it is off."""
    params = PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.10, no_trade_band=0.005)
    assert params.sleeve_max_gross == 0.0
    model, _main, _sleeve = _model(params)
    weights, _combined, per = model.evaluate(august_panel)
    bare = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    bpy = august_panel.bars_per_year
    expected = combine_books(
        {
            "main": build_weights(per["tsmom"], august_panel.close, bpy, bare),
            "sleeve": build_weights(per["breakout"], august_panel.close, bpy, bare) * FRACTION,
        },
        params,
    )
    _bit_for_bit(weights, expected)


def test_the_cap_binds_the_sleeve_before_its_fraction_and_never_the_main_book(august_panel: Panel) -> None:
    """The sleeve's OWN gross is what is capped, so the contribution is `min(gross, cap) * fraction`.

    Capping after the fraction would give `min(gross * fraction, cap)` - a different book, and one in
    which `fraction` and `cap` are not separable.  The two differ whenever the cap binds, which is the
    whole point of running the arm.
    """
    cap = 0.30
    params = PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.10, sleeve_max_gross=cap)
    model, _main, _sleeve = _model(params)
    bare = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    bpy = august_panel.bars_per_year
    _weights, _combined, per = model.evaluate(august_panel)
    raw_sleeve = build_weights(per["breakout"], august_panel.close, bpy, bare)
    raw_main = build_weights(per["tsmom"], august_panel.close, bpy, bare)
    books = model.book_weights(per, august_panel.close, bpy)

    assert raw_sleeve.abs().sum(axis=1).max() > cap, "fixture must actually reach the cap or it proves nothing"
    pd.testing.assert_frame_equal(books["main"], raw_main)  # the main book is `max_gross`'s business
    pd.testing.assert_frame_equal(books["sleeve"], cap_gross(raw_sleeve, cap) * FRACTION)
    decided = books["sleeve"].dropna(how="all")
    assert (decided.abs().sum(axis=1) <= cap * FRACTION + 1e-12).all()


def test_capping_is_not_the_same_book_as_lowering_the_fraction(august_panel: Panel) -> None:
    """F2's mechanism, as an identity rather than as a measurement.

    A cap binds only on the bars above it; a smaller fraction scales every bar.  If the two were the
    same operation the experiment would be a fraction change wearing a different name, which is what
    the pre-registration forbids choosing after the fact.
    """
    cap = 0.30
    params = PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.10, sleeve_max_gross=cap)
    model, _main, _sleeve = _model(params)
    bpy = august_panel.bars_per_year
    _w, _c, per = model.evaluate(august_panel)
    bare = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    raw = build_weights(per["breakout"], august_panel.close, bpy, bare)
    capped = cap_gross(raw, cap)
    gross = raw.abs().sum(axis=1)
    binding = gross > cap
    assert binding.any() and not binding.all(), "the cap must bind on some bars and not others"
    # under the cap the two books are identical; above it they are not proportional to each other
    _bit_for_bit(capped[~binding], raw[~binding])
    scaled = raw * float((capped.abs().sum(axis=1).sum()) / gross.sum())  # the exposure-matched fraction
    assert not np.allclose(capped.fillna(0.0).to_numpy(), scaled.fillna(0.0).to_numpy()), (
        "a cap that equals a uniform rescaling would make F2 unanswerable"
    )
