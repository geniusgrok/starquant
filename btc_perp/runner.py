"""One forward cycle. The exchange snapshot is the position.

A market order is written as ``sent`` before the transport call. A timeout
queries that same client id. Demo and production share this loop and differ
by host, keys, state directory, and the production gate.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from btc_perp.bars import BarStatus, MinuteBar, inspect_bars
from btc_perp.binance_client import AlgoEndpointRequired, UnknownExecution, account_problems
from btc_perp.config import AccountConfig
from btc_perp.gates import entry_block_reason, reducing_block_reason
from btc_perp.machine import (
    apply_takeover,
    foreign_ids,
    freeze_for_manual,
    new_client_id,
    plan_protection,
    promote_protection,
    protections_cover,
    quantize_down,
    sibling_cancels,
)
from btc_perp.model import Action, Book, Command, Intent, Limits, Snapshot
from btc_perp.policy import _qty, decide, disaster_take, initial_stop
from btc_perp.store import Store

DRIFT_MS = 2_000
NAKED_DEFAULT_SECONDS = 120


class Venue(Protocol):
    def snapshot(self) -> Snapshot:
        """REST account snapshot."""

    def place_market(self, *, client_id: str, side: str, qty: str, reduce_only: bool) -> dict[str, object]:
        """Send one market order."""

    def place_algo(
        self,
        *,
        client_id: str,
        side: str,
        order_type: str,
        trigger_price: str,
        close_position: bool,
        qty: str = "",
        reduce_only: bool = False,
    ) -> dict[str, object]:
        """Send one conditional order."""

    def cancel_order(self, client_id: str) -> dict[str, object]:
        """Cancel one plain order."""

    def cancel_algo(self, client_id: str) -> dict[str, object]:
        """Cancel one algo order."""

    def query_order(self, client_id: str) -> dict[str, object]:
        """Read one plain order by its original client id."""

    def query_algo(self, client_id: str) -> dict[str, object]:
        """Read one algo order by its original client id."""


@dataclass(frozen=True)
class CycleReport:
    mode: str
    frozen: bool
    reason: str
    sent: tuple[str, ...]
    position_qty: float
    covered: bool
    alerts: tuple[str, ...]
    dry_run: bool = False
    would_send: tuple[str, ...] = ()


def readiness(snapshot: Snapshot) -> str:
    filters = snapshot.filters
    filters_ok = filters is not None and filters.step_size > 0 and filters.tick_size > 0
    base = account_problems(snapshot, filters_ok)
    if base:
        return base
    if snapshot.fee_taker is None:
        return "手续费未知"
    if not snapshot.brackets_ok:
        return "杠杆档位读不到"
    if not snapshot.recent_trades_ok:
        return "近期成交读不到"
    if not snapshot.funding_ok:
        return "资金费读不到"
    if snapshot.mark_price <= 0 or snapshot.last_price <= 0:
        return "标记价或最新价未知"
    return ""


def interpret_body(body: dict[str, object]) -> str:
    code = body.get("code")
    if code not in (None, 0):
        try:
            number = int(str(code))
        except ValueError:
            return "unknown"
        msg = str(body.get("msg", "")).lower()
        if number in {-1007, -1001, -1008, -1021}:
            return "unknown"
        if number in {-2013, -2011}:
            return "missing"
        if "duplicat" in msg or "already exist" in msg:
            return "unknown"
        return "rejected"
    status = str(body.get("status") or body.get("algoStatus") or "")
    return {
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


def run_cycle(
    store: Store,
    venue: Venue,
    *,
    environment: str,
    limits: Limits,
    max_notional: float | None,
    cfg: AccountConfig,
    now_ms: int,
    bars: tuple[MinuteBar, ...],
    channels: tuple[float, float, float, float, int] | None,
    fx: float | None,
    mode: str,
    prod_enabled: bool,
    dry_run: bool = False,
    stream_expired: bool = False,
    hour_rows: tuple[tuple[int, float, float], ...] | None = None,
) -> CycleReport:
    book = store.load_book()
    sent: list[str] = []
    would: list[str] = []
    alerts: list[str] = []
    if mode == "run" and (store.directory / "stop.request").exists():
        mode = "stop"
    if mode == "run" and (store.directory / "flatten.request").exists():
        mode = "flatten"
    if stream_expired:
        alerts.append("用户流过期或断开，本轮只采用 REST 快照")
        store.append_event("stream", "rest-snapshot")

    snap = venue.snapshot()
    if not snap.known:
        book.entries_frozen = True
        book.freeze_reason = snap.reason or "账户未知"
        book.alerts.append(book.freeze_reason)
        _save(store, book, dry_run)
        store.append_event("freeze", book.freeze_reason)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would)

    _reconcile(store, venue, book, sent, alerts, dry_run)
    if sent and not dry_run:
        snap = venue.snapshot()
        if not snap.known:
            book.entries_frozen = True
            book.freeze_reason = snap.reason or "账户未知"
            _save(store, book, dry_run)
            return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would)
    intents = store.intents()
    fx_used = fx if fx is not None and fx > 0 else 1.0
    if fx is None:
        alerts.append("未提供汇率，峰值按 USDT 记")

    drift = snap.server_time_ms <= 0 or abs(now_ms - snap.server_time_ms) > DRIFT_MS
    problem = readiness(snap)
    foreign = foreign_ids(snap, _known_ids(store, book))
    mismatch = freeze_for_manual(book, snap, intents)
    if mode == "takeover":
        apply_takeover(book, snap)
        alerts.append("已接管实仓，仍不自动加仓")
        mismatch = ""
    if mismatch:
        book.entries_frozen = True
        book.freeze_reason = mismatch
        alerts.append(mismatch)
    else:
        if drift:
            book.entries_frozen = True
            book.freeze_reason = "时间漂移或交易所时间未知"
        elif problem:
            book.entries_frozen = True
            book.freeze_reason = problem
        elif foreign:
            book.entries_frozen = True
            book.freeze_reason = "存在未知外来订单：" + ",".join(foreign[:5])
        elif book.manual:
            book.entries_frozen = True
            book.freeze_reason = "已接管实仓，仍不自动加仓"
        else:
            book.entries_frozen = False
            book.freeze_reason = ""
        _absorb(book, snap, cfg)
        if book.freeze_reason:
            alerts.append(book.freeze_reason)

    if mode == "check":
        covered, why = protections_cover(snap)
        if why:
            alerts.append(why)
        _save(store, book, dry_run)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)

    if mode == "stop":
        _safe_stop(store, venue, snap, book, sent, would, alerts, dry_run)
        snap = venue.snapshot() if not dry_run else snap
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)

    if mode == "flatten":
        book.entries_frozen = True
        book.freeze_reason = "只减仓停机"
        _flatten(store, venue, snap, book, environment, prod_enabled, sent, would, alerts, dry_run, now_ms)
        snap = venue.snapshot() if not dry_run else snap
        if not book.manual and snap.known:
            _absorb(book, snap, cfg)
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)

    loss = _loss_block(book, snap, limits, now_ms)
    if loss:
        book.entries_frozen = True
        book.freeze_reason = loss
        alerts.append(loss)
    if _liquidation_close(snap):
        book.entries_frozen = True
        book.freeze_reason = "强平距离过近"
        alerts.append(book.freeze_reason)

    status = inspect_bars(bars, now_ms, book.cursor_ms)
    action_note = ""
    if not status.fresh:
        book.entries_frozen = True
        book.freeze_reason = status.reason
        alerts.append(status.reason)
    else:
        action_note = _walk_bars(
            book,
            snap,
            status,
            channels,
            hour_rows,
            cfg,
            fx_used,
            max_notional,
            now_ms,
            store,
            venue,
            environment,
            limits,
            prod_enabled,
            sent,
            would,
            alerts,
            dry_run,
        )
    if action_note:
        alerts.append(action_note)

    if not dry_run:
        snap = venue.snapshot()
        if snap.known:
            _siblings(store, venue, snap, sent, alerts)
            snap = venue.snapshot()
        if snap.known and not book.manual and freeze_for_manual(book, snap, store.intents()) == "":
            before = book.qty
            _absorb(book, snap, cfg)
            if (
                before > 1e-8
                and book.qty < 1e-8
                and not any(item.action in {"reduce", "flatten"} and item.client_id in sent for item in store.intents())
            ):
                book.cooldown_until_ms = now_ms + cfg.cooldown_hours * 3_600_000
        _maybe_open_after_flat(
            store, venue, snap, book, cfg, environment, limits, max_notional, prod_enabled, sent, alerts, now_ms
        )
        snap = venue.snapshot()
        if snap.known and not book.manual and freeze_for_manual(book, snap, store.intents()) == "":
            _absorb(book, snap, cfg)
        if snap.known:
            _protect(store, venue, snap, book, cfg, sent, alerts)
            snap = venue.snapshot()
            _naked(store, venue, snap, book, limits, environment, prod_enabled, now_ms, sent, alerts)
            snap = venue.snapshot()
    else:
        _describe_protection(snap, book, cfg, would)

    if not snap.known:
        book.entries_frozen = True
        book.freeze_reason = snap.reason or "账户未知"
    _save(store, book, dry_run)
    covered, why = protections_cover(snap) if snap.known else (False, snap.reason)
    if why and abs(snap.position_qty) >= 1e-8:
        alerts.append(why)
    return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)


def _finish(
    store: Store,
    now_ms: int,
    mode: str,
    book: Book,
    snap: Snapshot,
    sent: list[str],
    alerts: list[str],
    dry_run: bool,
    would: list[str],
    covered: bool | None = None,
) -> CycleReport:
    report = _report(mode, book, snap, sent, alerts, dry_run, would, covered)
    store.append_journal(
        {
            "ts_ms": now_ms,
            "kind": "cycle",
            "mode": report.mode,
            "dry_run": dry_run,
            "frozen": report.frozen,
            "reason": report.reason,
            "position_qty": snap.position_qty if snap.known else None,
            "entry": snap.entry_price if snap.known else None,
            "wallet_usdt": snap.wallet_usdt if snap.known else None,
            "available_usdt": snap.available_usdt if snap.known else None,
            "mark": snap.mark_price if snap.known else None,
            "last": snap.last_price if snap.known else None,
            "fee_taker": snap.fee_taker,
            "funding_ok": snap.funding_ok,
            "covered": report.covered,
            "cursor_ms": book.cursor_ms,
            "server_time_ms": snap.server_time_ms,
            "sent": list(sent),
            "would": list(would),
            "alerts": alerts[-8:],
            "orders": [
                {"id": item.client_id, "type": item.order_type, "status": item.status, "reduce_only": item.reduce_only}
                for item in snap.orders
            ],
            "algos": [
                {
                    "id": item.client_algo_id,
                    "type": item.order_type,
                    "status": item.status,
                    "trigger": item.trigger_price,
                    "working": item.working_type,
                }
                for item in snap.algos
            ],
        }
    )
    return report


def _report(
    mode: str,
    book: Book,
    snap: Snapshot,
    sent: list[str],
    alerts: list[str],
    dry_run: bool,
    would: list[str],
    covered: bool | None = None,
) -> CycleReport:
    if covered is None:
        covered = protections_cover(snap)[0] if snap.known else False
    return CycleReport(
        mode=mode,
        frozen=book.entries_frozen,
        reason=book.freeze_reason,
        sent=tuple(sent),
        position_qty=snap.position_qty if snap.known else 0.0,
        covered=covered,
        alerts=tuple(alerts),
        dry_run=dry_run,
        would_send=tuple(would),
    )


def _known_ids(store: Store, book: Book) -> set[str]:
    found = {item.client_id for item in store.intents()}
    for key, value in book.swaps.items():
        if key.endswith("_id") or key.endswith("_next"):
            found.add(value)
    return found


def _absorb(book: Book, snap: Snapshot, cfg: AccountConfig) -> None:
    if not snap.known:
        return
    previous = book.qty
    book.side = snap.position_side
    book.qty = abs(snap.position_qty)
    if book.qty < 1e-8:
        book.entry = 0.0
        book.units = 0
        book.extreme = 0.0
        book.stop = 0.0
        book.last_add = 0.0
        return
    book.entry = snap.entry_price
    if previous < 1e-8:
        book.units = max(book.units, 1)
        book.extreme = snap.entry_price
        book.last_add = snap.entry_price
        if book.stop <= 0:
            book.stop = initial_stop(book.side, snap.entry_price, cfg.stop, snap.liquidation_price, snap.mark_price)
    elif book.qty > previous + 1e-6:
        book.units += 1
        book.last_add = snap.entry_price


def _reconcile(
    store: Store,
    venue: Venue,
    book: Book,
    sent: list[str],
    alerts: list[str],
    dry_run: bool,
) -> None:
    if dry_run:
        return
    for intent in list(store.open_intents()):
        if intent.phase == "planned":
            _transmit(store, venue, intent, sent, alerts)
            continue
        if intent.phase not in {"sent", "unknown"}:
            continue
        try:
            body = venue.query_algo(intent.client_id) if _is_algo(intent) else venue.query_order(intent.client_id)
        except UnknownExecution:
            store.mark_intent(intent.client_id, "unknown", "query-timeout")
            alerts.append("查询原订单超时")
            continue
        phase = interpret_body(body)
        if phase == "missing":
            if "retried" in intent.note:
                store.mark_intent(intent.client_id, "unknown", "still-missing")
                alerts.append("原订单仍查不到，不会换一个新身份重发")
                continue
            store.mark_intent(intent.client_id, "sent", "retried")
            refreshed = _reload(store, intent.client_id)
            if refreshed is not None:
                _transmit(store, venue, refreshed, sent, alerts)
            continue
        store.mark_intent(intent.client_id, phase, intent.note)
        _ = book


def _walk_bars(
    book: Book,
    snap: Snapshot,
    status: BarStatus,
    channels: tuple[float, float, float, float, int] | None,
    hour_rows: tuple[tuple[int, float, float], ...] | None,
    cfg: AccountConfig,
    fx: float,
    max_notional: float | None,
    now_ms: int,
    store: Store,
    venue: Venue,
    environment: str,
    limits: Limits,
    prod_enabled: bool,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
) -> str:
    table = _channel_table(hour_rows, cfg.entry_hours, cfg.exit_hours) if hour_rows else {}
    for bar in status.new_bars:
        hh, ll, xh, xl = _levels_for_bar(bar, channels, table)
        favorable, adverse = _marks(book, bar)
        close_usd = _equity_usd(snap, book, bar.close)
        fav_cny = _equity_usd(snap, book, favorable) * fx
        if fav_cny > book.peak_equity_cny:
            book.peak_equity_cny = fav_cny
        if close_usd * fx > book.close_peak_cny:
            book.close_peak_cny = close_usd * fx
        gate = (bar.open_ms // 60_000) % 60 == 59
        action = decide(
            book,
            close=bar.close,
            high=bar.high,
            low=bar.low,
            hh=hh,
            ll=ll,
            xh=xh,
            xl=xl,
            equity_cny=close_usd * fx,
            equity_usd=close_usd,
            now_ms=now_ms,
            cfg=cfg,
            hard_notional=max_notional or 0.0,
            gate_open=gate,
            adverse_cny=_equity_usd(snap, book, adverse) * fx,
        )
        if action.stop > 0 and book.side != 0:
            book.stop = action.stop
        book.cursor_ms = bar.open_ms
        if action.kind in {"hold", "update_stop"}:
            continue
        return _act(
            action,
            store,
            venue,
            snap,
            book,
            cfg,
            environment,
            limits,
            max_notional,
            prod_enabled,
            sent,
            would,
            alerts,
            dry_run,
            now_ms,
            bar.open_ms,
        )
    return ""


def _levels_for_bar(
    bar: MinuteBar,
    channels: tuple[float, float, float, float, int] | None,
    table: dict[int, tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """Levels known at this minute's close. A later hour is not visible yet."""
    blank = (float("inf"), float("-inf"), float("inf"), float("-inf"))
    close_ms = bar.open_ms + 60_000
    if table:
        known = [stamp for stamp in table if stamp <= close_ms]
        if not known:
            return blank
        return table[max(known)]
    if channels is None:
        return blank
    hh, ll, xh, xl, hour_open = channels
    if hour_open + 3_600_000 > close_ms:
        return blank
    return hh, ll, xh, xl


