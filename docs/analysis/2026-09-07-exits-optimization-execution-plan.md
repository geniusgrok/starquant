# 止盈止损优化执行方案（2026-09-07）· Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本方案只生成不执行。** 每个任务都挂在 §1 的一个操作者决定（Q1–Q6）上；在对应的 Q 得到回答之前，不改配置、不跑计费实验、不写 ledger。方案位置沿用仓库惯例放在 `docs/analysis/`（操作者要求分析与方案都用纯 Markdown 放在这里），而不是 `docs/superpowers/plans/`。

**Goal:** 把深度分析报告的 PIVOT 结论变成可逐步执行的工作：先写后跑地测掉操作者的字面问题（止盈 3σ/4σ、当前波动单位），给日报一个噪声尺度和 M-005 监测，处置一次未入账的实盘重放，并把采纳与回滚写成流程。

**Architecture:** 所有退出规则都留在 `starquant_alpha/overlays/exits.py` 的纯函数 `exit_step` 里，回测与实盘共用同一步函数（D-012）；研究证据由 `starquant research overlay` 产出并按 DL-K1 计入 ledger；实盘只在一个候选双 universe 通过预登记规则且操作者批准后，用一行配置 + 一次重启采纳。观测项（噪声尺度、反事实）只加在 `starquant_live/reports.py`，不碰下单路径。

**Tech Stack:** Python 3.12（`.venv`，见记忆：必须 3.12），pandas / numpy，pytest，click CLI（`starquant research overlay` / `starquant report daily`），launchd（`com.starquant.live`）。

**Spec:** `docs/analysis/2026-09-07-exits-adaptive-tp-sl-deep-analysis.md`（含 §8 对抗审查、§11 预登记规则、§12 Q1–Q6）。冻结版在会话 scratchpad `exits-adaptive-frozen.md`。

## Global Constraints

- **先写后跑**：任何计费实验的网格、判定规则、 ledger 预期必须以 git 提交的形式早于运行时间戳（DL-K3 顺序检查会核对）。
- **D-017 判定不变**：候选合格 = OOS MDD 改善 且 OOS Sharpe 损失 ≤ 0.10，时点与静态两个 universe 都要满足；`research overlay --max-sharpe-loss 0.10` 是默认值。
- **ledger**：`research overlay` 的每个候选计入书中每个策略（tsmom、flow）的 ledger（`starquant_cli/research_cmd.py:1101-1128`）；同一 (param_key, range, symbols, construction, overlay) 去重。本方案每一步都写明预期的 ledger 增量，运行后与报告 `ledger.charged` 核对。
- **非 alpha 行数**：六个包都顶在 `tests/architecture/test_source_budget.py` 的 `CEILING` 上（alpha 5,808 / live 5,065 / cli 3,291）。任何净增行数都要在 `CEILING` 处加一条"带理由句子"的抬升记录；≥100 行非 alpha 的捆绑改动需要操作者裁定（KILL-R12，Q5）。
- **实盘改动 = 构造变更**：`construction_fingerprint`（`starquant_live/engine.py:1177`）包含 `exits` 块；改 `config/live.demo.yaml` 的 `exits` 会重置 M-010 证据窗口。采纳前用 scratch `state_dir` 演练 `--dry-run`（`live run --dry-run` 会写 LIVE 状态目录，记忆 P13 教训 3）。
- **不做**：更紧的止损与移动止损、滚动入场锚、组合层 regime 敞口标量、部分止盈、交易所原生条件单、按 3 天实盘重放调参、在批准前跑任何计费实验。
- **多会话**：主 checkout 由 launchd 使用；代码改动在 `git worktree add ../starquant-exits -b feat/exits-p22 HEAD` 里做，`PYTHONPATH=<worktree>` 运行；shell 里 `cat`/`ls` 有别名，用 `/bin/cat`、`/bin/ls`。

---

## 1. 决策门：哪个 Q 解锁哪个任务

| Q（报告 §12） | 若答 A | 若答 B | 解锁的任务 |
| --- | --- | --- | --- |
| Q1 exit overlay 角色 | 主动 P&L 机制 → Task 3 必做，Task 7 排队 | 灾难后备 → Task 3 可选，Task 7 不做 | Task 3 / Task 7 |
| Q2 权益日波动 | ≈170 U → 本方案成立 | 更小 → 另开 P13 预算重议，本方案不变 | 无（决定的是 `vol_target`） |
| Q3 ledger 名额 | 是 → Task 1 + 2 + 3 | 否 → 只做 Task 4/5/6 中被批准的 | Task 1、2、3 |
| Q4 E-EX14 处置 | 补记 → Task 5A | 豁免 → Task 5B | Task 5 |
| Q5 KILL-R12 | 抬上限或指名删除 → Task 4 | 不做 → Task 4 跳过 | Task 4 |
| Q6 30 天规则 | 接受 → Task 6 写入 RUNBOOK；Task 9 受其约束 | 不接受 → Task 9 每次单独裁定 | Task 6、9 |

推荐默认（若操作者只回答 Q3）：Q1=B、Q2=A、Q4=B、Q5=A（抬上限 +77 live）、Q6=A。

## 2. 文件结构

| 文件 | 责任 | 任务 |
| --- | --- | --- |
| `docs/RESEARCH_LOG.md` | P22 预登记段与裁决段（先写后跑的证据链） | 1、3、5、7、8 |
| `starquant_alpha/overlays/exits.py` | `ExitParams.unit_mode`、`_unit_price`；（条件）`efficiency_ratio` / `regime_tp_scale` / `tp_scale` | 2、7 |
| `starquant_live/engine.py:1207-1213` | 构造指纹的 `exits` 块加 `unit_mode`（与条件任务的 regime 字段） | 2、7 |
| `starquant_live/exits.py` | （条件）实盘按 bar 算 ER 并传 `tp_scale` | 7 |
| `starquant_live/reports.py` | `noise_scale`、`exit_counterfactuals`、`daily_payload` 两个新键、两段 markdown | 4 |
| `starquant_cli/live_cmd.py:513-536` | `report daily` 把 `vol_target` 与 `data_root` 传给 `daily_payload` | 4 |
| `starquant_alpha/signals/base.py` | （条件）`scores_to_targets(exit_threshold, exit_dwell_bars)` 与 `_consecutive_true` | 8 |
| `starquant_alpha/signals/tsmom.py`、`starquant_alpha/registry.py`、`starquant_alpha/model.py` | （条件）tsmom 的两个退出参数、registry 读取、模型传递 | 8 |
| `scratchpad/p22_verdict.py` | 读四份 overlay 报告，按预登记规则打印裁决表 | 3 |
| `scratchpad/e_ex14_ledger.py` | （Q4=A）把实盘重放的 7 个配置补记进 ledger | 5 |
| `scratchpad/p23_subthreshold_forward.py` | （条件）O-EX1 的描述统计，计 1 个 trial | 8 |
| `tests/alpha/test_overlays.py`、`tests/live/test_round6b_funding_and_verify.py`、`tests/live/test_report_metrics.py`、`tests/alpha/test_conviction_mode.py`（或新建 `tests/alpha/test_exit_threshold.py`） | 上述改动的测试 | 2、4、7、8 |
| `tests/architecture/test_source_budget.py` | `CEILING` 抬升记录 | 2、4、7、8 |
| `docs/RUNBOOK.md` | Q6 规则；采纳与回滚步骤 | 6、9 |

## 3. ledger 与行数账（运行后逐项核对）

| 任务 | tsmom ledger | flow ledger | alpha 行 | live 行 | cli 行 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Task 2 `unit_mode` | 0 | 0 | +12 | +1 | 0 |
| Task 3 第一个实验（两 universe × 两次调用） | +10（退出 4×2 + 节流 1×2） | +10 | 0 | 0 | 0 |
| Task 4 日报观测 | 0 | 0 | 0 | +77 | +2 |
| Task 5A 补记 E-EX14 | +7 | +7 | 0 | 0 | 0 |
| Task 7（条件）regime 2×2 | +4 | +4 | +45 | +12 | 0 |
| Task 8（条件）描述统计 + validate | +1 +2 | 0 | +35 | 0 | 0 |

当前 ledger：tsmom 89、flow 14。Task 3 之后 tsmom 99（RISK-P4：下次复验的 FWER 阈值随 N 上移，headroom 目前 0.02–0.04）。

---

## Task 1：P22 预登记写入 RESEARCH_LOG（先于任何运行提交）

**前置：** Q3 = 是。

**Files:**
- Modify: `docs/RESEARCH_LOG.md`（在文件末尾追加）

**Interfaces:**
- Produces: 章节标题 `## 2026-09-0X · P22 预登记：止盈 3σ/4σ 与当前波动单位（先写后跑）`；Task 3 的裁决段引用它的时间戳与 commit。

- [ ] **Step 1: 追加预登记段（原文照抄，日期改为提交当天）**

