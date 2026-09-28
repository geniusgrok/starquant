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

# A new entry is halved once close-to-close equity is below this fraction of
# the close-to-close peak. Pyramid adds do not use the factor.
ENTRY_SCALE_BELOW = 0.82
ENTRY_SCALE = 0.5


def new_entry_scale(close_ratio: float) -> float:
    """Risk multiplier for a new entry. ``close_ratio`` is equity divided by the close peak."""
    if close_ratio < ENTRY_SCALE_BELOW:
        return ENTRY_SCALE
    return 1.0
