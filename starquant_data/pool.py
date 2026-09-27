"""Trading pool: point-in-time membership for research and a daily refresh for the live loop (D-013, D-014).

Research side.  ``point_in_time_membership`` rebuilds "the top-N by trailing
quote volume *as it stood at the time*" from daily klines of every symbol
that ever had an archive, so backtests do not trade 2021 with the 2026
universe.  Live side.  ``LivePool`` re-ranks candidates once a day with the
same hysteresis; the engine flattens what leaves and lets ``min_history_bars``
keep new listings untraded until they have a month of bars.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from starquant_data.archive import ArchiveClient, Month, month_range
from starquant_data.binance_public import AsyncPublicClient, PublicClient, drop_unclosed
from starquant_data.store import KlineStore
from starquant_data.universe import UniverseConfig, eligible_symbols, rank_with_hysteresis
from starquant_shared.types import InstrumentRules

DAILY = "1d"
DAY_MS = 86_400_000
MEMBERSHIP_FILE = "membership.parquet"


# --- research: daily data and point-in-time membership --------------------------------------------


@dataclass
class DailySyncReport:
    symbol: str
    rows: int = 0
    source: str = "cached"
    error: str = ""


def sync_daily(
    symbol: str,
    *,
    store: KlineStore,
    public: PublicClient,
    archive: ArchiveClient | None,
    now_ms: int,
    start_ms: int,
    listed: bool,
    max_age_days: int = 2,
) -> DailySyncReport:
    """Daily klines: REST for symbols the venue still lists, monthly archives for delisted ones."""
    report = DailySyncReport(symbol)
    last = store.last_open_time(symbol, DAILY) if store.exists(symbol, DAILY) else None
    if last is not None and last >= now_ms - max_age_days * DAY_MS:
        report.rows = store.count(symbol, DAILY)
        return report
    try:
        if listed:
            frame = drop_unclosed(public.klines_range(symbol, DAILY, (last + 1) if last else start_ms, now_ms), now_ms)
            report.source = "rest"
        else:
            if archive is None:
                raise RuntimeError("archive client required for delisted symbols")
            first = Month.of_ms(last + 1) if last else Month.of_ms(start_ms)
            pieces = [archive.fetch_month(symbol, DAILY, month) for month in month_range(first, Month.of_ms(now_ms))]
            frames = [piece for piece in pieces if piece is not None and not piece.empty]
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            report.source = "archive"
    except Exception as exc:  # network / parsing: report, never raise out of a bulk sync
        report.error = f"{type(exc).__name__}: {exc}"
        return report
    if not frame.empty:
        store.append(symbol, DAILY, frame)
    report.rows = store.count(symbol, DAILY)
    return report


def daily_quote_volume(store: KlineStore, symbols: Iterable[str]) -> pd.DataFrame:
    """Wide frame (UTC day x symbol) of daily quote volume; NaN where the symbol has no bar."""
    columns: dict[str, pd.Series] = {}
    for symbol in symbols:
        if not store.exists(symbol, DAILY):
            continue
        frame = store.load(symbol, DAILY)
        if frame.empty:
            continue
        index = pd.DatetimeIndex(pd.to_datetime(frame["open_time"].to_numpy(), unit="ms", utc=True)).normalize()
        series = pd.Series(frame["quote_volume"].to_numpy(dtype=float), index=index)
        columns[symbol] = series[~series.index.duplicated(keep="last")]
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(columns).sort_index()


def point_in_time_membership(
    quote_volume: pd.DataFrame,
    config: UniverseConfig,
    *,
    eligible: Iterable[str] | None = None,
    refresh: str = "MS",
    start: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Boolean frame (refresh date x symbol): members chosen at each refresh from data strictly before it.

    A symbol is rankable once it has ``config.min_age_days`` daily bars; its
    score is the trailing ``config.volume_lookback_days`` quote volume.  The
    same enter/exit hysteresis as the live pool is applied against the
    previous refresh's members, so membership churn in backtests matches what
    the live loop would have done.
    """
    if quote_volume.empty:
        raise ValueError("no daily quote volume supplied")
    days = pd.DatetimeIndex(quote_volume.index)
    first = pd.Timestamp(start, tz="UTC") if start is not None else days[0] + pd.Timedelta(days=config.min_age_days)
    dates = pd.date_range(first.normalize(), days[-1], freq=refresh, tz="UTC")
    if len(dates) == 0 or dates[0] > first:
        dates = pd.DatetimeIndex([first.normalize(), *dates]) if len(dates) else pd.DatetimeIndex([first.normalize()])
    universe = list(quote_volume.columns)
    eligible_set = set(universe if eligible is None else eligible)
    rows: list[list[bool]] = []
    previous: list[str] = []
    observed = quote_volume.notna().cumsum()
    for date in dates:
        before = quote_volume.loc[: date - pd.Timedelta(nanoseconds=1)]
        if before.empty:
            rows.append([False] * len(universe))
            continue
        age = observed.loc[: date - pd.Timedelta(nanoseconds=1)].iloc[-1]
        window = before.iloc[-config.volume_lookback_days :]
        volumes = {s: float(window[s].fillna(0.0).sum()) for s in universe if age[s] >= config.min_age_days}
        members = rank_with_hysteresis(
            volumes,
            eligible_set & set(volumes),
            previous,
            enter_rank=config.enter_rank,
            exit_rank=config.exit_rank,
            top_n=config.top_n,
            always_include=config.always_include,
        )
        previous = members
        chosen = set(members)
        rows.append([s in chosen for s in universe])
    return pd.DataFrame(rows, index=dates, columns=universe, dtype=bool)


