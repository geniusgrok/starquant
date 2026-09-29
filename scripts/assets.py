"""Other tapes for out-of-sample checks: ETHUSDT, SOLUSDT, and BTC spot before 2020.

Files come from data.binance.vision and go under ``data/``, which is not in the
repository. The spot tape has no perpetual funding, so its funding is zero and
the report says so. Missing minutes within complete source archives are filled
from the previous close and counted; a missing archive cannot be filled.
"""

from __future__ import annotations

import datetime as dt
import io
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from btc_perp.config import ROOT

BASE = "https://data.binance.vision/data"
DATA = ROOT / "data"
MINUTE = 60_000
HOUR = 3_600_000


@dataclass(frozen=True)
class Asset:
    name: str
    market: str
    symbol: str
    first: tuple[int, int]
    last: tuple[int, int]
    funding: bool
    daily_tail: tuple[int, int, int] | None = None


ASSETS = {
    "eth": Asset("eth", "futures/um", "ETHUSDT", (2020, 1), (2026, 8), True, (2026, 9, 19)),
    "sol": Asset("sol", "futures/um", "SOLUSDT", (2020, 10), (2026, 8), True, (2026, 9, 19)),
    "btc_spot_2017": Asset("btc_spot_2017", "spot", "BTCUSDT", (2017, 9), (2019, 12), False),
}


def _months(first: tuple[int, int], last: tuple[int, int]) -> list[str]:
    out = []
    year, month = first
    while (year, month) <= last:
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _get(url: str, retries: int = 4) -> bytes | None:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as handle:
                return bytes(handle.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            time.sleep(2 * (attempt + 1))
        except (OSError, TimeoutError):
            time.sleep(2 * (attempt + 1))
    return None


def _fetch(url: str, path: Path) -> bool:
    if path.exists() and path.stat().st_size > 0:
        return True
    body = _get(url)
    if body is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return True


def _jobs(asset: Asset) -> list[tuple[str, Path]]:
    kline_dir = DATA / "assets" / asset.name / "klines"
    fund_dir = DATA / "assets" / asset.name / "funding"
    jobs: list[tuple[str, Path]] = []
    for month in _months(asset.first, asset.last):
        name = f"{asset.symbol}-1m-{month}.zip"
        jobs.append((f"{BASE}/{asset.market}/monthly/klines/{asset.symbol}/1m/{name}", kline_dir / name))
        if asset.funding:
            fname = f"{asset.symbol}-fundingRate-{month}.zip"
            jobs.append((f"{BASE}/{asset.market}/monthly/fundingRate/{asset.symbol}/{fname}", fund_dir / fname))
    if asset.daily_tail is not None:
        year, tail_month, last_day = asset.daily_tail
        for day in range(1, last_day + 1):
            name = f"{asset.symbol}-1m-{year:04d}-{tail_month:02d}-{day:02d}.zip"
            jobs.append((f"{BASE}/{asset.market}/daily/klines/{asset.symbol}/1m/{name}", kline_dir / name))
    return jobs


def _require_archives(jobs: list[tuple[str, Path]]) -> None:
    missing = [path.name for _, path in jobs if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"required source archives missing or empty: {', '.join(missing)}")


def download(asset: Asset) -> dict[str, int]:
    jobs = _jobs(asset)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: _fetch(*job), jobs))
    _require_archives(jobs)
    return {"requested": len(jobs), "present": int(sum(results))}


def _read_klines(path: Path) -> np.ndarray:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(archive.namelist()[0])
    rows = []
    for line in io.BytesIO(raw):
        if line.startswith(b"open_time"):
            continue
        parts = line.split(b",")
        rows.append(
            (int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), float(parts[7]))
        )
    return np.array(rows, dtype=np.float64)


def _source_bounds(asset: Asset, path: Path) -> tuple[int, int]:
    period = path.stem.removeprefix(f"{asset.symbol}-1m-")
    first = dt.date.fromisoformat(period + "-01" if len(period) == 7 else period)
    if len(period) == 7:
        last = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    else:
        last = first + dt.timedelta(days=1)
    return (
        int(dt.datetime.combine(first, dt.time(), dt.UTC).timestamp() * 1000),
        int(dt.datetime.combine(last, dt.time(), dt.UTC).timestamp() * 1000),
    )


def _long_missing_days(left: int, right: int, stamps: np.ndarray) -> set[dt.date]:
    """Days containing a source gap of at least an hour, including month edges."""
    grid = np.arange(left, right, MINUTE, dtype=np.int64)
    missing = np.flatnonzero(~np.isin(grid, stamps[stamps % MINUTE == 0]))
    days: set[dt.date] = set()
    for run in np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1):
        if len(run) < 60:
            continue
        first = dt.datetime.fromtimestamp(int(grid[run[0]]) / 1000, dt.UTC).date()
        last = dt.datetime.fromtimestamp(int(grid[run[-1]]) / 1000, dt.UTC).date()
        while first <= last:
            days.add(first)
            first += dt.timedelta(days=1)
    return days


