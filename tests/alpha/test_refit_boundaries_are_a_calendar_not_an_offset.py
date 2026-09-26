"""Slice invariance for the two re-fitting estimators: the same bar must read the same on any window.

D-033's lesson, applied one layer up.  There it was a live recursion rebuilt every cycle on a request
window that slides one bar, so the latch point was an artefact of where the window started; here the
re-fit cadence was `range(start, n, refit_bars)` and `t % refit_bars == 0`, both counted off row 0 of
whatever frame the caller passed.  The same calendar bar therefore re-fitted in one window and sat
mid-block in another, and the measured consequence was a weight moving 9.69e-4 between a 1,442-bar and
a 1,443-bar request for that reason alone.

Both estimators are OFF by default (`vol_model="ewma"`, `budget_mode="inverse_vol"`; #35 and #48 are
both REFUTED), so nothing here changes a shipped number.  The test exists because the defect is only
expensive if one of them is ever re-opened, and by then the live loop is the thing exhibiting it.

The two comparisons are deliberately not the same strength, and the difference is the point:

* GARCH is EXACT.  Its block is a pure function of the trailing fitting window - parameters and the
  filter state alike - so any frame carrying that window reproduces the block bit for bit.
* HRP is exact in its BOUNDARIES and approximate in its level, because the EWMA covariance it clusters
  on starts from zero on each frame's first row.  The tolerance below is that warm-up and nothing
  else: after k bars the zero start still carries weight 2^(-k/halflife), which is 2^-50 for the
  burn-in this test uses.  A tolerance from a decaying, bounded, named quantity is a different object
  from a discrepancy nobody had measured.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from starquant_alpha.features import garch_forecast_vol, refit_boundaries
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, asset_vol, risk_budget
from tests.alpha.test_causality import _bit_for_bit

# Deliberately not midnight and deliberately not a multiple of anything: a panel whose first bar
# happened to sit on the grid would pass a positional implementation too.
PANEL_START = "2023-03-07 05:00"
SLICE_START = pd.Timestamp("2023-04-11 13:00", tz="UTC")
HALFLIFE = 8
BURN_IN = 400  # bars after the slice's first re-cluster; 2^(-400/8) is 8.9e-16


def _panel(n: int = 2_400, k: int = 6, seed: int = 41) -> Panel:
    """Closes with real cross-sectional correlation, so HRP has something to cluster."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 0.01, size=(n, 2))
    loadings = rng.normal(size=(2, k))
    noise = rng.normal(0.0, 0.004, size=(n, k)) * rng.uniform(0.5, 2.0, size=k)
    returns = factor @ loadings + noise
    index = pd.date_range(PANEL_START, periods=n, freq="h", tz="UTC")
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"S{i}" for i in range(k)])
    frames = {
        symbol: pd.DataFrame(
            {
                "open_time": close.index,
                "open": close[symbol],
                "high": close[symbol] * 1.001,
                "low": close[symbol] * 0.999,
                "close": close[symbol],
                "volume": 1_000.0,
            }
        )
        for symbol in close.columns
    }
    return Panel.from_frames(frames, interval="1h")


def test_the_boundaries_are_the_same_timestamps_however_the_frame_is_cut() -> None:
    """The property everything below rests on, asserted directly on the helper."""
    index = pd.date_range(PANEL_START, periods=500, freq="h", tz="UTC")
    whole = {index[position] for position in refit_boundaries(index, 24)}
    cut = index[137:]
    part = {cut[position] for position in refit_boundaries(cut, 24)}
    assert part and part < whole, "a slice's boundaries must be the panel's boundaries, restricted"
    assert all(stamp.hour == 0 for stamp in whole), "a 24-bar cadence on 1h bars is midnight UTC"
    # The floor is a floor on the first boundary, never a new origin: shifting it must only drop
    # boundaries from the front, never move the ones that remain.
    assert {index[p] for p in refit_boundaries(index, 24, 100)} == {s for s in whole if s >= index[100]}


