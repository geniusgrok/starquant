from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
from starquant_exchange.guard import GuardError, WriteGuard, normalize_host
from starquant_exchange.rules import quantize_qty
from starquant_shared.types import InstrumentRules, OrderOutcomeUnknown, OrderRequest, Side, VenueError

DEMO = "https://demo-fapi.binance.com"


def test_guard_rejects_mainnet_and_odd_urls() -> None:
    assert normalize_host(DEMO) == "demo-fapi.binance.com"
    for bad in (
        "https://fapi.binance.com",
        "http://demo-fapi.binance.com",
        "https://demo-fapi.binance.com/path",
        "https://user:pw@demo-fapi.binance.com",
    ):
        with pytest.raises(GuardError):
            normalize_host(bad)


def test_kill_switch_blocks_only_risk_increasing_writes(tmp_path: Path) -> None:
    switch = tmp_path / "KILL_SWITCH"
    guard = WriteGuard(DEMO, switch)
    guard.authorize("POST", "/fapi/v1/order", {"reduceOnly": "false"})
    switch.write_text("x")
    with pytest.raises(GuardError):
        guard.authorize("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})
    guard.authorize("POST", "/fapi/v1/order", {"symbol": "BTCUSDT", "reduceOnly": "true"})
    guard.authorize("DELETE", "/fapi/v1/order", {"symbol": "BTCUSDT"})
    guard.authorize("POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 2})
    guard.authorize("GET", "/fapi/v2/account", {})


def test_quantize_qty() -> None:
    rules = InstrumentRules("BTCUSDT", Decimal("0.10"), Decimal("0.001"), Decimal("0.001"), Decimal("100"))
    assert quantize_qty(0.00123, rules) == Decimal("0.001")
    assert quantize_qty(0.0004, rules) == Decimal("0")
    sol = InstrumentRules("SOLUSDT", Decimal("0.01"), Decimal("1"), Decimal("1"), Decimal("5"))
    assert quantize_qty(12.9, sol) == Decimal("12")


def _signed_ok(secret: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        query = parse_qs(request.url.query.decode()) if request.method == "GET" else parse_qs(request.content.decode())
        payload = {k: v[0] for k, v in query.items()}
        signature = payload.pop("signature")
        expected = hmac.new(secret.encode(), httpx.QueryParams(payload).__str__().encode(), hashlib.sha256).hexdigest()
        assert signature == expected, "signature must cover the sorted-as-sent query"
        assert request.headers["X-MBX-APIKEY"] == "key"
        if request.url.path == "/fapi/v1/order":
            return httpx.Response(
                200,
                json={
                    "symbol": payload["symbol"],
                    "clientOrderId": payload["newClientOrderId"],
                    "orderId": 42,
                    "side": payload["side"],
                    "status": "FILLED",
                    "executedQty": payload["quantity"],
                    "avgPrice": "60000.5",
                    "reduceOnly": payload.get("reduceOnly") == "true",
                },
            )
        return httpx.Response(
            200,
            json={
                "totalWalletBalance": "10000",
                "availableBalance": "9000",
                "totalMarginBalance": "10100",
                "canTrade": True,
                "positions": [
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.002",
                        "entryPrice": "59000",
                        "markPrice": "60000",
                        "unRealizedProfit": "2",
                        "leverage": "2",
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


async def test_signed_requests_and_venue_parsing() -> None:
    client = BinanceRestClient(DEMO, "key", "secret", guard=WriteGuard(DEMO), transport=_signed_ok("secret"))
    venue = BinanceUsdmVenue(client)
    account = await venue.account()
    assert account.equity == 10100.0 and account.positions["BTCUSDT"].qty == 0.002
    ack = await venue.place_order(OrderRequest("BTCUSDT", Side.BUY, Decimal("0.002"), "bd-test-1"))
    assert ack.status == "FILLED" and ack.executed_qty == Decimal("0.002") and ack.avg_price == 60000.5
    await client.aclose()


async def test_write_timeout_after_send_is_unknown_and_reads_retry() -> None:
    calls = {"time": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/order":
            raise httpx.ReadTimeout("slow", request=request)
        calls["time"] += 1
        if calls["time"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"serverTime": 1})

    client = BinanceRestClient(
        DEMO, "k", "s", guard=WriteGuard(DEMO), transport=httpx.MockTransport(handler), max_retries=2
    )
    with pytest.raises(OrderOutcomeUnknown) as info:
        await client.post(
            "/fapi/v1/order",
            {"symbol": "BTCUSDT", "newClientOrderId": "bd-x", "side": "BUY", "type": "MARKET", "quantity": "0.001"},
        )
    assert info.value.client_order_id == "bd-x"
    assert (await client.get("/fapi/v1/time"))["serverTime"] == 1  # connect error retried
    await client.aclose()


async def test_clock_skew_triggers_resync_and_retry() -> None:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": 5_000_000_000_000})
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(
                400, json={"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."}
            )
        return httpx.Response(200, json={"ok": True})

    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    assert (await client.get("/fapi/v2/account", signed=True)) == {"ok": True}
    assert client.clock_offset_ms > 0
    await client.aclose()


async def test_deterministic_rejection_raises_venue_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -4164, "msg": "Order's notional must be no smaller than 5"})

    client = BinanceRestClient(DEMO, "k", "s", guard=WriteGuard(DEMO), transport=httpx.MockTransport(handler))
    with pytest.raises(VenueError) as info:
        await client.post("/fapi/v1/order", {"symbol": "X", "side": "BUY", "type": "MARKET", "quantity": "1"})
    assert info.value.code == -4164 and not info.value.retryable
    await client.aclose()


def test_order_request_validation() -> None:
    with pytest.raises(ValueError):
        OrderRequest("BTCUSDT", Side.BUY, Decimal("0"), "x")
    with pytest.raises(ValueError):
        OrderRequest("BTCUSDT", Side.BUY, Decimal("1"), "x" * 37)
    assert json.dumps({"ok": True})


async def test_rate_limit_honours_retry_after_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-L03: a 429 with Retry-After must be waited out and retried, not raised at the caller."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7"},
                json={"code": -1003, "msg": "Too many requests; current limit is 2400 request weight per 1 MINUTE."},
            )
        return httpx.Response(200, json={"ok": True})

    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", record)
    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler))
    assert (await client.get("/fapi/v1/klines")) == {"ok": True}
    assert state["calls"] == 2, "the request is retried once"
    assert slept and slept[0] >= 7.0, f"Retry-After must dominate the backoff, slept {slept}"
    await client.aclose()


