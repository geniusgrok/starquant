"""M-002/M-005/M-006/M-008/M-010/M-014: the daily report measures what the plan said it measures."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from starquant_live.probe import ProbeParams
from starquant_live.reports import (
    daily_payload,
    drift_check,
    evidence_window,
    exit_and_pool_events,
    income_drift,
    leg_split,
    margin_and_rejections,
    probe_correlation,
    weekly_markdown,
    weekly_payload,
)
from starquant_live.state import StateStore

HOUR = 3_600_000
BASE = 1_788_000_000_000  # a round bar open time inside 2026-09


def _store(tmp_path: Path, cycles: list[dict], attributions: list[dict] | None = None) -> StateStore:
    store = StateStore(tmp_path / "live")
    for row in cycles:
        store.append_cycle(row)
    for row in attributions or []:
        store.append_attribution(row)
    return store


def _cycle(i: int, *, construction: str = "aaa", equity: float = 10_000.0, **extra: object) -> dict:
    return {"bar_open_ms": BASE + i * HOUR, "bar": f"bar-{i}", "equity": equity, "construction": construction, **extra}


def _aligned(i: int, equity: float, **extra: object) -> dict:
    """Like `_cycle`, but starting at a UTC midnight so a three-bar giveback cannot straddle a day boundary."""
    start = BASE - BASE % (24 * HOUR) + 24 * HOUR
    return {"bar_open_ms": start + i * HOUR, "bar": f"bar-{i}", "equity": equity, "construction": "aaa", **extra}


def test_evidence_window_starts_at_the_current_construction(tmp_path: Path) -> None:
    """Changing the band or a signal parameter resets what the live record is evidence of."""
    cycles = [_cycle(i, construction="old") for i in range(5)] + [_cycle(i, construction="new") for i in range(5, 9)]
    window = evidence_window(_store(tmp_path, cycles))
    assert window["construction"] == "new" and window["bars"] == 4
    assert window["since_ms"] == BASE + 5 * HOUR
    assert window["changes_7d"] == 1, "one change inside the trailing week"


def test_evidence_window_counts_every_promotion_in_the_week(tmp_path: Path) -> None:
    """The plan allowed one promotion per week and nothing counted them; two landed on 2026-09-04."""
    cycles = [_cycle(0, construction="a"), _cycle(1, construction="b"), _cycle(2, construction="c")]
    assert evidence_window(_store(tmp_path, cycles))["changes_7d"] == 2


def test_evidence_window_is_empty_without_fingerprints(tmp_path: Path) -> None:
    window = evidence_window(_store(tmp_path, [{"bar_open_ms": BASE, "equity": 1.0}]))
    assert window["construction"] is None and window["bars"] == 0


def test_income_drift_is_per_strategy_and_uses_income_not_equity(tmp_path: Path) -> None:
    """M-010: equity here is multi-asset collateral and one number for two books; income is neither."""
    attributions = [{"bar_open_ms": BASE + i * HOUR, "by_strategy": {"tsmom": 1.0, "flow": -0.5}} for i in range(60)]
    store = _store(tmp_path, [_cycle(i) for i in range(60)], attributions)
    result = income_drift(store, {"tsmom": {"oos_sharpe": 1.5}}, equity=10_000.0, since_ms=None)
    rows = result["by_strategy"]
    assert set(rows) == {"tsmom", "flow"}, "each strategy is measured on its own"
    assert rows["tsmom"]["bars"] == 60 and rows["tsmom"]["pnl"] == pytest.approx(60.0)
    assert rows["flow"]["expected_sharpe"] is None, "a strategy without an expectation is reported, not judged"
    assert income_drift(store, {}, equity=None, since_ms=None)["status"] == "INSUFFICIENT_DATA"
    # a constant series has no dispersion, so no Sharpe: the metric refuses rather than inventing one
    assert rows["tsmom"]["realised_sharpe"] is None


def test_income_drift_alerts_when_a_strategy_falls_two_standard_errors_short(tmp_path: Path) -> None:
    rng = __import__("numpy").random.default_rng(3)
    values = list(rng.normal(-0.002, 0.01, 24 * 40))
    attributions = [
        {"bar_open_ms": BASE + i * HOUR, "by_strategy": {"tsmom": v * 10_000}} for i, v in enumerate(values)
    ]
    store = _store(tmp_path, [_cycle(i) for i in range(len(values))], attributions)
    result = income_drift(store, {"tsmom": {"oos_sharpe": 1.6}}, equity=10_000.0, since_ms=None)
    assert result["status"] == "ALERT"
    assert result["by_strategy"]["tsmom"]["z"] < -2.0


def test_income_drift_respects_the_evidence_window(tmp_path: Path) -> None:
    attributions = [{"bar_open_ms": BASE + i * HOUR, "by_strategy": {"tsmom": 1.0}} for i in range(100)]
    store = _store(tmp_path, [_cycle(i) for i in range(100)], attributions)
    assert income_drift(store, {}, equity=10_000.0, since_ms=BASE + 90 * HOUR)["by_strategy"]["tsmom"]["bars"] == 10


def test_leg_split_uses_the_sign_of_the_target_that_bar(tmp_path: Path) -> None:
    """M-008: the backtest earned more on the short leg; live has to be able to say whether it does too."""
    cycles = [_cycle(0, targets={"A": 0.05, "B": -0.03, "C": 0.0})]
    attributions = [
        {
            "bar_open_ms": BASE,
            "by_symbol": {"A": {"total": 2.0}, "B": {"total": 5.0}, "C": {"total": -1.0}},
        }
    ]
    result = leg_split(_store(tmp_path, cycles, attributions), since_ms=None, equity=10_000.0)
    assert result["pnl"] == {"long": 2.0, "short": 5.0, "flat": -1.0}
    assert result["symbol_bars"] == {"long": 1, "short": 1, "flat": 1}
    assert result["pnl_pct"]["short"] == pytest.approx(0.0005)


def test_probe_correlation_exposes_a_sleeve_that_is_really_a_tilt(tmp_path: Path) -> None:
    """91% of the flow sleeve's positions stacked on tsmom's shorts in the backtest (round 5)."""
    attributions = [
        {"bar_open_ms": BASE + i * HOUR, "by_strategy": {"tsmom": float(i % 7) - 3.0, "flow": float(i % 7) - 3.0}}
        for i in range(30)
    ]
    store = _store(tmp_path, [_cycle(i) for i in range(30)], attributions)
    probes = (ProbeParams(book="flow_short", strategy="flow"),)
    result = probe_correlation(store, probes, since_ms=None)
    assert result["flow~tsmom"]["correlation"] == pytest.approx(1.0), "a perfect tilt reads as correlation 1"
    assert result["flow~tsmom"]["bars"] == 30
    thin = probe_correlation(_store(tmp_path / "b", [_cycle(0)], attributions[:3]), probes, since_ms=None)
    assert thin["flow~tsmom"]["correlation"] is None


def test_exit_and_pool_events_reach_the_report(tmp_path: Path) -> None:
    """Both lived only in cycles.jsonl before; the daily report never mentioned either."""
    day = "2026-09-04"
    rows = [
        {
            "bar_open_ms": BASE,
            "at": f"{day}T01:00:00+00:00",
            "bar": "b0",
            "equity": 1.0,
            "exit_events": [{"symbol": "A", "rule": "TAKE_PROFIT"}, {"symbol": "B", "rule": "TAKE_PROFIT"}],
            "universe_update": {"entered": ["NEW"], "left": ["OLD"]},
        }
    ]
    result = exit_and_pool_events(_store(tmp_path, rows), _day_of_bar(BASE))
    assert result["exit_count"] == 2 and result["by_rule"] == {"TAKE_PROFIT": 2}
    assert result["pool_entered"] == ["NEW"] and result["pool_left"] == ["OLD"] and result["pool_changes"] == 2


def test_exit_and_pool_events_ignore_dry_run_cycles(tmp_path: Path) -> None:
    """This is the same M-005 exit list `exit_counterfactuals` excludes dry runs from, a few sections higher.

    A `--dry-run` cycle submits no order (engine.py: DRY_RUN), so its `exit_events` name exits that never
    happened.  Counted here they inflate `exit_count` and `by_rule` in the very report whose counterfactual
    section is carefully counting only real exits toward `n_needed_for_decision`.  The filter is on the row,
    so the dry run's `universe_update` line goes with it.
    """
    real = {
        "bar_open_ms": BASE,
        "bar": "b0",
        "equity": 1.0,
        "exit_events": [{"symbol": "A", "rule": "TAKE_PROFIT"}],
        "universe_update": {"entered": ["NEW"], "left": []},
    }
    simulated = {
        "bar_open_ms": BASE + HOUR,
        "bar": "b1",
        "equity": 1.0,
        "dry_run": True,
        "exit_events": [{"symbol": "B", "rule": "STOP_LOSS"}],
        "universe_update": {"entered": ["GHOST"], "left": []},
    }
    result = exit_and_pool_events(_store(tmp_path, [real, simulated]), _day_of_bar(BASE))
    assert result["exit_count"] == 1 and result["by_rule"] == {"TAKE_PROFIT": 1}
    assert [event["symbol"] for event in result["exits"]] == ["A"]
    assert result["pool_entered"] == ["NEW"] and result["pool_changes"] == 1


def _day_of_bar(bar_ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(bar_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def test_noise_scale_reads_a_giveback_in_design_sigma(tmp_path: Path) -> None:
    """DL-EX0: a 65 U giveback on a 10,949 U book at vol_target 0.30 is 0.38 design daily sigma, not an event."""
    from starquant_live.reports import BACKTEST_EXITS_PER_WEEK, noise_scale

    path = [10_704.0 + 5.0 * i for i in range(60)] + [11_014.0, 10_979.0, 10_949.0]
    cycles = [_aligned(i, value) for i, value in enumerate(path)]  # bars 48-62 share the third UTC day
    day = _day_of_bar(cycles[60]["bar_open_ms"])
    result = noise_scale(_store(tmp_path, cycles), day, vol_target=0.30)
    assert abs(result["design_daily_sigma_u"] - 10_949.0 * 0.30 / math.sqrt(365.0)) < 1e-6
    assert result["peak_giveback_u"] == pytest.approx(65.0)
    assert result["giveback_in_design_sigma"] == pytest.approx(65.0 / (10_949.0 * 0.30 / math.sqrt(365.0)))
    assert result["realised_daily_sigma_u"] is not None
    assert result["expected_exits_so_far"] == pytest.approx(BACKTEST_EXITS_PER_WEEK / 7 * (63 / 24))
    assert result["exits_so_far"] == 0


def test_noise_scale_without_vol_target_or_cycles_does_not_crash(tmp_path: Path) -> None:
    from starquant_live.reports import noise_scale

    empty = noise_scale(_store(tmp_path, []), "2026-09-07", vol_target=None)
    assert empty["design_daily_sigma_u"] is None and empty["peak_giveback_u"] is None
    assert empty["giveback_since_hwm_u"] is None and empty["giveback_since_hwm_hours"] is None
    assert empty["giveback_since_hwm_in_horizon_sigma"] is None and empty["equity_hwm_u"] is None


def test_noise_scale_measures_the_giveback_from_the_loops_own_high_water_mark(tmp_path: Path) -> None:
    """DL-GB0: the fall the operator sees starts at the HWM, and the HWM is older than today.

    The day-inside ruler reads 140 U here and the account has given back 440 U, for no reason other than
    that the high was set yesterday - which is exactly the gap that had 2026-09-15's report answering 0.43
    sigma to a question about 1.28.  Three things are pinned: the mark is the loop's `throttle.equity_hwm`
    and not a high recomputed from the equity path; the age of that mark is dated from the earliest cycle
    row CARRYING it; and the horizon sigma shrinks the 24-hour sigma to those hours instead of reading an
    eight-hour fall against a day.

    The heartbeat at bar 21 is the case worth having a test for.  That restart is where the high actually
    happened - it is the shape of the 2026-09-14T20:24Z gap, whose two cycles wrote rows with no equity
    field at all - so the first row that can carry the new mark is bar 22, and `giveback_since_hwm_hours`
    reads 8 and not 9.  Visible, not true; the docstring says so and this is the row that makes it true.
    """
    from starquant_live.reports import noise_scale

    def armed(i: int, equity: float, hwm: float, ladder: float) -> dict:
        return _aligned(i, equity, throttle={"equity_hwm": hwm}, risk_ladder={"drawdown": ladder})

    cycles: list[dict] = [armed(i, 10_000.0, 10_000.0, 0.0) for i in range(21)]
    cycles.append({"bar_open_ms": _aligned(21, 0.0)["bar_open_ms"], "bar": "bar-21", "phase": "ERROR"})
    cycles += [armed(22, 10_900.0, 11_000.0, -0.01), armed(23, 10_850.0, 11_000.0, -0.01)]
    day_two = [10_690.0, 10_680.0, 10_700.0, 10_650.0, 10_600.0, 10_580.0, 10_560.0]
    cycles += [armed(24 + n, value, 11_000.0, -0.02) for n, value in enumerate(day_two)]

    result = noise_scale(_store(tmp_path, cycles), _day_of_bar(int(cycles[-1]["bar_open_ms"])), vol_target=0.30)
    design = 10_560.0 * 0.30 / math.sqrt(365.0)
    assert result["peak_giveback_u"] == pytest.approx(140.0), "the day-inside ruler only sees 10,700 -> 10,560"
    assert result["equity_hwm_u"] == pytest.approx(11_000.0)
    assert result["giveback_since_hwm_u"] == pytest.approx(440.0)
    assert result["giveback_since_hwm_in_design_sigma"] == pytest.approx(440.0 / design)
    assert result["giveback_since_hwm_hours"] == pytest.approx(8.0)
    assert result["giveback_since_hwm_in_horizon_sigma"] == pytest.approx(440.0 / (design * math.sqrt(8.0 / 24.0)))
    assert result["drawdown_vs_hwm_pct"] == pytest.approx(0.04)
    assert result["ladder_drawdown_pct"] == pytest.approx(-0.02), "R8's ruler is copied with the sign it was written"


def test_noise_scale_does_not_report_a_negative_giveback_above_the_mark(tmp_path: Path) -> None:
    """A cycle that sets a new high writes the mark and the equity in the same row, so the fall is 0, not -0.

    The floor matters because the mark is read off the row and the equity off the same row: without it a
    book making new highs would print a negative giveback and a negative sigma, which reads as a gain on a
    ruler that only measures losses.  The mark being one bar old also makes the age 0 hours, and a 0-hour
    horizon has no sigma to divide by - reported as absent rather than as an infinity.
    """
    from starquant_live.reports import noise_scale

    cycles = [_aligned(i, 10_000.0 + i, throttle={"equity_hwm": 10_000.0 + i}) for i in range(30)]
    result = noise_scale(_store(tmp_path, cycles), _day_of_bar(int(cycles[-1]["bar_open_ms"])), vol_target=0.30)
    assert result["giveback_since_hwm_u"] == pytest.approx(0.0)
    assert result["giveback_since_hwm_in_design_sigma"] == pytest.approx(0.0)
    assert result["giveback_since_hwm_hours"] == pytest.approx(0.0)
    assert result["giveback_since_hwm_in_horizon_sigma"] is None
    assert result["ladder_drawdown_pct"] is None, "no ladder block on the row means no reading, not a zero"


def test_noise_scale_restates_the_giveback_on_the_operators_usdt_ruler(tmp_path: Path) -> None:
    """A-GB01: the operator reads the venue's USDT equity, so the same fall is a bigger percentage.

    Everything pinned here is a CONVERSION of a number measured above it.  The numerator is still the fall
    from `throttle.equity_hwm`, measured on total equity; only the denominator becomes
    `collateral.usdt_equity`.  The account is half collateral in this fixture, so the same 1,000 U reads
    20.00% on the operator's screen and 10.00% against equity - a 2x gap that is entirely the denominator
    and not a disagreement about what happened.

    The two fixtures differ in the direction a bug would take: the earlier rows carry a DIFFERENT USDT
    balance, so a reader that took the first recorded split rather than the day's last cycle fails here,
    and the ladder/HWM keys are asserted unchanged so a future edit cannot quietly move a numerator onto
    the USDT series - which would be a fourth high-water mark, the thing this key exists not to become.
    """
    from starquant_live.reports import noise_scale

    def armed(i: int, equity: float, usdt: float) -> dict:
        return _aligned(
            i,
            equity,
            throttle={"equity_hwm": 11_000.0},
            collateral={"equity": equity, "usdt_equity": usdt, "collateral": equity - usdt, "share": 1 - usdt / equity},
        )

    cycles = [armed(i, 10_600.0, 6_000.0) for i in range(29)] + [armed(29, 10_000.0, 5_000.0)]
    result = noise_scale(_store(tmp_path, cycles), _day_of_bar(int(cycles[-1]["bar_open_ms"])), vol_target=0.30)

    design = 10_000.0 * 0.30 / math.sqrt(365.0)
    assert result["usdt_equity_u"] == pytest.approx(5_000.0), "the day's last cycle, not the first split recorded"
    assert result["giveback_since_hwm_u"] == pytest.approx(1_000.0), "the numerator stays on total equity"
    assert result["giveback_since_hwm_in_usdt_pct"] == pytest.approx(1_000.0 / 5_000.0)
    assert result["giveback_since_hwm_in_usdt_pct"] != pytest.approx(1_000.0 / 10_000.0), "denominator is USDT equity"
    assert result["design_daily_sigma_in_usdt_pct"] == pytest.approx(design / 5_000.0)
    assert result["design_daily_sigma_in_usdt_pct"] != pytest.approx(design / 10_000.0), "not the equity line"
    assert result["design_daily_sigma_u"] == pytest.approx(design), "the sigma itself is unchanged by the restatement"
    assert result["equity_hwm_u"] == pytest.approx(11_000.0), "no high-water mark is recomputed on the USDT series"
    assert result["drawdown_vs_hwm_pct"] == pytest.approx(1_000.0 / 11_000.0), "the equity ruler still reads its own"


def test_noise_scale_reports_no_usdt_ruler_when_the_venue_did_not_report_one(tmp_path: Path) -> None:
    """Three keys absent beats three keys wrong: a missing USDT balance is not a zero balance.

    Two silences reach here by different routes - a row written before the engine recorded the split at
    all (no `collateral` key), and a row whose `collateral` block exists with `usdt_equity: None` because
    the venue payload carried no USDT asset.  `collateral_share` already refuses to call the second one
    zero, and dividing by either would print an infinity or a 0.00% where the honest answer is "n/a".
    """
    from starquant_live.reports import noise_scale

    day = _day_of_bar(int(_aligned(29, 0.0)["bar_open_ms"]))
    for n, cycles in enumerate(
        (
            [_aligned(i, 10_000.0, throttle={"equity_hwm": 11_000.0}) for i in range(30)],
            [
                _aligned(
                    i,
                    10_000.0,
                    throttle={"equity_hwm": 11_000.0},
                    collateral={"equity": 10_000.0, "usdt_equity": None, "collateral": None, "share": None},
                )
                for i in range(30)
            ],
        )
    ):
        result = noise_scale(_store(tmp_path / f"case{n}", cycles), day, vol_target=0.30)
        assert result["usdt_equity_u"] is None
        assert result["design_daily_sigma_in_usdt_pct"] is None
        assert result["giveback_since_hwm_in_usdt_pct"] is None
        assert result["giveback_since_hwm_u"] == pytest.approx(1_000.0), "the rulers above it still read"


def test_noise_scale_does_not_count_a_cooldown_as_an_exit(tmp_path: Path) -> None:
    """`ExitOverlay.apply` appends an event for every truthy reason, and `exit_step` returns COOLDOWN once per
    *blocked* cycle, so at the live `cooldown_bars: 24` a single take-profit writes 24 more rows behind it.
    `BACKTEST_EXITS_PER_WEEK` is derived from 544 take-profits plus 18 stops - `apply_exits` never emits
    COOLDOWN at all - so counting them prints an expected and an actual up to 25x apart on denominators that
    do not mean the same thing.  `exit_counterfactuals` already drops them; this number did not.
    """
    from starquant_live.reports import noise_scale

    cycles = [_aligned(i, 10_000.0) for i in range(48)]
    cycles[10]["exit_events"] = [{"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "price": 100.0}]
    for i in range(11, 35):  # the 24 cycles the one take-profit blocked
        cycles[i]["exit_events"] = [{"symbol": "AAAUSDT", "rule": "COOLDOWN", "price": 100.0}]
    day = _day_of_bar(int(cycles[10]["bar_open_ms"]))
    result = noise_scale(_store(tmp_path, cycles), day, vol_target=0.30)
    assert result["exits_so_far"] == 1, "one take-profit and the 24 cycles it blocked is one exit"


def test_noise_scale_counts_exits_over_the_window_it_scales_the_expectation_by(tmp_path: Path) -> None:
    """The two exit counts printed side by side have to be on one window, or their ratio means nothing.

    `expected_exits_so_far` pro-rates the backtest rate by `evidence_window(...)["bars"]` - every cycle under
    the current construction, over all history - while the actual count read only `_cycles(window_days=30)`,
    the last 720 rows.  They agree until the window passes 720 bars and then silently diverge, and 720 bars
    is exactly the state K-EX14's clean-window rule is working toward.
    """
    from starquant_live.reports import BACKTEST_EXITS_PER_WEEK, noise_scale

    cycles = [_aligned(i, 10_000.0) for i in range(960)]
    for i in range(0, 960, 96):  # ten real exits; only the seven at bar >= 240 fall inside a 720-bar tail
        cycles[i]["exit_events"] = [{"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "price": 100.0}]
    day = _day_of_bar(int(cycles[-1]["bar_open_ms"]))
    result = noise_scale(_store(tmp_path, cycles), day, vol_target=0.30)
    assert result["expected_exits_so_far"] == pytest.approx(BACKTEST_EXITS_PER_WEEK / 7 * (960 / 24))
    assert result["exits_so_far"] == 10, "the evidence window holds ten, the trailing 30 days only seven"


def test_exit_counterfactuals_mark_young_events_pending_and_price_old_ones(tmp_path: Path) -> None:
    """M-005 as monitoring (K-EX12): what the exited position would have earned had it stayed in."""
    import pandas as pd

    from starquant_live.reports import exit_counterfactuals

    event = {
        "symbol": "AAAUSDT",
        "rule": "TAKE_PROFIT",
        "target": 0.05,
        "price": 100.0,
        "entry_price": 90.0,
        "unit": 0.02,
    }
    cycles = [_cycle(0, equity=10_000.0, exit_events=[event])] + [_cycle(i, equity=10_000.0) for i in range(1, 100)]
    young = [_cycle(i, equity=10_000.0) for i in range(0, 10)]
    young[5] = _cycle(5, equity=10_000.0, exit_events=[event])
    close_series = {
        "AAAUSDT": pd.Series(
            [100.0 * (1.0 + 0.001 * i) for i in range(200)], index=[BASE + i * HOUR for i in range(200)]
        )
    }
    priced = exit_counterfactuals(_store(tmp_path / "a", cycles), closes=lambda symbol: close_series[symbol])
    assert priced["events"] == 1 and priced["pending"] == 0
    # stayed in: 0.05 x 10,000 x (close_{t+24}/close_t - 1) = 500 x 0.024 = 12.0 U; the exit paid 2 x 7 bps x 500 = 0.7 U
    assert priced["by_horizon"]["24"]["mean_counterfactual_u"] == pytest.approx(12.0)
    assert priced["by_horizon"]["72"]["mean_counterfactual_u"] == pytest.approx(36.0)
    assert priced["by_horizon"]["24"]["n"] == 1 and priced["cost_saved_u"] == pytest.approx(0.7)
    pending = exit_counterfactuals(_store(tmp_path / "b", young), closes=lambda symbol: close_series[symbol].iloc[:8])
    assert pending["events"] == 1 and pending["pending"] == 1 and pending["by_horizon"]["24"]["n"] == 0
    assert priced["n_needed_for_decision"] == 16


def test_exit_counterfactuals_ignore_dry_run_cycles(tmp_path: Path) -> None:
    """A --dry-run cycle's exits never happened, and must not be priced against real closes.

    `exit_counterfactuals` walked `cycles.jsonl` raw, unlike `_cycles` and `drift_check`, which filter
    `dry_run`.  The filter is a property of each call site rather than of the file, so several other readers
    of the same file still do not have it; those are recorded and deliberately deferred, not closed here.  A
    dry run pointed at the live `state_dir` - the cross-worktree path collision DL-L1's lock guards against
    elsewhere - would have folded simulated exits into the one count M-005 keeps honest before a verdict is
    drawn, which is what `n_needed_for_decision` is counting toward.
    """
    import pandas as pd

    from starquant_live.reports import exit_counterfactuals

    event = {"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "target": 0.05, "price": 100.0, "unit": 0.02}
    live = [_cycle(0, equity=10_000.0, exit_events=[event])] + [_cycle(i, equity=10_000.0) for i in range(1, 100)]
    mixed = [*live]
    mixed[5] = _cycle(5, equity=10_000.0, exit_events=[event], dry_run=True)
    closes = pd.Series([100.0 * (1.0 + 0.001 * i) for i in range(200)], index=[BASE + i * HOUR for i in range(200)])

    only_dry = exit_counterfactuals(_store(tmp_path / "a", [mixed[5]]), closes=lambda _symbol: closes)
    assert only_dry["events"] == 0 and only_dry["pending"] == 0
    assert only_dry["cost_saved_u"] == 0.0
    assert only_dry["by_horizon"]["24"]["n"] == 0 and only_dry["by_horizon"]["24"]["mean_counterfactual_u"] is None

    # the dry-run bar is the only difference between the two stores, so every number has to match
    both = exit_counterfactuals(_store(tmp_path / "b", mixed), closes=lambda _symbol: closes)
    real = exit_counterfactuals(_store(tmp_path / "c", live), closes=lambda _symbol: closes)
    assert both["events"] == real["events"] == 1
    assert both["cost_saved_u"] == pytest.approx(0.7)
    assert both["cost_saved_u"] == pytest.approx(real["cost_saved_u"])
    assert both["by_horizon"] == real["by_horizon"]


def test_exit_counterfactuals_anchor_the_horizon_on_the_bar_the_data_carried(tmp_path: Path) -> None:
    """The event's `price` is the close at `as_of_ms`; `bar_open_ms` is the host's own idea of the bar.

    D-025 recorded the host sitting a full hour behind the venue on 2026-09-04, and `_day_of` in this same
    module already prefers `as_of_ms` for that reason.  Anchoring the counterfactual on the host clock walks
    the horizon from a bar the price did not come from - a 23-bar hold priced as a 24-bar one - which is a
    silent misprice of the one number M-005 will be judged on.
    """
    import pandas as pd

    from starquant_live.reports import exit_counterfactuals

    event = {"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "target": 0.05, "price": 100.0, "unit": 0.02}
    # the host runs one bar ahead of the venue: `as_of_ms` is the bar the klines actually closed on
    cycles = [_cycle(0, equity=10_000.0, as_of_ms=BASE - HOUR, exit_events=[event])]
    cycles += [_cycle(i, equity=10_000.0, as_of_ms=BASE + (i - 1) * HOUR) for i in range(1, 100)]
    closes = pd.Series(
        [100.0 * (1.0 + 0.001 * i) for i in range(200)], index=[BASE - HOUR + i * HOUR for i in range(200)]
    )

    priced = exit_counterfactuals(_store(tmp_path, cycles), closes=lambda _symbol: closes)
    # 0.05 x 10,000 x (close_{as_of + 24h}/100 - 1) = 500 x 0.024 = 12.0 U; off the host clock it is 12.5
    assert priced["events"] == 1 and priced["pending"] == 0
    assert priced["by_horizon"]["24"]["mean_counterfactual_u"] == pytest.approx(12.0)
    assert priced["by_horizon"]["72"]["mean_counterfactual_u"] == pytest.approx(36.0)
    assert priced["rows"][0]["as_of_ms"] == BASE - HOUR


def test_exit_counterfactuals_survive_a_truncated_parquet(tmp_path: Path) -> None:
    """A zero-byte or half-written parquet raises `pyarrow.lib.ArrowInvalid`, not `FileNotFoundError`.

    `data_coverage`, twenty lines away in the same module, catches broad `Exception` off the same store for
    the stated reason that a missing store is a research problem and never a reporting failure.  The narrow
    catch here let a truncated file propagate out of `report daily` and stop the unattended monitor - the one
    instrument that would have said so.
    """
    from starquant_live.reports import exit_counterfactuals

    event = {"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "target": 0.05, "price": 100.0, "unit": 0.02}
    cycles = [_cycle(0, equity=10_000.0, exit_events=[event])] + [_cycle(i, equity=10_000.0) for i in range(1, 100)]
    archive = tmp_path / "data" / "klines" / "AAAUSDT"
    archive.mkdir(parents=True)
    (archive / "1h.parquet").write_bytes(b"")  # the shape an interrupted append leaves behind

    result = exit_counterfactuals(_store(tmp_path / "live", cycles), root=tmp_path / "data")
    assert result["events"] == 1 and result["pending"] == 1
    assert result["by_horizon"]["24"]["n"] == 0
    assert result["cost_saved_u"] == pytest.approx(0.7), "the fee is known without any price series"


def test_drift_check_skips_bars_whose_clock_jumped(tmp_path: Path) -> None:
    """M-012 promised it; the bars were recorded but still counted as returns."""
    clean = [_cycle(i, equity=10_000.0 + i) for i in range(60)]
    jumped = [
        *clean[:30],
        _cycle(30, equity=99_999.0, clock={"jumped": True}),
        *[_cycle(i, equity=10_000.0 + i) for i in range(31, 60)],
    ]
    expectations = {"tsmom": {"oos_sharpe": 1.5, "full_sample_max_drawdown": -0.13}}
    without = drift_check(_store(tmp_path / "a", clean), expectations)
    with_jump = drift_check(_store(tmp_path / "b", jumped), expectations)
    assert without["status"] != "INSUFFICIENT_DATA"
    assert with_jump["trailing_drawdown"] == pytest.approx(without["trailing_drawdown"], abs=1e-9)


def test_daily_payload_carries_every_new_section(tmp_path: Path) -> None:
    day = _day_of_bar(BASE)
    cycles = [
        {**_cycle(i), "at": f"{day}T0{i}:00:00+00:00", "targets": {"A": 0.1}, "exit_events": [], "universe_update": {}}
        for i in range(3)
    ]
    attributions = [
        {
            "bar_open_ms": BASE + i * HOUR,
            "at": f"{day}T0{i}:00:00+00:00",
            "by_strategy": {"tsmom": 1.0},
            "by_symbol": {"A": {"total": 1.0}},
        }
        for i in range(3)
    ]
    payload = daily_payload(_store(tmp_path, cycles, attributions), day, {"tsmom": {"oos_sharpe": 1.6}})
    for key in ("evidence_window", "income_drift", "legs", "probe_correlation", "events"):
        assert key in payload, key
    assert "noise_scale" in payload and "exit_counterfactual" in payload
    assert payload["legs"]["pnl"]["long"] == pytest.approx(3.0)
    assert json.dumps(payload, default=str)
    assert math.isfinite(payload["legs"]["pnl"]["long"])


def test_margin_peak_and_rejections_are_counted(tmp_path: Path) -> None:
    """M-007: the margin block existed and no series was ever taken from it; -2019 was indistinguishable."""
    cycles = [
        _cycle(0, equity=10_000.0, margin={"needed_margin": 500.0}),
        _cycle(1, equity=10_000.0, margin={"needed_margin": 6_000.0}),
        _cycle(2, equity=10_000.0, margin={"needed_margin": 100.0}),
    ]
    store = _store(tmp_path, cycles)
    for row in (
        {"bar_open_ms": BASE + HOUR, "status": "REJECTED", "error": "-2019: Margin is insufficient"},
        {"bar_open_ms": BASE + HOUR, "status": "REJECTED", "error": "-1111: Precision is over the maximum"},
        {"bar_open_ms": BASE + HOUR, "status": "FILLED", "error": "already submitted for this bar"},
    ):
        store.append_trade(row)
    result = margin_and_rejections(store, since_ms=None)
    assert result["peak_margin_usage"] == pytest.approx(0.6) and result["over_budget"] is True
    assert result["peak_at_bar_ms"] == BASE + HOUR
    assert result["insufficient_margin"] == 1, "a -2019 is distinguishable from a lot-size error"
    assert result["rejections"]["-1111"] == 1
    assert "already submitted for this bar" not in result["rejections"], "a filled order is not a rejection"


def test_weekly_report_puts_the_weeks_promotions_next_to_the_weeks_evidence(tmp_path: Path) -> None:
    """The plan listed a weekly research report as a deliverable and it was never built."""
    day = _day_of_bar(BASE + 3 * 24 * HOUR)
    cycles = [_cycle(i, construction="a" if i < 40 else "b") for i in range(80)]
    attributions = [{"bar_open_ms": BASE + i * HOUR, "by_strategy": {"tsmom": 0.5}} for i in range(80)]
    payload = weekly_payload(_store(tmp_path, cycles, attributions), day, expectations={"tsmom": {"oos_sharpe": 1.7}})
    assert payload["cycles"] == 80 and payload["promotions"] == 1
    assert payload["promotion_budget"] == 1 and len(payload["constructions_seen"]) == 2
    assert payload["evidence_window"]["construction"] == "b"
    assert "tsmom" in payload["income"]["by_strategy"]
    markdown = weekly_markdown(payload)
    assert "Promotions this week" in markdown and "M-007" in markdown


def test_weekly_report_flags_a_week_that_broke_the_promotion_budget(tmp_path: Path) -> None:
    """Two promotions landed on 2026-09-04 and nothing said so."""
    day = _day_of_bar(BASE)
    cycles = [_cycle(0, construction="a"), _cycle(1, construction="b"), _cycle(2, construction="c")]
    payload = weekly_payload(_store(tmp_path, cycles), day)
    assert payload["promotions"] == 2 > payload["promotion_budget"]
    assert "within_budget | no" in weekly_markdown(payload)


def test_effort_share_measures_new_work_not_the_accumulated_tree() -> None:
    """The 90% target governs the next line written; the tree's 22% is sunk (operator decision 2026-09-04)."""
    from starquant_live.reports import ALPHA_EFFORT_TARGET, effort_share

    result = effort_share(
        {
            "starquant_alpha/signals/tsmom.py": 80,
            "tests/alpha/test_signal_suite.py": 10,
            "docs/RESEARCH_LOG.md": 10,
            "starquant_live/engine.py": 100,
            "reports/research/tsmom-validation-x.json": 5_000,
        }
    )
    assert result["lines"] == {"alpha": 90, "research": 10, "infrastructure": 100}
    assert result["total"] == 200, "generated evidence is not effort"
    assert result["alpha_share"] == pytest.approx(0.5) and result["on_target"] is False
    assert result["target"] == ALPHA_EFFORT_TARGET == 0.90


