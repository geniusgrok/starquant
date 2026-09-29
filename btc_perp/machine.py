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
    """At least one live stop and one live take, all of the right shape.

    Several valid protections may coexist: that is safe, and cancelling a
    healthy one only to reach "exactly one" would open a gap.
    """
    if not snapshot.known:
        return False, "账户未知"
    if abs(snapshot.position_qty) < 1e-8:
        leftover = [algo.client_algo_id for algo in snapshot.algos if algo.status in _ALGO_LIVE]
        if leftover:
            return False, "空仓仍有活动条件单"
        return True, ""
    stops = _live_algos(snapshot, "STOP_MARKET")
    takes = _live_algos(snapshot, "TAKE_PROFIT_MARKET")
    if not stops or not takes:
        return False, "缺少活动的止损或止盈"
    closing_side = "SELL" if snapshot.position_qty > 0 else "BUY"
    for algo in (*stops, *takes):
        if algo.side != closing_side:
            return False, "保护单方向和持仓不一致"
        if algo.working_type != "CONTRACT_PRICE":
            return False, "保护单触发价源不是合约最新价"
        if algo.close_position:
            if algo.reduce_only or algo.qty:
                return False, "closePosition 保护单还带了数量或 reduceOnly"
        elif not algo.reduce_only or algo.qty + 1e-12 < abs(snapshot.position_qty):
            return False, "保护单数量盖不住实仓"
        if algo.trigger_price <= 0:
            return False, "保护单触发价无效"
    long = snapshot.position_qty > 0
    stop_px = max(algo.trigger_price for algo in stops) if long else min(algo.trigger_price for algo in stops)
    take_px = min(algo.trigger_price for algo in takes) if long else max(algo.trigger_price for algo in takes)
    if long and not stop_px < take_px:
        return False, "多仓止损不在止盈下方"
    if not long and not stop_px > take_px:
        return False, "空仓止损不在止盈上方"
    if long and snapshot.last_price > 0 and stop_px >= snapshot.last_price:
        return False, "多仓止损不在现价下方"
    if not long and snapshot.last_price > 0 and stop_px <= snapshot.last_price:
        return False, "空仓止损不在现价上方"
    liquidation = snapshot.liquidation_price
    if liquidation > 0:
        if long and stop_px <= liquidation:
            return False, "多仓止损不在强平价上方，可能先被强平"
        if not long and stop_px >= liquidation:
            return False, "空仓止损不在强平价下方，可能先被强平"
    return True, ""


def foreign_ids(snapshot: Snapshot, known: set[str], known_native: set[str] | None = None) -> list[str]:
    found: list[str] = []
    for order in snapshot.orders:
        if (
            order.status in _OPEN
            and order.client_id not in known
            and not (order.order_id and order.order_id in (known_native or ()))
        ):
            found.append(order.client_id or "order-without-id")
    for algo in snapshot.algos:
        if algo.status in _ALGO_LIVE and algo.client_algo_id not in known:
            found.append(algo.client_algo_id or "algo-without-id")
    return found


POSITION_ACTIONS = frozenset({"enter", "add", "reverse", "reduce", "flatten"})
OPEN_PHASES = frozenset({"planned", "sent", "unknown", "acked", "partial"})


def sibling_cancels(snapshot: Snapshot, known: set[str]) -> list[Command]:
    """Cancel our own leftover protection once the position is gone.

    A finished protection while a position remains is not proof that the
    position is closed: the remainder keeps the other protection. Ids that
    this program did not create are never cancelled here.
    """
    if not snapshot.known or abs(snapshot.position_qty) >= 1e-8:
        return []
    return [
        Command("cancel_algo", algo.client_algo_id)
        for algo in snapshot.algos
        if algo.status in _ALGO_LIVE and algo.client_algo_id in known
    ]


def triggered_with_position(snapshot: Snapshot) -> bool:
    """A protection has fired but the account still holds a position."""
    return abs(snapshot.position_qty) >= 1e-8 and any(
        algo.status in {"FINISHED", "TRIGGERED"} for algo in snapshot.algos
    )


def _signed(intent: Intent) -> float:
    try:
        qty = abs(float(intent.qty or 0.0))
    except ValueError:
        return 0.0
    return qty if intent.side == "BUY" else -qty if intent.side == "SELL" else 0.0


def position_bounds(
    book: Book, intents: list[Intent], live_algo_ids: frozenset[str] | set[str] = frozenset()
) -> tuple[float, float]:
    """How far our own unfinished or uncounted orders could have moved the position.

    A plain order can move it by up to its quantity in its own direction. A
    protection of ours that has fired, or whose state is not known, can close
    what the book holds. One that still rests on the exchange has not fired
    and explains nothing. Nothing else explains a change.
    """
    low = 0.0
    high = 0.0
    held = book.side * book.qty
    closable = False
    for item in intents:
        counted = item.phase in OPEN_PHASES or not item.absorbed
        if item.action in POSITION_ACTIONS and counted:
            move = _signed(item)
            if move > 0:
                high += move
            else:
                low += move
        elif item.action in {"stop", "take"} and counted and item.client_id not in live_algo_ids:
            # A confirmed child fill explains only its own quantity. An empty
            # quantity on a filled close-position order is a full close. Anything
            # else, including a parent that merely ended, explains nothing.
            amount = _executed_qty(item)
            if amount is not None and amount > 0:
                if item.side == "SELL":
                    low -= amount
                elif item.side == "BUY":
                    high += amount
            elif item.phase == "filled" and item.close_position and amount is None:
                closable = True
    if closable and held > 0:
        low -= held
    elif closable and held < 0:
        high -= held
    return low, high


