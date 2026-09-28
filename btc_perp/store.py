"""Durable intents, strategy memory, and a single-process lock.

The state directory is stamped with demo or prod. A second process, or the
other environment, does not get the lock.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from pathlib import Path
from typing import cast

from btc_perp.model import Book, Intent

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
    note text not null
);
create table if not exists kv (
    key text primary key,
    value text not null
);
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
        self._db = sqlite3.connect(self.directory / "account.sqlite")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()

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
                "swaps": book.swaps,
                "alerts": book.alerts[-50:],
            },
        )

    def load_book(self) -> Book:
        raw = self.get_json("book")
        if not isinstance(raw, dict):
            return Book()
        book = Book()
        book.side = int(raw.get("side", 0))
        book.qty = float(raw.get("qty", 0.0))
        book.entry = float(raw.get("entry", 0.0))
        book.units = int(raw.get("units", 0))
        book.extreme = float(raw.get("extreme", 0.0))
        book.last_add = float(raw.get("last_add", 0.0))
        book.stop = float(raw.get("stop", 0.0))
        book.cooldown_until_ms = int(raw.get("cooldown_until_ms", 0))
        book.peak_equity_cny = float(raw.get("peak_equity_cny", 10_000.0))
        book.close_peak_cny = float(raw.get("close_peak_cny", 10_000.0))
        book.cursor_ms = int(raw.get("cursor_ms", 0))
        book.entries_frozen = bool(raw.get("entries_frozen", False))
        book.freeze_reason = str(raw.get("freeze_reason", ""))
        since = raw.get("unprotected_since_ms")
        book.unprotected_since_ms = None if since is None else int(since)
        book.day_key = str(raw.get("day_key", ""))
        book.day_realized_usdt = float(raw.get("day_realized_usdt", 0.0))
        book.manual = bool(raw.get("manual", False))
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
                trigger_price, environment, created_ms, note
            ) values(?,?,?,?,?,?,?,?,?,?,?)""",
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
            ),
        )
        self._db.commit()

    def mark_intent(self, client_id: str, phase: str, note: str = "") -> None:
        self._db.execute(
            "update intents set phase=?, note=? where client_id=?",
            (phase, note, client_id),
        )
        self._db.commit()

    def intents(self) -> list[Intent]:
        rows = self._db.execute(
            "select client_id, action, phase, side, qty, reduce_only, close_position, "
            "trigger_price, environment, created_ms, note from intents order by created_ms"
        ).fetchall()
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
            )
            for row in rows
        ]

    def open_intents(self) -> list[Intent]:
        return [item for item in self.intents() if item.phase in {"planned", "sent", "unknown", "acked", "partial"}]

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
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
