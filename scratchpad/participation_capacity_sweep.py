"""M-017: how much of the shipped book's target turnover would live have refused, by capital.

The vol-target k is scale-free in the backtest because gross P&L, turnover cost and funding are all
linear in the weights (config/live.demo.yaml).  ``max_participation`` is the one live constraint that
is not, so this is the curve that says at what account size that identity stops being a good
approximation and k has to be re-derived under an impact-aware cost model.

It measures and changes nothing: ``ParticipationModel`` is an instrument, and the book it scores is
bit-for-bit the one the loop holds.

2026-09-08 audit: it used to score tsmom alone with no exit overlay, and the curve was read as the
capacity of the shipped book.  Turnover has since roughly doubled - P13 took ``vol_target`` 0.15 -> 0.30
and the exit overlay adds about 10% on top - and the share the cap refuses rises with target turnover,
so the old knee sat to the right of the real one.  It now builds from the registry (main book plus the
flow_short sleeve) and applies the profile's exits, i.e. the same four layers ``research validate``
scores since the same audit.
"""

from __future__ import annotations

from pathlib import Path

from starquant_alpha.backtest import ParticipationModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_shared.config import load_yaml

CAPITALS = (1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0)
ROOT = ".starquant/data"
INTERVAL = "1h"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(ROOT, "", INTERVAL, "pit")
    panel = _load(ROOT, chosen, INTERVAL, None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    model = build_model(registry, profile)
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    weights, _c, _p = model.evaluate(panel, membership)
    bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    if exits.enabled:
        weights = apply_exits(weights, panel.close, exits).weights

    portfolio = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(portfolio.get("max_weight", 0.15)),
        max_gross=float(portfolio.get("max_gross", 2.0)),
        daily_loss_pause=float((profile.get("guards", {}) or {}).get("daily_loss_pause", -0.05)),
    )
    rate = float(portfolio.get("max_participation", 0.02))
    window = int((profile.get("pool", {}) or {}).get("liquidity_window", 24))

    baseline = run_backtest(panel, weights, cost, guards=guards)
    base = baseline.summary()["annualized_sharpe"]
    books = [f"{e.id}({e.book})" for e in model.entries]
    print(f"book={books}  exits={'on' if exits.enabled else 'off'}  bars={len(baseline.weights)}")
    print(f"max_participation={rate}  window={window}  turnover={baseline.summary()['turnover_units']:.1f}")
    print(f"baseline net Sharpe {base:.4f} - unchanged at every capital below, and asserted per row\n")
    print(f"{'capital (USDT)':>16} {'refused turnover':>18} {'capped bars':>13} {'share of bars':>15}")
    print("-" * 66)
    for capital in CAPITALS:
        result = run_backtest(
            panel, weights, cost, guards=guards, participation=ParticipationModel(capital, rate, window)
        )
        g = result.summary()["guards"]
        assert result.summary()["annualized_sharpe"] == base, "the instrument moved the book"
        print(
            f"{capital:>16,.0f} {g['refused_turnover_share']:>17.2%} "
            f"{g['participation_capped_bars']:>13,} {g['participation_capped_bars'] / g['bars']:>14.2%}"
        )


if __name__ == "__main__":
    main()
