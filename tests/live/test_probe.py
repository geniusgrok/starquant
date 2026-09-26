"""D-019: probe books - the stop rule, the engine's reaction and its persistence across restarts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry, parse_registry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.engine import LiveEngine
from starquant_live.probe import DAY_MS, ProbeParams, probe_status, probes_from_registry
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _prices

NOW = 1_756_800_000_000  # 2025-09-02T08:00Z


def _rows(*pnls: tuple[int, float]) -> list[dict]:
    return [
        {"until_ms": stamp, "basis": "net_exposure", "by_strategy": {"flow": pnl, "tsmom": 1.0}} for stamp, pnl in pnls
    ]


def test_a_row_on_the_retired_basis_is_skipped_rather_than_added() -> None:
    """D-044: the 30-day window may not mix the two splitting rules.

    The magnitude rule gave every strategy in a symbol the sign of that SYMBOL's P&L, so for a
    short-only sleeve sitting beside a long main book the old rows can carry the opposite sign to
    what the sleeve's own exposure earned.  Adding them to net-exposure rows produces a number that
    is neither, and it would be the number a stop fires on.

    The skipped rows are counted, not silently dropped: a window that thins out because the caliber
    changed has to be distinguishable from a sleeve that stopped trading.
    """
    probe = ProbeParams(book="flow_short", strategy="flow", window_days=30, max_loss=0.01)
    legacy = [{"until_ms": NOW - 5 * DAY_MS, "by_strategy": {"flow": -500.0, "tsmom": 1.0}}]  # no `basis` key
    status = probe_status(probe, legacy, equity=10_000.0, now_ms=NOW)
    assert status["rows"] == 0 and status["pnl"] == 0.0 and status["pnl_pct"] is None
    assert status["stale_basis_rows"] == 1 and status["stop"] is False
    mixed = probe_status(probe, legacy + _rows((NOW - DAY_MS, -30.0)), equity=10_000.0, now_ms=NOW)
    assert mixed["rows"] == 1 and mixed["pnl"] == -30.0 and mixed["stale_basis_rows"] == 1


def test_probe_status_windows_stop_and_review() -> None:
    probe = ProbeParams(book="flow_short", strategy="flow", window_days=30, max_loss=0.01, review_after_days=90)
    empty = probe_status(probe, [], equity=10_000.0, now_ms=NOW)
    assert empty["status"] == "OK" and empty["pnl_pct"] is None and empty["days_running"] is None
    rows = _rows((NOW - 40 * DAY_MS, -500.0), (NOW - 10 * DAY_MS, -60.0), (NOW - DAY_MS, -30.0))
    status = probe_status(probe, rows, equity=10_000.0, now_ms=NOW)
    assert status["rows"] == 2 and status["pnl"] == -90.0 and status["pnl_pct"] == pytest.approx(-0.009)
    assert status["status"] == "OK" and status["days_running"] == pytest.approx(40.0)
    stopped = probe_status(probe, rows + _rows((NOW - 2 * DAY_MS, -20.0)), equity=10_000.0, now_ms=NOW)
    assert stopped["stop"] and stopped["status"] == "STOP" and stopped["pnl_pct"] == pytest.approx(-0.011)
    # a literal "any loss stops" rule
    assert probe_status(ProbeParams("b", "flow", max_loss=0.0), _rows((NOW, -1.0)), equity=1.0, now_ms=NOW)["stop"]
    assert not probe_status(ProbeParams("b", "flow", max_loss=0.0), _rows((NOW, 1.0)), equity=1.0, now_ms=NOW)["stop"]
    dated = ProbeParams(book="b", strategy="flow", review_after_days=90, accepted_on="2025-06-01")
    review = probe_status(dated, _rows((NOW - DAY_MS, 5.0)), equity=10_000.0, now_ms=NOW)
    assert review["status"] == "REVIEW_DUE" and review["days_running"] > 90
    # attribution earned under this strategy id before the acceptance date is not the probe's record
    recent = ProbeParams(book="b", strategy="flow", accepted_on="2025-09-01")
    mixed = _rows((NOW - 3 * DAY_MS, -900.0), (NOW - DAY_MS, -20.0))
    before = probe_status(recent, mixed, equity=10_000.0, now_ms=NOW)
    assert before["rows"] == 1 and before["pnl"] == -20.0 and not before["stop"]
    assert before["days_running"] == pytest.approx(1.0 + 8 / 24)
    with pytest.raises(ValueError):
        ProbeParams("b", "flow", window_days=0)
    registry = parse_registry(
        {
            "books": {"flow_short": {"fraction": 0.5}},
            "strategies": [
                {"id": "tsmom"},
                {
                    "id": "flow",
                    "book": "flow_short",
                    "probe": {"accepted_on": "2026-09-03", "stop": {"window_days": 20, "max_loss": 0.02}},
                },
                {"id": "xsmom", "enabled": False, "book": "flow_short", "probe": {"stop": {}}},
            ],
        }
    )
    probes = probes_from_registry(registry)
    assert [p.strategy for p in probes] == ["flow"] and probes[0].window_days == 20 and probes[0].max_loss == 0.02


def _two_book_model() -> AlphaModel:
    main = StrategyEntry(
        "tsmom",
        params={
            **TsmomParams(vol_window=100).__dict__,
            "horizons": [5, 20, 50],
            "horizon_weights": [0.2, 0.3, 0.5],
            "entry_threshold": 0.05,
        },
    )
    sleeve = StrategyEntry("breakout", params={**asdict(BreakoutParams()), "entry_threshold": 0.05}, book="probe")
    return AlphaModel(
        entries=(main, sleeve),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
        books={"probe": 0.5},
    )


async def test_engine_stops_a_probe_book_and_keeps_it_stopped(august_panel: Panel, tmp_path: Path) -> None:
    probe = ProbeParams(book="probe", strategy="breakout", window_days=30, max_loss=0.01, accepted_on="2026-08-01")
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    config = _config(tmp_path, probes=(probe,), strategy_weights={"tsmom": 1.0, "breakout": 0.5})
    engine = LiveEngine(config, model=_two_book_model(), market=market, venue=venue, clock=clock, store=store)
    await engine.startup()
    bar = market.bar_open_ms(cursor - 1)
    first = await engine.run_cycle(bar)
    assert first["probes"][0]["status"] == "OK" and set(engine.state.last_contributions) == {"tsmom", "breakout"}
    assert store.read_heartbeat()["probes"] == {"probe": "OK"}
    # losses attributed to the sleeve inside the trailing window: -2% of equity
    store.append_attribution(
        {
            "bar_open_ms": bar,
            "until_ms": clock.now_ms(),
            "basis": "net_exposure",
            "by_strategy": {"breakout": -200.0, "tsmom": 40.0},
        }
    )
    market.cursor += 1
    second = await engine.run_cycle(bar + 3_600_000)
    status = second["probes"][0]
    assert status["stop"] and status["status"] == "STOPPED" and status["pnl_pct"] == pytest.approx(-0.02, rel=0.05)
    assert "probe" in engine.state.stopped_books and "reason" in engine.state.stopped_books["probe"]
    assert [e.id for e in engine.model.entries] == ["tsmom"]
    assert set(engine.state.last_contributions) == {"tsmom"}
    assert store.read_heartbeat()["probes"] == {"probe": "STOPPED"}
    # a restart with the full model still excludes the stopped book
    fresh = LiveEngine(
        config, model=_two_book_model(), market=market, venue=venue, clock=clock, store=StateStore(tmp_path / "live")
    )
    assert [e.id for e in fresh.model.entries] == ["tsmom"]
    market.cursor += 1
    third = await fresh.run_cycle(bar + 2 * 3_600_000)
    assert third["probes"][0]["status"] == "STOPPED" and set(fresh.state.last_contributions) == {"tsmom"}


async def test_income_ingestion_survives_a_backwards_clock_jump(august_panel: Panel, tmp_path: Path) -> None:
    """A watermark ahead of the clock must not abort the cycle (-1023); it skips ingestion and keeps the watermark."""
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(
        _config(tmp_path), model=_two_book_model(), market=market, venue=venue, clock=clock, store=store
    )
    await engine.startup()
    watermark = clock.now_ms() + 3_612_000  # the host clock jumped an hour backwards after the last cycle
    engine.state.last_income_ms = watermark
    venue.income_log.append({"incomeType": "REALIZED_PNL", "symbol": "BTCUSDT", "income": "5.0"})
    record = await engine.run_cycle(market.bar_open_ms(cursor - 1))
    assert "income" not in venue.calls, "the cycle must not ask the venue for a backwards time range"
    assert record["external_flows"]["clock_skew_ms"] == 3_612_000
    assert engine.state.last_income_ms == watermark, "the watermark must not move backwards"
    assert not record["skip"] and record["guard_reasons"] == []
    assert "summary" in record, "the cycle must still reach the trading stage"
    clock.advance(3_613.0)  # the clock catches up
    later = await engine.run_cycle(market.bar_open_ms(cursor - 1) + 3_600_000)
    assert "income" in venue.calls and later["external_flows"]["rows"] == 0
    assert engine.state.last_income_ms > watermark
