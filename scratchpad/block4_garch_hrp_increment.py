"""P29: what the GARCH divisor (#35) and the HRP budget (#48) are worth against what already ships.

Pre-registered in RESEARCH_LOG (commit 227e865, renumbered P28 -> P29 because #6 had already taken P28), written before this ran.  Grids, criteria and
falsifiers are there; this file is the harness, and it adopts nothing.

**Writes nothing**: no ledger row, no report, no config.  Both options are construction changes, so
turning either on belongs to batch window #1 (Phase 4a) and would reset M-010's 30-day window, which
stands at 4.66/30 days and first matures 2026-10-04.  The output is two tables.

Three design decisions that are the measurement rather than the plumbing:

* The per-strategy targets are computed ONCE and reused by every arm.  An arm must differ from the
  baseline in its divisor or its budget and in nothing else; re-deriving targets per arm would also
  move the cross-sectional reference population, and then the comparison is of two strategies.
* Both arms are masked to the COMMON SUPPORT of the two divisors.  GARCH warms up longer than EWMA
  (57.0% of symbol-bars against 61.2% on the point-in-time panel), and an arm trading a different pool
  is a pool difference, not a divisor difference.  The unmasked run is reported as a control row.
* The ruler is PAIRED and per fold.  Both arms run on the same bars and the same signals, so their net
  streams are correlated near 1 and the quantity with a standard error is the DIFFERENCE.  Judging a
  paired difference against the 0.43 sampling error of a single annual Sharpe is the mistake this
  file's own repository made on P10 cell B and corrected on 2026-09-04.
"""

from __future__ import annotations

import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.backtest import run_backtest
from starquant_alpha.features import ewm_vol, garch_forecast_vol
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.panel import Panel, interval_seconds
from starquant_alpha.portfolio import PortfolioParams, asset_vol
from starquant_alpha.validation.metrics import max_drawdown, sharpe
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")
INTERVAL = "1h"
FOLDS, MIN_TRAIN = 5, 4000

ARMS: dict[str, dict[str, object]] = {
    "A0/B0 baseline  ewma-48 / inverse_vol": {},
    "A1 ewma-24                           ": {"vol_halflife": 24},
    "A2 ewma-168                          ": {"vol_halflife": 168},
    "A3 garch  fit 8760 refit 720         ": {"vol_model": "garch"},
    "A4 garch  fit 8760 refit 168         ": {"vol_model": "garch", "garch_refit_bars": 168},
    "A5 garch  fit 4380 refit 720         ": {"vol_model": "garch", "garch_fit_bars": 4380},
    "B1 inverse_variance (control)        ": {"budget_mode": "inverse_variance"},
    "B2 hrp    refit 720                  ": {"budget_mode": "hrp"},
    "B3 hrp    refit 168                  ": {"budget_mode": "hrp", "hrp_refit_bars": 168},
    "B4 hrp    refit 2160                 ": {"budget_mode": "hrp", "hrp_refit_bars": 2160},
    "B5 hrp    refit 720, cov_hl 336      ": {"budget_mode": "hrp", "covariance_halflife": 336},
}


def qlike(forecast: np.ndarray, realised: np.ndarray) -> float:
    """QLIKE against next bar's r^2.  Not MSE: MSE on a variance ranks by which tail luck it caught.

    Flat numpy rather than the obvious pandas `.stack()`: on this panel that is 5.8M rows twice over
    and the first attempt at this script was killed at 4.8 GB before it printed a line.
    """
    ratio = realised / forecast**2
    keep = np.isfinite(ratio) & (ratio > 0)
    return float(np.mean(ratio[keep] - np.log(ratio[keep]) - 1.0))


def fold_sharpes(net: pd.Series, bars_per_year: float) -> list[float]:
    folds = walk_forward_folds(len(net), FOLDS, min_train=MIN_TRAIN)
    return [float(sharpe(net.iloc[f.test_slice], bars_per_year) or math.nan) for f in folds]


def measure(name: str, panel: Panel, model: object, per_strategy: dict, tuned: PortfolioParams, exits: ExitParams, cost: object) -> dict:
    built = replace(model, portfolio=tuned).weights_from(per_strategy, panel.close, panel.bars_per_year)
    weights = apply_exits(built, panel.close, exits).weights if exits.enabled else built
    result = run_backtest(panel, weights, cost)
    net = result.portfolio_net
    oos = net.iloc[walk_forward_folds(len(net), FOLDS, min_train=MIN_TRAIN)[0].test_start :]
    return {
        "name": name,
        "net": net,
        "folds": fold_sharpes(net, panel.bars_per_year),
        "oos_sharpe": float(sharpe(oos, panel.bars_per_year) or math.nan),
        "oos_mdd": float(max_drawdown(oos)),
        "turnover": float(result.turnover.sum()),
        "exposure": float(result.weights.abs().sum(axis=1).mean()),
    }


