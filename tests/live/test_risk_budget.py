"""M2/M3: the construction digest can see the vol target, and `auto` refuses a leverage cap it cannot honour."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from starquant_alpha.portfolio import PortfolioParams
from starquant_live.engine import LiveConfig, LiveEngine, construction_fingerprint
from starquant_live.guards import GuardParams
from starquant_live.rebalancer import RebalanceParams
from starquant_live.state import StateStore
from tests.fakes.fake_venue import FakeVenue
from tests.live.fakes import FakeClock, FakeMarketData
from tests.live.test_live_loop import SYMBOLS, _model, _prices


def _config(tmp_path: Path, **overrides: object) -> LiveConfig:
    base: dict[str, object] = {
        "interval": "1h",
        "history_bars": 300,
        "universe": tuple(SYMBOLS),
        "leverage": 2,
        "rebalance": RebalanceParams(no_trade_band=0.002),
        "guards": GuardParams(),
        "kill_switch_path": tmp_path / "KILL_SWITCH",
        "strategy_weights": {"tsmom": 1.0},
        "poll_interval_seconds": 0.0,
        "grace_seconds": 1.0,
    }
    base.update(overrides)
    return LiveConfig(**base)  # type: ignore[arg-type]


def test_the_digest_moves_when_the_vol_target_moves(tmp_path: Path) -> None:
    """D-026's second half: doubling the book's size used to leave the construction record identical."""
    base = _config(tmp_path, portfolio=PortfolioParams(vol_target=0.15))
    doubled = replace(base, portfolio=PortfolioParams(vol_target=0.30))
    before = construction_fingerprint(base)
    after = construction_fingerprint(doubled)
    assert before["digest"] != after["digest"]
    assert before["portfolio"]["vol_target"] == 0.15
    assert after["portfolio"]["vol_target"] == 0.30
    # the other construction knobs travel with it, so a later reader can reconstruct the book
    assert set(after["portfolio"]) == {
        "vol_target",
        "vol_halflife",
        "covariance_halflife",
        "min_asset_vol",
        "max_scalar",
        "min_history_bars",  # v4 (2026-09-09): it decides which symbols may be held
        "sleeve_max_gross",  # v5 (P30, 2026-09-12): how big a non-main book may run before its fraction
    }


def _engine(tmp_path: Path, august_panel, **overrides: object) -> LiveEngine:
    cursor = 400
    market = FakeMarketData(august_panel, cursor)
    venue = FakeVenue(balance=10_000.0, prices=_prices(august_panel, cursor))
    return LiveEngine(
        _config(tmp_path, **overrides),
        model=_model(),
        market=market,
        venue=venue,
        clock=FakeClock(market.bar_open_ms(cursor) + 5_000),
        store=StateStore(tmp_path / "live"),
    )


@pytest.mark.asyncio
async def test_auto_refuses_a_leverage_cap_that_cannot_honour_the_margin_cap(tmp_path: Path, august_panel) -> None:
    engine = _engine(
        tmp_path,
        august_panel,
        leverage_mode="auto",
        max_leverage=5,
        margin_cap=0.40,
        guards=GuardParams(max_gross=3.0),  # needs 8x; the 5x cap would silently run at 60% margin
    )
    with pytest.raises(RuntimeError, match="margin_cap"):
        await engine.startup()


@pytest.mark.asyncio
async def test_auto_starts_when_the_three_numbers_are_consistent(tmp_path: Path, august_panel) -> None:
    engine = _engine(
        tmp_path,
        august_panel,
        leverage_mode="auto",
        max_leverage=5,
        margin_cap=0.40,
        guards=GuardParams(max_gross=2.0),  # exactly 5 x 0.40
    )
    await engine.startup()
    assert engine.state.leverage_set


@pytest.mark.asyncio
async def test_fixed_mode_is_exempt_because_margin_cap_is_not_consulted_there(tmp_path: Path, august_panel) -> None:
    """The profile's own note - "was 100% at a fixed 2x" - is a state this check must not retroactively ban."""
    engine = _engine(tmp_path, august_panel, leverage=2, guards=GuardParams(max_gross=2.0), margin_cap=0.40)
    await engine.startup()
