"""M-G05: the divergence between what the machine ruled and what a person later thinks it should have.

This is Pre-A′'s only falsifier - "写死的规则能替代人在运行时的**决策**" is the plan's own highest-risk
assumption, and until 2026-09-10 the instrument that could refute it did not exist in any form.  It was
a row in §11 and a cell in §13, and nothing wrote, read or computed it.

**Why this is not `governance replay`.**  Replay asks whether the rules REPRODUCE decisions people
already took, and its number is M-G02 (unattributed differences, currently 0).  That is a statement
about the past, made once, against a fixed record.  M-G05 asks the opposite question in the opposite
direction: the machine rules first, a person reviews afterwards, and the disagreement is counted going
forward.  A rule set can reproduce every historical decision and still be wrong about the next one -
that is exactly what "the rules were fitted to the history" means - so the two are not substitutes.

**The one design decision that matters: the machine's verdict is recorded WHERE IT IS MADE, not by
whoever remembers.**  A sample assembled from remembered decisions is selected by the memorability of
the decision, and the memorable ones are the surprising ones.  So `record()` is called from the gates
themselves and the ledger is append-only; the human half arrives later, keyed on the verdict's id, and
its absence is visible as `pending` rather than silently shrinking the denominator.

**Direction is kept separate** (§11 says so): a machine that refuses too much and a machine that admits
too much fail differently and need different fixes.  A single rate would average them into a number
that can look healthy while both errors are large.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

LEDGER = "governance/verdicts.jsonl"

ALLOW = "allow"
REFUSE = "refuse"
AGREE = "agree"
DISAGREE = "disagree"


@dataclass(frozen=True)
class Verdict:
    """One machine ruling, and the human review of it if one has happened."""

    id: str
    at: str
    kind: str  # which gate ruled: "admission", "family_gate", ...
    subject: str  # what it ruled on: a strategy id, a candidate registry, ...
    ruling: str  # ALLOW or REFUSE
    reasons: tuple[str, ...] = ()
    reviewed_at: str = ""
    review: str = ""  # AGREE or DISAGREE, empty while pending
    review_why: str = ""

    @property
    def pending(self) -> bool:
        return self.review not in (AGREE, DISAGREE)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> Verdict | None:
        try:
            payload = json.loads(line)
        except ValueError:
            return None
        if not isinstance(payload, dict) or "id" not in payload:
            return None
        return cls(
            id=str(payload.get("id", "")),
            at=str(payload.get("at", "")),
            kind=str(payload.get("kind", "")),
            subject=str(payload.get("subject", "")),
            ruling=str(payload.get("ruling", "")),
            reasons=tuple(str(r) for r in (payload.get("reasons") or ())),
            reviewed_at=str(payload.get("reviewed_at", "")),
            review=str(payload.get("review", "")),
            review_why=str(payload.get("review_why", "")),
        )


def verdict_id(kind: str, subject: str, ruling: str, reasons: Sequence[str], at: str) -> str:
    """Stable enough to key a review on, unique enough that two rulings are two rows.

    Includes the reasons: the same gate refusing the same subject for a DIFFERENT reason is a
    different ruling, and folding them would let one review stand for a judgement nobody made.
    """
    material = "|".join([kind, subject, ruling, *sorted(reasons), at])
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def read(path: Path) -> list[Verdict]:
    """Append-only, and a later row for the same id supersedes an earlier one (that is the review)."""
    if not path.exists():
        return []
    latest: dict[str, Verdict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        verdict = Verdict.from_json(line)
        if verdict is not None:
            latest[verdict.id] = verdict
    return list(latest.values())


def ruling_key(verdict: Verdict) -> tuple[str, str, str, tuple[str, ...]]:
    """What makes two rows the SAME machine ruling: the gate, the subject, the call and the reasons.

    Deliberately not the date.  `reasons` carries the numbers the gate ruled on ("OOS 1.8087 vs
    1.5149 at N=185"), so a genuinely new ruling - a moved ledger, a flipped gate - differs here and
    lands as its own row; re-asking a question nobody has changed the answer to does not.
    """
    return (verdict.kind, verdict.subject, verdict.ruling, verdict.reasons)


def record(
    path: Path,
    *,
    kind: str,
    subject: str,
    ruling: str,
    reasons: Sequence[str] = (),
    now: datetime | None = None,
) -> Verdict:
    """Append one machine ruling.  The same ruling twice is one row, whenever the second one happens.

    Idempotence was by (kind, subject, ruling, reasons, DATE) for exactly the reason stated here -
    "a denominator that counts how often somebody typed a read-only command is not measuring the
    machine" - and the date left the hole open one day wide.  Measured 2026-09-12: three rows in this
    ledger, byte-identical reasons, one per day somebody ran `governance gate`, all three pending
    review, `governance divergence` reporting "3 pending".  Ten such days would carry M-G05 to its
    quorum of 10 on ten re-readings of one ruling - Pre-A′'s only falsifier, satisfied without a
    single decision having been made.  The day is now out of the key.
    """
    moment = now or datetime.now(UTC)
    verdict = Verdict(
        verdict_id(kind, subject, ruling, tuple(reasons), moment.date().isoformat()),
        moment.isoformat(),
        kind,
        subject,
        ruling,
        tuple(reasons),
    )
    for existing in read(path):
        if ruling_key(existing) == ruling_key(verdict):
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(verdict.to_json() + "\n")
    return verdict


def review(path: Path, identifier: str, verdict_review: str, why: str, *, now: datetime | None = None) -> Verdict:
    """Append the human half.  The original row stays; this one supersedes it on read."""
    rows = {verdict.id: verdict for verdict in read(path)}
    if identifier not in rows:
        raise KeyError(f"no verdict {identifier!r} in {path}")
    if verdict_review not in (AGREE, DISAGREE):
        raise ValueError(f"a review is {AGREE!r} or {DISAGREE!r}, not {verdict_review!r}")
    if not why.strip():
        # A disagreement with no reason cannot be acted on, and an agreement with no reason cannot be
        # told apart from not having looked.  Both are the sample being polluted by convenience.
        raise ValueError("a review has to say why; that sentence is the whole content of M-G05")
    moment = now or datetime.now(UTC)
    original = rows[identifier]
    updated = Verdict(
        original.id,
        original.at,
        original.kind,
        original.subject,
        original.ruling,
        original.reasons,
        moment.isoformat(),
        verdict_review,
        why.strip(),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(updated.to_json() + "\n")
    return updated


@dataclass(frozen=True)
class Divergence:
    """M-G05 with its directions kept apart, and its sample size in front of its rate."""

    reviewed: int = 0
    pending: int = 0
    machine_allowed_human_refused: int = 0
    machine_refused_human_allowed: int = 0
    quorum: int = 10
    threshold: float = 0.20
    by_kind: Mapping[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def disagreements(self) -> int:
        return self.machine_allowed_human_refused + self.machine_refused_human_allowed

    @property
    def rate(self) -> float | None:
        """None, not zero, below quorum.  Zero of three reviews is not a 0% divergence rate."""
        return None if self.reviewed < self.quorum else self.disagreements / self.reviewed

    @property
    def one_sided(self) -> bool:
        """§11 asks for systematic bias as well as size: 4-0 in eight reviews is a finding at any rate."""
        both = (self.machine_allowed_human_refused, self.machine_refused_human_allowed)
        return self.disagreements >= 4 and min(both) == 0

    @property
    def triggers_review(self) -> bool:
        rate = self.rate
        return bool(self.one_sided or (rate is not None and rate > self.threshold))

    def why(self) -> str:
        if self.reviewed < self.quorum:
            return f"{self.reviewed}/{self.quorum} reviewed this period; below quorum the rate is not reported"
        parts = [
            f"{self.disagreements}/{self.reviewed} = {self.rate:.1%}",
            f"machine-allowed/human-refused {self.machine_allowed_human_refused}",
            f"machine-refused/human-allowed {self.machine_refused_human_allowed}",
        ]
        if self.one_sided:
            parts.append("one-sided: every disagreement is in the same direction")
        return "; ".join(parts)


def divergence(verdicts: Iterable[Verdict], *, quorum: int = 10, threshold: float = 0.20) -> Divergence:
    """M-G05 over a set of verdicts - the caller picks the period, this counts what it is given.

    One ruling counts once, however many rows carry it.  The ledger is append-only, so the three
    identical `family_gate` rows written on 2026-09-09/10/12 stay where they are; what changes is
    that a re-reading of a ruling is no longer a second sample of the machine's judgement.  A row
    somebody has reviewed wins over an identical one nobody has, so collapsing can only shrink
    `pending`, never hide a review.
    """
    collapsed: dict[tuple[str, str, str, tuple[str, ...]], Verdict] = {}
    for verdict in verdicts:
        key = ruling_key(verdict)
        if key not in collapsed or (collapsed[key].pending and not verdict.pending):
            collapsed[key] = verdict
    verdicts = list(collapsed.values())
    reviewed = [verdict for verdict in verdicts if not verdict.pending]
    pending = sum(1 for verdict in verdicts if verdict.pending)
    allowed_refused = sum(1 for v in reviewed if v.ruling == ALLOW and v.review == DISAGREE)
    refused_allowed = sum(1 for v in reviewed if v.ruling == REFUSE and v.review == DISAGREE)
    by_kind: dict[str, tuple[int, int]] = {}
    for verdict in reviewed:
        seen, disagreed = by_kind.get(verdict.kind, (0, 0))
        by_kind[verdict.kind] = (seen + 1, disagreed + (1 if verdict.review == DISAGREE else 0))
    return Divergence(
        reviewed=len(reviewed),
        pending=pending,
        machine_allowed_human_refused=allowed_refused,
        machine_refused_human_allowed=refused_allowed,
        quorum=quorum,
        threshold=threshold,
        by_kind=by_kind,
    )


def since(verdicts: Iterable[Verdict], start: str) -> list[Verdict]:
    return [verdict for verdict in verdicts if verdict.at >= start]
