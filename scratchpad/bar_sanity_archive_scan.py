"""G6's thresholds, measured: `starquant_live.bar_sanity` run over every 1h bar in the archive.

Read-only: reads ``<data-root>/klines/*/1h.parquet`` and ``<data-root>/membership.parquet``, writes nothing.

    PYTHONPATH=$PWD .venv/bin/python scratchpad/bar_sanity_archive_scan.py --data-root .starquant/data

What it prints, and why each piece is there:

1. The shipped check (``check_bars`` with the module's own constants) over each file: exact counts per
   check, all bars and bars on PIT-member days.  Member days are the population the loop trades.
2. The same rules at looser settings (``MAX_LOG_RETURN`` = ln 1.5, ``FROZEN_BARS`` = 1), so the
   threshold is chosen from a table rather than asserted.  The sweep is filtered back to the shipped
   settings and must reproduce (1) exactly, or the script stops - the table has to describe the code.
3. Every ``jump`` split by whether a trade bridged the two closes (``continuous``).  A redenomination, a
   placeholder price before a listing's first trade, or a reopening after a halt has no trade between
   the two closes; a real hour does.  "False positive" below means a continuous flag: a real move.
4. BNXUSDT's 2023-02-22 14:00 bar, printed in full: the case the check has to catch.
5. What one live cycle costs: ``check_bars`` on the live shape (the last membership day's members,
   the last 1,442 bars each - the window the loop requests), timed over 200 repetitions.
"""

from __future__ import annotations

import argparse
import math
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import starquant_live.bar_sanity as sanity

HOUR_MS = 3_600_000
LIVE_WINDOW = 1_442  # config/live.demo.yaml: max(history_bars, min_history_bars + warmup)
LIVE_BARS_PER_YEAR = 8_760
SWEEP_T = {"ln 1.5": math.log(1.5), "ln 2": math.log(2.0), "ln 3": math.log(3.0), "ln 4": math.log(4.0)}
SWEEP_N = (1, 2, 3, 5, 15, 16)
COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]


def _day(ms: int) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d")


def _stamp(ms: int) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


def _member(flag: dict[str, Any], days: set[str]) -> bool:
    if flag["check"] != "frozen":
        return _day(flag["open_time"]) in days
    span = pd.date_range(_day(flag["open_time"]), _day(flag["last_open_time"]), freq="D")
    return any(day in days for day in span.strftime("%Y-%m-%d"))


