"""DL-D2 ingestion: a store, a resumable downloader, and the gate that makes both safe.

The gate first, because without it the ingestion is the hazard rather than the feature.  Research eats
the T+1 archive; live can only read the 30-day REST window.  Ingesting the archive and letting a
signal use it would reopen KILL-027 in its purest form - a research panel strictly larger than the
live one, with nothing saying so.  So a strategy that declares `needs_metrics` refuses to start live
unless the LIVE source can answer for the bars it will trade.

The downloader reuses `archive.py`'s shape - checksum verification, 404 means "not published yet" -
because that file already learned these lessons once.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pandas as pd
import pytest

CSV = (
    "create_time,symbol,sum_open_interest,sum_open_interest_value,"
    "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
    "2026-09-05 10:15:00,BTCUSDT,107239.507,1.0,2.0,3.0,4.0,5.0\n"
    "2026-09-05 10:20:00,BTCUSDT,107239.236,1.0,2.0,3.0,4.0,5.0\n"
)


def _zip_bytes(name: str = "BTCUSDT-metrics-2026-09-05.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(name, CSV)
    return buffer.getvalue()


def _transport(payload: bytes, *, checksum: str | None = None, missing: bool = False) -> httpx.MockTransport:
    digest = checksum if checksum is not None else hashlib.sha256(payload).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if missing:
            return httpx.Response(404)
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{digest}  x.zip\n")
        return httpx.Response(200, content=payload)

    return httpx.MockTransport(handler)


# --- the store ------------------------------------------------------------------------------------


def test_the_store_round_trips_in_the_canonical_shape(tmp_path: Path) -> None:
    from starquant_data.metrics import parse_archive_csv
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path)
    # `append` returns TOTAL rows stored, the convention KlineStore and FundingStore already document.
    total = store.append("BTCUSDT", parse_archive_csv(CSV))

    assert total == 2
    frame = store.load("BTCUSDT")
    assert list(frame.columns)[:2] == ["open_time", "symbol"]
    assert frame["open_time"].is_monotonic_increasing


def test_appending_the_same_day_twice_adds_nothing(tmp_path: Path) -> None:
    """Only-appended and de-duplicated, like every other store here: a re-run is not new data."""
    from starquant_data.metrics import parse_archive_csv
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path)
    store.append("BTCUSDT", parse_archive_csv(CSV))

    assert store.append("BTCUSDT", parse_archive_csv(CSV)) == 2  # total unchanged: a re-run is not new data
    assert len(store.load("BTCUSDT")) == 2


def test_the_store_reports_where_it_got_to(tmp_path: Path) -> None:
    """Resume needs a watermark, and the watermark has to be the store's, not a side file."""
    from starquant_data.metrics import parse_archive_csv
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path)
    assert store.last_open_time("BTCUSDT") is None
    store.append("BTCUSDT", parse_archive_csv(CSV))

    assert store.last_open_time("BTCUSDT") == pd.Timestamp("2026-09-05 10:20", tz="UTC").value // 1_000_000


# --- the downloader -------------------------------------------------------------------------------


def test_a_day_is_verified_against_its_checksum(tmp_path: Path) -> None:
    from starquant_data.metrics_archive import MetricsArchiveClient

    payload = _zip_bytes()
    client = MetricsArchiveClient(transport=_transport(payload))

    frame = client.fetch_day("BTCUSDT", "2026-09-05")

    assert frame is not None and len(frame) == 2


def test_a_corrupt_download_raises_rather_than_storing(tmp_path: Path) -> None:
    """`archive.py` learned this once; a second downloader must not have to learn it again."""
    from starquant_data.archive import ChecksumMismatch
    from starquant_data.metrics_archive import MetricsArchiveClient

    client = MetricsArchiveClient(transport=_transport(_zip_bytes(), checksum="0" * 64))

    with pytest.raises(ChecksumMismatch):
        client.fetch_day("BTCUSDT", "2026-09-05")


def test_a_day_the_archive_has_not_published_is_none_not_an_error(tmp_path: Path) -> None:
    """T+1 at about 07:00 UTC: today's file is absent by design, not broken."""
    from starquant_data.metrics_archive import MetricsArchiveClient

    client = MetricsArchiveClient(transport=_transport(b"", missing=True))

    assert client.fetch_day("BTCUSDT", "2026-09-07") is None


