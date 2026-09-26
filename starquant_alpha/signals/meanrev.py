"""Short-horizon robust mean reversion (vectorised port of ``MeanReversionEngine``).

z = (close - rolling median) / (1.4826 * rolling MAD) over ``window`` bars.
Enter against the dislocation when |z| >= z_entry (score = -clip(z / z_max)),
emit an explicit exit (0.0) once |z| < z_exit, hold in between (NaN).  A
trend gate blocks entries when the trailing move is a strong trend
(|ret_window| / (vol * sqrt(window)) > trend_gate_z), mirroring the legacy
"RANGING only" regime gate.

``max_hold_bars`` is the time stop round 1 asked for on 2026-09-03 and nobody
built (docs/RESEARCH_LOG.md:12, :23, :60; the reopen condition ruled on
2026-09-17).  It exists because this signal's information is real and its
losses are not where the information is: on the point-in-time universe the
1h cross-sectional IC is +0.0159 at NW t 7.64 and the time-series IC is
positive at all seven horizons, while the equal-notional zero-cost Sharpe is
-0.62.  The ranking is right; the tail eats it.  In the 720-bar non-overlapping
buckets the SHORT bucket's mean forward return is +14.77% - the names it sold
went up 15% on average - which is the "尾部趋势延续时持仓亏大钱" of round 1
stated in numbers.  A dislocation that keeps widening never re-enters the exit
zone, so without a clock the position is held into exactly that tail.

Off by default (``0``), so every archived meanrev report reproduces bit for bit.  **It is off because
it was measured and it does not work**, not because it is untested: on the same pit panel, eight cells
of (``trend_gate_z``, ``max_hold_bars``) all came back worse than the baseline's -0.62 zero-cost Sharpe
(-0.66 at 48 bars, -0.76/-0.80 at 12/24, down to -0.87 at the tightest gate), and the reopen condition
ruled on 2026-09-17 asked for that number to turn POSITIVE before anything goes to `validate`.

The shape of the failure is the informative part and it refutes round 1's mechanism.  Tightening the
clock and the gate does cut the absolute loss - gross -0.0981 -> -0.0637 - but it cuts it by cutting
exposure (0.062 -> 0.026), and the Sharpe gets worse doing it.  A stop that were really catching the
tail would improve return per unit of risk; this one takes the good holds out with the bad.  So
meanrev's losses are not concentrated in positions held too long, and "尾部趋势延续时持仓亏大钱"
names a real tail (the 720-bar short bucket averages +14.77% forward) that a clock cannot reach,
because that tail is already under way early in the hold.  See docs/RESEARCH_LOG.md 2026-09-17
「时间止损实现了，八格全负」.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import realized_vol, realized_vol_warmup, returns, robust_zscore, robust_zscore_warmup
from starquant_alpha.panel import Panel


@dataclass(frozen=True)
class MeanrevParams:
    window: int = 48
    z_entry: float = 1.5
    z_exit: float = 0.5
    z_max: float = 5.0
    trend_gate_z: float = 2.0
    vol_window: int = 48
    entry_threshold: float = 0.20
    #: Bars a position may be held before it is closed regardless of ``z``.  0 disables the clock.
    max_hold_bars: int = 0

    def __post_init__(self) -> None:
        if self.window < 10 or self.z_max <= 0 or self.z_entry <= self.z_exit or self.z_exit < 0:
            raise ValueError("invalid mean-reversion parameters")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")
        if self.max_hold_bars < 0:
            raise ValueError("max_hold_bars must be >= 0")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> MeanrevParams:
        return cls(**dict(params))

    @property
    def warmup_bars(self) -> int:
        """The z-score dominates: its MAD is a rolling median of a rolling deviation, so it needs two windows.

        ``max(window, vol_window) + 1`` reported 49 for the defaults while the first non-NaN score is at
        bar 95.  The trend gate's own inputs (an h-bar return and ``realized_vol``) are cheaper but are
        kept explicit so a future parameter change cannot make one of them the binding term unnoticed.

        The clock is added because it is path-dependent: `_expire` reads the position a downstream hold
        would be carrying, and it can only see the trades that opened inside the frame it is given.  A
        live window shorter than warmup + ``max_hold_bars`` would date a position from the window's own
        first bar and so hold it past the stop.  Adding the term makes the rule self-consistent - if the
        clock is enforced, no live position is older than ``max_hold_bars``, so its open is always in view.
        """
        return max(
            robust_zscore_warmup(self.window),
            self.window + 1,
            realized_vol_warmup(self.vol_window),
            self.max_hold_bars + 1,
        )


def meanrev_scores(close: pd.DataFrame, params: MeanrevParams | None = None) -> pd.DataFrame:
    p = params or MeanrevParams()
    z = robust_zscore(close, p.window)
    trailing = returns(close, p.window)
    vol = realized_vol(close, p.vol_window, ddof=0)
    trend_strength = (trailing / (vol * np.sqrt(p.window))).abs()
    entry = (z.abs() >= p.z_entry) & (trend_strength <= p.trend_gate_z)
    exit_zone = z.abs() < p.z_exit
    score = (-(z / p.z_max)).clip(-1.0, 1.0)
    result = score.where(entry)
    result = result.mask(exit_zone & z.notna(), 0.0)
    result = _expire(result, p)
    return result.where(z.notna())


def _expire(scores: pd.DataFrame, p: MeanrevParams) -> pd.DataFrame:
    """Close a position that has been held ``max_hold_bars`` bars, and keep it closed for that leg.

    The age is counted on the position a downstream ``scores_to_targets(hold=True)`` would carry, not on
    the raw score, because that is the thing being held: sub-threshold bars are NaN here and the hold
    makes them a position.  So the trade this dates is the ffilled one, and a bar that merely re-states
    the same side - a dislocation widening from z 2.0 to 2.5 - adds to the open trade rather than
    starting a new one.  That is the case the stop exists for, so it must not reset the clock.

    **Once expired, the leg stays flat until the signal itself lets go.**  Emitting a single 0.0 and then
    allowing the next in-threshold bar to re-open would make the rule cost turnover and change nothing:
    the z that held the position past the stop is still past ``z_entry`` on the next bar.  The leg
    therefore stays at 0.0 for as long as the ffilled side is unchanged, which ends only when ``z`` falls
    back inside the exit zone (an explicit 0.0) or crosses to the other side.  Both of those are the
    signal changing its mind rather than the clock being argued with.
    """
    if p.max_hold_bars <= 0:
        return scores
    actionable = scores.where(scores.abs() >= p.entry_threshold).mask(scores == 0.0, 0.0)
    signs = np.sign(actionable.ffill().to_numpy(dtype=float))
    side = pd.DataFrame(signs, index=scores.index, columns=scores.columns).fillna(0.0)
    opened = side.ne(side.shift(1)) & side.ne(0.0)
    rows = np.arange(len(scores), dtype=float)[:, None]
    starts = pd.DataFrame(np.where(opened.to_numpy(), rows, np.nan), index=scores.index, columns=scores.columns)
    age = rows - starts.ffill().to_numpy()
    expired = (age >= p.max_hold_bars) & (side.to_numpy() != 0.0)
    return scores.mask(pd.DataFrame(expired, index=scores.index, columns=scores.columns), 0.0)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return meanrev_scores(panel.close, MeanrevParams.from_mapping(params))
