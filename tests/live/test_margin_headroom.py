"""D-027: a venue whose margin arithmetic is corrupt must not silently turn the loop reduce-only.

Observed on demo-fapi 2026-09-04: totalInitialMargin came back as 92233720368.54775807 (int64 max / 1e8),
the venue derived availableBalance 0 from it, and the margin scaler would then have dropped every
risk-adding order while 95% of the account was free.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
from starquant_live.leverage import scale_orders_to_margin
from starquant_live.rebalancer import PlannedOrder
from starquant_live.reconciler import Snapshot
from starquant_shared.types import AccountState, Position, Side
from tests.fakes.fake_venue import DEFAULT_RULES

OVERFLOW = "92233720368.54775807"  # int64 max scaled by 1e8, as the venue returned it


def _account_payload(initial_margin: str) -> dict[str, object]:
    return {
        "totalWalletBalance": "10725.03",
        "totalMarginBalance": "10745.73",
        "availableBalance": "0.00000000",
        "totalInitialMargin": initial_margin,
        "totalMaintMargin": "27.01",
        "canTrade": True,
        "positions": [],
    }


def _snapshot(account: AccountState) -> Snapshot:
    positions = {
        "BTCUSDT": Position("BTCUSDT", qty=0.03, entry_price=60_000.0, mark_price=60_000.0),
        "ETHUSDT": Position("ETHUSDT", qty=-0.36, entry_price=3_000.0, mark_price=3_000.0),
    }
    return Snapshot(account=account, positions=positions, prices={"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0})


def _parse(payload: dict[str, object]) -> AccountState:
    """The parsing half of BinanceUsdmVenue.account, without the HTTP call."""

    class _Stub:
        async def get(self, *_a: object, **_k: object) -> dict[str, object]:
            return payload

    import asyncio

    return asyncio.run(BinanceUsdmVenue(_Stub()).account())  # type: ignore[arg-type]


def test_a_corrupt_initial_margin_is_detected() -> None:
    assert _parse(_account_payload(OVERFLOW)).margin_fields_reliable is False
    assert _parse(_account_payload("576.04")).margin_fields_reliable is True
    # equal to the margin balance is still plausible: a fully committed account
    assert _parse(_account_payload("10745.73")).margin_fields_reliable is True


def test_headroom_falls_back_to_the_positions_when_the_venue_is_corrupt() -> None:
    corrupt = _snapshot(_parse(_account_payload(OVERFLOW)))
    assert corrupt.account.available_balance == 0.0  # what the venue claims
    # 1,800 + 1,080 of notional at the 5x the loop set = 576 of margin against 10,745.73 of equity
    assert corrupt.available_margin({"BTCUSDT": 5, "ETHUSDT": 5}) == pytest.approx(10_745.73 - 576.0, abs=0.01)
    # with no leverage information at all it stays conservative rather than optimistic
    assert corrupt.available_margin() == pytest.approx(10_745.73 - 2_880.0, abs=0.01)


def test_a_sane_venue_number_is_still_authoritative() -> None:
    sane = _snapshot(_parse({**_account_payload("576.04"), "availableBalance": "9999.99"}))
    assert sane.available_margin({"BTCUSDT": 5, "ETHUSDT": 5}) == pytest.approx(9_999.99)


def test_the_corruption_would_otherwise_drop_every_risk_adding_order() -> None:
    """The behaviour this guards against, asserted directly on the scaler."""
    orders = [
        PlannedOrder("BTCUSDT", Side.BUY, Decimal("0.010"), False, "bd-1-BTCUSDT", 0.05, 0.0, 600.0, 60_000.0),
        PlannedOrder("ETHUSDT", Side.SELL, Decimal("0.200"), True, "bd-1-ETHUSDT", -0.02, 0.0, -600.0, 3_000.0),
    ]
    starved, info = scale_orders_to_margin(orders, 0.0, {"BTCUSDT": 5}, DEFAULT_RULES)
    assert [o.symbol for o in starved] == ["ETHUSDT"], "only the reduce-only order survives a zero budget"
    assert info["scaled"] and info["dropped"][0]["symbol"] == "BTCUSDT"
    corrupt = _snapshot(_parse(_account_payload(OVERFLOW)))
    kept, ok = scale_orders_to_margin(
        orders, corrupt.available_margin({"BTCUSDT": 5, "ETHUSDT": 5}), {"BTCUSDT": 5}, DEFAULT_RULES
    )
    assert kept == orders and not ok["scaled"], "with the real headroom both orders go through untouched"