def _channel_table(
    rows: tuple[tuple[int, float, float], ...],
    entry_hours: int,
    exit_hours: int,
) -> dict[int, tuple[float, float, float, float]]:
    import numpy as np

    from scripts.frontier import rolling_max, rolling_min

    ordered = tuple(sorted(rows))
    if not ordered:
        return {}
    high = np.array([item[1] for item in ordered], dtype=np.float64)
    low = np.array([item[2] for item in ordered], dtype=np.float64)
    hh = np.full(len(ordered), np.inf)
    ll = np.full(len(ordered), -np.inf)
    xh = np.full(len(ordered), np.inf)
    xl = np.full(len(ordered), -np.inf)
    if len(ordered) >= entry_hours:
        hh = rolling_max(high, entry_hours)
        ll = rolling_min(low, entry_hours)
    if len(ordered) >= exit_hours:
        xh = rolling_max(high, exit_hours)
        xl = rolling_min(low, exit_hours)
    return {
        ordered[i][0] + 3_600_000: (float(hh[i]), float(ll[i]), float(xh[i]), float(xl[i])) for i in range(len(ordered))
    }


def _save(store: Store, book: Book, dry_run: bool) -> None:
    if not dry_run:
        store.save_book(book)


def _act(
    action: Action,
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    cfg: AccountConfig,
    environment: str,
    limits: Limits,
    max_notional: float | None,
    prod_enabled: bool,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
    now_ms: int,
    bar_open_ms: int,
) -> str:
    if action.kind in {"enter", "add"}:
        if book.entries_frozen or book.manual:
            return "增仓已冻结：" + book.freeze_reason
        blocked = entry_block_reason(environment, limits, max_notional, prod_enabled=prod_enabled)
        if blocked:
            return blocked
        if _blocking_entry(store):
            return "已有未完成订单，不会再发一张增仓单"
        price = snap.mark_price or snap.last_price
        qty = _fit_qty(action.qty, snap, price, False, max_notional or 0.0)
        if qty is None:
            return "数量不满足交易所过滤器或名义上限"
        side = "BUY" if action.side > 0 else "SELL"
        _queue_market(
            store, venue, environment, action.kind, side, qty, False, "", sent, would, alerts, dry_run, now_ms
        )
        return action.reason
    if action.kind in {"exit", "reverse"}:
        blocked = reducing_block_reason(environment, prod_enabled=prod_enabled)
        if blocked:
            return blocked
        if _blocking_reduce(store):
            return "已有未完成订单，先等这张平仓单结束"
        if action.kind == "reverse":
            book.swaps["after_flat"] = "BUY" if action.side > 0 else "SELL"
            book.swaps["after_flat_ms"] = str(bar_open_ms)
            book.swaps["after_scale"] = str(action.scale)
        price = snap.mark_price or snap.last_price
        qty = _fit_qty(abs(snap.position_qty), snap, price, True, max_notional or 0.0)
        if qty is None:
            return "实仓数量无法量化"
        side = "SELL" if snap.position_qty > 0 else "BUY"
        _queue_market(store, venue, environment, "reduce", side, qty, True, "", sent, would, alerts, dry_run, now_ms)
        return action.reason
    _ = cfg
    return ""


