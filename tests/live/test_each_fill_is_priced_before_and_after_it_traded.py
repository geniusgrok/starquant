"""清单 #10.9 / #10.10：每笔成交的事前成本估计摆在它的事后成本旁边。

`report_execution.per_order_tca` 只报告，不告警。这个文件钉住会静默坏掉的事：

一、事前估计只用下单那一刻已经收盘的 bar。决策 bar 取周期行的 `as_of_ms`，不取成交行的 `bar_open_ms`：
    后者是主机时钟的标签，D-025 允许它与数据差整根 bar。`decision_close` 对不上归档那根 bar 的收盘价时，
    不拆也不估，按原因计数。
二、事前估计照它的主人算。参与率是 `LiveEngine._liquidity` 的小时成交额，逐位相同；冲击是
    `impact_costs` 对同一笔单收的钱，σ 取开盘到收盘；参数经 `impact_model` 从成本文件来。
三、事后滑点与 M-Q08 是同一批成交、同一套算术。全书与主书两个读数都要对得上；对不上时块里要说差在哪。
四、预测只跟「成交」那一段比。`slippage_bps` 按下一根开盘价定义，跳空不在预测里。
五、归档定不了价的成交照样计入实际滑点。它只是不拆、不估，并按原因计数；一个标的的归档读不出，
    只影响这个标的。
六、手续费另列，读 attribution 入账的数。一个 (bar, symbol) 对不上唯一一行就不读；入账窗口里有
    `live flatten` 成交的也不读。
七、这一块坏了，日报的其余部分与告警一字不变。

fixture 尽量是真实行。第一条测试的成交是 `trades.jsonl` 2026-09-24 那份的第 256 行（16:00:28Z，
AKEUSDT BUY），手续费是 `attribution.jsonl` 第 100 行。决策 bar 与前后各一根取 AKEUSDT 归档的原值。
时钟偏移那条用 2026-09-04 主机慢一小时时的真实周期行与成交行，flatten 用 2026-09-13 那次的真实行。
更早的历史是合成的，只用来让 720 根窗口的 σ 与 ADV 有数可算；合成 bar 的开盘价不等于上一根收盘价，
这样开盘到收盘与收盘到收盘两种 σ 在这里分得开。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import ImpactModel, asset_returns, impact_costs
from starquant_alpha.panel import Panel
from starquant_data.store import KlineStore
from starquant_live import report_execution
from starquant_live.composition import impact_model
from starquant_live.engine import LiveEngine
from starquant_live.report_common import LIQUIDITY_WINDOW_BARS
from starquant_live.report_execution import TCA_PARTICIPATION_EDGES, _by_participation, per_order_tca, tca_lines
from starquant_live.reports import daily_alerts, daily_markdown, daily_payload
from starquant_live.risk_budget import RiskBudgetParams, books_by_bar, slippage_bps
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3_600_000
BAR = 1_790_262_000_000  # 2026-09-24T15:00Z, the decision bar of the real fill below
COSTS = load_yaml(ROOT / "config/costs.yaml")

# `.starquant/live/trades.jsonl`, line 256 of the 2026-09-24 copy: every field as written.
REAL_FILL: dict[str, Any] = {
    "at": "2026-09-24T16:00:28+00:00",
    "avg_price": 0.044624,
    "bar_open_ms": 1790262000000,
    "client_order_id": "bd-1790262000000-AKEUSDT",
    "current_notional": 0.0,
    "decision_close": 0.044588,
    "error": "",
    "executed_qty": "2943",
    "late_seconds": 28.192,
    "note": "",
    "order_id": "322947312",
    "price": 0.04458192,
    "quantity": "2943",
    "reduce_only": False,
    "side": "BUY",
    "status": "FILLED",
    "symbol": "AKEUSDT",
    "target_notional": 131.23442731096677,
    "target_weight": 0.010033114803632767,
    "venue_status": "FILLED",
}
# `.starquant/live/attribution.jsonl`, line 100: the next cycle's income window, keyed by the bar that traded.
REAL_INCOME: dict[str, Any] = {
    "at": "2026-09-24T17:00:25+00:00",
    "bar_open_ms": 1790262000000,
    "basis": "net_exposure",
    "by_strategy": {"tsmom": -0.06566421},
    "by_symbol": {
        "AKEUSDT": {
            "COMMISSION": -0.06566421,
            "FUNDING_FEE": 0.0,
            "INSURANCE_CLEAR": 0.0,
            "REALIZED_PNL": 0.0,
            "total": -0.06566421,
        }
    },
    "cancelled": {},
    "external_flows": {"by_type": {}, "rows": 0, "total": 0.0},
    "foreign": {"by_symbol": {}, "reconciled": True, "rows": 0, "total": 0},
    "since_ms": 1790265625997,
    "total": -0.06566421,
    "unattributed": 0.0,
    "until_ms": 1790269226956,
}
# AKEUSDT's archive, 14:00 to 16:00 on 2026-09-24: the decision bar is the middle one.
REAL_BARS = [
    (1790258400000, 0.043546, 0.045875, 0.043476, 0.045525, 202807875.0, 1790261999999, 9075448.32902, 238455),
    (1790262000000, 0.045526, 0.045986, 0.043829, 0.044588, 116425207.0, 1790265599999, 5242097.489977, 155373),
    (1790265600000, 0.044591, 0.044728, 0.04187, 0.042107, 138959339.0, 1790269199999, 6004885.742603, 146125),
]
PLANNED = 2943 * 0.04458192  # quantity x price: what the order was sized at before it went out

# `.starquant/live/trades.jsonl`, line 172 of the 2026-09-25 copy: the AKEUSDT fill of the 2026-09-13T20:37Z
# `live flatten`, every field as written.  No bar; `at` is when it was written, on the host's clock.
REAL_FLATTEN: dict[str, Any] = {
    "at": "2026-09-13T20:37:51+00:00",
    "avg_price": 0.015085,
    "bar_open_ms": None,
    "client_order_id": "bdflat-1789331867692-AKEUSDT",
    "current_notional": 148.418607,
    "error": "",
    "executed_qty": "9831",
    "flatten": True,
    "note": "",
    "order_id": "317210839",
    "price": 0.015097,
    "quantity": "9831",
    "reduce_only": True,
    "side": "SELL",
    "status": "FILLED",
    "symbol": "AKEUSDT",
    "target_notional": 0.0,
    "target_weight": 0.0,
    "venue_status": "FILLED",
}

# 2026-09-04, the host an hour behind the venue (D-025).  `cycles.jsonl` line 25 and `trades.jsonl` line 41
# of the 2026-09-25 copy, with the fields this block reads copied verbatim: the row's `bar_open_ms` is the
# host's label (01:00Z) and its `as_of_ms` the klines' bar (02:00Z), 3,600,000 ms apart as on 21 rows
# that day.  The order is the one the row lists and the fill row repeats.
OFFSET_ORDER: dict[str, Any] = {
    "avg_price": 0.014501,
    "client_order_id": "bd-1788483600000-AKEUSDT",
    "current_notional": 0.0,
    "error": "",
    "executed_qty": "5155",
    "note": "",
    "order_id": "312452648",
    "price": 0.01448838,
    "quantity": "5155",
    "reduce_only": False,
    "side": "BUY",
    "status": "FILLED",
    "symbol": "AKEUSDT",
    "target_notional": 74.69197672151056,
    "target_weight": 0.006941099999987538,
    "venue_status": "FILLED",
}
OFFSET_CYCLE: dict[str, Any] = {
    "as_of_ms": 1788487200000,
    "at": "2026-09-04T02:30:37+00:00",
    "bar": "2026-09-04T01:00:00+00:00",
    "bar_open_ms": 1788483600000,
    "clock": {"beyond_tolerance": True, "skew_ms": 3611932.5},
    "dry_run": False,
    "equity": 10760.82706223,
    "orders": [OFFSET_ORDER],
    "skip": False,
}
# The row predates `decision_close` (2026-09-08), so it is added as every row since carries it: the close
# of the last bar the loop read (`latest_closes`), which is the `as_of_ms` bar's.
OFFSET_FILL: dict[str, Any] = {
    "at": "2026-09-04T02:30:37+00:00",
    **OFFSET_ORDER,
    "bar_open_ms": 1788483600000,
    "decision_close": 0.014549,
}
# AKEUSDT's archive, 00:00 to 03:00 on 2026-09-04: the host's label is the second bar, the data bar the third.
OFFSET_BARS = [
    (1788480000000, 0.014901, 0.015192, 0.014705, 0.014855, 242817335.0, 1788483599999, 3622877.568762, 95169),
    (1788483600000, 0.014857, 0.01505, 0.014012, 0.014209, 270021946.0, 1788487199999, 3965626.6300449, 99482),
    (1788487200000, 0.014208, 0.014962, 0.0142, 0.014549, 328020880.0, 1788490799999, 4777476.9194211, 119287),
    (1788490800000, 0.014548, 0.014838, 0.014345, 0.01479, 167761108.0, 1788494399999, 2441777.8738117, 65174),
]

_ORDER_IDS = itertools.count(322947313)  # the synthetic fills' own venue ids: one order, one id


def _archive(
    root: Path,
    *,
    symbol: str = "AKEUSDT",
    history: int = 800,
    real: Sequence[tuple[Any, ...]] = REAL_BARS,
    after: list[tuple[Any, ...]] | None = None,
) -> None:
    """Synthetic history up to the real bars, then the real bars, then whatever `after` adds.

    Each synthetic bar opens away from the previous close, as the archive's bars do, so open-to-close and
    close-to-close returns are different series here and a sigma read on the wrong one shows.
    """
    rng = np.random.default_rng(7)
    first = real[0][0] - history * HOUR
    closes = 0.04 * np.cumprod(1.0 + rng.normal(0.0, 0.01, history))
    opens = np.concatenate(([closes[0]], closes[:-1])) * (1.0 + rng.normal(0.0, 0.004, history))
    volumes = 5e6 * (1.0 + 0.5 * np.sin(np.arange(history) / 10.0))
    synthetic = [
        (first + i * HOUR, o, max(o, c), min(o, c), c, v / c, first + (i + 1) * HOUR - 1, v, 100)
        for i, (o, c, v) in enumerate(zip(opens, closes, volumes, strict=True))
    ]
    rows = [(*row, 0.0, 0.0) for row in [*synthetic, *real, *(after or [])]]
    frame = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
        ],
    )
    KlineStore(root).append(symbol, "1h", frame)


def _store(root: Path, trades: Sequence[dict[str, Any]], income: Sequence[dict[str, Any]] = ()) -> StateStore:
    store = StateStore(root / "live")
    for i in range(3):
        bar = BAR - (2 - i) * HOUR
        store.append_cycle({"bar_open_ms": bar, "equity": 13_000.0, "construction": "c", "registry": "r"})
    for trade in trades:
        store.append_trade(trade)
    for row in income:
        store.append_attribution(row)
    return store


def test_a_real_fill_is_split_at_the_next_open_and_priced_from_what_had_closed(tmp_path: Path) -> None:
    _archive(tmp_path / "archive")
    store = _store(tmp_path, [REAL_FILL], [REAL_INCOME])
    block = per_order_tca(store, RiskBudgetParams(), data_root=tmp_path / "archive", costs=COSTS)

    reference, filled = 0.044588, 0.044624
    slippage = (filled - reference) / reference * 1e4  # a BUY above the decision close costs
    gap = (0.044591 - reference) / reference * 1e4  # the next bar's archived open
    post = block["post_trade"]
    assert post["slippage"]["value"] == pytest.approx(slippage, rel=1e-12)
    assert post["gap"]["value"] == pytest.approx(gap, rel=1e-12)
    assert post["fill"]["value"] == pytest.approx(slippage - gap, rel=1e-12)
    assert post["gap"]["value"] + post["fill"]["value"] == pytest.approx(post["split_slippage"]["value"], abs=1e-12)
    assert post["late_seconds_median"] == pytest.approx(28.192)

    # The estimate, computed the way `impact_costs` computes it for `run_backtest` - pandas rolling windows
    # over the whole series, sigma on open-to-close returns - read at the decision bar.  Independent of the
    # slicing the reading does, which is the point of computing it twice.
    frame = KlineStore(tmp_path / "archive").load("AKEUSDT", "1h").set_index("open_time")
    returns = frame["close"] / frame["open"] - 1.0
    sigma = returns.rolling(720, min_periods=180).std().loc[BAR] * math.sqrt(24)
    adv = frame["quote_volume"].rolling(720, min_periods=1).mean().loc[BAR] * 24
    hourly = frame["quote_volume"].rolling(LIQUIDITY_WINDOW_BARS).mean().loc[BAR]
    impact = 1.0 * sigma * math.sqrt(PLANNED / adv) * 1e4
    pre = block["pre_trade"]
    assert pre["impact"]["value"] == pytest.approx(impact, rel=1e-9)
    assert pre["predicted"]["value"] == pytest.approx(2.0 + impact, rel=1e-9)
    assert pre["participation"]["median"] == pytest.approx(PLANNED / hourly, rel=1e-12)
    # The prediction against the fill part, which starts at the open `slippage_bps` is defined from.
    assert block["predicted_minus_actual"]["value"] == pytest.approx(2.0 + impact - (slippage - gap), rel=1e-9)
    assert pre["unestimated"] == {} and post["unsplit"] == {}

    # 0.06566421 USDT on 131.33 USDT: the name's booked 5.0 bps, not a model number.
    assert post["fee"]["booked"]["value"] == pytest.approx(0.06566421 / (filled * 2943) * 1e4, rel=1e-12)
    assert post["fee"]["booked"]["value"] == pytest.approx(5.0, abs=1e-3)
    assert post["fee"]["model_bps"] == 5.0

    recon = block["reconciliation"]["combined"]
    assert recon["agrees"] is True and recon["m_q08_fills"] == 1
    assert recon["difference"] == pytest.approx(0.0, abs=1e-9)


def test_the_estimate_reads_nothing_after_the_decision_bar(tmp_path: Path) -> None:
    """Rewrite every bar after the decision bar: the estimate may not move, and the split must."""
    _archive(tmp_path / "as_traded")
    later = [(BAR + 2 * HOUR, 9.9, 9.9, 9.9, 9.9, 1.0, BAR + 3 * HOUR - 1, 1e12, 1)]
    _archive(tmp_path / "rewritten", after=later)
    rewritten = KlineStore(tmp_path / "rewritten").load("AKEUSDT", "1h")
    rewritten.loc[rewritten["open_time"] == BAR + HOUR, ["open", "close", "quote_volume"]] = [0.05, 0.05, 1e12]
    KlineStore(tmp_path / "rewritten").append("AKEUSDT", "1h", rewritten)

    store = _store(tmp_path, [REAL_FILL], [REAL_INCOME])
    before = per_order_tca(store, data_root=tmp_path / "as_traded", costs=COSTS)
    after = per_order_tca(store, data_root=tmp_path / "rewritten", costs=COSTS)

    assert after["pre_trade"] == before["pre_trade"], "the estimate saw a bar the order could not have"
    assert after["post_trade"]["gap"]["value"] != before["post_trade"]["gap"]["value"]
    # The error follows the fill part, which starts at the next open - so it moves with the split, not the estimate.
    for block in (before, after):
        error = block["pre_trade"]["predicted"]["value"] - block["post_trade"]["fill"]["value"]
        assert block["predicted_minus_actual"]["value"] == pytest.approx(error, rel=1e-12)


def _offset_store(root: Path, cycle: dict[str, Any], fill: dict[str, Any]) -> StateStore:
    store = StateStore(root / "live")
    store.append_cycle(cycle)
    store.append_trade(fill)
    return store


def test_a_host_clock_offset_moves_the_label_and_not_the_decision_bar(tmp_path: Path) -> None:
    """D-025: the bar an order was decided on is the cycle row's `as_of_ms`, whatever the host called it.

    The record's own case is the host an hour BEHIND: read at its label, the gap would run from the
    decision bar's own open (-234 bps) instead of the next one.  The other direction has not happened on
    the record and is the dangerous one: a host an hour AHEAD labels the order with the bar it traded in,
    which had not closed, and the estimate would read it.
    """
    root = tmp_path / "archive"
    _archive(root, real=OFFSET_BARS)
    data_bar, ahead_label = OFFSET_CYCLE["as_of_ms"], OFFSET_CYCLE["as_of_ms"] + HOUR
    behind = per_order_tca(_offset_store(tmp_path / "behind", OFFSET_CYCLE, OFFSET_FILL), data_root=root, costs=COSTS)
    right = per_order_tca(
        _offset_store(
            tmp_path / "right",
            {**OFFSET_CYCLE, "bar_open_ms": data_bar, "bar": "2026-09-04T02:00:00+00:00"},
            {**OFFSET_FILL, "bar_open_ms": data_bar, "client_order_id": f"bd-{data_bar}-AKEUSDT"},
        ),
        data_root=root,
        costs=COSTS,
    )
    ahead_rows = (
        {**OFFSET_CYCLE, "bar_open_ms": ahead_label, "bar": "2026-09-04T03:00:00+00:00"},
        {**OFFSET_FILL, "bar_open_ms": ahead_label, "client_order_id": f"bd-{ahead_label}-AKEUSDT"},
    )
    ahead = per_order_tca(_offset_store(tmp_path / "ahead", *ahead_rows), data_root=root, costs=COSTS)

    gap = (0.014548 - 0.014549) / 0.014549 * 1e4  # the 03:00Z open against the 02:00Z close: -0.69 bps
    for block in (behind, ahead):
        assert block["pre_trade"] == right["pre_trade"]
        assert block["post_trade"]["gap"] == right["post_trade"]["gap"]
        assert block["post_trade"]["gap"]["value"] == pytest.approx(gap, rel=1e-12)
        assert block["post_trade"]["unsplit"] == {} and block["pre_trade"]["unestimated"] == {}

    # The bar a host an hour ahead names had not closed when the order went out: rewriting it moves nothing.
    _archive(tmp_path / "rewritten", real=OFFSET_BARS)
    rewritten = KlineStore(tmp_path / "rewritten").load("AKEUSDT", "1h")
    rewritten.loc[rewritten["open_time"] == ahead_label, ["close", "quote_volume"]] = [0.02, 1e12]
    KlineStore(tmp_path / "rewritten").append("AKEUSDT", "1h", rewritten)
    moved = per_order_tca(_offset_store(tmp_path / "moved", *ahead_rows), data_root=tmp_path / "rewritten", costs=COSTS)
    assert moved["pre_trade"] == ahead["pre_trade"], "the estimate read a bar that had not closed"


def test_a_decision_close_the_archive_does_not_hold_is_neither_split_nor_estimated(tmp_path: Path) -> None:
    """An order no traded cycle lists keeps the host's label; here the label is an hour off, and the check says so."""
    root = tmp_path / "archive"
    _archive(root, real=OFFSET_BARS)
    # A cycle that raised after placing its orders writes them on an ERROR row, which carries no equity and
    # is not a traded cycle: nothing maps the order to its data bar.
    unlisted = {**OFFSET_CYCLE, "orders": []}
    block = per_order_tca(_offset_store(tmp_path, unlisted, OFFSET_FILL), data_root=root, costs=COSTS)
    assert block["pre_trade"]["unestimated"] == {"AKEUSDT 决策 bar 对不上归档": 1}
    assert block["post_trade"]["unsplit"] == {"AKEUSDT 决策 bar 对不上归档": 1}
    assert block["post_trade"]["slippage"]["fills"] == 1, "counted in the mean, only not split or estimated"
    assert tca_lines(block)["没有事前估计的"] == "AKEUSDT 决策 bar 对不上归档 1 笔"


