"""The command line entry, end to end, with an in-process client in place of the exchange.

These go through ``main``: argument handling, the state directory, the lock, the
run loop, the wind-down on every exit, ``run_state.json`` and the exit code.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path

import pytest
from test_forward import FakeVenue, _snap

import btc_perp.__main__ as entry
from btc_perp.model import Intent, Snapshot
from btc_perp.runner import CycleReport


class LiveFake(FakeVenue):
    """A venue whose clock is the real one, as the command line uses it."""

    def __init__(self, **snap_fields: object) -> None:
        super().__init__(_snap(**snap_fields))  # type: ignore[arg-type]
        self.snapshots = 0
        self.fail_after: int | None = None
        self.minutes: list[object] = []
        self.transport = None

    def snapshot(self) -> Snapshot:
        self.snapshots += 1
        if self.fail_after is not None and self.snapshots > self.fail_after:
            raise OSError("network down")
        now = int(time.time() * 1000)
        return dataclasses.replace(self.snap, server_time_ms=now, read_ms=now)

    def klines(self, interval: str = "1m", *_a: object, **_k: object) -> list[object]:
        if interval == "1m":
            return list(self.minutes)
        return []


class NoStream:
    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def start(self, *_a: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def keepalive(self, _now: int) -> None:
        pass

    def reconnect_if_due(self, *_a: object) -> None:
        pass

    def poll(self) -> tuple[tuple[object, ...], bool]:
        return (), False


@pytest.fixture
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[LiveFake, Path]:
    venue = LiveFake()
    monkeypatch.setenv("STARQUANT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("STARQUANT_DEMO_API_KEY", "key")
    monkeypatch.setenv("STARQUANT_DEMO_API_SECRET", "secret")
    monkeypatch.setattr(entry, "UsdMClient", lambda *_a, **_k: venue)
    monkeypatch.setattr(entry, "UserStream", NoStream)
    return venue, tmp_path / "state" / "demo"


def _state(state: Path) -> dict[str, object]:
    return json.loads((state / "run_state.json").read_text())


def test_run_once_winds_down_and_records_the_state(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _venue, state = wired
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    out = capsys.readouterr().out
    body = _state(state)
    assert body["phase"] == "stopped"
    assert isinstance(body["wind_down"], dict) and body["wind_down"]["verified"] is True
    assert "收尾：settled=true" in out
    assert code == 2  # no minutes were readable, so entries stayed frozen: not a clean "ready" exit
    modes = [json.loads(line).get("mode") for line in (state / "journal.jsonl").read_text().splitlines()]
    assert "run" in modes and "stop" in modes


def test_an_exception_in_the_loop_still_winds_down_and_names_the_failure(
    wired: tuple[LiveFake, Path],
) -> None:
    venue, state = wired
    venue.fail_after = 0
    with pytest.raises(OSError, match="network down"):
        entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    body = _state(state)
    assert body["phase"] == "stopped"
    assert "network down" in str(body["failure"])
    assert body["wind_down"] == "unverified" or body["wind_down"]["verified"] is False


def test_a_changed_config_with_an_open_intent_refuses_to_start(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _venue, state = wired
    entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    capsys.readouterr()
    from btc_perp.store import Store

    store = Store(state, "demo")
    store.insert_intent(
        Intent("en1", "enter", "unknown", "BUY", "1.0", False, False, "", "demo", int(time.time() * 1000), "", 1, False)
    )
    store.close()
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "150", "--once"])
    assert code == 2
    assert "未完成订单创建时不同" in capsys.readouterr().out
    assert _state(state)["phase"] == "not_started"


def test_stop_writes_a_scoped_request_and_reports_the_open_item(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    venue, state = wired
    venue.snap = dataclasses.replace(_snap(), position_qty=0.0)
    from btc_perp.store import Store

    store = Store(state, "demo")
    store.insert_intent(
        Intent("en2", "enter", "unknown", "BUY", "1.0", False, False, "", "demo", int(time.time() * 1000), "", 1, False)
    )
    store.close()
    code = entry.main(["stop", "--environment", "demo"])
    out = capsys.readouterr().out
    assert code == 2
    assert "en2" in out
    assert json.loads((state / "stop.request").read_text())["environment"] == "demo"
    assert entry.main(["resume", "--environment", "demo"]) == 0
    assert not (state / "stop.request").exists()


def test_the_wind_down_reports_unverified_when_it_cannot_read_the_account(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    venue, state = wired
    venue.fail_after = 1
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    assert code == 2
    assert "收尾没有完成" in capsys.readouterr().out
    body = _state(state)
    assert body["wind_down"] == "unverified" or body["wind_down"]["verified"] is False


def _pinned_stamp() -> float:
    """Five seconds after a minute boundary, so the previous close is fresh and the age is stable."""
    now_ms = int(time.time() * 1000)
    return ((now_ms // 60_000) * 60_000 + 5_000) / 1000


def _minute(now_ms: int) -> list[object]:
    open_ms = (now_ms // 60_000) * 60_000 - 60_000
    return [open_ms, "100", "100", "100", "100", "10", open_ms + 59_999, "1000000"]


def test_the_real_entry_uses_a_clock_that_moves(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command line does not pass a clock. A gate 45s after the read must not still call it fresh."""
    from btc_perp.model import Action

    venue, _state_dir = wired
    stamp = _pinned_stamp()
    monkeypatch.setattr(time, "time", lambda: stamp)
    venue.snap = dataclasses.replace(venue.snap, clock_offset_ms=0, clock_rtt_ms=1)
    venue.minutes = [_minute(int(stamp * 1000))]
    monkeypatch.setattr("btc_perp.runner.decide", lambda *_a, **_k: Action("enter", 1, 2.0, 0.0, 0.0, "probe"))
    monkeypatch.setattr("btc_perp.runner._wall_ms", lambda: int(stamp * 1000) + 45_000)
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    assert code == 2
    assert venue.market_ids == []
    assert "过期" in capsys.readouterr().out


