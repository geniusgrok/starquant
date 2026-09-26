"""The instrument the 2026-09-08 ruling owes.

Audit question 3 asked whether the backtest's equity and the live loop's equity are the same quantity.
They are not: 52% of live equity is non-USDT collateral and the backtest models none, so every weight
is a fraction of a number that moves with BTC.  The operator ruled on 2026-09-08 that the denominator
stays total equity - it is the venue's own margin basis, and under cross margin the collateral really
does absorb losses - which makes the pro-cyclical amplifier a NAMED accepted risk.

D.8 asks that an accepted residual risk carry a compensating control, and this repository's own
recurring lesson is blunter: a threshold nothing measures is just a sentence.  So the amplifier gets an
instrument.  It measures and changes nothing, and it must never page: it is a standing fact about the
account, not an event.

The property that matters most is the last one.  Reporting the repriced share is safe; subtracting it
would silently produce the USDT-denominator book the operator did not choose.

2026-09-09 audit, and the reason this file changed.  Until today the first test here ended with
``assert 0.72 < drift["repricing_share"] < 0.74`` under the heading "the live shape".  It was not the
live shape: it is a division between two numbers hard-coded three lines above it, so it could only ever
restate arithmetic the previous two assertions had already fixed.  What it DID do was publish a level -
the governance plan's §12 cites "23 周期里 73% 是重估" and `risk_budget.py`'s own docstring repeated it -
and that level was never a property of anything.  Measured on the live record on 2026-09-09 the same
instrument reads 1.0682 over 47 cycles: equity +36.41 while the book was DOWN 2.48, so more than all of
the rise was collateral.

So the assertions here now pin what cannot drift: the decomposition is an identity, and the share is
classified by DIRECTION rather than by level.  The direction that matters has a definitional boundary
and not a calibrated one - above a share of 1 the account's equity sign no longer tells you the book's
P&L sign, which is precisely the thing RISK-G11 exists to make visible.  Widening the old interval to
include 1.07 would have been the other move available today, and it would have been the wrong one: it
keeps a level nobody can justify and merely moves it to wherever the account happens to sit.
"""

from __future__ import annotations

from typing import Any

from starquant_live.risk_budget import collateral_drift


def _cycle(ms: int, equity: float, usdt: float) -> dict[str, Any]:
    return {
        "bar_open_ms": ms,
        "equity": equity,
        "collateral": {
            "equity": equity,
            "usdt_equity": usdt,
            "collateral": equity - usdt,
            "share": (equity - usdt) / equity,
        },
    }


def test_it_splits_the_equity_move_into_trading_and_repricing() -> None:
    """The 2026-09-07 window, kept as a worked example - but read as an identity, not as a level."""
    rows = [_cycle(1_000, 10_964.21, 5_264.90), _cycle(2_000, 10_904.10, 5_216.70)]
    attribution = [{"bar_open_ms": 1_500, "total": -16.19}]
    drift = collateral_drift(rows, attribution)

    assert drift["enforced"]
    assert round(drift["equity_change"], 2) == -60.11
    assert round(drift["attributed_pnl"], 2) == -16.19
    assert round(drift["collateral_repricing"], 2) == -43.92
    # Both parts pushed the same way here, so the account's sign did tell you the book's sign.
    assert drift["direction"] == "same_direction"
    assert drift["account_misleads"] is False


