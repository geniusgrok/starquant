"""M-Q08 on one page: slippage as a trend beside its judged number, and all four clauses together.

The judged slippage reading pools thirty days, so it cannot say whether fills are getting better or
worse.  The trend buckets the same fills by week with the same arithmetic - pinned below to the bit - and,
since the operator's G9 ruling (2026-09-23), the same split: each fill by the books of its own cycle and
the one before (`fill_grouper`).  Before the ruling the judged reading split every fill by the newest
cycle's map, and this file pinned that difference; the rule itself is pinned in
`test_mq08_judges_each_fill_by_the_books_it_traded_for.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.registry import parse_registry
from starquant_live import execution_fidelity as fidelity
from starquant_live.composition import build_model, load_registry
from starquant_live.config import live_overlay_blocks
from starquant_live.engine import registry_digest
from starquant_live.reports import daily_markdown, daily_payload
from starquant_live.risk_budget import RiskBudgetParams, books_by_bar, slippage_bps
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_788_220_800_000  # 2026-09-01T00:00Z, a Tuesday: its week began Monday 2026-08-31
BOTH_BOOKS = {"tsmom": {"AAAUSDT": 1.0, "BBBUSDT": -1.0}, "flow": {"BBBUSDT": -1.0}}
MAIN_ONLY = {"tsmom": {"AAAUSDT": 1.0, "BBBUSDT": -1.0}, "flow": {}}


def _cycle(bar: int, contributions: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"bar_open_ms": bar, "equity": 1_000.0, "registry": "abc123", "construction": "c"}
    if contributions is not None:
        row["books"] = {"tsmom": "main", "flow": "flow_short"}
        row["contributions"] = contributions
    return row


def _fill(bar: int, symbol: str, side: str, price: float, quantity: float = 1.0, **extra: Any) -> dict[str, Any]:
    return {
        "bar_open_ms": bar,
        "symbol": symbol,
        "side": side,
        "avg_price": price,
        "executed_qty": str(quantity),
        "decision_close": 100.0,
        **extra,
    }


def test_each_week_carries_its_mean_error_bar_and_count() -> None:
    first, second = T0 + DAY, T0 + 7 * DAY  # Wednesday 09-02 and Tuesday 09-08
    rows = [_cycle(first, MAIN_ONLY), _cycle(second, BOTH_BOOKS), _cycle(second + HOUR)]
    trades = [
        _fill(first, "AAAUSDT", "BUY", 100.01),  # +1 bps
        _fill(first, "AAAUSDT", "BUY", 100.50, flatten=True),  # an operator flatten is not the book's execution
        _fill(first, "AAAUSDT", "BUY", 100.50, decision_close=None),  # no reference, no reading
        _fill(second, "AAAUSDT", "SELL", 99.98),  # +2 bps, main-only by its own cycle
        _fill(second, "BBBUSDT", "SELL", 99.79),  # +21 bps, both books carried it on that bar
        _fill(second + HOUR, "AAAUSDT", "BUY", 100.03),  # +3 bps, from a cycle that cannot name the books
    ]
    weeks = fidelity.slippage_by_week(rows, trades)

    assert [week["week"] for week in weeks] == ["2026-08-31", "2026-09-07"]
    assert weeks[0]["combined"]["fills"] == 1 and weeks[0]["combined"]["value"] == pytest.approx(1.0)
    assert weeks[0]["main_only"]["value"] == pytest.approx(1.0) and weeks[0]["unsplit"] == 0
    assert weeks[1]["combined"]["fills"] == 3 and weeks[1]["combined"]["se"] is not None
    assert weeks[1]["main_only"]["fills"] == 1 and weeks[1]["main_only"]["value"] == pytest.approx(2.0)
    assert weeks[1]["unsplit"] == 1
    assert len(fidelity.slippage_by_week(rows, trades, weeks=1)) == 1


def test_a_bucket_is_read_with_the_judged_instruments_own_arithmetic() -> None:
    """Every fill on the newest cycle: the trend's bucket and `slippage_bps` must agree to the bit."""
    bar = T0 + DAY
    rows = [_cycle(bar, BOTH_BOOKS)]
    trades = [
        _fill(bar, "AAAUSDT", "BUY", 100.04, quantity=3.0),
        _fill(bar, "AAAUSDT", "SELL", 99.99, quantity=1.0),
        _fill(bar, "BBBUSDT", "SELL", 99.80, quantity=2.0),
        _fill(bar, "BBBUSDT", "BUY", 100.07, quantity=5.0),
    ]
    judged = slippage_bps(trades, RiskBudgetParams(min_slippage_fills=1), latest_ms=bar, books_at=books_by_bar(rows))
    (week,) = fidelity.slippage_by_week(rows, trades)
    assert week["combined"] == judged["combined"]
    assert week["main_only"] == judged["by_group"]["main_only"]