def test_participation_is_the_planned_notional_over_the_hour_the_cap_divides(tmp_path: Path) -> None:
    """`max_participation`'s ruler (GLOSSARY: 参与率), bit for bit: `LiveEngine._liquidity` on the bars it held."""
    _archive(tmp_path / "archive")
    block = per_order_tca(_store(tmp_path, [REAL_FILL]), data_root=tmp_path / "archive", costs=COSTS)

    frame = KlineStore(tmp_path / "archive").load("AKEUSDT", "1h")
    decided = frame[frame["open_time"] <= BAR]
    engine = SimpleNamespace(config=SimpleNamespace(liquidity_window=LIQUIDITY_WINDOW_BARS))
    hourly = LiveEngine._liquidity(engine, {"AKEUSDT": decided})["AKEUSDT"]
    assert block["pre_trade"]["participation"]["median"] == PLANNED / hourly
    assert block["pre_trade"]["liquidity_window_bars"] == LIQUIDITY_WINDOW_BARS
    # The decision bar's own volume, which it was until 2026-09-25, is a different number on this tape.
    assert not math.isclose(PLANNED / hourly, PLANNED / 5242097.489977, rel_tol=1e-3)


def test_the_impact_is_what_impact_costs_charges_for_the_same_order(tmp_path: Path) -> None:
    """Against the owner's code, as `liquidity_to_close`'s test does: `impact_costs` on the execution bar."""
    _archive(tmp_path / "archive")
    block = per_order_tca(_store(tmp_path, [REAL_FILL]), data_root=tmp_path / "archive", costs=COSTS)

    frame = KlineStore(tmp_path / "archive").load("AKEUSDT", "1h")
    panel = Panel.from_frames({"AKEUSDT": frame}, interval="1h")
    execution = pd.Timestamp(BAR + HOUR, unit="ms", tz="UTC")
    turnover = pd.DataFrame({"AKEUSDT": [1.0]}, index=pd.DatetimeIndex([execution]))

    def charged(convention: Any) -> float:
        rets = asset_returns(panel, convention)
        cost = impact_costs(turnover, rets, panel, ["AKEUSDT"], impact_model(COSTS, capital=PLANNED))
        return 1e4 * float(cost.loc[execution, "AKEUSDT"])

    impact = block["pre_trade"]["impact"]["value"]
    assert math.isclose(impact, charged("open_to_close"), rel_tol=1e-9)
    # The fixture tells the two conventions apart, so the line above cannot pass on the other one.
    assert not math.isclose(impact, charged("close_to_close"), rel_tol=1e-3)


