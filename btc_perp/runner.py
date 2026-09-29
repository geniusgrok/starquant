"""One forward cycle. The exchange snapshot is the position.

A market order is written as ``sent`` before the transport call. A timeout
queries that same client id. Demo and production share this loop and differ
by host, keys, state directory, and the production gate.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable
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
MAX_DECISION_AGE_MS = 30_000
FLATTEN_ROUNDS = 4
FLOW_KINDS = frozenset({"TRANSFER", "INTERNAL_TRANSFER", "WELCOME_BONUS", "CROSS_COLLATERAL_TRANSFER", "AUTO_EXCHANGE"})
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
    remaining: tuple[str, ...] = ()


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


# Codes that mean "this request was refused before it did anything". Everything
# else that is not a success stays unknown so that no new risk is released.
_REFUSED = frozenset(range(-2028, -2017)) | frozenset({-2010, -2014, -2015}) | frozenset(range(-1130, -1099))
_REFUSED_BAND = (-4200, -4000)
_STILL_UNKNOWN = frozenset({-4116, -4120})


@dataclass(frozen=True)
class EntryContext:
    """What the single entry gate needs besides the fresh snapshot and the book."""

    environment: str
    limits: Limits
    cli_cap: float | None
    cap: float | None
    prod_enabled: bool
    clock: Callable[[], int]


@dataclass(frozen=True)
class Outcome:
    phase: str
    executed: float = 0.0
    order_id: str = ""


def _refused_code(number: int) -> bool:
    if number in _STILL_UNKNOWN:
        return False
    return number in _REFUSED or _REFUSED_BAND[0] <= number <= _REFUSED_BAND[1]


def classify(body: dict[str, object], *, cancel: bool = False) -> Outcome:
    """Map one exchange answer onto an intent phase, with the fill it reports.

    A missing order, a refused request, a finished conditional order and a
    cancel that found nothing are different facts. Unrecognised answers are
    ``unknown``.
    """
    code = body.get("code")
    if code not in (None, 0, 200):
        try:
            number = int(str(code))
        except ValueError:
            return Outcome("unknown")
        msg = str(body.get("msg", "")).lower()
        if number == -2013:
            return Outcome("missing")
        if "duplicat" in msg or "already exist" in msg:
            return Outcome("unknown")
        if _refused_code(number):
            return Outcome("rejected")
        return Outcome("unknown")
    status = str(body.get("status") or body.get("algoStatus") or "")
    executed = _float(body.get("executedQty"))
    order_id = str(body.get("orderId") or body.get("actualOrderId") or "")
    if order_id in {"0", "None"}:
        order_id = ""
    if not status and cancel and code in (0, 200):
        return Outcome("canceled", executed, order_id)
    if status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"} and executed > 0:
        return Outcome("filled", executed, order_id)
    if status == "FINISHED":
        return Outcome("filled" if order_id else "unknown", executed, order_id)
    phase = {
        "NEW": "acked",
        "PARTIALLY_FILLED": "partial",
        "FILLED": "filled",
        "CANCELED": "canceled",
        "CANCELLED": "canceled",
        "REJECTED": "rejected",
        "EXPIRED": "expired",
        "TRIGGERING": "acked",
        "TRIGGERED": "acked",
    }.get(status, "unknown")
    return Outcome(phase, executed, order_id)


def interpret_body(body: dict[str, object], *, cancel: bool = False) -> str:
    return classify(body, cancel=cancel).phase


def _float(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


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


def _control_requested(store: Store, name: str, environment: str, alerts: list[str]) -> bool:
    """A stop or flatten request file counts only for the environment that wrote it."""
    path = store.directory / name
    if not path.exists():
        return False
    try:
        body = json.loads(path.read_text() or "{}")
    except (OSError, ValueError):
        return True
    if isinstance(body, dict) and body.get("environment") not in (None, environment):
        alerts.append(f"{name} 属于另一个环境，忽略")
        return False
    return True


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
    clock: Callable[[], int] | None = None,
) -> CycleReport:
    """One pass. ``check`` and ``takeover`` never write to the exchange."""
    clock_ms = clock or (lambda: now_ms)
    book = store.load_book()
    sent: list[str] = []
    would: list[str] = []
    alerts: list[str] = []
    remaining: list[str] = []
    if mode == "run" and _control_requested(store, "stop.request", environment, alerts):
        mode = "stop"
    if mode == "run" and _control_requested(store, "flatten.request", environment, alerts):
        mode = "flatten"
    if stream_expired:
        alerts.append("用户流过期或断开，本轮只采用 REST 快照")
        store.append_event("stream", "rest-snapshot")
    cap = notional_cap(max_notional, limits)
    ctx = EntryContext(environment, limits, max_notional, cap, prod_enabled, clock_ms)
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
    flow_problem = _flow_problem(book, snap)

    drift = _drift(snap, now_ms)
    problem = readiness(snap)
    foreign = foreign_ids(snap, store.all_client_ids())
    cursor = _trade_cursor(book, snap)
    mismatch = freeze_for_manual(book, snap, store.intents(), store.own_order_ids(), cursor)
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
        elif flow_problem:
            book.entries_frozen = True
            book.freeze_reason = flow_problem
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
        for item in store.open_intents():
            alerts.append(f"未决意图 {item.client_id}（{item.action}，{item.phase}）")
        _save(store, book, dry_run)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered)

    owned = not mismatch or book.manual

    if mode == "stop":
        settled = False
        if dry_run:
            _safe_stop(store, venue, snap, book, sent, would, alerts, dry_run)
        else:
            settled = _stop_until_safe(store, venue, book, cfg, environment, prod_enabled, owned, sent, alerts, now_ms)
            snap = venue.snapshot()
            remaining = _own_remaining(store, snap, entries_only=True)
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered, settled, remaining)

    if mode == "flatten":
        book.entries_frozen = True
        book.freeze_reason = "只减仓停机"
        settled = False
        if dry_run:
            _flatten(store, venue, snap, book, environment, prod_enabled, sent, would, alerts, dry_run, now_ms)
        else:
            settled, remaining = _flatten_until_done(
                store, venue, book, cfg, environment, prod_enabled, sent, alerts, now_ms
            )
            snap = venue.snapshot()
            _sync_book(store, book, snap, cfg, now_ms)
        _save(store, book, dry_run)
        covered, _why = protections_cover(snap)
        return _finish(store, now_ms, mode, book, snap, sent, alerts, dry_run, would, covered, settled, remaining)

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
            ctx,
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
        _maybe_open_after_flat(store, venue, snap, book, cfg, ctx, sent, alerts, now_ms)
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
    remaining: list[str] | None = None,
) -> CycleReport:
    report = _report(mode, book, snap, sent, alerts, dry_run, would, covered, settled, remaining)
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
            "remaining": list(remaining or []),
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
    remaining: list[str] | None = None,
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
        remaining=tuple(remaining or ()),
    )


def _update_lock(book: Book, snap: Snapshot, cfg: AccountConfig, fx_used: float, alerts: list[str]) -> None:
    """Say out loud when the drawdown lock is on. It blocks new entries and adds."""
    equity = _equity_now(snap) * fx_used
    perf = float(book.swaps.get("perf_peak", "0") or "0")
    if equity > perf:
        book.swaps["perf_peak"] = repr(equity)
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
    live_plain = [order.client_id or "无编号" for order in snap.orders if order.status in {"NEW", "PARTIALLY_FILLED"}]
    live_algo = [algo.client_algo_id or "无编号" for algo in snap.algos if algo.status in {"NEW", "TRIGGERING"}]
    if live_plain or live_algo:
        alerts.append("交易所上还有活动订单，不重置回撤基准：" + ",".join((live_plain + live_algo)[:5]))
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
    book.swaps.pop("flow_frozen", None)
    book.swaps["income_cursor_ms"] = str(snap.server_time_ms or int(time.time() * 1000))
    book.swaps.setdefault("perf_peak", repr(old[1]))
    store.append_event("rearm", f"peak {old[0]:.2f}/{old[1]:.2f} -> {equity:.2f}")
    alerts.append(
        f"回撤基准已重置为 {equity:.2f}；累计绩效峰值 {book.swaps['perf_peak']} 不变，这不改变止损、保护和其他限额"
    )
    return True


def _trade_cursor(book: Book, snap: Snapshot) -> int:
    """Fills up to here are already accounted for. The first look starts from the newest fill."""
    raw = book.swaps.get("trade_cursor")
    if raw is None:
        newest = max((trade.trade_id for trade in snap.trades), default=0)
        book.swaps["trade_cursor"] = str(newest)
        return newest
    try:
        return int(raw)
    except ValueError:
        return 0


def _flow_problem(book: Book, snap: Snapshot) -> str:
    """Deposits, withdrawals and transfers change the equity baselines. They are not supported mid-run."""
    if book.swaps.get("flow_frozen"):
        return "发现过资金划转，新增风险冻结；确认后在空仓时用 rearm 重置"
    if not snap.funding_ok:
        return ""
    stamp = snap.server_time_ms
    raw = book.swaps.get("income_cursor_ms")
    if raw is None:
        book.swaps["income_cursor_ms"] = str(stamp)
        return ""
    flows = [row for row in snap.income if row.kind in FLOW_KINDS and row.time_ms > int(raw)]
    if flows:
        book.swaps["flow_frozen"] = "1"
        return f"发现 {len(flows)} 笔资金划转，新增风险冻结；确认后在空仓时用 rearm 重置"
    return ""


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
        if "perf_peak" in book.swaps:
            book.swaps["perf_peak"] = repr(float(book.swaps["perf_peak"]) * scale)
    book.swaps["peak_unit"] = unit
    if unit == "CNY":
        book.swaps["peak_fx"] = repr(fx_used)
    return ""


def _sync_book(store: Store, book: Book, snap: Snapshot, cfg: AccountConfig, now_ms: int) -> None:
    """Follow the exchange position only when our own orders explain it."""
    if not snap.known or book.manual:
        return
    intents = store.intents()
    cursor = _trade_cursor(book, snap)
    if freeze_for_manual(book, snap, intents, store.own_order_ids(), cursor) != "":
        return
    _absorb(book, snap, cfg, now_ms, store)
    if snap.trades:
        book.swaps["trade_cursor"] = str(max(cursor, max(trade.trade_id for trade in snap.trades)))
    if not any(item.action in POSITION_ACTIONS and item.phase in OPEN_PHASES for item in intents):
        store.settle_absorbed()


def _absorb(book: Book, snap: Snapshot, cfg: AccountConfig, now_ms: int, store: Store) -> None:
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
        book.swaps["pos_since_ms"] = str(_fill_time(store, snap, now_ms))
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


def _fill_time(store: Store, snap: Snapshot, now_ms: int) -> int:
    """When our entry order filled. Without a matching fill the first sighting is the best available time."""
    entry_orders = {item.order_id for item in store.intents() if item.action in _ENTRY_ACTIONS and item.order_id}
    times = [trade.time_ms for trade in snap.trades if trade.order_id in entry_orders]
    return max(times) if times else now_ms


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


def _record_outcome(store: Store, intent: Intent, outcome: Outcome, note: str = "") -> None:
    store.mark_intent(intent.client_id, outcome.phase, note or intent.note, order_id=outcome.order_id)
    if outcome.phase in {"rejected", "canceled", "expired"} and outcome.executed <= 0:
        store.mark_absorbed(intent.client_id)
    elif outcome.phase == "filled" and _is_algo(intent):
        store.mark_unabsorbed(intent.client_id)


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
    (protection and reduce-only orders), or ``all``. An entry that was never
    handed to the network is dropped and decided again on the current gate. An
    entry that may have been handed over is only queried: not found and
    unanswered both stay unknown until an operator resolves them.
    """
    _ = book
    if dry_run:
        return
    live_algos = {algo.client_algo_id for algo in snap.algos if algo.status == "NEW"}
    for intent in list(store.open_intents()):
        is_entry = intent.action in _ENTRY_ACTIONS
        if intent.phase == "planned":
            if is_entry:
                store.mark_intent(intent.client_id, "canceled", "unsent-plan-dropped")
                store.mark_absorbed(intent.client_id)
                alerts.append("未发送的旧入场计划已作废，会按当前条件重新决定")
                continue
            if not _may_send(intent.action, allow):
                if allow != "none":
                    store.mark_intent(intent.client_id, "canceled", "not-sent-in-this-mode")
                    store.mark_absorbed(intent.client_id)
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
        outcome = classify(body)
        if outcome.phase != "missing":
            _record_outcome(store, intent, outcome)
            continue
        if is_entry:
            store.mark_intent(intent.client_id, "unknown", "missing-not-resent")
            alerts.append(
                f"原入场单 {intent.client_id} 查不到：不重发，也不会按时间判为过期；确认交易所没有它之后用 resolve 处理"
            )
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
    ctx: EntryContext,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
) -> str:
    table = _channel_table(hour_rows, cfg.entry_hours, cfg.exit_hours) if hour_rows else {}
    since = int(book.swaps.get("pos_since_ms", "0") or "0")
    for bar in status.new_bars:
        hh, ll, xh, xl = _levels_for_bar(bar, channels, table)
        # The minute that contains the fill is not a minute the position was held through.
        held_then = book.side != 0 and (since <= 0 or bar.open_ms >= since)
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
            equity_usd=risk_equity(close_usd, ctx.limits),
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
            # A backlog minute only rebuilds memory. It never opens risk at today's price.
            if action.kind in {"enter", "add"}:
                continue
            if action.kind == "reverse":
                action = Action("exit", action.side, action.qty, action.stop, action.disaster_take, action.reason)
        return _act(action, store, venue, snap, book, cfg, ctx, sent, would, alerts, dry_run, now_ms, bar.open_ms)
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


