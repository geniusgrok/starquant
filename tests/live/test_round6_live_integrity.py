"""Round 6: request window from registry params, external cash flows, the cross-cycle hold seed, exit references."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_data.store import KlineStore
from starquant_live.attribution import attribute, external_flows
from starquant_live.composition import load_panel
from starquant_live.engine import MAX_HISTORY_BARS, LiveEngine
from starquant_live.exits import ExitOverlay
from starquant_live.reports import daily_payload, drift_check, expectations_from_evidence
from starquant_live.state import LiveState, StateStore
from starquant_shared.types import Position
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import SYMBOLS, _config, _model, _prices

WEEKLY = {"horizons": [168, 336, 720], "horizon_weights": [0.2, 0.3, 0.5]}


def _weekly_model(min_history_bars: int) -> AlphaModel:
    entry = StrategyEntry("tsmom", params={**TsmomParams().__dict__, **WEEKLY})
    return AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=min_history_bars,
    )


def _engine(august_panel: Panel, tmp_path: Path, model: AlphaModel, store: StateStore | None = None) -> dict:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = store or StateStore(tmp_path / "live")
    engine = LiveEngine(_config(tmp_path), model=model, market=market, venue=venue, clock=clock, store=store)
    return {"engine": engine, "venue": venue, "market": market, "store": store, "bar": market.bar_open_ms(cursor - 1)}


# --- P1: the request window follows the registry params and never truncates silently ------------------


async def test_history_bars_derive_from_registry_params_and_refuse_overflow(
    august_panel: Panel, tmp_path: Path
) -> None:
    hourly = _engine(august_panel, tmp_path / "a", _model())
    assert hourly["engine"].history_bars == 300  # config floor; 5/20/50 defaults need only 97
    weekly = _engine(august_panel, tmp_path / "b", _weekly_model(min_history_bars=720))
    assert weekly["engine"].history_bars == 720 + 722  # listing-age filter + the 720-bar horizon + 1 (E-042)
    too_big = _engine(august_panel, tmp_path / "c", _weekly_model(min_history_bars=1000))
    assert too_big["engine"].history_bars > MAX_HISTORY_BARS
    with pytest.raises(RuntimeError, match="serves at most"):
        await too_big["engine"].startup()


# --- P3: external cash flows re-baseline and are recorded --------------------------------------------


async def test_external_transfer_rebaselines_and_is_recorded(august_panel: Panel, tmp_path: Path) -> None:
    world = _engine(august_panel, tmp_path, _model())
    engine, venue, market, store = world["engine"], world["venue"], world["market"], world["store"]
    await engine.startup()
    first = await engine.run_cycle(world["bar"])
    assert first["external_flows"] == {"total": 0.0, "rows": 0, "by_type": {}, "rebaselined": False}
    assert venue.order_log, "the first cycle must open positions"
    # a demo reset / deposit between two cycles (E-044): money moves without a trade
    venue.balance += 5_000.0
    venue.income_log.append({"symbol": "", "incomeType": "TRANSFER", "income": 5_000.0, "asset": "USDT"})
    market.cursor += 1
    for symbol in SYMBOLS:
        venue.set_price(symbol, float(market.panel.close[symbol].iloc[market.cursor - 1]))
    second = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))
    flows = second["external_flows"]
    assert flows["total"] == pytest.approx(5_000.0) and flows["rows"] == 1 and flows["rebaselined"]
    assert flows["by_type"] == {"TRANSFER": pytest.approx(5_000.0)}
    assert engine.state.day_start_equity == pytest.approx(second["equity"])
    assert engine.state.equity_hwm == pytest.approx(second["equity"])
    rows = store.read_jsonl(store.attribution_path)
    assert rows and rows[-1]["external_flows"]["rows"] == 1 and rows[-1]["bar_open_ms"] == world["bar"]
    assert "tsmom" in rows[-1]["by_strategy"]  # the first cycle's fills are attributed to the targets that caused them


def test_attribution_splits_by_net_exposure_and_flows_are_separated() -> None:
    """D-044: a strategy on the other side of a symbol is charged the other sign.

    E-050's own scenario, re-priced.  `a` is long 0.5 and `b` short 0.3 while the symbol loses 4, so
    the book's net exposure is +0.2 and the loss belongs to the long: `a` -10, `b` +6, summing to the
    -4 that actually happened.  The magnitude rule this replaces paid them -2.5 and -1.5 - both
    charged for a loss only one of them was positioned for.
    """
    conflict = attribute(
        [{"symbol": "X", "incomeType": "REALIZED_PNL", "income": "-4"}],
        {"a": {"X": 0.5}, "b": {"X": -0.3}},
        {"a": 1.0, "b": 1.0},
    )
    assert conflict["by_strategy"]["a"] == pytest.approx(-10.0) and conflict["by_strategy"]["b"] == pytest.approx(6.0)
    assert sum(conflict["by_strategy"].values()) == pytest.approx(conflict["total"])
    assert conflict["basis"] == "net_exposure"
    # E-050's failure mode is refused rather than rewritten: legs that cancel to within MIN_NET_SHARE
    # of their gross have no attributable owner, so the income is booked as cancelled, not split.
    cancelled = attribute(
        [{"symbol": "X", "incomeType": "REALIZED_PNL", "income": "-4"}],
        {"a": {"X": 0.5}, "b": {"X": -0.48}},
        {"a": 1.0, "b": 1.0},
    )
    assert cancelled["by_strategy"] == {}
    assert cancelled["unattributed"] == pytest.approx(-4.0)
    assert cancelled["cancelled"] == {"X": pytest.approx(-4.0)}
    # A symbol nobody held is an absence, not a cancellation - the two must not read the same.
    absent = attribute([{"symbol": "Z", "incomeType": "REALIZED_PNL", "income": "-4"}], {"a": {"X": 0.5}}, {"a": 1.0})
    assert absent["unattributed"] == pytest.approx(-4.0) and absent["cancelled"] == {}
    reset = attribute([{"symbol": "", "incomeType": "TRANSFER", "income": "5000"}], {}, {})
    assert reset["by_symbol"] == {} and reset["total"] == 0.0
    assert reset["external_flows"] == {"total": 5000.0, "rows": 1, "by_type": {"TRANSFER": 5000.0}}
    assert external_flows([{"incomeType": "COMMISSION", "income": "-1"}]) == {"total": 0.0, "rows": 0, "by_type": {}}


def _cycles(store: StateStore, equities: list[float], *, start: int = 0, flagged: set[int] = frozenset()) -> None:
    base = 1_756_800_000_000  # 2025-09-02T08:00Z
    for offset, equity in enumerate(equities):
        i = start + offset
        record = {
            "bar_open_ms": base + i * 3_600_000,
            "equity": equity,
            "skip": False,
            "guard_reasons": [],
            "targets": {},
            "orders": [],
        }
        if i in flagged:
            record["external_flows"] = {
                "total": -5_000.0,
                "rows": 1,
                "by_type": {"TRANSFER": -5_000.0},
                "rebaselined": True,
            }
        store.append_cycle(record)


def test_drift_check_skips_rebaselined_bars_and_daily_report_lists_flows(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    _cycles(store, [10_000 * (1 + 0.0002 * i) for i in range(100)])
    _cycles(store, [5_000 * (1 + 0.0002 * i) for i in range(60)], start=100, flagged={100})  # a reset halves equity
    expectations = expectations_from_evidence(
        {"tsmom": {"walk_forward": {"oos_sharpe": 1.4}, "full_sample": {"max_drawdown": -0.13}}}
    )
    drift = drift_check(store, expectations)
    assert drift["status"] == "OK", drift  # the -50% bar is not a return; without the skip it would be an ALERT
    payload = daily_payload(store, "2025-09-06")  # the flagged bar (offset 100) falls on this UTC day
    assert payload["external_flows"] == {"total": -5_000.0, "rows": 1, "rebaselined_cycles": 1}


# --- P4: NO_ACTION keeps the previous cycle's target even with a short window -----------------------


async def test_previous_targets_seed_the_hold_across_cycles(august_panel: Panel, tmp_path: Path) -> None:
    entry = StrategyEntry(
        "tsmom",
        params={
            **TsmomParams(vol_window=100).__dict__,
            "horizons": [5, 20, 50],
            "horizon_weights": [0.2, 0.3, 0.5],
            "entry_threshold": 1.0,
        },  # nothing is ever actionable inside the window
    )
    model = AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )
    store = StateStore(tmp_path / "live")
    store.save(LiveState(last_contributions={"tsmom": {"BTCUSDT": 0.5}, "flow": {"ETHUSDT": 1.0}}))
    world = _engine(august_panel, tmp_path, model, store=store)
    engine, venue = world["engine"], world["venue"]
    await engine.startup()
    record = await engine.run_cycle(world["bar"])
    assert record["targets"]["BTCUSDT"] > 0 and all(record["targets"][s] == 0 for s in SYMBOLS if s != "BTCUSDT")
    assert venue.qty.get("BTCUSDT", 0.0) > 0 and "ETHUSDT" not in venue.qty
    assert engine.state.last_contributions == {"tsmom": {s: (0.5 if s == "BTCUSDT" else 0.0) for s in SYMBOLS}}


# --- P8: the exit reference is the first entry, not the venue's moving VWAP ------------------------------


def test_live_exit_reference_keeps_first_entry_across_same_direction_resizes() -> None:
    overlay = ExitOverlay(ExitParams(take_profit=6.0, cooldown_bars=2, vol_halflife=48), interval_ms=3_600_000)
    closes = [100.0 * (1.01 if i % 2 else 1.0) for i in range(60)] + [101.0]
    frame = pd.DataFrame({"close": closes, "volume": 1.0})
    first = Position("BTCUSDT", qty=1.0, entry_price=100.0, mark_price=101.0)
    _, states, _ = overlay.apply(
        {"BTCUSDT": 0.1}, positions={"BTCUSDT": first}, bars={"BTCUSDT": frame}, states={}, bar_open_ms=10
    )
    assert states["BTCUSDT"]["entry_price"] == 100.0 and states["BTCUSDT"]["direction"] == 1
    resized = Position("BTCUSDT", qty=2.0, entry_price=105.0, mark_price=101.0)  # added to the long at a higher VWAP
    _, states2, _ = overlay.apply(
        {"BTCUSDT": 0.2}, positions={"BTCUSDT": resized}, bars={"BTCUSDT": frame}, states=states, bar_open_ms=20
    )
    assert states2["BTCUSDT"]["entry_price"] == 100.0 and states2["BTCUSDT"]["unit"] == states["BTCUSDT"]["unit"]
    flipped = Position("BTCUSDT", qty=-1.0, entry_price=99.0, mark_price=101.0)
    _, states3, _ = overlay.apply(
        {"BTCUSDT": -0.1}, positions={"BTCUSDT": flipped}, bars={"BTCUSDT": frame}, states=states2, bar_open_ms=30
    )
    assert states3["BTCUSDT"]["direction"] == -1 and states3["BTCUSDT"]["entry_price"] == 99.0


# --- research on universe.json must survive a symbol the pool admitted before any sync -------------------


def test_load_panel_skips_symbols_without_stored_klines(tmp_path: Path, august_dir: Path) -> None:
    store = KlineStore(tmp_path)
    store.append("BTCUSDT", "1h", pd.read_parquet(august_dir / "BTCUSDT" / "1h.parquet"))
    panel = load_panel(store, ["BTCUSDT", "NOPEUSDT"], "1h")
    assert panel.symbols == ["BTCUSDT"]
    with pytest.raises(ValueError):
        load_panel(store, ["NOPEUSDT"], "1h")
