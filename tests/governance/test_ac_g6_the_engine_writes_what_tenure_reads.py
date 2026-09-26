"""AC-G6': the real engine produces the record, and the real time rule reads it back.

Both halves were already tested and they never met.  `tests/live/test_probe.py` drives a live engine
until a probe book's stop fires; `tests/governance/test_the_time_rule_reads_the_record.py` drives
`tenure` over hand-written cycles.  Between them sits the join AC-G6' is actually about - whether the
rows the engine WRITES are the rows the rule can READ - and that join is where this project's defects
live: `probes_from_registry` excluding the main book, the record keyed on the book while the state was
keyed on the strategy, a stop threshold in no digest.  A hand-written fixture agrees with whatever it
was written to agree with.

So: run the engine, let the stop fire, hand `tenure` the file the engine just wrote, and assert the
state machine moves the way §3 says.  Three sequences, which is what AC-G6' asks for.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.tenure import tenure
from starquant_live.engine import LiveEngine
from starquant_live.probe import ProbeParams
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import _config, _prices

POLICY = Policy()
ANCHOR = "2026-09-03T00:00:00+00:00"


def _model() -> AlphaModel:
    main = StrategyEntry(
        "tsmom",
        params={
            **TsmomParams(vol_window=100).__dict__,
            "horizons": [5, 20, 50],
            "horizon_weights": [0.2, 0.3, 0.5],
            "entry_threshold": 0.05,
        },
    )
    sleeve = StrategyEntry("breakout", params={**asdict(BreakoutParams()), "entry_threshold": 0.05}, book="probe")
    return AlphaModel(
        entries=(main, sleeve),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
        books={"probe": 0.5},
    )


async def _run(panel: Panel, tmp_path: Path, *, loss: float | None, flows: dict | None) -> list[dict]:
    """Two cycles of a real engine; the second one carries `loss` attributed to the probe sleeve."""
    probe = ProbeParams(book="probe", strategy="breakout", window_days=30, max_loss=0.01, accepted_on="2026-08-01")
    cursor = 400
    market = FakeMarketData(panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(panel, cursor))
    clock = FakeClock(market.bar_open_ms(cursor) + 5_000)
    store = StateStore(tmp_path / "live")
    config = _config(tmp_path, probes=(probe,), strategy_weights={"tsmom": 1.0, "breakout": 0.5})
    engine = LiveEngine(config, model=_model(), market=market, venue=venue, clock=clock, store=store)
    await engine.startup()
    bar = market.bar_open_ms(cursor - 1)
    await engine.run_cycle(bar)
    if loss is not None:
        store.append_attribution(
            {
                "bar_open_ms": bar,
                "until_ms": clock.now_ms(),
                "basis": "net_exposure",
                "by_strategy": {"breakout": loss, "tsmom": 40.0},
            }
        )
    market.cursor += 1
    await engine.run_cycle(bar + 3_600_000)
    if flows is not None:
        # Rewrite the PERSISTED row, not the dict `run_cycle` returned: the engine adds `at` when it
        # appends, so serialising the return value drops the timestamp and `tenure` then skips the row
        # for being outside the window.  Which is the point of testing against the real writer - a
        # hand-written fixture has whatever fields its author remembered.
        lines = store.cycles_path.read_text(encoding="utf-8").splitlines()
        persisted = json.loads(lines[-1])
        persisted["external_flows"] = flows
        lines[-1] = json.dumps(persisted)
        store.cycles_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [json.loads(line) for line in store.cycles_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _book() -> Book:
    return Book(candidates={"breakout": Candidate("breakout", State.PROBE, probe_entries=1, fraction=1 / 3)})


async def test_no_stop_leaves_the_probe_where_it_was(august_panel: Panel, tmp_path: Path) -> None:
    rows = await _run(august_panel, tmp_path, loss=None, flows=None)
    derived = tenure(rows, book="probe", started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
    assert derived.stopped_at is None and not [e for e in derived.events if e.event is Event.PNL_STOP]
    book = _book()
    for event in derived.events:
        book, _ = apply(book, "breakout", event.event, Facts(), POLICY)
    assert book.candidates["breakout"].state is State.PROBE
    assert book.consecutive_probe_stops == 0


async def test_one_stop_demotes_the_probe_and_zeroes_its_windows(august_panel: Panel, tmp_path: Path) -> None:
    rows = await _run(august_panel, tmp_path, loss=-200.0, flows=None)
    stopped = [r for r in rows if any(p.get("stop") for p in (r.get("probes") or []))]
    assert stopped, "the engine did not write a stop for tenure to read"

    derived = tenure(rows, book="probe", started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
    assert derived.stopped_at, "the engine wrote a stop and the rule could not see it"
    assert derived.strategy == "breakout", "the record has to carry the id the state is keyed on"

    book = _book()
    for event in derived.events:
        book, _ = apply(book, "breakout", event.event, Facts(), POLICY)
    candidate = book.candidates["breakout"]
    assert candidate.state is State.QUEUED, "§3: a stopped probe is demoted, not retired"
    assert candidate.windows_survived == 0 and candidate.fraction == 0.0
    assert book.consecutive_probe_stops == 1 and not book.frozen()


async def test_a_stop_inside_a_rebaselined_cycle_moves_nothing(august_panel: Panel, tmp_path: Path) -> None:
    """KILL-AR-20: the demo account resets as a TRANSFER, and a reset must not retire a book."""
    flows = {"total": 5_000.0, "rows": 1, "by_type": {"TRANSFER": 5_000.0}, "rebaselined": True}
    rows = await _run(august_panel, tmp_path, loss=-200.0, flows=flows)
    assert any(p.get("stop") for p in (rows[-1].get("probes") or [])), "the engine still recorded the stop"

    derived = tenure(rows, book="probe", started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
    assert derived.stopped_at is None, "and the rule refused to read it as one"
    assert derived.skipped and "rebaselined" in derived.skipped[0].why

    book = _book()
    for event in derived.events:
        book, _ = apply(book, "breakout", event.event, Facts(), POLICY)
    assert book.candidates["breakout"].state is State.PROBE
    assert book.consecutive_probe_stops == 0
