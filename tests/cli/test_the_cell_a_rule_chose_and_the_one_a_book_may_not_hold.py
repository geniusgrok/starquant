"""Two layer-0 items with one shape: a choice that was being made without anyone naming it.

**`--select`** (round 7's副产品 1).  `validate` picks `best_params` by full-sample Sharpe, and the
registry's startup gate compares the running params against that field.  So a candidate that wins on
a PRE-REGISTERED rule but is a shade lower on the full sample can never be a grid report's
`best_params`: H-001's rule was "OOS >= baseline - 0.05 AND drawdown improves AND turnover falls",
the sign arm won it and lost the argmax, and adopting it took a second single-configuration report
(`tsmom-validation-20260904T020459Z`).  Naming the cell is the cheaper half.  What keeps the naming
honest is that `--select` requires `--prereg` - a commit whose timestamp lands in the artefact - and
that the argmax is recorded beside it whichever rule won.

**The ensemble guard.**  `combine_targets` takes a weighted MEAN of a book's per-strategy targets and
`build_weights` sizes on that number, so two strategies at +1 and -1 produce 0 (a close) and three at
+1/+1/-1 produce a third of a position.  That is the magnitude back in a book whose
`conviction_mode: sign` was adopted on D-024's measurement that magnitude carries no return
information.  The combination has never been scored.  Today the refusal is unreachable - both books
run one strategy - which is exactly when it is worth writing: the day a second one is added is the
day it should be a decision rather than a side effect of an `enabled: true`.
"""

from __future__ import annotations

import json

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import BookSpec, Registry, StrategyEntry
from starquant_cli.research_cmd import _selected_key

GRID = {
    "a": {"crowding_window": 0, "entry_threshold": 0.2},
    "b": {"crowding_window": 72, "entry_threshold": 0.2},
    "c": {"crowding_window": 72, "entry_threshold": 0.3},
}


def test_no_selection_leaves_the_argmax_in_charge() -> None:
    assert _selected_key("", GRID, "") is None


def test_naming_a_cell_without_saying_which_rule_is_refused() -> None:
    """The safeguard is the whole feature: a name with no pre-registration is just a later argmax."""
    with pytest.raises(Exception, match="--prereg"):
        _selected_key('{"crowding_window": 0}', GRID, "")


def test_one_cell_named_by_a_rule_that_predates_the_run() -> None:
    assert _selected_key('{"crowding_window": 0}', GRID, "HEAD") == "a"
    assert _selected_key('{"crowding_window": 72, "entry_threshold": 0.3}', GRID, "HEAD") == "c"


def test_a_selector_that_matches_two_cells_is_refused_rather_than_resolved() -> None:
    """Picking one of several here would be the choice the pre-registration is supposed to have made."""
    with pytest.raises(Exception, match="matches 2 of this run's 3 cells"):
        _selected_key('{"crowding_window": 72}', GRID, "HEAD")
    with pytest.raises(Exception, match="matches 0 of"):
        _selected_key('{"crowding_window": 999}', GRID, "HEAD")


def _registry(books: dict[str, str]) -> Registry:
    """`books` maps a strategy id to the book it belongs to."""
    return Registry(
        version=1,
        ensemble_method="mean",
        turnover_penalty=0.0,
        strategies=tuple(StrategyEntry(id=name, enabled=True, book=book) for name, book in books.items()),
        books={name: BookSpec(name=name, fraction=0.5) for name in set(books.values()) if name != "main"},
    )


def test_one_strategy_per_book_is_what_ships_and_it_builds() -> None:
    model = AlphaModel.from_registry(_registry({"tsmom": "main", "flow": "flow_short"}), PortfolioParams(), "1h")
    assert model.book_names == ("main", "flow_short")


def test_a_second_strategy_in_one_book_is_refused_with_the_arithmetic_that_makes_it_a_decision() -> None:
    with pytest.raises(ValueError, match="more than one strategy"):
        AlphaModel.from_registry(_registry({"tsmom": "main", "xsmom": "main"}), PortfolioParams(), "1h")


def test_the_refusal_names_every_crowded_book_not_only_the_first() -> None:
    crowded = _registry({"a": "main", "b": "main", "c": "probe", "d": "probe"})
    with pytest.raises(ValueError) as caught:
        AlphaModel.from_registry(crowded, PortfolioParams(), "1h")
    assert "'main'" in str(caught.value) and "'probe'" in str(caught.value)


def test_research_can_still_build_the_combination_it_would_have_to_measure() -> None:
    """Refused at the live seam only: measuring the ensemble is how it would ever earn its way in."""
    model = AlphaModel(
        entries=(StrategyEntry(id="tsmom"), StrategyEntry(id="xsmom")), portfolio=PortfolioParams(), interval="1h"
    )
    assert model.book_names == ("main",)


def test_the_shipped_registry_is_on_the_allowed_side() -> None:
    from starquant_live.composition import load_registry

    registry = load_registry("config/alpha_registry.yaml")
    per_book = {book: sum(1 for e in registry.enabled if e.book == book) for e in registry.enabled for book in [e.book]}
    assert max(per_book.values()) == 1, per_book
    assert json.dumps(sorted(per_book)) == json.dumps(["flow_short", "main"])
