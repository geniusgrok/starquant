"""T-P01/T-P02: hysteresis ranking and point-in-time membership (pure)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import numpy as np
import pandas as pd

from starquant_data.pool import (
    LivePool,
    membership_at_bars,
    membership_summary,
    point_in_time_membership,
    refresh_selection,
    tenure_mask,
)
from starquant_data.universe import UniverseConfig, rank_with_hysteresis
from starquant_shared.types import InstrumentRules


def _rules(symbols: list[str]) -> dict[str, InstrumentRules]:
    return {s: InstrumentRules(s, Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("5")) for s in symbols}


def test_rank_with_hysteresis_enter_exit_and_pins() -> None:
    """T-P01: rank <= 15 enters, an incumbent survives to rank 20, rank 21 leaves, pins survive any rank."""
    symbols = [f"S{i:02d}" for i in range(1, 31)]
    volumes = {s: float(100 - i) for i, s in enumerate(symbols)}  # S01 is rank 1 ... S30 rank 30
    previous = ["S18", "S21", "S05"]
    chosen = rank_with_hysteresis(
        volumes, symbols, previous, enter_rank=15, exit_rank=20, top_n=15, always_include=("S30",)
    )
    assert set(symbols[:15]) <= set(chosen)
    assert "S18" in chosen and "S21" not in chosen and "S30" in chosen
    assert chosen[0] == "S01" and len(chosen) <= 21
    update = refresh_selection(volumes, _rules(symbols), UniverseConfig(top_n=15), previous, at_ms=1)
    assert "S21" in update.left and "S01" in update.entered and update.symbols[0] == "S01"


def test_point_in_time_membership_is_causal_and_respects_listing_age() -> None:
    """T-P02: a symbol cannot be a member before it has min_age_days of bars, and a refresh only sees earlier days."""
    days = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    volume = pd.DataFrame({"A": 100.0, "B": 90.0, "C": np.nan, "D": 10.0}, index=days)
    volume.loc[days[60:], "C"] = 1000.0  # listed on day 60 with huge volume
    volume.loc[days[95:], "D"] = 5000.0  # D becomes the most liquid name only from day 95
    config = UniverseConfig(top_n=2, enter_rank=2, exit_rank=3, min_age_days=30, volume_lookback_days=30)
    membership = point_in_time_membership(volume, config, refresh="MS")
    assert list(membership.index) == [
        pd.Timestamp("2024-01-31", tz="UTC"),
        *pd.date_range("2024-02-01", "2024-04-01", freq="MS", tz="UTC"),
    ]
    march = membership.loc["2024-03-01"]
    assert bool(march["A"]) and bool(march["B"]) and not bool(march["C"])  # C listed 2024-03-01: no age yet
    april = membership.loc["2024-04-01"]
    assert bool(april["C"]) and not bool(april["D"])  # D's surge starts after the April refresh: unseen
    assert not bool(april["B"]) or bool(april["A"])  # exactly top-2 plus hysteresis survivors
    hourly = pd.date_range("2024-01-20", periods=24 * 80, freq="h", tz="UTC")
    at_bars = membership_at_bars(membership, hourly)
    assert not at_bars.loc["2024-01-20 00:00", "A"]  # before the first refresh nobody is in
    assert at_bars.loc["2024-02-15 12:00", "A"] and not at_bars.loc["2024-02-15 12:00", "C"]
    assert at_bars.loc["2024-04-02 00:00", "C"]
    summary = membership_summary(membership)
    assert summary["refreshes"] == len(membership) and "C" in summary["union"]


def test_tenure_mask_is_causal_and_cumulative() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="MS", tz="UTC")
    membership = pd.DataFrame({"A": [True, True, True, True], "B": [False, True, False, True]}, index=index)
    established = tenure_mask(membership, 2)
    assert established["A"].tolist() == [False, True, True, True]
    assert established["B"].tolist() == [False, False, False, True]  # second selection counts even after a gap
    pd.testing.assert_frame_equal(tenure_mask(membership, 1), membership)


class _FakeDailyClient:
    """The public-data half of a live refresh: 24h tickers, and daily bars whose count is the listing age."""

    DAY_MS = 86_400_000

    def __init__(self, ages: dict[str, int], volumes: dict[str, float], now_ms: int) -> None:
        self.ages, self.volumes, self.now_ms = ages, volumes, now_ms

    async def server_time_ms(self) -> int:
        return self.now_ms

    async def ticker_24h(self) -> list[dict[str, object]]:
        return [{"symbol": s, "quoteVolume": v} for s, v in self.volumes.items()]

    async def klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        bars = min(self.ages[symbol], limit)
        opens = [self.now_ms - (bars - i) * self.DAY_MS for i in range(bars)]
        return pd.DataFrame(
            {
                "open_time": opens,
                "close_time": [o + self.DAY_MS - 1 for o in opens],
                "quote_volume": [self.volumes[symbol] for _ in opens],
            }
        )


def test_live_pool_applies_the_same_listing_age_filter_as_research() -> None:
    """G1: a listing too young for ``point_in_time_membership`` must not take a live slot either.

    The two halves of D-013 have to agree, or the live book runs on fewer names than the backtest that
    justified it: ``min_history_bars`` refuses to trade the young name, but the pool has already spent
    one of ``top_n`` slots on it, and nothing reports the difference.
    """
    now_ms = 1_700_000_000_000
    ages = {"OLDUSDT": 400, "MIDUSDT": 400, "NEWUSDT": 9, "PINUSDT": 5}
    volumes = {"NEWUSDT": 9e9, "OLDUSDT": 5e9, "MIDUSDT": 4e9, "PINUSDT": 3e9}
    config = UniverseConfig(top_n=2, enter_rank=2, exit_rank=3, min_age_days=30, always_include=("PINUSDT",))
    update = asyncio.run(LivePool(_FakeDailyClient(ages, volumes, now_ms), config).select((), _rules(list(ages))))
    assert "NEWUSDT" not in update.symbols  # ranks first by volume, nine days old
    assert "PINUSDT" not in update.symbols  # a pin is not a way around the age filter either
    assert list(update.symbols) == ["OLDUSDT", "MIDUSDT"]

    # ... and research, given the same ages and volumes, selects the same two names.
    days = pd.date_range(end=pd.Timestamp(now_ms, unit="ms", tz="UTC").normalize(), periods=400, freq="D")
    daily = pd.DataFrame({s: [volumes[s]] * len(days) for s in ages}, index=days)
    for symbol, age in ages.items():
        daily.loc[days[: len(days) - age], symbol] = np.nan
    membership = point_in_time_membership(daily, config, refresh="D", start=str(days[-1].date()))
    assert sorted(membership.columns[membership.iloc[-1]]) == ["MIDUSDT", "OLDUSDT"]
