"""Restore the three frozen BTC inputs and premium archives from public sources."""

from __future__ import annotations

import hashlib
import io
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from btc_perp.config import ROOT
from scripts.assets import Asset, _jobs, _read_klines

DATA = ROOT / "data"
EXPECTED = {
    "btcusdt_1m.npz": "259ceaae3bbc7fc7d11f128b3b7ff0658651e56ef0fdd57cf0d4e9c95d197c0a",
    "funding.npz": "0682df98242a6fccfe86da66a1da871c2af1d0b955fac6d38734b0059b94cb7a",
    "usdcny_frankfurter.json": "67606315ea34c0301e0129ac8fc27056099986d9fbd58a552a07f140cdd05bb5",
}


def require_digest(path: Path, expected: str) -> None:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"frozen input identity mismatch: {path}")


def fetch(job: tuple[str, Path]) -> None:
    url, path = job
    path.parent.mkdir(parents=True, exist_ok=True)
    checksum = Path(str(path) + ".CHECKSUM")
    if path.exists() and checksum.exists():
        require_digest(path, checksum.read_text().split()[0])
        return
    for source, target in ((url, path), (url + ".CHECKSUM", checksum)):
        partial = target.with_suffix(target.suffix + ".partial")
        subprocess.run(["curl", "-fsSL", "--retry", "3", "--max-time", "90", "-o", str(partial), source], check=True)
        partial.replace(target)
    require_digest(path, checksum.read_text().split()[0])


def main() -> int:
    DATA.mkdir(exist_ok=True)
    present = []
    for name, expected in EXPECTED.items():
        path = DATA / name
        if path.exists():
            require_digest(path, expected)
            present.append(name)
    if len(present) < len(EXPECTED):
        jobs = _jobs(Asset("btc", "futures/um", "BTCUSDT", (2020, 1), (2026, 8), True, (2026, 9, 19)))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch, jobs))
        klines = [path for _, path in jobs if path.parent.name == "klines"]
        if "btcusdt_1m.npz" not in present:
            joined = np.concatenate([_read_klines(path) for path in klines])
            joined = joined[np.argsort(joined[:, 0], kind="stable")]
            np.savez(
                DATA / "btcusdt_1m.npz",
                ts=joined[:, 0].astype(np.int64),
                o=joined[:, 1],
                h=joined[:, 2],
                l=joined[:, 3],
                c=joined[:, 4],
                qv=joined[:, 5],
            )
        if "funding.npz" not in present:
            pieces = []
            for _, path in jobs:
                if path.parent.name == "funding":
                    with zipfile.ZipFile(path) as archive:
                        body = archive.read(archive.namelist()[0])
                    pieces.append(np.loadtxt(io.BytesIO(body), delimiter=",", skiprows=1, usecols=(0, 2)))
            joined = np.concatenate(pieces)
            np.savez(DATA / "funding.npz", ts=joined[:, 0].astype(np.int64), rate=joined[:, 1])
        if "usdcny_frankfurter.json" not in present:
            subprocess.run(
                [
                    "curl",
                    "-fsSL",
                    "--retry",
                    "3",
                    "--max-time",
                    "90",
                    "-o",
                    str(DATA / "usdcny_frankfurter.json"),
                    "https://api.frankfurter.dev/v1/2019-12-31..2026-09-18?base=USD&symbols=CNY",
                ],
                check=True,
            )
    premium = [
        (
            f"https://data.binance.vision/data/futures/um/daily/premiumIndexKlines/BTCUSDT/8h/BTCUSDT-8h-2026-09-{day:02d}.zip",
            DATA / "premium" / f"BTCUSDT-8h-2026-09-{day:02d}.zip",
        )
        for day in range(1, 20)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, premium))
    for name, expected in EXPECTED.items():
        require_digest(DATA / name, expected)
    print("Frozen BTC inputs match all three recorded SHA-256 values; 19 premium archives verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
