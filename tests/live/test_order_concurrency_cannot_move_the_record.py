"""Serial order sending inflates the very slippage it is measured by (2026-09-13 perf item P3).

`execute_order` sleeps 1.0s up to `poll_attempts` times whenever an ack is not terminal, and the loop
sends one order at a time, so the LAST order of a bar can leave tens of seconds after the first.  The
further from the decision the fill is, the further the price is from `decision_close` - and
`decision_close` is exactly what M-Q08 measures slippage against, recorded on every trade row
(`engine._record_fill`).  So the sending strategy pushes the number that judges the sending strategy.

`order_concurrency` is the lever, and it is off (1) by default.  Two properties have to hold before it
can ever be turned on, and they are what this module pins:

* at 1 the path is the serial loop it has always been - same sends, same order, same rows;
* above 1 the ARRIVAL order changes and the RECORD does not.  `store.append_trade` and
  `record["orders"]` are the append-only trade log and the cycle row that every later reader
  reconstructs a bar from, and neither may follow whichever venue answered first.

Double-sending is not among the risks: `client_order_id` is derived from the bar and `execute_order`
queries before it submits (D-032 / T-L01).  What concurrency changes is latency and arrival order,
which is why those two are the things under test.

Two rules were added on 2026-09-25 and hold at any concurrency: reductions are sent before anything
that adds risk, and one order raising no longer stops the orders behind it (the last two tests).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.rebalancer import PlannedOrder, client_order_id
from starquant_live.state import StateStore
from starquant_shared.types import OrderAck, OrderRequest, Side
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices


class _StaggeredVenue(FakeVenue):
    """Answers in an order of its own choosing, so "arrival order" is a real variable and not luck."""

    def __init__(self, *, yields: dict[str, int] | None = None, fail_symbol: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.yields = dict(yields or {})
        self.fail_symbol = fail_symbol
        self.completions: list[str] = []

    async def place_order(self, request: OrderRequest) -> OrderAck:
        for _ in range(self.yields.get(request.symbol, 0)):
            await asyncio.sleep(0)
        if request.symbol == self.fail_symbol:
            raise RuntimeError("the transport went away mid-batch")
        ack = await super().place_order(request)
        self.completions.append(request.symbol)
        return ack


async def _cycle(
    august_panel: Panel,
    directory: Path,
    *,
    concurrency: int,
    yields: dict[str, int] | None = None,
    fail_symbol: str | None = None,
) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = _StaggeredVenue(
        balance=10_000.0, prices=_prices(august_panel, cursor), yields=yields, fail_symbol=fail_symbol
    )
    store = StateStore(directory / "live")
    engine = LiveEngine(
        _config(directory),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=store,
        order_concurrency=concurrency,
    )
    await engine.startup()
    record: dict[str, Any] = {"orders": []}
    failure: BaseException | None = None
    try:
        record = await engine.run_cycle(market.bar_open_ms(cursor - 1))
    except BaseException as exc:  # only the injected one; re-raised by the caller that asked for it
        failure = exc
    return {
        "record": record,
        "venue": venue,
        "store": store,
        "failure": failure,
        "planned": [order["symbol"] for order in record["orders"]],
        "traded": [row["symbol"] for row in store.read_jsonl(store.trades_path)],
    }


def _comparable(record: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Everything about an order row that is not a clock reading."""
    return [
        (o["symbol"], o["side"], o["quantity"], o["status"], o["reduce_only"], o["client_order_id"])
        for o in record["orders"]
    ]


async def test_the_default_path_is_the_serial_loop(august_panel: Panel, tmp_path: Path) -> None:
    """Concurrency 1 sends one at a time: the venue answers in exactly the planned order."""
    run = await _cycle(august_panel, tmp_path, concurrency=1)

    assert len(run["planned"]) >= 2, "the fixture needs more than one order for any of this to mean anything"
    assert run["venue"].completions == run["planned"]
    assert run["traded"] == run["planned"]


async def test_concurrency_reorders_the_venue_and_not_the_record(august_panel: Panel, tmp_path: Path) -> None:
    """The arrival order is deliberately reversed.  The trade log and the cycle row do not notice."""
    serial = await _cycle(august_panel, tmp_path / "serial", concurrency=1)
    planned = serial["planned"]
    # The first order planned yields the most, so it is the last to come back.
    reversing = {symbol: len(planned) - 1 - index for index, symbol in enumerate(planned)}

    parallel = await _cycle(august_panel, tmp_path / "parallel", concurrency=4, yields=reversing)

    assert parallel["venue"].completions == list(reversed(planned)), "the fixture really did overlap them"
    assert parallel["planned"] == planned, "the cycle row stays in planned order"
    assert parallel["traded"] == planned, "and so does the append-only trade log"


