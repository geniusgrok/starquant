"""G4: the backtest's one-day VaR / ES reach the daily report in USDT, and live days are counted against them.

`starquant_live.reports.tail_readings` converts four constants measured by
`scratchpad/g4_stress_windows_and_var_at_k060.py` and counts live UTC days past the VaR.  These tests pin the
conversion (which equity, which constant), the live day (which steps, which days) and the one refusal (the
constants belong to one vol_target).  One of them drives the equity with the August 2026 Binance closes,
because the day bucketing is where a real record differs from a hand-made one: real bars straddle UTC
midnight at the venue's hour, and a count that is right on round numbers can still be off by a day there.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel
from starquant_live.reports import (
    BACKTEST_DAILY_ES,
    BACKTEST_DAILY_VAR,
    TAIL_VOL_TARGET,
    daily_markdown,
    daily_payload,
    tail_readings,
)
from starquant_live.state import StateStore

HOUR = 3_600_000
DAY = 24 * HOUR
MIDNIGHT = 1_788_048_000_000  # 2026-08-30T00:00Z


def _store(tmp_path: Path, cycles: list[dict]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for row in cycles:
        store.append_cycle(row)
    return store


def _path(equities: list[float], *, start: int = MIDNIGHT, construction: str = "aaa", **extra: object) -> list[dict]:
    return [
        {"bar_open_ms": start + i * HOUR, "bar": f"bar-{i}", "equity": value, "construction": construction, **extra}
        for i, value in enumerate(equities)
    ]


def _day(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")


def test_the_constants_are_ordered_the_way_a_tail_is() -> None:
    """ES is the mean beyond the VaR and 99% sits beyond 95%: a transposed constant breaks one of these."""
    for level in (0.95, 0.99):
        assert 0.0 < BACKTEST_DAILY_VAR[level] <= BACKTEST_DAILY_ES[level] < 1.0
    assert BACKTEST_DAILY_VAR[0.95] < BACKTEST_DAILY_VAR[0.99]
    assert BACKTEST_DAILY_ES[0.95] < BACKTEST_DAILY_ES[0.99]


def test_var_and_es_are_converted_at_the_days_last_equity(tmp_path: Path) -> None:
    """The equity `design_daily_sigma_u` scales, not the day's first: the weights are fractions of the last."""
    cycles = _path([10_000.0 + 50.0 * i for i in range(30)])
    day = _day(MIDNIGHT + DAY)
    result = tail_readings(_store(tmp_path, cycles), day, vol_target=TAIL_VOL_TARGET)
    last = 10_000.0 + 50.0 * 29
    assert result["enforced"] is True and result["equity_u"] == last
    for level, tag in ((0.95, "95"), (0.99, "99")):
        assert math.isclose(result[f"var_{tag}_u"], BACKTEST_DAILY_VAR[level] * last, rel_tol=1e-12)
        assert math.isclose(result[f"es_{tag}_u"], BACKTEST_DAILY_ES[level] * last, rel_tol=1e-12)


