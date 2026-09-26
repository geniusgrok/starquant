"""DRILL-G2 and DRILL-G6, the two of §5's six that were still owed.

The other four are drills already: G1 writes a bad evidence pointer at the real startup gate, G4 fails
a canary soak, G5 proposes what the file already says, G3 is the pinned `policy_digest()` plus the
comparison `live status --check` now makes.  These two were listed as "covered by the property tests",
which is not the same claim: a property test drives the state machine directly, and what these two ask
is whether the LIVE RECORD, read the way the machine reads it, produces the event at all.  That seam -
`cycles.jsonl` -> `tenure` -> `lifecycle` -> `governance_state.json` - is where the "the rule exists
and nothing raises its event" defect lives, and it is exactly the defect this project keeps finding.

G2: two stopped probes freeze promotion, and `governance status` says so; a stop on a re-baselined
    cycle is not one of the two.
G6: an hour of proxy 503s produces no governance decision at all - not a survived window, not a stop,
    not an R5 count - and does not page once per cycle.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from starquant_cli.governance_cmd import governance
from starquant_governance.lifecycle import Book, Candidate, Event, Facts, State, apply
from starquant_governance.policy import Policy
from starquant_governance.state import dump
from starquant_governance.tenure import tenure

ANCHOR = "2026-09-03T00:00:00+00:00"
START = datetime(2026, 9, 3, tzinfo=UTC)
POLICY = Policy()


def _cycle(hours: int, probes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    at = START + timedelta(hours=hours)
    return {
        "at": at.isoformat(),
        "bar_open_ms": int(at.timestamp() * 1000),
        "equity": 10_000.0,
        "probes": probes,
        **extra,
    }


def _probe(book: str, strategy: str, *, stop: bool = False) -> dict[str, Any]:
    return {"book": book, "strategy": strategy, "stop": stop, "status": "STOP" if stop else "OK", "pnl_pct": -0.021}


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "cycles.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


# --- DRILL-G2 ----------------------------------------------------------------------------------


def _book_with_two_probes() -> Book:
    half = POLICY.probe_budget_share / 2
    return Book(
        candidates={
            "flow": Candidate("flow", State.PROBE, probe_entries=1, fraction=half),
            "resid": Candidate("resid", State.PROBE, probe_entries=1, fraction=half),
        }
    )


def test_drill_g2_two_stopped_probes_freeze_promotion_and_the_status_says_so(tmp_path: Path) -> None:
    rows = [_cycle(h, [_probe("flow_short", "flow"), _probe("resid_short", "resid")]) for h in range(4)]
    rows.append(_cycle(4, [_probe("flow_short", "flow", stop=True), _probe("resid_short", "resid")]))
    rows.append(_cycle(5, [_probe("flow_short", "flow", stop=True), _probe("resid_short", "resid", stop=True)]))
    record = [json.loads(line) for line in _write(tmp_path, rows).read_text(encoding="utf-8").splitlines()]

    book = _book_with_two_probes()
    fired: list[str] = []
    for name, strategy in (("flow_short", "flow"), ("resid_short", "resid")):
        derived = tenure(record, book=name, started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
        assert derived.stopped_at, f"{name}: the record shows a stop and tenure did not derive one"
        for event in derived.events:
            if event.event is Event.PNL_STOP:
                book, decision = apply(book, strategy, Event.PNL_STOP, Facts(), POLICY)
                fired.append(strategy)
                assert decision.allowed

    assert fired == ["flow", "resid"]
    assert book.consecutive_probe_stops == POLICY.freeze_after_consecutive_stops
    assert book.frozen(), "R5: two consecutive stops must freeze promotion"
    assert all(c.state is State.QUEUED for c in book.candidates.values()), "a stopped probe is demoted, not retired"

    # the freeze has to be legible to the operator, not only true in a dataclass
    root = tmp_path / "checkout"
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "governance_state.json").write_text(json.dumps(dump(book)), encoding="utf-8")
    result = CliRunner().invoke(governance, ["status", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert "FROZEN" in result.output, result.output
    assert f"until window {book.frozen_until_window}" in result.output


def test_drill_g2_a_stop_on_a_rebaselined_cycle_is_not_one_of_the_two(tmp_path: Path) -> None:
    """The demo account resets as a TRANSFER with no fills.  R5 counting that is the venue retiring a book."""
    rows = [_cycle(h, [_probe("flow_short", "flow")]) for h in range(4)]
    rows.append(
        _cycle(
            4,
            [_probe("flow_short", "flow", stop=True)],
            external_flows={"total": 5_000.0, "rows": 1, "by_type": {"TRANSFER": 5_000.0}, "rebaselined": True},
        )
    )
    record = [json.loads(line) for line in _write(tmp_path, rows).read_text(encoding="utf-8").splitlines()]

    derived = tenure(record, book="flow_short", started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
    assert derived.stopped_at is None, "a stop inside a re-baselined cycle is not a stop"
    assert not [e for e in derived.events if e.event is Event.PNL_STOP]
    assert derived.skipped and "rebaselined" in derived.skipped[0].why

    book = _book_with_two_probes()
    for event in derived.events:
        book, _ = apply(book, "flow", event.event, Facts(), POLICY)
    assert book.consecutive_probe_stops == 0 and not book.frozen()


# --- DRILL-G6 ----------------------------------------------------------------------------------


def test_drill_g6_an_hour_of_proxy_503s_produces_no_governance_decision(tmp_path: Path) -> None:
    """The path to the venue goes through a proxy that returns 503 in bursts (E-0/1082, memory).

    An ERROR cycle is not evidence in either direction: it must not count as a window survived, must
    not fire a stop, and must not touch R5.  The failing mode this guards is the attractive one - an
    outage looks like a book that stopped trading, and "stopped trading" is what a stop looks like too.
    """
    rows = [_cycle(h, [_probe("flow_short", "flow")]) for h in range(6)]
    rows += [
        {
            "at": (START + timedelta(hours=6 + h)).isoformat(),
            "bar_open_ms": int((START + timedelta(hours=6 + h)).timestamp() * 1000),
            "phase": "ERROR",
            "error": "httpx.ProxyError: 503 from the local proxy",
        }
        for h in range(60)
    ]
    record = [json.loads(line) for line in _write(tmp_path, rows).read_text(encoding="utf-8").splitlines()]

    derived = tenure(record, book="flow_short", started_at=ANCHOR, window_anchor=ANCHOR, policy=POLICY)
    assert derived.stopped_at is None
    assert derived.windows_survived == 0, "an hour of outage does not close a 30-day window"
    assert not [e for e in derived.events if e.event is Event.PNL_STOP]

    # and the state machine refuses every event a no-decision cycle could carry
    book = _book_with_two_probes()
    for event in Event:
        after, decision = apply(book, "flow", event, Facts(no_decision=True), POLICY)
        assert after == book and not decision.allowed
        assert decision.reasons, f"{event.value} refused without naming a rule"
    assert book.consecutive_probe_stops == 0


def test_drill_g6_the_outage_does_not_page_once_per_cycle(tmp_path: Path) -> None:
    """60 identical 503s inside the dedup window are one page, and the hour after is a new one.

    Driven through the real `WebhookAlerts` with a fake transport rather than a stub `send`, because
    the dedup this drill is about is the one that failed before: KILL-R7's 36 identical FAIL lines came
    from a fresh process every hour, so a dedup that lives only in memory suppressed nothing.
    """
    import asyncio

    import httpx

    from starquant_live.alerts import WebhookAlerts

    sent: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200)

    now = [0.0]
    alerts = WebhookAlerts(
        url="https://example.invalid/hook",
        dedup_window_seconds=3600.0,
        clock=lambda: now[0],
        transport=httpx.MockTransport(_handler),
        state_path=tmp_path / "alert_dedup.json",
    )

    async def _drive() -> None:
        for hour in range(60):
            now[0] = hour * 60.0  # a cycle a minute for an hour
            await alerts.send("StarQuant：循环报错 httpx.ProxyError: 503")
        now[0] = 4_000.0
        await alerts.send("StarQuant：循环报错 httpx.ProxyError: 503")

    asyncio.run(_drive())
    assert len(sent) == 2, f"one page for the storm and one after the window, got {len(sent)}"
