"""R8 divides by a pinned path but the positions in its numerator are sized off CURRENT equity.

The reading is `marked / peak - 1`, and `peak` is the running max of `base + the book's own P&L`: it
moves only when the book makes a new high.  The positions whose loss lands in that numerator are
`weight x equity`, and on this account equity also floats with 52.65% BTC collateral.  So the same
percentage move of the book reads scaled by `equity / peak`, and while the book sits below its own
high-water mark that factor has no path back to 1.

Measured over 287 live cycles on 2026-09-14 (`scratchpad/r8_denominator_drift.py`): 1.000 at the
baseline, 1.0154 eleven days later, above 1 on 261 of them.  Small today - a -35% rung firing at -34.66%
of the book's own move - and unbounded in mechanism, which is why it is worth a number rather than a
paragraph.  This is a READING, not a rule: nothing here changes when the ladder fires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starquant_live.engine import LiveEngine
from starquant_live.risk_budget import RiskBudgetParams, attributed_drawdown_state
from starquant_live.state import LiveState, StateStore

BAR = 3_600_000
START = 1_788_400_000_000


class _Alerts:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


def _engine(tmp_path: Path) -> LiveEngine:
    engine = LiveEngine.__new__(LiveEngine)
    engine.config = type("C", (), {"portfolio": type("P", (), {"vol_target": 0.60})()})()
    engine.store = StateStore(tmp_path)
    engine.state = LiveState()
    engine.alerts = _Alerts()
    return engine


def _cycle(store: StateStore, index: int, equity: float, **extra: Any) -> int:
    bar = START + index * BAR
    store.append_cycle({"at": "2026-09-01T00:00:00+00:00", "bar_open_ms": bar, "equity": equity, **extra})
    return bar


def _attribute(store: StateStore, bar: int, total: float) -> None:
    store.append_attribution(
        {"bar_open_ms": bar, "until_ms": bar + BAR, "total": total, "by_strategy": {"tsmom": total}}
    )


def _reading(store: StateStore) -> dict[str, Any]:
    return attributed_drawdown_state(
        store.read_jsonl(store.cycles_path), store.read_jsonl(store.attribution_path), RiskBudgetParams()
    )


def test_the_factor_is_one_while_equity_and_the_path_still_agree(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    _attribute(store, _cycle(store, 0, 10_000.0), 0.0)

    assert _reading(store)["equity_over_peak"] == pytest.approx(1.0)


def test_collateral_lifting_equity_shows_up_as_a_factor_above_one(tmp_path: Path) -> None:
    """The live mechanism: equity rises for a reason the book did not earn, and `peak` cannot follow."""
    store = StateStore(tmp_path)
    _attribute(store, _cycle(store, 0, 10_000.0), 0.0)
    _attribute(store, _cycle(store, 1, 12_000.0), -100.0)  # BTC up 20%, the book down 100

    reading = _reading(store)

    assert reading["peak"] == pytest.approx(10_000.0), "a losing book makes no new high, so the peak is pinned"
    assert reading["equity_over_peak"] == pytest.approx(1.2)
    assert reading["value"] == pytest.approx(-0.01), "and the reading itself never saw the equity move"


def test_the_factor_falls_below_one_when_equity_drops_instead(tmp_path: Path) -> None:
    """The other direction has to work too, or the field is a one-way decoration."""
    store = StateStore(tmp_path)
    _attribute(store, _cycle(store, 0, 10_000.0), 0.0)
    _attribute(store, _cycle(store, 1, 9_000.0), -100.0)

    assert _reading(store)["equity_over_peak"] == pytest.approx(0.9)


async def test_the_engine_writes_it_into_the_cycle_record(tmp_path: Path) -> None:
    """A number computed and not recorded is the shape D-038 exists to stop."""
    engine = _engine(tmp_path)
    _attribute(engine.store, _cycle(engine.store, 0, 10_000.0), 0.0)
    bar = _cycle(engine.store, 1, 12_000.0)
    _attribute(engine.store, bar, -100.0)

    block = await LiveEngine._risk_ladder(engine, bar)

    assert block["equity_over_peak"] == pytest.approx(1.2)
