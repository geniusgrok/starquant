"""Candidate model: an ensemble of Donchian trend sleeves, sized by volatility.

Research only. It is not wired to the forward loop. The point is fewer tuned
settings and no cliff: four channel lengths share one signal, size follows a
volatility target, the stop is a multiple of the average daily range, and the
drawdown control scales risk down smoothly against a rolling peak, so a bad
stretch ends. Fills, costs, funding, margin and the intrabar stop path follow
the baseline replay in ``scripts.frontier``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import yaml
from numba import njit

from btc_perp.config import ROOT
from btc_perp.costs import CASH_BUFFER, FX_FEE, MIN_NOTIONAL, START_CNY, TAKER
from btc_perp.tapes import Tape
from scripts.frontier import (
    _channels,
    _clamp_stop,
    _mark,
    _mmr_cum,
    _realize,
    _slip_amt,
    rolling_max,
    rolling_min,
)

HOURS_PER_YEAR = 8760.0


@dataclass(frozen=True)
class CandidateConfig:
    lookback_days: tuple[int, ...]
    exit_fraction: float
    target_vol: float
    atr_mult: float
    max_leverage: float
    leverage: float
    vol_days: int
    atr_days: int
    dd_window_days: int
    dd_soft: float
    dd_floor: float
    band: float
    cooldown_hours: int
    flatten_ratio: float


def load_candidate() -> CandidateConfig:
    raw = yaml.safe_load((ROOT / "config" / "candidate.yaml").read_text())
    return CandidateConfig(
        lookback_days=tuple(int(x) for x in raw["lookback_days"]),
        exit_fraction=float(raw["exit_fraction"]),
        target_vol=float(raw["target_vol"]),
        atr_mult=float(raw["atr_mult"]),
        max_leverage=float(raw["max_leverage"]),
        leverage=float(raw["leverage"]),
        vol_days=int(raw["vol_days"]),
        atr_days=int(raw["atr_days"]),
        dd_window_days=int(raw["dd_window_days"]),
        dd_soft=float(raw["dd_soft"]),
        dd_floor=float(raw["dd_floor"]),
        band=float(raw["band"]),
        cooldown_hours=int(raw["cooldown_hours"]),
        flatten_ratio=float(raw["flatten_ratio"]),
    )


def _rolling_mean(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    if len(a) < w:
        return out
    csum = np.cumsum(np.insert(a, 0, 0.0))
    out[w - 1 :] = (csum[w:] - csum[:-w]) / w
    return out


def indicators(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, cfg: CandidateConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Hourly channel levels, ATR and volatility. Channels are lagged one hour; ATR and vol use the hour itself."""
    nh = len(close)
    k = len(cfg.lookback_days)
    hhk = np.empty((k, nh))
    llk = np.empty((k, nh))
    xhk = np.empty((k, nh))
    xlk = np.empty((k, nh))
    for j, days in enumerate(cfg.lookback_days):
        entry = days * 24
        exit_ = max(int(entry * cfg.exit_fraction), 1)
        hhk[j], llk[j], xhk[j], xlk[j] = _channels(high, low, entry, exit_)
    rng24 = rolling_max(high, 24) - rolling_min(low, 24)
    rng24[:23] = 0.0
    atr = _rolling_mean(rng24, cfg.atr_days * 24)
    atr[: 23 + cfg.atr_days * 24 - 1] = np.nan
    ret = np.zeros(nh)
    ret[1:] = np.diff(np.log(close))
    w = cfg.vol_days * 24
    mean = _rolling_mean(ret, w)
    mean_sq = _rolling_mean(ret * ret, w)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    vol = np.sqrt(var) * np.sqrt(HOURS_PER_YEAR)
    vol[: w - 1] = np.nan
    return hhk, llk, xhk, xlk, atr, vol


