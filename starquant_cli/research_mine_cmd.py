"""``starquant research mine``：表达式挖掘。

挖掘候选按结构至多 WEAK_PASS，而 mined 桶的门高于在位者——这不是 bug，是 D-028 按今天的
N 重算的结果。搜得越多，自己的 incumbent 退休得越快。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import numpy as np
import pandas as pd

from starquant_alpha.backtest import run_backtest
from starquant_alpha.mining import enumerate_candidates, to_signal
from starquant_alpha.model import AlphaModel, FundingUnavailable
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import register as register_signal
from starquant_alpha.validation.ledger import (
    LEDGER_ENV,
    MINED_SEARCH_STRATEGY,
    TrialRecord,
    ledger_redirection,
    parse_ledger,
    resolve_ledger_path,
    unique_trials,
)
from starquant_alpha.validation.metrics import (
    compound,
    max_drawdown,
    sharpe,
)
from starquant_alpha.validation.multiple_testing import (
    effective_trials_from_correlation,
)
from starquant_cli import research
from starquant_cli.research_feature_store import with_feature_store
from starquant_cli.research_ledger_io import (
    _construction_digest,
    _prior_search,
    _record_trials,
    _reproduction_of,
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
    _resolve_mined,
    _resolve_symbols,
)
from starquant_cli.research_report import (
    _fmt,
    _stamp,
    _write,
)
from starquant_data.manifest import build_manifest
from starquant_governance.policy import Policy
from starquant_live.composition import (
    cost_model,
    portfolio_params,
)
from starquant_shared.config import load_yaml


@research.command("mine")
@click.option(
    "--reauthorize",
    default="",
    help=(
        "R2 override: run a search space that has already been enumerated.  Give the decision and the "
        "reason; it is recorded in the shortlist report.  The reopen path exists because a recording "
        "gap is a real reason to re-run - K-EX07's shape - and a rule with no reopen path gets edited."
    ),
)
@_common_options
@click.option("--top", default=12, show_default=True, help="candidates to print, ranked by full-sample Sharpe")
@click.option("--max-complexity", default=10, show_default=True)
@click.option("--max-lookback", default=1400, show_default=True, help="more than the loop can fetch is a bug (E-042)")
@click.option(
    "--include-funding/--no-include-funding",
    default=True,
    show_default=True,
    help="search the carry family (needs the funding panel)",
)
@click.option(
    "--measure",
    is_flag=True,
    default=False,
    help=(
        "Q4: score the space to COUNT it, not to search it.  Writes no ledger row, ranks nothing, and "
        "is not an enumeration for R2's purposes - it exists because `effective_trials` cannot be "
        "computed from the ledger (it stores Sharpes, not streams) and buying the measurement with a "
        "mine round would raise the very bar the number is about."
    ),
)
@click.option("--baseline", default="", help="strategy id to compare each candidate against (registry params)")
@click.option("--baseline-params", default="", help="JSON overriding the baseline's registry params")
def research_mine(
    reauthorize: str,
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
    top: int,
    max_complexity: int,
    max_lookback: int,
    include_funding: bool,
    measure: bool,
    baseline: str,
    baseline_params: str,
    grids: str,
) -> None:
    """Enumerate candidate expressions and rank them full-sample.  This produces a SHORTLIST, not evidence.

    Nothing here is a verdict: ranking hundreds of expressions on the full sample *is* selection, and
    filing the winner as a result would be the mistake D-020 exists to prevent.  It does write the
    trials ledger, though - every candidate the search kept goes in as a ``mined`` row (DL-K2) - because
    a search that costs nothing is a DSR denominator that is wrong in the one direction that flatters
    it; before DL-K2 the count was printed on the last line and retyped into ``--prior-trials`` by
    hand.  Rows fold only on the full signature, data range included, so re-running the same space
    after the range has moved is recorded as a new trial per candidate: conservative charging, KILL-Q5.
    Measured 2026-09-08: P20's 514-wide space re-run over 24 more bars appended 514 rows and the
    family's prior went 514 -> 1,028; the operator then ruled those rows back out, which is a
    governance call this command does not make.  The last lines, and the report's ``ledger`` block,
    say what this run charged and what the family now costs, so the number is seen where it is
    incurred rather than discovered at the next validation.  ``--strategy`` is inherited from the
    shared options and ignored here; the candidates are the strategies.
    """
    profile_payload = load_yaml(profile)
    # R1, asked BEFORE anything is loaded.  `mine_refusals` and `admission.window_start` were both
    # written and both unread here: `governance next` printed "4/4 mine rounds" and `scheduler
    # .next_action` consumed the refusal, while this command - the only thing that can spend a round -
    # imported neither and had never asked.  So the round limit was advisory, which is the shape the
    # 2026-09-09 audit is named for; R2 next door has refused in this very function all along.
    #
    # Before the panel rather than beside R2's check, because R2 needs `search.space_digest` and this
    # needs only the ledger: a run that is not allowed to happen should not first score the space it
    # is not allowed to score.  `--reauthorize` carries the operator past both, and is recorded in the
    # shortlist report either way - one override, so a run cannot slip past R1 while looking untouched
    # to R2.
    if not reauthorize:
        from starquant_governance.admission import window_start as _window_start
        from starquant_governance.budget import mine_refusals, window_spend

        _ledger = resolve_ledger_path(out=out)
        _lines = _ledger.read_text(encoding="utf-8").splitlines() if _ledger.exists() else []
        _policy = Policy()
        _refusals = mine_refusals(window_spend(_lines, window_start=_window_start(_policy), policy=_policy))
        if _refusals:
            raise click.ClickException(
                f"{'; '.join(_refusals)}.  R1 bounds how many SELECTIONS a window makes, and one mine "
                "round is one selection however wide the space.  Wait for the next window, or pass "
                "--reauthorize '<D-decision and reason>'; the reason is recorded in the shortlist report."
            )
    chosen = _resolve_symbols(root, symbols, interval, universe_mode)
    # DL-D4: `metrics=True`, for the reason `research decompose` states one function up - enumeration
    # happens after the panel exists, so the panel cannot be conditioned on what will be enumerated.
    # This command is the one that ENUMERATES the metrics leaves, and it loaded a panel without them:
    # every `oi` and `lsr` candidate raised `ExprError` in every round since DL-D4 shipped.  Measured
    # 2026-09-09 across two rounds, `outcomes.errored = 90` both times, and the 90 are exactly the 54
    # `oi` plus 36 `lsr`.  The rows carry the reason - `error: ExprError: ... does not carry` - and only
    # the count reached the summary, so it read as a family that ran and lost.
    #
    # DL-D5: `spot=True` for the same reason and with the opposite symptom, which is why it survived a
    # round longer.  The metrics leaves were enumerated against a panel that could not answer them and
    # errored 90 times; the basis leaves were narrowed away by `searched_basis` below and errored zero
    # times, so the run was clean and the family was never searched at all.  A quiet defect outlives a
    # noisy one - the narrowing is right, and what was wrong was the panel it narrowed on.
    panel = _load(root, chosen, interval, start, end, funding, metrics=True, spot=True)
    membership = _membership(root, universe_mode, panel, min_tenure)
    cost = cost_model(load_yaml(costs_path), use_funding=funding)
    portfolio = portfolio_params(profile_payload)
    history = (
        min_history
        if min_history is not None
        else int((profile_payload.get("portfolio", {}) or {}).get("min_history_bars", 720))
    )
    # F-1.  The search space narrows to what this panel can actually answer; it does not refuse, because a
    # refusal makes `mine` unrunnable on the OHLCV-only panels the rest of the suite uses.
    #
    # The predicate is the panel, never the flag, and never `panel.funding is not None` either.  `--funding`
    # against a store with no funding archive yields an all-zero frame rather than None, so both of those
    # weaker tests pass while every carry candidate evaluates to a constant: 42 expressions kept, charged to
    # `declared_trials`, scored on zeros, and a report recording `include_funding: true`.  That is KILL-027
    # standing inside the guard written to prevent it - an artefact asserting a family was searched when it
    # was not.  `panel.settled_symbols` is the quantity that answers it, and `_require_funding` below is the
    # backstop for anything this narrowing lets through - a `--baseline` in particular.
    searched_funding = include_funding and panel.settled_symbols > 0
    # DL-D5, the same narrowing one source over.  It narrowed to False on every run until 2026-09-09,
    # not because a flag said so but because `_load` built no spot store, so no panel this command could
    # construct carried spot and the 18 basis shapes were never charged to `declared_trials` for a
    # family nobody scored.  Writing it as the predicate rather than as a hardcoded False is what let it
    # turn itself on the day the store arrived - the difference between "narrowed by what the panel
    # holds" and "switched off by hand".  It still narrows on an unsynced root, which is the honest
    # answer there: `starquant data spot` has to have run for this root before a basis shape can be scored.
    searched_basis = panel.spot_symbols > 0
    # Every grid is a bar COUNT, so the same search at another interval needs them rescaled: at 1d the
    # default `horizons` of 24..720 mean 24..720 DAYS, and `max_lookback` 1400 outruns the sample.  Keys
    # are checked against the signature rather than splatted blind - a typo would search the default
    # space while the report's own `run.grids` claimed otherwise, which is the failure this block exists
    # to make impossible.
    grid_overrides: dict[str, Any] = json.loads(grids) if grids else {}
    allowed = set(inspect.signature(enumerate_candidates).parameters)
    unknown = sorted(set(grid_overrides) - allowed)
    if unknown:
        raise click.ClickException(f"--grids has no such parameter(s): {', '.join(unknown)}; known: {sorted(allowed)}")
    # A key that is also a flag would be passed twice, and the interface should say which one to use
    # rather than let the call fail on a duplicate keyword - the run block records `grids` verbatim, so
    # an instruction the tool cannot obey must be refused where it is written.
    collide = sorted(set(grid_overrides) & {"max_complexity", "max_lookback", "include_funding"})
    if collide:
        raise click.ClickException(
            f"--grids must not set {', '.join(collide)}; each has its own flag (--{collide[0].replace('_', '-')})"
        )
    if include_funding and not searched_funding:
        click.echo(
            "no settlement in this panel: narrowing the search space, the carry family is neither searched "
            "nor charged to --prior-trials (pass --funding, or --no-include-funding to silence this)"
        )
    if not searched_basis:
        # Unconditional rather than behind a flag, because there is no flag to check: nothing builds a
        # spot store for this command yet, so this line is the only place a reader learns that the basis
        # family did not run.  Silence here is exactly the DL-D4 shape - a family absent from the report
        # for a reason the report does not give.
        click.echo(
            "no spot leg in this panel: narrowing the search space, the basis family is neither searched "
            "nor charged to --prior-trials (DL-D5; no panel carries spot yet)"
        )
    baseline_net: pd.Series | None = None
    if baseline:
        _resolve_mined(baseline)  # a mined candidate is addressable by its hash, like any other id
        # The baseline every marginal is measured against must be expressible at this interval too:
        # `--baseline tsmom --interval 1d` on registry params would compare each candidate to a
        # two-year-horizon book, because tsmom's horizons are bar counts.
        baseline_entry = _entry(baseline, registry_path, baseline_params, grids)
        # Every candidate's marginal is measured against this book, so a baseline running its modifier
        # inert would corrupt the whole column (E-040 / KILL-027).  Same refusal every other command uses.
        _require_funding([baseline_entry], panel)
        baseline_model = _model(baseline_entry, profile_payload, interval, history)
        baseline_weights, _bc, _bp = baseline_model.evaluate(panel, membership)
        # Guard-free on purpose, byte-identical to the candidates' call below: the shortlist buys internal
        # consistency, not realism.  The daily-loss pause reads the equity path it is producing, so
        # replaying it on one leg only would leak that replay into every candidate's correlation.
        baseline_net = run_backtest(panel, baseline_weights, cost, execution=execution).portfolio_net  # type: ignore[arg-type]
    search = enumerate_candidates(
        max_complexity=max_complexity,
        max_lookback=max_lookback,
        include_funding=searched_funding,
        include_basis=searched_basis,
        **grid_overrides,
    )
    click.echo(
        f"search: evaluated {search.evaluated} distinct expressions, kept {len(search.candidates)} "
        f"({json.dumps(search.rejected)}) space={search.space_digest} "
        f"on {len(panel.symbols)} symbols x {len(panel.index)} bars"
    )
    reports_dir = Path(out).parent if out else Path("reports/research")
    prior_run = _prior_search(search, reports_dir)
    if prior_run is not None and not reauthorize and not measure:
        raise click.ClickException(
            f"R2: this search space was already enumerated by {prior_run}.  Re-running it charges the "
            "family a second time for one hypothesis - which is what happened on 2026-09-08, when a "
            "replay over 24 more bars appended 514 rows and moved the family's prior 514 -> 1,028 "
            "(reverted by ruling Q7, on K-EX07's precedent).\n"
            "Widen the space, or pass --reauthorize '<D-decision and reason>' to run it anyway; the "
            "reason is recorded in the shortlist report."
        )
    # The candidates ARE the strategies here, so the funding check belongs after enumeration rather than
    # on `--strategy` (which this command ignores).  It has to happen before the loop: a family that reads
    # funding would otherwise land in the `error` rows below and the command would still exit 0, writing a
    # shortlist whose `declared_trials` counts candidates that were never scored - and that count is what
    # `research validate --prior-trials` feeds into the DSR denominator.
    specs = [register_signal(to_signal(candidate)) for candidate in search.candidates]
    entries = [StrategyEntry(id=spec.id, params=dict(spec.default_params)) for spec in specs]
    _require_funding(entries, panel)
    rows: list[dict[str, Any]] = []
    # Q4: kept only under `--measure`, and only to be COUNTED.  `effective_trials` needs the streams
    # side by side; the ledger cannot supply them, which is the documented reason the N_eff debt has
    # stayed open ("the ledger stores Sharpes, not return series").
    streams: dict[str, pd.Series] = {}
    for candidate, entry in zip(search.candidates, entries, strict=True):
        model = with_feature_store(
            AlphaModel(entries=(entry,), portfolio=portfolio, interval=interval, min_history_bars=history)
        )
        try:
            weights, _combined, _per = model.evaluate(panel, membership)
            result = run_backtest(panel, weights, cost, execution=execution)  # type: ignore[arg-type]
        except FundingUnavailable:
            raise  # belt and braces: the run has no funding, which is not this candidate being unscoreable
        except Exception as exc:  # a candidate that cannot be evaluated is dropped, never silently scored
            rows.append({**candidate.to_dict(), "error": f"{type(exc).__name__}: {exc}"})
            continue
        net = result.portfolio_net
        if measure:
            streams[candidate.hash] = net
        row = {
            **candidate.to_dict(),
            "sharpe": sharpe(net, panel.bars_per_year),
            "net_return": compound(net),
            "max_drawdown": max_drawdown(net),
            "turnover": float(result.turnover.sum()),
        }
        if baseline_net is not None:
            # Aligned per candidate, not once: lookbacks run from 25 to ~1,400 bars, so a baseline Sharpe
            # precomputed over its own index would subtract two numbers measured over different regimes.
            frame = pd.DataFrame({"baseline": baseline_net, "candidate": net}).dropna(how="all").fillna(0.0)
            correlation = float(frame["baseline"].corr(frame["candidate"]))
            combined = sharpe(frame.mean(axis=1), panel.bars_per_year)
            alone = sharpe(frame["baseline"], panel.bars_per_year)
            row["baseline_correlation"] = None if pd.isna(correlation) else correlation
            row["baseline_marginal_sharpe"] = None if combined is None or alone is None else combined - alone
            row["baseline_bars"] = len(frame)
        rows.append(row)
    scored = [row for row in rows if row.get("sharpe") is not None]
    # With a baseline the question is a SECOND, uncorrelated book, so the shortlist ranks on the marginal.
    # Ranking on the full-sample Sharpe is the exact quantity that produces a false "the space is empty"
    # verdict: the best absolute candidate is usually the one most correlated with the book already
    # running, and it is also the maximum of a few hundred noisy draws.  Rows whose marginal could not be
    # computed sort last rather than falling back to a number on a different scale.
    ranked_by = "baseline_marginal_sharpe" if baseline else "sharpe"
    scored.sort(
        key=lambda row: float(row[ranked_by]) if row.get(ranked_by) is not None else float("-inf"), reverse=True
    )
    # A candidate whose net never varies gets `sharpe` None and no "error" key, so it leaves the table
    # without leaving a trace while still being charged to `declared_trials`.  Counted rather than
    # inferred: a family that enumerated but never traded should be visible in the artefact.
    never_traded = [row for row in rows if "error" not in row and row.get("sharpe") is None]
    failed = [row for row in rows if "error" in row]
    # Every counted expression lands in exactly one bucket, checked rather than described.  The
    # pre-registered rule asked for `scored == evaluated`, which no run can satisfy: `evaluated` fires
    # before the complexity and lookback caps, so anything they drop is charged and never scored.  This
    # is the achievable form of the same intent - nothing disappears without a bucket - and it is
    # enforced here because an artefact whose own arithmetic does not close should not be written.
    dropped_by_caps = search.rejected["too_complex"] + search.rejected["too_long"]
    accounted = dropped_by_caps + len(scored) + len(failed) + len(never_traded)
    if accounted != search.evaluated:
        raise click.ClickException(
            f"the run does not account for itself: {accounted} bucketed against {search.evaluated} evaluated"
        )
    payload: dict[str, Any] = {
        "kind": "mine-measurement" if measure else "mine-shortlist",
        # R2: WHICH space this was, so the next run can refuse to enumerate it again.  The set of
        # canonical expression hashes, not the parameters - two parameterisations of the same space are
        # the same hypothesis space.  `evaluated` beside it is a count and cannot tell two apart.
        "search_space_digest": search.space_digest,
        "reauthorized": reauthorize or None,
        "generated_at": datetime.now(UTC).isoformat(),
        # Everything that moves a number in this report, so the JSON alone rebuilds the command line.
        # P14's shortlist recorded none of it, and recovering what it actually ran - vol_target 0.15 with
        # funding charged - took a four-arm reproduction rather than a read (D-024 applied to `mine`).
        "run": {
            "funding": funding,
            # What was searched against what was asked for; the settlement count that decides between
            # them is `funding_inputs.symbols_settled`, recorded once at the top level like every report.
            "include_funding": searched_funding,
            "include_funding_requested": include_funding,
            # DL-D5.  Recorded even though it has no flag, and BECAUSE it has no flag: a reader who sees
            # neither `basis` nor an explanation cannot tell "the family was searched and lost" from
            # "the panel could not answer it", and those are the two readings DL-D4 spent two rounds
            # apart.  `spot_symbols` is the count that decides it, stated beside the verdict.
            "include_basis": searched_basis,
            "spot_symbols": panel.spot_symbols,
            "execution": execution,
            "universe_mode": universe_mode,
            "min_tenure": min_tenure,
            "interval": interval,
            "start": start,
            "end": end,
            "min_history_bars": history,  # resolved, not the raw option, which is None by default
            "portfolio": portfolio.__dict__,  # the cost model is the top-level `costs`, as in every report
            "max_complexity": max_complexity,
            "max_lookback": max_lookback,
            "grids": grid_overrides,  # {} means the declared defaults; the space searched, stated
            "baseline_params": json.loads(baseline_params) if baseline_params else {},
            "top": top,
            "ranked_by": ranked_by,
            "baseline": baseline or None,
            "profile": profile,
            "costs_path": costs_path,
            "registry_path": registry_path,
            "root": root,
            "symbols_arg": symbols,
        },
        "universe_mode": universe_mode,
        "declared_trials": search.declared_trials,
        "evaluated": search.evaluated,
        "rejected": search.rejected,
        "symbols": panel.symbols,
        "range": [str(panel.index[0]), str(panel.index[-1])],
        "costs": cost.__dict__,
        "funding_inputs": _funding_facts(entries, panel),
        "dataset": build_manifest(root, interval).to_dict(),
        "outcomes": {
            "evaluated": search.evaluated,
            "dropped_by_caps": dropped_by_caps,  # counted before the complexity/lookback checks fire
            "scored": len(scored),
            "errored": len(failed),
            "never_traded": len(never_traded),  # enumerated, charged, but no Sharpe to rank
            "accounted": accounted,  # == evaluated, enforced above
        },
        "candidates": rows,
        "baseline": (
            None
            if not baseline
            else {
                "strategy": baseline,
                # Which configuration the baseline actually ran under.  Naming the strategy is not enough:
                # the registry moves, and a marginal measured against tsmom-with-crowding is a different
                # number from one measured against tsmom-without, with nothing in the artefact to tell
                # them apart.
                "params": dict(baseline_entry.params),
                "sharpe": sharpe(baseline_net, panel.bars_per_year) if baseline_net is not None else None,
                "net_return": compound(baseline_net) if baseline_net is not None else None,
                "max_drawdown": max_drawdown(baseline_net) if baseline_net is not None else None,
                "marginal": (
                    "equal-weight two-stream: sharpe(mean(baseline, candidate)) - sharpe(baseline); NOT the "
                    "risk-budgeted, fold-aware D-018 marginal that `research book` computes"
                ),
            }
        ),
        "not_evidence": (
            "full-sample ranking over a search; promote a candidate only through `research validate` "
            "on the point-in-time universe (D-013/D-020).  Every kept candidate is charged to the one "
            "ledger by this run (DL-K2), so --prior-trials covers only trials outside it."
        ),
    }
    lines = [
        f"| {row['hash']} | {row['sharpe']:.3f} | {row['max_drawdown']:.3f} | "
        f"{_fmt(row.get('baseline_marginal_sharpe'))} | {_fmt(row.get('baseline_correlation'))} | "
        f"{row['expression']} |"
        for row in scored[:top]
    ]
    markdown = "\n".join(
        [
            "| hash | sharpe | mdd | marginal | corr | expression |",
            "| --- | --- | --- | --- | --- | --- |",
            *lines,
        ]
    )
    # Stamped, because `mine` was the only unstamped name here: once the payload records the flags, two
    # runs differing only in them would overwrite each other's evidence at one path.
    # DL-K2: the search pays for itself.  Until now `declared_trials` was printed on the last line and
    # carried by hand into `research validate --prior-trials` - which is how P20's 514 got there, and
    # a number that is retyped is a number that can be mistyped, forgotten, or quietly rounded down.
    #
    # `search_space_version` is deliberately left empty on these rows.  A candidate examined in a
    # 267-wide search and again in a 514-wide one is one hypothesis looked at twice, not two; stamping
    # the width on would charge 267 + 514 for a family of 514, inflating N in the direction that looks
    # rigorous and is simply wrong.  On a mined id's VALIDATION row it is set, because validating the
    # same expression after the space widened really is a second, more expensive selection.
    if measure:
        # Free to COUNT, never free to LOOK.  A ranked shortlist here would be a selection over 676
        # candidates that nothing charged - the exact hole the shared `mined` bucket exists to close -
        # so the artefact carries distribution-level readings and no candidate rows at all.
        payload.pop("candidates", None)
        frame = pd.DataFrame(streams).dropna(how="all").fillna(0.0)
        values = frame.to_numpy(dtype=float)
        # Q4b: the matrix is persisted and the headline number is computed FROM the persisted matrix,
        # so the two cannot drift.  The first `--measure` run cost 45 minutes and wrote one scalar; the
        # structure behind it died with the process, which made validating the estimator cost the 45
        # minutes again.  That is a defect in the artefact, not a limit of the estimator - the same
        # failure `all_trials` names: a number nobody can argue with.  Li & Ji reads only the
        # correlation, so the correlation is the whole of what a later reader needs.
        live = values.std(axis=0, ddof=1) > 0
        corr_matrix = np.corrcoef(values[:, live], rowvar=False) if live.any() else np.zeros((0, 0))
        corr_matrix = np.atleast_2d(corr_matrix).astype(np.float32)
        dead = int(values.shape[1] - live.sum())
        stamp = _stamp()
        matrix_path = Path(out) / f"mine-measurement-{stamp}-corr_matrix.npy"
        matrix_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(matrix_path, corr_matrix)
        payload["effective_trials"] = float(effective_trials_from_correlation(corr_matrix.astype(float), dead=dead))
        payload["measurement"] = {
            "note": (
                "Q4: no ledger row was written and nothing was ranked.  `effective_trials` is Li & Ji's "
                "count of INDEPENDENT trials among the streams scored here; it is reported and is not "
                "substituted into any gate (R0 still reads the raw ledger count).  It is an integer in "
                "exact arithmetic and is NOT one here - `eigvalsh` is not exact, so a value off an "
                "integer by ~1e-13 is numerical noise, not structure."
            ),
            "streams": int(frame.shape[1]),
            "bars": int(frame.shape[0]),
            "correlation": {
                "path": str(matrix_path),
                "shape": list(corr_matrix.shape),
                "dtype": "float32",
                "dead_columns": dead,
                "sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
                "note": (
                    "`effective_trials` above was computed from THIS file, so the artefact reproduces "
                    "its own headline number: "
                    "`effective_trials_from_correlation(np.load(path).astype(float), dead=dead_columns)`."
                ),
            },
        }
        path, digest = _write(out, f"mine-measurement-{stamp}", payload, markdown)
        click.echo(
            f"measurement: {payload['effective_trials']:.1f} independent of {search.evaluated} scored "
            f"({frame.shape[1]} streams x {frame.shape[0]} bars).  No ledger row written, nothing ranked; "
            f"R0 still reads the raw count.  {path} sha256={digest[:12]}"
        )
        return

    ledger_path = resolve_ledger_path(out=out)
    stamp = datetime.now(UTC).isoformat()
    run_id = f"mine-shortlist-{_stamp()}"
    scored_by_hash = {row["hash"]: row for row in rows}
    construction = _construction_digest(portfolio.__dict__, cost, execution)
    symbol_hash = _symbol_set_hash(panel.symbols)
    charged = _record_trials(
        ledger_path,
        [
            TrialRecord(
                strategy=MINED_SEARCH_STRATEGY,
                param_key=candidate.hash,
                sharpe_annual=scored_by_hash.get(candidate.hash, {}).get("sharpe"),
                bars_per_year=panel.bars_per_year,
                recorded_at=stamp,
                range_start=str(panel.index[0]),
                range_end=str(panel.index[-1]),
                symbols=len(panel.symbols),
                run_id=run_id,
                construction_digest=construction,
                symbol_set_hash=symbol_hash,
            )
            for candidate in search.candidates
        ],
    )
    # What the family now costs, read back off the file through the fold `research validate` applies
    # (`ledger_scope` sends every mined id to this key) rather than derived from `charged`.  The two
    # part ways exactly when it matters: rows fold on the full signature, data range included, so a
    # replay after the range has moved charges every candidate again - conservative by design (KILL-Q5),
    # and +514 rows on 2026-09-08 with nothing on the terminal saying so.  `before` is the difference,
    # exact because `_record_trials` appends only signatures the file did not already hold.
    ledger_lines = ledger_path.read_text(encoding="utf-8").splitlines() if ledger_path.exists() else []
    family_prior = (
        len(
            unique_trials(
                parse_ledger(ledger_lines, MINED_SEARCH_STRATEGY),
                range_end_granularity_days=Policy().trial_range_end_granularity_days,
            )
        )
        if ledger_lines
        else 0
    )
    # `evaluated` counts expressions the enumerator looked at, including those the caps rejected before
    # any data was touched; only the kept ones have a hash to charge.  The remainder is stated rather
    # than absorbed, so nobody has to rediscover that the two numbers differ.
    remainder = search.declared_trials - len(search.candidates)
    # How many distinct HYPOTHESES the family's denominator is about, beside how many rows it is.  Every
    # other number in this block counts rows, so the artefact could say 2,731 four ways and never once
    # say 676 - and on 2026-09-14 an analysis read `family_prior.after` as a candidate count and judged
    # the miner on it.  Read back off the file like `family_prior`, never derived from this run.
    distinct_hypotheses = (
        len({record.param_key for record in parse_ledger(ledger_lines, MINED_SEARCH_STRATEGY)}) if ledger_lines else 0
    )
    payload["ledger"] = {
        "path": str(ledger_path),
        # Where the rows went, when that is not the one ledger.  `resolve_ledger_path` calls this
        # variable's "only possible purpose ... to not be charged"; until now a redirected run and a
        # charging run produced identical output, so the loophole this module names out loud was the
        # one it reported nothing about.  Empty string means the shared, tracked ledger was written.
        "redirected_to": ledger_redirection(),
        "charged": charged,
        "candidates": len(search.candidates),
        "declared_remainder": remainder,
        # The family's denominator in the artefact, not only on the terminal: 2026-09-08's report said
        # `charged: 514` - what the run did - and nothing about what the family cost afterwards.
        # `distinct_hypotheses` sits inside `family_prior` and not beside it on purpose: `after` is the
        # number that was misread, so its companion belongs where the misreading happens.  Same key name
        # as `dsr_inputs` uses for the same quantity - two names for one number is the shape this repo
        # has had to unpick twice already.
        "family_prior": {
            "strategy": MINED_SEARCH_STRATEGY,
            "before": family_prior - charged,
            "after": family_prior,
            "distinct_hypotheses": distinct_hypotheses,
        },
    }
    # Did the re-run its authorisation bought actually buy anything?  R2 records the REASON a space was
    # re-enumerated and has never recorded whether the reason came true.  On 2026-09-09 one did not:
    # 09:50Z charged 658 rows and returned all 658 Sharpes identical to 08:29Z, the same 90 errors
    # included, because the fix its `--reauthorize` invoked had not reached this path.  Whether such a
    # round stays charged is Q7's kind of ruling and nothing here makes it; it only stops being a thing
    # you can learn solely by diffing two reports by hand.
    payload["reproduction"] = _reproduction_of(rows, prior_run, reports_dir)
    path, digest = _write(out, run_id, payload, markdown)
    if payload["ledger"]["redirected_to"]:
        click.echo(
            f"ledger REDIRECTED by {LEDGER_ENV} to {payload['ledger']['redirected_to']}: these "
            f"{charged} row(s) are NOT in the shared book, so the family's denominator did not move"
        )
    if payload["reproduction"]["bought_nothing"]:
        click.echo(
            f"this round REPRODUCED {payload['reproduction']['of']} exactly: "
            f"{payload['reproduction']['identical']}/{payload['reproduction']['compared']} candidates "
            f"returned an identical reading, so the {charged} row(s) it charged bought no new score.  "
            "Whether they stay charged is a ruling (Q7's precedent, 2026-09-08)"
        )
    for row in scored[:top]:
        click.echo(
            f"  {row['hash']}  sharpe={row['sharpe']:6.3f}  mdd={row['max_drawdown']:7.3f}  "
            f"turnover={row['turnover']:8.1f}  lookback={row['lookback']:>4}  {row['expression']}"
        )
    if failed:
        # "see the report" is what let this hide for two rounds.  The rows carried the reason all along
        # - `error: "ExprError: ... does not carry"` on each one - and the summary handed the reader a
        # bare count, so a family that could NOT RUN read as a family that ran and lost.  90 of 658 is a
        # plausible number for a search rejecting malformed combinations, which this search legitimately
        # does.  Printing the distinct reasons is the whole fix: one line per kind, with how many, so the
        # difference between "these are illegal combinations" and "an entire family cannot see its
        # column" is visible without opening the JSON.  Truncated per reason because an ExprError
        # message names the node, and 90 of them are the same sentence.
        click.echo(f"{len(failed)} candidate(s) could not be evaluated:")
        reasons: dict[str, int] = {}
        for row in failed:
            reasons[str(row.get("error", "unknown"))] = reasons.get(str(row.get("error", "unknown")), 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            click.echo(f"  {count:5d}x  {reason[:160]}")
    if never_traded:
        click.echo(
            f"{len(never_traded)} candidate(s) enumerated but never traded (zero-variance net, so no Sharpe): "
            "charged to --prior-trials, absent from the table"
        )
    click.echo(
        f"trials ledger: {ledger_path} (+{charged} of {len(search.candidates)} kept candidates; "
        f"the rest were already in it)"
    )
    click.echo(
        f"mined family prior: {family_prior} distinct trials in the ledger ({family_prior - charged} before this run, "
        f"+{charged} charged now); the search cost `research validate` charges every mined id"
    )
    if remainder:
        click.echo(
            f"declare --prior-trials {remainder} on top: expressions the caps rejected before any data "
            "was touched, so they have no hash to charge"
        )
    click.echo(f"report: {path} sha256={digest}")