def _maybe_open_after_flat(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    cfg: AccountConfig,
    environment: str,
    limits: Limits,
    max_notional: float | None,
    prod_enabled: bool,
    sent: list[str],
    alerts: list[str],
    now_ms: int,
) -> None:
    side = book.swaps.get("after_flat", "")
    if not side or not snap.known or abs(snap.position_qty) >= 1e-8:
        return
    if any(order.status in {"NEW", "PARTIALLY_FILLED"} for order in snap.orders):
        return
    if any(algo.status == "NEW" for algo in snap.algos):
        alerts.append("平仓后仍有条件单，先清理再开新方向")
        return
    stamped = int(book.swaps.get("after_flat_ms", "0") or "0")
    if stamped and book.cursor_ms - stamped > 60_000:
        book.swaps.pop("after_flat", None)
        book.swaps.pop("after_flat_ms", None)
        book.swaps.pop("after_scale", None)
        alerts.append("反向开仓错过确认窗口")
        return
    if book.entries_frozen or book.manual:
        return
    blocked = entry_block_reason(environment, limits, max_notional, prod_enabled=prod_enabled)
    if blocked or _blocking_entry(store):
        alerts.append(blocked or "反向开仓还在等上一张单")
        return
    price = snap.mark_price or snap.last_price
    equity = snap.wallet_usdt
    raw = _qty(
        equity,
        price,
        cfg.stop,
        cfg.risk,
        float(book.swaps.get("after_scale", "1") or "1"),
        cfg.iso_frac,
        cfg.heat,
        cfg.trail,
        cfg.leverage,
        max_notional or 0.0,
    )
    qty = _fit_qty(raw, snap, price, False, max_notional or 0.0)
    if qty is None:
        alerts.append("反向开仓数量不满足过滤器")
        return
    _queue_market(store, venue, environment, "enter", side, qty, False, "", sent, [], alerts, False, now_ms)
    book.swaps.pop("after_flat", None)
    book.swaps.pop("after_flat_ms", None)
    book.swaps.pop("after_scale", None)


