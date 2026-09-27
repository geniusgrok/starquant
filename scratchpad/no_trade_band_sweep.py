"""What the no-trade band's relative arm buys and costs: turnover, cost drag, and order frequency.

The band's job is to stop the book paying 7 bps to chase a target it is already on.  Widening it
saves cost and loses tracking; the question this answers is the shape of that trade, not which
value to adopt.

D-033 is what makes a backtest the right place to measure it: the model's weights are *unbanded*
live, the rebalancer applies the band against the venue's real position, and
``apply_no_trade_band`` is that same position recursion.  So the banded weight frame here IS the
live position path, and the orders counted below are the orders the loop would have placed.

The model is evaluated ONCE (the band is post-hoc on the weight frame, not a model input), so the
ladder costs one backtest per rung rather than one full evaluation.

Stated limits.  ``CostModel`` charges a flat ``turnover_bps`` at any order size and models neither
impact nor ``max_participation``, so the cost column here ranks bands by turnover alone.  Narrowing
moves two things a flat charge cannot separate - it raises total turnover (more cost) while cutting
the size of each clip (less impact per unit) - so the sign of the correction under an impact-aware
model is not predictable from this table; see ``participation_capacity_sweep.py`` for the capital at
which that stops being academic.  And the live band was itself chosen on this data (P10 cell B), so
a run that finds the shipped value optimal is confirming, not independent.

Nothing here selects a value: that needs a rule written before the numbers, and a re-run of
`research validate` plus a registry pointer (P13).

No parameter search, no report, no trials ledger entry.

    python scratchpad/no_trade_band_sweep.py pit|static [rel_band,rel_band,...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.portfolio import apply_no_trade_band
from starquant_alpha.validation.walk_forward import param_key, walk_forward_evaluate, walk_forward_folds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
# absolute arm held at the profile's value throughout; only the relative arm moves
REL_BANDS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
FOLDS, MIN_TRAIN, PURGE = 5, 4000, 50


def order_stats(banded: pd.DataFrame) -> tuple[float, float]:
    """(orders per day across the book, median hours a symbol holds a weight before it moves)."""
    values = banded.to_numpy(dtype=float)
    live = ~np.isnan(values)
    filled = np.where(live, values, 0.0)
    moved = (np.diff(filled, axis=0) != 0.0) & live[1:] & live[:-1]
    per_bar = moved.sum(axis=1)
    orders_per_day = float(per_bar.mean()) * 24.0
    holds: list[int] = []
    for column in range(moved.shape[1]):
        idx = np.flatnonzero(moved[:, column])
        if len(idx) > 1:
            holds.extend(np.diff(idx).tolist())
    return orders_per_day, float(np.median(holds)) if holds else float("nan")


def main(mode: str, ladder: tuple[float, ...] = REL_BANDS) -> None:
    profile = load_yaml("config/live.demo.yaml")
    model, _registry = build_model_from_profile(profile)
    abs_band = float(profile["portfolio"]["no_trade_band"])
    live_rel = float(profile["portfolio"]["no_trade_rel_band"])
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

    # unbanded, exactly what the live loop's `targets()` hands the rebalancer (D-033)
    weights, _combined, _per = model.evaluate(panel, membership, band=False)
    years = len(panel.index) / panel.bars_per_year

    print(f"[{mode}] books={model.book_names} symbols={weights.shape[1]} bars={len(panel.index)} ({years:.2f}y)")
    print(f"       cost={cost.turnover_bps:.1f}bps/unit  abs_band={abs_band}  live rel_band={live_rel}\n")
    header = (
        f"{'rel_band':>9}{'turn/yr':>9}{'cost/yr':>9}{'cost%gr':>9}"
        f"{'Sharpe_g':>10}{'Sharpe_n':>10}{'OOS_n':>8}{'MDD':>8}{'ord/day':>9}{'hold_h':>8}"
    )
    print(header)
    rows = []
    folds = None
    for rel in ladder:
        banded = apply_no_trade_band(weights, abs_band, rel)
        result = run_backtest(panel, banded, cost, guards=guards)
        summary = result.summary()
        net = result.portfolio_net
        if folds is None:
            folds = walk_forward_folds(len(net), FOLDS, min_train=MIN_TRAIN, purge=PURGE)
        key = param_key({"no_trade_rel_band": rel})
        oos = walk_forward_evaluate({key: net}, {key: {"no_trade_rel_band": rel}}, folds, panel.bars_per_year)
        oos_sharpe = oos.summary(panel.bars_per_year).get("oos_sharpe")
        cost_yr = float(result.costs.sum().sum()) / years
        turn_yr = float(result.turnover.sum()) / years
        per_day, hold_h = order_stats(banded)
        rows.append(
            {
                "rel_band": rel,
                "turnover_per_year": turn_yr,
                "cost_per_year": cost_yr,
                "cost_share_of_gross": summary["cost_share_of_gross"],
                "sharpe_gross": summary["annualized_sharpe_gross"],
                "sharpe_net": summary["annualized_sharpe"],
                "oos_sharpe_net": oos_sharpe,
                "max_drawdown": summary["max_drawdown"],
                "orders_per_day": per_day,
                "median_hold_hours": hold_h,
            }
        )
        r = rows[-1]
        oos_txt = "n/a" if oos_sharpe is None else f"{oos_sharpe:.3f}"
        print(
            f"{rel:>9.2f}{turn_yr:>9.1f}{cost_yr:>9.2%}{r['cost_share_of_gross']:>9.1%}"
            f"{r['sharpe_gross']:>10.4f}{r['sharpe_net']:>10.4f}{oos_txt:>8}"
            f"{r['max_drawdown']:>8.1%}{per_day:>9.1f}{hold_h:>8.0f}"
        )
    tag = f"{min(ladder):g}-{max(ladder):g}x{len(ladder)}"
    Path(f"scratchpad/band-sweep-{mode}-{tag}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    rungs = tuple(float(x) for x in sys.argv[2].split(",")) if len(sys.argv) > 2 else REL_BANDS
    main(sys.argv[1] if len(sys.argv) > 1 else "pit", rungs)
