"""backtest-guard audit 2026-09-08: re-score the live book at the cost and convention live has shown.

Two inputs the backtest assumes and the loop has now measured:
  * slippage.  costs.yaml charges 2.0 bps.  101 filled demo orders (.starquant/live/trades.jsonl,
    fill vs the plan price) give a mean of 5.60 bps, 95% CI [2.01, 9.19], notional-weighted 5.52.
  * the execution convention.  `open_to_close` drops the close->open gap on every held bar;
    live holds through it.  `close_to_close` is the convention that earns it.

Nothing here is evidence: the fills are DEMO fills, n=101, over four days, and the CI's lower
bound touches the modelled value.  It is a sensitivity, run at the point estimate and at the
CI bounds.  Writes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "~/starquant")

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_alpha.validation.metrics import max_drawdown, newey_west_tstat, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, load_panel, load_registry
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
PROFILE = load_yaml("config/live.demo.yaml")
COSTS = load_yaml("config/costs.yaml")
FEE = float(COSTS["taker_fee_bps"])  # 5.0

table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
idx = pd.DatetimeIndex(table.index)
table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
store = KlineStore(ROOT)
stored = set(store.symbols("1h"))
symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
panel = load_panel(store, symbols, "1h", funding_store=FundingStore(ROOT))
membership = membership_at_bars(table, panel.index)

registry = load_registry(Path("config/alpha_registry.yaml"))
model = build_model(registry, PROFILE)
bpy = panel.bars_per_year
weights, _c, _p = model.evaluate(panel, membership)
exits = ExitParams.from_mapping(
    {**(PROFILE.get("exits") or {}), "bars_per_day": max(1, 86_400 // interval_seconds("1h"))}
)
guards = BookGuardParams(
    max_weight=float(PROFILE["portfolio"]["max_weight"]),
    max_gross=float(PROFILE["portfolio"]["max_gross"]),
    daily_loss_pause=float(PROFILE["guards"]["daily_loss_pause"]),
)
w = apply_exits(weights, panel.close, exits).weights

scenarios = [
    ("shipped: model 2.0 bps slip, open_to_close", FEE + 2.0, "open_to_close"),
    ("measured: 5.5 bps slip, open_to_close", FEE + 5.5, "open_to_close"),
    ("measured slip + close_to_close", FEE + 5.5, "close_to_close"),
    ("CI low  2.0 bps + close_to_close", FEE + 2.0, "close_to_close"),
    ("CI high 9.2 bps + close_to_close", FEE + 9.2, "close_to_close"),
    ("D-020 stress x2 (14.0 bps), open_to_close", 14.0, "open_to_close"),
]

folds = None
print(f"{'scenario':<44} {'bps':>6} {'full Sh':>8} {'OOS Sh':>8} {'NW t':>7} {'OOS MDD':>9} {'cost/gross':>11}")
for label, bps, execution in scenarios:
    res = run_backtest(
        panel, w, CostModel(turnover_bps=bps, carry_bps_per_bar=0.0, use_funding=True),
        execution=execution, guards=guards,
    )
    net = res.portfolio_net
    if folds is None:
        folds = walk_forward_folds(len(net), 5, min_train=4000, purge=50)
    oos = pd.concat([net.iloc[f.test_slice] for f in folds])
    s = res.summary()
    print(
        f"{label:<44} {bps:>6.1f} {s['annualized_sharpe']:>8.4f} {sharpe(oos, bpy):>8.4f}"
        f" {newey_west_tstat(oos)['t_stat']:>7.3f} {max_drawdown(oos):>9.4f}"
        f" {s['cost_share_of_gross']:>11.4f}"
    )
