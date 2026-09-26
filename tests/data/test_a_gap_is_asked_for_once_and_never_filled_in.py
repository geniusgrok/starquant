"""`starquant data repair` (9.4): each hole is asked for once, merged bit for bit, or recorded as confirmed.

The rows served here are verbatim slices of the real archive (`tests/fixtures/gap_repair/`, plus the BNX
redenomination slice the bar sanity tests already carry), because a repair tested against rows a fake
invented tests a contract that does not exist.  The daily archive is served through `ArchiveClient`'s own
transport seam, so the path, the checksum check and the zip parser are the ones `--apply` runs.  Nothing
here reaches the network: every source is either that transport or a stub that fails when it is asked.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_cli import data_cmd, main
from starquant_data.archive import ArchiveClient, daily_archive_path, zip_to_frame
from starquant_data.binance_public import KLINE_COLUMNS, funding_to_frame
from starquant_data.repair import (
    CONFIRMED_GAPS_FILE,
    FUNDING,
    Gap,
    Sources,
    find_gaps,
    funding_holes,
    read_confirmed,
    record_confirmed,
    repair,
)
from starquant_data.store import FundingStore, KlineStore, funding_per_bar
from tests.alpha.test_causality import _bit_for_bit

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "gap_repair"
BNX = ROOT / "tests" / "fixtures" / "bar_sanity" / "BNXUSDT_2023-02-22.json"
SLICES = (
    "BTCUSDT_2022-02-26.json",
    "1000BONKUSDT_funding_2026-06-24.json",
    "LAYERUSDT_funding_listing.json",
    "KORUUSDT_funding_2026-07-15.json",
)
H = 3_600_000
NOW = 1_790_000_000_000  # 2026-09-21: every hole below has long closed
HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
)


def ms(text: str) -> int:
    return int(pd.Timestamp(text, tz="UTC").timestamp() * 1000)


# The batch hole: FLOWUSDT, GTCUSDT and sixteen more lack exactly these 72 bars in the stored archive.
AFTER, BEFORE = ms("2022-02-25 23:00"), ms("2022-03-01 00:00")


def _slice(path: Path) -> tuple[str, pd.DataFrame]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["symbol"]), pd.DataFrame(payload["rows"], columns=payload["columns"])


def _btc() -> pd.DataFrame:
    return _slice(FIXTURES / "BTCUSDT_2022-02-26.json")[1]


def _day_zip(rows: pd.DataFrame, name: str) -> bytes:
    """One day in the archive's own CSV layout, header row included, zipped as the archive ships it.

    The slice's eleven columns are the archive's first eleven, in order; the twelfth is the unused one.
    ``str`` of a float64 is its shortest round-trip form, so the parser reads back the same bits.
    """
    assert list(rows.columns) == list(KLINE_COLUMNS)
    lines = [HEADER, *(",".join([*(str(value) for value in row), "0"]) for row in rows.itertuples(index=False))]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name.replace(".zip", ".csv"), "\n".join(lines) + "\n")
    return buffer.getvalue()


def _daily_archive(symbol: str, rows: pd.DataFrame) -> tuple[httpx.MockTransport, list[str], dict[str, bytes]]:
    """Serve one checksummed file per UTC day in ``rows``; anything else is a 404, as the archive answers."""
    files: dict[str, bytes] = {}
    days = pd.to_datetime(rows["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    for day, part in rows.groupby(days.to_numpy()):
        path = daily_archive_path(symbol, "1h", str(day))
        files[path] = _day_zip(part, path.rsplit("/", 1)[1])
        files[path + ".CHECKSUM"] = f"{hashlib.sha256(files[path]).hexdigest()}  {path.rsplit('/', 1)[1]}\n".encode()
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        body = files.get(request.url.path)
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    return httpx.MockTransport(handler), asked, files


def _refuse(*args: object) -> pd.DataFrame | None:
    raise AssertionError(f"this source was not supposed to be asked: {args}")


def _sources(archive: ArchiveClient | None = None, **stubs: Callable[..., Any]) -> Sources:
    return Sources(
        archive_day=archive.fetch_day if archive is not None else _refuse,
        rest_klines=stubs.get("rest_klines", _refuse),
        rest_funding=stubs.get("rest_funding", _refuse),
    )


def _store_with_hole(root: Path, rows: pd.DataFrame, first: int, last: int) -> None:
    KlineStore(root).append("BTCUSDT", "1h", rows[~rows["open_time"].between(first, last)])


# --- klines ---------------------------------------------------------------------------------------------


def test_the_2022_batch_hole_is_mended_from_the_daily_files_bit_for_bit(tmp_path: Path) -> None:
    rows = _btc()
    _store_with_hole(tmp_path, rows, AFTER + H, BEFORE - H)
    (gap,) = find_gaps(tmp_path, "1h")
    assert gap == Gap("klines/1h", "BTCUSDT", AFTER, BEFORE, 72), "the hole the 18 symbols carry, exactly"

    transport, asked, files = _daily_archive("BTCUSDT", rows[rows["open_time"].between(AFTER + H, BEFORE - H)])
    with ArchiveClient(transport=transport) as archive:
        outcome = repair(gap, root=tmp_path, sources=_sources(archive), now_ms=NOW)

    assert (outcome.added, outcome.confirmed, outcome.errors) == (72, [], [])
    assert outcome.answers["rest"] == "not asked: the archive filled the hole"
    assert len(asked) == 6, "three day files and their three checksums, nothing else"
    stored = KlineStore(tmp_path).load("BTCUSDT", "1h")
    served = pd.concat([zip_to_frame(body) for path, body in sorted(files.items()) if path.endswith(".zip")])
    inside = stored[stored["open_time"].between(AFTER + H, BEFORE - H)]
    _bit_for_bit(inside.reset_index(drop=True), served.reset_index(drop=True))  # what the source served
    _bit_for_bit(stored, rows.reset_index(drop=True))  # and the archive slice, whole
    assert find_gaps(tmp_path, "1h") == []


def test_a_stored_bar_is_never_rewritten_and_the_watermark_does_not_move(tmp_path: Path) -> None:
    """The dedupe rule keeps the LAST row; a repair must never hand it a stored bar to decide about."""
    rows = _btc()
    first, last = ms("2022-02-26 05:00"), ms("2022-02-26 10:00")
    _store_with_hole(tmp_path, rows, first, last)
    before = KlineStore(tmp_path).load("BTCUSDT", "1h")
    day = rows[rows["open_time"].between(ms("2022-02-26 00:00"), ms("2022-02-26 23:00"))].copy()
    noon = day["open_time"] == ms("2022-02-26 12:00")
    day.loc[noon, "trades"] += 1  # a column the agreement check does not read, on a bar that is stored
    transport, _, _ = _daily_archive("BTCUSDT", day)
    (gap,) = find_gaps(tmp_path, "1h")
    with ArchiveClient(transport=transport) as archive:
        outcome = repair(gap, root=tmp_path, sources=_sources(archive), now_ms=NOW)

    after = KlineStore(tmp_path).load("BTCUSDT", "1h")
    assert outcome.added == 6 and after["open_time"].is_unique and after["open_time"].is_monotonic_increasing
    kept = after[after["open_time"].isin(before["open_time"])].reset_index(drop=True)
    _bit_for_bit(kept, before)  # the stored noon bar kept its own `trades`
    assert KlineStore(tmp_path).last_open_time("BTCUSDT", "1h") == int(before["open_time"].max())


def test_a_source_that_disagrees_with_a_stored_bar_gives_nothing_and_confirms_nothing(tmp_path: Path) -> None:
    rows = _btc()
    _store_with_hole(tmp_path, rows, ms("2022-02-26 05:00"), ms("2022-02-26 10:00"))
    before = KlineStore(tmp_path).load("BTCUSDT", "1h")
    day = rows[rows["open_time"].between(ms("2022-02-26 00:00"), ms("2022-02-26 23:00"))].copy()
    day.loc[day["open_time"] == ms("2022-02-26 12:00"), "close"] *= 55.0  # another series under the same name
    transport, _, _ = _daily_archive("BTCUSDT", day)
    (gap,) = find_gaps(tmp_path, "1h")
    with ArchiveClient(transport=transport) as archive:
        outcome = repair(gap, root=tmp_path, sources=_sources(archive, rest_klines=lambda *_: None), now_ms=NOW)

    assert outcome.added == 0 and outcome.confirmed == []
    assert outcome.errors == ["archive 2022-02-26 disagrees with 1 stored values; nothing taken from it"]
    _bit_for_bit(KlineStore(tmp_path).load("BTCUSDT", "1h"), before)


def test_an_unclosed_bar_is_not_merged_and_its_hole_is_not_confirmed(tmp_path: Path) -> None:
    rows = _btc()
    _store_with_hole(tmp_path, rows, AFTER + H, BEFORE - H)
    transport, _, _ = _daily_archive("BTCUSDT", rows[rows["open_time"].between(AFTER + H, BEFORE - H)])
    (gap,) = find_gaps(tmp_path, "1h")
    clock = AFTER + 11 * H  # ten bars of the hole have closed; the eleventh is still open
    with ArchiveClient(transport=transport) as archive:
        outcome = repair(gap, root=tmp_path, sources=_sources(archive, rest_klines=lambda *_: None), now_ms=clock)

    assert outcome.added == 10 and outcome.confirmed == [], "`drop_unclosed`, the sync's rule, applies here too"
    stored = KlineStore(tmp_path).load("BTCUSDT", "1h")
    inside = stored[stored["open_time"].between(AFTER + H, BEFORE - H)]
    assert len(inside) == 10 and (inside["close_time"] < clock).all()


def test_a_hole_no_source_holds_is_confirmed_once_and_status_stops_counting_it(tmp_path: Path) -> None:
    symbol, rows = _slice(BNX)
    KlineStore(tmp_path).append(symbol, "1h", rows)
    runner = CliRunner()
    assert (
        "gaps: 1 missing stretch(es) across 1 symbols; 0 confirmed"
        in runner.invoke(main, ["data", "status", "--root", str(tmp_path)]).output
    )
    (gap,) = find_gaps(tmp_path, "1h")
    assert (gap.after, gap.before, gap.missing) == (1_675_206_000_000, 1_677_074_400_000, 518)

    transport, asked, _ = _daily_archive(symbol, rows.iloc[:0])  # the archive has none of those days
    with ArchiveClient(transport=transport) as archive:
        outcome = repair(gap, root=tmp_path, sources=_sources(archive, rest_klines=lambda *_: None), now_ms=NOW)
    assert outcome.confirmed == [gap] and outcome.added == 0 and len(asked) == 22
    assert outcome.answers == {"archive": "22 day files, 22 absent (404), 0 bars inside", "rest": "not listed (-1121)"}
    path, new = record_confirmed(tmp_path, [outcome], NOW)
    assert new == 1 and path == tmp_path / CONFIRMED_GAPS_FILE
    (entry,) = read_confirmed(tmp_path).values()
    assert entry["after_utc"] == "2023-01-31T23:00Z" and entry["before_utc"] == "2023-02-22T14:00Z"
    assert record_confirmed(tmp_path, [outcome], NOW + H)[1] == 0, "recorded once; a second answer adds nothing"

    status = runner.invoke(main, ["data", "status", "--root", str(tmp_path)]).output
    assert "gaps: 0 missing stretch(es) across 1 symbols; 1 confirmed absent upstream" in status
    assert "GAPS=" not in status
    plan = runner.invoke(main, ["data", "repair", "--root", str(tmp_path), "--no-funding"]).output
    assert "klines/1h: 0 hole(s), 0 missing, 0 symbol(s); already confirmed, not asked: 1" in plan
    _bit_for_bit(KlineStore(tmp_path).load(symbol, "1h"), rows)  # confirming touches no bar


# --- funding --------------------------------------------------------------------------------------------


def test_a_hole_is_judged_against_the_symbols_own_schedule() -> None:
    _, bonk = _slice(FIXTURES / "1000BONKUSDT_funding_2026-06-24.json")
    _, layer = _slice(FIXTURES / "LAYERUSDT_funding_listing.json")
    _, koru = _slice(FIXTURES / "KORUUSDT_funding_2026-07-15.json")
    (hole,) = funding_holes(bonk["funding_time"].to_numpy())
    assert (hole[0] // H * H, hole[1] // H * H, hole[2]) == (ms("2026-06-24 00:00"), ms("2026-06-24 08:00"), 1)
    assert funding_holes(layer["funding_time"].to_numpy()) == [], "4h then 2h after listing is a schedule change"
    (hole,) = funding_holes(koru["funding_time"].to_numpy())
    assert (hole[0] // H * H, hole[1] // H * H, hole[2]) == (ms("2026-07-15 00:00"), ms("2026-07-15 16:00"), 1)

    def hours(*steps: int) -> list[int]:
        return [int(t) * H for t in np.cumsum([0, *steps])]

    assert funding_holes(hours(4, 4, 4, 4, 8, 8, 8, 8)) == [], "a switch from 4h to 8h"
    assert funding_holes(hours(8, 8, 8, 4, 4, 4, 4)) == [], "and back"
    assert [h[2] for h in funding_holes(hours(8, 8, 8, 16, 16, 8, 8, 8))] == [1, 1], "two holes side by side"
    assert [h[2] for h in funding_holes(hours(1, 1, 1, 1, 3, 1, 1, 1))] == [2]


def _bonk_store(root: Path) -> pd.DataFrame:
    _, bonk = _slice(FIXTURES / "1000BONKUSDT_funding_2026-06-24.json")
    FundingStore(root).append("1000BONKUSDT", bonk)
    return bonk


def _rest(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame REST's own parser makes of these rows, as `PublicClient.funding_history` returns it."""
    return funding_to_frame(
        [
            {"fundingTime": int(r.funding_time), "fundingRate": str(r.funding_rate), "markPrice": str(r.mark_price)}
            for r in frame.itertuples()
        ]
    )


