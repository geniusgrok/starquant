"""L1-04: the instrument that judges M-Q08 was pointed at the wrong price and gated too loose.

M-Q08 is one of the two criteria the demo phase is now judged by (report section 9: "demo 的成功判据
不再是 M-010，而是 M-Q08（执行保真）与 M-Q09（无人值守存活）").  Its slippage clause reads
"滑点 ≤ 2× 模型" - the model charges 2 bps, so the bar is 4 bps.  Two things made the instrument
unable to say whether that bar was met:

1. **The reference price was the venue's mark at snapshot time** (`reconciler.take_snapshot` calls
   `venue.mark_prices`, and `plan_orders` carries that number onto the trade row).  The backtest enters
   at the execution bar's OPEN, which in a continuous market is the decision bar's CLOSE - a different
   number, drifting independently, because a mark is an index price and a close is a trade price.
   Measuring against the mark answers "how far from the index did we fill", which is not the question
   M-Q08 asks.
2. **The limit was 10 bps.**  Its own config comment says "against the cost model's 7 bps" - but 7 is
   `turnover_bps`, which bundles the 5 bps taker fee with the 2 bps slippage, while this instrument
   measures price slippage alone (`avg_price` excludes commission).  So a fee-inclusive budget was
   being used to judge a fee-exclusive measurement, at 2.5x the bar M-Q08 actually states.

Together they made the gate structurally unable to fail: the report measured +4.3 bps - outside
M-Q08's 4, comfortably inside the instrument's 10 - and the instrument reported green.

Same family as M-003's missing suite-duration instrument, and worse in one way: that budget had no
instrument at all, this one had an instrument that reported OK while pointed elsewhere.

Rows written before `decision_close` existed are SKIPPED, not silently measured against the mark.
An honest "I cannot measure these 30 fills" is worth more than a precise number for the wrong quantity,
and the house rule is that history is not backfilled.
"""

from __future__ import annotations

from starquant_live.risk_budget import RiskBudgetParams, slippage_bps

HOUR = 3_600_000
NOW = 1_757_000_000_000


def _fill(*, decision_close: float | None, avg_price: float, side: str = "BUY", qty: float = 1.0) -> dict:
    row: dict = {
        "bar_open_ms": NOW - HOUR,
        "avg_price": avg_price,
        "executed_qty": qty,
        "side": side,
        "price": 999.0,
    }  # `price` is the old mark-based reference; it must no longer be used
    if decision_close is not None:
        row["decision_close"] = decision_close
    return row


def _params(**kw: object) -> RiskBudgetParams:
    return RiskBudgetParams(min_slippage_fills=1, **kw)  # type: ignore[arg-type]


def test_slippage_is_measured_against_the_decision_close_not_the_mark() -> None:
    """A buy filled 10 bps above the decision close reads 10 bps, whatever the mark said."""
    result = slippage_bps([_fill(decision_close=100.0, avg_price=100.1)], _params(), latest_ms=NOW)
    assert result["enforced"] is True
    assert abs(result["value"] - 10.0) < 1e-9


def test_a_sell_filled_below_the_decision_close_is_adverse_too() -> None:
    result = slippage_bps([_fill(decision_close=100.0, avg_price=99.9, side="SELL")], _params(), latest_ms=NOW)
    assert abs(result["value"] - 10.0) < 1e-9


def test_rows_without_a_decision_close_are_skipped_and_counted_not_measured_against_the_mark() -> None:
    """The old rows carry `price` (the mark).  Falling back to it is how the wrong number returns."""
    result = slippage_bps([_fill(decision_close=None, avg_price=100.1)] * 40, _params(), latest_ms=NOW)
    assert result["enforced"] is False
    assert result["without_reference"] == 40
    assert result["value"] is None


def test_the_limit_is_twice_the_cost_models_slippage_not_a_standalone_constant() -> None:
    """M-Q08 says "<= 2x model", so the bar must move when the model does, not sit at 10."""
    assert _params().max_slippage_bps == 4.0
    assert _params(model_slippage_bps=3.0).max_slippage_bps == 6.0
    assert _params(slippage_multiple=3.0).max_slippage_bps == 6.0


