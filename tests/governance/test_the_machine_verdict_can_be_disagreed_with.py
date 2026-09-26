"""M-G05, which was Pre-A′'s only falsifier and had no instrument of any kind until 2026-09-10.

The plan names Pre-A′ - "写死的规则能替代人在运行时的**决策**" - as its highest-risk assumption, gives
it exactly one falsifier (M-G05, divergence between machine rulings and later human review), and then
never writes, reads or computes it.  §11 had the row, §13 had the cell, `governance/` had neither.

Two properties this file exists to hold, because both are ways the measurement quietly stops measuring:

* the sample is written BY THE GATE, so it is not selected by which decisions somebody found memorable;
* an unreviewed ruling is `pending`, not absent, so the denominator cannot shrink toward agreement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from starquant_governance.verdicts import (
    AGREE,
    ALLOW,
    DISAGREE,
    REFUSE,
    Verdict,
    divergence,
    read,
    record,
    review,
    since,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def _ledger(tmp_path: Path) -> Path:
    return tmp_path / "governance" / "verdicts.jsonl"


def test_a_ruling_is_recorded_where_it_is_made_and_starts_pending(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    verdict = record(path, kind="admission", subject="cand.yaml", ruling=REFUSE, reasons=("R3: over budget",), now=NOW)
    assert verdict.pending
    rows = read(path)
    assert [r.id for r in rows] == [verdict.id]
    assert rows[0].reasons == ("R3: over budget",)


def test_the_same_ruling_twice_in_a_day_is_one_row(tmp_path: Path) -> None:
    """`governance plan` is meant to be run repeatedly; a denominator counting keystrokes measures nobody."""
    path = _ledger(tmp_path)
    record(path, kind="admission", subject="c.yaml", ruling=REFUSE, reasons=("R3",), now=NOW)
    record(path, kind="admission", subject="c.yaml", ruling=REFUSE, reasons=("R3",), now=NOW + timedelta(hours=3))
    assert len(read(path)) == 1


def test_the_same_subject_refused_for_a_different_reason_is_a_different_ruling(tmp_path: Path) -> None:
    """One review must not stand for a judgement nobody made."""
    path = _ledger(tmp_path)
    record(path, kind="admission", subject="c.yaml", ruling=REFUSE, reasons=("R3",), now=NOW)
    record(path, kind="admission", subject="c.yaml", ruling=REFUSE, reasons=("K-EX14",), now=NOW)
    assert len(read(path)) == 2


def test_a_review_supersedes_without_erasing(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    verdict = record(path, kind="family_gate", subject="tsmom", ruling=ALLOW, now=NOW)
    review(path, verdict.id, DISAGREE, "the bucket is about to grow past it", now=NOW + timedelta(days=1))
    rows = read(path)
    assert len(rows) == 1 and rows[0].review == DISAGREE and not rows[0].pending
    assert rows[0].ruling == ALLOW, "the machine's original ruling is still on the record"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2, "append-only: both rows are in the file"


def test_a_review_without_a_reason_is_refused(tmp_path: Path) -> None:
    """An agreement with no reason cannot be told apart from not having looked."""
    path = _ledger(tmp_path)
    verdict = record(path, kind="family_gate", subject="tsmom", ruling=ALLOW, now=NOW)
    with pytest.raises(ValueError, match="say why"):
        review(path, verdict.id, AGREE, "   ")
    with pytest.raises(ValueError, match="agree"):
        review(path, verdict.id, "maybe", "hmm")
    with pytest.raises(KeyError):
        review(path, "deadbeef", AGREE, "fine")


# --- the rate itself -----------------------------------------------------------------------------


def _verdicts(*specs: tuple[str, str]) -> list[Verdict]:
    return [
        Verdict(f"id{i}", NOW.isoformat(), "admission", f"s{i}", ruling, review=rev, review_why="because")
        for i, (ruling, rev) in enumerate(specs)
    ]


def test_below_quorum_the_rate_is_none_rather_than_zero() -> None:
    """Zero disagreements out of three reviews is not a 0% divergence rate; it is three reviews."""
    result = divergence(_verdicts((ALLOW, AGREE), (REFUSE, AGREE), (ALLOW, AGREE)))
    assert result.reviewed == 3 and result.rate is None
    assert not result.triggers_review
    assert "below quorum" in result.why()


def test_pending_rulings_do_not_shrink_the_denominator_toward_agreement() -> None:
    rows = _verdicts(*[(ALLOW, AGREE)] * 10)
    rows.append(Verdict("p1", NOW.isoformat(), "admission", "sx", REFUSE))
    result = divergence(rows)
    assert result.reviewed == 10 and result.pending == 1
    assert result.rate == pytest.approx(0.0)


def test_a_rate_over_the_threshold_asks_for_a_rule_version_review() -> None:
    rows = _verdicts(*([(ALLOW, DISAGREE)] * 2 + [(REFUSE, DISAGREE)] * 1 + [(ALLOW, AGREE)] * 9))
    result = divergence(rows)
    assert result.reviewed == 12 and result.rate == pytest.approx(3 / 12)
    assert result.triggers_review and result.rate > result.threshold


def test_the_directions_are_kept_apart() -> None:
    """A machine that refuses too much and one that admits too much need different fixes."""
    rows = _verdicts(*([(ALLOW, DISAGREE)] * 3 + [(REFUSE, DISAGREE)] * 1 + [(ALLOW, AGREE)] * 8))
    result = divergence(rows)
    assert result.machine_allowed_human_refused == 3
    assert result.machine_refused_human_allowed == 1
    assert result.disagreements == 4


def test_a_one_sided_pattern_is_a_finding_even_inside_the_rate() -> None:
    """§11 asks for systematic bias as well as size: four disagreements all one way, at 4/20 = 20%."""
    rows = _verdicts(*([(ALLOW, DISAGREE)] * 4 + [(ALLOW, AGREE)] * 16))
    result = divergence(rows)
    assert result.rate == pytest.approx(0.20) and result.rate <= result.threshold
    assert result.one_sided and result.triggers_review
    assert "one-sided" in result.why()


def test_the_period_filter_is_the_callers(tmp_path: Path) -> None:
    rows = [
        Verdict("a", "2026-06-01T00:00:00+00:00", "admission", "s", ALLOW, review=AGREE, review_why="x"),
        Verdict("b", "2026-09-01T00:00:00+00:00", "admission", "s", ALLOW, review=AGREE, review_why="x"),
    ]
    assert [v.id for v in since(rows, "2026-07-01")] == ["b"]
