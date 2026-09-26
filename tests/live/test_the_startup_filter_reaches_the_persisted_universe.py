"""The startup filter is a mutation of the managed set, so it has to reach disk like the other three.

`startup` drops symbols the venue will not trade (`engine.py`, right after `venue.rules()`), and every
OTHER mutation of `self.universe` pairs the in-process list with `self.state.universe`: `__init__` when
the profile pins a universe, `_quarantine` on D-031's exit, `_maybe_refresh_universe` on D-014's daily
refresh.  This one did not, and `store.save(self.state)` at the end of `startup` then persisted the
UNFILTERED list.

Why that matters rather than being untidy.  `starquant live verify` (M-011, D-023) reads only
`state.universe` - for the fetch list and for `reference_symbols`.  D-042 rules that the reference
population is an explicit contract, so a reproduction that ranks and demeans over a strictly larger
population than the cycle did moves EVERY cross-sectional contribution, not one symbol's.  M-011 goes
red with nothing in the record able to say why: that is KILL-027's shape one layer down.

It does not self-heal under the shipped profile: a pinned universe makes `_maybe_refresh_universe`
return before it touches `state.universe`, so only a restart with every pinned symbol tradable clears
it.  And `engine.py`'s own `logger.warning("dropping non-tradable symbols...")` exists because the
author expects the dropped list to be non-empty - a pinned symbol going SETTLING or BREAK.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams
from starquant_live.state import StateStore
from tests.fakes.fake_venue import DEFAULT_RULES, FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
SETTLING = "BNBUSDT"


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )


def _config(tmp_path: Path, *, pinned: bool) -> LiveConfig:
    return LiveConfig(  # type: ignore[arg-type]
        interval="1h",
        history_bars=300,
        universe=tuple(SYMBOLS),
        universe_pinned=pinned,
        leverage=2,
        rebalance=RebalanceParams(no_trade_band=0.002),
        guards=GuardParams(),
        kill_switch_path=tmp_path / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
    )


def _engine(august_panel: Panel, tmp_path: Path, *, pinned: bool) -> tuple[LiveEngine, StateStore]:
    cursor = 400
    rules = dict(DEFAULT_RULES) | {SETTLING: replace(DEFAULT_RULES[SETTLING], status="SETTLING")}
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, rules=rules)
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(
        _config(tmp_path, pinned=pinned), model=_model(), market=market, venue=venue, clock=clock, store=store
    )
    return engine, store


@pytest.fixture
def engine_with_a_settling_symbol(august_panel: Panel, tmp_path: Path) -> tuple[LiveEngine, StateStore]:
    """One of the four symbols is mid-settlement, so `startup` will drop it."""
    return _engine(august_panel, tmp_path, pinned=False)


@pytest.fixture
def pinned_engine_with_a_settling_symbol(august_panel: Panel, tmp_path: Path) -> tuple[LiveEngine, StateStore]:
    """The shipped shape: `alpha_registry.yaml` pins the universe, so `__init__` writes it to state."""
    return _engine(august_panel, tmp_path, pinned=True)


async def test_the_dropped_symbol_leaves_the_in_process_universe(
    engine_with_a_settling_symbol: tuple[LiveEngine, StateStore],
) -> None:
    """The half that already worked."""
    engine, _ = engine_with_a_settling_symbol

    await engine.startup()

    assert SETTLING not in engine.universe
    assert sorted(engine.universe) == sorted(s for s in SYMBOLS if s != SETTLING)


async def test_the_dropped_symbol_leaves_the_persisted_universe_too(
    engine_with_a_settling_symbol: tuple[LiveEngine, StateStore],
) -> None:
    """The half that did not: `store.save` inside `startup` wrote the list from before the filter."""
    engine, store = engine_with_a_settling_symbol

    await engine.startup()

    reloaded = store.load()
    assert SETTLING not in reloaded.universe, (
        "`live verify` reads state.universe and would rank over a population the cycle never scored"
    )
    assert sorted(reloaded.universe) == sorted(engine.universe)


async def test_the_two_universes_agree_after_startup(
    engine_with_a_settling_symbol: tuple[LiveEngine, StateStore],
) -> None:
    """The invariant the other three mutation sites keep, stated once so a fourth site cannot skip it."""
    engine, store = engine_with_a_settling_symbol

    await engine.startup()

    assert list(engine.state.universe) == list(engine.universe)
    assert list(store.load().universe) == list(engine.universe)


async def test_a_pinned_universe_does_not_persist_the_symbol_it_just_dropped(
    pinned_engine_with_a_settling_symbol: tuple[LiveEngine, StateStore],
) -> None:
    """The shipped shape, and the one that cannot self-heal.

    `__init__` writes the pinned list to `state.universe` BEFORE the venue is reachable, so the
    unfiltered name is on disk from the first line.  `_maybe_refresh_universe` then returns early for a
    pinned universe without touching `state.universe`, so nothing later corrects it: the stale name
    survives every cycle until a restart finds it tradable again.
    """
    engine, store = pinned_engine_with_a_settling_symbol
    assert SETTLING in engine.state.universe, "precondition: __init__ wrote the pinned list, unfiltered"

    await engine.startup()

    assert SETTLING not in engine.state.universe
    assert SETTLING not in store.load().universe
    assert list(store.load().universe) == list(engine.universe)
