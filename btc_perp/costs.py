"""Cost and entry-size constants for the research replay.

``scripts.frontier.run`` reads these values. ``config/btc_account.yaml`` repeats
the fee fields. ``tests/test_btc_account.py`` fails if the two copies diverge.
"""

from __future__ import annotations

TAKER = 0.0004
SLIP_BASE = 0.0001
IMPACT_Y = 0.5
FX_FEE = 0.0035
LEVERAGE = 20.0
START_CNY = 10000.0
# Cash left untouched so one isolated position cannot spend the whole wallet.
CASH_BUFFER = 0.02
MIN_NOTIONAL = 100.0
# Highest notional Binance allows at 20x on the BTCUSDT bracket used below.
MAX_NOTIONAL_20X = 5_000_000.0

# USD-M BTCUSDT maintenance brackets. Margin = notional * rate - amount.
# The amount keeps the schedule continuous at each boundary. This is the
# published 125x table (0.40% / 0.50% / 1.00% / 2.50% / 5.00%), not a live
# pull. Binance has revised brackets during 2020–2026; the replay uses one table.
MARGIN_BRACKETS = (
    (50_000.0, 0.004, 0.0),
    (250_000.0, 0.005, 50.0),
    (1_000_000.0, 0.010, 1_300.0),
    (5_000_000.0, 0.025, 16_300.0),
    (20_000_000.0, 0.050, 141_300.0),
)

# A new entry is scaled once close-to-close equity is below this fraction of
# the close-to-close peak. Pyramid adds do not use the factor.
# config/btc_account.yaml repeats these. A test fails if the copies diverge.
ENTRY_SCALE_BELOW = 0.82
ENTRY_SCALE = 0.5
# Path equity at or below this fraction of the path peak closes the position.
FLATTEN_RATIO = 0.5


def new_entry_scale(close_ratio: float) -> float:
    """Risk multiplier for a new entry. ``close_ratio`` is equity divided by the close peak."""
    if close_ratio < ENTRY_SCALE_BELOW:
        return ENTRY_SCALE
    return 1.0
