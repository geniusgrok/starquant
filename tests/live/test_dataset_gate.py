"""D-041: the dataset manifest is checked at startup, not merely written.

`manifest_problems` existed and had no caller: `research validate` wrote a manifest into every report
and nothing ever read one back, so the stale-evidence pointer it was built to catch could not be caught.
These tests cover the wiring and, more importantly, the severity split - the gate has to refuse a
membership rebuild without refusing the daily sync, or it will be turned off within a week.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from starquant_alpha.registry import Registry, StrategyEntry
from starquant_data.manifest import build_manifest
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import load_registry
from starquant_live.config import registry_dataset_problems
from starquant_live.reports import daily_markdown, daily_payload, weekly_markdown, weekly_payload
from starquant_live.state import StateStore

ROOT = Path(__file__).resolve().parents[2]


def _data_root(tmp_path: Path, *, refreshes: int = 30, symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    index = pd.date_range("2024-01-01", periods=refreshes, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=list(symbols)).to_parquet(root / "membership.parquet")
    (root / "universe.json").write_text(
        json.dumps({"symbols": list(symbols), "source": "pool-refresh", "selected_at_ms": 1}), encoding="utf-8"
    )
    KlineStore(root).append("BTCUSDT", "1h", pd.DataFrame({"open_time": [0, 3_600_000], "close": [1.0, 2.0]}))
    FundingStore(root).append(
        "BTCUSDT", pd.DataFrame({"funding_time": [0], "funding_rate": [0.0001], "mark_price": [100.0]})
    )
    return root


def _registry_citing(report: Path) -> Registry:
    entry = StrategyEntry("tsmom", evidence={"report": str(report), "sha256": "a" * 64, "verdict": "PASS"})
    return Registry(version=1, ensemble_method="mean", turnover_penalty=0.0, strategies=(entry,))


def _report(tmp_path: Path, data_root: Path, *, with_manifest: bool = True, universe_mode: str | None = None) -> Path:
    payload: dict[str, object] = {"kind": "validation", "verdict": "PASS"}
    if with_manifest:
        payload["dataset"] = build_manifest(data_root).to_dict()
    if universe_mode is not None:
        payload["universe_mode"] = universe_mode
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_membership_rebuild_blocks_the_strategy_that_cites_it(tmp_path: Path) -> None:
    """P12's shape, now refused at startup instead of discovered afterwards."""
    root = _data_root(tmp_path, refreshes=6)
    registry = _registry_citing(_report(tmp_path, root))

    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")

    check = registry_dataset_problems(registry, data_root=root)
    assert check.blocking and check.blocking[0].startswith("tsmom: ")
    assert "membership.refreshes: 6 -> 180" in check.blocking[0]


def test_the_daily_sync_appending_bars_does_not_block(tmp_path: Path) -> None:
    """The archive grows every day; a gate that refuses on that gets --allow-unvalidated forever."""
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root))
    KlineStore(root).append("ETHUSDT", "1h", pd.DataFrame({"open_time": [0], "close": [1.0]}))

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking
    assert check.advisory and "klines.symbols: 1 -> 2" in check.advisory[0]


def test_a_report_with_no_dataset_block_is_advisory_so_nothing_in_flight_is_blocked(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root, with_manifest=False))

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking
    assert check.advisory and "no dataset manifest recorded" in check.advisory[0]


def test_a_missing_report_is_left_to_the_evidence_gate_rather_than_reported_twice(tmp_path: Path) -> None:
    """`registry_evidence_problems` already says the report is missing; saying it again is noise."""
    root = _data_root(tmp_path)
    registry = _registry_citing(tmp_path / "gone.json")

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking and not check.advisory


