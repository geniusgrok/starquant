"""研究报告的落盘与成文：写 JSON/Markdown、格式化、以及判读时必须跟着数走的那些 note。

`_durable` 在这里而不是在写盘的调用点：一份报告是证据，证据要么完整落盘要么不算数。
各种 `_*_note` 也在这里——它们是「这个数该怎么读」的一部分，不是排版。
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from starquant_alpha.report import canonical_json

# The panel layer now lives in `starquant_cli/research_panel.py` (M6 step 1) and is re-exported here.
# Twenty-nine scripts under `scratchpad/` - the reproductions behind D-035's ladder bootstrap, P26,
# P29, P32, D-039's band sweep and the exit reachability tables - import `_load`, `_membership` and
# `_resolve_symbols` from THIS module, and a dozen tests import the others.  Moving the definitions
# without keeping the addresses would have made a move-only commit break the evidence base, so the
# addresses stay until the sink step gives those names a home outside `starquant_cli` entirely.


def _write(out: str, name: str, payload: dict[str, Any], markdown: str) -> tuple[Path, str]:
    directory = Path(out)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{name}.json"
    rendered = canonical_json(payload)
    json_path.write_text(rendered, encoding="utf-8")
    (directory / f"{name}.md").write_text(markdown, encoding="utf-8")
    return json_path, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _stamp() -> str:
    # seconds resolution: two runs inside the same minute must never overwrite each other's evidence
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


COST_SHARE_LIMIT = 0.40  # KILL-013: above this, turnover is eating the edge and the result is not investable


def _cost_flag(cost_share: float | None) -> str:
    """KILL-013 asks for costs above 40% of gross to be flagged, not merely printed."""
    if cost_share is None or cost_share <= COST_SHARE_LIMIT:
        return ""
    return f"  ** COSTS EAT {cost_share:.0%} OF GROSS (> {COST_SHARE_LIMIT:.0%}, KILL-013) **"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:+.3f}%"


def _echo_summary(summary: dict[str, Any], benchmark: dict[str, Any] | None = None) -> None:
    click.echo(
        f"bars={summary['bars']} gross={summary['gross_return']:.4f} net={summary['net_return']:.4f} "
        f"sharpe={_fmt(summary['annualized_sharpe'])} mdd={summary['max_drawdown']:.4f} "
        f"turnover={summary['turnover_units']:.1f} exposure={summary['average_absolute_exposure']:.3f} "
        f"cost_share={_fmt(summary['cost_share_of_gross'])}{_cost_flag(summary['cost_share_of_gross'])}"
    )
    if benchmark:
        click.echo(f"benchmark: gross={benchmark['gross_return']:.4f} sharpe={_fmt(benchmark['sharpe'])}")


# The three notes below travel WITH the numbers they qualify.  Each caveat already existed in the tree -
# in `cpcv_splits`' docstring, in `backtest.py`'s margin-buffer paragraph, in `verdict.decide`'s PBO
# branch - and each was quoted without it: the 2026-09-14 audit found the registry note and the commit
# message for `tsmom-validation-20260913T182325Z` citing CPCV's `fraction_negative`, the zero liquidation
# touches, and a PBO move, none of them carrying the caveat that lives one file over.  A caveat reachable
# only by reading the implementation is not a disclosure to the person reading the artefact - it is a
# disclosure to the person who already knows.  Markdown only: the JSON payload is deliberately untouched
# so every archived report's sha256 stays comparable with the ones the registry already cites.
_MARGIN_BUFFER_NOTE = (
    "structural bound, not a measurement: buffer = (1 + r - c) / (gross * maintenance_margin_rate), and "
    "gross <= max_gross, so at mmr 0.005 and max_gross 2.0 it cannot fall below about 100.  Reaching the "
    "liquidation line at 1.0 would take one bar losing ~99%, so `liquidation_touches: 0` is arithmetic "
    "rather than evidence.  The channel that can actually liquidate this account is collateral repricing "
    "(52% non-USDT, KILL-AR-05) and this replay models zero collateral."
)


def _embargo_note(embargo: int) -> str:
    """Why `fraction_negative` is easier to pass than it looks, printed beside `fraction_negative`."""
    return (
        f"{embargo} bars, which is shorter than the model's feature lookback (tsmom max(horizons)=720, "
        "AlphaModel.warmup_bars 1442).  Training bars AFTER a test block are therefore computed from a "
        "window covering it, and `cpcv_evaluate` picks parameters on exactly those bars.  The returns stay "
        "causal, so this is selection contamination rather than look-ahead - it makes `fraction_negative`, "
        "one of D-020's hard gates, easier to pass than it should be.  Open boundary on the record: see "
        "`cpcv_splits`' docstring and docs/analysis/2026-09-13-full-repo-review.md."
    )


def _full_sample_tail_note(is_tail: object) -> str:
    """KILL-Q2 / D-043, printed beside `oos_is_full_sample_tail` instead of only on stdout.

    The stdout NOTE at the end of `validate` has said this since KILL-Q2, and stdout is not an
    artefact: the run scrolls away and the Markdown is what the registry's reader opens a year later.
    `oos_is_full_sample_tail: True` on its own is a bare boolean next to a Sharpe that reads like an
    out-of-sample estimate, which is the same shape the three notes above were written to close.
    """
    if is_tail is not True:
        return "folds exercised a choice: this OOS is a selection procedure's out-of-sample record"
    return (
        "NO fold had a choice to make (single configuration, or every fold picked the same one), so the "
        "OOS Sharpe above is the TAIL OF ONE FULL-SAMPLE SERIES, not a selection's out-of-sample record.  "
        "D-043 caps such a report at WEAK_PASS: the number stands, the claim that a selection survived "
        "out of sample does not.  `registry.py` still admits WEAK_PASS to live use."
    )


def _caliber_note(gate: Mapping[str, Any], library: Mapping[str, Any] | None) -> str:
    """R0's two N's, side by side, with the margin each one leaves.

    `oos_selection_whole_library` has been in the JSON since DL-G1, whose own comment says an artefact
    carrying only the caliber that was chosen "cannot be used to re-open the choice".  The Markdown
    carried only the chosen one, so for every reader who does not open the JSON the artefact was
    exactly that.  Same rule as `_MARGIN_BUFFER_NOTE`: Markdown only, the payload is untouched, every
    archived sha256 stays comparable.

    Measured on `tsmom-validation-20260913T182325Z.json`, the report the live registry cites: the gate
    at N=242 leaves +0.04, the library at N=2,914 leaves -0.23.  Neither number is new and the verdict
    does not move - `verdict.decide` reads `oos_selection` and nothing else, and a test holds that.
    What moves is whether a reader of the Markdown can see that the choice of N was consequential.
    """
    if not library:
        return "not reported (policy.report_whole_library_n is off)"
    gate_sharpe, gate_n = gate.get("oos_sharpe_annual"), gate.get("n_trials")
    gate_threshold, lib_threshold = gate.get("threshold_annual"), library.get("threshold_annual")
    lib_n, lib_p = library.get("n_trials"), library.get("p_family")
    if not isinstance(gate_sharpe, (int, float)) or not isinstance(lib_threshold, (int, float)):
        return "reported but not comparable: the two blocks do not carry the same fields"
    # Signed, unlike `_fmt`: the sign IS the reading here - one caliber clears and the other does not,
    # and a bare "0.04" next to a bare "0.23" reads like two distances of the same kind.
    gate_margin = f"{gate_sharpe - gate_threshold:+.2f}" if isinstance(gate_threshold, (int, float)) else "n/a"
    return (
        f"ENFORCED at N={gate_n} (the per-strategy bucket): threshold {_fmt(gate_threshold)}, "
        f"margin {gate_margin}.  REPORTED and never enforced at N={lib_n} (the whole library): "
        f"threshold {_fmt(lib_threshold)}, margin {gate_sharpe - lib_threshold:+.2f}"
        + (f", p_family {lib_p:.4f}" if isinstance(lib_p, (int, float)) else "")
        + ".  Which N is the gate is R0 / KILL-AR-01, an operator ruling rather than a property of the "
        "arithmetic, and both numbers are printed so the ruling stays arguable from the artefact alone."
    )


def _power_rows(power: Mapping[str, Any] | None) -> dict[str, str]:
    """Render `oos_selection.power` as flat rows, for the Markdown and for `research power`.

    One renderer rather than two because the pre-registration and the report it later justifies have
    to be comparable line for line - a pre-registration that quotes 43.3% and a report that prints
    "0.4333" is a comparison nobody makes.  The percentages carry one decimal: the approximation in
    `selection_power`'s own docstring is worth about a tenth of a point, so a second decimal would be
    printing noise.
    """
    if not power:
        return {"power": "n/a (no null: the OOS series is too short to give a Sharpe)"}
    rows = {
        "standard error of the OOS Sharpe (annual)": f"{power['se_annual']:.4f}",
        "gate (max of the two halves)": f"{power['gate_annual']:.4f}  [{power['binding']} binds]",
        "  D-028 selection threshold": f"{power['selection_threshold_annual']:.4f} at N={power['n_trials']}, alpha={power['alpha']}",
        "  D-020 pass line": f"{power['pass_line_annual']:.4f}",
    }
    for row in power["detects"]:
        rows[f"P(clear | true annual Sharpe = {row['true_sharpe_annual']:.1f})"] = f"{row['power']:.1%}"
    rows["not included in the above"] = ", ".join(power["excludes"]) + " (so the true joint power is LOWER)"
    return rows


def _regime_rows(split: Mapping[str, Any], basis: Mapping[str, Any]) -> dict[str, str]:
    """`stability.regime_split_sharpes` as flat rows, each tercile's vol range in its key.

    Flat for `_power_rows`' reason: `render_markdown` prints a nested dict as one cell, which is a table
    nobody reads.  The basis follows the numbers because "high" means nothing until it says high WHAT,
    measured WHEN - and the answer to WHEN (bars through t-1) is the causality claim itself.
    """
    rows = {
        f"{label} (annualised vol {row['vol_from']:.2f}-{row['vol_to']:.2f})": f"sharpe={_fmt(row['sharpe'])}  bars={row['bars']}"
        for label, row in split.items()
    } or {"regime split": "n/a (fewer than 30 OOS bars carry a trailing-vol label)"}
    return {**rows, **{f"basis: {key}": str(value) for key, value in basis.items()}}


def _break_even_row(block: Mapping[str, Any]) -> str:
    """`cost_break_even` as one row: each series' m*, or why it has none, or how far re-pricing left it."""
    cells = []
    for label in ("full_sample", "oos"):
        row = block[label]
        if row["multiple"] is None:
            cells.append(f"{label}=n/a ({row['why']})")
        else:
            off = row["mean_net_at_multiple"] / row["cost_per_multiple"]
            cells.append(
                f"{label}={row['multiple']:.2f}" + ("" if row["converged"] else f" (unsettled: {off:+.1e} off)")
            )
    return "  ".join(cells) + "  (mean net return is 0 with turnover and carry costs x m*)"


