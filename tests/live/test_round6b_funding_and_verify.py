"""Round 6b (KILL-027 / M-011): funding history reaches the live panel, and the live output is verifiable offline.

The bug this closes: a signal that reads ``panel.funding`` got ``None`` on the live path while the
registry evidence claimed the modifier was on, so the loop traded a configuration nobody validated.
The fix is declarative — a signal says whether it needs funding, the model refuses to run without it,
and the engine refuses to start when the market port cannot supply it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from starquant_alpha.ensemble import TargetWeights
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import get_signal
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_data.binance_public import funding_to_frame
from starquant_data.live_feed import funding_series
from starquant_live.alerts import WebhookAlerts
from starquant_live.engine import LiveEngine
from starquant_live.inputs import first_open_ms, model_inputs, required_history
from starquant_live.reconciler import take_snapshot
from starquant_live.state import LiveState, StateStore
from starquant_live.verify import compare_targets, last_recorded_as_of_ms
from tests.alpha.test_signal_suite import _synthetic_panel
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import SYMBOLS, _config, _model, _prices

CROWDING = {"crowding_window": 72, "crowding_cut": 0.7, "crowding_penalty": 0.5}
WEEKLY = {"horizons": [24, 72, 168], "horizon_weights": [0.2, 0.3, 0.5]}


def _model_with(params: dict, min_history_bars: int = 0) -> AlphaModel:
    entry = StrategyEntry("tsmom", params={**TsmomParams(vol_window=100).__dict__, **WEEKLY, **params})
    return AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=min_history_bars,
    )


def _frames(panel: Panel) -> dict[str, pd.DataFrame]:
    fields = ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote")
    return {
        symbol: pd.DataFrame(
            {field: getattr(panel, field)[symbol] for field in fields if getattr(panel, field) is not None}
        )
        for symbol in panel.symbols
    }


def _settled(panel: Panel) -> dict[str, pd.Series]:
    """Funding as the public endpoint returns it: only the settlements, not a value on every bar."""
    assert panel.funding is not None
    return {symbol: panel.funding[symbol][panel.funding[symbol] != 0.0] for symbol in panel.symbols}


# --- a signal declares whether it reads funding ---------------------------------------------------


def test_signals_declare_their_funding_use() -> None:
    tsmom = get_signal("tsmom")
    assert not tsmom.needs_funding({**WEEKLY, "crowding_window": 0})
    assert tsmom.needs_funding({**WEEKLY, **CROWDING})
    assert not tsmom.needs_funding({**WEEKLY, **CROWDING, "crowding_penalty": 0.0})  # inert modifier
    assert get_signal("carry").needs_funding({})  # carry is nothing but funding
    assert not get_signal("xsmom").needs_funding({})
    assert _model_with({**CROWDING}).needs_funding and not _model_with({"crowding_window": 0}).needs_funding


def test_targets_refuse_to_run_a_funding_signal_without_history() -> None:
    panel = _synthetic_panel(seed=5, n_bars=600)
    model = _model_with(CROWDING)
    with pytest.raises(ValueError, match="KILL-027"):
        model.targets(_frames(panel), {})
    assert model.targets(_frames(panel), {}, funding_history=_settled(panel)).weights  # supplied -> runs
    assert _model_with({"crowding_window": 0}).targets(_frames(panel), {}).weights  # not needed -> unchanged


# --- the live panel equals the research panel (the actual KILL-027 closer) --------------------------


def test_live_funding_history_reproduces_the_research_panel() -> None:
    panel = _synthetic_panel(seed=11, n_bars=900)
    model = _model_with(CROWDING)
    _weights, _combined, research = model.evaluate(panel)  # research path: panel.funding from the store
    live = model.targets(_frames(panel), {}, funding_history=_settled(panel))  # live path: settled rates only
    for symbol in panel.symbols:
        assert live.contributions["tsmom"][symbol] == pytest.approx(
            float(research["tsmom"].iloc[-1].fillna(0.0)[symbol]), abs=1e-12
        ), symbol
    # and the modifier is not a no-op on this panel, so the parity above is a real comparison
    without = _model_with({"crowding_window": 0}).targets(_frames(panel), {})
    assert any(abs(live.contributions["tsmom"][s] - without.contributions["tsmom"][s]) > 1e-9 for s in panel.symbols), (
        "the crowding modifier changed nothing here; pick a seed where it bites"
    )


def test_funding_series_maps_settlements_to_utc_times() -> None:
    frame = funding_to_frame(
        [
            {"fundingTime": 1_700_000_000_000, "fundingRate": "0.0001", "markPrice": "1"},
            {"fundingTime": 1_700_028_800_000, "fundingRate": "-0.0002", "markPrice": "1"},
        ]
    )
    series = funding_series(frame)
    assert list(series.values) == [0.0001, -0.0002]
    assert series.index[0] == pd.Timestamp(1_700_000_000_000, unit="ms", tz="UTC")
    assert funding_series(funding_to_frame([])).empty


# --- the cycle fetches funding only when the model needs it ----------------------------------------


async def test_model_inputs_fetch_funding_history_only_when_needed(august_panel: Panel) -> None:
    funding = pd.DataFrame(0.0, index=august_panel.index, columns=august_panel.symbols)
    funding.iloc[::8] = 0.0001
    market = FakeMarketData(august_panel, cursor=400, funding_history=funding)
    plain = await model_inputs(market, _model(), SYMBOLS, "1h", 300)
    assert plain.funding_history is None and not market.funding_history_calls
    assert plain.bars and plain.dropped == []
    hungry = await model_inputs(market, _model_with(CROWDING), SYMBOLS, "1h", 300)
    assert hungry.funding_history is not None and len(market.funding_history_calls) == 1
    requested_symbols, start_ms = market.funding_history_calls[0]
    assert sorted(requested_symbols) == sorted(SYMBOLS)
    assert start_ms == min(first_open_ms(frame) or 0 for frame in hungry.bars.values())
    assert all((series != 0.0).all() for series in hungry.funding_history.values())  # settlements only
    assert hungry.to_dict()["funding_history"] is True


async def test_startup_refuses_a_funding_model_when_the_port_cannot_supply_history(
    august_panel: Panel, tmp_path: Path
) -> None:
    class NoFundingHistory:
        """A market port from before D-021: closed bars and the latest rate, nothing else."""

        def __init__(self, inner: FakeMarketData) -> None:
            self._inner = inner

        async def closed_bars(self, symbols: Sequence[str], interval: str, limit: int) -> dict[str, pd.DataFrame]:
            return await self._inner.closed_bars(symbols, interval, limit)

        async def funding_rates(self, symbols: Sequence[str]) -> dict[str, float]:
            return await self._inner.funding_rates(symbols)

    market = FakeMarketData(august_panel, cursor=400)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    engine = LiveEngine(
        _config(tmp_path),
        model=_model_with(CROWDING),
        market=NoFundingHistory(market),  # type: ignore[arg-type]
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    with pytest.raises(RuntimeError, match="funding history"):
        await engine.startup()
    assert venue.order_log == []


async def test_cycle_passes_funding_history_through_to_the_model(august_panel: Panel, tmp_path: Path) -> None:
    funding = pd.DataFrame(0.0, index=august_panel.index, columns=august_panel.symbols)
    funding.iloc[::8] = 0.0002
    market = FakeMarketData(august_panel, cursor=400, funding_history=funding)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    engine = LiveEngine(
        _config(tmp_path),
        model=_model_with(CROWDING),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    await engine.startup()
    record = await engine.run_cycle(market.bar_open_ms(399))
    assert record["inputs"]["funding_history"] is True and market.funding_history_calls
    assert not record["skip"] and record["targets"]


# --- M-011: the last cycle reproduces offline ------------------------------------------------------


def _state(bar_ms: int, contributions: dict[str, dict[str, float]], targets: dict[str, float]) -> LiveState:
    return LiveState(last_bar_ms=bar_ms, last_contributions=contributions, last_targets=targets)


def _targets(bar: pd.Timestamp, contributions: dict[str, dict[str, float]], weights: dict[str, float]) -> TargetWeights:
    return TargetWeights(as_of=bar, weights=weights, contributions=contributions, combined={})


def test_verify_reports_a_faithful_reproduction() -> None:
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    contributions = {"tsmom": {"BTCUSDT": 0.34, "ETHUSDT": -0.2}}
    weights = {"BTCUSDT": 0.031, "ETHUSDT": -0.02}
    result = compare_targets(
        _targets(bar, contributions, weights), _state(int(bar.timestamp() * 1000), contributions, weights)
    )
    assert result["ok"] and result["bar_matched"]
    assert result["max_contribution_diff"] == 0.0 and result["max_target_diff"] == 0.0
    assert result["contribution_diffs"] == {"tsmom": {}} and result["strategies_not_in_state"] == []


def test_verify_flags_a_drifted_contribution_and_a_stale_bar() -> None:
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(int(bar.timestamp() * 1000), {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031})
    drifted = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.17}}, {"BTCUSDT": 0.031}), state)
    assert not drifted["ok"] and drifted["bar_matched"]
    assert drifted["max_contribution_diff"] == pytest.approx(0.17)
    assert drifted["contribution_diffs"]["tsmom"]["BTCUSDT"] == pytest.approx(0.17)
    assert "无法复现" in drifted["note"]
    stale = compare_targets(
        _targets(bar + pd.Timedelta(hours=1), {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031}), state
    )
    assert not stale["ok"] and not stale["bar_matched"] and "属于另一根 K 线" in stale["note"]
    # a target difference alone is informational: exits / throttle / guards act after the model
    exited = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.0}), state)
    assert exited["ok"] and exited["max_target_diff"] == pytest.approx(0.031)
    assert exited["target_diffs"] == {"BTCUSDT": pytest.approx(0.031)}


def test_a_symbol_that_left_the_universe_is_not_a_reproduction_failure() -> None:
    """`last_contributions` is a MEMORY, not a record of what the last cycle scored.

    `engine.py` merges each cycle's contributions into the previous ones on purpose - D-005's hold
    seed keeps a departed symbol's last value, the way the backtest's forward-fill does.  So the
    memory outlives the universe, while the reproduction scores only the names the cycle declared,
    and diffing the two over the UNION of their keys reports the departure as an unreproducible
    contribution - every hour, forever.

    Measured: TRUMPUSDT left the pinned universe at 2026-09-13T21:13Z and `live verify --check` went
    red on the next cycle and stayed red for 16 consecutive runs, with `max_target_diff` 0.0 the whole
    time.  The monitor's own output became the noisiest thing about it - which is the failure its own
    `reference_symbols` docstring, one field over, was written to prevent.
    """
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(
        int(bar.timestamp() * 1000),
        {"tsmom": {"BTCUSDT": 0.34, "TRUMPUSDT": 1.0}},  # the memory still carries the departed name
        {"BTCUSDT": 0.031},
    )
    state.universe = ["BTCUSDT"]  # what the cycle declared it was managing

    result = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031}), state)

    assert result["ok"], result["note"]
    assert result["contribution_diffs"] == {"tsmom": {}}
    assert result["max_contribution_diff"] == 0.0


def test_a_symbol_still_in_the_universe_that_stops_reproducing_is_still_caught() -> None:
    """The other side of the same line: this is what the monitor exists to see."""
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(int(bar.timestamp() * 1000), {"tsmom": {"BTCUSDT": 0.34, "ETHUSDT": -0.2}}, {"BTCUSDT": 0.031})
    state.universe = ["BTCUSDT", "ETHUSDT"]

    result = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031}), state)

    assert not result["ok"]
    assert result["contribution_diffs"]["tsmom"]["ETHUSDT"] == pytest.approx(0.2)


def test_a_symbol_held_only_to_be_reduced_out_is_still_compared() -> None:
    """`leaving` names are scored: the engine passes universe+leaving to the model and excludes the
    exits only from the cross-sectional RANKING (`engine.py`: "the model still scores it").  So they
    are part of the population this diff runs over, and dropping them would blind the monitor for
    exactly the cycles in which a symbol is being unwound."""
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(int(bar.timestamp() * 1000), {"tsmom": {"BTCUSDT": 0.34, "DOGEUSDT": 0.5}}, {"BTCUSDT": 0.031})
    state.universe, state.leaving = ["BTCUSDT"], ["DOGEUSDT"]

    result = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031}), state)

    assert not result["ok"]
    assert result["contribution_diffs"]["tsmom"]["DOGEUSDT"] == pytest.approx(0.5)


def test_a_state_that_declares_no_universe_is_compared_on_everything() -> None:
    """No declared population is not a licence to check less - it fails toward more comparison."""
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(int(bar.timestamp() * 1000), {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031})
    assert state.universe == []

    result = compare_targets(_targets(bar, {"tsmom": {"BTCUSDT": 0.17}}, {"BTCUSDT": 0.031}), state)

    assert not result["ok"] and result["contribution_diffs"]["tsmom"]["BTCUSDT"] == pytest.approx(0.17)


def test_verify_flags_a_strategy_the_state_never_saw() -> None:
    bar = pd.Timestamp("2026-09-03T13:00:00Z")
    state = _state(int(bar.timestamp() * 1000), {"tsmom": {"BTCUSDT": 0.34}}, {"BTCUSDT": 0.031})
    added = compare_targets(
        _targets(bar, {"tsmom": {"BTCUSDT": 0.34}, "flow": {"BTCUSDT": -0.1}}, {"BTCUSDT": 0.031}), state
    )
    assert not added["ok"] and added["strategies_not_in_state"] == ["flow"]


def test_required_history_matches_the_engine() -> None:
    weekly = _model_with({"crowding_window": 0}, min_history_bars=720)
    assert required_history(weekly, 400) == 720 + weekly.warmup_bars
    assert required_history(weekly, 5_000) == 5_000  # the profile floor wins when it is larger


async def test_gross_before_comes_from_position_risk_not_the_account_payload(
    august_panel: Panel, tmp_path: Path
) -> None:
    """The venue's account payload may carry no positions array; the cycle report must not read 0.0 then."""

    class NoPositionsInAccount(FakeVenue):
        async def account(self):  # type: ignore[no-untyped-def]
            state = await super().account()
            return replace(state, positions={})  # what demo-fapi actually returns

    market = FakeMarketData(august_panel, cursor=400)
    venue = NoPositionsInAccount(balance=10_000.0, prices=_prices(august_panel, 400))
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    await engine.startup()
    opened = await engine.run_cycle(market.bar_open_ms(399))
    assert opened["gross_before"] == 0.0  # genuinely flat before the first fills
    assert opened["orders"], "the first cycle should open the book"
    market.cursor += 1
    held = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))
    assert held["gross_before"] > 0.0, "a fully invested book must not report a flat gross"
    snapshot = await take_snapshot(engine.venue, engine.managed_symbols())
    assert snapshot.account.gross_notional() == 0.0  # the account payload really is empty here
    assert snapshot.gross_notional() > 0.0


