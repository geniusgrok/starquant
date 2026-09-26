"""`used_weight` is now read, edge-triggered, and still does not sleep.

`X-MBX-USED-WEIGHT-1M` was parsed into `self.used_weight` from the first version and nothing ever
looked at it, while `docs/ARCHITECTURE.md` listed "限频" as one of this package's jobs.  A client
walking into the 2,400/minute ceiling therefore looked exactly like an idle one right up to the 429.

What landed instead of a token bucket is a warning, and these tests pin BOTH halves of that choice:
the line appears once per crossing, and the default request path is unchanged - no sleep, no delay,
no extra call.  Active throttling would change what the live loop does mid-run, and the live loop is
running; that is a decision to price on its own, not a side effect of correcting a doc.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import USED_WEIGHT_WARN, BinanceRestClient

DEMO = "https://demo-fapi.binance.com"
CLIENT_LOG = "starquant_exchange.binance_usdm.rest_client"


def _weighing(weights: list[int]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Answers each request with the next weight in the list, repeating the last one forever."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        weight = weights[min(len(seen), len(weights) - 1)]
        seen.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"X-MBX-USED-WEIGHT-1M": str(weight)})

    return httpx.MockTransport(handler), seen


def _weight_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.message for r in caplog.records if r.name == CLIENT_LOG and "request weight" in r.message]


async def test_the_header_is_still_recorded_on_every_response() -> None:
    transport, _ = _weighing([12, 340, 1_205])
    client = BinanceRestClient(DEMO, "k", "s", transport=transport)
    for expected in (12, 340, 1_205):
        await client.get("/fapi/v1/premiumIndex")
        assert client.used_weight == expected
    await client.aclose()


async def test_crossing_the_threshold_warns_exactly_once_not_once_per_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """At the ceiling there are thousands of requests a minute; a line each would bury the loop's log."""
    transport, _ = _weighing([100, USED_WEIGHT_WARN, USED_WEIGHT_WARN + 1, USED_WEIGHT_WARN + 200])
    client = BinanceRestClient(DEMO, "k", "s", transport=transport)

    with caplog.at_level(logging.WARNING, logger=CLIENT_LOG):
        for _ in range(6):
            await client.get("/fapi/v1/premiumIndex")

    assert len(_weight_lines(caplog)) == 1, f"edge-triggered, not level-triggered: {_weight_lines(caplog)}"
    assert str(USED_WEIGHT_WARN) in _weight_lines(caplog)[0]
    await client.aclose()


async def test_dropping_back_under_the_threshold_re_arms_the_warning(caplog: pytest.LogCaptureFixture) -> None:
    """The venue's weight window resets every minute, so a second busy cycle is a second crossing."""
    transport, _ = _weighing([USED_WEIGHT_WARN + 5, 10, USED_WEIGHT_WARN + 5])
    client = BinanceRestClient(DEMO, "k", "s", transport=transport)

    with caplog.at_level(logging.WARNING, logger=CLIENT_LOG):
        for _ in range(3):
            await client.get("/fapi/v1/premiumIndex")

    assert len(_weight_lines(caplog)) == 2, f"two crossings, two lines: {_weight_lines(caplog)}"
    await client.aclose()


async def test_staying_under_the_threshold_says_nothing_at_all(caplog: pytest.LogCaptureFixture) -> None:
    """A normal cycle is ~30 weight against a 2,400 budget; it must be silent."""
    transport, _ = _weighing([5, 40, USED_WEIGHT_WARN - 1])
    client = BinanceRestClient(DEMO, "k", "s", transport=transport)

    with caplog.at_level(logging.WARNING, logger=CLIENT_LOG):
        for _ in range(3):
            await client.get("/fapi/v1/premiumIndex")

    assert _weight_lines(caplog) == []
    await client.aclose()


async def test_a_weight_header_that_is_not_a_number_is_ignored_rather_than_fatal() -> None:
    """A header the venue mangles must not take a cycle down; the last good reading simply stands."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, headers={"X-MBX-USED-WEIGHT-1M": "n/a"})

    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    assert await client.get("/fapi/v1/premiumIndex") == {"ok": True}
    assert client.used_weight == 0
    await client.aclose()


async def test_a_response_with_no_weight_header_leaves_the_last_reading_alone() -> None:
    """`/fapi/v1/time` and the mock venues in this suite send none; that is not a reading of zero."""
    seen = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        headers = {"X-MBX-USED-WEIGHT-1M": "700"} if seen["n"] == 1 else {}
        return httpx.Response(200, json={"ok": True}, headers=headers)

    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    await client.get("/fapi/v1/premiumIndex")
    await client.get("/fapi/v1/premiumIndex")
    assert client.used_weight == 700
    await client.aclose()


async def test_being_over_the_threshold_changes_nothing_about_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half of option (a) that matters for a running loop: observability only, bit-identical path.

    If this ever starts failing because something sleeps, that is a behaviour change to the live loop
    and belongs in its own decision - not in whatever commit made this test go red.
    """
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record)
    transport, seen = _weighing([USED_WEIGHT_WARN + 500])
    client = BinanceRestClient(DEMO, "k", "s", transport=transport)

    for _ in range(4):
        assert await client.get("/fapi/v1/premiumIndex") == {"ok": True}

    assert slept == [], "no throttle: the client is still purely reactive to 429/418"
    assert len(seen) == 4, "one request per call, no probing and no coalescing"
    await client.aclose()
