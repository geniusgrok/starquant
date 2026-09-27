"""The four ambiguity branches: not sent (retry), maybe sent (unknown), 5xx (unknown), backend timeout (unknown).

A write whose response never arrived is NOT a write that did not happen.  Re-submitting it is how a
loop doubles a position, and the whole `bd-<bar_open_ms>-<symbol>` idempotency scheme (D-003) exists
so the caller can ask the venue what happened instead.  The client's job is to tell the two apart:

* `ConnectError` / `ConnectTimeout` / `ProxyError` / `PoolTimeout` - the connection to the venue was
  never established, so nothing left the process.  Retryable for reads and writes alike.
* any other `TransportError` (`ReadTimeout`, `WriteError`, `RemoteProtocolError`, ...) - the request
  was on the wire.  For a mutating method this raises `OrderOutcomeUnknown` immediately; for a read
  it is just another retry.
* HTTP 5xx - the venue answered, but the answer says nothing about the order.  Same rule.
* HTTP 408 / code -1007 - the venue's own "timed out waiting for the backend, execution status
  unknown".  Same rule; it sat in the retryable codes until 2026-09-25, so a write was re-sent.

There was one file of exchange tests against 611 lines of package and this whole table sat under a
single case of it, which is what these fill in.  DELETE is covered alongside POST because it is
mutating too, and cancelling twice is not free either - the second cancel can race a fill.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import TRANSPORT_FAILURE_WARN, BinanceRestClient
from starquant_exchange.guard import WriteGuard
from starquant_shared.types import OrderOutcomeUnknown, VenueError

DEMO = "https://demo-fapi.binance.com"
CLIENT_LOG = "starquant_exchange.binance_usdm.rest_client"
ORDER = {"symbol": "BTCUSDT", "newClientOrderId": "bd-1757000000000-BTCUSDT", "side": "BUY", "quantity": "0.001"}


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Backoff is arithmetic, not a wait, for every test here."""
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record)
    return slept


def _client(handler: object, **kwargs: object) -> BinanceRestClient:
    return BinanceRestClient(DEMO, "k", "s", guard=WriteGuard(DEMO), transport=httpx.MockTransport(handler), **kwargs)


async def test_a_connect_timeout_never_reached_the_venue_so_the_write_is_retried() -> None:
    """`ConnectTimeout` means the TCP connection was not established: nothing was sent, retry is safe.

    The distinction is the whole point - lumping it in with the other transport errors would turn
    every unreachable-proxy blip into an `OrderOutcomeUnknown`, and the caller's response to that is
    a reconciliation query per order.  (The path to the venue runs through a local proxy that 503s
    intermittently, so this is the common case, not the exotic one.)
    """
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectTimeout("proxy did not answer", request=request)
        return httpx.Response(200, json={"orderId": 7, "symbol": "BTCUSDT", "status": "NEW"})

    client = _client(handler, max_retries=3)
    assert (await client.post("/fapi/v1/order", ORDER))["orderId"] == 7
    assert attempts["n"] == 3, "two failures, then the third attempt got through"
    await client.aclose()


async def test_a_connect_error_that_never_clears_ends_as_a_retryable_venue_error_not_an_unknown() -> None:
    """Exhausting the retries on a never-sent write is a failure, not an ambiguity.

    `OrderOutcomeUnknown` costs the caller a reconciliation round trip and, in D-003's loop, a skipped
    bar.  Raising it for a request that provably never left the process would spend that for nothing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = _client(handler, max_retries=2)
    with pytest.raises(VenueError) as info:
        await client.post("/fapi/v1/order", ORDER)
    assert not isinstance(info.value, OrderOutcomeUnknown)
    assert info.value.retryable, "the cycle is skipped and retried, not killed"
    await client.aclose()


@pytest.mark.parametrize(
    "error",
    [httpx.ProxyError("503 Service Unavailable"), httpx.PoolTimeout("no free connection")],
    ids=["proxy_refused_the_connect", "pool_timeout"],
)
async def test_a_proxy_that_refused_the_tunnel_never_reached_the_venue_either(error: httpx.TransportError) -> None:
    """The local proxy's 503 arrives as `ProxyError`, which is not a `ConnectError`.

    It is the commonest failure on the Mac - five of the seven ERROR cycles in the 14 days to
    2026-09-25 - and on an order it fell into the "may have been sent" branch: an order that never
    left the machine would come back `UNKNOWN` after five reconciliation queries, unsent for the bar.
    """
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise type(error)(str(error), request=request)
        return httpx.Response(200, json={"orderId": 7, "symbol": "BTCUSDT", "status": "NEW"})

    client = _client(handler)
    assert (await client.post("/fapi/v1/order", ORDER))["orderId"] == 7
    assert attempts["n"] == 2, "refused once, sent once"
    await client.aclose()


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (408, {"code": -1007, "msg": "Timeout waiting for response from backend server."}),
        (408, None),
        (400, {"code": -1007, "msg": "Timeout waiting for response from backend server."}),
    ],
    ids=["408_with_code", "bare_408", "code_without_408"],
)
async def test_a_backend_timeout_on_a_write_is_unknown_and_is_sent_once(
    status: int, body: dict[str, object] | None
) -> None:
    """-1007 was in the retryable codes, so the client signed the order again and re-sent it.

    The first may already have filled, and the same `newClientOrderId` does not stop the second: the id
    only has to be unique among open orders.  Reproduced on a mock transport before the fix: two POSTs
    and a FILLED report for one bar's one order.  A bare 408 was worse in the other direction - a
    non-retryable rejection, so the caller recorded REJECTED for an order that may have filled.
    """
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status, text="timeout")

    client = _client(handler)
    with pytest.raises(OrderOutcomeUnknown) as info:
        await client.post("/fapi/v1/order", ORDER)
    assert attempts["n"] == 1, "never re-sent"
    assert info.value.client_order_id == "bd-1757000000000-BTCUSDT" and info.value.symbol == "BTCUSDT"
    await client.aclose()


async def test_the_same_backend_timeout_on_a_read_is_asked_again() -> None:
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(408, json={"code": -1007, "msg": "Timeout waiting for response from backend server."})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert await client.get("/fapi/v2/account", signed=True) == {"ok": True}
    assert attempts["n"] == 2
    await client.aclose()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("no response"),
        httpx.WriteError("broken pipe"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.ReadError("connection reset"),
    ],
    ids=["read_timeout", "write_error", "remote_protocol", "read_error"],
)
async def test_any_other_transport_error_on_a_write_is_unknown_and_carries_the_client_order_id(
    error: httpx.TransportError,
) -> None:
    """These all mean "it may be at the venue".  The client id is what lets the caller go and look."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise type(error)(str(error), request=request)

    client = _client(handler)
    with pytest.raises(OrderOutcomeUnknown) as info:
        await client.post("/fapi/v1/order", ORDER)
    assert info.value.client_order_id == "bd-1757000000000-BTCUSDT"
    assert info.value.symbol == "BTCUSDT"
    await client.aclose()


