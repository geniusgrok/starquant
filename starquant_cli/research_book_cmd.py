"""``starquant research book``：候选作为 sleeve 进主书的判定（D-018 那把尺子）。

用 `bare` + 带，是 D-018 预登记时用的口径。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import click
import pandas as pd

from starquant_alpha.panel import Panel
from starquant_alpha.report import render_markdown
from starquant_alpha.validation.book_limits import (
    marginal_checks,
)
from starquant_alpha.validation.ledger import (
    TrialRecord,
    resolve_ledger_path,
)
from starquant_alpha.validation.stability import (
    slippage_levels,
)
from starquant_cli import research
from starquant_cli.research_book_eval import (
    BOOK_RULE,
    _embargo_bars,
    _evaluate_book,
    _running_book_nets,
)
from starquant_cli.research_ledger_io import _record_trial
from starquant_cli.research_options import (
    UNIVERSE_MODES,
    _embargo_option,
)

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
    portfolio_params,
    read_universe,
)
from starquant_shared.config import load_yaml


@research.command("book")
@click.option("--main", "main_id", default="tsmom", show_default=True, help="main book strategy id (registry params)")
@click.option("--sleeve", "sleeve_id", required=True, help="candidate sleeve strategy id")
@click.option("--sleeve-params", default="", help="JSON overriding the sleeve's registry/default params")
@click.option(
    "--fraction",
    default=1.0 / 3.0,
    show_default=True,
    type=float,
    help="sleeve risk budget as a fraction of the main book's vol target and caps (one pre-registered value, no grid)",
)
@click.option(
    "--sensitivity",
    default="0.2,0.5",
    show_default=True,
    help="extra fractions reported for context only; never a decision input and never a ledger trial",
)
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
@click.option("--universe", "universe_mode", type=click.Choice(list(UNIVERSE_MODES)), default="pit", show_default=True)
@click.option(
    "--robustness",
    "robustness_mode",
    type=click.Choice(["none", *UNIVERSE_MODES]),
    default="none",
    show_default=True,
    help="second universe on which the sleeve must not subtract OOS Sharpe (D-018)",
)
@click.option("--folds", default=5, show_default=True)
@click.option("--min-train", default=4000, show_default=True)
@click.option("--purge", default=50, show_default=True)
@_embargo_option
@click.option("--cpcv-groups", default=6, show_default=True)
@click.option(
    "--sleeve-max-gross",
    default=None,
    type=float,
    help=(
        "P30: cap the sleeve's own sum |w| per bar, BEFORE --fraction (0 = off). "
        "Defaults to the profile's portfolio.sleeve_max_gross so the live construction is the default."
    ),
)
@click.option(
    "--prior-trials",
    default=0,
    show_default=True,
    help="sleeve configurations evaluated before the ledger existed (charged in the standalone DSR)",
)
def research_book(
    main_id: str,
    sleeve_id: str,
    sleeve_params: str,
    fraction: float,
    sensitivity: str,
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
    robustness_mode: str,
    folds: int,
    min_train: int,
    purge: int,
    embargo: int | None,
    cpcv_groups: int,
    sleeve_max_gross: float | None,
    prior_trials: int,
) -> None:
    """Evidence for running SLEEVE as an independent small book next to MAIN (D-018).

    Books are summed (each with its own portfolio construction; the sleeve scaled by --fraction), then the
    main book's caps and no-trade band apply to the total.  The report compares main-only with main+sleeve
    out of sample and scores the sleeve on its own exactly like `research validate`.
    """
    if not 0 < fraction <= 1:
        raise click.ClickException("--fraction must be in (0, 1]")
    extra = [float(v) for v in sensitivity.split(",") if v.strip()]
    fractions = [fraction, *[f for f in extra if f != fraction]]
    profile_payload = load_yaml(profile)
    portfolio = portfolio_params(profile_payload)
    if sleeve_max_gross is not None:
        if sleeve_max_gross < 0:
            raise click.ClickException("--sleeve-max-gross must be >= 0 (0 disables it)")
        portfolio = replace(portfolio, sleeve_max_gross=sleeve_max_gross)
    history = (
        min_history
        if min_history is not None
        else int((profile_payload.get("portfolio", {}) or {}).get("min_history_bars", 720))
    )
    main_entry = _entry(main_id, registry_path, "")
    sleeve_entry = _entry(sleeve_id, registry_path, sleeve_params)
    costs_payload = load_yaml(costs_path)
    cost = cost_model(costs_payload, use_funding=funding)
    ledger_path = resolve_ledger_path(out=out)
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    panel = _load(root, chosen, interval, start, end, funding)
    _require_funding([main_entry, sleeve_entry], panel)
    decision_membership = _membership(root, universe_mode, panel)
    universes: list[tuple[str, Panel, pd.DataFrame | None]] = [(universe_mode, panel, decision_membership)]
    if robustness_mode not in {"none", universe_mode}:
        if robustness_mode == "static":
            static = [s for s in read_universe(root) if s in panel.close.columns]
            if not static:
                raise click.ClickException("robustness universe 'static' needs a selected universe in the store")
            universes.append(("static", panel.select(static), None))
        else:
            pit_panel = _load(root, _resolve_symbols(root, "", interval, "pit"), interval, start, end, funding)
            universes.append(("pit", pit_panel, _membership(root, "pit", pit_panel)))
    # §3's limits are measured against what is RUNNING, so they are computed once, on the decision
    # universe, before the loop: the robustness arm is a sensitivity of the evidence, not a second book.
    running_nets, running_notes = _running_book_nets(
        registry_path,
        profile_payload,
        panel,
        decision_membership,
        cost,
        interval=interval,
        min_history=history,
        exclude_strategy=sleeve_id,
    )
    slippage_totals = slippage_levels(
        taker_fee_bps=float(costs_payload.get("taker_fee_bps", 5.0)),
        levels=[float(v) for v in costs_payload.get("slippage_stress_bps", []) or []],
    )
    for name in running_notes:
        click.echo(f"running book: {name}")
    evaluated: dict[str, dict[str, Any]] = {}
    records: list[TrialRecord] = []
    embargo_bars = _embargo_bars(purge, embargo)
    for position, (mode, mode_panel, membership) in enumerate(universes):
        click.echo(
            f"[{mode}] {main_id} + {fraction:.3f} x {sleeve_id} on {len(mode_panel.symbols)} symbols x "
            f"{len(mode_panel.index)} bars"
        )
        payload, record = _evaluate_book(
            mode,
            mode_panel,
            membership,
            main_entry,
            sleeve_entry,
            portfolio,
            fractions,
            cost,
            interval=interval,
            min_history=history,
            folds=folds,
            min_train=min_train,
            purge=purge,
            embargo=embargo_bars,
            cpcv_groups=cpcv_groups,
            prior_trials=prior_trials,
            ledger_path=ledger_path,
            with_limits=position == 0,
            running_nets=running_nets,
            running_notes=running_notes,
            slippage_totals=slippage_totals,
        )
        evaluated[mode] = payload
        records.append(record)
    decision = evaluated[universe_mode]
    chosen_fraction = decision["by_fraction"][f"{fraction:.4f}"]
    marginal = chosen_fraction["marginal"]
    standalone = decision["sleeve_standalone"]
    robustness = None if robustness_mode in {"none", universe_mode} else evaluated[robustness_mode]
    robustness_delta = (
        None if robustness is None else robustness["by_fraction"][f"{fraction:.4f}"]["marginal"]["delta_oos_sharpe"]
    )
    limits = decision["book_limits"]
    checks: dict[str, bool | None] = {
        # The same three bars the slippage stress re-applies at 5.5 bps (`book_limits.marginal_checks`).
        **marginal_checks(marginal, BOOK_RULE),
        "cpcv_negative": (
            standalone["cpcv"]["fraction_negative"] is not None
            and standalone["cpcv"]["fraction_negative"] <= BOOK_RULE["max_cpcv_negative"]
        ),
        "cost_x2_sharpe": (
            standalone["cost_stress"]["x2"] is not None
            and standalone["cost_stress"]["x2"] >= BOOK_RULE["min_cost_x2_sharpe"]
        ),
        "robustness_delta": (
            None if robustness_delta is None else bool(robustness_delta >= BOOK_RULE["min_robustness_delta"])
        ),
    }
    reasons = [name for name, ok in checks.items() if ok is False]
    notes = ["robustness universe not evaluated"] if checks["robustness_delta"] is None else []
    book_verdict = "ACCEPT" if not reasons else "REJECT"
    report: dict[str, Any] = {
        "kind": "book",
        "main": {"strategy": main_id, "params": main_entry.params},
        "sleeve": {"strategy": sleeve_id, "params": sleeve_entry.params},
        "fraction": fraction,
        "sensitivity_fractions": [f for f in fractions if f != fraction],
        "combination": {
            "rule": "total = main + fraction x sleeve (each book vol-targeted on its own), then the main book's "
            "per-symbol cap, gross cap and no-trade band on the total",
            "max_weight": portfolio.max_weight,
            "max_gross": portfolio.max_gross,
            "no_trade_band": portfolio.no_trade_band,
            "no_trade_rel_band": portfolio.no_trade_rel_band,
            "flat_inside_band": portfolio.flat_inside_band,
            "band_entry_multiple": portfolio.band_entry_multiple,
        },
        "interval": interval,
        "universe_mode": universe_mode,
        "robustness_universe": None if robustness is None else robustness_mode,
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts([main_entry, sleeve_entry], panel),
        "folds": folds,
        "min_train": min_train,
        "purge": purge,
        # Same key, same reason, as the validation report: the sleeve's standalone block is scored by
        # the same CPCV, so the number that shaped `cpcv_negative` belongs in the artefact.
        "embargo": embargo_bars,
        "prior_trials": prior_trials,
        "universes": evaluated,
        "rule": BOOK_RULE,
        "checks": checks,
        # §3's three limits, BESIDE D-018's six checks and deliberately not folded into `book_verdict`:
        # D-018 is a portfolio finding about the evidence, §3 is an admission decision about the running
        # book, and `starquant_governance.lifecycle` is where the second one is enforced.  Folding them
        # together would move what `book_verdict` means for the six archived reports that carry it.
        "book_limits": limits,
        "book_verdict": book_verdict,
        "reasons": reasons,
        "notes": notes,
        "sleeve_standalone_verdict": standalone["verdict"],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    main_only = decision["main_only"]
    total = chosen_fraction["total"]
    sections: list[tuple[str, Any]] = [
        ("Range", decision["range"]),
        (
            "Books",
            {
                "main": main_id,
                "sleeve": sleeve_id,
                "sleeve_params": json.dumps(sleeve_entry.params, sort_keys=True),
                "fraction": fraction,
                "universe": universe_mode,
                "robustness_universe": report["robustness_universe"] or "none",
            },
        ),
        ("Main book alone", {k: v for k, v in main_only.items() if k != "summary"}),
        (
            "Sleeve alone (as `research validate` would score it)",
            {
                "full_sharpe": standalone["full_sample"]["annualized_sharpe"],
                "full_mdd": standalone["full_sample"]["max_drawdown"],
                "average_absolute_exposure": standalone["full_sample"]["average_absolute_exposure"],
                "oos_sharpe": standalone["walk_forward"]["oos_sharpe"],
                "fold_sharpes": standalone["walk_forward"]["fold_sharpes"],
                "cpcv_mean_q05_negative": [
                    standalone["cpcv"]["oos_sharpe_mean"],
                    standalone["cpcv"]["oos_sharpe_q05"],
                    standalone["cpcv"]["fraction_negative"],
                ],
                "dsr_p_value": standalone["multiple_testing"]["dsr_p_value"],
                "n_trials": standalone["multiple_testing"]["n_trials"],
                "cost_x2_sharpe": standalone["cost_stress"]["x2"],
                "standalone_verdict": standalone["verdict"],
                "standalone_reasons": standalone["reasons"] or ["-"],
            },
        ),
        ("Total book (main + fraction x sleeve)", {k: v for k, v in total.items() if k != "summary"}),
        (
            "Marginal",
            {
                **marginal,
                "correlation_full": decision["correlation"]["full"],
                "correlation_oos": decision["correlation"]["oos"],
                "sleeve_scaled_exposure": decision["sleeve_scaled_summary"]["average_absolute_exposure"],
            },
        ),
        ("Netting and caps", {**decision["netting"], **chosen_fraction["cap_binding"]}),
        (
            "Sensitivity (context only)",
            {
                key: {
                    "delta_oos_sharpe": row["marginal"]["delta_oos_sharpe"],
                    "oos_mdd_worsening": row["marginal"]["oos_mdd_worsening"],
                    "fold_win_rate": row["marginal"]["fold_win_rate"],
                }
                for key, row in decision["by_fraction"].items()
            },
        ),
        (
            "Robustness universe",
            {"universe": robustness_mode, "delta_oos_sharpe": robustness_delta}
            if robustness is not None
            else {"universe": "none"},
        ),
        ("Yearly returns (main / total / sleeve alone at fraction)", decision["yearly_marginal"]),
        ("Rule (D-018)", BOOK_RULE),
        ("Checks", checks),
        (
            "§3 limits (read by the state machine at validated->booked, not by `book_verdict`)",
            {
                "slippage_stress_5.5_pass": limits["slippage_stress"]["pass"],
                "slippage_stress_reasons": limits["slippage_stress"]["reasons"] or ["-"],
                "sleeve_sharpe_by_slippage": limits["slippage_stress"]["sleeve_standalone_sharpe"],
                "max_correlation_with_running": limits["max_correlation_with_running"],
                "correlation_with_running": limits["correlation_with_running"] or {"-": "no running book measured"},
                "running_books_notes": limits["running_books_notes"] or ["-"],
                "turnover_ratio_to_main": limits["turnover_ratio_to_main"],
                "turnover_per_gross_ratio": limits["turnover"]["per_gross_ratio"],
            },
        ),
        ("Verdict", {"book_verdict": book_verdict, "reasons": reasons or ["-"], "notes": notes or ["-"]}),
    ]
    markdown = render_markdown(f"Book evidence: {main_id} + {fraction:.3f} x {sleeve_id} — {book_verdict}", sections)
    path, digest = _write(out, f"book-{main_id}-{sleeve_id}-{_stamp()}", report, markdown)
    for record in records:
        recorded = _record_trial(ledger_path, replace(record, run_id=path.stem))
        click.echo(
            f"trials ledger: {sleeve_id} standalone on {record.symbols} symbols "
            f"{'recorded' if recorded else 'already recorded (exact replay, not charged twice)'}"
        )
    click.echo(
        f"main-only oos_sharpe={_fmt(main_only['oos_sharpe'])} oos_mdd={main_only['oos_mdd']:.3f} | "
        f"total oos_sharpe={_fmt(total['oos_sharpe'])} oos_mdd={total['oos_mdd']:.3f} | "
        f"delta={_fmt(marginal['delta_oos_sharpe'])} folds_won={_fmt(marginal['fold_win_rate'])}"
    )
    click.echo(
        f"sleeve alone: oos_sharpe={_fmt(standalone['walk_forward']['oos_sharpe'])} "
        f"dsr_p={_fmt(standalone['multiple_testing']['dsr_p_value'])} "
        f"(n_trials {standalone['multiple_testing']['n_trials']}) verdict={standalone['verdict']}"
    )
    if robustness_delta is not None:
        click.echo(f"robustness [{robustness_mode}] delta_oos_sharpe={_fmt(robustness_delta)}")
    click.echo(f"checks: {json.dumps(checks)}")
    click.echo(
        f"§3 limits: slippage_5.5_pass={limits['slippage_stress']['pass']} "
        f"{limits['slippage_stress']['reasons'] or ''} | "
        f"max_corr_with_running={_fmt(limits['max_correlation_with_running'])} "
        f"({', '.join(sorted(limits['correlation_with_running'])) or 'none measured'}) | "
        f"turnover_ratio_to_main={_fmt(limits['turnover_ratio_to_main'])}"
    )
    click.echo(f"BOOK VERDICT: {book_verdict} {reasons if reasons else ''} {notes if notes else ''}")
    click.echo(f"report: {path} sha256={digest}")
