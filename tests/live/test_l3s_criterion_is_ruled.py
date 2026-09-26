"""§5 L3, ruled on 2026-09-10: the no-decision reading is the gate, and the streak gets the bar.

§5 states L3 twice and the two disagree.  "7 天无 ERROR 相" counts ERROR cycles; the Testnet paragraph
of the same section says an ERROR phase "不产生任何治理决定", which KILL-AR-20 turned into
`Policy.no_decision_phases`.  On the armed record the second holds and the first cannot: 0.318 ERROR
per day gives a 10.8% chance of seven consecutive clean days, 1.2% of fourteen, 0.03% of thirty - and
the cause is the system proxy §5 names itself two paragraphs later.

**Why the no-decision reading rather than the achievable one.**  Choosing the criterion a deployment
happens to pass is the move the mine pre-registrations forbid, so the reason cannot be "the other one
fails".  It is this: only one of the two sentences has a mechanism behind it.  `no_decision_phases`
exists, is enforced, and is falsifiable per cycle - an ERROR cycle that placed an order, quarantined a
sleeve or moved the ladder would fail it and be visible in the row.  The literal count has no
mechanism; it is a tally of a phase whose definition is "we declined to act on bad data", which is the
loop working, not failing.  The contradiction predates every measurement in this file.

**And the criterion is made HARDER in the dimension that matters.**  The no-decision reading alone
cannot see a venue outage: six hours of 503s decide nothing either, and a week containing one is not
a week that proved unattended operation.  So the longest ERROR STREAK gets a bar - and the bar is not
invented.  `live status --check` already fails when the heartbeat is ERROR with `consecutive_errors
>= 3`, which is the alarm that pages the operator.  A week that contained an incident the hourly check
was paging about must not pass L3, so L3 reuses that number rather than picking one.  KILL-R6 refuted
invented seconds bars; this is the same refusal applied to a count.

The literal reading stays computed and printed.  Ruling it out of the gate is not the same as hiding
it, and the day the proxy is replaced it becomes reachable again.
"""

from __future__ import annotations

from typing import Any

from starquant_live.health import STUCK_IN_ERROR_STREAK
from starquant_live.soak import score


def _cycle(at: str, phase: str = "OK", **extra: Any) -> dict[str, Any]:
    return {"at": at, "phase": phase, "orders": [], "risk_ladder": {}, **extra}


def _week(errors_at: tuple[int, ...] = (), *, hours: int = 7 * 24) -> list[dict[str, Any]]:
    """One cycle an hour for a week, with ERROR phases at the given hour offsets."""
    return [
        _cycle(f"2026-09-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00", "ERROR" if hour in errors_at else "OK")
        for hour in range(hours + 1)
    ]


def test_the_bar_for_a_streak_is_the_one_the_hourly_check_already_uses() -> None:
    """If this number is ever picked independently of `live status --check`, one of them is invented."""
    assert STUCK_IN_ERROR_STREAK == 3


# --- the ruling -------------------------------------------------------------------------------------


def test_a_clean_week_passes_every_reading() -> None:
    reading = score(_week())

    assert reading.literal_pass is True
    assert reading.no_decision_pass is True
    assert reading.passes is True


def test_scattered_errors_that_decided_nothing_now_pass() -> None:
    """The measured shape: two ERROR cycles in the week, neither of which did anything."""
    reading = score(_week(errors_at=(30, 100)))

    assert reading.error_cycles == 2
    assert reading.literal_pass is False, "the literal reading still fails, and is still reported"
    assert reading.no_decision_pass is True
    assert reading.passes is True, "this is the ruling"


def test_an_error_cycle_that_decided_something_fails_whatever_the_streak() -> None:
    """KILL-AR-20 failing in practice: the one thing the no-decision reading is there to catch."""
    cycles = _week()
    cycles[30] = _cycle("2026-09-02T06:00:00+00:00", "ERROR", orders=[{"symbol": "BTCUSDT"}])

    reading = score(cycles)

    assert reading.deciding_errors
    assert reading.no_decision_pass is False
    assert reading.passes is False


def test_a_streak_at_the_hourly_checks_bar_fails_even_though_it_decided_nothing() -> None:
    """Three in a row is `live status --check`'s own ERROR condition; a week holding one is not clean."""
    reading = score(_week(errors_at=(30, 31, 32)))

    assert reading.longest_error_streak == 3
    assert reading.no_decision_pass is True, "no decision was taken - the older reading cannot see this"
    assert reading.passes is False, "and this is why the streak needed a bar"


def test_a_streak_one_short_of_the_bar_still_passes() -> None:
    """The bar is the alarm's, so two in a row - which never paged anyone - must not fail L3."""
    reading = score(_week(errors_at=(30, 31)))

    assert reading.longest_error_streak == 2
    assert reading.passes is True


def test_a_short_soak_fails_on_length_alone() -> None:
    reading = score(_week(hours=48))

    assert reading.long_enough is False
    assert reading.passes is False


def test_a_broken_transaction_chain_fails_regardless() -> None:
    assert score(_week(), transactions_closed=False).passes is False


def test_an_unknown_transaction_chain_does_not_fail_the_soak() -> None:
    """`None` is "no log to read", which is not evidence of a broken chain - the same refusal elsewhere."""
    assert score(_week(), transactions_closed=None).passes is True


def test_the_literal_reading_is_still_computed_after_being_ruled_out_of_the_gate() -> None:
    """Ruling it out of the gate is not deleting it: the day the proxy is fixed it is reachable again."""
    reading = score(_week(errors_at=(30,)))

    assert reading.error_cycles == 1
    assert reading.literal_pass is False
    assert "7 天无 ERROR 相" in __import__("starquant_live.soak", fromlist=["render"]).render(reading)