def test_live_days_past_the_var_on_real_august_prices(tmp_path: Path, august_panel: Panel) -> None:
    """Equity driven by the real August 2026 basket; the count must equal an independent pandas count."""
    close = august_panel.close
    basket = close.pct_change().mean(axis=1).fillna(0.0)
    equity = 10_000.0 * (1.0 + 3.0 * basket).cumprod()
    stamps = [int(stamp.value // 1_000_000) for stamp in equity.index]
    cycles = [
        {"bar_open_ms": ms, "as_of_ms": ms, "bar": str(i), "equity": float(value), "construction": "aaa"}
        for i, (ms, value) in enumerate(zip(stamps, equity.to_numpy(), strict=True))
    ]
    report_day = _day(stamps[-1])
    result = tail_readings(_store(tmp_path, cycles), report_day, vol_target=TAIL_VOL_TARGET)

    by_day = equity.groupby(equity.index.strftime("%Y-%m-%d")).last()
    daily = (by_day / by_day.shift(1) - 1.0).dropna()
    counted = daily[(daily.index > _day(stamps[0])) & (daily.index < report_day)]
    assert result["days"] == len(counted) and result["first_day"] == counted.index[0]
    for level, tag in ((0.95, "95"), (0.99, "99")):
        expected = sorted(counted.index[counted < -BACKTEST_DAILY_VAR[level]])
        assert result[f"past_var_{tag}"] == expected
        assert math.isclose(result[f"expected_past_var_{tag}"], len(counted) * (1.0 - level), rel_tol=1e-12)
    # The fixture has to discriminate: at 3x the basket some real days go past VaR 95 and most do not, and
    # fewer go past VaR 99 than past VaR 95 without that count being zero.
    assert 0 < len(result["past_var_99"]) < len(result["past_var_95"]) < len(counted)
    assert math.isclose(result["equity_u"], float(equity.iloc[-1]), rel_tol=1e-12)


def test_a_day_is_compounded_like_the_backtests_not_summed(tmp_path: Path) -> None:
    """+50% then -40% inside one day is a 10% loss, as `complete_days` in the scratchpad compounds it.

    Summed hour by hour the same day reads +10%, and on this book's scale the two part ways exactly on the
    days that matter: the ones that moved a lot.
    """
    path = [10_000.0] * 72
    for i in range(30, 72):
        path[i] = 15_000.0 if i < 40 else 9_000.0  # day 1: 06:00Z up half, 16:00Z down forty percent
    result = tail_readings(_store(tmp_path, _path(path)), _day(MIDNIGHT + 2 * DAY), vol_target=TAIL_VOL_TARGET)
    assert result["days"] == 1 and result["past_var_95"] == [_day(MIDNIGHT + DAY)] == result["past_var_99"]


def test_a_transfer_is_not_a_loss_day(tmp_path: Path) -> None:
    """A demo reset arrives as a TRANSFER and re-baselines the cycle; `noise_scale` skips that step, so does this."""
    flat = [10_000.0] * 72
    flat[40] = 5_000.0  # a withdrawal on day 2, recorded as a re-baselined cycle
    for i in range(41, 72):
        flat[i] = 5_000.0
    cycles = _path(flat)
    cycles[40]["external_flows"] = {"rebaselined": True, "total": -5_000.0, "rows": 1}
    result = tail_readings(_store(tmp_path, cycles), _day(MIDNIGHT + 3 * DAY), vol_target=TAIL_VOL_TARGET)
    assert result["days"] == 2 and result["past_var_95"] == [] and result["past_var_99"] == []


def _halved_at(bars: int, crashes: set[int], level: float = 10_000.0) -> list[float]:
    """An equity path that halves at each listed bar and stays there: past both VaRs on the day it lands."""
    path = []
    for i in range(bars):
        level *= 0.5 if i in crashes else 1.0
        path.append(level)
    return path


def test_only_complete_days_of_the_running_construction_before_the_report_day_count(tmp_path: Path) -> None:
    """A day the construction opened in, days under the old one, and the report's own day are all left out."""
    old = _path(_halved_at(30, {20}), construction="old")  # day 0 at 20:00Z, the old construction
    # 90 bars from day 1 06:00Z: bar 5 is day 1 (the day the window opened), bar 50 is day 3 08:00Z (counted),
    # bar 85 is day 4 19:00Z (the report's own day, still open).
    new = _path(_halved_at(90, {5, 50, 85}, level=5_000.0), start=MIDNIGHT + 30 * HOUR, construction="new")
    store = _store(tmp_path, old + new)
    result = tail_readings(store, _day(MIDNIGHT + 4 * DAY), vol_target=TAIL_VOL_TARGET)
    assert result["first_day"] == _day(MIDNIGHT + 2 * DAY) and result["days"] == 2
    assert result["past_var_95"] == [_day(MIDNIGHT + 3 * DAY)] == result["past_var_99"]


def test_constants_are_not_converted_under_another_vol_target(tmp_path: Path) -> None:
    """Measured at 0.60: at 0.30 the same fractions would describe a book twice the size of the one running."""
    store = _store(tmp_path, _path([10_000.0] * 30))
    for vol_target in (0.30, None):
        result = tail_readings(store, _day(MIDNIGHT + DAY), vol_target=vol_target)
        assert result["enforced"] is False and "var_95_u" not in result and "past_var_95" not in result


def test_the_daily_report_prints_it_right_under_the_sigma_ruler(tmp_path: Path) -> None:
    cycles = _path(list(10_000.0 * np.cumprod(np.full(80, 1.001))))
    day = _day(MIDNIGHT + 3 * DAY)
    payload = daily_payload(_store(tmp_path, cycles), day, vol_target=TAIL_VOL_TARGET)
    assert payload["tail"]["enforced"] is True and payload["tail"]["days"] == 2
    markdown = daily_markdown(payload)
    sigma, tail = markdown.index("Noise scale (DL-EX0)"), markdown.index("Tail beside the sigma ruler (G4)")
    assert sigma < tail < markdown.index("Exit counterfactuals")
    assert "live days below -VaR 95%" in markdown and "0 of 2 (expected 0.10)" in markdown
