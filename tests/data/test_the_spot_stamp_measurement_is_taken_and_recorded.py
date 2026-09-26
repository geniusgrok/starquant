"""DL-D5, the half that was missing: somebody has to actually TAKE the spot measurement.

`starquant_data.alignment` declared the SPOT contract on 2026-09-09 and `starquant_live.engine.spot_refusal`
held a basis candidate to it, and the gate was shut on every root forever - because nothing produced a
`Verification`.  `starquant_data.spot`'s docstring recorded a real measurement (744/744 bars at lag 0,
0/743 one bar either way) and a sentence in a docstring is not one of these, which is precisely what
`admits_live_signal` is built to be unable to read.

So these tests are about the path from the venue to the gate, and the three places it must stay honest:

* the CHECK is a comparison of two independent renderings (archive vs REST), not of a frame with itself;
* the RECORD carries the counts, and the reader RE-DERIVES the verdict from them rather than believing
  the one written beside them - otherwise a file an operator can edit is a config key in a measurement's
  clothes, and `LiveEngine.__init__` says in as many words that no such thing may open this gate;
* a run that could not measure leaves the gate shut.  "The archive had no month for this symbol" and
  "the offset is fine" are different facts and only one of them is a permission.

The reverse control for the middle one is `test_a_record_whose_own_numbers_refute_it_is_not_admitted`:
edit the counts under a PASS and the gate closes again.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_cli import main
from starquant_data.alignment import (
    FAIL,
    PASS,
    SPOT,
    SPOT_BASIS_COLUMN,
    SPOT_COLUMNS,
    SPOT_MIN_OVERLAP_BARS,
    SPOT_VERIFICATION_FILE,
    UNVERIFIABLE,
    admits_live_signal,
    read_spot_verification,
    rederive_verdict,
    spot_verification_frame,
    verify_spot_contract,
    write_spot_verification,
)
from starquant_data.archive import Month
from starquant_data.spot import SPOT_MARKET
from starquant_data.store import SPOT_KLINE_KIND, KlineStore
from starquant_live.engine import spot_refusal

HOUR_MS = 3_600_000
AUGUST = Month(2026, 8)
# Inside 2026-09 and past the first bar of it, so `Month.of_ms(now)` is September and the last COMPLETE
# month - the one the command samples - is August.
NOW_MS = Month(2026, 9).start_ms() + 5 * HOUR_MS


def _bars(count: int = 60, *, start_ms: int = AUGUST.start_ms(), seed: int = 5) -> pd.DataFrame:
    """Hourly klines in the shape `klines_to_frame` returns, with a close that moves every bar.

    Moving is the requirement, not the decoration: `verify_stamp_offset` answers UNVERIFIABLE unless the
    rival offsets are REFUTED, and a flat series agrees with itself at every offset.  `high` and `low`
    are scaled off the same walk for the same reason.
    """
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, count)))
    opens = [start_ms + index * HOUR_MS for index in range(count)]
    return pd.DataFrame(
        {
            "open_time": opens,
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1.0,
            "close_time": [open_time + HOUR_MS - 1 for open_time in opens],
            "quote_volume": close * 10.0,
            "trades": 1,
            "taker_buy_base": 0.5,
            "taker_buy_quote": 0.5,
        }
    )


# --- the check ---------------------------------------------------------------------------------------


def test_two_renderings_of_the_same_bars_confirm_the_declared_zero_offset_and_refute_its_rivals() -> None:
    """The measured answer for spot is ZERO, which is exactly why it had to be measured: "no offset" and
    "one bucket of offset" look identical in code, and metrics turned out to be the second one."""
    result = verify_spot_contract(_bars(), _bars())

    assert result.verdict == PASS, result.reason
    assert result.matched == result.compared == 60
    assert {rival.rest_offset_ms for rival in result.rivals} == {-HOUR_MS, HOUR_MS}
    assert all(rival.matched < rival.compared for rival in result.rivals), "an unrefuted rival is no evidence"
    assert set(result.compared_columns) == set(SPOT_COLUMNS)
    assert admits_live_signal(SPOT_BASIS_COLUMN, result) == (True, f"spot: {result.reason}")


def test_a_rest_sample_shifted_by_one_bar_fails_rather_than_being_absorbed() -> None:
    """DL-D2's defect, one market over: the two sources' own stamps taken as equal when they are not.
    It flatters - research reads a value before live could have - and nothing else in the system sees it."""
    shifted = _bars().assign(open_time=lambda frame: frame["open_time"] + HOUR_MS)

    result = verify_spot_contract(_bars(), shifted)

    assert result.verdict == FAIL, result.reason
    assert admits_live_signal(SPOT_BASIS_COLUMN, result)[0] is False


def test_a_sample_that_does_not_move_answers_unverifiable_rather_than_pass() -> None:
    """The half that is easy to get wrong: a column that barely moves agrees with itself at every offset,
    so "the declared offset matches" passes on exactly the data that cannot tell offsets apart."""
    flat = _bars().assign(open=1.0, high=1.0, low=1.0, close=1.0, quote_volume=1.0)

    result = verify_spot_contract(flat, flat)

    assert result.verdict == UNVERIFIABLE, result.reason
    assert admits_live_signal(SPOT_BASIS_COLUMN, result)[0] is False


def test_a_sample_shorter_than_a_day_refuses_to_answer_instead_of_answering_weakly() -> None:
    """`measure_alignment`'s floor, quoted rather than re-picked: a fresh listing's handful of bars can
    put any offset on top by chance, and a verdict a sample cannot support is a number without a
    measurement behind it."""
    short = verify_spot_contract(_bars(SPOT_MIN_OVERLAP_BARS - 1), _bars(SPOT_MIN_OVERLAP_BARS - 1))

    assert short.verdict == UNVERIFIABLE
    assert verify_spot_contract(_bars(SPOT_MIN_OVERLAP_BARS), _bars(SPOT_MIN_OVERLAP_BARS)).verdict == PASS


def test_the_columns_are_prefixed_so_a_new_spot_field_cannot_escape_the_contract() -> None:
    """`CONTRACTS` is a FLAT table keyed by bare name, so a raw 'close' would claim the word for the
    PERPETUAL's own close.  The frame renames on the way in and keeps the stamp exactly as it arrived."""
    framed = spot_verification_frame(_bars())

    assert list(framed.columns) == [SPOT.archive.column, *SPOT_COLUMNS]
    assert framed[SPOT.archive.column].tolist() == _bars()["open_time"].tolist()
    with pytest.raises(KeyError, match="open_time"):
        spot_verification_frame(_bars().drop(columns=["open_time"]))


