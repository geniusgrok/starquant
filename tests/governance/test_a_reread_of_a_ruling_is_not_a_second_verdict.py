"""M-G05's denominator was growing by one every day somebody ran a read-only command.

Measured 2026-09-12 on the live ledger: three `family_gate` rows, byte-identical reasons
("OOS 1.8087 vs 1.5149 at N=185"), written 09-09, 09-10 and 09-12 - one per day someone ran
`starquant governance gate` - all three pending, `governance divergence` reporting "3 pending review".

`record()`'s own docstring already named the failure: "a denominator that counts how often somebody
typed a read-only command is not measuring the machine".  It then keyed idempotence on the DATE, which
leaves that hole open one day wide.  Ten quiet days of running the gate would have carried M-G05 to
its quorum of 10 - Pre-A′'s only falsifier, satisfied by ten re-readings of one ruling with no
decision made and nothing changed.

A ruling is (gate, subject, call, reasons).  The reasons carry the numbers, so a gate that flips, or
one ruling on a moved ledger, is a different ruling and still lands its own row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from starquant_governance.verdicts import AGREE, ALLOW, DISAGREE, divergence, read, record, review

REASONS = ("OOS 1.8087 vs 1.5149 at N=185",)


def _gate(path: Path, day: str, reasons: tuple[str, ...] = REASONS) -> None:
    record(
        path,
        kind="family_gate",
        subject="tsmom",
        ruling=ALLOW,
        reasons=reasons,
        now=datetime.fromisoformat(f"{day}T09:00:00+00:00").astimezone(UTC),
    )


def test_running_the_gate_on_three_days_with_nothing_changed_is_one_ruling(tmp_path: Path) -> None:
    path = tmp_path / "verdicts.jsonl"
    _gate(path, "2026-09-09")
    _gate(path, "2026-09-10")
    _gate(path, "2026-09-12")
    assert len(read(path)) == 1
    assert divergence(read(path)).pending == 1


def test_a_ruling_whose_numbers_moved_is_a_new_ruling(tmp_path: Path) -> None:
    """The falsifier: the dedup must not swallow a gate that now says something else."""
    path = tmp_path / "verdicts.jsonl"
    _gate(path, "2026-09-09")
    _gate(path, "2026-09-10", ("OOS 1.8087 vs 1.6402 at N=2731",))
    assert len(read(path)) == 2
    assert divergence(read(path)).pending == 2


def test_rows_already_in_an_append_only_ledger_collapse_on_read(tmp_path: Path) -> None:
    """The three live rows cannot be rewritten, so the count has to be right over them as they are."""
    path = tmp_path / "verdicts.jsonl"
    rows = [
        '{"id": "a", "at": "2026-09-09T16:21:23+00:00", "kind": "family_gate", "subject": "tsmom", '
        '"ruling": "allow", "reasons": ["OOS 1.8087 vs 1.5149 at N=185"], "review": "", "review_why": "", '
        '"reviewed_at": ""}',
        '{"id": "b", "at": "2026-09-10T05:45:22+00:00", "kind": "family_gate", "subject": "tsmom", '
        '"ruling": "allow", "reasons": ["OOS 1.8087 vs 1.5149 at N=185"], "review": "", "review_why": "", '
        '"reviewed_at": ""}',
        '{"id": "c", "at": "2026-09-12T11:21:28+00:00", "kind": "family_gate", "subject": "tsmom", '
        '"ruling": "allow", "reasons": ["OOS 1.8087 vs 1.5149 at N=185"], "review": "", "review_why": "", '
        '"reviewed_at": ""}',
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert len(read(path)) == 3, "the ledger keeps every row it was written"
    assert divergence(read(path)).pending == 1, "but three readings of one ruling are one sample"


def test_a_reviewed_row_wins_over_an_identical_pending_one(tmp_path: Path) -> None:
    """Collapsing may shrink `pending`; it must never hide a review that happened."""
    path = tmp_path / "verdicts.jsonl"
    _gate(path, "2026-09-09")
    identifier = read(path)[0].id
    review(path, identifier, DISAGREE, "the gate's N predates the mined bucket")
    _gate(path, "2026-09-12")
    result = divergence(read(path))
    assert result.pending == 0 and result.reviewed == 1
    assert result.machine_allowed_human_refused == 1
    assert AGREE not in {v.review for v in read(path)}
