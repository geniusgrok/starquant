"""Full-sample research measurement of the one account.

This is the same-close historical mirror. It is not a real-time Demo month.
The forward loop is ``python -m btc_perp run``. A next-open fill study is
``python -m btc_perp causal``.

The sample is walked by successive manual sessions. Each session lasts
``session_seconds``, polls every ``poll_seconds``, and returns. The next
session is a new object on the same in-process venue, so a position and its
stop and take-profit stay up across the gap. There is no resident process.

A minute of the tape is replayed on the poll that completes that minute of
the session clock. The economics are ``scripts.frontier`` resumed one minute
at a time. The venue mirrors the size change, including a close.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from btc_perp.config import ROOT, AccountConfig, load_config
from btc_perp.exchange import SimExchange
from btc_perp.reportio import completion, publish
from btc_perp.session import Clock, Intent, ManualClock, Session

YEARS = 2454 / 365.25
TARGET_CNY = 10000.0 * (2.0**YEARS)


def _lots(qty: float) -> float:
    return float(round(abs(qty) * 1000.0) / 1000.0)


def _take_profit(side: int, entry: float, multiple: float) -> float:
    if side > 0:
        return entry * multiple
    if side < 0 and multiple != 0.0:
        return entry / multiple
    return 0.0


def position_intents(
    before_side: int,
    before_qty: float,
    before_stop: float,
    before_entry: float,
    after_side: int,
    after_qty: float,
    after_stop: float,
    after_entry: float,
    take_profit_multiple: float,
) -> tuple[Intent, ...]:
    """Orders that move a one-way book from the previous minute to this one.

    A reversal, or a same-side position whose entry price changed, is a reduce
    to flat and then a new entry. The reduce never carries size onto the new
    order. A larger size at a new average entry is a pyramid add.
    """
    tp = _take_profit(after_side, after_entry, take_profit_multiple)
    if before_side == 0 and after_side == 0:
        return ()
    if before_side == 0:
        return (Intent(after_side, _lots(after_qty), after_stop, tp),)
    if after_side == 0:
        return (Intent(0, _lots(before_qty), after_stop, tp),)
    if after_side != before_side:
        return (
            Intent(0, _lots(before_qty), after_stop, tp),
            Intent(after_side, _lots(after_qty), after_stop, tp),
        )
    if after_qty > before_qty + 1e-9:
        delta = _lots(after_qty - before_qty)
        if delta >= 0.001:
            return (Intent(after_side, delta, after_stop, tp),)
    if before_entry != after_entry:
        return (
            Intent(0, _lots(before_qty), after_stop, tp),
            Intent(after_side, _lots(after_qty), after_stop, tp),
        )
    if before_qty > after_qty + 1e-9:
        delta = _lots(before_qty - after_qty)
        if delta >= 0.001:
            return (Intent(-after_side, delta, after_stop, tp),)
    if after_stop != before_stop:
        return (Intent(after_side, 0.0, after_stop, tp),)
    return ()


def _check_timing(session_seconds: int, poll_seconds: int) -> None:
    if session_seconds <= 0 or poll_seconds <= 0:
        raise RuntimeError("session_seconds and poll_seconds must be positive")
    if 60 % poll_seconds != 0:
        raise RuntimeError("poll_seconds must divide 60 so a minute ends on a poll")
    if session_seconds % 60 != 0:
        raise RuntimeError("session_seconds must cover a whole number of minutes")


def _book(state: np.ndarray) -> tuple[int, float, float, float]:
    return int(state[1]), float(state[2]), float(state[3]), float(state[5])


def _signed_lots(qty: float) -> float:
    if abs(qty) < 0.001:
        return 0.0
    snapped = _lots(qty)
    return snapped if qty > 0 else -snapped


def _assert_mirrored(exchange: SimExchange, state: np.ndarray, bar: int) -> None:
    side, qty, _entry, _stop = _book(state)
    kernel = 0.0 if side == 0 else side * _lots(qty)
    venue = _signed_lots(exchange.position_qty)
    if abs(kernel - venue) >= 0.0005:
        raise RuntimeError(f"venue position {exchange.position_qty} diverged from kernel {kernel} at bar {bar}")
    if abs(kernel) < 0.001:
        if exchange.protections or exchange.late:
            raise RuntimeError(f"flat kernel still has venue orders at bar {bar}")
        return
    if not exchange.protection_covers_position():
        raise RuntimeError(f"open kernel is not fully protected at bar {bar}")


@dataclass
class _Held:
    """Book for one tape. Each manual session calls ``decide`` and then returns."""

    cfg: AccountConfig
    state: np.ndarray
    exchange: SimExchange
    equity: np.ndarray
    trace: np.ndarray
    o: np.ndarray
    h: np.ndarray
    low: np.ndarray
    c: np.ndarray
    fund: np.ndarray
    fx: np.ndarray
    hh: np.ndarray
    ll: np.ndarray
    xh: np.ndarray
    xl: np.ndarray
    gate: np.ndarray
    qv: np.ndarray
    resume: Any
    cursor: int
    end: float
    closes: int
    first_step_at: float
    origin: float = 0.0
    limit: int = 0
    start: int = 0
    poll_s: float = 0.0
    clock: Clock | None = None

    def decide(self, _view: Any) -> tuple[Intent, ...] | None:
        clock = self.clock
        if clock is None:
            raise RuntimeError("session clock is not set")
        _assert_mirrored(self.exchange, self.state, self.cursor)
        elapsed = clock.now() - self.origin + self.poll_s
        target = min(self.limit, self.start + int(elapsed // 60))
        intents: list[Intent] = []
        while self.cursor < target:
            if self.first_step_at < 0.0:
                self.first_step_at = clock.now()
            before_side, before_qty, before_entry, before_stop = _book(self.state)
            raw = self.resume(
                self.state,
                self.cursor,
                self.cursor + 1,
                self.o,
                self.h,
                self.low,
                self.c,
                self.fund,
                self.fx,
                self.hh,
                self.ll,
                self.xh,
                self.xl,
                self.cfg.stop,
                self.cfg.trail,
                self.cfg.add_step,
                self.cfg.max_units,
                self.cfg.risk,
                self.cfg.dd_flat,
                self.cfg.iso_frac,
                self.cfg.cooldown_hours * 60,
                self.cfg.ratchet_gain,
                self.cfg.ratchet_trail,
                self.cfg.heat,
                self.cfg.flatten_ratio,
                self.cfg.entry_scale_below,
                self.cfg.entry_scale,
                self.gate,
                self.qv,
                self.equity,
                self.trace,
            )
            self.end = float(raw[0])
            after_side, after_qty, after_entry, after_stop = _book(self.state)
            if before_side != 0 and (after_side != before_side or after_qty < before_qty - 1e-9):
                self.closes += 1
            intents.extend(
                position_intents(
                    before_side,
                    before_qty,
                    before_stop,
                    before_entry,
                    after_side,
                    after_qty,
                    after_stop,
                    after_entry,
                    self.cfg.take_profit_multiple,
                )
            )
            self.cursor += 1
        if not intents:
            return None
        return tuple(intents)


@dataclass
class Walk:
    end: float
    min_ratio: float
    n_long: int
    n_short: int
    n_stop: int
    min_i: int
    equity: np.ndarray
    closes: int
    submits: int
    sessions: int
    polls: int
    first_step_clock: tuple[float, ...]
    position_at_session_end: tuple[float, ...]


def walk_tape(
    cfg: AccountConfig,
    o: np.ndarray,
    h: np.ndarray,
    low: np.ndarray,
    c: np.ndarray,
    qv: np.ndarray,
    fund: np.ndarray,
    fx: np.ndarray,
    hh: np.ndarray,
    ll: np.ndarray,
    xh: np.ndarray,
    xl: np.ndarray,
    gate: np.ndarray,
) -> Walk:
    """Replay ``c`` by starting a session, letting it return, then starting the next."""
    _check_timing(cfg.session_seconds, cfg.poll_seconds)
    from scripts.frontier import initial_state, resume

    n = len(c)
    bars_per_session = cfg.session_seconds // 60
    state = initial_state(float(fx[0]))
    equity = np.empty(n, dtype=np.float64)
    trace = np.empty((1, 4), dtype=np.float64)
    exchange = SimExchange()
    cursor = 0
    closes = 0
    sessions = 0
    polls = 0
    end = 0.0
    first_step_clock: list[float] = []
    position_at_session_end: list[float] = []
    held = _Held(
        cfg=cfg,
        state=state,
        exchange=exchange,
        equity=equity,
        trace=trace,
        o=o,
        h=h,
        low=low,
        c=c,
        fund=fund,
        fx=fx,
        hh=hh,
        ll=ll,
        xh=xh,
        xl=xl,
        gate=gate,
        qv=qv,
        resume=resume,
        cursor=0,
        end=0.0,
        closes=0,
        first_step_at=-1.0,
    )

    while cursor < n:
        limit = min(n, cursor + bars_per_session)
        clock = ManualClock()
        session = Session(exchange, clock, duration_s=float(cfg.session_seconds), poll_s=float(cfg.poll_seconds))
        held.cursor = cursor
        held.start = cursor
        held.limit = limit
        held.first_step_at = -1.0
        held.origin = clock.now()
        held.poll_s = float(cfg.poll_seconds)
        held.clock = clock
        session.run(held.decide)
        cursor = held.cursor
        end = held.end
        closes += held.closes
        held.closes = 0
        _assert_mirrored(exchange, state, cursor)
        sessions += 1
        polls += session.polls
        if held.first_step_at >= 0.0:
            first_step_clock.append(held.first_step_at)
        position_at_session_end.append(exchange.position_qty)

    return Walk(
        end=end,
        min_ratio=float(state[12]),
        n_long=int(state[13]),
        n_short=int(state[14]),
        n_stop=int(state[15]),
        min_i=int(state[16]),
        equity=equity,
        closes=closes,
        submits=exchange.submits,
        sessions=sessions,
        polls=polls,
        first_step_clock=tuple(first_step_clock),
        position_at_session_end=tuple(position_at_session_end),
    )


def _prepare(cfg: AccountConfig) -> tuple[Any, ...]:
    from scripts.frontier import _channels, load_hourly

    _open_h, h_h, l_h, c_h, fund_h, fx_h, days_h = load_hourly()
    raw = np.load(ROOT / "data" / "btcusdt_1m.npz")
    o = raw["o"].astype(np.float64)
    h = raw["h"].astype(np.float64)
    low = raw["l"].astype(np.float64)
    c = raw["c"].astype(np.float64)
    qv = raw["qv"].astype(np.float64)
    n = len(c)
    if n != len(c_h) * 60:
        raise RuntimeError("1-minute tape is not an exact hourly multiple")
    minute = np.arange(n) % 60
    hour = np.arange(n) // 60
    fund = np.zeros(n)
    fund[minute == 0] = fund_h
    fx = np.repeat(fx_h, 60)
    days = np.repeat(days_h, 60)
    hh, ll, xh, xl = _channels(h_h, l_h, cfg.entry_hours, cfg.exit_hours)
    gate = np.zeros(n, np.int8)
    gate[minute == 59] = 1
    return o, h, low, c, qv, fund, fx, days, minute, hh[hour], ll[hour], xh[hour], xl[hour], gate


def run_official(write_report: bool = True) -> dict[str, Any]:
    cfg = load_config()
    problems = _tape_problems()
    if problems:
        refused: dict[str, Any] = {
            "verified": False,
            "passed": False,
            "reason": "行情校验没有通过，这次没有测量结果",
            "problems": problems,
            "completion": completion(data_validated=False, path_complete=False, economic_pass=False),
        }
        if write_report:
            publish(ROOT / "reports" / "btc_account_measure.json", refused)
        return refused
    o, h, low, c, qv, fund, fx, days, minute, hh, ll, xh, xl, gate = _prepare(cfg)
    walked = walk_tape(cfg, o, h, low, c, qv, fund, fx, hh, ll, xh, xl, gate)
    end = walked.end
    ratio = walked.min_ratio
    cagr = (end / cfg.start_cny) ** (1.0 / YEARS) - 1.0 if end > 0 else -1.0
    yearly: dict[str, dict[str, float]] = {}
    prev = cfg.start_cny
    seen: dict[int, float] = {}
    for i, day in enumerate(days):
        if minute[i] == 59:
            seen[int(day) // 10000] = float(walked.equity[i])
    for year, equity in sorted(seen.items()):
        yearly[str(year)] = {"equity_cny": equity, "return": equity / prev - 1.0}
        prev = equity
    passed = bool(cagr >= 1.0 and ratio > 0.5 and end >= TARGET_CNY and walked.n_long > 0 and walked.n_short > 0)
    meets_150 = bool(cagr >= 1.5 and ratio > 0.5 and walked.n_long > 0 and walked.n_short > 0)
    report: dict[str, Any] = {
        "verified": True,
        "passed": passed,
        "completion": completion(data_validated=True, path_complete=True, economic_pass=meets_150),
        "start_cny": cfg.start_cny,
        "end_cny": float(end),
        "target_cny": TARGET_CNY,
        "cagr": float(cagr),
        "min_equity_over_peak": float(ratio),
        "min_day": int(days[walked.min_i]),
        "n_long": int(walked.n_long),
        "n_short": int(walked.n_short),
        "n_stop": int(walked.n_stop),
        "yearly": yearly,
        "costs": {
            "taker": cfg.taker,
            "slip_base": cfg.slip_base,
            "impact_y": cfg.impact_y,
            "fx_fee": cfg.fx_fee,
            "funding": "binance vision through 2026-08-31, premium-index September 2026, 2026-09-01 00:00 missing",
        },
        "path": (
            "successive manual sessions, one minute stepped when the session clock completes that minute; "
            "1-minute OHLC path, previous-minute stop slippage, FX fixing from the previous date, tiered liquidation"
        ),
        "sessions": {
            "seconds": cfg.session_seconds,
            "poll_seconds": cfg.poll_seconds,
            "count": walked.sessions,
            "polls": walked.polls,
            "closes": walked.closes,
        },
    }
    if write_report:
        publish(ROOT / "reports" / "btc_account_measure.json", report)
    return report


def _tape_problems() -> list[str]:
    """The same minute-tape checks the causal replay makes, before any number is produced."""
    from btc_perp.causal import validate_minutes

    path = ROOT / "data" / "btcusdt_1m.npz"
    if not path.exists():
        return ["data/btcusdt_1m.npz 不存在"]
    raw = np.load(path)
    return list(validate_minutes(raw["ts"], raw["o"], raw["h"], raw["l"], raw["c"], raw["qv"]))
