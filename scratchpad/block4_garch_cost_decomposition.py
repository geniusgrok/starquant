"""P29 addendum: is the GARCH divisor's loss the extra turnover it buys, or worse timing as well?

The main harness measured A3 at -0.2732 paired Sharpe against A0 with turnover +29.6% on the
point-in-time universe.  Those two facts have two very different readings and the table cannot
separate them, so this re-prices the SAME two weight paths at zero turnover cost.  It is the check
P10 cell B needed and got - "the gain is not the cost saved, 91% of it is a timing change" - pointed
the other way.

Nothing new is searched here: same two arms, same panel, same pre-registration.  Writes nothing.
"""

from __future__ import annotations

import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.panel import interval_seconds
from starquant_alpha.portfolio import asset_vol
from starquant_alpha.validation.metrics import sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")
FOLDS, MIN_TRAIN = 5, 4000


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    model = build_model(load_registry(Path("config/alpha_registry.yaml")), profile)
    panel = _load(ROOT, _resolve_symbols(ROOT, "", "1h", "pit"), "1h", None, None, True)
    membership = _membership(ROOT, "pit", panel)
    charged = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    free = CostModel(turnover_bps=0.0, carry_bps_per_bar=0.0, use_funding=charged.use_funding)
    exits = ExitParams.from_mapping(
        {**(profile.get("exits") or {}), "bars_per_day": max(1, 86_400 // interval_seconds("1h"))}
    )
    base_params = model.portfolio
    garch_params = replace(base_params, vol_model="garch")
    support = asset_vol(panel.close, base_params, panel.bars_per_year).notna() & asset_vol(
        panel.close, garch_params, panel.bars_per_year
    ).notna()
    targets = {
        k: v.where(support.reindex_like(v))
        for k, v in model.strategy_targets(panel, membership).items()
    }

    rows = {}
    for name, tuned in (("A0 ewma-48", base_params), ("A3 garch", garch_params)):
        built = replace(model, portfolio=tuned).weights_from(targets, panel.close, panel.bars_per_year)
        weights = apply_exits(built, panel.close, exits).weights if exits.enabled else built
        rows[name] = {
            label: run_backtest(panel, weights, cost)
            for label, cost in (("charged", charged), ("free", free))
        }

    print(f"{'':<12}{'net Sharpe (7bps)':>20}{'gross Sharpe (0bps)':>22}{'turnover units':>18}")
    folded = {}
    for name, priced in rows.items():
        out = {}
        for label, result in priced.items():
            net = result.portfolio_net
            start = walk_forward_folds(len(net), FOLDS, min_train=MIN_TRAIN)[0].test_start
            out[label] = [
                float(sharpe(net.iloc[f.test_slice], panel.bars_per_year) or math.nan)
                for f in walk_forward_folds(len(net), FOLDS, min_train=MIN_TRAIN)
            ]
            out[f"{label}_oos"] = float(sharpe(net.iloc[start:], panel.bars_per_year) or math.nan)
        folded[name] = out
        print(
            f"{name:<12}{out['charged_oos']:>20.4f}{out['free_oos']:>22.4f}"
            f"{float(priced['charged'].turnover.sum()):>18,.1f}"
        )

    for label in ("charged", "free"):
        delta = [a - b for a, b in zip(folded["A3 garch"][label], folded["A0 ewma-48"][label], strict=True)]
        se = float(np.std(delta, ddof=1) / math.sqrt(len(delta)))
        print(f"paired dSharpe at {label:<8} {np.mean(delta):+.4f}  fold SE {se:.4f}  t {np.mean(delta) / se:+.2f}")
    charged_gap = folded["A3 garch"]["charged_oos"] - folded["A0 ewma-48"]["charged_oos"]
    free_gap = folded["A3 garch"]["free_oos"] - folded["A0 ewma-48"]["free_oos"]
    print(f"\nOOS gap net {charged_gap:+.4f}, gross {free_gap:+.4f} -> cost explains {1 - free_gap / charged_gap:.1%}")


if __name__ == "__main__":
    main()
