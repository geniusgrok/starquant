"""M-010's evidence can lose a block of hours and every reader of it will see a shorter window instead.

`state.py` returns an empty state when `state.json` fails to parse; `engine.py`'s income watermark is
then `self.state.last_income_ms or now`, i.e. *now*, and the income earned while the loop was away is
never queried.  `attribution.jsonl` keeps its rows on both sides of the hole, `decay_watch` reads
`live_windows` as merely shorter, and nothing anywhere says "a stretch is missing".  Every row has
carried `since_ms` / `until_ms` since the first live commit and nothing compared one row's end to the
next row's start.

These tests pin the two halves that must not be confused:

  * a gap is NORMAL - a row is written only by a cycle that had income, so a quiet hour leaves one.
    On the live record 2026-09-13: 42 rows, span 213.0 h, union 37.3 h (`coverage` 0.175), 31 gaps,
    widest 18.0 h, and not one of them lost a cent.  A `coverage` near 1.0 is not the healthy reading
    and this file must never be read as if it were.
  * a gap the loop did NOT run through is the failure, because the cycle at a gap's right edge is the
    one that queried across it.  One cycle period wide, the two shapes are indistinguishable (a single
    quiet hour leaves nothing strictly inside its gap); several periods wide, only the hole does.

And the rule that comes with a new reading: it reports, it does not gate.  `report daily --check`
exits non-zero on `alerts`, so a file full of benign gaps must not add one.
"""

from __future__ import annotations

from pathlib import Path

from starquant_live.reports import attribution_coverage, daily_alerts, daily_markdown, daily_payload
from starquant_live.state import StateStore

HOUR = 3_600_000
BASE = 1_789_000_000_000 // HOUR * HOUR
SECOND = 1_000


