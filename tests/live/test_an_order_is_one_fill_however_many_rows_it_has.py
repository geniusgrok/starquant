"""一笔 venue 订单只算一次：重启重跑同一根 bar 时写下的「already submitted for this bar」行不是第二笔成交。

`execute_order` 先查后下。重启重跑一根已经下过单的 bar，它拿到旧单的 ack，却套在这一轮的新计划上返回：
方向、数量、计划价是新的，`executed_qty`、`avg_price`、`order_id` 是旧单的。`_record_fill` 把它写成一行。
真实例子是 2026-09-03 的 order 869468534：13:00:15 那行是卖出 32,080 张 1000PEPEUSDT，13:37:34 那行写成
买入 33,010 张，成交数量还是那 32,080。

读两次，成交就算了两遍；按第二行的方向记，滑点的符号还是反的。这里钉住每个读者都只读第一行：
M-Q08 的滑点（`risk_budget.slippage_bps`）与它的按周读数（`execution_fidelity.slippage_by_week`）、
M-Q08 的实盘换手（`execution_fidelity.live_turnover`）、逐单 TCA（`report_execution.per_order_tca`）、
日报的订单状态计数与成交额（`reports.daily_payload`），以及 M-Q03 的成交迟到（`report_execution.restart_cost`）。

fixture 是 `trades.jsonl` 2026-09-25 那份的第 18 行与第 20 行，逐字照抄；周期行取 `cycles.jsonl`
同一根 bar 的两行，只抄这些读者读的字段。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from starquant_live.execution_fidelity import live_turnover, slippage_by_week
from starquant_live.report_execution import per_order_tca, restart_cost
from starquant_live.reports import daily_payload
from starquant_live.risk_budget import RiskBudgetParams, one_row_per_order, slippage_bps
from starquant_live.scheduler import late_seconds
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
BAR = 1_788_436_800_000  # 2026-09-03T12:00Z

FIRST: dict[str, Any] = {
    "at": "2026-09-03T13:00:15+00:00",
    "avg_price": 0.0035042,
    "bar_open_ms": 1788436800000,
    "client_order_id": "bd-1788436800000-1000PEPEUSDT",
    "current_notional": 151.4067281,
    "error": "",
    "executed_qty": "32080",
    "order_id": "869468534",
    "price": 0.0034759,
    "quantity": "32080",
    "reduce_only": True,
    "side": "SELL",
    "status": "FILLED",
    "symbol": "1000PEPEUSDT",
    "target_notional": 39.898107519377206,
    "target_weight": 0.003710762774283222,
    "venue_status": "FILLED",
}
AGAIN: dict[str, Any] = {
    "at": "2026-09-03T13:37:34+00:00",
    "avg_price": 0.0035042,
    "bar_open_ms": 1788436800000,
    "client_order_id": "bd-1788436800000-1000PEPEUSDT",
    "current_notional": 40.073762949999995,
    "error": "already submitted for this bar",
    "executed_qty": "32080",
    "note": "",
    "order_id": "869468534",
    "price": 0.00349105,
    "quantity": "33010",
    "reduce_only": False,
    "side": "BUY",
    "status": "FILLED",
    "symbol": "1000PEPEUSDT",
    "target_notional": 155.3159221798189,
    "target_weight": 0.01442436992865853,
    "venue_status": "FILLED",
}
# Both rows predate `decision_close` (2026-09-08).  Every row since carries it: the decision bar's close,
# here 1000PEPEUSDT's archived 12:00Z close.
DECISION_CLOSE = 0.003504
# The two cycle rows of that bar - the one that placed the order and the restart that listed it again.
CYCLES = (
    {"at": "2026-09-03T13:00:15+00:00", "bar_open_ms": BAR, "as_of_ms": BAR, "equity": 10751.99627308},
    {"at": "2026-09-03T13:37:37+00:00", "bar_open_ms": BAR, "as_of_ms": BAR, "equity": 10767.60530602},
)


def _referenced(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "decision_close": DECISION_CLOSE}


def test_the_first_row_is_the_one_kept() -> None:
    assert one_row_per_order([FIRST, AGAIN]) == [FIRST]
    unacknowledged = {**AGAIN, "order_id": None, "executed_qty": None, "avg_price": None, "status": "REJECTED"}
    assert one_row_per_order([unacknowledged, unacknowledged]) == [unacknowledged] * 2, "no id: nothing to match"
    elsewhere = {**AGAIN, "symbol": "BTCUSDT"}
    assert one_row_per_order([FIRST, elsewhere]) == [FIRST, elsewhere], "ids are compared within a symbol"


def test_mq08_counts_the_rows_as_written_as_one_fill_without_a_reference() -> None:
    assert slippage_bps([FIRST, AGAIN], RiskBudgetParams(), latest_ms=BAR)["without_reference"] == 1


def test_mq08_reads_one_sell_where_the_log_has_a_sell_and_a_buy() -> None:
    reading = slippage_bps([_referenced(FIRST), _referenced(AGAIN)], RiskBudgetParams(), latest_ms=BAR)
    sell = -(0.0035042 - DECISION_CLOSE) / DECISION_CLOSE * 1e4  # sold above the close: a negative cost
    assert reading["combined"]["fills"] == 1
    assert reading["combined"]["value"] == pytest.approx(sell, rel=1e-12)
    [week] = slippage_by_week(list(CYCLES), [_referenced(FIRST), _referenced(AGAIN)])
    assert week["combined"]["fills"] == 1 and week["combined"]["value"] == pytest.approx(sell, rel=1e-12)


def test_the_live_turnover_counts_the_order_once() -> None:
    live = live_turnover(CYCLES[:1], [FIRST, AGAIN], since_ms=BAR, until_ms=BAR)
    assert live["by_bar"] == {BAR: pytest.approx(32080 * 0.0035042 / 10751.99627308, rel=1e-12)}


def test_tca_reads_the_order_once_and_still_agrees_with_mq08(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")
    for row in CYCLES:
        store.append_cycle(row)
    store.append_trade(_referenced(FIRST))
    store.append_trade(_referenced(AGAIN))
    block = per_order_tca(store, data_root=tmp_path / "no-archive", costs=load_yaml(ROOT / "config/costs.yaml"))
    sell = -(0.0035042 - DECISION_CLOSE) / DECISION_CLOSE * 1e4
    assert block["fills"] == 1 and block["post_trade"]["slippage"]["value"] == pytest.approx(sell, rel=1e-12)
    assert block["reconciliation"]["combined"]["agrees"] is True


def test_the_daily_report_counts_the_order_and_its_notional_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-09-03's `orders` and `traded_notional`: one FILLED order of 112.41 USDT, not two."""
    monkeypatch.chdir(ROOT)  # the TCA block reads `config/costs.yaml` from the working directory
    store = StateStore(tmp_path / "live")
    for row in CYCLES:
        store.append_cycle(row)
    store.append_trade(FIRST)
    store.append_trade(AGAIN)
    payload = daily_payload(store, "2026-09-03", {}, data_root=tmp_path / "no-archive")
    assert payload["orders"] == {"FILLED": 1}
    assert payload["traded_notional"] == pytest.approx(32080 * 0.0035042, rel=1e-12)


def test_restart_cost_times_the_fill_and_not_the_rerun_that_listed_it_again() -> None:
    """M-Q03's fill half.  `late_seconds` arrived on 2026-09-07, after these rows, so it is added the way
    `_record_fill` writes it: when the row is written.  The repeat would read 2,254 s late only because
    the restart wrote it then."""

    def timed(row: dict[str, Any]) -> dict[str, Any]:
        written = int(datetime.fromisoformat(row["at"]).timestamp() * 1000)
        return {**row, "late_seconds": late_seconds(BAR, 3_600_000, at_ms=written)}

    first, again = timed(FIRST), timed(AGAIN)
    assert (first["late_seconds"], again["late_seconds"]) == (15.0, 2254.0)
    block = restart_cost(list(CYCLES), [first, again])
    assert block["fills_measured"] == 1 and block["worst_late_fill_seconds"] == 15.0
