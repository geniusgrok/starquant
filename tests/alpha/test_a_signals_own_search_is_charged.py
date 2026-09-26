"""DL-K2 one level down: a signal that chooses WHICH combinations to trade has made a selection.

`research mine` charges every candidate its search kept, because "a search that costs nothing is a DSR
denominator wrong in the one direction that flatters it".  The same hole was open inside `pairs`: the
refit loop looks at every pair its formation window can form and keeps a handful, and the report that
shipped on 2026-09-08 recorded `n_trials: 4` - the four cells of its parameter grid - for a run that had
examined 19,578 distinct pairs of the 20,910 the panel could form.

What is asserted here is the shape of the accounting, not that number: the census counts the search the
SCORES came from (a census with its own copy of the eligibility rule would drift silently, and only ever
in the direction that under-charges), it deduplicates a candidate re-examined at the next refit, and any
signal that declares a census is routed to a shared ledger bucket rather than to its own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_alpha.signals import SIGNALS
from starquant_alpha.signals.pairs import PairsParams, pairs_scores, search_census
from starquant_alpha.validation.ledger import PAIR_SEARCH_STRATEGY, ledger_scope

SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")
DEFAULTS = PairsParams().__dict__


def _panel(n_bars: int = 2_400, seed: int = 5, coupling: float = 0.9, frozen: str = "") -> Panel:
    """The coupled panel of the P28 tests; ``frozen`` pins one symbol's price so it never moves."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    common = rng.normal(0, 0.01, n_bars)
    steps = rng.normal(0, 0.01, size=(n_bars, len(SYMBOLS)))
    steps[:, 0] = coupling * common + (1 - coupling) * steps[:, 0]
    steps[:, 1] = coupling * common + (1 - coupling) * steps[:, 1]
    frames = {}
    for j, symbol in enumerate(SYMBOLS):
        close = 100.0 * np.exp(np.cumsum(steps[:, j]))
        if symbol == frozen:
            close = np.full(n_bars, 100.0)
        frames[symbol] = pd.DataFrame(
            {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1_000.0},
            index=index,
        )
    return Panel.from_frames(frames, "1h")


def test_the_census_counts_every_pair_the_window_could_form_not_the_ones_it_kept() -> None:
    """The number that was free.  Four symbols is six hypotheses; the run traded one of them."""
    census = search_census(_panel(), DEFAULTS)

    assert set(census.candidates) == {f"{left}|{right}" for i, left in enumerate(SYMBOLS) for right in SYMBOLS[i + 1 :]}
    assert census.facts["distinct_pairs"] == 6
    assert census.facts["possible_pairs"] == 6
    assert len(census.selected) < len(census.candidates), "a search that keeps everything selected nothing"


def test_the_same_pair_at_the_next_refit_is_one_hypothesis_not_two() -> None:
    """DL-K2's rule, which is why `mine` rows carry no `search_space_version` either.

    Three refits over this panel look at the same six pairs eighteen times.  Charging pair-windows
    would put 18 in the denominator for six hypotheses - inflating N in the direction that looks
    rigorous and is simply wrong.
    """
    census = search_census(_panel(), DEFAULTS)

    assert census.facts["refits"] == 3
    assert census.facts["pairs_per_refit"]["sum"] == 18
    assert len(census.candidates) == 6 == len(set(census.candidates))


def test_the_census_walks_the_loop_that_trades_rather_than_a_copy_of_it() -> None:
    """The drift this is here to prevent: a census over its own idea of the search under-charges.

    Every symbol the scores ever trade must belong to a pair the census says was selected, and every
    selected pair must actually appear in the scores.  A refit loop that moved without the census
    moving fails here rather than in a report nobody can re-derive.
    """
    panel = _panel()
    census = search_census(panel, DEFAULTS)
    scores = pairs_scores(panel)

    traded = {str(column) for column in scores.columns[scores.notna().any().to_numpy()]}
    legs = {leg for candidate in census.selected for leg in candidate.split("|")}
    assert traded == legs
    for candidate in census.selected:
        left, right = candidate.split("|")
        both = scores[[left, right]].dropna()
        assert not both.empty, f"{candidate} was selected and never scored"


