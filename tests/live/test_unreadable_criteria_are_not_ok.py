"""A criterion nobody can read must not report as a pass (2026-09-08 audit).

Every metric in ``risk_budget`` already refuses to invent a number it cannot compute - it returns
``enforced: false`` with a reason.  The summary above them did not carry that through: with no
readable criterion at all, ``risk_budget_status`` returned ``status: OK`` and an empty ``reasons``,
which is what the 2026-09-07 daily report says while M-Q08's slippage instrument had zero usable
fills.  A blind gate and a passing gate looked identical in the one line an operator reads.

Routing is deliberately NOT changed: a criterion that will re-arm on its own once the fills arrive is
the "unactionable standing fact" ``daily_alerts`` was written to keep off the paging path, so it
becomes a notice rather than an alert.
"""

from __future__ import annotations

import math
from typing import Any

from starquant_live.reports import daily_alerts
from starquant_live.risk_budget import RiskBudgetParams, risk_budget_status

HOUR_MS = 3_600_000


def _cycle(index: int, equity: float, **extra: Any) -> dict[str, Any]:
    return {
        "bar_open_ms": 1_700_000_000_000 + index * HOUR_MS,
        "equity": equity,
        "construction": extra.pop("construction", "aaa"),
        "guard_reasons": extra.pop("guard_reasons", []),
        **extra,
    }


def _fill(row_ms: int) -> dict[str, Any]:
    return {
        "bar_open_ms": row_ms,
        "side": "BUY",
        "decision_close": 100.0,
        "avg_price": 100.0,
        "executed_qty": "1",
    }


def test_a_criterion_that_cannot_be_read_is_not_reported_as_ok() -> None:
    """The 2026-09-07 shape: 0 usable fills, and the report said OK."""
    params = RiskBudgetParams()
    rows = [_cycle(i, 100.0) for i in range(5)]

    out = risk_budget_status(rows, [], params)

    assert out["status"] == "BLIND"
    assert not out["reasons"]  # nothing is breached; nothing can be read either
    unreadable = {entry["metric"] for entry in out["unreadable"]}
    assert unreadable == {"realised_vol", "slippage"}
    assert any("需要 30 笔" in entry["why"] for entry in out["unreadable"])


def test_every_criterion_readable_and_inside_its_bar_is_still_ok() -> None:
    params = RiskBudgetParams(min_vol_bars=3, min_slippage_fills=1)
    # Derived from the band, not hardcoded: this test is about "a readable criterion inside its bar is OK",
    # and a literal here silently re-tests whatever `vol_band`'s default happens to be.  It was 0.30 against
    # the k=0.30 pair and broke the day the default moved to the k=0.60 one (2026-09-14).
    low, high = params.vol_band
    step = (low + high) / 2 / math.sqrt(params.bars_per_year)  # alternating +-step lands on the band's middle
    equity, rows = 100.0, []
    for i in range(40):
        equity *= 1.0 + (step if i % 2 else -step)
        rows.append(_cycle(i, equity))

    out = risk_budget_status(rows, [_fill(rows[-1]["bar_open_ms"])], params)

    assert out["status"] == "OK"
    assert out["unreadable"] == []


def test_a_breach_outranks_a_blind_criterion() -> None:
    """A real breach must not be downgraded just because another metric is unreadable."""
    params = RiskBudgetParams()
    rows = [_cycle(0, 100.0), _cycle(1, 40.0)]  # -60%: past rollback_at, and slippage stays blind

    out = risk_budget_status(rows, [], params)

    assert out["status"] == "ALERT"
    assert any("回撤" in reason for reason in out["reasons"])
    assert {entry["metric"] for entry in out["unreadable"]} == {"realised_vol", "slippage"}


def test_a_blind_risk_budget_is_a_notice_and_never_pages() -> None:
    """It re-arms on its own once the fills arrive, which is what `notices` exists for."""
    alerts, notices = daily_alerts(
        {"risk_budget": {"status": "BLIND", "reasons": [], "unreadable": [{"metric": "slippage", "why": "0 fills"}]}}
    )

    assert alerts == []
    assert any("slippage" in notice for notice in notices)


def test_the_ladders_reading_carries_the_share_of_equity_that_is_not_the_book() -> None:
    """L1-10 measured it and the daily report printed it - four blocks away from the ladder that divides by it.

    The de-escalation ladder acts on `drawdown from the high-water mark`, and on 2026-09-07 52.3% of the
    equity that drawdown is measured on was non-USDT collateral.  A -35% reading can then belong to BTC
    rather than to the book.  Reported beside the reading, never subtracted from it: changing the
    denominator would change every position size, which is a construction decision (L1-10's own ruling).
    """
    params = RiskBudgetParams()
    rows = [
        _cycle(0, 10_000.0),
        _cycle(1, 9_000.0, collateral={"share": 0.5231, "collateral": 4_707.0, "usdt_equity": 4_293.0}),
    ]

    drawdown = risk_budget_status(rows, [], params)["drawdown"]

    assert drawdown["collateral_share"] == 0.5231


def test_a_run_whose_cycles_never_recorded_collateral_says_none_rather_than_zero() -> None:
    """Zero would read as "all of it is the book's own currency", which is the opposite of "we do not know"."""
    drawdown = risk_budget_status([_cycle(0, 10_000.0)], [], RiskBudgetParams())["drawdown"]

    assert drawdown["collateral_share"] is None
