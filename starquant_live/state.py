"""Durable, human-readable live state: state.json, trades.jsonl, attribution.jsonl, cycles.jsonl, heartbeat.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StateUnreadable(Exception):
    """``state.json`` is there and cannot be parsed.  Refuse, do not start fresh.

    Until 2026-09-13 this case returned an empty ``LiveState()`` - no raise, no alert, no row - and
    four cross-cycle facts that exist in exactly one copy went with it: ``last_income_ms`` (the income
    watermark, whose loss sends `_ingest_income`'s window to ``[now, now]`` and drops every income row
    earned while the loop was down, permanently, out of ``attribution.jsonl``), ``equity_hwm`` (the
    drawdown reads 0 and D-015's throttle and R8's ladder both go blind at once), ``exit_states`` (every
    entry anchor is rebuilt from the venue's VWAP) and ``last_contributions`` (D-005's hold seed zeroes
    once).  KILL-006 rests M-010's 30-day window on that first one being continuous, and `decay_watch`
    reading a SHORTER `live_windows` cannot tell "the loop ran less" from "a chunk is missing".

    So the answer to a file that will not parse is to stop and say so.  The operator's way out is in
    the message: rename the bad file and let the next start rebuild, which is a DECISION with a record
    rather than a silent reset nobody sees.
    """


@dataclass
class LiveState:
    last_bar_ms: int | None = None
    last_targets: dict[str, float] = field(default_factory=dict)
    last_contributions: dict[str, dict[str, float]] = field(default_factory=dict)
    last_equity: float | None = None
    day: str | None = None
    day_start_equity: float | None = None
    last_income_ms: int | None = None
    leverage_set: dict[str, int] = field(default_factory=dict)
    exit_states: dict[str, dict[str, Any]] = field(default_factory=dict)  # per-symbol exit overlay state (D-012)
    equity_hwm: float | None = None  # high-water mark for the drawdown throttle (D-015)
    universe: list[str] = field(default_factory=list)  # last refreshed universe (D-014)
    universe_day: str | None = None
    leaving: list[str] = field(default_factory=list)  # symbols that left the universe but still hold a position
    reject_streak: dict[str, int] = field(default_factory=dict)  # consecutive rejected orders per symbol (D-031)
    # Same shape as `reject_streak`, pointed at the other silent exit: consecutive cycles whose inputs
    # carried no usable bars for a symbol.  Persisted because the streak has to survive a restart -
    # a loop that restarts every time the venue's kline endpoint flaps would otherwise never reach the
    # threshold, and a delisting would never be acted on.
    dropped_streak: dict[str, int] = field(default_factory=dict)
    # The PRE-throttle model weights of the last completed cycle, which is what a symbol whose data
    # went missing holds onto.  `last_targets` is post-throttle/post-guard and would be throttled a
    # second time when re-used as an input; this is the quantity the model actually produced.
    last_raw_targets: dict[str, float] = field(default_factory=dict)
    stopped_books: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # probe books closed by their stop rule (D-019)
    # R8 / DL-G7: how many consecutive cycles the attributed drawdown has sat on a ladder rung, and
    # whether the first crossing was already announced.  Persisted for the same reason `stopped_books`
    # is: a restart must not hand the book a fresh two-cycle grace on a breach that never lifted.
    risk_ladder: dict[str, Any] = field(default_factory=dict)
    last_clock_skew_ms: float | None = None  # venue time minus host time at the last cycle
    last_guard_reasons: list[str] = field(default_factory=list)  # edge-trigger for the guard alert
    # `consecutive_errors` deliberately absent (DL-L2): the streak belongs to the process, not to the
    # book.  Persisting it meant a restart inherited a tripped breaker's count and tripped again at once
    # (L1-03 / KILL-R29).  `from_dict` drops the key, so an old state.json still loads.
    restarts: int = 0  # process restarts since the state file was created (M-004)
    restarted_at: str | None = None
    cycles: int = 0
    started_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LiveState:
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        return cls(**known)


class StateStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "state.json"
        self.trades_path = self.directory / "trades.jsonl"
        self.attribution_path = self.directory / "attribution.jsonl"
        self.cycles_path = self.directory / "cycles.jsonl"
        self.heartbeat_path = self.directory / "heartbeat.json"
        # path -> (size, mtime_ns, parsed rows).  See `read_jsonl`.
        self._jsonl_cache: dict[Path, tuple[int, int, list[dict[str, Any]]]] = {}

    def load(self) -> LiveState:
        """A missing file is a first start; a file that will not parse is a refusal (see `StateUnreadable`).

        The two used to share one answer - a fresh `LiveState()` - and that is the whole defect: the
        only difference between "this account has never traded" and "the only copy of the income
        watermark is corrupt" was a file on disk that nobody looked at again.
        """
        if not self.state_path.exists():
            return LiveState()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StateUnreadable(self._unreadable_message(exc)) from exc
        if not isinstance(payload, dict):
            raise StateUnreadable(self._unreadable_message(f"top level is {type(payload).__name__}, not an object"))
        try:
            return LiveState.from_dict(payload)
        except TypeError as exc:  # a known key holding a shape the dataclass cannot take
            raise StateUnreadable(self._unreadable_message(exc)) from exc

    def _unreadable_message(self, detail: object) -> str:
        """One message, and it has to contain the way out - an operator reads this at 03:00."""
        return (
            f"{self.state_path} exists but cannot be read as live state ({detail}). "
            "Refusing to start on an empty state: it would silently lose the income watermark "
            "(last_income_ms), the drawdown high-water mark, the exit anchors and D-005's hold seed, "
            "and M-010's out-of-sample window would restart from now with nothing saying a chunk is "
            f"missing.  To rebuild deliberately: `mv {self.state_path} {self.state_path}.bad` and start "
            "again, then check attribution.jsonl's since_ms/until_ms for the gap that leaves."
        )

    def save(self, state: LiveState) -> None:
        state.updated_at = utc_now_iso()
        self._atomic_write(self.state_path, json.dumps(state.to_dict(), indent=2, sort_keys=True))

    def heartbeat(self, payload: dict[str, Any]) -> None:
        self._atomic_write(self.heartbeat_path, json.dumps({"at": utc_now_iso(), **payload}, indent=2, sort_keys=True))

    def read_heartbeat(self) -> dict[str, Any] | None:
        if not self.heartbeat_path.exists():
            return None
        try:
            payload = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def append_trade(self, record: dict[str, Any]) -> None:
        self._append(self.trades_path, record)

    def append_attribution(self, record: dict[str, Any]) -> None:
        self._append(self.attribution_path, record)

    def append_cycle(self, record: dict[str, Any]) -> None:
        self._append(self.cycles_path, record)

    @staticmethod
    def _parse_jsonl(text: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """Every row in an append-only ledger, parsing only what is new since the last call.

        `run_cycle` reads `cycles.jsonl` and `attribution.jsonl` twice each - `_risk_ladder` and
        `_check_probes` - and `report daily` reads `cycles.jsonl` eleven times for one report.  Each of
        those used to re-read and re-parse the whole file: at 319 rows and 5.5 KB a row that is about
        7 MB per cycle today, and at one bar an hour the ledger grows ~48 MB a year, so the same code
        re-parses ~190 MB per cycle after a year.  Nothing about the work was necessary: `_append`
        writes whole lines and never rewrites one.

        So the parsed rows are kept and only the appended bytes are parsed.  The cache is keyed on the
        file's size and mtime, and ANY disagreement with what was cached - a shrink, an mtime that went
        backwards, a truncation and rewrite by another process - falls back to a full re-read rather
        than trusting the tail.  The returned list is a copy: callers sort and mutate these rows, and a
        cache a caller can edit is worse than no cache.
        """
        if not path.exists():
            self._jsonl_cache.pop(path, None)
            return []
        stat = path.stat()
        cached = self._jsonl_cache.get(path)
        if cached is not None:
            size, mtime, rows = cached
            if size == stat.st_size and mtime == stat.st_mtime_ns:
                return list(rows)
            if stat.st_size > size and mtime <= stat.st_mtime_ns and size > 0:
                # A seek lands on a byte offset, not a row boundary.  `_append` only ever writes whole
                # lines, so the byte before the resume point is a newline whenever the cached size was
                # taken at one - and when it is not (a torn write, an editor, a different writer), the
                # tail would splice a half row onto a whole one.  Check rather than assume.
                with path.open("rb") as handle:
                    handle.seek(size - 1)
                    if handle.read(1) == b"\n":
                        tail = handle.read().decode("utf-8", errors="replace")
                        grown = rows + self._parse_jsonl(tail)
                        self._jsonl_cache[path] = (stat.st_size, stat.st_mtime_ns, grown)
                        return list(grown)
        rows = self._parse_jsonl(path.read_text(encoding="utf-8"))
        self._jsonl_cache[path] = (stat.st_size, stat.st_mtime_ns, rows)
        return list(rows)

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        """One complete line, on the disk before we return (L1-14).

        These are the append-only ledgers every post-mortem reads, and the row that matters most is
        always the last one written before whatever went wrong.  At one row an hour the fsync costs
        nothing; leaving it in a buffer costs the only copy of what the loop was doing.
        """
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": utc_now_iso(), **record}, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """tmp -> fsync -> replace -> fsync the directory.  Same standard as `_append` (L1-14).

        This file had two standards in it until 2026-09-13: `_append` above wrote six lines about why
        a ledger row must be on the disk before the call returns and fsynced, while this one - which
        writes state.json, the ONLY copy of the income watermark and the drawdown high-water mark -
        did tmp + `replace` and nothing else.  `replace` is atomic about the RENAME; it promises
        nothing about the tmp file's CONTENTS having left the page cache, so a power loss between the
        write and the flush can publish a name pointing at a zero-length or half-written file.  That
        is exactly the file `load` now refuses to start on, so the cheap fix belongs here rather than
        in the refusal.

        The directory fsync is what makes the rename itself durable, and it is best effort: some
        filesystems refuse a directory fsync, and failing to make a heartbeat durable must never be
        the reason a cycle fails.
        """
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        try:
            fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
