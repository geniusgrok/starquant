"""DL-G8 / T-G8-1 and T-G8-2: the research loop's next step, as a pure function.

It returns an action and never performs one.  The expensive half already exists as
`starquant_cli.research_cmd`; wrapping it in a loop that also decided would produce a scheduler nobody
can test without a data archive and an hour.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starquant_governance.budget import LedgerBudget
from starquant_governance.policy import Policy
from starquant_governance.scheduler import BOOK, MINE, PARITY, QUEUE, VALIDATE, WAIT, Context, next_action

FULL = LedgerBudget(window_start=datetime(2026, 9, 1, tzinfo=UTC).isoformat(), spent=170, allowed=170)
ROOM = LedgerBudget(window_start=datetime(2026, 9, 1, tzinfo=UTC).isoformat(), spent=0, allowed=170)


def test_t_g8_1_an_unchanged_search_space_does_not_mine() -> None:
    """R2.  The 2026-09-08 incident in one assertion."""
    context = Context(search_space_digest="abc", last_mined_space_digest="abc", budget=ROOM, wanted_trials=10)
    action = next_action(context)
    assert action.kind == WAIT
    assert action.reasons and action.reasons[0].startswith("R2")


def test_a_changed_search_space_does_mine() -> None:
    action = next_action(
        Context(search_space_digest="abc", last_mined_space_digest="xyz", budget=ROOM, wanted_trials=10)
    )
    assert action.kind == MINE


def test_a_mine_is_gated_on_the_mine_budget_not_the_row_budget() -> None:
    """Policy 0.2.0.  A full row budget must not block a mine, and a spent one must not either."""
    spent_rows = LedgerBudget(FULL.window_start, spent=170, allowed=170, mine_rounds=0, allowed_mine_rounds=1)
    assert next_action(Context(search_space_digest="a", last_mined_space_digest="x", budget=spent_rows)).kind == MINE

    used_round = LedgerBudget(FULL.window_start, spent=0, allowed=170, mine_rounds=1, allowed_mine_rounds=1)
    action = next_action(Context(search_space_digest="a", last_mined_space_digest="x", budget=used_round))
    assert action.kind == WAIT and "already run 1 mine round(s)" in action.reasons[0]


def test_t_g8_2_an_exhausted_budget_stops_validate_rather_than_truncating_it() -> None:
    context = Context(search_space_digest="a", shortlist_candidates=5, budget=FULL, wanted_trials=5)
    action = next_action(context)
    assert action.kind == WAIT
    assert action.reasons[0].startswith("R1")


def test_work_in_hand_is_spent_before_a_new_search_is_started() -> None:
    """Re-enumerating before spending a shortlist is how a family gets charged twice (ruling Q7)."""
    context = Context(
        search_space_digest="abc", last_mined_space_digest="xyz", shortlist_candidates=3, budget=ROOM, wanted_trials=1
    )
    assert next_action(context).kind == VALIDATE


def test_the_pipeline_runs_backwards_from_the_step_closest_to_the_queue() -> None:
    base = {"search_space_digest": "a", "last_mined_space_digest": "a"}
    assert (
        next_action(Context(**base, parity_met_unqueued=1, booked_without_parity=1, validated_unbooked=1)).kind == QUEUE
    )
    assert next_action(Context(**base, booked_without_parity=1, validated_unbooked=1)).kind == PARITY
    assert next_action(Context(**base, validated_unbooked=1)).kind == BOOK


def test_wait_always_carries_a_reason() -> None:
    """A scheduler meant to run unattended must be distinguishable from a broken one."""
    for context in (
        Context(search_space_digest="a", last_mined_space_digest="a"),
        Context(search_space_digest="a", shortlist_candidates=1, budget=FULL, wanted_trials=1),
    ):
        action = next_action(context)
        assert action.kind == WAIT and action.reasons


def test_the_rule_can_be_turned_off_only_in_the_policy() -> None:
    """R10: the reopen path is a policy change with a version bump, not a scheduler flag."""
    relaxed = Policy(mine_requires_new_search_space=False)
    context = Context(search_space_digest="abc", last_mined_space_digest="abc", budget=ROOM, wanted_trials=1)
    assert next_action(context).kind == WAIT
    assert next_action(context, relaxed).kind == MINE
    assert relaxed.digest() != Policy().digest(), "turning a rule off must move the digest the loop records"
