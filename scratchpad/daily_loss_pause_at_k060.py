"""What the shipped `daily_loss_pause -0.05` buys at k=0.60, and what the book looks like without it.

A REPLAY of the construction that trades, not a search: the only arms are the shipped setting and the
guard switched off, which is the control the config comment for `vol_target 0.30` already took at the
old k ("daily_loss_pause fires about once a year ... 0 times in 5.6 years at 0.15; 5 and 4 times at
0.30").  That reading has never been taken at 0.60.  No ledger row is written and none is owed:
nothing here picks a new threshold.

The comparison is deliberately marginal - guard on vs the SAME weights with the guard off - so the
difference is the guard and not the construction.  `gross_capped` stays on in both arms, because
turning both guards off would measure a book the loop would not hold (KILL-027's shape).

    python dlp.py pit|static
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

K = 0.60
SHARED = Path("~/starquant")
DATA = str(SHARED / ".starquant/data")


def main(mode: str) -> None:
    profile = load_yaml(str(SHARED / "config/live.demo.yaml"))
    registry = load_registry(SHARED / "config/alpha_registry.yaml")
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml(str(SHARED / "config/costs.yaml")), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = K
    weights, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    weights = apply_exits(weights, panel.close, exits).weights if exits.enabled else weights

    out: dict[str, object] = {"mode": mode, "vol_target": K, "bars": len(panel.index)}
    for label, threshold in (("shipped_-0.05", float(profile["guards"]["daily_loss_pause"])), ("off", -1.0)):
        guards = BookGuardParams(
            max_weight=float(pf["max_weight"]), max_gross=float(pf["max_gross"]), daily_loss_pause=threshold
        )
        result = run_backtest(panel, weights, cost, guards=guards)
        summary = result.summary()
        out[label] = {
            "threshold": threshold,
            "annualized_sharpe": round(float(summary["annualized_sharpe"]), 4),
            "net_return": round(float(summary["net_return"]), 4),
            "max_drawdown": round(float(summary["max_drawdown"]), 6),
            "turnover_units": round(float(summary["turnover_units"]), 1),
            "avg_gross": round(float(summary["average_absolute_exposure"]), 4),
            "daily_loss_pause_bars": summary["guards"]["daily_loss_pause_bars"],
            "gross_capped_bars": summary["guards"]["gross_capped_bars"],
        }
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
