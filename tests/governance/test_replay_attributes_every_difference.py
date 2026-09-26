"""AC-G0: the replay's difference list has no unattributed item, and `evidence_gap` is not a hole.

Two tests carry the acceptance and one carries the register.

T-G0-1 is the register: the seven rulings Phase 0 was told to account for are declared, each with the
rule it conflicts with and the reason it stays an exception rather than becoming a rule.  A register
whose entries only said "this happened" would let anything in.

T-G0-2 is the acceptance, and its teeth are in `Difference.attributed`: an `evidence_gap` counts as
attributed only when it names the fix that would close it.  Without that clause "we cannot tell"
becomes a wastebasket and AC-G0 passes by construction, which is the failure mode of every audit that
grades itself.

The adoptions below are real - report paths the registry has actually cited, with the dates it cited
them - written out rather than derived from `git log`, so the test says the same thing in a shallow
clone as in a full one.  The CLI derives the full set from history; this is the shape check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starquant_governance.replay import (
    EVIDENCE_GAP,
    EXCEPTIONS,
    EXCEPTIONS_BY_ID,
    SUSPENDED,
    Difference,
    load_jsonl,
    render,
    replay_adoptions,
    replay_live,
)

ROOT = Path(__file__).resolve().parents[2]

# One of each shape the archive actually contains.
ADOPTIONS = {
    "reports/research/tsmom-validation-20260903T0619Z.json": "2026-09-03",  # predates the D-028 block
    "reports/research/book-tsmom-flow-20260903T143621Z.json": "2026-09-04",  # book, ACCEPT
    "reports/research/tsmom-validation-20260906T093705Z.json": "2026-09-06",  # has the block, unnamed gate
    "reports/research/book-tsmom-flow-20260908T105322Z.json": "2026-09-08",  # book, acknowledged REJECT
    "reports/research/tsmom-validation-20260908T105259Z.json": "2026-09-08",  # names its gate
    # 2026-09-09 (`aed1066`), the pointer the registry cites NOW.  It was missing until DL-K3 stopped
    # comparing timestamps as strings: while that bug refused this report, "the rules say no" and
    # "history never adopted it" agreed, and the agreement was hiding a stale list.  One bug was
    # masking another, and the masked one is the kind that makes an adoption history quietly wrong.
    "reports/research/tsmom-validation-20260908T182204Z.json": "2026-09-09",  # carries a preregistration block
    # 2026-09-14 (`72034790`), the pointer the registry cites now: P32 ruled k = 0.60, which made the
    # 182204Z evidence describe a construction that is no longer traded (`registry_evidence_problems`
    # read `portfolio vol_target is 0.6 live but 0.3 in the cited evidence` and refused the armed
    # start), so tsmom was re-validated at 0.60 and the pointer moved.
    #
    # Second time this list has gone stale, and the entry above records the first - which is the part
    # worth naming rather than just fixing.  This dict IS the adoption history, deliberately written
    # out instead of derived from `git log` (see the module docstring: a shallow clone must replay the
    # same), so moving an evidence pointer is only half an adoption; the other half is this line.  Miss
    # it and AC-G0 reports an unattributed difference - which is the check working, not a false alarm:
    # a report the registry cites and history does not record IS a difference between the rules and
    # what happened.
    "reports/research/tsmom-validation-20260913T182325Z.json": "2026-09-14",
}
ACKNOWLEDGED = ("book-tsmom-flow-20260908T105322Z.json",)


def _reports() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted((ROOT / "reports" / "research").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(payload, dict):
            out[path.relative_to(ROOT).as_posix()] = payload
    return out


@pytest.mark.parametrize("ruling", ["D-019", "D-029", "K-EX07", "Q7", "P10-cellB", "P11", "P13"])
def test_t_g0_1_the_seven_rulings_are_in_the_exception_list(ruling: str) -> None:
    entry = EXCEPTIONS_BY_ID[ruling]
    assert entry.ruling and entry.rule_conflict and entry.why_not_encoded, f"{ruling} is a stub"
    assert entry.date.startswith("2026-"), f"{ruling} has no date"


def test_an_exception_entry_has_to_say_which_rule_it_breaks() -> None:
    """Otherwise the register lists history rather than the cost of encoding it."""
    for entry in EXCEPTIONS:
        assert any(token in entry.rule_conflict for token in ("R", "§", "D-", "DL-")), entry.id


def test_t_g0_2_every_difference_carries_a_named_cause() -> None:
    result = replay_adoptions(_reports(), ADOPTIONS, acknowledged_rejects=ACKNOWLEDGED)
    assert result.differences, "a replay that finds no difference is not replaying anything"
    for difference in result.differences:
        assert difference.attributed, f"unattributed: {difference.subject} / {difference.rules_say}"
    assert result.passes_ac_g0


def test_an_evidence_gap_without_a_fix_is_not_attributed() -> None:
    """The clause that stops AC-G0 from grading itself."""
    hole = Difference("x", "adopted", "rule says no", EVIDENCE_GAP, "cannot tell", fix="")
    closed = Difference("x", "adopted", "rule says no", EVIDENCE_GAP, "cannot tell", fix="write the field")
    assert not hole.attributed
    assert closed.attributed


def test_only_the_reports_that_name_their_gate_are_the_ones_the_rules_admit() -> None:
    """The replay's sharpest finding, pinned so it cannot quietly become "all of them".

    Two, not one, since 2026-09-09: the re-run tsmom evidence cleared the gate after it was made
    stricter, and it is the first report to carry a `preregistration` block, so DL-K3 can be decided
    on the artefact instead of suspended.  The set is named rather than counted - a count would pass
    while the wrong report joined it.

    Three since 2026-09-14, and the naming is what made the third one checkable rather than assumed:
    P32's re-validation at k = 0.60 carries `preregistration` (commit `96d659ae`, committed 02:20:42
    +08:00, three minutes before the report's own 18:23:25Z stamp, so DL-K3's ordering holds on the
    artefact), reads `verdict: PASS`, and has the same shape as the pointer it replaces apart from the
    `embargo` field that landed with `--embargo`.  Its OOS margin is thin - 1.5919 against a 1.5493
    gate at N=242, where the report it replaces cleared by 0.2951 - which is a fact for whoever cites
    it next, not a reason the rules refuse it.
    """
    result = replay_adoptions(_reports(), ADOPTIONS, acknowledged_rejects=ACKNOWLEDGED)
    admitted = sorted(line.split("：")[0] for line in result.reproduced if "规则同意采纳（validate" in line)
    assert admitted == [
        "tsmom-validation-20260908T105259Z.json",
        "tsmom-validation-20260908T182204Z.json",
        "tsmom-validation-20260913T182325Z.json",
    ]


def test_a_suspended_condition_says_what_would_make_it_readable() -> None:
    for condition in SUSPENDED:
        assert condition.fix.startswith("Phase "), f"{condition.condition} has no owner phase"
        assert condition.reads.startswith("Facts."), condition.condition


def test_the_live_replay_refuses_to_decide_on_an_error_cycle() -> None:
    """KILL-AR-20 against a hand-built record: one ERROR cycle, one rebaseline, one clean cycle."""
    cycles = load_jsonl(
        "\n".join(
            json.dumps(row)
            for row in (
                {"at": "2026-01-01T00:00:00+00:00", "construction": "aaaaaaaaaaaa", "probes": []},
                {"at": "2026-01-01T01:00:00+00:00", "phase": "ERROR", "error": "proxy 503"},
                {
                    "at": "2026-01-01T02:00:00+00:00",
                    "construction": "aaaaaaaaaaaa",
                    "external_flows": {"rebaselined": True},
                },
            )
        )
    )
    result = replay_live(cycles, [{"total": -1.0}])
    assert any("ERROR 1" in line and "重基 1" in line for line in result.reproduced)
    assert not [d for d in result.differences if "construction" in d.subject], "no construction changed"
    assert result.passes_ac_g0


def test_the_artefact_states_its_own_verdict() -> None:
    text = render(
        replay_adoptions(_reports(), ADOPTIONS, acknowledged_rejects=ACKNOWLEDGED),
        replay_live([], []),
    )
    assert "AC-G0：未归因项 0 条" in text
    assert "policy_digest" in text


def test_a_fingerprint_change_with_no_behaviour_change_is_not_a_construction_change() -> None:
    """The first version of this replay reported six construction changes where four happened.

    `starquant_live.health.CONSTRUCTION_ALIASES` exists precisely because two of the live record's
    fingerprints differ from an earlier one only in fields nothing reads differently - `unit_mode`
    moved the digest without changing a byte of behaviour.  Counting raw digests overstates the thing
    §8's construction freeze is about, and it does so in the direction that makes the operator's
    record look worse than it was, which is the direction an audit is least likely to question.
    """
    rows = [
        {"at": "2026-01-01T00:00:00+00:00", "construction": "old"},
        {"at": "2026-01-01T01:00:00+00:00", "construction": "renamed"},  # same behaviour, new digest
        {"at": "2026-01-01T02:00:00+00:00", "construction": "genuinely-different"},
    ]
    raw = replay_live(rows, [])
    aliased = replay_live(rows, [], construction_aliases={"renamed": "old"})
    assert len([d for d in raw.differences if "construction" in d.subject]) == 2
    assert len([d for d in aliased.differences if "construction" in d.subject]) == 1


def test_dl_g9_turns_a_permanent_blind_spot_into_an_artefact_age_question() -> None:
    """The two conditions Phase 0 suspended are now judged when the fields are there, and only then.

    Before DL-G9 `prereg_before_report` and `evidence_construction_matches_live` were False for every
    artefact that could ever exist, which made §3's state machine unable to admit anything at all - the
    finding that reordered Phase 1.  A report carrying both fields must now be judged on them, and a
    report carrying a construction the loop never ran must be refused rather than waved through.
    """
    modern = {
        "kind": "validation",
        "strategy": "x",
        "verdict": "PASS",
        "generated_at": "2026-10-01T00:00:00+00:00",
        "walk_forward": {"oos_sharpe": 2.0},
        "oos_selection": {"gate": "max_sharpe_quantile", "threshold_annual": 1.0, "n_trials": 10},
        "preregistration": {"commit": "a" * 40, "committed_at": "2026-09-30T00:00:00+00:00"},
        "evidence_construction": "deadbeefdeadbeef",
    }
    reports = {"reports/research/modern.json": modern}
    adoptions = {"reports/research/modern.json": "2026-10-01"}

    admitted = replay_adoptions(reports, adoptions, live_constructions=["deadbeefdeadbeef"])
    assert not admitted.differences, [d.rules_say for d in admitted.differences]
    assert any("已可判定" in line for line in admitted.reproduced)

    # Same report, a loop running something else: refused on KILL-AR-07 rather than suspended.
    diverged = replay_adoptions(reports, adoptions, live_constructions=["0000000000000000"])
    assert [d.rules_say for d in diverged.differences] == [
        "KILL-AR-07: the evidence was produced under a different construction than the loop holds"
    ]
    # And it is a FINDING, not a blind spot: filing a real divergence under "we could not tell" is
    # exactly what `Difference.attributed` was tightened to stop.
    assert not diverged.passes_ac_g0

    # And a pre-registration dated AFTER its own report is the DL-K3 violation, not a pass.
    late = {**modern, "preregistration": {"commit": "b" * 40, "committed_at": "2026-10-02T00:00:00+00:00"}}
    refused = replay_adoptions(
        {"reports/research/late.json": late},
        {"reports/research/late.json": "2026-10-02"},
        live_constructions=["deadbeefdeadbeef"],
    )
    assert any(d.rules_say.startswith("DL-K3") for d in refused.differences)
    assert not refused.passes_ac_g0, "a pre-registration dated after its own report is a finding"
