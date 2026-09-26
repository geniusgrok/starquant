"""backtest-guard audit 2026-09-08: how much return does the `open_to_close` convention discard?

`run_backtest`'s default scores PnL_{t+1} = w_t * (close_{t+1}/open_{t+1} - 1).  A position held
across a bar boundary really earns the gap open_{t+1}/close_t as well; the convention drops it,
symmetrically for strategy and benchmark, and the module docstring calls that conservative.
This measures the size and the sign of what is dropped, and re-scores the shipped book under
`close_to_close` (which does earn it).  Writes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "~/starquant")

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_alpha.validation.metrics import max_drawdown, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, cost_model, load_panel, load_registry
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
PROFILE = load_yaml("config/live.demo.yaml")
COSTS = load_yaml("config/costs.yaml")

table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
idx = pd.DatetimeIndex(table.index)
table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
store = KlineStore(ROOT)
stored = set(store.symbols("1h"))
symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
panel = load_panel(store, symbols, "1h", funding_store=FundingStore(ROOT))
membership = membership_at_bars(table, panel.index)

# --- how big is the gap itself, per symbol-bar ---------------------------------------------------
intrabar = np.log(panel.close / panel.open)
gap = np.log(panel.open / panel.close.shift(1))
both = intrabar.notna() & gap.notna()
i = intrabar.where(both).to_numpy(dtype=float)
g = gap.where(both).to_numpy(dtype=float)
mask = np.isfinite(i) & np.isfinite(g)
print(f"symbol-bars compared: {int(mask.sum()):,}")
print(f"mean |intrabar log move| : {np.abs(i[mask]).mean() * 1e4:8.2f} bps")
print(f"mean |gap log move|      : {np.abs(g[mask]).mean() * 1e4:8.2f} bps"
      f"   ({np.abs(g[mask]).mean() / np.abs(i[mask]).mean() * 100:.2f}% of the intrabar move)")
print(f"share of total absolute move carried by the gap: "
      f"{np.abs(g[mask]).sum() / (np.abs(g[mask]).sum() + np.abs(i[mask]).sum()) * 100:.2f}%")
print(f"corr(gap, next intrabar) : {np.corrcoef(g[mask], i[mask])[0, 1]:+.4f}")

# --- re-score the shipped book under both conventions --------------------------------------------
registry = load_registry(Path("config/alpha_registry.yaml"))
model = build_model(registry, PROFILE)
cost = cost_model(COSTS, use_funding=True)
bpy = panel.bars_per_year
weights, _c, _p = model.evaluate(panel, membership)
exits = ExitParams.from_mapping({**(PROFILE.get("exits") or {}), "bars_per_day": max(1, 86_400 // interval_seconds("1h"))})
guards = BookGuardParams(
    max_weight=float(PROFILE["portfolio"]["max_weight"]),
    max_gross=float(PROFILE["portfolio"]["max_gross"]),
    daily_loss_pause=float(PROFILE["guards"]["daily_loss_pause"]),
)
w = apply_exits(weights, panel.close, exits).weights

folds = None
print(f"\n{'convention':<16} {'full Sh':>8} {'OOS Sh':>8} {'OOS MDD':>9} {'net return':>12}")
for execution in ("open_to_close", "close_to_close"):
    res = run_backtest(panel, w, cost, execution=execution, guards=guards)
    net = res.portfolio_net
    if folds is None:
        folds = walk_forward_folds(len(net), 5, min_train=4000, purge=50)
    oos = pd.concat([net.iloc[f.test_slice] for f in folds])
    s = res.summary()
    print(f"{execution:<16} {s['annualized_sharpe']:>8.4f} {sharpe(oos, bpy):>8.4f}"
          f" {max_drawdown(oos):>9.4f} {s['net_return']:>12.2f}")
