"""Research replay: turtle pyramid with path-ordered equity marks.

Private research only. See LICENSE. This module does not send orders.

Stops are live on the assumed path inside each bar. Peak and trough update in
that order, so a wick that does not trade through the stop still counts as
floating drawdown. A stop is pulled back to the safe side of the tiered
liquidation price. Stop slippage uses the previous completed minute. The
USD/CNY fixing for a date is applied only on later dates. The published account measurement resumes this loop one minute at a time.
``btc_perp.measure`` steps a minute only after a manual session's clock has
completed that minute.
"""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from collections import deque

import numpy as np
from numba import njit

from btc_perp.config import ROOT
from btc_perp.costs import (
    CASH_BUFFER,
    ENTRY_SCALE,
    ENTRY_SCALE_BELOW,
    FX_FEE,
    IMPACT_Y,
    LEVERAGE,
    MAX_NOTIONAL_20X,
    MIN_NOTIONAL,
    SLIP_BASE,
    START_CNY,
    TAKER,
)

DATA_DIR = ROOT / "data"


def rolling_max(a: np.ndarray, w: int) -> np.ndarray:
    out = np.empty_like(a)
    dq: deque[tuple[float, int]] = deque()
    for i, x in enumerate(a):
        while dq and dq[-1][0] <= x:
            dq.pop()
        dq.append((float(x), i))
        while dq[0][1] <= i - w:
            dq.popleft()
        out[i] = dq[0][0]
    return out


def rolling_min(a: np.ndarray, w: int) -> np.ndarray:
    return -rolling_max(-a, w)


def _channels(h, l, entry_w, exit_w):
    hh = np.empty_like(h)
    ll = np.empty_like(l)
    xh = np.empty_like(h)
    xl = np.empty_like(l)
    rh = rolling_max(h, entry_w)
    rl = rolling_min(l, entry_w)
    rxh = rolling_max(h, exit_w)
    rxl = rolling_min(l, exit_w)
    hh[0] = h[0]
    ll[0] = l[0]
    xh[0] = h[0]
    xl[0] = l[0]
    hh[1:] = rh[:-1]
    ll[1:] = rl[:-1]
    xh[1:] = rxh[:-1]
    xl[1:] = rxl[:-1]
    return hh, ll, xh, xl


def causal_fx(days: list[dt.date], rates: dict[dt.date, float], fallback: float = 6.9615) -> np.ndarray:
    """USD/CNY known on each date.

    ``rates`` stores the Frankfurter fixing published for that calendar date.
    A bar on date D uses the latest fixing whose date is strictly earlier, so
    the replay does not use today's rate from midnight. ``fallback`` is the
    2019-12-31 fixing, used only before the first stored date.
    """
    ordered = sorted(rates)
    out = np.empty(len(days))
    j = 0
    current = fallback
    for i, day in enumerate(days):
        while j < len(ordered) and ordered[j] < day:
            current = rates[ordered[j]]
            j += 1
        out[i] = current
    return out


def _bucket8h(ts_ms: int) -> int:
    step = 8 * 3600 * 1000
    return int(round(ts_ms / step) * step)


