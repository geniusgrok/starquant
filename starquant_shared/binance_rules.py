"""Pure parsing of Binance USDⓈ-M ``exchangeInfo`` into :class:`InstrumentRules`."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from starquant_shared.types import InstrumentRules


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)
    return parsed if parsed.is_finite() else Decimal(default)


def parse_symbol_rules(payload: Mapping[str, Any]) -> InstrumentRules | None:
    symbol = str(payload.get("symbol", ""))
    if not symbol:
        return None
    filters = {str(item.get("filterType")): item for item in payload.get("filters", []) if isinstance(item, Mapping)}
    price = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    notional = filters.get("MIN_NOTIONAL", {})
    return InstrumentRules(
        symbol=symbol,
        tick_size=_decimal(price.get("tickSize"), "0.01"),
        step_size=_decimal(lot.get("stepSize"), "0.001"),
        min_qty=_decimal(lot.get("minQty"), "0"),
        min_notional=_decimal(notional.get("notional"), "5"),
        status=str(payload.get("status", "")),
        contract_type=str(payload.get("contractType", "")),
        quote_asset=str(payload.get("quoteAsset", "")),
    )


def parse_exchange_info(payload: Mapping[str, Any]) -> dict[str, InstrumentRules]:
    rules: dict[str, InstrumentRules] = {}
    for item in payload.get("symbols", []):
        if not isinstance(item, Mapping):
            continue
        parsed = parse_symbol_rules(item)
        if parsed is not None:
            rules[parsed.symbol] = parsed
    return rules
