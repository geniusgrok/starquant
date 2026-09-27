"""Order-flow imbalance: taker-buy share of quote volume, scaled by volume expansion (new).

imbalance = taker_buy_quote / quote_volume - 0.5  over ``window`` bars
score = clip(tanh(imbalance / scale) * min(1, vol_ratio), -1, 1)

Requires ``taker_buy_quote`` and ``quote_volume`` in the panel (present in the
official archives); returns NaN otherwise.  Optionally cross-sectionally
demeaned so the book is market-neutral.

Short-side trend gate (round 5).  Perp taker *selling* into a strongly rising
market is hedging and short-selling into strength, not informed flow: the
price is being driven by spot demand the perp tape cannot see, and those
shorts are what got squeezed in 2024-11 (XRP/ADA/SUI).  With ``short_gate``
> 0 a negative score is replaced by an explicit exit (0.0) while the symbol's
weekly-scale momentum score is >= ``short_gate``.  Longs against downtrends
are deliberately left alone: the symmetric gate destroyed the 2022 bear-market
folds, where dip-buying flow was the profitable leg.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import apply_numpy, taker_buy_ratio, volume_ratio, within_reference
from starquant_alpha.panel import Panel
from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores


@dataclass(frozen=True)
class FlowParams:
    window: int = 24
    scale: float = 0.05
    volume_window: int = 48
    # What the volume-expansion multiplier reads before it has `volume_window` bars.  1.0 is what the
    # code has always done and stays the default so nothing moves; `None` means "do not fill", which
    # leaves the score NaN until expansion is warm and is the value `warmup_bars` already declares.
    # The two are not equivalent and 1.0 is not the neutral one - see `flow_scores`.  Adopting `None`
    # is an operator decision with its own evidence, so it is a config edit and not a code change.
    #
    # Declaring it DOES move two digests, because both are taken over canonicalised signal params:
    # `registry_fingerprint` 7a969e02 -> 0e1da8bb and `registry_digest` abe21f7a8edf -> e204447bef68.
    # Nothing the loop computes changes, but until the running process is restarted
    # `starquant live status --check` will correctly report that the file is not what the loop holds.
    volume_warmup_fill: float | None = 1.0
    cross_sectional: bool = True
    entry_threshold: float = 0.20
    short_gate: float = 0.0  # 0 disables; shorts are dropped while momentum >= short_gate
    long_side: bool = True  # False = short-only book (the long leg's static-universe evidence was survivorship)
    gate_horizons: tuple[int, ...] = (168, 336, 720)
    gate_weights: tuple[float, ...] = (0.2, 0.3, 0.5)
    gate_return_scale: float = 0.20
    gate_vol_window: int | None = 400

    def __post_init__(self) -> None:
        if self.window <= 0 or self.scale <= 0 or self.volume_window < 2:
            raise ValueError("invalid flow parameters")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")
        if not 0 <= self.short_gate <= 1:
            raise ValueError("short_gate must be in [0, 1]")
        if self.volume_warmup_fill is not None and not 0 < self.volume_warmup_fill <= 1:
            raise ValueError("volume_warmup_fill must be in (0, 1] - expansion's own range - or None")
        if self.short_gate > 0:
            self.gate_params()  # validates the momentum parameters eagerly

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> FlowParams:
        values = dict(params)
        for key in ("gate_horizons", "gate_weights"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)

    def gate_params(self) -> TsmomParams:
        return TsmomParams(
            horizons=self.gate_horizons,
            horizon_weights=self.gate_weights,
            return_scale=self.gate_return_scale,
            vol_window=self.gate_vol_window,
        )

    @property
    def warmup_bars(self) -> int:
        base = max(self.window, self.volume_window) + 1
        if self.short_gate <= 0:
            return base
        return max(base, self.gate_params().warmup_bars)


def flow_scores(panel: Panel, params: FlowParams | None = None) -> pd.DataFrame:
    """Scores; ``volume_warmup_fill`` decides what the expansion multiplier is before it is warm.

    ``expansion`` lives in (0, 1] and multiplies the imbalance, so ``fillna(1.0)`` is its UPPER bound,
    not a neutral value: on a bar where the ratio is unknown the score is computed as though volume had
    expanded as much as it ever can.  That is a lean toward taking the position, in a signal whose
    shipped use is the short-only ``flow_short`` probe.

    WHERE it is reachable was measured before this knob was written, because the answer is not the one
    the shape suggests.  The review's reading was the warm-up head: ``imbalance`` needs ``window`` bars
    and the score is masked where it is NaN, so the fill shows only on ``volume_window < t <= window``,
    which is bars 25-48 under this class's defaults and EMPTY under the shipped registry (``window``
    168 against ``volume_window`` 48).  On the point-in-time panel (205 symbols, 49,937 bars,
    2021-01-01..2026-09-12) the count of bars the fill actually reaches under the registry's own
    parameters is 4,284 - and every single one of them comes from the OTHER NaN in ``volume_ratio``:
    ``baseline.where(baseline > 0)``, a symbol whose trailing 48-bar mean volume is exactly zero.
    36 symbols, 238 of the 4,284 inside the eligible/point-in-time mask.

    Which makes the fill's meaning worse than "aggressive during warm-up": a symbol that has stopped
    quoting for two days is scored as though its volume were expanding as hard as it can.  It is the
    same population O4's ``dead_slot_share`` counts - a 30-day trailing volume keeps ranking a name
    that no longer prints - reached through a different door.

    The default still does not move.  `flow_short` is ENABLED, ``None`` changes 238 in-universe cells
    from a value to a hold/NaN, and `scores_to_targets` carries values forward, so this is a live
    change and therefore the operator's to price - not a correction to slip in beside four that are
    bit-identical.
    """
    p = params or FlowParams()
    if panel.taker_buy_quote is None or panel.quote_volume is None:
        return pd.DataFrame(np.nan, index=panel.close.index, columns=panel.close.columns)
    imbalance = taker_buy_ratio(panel.taker_buy_quote, panel.quote_volume, p.window) - 0.5
    if p.cross_sectional:
        # P1-01: the mean is taken over the reference population, not over whichever columns
        # the caller loaded.  This half of the defect is the one that is live today - the flow
        # probe demeans against ~123 research names and against the 15-18 the loop manages.
        centre = within_reference(imbalance, panel.reference).mean(axis=1)
        imbalance = imbalance.sub(centre, axis=0)
    expansion = volume_ratio(panel.volume, p.volume_window).clip(upper=1.0)
    if p.volume_warmup_fill is not None:
        expansion = expansion.fillna(p.volume_warmup_fill)
    score = apply_numpy(imbalance / p.scale, np.tanh) * expansion
    score = apply_short_gate(score.clip(-1.0, 1.0).where(imbalance.notna()), panel.close, p)
    if not p.long_side:
        score = score.mask(score > 0, 0.0)  # a buy signal closes a short but never opens a long
    return score


def apply_short_gate(score: pd.DataFrame, close: pd.DataFrame, p: FlowParams) -> pd.DataFrame:
    """Replace short scores by an explicit exit while weekly momentum is strongly positive."""
    if p.short_gate <= 0:
        return score
    momentum = tsmom_scores(close, p.gate_params()).reindex(index=score.index, columns=score.columns)
    blocked = (score < 0) & (momentum >= p.short_gate)
    return score.mask(blocked, 0.0)


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return flow_scores(panel, FlowParams.from_mapping(params))
