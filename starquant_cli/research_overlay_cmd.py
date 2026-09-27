"""``starquant research overlay``：退出层的网格扫描。

它量的是**裸 ensemble**。RESEARCH_LOG 2026-09-08 写死了这条协议：判据评的是不带 shipped
exits 的裸 ensemble，所以它与每一条 D-017 裁决可比。给它套上线的 exits 会打断那个可比性。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import click

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import DrawdownThrottleParams, apply_drawdown_throttle
from starquant_alpha.panel import interval_seconds
from starquant_alpha.registry import registry_fingerprint
from starquant_alpha.report import render_markdown
from starquant_alpha.signals import get_signal
from starquant_alpha.validation.ledger import (
    TrialRecord,
    resolve_ledger_path,
)
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli import research
from starquant_cli.research_book_eval import _overlay_metrics
from starquant_cli.research_feature_store import with_feature_store
from starquant_cli.research_grids import (
    DEFAULT_EXIT_GRID,
    DEFAULT_THROTTLE_GRID,
    _grid,
    _grid_of,
)
from starquant_cli.research_ledger_io import (
    _construction_digest,
    _record_trial,
    _short_digest,
    _symbol_set_hash,
)
from starquant_cli.research_options import UNIVERSE_MODES

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_cli.research_panel import (
    _funding_facts,
    _load,
    _membership,
    _require_funding,
    _resolve_symbols,
)
from starquant_cli.research_report import (
    _fmt,
    _stamp,
    _write,
)
from starquant_live.composition import (
    build_model,
    cost_model,
    load_registry,
)
from starquant_shared.config import load_yaml


@research.command("overlay")
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--symbols", default="", help="comma-separated; default = selected universe or all stored")
@click.option("--interval", default="1h", show_default=True)
@click.option("--from", "start", default=None, help="YYYY-MM-DD inclusive")
@click.option("--to", "end", default=None, help="YYYY-MM-DD exclusive")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--registry", "registry_path", default="config/alpha_registry.yaml", show_default=True)
@click.option("--costs", "costs_path", default="config/costs.yaml", show_default=True)
@click.option("--funding/--no-funding", default=True, show_default=True)
@click.option("--out", default="reports/research", show_default=True)
@click.option("--min-history", default=None, type=int)
@click.option("--universe", "universe_mode", type=click.Choice(list(UNIVERSE_MODES)), default="static")
@click.option("--exits-grid", default="", help="JSON {param: [values...]} (default: the pre-registered grid)")
@click.option("--throttle-grid", default="", help="JSON {param: [values...]} (default: the pre-registered grid)")
@click.option("--folds", default=5, show_default=True)
@click.option("--min-train", default=4000, show_default=True)
@click.option(
    "--max-sharpe-loss",
    default=0.10,
    show_default=True,
    help="D-017: a candidate qualifies only if OOS max drawdown improves and OOS Sharpe loses at most this much",
)
def research_overlay(
    root: str,
    symbols: str,
    interval: str,
    start: str | None,
    end: str | None,
    profile: str,
    registry_path: str,
    costs_path: str,
    funding: bool,
    out: str,
    min_history: int | None,
    universe_mode: str,
    exits_grid: str,
    throttle_grid: str,
    folds: int,
    min_train: int,
    max_sharpe_loss: float,
) -> None:
    """Evidence for the exit overlay and the drawdown throttle on the registry ensemble (D-012/D-015/D-017)."""
    profile_payload = load_yaml(profile)
    registry = load_registry(registry_path)
    model = build_model(registry, profile_payload)
    if min_history is not None:
        # `replace`, not a hand-listed constructor: the hand-listed one omitted `books=`, so
        # `--min-history` died on any registry declaring a sleeve - the shipped one does (D-018) - before
        # it could reach the data.  Re-listing fields is the bug; carrying them all is the fix.
        model = replace(model, min_history_bars=min_history)
    model = with_feature_store(model)  # after `replace`, so the store rides on the final model
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    panel = _load(root, chosen, interval, start, end, funding)
    _require_funding(model.entries, panel)
    membership = _membership(root, universe_mode, panel)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    bpy = panel.bars_per_year
    weights, _combined, _per = model.evaluate(panel, membership)
    base = run_backtest(panel, weights, cost)
    baseline = _overlay_metrics(base, folds, min_train, bpy)
    bars_per_day = max(1, 86_400 // interval_seconds(interval))
    exit_combos = _grid("exits", exits_grid, {}) if exits_grid else _grid_of(DEFAULT_EXIT_GRID)
    throttle_combos = _grid("throttle", throttle_grid, {}) if throttle_grid else _grid_of(DEFAULT_THROTTLE_GRID)
    rows: list[dict[str, Any]] = []
    click.echo(
        f"ensemble {[e.id for e in model.entries]} on {len(panel.symbols)} symbols x {len(panel.index)} bars; "
        f"baseline oos_sharpe={_fmt(baseline['oos_sharpe'])} oos_mdd={baseline['oos_mdd']:.3f}"
    )
    for combo in exit_combos:
        params = ExitParams.from_mapping({**combo, "bars_per_day": bars_per_day})
        if not params.enabled:
            continue
        overlay = apply_exits(weights, panel.close, params)
        metrics = _overlay_metrics(run_backtest(panel, overlay.weights, cost), folds, min_train, bpy)
        rows.append({"kind": "exits", "params": combo, **metrics, "events": overlay.summary()})
    for combo in throttle_combos:
        throttle = DrawdownThrottleParams.from_mapping({**combo, "enabled": True})
        scaled, scalars = apply_drawdown_throttle(weights, base.portfolio_net.reindex(weights.index), throttle)
        metrics = _overlay_metrics(run_backtest(panel, scaled, cost), folds, min_train, bpy)
        rows.append({"kind": "throttle", "params": combo, **metrics, "mean_scalar": float(scalars.mean())})

    def qualifies(row: dict[str, Any]) -> bool:
        if row["oos_sharpe"] is None or baseline["oos_sharpe"] is None:
            return False
        return bool(
            row["oos_mdd"] > baseline["oos_mdd"] and row["oos_sharpe"] >= baseline["oos_sharpe"] - max_sharpe_loss
        )

    recommendation: dict[str, Any] = {}
    for kind in ("exits", "throttle"):
        qualified = [row for row in rows if row["kind"] == kind and qualifies(row)]
        best = max(qualified, key=lambda row: float(row["oos_sharpe"])) if qualified else None
        recommendation[kind] = {
            "enable": best is not None,
            "params": None if best is None else best["params"],
            "qualified": len(qualified),
            "tested": sum(1 for row in rows if row["kind"] == kind),
            "rule": f"oos_mdd improves and oos_sharpe >= baseline - {max_sharpe_loss}; tie-break: highest oos_sharpe",
        }
    report: dict[str, Any] = {
        "kind": "overlay",
        "strategies": [e.id for e in model.entries],
        # D-024: an overlay decides on the ensemble, so it is only valid for the registry it ran against.
        "registry": registry_fingerprint(registry, lambda sid, params: get_signal(sid).canonical_params(params)),
        "portfolio": model.portfolio.__dict__,
        "interval": interval,
        "universe_mode": universe_mode,
        "symbols": panel.symbols,
        "range": {"start": str(base.weights.index[0]), "end": str(base.weights.index[-1]), "bars": len(base.weights)},
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts(model.entries, panel),
        "folds": folds,
        "min_train": min_train,
        "baseline": baseline,
        "candidates": rows,
        "recommendation": recommendation,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    # DL-K1 / E-15: an overlay grid is a search over the PORTFOLIO layer, and it was free.  Each
    # candidate is charged to every strategy in the book it was chosen on top of - the overlay was
    # selected by looking at the returns those signals produce, so the selection pressure lands on
    # them.  This is also the case that makes the signature extension load-bearing: every row here
    # shares one param_key, one range, one symbol set and one construction, and differs ONLY in the
    # overlay.  Under the old four-field signature all twelve folded into a single trial.
    ledger_path = resolve_ledger_path(out=out)
    stamp = datetime.now(UTC).isoformat()
    charged = 0
    construction = _construction_digest(report["portfolio"], cost, execution="open_to_close")
    symbol_hash = _symbol_set_hash(panel.symbols)
    for entry in model.entries:
        for row in rows:
            charged += _record_trial(
                ledger_path,
                TrialRecord(
                    strategy=entry.id,
                    param_key=param_key(dict(entry.params)),
                    sharpe_annual=row["full_sharpe"],
                    bars_per_year=bpy,
                    recorded_at=stamp,
                    range_start=str(base.weights.index[0]),
                    range_end=str(base.weights.index[-1]),
                    symbols=len(panel.symbols),
                    run_id="",
                    construction_digest=construction,
                    symbol_set_hash=symbol_hash,
                    overlay_digest=_short_digest({"kind": row["kind"], "params": row["params"]}),
                ),
            )
    report["ledger"] = {"path": str(ledger_path), "charged": charged, "candidates": len(rows)}
    lines = [
        f"{row['kind']} {json.dumps(row['params'])}: oos_sharpe={_fmt(row['oos_sharpe'])} "
        f"oos_mdd={row['oos_mdd']:.3f} full_sharpe={_fmt(row['full_sharpe'])} full_mdd={row['full_mdd']:.3f} "
        f"folds={[round(x, 2) if x is not None else None for x in row['fold_sharpes']]} "
        f"{'QUALIFIES' if qualifies(row) else '-'}"
        for row in rows
    ]
    markdown = render_markdown(
        "Overlay evidence: " + ", ".join(report["strategies"]),
        [
            ("Range", report["range"]),
            (
                "Registry this was computed against (D-024)",
                {
                    "digest": report["registry"]["digest"],
                    "ensemble": report["registry"]["ensemble_method"],
                    "books": json.dumps(report["registry"]["books"]),
                    **{
                        f"{sid} params": json.dumps(row["params"], sort_keys=True)
                        for sid, row in report["registry"]["strategies"].items()
                    },
                },
            ),
            ("Baseline (no overlay)", {k: v for k, v in baseline.items() if k != "fold_sharpes"}),
            ("Candidates", lines),
            ("Recommendation (D-017)", {k: json.dumps(v) for k, v in recommendation.items()}),
        ],
    )
    path, digest = _write(out, f"overlay-{_stamp()}", report, markdown)
    for line in lines:
        click.echo(line)
    click.echo(f"recommendation: {json.dumps(recommendation)}")
    click.echo(f"registry digest: {report['registry']['digest']}")
    click.echo(f"report: {path} sha256={digest}")
