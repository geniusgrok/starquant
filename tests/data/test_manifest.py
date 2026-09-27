"""The dataset manifest, written against the drift it exists to catch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_data.manifest import DatasetManifest, build_manifest, manifest_check, manifest_problems
from starquant_data.store import FundingStore, KlineStore


def _funding(*, rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "funding_time": [i * 28_800_000 for i in range(rows)],
            "funding_rate": [0.0001] * rows,
            "mark_price": [100.0] * rows,
        }
    )


def _root(tmp_path: Path, *, refreshes: int, freq: str, symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    index = pd.date_range("2024-01-01", periods=refreshes, freq=freq, tz="UTC")
    table = pd.DataFrame(True, index=index, columns=list(symbols))
    table.to_parquet(root / "membership.parquet")
    (root / "universe.json").write_text(
        json.dumps({"symbols": list(symbols), "source": "pool-refresh", "selected_at_ms": 1}), encoding="utf-8"
    )
    # Written through the stores themselves.  A fixture that spells the layout out by hand is the same
    # duplication that blinded the funding fact for every report that ever carried one (D-040).
    KlineStore(root).append("BTCUSDT", "1h", pd.DataFrame({"open_time": [0, 3_600_000], "close": [1.0, 2.0]}))
    FundingStore(root).append("BTCUSDT", _funding(rows=2))
    return root


def test_a_manifest_of_unchanged_data_reports_no_problem(tmp_path: Path) -> None:
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    assert manifest_problems(recorded, build_manifest(root)) == []


def test_the_p12_drift_is_named_rather_than_merely_detected(tmp_path: Path) -> None:
    """A monthly table rebuilt as daily is the 2026-09-04 incident; the manifest must say which field moved."""
    root = _root(tmp_path, refreshes=6, freq="MS")
    recorded = build_manifest(root).to_dict()

    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")

    problems = manifest_problems(recorded, build_manifest(root))
    assert problems, "a table rebuilt at a different cadence must not pass silently"
    message = problems[0]
    assert "membership.refreshes: 6 -> 180" in message
    assert "membership.median_gap_hours" in message, "the cadence change is the fact P12 needed"


def test_a_changed_universe_selection_is_caught(tmp_path: Path) -> None:
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "live-refresh", "selected_at_ms": 2}), encoding="utf-8"
    )
    problems = manifest_problems(recorded, build_manifest(root))
    assert problems and "universe.fingerprint" in problems[0]


def test_a_result_with_no_manifest_reports_unknown_provenance_not_agreement(tmp_path: Path) -> None:
    """ "No manifest" and "manifest matches" are different facts and must not collapse into each other."""
    root = _root(tmp_path, refreshes=30, freq="D")
    problems = manifest_problems(None, build_manifest(root))
    assert problems and "cannot be checked" in problems[0]


def test_the_digest_ignores_mtime_so_a_rewrite_of_identical_data_is_not_drift(tmp_path: Path) -> None:
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    table = pd.read_parquet(root / "membership.parquet")
    table.to_parquet(root / "membership.parquet")  # same content, new mtime
    assert manifest_problems(recorded, build_manifest(root)) == []


def test_both_store_layouts_are_counted(tmp_path: Path) -> None:
    """klines nest as ``<SYMBOL>/<interval>.parquet``; funding is flat as ``<SYMBOL>.parquet``.

    ``_store_fact`` walked the nested layout for both and guarded with ``child.is_dir()``, so every
    funding file was skipped.  On 2026-09-05 a 231-file / 20 MB archive still read ``{0, 0, ...}``.
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    manifest = build_manifest(root)
    assert manifest.klines is not None and manifest.funding is not None
    assert manifest.klines["symbols"] == 1, "the nested klines layout must still be counted"
    assert manifest.funding["symbols"] == 1, "the flat funding layout must be counted"
    assert manifest.funding["bytes"] > 0


def test_a_changed_funding_archive_is_caught(tmp_path: Path) -> None:
    """Why counting funding matters: D-034 rewrote what that archive means and no manifest could see it."""
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    FundingStore(root).append("ETHUSDT", _funding(rows=3))
    problems = manifest_problems(recorded, build_manifest(root))
    assert problems, "a funding archive that grew must not pass silently"
    assert "funding.symbols: 1 -> 2" in problems[0]


def _v1_record(root: Path) -> dict[str, Any]:
    """A manifest as reports on disk actually carry it: written before D-040, so no version stamp and a
    funding fact the layout bug had blinded to zero.  ``44136fa355b3678a`` is the fingerprint all four
    surviving reports carry, and it is exactly ``_digest({})``."""
    current = build_manifest(root)
    blinded = DatasetManifest(
        root=current.root,
        interval=current.interval,
        membership=current.membership,
        universe=current.universe,
        klines=current.klines,
        funding={"symbols": 0, "bytes": 0, "fingerprint": "44136fa355b3678a"},
    )
    recorded = blinded.to_dict()  # digest computed over the blind funding fact, as v1 wrote it
    recorded.pop("version", None)
    return recorded


