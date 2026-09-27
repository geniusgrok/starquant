"""``starquant data sync``: official monthly archives + REST tail for klines, REST for funding, into the parquet store."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from starquant_data.archive import FUTURES_MARKET, ArchiveClient, Month, month_range
from starquant_data.binance_public import PublicClient, drop_unclosed
from starquant_data.spot import SymbolNotListed
from starquant_data.store import FundingStore, KlineStore

Progress = Callable[[str], None]


@dataclass
class SyncReport:
    symbol: str
    interval: str
    archive_months: int = 0
    rest_rows: int = 0
    total_rows: int = 0
    funding_rows: int = 0
    # Absence, kept apart from failure.  A spot symbol the venue does not list answers 400 -1121, which
    # is a fact about the board rather than a broken download; folding it into `errors` would make a
    # third of the perpetual universe (166 of 528) report as errors every night, and an error list
    # nobody can read is an error list nobody reads.
    not_listed: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "archive_months": self.archive_months,
            "rest_rows": self.rest_rows,
            "total_rows": self.total_rows,
            "funding_rows": self.funding_rows,
            "not_listed": self.not_listed,
            "errors": list(self.errors),
        }


def sync_klines(
    symbol: str,
    interval: str,
    *,
    history_start: Month,
    store: KlineStore,
    archive: ArchiveClient,
    public: PublicClient,
    now_ms: int,
    progress: Progress | None = None,
    market: str = FUTURES_MARKET,
) -> SyncReport:
    """Monthly archive then REST tail, for whichever market ``market`` and ``public`` name (DL-D5).

    One function for both markets on purpose.  Spot and perpetual bars are compared bar-for-bar by
    every basis signal, so the two series have to be built by the same watermark, the same dedupe and
    the same "drop the unclosed bar" rule; a second copy of this loop would let them diverge in exactly
    the way that produces a basis series with a hole in one leg and not the other.  ``public`` carries
    the venue difference that does exist - the spot page limit is 1000, and asking for 1500 returns 200
    with 1000 rows rather than an error.
    """
    report = SyncReport(symbol=symbol, interval=interval)
    last = store.last_open_time(symbol, interval)
    first_month = history_start if last is None else Month.of_ms(last)
    current_month = Month.of_ms(now_ms)
    for month in month_range(first_month, current_month):
        if last is not None and last >= month.end_ms() - 1:
            continue  # already complete
        try:
            frame = archive.fetch_month(symbol, interval, month, market)
        except Exception as exc:
            report.errors.append(f"archive {month}: {type(exc).__name__}: {exc}")
            break
        if frame is None:
            continue  # symbol did not exist yet that month
        store.append(symbol, interval, frame)
        report.archive_months += 1
        last = store.last_open_time(symbol, interval)
        if progress:
            progress(f"{symbol} {interval}: archive {month} ({len(frame)} rows)")
    tail_start = (store.last_open_time(symbol, interval) or history_start.start_ms()) + 1
    try:
        tail = drop_unclosed(public.klines_range(symbol, interval, tail_start, now_ms), now_ms)
    except SymbolNotListed:
        report.not_listed = True
        tail = pd.DataFrame()
    except Exception as exc:
        report.errors.append(f"rest tail: {type(exc).__name__}: {exc}")
        tail = pd.DataFrame()
    if not tail.empty:
        store.append(symbol, interval, tail)
        report.rest_rows = len(tail)
        if progress:
            progress(f"{symbol} {interval}: rest tail {len(tail)} rows")
    report.total_rows = store.count(symbol, interval)
    return report


def sync_funding(
    symbol: str,
    *,
    history_start: Month,
    store: FundingStore,
    public: PublicClient,
    now_ms: int,
    report: SyncReport,
) -> SyncReport:
    last = store.last_time(symbol)
    start = history_start.start_ms() if last is None else last + 1
    try:
        frame = public.funding_history(symbol, start, now_ms)
    except Exception as exc:
        report.errors.append(f"funding: {type(exc).__name__}: {exc}")
        return report
    if not frame.empty:
        store.append(symbol, frame)
    report.funding_rows = len(store.load(symbol))
    return report