def test_a_fast_cycle_on_the_same_entry_still_sends(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from btc_perp.model import Action

    venue, _state_dir = wired
    stamp = _pinned_stamp()
    monkeypatch.setattr(time, "time", lambda: stamp)
    venue.snap = dataclasses.replace(venue.snap, clock_offset_ms=0, clock_rtt_ms=1)
    venue.minutes = [_minute(int(stamp * 1000))]
    monkeypatch.setattr("btc_perp.runner.decide", lambda *_a, **_k: Action("enter", 1, 2.0, 0.0, 0.0, "probe"))
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    assert venue.market_ids
    assert "过期" not in capsys.readouterr().out
    assert code == 0  # a healthy run and settled stop are a successful one-shot session


def test_a_failed_wind_down_after_a_clean_cycle_is_not_exit_zero(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, state = wired
    stamp = _pinned_stamp()
    monkeypatch.setattr(time, "time", lambda: stamp)
    venue.snap = dataclasses.replace(venue.snap, clock_offset_ms=0, clock_rtt_ms=1)
    venue.minutes = [_minute(int(stamp * 1000))]
    venue.fail_after = 1
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    assert code == 2
    assert "收尾没有完成" in capsys.readouterr().out
    assert _state(state)["wind_down"] == "unverified"


def test_flatten_of_a_quiet_account_exits_zero(
    wired: tuple[LiveFake, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _venue, state = wired
    code = entry.main(["flatten", "--environment", "demo"])
    out = capsys.readouterr().out
    assert code == 0
    assert "settled=true" in out
    body = _state(state)
    assert isinstance(body["wind_down"], dict) and body["wind_down"]["verified"] is True


@pytest.mark.parametrize("also_stop", [False, True])
def test_run_handles_flatten_request_before_stop_and_exits(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch, also_stop: bool
) -> None:
    _venue, state = wired
    state.mkdir(parents=True)
    (state / "flatten.request").write_text(json.dumps({"environment": "demo"}))
    if also_stop:
        (state / "stop.request").write_text(json.dumps({"environment": "demo"}))
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: pytest.fail("清仓处理后不应再睡眠或重复执行"))

    assert entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200"]) == 0
    assert _state(state)["wind_down"]["verified"] is True
    modes = [json.loads(line).get("mode") for line in (state / "journal.jsonl").read_text().splitlines()]
    assert modes.count("flatten") == 1
    assert "stop" not in modes


@pytest.mark.parametrize("control", ["stop", "flatten"])
def test_operator_request_skips_strategy_market_fetch(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch, control: str
) -> None:
    venue, state = wired
    state.mkdir(parents=True)
    (state / f"{control}.request").write_text(json.dumps({"environment": "demo"}))
    monkeypatch.setattr(venue, "klines", lambda *_a, **_k: pytest.fail("控制请求不能排在行情分页后面"))

    assert entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"]) == 0
    modes = [json.loads(line).get("mode") for line in (state / "journal.jsonl").read_text().splitlines()]
    assert control in modes and "run" not in modes


def test_requested_flatten_cannot_succeed_only_because_subsequent_stop_settles(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _venue, state = wired
    monkeypatch.setattr(
        entry,
        "_one_cycle",
        lambda *_args: CycleReport(
            "flatten", True, "未平仓", (), 1.0, False, (), settled=False, remaining=("仍有持仓",)
        ),
    )
    monkeypatch.setattr(
        entry,
        "_wind_down",
        lambda *_args: CycleReport("stop", True, "安全停机", (), 1.0, True, (), settled=True),
    )
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: pytest.fail("清仓未完成也应退出并报告"))

    assert entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200"]) == 2
    assert _state(state)["exit_code"] == 2


@pytest.mark.parametrize("interval", ["0", "5.01", "3600"])
def test_unresponsive_poll_interval_is_rejected(interval: str) -> None:
    with pytest.raises(SystemExit) as exc:
        entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--poll-seconds", interval])
    assert exc.value.code == 2


def test_interrupt_with_a_confirmed_stop_is_named_apart_from_an_unconfirmed_one() -> None:
    from btc_perp.__main__ import _interrupt_line
    from btc_perp.runner import CycleReport

    done = CycleReport("stop", True, "", (), 0.0, True, (), settled=True)
    assert _interrupt_line(done) == "用户中断，收尾已确认"
    assert _interrupt_line(None) == "用户中断，收尾未确认"


def test_second_interrupt_during_cleanup_records_unverified_and_releases_lock(
    wired: tuple[LiveFake, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _venue, state = wired

    def interrupted(*_args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(entry, "_wind_down", interrupted)
    code = entry.main(["run", "--environment", "demo", "--max-notional-usdt", "200", "--once"])
    assert code == 2
    body = _state(state)
    assert body["phase"] == "stopped" and body["exit_code"] == 2
    assert body["wind_down"] == "unverified"
    from btc_perp.store import Store

    with Store(state, "demo"):
        pass
