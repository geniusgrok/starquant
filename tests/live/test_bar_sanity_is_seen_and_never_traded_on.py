"""G6: the bars a cycle hands its model are checked for being prices at all - and nothing trades on it.

Four claims, each with its own tests:

1. **Real bad bars are caught, real good bars are not.**  BNXUSDT's 2023-02-22 redenomination and
   LUNAUSDT's 2022-05-12 halt are verbatim slices of the 1h archive (`tests/fixtures/bar_sanity/`,
   checked against the archive itself where it exists); the August 2026 panel is four real months of
   ordinary bars and must raise nothing.
2. **Each rule fires at its threshold and not below it**, one corrupted field at a time.
3. **The check never raises.**  A frame it cannot read costs that frame's reading; a failure of the
   whole pass is recorded, not propagated.
4. **It is alert only.**  Two engines on the same redenominated history, one with the check and one
   with it replaced by a no-op, place the same orders at the same targets.  And the daily report
   pages on a flag the day it is first seen, not on every day it sits in the window.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live import bar_sanity
from starquant_live.bar_sanity import FROZEN_BARS, MAX_LOG_RETURN, check_bars, sanity_findings, sanity_status
from starquant_live.engine import LiveConfig, LiveEngine
from starquant_live.guards import GuardParams
from starquant_live.inputs import model_inputs
from starquant_live.rebalancer import RebalanceParams
from starquant_live.reports import _day_of, daily_alerts, daily_markdown, daily_payload
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "bar_sanity"
SLICES = ("BNXUSDT_2023-02-22.json", "LUNAUSDT_2022-05-12.json")
BNX_BAR = 1_677_074_400_000  # 2023-02-22 14:00Z, the first bar after the 518-bar halt
HOUR = 3_600_000
FIELDS = ("open", "high", "low", "close", "volume")
AUGUST_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")  # the four `august_panel` loads


def _slice(name: str) -> tuple[str, pd.DataFrame]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return str(payload["symbol"]), pd.DataFrame(payload["rows"], columns=payload["columns"])


def _august(august_dir: Path) -> dict[str, pd.DataFrame]:
    return {symbol: pd.read_parquet(august_dir / symbol / "1h.parquet") for symbol in AUGUST_SYMBOLS}


def _of(reading: dict[str, Any], check: str) -> list[dict[str, Any]]:
    return [flag for flag in reading["flags"] if flag["check"] == check]


# --- 1. real bars -------------------------------------------------------------------------------------


def test_the_bnx_redenomination_in_the_archive_is_flagged() -> None:
    symbol, frame = _slice("BNXUSDT_2023-02-22.json")

    reading = check_bars({symbol: frame})

    assert reading["counts"] == {"ohlc": 0, "frozen": 0, "jump": 1}
    [flag] = _of(reading, "jump")
    assert flag["open_time"] == BNX_BAR
    assert flag["log_return"] == pytest.approx(math.log(1.552 / 85.59), abs=1e-4), "x1/55 in one bar"
    assert flag["gap_bars"] == 518, "the halt it came back from"
    assert flag["continuous"] is False, "no trade bridged the two closes - which is what makes it an artifact"


def test_lunas_halt_on_a_member_day_is_one_frozen_run_and_its_crash_hours_read_as_real() -> None:
    symbol, frame = _slice("LUNAUSDT_2022-05-12.json")

    reading = check_bars({symbol: frame})

    assert [(f["bars"], f["price"]) for f in _of(reading, "frozen")] == [(15, 0.008)]
    jumps = _of(reading, "jump")
    assert jumps, "LUNA fell x0.30-x0.49 per hour before the halt"
    assert all(flag["continuous"] for flag in jumps), "those hours traded: the flag must say so"


def test_four_real_months_of_ordinary_bars_raise_nothing(august_dir: Path) -> None:
    frames = _august(august_dir)

    reading = check_bars(frames)

    assert reading["counts"] == {"ohlc": 0, "frozen": 0, "jump": 0}
    assert reading["errors"] == {} and reading["flags"] == []
    assert reading["symbols"] == 4 and reading["bars"] == sum(len(frame) for frame in frames.values())


def test_a_panel_shaped_frame_reads_the_same_as_a_feed_shaped_one(august_panel: Panel, august_dir: Path) -> None:
    """The feed hands `open_time` columns; the test fakes hand a panel's DatetimeIndex.  Same answer."""
    symbol = "BTCUSDT"
    feed = _august(august_dir)[symbol].copy()
    feed.loc[400:, ["open", "high", "low", "close"]] /= 55.0
    panel_shaped = pd.DataFrame({f: feed[f].to_numpy() for f in FIELDS}, index=august_panel.close.index)

    assert check_bars({symbol: feed})["flags"] == check_bars({symbol: panel_shaped})["flags"]


