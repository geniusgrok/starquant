"""G1 (2026-09-23): §12.9's decay rule reaches the hourly check, and its windows start at the construction.

The rule was adopted 2026-09-07 and built the same day, and its only reader was `report weekly` - which no
job runs.  So a REVIEW would have been computed by nobody.  `report daily --check` is what the hourly job
runs, and these tests pin what it now does with the rule:

* **REVIEW pages; nothing else does.**  Two whole windows below q10 is an alert.  One window below is OK.
  INSUFFICIENT_DATA - the reading for sixty days after every construction change - is rendered in the
  report and routed nowhere, not even as a notice.
* **The windows start where M-010's does.**  §12.9: "构造一变，q10 必须重算，与 M-010 的清零语义一致".
  Until this change the windows were read from bar zero, so on the live record the first one would
  have mixed six canonical constructions.  An aliased digest must NOT restart them.
* **The daily and the weekly read the rule identically**, because they make the same call.
* **The page names both calibers.**  The live windows are realised attributed income and q10 is the
  backtest's mark-to-market; operator ruling A (2026-09-23) keeps the comparison and labels it.

The q10s are not invented here: they come from the evidence reports the registry cites today, through
`expectations_from_evidence` - the path `report daily` itself takes.  Only the live record is synthetic,
and it is built so each 30-day window's Sharpe is known in closed form.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from starquant_live.composition import load_registry
from starquant_live.construction import CONSTRUCTION_ALIASES
from starquant_live.reports import (
    daily_alerts,
    daily_markdown,
    daily_payload,
    decay_watch,
    expectations_from_evidence,
    weekly_payload,
)
from starquant_live.state import StateStore

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3_600_000
WINDOW = 720  # DECAY_WINDOW_DAYS of hourly bars
BASE = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000)
EQUITY = 10_000.0
# Real digests.  The live loop recorded `0c555e1c...` from 2026-09-17T16:07Z (D3, a real construction
# change from `46b8d731...`), and `b8f215ab...` after the v10 restart, declared the same book.
BEFORE_D3 = "46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10"
CURRENT = "0c555e1c837e342a8af1edca0089b12461a9bdbe3b9a0f122142c63d6ba54bd7"
ALIAS_OF_CURRENT = "b8f215ab706ca7c472028d109f96f9fbb911097a9a16bb4b6fb9dee9ec5b528a"
SECTION = "## Edge decay (M-010 vs backtest q10)"


def _registry_expectations() -> dict[str, Any]:
    """What `report daily` hands the rule: the expectations of the evidence the registry cites."""
    registry = load_registry(ROOT / "config" / "alpha_registry.yaml")
    reports = {
        entry.id: json.loads((ROOT / str(entry.evidence["report"])).read_text(encoding="utf-8"))
        for entry in registry.enabled
    }
    return expectations_from_evidence(reports)


def _window(sharpe: float) -> list[float]:
    """720 per-bar returns whose annualised Sharpe is exactly `sharpe`: +-s around a mean m, alternating."""
    spread = 1e-3
    mean = sharpe * spread * math.sqrt(WINDOW / (WINDOW - 1)) / math.sqrt(8760.0)
    return [mean + spread * (1 if i % 2 == 0 else -1) for i in range(WINDOW)]


def _record(tmp_path: Path, segments: list[tuple[str, list[float]]], *, flow_sharpe: float = 1.0) -> StateStore:
    """A live record: one cycle and one attribution row per hour, `segments` of (digest, tsmom returns).

    flow gets the same number of bars at `flow_sharpe` per whole window, so a test can show that only the
    strategy whose windows sit below ITS OWN q10 is named.
    """
    store = StateStore(tmp_path / "live")
    returns = [(digest, value) for digest, values in segments for value in values]
    flow = [value for _ in range(len(returns) // WINDOW + 1) for value in _window(flow_sharpe)]
    cycles, attributions = [], []
    for i, (digest, value) in enumerate(returns):
        bar = BASE + i * HOUR
        at = datetime.fromtimestamp((bar + HOUR) / 1000 + 25, tz=UTC).isoformat()
        cycles.append({"at": at, "bar_open_ms": bar, "equity": EQUITY, "construction": digest})
        by_strategy = {"tsmom": value * EQUITY, "flow": flow[i] * EQUITY}
        attributions.append({"at": at, "bar_open_ms": bar, "by_strategy": by_strategy})
    store.cycles_path.write_text("".join(json.dumps(row) + "\n" for row in cycles), encoding="utf-8")
    store.attribution_path.write_text("".join(json.dumps(row) + "\n" for row in attributions), encoding="utf-8")
    return store


def _day(store: StateStore) -> str:
    last = store.read_jsonl(store.cycles_path)[-1]["bar_open_ms"]
    return datetime.fromtimestamp(last / 1000, tz=UTC).strftime("%Y-%m-%d")


def _daily(store: StateStore, tmp_path: Path) -> dict[str, Any]:
    return daily_payload(store, _day(store), _registry_expectations(), data_root=tmp_path / "no-archive")


def _mentions_decay(lines: list[str]) -> list[str]:
    return [line for line in lines if "衰减" in line or "REVIEW" in line]


def test_the_registry_cited_evidence_carries_a_q10_for_every_enabled_strategy() -> None:
    """Without one the rule reads INSUFFICIENT_DATA for ever and the hourly check can never page on it."""
    expectations = _registry_expectations()
    assert expectations, "the registry enables no strategy"
    for strategy, row in expectations.items():
        assert row.get("oos_window_sharpe_q10") is not None, f"{strategy}: its evidence carries no q10"
    # The threshold the tests below cross is below zero, as §12.9 predicted for a 30-day window.
    assert expectations["tsmom"]["oos_window_sharpe_q10"] < 0


def test_two_whole_windows_below_q10_page_from_the_hourly_check(tmp_path: Path) -> None:
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    store = _record(tmp_path, [(CURRENT, _window(q10 - 3.0) + _window(q10 - 2.0))])
    payload = _daily(store, tmp_path)
    row = payload["decay"]["tsmom"]
    assert row["status"] == "REVIEW" and row["below"] == 2 and row["bars"] == 2 * WINDOW
    assert row["windows"] == pytest.approx([q10 - 3.0, q10 - 2.0], abs=1e-9)
    assert payload["decay"]["flow"]["status"] == "OK", "flow's windows sit above ITS q10"
    alerts, notices = daily_alerts(payload)
    paged = _mentions_decay(alerts)
    assert len(paged) == 1 and "tsmom" in paged[0] and "flow" not in paged[0]
    assert f"{q10:.2f}" in paged[0], "the line quotes the threshold it crossed"
    assert "口径不同" in paged[0], "ruling A: the page says the two sides are different calibers"
    assert not _mentions_decay(notices)
    text = daily_markdown(payload)
    assert SECTION in text and "REVIEW (2/2 below q10)" in text


@pytest.mark.parametrize("order", ["first_below", "second_below"])
def test_one_window_below_q10_does_not_page(tmp_path: Path, order: str) -> None:
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    below, above = _window(q10 - 3.0), _window(q10 + 3.0)
    store = _record(tmp_path, [(CURRENT, below + above if order == "first_below" else above + below)])
    payload = _daily(store, tmp_path)
    assert payload["decay"]["tsmom"]["status"] == "OK" and payload["decay"]["tsmom"]["below"] == 1
    alerts, notices = daily_alerts(payload)
    assert not _mentions_decay(alerts) and not _mentions_decay(notices)


def test_insufficient_data_is_shown_and_routed_nowhere(tmp_path: Path) -> None:
    """The reading for the rule's first sixty days.  It is expected, not a fault, and must not page."""
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    store = _record(tmp_path, [(CURRENT, _window(q10 - 3.0) + _window(q10 - 3.0)[:100])])
    payload = _daily(store, tmp_path)
    assert payload["decay"]["tsmom"]["status"] == "INSUFFICIENT_DATA"
    assert payload["decay"]["tsmom"]["bars"] == WINDOW + 100
    alerts, notices = daily_alerts(payload)
    assert not _mentions_decay(alerts) and not _mentions_decay(notices)
    text = daily_markdown(payload)
    assert SECTION in text
    assert "INSUFFICIENT_DATA - 1 whole windows, needs 2" in text
    assert f"bars {WINDOW + 100}/{2 * WINDOW}" in text, "the countdown is what is rendered"
    assert "| 口径 | 实盘窗口是已实现归因，q10 是回测盯市。口径不同" in text, "ruling A, 2026-09-23"


