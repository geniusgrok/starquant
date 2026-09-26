"""DL-L1: one trading process per account, enforced rather than assumed.

C-P1, and the most concrete risk on the book today.  There are seven git worktrees on this machine;
``run_live.sh`` sources the credentials from ``~/.zshrc`` globally; ``state_dir`` and the kill switch
are relative paths; ``live run`` defaults to non-dry-run with no arming step.  So `starquant live run
--allow-unvalidated` in any worktree is a second process trading the same account, with its own
state directory, its own kill switch that the other cannot see, and a universe that falls back to
``always_include`` - its non-overlapping positions look foreign to the main loop, and when it exits
they are orphaned.  KILL-R20 also killed the concurrency argument that made this a P2: the two
processes are woken by the same scheduler at close+5s, so a collision is not a random arrival.

Three decisions that the tests below pin down:

* the lock key is the **API key fingerprint**, not the state directory - the thing that must be
  exclusive is the account, and every worktree has a different directory;
* the lock path is absolute (``~/Library/Application Support/starquant``), for the same reason L1-07
  moves the kill switch off a relative path: two processes with different working directories were
  locking different files;
* a rejected instance exits **0** with an alert.  Non-zero would have launchd relaunch it every
  ThrottleInterval and alert every time (KILL-R20(d)); 0 leaves the winner alone and says so once.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from starquant_live.lock import LockBusy, SingleInstanceLock, account_lock_path


def test_the_lock_key_is_the_account_not_the_directory(tmp_path: Path) -> None:
    """Two worktrees, two state dirs, one account: the fingerprint has to be what collides."""
    a = account_lock_path("SAME-KEY", root=tmp_path)
    b = account_lock_path("SAME-KEY", root=tmp_path)
    other = account_lock_path("OTHER-KEY", root=tmp_path)

    assert a == b
    assert a != other
    assert a.is_absolute()


def test_the_lock_file_never_contains_the_api_key(tmp_path: Path) -> None:
    """A filename is not a secret store; the fingerprint is a truncated digest, not the key."""
    path = account_lock_path("super-secret-key", root=tmp_path)

    assert "super-secret-key" not in str(path)
    assert hashlib.sha256(b"super-secret-key").hexdigest()[:16] in path.name


def test_a_second_instance_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "acct.lock"

    with SingleInstanceLock(path), pytest.raises(LockBusy), SingleInstanceLock(path):
        pass  # pragma: no cover - the point is that we never get here


def test_the_lock_is_released_when_the_holder_exits(tmp_path: Path) -> None:
    path = tmp_path / "acct.lock"

    with SingleInstanceLock(path):
        pass
    with SingleInstanceLock(path):
        pass  # a clean exit must not leave the account locked out


def test_the_lock_is_released_even_when_the_holder_raises(tmp_path: Path) -> None:
    path = tmp_path / "acct.lock"

    with pytest.raises(RuntimeError), SingleInstanceLock(path):
        raise RuntimeError("cycle blew up")
    with SingleInstanceLock(path):
        pass


def test_the_holder_is_recorded_so_the_loser_can_say_who_won(tmp_path: Path) -> None:
    """'Another instance is running' is not actionable; a pid and a working directory are."""
    path = tmp_path / "acct.lock"

    with SingleInstanceLock(path, holder="pid=123 repo=/Users/x/starquant"):
        assert "pid=123" in path.read_text(encoding="utf-8")
        assert "repo=/Users/x/starquant" in path.read_text(encoding="utf-8")


def test_the_loser_can_read_the_winners_details(tmp_path: Path) -> None:
    path = tmp_path / "acct.lock"

    with (
        SingleInstanceLock(path, holder="pid=123 repo=/Users/x/starquant"),
        pytest.raises(LockBusy) as busy,
        SingleInstanceLock(path, holder="pid=456 repo=/worktree"),
    ):
        pass  # pragma: no cover

    assert "pid=123" in str(busy.value)


def test_different_accounts_do_not_block_each_other(tmp_path: Path) -> None:
    """Paper/demo/mainnet keys are different accounts; only same-account concurrency is the hazard."""
    with SingleInstanceLock(tmp_path / "a.lock"), SingleInstanceLock(tmp_path / "b.lock"):
        pass


def test_a_missing_parent_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "does" / "not" / "exist" / "acct.lock"

    with SingleInstanceLock(path):
        assert path.exists()
