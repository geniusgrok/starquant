"""A book of several books is banded by the same rule as a book of one: every knob, not the ones that arrived first.

`apply_no_trade_band` takes the band's knobs one argument at a time, and it had three callers:
`build_weights` (one book), `combine_books` (the sum of several) and `research book`'s `banded()`.  D2
`flat_inside_band` (2026-09-15, `ad70e81a`) reached the first two.  D3 `band_entry_multiple`
(2026-09-17, `b361f553`) reached only `build_weights`.  From 2026-09-17 every multi-book research
reading - `research overlay` on the registry, `research book`'s combined arm, `p32d.panel_series` and
the k sweep built on it - banded with D2 and without D3.  That is a construction which never traded:
the profile turned D1, D2 and D3 on in one commit (PR #53).  The live loop was never affected - it asks
the model for `band=False`, and the rebalancer, which carries D3, bands against the venue's position.

Nothing caught it, because the one two-book band test (`test_books.py`) compares `combine_books` with
itself at the default knobs, where D2 is off and D3 is 1.0.  This file writes the rule out instead and
holds both paths to it, at knobs where D3 has something to bite.
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, apply_no_trade_band
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams
from tests.alpha.test_causality import _bit_for_bit

# The two books `test_shuffling_the_future_moves_no_weight_before_it.py` runs on this fixture, at the
# live sleeve's fraction.
TSMOM = {
    **asdict(TsmomParams(vol_window=100)),
    "horizons": [5, 20, 50],
    "horizon_weights": [0.2, 0.3, 0.5],
    "conviction_mode": "sign",
}
BREAKOUT = {**asdict(BreakoutParams()), "entry_threshold": 0.05}
MAIN = StrategyEntry("tsmom", params=TSMOM)
SLEEVE = StrategyEntry("breakout", params=BREAKOUT, book="sleeve")
SLEEVE_FRACTION = 0.333333

#: The shipped band knobs - D2 on, D3 2.0, the relative arm 0.40 - written out rather than read from the
#: profile, because what is under test is that each knob REACHES each path, whatever the operator sets
#: it to.  Two numbers are moved so that D3 has something to bite.  `vol_target` 0.60 -> 0.10: at 0.60
#: every August weight sits on `max_weight`.  `no_trade_band` 0.005 -> 0.02, measured 2026-09-23: at 0.02
#: D3 moves 420 cells of the two-book book and 274 of the one-book book; at the shipped 0.005 it still
#: moves 15 of the two-book book and none of the one-book book, because it is the sleeve's third that puts
#: weights inside twice the band.  Fifteen cells is too thin a margin to hold a test on.
PARAMS = PortfolioParams(
    vol_target=0.10,
    no_trade_band=0.02,
    no_trade_rel_band=0.40,
    flat_inside_band=True,
    band_entry_multiple=2.0,
)

ONE_BOOK = AlphaModel(entries=(MAIN,), portfolio=PARAMS, interval="1h", min_history_bars=0)
TWO_BOOKS = AlphaModel(
    entries=(MAIN, SLEEVE),
    portfolio=PARAMS,
    interval="1h",
    min_history_bars=0,
    books={"sleeve": SLEEVE_FRACTION},
)


def _moved(left: pd.DataFrame, right: pd.DataFrame) -> int:
    return int((left.fillna(0.0).to_numpy() != right.fillna(0.0).to_numpy()).sum())


@pytest.mark.parametrize("model", [ONE_BOOK, TWO_BOOKS], ids=["one_book", "two_books"])
def test_the_band_applies_every_knob_the_params_carry(august_panel: Panel, model: AlphaModel) -> None:
    """`weights_from` with the band equals the rule, with every knob, applied to `weights_from` without it."""
    per_strategy = model.strategy_targets(august_panel)
    close, bars_per_year = august_panel.close, august_panel.bars_per_year
    unbanded = model.weights_from(per_strategy, close, bars_per_year, band=False)
    rule = apply_no_trade_band(
        unbanded,
        PARAMS.no_trade_band,
        PARAMS.no_trade_rel_band,
        PARAMS.flat_inside_band,
        PARAMS.band_entry_multiple,
    )
    # Not vacuous: D3 binds on this book, so a path that dropped it could not pass by coincidence.
    without_d3 = apply_no_trade_band(unbanded, PARAMS.no_trade_band, PARAMS.no_trade_rel_band, True, 1.0)
    assert _moved(rule, without_d3) > 0, "D3 never binds here; the comparison below could not see it missing"
    _bit_for_bit(model.weights_from(per_strategy, close, bars_per_year), rule)