def test_the_windows_start_at_the_current_construction(tmp_path: Path) -> None:
    """Two bad windows under the book BEFORE D3 say nothing about the book after it.

    Read from bar zero - the rule as built on 2026-09-07 - this record is REVIEW and pages.  Read from
    the construction, it has 200 bars and no whole window.
    """
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    old = _window(q10 - 3.0) + _window(q10 - 3.0)
    store = _record(tmp_path, [(BEFORE_D3, old), (CURRENT, _window(q10 + 3.0)[:200])])
    payload = _daily(store, tmp_path)
    row = payload["decay"]["tsmom"]
    assert row["status"] == "INSUFFICIENT_DATA" and row["bars"] == 200
    assert row["bars"] == payload["income_drift"]["by_strategy"]["tsmom"]["bars"], "M-010's own series"
    assert not _mentions_decay(daily_alerts(payload)[0])


def test_an_aliased_digest_does_not_restart_the_windows(tmp_path: Path) -> None:
    """A renamed fingerprint is the same book (`CONSTRUCTION_ALIASES`), so the windows run across it."""
    assert CONSTRUCTION_ALIASES[ALIAS_OF_CURRENT] == CURRENT
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    store = _record(tmp_path, [(CURRENT, _window(q10 - 3.0)), (ALIAS_OF_CURRENT, _window(q10 - 2.0))])
    payload = _daily(store, tmp_path)
    assert payload["decay"]["tsmom"]["status"] == "REVIEW"
    assert payload["decay"]["tsmom"]["bars"] == 2 * WINDOW
    assert _mentions_decay(daily_alerts(payload)[0])


def test_the_daily_and_the_weekly_read_the_rule_identically(tmp_path: Path) -> None:
    q10 = _registry_expectations()["tsmom"]["oos_window_sharpe_q10"]
    store = _record(tmp_path, [(BEFORE_D3, _window(q10 - 3.0)), (CURRENT, _window(q10 - 3.0) + _window(1.0))])
    expectations = _registry_expectations()
    daily = daily_payload(store, _day(store), expectations, data_root=tmp_path / "no-archive")["decay"]
    weekly = weekly_payload(store, _day(store), expectations=expectations)["decay"]
    assert daily == weekly == decay_watch(store, expectations, equity=EQUITY)
    assert daily["tsmom"]["status"] == "OK" and daily["tsmom"]["whole_windows"] == 2
