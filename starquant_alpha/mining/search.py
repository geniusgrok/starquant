"""Enumerate candidate expressions, deduplicate them by canonical hash, and compile survivors to signals.

The miner **proposes**; nothing here judges.  A candidate compiles to an ordinary ``SignalSpec``, so
walk-forward, CPCV, the trials ledger and the D-020/D-028 verdict decide its fate exactly as they decide a
hand-written signal's.  That is the whole difference from a miner that carries its own evaluation
stack (and whose generators stay unreachable from any entry point).

**The multiple-testing rule this module exists to enforce.**  A search that evaluates 400 expressions and
reports the best one has performed 400 trials, whatever id the survivor is filed under.  Because
``parse_ledger`` filters the trials ledger *by strategy*, giving each candidate a fresh id would hide the
whole search from the DSR denominator - p-hacking with extra steps, and the exact failure D-020 exists to
stop.  So ``SearchResult`` carries ``evaluated``, the count of distinct canonical expressions the search
actually looked at, and ``declared_trials`` is what must be passed to ``research validate --prior-trials``.
Validating a mined candidate without it is not a shortcut; it is a different, wrong experiment.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any

import pandas as pd

from starquant_alpha.mining.expr import (
    Abs,
    Basis,
    Const,
    CrossSectional,
    Expr,
    ExprError,
    Funding,
    HourOfDay,
    LongShortRatio,
    Moment,
    Mul,
    OpenInterest,
    RangePosition,
    Ratio,
    Residual,
    Ret,
    Semi,
    Squash,
    Sum,
    TakerBuy,
    TradeSize,
    Vol,
    VolumeRatio,
    ZScore,
)
from starquant_alpha.panel import Panel
from starquant_alpha.signals.base import SignalSpec, scores_to_targets


@dataclass(frozen=True)
class Candidate:
    """One expression, with the identity and cost the ledger and the verdict need."""

    expr: Expr
    hash: str
    complexity: int
    lookback: int

    @classmethod
    def of(cls, expr: Expr) -> Candidate:
        reduced = expr.canonical()
        return cls(reduced, reduced.canonical_hash(), reduced.complexity(), reduced.lookback())

    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "expression": str(self.expr),
            "complexity": self.complexity,
            "lookback": self.lookback,
        }


#: An expression's SHAPE: magnitudes dropped, operator kinds and discriminating parameters kept.  676
#: candidates are 61 shapes (measured 2026-09-20).  This is the distribution-level reading Q4's ruling
#: leaves open - it says how much of the space is one mechanism re-parameterised and names no
#: candidate, so it is "free to count" rather than the ranked shortlist "free to look" would be.
#:
#: A BLACKLIST of magnitude field names, never a whitelist of discriminating ones, and the direction is
#: the point: a field nobody lists here is kept, so a new parameter can at worst split one shape into
#: several.  A whitelist would fail the other way and quietly fold two mechanisms into one.  The only
#: numeric field that discriminates today is `moment.order` - 3 is skewness, 4 is kurtosis - and the
#: first version of this key, built on `describe()` text, folded exactly that pair together.
_MAGNITUDE_FIELDS = frozenset({"days", "horizon", "scale", "weight", "window"})

#: Nodes whose operands commute.  `canonical()` already sorts them, but it sorts on the constants, so
#: dropping the constants leaves the order arbitrary and has to be re-established.  Measured: without
#: this, `funding/vol * ret/vol` and `ret/vol * funding/vol` are two shapes, and the space reads as 85
#: shapes instead of 61 - 24 of them one mechanism written in both orders.
_COMMUTATIVE = frozenset({"mul", "sum"})


def structural_key(expr: Expr) -> str:
    """The shape `expr` is one parameterisation of.

    Taken off `signature()` rather than the `describe()` text.  The text is what a person reads, and a
    regex over it cannot put a commutative product back in order, which is how the first version
    counted 85: `a * b` and `b * a` are the same mechanism and were two shapes.  The tree knows.
    """
    return json.dumps(_shape(expr.canonical().signature()), sort_keys=True, separators=(",", ":"))


def _shape(node: object) -> object:
    if not isinstance(node, dict):
        return node
    shaped: dict[str, object] = {"k": node["k"]}
    if "p" in node:
        parameters = node["p"]
        assert isinstance(parameters, Mapping)
        shaped["p"] = {name: ("N" if name in _MAGNITUDE_FIELDS else value) for name, value in parameters.items()}
    if "c" in node:
        children = node["c"]
        assert isinstance(children, list)
        kids = [_shape(child) for child in children]
        shaped["c"] = sorted(kids, key=_ordering) if node["k"] in _COMMUTATIVE else kids
    if "t" in node:  # `sum` carries weighted terms; the weight is a magnitude like any other
        terms = node["t"]
        assert isinstance(terms, list)
        shaped["t"] = sorted((["N", _shape(child)] for _, child in terms), key=_ordering)
    return shaped


def _ordering(node: object) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def structural_families(candidates: Sequence[Candidate]) -> dict[str, int]:
    """How many parameterisations each shape holds.  Distribution-level: no candidate, no ranking."""
    families: Counter[str] = Counter()
    for candidate in candidates:
        families[structural_key(candidate.expr)] += 1
    return dict(families)


@dataclass(frozen=True)
class SearchResult:
    """Candidates that survived structural filtering, and the trial count that must be declared."""

    candidates: tuple[Candidate, ...]
    evaluated: int  # distinct canonical expressions the search looked at
    rejected: dict[str, int] = field(default_factory=dict)

    @property
    def declared_trials(self) -> int:
        """What ``research validate --prior-trials`` must receive for any candidate from this search."""
        return self.evaluated

    @property
    def space_digest(self) -> str:
        """R2: WHICH space this was, so a second enumeration of it can be refused rather than charged.

        The identity is the set of canonical expression hashes, not the parameters that produced it.
        Two different parameterisations that enumerate the same set are the same hypothesis space and
        must compare equal; the same parameters against a widened node table are not, and do not.

        Not the same thing as ``evaluated``, which is a count and cannot tell two 514-wide spaces apart,
        and deliberately not written into ``TrialRecord.search_space_version`` - see the note in
        ``research mine``, where changing that field would re-price every existing mined row.
        """
        return hashlib.sha256("|".join(sorted(c.hash for c in self.candidates)).encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "declared_trials": self.declared_trials,
            "kept": len(self.candidates),
            "rejected": dict(self.rejected),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _momentum_family(horizons: Sequence[int], vol_windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """return / volatility, squashed: the shape momentum signals take once the units cancel."""
    for horizon, window, scale in product(horizons, vol_windows, scales):
        yield Squash(Ratio(Ret(horizon), Vol(window)), scale)


def _normalised_family(horizons: Sequence[int], windows: Sequence[int], robust: Sequence[bool]) -> Iterator[Expr]:
    """z-scored returns, then cross-sectionally ranked: a relative-strength shape."""
    for horizon, window, is_robust in product(horizons, windows, robust):
        yield CrossSectional(ZScore(Ret(horizon), window, is_robust), "rank")


def _flow_family(windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """Taker-buy imbalance and volume surprise, the two order-flow shapes this panel can express."""
    for window, scale in product(windows, scales):
        yield Squash(TakerBuy(window), scale)
        yield Squash(VolumeRatio(window), scale)


def _reversal_family(horizons: Sequence[int], windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """The negated z-score.  The first search could not express reversal at all: with no product node
    there was no way to write a minus sign, so every candidate it offered was a momentum shape."""
    for horizon, window, scale in product(horizons, windows, scales):
        yield Squash(Mul(Const(-1.0), ZScore(Ret(horizon), window)), scale)


def _range_family(windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """Position inside the trailing Donchian range - the only family that reads high and low."""
    for window in windows:
        yield CrossSectional(RangePosition(window), "rank")  # scale-free: ranking discards the magnitude
        for scale in scales:
            yield Squash(RangePosition(window), scale)


def _regime_family(
    horizons: Sequence[int],
    vol_windows: Sequence[int],
    long_windows: Sequence[int],
    scales: Sequence[float],
    momentum_window: int,
) -> Iterator[Expr]:
    """Momentum gated by a volatility-regime ratio: short-window vol over long-window vol.

    Both legs are RETURN, so the ratio is dimensionless and the product stays dimensionless.  This is the
    interaction shape - "trade the forecast harder when vol is expanding" - that a sum cannot express.

    The momentum leg's denominator must differ from the regime numerator, and that is not a detail.  The
    first version of this family reused the same window for both, so every candidate it emitted was
    ``(ret/vol_a) * (vol_a/vol_b)``, which cancels algebraically to ``ret/vol_b``: 75 of 255 candidates
    were plain momentum wearing an interaction's clothes, and the run showed it - three of them scored
    0.817, 0.817, 0.818, differing only in where their warmup NaNs fell.  The canonicaliser cannot catch
    this; it folds structural identities, not algebraic ones over division.  So the family excludes the
    cancelling combination itself.
    """
    for horizon, short, long, scale in product(horizons, vol_windows, long_windows, scales):
        if short >= long or short == momentum_window:
            continue
        yield Squash(Mul(Ratio(Ret(horizon), Vol(momentum_window)), Ratio(Vol(short), Vol(long))), scale)


def _multi_horizon_family(horizons: Sequence[int], vol_window: int, scales: Sequence[float]) -> Iterator[Expr]:
    """Equal-weighted sums of two momentum legs: the shape tsmom actually runs, reachable by search."""
    for (fast, slow), scale in product(combinations(horizons, 2), scales):
        legs = ((0.5, Ratio(Ret(fast), Vol(vol_window))), (0.5, Ratio(Ret(slow), Vol(vol_window))))
        yield Squash(Sum(legs), scale)


def _funding_family(
    windows: Sequence[int],
    vol_window: int,
    scales: Sequence[float],
    horizons: Sequence[int],
    interaction_scale: float,
) -> Iterator[Expr]:
    """Carry, and carry crossed with momentum: the only family that reads ``panel.funding``.

    Every shape divides the funding leg by ``Vol`` first, which the dimension system enforces rather than
    suggests - ``Funding`` is RETURN, so ``Squash``, ``Mul`` and a mixed ``Sum`` all refuse it raw.  The
    interaction reuses one ``vol_window`` on both legs, which is safe here and was not in
    ``_regime_family``: this is ``ret * funding / vol**2``, where nothing appears in both a numerator and a
    denominator, so there is no algebraic cancellation for the canonicaliser to miss.

    Three things a reader of the shortlist has to know.

    **Both signs are emitted, so a funding candidate is always near the top.**  ``cross_sectional_rank``
    and ``tanh`` are both odd, so each short shape is the exact mirror of its long one and the mirror of
    the worst candidate is the best.  "A carry expression ranked first" is therefore not information; only
    its margin over the baseline is.

    **The interaction is not a test of tsmom's crowding modifier.**  That modifier is a thresholded,
    one-sided, shrink-only multiplier in {1.0, 0.5} on a cross-sectional *rank* of funding, with
    ``min_periods=window`` and an observed mask.  This is a continuous, symmetric, sign-flipping,
    amplifying product of raw vol-scaled quantities.  No setting of (h, v, w, s, sign) recovers it - the
    positive sign amplifies exactly where the modifier shrinks.  A hit here is an analogy to that
    evidence, never a replication of it.

    **Shape three carries a positive carry weight**, i.e. "go long what pays the most funding", which is
    the opposite of ``carry.py``'s prior.  That is the contract's choice, not an oversight; the negative
    version is reachable through the short arm of shape one.

    Two combinations are excluded by construction.  ``CrossSectional(Funding(w), "rank")`` type-checks -
    ``CrossSectional`` bans only PRICE - but ranks un-normalised carry, which is ``carry.py``'s already
    killed rank mode.  And ``Mul(Ratio(Funding(w), Vol(a)), Ratio(Vol(a), Vol(b)))`` is ``_regime_family``'s
    cancellation verbatim: it collapses to ``funding(w) / vol(b)``, which is shape one with a different
    denominator.
    """
    for window in windows:
        carry = Ratio(Funding(window), Vol(vol_window))
        # The minus sign goes inside the Ratio because Mul refuses a non-RATIO operand and a ranked
        # expression is a SCORE: negating the CrossSectional would raise, and an ExprError leaves this
        # generator closed, silently truncating the rest of the family for one malformed count.
        short_carry = Mul(Const(-1.0), carry)
        yield CrossSectional(carry, "rank")  # scale-free: ranking discards the magnitude
        yield CrossSectional(short_carry, "rank")
        for scale in scales:
            yield Squash(carry, scale)
            yield Squash(short_carry, scale)
        for horizon in horizons:
            momentum = Ratio(Ret(horizon), Vol(vol_window))
            # One operand order only: Mul.canonical sorts by hash, so the reverse is the same tree.
            interaction = Mul(momentum, carry)
            yield Squash(interaction, interaction_scale)
            yield Squash(Mul(Const(-1.0), interaction), interaction_scale)
            yield Squash(Sum(((0.5, momentum), (0.5, carry))), interaction_scale)


def _positioning_family(
    oi_windows: Sequence[int],
    lsr_windows: Sequence[int],
    vol_window: int,
    scales: Sequence[float],
    horizons: Sequence[int],
    interaction_scale: float,
) -> Iterator[Expr]:
    """DL-D4: the only family that reads `panel.metrics` - who is building position, and who is crowded.

    Two leaves with different dimensions and the type system makes the difference load bearing.
    `OpenInterest` is a log CHANGE, so it is RETURN and every shape must divide it by `Vol` before
    `Squash` or `Mul` will take it - exactly as `_funding_family` must.  `LongShortRatio` is already a
    deviation from its own mean, so it is RATIO and passes raw; wrapping it in another normaliser would
    be normalising a normalised quantity, which is how a leaf stops meaning anything.

    Three things a reader of the shortlist has to know, in the shape `_funding_family` established.

    **Both signs are emitted, so a positioning candidate is always near the top.**  `cross_sectional_rank`
    and `tanh` are odd, so every short shape is the exact mirror of its long one and the mirror of the
    worst candidate is the best.  "A positioning expression ranked first" is not information; its margin
    over the baseline is.

    **The interactions are the hypotheses, the leaves alone are the controls.**  "Price moved and open
    interest rose" (new money) is a different claim from "price moved and open interest fell" (covering),
    and neither is expressible by either leaf alone - that is the reason for the family rather than for
    two more solitary leaves.

    **The long/short leaf is a CONTRARIAN prior in shape four and its mirror is in the family too.**  The
    published intuition is that crowded-long names fall, so the negated arm is the one that matches it;
    both ship, because deciding which sign is right from the same data that ranked them is the failure
    this whole pipeline exists to refuse.

    Grid choice, pre-registered: `oi_windows` reuses `funding_windows`' values because the meaning
    carries - a trailing window over a five-minute-bucket series - and `lsr_windows` drops the shortest,
    because the leaf is already a deviation from a rolling mean and a 24-bar base makes it mostly noise
    about noise.  The interaction's momentum leg takes `horizons`, the general return-horizon dimension,
    so an operator rescaling the search for another interval rescales it too.  Adding a value is a
    parameter; adding a fifth shape is a hypothesis (KILL-P6).
    """
    for window in oi_windows:
        flow = Ratio(OpenInterest(window), Vol(vol_window))
        short_flow = Mul(Const(-1.0), flow)
        yield CrossSectional(flow, "rank")
        yield CrossSectional(short_flow, "rank")
        for scale in scales:
            yield Squash(flow, scale)
            yield Squash(short_flow, scale)
        for horizon in horizons:
            momentum = Ratio(Ret(horizon), Vol(vol_window))
            interaction = Mul(momentum, flow)
            yield Squash(interaction, interaction_scale)
            yield Squash(Mul(Const(-1.0), interaction), interaction_scale)
    for window in lsr_windows:
        crowding = LongShortRatio(window)
        short_crowding = Mul(Const(-1.0), crowding)
        yield CrossSectional(crowding, "rank")
        yield CrossSectional(short_crowding, "rank")
        for scale in scales:
            yield Squash(crowding, scale)
            yield Squash(short_crowding, scale)
        for horizon in horizons:
            momentum = Ratio(Ret(horizon), Vol(vol_window))
            interaction = Mul(momentum, crowding)
            yield Squash(interaction, interaction_scale)
            yield Squash(Mul(Const(-1.0), interaction), interaction_scale)


# --- DL-A1: five families over the panel's existing columns ------------------------------------
#
# One family per new node, and each says something none of the seven before it could.  All of them
# emit both signs wherever the outer operator is odd (`cross_sectional_rank` and `tanh` both are), so
# - exactly as `_funding_family` records - "a candidate of this family ranked first" is not
# information; the mirror of the worst tree is the best one.  Only the margin over the baseline is.


def _seasonality_family(
    hod_days: Sequence[int],
    vol_window: int,
    scales: Sequence[float],
    horizons: Sequence[int],
    interaction_scale: float,
) -> Iterator[Expr]:
    """#8: does a symbol's own hour of the UTC day carry anything, and does it modulate momentum?

    `HourOfDay` is a mean RETURN, so every shape divides it by `Vol` before `Squash` or `Mul` will
    take it - the same discipline `OpenInterest` and `_funding_family` are held to, and the type
    system is what enforces it rather than a comment.

    Both signs ship, for the reason `_positioning_family` states: `cross_sectional_rank` and `tanh`
    are odd, so every short shape is the exact mirror of its long one and "a seasonality expression
    ranked first" is not information.  Deciding the sign from the same data that ranked it is the
    failure this pipeline exists to refuse.

    The interaction is the hypothesis worth more than the leaf.  "This hour has been kind to this
    symbol" is weak on its own; "this hour has been kind AND the symbol is trending" is a different
    claim, and the leaf's one-occurrence shift is what keeps it from being momentum times itself.

    Grid choice, pre-registered: `hod_days` is {14, 30, 56} - two weeks, a month, eight weeks of the
    same hour.  Shorter than two weeks is fourteen numbers averaging noise; longer than two months and
    any intraday shape that is real has had time to move.  Adding a value is a parameter; adding a
    fifth shape is a hypothesis (KILL-P6).

    56 rather than 60 because `max_lookback` is 1400 and `hod(60)` reserves `(60 + 1) * 24 = 1464`.
    The first draft wrote 60 and the enumeration dropped all eighteen of its shapes as `too_long` -
    silently, since a rejection tally is not a failure.  A grid that reports three windows and
    searches two is a pre-registration that is not true, which is worse than a narrower grid.
    """
    for days in hod_days:
        seasonal = Ratio(HourOfDay(days), Vol(vol_window))
        short_seasonal = Mul(Const(-1.0), seasonal)
        yield CrossSectional(seasonal, "rank")
        yield CrossSectional(short_seasonal, "rank")
        for scale in scales:
            yield Squash(seasonal, scale)
            yield Squash(short_seasonal, scale)
        for horizon in horizons:
            momentum = Ratio(Ret(horizon), Vol(vol_window))
            interaction = Mul(momentum, seasonal)
            yield Squash(interaction, interaction_scale)
            yield Squash(Mul(Const(-1.0), interaction), interaction_scale)


def _basis_family(
    vol_window: int,
    scales: Sequence[float],
    horizons: Sequence[int],
    interaction_scale: float,
) -> Iterator[Expr]:
    """DL-D5, block 2: the only family that reads `panel.spot` - how rich the perpetual is against spot.

    `Basis` is a log price ratio, so it is RETURN and every shape divides it by `Vol` before `Squash`
    or `Mul` will take it, exactly as `_funding_family` must.  The leaf's own docstring carries the
    pre-registered choice of writing (log ratio, level, un-annualised, no window) and why the other
    three were rejected; this docstring is about the family.

    **The question that had to be answered before a hit here could mean anything - is this the carry
    family wearing a different hat? - and it was answered by measurement, not by argument.**  Funding
    is the venue's instrument for pinning the perpetual to spot, so the two are the ends of one
    arbitrage relation and a near-collinear pair was the expected answer.  It is not what the data
    says.  Measured 2026-09-09 on 20 liquid perpetuals x 14,592 hourly bars (2025-01..2026-08), spot
    fetched from the venue and joined by `align_spot_to_perp_bars`:

    * raw leaf, pooled: corr(basis, funding(w)) = +0.27 / +0.24 / +0.23 for w = 24 / 72 / 168.
    * the node every shape here actually uses: corr(basis/vol(48), funding(w)/vol(48)) = +0.25 to
      +0.26 by Pearson but only +0.09 by Spearman - the agreement lives in the tails, not the body.
    * what the family TRADES: cs_rank(basis/vol) against cs_rank(funding(w)/vol) has a per-bar
      cross-sectional Spearman of +0.045 on the mean bar, with a 5th-95th percentile of -0.41 to
      +0.48.  On the typical bar the two order the board almost independently, and the sign of the
      relationship flips from bar to bar.
    * regressing basis/vol on funding(w)/vol gives R^2 = 0.064 / 0.064 / 0.067.  Funding accounts for
      about a fifteenth of this leaf's variance.

    Two mechanisms explain the gap and both are visible in the same data.  Binance's funding formula
    adds a constant interest term (0.01%/8h) to the premium and then clamps, so funding is not a
    monotone reading of the premium; and funding is charged on the perpetual against the multi-venue
    INDEX, while this leaf reads it against Binance spot.  Those are two different spreads, measured
    the same day: log(index / Binance spot) was +0.00000 to +0.00035 across eight majors while
    log(mark / Binance spot) was -0.00026 to -0.00067.  So the honest statement is that this family is
    NOT a restatement of carry - and that the reason is partly an artefact of which spot leg the
    venue's own formula uses, which is a caveat on the hypothesis rather than support for it.

    **The residual shape is missing on purpose and it is the one a reader will want to add.**  The
    orthogonal writing is `basis/vol - funding/vol`, and `Sum` is the only operator that can express it.
    `Sum.evaluate` adds with `fill_value=0.0`, so a NaN term enters as a zero: on the 166 of 528
    perpetuals with no spot leg, that shape evaluates to pure carry with nothing saying so - a signal
    that scores the whole board while reading spot on two thirds of it.  Adding it before `Sum`
    propagates missing values would put the exact substitution `align_spot_to_perp_bars` refuses back
    into the pipeline one layer up.

    **Both signs ship**, for the reason `_funding_family` records: `cross_sectional_rank` and `tanh`
    are odd, so each short shape is the exact mirror of its long one and "a basis candidate ranked
    first" is not information - only its margin over the baseline is.  Which sign is right is a real
    open question here (does an un-charged premium mean-revert, or does it mark the crowd that is
    about to keep being right?), and deciding it from the data that ranked it is what D-020 exists for.

    **Six of the eighteen shapes are a market-wide tilt in disguise, and that was measured too.**  The
    basis has a common level as well as a spread, and the level is nearly always on one side: on the
    same 20-symbol sample its bar-mean is negative on 98.1% of bars (median -0.000537), which is the
    sign Binance's constant interest term implies.  So `Squash(carry, s)`, which keeps the level, gives
    a POSITIVE score to only 8.9% of symbols on the mean bar - it is close to "hold the same side of
    almost everything, almost always", i.e. a directional bet on the board rather than a claim about
    which symbol is rich.  `CrossSectional(..., "rank")` removes it, and the cross-sectional part is
    the larger half anyway (84% of total variance), so the ranked arm is where the stated hypothesis
    actually lives.  The level shapes still ship - dropping them would make this family
    non-comparable with `_funding_family`, whose level shapes are exactly as one-sided - but a hit on
    one of them is a claim about market direction and its falsifier is a constant-position control,
    not a baseline book.

    **The universe is not the same universe, and that is this family's own confound.**  A basis
    candidate can only score 362 of 528 perpetuals; every other family scores all of them.  So a
    marginal over a `--baseline` book is measured across a smaller cross-section, and a Sharpe
    difference that comes from holding a third fewer names is not an edge.  The falsifier for that is
    in the pre-registration, not in the code.

    Grid choice, pre-registered: no basis-specific value at all.  The leaf takes no window (see its
    docstring), `vol_window` reuses `vol_windows[0]` as every other interaction family does, and the
    momentum leg takes `horizons`, the general return-horizon dimension, so an operator rescaling the
    search for another interval rescales it too.  That makes this the cheapest family in the module -
    18 expressions - which is the right size for a hypothesis whose most likely verdict is "already
    searched under another name".  Adding a value is a parameter; adding a fourth shape is a hypothesis
    (KILL-P6).

    Lookback is `Ret(max(horizons)) + 1` and nothing else: `Basis` reserves one bar and `Vol(48)`
    twenty-five, so at the declared grid the family's deepest shape is 721 against `max_lookback`
    1400.  Stated because `hod(60)` was not - it reserved 1464, and all eighteen of its shapes left as
    `too_long` while the grid still claimed three windows.
    """
    carry = Ratio(Basis(), Vol(vol_window))
    # The minus sign goes inside, never around a `CrossSectional`: negating a SCORE raises, and an
    # `ExprError` closes this generator, which would truncate the rest of the family for one count.
    short_carry = Mul(Const(-1.0), carry)
    yield CrossSectional(carry, "rank")  # scale-free: ranking discards the magnitude
    yield CrossSectional(short_carry, "rank")
    for scale in scales:
        yield Squash(carry, scale)
        yield Squash(short_carry, scale)
    for horizon in horizons:
        momentum = Ratio(Ret(horizon), Vol(vol_window))
        # One operand order only: `Mul.canonical` sorts by hash, so the reverse is the same tree.
        interaction = Mul(momentum, carry)
        yield Squash(interaction, interaction_scale)
        yield Squash(Mul(Const(-1.0), interaction), interaction_scale)


def _surprise_family(horizons: Sequence[int], z_windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """How *far* a symbol moved, with the direction thrown away.

    The hypothesis the language could not state before ``Abs``: an unusually large move is itself a
    predictor, whichever way it went.  ``|ret|`` z-scored against its own history is the "surprise",
    and both signs are searched because the crypto literature disagrees with itself about whether a
    shock continues or reverts - which is the honest reason to let the data answer.
    """
    for horizon in horizons:
        surprise = ZScore(Abs(Ret(horizon)), z_windows[0])
        for window in z_windows:
            yield CrossSectional(ZScore(Abs(Ret(horizon)), window), "rank")
        for scale in scales:
            yield Squash(surprise, scale)
            yield Squash(Mul(Const(-1.0), surprise), scale)


def _shape_family(moment_windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """Skewness and kurtosis of one-bar returns: the two shapes a mean and a variance cannot see.

    A distribution that has been paying small gains and taking rare large losses looks identical to
    ``Vol`` and quite different to ``Moment``.  Both orders and both signs; nothing here has a prior
    strong enough to fix one.
    """
    for window in moment_windows:
        for order in (3, 4):
            shape = Moment(Ret(1), order, window)
            yield CrossSectional(shape, "rank")
            for scale in scales:
                yield Squash(shape, scale)
                yield Squash(Mul(Const(-1.0), shape), scale)


def _downside_family(horizons: Sequence[int], semi_windows: Sequence[int], scales: Sequence[float]) -> Iterator[Expr]:
    """Momentum scaled by the risk that hurts, instead of by all movement.

    ``_momentum_family`` divides a return by ``Vol``, which charges a rally and a crash the same
    amount.  This divides by ``Semi``, so a symbol that rose in a straight line is not penalised for
    having risen.  It is the same hypothesis measured with a different denominator, which is exactly
    the sort of thing a search should settle rather than an author.
    """
    for horizon in horizons:
        for window in semi_windows:
            scaled = Ratio(Ret(horizon), Semi(Ret(1), window))
            yield CrossSectional(scaled, "rank")
            for scale in scales:
                yield Squash(scaled, scale)
                yield Squash(Mul(Const(-1.0), scaled), scale)


def _residual_family(
    horizons: Sequence[int], residual_windows: Sequence[int], vol_window: int, scales: Sequence[float]
) -> Iterator[Expr]:
    """Residual momentum: the part of the move the market did not explain.

    tsmom trades the whole move, so in a market where everything rises together it is largely long
    beta.  Residualising against the cross-sectional mean asks whether what is left over - the part
    specific to the symbol - carries the edge.  The market is taken over ``panel.reference``, so this
    family inherits P1-01's contract rather than re-opening it.
    """
    for horizon in horizons:
        for window in residual_windows:
            residual = Ratio(Residual(Ret(horizon), window), Vol(vol_window))
            yield CrossSectional(residual, "rank")
            for scale in scales:
                yield Squash(residual, scale)
                yield Squash(Mul(Const(-1.0), residual), scale)


def _print_size_family(
    trade_windows: Sequence[int], z_windows: Sequence[int], horizons: Sequence[int], scales: Sequence[float]
) -> Iterator[Expr]:
    """Whether the volume arrived as a few large prints or many small ones.

    The only hypothesis in this batch that reads a column no node had ever read (``panel.trades``).
    ``_flow_family`` knows how much traded and who lifted; it cannot tell one 10 BTC print from a
    thousand 0.01 ones, and the folklore that large prints lead is at least worth one family.  The
    interaction with momentum is included because "big prints in the direction of the trend" is the
    specific version of the claim that would be interesting.
    """
    for window in trade_windows:
        size = ZScore(TradeSize(window), z_windows[0])
        yield CrossSectional(size, "rank")
        for scale in scales:
            yield Squash(size, scale)
            yield Squash(Mul(Const(-1.0), size), scale)
        for horizon in horizons:
            interaction = Mul(Ratio(Ret(horizon), Vol(z_windows[0])), size)
            yield Squash(interaction, scales[0])
            yield Squash(Mul(Const(-1.0), interaction), scales[0])


def enumerate_candidates(
    *,
    horizons: Sequence[int] = (24, 72, 168, 336, 720),
    vol_windows: Sequence[int] = (48, 168, 400),
    scales: Sequence[float] = (0.5, 1.0, 2.0),
    z_windows: Sequence[int] = (72, 168, 336),
    flow_windows: Sequence[int] = (4, 12, 24),
    range_windows: Sequence[int] = (24, 72, 168),
    regime_long_windows: Sequence[int] = (400, 720),
    include_funding: bool = True,
    funding_windows: Sequence[int] = (24, 72, 168),
    # DL-D4.  A search-space parameter, not a panel probe, for the same reason `include_funding` is:
    # this function must stay deterministic and data-free so `_resolve_mined` can re-derive an id.
    include_metrics: bool = True,
    oi_windows: Sequence[int] = (24, 72, 168),
    lsr_windows: Sequence[int] = (72, 168),
    funding_horizons: Sequence[int] = (72, 168),
    funding_scale: float = 1.0,
    # DL-A1 windows.  Reused from the families above wherever the meaning carries over, so the space
    # grows by hypotheses rather than by a fourth value of something already searched (KILL-P6).
    moment_windows: Sequence[int] = (168, 336),
    semi_windows: Sequence[int] = (72, 168),
    residual_windows: Sequence[int] = (168, 336),
    trade_windows: Sequence[int] = (24, 72),
    # #8, block 2.  Occurrences of the hour, not bars; see `HourOfDay`.
    include_seasonality: bool = True,
    hod_days: Sequence[int] = (14, 30, 56),
    # DL-D5, block 2.  A search-space parameter for the same reason `include_funding` and
    # `include_metrics` are: this function stays deterministic and data-free, and the caller narrows
    # the space when its panel carries no spot.  Unlike those two, the narrowing is the COMMON case and
    # today it is the ONLY case - `research mine` narrows on `Panel.spot_symbols`, and nothing builds a
    # panel with a spot store yet, so these 18 shapes are enumerable here and unreachable there.  That
    # asymmetry is deliberate: the space stays declared and hashable (so an id keeps resolving) without
    # charging `declared_trials` for a family no panel can score.
    include_basis: bool = True,
    include_panel_nodes: bool = True,
    max_complexity: int = 10,
    max_lookback: int = 1400,
) -> SearchResult:
    """Enumerate the declared families, drop malformed and duplicate trees, and count everything looked at.

    ``max_lookback`` defaults just under the venue's 1,500-bar request ceiling (E-042): a signal whose
    warmup exceeds what the live loop can fetch is not a candidate, it is a bug waiting for a restart.

    The families are structural shapes, not parameter values, and that distinction is the point.  Adding
    a fourth scale to an existing family would raise ``declared_trials`` - and so the DSR bar anything
    promoted has to clear - without adding a hypothesis.  Each family here says something the others
    cannot: reversal needs a minus sign, the range family is the only reader of high and low, the regime
    family is the only interaction, the multi-horizon family is the only sum, and the funding family
    expresses carry - the one panel input no node could read until ``Funding`` existed.

    ``include_funding`` is a search-space parameter and not a panel probe, deliberately: this function
    stays deterministic and touches no data, which is the property ``research_cmd._resolve_mined`` relies
    on to re-derive a ``mined_<hash>`` id without persisting anything.  The caller narrows the space when
    its panel carries no funding.

    ``max_complexity`` is 10 rather than 8 because the contract's signed momentum-times-carry product is a
    ten-node tree - the minus sign costs two nodes.  The raise is inert on what came before, and the
    reason is monotonicity, not headroom: relaxing an upper bound can only admit trees, never drop them,
    and the recorded baseline has ``rejected["too_complex"] == 0``, so nothing that existed exceeded 8.
    Headroom is precisely what there is none of - 75 of the 225, the single largest bucket, sit *at*
    complexity 8 - so the next momentum-shaped family will land on the cap again.  Asserted rather than
    argued: the identity test enumerates the pre-``Funding`` space at both 8 and 10 and requires the same
    225 hashes in the same order.  At 8 the six negated interaction trees are charged to
    ``declared_trials`` and then dropped unscored, which is the worst of both.
    """
    seen: dict[str, Candidate] = {}
    rejected = {"malformed": 0, "duplicate": 0, "too_complex": 0, "too_long": 0}
    evaluated = 0
    families: tuple[Iterator[Expr], ...] = (
        _momentum_family(horizons, vol_windows, scales),
        _normalised_family(horizons, z_windows, (False, True)),
        _flow_family(flow_windows, scales),
        _reversal_family(horizons, z_windows, scales),
        _range_family(range_windows, scales),
        _regime_family(horizons, vol_windows, regime_long_windows, scales, vol_windows[0]),
        _multi_horizon_family(horizons, vol_windows[0], scales),
    )
    if include_funding:
        families = (
            *families,
            _funding_family(funding_windows, vol_windows[0], scales, funding_horizons, funding_scale),
        )
    if include_metrics:
        # Appended, never interleaved, for the reason recorded below: a family's position does not enter
        # a candidate's hash, but the order candidates are FIRST SEEN in decides which duplicate is kept,
        # and every id already in the ledger has to keep resolving.
        families = (
            *families,
            # `horizons`, not `funding_horizons`: the interaction's momentum leg is a return over a
            # horizon, so it belongs to the dimension an operator rescales when the interval changes.
            # Caught by T-P19's rescale test, which is exactly what that test is for - it read `ret(72)`
            # out of a search whose horizons had been overridden to {1, 3, 7}.
            _positioning_family(oi_windows, lsr_windows, vol_windows[0], scales, horizons, funding_scale),
        )
    if include_panel_nodes:
        # Appended, never interleaved: a family's position does not enter a candidate's hash, but the
        # order candidates are *first seen* in decides which duplicate is kept, and every id already in
        # the ledger has to keep resolving (T-A1-3).
        families = (
            *families,
            _surprise_family(horizons, z_windows, scales),
            _shape_family(moment_windows, scales),
            _downside_family(horizons, semi_windows, scales),
            _residual_family(horizons, residual_windows, vol_windows[0], scales),
            _print_size_family(trade_windows, z_windows, horizons, scales),
        )
    if include_seasonality:
        # Appended for the same reason the panel nodes are: a family's position does not enter a
        # candidate's hash, but the order candidates are FIRST SEEN in decides which duplicate is
        # kept, and every id already in the ledger has to keep resolving (T-A1-3).
        families = (*families, _seasonality_family(hod_days, vol_windows[0], scales, horizons, funding_scale))
    if include_basis:
        # Appended last, and never interleaved, for the reason every block above it records: a family's
        # position does not enter a candidate's hash, but the order candidates are FIRST SEEN in decides
        # which duplicate is kept, and every id already in the ledger has to keep resolving (T-A1-3).
        # Last specifically, and not merely appended: this is the newest family, so appending it here is
        # the only position that leaves all six earlier append points reading exactly as they did.
        families = (*families, _basis_family(vol_windows[0], scales, horizons, funding_scale))
    for family in families:
        while True:
            try:
                expr = next(family)
            except StopIteration:
                break
            except ExprError:  # a family that generates an illegal combination is a bug, not a candidate
                rejected["malformed"] += 1
                continue
            candidate = Candidate.of(expr)
            if candidate.hash in seen:
                rejected["duplicate"] += 1
                continue
            evaluated += 1
            if candidate.complexity > max_complexity:
                rejected["too_complex"] += 1
                continue
            if candidate.lookback > max_lookback:
                rejected["too_long"] += 1
                continue
            seen[candidate.hash] = candidate
    ordered = tuple(sorted(seen.values(), key=lambda c: (c.complexity, c.hash)))
    return SearchResult(candidates=ordered, evaluated=evaluated, rejected=rejected)


def to_signal(candidate: Candidate) -> SignalSpec:
    """Compile a candidate into the ordinary signal contract, so the existing judge applies unchanged."""

    def compute(panel: Panel, params: Mapping[str, Any]) -> pd.DataFrame:
        scores = candidate.expr.evaluate(panel)
        return scores_to_targets(
            scores.clip(-1.0, 1.0),
            float(params.get("entry_threshold", 0.2)),
            hold=True,
            zero_is_exit=False,
        )

    def warmup(params: Mapping[str, Any]) -> int:
        """Derived from the tree, not declared by hand, which is the point of tracking lookback at all."""
        return candidate.lookback

    # Derived from the candidate, never from a flag threaded in from the caller: ``research mine`` and
    # ``_resolve_mined`` build the same id by different routes, and ``register`` overwrites by id without
    # comparing.  A hardcoded ``False`` here is the KILL-027 shape - a signal telling the live loop it
    # needs no funding history and then reading ``panel.funding`` anyway (D-023).
    reads_funding = candidate.expr.reads_funding()
    # DL-D4, and the same sentence as the line above with one word changed: research reads a T+1
    # archive the live loop cannot have for its first 30 days, so a candidate that reads a metrics
    # column must say so or `metrics_refusal` has nothing to refuse on.  Derived from the tree for the
    # same reason `reads_funding` is - `research mine` and `_resolve_mined` build this spec by
    # different routes and `register` overwrites by id without comparing.
    reads_metrics = bool(candidate.expr.reads_metrics())
    # DL-D5, the third of these, and the one that had to be added rather than inherited: the inherited
    # WIP defined `Expr.reads_spot` and never called it, which is a declaration nothing declares to.
    # A spot-reading candidate that reached live without saying so would raise `ExprError` from inside
    # a cycle - loud, but loud in the wrong place, mid-loop instead of at startup.
    reads_spot = candidate.expr.reads_spot()

    return SignalSpec(
        id=f"mined_{candidate.hash}",
        compute=compute,
        default_params={"entry_threshold": 0.2, "expression": str(candidate.expr), "hash": candidate.hash},
        description=f"mined candidate {candidate.expr}",
        warmup_bars=candidate.lookback,
        warmup=warmup,
        uses_funding=lambda params: reads_funding,
        needs_metrics=lambda params: reads_metrics,
        needs_spot=lambda params: reads_spot,
        canonical=dict,
    )


def _reading(row: Mapping[str, Any]) -> tuple[str, Any]:
    """What a shortlist row says about one candidate, reduced to the part a re-run is bought for.

    A score, or the absence of one.  The error TEXT is deliberately not part of it: "bought nothing"
    is a claim about scores, and a round that produced the same non-scores with a differently worded
    exception still produced no scores.
    """
    return ("error",) if "error" in row else ("scored", row.get("sharpe"))  # type: ignore[return-value]


def scoring_reproduction(previous: Sequence[Mapping[str, Any]], current: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Did this round reproduce its predecessor, or did it buy something?

    R2 refuses a re-run of an enumerated space unless `--reauthorize` carries a reason, and the
    reasons given have been specific and checkable ("these 90 errored, the fix landed in 3b49af8, so
    re-run them").  What no artefact has ever recorded is whether the reason came true.  On
    2026-09-09 one did not: the 09:50Z round charged 658 rows and returned all 658 Sharpes identical
    to 08:29Z, the same 90 errors included, because the fix it invoked had not reached that path.

    The round is charged either way and this changes nothing about that - whether a reproduced round
    stays in the ledger is Q7's kind of ruling, made by a person. This only makes the question
    answerable from the artefact instead of by diffing two reports by hand.

    `bought_nothing` is false for a first run of a space: nothing to reproduce is not the same fact
    as reproducing everything, and a vacuous true here would fire on precisely the rounds that are
    doing the work.
    """
    before = {row["hash"]: _reading(row) for row in previous if "hash" in row}
    after = {row["hash"]: _reading(row) for row in current if "hash" in row}
    shared = before.keys() & after.keys()
    return {
        "compared": len(shared),
        "identical": sum(1 for key in shared if before[key] == after[key]),
        "newly_scored": sum(1 for key in shared if before[key][0] == "error" and after[key][0] == "scored"),
        "unseen": len(after.keys() - before.keys()),
        "bought_nothing": bool(before) and bool(after) and before == after,
    }
