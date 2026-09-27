"""P32i: `p32h`'s k sweep with one more arm - the same book with its drift discounted to the honest OOS Sharpe.

WHY.  The 2026-09-25 backtest-guard audit, first pass, first item (`docs/analysis/2026-09-25-backtest-guard-
audit.md`): every pricing of `k` so far block-bootstraps the net return series of the configuration the
full sample picked.  A bootstrap keeps the series' mean, so the K table's CAGR, q95 drawdown and P(breach)
all ride a drift the selection lifted.  The honest selection procedure delivers `oos_selection.
oos_sharpe_annual` in the evidence the registry cites (`reports/research/tsmom-validation-20260919T081914Z.
json`, 1.2306); the full-sample number beside it is 1.6670.

THE ARM.  Per panel - one universe, one `k` - subtract ONE constant `c` from every bar's net return, so
that the whole series' annualised Sharpe equals that OOS value.  A constant moves the mean and nothing
else: the standard deviation, the autocorrelation, the ordering and every block the bootstrap draws are
the series' own.  `c` is solved in closed form and then CHECKED with the repository's own estimator
(`multiple_testing.sharpe_per_period` x sqrt(`bars_per_year("1h")`), the one `oos_sharpe_annual` is made
of - ddof 1, 8760 bars a year), not asserted.  `realised` takes the same `c`; the mtm ruler every arm
below uses never reads it (`p32h.ladder_at_base` only accumulates `path` for the realised ruler).

Note what the target is and is not: tsmom's single-book OOS Sharpe, applied as a haircut to the whole
registry book `p32d.panel_series` builds (tsmom + the flow_short sleeve, exits, guards).  It prices "the
drift the selection lifted", which is the audit's ask; it is not a claim that this book's own OOS Sharpe
is 1.2306.

Because the panel's own full-sample Sharpe moves with `k` (pit: 1.70 at 0.60, 1.91-1.96 at 0.15-0.30),
one target for every `k` takes a larger share of the drift the smaller `k` is.  `--drifts prop` runs the
other end as a sensitivity, NOT the audit's arm: each panel keeps the share of its own Sharpe that the
evidence's book kept out of sample (OOS / `full_sample.annualized_sharpe`, 1.2306 / 1.6670 = 0.738).

EVERYTHING ELSE IS `p32h`'s, imported rather than copied: `p32h.panel` (the static universe pinned to
`STATIC_P32G`), `p32h.run_arm` (the loop, `ladder_at_base`, the USDT conversion), `p32h.crossing`; `SEED`,
`BLOCK`, 2000 draws, one set of block starts per `k` shared by every arm - so each honest cell is PAIRED
with the published cell beside it.  The USDT conversion factor is `p32g`'s pin by default: the USDT
share of the account at its 2026-09-22 peak, 7,489.95 / 13,251.98 = 0.5652, a factor of 1.769.  It has
drifted since (1.748 in the daily reports of 2026-09-23 to 09-25); keeping p32h's is what lets the
original arm reproduce.  `--factor-report` takes a daily report's `risk_budget.usdt_drawdown.
vs_total_equity` instead - the same quantity, total-equity peak over USDT peak - and the date is printed
with every table either way.

THE DATA END is pinned, which `p32h` did not need to do on the day it ran: `p32d.panel_series` loads the
store to its newest bar and the store grows by a daily sync.  The published panels ended at the bar
opened 2026-09-22 16:00Z (pit 49,456 bars, static 49,457); `KlineStore.load` keeps `open_time < end`, so
`END` is 17:00.  The pin goes where the lookup happens - `p32d`'s namespace - and is counted, like
`p32h`'s static pin.  A different bar count stops the run: the block starts are drawn from `n`.

THE STORE ITSELF moved under that end after the published runs, for three names (`STORE_0923`).  Pinned
to `END` alone, pit k=0.30 differs from the archived series in its last 461 bars (from 2026-09-03 12:00,
up to 0.006 a bar).  `--store 0923` reads those three names as they stood before the writes, and the
anchor then has to come back bit for bit; `--store today` reads the store as it is (the backfills are
real data the published runs lacked).  Nothing is written to the store either way: two class methods are
wrapped for the life of the panel build, in this process only.

`STORE_0923` covers the writes up to 2026-09-25 11:36Z and no further.  Then `data repair` (9.4) filled
holes in 21 1h files, 4 of them in the pit union (BNX, OCEAN, OGN, RSR; none in `STATIC_P32G`), and it
records what no source held (`confirmed_gaps.json`), not the bars it added.  Since then `--store 0923`
still reproduces static bit for bit and pit stops at the anchor, as it should: the 2026-09-25 outputs
archived at `reports/research/p32i-20260925/` are the record, not a rerun.

TWO CODE BASES, one script.  `p32h`'s table was measured with D2 alone in `combine_books`; #115
(`227a6348`) gave the multi-book path D3, so on `main` the original arm no longer reproduces that table
(RESEARCH_LOG 2026-09-23, "多书研究路径的再平衡带少一条规则" §五).  Run this in a worktree at `555be470`
(the last `main` commit that reproduces it) for the D2 table, and at `main` for D2+D3.  Which band a
run measured is not asserted either: `--band` states it and `--anchor-dir` checks it.  Pointed at the
series and bootstrap output that section wrote - archived since #154 at `reports/research/k-scan-20260923/`
- the rebuilt series are compared bit for bit with its `d2` and `d3` series, and the rows with its `kgrid`
output at full precision.

CHECKS, in the order they can stop the run:
1. bar count = the published one; the data-end pin and the static pin each took exactly once
2. (with `--anchor-dir`) rebuilt series bit-identical to the archived series of the stated band
3. every discounted series: annualised Sharpe = its target, std and lag-1 autocorrelation unchanged
4. original arms vs the published table at its printed precision - RESEARCH_LOG "k 扫描的更正" §3 for
   D2, the D3 section's table for D2+D3 - and (with `--anchor-dir`) vs `kgrid` at full precision

`--drifts` picks the series the ladder arms run on (orig, honest, prop) and `--no-controls` drops `no ladder`
and `ladder@0.60`, so an extension point or a sensitivity arm does not re-buy cells already measured.  Every
`k` draws its own block starts from `SEED` and `n`, so runs split by `k` or by arm are one computation;
`scratchpad/p32i_merge_runs.py` merges them and refuses if two runs disagree on anything they share.

Zero ledger: reads the store, the membership table, the evidence JSON and config; writes only
`scratchpad/p32i-*.json` under the working directory.  The 2026-09-25 runs are archived at
`reports/research/p32i-20260925/` (RESEARCH_LOG "p32i：诚实漂移下补测 0.15").

    PYTHONPATH=<worktree> .venv/bin/python scratchpad/p32i_k_sweep_at_honest_drift.py pit|static --band d2|d3 \
        --store 0923|today [--draws 2000] [--workers 4] [--anchor-dir reports/research/k-scan-20260923] \
        [--k 0.60,0.30,0.25,0.20] [--drifts orig,honest] [--no-controls] [--factor-report reports/daily/<day>.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p32d_ladder_bootstrap_pathwise as p32d
import p32h_k_sweep_at_the_base_in_force as p32h
from p32d_ladder_bootstrap_pathwise import BLOCK, SEED, rescaled
from p32e_ruler_divergence import K
from p32f_usdt_denominated_budget import DECLARED_BUDGET
from p32g_which_k_holds_the_usdt_budget import USDT_SHARE_AT_PEAK

import starquant_alpha
from starquant_alpha.panel import bars_per_year
from starquant_alpha.validation.multiple_testing import sharpe_per_period
from starquant_data.store import FundingStore, KlineStore
from starquant_governance.policy import Policy

EVIDENCE = Path("reports/research/tsmom-validation-20260919T081914Z.json")
END = "2026-09-22 17:00"
PUBLISHED_BARS = {"pit": 49_456, "static": 49_457}
#: symbol -> (1h open_time <, funding_time <, funding rows then): the three names written to after the
#: published runs read the store (p32g 2026-09-22T18:15Z; p32h and the D3 section before 2026-09-23T06:31Z).
#:   CYSUSDT, TUTUSDT - backfilled 2026-09-23T16:32Z (RESEARCH_LOG "重启 #56"): 1h last rows before it
#:     09-04T06:00Z and 09-03T11:00Z; funding rows 1,594 and 3,192 as that section records them.  TUT's
#:     3,192nd is the 09-03 12:00 settlement, stamped 12:00:00.002, hence 13:00.
#:   LSKUSDT - 1h stopped at 09-18T16:00Z until the 2026-09-23T17:20Z daily job (RESEARCH_LOG "data sync 漏掉了
#:     池子里的名字").  Its funding count before that was not recorded; the cutoff is the one the anchor accepts.
STORE_0923 = {
    "CYSUSDT": ("2026-09-04 07:00", "2026-09-04 07:00", 1_594),
    "TUTUSDT": ("2026-09-03 12:00", "2026-09-03 13:00", 3_192),
    "LSKUSDT": ("2026-09-18 17:00", "2026-09-18 18:00", None),
}
K_DEFAULT = (0.60, 0.30, 0.25, 0.20)
SCALE = math.sqrt(bars_per_year("1h"))

#: RESEARCH_LOG 2026-09-23 "k 扫描的更正" §3, as printed: (q95 USDT, P USDT>70, CAGR) per arm, and the trip
#: rate, which is one number for both ladder arms.  D2-only band.  Strings, so each cell is compared at
#: exactly the precision it was published at (pit's `no ladder` at 0.25 was printed with two decimals).
PUBLISHED_D2 = {
    "pit": {
        0.60: {"ladder@0.60": ("-102.7", "89.5", "111.8"), "ladder@k": ("-102.7", "89.5", "111.8"),
               "no ladder": ("-125.3", "93.4", "124.7"), "trip": "100.0"},
        0.30: {"ladder@0.60": ("-65.1", "0.9", "74.1"), "ladder@k": ("-74.3", "8.8", "76.6"),
               "no ladder": ("-80.1", "13.2", "77.2"), "trip": "68.5"},
        0.25: {"ladder@0.60": ("-59.1", "0.1", "61.2"), "ladder@k": ("-67.0", "3.0", "62.3"),
               "no ladder": ("-70.03", "5.1", "62.6"), "trip": "43.0"},
        0.20: {"ladder@0.60": ("-53.7", "0.0", "48.4"), "ladder@k": ("-57.7", "0.4", "48.8"),
               "no ladder": ("-58.8", "0.9", "48.8"), "trip": "15.3"},
        "running": ("-118.9", None, "123.2"),
    },
    "static": {
        0.60: {"ladder@0.60": ("-100.1", "87.3", "110.4"), "ladder@k": ("-100.1", "87.3", "110.4"),
               "no ladder": ("-121.4", "91.2", "122.3"), "trip": "100.0"},
        0.30: {"ladder@0.60": ("-66.8", "2.0", "64.7"), "ladder@k": ("-76.2", "13.9", "67.7"),
               "no ladder": ("-83.2", "19.5", "68.4"), "trip": "75.3"},
        0.25: {"ladder@0.60": ("-60.2", "0.2", "54.0"), "ladder@k": ("-69.3", "4.3", "55.6"),
               "no ladder": ("-73.4", "7.6", "55.9"), "trip": "52.4"},
        0.20: {"ladder@0.60": ("-54.8", "0.0", "45.8"), "ladder@k": ("-59.5", "0.7", "46.3"),
               "no ladder": ("-61.3", "1.5", "46.3"), "trip": "23.6"},
        "running": ("-115.8", None, "121.5"),
    },
}
#: RESEARCH_LOG 2026-09-23 "多书研究路径的再平衡带少一条规则" §三, the right-hand side of each arrow (D2+D3).
PUBLISHED_D3 = {
    "pit": {0.30: {"ladder@0.60": ("-65.0", "1.1", "73.0"), "ladder@k": ("-74.5", "9.3", "74.9")},
            0.25: {"ladder@k": ("-66.2", "2.9", "61.5")}},
    "static": {0.30: {"ladder@k": ("-76.2", "13.0", "68.9")}, 0.25: {"ladder@k": ("-69.2", "4.4", "55.9")}},
}
#: The same two sections' interpolated k at q95(USDT) = -70%, ladder@k, printed to four places.
PUBLISHED_CROSSING = {"d2": {"pit": "0.2707", "static": "0.2548"}, "d3": {"pit": "0.2730", "static": "0.2557"}}
COMPARED = ("q95_usdt", "p_past_70_usdt", "cagr_median")
FULL = ("median_total", "q95_total", "q95_usdt", "p_past_70_usdt", "cagr_median", "draws_that_ever_tripped")


def _ms(stamp: str) -> int:
    return int(pd.Timestamp(stamp, tz="UTC").timestamp() * 1000)


@contextmanager
def store_as_of_0923() -> Iterator[dict[str, int]]:
    """`KlineStore.load` / `FundingStore.load` with `STORE_0923` applied; yields the funding rows each name kept."""
    klines, funding = KlineStore.load, FundingStore.load
    kept: dict[str, int] = {}

    def klines_then(self: KlineStore, symbol: str, interval: str, start_ms: int | None = None, end_ms: int | None = None) -> pd.DataFrame:
        frame = klines(self, symbol, interval, start_ms, end_ms)
        if symbol in STORE_0923:
            frame = frame[frame["open_time"] < _ms(STORE_0923[symbol][0])].reset_index(drop=True)
        return frame

    def funding_then(self: FundingStore, symbol: str) -> pd.DataFrame:
        frame = funding(self, symbol)
        if symbol in STORE_0923:
            frame = frame[frame["funding_time"] < _ms(STORE_0923[symbol][1])].reset_index(drop=True)
            expected = STORE_0923[symbol][2]
            if expected is not None and len(frame) != expected:
                raise RuntimeError(f"{symbol}: {len(frame)} funding rows before the backfill, recorded {expected}")
            kept[symbol] = len(frame)
        return frame

    KlineStore.load, FundingStore.load = klines_then, funding_then  # type: ignore[method-assign]
    try:
        yield kept
    finally:
        KlineStore.load, FundingStore.load = klines, funding  # type: ignore[method-assign]


def pinned_panel(mode: str, k: float) -> tuple[np.ndarray, np.ndarray]:
    """`p32h.panel` with the store read up to `END`, counted like `p32h`'s static pin."""
    calls: list[Any] = []
    original = p32d._load

    def load_to_end(root: str, symbols: list[str], interval: str, start: Any, end: Any, funding: bool, *a: Any, **kw: Any) -> Any:
        calls.append((start, end))
        if start is not None or end is not None:
            raise RuntimeError(f"panel_series passed a range of its own ({start!r}, {end!r}); the pin would override it")
        return original(root, symbols, interval, None, END, funding, *a, **kw)

    p32d._load = load_to_end
    try:
        mark, realised = p32h.panel(mode, k)
    finally:
        p32d._load = original
    if calls != [(None, None)]:
        raise RuntimeError(f"the data-end pin did not take exactly once ({calls!r})")
    if len(mark) != PUBLISHED_BARS[mode]:
        raise RuntimeError(f"{mode} k={k}: {len(mark)} bars, published {PUBLISHED_BARS[mode]}; the block starts would differ")
    return mark, realised


