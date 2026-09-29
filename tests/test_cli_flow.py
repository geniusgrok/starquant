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


class LiveFake(FakeVenue):
    """A venue whose clock is the real one, as the command line uses it."""

    def __init__(self, **snap_fields: object) -> None:
        super().__init__(_snap(**snap_fields))  # type: ignore[arg-type]
        self.snapshots = 0
        self.fail_after: int | None = None
        self.transport = None

    def snapshot(self) -> Snapshot:
        self.snapshots += 1
        if self.fail_after is not None and self.snapshots > self.fail_after:
            raise OSError("network down")
        now = int(time.time() * 1000)
        return dataclasses.replace(self.snap, server_time_ms=now, read_ms=now)

    def klines(self, *_a: object, **_k: object) -> list[object]:
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
    monkeypatch.setenv("STARQUANT_LOCK_DIR", str(tmp_path / "locks"))
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
