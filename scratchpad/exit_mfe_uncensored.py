"""How many episodes would a take-profit at k fire on, measured WITHOUT the censoring the live tp=6 imposes.

Why this exists (2026-09-08).  `scratchpad/exit_reachability.py` reports the MFE distribution of the
episodes the LIVE setting produces, and the live setting includes `take_profit: 6.0`.  `episodes()`
segments on `sign(held)`, and a take-profit sets the weight to 0 - so every episode that reaches 6 sigma
ENDS there.  The MFE distribution is therefore structurally censored just above 6:

  - Downward (tp 3, 4, 5) the counts are valid: anything reaching 6 passed 3, 4 and 5 first, so the
    ranking is monotone and the censoring cannot hide a trigger.  This is the argument
    `docs/analysis/2026-09-07-exits-tail-endpoint.md` sec 2.2 relies on, and it holds.
  - Upward (tp 6.5, 7, 8, ...) the counts are NOT estimates of anything.  They only measure how far past
    6 sigma the close overshot on the single bar that triggered the exit.  Reading them as "tp=8 would
    fire 18 times" is reading an overshoot distribution as a reachability distribution.

So the loosening side has to be measured on a book that carries no take-profit at all.  `BASE` below is
the tp -> infinity endpoint (the live stop, no take-profit), which is exactly the counterfactual the
question is about.  Both segmentations are printed side by side so the size of the artifact is visible.

Still descriptive, still zero ledger: no `research` command, no report written, no trial recorded.
Limits inherited from `episodes()`: executed weights lag the decision bar by one, the entry reference is
the bar close rather than the venue VWAP, and episodes are still bounded by the model's own weight
changes and by the stop - which is what tp=infinity means, not a defect.

    python scratchpad/exit_mfe_uncensored.py pit|static [--root .starquant/data]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scratchpad.exit_reachability import episodes
from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits, daily_vol
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

LIVE = {"stop_loss": 6.0, "trailing_stop": 0.0, "take_profit": 6.0}
BASE = {"stop_loss": 6.0, "trailing_stop": 0.0, "take_profit": 0.0}  # the tp -> infinity endpoint
K_MFE = (3.0, 4.0, 5.0, 6.0, 6.5, 7.0, 8.0, 9.0, 10.0, 12.0)


def _segment(panel, weights, overlay: dict[str, float], cost: CostModel) -> pd.DataFrame:
    params = ExitParams.from_mapping({**overlay, "bars_per_day": 24})
    adjusted = apply_exits(weights, panel.close, params).weights if params.enabled else weights
    result = run_backtest(panel, adjusted, cost)
    held, net = result.weights, result.net
    close = panel.close.reindex(index=held.index, columns=held.columns)
    # the sigma unit is a property of the panel, not of the overlay: keep it identical across both books
    sigma = daily_vol(panel.close, ExitParams.from_mapping({**LIVE, "bars_per_day": 24}))
    sigma = sigma.reindex(index=held.index, columns=held.columns)
    listed = {s: int(np.argmax(panel.close[s].notna().to_numpy())) for s in held.columns}
    rows: list[dict[str, float]] = []
    for symbol in held.columns:
        if symbol not in net.columns:
            continue
        for row in episodes(held[symbol], net[symbol], close[symbol], sigma[symbol], listed.get(symbol, 0)):
            rows.append({**row, "symbol": symbol})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pit", "static"))
    parser.add_argument("--root", default=".starquant/data")
    parser.add_argument("--profile", default="config/live.demo.yaml")
    args = parser.parse_args()

    profile = load_yaml(args.profile)
    model, _ = build_model_from_profile(profile)
    costs = load_yaml("config/costs.yaml")
    cost = CostModel(
        turnover_bps=float(costs["taker_fee_bps"]) + float(costs["slippage_bps"]),
        use_funding=bool(costs.get("use_actual_funding", True)),
    )
    chosen = _resolve_symbols(args.root, "", "1h", args.mode)
    panel = _load(args.root, chosen, "1h", None, None, True)
    membership = _membership(args.root, args.mode, panel, 0)
    weights, _combined, _per = model.evaluate(panel, membership)

    live = _segment(panel, weights, LIVE, cost)
    base = _segment(panel, weights, BASE, cost)

    print(f"[{args.mode}] {len(panel.symbols)} symbols x {len(panel.index)} bars")
    print(f"  segmented on LIVE  (sl6 + tp6)      : {len(live):5d} episodes  <- censored above 6 sigma")
    print(f"  segmented on BASE  (sl6, no tp)     : {len(base):5d} episodes  <- the tp=infinity endpoint\n")

    for label, frame in (("LIVE (censored)", live), ("BASE (uncensored)", base)):
        v = frame["max_mfe"].to_numpy()
        q = np.percentile(v, [50, 90, 99])
        print(f"  {label:19} max_mfe  median {q[0]:5.2f}  p90 {q[1]:5.2f}  p99 {q[2]:5.2f}  max {v.max():6.2f}")

    print("\n  episodes a take-profit at k would fire on:")
    print(f"  {'tp':>5} {'LIVE (censored)':>18} {'BASE (uncensored)':>19} {'ratio':>8}")
    lv, bv = live["max_mfe"].to_numpy(), base["max_mfe"].to_numpy()
    for k in K_MFE:
        a, b = int((lv >= k).sum()), int((bv >= k).sum())
        print(f"  {k:>5g} {a:>18d} {b:>19d} {(b / a if a else float('nan')):>8.2f}")

    at6 = int((bv >= 6.0).sum())
    print(f"\n  on BASE, relative to tp=6 ({at6} episodes):")
    for k in K_MFE:
        if k <= 6.0:
            continue
        b = int((bv >= k).sum())
        print(f"    tp={k:<5g} keeps {b:5d} = {b / max(at6, 1) * 100:5.1f}% of tp6's triggers")


if __name__ == "__main__":
    main()
