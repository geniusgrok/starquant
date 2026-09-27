"""What one live cycle feeds the model: closed bars, the latest funding rates and, when the model reads it,
funding history over the same window.

Shared by the engine and by ``starquant live verify`` so the offline reproduction of a cycle (M-011) builds its
inputs through exactly the same code as the cycle itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from starquant_live.bar_sanity import check_bars
from starquant_live.ports import MarketData, SignalModel


def required_history(model: SignalModel, floor: int) -> int:
    """Closed bars a cycle must request: the listing-age filter plus the model's warmup under its real params."""
    needed = int(getattr(model, "min_history_bars", 0)) + int(getattr(model, "warmup_bars", 0))
    return max(int(floor), needed)


def first_open_ms(frame: pd.DataFrame) -> int | None:
    """Open time of the first bar in a closed-bar frame (``open_time`` column or a UTC DatetimeIndex)."""
    if len(frame) == 0:
        return None
    if "open_time" in frame.columns:
        return int(frame["open_time"].iloc[0])
    if isinstance(frame.index, pd.DatetimeIndex):
        stamp = pd.Timestamp(frame.index[0])
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
        return int(stamp.timestamp() * 1000)
    return None


@dataclass
class ModelInputs:
    bars: dict[str, pd.DataFrame]
    funding: dict[str, float]
    funding_history: dict[str, pd.Series] | None = None
    dropped: list[str] = field(default_factory=list)  # symbols whose frame was missing or too short
    # G6: `bar_sanity.check_bars` over `bars`.  A reading for the cycle row and the daily report; the
    # model is never handed it, so no weight can depend on it.  Not in `to_dict`: `inputs` keeps its shape.
    sanity: dict[str, Any] = field(default_factory=dict)

    def settled_symbols(self) -> int:
        """Symbols carrying at least one settlement this cycle.  A zero column and no column are one input."""
        if self.funding_history is None:
            return 0
        return sum(1 for series in self.funding_history.values() if float(series.abs().sum()) > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": len(self.bars),
            "bars": min((len(frame) for frame in self.bars.values()), default=0),
            "funding_history": self.funding_history is not None,
            # The live twin of `Panel.settled_symbols`, and the question the flag above cannot answer.
            # `funding_history is not None` says a frame was FETCHED - it stayed true for 37 cycles
            # while the crowding modifier was inert (D-042) - and a symbol with no archive comes back
            # as a column of zeros, which the modifier cannot tell from calm funding.  Research has
            # recorded `symbols_settled` in every report since `_funding_facts`; the loop recorded a
            # boolean, so the two halves of one comparison were not comparable.
            "symbols_settled": self.settled_symbols(),
            "dropped": list(self.dropped),
        }


async def model_inputs(
    market: MarketData, model: SignalModel, symbols: Sequence[str], interval: str, history_bars: int
) -> ModelInputs:
    """Fetch the cycle's inputs.  Funding history is fetched only when the model consumes it (KILL-027)."""
    bars = await market.closed_bars(symbols, interval, history_bars)
    usable = {symbol: frame for symbol, frame in bars.items() if frame is not None and len(frame) >= 2}
    dropped = [symbol for symbol in symbols if symbol not in usable]
    if not usable:
        raise RuntimeError("no closed bars returned for the universe")
    funding = await market.funding_rates(symbols)
    history: dict[str, pd.Series] | None = None
    if bool(getattr(model, "needs_funding", False)):
        starts = [start for start in (first_open_ms(frame) for frame in usable.values()) if start is not None]
        history = await market.funding_history(list(usable), min(starts) if starts else 0)
    sanity = check_bars(usable, interval)  # alert only, never raises (see its module docstring)
    return ModelInputs(bars=usable, funding=dict(funding), funding_history=history, dropped=dropped, sanity=sanity)


def latest_closes(bars: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    return {symbol: float(frame["close"].iloc[-1]) for symbol, frame in bars.items()}
