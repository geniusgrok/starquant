"""The L4 soak wrote one directory and all three of its readers looked in another.

Found 2026-09-12, the first time `deploy/run_shadow.sh` was ever started (operator ruling the same
day - one machine only - removed the blocker, which was that a data-only research machine has no
trading credentials and `--dry-run` still builds the venue).

    run_shadow.sh       --state-dir .starquant/live-shadow
    build_store         .starquant/live-shadow  ->  .starquant/live-shadow-dry-run
    governance canary   --shadow-dir default .starquant/live-shadow
    governance plan     --shadow-dir default .starquant/live-shadow
    governance apply    --shadow-dir default .starquant/live-shadow

Each of the five lines is correct on its own.  Together the soak would have run its full 168 hours
while every reader said "L4: no shadow record", and AC-G5 would then have failed for a reason with
nothing to do with the candidate.  27th instance of this repository's most frequent defect.

The suffix now has one definition - `store_directory` - and the store and the readers both use it.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_cli.governance_cmd import _shadow_rows
from starquant_live.config import build_store, store_directory


def _write(directory: Path, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_the_store_and_the_reader_agree_on_one_name(tmp_path: Path) -> None:
    """The falsifier for the whole class: derive both from the same function or they drift again."""
    declared = tmp_path / "live-shadow"
    profile = {"paths": {"state_dir": str(declared)}}
    assert build_store(profile, dry_run=True).directory == store_directory(declared, dry_run=True)
    assert build_store(profile, dry_run=False).directory == store_directory(declared, dry_run=False)
    assert store_directory(declared, dry_run=True).name == "live-shadow-dry-run"
    assert store_directory(declared, dry_run=False).name == "live-shadow"


def test_the_reader_finds_the_soak_at_the_suffixed_name(tmp_path: Path) -> None:
    """What the canary was about to miss for 168 hours."""
    _write(tmp_path / "live-shadow-dry-run", [{"bar_open_ms": 1, "phase": "OK"}])
    assert len(_shadow_rows(str(tmp_path / "live-shadow"))) == 1


def test_an_unsuffixed_record_handed_over_by_hand_is_still_read(tmp_path: Path) -> None:
    """A soak's record can also arrive by copy; refusing it would trade one blind spot for another."""
    _write(tmp_path / "live-shadow", [{"bar_open_ms": 1, "phase": "OK"}])
    assert len(_shadow_rows(str(tmp_path / "live-shadow"))) == 1


def test_the_suffixed_record_wins_when_both_exist(tmp_path: Path) -> None:
    """The live soak is the authority; a stale hand-copied one must not shadow it."""
    _write(tmp_path / "live-shadow", [{"bar_open_ms": 1, "phase": "OK"}])
    _write(tmp_path / "live-shadow-dry-run", [{"bar_open_ms": 2}, {"bar_open_ms": 3}])
    assert [row["bar_open_ms"] for row in _shadow_rows(str(tmp_path / "live-shadow"))] == [2, 3]


def test_no_record_anywhere_reads_as_no_record(tmp_path: Path) -> None:
    assert _shadow_rows(str(tmp_path / "live-shadow")) == []
