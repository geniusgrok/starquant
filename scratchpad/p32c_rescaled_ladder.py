"""P32c: k=0.60 with the R8 ladder RESCALED to the new budget - the arm P32b did not test.

P32b showed the shipped ladder (hardcoded -0.35 -> 0.225, -0.50 -> 0.15) costs 16.3pp of CAGR at
k=0.60 and buys no drawdown.  That is the ladder at its ORIGINAL calibration, which was written for
k=0.30 against a 50% budget.  Before concluding "0.60 is a bad rung", the honest comparison is 0.60
with the ladder re-derived for the budget the operator just declared.

The rescale is a TRANSCRIPTION of the existing rule, not a new rule - the shipped numbers read, as
fractions of their own calibration:
    deescalate_at = 70% of budget ,  rollback_at = 100% of budget
    deescalate_to = 75% of k      ,  rollback_to = 50%  of k
At budget 70%: k=0.60 -> ((-0.49, 0.45), (-0.70, 0.30));  k=0.75 -> ((-0.49, 0.5625), (-0.70, 0.375)).

Also reports the bootstrapped q95 of the THROTTLED series, because P32's q95 was measured on the
un-throttled one and the throttle changes the very tail it is supposed to control.

SUPERSEDED for every q95 and P(breach) number below by `p32d_ladder_bootstrap_pathwise.py`
(2026-09-14, `docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md`).  Two defects, and the
paragraph above names the right problem while `q95_of` only half-solves it:

  1. `q95_of` resamples `thr`, whose throttle scalars were decided on the HISTORICAL ordering, so a
     draw deep enough to matter carries the protection history happened to earn at those bar
     positions instead of the protection the ladder would have applied to that draw.  Replaying the
     ladder inside each draw moves the shipped arm from -70.8% to -52.6% and reverses C-006.
  2. Both arms are replayed against the book's mark-to-market NAV, and R8 does not read that.  Under
     the ruler it does read - `base + cumsum(attributed)`, income rows only - the shipped ladder gets
     q95 -69.3% against the rescaled arm's -69.9%, i.e. almost no ladder at all (p32e, p32d).

This file is left running exactly as it ran, numbers included: E-010 and C-006 cite it, and rewriting
the evidence underneath a claim is how a record stops being one.
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

sys.path.insert(0, "scratchpad")
from p32b_r8_ladder_replay import drawdown_path, replay_ladder

BUDGET = 0.70
ARMS = {0.45: None, 0.60: None, 0.75: None}
BLOCK, DRAWS, SEED = 168, 2000, 20260904


def rescaled(k: float) -> tuple[tuple[float, float], ...]:
    return ((-0.70 * BUDGET, 0.75 * k), (-1.00 * BUDGET, 0.50 * k))


def q95_of(net: np.ndarray, rng) -> tuple[float, float]:
    blocks = len(net) // BLOCK
    draws = np.empty(DRAWS)
    for d in range(DRAWS):
        st = rng.integers(0, len(net) - BLOCK, size=blocks)
        draws[d] = float(drawdown_path(np.concatenate([net[s : s + BLOCK] for s in st])).min())
    return float(np.percentile(draws, 5)), float((draws <= -0.50).mean())


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(".starquant/data", _resolve_symbols(".starquant/data", "", "1h", mode), "1h", None, None, True)
    membership = _membership(".starquant/data", mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(max_weight=float(pf["max_weight"]), max_gross=float(pf["max_gross"]),
                             daily_loss_pause=float(profile["guards"]["daily_loss_pause"]))
    years = len(panel.close) / panel.bars_per_year
    print(f"[{mode}] budget {BUDGET:.0%}; rescaled rungs are a transcription of the shipped rule")
    print(f"{'k':>6}{'arm':>12}{'CAGR':>9}{'IS MDD':>9}{'q95 MDD':>10}{'P<-50%':>9}{'throttled':>11}")
    out = []
    for k in ARMS:
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = k
        w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
        w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
        net = np.nan_to_num(run_backtest(panel, w, cost, guards=guards).portfolio_net.to_numpy(), nan=0.0)
        for name, rungs in (("shipped R8", Policy().drawdown_ladder), ("rescaled R8", rescaled(k))):
            thr, sc = replay_ladder(net, k, replace(Policy(), drawdown_ladder=tuple(rungs)))
            cagr = float(np.prod(1.0 + thr) ** (1.0 / years) - 1.0)
            mdd = float(drawdown_path(thr).min())
            q95, p50 = q95_of(thr, np.random.default_rng(SEED))
            share = float((sc < 1.0 - 1e-9).mean())
            out.append({"vol_target": k, "arm": name, "rungs": list(map(list, rungs)), "cagr": cagr,
                        "is_mdd": mdd, "q95_mdd": q95, "p_breach_50": p50, "throttled_share": share})
            print(f"{k:>6.2f}{name:>12}{cagr:>9.1%}{mdd:>9.1%}{q95:>10.1%}{p50:>9.1%}{share:>11.1%}")
    Path(f"scratchpad/p32c-{mode}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32c-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