def load_hourly():
    """Hourly bars, funding, and USD/CNY from ``data/`` next to the repository."""
    d = np.load(DATA_DIR / "btcusdt_1m.npz")
    ts, o, h, l, c = d["ts"], d["o"], d["h"], d["l"], d["c"]
    n = len(c) // 60
    O = o[::60].astype(np.float64)
    H = h.reshape(n, 60).max(1).astype(np.float64)
    L = l.reshape(n, 60).min(1).astype(np.float64)
    C = c[59::60].astype(np.float64)
    TS = ts[::60]
    # Premium approximation is written first. Official prints overwrite it.
    fmap: dict[int, float] = {}
    for f in sorted((DATA_DIR / "premium").glob("*.zip")):
        with zipfile.ZipFile(f) as z:
            with z.open(z.namelist()[0]) as fh:
                for line in fh:
                    if line.startswith(b"open_time"):
                        continue
                    p = line.split(b",")
                    ot = int(p[0])
                    avg = sum(map(float, p[1:5])) / 4
                    adj = min(0.0005, max(-0.0005, 0.0001 - avg))
                    rate = min(0.003, max(-0.003, avg + adj))
                    fmap[_bucket8h(ot + 8 * 3600 * 1000)] = rate
    fund_z = np.load(DATA_DIR / "funding.npz")
    for t, r in zip(fund_z["ts"], fund_z["rate"], strict=True):
        fmap[_bucket8h(int(t))] = float(r)
    fund = np.array([fmap.get(int(t), 0.0) for t in TS], np.float64)
    raw = json.loads((DATA_DIR / "usdcny_frankfurter.json").read_text())
    rates = {dt.date.fromisoformat(k): float(v["CNY"]) for k, v in raw["rates"].items()}
    day_list: list[dt.date] = []
    days = np.empty(n, np.int32)
    for i, t in enumerate(TS):
        day = dt.datetime.fromtimestamp(int(t) / 1000, dt.timezone.utc).date()
        days[i] = day.year * 10000 + day.month * 100 + day.day
        day_list.append(day)
    fx = causal_fx(day_list, rates)
    return O, H, L, C, fund, fx, days


@njit(cache=True)
def _mmr_cum(notional):
    """Maintenance rate and cumulative amount for a BTCUSDT notional."""
    if notional <= 50_000.0:
        return 0.004, 0.0
    if notional <= 250_000.0:
        return 0.005, 50.0
    if notional <= 1_000_000.0:
        return 0.01, 1_300.0
    if notional <= 5_000_000.0:
        return 0.025, 16_300.0
    return 0.05, 141_300.0


@njit(cache=True)
def _liq_from(side, entry, qty, isolated, mmr, cum):
    if side > 0:
        denom = qty * (1.0 - mmr)
        if denom <= 0.0:
            return 0.0
        return (qty * entry - isolated - cum) / denom
    denom = qty * (1.0 + mmr)
    if denom <= 0.0:
        return 0.0
    return (qty * entry + isolated + cum) / denom


@njit(cache=True)
def _liq_price(side, entry, qty, isolated, mark):
    """Isolated liquidation price. The bracket is the one at the liquidation notional."""
    if qty < 0.001 or mark <= 0.0 or entry <= 0.0:
        return 0.0
    mmr, cum = _mmr_cum(qty * mark)
    lp = _liq_from(side, entry, qty, isolated, mmr, cum)
    if lp <= 0.0:
        return 0.0
    mmr2, cum2 = _mmr_cum(qty * lp)
    if mmr2 == mmr and cum2 == cum:
        return lp
    lp2 = _liq_from(side, entry, qty, isolated, mmr2, cum2)
    if lp2 <= 0.0:
        return lp
    return lp2


@njit(cache=True)
def _clamp_stop(side, stop_px, entry, qty, isolated, mark):
    """Keep a resting stop on the safe side of liquidation.

    A long stop below the liquidation price would not be live: the position
    is already closed by the exchange. The 0.1% gap leaves the stop first.
    """
    lp = _liq_price(side, entry, qty, isolated, mark)
    if lp <= 0.0:
        return stop_px
    if side > 0:
        floor = lp * 1.001
        if stop_px < floor:
            return floor
        return stop_px
    ceiling = lp * 0.999
    if stop_px > ceiling:
        return ceiling
    return stop_px


@njit(cache=True)
def _mark(px, wallet, entry, qty, side, fx_i, fx_fee, peak, min_ratio, min_i, i):
    eq = wallet + ((px - entry) * qty * side if side != 0 else 0.0)
    cny = eq * fx_i * (1.0 - fx_fee)
    if cny > peak:
        peak = cny
    ratio = cny / peak if peak > 0.0 else 1.0
    if ratio < min_ratio:
        min_ratio = ratio
        min_i = i
    return peak, min_ratio, min_i