```markdown
## 2026-09-0X · P22 预登记：止盈 3σ/4σ 与当前波动单位（先写后跑）

来源：`docs/analysis/2026-09-07-exits-adaptive-tp-sl-deep-analysis.md` §11.2（EXP-EX1b + EXP-EX3），对抗审查 K-EX01 / K-EX03 的关闭条件。操作者对 Q3 的回答：是。

**问题。** D-017 预登记网格里 `take_profit ∈ {0, 6}`，6σ 以内的止盈从未测过；所有 exit overlay 证据都在 `vol_target 0.15` 构造上算。

**网格（两个 universe 各两次调用，四份报告）：**
1. `stop_loss [6.0] × trailing_stop [0.0] × take_profit [3.0, 4.0, 6.0] × unit_mode ["entry"]`——TP6-entry 是现行设置，在 0.30 构造上重跑作为对照；
2. `stop_loss [6.0] × trailing_stop [0.0] × take_profit [6.0] × unit_mode ["current"]`。
节流网格用默认（`start 0.05 / stop 0.20 / floor 0.25`），它在两次调用间去重，只计一次；这是对配置注释"启用前必须在 0.30 重跑"的兑现，不是新候选。

**判定规则（写在跑之前，跑完不改）：**
- 固定止盈 3σ 或 4σ 采纳当且仅当：该档在时点与静态都通过 D-017（对各自报告的 baseline：OOS MDD 改善且 OOS Sharpe 损失 ≤ 0.10）**且** 两个 universe 的 OOS Sharpe 都 ≥ 同报告里 TP6-entry 的 OOS Sharpe − 0.02 **且** 退出次数 ≤ TP6-entry 的 3 倍。
- 当前波动单位（TP6-current）采纳当且仅当：双 universe 通过 D-017 **且** 双 universe 的 OOS MDD 不差于 TP6-entry **且** 退出次数 ≤ TP6-entry 的 3 倍。
- 任一条件不满足 → 对应 Claim（C-EX02a-TP / C-EX02c）REFUTED，记负结果，不扩网格。
- 两档止盈都通过时取 OOS MDD 更优者；止盈与 current 同时通过时**不合并**，各自记录，合并版本需另行预登记。

**ledger 预期：** tsmom +10、flow +10（退出候选 4 × 2 universe + 节流 1 × 2 universe）。运行后核对每份报告的 `ledger.charged`。

**先验（写在结果之前）：** 止盈 3σ/4σ 为负（趋势系统利润在右尾；E-EX14 的 3 天重放不算证据）；current 方向不确定。

**不做：** 不加 TP3-current / TP4-current（省 8 行 ledger；若 current 单独通过再另行预登记）。
```

- [ ] **Step 2: 提交**

```bash
git add docs/RESEARCH_LOG.md
git commit -m "research: P22 预登记——止盈 3σ/4σ 与当前波动单位（先写后跑）"
```

---

## Task 2：`unit_mode`（当前波动单位）+ 构造指纹 + 测试

**前置：** Q3 = 是（Task 1 已提交）。

**Files:**
- Modify: `starquant_alpha/overlays/exits.py:34-58`（`ExitParams`）、`:105-157`（`exit_step`）、`:187-227`（`apply_exits` 事件行）
- Modify: `starquant_live/engine.py:1207-1213`（指纹 `exits` 块）
- Test: `tests/alpha/test_overlays.py`、`tests/live/test_round6b_funding_and_verify.py:449-461`
- Modify: `tests/architecture/test_source_budget.py`（`CEILING` alpha +12、live +1）

**Interfaces:**
- Produces: `ExitParams.unit_mode: str = "entry"`（取值 `entry | current`）；`_unit_price(state, sigma_1d, params) -> float`；`research overlay --exits-grid` 的 JSON 直接接受 `"unit_mode": ["entry","current"]`（`ExitParams.from_mapping` 只取 dataclass 已有字段，所以字段一加即可入网格）。
- 实盘路径零改动：`starquant_live/exits.py:48-50` 已把本 bar 的 `sigma` 传给 `exit_step`。

- [ ] **Step 1: 写两个失败测试（追加到 `tests/alpha/test_overlays.py`）**

```python
def test_unit_mode_entry_is_the_default_and_bit_identical() -> None:
    """EXP-EX3 / T-EX7-1: `unit_mode: entry` must reproduce the shipped overlay exactly, and it is the default."""
    rng = np.random.default_rng(7)
    path = list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, size=120))))
    weights, close, vol = _frames(path)
    shipped = ExitParams(stop_loss=6.0, take_profit=6.0)
    explicit = ExitParams(stop_loss=6.0, take_profit=6.0, unit_mode="entry")
    assert shipped.unit_mode == "entry"
    a = apply_exits(weights, close, shipped, sigma_1d=vol)
    b = apply_exits(weights, close, explicit, sigma_1d=vol)
    pd.testing.assert_frame_equal(a.weights, b.weights)
    pd.testing.assert_frame_equal(a.events, b.events)
    with pytest.raises(ValueError):
        ExitParams(unit_mode="atr")


def test_unit_mode_current_measures_distance_in_this_bars_sigma() -> None:
    """The same 3-point adverse move is 1.5 entry-units (no stop) but 3 current-units once sigma halves."""
    path = [100.0, 100.0, 98.5, 97.0, 97.0]
    weights, close, _ = _frames(path)
    vol = pd.DataFrame({"A": [0.02, 0.02, 0.01, 0.01, 0.01]}, index=close.index)
    entry = apply_exits(weights, close, ExitParams(stop_loss=2.0, unit_mode="entry"), sigma_1d=vol)
    current = apply_exits(weights, close, ExitParams(stop_loss=2.0, unit_mode="current"), sigma_1d=vol)
    assert len(entry.events) == 0  # 3 points / (0.02 * 100) = 1.5 units < 2
    assert len(current.events) == 1 and current.events.iloc[0]["rule"] == STOP_LOSS  # 3 / (0.01 * 100) = 3 units
    assert current.events.iloc[0]["units"] <= -2.0  # reported in the unit that fired, not the entry unit
    assert current.weights["A"].iloc[3] == 0.0
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/pytest tests/alpha/test_overlays.py -k unit_mode -v
```
Expected: FAIL，`TypeError: ExitParams.__init__() got an unexpected keyword argument 'unit_mode'`。

- [ ] **Step 3: 实现（`starquant_alpha/overlays/exits.py`）**

在 `ExitParams` 里加字段与校验：

```python
    min_unit: float = 0.005  # floor on sigma_1d (fraction) so a dead-quiet series cannot make a 1-tick stop
    unit_mode: str = "entry"  # entry | current: which sigma_1d the k-units are measured in (EXP-EX3)

    def __post_init__(self) -> None:
        if min(self.stop_loss, self.trailing_stop, self.take_profit) < 0:
            raise ValueError("exit thresholds must be >= 0")
        if self.cooldown_bars < 0 or self.vol_halflife <= 0 or self.bars_per_day <= 0 or self.min_unit <= 0:
            raise ValueError("invalid exit parameters")
        if self.unit_mode not in {"entry", "current"}:
            raise ValueError("unit_mode must be 'entry' or 'current'")
```

在 `_sign` 之后加辅助函数：

```python
def _unit_price(state: ExitState, sigma_1d: float, params: ExitParams) -> float:
    """The price distance one k-unit is worth on this bar.

    ``entry``: the sigma frozen when the position opened (D-012's definition - the same k is the same
    statistical distance, measured once).  ``current``: this bar's sigma, so the thresholds breathe with
    volatility - tighter when the market calms, wider when it wakes - which is what the Chandelier / ATR
    family does by default and what EXP-EX3 tests.  A missing current sigma falls back to the entry unit.
    """
    unit = state.unit
    if params.unit_mode == "current" and not math.isnan(sigma_1d) and sigma_1d > 0:
        unit = sigma_1d
    return max(unit, params.min_unit) * state.entry_price
```

`exit_step` 里把 `unit_price = max(state.unit, params.min_unit) * state.entry_price` 改为：

```python
        unit_price = _unit_price(state, sigma_1d, params)
```

`apply_exits` 的事件行里把 `unit_price = max(before.unit, params.min_unit) * before.entry_price` 改为：

```python
                unit_price = _unit_price(before, vols[t, j], params)
```

- [ ] **Step 4: 运行，确认通过，并跑整个 overlay 测试文件**

```bash
.venv/bin/pytest tests/alpha/test_overlays.py -v
```
Expected: 全部 PASS（原有 T-X01..T-X05 与 T-S04 不变）。

- [ ] **Step 5: 构造指纹看见 `unit_mode`（`starquant_live/engine.py:1207-1213`）**

```python
        "exits": {
            "stop_loss": config.exits.stop_loss,
            "trailing_stop": config.exits.trailing_stop,
            "take_profit": config.exits.take_profit,
            "cooldown_bars": config.exits.cooldown_bars,
            "vol_halflife": config.exits.vol_halflife,
            "unit_mode": config.exits.unit_mode,
        },
```

在 `tests/live/test_round6b_funding_and_verify.py` 的 `test_the_construction_fingerprint_sees_what_the_evidence_gate_cannot` 末尾追加：

```python
    breathing = dc_replace(base, exits=dc_replace(base.exits, unit_mode="current"))
    assert construction_fingerprint(breathing)["digest"] != construction_fingerprint(base)["digest"]
    assert construction_fingerprint(breathing)["exits"]["unit_mode"] == "current"
```

**注意**：加字段后现有实盘构造指纹 `0dcd044d0158…` 会变（指纹多了一个键）。这是本任务合并进主 checkout 并重启时的一次构造变更，要在 RESEARCH_LOG 记一行"指纹因新增字段而变，行为未变"，M-010 窗口按 D-026 规则重置。若操作者不愿为此重置窗口，可把 `unit_mode` 从指纹里去掉直到真的采纳 `current` 时再加——两种都合法，默认取前者（指纹如实）。

```bash
.venv/bin/pytest tests/live/test_round6b_funding_and_verify.py -k fingerprint -v
```
Expected: PASS。

- [ ] **Step 6: `CEILING` 抬升记录（`tests/architecture/test_source_budget.py`）**

在 `CEILING = {` 之前的注释块末尾追加，并把两个数字改掉：

```python
# Raise 2026-09-0X, with the sentence the rule requires: +12 in starquant_alpha and +1 in starquant_live for
# `ExitParams.unit_mode` (EXP-EX3): the k-units of the exit overlay can now be measured in this bar's sigma
# instead of the entry bar's, which is the cheapest test of "adaptive" exits the operator asked for, and the
# construction fingerprint records which unit a cycle ran under so an adoption cannot be silent.
CEILING = {
    "starquant_alpha": 5_820,
    "starquant_live": 5_066,
```

```bash
.venv/bin/pytest tests/architecture/test_source_budget.py -v
```
Expected: PASS（若实际行数与估计不同，按实测改数字，理由句子不变）。

- [ ] **Step 7: 全量测试与提交**