def test_the_impact_parameters_come_through_researchs_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`impact_model` builds them from the cost file for `research backtest` and `validate`; this block too."""
    _archive(tmp_path / "archive")
    monkeypatch.setattr(
        report_execution, "impact_model", lambda costs: ImpactModel(coefficient=2.5, adv_window=600, vol_window=480)
    )
    block = per_order_tca(_store(tmp_path, [REAL_FILL]), data_root=tmp_path / "archive", costs=COSTS)
    model = block["pre_trade"]["model"]
    assert (model["impact_coefficient"], model["adv_window_bars"], model["vol_window_bars"]) == (2.5, 600, 480)
    assert (model["taker_fee_bps"], model["slippage_bps"]) == (COSTS["taker_fee_bps"], COSTS["slippage_bps"])


def _fill(bar: int, symbol: str, side: str, price: float, **extra: Any) -> dict[str, Any]:
    """A fill in the real row's shape, with its own venue id and the archive's close as its reference."""
    closes = {row[0]: row[4] for row in REAL_BARS}
    return {
        **REAL_FILL,
        "bar_open_ms": bar,
        "client_order_id": f"bd-{bar}-{symbol}",
        "order_id": str(next(_ORDER_IDS)),
        "symbol": symbol,
        "side": side,
        "avg_price": price,
        "decision_close": closes.get(bar, 0.044588),
        **extra,
    }


def test_the_prediction_is_compared_with_the_fill_part_alone(tmp_path: Path) -> None:
    """`slippage_bps` is against the next open, so a fill with no next bar yet is estimated and not compared."""
    _archive(tmp_path / "archive")
    newest = _fill(BAR + HOUR, "AKEUSDT", "SELL", 0.0421)  # its next bar is not archived yet
    block = per_order_tca(_store(tmp_path, [REAL_FILL, newest]), data_root=tmp_path / "archive", costs=COSTS)
    assert block["pre_trade"]["predicted"]["fills"] == 2 and block["post_trade"]["fill"]["fills"] == 1
    assert block["predicted_minus_actual"]["fills"] == 1
    [bucket] = block["by_participation"]
    assert bucket["predicted_minus_actual"]["value"] == pytest.approx(bucket["predicted"] - bucket["fill"], rel=1e-12)
    lines = tca_lines(block)
    assert lines["预测比的是哪一段"].startswith("成交段") and "跳空不在预测里" in lines["预测比的是哪一段"]


def test_the_mean_is_mq08s_on_the_same_fills_and_says_where_it_would_part(tmp_path: Path) -> None:
    _archive(tmp_path / "archive")
    trades = [
        _fill(BAR, "AKEUSDT", "BUY", 0.044624),
        _fill(BAR - HOUR, "AKEUSDT", "SELL", 0.044500, executed_qty="1000"),
        _fill(BAR - HOUR, "NOARCHIVEUSDT", "BUY", 0.044700),  # counted, not split, not estimated
        _fill(BAR, "AKEUSDT", "BUY", 0.046, decision_close=None),  # M-Q08 counts it apart; so does this
        {**_fill(BAR, "AKEUSDT", "SELL", 0.04), "bar_open_ms": None, "flatten": True},  # not the book's execution
        _fill(BAR - 40 * 24 * HOUR, "AKEUSDT", "BUY", 0.05),  # outside M-Q08's 30 days
    ]
    store = _store(tmp_path, trades)
    block = per_order_tca(store, RiskBudgetParams(), data_root=tmp_path / "archive", costs=COSTS)

    mq08 = slippage_bps(store.read_jsonl(store.trades_path), RiskBudgetParams(), latest_ms=BAR)
    assert block["post_trade"]["slippage"] == mq08["combined"], "same fills, same arithmetic, same dict"
    assert block["fills"] == 3 and block["without_reference"] == mq08["without_reference"] == 1
    assert block["reconciliation"]["combined"]["agrees"] is True
    assert block["pre_trade"]["unestimated"] == {"NOARCHIVEUSDT 归档没有这个标的": 1}
    assert block["post_trade"]["unsplit"] == {"NOARCHIVEUSDT 归档没有这个标的": 1}
    assert block["post_trade"]["gap"]["fills"] == 2, "the unpriced fill stays in the mean and leaves the split"

    # Where the two would part, said in the block rather than left for a reader to find.
    parted = report_execution._reconciled({"value": 5.0, "fills": 3}, {"value": 5.0, "fills": 2})
    assert parted["agrees"] is False and "成交笔数不同" in str(parted["why"])
    drifted = report_execution._reconciled({"value": 5.0, "fills": 3}, {"value": 5.1, "fills": 3})
    assert drifted["agrees"] is False and "算术" in str(drifted["why"])


def test_an_archive_that_will_not_open_costs_only_its_own_symbol(tmp_path: Path) -> None:
    """A zero-byte parquet raises ArrowInvalid, not FileNotFoundError: one symbol's reason, not the block's error."""
    root = tmp_path / "archive"
    _archive(root)
    broken = KlineStore(root).path("BBBUSDT", "1h")
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"")
    block = per_order_tca(
        _store(tmp_path, [REAL_FILL, _fill(BAR, "BBBUSDT", "SELL", 0.0445)]), data_root=root, costs=COSTS
    )
    assert "error" not in block and block["fills"] == 2
    [(why, count)] = block["pre_trade"]["unestimated"].items()
    assert why.startswith("BBBUSDT 归档读不出：") and count == 1
    assert block["post_trade"]["unsplit"] == block["pre_trade"]["unestimated"]
    assert block["post_trade"]["gap"]["fills"] == 1 == block["pre_trade"]["impact"]["fills"], "AKEUSDT still priced"


def test_the_split_by_book_reconciles_with_the_reading_mq08_judges(tmp_path: Path) -> None:
    """G9's split, per fill, on the report's own rows - where a SKIPPED row is not a bar that traded.

    Read from every row, the restart's skip below would end the window an hour late and drop the fill
    on its first bar: M-Q08 would count three fills and this block two.
    """
    _archive(tmp_path / "archive")
    store = StateStore(tmp_path / "live")
    carried = {"tsmom": {"AKEUSDT": 1.0, "BBBUSDT": -1.0}, "flow": {"BBBUSDT": -1.0}}
    for i in range(3):
        bar = BAR - (2 - i) * HOUR
        books = {"tsmom": "main", "flow": "flow_short"}
        store.append_cycle({"bar_open_ms": bar, "equity": 13_000.0, "books": books, "contributions": carried})
    # A restart that woke outside the next bar's window, with the keys a real one carries (2026-09-23T16:41Z).
    store.append_cycle(
        {
            "at": "2026-09-24T17:41:45+00:00",
            "bar": "2026-09-24T16:00:00+00:00",
            "bar_open_ms": BAR + HOUR,
            "dry_run": False,
            "late_seconds": 2505.204,
            "missed_rebalances": 1,
            "orders": [],
            "phase": "SKIPPED",
            "reason": "restart outside the rebalance window",
            "targets": {},
            "window_seconds": 85.861,
        }
    )
    store.append_trade(_fill(BAR, "AKEUSDT", "BUY", 0.044624))  # the main book alone carried it
    store.append_trade(_fill(BAR, "BBBUSDT", "SELL", 0.044500))  # both books carried it
    store.append_trade(_fill(BAR - 30 * 24 * HOUR, "AKEUSDT", "BUY", 0.0446))  # M-Q08's first bar; no books
    block = per_order_tca(store, RiskBudgetParams(), data_root=tmp_path / "archive", costs=COSTS)

    rows = [row for row in store.read_jsonl(store.cycles_path) if row.get("equity") is not None]
    mq08 = slippage_bps(
        store.read_jsonl(store.trades_path), RiskBudgetParams(), latest_ms=BAR, books_at=books_by_bar(rows)
    )
    recon = block["reconciliation"]
    assert recon["judged"] == mq08["judged"] == "main_only"
    assert recon["main_only"]["fills"] == mq08["by_group"]["main_only"]["fills"] == 1
    assert recon["main_only"]["value"] == pytest.approx(mq08["by_group"]["main_only"]["value"], abs=1e-9)
    assert recon["combined"]["fills"] == mq08["combined"]["fills"] == 3
    assert recon["main_only"]["agrees"] and recon["combined"]["agrees"]


def test_the_fee_is_read_only_where_one_commission_meets_one_fill(tmp_path: Path) -> None:
    _archive(tmp_path / "archive")
    store = _store(tmp_path, [REAL_FILL], [REAL_INCOME, {**REAL_INCOME, "at": "2026-09-24T17:30:00+00:00"}])
    block = per_order_tca(store, data_root=tmp_path / "archive", costs=COSTS)
    assert block["post_trade"]["fee"]["booked"]["fills"] == 0, "two income rows on one key: ambiguous, not summed"
    assert block["post_trade"]["fee"]["unmatched"] == 1 and block["post_trade"]["fee"]["not_yet_read"] == 0
    assert "1 笔在 attribution 里对不上唯一一行" in tca_lines(block)["手续费（另列，不在滑点里）"]

    # The newest bar's commission is read by the next cycle: not missing, only not read yet.
    newest = per_order_tca(_store(tmp_path / "newest", [REAL_FILL]), data_root=tmp_path / "archive", costs=COSTS)
    assert newest["post_trade"]["fee"]["not_yet_read"] == 1 and newest["post_trade"]["fee"]["unmatched"] == 0
    assert "1 笔下个周期才读到手续费" in tca_lines(newest)["手续费（另列，不在滑点里）"]


def test_a_flatten_inside_the_income_window_keeps_that_keys_fee_unread(tmp_path: Path) -> None:
    """A flatten fill has no bar, so the one-row-per-key count cannot see it; its commission is in that row too.

    Placed by the host's clock on both sides: written between the fill and the income row that books it,
    the flatten is inside that row's window, not the one before.  After the row, or on another symbol, it
    is in neither.
    """
    _archive(tmp_path / "archive")
    # The income row an hour earlier, in the same shape: the window that closed before the fill was placed.
    earlier = {
        **REAL_INCOME,
        "at": "2026-09-24T16:00:25+00:00",
        "bar_open_ms": BAR - HOUR,
        "since_ms": 1790262025000,
        "until_ms": 1790265625997,
    }
    inside = {**REAL_FLATTEN, "at": "2026-09-24T16:37:51+00:00"}
    income = [earlier, REAL_INCOME]
    block = per_order_tca(
        _store(tmp_path / "inside", [REAL_FILL, inside], income), data_root=tmp_path / "archive", costs=COSTS
    )
    fee = block["post_trade"]["fee"]
    assert fee["booked"]["fills"] == 0 and fee["flatten_in_window"] == 1 and fee["unmatched"] == 0
    assert "1 笔的入账窗口里有 live flatten 的成交，不读" in tca_lines(block)["手续费（另列，不在滑点里）"]

    later = {**REAL_FLATTEN, "at": "2026-09-24T17:30:00+00:00"}
    elsewhere = {**inside, "symbol": "ZECUSDT", "client_order_id": "bdflat-1789331867692-ZECUSDT"}
    for name, flatten in (("later", later), ("elsewhere", elsewhere)):
        clean = per_order_tca(
            _store(tmp_path / name, [REAL_FILL, flatten], income), data_root=tmp_path / "archive", costs=COSTS
        )
        assert clean["post_trade"]["fee"]["booked"]["fills"] == 1, name
        assert clean["post_trade"]["fee"]["flatten_in_window"] == 0, name


def test_participation_buckets_are_fixed_decades() -> None:
    readings = [
        {"participation": p, "error": e, "fill": s, "predicted": s + e, "notional": 100.0}
        for p, e, s in ((5e-6, -1.0, 3.0), (1e-5, -2.0, 4.0), (2e-4, 0.5, 1.0), (1e-3, -6.0, 8.0))
    ]
    buckets = _by_participation(readings)
    assert TCA_PARTICIPATION_EDGES == (1e-5, 1e-4, 1e-3)
    assert [row["bucket"] for row in buckets] == ["<1e-05", "1e-05–1e-04", "1e-04–1e-03", "≥1e-03"]
    fills = [row["predicted_minus_actual"]["fills"] for row in buckets]
    assert fills == [1, 1, 1, 1], "an edge belongs to the bucket above it"
    assert buckets[1]["predicted_minus_actual"]["value"] == pytest.approx(-2.0)
    assert buckets[1]["fill"] == pytest.approx(4.0) and buckets[1]["predicted"] == pytest.approx(2.0)


def _day_store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "live")
    for i in range(24):
        bar = BAR - (23 - i) * HOUR
        store.append_cycle(
            {
                "bar_open_ms": bar,
                "equity": 13_000.0,
                "registry": "r",
                "construction": "c",
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
            }
        )
    store.append_trade(REAL_FILL)
    store.append_attribution(REAL_INCOME)
    return store


def test_the_daily_report_carries_it_after_mq08_and_says_what_the_estimate_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)  # the cost model is read from `config/costs.yaml`, as the loop's profile names it
    _archive(tmp_path / "archive")
    payload = daily_payload(_day_store(tmp_path), "2026-09-24", {}, data_root=tmp_path / "archive")
    keys = list(payload)
    assert keys.index("tca") == keys.index("execution_fidelity") + 1
    recon, slippage = payload["tca"]["reconciliation"], payload["risk_budget"]["slippage"]
    assert recon["combined"]["m_q08"] == slippage["combined"]["value"] and recon["combined"]["agrees"]
    markdown = daily_markdown(payload)
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    at = headings.index("## Execution fidelity (M-Q08, four clauses)")
    assert headings[at + 1] == "## Per-order TCA (#10.9 / #10.10, reported only)"
    section = markdown.split("## Per-order TCA (#10.9 / #10.10, reported only)")[1].split("\n## ")[0]
    said = (
        "离线重建",
        "只用决策时刻已收盘的 bar",
        "as_of_ms",
        f"近 {LIQUIDITY_WINDOW_BARS} 根 bar 的平均小时成交额",
        "没校准",
        "对得上",
        "主网与 demo 的价格差",
        "这是推断",
        "bookTicker 归档止于 2024-04",
        "合成的",
        "跳空不在预测里",
    )
    for phrase in said:
        assert phrase in section, phrase
    # Reported only: taking the block out moves no alert and no notice.
    assert daily_alerts(payload) == daily_alerts({k: v for k, v in payload.items() if k != "tca"})


def test_a_broken_block_leaves_the_rest_of_the_report_and_its_alerts_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    _archive(tmp_path / "archive")
    store = _day_store(tmp_path)
    clean = daily_payload(store, "2026-09-24", {}, data_root=tmp_path / "archive")

    def broken(*_args: object, **_kwargs: object) -> Any:
        raise ZeroDivisionError("injected by the test")

    monkeypatch.setattr(report_execution, "_tca", broken)
    payload = daily_payload(store, "2026-09-24", {}, data_root=tmp_path / "archive")
    assert payload["tca"] == {"error": "ZeroDivisionError: injected by the test"}
    assert daily_alerts(payload) == daily_alerts(clean)
    markdown = daily_markdown(payload)
    sections = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert sections == [line for line in daily_markdown(clean).splitlines() if line.startswith("## ")]
    section = markdown.split("## Per-order TCA (#10.9 / #10.10, reported only)")[1].split("\n## ")[0]
    assert "读不出，这一块整块失败" in section and "ZeroDivisionError: injected by the test" in section
