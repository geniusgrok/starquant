"""Binance SPOT klines beside the USDⓈ-M perpetual ones, and the contract that makes the two comparable (DL-D5).

Everything below was MEASURED against the venue on 2026-09-09, not inferred from the naming, because
DL-D2 is the record of what inferring costs: metrics' archive stamp turned out to be one bucket earlier
than REST's, nothing raised, and every piece of evidence would have carried five minutes of look-ahead.
Spot-vs-perp is the same shape one market over, so it gets the same treatment.

1.  COVERAGE.  362 of the 528 TRADING USDT perpetuals have a TRADING spot symbol; 166 do not.  A third
    of the board has no spot leg at all, so "missing" is the common case rather than the exception, and
    a pipeline that cannot say so honestly is worse than no pipeline.

2.  THE NAME IS NOT A RULE.  Six perps quote a multiple of the spot unit - 1000BONK, 1000FLOKI,
    1000LUNC, 1000PEPE, 1000SHIB, 1000XEC - so their price is 1000x the spot price.  But 1000CATUSDT,
    1000CHEEMSUSDT, 1000SATSUSDT and 1MBABYDOGEUSDT are listed on SPOT under those exact names: the
    TOKEN is called 1000SATS, and stripping the digits would name a different asset (or, as here, one
    the venue does not list).  So a candidate is PROPOSED from the name and CONFIRMED against the
    venue's own listing, identity first.  A pure string rule gets four symbols wrong today and would
    get them wrong silently - a 1000x price error reads as a 100,000% basis, not as an exception.

3.  THE GRID.  Both markets stamp ``open_time`` on the same UTC hour boundary: every bar of 2026-08,
    in both markets, satisfies ``open_time % 3_600_000 == 0``.

4.  ARCHIVE VS REST, for spot.  744/744 bars of BTCUSDT 2026-08 have identical closes when the archive's
    ``open_time`` is joined to REST's ``openTime`` directly; 0/743 at a one-bar shift either way.  So
    there is NO offset here - the opposite of what DL-D2 found for metrics.  That is precisely why it
    had to be measured: "no offset" and "one bucket of offset" look the same in code.

5.  UNITS.  The spot monthly archive switched from milliseconds to MICROSECONDS at 2025-01 (BTCUSDT
    1h: 1717200000000 in 2024-06, 1735689600000000 in 2025-01); the futures archive is still
    milliseconds in 2026-08.  ``klines_to_frame`` normalises both, which is the only reason a spot
    ingest can reuse it - reading a microsecond stamp as milliseconds puts the bar tens of thousands of
    years out, the join to the perp index then matches nothing, and a column of NaN looks exactly like
    a symbol nobody downloaded.

6.  THE LAG.  For BTCUSDT, SOLUSDT, 1000SHIBUSDT and 1000PEPEUSDT over 2026-08, the lag minimising
    ``median |log(perp_close / (spot_close * multiplier))|`` is 0 bars, at 0.00043-0.00151 against
    0.0015-0.0039 one bar either side.  This is the spot analogue of DL-D2's 166/166, and
    ``measure_alignment`` is it as a runnable check rather than a sentence in a log.

7.  WHY THERE IS NO FORWARD FILL.  XMRUSDT's spot listing has been halted since 2024-02-20 02:00 (last
    bar, close 118.70) while its perpetual trades normally (2026-09-09 07:00, close 503.83).  Under the
    "latest bucket that had closed" rule ``metrics.align_to_bars`` uses - correct there, for open
    interest - a basis leaf would read +324% and hold it for two years.  It would look like the trade of
    the decade and it is an artefact of a dead listing.  So a perp bar reads the spot bar with the SAME
    open time or it reads NaN.  Same grid, so same-bar costs nothing; a hole stays a hole.

8.  PAGE SIZE.  ``/api/v3/klines?limit=1500`` returns HTTP 200 and 1000 rows - it does not error, it
    truncates.  ``klines_range`` decides "was that a full page?" by comparing against the page limit, so
    a spot client inheriting the futures 1500 would read one page, conclude the range was exhausted and
    stop 1000 bars in, quietly.  Hence ``_page_limit`` is per client rather than a module constant.

9.  ABSENCE.  A perp with no spot listing answers 400 ``-1121 Invalid symbol`` on REST and 404 on the
    archive.  Neither is a failure and neither may end a run.
"""

from __future__ import annotations

import json
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from starquant_data.binance_public import PublicClient, is_invalid_symbol