def _preflight(side: int, book: Book, snap: Snapshot, cfg: AccountConfig, adding: bool) -> str:
    """Both protection legs must be placeable at today's price before any entry is sent."""
    filters = snap.filters
    last = snap.last_price
    if filters is None or last <= 0:
        return "没有价格精度或现价，无法预检保护单"
    price = snap.mark_price or last
    if adding and book.side == side and book.stop > 0:
        stop_source = book.stop
    else:
        stop_source = initial_stop(side, price, cfg.stop, 0.0, price)
    take_source = disaster_take(side, price, cfg.take_profit_multiple)
    stop_px = _tick(stop_source, filters.tick_size)
    take_px = _tick(take_source, filters.tick_size)
    if not (_trigger_ok(side, "stop", stop_px, last) and _trigger_ok(side, "take", take_px, last)):
        return "保护单预检未通过：触发价落在现价的错误一侧"
    if not _in_band(filters.min_price, filters.max_price, stop_px, take_px):
        return "保护单预检未通过：触发价在价格带外"
    return ""


def _entry_gate(
    store: Store, snap: Snapshot, book: Book, cfg: AccountConfig, ctx: EntryContext, decided_ms: int
) -> str:
    """The one check every new-risk path passes, run against the newest snapshot.

    Ordinary entries, adds, the opening leg of a reversal and any restarted
    plan all come through here. Empty means new risk may be sent.
    """
    if book.manual:
        return "已接管实仓，仍不自动加仓"
    if book.entries_frozen:
        return "增仓已冻结：" + book.freeze_reason
    if book.dd_locked:
        return "回撤锁已触发，不开新仓、不加仓"
    if book.swaps.get("flow_frozen"):
        return "发现过资金划转，新增风险冻结"
    if book.cooldown_until_ms > decided_ms:
        return "止损后的冷却期内，不开新仓"
    blocked = entry_block_reason(ctx.environment, ctx.limits, ctx.cli_cap, prod_enabled=ctx.prod_enabled)
    if blocked:
        return blocked
    if not snap.known:
        return snap.reason or "账户未知"
    now = ctx.clock()
    problem = readiness(snap) or _drift(snap, now)
    if problem:
        return problem
    if snap.read_ms <= 0 or now - snap.read_ms > MAX_DECISION_AGE_MS:
        return "账户读数已过期，不发送新增风险"
    if now - decided_ms > MAX_DECISION_AGE_MS:
        return "决策已过期，不发送新增风险"
    loss = _loss_block(book, snap, ctx.limits, decided_ms)
    if loss:
        return loss
    if _liquidation_close(snap):
        return "强平距离过近"
    alerts: list[str] = []
    for name in ("stop.request", "flatten.request"):
        if _control_requested(store, name, ctx.environment, alerts):
            return "有停机或平仓请求，不发送新增风险"
    stray = foreign_ids(snap, store.all_client_ids())
    if stray:
        return "存在未知外来订单：" + ",".join(stray[:5])
    mismatch = freeze_for_manual(book, snap, store.intents(), store.own_order_ids(), _trade_cursor(book, snap))
    if mismatch:
        return mismatch
    if any(item.action in POSITION_ACTIONS and item.phase in OPEN_PHASES for item in store.intents(_OPEN)):
        return "已有未完成订单，不会再发一张新增风险的单"
    if abs(snap.position_qty) >= 1e-8 and not protections_cover(snap)[0]:
        return "现有仓位保护不完整，先补保护，不加仓"
    return ""


