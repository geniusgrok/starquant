"""Live adapter of the exit overlay: venue positions are the truth for direction and entry price (D-012, KILL-022)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pandas as pd

from starquant_alpha.overlays.exits import COOLDOWN, ExitParams, ExitState, daily_vol, exit_step, regime_tp_scale
from starquant_shared.types import Position


class ExitOverlay:
    def __init__(self, params: ExitParams, interval_ms: int) -> None:
        self.params = params
        self.interval_ms = interval_ms

    @property
    def enabled(self) -> bool:
        return self.params.enabled

    def apply(
        self,
        targets: Mapping[str, float],
        *,
        positions: Mapping[str, Position],
        bars: Mapping[str, pd.DataFrame],
        states: Mapping[str, Mapping[str, Any]],
        bar_open_ms: int,
    ) -> tuple[dict[str, float], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Return (adjusted targets, new per-symbol states, exit events)."""
        adjusted = dict(targets)
        new_states: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        if not self.enabled:
            return adjusted, {}, events
        for symbol, target in targets.items():
            frame = bars.get(symbol)
            if frame is None or len(frame) < 2:
                continue
            close = float(frame["close"].iloc[-1])
            if not math.isfinite(close) or close <= 0:
                # Same rule as `exit_step`'s own guard, applied one step earlier because `_reconcile`
                # runs BEFORE it and writes the entry anchor: a NaN close reached `_reconcile`, which
                # adopted it (or the venue VWAP with a NaN unit), and then `exit_step` re-anchored on
                # top of that.  A bar with no close is not information; leaving the symbol out of
                # `new_states` is what preserves the anchor, because the engine merges rather than
                # replaces (`{**self.state.exit_states, **exit_states}`).  The model's own target
                # stands for this cycle, exactly as it does for a missing or too-short frame above.
                continue
            sigma = self._sigma(frame)
            tp_scale = 1.0
            if self.params.regime_window > 0:
                closes = pd.DataFrame({"x": frame["close"].astype(float).to_numpy()})
                scale = regime_tp_scale(closes, self.params)
                tp_scale = float(scale["x"].iloc[-1]) if scale is not None else 1.0
            state = self._reconcile(
                ExitState.from_dict(states.get(symbol, {})), positions.get(symbol), close, sigma, bar_open_ms
            )
            before = state
            state, weight, reason = exit_step(
                state,
                float(target),
                close,
                sigma,
                bar_open_ms,
                self.params,
                bar_step=self.interval_ms,
                tp_scale=tp_scale,
            )
            adjusted[symbol] = weight
            new_states[symbol] = state.to_dict()
            if reason:
                events.append(
                    {
                        "symbol": symbol,
                        "rule": reason,
                        "target": float(target),
                        "price": close,
                        "entry_price": None if math.isnan(before.entry_price) else before.entry_price,
                        "unit": None if math.isnan(before.unit) else before.unit,
                        "cooldown_until_ms": state.cooldown_until if reason != COOLDOWN else before.cooldown_until,
                    }
                )
        return adjusted, new_states, events

    def _sigma(self, frame: pd.DataFrame) -> float:
        closes = pd.DataFrame({"x": frame["close"].astype(float).to_numpy()})
        value = daily_vol(closes, self.params)["x"].iloc[-1]
        return float(value) if pd.notna(value) else float("nan")

    def _reconcile(
        self, state: ExitState, position: Position | None, close: float, sigma: float, bar: int
    ) -> ExitState:
        """Adopt the venue's position as the truth for *direction*; the entry reference is fixed at first entry.

        The venue's VWAP is adopted only when the direction changed or the
        state has no entry yet (a restart into an existing position).  A
        same-direction resize keeps the original entry and volatility unit,
        exactly as ``apply_exits`` does in the backtest (E-047): re-anchoring
        to the venue VWAP every cycle made the live take-profit reference
        drift with every rebalance.

        D-045: a position the overlay has ALREADY exited, and which is still on the venue, is not a
        new entry.  ``exit_step`` drops the anchors when a rule fires - correct in a backtest, where
        weight 0 IS flat on the next bar - but live the order can fail to land: `plan_rebalance`
        refuses a close inside the absolute band (`BAND_BLOCKS_EXIT`, and `rebalancer.py` records
        ENAUSDT sitting that way for days), below `minNotional`, or on a venue rejection.  The next
        cycle then saw `state.direction` 0 against a held position, took the `!= held` branch, and
        re-entered: `entry_price` came back from the venue VWAP (so the real cost survived) but
        ``unit`` was rebuilt from THIS bar's sigma, which is not what D-012 means by "k daily sigmas
        fixed at entry".  Measured on a position entered at 100 and marked at 87: a re-anchor while
        sigma reads 0.01 puts the 6-sigma stop 6 points away and fires; at 0.08 it puts it 48 points
        away and the stop is gone.  Volatility rising is exactly when an exit order is most likely to
        miss, so the failure biased toward releasing the stop in the bar that needed it.

        The state already carries what distinguishes the two cases, so nothing is added to it:
        ``cooldown_direction`` is the side the rule fired on and ``cooldown_until`` is how long that
        decision stands.  Inside that window the overlay keeps saying flat - `exit_step` reaches its
        COOLDOWN branch and returns 0.0 - so the rebalancer keeps being asked to close.  Past it, a
        position still standing is a fresh holding decision and re-anchoring is the honest reading.
        """
        held = 0 if position is None or position.qty == 0.0 else (1 if position.qty > 0 else -1)
        if held == 0:
            return replace(state, direction=0)
        if bar < state.cooldown_until and held == state.cooldown_direction:
            return replace(state, direction=0)
        if state.direction != held or math.isnan(state.entry_price) or math.isnan(state.unit):
            entry = position.entry_price if position is not None and position.entry_price > 0 else close
            unit = sigma if (not math.isnan(sigma) and sigma > 0) else self.params.min_unit
            return ExitState(
                direction=held,
                entry_price=entry,
                extreme=entry,
                unit=max(unit, self.params.min_unit),
                cooldown_until=state.cooldown_until,
                cooldown_direction=state.cooldown_direction,
            )
        extreme = state.extreme if not math.isnan(state.extreme) else state.entry_price
        return replace(state, extreme=extreme)
