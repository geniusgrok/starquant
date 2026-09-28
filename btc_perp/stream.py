"""User-stream hints. A hint never changes the position.

``ALGO_UPDATE`` uses the object key ``o`` and client id ``caid``. That matches
the binance SDK 3.6.0 raw type and a published 2025-12-11 payload. ``ao`` and
``ALGO_ORDER_UPDATE`` are accepted as aliases. A missed or expired stream is
healed by the REST snapshot. This parser has not been checked on a live Demo
socket.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamHint:
    kind: str
    client_id: str
    status: str


def parse_stream_event(payload: dict[str, object]) -> StreamHint:
    """``kind`` is ``order``, ``algo``, ``account``, ``expired``, ``reject``, or ``ignore``."""
    event = str(payload.get("e", ""))
    if event == "listenKeyExpired":
        return StreamHint("expired", "", "")
    if event == "ACCOUNT_UPDATE":
        return StreamHint("account", "", "")
    order = payload.get("o", payload.get("ao"))
    if not isinstance(order, dict):
        order = {}
    if event in {"ALGO_UPDATE", "ALGO_ORDER_UPDATE"}:
        client = order.get("caid", order.get("clientAlgoId", ""))
        return StreamHint("algo", str(client), str(order.get("X", "")))
    if event == "ORDER_TRADE_UPDATE":
        client = order.get("c", order.get("clientOrderId", ""))
        return StreamHint("order", str(client), str(order.get("X", "")))
    if event == "CONDITIONAL_ORDER_TRIGGER_REJECT":
        client = order.get("caid", order.get("c", ""))
        return StreamHint("reject", str(client), "REJECTED")
    return StreamHint("ignore", "", event)


def hint_from_event(payload: dict[str, object]) -> tuple[str, str]:
    hint = parse_stream_event(payload)
    return hint.kind, hint.client_id