def _act(
    action: Action,
    store: Store,
    venue: Venue,
    snap: Snapshot,
    book: Book,
    cfg: AccountConfig,
    ctx: EntryContext,
    sent: list[str],
    would: list[str],
    alerts: list[str],
    dry_run: bool,
    now_ms: int,
    bar_open_ms: int,
) -> str:
    environment = ctx.environment
    if action.kind in {"enter", "add"}:
        blocked = _entry_gate(store, snap, book, cfg, ctx, now_ms)
        if blocked:
            return blocked
        problem = _preflight(1 if action.side > 0 else -1, book, snap, cfg, action.kind == "add")
        if problem:
            return problem
        price = snap.mark_price or snap.last_price
        qty = _fit_qty(action.qty, snap, price, False, ctx.cap or 0.0)
        if qty is None:
            return "数量不满足交易所过滤器或名义上限"
        side = "BUY" if action.side > 0 else "SELL"
        _queue_market(
            store, venue, book, environment, action.kind, side, qty, False, sent, would, alerts, dry_run, now_ms
        )
        return action.reason
    if action.kind in {"exit", "reverse"}:
        blocked = reducing_block_reason(environment, prod_enabled=ctx.prod_enabled)
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
    ctx: EntryContext,
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
        _drop_reverse_plan(book)
        alerts.append("反向开仓错过确认窗口")
        return
    blocked = _entry_gate(store, snap, book, cfg, ctx, now_ms)
    if blocked:
        alerts.append("反向开仓被拦下：" + blocked)
        return
    problem = _preflight(1 if side == "BUY" else -1, book, snap, cfg, False)
    if problem:
        alerts.append("反向开仓被拦下：" + problem)
        return
    price = snap.mark_price or snap.last_price
    raw = _qty(
        risk_equity(_equity_now(snap), ctx.limits),
        price,
        cfg.stop,
        cfg.risk,
        float(book.swaps.get("after_scale", "1") or "1"),
        cfg.iso_frac,
        cfg.heat,
        cfg.trail,
        cfg.leverage,
        ctx.cap or 0.0,
    )
    qty = _fit_qty(raw, snap, price, False, ctx.cap or 0.0)
    if qty is None:
        alerts.append("反向开仓数量不满足过滤器")
        return
    _drop_reverse_plan(book)
    _queue_market(store, venue, book, ctx.environment, "enter", side, qty, False, sent, [], alerts, False, now_ms)


