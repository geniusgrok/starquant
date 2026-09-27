"""T-D5-1: the spot leg is confirmed against the venue and against the prices, never against the name.

Every number asserted here was measured on 2026-09-09 and is recorded in `starquant_data.spot`'s module
docstring.  The fixtures are small because the properties are structural; the measurements they encode
are not, and the report that accompanied this commit says which of them were taken against the live
endpoints and which were not.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

HOUR_MS = 3_600_000
SPOT_LISTED = {"BTCUSDT", "SHIBUSDT", "PEPEUSDT", "1000SATSUSDT", "1000CATUSDT", "SOLUSDT"}


def _klines(open_times: list[int], closes: list[float], *, micros: bool = False) -> list[list[object]]:
    """Raw venue rows.  `micros` reproduces the spot archive's 2025-01 switch to microsecond stamps."""
    scale = 1000 if micros else 1
    return [
        [t * scale, c, c, c, c, 1.0, (t + HOUR_MS - 1) * scale, 10.0, 5, 0.5, 5.0]
        for t, c in zip(open_times, closes, strict=True)
    ]


def _frame(open_times: list[int], closes: list[float], *, micros: bool = False) -> pd.DataFrame:
    from starquant_data.binance_public import klines_to_frame

    return klines_to_frame(_klines(open_times, closes, micros=micros))


# --- the mapping: proposed from the name, confirmed by the venue ------------------------------------


def test_a_plain_perpetual_maps_to_the_spot_symbol_of_the_same_name() -> None:
    from starquant_data.spot import map_to_spot

    mapping = map_to_spot("BTCUSDT", SPOT_LISTED)

    assert mapping.spot == "BTCUSDT" and mapping.multiplier == 1.0


def test_a_thousand_prefixed_perpetual_carries_the_multiplier_into_the_mapping() -> None:
    """1000SHIBUSDT quotes a thousand SHIB, so its price is 1000x the spot price (six such symbols)."""
    from starquant_data.spot import map_to_spot

    mapping = map_to_spot("1000SHIBUSDT", SPOT_LISTED)

    assert mapping.spot == "SHIBUSDT" and mapping.multiplier == 1000.0


def test_a_token_whose_own_name_starts_with_digits_maps_to_itself() -> None:
    """The 1000CAT trap, measured: 1000SATSUSDT and 1000CATUSDT are SPOT symbols under those exact names.

    A string rule that stripped the digits would name a different asset - and where the venue happened
    to list that other asset it would pair two unrelated coins at a 1000x scale, which reads as a
    100,000% basis rather than as an error.  Identity is tried first for exactly this reason.
    """
    from starquant_data.spot import map_to_spot

    for perp in ("1000SATSUSDT", "1000CATUSDT"):
        mapping = map_to_spot(perp, SPOT_LISTED)
        assert mapping.spot == perp and mapping.multiplier == 1.0


def test_a_perpetual_the_spot_venue_does_not_list_maps_to_nothing() -> None:
    """166 of 528 perpetuals, so this is the ordinary case and it may not look like a failure."""
    from starquant_data.spot import map_to_spot

    mapping = map_to_spot("FARTCOINUSDT", SPOT_LISTED)

    assert mapping.spot is None and not mapping.exists


def test_the_stripped_candidate_is_only_taken_when_the_venue_lists_it() -> None:
    """1000RATSUSDT: neither the identity nor RATSUSDT is listed, so the answer is "no spot", not RATSUSDT."""
    from starquant_data.spot import map_to_spot

    assert map_to_spot("1000RATSUSDT", SPOT_LISTED).spot is None


def test_the_mapping_survives_a_round_trip_through_the_file_the_sync_writes(tmp_path: Path) -> None:
    """Research and live must resolve a perpetual the same way; a file can be compared, a rule cannot."""
    from starquant_data.spot import map_universe, read_spot_map, write_spot_map

    mappings = map_universe(["BTCUSDT", "1000SHIBUSDT", "FARTCOINUSDT"], SPOT_LISTED)
    write_spot_map(tmp_path, mappings, {"measured_at_ms": 1})

    restored = read_spot_map(tmp_path)
    assert restored["1000SHIBUSDT"].spot == "SHIBUSDT" and restored["1000SHIBUSDT"].multiplier == 1000.0
    assert restored["FARTCOINUSDT"].spot is None