def report(rows: list[dict], label: str, base_index: int = 0) -> None:
    """`base_index` selects which arm the pairing is against.

    Criterion 2 for HRP is B2 against B1, not against A0/B0: the pre-registration asks whether the
    CLUSTERING pays, and B1 is the same allocator with the clustering removed.  A pairing against the
    shipped arm cannot answer that, because it also carries the inverse-vol -> inverse-variance change.
    """
    base = rows[base_index]
    print(f"\n{'=' * 118}\n{label}\n{'=' * 118}")
    print(f"{'arm':<38}{'OOS Sh':>9}{'dSharpe':>9}{'fold SE':>9}{'t':>7}{'OOS MDD':>10}{'dMDD pp':>9}{'turn %':>9}{'corr':>8}")
    for row in rows:
        delta = [a - b for a, b in zip(row["folds"], base["folds"], strict=True)]
        se = float(np.std(delta, ddof=1) / math.sqrt(len(delta))) if row is not base else math.nan
        mean = float(np.mean(delta))
        joint = row["net"].notna() & base["net"].notna()
        corr = float(row["net"][joint].corr(base["net"][joint])) if row is not base else 1.0
        print(
            f"{row['name']:<38}{row['oos_sharpe']:>9.4f}"
            f"{'' if row is base else f'{mean:>+9.4f}'}{'' if row is base else f'{se:>9.4f}'}"
            f"{'' if row is base else f'{mean / se:>7.2f}'}"
            f"{row['oos_mdd'] * 100:>9.2f}%{'' if row is base else f'{(row['oos_mdd'] - base['oos_mdd']) * 100:>+9.2f}'}"
            f"{(row['turnover'] / base['turnover'] - 1.0) * 100:>+8.1f}%{'' if row is base else f'{corr:>8.4f}'}"
        )


def run(universe_mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    model = build_model(registry, profile)
    chosen = _resolve_symbols(ROOT, "", INTERVAL, universe_mode)
    panel = _load(ROOT, chosen, INTERVAL, None, None, True)
    membership = _membership(ROOT, universe_mode, panel)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    base_params = model.portfolio

    # The two divisors, and the common support the arms are judged on.
    ewma = asset_vol(panel.close, base_params, panel.bars_per_year)
    garch = asset_vol(panel.close, replace(base_params, vol_model="garch"), panel.bars_per_year)
    support = ewma.notna() & garch.notna()
    realised = panel.close.pct_change().pow(2).shift(-1).to_numpy(dtype=float)
    raw_ewma = ewm_vol(panel.close, halflife=base_params.vol_halflife).to_numpy(dtype=float)
    raw_garch = garch_forecast_vol(panel.close).to_numpy(dtype=float)
    seen = support.to_numpy() & np.isfinite(realised) & (raw_ewma > 0) & (raw_garch > 0)
    level, forecast = raw_ewma[seen], raw_garch[seen]
    print(f"\n### {universe_mode} universe: {len(panel.symbols)} symbols x {len(panel.index)} bars")
    print(f"support  ewma {ewma.notna().to_numpy().mean():.4f}  garch {garch.notna().to_numpy().mean():.4f}  both {support.to_numpy().mean():.4f}  pairs {seen.sum():,}")
    print(f"corr(sigma) level {np.corrcoef(forecast, level)[0, 1]:.4f}  log {np.corrcoef(np.log(forecast), np.log(level))[0, 1]:.4f}")
    print(
        f"QLIKE vs r^2(t+1)  ewma-48 {qlike(level, realised[seen]):.5f}"
        f"  garch {qlike(forecast, realised[seen]):.5f}  (lower is better)"
    )

    per_strategy = replace(model, portfolio=base_params).strategy_targets(panel, membership)
    masked = {k: v.where(support.reindex_like(v)) for k, v in per_strategy.items()}
    for targets, label in ((masked, "common support"), (per_strategy, "unmasked control")):
        rows = [
            measure(name, panel, model, targets, replace(base_params, **arm), exits, cost)  # type: ignore[arg-type]
            for name, arm in ARMS.items()
        ]
        report(rows, f"{universe_mode} universe, {label}: paired per-fold ruler against A0/B0")
        control = next(i for i, row in enumerate(rows) if row["name"].startswith("B1"))
        report(
            [rows[control]] + [row for row in rows if row["name"][0] == "B" and row is not rows[control]],
            f"{universe_mode} universe, {label}: criterion 2 - the HRP arms against the B1 control",
        )
        for row in rows:
            print(f"  folds {row['name']}  " + " ".join(f"{f:+.4f}" for f in row["folds"]))


if __name__ == "__main__":
    for mode in ("pit", "static"):
        run(mode)
