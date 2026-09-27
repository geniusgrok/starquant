"""G4 (2026-09-23): the crash windows and the empirical one-day VaR / ES, on the construction that trades.

WHY.  `config/alpha_registry.yaml`'s 2026-09-08 audit paragraph says the book "has been replayed through
2021-05, 2022-05, 2022-06, 2022-11 and 2024-08 - four positive, one small negative (FTX -3.3%)".  Those
replays are `scratchpad/audit20260908_stress_windows.py`, run while `vol_target` was 0.30.  P32 moved it to
0.60 on 2026-09-14 and nobody re-ran the windows, so the registry's tail statement describes a book half
the size of the one trading.  Until this script the daily report had a sigma ruler (DL-EX0) and no
empirical VaR or ES; the constants it measures are what `starquant_live.reports.tail_readings` now prints.
Checklist items 3.5 / 3.6 (`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`, G4).

WHAT RUNS.  The registry book as `p32d.panel_series` builds it - `build_model(registry, profile)` with the
profile's `vol_target` replaced, on the point-in-time panel, the exit overlay, then `run_backtest` with
both book guards and actual funding - with ONE difference, the band, and then R8's ladder, stepped by the
shipped `ladder_step` with `base` = the `k` being run (p32h's correction to p32g) on the mark-to-market
ruler.  Two columns, identical but for `k`: 0.60 (today) and 0.30 (the control, what the 09-08 replay
ran).  At 0.30 both of `Policy().drawdown_ladder`'s rungs ask for a target at or above the base, so the
clamp in `rung_scalar` makes the ladder inert there by construction; at 0.60 whether it fires is printed.

THE BAND.  `combine_books` bands the two-book sum with D2 and without D3: it passes `flat_inside_band` to
`apply_no_trade_band` and not `band_entry_multiple`, where `build_weights` passes both and the live
rebalancer applies both.  `starquant_alpha/portfolio.py` is another session's file on 2026-09-23, so this
script asks `evaluate` for the UNBANDED sum (`band=False`: summed, clipped, gross-capped, exactly
`combine_books` with the band switched off) and bands it itself with all of the profile's halves.
That it is `combine_books` plus D3 and nothing else is checked, not claimed: at `entry_multiple` 1.0 the
hand-applied band must equal `evaluate`'s own weights bit for bit, or the run stops.  The D2-only book
(what `research overlay`, `book` and the p32 family measure) is printed beside it as a sensitivity.

Everything else is read from `config/` as it stands, not restated here.  The old script is left exactly
as it ran - its numbers are what the registry comment cites.

KNOWN GAPS, carried rather than fixed (none is this script's to fix):

* The ladder's scalar multiplies the net series rather than re-deriving the weight path (P32b's
  approximation, inherited by every p32 replay).
* The flow sleeve's probe stop (`probe.stop`) is not replayed: the sleeve runs through every window.
* The benchmark is `benchmark_returns(..., membership=...)`, the members-only basket (bb1b9262).  The 09-08
  script averaged every panel column, which on a pit panel carries names selected in their future, so
  its benchmark column is not comparable with this one.

VaR / ES DEFINITION, fixed before the run: historical, over complete UTC days (24 hourly bars), daily
return = the compounded hourly net.  With n days sorted ascending and m = ceil(n x (1 - level)), VaR is
minus the m-th worst day and ES is minus the mean of the m worst days, so ES >= VaR holds by construction
and no interpolation rule has to be chosen.  Both are fractions of equity, positive = a loss.

Pinned for reproduction: the panel stops at `--to` (exclusive, default 2026-09-22T00:00Z, the last
midnight before the 1h archive's ragged end - BTCUSDT's last stored bar opened 2026-09-22T16:00Z).  The
membership table's sha256 is printed and written out; if it differs from the one RESEARCH_LOG records, the
table was rebuilt and the numbers will not reproduce - the 2026-09-04 lesson, stated rather than rediscovered.

Writes `scratchpad/g4-tail-readings.json` (ignored) and nothing else: no ledger, no report, no registry.

    .venv/bin/python scratchpad/g4_stress_windows_and_var_at_k060.py [--data-root .starquant/data] [--to 2026-09-22]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import benchmark_returns, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.overlays.ladder import ladder_step
from starquant_alpha.portfolio import apply_no_trade_band
from starquant_alpha.validation.metrics import compound, max_drawdown, sharpe
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_data.pool import MEMBERSHIP_FILE
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[1]
K_NOW, K_CONTROL = 0.60, 0.30
LEVELS = (0.95, 0.99)
OUT = ROOT / "scratchpad" / "g4-tail-readings.json"

#: The 09-08 script's list, verbatim, so every row can be read against the one the registry cites.  The
#: five the registry names are the middle five; 2020-03 predates the archive and 2025-02 was that script's
#: "largest in-sample drawdown month" at 0.30, kept as a row rather than re-chosen at 0.60.
WINDOWS = (
    ("2020-03 COVID crash", "2020-02-15", "2020-04-01"),
    ("2021-05 leverage flush", "2021-05-10", "2021-06-01"),
    ("2022-05 LUNA/UST", "2022-05-05", "2022-05-25"),
    ("2022-06 3AC/Celsius", "2022-06-10", "2022-07-05"),
    ("2022-11 FTX", "2022-11-05", "2022-11-25"),
    ("2024-08 yen carry unwind", "2024-08-01", "2024-08-15"),
    ("2025-02 (09-08's worst month)", "2025-02-01", "2025-03-01"),
)


def ladder_scalars(net: np.ndarray, base: float, policy: Policy) -> np.ndarray:
    """R8 on the book's own mark-to-market path, stepped by the shipped state machine at `base`.

    `p32h.ladder_at_base` with the realised ruler dropped: the loop's ruler has read
    `attributed_pnl+unrealized` since 2026-09-14, which is the backtest's mark-to-market path.  The
    scalar decided at bar t applies from bar t+1, as the loop's does to the next cycle's weights.
    """
    equity = hwm = 1.0
    standing: dict[str, Any] = {}
    scalars = np.ones(len(net))
    scalar = 1.0
    for t, value in enumerate(net):
        scalars[t] = scalar
        equity *= 1.0 + scalar * value
        hwm = max(hwm, equity)
        step = ladder_step(
            reading={"enforced": True, "value": equity / hwm - 1.0},
            standing=standing,
            base=base,
            rungs=policy.drawdown_ladder,
            grace_cycles=policy.drawdown_grace_cycles,
            bar_open_ms=t,
            now="",
        )
        if step.standing is not None:
            standing = step.standing
        scalar = float(step.block["scalar"])
    return scalars


def weight_paths(k: float, panel: Any, membership: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """The book at `vol_target = k` under two bands: the live one (D2 + D3) and `combine_books`' (D2 only).

    Signals are scored once; the two paths differ only in which `entry_multiple` bands the unbanded sum.
    Stops unless the hand-applied band at 1.0 IS `combine_books`' band - see THE BAND in the docstring.
    """
    tuned = copy.deepcopy(load_yaml(ROOT / "config" / "live.demo.yaml"))
    tuned.setdefault("portfolio", {})["vol_target"] = k
    model = build_model(load_registry(ROOT / "config" / "alpha_registry.yaml"), tuned)
    per = model.strategy_targets(panel, membership)
    unbanded = model.weights_from(per, panel.close, panel.bars_per_year, band=False)
    own = model.weights_from(per, panel.close, panel.bars_per_year)
    p = model.portfolio
    d2 = apply_no_trade_band(unbanded, p.no_trade_band, p.no_trade_rel_band, p.flat_inside_band, 1.0)
    if not (own.shape == d2.shape and np.array_equal(own.to_numpy(), d2.to_numpy(), equal_nan=True)):
        raise SystemExit(f"k={k}: the hand-applied band at entry_multiple 1.0 is not combine_books' band")
    live = apply_no_trade_band(unbanded, p.no_trade_band, p.no_trade_rel_band, p.flat_inside_band, p.band_entry_multiple)
    return {"live": live, "d2_only": own}


def replay(k: float, panel: Any, weights: pd.DataFrame) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    """Hourly net return of one weight path at `vol_target = k`: exits, both guards, then R8's ladder.

    The third value is the guard replay's per-bar record, so a window can say which guard bound in it.
    """
    profile = load_yaml(ROOT / "config" / "live.demo.yaml")
    registry = load_registry(ROOT / "config" / "alpha_registry.yaml")
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(pf["max_weight"]),
        max_gross=float(pf["max_gross"]),
        daily_loss_pause=float(profile["guards"]["daily_loss_pause"]),
    )
    weights = apply_exits(weights, panel.close, exits).weights if exits.enabled else weights
    result = run_backtest(panel, weights, cost_model(load_yaml(ROOT / "config" / "costs.yaml"), use_funding=True),
                          guards=guards)
    raw = result.portfolio_net
    scalars = ladder_scalars(raw.to_numpy(dtype=float), k, Policy())
    net = pd.Series(raw.to_numpy(dtype=float) * scalars, index=raw.index)
    events = result.guard_events if result.guard_events is not None else pd.DataFrame()
    info = {
        "k": k,
        "portfolio": {**pf, "vol_target": k},
        "exits": profile.get("exits"),
        "daily_loss_pause": guards.daily_loss_pause,
        "ladder_rungs": [list(rung) for rung in Policy().drawdown_ladder],
        "sleeves": {name: spec.fraction for name, spec in registry.books.items()},
        "strategies": [entry.id for entry in registry.enabled],
        "bars": len(net),
        "first_bar": str(net.index[0]),
        "last_bar": str(net.index[-1]),
        "ladder_bars_below_1": int((scalars < 1.0 - 1e-12).sum()),
        "unladdered_min_drawdown": float(max_drawdown(raw)),
        "daily_loss_pause_bars": int(events["daily_loss_pause"].sum()) if "daily_loss_pause" in events else None,
        "gross_capped_bars": int(events["gross_capped"].sum()) if "gross_capped" in events else None,
        "full_sample": {
            "compound": compound(net),
            "cagr": float(np.prod(1.0 + net.to_numpy()) ** (panel.bars_per_year / len(net)) - 1.0),
            "sharpe": sharpe(net, panel.bars_per_year),
            "max_drawdown": max_drawdown(net),
        },
    }
    return net, info, events.reindex(net.index)


def complete_days(net: pd.Series) -> pd.Series:
    """Compounded return per UTC day, keeping only days with all 24 hourly bars."""
    grouped = (1.0 + net).groupby(net.index.floor("D"))
    growth = grouped.prod()
    return (growth[grouped.size() == 24] - 1.0).rename("daily")


def var_es(daily: pd.Series, level: float) -> dict[str, float | int]:
    """Historical VaR and ES at `level`: the m-th worst day and the mean of the m worst, m = ceil(n(1-level))."""
    ordered = np.sort(daily.to_numpy(dtype=float))
    m = math.ceil(len(ordered) * (1.0 - level) - 1e-9)
    return {"m": m, "n": len(ordered), "var": float(-ordered[m - 1]), "es": float(-ordered[:m].mean())}


def main(data_root: str, to: str) -> None:
    table_path = Path(data_root) / MEMBERSHIP_FILE
    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
    symbols = _resolve_symbols(data_root, "", "1h", "pit")
    panel = _load(data_root, symbols, "1h", None, to, True)
    membership = _membership(data_root, "pit", panel, 0)
    bench_all = benchmark_returns(panel, "open_to_close", membership=membership)
    print(f"pit panel: {len(panel.symbols)} symbols x {len(panel.index):,} bars, {panel.index[0]} -> {panel.index[-1]}")
    print(f"membership.parquet sha256 {digest}")

    nets: dict[float, pd.Series] = {}
    infos: dict[float, dict[str, Any]] = {}
    events: dict[float, pd.DataFrame] = {}
    d2_nets: dict[float, pd.Series] = {}
    d2_infos: dict[float, dict[str, Any]] = {}
    for k in (K_NOW, K_CONTROL):
        paths = weight_paths(k, panel, membership)
        nets[k], infos[k], events[k] = replay(k, panel, paths["live"])
        d2_nets[k], d2_infos[k], _ = replay(k, panel, paths["d2_only"])
        for band, info in (("live band", infos[k]), ("D2 only  ", d2_infos[k])):
            fs = info["full_sample"]
            print(
                f"k={k:.2f} {band}: {info['bars']:,} bars {info['first_bar']} -> {info['last_bar']}  "
                f"CAGR {fs['cagr']:+.2%}  Sharpe {fs['sharpe']:.3f}  MDD {fs['max_drawdown']:.2%}  "
                f"ladder bars {info['ladder_bars_below_1']} (unladdered MDD {info['unladdered_min_drawdown']:.2%})  "
                f"pause bars {info['daily_loss_pause_bars']}  gross-capped bars {info['gross_capped_bars']}"
            )
    print("the hand-applied band at entry_multiple 1.0 equals combine_books' band bit for bit at both k")

    rows = []
    header = f"{'window':<32}{'bars':>6}" + "".join(
        f"{f'ret@{k:.2f}':>10}{f'sh@{k:.2f}':>9}{f'mdd@{k:.2f}':>10}" for k in (K_NOW, K_CONTROL)
    ) + f"{'bench':>9}"
    print("\n" + header)
    for label, start, end in WINDOWS:
        row: dict[str, Any] = {"window": label, "start": start, "end": end}
        slabs = {k: nets[k].loc[(nets[k].index >= start) & (nets[k].index < end)] for k in nets}
        bars = len(slabs[K_NOW])
        row["bars"] = bars
        if bars < 24:
            print(f"{label:<32}{bars:>6}   NOT IN SAMPLE (book starts {nets[K_NOW].index[0].date()})")
            row["in_sample"] = False
            rows.append(row)
            continue
        row["in_sample"] = True
        line = f"{label:<32}{bars:>6}"
        for k in (K_NOW, K_CONTROL):
            slab = slabs[k]
            s = sharpe(slab, panel.bars_per_year)
            d2 = d2_nets[k].loc[slab.index]
            bound = events[k].loc[slab.index]
            row[f"k{k:.2f}"] = {"return": compound(slab), "sharpe": s, "max_drawdown": max_drawdown(slab),
                                "d2_only_return": compound(d2), "d2_only_max_drawdown": max_drawdown(d2),
                                "pause_bars": int(bound["daily_loss_pause"].sum()),
                                "gross_capped_bars": int(bound["gross_capped"].sum())}
            line += f"{compound(slab):>+10.4f}{(s if s is not None else float('nan')):>9.2f}{max_drawdown(slab):>10.4f}"
        bench = compound(bench_all.loc[slabs[K_NOW].index])
        row["benchmark_members"] = bench
        print(line + f"{bench:>+9.4f}")
        rows.append(row)
    moves = [
        abs(row[f"k{k:.2f}"][f"d2_only_{name}"] - row[f"k{k:.2f}"][name])
        for row in rows
        if row["in_sample"]
        for k in (K_NOW, K_CONTROL)
        for name in ("return", "max_drawdown")
    ]
    print(f"D2-only band (combine_books as it stands): largest move of any window return or drawdown {max(moves):.4f}")
    print("guards inside each window (bars): " + "; ".join(
        f"{row['window'][:7]} pause {row['k0.60']['pause_bars']}/{row['k0.30']['pause_bars']} "
        f"capped {row['k0.60']['gross_capped_bars']}/{row['k0.30']['gross_capped_bars']}"
        for row in rows if row["in_sample"]
    ) + "  (k=0.60/k=0.30)")

    tails: dict[str, Any] = {}
    print("\none-day tail, historical, fractions of equity (positive = loss):")
    for k in (K_NOW, K_CONTROL):
        daily = complete_days(nets[k])
        levels = {f"{level:.2f}": var_es(daily, level) for level in LEVELS}
        worst = daily.nsmallest(6)
        # In units of the series' own daily sd, beside what a normal day would give: the sigma ruler's
        # reader needs to know how far a bad day sits outside it.
        sd = float(daily.std(ddof=1))
        in_sd = {f"{name}_{level[2:]}": v[name] / sd for level, v in levels.items() for name in ("var", "es")}
        tails[f"k{k:.2f}"] = {
            "days": len(daily),
            "first_day": str(daily.index[0].date()),
            "last_day": str(daily.index[-1].date()),
            "levels": levels,
            "daily_sd": sd,
            "in_sd": in_sd,
            "worst_days": {str(stamp.date()): float(value) for stamp, value in worst.items()},
            "days_below_daily_loss_pause": int((daily < -0.05).sum()),
        }
        text = "  ".join(
            f"VaR{level[2:]} {v['var']:.4%} ES{level[2:]} {v['es']:.4%} (m={v['m']})" for level, v in levels.items()
        )
        print(f"k={k:.2f}: {len(daily):,} complete UTC days {daily.index[0].date()} -> {daily.index[-1].date()}  {text}")
        print("        worst days: " + ", ".join(f"{s.date()} {v:+.2%}" for s, v in worst.items()))
        print(
            f"        daily sd {sd:.4%}; in sd: VaR95 {in_sd['var_95']:.3f} ES95 {in_sd['es_95']:.3f} "
            f"VaR99 {in_sd['var_99']:.3f} ES99 {in_sd['es_99']:.3f} (a normal day: 1.645 / 2.063 / 2.326 / 2.665); "
            f"days below the -5% pause line {int((daily < -0.05).sum())}"
        )
        d2_levels = {f"{level:.2f}": var_es(complete_days(d2_nets[k]), level) for level in LEVELS}
        tails[f"k{k:.2f}"]["d2_only_levels"] = d2_levels
        print(
            "        D2-only band: "
            + "  ".join(f"VaR{lv[2:]} {v['var']:.4%} ES{lv[2:]} {v['es']:.4%}" for lv, v in d2_levels.items())
        )

    OUT.write_text(
        json.dumps(
            {
                "script": "scratchpad/g4_stress_windows_and_var_at_k060.py",
                "data_root": data_root,
                "to_exclusive": to,
                "membership_sha256": digest,
                "panel": {"symbols": len(panel.symbols), "bars": len(panel.index),
                          "first": str(panel.index[0]), "last": str(panel.index[-1])},
                "replays": {f"k{k:.2f}": infos[k] for k in infos},
                "replays_d2_only": {f"k{k:.2f}": d2_infos[k] for k in d2_infos},
                "windows": rows,
                "tails": tails,
            },
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=".starquant/data")
    parser.add_argument("--to", default="2026-09-22")
    args = parser.parse_args()
    main(args.data_root, args.to)
