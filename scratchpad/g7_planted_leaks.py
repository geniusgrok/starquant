"""Which one-bar look-aheads `tests/alpha/test_shuffling_the_future_moves_no_weight_before_it.py` catches.

A causality test that has never failed has not shown that it can.  This plants one leak at a time - each
a one-bar look-ahead, the smallest there is - in a COPY of the tree (never in the tree it is run from),
runs the test file against the copy, and prints which tests went red.  The file's module docstring quotes
the result.

With `--scan`, every leak that passes is tried again at 79 cutoffs (150, 157, ..., 696) using the file's
own comparisons with `CUTOFF` moved.  A cutoff counts as a catch only when a `_bit_for_bit` comparison
fails: the non-vacuity assertions were written for one cutoff, and one of them failing somewhere else is
not a leak being seen.

    .venv/bin/python scratchpad/g7_planted_leaks.py [--scan]

Each leak is an exact-text edit.  If its anchor text no longer exists the script stops and names it,
rather than reporting a leak it never planted as caught.  `PYTHONDONTWRITEBYTECODE` is set and every
`__pycache__` removed before each run: an equal-length edit inside the same second leaves a stale `.pyc`
valid, and the unplanted code would be what ran.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST = "tests/alpha/test_shuffling_the_future_moves_no_weight_before_it.py"
COPIED = ("starquant_", "tests/", "config/", "pyproject.toml")
CUTOFFS = range(150, 700, 7)

#: name -> (file, anchor text, the same text with the leak planted).  The control is not a leak: it zeroes
#: every weight, and if the file does not go red on it, the copy is not the code the tests imported.
LEAKS: dict[str, tuple[str, str, str]] = {
    "control: build_weights returns zeros": (
        "starquant_alpha/portfolio.py",
        # The line above the return, because `combine_books` ends in the same `return banded(...)`.
        "    weights = weights.where(aligned.notna().any(axis=1).cummax(), other=np.nan)\n"
        "    return banded(weights, params)\n",
        "    weights = weights.where(aligned.notna().any(axis=1).cummax(), other=np.nan)\n"
        "    return banded(weights, params) * 0.0\n",
    ),
    "covariance recursion reads the next bar": (
        "starquant_alpha/portfolio.py",
        "        row = r[t]\n        cov = lam * cov + (1.0 - lam) * np.outer(row, row)\n        if t + 1 >= max(halflife, 2):",
        "        row = r[min(t + 1, n_bars - 1)]\n        cov = lam * cov + (1.0 - lam) * np.outer(row, row)\n"
        "        if t + 1 >= max(halflife, 2):",
    ),
    "stage-1 divisor (ewm_vol) reads the next bar": (
        "starquant_alpha/features.py",
        "    simple = close.pct_change()\n    return simple.pow(2).ewm(",
        "    simple = close.pct_change().shift(-1)\n    return simple.pow(2).ewm(",
    ),
    "band recursion reads the next row": (
        "starquant_alpha/portfolio.py",
        "        row = values[t]\n        if np.all(np.isnan(row)):",
        "        row = values[min(t + 1, values.shape[0] - 1)]\n        if np.all(np.isnan(row)):",
    ),
    "build_weights gross cap through a centred window": (
        "starquant_alpha/portfolio.py",
        "    gross = stage2.abs().sum(axis=1)\n",
        "    gross = stage2.abs().sum(axis=1).rolling(3, center=True, min_periods=1).max()\n",
    ),
    "cap_gross (sleeve and total) reads the next row": (
        "starquant_alpha/portfolio.py",
        "    gross = weights.abs().sum(axis=1)\n    factor = (max_gross / gross.where(gross > max_gross))",
        "    gross = weights.abs().sum(axis=1).shift(-1).fillna(0.0)\n"
        "    factor = (max_gross / gross.where(gross > max_gross))",
    ),
    "combine_books adds the sleeve one bar ahead": (
        "starquant_alpha/portfolio.py",
        "        total = total + frame.fillna(0.0)",
        "        total = total + frame.shift(-1).fillna(0.0)",
    ),
    "HRP re-cluster reads the next bar": (
        "starquant_alpha/portfolio.py",
        "        row = r[t]\n        cov = lam * cov + (1.0 - lam) * np.outer(row, row)\n"
        "        if t >= max(params.covariance_halflife, 2) and t in recluster:",
        "        row = r[min(t + 1, n_bars - 1)]\n        cov = lam * cov + (1.0 - lam) * np.outer(row, row)\n"
        "        if t >= max(params.covariance_halflife, 2) and t in recluster:",
    ),
    "pause decided on the bar's own return": (
        "starquant_alpha/backtest.py",
        "        if day_start > 0 and equity > 0 and equity / day_start - 1.0 < params.daily_loss_pause:",
        "        peek = equity * (1.0 + float(np.nan_to_num(values[t]) @ returns[t]))\n"
        "        if day_start > 0 and peek > 0 and peek / day_start - 1.0 < params.daily_loss_pause:",
    ),
    "replay equity updated before the guards decide": (
        "starquant_alpha/backtest.py",
        "        row, gross_capped = clamp_book(values[t], params.max_weight, params.max_gross)",
        "        equity *= 1.0 + float(np.nan_to_num(held) @ returns[t])\n"
        "        row, gross_capped = clamp_book(values[t], params.max_weight, params.max_gross)",
    ),
    "participation liquidity read at the execution bar": (
        "starquant_alpha/backtest.py",
        "average_quote_volume(panel, columns, participation.window).reindex(decision_times)",
        "average_quote_volume(panel, columns, participation.window).reindex(executed.index)",
    ),
    "eligibility reads the next bar's membership": (
        "starquant_alpha/model.py",
        "        member = membership.reindex(index=panel.index, columns=panel.close.columns)",
        "        member = membership.shift(-1).reindex(index=panel.index, columns=panel.close.columns)",
    ),
    "hold fills from the next actionable score": (
        "starquant_alpha/signals/base.py",
        "        filled = actionable.ffill()",
        "        filled = actionable.bfill().ffill()",
    ),
    "run_backtest executes on the decision bar": (
        "starquant_alpha/backtest.py",
        "    executed = decided.shift(1).loc[first_valid:]",
        "    executed = decided.shift(0).loc[first_valid:]",
    ),
    "scoring population reads the next bar's membership": (
        "starquant_alpha/model.py",
        "        scored = self.strategy_scores(panel, eligible)",
        "        scored = self.strategy_scores(panel, eligible.shift(-1).fillna(False).astype(bool))",
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


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _clean(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache)


def _red_tests(root: Path) -> list[str]:
    _clean(root)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-rf"], cwd=root, env=_env(), capture_output=True, text=True
    )
    failed = [line.split("::", 1)[1].split(" ")[0] for line in result.stdout.splitlines() if line.startswith("FAILED ")]
    return sorted(set(failed))


def _cutoffs_that_catch(root: Path) -> int:
    _clean(root)
    result = subprocess.run(
        [sys.executable, __file__, "--scan-inside", str(root)], cwd=root, env=_env(), capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr)
    return int(result.stdout.strip().splitlines()[-1])


def _scan_inside(root: Path) -> None:
    """Runs in a subprocess inside the planted copy: the file's comparisons, at every cutoff in `CUTOFFS`."""
    sys.path.insert(0, str(root))
    import tests.alpha.test_shuffling_the_future_moves_no_weight_before_it as module
    from tests.conftest import FIXTURES, load_august_panel

    panel = load_august_panel(FIXTURES / "august_2026")
    cases: list[Callable[[], None]] = [
        lambda: module.test_no_stage_of_build_weights_moves_before_the_cutoff(panel, "inverse_vol"),
        lambda: module.test_no_stage_of_build_weights_moves_before_the_cutoff(panel, "hrp"),
        lambda: module.test_summing_capping_and_banding_the_sleeves_moves_nothing_before_the_cutoff(panel),
        lambda: module.test_the_guard_replay_decides_every_bar_through_the_cutoff_from_what_came_before_it(panel),
        lambda: module.test_the_whole_book_with_a_moving_reference_population_cannot_see_past_the_cutoff(panel),
    ]

    def seen(case: Callable[[], None]) -> bool:
        try:
            case()
        except AssertionError as error:
            return any(frame.name == "_bit_for_bit" for frame in traceback.extract_tb(error.__traceback__))
        return False

    caught = 0
    for cutoff in CUTOFFS:
        module.CUTOFF = cutoff
        caught += any(seen(case) for case in cases)
    print(caught)


def main() -> None:
    if sys.argv[1:2] == ["--scan-inside"]:
        _scan_inside(Path(sys.argv[2]))
        return
    scan = "--scan" in sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="g7-planted-") as scratch:
        root = Path(scratch)
        _copy(root)
        if _red_tests(root):
            raise SystemExit("the unplanted copy is already red; nothing below would mean anything")
        for name, (relative, anchor, planted) in LEAKS.items():
            path = root / relative
            source = path.read_text(encoding="utf-8")
            if source.count(anchor) != 1:
                raise SystemExit(f"{name}: anchor found {source.count(anchor)} times in {relative}")
            path.write_text(source.replace(anchor, planted), encoding="utf-8")
            try:
                red = _red_tests(root)
                line = f"{name:<52} {', '.join(red) if red else 'PASSES'}"
                if scan and not red:
                    line += f"  (caught at {_cutoffs_that_catch(root)}/{len(CUTOFFS)} cutoffs)"
                print(line, flush=True)
            finally:
                path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
