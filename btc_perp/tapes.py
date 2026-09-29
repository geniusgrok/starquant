"""Minute tapes for the baseline, the candidate, and the other assets."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

import numpy as np

from btc_perp.causal import validate_minutes
from btc_perp.config import ROOT

DATA = ROOT / "data"


@dataclass
class Tape:
    name: str
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    low: np.ndarray
    c: np.ndarray
    qv: np.ndarray
    fund: np.ndarray
    fx: np.ndarray
    days: np.ndarray
    note: str = ""

    @property
    def hours(self) -> int:
        return len(self.c) // 60

    def hourly(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = self.hours
        high = self.h.reshape(n, 60).max(1)
        low = self.low.reshape(n, 60).min(1)
        close = self.c[59::60]
        return high.astype(np.float64), low.astype(np.float64), close.astype(np.float64)


EXPECTED_WINDOWS = {
    "btc": ("2020-01-01", "2026-09-20"),
    "eth": ("2020-01-01", "2026-09-20"),
    "sol": ("2020-10-01", "2026-09-20"),
    "btc_spot_2017": ("2017-09-01", "2020-01-01"),
}


def validate_tape(tape: Tape) -> list[str]:
    problems = validate_minutes(tape.ts, tape.o, tape.h, tape.low, tape.c, tape.qv, official_window=tape.name == "btc")
    if tape.name not in EXPECTED_WINDOWS:
        return [*problems, "未知行情窗口"]
    first, end = EXPECTED_WINDOWS[tape.name]
    begin_ms = int(dt.datetime.fromisoformat(first).replace(tzinfo=dt.UTC).timestamp() * 1000)
    end_ms = int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.UTC).timestamp() * 1000)
    if len(tape.ts) and (int(tape.ts[0]) != begin_ms or int(tape.ts[-1]) != end_ms - 60_000):
        problems.append("行情不在预定时间窗口")
    n = len(tape.ts)
    if n % 60 or any(len(a) != n for a in (tape.fund, tape.fx, tape.days)):
        problems.append("资金费、汇率、日期或小时数组长度不一致")
        return problems
    if not np.all(np.isfinite(tape.fund)):
        problems.append("资金费有非有限数字")
    if not np.all(np.isfinite(tape.fx)) or np.any(tape.fx <= 0):
        problems.append("汇率有非有限或非正数字")
    return problems


def _fx(ts_hours: np.ndarray, use_real: bool) -> np.ndarray:
    from scripts.frontier import causal_fx

    if not use_real:
        return np.ones(len(ts_hours))
    raw = json.loads((DATA / "usdcny_frankfurter.json").read_text())
    rates = {dt.date.fromisoformat(k): float(v["CNY"]) for k, v in raw["rates"].items()}
    days = [dt.datetime.fromtimestamp(int(t) / 1000, dt.UTC).date() for t in ts_hours]
    return np.asarray(causal_fx(days, rates), dtype=np.float64)


def _days(ts_hours: np.ndarray) -> np.ndarray:
    out = np.empty(len(ts_hours), np.int32)
    for i, t in enumerate(ts_hours):
        day = dt.datetime.fromtimestamp(int(t) / 1000, dt.UTC)
        out[i] = day.year * 10000 + day.month * 100 + day.day
    return out


def load_tape(name: str) -> Tape:
    from scripts.frontier import _bucket8h, load_hourly

    if name == "btc":
        raw = np.load(DATA / "btcusdt_1m.npz")
        _o, _h, _l, _c, fund_h, fx_h, days_h = load_hourly()
        n = len(raw["c"])
        fund = np.zeros(n)
        fund[np.arange(n) % 60 == 0] = fund_h
        return Tape(
            "btc",
            raw["ts"],
            raw["o"].astype(np.float64),
            raw["h"].astype(np.float64),
            raw["l"].astype(np.float64),
            raw["c"].astype(np.float64),
            raw["qv"].astype(np.float64),
            fund,
            np.repeat(fx_h, 60),
            np.repeat(days_h, 60),
            "official funding; 2026-09 funding is a premium estimate and one slot is missing",
        )
    path = DATA / "assets" / f"{name}_1m.npz"
    raw = np.load(path)
    ts = raw["ts"]
    n = len(ts)
    hour_ts = ts[::60]
    fund = np.zeros(n)
    note = "no perpetual funding on a spot tape; funding is zero"
    funding_path = DATA / "assets" / f"{name}_funding.npz"
    if name in {"eth", "sol"} and not funding_path.exists():
        raise ValueError(f"{funding_path.name} 缺失，不能按零费率替代永续合约资金费")
    if funding_path.exists():
        official = np.load(funding_path)
        stamps, rates = official["ts"], official["rate"]
        if not np.all(np.isfinite(rates)) or len(np.unique(stamps)) != len(stamps):
            raise ValueError(f"{funding_path.name} 资金费时间重复或费率非有限")
        rate = {_bucket8h(int(t)): float(r) for t, r in zip(stamps, rates, strict=True)}
        step = 8 * 3600 * 1000
        slots = [(i, int(t)) for i, t in enumerate(hour_ts) if int(t) % step == 0]
        missing = sum(1 for _i, t in slots if t not in rate)
        for i, t in slots:
            fund[i * 60] = rate.get(t, 0.0)
        note = f"official funding; {missing} of {len(slots)} slots missing and filled with zero"
    real_fx = name != "btc_spot_2017"
    fx_h = _fx(hour_ts, real_fx)
    return Tape(
        name,
        ts,
        raw["o"].astype(np.float64),
        raw["h"].astype(np.float64),
        raw["l"].astype(np.float64),
        raw["c"].astype(np.float64),
        raw["qv"].astype(np.float64),
        fund,
        np.repeat(fx_h, 60),
        np.repeat(_days(hour_ts), 60),
        note if real_fx else note + "; USD units (fx = 1)",
    )
