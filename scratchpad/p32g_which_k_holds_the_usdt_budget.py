"""P32g: which `k` holds a 70% budget on the money that can actually trade?

`p32f` answered the question the 2026-09-20 ruling asked first - re-denominate the BUDGET to tradable
USDT, let the shipped rule re-derive the rungs - and the answer was that it buys nothing: about 13pp of
CAGR for a tail still past a total loss of the tradable money, breached in 94.5% of draws.  Its third
conclusion was that the rungs are not the lever, because the MEDIAN 5.6-year draw already gives back
51.6% of total equity, which is 96% of what can trade.  The remaining lever is `k`.

So this sweeps `k` and asks, for each one, whether q95 of the tradable drawdown lands inside -70%.

TWO ARMS PER `k`, and the second is the reason this is not just `p32f` in a loop:

* `ladder` - `k` with the USDT-denominated rungs the shipped rule derives for it.  Note what does and
  does not move with `k`: the LEVELS stay at -26.3% / -37.6%, because those are a property of the
  account's composition and of the declared budget, not of `k`; the TARGETS are `0.75k` and `0.50k`.
* `no ladder` - the same `k` with no rungs at all.  Without it the sweep cannot say whether a `k` that
  holds the budget holds it because the book is smaller or because the brake fires more often, and
  those two have very different costs.

`p32f`'s three caveats carry over unchanged and still all point the same way (the real tail is worse):
the weekly block bootstrap destroys multi-month regime structure (A-003); the USDT conversion assumes
the loss lands in USDT, which understates a joint BTC-and-book fall; and the CAGR levels are an
artifact of bootstrapping a leveraged crypto momentum book, so only differences mean anything.

WHAT THIS IS NOT.  `vol_target` is inside the construction fingerprint frozen to 2026-10-13; moving it
resets M-010, M-G06 and `realised_vol`.  This run produces an input to that ruling, not an action.

    python scratchpad/p32g_which_k_holds_the_usdt_budget.py pit|static [draws]
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scratchpad")

from p32d_ladder_bootstrap_pathwise import BLOCK, SEED, ladder, panel_series, rescaled
from p32e_ruler_divergence import drawdown_path
from p32f_usdt_denominated_budget import DECLARED_BUDGET
from p32f_usdt_denominated_budget import USDT_SHARE_AT_PEAK as SHARE_20260920

from starquant_governance.policy import Policy

#: Re-measured 2026-09-22: USDT peak 7,489.95 over total-equity peak 13,251.98.  `p32f` ran at
#: 0.537441 (6,647.18 / 12,368.22) two days earlier, so this moved **+5.16% in two days** - and that
#: is not drift to average away, it is the quantity's own behaviour.  The collateral line is nearly
#: static (5.25% of summed absolute equity moves, measured over 269 cycles), so every unit the book
#: earns lands in USDT and raises USDT's share of the account.  **The more the book makes, the
#: shallower the same total-equity drawdown reads in tradable terms.**
#:
#: So this is not a constant of the account and must not be treated as one.  It is pinned to a date
#: here rather than read from the live record, because a research script that reads live state gives
#: a different answer every time it runs and stops being reproducible.  The cost of pinning is that
#: it goes stale, which is why `p32f`'s value is kept beside it: the two together say how fast.
USDT_SHARE_AT_PEAK = 7_489.95 / 13_251.98

#: 0.60 is what trades (since 2026-09-13T19:00Z); 0.30 is what it was before, and what `rollback_to`
#: still points at, so the grid spans the two ends the operator has actually declared.
K_GRID = (0.60, 0.50, 0.45, 0.40, 0.35, 0.30)


def main(mode: str, draws: int) -> None:
    usdt_budget = DECLARED_BUDGET * USDT_SHARE_AT_PEAK
    factor = 1.0 / USDT_SHARE_AT_PEAK
    print(f"[{mode}] draws={draws}  USDT share at peak {USDT_SHARE_AT_PEAK:.4f} (2026-09-22)")
    print(f"  p32f ran at {SHARE_20260920:.4f} (2026-09-20); the share moved {USDT_SHARE_AT_PEAK / SHARE_20260920 - 1:+.2%}")
    print("  it rises as the book earns - every unit of profit settles in USDT and the collateral does not move")
    print(f"a {DECLARED_BUDGET:.0%} USDT budget is {usdt_budget:.2%} of total equity;")
    print(f"every drawdown below reads {factor:.3f}x deeper in USDT than on total equity")
    print(
        f"\n{'k':>6}{'arm':>10}{'rungs':>26}{'med tot':>9}{'q95 tot':>9}"
        f"{'q95 usdt':>10}{'P usdt>70':>11}{'CAGR':>9}{'trip%':>8}{'holds?':>8}"
    )
    out = []
    for k in K_GRID:
        mark, realised = panel_series(mode, k=k)
        n = len(mark)
        blocks = n // BLOCK
        years = (blocks * BLOCK) / 8760.0
        # One seed, one set of block starts, reused by every k and both arms: the comparison is PAIRED.
        rng = np.random.default_rng(SEED)
        starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(draws)])
        for arm, rungs in (("ladder", tuple(rescaled(k, budget=usdt_budget))), ("no ladder", ())):
            policy = replace(Policy(), drawdown_ladder=rungs)
            b = np.empty(draws)
            cagr = np.empty(draws)
            trip = np.zeros(draws, dtype=bool)
            for d, row in enumerate(starts):
                m = np.concatenate([mark[s : s + BLOCK] for s in row])
                r = np.concatenate([realised[s : s + BLOCK] for s in row])
                stepped, scalars = ladder(m, r, policy, "mtm")
                b[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
                cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
                trip[d] = bool((scalars < 1.0 - 1e-9).any())
            q95 = float(np.percentile(b, 5))
            q95_usdt = q95 * factor
            holds = q95_usdt >= -DECLARED_BUDGET
            row_out = {
                "k": k,
                "arm": arm,
                "rungs": list(map(list, rungs)),
                "median_total": float(np.median(b)),
                "q95_total": q95,
                "q95_usdt": q95_usdt,
                "p_past_70_usdt": float((b * factor <= -DECLARED_BUDGET).mean()),
                "cagr_median": float(np.median(cagr)),
                "draws_that_ever_tripped": float(trip.mean()),
                "holds_the_usdt_budget": holds,
                "bars": n,
            }
            out.append(row_out)
            rung_text = "/".join(f"{lvl:.0%}->{tgt:.2f}" for lvl, tgt in rungs) or "-"
            print(
                f"{k:>6.2f}{arm:>10}{rung_text:>26}{row_out['median_total']:>9.1%}{q95:>9.1%}"
                f"{q95_usdt:>10.1%}{row_out['p_past_70_usdt']:>11.1%}"
                f"{row_out['cagr_median']:>9.1%}{row_out['draws_that_ever_tripped']:>8.1%}"
                f"{('YES' if holds else 'no'):>8}"
            )
    Path(f"scratchpad/p32g-{mode}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32g-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit", int(sys.argv[2]) if len(sys.argv) > 2 else 2000)
