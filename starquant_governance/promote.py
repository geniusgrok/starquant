"""R6 / DL-G4: writing the registry as a transaction that can be taken back.

KILL-Q15 is the reason this exists.  The engine builds its model once at startup, so editing
`alpha_registry.yaml` under a running loop changes nothing until a restart - and in 2026-09 that gap
ran for 96 cycles with the loop trading one registry while the file described another.  Q9 (operator
ruling, 2026-09-08) is that the machine performs this write from the first transaction, with no human
confirmation point; what stands in for the person is this module's ability to undo itself.

**One deliberate departure from the plan's ordering, and the reason.**  §2 describes: write the YAML,
request a restart, let the startup gate refuse, then roll back.  This checks the gate IN PROCESS,
before any restart is requested, so a bad write never reaches a running loop at all.  That is only
safe because it is the SAME function startup calls - the gate is injected by the caller and the caller
passes `starquant_live.config.registry_evidence_problems`.  A second, similar check written here would be
the divergence this whole project keeps finding, so there isn't one; DRILL-G1 exists to prove the
injected gate is the real one by feeding it a report whose sha256 does not match.

Nothing here restarts anything.  A transaction reports `restart_required`, and who acts on that is a
question about deployment, not about the registry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: What a caller must supply: the startup gate, given the registry file to judge.
Gate = Callable[[Path], Sequence[str]]

PLAN = "PLAN"
APPLY = "APPLY"
ROLLBACK = "ROLLBACK"
NOOP = "NOOP"


@dataclass(frozen=True)
class Transaction:
    """One attempt to change the registry, whatever happened to it.

    `actor` is recorded because AC-L5 asks for it: the first fully automatic window must show
    `actor = machine` on the APPLY row, and a log that cannot distinguish a machine write from a
    person's is not evidence that the machine did it.
    """

    at: str
    action: str
    actor: str
    candidate: str
    registry_path: str
    before_digest: str
    after_digest: str | None = None
    restart_required: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _append(log_path: Path, transaction: Transaction) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(transaction.to_json() + "\n")


def _write(path: Path, text: str) -> None:
    """Atomic replace: a torn registry read by a starting loop is the one failure with no undo."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def apply(
    registry_path: Path,
    proposed: str,
    *,
    gate: Gate,
    log_path: Path,
    candidate: str,
    actor: str = "machine",
) -> Transaction:
    """Write ``proposed``, ask the gate, and put the old bytes back if it refuses.

    Idempotent by content: proposing what the file already says is a NOOP, not a second APPLY.  That
    matters more than it looks - DRILL-G5 restarts the loop mid-window, and a scheduler that retries
    its own transaction must not leave two APPLY rows describing one change.

    The rollback restores the ORIGINAL BYTES, not a re-serialisation of them.  A YAML round-trip loses
    comments, and this file's comments carry the D-029 acknowledgement and the stress-coverage record -
    losing them would be a silent second change made by the undo of the first.
    """
    current = registry_path.read_text(encoding="utf-8")
    before = digest_of(current)
    now = datetime.now(UTC).isoformat()
    if proposed == current:
        transaction = Transaction(now, NOOP, actor, candidate, str(registry_path), before, before)
        _append(log_path, transaction)
        return transaction

    _write(registry_path, proposed)
    problems = tuple(str(problem) for problem in gate(registry_path))
    if problems:
        _write(registry_path, current)
        restored = digest_of(registry_path.read_text(encoding="utf-8"))
        transaction = Transaction(
            now, ROLLBACK, actor, candidate, str(registry_path), before, restored, False, problems
        )
        _append(log_path, transaction)
        return transaction

    after = digest_of(proposed)
    transaction = Transaction(now, APPLY, actor, candidate, str(registry_path), before, after, True)
    _append(log_path, transaction)
    return transaction


def plan(registry_path: Path, proposed: str, *, gate: Gate, candidate: str, actor: str = "machine") -> Transaction:
    """What `apply` would do, without doing it - the gate is asked against a copy.

    Not merely a convenience.  `governance plan` is what a person reads before the machine is allowed
    to write anything at all, and it must exercise the identical path: a dry run that checks a
    different thing is a dry run that says nothing about the wet one.
    """
    current = registry_path.read_text(encoding="utf-8")
    before = digest_of(current)
    now = datetime.now(UTC).isoformat()
    if proposed == current:
        return Transaction(now, NOOP, actor, candidate, str(registry_path), before, before)
    scratch = registry_path.with_suffix(registry_path.suffix + ".plan")
    try:
        scratch.write_text(proposed, encoding="utf-8")
        problems = tuple(str(problem) for problem in gate(scratch))
    finally:
        scratch.unlink(missing_ok=True)
    return Transaction(
        now,
        PLAN,
        actor,
        candidate,
        str(registry_path),
        before,
        digest_of(proposed),
        not problems,
        problems,
    )


def read_log(log_path: Path) -> list[Transaction]:
    if not log_path.exists():
        return []
    out: list[Transaction] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            out.append(
                Transaction(
                    at=str(payload.get("at", "")),
                    action=str(payload.get("action", "")),
                    actor=str(payload.get("actor", "")),
                    candidate=str(payload.get("candidate", "")),
                    registry_path=str(payload.get("registry_path", "")),
                    before_digest=str(payload.get("before_digest", "")),
                    after_digest=payload.get("after_digest"),
                    restart_required=bool(payload.get("restart_required", False)),
                    reasons=tuple(str(r) for r in (payload.get("reasons") or [])),
                )
            )
    return out


def closed(log: Sequence[Transaction]) -> bool:
    """AC-G4's "the transaction log is closed": every write left the file at a digest the log names.

    Read as a chain rather than per row: an APPLY's `after` must be the next row's `before`, and a
    ROLLBACK must land back on its own `before`.  A gap means something changed the registry outside a
    transaction, which is exactly the hand-edit this module replaces.
    """
    previous: str | None = None
    for transaction in log:
        if previous is not None and transaction.before_digest != previous:
            return False
        if transaction.action == ROLLBACK and transaction.after_digest != transaction.before_digest:
            return False
        previous = transaction.after_digest or transaction.before_digest
    return True
