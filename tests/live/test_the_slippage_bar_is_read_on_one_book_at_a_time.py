"""M-Q08's 4 bps bar was being failed by a 1/3-fraction probe book on behalf of the main book.

On 2026-09-12 the daily report alerted `滑点 5.5 bps 高于假设的 4 bps` and had been doing so for two
days.  Split by the book that carries each symbol, the same 34 fills read:

    main-book-only names   19 fills   +0.80 bps   (mean +2.32, se 1.44)
    both books' names      15 fills  +16.18 bps   (mean +14.23, se 4.43, t = 2.31 vs the bar)

The combined 5.47 is a mixture that describes neither population, and its own error bar is 2.59 -
0.57 SE from the bar it is quoted as breaching.  Same defect as M-Q03's late share (restarts mixed
into scheduled cycles) and M-015's compression (two books summed before the spread was taken): an
aggregate over two populations, presented as a reading of one.

**Operator ruling 2026-09-12: M-Q08 judges the main book.**  Its clause is about the execution fidelity
of the book the demo phase is testing, and the probe sleeve already has its own bar for this - `§3
滑点压力 5.5 档` in `validation/book_limits.py`.  The ruling was made with its cost stated: the main
book holds 19 of the 34 fills, so M-Q08 goes from a FAIL it could not support to a BLIND that says how
many fills short it is.  The combined number stays computed and printed either way - the shape of the
2026-09-10 L3 ruling and of M-015's split on the same day.

A record that cannot name the books is judged on the combined reading, not excused: every trade row
written before 2026-09-12 is that case, and an unreadable split is not a pass.

Since the G9 ruling (2026-09-23) the split is per fill, by the books of its own cycle and the one before
(`test_mq08_judges_each_fill_by_the_books_it_traded_for.py`).  Every fill below sits on one bar, so
`BOOKS_AT` gives that bar the map these tests always meant.
"""

from __future__ import annotations

from starquant_live.risk_budget import RiskBudgetParams, books_by_symbol, slippage_bps

HOUR = 3_600_000
NOW = 1_757_000_000_000
BOOKS = {"MAINONLYUSDT": frozenset({"main"}), "OVERLAIDUSDT": frozenset({"main", "flow_short"})}
BOOKS_AT = {NOW - HOUR: BOOKS}  # every `_fill` below trades on this bar


def _fill(symbol: str, *, decision_close: float, avg_price: float, qty: float = 1.0) -> dict:
    return {
        "bar_open_ms": NOW - HOUR,
        "symbol": symbol,
        "avg_price": avg_price,
        "executed_qty": qty,
        "side": "BUY",
        "decision_close": decision_close,
    }


def _params(**kw: object) -> RiskBudgetParams:
    return RiskBudgetParams(min_slippage_fills=1, **kw)  # type: ignore[arg-type]


def test_the_two_populations_are_reported_separately() -> None:
    """One name at 1 bps and one at 21 bps must not both be reported as 11."""
    fills = [
        _fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.01),
        _fill("OVERLAIDUSDT", decision_close=100.0, avg_price=100.21),
    ]
    result = slippage_bps(fills, _params(), latest_ms=NOW, books_at=BOOKS_AT)
    groups = result["by_group"]
    assert abs(groups["main_only"]["value"] - 1.0) < 1e-6
    assert abs(groups["overlaid"]["value"] - 21.0) < 1e-6
    assert groups["main_only"]["fills"] == 1 and groups["overlaid"]["fills"] == 1
    # the bar is taken on the main book: 1 bps, inside 4
    assert result["judged"] == "main_only" and abs(result["value"] - 1.0) < 1e-6
    assert result["inside"] is True
    # and the combined number, which is neither population's, is still computed and still printed
    # (notional-weighted, so it lands a hair above the midpoint - the larger fill is the worse one)
    assert abs(result["combined"]["value"] - 11.0) < 0.05


def test_a_record_that_cannot_name_the_books_reports_one_population_rather_than_guessing() -> None:
    """No `books` in the cycle -> no split.  Absent knowledge is not a reading (the house rule)."""
    fills = [_fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.01)]
    blind = slippage_bps(fills, _params(), latest_ms=NOW, books_at=None)
    assert blind["by_group"] == {} and blind["judged"] == "combined"
    assert books_by_symbol({"contributions": {"tsmom": {"MAINONLYUSDT": 1.0}}}) == {}
    assert books_by_symbol(None) == {}


