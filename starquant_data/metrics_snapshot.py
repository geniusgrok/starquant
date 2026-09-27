"""The loop's own metrics recording: one truth for research and live (DL-Q6 / KILL-Q11).

KILL-Q11's finding is that research and live read *different sources* - the T+1 daily archive and the
30-day REST window - so a metrics signal validated on one and traded on the other has never been
tested on what it will actually see.  The archive/REST stamp offset showed how quietly that goes
wrong: the same numbers under two conventions, and a five-minute look-ahead in every bucket.

The answer is not a second copy of the data, it is a recording of *what the loop could read*.  The
loop polls the REST window each cycle and appends the buckets to its own store; that store is the
common truth, and the archive becomes something to CHECK it against rather than something to trade on.

**No separate five-minute daemon**, and the reasoning matters more than the code.  The granularity
that matters belongs to the BUCKET (5m), not to the poll: the REST window is 30 days deep, so one
poll an hour retrieves all twelve buckets of the past hour with nothing missed.  Polling at the bar
close also does something a 5m daemon cannot - it records exactly the buckets that had CLOSED when the
loop made its decision, which is precisely the set `align_to_bars` selects.  A daemon would be a
second process, a second failure mode and a second thing to restart, in exchange for a superset of the
same rows recorded at instants no decision was made at.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import pandas as pd

from starquant_data.metrics import REST_SOURCES, parse_rest_rows, period_ms
from starquant_data.store import MetricsStore

#: Kept so anything naming the open-interest page by hand still resolves; the poll uses `REST_SOURCES`.
METRICS_PATH = REST_SOURCES[0][0]


class _Getter(Protocol):
    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any: ...


async def snapshot_metrics(
    client: _Getter,
    store: MetricsStore,
    symbols: Sequence[str],
    *,
    period: str = "5m",
    limit: int = 12,
    concurrency: int = 6,
) -> dict[str, Any]:
    """Record the metrics buckets this loop could read, symbol by symbol.

    Best-effort by contract, like every other instrument in the cycle: collecting data may never be
    the reason a book stops trading, so a failure is returned in the result rather than raised.
    """
    step = period_ms(period)
    stored: dict[str, int] = {}
    missing: dict[str, list[str]] = {}
    # Five endpoints x eighteen symbols is ninety requests, and serially that measured 28.6s against a
    # cycle that takes about twenty - which would push every rebalance a half-minute later and move
    # M-Q08's own reference (adverse fill vs the DECISION CLOSE) by that much.  Bounded rather than
    # unbounded: this runs beside the loop's own market-data fetches on a proxy path that intermittently
    # 503s, and a burst of ninety is how a shared route starts refusing the requests that matter.
    gate = asyncio.Semaphore(concurrency)

    async def one(symbol: str) -> tuple[str, pd.DataFrame | None, list[str]]:
        frame: pd.DataFrame | None = None
        absent: list[str] = []
        for path, mapping in REST_SOURCES:
            async with gate:
                rows = await client.get(path, {"symbol": symbol, "period": period, "limit": int(limit)})
            if not rows:
                # Recorded per endpoint rather than folded into the row count: an endpoint that stops
                # answering leaves its columns NaN, and NaN in this store is exactly what
                # `metrics_parity` cannot see (it skips NaN pairs and calls that agreement).
                absent.append(path.rsplit("/", 1)[-1])
                continue
            page = parse_rest_rows(rows, step, mapping, symbol=symbol)
            frame = page if frame is None else _merge(frame, page, mapping.values())
        return symbol, frame, absent

    try:
        for symbol, frame, absent in await asyncio.gather(*(one(symbol) for symbol in symbols)):
            if absent:
                missing[symbol] = absent
            if frame is not None:
                # The store is read-modify-write per symbol, so the writes stay serial here even though
                # the fetches did not (DL-Q6: two writers can publish a file one was still writing).
                stored[symbol] = store.append(symbol, frame)
    except Exception as exc:
        return {"stored": stored, "missing": missing, "error": f"{type(exc).__name__}: {exc}"}
    return {"stored": stored, **({"missing": missing} if missing else {})}


def _merge(frame: pd.DataFrame, page: pd.DataFrame, columns: Any) -> pd.DataFrame:
    """Fold one endpoint's columns onto the bucket rows already collected for this symbol.

    Aligned on ``open_time``, which every page carries after `parse_rest_rows` converts the stamp -
    so an endpoint whose window is one bucket short contributes what it has and leaves the rest NaN,
    rather than shifting its values onto the wrong buckets.
    """
    indexed = page.set_index("open_time")
    out = frame.set_index("open_time")
    for column in columns:
        if column in indexed:
            out[column] = indexed[column].reindex(out.index)
    return out.reset_index()


def metrics_parity(snapshot: pd.DataFrame, archive: pd.DataFrame, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """M-011: do the two sources agree on the buckets they share?

    The rate is ``None`` rather than 1.0 when nothing overlaps.  Zero disagreements out of zero
    comparisons is not agreement - reporting it as perfect is how a dead snapshot stream would look
    healthiest exactly while it stopped recording.
    """
    if snapshot.empty or archive.empty:
        return {"overlapping": 0, "differing": 0, "rate": None}
    columns = [c for c in snapshot.columns if c in archive.columns and c not in ("open_time", "symbol")]
    merged = snapshot.merge(archive, on="open_time", suffixes=("_snap", "_arch"))
    if merged.empty or not columns:
        return {"overlapping": 0, "differing": 0, "rate": None}
    differing = pd.Series(False, index=merged.index)
    for column in columns:
        left, right = merged[f"{column}_snap"], merged[f"{column}_arch"]
        differing |= ~((left - right).abs() <= tolerance) & left.notna() & right.notna()
    count = int(differing.sum())
    return {"overlapping": len(merged), "differing": count, "rate": count / len(merged)}


def live_coverage_bars(store: MetricsStore, symbols: Sequence[str], *, interval_ms: int, period: str = "5m") -> int:
    """How many whole BARS the live snapshot can answer for, across the whole universe.

    Counted in bars because that is the unit a strategy's warmup is in, and taken as the THINNEST
    symbol because a book trades a universe: coverage the whole universe does not have is not
    coverage, it is coverage of a different book.

    Counted from the number of buckets actually held, not from first-to-last span.  A span treats a
    gap - the loop was down for a day - as covered, and for a GATE that is the wrong direction to be
    wrong in: it would admit a strategy onto data with holes.  Counting buckets under-reports across a
    gap instead, which delays a promotion rather than allowing a bad one.
    """
    if not symbols:
        return 0
    step = period_ms(period)
    counts: list[int] = []
    for symbol in symbols:
        frame = store.load(symbol)
        if frame.empty:
            return 0
        counts.append(len(frame))
    return int(min(counts) * step // int(interval_ms))
