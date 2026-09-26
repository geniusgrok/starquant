"""2026-09-09: §3 says the main book keeps its P&L stop, and nothing computed one.

`probes_from_registry` excluded `MAIN_BOOK` unconditionally, with no comment and no test.  So the
book that carries the whole `fraction` had its 30-day trailing attributed P&L not merely un-acted-on
but never CALCULATED - and what a rule cannot see it cannot bound.

The semantics are §3's, not the engine's existing stop.  §3 gives the two transitions different
channels on purpose: `probe -> retired` is "快：`stopped_books`" and `main -> probe` is not.  Halting
a probe IS the control; halting a `fraction` 1.0 book is switching the strategy off, and §3 says a
main sleeve that fires is demoted and recounts.  So main's stop reports and moves the lifecycle; it
does not empty the book.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from starquant_alpha.registry import parse_registry
from starquant_live.probe import ProbeParams, probes_from_registry

MAIN_WITH_STOP = {
    "version": 1,
    "books": {"flow_short": {"fraction": 1 / 3}},
    "strategies": [
        {"id": "tsmom", "enabled": True, "params": {}, "probe": {"stop": {"window_days": 30, "max_loss": 0.06}}},
        {"id": "flow", "enabled": True, "book": "flow_short", "params": {}, "probe": {"stop": {"max_loss": 0.02}}},
    ],
}
MAIN_WITHOUT = {
    "version": 1,
    "strategies": [{"id": "tsmom", "enabled": True, "params": {}}],
}


def test_the_main_book_is_watched_when_it_carries_a_stop() -> None:
    books = {p.book: p for p in probes_from_registry(parse_registry(MAIN_WITH_STOP))}
    assert set(books) == {"main", "flow_short"}
    assert books["main"].max_loss == 0.06
    assert books["flow_short"].max_loss == 0.02


def test_a_main_book_with_no_stop_block_is_still_skipped() -> None:
    """Absent knowledge is not a threshold; every registry written before today keeps behaving."""
    assert probes_from_registry(parse_registry(MAIN_WITHOUT)) == ()


def test_the_main_stop_reports_and_the_probe_stop_halts() -> None:
    """The distinction §3 draws, and the whole reason this is not one flag for both."""
    books = {p.book: p for p in probes_from_registry(parse_registry(MAIN_WITH_STOP))}
    assert books["main"].halts is False
    assert books["flow_short"].halts is True


def test_the_registry_can_ask_for_a_halt_explicitly() -> None:
    """Turning main's stop into a hard halt is a decision, so it is a field a person sets."""
    payload = {
        **MAIN_WITH_STOP,
        "strategies": [
            {
                "id": "tsmom",
                "enabled": True,
                "params": {},
                "probe": {"stop": {"window_days": 30, "max_loss": 0.06, "halts": True}},
            }
        ],
    }
    books = {p.book: p for p in probes_from_registry(parse_registry(payload))}
    assert books["main"].halts is True


@pytest.mark.asyncio
async def test_a_firing_main_book_is_not_removed_from_the_model(tmp_path: Any) -> None:
    """The behaviour that matters: it fires, it is recorded, and the book keeps trading."""
    from starquant_live.engine import LiveEngine
    from starquant_live.state import LiveState, StateStore

    class _Alerts:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, message: str) -> None:
            self.sent.append(message)

    class _Clock:
        def now_ms(self) -> int:
            return 1_788_919_200_000

    engine = LiveEngine.__new__(LiveEngine)
    engine.config = type(
        "C", (), {"probes": (ProbeParams(book="main", strategy="tsmom", max_loss=0.0, halts=False),)}
    )()
    engine.store = StateStore(tmp_path)
    engine.state = LiveState(last_equity=10_000.0)
    engine.clock = _Clock()
    engine.alerts = _Alerts()
    engine.model = object()
    sentinel = engine.model

    engine.store.append_attribution(
        {
            "at": "2026-09-09T02:00:00+00:00",
            "until_ms": 1_788_919_200_000,
            "basis": "net_exposure",
            "by_strategy": {"tsmom": -500.0},
        }
    )
    statuses = await LiveEngine._check_probes(engine, 1_788_919_200_000)

    assert statuses[0]["stop"] is True
    assert statuses[0]["status"] == "STOP_REPORTED"
    assert engine.state.stopped_books == {}, "a main stop must not empty the book"
    assert engine.model is sentinel, "the model must be untouched"
    assert any("未停止交易" in m for m in engine.alerts.sent), engine.alerts.sent


def test_the_shipped_registry_gives_main_a_reporting_stop() -> None:
    """What is actually deployed, so a future edit that flips it to a halt has to face this test."""
    shipped = parse_registry(yaml.safe_load(Path("config/alpha_registry.yaml").read_text(encoding="utf-8")))
    books = {p.book: p for p in probes_from_registry(shipped)}
    assert "main" in books, "§3 says the main book keeps a P&L stop"
    assert books["main"].halts is False
    assert books["main"].max_loss == 0.06