def test_the_reported_plus_four_point_three_bps_now_fails_the_gate_it_used_to_pass() -> None:
    """The regression this whole file exists for: 4.3 bps was green at 10, and is red at M-Q08's 4."""
    result = slippage_bps([_fill(decision_close=100.0, avg_price=100.043)], _params(), latest_ms=NOW)
    assert abs(result["value"] - 4.3) < 1e-6
    assert result["inside"] is False


# --- the wiring, without which the above is a correct instrument nobody feeds (the DL-X1 shape) ------


async def _trade_rows_from_one_real_cycle(panel, tmp_path):
    """One real cycle against a venue whose mark deliberately disagrees with the bar close."""
    from pathlib import Path

    from starquant_alpha.model import AlphaModel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals.tsmom import TsmomParams
    from starquant_live.engine import LiveConfig, LiveEngine
    from starquant_live.guards import GuardParams
    from starquant_live.rebalancer import RebalanceParams
    from starquant_live.state import StateStore
    from tests.fakes.fake_venue import FakeVenue
    from tests.live.fakes import FakeClock, FakeMarketData

    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    cursor = 400
    market = FakeMarketData(panel, cursor)
    venue = FakeVenue()
    # The mark is 5% away from the close on purpose: if the row records the mark, the assertion below
    # fails by 500 bps, which is the whole point of the test.
    for symbol in symbols:
        venue.prices[symbol] = float(panel.close[symbol].iloc[cursor - 1]) * 1.05
    params = dict(TsmomParams(vol_window=100).__dict__) | {
        "horizons": [5, 20, 50],
        "horizon_weights": [0.2, 0.3, 0.5],
        "entry_threshold": 0.05,
    }
    model = AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, max_weight=0.15, max_gross=0.6),
        interval="1h",
        min_history_bars=0,
    )
    engine = LiveEngine(
        LiveConfig(
            interval="1h",
            history_bars=300,
            universe=tuple(symbols),
            leverage=2,
            rebalance=RebalanceParams(no_trade_band=0.002),
            guards=GuardParams(),
            kill_switch_path=Path(tmp_path) / "KILL_SWITCH",
            strategy_weights={"tsmom": 1.0},
            poll_interval_seconds=0.0,
            grace_seconds=1.0,
        ),
        model=model,
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=StateStore(Path(tmp_path) / "live"),
    )
    await engine.startup()
    await engine.run_cycle(market.bar_open_ms(cursor))
    store = engine.store
    return [row for row in store.read_jsonl(store.trades_path) if row.get("executed_qty")], panel, cursor


def test_the_engine_records_the_decision_close_on_every_trade_row(august_panel, tmp_path) -> None:
    """Without this the instrument above measures nothing: every row lands in `without_reference`."""
    import asyncio

    rows, panel, cursor = asyncio.run(_trade_rows_from_one_real_cycle(august_panel, tmp_path))
    assert rows, "the cycle placed no orders, so this test would pass vacuously"
    for row in rows:
        expected = float(panel.close[row["symbol"]].iloc[cursor - 1])
        assert row.get("decision_close") is not None, f"{row['symbol']} carries no decision_close"
        assert abs(float(row["decision_close"]) - expected) < 1e-9
        # and it is NOT the mark the old instrument used
        assert abs(float(row["decision_close"]) - float(row["price"])) > 1e-6


def test_the_retired_config_key_is_refused_rather_than_silently_ignored() -> None:
    """`max_slippage_bps` is a derived property now, so `from_mapping` would drop it without a word.

    An operator who sets a number and gets no effect and no error is the failure this repository keeps
    finding.  Refusing names the replacement.
    """
    import pytest

    with pytest.raises(ValueError, match="max_slippage_bps"):
        RiskBudgetParams.from_mapping({"max_slippage_bps": 10.0})
