"""P32h: `p32g`'s `k` sweep again, with the ladder stepped against the base that is actually in force.

THE DEFECT.  `p32g`'s ladder arm calls `p32d.ladder`, which hands `ladder_step` `base=K` - `p32e`'s module
constant, 0.60.  `LiveEngine._risk_ladder` hands it `self.config.portfolio.vol_target`: the `k` that is
running.  The rungs the shipped rule derives for a `k` are ABSOLUTE targets, `0.75k` and `0.50k`
(`p32d.rescaled`), and `rung_scalar(target, base)` is what turns a target into the multiplier on the book:

    live     0.75k / k    = 0.75     0.50k / k    = 0.50
    p32g     0.75k / 0.60 = 1.25k    0.50k / 0.60 = 0.833k

The same at k=0.60.  Below it `p32g` brakes K/k times harder than the rule it transcribes: 2.0x at 0.30
(the first rung takes the book to 0.375 where the rule asks for 0.75), 1.71x at 0.35, 1.2x at 0.50.
`p32d` and `p32f` only ever ran k=0.60, where the constant IS the base, so neither could show it.
`p32d.ladder_legacy`'s docstring already names this defect in the hand-written replay ("`standing / K`
divides by a module constant rather than by the base actually in force"); the swap to `ladder_step` fixed
the arithmetic and carried the constant over as an argument.

`p32d` and `p32g` are left exactly as they ran.  Their numbers are what RESEARCH_LOG 2026-09-22 and
`governance/reopen.yaml`'s `drawdown-budget-denominator` cite, and rewriting the evidence under a claim is
how a record stops being one - the reason `p32d` gives for leaving `p32c` alone.

ARMS, per `k`, all PAIRED on the one set of block starts `p32g` draws for that `k`:

* `ladder@0.60` - `p32g`'s ladder arm verbatim, through `p32d.ladder`.  A CONTROL, not a result: it must
  reproduce `PUBLISHED` cell for cell, or the data moved underneath and the next arm cannot be read as
  "only the base changed".
* `ladder@k` - the same rungs stepped with `base=k`: what the loop does at `vol_target = k`.
* `no ladder` - `p32g`'s, and a second control: with no rungs the base is never read.
* `running`, at k=0.60 only - `Policy().drawdown_ladder`, the total-equity rungs that trade today.  `p32g`
  priced its "about 45pp" against `p32f`'s 119.2%, a run on 2026-09-20 data with 96 fewer bars and so
  other block starts; here the baseline sits on the same draws as the arms it is subtracted from.

`EXTENDED` goes below `p32g`'s grid, which spans the two values the operator has declared (0.60 trading;
0.30 before it and `rollback_to`), because under the corrected base the first `k` that holds may not be on
that grid.  Its rows are measurements, not a proposal.

THE BAND is `p32d.panel_series`'s, deliberately: `combine_books` applies D2 (`flat_inside_band`) but not D3
(`band_entry_multiple`), where the live rebalancer applies both.  `p32g` measured on that D2-only band, so
keeping it is what lets `ladder@k` differ from the published arm in the base and in nothing else.
Whether `combine_books` gets D3 is a separate ruling.

THE STATIC UNIVERSE is pinned, which `p32g` did not do.  `p32g` resolved it from `universe.json`, and the
live loop rewrites that file every day; at 2026-09-23T01:00:21Z AKEUSDT entered - after `p32g` ran - so
`p32g static` stopped reproducing from the file.  Measured the same day: read from the file, its k=0.30
ladder row comes out -65.8% / 1.8% / 66.1% (q95 USDT / P / CAGR) against a published -66.8% / 2.0% /
64.7%; pinned to `STATIC_P32G`, all 12 published rows come back cell for cell.  Pit reads the membership
table, which has not moved since 2026-09-18.

`p32f`'s three caveats carry over unchanged and still all point the same way (the real tail is worse):
A-003's weekly block bootstrap, the USDT conversion's assumption that the loss lands in USDT, and CAGR
levels that only mean anything as differences.

WHAT THIS IS NOT.  `vol_target` is inside the construction fingerprint frozen to 2026-10-13.  This corrects
an input to that ruling; it moves nothing.

    python scratchpad/p32h_k_sweep_at_the_base_in_force.py pit|static [draws] [workers]
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scratchpad")

import p32d_ladder_bootstrap_pathwise as p32d
from p32d_ladder_bootstrap_pathwise import BLOCK, SEED, ladder, panel_series, rescaled
from p32e_ruler_divergence import K, drawdown_path
from p32f_usdt_denominated_budget import DECLARED_BUDGET
from p32g_which_k_holds_the_usdt_budget import K_GRID, USDT_SHARE_AT_PEAK

from starquant_alpha.overlays.ladder import ladder_step
from starquant_governance.policy import Policy

EXTENDED = (0.25, 0.20)

#: What `universe.json` held from 2026-09-22T01:00:21Z to 2026-09-23T01:00:21Z, order included - the live
#: record's `universe_update` for 2026-09-22 (`at_ms` 1790038821724, LINKUSDT left).  `p32g` ran inside
#: that window.  `p32f` (2026-09-20) did not: its static panel still had LINKUSDT.
STATIC_P32G = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT", "XRPUSDT", "HYPEUSDT", "DOGEUSDT", "BNBUSDT",
    "ENAUSDT", "NEARUSDT", "UNIUSDT", "SUIUSDT", "LSKUSDT", "TRUMPUSDT", "1000PEPEUSDT", "ADAUSDT",
)

#: `p32g`'s output as it printed, from the run RESEARCH_LOG 2026-09-22 cites (logs of 2026-09-23 02:15
#: and 02:17 +0800): (median total, q95 total, q95 USDT, P USDT>70, CAGR, trip%) for (ladder, no ladder).
#: Strings, so the control is compared at exactly the precision the evidence was published at.
PUBLISHED = {
    "pit": {
        0.60: (("-46.6", "-58.0", "-102.7", "89.5", "111.8", "100.0"), ("-51.6", "-70.8", "-125.3", "93.4", "124.7", "0.0")),
        0.50: (("-41.2", "-50.6", "-89.5", "61.6", "104.9", "99.9"), ("-45.4", "-64.6", "-114.2", "77.1", "115.9", "0.0")),
        0.45: (("-38.2", "-47.2", "-83.5", "40.2", "97.6", "99.5"), ("-42.0", "-60.4", "-106.9", "63.2", "106.9", "0.0")),
        0.40: (("-35.5", "-44.1", "-77.9", "21.3", "92.1", "96.3"), ("-38.7", "-56.3", "-99.5", "46.2", "99.8", "0.0")),
        0.35: (("-32.7", "-40.6", "-71.8", "7.4", "84.3", "86.0"), ("-34.8", "-50.8", "-89.9", "28.2", "89.3", "0.0")),
        0.30: (("-30.1", "-36.8", "-65.1", "0.9", "74.1", "68.5"), ("-30.6", "-45.3", "-80.1", "13.2", "77.2", "0.0")),
    },
    "static": {
        0.60: (("-45.7", "-56.6", "-100.1", "87.3", "110.4", "100.0"), ("-50.4", "-68.6", "-121.4", "91.2", "122.3", "0.0")),
        0.50: (("-40.7", "-50.3", "-89.0", "58.7", "99.3", "99.9"), ("-44.7", "-62.5", "-110.6", "75.2", "109.7", "0.0")),
        0.45: (("-37.9", "-46.6", "-82.4", "38.9", "93.8", "98.9"), ("-41.6", "-58.7", "-103.9", "60.6", "102.6", "0.0")),
        0.40: (("-35.7", "-43.9", "-77.7", "22.4", "81.5", "96.4"), ("-39.0", "-56.0", "-99.1", "47.0", "88.8", "0.0")),
        0.35: (("-33.2", "-40.8", "-72.2", "8.8", "75.2", "88.6"), ("-35.5", "-51.5", "-91.2", "32.0", "80.6", "0.0")),
        0.30: (("-31.1", "-37.8", "-66.8", "2.0", "64.7", "75.3"), ("-32.4", "-47.0", "-83.2", "19.5", "68.4", "0.0")),
    },
}
PUBLISHED_COLUMNS = ("median_total", "q95_total", "q95_usdt", "p_past_70_usdt", "cagr_median", "draws_that_ever_tripped")


def ladder_at_base(
    mark: np.ndarray, realised: np.ndarray, policy: Policy, ruler: str, base: float
) -> tuple[np.ndarray, np.ndarray]:
    """`p32d.ladder` with the one thing it hard-codes made an argument: `base`.

    Nothing else differs, and that is checked rather than claimed: `main` runs this at `base=K` against
    `p32d.ladder` on every panel and stops unless both outputs are bit-for-bit identical.
    """
    equity = hwm = 1.0
    path = peak = 1.0
    standing: dict = {}
    out = np.empty(len(mark))
    scalars = np.ones(len(mark))
    for t in range(len(mark)):
        drawdown = (equity / hwm - 1.0) if ruler == "mtm" else (path / peak - 1.0 if peak > 0 else 0.0)
        step = ladder_step(
            reading={"enforced": True, "value": drawdown},
            standing=standing,
            base=base,
            rungs=policy.drawdown_ladder,
            grace_cycles=policy.drawdown_grace_cycles,
            bar_open_ms=t,
            now="",
        )
        if step.standing is not None:
            standing = step.standing
        scalar = float(step.block["scalar"])
        scalars[t] = scalar
        out[t] = scalar * mark[t]
        path += scalar * realised[t] * equity
        equity *= 1.0 + out[t]
        peak = max(peak, path)
        hwm = max(hwm, equity)
    return out, scalars


def panel(mode: str, k: float) -> tuple[np.ndarray, np.ndarray]:
    """`p32d.panel_series`, with the static universe pinned to what `p32g` read.

    The pin goes where the lookup happens - `p32d`'s module namespace, which is where `panel_series`
    resolves `_resolve_symbols` - and the call is counted, so a pin that stops taking effect fails here
    instead of quietly reading the file again.
    """
    if mode != "static":
        return panel_series(mode, k=k)
    calls: list[str] = []

    def pinned(root: str, symbols: str, interval: str, universe_mode: str = "static") -> list[str]:
        calls.append(universe_mode)
        return list(STATIC_P32G)

    original = p32d._resolve_symbols
    p32d._resolve_symbols = pinned
    try:
        series = panel_series("static", k=k)
    finally:
        p32d._resolve_symbols = original
    if calls != ["static"]:
        raise RuntimeError(f"the static pin did not take ({calls!r}): panel_series no longer resolves through p32d")
    return series


def run_arm(task: dict[str, Any]) -> dict[str, Any]:
    """One arm over every draw - `p32g`'s loop, plus the paired cost and how long the brake is on."""
    mark, realised, starts, years = task["mark"], task["realised"], task["starts"], task["years"]
    policy = replace(Policy(), drawdown_ladder=tuple(task["rungs"]))
    base = task["base"]  # None: `p32d.ladder`, i.e. base=K, exactly as `p32g` ran it
    draws = len(starts)
    b, cagr, raw, throttled = np.empty(draws), np.empty(draws), np.empty(draws), np.empty(draws)
    trip = np.zeros(draws, dtype=bool)
    seen: set[float] = set()
    for d, row in enumerate(starts):
        m = np.concatenate([mark[s : s + BLOCK] for s in row])
        r = np.concatenate([realised[s : s + BLOCK] for s in row])
        stepped, scalars = ladder(m, r, policy, "mtm") if base is None else ladder_at_base(m, r, policy, "mtm", base)
        b[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
        cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
        raw[d] = np.prod(1.0 + m) ** (1.0 / years) - 1.0
        acting = scalars < 1.0 - 1e-9
        trip[d] = bool(acting.any())
        throttled[d] = float(acting.mean())
        seen.update(np.round(np.unique(scalars[acting]), 9).tolist())
    q95 = float(np.percentile(b, 5))
    q95_usdt = q95 * task["factor"]
    return {
        "k": task["k"],
        "arm": task["arm"],
        "base": K if base is None else base,
        "rungs": [list(r) for r in task["rungs"]],
        "acting_scalars": sorted(seen, reverse=True),
        "median_total": float(np.median(b)),
        "q95_total": q95,
        "q95_usdt": q95_usdt,
        "p_past_70_usdt": float((b * task["factor"] <= -DECLARED_BUDGET).mean()),
        "cagr_median": float(np.median(cagr)),
        # Paired: the same draw with and without this arm's brake.  Zero for `no ladder` by construction.
        "ladder_cost_median": float(np.median(raw - cagr)),
        "draws_that_ever_tripped": float(trip.mean()),
        "throttled_bars_median": float(np.median(throttled)),
        "holds_the_usdt_budget": bool(q95_usdt >= -DECLARED_BUDGET),
        "bars": len(mark),
    }


def crossing(rows: list[dict[str, Any]], target: float) -> tuple[float, float] | None:
    """(k, CAGR) where q95(USDT) first reaches `target` walking `k` down, linear between the two grid
    points that bracket it.  An interpolation on a 0.05 grid, and read as one.

    None unless two grid points bracket the target: a family whose shallowest-reaching `k` is already
    past it (or never gets there) has no point at that tail to compare, and extrapolating one would be
    inventing it.
    """
    rows = sorted(rows, key=lambda row: -row["k"])
    for hi, lo in pairwise(rows):
        if hi["q95_usdt"] < target <= lo["q95_usdt"]:
            t = (target - hi["q95_usdt"]) / (lo["q95_usdt"] - hi["q95_usdt"])
            return hi["k"] + t * (lo["k"] - hi["k"]), hi["cagr_median"] + t * (lo["cagr_median"] - hi["cagr_median"])
    return None


def main(mode: str, draws: int, workers: int) -> None:
    usdt_budget = DECLARED_BUDGET * USDT_SHARE_AT_PEAK
    factor = 1.0 / USDT_SHARE_AT_PEAK
    print(f"[{mode}] draws={draws}  USDT share at peak {USDT_SHARE_AT_PEAK:.4f} (2026-09-22, as p32g)")
    print(f"a {DECLARED_BUDGET:.0%} USDT budget is {usdt_budget:.2%} of total equity; drawdowns read {factor:.3f}x deeper in USDT")
    print("band: D2 only (combine_books passes flat_inside_band, not band_entry_multiple) - as p32g measured")
    if mode == "static":
        print(f"static universe pinned to p32g's ({len(STATIC_P32G)}): {', '.join(STATIC_P32G)}")

    pending = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for k in K_GRID + EXTENDED:
            mark, realised = panel(mode, k)
            n = len(mark)
            blocks = n // BLOCK
            years = (blocks * BLOCK) / 8760.0
            # `p32g`'s draw, verbatim: one seed and one set of block starts per k, shared by every arm.
            rng = np.random.default_rng(SEED)
            starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(draws)])
            rungs = tuple(rescaled(k, budget=usdt_budget))
            policy = replace(Policy(), drawdown_ladder=rungs)
            ref, ref_scalars = ladder(mark, realised, policy, "mtm")
            mine, mine_scalars = ladder_at_base(mark, realised, policy, "mtm", K)
            if not (np.array_equal(ref, mine) and np.array_equal(ref_scalars, mine_scalars)):
                raise RuntimeError(f"k={k}: ladder_at_base(base=K) is not p32d.ladder on this panel; the copy drifted")
            print(f"  k={k:.2f}: panel built, bars={n}; ladder_at_base(base=K) == p32d.ladder bit for bit", flush=True)
            arms: list[tuple[str, tuple, float | None]] = [
                ("ladder@0.60", rungs, None),
                ("ladder@k", rungs, k),
                ("no ladder", (), None),
            ]
            if k == K:
                arms.append(("running", tuple(Policy().drawdown_ladder), None))
            for arm, arm_rungs, base in arms:
                task = {"k": k, "arm": arm, "rungs": arm_rungs, "base": base, "mark": mark, "realised": realised,
                        "starts": starts, "years": years, "factor": factor}
                pending.append(pool.submit(run_arm, task))
        rows = [future.result() for future in pending]

    print(
        f"\n{'k':>6}{'arm':>13}{'scalars':>14}{'med tot':>9}{'q95 tot':>9}{'q95 usdt':>10}{'P usdt>70':>11}"
        f"{'CAGR':>9}{'cost':>8}{'trip%':>8}{'thr bars':>10}{'holds?':>8}"
    )
    for row in rows:
        scal = "/".join(f"{s:.4g}" for s in row["acting_scalars"]) or "-"
        mark_ext = "*" if row["k"] in EXTENDED else " "
        print(
            f"{row['k']:>5.2f}{mark_ext}{row['arm']:>13}{scal:>14}{row['median_total']:>9.1%}{row['q95_total']:>9.1%}"
            f"{row['q95_usdt']:>10.1%}{row['p_past_70_usdt']:>11.1%}{row['cagr_median']:>9.1%}"
            f"{row['ladder_cost_median']:>8.2%}{row['draws_that_ever_tripped']:>8.1%}"
            f"{row['throttled_bars_median']:>10.1%}{('YES' if row['holds_the_usdt_budget'] else 'no'):>8}"
        )
    print("  * EXTENDED: below p32g's grid; scalars are the multipliers the rungs actually applied")

    by = {(row["k"], row["arm"]): row for row in rows}
    checks: dict[str, Any] = {}
    # 1. The controls against the published table, at the precision it was printed.
    mismatches = []
    for k, (lad, bare) in PUBLISHED[mode].items():
        for arm, published in (("ladder@0.60", lad), ("no ladder", bare)):
            got = tuple(f"{by[(k, arm)][col]:.1%}"[:-1] for col in PUBLISHED_COLUMNS)
            if got != published:
                mismatches.append({"k": k, "arm": arm, "published": published, "now": got})
    checks["controls_reproduce_p32g"] = not mismatches
    checks["control_mismatches"] = mismatches
    print(f"\ncontrols vs p32g's published table: {2 * len(PUBLISHED[mode]) - len(mismatches)}/{2 * len(PUBLISHED[mode])} rows identical")
    for miss in mismatches:
        print(f"  k={miss['k']:.2f} {miss['arm']}: published {miss['published']}  now {miss['now']}")
    # 2. The first trip happens before any scalar applies, so the base cannot move WHETHER a draw trips.
    same_trip = all(by[(k, "ladder@k")]["draws_that_ever_tripped"] == by[(k, "ladder@0.60")]["draws_that_ever_tripped"]
                    for k in K_GRID + EXTENDED)
    checks["trip_rate_independent_of_base"] = same_trip
    print(f"trip rate identical under both bases at every k (structural): {same_trip}")
    # 3. At k=K the two ladder arms are one computation.
    same_at_k = all(by[(K, "ladder@k")][c] == by[(K, "ladder@0.60")][c] for c in PUBLISHED_COLUMNS)
    checks["identical_at_k_060"] = same_at_k
    print(f"ladder@k == ladder@0.60 at k={K}: {same_at_k}")

    families = {arm: [row for row in rows if row["arm"] == arm] for arm in ("ladder@0.60", "ladder@k", "no ladder")}
    running = by[(K, "running")]
    summary: dict[str, Any] = {"running": {"q95_usdt": running["q95_usdt"], "cagr_median": running["cagr_median"]}}
    print(f"\nrunning today (k=0.60, total-equity rungs): q95 usdt {running['q95_usdt']:.1%}  CAGR {running['cagr_median']:.1%}")
    print("where q95(USDT) reaches -70% (interpolated along k):")
    summary["holds_at"] = {}
    for arm, family in families.items():
        grid = [row["k"] for row in sorted(family, key=lambda row: -row["k"]) if row["holds_the_usdt_budget"]]
        cross = crossing(family, -DECLARED_BUDGET)
        summary["holds_at"][arm] = {"first_grid_k": grid[0] if grid else None, "interpolated": cross}
        if cross is None:
            print(f"  {arm:>12}: not within the grid")
            continue
        cost = running["cagr_median"] - cross[1]
        print(
            f"  {arm:>12}: first grid k {grid[0] if grid else '-'}; k ~ {cross[0]:.3f}, CAGR ~ {cross[1]:.1%};"
            f" vs running {cost * 100:+.1f}pp ({cross[1] / running['cagr_median']:.2f}x)"
        )
    print("the ladder vs a smaller k with no ladder, at EQUAL q95(USDT):")
    summary["equal_tail"] = {}
    for arm in ("ladder@0.60", "ladder@k"):
        out = []
        for bare in sorted(families["no ladder"], key=lambda row: -row["k"]):
            cross = crossing(families[arm], bare["q95_usdt"])
            if cross is None:
                continue
            gain = cross[1] - bare["cagr_median"]
            out.append({"q95_usdt": bare["q95_usdt"], "bare_k": bare["k"], "bare_cagr": bare["cagr_median"],
                        "ladder_k": cross[0], "ladder_cagr": cross[1], "gain": gain})
            print(
                f"  {arm:>12} at {bare['q95_usdt']:.1%}: ladder k~{cross[0]:.3f} {cross[1]:.1%}"
                f"  vs  no ladder k={bare['k']:.2f} {bare['cagr_median']:.1%}  ->  {gain * 100:+.1f}pp"
            )
        summary["equal_tail"][arm] = out

    payload = {
        "mode": mode,
        "draws": draws,
        "usdt_share_at_peak": USDT_SHARE_AT_PEAK,
        "band": "D2 only: combine_books passes flat_inside_band, not band_entry_multiple",
        "static_universe": list(STATIC_P32G) if mode == "static" else None,
        "rows": rows,
        "checks": checks,
        "summary": summary,
    }
    Path(f"scratchpad/p32h-{mode}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32h-{mode}.json")


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "pit",
        int(sys.argv[2]) if len(sys.argv) > 2 else 2000,
        int(sys.argv[3]) if len(sys.argv) > 3 else 4,
    )
