from __future__ import annotations

from pathlib import Path

import pytest

from starquant_live.reports import daily_payload, drift_check, expectations_from_evidence
from starquant_live.state import StateStore


def _fill_cycles(store: StateStore, equities: list[float]) -> None:
    base = 1_756_800_000_000  # 2025-09-02T08:00Z
    for i, equity in enumerate(equities):
        store.append_cycle(
            {
                "bar_open_ms": base + i * 3_600_000,
                "equity": equity,
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
            }
        )


def test_drift_alerts_when_realised_far_below_expectation(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    _fill_cycles(store, [10_000 * (1 - 0.002 * i) for i in range(200)])  # steady losses
    expectations = expectations_from_evidence(
        {
            "tsmom": {
                "walk_forward": {"oos_sharpe": 1.4},
                "full_sample": {"annualized_sharpe": 1.5, "max_drawdown": -0.13},
                "verdict": "PASS",
            }
        }
    )
    drift = drift_check(store, expectations)
    assert drift["status"] == "ALERT" and drift["reasons"]
    assert expectations["tsmom"]["oos_sharpe"] == 1.4


def test_drift_ok_and_insufficient(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    assert drift_check(store, {})["status"] == "INSUFFICIENT_DATA"
    _fill_cycles(store, [10_000 * (1 + 0.0002 * i) for i in range(100)])
    drift = drift_check(
        store,
        expectations_from_evidence(
            {"tsmom": {"walk_forward": {"oos_sharpe": 1.4}, "full_sample": {"max_drawdown": -0.13}}}
        ),
    )
    assert drift["status"] == "OK"
    payload = daily_payload(store, "2025-09-02", {"tsmom": {"oos_sharpe": 1.4}})
    assert payload["cycles"] > 0 and payload["drift"]["status"] in {"OK", "INSUFFICIENT_DATA"}


def test_daily_payload_reports_probe_books(tmp_path: Path) -> None:
    from starquant_live.probe import ProbeParams
    from starquant_live.reports import daily_markdown

    store = StateStore(tmp_path)
    _fill_cycles(store, [10_000.0, 10_050.0])
    base = 1_756_800_000_000
    store.append_attribution(
        {"bar_open_ms": base, "until_ms": base + 3_600_000, "basis": "net_exposure", "by_strategy": {"flow": -30.0}}
    )
    probe = ProbeParams(book="flow_short", strategy="flow", window_days=30, max_loss=0.01, accepted_on="2025-06-01")
    payload = daily_payload(store, "2025-09-02", {}, probes=(probe,))
    row = payload["probes"][0]
    assert row["book"] == "flow_short" and row["pnl"] == -30.0 and row["status"] == "REVIEW_DUE"
    assert row["pnl_pct"] == pytest.approx(-30.0 / 10_050.0)
    markdown = daily_markdown(payload)
    assert "Probe books (D-019)" in markdown and "REVIEW_DUE strategy=flow" in markdown
    state = store.load()
    state.stopped_books = {"flow_short": {"reason": "test"}}
    store.save(state)
    assert daily_payload(store, "2025-09-02", {}, probes=(probe,))["probes"][0]["status"] == "STOPPED"
