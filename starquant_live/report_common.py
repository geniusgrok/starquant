"""What every report block reads the live state files with, and prints its numbers with.

Split out of `reports.py` on 2026-09-25 with the rest of the monitoring layer (see that module's
docstring).  Nothing here judges anything: which day a row belongs to, the cycles in a window, the
current construction's evidence window, the archive's closes, and three formatters.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_data.store import KlineStore
from starquant_live.construction import canonical_construction
from starquant_live.state import LiveState, StateStore, StateUnreadable


def _day_of(record: dict[str, Any]) -> str | None:
    """The UTC day a record belongs to, preferring the bar its data carried (D-025).

    ``bar_open_ms`` is derived from the host clock, which is the reference for scheduling but may sit a
    whole bar away from the venue's; ``as_of_ms`` comes from the klines themselves.  Bucketing by the
    data keeps a day's report describing the day that was actually traded.
    """
    for key in ("as_of_ms", "bar_open_ms"):
        value = record.get(key)
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%d")
    stamp = record.get("at")
    return str(stamp)[:10] if stamp else None


def _day_end_ms(day: str) -> int:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    return int((start + timedelta(days=1)).timestamp() * 1000)


def readable_state(store: StateStore) -> tuple[LiveState, str]:
    """The persisted state, or an empty one plus the reason it could not be read.

    `StateStore.load` refuses a corrupt state.json rather than returning a fresh `LiveState`, because
    silently zeroing the income watermark is how the only clean out-of-sample series (M-010) loses a
    stretch nothing can later detect.  `starquant live run` must inherit that refusal.  The REPORT must
    not: it is the unattended monitor, it is how a broken file gets noticed at all, and a report that
    dies on the first line tells the operator less than one that renders the venue's equity, the
    guards and the drift next to a sentence naming the file.

    D-035's rule, applied to a file instead of to a metric: what cannot be computed says so and gives
    the reason - it is never read as a zero, and it is never read as "fine".
    """
    try:
        return store.load(), ""
    except StateUnreadable as exc:
        return LiveState(), str(exc)


def _state_problem(store: StateStore) -> str:
    """The reason `state.json` cannot be read, or an empty string when it can."""
    return readable_state(store)[1]


DAY_MS = 86_400_000
# The bars `LiveEngine._liquidity` averages for the participation cap: the profile's `pool.liquidity_window`.
# The cycle record does not carry it, so it is written here and a test holds it to the profile.  Here and
# not in either reader, because the closing reading (3.9) and the per-order one (#10.9) must use one hour.
LIQUIDITY_WINDOW_BARS = 24


def _cycles(store: StateStore, *, window_days: int | None = None, now_ms: int | None = None) -> list[dict[str, Any]]:
    """Traded cycles, newest last.  A failed cycle carries no equity and is not a bar that happened."""
    rows = [
        row for row in store.read_jsonl(store.cycles_path) if row.get("equity") is not None and not row.get("dry_run")
    ]
    if window_days is None:
        return rows
    cutoff = (now_ms or 0) - window_days * DAY_MS
    return (
        [row for row in rows if int(row.get("bar_open_ms") or 0) >= cutoff] if now_ms else rows[-(window_days * 24) :]
    )


def evidence_window(store: StateStore) -> dict[str, Any]:
    """When the currently running construction started (D-026 fingerprint), i.e. when live evidence begins.

    Every change to the book - a signal parameter, a band, a half-life - resets what the live record is
    evidence *of*.  Adopting `conviction_mode: sign` and then P10 cell B on the same day made this
    concrete: the numbers before each change describe a different book.  M-010's 30-day window has to
    start here, not at the first cycle ever recorded.
    """
    rows = [row for row in _cycles(store) if row.get("construction")]
    if not rows:
        return {"construction": None, "since_ms": None, "bars": 0, "changes_7d": 0}
    # Compared through `canonical_construction`, because a digest can move without the book moving: the
    # fingerprint's own field set grew twice on 2026-09-07 (P22, P23) and each time this window reset to
    # one bar while every construction VALUE was identical.  Old rows keep the digest they were written
    # with - history is not rewritten - and the equivalence is declared in code, with its proof.
    current = canonical_construction(rows[-1]["construction"])
    since = rows[-1]
    for row in reversed(rows):
        if canonical_construction(row.get("construction")) != current:
            break
        since = row
    latest_ms = int(rows[-1].get("bar_open_ms") or 0)
    recent = [row for row in rows if int(row.get("bar_open_ms") or 0) >= latest_ms - 7 * DAY_MS]
    changes = sum(
        1
        for a, b in pairwise(recent)
        if canonical_construction(a.get("construction")) != canonical_construction(b.get("construction"))
    )
    return {
        "construction": str(current)[:12],
        "since_ms": int(since.get("bar_open_ms") or 0),
        "bars": sum(1 for row in rows if canonical_construction(row.get("construction")) == current),
        "changes_7d": changes,
    }


def _store_closes(root: str | Path, interval: str) -> Callable[[str], pd.Series]:
    def loader(symbol: str) -> pd.Series:
        frame = KlineStore(root).load(symbol, interval)
        return pd.Series(frame["close"].astype(float).to_numpy(), index=frame["open_time"].astype(int).to_numpy())

    return loader


def _parsed(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _fmt_num(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def _fmt_pct(value: Any) -> str:
    return "n/a" if value is None else f"{100.0 * float(value):.2f}%"
