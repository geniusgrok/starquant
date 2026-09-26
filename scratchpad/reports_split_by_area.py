"""Move starquant_live/reports.py's readings into report_* modules by checklist area, byte for byte.

Every top-level definition is cut out of the original source with the comment block directly above
it (never retyped), so a function body cannot change in transit.  Imports are recomputed per module
from the names each chunk actually uses.  Run from the worktree root.

A record of the 2026-09-25 split, not a tool to run again: it ran once on 5fe1e6b3 as
`python reports_split_by_area.py <the 56 contract names, comma-separated> <reports docstring file>`.
Three things were done by hand after it, all visible in that commit's diff: `ruff check --select I
--fix` and `ruff format` on the new files; one import removed from `report_risk.py` (`latest`, which
the name scan picked up from a local variable of the same name - ruff F401/F811 caught it); and
`__all__` appended to `reports.py`, because mypy's strict mode does not follow an implicit re-export.
`scratchpad/reports_split_byte_identity.py` is the check that nothing else moved.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path("starquant_live/reports.py")

COMMON = [
    "DAY_MS", "_day_of", "_day_end_ms", "readable_state", "_state_problem", "_cycles", "evidence_window",
    "_store_closes", "_parsed", "_fmt_num", "_fmt_pct", "json_dumps",
]
AREAS: dict[str, list[str]] = {
    "report_decay": [
        "expectations_from_evidence", "probe_rows", "attribution_coverage", "_series_by_strategy",
        "income_drift", "decay_watch", "decay_verdict", "_decay_alerts", "_decay_lines", "_utc_minute",
        "M_G06_WINDOW_MONTHS", "_plus_months", "long_run_sharpe", "_has_dispersion", "probe_correlation",
        "drift_check", "_long_run_sharpe_lines", "_attribution_coverage_lines", "_probe_correlation_note",
    ],
    "report_risk": [
        "RISK_COMPRESSION_LIMIT", "collateral_share", "leg_split", "PLAN_MARGIN_BUDGET", "margin_and_rejections",
        "BACKTEST_EXITS_PER_WEEK", "noise_scale", "TAIL_VOL_TARGET", "BACKTEST_DAILY_VAR", "BACKTEST_DAILY_ES",
        "tail_readings", "_tradable_drawdown_line", "_risk_budget_lines", "_collateral_drift_lines",
        "_weight_cap_line", "_risk_adaptation_lines", "risk_adaptation", "max_weight_of", "weight_cap_bindings",
        "latest_risk_adaptation", "risk_adaptation_headline", "_noise_scale_lines", "_tail_readings_lines",
    ],
    "report_exits": [
        "exit_and_pool_events", "exit_reachability", "COUNTERFACTUAL_N_FOR_DECISION", "TURNOVER_BPS",
        "exit_counterfactuals",
    ],
    "report_execution": ["plan_gaps", "clock_health", "_restart_cost_lines", "_woke_seconds_after_close", "restart_cost"],
    "report_data": ["metrics_parity_status", "data_coverage", "_dataset_block"],
    "report_beta": ["_beta_regression_lines", "market_beta", "_market_beta_lines", "beta_markdown"],
    "report_governance": [
        "ALPHA_EFFORT_TARGET", "effort_share", "PREREGISTRATION_EFFECTIVE_FROM", "preregistration_skipped",
        "preregistration_problems",
    ],
}
ASSEMBLY = ["daily_payload", "daily_alerts", "weekly_payload", "weekly_markdown", "daily_markdown"]

DOCSTRINGS = {
    "report_common": '''"""What every report block reads the live state files with, and prints its numbers with.

Split out of `reports.py` on 2026-09-25 with the rest of the monitoring layer (see that module's
docstring).  Nothing here judges anything: which day a row belongs to, the cycles in a window, the
current construction's evidence window, the archive's closes, and three formatters.
"""''',
    "report_decay": '''"""Is the edge still there: the readings that hold the live series against its evidence.

Checklist areas #1.10 (edge decay monitoring) and #4.10 (signal monitoring dashboard) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`, and the automatic part of D.3
(when to stop): equity and income drift (M-002 / M-010), the decay rule (G1), M-G06, the coverage of
the attribution series under them (O3), and the probe books' stop and review (D-019, M-014).
"""''',
    "report_risk": '''"""The daily risk dashboard: how big the book is, how much it can lose, and what binds it.

Checklist area #3 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`: the risk
budget and its ladder (P13), the sigma ruler (DL-EX0) with the backtest VaR / ES beside it (G4),
margin (M-007), collateral (L1-10 / RISK-G11), the long and short legs (M-008) and per-symbol risk
adaptation (M-015, D-046).
"""''',
    "report_exits": '''"""What the exit overlay did, what it could not have done, and what not doing it would have cost.

Checklist items #1.5 (exit rules) and #3.2 (stop-loss framework) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`: exit and pool events
(M-005 / M-006), thresholds no price path can reach, and the exit counterfactuals.  The overlay is
`starquant_alpha/overlays/exits.py`; the loop's half is `starquant_live/exits.py`.
"""''',
    "report_execution": '''"""Whether each bar was traded on time and as planned.

Checklist area #10 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`, the part
`execution_fidelity.py` (M-Q08) does not hold: restart cost and failed bars (M-Q03), the no-trade
band's plan gaps, and the host clock (D-025).
"""''',
    "report_data": '''"""Whether the data under the book is the data its evidence was measured on.

Checklist area #9 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`: the research
archive's coverage of what the loop traded, metrics same-source parity (DL-D4 / M-011) and dataset
provenance (D-041).  Bar sanity (G6) lives in `bar_sanity.py`.
"""''',
    "report_beta": '''"""How much of the live return was the market's (D-045): the daily block and `report beta`.