```bash
.venv/bin/pytest -q
git add starquant_alpha/overlays/exits.py starquant_live/engine.py tests/alpha/test_overlays.py tests/live/test_round6b_funding_and_verify.py tests/architecture/test_source_budget.py
git commit -m "feat(alpha): ExitParams.unit_mode——退出阈值可用当前 σ 计量（EXP-EX3），指纹如实"
```

---

## Task 3：第一个实验——两 universe × 两次 overlay 调用，按 P22 规则裁决

**前置：** Task 1、Task 2 已提交（预登记 commit 时间戳早于运行）。

**Files:**
- Create: `scratchpad/p22_verdict.py`
- Produces: `reports/research/overlay-<stamp>.json` × 4；`docs/RESEARCH_LOG.md` 的 P22 裁决段

- [ ] **Step 1: 运行（从 worktree，`PYTHONPATH` 指向它；数据根仍是主树）**

```bash
export PYTHONPATH=$PWD
.venv/bin/python -m starquant_cli research overlay --universe pit    --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[3.0,4.0,6.0],"unit_mode":["entry"]}'
.venv/bin/python -m starquant_cli research overlay --universe pit    --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[6.0],"unit_mode":["current"]}'
.venv/bin/python -m starquant_cli research overlay --universe static --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[3.0,4.0,6.0],"unit_mode":["entry"]}'
.venv/bin/python -m starquant_cli research overlay --universe static --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[6.0],"unit_mode":["current"]}'
```
Expected: 每次调用打印 `ensemble ['tsmom', 'flow'] on N symbols x M bars; baseline oos_sharpe=… oos_mdd=…`，随后每个候选一行，落盘 `reports/research/overlay-<stamp>.json` 与 `.md`。四份报告的 `portfolio.vol_target` 必须是 `0.3`（否则是 profile 读错了，停）。`ledger.charged`：第一次调用每策略 4（3 退出 + 1 节流）、第二次每策略 1（节流去重为 0）；两 universe 合计 tsmom +10、flow +10。若 `charged` 与预期不符，先查 `reports/research/trials.jsonl` 再继续。

- [ ] **Step 2: 写裁决脚本 `scratchpad/p22_verdict.py`**

```python
"""P22 verdict: read the four overlay reports and print the pre-registered decision table.

Usage: python scratchpad/p22_verdict.py PIT_ENTRY.json PIT_CURRENT.json STATIC_ENTRY.json STATIC_CURRENT.json
Rules are the ones written in RESEARCH_LOG's P22 pre-registration; this script does not decide anything new.
"""

from __future__ import annotations

import json
import sys
from typing import Any

MAX_SHARPE_LOSS = 0.10
TP_MARGIN_VS_CURRENT = 0.02
MAX_EXIT_RATIO = 3.0


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def exits_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in report["candidates"]:
        if row["kind"] != "exits":
            continue
        p = row["params"]
        key = f"TP{p['take_profit']:g}-{p.get('unit_mode', 'entry')}"
        rows[key] = row
    return rows


def d017(row: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return row["oos_mdd"] > baseline["oos_mdd"] and row["oos_sharpe"] >= baseline["oos_sharpe"] - MAX_SHARPE_LOSS


def main(paths: list[str]) -> None:
    pit = {**exits_rows(load(paths[0])), **exits_rows(load(paths[1]))}
    static = {**exits_rows(load(paths[2])), **exits_rows(load(paths[3]))}
    base_pit, base_static = load(paths[0])["baseline"], load(paths[2])["baseline"]
    ref_pit, ref_static = pit["TP6-entry"], static["TP6-entry"]
    print(f"{'candidate':14s} {'pit OOS/MDD':>18s} {'static OOS/MDD':>18s} {'D-017':>6s} {'vs TP6':>8s} {'exits x':>8s}  verdict")
    for key in sorted(set(pit) & set(static)):
        a, b = pit[key], static[key]
        passes = d017(a, base_pit) and d017(b, base_static)
        exits_ratio = max(a["events"]["exits"] / max(ref_pit["events"]["exits"], 1), b["events"]["exits"] / max(ref_static["events"]["exits"], 1))
        if key.endswith("-current"):
            extra = a["oos_mdd"] >= ref_pit["oos_mdd"] and b["oos_mdd"] >= ref_static["oos_mdd"]
            rule = "MDD not worse than TP6-entry"
        else:
            extra = (a["oos_sharpe"] >= ref_pit["oos_sharpe"] - TP_MARGIN_VS_CURRENT
                     and b["oos_sharpe"] >= ref_static["oos_sharpe"] - TP_MARGIN_VS_CURRENT)
            rule = "Sharpe >= TP6-entry - 0.02"
        adopt = passes and extra and exits_ratio <= MAX_EXIT_RATIO
        print(
            f"{key:14s} {a['oos_sharpe']:7.4f}/{a['oos_mdd']:8.4f} {b['oos_sharpe']:7.4f}/{b['oos_mdd']:8.4f} "
            f"{'yes' if passes else 'no':>6s} {'ok' if extra else 'fail':>8s} {exits_ratio:8.2f}  "
            f"{'ADOPT-CANDIDATE' if adopt else 'REFUTED'}  ({rule})"
        )
    for name, report in (("pit", load(paths[0])), ("static", load(paths[2]))):
        thr = [r for r in report["candidates"] if r["kind"] == "throttle"]
        if thr:
            r = thr[0]
            print(f"throttle@0.30 {name}: {r['oos_sharpe']:.4f}/{r['oos_mdd']:.4f} vs baseline "
                  f"{report['baseline']['oos_sharpe']:.4f}/{report['baseline']['oos_mdd']:.4f} -> "
                  f"{'passes' if d017(r, report['baseline']) else 'fails'} D-017 (informational, stays off)")


if __name__ == "__main__":
    main(sys.argv[1:5])
```

- [ ] **Step 3: 跑裁决脚本**

```bash
.venv/bin/python scratchpad/p22_verdict.py reports/research/overlay-<pit-entry>.json reports/research/overlay-<pit-current>.json reports/research/overlay-<static-entry>.json reports/research/overlay-<static-current>.json
```
Expected: 三个候选各一行 `ADOPT-CANDIDATE` 或 `REFUTED`，节流两行 informational。

- [ ] **Step 4: 写 P22 裁决段（追加到 `docs/RESEARCH_LOG.md`，表格照脚本输出填）**

```markdown
## 2026-09-0X · P22 裁决：<一句话结论>

预登记：<commit sha>（<时间戳>）；运行：<四个报告 stamp>；`portfolio.vol_target 0.30`；ledger tsmom +N / flow +N（预期 10/10）。

| 候选 | 时点 OOS / MDD | 静态 OOS / MDD | D-017 双通过 | 对 TP6-entry | 退出次数比 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| TP3-entry | | | | | | |
| TP4-entry | | | | | | |
| TP6-entry（现行，0.30 重跑） | | | 对 baseline： | — | 1.00 | 关闭 K-EX03 的采纳前提 |
| TP6-current | | | | | | |

节流 0.05/0.20/0.25 在 0.30 上：时点 <…>、静态 <…>（informational，保持关闭）。

Claim 更新：C-EX02a-TP → <SUPPORTED/REFUTED>；C-EX02c → <SUPPORTED/REFUTED>。下一步：<按判定：Task 9 采纳流程（需操作者批准与 Q6 窗口）/ 记负结果，Task 7 是否进入由 Q1 决定>。
```

- [ ] **Step 5: 提交（报告 + 脚本 + 日志一起）**

```bash
git add reports/research/overlay-*.json reports/research/overlay-*.md reports/research/trials.jsonl scratchpad/p22_verdict.py docs/RESEARCH_LOG.md
git commit -m "research: P22 裁决——<结论一句话>"
```

---

## Task 4：日报"噪声尺度"段 + M-005 反事实监测（DL-EX0 / DL-EX0b）

**前置：** Q5 = 抬上限或指名删除。

**Files:**
- Modify: `starquant_live/reports.py`（新函数 `noise_scale`、`exit_counterfactuals`；`daily_payload` 两个新键；`daily_markdown` 两段）
- Modify: `starquant_cli/live_cmd.py:25`（import）、`:527-534`（`daily_payload(...)` 调用）
- Test: `tests/live/test_report_metrics.py`
- Modify: `tests/architecture/test_source_budget.py`（live +77、cli +2）

**Interfaces:**
- Produces: `noise_scale(store, day, *, vol_target) -> dict`、`exit_counterfactuals(store, *, closes=None, root=".starquant/data", interval="1h", horizons=(24, 72)) -> dict`；`daily_payload(..., vol_target: float | None = None, data_root: str | Path = ".starquant/data", closes=None)`；payload 新键 `noise_scale`、`exit_counterfactual`。
- Consumes: `_cycles(store, window_days=30)`（`reports.py:89`）、`_day_of`、`StateStore.read_jsonl`、`KlineStore.load(symbol, interval)` 返回含 `open_time`、`close` 列的 DataFrame。

- [ ] **Step 1: 失败测试（追加到 `tests/live/test_report_metrics.py`）**

