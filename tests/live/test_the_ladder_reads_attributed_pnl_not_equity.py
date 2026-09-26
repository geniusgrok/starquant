"""DL-G7 / R8: the de-escalation ladder, on attributed P&L, with two cycles of grace.

Before this, `Policy.throttle_scalar` and `drawdown_grace_cycles` had no caller anywhere in the tree.
The rungs were written down, versioned, hashed into `policy_digest()` and recorded every cycle - and
nothing consulted them.  That is the same shape as the four other defects found on 2026-09-09: a thing
that looks like a control and controls nothing.

The other half is which ruler it reads.  52% of this account is non-USDT collateral and 73% of its
measured equity change was repricing, so an equity drawdown can be bitcoin moving while the book sits
flat.  T-G7-3 is the test that says so: equity halves, attribution never moves, the ladder does not
fire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from starquant_governance.policy import Policy
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


# 0.60 is the k the rungs are derived for since 2026-09-14; at a different k the scalars below mean
# something else, which is the dependence `engine._risk_ladder` now clamps rather than hides.
def _engine(tmp_path: Path, *, vol_target: float = 0.60) -> LiveEngine:
    engine = LiveEngine.__new__(LiveEngine)
    engine.config = type("C", (), {"portfolio": type("P", (), {"vol_target": vol_target})()})()
    engine.store = StateStore(tmp_path)
    engine.state = LiveState()
    engine.alerts = _Alerts()
    return engine


def _cycle(store: StateStore, index: int, equity: float, **extra: Any) -> int:
    bar = START + index * BAR
    store.append_cycle(
        {"at": f"2026-09-0{1 + index // 24}T00:00:00+00:00", "bar_open_ms": bar, "equity": equity, **extra}
    )
    return bar


def _attribute(store: StateStore, bar: int, total: float) -> None:
    store.append_attribution(
        {"bar_open_ms": bar, "until_ms": bar + BAR, "total": total, "by_strategy": {"tsmom": total}}
    )


# --- T-G7-1: one set of rungs, two instruments -------------------------------------------------


def test_the_profile_and_the_policy_cannot_disagree_about_the_rungs() -> None:
    """The same four numbers live in `live.demo.yaml` and in `Policy`, and nothing joined them.

    They are not redundant - `risk_budget` is P13's monitoring on venue equity and the policy ladder is
    what R8 acts on - but they are the SAME thresholds, and a threshold written twice drifts.  This is
    the join.
    """
    profile = yaml.safe_load(Path("config/live.demo.yaml").read_text(encoding="utf-8"))
    block = profile["risk_budget"]
    rungs = dict(Policy().drawdown_ladder)
    assert rungs[-float(block["deescalate_at"])] == pytest.approx(float(block["deescalate_to"]))
    assert rungs[-float(block["rollback_at"])] == pytest.approx(float(block["rollback_to"]))


# --- T-G7-2: it fires, after the grace ---------------------------------------------------------


async def test_a_fifty_percent_attributed_drawdown_alerts_then_acts_two_cycles_later(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = engine.store
    bar = _cycle(store, 0, 10_000.0)
    _attribute(store, bar, 0.0)
    first = await LiveEngine._risk_ladder(engine, bar)
    assert first["enforced"] and first["scalar"] == 1.0 and not first["acting"]

    # the book loses 50% of the account by trading; equity is left alone so only attribution moves
    bar = _cycle(store, 1, 10_000.0)
    _attribute(store, bar, -5_000.0)
    crossed = await LiveEngine._risk_ladder(engine, bar)
    assert crossed["drawdown"] == pytest.approx(-0.50)
    assert crossed["rung"] == 0.45 and crossed["cycles"] == 1
    assert crossed["scalar"] == 1.0 and not crossed["acting"], "the first crossing must not size anything"
    assert any("不缩仓" in m for m in engine.alerts.sent), engine.alerts.sent

    bar = _cycle(store, 2, 10_000.0)
    held = await LiveEngine._risk_ladder(engine, bar)
    assert held["cycles"] == 2 and held["scalar"] == 1.0 and not held["acting"]

    bar = _cycle(store, 3, 10_000.0)
    acting = await LiveEngine._risk_ladder(engine, bar)
    assert acting["cycles"] == 3 and acting["acting"]
    assert acting["scalar"] == pytest.approx(0.75), "AC-G7: vol_target 0.60 -> 0.45"
    assert acting["vol_target"] == 0.45
    assert sum("已生效" in m for m in engine.alerts.sent) == 1

    # deepening past the second rung does not restart the grace - a worse loss must act faster, not slower
    bar = _cycle(store, 4, 10_000.0)
    _attribute(store, bar, -2_100.0)  # -71% in total, past the second rung
    deeper = await LiveEngine._risk_ladder(engine, bar)
    assert deeper["vol_target"] == 0.30 and deeper["scalar"] == pytest.approx(0.5) and deeper["acting"]

    # and it lifts when the drawdown does, with the recovery said out loud
    bar = _cycle(store, 5, 10_000.0)
    _attribute(store, bar, 5_200.0)
    lifted = await LiveEngine._risk_ladder(engine, bar)
    assert not lifted["acting"] and lifted["scalar"] == 1.0
    assert engine.state.risk_ladder == {}
    assert any("恢复" in m for m in engine.alerts.sent), engine.alerts.sent


# --- T-G7-3: the ruler is the point ------------------------------------------------------------


async def test_an_equity_collapse_the_book_did_not_cause_does_not_move_the_ladder(tmp_path: Path) -> None:
    """Collateral halves; the book realised nothing.  The equity instrument screams, R8 does not act."""
    engine = _engine(tmp_path)
    store = engine.store
    bar = _cycle(store, 0, 10_000.0)
    _attribute(store, bar, 0.0)
    for index, equity in enumerate([9_000.0, 7_000.0, 5_000.0], start=1):
        bar = _cycle(store, index, equity)
        block = await LiveEngine._risk_ladder(engine, bar)
        assert block["scalar"] == 1.0 and not block["acting"]
    assert engine.state.risk_ladder == {}
    assert engine.alerts.sent == []

    from starquant_live.risk_budget import drawdown_state

    rows = store.read_jsonl(store.cycles_path)
    assert drawdown_state(rows, RiskBudgetParams())["value"] == pytest.approx(0.50), "the equity ruler does see it"
    assert attributed_drawdown_state(rows, store.read_jsonl(store.attribution_path), RiskBudgetParams())[
        "value"
    ] == pytest.approx(0.0)


# --- the state has to survive the restart, like `stopped_books` --------------------------------


async def test_a_restart_does_not_hand_the_book_a_fresh_grace(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = engine.store
    bar = _cycle(store, 0, 10_000.0)
    _attribute(store, bar, -5_500.0)  # -55%, on the first rung since 2026-09-14
    for index in (1, 2, 3):
        bar = _cycle(store, index, 10_000.0)
        await LiveEngine._risk_ladder(engine, bar)
    assert engine.state.risk_ladder["cycles"] == 3 and engine.state.risk_ladder["acting"]
    store.save(engine.state)

    revived = _engine(tmp_path)
    revived.state = StateStore(tmp_path).load()
    assert revived.state.risk_ladder["acting"], "the breach outlived the process"
    bar = _cycle(store, 4, 10_000.0)
    block = await LiveEngine._risk_ladder(revived, bar)
    assert block["acting"] and block["scalar"] == pytest.approx(0.75), "not a fresh two-cycle grace"


async def test_a_reading_that_cannot_be_taken_does_not_lift_a_standing_action(tmp_path: Path) -> None:
    """ "Cannot compute" is not "recovered" - the failure this repository keeps finding, in one assert."""
    engine = _engine(tmp_path)
    engine.state.risk_ladder = {"cycles": 9, "rung": 0.45, "vol_target": 0.45, "scalar": 0.75, "acting": True}
    bar = _cycle(engine.store, 0, 10_000.0)  # a cycle, but no attribution row lands on it
    block = await LiveEngine._risk_ladder(engine, bar)
    assert not block["enforced"] and block["acting"] and block["scalar"] == pytest.approx(0.75)
    assert block["held_blind"] and "realised nothing" in block["why"]


def test_pnl_that_lands_on_no_priced_cycle_is_reported_rather_than_dropped(tmp_path: Path) -> None:
    """The path is built off priced cycles, so attribution on an unpriced bar would vanish silently.

    Vanishing understates the drawdown, which is the permissive direction, and "it is zero on today's
    record" is not a property.  Zero on the live record as of 2026-09-09 - measured, and reported so the
    day it stops being zero is visible.
    """
    store = StateStore(tmp_path)
    bar = _cycle(store, 0, 10_000.0)
    _attribute(store, bar, -100.0)
    _attribute(store, bar + 99 * BAR, -5_000.0)  # a bar no cycle ever priced
    reading = attributed_drawdown_state(
        store.read_jsonl(store.cycles_path), store.read_jsonl(store.attribution_path), RiskBudgetParams()
    )
    assert reading["enforced"] and reading["rows"] == 1
    assert reading["orphaned_rows"] == 1 and reading["orphaned_pnl"] == pytest.approx(-5_000.0)
    assert reading["value"] == pytest.approx(-0.01), "the orphan is not silently folded in either"