def test_the_three_parts_add_up_on_every_window_it_can_read() -> None:
    """The property the old level-assertion was standing in for, stated as what it is.

    `repricing_share` is a ratio of two numbers this function returns, so the only thing that could
    ever be wrong is the decomposition itself.  Checked across four windows of different shapes -
    losing, rising, book-and-collateral-agreeing, book-and-collateral-opposed - because a bug that
    survives one sign is not a bug that survives all four.
    """
    windows = [
        (10_964.21, 10_904.10, -16.19),  # 2026-09-07: both down
        (10_000.00, 10_036.41, -2.48),  # 2026-09-09: equity up, book down
        (10_000.00, 9_900.00, -150.00),  # book lost more than the account shows
        (10_000.00, 10_500.00, 500.00),  # the collateral did nothing
    ]
    for start, end, attributed in windows:
        drift = collateral_drift(
            [_cycle(1_000, start, start / 2), _cycle(2_000, end, end / 2)],
            [{"bar_open_ms": 1_500, "total": attributed}],
        )
        assert abs(drift["attributed_pnl"] + drift["collateral_repricing"] - drift["equity_change"]) < 1e-9
        assert abs(drift["repricing_share"] * drift["equity_change"] - drift["collateral_repricing"]) < 1e-9


def test_the_share_is_not_a_share_of_one_and_says_so_when_it_runs_past_it() -> None:
    """2026-09-09's live shape: equity +36.41 while the book was -2.48, so the share is 106.8%.

    This is the reading the pinned 0.72-0.74 could not have survived being asked about, and it is the
    one that matters: the account went UP while the book went DOWN.  The instrument must be able to
    report a share above 1 rather than clamp it, and must name the crossing rather than leave a reader
    to notice that a percentage went past 100.
    """
    rows = [_cycle(1_000, 10_000.00, 5_000.00), _cycle(2_000, 10_036.41, 5_190.00)]
    drift = collateral_drift(rows, [{"bar_open_ms": 1_500, "total": -2.48}])

    assert round(drift["repricing_share"], 4) == 1.0681
    assert drift["direction"] == "book_opposed"
    assert drift["account_misleads"] is True


def test_a_share_below_zero_is_the_other_disagreement_and_is_not_the_flagged_one() -> None:
    """The collateral moved against the book: the book carried more than the whole move.

    Reported and classified, but NOT flagged, because the equity sign still tells you the book's sign -
    which is the only thing `account_misleads` claims.  Folding the two disagreements together would
    make the flag mean "the parts disagree", and the operator cannot act on that.
    """
    rows = [_cycle(1_000, 10_000.00, 5_000.00), _cycle(2_000, 9_900.00, 4_950.00)]
    drift = collateral_drift(rows, [{"bar_open_ms": 1_500, "total": -150.00}])

    assert drift["repricing_share"] < 0.0
    assert drift["direction"] == "collateral_opposed"
    assert drift["account_misleads"] is False


def test_a_flat_window_is_flat_rather_than_misleading() -> None:
    """No move is not a disagreement about the direction of a move."""
    rows = [_cycle(1, 100.0, 50.0), _cycle(2, 100.0, 40.0)]
    drift = collateral_drift(rows, [])
    assert drift["direction"] == "flat"
    assert drift["account_misleads"] is False


def test_attribution_before_the_window_is_not_counted() -> None:
    """Otherwise a long attribution history would be charged against a short collateral window."""
    rows = [_cycle(5_000, 100.0, 50.0), _cycle(6_000, 90.0, 50.0)]
    stale = [{"bar_open_ms": 1, "total": -999.0}, {"bar_open_ms": 5_500, "total": -4.0}]
    assert collateral_drift(rows, stale)["attributed_pnl"] == -4.0


def test_a_flat_window_reports_no_share_rather_than_zero() -> None:
    """Zero would read as "none of it was collateral", which is the opposite of what it means."""
    rows = [_cycle(1, 100.0, 50.0), _cycle(2, 100.0, 40.0)]
    assert collateral_drift(rows, [])["repricing_share"] is None


def test_it_refuses_rather_than_inventing_a_number_when_the_field_is_too_new() -> None:
    """The same refusal shape as the rest of this module: a window too short says so."""
    assert not collateral_drift([], [])["enforced"]
    assert not collateral_drift([_cycle(1, 100.0, 50.0)], [])["enforced"]
    assert "needs 2 cycles" in collateral_drift([{"bar_open_ms": 1}], [])["reason"]