SPOT_BASE_URL = "https://api.binance.com"
SPOT_MARKET = "spot"  # the `market` segment of a data.binance.vision archive path
SPOT_MAX_KLINE_LIMIT = 1000
SPOT_MAP_FILE = "spot_map.json"
# Perpetual names whose spot leg the daily `starquant data spot` maps and syncs whatever the kline store holds.
# USDCUSDT is the stablecoin peg `starquant_live/report_events.py` reads (#8.10): the only stablecoin pair the
# archive holds, and until 2026-09-25 it was synced only because a perpetual of that name happened to be stored.
ALWAYS_MAPPED: tuple[str, ...] = ("USDCUSDT",)

# Price columns are quoted in the perpetual's unit after scaling; `quote_volume` is USDT on both sides
# and is carried unscaled.  Base `volume` is deliberately NOT carried: one unit differs between the two
# markets by exactly the multiplier, so a column that mixed them would be wrong for six symbols and
# right for the rest, which is the least detectable kind of wrong.
SPOT_PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")
SPOT_PANEL_COLUMNS: tuple[str, ...] = (*SPOT_PRICE_COLUMNS, "quote_volume")

# A wrong multiplier is out by a factor of at least ten, i.e. |log ratio| >= 2.3.  The largest residual
# measured on a CORRECT pairing was 0.0015 (1000PEPE, median over 2026-08).  0.5 sits three hundred
# times above the real basis and four times below the smallest possible unit error, so it separates the
# two questions this check exists to keep apart: "is the basis large today" and "is this the wrong pair".
MAX_ABS_LOG_RATIO = 0.5


class SymbolNotListed(LookupError):
    """The spot venue does not list this symbol.  An absence, not a failure - see note 9."""


@dataclass(frozen=True)
class SpotMapping:
    """One perpetual's spot leg, or the recorded fact that it has none.

    ``multiplier`` is defined by ``perp_price ~= spot_price * multiplier``, so it is what a spot price
    must be multiplied by to be quoted in the perpetual's own unit.
    """

    perp: str
    spot: str | None
    multiplier: float = 1.0

    @property
    def exists(self) -> bool:
        return self.spot is not None


def spot_candidates(perp: str) -> list[tuple[str, float]]:
    """Spot symbols this perpetual COULD be, most likely first: identity, then the digits stripped.

    Identity leads because a leading number can belong to the token's own name (1000SATS, 1000CAT), and
    the venue is the only thing that can tell the two cases apart.  At most three candidates are
    proposed - identity, digits removed, digits-and-magnitude-letter removed - because a wider net would
    start proposing names that merely look plausible, and every extra candidate is another chance to
    confirm a pairing that is really a different asset.
    """
    candidates: list[tuple[str, float]] = [(perp, 1.0)]
    if not perp.endswith("USDT"):
        return candidates
    base = perp[: -len("USDT")]
    digits = len(base) - len(base.lstrip("0123456789"))
    if digits == 0 or digits == len(base):
        return candidates
    scale = float(base[:digits])
    stripped = base[digits:]
    candidates.append((stripped + "USDT", scale))
    # "1MBABYDOGE" is one million BABYDOGE, but "MOG" starts with an M of its own, so the magnitude
    # letter is a candidate rather than a parse.
    if len(stripped) > 1 and stripped[0] in ("M", "B"):
        candidates.append((stripped[1:] + "USDT", scale * (1e6 if stripped[0] == "M" else 1e9)))
    return candidates


def map_to_spot(perp: str, listed: Container[str]) -> SpotMapping:
    """The first candidate the venue actually lists, or a mapping that records the absence."""
    for candidate, multiplier in spot_candidates(perp):
        if candidate in listed:
            return SpotMapping(perp=perp, spot=candidate, multiplier=multiplier)
    return SpotMapping(perp=perp, spot=None)


def map_universe(perps: Iterable[str], listed: Container[str]) -> dict[str, SpotMapping]:
    return {perp: map_to_spot(perp, listed) for perp in perps}


