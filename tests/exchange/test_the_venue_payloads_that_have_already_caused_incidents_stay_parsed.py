"""Regression cases for `parse_position`, `account()` and `margin_mode()` - all of them from incidents.

`venue.py:43-75` is thirty lines of parsing that has been wrong in production twice: the
`unRealizedProfit` / `unrealizedProfit` spelling (the two payloads disagree), and the notional that
read zero for every account-derived position because the mark price it was derived from was absent.
`account()` has a third: `totalInitialMargin` coming back as 92233720368.54775807, an int64 overflow
sentinel scaled by 1e8, which made the venue derive `availableBalance` 0 and would have made the
margin scaler refuse every risk-adding order on a 95%-free account.

Each test below is one of those, plus the two that were fixed by reading the payload correctly the
first time (`liquidationPrice` 0, `isolated` vs `marginType`) and so have never had a test either.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue, parse_position

DEMO = "https://demo-fapi.binance.com"

# A /fapi/v2/positionRisk row as demo-fapi actually returns it (shape recorded 2026-09-06).
RISK_ROW: dict[str, Any] = {
    "symbol": "ZECUSDT",
    "positionAmt": "0.169",
    "entryPrice": "872.08",
    "markPrice": "954.81",
    "unRealizedProfit": "13.98137000",
    "liquidationPrice": "0",
    "leverage": "0",
    "isolated": False,
    "marginType": "cross",
}
# A /fapi/v2/account `positions` row: different spelling, no mark, no liquidation price at all.
ACCOUNT_ROW: dict[str, Any] = {
    "symbol": "ZECUSDT",
    "positionAmt": "0.169",
    "entryPrice": "872.08",
    "notional": "161.36289000",
    "unrealizedProfit": "13.98137000",
    "leverage": "0",
}


def _venue(routes: dict[str, Any]) -> BinanceUsdmVenue:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path in routes, f"unrouted call to {request.url.path}"
        return httpx.Response(200, json=routes[request.url.path])

    return BinanceUsdmVenue(BinanceRestClient(DEMO, "k", "s", transport=httpx.MockTransport(handler)))


def test_both_spellings_of_unrealized_pnl_are_read_because_the_two_payloads_disagree() -> None:
    """The capital R is positionRisk's; the account row uses a small one.  Reading only one gave 0."""
    assert parse_position(RISK_ROW) is not None
    assert parse_position(RISK_ROW).unrealized_pnl == pytest.approx(13.98137)  # type: ignore[union-attr]
    assert parse_position(ACCOUNT_ROW).unrealized_pnl == pytest.approx(13.98137)  # type: ignore[union-attr]


def test_an_account_row_uses_the_venues_own_notional_because_it_has_no_mark_to_derive_one_from() -> None:
    """`gross_notional()` read 0 with fifteen positions open; this is why."""
    parsed = parse_position(ACCOUNT_ROW)
    assert parsed is not None
    assert parsed.mark_price == 0.0, "nothing is invented for a field the venue did not send"
    assert parsed.venue_notional == pytest.approx(161.36289)
    assert parsed.notional == pytest.approx(161.36289), "the venue's figure, not qty x a missing mark"


def test_a_position_risk_row_falls_back_to_qty_times_mark_because_it_carries_no_notional() -> None:
    parsed = parse_position(RISK_ROW)
    assert parsed is not None
    assert parsed.venue_notional is None and parsed.notional == pytest.approx(0.169 * 954.81)


def test_a_liquidation_price_of_zero_is_not_a_price_and_becomes_none() -> None:
    """Under cross margin the venue writes 0 for every long with enough equity behind it (DL-X1).

    Measured on demo 2026-09-06: 14 of 14 longs zero, 4 of 4 shorts non-zero.  Carried through as a
    float it would put every long at distance zero from liquidation, forever.
    """
    assert parse_position(RISK_ROW).liquidation_price is None  # type: ignore[union-attr]
    assert parse_position({**RISK_ROW, "liquidationPrice": "731.44"}).liquidation_price == pytest.approx(731.44)  # type: ignore[union-attr]
    # An account row does not carry the field at all, which must read the same way, not as 0.0.
    assert parse_position(ACCOUNT_ROW).liquidation_price is None  # type: ignore[union-attr]


def test_leverage_is_taken_from_the_payload_even_though_the_payload_is_useless() -> None:
    """Both payloads say "0" regardless of what was set, so `state.leverage_set` is the record.

    Pinned so that nobody "fixes" this by inferring leverage from notional/margin - that arithmetic
    would be wrong in exactly the way the margin sentinel below is wrong.
    """
    assert parse_position(RISK_ROW).leverage == 0  # type: ignore[union-attr]


def test_a_flat_row_is_dropped_and_a_short_keeps_its_sign() -> None:
    assert parse_position({"symbol": "X", "positionAmt": "0"}) is None
    assert parse_position({"symbol": "X", "positionAmt": "0.0"}) is None
    short = parse_position({**ACCOUNT_ROW, "positionAmt": "-0.169", "notional": "-161.36289000"})
    assert short is not None and short.qty < 0 and short.notional < 0


