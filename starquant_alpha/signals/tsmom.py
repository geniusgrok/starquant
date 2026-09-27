"""Multi-horizon time-series momentum (vectorised port of the legacy ``TrendAlpha`` formula).

Edge, stated.  The external audit in ``docs/analysis/2026-09-05-backtest-guard-external-audit.md``
asked what this is paid for and found no answer anywhere in the repo, which is a fair thing to have
been missing from the one strategy that trades.

*What it is paid for.*  Bearing trend risk that discretionary holders shed too slowly.  The
counterparty is the late leveraged long: the flow that adds exposure after a move is established and
is forced out when it reverses.  Behavioural, not structural - nothing in the perpetual's settlement
mechanics protects it - so it should be expected to decay as participants adapt, and the walk-forward
re-runs are how that is watched rather than assumed away.

*What it is not, measured rather than argued.*  It is not funding carry in disguise.  If the return
were compensation for supplying leverage to perpetual longs, the carry signal would collect it
directly.  It does not: carry in rank mode is gross -6% over five years, and round 4's reading
(RESEARCH_LOG) is that the funding rate roughly equals expected drift - funding in this universe is
fairly priced.  That closes the branch the audit raised, that tsmom and carry might be one trade
wearing two hats.

*Where funding does enter* is the crowding modifier below, and its shape argues for the statement
above rather than against it.  Re-validated 2026-09-05 under D-034's corrected funding
(``tsmom-validation-20260904T193707Z``; all five folds select the modifier), the per-fold effect is:

    fold   test period          off     on    delta
    1      2021-06 -> 2022-07   1.45   1.63   +0.18
    2      2022-07 -> 2023-07   0.50   0.90   +0.40
    3      2023-07 -> 2024-08   2.51   2.59   +0.08
    4      2024-08 -> 2025-08   1.10   1.10    0.00
    5      2025-08 -> 2026-09   2.66   2.56   -0.10

It helps most where the base is weakest and costs a little where the base is strongest.  That is a
tail-mitigation profile, not a return enhancer: shrinking a long the whole market is already paying to
hold is the strategy declining to *be* the late leveraged long, which is the edge statement applied to
itself.

*Held as a hypothesis, not a finding.*  None of this is a mechanism test.  The fold pattern is
consistent with the story and does not prove it, five folds is five observations, and the pattern was
read after the fact.  The live arbiter is M-010 income attribution over 30 days.

score = clip( (0.40*momentum + 0.25*slope + 0.10*persistence*direction) / 0.75 , -1, 1 )

momentum_h    = tanh(ret_h / max(vol, return_scale))            (momentum_mode "fixed", the validated form)
              = tanh(ret_h / (return_scale * vol * sqrt(h)))     (momentum_mode "vol_scaled", a t-statistic form)
slope_h       = tanh((ret_h / h) / slope_scale)
momentum      = sum_h w_h * momentum_h / sum_h w_h   (likewise slope)
persistence   = |mean_h sign(momentum_h)|,  direction = sign(momentum) (+1 when 0)

``vol`` is the std of *one-bar* simple returns (``vol_window=None`` reproduces
the legacy expanding population std exactly, used by the August 2026 parity
test).  Honest note (E-043): in "fixed" mode that per-bar std is always far
below ``return_scale`` (0.5%-4% hourly vs 0.20), so ``max(vol, return_scale)``
is simply ``return_scale``; the arithmetic is kept verbatim because it is what
was validated, and ``vol_window`` then only sets the NaN warmup of the rolling
std.  "vol_scaled" is the pre-registered alternative in which ``vol`` matters:
``return_scale`` becomes the number of h-bar standard deviations that saturates
the score.  At weekly horizons the slope term is nearly inert (mean |contribution|
0.02 vs 0.32 for momentum); it is likewise kept for parity.

``conviction_mode`` (H-001, pre-registered in round 7) decides whether the
score's *magnitude* is traded at all.  "score" is the validated form.  "sign"
replaces every actionable score by its sign, so the book expresses direction
only; sub-threshold scores are untouched and therefore still mean NO_ACTION,
and an exact 0.0 is still an explicit exit.  The crowding modifier, when it is
on, keeps its threshold effect (a shrunk score can fall below the entry
threshold) but loses its magnitude effect, so it is applied first.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import cross_sectional_rank, realized_vol, realized_vol_warmup, returns
from starquant_alpha.panel import Panel


@dataclass(frozen=True)
class TsmomParams:
    horizons: tuple[int, ...] = (5, 20, 50)
    horizon_weights: tuple[float, ...] = (0.2, 0.3, 0.5)
    return_weight: float = 0.40
    slope_weight: float = 0.25
    persistence_weight: float = 0.10
    return_scale: float = 0.20
    slope_scale: float = 0.01
    entry_threshold: float = 0.20
    vol_window: int | None = 200
    # Optional funding-crowding modifier (carry's only plausible role after it failed standalone):
    # when a symbol's trailing funding sits in the extreme cross-sectional rank on the *same* side as the
    # momentum score, the position is crowded and the score is shrunk by ``crowding_penalty``.
    crowding_window: int = 0
    crowding_cut: float = 0.7
    crowding_penalty: float = 0.5
    momentum_mode: str = "fixed"  # fixed | vol_scaled (see module docstring)
    conviction_mode: str = "score"  # score | sign (H-001: trade direction only, see module docstring)

    def __post_init__(self) -> None:
        if len(self.horizons) != len(self.horizon_weights) or not self.horizons:
            raise ValueError("horizons and horizon_weights must align")
        if any(h <= 0 for h in self.horizons) or any(w < 0 for w in self.horizon_weights):
            raise ValueError("horizons must be positive and weights non-negative")
        if sum(self.horizon_weights) <= 0:
            raise ValueError("horizon_weights must have positive mass")
        if self.return_scale <= 0 or self.slope_scale <= 0:
            raise ValueError("scales must be positive")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")
        if self.crowding_window < 0 or not 0 < self.crowding_cut <= 1 or not 0 <= self.crowding_penalty <= 1:
            raise ValueError("invalid crowding parameters")
        if self.momentum_mode not in {"fixed", "vol_scaled"}:
            raise ValueError("momentum_mode must be 'fixed' or 'vol_scaled'")
        if self.conviction_mode not in {"score", "sign"}:
            raise ValueError("conviction_mode must be 'score' or 'sign'")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> TsmomParams:
        values = dict(params)
        for key in ("horizons", "horizon_weights"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)

    @property
    def warmup_bars(self) -> int:
        """Both terms bind: the longest return needs its horizon, and every score divides by ``realized_vol``.

        Reporting only the horizon understated the 5/20/50 defaults by 50 bars (declared 51, first
        non-NaN score at 101 under ``vol_window`` 200).  The weekly configuration that runs live is
        unaffected - 721 dominates the 201 its ``vol_window`` 400 needs - but D-022 sizes the live
        request window from this number, so a shorter horizon would have silently shortened it.
        """
        return max(max(self.horizons) + 1, realized_vol_warmup(self.vol_window))

    @property
    def uses_funding(self) -> bool:
        """The crowding modifier is the only part of tsmom that reads funding history."""
        return self.crowding_window > 0 and self.crowding_penalty > 0


def _tanh(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.tanh(frame.to_numpy(dtype=float)), index=frame.index, columns=frame.columns)


def tsmom_scores(close: pd.DataFrame, params: TsmomParams | None = None) -> pd.DataFrame:
    p = params or TsmomParams()
    vol = realized_vol(close, window=p.vol_window, ddof=0)
    denominator = vol.clip(lower=p.return_scale).clip(lower=1e-12)
    weight_total = float(sum(p.horizon_weights))
    momentum_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    slope_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    sign_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    valid = pd.DataFrame(True, index=close.index, columns=close.columns)
    for horizon, weight in zip(p.horizons, p.horizon_weights, strict=True):
        ret = returns(close, horizon)
        if p.momentum_mode == "vol_scaled":
            scale = (vol * math.sqrt(horizon) * p.return_scale).clip(lower=1e-12)
            momentum_h = _tanh(ret / scale)
        else:
            momentum_h = _tanh(ret / denominator)
        slope_h = _tanh((ret / horizon) / p.slope_scale)
        valid &= momentum_h.notna()
        momentum_sum = momentum_sum + momentum_h.fillna(0.0) * weight
        slope_sum = slope_sum + slope_h.fillna(0.0) * weight
        sign_sum = sign_sum + momentum_h.fillna(0.0).apply(np.sign)
    momentum = momentum_sum / weight_total
    slope = slope_sum / weight_total
    persistence = (sign_sum / len(p.horizons)).abs()
    direction = pd.DataFrame(np.where(momentum >= 0, 1.0, -1.0), index=close.index, columns=close.columns)
    component_weight = p.return_weight + p.slope_weight + p.persistence_weight
    score = (
        momentum * p.return_weight + slope * p.slope_weight + persistence * direction * p.persistence_weight
    ) / component_weight
    return score.clip(-1.0, 1.0).where(valid)


def apply_crowding_modifier(
    score: pd.DataFrame,
    funding: pd.DataFrame | None,
    p: TsmomParams,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Shrink same-direction scores where trailing funding is in the extreme cross-sectional rank.

    ``reference`` is the population the rank is taken over (P1-01 / DL-Q1).  Ranking over
    every column the caller loaded made this modifier a different signal on each path:
    research ranked a symbol against ~123 names, the live loop against 15-18, and a
    ``crowding_cut`` of 0.7 marks a fixed 20% of a 15-name panel against 15% of a wide one.
    The trailing sum still reads the symbol's own full history, so a name that re-enters
    the universe is rankable on its first bar of membership.
    """
    crowded = crowding_mask(score, funding, p, reference)
    if crowded is None:
        return score
    return score.mask(crowded, score * (1.0 - p.crowding_penalty))


