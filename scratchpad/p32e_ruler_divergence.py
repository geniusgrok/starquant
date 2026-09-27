"""P32e: the ruler R8 actually reads, against the ruler P32b/P32c/p32d replayed it with.

E-015 recorded this as a limitation with the net effect unquantified.  After the 2026-09-14 audit it
is decisive rather than marginal: the whole value of the shipped ladder in `p32d`'s method B comes
from it firing inside a deep drawdown, and the live ruler may not see that drawdown at all.

The two rulers, read off `starquant_live/risk_budget.py:223-262`:

  live   `path = base + cumsum(attributed)`, base = the account's TOTAL equity at the first priced
         cycle (52.65% of it non-USDT collateral today), and `attributed` counts income rows only -
         realised P&L, funding and fees.  Unrealised P&L is invisible to it.  The path is LINEAR in
         USDT, not compounding.
  replay `equity *= 1 + net`, i.e. the book's own mark-to-market NAV.  Every adverse bar shows up the
         moment it happens.

A momentum book holds losers unrealised, so the live ruler must lag.  This measures by how much, on
the same 2021-2026 panel the k decision was made on, plus the divergence already visible on the 295
live cycles.

Realised-P&L reconstruction: per symbol, mark-to-market P&L accumulates in an unrealised bucket and
is booked when the position shrinks, proportionally to the shrink (average-cost convention, which is
what a cross-margin venue uses); a sign flip books all of it.  Fees and funding are realised on the
bar they are charged.  By construction `cumsum(realised) + unrealised == cumsum(mark-to-market)` at
every bar, which the script asserts.

APPROXIMATIONS, stated because they bound what this can claim:
  * the ladder's scalar is applied to the realised NET series rather than re-deriving the weight path
    (P32b's approximation, inherited): P&L is linear in position size, so scaling the book by s scales
    both rulers by s, but turnover cost is scaled with the position instead of re-derived.
  * `base` is taken as the book's own equity (1.0).  Live's base is the TOTAL account equity, which is
    LARGER than the book's - so the same realised loss is a SMALLER fraction of it and live triggers
    even later than this reports.  The bias runs with the finding, not against it.

    python scratchpad/p32e_ruler_divergence.py pit|static
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "scratchpad")

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

K = 0.60
# The klines, the live record and the venue state live in the MAIN checkout and are shared across
# worktrees; memory of every earlier round: read them, never rewrite them.  `_resolve_symbols` and
# `_membership` are read-only (they open the membership parquet and `universe.json` and nothing else),
# which is why an unarmed run here cannot disturb what the loop holds.
SHARED = Path("~/starquant")
DATA = str(SHARED / ".starquant/data")
CYCLES = SHARED / ".starquant/live/cycles.jsonl"


def drawdown_path(series: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(series)
    return series / np.where(peak > 0, peak, 1.0) - 1.0


def realised_split(weights: np.ndarray, rets: np.ndarray, costs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(realised, mark_to_market) per bar, in fractions of equity.

    `weights[t]` is the row held THROUGH bar t, so the position change that books P&L is
    `weights[t] -> weights[t + 1]`.
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
        shrink = np.zeros(n_sym)
        live = held > 1e-12
        same_side = live & (np.sign(nxt) == np.sign(weights[t]))
        shrink[same_side] = np.clip(1.0 - np.abs(nxt[same_side]) / held[same_side], 0.0, 1.0)
        shrink[live & ~same_side] = 1.0  # flat or flipped: the whole position closed
        booked = shrink * unrealised
        realised[t] += float(booked.sum())
        unrealised -= booked
    return realised, mark


def replay(mark: np.ndarray, realised: np.ndarray, base: float, policy: Policy, ruler: str) -> dict[str, float]:
    """Sequential ladder replay under one of the two rulers.

    Equity always compounds on mark-to-market - that is what the account is worth.  What differs is
    what the LADDER reads: `mtm` reads that equity curve, `realised` reads `base + cumsum(attributed)`
    the way `attributed_drawdown_state` builds it, linear in absolute units.
    """
    equity = hwm_mtm = 1.0
    path = peak = base
    cycles, standing = 0, None
    scalars = np.ones(len(mark))
    stepped = np.empty(len(mark))
    ruler_path = np.empty(len(mark))
    first_trip: int | None = None
    for t in range(len(mark)):
        drawdown = (equity / hwm_mtm - 1.0) if ruler == "mtm" else (path / peak - 1.0 if peak > 0 else 0.0)
        rung = policy.throttle_scalar(drawdown)
        if rung is None:
            cycles, standing = 0, None
        else:
            cycles += 1
            standing = rung if cycles > policy.drawdown_grace_cycles else standing
        scalar = (standing / K) if standing is not None else 1.0
        scalars[t] = scalar
        if scalar < 1.0 - 1e-9 and first_trip is None:
            first_trip = t
        path += scalar * realised[t] * equity
        stepped[t] = scalar * mark[t]
        equity *= 1.0 + stepped[t]
        peak = max(peak, path)
        hwm_mtm = max(hwm_mtm, equity)
        ruler_path[t] = path
    years = len(mark) / 8760.0
    return {
        "ruler": ruler,
        "throttled_share": float((scalars < 1.0 - 1e-9).mean()),
        "first_trip_bar": -1 if first_trip is None else int(first_trip),
        "cagr": float(np.prod(1.0 + stepped) ** (1.0 / years) - 1.0),
        "mdd_mark_to_market": float(drawdown_path(np.cumprod(1.0 + stepped)).min()),
        "mdd_as_the_ruler_sees_it": float(drawdown_path(ruler_path).min()),
    }


def live_divergence() -> dict[str, float] | None:
    """The same two rulers on the 295 live cycles.  Neither is near a rung; the point is the RATIO.

    `throttle.drawdown` is venue equity below its high-water mark, reported as a non-negative
    fraction (`overlays/exposure.py:41`).  `risk_ladder.drawdown` is the attributed ruler, negative.
    """
    rows = [json.loads(line) for line in CYCLES.read_text().splitlines() if line.strip()]
    pairs = [
        (abs(float(r["throttle"]["drawdown"])), abs(float(r["risk_ladder"]["drawdown"])))
        for r in rows
        if isinstance(r.get("throttle"), dict)
        and isinstance(r.get("risk_ladder"), dict)
        and r["throttle"].get("drawdown") is not None
        and r["risk_ladder"].get("drawdown") is not None
    ]
    if not pairs:
        return None
    equity_dd = np.array([p[0] for p in pairs])
    attributed_dd = np.array([p[1] for p in pairs])
    deeper = equity_dd > attributed_dd + 1e-12
    return {
        "cycles": len(pairs),
        "equity_ruler_worst": float(equity_dd.max()),
        "attributed_ruler_worst": float(attributed_dd.max()),
        "cycles_where_equity_ruler_is_deeper": int(deeper.sum()),
        "median_ratio_equity_over_attributed": float(
            np.median(equity_dd[attributed_dd > 1e-9] / attributed_dd[attributed_dd > 1e-9])
        ) if (attributed_dd > 1e-9).any() else None,
    }


def main(mode: str) -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", mode), "1h", None, None, True)
    membership = _membership(DATA, mode, panel, 0)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    pf = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(max_weight=float(pf["max_weight"]), max_gross=float(pf["max_gross"]),
                             daily_loss_pause=float(profile["guards"]["daily_loss_pause"]))
    tuned = copy.deepcopy(profile)
    tuned.setdefault("portfolio", {})["vol_target"] = K
    w, _c, _p = build_model(registry, tuned).evaluate(panel, membership)
    w = apply_exits(w, panel.close, exits).weights if exits.enabled else w
    result = run_backtest(panel, w, cost, guards=guards)
    weights = np.nan_to_num(result.weights.to_numpy(dtype=float), nan=0.0)
    rets = np.nan_to_num(result.asset_returns.to_numpy(dtype=float), nan=0.0)
    costs = np.nan_to_num(result.costs.to_numpy(dtype=float), nan=0.0)
    realised, mark = realised_split(weights, rets, costs)
    assert abs(realised.sum() - mark.sum()) < 1e-6, "the split must conserve total P&L"

    # the two rulers, unthrottled, on the same path
    mtm_curve = np.cumprod(1.0 + mark)
    realised_curve = 1.0 + np.cumsum(realised * np.concatenate(([1.0], mtm_curve[:-1])))
    dd_mtm = drawdown_path(mtm_curve)
    dd_real = drawdown_path(realised_curve)
    trip = np.flatnonzero(dd_mtm <= -0.35)
    out: dict[str, object] = {
        "mode": mode,
        "bars": len(mark),
        "worst_drawdown_mark_to_market": float(dd_mtm.min()),
        "worst_drawdown_realised_ruler": float(dd_real.min()),
        "bars_past_rung1_mark_to_market": int((dd_mtm <= -0.35).sum()),
        "bars_past_rung1_realised_ruler": int((dd_real <= -0.35).sum()),
        "bars_past_rung2_mark_to_market": int((dd_mtm <= -0.50).sum()),
        "bars_past_rung2_realised_ruler": int((dd_real <= -0.50).sum()),
        "realised_lag_at_first_mtm_trip": (
            None if trip.size == 0 else {"bar": int(trip[0]), "mtm": float(dd_mtm[trip[0]]),
                                         "realised": float(dd_real[trip[0]])}
        ),
        "live": live_divergence(),
    }
    for ruler in ("mtm", "realised"):
        out[f"replay_{ruler}"] = replay(mark, realised, 1.0, Policy(), ruler)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    Path(f"scratchpad/p32e-{mode}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pit")
