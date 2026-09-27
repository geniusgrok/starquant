"""L1-13: a rehearsal must not write into the book's own state directory.

``starquant live run --dry-run`` shared ``paths.state_dir`` with the real loop, so a rehearsal appended to
the live ``cycles.jsonl`` and rewrote ``heartbeat.json`` and ``state.json``.  The consequences are not
cosmetic: ``live status --check`` reads that heartbeat to decide whether the loop is alive, the daily
report counts those cycle rows, and ``drawdown_state`` reads the equity series they carry.  A rehearsal
could therefore make a dead loop look fresh, or put bars into a metric that is supposed to describe
what the book actually did.

The isolation is DERIVED rather than configured - ``<state_dir>-dry-run`` - for two reasons.  A separate
key would have to be remembered exactly when someone is in a hurry, which is when rehearsals happen; and
the live profile sets ``state_dir`` explicitly, so "honour an explicit setting" would have kept the
original bug for the one profile people actually rehearse.
"""

from __future__ import annotations

from starquant_live.config import build_store


def test_a_real_run_uses_the_configured_directory_unchanged(tmp_path) -> None:
    live = build_store({"paths": {"state_dir": str(tmp_path / "live")}}, dry_run=False)
    assert live.directory.name == "live"


def test_a_dry_run_never_lands_in_the_live_directory(tmp_path) -> None:
    profile = {"paths": {"state_dir": str(tmp_path / "live")}}
    live = build_store(profile, dry_run=False)
    rehearsal = build_store(profile, dry_run=True)
    assert rehearsal.directory != live.directory
    assert rehearsal.directory.name == "live-dry-run"
    # the files a rehearsal would clobber are the ones that matter
    for path in ("heartbeat_path", "cycles_path", "state_path", "trades_path"):
        assert getattr(rehearsal, path) != getattr(live, path)


def test_the_default_directory_is_isolated_too(tmp_path, monkeypatch) -> None:
    """A profile with no `paths` block is the easiest way to rehearse by accident."""
    monkeypatch.chdir(tmp_path)
    assert build_store({}, dry_run=True).directory.name == "live-dry-run"
    assert build_store({}, dry_run=False).directory.name == "live"
