"""R1: how many trials a window may buy, read off the ledger rather than remembered.

R3, R4, R5 and R7 are properties of the book's state and live in `lifecycle`.  R1 is not: it is a
property of the trials ledger, which is append-only, shared between sessions, and the only record that
can say what a window actually cost.  Keeping it here rather than in `lifecycle` is what stops the
state machine from holding a counter that a parallel session's `research validate` has already made
wrong - the 2026-09-08 incident was exactly that shape, a search charging 514 rows with nothing on the
terminal saying so.

The count is of DISTINCT trials, folded the way `unique_trials` folds them, because that is what the
DSR denominator reads.  Counting raw lines would charge a replay twice and make the budget stricter
than the thing it is budgeting.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from starquant_alpha.validation.ledger import MINED_SEARCH_STRATEGY, TrialRecord, all_trials, unique_trials
from starquant_governance.policy import Policy


@dataclass(frozen=True)
class LedgerBudget:
    """What this window has spent, in the two units R1 counts since policy 0.2.0.

    Rows and mine rounds are separate because they answer different questions.  A `validate` is one
    selection and writes a handful of rows; a `mine` is also ONE selection and writes 514, and
    charging the second by its row count made it structurally impossible to run in a monthly window.
    """

    window_start: str
    spent: int  # rows, excluding the shared `mined` bucket
    allowed: int
    mine_rounds: int = 0
    allowed_mine_rounds: int = 1
    mined_rows: int = 0  # reported, never charged: it is the DSR denominator, not the budget

    @property
    def remaining(self) -> int:
        return max(0, self.allowed - self.spent)

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.allowed

    @property
    def mine_exhausted(self) -> bool:
        return self.mine_rounds >= self.allowed_mine_rounds


def _recorded_at(record: TrialRecord) -> datetime | None:
    try:
        return datetime.fromisoformat(record.recorded_at)
    except ValueError:
        return None


def window_spend(lines: Iterable[str], *, window_start: datetime, policy: Policy | None = None) -> LedgerBudget:
    """What this window has already bought, and what R1 still allows.

    Rows with an unreadable timestamp are counted as inside the window.  That is the conservative
    direction: an unparseable row is one this function cannot prove was bought earlier, and a budget
    that resolves its own doubt in favour of spending more is not a budget.
    """
    policy = policy or Policy()
    inside: list[TrialRecord] = []
    for record in all_trials(lines):
        when = _recorded_at(record)
        if when is None or when >= window_start:
            inside.append(record)
    mined = [record for record in inside if record.strategy == MINED_SEARCH_STRATEGY]
    charged = [record for record in inside if record.strategy != MINED_SEARCH_STRATEGY]
    return LedgerBudget(
        window_start=window_start.isoformat(),
        spent=len(unique_trials(charged, range_end_granularity_days=policy.trial_range_end_granularity_days)),
        allowed=policy.max_ledger_rows_per_window,
        # A round is a `run_id`: `research mine` writes every candidate of one enumeration under one.
        mine_rounds=len({record.run_id for record in mined}),
        allowed_mine_rounds=policy.max_mine_rounds_per_window,
        mined_rows=len(unique_trials(mined, range_end_granularity_days=policy.trial_range_end_granularity_days)),
    )


def mine_refusals(budget: LedgerBudget) -> Sequence[str]:
    """R1 for a mine round: one selection per window, whatever the space's width.

    Separate from `refusals` rather than a `wanted` of one, because the two are counted in different
    units and folding them would restore exactly the confusion 0.2.0 exists to remove.
    """
    if budget.mine_exhausted:
        return (f"R1: this window has already run {budget.mine_rounds} mine round(s) of {budget.allowed_mine_rounds}",)
    return ()


def refusals(budget: LedgerBudget, wanted: int) -> Sequence[str]:
    """R1 as the scheduler asks it: may this run of ``wanted`` trials start at all?

    A run that would cross the line is refused whole rather than truncated.  Truncating it would
    produce a search whose `declared_trials` counts candidates that were never scored, which is the
    number `research validate --prior-trials` feeds into the DSR denominator - a half-charged family
    is worse than an uncharged one.
    """
    if wanted <= 0:
        return ()
    if budget.exhausted:
        return (f"R1: the window's {budget.allowed}-trial budget is spent ({budget.spent})",)
    if wanted > budget.remaining:
        return (f"R1: {wanted} trials wanted, {budget.remaining} left of {budget.allowed} this window",)
    return ()
