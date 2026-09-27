"""L1-10: how much of "equity" is BTC rather than the book (report-only, deliberately).

The demo account is on multi-assets margin, so `totalMarginBalance` - the number the drawdown ladder and
the vol sizing divide by - includes non-USDT collateral valued at mark.  BTC moves and the book's measured
equity moves with it, even on a bar where the book did nothing.  A -35% reading on that series can be the
ladder reacting to BTC, not to the strategy.

**This does not change the sizing, on purpose.**  Changing what the guardrails divide by would change
every position size, which is a construction change: it would reset M-010's evidence window and needs to
be decided on its own merits by the operator, not smuggled in as a bug fix.  What was actually missing is
that nobody could SEE the divergence.  So this measures it and the daily report prints it, and the number
the book trades on is untouched.

`/fapi/v2/account` already carries the per-asset breakdown in `assets`; it was being thrown away.
"""

from __future__ import annotations

from starquant_live.reports import collateral_share


def test_a_usdt_only_account_reports_no_collateral_drift() -> None:
    assert collateral_share(equity=10_000.0, usdt_equity=10_000.0)["share"] == 0.0


def test_the_share_is_the_part_of_equity_that_is_not_usdt() -> None:
    out = collateral_share(equity=10_000.0, usdt_equity=7_500.0)
    assert abs(out["share"] - 0.25) < 1e-12
    assert abs(out["collateral"] - 2_500.0) < 1e-9


def test_an_unreported_usdt_balance_is_none_not_zero() -> None:
    """Zero would read as "all of it is BTC", which is the opposite of "we do not know"."""
    out = collateral_share(equity=10_000.0, usdt_equity=None)
    assert out["share"] is None
    assert out["collateral"] is None


def test_a_flat_or_absent_equity_does_not_divide_by_zero() -> None:
    assert collateral_share(equity=0.0, usdt_equity=0.0)["share"] is None


# --- the wiring: the number has to reach the row, or the function above measures nothing -------------


def test_the_venue_reads_the_usdt_balance_out_of_the_assets_array() -> None:
    """`/fapi/v2/account` already carries `assets`; it was parsed away."""
    import asyncio

    from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
    from tests.live.helpers_liquidation import _RecordingClient  # a get() that returns a canned payload

    payload = {
        "totalMarginBalance": "10000.0",
        "totalWalletBalance": "9800.0",
        "availableBalance": "9000.0",
        "totalInitialMargin": "500.0",
        "positions": [],
        "assets": [
            {"asset": "USDT", "marginBalance": "7500.0"},
            {"asset": "BTC", "marginBalance": "2500.0"},
        ],
    }
    venue = BinanceUsdmVenue(_RecordingClient({"/fapi/v2/account": payload}))  # type: ignore[arg-type]
    account = asyncio.run(venue.account())
    assert account.usdt_equity == 7500.0


def test_an_account_payload_without_assets_reports_none_not_zero() -> None:
    import asyncio

    from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
    from tests.live.helpers_liquidation import _RecordingClient

    payload = {
        "totalMarginBalance": "10000.0",
        "totalWalletBalance": "9800.0",
        "availableBalance": "9000.0",
        "totalInitialMargin": "500.0",
        "positions": [],
    }
    venue = BinanceUsdmVenue(_RecordingClient({"/fapi/v2/account": payload}))  # type: ignore[arg-type]
    assert asyncio.run(venue.account()).usdt_equity is None


def test_the_cycle_row_carries_the_split(august_panel, tmp_path) -> None:
    """The DL-X1 check: a correct function nobody calls measures nothing."""
    import asyncio

    from tests.live.test_slippage_measures_what_mq08_names import _trade_rows_from_one_real_cycle

    asyncio.run(_trade_rows_from_one_real_cycle(august_panel, tmp_path))
    import json

    rows = [json.loads(line) for line in (tmp_path / "live" / "cycles.jsonl").read_text().splitlines()]
    assert rows, "no cycle row was written"
    assert "collateral" in rows[-1], "the engine did not record the collateral split"
    assert set(rows[-1]["collateral"]) == {"equity", "usdt_equity", "collateral", "share"}