def test_the_judged_reading_and_the_trend_split_a_fill_by_its_own_cycle() -> None:
    """Operator ruling 2026-09-23 (G9): one rule for both readers.

    Until the ruling this test pinned the opposite on purpose - the judged reading split by the newest
    cycle, so this overlaid fill, made while the probe carried BBB, was judged as the main book's.
    """
    traded, newest = T0 + DAY, T0 + 2 * DAY
    rows = [_cycle(traded, BOTH_BOOKS), _cycle(newest, MAIN_ONLY)]  # the probe went flat after the fill
    trades = [_fill(traded, "BBBUSDT", "SELL", 99.79)]
    judged = slippage_bps(trades, RiskBudgetParams(min_slippage_fills=1), latest_ms=newest, books_at=books_by_bar(rows))
    (week,) = fidelity.slippage_by_week(rows, trades)
    assert judged["judged"] == "main_only" and judged["fills"] == 0 and not judged["enforced"]
    assert judged["by_group"]["overlaid"]["fills"] == 1, "judged: an overlaid fill, not the main book's"
    assert week["main_only"] is None and week["combined"]["fills"] == 1, "trend: the same"


def test_the_daily_report_prints_all_four_mq08_clauses(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    for i in range(30):
        store.append_cycle({**_cycle(T0 + i * HOUR), "skip": False, "guard_reasons": [], "targets": {}, "orders": []})
    store.append_trade(_fill(T0 + 3 * HOUR, "AAAUSDT", "BUY", 100.02))
    payload = daily_payload(store, "2026-09-01", {})
    block = payload["execution_fidelity"]
    assert block["turnover"]["enforced"] is False and "registry 与 profile" in block["turnover"]["why"]
    assert block["registry"]["loop"] == "abc123" and block["registry"]["consistent"] is None
    section = daily_markdown(payload).split("## Execution fidelity (M-Q08, four clauses)")[1].split("\n## ")[0]
    for clause in (
        "换手 实盘/回测同期",
        "滑点（判定读数",
        "迟到周期",
        "registry digest 循环/磁盘",
        "滑点 2026-08-31 起一周",
    ):
        assert clause in section, clause


def test_the_replay_inputs_are_the_loops_own_construction(tmp_path: Path) -> None:
    profile = {**load_yaml(ROOT / "config/live.demo.yaml"), "costs": str(ROOT / "config/costs.yaml")}
    registry = load_registry(ROOT / "config/alpha_registry.yaml")
    inputs = fidelity.ReplayInputs.from_profile(profile, registry, tmp_path)
    assert inputs.problem is None and inputs.model is not None and inputs.guards is not None
    blocks = live_overlay_blocks(profile)
    assert vars(inputs.guards) == blocks["book_guards"]
    assert inputs.exits is not None and vars(inputs.exits) == blocks["exits"]
    # the digest `live status --check` compares the loop against, computed the same way
    assert inputs.registry_on_disk == registry_digest(build_model(registry, profile))

    # A registry the loop could not start on blinds the instrument; it must not break the hourly report.
    blind = fidelity.ReplayInputs.from_profile(profile, parse_registry({"strategies": []}), tmp_path)
    assert blind.model is None and "no enabled strategies" in str(blind.problem)
    missing = fidelity.ReplayInputs.from_profile({**profile, "costs": str(tmp_path / "none.yaml")}, registry, tmp_path)
    assert missing.model is None and missing.problem is not None
