"""Measure the slice dependence of the two re-fitting estimators, before and after the calendar anchor.

Run it against the pre-change tree and against the post-change tree; the numbers below are what the
test in `tests/alpha/test_refit_boundaries_are_a_calendar_not_an_offset.py` asserts qualitatively.

    python scratchpad/refit_boundary_slice_invariance.py

The panel is synthetic on purpose: this is a statement about the ESTIMATOR's dependence on where its
input frame begins, and a synthetic panel makes the comparison reproducible without touching
`.starquant/data`.  Both options are off in production (`vol_model="ewma"`, `budget_mode="inverse_vol"`),
so nothing here is a shipped number.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from starquant_alpha.features import garch_forecast_vol
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, asset_vol, risk_budget

PANEL_START = "2023-03-07 05:00"
SLICE_START = pd.Timestamp("2023-04-11 13:00", tz="UTC")


def build(n: int = 2_400, k: int = 6, seed: int = 41) -> Panel:
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
                "open_time": index,
                "open": close[symbol].to_numpy(),
                "high": (close[symbol] * 1.001).to_numpy(),
                "low": (close[symbol] * 0.999).to_numpy(),
                "close": close[symbol].to_numpy(),
                "volume": 1_000.0,
            }
        )
        for symbol in close.columns
    }
    return Panel.from_frames(frames, interval="1h")


def report(name: str, whole: pd.DataFrame, part: pd.DataFrame, skip: int) -> None:
    """Largest disagreement on the tail both frames should be able to reproduce."""
    common = part.index[skip:]
    left, right = whole.loc[common].to_numpy(), part.loc[common].to_numpy()
    seen = np.isfinite(left) & np.isfinite(right)
    absolute = np.abs(left[seen] - right[seen])
    relative = absolute / np.maximum(np.abs(right[seen]), 1e-30)
    print(
        f"{name:<28} bars={seen.sum():>6}  max_abs={absolute.max():.3e}  max_rel={relative.max():.3e}  "
        f"nan_disagreement={(np.isfinite(left) != np.isfinite(right)).sum()}"
    )


def main() -> None:
    import starquant_alpha

    # Printed because running this file directly puts `scratchpad/` on `sys.path` and NOT the working
    # directory, so an editable install silently decides which tree is being measured.  Use
    # `PYTHONPATH=. python scratchpad/...` to measure the worktree.
    print(f"starquant_alpha from {starquant_alpha.__file__}")
    panel = build()
    cut = panel.slice(start=SLICE_START)
    print(f"panel {panel.index[0]} .. {panel.index[-1]} ({len(panel.index)} bars); slice from {SLICE_START}")

    kwargs = {"fit_bars": 480, "refit_bars": 24, "min_obs": 240}
    report("garch_forecast_vol", garch_forecast_vol(panel.close, **kwargs), garch_forecast_vol(cut.close, **kwargs), 800)

    params = PortfolioParams(budget_mode="hrp", covariance_halflife=8, vol_halflife=8, hrp_refit_bars=24)

    def budget(frame: Panel, mode: str = "hrp") -> pd.DataFrame:
        sigma = asset_vol(frame.close, params, frame.bars_per_year)
        return risk_budget(sigma, frame.close.pct_change(), replace(params, budget_mode=mode))

    report("risk_budget(hrp)", budget(panel), budget(cut), 700)
    report("risk_budget(inverse_variance)", budget(panel, "inverse_variance"), budget(cut, "inverse_variance"), 700)


if __name__ == "__main__":
    main()