def _pbo_note(grid_trials: object) -> str:
    """PBO below four configurations is a coin flip; `decide` knows that and readers of the report did not."""
    try:
        trials = int(grid_trials)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return "grid_trials not reported"
    if trials >= 4:
        return f"enforced: grid_trials={trials} >= 4"
    return (
        f"NOT informative and NOT enforced at grid_trials={trials}: CSCV ranks configurations against each "
        "other, and with fewer than four it only says that two curves traded places across sub-periods.  "
        "`verdict.decide` skips the gate below four, so a move in this number is not a cost or a gain either."
    )


def _durable(handle: Any) -> None:
    """Flush and fsync an append-only ledger row.

    DL-L6 did this for `.starquant/live/*.jsonl` and left this file, which is the same contract and the
    more consequential one: `reports/research/trials.jsonl` IS the DSR denominator, so a row lost to a
    crash makes N smaller, and a smaller N flatters every verdict computed afterwards.  At a few rows
    per run the cost is nothing.
    """
    handle.flush()
    os.fsync(handle.fileno())


def _grid_table(params_by_key: Mapping[str, Mapping[str, Any]], sharpes: Mapping[str, float | None]) -> list[str]:
    """Every configuration tried in this run with its full-sample Sharpe, varying parameters only.

    The plan asked for a parameter stability view; the report printed a single
    worst-neighbour number and hid the grid it already had in ``trial_sharpes``.
    Only parameters that actually differ across the grid are shown, so a
    one-configuration run renders a single line instead of thirteen defaults.
    """
    if not params_by_key:
        return []
    keys = sorted({key for params in params_by_key.values() for key in params})
    varying = [k for k in keys if len({str(p.get(k)) for p in params_by_key.values()}) > 1]
    ranked = sorted(params_by_key, key=lambda k: (sharpes.get(k) is None, -(sharpes.get(k) or 0.0)))
    lines = []
    for key in ranked:
        params = params_by_key[key]
        shown = ", ".join(f"{k}={params.get(k)}" for k in varying) if varying else "single configuration"
        lines.append(f"{shown}: sharpe={_fmt(sharpes.get(key))}")
    return lines