@pytest.mark.skipif(
    not (ROOT / ".starquant" / "data" / "klines").exists(),
    reason="the archive is not in this checkout (CI and worktrees)",
)
@pytest.mark.parametrize("name", SLICES)
def test_the_fixtures_are_the_archive_verbatim(name: str) -> None:
    """A fixture nobody can compare to its source is a fixture someone could have made up."""
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    archive = pd.read_parquet(ROOT / payload["source"])
    rows = archive[archive["open_time"].between(payload["open_time_from"], payload["open_time_to"])]
    _, fixture = _slice(name)

    assert list(rows.columns) == payload["columns"] and len(rows) == len(fixture)
    for column in payload["columns"]:
        assert (rows[column].to_numpy() == fixture[column].to_numpy()).all(), column


# --- 2. each rule at its threshold --------------------------------------------------------------------


def _btc(august_dir: Path) -> pd.DataFrame:
    return _august(august_dir)["BTCUSDT"].copy()


@pytest.mark.parametrize(
    ("field", "move", "reason"),
    [
        ("low", lambda o, h, lo, c: min(o, c) * 1.0001, "low_above_body"),
        ("high", lambda o, h, lo, c: max(o, c) * 0.9999, "high_below_body"),
        ("open", lambda o, h, lo, c: 0.0, "non_positive"),
        ("close", lambda o, h, lo, c: float("nan"), "non_finite"),
    ],
)
def test_a_bar_that_contradicts_itself_is_flagged(august_dir: Path, field: str, move: Any, reason: str) -> None:
    frame = _btc(august_dir)
    o, h, lo, c = (float(frame.at[300, name]) for name in ("open", "high", "low", "close"))
    frame.at[300, field] = move(o, h, lo, c)

    [flag] = _of(check_bars({"BTCUSDT": frame}), "ohlc")

    assert flag["open_time"] == int(frame.at[300, "open_time"]) and reason in flag["reasons"]


def test_a_frozen_run_needs_frozen_bars_in_a_row(august_dir: Path) -> None:
    def frozen_for(length: int) -> list[dict[str, Any]]:
        frame = _btc(august_dir)
        price = float(frame.at[299, "close"])
        frame.loc[300 : 300 + length - 1, ["open", "high", "low", "close"]] = price
        frame.loc[300 : 300 + length - 1, "volume"] = 0.0
        return _of(check_bars({"BTCUSDT": frame}), "frozen")

    assert FROZEN_BARS == 2
    assert frozen_for(1) == [], "one flat, empty hour is the venue-wide 2024-10-28 20:00 shape"
    [flag] = frozen_for(2)
    assert flag["bars"] == 2 and flag["open_time"] == int(_btc(august_dir).at[300, "open_time"])


@pytest.mark.parametrize(("factor", "flagged"), [(1 + 1e-6, True), (1 - 1e-6, False)])
def test_a_jump_is_flagged_above_ln_2_and_not_below(august_dir: Path, factor: float, flagged: bool) -> None:
    """Every price from bar 300 on is rescaled, so exactly one close-to-close ratio is 2x (1 +- 1e-6)."""
    frame = _btc(august_dir)
    scale = 2.0 * factor * float(frame.at[299, "close"]) / float(frame.at[300, "close"])
    frame.loc[300:, ["open", "high", "low", "close"]] *= scale

    jumps = _of(check_bars({"BTCUSDT": frame}), "jump")

    assert math.isclose(MAX_LOG_RETURN, math.log(2.0), rel_tol=0.0, abs_tol=1e-12)
    assert [flag["open_time"] for flag in jumps] == ([int(frame.at[300, "open_time"])] if flagged else [])


# --- 3. never raises ----------------------------------------------------------------------------------


def test_a_frame_it_cannot_read_costs_only_that_frames_reading(august_dir: Path) -> None:
    frames: dict[str, Any] = dict(_august(august_dir))
    frames["NOVOLUME"] = frames["BTCUSDT"].drop(columns=["volume"])
    frames["NOTAFRAME"] = None

    reading = check_bars(frames)

    assert set(reading["errors"]) == {"NOVOLUME", "NOTAFRAME"}
    assert "KeyError" in reading["errors"]["NOVOLUME"]
    assert reading["bars"] == sum(len(frames[s]) for s in AUGUST_SYMBOLS), "the readable frames were still read"


def test_an_internal_failure_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch, august_dir: Path) -> None:
    def boom(*_args: Any) -> list[dict[str, Any]]:
        raise RuntimeError("a bug in a rule")

    monkeypatch.setattr(bar_sanity, "_jump_flags", boom)
    per_frame = check_bars(_august(august_dir))
    assert set(per_frame["errors"]) == set(AUGUST_SYMBOLS)
    assert all("RuntimeError: a bug in a rule" in text for text in per_frame["errors"].values())

    whole = check_bars(_august(august_dir), interval="7x")  # the pass itself cannot start
    assert whole["error"].startswith("ValueError") and "flags" not in whole