def _drop_reverse_plan(book: Book) -> None:
    for key in ("after_flat", "after_flat_ms", "after_scale"):
        book.swaps.pop(key, None)


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
    known = store.all_client_ids()
    commands, swaps = plan_protection(snap, book.swaps, stop_price=stop_px, take_price=take_px, known=known)
    book.swaps = swaps
    for command in commands:
        _queue_algo(store, venue, book, store.environment, command, sent, alerts, now_ms)
        placed = _reload(store, command.client_id)
        if command.order_type == "STOP_MARKET" and (placed is None or placed.phase not in {"acked", "filled"}):
            alerts.append("止损单没有确认，本轮不再挂止盈，下一轮先核对")
            break
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
    """Cancel the entry orders that this program created. Foreign orders are named, never touched."""
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


def _own_remaining(store: Store, snap: Snapshot, entries_only: bool = False) -> list[str]:
    """What still stands between the account and "settled". Empty means nothing does.

    ``entries_only`` is the stop check: no unfinished entry or reduce intent,
    no entry order of ours resting, protection intact while a position stays.
    Otherwise (flatten) the account must be flat with no order of ours left.
    Orders that are not ours are always listed and never cleared.
    """
    if not snap.known:
        return ["账户快照未知"]
    known = store.all_client_ids()
    left: list[str] = []
    for item in store.open_intents():
        if item.action in _ENTRY_ACTIONS or item.action in {"reduce", "flatten"} or not entries_only:
            left.append(f"未完成意图 {item.client_id}（{item.action}，{item.phase}）")
    for order in snap.orders:
        if order.status not in {"NEW", "PARTIALLY_FILLED"}:
            continue
        name = order.client_id or "无编号"
        if order.client_id not in known:
            left.append(f"外来订单 {name}")
        elif not order.reduce_only or not entries_only:
            left.append(f"本程序挂单 {name}")
    flat = abs(snap.position_qty) < 1e-8
    for algo in snap.algos:
        if algo.status != "NEW":
            continue
        name = algo.client_algo_id or "无编号"
        if algo.client_algo_id not in known:
            left.append(f"外来条件单 {name}")
        elif flat:
            left.append(f"空仓仍有本程序条件单 {name}")
    if not flat:
        if not entries_only:
            left.append(f"仍有持仓 {snap.position_qty}")
        else:
            covered, why = protections_cover(snap)
            if not covered:
                left.append("保护不完整：" + why)
    return left