async def test_the_two_paths_produce_the_same_bar(august_panel: Panel, tmp_path: Path) -> None:
    """Same orders, same statuses, same book.  Concurrency is a latency change and nothing else."""
    serial = await _cycle(august_panel, tmp_path / "serial", concurrency=1)
    reversing = {symbol: len(serial["planned"]) - 1 - index for index, symbol in enumerate(serial["planned"])}
    parallel = await _cycle(august_panel, tmp_path / "parallel", concurrency=4, yields=reversing)

    assert _comparable(parallel["record"]) == _comparable(serial["record"])
    assert parallel["venue"].qty == serial["venue"].qty
    assert parallel["record"]["targets"] == serial["record"]["targets"]
    assert parallel["record"]["summary"] == serial["record"]["summary"]


async def test_one_order_blowing_up_still_records_the_ones_that_came_back(august_panel: Panel, tmp_path: Path) -> None:
    """What the serial loop does too: everything already sent is written down, then the failure propagates.

    The batch is gathered with `return_exceptions=True` for this: without it the first raise reaches
    the caller while the other sends are still in flight, and orders that DID reach the venue would
    finish as orphans outside the cycle that owns them - fills with no row anywhere.
    """
    serial = await _cycle(august_panel, tmp_path / "serial", concurrency=1)
    planned = serial["planned"]
    victim = planned[0]
    reversing = {symbol: len(planned) - 1 - index for index, symbol in enumerate(planned)}

    run = await _cycle(august_panel, tmp_path / "parallel", concurrency=4, yields=reversing, fail_symbol=victim)

    assert isinstance(run["failure"], RuntimeError), "the cycle fails, as it does today"
    assert run["traded"] == [symbol for symbol in planned if symbol != victim]
    assert run["venue"].completions == list(reversed(run["traded"])), "they really were in flight together"


async def test_the_serial_loop_no_longer_stops_at_the_first_order_that_raises(
    august_panel: Panel, tmp_path: Path
) -> None:
    """2026-09-25: the serial path used to abort the batch at its first raise, so every order behind it -
    exits included - waited for the next bar.  It now does what the concurrent path above always did."""
    planned = (await _cycle(august_panel, tmp_path / "clean", concurrency=1))["planned"]
    victim = planned[0]

    run = await _cycle(august_panel, tmp_path / "failing", concurrency=1, fail_symbol=victim)

    assert isinstance(run["failure"], RuntimeError), "the cycle still fails, and still says why"
    assert run["traded"] == [symbol for symbol in planned if symbol != victim]
    assert run["venue"].completions == run["traded"], "one at a time, in planned order"


def _order(symbol: str, side: Side, quantity: str, *, reduce_only: bool) -> PlannedOrder:
    return PlannedOrder(
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        reduce_only=reduce_only,
        client_order_id=client_order_id("bd", symbol, 1_757_000_000_000),
        target_weight=0.0,
        current_notional=0.0,
        target_notional=0.0,
        price=0.0,
    )


async def test_reductions_go_first_and_a_failure_before_them_cannot_hold_them_back(
    august_panel: Panel, tmp_path: Path
) -> None:
    """Planned order interleaves two openings with two reductions, and the first opening raises.

    Reductions are sent first - they free margin, and they are what a bar can least afford to lose -
    so the failure lands after them, and the opening behind it is still sent.
    """
    venue = _StaggeredVenue(fail_symbol="BTCUSDT")
    venue.qty = {"ETHUSDT": 1.0, "BNBUSDT": 10.0}
    venue.entry = {symbol: venue.prices[symbol] for symbol in venue.qty}
    market = FakeMarketData(august_panel, 400)
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(400) + 5_000),
        store=StateStore(tmp_path / "live"),
    )
    planned = [
        _order("BTCUSDT", Side.BUY, "0.010", reduce_only=False),
        _order("ETHUSDT", Side.SELL, "0.500", reduce_only=True),
        _order("SOLUSDT", Side.BUY, "10", reduce_only=False),
        _order("BNBUSDT", Side.SELL, "5.00", reduce_only=True),
    ]
    record: dict[str, Any] = {"orders": []}

    with pytest.raises(RuntimeError):
        await engine._execute_orders(planned, record, bar_open_ms=1_757_000_000_000, decision_closes={})

    assert venue.completions == ["ETHUSDT", "BNBUSDT", "SOLUSDT"]
    assert [row["symbol"] for row in record["orders"]] == ["ETHUSDT", "BNBUSDT", "SOLUSDT"]
    assert venue.qty["ETHUSDT"] == pytest.approx(0.5) and venue.qty["BNBUSDT"] == pytest.approx(5.0)
