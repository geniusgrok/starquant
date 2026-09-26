"""`pool history`: a daily table by default, a warning before it starts, and no half-written table (2026-09-23).

Three findings from G10 (#120), fixed together because they meet in one command:

- The default was `--refresh MS`, a monthly table.  Research adopted the daily one on 2026-09-04, and the
  hourly `pool lag --check` flags a monthly table as not daily.  A default the system itself calls wrong
  is a trap, so the default is now `D`.
- A rebuild moves the manifest's blocking `membership` field, and the armed start is then refused until
  the evidence is re-issued on the new table.  The command now says so before its long sync starts.
- The table was written in place, so the hourly check could read half of one.  It now goes through
  `write_parquet_atomically`, the store's one standard: a rebuild that dies midway leaves the old table.

The venue, the archive listing and the daily volumes are stubbed; `point_in_time_membership` is real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner, Result

from starquant_cli import data_cmd, main

ROOT = Path(__file__).resolve().parents[2]
REAL_TABLE = ROOT / "tests" / "fixtures" / "pit_membership_2026_09_17" / "membership.parquet"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


class _Public:
    def __init__(self, url: str) -> None:
        self.url = url

    def __enter__(self) -> _Public:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def server_time_ms(self) -> int:
        return 1_790_000_000_000

    def exchange_info(self) -> dict[str, Any]:
        return {}


class _Archive:
    def __enter__(self) -> _Archive:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def list_symbols(self) -> list[str]:
        return list(SYMBOLS)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    days = pd.date_range("2026-03-01", "2026-06-30", freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    volume = pd.DataFrame(rng.uniform(1e8, 1e9, size=(len(days), len(SYMBOLS))), index=days, columns=SYMBOLS)
    monkeypatch.setattr(data_cmd, "PublicClient", _Public)
    monkeypatch.setattr(data_cmd, "ArchiveClient", _Archive)
    monkeypatch.setattr(data_cmd, "parse_exchange_info", lambda _info: {})
    monkeypatch.setattr(data_cmd, "daily_quote_volume", lambda _store, _symbols: volume)


def _history(root: Path, *args: str) -> Result:
    return CliRunner().invoke(main, ["data", "pool", "history", "--root", str(root), "--no-sync", *args])


def test_the_default_rebuild_is_the_daily_table(tmp_path: Path) -> None:
    result = _history(tmp_path)
    assert result.exit_code == 0, result.output
    table = pd.read_parquet(tmp_path / "membership.parquet")
    assert isinstance(table.index, pd.DatetimeIndex)  # the dates survive the atomic write
    assert table.index.to_series().diff().dropna().median() == pd.Timedelta(days=1)
    assert not list(tmp_path.glob("*.tmp"))


def test_monthly_is_still_there_when_asked_for(tmp_path: Path) -> None:
    result = _history(tmp_path, "--refresh", "MS")
    assert result.exit_code == 0, result.output
    table = pd.read_parquet(tmp_path / "membership.parquet")
    assert table.index.to_series().diff().dropna().median() >= pd.Timedelta(days=28)  # `pool lag`'s own test


def test_the_gate_warning_comes_before_the_work(tmp_path: Path) -> None:
    result = _history(tmp_path)
    first = result.output.splitlines()[0]
    assert first.startswith("注意：") and "armed 启动随即被数据集门挡住" in first
    assert "registry_dataset_problems" in first and "要和证据重出排在一起" in first


def test_a_rebuild_that_dies_midway_leaves_the_old_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure the hourly check used to be able to catch: a table cut off halfway through its write."""
    old = REAL_TABLE.read_bytes()
    (tmp_path / "membership.parquet").write_bytes(old)
    original = pd.DataFrame.to_parquet

    def dies_halfway(self: pd.DataFrame, path: Any, *args: Any, **kwargs: Any) -> None:
        original(self, path, *args, **kwargs)
        written = Path(path).read_bytes()
        Path(path).write_bytes(written[: len(written) // 2])
        raise OSError("disk went away")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", dies_halfway)
    result = _history(tmp_path)
    assert result.exit_code != 0
    assert (tmp_path / "membership.parquet").read_bytes() == old