def _protect(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    cfg: AccountConfig,
    sent: list[str],
    alerts: list[str],
) -> None:
    if not snap.known or abs(snap.position_qty) < 1e-8:
        return
    side = snap.position_side
    entry = snap.entry_price
    if book.side == side and book.stop > 0:
        stop_source = book.stop
    else:
        stop_source = initial_stop(side, entry, cfg.stop, snap.liquidation_price, snap.mark_price)
        if book.side == side:
            book.stop = stop_source
    take = disaster_take(side, entry, cfg.take_profit_multiple)
    filters = snap.filters
    if filters is None:
        alerts.append("没有价格精度，不能挂保护")
        return
    stop_px = _tick(stop_source, filters.tick_size)
    take_px = _tick(take, filters.tick_size)
    if not _trigger_ok(side, "stop", stop_px, snap.last_price) or not _trigger_ok(
        side, "take", take_px, snap.last_price
    ):
        alerts.append("保护触发价落在现价的错误一侧")
        book.entries_frozen = True
        book.freeze_reason = "保护触发价无效"
        return
    commands, swaps = plan_protection(snap, book.swaps, stop_price=stop_px, take_price=take_px)
    book.swaps = swaps
    for command in commands:
        _queue_algo(store, venue, store.environment, command, sent, alerts)
    if commands:
        snap = venue.snapshot()
    cancels, swaps = promote_protection(snap, book.swaps)
    book.swaps = swaps
    for command in cancels:
        _cancel(store, venue, command, sent, alerts)


