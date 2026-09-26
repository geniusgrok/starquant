"""Independent re-derivation of `p32e`'s backtest half, plus the check it did not run.

Reproduces the four numbers the 2026-09-14 pre-registration (`ede008c9`) cites for k=0.60 - pit
mark-to-market -39.85% / realised -21.27%, 785 bars past the first rung against 0; static -35.29% /
-24.13%, 1 against 0 - from the same construction entry points, with the realised/mark split written
here rather than imported, so agreement is evidence and not a tautology.

The check `p32e` did not run, and the reason this file exists rather than a note saying "I re-ran it":
the whole finding rests on the realised/mark split, and that split has exactly one free choice - WHEN
an open position's paper P&L becomes realised.  A conclusion that depends on the convention is a
conclusion about the convention, so this brackets it:

  eager         realised == mark                  book instantly; the degenerate upper bound
  proportional  book on every shrink, in proportion    `p32e`'s convention
  on_close      book only on a flat or a flip     the most lagging realistic convention

More eager booking tracks the mark path more closely, drives the realised drawdown DEEPER and makes a
rung crossing MORE likely.  `p32e` therefore already picked the end of the realistic range that most
favours crossing; measured here, it still gives zero.  `eager` crosses 785 times, which is the sanity
check that the instrument can fire at all.

Read-only.  Klines, membership and the live record are shared with the running loop and with other
worktrees: this opens them and writes nothing.

    python scratchpad/p32e_ruler_divergence_recheck.py pit|static
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

K = 0.60
RUNG1, RUNG2 = -0.35, -0.50
DATA = ".starquant/data"


def drawdown_path(series: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(series)
    return series / np.where(peak > 0, peak, 1.0) - 1.0


def split(weights: np.ndarray, rets: np.ndarray, costs: np.ndarray, convention: str) -> tuple[np.ndarray, np.ndarray]:
    """(realised, mark) per bar as fractions of equity, under one booking convention.

    `weights[t]` is the row held THROUGH bar t, so what books P&L is the move to `weights[t + 1]`.
    """
    n_bars, n_sym = weights.shape
    unrealised = np.zeros(n_sym)
    realised = np.zeros(n_bars)
    mark = np.zeros(n_bars)
    for t in range(n_bars):
        step = weights[t] * rets[t]
        unrealised += step
        mark[t] = float(step.sum() - costs[t].sum())
        realised[t] = -float(costs[t].sum())  # fees and funding are booked on the bar
        nxt = weights[t + 1] if t + 1 < n_bars else np.zeros(n_sym)
        held = np.abs(weights[t])
        live = held > 1e-12
        same_side = live & (np.sign(nxt) == np.sign(weights[t]))
        shrink = np.zeros(n_sym)
        if convention == "eager":
            shrink[live] = 1.0
        elif convention == "proportional":
            shrink[same_side] = np.clip(1.0 - np.abs(nxt[same_side]) / held[same_side], 0.0, 1.0)
            shrink[live & ~same_side] = 1.0
        elif convention == "on_close":
            shrink[live & ~same_side] = 1.0
        else:
            raise ValueError(convention)
        booked = shrink * unrealised
        realised[t] += float(booked.sum())
        unrealised -= booked
    return realised, mark


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(pf["max_weight"]),
        max_gross=float(pf["max_gross"]),
        daily_loss_pause=float(profile["guards"]["daily_loss_pause"]),
    )
    # `vol_target` is pinned here rather than read from the profile: this script reproduces a k=0.60
    # reading, and re-pricing risk in the profile must not silently re-point it at another book.
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = K
    w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
    result = run_backtest(panel, w, cost, guards=guards)
    weights = np.nan_to_num(result.weights.to_numpy(dtype=float), nan=0.0)
    rets = np.nan_to_num(result.asset_returns.to_numpy(dtype=float), nan=0.0)
    costs = np.nan_to_num(result.costs.to_numpy(dtype=float), nan=0.0)

    out: dict[str, object] = {"mode": mode, "bars": int(weights.shape[0]), "vol_target": K}
    for convention in ("eager", "proportional", "on_close"):
        realised, mark = split(weights, rets, costs, convention)
        assert abs(realised.sum() - mark.sum()) < 1e-6, f"{convention}: the split must conserve total P&L"
        mtm_curve = np.cumprod(1.0 + mark)
        realised_curve = 1.0 + np.cumsum(realised * np.concatenate(([1.0], mtm_curve[:-1])))
        dd_mtm, dd_real = drawdown_path(mtm_curve), drawdown_path(realised_curve)
        out[convention] = {
            "worst_dd_mark_to_market": round(float(dd_mtm.min()), 6),
            "worst_dd_realised_ruler": round(float(dd_real.min()), 6),
            "bars_past_rung1_mtm": int((dd_mtm <= RUNG1).sum()),
            "bars_past_rung1_realised": int((dd_real <= RUNG1).sum()),
            "bars_past_rung2_mtm": int((dd_mtm <= RUNG2).sum()),
            "bars_past_rung2_realised": int((dd_real <= RUNG2).sum()),
        }
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
