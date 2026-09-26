"""The alpha model: registry entries -> per-strategy targets -> per-book conviction -> portfolio weights.

Strategies belong to books.  The main book is built exactly as before (ensemble mean -> vol
target -> caps -> no-trade band).  A non-main book (D-018/D-019) is built on its own, scaled
by its fraction of the main risk budget and summed with the main book; the main book's caps
and band then apply to the total (``combine_books``).  With only the main book present the
code path is bit-for-bit the original one.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

import pandas as pd

from starquant_alpha.ensemble import TargetWeights, combine_targets, snapshot
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import (
    PortfolioParams,
    asset_vol,
    build_weights,
    cap_gross,
    clipped_risk_share,
    combine_books,
    ewma_portfolio_vol,
    vol_targeted,
)
from starquant_alpha.registry import MAIN_BOOK, Registry, StrategyEntry
from starquant_alpha.signals import get_signal, scores_to_targets

# strategy -> symbol -> the unscaled target recorded at the end of the previous live cycle (the D-005 hold seed, E-042)
PreviousTargets = Mapping[str, Mapping[str, float]]


def _last_finite(series: pd.Series) -> float | None:
    """The newest value a diagnostic could compute, or ``None`` when it could not compute one.

    `None` rather than 0.0, the same distinction `Panel.metric` draws one layer down: a book whose
    covariance is still warming up and a book at zero volatility are different facts, and only one of
    them is fixed by waiting.  The daily report says `enforced: false` for the same reason (D-035).
    """
    if series.empty:
        return None
    value = float(series.iloc[-1])
    return None if not math.isfinite(value) else value


class FundingUnavailable(ValueError):
    """The panel cannot supply funding history an enabled signal reads (E-040 / KILL-027).

    A ``ValueError``, so every caller that already catches one is unaffected, but its own type so the
    two places that score many things in a loop can let it through.  Both treat a failure as a property
    of the ITEM - ``research mine`` drops a candidate that raises into an ``error`` row,
    ``parameter_neighborhood`` records a perturbation that raises as ``None`` - and a missing archive is
    a property of the RUN, so under those handlers the refusal became a quietly thinner shortlist or a
    missing neighbour rather than a stop.  A guard that any blanket handler can absorb is not a guard.
    """


@dataclass(frozen=True)
class AlphaModel:
    entries: tuple[StrategyEntry, ...]
    portfolio: PortfolioParams
    interval: str
    ensemble_method: str = "mean"
    hold_on_no_action: bool = True
    min_history_bars: int = 720
    books: dict[str, float] = field(default_factory=dict)  # non-main book -> fraction of the main risk budget
    # The pinned traded population, carried so `registry_digest` can see it: this model IS what the
    # running process holds, and a loop holding one universe while the file names another is KILL-Q15's
    # shape.  Empty when the registry pins none, which is every registry written before 2026-09-09.
    universe: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, fraction in self.books.items():
            if name == MAIN_BOOK or not 0 < fraction <= 1:
                raise ValueError(f"book {name!r}: fraction must be in (0, 1] and the main book is implicit")
        for entry in self.entries:
            if entry.book != MAIN_BOOK and entry.book not in self.books:
                raise ValueError(f"strategy {entry.id} refers to undeclared book {entry.book!r}")
        # Every per-strategy structure in this class is a dict keyed by id, so two entries sharing one
        # would silently become one and the loop would trade a book it cannot name.  `parse_registry`
        # already refuses this for a registry read from disk; said here too, because a model can also be
        # built by `replace`, by a test, or by a miner assembling entries by hand.
        ids = [entry.id for entry in self.entries]
        repeated = sorted({name for name in ids if ids.count(name) > 1})
        if repeated:
            raise ValueError(f"duplicate strategy id {repeated}: per-strategy results are keyed by id")

    @classmethod
    def from_registry(
        cls, registry: Registry, portfolio: PortfolioParams, interval: str, *, min_history_bars: int = 720
    ) -> AlphaModel:
        if not registry.enabled:
            raise ValueError("registry has no enabled strategies")
        counts = Counter(entry.book for entry in registry.enabled)
        crowded = sorted(book for book, count in counts.items() if count > 1)
        if crowded:
            # The `turnover_penalty` precedent, one layer up: a path that is reachable, looks supported
            # and has never been scored.  `book_targets` combines a book's strategies with
            # `combine_targets`, which takes a weighted MEAN of their targets, and `build_weights` then
            # sizes on that number - so two strategies at +1 and -1 produce 0, which `scores_to_targets`
            # would have read as NO_ACTION and this path reads as a CLOSE, and three at +1/+1/-1 produce
            # a third of a position.  That is the magnitude back in the book.
            #
            # `conviction_mode: sign` was adopted on the measurement that magnitude carries no return
            # information (D-024: `magnitude_over_direction` is exactly 0.0, and the paired per-bar
            # difference has a Newey-West t of -0.047), and no run has ever scored the ensemble that
            # puts it back.  Today the refusal is unreachable - both books run one strategy - which is
            # the right time to write it: the day a second one is added is the day this should be a
            # decision with evidence rather than a side effect of an `enabled: true`.
            #
            # Refused HERE and not in `AlphaModel.__post_init__` or `parse_registry`: this is the seam
            # where a registry becomes the model the live loop holds (`composition.build_model`).
            # Research builds multi-strategy models directly - `research correlate` is exactly that -
            # and measuring the combination is how it would ever earn its way in.
            raise ValueError(
                f"book(s) {crowded} enable more than one strategy, and the ensemble that would combine "
                "them re-introduces the magnitude this construction was validated without: "
                "`combine_targets` takes a weighted mean of per-strategy targets and `build_weights` "
                "sizes on it, so +1 and -1 become a close and +1/+1/-1 becomes a third of a position.  "
                "D-024 measured that magnitude carries no return information and `conviction_mode: sign` "
                "was adopted on it; the combination has never been scored.  Wiring it is a construction "
                "change with its own evidence - until then a book runs one strategy."
            )
        return cls(
            entries=registry.enabled,
            portfolio=portfolio,
            interval=interval,
            ensemble_method=registry.ensemble_method,
            min_history_bars=min_history_bars,
            books={name: spec.fraction for name, spec in registry.books.items()},
            universe=registry.universe,
        )

    # --- books ----------------------------------------------------------------
    @property
    def book_names(self) -> tuple[str, ...]:
        """Books in use, the main book first."""
        names = [MAIN_BOOK] if any(entry.book == MAIN_BOOK for entry in self.entries) else []
        for entry in self.entries:
            if entry.book not in names:
                names.append(entry.book)
        return tuple(names)

    def fraction(self, book: str) -> float:
        return 1.0 if book == MAIN_BOOK else self.books[book]

    def entries_of(self, book: str) -> tuple[StrategyEntry, ...]:
        return tuple(entry for entry in self.entries if entry.book == book)

    def without_books(self, names: Iterable[str]) -> AlphaModel:
        """The same model with the given books (and their strategies) removed - a stopped probe (D-019)."""
        dropped = set(names)
        if MAIN_BOOK in dropped:
            raise ValueError("the main book cannot be stopped")
        entries = tuple(entry for entry in self.entries if entry.book not in dropped)
        if not entries:
            raise ValueError("stopping these books would leave no strategy")
        return replace(self, entries=entries, books={k: v for k, v in self.books.items() if k not in dropped})

    def without_symbols(self, symbols: Iterable[str]) -> AlphaModel:
        """A model that no longer names `symbols` in its pinned universe.

        The mirror of `without_books`, and it exists for the same reason: when the loop stops trading
        something, `registry_digest` has to stop claiming it does.  D-031 quarantines a symbol the venue
        keeps rejecting, which under a pinned universe is the machine departing from a governed decision -
        measured 2026-09-09: one quarantine left the engine trading 17 of 18 pinned symbols while the
        digest stayed byte-identical, so `live status --check` would keep reporting agreement.
        """
        drop = {str(symbol).upper() for symbol in symbols}
        if not drop or not self.universe:
            return self
        return replace(self, universe=tuple(s for s in self.universe if s not in drop))

    # --- targets --------------------------------------------------------------
    def eligible(self, panel: Panel, membership: pd.DataFrame | None = None) -> pd.DataFrame:
        """Symbols become tradable only after ``min_history_bars`` observed bars (new listings are excluded).

        ``membership`` (bool, bars x symbols) restricts trading to the point-in-time universe (D-013).
        """
        history = panel.close.notna().cumsum() >= self.min_history_bars
        if membership is None:
            return history
        member = membership.reindex(index=panel.index, columns=panel.close.columns).fillna(False).astype(bool)
        return history & member

    @property
    def warmup_bars(self) -> int:
        """Bars the model needs before its first decision, under the *registry* parameters.

        Derived from each signal's actual params (a 720-bar horizon needs 721
        bars), not from the signal defaults: the defaults once sized the live
        request window at 817 bars for a weekly strategy (E-042).
        """
        signal_warmup = max(get_signal(entry.id).warmup_for(entry.params) for entry in self.entries)
        return max(signal_warmup, self.portfolio.covariance_halflife, self.portfolio.vol_halflife) + 1

    @property
    def needs_funding(self) -> bool:
        """True when any enabled signal reads funding history under its registry params (KILL-027)."""
        return any(get_signal(entry.id).needs_funding(entry.params) for entry in self.entries)

    def reference_for(self, panel: Panel, membership: pd.DataFrame | None = None) -> pd.DataFrame:
        """The cross-sectional population for these bars (P1-01 / DL-Q1).

        It is ``eligible`` - the point-in-time members that have cleared the listing-age
        filter - because ranking a symbol the loop could not hold, or one the membership
        table says was not in the universe, is exactly the mismatch this contract closes.
        Live, the same set arrives as ``reference_symbols`` from the engine's managed
        universe, which the pool builds under the identical hysteresis rule (D-013/D-014).
        """
        return self.eligible(panel, membership)

    def strategy_scores(self, panel: Panel, reference: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
        """Raw scores.  ``reference`` names the population every cross-sectional operator uses."""
        scored = panel if reference is None else panel.with_reference(reference)
        return {entry.id: get_signal(entry.id).compute(scored, entry.params) for entry in self.entries}

    def strategy_targets(
        self, panel: Panel, membership: pd.DataFrame | None = None, previous: PreviousTargets | None = None
    ) -> dict[str, pd.DataFrame]:
        """Per-strategy held targets; ``previous`` seeds NO_ACTION with what the live loop held last cycle.

        The eligible set does two jobs and they are deliberately distinct: it is the
        cross-sectional population the signals rank over (P1-01, applied *before* they
        compute), and it is the mask that turns leaving the universe into an explicit
        exit (applied after).  Before the first job existed, the population was whatever
        symbols the caller had loaded.

        The panel must carry funding whenever an enabled signal reads it - the refusal ``targets`` makes
        for the live path (KILL-027), made here because research is where evidence is produced.  Without
        it ``starquant research backtest --strategy tsmom --no-funding`` exited 0 and wrote a report whose
        ``params`` cited ``crowding_window: 72`` for a modifier that had consumed nothing (E-040).
        The guard sits on this method rather than on ``evaluate`` because it is the one seam every caller
        crosses: ``decompose_book`` reaches the signals through here without ever calling ``evaluate``.

        It asks ``settled_symbols``, not ``funding is None``.  The first draft asked the latter, which
        answers "was funding requested" rather than "did any arrive": ``--funding`` is the CLI default,
        and against an unsynced archive the panel carries a frame of zeros that satisfies an ``is None``
        test while the modifier reads nothing.  That was fixed in the CLI first and left asymmetric here,
        which put ``research book``'s robustness panels and every direct library caller - including the
        scratchpad script the registry cites as corroboration - back on the weaker test.
        """
        if self.needs_funding and panel.settled_symbols == 0:
            raise FundingUnavailable(
                "an enabled signal reads funding history but the panel carries no settlement for any "
                "symbol; the signal would run on inputs it did not have when it was judged (E-040 / KILL-027)"
            )
        eligible = self.eligible(panel, membership)
        targets: dict[str, pd.DataFrame] = {}
        # By id, not by position.  `strategy_scores` builds its dict in this same order, so zipping the
        # values against `self.entries` was right - until two entries share an id, at which point the
        # dict collapses by one and the loop pairs every later entry with the wrong frame.  `strict=True`
        # turns that into a length error, which is a true statement about the zip and says nothing about
        # the duplicate that caused it.  `parse_registry` refuses duplicates at the door and names the
        # id; this is the second lock, for a model built any other way.
        scored = self.strategy_scores(panel, eligible)
        for entry in self.entries:
            scores = scored[entry.id]
            seed = self._seed(previous, entry)
            held = scores_to_targets(
                scores.where(eligible), entry.entry_threshold, hold=self.hold_on_no_action, initial=seed
            )
            if membership is not None:  # leaving the universe is an explicit exit, never a held position
                held = held.mask(~eligible & held.notna(), 0.0)
            targets[entry.id] = held
        return targets

    @staticmethod
    def _seed(previous: PreviousTargets | None, entry: StrategyEntry) -> dict[str, float] | None:
        """The targets ``entry`` held at the end of the previous live cycle (unscaled per-strategy targets)."""
        if previous is None:
            return None
        recorded = previous.get(entry.id)
        if not recorded:
            return None
        return {str(symbol): float(value) for symbol, value in recorded.items() if value is not None}

    def book_targets(self, per_strategy: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Per-book conviction: the ensemble of that book's strategies."""
        return {
            book: combine_targets(
                {entry.id: per_strategy[entry.id] for entry in self.entries_of(book)},
                {entry.id: entry.weight for entry in self.entries_of(book)},
                method=self.ensemble_method,
            )
            for book in self.book_names
        }

    def combined_targets(self, panel: Panel, targets: Mapping[str, pd.DataFrame] | None = None) -> pd.DataFrame:
        """Conviction of the main book (or of the only book when the main one is absent)."""
        per_strategy = dict(targets) if targets is not None else self.strategy_targets(panel)
        return self.book_targets(per_strategy)[self.book_names[0]]

    def book_weights(
        self, per_strategy: Mapping[str, pd.DataFrame], close: pd.DataFrame, bars_per_year: float
    ) -> dict[str, pd.DataFrame]:
        """Each book vol-targeted on its own (no band), gross-capped if it is a sleeve, then scaled by its fraction.

        The cap (P30) belongs here rather than inside ``build_weights`` because ``build_weights`` is
        book-agnostic - it does not know whether what it is sizing is the main book - and the rule is
        about which book this is.  Order is load-bearing and pre-registered: cap, then fraction.  The
        other order is a different book, and one in which the two knobs stop being separable.
        """
        bare = replace(self.portfolio, no_trade_band=0.0, no_trade_rel_band=0.0)
        return {
            book: cap_gross(
                build_weights(conviction, close, bars_per_year, bare),
                0.0 if book == MAIN_BOOK else self.portfolio.sleeve_max_gross,
            )
            * self.fraction(book)
            for book, conviction in self.book_targets(per_strategy).items()
        }

    def weights_from(
        self,
        per_strategy: Mapping[str, pd.DataFrame],
        close: pd.DataFrame,
        bars_per_year: float,
        *,
        band: bool = True,
    ) -> pd.DataFrame:
        """``band=False`` returns the weights the book actually wants, with no no-trade band applied (D-033).

        The band's rule is "keep the previous weight unless the change is big enough", and the two
        halves of the system disagree about what *previous* means.  In a backtest the model's own
        output is the position, so ``apply_no_trade_band`` is the position recursion and belongs
        here.  Live, the position is the venue's, and ``plan_rebalance`` applies the identical rule
        against it - so applying the band here as well suppresses the change twice, against a
        reference that is not the book.  Worse, the live path rebuilds this path-dependent recursion
        from scratch over a request window that slides by one bar every cycle, so the latch point is
        an artefact of the window: measured on the shipped book, 1,442 bars against 1,443 moved one
        symbol's weight by 14% of itself, and the model layer carried 20% more turnover over 200
        bars than the continuous path the evidence was measured on.
        """
        portfolio = self.portfolio if band else replace(self.portfolio, no_trade_band=0.0, no_trade_rel_band=0.0)
        if self.book_names == (MAIN_BOOK,):
            return build_weights(self.book_targets(per_strategy)[MAIN_BOOK], close, bars_per_year, portfolio)
        return combine_books(self.book_weights(per_strategy, close, bars_per_year), portfolio)

    def weights(self, panel: Panel, membership: pd.DataFrame | None = None) -> pd.DataFrame:
        return self.weights_from(self.strategy_targets(panel, membership), panel.close, panel.bars_per_year)

    def evaluate(
        self,
        panel: Panel,
        membership: pd.DataFrame | None = None,
        previous: PreviousTargets | None = None,
        *,
        band: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
        per_strategy = self.strategy_targets(panel, membership, previous)
        combined = self.combined_targets(panel, per_strategy)
        weights = self.weights_from(per_strategy, panel.close, panel.bars_per_year, band=band)
        return weights, combined, per_strategy

    def targets(
        self,
        bars: Mapping[str, pd.DataFrame],
        funding: Mapping[str, float],
        previous: PreviousTargets | None = None,
        funding_history: Mapping[str, pd.Series] | pd.DataFrame | None = None,
        reference_symbols: Iterable[str] | None = None,
    ) -> TargetWeights:
        """Live entry point: closed bars per symbol -> latest target weights.

        Contributions are unscaled per-strategy targets (the hold seed of the next cycle); a
        book's fraction reaches attribution through ``LiveConfig.strategy_weights`` (D-019).
        ``previous`` is the last cycle's contributions: a sub-threshold score keeps the held
        target (D-005) even when the sub-threshold stretch is longer than the request window,
        exactly as in a full-history backtest (E-042).  ``funding`` (latest rate per symbol) is
        accepted for the port's sake and unused; ``funding_history`` (settled rates per symbol,
        indexed by settlement time) becomes ``panel.funding`` exactly as ``load_panel`` builds
        it for research, and is mandatory whenever an enabled signal reads it (KILL-027).

        ``reference_symbols`` is the cross-sectional population (P1-01 / DL-Q1): the universe the
        loop manages this cycle.  Research derives the same set from the point-in-time membership,
        so the two paths rank a symbol against the same names.  Passing ``None`` keeps the old
        behaviour - the population is every symbol in ``bars`` - which is what the offline
        reproduction does when it has no universe of its own to declare.

        The weights are *unbanded* (D-033): live, the no-trade band is the rebalancer's, applied
        against the venue's real position, which is the reference a backtest's band already has.
        """
        if self.needs_funding and funding_history is None:
            raise ValueError(
                "an enabled signal reads funding history but none was supplied; the live path would trade "
                "an unvalidated configuration (KILL-027)"
            )
        panel = Panel.from_frames(bars, interval=self.interval, funding=funding_history)
        if len(panel.index) < self.warmup_bars:
            raise ValueError(f"need at least {self.warmup_bars} closed bars, got {len(panel.index)}")
        membership = None
        if reference_symbols is not None:
            named = [symbol for symbol in reference_symbols if symbol in panel.close.columns]
            membership = pd.DataFrame(False, index=panel.index, columns=panel.close.columns)
            membership[named] = True
        weights, combined, per_strategy = self.evaluate(panel, membership, previous=previous, band=False)
        # The same panel and the same params the weights were just built from, so the recorded
        # divisor cannot describe a different bar than the weight it explains.  `book_weights` is
        # recomputed rather than returned by `evaluate` deliberately: `evaluate` is the BACKTEST's hot
        # loop and this is the live entry point, so the cost lands where there is one call an hour.
        # It is the same pure function `weights_from` sums, so `combine_books` of these IS `weights` -
        # asserted in `test_recording_the_book_weights_changes_no_weight`, which is falsifier F1 of
        # the 2026-09-12 pre-registration: an observability field that moved a traded weight would not
        # be observability.
        # The two readings the construction could not make about itself, taken on the same panel and
        # the same params the weights were just built from - the rule `asset_vol` is here for.  Both
        # are observability: `test_recording_the_book_weights_changes_no_weight` is the falsifier that
        # an observability field which moved a traded weight would not be observability, and these are
        # computed from `weights` after the fact rather than inside the path that produces it.
        returns = panel.close.pct_change()
        book_vol = ewma_portfolio_vol(returns, weights, self.portfolio.covariance_halflife, panel.bars_per_year)
        clipped = clipped_risk_share(
            vol_targeted(combined, panel.close, panel.bars_per_year, self.portfolio), self.portfolio
        )
        return snapshot(
            weights,
            combined,
            per_strategy,
            asset_vol(panel.close, self.portfolio, panel.bars_per_year).iloc[-1],
            self.book_weights(per_strategy, panel.close, panel.bars_per_year),
            portfolio_vol=_last_finite(book_vol),
            clipped_risk_share=_last_finite(clipped),
        )
