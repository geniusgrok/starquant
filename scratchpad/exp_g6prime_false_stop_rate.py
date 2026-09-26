"""EXP-G6′: does R5's k=2 fire on noise?  Pre-registered 2026-09-12 at commit 6e87e7ed.

Two arms, both run and both reported:
  A (the plan's caliber)   stop at -2.0 sigma of the 30-day attributed P&L
  B (the measured caliber) stop at -14.56 sigma (flow) / -7.26 sigma (tsmom), measured on 214 live cycles

The rule is simulated AS WRITTEN: a rolling 720-hour sum of attributed P&L, judged every cycle, not
one draw per window.  That distinction is the point - overlapping looks cross a threshold far more
often than a single draw does, and the plan's 2.3% / 0.64% are single-draw normal approximations.
"""

from __future__ import annotations

import math

import numpy as np

SEED = 20260912
PATHS = 20_000
WINDOW_HOURS = 720          # 30 days
LIFE_WINDOWS = 9            # sec 3: a probe reaches main or retires within 9 windows
HOURS_PER_YEAR = 8760.0
SHARPES = (0.0, 1.7)
ARMS = {"A 方案口径 (-2.00σ)": 2.00, "B 实测口径 flow (-14.56σ)": 14.56, "B′ 实测口径 main (-7.26σ)": 7.26}


def simulate(sharpe: float, stop_sigmas: float, rng: np.random.Generator) -> tuple[float, float]:
    """(P(stopped within 9 windows), P(stopped within 1 window)) under the real rolling rule.

    Work in units of the hourly standard deviation, so the answer depends only on `stop_sigmas` and
    the Sharpe - not on the equity or on sigma itself.  The stop is `rolling_720_sum < -k * sigma_30d`
    and sigma_30d = sigma_h * sqrt(720), so the bar in hourly units is -k * sqrt(720).
    """
    mu_h = sharpe / math.sqrt(HOURS_PER_YEAR)          # drift per hour, in sigma_h units
    bar = -stop_sigmas * math.sqrt(WINDOW_HOURS)       # threshold on the 720-hour SUM, in sigma_h units
    total = LIFE_WINDOWS * WINDOW_HOURS
    stopped_life = 0
    stopped_first = 0
    chunk = 500
    for start in range(0, PATHS, chunk):
        n = min(chunk, PATHS - start)
        steps = rng.normal(mu_h, 1.0, size=(n, total))
        cumulative = np.cumsum(steps, axis=1)
        # rolling 720-hour sum, only defined once 720 hours exist (a probe cannot be stopped on
        # a window it has not yet lived - the same "no reading is not a breach" rule)
        rolling = cumulative[:, WINDOW_HOURS - 1 :].copy()
        rolling[:, 1:] -= cumulative[:, : total - WINDOW_HOURS]
        hit = rolling <= bar
        stopped_life += int(hit.any(axis=1).sum())
        stopped_first += int(hit[:, :WINDOW_HOURS].any(axis=1).sum())
    return stopped_life / PATHS, stopped_first / PATHS


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(f"EXP-G6′  paths={PATHS}  seed={SEED}  life={LIFE_WINDOWS} windows x {WINDOW_HOURS}h\n")
    print(f"{'arm':28s} {'Sharpe':>7s} {'①9窗口内被stop':>15s} {'③单窗口':>10s} {'②连续两个都stop (R5)':>22s}")
    rows = {}
    for arm, sigmas in ARMS.items():
        for sharpe in SHARPES:
            life, first = simulate(sharpe, sigmas, rng)
            rows[(arm, sharpe)] = (life, first)
            print(f"{arm:28s} {sharpe:7.1f} {life:15.4%} {first:10.4%} {life * life:22.6%}")
    print("\n方案 §3 的表（E5 正态近似，单窗口）：Sharpe-0 2.3% / Sharpe-1.7 0.64%")
    a0 = rows[("A 方案口径 (-2.00σ)", 0.0)][1]
    a17 = rows[("A 方案口径 (-2.00σ)", 1.7)][1]
    print(f"臂 A 单窗口实算：Sharpe-0 {a0:.4%} / Sharpe-1.7 {a17:.4%}")
    for name, mine, theirs in (("Sharpe-0", a0, 0.023), ("Sharpe-1.7", a17, 0.0064)):
        rel = abs(mine - theirs) / theirs
        print(f"  F1 {name}: 相对误差 {rel:.1%}  -> {'触发' if rel > 0.5 else '未触发'}")
    b_life = rows[("B 实测口径 flow (-14.56σ)", 0.0)][0]
    b_pair = b_life * b_life
    print(f"\n  F2 臂 B 连续两个都 stop = {b_pair:.6%}  -> {'触发' if b_pair > 0.01 else '未触发'}")
    print(f"  F3 臂 B 单个 probe 被 stop = {b_life:.6%}  -> {'触发' if b_life < 0.001 else '未触发'}")


main()


def addendum() -> None:
    """The §3 discrimination table, recomputed under the rule as written (arm A's caliber)."""
    global LIFE_WINDOWS
    rng = np.random.default_rng(SEED + 1)
    print("\n=== §3 的鉴别力表，按真实规则重算（臂 A 口径 −2σ）===")
    print(f"{'窗口数':>6s} {'Sharpe-0 到 main':>18s} {'Sharpe-1.7 到 main':>20s} {'鉴别比':>8s}   方案写的")
    plan = {3: (0.932, 0.981, 1.05), 9: (0.810, 0.944, 1.17)}
    for windows in (3, 9):
        LIFE_WINDOWS = windows
        s0 = 1.0 - simulate(0.0, 2.00, rng)[0]
        s17 = 1.0 - simulate(1.7, 2.00, rng)[0]
        p0, p17, pr = plan[windows]
        print(f"{windows:6d} {s0:18.1%} {s17:20.1%} {s17 / s0:8.2f}   {p0:.1%} / {p17:.1%} / {pr:.2f}")


addendum()
print("\n=== 要让停损落在 −2σ 上，σ 需要多大 ===")
for name, stop, sd30 in (("flow", 0.02, 0.001373), ("main", 0.06, 0.008266)):
    print(f"  {name:5s} 需要 30 天 σ = {stop / 2:.4%}，实测 {sd30:.4%}，需放大 {stop / 2 / sd30:.1f}x")
