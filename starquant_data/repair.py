"""`starquant data repair`: ask the sources once for every hole in the stored archive (9.4, 2026-09-25).

`KlineStore.gaps` has found holes since 2026-09-04 (T-D01) and nothing mended them.  GRTUSDT's 120 bars
came back from a one-off REST call; every other hole stayed one, and a backtest reads a hole as a jump.
A hole is one of two things and only the sources can say which.  Either they hold the rows and a sync
lost them - the monthly files lack 2022-02-26..28 and 2022-04-01..02, REST filled those days for the 146
members of 2026-09-03's table, and eighteen symbols still carry both holes, three of them members of
today's - or they do not, and the hole is a fact about the market: a contract relisted under an old
name, a redenomination halt.

So each hole is asked for once, in the order `starquant data sync` trusts its sources: the daily archive
files that cover it (checksummed, like the monthly ones), then REST for whatever they left.  Only rows
strictly inside the hole are merged, through the store's own ``append``.  A stored row is never
rewritten, so the dedupe rule has nothing to decide and the sync's watermark does not move.  A source
whose rows disagree with a stored row it overlaps is not used at all - it may be a different series
under the same name.  What no source holds goes into ``confirmed_gaps.json`` beside the data: `data
status` stops reporting it, and research can tell a confirmed absence from a sync that never finished.

Nothing here fills a price.  No interpolation, no forward fill.  A hole the sources do not have stays a
hole, and the record says who was asked and what they answered.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from starquant_data.archive import ArchiveClient
from starquant_data.binance_public import (
    MAX_FUNDING_LIMIT,
    MAX_KLINE_LIMIT,
    PublicClient,
    drop_unclosed,
    is_invalid_symbol,
)
from starquant_data.store import FundingStore, KlineStore, interval_ms

CONFIRMED_GAPS_FILE = "confirmed_gaps.json"
FUNDING = "funding"
HOUR_MS = 3_600_000
DAY_MS = 86_400_000

NEIGHBOURS = 6
"""Settlement steps on each side of a step that set the symbol's local schedule (see `funding_holes`)."""

# Dry-run estimates, measured 2026-09-25 on five real days of stored 1h rows (BTC, GTC, BNX, 1000PEPE,
# ICP) rebuilt in the archive's CSV layout: a daily zip of 24 bars is 1,176-1,544 bytes, a REST kline
# row 118-155 bytes of JSON, a funding row 104.  Rounded up; an estimate, not a size the venue reported.
ZIP_BYTES_PER_BAR = 64
CHECKSUM_BYTES = 110
REST_BYTES_PER_KLINE = 150
REST_BYTES_PER_SETTLEMENT = 110

_KLINE_CHECKED = ("open", "high", "low", "close", "volume", "close_time")


@dataclass(frozen=True)
class Gap:
    """A hole between two stored stamps: ``after`` is the last row before it, ``before`` the first after it.

    ``dataset`` is ``klines/<interval>`` or ``funding``.  ``missing`` counts bars, or for funding the
    settlements the local schedule expected - an estimate there, because the schedule can change inside
    the hole.  The key is the exact pair `KlineStore.gaps` reports, so a confirmation covers that hole and
    no other: fill part of it later and what is left is a new hole, reported again.
    """

    dataset: str
    symbol: str
    after: int
    before: int
    missing: int

    @property
    def key(self) -> tuple[str, str, int, int]:
        return (self.dataset, self.symbol, self.after, self.before)