def membership_at_bars(membership: pd.DataFrame, bar_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill refresh-date membership onto bar timestamps; bars before the first refresh are out."""
    if membership.empty:
        return pd.DataFrame(False, index=bar_index, columns=[])
    aligned = membership.reindex(membership.index.union(bar_index)).ffill().reindex(bar_index)
    return aligned.fillna(False).astype(bool)


def tenure_mask(membership: pd.DataFrame, min_refreshes: int) -> pd.DataFrame:
    """Members with at least ``min_refreshes`` cumulative refreshes of membership as of each row (causal).

    An "established names" universe: a symbol must have been selected that
    many times before (this refresh included) to be tradable.
    """
    members = membership.astype(bool)
    if min_refreshes <= 1:
        return members
    tenure = members.astype(int).cumsum(axis=0)
    return members & (tenure >= min_refreshes)


def membership_summary(membership: pd.DataFrame, *, available: pd.DataFrame | None = None) -> dict[str, Any]:
    """Shape of a membership table, plus - when the caller can say - how many slots held no data.

    ``available`` is a boolean frame of the same shape: did this symbol have market data at this
    refresh?  Given one, the summary gains ``dead_slots`` (member-refresh slots with no data),
    ``dead_slot_share`` and ``worst_refresh``.  Omitted, those keys are ABSENT rather than 0.0
    (D-035): a metric that could not be computed must never read as one that passed.  The caller owns
    the I/O - this module is handed frames, it does not open the archive.

    Why it is worth three keys for a number this small.  A 30-day trailing volume keeps ranking a
    symbol that has stopped quoting, so it can hold one of ``top_n`` slots with nothing in it for up to
    a month: LUNAUSDT's last 1h bar is 2022-05-13 and it stayed a member until 2022-06-10, 28
    refreshes.  Measured over the whole point-in-time table - 2,042 refreshes, 35,899 member-refresh
    slots - that is 109 dead slots, 0.30%, on 104 refresh days (5.1%), worst 2 of 18 on 2026-07-18.
    0.30% changes no conclusion.  It is reported because "N-choose-K degenerates in some periods" is a
    family of defect where a measured 0.30% and an unmeasured unknown are not the same answer, and only
    one of them can be argued with.

    Running it also splits the 109 into two unrelated causes, which is the part a single share hides:
    28 are LUNAUSDT's delisting tail, and the other 81 belong to six 2026 names (SKYAI, SYN, BLESS,
    ALLO, RE, ENSO) whose 1h archive has simply not been backfilled - the same six
    ``research --universe pit`` already prints as "member symbols have no 1h klines yet".  Those are a
    sync gap wearing a universe defect's clothes, and the fix for them is a download.
    """
    if membership.empty:
        return {"refreshes": 0, "union": [], "mean_size": 0.0, "changes_per_refresh": 0.0}
    sizes = membership.sum(axis=1)
    diffs = membership.astype(int).diff().abs().sum(axis=1).iloc[1:]
    summary: dict[str, Any] = {
        "refreshes": len(membership),
        "union": sorted(membership.columns[membership.any(axis=0)]),
        "mean_size": float(sizes.mean()),
        "changes_per_refresh": float(diffs.mean()) if len(diffs) else 0.0,
        "first": str(membership.index[0]),
        "last": str(membership.index[-1]),
    }
    if available is None:
        return summary
    members = membership.astype(bool)
    # `fillna(False)` on the REINDEX, so a symbol or refresh the caller could say nothing about counts
    # as dead rather than as fine.  A slot the archive cannot speak for is exactly the slot in question.
    live = available.reindex(index=membership.index, columns=membership.columns).fillna(False).astype(bool)
    slots = int(members.sum().sum())
    if not slots:  # no member-refresh slots at all: the share is 0/0, and 0.0 would read as a pass
        return summary
    per_refresh = (members & ~live).sum(axis=1)
    worst = per_refresh.idxmax()
    summary["dead_slots"] = int(per_refresh.sum())
    summary["dead_slot_share"] = float(per_refresh.sum() / slots)
    summary["worst_refresh"] = {
        "at": str(worst),
        "dead": int(per_refresh.loc[worst]),
        "members": int(sizes.loc[worst]),
    }
    return summary


MEMBERSHIP_ALERT_DAYS = 14
"""The hourly check alerts once the table trails today (UTC) by this many days.  Measured, not picked.