# --- the record --------------------------------------------------------------------------------------


def test_a_stored_verdict_is_re_derived_rather_than_believed(tmp_path: Path) -> None:
    """`rederive_verdict` is a second implementation of `verify_stamp_offset`'s conclusion, on purpose:
    a checker that reuses the writer's own answer checks nothing.  Held against it here so the copy
    cannot drift - both directions, so neither is allowed to become permissive alone."""
    for archive, rest in (
        (_bars(), _bars()),
        (_bars(), _bars().assign(open_time=lambda frame: frame["open_time"] + HOUR_MS)),
        (_bars().assign(close=1.0, open=1.0, high=1.0, low=1.0, quote_volume=1.0),) * 2,
        (_bars(12), _bars(12)),
    ):
        measured = verify_spot_contract(archive, rest)
        assert rederive_verdict(measured)[0] == measured.verdict, measured.reason

    written = write_spot_verification(tmp_path, verify_spot_contract(_bars(), _bars()), {"symbol": "BTCUSDT"})
    assert written.name == SPOT_VERIFICATION_FILE
    restored = read_spot_verification(tmp_path)
    assert restored is not None and restored.verdict == PASS
    assert restored.compared == 60 and set(restored.compared_columns) == set(SPOT_COLUMNS)
    assert "symbol=BTCUSDT" in restored.reason, "a reader must be able to see WHAT was measured"


