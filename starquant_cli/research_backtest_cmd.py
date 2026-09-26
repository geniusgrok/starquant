"""``starquant research backtest``：单次回测。

2026-09-17 起默认过 exit overlay（`--no-exits` 复现旧报告）——在那之前它根本没有这个开关，
所以它的 Sharpe 比 `validate` 低 0.058，而文件里没有任何东西说这两个数不是同一本书。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import click

from starquant_alpha.backtest import benchmark_basket, benchmark_returns
from starquant_alpha.report import render_markdown
from starquant_alpha.validation.ledger import (
    TrialRecord,
    resolve_ledger_path,
)
from starquant_alpha.validation.metrics import (
    compound,
    sharpe,
    yearly_breakdown,
)
from starquant_alpha.validation.pipeline import layers_applied, score_book
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli import research
from starquant_cli.research_book_eval import (
    _book_guards,
    _exit_params,
)
from starquant_cli.research_ledger_io import (
    _construction_digest,
    _overlay_digest,
    _record_trial,
    _symbol_set_hash,
)
from starquant_cli.research_options import _common_options

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
    _echo_summary,
    _fmt,
    _stamp,
    _write,
)
from starquant_live.composition import (
    cost_model,
    impact_model,
)
from starquant_shared.config import load_yaml


@research.command("backtest")
@click.option(
    "--capital",
    default=0.0,
    show_default=True,
    help=(
        "USDT the book runs, for the DL-C1 impact model.  0 keeps the flat, scale-free cost model "
        "every archived report was produced under; a positive value charges the square-root law on top."
    ),
)
@_common_options
@click.option(
    "--guards/--no-guards",
    default=True,
    show_default=True,
    help="replay the book-level guards the live loop applies (gross cap + daily-loss pause)",
)
@click.option(
    "--exits/--no-exits",
    "exits",
    default=True,
    show_default=True,
    help=(
        "apply the profile's exit overlay, i.e. price the book the loop holds.  This command had no "
        "such flag until 2026-09-17 and so could not measure it at all: its Sharpe sat 0.058 below "
        "`validate`'s on identical inputs for that reason alone.  `--no-exits` reproduces every "
        "backtest report written before."
    ),
)
def research_backtest(
    capital: float,
    guards: bool,
    exits: bool,
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
    grids: str,
) -> None:
    """Backtest one strategy through the full portfolio pipeline and write a research report."""
    profile_payload = load_yaml(profile)
    entry = _entry(strategy, registry_path, params, grids)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    panel = _load(root, chosen, interval, start, end, funding)
    _require_funding([entry], panel)
    membership = _membership(root, universe_mode, panel, min_tenure)
    model = _model(entry, profile_payload, interval, min_history)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    impact = impact_model(load_yaml(costs_path), capital=capital)
    weights, _combined, _per = model.evaluate(panel, membership)
    # The guards are part of the construction the loop runs, not an extra: they are provably inert
    # wherever neither binds (`tests/alpha/test_book_guard_replay.py`), so leaving them on keeps a
    # report describing the book that would actually be held.  `--no-guards` reproduces older reports.
    book_guards = _book_guards(profile_payload, guards)
    exit_params = _exit_params(profile_payload, exits, interval)
    result, _priced = score_book(
        panel, weights, cost, execution=execution, guards=book_guards, exits=exit_params, impact=impact
    )
    summary = result.summary()
    bench = benchmark_returns(panel, execution, panel.symbols, membership).reindex(result.weights.index)  # type: ignore[arg-type]
    report: dict[str, Any] = {
        "kind": "backtest",
        # Which of the live book's four layers this priced.  Until 2026-09-17 this command could not
        # apply the overlay at all, and no report kind but `validation` said which book it measured.
        "layers": layers_applied(band="model", guards=book_guards, exits=exit_params),
        "strategy": strategy,
        "params": entry.params,
        "portfolio": model.portfolio.__dict__,
        "book_guards": None if book_guards is None else book_guards.__dict__,
        "interval": interval,
        "universe_mode": universe_mode,
        "symbols": panel.symbols,
        "range": {"start": str(result.weights.index[0]), "end": str(result.weights.index[-1]), "bars": summary["bars"]},
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts([entry], panel),
        "execution": execution,
        "summary": summary,
        # Held to `membership` since 2026-09-23 (operator ruling).  On a pit run the old basket carried names
        # picked for a membership still in their future (`benchmark_returns`) and the key did not change,
        # so the report says which basket this was.
        "benchmark": {
            "gross_return": compound(bench),
            "sharpe": sharpe(bench, panel.bars_per_year),
            "basket": benchmark_basket(membership),
        },
        "per_symbol": result.per_symbol_summary(),
        "yearly": yearly_breakdown(result.portfolio_net, panel.bars_per_year),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    # DL-K1 / E-15: a backtest evaluates a configuration, so it is a trial.  It was not charged, which
    # made the exploratory arm of every search free - try five vol windows by hand, report the best,
    # and the DSR denominator never hears about the four.  The protocol (report 7.1.4) says every
    # configuration EVALUATED, not every configuration validated, and this is where that starts being
    # true.  Dedup is D-024's, unchanged: an exact replay on the same data is one trial.
    ledger_path = resolve_ledger_path(out=out)
    trial = TrialRecord(
        strategy=strategy,
        param_key=param_key(dict(entry.params)),
        sharpe_annual=summary.get("annualized_sharpe"),
        bars_per_year=panel.bars_per_year,
        recorded_at=datetime.now(UTC).isoformat(),
        range_start=str(result.weights.index[0]),
        range_end=str(result.weights.index[-1]),
        symbols=len(panel.symbols),
        run_id="",
        construction_digest=_construction_digest(report["portfolio"], cost, execution, impact),
        symbol_set_hash=_symbol_set_hash(panel.symbols),
        overlay_digest=_overlay_digest(book_guards),
    )
    charged = _record_trial(ledger_path, trial)
    report["ledger"] = {"path": str(ledger_path), "charged": charged}
    markdown = render_markdown(
        f"Backtest: {strategy}",
        [
            ("Range", report["range"]),
            ("Params", entry.params),
            ("Summary", summary),
            ("Benchmark (equal-weight long, zero cost)", report["benchmark"]),
            (
                "Yearly",
                {year: f"ret={v['return']:.3f} sharpe={_fmt(v['sharpe'])}" for year, v in report["yearly"].items()},
            ),
            (
                "Per symbol",
                {
                    s: f"net={v['net_return']:.3f} sharpe={_fmt(v['annualized_sharpe'])} turnover={v['turnover_units']:.1f}"
                    for s, v in report["per_symbol"].items()
                },
            ),
        ],
    )
    path, digest = _write(out, f"{strategy}-backtest-{_stamp()}", report, markdown)
    _echo_summary(summary, report["benchmark"])
    click.echo(f"report: {path} sha256={digest}")
