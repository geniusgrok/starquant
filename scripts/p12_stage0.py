"""P12 stage 0: does an Amihud illiquidity screen bind on this pool at all?

Pre-registered in docs/RESEARCH_LOG.md before this ran.  Measures two things and nothing else:

  (a) the share of symbol-refreshes an ILLIQ > m x median screen would change, for m in {2, 4, 8};
      CORRECTION (stage 1, same day): the median here is taken over the SELECTED MEMBERS of a refresh,
      while the pre-registered rule normalises by the median of the CANDIDATE SET - about 81x larger.
      This file's numbers therefore describe a tighter, un-pre-registered screen; its PROCEED verdict
      does not apply to the pre-registered one, which stage 1 measured as inert.  Kept unchanged because
      it is the record of what was run; see the P12 stage 1 section of docs/RESEARCH_LOG.md.
  (b) the dispersion of log(ILLIQ) among the members of a refresh, because a screen needs something
      to rank on.

Stop rule, fixed before the run: if the tightest threshold (m=2) changes fewer than 3% of
symbol-refreshes, the screen is inert, and no backtest runs and no trials-ledger entry is spent.

Gap handling, also pre-registered: a daily return computed across a hole in the store spans the whole
hole, which would make a symbol with missing data look illiquid.  Any symbol-day whose previous daily
bar is absent is dropped from the ILLIQ average rather than patched, and the count is reported.

Writes a JSON report; changes nothing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "~/starquant/.starquant/data")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "reports/research")
WINDOW = 30  # = universe.yaml volume_lookback_days; fixed, not a free parameter
MULTIPLES = (2.0, 4.0, 8.0)
BINDING_FLOOR = 0.03


def daily_frames(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide (day x symbol) close and quote volume from the 1d parquet store."""
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for symbol in symbols:
        path = ROOT / "klines" / symbol / "1d.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=["open_time", "close", "quote_volume"])
        index = pd.DatetimeIndex(pd.to_datetime(frame["open_time"].to_numpy(), unit="ms", utc=True)).normalize()
        keep = ~index.duplicated(keep="last")
        closes[symbol] = pd.Series(frame["close"].to_numpy(dtype=float), index=index)[keep]
        volumes[symbol] = pd.Series(frame["quote_volume"].to_numpy(dtype=float), index=index)[keep]
    return pd.DataFrame(closes).sort_index(), pd.DataFrame(volumes).sort_index()


def illiquidity(close: pd.DataFrame, volume: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Trailing-``WINDOW`` mean of |daily return| / daily quote volume, on a UTC-day grid.

    Returns the ILLIQ frame plus (dropped, total) observation counts for the gap rule.
    """
    grid = pd.date_range(close.index.min(), close.index.max(), freq="D", tz="UTC")
    close, volume = close.reindex(grid), volume.reindex(grid)
    returns = close.pct_change()
    # A return is only usable when yesterday's bar exists too; otherwise it spans a hole in the store.
    contiguous = close.notna() & close.shift(1).notna()
    observed = close.notna() & volume.gt(0)
    usable = contiguous & observed
    dropped = int((observed & ~contiguous).to_numpy().sum())
    total = int(observed.to_numpy().sum())
    raw = (returns.abs() / volume.where(volume > 0)).where(usable)
    illiq = raw.rolling(WINDOW, min_periods=WINDOW // 2).mean()
    return illiq, dropped, total


def main() -> int:
    membership = pd.read_parquet(ROOT / "membership.parquet")
    membership.index = pd.DatetimeIndex(membership.index)
    members = membership.astype(bool)
    close, volume = daily_frames(list(members.columns))
    illiq, dropped, total = illiquidity(close, volume)

    changed = {f"m={m:g}": 0 for m in MULTIPLES}
    pairs = 0
    refreshes_with_a_change = {f"m={m:g}": 0 for m in MULTIPLES}
    excluded_names: dict[str, dict[str, int]] = {f"m={m:g}": {} for m in MULTIPLES}
    iqrs: list[float] = []
    unscored = 0

    for date in members.index:
        row = members.loc[date]
        names = [s for s in members.columns if bool(row[s])]
        if not names:
            continue
        # ILLIQ as it stood strictly before the refresh (causal, same convention as the membership table)
        history = illiq.loc[: date - pd.Timedelta(nanoseconds=1)]
        if history.empty:
            continue
        scores = history.iloc[-1].reindex(names)
        live = scores.dropna()
        unscored += len(names) - len(live)
        pairs += len(names)
        if len(live) < 3:
            continue
        positive = live[live > 0]
        if len(positive) >= 3:
            logs = np.log(positive.to_numpy())
            iqrs.append(float(np.percentile(logs, 75) - np.percentile(logs, 25)))
        median = float(live.median())
        for m in MULTIPLES:
            key = f"m={m:g}"
            out = live[live > m * median]
            changed[key] += len(out)
            refreshes_with_a_change[key] += 1 if len(out) else 0
            for name in out.index:
                excluded_names[key][name] = excluded_names[key].get(name, 0) + 1

    # The last refresh, by name, so a reader can see the numbers rather than trust the aggregate (D-024).
    last = members.index[-1]
    last_names = [s for s in members.columns if bool(members.loc[last, s])]
    last_scores = illiq.loc[: last - pd.Timedelta(nanoseconds=1)].iloc[-1].reindex(last_names).dropna().sort_values()
    snapshot = {
        "refresh": str(last.date()),
        "median_illiq": float(last_scores.median()),
        "by_symbol": {s: round(float(v) / float(last_scores.median()), 3) for s, v in last_scores.items()},
    }

    shares = {key: (count / pairs if pairs else 0.0) for key, count in changed.items()}
    tightest = shares[f"m={min(MULTIPLES):g}"]
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "stage": 0,
        "window_days": WINDOW,
        "multiples": list(MULTIPLES),
        "binding_floor": BINDING_FLOOR,
        "refreshes": len(members),
        "symbol_refreshes": pairs,
        "symbol_refreshes_without_illiq": unscored,
        "gap_rule": {"observations_dropped": dropped, "observations_total": total},
        "changed_symbol_refreshes": changed,
        "changed_share": shares,
        "refreshes_touched": refreshes_with_a_change,
        "log_illiq_iqr_mean": float(np.mean(iqrs)) if iqrs else None,
        "log_illiq_iqr_median": float(np.median(iqrs)) if iqrs else None,
        "most_excluded": {
            key: sorted(names.items(), key=lambda kv: -kv[1])[:10] for key, names in excluded_names.items()
        },
        "latest_refresh_multiples_of_median": snapshot,
        "verdict": "PROCEED_TO_STAGE_1" if tightest >= BINDING_FLOOR else "INERT_STOP",
        "verdict_basis": f"tightest multiple m={min(MULTIPLES):g} changes {tightest:.4%} of symbol-refreshes",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"p12-stage0-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "most_excluded"}, indent=2, sort_keys=True))
    print(f"\nwritten {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