def _stop_settled(store: Store, snap: Snapshot) -> bool:
    return not _own_remaining(store, snap, entries_only=True)


def _stop_until_safe(
    store: Store,
    venue: Venue,
    book: Book,
    cfg: AccountConfig,
    environment: str,
    prod_enabled: bool,
    owned: bool,
    sent: list[str],
    alerts: list[str],
    now_ms: int,
) -> bool:
    """Stop entering, keep or restore protection, and repeat until the account says it is settled."""
    book.entries_frozen = True
    book.freeze_reason = "安全停机"
    for _round in range(FLATTEN_ROUNDS):
        snap = venue.snapshot()
        if not snap.known:
            alerts.append("停机时账户快照未知")
            return False
        _reconcile(store, venue, snap, book, sent, alerts, allow="reduce", now_ms=now_ms, dry_run=False)
        snap = venue.snapshot()
        if not snap.known:
            return False
        _safe_stop(store, venue, snap, book, sent, [], alerts, False)
        snap = venue.snapshot()
        if snap.known and owned and abs(snap.position_qty) >= 1e-8:
            if _keep_protected(store, venue, snap, book, cfg, sent, alerts, now_ms):
                _flatten(
                    store, venue, venue.snapshot(), book, environment, prod_enabled, sent, [], alerts, False, now_ms
                )
            snap = venue.snapshot()
        if _stop_settled(store, snap):
            return True
    return False


