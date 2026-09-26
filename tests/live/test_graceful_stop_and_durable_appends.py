"""DL-L6 / L1-14: stopping the loop should not be able to tear a record in half.

Two small things that only matter at the moment everything else is going wrong.

*Appends.*  ``_append`` wrote a JSON line to an open handle with no flush and no fsync.  A line is
written in one ``write`` call, so the tear is unlikely - but "unlikely" is not what an append-only
ledger is for, and these are the files the daily report, the attribution and every post-mortem read.
Flush and fsync cost nothing at one line an hour.

*SIGTERM.*  ``launchctl unload`` sends SIGTERM and then SIGKILLs after ExitTimeOut (30s in
deploy/com.starquant.live.plist).  Without a handler the loop dies wherever it happens to be, which
during a cycle means orders sent and not yet recorded.  With one it finishes the cycle it is in and
declines to start another - and the drill in DL-X2's place (`launchctl unload`) is exactly this
path, so it needs to be the tested one.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_live.state import StateStore


def test_an_appended_row_reaches_the_disk_immediately(tmp_path: Path) -> None:
    """No buffering: the row a post-mortem needs is the last one written before the crash."""
    store = StateStore(tmp_path)

    store.append_cycle({"phase": "OK", "bar_open_ms": 1})

    rows = [json.loads(line) for line in store.cycles_path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["phase"] == "OK"


def test_every_appended_row_is_complete_json(tmp_path: Path) -> None:
    store = StateStore(tmp_path)

    for i in range(50):
        store.append_trade({"symbol": "BTCUSDT", "i": i})

    lines = store.trades_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    assert all(json.loads(line)["i"] == i for i, line in enumerate(lines))


def test_a_stop_request_is_honoured_between_cycles() -> None:
    from starquant_live.engine import StopRequested

    stop = StopRequested()
    assert stop.requested is False

    stop.request("SIGTERM")

    assert stop.requested is True
    assert "SIGTERM" in stop.reason


def test_the_loop_finishes_its_cycle_before_it_stops() -> None:
    """A cycle sends orders and then records them; being killed between the two is the hazard."""
    import inspect

    from starquant_live.engine import LiveEngine

    source = inspect.getsource(LiveEngine.run)
    assert "stop.requested" in source


def test_the_handler_is_installed_by_the_cli_not_by_the_library() -> None:
    """Signal handlers are process-global; a library that installs one surprises its callers."""
    import inspect

    from starquant_cli import live_cmd
    from starquant_live import engine

    assert "SIGTERM" in inspect.getsource(live_cmd.live_run.callback)
    assert "signal.signal" not in inspect.getsource(engine)