def test_no_stored_map_reads_as_no_mapping_rather_than_an_error(tmp_path: Path) -> None:
    from starquant_data.spot import read_spot_map

    assert read_spot_map(tmp_path) == {}


# --- the alignment: measured against the prices ------------------------------------------------------


def _paired(n: int = 200, *, multiplier: float = 1.0, shift_bars: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A perp and a spot series on one grid, differing only by a small basis (and optionally a shift)."""
    rng = np.random.default_rng(7)
    opens = [i * HOUR_MS for i in range(n)]
    spot = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    basis = 1.0 + rng.normal(0.0004, 0.0002, n)
    perp = spot * multiplier * basis
    return (
        _frame([t + shift_bars * HOUR_MS for t in opens], list(perp)),
        _frame(opens, list(spot)),
    )


def test_a_correctly_paired_series_measures_zero_lag() -> None:
    """The spot analogue of DL-D2's 166/166: the offset is measured, not assumed to be zero."""
    from starquant_data.spot import SpotMapping, measure_alignment

    perp, spot = _paired()

    evidence = measure_alignment(perp, spot, mapping=SpotMapping("BTCUSDT", "BTCUSDT"), interval_ms=HOUR_MS)

    assert evidence.aligned and evidence.best_lag_bars == 0
    assert evidence.overlap_bars == 200


def test_a_one_bar_offset_is_caught_rather_than_absorbed() -> None:
    """This is the failure DL-D2 found one market over: it raises nothing and flatters every backtest.

    The sign is asserted in both directions because a lag whose direction is ambiguous cannot be acted
    on - the reader has no way to tell which of the two series to move.  Lag k means the perpetual bar
    at t was matched to the spot bar at t + k bars, so a perpetual stamped one bar LATE reports -1.
    """
    from starquant_data.spot import SpotMapping, measure_alignment

    mapping = SpotMapping("BTCUSDT", "BTCUSDT")

    late = measure_alignment(*_paired(shift_bars=1), mapping=mapping, interval_ms=HOUR_MS)
    early = measure_alignment(*_paired(shift_bars=-1), mapping=mapping, interval_ms=HOUR_MS)

    assert not late.aligned and late.best_lag_bars == -1 and "lag" in late.reason
    assert not early.aligned and early.best_lag_bars == 1 and "lag" in early.reason


def test_a_multiplier_that_is_off_by_a_thousand_is_refused_as_a_unit_error_not_as_a_lag() -> None:
    """The 1000SHIB mistake, priced: a wrong unit is |log ratio| ~= 6.9 against a real basis of ~0.0005.

    The verdict has to name the UNIT.  A 1000x error puts every candidate lag at the same 6.908 - the
    price gap swamps the price movement the lag search reads - so the argmin is noise, and the first
    version of this check duly reported "best lag is -2 bars" for a series with no lag at all.  That
    would have sent a reader hunting a timestamp bug that does not exist.
    """
    from starquant_data.spot import SpotMapping, measure_alignment

    perp, spot = _paired(multiplier=1000.0)

    wrong = measure_alignment(perp, spot, mapping=SpotMapping("1000SHIBUSDT", "SHIBUSDT", 1.0), interval_ms=HOUR_MS)
    right = measure_alignment(perp, spot, mapping=SpotMapping("1000SHIBUSDT", "SHIBUSDT", 1000.0), interval_ms=HOUR_MS)

    assert not wrong.aligned and "multiplier" in wrong.reason
    assert pytest.approx(6.9, abs=0.2) == wrong.median_abs_log_ratio
    assert right.aligned and right.median_abs_log_ratio < 0.01


def test_too_little_overlap_refuses_to_answer_instead_of_answering_weakly() -> None:
    """A verdict a measurement cannot support is the defect this repository keeps finding."""
    from starquant_data.spot import SpotMapping, measure_alignment

    perp, spot = _paired(n=10)

    evidence = measure_alignment(perp, spot, mapping=SpotMapping("BTCUSDT", "BTCUSDT"), interval_ms=HOUR_MS)

    assert not evidence.aligned and "overlap" in evidence.reason


def test_two_series_that_never_overlap_say_so(tmp_path: Path) -> None:
    from starquant_data.spot import SpotMapping, measure_alignment

    perp = _frame([i * HOUR_MS for i in range(50)], [100.0] * 50)
    spot = _frame([(1000 + i) * HOUR_MS for i in range(50)], [100.0] * 50)

    evidence = measure_alignment(perp, spot, mapping=SpotMapping("BTCUSDT", "BTCUSDT"), interval_ms=HOUR_MS)

    assert not evidence.aligned and evidence.overlap_bars == 0


# --- the two venue differences that do not raise -----------------------------------------------------


def test_the_spot_archives_microsecond_stamps_land_on_the_same_grid_as_the_perpetuals_milliseconds() -> None:
    """Measured: spot monthly files switched to microseconds at 2025-01; futures files are still ms.

    Read as milliseconds a microsecond stamp lands tens of thousands of years out, the join to the perp
    index matches nothing, and the resulting all-NaN column is indistinguishable from a symbol nobody
    downloaded.  Both markets pass through `klines_to_frame`, which is the only reason this holds.
    """
    opens = [1735689600000 + i * HOUR_MS for i in range(24)]

    perp = _frame(opens, [100.0] * 24)
    spot = _frame(opens, [100.0] * 24, micros=True)

    assert list(spot["open_time"]) == list(perp["open_time"])
    assert list(spot["close_time"]) == list(perp["close_time"])


def test_the_spot_client_pages_at_its_own_limit_rather_than_the_futures_one() -> None:
    """`/api/v3/klines?limit=1500` answers HTTP 200 with 1000 rows - it truncates instead of erroring.

    `klines_range` stops when a page comes back short of the page limit, so a spot client inheriting the
    futures 1500 would read one page, decide the range was exhausted, and end the tail 1000 bars in
    without a word.  The fake below truncates exactly as the venue does.
    """
    from starquant_data.spot import SPOT_MAX_KLINE_LIMIT, SpotClient

    served: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        limit = min(int(request.url.params["limit"]), SPOT_MAX_KLINE_LIMIT)
        start = int(request.url.params["startTime"])
        served.append(limit)
        rows = _klines([start + i * HOUR_MS for i in range(limit)], [100.0] * limit)
        return httpx.Response(200, json=rows)

    client = SpotClient()
    client._client = httpx.Client(base_url="https://api.binance.com", transport=httpx.MockTransport(handler))

    frame = client.klines_range("BTCUSDT", "1h", 0, 2500 * HOUR_MS)

    assert served and max(served) == SPOT_MAX_KLINE_LIMIT
    assert len(frame) > SPOT_MAX_KLINE_LIMIT, "the tail stopped at one page: the page limit is the futures one"


def test_a_symbol_the_spot_venue_does_not_list_is_an_absence_not_a_failure() -> None:
    """Measured: 400 with `-1121 Invalid symbol` on REST, 404 on the archive.  Neither may end a run."""
    from starquant_data.spot import SpotClient, SymbolNotListed

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    client = SpotClient(max_retries=0)
    client._client = httpx.Client(base_url="https://api.binance.com", transport=httpx.MockTransport(handler))

    with pytest.raises(SymbolNotListed):
        client.klines("FARTCOINUSDT", "1h")


def test_an_unlisted_spot_symbol_is_reported_apart_from_a_broken_download(tmp_path: Path) -> None:
    """`not_listed` rather than an error row: a third of the board would otherwise report as errors nightly."""
    from starquant_data.archive import ArchiveClient, Month
    from starquant_data.spot import SPOT_MARKET, SpotClient
    from starquant_data.store import SPOT_KLINE_KIND, KlineStore
    from starquant_data.sync import sync_klines

    def spot_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    client = SpotClient(max_retries=0)
    client._client = httpx.Client(base_url="https://api.binance.com", transport=httpx.MockTransport(spot_handler))
    archive = ArchiveClient()
    archive._client = httpx.Client(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )

    report = sync_klines(
        "FARTCOINUSDT",
        "1h",
        history_start=Month(2026, 8),
        store=KlineStore(tmp_path, kind=SPOT_KLINE_KIND),
        archive=archive,
        public=client,
        now_ms=Month(2026, 9).start_ms(),
        market=SPOT_MARKET,
    )

    assert report.not_listed and not report.errors


# --- the archive path -------------------------------------------------------------------------------


def test_the_two_markets_share_one_archive_path_builder() -> None:
    from starquant_data.archive import Month, archive_path
    from starquant_data.spot import SPOT_MARKET

    month = Month(2026, 8)

    assert archive_path("BTCUSDT", "1h", month) == ("/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-08.zip")
    assert archive_path("BTCUSDT", "1h", month, SPOT_MARKET) == (
        "/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-08.zip"
    )


def test_a_spot_month_is_verified_against_its_checksum_like_every_other_download(tmp_path: Path) -> None:
    """`archive.py` learned checksum-then-parse once; the spot market must not learn it again."""
    from starquant_data.archive import ArchiveClient, ChecksumMismatch, Month
    from starquant_data.spot import SPOT_MARKET

    header = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote,ignore\n"
    )
    body = "".join(
        f"{(1785542400000 + i * HOUR_MS) * 1000},1,1,1,{100 + i},1,{(1785542400000 + (i + 1) * HOUR_MS - 1) * 1000},1,1,1,1,0\n"
        for i in range(3)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive_zip:
        archive_zip.writestr("BTCUSDT-1h-2026-08.csv", header + body)
    payload = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/data/spot/monthly/klines/" in request.url.path
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{hashlib.sha256(payload).hexdigest()}  x.zip\n")
        return httpx.Response(200, content=payload)

    client = ArchiveClient()
    client._client = httpx.Client(base_url="https://data.binance.vision", transport=httpx.MockTransport(handler))

    frame = client.fetch_month("BTCUSDT", "1h", Month(2026, 8), SPOT_MARKET)

    assert frame is not None and len(frame) == 3
    # The header row is skipped and the microsecond stamps come back on the millisecond grid.
    assert int(frame["open_time"].iloc[0]) == 1785542400000

    def corrupt(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{'0' * 64}  x.zip\n")
        return httpx.Response(200, content=payload)

    client._client = httpx.Client(base_url="https://data.binance.vision", transport=httpx.MockTransport(corrupt))
    with pytest.raises(ChecksumMismatch):
        client.fetch_month("BTCUSDT", "1h", Month(2026, 8), SPOT_MARKET)


def test_a_month_the_spot_archive_never_published_is_none(tmp_path: Path) -> None:
    """Spot listings start later than the history window for most symbols; 404 is the normal answer."""
    from starquant_data.archive import ArchiveClient, Month
    from starquant_data.spot import SPOT_MARKET

    client = ArchiveClient()
    client._client = httpx.Client(
        base_url="https://data.binance.vision", transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )

    assert client.fetch_month("PEPEUSDT", "1h", Month(2021, 1), SPOT_MARKET) is None


def test_the_spot_store_is_a_separate_directory_keyed_by_the_spot_symbol(tmp_path: Path) -> None:
    """One spot symbol can back several perpetuals, so the store records the venue's name, not the perp's."""
    from starquant_data.store import SPOT_KLINE_KIND, KlineStore

    spot = KlineStore(tmp_path, kind=SPOT_KLINE_KIND)
    perp = KlineStore(tmp_path)
    spot.append("SHIBUSDT", "1h", _frame([0, HOUR_MS], [1.0, 2.0]))
    perp.append("1000SHIBUSDT", "1h", _frame([0, HOUR_MS], [1000.0, 2000.0]))

    assert spot.symbols("1h") == ["SHIBUSDT"] and perp.symbols("1h") == ["1000SHIBUSDT"]
    assert spot.directory != perp.directory


# --- the command ------------------------------------------------------------------------------------


def test_the_command_reports_the_mapping_the_missing_legs_and_the_alignment(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The contract is printed on every run, not behind a flag.

    T-D5-1 is a claim about two live series, and a claim only ever checked against fixtures is a claim
    about fixtures.  The three lines this asserts are the three the operator has to be able to read:
    which perpetuals have no leg, what each mapping scaled by, and whether the two grids still agree.
    """
    from click.testing import CliRunner

    import starquant_cli.data_cmd as data_cmd
    from starquant_data.archive import ArchiveClient
    from starquant_data.spot import SpotClient
    from starquant_data.store import KlineStore

    august = 1785542400000  # 2026-08-01 00:00 UTC
    now_ms = august + 30 * 24 * HOUR_MS
    perp_bars = [august + i * HOUR_MS for i in range(200)]
    perp_store = KlineStore(tmp_path)
    perp_store.append("BTCUSDT", "1h", _frame(perp_bars, [100.0 + i for i in range(200)]))
    perp_store.append("1000SHIBUSDT", "1h", _frame(perp_bars, [10.0 + i for i in range(200)]))
    perp_store.append("FARTCOINUSDT", "1h", _frame(perp_bars, [1.0] * 200))

    def spot_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": now_ms})
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(
                200,
                json={"symbols": [{"symbol": s, "status": "TRADING"} for s in ("BTCUSDT", "SHIBUSDT")]},
            )
        symbol = request.url.params["symbol"]
        # SHIBUSDT is a thousandth of the perpetual's price; a mapping that dropped the multiplier
        # would show up as a REFUSED line rather than as a plausible basis.
        scale = 0.001 if symbol == "SHIBUSDT" else 1.0
        base = 100.0 if symbol == "BTCUSDT" else 10.0
        return httpx.Response(200, json=_klines(perp_bars, [(base + i) * scale for i in range(200)]))

    monkeypatch.setattr(data_cmd, "SpotClient", lambda url: _with_transport(SpotClient(), spot_handler))
    monkeypatch.setattr(
        data_cmd, "ArchiveClient", lambda: _with_transport(ArchiveClient(), lambda r: httpx.Response(404))
    )

    result = CliRunner().invoke(
        data_cmd.data.commands["spot"],
        ["--root", str(tmp_path), "--symbols", "BTCUSDT,1000SHIBUSDT,FARTCOINUSDT", "--start", "2026-08"],
    )

    assert result.exit_code == 0, result.output
    assert "2/3 mapped, 1 with no spot listing" in result.output
    assert "no spot leg: FARTCOINUSDT" in result.output
    assert "1000SHIBUSDT -> SHIBUSDT x1000" in result.output
    for line in ("BTCUSDT/BTCUSDT:", "1000SHIBUSDT/SHIBUSDT:"):
        assert any(line in row and "lag=+0" in row and "OK" in row for row in result.output.splitlines()), (
            f"{line} did not report an aligned pairing:\n{result.output}"
        )
    # The mapping is left on disk for the panel to read; re-deriving it at read time is what it replaces.
    from starquant_data.spot import read_spot_map

    assert read_spot_map(tmp_path)["1000SHIBUSDT"].multiplier == 1000.0


def _with_transport(client, handler):  # type: ignore[no-untyped-def]
    """Point an already-built client at a fake venue, keeping its real retry and parsing code."""
    client._client = httpx.Client(base_url=str(client._client.base_url), transport=httpx.MockTransport(handler))
    return client
