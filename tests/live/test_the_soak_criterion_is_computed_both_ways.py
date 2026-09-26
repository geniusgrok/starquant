"""§5 states L3's criterion twice and the two disagree; nothing computed either until 2026-09-09.

The L3 row says "7 天无 ERROR 相".  Two paragraphs later the same section says the path to the venue
crosses a proxy that returns 503 in bursts and that an ERROR phase produces no governance decision -
which KILL-AR-20 turned into `Policy.no_decision_phases`.  One counts ERROR cycles; the other is a
claim about their consequences, and on the armed record the second holds while the first cannot:
0.318 ERROR/day over 6.29 days, longest clean run 4.92 days, and a Poisson fit puts seven consecutive
clean days at 10.8%.

So this module reports both and rules on neither.  The ruling is the operator's; a scorer that quietly
picked one would be making it.
"""

from __future__ import annotations

from typing import Any

import pytest

from starquant_live.soak import score


def _cycle(hour: int, phase: str | None = None, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "at": f"2026-09-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00",
        "orders": [],
        "risk_ladder": {},
    }
    if phase:
        row["phase"] = phase
    row.update(extra)
    return row


def test_a_clean_week_passes_both_readings() -> None:
    reading = score([_cycle(h) for h in range(24 * 8)])
    assert reading.literal_pass and reading.no_decision_pass
    assert reading.error_cycles == 0


def test_a_week_with_one_harmless_error_splits_the_two_readings() -> None:
    """The whole point, in one assertion: the same record passes one criterion and fails the other."""
    rows = [_cycle(h) for h in range(24 * 8)]
    rows[100] = _cycle(100, "ERROR")
    reading = score(rows)
    assert not reading.literal_pass, "one ERROR phase is one too many for the literal reading"
    assert reading.no_decision_pass, "it decided nothing, which is the other reading's whole question"
    assert reading.deciding_errors == ()
    assert any("KILL-AR-20" in note for note in reading.notes)


def test_an_error_cycle_that_decided_something_fails_the_reading_that_matters() -> None:
    """KILL-AR-20 failing in practice: the guard has to be able to catch it, or it guards nothing."""
    rows = [_cycle(h) for h in range(24 * 8)]
    rows[100] = _cycle(100, "ERROR", orders=[{"symbol": "BTCUSDT"}], leaving=["CYSUSDT"])
    reading = score(rows)
    assert not reading.no_decision_pass
    assert len(reading.deciding_errors) == 1
    assert "orders" in reading.deciding_errors[0] and "leaving" in reading.deciding_errors[0]


def test_a_quiet_cycle_is_not_read_as_a_decision() -> None:
    """The loop writes `orders: []` and `risk_ladder: {}` every cycle; presence is not a decision."""
    rows = [_cycle(h) for h in range(24 * 8)]
    rows[100] = _cycle(100, "ERROR", orders=[], risk_ladder={}, leaving=[], quarantined=[])
    assert score(rows).no_decision_pass


def test_a_short_soak_fails_both_however_clean_it_is() -> None:
    """Length is not a formality: a criterion about seven days cannot be met by six perfect ones."""
    reading = score([_cycle(h) for h in range(24 * 6)])
    assert not reading.long_enough
    assert not reading.literal_pass and not reading.no_decision_pass


def test_a_broken_transaction_chain_fails_both() -> None:
    rows = [_cycle(h) for h in range(24 * 8)]
    reading = score(rows, transactions_closed=False)
    assert not reading.literal_pass and not reading.no_decision_pass


def test_the_error_streak_is_reported_because_neither_reading_covers_it() -> None:
    """One 503 is the proxy blinking; six hours of them is the venue being gone.  Reported, not gated."""
    rows = [_cycle(h) for h in range(24 * 8)]
    for h in range(100, 106):
        rows[h] = _cycle(h, "ERROR")
    reading = score(rows)
    assert reading.longest_error_streak == 6
    assert reading.no_decision_pass, "not gated on yet - the operator has not ruled"
    assert any("streak" in note for note in reading.notes)


def test_the_measured_armed_record_is_what_this_module_says_it_is() -> None:
    """The numbers the assessment rests on, recomputed from a record shaped like the real one."""
    rows = [_cycle(h) for h in range(151)]  # 6.25 days at 1h
    rows[24] = _cycle(24, "ERROR")
    rows[142] = _cycle(142, "ERROR")
    reading = score(rows, required_days=6.0)
    assert reading.error_cycles == 2 and reading.longest_error_streak == 1
    assert reading.longest_clean_days == pytest.approx((142 - 24) / 24.0, abs=0.01)
    assert not reading.literal_pass and reading.no_decision_pass
