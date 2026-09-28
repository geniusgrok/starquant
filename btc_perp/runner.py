"""One forward cycle. The exchange snapshot is the position.

A market order is written as ``sent`` before the transport call. A timeout
queries that same client id. Demo and production share this loop and differ
by host, keys, state directory, and the production gate.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from btc_perp.bars import BarStatus, MinuteBar, inspect_bars
from btc_perp.binance_client import AlgoEndpointRequired, UnknownExecution, WriteRefused, account_problems
from btc_perp.config import AccountConfig
from btc_perp.gates import entry_block_reason, notional_cap, reducing_block_reason, risk_equity
from btc_perp.machine import (
    OPEN_PHASES,
    POSITION_ACTIONS,
    apply_takeover,
    foreign_ids,
    freeze_for_manual,
    new_client_id,
    plan_protection,
    promote_protection,
    protections_cover,
    quantize_down,
    sibling_cancels,
    triggered_with_position,
)
from btc_perp.model import Action, Book, Command, Intent, Limits, Snapshot
from btc_perp.policy import _qty, decide, disaster_take, initial_stop
from btc_perp.store import Store

DRIFT_MS = 2_000
MAX_RTT_MS = 5_000
NAKED_DEFAULT_SECONDS = 120
STALE_SIGNAL_MS = 90_000
PLANNED_MAX_AGE_MS = 120_000
MISSING_ENTRY_EXPIRE_MS = 600_000
_OPEN = tuple(sorted(OPEN_PHASES))
_ENTRY_ACTIONS = frozenset({"enter", "add"})
_RISK_DOWN_ACTIONS = frozenset({"reduce", "flatten", "stop", "take"})


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
    settled: bool = False
    locked: bool = False


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


def interpret_body(body: dict[str, object], *, cancel: bool = False) -> str:
    """Map one exchange answer onto an intent phase. Anything unrecognised is ``unknown``."""
    code = body.get("code")
    if code not in (None, 0, 200):
        try:
            number = int(str(code))
        except ValueError:
            return "unknown"
        msg = str(body.get("msg", "")).lower()
        if number in {-1007, -1006, -1001, -1008, -1021}:
            return "unknown"
        if number in {-2013, -2011}:
            return "missing"
        if "duplicat" in msg or "already exist" in msg:
            return "unknown"
        return "rejected"
    status = str(body.get("status") or body.get("algoStatus") or "")
    if not status and cancel and code in (0, 200):
        return "canceled"
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


def _drift(snap: Snapshot, now_ms: int) -> str:
    if snap.server_time_ms <= 0:
        return "交易所时间未知"
    if snap.clock_offset_ms is not None and snap.clock_rtt_ms is not None:
        if snap.clock_rtt_ms > MAX_RTT_MS:
            return "网络往返过慢，时间读数不可信"
        if abs(snap.clock_offset_ms) > DRIFT_MS:
            return "本机时钟和交易所相差超过 2 秒"
        return ""
    if abs(now_ms - snap.server_time_ms) > DRIFT_MS:
        return "时间漂移或交易所时间未知"
    return ""


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
    """One pass. ``check`` and ``takeover`` never write to the exchange."""
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
    cap = notional_cap(max_notional, limits)
    writes = not dry_run and mode in {"run", "stop", "flatten"}

    snap = venue.snapshot()
    marker = len(sent)
    if not snap.known:
        book.entries_frozen = True
        book.freeze_reason = snap.reason or "账户未知"
        book.alerts.append(book.freeze_reason)
        _save(store, book, dry_run)
        store.append_event("freeze", book.freeze_reason)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would)

    allow = "none"
    if writes:
        allow = "all" if mode == "run" else "reduce"
    _reconcile(store, venue, snap, book, sent, alerts, allow=allow, now_ms=now_ms, dry_run=dry_run)
    if sent:
        snap = venue.snapshot()
        marker = len(sent)
        if not snap.known:
            book.entries_frozen = True
            book.freeze_reason = snap.reason or "账户未知"
            _save(store, book, dry_run)
            return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would)

    def resnap() -> Snapshot:
        nonlocal snap, marker
        if not dry_run and len(sent) != marker:
            snap = venue.snapshot()
            marker = len(sent)
        return snap

    fx_used = fx if fx is not None and fx > 0 else 1.0
    if fx is None:
        alerts.append("未提供汇率，峰值按 USDT 记")
    peak_problem = _init_peaks(book, snap, fx, fx_used)

    drift = _drift(snap, now_ms)
    problem = readiness(snap)
    foreign = foreign_ids(snap, store.all_client_ids() | _swap_ids(book))
    mismatch = freeze_for_manual(book, snap, store.intents())
    if mode == "takeover":
        apply_takeover(book, snap)
        alerts.append("已接管实仓，仍不自动加仓；保护由下一轮 run 补齐")
        mismatch = ""
    if mismatch:
        book.entries_frozen = True
        book.freeze_reason = mismatch
        alerts.append(mismatch)
    else:
        if drift:
            book.entries_frozen = True
            book.freeze_reason = drift
        elif problem:
            book.entries_frozen = True
            book.freeze_reason = problem
        elif peak_problem:
            book.entries_frozen = True
            book.freeze_reason = peak_problem
        elif foreign:
            book.entries_frozen = True
            book.freeze_reason = "存在未知外来订单：" + ",".join(foreign[:5])
        elif book.manual:
            book.entries_frozen = True
            book.freeze_reason = "已接管实仓，仍不自动加仓"
        else:
            book.entries_frozen = False
            book.freeze_reason = ""
        _sync_book(store, book, snap, cfg, now_ms)
        if book.freeze_reason:
            alerts.append(book.freeze_reason)
    _track_naked(book, snap, now_ms)
    _update_lock(book, snap, cfg, fx_used, alerts)

    if mode == "rearm":
        done = _rearm(store, book, snap, fx_used, alerts, dry_run)
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered, done)

    if mode in {"check", "takeover"}:
        covered, why = protections_cover(snap)
        if why:
            alerts.append(why)
        _save(store, book, dry_run)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)

    owned = not mismatch or book.manual

    if mode == "stop":
        _safe_stop(store, venue, snap, book, sent, would, alerts, dry_run)
        if owned and not dry_run:
            resnap()
            _keep_protected(store, venue, snap, book, cfg, sent, alerts, now_ms)
        settled = _stop_settled(store, resnap()) if not dry_run else False
        snap = resnap()
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered, settled)

    if mode == "flatten":
        book.entries_frozen = True
        book.freeze_reason = "只减仓停机"
        _flatten(store, venue, snap, book, environment, prod_enabled, sent, would, alerts, dry_run, now_ms)
        resnap()
        _sync_book(store, book, snap, cfg, now_ms)
        settled = snap.known and abs(snap.position_qty) < 1e-8 and not dry_run
        if settled and writes:
            _clear_own_orders(store, venue, snap, sent, alerts)
            resnap()
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered, settled)

    loss = _loss_block(book, snap, limits, now_ms)
    if loss:
        book.entries_frozen = True
        book.freeze_reason = loss
        alerts.append(loss)
    if _liquidation_close(snap):
        book.entries_frozen = True
        book.freeze_reason = "强平距离过近"
        alerts.append(book.freeze_reason)

    if writes and owned:
        if _keep_protected(store, venue, snap, book, cfg, sent, alerts, now_ms):
            _flatten(store, venue, resnap(), book, environment, prod_enabled, sent, would, alerts, dry_run, now_ms)
            book.cooldown_until_ms = now_ms + cfg.cooldown_hours * 3_600_000
        resnap()

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
            cap,
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
        snap = resnap()
        if snap.known:
            _siblings(store, venue, snap, sent, alerts)
            if triggered_with_position(snap):
                alerts.append("有保护单已触发但仍有实仓，保留另一张保护，等待成交结算")
            snap = resnap()
        if snap.known and not book.manual:
            before = book.qty
            _sync_book(store, book, snap, cfg, now_ms)
            if (
                before > 1e-8
                and book.qty < 1e-8
                and not any(item.action in {"reduce", "flatten"} and item.client_id in sent for item in store.intents())
            ):
                book.cooldown_until_ms = now_ms + cfg.cooldown_hours * 3_600_000
        _maybe_open_after_flat(
            store, venue, snap, book, cfg, environment, limits, cap, max_notional, prod_enabled, sent, alerts, now_ms
        )
        snap = resnap()
        if snap.known:
            _sync_book(store, book, snap, cfg, now_ms)
            _track_naked(book, snap, now_ms)
            if owned:
                if _keep_protected(store, venue, snap, book, cfg, sent, alerts, now_ms):
                    _flatten(
                        store, venue, resnap(), book, environment, prod_enabled, sent, would, alerts, dry_run, now_ms
                    )
                snap = resnap()
                _naked(store, venue, snap, book, limits, environment, prod_enabled, now_ms, sent, alerts)
                snap = resnap()
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
    settled: bool = False,
) -> CycleReport:
    report = _report(mode, book, snap, sent, alerts, dry_run, would, covered, settled)
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
            "settled": settled,
            "dd_locked": book.dd_locked,
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
    settled: bool = False,
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
        settled=settled,
        locked=book.dd_locked,
    )


def _update_lock(book: Book, snap: Snapshot, cfg: AccountConfig, fx_used: float, alerts: list[str]) -> None:
    """Say out loud when the drawdown lock is on. It blocks new entries and adds."""
    equity = _equity_now(snap) * fx_used
    peak = book.close_peak_cny
    book.dd_locked = peak > 0 and equity / peak <= 1.0 - cfg.dd_flat
    if not book.dd_locked:
        return
    if abs(snap.position_qty) < 1e-8:
        alerts.append("回撤锁已触发：空仓不会自行回到线上，不会再开新仓；接受新的回撤基准后用 rearm 重置")
    else:
        alerts.append("回撤锁已触发：不开新仓、不加仓，仍按规则离场")


def _rearm(store: Store, book: Book, snap: Snapshot, fx_used: float, alerts: list[str], dry_run: bool) -> bool:
    """Move the drawdown baseline to today's equity. Only a flat, quiet account may do it."""
    if abs(snap.position_qty) >= 1e-8 or book.side != 0:
        alerts.append("有持仓，不重置回撤基准")
        return False
    if store.open_intents():
        alerts.append("还有未完成订单，不重置回撤基准")
        return False
    equity = _equity_now(snap) * fx_used
    if equity <= 0:
        alerts.append("账户权益不是正数，不重置回撤基准")
        return False
    old = (book.peak_equity_cny, book.close_peak_cny)
    if dry_run:
        alerts.append(f"会把峰值从 {old[1]:.2f} 重置为 {equity:.2f}（dry-run，没有写入）")
        return False
    book.peak_equity_cny = equity
    book.close_peak_cny = equity
    book.dd_locked = False
    store.append_event("rearm", f"peak {old[0]:.2f}/{old[1]:.2f} -> {equity:.2f}")
    alerts.append(f"回撤基准已重置为 {equity:.2f}；这不改变止损、保护和其他限额")
    return True


