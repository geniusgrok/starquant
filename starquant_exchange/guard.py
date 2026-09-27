"""Local write guard: exact host allow-list, kill-switch file, reduce-only pass-through.

This is not an authorization system.  It is the last local check before a
mutating request leaves the process: mainnet hosts are refused outright, and
while the kill-switch file exists only risk-reducing writes (cancel,
reduce-only orders, leverage/session control) are allowed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ALLOWED_HOSTS: frozenset[str] = frozenset({"demo-fapi.binance.com", "testnet.binancefuture.com"})
MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "DELETE"})
ORDER_PATHS: frozenset[str] = frozenset({"/fapi/v1/order", "/fapi/v1/batchOrders"})


class GuardError(PermissionError):
    pass


def normalize_host(rest_url: str) -> str:
    parsed = urlsplit(str(rest_url or "").strip())
    if parsed.scheme.lower() != "https":
        raise GuardError("REST URL must use https")
    if not parsed.hostname:
        raise GuardError("REST URL must contain a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise GuardError("credentials in the REST URL are forbidden")
    if parsed.port not in (None, 443):
        raise GuardError("REST URL must use port 443")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise GuardError("REST base URL must not carry a path, query or fragment")
    host = parsed.hostname.lower()
    if host not in ALLOWED_HOSTS:
        raise GuardError(f"host {host!r} is not an allowed demo/testnet host")
    return host


def is_risk_reducing(method: str, path: str, params: Mapping[str, Any]) -> bool:
    if method == "DELETE":
        return True
    if path in ORDER_PATHS:
        flag = str(params.get("reduceOnly", "false")).lower()
        return flag == "true" or str(params.get("closePosition", "false")).lower() == "true"
    return path not in ORDER_PATHS  # leverage / margin type / listen-key style session control


def _as_paths(value: str | Path | Sequence[str | Path] | None) -> tuple[Path, ...]:
    """One path, several, or none - callers predate the plural and must keep working."""
    if value is None:
        return ()
    if isinstance(value, (str, Path)):
        return (Path(value),)
    return tuple(Path(item) for item in value)


class WriteGuard:
    def __init__(self, rest_url: str, kill_switch_path: str | Path | Sequence[str | Path] | None = None) -> None:
        self.host = normalize_host(rest_url)
        self.kill_switch_paths = _as_paths(kill_switch_path)

    @property
    def kill_switch_path(self) -> Path | None:
        """The first configured path, kept for callers and logs that name a single file."""
        return self.kill_switch_paths[0] if self.kill_switch_paths else None

    def kill_switch_engaged(self) -> bool:
        """Engaged if ANY configured file exists (L1-07).

        Three places ask this question - the engine's guard, this one at the HTTP layer, and the CLI -
        and the account-scoped path was added to only the first.  This is the one that refuses a
        risk-adding order at the wire, so a switch the engine honours and the guard does not would be
        the worst of the three to leave disagreeing.
        """
        return any(path.exists() for path in self.kill_switch_paths)

    def engage_kill_switch(self, reason: str = "") -> Path:
        if self.kill_switch_path is None:
            raise GuardError("no kill switch path configured")
        self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.write_text(reason or "engaged\n", encoding="utf-8")
        return self.kill_switch_path

    def authorize(self, method: str, path: str, params: Mapping[str, Any]) -> None:
        method = method.upper()
        if method not in MUTATING_METHODS:
            return
        if self.kill_switch_engaged() and not is_risk_reducing(method, path, params):
            raise GuardError(f"kill switch engaged at {self.kill_switch_path}; risk-increasing write refused")
