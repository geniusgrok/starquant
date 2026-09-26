"""M-Q08's judged slippage splits each fill by the books it traded for (operator ruling 2026-09-23, G9).

Until then the judged reading split thirty days of fills by the NEWEST cycle's books.  Once the probe book
went flat every fill read as the main book's: on 2026-09-23 it judged 119 fills, of which 67 were the main
book's alone, 18 overlaid - at +12.10 bps against the main book's +5.17 - and 34 from cycles written
before `books` existed.  The rule now: a fill belongs to the books that carried its symbol in its own
cycle or the one before, the targets it moved between.  A cycle without `books` cannot say, and a name no
book carried on either side cannot either; neither is guessed.

The cycles and fills below are built in the shape the loop writes (`books` maps strategy to book,
`contributions` maps strategy to symbol scores), and every rule is read through the real functions.
"""

from __future__ import annotations

from typing import Any

import pytest

from starquant_live import execution_fidelity as fidelity
from starquant_live.risk_budget import RiskBudgetParams, books_by_bar, fill_grouper, risk_budget_status, slippage_bps

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_788_220_800_000  # 2026-09-01T00:00Z
ONE = RiskBudgetParams(min_slippage_fills=1)
BOTH = {"tsmom": {"AAAUSDT": 1.0, "BBBUSDT": -1.0}, "flow": {"BBBUSDT": -1.0}}
MAIN = {"tsmom": {"AAAUSDT": 1.0, "BBBUSDT": -1.0}, "flow": {}}
CLOSED = {"tsmom": {"AAAUSDT": 1.0, "BBBUSDT": 0.0}, "flow": {}}
PROBE_ALONE = {"tsmom": {"AAAUSDT": 1.0}, "flow": {"CCCUSDT": -1.0}}


def _cycle(bar: int, contributions: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"bar_open_ms": bar, "equity": 1_000.0}
    if contributions is not None:
        row["books"] = {"tsmom": "main", "flow": "flow_short"}
        row["contributions"] = contributions
    return row


def _fill(bar: int, symbol: str, side: str, price: float, quantity: float = 1.0) -> dict[str, Any]:
    return {
        "bar_open_ms": bar,
        "symbol": symbol,
        "side": side,
        "avg_price": price,
        "executed_qty": str(quantity),
        "decision_close": 100.0,
    }


def test_a_fill_is_the_main_books_only_when_the_main_book_alone_carried_it() -> None:
    group = fill_grouper(books_by_bar([_cycle(T0, BOTH), _cycle(T0 + HOUR, PROBE_ALONE)]))

    assert group(T0, "AAAUSDT") == "main_only"
    assert group(T0, "BBBUSDT") == "overlaid"
    assert group(T0 + HOUR, "CCCUSDT") == "other", "a name only the probe carried is not the main book's"


def test_a_close_is_attributed_by_the_cycle_before_it() -> None:
    """The bar that closes a name carries it nowhere; the cycle before names the books that held it."""
    group = fill_grouper(books_by_bar([_cycle(T0, BOTH), _cycle(T0 + HOUR, CLOSED)]))

    assert group(T0 + HOUR, "BBBUSDT") == "overlaid"
    assert group(T0 + HOUR, "ZZZUSDT") == "unattributed", "no book carried it on either side"


def test_a_cycle_without_books_cannot_say_and_is_never_guessed() -> None:
    group = fill_grouper(books_by_bar([_cycle(T0), _cycle(T0 + HOUR, MAIN)]))

    assert group(T0, "AAAUSDT") == "unattributed"
    assert group(T0 + 2 * HOUR, "AAAUSDT") == "unattributed", "a bar with no cycle record at all"


def test_a_later_row_without_books_does_not_erase_the_bar_it_repeats() -> None:
    """A SKIPPED row for a bar that already traded carries no `books`.  Keyed over the traded cycle, it
    turned 18 of 2026-09-23's fills into "cannot say" in a replay fed every row."""
    skipped = {"bar_open_ms": T0, "phase": "SKIPPED"}
    group = fill_grouper(books_by_bar([_cycle(T0, BOTH), skipped]))

    assert group(T0, "AAAUSDT") == "main_only"
    assert group(T0, "BBBUSDT") == "overlaid"