def _swap_ids(book: Book) -> set[str]:
    return {value for key, value in book.swaps.items() if key.endswith("_id") or key.endswith("_next")}


def _equity_now(snap: Snapshot) -> float:
    equity = snap.wallet_usdt
    if snap.mark_price > 0 and snap.entry_price > 0 and abs(snap.position_qty) > 0:
        equity += (snap.mark_price - snap.entry_price) * snap.position_qty
    return equity


def _init_peaks(book: Book, snap: Snapshot, fx: float | None, fx_used: float) -> str:
    """Peaks start from the account's own equity and keep one pricing unit.

    Nothing here compares a small live account with the 10,000 CNY research
    start. Switching between USDT and CNY re-expresses the peaks instead of
    resetting the loss history.
    """
    unit = "CNY" if fx is not None and fx > 0 else "USDT"
    equity = _equity_now(snap) * fx_used
    if equity <= 0:
        return "" if book.peak_equity_cny > 0 else "账户权益不是正数，无法建立峰值"
    if book.peak_equity_cny <= 0 or book.close_peak_cny <= 0:
        start = max(book.peak_equity_cny, book.close_peak_cny, equity)
        book.peak_equity_cny = start
        book.close_peak_cny = start
        book.swaps["peak_unit"] = unit
        if unit == "CNY":
            book.swaps["peak_fx"] = repr(fx_used)
        return ""
    previous = book.swaps.get("peak_unit", "")
    if previous and previous != unit:
        if unit == "CNY":
            scale = fx_used
        else:
            old_fx = float(book.swaps.get("peak_fx", "0") or "0")
            if old_fx <= 0:
                return "峰值原按人民币记，现在没有汇率，无法换算"
            scale = 1.0 / old_fx
        book.peak_equity_cny *= scale
        book.close_peak_cny *= scale
    book.swaps["peak_unit"] = unit
    if unit == "CNY":
        book.swaps["peak_fx"] = repr(fx_used)
    return ""


