"""G8: break each rule the break-even tests guard, one at a time, and check that some test goes red.

The mutation readings behind `docs/RESEARCH_LOG.md` 2026-09-23 · G8 (「变异 13 个」).  Every mutation is an
exact-text edit made in a COPY of the tree, never in the tree this is run from; the copy is checked
green before anything is planted.  If an anchor no longer exists the script stops and names it, rather
than reporting a mutation it never made as caught.  `PYTHONDONTWRITEBYTECODE` is set and every
`__pycache__` removed before each run: an equal-length edit inside the same second leaves a stale
`.pyc` valid, and the unmutated code would be what ran.

    .venv/bin/python scratchpad/g8_break_even_mutations.py

About 30 s.  Prints RED (a test caught it) or SURVIVED per mutation, and the tests that went red.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALPHA = "tests/alpha/test_the_break_even_multiple_is_where_mean_net_is_zero.py"
CLI = "tests/cli/test_validate_reports_the_break_even_cost_multiple.py"
STAB = "starquant_alpha/validation/stability.py"
CMD = "starquant_cli/research_validate_cmd.py"
REP = "starquant_cli/research_report.py"
VERDICT = "starquant_alpha/validation/verdict.py"
BACKTEST = "starquant_alpha/backtest.py"
# `reports/research/` because one test walks every archived validation report.
COPIED = ("starquant_", "tests/", "config/", "reports/research/", "pyproject.toml")
FAIL_CLAUSE = '    if reasons:\n        return "FAIL", reasons\n'

#: name -> (file, anchor text, the text with the mutation made, the test files expected to catch it)
MUTATIONS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "M1 solver: the first re-pricing always counts as the zero": (
        STAB,
        "        if abs(mean) <= BREAK_EVEN_TOLERANCE * -slope:\n",
        "        if True:\n",
        (ALPHA,),
    ),
    "M2 solver: the secant step goes the wrong way": (
        STAB,
        "        multiple -= mean * (multiple - m0) / (mean - f0)\n",
        "        multiple += mean * (multiple - m0) / (mean - f0)\n",
        (ALPHA,),
    ),
    "M3 solver: no re-pricing; the x1-x2 line is reported as the answer": (
        STAB,
        "    previous = (hi, means[hi])\n",
        "    return {**out, 'multiple': multiple, 'converged': True, 'repricings': 1, 'mean_net_at_multiple': 0.0}\n"
        "    previous = (hi, means[hi])\n",
        (ALPHA,),
    ),
    "M4 solver: a negative zero is clamped to 0 and priced, not reported as none": (
        STAB,
        '    if multiple < 0:\n        return {**out, "why": "mean net is below zero before any cost is scaled"}\n',
        "    multiple = max(multiple, 0.0)\n",
        (ALPHA,),
    ),
    "M5 decide: FAIL when the OOS m* is below 2": (
        VERDICT,
        FAIL_CLAUSE,
        '    _be = ((report.get("cost_break_even") or {}).get("oos") or {}).get("multiple")\n'
        '    if _be is not None and _be < 2:\n        reasons.append("m* < 2")\n' + FAIL_CLAUSE,
        (ALPHA,),
    ),
    "M6 decide: a high full-sample m* waives every other reason": (
        VERDICT,
        FAIL_CLAUSE,
        '    _be = ((report.get("cost_break_even") or {}).get("full_sample") or {}).get("multiple")\n'
        "    if _be is not None and _be > 50:\n        reasons = []\n" + FAIL_CLAUSE,
        (ALPHA,),
    ),
    "M7 cli: the full-sample m* is taken on common_index, not on cost_stress's series": (
        CMD,
        '        "full_sample": break_even_cost_multiple(_priced, stressed_nets),\n',
        '        "full_sample": break_even_cost_multiple(_priced, stressed_nets, lambda n: n.reindex(common_index).fillna(0.0)),\n',
        (CLI,),
    ),
    "M8 cli: the OOS view is all of common_index, not the fold test slices": (
        CMD,
        "        oos: pd.Series = pd.concat([aligned.iloc[fold.test_slice] for fold in fold_list])\n",
        "        oos: pd.Series = aligned\n",
        (CLI,),
    ),
    "M9 cli: the solver's re-pricing ignores m": (
        CMD,
        '        "oos": break_even_cost_multiple(_priced, stressed_nets, _oos),\n',
        '        "oos": break_even_cost_multiple(lambda m: _priced(1.0), stressed_nets, _oos),\n',
        (CLI,),
    ),
    "M10 cli: the Markdown row is dropped": (
        CMD,
        '                {**stress, "break-even multiple m* (never enforced)": _break_even_row(break_even)},\n',
        "                stress,\n",
        (CLI,),
    ),
    "M11 report: an unsettled m* prints like a settled one": (
        REP,
        '("" if row["converged"] else f" (unsettled: {off:+.1e} off)")',
        '("")',
        (CLI,),
    ),
    "M12 premise: funding scales with the cost multiple": (
        BACKTEST,
        "        costs = costs + executed * funding\n",
        "        costs = costs + executed * funding * (cost.turnover_bps / 7.0)\n",
        (ALPHA,),
    ),
    "M13 premise: the daily-loss pause reads equity before the scaled costs": (
        BACKTEST,
        "        charge = float(np.abs(row - held).sum()) * turnover_rate + float(np.abs(row).sum()) * carry_rate\n",
        "        charge = 0.0\n",
        (ALPHA,),
    ),
}


def _copy(target: Path) -> None:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=REPO, check=True, capture_output=True
    ).stdout.decode()
    for name in filter(None, listed.split("\0")):
        if name.startswith(COPIED) and (REPO / name).is_file():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / name, target / name)


def _red_tests(root: Path, tests: tuple[str, ...]) -> list[str]:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-p", "no:cacheprovider", "-rf"],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
    )
    failed = [line.split("::", 1)[1].split(" ")[0] for line in result.stdout.splitlines() if line.startswith("FAILED ")]
    if result.returncode != 0 and not failed:
        raise SystemExit(f"pytest exited {result.returncode} with no FAILED line:\n{result.stdout[-2000:]}")
    return sorted(set(failed))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="g8-mutations-") as scratch:
        root = Path(scratch)
        _copy(root)
        if _red_tests(root, (ALPHA, CLI)):
            raise SystemExit("the unmutated copy is already red; nothing below would mean anything")
        survived = 0
        for name, (relative, anchor, mutated, tests) in MUTATIONS.items():
            path = root / relative
            source = path.read_text(encoding="utf-8")
            if source.count(anchor) != 1:
                raise SystemExit(f"{name}: anchor found {source.count(anchor)} times in {relative}")
            path.write_text(source.replace(anchor, mutated), encoding="utf-8")
            try:
                red = _red_tests(root, tests)
            finally:
                path.write_text(source, encoding="utf-8")
            survived += not red
            print(f"{'RED     ' if red else 'SURVIVED'} {name}\n         {', '.join(red) or '-'}", flush=True)
        print(f"\n{len(MUTATIONS) - survived} of {len(MUTATIONS)} caught; the copy is restored after each one")


if __name__ == "__main__":
    main()