def _iso(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _store(
    tmp_path: Path,
    *,
    cycles: range,
    income_at: set[int],
    down_at: set[int] = frozenset(),
    wiped_at: set[int] = frozenset(),
) -> StateStore:
    """One cycle an hour, chained the way `_ingest_income` chains them.

    Each cycle wakes a second after its bar, queries [the previous cycle's wake, its own wake], and
    writes an attribution row only if that window earned something.  `down_at` is an hour the loop
    did not run at all - the watermark survives, so the cycle after it queries across the whole
    outage and nothing is lost.  `wiped_at` is that same outage with `state.json` unreadable on
    restart: `since = self.state.last_income_ms or now` becomes *now*, the hours in between are
    never queried, and no row records that they existed.  That second shape is the failure.
    """
    store = StateStore(tmp_path / "live")
    previous: int | None = None
    for index in cycles:
        bar = BASE + index * HOUR
        woke = bar + SECOND
        if index in down_at:  # no cycle row and no ingestion: the loop was not running this hour
            continue
        store.append_cycle({"bar_open_ms": bar, "equity": 10_000.0, "at": _iso(woke)})
        if index in wiped_at:
            # The restart cycle with an empty state: it queries [now, now], finds nothing, writes no
            # row, and leaves the watermark at its own wake.  Everything before it is unreachable.
            previous = woke
            continue
        if index in income_at and previous is not None:
            store.append_attribution(
                {"bar_open_ms": bar, "since_ms": previous, "until_ms": woke, "by_strategy": {"tsmom": -1.0}}
            )
        previous = woke
    return store


def test_a_contiguous_series_reads_as_covered(tmp_path: Path) -> None:
    """Every hour earned something: the rows meet end to end and the span is fully covered."""
    store = _store(tmp_path, cycles=range(10), income_at=set(range(10)))
    block = attribution_coverage(store)
    assert block["enforced"] is True
    assert block["gap_count"] == 0
    assert block["covered_ms"] == block["span_ms"] == 9 * HOUR, "the first cycle has no previous wake to ingest from"
    assert block["coverage"] == 1.0
    assert block["gaps_without_a_cycle"] == 0


def test_quiet_hours_leave_gaps_that_lost_nothing(tmp_path: Path) -> None:
    """The live shape: 31 of 31 gaps are hours the book simply earned nothing, and the loop ran through them."""
    store = _store(tmp_path, cycles=range(24), income_at={1, 8, 20})
    block = attribution_coverage(store)
    assert block["gap_count"] == 2, "8 follows 1 and 20 follows 8"
    assert block["gaps_without_a_cycle"] == 0, "a cycle ran every hour in between; income WAS queried"
    assert block["coverage"] < 0.2, "and `coverage` is low for exactly that reason - it is not a health score"


def test_an_outage_the_watermark_survived_loses_nothing(tmp_path: Path) -> None:
    """Nine hours down but `state.json` intact: the next cycle queries across the whole outage.

    The window is one wide row rather than nine, so there is no gap at all - which is exactly the
    recovery `_ingest_income`'s docstring describes, and this reading must not call it a hole.
    """
    store = _store(tmp_path, cycles=range(24), income_at={1, 2, 12, 13}, down_at=set(range(3, 12)))
    block = attribution_coverage(store)
    assert block["gap_count"] == 0
    assert block["coverage"] == 1.0


def test_a_wiped_watermark_is_the_thing_this_reads(tmp_path: Path) -> None:
    """The same outage with an unreadable state on restart: ten hours no cycle ran through, and no row says so."""
    store = _store(tmp_path, cycles=range(24), income_at={1, 2, 13, 14}, down_at=set(range(3, 12)), wiped_at={12})
    block = attribution_coverage(store)
    assert block["gap_count"] == 1
    assert block["gaps_without_a_cycle"] == 1
    assert block["largest_gap_without_a_cycle_ms"] == 10 * HOUR, "bar 2's wake to the restart cycle's own wake"
    assert block["largest_gap_ms"] == 10 * HOUR
    assert block["coverage"] < 1.0


def test_one_hour_of_silence_and_one_hour_of_downtime_are_not_distinguished(tmp_path: Path) -> None:
    """Stated as a test because it is the limit of the instrument, not a defect to be fixed quietly.

    A single quiet cycle leaves a gap with nothing STRICTLY inside it, exactly as an hour of downtime
    does.  That is why the reading is one cycle period wide on a healthy live file and why it carries
    no threshold: a gate here would fire on a quiet hour.
    """
    store = _store(tmp_path, cycles=range(6), income_at={1, 3})
    block = attribution_coverage(store)
    assert block["gap_count"] == 1
    assert block["gaps_without_a_cycle"] == 1
    assert block["largest_gap_without_a_cycle_ms"] == HOUR, "one period of silence, shaped like one of downtime"


def test_it_refuses_rather_than_reading_one_row_as_complete(tmp_path: Path) -> None:
    """A file reduced to one row is what the failure LOOKS like; `covered / span` would read 1.0."""
    store = _store(tmp_path, cycles=range(3), income_at={1})
    block = attribution_coverage(store)
    assert block["enforced"] is False
    assert block["coverage"] is None and block["gap_count"] is None
    assert "fewer than 2" in str(block["reason"])


def test_an_empty_file_says_so_and_returns_no_number(tmp_path: Path) -> None:
    """D-035: a reading that cannot be computed is `enforced: false` plus a reason, never a 1.0."""
    block = attribution_coverage(StateStore(tmp_path / "live"))
    assert block == {**block, "enforced": False, "rows": 0, "coverage": None, "gaps_without_a_cycle": None}
    assert block["reason"]


def test_rows_that_cannot_say_their_window_are_counted_not_skipped(tmp_path: Path) -> None:
    """A row without a readable window shrinks what can be checked, and the reader is told how many."""
    store = _store(tmp_path, cycles=range(6), income_at={1, 3, 5})
    store.append_attribution({"bar_open_ms": BASE, "by_strategy": {"tsmom": -1.0}})  # pre-window shape
    store.append_attribution({"bar_open_ms": BASE, "since_ms": BASE + HOUR, "until_ms": BASE, "by_strategy": {}})
    block = attribution_coverage(store)
    assert block["unreadable_rows"] == 2, "one with no window at all, one that ends before it starts"
    assert block["rows"] == 3


def test_a_window_ingested_twice_is_counted(tmp_path: Path) -> None:
    """An overlap is the other way income goes wrong: the same rows queried twice, attributed twice."""
    store = _store(tmp_path, cycles=range(6), income_at={1, 2, 3})
    store.append_attribution(
        {"bar_open_ms": BASE + 2 * HOUR, "since_ms": BASE + SECOND, "until_ms": BASE + 3 * HOUR, "by_strategy": {}}
    )
    block = attribution_coverage(store)
    assert block["overlap_count"] >= 1
    assert block["gap_count"] == 0


def test_the_daily_report_carries_it_and_does_not_gate_on_it(tmp_path: Path) -> None:
    """O3 lands in the evidence-window section, and `report daily --check` keeps its exit code."""
    day = "2026-09-10"  # the UTC day BASE falls on
    holed = _store(
        tmp_path / "holed", cycles=range(24), income_at={1, 2, 21, 22}, down_at=set(range(3, 20)), wiped_at={20}
    )
    clean = _store(tmp_path / "clean", cycles=range(24), income_at=set(range(24)))
    holed_payload = daily_payload(holed, day, {})
    clean_payload = daily_payload(clean, day, {})
    assert holed_payload["attribution_coverage"]["gaps_without_a_cycle"] == 1
    assert clean_payload["attribution_coverage"]["gaps_without_a_cycle"] == 0
    # `live report daily --check` exits non-zero on `alerts` only.  A hole is a reading, not a breach.
    assert daily_alerts(holed_payload)[0] == daily_alerts(clean_payload)[0]
    text = daily_markdown(holed_payload)
    assert "gaps_without_a_cycle" in text and "attributed_hours" in text
