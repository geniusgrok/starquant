"""M-007's denominator (2026-09-19): `margin_cap` was calibrated where collateral does not exist.

The backtest models no collateral (RISK-G11), so `margin_cap: 0.40` was always a statement about the
USDT line.  Measuring it against total equity - about half BTC here - made the ruler 1.9x looser than
the policy it stands for, and M-007 had never once reported a breach.

This is the same correction as 2026-09-14, one layer down: that one fixed the BAR (the plan's 50%
judging where the profile said 40%), this one fixes the DENOMINATOR.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_live.reports import daily_alerts, margin_and_rejections
from starquant_live.state import StateStore

HOUR = 3_600_000
BAR = 1_789_000_000_000


def _store(tmp_path: Path, rows: list[dict]) -> StateStore:
    store = StateStore(tmp_path)
    with store.cycles_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    store.trades_path.write_text("", encoding="utf-8")
    return store


def _cycle(i: int, *, usage: float, equity: float, usdt: float, gross: float = 0.0) -> dict:
    return {
        "bar_open_ms": BAR + i * HOUR,
        "equity": equity,
        "margin_usage": usage,
        "gross_before": gross,
        "collateral": {"equity": equity, "usdt_equity": usdt, "collateral": equity - usdt},
    }


def test_the_tradable_reading_rescales_by_the_collateral_share(tmp_path: Path) -> None:
    """Half the equity is BTC, so the same book consumes twice the share of what can open a position."""
    store = _store(tmp_path, [_cycle(0, usage=0.20, equity=10_000.0, usdt=5_000.0, gross=9_000.0)])

    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert margin["peak_standing_usage"] == 0.20
    assert margin["peak_standing_usage_tradable"] == 0.40
    assert margin["last_gross_over_tradable"] == 1.80, "gross is 0.9x equity but 1.8x tradable"


def test_a_book_inside_the_budget_on_equity_can_be_outside_it_on_tradable_usdt(tmp_path: Path) -> None:
    """The 2026-09-13T22:00Z shape: 22.73% of equity, 48.71% of tradable, and M-007 said OK."""
    store = _store(tmp_path, [_cycle(0, usage=0.2273, equity=10_800.0, usdt=5_040.0)])

    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert margin["over_budget"] is False, "the old ruler cannot see it"
    assert margin["over_budget_tradable"] is True
    assert margin["peak_standing_usage_tradable"] > 0.48


def test_the_disagreement_between_the_two_rulers_is_reported_once(tmp_path: Path) -> None:
    """Not twice, and not under the same wording: the GAP is the finding, not a second breach."""
    store = _store(tmp_path, [_cycle(0, usage=0.2273, equity=10_800.0, usdt=5_040.0)])
    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    _, notices = daily_alerts({"margin": margin, "risk_budget": {}, "drift": {}, "restarts": {}})

    tradable = [n for n in notices if "可动用 USDT" in n]
    assert len(tradable) == 1
    assert "48" in tradable[0] and "22" in tradable[0], "both readings are in the one notice"
    assert "构造冻结" in tradable[0], "and it says the constraint side was not touched"


def test_a_breach_on_both_rulers_does_not_produce_two_notices(tmp_path: Path) -> None:
    store = _store(tmp_path, [_cycle(0, usage=0.55, equity=10_000.0, usdt=5_000.0)])
    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    _, notices = daily_alerts({"margin": margin, "risk_budget": {}, "drift": {}, "restarts": {}})

    assert margin["over_budget"] and margin["over_budget_tradable"]
    assert len([n for n in notices if "M-007" in n]) == 1


def test_a_cycle_without_a_collateral_reading_is_skipped_not_counted_as_zero(tmp_path: Path) -> None:
    """Cycles predate `collateral`; a missing reading must not enter the series as a flattering 0."""
    rows = [
        {"bar_open_ms": BAR, "equity": 10_000.0, "margin_usage": 0.30},  # no collateral block
        _cycle(1, usage=0.20, equity=10_000.0, usdt=5_000.0),
    ]
    store = _store(tmp_path, rows)

    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert margin["peak_standing_usage"] == 0.30, "the equity series still sees both"
    assert margin["peak_standing_usage_tradable"] == 0.40, "the tradable series sees only the priced one"


def test_a_pure_usdt_account_reads_the_same_on_both_rulers(tmp_path: Path) -> None:
    """The degenerate case that says the rescaling is a denominator swap and nothing else."""
    store = _store(tmp_path, [_cycle(0, usage=0.33, equity=7_000.0, usdt=7_000.0)])

    margin = margin_and_rejections(store, since_ms=None, margin_cap=0.40)

    assert margin["peak_standing_usage"] == margin["peak_standing_usage_tradable"]


def test_the_constraint_side_still_divides_by_total_equity(tmp_path: Path) -> None:
    """The line this correction must NOT cross, pinned so a later tidy-up cannot cross it quietly.

    `max_gross` clips weights in `guards.clamp_book` and `margin_cap` derives venue leverage (D-016),
    both against total equity, and both sit inside the construction fingerprint frozen to 2026-10-13.
    Changing either denominator resizes every position and resets M-010, M-G06 and `realised_vol` -
    a construction decision for the operator.  M-007 measuring the tradable line does not make it.
    """
    import inspect

    import numpy as np

    from starquant_alpha.overlays.exposure import clamp_book

    # The invariant is in the signature: weights are fractions of TOTAL equity, and there is nowhere
    # to pass a collateral share or a USDT balance in.  A future "let's unify the denominators" would
    # have to add a parameter here, and that is the change that must not happen quietly.
    assert list(inspect.signature(clamp_book).parameters) == ["values", "max_weight", "max_gross"]

    clamped, capped = clamp_book(np.array([1.0, 1.0]), 1.0, 2.0)

    assert capped is False, "gross 2.0 is exactly at the cap and is not clipped"
    assert clamped.tolist() == [1.0, 1.0]