@njit(cache=True)
def _slip_amt(px, qty, hi, lo, qv_i):
    rng = 0.0
    if px > 0.0:
        rng = (hi - lo) / px
    if rng < 0.0:
        rng = 0.0
    denom = qv_i if qv_i > 1.0 else 1.0
    part = (qty * px) / denom
    # The square-root impact model is for an order inside the bar's volume.
    # A zero-volume print would otherwise blow the cost up without a bound.
    if part > 1.0:
        part = 1.0
    if part < 0.0:
        part = 0.0
    return SLIP_BASE + IMPACT_Y * rng * np.sqrt(part)


@njit(cache=True)
def _realize(wallet, raw, pay, isolated):
    """Apply price PnL and funding. The position cannot lose more than its margin.

    Posted margin is the isolated cash still on the position. Once funding has
    reduced that below zero, a later price loss is already outside the posted
    margin: it is not taken again, and the negative margin is not paid back
    as a credit.
    """
    delta = raw - pay
    cap = isolated if isolated > 0.0 else 0.0
    if delta < -cap:
        delta = -cap
    return wallet + delta, delta


@njit(cache=True)
def _tighten(side, extreme, entry, stop_px, trail, ratchet_gain, ratchet_trail):
    if side > 0:
        t_use = trail
        if ratchet_gain > 0.0 and entry > 0.0 and extreme / entry - 1.0 >= ratchet_gain:
            t_use = ratchet_trail
        trailed = extreme * (1.0 - t_use)
        if trailed > stop_px:
            return trailed
        return stop_px
    t_use = trail
    if ratchet_gain > 0.0 and extreme > 0.0 and entry / extreme - 1.0 >= ratchet_gain:
        t_use = ratchet_trail
    trailed = extreme * (1.0 + t_use)
    if side < 0 and trailed < stop_px:
        return trailed
    return stop_px


# Resume book. Integer fields stay on whole numbers, which float64 holds exactly
# for this tape. 0 wallet, 1 side, 2 qty, 3 entry, 4 isolated, 5 stop, 6 extreme,
# 7 units, 8 last_add, 9 cool, 10 peak, 11 peak_c, 12 min_ratio, 13 n_long,
# 14 n_short, 15 n_stop, 16 min_i.
STATE_N = 17


@njit(cache=True)
def _reset(state, fx0):
    state[0] = START_CNY / (fx0 * (1.0 + FX_FEE))
    state[1] = 0.0
    state[2] = 0.0
    state[3] = 0.0
    state[4] = 0.0
    state[5] = 0.0
    state[6] = 0.0
    state[7] = 0.0
    state[8] = 0.0
    state[9] = 0.0
    state[10] = START_CNY
    state[11] = START_CNY
    state[12] = 1.0
    state[13] = 0.0
    state[14] = 0.0
    state[15] = 0.0
    state[16] = 0.0