async def test_model_inputs_still_returns_the_bars_when_the_check_fails(
    monkeypatch: pytest.MonkeyPatch, august_panel: Panel
) -> None:
    def boom(*_args: Any) -> list[dict[str, Any]]:
        raise RuntimeError("a bug in a rule")

    monkeypatch.setattr(bar_sanity, "_check_frame", boom)
    market = FakeMarketData(august_panel, 400)

    inputs = await model_inputs(market, _model(), list(AUGUST_SYMBOLS), "1h", 300)

    assert set(inputs.bars) == set(AUGUST_SYMBOLS) and all(len(frame) == 300 for frame in inputs.bars.values())
    assert set(inputs.sanity["errors"]) == set(AUGUST_SYMBOLS)
    assert "sanity" not in json.dumps(inputs.to_dict()), "`inputs` keeps its shape in the cycle row"


# --- 4a. alert only: the engine records it and trades exactly as without it -------------------------------


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )


async def _one_cycle(panel: Panel, directory: Path) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(panel, cursor)
    prices = {s: float(panel.close[s].iloc[cursor - 1]) for s in AUGUST_SYMBOLS}
    store = StateStore(directory / "live")
    config = LiveConfig(  # type: ignore[arg-type]
        interval="1h",
        history_bars=300,
        universe=tuple(AUGUST_SYMBOLS),
        leverage=2,
        rebalance=RebalanceParams(no_trade_band=0.002),
        guards=GuardParams(),
        kill_switch_path=directory / "KILL_SWITCH",
        strategy_weights={"tsmom": 1.0},
        poll_interval_seconds=0.0,
        grace_seconds=1.0,
    )
    engine = LiveEngine(
        config,
        model=_model(),
        market=market,
        venue=FakeVenue(balance=10_000.0, prices=prices),
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=store,
    )
    await engine.startup()
    await engine.guarded_cycle(market.bar_open_ms(cursor - 1))
    return store.read_jsonl(store.cycles_path)[-1]


@pytest.fixture
def redenominated(august_dir: Path) -> tuple[Panel, int]:
    """BTCUSDT divided by 55 from bar 350 on - BNX's ratio, inside the 300-bar window a cycle at 400 reads."""
    frames = _august(august_dir)
    frames["BTCUSDT"].loc[350:, ["open", "high", "low", "close"]] /= 55.0
    return Panel.from_frames(frames, interval="1h"), int(frames["BTCUSDT"].at[350, "open_time"])


async def test_a_cycle_records_what_the_check_saw(tmp_path: Path, redenominated: tuple[Panel, int]) -> None:
    panel, bar = redenominated

    row = await _one_cycle(panel, tmp_path)

    assert row["bar_sanity"]["symbols"] == 4 and row["bar_sanity"]["counts"] == {"ohlc": 0, "frozen": 0, "jump": 1}
    [flag] = row["bar_sanity"]["flags"]
    assert (flag["symbol"], flag["open_time"]) == ("BTCUSDT", bar)


async def test_the_check_changes_no_target_and_no_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redenominated: tuple[Panel, int]
) -> None:
    """The same redenominated history with the check, and with the check replaced by a no-op."""
    panel, _ = redenominated
    with_check = await _one_cycle(panel, tmp_path / "with")
    monkeypatch.setattr("starquant_live.inputs.check_bars", lambda *_args: {})
    without = await _one_cycle(panel, tmp_path / "without")

    assert with_check["bar_sanity"]["counts"]["jump"] == 1 and without["bar_sanity"] == {}
    assert with_check["orders"], "a cycle that placed nothing would make this comparison empty"
    assert with_check["targets"] == without["targets"]
    assert with_check["orders"] == without["orders"]


async def test_a_check_that_fails_inside_a_cycle_leaves_the_cycle_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, august_panel: Panel
) -> None:
    normal = await _one_cycle(august_panel, tmp_path / "normal")

    def boom(*_args: Any) -> list[dict[str, Any]]:
        raise RuntimeError("a bug in a rule")

    monkeypatch.setattr(bar_sanity, "_check_frame", boom)
    broken = await _one_cycle(august_panel, tmp_path / "broken")

    assert "error" not in broken and broken.get("phase") != "ERROR", "the cycle completed"
    assert set(broken["bar_sanity"]["errors"]) == set(AUGUST_SYMBOLS)
    assert (broken["targets"], broken["orders"]) == (normal["targets"], normal["orders"])


# --- 4b. the report pages once per flag ---------------------------------------------------------------


