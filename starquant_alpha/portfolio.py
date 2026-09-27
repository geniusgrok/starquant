"""Portfolio construction: conviction -> vol-targeted, capped weights (fraction of equity).

Stage 1  w1 = target * vol_target / asset_vol         (each position sized to the target vol standalone)
Stage 2  w2 = w1 * vol_target / portfolio_vol(w1)      (EWMA covariance, causal)      scalar clipped
Stage 3  |w| <= max_weight,  sum |w| <= max_gross
Optionally a no-trade band suppresses tiny rebalances (path dependent, applied last).

``combine_books`` (D-018/D-019) sums independently built books - each already vol-targeted
and scaled by its fraction - and applies the per-symbol cap, the gross cap and the band to
the total.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import ewm_vol, garch_forecast_vol, refit_boundaries

VOL_MODELS = ("ewma", "garch")
BUDGET_MODES = ("inverse_vol", "inverse_variance", "hrp")


@dataclass(frozen=True)
class PortfolioParams:
    vol_target: float = 0.15
    vol_halflife: int = 48
    covariance_halflife: int = 96
    min_asset_vol: float = 0.10
    max_weight: float = 0.15
    max_gross: float = 2.0
    max_scalar: float = 3.0
    no_trade_band: float = 0.0
    no_trade_rel_band: float = 0.0
    # Two construction OPTIONS, both off by default and both a Phase 4a change to turn on: switching
    # either one moves every weight, so it is a construction change and resets M-010's 30-day window.
    # They live here rather than behind a flag elsewhere so that `from_mapping` reaches them and the
    # eventual adoption is a config edit plus evidence, not a code change under time pressure.
    vol_model: str = "ewma"  # ewma | garch: what stage 1 divides by (#35)
    garch_fit_bars: int = 8760  # trailing bars each GARCH re-fit sees
    garch_refit_bars: int = 720  # bars between re-fits
    budget_mode: str = "inverse_vol"  # inverse_vol (shipped) | inverse_variance (control) | hrp (#48)
    hrp_refit_bars: int = 720  # bars between HRP re-clusterings
    # P30 (2026-09-12), pre-registered before this line existed.  A per-bar gross cap on each NON-main
    # book, applied BEFORE its fraction, so that `fraction` keeps D-019's meaning - a proportion of the
    # main book's risk budget - rather than a proportion of however big that sleeve happens to run.
    # P21 rejected `594a12f9` on drawdown alone and diagnosed the cause as exposure: the sleeve averages
    # 1.372 gross against tsmom's 0.859, so a third of it is closer to half a main book.  0 is off, and
    # off is bit-identical - the knob ships into a loop that is holding positions.
    sleeve_max_gross: float = 0.0
    # D2 (2026-09-14).  Must be flipped together with `starquant_live.rebalancer.RebalanceParams`, on the
    # `exempt_reductions` rule: the two halves replay the same band and only agree because they are
    # written to the same sentence.  "Never hold a position smaller than the absolute band" - live,
    # such a position can never be closed again, because the largest gap a zero target can ask for is
    # |current|, which is inside the band by construction.  Off is bit-identical: `apply_no_trade_band`
    # is only reached at all when `no_trade_band > 0`, and False leaves its recursion untouched.
    flat_inside_band: bool = False
    # D3 (2026-09-17, operator ruling: adopt now rather than at the freeze's end).  How much room a
    # target must clear the absolute band by before `flat_inside_band` lets it stand.  1.0 - the value
    # that shipped with D2 - is D2 exactly, so off is bit-identical by arithmetic rather than by branch.
    #
    # **D2 tests the TARGET; a position walks into the band on PRICE, and D2 never looks again.**  That
    # is the hole LSKUSDT fell through, and it is a third path neither D2 nor `exempt_crossings` covers:
    #     09-16T21:00Z  BUY 74 @0.7287, target 54.08 against a 53.66 band - it cleared by 0.42 USDT
    #     09-16T22:00Z  price -8%, |current| 49.53 < band 53.74  ->  BAND_BLOCKS_EXIT, and permanently
    # One hour from a target D2 approved to a position nothing can close.  The 09-14 section of
    # `docs/RESEARCH_LOG.md` recorded two ways to make a stub - a reduction landing inside the band and
    # a flip landing inside it - and both are about where the TARGET lands.  This one is about where the
    # POSITION drifts, so D2 approves it on the way in and has no opinion afterwards.
    #
    # Why a multiple on the entry test and not a check on `|current|`.  A rule that closes whatever
    # currently sits inside the band oscillates: LSKUSDT's target is 0.53% of equity against a 0.50%
    # band, so the position would be closed, re-opened at the unchanged target, and closed again on the
    # next 6% move - and its hourly sigma is 9.2%.  Testing the target instead is stable, because the
    # target is what the model holds still: 58.66 USDT is below 2 x 55.33 every cycle, so the name
    # stays flat rather than flickering.  It also closes the existing stub, because a target taken as
    # flat is a target of exactly zero, which is the one case `exempt_crossings` waves through the band.
    #
    # What 2.0 buys, in the units that produced the failure: a position must lose HALF its notional
    # before it can reach the band, where 1.0 allowed 0.8%.  Both LSKUSDT entries cleared the band by
    # under 1% (52.40/52.12 and 54.08/53.66), and no other name in the 2026-09-17 book is within 3.5x
    # of it - the next smallest is LINKUSDT at 202 USDT against 55.33.  So on today's book this is the
    # difference between holding LSKUSDT and TRUMPUSDT or holding neither, and nothing else moves.
    band_entry_multiple: float = 1.0

    def __post_init__(self) -> None:
        if self.vol_target <= 0 or self.min_asset_vol <= 0 or self.max_weight <= 0 or self.max_gross <= 0:
            raise ValueError("portfolio parameters must be positive")
        if self.no_trade_band < 0 or self.no_trade_rel_band < 0 or self.max_scalar <= 0:
            raise ValueError("no-trade bands must be >= 0 and max_scalar > 0")
        if self.sleeve_max_gross < 0:
            raise ValueError("sleeve_max_gross must be >= 0 (0 disables it)")
        # Below 1.0 the multiple would shrink the flat-inside test to a SUBSET of the band, which is a
        # position the planner still cannot close - the opposite of what the field is for.
        if self.band_entry_multiple < 1.0:
            raise ValueError("band_entry_multiple must be >= 1.0 (1.0 is D2 exactly)")
        if self.vol_model not in VOL_MODELS or self.budget_mode not in BUDGET_MODES:
            raise ValueError(f"vol_model must be one of {VOL_MODELS} and budget_mode one of {BUDGET_MODES}")
        if min(self.garch_fit_bars, self.garch_refit_bars, self.hrp_refit_bars) < 1:
            raise ValueError("re-fit cadences must be at least one bar")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PortfolioParams:
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        return cls(**known)


def ewma_portfolio_vol(returns: pd.DataFrame, weights: pd.DataFrame, halflife: int, bars_per_year: float) -> pd.Series:
    """Annualised sqrt(w_t' Sigma_t w_t) with an EWMA covariance recursion; Sigma_t uses returns through t.

    ``fillna(0.0)`` reads a missing return as a FLAT bar, and that is an assumption rather than a
    neutral default.  Before a symbol lists it is harmless and exact: `asset_vol` is NaN there, stage 1
    zeroes the weight, and a zero row contributes nothing to a quadratic form it is also weighted out
    of.  Inside a symbol's own history it is not harmless - a hole in the archive enters the recursion
    as evidence of calm, so the covariance is biased DOWN, the stage-2 scalar `vol_target / this` is
    biased UP, and the book runs slightly hot for about a halflife afterwards.

    Recorded rather than fixed, for a reason that is about the estimator and not about effort.  There
    is no one-line repair: the recursion updates a full matrix from `outer(row, row)`, so a single
    absent symbol cannot be skipped without either dropping the whole bar for every symbol (throwing
    away the names that did print) or moving to pairwise-available covariances (which need not stay
    positive semi-definite, and this feeds a variance).  Any of those is a different estimator, it
    moves every archived number, and it would have to be re-validated against the evidence the
    registry cites - a construction change, which is D-026's shape and belongs behind a flag with its
    own measurement.

    The size of what is being carried, so the decision can be argued with: `starquant_data.pool` measures
    5 point-in-time members with internal gaps, 1,005 symbol-bars, against a panel of roughly 123
    symbols across 43,800 bars - about 0.02% of cells - and none of the five has ever been in the
    pinned live universe.  A hole wide enough to matter would have to open in a name the book is
    actually holding, which is also the case in which `starquant_live.staleness`'s rules fire first.
    """
    r = returns.fillna(0.0).to_numpy(dtype=float)
    w = weights.fillna(0.0).to_numpy(dtype=float)
    n_bars, n_assets = r.shape
    lam = math.exp(-math.log(2.0) / max(halflife, 1))
    cov = np.zeros((n_assets, n_assets))
    out = np.full(n_bars, np.nan)
    for t in range(n_bars):
        row = r[t]
        cov = lam * cov + (1.0 - lam) * np.outer(row, row)
        if t + 1 >= max(halflife, 2):
            variance = float(w[t] @ cov @ w[t])
            out[t] = math.sqrt(max(variance, 0.0) * bars_per_year)
    return pd.Series(out, index=weights.index)


def asset_vol(close: pd.DataFrame, params: PortfolioParams, bars_per_year: float) -> pd.DataFrame:
    """Annualised per-symbol volatility, floored at ``min_asset_vol``: stage 1's divisor.

    Named rather than inlined so the live report can display the number the construction
    actually divided by.  A report that re-derives it is a report that can disagree with
    the book while both look right, and the question this exists to answer - "is sizing
    adapting to each symbol's market?" - is exactly the one a disagreement would corrupt.

    ``vol_model="garch"`` swaps the EWMA level for a one-step-ahead GARCH(1,1) forecast (#35).  It
    is off by default and the two are not the same quantity - see ``garch_forecast_vol``.
    """
    raw = (
        garch_forecast_vol(close, fit_bars=params.garch_fit_bars, refit_bars=params.garch_refit_bars)
        if params.vol_model == "garch"
        else ewm_vol(close, halflife=params.vol_halflife)
    )
    return (raw * math.sqrt(bars_per_year)).clip(lower=params.min_asset_vol)


def _quasi_diagonal_order(distance: np.ndarray) -> list[int]:
    """Leaf order of a single-linkage tree - Lopez de Prado's ``getQuasiDiag``, without scipy.

    ``starquant_alpha`` is pinned to numpy and pandas by ``test_import_rules``, so the linkage is
    hand-rolled.  It is the naive O(n^3) agglomeration, which is fine here because it runs once per
    re-cluster (720 bars apart by default) on at most a few hundred symbols, not once per bar.
    """
    members = {i: [i] for i in range(distance.shape[0])}
    d = distance.astype(float).copy()
    np.fill_diagonal(d, np.inf)
    active = list(range(distance.shape[0]))
    while len(active) > 1:
        block = d[np.ix_(active, active)]
        i, j = np.unravel_index(int(np.argmin(block)), block.shape)
        keep, drop = active[i], active[j]
        members[keep] = members[keep] + members[drop]
        d[keep] = np.minimum(d[keep], d[drop])  # single linkage: nearest members define cluster distance
        d[:, keep] = d[keep]
        d[keep, keep] = np.inf
        active.remove(drop)
    return members[active[0]]


def _cluster_variance(cov: np.ndarray, items: list[int]) -> float:
    block = cov[np.ix_(items, items)]
    inverse = 1.0 / np.maximum(np.diag(block), 1e-18)
    weights = inverse / inverse.sum()
    return float(weights @ block @ weights)


def hrp_budget(cov: np.ndarray) -> np.ndarray:
    """Hierarchical risk parity budget (non-negative, sums to 1) from one covariance matrix (#48).

    Correlation -> distance sqrt((1-rho)/2) -> distance between those distance vectors -> single-linkage
    order -> recursive bisection allocating between two halves by their inverse cluster variance.
    """
    std = np.sqrt(np.maximum(np.diag(cov), 0.0))
    denominator = np.outer(std, std)
    corr = np.clip(np.divide(cov, denominator, out=np.zeros_like(cov), where=denominator > 0), -1.0, 1.0)
    d = np.sqrt(np.maximum(0.5 * (1.0 - corr), 0.0))
    gram = d @ d.T
    norms = np.diag(gram).copy()
    order = _quasi_diagonal_order(np.sqrt(np.maximum(norms[:, None] + norms[None, :] - 2.0 * gram, 0.0)))
    weights = np.ones(len(order))
    groups = [list(range(len(order)))]
    while groups:
        following: list[list[int]] = []
        for group in groups:
            if len(group) < 2:
                continue
            left, right = group[: len(group) // 2], group[len(group) // 2 :]
            variance_left = _cluster_variance(cov, [order[k] for k in left])
            variance_right = _cluster_variance(cov, [order[k] for k in right])
            total = variance_left + variance_right
            share = 1.0 - variance_left / total if total > 0 else 0.5
            weights[left] *= share
            weights[right] *= 1.0 - share
            following.extend([left, right])
        groups = following
    out = np.empty(len(order))
    out[order] = weights
    return out


def _hrp_tilt(sigma: pd.DataFrame, returns: pd.DataFrame, params: PortfolioParams) -> pd.DataFrame:
    """HRP's budget divided by the inverse-variance budget it would have used with no clustering.

    Expressed as a tilt, not as a budget, because HRP changes TWO things against the shipped path and
    a single number that moves both cannot say which one paid: it allocates on inverse VARIANCE where
    stage 1 allocates on inverse VOL, and it then tilts that by the correlation clustering.  As a tilt
    the clustering is separable, and ``budget_mode="inverse_variance"`` is the control arm with the
    tilt held at exactly 1.

    The CORRELATION is the same causal EWMA recursion ``ewma_portfolio_vol`` runs, so the clustering and
    the stage-2 scalar cannot disagree about what co-moves with what.  The DIAGONAL is not: the block is
    rebuilt as ``corr * outer(sigma, sigma)`` from the floored ``asset_vol``, for two reasons that turned
    out to be the same reason.  Consistency - the tilt divides by the inverse-variance budget it is a
    tilt on, and dividing by a different variance estimate than the one it multiplies is not a tilt at
    all.  And arithmetic: measured on the point-in-time panel, the raw EWMA diagonal contains symbols
    whose variance rounds to zero (a window with no price change at all), which handed one name ~100% of
    the inverse-variance budget and produced tilts of 1e86 for everything else.  ``min_asset_vol`` is
    already the construction's answer to "this number is too small to divide by"; HRP now uses it too.

    Re-clustered every ``hrp_refit_bars``; between re-clusters the tilt is held while the
    inverse-variance part it multiplies keeps updating every bar, so a symbol that lists mid-block is
    sized (tilt 1) rather than dropped.

    WHICH bars those re-clusters land on is a calendar fact, not an offset from row 0 (`refit_boundaries`).
    ``t % hrp_refit_bars == 0`` made the whole tilt path a function of where the panel started: the same
    calendar hour re-clustered in one window and held a stale tilt in another, and measured on the
    point-in-time panel one symbol's weight moved 9.69e-4 between a 1,442-bar and a 1,443-bar request
    window for no reason but that.  Off by default (``budget_mode`` is ``inverse_vol``, #48 REFUTED), so
    this moves nothing shipped; it matters the day it is re-opened, because the live loop re-requests a
    window that slides one bar per cycle and would re-cluster on a different hour every hour (D-033).

    What is NOT fixed, and cannot be without changing the estimator: the EWMA covariance itself starts
    from zero on the frame's first row, so two frames agree only up to the weight that start still
    carries - ``2^(-k/halflife)`` after k bars.  That is a warm-up, it decays, and it is bounded; the
    boundary placement was neither.
    """
    r = returns.fillna(0.0).to_numpy(dtype=float)
    scale = sigma.to_numpy(dtype=float)
    n_bars, n_symbols = r.shape
    lam = math.exp(-math.log(2.0) / max(params.covariance_halflife, 1))
    cov = np.zeros((n_symbols, n_symbols))
    tilt = np.ones((n_bars, n_symbols))
    current = np.ones(n_symbols)
    recluster = set(refit_boundaries(pd.DatetimeIndex(returns.index), params.hrp_refit_bars))
    for t in range(n_bars):
        row = r[t]
        cov = lam * cov + (1.0 - lam) * np.outer(row, row)
        if t >= max(params.covariance_halflife, 2) and t in recluster:
            active = np.flatnonzero(np.isfinite(scale[t]) & (scale[t] > 0) & (np.diag(cov) > 0))
            if len(active) >= 2:
                block = cov[np.ix_(active, active)]
                std = np.sqrt(np.diag(block))
                width = scale[t][active]
                inverse = 1.0 / width**2
                current = np.ones(n_symbols)
                current[active] = hrp_budget(block / np.outer(std, std) * np.outer(width, width)) / (
                    inverse / inverse.sum()
                )
        tilt[t] = current
    return pd.DataFrame(tilt, index=returns.index, columns=returns.columns)


def risk_budget(sigma: pd.DataFrame, returns: pd.DataFrame, params: PortfolioParams) -> pd.DataFrame:
    """Cross-sectional risk budget, rows summing to 1 over the symbols that have a volatility yet.

    Stage 1's ``vol_target / sigma_i`` IS ``vol_target * b_i * sum_j(1 / sigma_j)`` with ``b`` the
    normalised inverse-vol budget, so every mode below keeps stage 1's TOTAL budget and changes only
    how it is split.  That is what makes the comparison a comparison: leave the total free and the two
    arms differ in how often ``max_weight`` and ``max_gross`` bind, which is not what #48 is about.
    """
    inverse = 1.0 / sigma if params.budget_mode == "inverse_vol" else 1.0 / sigma.pow(2)
    if params.budget_mode == "hrp":
        inverse = inverse * _hrp_tilt(sigma, returns, params)
    total = inverse.sum(axis=1)
    return inverse.div(total.where(total > 0), axis=0)


def vol_targeted(
    targets: pd.DataFrame, close: pd.DataFrame, bars_per_year: float, params: PortfolioParams
) -> pd.DataFrame:
    """Stages 1 and 2 - the weights the vol target asks for, BEFORE either cap.

    Extracted from ``build_weights`` (which now calls it) for the reason ``asset_vol`` was extracted
    one layer down: the question "how much of the requested risk did `max_weight` remove" can only be
    answered against the number the construction actually divided by, and a diagnostic that rebuilds
    its own copy of these two stages is a diagnostic that can disagree with the book while both look
    right.  One implementation, two readers.
    """
    aligned = targets.reindex(index=close.index, columns=close.columns)
    sigma = asset_vol(close, params, bars_per_year)
    returns = close.pct_change()
    if params.budget_mode == "inverse_vol":
        # Algebraically this is the general branch below with b = inverse-vol, and it is kept literal
        # anyway: the two agree to about 1e-16 relative, not bit for bit, and the shipped construction
        # is compared bit for bit against a frozen baseline.  A default that is "the same modulo
        # rounding" is a default that has been changed.
        stage1 = (aligned.fillna(0.0) * (params.vol_target / sigma)).fillna(0.0)
    else:
        budget = risk_budget(sigma, returns, params).mul((1.0 / sigma).sum(axis=1), axis=0)
        stage1 = (aligned.fillna(0.0) * budget * params.vol_target).fillna(0.0)
    portfolio_vol = ewma_portfolio_vol(returns, stage1, params.covariance_halflife, bars_per_year)
    scalar = (params.vol_target / portfolio_vol.where(portfolio_vol > 1e-12)).clip(upper=params.max_scalar).fillna(0.0)
    return stage1.mul(scalar, axis=0)


def clipped_risk_share(sized: pd.DataFrame, params: PortfolioParams) -> pd.Series:
    """Per bar, the share of the requested |weight| that ``max_weight`` removed and did NOT give back.

    GAP-AM02.  At ``vol_target`` 0.60 the per-symbol cap binds on about half the cycles that record
    per-book weights - only BTCUSDT and BNBUSDT, because inverse-vol sizing necessarily hands the
    largest weight to the calmest name - and `config/live.demo.yaml` records the count.  What no
    reading answered is how much RISK that removes, and the difference matters twice over: the book
    then runs under its vol target, and the identity P13 rests on ("scaling every weight by k leaves
    net Sharpe exactly unchanged, so the dial carries no alpha") holds only while the cap does not
    bind.  A count cannot say either; this can.

    Only the per-symbol cap.  The gross cap is a row-wise rescale that keeps the book's SHAPE, it is
    already visible as `GROSS_CAPPED`, and folding the two together would report one number for two
    different events.
    """
    requested = sized.abs().sum(axis=1)
    kept = sized.clip(-params.max_weight, params.max_weight).abs().sum(axis=1)
    return (1.0 - kept / requested.where(requested > 0)).fillna(0.0)


def build_weights(
    targets: pd.DataFrame, close: pd.DataFrame, bars_per_year: float, params: PortfolioParams
) -> pd.DataFrame:
    aligned = targets.reindex(index=close.index, columns=close.columns)
    stage2 = vol_targeted(targets, close, bars_per_year, params).clip(-params.max_weight, params.max_weight)
    gross = stage2.abs().sum(axis=1)
    factor = (params.max_gross / gross.where(gross > params.max_gross)).fillna(1.0).clip(upper=1.0)
    weights = stage2.mul(factor, axis=0)
    weights = weights.where(aligned.notna().any(axis=1).cummax(), other=np.nan)
    return banded(weights, params)


def apply_no_trade_band(
    weights: pd.DataFrame,
    band: float,
    relative: float = 0.0,
    flat_inside: bool = False,
    entry_multiple: float = 1.0,
) -> pd.DataFrame:
    """Keep the previous weight when |Δw| < max(band, relative * |w_prev|).

    Path dependent.  Exits to exactly zero, entries from zero and sign flips
    are always executed; only same-direction resizing is suppressed.

    ``flat_inside`` is D2's backtest half and must be flipped together with
    ``starquant_live.rebalancer.RebalanceParams.flat_inside_band``: a weight
    strictly inside the absolute band is taken as flat, because live that is
    a position the planner can never close again - the largest gap a zero
    target can ask for is ``|current|``, which is inside the band by
    construction.  Applied to the raw row, before the band's own recursion,
    so the suppressed-resize rule still sees the target the model asked for.

    ``entry_multiple`` is D3's backtest half, on the same joint-flip rule.  It
    widens that same test to ``band * entry_multiple``, so a weight has to
    clear the band by a margin before it is allowed to stand;
    ``PortfolioParams.band_entry_multiple`` carries the derivation and the
    LSKUSDT reading it was written from.  1.0 is D2 exactly.
    """
    values = weights.to_numpy(dtype=float)
    out = np.empty_like(values)
    previous = np.zeros(values.shape[1])
    for t in range(values.shape[0]):
        row = values[t]
        if np.all(np.isnan(row)):
            out[t] = np.nan
            continue
        current = np.where(np.isnan(row), 0.0, row)
        if flat_inside:
            current = np.where(np.abs(current) < band * entry_multiple, 0.0, current)
        threshold = np.maximum(band, relative * np.abs(previous))
        same_direction = (np.sign(current) == np.sign(previous)) & (current != 0.0) & (previous != 0.0)
        small = (np.abs(current - previous) < threshold) & same_direction
        current = np.where(small, previous, current)
        out[t] = current
        previous = current
    return pd.DataFrame(out, index=weights.index, columns=weights.columns)


def banded(weights: pd.DataFrame, params: PortfolioParams) -> pd.DataFrame:
    """The no-trade band as the construction applies it: every knob ``params`` carries, or none at all.

    The one way a book gets banded, for the reason ``cap_gross`` is the one gross cap.
    ``apply_no_trade_band`` takes its knobs one argument at a time, and each caller used to spell the call
    out - so each knob reached only the callers someone remembered.  D2 (2026-09-15) reached
    ``build_weights`` and ``combine_books`` but not ``research book``'s single arms; D3 (2026-09-17)
    reached ``build_weights`` alone.  From then on, every multi-book research reading banded D2 without
    D3, a construction that never traded.  The live loop was never affected: it asks for ``band=False``
    and the rebalancer, which carries D3, bands against the venue's position.  A knob added here reaches
    every book.
    """
    if params.no_trade_band > 0 or params.no_trade_rel_band > 0:
        return apply_no_trade_band(
            weights,
            params.no_trade_band,
            params.no_trade_rel_band,
            params.flat_inside_band,
            params.band_entry_multiple,
        )
    return weights


def cap_gross(weights: pd.DataFrame, max_gross: float) -> pd.DataFrame:
    """Scale each row down to ``sum |w| <= max_gross``; never up, and never below.  ``0`` disables.

    One row-wise gross cap, used in two places: on the combined total (``combine_books``, where it is
    ``max_gross``) and on a non-main book before its fraction (``AlphaModel.book_weights``, where it is
    ``sleeve_max_gross``).  They are the same operation on different books, so they are the same
    function - D-036's rule, arrived at there by finding two copies of the guard semantics that had
    drifted apart.

    A row with no decision yet is all-NaN: its gross sums to zero, the factor is one, and the NaNs
    survive multiplication.  That matters because the caller uses NaN to mean "before this book's
    warmup", not "flat".
    """
    if max_gross <= 0:
        return weights
    gross = weights.abs().sum(axis=1)
    factor = (max_gross / gross.where(gross > max_gross)).fillna(1.0).clip(upper=1.0)
    return weights.mul(factor, axis=0)


def combine_books(books: Mapping[str, pd.DataFrame], params: PortfolioParams) -> pd.DataFrame:
    """Sum independently built books, then the per-symbol cap, the gross cap and the no-trade band on the total.

    Rows where every book is NaN (before the first decision) stay NaN; elsewhere a missing
    book counts as flat.  With a single, already-capped book this is the identity (plus band).
    """
    if not books:
        raise ValueError("no books to combine")
    frames = list(books.values())
    columns = frames[0].columns
    index = frames[0].index
    for frame in frames[1:]:
        columns = columns.union(frame.columns)
        index = index.union(frame.index)
    aligned = [frame.reindex(index=index, columns=columns) for frame in frames]
    valid = aligned[0].notna().any(axis=1)
    total = aligned[0].fillna(0.0)
    for frame in aligned[1:]:
        valid = valid | frame.notna().any(axis=1)
        total = total + frame.fillna(0.0)
    clipped = total.clip(-params.max_weight, params.max_weight)
    weights = cap_gross(clipped, params.max_gross).where(valid, other=np.nan)
    return banded(weights, params)
