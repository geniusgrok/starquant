"""The startup gate reads the loop's own overlays out of the profile (2026-09-08 audit).

`construction_problems` can compare a report's `book_guards` / `exits` against the loop's, but only if
someone hands it the loop's.  This is that wiring, and the test that it is not a dead parameter -
`starquant_alpha` has a pure comparison and no way to know what `live.demo.yaml` says.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starquant_alpha.registry import parse_registry
from starquant_live.config import registry_evidence_problems

LIVE_PROFILE: dict[str, Any] = {
    "market_data": {"interval": "1h"},
    "portfolio": {"vol_target": 0.30, "max_weight": 0.15, "max_gross": 2.0, "no_trade_rel_band": 0.40},
    "guards": {"daily_loss_pause": -0.05},
    "exits": {"stop_loss": 6.0, "take_profit": 6.0, "trailing_stop": 0.0},
}


def _registry(report: Path) -> Any:
    return parse_registry(
        {
            "version": 1,
            "strategies": [
                {
                    "id": "tsmom",
                    "enabled": True,
                    "params": {"horizons": [168, 336, 720]},
                    "evidence": {
                        "report": str(report),
                        "sha256": __import__("hashlib").sha256(report.read_bytes()).hexdigest(),
                        "verdict": "PASS",
                    },
                }
            ],
        }
    )


def _write(tmp_path: Path, **blocks: Any) -> Path:
    report = tmp_path / "evidence.json"
    report.write_text(
        json.dumps(
            {
                "kind": "validation",
                "strategy": "tsmom",
                "best_params": {"horizons": [168, 336, 720]},
                "portfolio": {"vol_target": 0.30, "max_weight": 0.15, "max_gross": 2.0, "no_trade_rel_band": 0.40},
                **blocks,
            }
        ),
        encoding="utf-8",
    )
    return report


def test_a_guard_the_loop_runs_and_the_evidence_did_not_is_refused(tmp_path: Path) -> None:
    """The 2026-09-08 shape, once the field exists: `validate` scored the book without the guards."""
    report = _write(tmp_path, book_guards=None, exits=None)

    problems = registry_evidence_problems(_registry(report), LIVE_PROFILE)

    assert any("book_guards" in problem for problem in problems), problems
    assert any("exits" in problem for problem in problems), problems


def test_evidence_produced_under_the_loops_own_overlays_is_silent(tmp_path: Path) -> None:
    report = _write(
        tmp_path,
        book_guards={"max_weight": 0.15, "max_gross": 2.0, "daily_loss_pause": -0.05},
        exits={"stop_loss": 6.0, "take_profit": 6.0, "trailing_stop": 0.0, "bars_per_day": 24},
    )

    assert registry_evidence_problems(_registry(report), LIVE_PROFILE) == []


def test_a_report_that_predates_the_fields_is_still_allowed_to_start(tmp_path: Path) -> None:
    assert registry_evidence_problems(_registry(_write(tmp_path)), LIVE_PROFILE) == []
