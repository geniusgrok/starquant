"""What pages the operator vs what only lands in the daily report.

`com.starquant.check` ran red hourly for three days on a TRUE but unactionable line: two construction
changes had landed on 2026-09-04 and a promotion cannot be un-done.  It also double-posted to the
alert channel every hour: two writers on one channel, and a dedup window then equal to the job's own
period, which is a coin flip rather than a suppression.  A standing governance fact is exactly
the repeated alert that `starquant_live/alerts.py` warns makes the one that matters get missed, so it
no longer pages at all: it stays in the report's Evidence window block, where a human reads it at
review time.  Operational alerts - drift, risk budget, risk adaptation - are untouched.
"""

from __future__ import annotations

from starquant_live.reports import daily_alerts


def _payload(**extra: object) -> dict:
    return {"drift": {}, "income_drift": {}, "risk_budget": {}, "risk_adaptation": {}, "evidence_window": {}, **extra}


def test_construction_cadence_is_a_notice_and_never_pages() -> None:
    alerts, notices = daily_alerts(_payload(evidence_window={"changes_7d": 2}))
    assert alerts == [], "a promotion count cannot be acted on; paging hourly only buries real alerts"
    assert len(notices) == 1 and "2 次构造变更" in notices[0]


def test_one_promotion_a_week_is_not_even_a_notice() -> None:
    assert daily_alerts(_payload(evidence_window={"changes_7d": 1})) == ([], [])


def test_operational_alerts_still_page() -> None:
    alerts, notices = daily_alerts(_payload(risk_budget={"status": "ALERT", "reasons": ["drawdown 36%"]}))
    assert notices == []
    assert len(alerts) == 1 and "风险预算告警" in alerts[0] and "drawdown 36%" in alerts[0]


def test_a_notice_does_not_swallow_an_alert_raised_in_the_same_report() -> None:
    alerts, notices = daily_alerts(
        _payload(
            evidence_window={"changes_7d": 3},
            drift={"status": "ALERT", "reasons": ["realised 0.2 vs expected 1.5"]},
        )
    )
    assert len(alerts) == 1 and "权益漂移告警" in alerts[0]
    assert len(notices) == 1 and "3 次构造变更" in notices[0]


def test_income_drift_keeps_its_per_strategy_z_detail() -> None:
    """The z-score fallback only fires when `reasons` is empty; M-010 reads per-strategy, not equity."""
    alerts, _ = daily_alerts(
        _payload(income_drift={"status": "ALERT", "by_strategy": {"tsmom": {"z": -3.4}, "flow": {"z": -0.2}}})
    )
    assert len(alerts) == 1
    assert "策略收益漂移告警" in alerts[0] and "tsmom: z=-3.4" in alerts[0] and "flow" not in alerts[0]


# --- M-Q03's two halves, split 2026-09-16 (operator's decision) -------------------------------------
#
# M-Q03 was wholly a notice, for a reason this module's docstring gives: a planned deployment restart
# costs a rebalance, cannot be undone, and would hold the hourly check red until UTC midnight.  That
# argument covers restart misses.  It does NOT cover the other half the reporter learned to count the
# same day: a bar whose CYCLE FAILED is an hour in which the book was not rebalanced and - because the
# exit overlay rests no order at the venue - not checked for stops either, and the thing to do about it
# is on the path to the venue, now, not at review.  So the failed half pages and the restart half does
# not.  The operator priced the cadence before choosing: one failed bar re-announces hourly until UTC
# midnight, the same way `live status`'s 95% gate already does for the same incident.


def _restarts(**extra: object) -> dict:
    return {"status": "ALERT", "failed_bars": 0, "reasons": ["漏掉 1 次再平衡（M-Q03 阈值 0）"], **extra}


def test_a_failed_bar_pages() -> None:
    alerts, notices = daily_alerts(
        _payload(restarts=_restarts(failed_bars=1, failed_bar_error="ProxyError: 503 Service Unavailable"))
    )
    assert len(alerts) == 1
    assert "1 根 bar" in alerts[0], "how many hours of the book went unmanaged"
    assert "ProxyError: 503 Service Unavailable" in alerts[0], "and what to go and look at"
    assert len(notices) == 1, "the notice stays: it is the complete record read at review"


def test_a_restart_miss_alone_still_only_notices() -> None:
    """The half the original argument covers, unchanged.  A restart cannot be un-restarted."""
    alerts, notices = daily_alerts(_payload(restarts=_restarts()))
    assert alerts == []
    assert len(notices) == 1 and "M-Q03" in notices[0]


def test_a_late_cycle_share_breach_alone_still_only_notices() -> None:
    """The other way into `status == ALERT`.  Lateness is not a lost bar and does not page."""
    alerts, notices = daily_alerts(_payload(restarts=_restarts(reasons=["迟到周期占比 8.0% 高于 M-Q03 的 5%"])))
    assert alerts == []
    assert len(notices) == 1


def test_a_day_with_both_halves_pages_for_the_failed_one_and_notices_the_whole() -> None:
    alerts, notices = daily_alerts(
        _payload(restarts=_restarts(failed_bars=2, failed_bar_error="ConnectError: All connection attempts failed"))
    )
    assert len(alerts) == 1 and "2 根 bar" in alerts[0]
    assert len(notices) == 1 and "漏掉 1 次再平衡" in notices[0]


def test_a_payload_written_before_this_split_does_not_crash_or_page() -> None:
    """`failed_bars` did not exist until 2026-09-16; yesterday's report JSON is still readable."""
    alerts, notices = daily_alerts(_payload(restarts={"status": "ALERT", "reasons": ["漏掉 1 次再平衡"]}))
    assert alerts == [] and len(notices) == 1


def test_the_page_is_raised_from_what_the_reporter_actually_returns() -> None:
    """Through `restart_cost`, not a hand-built block: the two sides have to agree on the key."""
    from starquant_live.reports import restart_cost

    failed = {
        "bar_open_ms": 1_789_531_200_000,
        "phase": "ERROR",
        "error": "ProxyError: 503 Service Unavailable",
        "window_seconds": 87.1,
        "orders": [],
        "leaving": [],
        "quarantined": [],
        "universe_update": None,
        "risk_ladder": {},
    }
    alerts, _ = daily_alerts(_payload(restarts=restart_cost([failed])))
    assert len(alerts) == 1 and "1 根 bar" in alerts[0]