def _flatten_until_done(
    store: Store,
    venue: Venue,
    book: Book,
    cfg: AccountConfig,
    environment: str,
    prod_enabled: bool,
    sent: list[str],
    alerts: list[str],
    now_ms: int,
) -> tuple[bool, list[str]]:
    """Reduce to flat and clean our own orders, in a bounded loop. The leftovers are named, not hidden."""
    _ = cfg
    remaining: list[str] = []
    blocked = reducing_block_reason(environment, prod_enabled=prod_enabled)
    for _round in range(FLATTEN_ROUNDS):
        snap = venue.snapshot()
        if not snap.known:
            return False, ["账户快照未知"]
        _reconcile(store, venue, snap, book, sent, alerts, allow="reduce", now_ms=now_ms, dry_run=False)
        snap = venue.snapshot()
        if not snap.known:
            return False, ["账户快照未知"]
        if blocked:
            alerts.append(blocked)
        else:
            _flatten(store, venue, snap, book, environment, prod_enabled, sent, [], alerts, False, now_ms)
            snap = venue.snapshot()
            if snap.known:
                _reconcile(store, venue, snap, book, sent, alerts, allow="reduce", now_ms=now_ms, dry_run=False)
                snap = venue.snapshot()
        if snap.known:
            _siblings(store, venue, snap, sent, alerts)
            snap = venue.snapshot()
        remaining = _own_remaining(store, snap)
        if not remaining:
            return True, []
        if blocked:
            break
    return False, remaining


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
        phase="sent",
        side=side,
        qty=qty,
        reduce_only=reduce_only,
        close_position=False,
        trigger_price="",
        environment=environment,
        created_ms=now_ms,
        note="before-transport",
        absorbed=False,
    )
    if action in _ENTRY_ACTIONS:
        book.swaps["unit_from"] = client_id
    store.record_send(intent, book)
    _transmit(store, venue, intent, sent, alerts)