```python
def _aligned(i: int, equity: float, **extra: object) -> dict:
    """Like `_cycle`, but starting at a UTC midnight so a three-bar giveback cannot straddle a day boundary."""
    start = BASE - BASE % (24 * HOUR) + 24 * HOUR
    return {"bar_open_ms": start + i * HOUR, "bar": f"bar-{i}", "equity": equity, "construction": "aaa", **extra}


def test_noise_scale_reads_a_giveback_in_design_sigma(tmp_path: Path) -> None:
    """DL-EX0: a 65 U giveback on a 10,949 U book at vol_target 0.30 is 0.38 design daily sigma, not an event."""
    from starquant_live.reports import BACKTEST_EXITS_PER_WEEK, noise_scale

    path = [10_704.0 + 5.0 * i for i in range(60)] + [11_014.0, 10_979.0, 10_949.0]
    cycles = [_aligned(i, value) for i, value in enumerate(path)]  # bars 48-62 share the third UTC day
    day = _day_of_bar(cycles[60]["bar_open_ms"])
    result = noise_scale(_store(tmp_path, cycles), day, vol_target=0.30)
    assert abs(result["design_daily_sigma_u"] - 10_949.0 * 0.30 / math.sqrt(365.0)) < 1e-6
    assert result["peak_giveback_u"] == pytest.approx(65.0)
    assert result["giveback_in_design_sigma"] == pytest.approx(65.0 / (10_949.0 * 0.30 / math.sqrt(365.0)))
    assert result["realised_daily_sigma_u"] is not None
    assert result["expected_exits_so_far"] == pytest.approx(BACKTEST_EXITS_PER_WEEK / 7 * (63 / 24))
    assert result["exits_so_far"] == 0


def test_noise_scale_without_vol_target_or_cycles_does_not_crash(tmp_path: Path) -> None:
    from starquant_live.reports import noise_scale

    empty = noise_scale(_store(tmp_path, []), "2026-09-07", vol_target=None)
    assert empty["design_daily_sigma_u"] is None and empty["peak_giveback_u"] is None


def test_exit_counterfactuals_mark_young_events_pending_and_price_old_ones(tmp_path: Path) -> None:
    """M-005 as monitoring (K-EX12): what the exited position would have earned had it stayed."""
    import pandas as pd

    from starquant_live.reports import exit_counterfactuals

    event = {"symbol": "AAAUSDT", "rule": "TAKE_PROFIT", "target": 0.05, "price": 100.0, "entry_price": 90.0, "unit": 0.02}
    cycles = [_cycle(0, equity=10_000.0, exit_events=[event])] + [_cycle(i, equity=10_000.0) for i in range(1, 100)]
    young = [_cycle(i, equity=10_000.0) for i in range(0, 10)]
    young[5] = _cycle(5, equity=10_000.0, exit_events=[event])
    closes = {"AAAUSDT": pd.Series([100.0 * (1.0 + 0.001 * i) for i in range(200)], index=[BASE + i * HOUR for i in range(200)])}
    priced = exit_counterfactuals(_store(tmp_path / "a", cycles), closes=lambda symbol: closes[symbol])
    assert priced["events"] == 1 and priced["pending"] == 0
    # stayed in: 0.05 x 10,000 x (close_{t+24}/close_t - 1) = 500 x 0.024 = 12.0 U; the exit paid 2 x 7 bps x 500 = 0.7 U
    assert priced["by_horizon"]["24"]["mean_counterfactual_u"] == pytest.approx(12.0)
    assert priced["by_horizon"]["72"]["mean_counterfactual_u"] == pytest.approx(36.0)
    assert priced["by_horizon"]["24"]["n"] == 1 and priced["cost_saved_u"] == pytest.approx(0.7)
    pending = exit_counterfactuals(_store(tmp_path / "b", young), closes=lambda symbol: closes[symbol].iloc[:8])
    assert pending["events"] == 1 and pending["pending"] == 1 and pending["by_horizon"]["24"]["n"] == 0
    assert priced["n_needed_for_decision"] == 16
```

并在 `test_daily_payload_carries_every_new_section` 的断言里加两行：

```python
    assert "noise_scale" in payload and "exit_counterfactual" in payload
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/pytest tests/live/test_report_metrics.py -k "noise_scale or counterfactual or every_new_section" -v
```
Expected: FAIL，`ImportError: cannot import name 'noise_scale'`。

- [ ] **Step 3: 实现（`starquant_live/reports.py`）**

在 import 区加：

```python
from collections.abc import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
```

（`Mapping, Sequence` 原本就从 `collections.abc` 导入；把 `Callable` 加进同一行即可。）在 `exit_and_pool_events` 之后加：

```python
BACKTEST_EXITS_PER_WEEK = 562.0 / 49_735.0 * 24.0 * 7.0  # P11: 544 take-profits + 18 stops over 49,735 hourly bars
COUNTERFACTUAL_N_FOR_DECISION = 16  # a half-sigma per-event effect at t = 2; about two months at the rate above
TURNOVER_BPS = 7.0


def noise_scale(store: StateStore, day: str, *, vol_target: float | None) -> dict[str, Any]:
    """DL-EX0: the size of a normal day, so a giveback can be read as a multiple of it instead of as a feeling.

    ``design`` is vol_target / sqrt(365) of the day's last equity; ``realised`` is the std of hourly equity
    changes over the trailing 30 days of traded cycles (bars re-baselined by an external transfer are
    skipped), scaled by sqrt(24); ``peak_giveback`` is the largest drop from the running equity high inside
    the day.  The expected exit count pro-rates the P11 backtest rate for the whole book to the cycles seen
    so far in the current construction.
    """
    trailing = _cycles(store, window_days=30)
    today = [row for row in trailing if _day_of(row) == day]
    equities = [float(row["equity"]) for row in today]
    last = equities[-1] if equities else None
    design = (float(vol_target) / math.sqrt(365.0) * last) if (vol_target and last) else None
    steps = [
        float(b["equity"]) - float(a["equity"])
        for a, b in pairwise(trailing)
        if not (b.get("external_flows") or {}).get("rebaselined")
    ]
    realised = float(np.std(steps, ddof=1) * math.sqrt(24.0)) if len(steps) >= 24 else None
    peak = giveback = None
    for value in equities:
        peak = value if peak is None else max(peak, value)
        giveback = (peak - value) if giveback is None else max(giveback, peak - value)
    window = evidence_window(store)
    bars = int(window.get("bars") or 0)
    exits = sum(len(row.get("exit_events") or []) for row in trailing if int(row.get("bar_open_ms") or 0) >= int(window.get("since_ms") or 0))
    return {
        "design_daily_sigma_u": design,
        "realised_daily_sigma_u": realised,
        "peak_giveback_u": giveback,
        "giveback_in_design_sigma": (giveback / design) if (giveback is not None and design) else None,
        "expected_exits_so_far": BACKTEST_EXITS_PER_WEEK / 7.0 * (bars / 24.0),
        "exits_so_far": exits,
    }


def _store_closes(root: str | Path, interval: str) -> Callable[[str], pd.Series]:
    def loader(symbol: str) -> pd.Series:
        frame = KlineStore(root).load(symbol, interval)
        return pd.Series(frame["close"].astype(float).to_numpy(), index=frame["open_time"].astype(int).to_numpy())

    return loader


def exit_counterfactuals(
    store: StateStore,
    *,
    closes: Callable[[str], pd.Series] | None = None,
    root: str | Path = ".starquant/data",
    interval: str = "1h",
    horizons: Sequence[int] = (24, 72),
) -> dict[str, Any]:
    """M-005 as monitoring (K-EX12): for every exit the loop ever made, what the position would have earned had it stayed.

    Counterfactual P&L at horizon h = target x equity x (close_{t+h} / close_t - 1), with close_t the price the
    event recorded and close_{t+h} the mainnet close h bars later; the cost the exit paid is 2 x 7 bps x
    |target| x equity (out and back in).  Events younger than the longest horizon are ``pending``.  About 16
    priced events are needed before the mean says anything (a half-sigma effect at t = 2), which at the
    backtest's 1.9 exits per week is roughly two months - the reason this monitors and D-017 keeps the verdict.
    """
    loader = closes or _store_closes(root, interval)
    span_ms = int(interval_seconds(interval) * 1000)
    rows: list[dict[str, Any]] = []
    pending = 0
    cost_saved = 0.0
    cache: dict[str, pd.Series] = {}
    for record in store.read_jsonl(store.cycles_path):
        events = record.get("exit_events") or []
        if not events or record.get("equity") is None:
            continue
        equity = float(record["equity"])
        bar = int(record.get("bar_open_ms") or 0)
        for event in events:
            if event.get("rule") == "COOLDOWN" or not event.get("price"):
                continue
            symbol = str(event.get("symbol"))
            notional = float(event.get("target") or 0.0) * equity
            cost_saved += 2.0 * TURNOVER_BPS / 10_000.0 * abs(notional)
            if symbol not in cache:
                try:
                    cache[symbol] = loader(symbol)
                except FileNotFoundError:
                    cache[symbol] = pd.Series(dtype=float)
            series = cache[symbol]
            row = {"symbol": symbol, "rule": event.get("rule"), "bar_open_ms": bar, "price": float(event["price"])}
            complete = True
            for horizon in horizons:
                future = bar + horizon * span_ms
                if future in series.index:
                    row[str(horizon)] = notional * (float(series.loc[future]) / float(event["price"]) - 1.0)
                else:
                    row[str(horizon)] = None
                    complete = False
            pending += 0 if complete else 1
            rows.append(row)
    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        values = [float(row[str(horizon)]) for row in rows if row.get(str(horizon)) is not None]
        by_horizon[str(horizon)] = {
            "n": len(values),
            "mean_counterfactual_u": float(np.mean(values)) if values else None,
            "share_where_staying_paid": float(np.mean([v > 0 for v in values])) if values else None,
        }
    return {
        "events": len(rows),
        "pending": pending,
        "cost_saved_u": cost_saved,
        "by_horizon": by_horizon,
        "n_needed_for_decision": COUNTERFACTUAL_N_FOR_DECISION,
        "rows": rows[-20:],
    }
```

import 区还要加一行 `from starquant_alpha.panel import interval_seconds`（`starquant_live/config.py` 已从同一处导入它）。

`daily_payload` 签名与返回：

```python
def daily_payload(
    store: StateStore,
    day: str,
    expectations: dict[str, Any] | None = None,
    probes: Sequence[ProbeParams] = (),
    risk_budget: RiskBudgetParams | None = None,
    dataset: Mapping[str, Any] | None = None,
    *,
    vol_target: float | None = None,
    data_root: str | Path = ".starquant/data",
    closes: Callable[[str], pd.Series] | None = None,
) -> dict[str, Any]:
```