def write_spot_map(
    root: str | Path, mappings: Mapping[str, SpotMapping], meta: Mapping[str, Any] | None = None
) -> Path:
    """Persist the mapping as the venue snapshot that produced it.

    A file rather than a rule re-derived at read time, and rather than a directory listing of whatever
    got downloaded: research and the live loop must resolve a perp to the SAME spot symbol, and a
    derivation that runs twice can disagree with itself once the listing changes underneath it.  This is
    D-040's lesson - re-deriving a layout instead of asking the thing that knows it.
    """
    path = Path(root) / SPOT_MAP_FILE
    payload = {
        "symbols": {
            perp: {"spot": mapping.spot, "multiplier": mapping.multiplier} for perp, mapping in sorted(mappings.items())
        },
        **dict(meta or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_spot_map(root: str | Path) -> dict[str, SpotMapping]:
    """The stored mapping, or ``{}`` when nothing was ever ingested."""
    path = Path(root) / SPOT_MAP_FILE
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(perp): SpotMapping(
            perp=str(perp),
            spot=None if entry.get("spot") is None else str(entry["spot"]),
            multiplier=float(entry.get("multiplier", 1.0)),
        )
        for perp, entry in (payload.get("symbols") or {}).items()
    }


def align_spot_to_perp_bars(spot: pd.DataFrame, bars: pd.DatetimeIndex, *, multiplier: float = 1.0) -> pd.DataFrame:
    """The spot bar with the SAME open time as each perp bar, quoted in the perpetual's unit; else NaN.

    Causality (T-D5-2).  The two markets share one grid (note 3), so the spot bar opening at t closes at
    exactly the instant the perp bar opening at t closes.  A decision taken on the perp bar's close may
    therefore read it, and reads nothing the perp close does not already carry: this adds no lag of its
    own and inherits whatever execution lag the panel already applies to ``close``.

    No fill, in either direction, and that is the whole design (note 7).  Reindexing is the only
    operation here; a ``ffill`` would be the helpful thing to add and would turn XMRUSDT's two-year-old
    halted price into a +324% basis that no other instrument in the system could contradict.
    """
    columns = [column for column in SPOT_PANEL_COLUMNS if column in spot.columns]
    if spot.empty or not columns:
        return pd.DataFrame(index=bars, columns=list(SPOT_PANEL_COLUMNS), dtype=float)
    stamps = pd.DatetimeIndex(pd.to_datetime(spot["open_time"].astype("int64").to_numpy(), unit="ms", utc=True))
    indexed = spot[columns].set_axis(stamps, axis=0).astype(float)
    indexed = indexed[~indexed.index.duplicated(keep="last")].sort_index()
    aligned = indexed.reindex(bars)
    for column in SPOT_PRICE_COLUMNS:
        if column in aligned.columns:
            aligned[column] = aligned[column] * float(multiplier)
    return aligned.reindex(columns=list(SPOT_PANEL_COLUMNS))


@dataclass(frozen=True)
class AlignmentEvidence:
    """What ``measure_alignment`` found.  Numbers, then a verdict derived from them - never the reverse.

    ``best_lag_bars`` is stated from the PERPETUAL's point of view: k means each perp bar was compared
    against the spot bar opening k bars later, so a positive k is the direction that reads the future.
    Only 0 is acceptable.  The sign is spelled out because a lag whose direction is ambiguous is a lag
    nobody can act on - the reader cannot tell which series to move.
    """

    perp: str
    spot: str
    multiplier: float
    overlap_bars: int
    best_lag_bars: int
    median_abs_log_ratio: float
    p95_abs_log_ratio: float
    reason: str

    @property
    def aligned(self) -> bool:
        return self.reason == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "perp": self.perp,
            "spot": self.spot,
            "multiplier": self.multiplier,
            "overlap_bars": self.overlap_bars,
            "best_lag_bars": self.best_lag_bars,
            "median_abs_log_ratio": self.median_abs_log_ratio,
            "p95_abs_log_ratio": self.p95_abs_log_ratio,
            "aligned": self.aligned,
            "reason": self.reason,
        }


