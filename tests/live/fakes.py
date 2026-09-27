from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from starquant_alpha.panel import Panel


class FakeClock:
    def __init__(self, now_ms: int) -> None:
        self._now = now_ms
        self.sleeps: list[float] = []

    def now_ms(self) -> int:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += int(seconds * 1000)

    def advance(self, seconds: float) -> None:
        self._now += int(seconds * 1000)


class FakeMarketData:
    """Serves closed bars from a Panel up to a movable cursor (exclusive)."""

    def __init__(
        self,
        panel: Panel,
        cursor: int,
        funding: Mapping[str, float] | None = None,
        funding_history: pd.DataFrame | None = None,
    ) -> None:
        self.panel = panel
        self.cursor = cursor
        self.funding = dict(funding or {})
        self.funding_frame = funding_history  # bars x symbols settled rates (0 off-settlement), like Panel.funding
        self.funding_history_calls: list[tuple[list[str], int]] = []
        self.lag_bars = 0
        self.fail_next = 0
        # D-025's instrumentation runs only when the feed can be asked for its own clock.  This fake
        # could not be, so `_clock_skew` took its all-None branch in every test built on it and the
        # skew/alignment/jump path was reachable through one bespoke subclass.
        #
        # Default None - the probe stays ABSENT - because flipping it would quietly change what two
        # hundred existing tests measure, and one of them says `# no server_time_ms` in its own body.
        # Set it to a number of milliseconds to make the feed's clock that far from the host's; the
        # tests that want the instrumentation ask for it.
        self.server_skew_ms: int | None = None

    def bar_open_ms(self, position: int) -> int:
        return int(pd.Timestamp(self.panel.index[position]).timestamp() * 1000)

    @property
    def server_time_ms(self) -> Callable[[], Any]:
        """Present only when a skew is configured.

        A property that raises `AttributeError` is how a fake says a member is ABSENT: the engine asks
        `getattr(self.market, "server_time_ms", None)` and gets None, which is what a real feed without
        a clock endpoint looks like.  A method that always exists and raises when called would instead
        look like a feed whose clock is broken - a different thing, and one `_clock_skew` swallows.
        """
        if self.server_skew_ms is None:
            raise AttributeError("this feed exposes no clock")
        skew = self.server_skew_ms

        async def probe() -> int:
            return self.bar_open_ms(self.cursor) + skew

        return probe

    async def closed_bars(self, symbols: Sequence[str], interval: str, limit: int) -> dict[str, pd.DataFrame]:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("market data unavailable")
        end = self.cursor - self.lag_bars
        start = max(0, end - limit)
        out: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            if symbol not in self.panel.close.columns:
                continue
            frame = pd.DataFrame(
                {
                    field: getattr(self.panel, field)[symbol].iloc[start:end]
                    for field in ("open", "high", "low", "close", "volume")
                }
            )
            out[symbol] = frame
        return out

    async def funding_rates(self, symbols: Sequence[str]) -> dict[str, float]:
        return {symbol: self.funding.get(symbol, 0.0) for symbol in symbols}

    async def funding_history(self, symbols: Sequence[str], start_ms: int) -> dict[str, pd.Series]:
        """Settled rates since ``start_ms`` (only the non-zero settlements, as the public endpoint returns them)."""
        self.funding_history_calls.append((list(symbols), int(start_ms)))
        out: dict[str, pd.Series] = {}
        for symbol in symbols:
            if self.funding_frame is None or symbol not in self.funding_frame.columns:
                out[symbol] = pd.Series(dtype=float)
                continue
            series = self.funding_frame[symbol]
            stamps = pd.DatetimeIndex(series.index)
            since = stamps >= pd.Timestamp(start_ms, unit="ms", tz="UTC")
            settled = series[since & (series != 0.0)]
            out[symbol] = settled.astype(float)
        return out


# A port nothing listens on.  Set as `market_data.rest_url` so a CLI test cannot reach the public
# internet on ANY machine.  Two tests used to fetch mainnet `exchangeInfo` for real: one asserted an
# exit code and so was red on GitHub's runners (Binance answers them with 451) for five consecutive
# runs while staying green locally, the other only checked for a missing word and so hid a 0.55s
# round trip in every offline run.  With this a network call added to those paths fails everywhere.
UNREACHABLE = "http://127.0.0.1:1"

# One tradable perpetual is all those branches need; `parse_exchange_info` reads exactly these fields.
EXCHANGE_INFO: dict[str, Any] = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "contractType": "PERPETUAL",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }
    ]
}


def paper_venue_from(payload: Mapping[str, Any] | None = None) -> Callable[..., Any]:
    """A drop-in for `live_cmd._paper_venue`: the real `PaperVenue`, with only the fetch replaced."""
    from starquant_live.paper import PaperVenue

    def build(_url: str, balance: float, state_path: Any) -> Any:
        return PaperVenue.from_exchange_info(dict(payload or EXCHANGE_INFO), balance=balance, state_path=state_path)

    return build
