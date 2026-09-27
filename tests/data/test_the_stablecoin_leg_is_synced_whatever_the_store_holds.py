"""#8.10's stablecoin reading needs the USDC/USDT spot series every day, whatever the kline store holds.

Until 2026-09-25 the daily `starquant data spot` synced it only because a perpetual named USDCUSDT happened to be
stored: the default run maps every perpetual the store holds, and nothing else.  `ALWAYS_MAPPED` pins the leg
into that default run.  An explicit `--symbols` is still taken as asked - the other ingest tests rely on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_cli import main
from starquant_data.binance_public import klines_to_frame
from starquant_data.spot import ALWAYS_MAPPED, SPOT_MAP_FILE
from starquant_data.store import SPOT_KLINE_KIND, KlineStore
from starquant_live.report_events import PEG_PAIR

NOW_MS = 1_756_684_800_000  # 2025-09-01T00:00Z


def _bars(n: int = 48, start_ms: int = NOW_MS - 48 * 3_600_000) -> pd.DataFrame:
    """Closed hourly klines in the shape `klines_to_frame` returns."""
    rows = [
        [t, "1.0", "1.001", "0.999", "1.0", "10", t + 3_599_999, "10", 1, "5", "5"]
        for t in (start_ms + i * 3_600_000 for i in range(n))
    ]
    return klines_to_frame(rows)


class _Archive:
    """The monthly archive with nothing in it: every month is a 404, so each leg's tail comes from REST."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __enter__(self) -> _Archive:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def fetch_month(self, symbol: str, interval: str, month: object, market: str = "futures/um") -> None:
        self.asked.append(symbol)
        return None


class _Spot:
    """`SpotClient` reduced to what the ingest calls; both legs are listed on spot."""

    def __init__(self, url: str = "") -> None:
        pass

    def __enter__(self) -> _Spot:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def server_time_ms(self) -> int:
        return NOW_MS

    def listed_symbols(self, status: str = "TRADING") -> set[str]:
        return {"BTCUSDT", "USDCUSDT"}

    def klines_range(self, symbol: str, interval: str, start_ms: int | None = None, end_ms: int | None = None):
        return _bars()


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> tuple[_Archive, str]:
    KlineStore(tmp_path).append("BTCUSDT", "1h", _bars())  # the store holds BTC only, no USDCUSDT perpetual
    archive = _Archive()
    monkeypatch.setattr("starquant_cli.data_cmd.ArchiveClient", lambda *a, **k: archive)
    monkeypatch.setattr("starquant_cli.data_cmd.SpotClient", _Spot)
    monkeypatch.setattr("starquant_cli.data_cmd._record_spot_contract", lambda *a, **k: None)
    result = CliRunner().invoke(main, ["data", "spot", "--root", str(tmp_path), "--start", "2025-08", *extra])
    assert result.exit_code == 0, result.output
    return archive, result.output


def test_the_peg_the_reading_uses_is_one_of_the_pinned_legs() -> None:
    assert PEG_PAIR in ALWAYS_MAPPED


def test_the_daily_run_maps_and_syncs_the_peg_without_its_perpetual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, output = _run(tmp_path, monkeypatch)
    assert "USDCUSDT" in archive.asked, output
    mapped = json.loads((tmp_path / SPOT_MAP_FILE).read_text(encoding="utf-8"))
    assert "USDCUSDT" in json.dumps(mapped)
    assert KlineStore(tmp_path, kind=SPOT_KLINE_KIND).exists("USDCUSDT", "1h")


def test_an_explicit_symbols_run_is_taken_as_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive, output = _run(tmp_path, monkeypatch, "--symbols", "BTCUSDT")
    assert "USDCUSDT" not in archive.asked, output


def test_an_empty_store_still_has_nothing_to_map(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["data", "spot", "--root", str(tmp_path)])
    assert result.exit_code != 0 and "no perpetuals to map" in result.output
