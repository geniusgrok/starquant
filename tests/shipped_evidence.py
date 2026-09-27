"""The one place that records: the shipped registry knowingly cites evidence its own gate refuses.

`test_the_shipped_registry_runs_what_its_evidence_validated` owns the contract "the shipped registry
and profile are a pair the real gate accepts", and `tests/governance/`'s drill fixture says so in as
many words rather than re-deriving it.  On 2026-09-19 the operator pointed tsmom at
`tsmom-validation-20260919T081914Z.json`, whose verdict is FAIL, so that contract is deliberately
false until the construction freeze ends.

**Why the pointer moved to evidence that does not clear.** Both available pointers were already
refused, on different gates - measured, not argued:

    20260913T182325Z (WEAK_PASS)  evidence passes; `registry_dataset_problems` refuses - the
                                  membership table was rebuilt (union 211 -> 212, refreshes
                                  2042 -> 2056) and that report no longer describes the data on disk
    20260919T081914Z (FAIL)       dataset passes - it was produced on today's table; evidence
                                  refuses on the honest FAIL

`live_cmd.py` is `if problems or dataset.blocking:` and both land in the same `raise`, so the choice
never changed whether an armed loop can start - only which gate names the reason.  It has been
`deploy/run_live.sh`'s D-041 bridge keeping the loop armed either way, and this file expires on the
same day for the same reason.

**What this does NOT do.** It hides exactly one string, by exact match.  A parameter drift, a
construction divergence, a digest mismatch or a second strategy failing its gate all still come
through - that is the difference between an exemption and a muted test.

**What it does not make go away, either.** In production `governance apply` is blocked while this
problem stands: the gate reads the registry file, the file does not clear, so even a comment-only
edit rolls back.  That is a real cost of the pointer move and it is not exempted anywhere - only the
drill that tests the transaction machinery is, because a drill must not answer for that decision.
Autonomous registry writes are therefore off until the pointer cites evidence that clears, or until
this date, whichever comes first.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

# `deploy/run_live.sh`'s `BRIDGE_UNTIL`.  The same date twice is a duplication worth paying for: the
# shell script cannot import Python and the test suite cannot read a bash variable, so what keeps them
# together is `test_the_exemption_expires_with_the_bridge_it_belongs_to` below, which greps the script.
EXEMPT_UNTIL = date(2026, 10, 13)

# Exact strings, not patterns.  A pattern would quietly grow to cover the next failure too.
EXEMPTED: tuple[str, ...] = ("tsmom: evidence verdict FAIL does not allow live use",)


def _today() -> date:
    return datetime.now(UTC).date()


def unexempted(problems: Iterable[str]) -> list[str]:
    """`problems` minus the knowingly-accepted ones - and minus nothing at all once the bridge expires.

    After `EXEMPT_UNTIL` this is the identity function, so every caller goes red on the same day the
    armed loop stops being allowed to start on this evidence.  That is the safe direction and it needs
    no one to remember: the repository keeps re-learning that a flag a human has to recall is the next
    incident.
    """
    if _today() >= EXEMPT_UNTIL:
        return list(problems)
    return [problem for problem in problems if problem not in EXEMPTED]