def test_books_by_symbol_reads_the_cycles_own_books_field() -> None:
    """`contributions` keys by strategy; only `books` says which book that strategy belongs to."""
    carried = books_by_symbol(
        {
            "books": {"tsmom": "main", "flow": "flow_short"},
            "contributions": {
                "tsmom": {"BTCUSDT": 1.0, "ENAUSDT": 1.0},
                "flow": {"ENAUSDT": -0.23, "TUTUSDT": -0.2, "ZEROUSDT": 0.0},
            },
        }
    )
    assert carried["BTCUSDT"] == frozenset({"main"})
    assert carried["ENAUSDT"] == frozenset({"main", "flow_short"})
    assert carried["TUTUSDT"] == frozenset({"flow_short"})
    assert "ZEROUSDT" not in carried  # a zero contribution is not a position in a book


def test_the_breach_carries_the_error_bar_that_decides_whether_it_is_a_reading() -> None:
    """Two fills 20 bps apart cannot tell 5.5 from 4.0, and the instrument must say so.

    `min_slippage_fills` counts fills and has never asked how much they disagree; the 2026-09-12
    reading had 34 of them and a 12.7 bps spread.
    """
    noisy = slippage_bps(
        [
            _fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.16),
            _fill("MAINONLYUSDT", decision_close=100.0, avg_price=99.95),
        ],
        _params(),
        latest_ms=NOW,
        books_at=BOOKS_AT,
    )
    assert noisy["se"] > 2.0
    assert noisy["decisive"] is False  # 5.5 bps with a 10 bps error bar is not a breach measurement

    tight = slippage_bps(
        [_fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.2)] * 4,
        _params(),
        latest_ms=NOW,
        books_at=BOOKS_AT,
    )
    assert tight["se"] == 0.0
    assert tight["decisive"] is True  # 20 bps against a 4 bps bar, with no disagreement at all


def test_the_worst_symbols_are_named_so_a_breach_can_be_chased() -> None:
    """The 2026-09-12 breach was four illiquid alts; a number alone could not have said that."""
    fills = [
        _fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.01),
        _fill("OVERLAIDUSDT", decision_close=100.0, avg_price=100.5),
    ]
    worst = slippage_bps(fills, _params(), latest_ms=NOW, books_at=BOOKS_AT)["worst_symbols"]
    assert worst[0]["symbol"] == "OVERLAIDUSDT"
    assert abs(worst[0]["value"] - 50.0) < 1e-6


def test_the_probes_names_can_no_longer_fail_the_main_books_bar() -> None:
    """The 2026-09-12 shape, scaled down: the main book inside 4, the probe's names four times it."""
    fills = [_fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.008)] * 2
    fills += [_fill("OVERLAIDUSDT", decision_close=100.0, avg_price=100.162)] * 2
    result = slippage_bps(fills, _params(), latest_ms=NOW, books_at=BOOKS_AT)
    assert result["judged"] == "main_only"
    assert result["inside"] is True, "the main book fills at 0.8 bps"
    assert result["combined"]["value"] > result["limit"], "and the book as traded is still over the bar"
    assert result["by_group"]["overlaid"]["value"] > 4.0 * result["limit"]


def test_a_main_book_that_really_is_slow_still_fails() -> None:
    """The falsifier.  Re-pointing the bar must not be a way of never failing it."""
    fills = [_fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.09)] * 2
    result = slippage_bps(fills, _params(), latest_ms=NOW, books_at=BOOKS_AT)
    assert result["judged"] == "main_only" and result["inside"] is False
    assert abs(result["value"] - 9.0) < 1e-6


def test_too_few_main_book_fills_is_blind_and_says_how_many_short() -> None:
    """M-Q08's own "≥ 30 fills" now applies to the book it judges - 19 of 34, on 2026-09-12."""
    fills = [_fill("MAINONLYUSDT", decision_close=100.0, avg_price=100.01)] * 2
    fills += [_fill("OVERLAIDUSDT", decision_close=100.0, avg_price=100.2)] * 40
    result = slippage_bps(fills, RiskBudgetParams(min_slippage_fills=30), latest_ms=NOW, books_at=BOOKS_AT)
    assert result["enforced"] is False and result["value"] is None
    assert result["fills"] == 2 and result["fills_all_books"] == 42
    assert "主书只有 2 笔" in result["why"]
    assert result["by_group"]["overlaid"]["fills"] == 40, "the probe's fills are reported, just not judged"
