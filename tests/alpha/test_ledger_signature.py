"""DL-K1: what makes two runs the same trial, and where the one ledger lives.

KILL-Q5 named two holes in the accounting protocol.

The first is the signature.  `(param_key, range_start, range_end, symbols)` cannot see the
construction the weights were built under, the overlay that was applied to them, *which* symbols
those were rather than how many, or which search space a mined id was drawn from.  Two runs that
differ in any of those are different trials, and the ledger was folding them into one - charging the
DSR denominator less than the selection actually cost.

The second is the ledger's address.  It was `Path(--out) / "trials.jsonl"`, and `--out` is a flag
people pass for ordinary reasons: point the reports somewhere else and the run is charged to a fresh,
empty ledger.  That is not a loophole anyone has to intend, which is what made it worth closing.  The
address is now fixed, and moving it takes an environment variable whose only possible purpose is to
not be charged.

C-P6 is the constraint on all of it: this changes what FUTURE runs cost.  Nothing here reaches back
and re-prices an archived report, so tsmom's N=125 is the same number tomorrow as it was yesterday.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_alpha.validation.ledger import TrialRecord, dsr_inputs, parse_ledger, resolve_ledger_path, unique_trials

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

LEGACY = TrialRecord("s", "k1", 1.6, 8760.0, "t1", "2021-01-31", "2026-09-03", 146, "run-legacy")


def test_a_legacy_row_reads_back_with_empty_fields_rather_than_failing() -> None:
    """145 rows predate this change.  A ledger that cannot read its own history is not a ledger."""
    line = json.dumps(
        {
            "strategy": "s",
            "param_key": "k1",
            "sharpe_annual": 1.6,
            "bars_per_year": 8760.0,
            "recorded_at": "t1",
            "range_start": "2021-01-31",
            "range_end": "2026-09-03",
            "symbols": 146,
            "run_id": "run-legacy",
        }
    )

    record = TrialRecord.from_json(line)

    assert record is not None
    assert record.construction_digest == ""
    assert record.overlay_digest == ""
    assert record.symbol_set_hash == ""
    assert record.search_space_version == ""


def test_two_legacy_rows_still_fold_into_one_trial() -> None:
    """The old rows' dedup semantics are preserved exactly: missing fields are equal to each other."""
    replay = TrialRecord("s", "k1", 1.6, 8760.0, "t2", "2021-01-31", "2026-09-03", 146, "run-replay")

    assert [r.run_id for r in unique_trials([LEGACY, replay], range_end_granularity_days=FOLD_DAYS)] == ["run-legacy"]


def test_a_new_row_does_not_fold_into_a_legacy_one(  # T-K1-1
) -> None:
    """KILL-P5.  A legacy row cannot vouch for a construction it never recorded.

    Folding them would silently ASSERT that the old run used today's construction - the ledger
    claiming knowledge it does not have, which is worse than charging a trial twice.
    """
    modern = TrialRecord(
        "s",
        "k1",
        1.6,
        8760.0,
        "t2",
        "2021-01-31",
        "2026-09-03",
        146,
        "run-modern",
        construction_digest="0dcd044d0158",
    )

    assert [r.run_id for r in unique_trials([LEGACY, modern], range_end_granularity_days=FOLD_DAYS)] == [
        "run-legacy",
        "run-modern",
    ]


def test_the_same_grid_point_under_two_constructions_is_two_trials() -> None:
    """P10 cell B moved the no-trade band and every weight with it; the old signature saw one trial."""
    band_025 = TrialRecord("s", "k1", 1.6, 8760.0, "t1", "a", "b", 146, "r1", construction_digest="aaa")
    band_040 = TrialRecord("s", "k1", 1.7, 8760.0, "t2", "a", "b", 146, "r2", construction_digest="bbb")

    assert len(unique_trials([band_025, band_040], range_end_granularity_days=FOLD_DAYS)) == 2


def test_the_same_count_of_different_symbols_is_two_trials() -> None:
    """`symbols` is a COUNT.  Two disjoint 146-symbol universes were indistinguishable to it."""
    one = TrialRecord("s", "k1", 1.6, 8760.0, "t1", "a", "b", 146, "r1", symbol_set_hash="111")
    other = TrialRecord("s", "k1", 1.6, 8760.0, "t2", "a", "b", 146, "r2", symbol_set_hash="222")

    assert len(unique_trials([one, other], range_end_granularity_days=FOLD_DAYS)) == 2