def test_a_record_whose_own_numbers_refute_it_is_not_admitted(tmp_path: Path) -> None:
    """The reverse control, and the reason the reader re-derives at all.  `spot_alignment.json` sits in
    the data root where an operator can edit it, and `LiveEngine.__init__` says no edit may open this
    gate - so a PASS whose counts do not support it has to close it again."""
    write_spot_verification(tmp_path, verify_spot_contract(_bars(), _bars()))
    path = tmp_path / SPOT_VERIFICATION_FILE
    original = json.loads(path.read_text(encoding="utf-8"))

    for mutation, expected in (
        ({"rivals": []}, UNVERIFIABLE),  # nothing was refuted, so the match shows nothing
        ({"rivals": [{"rest_offset_ms": HOUR_MS, "matched": 59, "compared": 59}]}, UNVERIFIABLE),  # rival unrefuted
        ({"matched": 59}, FAIL),  # a row disagreed
        ({"compared": 12, "matched": 12}, UNVERIFIABLE),  # too little to answer
    ):
        payload = json.loads(json.dumps(original))
        payload["verification"].update(mutation)
        assert payload["verification"]["verdict"] == PASS, "the tamper has to leave the CLAIM in place"
        path.write_text(json.dumps(payload), encoding="utf-8")

        restored = read_spot_verification(tmp_path)

        assert restored is not None and restored.verdict == expected
        assert "the record claims PASS" in restored.reason
        assert admits_live_signal(SPOT_BASIS_COLUMN, restored)[0] is False


def test_a_missing_or_foreign_record_reads_as_no_measurement_rather_than_as_a_pass(tmp_path: Path) -> None:
    """`None` and a refusing `Verification` are different facts; both refuse, and the reason says which."""
    assert read_spot_verification(tmp_path) is None
    assert admits_live_signal(SPOT_BASIS_COLUMN, None)[0] is False

    (tmp_path / SPOT_VERIFICATION_FILE).write_text('{"contract": "metrics"}', encoding="utf-8")
    foreign = read_spot_verification(tmp_path)
    assert foreign is not None and foreign.verdict == UNVERIFIABLE and "metrics" in foreign.reason

    (tmp_path / SPOT_VERIFICATION_FILE).write_text("not json at all", encoding="utf-8")
    broken = read_spot_verification(tmp_path)
    assert broken is not None and broken.verdict == UNVERIFIABLE
    assert admits_live_signal(SPOT_BASIS_COLUMN, broken)[0] is False


# --- the command that takes it ------------------------------------------------------------------------


class _FakeArchive:
    """The monthly archive, answering for whichever (symbol, month) the test put in it; 404 is `None`."""

    def __init__(self, months: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.months = months
        self.asked: list[tuple[str, str, str]] = []

    def __enter__(self) -> _FakeArchive:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def fetch_month(self, symbol: str, interval: str, month: Month, market: str = "futures/um") -> pd.DataFrame | None:
        assert market == SPOT_MARKET, "the spot ingest must not read the futures archive"
        self.asked.append((symbol, str(month), market))
        return self.months.get((symbol, str(month)))


class _FakeSpotVenue:
    """`SpotClient` reduced to what the ingest calls: the clock, the listing, and a range of klines."""

    def __init__(self, url: str = "", *, frame: pd.DataFrame | None = None) -> None:
        self.frame = _bars() if frame is None else frame

    def __enter__(self) -> _FakeSpotVenue:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def server_time_ms(self) -> int:
        return NOW_MS

    def listed_symbols(self, status: str = "TRADING") -> set[str]:
        return {"BTCUSDT"}

    def klines_range(
        self, symbol: str, interval: str, start_ms: int | None = None, end_ms: int | None = None
    ) -> pd.DataFrame:
        rows = self.frame
        if start_ms is not None:
            rows = rows[rows["open_time"] >= start_ms]
        if end_ms is not None:
            rows = rows[rows["open_time"] < end_ms]
        return rows.reset_index(drop=True)


def _run_data_spot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive: _FakeArchive) -> tuple[int, str]:
    """`starquant data spot` against the fakes, on a root that already holds the perpetual's own bars."""
    KlineStore(tmp_path).append("BTCUSDT", "1h", _bars())
    monkeypatch.setattr("starquant_cli.data_cmd.ArchiveClient", lambda *a, **k: archive)
    monkeypatch.setattr("starquant_cli.data_cmd.SpotClient", _FakeSpotVenue)
    result = CliRunner().invoke(
        main,
        ["data", "spot", "--root", str(tmp_path), "--symbols", "BTCUSDT", "--start", "2026-08"],
    )
    return result.exit_code, result.output


