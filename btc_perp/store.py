"""Durable intents, strategy memory, and single-writer locks.

The state directory is stamped with demo or prod and bound to one credential
fingerprint. A second process on the same directory, or on the same account
through another directory, does not get the lock. Locks use ``fcntl``: Linux
and macOS on one machine. Running one account from two machines is not
supported.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import IO, cast

from btc_perp.model import Book, Intent

JOURNAL_MAX_BYTES = 32 * 1024 * 1024
OPEN_PHASES = ("planned", "sent", "unknown", "acked", "partial")

_SCHEMA = """
create table if not exists intents (
    client_id text primary key,
    action text not null,
    phase text not null,
    side text not null,
    qty text not null,
    reduce_only integer not null,
    close_position integer not null,
    trigger_price text not null,
    environment text not null,
    created_ms integer not null,
    note text not null,
    attempts integer not null default 1,
    absorbed integer not null default 1
);
create table if not exists kv (
    key text primary key,
    value text not null
);
create index if not exists intents_phase on intents(phase);
"""


class Store:
    def __init__(self, directory: Path, environment: str) -> None:
        if environment not in {"demo", "prod"}:
            raise ValueError("environment must be demo or prod")
        self.directory = directory
        self.environment = environment
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = self.directory / "environment"
        if stamp.exists():
            found = stamp.read_text().strip()
            if found != environment:
                raise RuntimeError(f"状态目录属于 {found}，不会拿来跑 {environment}")
        else:
            stamp.write_text(environment + "\n")
        self._fh = (self.directory / "instance.lock").open("a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("另一个进程已经持有这个状态目录") from exc
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(str(os.getpid()))
        self._fh.flush()
        self._account_fh: IO[str] | None = None
        try:
            self._db = sqlite3.connect(self.directory / "account.sqlite")
            self._open_checked()
        except BaseException:
            self._release()
            raise

    def _open_checked(self) -> None:
        check = self._db.execute("pragma quick_check").fetchone()
        if check is None or str(check[0]) != "ok":
            raise RuntimeError("account.sqlite 没有通过完整性检查，进入只读恢复，不会改成新账户")
        self._db.executescript(_SCHEMA)
        columns = {str(row[1]) for row in self._db.execute("pragma table_info(intents)")}
        if "attempts" not in columns:
            self._db.execute("alter table intents add column attempts integer not null default 1")
        if "absorbed" not in columns:
            self._db.execute("alter table intents add column absorbed integer not null default 1")
        self._db.commit()
        backup = sqlite3.connect(self.directory / "account.sqlite.bak")
        try:
            self._db.backup(backup)
        finally:
            backup.close()

    def bind_credential(self, api_key: str) -> None:
        """Tie this state to one credential and take the account-wide write lock.

        The fingerprint is a hash of the key, not the key. It stops A's peak,
        cursor, and intents from being reused under B's credentials, and stops
        a second state directory from driving the same account.
        """
        fingerprint = hashlib.sha256(("starquant\0" + api_key).encode()).hexdigest()[:16]
        stored = self.get_json("credential")
        if stored is not None and stored != fingerprint:
            raise RuntimeError("状态目录绑定的是另一组凭据，不会拿来跑这一组")
        lock_dir = Path(os.environ.get("STARQUANT_LOCK_DIR", "") or tempfile.gettempdir())
        lock_dir.mkdir(parents=True, exist_ok=True)
        handle = (lock_dir / f"starquant-{self.environment}-{fingerprint}.lock").open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise RuntimeError("同一账户已有另一个状态目录的进程在运行") from exc
        self._account_fh = handle
        if stored is None:
            self.put_json("credential", fingerprint)

    def _release(self) -> None:
        if self._account_fh is not None:
            fcntl.flock(self._account_fh.fileno(), fcntl.LOCK_UN)
            self._account_fh.close()
            self._account_fh = None
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()

    def close(self) -> None:
        self._db.close()
        self._release()

    def put_json(self, key: str, value: object) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self._db.execute(
            "insert into kv(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
            (key, raw),
        )
        self._db.commit()

    def get_json(self, key: str) -> object | None:
        row = self._db.execute("select value from kv where key=?", (key,)).fetchone()
        if row is None:
            return None
        return cast(object, json.loads(str(row[0])))

    def save_book(self, book: Book) -> None:
        self.put_json(
            "book",
            {
                "side": book.side,
                "qty": book.qty,
                "entry": book.entry,
                "units": book.units,
                "extreme": book.extreme,
                "last_add": book.last_add,
                "stop": book.stop,
                "cooldown_until_ms": book.cooldown_until_ms,
                "peak_equity_cny": book.peak_equity_cny,
                "close_peak_cny": book.close_peak_cny,
                "cursor_ms": book.cursor_ms,
                "entries_frozen": book.entries_frozen,
                "freeze_reason": book.freeze_reason,
                "unprotected_since_ms": book.unprotected_since_ms,
                "day_key": book.day_key,
                "day_realized_usdt": book.day_realized_usdt,
                "manual": book.manual,
                "dd_locked": book.dd_locked,
                "swaps": book.swaps,
                "alerts": book.alerts[-50:],
            },
        )

    def load_book(self) -> Book:
        raw = self.get_json("book")
        if raw is None:
            return Book()
        if not isinstance(raw, dict):
            raise RuntimeError("策略记忆已损坏，进入只读恢复，不会当成新账户")
        book = Book()
        book.side = int(raw.get("side", 0))
        book.qty = float(raw.get("qty", 0.0))
        book.entry = float(raw.get("entry", 0.0))
        book.units = int(raw.get("units", 0))
        book.extreme = float(raw.get("extreme", 0.0))
        book.last_add = float(raw.get("last_add", 0.0))
        book.stop = float(raw.get("stop", 0.0))
        book.cooldown_until_ms = int(raw.get("cooldown_until_ms", 0))
        book.peak_equity_cny = float(raw.get("peak_equity_cny", 0.0))
        book.close_peak_cny = float(raw.get("close_peak_cny", 0.0))
        book.cursor_ms = int(raw.get("cursor_ms", 0))
        book.entries_frozen = bool(raw.get("entries_frozen", False))
        book.freeze_reason = str(raw.get("freeze_reason", ""))
        since = raw.get("unprotected_since_ms")
        book.unprotected_since_ms = None if since is None else int(since)
        book.day_key = str(raw.get("day_key", ""))
        book.day_realized_usdt = float(raw.get("day_realized_usdt", 0.0))
        book.manual = bool(raw.get("manual", False))
        book.dd_locked = bool(raw.get("dd_locked", False))
        swaps = raw.get("swaps", {})
        book.swaps = {str(k): str(v) for k, v in swaps.items()} if isinstance(swaps, dict) else {}
        alerts = raw.get("alerts", [])
        book.alerts = [str(item) for item in alerts] if isinstance(alerts, list) else []
        return book

    def insert_intent(self, intent: Intent) -> None:
        if intent.environment != self.environment:
            raise RuntimeError("意图上的环境与状态目录不一致")
        self._db.execute(
            """insert into intents(
                client_id, action, phase, side, qty, reduce_only, close_position,
                trigger_price, environment, created_ms, note, attempts, absorbed
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                intent.client_id,
                intent.action,
                intent.phase,
                intent.side,
                intent.qty,
                int(intent.reduce_only),
                int(intent.close_position),
                intent.trigger_price,
                intent.environment,
                intent.created_ms,
                intent.note,
                intent.attempts,
                int(intent.absorbed),
            ),
        )
        self._db.commit()

    def mark_intent(self, client_id: str, phase: str, note: str = "", *, attempts: int | None = None) -> None:
        if attempts is None:
            self._db.execute("update intents set phase=?, note=? where client_id=?", (phase, note, client_id))
        else:
            self._db.execute(
                "update intents set phase=?, note=?, attempts=? where client_id=?", (phase, note, attempts, client_id)
            )
        self._db.commit()

    def intents(self, phases: tuple[str, ...] | None = None) -> list[Intent]:
        query = (
            "select client_id, action, phase, side, qty, reduce_only, close_position, "
            "trigger_price, environment, created_ms, note, attempts, absorbed from intents"
        )
        args: tuple[str, ...] = ()
        if phases is not None:
            query += " where phase in (" + ",".join("?" for _ in phases) + ")"
            args = phases
        rows = self._db.execute(query + " order by created_ms, rowid", args).fetchall()
        return [
            Intent(
                client_id=str(row[0]),
                action=str(row[1]),
                phase=str(row[2]),
                side=str(row[3]),
                qty=str(row[4]),
                reduce_only=bool(row[5]),
                close_position=bool(row[6]),
                trigger_price=str(row[7]),
                environment=str(row[8]),
                created_ms=int(row[9]),
                note=str(row[10]),
                attempts=int(row[11]),
                absorbed=bool(row[12]),
            )
            for row in rows
        ]

    def open_intents(self) -> list[Intent]:
        return self.intents(OPEN_PHASES)

    def mark_absorbed(self, client_id: str) -> None:
        self._db.execute("update intents set absorbed=1 where client_id=?", (client_id,))
        self._db.commit()

    def settle_absorbed(self) -> None:
        """The book now matches the account: every finished position order has been counted."""
        marks = ",".join("?" for _ in OPEN_PHASES)
        self._db.execute(f"update intents set absorbed=1 where absorbed=0 and phase not in ({marks})", OPEN_PHASES)
        self._db.commit()

    def all_client_ids(self) -> set[str]:
        return {str(row[0]) for row in self._db.execute("select client_id from intents")}

    def append_event(self, kind: str, detail: str) -> None:
        events = self.get_json("events")
        row = {"kind": kind, "detail": detail}
        if isinstance(events, list):
            events.append(row)
        else:
            events = [row]
        self.put_json("events", events[-500:])

    def append_journal(self, row: dict[str, object]) -> None:
        """Append one redacted cycle or transmit line. This file is the forward record."""
        path = self.directory / "journal.jsonl"
        if path.exists() and path.stat().st_size > JOURNAL_MAX_BYTES:
            path.replace(self.directory / "journal.jsonl.1")
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
