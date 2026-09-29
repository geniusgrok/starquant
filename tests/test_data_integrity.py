"""Source archive completeness and actual funding settlement times."""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import numpy as np
import pytest

from btc_perp import tapes
from scripts import assets


def _archive(path: Path, stamps: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = b"".join(f"{t},100,100,100,100,0,0,1\n".encode() for t in stamps)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("data.csv", rows)


def test_missing_source_month_is_not_filled_by_neighbouring_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assets, "DATA", tmp_path)
    asset = assets.Asset("test", "spot", "X", (2020, 1), (2020, 2), False)
    folder = tmp_path / "assets" / "test" / "klines"
    start = int(dt.datetime(2020, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)
    _archive(folder / "X-1m-2020-01.zip", np.arange(start, start + 31 * 1440 * 60_000, 60_000))
    with pytest.raises(FileNotFoundError, match="X-1m-2020-02"):
        assets.build(asset)
    assert not (tmp_path / "assets" / "test_1m.npz").exists()


def test_asset_command_fails_when_a_source_gap_remains(monkeypatch: pytest.MonkeyPatch) -> None:
    one = assets.Asset("test", "spot", "X", (2020, 1), (2020, 1), False)
    monkeypatch.setattr(assets, "ASSETS", {"test": one})
    monkeypatch.setattr(assets, "download", lambda asset: {"requested": 1, "present": 1})
    monkeypatch.setattr(assets, "build", lambda asset: {"asset": asset.name, "ok": False})
    assert assets.main() == 2


def test_daily_source_repairs_missing_month_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets, "DATA", tmp_path)
    asset = assets.Asset("test", "spot", "X", (2020, 1), (2020, 1), False)
    folder = tmp_path / "assets" / "test" / "klines"
    start = int(dt.datetime(2020, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)
    all_minutes = np.arange(start, start + 31 * 1440 * 60_000, 60_000)
    absent = (all_minutes >= start + 4 * 1440 * 60_000) & (all_minutes < start + 5 * 1440 * 60_000)
    _archive(folder / "X-1m-2020-01.zip", all_minutes[~absent])
    _archive(folder / "X-1m-2020-01-05.zip", all_minutes[absent])
    result = assets.build(asset)
    assert result["ok"] is True
    assert result["daily_backfill_archives"] == 1
    assert result["filled_minutes"] == 0
    with np.load(tmp_path / "assets" / "test_1m.npz") as data:
        assert len(data["ts"]) == len(all_minutes)
        assert np.all(data["present"])


def test_every_actual_funding_hour_counts_and_official_slots_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "assets"
    path.mkdir()
    begin = int(dt.datetime(2022, 11, 10, tzinfo=dt.UTC).timestamp() * 1000)
    ts = np.arange(begin, begin + 1440 * 60_000, 60_000)
    np.savez(
        path / "sol_1m.npz",
        ts=ts,
        o=ts * 0 + 100,
        h=ts * 0 + 100,
        l=ts * 0 + 100,
        c=ts * 0 + 100,
        qv=ts * 0 + 1,
        present=np.ones(len(ts), dtype=bool),
    )
    monkeypatch.setattr(tapes, "DATA", tmp_path)
    monkeypatch.setattr(tapes, "_fx", lambda hours, use_real: np.ones(len(hours)))
    stamps = begin + np.array([0, 2, 4, 6, 8, 16], dtype=np.int64) * 3_600_000 + 11
    rates = np.array([0.001, -0.02, -0.03, -0.04, -0.05, -0.06])
    np.savez(path / "sol_funding.npz", ts=stamps, rate=rates)
    tape = tapes.load_tape("sol")
    np.testing.assert_allclose(tape.fund[np.array([0, 2, 4, 6, 8, 16]) * 60], rates)
    assert np.count_nonzero(tape.fund) == len(rates)
    other = stamps != begin + 8 * 3_600_000 + 11
    np.savez(path / "sol_funding.npz", ts=stamps[other], rate=rates[other])
    with pytest.raises(ValueError, match="8 小时资金费缺失"):
        tapes.load_tape("sol")


def test_more_than_one_day_of_filled_minutes_invalidates_research_tape() -> None:
    ts = np.arange(3000, dtype=np.int64) * 60_000
    values = np.ones(len(ts))
    present = np.ones(len(ts), dtype=bool)
    present[100:1541] = False
    tape = tapes.Tape(
        "btc_spot_2017", ts, values, values, values, values, values, values, values, values, present=present
    )
    assert any("连续缺失超过 24 小时" in problem for problem in tapes.validate_tape(tape))
