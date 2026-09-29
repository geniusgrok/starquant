"""Out-of-sample and cross-asset checks. Nothing here changes a setting."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np

from btc_perp.config import ROOT, AccountConfig
from btc_perp.costs import START_CNY
from btc_perp.reportio import completion, publish
from btc_perp.tapes import Tape

_CHANNELS: dict[tuple[str, int, int], tuple[np.ndarray, ...]] = {}


def _baseline_channels(tape: Tape, entry: int, exit_: int) -> tuple[np.ndarray, ...]:
    from scripts.frontier import _channels

    key = (tape.name, entry, exit_)
    if key not in _CHANNELS:
        high, low, _close = tape.hourly()
        hh, ll, xh, xl = _channels(high, low, entry, exit_)
        _CHANNELS[key] = tuple(np.repeat(a, 60) for a in (hh, ll, xh, xl))
    return _CHANNELS[key]


def baseline_replay(
    tape: Tape,
    cfg: AccountConfig,
    i0: int = 0,
    i1: int | None = None,
    stop_extra: float = 0.0,
    taker: float = 0.0,
    keep_path: bool = False,
) -> dict[str, Any]:
    """The published rules on any tape, next-open fills, starting flat at ``i0``."""
    from scripts.frontier import initial_state, resume

    n = len(tape.c)
    end_index = n if i1 is None else i1
    hh, ll, xh, xl = _baseline_channels(tape, cfg.entry_hours, cfg.exit_hours)
    gate = np.zeros(n, np.int8)
    gate[np.arange(n) % 60 == 59] = 1
    state = initial_state(float(tape.fx[i0]))
    state[22] = stop_extra
    state[23] = taker
    equity = np.zeros(n) if keep_path else np.empty(1)
    trace = np.zeros((n, 5)) if keep_path else np.zeros((1, 5))
    end, ratio, n_long, n_short, n_stop, _mi = resume(
        state,
        i0,
        end_index,
        tape.o,
        tape.h,
        tape.low,
        tape.c,
        tape.fund,
        tape.fx,
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
        tape.qv,
        equity,
        trace,
        1,
    )
    years = (end_index - i0) / 1440.0 / 365.25
    cagr = (end / START_CNY) ** (1.0 / years) - 1.0 if end > 0 and years > 0 else -1.0
    row: dict[str, Any] = {
        "end_cny": float(end),
        "cagr": float(cagr),
        "min_equity_over_peak": float(ratio),
        "trades": int(n_long + n_short),
        "n_stop": int(n_stop),
    }
    if keep_path:
        row["_equity"] = equity[i0:end_index]
        row["_side"] = trace[i0:end_index, 0]
    return row


LB_MULTIPLES = (1.0, 2.0, 3.0, 4.5)
LB_SCALES = (10, 20, 40, 60)
TARGET_VOLS = (0.3, 0.5, 0.8)
ATR_MULTS = (2.0, 3.0, 5.0)
TAPES = ("btc", "eth", "sol", "btc_spot_2017")


def family() -> list[dict[str, Any]]:
    """The candidate's whole search space. Small on purpose, and every point is reported."""
    return [{"lb_scale": s, "target_vol": v, "atr_mult": a} for s in LB_SCALES for v in TARGET_VOLS for a in ATR_MULTS]


def _candidate_cfg(base: Any, point: dict[str, Any]) -> Any:
    import dataclasses

    days = tuple(max(round(point["lb_scale"] * m), 2) for m in LB_MULTIPLES)
    return dataclasses.replace(base, lookback_days=days, target_vol=point["target_vol"], atr_mult=point["atr_mult"])


def calmar(row: dict[str, Any]) -> float:
    drawdown = max(1.0 - float(row["min_equity_over_peak"]), 0.05)
    return float(row["cagr"]) / drawdown


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def candidate_grid(tapes: dict[str, Tape], base: Any) -> list[dict[str, Any]]:
    from btc_perp.candidate import indicators, run_candidate

    rows: list[dict[str, Any]] = []
    for point in family():
        cfg = _candidate_cfg(base, point)
        for name, tape in tapes.items():
            high, low, close = tape.hourly()
            arrays = indicators(high, low, close, cfg)
            row = _public(run_candidate(tape, cfg, arrays=arrays))
            row.update({"tape": name, **point, "calmar": calmar(row)})
            rows.append(row)
    return rows


def _key(point: dict[str, Any]) -> tuple[Any, ...]:
    return (point["lb_scale"], point["target_vol"], point["atr_mult"])