def test_an_unparseable_number_reads_as_zero_rather_than_raising_mid_cycle() -> None:
    """A venue that sends "" or null for a numeric field must not abort a whole trading cycle."""
    parsed = parse_position({**RISK_ROW, "markPrice": "", "entryPrice": None})
    assert parsed is not None and parsed.mark_price == 0.0 and parsed.entry_price == 0.0


async def test_the_int64_overflow_sentinel_marks_the_margin_fields_unreliable() -> None:
    """92233720368.54775807 is int64 max over 1e8 - an overflow sentinel, not a margin requirement.

    Observed on demo-fapi 2026-09-04.  The venue then derives `availableBalance` and
    `maxWithdrawAmount` as 0 from it, which would make the margin scaler drop every risk-adding order
    while the account is in fact 95% free.  The corruption is detectable because maintenance margin
    and margin balance stay sane: initial margin can never exceed the margin balance.
    """
    venue = _venue(
        {
            "/fapi/v2/account": {
                "totalWalletBalance": "10000",
                "availableBalance": "0",
                "totalMarginBalance": "10100",
                "totalInitialMargin": "92233720368.54775807",
                "canTrade": True,
                "positions": [ACCOUNT_ROW],
            }
        }
    )
    account = await venue.account()
    assert not account.margin_fields_reliable, "the caller must compute its own headroom"
    assert account.equity == 10100.0 and account.available_balance == 0.0, "the raw figures are still reported"
    await venue.aclose()


async def test_an_ordinary_account_keeps_its_margin_fields_trusted() -> None:
    """The control: the sentinel check must not condemn a healthy payload."""
    venue = _venue(
        {
            "/fapi/v2/account": {
                "totalWalletBalance": "10000",
                "availableBalance": "9000",
                "totalMarginBalance": "10100",
                "totalInitialMargin": "512.5",
                "canTrade": True,
                "positions": [ACCOUNT_ROW],
                "assets": [{"asset": "BTC", "marginBalance": "4000"}, {"asset": "USDT", "marginBalance": "6100"}],
            }
        }
    )
    account = await venue.account()
    assert account.margin_fields_reliable
    assert account.usdt_equity == pytest.approx(6100.0), "L1-10: the USDT slice of a multi-asset equity"
    await venue.aclose()


async def test_an_account_with_no_asset_breakdown_reports_none_rather_than_zero_usdt() -> None:
    """0.0 would read as "all of it is collateral", which is the opposite of "we were not told"."""
    venue = _venue(
        {
            "/fapi/v2/account": {
                "totalWalletBalance": "10000",
                "availableBalance": "9000",
                "totalMarginBalance": "10100",
                "totalInitialMargin": "0",
                "canTrade": True,
                "positions": [],
            }
        }
    )
    account = await venue.account()
    assert account.usdt_equity is None and account.positions == {}
    await venue.aclose()


async def test_margin_mode_reads_the_isolated_boolean_because_demo_spells_margin_type_lowercase() -> None:
    """`marginType == "CROSSED"` would have matched nothing: demo-fapi sends "cross" / "isolated".

    Checked against all 18 open positions on 2026-09-07.  Written the obvious way the assertion
    refuses every startup; written the other way round it refuses nothing.  A spelling change is
    silent, a missing boolean is loud - hence the boolean.
    """
    venue = _venue(
        {
            "/fapi/v1/multiAssetsMargin": {"multiAssetsMargin": True},
            "/fapi/v2/positionRisk": [
                {**RISK_ROW, "symbol": "ZECUSDT", "isolated": False, "marginType": "cross"},
                {**RISK_ROW, "symbol": "ETHUSDT", "isolated": True, "marginType": "isolated"},
                # Flat, and still isolated: margin mode outlives the position, so it is still isolated
                # when the book opens this symbol again tomorrow.
                {**RISK_ROW, "symbol": "BNBUSDT", "positionAmt": "0", "isolated": True, "marginType": "isolated"},
            ],
        }
    )
    mode = await venue.margin_mode()
    assert mode == {"multi_assets": True, "isolated_symbols": ["BNBUSDT", "ETHUSDT"]}
    await venue.aclose()


async def test_margin_mode_does_not_trust_margin_type_even_when_it_contradicts_the_boolean() -> None:
    """If the two fields ever disagree, the boolean wins - that is the documented reading."""
    venue = _venue(
        {
            "/fapi/v1/multiAssetsMargin": {"multiAssetsMargin": False},
            "/fapi/v2/positionRisk": [{**RISK_ROW, "symbol": "SOLUSDT", "isolated": False, "marginType": "ISOLATED"}],
        }
    )
    assert (await venue.margin_mode())["isolated_symbols"] == []
    await venue.aclose()


async def test_positions_are_keyed_by_symbol_and_flat_ones_never_appear() -> None:
    venue = _venue(
        {
            "/fapi/v2/positionRisk": [
                RISK_ROW,
                {**RISK_ROW, "symbol": "ETHUSDT", "positionAmt": "-2.5"},
                {**RISK_ROW, "symbol": "BNBUSDT", "positionAmt": "0"},
            ]
        }
    )
    positions = await venue.positions()
    assert sorted(positions) == ["ETHUSDT", "ZECUSDT"] and positions["ETHUSDT"].qty == -2.5
    await venue.aclose()
