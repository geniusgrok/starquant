"""The same-source contract's other half: one truth for research and live (DL-Q6 / KILL-Q11).

Research eats the T+1 daily archive.  Live can read only the 30-day REST window.  KILL-Q11's finding
is that these are two sources, so a metrics signal validated on one and traded on the other has never
been tested on what it will actually see - and the archive/REST stamp offset showed how quietly that
goes wrong.  The answer the plan names is a snapshot stream: the loop records what IT could read, and
that recording is the common truth.

**Not a separate five-minute daemon**, and the reason is the interesting part.  The granularity that
matters is the BUCKET's (5m), not the poll's: the REST window is 30 days deep, so one poll an hour
retrieves all twelve buckets of the past hour with nothing missed.  Polling at the bar close does
something a 5-minute daemon cannot: it records exactly the buckets that had CLOSED when the loop made
its decision - which is precisely what `align_to_bars` selects.  A separate daemon would be a second
process, a second failure mode and a second thing to restart, to record a superset of the same rows
at instants no decision was made at.

The parity check is the contract's teeth: the same buckets from the snapshot and from the archive must
carry the same numbers, and the divergence rate is reported daily (M-011).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

FIVE_MIN_MS = 5 * 60 * 1000


class _Client:
    """The generic `get` the public feed already exposes; records what was asked for."""

    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows
        self.asked: list[dict[str, Any]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.asked.append({"path": path, **(params or {})})
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


def _rest_rows(n: int, start: str = "2026-09-05 10:05") -> list[dict[str, Any]]:
    base = pd.Timestamp(start, tz="UTC").value // 1_000_000
    return [
        {
            "symbol": "BTCUSDT",
            "sumOpenInterest": f"{100 + i}",
            "sumOpenInterestValue": "1",
            "timestamp": base + i * FIVE_MIN_MS,
        }
        for i in range(n)
    ]


# --- the snapshot ---------------------------------------------------------------------------------


async def test_a_poll_stores_the_buckets_in_the_canonical_shape(tmp_path: Path) -> None:
    from starquant_data.metrics_snapshot import snapshot_metrics
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    client = _Client(_rest_rows(12))

    await snapshot_metrics(client, store, ["BTCUSDT"], period="5m", limit=12)

    frame = store.load("BTCUSDT")
    assert len(frame) == 12
    # canonical: the REST close-stamp has been converted to the bucket OPEN exactly once, here
    assert frame["open_time"].iloc[0] == pd.Timestamp("2026-09-05 10:00", tz="UTC").value // 1_000_000


async def test_the_snapshot_lives_beside_the_archive_not_inside_it(tmp_path: Path) -> None:
    """They have to be comparable, so they cannot be the same file."""
    from starquant_data.store import MetricsStore

    assert MetricsStore(tmp_path, kind="metrics_snapshot").directory != MetricsStore(tmp_path).directory


async def test_polling_twice_in_an_hour_stores_each_bucket_once(tmp_path: Path) -> None:
    from starquant_data.metrics_snapshot import snapshot_metrics
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    for _ in range(3):
        await snapshot_metrics(_Client(_rest_rows(12)), store, ["BTCUSDT"], period="5m", limit=12)

    assert len(store.load("BTCUSDT")) == 12


async def test_one_poll_an_hour_covers_the_hour(tmp_path: Path) -> None:
    """Why no daemon: the REST window is 30 days, so twelve buckets an hour is nothing missed."""
    from starquant_data.metrics_snapshot import snapshot_metrics
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    await snapshot_metrics(_Client(_rest_rows(12, "2026-09-05 10:05")), store, ["BTCUSDT"], period="5m", limit=12)
    await snapshot_metrics(_Client(_rest_rows(12, "2026-09-05 11:05")), store, ["BTCUSDT"], period="5m", limit=12)

    opens = store.load("BTCUSDT")["open_time"]
    gaps = opens.diff().dropna().unique()
    assert list(gaps) == [FIVE_MIN_MS], f"the hourly polls left a gap: {gaps}"


async def test_a_failing_poll_is_recorded_and_never_raised(tmp_path: Path) -> None:
    """Same contract as every other instrument here: data collection may not stop a cycle."""
    from starquant_data.metrics_snapshot import snapshot_metrics
    from starquant_data.store import MetricsStore

    result = await snapshot_metrics(
        _Client(RuntimeError("venue is unreachable")),
        MetricsStore(tmp_path, kind="metrics_snapshot"),
        ["BTCUSDT"],
        period="5m",
        limit=12,
    )

    assert result["error"].startswith("RuntimeError")
    assert result["stored"] == {}


# --- parity, the contract's teeth -----------------------------------------------------------------


def test_parity_counts_the_buckets_that_disagree() -> None:
    from starquant_data.metrics_snapshot import metrics_parity

    archive = pd.DataFrame({"open_time": [1, 2, 3], "sum_open_interest": [10.0, 20.0, 30.0]})
    snapshot = pd.DataFrame({"open_time": [2, 3, 4], "sum_open_interest": [20.0, 99.0, 40.0]})

    parity = metrics_parity(snapshot, archive)

    assert parity["overlapping"] == 2
    assert parity["differing"] == 1
    assert parity["rate"] == pytest.approx(0.5)


def test_no_overlap_is_reported_as_unknown_rather_than_perfect() -> None:
    """Zero differing out of zero compared is not agreement; calling it 1.0 would hide a dead stream."""
    from starquant_data.metrics_snapshot import metrics_parity

    parity = metrics_parity(
        pd.DataFrame({"open_time": [4], "sum_open_interest": [1.0]}),
        pd.DataFrame({"open_time": [1], "sum_open_interest": [1.0]}),
    )

    assert parity["overlapping"] == 0
    assert parity["rate"] is None


def test_parity_is_not_fooled_by_float_noise() -> None:
    from starquant_data.metrics_snapshot import metrics_parity

    archive = pd.DataFrame({"open_time": [1], "sum_open_interest": [107239.507]})
    snapshot = pd.DataFrame({"open_time": [1], "sum_open_interest": [107239.50700000001]})

    assert metrics_parity(snapshot, archive)["differing"] == 0


# --- the gate now has something to read -----------------------------------------------------------


def test_a_signal_declares_whether_it_needs_metrics() -> None:
    """Same shape as `uses_funding`, which this repository already has for exactly this question."""
    from starquant_alpha.signals.base import SignalSpec

    assert "needs_metrics" in SignalSpec.__dataclass_fields__


def test_the_gate_reads_the_snapshot_store_not_the_archive(tmp_path: Path) -> None:
    """The archive is what research has.  The gate is about what LIVE has."""
    from starquant_data.metrics_snapshot import live_coverage_bars
    from starquant_data.store import MetricsStore

    archive = MetricsStore(tmp_path)
    archive.append("BTCUSDT", pd.DataFrame({"open_time": [i * FIVE_MIN_MS for i in range(1000)], "symbol": "BTCUSDT"}))

    assert live_coverage_bars(MetricsStore(tmp_path, kind="metrics_snapshot"), ["BTCUSDT"], interval_ms=3_600_000) == 0


def test_coverage_is_counted_in_BARS_not_in_buckets(tmp_path: Path) -> None:
    """A strategy needs 720 hourly bars, and twelve 5m buckets are one bar."""
    from starquant_data.metrics_snapshot import live_coverage_bars
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    store.append("BTCUSDT", pd.DataFrame({"open_time": [i * FIVE_MIN_MS for i in range(120)], "symbol": "BTCUSDT"}))

    assert live_coverage_bars(store, ["BTCUSDT"], interval_ms=3_600_000) == 10


def test_the_thinnest_symbol_decides(tmp_path: Path) -> None:
    """A book trades a universe: coverage the whole universe does not have is not coverage."""
    from starquant_data.metrics_snapshot import live_coverage_bars
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    store.append("BTCUSDT", pd.DataFrame({"open_time": [i * FIVE_MIN_MS for i in range(120)], "symbol": "BTCUSDT"}))
    store.append("ETHUSDT", pd.DataFrame({"open_time": [i * FIVE_MIN_MS for i in range(24)], "symbol": "ETHUSDT"}))

    assert live_coverage_bars(store, ["BTCUSDT", "ETHUSDT"], interval_ms=3_600_000) == 2


def test_a_gap_under_reports_rather_than_over_reports(tmp_path: Path) -> None:
    """The loop was down for a day.  A span would call the gap covered; a gate must not."""
    from starquant_data.metrics_snapshot import live_coverage_bars
    from starquant_data.store import MetricsStore

    store = MetricsStore(tmp_path, kind="metrics_snapshot")
    early = [i * FIVE_MIN_MS for i in range(12)]
    late = [(i + 10_000) * FIVE_MIN_MS for i in range(12)]  # a very long way later
    store.append("BTCUSDT", pd.DataFrame({"open_time": early + late, "symbol": "BTCUSDT"}))

    # 24 buckets is two hours of data, however far apart they sit
    assert live_coverage_bars(store, ["BTCUSDT"], interval_ms=3_600_000) == 2


# --- wired into the loop --------------------------------------------------------------------------


async def test_the_cycle_records_what_it_could_read(tmp_path: Path, august_panel: Any) -> None:
    """The recording happens where the decision happens, or it is recording something else."""
    from tests.live.helpers_liquidation import cycle_with_metrics

    row, store = await cycle_with_metrics(august_panel, tmp_path, rows=_rest_rows(12))

    assert row["metrics_snapshot"]["stored"]
    assert len(store.load("BTCUSDT")) == 12


async def test_a_dead_metrics_endpoint_does_not_stop_the_cycle(tmp_path: Path, august_panel: Any) -> None:
    from tests.live.helpers_liquidation import cycle_with_metrics

    row, _store = await cycle_with_metrics(august_panel, tmp_path, rows=RuntimeError("down"))

    assert row["metrics_snapshot"]["error"].startswith("RuntimeError")
    # the cycle completed: it priced the book and wrote the fields a completed cycle carries
    assert row["equity"] > 0
    assert row["guard_reasons"] == []
    assert "targets" in row and "min_liq_distance" in row


async def test_startup_refuses_a_metrics_strategy_with_no_live_recording(tmp_path: Path) -> None:
    """KILL-027 made structural: the strategy that needs metrics cannot start before live has them."""
    from tests.live.helpers_liquidation import engine_needing_metrics

    engine = engine_needing_metrics(tmp_path, coverage_buckets=0)

    with pytest.raises(RuntimeError, match="metrics"):
        await engine.startup()


async def test_startup_allows_it_once_the_recording_is_deep_enough(tmp_path: Path) -> None:
    from tests.live.helpers_liquidation import engine_needing_metrics

    engine = engine_needing_metrics(tmp_path, coverage_buckets=12 * 720)

    await engine.startup()  # must not raise
