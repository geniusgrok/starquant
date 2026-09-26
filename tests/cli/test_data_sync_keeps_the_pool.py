"""`data sync` stores bars for every name in the pool, not only for the 24h top 2N (2026-09-23).

The pool ranks 30-day volume with hysteresis; the sync list ranked 24h volume and nothing else.  A member
can sit below that cut for weeks.  LSKUSDT did: its bars stopped at 2026-09-18T16:00Z while the loop still
held it in its pool, and CYSUSDT and TUTUSDT lost twelve days before they left on 09-16.  All three fell
out of `report beta`'s basket and M-Q08's turnover replay.  `LivePool.select` keeps `previous` among its
candidates for this reason; the sync now keeps the pool too, plus the names its last refresh dropped.

`universe.json` is written here by the loop's own sink (`universe_sink`), so the test reads the file the
loop writes rather than a shape invented for it.  Downloads and the venue are stubbed; the list of
symbols handed to `sync_klines` is what is asserted.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner, Result

from starquant_cli import data_cmd, main
from starquant_data.pool import UniverseUpdate
from starquant_live.config import universe_sink

# 24h quote volume, highest first.  `--candidates 3` cuts after SOLUSDT.
VOLUMES = {"BTCUSDT": 9e9, "ETHUSDT": 8e9, "SOLUSDT": 7e9, "XRPUSDT": 6e9, "LSKUSDT": 1e6, "CYSUSDT": 5e5}


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

    def ticker_24h(self) -> list[dict[str, Any]]:
        return [{"symbol": symbol, "quoteVolume": volume} for symbol, volume in VOLUMES.items()]


class _Archive:
    def __enter__(self) -> _Archive:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def sync_klines(symbol: str, *_: Any, **__: Any) -> SimpleNamespace:
        seen.append(symbol)
        return SimpleNamespace(total_rows=0, archive_months=0, rest_rows=0, funding_rows=0, errors=[])

    monkeypatch.setattr(data_cmd, "PublicClient", _Public)
    monkeypatch.setattr(data_cmd, "ArchiveClient", _Archive)
    monkeypatch.setattr(data_cmd, "parse_exchange_info", lambda _info: {})
    monkeypatch.setattr(data_cmd, "eligible_symbols", lambda _rules, _config: list(VOLUMES))
    monkeypatch.setattr(data_cmd, "sync_klines", sync_klines)
    return seen


def _pool(root: Path, symbols: list[str], left: list[str]) -> None:
    universe_sink(root)(UniverseUpdate(symbols=tuple(symbols), entered=(), left=tuple(left), at_ms=1))


def _sync(root: Path, *args: str) -> Result:
    result = CliRunner().invoke(main, ["data", "sync", "--root", str(root), "--no-funding", "--candidates", "3", *args])
    assert result.exit_code == 0, result.output
    return result


def test_a_pool_member_below_the_24h_cut_is_still_synced(tmp_path: Path, synced: list[str]) -> None:
    _pool(tmp_path, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LSKUSDT"], left=[])
    result = _sync(tmp_path)
    assert "LSKUSDT" in synced
    assert "pool names outside the 24h top 3: LSKUSDT" in result.output  # the log says why it is there


def test_the_names_the_last_refresh_dropped_ride_along(tmp_path: Path, synced: list[str]) -> None:
    """The day a name leaves, the loop is closing it.  Those bars belong in the replay too."""
    _pool(tmp_path, ["BTCUSDT", "ETHUSDT", "SOLUSDT"], left=["CYSUSDT"])
    _sync(tmp_path)
    assert "CYSUSDT" in synced


def test_the_ranking_still_decides_the_rest(tmp_path: Path, synced: list[str]) -> None:
    _pool(tmp_path, ["BTCUSDT", "ETHUSDT", "LSKUSDT"], left=[])
    _sync(tmp_path)
    assert sorted(synced) == ["BTCUSDT", "ETHUSDT", "LSKUSDT", "SOLUSDT"]  # pins, pool, top 3; XRP and CYS not
    assert len(synced) == len(set(synced))  # a name in two lists is fetched once


def test_without_a_pool_file_the_list_is_the_ranking_it_always_was(tmp_path: Path, synced: list[str]) -> None:
    _sync(tmp_path)
    assert synced == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_an_explicit_symbol_list_stays_exact(tmp_path: Path, synced: list[str]) -> None:
    _pool(tmp_path, ["BTCUSDT", "LSKUSDT"], left=["CYSUSDT"])
    _sync(tmp_path, "--symbols", "xrpusdt")
    assert synced == ["XRPUSDT"]


def test_an_unreadable_pool_file_warns_and_still_syncs_the_ranking(tmp_path: Path, synced: list[str]) -> None:
    """`pool refresh` reads the same file next in `run_data.sh` and fails loudly; this step must not."""
    (tmp_path / "universe.json").write_text("{half", encoding="utf-8")
    result = _sync(tmp_path)
    assert "universe.json unreadable, pool names not added" in result.output
    assert synced == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