def test_the_ingest_measures_the_stamp_contract_and_writes_what_the_live_gate_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end, because every piece of this existed and the end was never joined up.

    The command is the only place that has the archive and REST open at once, which is why the
    measurement belongs here rather than in a script somebody remembers to run.
    """
    archive = _FakeArchive({("BTCUSDT", "2026-08"): _bars()})

    code, output = _run_data_spot(tmp_path, monkeypatch, archive)

    assert code == 0, output
    assert "spot contract: PASS" in output
    assert (tmp_path / SPOT_VERIFICATION_FILE).exists()
    record = json.loads((tmp_path / SPOT_VERIFICATION_FILE).read_text(encoding="utf-8"))
    assert record["contract"] == "spot" and record["symbol"] == "BTCUSDT" and record["sample"] == "2026-08"
    assert KlineStore(tmp_path, kind=SPOT_KLINE_KIND).exists("BTCUSDT", "1h"), "the bars themselves are the point too"

    # The gate this whole path exists to open, asked exactly as `LiveEngine._startup` asks it.
    assert spot_refusal(needs_spot=["mined_abc"], verification=read_spot_verification(tmp_path)) is None


def test_a_month_the_archive_never_published_leaves_the_gate_shut_rather_than_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Could not measure" is not "measured fine".  A run that cannot sample says so and writes nothing,
    so a root whose ingest half-worked refuses a basis strategy exactly like one that never ran."""
    code, output = _run_data_spot(tmp_path, monkeypatch, _FakeArchive({}))

    assert code == 0, output  # the ingest itself succeeded through the REST tail
    assert "spot contract: NOT MEASURED" in output
    assert not (tmp_path / SPOT_VERIFICATION_FILE).exists()
    assert read_spot_verification(tmp_path) is None

    refusal = spot_refusal(needs_spot=["mined_abc"], verification=read_spot_verification(tmp_path))
    assert refusal is not None and "no verification on record" in refusal


def test_the_daily_data_job_runs_the_ingest_that_produces_all_of_this() -> None:
    """The 2026-09-09 lesson in one assertion: a command nothing schedules is a command nobody runs.

    `.starquant/data/` held no `spot_klines/` and no `spot_map.json` on the day DL-D5 was declared shipped,
    because `deploy/run_data.sh` synced klines and funding and never mentioned spot.
    """
    script = (Path(__file__).resolve().parents[2] / "deploy/run_data.sh").read_text(encoding="utf-8")
    # The lines that RUN something, not the ones that explain it - a comment naming the command is how
    # this defect looked from the outside for a whole round.
    invoked = [
        line.split("data ", 1)[1].split()[0] for line in script.splitlines() if line.startswith('"$STARQUANT" data ')
    ]

    assert "spot" in invoked, "nothing schedules the spot ingest"
    assert invoked.index("sync") < invoked.index("spot"), "it maps what the perp store holds"