def test_verify_prefers_the_data_bar_over_the_clock_label_when_the_host_drifts() -> None:
    """A host clock an hour behind the venue labels the cycle wrongly; the data still reproduces (2026-09-04)."""
    data_bar = pd.Timestamp("2026-09-04T02:00:00Z")
    label_ms = int((data_bar - pd.Timedelta(hours=1)).timestamp() * 1000)  # what the drifted clock wrote
    contributions = {"tsmom": {"BTCUSDT": 0.34}}
    state = _state(label_ms, contributions, {"BTCUSDT": 0.031})
    targets = _targets(data_bar, contributions, {"BTCUSDT": 0.031})
    naive = compare_targets(targets, state)
    assert not naive["ok"] and not naive["bar_matched"]  # comparing against the label alone: spurious failure
    aware = compare_targets(targets, state, recorded_as_of_ms=int(data_bar.timestamp() * 1000))
    assert aware["ok"] and aware["bar_matched"]
    assert aware["bar_label_skew_ms"] == 3_600_000
    assert aware["clock_note"] and "本机时钟已偏离交易所" in aware["clock_note"]
    assert (
        compare_targets(
            targets,
            _state(int(data_bar.timestamp() * 1000), contributions, {"BTCUSDT": 0.031}),
            recorded_as_of_ms=int(data_bar.timestamp() * 1000),
        )["clock_note"]
        is None
    )