在返回字典的 `"events": exit_and_pool_events(store, day),` 后加：

```python
        "noise_scale": noise_scale(store, day, vol_target=vol_target),
        "exit_counterfactual": exit_counterfactuals(store, closes=closes, root=data_root),
```

`daily_markdown` 在 `"Exits and pool (M-005 / M-006)"` 段之后加两段：

```python
            (
                "Noise scale (DL-EX0)",
                {
                    "design_daily_sigma_u": _fmt_num((payload.get("noise_scale") or {}).get("design_daily_sigma_u")),
                    "realised_daily_sigma_u": _fmt_num((payload.get("noise_scale") or {}).get("realised_daily_sigma_u")),
                    "peak_giveback_u": _fmt_num((payload.get("noise_scale") or {}).get("peak_giveback_u")),
                    "giveback_in_design_sigma": _fmt_num((payload.get("noise_scale") or {}).get("giveback_in_design_sigma")),
                    "expected_exits_so_far": _fmt_num((payload.get("noise_scale") or {}).get("expected_exits_so_far")),
                    "exits_so_far": (payload.get("noise_scale") or {}).get("exits_so_far"),
                },
            ),
            (
                "Exit counterfactuals (M-005, monitoring only)",
                {
                    "events": (payload.get("exit_counterfactual") or {}).get("events"),
                    "pending": (payload.get("exit_counterfactual") or {}).get("pending"),
                    "mean_24h_u": _fmt_num(((payload.get("exit_counterfactual") or {}).get("by_horizon") or {}).get("24", {}).get("mean_counterfactual_u")),
                    "mean_72h_u": _fmt_num(((payload.get("exit_counterfactual") or {}).get("by_horizon") or {}).get("72", {}).get("mean_counterfactual_u")),
                    "cost_saved_u": _fmt_num((payload.get("exit_counterfactual") or {}).get("cost_saved_u")),
                    "n_needed_for_decision": (payload.get("exit_counterfactual") or {}).get("n_needed_for_decision"),
                },
            ),
```

`starquant_cli/live_cmd.py`：import 行改为 `from starquant_live.composition import build_model, load_registry, portfolio_params`；`report_daily` 的调用加两个关键字参数：

```python
    data = daily_payload(
        store,
        chosen,
        expectations_from_evidence(_evidence_reports(registry)),
        probes_from_registry(registry),
        RiskBudgetParams.from_mapping(payload.get("risk_budget", {}) or {}),
        dataset=asdict(registry_dataset_problems(registry, data_root, _interval(payload))),
        vol_target=portfolio_params(payload).vol_target,
        data_root=data_root,
    )
```

- [ ] **Step 4: 运行测试**

```bash
.venv/bin/pytest tests/live/test_report_metrics.py -v
```
Expected: 全部 PASS。

- [ ] **Step 5: 在真实状态上跑一次日报（只读）并目视两段**

```bash
.venv/bin/python -m starquant_cli report daily --out /tmp/starquant/plan-check
/bin/cat /tmp/starquant/plan-check/$(date -u +%F).md | grep -A8 'Noise scale'
```
Expected: `design_daily_sigma_u` ≈ 170、`peak_giveback_u` 为当日数字、`exits_so_far 0`；反事实段 `events 0`。`--out` 指向临时目录，不覆盖 `reports/daily`。

- [ ] **Step 6: `CEILING` 抬升记录 + 提交**

```python
# Raise 2026-09-0X, with the sentence the rule requires: +77 in starquant_live and +2 in starquant_cli for two
# observations the exits analysis found missing - a noise scale (design daily sigma in USDT, so a 65 U
# giveback reads as 0.4 sigma rather than as a feeling) and M-005's promised 24/72h counterfactual, shipped
# as monitoring with its own n-for-decision, because at 1.9 exits a week it cannot adjudicate in 30 days.
CEILING = {
    ...
    "starquant_live": 5_143,
    "starquant_cli": 3_293,
```

```bash
.venv/bin/pytest -q
git add starquant_live/reports.py starquant_cli/live_cmd.py tests/live/test_report_metrics.py tests/architecture/test_source_budget.py
git commit -m "feat(live): 日报噪声尺度段 + M-005 反事实监测（DL-EX0/0b，K-EX12：监测不裁决）"
```

---

## Task 5：E-EX14 的 ledger 处置（Q4）

**前置：** Q4 已回答。

### 5A（Q4 = 补记）

**Files:**
- Create: `scratchpad/e_ex14_ledger.py`
- Produces: `reports/research/trials.jsonl` +14 行（tsmom 7、flow 7）

- [ ] **Step 1: 写脚本（重算同一份重放并逐配置记账）**

```python
"""E-EX14 -> ledger (K-EX07): the seven exit configurations replayed on the live record are diagnostic trials.

They cannot select anything (60 bars), but the repository's rule is that every diagnostic configuration is
charged; this records them under run_id "E-EX14" with the replay's own annualised Sharpe, the live window as
the range, the 18 live symbols, and the live construction fingerprint as the construction digest.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from starquant_alpha.overlays.exits import ExitParams, apply_exits, daily_vol
from starquant_alpha.validation.ledger import TrialRecord, resolve_ledger_path
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_cmd import _record_trial, _short_digest, _symbol_set_hash
from starquant_live.composition import load_registry

CONFIGS = [
    ExitParams(),
    ExitParams(stop_loss=6, take_profit=3),
    ExitParams(stop_loss=6, take_profit=2),
    ExitParams(stop_loss=6, take_profit=1.5),
    ExitParams(stop_loss=6, take_profit=1),
    ExitParams(stop_loss=6, take_profit=6, trailing_stop=2),
    ExitParams(stop_loss=6, take_profit=6, trailing_stop=1),
]
START = "2026-09-04T17:21"
EQUITY = 10_704.55


def main() -> None:
    records = [json.loads(line) for line in open(".starquant/live/cycles.jsonl", encoding="utf-8")]
    rows = {int(r["bar_open_ms"]): r["targets"] for r in records if r.get("at", "") >= START and r.get("targets")}
    bars = sorted(rows)
    symbols = sorted({s for t in rows.values() for s in t})
    weights = pd.DataFrame([[rows[b].get(s, 0.0) for s in symbols] for b in bars],
                           index=pd.to_datetime(bars, unit="ms", utc=True), columns=symbols)
    closes = {}
    for s in symbols:
        frame = pd.read_parquet(f".starquant/data/klines/{s}/1h.parquet").sort_values("open_time")
        closes[s] = pd.Series(frame["close"].astype(float).to_numpy(), index=pd.to_datetime(frame["open_time"], unit="ms", utc=True))
    close = pd.DataFrame(closes).sort_index().loc[: weights.index[-1] + pd.Timedelta(hours=1)]
    rets = close.pct_change()
    sigma = daily_vol(close, ExitParams()).reindex(index=weights.index, columns=symbols)
    construction = json.loads(open(".starquant/live/heartbeat.json", encoding="utf-8").read())["construction"]
    registry = load_registry("config/alpha_registry.yaml")
    ledger = resolve_ledger_path()
    stamp = datetime.now(UTC).isoformat()
    charged = 0
    for params in CONFIGS:
        w = apply_exits(weights, close, params, sigma_1d=sigma).weights.reindex(close.index).ffill().fillna(0.0).loc[weights.index[0]:]
        pnl = (w.shift(1) * rets.loc[w.index]).sum(axis=1) - w.diff().abs().sum(axis=1).fillna(0.0) * 7e-4
        sharpe = float(pnl.mean() / pnl.std(ddof=1) * (8760 ** 0.5)) if pnl.std(ddof=1) > 0 else None
        overlay = {"stop_loss": params.stop_loss, "trailing_stop": params.trailing_stop, "take_profit": params.take_profit}
        for entry in registry.enabled:
            charged += _record_trial(ledger, TrialRecord(
                strategy=entry.id, param_key=param_key(dict(entry.params)), sharpe_annual=sharpe, bars_per_year=8760.0,
                recorded_at=stamp, range_start=str(weights.index[0]), range_end=str(weights.index[-1]),
                symbols=len(symbols), run_id="E-EX14", construction_digest=str(construction),
                symbol_set_hash=_symbol_set_hash(symbols), overlay_digest=_short_digest({"kind": "exits", "params": overlay}),
            ))
    print(f"charged {charged} rows to {ledger} (expected 14)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行并核对**

```bash
.venv/bin/python scratchpad/e_ex14_ledger.py
grep -c '"run_id": "E-EX14"' reports/research/trials.jsonl
```
Expected: `charged 14 rows`；grep 输出 `14`。第二次运行应打印 `charged 0`（去重）。

- [ ] **Step 3: 在 RESEARCH_LOG 记一段并提交**

```markdown
## 2026-09-0X · E-EX14 补记 ledger（K-EX07）

止盈止损分析里的 60 bar 实盘重放跑了 7 个退出配置，按"每个诊断配置计入 prior-trials"补记：tsmom +7、flow +7，`run_id E-EX14`，Sharpe 为重放自身的年化值（n=60 bar，仅作 ledger 占位，不作证据）。此后任何 `--prior-trials` 申报都以 ledger 行数为准。
```

```bash
git add scratchpad/e_ex14_ledger.py reports/research/trials.jsonl docs/RESEARCH_LOG.md
git commit -m "research: E-EX14 的 7 个实盘重放配置补记 ledger（K-EX07）"
```

### 5B（Q4 = 豁免）

- [ ] **Step 1: 在 RESEARCH_LOG 追加规则段并提交**

```markdown
## 2026-09-0X · 规则：短窗描述性实盘重放不计费（K-EX07 的处置，操作者裁定）