def test_an_overlay_makes_it_a_different_trial() -> None:
    naked = TrialRecord("s", "k1", 1.6, 8760.0, "t1", "a", "b", 146, "r1", construction_digest="aaa")
    stopped = TrialRecord(
        "s", "k1", 1.5, 8760.0, "t2", "a", "b", 146, "r2", construction_digest="aaa", overlay_digest="stop6tp6"
    )

    assert len(unique_trials([naked, stopped], range_end_granularity_days=FOLD_DAYS)) == 2


def test_a_mined_id_from_a_wider_space_is_a_different_trial() -> None:
    """B2 took the space 267 -> 514.  The same expression drawn from a wider search cost more to find."""
    from_267 = TrialRecord("mined_x", "k", 1.7, 8760.0, "t1", "a", "b", 205, "r1", search_space_version="267")
    from_514 = TrialRecord("mined_x", "k", 1.7, 8760.0, "t2", "a", "b", 205, "r2", search_space_version="514")

    assert len(unique_trials([from_267, from_514], range_end_granularity_days=FOLD_DAYS)) == 2


def test_the_extension_does_not_reprice_the_archive(  # T-K1-4 / C-P6
) -> None:
    """The whole ledger as it stands today is legacy rows; reading it must give the number it gave."""
    rows = [TrialRecord("s", f"k{i}", 1.0 + i, 8760.0, "t", "2021-01-31", "2026-09-03", 146, f"r{i}") for i in range(5)]
    rows.append(TrialRecord("s", "k0", 1.0, 8760.0, "t-later", "2021-01-31", "2026-09-03", 146, "r-replay"))

    pooled = dsr_inputs(rows, {"new": None}, 8760.0, manual_prior_trials=60, range_end_granularity_days=FOLD_DAYS)

    assert pooled["ledger_trials"] == 5
    assert pooled["duplicate_rows"] == 1
    assert pooled["n_trials"] == 5 + 1 + 60


def test_a_round_trip_through_json_preserves_the_new_fields() -> None:
    record = TrialRecord(
        "s",
        "k",
        1.0,
        8760.0,
        "t",
        "a",
        "b",
        1,
        "r",
        construction_digest="c",
        overlay_digest="o",
        symbol_set_hash="h",
        search_space_version="v",
    )

    assert TrialRecord.from_json(record.to_json()) == record


def test_parse_ledger_still_filters_by_strategy() -> None:
    lines = [LEGACY.to_json(), TrialRecord("other", "z", 2.0, 8760.0, "t", "a", "b", 15, "r").to_json()]

    assert [r.strategy for r in parse_ledger(lines, "s")] == ["s"]


# --- the ledger's address -----------------------------------------------------------------------


def test_the_ledger_does_not_move_when_the_reports_do() -> None:
    """KILL-Q5's actual hole: `--out` is a reporting flag, and it was also the accounting flag."""
    assert resolve_ledger_path(out="/somewhere/else/reports") == resolve_ledger_path(out="reports/research")


