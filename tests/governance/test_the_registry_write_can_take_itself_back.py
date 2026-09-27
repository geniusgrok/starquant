"""DL-G4 / DRILL-G1 and G5: the registry write is a transaction, and the gate it asks is the real one.

Q9 (operator ruling, 2026-09-08) removed the human confirmation point from single promotions: the
machine writes the registry from the first transaction.  What stands in for the person is this
module's ability to undo itself, so these tests are the compensating control, not paperwork.

DRILL-G1 is run against the SHIPPED registry with a real corruption - a report whose sha256 no longer
matches - and against the REAL startup gate, `starquant_live.config.registry_evidence_problems`.  Using a
stub gate here would test that `apply` calls whatever it is given, which is not the question; the
question is whether the thing it is given refuses what the loop would refuse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from starquant_alpha.registry import parse_registry
from starquant_governance.promote import APPLY, NOOP, ROLLBACK, apply, closed, digest_of, plan, read_log
from starquant_live.config import registry_evidence_problems
from tests.shipped_evidence import unexempted

ROOT = Path(__file__).resolve().parents[2]


def _real_gate(profile: dict) -> object:
    """The shipped `registry_evidence_problems`, minus the one knowingly-accepted problem.

    Still the REAL gate, which is this file's design: `_corrupt` below breaks a digest and the gate has
    to refuse that, and it does.  What `unexempted` drops is one exact string
    (`tests/shipped_evidence.py`), so the drill keeps testing the TRANSACTION machinery instead of
    re-deciding whether the operator may point tsmom at FAIL evidence.

    Worth being blunt about what this does not change: in production `governance apply` really is
    blocked while that problem stands - even a comment-only edit rolls back, because the gate reads the
    file and the file does not clear.  That is the gate working as designed and it is a real cost of the
    2026-09-19 pointer move, recorded here and in `tests/shipped_evidence.py` rather than engineered
    around.  It lifts when the pointer cites evidence that clears, or on 2026-10-13, whichever is first.
    """

    def gate(path: Path) -> list[str]:
        registry = parse_registry(yaml.safe_load(path.read_text(encoding="utf-8")))
        return unexempted(registry_evidence_problems(registry, profile))

    return gate


def _corrupt(registry_text: str) -> str:
    """Break the first evidence digest, whatever it currently is.

    Not a hardcoded hash: this file deliberately drills against the SHIPPED registry, and pinning the
    literal `sha256: 11f91787` made the drill go red the first time that evidence was re-derived - the
    replacement matched nothing, the "corrupt" copy was identical to the original, and the fixture's own
    guard fired.  A test that breaks whenever the thing it points at is legitimately updated teaches
    people to edit the test.
    """
    corrupted = re.sub(r"sha256: [0-9a-f]{64}", "sha256: " + "0" * 64, registry_text, count=1)
    assert corrupted != registry_text, "the shipped registry carries no evidence digest to corrupt"
    return corrupted


def _shipped(tmp_path: Path) -> tuple[Path, Path, dict]:
    registry = tmp_path / "alpha_registry.yaml"
    registry.write_text((ROOT / "config" / "alpha_registry.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    profile = yaml.safe_load((ROOT / "config" / "live.demo.yaml").read_text(encoding="utf-8"))

    # Every drill below starts from a pair the real gate accepts, and says so rather than assuming it.
    # Drilling the REAL gate is this file's whole design (see the module docstring), and the cost of that
    # is that the drill goes red whenever the shipped profile and registry disagree for reasons that have
    # nothing to do with transactions - reporting someone else's breakage in the one vocabulary that
    # cannot describe it.  2026-09-14: `vol_target` 0.30 -> 0.60 (96d659ae) made the gate refuse, the
    # accepted-change drill failed as `assert 'ROLLBACK' == 'APPLY'`, and nothing in that message named
    # the config, the field, or the armed loop that would refuse to start.  The pair is owned by
    # `tests/alpha/test_evidence_gate.py::test_the_shipped_registry_runs_what_its_evidence_validated`;
    # this line only keeps the drill from answering for it.
    # 2026-09-19: minus the one problem the operator knowingly accepted when tsmom's pointer moved to
    # FAIL evidence.  The ownership sentence above still holds - this line does not decide anything, it
    # reads the same exemption `test_evidence_gate.py` reads, from `tests/shipped_evidence.py`, and it
    # expires on the same day.  A drill must not answer for that decision either way.
    problems = registry_evidence_problems(parse_registry(yaml.safe_load(registry.read_text(encoding="utf-8"))), profile)
    assert unexempted(problems) == [], (
        f"the shipped registry and profile disagree before the drill even starts: {problems}"
    )

    return registry, tmp_path / "transactions.jsonl", profile


def test_drill_g1_a_bad_evidence_pointer_is_written_refused_and_taken_back(tmp_path: Path) -> None:
    registry, log, profile = _shipped(tmp_path)
    original = registry.read_text(encoding="utf-8")

    transaction = apply(registry, _corrupt(original), gate=_real_gate(profile), log_path=log, candidate="drill-g1")

    assert transaction.action == ROLLBACK
    assert transaction.reasons, "a rollback with no reason cannot be acted on"
    assert registry.read_text(encoding="utf-8") == original, "the rollback must restore the ORIGINAL bytes"
    assert transaction.after_digest == transaction.before_digest == digest_of(original)
    assert not transaction.restart_required, "a rolled-back transaction must not ask for a restart"
    assert [t.action for t in read_log(log)] == [ROLLBACK]


def test_the_rollback_keeps_the_comments_that_carry_the_rulings(tmp_path: Path) -> None:
    """A YAML round-trip would lose them, and this file's comments hold the D-029 acknowledgement."""
    registry, log, profile = _shipped(tmp_path)
    before = registry.read_text(encoding="utf-8")
    apply(
        registry,
        before.replace("sha256: 11f91787", "sha256: deadbeef", 1),
        gate=_real_gate(profile),
        log_path=log,
        candidate="c",
    )
    after = registry.read_text(encoding="utf-8")
    assert "D-029" in after
    assert after == before


