"""What the multi-book band lost without D3: read-only replays on the registry book (2026-09-23).

Until the fix this script ships beside, `combine_books` passed D2 `flat_inside_band` and not D3
`band_entry_multiple`, and `research book`'s single arms passed neither.  This measures the difference on
the book the registry holds (tsmom + 1/3 flow_short) with the live profile (band 0.005, relative 0.40,
D2 on, D3 2.0), all data, in three protocols:

  A. `research overlay`'s baseline - the registry model banded, priced with no guards and no exits
  B. `research book`'s arms - tsmom + 1/3 flow, 5 folds, min_train 4000, purge 50 - banded both ways
  C. the book the loop holds (exits + guards) at k in {0.60, 0.35, 0.30, 0.25}: the series
     `p32d.panel_series` hands `p32f`, `p32g` and `p32h`, saved for `d3_multibook_kgrid_bootstrap.py`

Every arm is built explicitly from the unbanded weights, so the script means the same thing on either side
of the fix; it prints which arm the production path equals (D2 alone before the fix, D2 + D3 after).
Nothing is charged to the ledger and nothing is written under `reports/`; outputs go to
`scratchpad/d3_multibook_out/`, which `.gitignore` keeps out of the tree.

    .venv/bin/python scratchpad/d3_multibook_band_impact.py pit|static

`static` is pinned to `p32h.STATIC_P32G`, the 16 names `p32g` ran on.  Read from `universe.json` instead,
it would be whatever the loop's daily refresh last wrote - AKEUSDT entered at 2026-09-23T01:00Z.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p32e_ruler_divergence import DATA, realised_split
from p32h_k_sweep_at_the_base_in_force import STATIC_P32G

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.portfolio import apply_no_trade_band, build_weights, combine_books
from starquant_alpha.validation.metrics import max_drawdown, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_cli.research_book_eval import _fold_metrics, _overlay_metrics
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scratchpad" / "d3_multibook_out"

T0 = time.time()


def log(message: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {message}", flush=True)


def bits_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        return False
    return bool(np.array_equal(left.to_numpy(dtype=float).view(np.uint64), right.to_numpy(dtype=float).view(np.uint64)))


def which(production: pd.DataFrame, d2_only: pd.DataFrame, d2_d3: pd.DataFrame) -> str:
    if bits_equal(production, d2_only):
        return "D2 only (before the fix)"
    if bits_equal(production, d2_d3):
        return "D2 + D3 (after the fix)"
    return "NEITHER - the replay does not describe this code"


def diff_stats(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    x = before.fillna(0.0).to_numpy(dtype=float)
    y = after.fillna(0.0).to_numpy(dtype=float)
    changed = x != y
    nonzero = x != 0.0
    return {
        "cells_changed": int(changed.sum()),
        "nonzero_cells_before": int(nonzero.sum()),
        "share_of_nonzero_changed": float(changed.sum() / max(1, nonzero.sum())),
        "cells_zeroed": int((nonzero & (y == 0.0)).sum()),
        "bars_touched": int(changed.any(axis=1).sum()),
        "names_touched": int(changed.any(axis=0).sum()),
        "abs_exposure_moved_share": float(np.abs(x - y).sum() / max(1e-12, np.abs(x).sum())),
    }


def paired(left: list[float], right: list[float]) -> dict:
    deltas = np.asarray(right, dtype=float) - np.asarray(left, dtype=float)
    se = float(deltas.std(ddof=1) / np.sqrt(len(deltas)))
    return {"fold_deltas": deltas.tolist(), "mean": float(deltas.mean()), "se": se, "t": float(deltas.mean() / se)}


def main(mode: str) -> None:
    profile = load_yaml(str(REPO / "config" / "live.demo.yaml"))
    model = build_model(load_registry(REPO / "config" / "alpha_registry.yaml"), profile)
    pf = model.portfolio
    log(f"books={model.book_names} fractions={model.books} band={pf.no_trade_band} rel={pf.no_trade_rel_band} "
        f"D2={pf.flat_inside_band} D3={pf.band_entry_multiple} vol_target={pf.vol_target}")
    symbols = ",".join(STATIC_P32G) if mode == "static" else ""
    panel = _load(DATA, _resolve_symbols(DATA, symbols, "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    bpy = panel.bars_per_year
    log(f"{mode}: {len(panel.symbols)} symbols x {len(panel.index)} bars, {panel.index[0]} -> {panel.index[-1]}")
    cost = cost_model(load_yaml(str(REPO / "config" / "costs.yaml")), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    guards = BookGuardParams(
        max_weight=pf.max_weight, max_gross=pf.max_gross, daily_loss_pause=float(profile["guards"]["daily_loss_pause"])
    )
    per = model.strategy_targets(panel, membership)
    report: dict = {"mode": mode, "range": [str(panel.index[0]), str(panel.index[-1])], "bars": len(panel.index)}

    def band(weights: pd.DataFrame, flat_inside: bool, multiple: float) -> pd.DataFrame:
        return apply_no_trade_band(weights, pf.no_trade_band, pf.no_trade_rel_band, flat_inside, multiple)

    # A. The registry model, banded, as `research overlay` prices it.
    unbanded = model.weights_from(per, panel.close, bpy, band=False)
    d2, d3 = band(unbanded, True, 1.0), band(unbanded, True, 2.0)
    report["A_production_is"] = which(model.weights_from(per, panel.close, bpy), d2, d3)
    report["A_weights"] = diff_stats(d2, d3)
    books = model.book_weights(per, panel.close, bpy)
    report["A_weights_one_book_control"] = diff_stats(band(books["main"], True, 1.0), band(books["main"], True, 2.0))
    metrics = {name: _overlay_metrics(run_backtest(panel, w, cost), 5, 4000, bpy) for name, w in (("d2", d2), ("d3", d3))}
    one_book = {
        name: _overlay_metrics(run_backtest(panel, band(books["main"], True, m), cost), 5, 4000, bpy)
        for name, m in (("d2", 1.0), ("d3", 2.0))
    }
    report["A_overlay_baseline"] = {
        "d2_only": metrics["d2"],
        "d2_d3": metrics["d3"],
        "paired_folds": paired(metrics["d2"]["fold_sharpes"], metrics["d3"]["fold_sharpes"]),
        "one_book_oos_sharpe": [one_book["d2"]["oos_sharpe"], one_book["d3"]["oos_sharpe"]],
    }
    log(f"A production is {report['A_production_is']}; two books oos {metrics['d2']['oos_sharpe']:.4f} -> "
        f"{metrics['d3']['oos_sharpe']:.4f}, one book {one_book['d2']['oos_sharpe']:.4f} -> {one_book['d3']['oos_sharpe']:.4f}; "
        f"cells {report['A_weights']['cells_changed']} over {report['A_weights']['names_touched']} names "
        f"(one book {report['A_weights_one_book_control']['names_touched']})")

    # B. `research book`'s arms.  The registry sleeve's book weights ARE `w_sleeve * fraction`.
    bare = replace(pf, no_trade_band=0.0, no_trade_rel_band=0.0)
    w_main, fraction = books["main"], model.books["flow_short"]
    w_sleeve = build_weights(model.book_targets(per)["flow_short"], panel.close, bpy, bare)
    report["B_combined_production_is"] = which(combine_books({"main": w_main, "sleeve": w_sleeve * fraction}, pf), d2, d3)
    arms = {
        "main_none": band(w_main, False, 1.0),
        "main_full": band(w_main, True, 2.0),
        "combined_d2": d2,
        "combined_full": d3,
        "sleeve_none": band(w_sleeve, False, 1.0),
        "sleeve_full": band(w_sleeve, True, 2.0),
    }
    results = {name: run_backtest(panel, w, cost) for name, w in arms.items()}
    index = results["main_none"].portfolio_net.index
    for result in results.values():
        index = index.intersection(result.portfolio_net.index)
    folds = walk_forward_folds(len(index), 5, min_train=min(4000, max(len(index) // 2, 2)), purge=50)
    fm = {name: _fold_metrics(r.portfolio_net.reindex(index).fillna(0.0), folds, bpy) for name, r in results.items()}

    def d018(main_key: str, total_key: str) -> dict:
        m, t = fm[main_key], fm[total_key]
        deltas = [b - a for a, b in zip(m["fold_sharpes"], t["fold_sharpes"], strict=True)]
        return {
            "delta_oos_sharpe": t["oos_sharpe"] - m["oos_sharpe"],
            "oos_mdd_worsening": m["oos_mdd"] - t["oos_mdd"],
            "fold_win_rate": float(np.mean([d > 0 for d in deltas])),
            "fold_deltas": deltas,
        }

    report["B_book"] = {
        "as banded before the fix (main none, combined D2)": d018("main_none", "combined_d2"),
        "combine_books fixed alone (main none, combined D2+D3)": d018("main_none", "combined_full"),
        "both fixed (main D2+D3, combined D2+D3)": d018("main_full", "combined_full"),
        "sleeve_alone_oos_sharpe": [fm["sleeve_none"]["oos_sharpe"], fm["sleeve_full"]["oos_sharpe"]],
    }
    for name, row in report["B_book"].items():
        if isinstance(row, dict):
            log(f"B {name}: delta {row['delta_oos_sharpe']:+.4f} mdd_worse {row['oos_mdd_worsening']:+.4f} "
                f"win {row['fold_win_rate']:.1f} folds {[round(d, 4) for d in row['fold_deltas']]}")

    # C. The book the loop holds, at three k, for the p32 family.
    OUT.mkdir(parents=True, exist_ok=True)
    series: dict[str, np.ndarray] = {}
    report["C"] = {}
    for k in (0.60, 0.35, 0.30, 0.25):
        at_k = replace(model, portfolio=replace(pf, vol_target=k))
        unbanded_k = at_k.weights_from(per, panel.close, bpy, band=False)
        arms_k = {"d2": band(unbanded_k, True, 1.0), "d3": band(unbanded_k, True, 2.0)}
        row: dict = {
            "production_is": which(at_k.weights_from(per, panel.close, bpy), arms_k["d2"], arms_k["d3"]),
            "weights": diff_stats(arms_k["d2"], arms_k["d3"]),
        }
        for name, weights in arms_k.items():
            held = apply_exits(weights, panel.close, exits).weights if exits.enabled else weights
            result = run_backtest(panel, held, cost, guards=guards)
            realised, mark = realised_split(  # (realised, mark_to_market) - `p32d`'s order
                np.nan_to_num(result.weights.to_numpy(dtype=float), nan=0.0),
                np.nan_to_num(result.asset_returns.to_numpy(dtype=float), nan=0.0),
                np.nan_to_num(result.costs.to_numpy(dtype=float), nan=0.0),
            )
            series[f"k{k:.2f}_{name}_mark"], series[f"k{k:.2f}_{name}_realised"] = mark, realised
            equity = np.cumprod(1.0 + mark)
            row[name] = {
                "full_sharpe": sharpe(result.portfolio_net, bpy),
                "full_mdd_net": max_drawdown(result.portfolio_net),
                "mtm_mdd": float((equity / np.maximum.accumulate(equity) - 1.0).min()),
                "cagr": float(equity[-1] ** (8760.0 / len(mark)) - 1.0),
            }
        report["C"][f"{k:.2f}"] = row
        log(f"C k={k}: {row['production_is']}; {row['weights']['cells_changed']} cells "
            f"({row['weights']['share_of_nonzero_changed']:.2%} of non-zero); sharpe {row['d2']['full_sharpe']:.4f} -> "
            f"{row['d3']['full_sharpe']:.4f}, cagr {row['d2']['cagr']:.4f} -> {row['d3']['cagr']:.4f}")
    np.savez_compressed(OUT / f"series-{mode}.npz", **series)
    (OUT / f"impact-{mode}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log(f"wrote {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