def test_a_disabled_strategy_is_not_checked(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    entry = StrategyEntry("tsmom", enabled=False, evidence={"report": str(tmp_path / "gone.json")})
    registry = Registry(version=1, ensemble_method="mean", turnover_penalty=0.0, strategies=(entry,))

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking and not check.advisory


@pytest.mark.skipif(not (ROOT / ".starquant" / "data").exists(), reason="live data root is not in this checkout")
def test_the_shipped_registry_is_not_blocked_on_the_machine_that_runs_the_loop() -> None:
    """The operator-facing guard: adding this gate must not stop what is already running.

    Skipped in worktrees and CI, where `.starquant/data` does not exist - it is a statement about the
    machine holding the archive, which is the only place the answer means anything.

    Why this is xfail rather than deleted or loosened.  The assertion is still the right one and it is
    still being evaluated every run; what changed is that its answer is currently "blocked", and that is
    a fact about the archive rather than a defect in the check.  Leaving it as a plain red would bury the
    next real failure in noise; weakening the assertion would throw away the guard.  `strict=True` keeps
    both: the condition is measured, its current state is declared, and a change in either direction is
    loud.  The `deploy/run_live.sh` bridge does NOT make this pass - it lets the loop start anyway, which
    is a different claim from "the evidence matches the data".

    2026-09-25: the `xfail(strict=True)` is gone, because it had done its job.  It went on 2026-09-18,
    when rebuilding `.starquant/data/membership.parquet` (2,042 -> 2,056 refreshes, union 211 -> 212) moved
    a BLOCKING manifest field under tsmom's cited evidence.  On 2026-09-19 `16a52547` pointed tsmom at the
    16-cell report, whose manifest was taken on the rebuilt table, and this gate has been clear since -
    so from that day this test passed unexpectedly on the machine that runs the loop and failed there
    under strict, while CI (no `.starquant/data`) skipped it and could not see it.  The marker's reason said
    it would pass "the day tsmom qualifies again", which folded two gates into one: this test measures the
    DATASET gate only.  The evidence verdict is still FAIL on 2026-09-25; that half is the startup
    evidence gate's (`live run`'s refusal, bypassed by the D-041 bridge until 2026-10-13), not this one's.
    Found by `docs/analysis/2026-09-25-october-13-readiness.md` and confirmed by running this test there.
    """
    registry = load_registry(ROOT / "config" / "alpha_registry.yaml")
    check = registry_dataset_problems(registry, data_root=ROOT / ".starquant" / "data")
    assert not check.blocking, check.blocking


def _dataset_block() -> dict[str, list[str]]:
    return {
        "blocking": [],
        "advisory": ["flow: no dataset manifest recorded: this result's data provenance cannot be checked"],
    }


def test_the_daily_report_carries_the_dataset_check(tmp_path: Path) -> None:
    """Where a human actually reads it.  A check only the startup gate sees is invisible after startup."""
    store = StateStore(tmp_path / "live")
    payload = daily_payload(store, "2025-09-02", dataset=_dataset_block())
    assert payload["dataset"] == _dataset_block()
    assert "no dataset manifest recorded" in daily_markdown(payload)


def test_the_weekly_report_carries_the_dataset_check(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")
    payload = weekly_payload(store, "2025-09-02", dataset=_dataset_block())
    assert payload["dataset"] == _dataset_block()
    assert "no dataset manifest recorded" in weekly_markdown(payload)


def test_a_report_written_without_a_dataset_check_still_renders(tmp_path: Path) -> None:
    """Older payloads on disk have no `dataset` key; rendering one must not raise."""
    store = StateStore(tmp_path / "live")
    payload = daily_payload(store, "2025-09-02")
    assert payload["dataset"] == {"blocking": [], "advisory": []}
    assert daily_markdown(payload)


def test_a_pit_report_is_not_blocked_by_the_universe_file_at_startup(tmp_path: Path) -> None:
    """The WIRING, not just the predicate: the gate has to read ``universe_mode`` off the report.

    A correct predicate nobody passes the mode to is this repository's most frequent defect - a
    producer and a consumer that are each right on their own.  So the join is tested, not assumed.
    """
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root, universe_mode="pit"))
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking, "a pit result's population is the membership table, not this file"
    assert check.advisory and "universe.fingerprint" in check.advisory[0]


def test_a_static_report_is_still_blocked_by_the_universe_file_at_startup(tmp_path: Path) -> None:
    """The other half of the join: static keeps the block, so the exemption cannot be a blanket one."""
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root, universe_mode="static"))
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )

    check = registry_dataset_problems(registry, data_root=root)
    assert check.blocking and check.blocking[0].startswith("tsmom: ")
    assert "universe.fingerprint" in check.blocking[0]


def test_a_report_declaring_no_universe_mode_is_still_blocked_at_startup(tmp_path: Path) -> None:
    """Silence is not an exemption - checked where the reading actually happens.

    `registry_dataset_problems` is the only caller that holds a whole report payload, so the
    `.get("universe_mode")` and the `isinstance` guard beside it are the two lines that decide what an
    unstated mode means.  Defaulting them to `"pit"`, or rewriting the predicate as `!= "static"`,
    would exempt every report written before the field was recorded.

    This lives here rather than beside `manifest_check` on purpose: a unit-layer version passes the
    argument itself, so it exercises a call the production path never makes and is a verbatim
    duplicate of `test_a_changed_symbol_set_under_the_same_source_blocks`.  Moved 2026-09-15.
    """
    root = _data_root(tmp_path)
    report = _report(tmp_path, root)
    assert "universe_mode" not in json.loads(report.read_text(encoding="utf-8")), (
        "the fixture has to actually omit the key, or this test proves nothing about silence"
    )
    registry = _registry_citing(report)
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )

    check = registry_dataset_problems(registry, data_root=root)
    assert check.blocking and check.blocking[0].startswith("tsmom: ")
    assert "universe.fingerprint" in check.blocking[0]
