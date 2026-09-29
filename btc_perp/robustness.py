"""How fragile the published economics are.

The published result is one path. This module replays the same tape with the
stop filling worse, a higher taker fee, and each tuned setting moved a little.
Nothing here changes a setting or a pass line. It reports what the neighbours
do, and whether the drawdown lock ended a run.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from btc_perp.causal import TARGET_150, _provenance, _sha256, lockout, validate_minutes
from btc_perp.config import ROOT, AccountConfig, load_config
from btc_perp.measure import TARGET_CNY, YEARS
from btc_perp.reportio import completion, publish

STOP_EXTRA = (0.001, 0.002, 0.005, 0.01)
TAKER_STRESS = 0.0005
NEIGHBOUR_FACTORS = (0.9, 0.95, 1.05, 1.1)
NEIGHBOUR_FIELDS = (
    "entry_hours",
    "exit_hours",
    "stop",
    "trail",
    "add_step",
    "risk",
    "dd_flat",
    "flatten_ratio",
    "entry_scale_below",
    "heat",
    "iso_frac",
    "ratchet_gain",
    "ratchet_trail",
    "cooldown_hours",
)
REPORT = ROOT / "reports" / "btc_account_robustness.json"


def _replay(cfg: AccountConfig, stop_extra: float = 0.0, taker: float = 0.0) -> dict[str, Any]:
    from btc_perp.measure import _prepare
    from scripts.frontier import initial_state, resume

    o, h, low, c, qv, fund, fx, days, minute, hh, ll, xh, xl, gate = _prepare(cfg)
    n = len(c)
    state = initial_state(float(fx[0]))
    state[22] = stop_extra
    state[23] = taker
    equity = np.empty(n, dtype=np.float64)
    trace = np.zeros((n, 5), dtype=np.float64)
    end, ratio, n_long, n_short, n_stop, _min_i = resume(
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
    lock = lockout(equity, trace[:, 0], days, cfg.dd_flat, cfg.start_cny)
    return {
        "end_cny": float(end),
        "cagr": float(cagr),
        "min_equity_over_peak": float(ratio),
        "trades": int(n_long + n_short),
        "n_stop": int(n_stop),
        "breaches_half_peak_line": bool(ratio <= 0.5),
        "locked_at_end": lock["locked_at_end"],
        "flat_days_at_end": lock["flat_days_at_end"],
        "_equity": equity,
        "_minute": minute,
        "_days": days,
    }


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _year_ends(row: dict[str, Any]) -> dict[str, float]:
    seen: dict[int, float] = {}
    for i, day in enumerate(row["_days"]):
        if row["_minute"][i] == 59:
            seen[int(day) // 10000] = float(row["_equity"][i])
    return {str(year): value for year, value in sorted(seen.items())}


def _concentration(base: dict[str, Any], start: float) -> dict[str, Any]:
    ends = _year_ends(base)
    years = list(ends)
    previous = start
    yearly = {}
    for year in years:
        yearly[year] = {"equity_cny": ends[year], "return": ends[year] / previous - 1.0}
        previous = ends[year]
    first = years[0]
    rest_years = YEARS - 1.0
    rest = (base["end_cny"] / ends[first]) ** (1.0 / rest_years) - 1.0 if rest_years > 0 and ends[first] > 0 else None
    return {
        "yearly": yearly,
        "first_year": first,
        "cagr_after_first_year": rest,
        "note": "the first year is one path from the same tape; the rest CAGR starts from its ending equity",
    }


def _with(cfg: AccountConfig, name: str, value: float) -> AccountConfig:
    changes: dict[str, Any] = {name: value}
    return dataclasses.replace(cfg, **changes)


def _neighbours(cfg: AccountConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in NEIGHBOUR_FIELDS:
        base = getattr(cfg, name)
        seen: set[float] = set()
        for factor in NEIGHBOUR_FACTORS:
            scaled = base * factor
            value = max(round(scaled), 1) if isinstance(base, int) else round(scaled, 6)
            if value == base or value in seen:
                continue
            seen.add(value)
            row = _public(_replay(_with(cfg, name, value)))
            row.update({"field": name, "base": base, "value": value})
            rows.append(row)
    return rows


def run_robustness(write_report: bool = True) -> dict[str, Any]:
    data = ROOT / "data" / "btcusdt_1m.npz"
    funding = ROOT / "data" / "funding.npz"
    fx_path = ROOT / "data" / "usdcny_frankfurter.json"
    if not data.exists() or not funding.exists() or not fx_path.exists():
        report: dict[str, Any] = {"verified": False, "reason": "行情文件不在 data/，没有稳健性结果"}
        if write_report:
            _write(report)
        return report
    raw = np.load(data)
    problems = validate_minutes(raw["ts"], raw["o"], raw["h"], raw["l"], raw["c"], raw["qv"])
    if problems:
        report = {"verified": False, "reason": "行情校验没有通过", "problems": problems}
        if write_report:
            _write(report)
        return report

    cfg = load_config()
    base = _replay(cfg)
    stops = []
    for extra in STOP_EXTRA:
        row = _public(_replay(cfg, stop_extra=extra))
        row["stop_extra"] = extra
        stops.append(row)
    fee = _public(_replay(cfg, taker=TAKER_STRESS))
    fee["taker"] = TAKER_STRESS
    neighbours = _neighbours(cfg)
    failed = [row for row in neighbours if row["breaches_half_peak_line"] or row["locked_at_end"]]
    first_stop_failure = next((row["stop_extra"] for row in stops if row["breaches_half_peak_line"]), None)
    report = {
        "verified": True,
        "fills": "next open after the close is known (defer=1); stops use the intrabar path",
        "base": _public(base),
        "concentration": _concentration(base, cfg.start_cny),
        "stop_extra_adverse": stops,
        "taker_stress": fee,
        "neighbours": neighbours,
        "summary": {
            "neighbour_runs": len(neighbours),
            "neighbours_breaching_half_peak_or_locked": len(failed),
            "neighbour_failure_share": len(failed) / len(neighbours) if neighbours else None,
            "smallest_stop_extra_that_breaches": first_stop_failure,
            "base_min_equity_over_peak": base["min_equity_over_peak"],
            "target_cny_100": TARGET_CNY,
            "target_cny_150": TARGET_150,
            "reading": (
                "A stop that fills worse, or a setting moved by 5 to 10 percent, often ends in the drawdown "
                "lock. Read the published 120% as one path on one tape, not as a robust estimate."
            ),
        },
        "inputs": {
            "btcusdt_1m.npz": _sha256(data),
            "funding.npz": _sha256(funding),
            "usdcny_frankfurter.json": _sha256(fx_path),
        },
        "provenance": _provenance(),
    }
    if write_report:
        _write(report)
    return report


def _write(report: dict[str, Any]) -> None:
    verified = bool(report.get("verified"))
    report.setdefault("completion", completion(data_validated=verified, path_complete=verified, economic_pass=False))
    publish(REPORT, report)
