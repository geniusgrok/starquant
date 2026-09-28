"""Order identity, protection replacement, and reverse sequencing.

Sending is the caller's job. This module only decides which command is safe
and how a snapshot changes a stored intent. A timeout keeps the original
client id.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal

from btc_perp.model import AlgoOrder, Book, Command, Intent, Snapshot

_OPEN = {"NEW", "PARTIALLY_FILLED"}
_ALGO_LIVE = {"NEW"}
_TERMINAL = {"filled", "rejected", "canceled", "expired"}


def new_client_id(action: str) -> str:
    prefix = {"enter": "en", "add": "ad", "reduce": "rd", "stop": "st", "take": "tp", "flatten": "fl"}[action]
    return prefix + uuid.uuid4().hex[:20]


def quantize_down(value: float, step: float) -> str:
    if step <= 0:
        raise ValueError("step must be positive")
    amount = Decimal(str(value))
    size = Decimal(str(step))
    units = (amount / size).to_integral_value(rounding=ROUND_DOWN)
    return format(units * size, "f")


def check_algo_shape(*, close_position: bool, qty: str, reduce_only: bool) -> None:
    if close_position and (qty not in {"", "0"} or reduce_only):
        raise ValueError("closePosition 不能和 quantity 或 reduceOnly 一起用")
    if not close_position and not reduce_only:
        raise ValueError("保护单必须是 closePosition 或 reduceOnly")


def _live_algos(snapshot: Snapshot, order_type: str) -> list[AlgoOrder]:
    return [algo for algo in snapshot.algos if algo.order_type == order_type and algo.status in _ALGO_LIVE]


def protections_cover(snapshot: Snapshot) -> tuple[bool, str]:
    if not snapshot.known:
        return False, "账户未知"
    if abs(snapshot.position_qty) < 1e-8:
        leftover = [algo.client_algo_id for algo in snapshot.algos if algo.status in _ALGO_LIVE]
        if leftover:
            return False, "空仓仍有活动条件单"
        return True, ""
    stops = _live_algos(snapshot, "STOP_MARKET")
    takes = _live_algos(snapshot, "TAKE_PROFIT_MARKET")
    if len(stops) != 1 or len(takes) != 1:
        return False, "活动止损或止盈不是恰好一张"
    closing_side = "SELL" if snapshot.position_qty > 0 else "BUY"
    for algo in (stops[0], takes[0]):
        if algo.side != closing_side:
            return False, "保护单方向和持仓不一致"
        if algo.working_type != "CONTRACT_PRICE":
            return False, "保护单触发价源不是合约最新价"
        if algo.status not in _ALGO_LIVE:
            return False, "保护单不是活动状态"
        if algo.close_position:
            if algo.reduce_only or algo.qty:
                return False, "closePosition 保护单还带了数量或 reduceOnly"
        elif not algo.reduce_only or algo.qty + 1e-12 < abs(snapshot.position_qty):
            return False, "保护单数量盖不住实仓"
        if algo.trigger_price <= 0:
            return False, "保护单触发价无效"
    stop_px = stops[0].trigger_price
    take_px = takes[0].trigger_price
    # A trailed long stop can sit above the original entry. It still has to
    # sit below the take, and on the protective side of the last trade.
    if snapshot.position_qty > 0 and not stop_px < take_px:
        return False, "多仓止损不在止盈下方"
    if snapshot.position_qty < 0 and not stop_px > take_px:
        return False, "空仓止损不在止盈上方"
    if snapshot.position_qty > 0 and snapshot.last_price > 0 and stop_px >= snapshot.last_price:
        return False, "多仓止损不在现价下方"
    if snapshot.position_qty < 0 and snapshot.last_price > 0 and stop_px <= snapshot.last_price:
        return False, "空仓止损不在现价上方"
    return True, ""


def foreign_ids(snapshot: Snapshot, known: set[str]) -> list[str]:
    found: list[str] = []
    for order in snapshot.orders:
        if order.status in _OPEN and order.client_id not in known:
            found.append(order.client_id or "order-without-id")
    for algo in snapshot.algos:
        if algo.status in _ALGO_LIVE and algo.client_algo_id not in known:
            found.append(algo.client_algo_id or "algo-without-id")
    return found


def adopt_snapshot(intents: list[Intent], snapshot: Snapshot) -> list[tuple[str, str]]:
    """Map stored ids onto the snapshot. Missing ids stay unknown; none are replaced."""
    orders = {order.client_id: order.status for order in snapshot.orders}
    algos = {algo.client_algo_id: algo.status for algo in snapshot.algos}
    updates: list[tuple[str, str]] = []
    for intent in intents:
        if intent.phase in _TERMINAL:
            continue
        if intent.phase not in {"planned", "sent", "unknown", "acked", "partial"}:
            continue
        status = orders.get(intent.client_id, algos.get(intent.client_id))
        if status is None:
            if intent.phase in {"sent", "unknown", "acked", "partial"}:
                updates.append((intent.client_id, "unknown"))
            continue
        mapped = {
            "NEW": "acked",
            "PARTIALLY_FILLED": "partial",
            "FILLED": "filled",
            "CANCELED": "canceled",
            "CANCELLED": "canceled",
            "REJECTED": "rejected",
            "EXPIRED": "expired",
            "TRIGGERED": "acked",
            "FINISHED": "filled",
        }.get(status, "unknown")
        updates.append((intent.client_id, mapped))
    return updates


def has_inflight(intents: list[Intent]) -> bool:
    return any(item.phase in {"planned", "sent", "unknown", "partial"} for item in intents)


def sibling_cancels(snapshot: Snapshot) -> list[Command]:
    """After one protection finishes, cancel the other live one. Flat cancels both."""
    finished = [algo for algo in snapshot.algos if algo.status == "FINISHED"]
    live = [algo for algo in snapshot.algos if algo.status in _ALGO_LIVE]
    commands: list[Command] = []
    if abs(snapshot.position_qty) < 1e-8:
        for algo in live:
            commands.append(Command("cancel_algo", algo.client_algo_id))
        return commands
    if finished:
        for algo in live:
            commands.append(Command("cancel_algo", algo.client_algo_id))
    return commands


def freeze_for_manual(book: Book, snapshot: Snapshot, intents: list[Intent]) -> str:
    if not snapshot.known:
        return "账户快照未知"
    inflight = [item for item in intents if item.phase in {"planned", "sent", "unknown", "acked", "partial"}]
    if inflight:
        return ""
    snap_side = snapshot.position_side
    if snap_side != book.side or abs(abs(snapshot.position_qty) - book.qty) > 1e-6:
        if book.manual:
            return ""
        return "实仓和策略记忆不一致，已冻结，等待 takeover"
    return ""


def _price_matches(live: float, wanted: float) -> bool:
    if wanted <= 0:
        return False
    return abs(live - wanted) / wanted <= 1e-6


def plan_protection(
    snapshot: Snapshot,
    swaps: dict[str, str],
    *,
    stop_price: float,
    take_price: float,
) -> tuple[list[Command], dict[str, str]]:
    """Place a new stop id when the live trigger no longer matches.

    The returned swaps remember ``stop_next`` / ``take_next``. The old id stays
    in ``stop_id`` / ``take_id`` until ``promote_protection`` sees the new one live.
    """
    updates = dict(swaps)
    if abs(snapshot.position_qty) < 1e-8 or stop_price <= 0 or take_price <= 0:
        return [], updates
    closing = "SELL" if snapshot.position_qty > 0 else "BUY"
    commands: list[Command] = []
    for kind, order_type, price in (
        ("stop", "STOP_MARKET", stop_price),
        ("take", "TAKE_PROFIT_MARKET", take_price),
    ):
        live = [algo for algo in _live_algos(snapshot, order_type) if _price_matches(algo.trigger_price, price)]
        if live:
            updates[f"{kind}_id"] = live[0].client_algo_id
            updates.pop(f"{kind}_next", None)
            continue
        nxt = updates.get(f"{kind}_next") or new_client_id("stop" if kind == "stop" else "take")
        updates[f"{kind}_next"] = nxt
        already = any(algo.client_algo_id == nxt and algo.status in _ALGO_LIVE for algo in snapshot.algos)
        if not already:
            commands.append(
                Command(
                    "place_algo",
                    nxt,
                    side=closing,
                    close_position=True,
                    trigger_price=f"{price:.8f}",
                    order_type=order_type,
                )
            )
    return commands, updates


def promote_protection(snapshot: Snapshot, swaps: dict[str, str]) -> tuple[list[Command], dict[str, str]]:
    """Cancel the old id only after the replacement is live, then drop the old id."""
    updates = dict(swaps)
    commands: list[Command] = []
    live = {algo.client_algo_id for algo in snapshot.algos if algo.status in _ALGO_LIVE}
    for kind in ("stop", "take"):
        new_id = updates.get(f"{kind}_next", "")
        old_id = updates.get(f"{kind}_id", "")
        if new_id and new_id in live and old_id and old_id in live and new_id != old_id:
            commands.append(Command("cancel_algo", old_id))
        if new_id and new_id in live and old_id not in live:
            updates[f"{kind}_id"] = new_id
            updates.pop(f"{kind}_next", None)
    return commands, updates


def apply_takeover(book: Book, snapshot: Snapshot) -> Book:
    book.manual = True
    book.side = snapshot.position_side
    book.qty = abs(snapshot.position_qty)
    book.entry = snapshot.entry_price
    book.units = 1 if book.qty else 0
    book.extreme = snapshot.entry_price
    book.last_add = snapshot.entry_price
    book.entries_frozen = True
    book.freeze_reason = "已接管实仓，仍不自动加仓"
    book.alerts.append("takeover")
    return book
