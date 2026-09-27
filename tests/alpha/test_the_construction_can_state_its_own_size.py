"""Three quantities the book could not say about itself (2026-09-17, layer 0 ④).

Two of them are about the construction rather than about a symbol, and the reason they are worth a
field each is that `vol_target` is the number everything else is argued from:

* **`portfolio_vol`** - the ex-ante annualised volatility of the weights AS THEY LEAVE THE MODEL.
  Stage 2 targets the volatility of stage 1; `combine_books` then sums sleeves without re-targeting
  (a 1/3 sleeve took the 2026-09-07 book from 32.24% to 35.66%, +10.6%), and `max_weight` takes some
  of it back off.  So the vol the loop holds is neither of the two numbers that were measured, and
  nothing recorded it.
* **`clipped_risk_share`** - how much of the requested |weight| the per-symbol cap removed (GAP-AM02).
  At `vol_target` 0.60 the cap binds on 49 of the 95 cycles that carry per-book weights, on BTCUSDT
  and BNBUSDT only, because inverse-vol sizing necessarily hands the largest weight to the calmest
  name.  The count was recorded; the RISK it removes was not - and P13's "scaling every weight by k
  leaves net Sharpe exactly unchanged, so the dial carries no alpha" holds only while the cap is not
  binding, which is the reading the count cannot supply.
* **`symbols_settled`** - the live twin of `Panel.settled_symbols`.  `funding_history is not None`
  says a frame was FETCHED; it stayed true for 37 cycles while the modifier was inert (D-042), and a
  symbol with no archive returns a column of zeros the modifier cannot tell from calm funding.

All three are observability.  The extraction that makes the second one exact - `vol_targeted`, which
`build_weights` now calls - is held to bit-for-bit reproduction below, because a diagnostic that
rebuilds its own copy of stage 1 and stage 2 can disagree with the book while both look right.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.ensemble import TargetWeights
from starquant_alpha.portfolio import (
    PortfolioParams,
    build_weights,
    cap_gross,
    clipped_risk_share,
    ewma_portfolio_vol,
    vol_targeted,
)

BARS_PER_YEAR = 8760.0


def _panel(bars: int = 400, symbols: int = 4, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=bars, freq="h", tz="UTC")
    # Deliberately unequal volatilities: inverse-vol sizing is what makes the cap bind on one name.
    steps = rng.normal(0.0, 1.0, size=(bars, symbols)) * np.array([0.0004, 0.004, 0.008, 0.02])
    return pd.DataFrame(100.0 * np.exp(np.cumsum(steps, axis=0)), index=index, columns=list("ABCD"))


def _targets(close: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=close.index, columns=close.columns)


def test_extracting_the_two_stages_reproduces_build_weights_bit_for_bit() -> None:
    """The seam, pinned: cap and gross-cap the extracted stages and the shipped path comes back."""
    close = _panel()
    params = PortfolioParams(vol_target=0.60, max_weight=0.15, max_gross=2.0)
    aligned = _targets(close)
    rebuilt = cap_gross(
        vol_targeted(aligned, close, BARS_PER_YEAR, params).clip(-params.max_weight, params.max_weight),
        params.max_gross,
    ).where(aligned.notna().any(axis=1).cummax(), other=np.nan)
    shipped = build_weights(aligned, close, BARS_PER_YEAR, params)
    assert np.array_equal(shipped.to_numpy().view(np.uint64), rebuilt.to_numpy().view(np.uint64)), (
        "the extraction moved a weight"
    )


def test_the_cap_removes_risk_and_the_share_says_how_much() -> None:
    close = _panel()
    params = PortfolioParams(vol_target=0.60, max_weight=0.05, max_gross=99.0)
    sized = vol_targeted(_targets(close), close, BARS_PER_YEAR, params)
    share = clipped_risk_share(sized, params)
    assert share.max() > 0.0, "a 5% cap against a 60% vol target has to bind on the calmest name"
    assert (share >= 0.0).all() and (share <= 1.0).all()
    # ...and it is exactly what the clip took off, on the bar where it took the most.
    bar = share.idxmax()
    requested, kept = sized.loc[bar].abs().sum(), sized.loc[bar].clip(-0.05, 0.05).abs().sum()
    assert share.loc[bar] == pytest.approx(1.0 - kept / requested)


def test_a_cap_that_never_binds_removes_nothing() -> None:
    close = _panel()
    loose = PortfolioParams(vol_target=0.15, max_weight=10.0)
    assert clipped_risk_share(vol_targeted(_targets(close), close, BARS_PER_YEAR, loose), loose).max() == 0.0


def test_the_book_leaves_the_model_under_its_target_when_the_cap_binds() -> None:
    """The reading P13's identity needs and the count could not give: capped weights carry less risk."""
    close = _panel()
    capped = PortfolioParams(vol_target=0.60, max_weight=0.05, max_gross=99.0)
    loose = PortfolioParams(vol_target=0.60, max_weight=10.0, max_gross=99.0)
    returns = close.pct_change()
    ex_ante = {
        name: ewma_portfolio_vol(
            returns,
            build_weights(_targets(close), close, BARS_PER_YEAR, params),
            params.covariance_halflife,
            BARS_PER_YEAR,
        ).iloc[-1]
        for name, params in (("capped", capped), ("loose", loose))
    }
    assert ex_ante["capped"] < ex_ante["loose"], ex_ante
    assert ex_ante["loose"] == pytest.approx(0.60, rel=0.25), "stage 2 should land near the target when free"