def _siblings(store: Store, venue: Venue, snap: Snapshot, sent: list[str], alerts: list[str]) -> None:
    if not snap.known:
        return
    for command in sibling_cancels(snap):
        _cancel(store, venue, command, sent, alerts)


def _naked(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    limits: Limits,
    environment: str,
    prod_enabled: bool,
    now_ms: int,
    sent: list[str],
    alerts: list[str],
) -> None:
    covered, _why = protections_cover(snap) if snap.known else (False, "")
    if not snap.known or abs(snap.position_qty) < 1e-8 or covered:
        book.unprotected_since_ms = None
        return
    if book.unprotected_since_ms is None:
        book.unprotected_since_ms = now_ms
    cap = limits.max_unprotected_seconds or NAKED_DEFAULT_SECONDS
    if now_ms - book.unprotected_since_ms < cap * 1000:
        return
    alerts.append("保护覆盖超时，改为只减仓")
    book.entries_frozen = True
    book.freeze_reason = "保护覆盖超时"
    _flatten(store, venue, snap, book, environment, prod_enabled, sent, [], alerts, False, now_ms)


def _safe_stop(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
) -> None:
    book.entries_frozen = True
    book.freeze_reason = "安全停机"
    for order in snap.orders:
        if order.status in {"NEW", "PARTIALLY_FILLED"} and not order.reduce_only:
            command = Command("cancel_order", order.client_id)
            if dry_run:
                would.append("cancel " + order.client_id)
            else:
                _cancel(store, venue, command, sent, alerts)
    if abs(snap.position_qty) < 1e-8:
        for algo in snap.algos:
            if algo.status == "NEW":
                command = Command("cancel_algo", algo.client_algo_id)
                if dry_run:
                    would.append("cancel " + algo.client_algo_id)
                else:
                    _cancel(store, venue, command, sent, alerts)
    else:
        alerts.append("停机保留已有实仓的保护单")


