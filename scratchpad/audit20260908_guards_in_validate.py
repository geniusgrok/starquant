"""backtest-guard audit 2026-09-08: does `research validate`'s missing guard replay change the number?

Reproduces the shipped tsmom configuration exactly as `research validate --universe pit` builds it
(registry params, live.demo.yaml portfolio, costs.yaml, funding on), then scores the SAME weights
twice: once the way `validate` does (no `guards=`) and once the way `backtest` does
(`guards=BookGuardParams(...)`).  Writes nothing: no ledger, no report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "~/starquant")

from starquant_alpha.backtest import run_backtest
from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.walk_forward import walk_forward_evaluate, walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import cost_model, load_panel, load_registry, portfolio_params
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
PROFILE = load_yaml("config/live.demo.yaml")
COSTS = load_yaml("config/costs.yaml")
INTERVAL = "1h"

table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
idx = pd.DatetimeIndex(table.index)
table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
store = KlineStore(ROOT)
stored = set(store.symbols(INTERVAL))
symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
print(f"pit union with 1h klines: {len(symbols)} symbols", flush=True)

panel = load_panel(store, symbols, INTERVAL, funding_store=FundingStore(ROOT))
membership = membership_at_bars(table, panel.index)
print(
    f"panel: {len(panel.index)} bars x {len(panel.symbols)} symbols ({panel.index[0]} -> {panel.index[-1]})",
    flush=True,
)

entry = next(e for e in load_registry(Path("config/alpha_registry.yaml")).strategies if e.id == "tsmom")
model = AlphaModel(
    entries=(StrategyEntry(id="tsmom", params=dict(entry.params)),),
    portfolio=portfolio_params(PROFILE),
    interval=INTERVAL,
    min_history_bars=int(PROFILE["portfolio"]["min_history_bars"]),
)
cost = cost_model(COSTS, use_funding=True)
print(f"cost: {cost}", flush=True)
print(f"portfolio: {model.portfolio}", flush=True)

weights, _c, _p = model.evaluate(panel, membership)
guards = BookGuardParams(
    max_weight=float(PROFILE["portfolio"]["max_weight"]),
    max_gross=float(PROFILE["portfolio"]["max_gross"]),
    daily_loss_pause=float(PROFILE["guards"]["daily_loss_pause"]),
)
print(f"guards: {guards}", flush=True)

off = run_backtest(panel, weights, cost, execution="open_to_close")
on = run_backtest(panel, weights, cost, execution="open_to_close", guards=guards)
bpy = panel.bars_per_year

for name, res in (("validate (no guards)", off), ("backtest (guards replayed)", on)):
    s = res.summary()
    print(f"\n--- {name} ---", flush=True)
    print(json.dumps({k: v for k, v in s.items() if k != "guards"}, indent=1))
    if "guards" in s:
        print("guards:", json.dumps(s["guards"]))

for name, res in (("validate (no guards)", off), ("backtest (guards replayed)", on)):
    net = res.portfolio_net.reset_index(drop=True)
    n = len(net)
    folds = walk_forward_folds(n, 5, min_train=min(4000, max(n // 2, 2)), purge=50)
    wf = walk_forward_evaluate({"one": net}, {"one": dict(entry.params)}, folds, bpy)
    sm = wf.summary(bpy)
    print(
        f"\n[{name}] walk-forward OOS sharpe {sm['oos_sharpe']:.4f}  NW t {sm['oos_t_stat']:.4f}"
        f"  folds {[None if f is None else round(f, 3) for f in sm['fold_sharpes']]}"
        f"  MDD {sm['oos_max_drawdown']:.4f}",
        flush=True,
    )

d = on.summary()["annualized_sharpe"] - off.summary()["annualized_sharpe"]
print(f"\nfull-sample sharpe delta (guards on - off): {d:+.4f}")
print(f"full-sample MDD: off {off.summary()['max_drawdown']:.4f} -> on {on.summary()['max_drawdown']:.4f}")
gross_off = off.weights.abs().sum(axis=1)
print(
    f"gross above max_gross in the UNGUARDED book: {int((gross_off > guards.max_gross + 1e-9).sum())} bars"
    f" of {len(gross_off)} (max gross {gross_off.max():.4f})"
)