def _sync_book(store: Store, book: Book, snap: Snapshot, cfg: AccountConfig, now_ms: int) -> None:
    """Follow the exchange position only when our own orders explain it."""
    if not snap.known or book.manual:
        return
    intents = store.intents()
    if freeze_for_manual(book, snap, intents) != "":
        return
    _absorb(book, snap, cfg, now_ms)
    if not any(item.action in POSITION_ACTIONS and item.phase in OPEN_PHASES for item in intents):
        store.settle_absorbed()


def _absorb(book: Book, snap: Snapshot, cfg: AccountConfig, now_ms: int = 0) -> None:
    if not snap.known:
        return
    previous = book.qty
    previous_entry = book.entry
    book.side = snap.position_side
    book.qty = abs(snap.position_qty)
    if book.qty < 1e-8:
        book.entry = 0.0
        book.units = 0
        book.extreme = 0.0
        book.stop = 0.0
        book.last_add = 0.0
        for key in ("pos_since_ms", "unit_from", "unit_counted", "pre_qty", "pre_entry"):
            book.swaps.pop(key, None)
        return
    book.entry = snap.entry_price
    if previous < 1e-8:
        book.units = max(book.units, 1)
        book.extreme = snap.entry_price
        book.last_add = snap.entry_price
        book.swaps["pos_since_ms"] = str(now_ms)
        book.swaps["unit_counted"] = book.swaps.get("unit_from", "")
        if book.stop <= 0:
            book.stop = initial_stop(book.side, snap.entry_price, cfg.stop, snap.liquidation_price, snap.mark_price)
        return
    if book.qty > previous + 1e-6:
        marker = book.swaps.get("unit_from", "")
        if marker and marker != book.swaps.get("unit_counted", ""):
            book.units += 1
            book.swaps["unit_counted"] = marker
            book.swaps["pre_qty"] = repr(previous)
            book.swaps["pre_entry"] = repr(previous_entry)
        pre_qty = float(book.swaps.get("pre_qty", "0") or "0")
        pre_entry = float(book.swaps.get("pre_entry", "0") or "0")
        added = book.qty - pre_qty
        if marker and marker == book.swaps.get("unit_counted", "") and added > 1e-9 and pre_qty > 0:
            book.last_add = (snap.entry_price * book.qty - pre_entry * pre_qty) / added


