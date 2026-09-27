"""`exempt_reductions=False` is bit-for-bit the code that was there before, on the real panel.

The knob widens T-S03's participation cap from "a full close is exempt" to "every reduce-only order is
exempt" (2026-09-13 review).  That is a live behaviour change and it moves backtest numbers, so it
ships off by default and the default has to be provably inert - not "the tests still pass", but the
shipped book scored on `.starquant/data` and compared against the pre-change source itself.

What this does, and changes nothing while doing it:

1. loads ``starquant_alpha/backtest.py`` and ``starquant_live/rebalancer.py`` as they were at ``BASELINE_REV``
   and imports them side by side with the current ones;
2. scores the shipped book (registry main + sleeve, profile exits, profile guards, funding costs) under
   both, with the participation instrument on, and compares weights, gross, costs, net, turnover and
   every ``guard_events`` column exactly;
3. replays a grid of (held, target, liquidity) through both rebalancers and compares every planned
   order and every skip record field by field;
4. then prints what the knob would read at ``True``, per capital, as the number the operator decides on.

Step 4 is a reading, not a proposal.  Nothing here writes to the trial ledger, the registry or any
config, and it never runs `research validate`/`mine`/`book`/`overlay`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pandas as pd

from starquant_alpha.backtest import ParticipationModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel, interval_seconds
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.config import load_yaml
from starquant_shared.types import InstrumentRules, Position

# The commit this worktree branched from, pinned rather than spelled `HEAD`: once the change is
# committed, `HEAD` is the changed source and the comparison becomes vacuous.
BASELINE_REV = "1db3e611"
INTERVAL = "1h"
CAPITALS = (1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0)
# `.starquant/data` is the convention; a git worktree does not carry it, so fall back to the main checkout.
DATA_ROOTS = (".starquant/data", "~/starquant/.starquant/data")


def _check_tree() -> None:
    """`python scratchpad/x.py` puts the SCRIPT's directory on sys.path, not the working directory.

    In a git worktree that means `starquant_alpha` resolves through the editable install to the main
    checkout, and this script would then compare that tree's source against this tree's baseline and
    report a difference that is not there.  Run it as
    ``PYTHONPATH=. .venv/bin/python scratchpad/participation_exempt_reductions_identity.py``.
    """
    import starquant_alpha.backtest as current

    here = Path(__file__).resolve().parents[1]
    loaded = Path(current.__file__ or "").resolve()
    if here not in loaded.parents:
        raise SystemExit(f"starquant_alpha loaded from {loaded}, not from this tree ({here}); set PYTHONPATH=.")


def _data_root() -> str:
    for candidate in DATA_ROOTS:
        if Path(candidate).is_dir():
            return candidate
    raise SystemExit(f"no kline store found in {DATA_ROOTS}")


def _module_at(rev: str, relative: str, name: str) -> ModuleType:
    """Import one file as it was at ``rev``, alongside the current one."""
    source = subprocess.run(
        ["git", "show", f"{rev}:{relative}"], capture_output=True, text=True, check=True
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _shipped_book() -> tuple[Panel, pd.DataFrame, object, BookGuardParams, float, int]:
    root = _data_root()
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    chosen = _resolve_symbols(root, "", INTERVAL, "pit")
    panel = _load(root, chosen, INTERVAL, None, None, True)
    membership = _membership(root, "pit", panel, 0)
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
    return panel, weights, cost, guards, rate, window


def _assert_identical(before: object, after: object, label: str) -> None:
    pd.testing.assert_frame_equal(before.weights, after.weights)  # type: ignore[attr-defined]
    pd.testing.assert_frame_equal(before.gross, after.gross)  # type: ignore[attr-defined]
    pd.testing.assert_frame_equal(before.costs, after.costs)  # type: ignore[attr-defined]
    pd.testing.assert_frame_equal(before.net, after.net)  # type: ignore[attr-defined]
    pd.testing.assert_series_equal(before.turnover, after.turnover)  # type: ignore[attr-defined]
    pd.testing.assert_frame_equal(before.guard_events, after.guard_events)  # type: ignore[attr-defined]
    assert before.summary() == after.summary(), label  # type: ignore[attr-defined]
    print(f"  {label}: identical (weights, gross, costs, net, turnover, guard_events, summary)")


def _live_grid_is_identical(baseline: ModuleType) -> None:
    """Every (held, target, liquidity) combination the cap can see, through both rebalancers."""
    from decimal import Decimal

    rules = {
        "BTCUSDT": InstrumentRules("BTCUSDT", Decimal("0.10"), Decimal("0.001"), Decimal("0.001"), Decimal("100"))
    }
    price = 60_000.0
    equity = 10_000.0
    compared = 0
    for held_weight in (-0.15, -0.12, -0.04, 0.0, 0.04, 0.12, 0.15):
        for target in (-0.15, -0.12, -0.04, 0.0, 0.04, 0.12, 0.15):
            for liquidity in (None, 0.0, 1_000.0, 10_000.0, 10_000_000.0):
                positions = (
                    {"BTCUSDT": Position("BTCUSDT", held_weight * equity / price, price, price)}
                    if held_weight
                    else {}
                )
                kwargs: dict[str, object] = {
                    "managed_symbols": ["BTCUSDT"],
                    "equity": equity,
                    "positions": positions,
                    "prices": {"BTCUSDT": price},
                    "rules": rules,
                    "bar_open_ms": 0,
                    "liquidity": None if liquidity is None else {"BTCUSDT": liquidity},
                }
                old_orders, old_skipped = baseline.plan_rebalance(
                    {"BTCUSDT": target}, params=baseline.RebalanceParams(max_participation=0.02), **kwargs
                )
                new_orders, new_skipped = plan_rebalance(
                    {"BTCUSDT": target},
                    params=RebalanceParams(max_participation=0.02, exempt_reductions=False),
                    **kwargs,
                )
                assert [o.to_dict() for o in old_orders] == [o.to_dict() for o in new_orders], (
                    held_weight,
                    target,
                    liquidity,
                )
                assert old_skipped == new_skipped, (held_weight, target, liquidity)
                compared += 1
    print(f"  live half: {compared} (held, target, liquidity) combinations, order-for-order identical")


def main() -> None:
    _check_tree()
    baseline_backtest = _module_at(BASELINE_REV, "starquant_alpha/backtest.py", "baseline_backtest")
    baseline_rebalancer = _module_at(BASELINE_REV, "starquant_live/rebalancer.py", "baseline_rebalancer")
    print(f"baseline = {BASELINE_REV}\n")

    panel, weights, cost, guards, rate, window = _shipped_book()
    print(f"panel: {len(panel.close)} bars x {len(panel.symbols)} symbols, max_participation={rate} window={window}")

    print("\n[1] exempt_reductions=False vs the pre-change source, shipped book, per capital")
    for capital in CAPITALS:
        before = baseline_backtest.run_backtest(
            panel,
            weights,
            cost,
            guards=guards,
            participation=baseline_backtest.ParticipationModel(capital, rate, window),
        )
        after = run_backtest(
            panel,
            weights,
            cost,
            guards=guards,
            participation=ParticipationModel(capital, rate, window, exempt_reductions=False),
        )
        _assert_identical(before, after, f"capital {capital:,.0f}")

    print("\n[2] the live half at exempt_reductions=False vs the pre-change rebalancer")
    _live_grid_is_identical(baseline_rebalancer)

    print("\n[3] the reading at exempt_reductions=True - a number for the operator, not a proposal")
    base_sharpe = run_backtest(panel, weights, cost, guards=guards).summary()["annualized_sharpe"]
    print(f"    baseline net Sharpe {base_sharpe:.4f} (the instrument must not move it at either setting)")
    header = f"{'capital':>14} {'refused False':>15} {'refused True':>14} {'capped bars False':>19} {'True':>8}"
    print(header)
    print("-" * len(header))
    for capital in CAPITALS:
        row = []
        for exempt in (False, True):
            result = run_backtest(
                panel,
                weights,
                cost,
                guards=guards,
                participation=ParticipationModel(capital, rate, window, exempt_reductions=exempt),
            )
            assert result.summary()["annualized_sharpe"] == base_sharpe, "the instrument moved the book"
            row.append(result.summary()["guards"])
        print(
            f"{capital:>14,.0f} {row[0]['refused_turnover_share']:>14.2%} {row[1]['refused_turnover_share']:>13.2%} "
            f"{row[0]['participation_capped_bars']:>19,} {row[1]['participation_capped_bars']:>8,}"
        )


if __name__ == "__main__":
    main()
