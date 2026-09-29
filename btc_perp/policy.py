"""Decisions from a confirmed book and a completed minute.

The 10x take-profit is a disaster cap resting on the exchange. The research
exit is the trail, the channel, or the half-peak flatten. Sizing uses the
research heat only as a model input; the caller's hard notional cap is applied
later and can only make the order smaller.
"""

from __future__ import annotations

from btc_perp.config import AccountConfig
from btc_perp.costs import MAX_NOTIONAL_20X, MIN_NOTIONAL
from btc_perp.model import Action, Book


def initial_stop(side: int, entry: float, stop: float, liquidation: float, mark: float) -> float:
    """Research stop, pulled to the safe side of liquidation by 0.1% of mark."""
    if entry <= 0 or stop <= 0:
        return 0.0
    if side > 0:
        raw = entry * (1.0 - stop)
        if liquidation > 0 and mark > 0:
            floor = liquidation + mark * 0.001
            if raw < floor:
                raw = floor
        return raw
    if side < 0:
        raw = entry * (1.0 + stop)
        if liquidation > 0 and mark > 0:
            ceil = liquidation - mark * 0.001
            if ceil > 0 and raw > ceil:
                raw = ceil
        return raw
    return 0.0


def clamp_to_liquidation(side: int, stop_px: float, liquidation: float) -> float:
    """Keep a resting stop on the safe side of liquidation, as the research kernel does.

    A long stop under the liquidation price is never live: the exchange closes
    the position first. The 0.1% gap leaves the stop ahead of it.
    """
    if liquidation <= 0 or stop_px <= 0:
        return stop_px
    if side > 0:
        return max(stop_px, liquidation * 1.001)
    if side < 0:
        return min(stop_px, liquidation * 0.999)
    return stop_px


def disaster_take(side: int, entry: float, multiple: float) -> float:
    if side > 0:
        return entry * multiple
    if side < 0 and multiple != 0.0:
        return entry / multiple
    return 0.0


def trail_stop(
    side: int, extreme: float, entry: float, stop_px: float, trail: float, ratchet_gain: float, ratchet_trail: float
) -> float:
    if side > 0:
        t_use = ratchet_trail if ratchet_gain > 0.0 and entry > 0.0 and extreme / entry - 1.0 >= ratchet_gain else trail
        trailed = extreme * (1.0 - t_use)
        return trailed if trailed > stop_px else stop_px
    t_use = ratchet_trail if ratchet_gain > 0.0 and extreme > 0.0 and entry / extreme - 1.0 >= ratchet_gain else trail
    trailed = extreme * (1.0 + t_use)
    if trailed < stop_px:
        return trailed
    return stop_px


def research_notional(equity_usd: float, iso_frac: float, heat: float, trail: float, leverage: int) -> float:
    """The total position notional the research sizing allows at this equity."""
    capn = equity_usd * iso_frac * leverage
    if heat > 0.0:
        heat_n = equity_usd * heat / trail
        if heat_n < capn:
            capn = heat_n
    return min(capn, MAX_NOTIONAL_20X)


def _qty(
    equity_usd: float,
    price: float,
    stop: float,
    risk: float,
    scale: float,
    iso_frac: float,
    heat: float,
    trail: float,
    leverage: int,
    cap: float,
) -> float:
    if price <= 0 or stop <= 0 or equity_usd <= 0:
        return 0.0
    dist = max(price * stop, price * 0.005)
    raw = equity_usd * risk * scale / dist
    q = float(int(raw * 1000.0) / 1000.0)
    capn = research_notional(equity_usd, iso_frac, heat, trail, leverage)
    if cap > 0 and cap < capn:
        capn = cap
    if q * price > capn:
        q = float(int((capn / price) * 1000.0) / 1000.0)
    if q * price < MIN_NOTIONAL:
        return 0.0
    return q


