"""P32f: what the de-escalation ladder becomes when the budget is declared in TRADABLE USDT.

The operator ruled on 2026-09-20 that the drawdown they are budgeting is the tradable money's, not the
account's.  `Policy.drawdown_ladder` is not a set of numbers someone chose - it is the shipped rule
transcribed, `deescalate_at = 0.70 * budget` and `rollback_at = budget` - so the ruling does not edit
two thresholds, it re-denominates the ONE parameter they are derived from, and the rungs follow.

`p32d` is left exactly as it ran: its numbers are what D-035 cites, and rewriting the evidence under a
claim is how a record stops being one (the reason `p32d` itself gives for not touching `p32c`).  This
imports its ladder replay and its panel, and adds one arm.

THE CONVERSION, and its one assumption.  The backtest's equity is the equity positions are sized off,
which live is TOTAL equity - the backtest models no collateral at all (RISK-G11).  A loss of L reads as
L/E_peak there and as L/U_peak to the operator, so a budget of 70% of USDT is a budget of 70% *
U_peak/E_peak in the units this replay works in.  On 2026-09-20 that factor is 6,647.18 / 12,368.22 =
0.5374, giving 37.62%.

The assumption is that the loss lands in USDT.  That is what settlement does, and the live record says
the collateral line barely participates: over the 269 cycles carrying both readings, 5.25% of the summed
absolute equity moves were collateral, whose whole range was 62.09 U (1.09% of its mean) while BTC's own
range over the same window was 7.28%.  Where it fails is a joint move - BTC down while the book is down -
and there the conversion UNDERSTATES the tradable drawdown, because E_peak falls too.  So the arm below
is the optimistic one, stacked on a block bootstrap that is already optimistic by construction (A-003).

    python scratchpad/p32f_usdt_denominated_budget.py pit|static [draws]
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
from p32e_ruler_divergence import K, drawdown_path

from starquant_governance.policy import Policy

#: Measured on the live record, 2026-09-20: `collateral.usdt_equity` peak over `equity` peak, each
#: series from its OWN high-water mark.  Not the latest ratio (0.5226) - the drawdowns being compared
#: are both measured from a peak, so the peaks are what convert them.  See
#: `risk_budget.usdt_drawdown_state.vs_total_equity`, which is this number's reciprocal.
USDT_SHARE_AT_PEAK = 6_647.18399227 / 12_368.22

#: The budget the operator declared on 2026-09-14, unchanged.  What changes is what it is 70% OF.
DECLARED_BUDGET = 0.70


def main(mode: str, draws: int) -> None:
    mark, realised = panel_series(mode)
    n = len(mark)
    blocks = n // BLOCK
    years = (blocks * BLOCK) / 8760.0
    rng = np.random.default_rng(SEED)
    starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(draws)])
    usdt_budget = DECLARED_BUDGET * USDT_SHARE_AT_PEAK
    factor = 1.0 / USDT_SHARE_AT_PEAK
    print(f"[{mode}] k={K} bars={n} blocks/draw={blocks} draws={draws}")
    print(f"USDT share at peak {USDT_SHARE_AT_PEAK:.4f}  ->  a {DECLARED_BUDGET:.0%} USDT budget is")
    print(f"  {usdt_budget:.2%} of total equity, and every drawdown below reads {factor:.3f}x deeper in USDT")
    arms = (
        ("equity (shipped)", tuple(rescaled(K)), DECLARED_BUDGET),
        ("usdt", tuple(rescaled(K, budget=usdt_budget)), usdt_budget),
    )
    print(
        f"\n{'budget denom':>18}{'rungs':>26}{'ruler':>10}"
        f"{'med tot':>9}{'q95 tot':>9}{'q95 usdt':>10}{'P tot>70':>10}{'P usdt>70':>11}"
        f"{'CAGR':>8}{'cost':>8}{'trip%':>8}"
    )
    out = []
    for name, rungs, budget in arms:
        policy = replace(Policy(), drawdown_ladder=rungs)
        for ruler in ("mtm", "realised"):
            b = np.empty(draws)
            cagr = np.empty(draws)
            raw = np.empty(draws)
            for d, row in enumerate(starts):
                m = np.concatenate([mark[s : s + BLOCK] for s in row])
                r = np.concatenate([realised[s : s + BLOCK] for s in row])
                stepped, _ = ladder(m, r, policy, ruler)
                b[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
                cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
                raw[d] = np.prod(1.0 + m) ** (1.0 / years) - 1.0
            q95 = float(np.percentile(b, 5))
            row_out = {
                "budget_denominator": name,
                "budget_in_total_units": budget,
                "rungs": list(map(list, rungs)),
                "ruler": ruler,
                "median_total": float(np.median(b)),
                "q95_total": q95,
                # The same tail restated in the unit the operator budgets in.  This is the number the
                # ruling is about: does a 70% USDT budget hold under a ladder calibrated for it?
                "q95_usdt": q95 * factor,
                # BOTH budgets, for both arms.  The shipped ladder was built so the first is small; the
                # question the ruling asks is what it leaves the second at, and an arm judged only by the
                # budget it was built for cannot answer that.
                "p_past_70_total": float((b <= -DECLARED_BUDGET).mean()),
                "p_past_70_usdt": float((b * factor <= -DECLARED_BUDGET).mean()),
                "cagr_median": float(np.median(cagr)),
                "cagr_cost_median": float(np.median(raw - cagr)),
                "cagr_cost_q90": float(np.percentile(raw - cagr, 90)),
                "draws_that_ever_tripped": float(np.mean(raw - cagr > 1e-9)),
            }
            out.append(row_out)
            rung_text = "/".join(f"{lvl:.0%}->{tgt:.2f}" for lvl, tgt in rungs)
            print(
                f"{name:>18}{rung_text:>26}{ruler:>10}{row_out['median_total']:>9.1%}{q95:>9.1%}"
                f"{row_out['q95_usdt']:>10.1%}{row_out['p_past_70_total']:>10.1%}"
                f"{row_out['p_past_70_usdt']:>11.1%}{row_out['cagr_median']:>8.1%}"
                f"{row_out['cagr_cost_median']:>8.2%}{row_out['draws_that_ever_tripped']:>8.1%}"
            )
    Path(f"scratchpad/p32f-{mode}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32f-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit", int(sys.argv[2]) if len(sys.argv) > 2 else 2000)
