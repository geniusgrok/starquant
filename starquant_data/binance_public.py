"""Unauthenticated Binance USDⓈ-M public endpoints (mainnet data for research and signals; D-002).

Pure request/response helpers plus thin sync/async clients with retry and
backoff.  No signing, no account access, no writes.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping
from typing import Any, Self

import httpx
import pandas as pd

DEFAULT_BASE_URL = "https://fapi.binance.com"
KLINE_COLUMNS: tuple[str, ...] = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
)
MAX_KLINE_LIMIT = 1500
MAX_FUNDING_LIMIT = 1000
RETRYABLE_STATUS = frozenset({418, 429, 500, 502, 503, 504})


def klines_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    """Convert raw kline rows to a typed frame (ms timestamps; microsecond archives are normalised)."""
    if not rows:
        return pd.DataFrame(columns=list(KLINE_COLUMNS))
    frame = pd.DataFrame([row[:11] for row in rows], columns=list(KLINE_COLUMNS))
    for column in ("open_time", "close_time"):
        values = pd.to_numeric(frame[column], errors="coerce").astype("int64")
        frame[column] = values.where(values < 10**14, values // 1000)
    for column in ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    frame["trades"] = pd.to_numeric(frame["trades"], errors="coerce").fillna(0).astype("int64")
    return frame.dropna(subset=["open", "high", "low", "close"]).sort_values("open_time").reset_index(drop=True)


def drop_unclosed(frame: pd.DataFrame, now_ms: int) -> pd.DataFrame:
    """Keep only bars whose close_time is strictly in the past (the in-progress candle is never a fact)."""
    if frame.empty:
        return frame
    return frame[frame["close_time"] < now_ms].reset_index(drop=True)


def is_invalid_symbol(exc: httpx.HTTPStatusError) -> bool:
    """400 ``-1121``: the venue does not list this symbol.  An absence, not a failure (`starquant_data.spot` note 9)."""
    return exc.response.status_code == 400 and '"code":-1121' in exc.response.text.replace(" ", "")


def funding_to_frame(rows: list[Mapping[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["funding_time", "funding_rate", "mark_price"])
    frame = pd.DataFrame(
        {
            "funding_time": [int(row["fundingTime"]) for row in rows],
            "funding_rate": [float(row["fundingRate"]) for row in rows],
            "mark_price": [float(row.get("markPrice") or 0.0) for row in rows],
        }
    )
    return frame.drop_duplicates("funding_time", keep="last").sort_values("funding_time").reset_index(drop=True)


class PublicClient:
    """Synchronous public REST client with bounded retry/backoff (used by ``starquant data sync``)."""

    # Per class, not per module, because `starquant_data.spot` subclasses this for a venue whose page size
    # is 1000 rather than 1500 - and which returns HTTP 200 with 1000 rows when asked for 1500 instead
    # of erroring.  `klines_range` decides "was that a full page?" by comparing against this number, so
    # a module constant would have made the spot tail stop after one page without a word (DL-D5 note 8).
    _klines_path = "/fapi/v1/klines"
    _page_limit = MAX_KLINE_LIMIT

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 20.0, max_retries: int = 5) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers={"User-Agent": "starquant"})
        self._max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        # `Self`, not `PublicClient`: `starquant_data.spot.SpotClient` subclasses this, and a `with` block
        # that narrowed it back to the base class would hide the spot-only methods from every checker.
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(path, params=dict(params or {}))
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
                time.sleep(delay + random.uniform(0, 0.5))
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else delay
                time.sleep(wait + random.uniform(0, 0.5))
                delay = min(delay * 2, 60.0)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")

    def server_time_ms(self) -> int:
        return int(self.get("/fapi/v1/time")["serverTime"])

    def exchange_info(self) -> dict[str, Any]:
        payload = self.get("/fapi/v1/exchangeInfo")
        assert isinstance(payload, dict)
        return payload

    def ticker_24h(self) -> list[dict[str, Any]]:
        payload = self.get("/fapi/v1/ticker/24hr")
        assert isinstance(payload, list)
        return payload

    def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        page = self._page_limit if limit is None else min(limit, self._page_limit)
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": page}
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        return klines_to_frame(self.get(self._klines_path, params))

    def klines_range(
        self, symbol: str, interval: str, start_ms: int, end_ms: int, pause_seconds: float = 0.1
    ) -> pd.DataFrame:
        """Page through ``[start_ms, end_ms]`` in 1500-bar pages."""
        pages: list[pd.DataFrame] = []
        cursor = int(start_ms)
        while cursor <= end_ms:
            page = self.klines(symbol, interval, start_ms=cursor, end_ms=end_ms)
            if page.empty:
                break
            pages.append(page)
            last_open = int(page["open_time"].iloc[-1])
            if len(page) < self._page_limit or last_open <= cursor:
                break
            cursor = last_open + 1
            if pause_seconds:
                time.sleep(pause_seconds)
        if not pages:
            return pd.DataFrame(columns=list(KLINE_COLUMNS))
        return (
            pd.concat(pages, ignore_index=True)
            .drop_duplicates("open_time", keep="last")
            .sort_values("open_time")
            .reset_index(drop=True)
        )

    def funding_history(
        self, symbol: str, start_ms: int, end_ms: int | None = None, pause_seconds: float = 0.1
    ) -> pd.DataFrame:
        pages: list[pd.DataFrame] = []
        cursor = int(start_ms)
        stop = int(end_ms) if end_ms is not None else None
        while True:
            params: dict[str, Any] = {"symbol": symbol, "startTime": cursor, "limit": MAX_FUNDING_LIMIT}
            if stop is not None:
                params["endTime"] = stop
            rows = self.get("/fapi/v1/fundingRate", params)
            frame = funding_to_frame(rows)
            if frame.empty:
                break
            pages.append(frame)
            last_time = int(frame["funding_time"].iloc[-1])
            if len(frame) < MAX_FUNDING_LIMIT or last_time <= cursor:
                break
            cursor = last_time + 1
            if pause_seconds:
                time.sleep(pause_seconds)
        if not pages:
            return funding_to_frame([])
        return (
            pd.concat(pages, ignore_index=True)
            .drop_duplicates("funding_time", keep="last")
            .sort_values("funding_time")
            .reset_index(drop=True)
        )

    def premium_index(self) -> list[dict[str, Any]]:
        payload = self.get("/fapi/v1/premiumIndex")
        assert isinstance(payload, list)
        return payload


class AsyncPublicClient:
    """Async twin of :class:`PublicClient` for the live loop."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 20.0, max_retries: int = 4) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers={"User-Agent": "starquant"})
        self._max_retries = max_retries

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(path, params=dict(params or {}))
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(delay + random.uniform(0, 0.5))
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep((float(retry_after) if retry_after else delay) + random.uniform(0, 0.5))
                delay = min(delay * 2, 60.0)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")

    async def server_time_ms(self) -> int:
        return int((await self.get("/fapi/v1/time"))["serverTime"])

    async def klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        rows = await self.get(
            "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": min(limit, MAX_KLINE_LIMIT)}
        )
        return klines_to_frame(rows)

    async def premium_index(self) -> list[dict[str, Any]]:
        payload = await self.get("/fapi/v1/premiumIndex")
        assert isinstance(payload, list)
        return payload

    async def funding_rate(self, symbol: str, start_ms: int, limit: int = MAX_FUNDING_LIMIT) -> pd.DataFrame:
        """Settled funding rates since ``start_ms`` (one page; 1000 settlements cover a year of 8h funding)."""
        rows = await self.get(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": int(start_ms), "limit": min(limit, MAX_FUNDING_LIMIT)},
        )
        return funding_to_frame(rows)

    async def ticker_24h(self) -> list[dict[str, Any]]:
        payload = await self.get("/fapi/v1/ticker/24hr")
        assert isinstance(payload, list)
        return payload
