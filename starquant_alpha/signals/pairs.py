"""Vol-matched pairs: mutual nearest neighbours, refit on a prefix, traded on the spread's z-score.

Pre-registered in docs/RESEARCH_LOG.md (P28, 2026-09-09) before this file existed.

**Vol-matched, not OLS-beta, and the construction is why.**  Stage 1 of the portfolio is
``w1 = target * vol_target / asset_vol`` - each leg sized to the target vol STANDALONE - so a signal
emitting ``+1`` and ``-beta`` would have its beta divided away by the two legs' own volatilities.
Defining the spread on vol-normalised returns instead makes that division the correct normalisation:
``+s`` and ``-s`` become two legs of equal risk contribution, which IS a vol-matched pair.  The hedge
ratio therefore comes free from the construction rather than being fought with it.

**Mutual nearest neighbours.**  A one-sided "closest partner" makes one popular symbol everybody's
partner, and then the book is not a set of pairs but a single leveraged bet against that symbol.

**The refit sees a prefix and nothing else.**  Selecting pairs on the full sample is the classic way
pairs trading reads the future, and it is not a subtle effect: choosing, in 2026, the pair that
co-moved best over 2021-2026 and then "trading" it in 2021 is close to a look-ahead by construction.
Partner, correlation and spread scale are all frozen at the refit bar and held until the next one.

**Choosing the partner is a search, and ``search_census`` is what it costs.**  The refit loop looks at
every pair its formation window can form and keeps a handful; that selection is a DSR denominator and
was free until 2026-09-09.  See ``search_census`` for the measurement.

Three vocabulary items, as everywhere else: ``+-`` an actionable score, an explicit ``0.0`` when the
spread has closed (``scores_to_targets`` reads it as CLOSE), and a sub-threshold hold otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel
from starquant_alpha.signals.base import SearchCensus

HOLD = 0.05


@dataclass(frozen=True)
class PairsParams:
    formation_bars: int = 720
    refit_bars: int = 720
    z_window: int = 168
    entry_z: float = 2.0
    exit_z: float = 0.5
    z_scale: float = 3.0
    min_corr: float = 0.5
    entry_threshold: float = 0.2

    def __post_init__(self) -> None:
        if self.formation_bars < 60 or self.refit_bars < 24 or self.z_window < 24:
            raise ValueError("pairs windows are too short to estimate anything")
        if not 0.0 < self.exit_z < self.entry_z:
            raise ValueError("exit_z must be positive and below entry_z")
        if self.z_scale <= 0 or not -1.0 <= self.min_corr <= 1.0:
            raise ValueError("invalid pairs parameters")
        if not 0 < self.entry_threshold <= 1:
            raise ValueError("entry_threshold must be in (0, 1]")

    @classmethod
    def from_mapping(cls, params: Mapping[str, Any]) -> PairsParams:
        return cls(**dict(params))

    @property
    def warmup_bars(self) -> int:
        return self.formation_bars + self.z_window + 1


def _examined(window: pd.DataFrame) -> np.ndarray:
    """The columns this formation window can pair at all - the search space of one refit.

    Enough observations AND some variance: `np.corrcoef` divides by the standard deviation, so a
    column that never moved in the formation window produces a NaN row and a divide warning, and a
    NaN row's argmax is meaningless rather than merely noisy.  A symbol that did not move is also not
    a pair candidate under any reading, so it is dropped here rather than masked afterwards.
    """
    observed = window.notna().sum() >= max(2, len(window) // 2)
    varying = window.std() > 0
    return np.flatnonzero((observed & varying).to_numpy())


def _mutual_pairs(window: pd.DataFrame, min_corr: float) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """The columns examined, and the mutually-nearest pairs among them above ``min_corr``.

    Mutual rather than one-sided: with a one-sided rule the market's most correlated name becomes
    everybody's partner and the book stops being pairs at all.

    Both halves are returned because the census and the scores have to agree about what was looked at.
    A census that re-derived the examined set from its own copy of the eligibility rule would drift the
    moment that rule moved, and it would drift silently in the direction that under-charges N.
    """
    columns = _examined(window)
    if len(columns) < 2:
        return columns, []
    matrix = np.corrcoef(np.nan_to_num(window.to_numpy(dtype=float)[:, columns], nan=0.0), rowvar=False)
    np.fill_diagonal(matrix, -np.inf)
    best = matrix.argmax(axis=1)
    out: list[tuple[int, int]] = []
    for i, j in enumerate(best):
        if i < j and best[j] == i and matrix[i, j] >= min_corr:
            out.append((int(columns[i]), int(columns[j])))
    return columns, out


def _normalised(close: pd.DataFrame, p: PairsParams) -> pd.DataFrame:
    """Vol-normalised returns: the unit the spread is defined in, and the unit stage 1 will size in."""
    positive = close.where(close > 0)
    returns = pd.DataFrame(
        np.log(positive.to_numpy(dtype=float)), index=positive.index, columns=positive.columns
    ).diff()
    vol = returns.rolling(p.z_window, min_periods=p.z_window // 2).std()
    return returns.div(vol.where(vol > 0))


def _refits(n_bars: int, p: PairsParams) -> range:
    """The bars the partner is re-chosen at; empty when the panel is too short to choose one.

    One definition rather than two, because ``search_census`` has to walk exactly the loop that trades:
    a census over more refits than the signal ran would charge hypotheses nobody looked at, and one over
    fewer would be the free search this module's accounting exists to close.
    """
    return range(p.formation_bars, n_bars, p.refit_bars) if n_bars > p.warmup_bars else range(0)


def pairs_scores(panel: Panel, params: PairsParams | None = None) -> pd.DataFrame:
    p = params or PairsParams()
    close = panel.close
    scores = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=float)
    normalised = _normalised(close, p)
    values = normalised.to_numpy(dtype=float)

    n = len(close)
    for refit in _refits(n, p):
        # Everything below is computed from bars strictly BEFORE `refit`, then held until the next one.
        window = normalised.iloc[refit - p.formation_bars : refit]
        _columns, pairs = _mutual_pairs(window, p.min_corr)
        if not pairs:
            continue
        stop = min(n, refit + p.refit_bars)
        for left, right in pairs:
            formation = values[refit - p.formation_bars : refit, [left, right]]
            spread_formation = np.nancumsum(formation[:, 0] - formation[:, 1])
            scale = float(np.nanstd(spread_formation[-p.z_window :]))
            if not np.isfinite(scale) or scale <= 0:
                continue
            anchor = float(spread_formation[-1])
            live = values[refit:stop, [left, right]]
            spread = anchor + np.nancumsum(np.nan_to_num(live[:, 0] - live[:, 1], nan=0.0))
            centre = float(np.nanmean(spread_formation[-p.z_window :]))
            z = (spread - centre) / scale
            leg = np.where(
                np.abs(z) >= p.entry_z,
                -np.clip(z / p.z_scale, -1.0, 1.0),
                np.where(np.abs(z) < p.exit_z, 0.0, HOLD * -np.sign(z)),
            )
            scores.iloc[refit:stop, left] = leg
            scores.iloc[refit:stop, right] = -leg
    return scores


def search_census(panel: Panel, params: Mapping[str, Any]) -> SearchCensus:
    """Every symbol pair the refit loop looked at, and the ones it kept (DL-K2 for a pair search).

    **Measured before it was designed**, on the panel the 2026-09-08 validation ran on (205 symbols,
    49,817 bars, 69 refits at the pre-registered ``formation_bars=refit_bars=720``): 52 to 175 symbols
    pass ``_examined`` in a given formation window - median 112 - so one window enumerates 1,326 to
    15,225 pairs and the run enumerates 515,328 pair-windows.  Deduplicated that is **19,578 distinct
    pairs**, 94% of the 20,910 the panel could form, of which **183 were ever traded** (151 at
    ``z_window=168``, 150 at 336).  The report that shipped recorded ``n_trials: 4``.

    Distinct pairs, not pair-windows: looking at the same pair at 69 consecutive refits is one
    hypothesis looked at 69 times, which is the rule DL-K2 already settled for ``mine``.

    The search is **not** restricted to the point-in-time universe.  ``pairs_scores`` reads
    ``panel.close``, and ``AlphaModel.strategy_targets`` applies the eligible mask to the SCORES
    afterwards, so the partner is chosen from every symbol the panel carries - which is why N is 19,578
    and not the ~150 pairs an 18-name universe could form.  Measured, not assumed; whether that is the
    right population is a signal question and not this function's to answer.

    What this census is honest about being: the selection ranks candidates on **formation-window
    correlation**, not on their own P&L, and it is made on a prefix.  That is a weaker selection than
    ``mine``'s full-sample Sharpe ranking, so charging one row per candidate is conservative.  The
    repository charges in the conservative direction on purpose (KILL-Q5), and the alternative - a
    discount nobody has estimated - would be a number chosen because it flatters.
    """
    p = PairsParams.from_mapping(params)
    close = panel.close
    names = [str(column) for column in close.columns]
    normalised = _normalised(close, p)
    examined: set[tuple[int, int]] = set()
    selected: set[tuple[int, int]] = set()
    sizes: list[int] = []
    for refit in _refits(len(close), p):
        window = normalised.iloc[refit - p.formation_bars : refit]
        columns, pairs = _mutual_pairs(window, p.min_corr)
        sizes.append(len(columns))
        examined.update(combinations((int(column) for column in columns), 2))  # `columns` is ascending
        selected.update((left, right) if left < right else (right, left) for left, right in pairs)
    per_refit = [size * (size - 1) // 2 for size in sizes]
    return SearchCensus(
        candidates=tuple(sorted(_pair_id(names, i, j) for i, j in examined)),
        selected=tuple(sorted(_pair_id(names, i, j) for i, j in selected)),
        facts={
            "refits": len(sizes),
            "symbols_per_refit": _spread(sizes),
            "pairs_per_refit": {**_spread(per_refit), "sum": sum(per_refit)},
            "distinct_pairs": len(examined),
            "traded_pairs": len(selected),
            "possible_pairs": len(names) * (len(names) - 1) // 2,
        },
    )


def _pair_id(names: list[str], left: int, right: int) -> str:
    """The ledger key for one pair hypothesis: the two symbols, alphabetically.

    Alphabetical rather than by column position, and the difference is not cosmetic: column order is a
    property of the RUN - which symbols were loaded, in which order - so an index-ordered id files the
    same pair under `BTCUSDT|BNBUSDT` in one run and `BNBUSDT|BTCUSDT` in the next, and the ledger,
    which folds on the key, would charge one hypothesis twice.  Caught by the CLI test rather than by
    reading, because both orders look equally right in the source.

    Mapped once per distinct pair rather than inside the loop: the enumeration visits half a million
    pair-windows on the production panel and 19,578 distinct pairs come out of it.
    """
    return "|".join(sorted((names[left], names[right])))


def _spread(values: list[int]) -> dict[str, float]:
    """min/median/max, and zeros when the search never ran - a panel too short to choose a partner."""
    if not values:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    return {"min": float(min(values)), "median": float(np.median(values)), "max": float(max(values))}


def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
    return pairs_scores(panel, PairsParams.from_mapping(params))
