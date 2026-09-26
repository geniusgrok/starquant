"""Fixtures for DL-X1's wiring tests: a venue whose REST calls are recorded, and a startable engine."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData


class _RecordingClient:
    """The smallest thing `BinanceUsdmVenue` will talk to: one dispatch table, one call log."""

    def __init__(self, responses: Mapping[str, Any]) -> None:
        self._responses = dict(responses)
        self.seen: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None, *, signed: bool = False) -> Any:
        self.seen.append((path, dict(params or {})))
        if path not in self._responses:
            raise AssertionError(f"unexpected GET {path}")
        return self._responses[path]

    async def aclose(self) -> None:  # pragma: no cover - the venue closes its client on teardown
        return None


def recording_venue(*, response: Any) -> tuple[BinanceUsdmVenue, list[tuple[str, dict[str, Any]]]]:
    client = _RecordingClient({"/fapi/v1/forceOrders": response})
    return BinanceUsdmVenue(client), client.seen  # type: ignore[arg-type]


def margin_mode_venue(*, multi_assets: bool, rows: Sequence[Mapping[str, Any]]) -> BinanceUsdmVenue:
    client = _RecordingClient(
        {
            "/fapi/v1/multiAssetsMargin": {"multiAssetsMargin": multi_assets},
            "/fapi/v2/positionRisk": [dict(row) for row in rows],
        }
    )
    return BinanceUsdmVenue(client)  # type: ignore[arg-type]


class _MarginModeVenue(FakeVenue):
    """A fake venue that can answer the margin-mode probe - or, given ``None``, cannot."""

    def __init__(self, mode: dict[str, Any] | None) -> None:
        super().__init__()
        if mode is not None:
            self.margin_mode = _constant(mode)  # type: ignore[method-assign]


def _constant(value: dict[str, Any]) -> Any:
    async def probe() -> dict[str, Any]:
        return value

    return probe


def engine_with_margin_mode(mode: dict[str, Any] | None) -> LiveEngine:
    """An engine whose ``start()`` reaches the margin-mode assertion and nothing costlier.

    ``dry_run`` keeps startup read-only, so no leverage is set and no order is cancelled; the market
    data feed is never touched before the assertion, which is the point of asserting there.
    """
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams

    tmp = Path(tempfile.mkdtemp())
    model = AlphaModel(
        entries=(StrategyEntry("tsmom", params=dict(TsmomParams().__dict__)),),
        portfolio=PortfolioParams(),
        interval="1h",
        min_history_bars=0,
    )
    config = LiveConfig(
        interval="1h",
        history_bars=300,
        universe=("BTCUSDT", "ETHUSDT"),
        leverage=2,
        rebalance=RebalanceParams(),
        guards=GuardParams(),
        kill_switch_path=tmp / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
        dry_run=True,
    )
    return LiveEngine(
        config,
        model=model,
        market=None,  # type: ignore[arg-type]
        venue=_MarginModeVenue(mode),
        clock=FakeClock(1_700_000_000_000),
        store=StateStore(tmp / "live"),
    )


class _RecordingAlerts:
    """Enough of `WebhookAlerts` for the engine: record what was sent, accept everything."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.urls: tuple[str, ...] = ()

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        self.sent.append(text)
        return True

    def clear(self, key: str) -> None:
        return None


class _LiquidatableVenue(FakeVenue):
    """A venue whose positions carry a liquidation price a fixed fraction away from the mark."""

    def __init__(self, fraction: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fraction = fraction

    async def positions(self) -> dict[str, Any]:
        out = await super().positions()
        return {
            symbol: replace(
                position,
                liquidation_price=position.mark_price * (1.0 - self._fraction)
                if position.qty > 0
                else position.mark_price * (1.0 + self._fraction),
            )
            for symbol, position in out.items()
        }


async def cycle_with_liquidation_price(panel: Any, tmp_path: Any, *, liquidation_fraction: float) -> list[str]:
    """Run one real cycle and return every alert the engine sent.

    ``liquidation_fraction`` is the distance from mark to liquidation as a fraction of the mark, so a
    small number puts the book right on top of its liquidation price and a large one puts it far away.
    """
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams

    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    cursor = 400
    market = FakeMarketData(panel, cursor)
    prices = {symbol: float(panel.close[symbol].iloc[cursor - 1]) for symbol in symbols}
    venue = _LiquidatableVenue(liquidation_fraction, balance=10_000.0, prices=prices)
    alerts = _RecordingAlerts()
    params = dict(TsmomParams(vol_window=100).__dict__) | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    model = AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )
    config = LiveConfig(
        interval="1h",
        history_bars=300,
        universe=tuple(symbols),
        leverage=2,
        rebalance=RebalanceParams(no_trade_band=0.002),
        guards=GuardParams(),
        kill_switch_path=Path(tmp_path) / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
    )
    engine = LiveEngine(
        config,
        model=model,
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=StateStore(Path(tmp_path) / "live"),
        alerts=alerts,  # type: ignore[arg-type]
    )
    await engine.startup()
    # Two cycles: the first opens the book, the second runs with positions held.
    await engine.run_cycle(market.bar_open_ms(cursor))
    await engine.run_cycle(market.bar_open_ms(cursor))
    return alerts.sent


