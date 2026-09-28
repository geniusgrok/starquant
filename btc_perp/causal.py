"""Causal economics: a signal is known after the close and fills at the next open.

``python -m btc_perp measure`` still fills on the same close. This module does
not overwrite that file. A missing tape is reported as unverified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from btc_perp.config import ROOT
from btc_perp.measure import TARGET_CNY, YEARS

TARGET_150 = 10000.0 * (2.5**YEARS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_minutes(
    ts: np.ndarray,
    o: np.ndarray,
    h: np.ndarray,
    low: np.ndarray,
    c: np.ndarray,
    qv: np.ndarray,
) -> list[str]:
    """Timestamp, OHLC, and volume problems. An empty list means the tape is usable."""
    problems: list[str] = []
    n = len(c)
    if not (len(ts) == len(o) == len(h) == len(low) == len(qv) == n):
        return ["分钟数组长度不一致"]
    if n < 2:
        return ["分钟样本太短"]
    gaps = np.diff(ts.astype(np.int64))
    bad = np.flatnonzero(gaps != 60_000)
    if len(bad):
        problems.append(f"分钟不连续或重复：{int(bad[0])} 处起，共 {len(bad)} 处")
    if bool(np.any(np.minimum(np.minimum(o, h), np.minimum(low, c)) <= 0)):
        problems.append("存在非正价格")
    if bool(np.any(h + 1e-9 < np.maximum(np.maximum(o, c), low))):
        problems.append("high 低于其他价格")
    if bool(np.any(low - 1e-9 > np.minimum(np.minimum(o, c), h))):
        problems.append("low 高于其他价格")
    if bool(np.any(qv < 0)):
        problems.append("成交额为负")
    return problems


def _turnover(trace: np.ndarray, close: np.ndarray) -> tuple[float, float]:
    signed = trace[:, 0] * trace[:, 1]
    delta = np.abs(np.diff(signed, prepend=0.0))
    return float(delta.sum()), float((delta * close).sum())


def _funding_gap(ts: np.ndarray, fund: np.ndarray) -> dict[str, Any]:
    import datetime as dt

    target = int(dt.datetime(2026, 9, 1, tzinfo=dt.UTC).timestamp() * 1000)
    hit = np.flatnonzero(ts.astype(np.int64) == target)
    if len(hit) == 0:
        return {"present": False, "rate": None, "note": "磁带里没有 2026-09-01 00:00 UTC"}
    rate = float(fund[int(hit[0])])
    return {
        "present": True,
        "rate": rate,
        "missing_slot": rate == 0.0,
        "note": "2026-09-01 00:00 UTC 的资金费槽位为 0，这一档未用官方结算价验证",
    }


def run_causal(write_report: bool = True) -> dict[str, Any]:
    """Replay the official window with ``defer=1``. Missing files stay unverified."""
    data = ROOT / "data" / "btcusdt_1m.npz"
    funding = ROOT / "data" / "funding.npz"
    fx_path = ROOT / "data" / "usdcny_frankfurter.json"
    previous_path = ROOT / "reports" / "btc_account_measure.json"
    if not data.exists() or not funding.exists() or not fx_path.exists():
        report: dict[str, Any] = {
            "verified": False,
            "reason": "行情文件不在 data/，这次没有经济结果",
            "fills": "next open after the close is known",
            "meets_150": False,
            "meets_100": False,
        }
        if write_report:
            _write(report)
        return report

    from btc_perp.config import load_config
    from btc_perp.measure import _prepare
    from scripts.frontier import initial_state, resume

    raw = np.load(data)
    problems = validate_minutes(raw["ts"], raw["o"], raw["h"], raw["l"], raw["c"], raw["qv"])
    cfg = load_config()
    o, h, low, c, qv, fund, fx, days, _minute, hh, ll, xh, xl, gate = _prepare(cfg)
    if problems:
        report = {
            "verified": False,
            "reason": "行情校验没有通过",
            "problems": problems,
            "inputs": {
                "btcusdt_1m.npz": _sha256(data),
                "funding.npz": _sha256(funding),
                "usdcny_frankfurter.json": _sha256(fx_path),
            },
            "meets_150": False,
            "meets_100": False,
        }
        if write_report:
            _write(report)
        return report

    n = len(c)
    state = initial_state(float(fx[0]))
    equity = np.empty(n, dtype=np.float64)
    trace = np.zeros((n, 5), dtype=np.float64)
    end, ratio, n_long, n_short, n_stop, min_i = resume(
        state,
        0,
        n,
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
        cfg.cooldown_hours * 60,
        cfg.ratchet_gain,
        cfg.ratchet_trail,
        cfg.heat,
        cfg.flatten_ratio,
        cfg.entry_scale_below,
        cfg.entry_scale,
        gate,
        qv,
        equity,
        trace,
        1,
    )
    cagr = (end / cfg.start_cny) ** (1.0 / YEARS) - 1.0 if end > 0 else -1.0
    btc_turn, usdt_turn = _turnover(trace, c)
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
    gap = _funding_gap(raw["ts"], fund)
    meets_100 = bool(cagr >= 1.0 and ratio > 0.5 and end >= TARGET_CNY and n_long > 0 and n_short > 0)
    meets_150 = bool(cagr >= 1.5 and ratio > 0.5 and end >= TARGET_150 and n_long > 0 and n_short > 0)
    report = {
        "verified": True,
        "funding_gap_unverified": bool(gap.get("missing_slot")),
        "fills": "signal after the minute close, fill at the next bar open; stops still use the intrabar path",
        "start_cny": cfg.start_cny,
        "end_cny": float(end),
        "cagr": float(cagr),
        "min_equity_over_peak": float(ratio),
        "min_day": int(days[min_i]),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "n_stop": int(n_stop),
        "turnover_btc": btc_turn,
        "turnover_usdt": usdt_turn,
        "target_cny_100": TARGET_CNY,
        "target_cny_150": TARGET_150,
        "meets_100": meets_100,
        "meets_150": meets_150,
        "economic_goal_met": meets_150,
        "inputs": {
            "btcusdt_1m.npz": _sha256(data),
            "funding.npz": _sha256(funding),
            "usdcny_frankfurter.json": _sha256(fx_path),
        },
        "funding_gap": gap,
        "previous_same_bar": None
        if previous is None
        else {
            "end_cny": previous.get("end_cny"),
            "cagr": previous.get("cagr"),
            "min_equity_over_peak": previous.get("min_equity_over_peak"),
            "n_long": previous.get("n_long"),
            "n_short": previous.get("n_short"),
            "n_stop": previous.get("n_stop"),
            "note": "同根收盘成交的旧研究，不是这次的结果",
        },
        "why_it_can_differ": "开仓、加仓和通道出场改到下一根开盘；止损和一半峰值平仓仍在当根路径上。最后一根的信号没有下一根开盘，不会成交。",
    }
    if write_report:
        _write(report)
    return report


def _write(report: dict[str, Any]) -> None:
    path = ROOT / "reports" / "btc_account_causal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