def funding_holes(times: Sequence[int] | np.ndarray) -> list[tuple[int, int, int]]:
    """``(after, before, missing)`` for each settlement the symbol's own schedule says is absent.

    The schedule is not one number.  The archive holds 1h, 2h, 4h and 8h steps and a symbol moves between
    them (API3USDT: 6,148 steps of 4h, 1,794 of 8h, 785 of 1h), so a step is judged against the median of
    the steps on each side of it and is a hole only when it is longer than both.  A switch from 4h to 8h
    is longer than the side before it and not the side after, so it is not one.  The first and last steps
    have one side, and there the step next to them counts as well: LAYERUSDT settled at 4h three times
    after listing and then at 2h, and against the median of the next six alone its first step read as a
    hole.  Stamps are compared by the hour, because `fundingTime` lands milliseconds past it.
    """
    stamps = np.asarray(times, dtype=np.int64)
    steps = np.diff(stamps // HOUR_MS)
    holes: list[tuple[int, int, int]] = []
    for i, step in enumerate(steps):
        before, after = steps[max(0, i - NEIGHBOURS) : i], steps[i + 1 : i + 1 + NEIGHBOURS]
        sides = [float(np.median(side)) for side in (before, after) if len(side)]
        if len(sides) == 1:
            sides.append(float(before[-1] if len(before) else after[0]))
        local = max(sides, default=0.0)
        if local > 0 and step > local:
            holes.append((int(stamps[i]), int(stamps[i + 1]), max(1, round(step / local) - 1)))
    return holes


def find_gaps(
    root: str | Path, interval: str, symbols: Iterable[str] | None = None, *, klines: bool = True, funding: bool = True
) -> list[Gap]:
    """Every hole the two stores hold now, klines first.  ``symbols`` narrows; ``None`` reads every file."""
    wanted = None if symbols is None else set(symbols)
    kline_store, funding_store = KlineStore(root), FundingStore(root)
    found: list[Gap] = []
    if klines:
        step = interval_ms(interval)
        for symbol in kline_store.symbols(interval):
            if wanted is None or symbol in wanted:
                pairs = kline_store.gaps(symbol, interval)
                found += [Gap(f"klines/{interval}", symbol, a, b, (b - a) // step - 1) for a, b in pairs]
    if funding:
        for symbol in funding_store.symbols():
            if wanted is None or symbol in wanted:
                times = funding_store.load(symbol)["funding_time"].astype("int64").to_numpy()
                found += [Gap(FUNDING, symbol, a, b, n) for a, b, n in funding_holes(times)]
    return found


def utc(ms: int) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%MZ")


def read_confirmed(root: str | Path) -> dict[tuple[str, str, int, int], dict[str, Any]]:
    """The confirmed gaps recorded under ``root``, keyed like `Gap.key`.  ``{}`` when none was ever written."""
    path = Path(root) / CONFIRMED_GAPS_FILE
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding="utf-8")).get("gaps", [])
    return {(str(e["dataset"]), str(e["symbol"]), int(e["after"]), int(e["before"])): e for e in entries}


@dataclass(frozen=True)
class Fetch:
    """What asking for one gap would cost, known before anything is asked."""

    gap: Gap
    days: tuple[str, ...]  # daily archive files; funding has none
    rest_calls: int
    est_bytes: int


def plan(gap: Gap) -> Fetch:
    """Daily files for every UTC day a missing bar opens on, and one REST range over the hole and its two ends.

    The REST range includes the two stored rows around the hole on purpose: they are what the source's
    answer is checked against before anything is taken from it.
    """
    rows = gap.missing + 2
    if gap.dataset == FUNDING:
        return Fetch(gap, (), -(-rows // MAX_FUNDING_LIMIT), rows * REST_BYTES_PER_SETTLEMENT)
    step = interval_ms(gap.dataset.split("/", 1)[1])
    first, last = (pd.Timestamp(ms, unit="ms", tz="UTC").normalize() for ms in (gap.after + step, gap.before - step))
    days = tuple(day.strftime("%Y-%m-%d") for day in pd.date_range(first, last, freq="D"))
    per_file = max(1, DAY_MS // step) * ZIP_BYTES_PER_BAR + CHECKSUM_BYTES
    return Fetch(gap, days, -(-rows // MAX_KLINE_LIMIT), len(days) * per_file + rows * REST_BYTES_PER_KLINE)


@dataclass(frozen=True)
class Sources:
    """The three fetches a repair makes, injectable so tests never reach the network.

    ``None`` is an answer - the archive has no such file (404), the venue does not list the symbol
    (-1121).  An exception is not one, and nothing a failed fetch touched is confirmed.
    """

    archive_day: Callable[[str, str, str], pd.DataFrame | None]
    rest_klines: Callable[[str, str, int, int], pd.DataFrame | None]
    rest_funding: Callable[[str, int, int], pd.DataFrame | None]


def venue_sources(archive: ArchiveClient, public: PublicClient) -> Sources:
    """The clients `starquant data sync` uses, with -1121 read as "not listed" rather than as a failure."""

    def listed(fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame | None:
        try:
            return fetch()
        except httpx.HTTPStatusError as exc:
            if is_invalid_symbol(exc):
                return None
            raise

    return Sources(
        archive_day=archive.fetch_day,
        rest_klines=lambda s, i, a, b: listed(lambda: public.klines_range(s, i, a, b)),
        rest_funding=lambda s, a, b: listed(lambda: public.funding_history(s, a, b)),
    )


@dataclass
class Outcome:
    gap: Gap
    added: int = 0
    confirmed: list[Gap] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _disagreements(stored: pd.DataFrame, source: pd.DataFrame, key: str, columns: Sequence[str]) -> int:
    """Stored values the source answers differently, on the rows both hold.  Exact: same source, same bits."""
    both = stored.merge(source, on=key, suffixes=("", "_source"))
    return int(sum((both[column] != both[f"{column}_source"]).sum() for column in columns))


def repair(gap: Gap, *, root: str | Path, sources: Sources, now_ms: int) -> Outcome:
    """Ask for one gap, merge what the sources hold, and say which part of it they do not.

    A part is confirmed only when every fetch for the gap answered and the whole hole has closed by
    ``now_ms``.  A partial repair still merges what it got: those rows are verified source rows either way.
    """
    outcome = (
        _repair_funding(gap, root, sources) if gap.dataset == FUNDING else _repair_klines(gap, root, sources, now_ms)
    )
    if outcome.errors or gap.before > now_ms:
        outcome.confirmed = []
    return outcome


def _repair_klines(gap: Gap, root: str | Path, sources: Sources, now_ms: int) -> Outcome:
    outcome, store = Outcome(gap), KlineStore(root)
    interval = gap.dataset.split("/", 1)[1]
    step = interval_ms(interval)
    stored = store.load(gap.symbol, interval)

    def inside(frame: pd.DataFrame | None, source: str, taken: set[int]) -> pd.DataFrame | None:
        """The closed rows strictly inside the hole that no earlier source gave, or ``None`` for none."""
        if frame is None or frame.empty:
            return None
        disagree = _disagreements(stored, frame, "open_time", _KLINE_CHECKED)
        if disagree:
            outcome.errors.append(f"{source} disagrees with {disagree} stored values; nothing taken from it")
            return None
        rows = drop_unclosed(frame, now_ms)
        rows = rows[(rows["open_time"] > gap.after) & (rows["open_time"] < gap.before)]
        rows = rows[~rows["open_time"].isin(taken)]
        return None if rows.empty else rows

    parts: list[pd.DataFrame] = []
    taken: set[int] = set()
    days = plan(gap).days
    absent = 0
    for day in days:
        try:
            served = sources.archive_day(gap.symbol, interval, day)
        except Exception as exc:
            outcome.errors.append(f"archive {day}: {type(exc).__name__}: {exc}")
            continue
        if served is None:
            absent += 1
        rows = inside(served, f"archive {day}", taken)
        if rows is not None:
            parts.append(rows)
            taken.update(int(t) for t in rows["open_time"])
    outcome.answers["archive"] = f"{len(days)} day files, {absent} absent (404), {len(taken)} bars inside"
    if len(taken) >= gap.missing:
        outcome.answers["rest"] = "not asked: the archive filled the hole"
    else:
        try:
            answer = sources.rest_klines(gap.symbol, interval, gap.after, gap.before)
        except Exception as exc:
            outcome.errors.append(f"rest: {type(exc).__name__}: {exc}")
            outcome.answers["rest"] = "failed"
        else:
            rows = inside(answer, "rest", taken)
            if rows is not None:
                parts.append(rows)
            new = 0 if rows is None else len(rows)
            outcome.answers["rest"] = (
                "not listed (-1121)" if answer is None else f"{len(answer)} rows, {new} new inside"
            )
    found = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not found.empty:
        store.append(gap.symbol, interval, found)
        outcome.added = len(found)
    remaining = [(a, b) for a, b in store.gaps(gap.symbol, interval) if a >= gap.after and b <= gap.before]
    outcome.confirmed = [Gap(gap.dataset, gap.symbol, a, b, (b - a) // step - 1) for a, b in remaining]
    return outcome


def _repair_funding(gap: Gap, root: str | Path, sources: Sources) -> Outcome:
    outcome, store = Outcome(gap), FundingStore(root)
    try:
        answer = sources.rest_funding(gap.symbol, gap.after, gap.before)
    except Exception as exc:
        outcome.errors.append(f"rest: {type(exc).__name__}: {exc}")
        outcome.answers["rest"] = "failed"
        return outcome
    outcome.answers["rest"] = "not listed (-1121)" if answer is None else f"{len(answer)} rows, 0 new inside"
    if answer is not None and not answer.empty:
        disagree = _disagreements(store.load(gap.symbol), answer, "funding_time", ("funding_rate",))
        if disagree:
            outcome.errors.append(f"rest disagrees with {disagree} stored rates; nothing taken from it")
            return outcome
        # By the hour, strictly between the two stored settlements: a second stamp inside an hour that
        # already settled would be summed into that bar by `funding_per_bar` and charge it twice.
        hours = answer["funding_time"].astype("int64") // HOUR_MS
        found = answer[(hours > gap.after // HOUR_MS) & (hours < gap.before // HOUR_MS)]
        if not found.empty:
            store.append(gap.symbol, found)
            outcome.added = len(found)
        outcome.answers["rest"] = f"{len(answer)} rows, {len(found)} new inside"
    times = store.load(gap.symbol)["funding_time"].astype("int64").to_numpy()
    remaining = [hole for hole in funding_holes(times) if hole[0] >= gap.after and hole[1] <= gap.before]
    outcome.confirmed = [Gap(FUNDING, gap.symbol, a, b, n) for a, b, n in remaining]
    return outcome


def record_confirmed(root: str | Path, outcomes: Iterable[Outcome], now_ms: int) -> tuple[Path, int]:
    """Add every confirmed part to ``confirmed_gaps.json`` (tmp then replace, as `universe.json` is written).

    Entries already there are kept as they were; the file records who was asked and when, and a later
    answer for the same hole is the same answer.  Returns the path and how many entries were new.
    """
    path = Path(root) / CONFIRMED_GAPS_FILE
    entries = read_confirmed(root)
    new = 0
    for outcome in outcomes:
        for gap in outcome.confirmed:
            if gap.key in entries:
                continue
            new += 1
            entries[gap.key] = {
                "dataset": gap.dataset,
                "symbol": gap.symbol,
                "after": gap.after,
                "before": gap.before,
                "after_utc": utc(gap.after),
                "before_utc": utc(gap.before),
                "missing": gap.missing,
                "answers": dict(outcome.answers),
                "confirmed_at": utc(now_ms),
            }
    if new:
        payload = {"kind": "confirmed-gaps", "version": 1, "gaps": [entries[key] for key in sorted(entries)]}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    return path, new