def crowding_mask(
    score: pd.DataFrame,
    funding: pd.DataFrame | None,
    p: TsmomParams,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    """Which cells the modifier shrinks, or ``None`` when it is switched off.

    Extracted so the instrument below can count what the modifier did without recomputing a
    counterfactual book.  ``apply_crowding_modifier`` is the only consumer that shrinks.
    """
    if p.crowding_window <= 0 or funding is None or p.crowding_penalty <= 0:
        return None
    aligned = funding.reindex(index=score.index, columns=score.columns)
    trailing = aligned.rolling(p.crowding_window, min_periods=p.crowding_window).sum()
    observed = aligned.abs().rolling(p.crowding_window, min_periods=p.crowding_window).sum() > 0
    rank = cross_sectional_rank(trailing.where(observed), reference).fillna(0.0)
    crowded_long = (score > 0) & (rank >= p.crowding_cut)
    crowded_short = (score < 0) & (rank <= -p.crowding_cut)
    return crowded_long | crowded_short


def crowding_effect(panel: Panel, params: Mapping[str, Any]) -> dict[str, Any]:
    """M-018: what the crowding modifier did on the decision bar, separating shrunk from decisive.

    "The modifier is running" has been readable only as ``inputs.funding_history: true``, which says the
    INPUT arrived, not that the modifier bit - the D-038 shape, and the reason it went 37 live cycles
    inert while the registry cited it (D-042's correction).  Two counts, because under
    ``conviction_mode: sign`` they differ by a factor of about two:

    * ``shrunk`` - cells the modifier multiplied by ``1 - crowding_penalty``.
    * ``decisive`` - cells where that multiplication changed what the book HOLDS.  Under ``sign`` a
      position is +-1 either way, so a shrink only matters when it drops the score under
      ``entry_threshold``: measured over 2021-2026 that is 9.87% of cells against 17.78% of shrinks,
      i.e. sign mode absorbs 44.5% of the modifier.  Under ``score`` every shrink is decisive.

    Derived from the mask and the pre-shrink score, never from a second ``compute`` call: a
    counterfactual book would be a second answer to a question the mask already answers exactly.
    """
    p = TsmomParams.from_mapping(params)
    raw = tsmom_scores(panel.close, p)
    crowded = crowding_mask(raw, panel.funding, p, panel.reference)
    if crowded is None or raw.empty:
        return {"enabled": False, "shrunk": 0, "decisive": 0, "eligible": 0}
    bar, shrunk = raw.index[-1], crowded.loc[raw.index[-1]]
    row = raw.loc[bar]
    if p.conviction_mode == "sign":
        decisive = (
            shrunk & (row.abs() >= p.entry_threshold) & (row.abs() * (1.0 - p.crowding_penalty) < p.entry_threshold)
        )
    else:
        decisive = shrunk
    return {
        "enabled": True,
        "shrunk": int(shrunk.sum()),
        "decisive": int(decisive.sum()),
        "eligible": int(row.notna().sum()),
    }


def apply_conviction_mode(score: pd.DataFrame, p: TsmomParams) -> pd.DataFrame:
    """H-001: in "sign" mode an actionable score becomes +-1; everything else passes through.

    Only ``|score| >= entry_threshold`` is rewritten, so the actionable set, the
    NO_ACTION (hold) stretches and the explicit 0.0 exits are exactly the ones
    "score" mode produces.  The result equals ``sign`` of the target frame the
    validated configuration would have held.
    """
    if p.conviction_mode != "sign":
        return score
    actionable = score.abs() >= p.entry_threshold
    signs = pd.DataFrame(np.sign(score.to_numpy(dtype=float)), index=score.index, columns=score.columns)
    return score.mask(actionable, signs)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    p = TsmomParams.from_mapping(params)
    reference = panel.reference
    crowded = apply_crowding_modifier(tsmom_scores(panel.close, p), panel.funding, p, reference)
    return apply_conviction_mode(crowded, p)
