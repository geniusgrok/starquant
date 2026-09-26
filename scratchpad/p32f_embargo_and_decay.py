"""P32f: the two audit findings that are measurable without a decision.

1. HOW MUCH IS THE OPEN CPCV BOUNDARY WORTH?  `cpcv_splits`' docstring says the embargo should be
   sized by the model's FEATURE LOOKBACK (tsmom `max(horizons)` 720, `AlphaModel.warmup_bars` 1442)
   and the callers pass `embargo = purge = 50`, leaving ~670 contaminated bars in the training set of
   every "after" group - bars `cpcv_evaluate` then selects parameters on.  `fraction_negative` is one
   of D-020's four hard gates, so the contamination makes a gate easier to pass.  The boundary is
   recorded as OPEN because closing it means a pre-registered re-run that charges the trials ledger.
   This measures the SIZE of the effect without charging anything: same nets, same groups, embargo
   varied.  A diagnostic that writes no ledger row is free; `research validate` is not.

2. IS THE EDGE DECAYING, AND HOW FAST?  `signals/tsmom.py:7-11` states the edge is behavioural and
   "should be expected to decay", and no round has ever estimated the rate - while k just doubled.
   This reports the per-year Sharpe of the shipped book and the OLS trend through it, with the
   standard error, so "we cannot pin a half-life from five annual observations" is a measurement
   rather than an impression.

    python scratchpad/p32f_embargo_and_decay.py pit|static
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scratchpad")

from p32e_ruler_divergence import DATA, K

from starquant_alpha.backtest import run_backtest
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.cpcv import cpcv_evaluate, cpcv_splits
from starquant_alpha.validation.metrics import sharpe, yearly_breakdown
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_cmd import (
    _book_guards,
    _entry,
    _exit_params,
    _load,
    _membership,
    _model,
    _overlaid,
    _resolve_symbols,
)
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

INTERVAL = "1h"
# The grid the cited evidence ran: `crowding_window` on and off, everything else at the registry value.
GRID = {"crowding_window": [72, 0]}
EMBARGOS = (50, 720, 1442)


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = K
    panel = _load(DATA, _resolve_symbols(DATA, "", INTERVAL, mode), INTERVAL, None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    exits = _exit_params(tuned, True, INTERVAL)
    guards = _book_guards(tuned, True)
    base = _entry("tsmom", "config/alpha_registry.yaml", "", "")
    bpy = panel.bars_per_year

    nets: dict[str, object] = {}
    for value in GRID["crowding_window"]:
        combo = {**base.params, "crowding_window": value}
        model = _model(StrategyEntry(id="tsmom", params=combo), tuned, INTERVAL)
        weights, _c, _p = model.evaluate(panel, membership)
        result = run_backtest(panel, _overlaid(weights, panel.close, exits), cost, guards=guards)
        nets[param_key(combo)] = result.portfolio_net
    index = None
    for series in nets.values():
        index = series.index if index is None else index.intersection(series.index)
    nets = {key: series.reindex(index).fillna(0.0) for key, series in nets.items()}
    n_bars = len(index)

    out: dict[str, object] = {"mode": mode, "bars": n_bars, "grid": GRID}
    out["cpcv_by_embargo"] = {
        str(embargo): {
            key: value
            for key, value in cpcv_evaluate(
                nets, cpcv_splits(n_bars, n_groups=6, n_test_groups=2, purge=50, embargo=embargo), bpy
            ).items()
            if key != "chosen"
        }
        for embargo in EMBARGOS
    }

    # 2. decay.  The shipped book (main + flow_short + exits + guards), per calendar year.
    registry = load_registry(Path("config/alpha_registry.yaml"))
    w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    book = run_backtest(panel, _overlaid(w, panel.close, exits), cost, guards=guards).portfolio_net
    years = yearly_breakdown(book, bpy)
    whole = [(int(y), v["sharpe"], v["bars"]) for y, v in years.items() if v["sharpe"] is not None and v["bars"] > bpy / 2]
    xs = np.array([y for y, _s, _b in whole], dtype=float)
    ys = np.array([s for _y, s, _b in whole], dtype=float)
    slope = intercept = stderr = None
    if len(xs) >= 3:
        slope, intercept = np.polyfit(xs, ys, 1)
        residual = ys - (slope * xs + intercept)
        dof = len(xs) - 2
        stderr = float(np.sqrt((residual @ residual) / dof / ((xs - xs.mean()) @ (xs - xs.mean()))))
    out["decay"] = {
        "per_year": {str(y): {"sharpe": s, "bars": b} for y, s, b in whole},
        "whole_years_used": len(whole),
        "ols_slope_sharpe_per_year": None if slope is None else float(slope),
        "ols_slope_stderr": stderr,
        "t_stat": None if slope is None or not stderr else float(slope / stderr),
        "first_half_sharpe": sharpe(book.iloc[: len(book) // 2], bpy),
        "second_half_sharpe": sharpe(book.iloc[len(book) // 2 :], bpy),
    }
    print(json.dumps(out, indent=1, default=float))
    Path(f"scratchpad/p32f-{mode}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
