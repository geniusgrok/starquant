"""P26: the vol-target k under the DL-C1 impact model, by capital.  Pre-registered in RESEARCH_LOG.

Written before it ran; a correction is made here rather than in a second place.

`vol_target` has been a free parameter in every backtest this repository has produced, because the
cost model charges the same bps for any order size - an arithmetic property of the pricing, not a
finding about the world.  The impact model breaks that, so the argmax k becomes finite and there is
finally a capital at which the shipped 0.30 has to be re-derived rather than assumed.

**This run adopts nothing.**  Changing `vol_target` is a construction change: it belongs in batch
window #1, and it would reset M-010's 30-day clock, which has been running unbroken since
2026-09-04T15:02Z.  The output is a curve.

Two control rows, declared before the sweep because what they falsify is this measurement rather than
the strategy:

* capital 0, guards OFF - net Sharpe must be identical across all seven k, to the last digit.  If it
  is not, this harness is measuring a bug.
* capital 0, guards ON - Sharpe is ALLOWED to move with k, and that movement is the guards, not
  impact.  Measured on 2026-09-04: doubling the vol target made both guards reachable (355 capped
  bars, 36 paused bars on the point-in-time universe).  Without this row, impact would be credited
  with the guards' k-dependence.

Writes nothing: no ledger row, no report, no config.  Construction parameters do not enter
`param_key`, so the new cells are declared as prior-trials debt in RESEARCH_LOG, on D-039's precedent.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from starquant_alpha.backtest import ImpactModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, impact_model, load_registry
from starquant_shared.config import load_yaml

VOL_TARGETS = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
CAPITALS = (0.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0)
ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")
INTERVAL = "1h"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(ROOT, "", INTERVAL, "pit")
    panel = _load(ROOT, chosen, INTERVAL, None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    costs_payload = load_yaml("config/costs.yaml")
    cost = cost_model(costs_payload, use_funding=True)
    template = impact_model(costs_payload, capital=0.0)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    portfolio = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(portfolio.get("max_weight", 0.15)),
        max_gross=float(portfolio.get("max_gross", 2.0)),
        daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
    )

    weights_by_k = {}
    for k in VOL_TARGETS:
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = k
        weights, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
        weights_by_k[k] = apply_exits(weights, panel.close, exits).weights if exits.enabled else weights

    print("CONTROL 1 - capital 0, guards OFF: the scale-free identity, which must hold exactly")
    free = {k: run_backtest(panel, w, cost).summary()["annualized_sharpe"] for k, w in weights_by_k.items()}
    spread = max(free.values()) - min(free.values())
    for k, sharpe in free.items():
        print(f"  vol_target {k:.2f}  net Sharpe {sharpe:.10f}")
    print(f"  spread {spread:.2e} -> {'HOLDS' if spread < 1e-9 else 'BROKEN: this harness measures a bug'}\n")

    print("CONTROL 2 - capital 0, guards ON: k-dependence that is the guards, not impact")
    guarded = {k: run_backtest(panel, w, cost, guards=guards).summary() for k, w in weights_by_k.items()}
    for k, s in guarded.items():
        g = s["guards"]
        print(
            f"  vol_target {k:.2f}  net Sharpe {s['annualized_sharpe']:.4f}  "
            f"capped {g['gross_capped_bars']:>4}  paused {g['daily_loss_pause_bars']:>3}"
        )
    base_arg = max(guarded, key=lambda k: guarded[k]["annualized_sharpe"])
    print(f"  argmax k at capital 0 (guards on) = {base_arg:.2f}\n")

    print("SWEEP - guards on, impact on")
    header = "  " + "".join(f"{k:>11.2f}" for k in VOL_TARGETS)
    print(f"{'capital':>12}{header}   argmax")
    for capital in CAPITALS:
        impact = ImpactModel(
            capital=capital,
            coefficient=template.coefficient,
            adv_window=template.adv_window,
            vol_window=template.vol_window,
        )
        row = {
            k: run_backtest(panel, w, cost, guards=guards, impact=impact).summary()["annualized_sharpe"]
            for k, w in weights_by_k.items()
        }
        best = max(row, key=lambda k: row[k])
        print(f"{capital:>12,.0f}  " + "".join(f"{row[k]:>11.4f}" for k in VOL_TARGETS) + f"   {best:.2f}")


if __name__ == "__main__":
    main()
