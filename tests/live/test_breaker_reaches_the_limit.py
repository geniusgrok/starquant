"""AC-L2: twelve consecutive failures, and what the operator is left with.

`test_breaker_stops_cleanly.py` pins `breaker_stop` in isolation - it alerts, it raises the clean
signal, it stays loud when nothing accepted the alert.  None of that says the loop ever REACHES it.
The acceptance criterion is a scenario, and it names three things the unit tests do not cover:

* the counter actually reaches `max_consecutive_errors` and trips there, not earlier and not never;
* the process exits **0**, which is a CLI-layer branch - and under `KeepAlive.SuccessfulExit=false`
  (verified empirically 2026-09-07: exit 0 ran once in 55s, exit 3 ran six times) that is the
  difference between a stopped book and L1-03's relaunch-into-the-same-wall every 60 seconds;
* a successful cycle resets the count, or twelve failures scattered over a month would stop the book.

The third is not in the plan's wording and is the one worth having: a breaker that counts forever is
a breaker that eventually fires for no reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from starquant_live.engine import BreakerTripped
from tests.live.fakes import UNREACHABLE, paper_venue_from


async def _run_until_breaker(
    tmp_path: Path, panel: Any, *, limit: int = 12, succeed_at: int | None = None
) -> dict[str, Any]:
    from tests.live.helpers_liquidation import breaker_engine

    engine, alerts, venue, store = breaker_engine(tmp_path, panel, limit=limit, succeed_at=succeed_at)
    tripped: BreakerTripped | None = None
    try:
        await engine.run(cycles=limit + 5, immediate=True)
    except BreakerTripped as exc:
        tripped = exc
    rows = [json.loads(line) for line in store.cycles_path.read_text(encoding="utf-8").splitlines()]
    return {"tripped": tripped, "alerts": alerts.sent, "rows": rows, "errors": venue.failures}


async def test_twelve_consecutive_failures_trip_the_breaker(tmp_path: Path, august_panel: Any) -> None:
    result = await _run_until_breaker(tmp_path, august_panel, limit=12)

    assert result["tripped"] is not None
    assert "12 consecutive cycle failures" in str(result["tripped"])
    assert result["errors"] == 12  # not 11, not 13


async def test_it_does_not_trip_early(tmp_path: Path, august_panel: Any) -> None:
    result = await _run_until_breaker(tmp_path, august_panel, limit=3)

    assert result["errors"] == 3


async def test_a_successful_cycle_resets_the_count(tmp_path: Path, august_panel: Any) -> None:
    """Twelve failures scattered over a month must not stop a book that recovered in between."""
    result = await _run_until_breaker(tmp_path, august_panel, limit=12, succeed_at=6)

    assert result["tripped"] is None


async def test_the_breaker_says_it_once_and_the_cycle_failures_are_deduped(tmp_path: Path, august_panel: Any) -> None:
    """Twelve failures of one kind are one hourly line plus the breaker's, not thirteen."""
    result = await _run_until_breaker(tmp_path, august_panel, limit=12)

    cycle_lines = [m for m in result["alerts"] if "StarQuant周期失败" in m]
    breaker_lines = [m for m in result["alerts"] if "StarQuant熔断" in m]
    assert len(cycle_lines) == 1, cycle_lines
    assert len(breaker_lines) == 1


async def test_every_failed_cycle_leaves_a_durable_row(tmp_path: Path, august_panel: Any) -> None:
    """The -1023 on 2026-09-04 left only a log line; a failed cycle has to be readable afterwards."""
    result = await _run_until_breaker(tmp_path, august_panel, limit=12)

    errors = [row for row in result["rows"] if row.get("phase") == "ERROR"]
    assert len(errors) == 12
    assert errors[-1]["consecutive_errors"] == 12
    assert "equity" not in errors[-1]  # or the drift check would read an outage as a loss


def test_the_cli_exits_zero_when_the_breaker_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The branch that decides between a stopped book and L1-03's relaunch loop.

    The engine is the real class with only `run` replaced: a bare stub would need every attribute the
    CLI touches bolted on one AttributeError at a time, and each one bolted on is a place the test
    stops resembling the thing it is testing.

    The venue is the real `PaperVenue` with only the `exchangeInfo` FETCH replaced, for the same
    reason and to the same depth.  `live run --paper` builds it at `live_cmd.py:223`, before the
    engine exists, so this branch could not be reached without the public internet - the one
    dependency a test about an exit code has no business having.
    """
    import yaml
    from click.testing import CliRunner

    import starquant_cli.live_cmd as live_cmd
    from starquant_cli import main
    from starquant_live.engine import LiveEngine

    class _Engine(LiveEngine):
        async def run(self, *args: Any, **kwargs: Any) -> int:
            raise BreakerTripped("12 consecutive cycle failures: RuntimeError: venue is unreachable")

    profile = yaml.safe_load(Path("config/live.demo.yaml").read_text(encoding="utf-8"))
    profile["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    profile["guards"]["kill_switch_path"] = str(tmp_path / "KILL_SWITCH")
    profile["market_data"]["rest_url"] = UNREACHABLE
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    monkeypatch.setattr(live_cmd, "LiveEngine", _Engine)
    monkeypatch.setattr(live_cmd, "_paper_venue", paper_venue_from())
    result = CliRunner().invoke(
        main,
        ["live", "run", "--paper", "--dry-run", "--allow-unvalidated", "--cycles", "1", "--profile", str(profile_path)],
    )

    assert result.exit_code == 0, result.output
    assert "breaker tripped" in result.output
    assert "launchd" in result.output  # the reason exit 0 is the right code is said out loud