def build(asset: Asset) -> dict[str, object]:
    jobs = _jobs(asset)
    _require_archives(jobs)
    kline_dir = DATA / "assets" / asset.name / "klines"
    files = [path for _, path in jobs if path.parent == kline_dir]
    parts = []
    daily_gaps: set[dt.date] = set()
    for path in files:
        rows = _read_klines(path)
        left, right = _source_bounds(asset, path)
        stamps = rows[:, 0].astype(np.int64) if len(rows) else np.empty(0, dtype=np.int64)
        if (
            len(stamps) < (right - left) // MINUTE * 0.8
            or np.any((stamps < left) | (stamps >= right))
            or len(np.unique(stamps)) != len(stamps)
        ):
            raise ValueError(f"source archive incomplete or wrong period: {path.name}")
        parts.append(rows)
        if len(path.stem.removeprefix(f"{asset.symbol}-1m-")) == 7:
            daily_gaps.update(_long_missing_days(left, right, stamps))
    # Monthly ZIPs may omit entire days or contain off-minute timestamps while
    # the official daily ZIP has the correct bars. Preserve both source files;
    # prefer daily rows at overlapping timestamps.
    daily_jobs = []
    for day in sorted(daily_gaps):
        name = f"{asset.symbol}-1m-{day.isoformat()}.zip"
        url = f"{BASE}/{asset.market}/daily/klines/{asset.symbol}/1m/{name}"
        daily_jobs.append((url, kline_dir / name))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda job: _fetch(*job), daily_jobs))
    _require_archives(daily_jobs)
    daily_parts = []
    for _, path in daily_jobs:
        rows = _read_klines(path)
        left, right = _source_bounds(asset, path)
        stamps = rows[:, 0].astype(np.int64) if len(rows) else np.empty(0, dtype=np.int64)
        if not len(stamps) or np.any((stamps < left) | (stamps >= right)) or len(np.unique(stamps)) != len(stamps):
            raise ValueError(f"daily source archive empty or wrong period: {path.name}")
        daily_parts.append(rows)
    joined = np.concatenate([*daily_parts, *parts])
    joined = joined[np.argsort(joined[:, 0], kind="stable")]
    _, unique = np.unique(joined[:, 0], return_index=True)
    joined = joined[unique]
    start = int(joined[0, 0])
    start += (-start) % HOUR
    end = int(joined[-1, 0])
    end -= (end + MINUTE) % HOUR
    grid = np.arange(start, end + MINUTE, MINUTE, dtype=np.int64)
    ts = joined[:, 0].astype(np.int64)
    index = np.searchsorted(ts, grid)
    index = np.clip(index, 0, len(ts) - 1)
    present = ts[index] == grid
    o = np.where(present, joined[index, 1], np.nan)
    h = np.where(present, joined[index, 2], np.nan)
    low = np.where(present, joined[index, 3], np.nan)
    c = np.where(present, joined[index, 4], np.nan)
    qv = np.where(present, joined[index, 5], 0.0)
    filled = int((~present).sum())
    residual_long_gaps = _long_missing_days(start, end + MINUTE, ts)
    last_close = np.nan
    for i in range(len(grid)):
        if present[i]:
            last_close = c[i]
        elif not np.isnan(last_close):
            o[i] = h[i] = low[i] = c[i] = last_close
    keep = ~np.isnan(c)
    first_valid = int(np.argmax(keep))
    grid = grid[first_valid:]
    o, h, low, c, qv, present = (a[first_valid:] for a in (o, h, low, c, qv, present))
    cut = len(grid) - len(grid) % 60
    grid = grid[:cut]
    o, h, low, c, qv, present = (a[:cut] for a in (o, h, low, c, qv, present))
    missing = np.flatnonzero(~present)
    longest_gap = max((len(run) for run in np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1)), default=0)
    funding_slots = 0
    if asset.funding:
        fund_ts: list[int] = []
        fund_rate: list[float] = []
        for _, path in jobs:
            if path.parent != DATA / "assets" / asset.name / "funding":
                continue
            with zipfile.ZipFile(path) as archive:
                text = archive.read(archive.namelist()[0]).decode()
            for line in text.splitlines()[1:]:
                bits = line.split(",")
                fund_ts.append(int(bits[0]))
                fund_rate.append(float(bits[2]))
        np.savez(DATA / "assets" / f"{asset.name}_funding.npz", ts=np.array(fund_ts), rate=np.array(fund_rate))
        funding_slots = len(fund_ts)
    out = DATA / "assets" / f"{asset.name}_1m.npz"
    np.savez(out, ts=grid, o=o, h=h, l=low, c=c, qv=qv, present=present)
    return {
        "asset": asset.name,
        "ok": longest_gap <= 1440,
        "minutes": len(grid),
        "filled_minutes": filled,
        "filled_share": filled / max(len(grid), 1),
        "daily_backfill_archives": len(daily_jobs),
        "residual_long_gap_days": [day.isoformat() for day in sorted(residual_long_gaps)],
        "max_consecutive_unfilled_minutes": longest_gap,
        "first": dt.datetime.fromtimestamp(int(grid[0]) / 1000, dt.UTC).isoformat(),
        "last": dt.datetime.fromtimestamp(int(grid[-1]) / 1000, dt.UTC).isoformat(),
        "funding_slots": funding_slots,
        "sha256_note": "compute with sha256sum on the npz",
    }


def main() -> int:
    failed = False
    for asset in ASSETS.values():
        print(asset.name, download(asset), flush=True)
        result = build(asset)
        print(result, flush=True)
        failed |= not bool(result["ok"])
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
