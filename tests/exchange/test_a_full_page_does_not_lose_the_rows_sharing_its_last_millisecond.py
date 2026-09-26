"""`_paged` walks a window without silently dropping rows at a page boundary.

Until 2026-09-13 the walk stepped to `last + 1` after a full page, so every row sharing that page's
final millisecond was skipped, and a full page lying entirely inside one millisecond tripped
`last <= cursor` and truncated the window outright.  Neither wrote a log line.  Income shares a
millisecond as a RULE rather than by accident - one funding settlement writes one row per held
symbol, all with the same `fundingTime` - and these are the rows D-021/D-032 attribute money from.

These tests are the regression.  Every one of them asserts the row ORDER as well as the row set:
`starquant_live.engine` reads the result as a time-ordered series, and a fix that recovered the rows
while shuffling them would be a worse bug than the one it replaced.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.binance_usdm.venue import MAX_PAGES, PAGE_LIMIT, BinanceUsdmVenue

DEMO = "https://demo-fapi.binance.com"
VENUE_LOG = "starquant_exchange.binance_usdm.venue"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Only this module's lines: caplog's handler sits at the root and httpx logs there too."""
    return [record.message for record in caplog.records if record.name == VENUE_LOG]


def _row(tran_id: int, time_ms: int, symbol: str = "BTCUSDT", income: str = "0.01") -> dict[str, Any]:
    return {
        "tranId": tran_id,
        "symbol": symbol,
        "incomeType": "FUNDING_FEE",
        "income": income,
        "asset": "USDT",
        "time": time_ms,
    }


def _venue_over(rows: list[dict[str, Any]], *, path: str = "/fapi/v1/income") -> tuple[BinanceUsdmVenue, list[int]]:
    """A venue whose `path` serves `rows` the way the venue does: `time >= startTime`, capped at `limit`.

    `rows` must already be sorted by time, which is how both paged endpoints answer.  The returned list
    records every `startTime` asked for, because the cursor's movement is half of what is under test -
    a walk that returns the right rows by requesting the whole window twice is not the fix.
    """
    cursors: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path, f"unexpected path {request.url.path}"
        query = parse_qs(request.url.query.decode())
        start = int(query["startTime"][0])
        end = int(query["endTime"][0])
        limit = int(query["limit"][0])
        cursors.append(start)
        window = [row for row in rows if start <= int(row["time"]) <= end]
        return httpx.Response(200, json=window[:limit])

    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    return BinanceUsdmVenue(client), cursors


async def test_a_full_page_ending_mid_millisecond_keeps_the_rest_of_that_millisecond() -> None:
    """The exact shape the old walk lost: 1,000 rows ending at T, with more rows still at T.

    A funding settlement over a book this size cannot reach 1,000 rows in an hour, which is why this
    was never observed - but D-030's first catch-up window and a post-restart window are not an hour.
    """
    # 999 rows on distinct milliseconds, then 12 rows all stamped 5_000 - so page one ends inside the
    # group of twelve and page two has to pick the remaining eleven up.
    rows = [_row(i, 1_000 + i) for i in range(PAGE_LIMIT - 1)]
    rows += [_row(10_000 + j, 5_000, symbol=f"SYM{j}USDT") for j in range(12)]
    venue, cursors = _venue_over(rows)

    got = await venue.income(0, 9_999)

    assert [row["tranId"] for row in got] == [row["tranId"] for row in rows], (
        "every row of the window, once each, in the venue's own order"
    )
    assert cursors == [0, 5_000], "the second page restarts ON the boundary millisecond, not past it"
    await venue.aclose()


async def test_the_rows_recovered_across_the_boundary_stay_in_their_original_order() -> None:
    """The eleven rows page one could not fit belong immediately after the one it did fit.

    Stated separately from the set test because `engine.py` reads this list as a time series: a row
    that arrives out of order lands in the wrong bar's attribution, which is the M-010 misalignment
    D-030 was written to stop.
    """
    rows = [_row(i, 1_000 + i) for i in range(PAGE_LIMIT - 1)] + [_row(10_000 + j, 5_000) for j in range(12)]
    venue, _ = _venue_over(rows)

    got = await venue.income(0, 9_999)

    times = [int(row["time"]) for row in got]
    assert times == sorted(times), "non-decreasing, as the caller assumes"
    tail = [row["tranId"] for row in got[PAGE_LIMIT - 1 :]]
    assert tail == [10_000 + j for j in range(12)], f"the boundary group is contiguous and in order: {tail}"
    await venue.aclose()


async def test_a_full_page_entirely_inside_one_millisecond_stops_loudly_instead_of_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """More than a page of rows on one timestamp cannot be walked past, so say so rather than truncate.

    /fapi/v1/income has no `fromId`; restarting at the same millisecond returns the same page forever.
    The old code broke here too - `last <= cursor` - but returned as if the window had ended.  The rows
    it did see are still returned: this is a monitoring gap, not a reason to lose what was read.
    """
    rows = [_row(i, 7_000) for i in range(PAGE_LIMIT + 40)]
    venue, cursors = _venue_over(rows)

    with caplog.at_level(logging.WARNING, logger=VENUE_LOG):
        got = await venue.income(0, 9_999)

    assert [row["tranId"] for row in got] == list(range(PAGE_LIMIT)), "what was readable is kept"
    assert cursors == [0, 7_000], "one retry at the boundary, then it gives up instead of spinning"
    assert any("may be incomplete" in line for line in _warnings(caplog)), (
        f"a truncated window must be logged; got {_warnings(caplog)}"
    )
    await venue.aclose()


