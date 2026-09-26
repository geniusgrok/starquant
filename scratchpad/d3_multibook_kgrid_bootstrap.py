"""The k sweep on two series of one book - banded with D2 alone, and with D2 + D3 (2026-09-23).

The series come from `d3_multibook_band_impact.py` (section C).  The D2-only series is what
`p32d.panel_series` produced before the fix, so the arms below reproduce the published sweeps on it
before anything else is read:

* `ladder@0.60` - `p32g`'s ladder arm, `p32d.ladder`, the base fixed at 0.60
* `ladder@k`    - `p32h`'s, `p32h.ladder_at_base` with the base in force, as the loop steps it
* `no ladder`   - both sweeps' control

On the D2-only series, `ladder@0.60` and `no ladder` must match `p32h.PUBLISHED` - `p32g`'s table as it
printed - at the precision it printed; the script prints the count.  `ladder@k` on that series is
`p32h`'s table, to compare by hand with PR #112's.  The D3 column is read only after both agree.
Paired throughout: one seed and one set of block starts per k, the same USDT share.  Nothing here is a
second implementation of the ladder - both steppers are imported, not copied.

    .venv/bin/python scratchpad/d3_multibook_kgrid_bootstrap.py pit|static [draws]
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p32d_ladder_bootstrap_pathwise import BLOCK, SEED, ladder, rescaled
from p32e_ruler_divergence import K, drawdown_path
from p32f_usdt_denominated_budget import DECLARED_BUDGET
from p32g_which_k_holds_the_usdt_budget import USDT_SHARE_AT_PEAK
from p32h_k_sweep_at_the_base_in_force import PUBLISHED, PUBLISHED_COLUMNS, ladder_at_base

from starquant_governance.policy import Policy

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scratchpad" / "d3_multibook_out"

MODE = sys.argv[1] if len(sys.argv) > 1 else "pit"
DRAWS = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
K_GRID = (0.60, 0.35, 0.30, 0.25)
ARMS = ("ladder@0.60", "ladder@k", "no ladder")


def run_arm(task: tuple[float, str, str]) -> dict:
    k, series, arm = task
    data = np.load(OUT / f"series-{MODE}.npz")
    mark, realised = data[f"k{k:.2f}_{series}_mark"], data[f"k{k:.2f}_{series}_realised"]
    n = len(mark)
    blocks = n // BLOCK
    years = (blocks * BLOCK) / 8760.0
    rng = np.random.default_rng(SEED)
    starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(DRAWS)])
    rungs = tuple(rescaled(k, budget=DECLARED_BUDGET * USDT_SHARE_AT_PEAK)) if arm != "no ladder" else ()
    policy = replace(Policy(), drawdown_ladder=rungs)
    drawdowns, cagr, tripped = np.empty(DRAWS), np.empty(DRAWS), np.zeros(DRAWS, dtype=bool)
    for d, row in enumerate(starts):
        m = np.concatenate([mark[s : s + BLOCK] for s in row])
        r = np.concatenate([realised[s : s + BLOCK] for s in row])
        if arm == "ladder@k":
            stepped, scalars = ladder_at_base(m, r, policy, "mtm", k)
        else:
            stepped, scalars = ladder(m, r, policy, "mtm")
        drawdowns[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
        cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
        tripped[d] = bool((scalars < 1.0 - 1e-9).any())
    q95 = float(np.percentile(drawdowns, 5))
    factor = 1.0 / USDT_SHARE_AT_PEAK  # `p32g`'s arithmetic exactly, so a draw on the line falls the same way
    return {
        "k": k,
        "series": series,
        "arm": arm,
        "bars": n,
        "median_total": float(np.median(drawdowns)),
        "q95_total": q95,
        "q95_usdt": q95 * factor,
        "p_past_70_usdt": float((drawdowns * factor <= -DECLARED_BUDGET).mean()),
        "cagr_median": float(np.median(cagr)),
        "draws_that_ever_tripped": float(tripped.mean()),
    }


def main() -> None:
    tasks = [(k, s, a) for k in K_GRID for s in ("d2", "d3") for a in ARMS]
    with ProcessPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(run_arm, tasks))
    by = {(r["k"], r["series"], r["arm"]): r for r in rows}
    print(f"{MODE}: draws={DRAWS} bars={rows[0]['bars']}")
    compared, matched = 0, 0
    for k, (with_ladder, without) in PUBLISHED[MODE].items():
        for arm, published in (("ladder@0.60", with_ladder), ("no ladder", without)):
            if (k, "d2", arm) not in by:
                continue
            compared += 1
            got = tuple(f"{by[(k, 'd2', arm)][col]:.1%}"[:-1] for col in PUBLISHED_COLUMNS)
            matched += got == published
            if got != published:
                print(f"  MISMATCH k={k:.2f} {arm}: published {published} now {got}")
    print(f"D2-only controls vs p32g as published: {matched}/{compared} rows identical")
    print(f"{'k':>5} {'arm':>12} {'band':>5} {'q95 tot':>8} {'q95 usdt':>9} {'P>70':>7} {'CAGR':>7} {'trip':>7}")
    for r in rows:
        print(f"{r['k']:>5.2f} {r['arm']:>12} {r['series']:>5} {r['q95_total']:>8.1%} {r['q95_usdt']:>9.1%} "
              f"{r['p_past_70_usdt']:>7.1%} {r['cagr_median']:>7.1%} {r['draws_that_ever_tripped']:>7.1%}")
    at_k060 = all(by[(K, s, "ladder@k")] == {**by[(K, s, "ladder@0.60")], "arm": "ladder@k"} for s in ("d2", "d3"))
    print(f"ladder@k == ladder@0.60 at k={K}: {at_k060}")
    (OUT / f"kgrid-{MODE}-{DRAWS}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
