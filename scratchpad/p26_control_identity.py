"""P26 CONTROL 1 broke.  This is what settled whether the harness was wrong or the control was.

The control, as pre-registered, said: at capital 0 with guards off, net Sharpe must be identical
across all seven `vol_target` values, because the backtest is scale-free.  It came out with a spread
of 0.133, and the pre-registration said that voids the run.

It does not.  The control was mis-specified, by me, and the mistake is worth keeping because it is an
easy one: the identity measured on 2026-09-04 is about scaling a FIXED weight frame by k, and changing
`vol_target` is not that operation.  `max_weight`, `max_gross` and the two no-trade bands live INSIDE
the portfolio construction and are absolute or relative thresholds that do not scale with the weights,
so a different vol target produces a differently-SHAPED path rather than a rescaled one.  Turning off
the book-guard replay does not remove them: they were already baked into the weights before
`run_backtest` ever saw the frame.

Measured here, in the order the question has to be asked:

  A. the identity as 2026-09-04 stated it - one frame, scaled - holds EXACTLY (1.8227423775 at every
     multiplier), so `run_backtest` is not the problem;
  B. vol_target 0.15 -> 0.30 takes symbol-bars pinned at the 0.15 per-symbol cap from 2,113 to 21,710
     and gross mean 0.486 -> 0.890, so the caps bind on an order of magnitude more of the panel;
  C. the ratio w(0.30)/w(0.15) is not 2.0 anywhere near everywhere - it ranges over [-1851, +1738],
     because the no-trade band makes the two paths take different rebalancing DECISIONS, so a weight
     can even sit opposite in sign between them.

Conclusion: CONTROL 1 as written could never have passed, for any correct implementation.  A is the
control it should have been, and it passes.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(ROOT, "", "1h", "pit")
    panel = _load(ROOT, chosen, "1h", None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    weights, _c, _p = build_model(registry, profile).evaluate(panel, membership)

    print("A. the identity as 2026-09-04 measured it: one weight frame, scaled")
    for k in (1.0, 1.5, 2.0, 3.0):
        s = run_backtest(panel, weights * k, cost).summary()["annualized_sharpe"]
        print(f"   weights x {k:.1f}  net Sharpe {s:.10f}")

    print("\nB. what changing vol_target actually changes: the shape, via caps and bands")
    for vt in (0.15, 0.30):
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = vt
        w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
        at_cap = (w.abs() >= float(profile["portfolio"]["max_weight"]) - 1e-12).to_numpy().sum()
        gross = w.abs().sum(axis=1)
        print(
            f"   vol_target {vt:.2f}: mean |w| {w.abs().to_numpy().mean():.5f}  "
            f"symbol-bars at the 0.15 cap {at_cap:,}  gross mean {gross.mean():.3f} max {gross.max():.3f}"
        )

    print("\nC. is B's difference a pure rescale of A?  If it were, the ratio would be constant.")
    frames = {}
    for vt in (0.15, 0.30):
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = vt
        frames[vt], _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    ratio = (frames[0.30] / frames[0.15]).replace([float("inf"), float("-inf")], float("nan")).stack().dropna()
    print(f"   w(0.30)/w(0.15) over {len(ratio):,} symbol-bars: min {ratio.min():.4f} max {ratio.max():.4f}")
    print(f"   a pure rescale would give exactly 2.0000 everywhere; spread = {ratio.max() - ratio.min():.4f}")
    print(f"\nD. cost model used: {CostModel(turnover_bps=cost.turnover_bps, use_funding=cost.use_funding)}")


if __name__ == "__main__":
    main()
