"""Block 4 #42 (VWAP): what a perfect N-way split is worth, in the units the book is judged in.

Under the DL-C1 square-root law slicing one order into N equal children is not a new cost model, it
is the SAME model with a different constant:

    impact(Q)  = c * sigma * sqrt(Q/ADV) * Q
    N children = N * c * sigma * sqrt((Q/N)/ADV) * (Q/N) = impact(Q) / sqrt(N)

so a perfect N-way VWAP is arithmetically indistinguishable from running with ``coefficient/sqrt(N)``.
That identity is the whole reason this script exists instead of an execution layer: it prices the best
case an execution layer could ever reach (zero timing risk, zero information leakage, every child
filled at the arrival price) without writing one, and it prices it against the fact that
``coefficient`` is itself an E5 assumption this system cannot calibrate.

Same four layers `research validate` scores, same book as `impact_capacity_curve.py`, so the
`coefficient=1.0` column reproduces that table.  Writes nothing - no ledger row, no report, no config.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from starquant_alpha.backtest import ImpactModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, impact_model, load_registry
from starquant_shared.config import load_yaml

# 10,731 is this ledger's own mean equity (`vwap_participation_measurement.py`); the rest are the
# capacity curve's rungs so the two tables can be read side by side.
CAPITALS = (10_731.0, 100_000.0, 1_000_000.0, 10_000_000.0)
SLICES = (1, 2, 4, 10)
ROOT = os.environ.get("STARQUANT_DATA_ROOT", "~/starquant/.starquant/data")
INTERVAL = "1h"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(ROOT, "", INTERVAL, "pit")
    panel = _load(ROOT, chosen, INTERVAL, None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    model = build_model(registry, profile)
    costs_payload = load_yaml("config/costs.yaml")
    cost = cost_model(costs_payload, use_funding=True)
    weights, _c, _p = model.evaluate(panel, membership)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    if exits.enabled:
        weights = apply_exits(weights, panel.close, exits).weights
    portfolio = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(portfolio.get("max_weight", 0.15)),
        max_gross=float(portfolio.get("max_gross", 2.0)),
        daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
    )
    template: ImpactModel = impact_model(costs_payload, capital=0.0)
    flat = run_backtest(panel, weights, cost, guards=guards).summary()["annualized_sharpe"]
    print(f"flat (capital=0) net Sharpe = {flat:.4f}   coefficient={template.coefficient}")
    print()
    header = "  ".join(f"N={n:<2d} (c/{math.sqrt(n):.2f})" for n in SLICES)
    print(f"{'capital':>13}  {header}   {'best case recovered':>20}")
    for capital in CAPITALS:
        cells = []
        for slices in SLICES:
            impact = ImpactModel(
                capital=capital,
                coefficient=template.coefficient / math.sqrt(slices),
                adv_window=template.adv_window,
                vol_window=template.vol_window,
            )
            cells.append(run_backtest(panel, weights, cost, guards=guards, impact=impact).summary()["annualized_sharpe"])
        recovered = cells[SLICES.index(4)] - cells[0]
        print(f"{capital:>13,.0f}  " + "  ".join(f"{v:>13.4f}" for v in cells) + f"   {recovered:>+20.4f}")
    print()
    print("'best case recovered' = N=4 minus unsliced, i.e. the most a 4-way VWAP could ever buy back.")


if __name__ == "__main__":
    main()
