from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from starquant_live.paper import PaperVenue
from starquant_shared.types import OrderRequest, Side, VenueError
from tests.fakes.fake_venue import DEFAULT_RULES


async def test_paper_venue_fills_marks_and_persists(tmp_path: Path) -> None:
    venue = PaperVenue(rules=DEFAULT_RULES, balance=1_000.0, state_path=tmp_path / "paper.json")
    venue.mark({"ETHUSDT": 2_000.0})
    ack = await venue.place_order(OrderRequest("ETHUSDT", Side.BUY, Decimal("0.05"), "bd-1-ETHUSDT"))
    assert ack.status == "FILLED" and ack.avg_price == 2_000.0
    venue.mark({"ETHUSDT": 2_100.0})
    account = await venue.account()
    assert account.positions["ETHUSDT"].unrealized_pnl == pytest.approx(5.0)
    with pytest.raises(VenueError):
        await venue.place_order(OrderRequest("ETHUSDT", Side.BUY, Decimal("0.05"), "bd-1-ETHUSDT"))
    reloaded = PaperVenue(rules=DEFAULT_RULES, state_path=tmp_path / "paper.json")
    assert reloaded.qty["ETHUSDT"] == pytest.approx(0.05)
    assert await reloaded.query_order("ETHUSDT", "bd-1-ETHUSDT") is not None
    close = await reloaded.place_order(
        OrderRequest("ETHUSDT", Side.SELL, Decimal("0.05"), "bd-2-ETHUSDT", reduce_only=True)
    )
    assert close.status == "FILLED" and reloaded.qty.get("ETHUSDT", 0.0) == 0.0
    income = await reloaded.income(0, 1)
    assert any(row["incomeType"] == "REALIZED_PNL" for row in income)
