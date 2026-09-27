"""DL-G8: what the research loop does next, decided as a pure function of what it can see.

It returns an action; it never performs one.  That split is the whole design: the expensive, stateful
half (enumerate, score, validate) already exists as `starquant_cli.research_cmd`, and wrapping it in a
loop that also decides would produce a scheduler nobody can test without a data archive and an hour.

The order is fixed and it is not a preference.  Mining before checking the budget would charge the
family for a search the budget was going to refuse anyway; checking parity before booking would ask a
question about columns that no book has yet decided to use.  Each step's precondition is the previous
step's output, which is why WAIT is a legitimate answer at every position rather than a failure.

It touches `.starquant/live` never.  The research machine and the trading machine share a git remote and
an append-only ledger; the moment this module reads live state, a research run's timing becomes a
function of what the book happens to be doing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from starquant_governance.budget import LedgerBudget, mine_refusals, refusals
from starquant_governance.policy import Policy

MINE = "mine"
VALIDATE = "validate"
BOOK = "book"
PARITY = "parity"
QUEUE = "queue"
WAIT = "wait"


@dataclass(frozen=True)
class Context:
    """What the scheduler is allowed to know.  Everything here is read from an artefact, not inferred."""

    search_space_digest: str
    last_mined_space_digest: str = ""
    shortlist_candidates: int = 0  # survivors of the last search, still unvalidated
    validated_unbooked: int = 0
    booked_without_parity: int = 0
    parity_met_unqueued: int = 0
    budget: LedgerBudget | None = None
    wanted_trials: int = 0
    # 0/1 rather than a float, so it folds into `load_bearing`'s "the other reading" exactly as every
    # other unreadable field here does.  Computed by `assemble.gate_has_passed_the_space` from two
    # measurements; this module is handed the answer, never the arithmetic.
    mined_gate_passed_best: int = 0


@dataclass(frozen=True)
class Action:
    kind: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


def next_action(context: Context, policy: Policy | None = None) -> Action:
    """The next thing to do, or WAIT with the reason it is not any of the others.

    WAIT always carries a reason.  A scheduler that returns "nothing to do" with no explanation is one
    a person cannot tell apart from a scheduler that is broken, and this one is meant to run unattended
    on a second machine.
    """
    policy = policy or Policy()
    blocked: list[str] = []

    # Latest first: a shortlist that has already been produced is work in hand, and re-enumerating
    # before spending it is how a family gets charged twice for one hypothesis (R2, ruling Q7).
    if context.parity_met_unqueued > 0:
        return Action(QUEUE, (f"{context.parity_met_unqueued} booked candidates have their parity evidence",))
    if context.booked_without_parity > 0:
        return Action(PARITY, (f"{context.booked_without_parity} booked candidates lack the M-011 obligation",))
    if context.validated_unbooked > 0:
        return Action(BOOK, (f"{context.validated_unbooked} validated candidates have no book report",))

    if context.shortlist_candidates > 0:
        stop = tuple(refusals(context.budget, context.wanted_trials)) if context.budget is not None else ()
        if stop:
            return Action(WAIT, stop)
        return Action(VALIDATE, (f"{context.shortlist_candidates} shortlisted candidates are unvalidated",))

    # R2b, before R2 and before the budget: a round the bar has already outrun costs the same and can
    # only raise the bar further.  On 2026-09-09 the `mined` gate passed the out-of-sample Sharpe of
    # the best candidate the space had ever produced, and two more rounds ran after it.  Refuses
    # SPENDING only - nothing here touches a verdict or what may reach the book - and an append-only
    # ledger is what makes not-spending the reversible direction.
    if policy.mine_requires_gate_below_best and context.mined_gate_passed_best > 0:
        blocked.append(
            "R2b: the mined gate has passed the best out-of-sample Sharpe this space has produced, so "
            "another round can only raise it further"
        )
        return Action(WAIT, tuple(blocked))
    if not policy.mine_requires_new_search_space or context.search_space_digest != context.last_mined_space_digest:
        # The mine BUDGET, not the row budget (policy 0.2.0).  Asking `refusals` here is what made a
        # 514-row search impossible inside a 170-row window, in every window, forever.
        stop = tuple(mine_refusals(context.budget)) if context.budget is not None else ()
        if stop:
            return Action(WAIT, stop)
        return Action(MINE, (f"search space {context.search_space_digest} has not been enumerated",))
    blocked.append(f"R2: search space {context.search_space_digest} was already enumerated")

    return Action(WAIT, tuple(blocked))


def parity_satisfied(status: Mapping[str, Any] | None) -> tuple[bool, str]:
    """M-011 / T-D4-2: may a candidate that reads a metrics column leave `booked`?

    Three answers, and the middle one is the point.  No status at all and a status that could not be
    computed are BOTH "no", because the obligation is to have shown parity - not to have failed to
    disprove it.  `metrics_parity` already refuses to call zero disagreements out of zero comparisons
    agreement; this refuses to call a missing report one.

    Returned with its reason rather than as a bare bool: the reason is what `governance status` prints
    when somebody asks why a candidate has been sitting in `booked` for a month.
    """
    if not status:
        return False, "M-011: no metrics parity report"
    if not status.get("enforced"):
        return False, f"M-011: parity not measurable ({status.get('reason', 'unstated')})"
    if status.get("unmeasurable"):
        return False, f"M-011: {len(status['unmeasurable'])} symbols have no overlapping buckets"
    rate = status.get("worst_differing_rate")
    if not isinstance(rate, int | float) or rate > 0.0:
        return False, f"M-011: worst symbol disagrees on {rate} of shared buckets"
    return True, f"M-011: {status.get('symbols_compared', 0)} symbols agree on every shared bucket"


def describe(actions: Sequence[Action]) -> str:
    return "; ".join(f"{action.kind}({', '.join(action.reasons)})" for action in actions)
