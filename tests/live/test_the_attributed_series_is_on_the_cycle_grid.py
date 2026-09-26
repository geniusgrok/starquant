"""M-002 / M-010 / M-G06 annualise a series at 8760 bars a year that had four fifths of its hours cut out.

An attribution row is written only by a cycle that HAD income.  Both readers then take the resulting
list as if it were one point per hour: `sharpe(values, bars_per_year=8760)` and `days = size / 24`.
Measured on the live record 2026-09-12, over the 214 cycles the attribution file spans:

    tsmom   41 rows (19% of cycles)   days read 1.71 vs 8.92   Sharpe -15.84 vs -6.78 on the grid
    flow    25 rows (12% of cycles)   days read 1.04 vs 8.92   Sharpe  -2.38 vs -0.77 on the grid

The inflation is sqrt(cycles/rows) - 2.28 and 2.93 predicted, 2.33 and 3.08 measured - because
dropping zeros leaves the sum alone while shrinking the count, so the mean grows faster than the sd.
Those gaps are true zeros: these rows carry realised P&L, commission and funding only, and a cycle
with none of them earned none of them.

It never changed a verdict.  M-G06's criterion is "point estimate >= 0 and nothing else", and deleting
zeros cannot move a sign.  M-010 is the one that was not safe: it divides by a FIXED expected Sharpe's
distance, so an inflated realised number and an inflated error bar do not cancel there.  And
`_has_dispersion`'s 48-bar floor - written as "enough bars", meaning hourly ones - was being asked of
a series where 48 rows meant ten days.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from starquant_live.reports import _series_by_strategy
from starquant_live.state import StateStore

HOUR = 3_600_000
BASE = 1_789_000_000_000 // HOUR * HOUR


def _store(tmp_path: Path, *, cycles: int, income_at: dict[int, dict[str, float]]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for index in range(cycles):
        store.append_cycle({"bar_open_ms": BASE + index * HOUR, "equity": 10_000.0})
        if index in income_at:
            store.append_attribution({"bar_open_ms": BASE + index * HOUR, "by_strategy": income_at[index]})
    return store


def test_every_cycle_in_the_covered_span_becomes_a_point(tmp_path: Path) -> None:
    """Ten cycles, three of them with income: a ten-point series, not a three-point one."""
    store = _store(tmp_path, cycles=10, income_at={2: {"tsmom": -1.0}, 5: {"tsmom": 2.0}, 7: {"tsmom": -1.0}})
    series = _series_by_strategy(store, None)["tsmom"]
    assert len(series) == 6, "bounded by the attribution span: bars 2..7 inclusive"
    assert [value for _bar, value in series] == [-1.0, 0.0, 0.0, 2.0, 0.0, -1.0]


def test_the_gaps_are_zeros_and_the_total_is_untouched(tmp_path: Path) -> None:
    """The fix must not invent or lose a cent; it changes the denominator, not the P&L."""
    store = _store(tmp_path, cycles=20, income_at={0: {"flow": -3.0}, 9: {"flow": 1.5}, 19: {"flow": 0.25}})
    series = _series_by_strategy(store, None)["flow"]
    assert len(series) == 20
    assert math.isclose(sum(value for _bar, value in series), -1.25)
    assert sum(1 for _bar, value in series if value == 0.0) == 17


def test_nothing_is_zero_filled_before_income_rows_existed(tmp_path: Path) -> None:
    """Zero-filling back to the first cycle would assert "no income" over hours nothing was recording."""
    store = _store(tmp_path, cycles=50, income_at={40: {"tsmom": 1.0}, 45: {"tsmom": -1.0}})
    series = _series_by_strategy(store, None)["tsmom"]
    assert series[0][0] == BASE + 40 * HOUR
    assert series[-1][0] == BASE + 45 * HOUR


def test_a_strategy_that_earned_nothing_that_hour_still_has_that_hour(tmp_path: Path) -> None:
    """Two strategies on one grid: they used to have different lengths, and so different `days`."""
    store = _store(
        tmp_path,
        cycles=12,
        income_at={1: {"tsmom": -1.0, "flow": -0.2}, 4: {"tsmom": 2.0}, 9: {"tsmom": 1.0, "flow": 0.5}},
    )
    series = _series_by_strategy(store, None)
    assert len(series["tsmom"]) == len(series["flow"]) == 9
    assert [value for _bar, value in series["flow"]] == [-0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]


def test_the_compression_really_did_inflate_the_annualised_sharpe(tmp_path: Path) -> None:
    """The measurement this fix rests on, as a test: same P&L, two series, sqrt(N/n) apart."""
    income = {index: {"tsmom": (1.0 if index % 6 else -3.0)} for index in range(0, 96, 4)}
    store = _store(tmp_path, cycles=96, income_at=income)
    grid = np.asarray([value for _bar, value in _series_by_strategy(store, None)["tsmom"]], dtype=float)
    rows = grid[grid != 0.0]

    def annualised(values: np.ndarray) -> float:
        return float(values.mean() / values.std(ddof=1) * math.sqrt(8760))

    ratio = annualised(rows) / annualised(grid)
    assert abs(ratio - math.sqrt(grid.size / rows.size)) < 0.30
    assert abs(annualised(rows)) > abs(annualised(grid)), "the deleted zeros were making it look bigger"
    assert np.sign(rows.sum()) == np.sign(grid.sum()), "and never big enough to move the sign - M-G06's bar"
