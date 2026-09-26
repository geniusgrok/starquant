"""One symbol's HTTP 400 on klines used to fail the whole cycle (2026-09-25 system review, A4).

`closed_bars` fetches every symbol through one `asyncio.gather`, and the public client raises on a 4xx
at once.  So a name mainnet stops knowing - delisted or renamed, which klines answers with HTTP 400 and
-1121 - failed every cycle for all seventeen names, and twelve in a row is the breaker stopping the
loop.  The engine already has a path for a symbol with no bars (`model_inputs` drops it, `_hold_dropped`
flattens or holds it and pages); it was only reachable when the venue answered 200 with nothing.

The line drawn is the status: a 400 names the request, while a 429, a 5xx that outlived the retries or
a transport error names the path to the venue, and those still fail the cycle as they did.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from starquant_data.binance_public import AsyncPublicClient
from starquant_data.live_feed import PublicMarketData

HOUR_MS = 3_600_000
NOW_MS = 1_757_000_000_000


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _rows(count: int) -> list[list[object]]:
    first = NOW_MS - (count + 1) * HOUR_MS
    return [
        [first + i * HOUR_MS, "1", "2", "0.5", "1.5", "10", first + (i + 1) * HOUR_MS - 1, "15", 3, "5", "7.5", "0"]
        for i in range(count)
    ]


def _feed(answers: dict[str, httpx.Response]) -> PublicMarketData:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": NOW_MS})
        return answers.get(request.url.params["symbol"], httpx.Response(200, json=_rows(5)))

    client = AsyncPublicClient("https://fapi.binance.com")
    client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(handler))
    return PublicMarketData(client=client)


async def test_a_400_for_one_symbol_is_that_symbol_having_no_bars() -> None:
    feed = _feed({"GONEUSDT": httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})})

    bars = await feed.closed_bars(["BTCUSDT", "GONEUSDT", "ETHUSDT"], "1h", 5)

    assert bars["GONEUSDT"].empty, "handed to the dropped-symbol path, not raised"
    assert len(bars["BTCUSDT"]) == 5 and len(bars["ETHUSDT"]) == 5, "the other names still have their bars"
    await feed.aclose()


@pytest.mark.parametrize("status", [429, 503])
async def test_a_failure_of_the_path_still_fails_the_cycle(status: int) -> None:
    """Treating these as "no bars" would flatten live positions over a rate limit or an outage."""
    feed = _feed({"ETHUSDT": httpx.Response(status, text="busy")})

    with pytest.raises(httpx.HTTPStatusError):
        await feed.closed_bars(["BTCUSDT", "ETHUSDT"], "1h", 5)
    await feed.aclose()