def test_last_recorded_as_of_ms_ignores_dry_runs(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    assert last_recorded_as_of_ms(store) is None
    store.append_cycle({"bar_open_ms": 1, "as_of_ms": 111, "dry_run": False})
    store.append_cycle({"bar_open_ms": 2, "as_of_ms": 222, "dry_run": True})
    assert last_recorded_as_of_ms(store) == 111
    store.append_cycle({"bar_open_ms": 3, "as_of_ms": 333, "dry_run": False})
    assert last_recorded_as_of_ms(store) == 333


# --- item 2: the loop measures host-vs-venue skew every cycle -------------------------------------


class SkewedMarket(FakeMarketData):
    """A market port whose venue clock sits ``offset_ms`` away from the loop's own clock."""

    def __init__(self, panel: Panel, cursor: int, offset_ms: int, clock: FakeClock) -> None:
        super().__init__(panel, cursor)
        self.offset_ms = offset_ms
        self.clock = clock
        self.server_time_calls = 0

    async def server_time_ms(self) -> int:
        self.server_time_calls += 1
        return self.clock.now_ms() + self.offset_ms


class RecordingAlerts(WebhookAlerts):
    def __init__(self) -> None:
        super().__init__("")
        self.sent: list[str] = []

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        self.sent.append(text)
        return True


async def _cycle_with_skew(august_panel: Panel, tmp_path: Path, offset_ms: int) -> tuple[dict, RecordingAlerts, Any]:
    probe = FakeMarketData(august_panel, cursor=400)
    clock = FakeClock(probe.bar_open_ms(400) + 5_000)
    market = SkewedMarket(august_panel, cursor=400, offset_ms=offset_ms, clock=clock)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    alerts = RecordingAlerts()
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=clock,
        store=StateStore(tmp_path / "live"),
        alerts=alerts,
    )
    await engine.startup()
    record = await engine.run_cycle(market.bar_open_ms(399))
    return record, alerts, engine


