"""🟠 #2 of the 2026-09-13 review: the one out-of-sample series hangs on a file that could reset itself.

KILL-006 decided against a historical hold-out, and the whole of its reasoning is that live attribution
IS the clean out-of-sample.  M-010's 30-day window therefore rests on `state.json.last_income_ms` being
continuous - and `StateStore.load` answered a file it could not parse with a brand-new `LiveState()`:
no raise, no alert, no row.  Three things follow from that one line, and every one of them is silent:

* `last_income_ms` becomes `None`, `engine._ingest_income` reads `since = ... or now`, the window is
  `[now, now]`, and every income row earned while the loop was down never enters `attribution.jsonl` -
  never, because nothing re-queries an old window.  `decay_watch` sees `live_windows` get SHORTER,
  which is indistinguishable from a loop that simply ran for less time.
* `equity_hwm` restarts at the current equity, so the drawdown reads 0 and D-015's throttle and R8's
  ladder go blind together.
* `exit_states` and `last_contributions` go with them (entry anchors rebuilt from the venue's VWAP,
  D-005's hold seed zeroed once).

And the file could be half-written in the first place: `_atomic_write` was tmp + `replace` with no
fsync, six lines under an `_append` whose comment explains why a ledger row is fsynced.  `replace`
makes the RENAME atomic and promises nothing about the tmp file's contents having left the page cache.

These tests are the three answers: refuse, fsync, and say so when the watermark is gone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.state import LiveState, StateStore, StateUnreadable
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices


class _RecordingAlerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    @property
    def enabled(self) -> bool:
        return True

    def clear(self, key: str) -> None:
        pass

    async def send(self, text: str, *, key: str | None = None, force: bool = False) -> bool:
        self.sent.append((text, key))
        return True


# --- A1: a missing file and an unreadable one are different answers ---------------------------


def test_a_missing_state_file_is_still_an_honest_first_start(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "live").load()

    assert state.cycles == 0
    assert state.last_income_ms is None


@pytest.mark.parametrize(
    "payload",
    [
        '{"cycles": 41, "last_income_ms": 1789',  # truncated: the shape a crash mid-write leaves
        "",  # zero length: what a tmp file published before its bytes were flushed looks like
        "[]",  # valid JSON, wrong shape
        "null",
    ],
)
def test_a_state_file_that_will_not_parse_refuses_instead_of_starting_fresh(tmp_path: Path, payload: str) -> None:
    store = StateStore(tmp_path / "live")
    store.state_path.write_text(payload, encoding="utf-8")

    with pytest.raises(StateUnreadable) as raised:
        store.load()

    message = str(raised.value)
    # The message is the operator's whole path out of this, so it is asserted rather than assumed.
    assert "last_income_ms" in message, "it has to say what would have been lost"
    assert str(store.state_path) in message
    assert ".bad" in message and "mv " in message, "an explicit rebuild, not a silent one"


def test_the_engine_will_not_construct_on_an_unreadable_state(
    august_panel: Panel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`starquant live run` builds the engine before it trades, so the refusal lands at startup."""
    store = StateStore(tmp_path / "live")
    store.state_path.write_text('{"cycles": 41', encoding="utf-8")
    market = FakeMarketData(august_panel, 400)

    with pytest.raises(StateUnreadable):
        LiveEngine(
            _config(tmp_path),
            model=_model(),
            market=market,
            venue=FakeVenue(balance=10_000.0, prices=_prices(august_panel, 400)),
            clock=FakeClock(market.bar_open_ms(400) + 5_000),
            store=StateStore(tmp_path / "live"),
        )


def test_a_state_file_written_by_this_store_still_loads(tmp_path: Path) -> None:
    """The refusal must not be reachable from a file we wrote ourselves."""
    store = StateStore(tmp_path / "live")
    store.save(LiveState(cycles=7, last_income_ms=1_789_016_400_000, equity_hwm=10_123.4))

    reloaded = store.load()

    assert (reloaded.cycles, reloaded.last_income_ms, reloaded.equity_hwm) == (7, 1_789_016_400_000, 10_123.4)


# --- A2: the same durability standard `_append` has had since L1-14 --------------------------


def test_the_state_write_is_on_the_disk_before_save_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tmp -> fsync -> replace -> fsync the directory.  `replace` alone only renames."""
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    store = StateStore(tmp_path / "live")
    store.save(LiveState(cycles=3))

    assert len(synced) >= 2, "the tmp file and the directory that now names it"
    assert json.loads(store.state_path.read_text(encoding="utf-8"))["cycles"] == 3
    assert not list((tmp_path / "live").glob("*.tmp")), "the tmp file is consumed by the rename"


def test_the_heartbeat_write_is_held_to_the_same_standard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])

    StateStore(tmp_path / "live").heartbeat({"phase": "STARTED"})

    assert len(synced) >= 2


# --- A3: `None` on a loop that has already run is a LOSS, not a first start -------------------


async def _world(august_panel: Panel, tmp_path: Path, seed: LiveState | None = None) -> dict[str, Any]:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    if seed is not None:
        store.save(seed)
    alerts = _RecordingAlerts()
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=clock,
        store=store,
        alerts=alerts,  # type: ignore[arg-type]
    )
    return {"engine": engine, "market": market, "alerts": alerts, "cursor": cursor}


async def test_a_lost_income_watermark_is_announced_and_written_onto_the_record(
    august_panel: Panel, tmp_path: Path
) -> None:
    """41 cycles of history and no watermark: that is a hole, and it has to be said at the moment it opens."""
    world = await _world(august_panel, tmp_path, seed=LiveState(cycles=41, last_income_ms=None))
    engine, alerts = world["engine"], world["alerts"]

    await engine.startup()
    record = await engine.run_cycle(world["market"].bar_open_ms(world["cursor"] - 1))

    keyed = [text for text, key in alerts.sent if key == "income-watermark-lost"]
    assert len(keyed) == 1, "once, under its own dedup key"
    assert "last_income_ms" in keyed[0] and "attribution.jsonl" in keyed[0]
    lost = record["external_flows"]["watermark_lost"]
    assert lost["lost"] is True
    assert lost["cycles"] == 41, "the record says how much history this loop had when the watermark went"


async def test_a_first_start_says_nothing(august_panel: Panel, tmp_path: Path) -> None:
    """The control.  `None` with no cycles behind it is the truth, and the loop must not cry about it."""
    world = await _world(august_panel, tmp_path)
    engine, alerts = world["engine"], world["alerts"]

    await engine.startup()
    record = await engine.run_cycle(world["market"].bar_open_ms(world["cursor"] - 1))

    assert [key for _, key in alerts.sent if key == "income-watermark-lost"] == []
    assert "watermark_lost" not in record["external_flows"]


async def test_the_loss_is_recorded_once_not_every_cycle(august_panel: Panel, tmp_path: Path) -> None:
    """One hole, one row.  Repeating it on every cycle would make a stale fact look like a new one."""
    world = await _world(august_panel, tmp_path, seed=LiveState(cycles=41, last_income_ms=None))
    engine, market, alerts = world["engine"], world["market"], world["alerts"]

    await engine.startup()
    first = await engine.run_cycle(market.bar_open_ms(world["cursor"] - 1))
    market.cursor += 1
    second = await engine.run_cycle(market.bar_open_ms(market.cursor - 1))

    assert "watermark_lost" in first["external_flows"]
    assert "watermark_lost" not in second["external_flows"]
    assert len([key for _, key in alerts.sent if key == "income-watermark-lost"]) == 1
