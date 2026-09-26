"""The weekly report's two governance readings: alpha effort share and pre-registration order.

The usage disciplines of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md` that a
report can check: effort goes to alpha (operator target 0.90, 2026-09-04), and a hypothesis is
written down before its result is seen (DL-K3 / KILL-R9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from starquant_live.report_common import _parsed

ALPHA_EFFORT_TARGET = 0.90  # operator decision 2026-09-04; see docs/RESEARCH_LOG.md


def effort_share(changed_lines: Mapping[str, int]) -> dict[str, Any]:
    """How much of a period's authored work went into alpha, against the 90% target.

    The target cannot be read off the source tree: reaching 90% of *lines* would mean 68,706 lines of
    signal code against today's 3,661, and bloated signal code is exactly what the rebuild deleted.
    The accumulated 22% is sunk - an exchange client, a live loop, a data pipeline and a CLI have a floor
    that does not shrink because the goal changed.  What the goal can govern is the *next* line written,
    so this measures the share of newly authored lines, and generated evidence under ``reports/`` is
    excluded because writing a report is not effort.

    Tests are counted with the thing they test, since a test for the exit overlay is live-loop work and a
    test for a signal is alpha work.
    """
    buckets: dict[str, int] = {"alpha": 0, "research": 0, "infrastructure": 0}
    for path, lines in changed_lines.items():
        if path.startswith("reports/"):
            continue
        if path.startswith(("starquant_alpha/", "tests/alpha/")):
            buckets["alpha"] += lines
        elif path.startswith(("docs/RESEARCH_LOG", "docs/analysis/")):
            buckets["research"] += lines
        else:
            buckets["infrastructure"] += lines
    total = sum(buckets.values())
    share = (buckets["alpha"] + buckets["research"]) / total if total else None
    return {
        "lines": buckets,
        "total": total,
        "alpha_share": share,
        "target": ALPHA_EFFORT_TARGET,
        "on_target": None if share is None else share >= ALPHA_EFFORT_TARGET,
    }


# DL-K3 landed on this date, and C-P6's rule applies to it exactly as it does to DL-K1: a mechanism
# that lands today judges tomorrow's runs.  Run against the archive the first time, this check produced
# nine FAILs and not one was a finding - seven mined validations with no `mined` ledger rows because
# DL-K2 landed the same day, and two reports whose log commit lands an hour later, which is a batch
# commit at the end of a session.  A commit timestamp says when the text was SAVED, not when it was
# written, and this check cannot tell those apart; nine lines of noise train an operator to skip the
# section, which is worse than not having one.
PREREGISTRATION_EFFECTIVE_FROM = "2026-09-07T00:00:00+00:00"


def preregistration_skipped(reports: Sequence[Mapping[str, Any]], *, effective_from: str) -> int:
    """How many reports this check declines to judge.  Reported, never silent."""
    boundary = _parsed(effective_from)
    if boundary is None:
        return 0
    return sum(1 for report in reports if (_parsed(report.get("generated_at")) or boundary) < boundary)


def preregistration_problems(
    reports: Sequence[Mapping[str, Any]],
    *,
    first_mentioned: Mapping[str, str | None],
    search_charged: Mapping[str, str | None],
    effective_from: str = "",
) -> list[str]:
    """DL-K3 / KILL-R9: report the validations whose hypothesis was not registered before the result.

    Two orderings, because there are two kinds of strategy.  A hand-written one is registered by name,
    so the earliest commit to ``docs/RESEARCH_LOG.md`` mentioning it has to predate the report.  A
    mined one cannot be: its id is DERIVED from the search, so the hash provably cannot appear in a
    commit written before the run that produced it.  What must precede a mined candidate is the search
    itself - the mine that enumerated it and charged it to the ledger (DL-K2) - and checking its hash
    against the log would only confirm that somebody wrote the verdict down afterwards.

    Silence is never a pass.  A strategy the log never mentions, a candidate no search ever charged and
    a timestamp that will not parse are all reported: a check that skips what it cannot read is a check
    that reports success it did not perform, which is the failure mode P19 found five times in a row.
    """
    boundary = _parsed(effective_from)
    problems: list[str] = []
    for report in reports:
        strategy = str(report.get("strategy", ""))
        path = str(report.get("path", strategy))
        produced = _parsed(report.get("generated_at"))
        if boundary is not None and produced is not None and produced < boundary:
            continue  # counted by `preregistration_skipped`, not judged here
        if produced is None:
            problems.append(f"{path}: its own timestamp could not be read, so nothing about its order is known")
            continue
        if strategy.startswith("mined_"):
            candidate = strategy.removeprefix("mined_")
            charged = _parsed(search_charged.get(candidate))
            if charged is None:
                problems.append(
                    f"{path}: no search ever charged candidate {candidate} to the ledger, so this "
                    "validation has no enumerated space behind it (DL-K2)"
                )
            elif charged > produced:
                problems.append(
                    f"{path}: validated at {produced.isoformat()} but the search that found {candidate} "
                    f"was only charged at {charged.isoformat()}"
                )
            continue
        mentioned = _parsed(first_mentioned.get(strategy))
        if mentioned is None:
            problems.append(
                f"{path}: {strategy} is never mentioned in docs/RESEARCH_LOG.md's history, so no "
                "pre-registration precedes this report"
            )
        elif mentioned > produced:
            problems.append(
                f"{path}: {strategy} was reported at {produced.isoformat()} but first appears in the "
                f"log at {mentioned.isoformat()} - the pre-registration was written after the result"
            )
    return problems
