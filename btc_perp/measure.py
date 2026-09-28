"""Full-sample research measurement of the one account.

Each minute is four OHLC prints, not a 5-second tape. A bullish minute is
ordered open, low, high, close; a bearish minute is open, high, low, close.
The trail amends when a new extreme prints, and the stop can fill on the next
print. Entries and pyramid adds are read on the completed hour (minute 59).
Channel exits are checked on every minute close.

Fee rates and the 82% entry-size cut live in ``btc_perp.costs``. The kernel
is ``scripts.frontier.run``. See ``docs/btc_account.md``.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from btc_perp.config import ROOT, AccountConfig, load_config

YEARS = 2454 / 365.25
TARGET_CNY = 10000.0 * (2.0**YEARS)


def _prepare(cfg: AccountConfig) -> tuple[Any, ...]:
    from scripts.frontier import _channels, load_hourly, run

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
    return run, o, h, low, c, qv, fund, fx, days, minute, hh[hour], ll[hour], xh[hour], xl[hour], gate


def run_official(write_report: bool = True) -> dict:
    cfg = load_config()
    run, o, h, low, c, qv, fund, fx, days, minute, hh, ll, xh, xl, gate = _prepare(cfg)
    eq = np.empty(len(c))
    end, ratio, n_long, n_short, n_stop, min_i = run(
        o,
        h,
        low,
        c,
        fund,
        fx,
        hh,
        ll,
        xh,
        xl,
        cfg.stop,
        cfg.trail,
        cfg.add_step,
        cfg.max_units,
        cfg.risk,
        cfg.dd_flat,
        cfg.iso_frac,
        0 if cfg.long_and_short else 1,
        cfg.cooldown_hours * 60,
        0.0,
        cfg.ratchet_gain,
        cfg.ratchet_trail,
        1,
        0,
        0.0,
        1,
        1.0,
        cfg.heat,
        0.0,
        gate,
        qv,
        eq,
        np.empty((1, 4)),
        np.empty(1),
    )
    cagr = (end / cfg.start_cny) ** (1.0 / YEARS) - 1.0 if end > 0 else -1.0
    yearly = {}
    prev = cfg.start_cny
    seen: dict[int, float] = {}
    for i, day in enumerate(days):
        if minute[i] == 59:
            seen[int(day) // 10000] = float(eq[i])
    for year, equity in sorted(seen.items()):
        yearly[str(year)] = {"equity_cny": equity, "return": equity / prev - 1.0}
        prev = equity
    passed = bool(cagr >= 1.0 and ratio > 0.5 and end >= TARGET_CNY and n_long > 0 and n_short > 0)
    report = {
        "passed": passed,
        "start_cny": cfg.start_cny,
        "end_cny": float(end),
        "target_cny": TARGET_CNY,
        "cagr": float(cagr),
        "min_equity_over_peak": float(ratio),
        "min_day": int(days[min_i]),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "n_stop": int(n_stop),
        "yearly": yearly,
        "costs": {
            "taker": cfg.taker,
            "slip_base": cfg.slip_base,
            "impact_y": cfg.impact_y,
            "fx_fee": cfg.fx_fee,
            "funding": "binance vision plus premium-index September 2026",
        },
        "path": "1-minute OHLC in 5-second order, trail amends on new extremes, entries on completed hours",
        "live_orders": False,
    }
    if write_report:
        path = ROOT / "reports" / "btc_account_measure.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
    return report
