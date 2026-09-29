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
    present: np.ndarray | None = None

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
    if tape.name != "btc":
        if tape.present is None or len(tape.present) != n or tape.present.dtype != np.dtype(bool):
            problems.append("缺少真实分钟来源覆盖标记；重新构建行情")
        else:
            missing = np.flatnonzero(~tape.present)
            for run in np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1):
                if len(run) > 1440:
                    first_gap = dt.datetime.fromtimestamp(int(tape.ts[run[0]]) / 1000, dt.UTC).isoformat()
                    problems.append(f"源行情连续缺失超过 24 小时：{first_gap} 起，{len(run)} 分钟")
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
    from scripts.frontier import load_hourly

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
    if "present" not in raw:
        raise ValueError(f"{path.name} 缺少真实分钟覆盖标记；请重新运行 scripts/assets.py")
    if name in {"eth", "sol"}:
        official = np.load(funding_path)
        stamps, rates = official["ts"], official["rate"]
        if (
            stamps.ndim != 1
            or rates.ndim != 1
            or len(stamps) != len(rates)
            or not np.issubdtype(stamps.dtype, np.integer)
            or not np.all(np.isfinite(rates))
        ):
            raise ValueError(f"{funding_path.name} 资金费时间或费率无效")
        hour_ms = 3_600_000
        if np.any(stamps % hour_ms >= 60_000):
            raise ValueError(f"{funding_path.name} 资金费结算时刻无法对齐 UTC 整小时")
        hours = stamps // hour_ms * hour_ms
        if len(np.unique(hours)) != len(hours):
            raise ValueError(f"{funding_path.name} 资金费同一结算小时重复")
        rate = {int(t): float(r) for t, r in zip(hours, rates, strict=True)}
        step = 8 * 3600 * 1000
        slots = [(i, int(t)) for i, t in enumerate(hour_ts) if int(t) % step == 0]
        official_end = int(dt.datetime(2026, 9, 1, tzinfo=dt.UTC).timestamp() * 1000)
        missing_official = [t for _i, t in slots if t < official_end and t not in rate]
        if missing_official:
            first = dt.datetime.fromtimestamp(missing_official[0] / 1000, dt.UTC).isoformat()
            raise ValueError(f"{funding_path.name} 官方 8 小时资金费缺失：{len(missing_official)} 槽，首个 {first}")
        missing_tail = sum(1 for _i, t in slots if t >= official_end and t not in rate)
        for i, t in enumerate(hour_ts):
            fund[i * 60] = rate.get(int(t), 0.0)
        note = (
            f"official funding events (including non-8h settlements); "
            f"{missing_tail} September 2026 slots lack official prints and use zero placeholders"
        )
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
        raw["present"],
    )
