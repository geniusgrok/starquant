"""P32: the vol-target ladder priced under the OPERATOR'S criterion - absolute return, not Sharpe.

NOT pre-registered, and the first version of this docstring said it was.  It claimed "PRE-REGISTERED
before it ran (RESEARCH_LOG entry of the same date)"; there is no 2026-09-14 entry in RESEARCH_LOG and
no occurrence of "P32" anywhere in docs/ or config/.  The grid and the reading WERE written before the
run - in the session transcript, which is not a durable artefact and is not what this repository means
by pre-registration (P30/P31 both committed theirs first).  Corrected rather than deleted, because a
script that certifies its own provenance is exactly the thing the certificate is supposed to prevent.
Anything downstream must therefore NOT cite a pre-registered selection rule for this run.

Adopts nothing, writes no config, no report and no ledger row; the output is a priced ladder.

WHY THIS IS NOT P26 AGAIN.  P26 (2026-09-08) swept the same k grid and read `annualized_sharpe`,
finding argmax 0.15 at every capital.  Under a RETURN criterion that table says something different
and P26 never printed it: net return is roughly linear in k while Sharpe decays a few percent, so
the argmax of return is the largest k that survives the risk constraints.  This run prints return,
drawdown and the ruin diagnostics P26 did not.

WHY IT IS NOT THE ADOPTION BOOTSTRAP AGAIN.  `vol_target_drawdown_bootstrap.py` scored
`model.book_names[0]` - the MAIN book alone.  The book that trades is main + flow_short + exits +
book guards, and it runs at 0.842x main's ex-ante vol (measured live 2026-09-13).  So the 50%
budget was priced on a book that is not the one at risk.  This run scores the registry book.

GRID: reuses the bootstrap's already-declared TARGETS.  No new k values are invented, because
inventing them after seeing P26's curve is exactly the selection pollution D-039 makes us pay for.

THE ONE NON-NEGOTIABLE.  The operator has said the drawdown budget is re-negotiable.  Ruin is not:
any rung whose `liquidation_touches` > 0 or `min_margin_buffer` <= 1.0 is refused regardless of
return, and that refusal is not an opinion the operator can overrule with a bigger budget.

    python scratchpad/p32_k_ladder_under_return_criterion.py pit|static
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import ImpactModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, impact_model, load_registry
from starquant_shared.config import load_yaml

# Identical to vol_target_drawdown_bootstrap.TARGETS - reused, not re-chosen.
VOL_TARGETS = (0.15, 0.225, 0.30, 0.375, 0.45, 0.60, 0.75)
CAPITALS = (0.0, 100_000.0)  # 0 = today's 10.8k is indistinguishable from it (P26: 0.0075 Sharpe at 10k)
BLOCK, DRAWS, SEED = 168, 2000, 20260904  # same block/draws/seed as the adoption run, so q95 is comparable
ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")
INTERVAL = "1h"


def max_drawdown(net: np.ndarray) -> float:
    equity = np.cumprod(1.0 + net)
    return float((equity / np.maximum.accumulate(equity) - 1.0).min())


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(ROOT, _resolve_symbols(ROOT, "", INTERVAL, mode), INTERVAL, None, None, True)
    membership = _membership(ROOT, mode, panel, 0)
    costs_payload = load_yaml("config/costs.yaml")
    cost = cost_model(costs_payload, use_funding=True)
    template = impact_model(costs_payload, capital=0.0)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(pf.get("max_weight", 0.15)),
        max_gross=float(pf.get("max_gross", 2.0)),
        daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
    )

    weights_by_k = {}
    for k in VOL_TARGETS:
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = k
        w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
        weights_by_k[k] = apply_exits(w, panel.close, exits).weights if exits.enabled else w

    years = len(panel.close) / panel.bars_per_year
    rng = np.random.default_rng(SEED)
    rows = []
    print(f"[{mode}] registry book (main + flow_short + exits + guards)  bars={len(panel.close)}  years={years:.2f}")
    print(f"        weekly block bootstrap block={BLOCK}h draws={DRAWS} seed={SEED}\n")
    head = f"{'k':>6}{'CAGR':>9}{'ar.mean':>9}{'Sharpe':>8}{'IS MDD':>9}{'q95 MDD':>9}{'P<-50%':>8}{'P<-70%':>8}{'gross':>7}{'cap':>6}{'pause':>6}{'liq':>5}{'buf':>8}"
    print(head)
    for k in VOL_TARGETS:
        result = run_backtest(panel, weights_by_k[k], cost, guards=guards)
        s = result.summary()
        net = result.portfolio_net.to_numpy()
        cagr = (1.0 + s["net_return"]) ** (1.0 / years) - 1.0 if s["net_return"] > -1 else float("nan")
        armean = float(np.nanmean(net)) * panel.bars_per_year
        blocks = len(net) // BLOCK
        draws = np.empty(DRAWS)
        for d in range(DRAWS):
            starts = rng.integers(0, len(net) - BLOCK, size=blocks)
            draws[d] = max_drawdown(np.concatenate([net[st : st + BLOCK] for st in starts]))
        q95 = float(np.percentile(draws, 5))
        g = s["guards"]
        rows.append(
            {
                "vol_target": k, "cagr": cagr, "arith_mean_annual": armean,
                "annualized_sharpe": s["annualized_sharpe"], "in_sample_mdd": s["max_drawdown"],
                "q95_mdd": q95, "p_breach_50": float((draws <= -0.50).mean()),
                "p_breach_70": float((draws <= -0.70).mean()),
                "avg_abs_exposure": s["average_absolute_exposure"],
                "gross_capped_bars": g["gross_capped_bars"], "pause_bars": g["daily_loss_pause_bars"],
                "liquidation_touches": g["liquidation_touches"], "min_margin_buffer": g["min_margin_buffer"],
                "turnover_units": s["turnover_units"], "cost_share_of_gross": s["cost_share_of_gross"],
            }
        )
        r = rows[-1]
        print(
            f"{k:>6.3f}{cagr:>9.1%}{armean:>9.1%}{r['annualized_sharpe']:>8.3f}{r['in_sample_mdd']:>9.1%}"
            f"{q95:>9.1%}{r['p_breach_50']:>8.1%}{r['p_breach_70']:>8.1%}{r['avg_abs_exposure']:>7.3f}"
            f"{r['gross_capped_bars']:>6}{r['pause_bars']:>6}{r['liquidation_touches']:>5}"
            f"{r['min_margin_buffer']:>8.2f}"
        )

    print("\nIMPACT - net Sharpe / CAGR at the config's own 100k trigger point")
    print(f"{'k':>6}{'cap0 CAGR':>11}{'100k CAGR':>11}{'cap0 SR':>9}{'100k SR':>9}")
    for capital in (CAPITALS[1],):
        im = ImpactModel(capital=capital, coefficient=template.coefficient,
                         adv_window=template.adv_window, vol_window=template.vol_window)
        for i, k in enumerate(VOL_TARGETS):
            s2 = run_backtest(panel, weights_by_k[k], cost, guards=guards, impact=im).summary()
            c2 = (1.0 + s2["net_return"]) ** (1.0 / years) - 1.0 if s2["net_return"] > -1 else float("nan")
            rows[i][f"cagr_capital_{int(capital)}"] = c2
            rows[i][f"sharpe_capital_{int(capital)}"] = s2["annualized_sharpe"]
            print(f"{k:>6.3f}{rows[i]['cagr']:>11.1%}{c2:>11.1%}{rows[i]['annualized_sharpe']:>9.3f}{s2['annualized_sharpe']:>9.3f}")

    Path(f"scratchpad/p32-{mode}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\nwrote scratchpad/p32-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
