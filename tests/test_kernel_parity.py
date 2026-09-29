"""The forward policy against the historical replay kernel, event by event.

Both see the same minutes and the same channels. The kernel (``scripts/frontier``
with ``defer=1``: a close signal fills at the next open) is the reference for
what trades happened. At every minute close this test asks the forward
``decide`` what it would do with the book the runner rebuilds from the kernel's
position, and requires the action to be the one the kernel took on the next
minute. Stop-outs are the exchange's job in production and the kernel's path in
research, so they are taken from the kernel and only checked to be reachable.

Intentional differences are listed in ``docs/forward_audit.md`` (round 5, S14).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest

from btc_perp.config import AccountConfig, load_config
from btc_perp.model import Book, Snapshot
from btc_perp.policy import clamp_to_liquidation, decide
from btc_perp.runner import _absorb
from btc_perp.store import Store
from scripts.frontier import _channels, _liq_price, initial_state, resume

HOURS = 24 * 60
FX = 7.0
T0 = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000


@dataclass
class Tape:
    o: np.ndarray
    h: np.ndarray
    low: np.ndarray
    c: np.ndarray
    hh: np.ndarray
    ll: np.ndarray
    xh: np.ndarray
    xl: np.ndarray
    gate: np.ndarray
    equity: np.ndarray
    trace: np.ndarray


def _prices(seed: int, vol: float = 0.0008) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = HOURS * 60
    drift = np.zeros(n)
    for a, b, d in (
        (6000, 16000, 0.00006),
        (22000, 34000, -0.00007),
        (40000, n, 0.00006),
    ):
        drift[a:b] = d
    ret = drift + rng.normal(0, vol, n)
    c = 100 * np.exp(np.cumsum(ret))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0003, n)))
    low = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0003, n)))
    return o, h, low, c


def _replay(cfg: AccountConfig, seed: int, vol: float = 0.0008) -> Tape:
    o, h, low, c = _prices(seed, vol)
    n = len(c)
    hi_h = h.reshape(-1, 60).max(1)
    lo_h = low.reshape(-1, 60).min(1)
    hh, ll, xh, xl = _channels(hi_h, lo_h, cfg.entry_hours, cfg.exit_hours)
    hour = np.arange(n) // 60
    gate = np.zeros(n, np.int8)
    gate[(np.arange(n) % 60) == 59] = 1
    state = initial_state(FX)
    equity = np.empty(n)
    trace = np.zeros((n, 5))
    resume(
        state, 0, n, o, h, low, c, np.zeros(n), np.full(n, FX),
        hh[hour], ll[hour], xh[hour], xl[hour],
        cfg.stop, cfg.trail, cfg.add_step, cfg.max_units, cfg.risk, cfg.dd_flat, cfg.iso_frac,
        cfg.cooldown_hours * 60, cfg.ratchet_gain, cfg.ratchet_trail, cfg.heat, cfg.flatten_ratio,
        cfg.entry_scale_below, cfg.entry_scale, gate, np.full(n, 5e8), equity, trace, 1,
    )  # fmt: skip
    return Tape(o, h, low, c, hh[hour], ll[hour], xh[hour], xl[hour], gate, equity, trace)


def _kernel_move(prev: tuple[float, float], now: tuple[float, float]) -> str:
    (s0, q0), (s1, q1) = prev, now
    if s0 == 0 and s1 != 0:
        return "enter"
    if s0 != 0 and s1 == 0:
        return "exit"
    if s0 != 0 and s1 == -s0:
        return "reverse"
    if s0 != 0 and s1 == s0 and q1 > q0 + 1e-9:
        return "add"
    return "none"


def _snapshot(tape: Tape, i: int, side: float, qty: float, entry: float) -> Snapshot:
    return Snapshot(
        known=True, reason="", position_qty=side * qty, entry_price=entry, wallet_usdt=0.0,
        available_usdt=0.0, mark_price=float(tape.c[i]), last_price=float(tape.c[i]),
        liquidation_price=0.0, one_way=True, isolated=True, leverage=20, symbol_status="TRADING",
        server_time_ms=0, can_trade=True, fee_taker=0.0004, filters=None, brackets_ok=True,
        recent_trades_ok=True, funding_ok=True,
    )  # fmt: skip


def _observe(book: Book, tape: Tape, i: int, store: Store, cfg: AccountConfig) -> None:
    """What the runner sees at a minute close. A reversal is flat between its two legs in production."""
    side, qty, _stop, _wallet, entry = (float(x) for x in tape.trace[i])
    now = T0 + i * 60_000
    if i > 0 and side * float(tape.trace[i - 1, 0]) < 0:
        _absorb(book, _snapshot(tape, i, 0.0, 0.0, 0.0), cfg, now, store)
    _absorb(book, _snapshot(tape, i, side, qty, entry), cfg, now, store)


def _drive(
    cfg: AccountConfig, tape: Tape, tmp: Path, restart_at: frozenset[int] = frozenset()
) -> list[tuple[int, str]]:
    """Events the forward policy produces, checked against the kernel as it goes."""
    events: list[tuple[int, str]] = []
    store = Store(tmp, "demo")
    book = Book()
    book.peak_equity_cny = book.close_peak_cny = float(tape.equity[0])
    n = len(tape.c)
    try:
        for i in range(n - 1):
            _observe(book, tape, i, store, cfg)
            equity = float(tape.equity[i])
            book.close_peak_cny = max(book.close_peak_cny, equity)
            book.peak_equity_cny = max(book.peak_equity_cny, equity)
            if i in restart_at:
                store.save_book(book)
                store.close()
                store = Store(tmp, "demo")
                book = store.load_book()
            now_ms = T0 + i * 60_000
            action = decide(
                book, close=float(tape.c[i]), high=float(tape.h[i]), low=float(tape.low[i]),
                hh=float(tape.hh[i]), ll=float(tape.ll[i]), xh=float(tape.xh[i]), xl=float(tape.xl[i]),
                equity_cny=equity, equity_usd=equity / FX, now_ms=now_ms, cfg=cfg, hard_notional=0.0,
                gate_open=bool(tape.gate[i]),
            )  # fmt: skip
            if action.stop > 0 and book.side != 0:
                book.stop = action.stop
            if book.side != 0:
                # The exchange reports the liquidation price; the kernel derives it from its margin model.
                margin = book.entry * book.qty / cfg.leverage
                for px in (tape.o[i], tape.low[i], tape.h[i], tape.c[i]):
                    liq = float(_liq_price(book.side, book.entry, book.qty, margin, float(px)))
                    book.stop = clamp_to_liquidation(book.side, book.stop, liq)
            if book.side != 0 and float(tape.trace[i, 0]) == book.side:
                kernel_stop = float(tape.trace[i, 2])
                assert book.stop == pytest.approx(kernel_stop, rel=1e-6), (
                    f"minute {i}: forward stop {book.stop}, kernel stop {kernel_stop}"
                )
            if book.side > 0 and tape.h[i] > book.extreme:
                book.extreme = float(tape.h[i])
            elif book.side < 0 and (book.extreme == 0.0 or tape.low[i] < book.extreme):
                book.extreme = float(tape.low[i])
            prev = (float(tape.trace[i, 0]), float(tape.trace[i, 1]))
            nxt = (float(tape.trace[i + 1, 0]), float(tape.trace[i + 1, 1]))
            move = _kernel_move(prev, nxt)
            if move == "exit" and action.kind not in {"exit", "reverse"}:
                stop = float(tape.trace[i, 2])
                touched = tape.low[i + 1] <= stop if prev[0] > 0 else tape.h[i + 1] >= stop
                assert touched, f"minute {i}: the kernel closed without a channel exit or a reachable stop"
                book.cooldown_until_ms = T0 + (i + 1) * 60_000 + cfg.cooldown_hours * 3_600_000
                events.append((i + 1, "stop"))
                continue
            expected = {"none": {"hold", "update_stop"}, "enter": {"enter"}, "add": {"add"}, "exit": {"exit"}}.get(move)
            if move == "reverse":
                expected = {"reverse"}
            assert expected is not None
            assert action.kind in expected, f"minute {i}: forward {action.kind}, kernel {move}"
            if move in {"enter", "add"}:
                assert action.side == nxt[0]
                added = nxt[1] - (prev[1] if move == "add" else 0.0)
                # Sizing prices differ by design: the policy sizes at the signal close, the kernel at the fill open.
                assert action.qty == pytest.approx(added, rel=0.02), f"minute {i}: size {action.qty} vs {added}"
                book.swaps["unit_from"] = f"m{i}"
            if move != "none":
                events.append((i + 1, move))
            if move in {"exit", "reverse"}:
                book.stop = 0.0
    finally:
        store.close()
    return events


def _cfg(entry: int = 24, exit_: int = 8, **over: float) -> AccountConfig:
    return replace(load_config(), entry_hours=entry, exit_hours=exit_, **over)


@pytest.mark.parametrize(
    ("vol", "entry", "exit_", "seed", "needed"),
    [
        (0.0008, 24, 8, 3, {"enter", "add", "exit"}),
        (0.0015, 12, 4, 1, {"enter", "add", "exit", "stop"}),
        (0.003, 8, 4, 1, {"enter", "add", "exit", "stop"}),
        (0.002, 6, 6, 2, {"enter", "add", "exit", "stop", "reverse"}),
        (0.0015, 10, 10, 5, {"enter", "add", "exit", "stop", "reverse"}),
    ],
)
def test_decisions_and_stops_match_the_kernel_minute_by_minute(
    vol: float, entry: int, exit_: int, seed: int, needed: set[str], tmp_path: Path
) -> None:
    cfg = _cfg(entry, exit_)
    events = _drive(cfg, _replay(cfg, seed, vol), tmp_path)
    assert needed <= {kind for _minute, kind in events}


def test_a_restart_in_the_middle_changes_no_decision(tmp_path: Path) -> None:
    cfg = _cfg(6, 6)
    tape = _replay(cfg, 2, 0.002)
    plain = _drive(cfg, tape, tmp_path / "a")
    restarted = _drive(cfg, tape, tmp_path / "b", frozenset(range(500, len(tape.c) - 1, 977)))
    assert plain == restarted


@pytest.mark.parametrize("dd_flat", [0.08, 0.3])
def test_the_drawdown_lock_stops_new_risk_like_the_kernel(dd_flat: float, tmp_path: Path) -> None:
    cfg = _cfg(6, 6, dd_flat=dd_flat)
    tape = _replay(cfg, 1, 0.002)
    events = _drive(cfg, tape, tmp_path)
    last_open = max((minute for minute, kind in events if kind in {"enter", "add", "reverse"}), default=0)
    assert 0 < last_open < len(tape.c) - 60 * 24 * 10, "the lock is absorbing: nothing opens near the end of the tape"