def decide(
    book: Book,
    *,
    close: float,
    high: float,
    low: float,
    hh: float,
    ll: float,
    xh: float,
    xl: float,
    equity_cny: float,
    equity_usd: float,
    now_ms: int,
    cfg: AccountConfig,
    hard_notional: float,
    gate_open: bool,
    adverse_cny: float | None = None,
) -> Action:
    """One completed minute. ``gate_open`` is true only on the minute-59 close."""
    side = book.side
    extreme = book.extreme
    if side > 0 and high > extreme:
        extreme = high
    elif side < 0 and (extreme == 0.0 or low < extreme):
        extreme = low
    stop_px = book.stop
    if side != 0 and extreme > 0:
        stop_px = trail_stop(side, extreme, book.entry, stop_px, cfg.trail, cfg.ratchet_gain, cfg.ratchet_trail)
    peak = book.close_peak_cny
    if equity_cny > peak:
        peak = equity_cny
    ratio = equity_cny / peak if peak > 0 else 1.0
    take = disaster_take(side, book.entry, cfg.take_profit_multiple) if side else 0.0
    path_peak = book.peak_equity_cny
    if equity_cny > path_peak:
        path_peak = equity_cny
    probe = equity_cny if adverse_cny is None else adverse_cny
    scale = cfg.entry_scale if ratio < cfg.entry_scale_below else 1.0
    if side != 0 and cfg.flatten_ratio > 0 and path_peak > 0 and probe <= cfg.flatten_ratio * path_peak:
        return Action("exit", -side, abs(book.qty), stop_px, take, "权益落到峰值一半")
    # A channel exit may happen on any minute. Opening the other way is an entry
    # and obeys the same gate, cooldown and drawdown lock as every entry.
    may_open = gate_open and now_ms >= book.cooldown_until_ms and ratio > 1.0 - cfg.dd_flat
    if side > 0 and close < xl:
        if close < ll and may_open:
            return Action("reverse", -1, abs(book.qty), stop_px, take, "通道反向", scale)
        return Action("exit", -1, abs(book.qty), stop_px, take, "通道离场")
    if side < 0 and close > xh:
        if close > hh and may_open:
            return Action("reverse", 1, abs(book.qty), stop_px, take, "通道反向", scale)
        return Action("exit", 1, abs(book.qty), stop_px, take, "通道离场")
    if side != 0 and stop_px != book.stop:
        held = Action("update_stop", side, abs(book.qty), stop_px, take, "移动止损")
    else:
        held = Action("hold", side, abs(book.qty), stop_px, take, "")
    if not gate_open or now_ms < book.cooldown_until_ms or ratio <= 1.0 - cfg.dd_flat:
        return held
    want = 0
    if close > hh:
        want = 1
    elif close < ll:
        want = -1
    if side == 0 and want != 0:
        qty = _qty(
            equity_usd, close, cfg.stop, cfg.risk, scale, cfg.iso_frac, cfg.heat, cfg.trail, cfg.leverage, hard_notional
        )
        if qty <= 0:
            return Action("hold", 0, 0.0, 0.0, 0.0, "数量低于最小名义")
        return Action("enter", want, qty, 0.0, 0.0, "通道突破", scale)
    if side != 0 and want == -side:
        return Action("reverse", want, abs(book.qty), stop_px, take, "通道反向", scale)
    if side != 0 and book.units < cfg.max_units:
        step = cfg.add_step
        trig = (side > 0 and close >= book.last_add * (1.0 + step)) or (
            side < 0 and close <= book.last_add * (1.0 - step)
        )
        if trig:
            qty = _qty(
                equity_usd,
                close,
                cfg.stop,
                cfg.risk,
                1.0,
                cfg.iso_frac,
                cfg.heat,
                cfg.trail,
                cfg.leverage,
                hard_notional,
            )
            room = research_notional(equity_usd, cfg.iso_frac, cfg.heat, cfg.trail, cfg.leverage) / close - abs(
                book.qty
            )
            if hard_notional > 0 and close > 0:
                room = min(room, hard_notional / close - abs(book.qty))
            if qty > room:
                qty = float(int(max(room, 0.0) * 1000.0) / 1000.0)
            if qty >= 0.001:
                return Action("add", side, qty, stop_px, take, "加仓")
    return held
