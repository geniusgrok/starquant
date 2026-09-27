"""Frontier search: turtle pyramid with path-ordered equity marks.

Stops are live. Peak and trough update in OHLC order, so a wick that does not
trade through the stop still counts as floating drawdown.
"""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
from numba import njit


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


def load_hourly():
    d = np.load("/workspace/data/btcusdt_1m.npz")
    ts, o, h, l, c = d["ts"], d["o"], d["h"], d["l"], d["c"]
    n = len(c) // 60
    O = o[::60].astype(np.float64)
    H = h.reshape(n, 60).max(1).astype(np.float64)
    L = l.reshape(n, 60).min(1).astype(np.float64)
    C = c[59::60].astype(np.float64)
    TS = ts[::60]
    fund_z = np.load("/workspace/data/funding.npz")
    pairs = [(int(t), float(r)) for t, r in zip(fund_z["ts"], fund_z["rate"])]
    for f in sorted(Path("/workspace/data/premium").glob("*.zip")):
        with zipfile.ZipFile(f) as z:
            with z.open(z.namelist()[0]) as fh:
                for line in fh:
                    if line.startswith(b"open_time"):
                        continue
                    p = line.split(b",")
                    ot = int(p[0])
                    avg = sum(map(float, p[1:5])) / 4
                    adj = min(0.0005, max(-0.0005, 0.0001 - avg))
                    pairs.append((ot + 8 * 3600 * 1000, min(0.003, max(-0.003, avg + adj))))
    fmap = {}
    for t, r in pairs:
        fmap[int(round(t / (8 * 3600 * 1000)) * 8 * 3600 * 1000)] = r
    fund = np.array([fmap.get(int(t), 0.0) for t in TS], np.float64)
    raw = json.loads(Path("/workspace/data/usdcny_frankfurter.json").read_text())
    rates = {dt.date.fromisoformat(k): float(v["CNY"]) for k, v in raw["rates"].items()}
    fx = np.empty(n)
    last = 6.9615
    days = np.empty(n, np.int32)
    for i, t in enumerate(TS):
        day = dt.datetime.fromtimestamp(int(t) / 1000, dt.timezone.utc).date()
        days[i] = day.year * 10000 + day.month * 100 + day.day
        if day in rates:
            last = rates[day]
        fx[i] = last
    return O, H, L, C, fund, fx, days


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
    return 0.0001 + 0.5 * rng * np.sqrt((qty * px) / denom)


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
    long_only,
    cool_h,
    flatten_at,
    ratchet_gain,
    ratchet_trail,
    trail_stride,
    streak_cut,
    buf,
    adverse,
    post_scale,
    heat,
    step,
    gate,
    qv,
    eq_out,
    trace,
    peak_out,
):
    """streak_cut: after this many losing exits, risk halves until a win.
    buf: close must clear the channel by this fraction.
    adverse: 1 marks OHLC path extremes, 0 marks closes only.
    post_scale: risk multiplier until a new equity peak after an equity flatten.
    """
    n = len(C)
    taker = 0.0004
    slip_b = 0.0001
    fx_fee = 0.0035
    lev = 20.0
    wallet = 10000.0 / (fx[0] * (1.0 + fx_fee))
    side = 0
    qty = 0.0
    entry = 0.0
    isolated = 0.0
    stop_px = 0.0
    extreme = 0.0
    units = 0
    last_add = 0.0
    cool = 0
    peak = 10000.0
    peak_c = 10000.0
    min_ratio = 1.0
    nL = 0
    nS = 0
    nStop = 0
    min_i = 0
    losses = 0
    scale_hold = 1.0
    for i in range(n):
        if qv.shape[0] == n and qty > 0.0:
            slip_b = _slip_amt(C[i], qty, H[i], L[i], qv[i])
        else:
            slip_b = 0.0001
        if side != 0 and fund[i] != 0.0:
            pay = qty * O[i] * fund[i] * side
            wallet -= pay
            isolated -= pay
            if isolated <= qty * O[i] * 0.004:
                if isolated > 0.0:
                    wallet -= isolated
                elif isolated < 0.0:
                    wallet -= isolated
                isolated = 0.0
                qty = 0.0
                side = 0
                units = 0
                stop_px = 0.0
                nStop += 1
                losses += 1
                cool = i + cool_h
        if side != 0 and adverse == 1:
            # 5-second sessions amend the trail as soon as a new extreme prints,
            # then the rest of the bar can fill that stop. Bullish bar: O-L-H-C.
            bull = C[i] >= O[i]
            hit = False
            fill = 0.0
            # Negative trail_stride trails the close only, on bars where i % stride == 0.
            close_only = trail_stride < 0
            stride = -trail_stride if close_only else trail_stride
            if stride <= 1:
                allow = True
            elif close_only:
                allow = (i % stride) == (stride - 1)
            else:
                allow = (i % stride) == 0
            for k in range(4):
                if k == 0:
                    px = O[i]
                elif k == 1:
                    px = L[i] if bull else H[i]
                elif k == 2:
                    px = H[i] if bull else L[i]
                else:
                    px = C[i]
                if side > 0 and px <= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 - slip_b)
                    break
                if side < 0 and px >= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 + slip_b)
                    break
                track = (k == 3) if close_only else True
                if track and side > 0 and px > extreme and (step <= 0.0 or px >= extreme * (1.0 + step)):
                    extreme = px
                elif track and side < 0 and px < extreme and (step <= 0.0 or px <= extreme * (1.0 - step)):
                    extreme = px
                if track and allow:
                    stop_px = _tighten(side, extreme, entry, stop_px, trail, ratchet_gain, ratchet_trail)
                peak, min_ratio, min_i = _mark(px, wallet, entry, qty, side, fx[i], fx_fee, peak, min_ratio, min_i, i)
            if hit:
                fee = qty * fill * taker
                raw = (fill - entry) * qty * side - fee
                cap = isolated if isolated > 0.0 else 0.0
                if raw < -cap:
                    raw = -cap
                wallet += raw
                if raw < 0.0:
                    losses += 1
                else:
                    losses = 0
                isolated = 0.0
                qty = 0.0
                side = 0
                units = 0
                stop_px = 0.0
                nStop += 1
                cool = i + cool_h
                peak, min_ratio, min_i = _mark(0.0, wallet, 0.0, 0.0, 0, fx[i], fx_fee, peak, min_ratio, min_i, i)
        elif side != 0:
            hit = False
            fill = 0.0
            if side > 0:
                if O[i] <= stop_px:
                    hit = True
                    fill = O[i] * (1.0 - slip_b)
                elif L[i] <= stop_px:
                    hit = True
                    fill = stop_px * (1.0 - slip_b)
            else:
                if O[i] >= stop_px:
                    hit = True
                    fill = O[i] * (1.0 + slip_b)
                elif H[i] >= stop_px:
                    hit = True
                    fill = stop_px * (1.0 + slip_b)
            if hit:
                fee = qty * fill * taker
                raw = (fill - entry) * qty * side - fee
                cap = isolated if isolated > 0.0 else 0.0
                if raw < -cap:
                    raw = -cap
                wallet += raw
                if raw < 0.0:
                    losses += 1
                else:
                    losses = 0
                isolated = 0.0
                qty = 0.0
                side = 0
                units = 0
                stop_px = 0.0
                nStop += 1
                cool = i + cool_h
            else:
                if side > 0 and H[i] > extreme:
                    extreme = H[i]
                elif side < 0 and L[i] < extreme:
                    extreme = L[i]
                if trail_stride <= 1 or (i % trail_stride) == 0:
                    if side > 0:
                        t_use = trail
                        if ratchet_gain > 0.0 and entry > 0.0 and extreme / entry - 1.0 >= ratchet_gain:
                            t_use = ratchet_trail
                        trailed = extreme * (1.0 - t_use)
                        if trailed > stop_px:
                            stop_px = trailed
                    elif side < 0:
                        t_use = trail
                        if ratchet_gain > 0.0 and extreme > 0.0 and entry / extreme - 1.0 >= ratchet_gain:
                            t_use = ratchet_trail
                        trailed = extreme * (1.0 + t_use)
                        if trailed < stop_px:
                            stop_px = trailed
        if side > 0 and C[i] < xl[i]:
            fill = C[i] * (1.0 - slip_b)
            fee = qty * fill * taker
            raw = (fill - entry) * qty * side - fee
            cap = isolated if isolated > 0.0 else 0.0
            if raw < -cap:
                raw = -cap
            wallet += raw
            if raw < 0.0:
                losses += 1
            else:
                losses = 0
            isolated = 0.0
            qty = 0.0
            side = 0
            units = 0
        elif side < 0 and C[i] > xh[i]:
            fill = C[i] * (1.0 + slip_b)
            fee = qty * fill * taker
            raw = (fill - entry) * qty * side - fee
            cap = isolated if isolated > 0.0 else 0.0
            if raw < -cap:
                raw = -cap
            wallet += raw
            if raw < 0.0:
                losses += 1
            else:
                losses = 0
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
            scale_hold = 1.0
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
        if peak_out.shape[0] == n:
            peak_out[i] = peak
        if side != 0 and flatten_at > 0.0 and ratio_c <= 1.0 - flatten_at:
            fill = C[i] * (1.0 - slip_b) if side > 0 else C[i] * (1.0 + slip_b)
            fee = qty * fill * taker
            raw = (fill - entry) * qty * side - fee
            cap = isolated if isolated > 0.0 else 0.0
            if raw < -cap:
                raw = -cap
            wallet += raw
            if raw < 0.0:
                losses += 1
            isolated = 0.0
            qty = 0.0
            side = 0
            units = 0
            stop_px = 0.0
            cool = i + cool_h
            scale_hold = post_scale
            eq = wallet
            cny = eq * fx[i] * (1.0 - fx_fee)
            if cny > peak:
                peak = cny
            if cny > peak_c:
                peak_c = cny
                scale_hold = 1.0
            ratio_c = cny / peak_c if peak_c > 0.0 else 1.0
            if cny / peak < min_ratio:
                min_ratio = cny / peak
            if eq_out.shape[0] == n:
                eq_out[i] = cny
        if i < cool or ratio_c <= 1.0 - dd_flat:
            continue
        if gate.shape[0] == n and gate[i] == 0:
            continue
        want = 0
        up = hh[i] * (1.0 + buf)
        dn = ll[i] * (1.0 - buf)
        if C[i] > up:
            want = 1
        elif C[i] < dn and long_only == 0:
            want = -1
        rscale = scale_hold
        if streak_cut > 0 and losses >= streak_cut:
            rscale *= 0.5
        if side == 0 and want != 0:
            px = C[i]
            dist = px * stop
            scale = 0.5 if ratio_c < 0.82 else 1.0
            scale *= rscale
            q = np.floor(eq * risk * scale / dist * 1000.0) / 1000.0
            capn = eq * iso_frac * lev
            if heat > 0.0:
                heat_n = eq * heat / trail
                if heat_n < capn:
                    capn = heat_n
            if q * px > capn:
                q = np.floor(capn / px * 1000.0) / 1000.0
            if q >= 0.001 and q * px >= 100.0:
                es = _slip_amt(px, q, H[i], L[i], qv[i]) if qv.shape[0] == n else 0.0001
                fill = px * (1.0 + es) if want > 0 else px * (1.0 - es)
                fee = q * fill * taker
                iso = q * fill / lev
                if iso + fee < wallet * 0.98:
                    wallet -= fee
                    side = want
                    qty = q
                    entry = fill
                    isolated = iso
                    units = 1
                    extreme = fill
                    last_add = fill
                    stop_px = fill * (1.0 - stop) if want > 0 else fill * (1.0 + stop)
                    if want > 0:
                        lp = (fill * q - iso) / (q * 0.996)
                        if stop_px < lp * 1.01:
                            stop_px = lp * 1.01
                        nL += 1
                    else:
                        lp = (iso + fill * q) / (q * 1.004)
                        if stop_px > lp * 0.99:
                            stop_px = lp * 0.99
                        nS += 1
        elif side != 0 and units < max_units:
            px = C[i]
            trig = (side > 0 and px >= last_add * (1.0 + add_step)) or (side < 0 and px <= last_add * (1.0 - add_step))
            if trig:
                dist = max(px * stop, px * 0.005)
                eq_now = wallet + (px - entry) * qty * side
                qadd = np.floor(eq_now * risk * rscale / dist * 1000.0) / 1000.0
                capn = eq_now * iso_frac * lev
                if heat > 0.0:
                    heat_n = eq_now * heat / trail
                    if heat_n < capn:
                        capn = heat_n
                room = capn / px - qty
                if qadd > room:
                    qadd = np.floor(max(room, 0.0) * 1000.0) / 1000.0
                if qadd >= 0.001:
                    es = _slip_amt(px, qadd, H[i], L[i], qv[i]) if qv.shape[0] == n else slip_b
                    fill = px * (1.0 + es) if side > 0 else px * (1.0 - es)
                    fee = qadd * fill * taker
                    iso_add = qadd * fill / lev
                    if wallet - isolated > iso_add + fee:
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
    eq = wallet + ((C[-1] - entry) * qty * side if side != 0 else 0.0)
    end = eq * fx[-1] * (1.0 - fx_fee)
    return end, min_ratio, nL, nS, nStop, min_i


