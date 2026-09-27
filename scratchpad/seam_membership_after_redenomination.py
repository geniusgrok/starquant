"""After a same-name repricing seam, is the name ever a point-in-time member inside the next 720 bars?

The question is the third item of the 2026-09-25 backtest-guard audit's first pass
(`docs/analysis/2026-09-25-backtest-guard-audit.md`, "同名重新计价后，720h horizon ..."): tsmom's
horizon return is `close / close.shift(h) - 1` (`starquant_alpha/features.py`), so for `k < h - g` bars
after a seam with `g` missing bars the h-bar lookback lands on the OLD series and reads the repricing as
a move.  The audit's criterion: over the 720 bars after each seam, does the membership table the research
path reads hold a single True?  All False moves the item to "excluded".

The seam is what `starquant_live.bar_sanity` flags, not a date typed in here: the shipped `jump` check
(|ln close ratio| > ln 2) with `continuous` false - no trade bridged the two closes.  Exactly one such
flag per file is required; anything else stops the run rather than picking one.

Membership is read the way `research validate --universe pit` reads it: `_membership_table` ->
`tenure_mask(..., 0)` (the 09-19 evidence ran `min_tenure 0`) -> `membership_at_bars` on the 720 hourly
open times starting at the seam bar.  The 09-19 evidence is only read for its `range`, `symbols` and
`dataset.membership` summary.

Read-only: reads `<data-root>/klines/<symbol>/{1h,1d}.parquet`, `<data-root>/membership.parquet` and
the evidence JSON; writes only the optional `--json` output.  No ledger, no validate.

    PYTHONPATH=<worktree> .venv/bin/python scratchpad/seam_membership_after_redenomination.py \
        --data-root ~/starquant/.starquant/data [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import starquant_live.bar_sanity as sanity
from starquant_cli.research_panel import _membership_table
from starquant_data.pool import membership_at_bars, tenure_mask

HOUR_MS = 3_600_000
WINDOW = 720
HORIZONS = (168, 336, 720)  # config/alpha_registry.yaml, tsmom
EVIDENCE = Path("reports/research/tsmom-validation-20260919T081914Z.json")
#: The audit's list.  PUMPUSDT is the case RESEARCH_LOG already checked by hand ("PUMPUSDT：同一个名字下的
#: 两段序列"); it runs as a reference row so this script is checked against a known answer.
NAMES = ("BNXUSDT", "LITUSDT", "AERGOUSDT", "MAVIAUSDT", "CVXUSDT", "KORUUSDT", "CRWDUSDT")
REFERENCE = ("PUMPUSDT",)
COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]


def _stamp(ms: int | pd.Timestamp) -> str:
    ts = ms if isinstance(ms, pd.Timestamp) else pd.Timestamp(int(ms), unit="ms", tz="UTC")
    return ts.strftime("%Y-%m-%d %H:%M")


def seam_of(symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    """The one jump in the file that no trade bridged, as the shipped check reports it."""
    flags = [f for f in sanity._check_frame(symbol, frame, HOUR_MS) if f["check"] == "jump" and not f["continuous"]]
    if len(flags) != 1:
        raise SystemExit(f"{symbol}: expected exactly one non-continuous jump, found {len(flags)}: {flags}")
    flag = flags[0]
    times = frame["open_time"].to_numpy(dtype=np.int64)
    i = int(np.flatnonzero(times == flag["open_time"])[0])
    # Flat, zero-volume bars immediately before the seam: the last price the old series printed and held.
    flat = (
        (frame["open"] == frame["high"]) & (frame["high"] == frame["low"]) & (frame["low"] == frame["close"])
        & (frame["volume"] == 0)
    ).to_numpy()
    run = 0
    while i - 1 - run >= 0 and flat[i - 1 - run]:
        run += 1
    return {
        "seam_open_time": int(flag["open_time"]),
        "previous_bar_open_time": int(times[i - 1]),
        "gap_bars": int(flag["gap_bars"]),
        "flat_zero_volume_bars_before": run,
        "previous_close": float(flag["previous_close"]),
        "close": float(flag["close"]),
        "ratio": float(flag["close"] / flag["previous_close"]),
        "log_return": math.log(flag["close"] / flag["previous_close"]),
        "open_gap": float(flag["open_gap"]),
    }


def daily_starts_at_seam(root: Path, symbol: str, seam_ms: int) -> bool | None:
    path = root / "klines" / symbol / "1d.parquet"
    if not path.exists():
        return None
    first = int(pd.read_parquet(path, columns=["open_time"])["open_time"].min())
    return pd.Timestamp(first, unit="ms", tz="UTC") == pd.Timestamp(seam_ms, unit="ms", tz="UTC").floor("D")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="~/starquant/.starquant/data")
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    root = Path(args.data_root)

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    lo, hi = pd.Timestamp(evidence["range"]["start"]), pd.Timestamp(evidence["range"]["end"])
    evidence_symbols = set(evidence["symbols"])
    table = _membership_table(str(root))
    summary = evidence["dataset"]["membership"]
    same_table = (
        (root / "membership.parquet").stat().st_size == summary["file"]["bytes"]
        and len(table) == summary["refreshes"]
        and table.shape[1] == summary["symbols"]
        and int(table.any(axis=0).sum()) == summary["union"]
        and str(table.index[0]) == summary["first"]
        and str(table.index[-1]) == summary["last"]
    )
    print(f"bar_sanity from {sanity.__file__}; jump threshold ln {math.exp(sanity.MAX_LOG_RETURN):g}")
    print(f"evidence {EVIDENCE.name}: range {lo} -> {hi}, {len(evidence_symbols)} symbols, min_tenure {evidence['min_tenure']}")
    print(f"membership table {table.shape}, {table.index[0].date()} -> {table.index[-1].date()};"
          f" matches the evidence's dataset.membership summary: {same_table}")
    members = tenure_mask(table, int(evidence["min_tenure"]))

    rows = []
    for symbol in NAMES + REFERENCE:
        frame = pd.read_parquet(root / "klines" / symbol / "1h.parquet", columns=COLUMNS)
        seam = seam_of(symbol, frame)
        start = pd.Timestamp(seam["seam_open_time"], unit="ms", tz="UTC")
        bars = pd.date_range(start, periods=WINDOW, freq="h")
        column = members[[symbol]] if symbol in members.columns else pd.DataFrame(False, index=members.index, columns=[symbol])
        at_bars = membership_at_bars(column, bars)[symbol]
        true_bars = at_bars[at_bars]
        g = seam["gap_bars"]
        # Bars k after the seam whose h-bar lookback lands on the old series (k < h - g), and whether any
        # of them is a member.  A True at k >= h - g reads NaN (the gap) or the new series only.
        k_true = [int((ts - start) / pd.Timedelta(hours=1)) for ts in true_bars.index]
        crossing = {h: max(0, h - g) for h in HORIZONS}
        row = {
            "symbol": symbol,
            "reference_only": symbol in REFERENCE,
            **seam,
            "seam": _stamp(start),
            "window_last_bar": _stamp(bars[-1]),
            "member_true_bars_in_720": int(at_bars.sum()),
            "member_true_first": _stamp(true_bars.index[0]) if len(true_bars) else None,
            "member_true_last": _stamp(true_bars.index[-1]) if len(true_bars) else None,
            "member_true_k": [k_true[0], k_true[-1]] if k_true else None,
            "bars_whose_lookback_crosses_the_seam": crossing,
            "member_true_bars_whose_lookback_crosses": {h: sum(k < crossing[h] for k in k_true) for h in HORIZONS},
            "window_inside_evidence_range": bool(lo <= bars[0] and bars[-1] <= hi),
            "member_true_bars_inside_evidence_range": int(((true_bars.index >= lo) & (true_bars.index <= hi)).sum()),
            "in_evidence_symbols": symbol in evidence_symbols,
            "member_days_anywhere": int(table[symbol].sum()) if symbol in table.columns else 0,
            "member_days_first_last": (
                [str(table.index[table[symbol]].min().date()), str(table.index[table[symbol]].max().date())]
                if symbol in table.columns and table[symbol].any() else None
            ),
            "daily_file_starts_at_seam": daily_starts_at_seam(root, symbol, seam["seam_open_time"]),
        }
        rows.append(row)

    print(f"\n{'symbol':>10} {'seam (UTC)':>17} {'gap':>4} {'flat':>5} {'ratio':>9} {'True/720':>9}"
          f" {'in range':>9} {'in ev.sym':>10} {'member days (all time)':>24} {'1d restarts':>12}")
    for r in rows:
        days = f"{r['member_days_anywhere']}" + (f" ({r['member_days_first_last'][0]}..{r['member_days_first_last'][1]})" if r["member_days_first_last"] else "")
        print(
            f"{r['symbol']:>10} {r['seam']:>17} {r['gap_bars']:>4} {r['flat_zero_volume_bars_before']:>5}"
            f" x{r['ratio']:<8.4g} {r['member_true_bars_in_720']:>9} {r['window_inside_evidence_range']!s:>9}"
            f" {r['in_evidence_symbols']!s:>10} {days:>24} {r['daily_file_starts_at_seam']!s:>12}"
            + ("   <- reference, not in the audit's list" if r["reference_only"] else "")
        )
    for r in rows:
        if r["member_true_bars_in_720"]:
            print(f"  {r['symbol']}: True from {r['member_true_first']} to {r['member_true_last']} (k {r['member_true_k']});"
                  f" of those, lookback crosses the seam at h=168/336/720: {r['member_true_bars_whose_lookback_crosses']}")
    audited = [r for r in rows if not r["reference_only"]]
    print(f"\naudit criterion (all False over the 720 bars after every seam): {all(r['member_true_bars_in_720'] == 0 for r in audited)}")
    if args.json:
        Path(args.json).write_text(json.dumps({"evidence": EVIDENCE.name, "membership_matches_evidence": same_table,
                                               "rows": rows}, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
