"""Does candidate 2's premise survive the 22:00Z ruler change?

Candidate 2 was "rescale R8's rungs to the REALISED yardstick - on this data a -35% realised reading is
about a -70% mark-to-market one, so the rungs would have to come down to about -17%".  That premise is
about a ruler that R8 stopped reading at 2026-09-13T22:00Z.  This counts, on the mark-to-market path
the new ruler follows, how often each rung would be crossed at k=0.60.

Replay, not a search: the weight path is the shipped construction and nothing is being chosen.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

SHARED = Path("~/starquant")
sys.path.insert(0, str(SHARED))

from starquant_alpha.backtest import run_backtest  # noqa: E402
from starquant_alpha.overlays.exits import ExitParams, apply_exits  # noqa: E402
from starquant_alpha.overlays.exposure import BookGuardParams  # noqa: E402
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols  # noqa: E402
from starquant_live.composition import build_model, cost_model, load_registry  # noqa: E402
from starquant_shared.config import load_yaml  # noqa: E402

K = 0.60
DATA = str(SHARED / ".starquant/data")
RUNGS = {"rescaled_-0.17": -0.17, "shipped_rung1_-0.35": -0.35, "shipped_rung2_-0.50": -0.50}


def main(mode: str) -> None:
    profile = load_yaml(str(SHARED / "config/live.demo.yaml"))
    registry = load_registry(SHARED / "config/alpha_registry.yaml")
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml(str(SHARED / "config/costs.yaml")), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(pf["max_weight"]),
        max_gross=float(pf["max_gross"]),
        daily_loss_pause=float(profile["guards"]["daily_loss_pause"]),
    )
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = K
    w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
    result = run_backtest(panel, w, cost, guards=guards)

    net = np.nan_to_num(result.portfolio_net.to_numpy(dtype=float), nan=0.0)
    curve = np.cumprod(1.0 + net)
    dd = curve / np.maximum.accumulate(curve) - 1.0
    bars = len(dd)
    out: dict[str, object] = {
        "mode": mode,
        "bars": bars,
        "worst_mark_to_market_drawdown": round(float(dd.min()), 6),
    }
    for label, level in RUNGS.items():
        crossed = int((dd <= level).sum())
        # distinct episodes: a crossing that follows a bar above the level starts a new one
        below = dd <= level
        episodes = int(np.sum(below & ~np.concatenate(([False], below[:-1]))))
        out[label] = {"bars_below": crossed, "share_of_bars": round(crossed / bars, 4), "episodes": episodes}
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
