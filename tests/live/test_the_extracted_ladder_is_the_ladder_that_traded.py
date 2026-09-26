"""Bit-for-bit equivalence between `ladder_step` and the engine method it was lifted out of.

D-033's technique, for the same reason it was used there: an extraction that changes what the live
loop does is a behaviour change wearing a refactor's name, and the only honest way to say it did not
is to run both against the same inputs and compare every output.

There are three outputs, and all three are compared: the block written into `cycles.jsonl`, the rung
persisted into `state.risk_ladder`, and the operator messages - because the messages are the only part
an operator ever sees, and a silently reworded alert is a real regression in a system where paging is
deduplicated on the text.

The comparison itself was a throwaway: the old body was kept as `_dead_risk_ladder`, both were run
over 128 combinations of standing rung x base x drawdown, and they were identical on all three outputs.
Then the old body was deleted, in the same commit.  What is left here is the successor - the behaviour
those 128 combinations covered, pinned against the pure function so it cannot drift back.
"""

from __future__ import annotations

from typing import Any

import pytest

from starquant_alpha.overlays.ladder import ladder_step, rung_scalar, rung_target
from starquant_governance.policy import Policy

GRACE = Policy().drawdown_grace_cycles
RUNGS = Policy().drawdown_ladder
BASE = 0.60
BAR = 1_757_000_000_000
NOW = "2026-09-15T00:00:00+00:00"


def _reading(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "enforced": True,
        "value": -0.10,
        "attributed": -1_000.0,
        "ruler": "attributed_pnl+unrealized",
        "marked_rows": 42,
        "equity_over_peak": 0.97,
    }
    base.update(overrides)
    return base


def _step(reading: dict[str, Any], standing: dict[str, Any] | None = None) -> Any:
    return ladder_step(
        reading=reading,
        standing=standing or {},
        base=BASE,
        rungs=RUNGS,
        grace_cycles=GRACE,
        bar_open_ms=BAR,
        now=NOW,
    )


# --- the rule itself --------------------------------------------------------------------------------


def test_the_policy_and_the_pure_function_are_the_same_rule() -> None:
    """`Policy.throttle_scalar` now delegates; if the two ever disagree there are two ladders again."""
    for drawdown in (0.0, -0.10, -0.48, -0.49, -0.50, -0.69, -0.70, -0.95):
        assert Policy().throttle_scalar(drawdown) == rung_target(drawdown, RUNGS)


def test_rungs_are_checked_deepest_first() -> None:
    """-0.70 must get the deeper rung, not the first one it happens to clear."""
    assert rung_target(-0.70, RUNGS) == 0.30
    assert rung_target(-0.49, RUNGS) == 0.45
    assert rung_target(-0.48, RUNGS) is None


def test_a_rung_above_the_running_target_is_clamped_and_reported() -> None:
    """A de-escalation ladder must never ADD size, and a mis-calibration must not read as quiet."""
    scalar, above = rung_scalar(0.45, base=0.30)

    assert scalar == 1.0, "0.45 against k=0.30 is 1.5x - an amplifier wearing a brake's name"
    assert above is True


# --- the state machine ------------------------------------------------------------------------------


def test_above_the_first_rung_nothing_is_persisted_or_said() -> None:
    step = _step(_reading(value=-0.02))

    assert step.standing is None, "leave the persisted rung untouched, which is not the same as clearing"
    assert step.block["acting"] is False and step.block["scalar"] == 1.0
    assert not step.alerts and not step.warnings


def test_climbing_back_above_the_first_rung_clears_the_standing_rung_once() -> None:
    standing = {"cycles": 5, "rung": 0.45, "vol_target": 0.45, "scalar": 0.75, "acting": True}

    step = _step(_reading(value=-0.02), standing)

    assert step.standing == {}, "an explicit clear, not `None`"
    assert len(step.alerts) == 1 and "恢复" in step.alerts[0]
    assert step.warnings == ("risk ladder cleared at attributed drawdown -0.0200",)


def test_the_first_crossing_alerts_and_does_not_cut() -> None:
    """The grace is the point: one late income page must not halve the risk budget by itself."""
    step = _step(_reading(value=-0.55))

    assert step.block["acting"] is False, "first crossing does not act"
    assert step.block["scalar"] == 1.0
    assert step.standing is not None and step.standing["cycles"] == 1
    assert "不缩仓" in step.alerts[0]


def test_it_acts_only_after_the_grace_is_spent() -> None:
    standing: dict[str, Any] = {}
    for cycle in range(1, GRACE + 2):
        step = _step(_reading(value=-0.55), standing)
        standing = dict(step.standing or {})
        assert step.block["cycles"] == cycle

    assert standing["acting"] is True
    assert step.block["acting"] is True
    assert step.block["scalar"] == pytest.approx(0.45 / BASE)
    assert "已生效" in step.alerts[0]


def test_acting_pages_once_per_rung_not_once_per_cycle() -> None:
    """DL-L3 / KILL-R7's shape: a venue down for six hours says so once, not six times."""
    acting = {"cycles": GRACE + 1, "rung": 0.45, "vol_target": 0.45, "scalar": 0.75, "acting": True}

    step = _step(_reading(value=-0.55), acting)

    assert step.block["acting"] is True
    assert not step.alerts, "same rung, already acting - nothing new to say"


def test_a_deeper_rung_pages_again() -> None:
    acting = {"cycles": GRACE + 1, "rung": 0.45, "vol_target": 0.45, "scalar": 0.75, "acting": True}

    step = _step(_reading(value=-0.75), acting)

    assert step.block["rung"] == 0.30
    assert step.alerts, "the rung moved, so the operator is told"


def test_a_blind_reading_holds_a_standing_breach_and_cannot_start_one() -> None:
    """ "Cannot compute" is not "recovered", and it is not "breached" either."""
    acting = {"cycles": 9, "rung": 0.45, "vol_target": 0.45, "scalar": 0.75, "acting": True}

    held = _step(_reading(enforced=False, why="no attributed rows yet"), acting)
    assert held.block["acting"] is True and held.block["held_blind"] is True
    assert held.block["scalar"] == 0.75
    assert held.standing is None, "a blind cycle must not rewrite the rung it cannot measure"

    quiet = _step(_reading(enforced=False, why="no attributed rows yet"))
    assert quiet.block["acting"] is False
    assert quiet.block["why"] == "no attributed rows yet"
    assert "held_blind" not in quiet.block


def test_since_bar_ms_survives_across_cycles() -> None:
    """The breach's start, so the record can say how long it has been standing."""
    first = _step(_reading(value=-0.55))
    assert first.standing is not None and first.standing["since_bar_ms"] == BAR

    later = ladder_step(
        reading=_reading(value=-0.55),
        standing=first.standing,
        base=BASE,
        rungs=RUNGS,
        grace_cycles=GRACE,
        bar_open_ms=BAR + 3_600_000,
        now=NOW,
    )
    assert later.standing is not None and later.standing["since_bar_ms"] == BAR


def test_nothing_in_the_step_reads_a_clock_a_file_or_a_venue() -> None:
    """What makes it replayable: `now` is an argument, so a replay reproduces the row it is replaying."""
    import inspect

    source = inspect.getsource(ladder_step)

    for forbidden in ("utc_now_iso", "datetime.now", "read_jsonl", "await ", "self."):
        assert forbidden not in source, f"{forbidden} would make this un-replayable"