def test_it_is_reported_and_never_subtracted() -> None:
    """Subtracting it would produce the USDT-denominator book the operator did not choose.

    Checked by shape rather than by grepping the caller: the returned mapping carries no field that a
    sizing path could read as a corrected equity, and the raw equity change is present unmodified.
    """
    rows = [_cycle(1, 200.0, 100.0), _cycle(2, 150.0, 100.0)]
    drift = collateral_drift(rows, [{"bar_open_ms": 1, "total": -10.0}])
    assert drift["equity_change"] == -50.0
    assert not any(key.endswith("adjusted_equity") or key == "equity" for key in drift)


# --- the reader.  Until 2026-09-09 this quantity reached `reports/daily/*.json` and stopped there ----


def _store_with_the_misleading_window(tmp_path: Any) -> Any:
    """A day whose account rose while the book lost, through the real store rather than a payload."""
    from starquant_live.state import StateStore

    base = 1_756_800_000_000  # 2025-09-02T08:00Z
    store = StateStore(tmp_path)
    for index, (equity, usdt) in enumerate(((10_000.00, 5_000.00), (10_036.41, 5_190.00))):
        store.append_cycle(
            {
                "bar_open_ms": base + index * 3_600_000,
                "equity": equity,
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
                "collateral": {
                    "equity": equity,
                    "usdt_equity": usdt,
                    "collateral": equity - usdt,
                    "share": (equity - usdt) / equity,
                },
            }
        )
    store.append_attribution({"bar_open_ms": base + 1_800_000, "total": -2.48, "by_strategy": {}, "by_symbol": {}})
    return store


def test_the_daily_report_renders_it(tmp_path: Any) -> None:
    """It was computed into the JSON payload and never into the markdown, which is what a human reads."""
    from starquant_live.reports import daily_markdown, daily_payload

    payload = daily_payload(_store_with_the_misleading_window(tmp_path), "2025-09-02", {})
    text = daily_markdown(payload)

    assert "RISK-G11" in text
    assert "repricing_share" in text
    # the crossing, spelled out where the reader is rather than left as a number above 100%
    assert "account_misleads" in text


def test_the_crossing_is_a_notice_and_never_an_alert(tmp_path: Any) -> None:
    """It must not page (this file's own third paragraph), and it must not hold `--check` red.

    The operator ruled the denominator on 2026-09-08, so there is nothing to do about the amplifier in
    the next hour; and a standing account property on the paging path re-announces itself every dedup
    window forever, whatever that window is set to - the KILL-R7 shape that created the notices
    channel in the first place.  Crossing 1.0 is still a fact that changed, so it
    belongs in the notices, which print beside the report and touch neither the webhook nor the exit code.
    """
    from starquant_live.reports import daily_alerts, daily_payload

    payload = daily_payload(_store_with_the_misleading_window(tmp_path), "2025-09-02", {})
    alerts, notices = daily_alerts(payload)

    assert not any("抵押品" in line for line in alerts)
    assert any("抵押品" in line and "106.8%" in line for line in notices)


def test_a_window_inside_the_boundary_says_nothing_at_all(tmp_path: Any) -> None:
    """A notice that fires on every ordinary day is the same failure as an alert that does."""
    from starquant_live.reports import daily_alerts, daily_payload
    from starquant_live.state import StateStore

    base = 1_756_800_000_000
    store = StateStore(tmp_path)
    for index, equity in enumerate((10_000.00, 9_939.89)):
        store.append_cycle(
            {
                "bar_open_ms": base + index * 3_600_000,
                "equity": equity,
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
                "collateral": {"equity": equity, "usdt_equity": equity / 2, "collateral": equity / 2, "share": 0.5},
            }
        )
    store.append_attribution({"bar_open_ms": base + 1_800_000, "total": -16.19, "by_strategy": {}, "by_symbol": {}})

    _alerts, notices = daily_alerts(daily_payload(store, "2025-09-02", {}))

    assert not any("抵押品" in line for line in notices)