Checklist item #6.9 (performance attribution) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`.  The computation is
`benchmark.beta_reading`; this module feeds it the archive's closes and renders what it returns.
"""''',
    "report_governance": '''"""The weekly report's two governance readings: alpha effort share and pre-registration order.

The usage disciplines of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md` that a
report can check: effort goes to alpha (operator target 0.90, 2026-09-04), and a hypothesis is
written down before its result is seen (DL-K3 / KILL-R9).
"""''',
}


def top_level(tree: ast.Module) -> dict[str, ast.stmt]:
    out: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def main() -> None:
    source = SRC.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    defs = top_level(tree)

    # Every definition is claimed exactly once.
    claimed = [*COMMON, *(n for names in AREAS.values() for n in names), *ASSEMBLY]
    dupes = {n for n in claimed if claimed.count(n) > 1}
    missing = set(defs) - set(claimed)
    extra = set(claimed) - set(defs)
    assert not dupes and not missing and not extra, (dupes, missing, extra)

    # Chunk = the definition plus the comment block directly above it.
    chunks: dict[str, str] = {}
    order: list[str] = []
    imports: dict[str, str] = {}  # imported name -> "from X import name" / "import X"
    previous_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if isinstance(node, ast.ImportFrom):
                    text = f"from {node.module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                else:
                    text = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                imports[bound] = text
            previous_end = node.end_lineno or node.lineno
            continue
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            previous_end = node.end_lineno or node.lineno  # the module docstring
            continue
        name = next(k for k, v in defs.items() if v is node)
        start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        gap = lines[previous_end : start - 1]
        above: list[str] = []
        for line in reversed(gap):
            if line.lstrip().startswith("#"):
                above.insert(0, line)
            else:
                break
        stray = [line for line in gap[: len(gap) - len(above)] if line.strip()]
        assert not stray, f"non-blank, non-attached text before {name}: {stray}"
        chunks[name] = "".join(above) + "".join(lines[start - 1 : node.end_lineno])
        order.append(name)
        previous_end = node.end_lineno or node.lineno
    assert "".join(lines[previous_end:]).strip() == "", "text after the last definition"

    home: dict[str, str] = dict.fromkeys(COMMON, "report_common")
    for module, names in AREAS.items():
        for n in names:
            home[n] = module
    for n in ASSEMBLY:
        home[n] = "reports"

    def used_names(names: list[str]) -> set[str]:
        used: set[str] = set()
        for n in names:
            for sub in ast.walk(defs[n]):
                if isinstance(sub, ast.Name):
                    used.add(sub.id)
        return used

    def header(module: str, names: list[str]) -> tuple[str, list[str]]:
        used = used_names(names)
        mine = set(names)
        lines_out = ["from __future__ import annotations", ""]
        external = sorted({imports[u] for u in used if u in imports and u not in mine})
        internal: dict[str, list[str]] = {}
        for u in sorted(used):
            if u in home and u not in mine:
                internal.setdefault(home[u], []).append(u)
        cross = [m for m in internal if m != "report_common" and module != "reports"]
        assert not cross, f"{module} would import from {cross}: areas must only lean on report_common"
        body = external + [
            f"from starquant_live.{m} import {', '.join(ns)}" for m, ns in sorted(internal.items())
        ]
        return "\n".join(lines_out + body), sorted(u for u in used if u in imports and u not in mine)

    written: dict[str, int] = {}
    for module in ["report_common", *AREAS]:
        names = COMMON if module == "report_common" else AREAS[module]
        names_in_order = [n for n in order if n in names]
        head, _ = header(module, names_in_order)
        text = DOCSTRINGS[module] + "\n\n" + head + "\n\n\n" + "\n\n".join(chunks[n] for n in names_in_order)
        Path(f"starquant_live/{module}.py").write_text(text, encoding="utf-8")
        written[module] = len(names_in_order)

    # reports.py: assembly + the address contract.
    contract = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else set()
    assembly_in_order = [n for n in order if n in ASSEMBLY]
    used = used_names(assembly_in_order)
    external = sorted({imports[u] for u in used if u in imports})
    per_module: dict[str, set[str]] = {}
    for n in set(home) - set(ASSEMBLY):
        if n in used or n in contract:
            per_module.setdefault(home[n], set()).add(n)
    reexport_only = {n for names in per_module.values() for n in names} - used
    blocks = []
    for module in ["report_common", *AREAS]:
        names = sorted(per_module.get(module, set()))
        if not names:
            continue
        noqa = any(n in reexport_only for n in names)
        comment = "  # noqa: F401  (re-exported at its historical address; see the module docstring)" if noqa else ""
        blocks.append(f"from starquant_live.{module} import ({comment}\n" + "".join(f"    {n},\n" for n in names) + ")")
    historical = sorted(n for n in contract if n not in home)
    for n in historical:
        blocks.append(f"{imports[n]}  # noqa: F401  (historical address; see the module docstring)")
    docstring = Path(sys.argv[2]).read_text(encoding="utf-8").rstrip("\n") if len(sys.argv) > 2 else '"""TODO"""'
    text = (
        docstring
        + "\n\nfrom __future__ import annotations\n\n"
        + "\n".join(external)
        + "\n\n"
        + "\n".join(blocks)
        + "\n\n\n"
        + "\n\n".join(chunks[n] for n in assembly_in_order)
    )
    SRC.write_text(text, encoding="utf-8")
    print("modules:", written)
    print("assembly:", assembly_in_order)
    print("re-exported only (not used by assembly):", sorted(reexport_only))
    print("historical (not defined in reports.py):", historical)


if __name__ == "__main__":
    main()
