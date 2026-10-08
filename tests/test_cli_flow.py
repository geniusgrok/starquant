"""The native CLI with an in-process client and no exchange connection."""
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
        super().__init__(_snap(**snap_fields))
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


@pytest.fixture
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[LiveFake, Path]:
    venue = LiveFake()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("STARQUANT_ACCOUNT_UID", raising=False)
    monkeypatch.setenv("STARQUANT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("STARQUANT_DEMO_API_KEY", "key")
    monkeypatch.setenv("STARQUANT_DEMO_API_SECRET", "secret")
    monkeypatch.setattr(entry, "UsdMClient", lambda *_a, **_k: venue)
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


def test_default_cli_does_not_trade() -> None:
    import subprocess
    import sys

    code = """
import importlib, pkgutil, socket, urllib.request

def refuse(*args, **kwargs):
    raise AssertionError('default CLI contacted the network or an account')

socket.create_connection = urllib.request.urlopen = refuse
import btc_perp
for module in pkgutil.iter_modules(btc_perp.__path__, 'btc_perp.'):
    importlib.import_module(module.name)
import btc_perp.__main__ as entry
entry.UsdMClient = refuse
assert entry.main([]) == 0
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "不会下单" in result.stdout
    assert "生产增仓默认关闭" in result.stdout


def test_cli_refuses_to_run_without_keys(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from btc_perp.__main__ import main

    monkeypatch.delenv("STARQUANT_PROD_API_KEY", raising=False)
    monkeypatch.delenv("STARQUANT_PROD_API_SECRET", raising=False)
    code = main(["run", "--environment", "prod", "--max-notional-usdt", "10", "--once"])
    assert code == 2
    assert "STARQUANT_PROD_API_KEY" in capsys.readouterr().out
