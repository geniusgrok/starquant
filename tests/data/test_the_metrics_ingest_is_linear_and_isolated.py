"""The two properties a six-hour ingest needs, and the measurement that produced both.

The first estimate for this job said 7.1 hours.  It was wrong twice over, and both errors are the kind
a small probe hides:

* it assumed 10 requests a second from the file size, when the path is latency bound - measured 0.06s
  of CPU against 0.58s of waiting per symbol-day, so 1.6/s;
* it was measured on a ten-day store, where `MetricsStore.append` is cheap.  That function reads the
  symbol's whole parquet, concatenates, sorts and writes it back, and `sync_metrics` called it ONCE
  PER DAY - so day k rewrote k x 288 rows and a 2,077-day symbol wrote about 621 million rows to store
  598 thousand.  Quadratic, and invisible at ten days.

So: gather a symbol's days and append once, and fetch several symbols at a time.  Both are asserted
here rather than trusted, because both are the sort of thing a later refactor tidies back.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import httpx
import pandas as pd
import pytest

from starquant_data.metrics_archive import MetricsArchiveClient, sync_metrics
from starquant_data.store import MetricsStore

DAY = "2024-01-01"


def _zip_for(symbol: str, day: str) -> bytes:
    rows = [f"{day} {hour:02d}:00:00,{symbol},100.0,200.0,1.0,1.1,1.2,1.3" for hour in range(3)]
    header = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{symbol}-metrics-{day}.csv", "\n".join([header, *rows]))
    return buffer.getvalue()


class _Recorder(httpx.BaseTransport):
    """Serves the archive, counts requests, and can be told to fail one symbol."""

    def __init__(self, *, fail: str = "", status: int = 500) -> None:
        self.requests: list[str] = []
        self._fail, self._status, self.attempts = fail, status, 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        symbol = path.split("/")[-2]
        if self._fail and symbol == self._fail:
            self.attempts += 1
            return httpx.Response(self._status, request=request)
        day = path.split("-metrics-")[1].removesuffix(".CHECKSUM").removesuffix(".zip")
        payload = _zip_for(symbol, day)
        if path.endswith(".CHECKSUM"):
            import hashlib

            return httpx.Response(200, text=f"{hashlib.sha256(payload).hexdigest()}  x.zip", request=request)
        return httpx.Response(200, content=payload, request=request)


def _client(transport: httpx.BaseTransport) -> MetricsArchiveClient:
    # backoff=0.0 so the 5xx tests below do not really sleep 1+2+4 seconds each.  The production
    # schedule is not lost with it: `test_the_retry_schedule_is_the_one_the_cdn_needs` pins it.
    return MetricsArchiveClient(transport=transport, backoff=0.0)


def test_a_symbols_days_are_appended_once_not_once_per_day(tmp_path: Path, monkeypatch) -> None:
    """The quadratic term, pinned.  One append per symbol, however many days it covers."""
    store = MetricsStore(tmp_path)
    appends: list[str] = []
    original = MetricsStore.append

    def counted(self, symbol: str, frame: pd.DataFrame) -> int:
        appends.append(symbol)
        return original(self, symbol, frame)

    monkeypatch.setattr(MetricsStore, "append", counted)
    with _client(_Recorder()) as client:
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-11")
    assert appends == ["AAAUSDT"], f"10 days must cost one append, got {len(appends)}"
    assert len(store.load("AAAUSDT")) == 30


def test_one_symbols_failure_does_not_end_the_run(tmp_path: Path) -> None:
    """The expensive half of a six-hour job is every OTHER symbol still in flight."""
    store = MetricsStore(tmp_path)
    transport = _Recorder(fail="BADUSDT", status=500)
    with _client(transport) as client:
        stored = sync_metrics(
            client, store, ["AAAUSDT", "BADUSDT", "CCCUSDT"], start="2024-01-01", end="2024-01-02", workers=3
        )
    assert set(stored) == {"AAAUSDT", "CCCUSDT"}
    assert store.load("BADUSDT").empty


def test_a_5xx_is_retried_and_a_404_is_not(tmp_path: Path) -> None:
    """A 404 is the normal case every morning: the day is simply not published yet."""
    store = MetricsStore(tmp_path)
    throttled = _Recorder(fail="AAAUSDT", status=503)
    with _client(throttled) as client:
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-02")
    assert throttled.attempts == 4, "a 503 must be retried with backoff"

    absent = _Recorder(fail="AAAUSDT", status=404)
    with _client(absent) as client:
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-02")
    assert absent.attempts == 1, "a 404 must not be retried"


def test_the_retry_schedule_is_the_one_the_cdn_needs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """What `backoff=0.0` costs the suite in coverage, bought back without the 7 seconds.

    The seam exists so the tests above run instantly; this one is the reason it is a seam and not a
    lowered default.  Against a CDN that throttles by concurrency, retrying three times in a row with
    no pause is not a retry - it is the same burst again - so the waits themselves are the behaviour.
    """
    slept: list[float] = []
    monkeypatch.setattr("starquant_data.metrics_archive.time.sleep", slept.append)
    store = MetricsStore(tmp_path)
    transport = _Recorder(fail="AAAUSDT", status=503)
    with MetricsArchiveClient(transport=transport, backoff=1.0) as client:  # the shipped default
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-02")
    assert slept == [1.0, 2.0, 4.0], f"four attempts, doubling between them, got {slept}"


def test_the_watermark_is_the_store_so_a_resume_asks_for_nothing_it_holds(tmp_path: Path) -> None:
    store = MetricsStore(tmp_path)
    first = _Recorder()
    with _client(first) as client:
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-04")
    again = _Recorder()
    with _client(again) as client:
        sync_metrics(client, store, ["AAAUSDT"], start="2024-01-01", end="2024-01-04")
    # Only the LAST day is asked for again, and that is correct rather than wasteful: this fixture
    # writes three buckets a day, so the watermark sits inside that day and its coverage really is
    # incomplete.  Against the real archive (288 buckets ending 23:55) the day is skipped outright.
    assert len({r for r in again.requests if "01-01" in r or "01-02" in r}) == 0
    assert len(first.requests) == 6 and len(again.requests) == 2


@pytest.mark.parametrize("workers", [1, 4])
def test_the_result_does_not_depend_on_how_many_workers_fetched_it(tmp_path: Path, workers: int) -> None:
    store = MetricsStore(tmp_path / str(workers))
    with _client(_Recorder()) as client:
        sync_metrics(client, store, ["AAAUSDT", "BBBUSDT"], start="2024-01-01", end="2024-01-04", workers=workers)
    for symbol in ("AAAUSDT", "BBBUSDT"):
        frame = store.load(symbol)
        assert len(frame) == 9
        assert frame["open_time"].is_monotonic_increasing
