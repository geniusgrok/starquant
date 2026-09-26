"""``starquant research decompose``：把一本书的收益拆到各条腿上。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import click

from starquant_alpha.report import render_markdown
from starquant_alpha.validation.decompose import decompose_book
from starquant_cli import research
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
    _fmt,
    _stamp,
    _write,
)
from starquant_live.composition import (
    cost_model,
)
from starquant_shared.config import load_yaml


@research.command("decompose")
@_common_options
@click.option("--folds", default=5, show_default=True)
@click.option("--min-train", default=4000, show_default=True)
@click.option("--purge", default=50, show_default=True)
def research_decompose(
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
    folds: int,
    min_train: int,
    purge: int,
    grids: str,
) -> None:
    """Signal-vs-construction attribution (D-024): the same pipeline on controlled convictions; not a ledger trial."""
    del execution  # the decomposition uses the open_to_close convention of the validation reports
    profile_payload = load_yaml(profile)
    entry = _entry(strategy, registry_path, params, grids)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    # DL-D4 and DL-D5: always, because the candidates about to be enumerated are what decides whether
    # the columns are needed, and enumeration happens after the panel exists.
    panel = _load(root, chosen, interval, start, end, funding, metrics=True, spot=True)
    _require_funding([entry], panel)
    membership = _membership(root, universe_mode, panel, min_tenure)
    model = _model(entry, profile_payload, interval, min_history)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    payload = decompose_book(model, panel, cost, membership=membership, folds=folds, min_train=min_train, purge=purge)
    report: dict[str, Any] = {
        "kind": "decompose",
        "strategy": strategy,
        "params": entry.params,
        "portfolio": model.portfolio.__dict__,
        "interval": interval,
        "universe_mode": universe_mode,
        "symbols": panel.symbols,
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts([entry], panel),
        **payload,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    lines = [
        f"{name}: sharpe={_fmt(row['full_sharpe'])} oos={_fmt(row['oos_sharpe'])} net={row['net_return']:.3f} "
        f"mdd={row['max_drawdown']:.3f} turnover={row['turnover_units']:.0f} "
        f"exposure={row['average_absolute_exposure']:.3f} corr_full={_fmt(row['correlation_with_full'])} "
        f"folds={[round(x, 2) if x is not None else None for x in row['fold_sharpes']]}"
        for name, row in payload["variants"].items()
    ]
    markdown = render_markdown(
        f"Decomposition: {strategy}",
        [
            ("Range", payload["range"]),
            ("Params", entry.params),
            ("Variants (same portfolio construction, different convictions)", lines),
            ("Increments (Sharpe)", payload["increments"]),
            ("Legs of the full book", payload["legs"]),
            ("Benchmark (equal-weight long, zero cost)", payload["benchmark"]),
        ],
    )
    path, digest = _write(out, f"decompose-{strategy}-{_stamp()}", report, markdown)
    for line in lines:
        click.echo(line)
    click.echo(f"increments: {json.dumps(payload['increments'])}")
    click.echo(f"report: {path} sha256={digest}")
