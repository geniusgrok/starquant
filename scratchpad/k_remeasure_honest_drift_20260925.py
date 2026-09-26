"""k 的重测（2026-09-25）：p32h 的配对 bootstrap 按今天的换算因子重跑，另加「诚实漂移」与「换抵押品（K-4）」两组臂。

起因。操作者 2026-09-25 对「D-041 的去向与 k 的重裁」答「按建议处理」。建议里的第 2 步是 10-08 前裁 k
（`docs/analysis/2026-09-25-october-13-readiness.md` 第 2.2、3 节）。取值规则是 D-035 事先写下的那条：
**取自助 q95 回撤仍在声明预算内的最大 k，两个 universe 都要满足。** 预算 −70%，口径是可动用 USDT。
同日的独立体检（`docs/analysis/2026-09-25-backtest-guard-audit.md` 第一遍第一条）要求再加一臂：
把漂移打到诚实的样本外 Sharpe 1.2306，同一组 block 起点配对重跑。

零 ledger：只建面板、跑 bootstrap，不调任何 `research` 命令。只用 p32h 看过的 8 个 k（`p32g.K_GRID + p32h.EXTENDED`），
不加新格子。

定义
----
* **今天的换算因子** F = 1.747858609376565，即总权益峰值 ÷ 可动用 USDT 峰值（13,495.80 / 7,721.33，
  两个峰值都在 2026-09-23T05:00:29Z）。出处：`reports/daily/2026-09-25.json` 的
  `risk_budget.usdt_drawdown.vs_total_equity`，09-23、09-24 两份日报同值。在 `cycles.jsonl` 的副本上按日报
  同一段代码（`report_common._cycles` + `risk_budget.usdt_drawdown_state`）重算，逐位相同。钉成常数不现读，
  理由同 p32g：现读会让每次运行得到不同的答案。p32h 钉的是 09-22 盘中读数 1.7693（`FACTOR_0922`）。
* **可动用口径的档位**：`rescaled(k, budget=0.70 / F)` = ((−0.2803, 0.75k), (−0.4005, 0.50k))，base = k
  （`p32h.ladder_at_base`，实盘 `LiveEngine._risk_ladder` 传的就是在跑的 k）。
* **K-4（把 BTC 抵押品换成 USDT）**：换完之后可动用 = 总权益，F = 1，档位按同一条规则取
  `rescaled(k, budget=0.70)` = ((−0.49, 0.75k), (−0.70, 0.50k))，base = k。k=0.60 时它就是
  `Policy().drawdown_ladder`，即 p32h 的 `running` 臂（档位只差浮点噪声；2026-09-25 实测四组读数逐位相同）。
  k<0.60 时不能读 `running`：它的档位目标是绝对值 0.45 / 0.30，`rung_scalar` 换成乘数 min(1, 目标 / k)。
  k≤0.45 时第一档的乘数到 1，k≤0.30 时两档都到 1，0.25 与 0.20 上它就等于无梯。那是为 0.60 校准的档位
  留在更小的 k 上，不是这条规则在这个 k 上的样子。
* **诚实漂移**：整条 mark 序列（每根 bar 的净收益，回撤与 CAGR 都从它算）减一个常数 c，使
  mean / std(ddof=1) × √8760 = 1.2306419157745636。这个数取自 `tsmom-validation-20260919T081914Z.json` 的
  `oos_selection.oos_sharpe_annual`，口径同 `multiple_testing.sharpe_per_period` × √`bars_per_year("1h")`。
  std 与自相关不动。按 (universe, 带, k) 逐条序列算 c。realised 同减 c：mtm 尺子不读它，减不减输出都一样。
  另有一组敏感性臂 `prop`：各 k 按同一比例打折，比例 r = 1.2306 / 该 universe k=0.60 序列的 Sharpe。
* **配对**：block 起点照抄 p32h，`default_rng(SEED)`，每个 k 一组，
  `starts[d] = rng.integers(0, n - BLOCK, size=n // BLOCK)`，2000 draws。n 相同则起点相同。
  脚本断言：每个 universe 的全部臂，起点哈希只有一个。
* **数据末端**：`_load` 的 end 钉在 2026-09-22 17:00（不含），即最后一根 bar 开盘 16:00Z。
  这是 p32h 跑时的末端：D3 那次同日同数据的 `impact-{mode}.json` 记 range
  2021-01-01 00:00 -> 2026-09-22 16:00，共 50,177 根。序列长度 pit 49,456、static 49,457，与 p32h 的 `bars` 相同。
* **static 名单**：走 `p32h.panel`，钉在 `p32h.STATIC_P32G` 的 16 个名字。
* **再平衡带**：`d3` = 现行代码（#115 之后，`combine_books` 经 `banded` 带 D2 + D3，与实盘一致）；
  `d2` = profile 的 `portfolio.band_entry_multiple` 改成 1.0，即 p32h 跑时的 D2-only。

与 p32h 的面板对不上的地方，以及为什么
--------------------------------------
今天建的面板只在尾部与 09-23 保存的序列不同：pit 从 2026-09-03 12:00Z 起共 461 根，static 从 09-18 17:00Z 起。
原因是 09-23 修的数据同步（`starquant_cli/data_cmd.py` 的 `_pool_and_leavers`）补回了 TUTUSDT、CYSUSDT、LSKUSDT
缺的 K 线。把三者截回补数前的状态（TUT ≤ 09-03 11:00Z、CYS ≤ 09-04 06:00Z、LSK ≤ 09-18 16:00Z）再建，
只剩边界上 1–2 根、最大 1e-5 的差。在那份 09-23 的序列上，这里的 bootstrap 逐位复现 p32h 与 D3 那次的全精度输出，
每个 universe 12/12 行。复现需要那三份 09-23 的文件。它们 2026-09-25 起归档在
`reports/research/k-scan-20260923/`，传 `--reference-dir reports/research/k-scan-20260923` 即可。

输出
----
`<out>/panels-{mode}-{band}.npz`，以及 `<out>/k-remeasure-20260925.json`。后者是列表：第 0 项是 meta，其余每项一个臂。
取列表而非字典，是为了不被 `governance replay` 当成研究报告读（`governance_cmd._payloads` 只收字典）。
入库的 `reports/research/k-remeasure-honest-drift-20260925.json` 是这份输出去掉缩进后的同一内容（`json.loads` 相等）。
`by_factor` 对每个臂给三种换算：today（F）、0922（p32h 的）、unit（1.0）。与档位一致的读法是：
rungs=today 读 today，0922 读 0922，unit 读 unit；policy（running）读 today 即 K-0，读 unit 即 K-4 在 0.60 的对照。

复现
----
    PYTHONPATH=. .venv/bin/python scratchpad/k_remeasure_honest_drift_20260925.py --workers 12
    # 可选：--out DIR（默认 scratchpad/k-remeasure-20260925/，被 .gitignore 挡住）
    #       --reference-dir DIR：含 09-23 的 series-{pit,static}.npz、p32h-{pit,static}.json、
    #       kgrid-{pit,static}-2000.json 时，另跑 12 行对照并逐位比；归档目录是 reports/research/k-scan-20260923

跑多久（2026-09-25 实测，16 核机，nice 10）：建 4 组面板 197 秒（4 个进程并行，pit 每个 k 约 15 秒，static 约 3 秒）。
不带 `--reference-dir` 是 144 个臂，其中 96 个带梯子循环；带上是 168 个、104 个。机器空闲时循环臂单核每个 130–180 秒，
12 个 worker 约 20 分钟。那天同机另有一轮同类测量与 pytest，全程用了 2,229 秒。无梯臂向量化，每个约 1 秒。

零 ledger 的核对
----------------
1. 脚本开头与结尾各算一次 `reports/research/trials.jsonl` 的 sha256，不等就报错退出。两个值都写进 meta。
2. 若环境里没有设 `STARQUANT_TRIALS_LEDGER`，脚本把它指向 `<out>/ledger-must-not-exist.jsonl`，结尾断言该文件不存在。
3. 手工再核一次：`shasum -a 256 reports/research/trials.jsonl`，跑前跑后各一次。
   2026-09-25 两次都是 09245c344b922ddc2cf31258d7f85111bf3f6d46f7afd68e9f97f97ecd85599d。
写 ledger 的只有 `research_*_cmd` 与 `research_ledger_io`，本脚本的调用链（`p32d.panel_series`、`run_backtest`、
`ladder_step`）不经过它们。

p32f 的三条误差方向原样适用，都指向真实尾部更差：周块 bootstrap 抹掉多月 regime、换算假设亏损全落在 USDT、
CAGR 的绝对水平只有差值有意义。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p32d_ladder_bootstrap_pathwise as p32d
import p32h_k_sweep_at_the_base_in_force as p32h
from p32d_ladder_bootstrap_pathwise import BLOCK, SEED, ladder, rescaled
from p32e_ruler_divergence import drawdown_path
from p32f_usdt_denominated_budget import DECLARED_BUDGET
from p32g_which_k_holds_the_usdt_budget import K_GRID
from p32g_which_k_holds_the_usdt_budget import USDT_SHARE_AT_PEAK as SHARE_0922

from starquant_governance.policy import Policy

ROOT = Path(__file__).resolve().parents[1]
GRID = tuple(K_GRID) + tuple(p32h.EXTENDED)  # p32h 看过的 8 个 k，不多一个
END = "2026-09-22 17:00"  # `_load` 的 end（不含）：最后一根 bar 开盘 2026-09-22 16:00Z，p32h 跑时的末端
FACTOR_TODAY = 1.747858609376565  # reports/daily/2026-09-25.json -> risk_budget.usdt_drawdown.vs_total_equity
FACTOR_0922 = 1.0 / SHARE_0922  # p32h 的算术：factor = 1 / USDT_SHARE_AT_PEAK（1.7693）
FACTORS = {"today": FACTOR_TODAY, "0922": FACTOR_0922, "unit": 1.0}
HONEST_SHARPE = 1.2306419157745636  # tsmom-validation-20260919T081914Z.json -> oos_selection.oos_sharpe_annual
BARS_PER_YEAR = 8760.0  # starquant_alpha.panel.bars_per_year("1h")
DRAWS = 2000
SENSITIVITY_K = (0.30, 0.25, 0.20)
DECOMPOSITION_K = (0.30, 0.25)
LEDGER = ROOT / "reports" / "research" / "trials.jsonl"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annual_sharpe(x: np.ndarray) -> float:
    return float(np.mean(x) / np.std(x, ddof=1) * math.sqrt(BARS_PER_YEAR))


# ---------------------------------------------------------------- 面板 ----------------------------------------------


def build_panels(job: tuple[str, str, str]) -> dict[str, Any]:
    """一组 (universe, 带) 的 8 个 k，全部走 `p32h.panel` -> `p32d.panel_series`。

    三处钉住打在 `p32d` 的模块命名空间里（`panel_series` 在那里解析这些名字），并计数，钉住没生效就停。
    面板只读一次、在进程内复用：`panel_series` 每次调用都 `_load`，缓存命中与否写进返回值。
    """
    mode, band, out = job
    os.chdir(ROOT)  # panel_series 按相对路径读 config/*.yaml
    calls = {"load": 0, "load_cached": 0, "profile": 0}
    cache: dict[Any, Any] = {}
    original_load, original_yaml = p32d._load, p32d.load_yaml

    def load_to_p32h_end(root, symbols, interval, start, end, funding, *args, **kwargs):
        if start is not None or end is not None:
            raise RuntimeError(f"panel_series passed start/end ({start!r}, {end!r}); this pin assumes None/None")
        key = (root, tuple(symbols), interval, funding, args, tuple(sorted(kwargs.items())))
        calls["load"] += 1
        if key in cache:
            calls["load_cached"] += 1
            return cache[key]
        cache[key] = original_load(root, symbols, interval, start, END, funding, *args, **kwargs)
        return cache[key]

    def yaml_with_band(path):
        data = original_yaml(path)
        if str(path) == "config/live.demo.yaml":
            calls["profile"] += 1
            if band == "d2":
                data = copy.deepcopy(data)
                data["portfolio"]["band_entry_multiple"] = 1.0
        return data

    p32d._load, p32d.load_yaml = load_to_p32h_end, yaml_with_band
    series: dict[str, np.ndarray] = {}
    digests: dict[str, str] = {}
    shape: dict[str, Any] = {}
    try:
        for k in GRID:
            before = dict(calls)
            mark, realised = p32h.panel(mode, k)
            if calls["load"] != before["load"] + 1 or calls["profile"] != before["profile"] + 1:
                raise RuntimeError(f"a pin did not take at {mode}/{band}/k={k}: {before} -> {calls}")
            panel = next(iter(cache.values()))
            shape = {"panel_bars": len(panel.index), "first": str(panel.index[0]), "last": str(panel.index[-1]),
                     "symbols": len(panel.symbols)}
            series[f"k{k:.2f}_mark"], series[f"k{k:.2f}_realised"] = mark, realised
            digests[f"k{k:.2f}"] = hashlib.sha256(mark.tobytes() + realised.tobytes()).hexdigest()[:16]
    finally:
        p32d._load, p32d.load_yaml = original_load, original_yaml
    path = Path(out) / f"panels-{mode}-{band}.npz"
    np.savez(path, **series)
    return {"mode": mode, "band": band, "file": str(path), "digests": digests, "calls": calls, **shape,
            "series_bars": len(series[f"k{GRID[0]:.2f}_mark"])}


# ---------------------------------------------------------------- 臂 ------------------------------------------------


def q05_ci(sorted_b: np.ndarray) -> tuple[float, float]:
    """5% 分位的无分布 95% 区间：落在真分位之下的抽样数 ~ Binomial(n, 0.05)。只量 bootstrap 的抽样噪声。"""
    n = len(sorted_b)
    mu, sd = n * 0.05, math.sqrt(n * 0.05 * 0.95)
    lo, hi = math.floor(mu - 1.96 * sd), math.ceil(mu + 1.96 * sd)
    return float(sorted_b[max(lo - 1, 0)]), float(sorted_b[min(hi - 1, n - 1)])


def run_arm(task: dict[str, Any]) -> dict[str, Any]:
    """p32h 的 `run_arm`，多两件事：漂移可以换，换算一次给三种因子。梯子不另写，只调用。"""
    t0 = time.time()
    data = np.load(task["file"])
    mark = data[task["key"] + "_mark"].copy()
    realised = data[task["key"] + "_realised"].copy()
    n = len(mark)
    sharpe_before = annual_sharpe(mark)
    c = 0.0
    if task["drift"] != "orig":
        c = float(np.mean(mark) - float(task["target_sharpe"]) * np.std(mark, ddof=1) / math.sqrt(BARS_PER_YEAR))
        mark, realised = mark - c, realised - c
    blocks = n // BLOCK
    years = (blocks * BLOCK) / 8760.0
    rng = np.random.default_rng(SEED)  # p32h 的抽法，逐字
    starts = np.stack([rng.integers(0, n - BLOCK, size=blocks) for _ in range(DRAWS)])
    k, arm = task["k"], task["arm"]
    if arm == "ladder@k":
        share = {"today": 1.0 / FACTOR_TODAY, "0922": SHARE_0922, "unit": 1.0}[task["rungs"]]
        rungs = tuple(rescaled(k, budget=DECLARED_BUDGET * share))
    elif arm == "running":
        rungs = tuple(Policy().drawdown_ladder)
    else:
        rungs = ()
    policy = replace(Policy(), drawdown_ladder=rungs)
    b, cagr, raw, throttled = np.empty(DRAWS), np.empty(DRAWS), np.empty(DRAWS), np.zeros(DRAWS)
    trip = np.zeros(DRAWS, dtype=bool)
    for d, row in enumerate(starts):
        m = np.concatenate([mark[s : s + BLOCK] for s in row])
        if arm == "none":
            stepped = m  # 无档位时 ladder_step 每根给 scalar 1.0，1.0 * m 逐位等于 m
        else:
            r = np.concatenate([realised[s : s + BLOCK] for s in row])
            if arm == "running":
                stepped, scalars = ladder(m, r, policy, "mtm")  # p32h 的 running：base=K 的 p32d.ladder
            else:
                stepped, scalars = p32h.ladder_at_base(m, r, policy, "mtm", k)
            acting = scalars < 1.0 - 1e-9
            trip[d] = bool(acting.any())
            throttled[d] = float(acting.mean())
        b[d] = drawdown_path(np.cumprod(1.0 + stepped)).min()
        cagr[d] = np.prod(1.0 + stepped) ** (1.0 / years) - 1.0
        raw[d] = np.prod(1.0 + m) ** (1.0 / years) - 1.0
    q95 = float(np.percentile(b, 5))
    lo, hi = q05_ci(np.sort(b))
    by_factor = {}
    for name, factor in FACTORS.items():
        by_factor[name] = {
            "q95_usdt": q95 * factor,
            "p_past_70_usdt": float((b * factor <= -DECLARED_BUDGET).mean()),
            "q95_usdt_ci95": [lo * factor, hi * factor],
            "margin_pp": (q95 * factor + DECLARED_BUDGET) * 100.0,
        }
    return {
        **{key: task[key] for key in ("label", "set", "mode", "band", "k", "arm", "rungs", "drift")},
        "target_sharpe": task.get("target_sharpe"),
        "rung_values": [list(x) for x in rungs],
        "bars": n,
        "starts_sha": hashlib.sha256(starts.tobytes()).hexdigest()[:16],
        "drift_c_per_bar": c,
        "sharpe_series_before": sharpe_before,
        "sharpe_series_after": annual_sharpe(mark),
        "median_total": float(np.median(b)),
        "q95_total": q95,
        "cagr_median": float(np.median(cagr)),
        "ladder_cost_median": float(np.median(raw - cagr)),
        "draws_that_ever_tripped": float(trip.mean()),
        "throttled_bars_median": float(np.median(throttled)),
        "by_factor": by_factor,
        "seconds": round(time.time() - t0, 1),
    }


def tasks_for(panels: dict[tuple[str, str], str], sharpe_060: dict[str, float], sharpe_k: dict) -> list[dict[str, Any]]:
    """全部臂。循环臂在前（慢），向量化的无梯臂在后。"""
    out: list[dict[str, Any]] = []

    def add(set_, mode, band, k, arm, rungs, drift, target=None):
        label = f"{set_}|{mode}|{band}|k{k:.2f}|{arm}|{rungs}|{drift}"
        out.append({"label": label, "set": set_, "mode": mode, "band": band, "k": k, "arm": arm, "rungs": rungs,
                    "drift": drift, "file": panels[(mode, band)], "key": f"k{k:.2f}", "target_sharpe": target})

    for mode in ("pit", "static"):
        for drift in ("orig", "honest"):
            target = HONEST_SHARPE if drift == "honest" else None
            for k in GRID:
                add("main", mode, "d3", k, "ladder@k", "today", drift, target)  # 表 A / 表 B
                add("k4", mode, "d3", k, "ladder@k", "unit", drift, target)  # 表 K-4
            add("k0", mode, "d3", 0.60, "running", "policy", drift, target)  # K-0
        for k in GRID:
            add("bridge", mode, "d2", k, "ladder@k", "today", "orig")  # 桥：p32h 的 D2-only 带
        for k in DECOMPOSITION_K:
            add("decomp", mode, "d2", k, "ladder@k", "0922", "orig")  # 只补数据、不换因子
        add("decomp", mode, "d2", 0.60, "running", "policy", "orig")
        ratio = HONEST_SHARPE / sharpe_060[mode]
        for k in SENSITIVITY_K:
            add("sens", mode, "d3", k, "ladder@k", "today", "prop", ratio * sharpe_k[(mode, k)])
    for mode in ("pit", "static"):
        for drift in ("orig", "honest"):
            for k in GRID:
                add("none", mode, "d3", k, "none", "none", drift, HONEST_SHARPE if drift == "honest" else None)
        for k in GRID:
            add("none", mode, "d2", k, "none", "none", "orig")
    return out


# ---------------------------------------------------------------- 可选对照 -------------------------------------------


def reference_tasks(reference: Path) -> list[dict[str, Any]]:
    """09-23 保存的序列上重跑 12 行，逐位比 p32h 与 D3 那次的全精度输出。三份文件不在仓库里。"""
    out: list[dict[str, Any]] = []
    for mode in ("pit", "static"):
        file = str(reference / f"series-{mode}.npz")
        for band, k, arm, rungs in (
            ("d2", 0.30, "ladder@k", "0922"), ("d2", 0.25, "ladder@k", "0922"), ("d2", 0.60, "running", "policy"),
            ("d3", 0.25, "ladder@k", "0922"),
            *(("d2", k, "none", "none") for k in (0.60, 0.35, 0.30, 0.25)),
            *(("d3", k, "none", "none") for k in (0.60, 0.35, 0.30, 0.25)),
        ):
            out.append({"label": f"ref|{mode}|{band}|k{k:.2f}|{arm}|{rungs}|orig", "set": "ref", "mode": mode,
                        "band": band, "k": k, "arm": arm, "rungs": rungs, "drift": "orig", "file": file,
                        "key": f"k{k:.2f}_{band}", "target_sharpe": None})
    return out


def check_reference(rows: list[dict[str, Any]], reference: Path) -> dict[str, Any]:
    arm_names = {"ladder@k": "ladder@k", "running": "running", "none": "no ladder"}
    result: dict[str, Any] = {}
    for mode in ("pit", "static"):
        pub = {(r["k"], r["arm"]): r for r in json.loads((reference / f"p32h-{mode}.json").read_text())["rows"]}
        d3 = {(r["k"], r["series"], r["arm"]): r for r in json.loads((reference / f"kgrid-{mode}-2000.json").read_text())}
        same, total, misses = 0, 0, []
        for row in (r for r in rows if r["set"] == "ref" and r["mode"] == mode):
            want = pub[(row["k"], arm_names[row["arm"]])] if row["band"] == "d2" else d3[(row["k"], "d3", arm_names[row["arm"]])]
            got = (row["median_total"], row["q95_total"], row["cagr_median"], row["by_factor"]["0922"]["q95_usdt"],
                   row["by_factor"]["0922"]["p_past_70_usdt"])
            exp = (want["median_total"], want["q95_total"], want["cagr_median"], want["q95_usdt"], want["p_past_70_usdt"])
            total += 1
            if got == exp:
                same += 1
            else:
                misses.append({"label": row["label"], "got": got, "want": exp})
        result[mode] = {"identical": same, "rows": total, "misses": misses}
    return result


# ---------------------------------------------------------------- 表与规则 -------------------------------------------


def reading(row: dict[str, Any], factor: str) -> dict[str, Any]:
    f = row["by_factor"][factor]
    return {"q95": f["q95_usdt"], "p": f["p_past_70_usdt"], "cagr": row["cagr_median"], "margin": f["margin_pp"],
            "ci": f["q95_usdt_ci95"], "holds": f["q95_usdt"] >= -DECLARED_BUDGET}


def crossing(points: list[tuple[float, float, float]], target: float) -> tuple[float, float] | None:
    """p32h.crossing 的同一算术：沿 k 线性插值。只作读数，不是网格点。"""
    for (k1, q1, c1), (k2, q2, c2) in pairwise(sorted(points, key=lambda p: -p[0])):
        if q1 < target <= q2:
            t = (target - q1) / (q2 - q1)
            return k1 + t * (k2 - k1), c1 + t * (c2 - c1)
    return None


def d035(table: dict[tuple[str, float], dict[str, Any]]) -> dict[str, Any]:
    """D-035：两个 universe 的 q95(USDT) 都 >= -70% 的最大网格 k。余量按 pp 给，不替谁圆。"""
    holds = [k for k in GRID if table[("pit", k)]["holds"] and table[("static", k)]["holds"]]
    best = max(holds) if holds else None
    out: dict[str, Any] = {"k": best}
    if best is not None:
        out["margin_pp"] = {m: table[(m, best)]["margin"] for m in ("pit", "static")}
        above = [k for k in GRID if k > best]
        if above:
            out["next_up"] = {"k": min(above), "margin_pp": {m: table[(m, min(above))]["margin"] for m in ("pit", "static")}}
    out["interpolated"] = {
        m: crossing([(k, table[(m, k)]["q95"], table[(m, k)]["cagr"]) for k in GRID], -DECLARED_BUDGET)
        for m in ("pit", "static")
    }
    return out


def print_table(title: str, table: dict[tuple[str, float], dict[str, Any]], rule: dict[str, Any]) -> None:
    print(f"\n== {title}")
    print(f"{'k':>5} | {'pit q95':>8} {'P>70':>6} {'CAGR':>7} | {'static q95':>10} {'P>70':>6} {'CAGR':>7} | 两边都守住  最小余量")
    for k in GRID:
        p, s = table[("pit", k)], table[("static", k)]
        print(f"{k:>5.2f} | {p['q95']:>8.2%} {p['p']:>6.2%} {p['cagr']:>7.1%} | {s['q95']:>10.2%} {s['p']:>6.2%} "
              f"{s['cagr']:>7.1%} | {'YES' if p['holds'] and s['holds'] else 'no':>6}  {min(p['margin'], s['margin']):+.2f}pp")
    print(f"   D-035 -> {rule}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=str(ROOT / "scratchpad" / "k-remeasure-20260925"))
    parser.add_argument("--reference-dir", default="")
    args = parser.parse_args()
    os.chdir(ROOT)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sentinel = None
    if not os.environ.get("STARQUANT_TRIALS_LEDGER"):
        sentinel = out / "ledger-must-not-exist.jsonl"
        os.environ["STARQUANT_TRIALS_LEDGER"] = str(sentinel)
    ledger_before = _sha(LEDGER)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"HEAD {head}; trials.jsonl sha256 before {ledger_before}")
    print(f"factor today {FACTOR_TODAY!r} (p32h: {FACTOR_0922!r}); honest Sharpe {HONEST_SHARPE!r}; end {END} (exclusive)")

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=min(4, args.workers)) as pool:
        built = list(pool.map(build_panels, [(m, b, str(out)) for m in ("pit", "static") for b in ("d2", "d3")]))
    for item in built:
        print(f"  panels {item['mode']}/{item['band']}: {item['series_bars']} bars of {item['panel_bars']} "
              f"({item['first']} -> {item['last']}, {item['symbols']} symbols) calls {item['calls']}")
    panels = {(i["mode"], i["band"]): i["file"] for i in built}
    sharpe_k = {}
    for mode in ("pit", "static"):
        data = np.load(panels[(mode, "d3")])
        for k in GRID:
            sharpe_k[(mode, k)] = annual_sharpe(data[f"k{k:.2f}_mark"])
    tasks = tasks_for(panels, {m: sharpe_k[(m, 0.60)] for m in ("pit", "static")}, sharpe_k)
    if args.reference_dir:
        tasks += reference_tasks(Path(args.reference_dir))
    print(f"panels built in {time.time() - t0:.0f}s; {len(tasks)} arms, {sum(t['arm'] != 'none' for t in tasks)} with a ladder loop")

    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_arm, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            if i % 10 == 0 or i == len(tasks):
                print(f"  [{i}/{len(tasks)} {time.time() - t0:5.0f}s] {row['label']}", flush=True)
    order = {t["label"]: i for i, t in enumerate(tasks)}
    rows.sort(key=lambda r: order[r["label"]])
    by = {r["label"]: r for r in rows}

    for mode in ("pit", "static"):
        shas = {r["starts_sha"] for r in rows if r["mode"] == mode}
        if len(shas) != 1:
            raise RuntimeError(f"{mode}: arms drew from {len(shas)} different sets of block starts: {shas}")

    def table(set_: str, band: str, rungs: str, drift: str, factor: str) -> dict[tuple[str, float], dict[str, Any]]:
        return {(m, k): reading(by[f"{set_}|{m}|{band}|k{k:.2f}|ladder@k|{rungs}|{drift}"], factor)
                for m in ("pit", "static") for k in GRID}

    tables = {
        "A_orig_d3_today": table("main", "d3", "today", "orig", "today"),
        "B_honest_d3_today": table("main", "d3", "today", "honest", "today"),
        "K4_orig_d3_unit": table("k4", "d3", "unit", "orig", "unit"),
        "K4_honest_d3_unit": table("k4", "d3", "unit", "honest", "unit"),
        "C_bridge_orig_d2_today": table("bridge", "d2", "today", "orig", "today"),
    }
    rules = {name: d035(t) for name, t in tables.items()}
    for name, t in tables.items():
        print_table(name, t, rules[name])

    ledger_after = _sha(LEDGER)
    if ledger_after != ledger_before:
        raise RuntimeError(f"trials.jsonl changed during the run: {ledger_before} -> {ledger_after}")
    if sentinel is not None and sentinel.exists():
        raise RuntimeError(f"something wrote a ledger row to {sentinel}")
    meta = {
        "kind": "meta",
        "script": "scratchpad/k_remeasure_honest_drift_20260925.py",
        "head": head,
        "grid": list(GRID),
        "end_exclusive": END,
        "factor_today": FACTOR_TODAY,
        "factor_0922": FACTOR_0922,
        "honest_sharpe": HONEST_SHARPE,
        "draws": DRAWS,
        "seed": SEED,
        "block": BLOCK,
        "static_universe": list(p32h.STATIC_P32G),
        "panels": [{k: v for k, v in item.items() if k != "file"} for item in built],
        "starts_sha": {m: next(r["starts_sha"] for r in rows if r["mode"] == m) for m in ("pit", "static")},
        "d035": rules,
        "trials_sha256_before": ledger_before,
        "trials_sha256_after": ledger_after,
        "ledger_sentinel_checked": sentinel is not None,
    }
    if args.reference_dir:
        meta["reference_check"] = check_reference(rows, Path(args.reference_dir))
        print(f"\nreference check (09-23 series): {meta['reference_check']}")
    path = out / "k-remeasure-20260925.json"
    path.write_text(json.dumps([meta, *rows], indent=1), encoding="utf-8")
    print(f"\ntrials.jsonl sha256 after {ledger_after} (unchanged); wrote {path} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