定义：在实盘记录（`cycles.jsonl` 的目标权重 × 公开收盘价）上、窗口 ≤ 100 根 bar、且不用于选择任何参数的重放，记为"描述性重放"，不计入 `trials.jsonl`。条件：(1) 报告里必须标 E5 并写明 n；(2) 不得据此改任何配置；(3) 超过 100 bar 或用于选择即按诊断试验计费。首例：`2026-09-07-exits-adaptive-tp-sl-deep-analysis.md` 的 E-EX14（7 配置 × 60 bar）。
```

```bash
git add docs/RESEARCH_LOG.md
git commit -m "docs: 短窗描述性实盘重放不计费的规则（K-EX07，操作者裁定）"
```

---

## Task 6：Q6 规则写入 RUNBOOK

**前置：** Q6 = 接受。

**Files:**
- Modify: `docs/RUNBOOK.md`（`## 改了 registry / profile 之后` 段末尾）

- [ ] **Step 1: 追加段落**

```markdown
### 采纳 exit overlay / 信号改动的最短干净窗口（K-EX14，2026-09-0X 操作者裁定）

M-010（30 天 income 归因）在当前构造指纹下不满 30 天连续记录之前，不采纳任何 exit overlay 或信号改动——研究可以跑、结论可以写，但 `config/live.demo.yaml` 的 `exits` 与 registry 的信号参数不动。唯一例外：P13 阶梯触发（回撤 −35% / −50%），那是预登记的降档，不是采纳。当前窗口起点：2026-09-06T10:19Z（P18 重启），最早采纳日 2026-10-06。每次采纳都是构造变更，窗口重新计数。
```

- [ ] **Step 2: 提交**

```bash
git add docs/RUNBOOK.md
git commit -m "docs(runbook): 采纳 exit overlay/信号改动的最短干净窗口（K-EX14）"
```

---

## Task 7（条件）：O-EX2 行情效率比切档的 2×2（`tp_scale` + ER）

**前置：** Task 3 已裁决；Q1 = A；操作者明确要测行情切档并接受 tsmom + flow 各 +4 ledger。先在 RESEARCH_LOG 追加 P22b 预登记（网格与规则见 Step 6），提交后再跑。

**Files:**
- Modify: `starquant_alpha/overlays/exits.py`（`ExitParams` 四个字段；`efficiency_ratio`、`regime_tp_scale`；`exit_step(..., tp_scale=1.0)`；`apply_exits` 传 `tp_scale`）
- Modify: `starquant_live/exits.py:40-52`（实盘按 bar 算 ER）
- Modify: `starquant_live/engine.py` 指纹 `exits` 块加四个字段
- Test: `tests/alpha/test_overlays.py`；`tests/architecture/test_source_budget.py`（alpha +45、live +12）

**Interfaces:**
- Produces: `ExitParams.regime_window: int = 0`（0 = 关）、`regime_er_cut: float = 0.05`、`regime_tp_scale: float = 0.5`、`regime_side: str = "low"`（`low | high`）；`efficiency_ratio(close: pd.DataFrame, window: int) -> pd.DataFrame`；`regime_tp_scale(close: pd.DataFrame, params: ExitParams) -> pd.DataFrame | None`；`exit_step(..., *, bar_step=1, tp_scale=1.0)`。
- 网格 JSON：`{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[6.0],"regime_window":[168],"regime_er_cut":[0.05],"regime_tp_scale":[0.5],"regime_side":["low","high"]}` → 两个候选（低 ER 臂、镜像臂）；固定 TP3 臂沿用 Task 3 的 TP3-entry 报告，不重跑。

- [ ] **Step 1: 失败测试**

```python
def test_efficiency_ratio_is_one_on_a_straight_line_and_near_zero_on_a_zigzag() -> None:
    from starquant_alpha.overlays.exits import efficiency_ratio

    index = pd.date_range("2024-01-01", periods=40, freq="h", tz="UTC")
    line = pd.DataFrame({"A": [100.0 * 1.01**k for k in range(40)]}, index=index)
    zigzag = pd.DataFrame({"A": [100.0 if k % 2 == 0 else 101.0 for k in range(40)]}, index=index)
    assert efficiency_ratio(line, 10)["A"].iloc[-1] == pytest.approx(1.0)
    assert efficiency_ratio(zigzag, 10)["A"].iloc[-1] < 0.05
    assert efficiency_ratio(line, 10)["A"].iloc[:10].isna().all()  # warmup


def test_regime_tp_scale_tightens_only_inside_the_chosen_regime_and_is_off_by_default() -> None:
    from starquant_alpha.overlays.exits import regime_tp_scale

    index = pd.date_range("2024-01-01", periods=40, freq="h", tz="UTC")
    zigzag = pd.DataFrame({"A": [100.0 if k % 2 == 0 else 101.0 for k in range(40)]}, index=index)
    assert regime_tp_scale(zigzag, ExitParams(take_profit=6.0)) is None
    low = regime_tp_scale(zigzag, ExitParams(take_profit=6.0, regime_window=10, regime_er_cut=0.05, regime_tp_scale=0.5, regime_side="low"))
    high = regime_tp_scale(zigzag, ExitParams(take_profit=6.0, regime_window=10, regime_er_cut=0.05, regime_tp_scale=0.5, regime_side="high"))
    assert low["A"].iloc[-1] == 0.5 and high["A"].iloc[-1] == 1.0
    assert low["A"].iloc[:10].eq(1.0).all()  # warmup bars scale nothing
    with pytest.raises(ValueError):
        ExitParams(regime_window=10, regime_side="sideways")


def test_tp_scale_halves_the_take_profit_distance() -> None:
    """A +4-unit move: no take-profit at 6 units, take-profit once the regime scales 6 to 3."""
    path = [100.0, 102.0, 104.0, 106.0, 108.0, 108.0]
    weights, close, vol = _frames(path)  # sigma 0.02 -> one unit is 2 points
    state = ExitState()
    params = ExitParams(take_profit=6.0)
    for t, price in enumerate(path[:5]):
        state, _, reason = exit_step(state, 0.1, price, 0.02, t, params)
        assert reason == ""
    scaled, w, reason = exit_step(state, 0.1, 108.0, 0.02, 5, params, tp_scale=0.5)
    assert reason == TAKE_PROFIT and w == 0.0
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/pytest tests/alpha/test_overlays.py -k "efficiency or regime or tp_scale" -v
```
Expected: FAIL（`ImportError` / `TypeError`）。

- [ ] **Step 3: 实现**

`ExitParams` 加字段与校验：

```python
    regime_window: int = 0  # bars of Kaufman efficiency ratio; 0 disables the regime scaling (EXP-EX2)
    regime_er_cut: float = 0.05  # pre-registered constant: BTC's 7-day ER read 0.020 in the 2026-09 consolidation, 0.118 over 30 days
    regime_tp_scale: float = 0.5  # take_profit multiplier inside the regime (6 -> 3)
    regime_side: str = "low"  # low: tighten when ER < cut (the operator's hypothesis); high: the mirror control arm
```

`__post_init__` 末尾：

```python
        if self.regime_window < 0 or not 0 < self.regime_tp_scale <= 1 or not 0 <= self.regime_er_cut <= 1:
            raise ValueError("invalid regime parameters")
        if self.regime_side not in {"low", "high"}:
            raise ValueError("regime_side must be 'low' or 'high'")
```

模块级函数（放在 `daily_vol` 之后）：

```python
def efficiency_ratio(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """Kaufman's efficiency ratio over ``window`` bars: |net log move| / sum of |bar log moves|, in [0, 1]; NaN in the warmup."""
    logp = np.log(close.astype(float))
    net = (logp - logp.shift(window)).abs()
    path = logp.diff().abs().rolling(window, min_periods=window).sum()
    return (net / path.where(path > 0)).clip(0.0, 1.0)


def regime_tp_scale(close: pd.DataFrame, params: ExitParams) -> pd.DataFrame | None:
    """Per symbol-bar multiplier on ``take_profit`` (EXP-EX2): ``regime_tp_scale`` inside the chosen regime, 1 elsewhere.

    ``regime_side="low"`` tightens the take-profit when the market is inefficient (the operator's "chop"
    hypothesis); ``"high"`` is the mirror control arm.  The cut is a pre-registered constant, never a rolling
    reference: the live loop only holds ~1,442 bars and a rolling median would make research and live
    disagree about the regime (KILL-027's shape).  Warmup bars scale nothing.
    """
    if params.regime_window <= 0:
        return None
    er = efficiency_ratio(close, params.regime_window)
    inside = (er < params.regime_er_cut) if params.regime_side == "low" else (er >= params.regime_er_cut)
    scale = pd.DataFrame(np.where(inside.to_numpy(), params.regime_tp_scale, 1.0), index=close.index, columns=close.columns)
    return scale.where(er.notna(), 1.0)
```

`exit_step` 签名加 `tp_scale: float = 1.0`，止盈判断改为：

```python
        elif params.take_profit > 0 and favourable >= params.take_profit * tp_scale:
            reason = TAKE_PROFIT
```

`apply_exits` 在 `vols = vol.to_numpy(dtype=float)` 之后：

```python
    scale_frame = regime_tp_scale(close, params)
    scales = (
        scale_frame.reindex(index=weights.index, columns=weights.columns).fillna(1.0).to_numpy(dtype=float)
        if scale_frame is not None
        else np.ones_like(values)
    )
```

循环里的调用改为：

```python
            new_state, weight, reason = exit_step(state, row[j], prices[t, j], vols[t, j], t, params, tp_scale=float(scales[t, j]))
```

`starquant_live/exits.py` 的 `apply` 循环里，`sigma = self._sigma(frame)` 之后：

```python
            tp_scale = 1.0
            if self.params.regime_window > 0:
                closes = pd.DataFrame({"x": frame["close"].astype(float).to_numpy()})
                scale = regime_tp_scale(closes, self.params)
                tp_scale = float(scale["x"].iloc[-1]) if scale is not None else 1.0
```

并在 `exit_step(...)` 调用里传 `tp_scale=tp_scale`（import 行加 `regime_tp_scale`）。指纹 `exits` 块加 `"regime_window"`、`"regime_er_cut"`、`"regime_tp_scale"`、`"regime_side"` 四个键。

