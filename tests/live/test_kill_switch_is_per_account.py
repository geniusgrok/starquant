"""L1-07, still open: the emergency stop resolves against the working directory.

DL-L5 fixed the half that lived inside one process - `live_cmd` and `live_config` each built the path
from the raw profile string, so they could disagree without anyone moving.  One helper, resolved once,
and that part is real.  The half the helper's own docstring describes is untouched: `Path(...).resolve()`
anchors a relative path to `os.getcwd()`, so

    starquant live kill-switch          # from the repo    -> /Users/.../starquant/.starquant/live/KILL_SWITCH
    starquant live kill-switch          # from a worktree  -> /Users/.../worktrees/x/.starquant/live/KILL_SWITCH

are different files, and the loop reads the first.  Measured 2026-09-07 against the running loop: the
second prints "kill switch engaged", exits 0, and stops nothing.

This is DL-L1's sentence again.  What has to be unique per ACCOUNT cannot be addressed by a path
relative to a working directory - which is why the instance lock is keyed to the API key and lives in
Application Support, and why the kill switch belongs beside it.

The engine reads the union of both, because a kill switch must fail toward stopping: an operator who
engages the old path still stops the book, and release has to clear both or they would be stuck.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_the_account_switch_sits_beside_the_account_lock() -> None:
    from starquant_live.lock import account_kill_switch_path, account_lock_path

    key = "some-api-key"
    switch = account_kill_switch_path(key)
    lock = account_lock_path(key)

    assert switch.parent == lock.parent
    assert switch.stem == lock.stem  # same account fingerprint, different suffix
    assert switch != lock


def test_two_working_directories_reach_the_same_account_switch(tmp_path: Path) -> None:
    """The whole point.  The path may not depend on where the command was run from."""
    from starquant_live.lock import account_kill_switch_path

    root = tmp_path / "support"
    assert account_kill_switch_path("k", root=root) == account_kill_switch_path("k", root=root)
    assert account_kill_switch_path("k", root=root) != account_kill_switch_path("other", root=root)


def test_either_file_stops_the_book(tmp_path: Path) -> None:
    """Fail toward stopping: the legacy path an operator may already rely on still works."""
    from starquant_live.engine import kill_switch_engaged

    legacy = tmp_path / "legacy" / "KILL_SWITCH"
    account = tmp_path / "account" / "k.KILL_SWITCH"
    legacy.parent.mkdir()
    account.parent.mkdir()

    assert kill_switch_engaged((legacy, account)) is False
    legacy.write_text("engaged", encoding="utf-8")
    assert kill_switch_engaged((legacy, account)) is True
    legacy.unlink()
    account.write_text("engaged", encoding="utf-8")
    assert kill_switch_engaged((legacy, account)) is True


def test_release_clears_both_or_the_operator_is_stuck(tmp_path: Path) -> None:
    from starquant_live.engine import release_kill_switches

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")

    released = release_kill_switches((a, b, tmp_path / "never-existed"))

    assert sorted(p.name for p in released) == ["a", "b"]
    assert not a.exists() and not b.exists()


def test_a_missing_directory_is_not_an_engaged_switch(tmp_path: Path) -> None:
    """An unreadable path must not read as "stop" - that would halt the book on a typo."""
    from starquant_live.engine import kill_switch_engaged

    assert kill_switch_engaged((tmp_path / "no" / "such" / "dir" / "KILL_SWITCH",)) is False


def test_the_engine_config_carries_both_paths() -> None:
    from starquant_live.engine import LiveConfig

    assert "kill_switch_paths" in LiveConfig.__dataclass_fields__


@pytest.mark.parametrize("key", ["Zq7XpLm3VtRw9KdN", "Ae4BsCf6GhJk8MnP"])
def test_the_fingerprint_never_contains_the_key(key: str) -> None:
    """Same rule as the lock: the file name is a digest, never the credential.

    The key here has to be credential-shaped rather than a letter: a one-character "key" appears
    inside `Application Support` by accident, and a test that passes for that reason checks nothing.
    """
    from starquant_live.lock import account_kill_switch_path

    assert key not in str(account_kill_switch_path(key))


def test_engaging_writes_both_so_there_is_no_transition_gap(tmp_path: Path) -> None:
    """A loop started before this change reads only the configured path.

    Writing the account path alone would make the switch LESS effective until the next restart, which
    is the wrong direction for an emergency stop to move even briefly.
    """
    from starquant_live.engine import engage_kill_switches

    a = tmp_path / "repo" / "KILL_SWITCH"
    b = tmp_path / "support" / "abc.KILL_SWITCH"

    written = engage_kill_switches((a, b), "engaged at T\n")

    assert sorted(p.name for p in written) == ["KILL_SWITCH", "abc.KILL_SWITCH"]
    assert a.read_text(encoding="utf-8") == "engaged at T\n"
    assert b.read_text(encoding="utf-8") == "engaged at T\n"


# --- the two read points the first fix missed -----------------------------------------------------


def test_the_write_guard_reads_every_path_too(tmp_path: Path) -> None:
    """The last line of defence, and it was still reading one file.

    Three places ask "is the switch engaged": the engine's guard, `WriteGuard` at the HTTP layer, and
    the CLI.  The first fix changed one of them.  `WriteGuard` is the one that refuses a risk-adding
    order at the wire, so a switch the engine honours and the guard does not is the worst of the three
    to leave inconsistent.
    """
    from starquant_exchange.guard import WriteGuard

    legacy = tmp_path / "legacy" / "KILL_SWITCH"
    account = tmp_path / "support" / "abc.KILL_SWITCH"
    legacy.parent.mkdir()
    account.parent.mkdir()
    guard = WriteGuard("https://demo-fapi.binance.com", (legacy, account))

    assert guard.kill_switch_engaged() is False
    account.write_text("engaged", encoding="utf-8")
    assert guard.kill_switch_engaged() is True


def test_the_write_guard_still_takes_a_single_path(tmp_path: Path) -> None:
    """Callers that pass one path keep working; this is a widening, not a break."""
    from starquant_exchange.guard import WriteGuard

    one = tmp_path / "KILL_SWITCH"
    guard = WriteGuard("https://demo-fapi.binance.com", one)

    assert guard.kill_switch_engaged() is False
    one.write_text("engaged", encoding="utf-8")
    assert guard.kill_switch_engaged() is True


def test_flatten_engages_every_path(tmp_path: Path, isolated_app_support: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`live flatten` engaged the switch through the single-path helper.

    Flatten is the one command whose whole purpose is to stop, so it engaging a switch two of the
    three readers cannot see would be the defect at its least funny.
    """
    from starquant_cli.live_cmd import engage_kill_switch

    monkeypatch.setenv("STARQUANT_TEST_KEY", "some-key")
    profile = {
        "guards": {"kill_switch_path": str(tmp_path / "repo" / "KILL_SWITCH")},
        "venue": {"api_key_env": "STARQUANT_TEST_KEY"},
    }

    engage_kill_switch(profile, "engaged\n")

    from starquant_cli.live_cmd import kill_switch_targets

    targets = kill_switch_targets(profile)
    assert len(targets) == 2
    assert all(path.exists() for path in targets)
    # And where it wrote them.  Until 2026-09-08 this test isolated the profile's path to `tmp_path`
    # and used a fake env var NAME, and still left `682f6697fa93eca6.KILL_SWITCH` reading `engaged`
    # in the operator's live Application Support - `account_kill_switches()` defaults `root=None`.
    # The `isolated_app_support` guard in conftest is what moved it; this asserts it stayed moved.
    assert tmp_path in targets[0].parents, targets[0]
    assert targets[1].parent == isolated_app_support, targets[1]