def test_drill_g5_proposing_what_the_file_already_says_is_not_a_second_apply(tmp_path: Path) -> None:
    """Idempotence.  A scheduler that retries its own transaction must leave one row, not two."""
    registry, log, profile = _shipped(tmp_path)
    unchanged = registry.read_text(encoding="utf-8")

    first = apply(registry, unchanged, gate=_real_gate(profile), log_path=log, candidate="c")
    second = apply(registry, unchanged, gate=_real_gate(profile), log_path=log, candidate="c")

    assert first.action == second.action == NOOP
    assert not any(t.restart_required for t in read_log(log))


def test_an_accepted_change_asks_for_a_restart_and_says_who_made_it(tmp_path: Path) -> None:
    """AC-L5 reads this row: the first fully automatic window must show `actor = machine`."""
    registry, log, profile = _shipped(tmp_path)
    # A comment-only edit passes the gate (it changes no field the gate reads) while changing the bytes.
    edited = registry.read_text(encoding="utf-8") + "\n# transaction test\n"

    transaction = apply(registry, edited, gate=_real_gate(profile), log_path=log, candidate="c")

    assert transaction.action == APPLY
    assert transaction.actor == "machine"
    assert transaction.restart_required, "the loop builds its model at startup; a write without a restart is inert"
    assert registry.read_text(encoding="utf-8") == edited


def test_plan_asks_the_same_gate_without_touching_the_file(tmp_path: Path) -> None:
    """A dry run that checks a different thing says nothing about the wet one."""
    registry, _log, profile = _shipped(tmp_path)
    before = registry.read_text(encoding="utf-8")

    proposed = plan(registry, _corrupt(before), gate=_real_gate(profile), candidate="c")

    assert proposed.reasons, "the plan must surface what apply would have refused"
    assert not proposed.restart_required
    assert registry.read_text(encoding="utf-8") == before
    assert not list(registry.parent.glob("*.plan")), "the scratch file must not survive"


def test_the_log_is_read_as_a_chain_so_an_outside_edit_shows_up(tmp_path: Path) -> None:
    """AC-G4's "closed": an APPLY's after-digest must be the next row's before-digest."""
    registry, log, profile = _shipped(tmp_path)
    apply(
        registry,
        registry.read_text(encoding="utf-8") + "\n# one\n",
        gate=_real_gate(profile),
        log_path=log,
        candidate="c",
    )
    apply(
        registry,
        registry.read_text(encoding="utf-8") + "\n# two\n",
        gate=_real_gate(profile),
        log_path=log,
        candidate="c",
    )
    assert closed(read_log(log))

    # Somebody edits the file by hand between transactions - the shape this module replaces.
    tampered = read_log(log)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**json.loads(tampered[-1].to_json()), "before_digest": "notthechain"}) + "\n")
    assert not closed(read_log(log))
