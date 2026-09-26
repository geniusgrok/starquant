"""DL-X1 / M-Q06: how close the book is to a liquidation, in units it can be judged in.

Distance is reported in DAILY VOLATILITY units rather than percent, because a percentage says nothing
about whether a name can travel that far.  Split out of ``health.py`` in 2026-09-15: that module was
four unrelated concepts behind a name that predicted none of them, and this is the one its own
``__all__`` did not mention.

Reports only.  Like everything in `risk_budget`'s block it alerts and never trades, and a distance it
cannot compute comes back as ``None`` with a reason rather than as a number that looks safe.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from starquant_shared.types import Position


def liquidation_distance(position: Position, *, daily_vol: float) -> float | None:
    """How far the mark is from the liquidation price, in daily volatility units.

    ``None`` whenever the question does not apply: a flat symbol, no volatility estimate, or - the
    common case - a position the venue reports no reachable liquidation price for.  ``None`` is not
    a small number, and the caller must not be able to treat it as one.
    """
    if position.qty == 0.0 or daily_vol <= 0.0:
        return None
    liquidation = position.liquidation_price
    if liquidation is None or liquidation <= 0.0 or position.mark_price <= 0.0:
        return None
    move = abs(position.mark_price - liquidation) / position.mark_price
    return move / daily_vol


def min_liquidation_distance(positions: Sequence[Position], daily_vol: Mapping[str, float]) -> dict[str, Any]:
    """M-Q06: the closest position that *has* a liquidation price, and how many do not.

    Both halves are reported.  "Every position is out of reach" is a fact about the book; a missing
    number would be a gap in the instrument, and the two must never look the same in the log.
    """
    measured: list[tuple[float, str]] = []
    unreachable = 0
    unmeasurable = 0
    for position in positions:
        if position.qty == 0.0:
            continue
        vol = float(daily_vol.get(position.symbol, 0.0))
        # Three outcomes, not two.  `unmeasurable` is the caller having no volatility estimate for
        # this symbol - the live case is a foreign position, which `asset_vol` never covers because
        # it only sizes the universe.  Folding it into `unreachable` would say "the venue reports no
        # liquidation price" about a symbol the venue was never asked, which is this function's own
        # mistake made one level up.
        if not math.isfinite(vol) or vol <= 0.0:
            unmeasurable += 1
            continue
        distance = liquidation_distance(position, daily_vol=vol)
        if distance is None:
            unreachable += 1
        else:
            measured.append((distance, position.symbol))
    closest = min(measured) if measured else None
    return {
        "min_distance": None if closest is None else closest[0],
        "symbol": None if closest is None else closest[1],
        "measured": len(measured),
        "unreachable": unreachable,
        "unmeasurable": unmeasurable,
    }