@njit(cache=True)
def _loop(
    state,
    i0,
    i1,
    O,
    H,
    L,
    C,
    fund,
    fx,
    hh,
    ll,
    xh,
    xl,
    stop,
    trail,
    add_step,
    max_units,
    risk,
    dd_flat,
    iso_frac,
    cool_h,
    ratchet_gain,
    ratchet_trail,
    heat,
    gate,
    qv,
    eq_out,
    trace,
):
    """Replay bars ``[i0, i1)`` and write the book back into ``state``."""
    n = len(C)
    # Fee inputs come from btc_perp.costs. The YAML copy is checked by a test.
    taker = TAKER
    slip_b = SLIP_BASE
    fx_fee = FX_FEE
    lev = LEVERAGE
    wallet = state[0]
    side = int(state[1])
    qty = state[2]
    entry = state[3]
    isolated = state[4]
    stop_px = state[5]
    extreme = state[6]
    units = int(state[7])
    last_add = state[8]
    cool = int(state[9])
    peak = state[10]
    peak_c = state[11]
    min_ratio = state[12]
    nL = int(state[13])
    nS = int(state[14])
    nStop = int(state[15])
    min_i = int(state[16])
    for i in range(i0, i1):
        # Stops can fill before this bar is finished, so impact uses the previous minute.
        if qv.shape[0] == n and qty > 0.0 and i > 0:
            slip_b = _slip_amt(C[i - 1], qty, H[i - 1], L[i - 1], qv[i - 1])
        else:
            slip_b = SLIP_BASE
        if side != 0 and fund[i] != 0.0:
            pay = qty * O[i] * fund[i] * side
            upnl = (O[i] - entry) * qty * side
            mmr, cum = _mmr_cum(qty * O[i])
            maint = qty * O[i] * mmr - cum
            if maint < 0.0:
                maint = 0.0
            # Margin balance includes unrealized PnL. A winner is not liquidated
            # just because funding has used up the cash that was posted.
            if isolated + upnl - pay <= maint:
                fill = O[i] * (1.0 - slip_b) if side > 0 else O[i] * (1.0 + slip_b)
                fee = qty * fill * taker
                raw = (fill - entry) * qty * side - fee
                wallet, _delta = _realize(wallet, raw, pay, isolated)
                isolated = 0.0
                qty = 0.0
                side = 0
                units = 0
                stop_px = 0.0
                nStop += 1
                cool = i + cool_h
            else:
                wallet -= pay
                isolated -= pay
        if side != 0:
            # No 5-second tape exists. A bullish bar is ordered open, low, high,
            # close, so the low is tested before a new high tightens the stop.
            # A bearish bar is open, high, low, close.
            bull = C[i] >= O[i]
            hit = False
            fill = 0.0
            for k in range(4):
                if k == 0:
                    px = O[i]
                elif k == 1:
                    px = L[i] if bull else H[i]
                elif k == 2:
                    px = H[i] if bull else L[i]
                else:
                    px = C[i]
                stop_px = _clamp_stop(side, stop_px, entry, qty, isolated, px)
                if side > 0 and px <= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 - slip_b)
                    break
                if side < 0 and px >= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 + slip_b)
                    break
                if side > 0 and px > extreme:
                    extreme = px
                elif side < 0 and px < extreme:
                    extreme = px
                stop_px = _tighten(side, extreme, entry, stop_px, trail, ratchet_gain, ratchet_trail)
                peak, min_ratio, min_i = _mark(px, wallet, entry, qty, side, fx[i], fx_fee, peak, min_ratio, min_i, i)
            if hit:
                fee = qty * fill * taker
                raw = (fill - entry) * qty * side - fee
                wallet, _delta = _realize(wallet, raw, 0.0, isolated)
                isolated = 0.0
                qty = 0.0
                side = 0
                units = 0
                stop_px = 0.0
                nStop += 1
                cool = i + cool_h
                peak, min_ratio, min_i = _mark(0.0, wallet, 0.0, 0.0, 0, fx[i], fx_fee, peak, min_ratio, min_i, i)
        # Channel exits are not limited to minute 59. Entries and adds are.
        # The close is known, so this fill can use the completed minute.
        if side > 0 and C[i] < xl[i]:
            slip_x = _slip_amt(C[i], qty, H[i], L[i], qv[i]) if qv.shape[0] == n else slip_b
            fill = C[i] * (1.0 - slip_x)
            fee = qty * fill * taker
            raw = (fill - entry) * qty * side - fee
            wallet, _delta = _realize(wallet, raw, 0.0, isolated)
            isolated = 0.0
            qty = 0.0
            side = 0
            units = 0
        elif side < 0 and C[i] > xh[i]:
            slip_x = _slip_amt(C[i], qty, H[i], L[i], qv[i]) if qv.shape[0] == n else slip_b
            fill = C[i] * (1.0 + slip_x)
            fee = qty * fill * taker
            raw = (fill - entry) * qty * side - fee
            wallet, _delta = _realize(wallet, raw, 0.0, isolated)
            isolated = 0.0
            qty = 0.0
            side = 0
            units = 0
        eq = wallet + ((C[i] - entry) * qty * side if side != 0 else 0.0)
        cny = eq * fx[i] * (1.0 - fx_fee)
        if cny > peak:
            peak = cny
        if cny > peak_c:
            peak_c = cny
        ratio_c = cny / peak_c if peak_c > 0.0 else 1.0
        if cny / peak < min_ratio:
            min_ratio = cny / peak
            min_i = i
        if eq_out.shape[0] == n:
            eq_out[i] = cny
        if trace.shape[0] == n:
            trace[i, 0] = side
            trace[i, 1] = qty
            trace[i, 2] = stop_px
            trace[i, 3] = wallet
            trace[i, 4] = entry
        # dd_flat blocks a new entry. It does not flatten the open position.
        if i < cool or ratio_c <= 1.0 - dd_flat:
            continue
        if gate.shape[0] == n and gate[i] == 0:
            continue
        want = 0
        if C[i] > hh[i]:
            want = 1
        elif C[i] < ll[i]:
            want = -1
        if side == 0 and want != 0:
            px = C[i]
            dist = px * stop
            # Same rule as btc_perp.costs.new_entry_scale. Inlined because this
            # loop is compiled. Adds below do not apply it. The published pass
            # depends on it; the rule is not a config field.
            scale = ENTRY_SCALE if ratio_c < ENTRY_SCALE_BELOW else 1.0
            q = np.floor(eq * risk * scale / dist * 1000.0) / 1000.0
            capn = eq * iso_frac * lev
            if heat > 0.0:
                heat_n = eq * heat / trail
                if heat_n < capn:
                    capn = heat_n
            if capn > MAX_NOTIONAL_20X:
                capn = MAX_NOTIONAL_20X
            if q * px > capn:
                q = np.floor(capn / px * 1000.0) / 1000.0
            if q >= 0.001 and q * px >= MIN_NOTIONAL:
                es = _slip_amt(px, q, H[i], L[i], qv[i]) if qv.shape[0] == n else SLIP_BASE
                fill = px * (1.0 + es) if want > 0 else px * (1.0 - es)
                fee = q * fill * taker
                iso = q * fill / lev
                if iso + fee < wallet * (1.0 - CASH_BUFFER):
                    wallet -= fee
                    side = want
                    qty = q
                    entry = fill
                    isolated = iso
                    units = 1
                    extreme = fill
                    last_add = fill
                    stop_px = fill * (1.0 - stop) if want > 0 else fill * (1.0 + stop)
                    stop_px = _clamp_stop(want, stop_px, fill, q, iso, px)
                    if want > 0:
                        nL += 1
                    else:
                        nS += 1
        elif side != 0 and units < max_units:
            px = C[i]
            trig = (side > 0 and px >= last_add * (1.0 + add_step)) or (side < 0 and px <= last_add * (1.0 - add_step))
            if trig:
                dist = max(px * stop, px * 0.005)
                eq_now = wallet + (px - entry) * qty * side
                qadd = np.floor(eq_now * risk / dist * 1000.0) / 1000.0
                capn = eq_now * iso_frac * lev
                if heat > 0.0:
                    heat_n = eq_now * heat / trail
                    if heat_n < capn:
                        capn = heat_n
                if capn > MAX_NOTIONAL_20X:
                    capn = MAX_NOTIONAL_20X
                room = capn / px - qty
                if qadd > room:
                    qadd = np.floor(max(room, 0.0) * 1000.0) / 1000.0
                if qadd >= 0.001:
                    es = _slip_amt(px, qadd, H[i], L[i], qv[i]) if qv.shape[0] == n else slip_b
                    fill = px * (1.0 + es) if side > 0 else px * (1.0 - es)
                    fee = qadd * fill * taker
                    iso_add = qadd * fill / lev
                    posted = isolated if isolated > 0.0 else 0.0
                    if wallet - posted > iso_add + fee:
                        wallet -= fee
                        entry = (entry * qty + fill * qadd) / (qty + qadd)
                        qty += qadd
                        isolated += iso_add
                        units += 1
                        last_add = fill
                        if side > 0:
                            if fill > extreme:
                                extreme = fill
                            be = fill / (1.0 + add_step)
                            if be > stop_px:
                                stop_px = be
                        else:
                            if fill < extreme:
                                extreme = fill
                            be = fill / (1.0 - add_step)
                            if be < stop_px:
                                stop_px = be
                    stop_px = _clamp_stop(side, stop_px, entry, qty, isolated, px)
        # The decision above used pre-trade equity. Record the book after the fill
        # so the stored curve includes the fee and the new position.
        eq_now = wallet + ((C[i] - entry) * qty * side if side != 0 else 0.0)
        cny_now = eq_now * fx[i] * (1.0 - fx_fee)
        if peak > 0.0 and cny_now / peak < min_ratio:
            min_ratio = cny_now / peak
            min_i = i
        if eq_out.shape[0] == n:
            eq_out[i] = cny_now
    state[0] = wallet
    state[1] = side
    state[2] = qty
    state[3] = entry
    state[4] = isolated
    state[5] = stop_px
    state[6] = extreme
    state[7] = units
    state[8] = last_add
    state[9] = cool
    state[10] = peak
    state[11] = peak_c
    state[12] = min_ratio
    state[13] = nL
    state[14] = nS
    state[15] = nStop
    state[16] = min_i
    last = i1 - 1
    eq = wallet + ((C[last] - entry) * qty * side if side != 0 else 0.0)
    end = eq * fx[last] * (1.0 - fx_fee)
    return end