def _flatten(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    environment: str,
    prod_enabled: bool,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
    now_ms: int,
) -> None:
    if abs(snap.position_qty) < 1e-8:
        alerts.append("当前没有实仓")
        return
    blocked = reducing_block_reason(environment, prod_enabled=prod_enabled)
    if blocked:
        alerts.append(blocked)
        return
    if _blocking_reduce(store):
        alerts.append("已有未完成的平仓单")
        return
    price = snap.mark_price or snap.last_price
    qty = _fit_qty(abs(snap.position_qty), snap, price, True, 0.0)
    if qty is None:
        alerts.append("实仓数量无法量化")
        return
    side = "SELL" if snap.position_qty > 0 else "BUY"
    _queue_market(store, venue, environment, "flatten", side, qty, True, "", sent, would, alerts, dry_run, now_ms)
    _ = book


def _describe_protection(snap: Snapshot, book: Book, cfg: AccountConfig, would: list[str]) -> None:
    if abs(snap.position_qty) < 1e-8:
        return
    covered, _why = protections_cover(snap)
    if not covered:
        would.append(
            f"place stop {book.stop:.4f} take {disaster_take(book.side, book.entry, cfg.take_profit_multiple):.4f}"
        )


def _queue_market(
    store: Store,
    venue: Venue,
    environment: str,
    action: str,
    side: str,
    qty: str,
    reduce_only: bool,
    note: str,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
    now_ms: int,
) -> None:
    if dry_run:
        would.append(f"{action} {side} {qty} reduce={reduce_only}")
        return
    kind = action if action in {"enter", "add", "reduce", "flatten"} else "reduce"
    client_id = new_client_id(kind)
    intent = Intent(
        client_id=client_id,
        action=action,
        phase="planned",
        side=side,
        qty=qty,
        reduce_only=reduce_only,
        close_position=False,
        trigger_price="",
        environment=environment,
        created_ms=now_ms,
        note=note,
    )
    store.insert_intent(intent)
    store.mark_intent(client_id, "sent", "before-transport")
    intent.phase = "sent"
    _transmit(store, venue, intent, sent, alerts)