def test_the_paging_line_names_each_population_for_what_it_is() -> None:
    """Four populations, four names.  The line had two until G9 added the other two, and on 2026-09-23 it
    paged 34 fills no record can attribute as 两本书共载."""
    rows = [_cycle(T0), _cycle(T0 + HOUR, BOTH), _cycle(T0 + 2 * HOUR, PROBE_ALONE)]
    trades = [
        _fill(T0, "AAAUSDT", "BUY", 100.05),  # a cycle without books
        _fill(T0 + HOUR, "AAAUSDT", "BUY", 100.10),
        _fill(T0 + HOUR, "BBBUSDT", "SELL", 99.80),
        _fill(T0 + 2 * HOUR, "CCCUSDT", "SELL", 99.70),  # a name only the probe carried
    ]

    (reason,) = [line for line in risk_budget_status(rows, trades, ONE)["reasons"] if line.startswith("滑点")]

    assert reason.endswith(
        "分书读：主书独有 10.0 bps/1 笔；两本书共载 20.0 bps/1 笔；其它书独有 30.0 bps/1 笔；分不出书 5.0 bps/1 笔"
    )


def test_the_budget_status_judges_each_fill_by_its_own_cycle_not_by_the_newest() -> None:
    """The regression: the probe went flat after these fills, and the newest cycle's map called both main."""
    rows = [_cycle(T0, BOTH), _cycle(T0 + DAY, MAIN)]
    trades = [_fill(T0, "AAAUSDT", "BUY", 100.01), _fill(T0, "BBBUSDT", "SELL", 99.79)]

    slippage = risk_budget_status(rows, trades, ONE)["slippage"]

    assert slippage["judged"] == "main_only" and slippage["fills"] == 1
    assert slippage["value"] == pytest.approx(1.0), "the +1 bps main-only fill, without the +21 bps overlaid one"
    assert slippage["by_group"]["overlaid"]["fills"] == 1 and slippage["combined"]["fills"] == 2


def test_unattributed_fills_are_counted_beside_the_main_book_and_not_in_it() -> None:
    rows = [_cycle(T0), _cycle(T0 + HOUR, MAIN)]
    trades = [_fill(T0, "AAAUSDT", "BUY", 100.05), _fill(T0 + HOUR, "AAAUSDT", "BUY", 100.01)]

    judged = slippage_bps(trades, ONE, latest_ms=T0 + HOUR, books_at=books_by_bar(rows))
    blind = slippage_bps(
        trades, RiskBudgetParams(min_slippage_fills=2), latest_ms=T0 + HOUR, books_at=books_by_bar(rows)
    )

    assert judged["judged"] == "main_only" and judged["fills"] == 1 and judged["value"] == pytest.approx(1.0)
    assert judged["by_group"]["unattributed"]["fills"] == 1
    assert not blind["enforced"] and "另有 1 笔分不出书" in blind["why"]


def test_when_nothing_can_be_attributed_the_combined_number_is_still_judged() -> None:
    """The 2026-09-12 rule, kept: a split the record cannot make is not a pass."""
    rows = [_cycle(T0), _cycle(T0 + HOUR)]
    trades = [_fill(T0, "AAAUSDT", "BUY", 100.05), _fill(T0 + HOUR, "BBBUSDT", "BUY", 100.01)]

    judged = slippage_bps(trades, ONE, latest_ms=T0 + HOUR, books_at=books_by_bar(rows))

    assert judged["judged"] == "combined" and judged["fills"] == 2


def test_the_trend_and_the_judged_reading_split_one_population() -> None:
    """Fills across three cycles of one week: the trend's main-only bucket IS the judged one, to the bit."""
    rows = [_cycle(T0, BOTH), _cycle(T0 + HOUR, CLOSED), _cycle(T0 + 2 * HOUR, MAIN)]
    trades = [
        _fill(T0, "AAAUSDT", "BUY", 100.02, quantity=2.0),
        _fill(T0, "BBBUSDT", "SELL", 99.90),
        _fill(T0 + HOUR, "BBBUSDT", "BUY", 100.08, quantity=3.0),  # a close: overlaid by the cycle before
        _fill(T0 + 2 * HOUR, "AAAUSDT", "SELL", 99.97),
    ]

    judged = slippage_bps(trades, ONE, latest_ms=T0 + 2 * HOUR, books_at=books_by_bar(rows))
    (week,) = fidelity.slippage_by_week(rows, trades)

    assert judged["by_group"]["main_only"]["fills"] == 2 and judged["by_group"]["overlaid"]["fills"] == 2
    assert week["main_only"] == judged["by_group"]["main_only"]
    assert week["combined"] == judged["combined"]