async def startup_with_foreign_position(foreign: list[str]) -> list[str]:
    """Run `startup()` against a venue holding positions outside the managed universe (DL-L5)."""
    import tempfile

    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams

    tmp = Path(tempfile.mkdtemp())
    venue = FakeVenue()
    for symbol in foreign:
        venue.qty[symbol] = 100.0
        venue.entry[symbol] = 1.0
        venue.prices.setdefault(symbol, 1.0)
        venue._rules.setdefault(symbol, next(iter(venue._rules.values())))
    alerts = _RecordingAlerts()
    engine = LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=300,
            universe=("BTCUSDT", "ETHUSDT"),
            leverage=2,
            rebalance=RebalanceParams(),
            guards=GuardParams(),
            kill_switch_path=tmp / "KILL_SWITCH",
            strategy_weights={"tsmom": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
            dry_run=True,
        ),
        model=AlphaModel(
            entries=(StrategyEntry("tsmom", params=dict(TsmomParams().__dict__)),),
            portfolio=PortfolioParams(),
            interval="1h",
            min_history_bars=0,
        ),
        market=None,  # type: ignore[arg-type]
        venue=venue,
        clock=FakeClock(1_700_000_000_000),
        store=StateStore(tmp / "live"),
        alerts=alerts,  # type: ignore[arg-type]
    )
    await engine.startup()
    return alerts.sent


class _FailingVenue(FakeVenue):
    """Lets `startup()` through, then fails every cycle except the ones named in ``succeed_at``.

    Failing during startup would exercise something else entirely: the loop never reaches a cycle, so
    the consecutive-error counter never moves and the breaker is not involved at all.
    """

    def __init__(self, *, succeed_at: int | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cycle = 0
        self._succeed_at = succeed_at
        self.failures = 0
        self._started = False

    async def account(self) -> Any:
        if not self._started:  # the startup reconcile
            self._started = True
            return await super().account()
        self._cycle += 1
        if self._cycle == self._succeed_at:
            return await super().account()
        self.failures += 1
        raise RuntimeError("venue is unreachable")


def breaker_engine(
    tmp_path: Any, panel: Any, *, limit: int, succeed_at: int | None = None
) -> tuple[Any, Any, Any, Any]:
    """An engine whose every cycle fails at the VENUE, wired to the real `run()` loop (AC-L2).

    Real market data on purpose: with `market=None` the cycle dies on an AttributeError before the
    venue is ever called, so the test would pass while exercising a failure mode no operator can hit.
    """
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams

    root = Path(tmp_path)
    symbols = ["BTCUSDT", "ETHUSDT"]
    cursor = 400
    market = FakeMarketData(panel, cursor)
    prices = {s: float(panel.close[s].iloc[cursor - 1]) for s in symbols}
    venue = _FailingVenue(succeed_at=succeed_at, prices=prices)
    # A REAL `WebhookAlerts` over a mock transport, not the recording stub: the stub has no dedup, so
    # asserting on it would be asserting that the fake records everything - true, and about nothing.
    import httpx

    from starquant_live.alerts import WebhookAlerts

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        sent.append(body.get("content", {}).get("text") or body.get("text", ""))
        return httpx.Response(200, json={"code": 0})

    alerts = WebhookAlerts("https://open.feishu.cn/x", transport=httpx.MockTransport(handler))
    alerts.sent = sent  # type: ignore[attr-defined]
    store = StateStore(root / "live")
    engine = LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=300,
            universe=tuple(symbols),
            leverage=2,
            rebalance=RebalanceParams(),
            guards=GuardParams(),
            kill_switch_path=root / "KILL_SWITCH",
            strategy_weights={"tsmom": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
            dry_run=True,
            max_consecutive_errors=limit,
        ),
        model=AlphaModel(
            entries=(StrategyEntry("tsmom", params=dict(TsmomParams().__dict__)),),
            portfolio=PortfolioParams(),
            interval="1h",
            min_history_bars=0,
        ),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=store,
        alerts=alerts,  # type: ignore[arg-type]
    )
    return engine, alerts, venue, store


