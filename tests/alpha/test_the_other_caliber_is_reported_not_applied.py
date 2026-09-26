"""R0 / DL-G1: both trial calibers are in the artefact, and exactly one of them decides anything.

"Which N" was the most consequential open choice in the governance rules.  The gate stays the strategy
bucket (`ledger_scope`), because deriving it from the whole library FAILs the incumbent on an honest
grid - that measurement is what settled it - and `effective_trials` can only lower the bar.  But a
report that carries only the caliber that was chosen cannot be used to re-open the choice, so both go
in and the unused one must be provably inert.

This file is the "provably inert" half.  `verdict.decide` reads `oos_selection`; a second block beside
it must not reach the verdict by any path, including the one where someone later "tidies" the two into
a loop over blocks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starquant_alpha.validation.ledger import TrialRecord, all_trials, ledger_scope, parse_ledger, unique_trials
from starquant_alpha.validation.verdict import decide

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

ROOT = Path(__file__).resolve().parents[2]


def _archived() -> list[tuple[str, dict[str, Any]]]:
    out = []
    # Recursive since 2026-09-23: `scratch/` and `diagnostics/` hold validation reports too, and the flat glob
    # read 79 of the 81 while this file's claim is about every report.
    for path in sorted((ROOT / "reports" / "research").rglob("*validation*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "validation":
            out.append((str(path.relative_to(ROOT)), payload))
    return out


def test_the_whole_library_block_cannot_change_a_verdict() -> None:
    """T-G1-1.  Injected at a level that would fail every report, the verdict must not move."""
    hostile = {"gate": "max_sharpe_quantile", "threshold_annual": 99.0, "n_trials": 10_000, "p_family": 1.0}
    reports = _archived()
    assert any(Path(name).parent != Path("reports/research") for name, _ in reports)  # scratch/, diagnostics/
    for name, report in reports:
        before = decide(report)
        after = decide({**report, "oos_selection_whole_library": hostile})
        assert before == after, f"{name}: the reported-only caliber reached the verdict"


def test_the_two_calibers_answer_different_questions() -> None:
    """The strategy bucket is a subset of the library, so its N is never the larger of the two."""
    lines = (ROOT / "reports" / "research" / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    bucket = len(unique_trials(parse_ledger(lines, ledger_scope("tsmom")), range_end_granularity_days=FOLD_DAYS))
    library = len(unique_trials(all_trials(lines), range_end_granularity_days=FOLD_DAYS))
    assert 0 < bucket <= library
    # Not merely "<=": if these were equal the whole R0 argument would be about nothing.
    assert bucket < library


def test_all_trials_reads_the_legacy_rows_too() -> None:
    """DL-K1's compatibility, which a whole-library count would otherwise silently drop."""
    legacy = TrialRecord(
        strategy="tsmom",
        param_key="k",
        sharpe_annual=1.0,
        bars_per_year=8760.0,
        recorded_at="2026-01-01T00:00:00+00:00",
        range_start="a",
        range_end="b",
        symbols=15,
        run_id="r",
    )
    line = json.dumps({k: v for k, v in json.loads(legacy.to_json()).items() if not k.endswith("_digest")})
    assert len(all_trials([line])) == 1
    assert all_trials(["not json at all", ""]) == []