def _track_naked(book: Book, snap: Snapshot, now_ms: int) -> None:
    """The clock starts when a bare position is first seen and only a covered or flat account stops it."""
    if not snap.known:
        return
    if abs(snap.position_qty) < 1e-8 or protections_cover(snap)[0]:
        book.unprotected_since_ms = None
    elif book.unprotected_since_ms is None:
        book.unprotected_since_ms = now_ms


def _may_send(action: str, allow: str) -> bool:
    if allow == "all":
        return True
    return allow == "reduce" and action in _RISK_DOWN_ACTIONS


def _reconcile(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    sent: list[str],
    alerts: list[str],
    *,
    allow: str,
    now_ms: int,
    dry_run: bool,
) -> None:
    """Settle stored intents against the exchange.

    ``allow`` says what may be sent: ``none`` (queries only), ``reduce``
    (protection and reduce-only orders), or ``all``. Risk-increasing orders are
    never sent a second time; an unanswered entry stays unknown.
    """
    if dry_run:
        return
    live_algos = {algo.client_algo_id for algo in snap.algos if algo.status == "NEW"}
    for intent in list(store.open_intents()):
        is_entry = intent.action in _ENTRY_ACTIONS
        if intent.phase == "planned":
            if not _may_send(intent.action, allow):
                if allow != "none":
                    store.mark_intent(intent.client_id, "canceled", "not-sent-in-this-mode")
                continue
            if is_entry and intent.created_ms and now_ms - intent.created_ms > PLANNED_MAX_AGE_MS:
                store.mark_intent(intent.client_id, "canceled", "stale-plan")
                continue
            _transmit(store, venue, intent, sent, alerts)
            continue
        if intent.phase == "acked" and _is_algo(intent) and intent.client_id in live_algos:
            continue
        try:
            body = venue.query_algo(intent.client_id) if _is_algo(intent) else venue.query_order(intent.client_id)
        except (UnknownExecution, WriteRefused, OSError, RuntimeError):
            store.mark_intent(intent.client_id, "unknown", "query-failed")
            alerts.append("查询原订单失败")
            continue
        phase = interpret_body(body)
        if phase != "missing":
            store.mark_intent(intent.client_id, phase, intent.note)
            continue
        if is_entry:
            store.mark_intent(intent.client_id, "unknown", "missing-not-resent")
            alerts.append("原入场单查不到，不会重发；十分钟内仓位不变才会放行")
            unchanged = abs(abs(snap.position_qty) - book.qty) < 1e-6
            if intent.created_ms and now_ms - intent.created_ms > MISSING_ENTRY_EXPIRE_MS and unchanged:
                store.mark_intent(intent.client_id, "expired", "missing-10min-flat-position")
                store.mark_absorbed(intent.client_id)
            continue
        if intent.attempts < 2 and _may_send(intent.action, allow):
            store.mark_intent(intent.client_id, "sent", "resend-same-id", attempts=intent.attempts + 1)
            refreshed = _reload(store, intent.client_id)
            if refreshed is not None:
                _transmit(store, venue, refreshed, sent, alerts)
            continue
        store.mark_intent(intent.client_id, "unknown", "still-missing")
        alerts.append("原订单仍查不到，不会换一个新身份重发")


