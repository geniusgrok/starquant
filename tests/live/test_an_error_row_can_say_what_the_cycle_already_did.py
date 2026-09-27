"""L3's gate asks a question the engine could not write an answer to.

`soak.passes` - the thing `starquant live soak --check` exits non-zero on - is
`no_decision_pass and streak_pass`, and `no_decision_pass` asks whether any ERROR cycle DECIDED
anything.  `soak._decided` looks for five keys: orders, leaving, quarantined, universe_update,
risk_ladder.

The ERROR row `guarded_cycle` writes is a fresh dict built in the exception handler.  It carried none
of the last four and hardcoded `"orders": []`.  So `deciding_errors` was always empty on an
engine-produced record and the gate degenerated to `long_enough and streak_pass`: the no-decision half
could not fail, whatever the loop had done.

The scenario it exists to catch is reachable and ordinary.  `run_cycle` executes orders, and only
THEN runs `_quarantine`, `_summarize` and `_finish_cycle`.  A raise in any of those three leaves
orders on the venue and writes a row that says the cycle placed none.  The fills are in
`trades.jsonl`; it is the cycle row - the one soak reads - that lost them.

`tests/live/test_l3s_criterion_is_ruled.py` asserts the gate works by hand-building
`_cycle(..., "ERROR", orders=[...])`, a row shape `guarded_cycle` could not emit.  The test passed;
the composition was wrong.  That is the seam being placed where the test is convenient rather than
where the domain is, so these tests drive the record from the ENGINE and read it with `soak.score`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams
from starquant_live.soak import DECISION_KEYS, _decided, score
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


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


def _prices(panel: Panel, position: int) -> dict[str, float]:
    return {symbol: float(panel.close[symbol].iloc[position - 1]) for symbol in SYMBOLS}


@pytest.fixture
def world(august_panel: Panel, tmp_path: Path) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    config = LiveConfig(  # type: ignore[arg-type]
        interval="1h",
        history_bars=300,
        universe=tuple(SYMBOLS),
        leverage=2,
        rebalance=RebalanceParams(no_trade_band=0.002),
        guards=GuardParams(),
        kill_switch_path=tmp_path / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
    )
    engine = LiveEngine(config, model=_model(), market=market, venue=venue, clock=clock, store=store)
    return {"engine": engine, "venue": venue, "store": store, "bar": market.bar_open_ms(cursor - 1)}


def _error_rows(store: StateStore) -> list[dict[str, Any]]:
    return [row for row in store.read_jsonl(store.cycles_path) if row.get("phase") == "ERROR"]


async def test_the_error_row_carries_the_orders_the_cycle_had_already_placed(world: dict[str, Any]) -> None:
    """`_quarantine` raising after `_execute_orders` is the exact shape KILL-AR-20 is about."""
    engine, venue, store = world["engine"], world["venue"], world["store"]
    await engine.startup()

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("venue went away between the fills and the quarantine sweep")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    assert venue.order_log, "precondition: the cycle really did place orders before it blew up"
    rows = _error_rows(store)
    assert len(rows) == 1
    assert rows[0]["orders"], "the row said the cycle placed nothing while the fills sit in trades.jsonl"


async def test_soak_sees_that_error_cycle_as_one_that_decided_something(world: dict[str, Any]) -> None:
    """The end-to-end statement: the gate can now fail on an engine-produced record."""
    engine, store = world["engine"], world["store"]
    await engine.startup()

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("venue went away between the fills and the quarantine sweep")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    reading = score(store.read_jsonl(store.cycles_path))

    assert reading.deciding_errors, "an ERROR cycle that placed orders must be visible to L3"
    assert reading.no_decision_pass is False
    assert reading.passes is False


async def test_a_clean_error_row_still_decides_nothing(world: dict[str, Any]) -> None:
    """The other half: a cycle that fails BEFORE deciding must stay invisible to the gate (KILL-AR-20).

    A venue returning 503 before anything is placed is the loop declining to act on bad data, which is
    the loop working.  If this ever fails, the fix has over-reached and every outage now retires a book.
    """
    engine, store = world["engine"], world["store"]
    await engine.startup()

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("venue unreachable")

    engine.venue.account = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    rows = _error_rows(store)
    assert len(rows) == 1
    reading = score(store.read_jsonl(store.cycles_path))
    assert not reading.deciding_errors, "nothing was decided, so L3 must not see a decision"


async def test_every_decision_key_is_writable_on_the_error_path(world: dict[str, Any]) -> None:
    """The contract, stated once.

    `_decided` reads five keys off a row that a different method 1,000 lines away produces.  This is
    the join: if someone adds a sixth key to DECISION_KEYS, or renames one, the ERROR path has to be
    able to carry it or this fails.
    """
    engine, store = world["engine"], world["store"]
    await engine.startup()

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("fails after the decisions are taken")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    row = _error_rows(store)[0]
    missing = [key for key in DECISION_KEYS if key not in row]
    assert not missing, f"the ERROR row cannot express {missing}, so L3 cannot fail on them"


async def test_a_computed_ladder_reading_is_not_a_decision(world: dict[str, Any]) -> None:
    """The over-reach this fix could have caused, pinned so it cannot come back.

    Carrying `risk_ladder` onto the ERROR row would otherwise make EVERY failed cycle look like a
    decision: `_risk_ladder` returns ten keys on the quietest cycle and is never `{}`, so an emptiness
    test reads "the ladder was computed" as "the ladder acted".  That is KILL-AR-20 inverted - the loop
    measuring itself would retire a book - so the predicate asks `acting`.
    """
    engine, store = world["engine"], world["store"]
    await engine.startup()

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("fails after the ladder has been read")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    row = _error_rows(store)[0]
    ladder = row["risk_ladder"]
    assert isinstance(ladder, dict) and ladder, "precondition: the reading really is a populated block"
    assert ladder.get("acting") is False
    assert "risk_ladder" not in _decided(row), "a reading is not an action"


def test_a_recorded_but_unadopted_universe_proposal_is_not_a_decision() -> None:
    """Under a pinned universe the loop writes a proposal once a day and deliberately does not take it."""
    recorded = {"proposal": ["BTCUSDT"], "entering": [], "leaving": [], "universe": ["ETHUSDT"], "adopted": False}

    assert not _decided({"phase": "ERROR", "universe_update": recorded})


def test_a_failed_refresh_that_kept_the_pool_is_not_a_decision() -> None:
    """T-P05: the refresh raised and the loop kept the previous pool.  The traded set did not move."""
    kept = {"error": "TimeoutError: venue", "universe": ["BTCUSDT", "ETHUSDT"]}

    assert not _decided({"phase": "ERROR", "universe_update": kept})


def test_an_adopted_refresh_is_a_decision() -> None:
    """And the half that must still fire: the traded set actually changed."""
    adopted = {"symbols": ["BTCUSDT"], "entered": ["BTCUSDT"], "left": ["ETHUSDT"], "day": "2026-09-14"}

    assert _decided({"phase": "ERROR", "universe_update": adopted}) == ("universe_update",)