def report(tag, end, ratio, nL, nS, nStop, years, eq, days):
    g = (end / 10000.0) ** (1 / years) - 1 if end > 0 else -1
    print(f"{tag} cagr={g:.3f} end={end:,.0f} ratio={ratio:.3f} L={nL} S={nS} stops={nStop}")
    if eq.shape[0] > 1:
        # year-end equity
        seen = {}
        for i, d in enumerate(days):
            seen[int(d) // 10000] = eq[i]
        prev = 10000.0
        for y in sorted(seen):
            e = seen[y]
            print(f"  {y} {e:,.0f} {(e / prev - 1):.1%}")
            prev = e
        imin = int(np.argmin(eq / np.maximum.accumulate(eq)))
        print(f"  min_i={imin} day={int(days[imin])} eq={eq[imin]:,.0f} peak={np.maximum.accumulate(eq)[imin]:,.0f}")


def main():
    O, H, L, C, fund, fx, days = load_hourly()
    years = 2454 / 365.25
    print("hours", len(C), "fund_nz", int(np.count_nonzero(fund)))
    cache = {}

    def channels(entry_h, exit_h):
        key = (entry_h, exit_h)
        if key not in cache:
            cache[key] = _channels(H, L, entry_h, exit_h)
        return cache[key]

    # Reproduce the known hourly neighborhood, close-only vs adverse.
    base = dict(
        stop=0.032,
        trail=0.16,
        add=0.05,
        units=3,
        risk=0.05,
        dd=0.495,
        iso=0.22,
        long_only=0,
        cool=6,
        flat=0.0,
        rg=0.45,
        rt=0.08,
        stride=1,
        streak=0,
        buf=0.0,
        post=1.0,
    )
    for eh, xh in ((984, 192), (960, 192), (1008, 192), (720, 192)):
        hh, ll, xh_a, xl = channels(eh, xh)
        for adverse in (0, 1):
            eq = np.empty(len(C))
            end, ratio, nL, nS, nStop, min_i = run(
                O,
                H,
                L,
                C,
                fund,
                fx,
                hh,
                ll,
                xh_a,
                xl,
                base["stop"],
                base["trail"],
                base["add"],
                base["units"],
                base["risk"],
                base["dd"],
                base["iso"],
                base["long_only"],
                base["cool"],
                base["flat"],
                base["rg"],
                base["rt"],
                base["stride"],
                base["streak"],
                base["buf"],
                adverse,
                base["post"],
                0.0,
                0.0,
                np.empty(1, np.int8),
                np.empty(1),
                eq,
                np.empty((1, 4)),
                np.empty(1),
            )
            report(f"eh={eh} adv={adverse}", end, ratio, nL, nS, nStop, years, eq, days)
            print(f"  path_min_i={min_i} day={int(days[min_i])}")

    print("--- heat / trail / risk ---")
    rows = []
    grid = []
    for eh in (960, 1008, 840, 720):
        for risk in (0.045, 0.055, 0.07, 0.09):
            for trail in (0.10, 0.12, 0.16):
                for heat in (0.0, 0.28, 0.36, 0.45):
                    for rg, rt in ((0.35, 0.06), (0.45, 0.08), (0.25, 0.05)):
                        grid.append((eh, risk, trail, heat, rg, rt))
    print("grid", len(grid))
    for eh, risk, trail, heat, rg, rt in grid:
        hh, ll, xh_a, xl = channels(eh, 192)
        end, ratio, nL, nS, nStop, min_i = run(
            O,
            H,
            L,
            C,
            fund,
            fx,
            hh,
            ll,
            xh_a,
            xl,
            0.032,
            trail,
            0.05,
            3,
            risk,
            0.48,
            0.25,
            0,
            6,
            0.0,
            rg,
            rt,
            1,
            0,
            0.0,
            1,
            1.0,
            heat,
            0.0,
            np.empty(1, np.int8),
            np.empty(1),
            np.empty(1),
            np.empty((1, 4)),
            np.empty(1),
        )
        g = (end / 10000.0) ** (1 / years) - 1 if end > 0 else -1
        rows.append((g, end, ratio, nL, nS, nStop, min_i, eh, risk, trail, heat, rg, rt))
    rows.sort(key=lambda r: (r[2] > 0.5 and r[0] >= 1.0, r[0]), reverse=True)
    valid = [r for r in rows if r[2] > 0.5 and r[0] >= 1.0]
    print("valid", len(valid), "of", len(rows))
    print("BEST ANY")
    for r in sorted(rows, reverse=True)[:6]:
        print(
            f"cagr={r[0]:.3f} end={r[1]:,.0f} ratio={r[2]:.3f} L={r[3]} S={r[4]} "
            f"day={int(days[r[6]])} eh={r[7]} risk={r[8]} trail={r[9]} heat={r[10]} rg={r[11]} rt={r[12]}"
        )
    print("BEST RATIO>0.5")
    ok = [r for r in rows if r[2] > 0.5]
    ok.sort(reverse=True)
    for r in ok[:8]:
        print(
            f"cagr={r[0]:.3f} end={r[1]:,.0f} ratio={r[2]:.3f} L={r[3]} S={r[4]} "
            f"day={int(days[r[6]])} eh={r[7]} risk={r[8]} trail={r[9]} heat={r[10]} rg={r[11]} rt={r[12]}"
        )
    print("VALID")
    for r in valid[:8]:
        print(
            f"cagr={r[0]:.3f} end={r[1]:,.0f} ratio={r[2]:.3f} L={r[3]} S={r[4]} "
            f"day={int(days[r[6]])} eh={r[7]} risk={r[8]} trail={r[9]} heat={r[10]} rg={r[11]} rt={r[12]}"
        )


if __name__ == "__main__":
    main()