async def test_rate_limit_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venue that stays rate limited surfaces a retryable VenueError instead of hanging."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"code": -1003, "msg": "Too many requests"})

    slept: list[float] = []

    async def instant(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", instant)
    client = BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(VenueError) as info:
        await client.get("/fapi/v1/klines")
    # the venue's own error is surfaced rather than a wrapper, and it stays marked retryable so the
    # cycle is skipped and retried instead of killing the loop
    assert info.value.retryable and info.value.code == -1003 and "Too many requests" in str(info.value)
    assert len(slept) == 2, f"one sleep per retry, not per attempt: {slept}"
    await client.aclose()


def test_account_rows_and_position_rows_are_both_parsed_faithfully() -> None:
    """demo-fapi's two position payloads disagree; neither may be turned into a silently wrong number."""
    from starquant_exchange.binance_usdm.venue import parse_position

    # /fapi/v2/account: carries notional, no markPrice, lowercase unrealizedProfit, leverage "0"
    account_row = {
        "symbol": "ZECUSDT",
        "positionAmt": "0.169",
        "entryPrice": "872.08",
        "notional": "161.36289000",
        "unrealizedProfit": "13.98137000",
        "leverage": "0",
        "initialMargin": "92233720368.54775807",
    }
    parsed = parse_position(account_row)
    assert parsed is not None
    assert parsed.notional == pytest.approx(161.36289), "the venue's own notional, not qty x a missing mark"
    assert parsed.mark_price == 0.0, "no mark price was supplied and none is invented"
    assert parsed.unrealized_pnl == pytest.approx(13.98137), "the account spelling is accepted too"

    # /fapi/v2/positionRisk: carries markPrice and the other spelling, but no notional
    risk_row = {
        "symbol": "ZECUSDT",
        "positionAmt": "0.169",
        "entryPrice": "872.08",
        "markPrice": "954.81",
        "unRealizedProfit": "13.98137000",
        "leverage": "0",
    }
    from_risk = parse_position(risk_row)
    assert from_risk is not None
    assert from_risk.notional == pytest.approx(0.169 * 954.81), "falls back to qty x mark when told nothing else"
    assert from_risk.unrealized_pnl == pytest.approx(13.98137)

    assert parse_position({"symbol": "X", "positionAmt": "0"}) is None
    # a short keeps its sign in both directions
    short = parse_position({**account_row, "positionAmt": "-0.169", "notional": "-161.36289000"})
    assert short is not None and short.notional < 0