def test_a_settlement_the_venue_never_published_is_confirmed(tmp_path: Path) -> None:
    bonk = _bonk_store(tmp_path)
    (gap,) = find_gaps(tmp_path, "1h")
    assert gap.dataset == FUNDING and gap.missing == 1
    around = bonk[bonk["funding_time"].between(gap.after, gap.before)]
    outcome = repair(gap, root=tmp_path, sources=_sources(rest_funding=lambda *_: _rest(around)), now_ms=NOW)
    assert outcome.confirmed == [gap] and outcome.added == 0 and outcome.answers == {"rest": "2 rows, 0 new inside"}


def test_a_missing_settlement_is_merged_into_its_own_hour_and_no_other(tmp_path: Path) -> None:
    """`funding_per_bar` sums the settlements inside a bar, so a second stamp in a settled hour charges it twice."""
    bonk = _bonk_store(tmp_path)
    (gap,) = find_gaps(tmp_path, "1h")
    around = bonk[bonk["funding_time"].between(gap.after, gap.before)]
    extra = pd.DataFrame(
        {
            "funding_time": [gap.after + 7, ms("2026-06-24 04:00") + 3],  # a re-stamp of 00:00, and the hole
            "funding_rate": [0.00031, -0.00017],
            "mark_price": [0.0101, 0.0102],
        }
    )
    answer = _rest(pd.concat([around, extra]).sort_values("funding_time"))
    bars = pd.date_range("2026-06-22", "2026-06-26", freq="1h", tz="UTC", inclusive="left")
    charged = funding_per_bar(bonk, bars)
    outcome = repair(gap, root=tmp_path, sources=_sources(rest_funding=lambda *_: answer), now_ms=NOW)

    assert (outcome.added, outcome.confirmed, outcome.errors) == (1, [], [])
    now_charged = funding_per_bar(FundingStore(tmp_path).load("1000BONKUSDT"), bars)
    moved = now_charged[now_charged != charged]
    assert list(moved.index) == [pd.Timestamp("2026-06-24 04:00", tz="UTC")] and moved.iloc[0] == -0.00017


