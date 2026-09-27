"""Quantisation against venue trading rules."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from starquant_shared.types import InstrumentRules


def quantize_qty(quantity: float | Decimal, rules: InstrumentRules) -> Decimal:
    """Round |quantity| down to the step size; returns 0 when below minQty."""
    step = rules.step_size
    raw = abs(Decimal(str(quantity)))
    if step <= 0:
        return raw
    quantized = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
    quantized = quantized.quantize(step) if step < 1 else quantized
    if quantized < rules.min_qty:
        return Decimal("0")
    return quantized


def quantize_price(price: float | Decimal, rules: InstrumentRules) -> Decimal:
    tick = rules.tick_size
    raw = Decimal(str(price))
    if tick <= 0:
        return raw
    return ((raw / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick).quantize(tick)


def meets_min_notional(quantity: Decimal, price: float, rules: InstrumentRules) -> bool:
    return quantity * Decimal(str(price)) >= rules.min_notional


def format_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text else "0"