async def test_a_whole_bar_offset_is_an_accepted_state_not_an_alarm(august_panel: Panel, tmp_path: Path) -> None:
    """D-025: the host clock is the reference, so an offset of whole bars is fine — the loop still wakes on a
    closed bar.  Measured live on 2026-09-04: 3,611,932 ms, which is one bar plus 12 s."""
    record, alerts, engine = await _cycle_with_skew(august_panel, tmp_path, offset_ms=3_612_000)
    clock = record["clock"]
    assert clock["skew_ms"] == pytest.approx(3_612_000, abs=5_000)
    assert clock["whole_bars"] == 1
    assert clock["alignment_ms"] == pytest.approx(12_000, abs=5_000)
    assert clock["beyond_tolerance"] is False and clock["jumped"] is False
    assert not [a for a in alerts.sent if "StarQuant时钟" in a], "a constant whole-bar offset must not page anyone"
    assert not record["skip"] and record["orders"]
    assert engine.state.last_clock_skew_ms == pytest.approx(clock["skew_ms"])


async def test_a_wake_up_in_the_middle_of_a_bar_is_flagged(august_panel: Panel, tmp_path: Path) -> None:
    """What actually endangers the cycle: waking 15 minutes off a bar boundary, so the newest bar may be open."""
    record, alerts, _ = await _cycle_with_skew(august_panel, tmp_path, offset_ms=900_000)
    clock = record["clock"]
    assert clock["alignment_ms"] == pytest.approx(900_000, abs=5_000)
    assert clock["beyond_tolerance"] is True
    assert len([a for a in alerts.sent if "StarQuant时钟" in a]) == 1
    assert not record["skip"], "the guard reports; it does not stop the loop"


