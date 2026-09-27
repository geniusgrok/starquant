"""P1-01 / DL-Q1, part two: research and live must hand the model the SAME population.

Part one (``test_reference_population.py``) gave the cross-sectional operators an
explicit population.  A contract nothing passes is decoration, so this file pins
the two callers:

* research passes the point-in-time membership (intersected with the listing-age
  filter) - the names that were tradable on that bar;
* the live loop passes the universe it manages that cycle.

The existing KILL-027 guard could not see any of this: it feeds both paths the
*same* six-symbol panel, so a signal that silently ranks over extra columns looks
identical on both.  ``test_research_panel_wider_than_the_live_panel_agrees`` is
that test done properly - research gets 30 symbols and a membership mask, live
gets the 6 it manages, and the per-strategy contributions must still agree.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_live.composition import build_model, load_registry
from starquant_shared.config import load_yaml
from tests.alpha.test_round6_hold_and_warmup import _frames
from tests.alpha.test_signal_suite import _synthetic_panel

ROOT = Path(__file__).resolve().parents[2]
CROWDING = {
    "horizons": [24, 48, 72],
    "horizon_weights": [0.2, 0.3, 0.5],
    "crowding_window": 72,
    "crowding_cut": 0.7,
    "crowding_penalty": 0.5,
    "entry_threshold": 0.2,
}


def _model(**overrides: object) -> AlphaModel:
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=CROWDING),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=0,
        **overrides,  # type: ignore[arg-type]
    )


def _membership(panel: Panel, members: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(False, index=panel.index, columns=panel.close.columns)
    frame[members] = True
    return frame


def test_research_ranks_over_the_point_in_time_members_not_the_whole_panel() -> None:
    """The research half: a 12-symbol panel with a 5-name membership scores like a 5-symbol panel."""
    model = _model()
    wide = _synthetic_panel(seed=21, n_symbols=12, n_bars=900)
    members = wide.symbols[:5]

    referenced = model.strategy_targets(wide, _membership(wide, members))["tsmom"][members]
    isolated = model.strategy_targets(wide.select(members))["tsmom"]

    pd.testing.assert_frame_equal(referenced, isolated, check_names=False)


def test_live_targets_take_the_reference_from_the_managed_universe() -> None:
    """The live half: ``targets`` accepts the population explicitly instead of inferring it."""
    model = _model()
    panel = _synthetic_panel(seed=22, n_symbols=8, n_bars=900)
    members = panel.symbols[:4]
    frames = _frames(panel)

    everything = model.targets(frames, {}, funding_history=panel.funding)
    restricted = model.targets(frames, {}, funding_history=panel.funding, reference_symbols=members)

    assert restricted.contributions["tsmom"] != everything.contributions["tsmom"]
    only_members = model.targets(
        {symbol: frames[symbol] for symbol in members},
        {},
        funding_history=panel.funding[members],
        reference_symbols=members,
    )
    for symbol in members:
        assert restricted.contributions["tsmom"][symbol] == pytest.approx(
            only_members.contributions["tsmom"][symbol], abs=1e-12
        )


def test_research_panel_wider_than_the_live_panel_agrees() -> None:
    """The KILL-027 guard the old one could not be: research 30 symbols, live 6, same answers.

    ``test_shipped_registry_live_path_matches_research_path`` hands both paths the same
    panel, which is exactly the case P1-01 hides in.  Here research sees 30 names with a
    6-name membership mask and the loop sees only those 6 - the shape that actually runs.
    """
    registry = load_registry(ROOT / "config/alpha_registry.yaml")
    model = build_model(registry, load_yaml(ROOT / "config/live.demo.yaml"))
    model = AlphaModel(
        entries=model.entries,
        portfolio=model.portfolio,
        interval=model.interval,
        ensemble_method=model.ensemble_method,
        min_history_bars=0,
        books=model.books,
    )
    wide = _synthetic_panel(seed=23, n_symbols=30, n_bars=1600, with_funding=True)
    members = wide.symbols[:6]

    _weights, _combined, per_strategy = model.evaluate(wide, _membership(wide, members), band=False)
    live = model.targets(
        {symbol: _frames(wide)[symbol] for symbol in members},
        {},
        funding_history=wide.funding[members] if wide.funding is not None else None,
        reference_symbols=members,
    )

    for strategy, frame in per_strategy.items():
        expected = frame.iloc[-1].fillna(0.0)
        for symbol in members:
            assert live.contributions[strategy][symbol] == pytest.approx(float(expected[symbol]), abs=1e-9), (
                strategy,
                symbol,
            )


def test_reference_is_the_membership_intersected_with_tradability() -> None:
    """A name still inside its listing-age warmup is not part of the population either.

    ``eligible`` already gates trading on ``min_history_bars``; the population must use the
    same set, or research would rank a symbol the loop cannot hold.
    """
    model = AlphaModel(
        entries=(StrategyEntry("tsmom", params=CROWDING),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=200,
    )
    panel = _synthetic_panel(seed=24, n_symbols=6, n_bars=600)
    reference = model.reference_for(panel, _membership(panel, panel.symbols[:4]))

    # bar 198 is the 199th observation: one short of ``min_history_bars``
    assert not reference.iloc[198].any(), "nothing is tradable before the listing-age filter clears"
    assert reference.iloc[199][panel.symbols[:4]].all(), "the 200th observation clears it"
    assert reference.iloc[-1][panel.symbols[:4]].all()
    assert not reference.iloc[-1][panel.symbols[4:]].any()