def annual_sharpe(x: np.ndarray) -> float:
    period = sharpe_per_period(x)
    if period is None:
        raise RuntimeError("series too short or flat for a Sharpe")
    return period * SCALE


def lag1(x: np.ndarray) -> float:
    return float(np.corrcoef(x[:-1], x[1:])[0, 1])


def honest(mark: np.ndarray, realised: np.ndarray, target: float) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """(mark - c, realised - c, what was checked): the one constant that puts the series' Sharpe on `target`."""
    std = float(np.std(mark, ddof=1))
    c = float(np.mean(mark)) - target * std / SCALE
    shifted = mark - c
    reading = {
        "full_sample_sharpe": annual_sharpe(mark),
        "c_per_bar": c,
        "c_annual_arithmetic": c * bars_per_year("1h"),
        "mean_per_bar_before": float(np.mean(mark)),
        "mean_per_bar_after": float(np.mean(shifted)),
        "sharpe_after": annual_sharpe(shifted),
        "std_rel_change": abs(float(np.std(shifted, ddof=1)) - std) / std,
        "lag1_before": lag1(mark),
        "lag1_after": lag1(shifted),
    }
    if abs(reading["sharpe_after"] - target) > 1e-9:
        raise RuntimeError(f"the shifted series reads Sharpe {reading['sharpe_after']!r}, not {target!r}")
    if reading["std_rel_change"] > 1e-12 or abs(reading["lag1_after"] - reading["lag1_before"]) > 1e-12:
        raise RuntimeError(f"a constant shift moved the std or the autocorrelation: {reading}")
    return shifted, realised - c, reading


