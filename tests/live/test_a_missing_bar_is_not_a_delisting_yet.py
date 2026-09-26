"""`inputs.dropped` had no reader anywhere in the tree, and the default was to flatten (2026-09-13 🟡).

The path: `closed_bars` hands back an empty frame or a single bar for a symbol - a delisting, a public
endpoint wobble, the empty body that follows a rate limit - `model_inputs` puts it in `dropped` and out
of `usable`, the model scores nothing for it, `run_cycle`'s `setdefault` fills it with 0.0, and
`plan_rebalance` reads a target of 0 against an open position as `closing`: one reduce-only market
order for the whole line.  The next cycle the data comes back and the signal opens it again.  The bill
for one missing HTTP response is two crossings of the spread, a reset exit anchor and a cooldown -
and `record["inputs"]["dropped"]` was written into `cycles.jsonl` where nothing read it.  D-041 /
DL-Q0's exact shape: written down, no reader.

Flattening a real delisting is RIGHT, so the change is not "stop flattening".  It is that the loop can
now tell the two apart, and the only thing that can tell them apart is whether the data comes back.
A single cycle of absence holds last cycle's target; `dropped_after` consecutive cycles is a delisting
and flattens, exactly D-031's `quarantine_after` shape one input over.

This can only REDUCE trading: the weights it touches are ones that had just been set to 0.0, and the
value it puts back is the same symbol's own weight from the previous cycle.  It cannot open a line the
model did not already have on, and a postponed flatten is the same flatten, later.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_alpha.panel import Panel
from starquant_live.engine import LiveEngine
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _model, _prices

HOUR_MS = 3_600_000
VICTIM = "SOLUSDT"


class _DroppingMarket(FakeMarketData):
    """A feed that serves everything except the symbols in `blind`, which is what a wobble looks like."""

    def __init__(self, panel: Panel, cursor: int) -> None:
        super().__init__(panel, cursor)
        self.blind: set[str] = set()

    async def closed_bars(self, symbols: Sequence[str], interval: str, limit: int) -> dict[str, pd.DataFrame]:
        bars = await super().closed_bars(symbols, interval, limit)
        for symbol in self.blind:
            bars.pop(symbol, None)
        return bars


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


def _world(august_panel: Panel, tmp_path: Path, **engine_kwargs: Any) -> dict[str, Any]:
    cursor = 400
    market = _DroppingMarket(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    alerts = _RecordingAlerts()
    engine = LiveEngine(
        _config(tmp_path),
        model=_model(),
        market=market,
        venue=venue,
        clock=clock,
        store=StateStore(tmp_path / "live"),
        alerts=alerts,  # type: ignore[arg-type]
        **engine_kwargs,
    )
    return {"engine": engine, "market": market, "venue": venue, "alerts": alerts, "cursor": cursor}


async def _open_the_book(world: dict[str, Any]) -> int:
    engine, market = world["engine"], world["market"]
    await engine.startup()
    bar = market.bar_open_ms(world["cursor"] - 1)
    await engine.run_cycle(bar)
    assert abs(world["venue"].qty.get(VICTIM, 0.0)) > 0, "the fixture needs an open line to endanger"
    return bar


async def test_one_missing_cycle_holds_the_position_instead_of_flattening_it(
    august_panel: Panel, tmp_path: Path
) -> None:
    world = _world(august_panel, tmp_path, dropped_after=3)
    engine, market, venue = world["engine"], world["market"], world["venue"]
    bar = await _open_the_book(world)
    held_before = venue.qty[VICTIM]

    market.blind = {VICTIM}
    market.cursor += 1
    record = await engine.run_cycle(bar + HOUR_MS)

    assert record["inputs"]["dropped"] == [VICTIM], "the fixture really did withhold the bars"
    assert record["dropped_inputs"]["held"] == [VICTIM]
    assert record["dropped_inputs"]["flattened"] == []
    assert record["targets"][VICTIM] != 0.0, "a target of 0 against an open line is a reduce-only flatten"
    assert [order for order in record["orders"] if order["symbol"] == VICTIM] == []
    assert venue.qty[VICTIM] == held_before, "nothing was sold on one missing HTTP response"


async def test_every_dropped_cycle_is_announced(august_panel: Panel, tmp_path: Path) -> None:
    """The other half of "no reader": an operator is told, under a key of its own."""
    world = _world(august_panel, tmp_path)
    engine, market, alerts = world["engine"], world["market"], world["alerts"]
    bar = await _open_the_book(world)
    assert [key for _, key in alerts.sent if key == "inputs-dropped"] == [], "a clean cycle says nothing"

    market.blind = {VICTIM}
    market.cursor += 1
    await engine.run_cycle(bar + HOUR_MS)

    announced = [text for text, key in alerts.sent if key == "inputs-dropped"]
    assert len(announced) == 1
    assert VICTIM in announced[0]


async def test_a_streak_is_a_delisting_and_still_flattens(august_panel: Panel, tmp_path: Path) -> None:
    """The rule is not "never flatten".  Three consecutive absences are evidence, and it acts on them."""
    world = _world(august_panel, tmp_path, dropped_after=3)
    engine, market, venue = world["engine"], world["market"], world["venue"]
    bar = await _open_the_book(world)
    market.blind = {VICTIM}

    records = []
    for step in (1, 2, 3):
        market.cursor += 1
        records.append(await engine.run_cycle(bar + step * HOUR_MS))

    assert [r["dropped_inputs"]["held"] for r in records] == [[VICTIM], [VICTIM], []]
    assert records[-1]["dropped_inputs"]["flattened"] == [VICTIM]
    assert records[-1]["dropped_inputs"]["streak"][VICTIM] == 3
    assert records[-1]["targets"][VICTIM] == 0.0
    assert venue.qty.get(VICTIM, 0.0) == 0.0, "a delisting is still exited, three cycles later"


async def test_the_streak_resets_the_moment_the_data_comes_back(august_panel: Panel, tmp_path: Path) -> None:
    """One good cycle clears it, so a feed that flaps every other hour never reaches the threshold."""
    world = _world(august_panel, tmp_path, dropped_after=3)
    engine, market, venue = world["engine"], world["market"], world["venue"]
    bar = await _open_the_book(world)

    for step, blind in enumerate((True, False, True, False, True), start=1):
        market.blind = {VICTIM} if blind else set()
        market.cursor += 1
        record = await engine.run_cycle(bar + step * HOUR_MS)
        if blind:
            assert record["dropped_inputs"]["streak"][VICTIM] == 1, "never accumulates"
        else:
            assert record["dropped_inputs"]["symbols"] == []
            assert engine.state.dropped_streak == {}

    assert abs(venue.qty.get(VICTIM, 0.0)) > 0, "five flaps cost nothing"


async def test_dropped_after_one_is_the_behaviour_this_replaced(august_panel: Panel, tmp_path: Path) -> None:
    """The control: with the hold turned off, the first absence flattens - which is what shipped before."""
    world = _world(august_panel, tmp_path, dropped_after=1)
    engine, market, venue = world["engine"], world["market"], world["venue"]
    bar = await _open_the_book(world)

    market.blind = {VICTIM}
    market.cursor += 1
    record = await engine.run_cycle(bar + HOUR_MS)

    assert record["dropped_inputs"]["flattened"] == [VICTIM]
    assert record["targets"][VICTIM] == 0.0
    assert venue.qty.get(VICTIM, 0.0) == 0.0


async def test_the_streak_survives_a_restart(august_panel: Panel, tmp_path: Path) -> None:
    """Persisted like `reject_streak`: a loop that restarts on every flap would never reach a delisting."""
    world = _world(august_panel, tmp_path)
    engine, market = world["engine"], world["market"]
    bar = await _open_the_book(world)

    market.blind = {VICTIM}
    market.cursor += 1
    await engine.run_cycle(bar + HOUR_MS)

    assert StateStore(tmp_path / "live").load().dropped_streak == {VICTIM: 1}


async def test_the_shipped_default_is_the_old_behaviour_so_the_rule_is_adopted_not_deployed(
    august_panel: Panel, tmp_path: Path
) -> None:
    """`dropped_after` ships at 1, which flattens on the first empty answer - what this replaced.

    The rule above is the fix; shipping it ON would have changed the live book as a side effect of
    deploying a defect report, which is the one thing every other knob added on 2026-09-13 was careful
    not to do.  `construction_fingerprint` carries the field so raising it is visible in the record,
    and raising it is a priced decision rather than a consequence of a restart.
    """
    from starquant_live.config import LiveConfig

    assert LiveConfig.dropped_after == 1
    world = _world(august_panel, tmp_path)  # no override: the shipped default
    assert world["engine"].dropped_after == 1