# --- the command ----------------------------------------------------------------------------------------


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_dry_run_fetches_nothing_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("a dry run opened a client")

    monkeypatch.setattr(data_cmd, "PublicClient", no_network)
    monkeypatch.setattr(data_cmd, "ArchiveClient", no_network)
    _store_with_hole(tmp_path, _btc(), AFTER + H, BEFORE - H)
    _bonk_store(tmp_path)
    before = _snapshot(tmp_path)

    result = CliRunner().invoke(main, ["data", "repair", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "BTCUSDT        2022-02-26T00:00Z .. 2022-02-28T23:00Z  72 bar(s): 3 archive day file(s)" in result.output
    assert "fetch: 3 archive day file(s) (+3 CHECKSUM), up to 2 REST call(s)" in result.output
    assert "dry run: nothing fetched, nothing written" in result.output
    assert _snapshot(tmp_path) == before and not (tmp_path / CONFIRMED_GAPS_FILE).exists()


class _DelistedVenue:
    """What REST answers for a symbol the venue no longer lists: 400 -1121, from klines and funding alike."""

    def __init__(self, url: str) -> None:
        self.url = url

    def __enter__(self) -> _DelistedVenue:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def server_time_ms(self) -> int:
        return NOW

    def _invalid(self) -> pd.DataFrame:
        request = httpx.Request("GET", f"{self.url}/fapi/v1/klines")
        response = httpx.Response(400, text='{"code":-1121,"msg":"Invalid symbol."}', request=request)
        raise httpx.HTTPStatusError("400 Bad Request", request=request, response=response)

    def klines_range(self, *_: object) -> pd.DataFrame:
        return self._invalid()

    def funding_history(self, *_: object) -> pd.DataFrame:
        return self._invalid()


def test_apply_reads_a_delisted_symbol_as_absent_and_records_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symbol, rows = _slice(BNX)
    KlineStore(tmp_path).append(symbol, "1h", rows)
    transport, asked, _ = _daily_archive(symbol, rows.iloc[:0])
    monkeypatch.setattr(data_cmd, "PublicClient", _DelistedVenue)
    monkeypatch.setattr(data_cmd, "ArchiveClient", lambda: ArchiveClient(transport=transport))

    result = CliRunner().invoke(main, ["data", "repair", "--root", str(tmp_path), "--apply"])
    assert result.exit_code == 0, result.output
    assert (
        "+0 row(s), confirmed 1 (archive: 22 day files, 22 absent (404), 0 bars inside; rest: not listed (-1121))"
        in (result.output)
    )
    assert "1 newly confirmed" in result.output and len(asked) == 22
    assert list(read_confirmed(tmp_path)) == [("klines/1h", symbol, 1_675_206_000_000, 1_677_074_400_000)]


# --- the fixtures ---------------------------------------------------------------------------------------


@pytest.mark.skipif(
    not (ROOT / ".starquant" / "data" / "klines").exists(),
    reason="the archive is not in this checkout (CI and worktrees)",
)
@pytest.mark.parametrize("name", SLICES)
def test_the_fixtures_are_the_archive_verbatim(name: str) -> None:
    """A fixture nobody can compare to its source is a fixture someone could have made up."""
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    archive = pd.read_parquet(ROOT / payload["source"])
    rows = archive[archive[payload["key"]].between(payload["from"], payload["to"])].reset_index(drop=True)
    _, fixture = _slice(FIXTURES / name)
    assert list(rows.columns) == payload["columns"]
    _bit_for_bit(rows, fixture)
