"""M-Q08's turnover clause: "within ±25% of the backtest over the same period" had no instrument.

A ratio of two turnovers means something only if both sides measure the same quantity, so the first two
tests here hold the two readers to one unit on REAL prices (the August 2026 panel):

* the backtest side is `run_backtest`'s own `turnover`, split by symbol and moved back one bar to the bar
  that DECIDED each trade - bit for bit, not a second definition of it;
* the live side is each fill's notional over the equity its own cycle recorded.  A live record that trades
  exactly the backtest's weights, sized off a moving equity, must read a ratio of one to rounding.

The rest pin the rules around the ratio: which bars form "the same period", what a cell the archive
cannot price does, and when the ratio is judged at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel
from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_alpha.validation.pipeline import score_book
from starquant_live import execution_fidelity as fidelity
from starquant_live.reports import daily_alerts

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_788_220_800_000  # 2026-09-01T00:00Z, a Tuesday; only its UTC-midnight alignment matters


def _inputs(*, registry: str = "r") -> fidelity.ReplayInputs:
    """Every kind of layer the shipped book has - relative band, vol target, guards, exit overlay.

    Shorter horizons and k = 3 rather than the shipped 6, so that a one-month fixture trades and takes
    exits; the unit under test does not depend on either.
    """
    entry = StrategyEntry(
        "tsmom",
        params={
            **TsmomParams(vol_window=100).__dict__,
            "horizons": [5, 20, 50],
            "horizon_weights": [0.2, 0.3, 0.5],
            "entry_threshold": 0.05,
        },
    )
    portfolio = PortfolioParams(
        vol_target=0.6, covariance_halflife=48, vol_halflife=24, no_trade_band=0.005, no_trade_rel_band=0.4
    )
    model = AlphaModel(entries=(entry,), portfolio=portfolio, interval="1h", min_history_bars=0)
    exits = ExitParams(take_profit=3.0, stop_loss=3.0)
    return fidelity.ReplayInputs(model, CostModel(), BookGuardParams(), exits, "", registry)


def _everyone(panel: Panel) -> pd.DataFrame:
    return pd.DataFrame(True, index=panel.index, columns=panel.close.columns)


def _ms(stamp: pd.Timestamp) -> int:
    return int(pd.Timestamp(stamp).timestamp() * 1000)


def test_the_replay_is_the_backtests_own_turnover_keyed_by_the_deciding_bar(august_panel: Panel) -> None:
    inputs = _inputs()
    assert inputs.model is not None
    per_symbol, exits = fidelity.replay_turnover(august_panel, _everyone(august_panel), inputs)
    decided, _, _ = inputs.model.evaluate(august_panel, _everyone(august_panel))
    result, _ = score_book(august_panel, decided, inputs.cost, guards=inputs.guards, exits=inputs.exits)

    # The backtest's own number, not a re-derivation of it: equal to the bit.
    assert np.array_equal(per_symbol.sum(axis=1).to_numpy(), result.turnover.to_numpy())
    # Charged at bar t+1 by the backtest, keyed to t here - the bar a live fill carries.
    bars = august_panel.close.index
    assert list(per_symbol.index) == [bars[bars.get_loc(stamp) - 1] for stamp in result.turnover.index]
    # A month of real prices trades, and the overlay fires, so neither assertion above is vacuous.
    assert result.turnover.sum() > 1.0
    assert exits, "no exit fired on the August panel: the exit half of the replay is untested"


def test_a_live_record_that_trades_the_backtests_weights_reads_one(august_panel: Panel) -> None:
    """The live reader, fed fills built from the backtest's EXECUTED weights, gives back the same series.

    The fills are built here from `score_book`'s weights - not from `replay_turnover`'s output - with the
    deciding bar derived independently, so a replay keyed by the wrong bar cannot agree with them.  The
    equity moves (it is the backtest's own curve) so a fill sized off the wrong cycle cannot either.
    """
    inputs = _inputs()
    assert inputs.model is not None
    per_symbol, _ = fidelity.replay_turnover(august_panel, _everyone(august_panel), inputs)
    decided, _, _ = inputs.model.evaluate(august_panel, _everyone(august_panel))
    result, _ = score_book(august_panel, decided, inputs.cost, guards=inputs.guards, exits=inputs.exits)
    bars = august_panel.close.index
    equity = 10_000.0 * result.equity_curve
    rows: list[dict[str, Any]] = []
    flatten_at = result.weights.index[len(result.weights) // 2].isoformat()
    trades: list[dict[str, Any]] = [
        {"flatten": True, "bar_open_ms": None, "at": flatten_at, "executed_qty": "1", "avg_price": 5.0}
    ]
    previous = pd.Series(0.0, index=result.weights.columns)
    for executed in result.weights.index:
        decision = bars[bars.get_loc(executed) - 1]
        sized_from = float(equity.get(decision, 10_000.0))
        rows.append({"bar_open_ms": _ms(decision), "equity": sized_from})
        for symbol, change in (result.weights.loc[executed] - previous).abs().items():
            if change > 0:
                price = float(august_panel.close.at[decision, symbol])
                trades.append(
                    {
                        "bar_open_ms": _ms(decision),
                        "symbol": symbol,
                        "avg_price": price,
                        "executed_qty": str(change * sized_from / price),
                    }
                )
        previous = result.weights.loc[executed]

    since, until = rows[0]["bar_open_ms"], rows[-1]["bar_open_ms"]
    live = fidelity.live_turnover(rows, trades, since_ms=since, until_ms=until)
    backtest = {_ms(stamp): float(value) for stamp, value in per_symbol.sum(axis=1).items()}

    assert live["flatten_fills"] == 1 and live["unsized_fills"] == 0
    for bar in set(backtest) | set(live["by_bar"]):
        expected = backtest.get(bar, 0.0)
        assert abs(live["by_bar"].get(bar, 0.0) - expected) <= 1e-12 * max(1.0, expected), bar
    days = fidelity.by_day(live["by_bar"], backtest)
    ratio, se = fidelity.paired_ratio([(row["live"], row["backtest"]) for row in days])
    assert ratio is not None and se is not None
    assert abs(ratio - 1.0) < 1e-12 and se < 1e-12
    assert len(days) >= 28, "a month of bars should span the month's days"


def test_a_fill_is_sized_by_the_cycle_that_decided_it() -> None:
    rows = [
        {"bar_open_ms": T0, "equity": 1_000.0},
        {"bar_open_ms": T0 + HOUR, "equity": 2_000.0},
        # T0 + 2h: the cycle failed after placing an order and recorded no equity
        {"bar_open_ms": T0 + 3 * HOUR, "equity": 4_000.0},
    ]
    trades = [
        {"bar_open_ms": T0 - HOUR, "symbol": "AAAUSDT", "executed_qty": "1", "avg_price": 9_999.0},  # before
        {"bar_open_ms": T0 + HOUR, "symbol": "AAAUSDT", "executed_qty": "2", "avg_price": 100.0},
        {"bar_open_ms": T0 + 2 * HOUR, "symbol": "AAAUSDT", "executed_qty": "1", "avg_price": 100.0},
        {"bar_open_ms": T0 + 3 * HOUR, "symbol": "BBBUSDT", "executed_qty": "4", "avg_price": 100.0},
        # An operator flatten is never the construction's turnover, even one that names a bar; counted by
        # wall clock, and only inside the window.
        {
            "flatten": True,
            "bar_open_ms": T0 + HOUR,
            "at": "2026-09-01T01:30:00+00:00",
            "executed_qty": "5",
            "avg_price": 1.0,
        },
        {
            "flatten": True,
            "bar_open_ms": None,
            "at": "2026-08-30T01:30:00+00:00",
            "executed_qty": "5",
            "avg_price": 1.0,
        },
    ]
    live = fidelity.live_turnover(rows, trades, since_ms=T0, until_ms=T0 + 3 * HOUR)
    # 200 / 2,000; the failed cycle's 100 / the 2,000 it was sized from; 400 / 4,000
    assert live["by_bar"] == {T0 + HOUR: 0.1, T0 + 2 * HOUR: 0.05, T0 + 3 * HOUR: 0.1}
    assert live["flatten_fills"] == 1 and live["unsized_fills"] == 0

    orphan = fidelity.live_turnover(rows[2:], trades[1:2], since_ms=T0, until_ms=T0 + 3 * HOUR)
    assert orphan["by_bar"] == {} and orphan["unsized_fills"] == 1, "no cycle sized it: counted, not guessed"


def _cycles(days: int, *, construction: str = "c", registry: str = "r") -> list[dict[str, Any]]:
    return [
        {"bar_open_ms": T0 + i * HOUR, "equity": 1_000.0, "construction": construction, "registry": registry}
        for i in range(days * 24)
    ]


def _replay(bars: list[int], per_bar: Mapping[str, float], priced_until: Mapping[str, int]) -> fidelity.Replay:
    index = pd.DatetimeIndex([pd.Timestamp(bar, unit="ms", tz="UTC") for bar in bars])
    frame = pd.DataFrame({symbol: [value] * len(bars) for symbol, value in per_bar.items()}, index=index)
    return fidelity.Replay(frame, dict(priced_until), set(), bars[0])


def _fills(rows: list[dict[str, Any]], per_bar: Mapping[str, float]) -> list[dict[str, Any]]:
    return [
        {"bar_open_ms": row["bar_open_ms"], "symbol": symbol, "executed_qty": str(share), "avg_price": 1_000.0}
        for row in rows
        for symbol, share in per_bar.items()
    ]


def test_a_symbol_bar_the_archive_cannot_price_leaves_both_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _cycles(2)
    bars = [row["bar_open_ms"] for row in rows]
    stale = bars[10]
    replay = _replay(bars, {"AAAUSDT": 0.01, "BBBUSDT": 0.02}, {"AAAUSDT": bars[-1], "BBBUSDT": stale})
    monkeypatch.setattr(fidelity, "backtest_turnover", lambda *_a, **_k: replay)

    block = fidelity.turnover_fidelity(rows, _fills(rows, {"AAAUSDT": 0.01, "BBBUSDT": 0.02}), _inputs())
    assert block["backtest"] == pytest.approx(48 * 0.01 + 11 * 0.02, abs=1e-12)
    assert block["live"] == pytest.approx(block["backtest"], abs=1e-12)
    assert block["ratio"] == pytest.approx(1.0, abs=1e-12)
    assert block["unpriced"]["BBBUSDT"]["live_turnover_excluded"] == pytest.approx(37 * 0.02, abs=1e-12)
    assert block["unpriced"]["BBBUSDT"]["archive_ends"] == pd.Timestamp(stale, unit="ms", tz="UTC").isoformat()


def test_the_ratio_is_judged_only_from_fourteen_complete_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twice the backtest's turnover is outside the band either way; only the sample decides if it is SAID."""
    for days, judged in ((13, False), (14, True)):
        rows = _cycles(days)
        bars = [row["bar_open_ms"] for row in rows]
        replay = _replay(bars, {"AAAUSDT": 0.01}, {"AAAUSDT": bars[-1]})
        monkeypatch.setattr(fidelity, "backtest_turnover", lambda *_a, _replay=replay, **_k: _replay)
        block = fidelity.turnover_fidelity(rows, _fills(rows, {"AAAUSDT": 0.02}), _inputs())
        assert block["ratio"] == pytest.approx(2.0) and block["inside"] is False
        assert block["complete_days"] == days and block["enforced"] is judged
        alerts, notices = daily_alerts({"execution_fidelity": {"turnover": block}})
        assert alerts == [], "M-Q08's failure action is a review: it never pages"
        assert [notice.split("：")[0] for notice in notices] == (["M-Q08 换手偏离"] if judged else [])
        if not judged:
            assert "13 个完整日" in block["why"]


def _later(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    return [{**row, "bar_open_ms": row["bar_open_ms"] + days * DAY} for row in rows]


def test_the_window_is_one_construction_and_one_registry() -> None:
    failed = {"bar_open_ms": T0 + 2 * DAY, "equity": None, "registry": None}  # breaks nothing
    for older in (_cycles(1, registry="old"), _cycles(1, construction="old")):
        window = fidelity.comparison_window([*older, *_later(_cycles(1), 1), failed])
        assert window is not None and window["since_ms"] == T0 + DAY and window["registry"] == "r"

    long_run = _cycles(40)
    capped = fidelity.comparison_window(long_run)
    assert capped is not None and capped["since_ms"] == long_run[-1]["bar_open_ms"] - 30 * DAY


def test_a_replay_of_a_registry_the_loop_is_not_running_is_not_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> fidelity.Replay:
        raise AssertionError("the replay must not run against a registry the loop does not hold")

    monkeypatch.setattr(fidelity, "backtest_turnover", refuse)
    block = fidelity.turnover_fidelity(_cycles(20, registry="loop"), [], _inputs(registry="disk"))
    assert block["enforced"] is False and "disk" in block["why"] and "loop" in block["why"]


def test_the_error_bar_is_cochrans_ratio_estimator() -> None:
    ratio, se = fidelity.paired_ratio([(2.0, 1.0), (1.0, 1.0), (3.0, 2.0)])
    # residuals 0.5, -0.5, 0.0: sqrt(0.5 / (3 * 2)) over the mean backtest day 4/3
    assert ratio == pytest.approx(1.5, abs=1e-15)
    assert se == pytest.approx((0.5 / 6) ** 0.5 / (4 / 3), abs=1e-15)
    assert fidelity.paired_ratio([(1.0, 0.0)]) == (None, None)
    assert fidelity.paired_ratio([(1.0, 2.0)]) == (0.5, None)


def test_the_replay_trades_the_loops_universe_and_the_table_before_it() -> None:
    index = pd.date_range(pd.Timestamp(T0, unit="ms", tz="UTC"), periods=6, freq="h")
    table = pd.DataFrame({"AAAUSDT": [False], "BBBUSDT": [True]}, index=[index[0].floor("D")])
    recorded = [(T0 + 2 * HOUR, frozenset({"AAAUSDT"})), (T0 + 4 * HOUR, frozenset({"AAAUSDT", "BBBUSDT"}))]
    membership = fidelity.replay_membership(index, ["AAAUSDT", "BBBUSDT"], recorded, table)
    assert membership["AAAUSDT"].tolist() == [False, False, True, True, True, True]
    assert membership["BBBUSDT"].tolist() == [True, True, False, False, True, True]
    without_table = fidelity.replay_membership(index, ["AAAUSDT", "BBBUSDT"], recorded, None)
    assert without_table["BBBUSDT"].tolist() == [False, False, False, False, True, True]