def test_the_snapshot_carries_them_and_none_is_not_zero() -> None:
    """`None` means the model could not compute it, which is a different fact from 0.0 (D-035's rule)."""
    empty = TargetWeights(as_of=pd.Timestamp("2026-01-01", tz="UTC"), weights={})
    assert empty.portfolio_vol is None and empty.clipped_risk_share is None


def test_the_live_model_computes_both_without_moving_a_weight() -> None:
    """The falsifier `test_recording_the_book_weights_changes_no_weight` states: observability that
    moves a traded weight is not observability."""
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.panel import Panel
    from starquant_alpha.registry import StrategyEntry

    close = _panel(bars=900)
    bars = {
        symbol: pd.DataFrame(
            {
                "open": close[symbol],
                "high": close[symbol],
                "low": close[symbol],
                "close": close[symbol],
                "volume": 1_000.0,
            },
            index=close.index,
        )
        for symbol in close.columns
    }
    entry = StrategyEntry(id="tsmom", params={"horizons": [5, 20, 50], "vol_window": 50, "crowding_window": 0})
    model = AlphaModel(
        entries=(entry,), portfolio=PortfolioParams(vol_target=0.60), interval="1h", min_history_bars=100
    )
    out = model.targets(bars, {})
    panel = Panel.from_frames(bars, interval="1h")
    weights, _combined, _per = model.evaluate(panel, None, band=False)
    assert out.weights == {str(s): float(v) for s, v in weights.iloc[-1].fillna(0.0).items()}
    assert out.portfolio_vol is not None and out.portfolio_vol > 0.0
    assert out.clipped_risk_share is not None and 0.0 <= out.clipped_risk_share <= 1.0


def test_a_column_of_zeros_is_not_a_settlement() -> None:
    """`Panel.settled_symbols`' rule, on the live side: "was it requested" is not "did any arrive"."""
    from starquant_live.inputs import ModelInputs

    index = pd.date_range("2026-01-01", periods=4, freq="8h", tz="UTC")
    frame = pd.DataFrame({"open_time": [0, 1, 2, 3], "close": [1.0, 1.0, 1.0, 1.0]})
    inputs = ModelInputs(
        bars={"A": frame, "B": frame},
        funding={},
        funding_history={"A": pd.Series([0.0] * 4, index=index), "B": pd.Series([1e-4, 0.0, 0.0, 0.0], index=index)},
    )
    assert inputs.to_dict()["symbols_settled"] == 1
    assert inputs.to_dict()["funding_history"] is True, "the flag still says a frame arrived"
    assert ModelInputs(bars={"A": frame}, funding={}).to_dict()["symbols_settled"] == 0
