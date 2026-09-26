"""Path-dependent overlays applied to portfolio weights: exits (stop/trail/take-profit) and exposure throttles.

Overlays are pure functions of price and weight histories.  The live loop
reuses the same per-bar step functions so backtest and live semantics are
identical by construction (D-012, D-015).
"""

from starquant_alpha.overlays.exits import ExitParams, ExitResult, ExitState, apply_exits, exit_step
from starquant_alpha.overlays.exposure import DrawdownThrottleParams, apply_drawdown_throttle, drawdown_scalar

__all__ = [
    "DrawdownThrottleParams",
    "ExitParams",
    "ExitResult",
    "ExitState",
    "apply_drawdown_throttle",
    "apply_exits",
    "drawdown_scalar",
    "exit_step",
]