def _executed_qty(intent: Intent) -> float | None:
    """Cumulative confirmed fill. ``None`` means the venue has not reported one."""
    raw = intent.executed
    if raw == "":
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    if number < 0 or number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def foreign_trades(
    snapshot: Snapshot, intents: list[Intent], own_orders: frozenset[str] | set[str], cursor: int
) -> list[int]:
    """Fills after the cursor whose native order id is not one of ours.

    Same side, a compatible time, or an old protection are not proof. ``intents``
    is unused on purpose: ownership is the stored order id and nothing else.
    """
    _ = intents
    found: list[int] = []
    for trade in snapshot.trades:
        if trade.trade_id <= cursor:
            continue
        if trade.order_id and trade.order_id in own_orders:
            continue
        found.append(trade.trade_id)
    return found


def freeze_for_manual(
    book: Book,
    snapshot: Snapshot,
    intents: list[Intent],
    own_orders: frozenset[str] | set[str] = frozenset(),
    trade_cursor: int = 0,
) -> str:
    """Empty when our own orders explain the position, otherwise the reason.

    Having an order in flight does not explain a different position: the
    change has to fit inside what that order and our protections could do,
    and fills that carry no order of ours are named.
    """
    if not snapshot.known:
        return "账户快照未知"
    if book.manual:
        return ""
    stray = foreign_trades(snapshot, intents, own_orders, trade_cursor)
    if stray:
        return f"存在不是本程序订单的成交（{len(stray)} 笔），已冻结，等待 takeover"
    delta = snapshot.position_qty - book.side * book.qty
    if abs(delta) <= 1e-6:
        return ""
    live = {algo.client_algo_id for algo in snapshot.algos if algo.status in _ALGO_LIVE}
    low, high = position_bounds(book, intents, live)
    if low - 1e-6 <= delta <= high + 1e-6:
        return ""
    return "实仓和策略记忆不一致，已冻结，等待 takeover"


def _price_matches(live: float, wanted: float) -> bool:
    if wanted <= 0:
        return False
    return abs(live - wanted) / wanted <= 1e-6


def shape_ok(algo: AlgoOrder, closing: str, position_qty: float) -> bool:
    if algo.side != closing or algo.working_type != "CONTRACT_PRICE" or algo.status not in _ALGO_LIVE:
        return False
    if algo.close_position:
        return not algo.reduce_only and algo.qty == 0.0
    return algo.reduce_only and algo.qty + 1e-12 >= abs(position_qty)


def plan_protection(
    snapshot: Snapshot,
    swaps: dict[str, str],
    *,
    stop_price: float,
    take_price: float,
    known: set[str] | None = None,
) -> tuple[list[Command], dict[str, str]]:
    """Place a new id when no live protection of the right shape sits at the wanted trigger.

    ``stop_next`` / ``take_next`` remember the replacement. ``promote_protection``
    cancels every older live protection of ours only after the replacement is live.
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
        live = [
            algo
            for algo in _live_algos(snapshot, order_type)
            if _price_matches(algo.trigger_price, price)
            and shape_ok(algo, closing, snapshot.position_qty)
            and (known is None or algo.client_algo_id in known)
        ]
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


def promote_protection(
    snapshot: Snapshot, swaps: dict[str, str], known: set[str]
) -> tuple[list[Command], dict[str, str]]:
    """Cancel our older live protection of the same type once the kept one is live.

    The kept id is recomputed from the snapshot every cycle, so a cancel that
    timed out is simply issued again, also after a restart.
    """
    updates = dict(swaps)
    commands: list[Command] = []
    for kind, order_type in (("stop", "STOP_MARKET"), ("take", "TAKE_PROFIT_MARKET")):
        live = _live_algos(snapshot, order_type)
        live_ids = {algo.client_algo_id for algo in live}
        new_id = updates.get(f"{kind}_next", "")
        if new_id and new_id in live_ids:
            updates[f"{kind}_id"] = new_id
            updates.pop(f"{kind}_next", None)
        keep = updates.get(f"{kind}_id", "")
        if not keep or keep not in live_ids:
            continue
        for algo in live:
            if algo.client_algo_id != keep and algo.client_algo_id in known:
                commands.append(Command("cancel_algo", algo.client_algo_id))
    return commands, updates


def apply_takeover(book: Book, snapshot: Snapshot, *, history_covered: bool = True) -> Book:
    book.manual = True
    book.side = snapshot.position_side
    book.qty = abs(snapshot.position_qty)
    book.entry = snapshot.entry_price
    book.units = 1 if book.qty else 0
    book.extreme = snapshot.entry_price
    book.last_add = snapshot.entry_price
    book.stop = 0.0
    for key in ("unit_from", "unit_counted", "pre_qty", "pre_entry"):
        book.swaps.pop(key, None)
    book.entries_frozen = True
    book.freeze_reason = "已接管实仓，仍不自动加仓"
    book.alerts.append("takeover")
    if history_covered and snapshot.trades:
        book.swaps["trade_cursor"] = str(max(trade.trade_id for trade in snapshot.trades))
    return book