def test_moving_the_ledger_takes_saying_so(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", "/tmp/scratch-ledger.jsonl")

    assert resolve_ledger_path(out="reports/research") == Path("/tmp/scratch-ledger.jsonl")


def test_the_default_address_is_the_one_ledger(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("STARQUANT_TRIALS_LEDGER", raising=False)

    assert resolve_ledger_path(out="anything", start=Path("/")) == Path("reports/research/trials.jsonl")


def test_the_test_suite_never_writes_to_the_real_ledger(isolated_trials_ledger: Path) -> None:
    """A guard on this file's own premise: without it, one forgotten flag pollutes the DSR denominator."""
    resolved = resolve_ledger_path(out="reports/research")

    assert resolved == isolated_trials_ledger
    assert Path("reports/research/trials.jsonl").resolve() != resolved.resolve()


def test_the_current_grid_is_still_excluded_once_the_signature_is_longer() -> None:
    """D-024 survives the extension, which it did not for one commit.

    `dsr_inputs` builds the exclusion set by hand from `current_range`.  Lengthening `signature`
    without lengthening that construction makes the exclusion match nothing, silently double-charging
    every re-validation of the same grid on the same data - the exact bookkeeping error this file is
    about, introduced by the fix for it.
    """
    rows = [
        TrialRecord("s", "k1", 1.6, 8760.0, "t1", "a", "b", 146, "r1"),
        TrialRecord("s", "k2", 0.4, 8760.0, "t2", "a", "b", 146, "r2"),
    ]

    pooled = dsr_inputs(
        rows, {"k2": 0.4 / 8760**0.5}, 8760.0, current_range=("a", "b", 146), range_end_granularity_days=FOLD_DAYS
    )

    assert pooled["ledger_trials"] == 1
    assert pooled["replayed_rows"] == 1


def test_the_same_grid_under_a_different_construction_is_not_a_replay() -> None:
    """The point of the extension, stated as a charge: re-running a grid after moving the band costs."""
    rows = [TrialRecord("s", "k1", 1.6, 8760.0, "t1", "a", "b", 146, "r1", construction_digest="old")]

    pooled = dsr_inputs(
        rows,
        {"k1": 1.6 / 8760**0.5},
        8760.0,
        current_range=("a", "b", 146),
        current_context=("new", "", "", ""),
        range_end_granularity_days=FOLD_DAYS,
    )

    assert pooled["ledger_trials"] == 1  # the old-construction row still counts
    assert pooled["replayed_rows"] == 0
    assert pooled["n_trials"] == 2


def test_the_ledger_is_found_from_a_subdirectory(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """L1-07's shape, one file over: a relative path resolves against the working directory.

    Fixing `--out` closed the loophole a flag opened and left the one a `cd` opens.  Run from
    `starquant_alpha/` or from a scripts directory and `reports/research/trials.jsonl` names a file that
    does not exist yet, so the run is charged to a fresh empty book and reports `ledger_trials: 0` -
    which is exactly the state KILL-Q5 was about, reached by walking instead of by typing.
    """
    monkeypatch.delenv("STARQUANT_TRIALS_LEDGER", raising=False)
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "starquant_alpha" / "validation"
    nested.mkdir(parents=True)

    assert resolve_ledger_path(root=None, start=nested) == tmp_path / "reports/research/trials.jsonl"
    assert resolve_ledger_path(root=None, start=tmp_path) == tmp_path / "reports/research/trials.jsonl"


def test_a_worktree_keeps_its_own_ledger(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A worktree's `.git` is a FILE, not a directory, and it is still that checkout's root.

    Deliberately per-checkout rather than shared: the ledger is a tracked file, so a worktree's rows
    reach the others by merging, which is the same path every other artefact in this repository takes.
    """
    monkeypatch.delenv("STARQUANT_TRIALS_LEDGER", raising=False)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")

    assert resolve_ledger_path(root=None, start=worktree) == worktree / "reports/research/trials.jsonl"


def test_outside_a_checkout_it_falls_back_to_the_relative_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("STARQUANT_TRIALS_LEDGER", raising=False)

    assert resolve_ledger_path(root=None, start=tmp_path) == Path("reports/research/trials.jsonl")


def test_a_mined_sleeve_in_a_book_pays_for_its_search_too() -> None:
    """DL-K2 reached `validate` and stopped there; `research book` scores the same sleeve.

    A candidate promoted through `book` rather than through `validate` would have been charged the
    search on one path and not the other - the accounting depending on which command an operator
    happened to run, which is the class of hole this whole batch is about.
    """
    from starquant_alpha.validation.ledger import ledger_scope

    assert ledger_scope("mined_abc") == ("mined_abc", "mined")
    assert ledger_scope("tsmom") == ("tsmom",)
    assert ledger_scope("xsmom") == ("xsmom",)


def test_the_trials_ledger_is_appended_as_durably_as_the_live_ones(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """DL-L6 fsynced `.starquant/live/*.jsonl` and left the other append-only ledger alone.

    Same contract, and this is the one that IS the DSR denominator: a row lost to a crash makes N
    smaller, and a smaller N flatters every verdict computed after it.  "Unlikely" is not what an
    append-only ledger is for - DL-L6's own sentence, applied to the file it did not cover.
    """
    from starquant_cli.research_cmd import _record_trials

    ledger = tmp_path / "trials.jsonl"
    monkeypatch.setenv("STARQUANT_TRIALS_LEDGER", str(ledger))
    rows = [TrialRecord("s", f"k{i}", 1.0, 8760.0, "t", "a", "b", 1, f"r{i}") for i in range(50)]

    assert _record_trials(ledger, rows) == 50

    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    assert all(json.loads(line)["run_id"] == f"r{i}" for i, line in enumerate(lines))
