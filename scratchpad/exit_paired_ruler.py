"""The paired ruler for exit-overlay decisions: NW t of the per-bar OOS difference, not two lone Sharpes.

Why (2026-09-08).  `docs/RESEARCH_LOG.md:481` already retracted the habit this fixes: judging an overlay
change against the 0.43 annualised standard error of a SINGLE Sharpe estimate, when the two books run on
the same data, the same folds and the same signals and are therefore ~99% correlated.  The quantity that
decides is the precision of the PAIRED difference.  P10 established the instrument
(`reports/research/paired-p10-band-20260904T030015Z.json`, NW t 4.182 on dSharpe 0.142); nothing had ever
applied it to the exit overlay, so every exits verdict before P24 was read off two point estimates.

It also separates two rulers the overlay reports conflate.  `dSharpe` moves when EITHER the mean return
or its volatility moves; the per-bar NW t on the difference series moves only with the mean.  On the live
setting they disagree by 34x (pit) and 0.29x (static), so "annualised return" and "Sharpe" are different
questions here and P24's criterion A is the former.

LEDGER (K-EX07: an offline replay is a diagnostic trial too).  Comparing ONLY the pair the overlay
reports already publish - baseline against the setting live in `config/live.demo.yaml` - evaluates no new
configuration and is not a trial.  Passing `--overlay` evaluates a candidate and IS one: it must be
declared and charged before the run.  P24 declared arms 1 and 2 in `docs/RESEARCH_LOG.md` (commit
2026-09-08 03:07:54 +08) and the operator confirmed tsmom +2 / flow +2.

Writes nothing itself: no report, no ledger row, no config change.  `scratchpad/p24_record.py` writes the
ledger rows separately, so a failed run cannot half-charge the ledger.

    python scratchpad/exit_paired_ruler.py [pit|static] [--overlay '{"take_profit": 8.0}']
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.panel import interval_seconds
from starquant_alpha.validation.metrics import newey_west_tstat, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, cost_model, load_panel, load_registry
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
INTERVAL = "1h"


def _oos(panel, weights, cost, folds_ref: list[Any] | None) -> tuple[pd.Series, list[Any]]:
    net = run_backtest(panel, weights, cost, execution="open_to_close").portfolio_net
    folds = folds_ref or walk_forward_folds(len(net), 5, min_train=4000, purge=50)
    return net, folds


def _report(name: str, base: pd.Series, cand: pd.Series, folds, bpy: float) -> dict[str, float]:
    oos_b = pd.concat([base.iloc[f.test_slice] for f in folds])
    oos_c = pd.concat([cand.iloc[f.test_slice] for f in folds])
    diff = oos_c - oos_b
    nw = newey_west_tstat(diff)
    per_fold = [sharpe(cand.iloc[f.test_slice], bpy) - sharpe(base.iloc[f.test_slice], bpy) for f in folds]
    mean, se = st.mean(per_fold), st.stdev(per_fold) / math.sqrt(len(per_fold))
    out = {
        "d_sharpe": sharpe(oos_c, bpy) - sharpe(oos_b, bpy),
        "annual_return_diff": float(diff.mean()) * bpy,
        "nw_t": float(nw["t_stat"]),
        "fold_t": mean / se if se else float("nan"),
        "fold_mean": mean,
        "corr": float(oos_b.corr(oos_c)),
    }
    print(
        f"  {name:<28} dSharpe {out['d_sharpe']:+.4f}   年化收益差 {out['annual_return_diff'] * 100:+.2f}%/年"
        f"   逐bar NW t {out['nw_t']:+.3f}   折级 t {out['fold_t']:+.2f}   corr {out['corr']:.4f}"
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="pit", choices=("pit", "static"))
    parser.add_argument("--overlay", default="", help='JSON overriding the live exits, e.g. {"take_profit": 8.0}')
    args = parser.parse_args()

    profile = load_yaml("config/live.demo.yaml")
    costs = load_yaml("config/costs.yaml")

    table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
    idx = pd.DatetimeIndex(table.index)
    table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    store = KlineStore(ROOT)
    stored = set(store.symbols(INTERVAL))
    symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
    if args.mode == "static":
        # the 18 symbols the loop holds today - the same set P22's static report used
        keep = set(json.loads(Path(".starquant/live/state.json").read_text())["universe"]) & set(symbols)
        symbols = [s for s in symbols if s in keep]
        table = table[symbols]
        table.loc[:, :] = True  # static = always a member, which is what the static reports mean
    panel = load_panel(store, symbols, INTERVAL, funding_store=FundingStore(ROOT))
    membership = membership_at_bars(table, panel.index)

    registry = load_registry(Path("config/alpha_registry.yaml"))
    model = build_model(registry, profile)
    cost = cost_model(costs, use_funding=True)
    bpy = panel.bars_per_year
    weights, _c, _p = model.evaluate(panel, membership)

    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    live_map = {**(profile.get("exits") or {}), "bars_per_day": bars_per_day}
    live = ExitParams.from_mapping(live_map)
    print(f"[{args.mode}] {len(panel.symbols)} symbols x {len(panel.index)} bars")
    print(f"  incumbent: sl={live.stop_loss} tr={live.trailing_stop} tp={live.take_profit} "
          f"cooldown={live.cooldown_bars} unit_mode={live.unit_mode}")

    net_a, folds = _oos(panel, weights, cost, None)  # A: no exits (report baseline)
    live_overlay = apply_exits(weights, panel.close, live)
    net_b, _ = _oos(panel, live_overlay.weights, cost, folds)  # B: incumbent
    print(f"  incumbent events: {live_overlay.summary()}")

    print(f"\n{'':<30}")
    _report("B incumbent - A baseline", net_a, net_b, folds, bpy)

    if args.overlay:
        override = json.loads(args.overlay)
        cand = ExitParams.from_mapping({**live_map, **override})
        cand_overlay = apply_exits(weights, panel.close, cand)
        net_c, _ = _oos(panel, cand_overlay.weights, cost, folds)
        print(f"\n  candidate: sl={cand.stop_loss} tr={cand.trailing_stop} tp={cand.take_profit} "
              f"cooldown={cand.cooldown_bars} unit_mode={cand.unit_mode}")
        print(f"  candidate events: {cand_overlay.summary()}")
        oos_c = pd.concat([net_c.iloc[f.test_slice] for f in folds])
        print(f"  candidate OOS Sharpe: {sharpe(oos_c, bpy):.4f}\n")
        out = _report("C candidate - B incumbent", net_b, net_c, folds, bpy)
        _report("C candidate - A baseline", net_a, net_c, folds, bpy)
        print("\n  === P24 判定（对 B incumbent）===")
        print(f"  (1) 年化收益差为正: {'是' if out['annual_return_diff'] > 0 else '否'} "
              f"({out['annual_return_diff'] * 100:+.2f}%/年)")
        print(f"  (2) 逐bar NW t >= 1.8: {'是' if out['nw_t'] >= 1.8 else '否'} ({out['nw_t']:+.3f})")
        print(f"  (3) 折级 ΔSharpe 符号: {'+' if out['fold_mean'] > 0 else '-'} ({out['fold_mean']:+.4f})")
        print(f"  sharpe_annual for ledger: {sharpe(oos_c, bpy):.6f}")


if __name__ == "__main__":
    main()
