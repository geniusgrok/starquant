"""D-032: P&L from fills the loop did not place must not reach the series that judges the strategy.

On 2026-09-04 the operator flattened the whole book by hand.  The +26.30 realised P&L was attributed to
tsmom, which is right in economic terms - tsmom chose and held those positions - but it compressed a whole
holding period's unrealised P&L into one bar, and M-010 computes Sharpe from a per-bar income series, so
both mean and variance moved.  `external_flows` could not catch it: that only knows TRANSFER rows.

An income row names a `tradeId` and nothing else about provenance.  A userTrades row carries that id plus
the `orderId`, and every order the loop placed is in trades.jsonl.  That is the join this file tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.panel import Panel
from starquant_live.attribution import attribute, split_by_origin
from starquant_live.engine import LiveEngine
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices

HOST_NOW = 1_788_500_000_000
CONTRIB = {"tsmom": {"BTCUSDT": 1.0, "ETHUSDT": 1.0}}


def _income(symbol: str, kind: str, amount: str, trade_id: str | None, time: int = HOST_NOW) -> dict[str, Any]:
    row: dict[str, Any] = {"symbol": symbol, "incomeType": kind, "income": amount, "time": time}
    if trade_id is not None:
        row["tradeId"] = trade_id
    return row


# --- the split itself -------------------------------------------------------------------------------


def test_a_fill_the_loop_did_not_place_is_foreign() -> None:
    rows = [_income("BTCUSDT", "REALIZED_PNL", "26.30", "999"), _income("BTCUSDT", "COMMISSION", "-0.10", "111")]
    own, foreign = split_by_origin(rows, {"111"})
    assert [r["tradeId"] for r in own] == ["111"]
    assert [r["tradeId"] for r in foreign] == ["999"]


def test_a_row_with_no_trade_id_stays_with_the_book() -> None:
    """Funding carries no tradeId, and it accrues on a position regardless of who opened it."""
    own, foreign = split_by_origin([_income("BTCUSDT", "FUNDING_FEE", "-0.09", None)], set())
    assert len(own) == 1 and foreign == []


def test_foreign_pnl_is_kept_out_of_by_strategy_but_not_out_of_the_ledger() -> None:
    rows = [
        _income("BTCUSDT", "REALIZED_PNL", "26.2986", "999"),  # the operator's flatten
        _income("BTCUSDT", "COMMISSION", "-2.3184", "111"),  # the loop's own rebuild
        _income("BTCUSDT", "FUNDING_FEE", "-0.1753", None),
    ]
    result = attribute(rows, CONTRIB, {"tsmom": 1.0}, own_trade_ids={"111"})
    assert result["by_strategy"]["tsmom"] == pytest.approx(-2.3184 - 0.1753)
    assert result["total"] == pytest.approx(-2.4937)
    assert result["foreign"]["total"] == pytest.approx(26.2986)
    assert result["foreign"]["rows"] == 1
    assert result["foreign"]["reconciled"] is True
    # the money is still in the record, just not in the strategy's column
    assert result["foreign"]["by_symbol"]["BTCUSDT"]["REALIZED_PNL"] == pytest.approx(26.2986)


def test_without_a_reconciliation_everything_is_attributed_as_before() -> None:
    """A monitor that cannot run must not silently reclassify a cycle's P&L as somebody else's."""
    rows = [_income("BTCUSDT", "REALIZED_PNL", "26.2986", "999")]
    result = attribute(rows, CONTRIB, {"tsmom": 1.0})
    assert result["by_strategy"]["tsmom"] == pytest.approx(26.2986)
    assert result["foreign"] == {"by_symbol": {}, "total": 0.0, "rows": 0, "reconciled": False}


# --- the join, through the engine -------------------------------------------------------------------


class TradesVenue(FakeVenue):
    def __init__(self, *args: Any, fills: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fills = fills or []
        self.raise_on_user_trades = False

    def venue_time_ms(self) -> int:
        return HOST_NOW

    async def user_trades(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        if self.raise_on_user_trades:
            raise RuntimeError("userTrades unavailable")
        return [f for f in self.fills if start_ms <= int(f["time"]) <= end_ms]


@pytest.fixture
def panel(august_panel: Panel) -> Panel:
    return august_panel


def _engine(tmp_path: Path, venue: FakeVenue, panel: Panel) -> LiveEngine:
    return LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=FakeMarketData(panel, cursor=400),
        venue=venue,
        clock=FakeClock(HOST_NOW),
        store=StateStore(tmp_path / "live"),
    )


async def test_the_join_runs_income_tradeid_to_orderid_to_our_own_orders(panel: Panel, tmp_path: Path) -> None:
    fills = [
        {"id": 111, "orderId": 55, "symbol": "BTCUSDT", "time": HOST_NOW - 1_000},  # ours
        {"id": 999, "orderId": 77, "symbol": "BTCUSDT", "time": HOST_NOW - 1_000},  # the operator's
    ]
    venue = TradesVenue(balance=10_000.0, prices=_prices(panel, 400), fills=fills)
    engine = _engine(tmp_path, venue, panel)
    engine.store.append_trade({"symbol": "BTCUSDT", "order_id": "55", "status": "FILLED"})

    assert await engine._own_trade_ids(HOST_NOW - 3_600_000, HOST_NOW) == {"111"}


async def test_an_order_placed_this_run_is_recognised_before_the_log_is_re_read(panel: Panel, tmp_path: Path) -> None:
    venue = TradesVenue(balance=10_000.0, prices=_prices(panel, 400))
    engine = _engine(tmp_path, venue, panel)
    assert engine._placed_order_ids() == set()

    class _Report:
        ack = type("Ack", (), {"order_id": "88"})()

    engine._remember_order(_Report())  # type: ignore[arg-type]
    assert "88" in engine._placed_order_ids()


async def test_a_venue_with_no_user_trades_attributes_everything(panel: Panel, tmp_path: Path) -> None:
    engine = _engine(tmp_path, FakeVenue(balance=10_000.0, prices=_prices(panel, 400)), panel)
    assert await engine._own_trade_ids(0, HOST_NOW) is None


async def test_a_failing_user_trades_call_never_takes_the_cycle_down(panel: Panel, tmp_path: Path) -> None:
    venue = TradesVenue(balance=10_000.0, prices=_prices(panel, 400))
    venue.raise_on_user_trades = True
    assert await _engine(tmp_path, venue, panel)._own_trade_ids(0, HOST_NOW) is None


async def test_the_2026_09_04_flatten_no_longer_lands_in_the_strategy_series(panel: Panel, tmp_path: Path) -> None:
    """End to end: the operator's realised P&L is reported, and tsmom's column carries only its own costs."""
    venue = TradesVenue(
        balance=10_000.0,
        prices=_prices(panel, 400),
        fills=[
            {"id": 111, "orderId": 55, "symbol": "BTCUSDT", "time": HOST_NOW - 1_000},
            {"id": 999, "orderId": 77, "symbol": "BTCUSDT", "time": HOST_NOW - 1_000},
        ],
    )
    engine = _engine(tmp_path, venue, panel)
    engine.store.append_trade({"symbol": "BTCUSDT", "order_id": "55", "status": "FILLED"})
    engine.state.last_income_ms = HOST_NOW - 3_600_000
    engine.state.last_contributions = CONTRIB
    venue.income_log = [
        _income("BTCUSDT", "REALIZED_PNL", "26.2986", "999", HOST_NOW - 1_000),
        _income("BTCUSDT", "COMMISSION", "-2.3184", "111", HOST_NOW - 1_000),
    ]

    await engine._ingest_income(HOST_NOW, 10_000.0)

    written = engine.store.read_jsonl(engine.store.attribution_path)[-1]
    assert written["by_strategy"]["tsmom"] == pytest.approx(-2.3184)
    assert written["foreign"]["total"] == pytest.approx(26.2986)
    assert written["foreign"]["rows"] == 1