def bits(x: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(x, dtype=np.float64).view(np.uint64)


def cell(value: float, published: str) -> str:
    places = len(published.split(".")[1]) if "." in published else 0
    return f"{value * 100:.{places}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pit", "static"))
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--band", choices=("d2", "d3"), required=True, help="the band this code base applies; the anchor checks it")
    parser.add_argument("--store", choices=("0923", "today"), required=True, help="STORE_0923 applied, or the store as it is")
    parser.add_argument("--anchor-dir", default="")
    parser.add_argument("--k", default=",".join(f"{k:.2f}" for k in K_DEFAULT))
    parser.add_argument("--factor-report", default="", help="a daily report: take risk_budget.usdt_drawdown.vs_total_equity instead of p32g's pin")
    parser.add_argument("--drifts", default="orig,honest",
                        help="which series to run the ladder arms on: orig, honest, and prop - a proportional haircut, "
                             "each panel keeping the evidence's OOS / full-sample share of its own Sharpe")
    parser.add_argument("--no-controls", action="store_true", help="skip `no ladder` and `ladder@0.60` (extension points)")
    args = parser.parse_args()
    mode, draws, band, store = args.mode, args.draws, args.band, args.store
    grid = tuple(float(x) for x in args.k.split(","))
    drifts = [d.strip() for d in args.drifts.split(",") if d.strip()]
    if not drifts or set(drifts) - {"orig", "honest", "prop"} or len(set(drifts)) != len(drifts):
        raise SystemExit(f"--drifts takes orig, honest, prop: {args.drifts!r}")

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    target = float(evidence["oos_selection"]["oos_sharpe_annual"])
    # The proportional variant (not the audit's arm - a sensitivity): the share of its Sharpe the evidence's
    # own book kept out of sample, applied to each panel's Sharpe instead of one level for every k.
    keep = target / float(evidence["full_sample"]["annualized_sharpe"])
    if args.factor_report:
        report = Path(args.factor_report)
        factor = float(json.loads(report.read_text(encoding="utf-8"))["risk_budget"]["usdt_drawdown"]["vs_total_equity"])
        share, factor_date = 1.0 / factor, report.stem
    else:
        share, factor_date = USDT_SHARE_AT_PEAK, "2026-09-22"
        factor = 1.0 / share
    usdt_budget = DECLARED_BUDGET * share
    print(f"[{mode}] draws={draws} SEED={SEED} BLOCK={BLOCK} k={grid}  starquant_alpha from {Path(starquant_alpha.__file__).parent}")
    print(f"data pinned to open_time < {END}Z; store {store}"
          + (f" ({', '.join(f'{s} 1h < {v[0]}, funding < {v[1]}' for s, v in STORE_0923.items())})" if store == "0923" else " (as it is)"))
    print(f"band {band}; honest Sharpe target {target!r} ({EVIDENCE.name} oos_selection.oos_sharpe_annual)")
    if args.factor_report:
        print(f"USDT factor {factor!r} = risk_budget.usdt_drawdown.vs_total_equity of {args.factor_report}; share {share:.6f}")
    else:
        print(f"USDT factor {factor:.4f} = 1 / {USDT_SHARE_AT_PEAK:.4f}: the 2026-09-22 USDT share at peak, p32g's pin as p32h ran it")
    print(f"drifts {drifts}; controls {'off' if args.no_controls else 'on'}")
    if "prop" in drifts:
        print(f"prop arm: each panel keeps {keep:.4f} of its own Sharpe (OOS {target:.4f} / full sample {target / keep:.4f})")
    if mode == "static":
        print(f"static universe pinned to p32h.STATIC_P32G ({len(p32h.STATIC_P32G)})")

    anchor_series = anchor_rows = None
    if args.anchor_dir:
        anchor = Path(args.anchor_dir)
        anchor_series = np.load(anchor / f"series-{mode}.npz")
        path = anchor / f"kgrid-{mode}-{draws}.json"
        anchor_rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    pending, drift, band_votes, funding_kept = [], {}, {}, {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for k in grid:
            if store == "0923":
                with store_as_of_0923() as kept:
                    mark, realised = pinned_panel(mode, k)
                funding_kept[k] = dict(kept)
            else:
                mark, realised = pinned_panel(mode, k)
            n = len(mark)
            if anchor_series is not None and f"k{k:.2f}_d2_mark" in anchor_series.files:
                band_votes[k] = [
                    band for band in ("d2", "d3")
                    if np.array_equal(bits(mark), bits(anchor_series[f"k{k:.2f}_{band}_mark"]))
                    and np.array_equal(bits(realised), bits(anchor_series[f"k{k:.2f}_{band}_realised"]))
                ]
                if band_votes[k] != [band]:
                    raise RuntimeError(f"k={k}: rebuilt series equal the archived series of {band_votes[k]!r}, expected [{band!r}]")
            h_mark, h_realised, drift[k] = honest(mark, realised, target)
            series = {"orig": (mark, realised), "honest": (h_mark, h_realised)}
            if "prop" in drifts:
                p_mark, p_realised, reading = honest(mark, realised, drift[k]["full_sample_sharpe"] * keep)
                series["prop"] = (p_mark, p_realised)
                drift[k]["prop"] = reading
            blocks = n // BLOCK
            years = (blocks * BLOCK) / 8760.0
            rng = np.random.default_rng(SEED)  # p32h's draw, verbatim: one seed and one set of starts per k
            starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(draws)])
            drift[k]["starts_sha256_16"] = hashlib.sha256(starts.tobytes()).hexdigest()[:16]
            rungs = tuple(rescaled(k, budget=usdt_budget))
            arms: list[tuple[str, str, tuple, float | None]] = [("ladder@k", d, rungs, k) for d in drifts]
            if not args.no_controls:
                arms.append(("no ladder", "orig", (), None))
                if k != K:  # at K the two ladder arms are one computation (p32h checks it; not re-bought here)
                    arms.append(("ladder@0.60", "orig", rungs, None))
            if k == K:
                arms += [("running", d, tuple(Policy().drawdown_ladder), None) for d in drifts]
            vote = f", archived {band_votes[k][0]} series bit for bit" if k in band_votes else ""
            print(f"  k={k:.2f}: {n} bars{vote}; full-sample Sharpe {drift[k]['full_sample_sharpe']:.4f} -> "
                  f"{drift[k]['sharpe_after']:.10f}, c = {drift[k]['c_per_bar']:.3e}/bar ({drift[k]['c_annual_arithmetic']:.2%}/yr)", flush=True)
            for arm, which, arm_rungs, base in arms:
                task = {"k": k, "arm": arm, "rungs": arm_rungs, "base": base, "starts": starts, "years": years,
                        "factor": factor, "mark": series[which][0], "realised": series[which][1]}
                pending.append((which, pool.submit(p32h.run_arm, task)))
        rows = []
        for which, future in pending:
            row = future.result()
            row["drift"] = which
            rows.append(row)

    by = {(r["k"], r["arm"], r["drift"]): r for r in rows}
    checks: dict[str, Any] = {"bars": PUBLISHED_BARS[mode], "band": band, "store": store,
                              "band_verified_bit_for_bit_at_k": sorted(band_votes),
                              "funding_rows_kept": {f"{k:.2f}": v for k, v in funding_kept.items()}}

    # 4. the original arms against what was published - every published cell this run has a row for
    published = PUBLISHED_D2[mode] if band == "d2" else PUBLISHED_D3[mode]
    label = "RESEARCH_LOG 'k 扫描的更正' §3 (D2)" if band == "d2" else "RESEARCH_LOG D3 section §三 (D2+D3)"
    compared = mismatched = 0
    misses = []
    for k in grid:
        for arm, cells in (published.get(k) or {}).items():
            if arm == "trip":
                got_row = by.get((k, "ladder@k", "orig"))
                pairs = [(got_row["draws_that_ever_tripped"], cells)] if got_row else []
            else:
                got_row = by.get((k, arm if (arm != "ladder@0.60" or k != K) else "ladder@k", "orig"))
                pairs = list(zip((got_row[c] for c in COMPARED), cells, strict=True)) if got_row else []
            for value, text in pairs:
                if text is None:
                    continue
                compared += 1
                if cell(value, text) != text.lstrip("+"):
                    mismatched += 1
                    misses.append({"k": k, "arm": arm, "published": text, "now": cell(value, text)})
    if "running" in published and (K, "running", "orig") in by:
        for value, text in zip((by[(K, "running", "orig")][c] for c in COMPARED), published["running"], strict=True):
            if text is None:
                continue
            compared += 1
            if cell(value, text) != text:
                mismatched += 1
                misses.append({"k": K, "arm": "running", "published": text, "now": cell(value, text)})
    checks["published_cells"] = {"source": label, "compared": compared, "identical": compared - mismatched, "misses": misses}
    print(f"\noriginal arms vs {label}: {compared - mismatched}/{compared} cells identical at the printed precision")
    for miss in misses:
        print(f"  MISMATCH k={miss['k']:.2f} {miss['arm']}: published {miss['published']}  now {miss['now']}")
    if anchor_rows is not None:
        full = [(r, by.get((r["k"], r["arm"] if (r["arm"] != "ladder@0.60" or r["k"] != K) else "ladder@k", "orig")))
                for r in anchor_rows if r["series"] == band and r["k"] in grid]
        same = [all(mine[c] == ref[c] for c in FULL) for ref, mine in full if mine is not None]
        checks["kgrid_full_precision"] = {"rows": len(same), "identical": sum(same)}
        print(f"original arms vs the archived kgrid ({band}) at full precision: {sum(same)}/{len(same)} rows identical")

    # the table
    print(f"\n{mode}: q95(USDT) / P(USDT>70%) / CAGR median; factor {factor:.4f} ({factor_date}); holds = q95(USDT) >= -70%")
    print(f"{'k':>6} {'arm':>12} " + " ".join(f"{d:>26}" for d in drifts) + f" {'d q95 (h-o)':>12} {'d CAGR (h-o)':>13} {'holds':>12}")

    def fmt(r: dict[str, Any]) -> str:
        return f"{r['q95_usdt']:.1%} / {r['p_past_70_usdt']:.1%} / {r['cagr_median']:.1%}"

    for k in grid:
        for arm in ("ladder@k", "running"):
            got = [by.get((k, arm, d)) for d in drifts]
            if not any(got):
                continue
            o, h = by.get((k, arm, "orig")), by.get((k, arm, "honest"))
            delta = (f" {(h['q95_usdt'] - o['q95_usdt']) * 100:>+10.1f}pp {(h['cagr_median'] - o['cagr_median']) * 100:>+11.1f}pp"
                     if o and h else f" {'':>12} {'':>13}")
            print(f"{k:>6.2f} {arm:>12} " + " ".join(f"{fmt(r) if r else '-':>26}" for r in got) + delta
                  + f" {'/'.join(('YES' if r['holds_the_usdt_budget'] else 'no') if r else '-' for r in got):>12}")

    summary: dict[str, Any] = {}
    print("\nwhere q95(USDT) reaches -70%, p32h.crossing along k (linear between the two grid points that bracket it):")
    for which in drifts:
        family = [r for r in rows if r["arm"] == "ladder@k" and r["drift"] == which]
        grid_holds = [r["k"] for r in sorted(family, key=lambda r: -r["k"]) if r["holds_the_usdt_budget"]]
        cross = p32h.crossing(family, -DECLARED_BUDGET)
        summary[which] = {"first_grid_k": grid_holds[0] if grid_holds else None, "interpolated": cross}
        text = "not within the grid" if cross is None else f"k ~ {cross[0]:.4f}, CAGR ~ {cross[1]:.1%}"
        print(f"  ladder@k {which:>6}: first grid k that holds {grid_holds[0] if grid_holds else '-'}; {text}")
    if "orig" in summary and summary["orig"]["interpolated"] is not None:
        mine = f"{summary['orig']['interpolated'][0]:.4f}"
        checks["crossing_vs_published"] = {"published": PUBLISHED_CROSSING[band][mode], "now": mine}
        print(f"  original arm's crossing vs published ({band}): {PUBLISHED_CROSSING[band][mode]} -> {mine}")
    for which in drifts:
        cross = summary[which]["interpolated"]
        if (K, "running", which) in by and cross is not None:
            base = by[(K, "running", which)]["cagr_median"]
            print(f"  cost vs running ({which}): {(cross[1] - base) * 100:+.1f}pp of CAGR ({cross[1] / base:.2f}x)")

    payload = {
        "mode": mode, "band": band, "store": store, "store_0923": STORE_0923 if store == "0923" else None,
        "draws": draws, "seed": SEED, "block": BLOCK, "k_grid": list(grid), "end_exclusive": END,
        "bars": PUBLISHED_BARS[mode], "honest_sharpe_target": target, "evidence": EVIDENCE.name,
        "drifts": drifts, "controls": not args.no_controls, "prop_keep": keep if "prop" in drifts else None,
        "usdt_share_at_peak": share, "usdt_factor": factor, "usdt_factor_date": factor_date,
        "static_universe": list(p32h.STATIC_P32G) if mode == "static" else None,
        "drift": {f"{k:.2f}": v for k, v in drift.items()}, "rows": rows, "checks": checks, "summary": summary,
    }
    grid_tag = "" if grid == K_DEFAULT else "-k" + "_".join(f"{k:.3g}" for k in grid)
    drift_tag = "" if drifts == ["orig", "honest"] else "-" + "+".join(drifts)
    out = Path(f"scratchpad/p32i-{mode}-{band}-store{store}-f{factor_date}{drift_tag}{'-nc' if args.no_controls else ''}{grid_tag}-{draws}.json")
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
