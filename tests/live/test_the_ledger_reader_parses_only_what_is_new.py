"""`read_jsonl` caches an append-only ledger, and a cache that is ever wrong is worse than none.

`run_cycle` reads `cycles.jsonl` and `attribution.jsonl` twice each per cycle (`_risk_ladder` and
`_check_probes`), and `report daily` reads `cycles.jsonl` eleven times for one report.  Each read used
to re-parse the whole file: ~7 MB per cycle at today's 319 rows, and the ledger grows ~48 MB a year at
one bar an hour, so the same code re-parses ~190 MB per cycle after a year.

`_append` writes whole lines and never rewrites one, which is what makes resuming from a byte offset
sound.  These tests are about every way that assumption can fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_live.state import StateStore


def _rows(store: StateStore) -> list[dict[str, object]]:
    return store.read_jsonl(store.cycles_path)


def test_an_empty_ledger_reads_as_no_rows(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")

    assert _rows(store) == []


def test_appended_rows_appear_on_the_next_read(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")
    store.append_cycle({"bar_open_ms": 1})
    assert len(_rows(store)) == 1

    store.append_cycle({"bar_open_ms": 2})
    rows = _rows(store)

    assert len(rows) == 2
    assert [row["bar_open_ms"] for row in rows] == [1, 2]


def test_the_result_is_a_copy_so_a_caller_cannot_poison_the_cache(tmp_path: Path) -> None:
    """Callers sort and mutate these rows.  A cache a caller can edit is worse than no cache."""
    store = StateStore(tmp_path / "live")
    store.append_cycle({"bar_open_ms": 1})

    first = _rows(store)
    first.append({"bar_open_ms": 999})
    first.reverse()

    assert [row["bar_open_ms"] for row in _rows(store)] == [1]


def test_a_rewritten_ledger_is_re_read_rather_than_resumed(tmp_path: Path) -> None:
    """Truncate-and-rewrite is not an append, and resuming from the old offset would splice history."""
    store = StateStore(tmp_path / "live")
    for bar in (1, 2, 3):
        store.append_cycle({"bar_open_ms": bar})
    assert len(_rows(store)) == 3

    store.cycles_path.write_text(json.dumps({"bar_open_ms": 99}) + "\n", encoding="utf-8")

    assert [row["bar_open_ms"] for row in _rows(store)] == [99]


def test_a_ledger_that_grew_without_a_row_boundary_is_re_read(tmp_path: Path) -> None:
    """A torn write leaves the file longer but not at a line boundary; the tail must not be spliced on."""
    store = StateStore(tmp_path / "live")
    store.append_cycle({"bar_open_ms": 1})
    assert len(_rows(store)) == 1

    # Rewrite the file as one row plus a PARTIAL second row, so the cached size no longer lands after
    # a newline.  Resuming from it would parse the partial row's tail as though it were whole.
    torn = json.dumps({"bar_open_ms": 1}) + "\n" + '{"bar_open_ms": 2, "hal'
    store.cycles_path.write_text(torn, encoding="utf-8")

    rows = _rows(store)

    assert [row["bar_open_ms"] for row in rows] == [1], "the half row is skipped, the whole one survives"


def test_the_completion_of_a_torn_row_is_picked_up(tmp_path: Path) -> None:
    """And once the writer finishes the line, the row appears - no stale cache holding the old answer."""
    store = StateStore(tmp_path / "live")
    store.cycles_path.write_text(json.dumps({"bar_open_ms": 1}) + "\n" + '{"bar_open_ms": 2, "hal', encoding="utf-8")
    assert len(_rows(store)) == 1

    store.cycles_path.write_text(
        json.dumps({"bar_open_ms": 1}) + "\n" + json.dumps({"bar_open_ms": 2}) + "\n", encoding="utf-8"
    )

    assert [row["bar_open_ms"] for row in _rows(store)] == [1, 2]


def test_a_deleted_ledger_forgets_what_it_had(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "live")
    store.append_cycle({"bar_open_ms": 1})
    assert len(_rows(store)) == 1

    store.cycles_path.unlink()

    assert _rows(store) == []


def test_only_the_new_bytes_are_parsed(tmp_path: Path) -> None:
    """The point of the whole thing, measured rather than asserted about.

    Counting `json.loads` calls is how this says "the second read did not redo the first read's work"
    without depending on a wall clock.
    """
    import starquant_live.state as state_mod

    store = StateStore(tmp_path / "live")
    for bar in range(50):
        store.append_cycle({"bar_open_ms": bar})
    assert len(_rows(store)) == 50  # warm

    calls = 0
    real = state_mod.json.loads

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)  # type: ignore[arg-type]

    state_mod.json.loads = counting  # type: ignore[assignment]
    try:
        _rows(store)  # unchanged file: nothing to parse
        assert calls == 0

        store.append_cycle({"bar_open_ms": 50})
        rows = _rows(store)
    finally:
        state_mod.json.loads = real  # type: ignore[assignment]

    assert len(rows) == 51
    assert calls == 1, f"one new row should cost one parse, not 51 (got {calls})"
