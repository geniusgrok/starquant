"""DL-C1 / KILL-A: where the flat cost model stops being a good approximation, by capital.

Written before it ran, so a correction is made in one place.

The backtest is scale-free by arithmetic - gross P&L, turnover cost and funding are all linear in the
weights, so scaling every weight by k leaves the Sharpe identical to the last digit.  That is what makes
`vol_target` a free parameter in the backtest and it is the assumption KILL-Q12 has held real capital
out of scope on since 2026-09-05.  `ImpactModel` breaks the identity on purpose: the square-root law
charges more per unit as the order grows against ADV, so the same book has a different Sharpe at every
account size and there is finally a size at which k has to be re-derived.

**What this can and cannot say.**  The coefficient is an assumption (equities literature, E5 for this
venue) and this system cannot calibrate it.  Read the KNEE, not the levels: the capital at which cost
share starts to bend is a structural statement about this book's turnover against this universe's
depth, and it moves with the coefficient only as sqrt - a coefficient of 0.25 halves every delta.

CORRECTION, made after the first run and left here rather than rewritten: this docstring predicted
"under a hundredth of a basis point" at demo notional, from an order/ADV of about 1e-8.  Measured, the
model attributes about 8.6% of total cost to impact at 10,000 USDT - roughly 0.7 bps, not 0.007.  The
estimate was wrong because it used the liquid names' ADV for the whole book: the thin end of an
18-symbol perp universe is where participation actually bites.  What survives is the conclusion, for a
different reason than stated: 0.7 bps sits well inside the [2.01, 9.19] bps interval of the 101 demo
fills, so that sample can neither confirm nor refute the model - it is not that impact is too small to
matter at demo scale, it is that it is too small to SEPARATE from spread.

It writes nothing - no ledger row, no report, no config.  Scored on the same four layers `research
validate` scores: registry book (tsmom + the flow_short sleeve), exits from the profile, book guards.
"""

from __future__ import annotations

import os
from pathlib import Path

from starquant_alpha.backtest import ImpactModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, impact_model, load_registry
from starquant_shared.config import load_yaml

CAPITALS = (0.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0, 100_000_000.0)
# Overridable so the sweep can run from a worktree against the checkout that holds the archive.
ROOT = os.environ.get("STARQUANT_DATA_ROOT", ".starquant/data")
INTERVAL = "1h"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(ROOT, "", INTERVAL, "pit")
    panel = _load(ROOT, chosen, INTERVAL, None, None, True)
    membership = _membership(ROOT, "pit", panel, 0)
    model = build_model(registry, profile)
    costs_payload = load_yaml("config/costs.yaml")
    cost = cost_model(costs_payload, use_funding=True)
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
    template: ImpactModel = impact_model(costs_payload, capital=0.0)
    books = [f"{e.id}({e.book})" for e in model.entries]
    print(f"book={books}  exits={'on' if exits.enabled else 'off'}  coefficient={template.coefficient}")
    print(f"{'capital (USDT)':>16} {'net Sharpe':>12} {'d vs flat':>11} {'cost/gross':>12} {'impact share':>14}")
    print("-" * 70)
    base = None
    for capital in CAPITALS:
        impact = ImpactModel(
            capital=capital,
            coefficient=template.coefficient,
            adv_window=template.adv_window,
            vol_window=template.vol_window,
        )
        result = run_backtest(panel, weights, cost, guards=guards, impact=impact)
        summary = result.summary()
        sharpe = summary["annualized_sharpe"]
        base = sharpe if base is None else base
        flat = run_backtest(panel, weights, cost, guards=guards).costs.to_numpy().sum()
        total = result.costs.to_numpy().sum()
        impact_share = 0.0 if total == 0 else (total - flat) / total
        print(
            f"{capital:>16,.0f} {sharpe:>12.4f} {sharpe - base:>11.4f} "
            f"{summary['cost_share_of_gross']:>11.2%} {impact_share:>13.2%}"
        )


if __name__ == "__main__":
    main()