def _loose_flags(symbol: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    shipped = (sanity.MAX_LOG_RETURN, sanity.FROZEN_BARS)
    sanity.MAX_LOG_RETURN, sanity.FROZEN_BARS = min(SWEEP_T.values()), min(SWEEP_N)
    try:
        return sanity._check_frame(symbol, frame, HOUR_MS)
    finally:
        sanity.MAX_LOG_RETURN, sanity.FROZEN_BARS = shipped


def _exact_log_return(flag: dict[str, Any]) -> float:
    return math.log(flag["close"] / flag["previous_close"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=".starquant/data")
    root = Path(parser.parse_args().data_root)
    print(f"bar_sanity from {sanity.__file__}")
    print(f"shipped: MAX_LOG_RETURN = ln {math.exp(sanity.MAX_LOG_RETURN):g}, FROZEN_BARS = {sanity.FROZEN_BARS}")
    membership = pd.read_parquet(root / "membership.parquet")
    member_days = {s: set(membership.index[membership[s].to_numpy()].strftime("%Y-%m-%d")) for s in membership.columns}

    started = time.perf_counter()
    files = sorted((root / "klines").glob("*/1h.parquet"))
    bars = member_bars = zero_volume = zero_volume_flat = 0
    shipped_counts: Counter[str] = Counter()
    flags: list[dict[str, Any]] = []
    for path in files:
        symbol = path.parent.name
        frame = pd.read_parquet(path, columns=COLUMNS)
        days = member_days.get(symbol, set())
        bars += len(frame)
        empty = frame["volume"] == 0
        flat = (frame["open"] == frame["high"]) & (frame["high"] == frame["low"]) & (frame["low"] == frame["close"])
        zero_volume += int(empty.sum())
        zero_volume_flat += int((empty & flat).sum())
        member_bars += int(np.isin(pd.to_datetime(frame["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d"), list(days)).sum()) if days else 0
        reading = sanity.check_bars({symbol: frame})
        assert not reading.get("error") and not reading["errors"], reading
        shipped_counts.update(reading["counts"])
        for flag in _loose_flags(symbol, frame):
            flag["member"] = _member(flag, days)
            flags.append(flag)
    print(f"\n{len(files)} files, {bars:,} bars, {member_bars:,} on member days, {time.perf_counter() - started:.1f}s")

    # (2) the sweep must reproduce the shipped counts exactly
    rebuilt = {
        "ohlc": sum(f["check"] == "ohlc" for f in flags),
        "frozen": sum(f["check"] == "frozen" and f["bars"] >= sanity.FROZEN_BARS for f in flags),
        "jump": sum(f["check"] == "jump" and abs(_exact_log_return(f)) > sanity.MAX_LOG_RETURN for f in flags),
    }
    assert rebuilt == dict(shipped_counts), (rebuilt, dict(shipped_counts))
    print(f"shipped counts {dict(shipped_counts)} (the sweep, filtered back, reproduces them)")

    print("\n== ohlc")
    ohlc = [f for f in flags if f["check"] == "ohlc"]
    print(f"   {len(ohlc)} bars ({sum(f['member'] for f in ohlc)} on member days): {Counter(r for f in ohlc for r in f['reasons'])}")

    print("\n== frozen: runs of flat, zero-volume bars")
    print(f"   zero-volume bars {zero_volume:,}, of which flat {zero_volume_flat:,}")
    frozen = [f for f in flags if f["check"] == "frozen"]
    for n in SWEEP_N:
        hit = [f for f in frozen if f["bars"] >= n]
        print(f"   runs >= {n:2d}: {len(hit):5d} all, {sum(f['member'] for f in hit):3d} touching member days")
    lengths = Counter(f["bars"] for f in frozen if f["member"])
    print(f"   run lengths touching member days: {sorted(lengths.items())}")
    singles = Counter(f["open_time"] for f in frozen if f["bars"] == 1 and f["member"])
    print(f"   member 1-bar runs by bar: {[(_stamp(k), v) for k, v in singles.most_common()]}")
    for bar in singles:
        shared = sum(1 for f in frozen if f["bars"] == 1 and f["open_time"] == bar)
        print(f"   symbols with a 1-bar run at {_stamp(bar)}, member or not: {shared}")
    for f in sorted((f for f in frozen if f["member"] and f["bars"] >= sanity.FROZEN_BARS), key=lambda f: f["open_time"]):
        print(f"   member run: {f['symbol']} {_stamp(f['open_time'])} -> {_stamp(f['last_open_time'])} ({f['bars']} bars) at {f['price']}")

    print("\n== jump: |ln(close / previous close)| > T; continuous = a trade bridged the two closes")
    jumps = [f for f in flags if f["check"] == "jump"]
    member_share = member_bars / LIVE_BARS_PER_YEAR  # member symbol-years in the archive
    print(f"   {'T':>7} {'all':>6} {'real':>6} {'artifact':>9} {'member':>7} {'member real':>12} {'real per live-year (17 symbols)':>32}")
    for label, threshold in SWEEP_T.items():
        hit = [f for f in jumps if abs(_exact_log_return(f)) > threshold]
        real = [f for f in hit if f["continuous"]]
        member_real = [f for f in real if f["member"]]
        per_year = len(member_real) / member_share * 17
        print(
            f"   {label:>7} {len(hit):6d} {len(real):6d} {len(hit) - len(real):9d} {sum(f['member'] for f in hit):7d}"
            f" {len(member_real):12d} {per_year:32.2f}"
        )
    print("   no trade between the closes (artifacts), T = ln 1.5 and above:")
    for f in sorted((f for f in jumps if not f["continuous"]), key=lambda f: -abs(_exact_log_return(f))):
        print(
            f"     {f['symbol']:>12} {_stamp(f['open_time'])} x{math.exp(_exact_log_return(f)):<8.4g}"
            f" ln {_exact_log_return(f):+.3f} open_gap {f['open_gap']:+.3f} gap_bars {f['gap_bars']:4d} member {int(f['member'])}"
        )
    shipped_member_real = sorted(
        (f for f in jumps if f["continuous"] and f["member"] and abs(_exact_log_return(f)) > sanity.MAX_LOG_RETURN),
        key=lambda f: f["open_time"],
    )
    print(f"   real hours on member days at the shipped T ({len(shipped_member_real)}, {len({_day(f['open_time']) for f in shipped_member_real})} distinct days):")
    for f in shipped_member_real:
        print(f"     {f['symbol']:>12} {_stamp(f['open_time'])} x{math.exp(_exact_log_return(f)):.4g}")

    print("\n== BNXUSDT 2023-02-22 14:00 under the shipped check")
    frame = pd.read_parquet(root / "klines/BNXUSDT/1h.parquet", columns=COLUMNS)
    reading = sanity.check_bars({"BNXUSDT": frame})
    hit = [f for f in reading["flags"] if f["check"] == "jump" and _stamp(f["open_time"]) == "2023-02-22 14:00"]
    print(f"   counts {reading['counts']}; the flag: {hit}")
    assert hit, "BNX's redenomination must be flagged"
    print("   delisted or redenominated?  Every hole in the file, and every flag the shipped check raises on it:")
    opens = frame["open_time"].to_numpy(dtype=np.int64)
    closes = frame["close"].to_numpy(dtype=float)
    for i in np.flatnonzero(np.diff(opens) != HOUR_MS):
        print(
            f"     hole {_stamp(opens[i])} -> {_stamp(opens[i + 1])} ({(opens[i + 1] - opens[i]) // HOUR_MS - 1} bars):"
            f" close {closes[i]} -> {closes[i + 1]} (x{closes[i + 1] / closes[i]:.4g})"
        )
    for flag in reading["flags"]:
        span = f" -> {_stamp(flag['last_open_time'])}, {flag['bars']} bars at {flag['price']}" if flag["check"] == "frozen" else ""
        print(f"     {flag['check']} {_stamp(flag['open_time'])}{span}")
    print(f"     file: {len(frame):,} bars, {_stamp(opens[0])} -> {_stamp(opens[-1])}")

    print("\n== one live cycle's cost: the last membership day's members, last 1,442 bars each")
    last = membership.index[-1]
    members = [s for s in membership.columns if membership.at[last, s]]
    window = {}
    for symbol in members:
        path = root / "klines" / symbol / "1h.parquet"
        if path.exists():
            window[symbol] = pd.read_parquet(path).tail(LIVE_WINDOW).reset_index(drop=True)
    timings = []
    for _ in range(200):
        began = time.perf_counter()
        sanity.check_bars(window)
        timings.append(time.perf_counter() - began)
    reading = sanity.check_bars(window)
    print(
        f"   {len(window)} symbols ({last.date()}), {reading['bars']:,} bars; counts {reading['counts']};"
        f" median {statistics.median(timings) * 1e3:.2f} ms, p95 {sorted(timings)[189] * 1e3:.2f} ms, max {max(timings) * 1e3:.2f} ms"
    )


if __name__ == "__main__":
    main()