def _queue_algo(
    store: Store,
    venue: Venue,
    environment: str,
    command: Command,
    sent: list[str],
    alerts: list[str],
) -> None:
    if any(item.client_id == command.client_id for item in store.intents()):
        intent = _reload(store, command.client_id)
        if intent is None or intent.phase not in {"planned", "rejected", "expired"}:
            return
    else:
        intent = Intent(
            client_id=command.client_id,
            action="stop" if command.order_type == "STOP_MARKET" else "take",
            phase="planned",
            side=command.side,
            qty=command.qty,
            reduce_only=command.reduce_only,
            close_position=command.close_position,
            trigger_price=command.trigger_price,
            environment=environment,
            created_ms=0,
            note="",
        )
        store.insert_intent(intent)
    store.mark_intent(intent.client_id, "sent", "before-transport")
    intent.phase = "sent"
    intent.side = command.side
    intent.trigger_price = command.trigger_price
    intent.close_position = True
    _transmit(store, venue, intent, sent, alerts)


def _transmit(store: Store, venue: Venue, intent: Intent, sent: list[str], alerts: list[str]) -> None:
    started = time.perf_counter()
    try:
        if _is_algo(intent):
            body = venue.place_algo(
                client_id=intent.client_id,
                side=intent.side,
                order_type="STOP_MARKET" if intent.action == "stop" else "TAKE_PROFIT_MARKET",
                trigger_price=intent.trigger_price,
                close_position=True,
            )
        else:
            body = venue.place_market(
                client_id=intent.client_id,
                side=intent.side,
                qty=intent.qty,
                reduce_only=intent.reduce_only,
            )
    except UnknownExecution:
        store.mark_intent(intent.client_id, "unknown", "timeout")
        alerts.append("执行结果未知，保留原客户端身份 " + intent.client_id)
        _transmit_journal(store, intent, "unknown", started)
        return
    except AlgoEndpointRequired:
        store.mark_intent(intent.client_id, "rejected", "algo-endpoint")
        alerts.append("条件单被普通订单接口拒绝，不会改域名重试")
        _transmit_journal(store, intent, "rejected", started)
        return
    except (ValueError, RuntimeError) as exc:
        store.mark_intent(intent.client_id, "rejected", "error")
        alerts.append(str(exc)[:160])
        _transmit_journal(store, intent, "rejected", started)
        return
    phase = interpret_body(body)
    if phase == "missing":
        phase = "unknown"
    store.mark_intent(intent.client_id, phase, intent.note)
    sent.append(intent.client_id)
    _transmit_journal(store, intent, phase, started)
    if phase == "rejected":
        alerts.append("订单被拒绝 " + intent.client_id)