async def test_the_same_transport_error_on_a_read_is_only_a_retry() -> None:
    """A GET has no side effect to be ambiguous about; raising `OrderOutcomeUnknown` here would be noise."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"serverTime": 1_757_000_000_000})

    client = _client(handler)
    assert (await client.get("/fapi/v1/time"))["serverTime"] == 1_757_000_000_000
    assert attempts["n"] == 2
    await client.aclose()


async def test_a_cancel_is_mutating_too_and_reports_the_id_it_was_cancelling() -> None:
    """DELETE takes `origClientOrderId`, not `newClientOrderId`; the unknown must name the right one."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no response", request=request)

    client = _client(handler)
    with pytest.raises(OrderOutcomeUnknown) as info:
        await client.delete("/fapi/v1/order", {"symbol": "SOLUSDT", "origClientOrderId": "bd-9-SOLUSDT"})
    assert info.value.client_order_id == "bd-9-SOLUSDT" and info.value.symbol == "SOLUSDT"
    await client.aclose()


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_a_5xx_on_a_write_is_unknown_even_though_those_statuses_are_retryable_for_reads(
    status: int,
) -> None:
    """The venue answered, but its answer says nothing about the order.  Retrying is re-submitting."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="<html>bad gateway</html>")

    client = _client(handler)
    with pytest.raises(OrderOutcomeUnknown) as info:
        await client.post("/fapi/v1/order", ORDER)
    assert str(status) in str(info.value)
    await client.aclose()


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_the_same_5xx_on_a_read_is_backed_off_and_retried(status: int, _no_real_sleeping: list[float]) -> None:
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(status, text="bad gateway")
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert await client.get("/fapi/v2/account", signed=True) == {"ok": True}
    assert attempts["n"] == 2 and _no_real_sleeping, "it waited before the retry"
    await client.aclose()


async def test_a_418_is_a_ban_not_a_write_ambiguity() -> None:
    """418 means the IP is banned for ignoring 429s.  Nothing reached the matching engine, so a write
    that gets one is a plain retryable failure - promoting it to `OrderOutcomeUnknown` would send the
    caller reconciling against an endpoint that is equally banned."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, headers={"Retry-After": "120"}, json={"code": -1003, "msg": "banned until ..."})

    client = _client(handler, max_retries=1)
    with pytest.raises(VenueError) as info:
        await client.post("/fapi/v1/order", ORDER)
    assert not isinstance(info.value, OrderOutcomeUnknown) and info.value.retryable
    await client.aclose()


async def test_consecutive_transport_failures_are_counted_and_announced_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The counter existed from the first version and nothing read it (fixed 2026-09-13).

    Edge-triggered at the threshold, so an outage that lasts an hour writes one line rather than one
    per attempt, and the success path re-arms it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("proxy gone", request=request)

    client = _client(handler, max_retries=TRANSPORT_FAILURE_WARN + 2)
    with caplog.at_level(logging.WARNING, logger=CLIENT_LOG), pytest.raises(VenueError):
        await client.get("/fapi/v1/time")

    assert client.consecutive_transport_failures == TRANSPORT_FAILURE_WARN + 3
    lines = [r.message for r in caplog.records if r.name == CLIENT_LOG and "consecutive transport" in r.message]
    assert len(lines) == 1, f"one line per run of failures, not one per attempt: {lines}"
    await client.aclose()


async def test_a_success_resets_the_failure_counter_so_the_next_outage_is_announced_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = {"fail": True, "n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["fail"]:
            raise httpx.ConnectError("proxy gone", request=request)
        return httpx.Response(200, json={"serverTime": 1})

    client = _client(handler, max_retries=TRANSPORT_FAILURE_WARN)
    with caplog.at_level(logging.WARNING, logger=CLIENT_LOG):
        with pytest.raises(VenueError):
            await client.get("/fapi/v1/time")
        state["fail"] = False
        await client.get("/fapi/v1/time")
        assert client.consecutive_transport_failures == 0, "a success clears it"
        state["fail"] = True
        with pytest.raises(VenueError):
            await client.get("/fapi/v1/time")

    lines = [r.message for r in caplog.records if r.name == CLIENT_LOG and "consecutive transport" in r.message]
    assert len(lines) == 2, f"two outages, two lines: {lines}"
    await client.aclose()
