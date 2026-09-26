"""The drawdown a vol target actually implies, as a distribution rather than a sample minimum.

The in-sample maximum drawdown is the worst thing that happened once; sizing to it means roughly a coin
flip on breaching the budget.  This resamples weekly blocks of the realised net series to get the
distribution, and the q95 of THAT is what `config/live.demo.yaml` sizes against (P13, 2026-09-04).

Stated limit: weekly blocks preserve within-week autocorrelation and destroy multi-month regime
structure, so real bear markets are longer than anything drawn here and the q95 is optimistic.

The targets below are ABSOLUTE, not multiples of whatever the profile currently says, so this keeps
reproducing the adoption decision after the profile moves.  Fixed seed; no parameter search, no report,
no trials ledger entry.

    python scratchpad/vol_target_drawdown_bootstrap.py pit|static
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.portfolio import build_weights
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
TARGETS = (0.15, 0.225, 0.30, 0.375, 0.45, 0.60, 0.75)
BLOCK, DRAWS, SEED = 168, 2000, 20260904


def max_drawdown(net: np.ndarray) -> float:
    equity = np.cumprod(1.0 + net)
    return float((equity / np.maximum.accumulate(equity) - 1.0).min())


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    model, _ = build_model_from_profile(profile)
    params = model.portfolio
    costs = load_yaml("config/costs.yaml")
    cost = CostModel(
        turnover_bps=float(costs["taker_fee_bps"]) + float(costs["slippage_bps"]),
        use_funding=bool(costs.get("use_actual_funding", True)),
    )
    guards = BookGuardParams(
        max_weight=float(profile["portfolio"]["max_weight"]),
        max_gross=float(profile["portfolio"]["max_gross"]),
        daily_loss_pause=float(profile["guards"]["daily_loss_pause"]),
    )
    panel = _load(ROOT, _resolve_symbols(ROOT, "", "1h", mode), "1h", None, None, True)
    membership = _membership(ROOT, mode, panel, 0)
    conviction = model.book_targets(model.strategy_targets(panel, membership))[model.book_names[0]]

    rng = np.random.default_rng(SEED)
    print(f"[{mode}] weekly block bootstrap  block={BLOCK}h  draws={DRAWS}  seed={SEED}\n")
    header = (
        f"{'vol_target':>11}{'in-sample':>11}{'median':>9}{'q75':>9}{'q90':>9}{'q95':>9}{'worst':>9}{'P(<-50%)':>10}"
    )
    print(header)
    rows = []
    for target in TARGETS:
        weights = build_weights(conviction, panel.close, panel.bars_per_year, replace(params, vol_target=target))
        net = run_backtest(panel, weights, cost, guards=guards).portfolio_net.to_numpy()
        blocks = len(net) // BLOCK
        draws = np.empty(DRAWS)
        for draw in range(DRAWS):
            starts = rng.integers(0, len(net) - BLOCK, size=blocks)
            draws[draw] = max_drawdown(np.concatenate([net[start : start + BLOCK] for start in starts]))
        # drawdowns are negative, so the *worst* tail is the low percentile
        median, q75, q90, q95 = np.percentile(draws, [50, 25, 10, 5])
        breach = float((draws <= -0.50).mean())
        rows.append(
            {
                "vol_target": target,
                "in_sample": max_drawdown(net),
                "median": median,
                "q75": q75,
                "q90": q90,
                "q95": q95,
                "worst": float(draws.min()),
                "p_breach_50": breach,
            }
        )
        print(
            f"{target:>11.3f}{rows[-1]['in_sample']:>11.1%}{median:>9.1%}{q75:>9.1%}"
            f"{q90:>9.1%}{q95:>9.1%}{rows[-1]['worst']:>9.1%}{breach:>10.1%}"
        )
    Path(f"scratchpad/bootstrap-{mode}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