@njit(cache=True)
def _loop(  # type: ignore[no-untyped-def]
    i0,
    i1,
    OP,
    H,
    L,
    C,
    fund,
    fx,
    qv,
    hhk,
    llk,
    xhk,
    xlk,
    atr_h,
    vol_h,
    target_vol,
    atr_mult,
    max_lev,
    lev,
    band,
    cool_min,
    dd_soft,
    dd_floor,
    flatten_ratio,
    ring_len,
    stop_extra,
    taker_in,
    eq_out,
    side_out,
    out,
):
    taker = taker_in if taker_in > 0.0 else TAKER
    kk = hhk.shape[0]
    sleeve = np.zeros(kk)
    wallet = START_CNY / (fx[i0] * (1.0 + FX_FEE))
    side = 0
    qty = 0.0
    entry = 0.0
    isolated = 0.0
    stop_px = 0.0
    extreme = 0.0
    cool = i0
    peak = START_CNY
    min_ratio = 1.0
    min_i = i0
    n_long = 0
    n_short = 0
    n_stop = 0
    n_flat = 0
    turn_u = 0.0
    ring = np.full(ring_len, START_CNY)
    rp = START_CNY
    pend = 0
    pend_q = 0.0
    for i in range(i0, i1):
        h = i // 60
        hk = h - 1 if h > 0 else 0
        slip_b = _slip_amt(C[i - 1], qty, H[i - 1], L[i - 1], qv[i - 1]) if (qty > 0.0 and i > i0) else 0.0001
        if side != 0 and fund[i] != 0.0:
            pay = qty * OP[i] * fund[i] * side
            upnl = (OP[i] - entry) * qty * side
            mmr, cum = _mmr_cum(qty * OP[i])
            maint = qty * OP[i] * mmr - cum
            if maint < 0.0:
                maint = 0.0
            if isolated + upnl - pay <= maint:
                fill = OP[i] * (1.0 - slip_b) if side > 0 else OP[i] * (1.0 + slip_b)
                fee = qty * fill * taker
                turn_u += qty * fill
                wallet, _d = _realize(wallet, (fill - entry) * qty * side - fee, pay, isolated)
                isolated = 0.0
                qty = 0.0
                side = 0
                stop_px = 0.0
                n_stop += 1
                cool = i + cool_min
                pend = 0
            else:
                wallet -= pay
                isolated -= pay
        if pend == 1:
            pend = 0
            tq = pend_q
            flip = side != 0 and (tq == 0.0 or (tq > 0.0) != (side > 0))
            if flip:
                fill = OP[i] * (1.0 - slip_b) if side > 0 else OP[i] * (1.0 + slip_b)
                fee = qty * fill * taker
                turn_u += qty * fill
                wallet, _d = _realize(wallet, (fill - entry) * qty * side - fee, 0.0, isolated)
                isolated = 0.0
                qty = 0.0
                side = 0
                stop_px = 0.0
                n_flat += 1
            want = abs(tq)
            if tq != 0.0 and i >= cool:
                atr_k = atr_h[hk]
                dist = atr_mult * atr_k
                if side == 0 and want >= 0.001 and dist > 0.0:
                    px = OP[i]
                    es = _slip_amt(px, want, H[i - 1], L[i - 1], qv[i - 1]) if i > i0 else 0.0001
                    fill = px * (1.0 + es) if tq > 0.0 else px * (1.0 - es)
                    fee_rate = fill * taker
                    cap_q = wallet * (1.0 - CASH_BUFFER) / (fill / lev + fee_rate)
                    cap_q = np.floor(cap_q * 1000.0) / 1000.0
                    if want > cap_q:
                        want = cap_q
                    if want >= 0.001 and want * px >= MIN_NOTIONAL:
                        wallet -= want * fee_rate
                        turn_u += want * fill
                        side = 1 if tq > 0.0 else -1
                        qty = want
                        entry = fill
                        isolated = want * fill / lev
                        extreme = fill
                        stop_px = fill - dist if side > 0 else fill + dist
                        stop_px = _clamp_stop(side, stop_px, fill, qty, isolated, px)
                        if side > 0:
                            n_long += 1
                        else:
                            n_short += 1
                elif side != 0 and dist > 0.0:
                    px = OP[i]
                    diff = want - qty
                    if diff > 0.0:
                        dq = np.floor(diff * 1000.0) / 1000.0
                        if dq >= 0.001:
                            es = _slip_amt(px, dq, H[i - 1], L[i - 1], qv[i - 1]) if i > i0 else 0.0001
                            fill = px * (1.0 + es) if side > 0 else px * (1.0 - es)
                            fee = dq * fill * taker
                            iso_add = dq * fill / lev
                            posted = isolated if isolated > 0.0 else 0.0
                            if wallet - posted > iso_add + fee:
                                wallet -= fee
                                turn_u += dq * fill
                                entry = (entry * qty + fill * dq) / (qty + dq)
                                qty += dq
                                isolated += iso_add
                                stop_px = _clamp_stop(side, stop_px, entry, qty, isolated, px)
                    elif diff < 0.0:
                        dq = np.floor(-diff * 1000.0) / 1000.0
                        if dq >= 0.001 and dq < qty:
                            es = _slip_amt(px, dq, H[i - 1], L[i - 1], qv[i - 1]) if i > i0 else 0.0001
                            fill = px * (1.0 - es) if side > 0 else px * (1.0 + es)
                            fee = dq * fill * taker
                            share = isolated * dq / qty
                            turn_u += dq * fill
                            wallet, _d = _realize(wallet, (fill - entry) * dq * side - fee, 0.0, share)
                            isolated -= share
                            qty -= dq
        if side != 0:
            bull = C[i] >= OP[i]
            hit = False
            fill = 0.0
            dist = atr_mult * atr_h[hk] if atr_h[hk] > 0.0 else 0.0
            for k in range(4):
                if k == 0:
                    px = OP[i]
                elif k == 1:
                    px = L[i] if bull else H[i]
                elif k == 2:
                    px = H[i] if bull else L[i]
                else:
                    px = C[i]
                stop_px = _clamp_stop(side, stop_px, entry, qty, isolated, px)
                if side > 0 and px <= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 - slip_b - (0.0 if k == 0 else stop_extra))
                    break
                if side < 0 and px >= stop_px:
                    hit = True
                    fill = (px if k == 0 else stop_px) * (1.0 + slip_b + (0.0 if k == 0 else stop_extra))
                    break
                scale_fx = fx[i] * (1.0 - FX_FEE)
                eq_usd = wallet + (px - entry) * qty * side
                if flatten_ratio > 0.0 and rp > 0.0 and scale_fx > 0.0 and eq_usd * scale_fx <= flatten_ratio * rp:
                    fill = px * (1.0 - slip_b) if side > 0 else px * (1.0 + slip_b)
                    peak, min_ratio, min_i = _mark(
                        px, wallet, entry, qty, side, fx[i], FX_FEE, peak, min_ratio, min_i, i
                    )
                    hit = True
                    break
                if (side > 0 and px > extreme) or (side < 0 and px < extreme):
                    extreme = px
                if dist > 0.0:
                    if side > 0 and extreme - dist > stop_px:
                        stop_px = extreme - dist
                    elif side < 0 and extreme + dist < stop_px:
                        stop_px = extreme + dist
                peak, min_ratio, min_i = _mark(px, wallet, entry, qty, side, fx[i], FX_FEE, peak, min_ratio, min_i, i)
            if hit:
                fee = qty * fill * taker
                turn_u += qty * fill
                wallet, _d = _realize(wallet, (fill - entry) * qty * side - fee, 0.0, isolated)
                isolated = 0.0
                qty = 0.0
                side = 0
                stop_px = 0.0
                n_stop += 1
                cool = i + cool_min
                peak, min_ratio, min_i = _mark(0.0, wallet, 0.0, 0.0, 0, fx[i], FX_FEE, peak, min_ratio, min_i, i)
        eq = wallet + ((C[i] - entry) * qty * side if side != 0 else 0.0)
        cny = eq * fx[i] * (1.0 - FX_FEE)
        if cny > peak:
            peak = cny
        if peak > 0.0 and cny / peak < min_ratio:
            min_ratio = cny / peak
            min_i = i
        eq_out[i] = cny
        side_out[i] = side
        if i % 60 == 59:
            ring[h % ring_len] = cny
            m = h + 1 if h + 1 < ring_len else ring_len
            best = START_CNY
            for r in range(m):
                if ring[r] > best:
                    best = ring[r]
            rp = best
            s = 0.0
            c = C[i]
            for j in range(kk):
                st = sleeve[j]
                up = c > hhk[j, h]
                dn = c < llk[j, h]
                if st > 0.0:
                    if dn:
                        st = -1.0
                    elif c < xlk[j, h]:
                        st = 0.0
                elif st < 0.0:
                    if up:
                        st = 1.0
                    elif c > xhk[j, h]:
                        st = 0.0
                else:
                    if up:
                        st = 1.0
                    elif dn:
                        st = -1.0
                sleeve[j] = st
                s += st
            s /= kk
            ratio = cny / rp if rp > 0.0 else 1.0
            span = dd_soft - dd_floor
            scale = (ratio - dd_floor) / span if span > 0.0 else 1.0
            if scale < 0.0:
                scale = 0.0
            if scale > 1.0:
                scale = 1.0
            atr_now = atr_h[h]
            vol_now = vol_h[h]
            tq = 0.0
            if atr_now > 0.0 and vol_now > 0.0 and s != 0.0 and scale > 0.0:
                lev_t = target_vol / (vol_now if vol_now > 0.05 else 0.05)
                if lev_t > max_lev:
                    lev_t = max_lev
                notional = eq * lev_t * abs(s) * scale
                tq = np.floor(notional / c * 1000.0) / 1000.0
                if s < 0.0:
                    tq = -tq
            cur_q = qty * side
            need = False
            if (
                (tq == 0.0 and cur_q != 0.0)
                or (tq != 0.0 and cur_q == 0.0)
                or (tq != 0.0 and (tq > 0.0) != (cur_q > 0.0))
            ):
                need = True
            elif tq != 0.0:
                ref = max(abs(tq), abs(cur_q))
                if abs(tq - cur_q) > band * ref:
                    need = True
            if need and i + 1 < i1:
                pend = 1
                pend_q = tq
    out[0] = wallet
    out[1] = min_ratio
    out[2] = n_long
    out[3] = n_short
    out[4] = n_stop
    out[5] = n_flat
    out[6] = turn_u
    out[7] = min_i
    last = i1 - 1
    eq_last = wallet + ((C[last] - entry) * qty * side if side != 0 else 0.0)
    return eq_last * fx[last] * (1.0 - FX_FEE)


