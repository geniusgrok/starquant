"""``starquant research diagnose``：信号级诊断（IC-by-horizon），零 ledger。

它回答的是「这个族有没有信息」，与「这本书赚不赚钱」是两个问题——2026-09-17 的读数里
最强的 IC 属于一个书级样本外 −2.29 的族。
"""

from __future__ import annotations

import click
import numpy as np

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.validation.labels import forward_returns
from starquant_alpha.validation.metrics import (
    information_coefficient,
    newey_west_tstat,
    sign_bucketed_ic,
    time_series_ic,
)
from starquant_cli import research
from starquant_cli.research_feature_store import feature_scores
from starquant_cli.research_options import _common_options

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.
from starquant_cli.research_panel import (
    _entry,
    _load,
    _membership,
    _require_funding,
    _resolve_symbols,
)
from starquant_cli.research_report import (
    _echo_summary,
    _fmt,
    _fmt_pct,
)
from starquant_live.composition import (
    cost_model,
)
from starquant_shared.config import load_yaml


@research.command("diagnose")
@_common_options
@click.option("--horizons", default="1,4,24,72,168", show_default=True, help="forward-return horizons (bars) for IC")
def research_diagnose(
    strategy: str,
    params: str,
    root: str,
    symbols: str,
    interval: str,
    start: str | None,
    end: str | None,
    profile: str,
    registry_path: str,
    costs_path: str,
    execution: str,
    funding: bool,
    out: str,
    min_history: int | None,
    universe_mode: str,
    min_tenure: int,
    horizons: str,
    grids: str,
) -> None:
    """Signal-level diagnostics before any portfolio construction: IC by horizon, signal-only backtest, flips."""
    del out  # diagnostics write nothing
    entry = _entry(strategy, registry_path, params, grids)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    panel = _load(root, chosen, interval, start, end, funding)
    _require_funding([entry], panel)
    if min_history is None:
        min_history = int((load_yaml(profile).get("portfolio", {}) or {}).get("min_history_bars", 720))
    eligible = panel.close.notna().cumsum() >= min_history
    membership = _membership(root, universe_mode, panel, min_tenure)
    if membership is not None:
        eligible &= membership
    scores = feature_scores(strategy, entry.params, panel).where(eligible)
    coverage = float(scores.notna().mean().mean())
    click.echo(f"{strategy} on {len(panel.symbols)} symbols x {len(panel.index)} bars; score coverage={coverage:.2f}")
    click.echo("horizon | ts-IC mean (spearman, per-symbol avg) | xs-IC mean | NW t | NW p")
    for horizon in [int(h) for h in horizons.split(",") if h.strip()]:
        fwd = forward_returns(panel.close, horizon)
        ts = [time_series_ic(scores[s], fwd[s]) for s in panel.symbols]
        ts_values = [v for v in ts if v is not None]
        xs = information_coefficient(scores, fwd)
        nw = newey_west_tstat(xs, max_lags=horizon) if len(xs) > 10 else {"t_stat": None, "p_value": None}
        ts_mean = sum(ts_values) / len(ts_values) if ts_values else float("nan")
        click.echo(
            f"{horizon:>7} | {ts_mean:+.4f} | {float(xs.mean()) if len(xs) else float('nan'):+.4f} | "
            f"{_fmt(nw['t_stat'])} | {_fmt(nw['p_value'])}"
        )
    # KILL-042: a negative time-series IC alongside a profitable book.  Non-overlapping labels, split by
    # the sign of the score, so "the magnitude is uninformative" and "the signal is wrong" are separable.
    click.echo("horizon | non-overlapping IC | long bucket: n / IC / mean fwd | short bucket: n / IC / mean fwd")
    for horizon in [int(h) for h in horizons.split(",") if h.strip()]:
        block = sign_bucketed_ic(
            scores, forward_returns(panel.close, horizon), horizon, threshold=entry.entry_threshold
        )
        long_side, short_side = block["long"], block["short"]
        click.echo(
            f"{horizon:>7} | {_fmt(block['overall_ic'])} | "
            f"{long_side['n']} / {_fmt(long_side['ic'])} / {_fmt_pct(long_side['mean_forward_return'])} | "
            f"{short_side['n']} / {_fmt(short_side['ic'])} / {_fmt_pct(short_side['mean_forward_return'])}"
        )
    targets = scores_to_targets(scores, entry.entry_threshold, hold=True)
    flips = int((targets.fillna(0.0).apply(np.sign).diff().abs() > 0).sum().sum())
    click.echo(f"target flips: {flips} ({flips / max(1, targets.notna().sum().sum()):.4f} per symbol-bar)")
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    equal = targets / max(1, len(panel.symbols))
    for label, model in (
        ("signal-only equal-notional, zero cost", CostModel(0.0, 0.0, False)),
        ("signal-only equal-notional, full cost", cost),
    ):
        summary = run_backtest(panel, equal, model, execution=execution).summary()  # type: ignore[arg-type]
        click.echo(f"{label}: ")
        _echo_summary(summary)