def _transmit_journal(store: Store, intent: Intent, phase: str, started: float) -> None:
    store.append_journal(
        {
            "ts_ms": int(time.time() * 1000),
            "kind": "transmit",
            "client_id": intent.client_id,
            "action": intent.action,
            "phase": phase,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    )


def _cancel(store: Store, venue: Venue, command: Command, sent: list[str], alerts: list[str]) -> None:
    try:
        if command.op == "cancel_algo":
            body = venue.cancel_algo(command.client_id)
        else:
            body = venue.cancel_order(command.client_id)
    except UnknownExecution:
        alerts.append("撤单结果未知 " + command.client_id)
        store.append_event("cancel-unknown", command.client_id)
        return
    phase = interpret_body(body)
    if any(item.client_id == command.client_id for item in store.intents()):
        store.mark_intent(
            command.client_id, "canceled" if phase in {"canceled", "filled", "missing"} else phase, "cancel"
        )
    sent.append(command.client_id)
    store.append_event("cancel", command.client_id)


def _blocking_entry(store: Store) -> bool:
    return any(
        item.phase in {"planned", "sent", "unknown", "partial"} and item.action in {"enter", "add", "reverse"}
        for item in store.intents()
    )


def _blocking_reduce(store: Store) -> bool:
    return any(
        item.phase in {"planned", "sent", "unknown"} and item.action in {"reduce", "flatten"}
        for item in store.intents()
    )


def _is_algo(intent: Intent) -> bool:
    return intent.action in {"stop", "take"} or intent.close_position


def _reload(store: Store, client_id: str) -> Intent | None:
    for item in store.intents():
        if item.client_id == client_id:
            return item
    return None


def _fit_qty(raw: float, snap: Snapshot, price: float, reduce_only: bool, max_notional: float) -> str | None:
    filters = snap.filters
    if filters is None or filters.step_size <= 0 or raw <= 0:
        return None
    qty_text = quantize_down(raw, filters.step_size)
    qty = float(qty_text)
    if qty < filters.min_qty:
        return None
    if reduce_only:
        return qty_text
    if price <= 0:
        return None
    if max_notional > 0 and abs(snap.position_qty) * price + qty * price > max_notional:
        room = (max_notional - abs(snap.position_qty) * price) / price
        if room <= 0:
            return None
        qty_text = quantize_down(room, filters.step_size)
        qty = float(qty_text)
    if qty < filters.min_qty or qty * price < filters.min_notional:
        return None
    if qty * price / 20.0 > snap.available_usdt:
        return None
    return qty_text


def _tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    units = (Decimal(str(price)) / Decimal(str(tick))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(units * Decimal(str(tick)))


def _trigger_ok(side: int, kind: str, price: float, last: float) -> bool:
    if last <= 0 or price <= 0:
        return False
    if kind == "stop":
        return price < last if side > 0 else price > last
    return price > last if side > 0 else price < last


def _equity_usd(snap: Snapshot, book: Book, price: float) -> float:
    if book.side == 0 or book.qty <= 0:
        return snap.wallet_usdt
    return snap.wallet_usdt + (price - book.entry) * book.qty * book.side


def _marks(book: Book, bar: MinuteBar) -> tuple[float, float]:
    if book.side > 0:
        return bar.high, bar.low
    if book.side < 0:
        return bar.low, bar.high
    return bar.close, bar.close


def _loss_block(book: Book, snap: Snapshot, limits: Limits, now_ms: int) -> str:
    if limits.max_daily_loss_usdt is None or limits.max_daily_loss_usdt <= 0:
        return ""
    day = dt.datetime.fromtimestamp(now_ms / 1000, dt.UTC).strftime("%Y-%m-%d")
    if book.day_key != day:
        book.day_key = day
        book.swaps["day_wallet"] = f"{snap.wallet_usdt:.8f}"
    start = float(book.swaps.get("day_wallet", snap.wallet_usdt))
    equity = snap.wallet_usdt
    if snap.mark_price > 0 and snap.entry_price > 0 and abs(snap.position_qty) > 0:
        equity = snap.wallet_usdt + (snap.mark_price - snap.entry_price) * snap.position_qty
    book.day_realized_usdt = equity - start
    if start - equity >= limits.max_daily_loss_usdt:
        return "已到单日损失上限"
    return ""


def _liquidation_close(snap: Snapshot) -> bool:
    if snap.mark_price <= 0 or snap.liquidation_price <= 0 or abs(snap.position_qty) < 1e-8:
        return False
    if snap.position_qty > 0:
        return (snap.mark_price - snap.liquidation_price) / snap.mark_price < 0.01
    return (snap.liquidation_price - snap.mark_price) / snap.mark_price < 0.01
