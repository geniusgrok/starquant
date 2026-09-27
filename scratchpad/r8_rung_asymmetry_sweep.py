"""Is the rung's 785-vs-1 split between universes a structural difference, or a knife edge?

At k=0.60 the shipped first rung (-35%) is crossed on 785 pit bars and 1 static bar.  Read as a
structural fact that says the brake means something completely different depending on which universe
you believe.  But pit's worst mark-to-market drawdown is -39.85% and static's is -35.29%, so the rung
sits 0.29pp inside static's deepest point and 4.85pp inside pit's - which is the shape of a threshold
that happens to land where one curve ends, not of two different books.

This sweeps the threshold instead of reading one point, on both universes.  A knife edge shows up as
static's count collapsing across a fraction of a percentage point while pit's changes smoothly.

Replay of the shipped construction; nothing is chosen and no ledger row is written.

    python asym.py
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


def drawdown(mode: str) -> np.ndarray:
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
    net = np.nan_to_num(run_backtest(panel, w, cost, guards=guards).portfolio_net.to_numpy(dtype=float), nan=0.0)
    curve = np.cumprod(1.0 + net)
    return curve / np.maximum.accumulate(curve) - 1.0


def main() -> None:
    paths = {mode: drawdown(mode) for mode in ("pit", "static")}
    out: dict[str, object] = {
        "vol_target": K,
        "worst": {mode: round(float(dd.min()), 6) for mode, dd in paths.items()},
        "bars": {mode: len(dd) for mode, dd in paths.items()},
    }
    sweep = []
    for level in [round(-0.20 - 0.01 * i, 2) for i in range(26)]:
        row: dict[str, object] = {"level": level}
        for mode, dd in paths.items():
            below = dd <= level
            row[f"{mode}_bars"] = int(below.sum())
            row[f"{mode}_episodes"] = int(np.sum(below & ~np.concatenate(([False], below[:-1]))))
        sweep.append(row)
    out["sweep"] = sweep
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
