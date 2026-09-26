"""M-015's own docstring pre-registered this fix before the alert that needed it.

`RISK_COMPRESSION_LIMIT`'s comment has said since 2026-09-08:

    Alert again from a cancellation and the answer is to measure the main book separately,
    NOT to raise this a second time.

On 2026-09-10 it alerted, and kept alerting for two days at 0.96-0.97 against 0.76.  Decomposed on
the live book of 2026-09-12:

    fourteen names only tsmom holds   risk contribution 0.024199 EVERY ONE, spread 1.000000
    four names the flow probe overlays  0.0078 / 0.0119 (cancelling) and 0.0563 / 0.0628 (stacking)

The whole 8.07x risk spread is max/min over those four.  Stage 1 is not what moved: on the names it
alone sizes it is exact to six figures.  The probe book is vol-targeted on its own at fraction 1/3
over four names against the main book's eighteen, so it carries ~1.4x the main book's per-name risk
where they overlap - arithmetic, not a fault, and invisible to a max/min taken after `combine_books`.

So the gate follows the single-book reading and the combined one is still computed and printed - the
same shape as the 2026-09-10 L3 ruling: moving a reading out of the gate is not deleting it.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

from starquant_live.reports import RISK_COMPRESSION_LIMIT, risk_adaptation
from starquant_live.state import LiveState, StateStore

BASE = 1_788_000_000_000
DAY = datetime.fromtimestamp(BASE / 1000, tz=UTC).strftime("%Y-%m-%d")

# Six names at a 4x vol spread; stage 1 sizes each to the same risk contribution of 0.03.
VOLS = {
    "AAAUSDT": 0.40,
    "BBBUSDT": 0.80,
    "EEEUSDT": 0.60,
    "FFFUSDT": 1.00,
    "CCCUSDT": 1.20,
    "DDDUSDT": 1.60,
}
MAIN = {symbol: 0.03 / vol for symbol, vol in VOLS.items()}


def _store(tmp_path: Path, targets: dict[str, float], *, books: dict | None, contributions: dict) -> StateStore:
    store = StateStore(tmp_path / "live")
    record: dict[str, object] = {
        "as_of_ms": BASE,
        "equity": 10_000.0,
        "targets": targets,
        "asset_vol": VOLS,
        "contributions": contributions,
    }
    if books is not None:
        record["books"] = books
    store.append_cycle(record)
    store.save(LiveState(leverage_set=dict.fromkeys(targets, 5)))
    return store


def _overlaid(tmp_path: Path) -> StateStore:
    """The 2026-09-12 shape: a second book stacking on one name and cancelling on another."""
    targets = dict(MAIN)
    targets["DDDUSDT"] = MAIN["DDDUSDT"] * 2.6  # stacks -> the max
    targets["CCCUSDT"] = MAIN["CCCUSDT"] * 0.32  # cancels -> the min
    return _store(
        tmp_path,
        targets,
        books={"tsmom": "main", "flow": "flow_short"},
        contributions={
            "tsmom": dict.fromkeys(VOLS, 1.0),
            "flow": {"CCCUSDT": -0.25, "DDDUSDT": -0.21},
        },
    )


def test_the_gate_reads_the_names_one_book_carries_alone(tmp_path: Path) -> None:
    """Stage 1 is exact on its own names, and that is the reading the alert is taken on."""
    block = risk_adaptation(_overlaid(tmp_path), DAY)
    assert block["judged"] == "single_book"
    assert block["single_book"]["symbols"] == 4
    assert math.isclose(block["single_book"]["risk_spread"], 1.0, rel_tol=1e-9)
    assert block["status"] == "OK"


def test_the_combined_reading_is_still_computed_and_still_printed(tmp_path: Path) -> None:
    """Moving a reading out of the gate is not deleting it (the 2026-09-10 L3 ruling's shape)."""
    block = risk_adaptation(_overlaid(tmp_path), DAY)
    combined = block["combined"]
    assert combined["symbols"] == 6
    assert combined["compression"] > RISK_COMPRESSION_LIMIT, "the book as held really does spread 8x"
    assert block["overlaid"]["names"] == ["CCCUSDT", "DDDUSDT"]
    assert block["overlaid"]["books"] == ["flow_short", "main"]


def test_deleting_stage_one_still_alerts_on_the_single_book_reading(tmp_path: Path) -> None:
    """The falsifier has to survive the split, or the split is just a way to stop alerting.

    Size every name alike INSIDE the main book and the single-book reading goes to 1.0 - the overlay
    cannot hide it, because the overlaid names are not in that reading at all.
    """
    flat = dict.fromkeys(VOLS, 0.05)
    flat["DDDUSDT"] = 0.05 * 2.6
    store = _store(
        tmp_path,
        flat,
        books={"tsmom": "main", "flow": "flow_short"},
        contributions={"tsmom": dict.fromkeys(VOLS, 1.0), "flow": {"DDDUSDT": -0.21}},
    )
    block = risk_adaptation(store, DAY)
    assert block["judged"] == "single_book" and block["single_book"]["symbols"] == 5
    assert math.isclose(block["compression"], 1.0, rel_tol=1e-12)
    assert block["status"] == "ALERT"


def test_a_cycle_with_no_books_falls_back_to_the_combined_reading_not_to_silence(tmp_path: Path) -> None:
    """Every cycle written before 2026-09-12 is this case.  An unreadable split is not a pass."""
    flat = dict.fromkeys(VOLS, 0.05)
    store = _store(tmp_path, flat, books=None, contributions={"tsmom": dict.fromkeys(VOLS, 1.0)})
    block = risk_adaptation(store, DAY)
    assert block["judged"] == "combined"
    assert math.isclose(block["compression"], 1.0, rel_tol=1e-12)
    assert block["status"] == "ALERT"


def test_a_single_book_day_is_unchanged_by_any_of_this(tmp_path: Path) -> None:
    """With one book every name is in the single-book reading, so the number cannot move."""
    store = _store(tmp_path, dict(MAIN), books={"tsmom": "main"}, contributions={"tsmom": dict.fromkeys(VOLS, 1.0)})
    block = risk_adaptation(store, DAY)
    assert block["judged"] == "single_book" and block["symbols"] == 6
    assert math.isclose(block["risk_spread"], 1.0, rel_tol=1e-9)
    assert block["overlaid"]["names"] == []
