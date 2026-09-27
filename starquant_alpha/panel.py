"""Wide market panel: one DataFrame per field, indexed by UTC bar open time, columns = symbols."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace

import pandas as pd

BAR_FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
)
REQUIRED_FIELDS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

_INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


def interval_seconds(interval: str) -> int:
    try:
        return _INTERVAL_SECONDS[interval]
    except KeyError as exc:
        raise ValueError(f"unsupported interval {interval!r}") from exc


def bars_per_year(interval: str) -> float:
    return 365.0 * 86400.0 / interval_seconds(interval)


def bar_freq(interval: str) -> str:
    """The pandas offset alias for one bar.  Binance's own aliases are not pandas' (``1m`` is a month there)."""
    return f"{interval_seconds(interval)}s"


def align_funding_to_bars(funding: pd.DataFrame, index: pd.DatetimeIndex, interval: str) -> pd.DataFrame:
    """Sum settled rates into the bar that *contains* them, never onto an exact timestamp match.

    Binance stamps ``fundingTime`` one to forty-seven milliseconds past the hour, and does so
    unevenly over time (34% of BTCUSDT's 2021 settlements land exactly on the hour against 85% of
    its 2024 ones).  Matching a settlement to a bar open by equality therefore dropped 43.7% of the
    441,678-row archive onto a silent zero: backtests with ``use_actual_funding`` charged about half
    the funding they should have, and the share missing differed from fold to fold.  Flooring onto
    the bar grid is the alignment the field was always documented to have.

    Two settlements inside one bar are summed, which is the same rule ``funding_per_bar`` applies
    when a symbol's schedule is finer than the bar.
    """
    if not isinstance(funding.index, pd.DatetimeIndex):
        raise ValueError("funding must be indexed by settlement time (a DatetimeIndex), not by position")
    stamps = funding.index
    stamps = stamps.tz_localize("UTC") if stamps.tz is None else stamps.tz_convert("UTC")
    binned = funding.set_axis(stamps.floor(bar_freq(interval)), axis=0)
    return binned.groupby(level=0).sum().reindex(index)


def to_utc_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy indexed by tz-aware UTC ``open_time`` (accepts ms ints or datetimes)."""
    if isinstance(frame.index, pd.DatetimeIndex) and "open_time" not in frame.columns:
        index = pd.DatetimeIndex(frame.index)
        out = frame.copy()
    else:
        raw = frame["open_time"]
        if pd.api.types.is_integer_dtype(raw):
            index = pd.DatetimeIndex(pd.to_datetime(raw.to_numpy(), unit="ms", utc=True))
        else:
            index = pd.DatetimeIndex(pd.to_datetime(raw.to_numpy(), utc=True))
        out = frame.drop(columns=["open_time"]).copy()
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    out.index = pd.DatetimeIndex(index, name="open_time")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


