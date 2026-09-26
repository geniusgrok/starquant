"""P32b: what the LIVE R8 ladder does to the k the operator just chose - which P32 never replayed.

The gap.  `run_backtest(guards=BookGuardParams(...))` replays max_weight, max_gross and
daily_loss_pause.  It does NOT replay R8, the attributed-drawdown ladder in `engine._risk_ladder`,
whose rungs are HARDCODED in `starquant_governance/policy.py:173` as ((-0.35, 0.225), (-0.50, 0.15))
on a frozen dataclass - not read from the profile's `risk_budget` block at all.  So every CAGR in
P32 describes a book without the throttle the live loop will actually apply.  That is KILL-027's
shape: a live-only guardrail making the two halves different instruments.

At vol_target 0.30 the rungs are a 25% and a 50% cut and they sit past the q95.  At 0.60 they are a
62.5% and a 75% cut sitting INSIDE the ordinary drawdown range, so this stops being a tail control
and becomes part of the construction.

APPROXIMATION, stated because it bounds what this can claim: the ladder's scalar is applied to the
realised net series rather than re-running the weight path, so turnover cost is scaled with the
position instead of re-derived from the new path.  Costs are ~7-12% of gross here, and the scalar
only ever shrinks, so this OVERSTATES the throttled arm's return slightly - the bias runs against
the finding, not for it.  The two-cycle grace is replayed exactly.

    python scratchpad/p32b_r8_ladder_replay.py pit|static
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

VOL_TARGETS = (0.30, 0.375, 0.45, 0.60, 0.75)
ROOT = ".starquant/data"
INTERVAL = "1h"


def drawdown_path(net: np.ndarray) -> np.ndarray:
    equity = np.cumprod(1.0 + net)
    return equity / np.maximum.accumulate(equity) - 1.0


def replay_ladder(net: np.ndarray, base: float, policy: Policy) -> tuple[np.ndarray, np.ndarray]:
    """Sequential replay of engine._risk_ladder: rung by attributed drawdown, 2 cycles of grace."""
    equity, hwm, cycles, standing = 1.0, 1.0, 0, None
    out = np.empty_like(net)
    scalars = np.ones_like(net)
    for t, r in enumerate(net):
        drawdown = equity / hwm - 1.0
        rung = policy.throttle_scalar(drawdown)
        if rung is None:
            cycles, standing = 0, None
        else:
            cycles += 1
            standing = rung if cycles > policy.drawdown_grace_cycles else standing
        scalar = (standing / base) if standing is not None else 1.0
        scalars[t] = scalar
        stepped = float(r) * scalar
        out[t] = stepped
        equity *= 1.0 + stepped
        hwm = max(hwm, equity)
    return out, scalars


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(ROOT, _resolve_symbols(ROOT, "", INTERVAL, mode), INTERVAL, None, None, True)
    membership = _membership(ROOT, mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(pf.get("max_weight", 0.15)),
        max_gross=float(pf.get("max_gross", 2.0)),
        daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
    )
    policy = Policy()
    years = len(panel.close) / panel.bars_per_year
    print(f"[{mode}] R8 rungs (hardcoded, policy.py:173): {policy.drawdown_ladder}  grace={policy.drawdown_grace_cycles}")
    print(f"{'k':>6}{'CAGR raw':>10}{'CAGR R8':>10}{'delta':>9}{'MDD raw':>9}{'MDD R8':>9}"
          f"{'bars@.225':>11}{'bars@.15':>10}{'throttled':>11}")
    rows = []
    for k in VOL_TARGETS:
        tuned = copy.deepcopy(profile)
        tuned.setdefault("portfolio", {})["vol_target"] = k
        w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
        w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
        net = run_backtest(panel, w, cost, guards=guards).portfolio_net.to_numpy()
        net = np.nan_to_num(net, nan=0.0)
        throttled, scalars = replay_ladder(net, k, policy)
        cagr_raw = float(np.prod(1.0 + net) ** (1.0 / years) - 1.0)
        cagr_r8 = float(np.prod(1.0 + throttled) ** (1.0 / years) - 1.0)
        mdd_raw = float(drawdown_path(net).min())
        mdd_r8 = float(drawdown_path(throttled).min())
        at225 = int((np.abs(scalars - 0.225 / k) < 1e-9).sum())
        at15 = int((np.abs(scalars - 0.15 / k) < 1e-9).sum())
        share = float((scalars < 1.0 - 1e-9).mean())
        rows.append({"vol_target": k, "cagr_raw": cagr_raw, "cagr_r8": cagr_r8, "mdd_raw": mdd_raw,
                     "mdd_r8": mdd_r8, "bars_at_225": at225, "bars_at_15": at15, "throttled_share": share})
        print(f"{k:>6.3f}{cagr_raw:>10.1%}{cagr_r8:>10.1%}{cagr_r8 - cagr_raw:>9.1%}"
              f"{mdd_raw:>9.1%}{mdd_r8:>9.1%}{at225:>11}{at15:>10}{share:>11.1%}")
    Path(f"scratchpad/p32b-{mode}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"wrote scratchpad/p32b-{mode}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
