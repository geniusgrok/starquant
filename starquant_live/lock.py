"""One trading process per account (DL-L1 / KILL-Q7).

``execute_order`` queries before it submits, which stops a *serial* repeat - the same bar replayed
after a restart.  It does nothing about two processes woken by the same scheduler at close+5s, and
that is the real shape of the risk here: seven worktrees on one machine, credentials sourced
globally from ``~/.zshrc``, ``state_dir`` and the kill switch on relative paths, and ``live run``
defaulting to non-dry-run.  A second loop started in any worktree trades the same account with its
own state, its own invisible kill switch, and a universe fallen back to ``always_include``.

The lock is therefore keyed to the **account**, not to a directory: a truncated SHA-256 of the API
key under an absolute application-support path, so every worktree contends for the same file.  It
holds ``flock(LOCK_EX | LOCK_NB)`` for the life of the process; the kernel releases it if the holder
dies, so a crash never locks the operator out - which a pid file would.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
from types import TracebackType

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "starquant"


class LockBusy(RuntimeError):
    """Another process already holds this account's lock; its details are in the message."""


def account_lock_path(api_key: str, *, root: Path | None = None) -> Path:
    """``<root>/<sha256(api_key)[:16]>.lock`` - absolute, and never containing the key itself."""
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return ((root or APP_SUPPORT) / f"{fingerprint}.lock").resolve()


def account_kill_switch_path(api_key: str, *, root: Path | None = None) -> Path:
    """The kill switch, addressed by ACCOUNT rather than by working directory (L1-07).

    The docstring above already names "its own invisible kill switch" as part of the risk this module
    exists for, and then solved only the lock half.  `Path(".starquant/live/KILL_SWITCH").resolve()`
    anchors to `os.getcwd()`, so engaging the switch from a worktree writes a file the loop - running
    from the repository root - never reads, prints success, and stops nothing (measured against the
    running loop on 2026-09-07).

    Same fingerprint as the lock, same directory, so the two facts about an account live together.
    """
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return ((root or APP_SUPPORT) / f"{fingerprint}.KILL_SWITCH").resolve()


def describe_holder() -> str:
    return f"pid={os.getpid()} repo={Path.cwd()}"


class SingleInstanceLock:
    """Exclusive, non-blocking, released by the kernel when the process ends."""

    def __init__(self, path: Path, *, holder: str | None = None) -> None:
        self.path = Path(path)
        self.holder = holder if holder is not None else describe_holder()
        self._fd: int | None = None

    def __enter__(self) -> SingleInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            incumbent = self._read_holder()
            os.close(fd)
            raise LockBusy(
                f"another starquant instance holds this account's lock ({incumbent or 'holder unknown'}); "
                f"lock file {self.path}"
            ) from exc
        os.ftruncate(fd, 0)
        os.write(fd, self.holder.encode("utf-8"))
        os.fsync(fd)
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def _read_holder(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