- [ ] **Step 4: 运行测试；全量；`CEILING` 抬升（alpha +45、live +12，句子写明"EXP-EX2 的 2×2 需要研究与实盘同一份 ER，固定阈值"）；提交**

```bash
.venv/bin/pytest tests/alpha/test_overlays.py tests/live -q
git add starquant_alpha/overlays/exits.py starquant_live/exits.py starquant_live/engine.py tests/alpha/test_overlays.py tests/architecture/test_source_budget.py
git commit -m "feat(alpha): exit overlay 按效率比 regime 缩放止盈（EXP-EX2 的 2×2，固定阈值）"
```

- [ ] **Step 5: 预登记 P22b（追加 RESEARCH_LOG，提交后才能跑）**

```markdown
## 2026-09-0X · P22b 预登记：行情效率比切档止盈的 2×2（先写后跑）

网格（两 universe 各一次调用）：`stop_loss [6.0] × trailing_stop [0.0] × take_profit [6.0] × regime_window [168] × regime_er_cut [0.05] × regime_tp_scale [0.5] × regime_side ["low","high"]` → 低 ER 臂、镜像臂各一。固定 TP3 臂 = P22 的 TP3-entry，不重跑。 ledger 预期 tsmom +4、flow +4（节流去重为 0）。
判定：低 ER 臂双 universe 通过 D-017 **且** 双 universe OOS Sharpe 都高于 TP3-entry **且** 镜像臂至少一个 universe 不通过 → C-EX02b SUPPORTED（候选进入 Task 9）。低 ER 臂与镜像臂都通过且都不优于 TP3-entry → "TP3 处处有效"，属 C-EX02a-TP，C-EX02b 不成立。其余 → C-EX02b REFUTED。ER 常数 168 / 0.05 只允许这一组。
```

- [ ] **Step 6: 运行与裁决**

```bash
.venv/bin/python -m starquant_cli research overlay --universe pit    --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[6.0],"regime_window":[168],"regime_er_cut":[0.05],"regime_tp_scale":[0.5],"regime_side":["low","high"]}'
.venv/bin/python -m starquant_cli research overlay --universe static --exits-grid '{"stop_loss":[6.0],"trailing_stop":[0.0],"take_profit":[6.0],"regime_window":[168],"regime_er_cut":[0.05],"regime_tp_scale":[0.5],"regime_side":["low","high"]}'
```
裁决表手工按上面的规则填入 RESEARCH_LOG "P22b 裁决"段（四列：低 ER 臂、镜像臂、TP3-entry、baseline），提交报告 + ledger + 日志。

---

## Task 8（条件）：O-EX1 信号侧退出滞回——先描述统计，再实现与验证

**前置：** Q1 = A 且操作者同意先花 1 个 tsmom ledger 名额做描述统计。

### 8.1 描述统计（计 1 个 trial）

**Files:**
- Create: `scratchpad/p23_subthreshold_forward.py`

- [ ] **Step 1: 脚本**

```python
"""P23 step 0 (K-EX02): do sub-threshold holds earn less than actionable holds?  One diagnostic trial, charged.

For every held symbol-bar of the shipped tsmom on the point-in-time universe, split by whether the raw
score was actionable (|score| >= 0.20) or sub-threshold (held on NO_ACTION), and compare the sign-adjusted
forward return at 24 and 72 bars.  If the sub-threshold bars are not significantly worse, O-EX1 stops here.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores
from starquant_alpha.validation.labels import forward_returns
from starquant_alpha.validation.ledger import TrialRecord, resolve_ledger_path
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_cmd import _load, _membership, _record_trial, _resolve_symbols, _short_digest, _symbol_set_hash
from starquant_live.composition import build_model, load_registry
from starquant_shared.config import load_yaml

ROOT, INTERVAL, UNIVERSE = ".starquant/data", "1h", "pit"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry("config/alpha_registry.yaml")
    model = build_model(registry, profile)
    symbols = _resolve_symbols(ROOT, "", INTERVAL, UNIVERSE)
    panel = _load(ROOT, symbols, INTERVAL, None, None, True)
    membership = _membership(ROOT, UNIVERSE, panel)
    entry = next(e for e in registry.enabled if e.id == "tsmom")
    params = TsmomParams.from_mapping(entry.params)
    raw = tsmom_scores(panel.close, params)
    held = model.strategy_targets(panel, membership)["tsmom"]
    direction = np.sign(held.fillna(0.0))
    lines = []
    for horizon in (24, 72):
        fwd = forward_returns(panel.close, horizon) * direction
        active = direction != 0
        sub = active & (raw.abs() < params.entry_threshold)
        act = active & (raw.abs() >= params.entry_threshold)
        a, s = fwd.where(act).stack().dropna(), fwd.where(sub).stack().dropna()
        # overlapping labels: shrink the effective n by the horizon (a conservative, not exact, correction)
        se = math.sqrt(a.var() / (len(a) / horizon) + s.var() / (len(s) / horizon))
        t = (a.mean() - s.mean()) / se if se > 0 else float("nan")
        lines.append(f"h={horizon}: actionable mean {a.mean()*1e4:+.1f} bps (n {len(a)}), sub-threshold mean {s.mean()*1e4:+.1f} bps (n {len(s)}), diff t {t:+.2f}")
    print("\n".join(lines))
    ledger = resolve_ledger_path()
    charged = _record_trial(ledger, TrialRecord(
        strategy="tsmom", param_key=param_key(dict(entry.params)), sharpe_annual=None, bars_per_year=float(panel.bars_per_year),
        recorded_at=datetime.now(UTC).isoformat(), range_start=str(panel.index[0]), range_end=str(panel.index[-1]),
        symbols=len(panel.symbols), run_id="P23-step0", symbol_set_hash=_symbol_set_hash(panel.symbols),
        overlay_digest=_short_digest({"kind": "diagnostic", "what": "subthreshold_forward_returns"}),
    ))
    print(f"charged {int(charged)} row to {ledger}")


if __name__ == "__main__":
    main()
```

`_resolve_symbols(root, symbols, interval, universe_mode)`、`_load(root, symbols, interval, start, end, funding)`、`_membership(root, universe_mode, panel)` 是 `research_cmd.py:151/217/166` 的模块级函数，`research overlay` 自己就是这样调用它们的。

- [ ] **Step 2: 运行；判定写入 RESEARCH_LOG**

```bash
.venv/bin/python scratchpad/p23_subthreshold_forward.py
```
停止条件（预登记）：若 h=72 的 diff t < 2.0（次阈值段不显著更差），**O-EX1 到此为止**，记负结果，不实现 8.2。

### 8.2 实现 `exit_threshold` / `exit_dwell_bars`（仅当 8.1 通过）

**Files:**
- Modify: `starquant_alpha/signals/base.py:72-118`、`starquant_alpha/signals/tsmom.py:82-118`（`TsmomParams`）、`starquant_alpha/registry.py:44-46`、`starquant_alpha/model.py:175-178`
- Test: `tests/alpha/test_exit_threshold.py`（新建）

**Interfaces:**
- Produces: `scores_to_targets(scores, entry_threshold, *, hold=True, zero_is_exit=True, initial=None, exit_threshold: float | None = None, exit_dwell_bars: int = 0)`；`TsmomParams.exit_threshold: float | None = None`、`exit_dwell_bars: int = 0`；`StrategyEntry.exit_threshold -> float | None`、`StrategyEntry.exit_dwell_bars -> int`。默认全部关闭 = 现状（K-EX04）。

- [ ] **Step 1: 失败测试（新文件）**

```python
"""O-EX1 / EXP-EX1: a held position leaves when its score has decayed below `exit_threshold` for `exit_dwell_bars`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.signals.base import scores_to_targets


def _scores(values: list[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({"A": values}, index=index)


def test_defaults_are_bit_identical_to_the_shipped_hold_semantics() -> None:
    rng = np.random.default_rng(3)
    scores = _scores(list(rng.normal(0, 0.3, size=500)))
    shipped = scores_to_targets(scores, 0.20)
    explicit = scores_to_targets(scores, 0.20, exit_threshold=None, exit_dwell_bars=0)
    pd.testing.assert_frame_equal(shipped, explicit)


def test_decay_exit_fires_after_the_dwell_and_a_flip_is_still_immediate() -> None:
    scores = _scores([0.5, 0.15, 0.05, 0.05, 0.05, 0.05, 0.3, -0.4, 0.05, 0.05])
    out = scores_to_targets(scores, 0.20, exit_threshold=0.10, exit_dwell_bars=3)["A"].tolist()
    # bar0 enter 0.5; bar1 0.15 is sub-threshold but above exit_threshold -> hold; bars2-4 decayed, dwell 3 reached at bar4 -> 0
    assert out[:2] == [0.5, 0.5] and out[2:4] == [0.5, 0.5] and out[4] == 0.0 and out[5] == 0.0
    assert out[6] == 0.3 and out[7] == -0.4  # re-entry and flip are immediate
    assert out[8:] == [-0.4, -0.4]  # the flip reset the dwell counter: two decayed bars are not yet three
    with pytest.raises(ValueError):
        scores_to_targets(scores, 0.20, exit_threshold=0.25)
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/pytest tests/alpha/test_exit_threshold.py -v
```
Expected: FAIL，`TypeError: scores_to_targets() got an unexpected keyword argument 'exit_threshold'`。

- [ ] **Step 3: 实现（`starquant_alpha/signals/base.py`）**