def run_candidate(
    tape: Tape,
    cfg: CandidateConfig,
    i0: int = 0,
    i1: int | None = None,
    stop_extra: float = 0.0,
    taker: float = 0.0,
    arrays: tuple[np.ndarray, ...] | None = None,
) -> dict[str, Any]:
    end_index = len(tape.c) if i1 is None else i1
    if arrays is None:
        high, low, close = tape.hourly()
        arrays = indicators(high, low, close, cfg)
    hhk, llk, xhk, xlk, atr, vol = arrays
    n = len(tape.c)
    eq = np.zeros(n)
    side = np.zeros(n, np.int8)
    out = np.zeros(8)
    end = _loop(
        i0,
        end_index,
        tape.o,
        tape.h,
        tape.low,
        tape.c,
        tape.fund,
        tape.fx,
        tape.qv,
        hhk,
        llk,
        xhk,
        xlk,
        atr,
        vol,
        cfg.target_vol,
        cfg.atr_mult,
        cfg.max_leverage,
        cfg.leverage,
        cfg.band,
        cfg.cooldown_hours * 60,
        cfg.dd_soft,
        cfg.dd_floor,
        cfg.flatten_ratio,
        cfg.dd_window_days * 24,
        stop_extra,
        taker,
        eq,
        side,
        out,
    )
    years = (end_index - i0) / 1440.0 / 365.25
    cagr = (end / START_CNY) ** (1.0 / years) - 1.0 if end > 0 and years > 0 else -1.0
    return {
        "end_cny": float(end),
        "cagr": float(cagr),
        "min_equity_over_peak": float(out[1]),
        "n_long": int(out[2]),
        "n_short": int(out[3]),
        "n_stop": int(out[4]),
        "n_flatten_or_flip": int(out[5]),
        "turnover_usdt": float(out[6]),
        "_equity": eq[i0:end_index],
        "_side": side[i0:end_index],
        "_i0": i0,
        "_i1": end_index,
    }
