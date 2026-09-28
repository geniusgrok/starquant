"""User-stream hints. A hint never changes the position.

Field names follow the USDⓈ-M user stream as published before the 2025-12 algo
migration, plus ``clientAlgoId``. The developers site did not return those
pages from this environment on 2026-09-28, so a live Demo socket is still
unverified. A missed or expired stream is healed by the REST snapshot.
"""

from __future__ import annotations


def hint_from_event(payload: dict[str, object]) -> tuple[str, str]:
    """Return ``(kind, client id)``. ``kind`` is ``order``, ``algo``, ``expired``, or ``ignore``."""
    event = str(payload.get("e", ""))
    if event == "listenKeyExpired":
        return "expired", ""
    order = payload.get("o")
    if not isinstance(order, dict):
        order = {}
    if event == "ALGO_UPDATE":
        client = order.get("caid", order.get("clientAlgoId", ""))
        return "algo", str(client)
    if event == "ORDER_TRADE_UPDATE":
        client = order.get("c", order.get("clientOrderId", ""))
        return "order", str(client)
    return "ignore", event
