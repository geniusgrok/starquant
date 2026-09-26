"""Exchange leverage derivation and margin-aware order scaling (D-016; legacy lesson E-035: one risk budget).

Exposure is decided by the portfolio layer (vol target, max_gross, max_weight).
The exchange leverage setting only decides how much *margin* that exposure
consumes: at leverage L and gross G the initial margin is G / L of equity.
``derive_leverage`` picks the smallest integer leverage that keeps margin use
at the gross cap below ``margin_cap``, bounded by the venue bracket and a hard
``max_leverage``.  ``scale_orders_to_margin`` shrinks risk-adding orders
pro-rata when the available balance cannot fund them, instead of letting the
venue reject them one by one (-2019).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from starquant_exchange.rules import meets_min_notional, quantize_qty
from starquant_live.rebalancer import PlannedOrder
from starquant_shared.types import InstrumentRules


def derive_leverage(max_gross: float, margin_cap: float, max_leverage: int, bracket_max: int | None = None) -> int:
    """Smallest integer leverage with ``max_gross / leverage <= margin_cap``, capped by bracket and policy."""
    if max_gross <= 0 or margin_cap <= 0 or max_leverage < 1:
        raise ValueError("max_gross, margin_cap must be positive and max_leverage >= 1")
    needed = math.ceil(max_gross / margin_cap - 1e-12)
    chosen = min(max(1, needed), int(max_leverage))
    if bracket_max is not None and bracket_max >= 1:
        chosen = min(chosen, int(bracket_max))
    return max(1, chosen)


def _margin_exposure(order: PlannedOrder) -> float:
    """The part of ``order.notional`` that actually *consumes* margin.

    A flip - long into short, or the reverse - is not ``reduce_only``, because it ends on the other
    side.  Its quantity is ``|current| + |target|``, and the ``|current|`` half CLOSES the standing
    position, so it releases margin rather than consuming it.  Counting the whole notional overstated
    ``needed`` and could shrink a book that fits (2026-09-13 review).  Only the ``|target|`` half is new
    exposure, expressed as ``notional - |current|`` rather than as a flat ``|target|`` so that a flip
    whose quantity was already truncated upstream (``max_order_notional``, the participation cap) is
    charged for what it actually opens - such an order may not even reach zero, and then it opens
    nothing.  For every other order this is ``order.notional`` unchanged.
    """
    flips = order.current_notional * order.target_notional < 0.0
    if not flips:
        return order.notional
    return max(0.0, order.notional - abs(order.current_notional))


def scale_orders_to_margin(
    orders: Sequence[PlannedOrder],
    available_balance: float,
    leverage_by_symbol: Mapping[str, int],
    rules: Mapping[str, InstrumentRules],
    *,
    buffer: float = 0.10,
    default_leverage: int = 1,
) -> tuple[list[PlannedOrder], dict[str, Any]]:
    """Shrink risk-adding orders pro-rata so their initial margin fits ``available_balance * (1 - buffer)``.

    Reduce-only orders are never scaled (they release margin).  Orders that
    fall below the venue minimum after scaling are dropped and reported.

    This is a PRE-CHECK, which is why ``_margin_exposure`` may correct it downwards without a window:
    it exists so the venue does not reject orders one by one (-2019), it can only ever shrink what
    ``plan_rebalance`` already decided, and the venue's own margin check remains the backstop.
    """
    adds = [order for order in orders if not order.reduce_only]
    needed = sum(
        _margin_exposure(order) / max(1, leverage_by_symbol.get(order.symbol, default_leverage)) for order in adds
    )
    budget = max(0.0, float(available_balance)) * (1.0 - buffer)
    if not adds or needed <= budget:
        return list(orders), {"scaled": False, "needed_margin": needed, "budget": budget}
    factor = budget / needed if needed > 0 else 0.0
    kept: list[PlannedOrder] = []
    dropped: list[dict[str, Any]] = []
    for order in orders:
        if order.reduce_only:
            kept.append(order)
            continue
        rule = rules.get(order.symbol)
        # No rule means no step to quantize to, and an unquantizable order is dropped below rather than
        # sent at an unknown step.  Spelled `Decimal(0)`: it used to read `order.quantity * 0`, which is
        # the same zero by Decimal arithmetic but reads like a typo.
        quantity = quantize_qty(float(order.quantity) * factor, rule) if rule is not None else Decimal(0)
        if quantity <= 0 or (rule is not None and not meets_min_notional(quantity, order.price, rule)):
            dropped.append({"symbol": order.symbol, "reason": "MARGIN_SCALED_BELOW_MIN", "factor": factor})
            continue
        kept.append(replace(order, quantity=quantity, note=(order.note + ";" if order.note else "") + "MARGIN_SCALED"))
    return kept, {"scaled": True, "factor": factor, "needed_margin": needed, "budget": budget, "dropped": dropped}
