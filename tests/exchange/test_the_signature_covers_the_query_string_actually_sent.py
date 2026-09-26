"""The HMAC is computed over `urlencode(params)`; the request is encoded by httpx.  Pin them together.

`_sign` signs `urlencode(signed, doseq=True)` and then hands the same dict to httpx, which encodes it
again on its own terms for GET and DELETE.  The two agree today only because every parameter this
client sends is a string or an int, and for those two shapes the encoders happen to agree.  Nothing
says so anywhere and nothing checked it, which is an implicit assumption sitting under every signed
request - and when it breaks the venue answers -1022 "Signature for this request is not valid" for a
request that looks perfectly well formed in the log.

So these tests do not re-derive the expectation from `_sign`.  They read the URL (or form body) the
fake transport actually received, strip `&signature=` off the end, and recompute the HMAC over what
is left - which is exactly the arithmetic the venue performs.  The edge of the assumption is pinned
too: see the `bool` case below, which is one keystroke away from `place_order`'s `reduceOnly`.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.guard import WriteGuard
from starquant_shared.types import VenueError

DEMO = "https://demo-fapi.binance.com"
SECRET = "sekrit-Ω"


def _recorder() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), seen


def _verify_as_the_venue_would(request: httpx.Request, *, body: bool = False) -> dict[str, str]:
    """Recompute the HMAC over the bytes that arrived, exactly as Binance does, and return the params.

    Binance signs "the query string as received, minus `&signature=...`".  Splitting on the LAST
    `&signature=` rather than parsing and re-encoding is what makes this a byte-level check: any
    re-encoding here would hide the very mismatch the test exists to catch.
    """
    raw = request.content.decode() if body else request.url.query.decode()
    head, marker, signature = raw.rpartition("&signature=")
    assert marker, f"every signed request carries a signature: {raw!r}"
    expected = hmac.new(SECRET.encode("utf-8"), head.encode("utf-8"), hashlib.sha256).hexdigest()
    assert signature == expected, (
        f"the signature must cover the query string as SENT.  Signed and sent have diverged: sent {head!r}"
    )
    return dict(pair.split("=", 1) for pair in head.split("&") if "=" in pair)


async def test_a_signed_get_is_verifiable_from_the_url_that_was_actually_sent() -> None:
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, transport=transport)

    await client.get("/fapi/v1/income", {"startTime": 1, "endTime": 2, "limit": 1000}, signed=True)

    assert len(seen) == 1
    params = _verify_as_the_venue_would(seen[0])
    assert params["startTime"] == "1" and params["limit"] == "1000"
    assert "recvWindow" in params and "timestamp" in params
    await client.aclose()


async def test_a_signed_delete_is_verifiable_too_because_httpx_encodes_it_the_same_way() -> None:
    """DELETE takes its parameters in the URL like GET does; cancel-order rides this path."""
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, guard=WriteGuard(DEMO), transport=transport)

    await client.delete("/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": "bd-1757-BTCUSDT"})

    params = _verify_as_the_venue_would(seen[0])
    assert params["origClientOrderId"] == "bd-1757-BTCUSDT"
    await client.aclose()


async def test_a_signed_post_is_verified_against_its_form_body_not_its_url() -> None:
    """POST sends `data=`, so httpx form-encodes the body; the same equality has to hold there."""
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, guard=WriteGuard(DEMO), transport=transport)

    await client.post(
        "/fapi/v1/order",
        {
            "symbol": "ETHUSDT",
            "side": "SELL",
            "type": "MARKET",
            "quantity": "0.014",
            "newClientOrderId": "bd-1757000000000-ETHUSDT",
            "newOrderRespType": "RESULT",
            "reduceOnly": "true",
        },
    )

    params = _verify_as_the_venue_would(seen[0], body=True)
    assert params["quantity"] == "0.014" and params["reduceOnly"] == "true"
    assert not seen[0].url.query, "the parameters go in the body, not both places"
    await client.aclose()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        # Everything this client sends today is one of these shapes.  A shape that is NOT one of them
        # is the `bool` case below, which is where the assumption actually breaks.
        ("symbol", "1000PEPEUSDT"),
        ("newClientOrderId", "bd-1757000000000-1000PEPEUSDT"),
        ("quantity", "0.001"),
        ("limit", 1000),
        ("leverage", 3),
    ],
)
async def test_every_parameter_shape_this_client_sends_survives_both_encoders(name: str, value: Any) -> None:
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, transport=transport)

    await client.get("/fapi/v1/probe", {name: value}, signed=True)

    assert _verify_as_the_venue_would(seen[0])[name] == str(value)
    await client.aclose()


async def test_a_bool_parameter_is_the_shape_that_would_break_the_two_encoders_apart() -> None:
    """The assumption itself, written down, with the one value that actually violates it.

    Percent-escaping is a red herring: `urlencode` and httpx's `QueryParams` agree on spaces, `+`,
    `/`, `:`, `@`, `&`, `=`, `#` and non-ASCII alike (checked across all of them, 2026-09-13).  Where
    they part is a Python `bool`: `urlencode` renders it `str(True)` -> "True", httpx renders it
    "true".  So `params["reduceOnly"] = True` - one keystroke from the `"true"` that `place_order`
    writes today, and accepted by `guard.py`, which lowercases before comparing - would be signed as
    `reduceOnly=True` and SENT as `reduceOnly=true`, and the venue would answer -1022 for a request
    that looks perfectly well formed in the log.

    This test asserts the divergence rather than fixing it: the fix is to keep sending strings, and
    the point of writing it down is that the next -1022 is one grep away from its cause.
    """
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, transport=transport)

    await client.get("/fapi/v1/probe", {"reduceOnly": True}, signed=True)

    head, _, _ = seen[0].url.query.decode().rpartition("&signature=")
    assert "reduceOnly=true" in head, f"httpx sent the lowercase form: {head!r}"
    assert urlencode({"reduceOnly": True}) == "reduceOnly=True", "but urlencode - what `_sign` hashes - did not"
    with pytest.raises(AssertionError, match="Signed and sent have diverged"):
        _verify_as_the_venue_would(seen[0])
    await client.aclose()


async def test_the_str_and_int_parameters_this_client_does_send_are_encoded_identically() -> None:
    """The other half of the assumption: for every shape in use today, the two encoders agree.

    Kept next to the failing case so the pair reads as one statement - "this is why it works, and
    this is the exact edge it works up to" - rather than as a lone curiosity about bools.
    """
    params: dict[str, Any] = {
        "symbol": "1000PEPEUSDT",
        "side": "SELL",
        "type": "MARKET",
        "quantity": "0.001",
        "newClientOrderId": "bd-1757000000000-1000PEPEUSDT",
        "reduceOnly": "true",
        "limit": 1000,
        "startTime": 1_757_000_000_000,
        "leverage": 3,
        "recvWindow": 10_000,
    }
    assert urlencode(params, doseq=True) == str(httpx.QueryParams(params))


async def test_an_unsigned_request_carries_no_signature_or_recv_window() -> None:
    """Public endpoints must not leak `recvWindow`/`timestamp`; `/fapi/v1/exchangeInfo` is called hot."""
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, transport=transport)

    await client.get("/fapi/v1/premiumIndex")

    query = seen[0].url.query.decode()
    assert "signature" not in query and "recvWindow" not in query and "timestamp" not in query
    assert seen[0].headers["X-MBX-APIKEY"] == "key", "the key header rides every request regardless"
    await client.aclose()


async def test_a_none_valued_parameter_is_dropped_before_it_is_signed() -> None:
    """`open_orders(None)` and friends pass optional parameters through; `None` must not reach the wire.

    A literal `symbol=None` would be signed, sent, and rejected as an unknown symbol rather than as
    a missing one - a deterministic VenueError whose message names the wrong problem.
    """
    transport, seen = _recorder()
    client = BinanceRestClient(DEMO, "key", SECRET, transport=transport)

    await client.get("/fapi/v1/openOrders", {"symbol": None}, signed=True)

    params = _verify_as_the_venue_would(seen[0])
    assert "symbol" not in params
    await client.aclose()


async def test_the_signature_is_recomputed_on_every_retry_not_reused() -> None:
    """A retried request carries a fresh timestamp, so it must carry a fresh signature.

    Re-sending the first attempt's signature with a new timestamp (or the old timestamp with a new
    clock offset) is the failure mode that turns one -1021 into three, then a dead cycle.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": 9_000_000_000_000})
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(400, json={"code": -1021, "msg": "outside of the recvWindow"})
        return httpx.Response(200, json={"ok": True})

    client = BinanceRestClient(DEMO, "key", SECRET, transport=httpx.MockTransport(handler))
    assert await client.get("/fapi/v2/account", signed=True) == {"ok": True}

    assert len(seen) == 2, "one rejection, one retry"
    first, second = (_verify_as_the_venue_would(request) for request in seen)
    assert first["timestamp"] != second["timestamp"], "the resync moved the clock; the retry is a new request"
    await client.aclose()


async def test_a_signed_request_that_the_venue_rejects_still_signed_what_it_sent() -> None:
    """The byte equality has to hold on the rejection path too - that is where -1022 shows up."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, json={"code": -1022, "msg": "Signature for this request is not valid."})

    client = BinanceRestClient(DEMO, "key", SECRET, transport=httpx.MockTransport(handler))
    with pytest.raises(VenueError) as info:
        await client.get("/fapi/v1/income", {"startTime": 1}, signed=True)

    assert info.value.code == -1022 and not info.value.retryable, "a bad signature is not retryable"
    _verify_as_the_venue_would(seen[0])
    await client.aclose()
