"""Minute tapes for the baseline, the candidate, and the other assets."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

import numpy as np

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
    if funding_path.exists():
        official = np.load(funding_path)
        rate = {_bucket8h(int(t)): float(r) for t, r in zip(official["ts"], official["rate"], strict=True)}
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
