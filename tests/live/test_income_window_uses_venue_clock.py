"""D-030: the income window is on the venue's clock, because a signed request's immunity does not cover it.

A wrong host clock is invisible on the auth path - a -1021 makes the REST client resync and retry, so a
signed request's ``timestamp`` is always venue-correct.  ``startTime``/``endTime`` on /fapi/v1/income are
plain query parameters and were passed through untouched, so with the host an hour behind the venue
(measured 2026-09-04) the loop asked for an hour-old window.  Proven the same day: after a manual flatten,
96 rows worth +23.98 USDT sat at venue times 07:51-07:53 while the loop queried [06:53, 06:58] and ingested
nothing.  Income was not lost - it arrived an hour late, attributed to the book held an hour after it was
earned, which is the corruption M-010 exists to rule out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices

HOUR_MS = 3_600_000
HOST_NOW = 1_788_500_000_000


class SkewedVenue(FakeVenue):
    """A venue whose clock runs ``offset_ms`` ahead of the host's, honouring the window it is asked for."""

    def __init__(self, *args: Any, offset_ms: int = HOUR_MS, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.offset_ms = offset_ms
        self.windows: list[tuple[int, int]] = []

    def venue_time_ms(self) -> int:
        return HOST_NOW + self.offset_ms

    async def sync_clock(self) -> int:
        return self.offset_ms

    async def income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        self.windows.append((int(start_ms), int(end_ms)))
        kept = [row for row in self.income_log if start_ms <= int(row["time"]) <= end_ms]
        self.income_log = [row for row in self.income_log if row not in kept]
        return kept


def _engine(tmp_path: Path, venue: FakeVenue, panel: Panel) -> LiveEngine:
    market = FakeMarketData(panel, cursor=400)
    return LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(HOST_NOW),
        store=StateStore(tmp_path / "live"),
    )


@pytest.fixture
def panel(august_panel: Panel) -> Panel:
    return august_panel


async def test_a_fill_that_just_happened_at_the_venue_is_inside_the_window(panel: Panel, tmp_path: Path) -> None:
    """The regression: with the host an hour behind, this row used to sit outside [since, host_now]."""
    venue = SkewedVenue(balance=10_000.0, prices=_prices(panel, 400))
    engine = _engine(tmp_path, venue, panel)
    engine.state.last_income_ms = HOST_NOW - 3_600_000
    engine.state.last_contributions = {"tsmom": {"BTCUSDT": 1.0}}
    just_filled = venue.venue_time_ms() - 60_000  # an hour AHEAD of the host clock
    venue.income_log = [
        {"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL", "income": "26.2986", "time": just_filled},
        {"symbol": "BTCUSDT", "incomeType": "COMMISSION", "income": "-2.3184", "time": just_filled},
    ]

    flows = await engine._ingest_income(HOST_NOW, 10_000.0)

    start, end = venue.windows[-1]
    assert end == venue.venue_time_ms(), "the window must end on the venue's clock, not the host's"
    assert start <= just_filled <= end
    assert venue.income_log == [], "both rows were ingested"
    assert flows["rows"] == 0  # neither row is an external cash flow
    written = engine.store.read_jsonl(engine.store.attribution_path)
    assert written and written[-1]["by_strategy"]["tsmom"] == pytest.approx(26.2986 - 2.3184)
    # and the watermark advances on the same clock, so the next window is contiguous
    assert engine.state.last_income_ms == venue.venue_time_ms()


async def test_the_first_window_after_the_change_recovers_the_hour_the_host_basis_missed(
    panel: Panel, tmp_path: Path
) -> None:
    """A watermark left in host basis makes exactly one wider window; nothing in the gap is dropped."""
    venue = SkewedVenue(balance=10_000.0, prices=_prices(panel, 400))
    engine = _engine(tmp_path, venue, panel)
    engine.state.last_income_ms = HOST_NOW - 300_000  # written by the old host-clock code
    engine.state.last_contributions = {"tsmom": {"BTCUSDT": 1.0}}
    stranded = HOST_NOW + 1_000  # earned after host-now, before venue-now: invisible to the old window
    venue.income_log = [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL", "income": "1.5", "time": stranded}]

    await engine._ingest_income(HOST_NOW, 10_000.0)

    start, end = venue.windows[-1]
    assert start == HOST_NOW - 300_000 and end == HOST_NOW + HOUR_MS
    assert venue.income_log == [], "the stranded row is recovered by the one wider window"


async def test_a_venue_without_a_clock_falls_back_to_the_host(panel: Panel, tmp_path: Path) -> None:
    venue = FakeVenue(balance=10_000.0, prices=_prices(panel, 400))  # no venue_time_ms
    assert _engine(tmp_path, venue, panel).venue_now_ms() == HOST_NOW


async def test_a_venue_clock_that_raises_never_takes_the_cycle_down(panel: Panel, tmp_path: Path) -> None:
    class Broken(SkewedVenue):
        def venue_time_ms(self) -> int:
            raise RuntimeError("venue clock unavailable")

    venue = Broken(balance=10_000.0, prices=_prices(panel, 400))
    assert _engine(tmp_path, venue, panel).venue_now_ms() == HOST_NOW