@njit(cache=True)
def run(
    O,
    H,
    L,
    C,
    fund,
    fx,
    hh,
    ll,
    xh,
    xl,
    stop,
    trail,
    add_step,
    max_units,
    risk,
    dd_flat,
    iso_frac,
    cool_h,
    ratchet_gain,
    ratchet_trail,
    heat,
    gate,
    qv,
    eq_out,
    trace,
):
    """Replay the whole tape from a flat book."""
    n = len(C)
    state = np.empty(STATE_N, dtype=np.float64)
    _reset(state, fx[0])
    end = _loop(
        state,
        0,
        n,
        O,
        H,
        L,
        C,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        stop,
        trail,
        add_step,
        max_units,
        risk,
        dd_flat,
        iso_frac,
        cool_h,
        ratchet_gain,
        ratchet_trail,
        heat,
        gate,
        qv,
        eq_out,
        trace,
    )
    return end, state[12], int(state[13]), int(state[14]), int(state[15]), int(state[16])


def initial_state(fx0: float) -> np.ndarray:
    """Flat book, before any minute has been replayed."""
    state = np.empty(STATE_N, dtype=np.float64)
    _reset(state, fx0)
    return state


def resume(
    state: np.ndarray,
    i0: int,
    i1: int,
    O: np.ndarray,
    H: np.ndarray,
    L: np.ndarray,
    C: np.ndarray,
    fund: np.ndarray,
    fx: np.ndarray,
    hh: np.ndarray,
    ll: np.ndarray,
    xh: np.ndarray,
    xl: np.ndarray,
    stop: float,
    trail: float,
    add_step: float,
    max_units: int,
    risk: float,
    dd_flat: float,
    iso_frac: float,
    cool_h: int,
    ratchet_gain: float,
    ratchet_trail: float,
    heat: float,
    gate: np.ndarray,
    qv: np.ndarray,
    eq_out: np.ndarray,
    trace: np.ndarray,
) -> tuple[float, float, int, int, int, int]:
    """Replay ``[i0, i1)`` on an existing book.

    Index 0 rebuilds the starting wallet. A later slice keeps ``state``.
    """
    if i0 == 0:
        _reset(state, float(fx[0]))
    end = _loop(
        state,
        i0,
        i1,
        O,
        H,
        L,
        C,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        stop,
        trail,
        add_step,
        max_units,
        risk,
        dd_flat,
        iso_frac,
        cool_h,
        ratchet_gain,
        ratchet_trail,
        heat,
        gate,
        qv,
        eq_out,
        trace,
    )
    return float(end), float(state[12]), int(state[13]), int(state[14]), int(state[15]), int(state[16])