async def startup_with_foreign_order(client_order_id: str) -> list[str]:
    """Run `startup()` against a venue with one resting order under the given id (AC-L5)."""
    import tempfile
    from decimal import Decimal

    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams
    from starquant_shared.types import OrderAck, Side

    class _WithRestingOrder(FakeVenue):
        """`FakeVenue.open_orders` is a stub that always returns []; the reconcile reads that method."""

        resting: ClassVar[list[OrderAck]] = []

        async def open_orders(self, symbol: str | None = None) -> list[OrderAck]:
            self.calls.append("open_orders")
            return list(self.resting)

    tmp = Path(tempfile.mkdtemp())
    venue = _WithRestingOrder()
    venue.resting = [
        OrderAck(
            symbol="BTCUSDT",
            client_order_id=client_order_id,
            order_id="1",
            side=Side("BUY"),
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=0.0,
            reduce_only=False,
            raw={},
        )
    ]
    alerts = _RecordingAlerts()
    engine = LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=300,
            universe=("BTCUSDT", "ETHUSDT"),
            leverage=2,
            rebalance=RebalanceParams(),
            guards=GuardParams(),
            kill_switch_path=tmp / "KILL_SWITCH",
            strategy_weights={"tsmom": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
            dry_run=True,
        ),
        model=AlphaModel(
            entries=(StrategyEntry("tsmom", params=dict(TsmomParams().__dict__)),),
            portfolio=PortfolioParams(),
            interval="1h",
            min_history_bars=0,
        ),
        market=None,  # type: ignore[arg-type]
        venue=venue,
        clock=FakeClock(1_700_000_000_000),
        store=StateStore(tmp / "live"),
        alerts=alerts,  # type: ignore[arg-type]
    )
    await engine.startup()
    return alerts.sent


async def cycle_with_metrics(panel: Any, tmp_path: Any, *, rows: Any) -> tuple[dict[str, Any], Any]:
    """One real cycle with a metrics store wired, returning the cycle row and the store (DL-Q6)."""
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams
    from starquant_data.store import MetricsStore

    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    cursor = 400
    market = FakeMarketData(panel, cursor)

    class _Client:
        async def get(self, path: str, params: Any = None) -> Any:
            if isinstance(rows, Exception):
                raise rows
            return rows

    market.client = _Client()  # type: ignore[attr-defined]
    prices = {s: float(panel.close[s].iloc[cursor - 1]) for s in symbols}
    store = MetricsStore(Path(tmp_path) / "data", kind="metrics_snapshot")
    engine = LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=300,
            universe=tuple(symbols),
            leverage=2,
            rebalance=RebalanceParams(no_trade_band=0.002),
            guards=GuardParams(),
            kill_switch_path=Path(tmp_path) / "KILL_SWITCH",
            strategy_weights={"tsmom": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
            dry_run=True,
        ),
        model=AlphaModel(
            entries=(
                StrategyEntry(
                    "tsmom",
                    params=dict(TsmomParams(vol_window=100).__dict__)
                    | {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5], "entry_threshold": 0.05},
                ),
            ),
            portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
            interval="1h",
            min_history_bars=0,
        ),
        market=market,
        venue=FakeVenue(balance=10_000.0, prices=prices),
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=StateStore(Path(tmp_path) / "live"),
        alerts=_RecordingAlerts(),  # type: ignore[arg-type]
        metrics_store=store,
    )
    await engine.startup()
    row = await engine.run_cycle(market.bar_open_ms(cursor))
    return row, store


def engine_needing_metrics(tmp_path: Any, *, coverage_buckets: int) -> Any:
    """An engine whose one strategy declares `needs_metrics`, with a snapshot store of a given depth."""
    import pandas as pd

    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals import SIGNALS, get_signal
    from starquant_alpha.signals import register as register_signal
    from starquant_data.store import MetricsStore

    base = get_signal("tsmom")
    if "mined_needsmetrics" not in SIGNALS:
        register_signal(replace(base, id="mined_needsmetrics", needs_metrics=lambda params: True))

    root = Path(tmp_path)
    store = MetricsStore(root / "data", kind="metrics_snapshot")
    if coverage_buckets:
        for symbol in ("BTCUSDT", "ETHUSDT"):
            store.append(
                symbol,
                pd.DataFrame({"open_time": [i * 300_000 for i in range(coverage_buckets)], "symbol": symbol}),
            )
    return LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=720,
            universe=("BTCUSDT", "ETHUSDT"),
            leverage=2,
            rebalance=RebalanceParams(),
            guards=GuardParams(),
            kill_switch_path=root / "KILL_SWITCH",
            strategy_weights={"mined_needsmetrics": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
            dry_run=True,
        ),
        model=AlphaModel(
            entries=(StrategyEntry("mined_needsmetrics", params=dict(SIGNALS["mined_needsmetrics"].default_params)),),
            portfolio=PortfolioParams(),
            interval="1h",
            min_history_bars=0,
        ),
        market=None,  # type: ignore[arg-type]
        venue=FakeVenue(),
        clock=FakeClock(1_700_000_000_000),
        store=StateStore(root / "live"),
        alerts=_RecordingAlerts(),  # type: ignore[arg-type]
        metrics_store=store,
    )