def _walk_bars(
    book: Book,
    snap: Snapshot,
    status: BarStatus,
    channels: tuple[float, float, float, float, int] | None,
    hour_rows: tuple[tuple[int, float, float], ...] | None,
    cfg: AccountConfig,
    fx: float,
    cap: float | None,
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
    since = int(book.swaps.get("pos_since_ms", "0") or "0")
    for bar in status.new_bars:
        hh, ll, xh, xl = _levels_for_bar(bar, channels, table)
        held_then = book.side == 0 or since <= 0 or bar.open_ms + 60_000 > since
        if held_then and book.side > 0 and bar.high > book.extreme:
            book.extreme = bar.high
        elif held_then and book.side < 0 and (book.extreme == 0.0 or bar.low < book.extreme):
            book.extreme = bar.low
        favorable, adverse = _marks(book, bar)
        close_usd = _equity_usd(snap, book, bar.close, held_then)
        fav_cny = _equity_usd(snap, book, favorable, held_then) * fx
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
            equity_usd=risk_equity(close_usd, limits),
            now_ms=now_ms,
            cfg=cfg,
            hard_notional=cap or 0.0,
            gate_open=gate,
            adverse_cny=_equity_usd(snap, book, adverse, held_then) * fx,
        )
        if action.stop > 0 and book.side != 0:
            book.stop = action.stop
        book.cursor_ms = bar.open_ms
        if action.kind in {"hold", "update_stop"}:
            continue
        if now_ms - (bar.open_ms + 60_000) > STALE_SIGNAL_MS:
            # A backlog minute still updates memory. It does not open new risk at today's price.
            if action.kind in {"enter", "add"}:
                continue
            if action.kind == "reverse":
                action = Action("exit", action.side, action.qty, action.stop, action.disaster_take, action.reason)
        return _act(
            action,
            store,
            venue,
            snap,
            book,
            cfg,
            environment,
            limits,
            cap,
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
    """Levels from hours that had finished before this minute's hour began.

    The research tape reads the window that ends one hour before the current
    hour. A minute inside hour H therefore sees hours up to H-1 and never its
    own hour, so a close can exceed the level.
    """
    blank = (float("inf"), float("-inf"), float("inf"), float("-inf"))
    if table:
        known = [stamp for stamp in table if stamp <= bar.open_ms]
        if not known:
            return blank
        return table[max(known)]
    if channels is None:
        return blank
    hh, ll, xh, xl, hour_open = channels
    if hour_open + 3_600_000 > bar.open_ms:
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
        hh[: entry_hours - 1] = np.inf
        ll[: entry_hours - 1] = -np.inf
    if len(ordered) >= exit_hours:
        xh = rolling_max(high, exit_hours)
        xl = rolling_min(low, exit_hours)
        xh[: exit_hours - 1] = np.inf
        xl[: exit_hours - 1] = -np.inf
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
    cap: float | None,
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
        blocked = entry_block_reason(environment, limits, cap, prod_enabled=prod_enabled)
        if blocked:
            return blocked
        if _blocking_entry(store):
            return "已有未完成订单，不会再发一张增仓单"
        if abs(snap.position_qty) >= 1e-8 and not protections_cover(snap)[0]:
            return "现有仓位保护不完整，先补保护，不加仓"
        price = snap.mark_price or snap.last_price
        qty = _fit_qty(action.qty, snap, price, False, cap or 0.0)
        if qty is None:
            return "数量不满足交易所过滤器或名义上限"
        side = "BUY" if action.side > 0 else "SELL"
        _queue_market(
            store, venue, book, environment, action.kind, side, qty, False, sent, would, alerts, dry_run, now_ms
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
        qty = _fit_qty(abs(snap.position_qty), snap, price, True, 0.0)
        if qty is None:
            return "实仓数量无法量化"
        side = "SELL" if snap.position_qty > 0 else "BUY"
        _queue_market(store, venue, book, environment, "reduce", side, qty, True, sent, would, alerts, dry_run, now_ms)
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
    cap: float | None,
    cli_cap: float | None,
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
    blocked = entry_block_reason(environment, limits, cli_cap, prod_enabled=prod_enabled)
    if blocked or _blocking_entry(store):
        alerts.append(blocked or "反向开仓还在等上一张单")
        return
    price = snap.mark_price or snap.last_price
    raw = _qty(
        risk_equity(_equity_now(snap), limits),
        price,
        cfg.stop,
        cfg.risk,
        float(book.swaps.get("after_scale", "1") or "1"),
        cfg.iso_frac,
        cfg.heat,
        cfg.trail,
        cfg.leverage,
        cap or 0.0,
    )
    qty = _fit_qty(raw, snap, price, False, cap or 0.0)
    if qty is None:
        alerts.append("反向开仓数量不满足过滤器")
        return
    _queue_market(store, venue, book, environment, "enter", side, qty, False, sent, [], alerts, False, now_ms)
    book.swaps.pop("after_flat", None)
    book.swaps.pop("after_flat_ms", None)
    book.swaps.pop("after_scale", None)


def _keep_protected(
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    cfg: AccountConfig,
    sent: list[str],
    alerts: list[str],
    now_ms: int,
) -> bool:
    """Place or replace protection. ``True`` means the stop is already behind the last price."""
    if not snap.known or abs(snap.position_qty) < 1e-8:
        return False
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
        return False
    if snap.last_price <= 0:
        alerts.append("现价未知，本轮不改保护")
        return False
    stop_px = _tick(stop_source, filters.tick_size)
    take_px = _tick(take, filters.tick_size)
    stop_ok = _trigger_ok(side, "stop", stop_px, snap.last_price)
    take_ok = _trigger_ok(side, "take", take_px, snap.last_price)
    if not stop_ok and take_ok:
        alerts.append("止损价已被现价越过，改为只减仓退出")
        return True
    if not (stop_ok and take_ok) or not _in_band(filters.min_price, filters.max_price, stop_px, take_px):
        alerts.append("保护触发价落在现价的错误一侧或价格带外")
        book.entries_frozen = True
        book.freeze_reason = "保护触发价无效"
        return False
    for kind in ("stop", "take"):
        nxt = book.swaps.get(f"{kind}_next", "")
        item = _reload(store, nxt) if nxt else None
        live = any(algo.client_algo_id == nxt and algo.status == "NEW" for algo in snap.algos)
        if item is not None and item.phase in {"rejected", "expired", "canceled", "filled"} and not live:
            book.swaps.pop(f"{kind}_next", None)
    commands, swaps = plan_protection(snap, book.swaps, stop_price=stop_px, take_price=take_px)
    book.swaps = swaps
    for command in commands:
        _queue_algo(store, venue, store.environment, command, sent, alerts, now_ms)
    if commands:
        snap = venue.snapshot()
    cancels, swaps = promote_protection(snap, book.swaps, store.all_client_ids())
    book.swaps = swaps
    for command in cancels:
        _cancel(store, venue, command, sent, alerts)
    return False


def _in_band(low: float, high: float, *prices: float) -> bool:
    return all((low <= 0 or price >= low) and (high <= 0 or price <= high) for price in prices)


def _siblings(store: Store, venue: Venue, snap: Snapshot, sent: list[str], alerts: list[str]) -> None:
    if not snap.known:
        return
    for command in sibling_cancels(snap, store.all_client_ids()):
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
    if not snap.known or abs(snap.position_qty) < 1e-8 or book.unprotected_since_ms is None:
        return
    cap = limits.max_unprotected_seconds or NAKED_DEFAULT_SECONDS
    if now_ms - book.unprotected_since_ms < cap * 1000:
        return
    alerts.append("保护覆盖超时，改为只减仓")
    book.entries_frozen = True
    book.freeze_reason = "保护覆盖超时"
    _flatten(store, venue, snap, book, environment, prod_enabled, sent, [], alerts, False, now_ms)


def _clear_own_orders(store: Store, venue: Venue, snap: Snapshot, sent: list[str], alerts: list[str]) -> None:
    """Cancel the entry orders and leftover protection that this program created."""
    known = store.all_client_ids()
    for order in snap.orders:
        if order.status in {"NEW", "PARTIALLY_FILLED"} and not order.reduce_only and order.client_id in known:
            _cancel(store, venue, Command("cancel_order", order.client_id), sent, alerts)
        elif order.status in {"NEW", "PARTIALLY_FILLED"} and order.client_id not in known:
            alerts.append("外来订单没有被撤销：" + (order.client_id or "无编号"))


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
    known = store.all_client_ids()
    for order in snap.orders:
        if order.status not in {"NEW", "PARTIALLY_FILLED"} or order.reduce_only:
            continue
        if order.client_id not in known:
            alerts.append("外来订单没有被撤销：" + (order.client_id or "无编号"))
            continue
        if dry_run:
            would.append("cancel " + order.client_id)
        else:
            _cancel(store, venue, Command("cancel_order", order.client_id), sent, alerts)
    if abs(snap.position_qty) < 1e-8:
        for algo in snap.algos:
            if algo.status != "NEW":
                continue
            if algo.client_algo_id not in known:
                alerts.append("外来条件单没有被撤销：" + (algo.client_algo_id or "无编号"))
            elif dry_run:
                would.append("cancel " + algo.client_algo_id)
            else:
                _cancel(store, venue, Command("cancel_algo", algo.client_algo_id), sent, alerts)
    else:
        alerts.append("停机保留已有实仓的保护单")


def _stop_settled(store: Store, snap: Snapshot) -> bool:
    if not snap.known:
        return False
    known = store.all_client_ids()
    own_entry_orders = [
        order
        for order in snap.orders
        if order.status in {"NEW", "PARTIALLY_FILLED"} and not order.reduce_only and order.client_id in known
    ]
    open_entries = [
        item for item in store.open_intents() if item.action in _ENTRY_ACTIONS or item.action in {"reduce", "flatten"}
    ]
    if own_entry_orders or open_entries:
        return False
    covered, _why = protections_cover(snap)
    return covered


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
    if not snap.known:
        return
    if not dry_run:
        # An entry that fills after the flatten would reopen the risk just removed.
        _clear_own_orders(store, venue, snap, sent, alerts)
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
    if any(item.action in _ENTRY_ACTIONS and item.phase in OPEN_PHASES for item in store.intents()):
        alerts.append("还有未结清的入场意图，平仓后需要再核对仓位")
    price = snap.mark_price or snap.last_price
    qty = _fit_qty(abs(snap.position_qty), snap, price, True, 0.0)
    if qty is None:
        alerts.append("实仓数量无法量化")
        return
    side = "SELL" if snap.position_qty > 0 else "BUY"
    _queue_market(store, venue, book, environment, "flatten", side, qty, True, sent, would, alerts, dry_run, now_ms)


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
    book: Book,
    environment: str,
    action: str,
    side: str,
    qty: str,
    reduce_only: bool,
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
        note="",
        absorbed=False,
    )
    store.insert_intent(intent)
    if action in _ENTRY_ACTIONS:
        book.swaps["unit_from"] = client_id
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
    now_ms: int,
) -> None:
    existing = _reload(store, command.client_id)
    if existing is not None:
        # An id keeps the meaning it was created with. Only an unsent plan is sent.
        if existing.phase != "planned":
            return
        intent = existing
    else:
        intent = Intent(
            client_id=command.client_id,
            action="stop" if command.order_type == "STOP_MARKET" else "take",
            phase="planned",
            side=command.side,
            qty=command.qty,
            reduce_only=command.reduce_only,
            close_position=True,
            trigger_price=command.trigger_price,
            environment=environment,
            created_ms=now_ms,
            note="",
        )
        store.insert_intent(intent)
    store.mark_intent(intent.client_id, "sent", "before-transport")
    intent.phase = "sent"
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
    except WriteRefused as exc:
        store.mark_intent(intent.client_id, "rejected", "not-sent")
        store.mark_absorbed(intent.client_id)
        alerts.append(str(exc)[:160])
        _transmit_journal(store, intent, "not-sent", started)
        return
    except AlgoEndpointRequired:
        store.mark_intent(intent.client_id, "rejected", "algo-endpoint")
        store.mark_absorbed(intent.client_id)
        alerts.append("条件单被普通订单接口拒绝，不会改域名重试")
        _transmit_journal(store, intent, "rejected", started)
        return
    except (ValueError, RuntimeError) as exc:
        store.mark_intent(intent.client_id, "rejected", "error")
        store.mark_absorbed(intent.client_id)
        alerts.append(str(exc)[:160])
        _transmit_journal(store, intent, "rejected", started)
        return
    phase = interpret_body(body)
    if phase == "missing":
        phase = "unknown"
    store.mark_intent(intent.client_id, phase, intent.note)
    if phase == "rejected":
        store.mark_absorbed(intent.client_id)
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
    """Cancel one of our own orders. The answer is recorded as it came, never as a success it was not."""
    known = _reload(store, command.client_id)
    try:
        if command.op == "cancel_algo":
            body = venue.cancel_algo(command.client_id)
        else:
            body = venue.cancel_order(command.client_id)
    except UnknownExecution:
        alerts.append("撤单结果未知 " + command.client_id)
        store.append_event("cancel-unknown", command.client_id)
        if known is not None:
            store.mark_intent(command.client_id, "unknown", "cancel-unknown")
        return
    except WriteRefused as exc:
        alerts.append(str(exc)[:160])
        return
    phase = interpret_body(body, cancel=True)
    if known is not None:
        if phase == "missing":
            store.mark_intent(command.client_id, "expired", "cancel-target-missing")
        else:
            store.mark_intent(command.client_id, phase, "cancel")
    sent.append(command.client_id)
    store.append_event("cancel", command.client_id)


