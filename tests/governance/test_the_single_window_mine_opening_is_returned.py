"""0.3.1 opened one extra mine round for one window.  This is what makes "one window" a fact.

The operator ruled a fifth round on 2026-09-10, for a window that allows four, because the 09-09 round
raced the spot ingest and never enumerated the 18 basis shapes.  The ruling was explicitly not a
standing increase - and a "just this once" recorded only in prose is a promise, which is precisely the
category the 2026-09-09 audit spent a day separating from controls.

So the reversion has an executing check.  From `SINGLE_WINDOW_MINE_OPENING_ENDS` this test fails, every
run, until somebody sets `max_mine_rounds_per_window` back to `STANDING_MINE_ROUNDS`.  It is meant to
be a nuisance on exactly one day and invisible before it: a test that can only fail in the future is
still a control, and one that never fails is the thing being guarded against.

Deliberately not a warning, a log line or a comment.  Each of those was available and each is what the
audit kept finding in place of a gate.

2026-09-25: the check did its job before its day.  Asked about the date ahead of it, the operator
made the fifth round standing, so `STANDING_MINE_ROUNDS` moved 4 -> 5 and the number stayed 5.  From
2026-10-03 the first test below holds because the standing value moved, not because the round was
returned - the second of the two paths its own message names.  Why no `POLICY_VERSION` bump: see there.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starquant_governance.policy import (
    SINGLE_WINDOW_MINE_OPENING_ENDS,
    STANDING_MINE_ROUNDS,
    Policy,
)


def test_the_single_window_mine_opening_is_returned() -> None:
    ends = datetime.fromisoformat(SINGLE_WINDOW_MINE_OPENING_ENDS)
    if datetime.now(UTC) < ends:
        return  # the window is still open; nothing to return yet
    assert Policy().max_mine_rounds_per_window == STANDING_MINE_ROUNDS, (
        f"the extra mine round was opened for the window ending {SINGLE_WINDOW_MINE_OPENING_ENDS} and "
        f"that window has closed.  Set `max_mine_rounds_per_window` back to {STANDING_MINE_ROUNDS} and "
        "bump POLICY_VERSION, or - if the operator wants it standing - say so at POLICY_VERSION and "
        "move `STANDING_MINE_ROUNDS`, which is a decision rather than a lapse."
    )


def test_the_opening_is_one_round_and_not_more() -> None:
    """An opening is one round above the standing value, as 0.3.1's was.  Two above is not that shape."""
    assert Policy().max_mine_rounds_per_window <= STANDING_MINE_ROUNDS + 1


def test_the_standing_value_is_what_the_operator_ruled() -> None:
    """4 from 0.3.0; 5 from the operator's ruling of 2026-09-25.  Moving it again is a new ruling, not a drift."""
    assert STANDING_MINE_ROUNDS == 5