async def test_the_alignment_alert_is_edge_triggered(august_panel: Panel, tmp_path: Path) -> None:
    _record, alerts, engine = await _cycle_with_skew(august_panel, tmp_path, offset_ms=900_000)
    market = engine.market
    market.cursor += 1  # type: ignore[attr-defined]
    again = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))  # type: ignore[attr-defined]
    assert again["clock"]["beyond_tolerance"] is True
    assert len([a for a in alerts.sent if "StarQuant时钟" in a]) == 1, "one alert per episode, not one per hour"


async def test_a_clock_jump_between_cycles_is_reported(august_panel: Panel, tmp_path: Path) -> None:
    """A jump remaps every label and can send the income watermark backwards — the -1023 of 2026-09-04."""
    _record, alerts, engine = await _cycle_with_skew(august_panel, tmp_path, offset_ms=3_612_000)
    assert not [a for a in alerts.sent if "StarQuant时钟" in a]
    market = engine.market
    market.offset_ms = 12_000  # type: ignore[attr-defined]  the venue stays put; the host clock jumped an hour
    market.cursor += 1  # type: ignore[attr-defined]
    after = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))  # type: ignore[attr-defined]
    assert after["clock"]["jumped"] is True
    assert after["clock"]["beyond_tolerance"] is False  # still aligned, but the mapping changed
    assert [a for a in alerts.sent if "跳变" in a]