def _queue_algo(
    store: Store,
    venue: Venue,
    book: Book,
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
        store.mark_intent(existing.client_id, "sent", "before-transport")
        existing.phase = "sent"
        _transmit(store, venue, existing, sent, alerts)
        return
    intent = Intent(
        client_id=command.client_id,
        action="stop" if command.order_type == "STOP_MARKET" else "take",
        phase="sent",
        side=command.side,
        qty=command.qty,
        reduce_only=command.reduce_only,
        close_position=True,
        trigger_price=command.trigger_price,
        environment=environment,
        created_ms=now_ms,
        note="before-transport",
    )
    store.record_send(intent, book)
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
        sent.append(intent.client_id)
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
    except ValueError as exc:
        store.mark_intent(intent.client_id, "rejected", "error")
        store.mark_absorbed(intent.client_id)
        alerts.append(str(exc)[:160])
        _transmit_journal(store, intent, "rejected", started)
        return
    except RuntimeError as exc:
        store.mark_intent(intent.client_id, "unknown", "runtime-error")
        sent.append(intent.client_id)
        alerts.append("下单出现无法归类的错误，结果按未知处理：" + str(exc)[:120])
        _transmit_journal(store, intent, "unknown", started)
        return
    outcome = classify(body)
    if outcome.phase == "missing":
        outcome = Outcome("unknown", outcome.executed, outcome.order_id)
    _record_outcome(store, intent, outcome)
    sent.append(intent.client_id)
    _transmit_journal(store, intent, outcome.phase, started)
    if outcome.phase == "rejected":
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
    """Cancel one of our own orders.

    The answer is recorded as it came. A target that is not found is not a
    success, and an answer about a different id proves nothing. The next
    snapshot is the check that the order is really gone.
    """
    known = _reload(store, command.client_id)
    try:
        if command.op == "cancel_algo":
            body = venue.cancel_algo(command.client_id)
        else:
            body = venue.cancel_order(command.client_id)
    except UnknownExecution:
        sent.append(command.client_id)
        alerts.append("撤单结果未知 " + command.client_id)
        store.append_event("cancel-unknown", command.client_id)
        if known is not None:
            store.mark_intent(command.client_id, "unknown", "cancel-unknown")
        return
    except WriteRefused as exc:
        alerts.append(str(exc)[:160])
        return
    sent.append(command.client_id)
    echoed = str(body.get("clientOrderId") or body.get("origClientOrderId") or body.get("clientAlgoId") or "")
    outcome = classify(body, cancel=True)
    if echoed and echoed != command.client_id:
        outcome = Outcome("unknown")
    if outcome.phase == "missing":
        alerts.append("撤单目标查不到，不当作已撤销：" + command.client_id)
        store.append_event("cancel-missing", command.client_id)
        if known is not None and known.phase in {"sent", "acked", "partial", "unknown"}:
            store.mark_intent(command.client_id, "unknown", "cancel-target-missing")
        return
    if outcome.phase == "unknown":
        alerts.append("撤单回应无法确认：" + command.client_id)
    if known is not None:
        _record_outcome(store, known, outcome, "cancel")
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
