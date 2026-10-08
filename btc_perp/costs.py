"""Fixed account values and current position-size limits."""

from __future__ import annotations

TAKER = 0.0004
SLIP_BASE = 0.0001
IMPACT_Y = 0.5
FX_FEE = 0.0035
LEVERAGE = 20.0
START_CNY = 10000.0
MIN_NOTIONAL = 100.0
# Fixed hard ceiling for the current 20x account sizing.
MAX_NOTIONAL_20X = 5_000_000.0

ENTRY_SCALE_BELOW = 0.82
ENTRY_SCALE = 0.5
# Path equity at or below this fraction of the path peak closes the position.
FLATTEN_RATIO = 0.5
