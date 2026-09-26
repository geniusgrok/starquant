"""8.R：两条在跑的状态规则的确认延迟——flow 的 `short_gate` 与风险预算阶梯的两周期宽限。

外部清单 8.R 问：regime 在事后总是清楚的，在当下总是模糊的；按当时能拿到的数据，每次切换要多久才能
确认？这个延迟常常大到吞掉整个超额收益。清点（docs/analysis/2026-09-23-external-prompt-checklist-vs-
starquant.md 的 8.R）判「部分」：在跑的这两条状态规则，确认延迟都没量过。读数与结论记在
docs/RESEARCH_LOG.md「2026-09-25 · 8.R：两条在跑的状态规则的确认延迟」。

复现（在仓库根目录，worktree 也一样）：

    PYTHONPATH=$PWD .venv/bin/python scratchpad/regime_confirmation_lag.py [flow|ladder|ruler|all]

主 checkout 经 editable 安装的 .pth 也在 sys.path 上，所以 `PYTHONPATH` 写上，脚本开头也把仓库根插到
最前。第一行打印 `starquant_alpha` 从哪里加载，用来核这一条。`all` 在 2026-09-25 跑了 3 分 41 秒。

零 ledger。只调库函数，不走任何 `research` 命令，不写任何文件。档案、membership 与实盘记录都只读，
读的是 p32e 的 `SHARED` 下那一份。面板钉在 `END`：档案每天追加，不钉就复现不了。

**一、flow 的 `short_gate`（`flow`）。**

规则：flow 分数为负，且门的动量 >= `short_gate` 时，空头换成 0，即平仓（`starquant_alpha/signals/flow.py:148`）。
门的动量是 `tsmom_scores`，参数取 registry：0.3，horizon 168/336/720，权重 0.2/0.3/0.5。它只读 t 及以前的
收盘价，是因果的。下文「门开」指动量 >= 0.3。

事后状态（真实 regime）要用未来的价格，是一个选择，所以给两个：

- A（主）：同一个指标，每个 horizon 的收益窗口挪到以 t 为中心，阈值同为 0.3。短于 24 根的开段与关段
  当噪声并掉（`debounce`）。
- B（替代）：拐点。价格从谷底涨 20% 才确认谷底，从峰顶跌 20% 才确认峰顶；谷底到峰顶记为上涨 regime
  （`zigzag_up`）。它不借用门的指标。

延迟：对每段事后 regime [s, e) 数门要等几根（`episodes` 的 docstring 有全部规则）。开启时门在 s-1 与 s
都已开，记「已在」；段内一直没开，记「漏掉」。结束只看门在段内开过的段；门在 e-1 与 e 都已关，记「已关」。

代价：flow_short sleeve 的权重是账户权益的比例（已乘 fraction 1/3）。每个变体单独跑 `run_backtest`，
逐 bar 相加、不复利，成本与资金费在内，5.65 年。「无门」是 `short_gate` 0；「事后门」是同一道门，开关按
事后状态（事后状态无定义的格退回因果动量）。开启等待期是 [s, 门第一次开)，看在跑的 sleeve 持有的空头；
结束等待期是 [e, 门第一次关)，看无门 sleeve 持有、被门挡掉的空头。整本书那一段照 `p32d.panel_series`
的构造，只把 flow 的 targets 换掉。

2026-09-25 的读数（`END` 2026-09-24，pit，212 个标的，50,208 根）。延迟单位是小时：

    A 开启 688 段：已在 23%，漏掉 22%，要等的 380 段  q25 39  中位 110  q75 182  q90 270
    A 结束 660 段：已关 18%，            要等的 540 段  q25 48  中位 102  q75 161  q90 191
    B 开启 1458 段：已在 19%，漏掉 40%，要等的 606 段  q25 43  中位 131  q75 285  q90 424
    B 结束 932 段：已关 3%，截尾 1，     要等的 900 段  q25 24  中位  84  q75 184  q90 306
    敏感性（等待中位，开启/结束）：居中最短 1/24/72 根 22/90、110/102、153/100；
                                   拐点 10%/20%/30% 40/86、131/84、208/94

    sleeve（权益的百分比）   合计      每年     夏普
    无门                    +23.78%   +4.21%   0.32
    在跑的门                +30.67%   +5.43%   0.51
    事后门 A               +135.11%  +23.92%   2.09
    事后门 B               +308.83%  +54.67%   6.26
    门的净贡献 +6.89%，每年 +1.22%，NW t 0.47（15 阶）/ 0.48（168 阶）

                                     A                   B
    开启等待期，门放行的空头   -34.89%（每年 -6.18%）  -109.88%（-19.45%）
    漏掉的段，门放行的空头      -4.62%（-0.82%）       -125.09%（-22.14%）
    结束等待期，门挡掉的空头   +10.89%（+1.93%）        +40.41%（+7.15%）
    在跑的门拿到事后门的        6.2%                     2.4%

    整本书（k=0.60）：无门每年 +98.76%、夏普 1.700；在跑 +101.38%、1.691；
    门每年 +2.61%，NW t 0.92（15 阶）/ 0.94（168 阶）

门的净贡献还按格子拆成互斥的六块，相加回到总数，脚本核过（读数见 RESEARCH_LOG）。

机械检查，全过才往下走：在跑的分数 == 无门分数按因果动量挡掉空头之后（逐位）；`momentum_score`
不居中时 == `tsmom_scores`（逐位）；`held_of` == `strategy_targets` 的 flow（逐位）；flow-only 的 sleeve
== 整本模型里的 flow_short（逐位）；整本书的在跑一侧 == `p32d.panel_series` 的 mark（差 2.8e-17）。
门的分母 `max(vol, return_scale)` 在 242 格上取到 vol，全是 LUNAUSDT 2022-05-11..21；居中版本不挪分母，
只在这些格上是近似。

**二、风险预算阶梯（`ladder`）。**

档位 ((-0.49, 0.45), (-0.70, 0.30))，宽限 2 个周期（`starquant_governance/policy.py:219`）：`ladder_step`
第三个连续在档位上的周期才生效（`starquant_alpha/overlays/ladder.py:145`）。`replay` 用的就是它，`base`
取所跑的 k，读盯市回撤。`delay=0` 是 p32 系列的约定（决定第 t 根时读到 t-1 收盘），`delay=1` 是实盘
的时序（见第三部分）。`delay=0` 的 scalar 与 `p32h.ladder_at_base` 逐位相同，脚本核过。

    universe  k     历史最大回撤   越档（实盘时序 / p32 约定）
    pit       0.60  -39.85%        0 / 0
    pit       0.80  -48.42%        0 / 0
    pit       0.85  -51.30%        5 / 5
    pit       0.90  -54.53%        66 / 46
    static    0.60  -37.48%        0 / 0
    static    0.90  -47.85%        0 / 0
    k=0.60 换成 policy 0.3.3 之前的档位（-35% 起）：pit 越档 38 次，static 11 次

在跑的档位在历史路径上没有越过一次，所以「越档到生效之间的回撤增量」没有样本。别的 k 与别的档位
只数次数，不量增量。

**三、归因回撤尺子（`ruler`）。**

读 `.starquant/live/cycles.jsonl` 与 `attribution.jsonl`，钉到 `LIVE_PIN` 那一行。两条：

- 第 n 个周期的读数 == `attributed_drawdown_state(前 n-1 行, 挂在第 n-1 行及以前的收入)`：364/364，差 0。
  所以未实现盈亏晚一个周期，阶梯从越档到生效实际隔 3 根 bar，不是 2 根。
- 第 k 行的 `unrealized` 是下单前的快照，挂在第 k 行的收入是下单后实现的，已实现盈亏因此算了两次。
  每条收入改放到收进它的那一行（`ruler_section` 的 docstring），与记录的读数比：331/364 个周期不同，
  读数最多深 1.58pp、最多浅 0.51pp、平均深 0.27pp；高水位每个周期都偏高，最多 226.89 USDT；
  2026-09-24T18:00Z 那一行读数 -4.17%，不重复的口径 -2.89%。
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p32d_ladder_bootstrap_pathwise as p32d
import p32h_k_sweep_at_the_base_in_force as p32h
from p32e_ruler_divergence import DATA, SHARED, drawdown_path

from starquant_alpha.backtest import BacktestResult, run_backtest
from starquant_alpha.features import realized_vol, returns
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.overlays.ladder import ladder_step
from starquant_alpha.panel import Panel
from starquant_alpha.signals import scores_to_targets
from starquant_alpha.signals.flow import FlowParams, flow_scores
from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores
from starquant_alpha.validation.metrics import newey_west_tstat
from starquant_cli.research_panel import _load, _membership, _resolve_symbols
from starquant_governance.policy import Policy
from starquant_live.composition import build_model, cost_model, load_registry
from starquant_live.risk_budget import RiskBudgetParams, attributed_drawdown_state
from starquant_shared.config import load_yaml

#: 面板的终点，按 bar 开盘时刻取「小于」：最后一根是 2026-09-23 23:00Z。档案每天追加，钉住才能复现。
END = "2026-09-24"
#: 事后状态 A 的最短 regime：短于它的开段与关段都按噪声并掉。
MIN_REGIME_BARS = 24
#: 事后状态 B 的拐点阈值：从谷底涨 20% 才确认谷底，从峰顶跌 20% 才确认峰顶。
ZIGZAG_THETA = 0.20
#: 敏感性表：只量延迟，不量收益。
SENSITIVITY_MIN_BARS = (1, 24, 72)
SENSITIVITY_THETA = (0.10, 0.20, 0.30)
#: 阶梯那一节扫的 k。0.60 是在跑的值。
K_SCAN = (0.60, 0.70, 0.75, 0.80, 0.85, 0.90)
#: 尺子那一节读的实盘记录，钉到这根 bar（含）为止。
LIVE_PIN = "2026-09-24T18:00:00+00:00"
LIVE = SHARED / ".starquant/live"
HOURS_PER_DAY = 24.0


# --- 通用 ---------------------------------------------------------------------------------------------
def same_bits(a: pd.DataFrame | np.ndarray, b: pd.DataFrame | np.ndarray) -> bool:
    """逐位相同：按 uint64 视图比，NaN 的位型也算在内。"""
    x = np.ascontiguousarray(np.asarray(a, dtype=float)).view(np.uint64)
    y = np.ascontiguousarray(np.asarray(b, dtype=float)).view(np.uint64)
    return x.shape == y.shape and bool((x == y).all())


def true_runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """布尔序列里每段 True 的 [起点, 终点)。"""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)


def quantiles(values: list[int]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return {"n": 0}
    q10, q25, q50, q75, q90 = np.percentile(arr, [10, 25, 50, 75, 90])
    return {"n": int(arr.size), "mean": float(arr.mean()), "q10": q10, "q25": q25, "q50": q50, "q75": q75, "q90": q90}


def fmt_q(q: dict[str, float]) -> str:
    if not q.get("n"):
        return "n=0"
    return (
        f"n={q['n']:>4}  q10 {q['q10']:>5.0f}  q25 {q['q25']:>5.0f}  中位 {q['q50']:>5.0f}  "
        f"q75 {q['q75']:>5.0f}  q90 {q['q90']:>5.0f}  均值 {q['mean']:>6.1f}  (中位 {q['q50'] / HOURS_PER_DAY:.1f} 天)"
    )


# --- 事后状态 ---------------------------------------------------------------------------------------------
def momentum_score(close: pd.DataFrame, p: TsmomParams, *, centred: bool) -> pd.DataFrame:
    """`tsmom_scores` 的逐行复写；`centred=True` 把每个 horizon 的收益窗口挪到以 t 为中心。

    `centred=False` 必须与 `tsmom_scores` 逐位相同，`flow_section` 开头核这一条。居中时只挪收益，
    分母不挪。分母是 `max(vol, return_scale)`，这块面板上只有 242 格取到 vol（LUNAUSDT 2022-05），
    其余都是 `return_scale` 本身。
    """
    vol = realized_vol(close, window=p.vol_window, ddof=0)
    denominator = vol.clip(lower=p.return_scale).clip(lower=1e-12)
    weight_total = float(sum(p.horizon_weights))
    momentum_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    slope_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    sign_sum = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    valid = pd.DataFrame(True, index=close.index, columns=close.columns)
    for horizon, weight in zip(p.horizons, p.horizon_weights, strict=True):
        ret = returns(close, horizon)
        if centred:
            ret = ret.shift(-(horizon // 2))
        momentum_h = pd.DataFrame(
            np.tanh((ret / denominator).to_numpy(dtype=float)), index=close.index, columns=close.columns
        )
        slope_h = pd.DataFrame(
            np.tanh(((ret / horizon) / p.slope_scale).to_numpy(dtype=float)), index=close.index, columns=close.columns
        )
        valid &= momentum_h.notna()
        momentum_sum = momentum_sum + momentum_h.fillna(0.0) * weight
        slope_sum = slope_sum + slope_h.fillna(0.0) * weight
        sign_sum = sign_sum + momentum_h.fillna(0.0).apply(np.sign)
    momentum = momentum_sum / weight_total
    slope = slope_sum / weight_total
    persistence = (sign_sum / len(p.horizons)).abs()
    direction = pd.DataFrame(np.where(momentum >= 0, 1.0, -1.0), index=close.index, columns=close.columns)
    component_weight = p.return_weight + p.slope_weight + p.persistence_weight
    score = (
        momentum * p.return_weight + slope * p.slope_weight + persistence * direction * p.persistence_weight
    ) / component_weight
    return score.clip(-1.0, 1.0).where(valid)


def debounce(on: np.ndarray, defined: np.ndarray, min_bars: int) -> np.ndarray:
    """先把两段开之间短于 `min_bars` 的关段补成开，再删掉短于 `min_bars` 的开段；不跨未定义的 bar。"""
    out = on & defined
    if min_bars <= 1:
        return out
    starts, ends = true_runs(defined & ~out)
    for a, b in zip(starts, ends, strict=True):
        if b - a < min_bars and a > 0 and b < len(out) and out[a - 1] and out[b]:
            out[a:b] = True
    starts, ends = true_runs(out)
    for a, b in zip(starts, ends, strict=True):
        if b - a < min_bars:
            out[a:b] = False
    return out


def zigzag_up(close: np.ndarray, theta: float) -> np.ndarray:
    """拐点：确认过的上涨段 [谷底, 峰顶) 记 1，下跌段记 0，首尾没确认的段记 NaN。"""
    state = np.full(len(close), np.nan)
    valid = np.flatnonzero(~np.isnan(close))
    if valid.size < 2:
        return state
    turns: list[tuple[int, bool]] = []  # (位置, 是不是谷底)
    hi = lo = int(valid[0])
    direction = 0
    for i in valid[1:]:
        price = close[i]
        if direction >= 0 and price > close[hi]:
            hi = int(i)
        if direction <= 0 and price < close[lo]:
            lo = int(i)
        if direction <= 0 and price >= close[lo] * (1.0 + theta):
            turns.append((lo, True))
            direction, hi = 1, int(i)
        elif direction >= 0 and price <= close[hi] * (1.0 - theta):
            turns.append((hi, False))
            direction, lo = -1, int(i)
    for (a, trough), (b, _) in pairwise(turns):
        state[a:b] = 1.0 if trough else 0.0
    return state


# --- 事件：事后切换 -> 门的切换 --------------------------------------------------------------------------------
def episodes(
    causal: np.ndarray, causal_def: np.ndarray, truth: np.ndarray, truth_def: np.ndarray, gate: np.ndarray
) -> dict[str, Any]:
    """一个标的上，每段事后 regime [s, e) 的开启延迟与结束延迟，以及对应的 bar 窗口。

    只算两端都有定义的段：s-1 与 e 的事后状态有定义，段没有被样本边界或未确认的拐点截断。
    开启：只算 s 在 universe 里的段。门在 s-1 与 s 都开着，记「已在」：门开在 regime 之前，不用等。
    否则取段内门第一次打开的那根，延迟 = 它 - s（同一根打开记 0）；段内一直没开，记「漏掉」，整段
    都是放行窗口。
    结束：只算门在段内开过、e 在 universe 里的段。门在 e-1 与 e 都关着，记「已关」。否则取 e 之后门第
    一次关上的那根，延迟 = 它 - e；到样本末尾还没关，记「截尾」。
    """
    n = len(causal)
    out: dict[str, Any] = {
        "onset": [], "already_on": 0, "missed": 0, "exit": [], "already_off": 0, "censored": 0,
        "entry_window": np.zeros(n, dtype=bool), "missed_window": np.zeros(n, dtype=bool),
        "exit_window": np.zeros(n, dtype=bool),
    }
    starts, ends = true_runs(truth)
    for s, e in zip(starts, ends, strict=True):
        if s == 0 or e >= n or not (truth_def[s - 1] and truth_def[e]):
            continue
        if gate[s] and causal_def[s]:
            if causal[s - 1] and causal[s]:
                out["already_on"] += 1
            else:
                inside = np.flatnonzero(causal[s:e])
                if inside.size:
                    out["onset"].append(int(inside[0]))
                    out["entry_window"][s : s + int(inside[0])] = True
                else:
                    out["missed"] += 1
                    out["missed_window"][s:e] = True
        if gate[e] and causal_def[e] and causal[s:e].any():
            if not (causal[e - 1] or causal[e]):
                out["already_off"] += 1
            else:
                after = np.flatnonzero(~causal[e:])
                if after.size:
                    out["exit"].append(int(after[0]))
                    out["exit_window"][e : e + int(after[0])] = True
                else:
                    out["censored"] += 1
    return out


def collect(
    causal: np.ndarray, causal_def: np.ndarray, truth: np.ndarray, truth_def: np.ndarray, gate: np.ndarray
) -> dict[str, Any]:
    """逐列跑 `episodes` 再汇总；窗口按 (bar, 标的) 摆回二维。"""
    total: dict[str, Any] = {"onset": [], "exit": [], "already_on": 0, "missed": 0, "already_off": 0, "censored": 0}
    windows = {name: np.zeros(causal.shape, dtype=bool) for name in ("entry_window", "missed_window", "exit_window")}
    for j in range(causal.shape[1]):
        one = episodes(causal[:, j], causal_def[:, j], truth[:, j], truth_def[:, j], gate[:, j])
        for key in ("onset", "exit"):
            total[key] += one[key]
        for key in ("already_on", "missed", "already_off", "censored"):
            total[key] += one[key]
        for name in windows:
            windows[name][:, j] = one[name]
    total.update(windows)
    return total


# --- flow 的 short_gate ----------------------------------------------------------------------------------------
def flow_section() -> dict[str, Any]:
    import starquant_alpha

    print(f"starquant_alpha 来自 {Path(starquant_alpha.__file__).resolve().parent}")
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry(Path("config/alpha_registry.yaml"))
    model = build_model(registry, profile)
    entry = next(e for e in model.entries if e.id == "flow")
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", "pit"), "1h", None, END, True)
    membership = _membership(DATA, "pit", panel, 0)
    p = FlowParams.from_mapping(entry.params)
    gate_params = p.gate_params()
    eligible = model.eligible(panel, membership)
    scored = panel.with_reference(eligible)
    print(
        f"pit 面板 {panel.index[0]} .. {panel.index[-1]}，{len(panel.index):,} 根 × {len(panel.symbols)} 个标的；"
        f"universe 内 {int(eligible.to_numpy().sum()):,} 格"
    )
    print(f"flow 参数（registry）：short_gate {p.short_gate}，门的 horizon {gate_params.horizons}，"
          f"权重 {gate_params.horizon_weights}，return_scale {gate_params.return_scale}，入场阈值 {entry.entry_threshold}")

    live = flow_scores(scored, p)
    ungated = flow_scores(scored, replace(p, short_gate=0.0))
    momentum = tsmom_scores(panel.close, gate_params)
    checks = {
        "live == ungated 按因果动量挡掉的空头": same_bits(live, ungated.mask((ungated < 0) & (momentum >= p.short_gate), 0.0)),
        "momentum_score(centred=False) == tsmom_scores": same_bits(momentum_score(panel.close, gate_params, centred=False), momentum),
    }
    centred = momentum_score(panel.close, gate_params, centred=True)
    vol = realized_vol(panel.close, window=gate_params.vol_window, ddof=0).to_numpy()
    binds = vol > gate_params.return_scale

    causal = (momentum >= p.short_gate).to_numpy()
    causal_def = momentum.notna().to_numpy()
    gate = eligible.to_numpy()
    close = panel.close.to_numpy(dtype=float)
    cen = centred.to_numpy()
    cen_def = ~np.isnan(cen)
    truths: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    a_on = np.zeros_like(causal)
    for j in range(causal.shape[1]):
        a_on[:, j] = debounce(cen[:, j] >= p.short_gate, cen_def[:, j], MIN_REGIME_BARS)
    truths["A"] = (a_on, cen_def)
    zig = np.column_stack([zigzag_up(close[:, j], ZIGZAG_THETA) for j in range(close.shape[1])])
    truths["B"] = (zig == 1.0, ~np.isnan(zig))

    print("\n== 机械检查")
    for name, ok in checks.items():
        print(f"  {name}: {ok}")
    print(f"  门的分母 max(vol, return_scale) 取到 vol 的格数：{int(binds.sum()):,}，其中 universe 内 "
          f"{int((binds & eligible.to_numpy()).sum()):,}（只有这些格上，居中版本不挪分母才是一个近似）")
    if not all(checks.values()):
        raise SystemExit("机械检查没过，后面的读数不代表在跑的规则")

    print("\n== 状态占比（universe 内、事后状态有定义的格）")
    print(f"  门开（因果，momentum >= {p.short_gate}）：{causal[gate & causal_def].mean():.1%}")
    lag_rows: dict[str, dict[str, Any]] = {}
    for name, (on, defined) in truths.items():
        mask = gate & defined
        print(f"  事后状态 {name} 开：{on[mask].mean():.1%}；与门一致：{(on == causal)[mask].mean():.1%}")
        lag_rows[name] = collect(causal, causal_def, on, defined, gate)

    print("\n== 延迟（小时）。A：同一指标、每个 horizon 的窗口居中、最短 regime 24 根；B：20% 拐点")
    for name, row in lag_rows.items():
        onsets = len(row["onset"]) + row["already_on"] + row["missed"]
        exits = len(row["exit"]) + row["already_off"] + row["censored"]
        print(f"  [{name}] 开启：{onsets} 段；门已在 {row['already_on']}（{row['already_on'] / onsets:.0%}），"
              f"段内漏掉 {row['missed']}（{row['missed'] / onsets:.0%}），要等的 {len(row['onset'])} 段：")
        print(f"        {fmt_q(quantiles(row['onset']))}")
        print(f"  [{name}] 结束：{exits} 段；门已关 {row['already_off']}（{row['already_off'] / exits:.0%}），"
              f"截尾 {row['censored']}，要等的 {len(row['exit'])} 段：")
        print(f"        {fmt_q(quantiles(row['exit']))}")

    print("\n== 敏感性：只换事后状态的一个参数，看延迟中位（小时）")
    for min_bars in SENSITIVITY_MIN_BARS:
        on = np.column_stack([debounce(cen[:, j] >= p.short_gate, cen_def[:, j], min_bars) for j in range(cen.shape[1])])
        row = collect(causal, causal_def, on, cen_def, gate)
        n_on = len(row["onset"]) + row["already_on"] + row["missed"]
        print(f"  居中，最短 regime {min_bars:>2} 根：开启 {n_on:>4} 段，门已在 {row['already_on'] / n_on:>4.0%}，"
              f"等待中位 {quantiles(row['onset']).get('q50', float('nan')):>5.0f}；结束等待中位 "
              f"{quantiles(row['exit']).get('q50', float('nan')):>5.0f}")
    for theta in SENSITIVITY_THETA:
        z = np.column_stack([zigzag_up(close[:, j], theta) for j in range(close.shape[1])])
        row = collect(causal, causal_def, z == 1.0, ~np.isnan(z), gate)
        n_on = len(row["onset"]) + row["already_on"] + row["missed"]
        print(f"  拐点 {theta:.0%}：            开启 {n_on:>4} 段，门已在 {row['already_on'] / n_on:>4.0%}，"
              f"等待中位 {quantiles(row['onset']).get('q50', float('nan')):>5.0f}；结束等待中位 "
              f"{quantiles(row['exit']).get('q50', float('nan')):>5.0f}")

    # --- 收益：sleeve 与整本书 ---
    def held_of(scores: pd.DataFrame) -> pd.DataFrame:
        """`AlphaModel.strategy_targets` 里的那两步：阈值加持有，离开 universe 即平。"""
        held = scores_to_targets(scores.where(eligible), entry.entry_threshold, hold=model.hold_on_no_action)
        return held.mask(~eligible & held.notna(), 0.0)

    flow_only = replace(model, entries=(entry,), books={entry.book: model.books[entry.book]})

    def sleeve(scores: pd.DataFrame) -> pd.DataFrame:
        return flow_only.book_weights({entry.id: held_of(scores)}, panel.close, panel.bars_per_year)[entry.book]

    per_strategy = model.strategy_targets(panel, membership)
    checks2 = {
        "held(live) == model.strategy_targets 的 flow": same_bits(held_of(live), per_strategy[entry.id]),
        "flow-only sleeve == 整本模型里的 flow_short": same_bits(
            sleeve(live), model.book_weights(per_strategy, panel.close, panel.bars_per_year)[entry.book]
        ),
    }
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    oracle = {
        name: ungated.mask((ungated < 0) & pd.DataFrame(np.where(defined, on, causal), index=live.index, columns=live.columns), 0.0)
        for name, (on, defined) in truths.items()
    }
    results: dict[str, BacktestResult] = {
        "无门": run_backtest(panel, sleeve(ungated), cost),
        "在跑的门": run_backtest(panel, sleeve(live), cost),
        **{f"事后门 {name}": run_backtest(panel, sleeve(scores), cost) for name, scores in oracle.items()},
    }
    index = results["在跑的门"].net.index
    years = len(index) / panel.bars_per_year
    columns = list(results["在跑的门"].net.columns)

    def at_execution(mask: np.ndarray) -> np.ndarray:
        """决策 bar 上的格子挪到它执行的那根：t 的决定在 t+1 挣钱。"""
        frame = pd.DataFrame(mask, index=panel.index, columns=panel.close.columns)
        return frame.shift(1, fill_value=False).reindex(index=index, columns=columns).fillna(False).to_numpy(dtype=bool)

    net = {name: result.net.to_numpy(dtype=float) for name, result in results.items()}

    def total(values: np.ndarray, mask: np.ndarray | None = None) -> float:
        return float(np.nansum(values if mask is None else np.where(mask, values, 0.0)))

    print("\n== 机械检查（sleeve）")
    for name, ok in checks2.items():
        print(f"  {name}: {ok}")
    if not all(checks2.values()):
        raise SystemExit("sleeve 不是在跑的 sleeve")

    print(f"\n== flow_short sleeve 的收益（权益的百分比，逐 bar 相加不复利；{years:.2f} 年，成本与资金费在内）")
    for name, values in net.items():
        series = np.nansum(values, axis=1)
        sharpe = series.mean() / series.std() * np.sqrt(panel.bars_per_year)
        print(f"  {name:<8} 合计 {total(values):+8.2%}   每年 {total(values) / years:+7.2%}   夏普 {sharpe:5.2f}")
    benefit = np.nansum(net["在跑的门"], axis=1) - np.nansum(net["无门"], axis=1)
    nw, nw168 = newey_west_tstat(benefit), newey_west_tstat(benefit, max_lags=168)
    print(f"  门的净贡献（在跑 - 无门）：合计 {benefit.sum():+.2%}，每年 {benefit.sum() / years:+.2%}，"
          f"NW t {nw['t_stat']:.2f}（{nw['lags']} 阶）/ {nw168['t_stat']:.2f}（168 阶）")

    print("\n== 延迟窗口里的空头（权益的百分比，逐 bar 相加；窗口按事后状态定，门的状态按因果）")
    in_universe = at_execution(gate)
    for name, (on, defined) in truths.items():
        row = lag_rows[name]
        entry_w, missed_w, exit_w = (at_execution(row[w] & gate) for w in ("entry_window", "missed_window", "exit_window"))
        g, u, o = net["在跑的门"], net["无门"], net[f"事后门 {name}"]
        print(f"  [{name}] 开启延迟窗口 {int(entry_w.sum()):>7,} 格：门放行的空头 {total(g, entry_w):+8.2%}"
              f"（每年 {total(g, entry_w) / years:+.2%}）")
        print(f"  [{name}] 漏掉的段     {int(missed_w.sum()):>7,} 格：门放行的空头 {total(g, missed_w):+8.2%}"
              f"（每年 {total(g, missed_w) / years:+.2%}）")
        print(f"  [{name}] 结束延迟窗口 {int(exit_w.sum()):>7,} 格：门挡掉的空头 {total(u - g, exit_w):+8.2%}"
              f"（每年 {total(u - g, exit_w) / years:+.2%}；为正即门少赚）")
        # 门的净贡献（在跑 - 无门）按格子拆成互斥的六块，六块相加必须回到总数
        c_on = at_execution(causal & gate)
        x_on = at_execution(on & defined & gate)
        x_def = at_execution(defined & gate)
        parts = {
            "门开、事后也开（挡对了）": c_on & x_on,
            "门开、事后已关，在结束延迟窗口里（关晚了）": c_on & ~x_on & x_def & exit_w,
            "门开、事后关，其余（提前开与误报）": c_on & ~x_on & x_def & ~exit_w,
            "门关（持有语义与波动率归一的外溢）": in_universe & ~c_on & x_def,
            "事后状态无定义": in_universe & ~x_def,
            "universe 外（离池那根的平仓成本）": ~in_universe,
        }
        pieces = {label: total(g - u, mask) for label, mask in parts.items()}
        if abs(sum(pieces.values()) - total(g - u)) > 1e-9:
            raise SystemExit(f"[{name}] 拆分没回到总数：{sum(pieces.values())} vs {total(g - u)}")
        print(f"  [{name}] 门的净贡献 {total(g - u):+.2%} 拆开：")
        for label, value in pieces.items():
            print(f"        {label:<24} {value:+8.2%}")
        print(f"  [{name}] 事后门 - 无门 {total(o - u):+8.2%}；事后门 - 在跑的门 {total(o - g):+8.2%}；"
              f"在跑的门拿到事后门的 {total(g - u) / total(o - u):.1%}")

    # --- 整本书：tsmom + flow sleeve，exit overlay 与 book guards 照 p32d.panel_series ---
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": 24})
    portfolio = profile.get("portfolio", {}) or {}
    guards = BookGuardParams(
        max_weight=float(portfolio["max_weight"]),
        max_gross=float(portfolio["max_gross"]),
        daily_loss_pause=float(profile["guards"]["daily_loss_pause"]),
    )

    def book(flow_held: pd.DataFrame) -> np.ndarray:
        weights = model.weights_from({**per_strategy, entry.id: flow_held}, panel.close, panel.bars_per_year)
        weights = apply_exits(weights, panel.close, exits).weights if exits.enabled else weights
        result = run_backtest(panel, weights, cost, guards=guards)
        return np.nansum(result.net.to_numpy(dtype=float), axis=1)

    book_live, book_ungated = book(per_strategy[entry.id]), book(held_of(ungated))
    mark, _ = p32d.panel_series("pit", k=float(portfolio["vol_target"]))
    print(f"\n== 整本书（k={portfolio['vol_target']}，tsmom + flow sleeve，exit overlay 与 book guards 在内）")
    print(f"  在跑的书 == p32d.panel_series 的 mark：max|差| {np.abs(book_live - mark).max():.1e}")
    book_years = len(book_live) / panel.bars_per_year
    for name, series in (("无门", book_ungated), ("在跑的门", book_live)):
        print(f"  {name:<8} 每年 {series.sum() / book_years:+7.2%}   夏普 {series.mean() / series.std() * np.sqrt(panel.bars_per_year):.3f}")
    delta = book_live - book_ungated
    nw, nw168 = newey_west_tstat(delta), newey_west_tstat(delta, max_lags=168)
    print(f"  门的净贡献：每年 {delta.sum() / book_years:+.2%}，NW t {nw['t_stat']:.2f}（{nw['lags']} 阶）/ {nw168['t_stat']:.2f}（168 阶）")
    return {"checks": {**checks, **checks2}}


# --- 风险预算阶梯 -------------------------------------------------------------------------------------------------
def replay(mark: np.ndarray, rungs: tuple[tuple[float, float], ...], base: float, delay: int) -> dict[str, Any]:
    """在跑的状态机按历史路径逐根走一遍；`delay` 是读数比决策晚几根。

    `delay=0` 是 p32 系列的约定：决定第 t 根仓位时读到第 t-1 根收盘后的回撤。实盘的尺子读的是上一周期
    写下的行，比这晚一根，即 `delay=1`（`ruler_section` 在实盘记录上核这一条）。
    """
    policy = Policy()
    equity = hwm = 1.0
    after: list[float] = []
    standing: dict[str, Any] = {}
    scalars = np.ones(len(mark))
    crossings = acting = 0
    for t in range(len(mark)):
        seen = t - 1 - delay
        reading = after[seen] if seen >= 0 else 0.0
        step = ladder_step(
            reading={"enforced": True, "value": reading}, standing=standing, base=base, rungs=rungs,
            grace_cycles=policy.drawdown_grace_cycles, bar_open_ms=t, now="",
        )
        if step.standing is not None:
            standing = step.standing
        crossings += int(step.block.get("cycles") == 1)
        acting += int(bool(step.block["acting"]))
        scalars[t] = float(step.block["scalar"])
        equity *= 1.0 + scalars[t] * mark[t]
        hwm = max(hwm, equity)
        after.append(equity / hwm - 1.0)
    return {"crossings": crossings, "acting_bars": acting, "scalars": scalars}


def ladder_section() -> dict[str, Any]:
    rungs = tuple(Policy().drawdown_ladder)
    grace = Policy().drawdown_grace_cycles
    print(f"\n== 风险预算阶梯：档位 {rungs}，宽限 {grace} 个周期，base = 所跑的 k，盯市尺子")
    rows: list[dict[str, Any]] = []
    for mode in ("pit", "static"):
        for k in K_SCAN:
            mark, realised = p32h.panel(mode, k)
            dd = drawdown_path(np.cumprod(1.0 + mark))
            live_timing = replay(mark, rungs, k, delay=1)
            p32_timing = replay(mark, rungs, k, delay=0)
            if k == K_SCAN[0]:
                reference = p32h.ladder_at_base(mark, realised, replace(Policy(), drawdown_ladder=rungs), "mtm", k)[1]
                print(f"  [{mode}] replay(delay=0) 的 scalar == p32h.ladder_at_base：{same_bits(p32_timing['scalars'], reference)}")
                old = replay(mark, p32d.UNRESCALED, k, delay=1)
                print(f"  [{mode}] k={k:.2f} 换成 0.3.3 之前的档位 {p32d.UNRESCALED}：越档 {old['crossings']} 次")
            row = {
                "mode": mode, "k": k, "bars": len(mark), "mdd": float(dd.min()),
                "bars_below_rung1": int((dd <= rungs[0][0]).sum()),
                "crossings": live_timing["crossings"], "acting_bars": live_timing["acting_bars"],
                "crossings_p32_timing": p32_timing["crossings"],
            }
            rows.append(row)
            print(f"  [{mode}] k={k:.2f}  bars {row['bars']:,}  历史最大回撤 {row['mdd']:+.2%}  "
                  f"低于 {rungs[0][0]:.0%} 的 bar {row['bars_below_rung1']:>4}  越档 {row['crossings']}"
                  f"（p32 约定 {row['crossings_p32_timing']}）  生效 bar {row['acting_bars']}")
    return {"rows": rows}


# --- 归因回撤尺子：实盘记录上核它读的是哪一行 -----------------------------------------------------------------------------
def ruler_section() -> dict[str, Any]:
    """R8 的尺子在实盘记录上读的是哪一行，以及它把哪一笔记了两次。

    第一条：第 n 个周期的读数，能否由「前 n-1 行 + 挂在第 n-1 行及以前的收入」逐个复现。能，就说明未实现
    部分晚一个周期：本周期的快照要到周期末才写进 cycles.jsonl。
    第二条：同一快照口径。第 k 行的 `unrealized` 是第 k 个周期下单之前的快照，挂在第 k 行的收入却是下单
    之后才实现的（`_ingest_income` 按上一周期的 bar 记账，下一个周期才收进来）。这一单实现的盈亏，在快照里
    是浮盈，在收入里又算一次。不重复的那条路径：每条收入放到收进它的那个周期的行上（该行快照在实现之后）；
    那一行若是 rebaseline，收入已在新的 base 里，丢掉。行按序号重新编号，因为重启会写出同一 bar 的多行。
    """
    pin = int(pd.Timestamp(LIVE_PIN).timestamp() * 1000)
    rows = [json.loads(line) for line in (LIVE / "cycles.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if int(row["bar_open_ms"]) <= pin]
    attribution = [
        json.loads(line) for line in (LIVE / "attribution.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    bars = [int(row["bar_open_ms"]) for row in rows]
    written = [pd.Timestamp(row["at"]) for row in rows]
    priced = [isinstance(row.get("equity"), int | float) and row["equity"] > 0 for row in rows]
    rebased = [bool((row.get("external_flows") or {}).get("rebaselined")) for row in rows]

    def landing(income: dict[str, Any]) -> int | None:
        ingested = pd.Timestamp(income["at"])
        first = next((i for i, at in enumerate(written) if at >= ingested), None)
        k = None if first is None else next((i for i in range(first, len(rows)) if priced[i]), None)
        return None if k is None or rebased[k] else k

    lands = [landing(income) for income in attribution]
    renumbered = [{**row, "bar_open_ms": i} for i, row in enumerate(rows)]
    params = RiskBudgetParams()
    exact = compared = 0
    worst = 0.0
    readings: list[tuple[str, float, float, float, float]] = []
    for n in range(1, len(rows)):
        recorded = (rows[n].get("risk_ladder") or {}).get("drawdown")
        if recorded is None:
            continue
        read = attributed_drawdown_state(
            rows[:n], [a for a in attribution if int(a["bar_open_ms"]) <= bars[n - 1]], params
        )
        moved = [{**a, "bar_open_ms": k} for a, k in zip(attribution, lands, strict=True) if k is not None and k < n]
        consistent = attributed_drawdown_state(renumbered[:n], moved, params)
        if read.get("value") is None or consistent.get("value") is None:
            continue
        compared += 1
        worst = max(worst, abs(float(read["value"]) - float(recorded)))
        exact += int(abs(float(read["value"]) - float(recorded)) <= 1e-12)
        readings.append((str(rows[n]["bar"]), float(read["value"]), float(consistent["value"]),
                         float(read["peak"]), float(consistent["peak"])))
    print(f"\n== 归因回撤尺子：实盘记录 {rows[0]['bar']} .. {rows[-1]['bar']}，{len(rows)} 行")
    print(f"  第 n 个周期的读数 == attributed_drawdown_state(前 n-1 行, 挂在第 n-1 行及以前的收入)：{exact}/{compared}，"
          f"max|差| {worst:.1e}")
    diffs = np.array([r[1] - r[2] for r in readings])
    peaks = np.array([r[3] - r[4] for r in readings])
    print(f"  读数 - 不重复口径：最小 {diffs.min():+.2%}，最大 {diffs.max():+.2%}，均值 {diffs.mean():+.2%}，"
          f"不同的周期 {int((np.abs(diffs) > 1e-12).sum())}/{len(diffs)}")
    print(f"  高水位：读数一侧最多高出 {peaks.max():,.2f} USDT，最少高出 {peaks.min():,.2f} USDT，偏高的周期 {int((peaks > 1e-9).sum())}；"
          f"最深读数 {min(r[1] for r in readings):+.2%}（不重复口径 {min(r[2] for r in readings):+.2%}）")
    print(f"  最后一个周期 {readings[-1][0]}：读数 {readings[-1][1]:+.2%}，不重复口径 {readings[-1][2]:+.2%}，"
          f"高水位高出 {peaks[-1]:,.2f} USDT")
    return {"exact": exact, "compared": compared}


#: `pin_end` 装上之后，p32d.panel_series 每读一次面板记一笔；最后打印，证明钉住生效了。
PINNED_CALLS: list[str] = []


def pin_end() -> None:
    """p32d.panel_series 不收 end，就在它查名字的地方钉住（p32h 钉 static 名单也是这么做的）。"""
    original = p32d._load

    def pinned(*args: Any, **kwargs: Any) -> Panel:
        root, symbols, interval, start, _end, funding, *rest = args
        PINNED_CALLS.append(END)
        return original(root, symbols, interval, start, END, funding, *rest, **kwargs)

    p32d._load = pinned


def main(argv: list[str]) -> None:
    what = argv[1] if len(argv) > 1 else "all"
    pin_end()
    if what in ("flow", "all"):
        flow_section()
    if what in ("ladder", "all"):
        ladder_section()
    if what in ("ruler", "all"):
        ruler_section()
    print(f"\np32d._load 按 END={END} 钉住的调用：{len(PINNED_CALLS)} 次")


if __name__ == "__main__":
    main(sys.argv)
