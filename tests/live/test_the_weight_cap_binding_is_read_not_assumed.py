"""D-046: `max_weight` binding was listed as a cause and never measured; now it is read.

`risk_adaptation`'s docstring names four honest reasons compression can rise with stage 1 untouched,
and one of them - "``max_weight`` binding on the calmest names" - stopped being hypothetical when
`vol_target` went to 0.60.  Nothing had to be recorded to measure it: `book_weights` has been in the
cycle row since 2026-09-12, and a name the cap truncated sits at exactly `max_weight`.

The reading is a lower bound whenever a bar was ALSO gross-capped, because stage 3 clips per symbol
and then scales the whole row.  The bound has to render as a bound - that is most of this file.
"""

from __future__ import annotations

from typing import Any

from starquant_live.reports import _weight_cap_line, max_weight_of, weight_cap_bindings
from starquant_live.state import StateStore


def _cycle(weights: dict[str, float], *, gross_capped: bool = False, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"book_weights": {"main": weights}, "guard_reasons": ["GROSS_CAPPED"] if gross_capped else []}
    return {**row, **extra}


def test_a_name_sitting_at_the_cap_is_counted_and_named() -> None:
    cycles = [
        _cycle({"BTCUSDT": 0.15, "ETHUSDT": 0.04}),
        _cycle({"BTCUSDT": 0.15, "BNBUSDT": 0.15}),
        _cycle({"BTCUSDT": 0.09, "ETHUSDT": 0.02}),
    ]

    reading = weight_cap_bindings(cycles, 0.15)

    assert reading["readable"] and reading["cycles"] == 3
    assert reading["bound_cycles"] == 2 and reading["share"] == 2 / 3
    assert reading["by_symbol"] == {"BTCUSDT": 2, "BNBUSDT": 1}
    assert reading["gross_capped_bars"] == 0


def test_a_short_position_at_the_cap_counts_too() -> None:
    """The cap is on |w|; a book that is short its calmest name is truncated the same way."""
    reading = weight_cap_bindings([_cycle({"BTCUSDT": -0.15})], 0.15)

    assert reading["bound_cycles"] == 1 and reading["by_symbol"] == {"BTCUSDT": 1}


def test_the_count_says_it_is_a_lower_bound_once_anything_was_gross_capped() -> None:
    """A truncated name on a gross-capped bar lands at `max_weight * factor` and is invisible here.

    Reporting the count alone would be an undercount that reads like a count, so the renderer has to
    say so on the same line.  Measured over the whole live record on 2026-09-17: 0 of 376 cycles have
    ever carried GROSS_CAPPED, so today the reading is exact - which is exactly why the guard has to
    exist before that changes rather than after.
    """
    cycles = [_cycle({"BTCUSDT": 0.15}), _cycle({"BTCUSDT": 0.12}, gross_capped=True)]

    reading = weight_cap_bindings(cycles, 0.15)

    assert reading["bound_cycles"] == 1 and reading["gross_capped_bars"] == 1
    assert "下界" in _weight_cap_line(reading)
    assert "下界" not in _weight_cap_line(weight_cap_bindings([_cycle({"BTCUSDT": 0.15})], 0.15))


def test_an_unreadable_window_says_why_rather_than_reading_zero() -> None:
    """D-035's rule: a reading that could not be taken must never look like one that passed."""
    assert weight_cap_bindings([_cycle({"BTCUSDT": 0.15})], None)["readable"] is False
    assert weight_cap_bindings([{"guard_reasons": []}], 0.15)["readable"] is False
    assert "读不出" in _weight_cap_line(weight_cap_bindings([], 0.15))


def test_the_cap_is_read_off_the_running_construction_not_the_config_file(tmp_path: Any) -> None:
    """KILL-Q15's shape: the engine builds its model once, so the file is not necessarily the loop."""
    store = StateStore(tmp_path)
    assert max_weight_of(store) is None  # no cycle yet: unknown, not a default
    store.append_cycle({"bar_open_ms": 1, "construction_full": {"guards": {"max_weight": 0.15}}})
    store.append_cycle({"bar_open_ms": 2})
    assert max_weight_of(store) == 0.15
    # A later process recording a different construction wins: the newest is what is running.
    store.append_cycle({"bar_open_ms": 3, "construction_full": {"guards": {"max_weight": 0.08}}})
    assert max_weight_of(store) == 0.08