```python
def _consecutive_true(mask: pd.DataFrame) -> pd.DataFrame:
    """Length of the run of True ending at each cell (0 where False)."""
    counts = mask.astype(int)
    csum = counts.cumsum()
    reset = csum.where(~mask).ffill().fillna(0)
    return (csum - reset).where(mask, 0)


def scores_to_targets(
    scores: pd.DataFrame,
    entry_threshold: float,
    *,
    hold: bool = True,
    zero_is_exit: bool = True,
    initial: Mapping[str, float] | None = None,
    exit_threshold: float | None = None,
    exit_dwell_bars: int = 0,
) -> pd.DataFrame:
    """…（原 docstring 保留，追加下面一段）…

    ``exit_threshold`` (O-EX1 / EXP-EX1): a held target is flattened once ``|score| < exit_threshold`` has
    lasted ``exit_dwell_bars`` consecutive bars - an explicit exit written into the actionable frame, so the
    hold semantics above are untouched: a sign flip is still immediate, a score back above
    ``entry_threshold`` re-enters at once, and ``None`` (the default) is exactly the shipped behaviour of
    holding a sub-threshold position indefinitely.
    """
    if not 0 < entry_threshold <= 1:
        raise ValueError("entry_threshold must be in (0, 1]")
    if exit_threshold is not None and not 0 < exit_threshold <= entry_threshold:
        raise ValueError("exit_threshold must be in (0, entry_threshold]")
    if exit_dwell_bars < 0:
        raise ValueError("exit_dwell_bars must be >= 0")
    actionable = scores.where(scores.abs() >= entry_threshold)
    if zero_is_exit:
        actionable = actionable.mask(scores == 0.0, 0.0)
    if exit_threshold is not None and hold:
        decayed = _consecutive_true(scores.abs() < exit_threshold) >= max(1, exit_dwell_bars)
        actionable = actionable.mask(decayed & actionable.isna(), 0.0)
    seen = scores.notna().cummax()
    …（其余不变）…
```

`TsmomParams` 加两个字段并校验（`exit_threshold` 为 None 或 `(0, entry_threshold]`，`exit_dwell_bars >= 0`）。`registry.py` 的 `StrategyEntry` 加两个属性：

```python
    @property
    def exit_threshold(self) -> float | None:
        value = self.params.get("exit_threshold")
        return None if value is None else float(value)

    @property
    def exit_dwell_bars(self) -> int:
        return int(self.params.get("exit_dwell_bars", 0) or 0)
```

`model.py:175-178` 的调用改为：

```python
            held = scores_to_targets(
                scores.where(eligible),
                entry.entry_threshold,
                hold=self.hold_on_no_action,
                initial=seed,
                exit_threshold=entry.exit_threshold,
                exit_dwell_bars=entry.exit_dwell_bars,
            )
```

- [ ] **Step 4: 测试、`CEILING`（alpha +35，句子写明"默认 None/0 逐位等于现状"）、提交**

```bash
.venv/bin/pytest tests/alpha -q
git add starquant_alpha/signals/base.py starquant_alpha/signals/tsmom.py starquant_alpha/registry.py starquant_alpha/model.py tests/alpha/test_exit_threshold.py tests/architecture/test_source_budget.py
git commit -m "feat(alpha): tsmom 的信号衰减退出（exit_threshold + dwell，默认关闭即现状）"
```

- [ ] **Step 5: 预登记 P23 并运行 validate（两格，计 tsmom +2）**

```bash
N=$(grep -c '"strategy": "tsmom"' reports/research/trials.jsonl)
.venv/bin/python -m starquant_cli research validate --strategy tsmom --universe pit --prior-trials $N --grid '{"exit_threshold":[0.10],"exit_dwell_bars":[24,72]}'
.venv/bin/python -m starquant_cli research validate --strategy tsmom --universe static --prior-trials $N --grid '{"exit_threshold":[0.10],"exit_dwell_bars":[24,72]}'
```
判定按报告 §11.2 EXP-EX1：时点 OOS Sharpe ≥ 基线 −0.05 且 OOS MDD 改善 ≥ 0.5pp 且逐 bar 差 NW t ≥ −1.0 且换手上升 ≤ 25% 且成本占毛利 ≤ 15%；静态 ΔOOS ≥ 0。任一不满足 → C-EX03 REFUTED。

---

## Task 9：采纳与回滚流程（任一候选通过且操作者批准后）

**前置：** Task 3（或 7/8）裁决为 ADOPT-CANDIDATE；操作者书面批准；Q6 窗口满足（若接受）。

- [ ] **Step 1: 在 worktree 里改配置并写理由**

`config/live.demo.yaml` 的 `exits:` 块，例如采纳 current 单位：

```yaml
exits:
  stop_loss: 6.0
  trailing_stop: 0.0
  take_profit: 6.0
  cooldown_bars: 24
  vol_halflife: 48
  # 2026-09-XX (P22, operator approval <date>): k-units measured in this bar's sigma instead of the entry
  # bar's.  Evidence: overlay-<pit>.json / overlay-<static>.json on the 0.30 construction - pit <OOS>/<MDD>,
  # static <OOS>/<MDD>, both inside D-017 and not worse than TP6-entry on drawdown; exits <n> vs <m>.
  unit_mode: current
```

（采纳止盈 3σ/4σ 时改 `take_profit` 并同样写证据指针。）

- [ ] **Step 2: 演练（绝不能用 live 状态目录）**

```bash
mkdir -p /tmp/starquant/rehearsal
sed 's#state_dir: .starquant/live#state_dir: /tmp/starquant/rehearsal#' config/live.demo.yaml > /tmp/starquant/rehearsal/live.rehearsal.yaml
.venv/bin/python -m starquant_cli live run --profile /tmp/starquant/rehearsal/live.rehearsal.yaml --dry-run --cycles 1
```
Expected: 一个周期跑完，`rehearsal/cycles.jsonl` 里 `construction` 与主树不同、`exit_events` 为空或合理；主树 `.starquant/live` 未被写。

- [ ] **Step 3: 合并到 main、重启、核对**

```bash
git add config/live.demo.yaml && git commit -m "feat(live): 采纳 <候选>（P22，操作者批准 <date>）"
# 合并到 main 后，在主 checkout：
launchctl kickstart -k gui/$(id -u)/com.starquant.live
sleep 90; .venv/bin/python -m starquant_cli live status --check
```
Expected: `registry: matches the running loop`；心跳 `construction` 变为新指纹；`phase OK`。

- [ ] **Step 4: 记录**

RESEARCH_LOG 追加"采纳 <候选>：构造变更，M-010 窗口自 <重启时间> 重新计数；回滚 = 还原该行 + kickstart"。日报次日核对 `Evidence window` 段 `construction_changes_last_7d` +1。

- [ ] **Step 5: 回滚（若需要）**

```bash
git revert <采纳 commit> && launchctl kickstart -k gui/$(id -u)/com.starquant.live
```

---

## 4. Kill 关闭映射（报告 §8.2 → 本方案）

| Kill | 关闭路径 | 任务 |
| --- | --- | --- |
| K-EX01 止盈 <6σ 未测 | TP3/TP4 进网格并作为 regime 对照 | 1、3、7 |
| K-EX02 C-EX03 无证据 | 描述统计先行，t < 2 即停 | 8.1 |
| K-EX03 证据在 0.15 上 | TP6-entry 与节流在 0.30 重跑 | 3 |
| K-EX04 O-EX1 默认值 | `exit_threshold=None` / `dwell 0` 逐位等于现状，测试锁定 | 8.2 |
| K-EX05 KILL-R12 捆绑 | 每任务单独记 `CEILING` 与句子；Task 4 需 Q5 | 2、4、7、8 |
| K-EX06 换手条款 | EXP-EX1 判定含换手 ≤ +25%、成本占比 ≤ 15% | 8.2 |
| K-EX07 E-EX14 未入账 | 补记或豁免 | 5 |
| K-EX08 基差尾部 | 价格路径候选的实盘触发率对比列为 falsifier（Task 9 采纳后的日报观察） | 4、9 |
| K-EX09 输出对症 | 报告 §12 已改；本方案 §1 以 Q1 为门 | — |
| K-EX10/11 事实与分级 | 报告已改 | — |
| K-EX12 M-005 不能裁决 | 反事实段带 `n_needed_for_decision`，裁决权留在 D-017 | 4 |
| K-EX13 regime 切分 | 固定 ER 常数、2×2 判定 | 7 |
| K-EX14 最短窗口 | RUNBOOK 规则 | 6、9 |

## 5. 顺序与时间线

1. 操作者回答 Q1–Q6（至少 Q3）。
2. 同一天：Task 1（预登记提交）→ Task 2（代码 + 测试，约 1 小时）→ Task 3（四次调用各数分钟 + 裁决段）。
3. 并行且互不依赖：Task 4（Q5）、Task 5（Q4）、Task 6（Q6）。
4. 视 Task 3 结果与 Q1：Task 7 或 Task 8。
5. Task 9 不早于 2026-10-06（若 Q6 接受；窗口起点 2026-09-06T10:19Z）。Task 2 合并进主树并重启本身也会改指纹，建议与 Task 9 合并成一次重启，或先合并 Task 2 而不重启（launchd 只在下一次重启时拾取）。

## 6. 自检（写完后对照报告）

- 报告 DL-EX0 / DL-EX0b → Task 4；DL-EX1b → Task 1–3；DL-EX2 → Task 7；DL-EX1 → Task 8；采纳 → Task 9；Q4 → Task 5；Q6 → Task 6。无遗漏。
- 无占位：每个代码步骤都给了可运行的实现与断言；条件任务（7、8）标明前置与预登记先于运行。
- 类型一致：`ExitParams.unit_mode` 在 Task 2 定义、Task 3 网格与 Task 9 配置引用；`exit_step(..., tp_scale)` 在 Task 7 定义并被 `apply_exits` 与 `starquant_live/exits.py` 同名引用；`scores_to_targets(exit_threshold, exit_dwell_bars)` 在 Task 8 定义并被 `model.py` 同名引用；`daily_payload(vol_target, data_root, closes)` 在 Task 4 定义并被 `live_cmd.py` 同名传入。
- 行数估计（+12/+1、+77/+2、+45/+12、+35）是估计，`test_source_budget.py` 会以实测为准；句子不变，数字按实测改。
