"""``starquant research correlate``：候选与在跑的书的净收益相关。

它要的是净收益序列，所以不套路径依赖的层——这是协议，不是缺陷。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import click
import pandas as pd

from starquant_alpha.backtest import run_backtest
from starquant_alpha.report import render_markdown
from starquant_alpha.validation.metrics import (
    sharpe,
)
from starquant_cli import research
from starquant_cli.research_options import UNIVERSE_MODES

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_cli.research_panel import (
    _entry,
    _funding_facts,
    _load,
    _membership,
    _model,
    _require_funding,
    _resolve_symbols,
)
from starquant_cli.research_report import (
    _stamp,
    _write,
)
from starquant_live.composition import (
    cost_model,
)
from starquant_shared.config import load_yaml


@research.command("correlate")
@click.option("--strategies", required=True, help="comma-separated signal ids (registry params are used)")
@click.option("--grids", default="", help="JSON of enumerate_candidates grids for mined ids")
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--symbols", default="")
@click.option("--interval", default="1h", show_default=True)
@click.option("--from", "start", default=None)
@click.option("--to", "end", default=None)
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--registry", "registry_path", default="config/alpha_registry.yaml", show_default=True)
@click.option("--costs", "costs_path", default="config/costs.yaml", show_default=True)
@click.option("--funding/--no-funding", default=True, show_default=True)
@click.option("--out", default="reports/research", show_default=True)
@click.option("--universe", "universe_mode", type=click.Choice(list(UNIVERSE_MODES)), default="static")
def research_correlate(
    strategies: str,
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
    universe_mode: str,
    grids: str,
) -> None:
    """Correlation of strategy net-return streams and the marginal Sharpe of each strategy in an equal-weight mix."""
    ids = [s.strip() for s in strategies.split(",") if s.strip()]
    profile_payload = load_yaml(profile)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    panel = _load(root, chosen, interval, start, end, funding)
    entries = {strategy: _entry(strategy, registry_path, "", grids) for strategy in ids}
    _require_funding(list(entries.values()), panel)
    membership = _membership(root, universe_mode, panel)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    nets: dict[str, pd.Series] = {}
    for strategy in ids:
        entry = entries[strategy]
        weights, _c, _p = _model(entry, profile_payload, interval).evaluate(panel, membership)
        nets[strategy] = run_backtest(panel, weights, cost).portfolio_net
    frame = pd.DataFrame(nets).dropna(how="all").fillna(0.0)
    bpy = panel.bars_per_year
    corr = frame.corr()
    individual = {k: sharpe(frame[k], bpy) for k in frame.columns}
    combined = sharpe(frame.mean(axis=1), bpy)
    marginal: dict[str, float | None] = {}
    for k in frame.columns:
        rest = [c for c in frame.columns if c != k]
        without = sharpe(frame[rest].mean(axis=1), bpy) if rest else None
        marginal[k] = None if combined is None or without is None else combined - without
    report: dict[str, Any] = {
        "kind": "correlation",
        "strategies": ids,
        "universe_mode": universe_mode,
        "symbols": panel.symbols,
        # every Sharpe and correlation below is NET of these costs, so a report without them cannot be
        # reproduced or compared - and `use_funding` is the field that says how the run was produced.
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts(list(entries.values()), panel),
        "range": {"start": str(frame.index[0]), "end": str(frame.index[-1]), "bars": len(frame)},
        "correlation": corr.round(4).to_dict(),
        "individual_sharpe": individual,
        "equal_weight_sharpe": combined,
        "marginal_sharpe": marginal,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    markdown = render_markdown(
        "Strategy correlation: " + ", ".join(ids),
        [
            ("Range", report["range"]),
            ("Individual Sharpe", individual),
            ("Equal-weight mix Sharpe", {"sharpe": combined}),
            ("Marginal Sharpe (mix minus mix-without)", marginal),
            ("Correlation", {f"{a}~{b}": corr.loc[a, b] for a in corr.index for b in corr.columns if a < b}),
        ],
    )
    path, digest = _write(out, f"correlate-{'-'.join(ids)}-{_stamp()}", report, markdown)
    click.echo(markdown)
    click.echo(f"report: {path} sha256={digest}")