def _blocking_entry(store: Store) -> bool:
    return any(
        item.phase in OPEN_PHASES and item.action in {"enter", "add", "reverse"} for item in store.intents(_OPEN)
    )


def _blocking_reduce(store: Store) -> bool:
    return any(item.phase in OPEN_PHASES and item.action in {"reduce", "flatten"} for item in store.intents(_OPEN))


def _is_algo(intent: Intent) -> bool:
    return intent.action in {"stop", "take"} or intent.close_position


def _reload(store: Store, client_id: str) -> Intent | None:
    for item in store.intents():
        if item.client_id == client_id:
            return item
    return None


def _fit_qty(raw: float, snap: Snapshot, price: float, reduce_only: bool, cap: float) -> str | None:
    filters = snap.filters
    if filters is None or filters.step_size <= 0 or raw <= 0 or not math.isfinite(raw):
        return None
    if reduce_only:
        if filters.max_qty > 0 and raw > filters.max_qty:
            raw = filters.max_qty
        qty_text = quantize_down(raw, filters.step_size)
        return qty_text if float(qty_text) >= filters.min_qty else None
    if price <= 0 or not math.isfinite(price):
        return None
    if filters.max_qty > 0 and raw > filters.max_qty:
        raw = filters.max_qty
    qty_text = quantize_down(raw, filters.step_size)
    qty = float(qty_text)
    if cap > 0 and abs(snap.position_qty) * price + qty * price > cap:
        room = (cap - abs(snap.position_qty) * price) / price
        if room <= 0:
            return None
        qty_text = quantize_down(room, filters.step_size)
        qty = float(qty_text)
    if qty < filters.min_qty or qty * price < filters.min_notional:
        return None
    leverage = float(snap.leverage) if snap.leverage > 0 else 20.0
    fee = snap.fee_taker if snap.fee_taker is not None else 0.0005
    if qty * price * (1.0 / leverage + 2.0 * fee) > snap.available_usdt:
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