async def test_an_ordinary_multi_page_window_is_walked_to_the_end_without_duplicates() -> None:
    """Two full pages and a short one, all on distinct milliseconds - the case that already worked."""
    rows = [_row(i, 1_000 + i) for i in range(2 * PAGE_LIMIT + 17)]
    venue, cursors = _venue_over(rows)

    got = await venue.income(0, 999_999)

    assert [row["tranId"] for row in got] == list(range(2 * PAGE_LIMIT + 17))
    assert len(cursors) == 3, f"three requests, not one per row: {cursors}"
    # Rows are stamped 1_000..3_016.  The overlap re-reads exactly one row per boundary and drops it,
    # which is the whole cost of the fix: page two therefore ends one row earlier than page one did.
    assert cursors == [0, 1_999, 2_998]
    await venue.aclose()


async def test_an_empty_window_is_one_request_and_an_empty_list(caplog: pytest.LogCaptureFixture) -> None:
    """Nothing happened in the window is a normal answer and must not be logged as a gap."""
    venue, cursors = _venue_over([])

    with caplog.at_level(logging.WARNING, logger=VENUE_LOG):
        got = await venue.income(5_000, 6_000)

    assert got == [] and cursors == [5_000]
    assert not _warnings(caplog), f"an empty window is not incomplete: {_warnings(caplog)}"
    await venue.aclose()


async def test_a_short_first_page_stops_without_a_second_request(caplog: pytest.LogCaptureFixture) -> None:
    """A page under the limit IS the end of the window; asking again would only cost weight."""
    rows = [_row(i, 1_000 + i) for i in range(3)]
    venue, cursors = _venue_over(rows)

    with caplog.at_level(logging.WARNING, logger=VENUE_LOG):
        got = await venue.income(0, 9_999)

    assert [row["tranId"] for row in got] == [0, 1, 2] and cursors == [0]
    assert not _warnings(caplog)
    await venue.aclose()


async def test_user_trades_dedupes_on_its_own_id_field_not_income_s() -> None:
    """The two paged endpoints spell the row id differently: income `tranId`, userTrades `id`.

    A shared key would make one of them de-duplicate on a field that is absent, which - with the
    overlapping cursor - returns the boundary row twice and double-counts a fill.
    """
    trades = [{"id": i, "orderId": 900 + i, "symbol": "ETHUSDT", "qty": "1", "time": 1_000 + i} for i in range(999)]
    trades += [{"id": 5_000 + j, "orderId": 990, "symbol": "ETHUSDT", "qty": "1", "time": 4_000} for j in range(4)]
    venue, cursors = _venue_over(trades, path="/fapi/v1/userTrades")

    got = await venue.user_trades(0, 9_999)

    assert [row["id"] for row in got] == [row["id"] for row in trades], "each fill once, in order"
    assert cursors == [0, 4_000]
    await venue.aclose()


async def test_an_endpoint_with_no_known_id_field_keeps_the_old_conservative_step() -> None:
    """Overlapping without a de-duplication key would double-count, which for money is worse than short.

    `_paged` is reachable only from `income` and `user_trades` today, both of which carry an id.  This
    pins the fallback so a third caller added later fails safe rather than inventing duplicates.
    """
    rows = [{"time": 1_000 + i, "value": i} for i in range(PAGE_LIMIT)] + [{"time": 9_000, "value": -1}]
    venue, cursors = _venue_over(rows, path="/fapi/v1/someOtherWindow")

    got = await venue._paged("/fapi/v1/someOtherWindow", 0, 99_999)

    assert cursors == [0, 1_000 + PAGE_LIMIT], "exclusive step: startTime is last + 1"
    # Each value exactly once: without a key there is no dedupe, so an overlap would show up here.
    assert [row["value"] for row in got] == [*range(PAGE_LIMIT), -1]
    await venue.aclose()


async def test_the_walk_is_bounded_even_if_the_venue_never_runs_out_of_pages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A venue answering full pages forever must cost a bounded number of requests, and say it stopped."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(parse_qs(request.url.query.decode())["startTime"][0])
        calls["n"] += 1
        # Always a full page, always advancing, so nothing but MAX_PAGES can end this.
        return httpx.Response(200, json=[_row(calls["n"] * PAGE_LIMIT + i, start + i) for i in range(PAGE_LIMIT)])

    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    venue = BinanceUsdmVenue(client)

    with caplog.at_level(logging.WARNING, logger=VENUE_LOG):
        got = await venue.income(0, 10**15)

    assert calls["n"] == MAX_PAGES, f"bounded at MAX_PAGES, took {calls['n']}"
    assert len(got) == MAX_PAGES * PAGE_LIMIT
    assert any("may be incomplete" in line for line in _warnings(caplog))
    await venue.aclose()