def _row(day_ms: int, reading: dict[str, Any]) -> dict[str, Any]:
    return {"bar_open_ms": day_ms, "equity": 10_000.0, "targets": {}, "orders": [], "bar_sanity": reading}


def test_a_flag_pages_on_the_day_it_is_first_seen_and_not_after(tmp_path: Path) -> None:
    """Through `daily_payload` and `daily_alerts`, on what `check_bars` really returns for BNX."""
    symbol, frame = _slice("BNXUSDT_2023-02-22.json")
    reading = check_bars({symbol: frame})
    store = StateStore(tmp_path)
    first = 1_789_430_400_000  # 2026-09-15T00:00Z
    for hour in range(3):
        store.append_cycle(_row(first + hour * HOUR, reading))
    store.append_cycle(_row(first + 86_400_000, reading))  # the next day: still in the window

    day_one = daily_payload(store, "2026-09-15")
    alerts, _notices = daily_alerts(day_one)
    [page] = [text for text in alerts if "bar sanity" in text]
    assert "BNXUSDT" in page and "缺 518 根" in page and "今天首次出现 1 处" in page
    assert day_one["bar_sanity"]["cycles"] == 3 and len(day_one["bar_sanity"]["new"]) == 1
    assert "Bar sanity (G6, alert only)" in daily_markdown(day_one)

    day_two = daily_payload(store, "2026-09-16")
    assert day_two["bar_sanity"]["new"] == [] and day_two["bar_sanity"]["standing"] == 1
    assert not [text for text in daily_alerts(day_two)[0] if "bar sanity" in text], "seen yesterday: no page today"


def test_a_symbol_entering_the_pool_with_an_old_redenomination_still_pages() -> None:
    """The case "bars that closed today" would miss: the bar is from 2023, the first sighting is today."""
    symbol, frame = _slice("BNXUSDT_2023-02-22.json")
    today = 1_789_516_800_000  # 2026-09-16T00:00Z
    rows = [_row(today - 86_400_000, check_bars({})), _row(today, check_bars({symbol: frame}))]

    status = sanity_status(rows, "2026-09-16", day_of=_day_of)

    assert [flag["open_time"] for flag in status["new"]] == [BNX_BAR]


def test_a_check_that_could_not_run_is_a_notice_not_a_page() -> None:
    today = 1_789_516_800_000
    status = sanity_status([_row(today, {"error": "ValueError: boom", "seconds": 0.0})], "2026-09-16", day_of=_day_of)

    alerts, notices = sanity_findings(status)

    assert alerts == [] and len(notices) == 1 and "ValueError: boom" in notices[0]


def test_a_report_without_the_block_is_unchanged() -> None:
    """Every report written before G6, and every cycle before the loop restarts onto this code."""
    assert sanity_findings({}) == ([], [])
    assert daily_alerts({}) == ([], [])


def _lunas_day() -> dict[str, Any]:
    """LUNA's 2022-05-12 archive, first seen today: traded-through crash hours plus one frozen halt."""
    symbol, frame = _slice("LUNAUSDT_2022-05-12.json")
    today = 1_789_516_800_000  # 2026-09-16T00:00Z
    return sanity_status([_row(today, check_bars({symbol: frame}))], "2026-09-16", day_of=_day_of)


def test_a_jump_that_traded_through_is_a_notice_and_a_frozen_halt_still_pages() -> None:
    """Operator ruling 2026-09-23: a move that traded reads as a market and is read at review, not paged."""
    status = _lunas_day()
    jumps = [flag for flag in status["new"] if flag["check"] == "jump"]
    assert jumps and all(flag["continuous"] for flag in jumps)

    alerts, notices = sanity_findings(status)

    [page] = alerts
    assert "今天首次出现 1 处可疑 bar" in page and "OHLC 全等且零成交" in page, "the frozen halt still pages"
    assert "跳变" not in page, "no traded-through jump rides along in the page"
    [notice] = notices
    assert f"今天首次出现 {len(jumps)} 处有连续成交的跳变" in notice and "像真实行情" in notice


def test_traded_through_jumps_alone_page_nothing_and_a_gap_bridged_jump_still_does() -> None:
    lunas = _lunas_day()
    only_jumps = {**lunas, "new": [flag for flag in lunas["new"] if flag["check"] == "jump"]}
    assert sanity_findings(only_jumps)[0] == []

    symbol, frame = _slice("BNXUSDT_2023-02-22.json")
    today = 1_789_516_800_000
    bnx = sanity_status([_row(today, check_bars({symbol: frame}))], "2026-09-16", day_of=_day_of)
    assert [flag["continuous"] for flag in bnx["new"]] == [False]
    alerts, notices = sanity_findings(bnx)
    assert len(alerts) == 1 and "BNXUSDT" in alerts[0] and notices == [], "a re-denomination is not a market"