async def test_a_port_without_a_clock_probe_is_not_an_error(august_panel: Panel, tmp_path: Path) -> None:
    market = FakeMarketData(august_panel, cursor=400)  # no server_time_ms
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    await engine.startup()
    record = await engine.run_cycle(market.bar_open_ms(399))
    assert record["clock"]["skew_ms"] is None and record["clock"]["beyond_tolerance"] is False
    assert not record["skip"]


async def test_a_recovered_cycle_clears_the_error_streak_on_disk(august_panel: Panel, tmp_path: Path) -> None:
    """A restart must not load a phantom error streak from a cycle that in fact succeeded."""
    market = FakeMarketData(august_panel, cursor=400)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    store = StateStore(tmp_path / "live")
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=store,
        alerts=RecordingAlerts(),
    )
    await engine.startup()
    market.fail_next = 1
    assert await engine.guarded_cycle(market.bar_open_ms(399)) is None
    # DL-L2: the streak is process-scoped now, so what has to reach disk is the *evidence* of the
    # failure - the append-only ERROR row and the heartbeat - not a counter that a restart would inherit.
    assert engine.consecutive_errors == 1
    assert json.loads(store.heartbeat_path.read_text(encoding="utf-8"))["consecutive_errors"] == 1
    assert await engine.guarded_cycle(market.bar_open_ms(399)) is not None
    assert engine.consecutive_errors == 0
    assert not hasattr(store.load(), "consecutive_errors"), "a restart must not inherit the streak"


def test_the_construction_fingerprint_sees_what_the_evidence_gate_cannot(tmp_path: Path) -> None:
    """D-026: changing the band changes every weight, and no registry check can see it."""
    from dataclasses import replace as dc_replace

    from starquant_alpha.overlays.exits import ExitParams
    from starquant_live.engine import construction_fingerprint

    base = _config(tmp_path)
    same = construction_fingerprint(dc_replace(base, history_bars=base.history_bars + 1))
    assert construction_fingerprint(base)["digest"] == same["digest"], "history_bars is not construction"
    widened = dc_replace(base, rebalance=dc_replace(base.rebalance, no_trade_rel_band=0.40))
    assert construction_fingerprint(widened)["digest"] != construction_fingerprint(base)["digest"]
    assert construction_fingerprint(widened)["rebalance"]["no_trade_rel_band"] == 0.40
    assert base.exits.take_profit == 0.0  # the loop-test config ships with the overlay off
    exits_on = dc_replace(base, exits=ExitParams(take_profit=6.0))
    assert construction_fingerprint(exits_on)["digest"] != construction_fingerprint(base)["digest"]
    assert construction_fingerprint(exits_on)["exits"]["take_profit"] == 6.0
    breathing = dc_replace(base, exits=dc_replace(base.exits, unit_mode="current"))
    assert construction_fingerprint(breathing)["digest"] != construction_fingerprint(base)["digest"]
    assert construction_fingerprint(breathing)["exits"]["unit_mode"] == "current"


async def test_a_cycle_records_the_construction_it_ran_under(august_panel: Panel, tmp_path: Path) -> None:
    from starquant_live.engine import construction_fingerprint

    market = FakeMarketData(august_panel, cursor=400)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400))
    store = StateStore(tmp_path / "live")
    config = _config(tmp_path)
    engine = LiveEngine(
        config,
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=store,
    )
    await engine.startup()
    started = store.read_heartbeat() or {}
    assert started["construction"]["rebalance"]["no_trade_rel_band"] == config.rebalance.no_trade_rel_band
    record = await engine.run_cycle(market.bar_open_ms(399))
    assert record["construction"] == construction_fingerprint(config)["digest"]