def test_a_v1_zero_funding_record_reads_as_unknown_rather_than_as_an_empty_archive(tmp_path: Path) -> None:
    """The pre-D-040 zero means "the manifest could not look", not "the archive was empty".

    Reporting it as drift would assert the archive grew, which is a false claim about history; staying
    silent would collapse unknown into agreement, which is the one thing this module refuses to do.
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    problems = manifest_problems(_v1_record(root), build_manifest(root))
    joined = " ".join(problems)
    assert "funding" in joined and "cannot be checked" in joined
    assert "funding.symbols: 0 -> 1" not in joined, "a blind manifest must not be reported as a grown archive"


def test_a_recorded_empty_funding_archive_is_a_real_zero_once_the_manifest_can_see_the_store(
    tmp_path: Path,
) -> None:
    """Why the version stamp earns its keep: after D-040 a zero is a measurement, so growth is drift."""
    root = _root(tmp_path, refreshes=30, freq="D")
    for path in FundingStore(root).directory.glob("*.parquet"):
        path.unlink()
    recorded = build_manifest(root).to_dict()
    FundingStore(root).append("BTCUSDT", _funding(rows=2))

    problems = manifest_problems(recorded, build_manifest(root))
    assert problems and "funding.symbols: 0 -> 1" in problems[0], "a measured zero must register growth"
    assert "cannot be checked" not in " ".join(problems)


def test_a_membership_cadence_rebuild_blocks_rather_than_merely_informs(tmp_path: Path) -> None:
    """P12's shape: the table's meaning changed, so evidence computed on it no longer describes it."""
    root = _root(tmp_path, refreshes=6, freq="MS")
    recorded = build_manifest(root).to_dict()
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")

    check = manifest_check(recorded, build_manifest(root))
    assert check.blocking and "membership.refreshes: 6 -> 180" in check.blocking[0]
    assert not check.advisory


def test_a_changed_symbol_set_under_the_same_source_blocks(tmp_path: Path) -> None:
    """The book the evidence describes is not the book being traded."""
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root))
    assert check.blocking and "universe.fingerprint" in check.blocking[0]


def test_the_live_loops_own_universe_refresh_is_advisory_not_blocking(tmp_path: Path) -> None:
    """``universe.json`` is rewritten by the running loop, so a changed *source* is its bookkeeping.

    Measured 2026-09-04: tsmom's cited universe read ``pool-refresh``/15 while disk read
    ``live-refresh``/16.  Blocking on that would have the loop refuse to start because of its own
    refresh.  Validation runs on the point-in-time membership table, which is why that one blocks
    unconditionally and this one does not.
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "source": "live-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root))
    assert not check.blocking, "a loop-driven re-selection must not stop the loop"
    assert check.advisory and "universe.source: pool-refresh -> live-refresh" in check.advisory[0]


def test_klines_growth_is_advisory_because_the_daily_sync_guarantees_it(tmp_path: Path) -> None:
    """The archive gains bars every day; blocking on that would refuse every start after a sync."""
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    KlineStore(root).append("ETHUSDT", "1h", pd.DataFrame({"open_time": [0], "close": [1.0]}))

    check = manifest_check(recorded, build_manifest(root))
    assert not check.blocking, "normal archive growth must not stop the loop"
    assert check.advisory and "klines.symbols: 1 -> 2" in check.advisory[0]


def test_provenance_never_recorded_is_advisory_so_nothing_in_flight_is_blocked(tmp_path: Path) -> None:
    """Mirrors the portfolio-block precedent: a report predating a gate dimension is skipped, not refused."""
    root = _root(tmp_path, refreshes=30, freq="D")
    absent = manifest_check(None, build_manifest(root))
    assert not absent.blocking and absent.advisory

    v1 = manifest_check(_v1_record(root), build_manifest(root))
    assert not v1.blocking, "a v1 funding unknown must not stop the loop"
    assert any("cannot be checked" in message for message in v1.advisory)


def test_manifest_problems_stays_the_two_buckets_in_order(tmp_path: Path) -> None:
    root = _root(tmp_path, refreshes=6, freq="MS")
    recorded = build_manifest(root).to_dict()
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")
    KlineStore(root).append("ETHUSDT", "1h", pd.DataFrame({"open_time": [0], "close": [1.0]}))

    current = build_manifest(root)
    check = manifest_check(recorded, current)
    assert check.blocking and check.advisory
    assert manifest_problems(recorded, current) == [*check.blocking, *check.advisory]


def test_a_pit_report_does_not_block_on_the_universe_file(tmp_path: Path) -> None:
    """A ``universe_mode: "pit"`` result's population is ``membership.parquet``; it never opens this file.

    ``research_cmd._resolve_symbols`` takes the membership union under ``pit`` and calls
    ``read_universe`` only under ``static``.  So blocking a pit result here refuses an armed start over
    a file that result never read.  The 2026-09-09 workaround for that was to freeze the TRADED pool
    instead, which left the live universe at 16 names from 09-09 to 09-15 while the cited evidence
    re-ranked every 24 hours (``median_gap_hours: 24.0``, ``union: 211``, ``mean_size: 17.58``).
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root), universe_mode="pit")
    assert not check.blocking, "a pit result's population is the membership table, not this file"
    assert check.advisory and "universe.fingerprint" in check.advisory[0]


def test_a_static_report_still_blocks_on_the_universe_file(tmp_path: Path) -> None:
    """``universe.json`` IS a static result's population, so its drift stays the real thing."""
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root), universe_mode="static")
    assert check.blocking and "universe.fingerprint" in check.blocking[0]


def test_a_pit_report_still_blocks_on_the_membership_table(tmp_path: Path) -> None:
    """The exemption moves ONE field.  A pit result's real gate is the table it actually ran on."""
    root = _root(tmp_path, refreshes=6, freq="MS")
    recorded = build_manifest(root).to_dict()
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")

    check = manifest_check(recorded, build_manifest(root), universe_mode="pit")
    assert check.blocking and "membership.refreshes: 6 -> 180" in check.blocking[0]
