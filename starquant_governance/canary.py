"""L4 / DL-G5: six deployment-health checks over a shadow run, and the one thing they do not do.

**A canary does not filter alpha** (KILL-AR-04).  The Phase 7 review's sharpest correction was that
calling this a filter would let a bad candidate through on a technicality and, worse, let a good one
be blocked by an unrelated venue hiccup - and then be recorded as evidence against the candidate.  It
answers one question: *would this registry, deployed, behave like a working deployment?*  Whether the
sleeve has any edge is R3's 1/3 budget and the P&L stop's problem, not this module's.

The shadow is `live run --dry-run --state-dir .starquant/live-shadow` against the candidate registry, and
every check below is computed against the ARMED loop's own cycles over the same window rather than
against a constant.  A constant would fail the whole canary on a day the venue was slow, which is the
false negative that teaches an operator to ignore it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SOAK_CYCLES = 168


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CanaryResult:
    checks: tuple[Check, ...] = field(default_factory=tuple)
    soaked: int = 0

    @property
    def healthy(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.passed)


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(key)) / len(rows)


def _longest_error_streak(rows: Sequence[Mapping[str, Any]]) -> int:
    longest = streak = 0
    for row in rows:
        streak = streak + 1 if row.get("phase") == "ERROR" else 0
        longest = max(longest, streak)
    return longest


def evaluate(
    shadow: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    *,
    soak_cycles: int = SOAK_CYCLES,
    gate_refusals: int = 0,
    max_error_streak: int = 2,
    aliases: Mapping[str, str] | None = None,
) -> CanaryResult:
    """The six checks of §5's L4 row, in the order a deployment fails them.

    ``gate_refusals`` is supplied rather than recomputed: whether the candidate registry passed the
    startup gate is a fact about a process that already ran, and asking a second implementation would
    reintroduce the divergence `promote` was careful to avoid.

    ``aliases`` is `CONSTRUCTION_ALIASES`, and `construction_stable` is wrong without it: the raw
    digest has moved six times on the armed record since 2026-09-04 while the CANONICAL construction
    moved once, because a renamed field changes the hash and nothing else.  Measured 2026-09-09 by
    pointing this function at the armed loop's own cycles: 6 distinct digests, and a candidate would
    have been called unhealthy for a deployment that never changed.  Passed in rather than imported
    so the package stays free of `starquant_live`.
    """
    resolve = dict(aliases or {})
    decided = [row for row in shadow if row.get("phase") not in ("ERROR", "SKIPPED")]
    digests = {
        resolve.get(str(row.get("construction")), str(row.get("construction")))
        for row in decided
        if row.get("construction")
    }
    base_guard_rate = _rate([r for r in baseline if r.get("phase") not in ("ERROR", "SKIPPED")], "guard_reasons")
    guard_rate = _rate(decided, "guard_reasons")
    streak = _longest_error_streak(shadow)

    over_cap = [
        f"{row.get('at')}: {order.get('symbol')}"
        for row in decided
        for order in (row.get("skipped") or [])
        if str(order.get("reason")) == "PARTICIPATION_CAP"
    ]
    outside = [
        f"{row.get('at')}: {symbol}"
        for row in decided
        for symbol in (row.get("targets") or {})
        if symbol not in set(row.get("universe") or [])
    ]

    checks = (
        Check("startup_gate", gate_refusals == 0, f"{gate_refusals} refusals"),
        Check("soak", len(shadow) >= soak_cycles, f"{len(shadow)}/{soak_cycles} cycles"),
        Check("construction_stable", len(digests) <= 1, f"{len(digests)} distinct construction digests"),
        # `<=` with a tolerance rather than `<`: guards firing at the same rate as the armed book is
        # the expected outcome, and a canary that demands an improvement is asking the wrong question.
        Check(
            "guard_rate",
            guard_rate <= base_guard_rate + 0.05,
            f"shadow {guard_rate:.3f} vs armed {base_guard_rate:.3f}",
        ),
        Check("no_error_streak", streak <= max_error_streak, f"longest ERROR streak {streak}"),
        # Planned orders inside the participation cap, and targets inside the universe.  Both are
        # deployment facts: an order the rebalancer would truncate and a target for a symbol the loop
        # does not manage are wiring mistakes, and neither says anything about the candidate's edge.
        Check("participation", not over_cap, f"{len(over_cap)} planned orders above the cap"),
        Check("targets_in_universe", not outside, f"{len(outside)} targets outside the managed universe"),
    )
    return CanaryResult(checks, soaked=len(shadow))