def choose(rows: list[dict[str, Any]], tapes: tuple[str, ...]) -> dict[str, Any]:
    """The point with the best median Calmar over ``tapes``."""
    scores: dict[tuple[Any, ...], list[float]] = {}
    for row in rows:
        if row["tape"] in tapes:
            scores.setdefault(_key(row), []).append(float(row["calmar"]))
    best = max(scores, key=lambda k: float(np.median(scores[k])))
    return {
        "lb_scale": best[0],
        "target_vol": best[1],
        "atr_mult": best[2],
        "median_calmar": float(np.median(scores[best])),
    }


def leave_one_out(rows: list[dict[str, Any]], names: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for held in names:
        others = tuple(n for n in names if n != held)
        pick = choose(rows, others)
        held_rows = [r for r in rows if r["tape"] == held]
        chosen = next(r for r in held_rows if _key(r) == _key(pick))
        ranked = sorted((float(r["calmar"]) for r in held_rows), reverse=True)
        rank = 1 + sum(1 for v in ranked if v > float(chosen["calmar"]))
        out.append(
            {
                "held_out": held,
                "chosen_on": list(others),
                "chosen": {k: pick[k] for k in ("lb_scale", "target_vol", "atr_mult")},
                "held_out_row": {
                    k: chosen[k] for k in ("end_cny", "cagr", "min_equity_over_peak", "n_long", "n_short", "calmar")
                },
                "rank_among_grid": rank,
                "grid_size": len(held_rows),
                "median_of_grid": {
                    "cagr": float(np.median([r["cagr"] for r in held_rows])),
                    "min_equity_over_peak": float(np.median([r["min_equity_over_peak"] for r in held_rows])),
                },
                "share_of_grid_with_positive_cagr": float(np.mean([r["cagr"] > 0 for r in held_rows])),
            }
        )
    return out


def block_bootstrap(equity: np.ndarray, draws: int = 1000, block: int = 20, seed: int = 20260929) -> dict[str, Any]:
    """Resample daily returns in blocks. Descriptive: it ignores path-dependent rules such as the lock."""
    daily = equity[1439::1440]
    if len(daily) < block * 3:
        return {}
    ret = daily[1:] / daily[:-1] - 1.0
    n = len(ret)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block, size=(draws, n // block + 1))
    picks = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n]
    curves = np.cumprod(1.0 + ret[picks], axis=1)
    peaks = np.maximum.accumulate(curves, axis=1)
    worst = (curves / peaks).min(axis=1)
    years = n / 365.25
    cagr = curves[:, -1] ** (1.0 / years) - 1.0
    pct = (5, 25, 50, 75, 95)
    return {
        "draws": draws,
        "block_days": block,
        "cagr_percentiles": {str(p): float(np.percentile(cagr, p)) for p in pct},
        "min_equity_over_peak_percentiles": {str(p): float(np.percentile(worst, p)) for p in pct},
        "share_min_ratio_above_half": float(np.mean(worst > 0.5)),
        "share_positive_cagr": float(np.mean(cagr > 0)),
    }


def window_returns(equity: np.ndarray, days: int = 182) -> dict[str, Any]:
    daily = equity[1439::1440]
    step = days
    rets = [daily[i + step] / daily[i] - 1.0 for i in range(0, len(daily) - step, step)]
    if not rets:
        return {}
    arr = np.array(rets)
    return {
        "windows": len(arr),
        "median": float(np.median(arr)),
        "share_positive": float(np.mean(arr > 0)),
        "worst": float(arr.min()),
        "best": float(arr.max()),
    }


REPORT = ROOT / "reports" / "btc_account_generalization.json"
WALK_START = "2022-01-01"
WALK_MONTHS = 6
STRESS_EXTRA = (0.001, 0.005)
STRESS_TAKER = 0.0005


def _month_starts(tape: Tape, first: str, months: int) -> list[int]:
    """Minute indices of each window start from ``first``, ending with the tape end."""
    start = dt.date.fromisoformat(first)
    ts = tape.ts
    out: list[int] = []
    y, m = start.year, start.month
    while True:
        day = dt.datetime(y, m, 1, tzinfo=dt.UTC)
        idx = int(np.searchsorted(ts, int(day.timestamp() * 1000)))
        if idx >= len(ts) - 1440:
            break
        out.append(idx)
        m += months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
    out.append(len(ts))
    return out


def baseline_family(cfg: AccountConfig) -> list[dict[str, Any]]:
    """The published settings plus every neighbour used in the robustness study."""
    from btc_perp.robustness import NEIGHBOUR_FACTORS, NEIGHBOUR_FIELDS, _with

    points: list[dict[str, Any]] = [{"field": None, "value": None, "cfg": cfg}]
    for name in NEIGHBOUR_FIELDS:
        base = getattr(cfg, name)
        seen: set[float] = set()
        for factor in NEIGHBOUR_FACTORS:
            scaled = base * factor
            value = max(round(scaled), 1) if isinstance(base, int) else round(scaled, 6)
            if value == base or value in seen:
                continue
            seen.add(value)
            points.append({"field": name, "value": value, "cfg": _with(cfg, name, value)})
    return points


def walk_forward(tape: Tape, cfg: AccountConfig) -> dict[str, Any]:
    """Pick the baseline's settings on the past, trade the next window flat, repeat."""
    points = baseline_family(cfg)
    edges = _month_starts(tape, WALK_START, WALK_MONTHS)
    windows = []
    growth = {"fixed": 1.0, "selected": 1.0, "median_of_family": 1.0}
    for k in range(len(edges) - 1):
        t0, t1 = edges[k], edges[k + 1]
        train = [baseline_replay(tape, p["cfg"], 0, t0) for p in points]
        scores = [calmar(r) for r in train]
        pick = int(np.argmax(scores))
        test = [baseline_replay(tape, p["cfg"], t0, t1) for p in points]
        returns = [r["end_cny"] / START_CNY - 1.0 for r in test]
        fixed, selected = returns[0], returns[pick]
        typical = float(np.median(returns))
        growth["fixed"] *= 1.0 + fixed
        growth["selected"] *= 1.0 + selected
        growth["median_of_family"] *= 1.0 + typical
        windows.append(
            {
                "test_start_index": t0,
                "test_days": (t1 - t0) // 1440,
                "chosen": {"field": points[pick]["field"], "value": points[pick]["value"]},
                "train_calmar_chosen": scores[pick],
                "train_calmar_published": scores[0],
                "return_published": fixed,
                "return_selected": selected,
                "return_median_of_family": typical,
                "min_ratio_selected": test[pick]["min_equity_over_peak"],
                "min_ratio_published": test[0]["min_equity_over_peak"],
                "share_of_family_positive": float(np.mean([r > 0 for r in returns])),
            }
        )
    days = (edges[-1] - edges[0]) // 1440
    years = days / 365.25
    cagr = {name: (value ** (1.0 / years) - 1.0 if value > 0 else -1.0) for name, value in growth.items()}
    return {
        "family_size": len(points),
        "window_months": WALK_MONTHS,
        "first_test": WALK_START,
        "windows": windows,
        "compounded_growth": growth,
        "cagr": cagr,
        "note": (
            "Each test window starts flat with 10,000 CNY. The family is the published settings and their "
            "neighbours, so it already sits around a point tuned on this same tape: this is optimistic, "
            "not a clean out-of-sample."
        ),
    }


def _stress(runner: Any, tape: Tape) -> list[dict[str, Any]]:
    rows = []
    for extra, taker in [(0.0, 0.0)] + [(e, 0.0) for e in STRESS_EXTRA] + [(0.0, STRESS_TAKER)]:
        row = _public(runner(tape, extra, taker))
        row.update({"stop_extra": extra, "taker": taker or None})
        rows.append(row)
    return rows


def _paths(tape: Tape, base: AccountConfig, cand: Any) -> dict[str, dict[str, Any]]:
    from btc_perp.candidate import run_candidate

    b = baseline_replay(tape, base, keep_path=True)
    c = run_candidate(tape, cand)
    out: dict[str, dict[str, Any]] = {}
    for label, row in (("baseline", b), ("candidate", c)):
        equity = np.asarray(row["_equity"], np.float64)
        out[label] = {
            "row": _public(row),
            "bootstrap": block_bootstrap(equity),
            "half_year_windows": window_returns(equity),
        }
    return out


def _sha(path: Path) -> str:
    from btc_perp.causal import _sha256

    return str(_sha256(path))


def run_generalization(write_report: bool = True) -> dict[str, Any]:
    from btc_perp.candidate import load_candidate, run_candidate
    from btc_perp.causal import _provenance, lockout
    from btc_perp.config import load_config
    from btc_perp.tapes import DATA, load_tape

    needed = [DATA / "btcusdt_1m.npz", DATA / "funding.npz", DATA / "usdcny_frankfurter.json"]
    needed += [DATA / "assets" / f"{name}_1m.npz" for name in TAPES if name != "btc"]
    missing = [p.name for p in needed if not p.exists()]
    if missing:
        report: dict[str, Any] = {
            "verified": False,
            "reason": "行情文件不在 data/ 或 data/assets/，没有泛化结果；先运行 scripts/assets.py",
            "missing": missing,
        }
        if write_report:
            _write(report)
        return report

    base = load_config()
    cand = load_candidate()
    tapes = {name: load_tape(name) for name in TAPES}
    span = {
        name: {
            "hours": t.hours,
            "years": t.hours / 8766.0,
            "note": t.note,
            "zero_volume_minutes": int((t.qv == 0.0).sum()),
            "zero_volume_share": float((t.qv == 0.0).mean()),
            "first_ts": int(t.ts[0]),
            "last_ts": int(t.ts[-1]),
        }
        for name, t in tapes.items()
    }

    side_by_side = {}
    for name, tape in tapes.items():
        plain = baseline_replay(tape, base, keep_path=True)
        held = lockout(plain["_equity"], plain["_side"], tape.days, base.dd_flat, START_CNY)
        side_by_side[name] = {
            "baseline_zero_tune": {
                **_public(plain),
                "locked_at_end": held["locked_at_end"],
                "flat_days_at_end": held["flat_days_at_end"],
            },
            "candidate_pre_committed": _public(run_candidate(tape, cand)),
        }

    rows = candidate_grid(tapes, cand)
    pooled = choose(rows, TAPES)
    loo = leave_one_out(rows, TAPES)
    by_tape = {}
    for name in TAPES:
        sel = [r for r in rows if r["tape"] == name]
        by_tape[name] = {
            "cagr_median": float(np.median([r["cagr"] for r in sel])),
            "cagr_worst": float(min(r["cagr"] for r in sel)),
            "cagr_best": float(max(r["cagr"] for r in sel)),
            "min_ratio_median": float(np.median([r["min_equity_over_peak"] for r in sel])),
            "share_positive_cagr": float(np.mean([r["cagr"] > 0 for r in sel])),
            "share_min_ratio_above_half": float(np.mean([r["min_equity_over_peak"] > 0.5 for r in sel])),
        }
    pooled_cfg = _candidate_cfg(cand, pooled)
    pooled_rows = {name: _public(run_candidate(t, pooled_cfg)) for name, t in tapes.items()}

    btc = tapes["btc"]
    walk = walk_forward(btc, base)
    paths = {name: _paths(t, base, cand) for name, t in tapes.items()}

    def cand_runner(config: Any) -> Any:
        return lambda tape, extra, taker: run_candidate(tape, config, stop_extra=extra, taker=taker)

    def base_runner(tape: Tape, extra: float, taker: float) -> dict[str, Any]:
        return baseline_replay(tape, base, stop_extra=extra, taker=taker)

    stress = {
        name: {
            "baseline": _stress(base_runner, t),
            "candidate_pre_committed": _stress(cand_runner(cand), t),
            "candidate_pooled_pick": _stress(cand_runner(pooled_cfg), t),
        }
        for name, t in tapes.items()
    }

    positive_base = sum(1 for v in side_by_side.values() if v["baseline_zero_tune"]["cagr"] > 0)
    positive_cand = sum(1 for v in side_by_side.values() if v["candidate_pre_committed"]["cagr"] > 0)
    report = {
        "verified": True,
        "purpose": "Does the published BTC result carry to data it was not tuned on, and does a simpler model?",
        "tapes": span,
        "side_by_side": side_by_side,
        "candidate_config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(cand).items()},
        "grid": {"size": len(family()), "space": family(), "rows": rows, "by_tape": by_tape},
        "pooled_pick": {"point": pooled, "rows": pooled_rows, "in_sample_on_all_four_tapes": True},
        "leave_one_tape_out": loo,
        "baseline_walk_forward": walk,
        "distributions": paths,
        "stress": stress,
        "variants_examined": {
            "candidate_grid": len(family()),
            "baseline_walk_forward_family": walk["family_size"],
            "candidate_pre_committed": 1,
            "note": (
                "The candidate's pre-committed values were fixed before its first run. Development runs after that "
                "fixed a bug (an ATR warm-up NaN) and checked trades; no value was moved to improve BTC. The baseline "
                "itself came from a far larger search that was not recorded."
            ),
        },
        "summary": {
            "tapes_with_positive_cagr_baseline_zero_tune": positive_base,
            "tapes_with_positive_cagr_candidate": positive_cand,
            "tapes": len(TAPES),
            "no_clean_out_of_sample_on_btc_2020_2026": True,
            "reading": (
                "BTC 2020-2026 was used to choose the baseline, so no clean out-of-sample is left on it. "
                "Other assets and earlier BTC are the only untouched data, and they are far fewer independent "
                "trials than they look because crypto assets move together."
            ),
        },
        "inputs": {p.name: _sha(p) for p in needed},
        "provenance": _provenance(),
    }
    if write_report:
        _write(report)
    return report


def _write(report: dict[str, Any]) -> None:
    verified = bool(report.get("verified"))
    report.setdefault("completion", completion(data_validated=verified, path_complete=verified, economic_pass=False))
    publish(REPORT, report)