def test_a_panel_that_starts_later_gets_the_same_garch_forecast_bit_for_bit() -> None:
    kwargs = {"fit_bars": 480, "refit_bars": 24, "min_obs": 240}
    panel = _panel()
    whole = garch_forecast_vol(panel.close, **kwargs)
    part = garch_forecast_vol(panel.slice(start=SLICE_START).close, **kwargs)

    # The bars both frames can possibly agree on: at or after the slice's first boundary whose whole
    # fitting window the slice also carries.  Anything earlier is a fit the slice does not have the
    # data for, which is a fact about the slice and not about the cadence.
    first = part.index[refit_boundaries(pd.DatetimeIndex(part.index), 24, 240)[0]]
    common = part.index[part.index >= first + pd.Timedelta(hours=kwargs["fit_bars"])]
    assert len(common) > 800, "the comparison must not be a handful of bars"
    assert whole.loc[common].notna().to_numpy().all(), "nor NaN against NaN"
    _bit_for_bit(whole.loc[common], part.loc[common])

    # The control: this test would pass on any implementation if the slice simply reproduced the whole
    # panel, so check that the two genuinely differ where the slice lacks the history.
    head = part.index[part.index < first]
    assert not whole.loc[head].equals(part.loc[head])


def test_a_panel_that_starts_later_gets_the_same_hrp_budget_up_to_the_ewma_warm_up() -> None:
    # BOTH half-lives are shortened, and the reason is the tolerance itself: the budget carries two
    # warm-starts, the HRP covariance and the `ewm_vol` divisor, and the slower of the two sets the
    # floor.  At the shipped `vol_halflife=48` the divisor alone still differs by 7e-4 relative after
    # 400 bars (2^(-400/48)), which would have been read as "the clustering disagrees".
    params = PortfolioParams(budget_mode="hrp", covariance_halflife=HALFLIFE, vol_halflife=HALFLIFE, hrp_refit_bars=24)
    panel = _panel()
    cut = panel.slice(start=SLICE_START)

    def budget(frame: Panel, mode: str = "hrp") -> pd.DataFrame:
        sigma = asset_vol(frame.close, params, frame.bars_per_year)
        return risk_budget(sigma, frame.close.pct_change(), replace(params, budget_mode=mode))

    whole, part = budget(panel), budget(cut)
    first = refit_boundaries(pd.DatetimeIndex(cut.index), params.hrp_refit_bars)[0]
    common = cut.index[first + BURN_IN :]
    assert len(common) > 800
    # 2^(-BURN_IN/HALFLIFE) = 8.9e-16 of each estimate is still the zero its own frame started from,
    # and the clustering is a continuous function of it away from an exact tie in the linkage.
    np.testing.assert_allclose(whole.loc[common].to_numpy(), part.loc[common].to_numpy(), rtol=1e-9, atol=1e-12)
    # The tilt is doing something here; without this the test could pass on a budget that ignores HRP.
    assert np.nanmax(np.abs(whole.to_numpy() - budget(panel, "inverse_variance").to_numpy())) > 1e-3


def test_an_index_with_no_usable_grid_falls_back_instead_of_refusing_to_fit() -> None:
    """A caller can hand these functions something that is not a bar grid; it must still produce blocks."""
    stuck = pd.DatetimeIndex([pd.Timestamp("2024-01-01", tz="UTC")] * 5)
    assert refit_boundaries(stuck, 2, 1) == [1, 3], "a degenerate index falls back to the positional cadence"
    assert refit_boundaries(pd.DatetimeIndex([]), 24) == []
    # Naive stamps are read as UTC, the way every other entry point in this package reads them.
    naive = pd.date_range("2024-01-01 05:00", periods=50, freq="h")
    assert refit_boundaries(naive, 24) == refit_boundaries(naive.tz_localize("UTC"), 24)