def _equity_usd(snap: Snapshot, book: Book, price: float, held: bool = True) -> float:
    if book.side == 0 or book.qty <= 0 or not held:
        return snap.wallet_usdt
    return snap.wallet_usdt + (price - book.entry) * book.qty * book.side


def _marks(book: Book, bar: MinuteBar) -> tuple[float, float]:
    if book.side > 0:
        return bar.high, bar.low
    if book.side < 0:
        return bar.low, bar.high
    return bar.close, bar.close


def _loss_block(book: Book, snap: Snapshot, limits: Limits, now_ms: int) -> str:
    """Freeze new risk once today's equity is down by the cap. It does not close positions.

    The day starts from wallet plus unrealised PnL at the first look of the UTC
    day. A deposit raises equity and cannot trip the cap; a withdrawal looks
    like a loss and can, which is the safe direction.
    """
    if limits.max_daily_loss_usdt is None or limits.max_daily_loss_usdt <= 0:
        return ""
    day = dt.datetime.fromtimestamp(now_ms / 1000, dt.UTC).strftime("%Y-%m-%d")
    equity = _equity_now(snap)
    if book.day_key != day:
        book.day_key = day
        book.swaps["day_equity"] = repr(equity)
    start = float(book.swaps.get("day_equity", equity))
    book.day_realized_usdt = equity - start
    if start - equity >= limits.max_daily_loss_usdt:
        return "已到单日损失上限，只停止新增风险"
    return ""


def _liquidation_close(snap: Snapshot) -> bool:
    if snap.mark_price <= 0 or snap.liquidation_price <= 0 or abs(snap.position_qty) < 1e-8:
        return False
    if snap.position_qty > 0:
        return (snap.mark_price - snap.liquidation_price) / snap.mark_price < 0.01
    return (snap.liquidation_price - snap.mark_price) / snap.mark_price < 0.01