def test_effort_share_counts_a_test_with_the_thing_it_tests() -> None:
    from starquant_live.reports import effort_share

    assert effort_share({"tests/alpha/test_x.py": 10})["alpha_share"] == 1.0
    assert effort_share({"tests/live/test_x.py": 10})["alpha_share"] == 0.0
    assert effort_share({})["alpha_share"] is None


def _archive(root: Path, *symbols: str, interval: str = "1h") -> Path:
    """A klines archive holding `symbols`.  `KlineStore.symbols` only globs, so empty files suffice."""
    (root / "klines").mkdir(parents=True, exist_ok=True)  # an archive with no symbols is still an archive
    for symbol in symbols:
        (root / "klines" / symbol).mkdir(parents=True, exist_ok=True)
        (root / "klines" / symbol / f"{interval}.parquet").write_bytes(b"")
    return root


def _store_trading(tmp_path: Path, *symbols: str) -> StateStore:
    store = StateStore(tmp_path / "live")
    state = store.load()
    state.universe = list(symbols)
    store.save(state)
    return store


def test_data_coverage_reads_the_data_root_the_report_was_given(tmp_path: Path, monkeypatch) -> None:
    """`data_coverage` exists to name a symbol trading live with no research klines behind it (CYSUSDT,
    sixteen hours).  It resolved `.starquant/data` against the process's cwd rather than `--data-root`, so
    run from anywhere but the repo root it answered about an archive nobody was trading against.

    Both directions are pinned, because the failure is silent in each: the wrong root invents missing
    symbols, and - as this test arranges - it can equally well clear a symbol that is genuinely absent
    from the archive actually in use.
    """
    cwd = tmp_path / "cwd"
    _archive(cwd / ".starquant" / "data", "AAAUSDT")  # the default the old call resolved to
    monkeypatch.chdir(cwd)
    payload = daily_payload(
        _store_trading(tmp_path, "AAAUSDT"), _day_of_bar(BASE), data_root=_archive(tmp_path / "elsewhere")
    )
    assert payload["data_coverage"]["missing_klines"] == ["AAAUSDT"]
    assert payload["data_coverage"]["missing_count"] == 1


def test_data_coverage_does_not_flag_a_symbol_present_under_the_given_data_root(tmp_path: Path, monkeypatch) -> None:
    """The companion direction: the archive named by `--data-root` holds the symbol, so nothing is missing."""
    cwd = tmp_path / "cwd"
    _archive(cwd / ".starquant" / "data")  # the cwd default is empty; only the passed root has the klines
    monkeypatch.chdir(cwd)
    payload = daily_payload(
        _store_trading(tmp_path, "AAAUSDT"),
        _day_of_bar(BASE),
        data_root=_archive(tmp_path / "archive", "AAAUSDT"),
    )
    assert payload["data_coverage"]["missing_klines"] == []
    assert payload["data_coverage"]["live_symbols"] == 1
