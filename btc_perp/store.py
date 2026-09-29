"""Durable intents, strategy memory, and single-writer locks.

The state directory is stamped with demo or prod and bound to one credential
fingerprint. A second process on the same directory, or on the same account
through another directory, does not get the lock. Locks use ``fcntl``: Linux
and macOS on one machine. Running one account from two machines is not
supported.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, cast

from btc_perp.model import Book, Intent

JOURNAL_MAX_BYTES = 32 * 1024 * 1024
JOURNAL_KEEP = 5
BACKUP_KEEP = 7
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
    absorbed integer not null default 1,
    order_id text not null default ''
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
        self._depth = 0
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
        existing = {str(row[0]) for row in self._db.execute("select name from sqlite_master where type='table'")}
        if "intents" in existing:
            columns = {str(row[1]) for row in self._db.execute("pragma table_info(intents)")}
            missing = {"attempts", "absorbed", "order_id"} - columns
            if missing:
                self._keep_pre_upgrade_copy()
        self._db.executescript(_SCHEMA)
        known_phases = (*OPEN_PHASES, "filled", "rejected", "canceled", "expired")
        odd = self._db.execute(
            "select client_id, phase from intents where phase not in (" + ",".join("?" for _ in known_phases) + ")",
            known_phases,
        ).fetchone()
        if odd is not None:
            raise RuntimeError(f"意图 {odd[0]} 的阶段 {odd[1]!r} 无法识别，进入只读恢复，不会忽略它")
        columns = {str(row[1]) for row in self._db.execute("pragma table_info(intents)")}
        if "attempts" not in columns:
            self._db.execute("alter table intents add column attempts integer not null default 1")
        if "absorbed" not in columns:
            self._db.execute("alter table intents add column absorbed integer not null default 1")
        if "order_id" not in columns:
            self._db.execute("alter table intents add column order_id text not null default ''")
        self._db.commit()
        self.load_book()
        self._archive()

    def _keep_pre_upgrade_copy(self) -> None:
        target = self.directory / "account.pre-upgrade.sqlite"
        if target.exists():
            return
        backup = sqlite3.connect(target)
        try:
            self._db.backup(backup)
        finally:
            backup.close()

    def _archive(self) -> None:
        """A dated copy per UTC day, taken only from a database that passed the semantic load."""
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        today = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
        dated = folder / f"account-{today}.sqlite"
        if not dated.exists():
            copy = sqlite3.connect(dated)
            try:
                self._db.backup(copy)
            finally:
                copy.close()
        for old in sorted(folder.glob("account-*.sqlite"))[:-BACKUP_KEEP]:
            old.unlink(missing_ok=True)

    def restore_latest_backup(self) -> Path | None:
        """Newest dated copy that opens and passes the integrity check. Nothing is replaced here."""
        for candidate in sorted((self.directory / "backups").glob("account-*.sqlite"), reverse=True):
            probe = sqlite3.connect(candidate)
            try:
                row = probe.execute("pragma quick_check").fetchone()
            except sqlite3.DatabaseError:
                continue
            finally:
                probe.close()
            if row is not None and str(row[0]) == "ok":
                return candidate
        return None

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Several writes that must land together or not at all."""
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._db.rollback()
            raise
        self._depth -= 1
        if self._depth == 0:
            self._db.commit()

    def _commit(self) -> None:
        if self._depth == 0:
            self._db.commit()

    def bind_credential(self, api_key: str, uid: str = "") -> None:
        """Tie this state to one account and take the account-wide write lock.

        With a UID the state follows the account: a new key for the same UID
        keeps the peak, intents and history, and two directories driving the
        same UID exclude each other. Without a UID the binding is the key
        fingerprint, which cannot see two keys on one account.
        """
        fingerprint = hashlib.sha256(("starquant\0" + api_key).encode()).hexdigest()[:16]
        stored = self.get_json("account")
        legacy = self.get_json("credential")
        if stored is None and isinstance(legacy, str):
            stored = {"id": "key:" + legacy, "keys": [legacy]}
        if stored is not None and not isinstance(stored, dict):
            raise RuntimeError("账户绑定记录已损坏，不会当成新账户")
        keys = [str(item) for item in stored.get("keys", [])] if isinstance(stored, dict) else []
        current = f"uid:{uid}" if uid else f"key:{fingerprint}"
        if isinstance(stored, dict):
            bound = str(stored.get("id", ""))
            if bound.startswith("uid:"):
                if uid and bound != current:
                    raise RuntimeError("状态目录绑定的是另一个账户 UID，不会拿来跑这一个")
                if not uid and fingerprint not in keys:
                    raise RuntimeError("状态目录绑定了账户 UID，这把密钥没有见过；请设置 STARQUANT_ACCOUNT_UID")
                current = bound
            elif uid:
                if fingerprint not in keys:
                    raise RuntimeError("状态目录绑定的是另一组凭据，不能升级成 UID 绑定")
            elif bound != current:
                raise RuntimeError("状态目录绑定的是另一组凭据，不会拿来跑这一组")
        lock_dir = Path(os.environ.get("STARQUANT_LOCK_DIR", "") or tempfile.gettempdir())
        lock_dir.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha256(current.encode()).hexdigest()[:16]
        handle = (lock_dir / f"starquant-{self.environment}-{tag}.lock").open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise RuntimeError("同一账户已有另一个状态目录的进程在运行") from exc
        self._account_fh = handle
        if fingerprint not in keys:
            keys.append(fingerprint)
        self.put_json("account", {"id": current, "keys": keys[-8:]})

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
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self._db.execute(
            "insert into kv(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
            (key, raw),
        )
        self._commit()

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

        def number(key: str, *, low: float | None = 0.0) -> float:
            value = raw.get(key, 0.0)
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
                raise RuntimeError(f"策略记忆 {key} 不是有限数字，进入只读恢复")
            if low is not None and float(value) < low:
                raise RuntimeError(f"策略记忆 {key} 超出范围，进入只读恢复")
            return float(value)

        def whole(key: str) -> int:
            value = raw.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuntimeError(f"策略记忆 {key} 不是非负整数，进入只读恢复")
            return value

        book = Book()
        side = raw.get("side", 0)
        if isinstance(side, bool) or side not in (-1, 0, 1):
            raise RuntimeError("策略记忆 side 不是 -1/0/1，进入只读恢复")
        book.side = int(side)
        book.qty = number("qty")
        book.entry = number("entry")
        book.units = whole("units")
        book.extreme = number("extreme")
        book.last_add = number("last_add")
        book.stop = number("stop")
        book.cooldown_until_ms = whole("cooldown_until_ms")
        book.peak_equity_cny = number("peak_equity_cny")
        book.close_peak_cny = number("close_peak_cny")
        book.cursor_ms = whole("cursor_ms")
        book.entries_frozen = bool(raw.get("entries_frozen", False))
        book.freeze_reason = str(raw.get("freeze_reason", ""))
        since = raw.get("unprotected_since_ms")
        if since is not None and (isinstance(since, bool) or not isinstance(since, int) or since < 0):
            raise RuntimeError("策略记忆 unprotected_since_ms 无效，进入只读恢复")
        book.unprotected_since_ms = None if since is None else int(since)
        book.day_key = str(raw.get("day_key", ""))
        book.day_realized_usdt = number("day_realized_usdt", low=None)
        book.manual = bool(raw.get("manual", False))
        book.dd_locked = bool(raw.get("dd_locked", False))
        swaps = raw.get("swaps", {})
        if not isinstance(swaps, dict):
            raise RuntimeError("策略记忆 swaps 无效，进入只读恢复")
        book.swaps = {str(k): str(v) for k, v in swaps.items()}
        alerts = raw.get("alerts", [])
        book.alerts = [str(item) for item in alerts] if isinstance(alerts, list) else []
        return book

    def insert_intent(self, intent: Intent) -> None:
        if intent.environment != self.environment:
            raise RuntimeError("意图上的环境与状态目录不一致")
        self._db.execute(
            """insert into intents(
                client_id, action, phase, side, qty, reduce_only, close_position,
                trigger_price, environment, created_ms, note, attempts, absorbed, order_id
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                intent.order_id,
            ),
        )
        self._commit()

    def record_send(self, intent: Intent, book: Book) -> None:
        """The request, the attempt state, and the strategy memory it depends on, in one commit."""
        with self.transaction():
            self.insert_intent(intent)
            self.save_book(book)

    def mark_intent(
        self, client_id: str, phase: str, note: str = "", *, attempts: int | None = None, order_id: str = ""
    ) -> None:
        if attempts is None:
            self._db.execute("update intents set phase=?, note=? where client_id=?", (phase, note, client_id))
        else:
            self._db.execute(
                "update intents set phase=?, note=?, attempts=? where client_id=?", (phase, note, attempts, client_id)
            )
        if order_id:
            self._db.execute("update intents set order_id=? where client_id=?", (order_id, client_id))
        self._commit()

    def own_order_ids(self) -> set[str]:
        return {str(row[0]) for row in self._db.execute("select order_id from intents where order_id != ''")}

    def intents(self, phases: tuple[str, ...] | None = None) -> list[Intent]:
        query = (
            "select client_id, action, phase, side, qty, reduce_only, close_position, "
            "trigger_price, environment, created_ms, note, attempts, absorbed, order_id from intents"
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
                order_id=str(row[13]),
            )
            for row in rows
        ]

    def open_intents(self) -> list[Intent]:
        return self.intents(OPEN_PHASES)

    def mark_absorbed(self, client_id: str) -> None:
        self._db.execute("update intents set absorbed=1 where client_id=?", (client_id,))
        self._commit()

    def mark_unabsorbed(self, client_id: str) -> None:
        """A finished order whose effect on the position the book has not counted yet."""
        self._db.execute("update intents set absorbed=0 where client_id=?", (client_id,))
        self._commit()

    def settle_absorbed(self) -> None:
        """The book now matches the account: every finished position order has been counted."""
        marks = ",".join("?" for _ in OPEN_PHASES)
        self._db.execute(f"update intents set absorbed=1 where absorbed=0 and phase not in ({marks})", OPEN_PHASES)
        self._commit()

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
        self.append_journal({"kind": "event", "event": kind, "detail": detail})

    def append_journal(self, row: dict[str, object]) -> None:
        """Append one redacted cycle or transmit line. This file is the forward record."""
        path = self.directory / "journal.jsonl"
        if path.exists() and path.stat().st_size > JOURNAL_MAX_BYTES:
            for index in range(JOURNAL_KEEP, 1, -1):
                older = self.directory / f"journal.jsonl.{index - 1}"
                if older.exists():
                    shutil.move(older, self.directory / f"journal.jsonl.{index}")
            path.replace(self.directory / "journal.jsonl.1")
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
