"""backtest-guard audit 2026-09-08: score the book the LOOP holds, all four layers at once.

The registry's evidence pointer (tsmom-validation-20260906T093705Z) scores layer 1 alone:
tsmom, no flow_short sleeve, no exit overlay, no book-guard replay.  The live loop runs all
four.  Each layer has its own report, measured at a different time under a different
construction, and no artefact composes them.  This composes them, on one panel, in one run.

Writes nothing: no ledger, no report.  Nothing here is evidence; it is a measurement of how
far the cited number is from the book that trades.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "~/starquant")

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_alpha.validation.metrics import max_drawdown, newey_west_tstat, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, cost_model, load_panel, load_registry
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
INTERVAL = "1h"
PROFILE = load_yaml("config/live.demo.yaml")
COSTS = load_yaml("config/costs.yaml")

table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
idx = pd.DatetimeIndex(table.index)
table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
store = KlineStore(ROOT)
stored = set(store.symbols(INTERVAL))
symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
panel = load_panel(store, symbols, INTERVAL, funding_store=FundingStore(ROOT))
membership = membership_at_bars(table, panel.index)

registry = load_registry(Path("config/alpha_registry.yaml"))
model = build_model(registry, PROFILE)
print(f"registry books: {model.book_names}  entries: {[(e.id, e.book) for e in model.entries]}")
cost = cost_model(COSTS, use_funding=True)
bpy = panel.bars_per_year

weights, _c, _p = model.evaluate(panel, membership)
bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
exits = ExitParams.from_mapping({**(PROFILE.get("exits") or {}), "bars_per_day": bars_per_day})
guards = BookGuardParams(
    max_weight=float(PROFILE["portfolio"]["max_weight"]),
    max_gross=float(PROFILE["portfolio"]["max_gross"]),
    daily_loss_pause=float(PROFILE["guards"]["daily_loss_pause"]),
)
print(f"exits: {exits}")
print(f"guards: {guards}")

overlay = apply_exits(weights, panel.close, exits)
print(f"exit events: {overlay.summary()}")

cases = {
    "A  sleeve, no exits, no guards  (= overlay report baseline)": (weights, None),
    "B  sleeve + exits, no guards": (overlay.weights, None),
    "C  sleeve + guards, no exits": (weights, guards),
    "D  sleeve + exits + guards      (= the live book)": (overlay.weights, guards),
}

n_ref = None
folds = None
print(f"\n{'case':<52} {'full Sh':>8} {'OOS Sh':>8} {'NW t':>7} {'OOS MDD':>9} {'turnover':>9} {'exposure':>9}")
for name, (w, g) in cases.items():
    res = run_backtest(panel, w, cost, execution="open_to_close", guards=g)
    net = res.portfolio_net
    if folds is None:
        n_ref = len(net)
        folds = walk_forward_folds(n_ref, 5, min_train=4000, purge=50)
    assert len(net) == n_ref, f"{name}: {len(net)} bars vs {n_ref}"
    oos = pd.concat([net.iloc[f.test_slice] for f in folds])
    s = res.summary()
    print(
        f"{name:<52} {s['annualized_sharpe']:>8.4f} {sharpe(oos, bpy):>8.4f}"
        f" {newey_west_tstat(oos)['t_stat']:>7.3f} {max_drawdown(oos):>9.4f}"
        f" {s['turnover_units']:>9.1f} {s['average_absolute_exposure']:>9.4f}"
    )
    if g is not None:
        print(f"     guards: {s['guards']}")

print("\nregistry's cited evidence (tsmom alone, no sleeve/exits/guards): OOS 1.7662, full 1.8177, MDD -23.68%")
