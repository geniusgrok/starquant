"""Daily metrics archive downloader, with resume and checksum verification (DL-D2 / DL-Q6).

Deliberately shaped like ``archive.py``: verify the zip against its published checksum, treat 404 as
"not published yet" rather than as an error, and let the STORE be the watermark so a resume needs no
side file to go stale.  That module learned these three things once; a second downloader should not
have to learn them again.

The publication schedule, measured 2026-09-07: a day's file appears at about T+1 06:45-07:00 UTC
(three consecutive days landed at 06:58, 06:52 and 06:43).  So "today" and usually "yesterday morning"
are legitimately absent, and a sync that treated absence as failure would be red every morning.

Every frame leaves here in the canonical shape of ``starquant_data.metrics`` - ``open_time``, never
``create_time`` - because the whole point of that module is that the conversion happens exactly once.
"""

from __future__ import annotations

import io
import time
import zipfile
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd

from starquant_data.archive import parse_checksum, verify_zip
from starquant_data.metrics import parse_archive_csv
from starquant_data.store import MetricsStore

BASE_URL = "https://data.binance.vision"
METRICS_PERIOD_MS = 300_000  # the daily archive is published at 5m granularity
_RETRIES = 4  # 1s, 2s, 4s between attempts; the CDN throttles by concurrency, so backing off works


def metrics_path(symbol: str, day: str) -> str:
    return f"/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip"


def days_between(start: str, end_exclusive: str) -> list[str]:
    first = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
    last = datetime.strptime(end_exclusive, "%Y-%m-%d").replace(tzinfo=UTC)
    out: list[str] = []
    while first < last:
        out.append(first.strftime("%Y-%m-%d"))
        first += timedelta(days=1)
    return out


class MetricsArchiveClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        backoff: float = 1.0,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport, follow_redirects=True)
        # A seam, not a knob - the one `onchain.CommunityClient` already carries, for the same reason.
        # Two tests here exercise the 5xx path and really slept 1+2+4s each - 14.0s, the same on both
        # boxes, because a sleep is the one cost that never shrinks on faster hardware.  That is why
        # `suite_duration.py` names it as the step change its ceiling exists to catch.  Tests pass 0.
        self._backoff = backoff

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MetricsArchiveClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str) -> httpx.Response:
        """One request, retried on a 5xx.

        Measured 2026-09-09, and worth recording because it contradicted the assumption it replaced:
        the operator had retired the local proxy that used to answer 503 in bursts, so a 503 should not
        have been possible - and 16 concurrent symbols produced one anyway, from the CDN, while 8 ran
        clean.  So this is the archive throttling, not a local artefact, and it is concurrency
        dependent rather than random.

        A 404 is NOT retried: the archive genuinely has no file for a day it has not published, and
        that is the normal case every morning (a day appears at about T+1 06:45-07:00 UTC).
        """
        delay = self._backoff
        for attempt in range(_RETRIES):
            response = self._client.get(path)
            if response.status_code < 500 or attempt == _RETRIES - 1:
                return response
            if delay:
                time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    def fetch_day(self, symbol: str, day: str) -> pd.DataFrame | None:
        """One verified day in the canonical shape, or ``None`` when the archive has no file (404)."""
        path = metrics_path(symbol, day)
        response = self._get(path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        checksum = self._get(path + ".CHECKSUM")
        checksum.raise_for_status()
        verify_zip(response.content, parse_checksum(checksum.text))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8")
        return parse_archive_csv(text)


def _fetch_symbol(
    client: MetricsArchiveClient, store: MetricsStore, symbol: str, days: Sequence[str]
) -> tuple[str, pd.DataFrame | None]:
    """Every day this symbol still owes, fetched and returned as ONE frame.

    One frame, not one append per day, and that is the whole of this function's reason to exist.
    ``MetricsStore.append`` reads the symbol's entire parquet, concatenates, dedupes, sorts and writes
    it back; calling it per day makes the ingest quadratic in days - day k rewrites k x 288 rows, so a
    2,077-day symbol writes about 621 million rows to store 598 thousand.  A ten-day probe cannot see
    that term at all, which is exactly how the estimate that preceded this function came to be wrong.
    """
    watermark = store.last_open_time(symbol)
    frames: list[pd.DataFrame] = []
    for day in days:
        day_end_ms = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000) + 86_400_000
        if watermark is not None and day_end_ms <= watermark + METRICS_PERIOD_MS:
            continue
        frame = client.fetch_day(symbol, day)
        if frame is not None and not frame.empty:
            frames.append(frame)
    return symbol, pd.concat(frames, ignore_index=True) if frames else None


def sync_metrics(
    client: MetricsArchiveClient,
    store: MetricsStore,
    symbols: Sequence[str],
    *,
    start: str,
    end: str,
    workers: int = 1,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, int]:
    """Fetch every published day in ``[start, end)`` that the store does not already hold.

    The watermark is the store's own ``last_open_time``, not a cursor file: a cursor can disagree with
    the data it claims to describe, and then a resume silently skips a gap.  Days already covered are
    not requested at all - which is what makes a nightly re-run cheap rather than a full re-download.

    ``workers`` fetches several SYMBOLS at once.  By symbol rather than by day for two reasons that
    both matter: a symbol's days must be gathered before its single append, and every write then
    happens on this thread, in the loop below, so two workers can never touch one parquet.  Measured
    per symbol-day: 0.06s of CPU against 0.58s of waiting, so this is the axis with the headroom.

    Default 1, because a function that silently became concurrent would change what every existing
    caller does; the CLI opts in.
    """
    days = days_between(start, end)
    stored: dict[str, int] = {}
    failures: dict[str, str] = {}
    done = 0
    total = len(symbols)

    def record(symbol: str, frame: pd.DataFrame | None) -> None:
        nonlocal done
        done += 1
        if frame is not None:
            stored[symbol] = store.append(symbol, frame)
        if progress is not None:
            progress(symbol, done, total)

    def isolate(symbol: str, produce: Callable[[], tuple[str, pd.DataFrame | None]]) -> None:
        """One symbol's failure is reported and skipped, never raised.

        The store is the watermark, so a re-run picks this symbol up exactly where it stopped; ending
        the whole run instead throws away every OTHER symbol's work, which is the expensive half of a
        six-hour job.  Applied to BOTH paths on purpose - the first version isolated only the
        concurrent one, so the same function ended a run or did not depending on `workers`.
        """
        try:
            record(*produce())
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}: {exc}"
            if progress is not None:
                progress(f"{symbol} FAILED ({type(exc).__name__})", len(stored) + len(failures), total)

    if workers <= 1:
        for symbol in symbols:
            isolate(symbol, lambda symbol=symbol: _fetch_symbol(client, store, symbol, days))  # type: ignore[misc]
        return stored

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_symbol, client, store, symbol, days): symbol for symbol in symbols}
        for future in as_completed(futures):
            isolate(futures[future], future.result)
    return stored