def measure_alignment(
    perp: pd.DataFrame,
    spot: pd.DataFrame,
    *,
    mapping: SpotMapping,
    interval_ms: int,
    lags: Sequence[int] = (-2, -1, 0, 1, 2),
    min_overlap_bars: int = 24,
) -> AlignmentEvidence:
    """Test the pairing against the prices themselves: is the offset zero, and is the multiplier right?

    Two failures are caught by one statistic.  A one-bar timestamp error and a wrong unit both inflate
    ``|log(perp / (spot * multiplier))|``, and they inflate it by amounts three orders of magnitude
    apart, so the residual at the best lag says WHICH went wrong rather than only that something did.

    ``lags`` are applied to the PERPETUAL: lag k compares the perp bar opening at t with the spot bar
    opening at ``t + k * interval_ms``, so k > 0 is the direction that reads the future.

    A too-short overlap refuses to answer instead of answering weakly.  Twenty-four bars of a fresh
    listing can put any lag on top by chance, and a check that returns a verdict it cannot support is
    the failure this repository keeps finding - a number where there is no measurement.
    """
    if mapping.spot is None:
        raise ValueError(f"{mapping.perp} has no spot leg to measure")
    frames = []
    for name, frame in (("perp", perp), ("spot", spot)):
        if frame.empty:
            return AlignmentEvidence(
                mapping.perp, mapping.spot, mapping.multiplier, 0, 0, float("nan"), float("nan"), f"no {name} bars"
            )
        series = frame.set_index(frame["open_time"].astype("int64"))["close"].astype(float)
        frames.append(series[~series.index.duplicated(keep="last")].sort_index())
    perp_close, spot_close = frames
    scored: dict[int, tuple[int, float, float]] = {}
    for lag in lags:
        joined = pd.concat(
            {"perp": perp_close.set_axis(perp_close.index + lag * int(interval_ms)), "spot": spot_close}, axis=1
        ).dropna()
        joined = joined[(joined["perp"] > 0) & (joined["spot"] > 0)]
        if joined.empty:
            continue
        residual = np.abs(np.log(joined["perp"].to_numpy() / (joined["spot"].to_numpy() * mapping.multiplier)))
        scored[int(lag)] = (len(joined), float(np.median(residual)), float(np.percentile(residual, 95)))
    if not scored:
        return AlignmentEvidence(
            mapping.perp, mapping.spot, mapping.multiplier, 0, 0, float("nan"), float("nan"), "no overlap"
        )
    best_lag = min(scored, key=lambda lag: scored[lag][1])
    overlap, median, p95 = scored.get(0, scored[best_lag])
    # Unit before lag, and the order is not cosmetic.  A multiplier that is out by 1000 puts every lag
    # at |log ratio| ~= 6.908 - the price difference swamps the price MOVEMENT the lag search reads - so
    # the argmin becomes noise and the report names a lag that does not exist.  Measured on the first
    # run of this function: a 1000x error reported "best lag is -2 bars", which would have sent a reader
    # looking for a timestamp problem that was not there.  A wrong unit hides a wrong lag; a wrong lag
    # (median ~0.006 with the right unit) does not hide a wrong unit.
    if overlap < min_overlap_bars:
        reason = f"overlap {overlap} bars < {min_overlap_bars}"
    elif not np.isfinite(median) or median > MAX_ABS_LOG_RATIO:
        reason = (
            f"median |log ratio| {median:.4f} > {MAX_ABS_LOG_RATIO} (multiplier {mapping.multiplier:g} looks wrong)"
        )
    elif best_lag != 0:
        reason = f"best lag is {best_lag:+d} bars, not 0"
    else:
        reason = "ok"
    return AlignmentEvidence(mapping.perp, mapping.spot, mapping.multiplier, overlap, best_lag, median, p95, reason)


class SpotClient(PublicClient):
    """The futures public client with two path prefixes and its own page size (note 8).

    A subclass and not a copy: retry, backoff, the retryable status set and the frame conversion are the
    same venue behaviour under a different prefix, and two copies of them would be two things to fix.
    """

    _klines_path = "/api/v3/klines"
    _page_limit = SPOT_MAX_KLINE_LIMIT

    def __init__(self, base_url: str = SPOT_BASE_URL, timeout: float = 20.0, max_retries: int = 5) -> None:
        super().__init__(base_url=base_url, timeout=timeout, max_retries=max_retries)

    def server_time_ms(self) -> int:
        return int(self.get("/api/v3/time")["serverTime"])

    def exchange_info(self) -> dict[str, Any]:
        payload = self.get("/api/v3/exchangeInfo")
        assert isinstance(payload, dict)
        return payload

    def listed_symbols(self, status: str = "TRADING") -> set[str]:
        """Spot symbols in ``status``.

        Defaults to TRADING because that is what "has a spot leg the live side can price" means.  The
        distinction is not academic: XMRUSDT's spot symbol is listed in BREAK and still answers REST
        with its last bar from 2024-02-20, so a laxer filter admits a symbol whose price stopped two
        years ago while the perpetual keeps trading.
        """
        return {str(row["symbol"]) for row in self.exchange_info().get("symbols", []) if row.get("status") == status}

    def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        try:
            return super().klines(symbol, interval, start_ms=start_ms, end_ms=end_ms, limit=limit)
        except httpx.HTTPStatusError as exc:
            if is_invalid_symbol(exc):
                raise SymbolNotListed(symbol) from exc
            raise
