"""The cycle record's writers and its declaration, compared - which nothing could do before.

Three defects found in this package on 2026-09-14/15 were the same shape: one writer and one reader
disagreeing about a key of `cycles.jsonl`, with nowhere for the disagreement to surface.  The startup
filter that never reached `state.universe`; the ERROR row that carried none of L3's five decision keys;
`_decided` testing `risk_ladder` for emptiness when `_risk_ladder` never returns `{}`.

Forty-two keys, three writing methods, six reading modules, 192 distinct `.get()` names, and no
declaration anywhere.  `cycle_record.KEYS` is the declaration; this file is the join.

It runs the engine rather than asserting over a hand-built dict, because a hand-built row is exactly
what let `test_l3s_criterion_is_ruled` pass while the composition was wrong.
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
from starquant_live.cycle_record import KEYS, latest, undeclared
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams
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


@pytest.fixture
def world(august_panel: Panel, tmp_path: Path) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    prices = {s: float(august_panel.close[s].iloc[cursor - 1]) for s in SYMBOLS}
    venue = FakeVenue(balance=10_000.0, prices=prices)
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
    engine = LiveEngine(
        config,
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=store,
    )
    return {"engine": engine, "store": store, "bar": market.bar_open_ms(cursor - 1)}


async def test_a_normal_cycle_writes_nothing_undeclared(world: dict[str, Any]) -> None:
    """The direction that catches a new key nobody told the readers about."""
    engine, store = world["engine"], world["store"]
    await engine.startup()
    await engine.guarded_cycle(world["bar"])

    row = store.read_jsonl(store.cycles_path)[-1]

    assert not undeclared(row), (
        f"{undeclared(row)} is written into cycles.jsonl and described nowhere. "
        "Add it to cycle_record.KEYS so the six reading modules have something to read against."
    )


async def test_the_error_path_writes_nothing_undeclared(world: dict[str, Any]) -> None:
    """The ERROR row is built by a different method, so it gets its own side of the join."""
    engine, store = world["engine"], world["store"]
    await engine.startup()

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("after the decisions")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"])

    row = store.read_jsonl(store.cycles_path)[-1]
    assert row["phase"] == "ERROR"
    assert not undeclared(row), f"{undeclared(row)} written on the ERROR path and described nowhere"


async def test_every_declared_key_is_reachable_from_some_cycle(world: dict[str, Any]) -> None:
    """The other direction: a declaration nobody writes is fiction, the way a stale port entry is.

    Some keys only appear on one of the two paths, so both are run and the union is what must be
    covered.  Keys that need a venue this fake cannot be are named here with the reason.
    """
    engine, store = world["engine"], world["store"]
    await engine.startup()
    await engine.guarded_cycle(world["bar"])

    async def boom(_reports: Any) -> list[str]:
        raise RuntimeError("after the decisions")

    engine._quarantine = boom  # type: ignore[method-assign]
    await engine.guarded_cycle(world["bar"] + 3_600_000)

    seen: set[str] = set()
    for row in store.read_jsonl(store.cycles_path):
        seen |= set(row)

    # Written only under conditions this fixture does not create.  Each needs a REASON, not a shrug.
    conditional = {
        "margin": "only when risk-adding orders had to be scaled to available margin",
        "universe_update": "only on the first cycle of a new UTC day",
        "quarantined": "present on both paths, but empty unless the venue rejected repeatedly",
        "summary": "written by the normal path only",
        "external_flows": "only when the venue reported a TRANSFER row",
        "governance": "only while Policy.record_digest_every_cycle is on",
        "registry": "written from the process's held digest, which this engine has not built",
    }
    missing = set(KEYS) - seen - set(conditional)
    assert not missing, f"cycle_record.KEYS declares {sorted(missing)}, which no cycle writes"


def test_latest_skips_rows_written_before_the_field_existed() -> None:
    """The one question that really was asked twice: the newest row carrying a field.

    Deliberately without a predicate parameter.  `verify`'s three backwards scans each carry a
    different one and each explains itself; folding them in here would delete the explanations.
    """
    rows = [
        {"phase": "OK", "equity": 100.0},
        {"phase": "OK"},  # an older row, before the field existed
        {"phase": "OK", "equity": 300.0},
        {"phase": "OK"},
    ]

    assert latest(rows, "equity") == 300.0
    assert latest(rows, "never_written") is None
    assert latest([], "equity") is None


def test_latest_treats_an_explicit_null_as_absent() -> None:
    """A row that carried the key with nothing in it is a row written before the value existed."""
    assert latest([{"collateral": {"share": 0.5}}, {"collateral": None}], "collateral") == {"share": 0.5}