@dataclass(frozen=True)
class Panel:
    """Aligned wide frames.  Missing fields are ``None``; ``funding`` is the per-bar funding rate (0 off-settlement).

    ``reference`` (P1-01 / DL-Q1) names the population a *cross-sectional* operator ranks,
    demeans or takes a breadth share over.  It is deliberately not a filter on the panel:
    every time series stays whole, so a symbol that re-enters the universe brings its own
    history with it and its rolling windows are defined on the first bar of membership -
    which is what the live loop, requesting full history for the symbols it manages, does.
    ``None`` means "every column", the behaviour before the contract existed.

    Why it has to be explicit.  ``apply_crowding_modifier`` ranked over ``score.columns``
    and ``flow`` demeaned over all of them, so the population was whatever the caller
    happened to load: research builds the panel from every symbol that was ever a member
    (205 on the point-in-time universe, ~123 with data on an average bar) and applies the
    membership mask only after the scores exist, while the live loop passes the 15-18 it
    manages that day.  Same registry parameters, two different signals - KILL-027's shape.
    """

    interval: str
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    quote_volume: pd.DataFrame | None = None
    trades: pd.DataFrame | None = None
    taker_buy_base: pd.DataFrame | None = None
    taker_buy_quote: pd.DataFrame | None = None
    funding: pd.DataFrame | None = None
    reference: pd.DataFrame | None = None
    # DL-D4.  One wide frame per metrics column (bars x symbols), ALREADY ALIGNED to these bars.
    #
    # Aligned by the caller and not here, which is the one design decision in this field.  The rule -
    # a bar may read the latest bucket that had CLOSED by the bar's own close - lives in
    # `starquant_data.metrics.align_to_bars` together with the measurement that justifies it (archive
    # `create_time` == rest `timestamp` - 5 minutes, 166/166 exact).  `starquant_alpha` may not import
    # `starquant_data`, so a copy here would be a second implementation of a look-ahead rule, and the
    # two would drift.  `from_frames` refuses a frame that is not on the bar index instead, so a
    # mis-aligned frame cannot enter through the front door either.
    metrics: dict[str, pd.DataFrame] | None = None
    # DL-D5.  One wide frame per SPOT field (bars x symbols), keyed by the PERPETUAL symbol and already
    # quoted in the perpetual's unit, so `close / spot["close"] - 1` is the basis and nothing here has
    # to know that 1000SHIBUSDT trades a thousand SHIB at a time.
    #
    # Aligned by the caller, exactly like `metrics` and for the same reason: the rule - a perp bar reads
    # the spot bar with the SAME open time or reads NaN - lives in `starquant_data.spot` next to the
    # measurement that justifies it (XMRUSDT's spot has been halted since 2024-02-20 while its perpetual
    # quadrupled, so "latest available" would price a +324% basis off a dead listing).  A symbol with no
    # spot leg is an all-NaN column rather than an absent one: 166 of 528 perpetuals have no spot at all,
    # and the panel has to be able to say that about a symbol it does carry.
    spot: dict[str, pd.DataFrame] | None = None

    @classmethod
    def from_frames(
        cls,
        frames: Mapping[str, pd.DataFrame],
        interval: str,
        funding: Mapping[str, pd.Series] | pd.DataFrame | None = None,
        metrics: Mapping[str, pd.DataFrame] | None = None,
        spot: Mapping[str, pd.DataFrame] | None = None,
    ) -> Panel:
        if not frames:
            raise ValueError("at least one symbol frame is required")
        normalized = {symbol: to_utc_index(frame) for symbol, frame in frames.items()}
        for symbol, frame in normalized.items():
            missing = [field for field in REQUIRED_FIELDS if field not in frame.columns]
            if missing:
                raise ValueError(f"{symbol} is missing required fields {missing}")
        wide: dict[str, pd.DataFrame | None] = {}
        for field in BAR_FIELDS:
            if all(field in frame.columns for frame in normalized.values()):
                wide[field] = pd.concat(
                    {symbol: frame[field].astype(float) for symbol, frame in normalized.items()}, axis=1
                )
            else:
                wide[field] = None
        index = pd.DatetimeIndex(wide["close"].index) if wide["close"] is not None else None
        funding_frame: pd.DataFrame | None = None
        if funding is not None and index is not None:
            funding_frame = funding if isinstance(funding, pd.DataFrame) else pd.DataFrame(dict(funding))
            funding_frame = align_funding_to_bars(funding_frame, index, interval)
            funding_frame = funding_frame.reindex(columns=list(normalized)).fillna(0.0).astype(float)
        assert wide["open"] is not None and wide["high"] is not None and wide["low"] is not None
        assert wide["close"] is not None and wide["volume"] is not None

        # The refusal that makes "aligned by the caller" safe, for both foreign sources.  A reindex here
        # would be the helpful thing to do and would silently re-introduce whatever offset the caller
        # had: what those stamps meant is exactly what this class does not know, so it cannot fix them.
        def on_bar_index(kind: str, source: Mapping[str, pd.DataFrame], aligner: str) -> dict[str, pd.DataFrame]:
            out: dict[str, pd.DataFrame] = {}
            for name, frame in source.items():
                if index is not None and not frame.index.equals(index):
                    raise ValueError(
                        f"{kind} column {name!r} is not on the bar index; align it with "
                        f"{aligner} before building the panel"
                    )
                out[str(name)] = frame.reindex(columns=list(normalized)).astype(float)
            return out

        metrics_frames = on_bar_index("metrics", metrics, "starquant_data.metrics.align_to_bars") if metrics else None
        spot_frames = on_bar_index("spot", spot, "starquant_data.spot.align_spot_to_perp_bars") if spot else None
        return cls(
            interval=interval,
            open=wide["open"],
            high=wide["high"],
            low=wide["low"],
            close=wide["close"],
            volume=wide["volume"],
            quote_volume=wide["quote_volume"],
            trades=wide["trades"],
            taker_buy_base=wide["taker_buy_base"],
            taker_buy_quote=wide["taker_buy_quote"],
            funding=funding_frame,
            metrics=metrics_frames,
            spot=spot_frames,
        )

    def spot_field(self, name: str) -> pd.DataFrame | None:
        """One spot field on the bar index, or None when the panel carries no spot at all.

        Two different absences, kept apart.  ``None`` means nobody ingested spot for this panel; an
        all-NaN COLUMN inside the frame means this perpetual has no spot leg on the venue, which is the
        ordinary case for a third of the board.  Collapsing them would make "not downloaded" and "does
        not exist" the same input, and only one of those is fixed by running the sync.
        """
        return None if not self.spot else self.spot.get(name)

    def metric(self, name: str) -> pd.DataFrame | None:
        """One metrics column, or None when the panel carries none.

        None rather than a zero frame: a metric nobody ingested and a metric that is genuinely zero
        are different facts, and zero-filling the first is how a node ends up scoring on data that was
        never there (the `metrics_parity` lesson, one level down).
        """
        return None if not self.metrics else self.metrics.get(name)

    @property
    def symbols(self) -> list[str]:
        return [str(column) for column in self.close.columns]

    @property
    def index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close.index)

    @property
    def bars_per_year(self) -> float:
        return bars_per_year(self.interval)

    @property
    def settled_symbols(self) -> int:
        """Symbols carrying at least one settlement.  A zero column and no column are the same input.

        ``FundingStore.load`` returns an empty frame for a symbol with no archive and ``funding_per_bar``
        turns that into a column of zeros, so a root whose klines are synced but whose funding never was
        yields ``funding`` that is present and says nothing.  Anything asking "does this panel actually
        carry funding" must ask this, not ``funding is None`` - that only answers "was funding requested".
        """
        return 0 if self.funding is None else int((self.funding.abs().sum(axis=0) > 0).sum())

    @property
    def spot_symbols(self) -> int:
        """Symbols with at least one spot bar.  DL-D5's answer to "can this panel price a basis?".

        The same question `settled_symbols` answers for funding, and it has to be asked the same way and
        for a sharper reason: 166 of 528 perpetuals have no spot leg at all, so `spot is not None` only
        says spot was REQUESTED, and a panel of nothing but all-NaN columns would pass it while every
        basis candidate evaluated to NaN.  `mine` narrows its search space on this rather than on the
        flag, which is what stopped the DL-D4 repeat where 90 metrics candidates were charged to
        `declared_trials` and errored unscored in every round.
        """
        close = self.spot_field("close")
        return 0 if close is None else int(close.notna().any(axis=0).sum())

    def reference_mask(self) -> pd.DataFrame:
        """The cross-sectional population as a bars x symbols boolean frame; all-true when unset."""
        if self.reference is None:
            return pd.DataFrame(True, index=self.close.index, columns=self.close.columns)
        return self.reference.reindex(index=self.close.index, columns=self.close.columns).fillna(False).astype(bool)

    def with_reference(self, reference: pd.DataFrame | None) -> Panel:
        """The same panel with its cross-sectional population set (DL-Q1)."""
        return replace(self, reference=reference)

    def _map(self, function: Callable[[pd.DataFrame], pd.DataFrame]) -> Panel:
        """Apply `function` to every frame this panel carries - EVERY frame, including `metrics`.

        `metrics` was omitted here, so it defaulted to None and `slice` / `tail` / `select` returned a
        panel with no metrics columns at all.  Nothing reported that: `_required_metric` raises, the
        miner counts the raise, and the count is all that reaches the report.  Measured 2026-09-09 on
        the round mined right after the 202/205 metrics backfill - the whole point of that backfill was
        the DL-D4 OI / long-short leaves - `outcomes.errored = 90`, and the 90 are EXACTLY the 54 `oi`
        and 36 `lsr` candidates.  Zero of them have ever been scored, in any round.  The expression
        evaluates fine on the panel it was handed; the miner slices, and the slice drops the column.
        """

        def maybe(frame: pd.DataFrame | None) -> pd.DataFrame | None:
            return None if frame is None else function(frame)

        return Panel(
            metrics=None if self.metrics is None else {name: function(f) for name, f in self.metrics.items()},
            interval=self.interval,
            open=function(self.open),
            high=function(self.high),
            low=function(self.low),
            close=function(self.close),
            volume=function(self.volume),
            quote_volume=maybe(self.quote_volume),
            trades=maybe(self.trades),
            taker_buy_base=maybe(self.taker_buy_base),
            taker_buy_quote=maybe(self.taker_buy_quote),
            funding=maybe(self.funding),
            reference=maybe(self.reference),
            # Carried through the slice, because a basis leaf is scored on `panel.slice(end=cutoff)` and
            # dropping it here would make the holdout split the thing that decides whether the leg
            # exists.  The same sentence is why `metrics` is carried above.
            spot=None if self.spot is None else {name: function(frame) for name, frame in self.spot.items()},
        )

    def slice(self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None) -> Panel:
        """Rows with ``start <= open_time < end``; bounds may be naive (read as UTC) or already tz-aware."""

        def as_utc(value: pd.Timestamp | str | None) -> pd.Timestamp | None:
            if value is None:
                return None
            stamp = pd.Timestamp(value)
            return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")

        start_ts = as_utc(start)
        end_ts = as_utc(end)

        def cut(frame: pd.DataFrame) -> pd.DataFrame:
            mask = pd.Series(True, index=frame.index)
            if start_ts is not None:
                mask &= frame.index >= start_ts
            if end_ts is not None:
                mask &= frame.index < end_ts
            return frame[mask.to_numpy()]

        return self._map(cut)

    def tail(self, bars: int) -> Panel:
        return self._map(lambda frame: frame.iloc[-bars:])

    def select(self, symbols: Iterable[str]) -> Panel:
        chosen = [symbol for symbol in symbols if symbol in self.close.columns]
        return self._map(lambda frame: frame[chosen])

    def latest_bar(self) -> pd.Timestamp:
        return pd.Timestamp(self.close.index[-1])