def test_a_column_that_never_moved_is_not_a_candidate() -> None:
    """`_examined` is one rule shared by the scores and the census, asserted through the census.

    A frozen column produces a NaN correlation row, is dropped before the argmax, and is not a pair
    candidate under any reading - so it must not be charged as one either.  Six pairs become three.
    """
    census = search_census(_panel(frozen="DDDUSDT"), DEFAULTS)

    assert all("DDDUSDT" not in candidate for candidate in census.candidates)
    assert census.facts["distinct_pairs"] == 3
    assert census.facts["possible_pairs"] == 6, "the panel could still form six; three were never looked at"


def test_a_panel_too_short_to_choose_a_partner_searched_nothing() -> None:
    """Zero, not an error and not a guess: `pairs_scores` returns all-NaN below the warmup."""
    census = search_census(_panel(n_bars=200), DEFAULTS)

    assert census.candidates == ()
    assert census.facts["refits"] == 0
    assert census.facts["symbols_per_refit"] == {"min": 0.0, "median": 0.0, "max": 0.0}
    assert pairs_scores(_panel(n_bars=200)).notna().to_numpy().sum() == 0


def test_a_wider_formation_window_searches_the_same_pairs_at_fewer_refits() -> None:
    """The census has to answer for the params it was given, not for the defaults."""
    narrow = search_census(_panel(), {**DEFAULTS, "formation_bars": 240, "refit_bars": 240})

    assert narrow.facts["refits"] > search_census(_panel(), DEFAULTS).facts["refits"]
    assert set(narrow.candidates) == set(search_census(_panel(), DEFAULTS).candidates)


def test_a_pair_is_the_same_hypothesis_whichever_order_the_panel_was_loaded_in() -> None:
    """The ledger folds on the key, so the key cannot carry the run's column order.

    Found by the CLI test: the id was built from column POSITIONS, which made `BTCUSDT|BNBUSDT` and
    `BNBUSDT|BTCUSDT` two rows for one pair the first time a universe was loaded in another order.
    """
    panel = _panel()
    reversed_panel = Panel.from_frames(
        {
            symbol: pd.DataFrame(
                {
                    field: getattr(panel, field)[symbol].to_numpy()
                    for field in ("open", "high", "low", "close", "volume")
                },
                index=panel.index,
            )
            for symbol in reversed(panel.symbols)
        },
        "1h",
    )

    assert search_census(reversed_panel, DEFAULTS).candidates == search_census(panel, DEFAULTS).candidates


@pytest.mark.parametrize("name", sorted(SIGNALS))
def test_a_signal_that_declares_a_search_names_the_bucket_it_is_charged_to(name: str) -> None:
    """The link that keeps the next pair-type candidate from being free.

    `ledger_scope` matches on the id so the ledger stays free of the signal registry, which means the
    two can disagree.  This is where they cannot: declare a census without a bucket, or register a
    searcher under an id `ledger_scope` does not route, and the search stops reaching the denominator.
    """
    spec = SIGNALS[name]

    assert bool(spec.selection) == bool(spec.selection_bucket), "a census without a bucket is charged nowhere"
    if spec.selection_bucket:
        assert spec.selection_bucket in ledger_scope(spec.id)
        assert spec.selection_bucket != spec.id, "a search shared with the next formalisation needs its own key"


def test_pairs_is_the_only_signal_searching_so_far_and_it_is_charged_to_the_shared_bucket() -> None:
    """Recorded so that adding the second one is a deliberate act with a test to update."""
    searchers = {name for name, spec in SIGNALS.items() if spec.selection is not None}

    assert searchers == {"pairs"}
    assert SIGNALS["pairs"].selection_bucket == PAIR_SEARCH_STRATEGY
    assert ledger_scope("pairs") == ("pairs", PAIR_SEARCH_STRATEGY)
