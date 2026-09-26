"""backtest-guard audit 2026-09-08: how sensitive is D-020's Newey-West t to the lag count?

`newey_west_tstat` picks lags = floor(4*(n/100)^(2/9)), the Newey-West (1994) rule.  On this book
that is ~16 hourly lags, while the signal's horizons are 168/336/720 bars and the no-trade band
holds positions for weeks.  This walks the lag count out and reports where the t-statistic settles.
Reads the shipped configuration's net-return series; writes nothing.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "~/starquant")

from starquant_alpha.backtest import run_backtest
from starquant_alpha.model import AlphaModel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.metrics import newey_west_tstat, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_evaluate, walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import cost_model, load_panel, load_registry, portfolio_params
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
entry = next(e for e in load_registry(Path("config/alpha_registry.yaml")).strategies if e.id == "tsmom")
model = AlphaModel(
    entries=(StrategyEntry(id="tsmom", params=dict(entry.params)),),
    portfolio=portfolio_params(PROFILE),
    interval="1h",
    min_history_bars=int(PROFILE["portfolio"]["min_history_bars"]),
)
weights, _c, _p = model.evaluate(panel, membership)
res = run_backtest(panel, weights, cost_model(COSTS, use_funding=True), execution="open_to_close")
bpy = panel.bars_per_year

net = res.portfolio_net.reset_index(drop=True)
folds = walk_forward_folds(len(net), 5, min_train=4000, purge=50)
wf = walk_forward_evaluate({"one": net}, {"one": dict(entry.params)}, folds, bpy)
oos = wf.oos_returns

for label, series in (("full sample", net), ("walk-forward OOS", oos)):
    values = np.asarray(series, dtype=float)
    values = values[np.isfinite(values)]
    n = values.size
    auto = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    print(f"\n=== {label}: n={n} bars  Sharpe {sharpe(series, bpy):.4f}  automatic lags={auto} ===")
    print(f"{'lags':>7}  {'lag in days':>12}  {'t_stat':>8}  {'p':>10}")
    for lags in (0, auto, 24, 72, 168, 336, 720, 1440, 2160):
        if lags > n - 2:
            continue
        out = newey_west_tstat(series, max_lags=lags)
        t = out["t_stat"]
        p = out["p_value"]
        tag = "  <- shipped rule" if lags == auto else ""
        print(f"{lags:>7}  {lags / 24.0:>12.1f}  {t:>8.3f}  {p:>10.5f}{tag}")

    # first-order autocorrelation profile of the return series, for context
    centered = values - values.mean()
    denom = float(np.dot(centered, centered))
    acf = [float(np.dot(centered[k:], centered[:-k])) / denom for k in (1, 24, 168, 336, 720, 1440)]
    print("  ACF at lags 1/24/168/336/720/1440: " + " ".join(f"{a:+.4f}" for a in acf))

# how long does a position actually persist?  mean |w| autocorrelation half-life per symbol
w = res.weights.fillna(0.0)
sign_series = np.sign(w.to_numpy(dtype=float))
flips = (np.diff(sign_series, axis=0) != 0).sum()
nonzero = (sign_series != 0).sum()
print(f"\nposition-sign changes: {flips} over {nonzero} held symbol-bars"
      f"  -> mean holding {nonzero / max(flips, 1):.0f} bars ({nonzero / max(flips, 1) / 24:.1f} days)")
auto_lags = math.floor(4 * (len(net) / 100.0) ** (2.0 / 9.0))
print(f"automatic lag rule gives {auto_lags} bars = {auto_lags / 24:.1f} days")
