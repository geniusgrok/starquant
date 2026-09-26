"""backtest-guard audit 2026-09-08, second pass: shape of the return distribution and the stress windows.

Ⅳ.1 asks whether this is a disguised short-volatility book (high hit rate, small wins, rare huge
losses, left-skewed).  Ⅲ.3 asks how it walked through the named crises.  Both are answerable from
the shipped configuration's own net-return series.  Writes nothing.
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
from starquant_alpha.validation.metrics import compound, max_drawdown, sharpe
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
model = build_model(load_registry(Path("config/alpha_registry.yaml")), PROFILE)
weights, _c, _p = model.evaluate(panel, membership)
exits = ExitParams.from_mapping(
    {**(PROFILE.get("exits") or {}), "bars_per_day": max(1, 86_400 // interval_seconds("1h"))}
)
guards = BookGuardParams(
    max_weight=float(PROFILE["portfolio"]["max_weight"]),
    max_gross=float(PROFILE["portfolio"]["max_gross"]),
    daily_loss_pause=float(PROFILE["guards"]["daily_loss_pause"]),
)
res = run_backtest(
    panel, apply_exits(weights, panel.close, exits).weights,
    cost_model(COSTS, use_funding=True), execution="open_to_close", guards=guards,
)
net = res.portfolio_net
bpy = panel.bars_per_year
print(f"sample: {net.index[0]} -> {net.index[-1]}  ({len(net):,} hourly bars)")

# --- Ⅳ.1 short-vol tells -------------------------------------------------------------------------
v = net.to_numpy(dtype=float)
v = v[np.isfinite(v)]
daily = net.resample("1D").apply(lambda s: float(np.prod(1.0 + s.to_numpy(dtype=float)) - 1.0))
d = daily.to_numpy(dtype=float)
d = d[np.isfinite(d)]
for label, x in (("hourly", v), ("daily", d)):
    mean, sd = x.mean(), x.std(ddof=1)
    skew = float(((x - mean) ** 3).mean() / sd**3)
    kurt = float(((x - mean) ** 4).mean() / sd**4)
    wins, losses = x[x > 0], x[x < 0]
    print(
        f"{label:>7}: n={len(x):>6,}  hit {len(wins) / len(x):.4f}"
        f"  mean win {wins.mean():+.5f}  mean loss {losses.mean():+.5f}"
        f"  payoff {abs(wins.mean() / losses.mean()):.3f}"
        f"  skew {skew:+.3f}  kurtosis {kurt:.2f}"
        f"  worst {x.min():+.4f}  best {x.max():+.4f}"
    )

# --- Ⅲ.3 named stress windows --------------------------------------------------------------------
windows = [
    ("2020-03 COVID crash", "2020-02-15", "2020-04-01"),
    ("2021-05 leverage flush", "2021-05-10", "2021-06-01"),
    ("2022-05 LUNA/UST", "2022-05-05", "2022-05-25"),
    ("2022-06 3AC/Celsius", "2022-06-10", "2022-07-05"),
    ("2022-11 FTX", "2022-11-05", "2022-11-25"),
    ("2024-08 yen carry unwind", "2024-08-01", "2024-08-15"),
    ("2025-02 (largest in-sample dd month)", "2025-02-01", "2025-03-01"),
]
print(f"\n{'window':<40} {'bars':>6} {'return':>9} {'Sharpe':>8} {'max dd':>9}  {'benchmark':>10}")
bench = (panel.close / panel.open - 1.0).reindex(net.index).mean(axis=1)
for label, start, end in windows:
    slab = net.loc[(net.index >= start) & (net.index < end)]
    if len(slab) < 24:
        print(f"{label:<40} {len(slab):>6}   NOT IN SAMPLE (panel starts {net.index[0].date()})")
        continue
    b = bench.loc[slab.index]
    s = sharpe(slab, bpy)
    print(
        f"{label:<40} {len(slab):>6} {compound(slab):>+9.4f} {(s if s is not None else float('nan')):>8.2f}"
        f" {max_drawdown(slab):>9.4f}  {compound(b):>+10.4f}"
    )

# --- worst months --------------------------------------------------------------------------------
monthly = net.resample("MS").apply(lambda s: float(np.prod(1.0 + s.to_numpy(dtype=float)) - 1.0))
print("\nworst 6 months:")
for stamp, value in monthly.nsmallest(6).items():
    print(f"  {pd.Timestamp(stamp).strftime('%Y-%m')}  {value:+.4f}")
print("worst 6 UTC days:")
for stamp, value in daily.nsmallest(6).items():
    print(f"  {pd.Timestamp(stamp).date()}  {value:+.4f}")