Bars after the last row borrow it (``membership_at_bars`` forward-fills), so a lag of k days is k days of
research run on a frozen pool.  On the table rebuilt 2026-09-18 (2,056 daily rows, last 2026-09-17, kept
as ``tests/fixtures/pit_membership_2026_09_17``) a refresh changes 0.36 names, and a frozen pool misses
1.2 of ~17.6 on its 7th day and 2.3 on its 14th.  A whole-history run barely notices; a window that ENDS
today does - a backtest of the live period set beside the live record, say.  In a 30-day window whose
last k days are borrowed, the wrong share of member slots averages 2.98% at k=13 and 3.42% at k=14 over
2,027 windows (last year: 2.95% / 3.38%).  RESEARCH_LOG's P12 stage-0 rule calls a membership change
under 3% too small to backtest, and 14 is the first k past it.  A fresh rebuild reads 1, not 0: its last
row is the last closed daily bar, yesterday's.

Against the calendar, not the archive's newest bar: the archive moves only when a sync runs (daily, from
`com.starquant.data`), so that base would let a stalled sync silence this alert too, and nothing checks the
sync hourly.
"""


@dataclass(frozen=True)
class MembershipLag:
    """``status``: OK, STALE, EMPTY, NOT_DAILY (built without ``--refresh D``) or AHEAD (last row after today)."""

    status: str
    last: pd.Timestamp | None = None
    lag_days: int | None = None
    gap_days: float | None = None


def membership_lag(
    membership: pd.DataFrame, today: str | pd.Timestamp, *, alert_days: int = MEMBERSHIP_ALERT_DAYS
) -> MembershipLag:
    """Whole UTC days from the table's last row to ``today``: the days research can only forward-fill.

    Every state that cannot vouch for freshness is named rather than read as OK.  A monthly table
    that is five days old is not fresh - every bar in it borrows a row up to a month old.
    """
    if membership.empty:
        return MembershipLag("EMPTY")
    index = pd.DatetimeIndex(membership.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    now = pd.Timestamp(today)
    now = now.tz_localize("UTC") if now.tz is None else now.tz_convert("UTC")
    last = index.max().normalize()
    lag = (now.normalize() - last).days
    gaps = pd.Series(index.sort_values()).diff().dropna()
    gap = float(gaps.median() / pd.Timedelta(days=1)) if len(gaps) else None
    if gap is not None and round(gap) != 1:  # half a day of tolerance; monthly reads 31, weekly 7
        status = "NOT_DAILY"
    elif lag < 0:
        status = "AHEAD"
    else:
        status = "STALE" if lag >= alert_days else "OK"
    return MembershipLag(status, last, lag, gap)


# --- live: daily refresh --------------------------------------------------------------------------


@dataclass(frozen=True)
class UniverseUpdate:
    symbols: tuple[str, ...]
    entered: tuple[str, ...]
    left: tuple[str, ...]
    at_ms: int
    volumes: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "entered": list(self.entered),
            "left": list(self.left),
            "at_ms": self.at_ms,
            "volumes": dict(self.volumes),
        }


def refresh_selection(
    volume_by_symbol: Mapping[str, float],
    rules: Mapping[str, InstrumentRules],
    config: UniverseConfig,
    previous: Sequence[str],
    at_ms: int,
) -> UniverseUpdate:
    """Rank what the caller measured.  ``volume_by_symbol`` is the eligibility set, pins included.

    ``point_in_time_membership`` drops a symbol that is too young *before* pinning, so a pin only survives
    if it was measurable that day.  Live has to intersect the same way or the two disagree about pins.
    """
    selected = rank_with_hysteresis(
        volume_by_symbol,
        [symbol for symbol in eligible_symbols(rules, config) if symbol in volume_by_symbol],
        previous,
        enter_rank=config.enter_rank,
        exit_rank=config.exit_rank,
        top_n=config.top_n,
        always_include=config.always_include,
    )
    before, after = set(previous), set(selected)
    return UniverseUpdate(
        symbols=tuple(selected),
        entered=tuple(sorted(after - before)),
        left=tuple(sorted(before - after)),
        at_ms=at_ms,
        volumes={s: float(v) for s, v in volume_by_symbol.items() if s in after},
    )


class LivePool:
    """Daily universe refresh from mainnet public data (implements ``starquant_live.ports.UniverseProvider``)."""

    def __init__(
        self, client: AsyncPublicClient, config: UniverseConfig, *, candidates: int = 0, concurrency: int = 4
    ) -> None:
        self._client = client
        self.config = config
        self._candidates = candidates or 3 * config.top_n
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _volume(self, symbol: str, days: int, now_ms: int) -> tuple[str, float, int]:
        """Trailing quote volume, and the closed daily bars behind it so ``select`` can apply the age filter."""
        async with self._semaphore:
            frame = await self._client.klines(symbol, DAILY, max(days, self.config.min_age_days) + 1)
        closed = drop_unclosed(frame, now_ms)
        if closed.empty:
            return symbol, 0.0, 0
        return symbol, float(closed["quote_volume"].tail(days).sum()), len(closed)

    async def select(self, previous: Sequence[str], rules: Mapping[str, InstrumentRules]) -> UniverseUpdate:
        now_ms = await self._client.server_time_ms()
        eligible = set(eligible_symbols(rules, self.config))
        tickers = await self._client.ticker_24h()
        by_24h = sorted(
            ((str(row.get("symbol", "")), float(row.get("quoteVolume", 0.0) or 0.0)) for row in tickers),
            key=lambda item: -item[1],
        )
        shortlist = [symbol for symbol, _ in by_24h if symbol in eligible][: self._candidates]
        candidates = list(dict.fromkeys([*self.config.always_include, *previous, *shortlist]))
        candidates = [symbol for symbol in candidates if symbol in eligible]
        days = self.config.volume_lookback_days
        results = await asyncio.gather(*(self._volume(symbol, days, now_ms) for symbol in candidates))
        # D-013's listing-age filter, live half.  Research ranks a symbol only once it has ``min_age_days``
        # daily bars; a live pool that skips the test spends one of ``top_n`` slots on a listing the model
        # then refuses to trade (``min_history_bars``), so the book runs on fewer names than the backtest
        # that justified it - and nothing reports the gap.  A fetch failure raises out of ``gather`` and the
        # engine keeps yesterday's universe (T-P05), so ``bars`` here is always a measurement, never a miss.
        volumes = {symbol: volume for symbol, volume, bars in results if bars >= self.config.min_age_days}
        return refresh_selection(volumes, rules, self.config, previous, now_ms)