def _full_day(day: str) -> pd.DataFrame:
    """A complete day at 5m: 288 buckets, the shape the archive actually publishes."""
    from starquant_data.metrics import parse_archive_csv

    start = pd.Timestamp(f"{day} 00:00", tz="UTC")
    header = CSV.splitlines()[0]
    rows = [
        f"{(start + pd.Timedelta(minutes=5 * i)).strftime('%Y-%m-%d %H:%M:%S')},BTCUSDT,1.0,1.0,1.0,1.0,1.0,1.0"
        for i in range(288)
    ]
    return parse_archive_csv("\n".join([header, *rows]) + "\n")


def test_sync_skips_a_day_the_store_already_covers(tmp_path: Path) -> None:
    """The watermark is the store's own last bucket - a cursor file can disagree with its data."""
    from starquant_data.metrics_archive import MetricsArchiveClient, sync_metrics
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path)
    store.append("BTCUSDT", _full_day("2026-09-05"))
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(404)

    sync_metrics(
        MetricsArchiveClient(transport=httpx.MockTransport(handler)),
        store,
        ["BTCUSDT"],
        start="2026-09-05",
        end="2026-09-07",
    )

    assert not any("2026-09-05" in path for path in asked)
    assert any("2026-09-06" in path for path in asked)


def test_a_partially_stored_day_is_fetched_again(tmp_path: Path) -> None:
    """Two rows of a day is not the day.  Skipping on 'some of it' is how a resume leaves a gap."""
    from starquant_data.metrics import parse_archive_csv
    from starquant_data.metrics_archive import MetricsArchiveClient, sync_metrics
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path)
    store.append("BTCUSDT", parse_archive_csv(CSV))  # two buckets of 2026-09-05
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(404)

    sync_metrics(
        MetricsArchiveClient(transport=httpx.MockTransport(handler)),
        store,
        ["BTCUSDT"],
        start="2026-09-05",
        end="2026-09-06",
    )

    assert any("2026-09-05" in path for path in asked)


# --- the gate that makes the ingestion safe --------------------------------------------------------


def test_a_strategy_that_needs_metrics_is_refused_when_live_has_none() -> None:
    """KILL-027, made structural rather than remembered."""
    from starquant_live.engine import metrics_refusal

    refusal = metrics_refusal(needs_metrics=["mined_x"], live_coverage_bars=0, required_bars=720)

    assert refusal is not None
    assert "mined_x" in refusal


def test_a_strategy_that_needs_metrics_is_refused_when_live_has_too_little() -> None:
    from starquant_live.engine import metrics_refusal

    refusal = metrics_refusal(needs_metrics=["mined_x"], live_coverage_bars=100, required_bars=720)

    assert refusal is not None
    assert "100" in refusal and "720" in refusal


def test_enough_live_history_starts() -> None:
    from starquant_live.engine import metrics_refusal

    assert metrics_refusal(needs_metrics=["mined_x"], live_coverage_bars=720, required_bars=720) is None


def test_a_book_that_needs_no_metrics_is_unaffected() -> None:
    """The gate must cost nothing to every strategy shipping today."""
    from starquant_live.engine import metrics_refusal

    assert metrics_refusal(needs_metrics=[], live_coverage_bars=0, required_bars=720) is None


# --- the CLI --------------------------------------------------------------------------------------


def test_the_cli_reports_what_it_stored_and_what_the_archive_had_not_published(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A sync that says nothing is a sync nobody can tell apart from a broken one."""
    from click.testing import CliRunner

    import starquant_cli.data_cmd as data_cmd
    from starquant_cli import main
    from starquant_data.metrics_archive import MetricsArchiveClient

    monkeypatch.setattr(
        data_cmd, "MetricsArchiveClient", lambda **kw: MetricsArchiveClient(transport=_transport(_zip_bytes()))
    )
    result = CliRunner().invoke(
        main,
        [
            "data",
            "metrics",
            "--root",
            str(tmp_path),
            "--symbols",
            "BTCUSDT",
            "--from",
            "2026-09-05",
            "--to",
            "2026-09-06",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "BTCUSDT" in result.output
    from starquant_data.store import MetricsStore

    assert MetricsStore(tmp_path).last_open_time("BTCUSDT") is not None
