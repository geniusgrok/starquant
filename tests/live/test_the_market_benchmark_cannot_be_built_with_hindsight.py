"""D-045: the traps that produced four different answers to one question, each pinned by a test.

Every case here is a mistake this repository actually made on 2026-09-19 while answering "is the live
book's return the market's or the signal's", not a hypothetical.  The numbers in the assertions are
the shapes of those mistakes, so a regression reads as the wrong answer coming back.

2026-09-22 added a fifth, found while re-checking the same question three days later: `NW_LAGS` and
`MIN_BARS` were both 48, so a window that just cleared the minimum ran a Bartlett kernel as wide as
its own sample.  A 55-bar window read alpha t = **5.49** that way, against 2.23 on plain OLS - the
correction shrank the standard error threefold instead of widening it, and 5.49 would have read as
"the signal finally shows".  See `MAX_LAG_SHARE` for where the boundary was measured.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
import pytest

from starquant_live.benchmark import (
    MAX_LAG_SHARE,
    MIN_BARS,
    NW_LAGS,
    _nw_se,
    beta_decomposition,
    foreign_bars,
    pit_benchmark,
    series_from_cycles,
    signal_state,
)
from starquant_live.reports import _beta_regression_lines, beta_markdown

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3_600_000


def _bars(n: int, start: int = 1_789_000_000_000) -> list[int]:
    return [start + i * HOUR for i in range(n)]


def test_a_symbol_that_leaves_the_universe_still_counts_while_it_was_held() -> None:
    """The fixed-basket bug: it dropped AKEUSDT entirely, and AKEUSDT was up 26.4% while held.

    Here LEAVER doubles over the first half and is then dropped from the universe.  A benchmark that
    kept only the symbols present at both ends would read 0%; the point-in-time one has to carry the
    gain it made while it was in the book.
    """
    bars = _bars(5)
    universe = {bar: (["STAY", "LEAVER"] if i < 3 else ["STAY"]) for i, bar in enumerate(bars)}
    prices = {
        "STAY": dict.fromkeys(bars, 100.0),
        # LEAVER: +20% per bar while held, then it is gone from the universe
        "LEAVER": {bar: 100.0 * (1.2**i) for i, bar in enumerate(bars)},
    }

    benchmark = pit_benchmark(bars, universe, prices)

    assert benchmark["level"][-1] > 1.0, "a symbol that left took its gain with it"
    # Two bars held at equal weight with a flat partner: (1 + 0.20/2)^2
    assert benchmark["level"][-1] == pytest.approx(1.1**2, rel=1e-9)
    assert benchmark["prices_missing"] == 0


def test_a_symbol_entering_the_universe_is_not_a_jump() -> None:
    """A newcomer contributes from its first FULL bar, never from the price it happened to enter at."""
    bars = _bars(4)
    universe = {bars[0]: ["A"], bars[1]: ["A"], bars[2]: ["A", "B"], bars[3]: ["A", "B"]}
    prices = {"A": dict.fromkeys(bars, 50.0), "B": {bars[2]: 10.0, bars[3]: 20.0}}

    level = pit_benchmark(bars, universe, prices)["level"]

    assert level[1] == pytest.approx(1.0) and level[2] == pytest.approx(1.0)
    # B doubles across the last bar and shares the basket with a flat A: +50%
    assert level[3] == pytest.approx(1.5, rel=1e-9)


def test_a_missing_price_is_counted_rather_than_absorbed() -> None:
    """A basket quietly thinning out is the fixed-basket bug wearing a different hat."""
    bars = _bars(3)
    universe = {bar: ["A", "B"] for bar in bars}
    prices = {"A": dict.fromkeys(bars, 10.0), "B": {bars[0]: 10.0}}  # B has no price after bar 0

    benchmark = pit_benchmark(bars, universe, prices)

    assert benchmark["prices_missing"] == 2
    assert benchmark["symbols_per_bar"] == pytest.approx(1.0), "两根 bar 都只剩 A 一个可用"


def test_the_equity_line_is_the_usdt_one_not_total_equity() -> None:
    """A-GB01: collateral repricing moves total equity without the book having traded."""
    bars = _bars(2)
    rows = [
        {"bar_open_ms": bars[0], "collateral": {"usdt_equity": 5_000.0, "equity": 10_000.0}, "targets": {"A": 1.0}},
        {"bar_open_ms": bars[1], "collateral": {"usdt_equity": 5_500.0, "equity": 20_000.0}, "targets": {"A": 1.0}},
    ]

    series = series_from_cycles(rows)

    assert series["equity"] == [5_000.0, 5_500.0], "total equity doubling must not enter the return series"
    # Exposure is rescaled from total equity onto the USDT line: 1.0 x 10,000 / 5,000
    assert series["exposure"][0] == pytest.approx(2.0)


def test_a_restart_writing_the_same_bar_twice_keeps_the_one_that_traded() -> None:
    bars = _bars(2)
    rows = [
        {"bar_open_ms": bars[0], "collateral": {"usdt_equity": 100.0, "equity": 100.0}, "targets": {}},
        {"bar_open_ms": bars[0], "collateral": {"usdt_equity": 111.0, "equity": 111.0}, "targets": {}},
        {"bar_open_ms": bars[1], "collateral": {"usdt_equity": 120.0, "equity": 120.0}, "targets": {}},
    ]

    series = series_from_cycles(rows)

    assert series["bars"] == bars
    assert series["equity"] == [111.0, 120.0]


def test_foreign_fills_are_read_from_the_attribution_rows_not_the_cycles() -> None:
    """The bug this pins: `foreign` is on attribution.jsonl only.

    Reading it off the cycle records returns an empty list with no error, which lets the operator's
    own 2026-09-10 flatten (+268.83 U through one bar) into the strategy's series.
    """
    cycles = [{"bar_open_ms": 1, "foreign": {"total": 268.83}}]
    attribution = [
        {"bar_open_ms": 7, "foreign": {"total": 268.83}},
        {"bar_open_ms": 8, "foreign": {"total": 0.0}},
        {"bar_open_ms": 9, "foreign": {}},
    ]

    assert foreign_bars(attribution) == [7]
    assert foreign_bars(cycles) == [1], "the function itself is agnostic; the caller must pass the right file"


def test_the_signal_section_covers_the_same_bars_as_the_decomposition() -> None:
    """`contributions` predates `collateral.usdt_equity`, so an unbounded read dilutes the share."""
    bars = _bars(4)
    rows = [{"bar_open_ms": bar, "contributions": {"tsmom": {"A": 1.0, "B": 1.0}}} for bar in bars]
    rows[0]["contributions"] = {"tsmom": {"A": 1.0, "B": -1.0}}

    windowed = signal_state(rows, "tsmom", bars[1:])
    unbounded = signal_state(rows, "tsmom")

    assert windowed["bars"] == 3 and windowed["all_long_share"] == pytest.approx(1.0)
    assert unbounded["bars"] == 4 and unbounded["all_long_share"] == pytest.approx(0.75)


def test_an_all_long_stretch_is_named_as_the_constant_long_comparator() -> None:
    """Over these bars no decomposition can attribute anything to the signal, and the report says so."""
    bars = _bars(3)
    rows = [{"bar_open_ms": bar, "contributions": {"tsmom": {"A": 1.0, "B": 1.0, "C": 1.0}}} for bar in bars]

    state = signal_state(rows, "tsmom", bars)

    assert state["all_long_bars"] == 3
    assert state["short_positions"] == 0
    assert state["values"] == {"+1.0": 9}


def test_the_newey_west_t_is_smaller_than_ols_on_autocorrelated_residuals() -> None:
    """OLS put alpha at t=1.83 where NW(48h) put it at 0.61; the first number is an artefact.

    A drifting residual with no market exposure: the market term is pure noise, and the strategy is a
    slow trend.  OLS sees hundreds of independent draws, NW sees a handful of two-day swings.
    """
    n = 300
    bars = _bars(n + 1)
    market = [math.sin(i / 11.0) * 0.004 for i in range(n)]
    drift = [0.0005 + 0.004 * math.sin(i / 40.0) for i in range(n)]  # autocorrelated, mean positive
    strategy_level = [1.0]
    benchmark_level = [1.0]
    for i in range(n):
        strategy_level.append(strategy_level[-1] * math.exp(drift[i]))
        benchmark_level.append(benchmark_level[-1] * math.exp(market[i]))

    result = beta_decomposition(strategy_level, benchmark_level, [1.0] * n, bars=bars)

    assert result["measured"]
    # The point of the test: a positive mean drift with strong autocorrelation must NOT come back as a
    # confident alpha.  Left uncorrected this residual reads as several sigma.
    assert abs(result["constant"]["alpha_t"]) < 2.0


def test_the_annualisation_switch_follows_the_t_in_both_directions() -> None:
    """11 days of noise at t=0.73 compounds to +1766%/yr, which is a decision the data did not make.

    Both directions on purpose: a switch only ever tested on the side it blocks is indistinguishable
    from a field that is always ``None``.
    """
    # MIN_BARS * 4, not * 3: at 3 the Newey-West bandwidth is clamped by `MAX_LAG_SHARE` and
    # annualisation is refused for that reason instead of this one, which would leave the "loud"
    # half of this test passing for the wrong reason.  The switch this test is about is the t; the
    # bandwidth switch has its own tests below.
    n = MIN_BARS * 4
    bars = _bars(n + 1)

    def build(mean: float) -> dict:
        rng = random.Random(20260919)
        strategy_level = [1.0]
        benchmark_level = [1.0]
        for _ in range(n):
            strategy_level.append(strategy_level[-1] * math.exp(mean + rng.gauss(0.0, 0.005)))
            benchmark_level.append(benchmark_level[-1] * math.exp(rng.gauss(0.0, 0.005)))
        return beta_decomposition(strategy_level, benchmark_level, [1.0] * n, bars=bars)

    quiet = build(0.00002)
    assert abs(quiet["constant"]["alpha_t"]) < 2.0
    assert quiet["constant"]["alpha_annualised"] is None, "an insignificant alpha must not be annualised"

    loud = build(0.004)
    assert abs(loud["constant"]["alpha_t"]) > 2.0
    assert loud["constant"]["alpha_annualised"] is not None, "a significant one still gets annualised"


def test_a_window_too_short_to_read_refuses_instead_of_returning_a_number() -> None:
    bars = _bars(6)
    result = beta_decomposition([1.0] * 6, [1.0] * 6, [1.0] * 5, bars=bars)

    assert result["measured"] is False
    assert str(MIN_BARS) in result["reason"]


def test_excluded_bars_leave_the_regression_rather_than_being_zeroed() -> None:
    """A bar whose P&L is not the book's must not contribute a data point at all."""
    n = MIN_BARS * 2
    bars = _bars(n + 1)
    strategy_level = [1.0]
    benchmark_level = [1.0]
    for i in range(n):
        # One enormous bar in the middle, the shape of the operator's flatten
        step = 0.30 if i == n // 2 else 0.001
        strategy_level.append(strategy_level[-1] * math.exp(step))
        benchmark_level.append(benchmark_level[-1] * math.exp(0.001))

    with_it = beta_decomposition(strategy_level, benchmark_level, [1.0] * n, bars=bars)
    without = beta_decomposition(
        strategy_level, benchmark_level, [1.0] * n, excluded_bars=[bars[n // 2 + 1]], bars=bars
    )

    assert without["bars"] == with_it["bars"] - 1
    assert without["strategy_return"] < with_it["strategy_return"]
    assert without["constant"]["alpha_bps_per_hour"] < with_it["constant"]["alpha_bps_per_hour"]


@pytest.mark.skipif(
    not (ROOT / ".starquant" / "live" / "cycles.jsonl").exists(),
    reason="live state is not in this checkout (CI and worktrees)",
)
def test_the_field_names_match_what_the_running_loop_actually_writes() -> None:
    """The fixture trap: invented keys give a dozen tests that agree with each other and with nothing.

    Every assertion above runs on records this file made up.  This one runs on the loop's own output,
    so a rename in `cycle_record` surfaces here instead of in a report that silently reads zeros.
    """
    rows = [
        json.loads(line)
        for line in (ROOT / ".starquant" / "live" / "cycles.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    series = series_from_cycles(rows)

    assert len(series["bars"]) > MIN_BARS, "the loop has written enough bars to decompose"
    assert all(value > 0 for value in series["equity"]), "usdt_equity is present and positive"
    assert series["prices"], "`closes` is being written"
    assert any(row.get("contributions") for row in rows), "`contributions` is being written"
    state = signal_state(rows, "tsmom", series["bars"])
    assert state["measured"] and state["bars"] > 0
    assert set(state["values"]) <= {"+1.0", "-1.0"}, "tsmom's contributions are still sign-only"


# --- the fifth trap: a bandwidth as wide as the sample -------------------------------------------------


def _resid(n: int, *, seed: int = 20260922) -> tuple[list[float], object]:
    rng = random.Random(seed)
    x = [rng.gauss(0.0, 0.005) for _ in range(n)]
    resid = np.asarray([rng.gauss(0.0, 0.004) for _ in range(n)], dtype=float)
    return x, resid


def test_the_bandwidth_is_capped_at_a_quarter_of_the_sample() -> None:
    """Measured boundary, not a rule of thumb: at 48/n <= 0.25 four bandwidths agree to within 0.05."""
    x, resid = _resid(100)

    _se_a, _se_b, used = _nw_se(x, resid, NW_LAGS)

    assert used == int(100 * MAX_LAG_SHARE) == 25
    assert used < NW_LAGS, "a 100-bar window cannot carry a 48-bar kernel"


def test_a_long_enough_window_still_gets_the_bandwidth_the_constant_names() -> None:
    """The shipped reading must not move: the live window is 349 bars and 48/349 = 0.14."""
    x, resid = _resid(349)

    _se_a, _se_b, used = _nw_se(x, resid, NW_LAGS)

    assert used == NW_LAGS


def test_clamping_is_the_same_as_having_asked_for_the_smaller_bandwidth() -> None:
    """The Bartlett weights must use the width in force, or the kernel stops being a proper one.

    The bug this forbids is subtle and silent: taper by `1 - lag / (requested + 1)` while summing
    only to `used` truncates the kernel mid-taper, which is no longer a positive-semidefinite weight
    function - the variance it produces can come out smaller than the uncorrected one, which is
    exactly the direction that invents significance.
    """
    x, resid = _resid(100)

    clamped = _nw_se(x, resid, NW_LAGS)
    asked = _nw_se(x, resid, 25)

    assert clamped == asked


def test_a_clamped_window_refuses_to_annualise_even_when_the_t_clears_the_bar() -> None:
    """Two separate refusals.  |t| >= 2 is about the estimate; `covers` is about the ruler."""
    n = MIN_BARS + 7  # the 55-bar shape that read 5.49
    bars = _bars(n + 1)
    rng = random.Random(20260922)
    strategy_level = [1.0]
    benchmark_level = [1.0]
    for _ in range(n):
        strategy_level.append(strategy_level[-1] * math.exp(0.004 + rng.gauss(0.0, 0.005)))
        benchmark_level.append(benchmark_level[-1] * math.exp(rng.gauss(0.0, 0.005)))

    block = beta_decomposition(strategy_level, benchmark_level, [1.0] * n, bars=bars)["constant"]

    assert abs(block["alpha_t"]) > 2.0, "the t still clears its own bar"
    assert block["nw_covers_intended_horizon"] is False
    assert block["nw_lags"] < block["nw_lags_requested"] == NW_LAGS
    assert block["alpha_annualised"] is None, "a ruler that cannot see two days does not clear a two-day bar"


def test_the_readout_says_which_bandwidth_produced_the_t() -> None:
    """Printing `NW_LAGS`'s name while another width was in force is the defect one layer down."""
    n = MIN_BARS * 4
    bars = _bars(n + 1)
    rng = random.Random(20260922)
    levels = [1.0]
    market = [1.0]
    for _ in range(n):
        levels.append(levels[-1] * math.exp(0.0002 + rng.gauss(0.0, 0.005)))
        market.append(market[-1] * math.exp(rng.gauss(0.0, 0.005)))
    long_block = beta_decomposition(levels, market, [1.0] * n, bars=bars)["constant"]
    short_block = beta_decomposition(levels[:60], market[:60], [1.0] * 59, bars=bars[:60])["constant"]

    assert f"{NW_LAGS} bar" in _beta_regression_lines(long_block)["NW 带宽"]
    assert "被夹住" not in _beta_regression_lines(long_block)["NW 带宽"]
    assert "被夹住" in _beta_regression_lines(short_block)["NW 带宽"]


# --- the sixth: a cumulative count read as a standing one ---------------------------------------------


def _row(bar: int, values: dict[str, float]) -> dict:
    return {"bar_open_ms": bar, "contributions": {"tsmom": values}}


def test_the_short_count_is_cumulative_and_the_current_one_is_reported_beside_it() -> None:
    """2026-09-22: "空头持仓数 394" was read as a standing count, and the answer to "why frozen" is
    that a cumulative count stops growing - which is not the same event as a position being closed."""
    bars = _bars(3)
    rows = [
        _row(bars[0], {"A": -1.0, "B": -1.0, "C": 1.0}),
        _row(bars[1], {"A": -1.0, "B": 1.0, "C": 1.0}),
        _row(bars[2], {"A": 1.0, "B": 1.0, "C": 1.0}),
    ]

    state = signal_state(rows, "tsmom", bars)

    assert state["short_positions"] == 3, "2 + 1 + 0 pairs over the window"
    assert state["shorts_last_bar"] == 0, "and nothing is short now"


def test_a_frozen_cumulative_count_does_not_mean_a_short_is_still_held() -> None:
    """The exact shape of the live record: the count stops moving because the signals stopped, and a
    reader of the cumulative number alone cannot tell that from a position that never closed."""
    bars = _bars(4)
    rows = [_row(bars[0], {"A": -1.0})] + [_row(b, {"A": 1.0}) for b in bars[1:]]

    state = signal_state(rows, "tsmom", bars)

    assert state["short_positions"] == 1
    assert state["shorts_last_bar"] == 0
    assert state["all_long_bars"] == 3


def test_a_short_that_is_still_open_shows_up_in_the_current_count() -> None:
    """Both directions, or the new field is indistinguishable from one that is always zero."""
    bars = _bars(2)
    rows = [_row(bars[0], {"A": 1.0, "B": 1.0}), _row(bars[1], {"A": -1.0, "B": -1.0})]

    state = signal_state(rows, "tsmom", bars)

    assert state["shorts_last_bar"] == 2
    assert state["all_long_bars"] == 1


def test_the_report_says_which_count_is_which() -> None:
    """The rename is the fix; printing both under one ambiguous label would not be.

    The decomposition is a real `beta_decomposition` product rather than an invented dict, because
    `beta_markdown` short-circuits to a refusal page when it is not measured - and a test that fed it
    a hand-written payload would have asserted against a page the command never renders.
    """
    n = MIN_BARS * 4
    bars = _bars(n + 1)
    rng = random.Random(20260922)
    levels = [1.0]
    market = [1.0]
    for _ in range(n):
        levels.append(levels[-1] * math.exp(0.0002 + rng.gauss(0.0, 0.005)))
        market.append(market[-1] * math.exp(rng.gauss(0.0, 0.005)))
    rows = [_row(bars[0], {"A": -1.0})] + [_row(b, {"A": 1.0}) for b in bars[1:]]

    text = beta_markdown(
        {
            "window": {},
            "benchmark": {},
            "signal": signal_state(rows, "tsmom", bars),
            "decomposition": beta_decomposition(levels, market, [1.0] * n, bars=bars),
        }
    )

    assert "窗口累计" in text
    assert "当前空头标的数" in text
    assert "空头持仓数" not in text, "the ambiguous label is gone, not merely joined"
