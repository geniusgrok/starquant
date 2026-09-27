# 策略体检报告 · backtest-guard

```
══════════════════════════════════════════
   策略体检报告 · backtest-guard
══════════════════════════════════════════
```

**受检对象**：StarQuant（Binance USDⓈ-M 永续，demo/testnet），main @ `3e5c44d`
**扫描**：`starquant_alpha` / `starquant_data` / `starquant_exchange` / `starquant_live` / `starquant_cli` ≈ 17.9k 行
（已排除 `worktrees/` 下 8 份分支副本与 `tests/` 的 16.7k 行）
**上一份**：`docs/analysis/2026-09-05-backtest-guard-external-audit.md`（本报告不重复其已闭环项）

**总评**：🔴 致命 0 项 · 🟠 高危 2 项 · 🟡 中 4 项 · 🔵 低 2 项（含逻辑项 3 项）

**判语**：

> 「工程上找不到未来函数，也找不到夸大——这一遍所有能量的偏差都指向**保守**那一侧。
> 剩下的两个高危有同一个形状，而且不是上一份报告那个形状：不再是「系统知道但没有仪表说出来」，
> 而是**每一层都被单独量过、每一个数都被写下来了，但没有一次运行把它们放在一起**。
> 引用的那份证据描述的是四层里的第一层。今天这个组合恰好比它好 0.083 个夏普；
> 这是关于今天参数的事实，不是关于流程的性质——同一个缺口藏住 −0.083 会一样称职。」

---

## 第一遍 · 工程审查：问题清单

> 每条定位到 `文件:行`。本轮所有量化结论由 6 个不写 ledger、不写报告的脚本产出，
> 已按本仓库的约定提交进 `scratchpad/`（`.gitignore` 的原话：「scratchpad scripts ARE committed」——
> 而 P11 那次尾部检查正是因为脚本没提交才变得不可复现，`live.demo.yaml:149-156` 记着这一课）：
> `audit20260908_guards_in_validate.py` / `_composed_book.py` / `_live_cost_rescore.py` /
> `_gap_return.py` / `_nw_lag_sensitivity.py` / `_stress_windows.py`。
> **交叉校验**：本报告的 exit overlay 控制行（pit，OOS 1.7737 → 1.8483）与仓库自己 09-07 跑的
> `overlay-20260907T085119Z.json` 逐位一致；tsmom 单独一臂的全样本 1.8204 对引用报告的 1.8177，
> 差 0.0027，来源是本地面板比该报告多 24 根 bar（49,072 对 49,048）。两处对得上，下面的数才有资格被读。

---

### [🟠 高危] 四层构造从未被同一次运行计分过——被引用的证据只描述第一层

**位置**
- `starquant_cli/research_cmd.py:557`（`research validate` 的 `run_backtest`，**无 `guards=`**）
- `starquant_cli/research_cmd.py:362`（16 个 `run_backtest` 调用点里**唯一**传 `guards=` 的一个，在 `research backtest`）
- `starquant_cli/research_cmd.py:1056`（`apply_exits` 的**唯一**调用点，在 `research overlay`）
- `config/alpha_registry.yaml:evidence` → `reports/research/tsmom-validation-20260906T093705Z.json`
  （`book_guards` 字段**不存在**；48 份 validation 报告里带 `book_guards` 的是 **0** 份）
- `config/live.demo.yaml:121-174`（exits `stop_loss 6 / take_profit 6`，**实盘开着**）
- `config/live.demo.yaml:221-222`（`daily_loss_pause -0.05`，**实盘开着**）

**问题**

实盘这本书是四层叠出来的：tsmom 主书 → flow_short 小书（1/3 预算）→ exit overlay → 组合层护栏。
`starquant live run` 启动门校验的那份 `evidence`，是 `research validate` 产出的，而 `validate`
**既不重放护栏、也不施加 exit overlay、也不含小书**。每一层都有自己的报告，各自在不同时点、
不同构造下测过；没有任何一条命令把它们叠起来跑一次。

已测（本轮，pit universe，205 币，49,072 bar，7 bps + 实际资金费）：

| 组合 | 全样本 Sharpe | 走前 OOS | NW t | OOS MDD | 换手 |
|---|---|---|---|---|---|
| A 主书+小书，无 exit overlay 无护栏（= overlay 报告的基线） | 1.8248 | 1.7737 | 4.036 | −25.34% | 428.5 |
| B A + exit overlay | 1.9160 | 1.8483 | 4.146 | −24.21% | 471.6 |
| C A + 护栏 | 1.8280 | 1.7757 | 4.042 | −25.27% | 429.6 |
| **D A + exit overlay + 护栏（≈ 循环持有的那本书）** | **1.9183** | **1.8492** | **4.149** | **−24.21%** | **472.9** |
| 引用证据 093705Z（tsmom 单独，三层都没有） | 1.8177 | 1.7662 | 4.05 | −23.68% | 375 |

护栏在 D 里确实咬得动：`gross_capped_bars 412`、`daily_loss_pause_bars 51`。
exit overlay 在 5.6 年里触发 **561 次**（TAKE_PROFIT 541 / STOP_LOSS 20），换手 +10.3%。

**※ 作者已披露**：`docs/analysis/2026-09-05-system-quality-deep-analysis.md:191` 的 F5 已写下
「validate/book 不重放 guards、不施加 exits，实盘两者都跑」。按规则严重度不降级，
但重点转向披露通常盖不住的两处，这两处都成立：

1. **披露的量级已经过期，而且在 pit 上变了号。** F5 把影响量化为「guards +0.005、stop −0.009」。
   `−0.009` 来自 P11 的 `overlay-20260904T063333Z`，那份报告的 `portfolio.vol_target` 是 **0.15**
   （已核对报告字段）；P13 把它改成 0.30 是同一天 14:53Z，在那之后。按今天的构造重测，
   同一个 exit overlay 是 **pit +0.0746 / static −0.0551**（`overlay-20260907T085119Z/085209Z` 的控制行，
   本报告复算一致）。也就是说披露里那个数差了一个数量级，且在 pit 上符号是反的。
   仓库自己对 `drawdown_throttle` 下过完全相同的判断（`live.demo.yaml:185-190`：
   「calibrated at `vol_target 0.15` and their meaning moved」），对 P10 的带也下过
   （`live.demo.yaml:124-126`）——唯独**开着**的这一层没有得到同样的处理。
2. **两两之差被记过，联合从未被记过。** F5 说的是每层单独的影响；D 行是第一次把四层放在一起。

**方向**：+0.083 OOS Sharpe，**朝有利一侧**。引用的数是保守的，不是虚高的。
但这句话的有效期只到下一次改构造为止——同一个缺口对 −0.083 会一样称职。

**修复**：让 `research validate` 接受 `--guards/--no-guards` 与 exits（复用 `:354` 已有的
`BookGuardParams` 构造与 `:1053` 已有的 `ExitParams.from_mapping`），并在报告里落
`book_guards` / `exits` 两个字段；`starquant live run` 的启动门顺带比对这两个字段与 profile，
这样「registry 参数一致但构造不一致」这条缝就和 D-024 的构造指纹合成同一道门。

---

### [🟠 高危] 没有任何一份报告按实盘已经显示出来的执行成本重算过

**位置**
- `config/costs.yaml:1-3`（`taker_fee_bps 5.0` + `slippage_bps 2.0` = `turnover_bps 7.0`）
- `starquant_alpha/backtest.py:192`（成本恒为 `turnover * turnover_bps/10000`，与下单量无关）
- `starquant_cli/research_cmd.py:625-641`（`cost_stress` 只按 1×/1.5×/2× 整体缩放 `turnover_bps`）
- `.starquant/live/trades.jsonl`（115 行，全部 FILLED；101 行可定价）

**问题**

`cost_stress` 缩放的是「手续费+滑点」这个合数，而实盘已经把两半分开量过了：手续费是合约常数，
滑点不是。按 `trades.jsonl` 里 101 笔可定价成交复算（`avg_price` 对下单时的参考价）：

```
mean 5.60 bps   median 1.33   名义加权 5.52   sd 18.41   n=101
95% CI [2.01, 9.19]   对 2.0 bps 的 t = 1.96   66.3% 的成交为不利方向
```

（与仓库自己的 E-19 一致：85 笔时 mean +5.0 / 中位 +1.3 / 名义加权 +4.3；本轮多出 16 笔。）

模型假设 2.0 bps。点估计是它的 2.8 倍，CI 下界恰好压在 2.0 上——**n=101 判不了这件事**，
但没有任何一份报告问过「如果滑点真是这个数，这本书还剩多少」。本轮问了：

| 情景 | bps/边 | 全样本 | OOS | NW t | OOS MDD | 成本占毛利 |
|---|---|---|---|---|---|---|
| 现行假设（2.0 滑点，open_to_close） | 7.0 | 1.9183 | **1.8492** | 4.149 | −24.21% | 7.9% |
| 实测滑点 5.5，open_to_close | 10.5 | 1.8300 | 1.7592 | 3.948 | −24.98% | 12.2% |
| **实测滑点 5.5 + close_to_close** | 10.5 | 1.8034 | **1.7299** | 3.880 | −24.93% | 12.3% |
| CI 上界 9.2 + close_to_close | 14.2 | 1.7107 | 1.6355 | 3.669 | −25.75% | 16.9% |
| D-020 的 ×2 压力档（作对照） | 14.0 | 1.7423 | 1.6700 | 3.749 | −25.75% | 16.4% |

**读法**：点估计下代价约 **0.12 个 OOS 夏普**，结论不翻——1.73 仍远在 D-028 的门（1.47@125）之上，
NW t 仍 3.88。CI 上界那一档（1.6355）与现行 ×2 压力档几乎重合，说明**现有压力档的量级是够的**，
缺的不是压力档，是把它对准滑点这一半。

**边界，必须说清楚**：上表用的 5.5 bps 参照的是 `venue.mark_prices`，正是 L1-04（`102bc6e`）
**判定为问错了问题而退休掉**的那个参照。所以这三行是**灵敏度，不是判决**；
新尺子（`decision_close`）目前一条读数都没有，见下面 🟡 那条。

**修复**：`cost_stress` 分离两项——费率固定 5 bps，滑点按 {模型 2.0, 实测点估计, CI 上界} 三档，
把结果写进 validate 报告；同时把「重算」挂在 M-Q08 的读数上，读数一变就重算，
而不是等人想起来。

---

### [🟡 中] `open_to_close` 丢掉的那段收益，对这本书是**不利**的，不是保守的

**位置** `starquant_alpha/backtest.py:1-8, 137-142`（模块 docstring 自称 "conservative"）

**问题**

默认口径 `PnL_{t+1} = w_t × (close_{t+1}/open_{t+1} − 1)`，`close_t → open_{t+1}` 这一段**永远不计**。
docstring 的理由是「symmetrically for strategy and benchmark」，语气是保守。已测（6,096,756 个币-bar）：

```
每 bar 平均 |bar 内对数变动|  78.48 bps
每 bar 平均 |跨 bar 缺口|      1.89 bps   （bar 内的 2.41%）
缺口占全部绝对变动            2.36%
corr(缺口, 随后的 bar 内变动)  −0.0075
```

把这段收回来（改 `close_to_close`）：OOS **1.8492 → 1.8199**，即 −0.029。
而 `close_to_close` 在**入场价**上是更优的（按决策收盘成交，零延迟），
所以纯持有段那部分的不利幅度**比 0.029 还大**。

结论：「保守」这个词对**入场价**成立，对**持有收益**不成立。实盘一根不落地穿过每一个 bar 边界。
量级很小（≈ 0.03 夏普），方向记录备查。

**修复**：不建议改口径（改了就断掉与 2026-08 基线的可比性）。建议在 docstring 里把
「conservative」拆成两句，并把 `close_to_close` 的数一并记在 validate 报告里作对照——
它已经是现成的参数，跑一次不花 ledger。

---

### [🟡 中] 被引用的那份证据里，判定门是已废弃的 E[max]；而仓库自己称为「诚实数」的那个数，今天只剩 0.003 的 headroom

**位置**
- `reports/research/tsmom-validation-20260906T093705Z.json` → `oos_selection.threshold_annual = 1.1446301244780732`
- `starquant_alpha/validation/multiple_testing.py:238-292`（今天用 `max_sharpe_quantile`）
- `starquant_alpha/validation/verdict.py:73-81`（`decide()` 读的是**报告里存的** `threshold_annual`）

**问题**

用报告自己的 `variance = 2.1987e-05` 与 `n_trials = 125` 回代：

```
expected_max_sharpe(125, v) × √8760 = 1.1446301245   ← 与报告存的值到小数点后 10 位一致
max_sharpe_quantile(125, v) × √8760 = 1.4683560059   ← 今天的代码给出的值
```

引入分位数门的提交是 `750e5c6`（2026-09-06 20:57 +0800 = **12:57Z**），
报告生成于 **09:37Z**——晚了 3 小时 20 分。`decide()` 读的是**artefact 里的字段**，
所以今天对这份报告重跑判定，比的仍是 1.1446。而 `750e5c6` 自己的提交标题是
「这道门被一次抛硬币就能越过」，`RESEARCH_LOG:2017` 的表格给出它放进噪声的概率是 **43.5%**。

**※ 作者已披露且已决策**：`RESEARCH_LOG:2037` 明写「registry 里被引用的那份报告早于这次修改、
存的是旧门槛，所以**不用重跑，一次试验额度也没花**：按新规则重算它那一块是 1.468 对 OOS 1.766」。
这个决定本身是对的——1.766 以 0.298 的 headroom 越过修正后的门。

**披露没有盖住的一处，是二阶效应**：registry 自己（`alpha_registry.yaml`，DL-R4 段）指出
真正的走前数是 16 格网格那次的 **1.4852**，并算过它在 N=125 时「clears by 0.003 to 0.017」。
ledger 从那以后又长了。按今天的 ledger 重算：

| 口径 | N | 分位数门 | 1.7662 | 1.4852 |
|---|---|---|---|---|
| 引用报告里存的（E[max]，已废弃） | 125 | 1.1446 | 过 | 过 |
| 同 N，修正后的分位数门 | 125 | 1.4684 | 过 | 过（+0.017） |
| **今天：tsmom 去重后 80 条 + 60 申报** | **140** | **1.4821** | 过 | **过（+0.003）** |
| ledger 里全部 618 个不同配置 | 618 | 1.6527 | 过 | **不过** |

（`trials.jsonl` 现 690 行 / 618 个不同配置：mined 514、tsmom 104、flow 28、meanrev 27、breakout 9。
按 `ledger_scope` 的口径 tsmom 只承担自己那一支，这是**合法的**——见「已排除」。）

**头条数 1.7662 在任何一列都过，这一条不动摇结论。** 它记录的是两件事：
(a) 门的定义变了，artefact 不会跟着变，而 `sha256` 钉子恰恰让这份过期变得**牢固**；
(b) 仓库自己称为「诚实」的那个数，headroom 已经薄到 0.003——比两个同样站得住的零假设 SD 之间的差还薄。

**修复**：给报告加一个 `gate_version`（或直接落 `expected_max_annual` 与 `threshold_annual` 两栏，
函数已经返回了 `expected_max_annual`），并让 `decide()` 在读到旧版本时拒绝判定而不是照旧比较；
「门变了 → 引用它的 registry 条目降级为待重签」应当是启动门的一条，不是一段散文。

---

### [🟡 中] M-Q08 的滑点仪表当前是盲的：0 笔可读，而它是 demo 阶段两条判据之一

**位置**
- `starquant_live/risk_budget.py:161-215`（`slippage_bps`，参照 `decision_close`，不回落 mark）
- `starquant_live/engine.py:637, 686`（`decision_close` 的写入点，`102bc6e`，2026-09-07 13:48Z）
- `reports/daily/2026-09-07.json` → `risk_budget.slippage`：
  `{"enforced": false, "fills": 0, "limit": 4.0, "value": null, "why": "0 fills, needs 30; 86 carry no decision_close"}`
- 实测：`.starquant/live/trades.jsonl` **115 行中带 `decision_close` 的是 0 行**

**问题**

`docs/analysis/2026-09-05-system-quality-deep-analysis.md:503` 把 demo 的成功判据定为
M-Q08（执行保真）与 M-Q09（无人值守存活）。M-Q08 的滑点条款是「≤ 2× 模型」= 4.0 bps。
L1-04 昨天把这把尺子从 venue mark 改成决策 bar 收盘——改得对，理由也写得对
（「诚实的『我量不了这 N 笔』比一个量错对象的精确数字有价值，历史不回填」）。
后果是：**这条判据从昨天 13:48Z 起没有任何读数**，且在积够 30 笔新成交之前不会有。
按当前节奏（130 周期 127 单，且最近两个周期 SKIPPED）大约 1.5–2 天。

同时，旧尺子的最后读数是 5.52 bps（名义加权），是判据 4.0 的 1.38 倍。
新尺子会给出什么数，**没有人知道**——参照价不同，方向也可能不同。

**※ 作者已披露**：`102bc6e` 的提交说明预告了这个空窗；`system-quality:804` 也记了
「`decision_close`（L1-04）本周期无法验证」。

**值得单独记下来的是它的形状，不是它本身。** 这是同一个模式在**四天内的第三次**：

| # | 仪表 | 改动 | 后果 |
|---|---|---|---|
| 1 | M-010 归因窗口 | 构造 digest 定义变了 | 窗口自清零（`181eb1f` / `e552f48`，从 1 根 bar 还原到 77 根） |
| 2 | D-028 选择门 | E[max] → 分位数（`750e5c6`） | 引用的 artefact 停在旧门上 |
| 3 | M-Q08 滑点 | 参照 mark → `decision_close`（`102bc6e`） | 判据窗口清零，散文继续引 +4.3 bps |

三次都不是错误——每次改动本身都是对的。但**「改尺子会清零它自己的历史」目前没有任何一处
被当作一类风险来处理**：没有 `instrument_version`、没有「读数不可用」进 `reasons`、
没有一处把「这个数是哪把尺子量的」写进它旁边。

**修复**：给每个判据加一个 `ruler_version` 与 `measured_under`，并让 `report daily --check` 在
判据不可读时把它列进 `reasons`（现在是 `"reasons": []` 加 `"status": "OK"`——
一条量不了的判据和一条通过的判据在日报里长得一模一样，正是 RESEARCH_LOG:1280 那句话）。

---

### [🟡 中] 夏普没有无风险利率口径，且未披露

**位置** `starquant_alpha/validation/metrics.py:24-33`（`sharpe` 的分子是 `np.mean(values)`）
全仓库 `risk_free` / `rf_rate` / `excess`（收益口径意义上）命中 = 0。

**问题**：分子未减无风险利率，且这个约定没有写在任何地方。这本书是 USDT 保证金的永续书，
权益全额押在交易所做保证金，机会成本是真实的。以 30% 年化波动、4% 无风险计，
口径差异约 0.13 个夏普——比本报告里几处 0.03–0.08 的项都大。

**修复**：不建议改数（改了同样断可比性）。建议在 `metrics.py` 的 docstring 里
写一句「分子为原始收益，无风险利率约定为 0，理由是 …」——把一个隐含约定变成一个显式约定。
需要的话另出一栏 `sharpe_excess` 作对照。

---

### [🔵 低] 时点 universe 的合格性过滤用的是**今天**的交易所规则

**位置** `starquant_cli/data_cmd.py:261-271`
```python
eligible = {s for s in candidates if s not in rules or (
    rules[s].contract_type == "PERPETUAL" and rules[s].quote_asset == config.quote_asset
    and (float(rules[s].min_notional) <= config.max_min_notional_usdt or s in pins))}
```
`rules` 来自当次 `exchange_info()`。已退市的币走 `s not in rules` 无条件通过——
**幸存者偏差本身是处理干净的**（`candidates = listed | archived`，`:238-240`）。
残留的是：仍在架的币若近期被上调 `min_notional` 或改过 `contract_type`，
会被**整段历史**排除。变动罕见，方向不定。记录备查，不建议改动。

### [🔵 低 · 2026-09-08 已撤回] 重启后实盘的退出锚点从「首次入场收盘」跳到「持仓 VWAP」

**撤回理由（复查于同日）**：本条的前提不成立，撤回而不是删除，因为前提错在哪里本身是有用的。

`starquant_live/exits.py:96-107` 的 `_reconcile` 只在 `state.direction != held` 或
`entry_price/unit` 为 NaN 时才采用币安的持仓 VWAP。而 `exit_states` 是**持久化**的
（`starquant_live/state.py:27` → `.starquant/live/state.json`），实测该文件当前为全部 18 个标的
保存着真实的 `entry_price`（例：`1000PEPEUSDT` direction −1 / entry_price 0.0036163 /
extreme 0.003562 / unit 0.0488）。所以普通重启**不会**换锚——锚只在状态确实缺失
（全新 `state_dir`、状态丢失）或方向在停机期间变了时才来自 VWAP，而这两种情况下
VWAP 是唯一可得的信息，采用它是正确的。

原判断只读了 `_reconcile` 一个函数就下了结论，没有核对状态是否跨重启存活——
正是本报告第一遍铁律要防的那种「命中即判决」。**不修，记录备查。**

---

## 已排除（命中可疑模式，读上下文后判为合法用法）

这一节是本报告可信度的证明：命中而被排除的项越具体，清单越可信。

- ✓ `starquant_alpha/validation/labels.py:12,19` `shift(-horizon)` —— 显式标签构造，只供
  `research_cmd.py` 的 IC 诊断消费；CPCV / walk-forward 走的是**净收益序列**，不存在标签跨边界。
- ✓ `starquant_cli/research_cmd.py:632` `best_weights.shift(-1)` —— 这是 `run_backtest` 内
  `decided.shift(1)` 的**逆运算**（把执行 bar 上的权重搬回决策 bar，再交给下一次 `run_backtest`
  重新前移）。逐位可验：`executed.shift(-1)[t] = executed[t+1] = decided[t]`。不是未来函数。
- ✓ `starquant_alpha/panel.py:55-73` `align_funding_to_bars` —— `floor` 到 bar 网格、同 bar 相加。
  D-034 修的正是「按等值匹配丢掉 43.7%」，方向是**补上**成本不是减少。
- ✓ `starquant_data/pool.py:126,130` `quote_volume.loc[: date - 1ns]` —— 严格早于换仓日；
  `membership_at_bars:152` 用 `ffill` 不是 `bfill`；`tenure_mask:165` 用 `cumsum` 逐行因果。
- ✓ 全仓库 `bfill` / `backfill` / `.interpolate(` / `center=True` / `fit_transform` /
  `train_test_split` / `KFold` / `shuffle` 命中 = **0**（唯一的 `backfill` 是
  `risk_budget.py:171` 的一句英文注释）。
- ✓ `starquant_alpha/features.py` 全部原语因果：`donchian:81` 用 `high.shift(1).rolling`、
  `volume_ratio:157` 分母用 `shift(1)`、`zscore/robust_zscore` 均 `min_periods=window`、
  `rolling` 全部默认 `center=False`。
- ✓ `starquant_alpha/portfolio.py:50-64` `ewma_portfolio_vol` —— EWMA 递推在 t 处只吃到 `r[t]`，
  而 `r[t] = close_t/close_{t-1}−1` 在 t 收盘时已知；`w[t]` 是同一时刻的决策。因果。
- ✓ `starquant_alpha/panel.py:46-47` 年化因子 `365×86400/interval_seconds`，crypto 7×24，
  由 bar 间隔推导而非硬编码 252/365。`metrics.compound/max_drawdown` 均几何复利。
- ✓ `starquant_alpha/overlays/exits.py:1-16` exit overlay**只在收盘评估、从不用 bar 内 high/low**——
  这是本清单 ③ 类「用 bar 内极值当成交价」的**反面**，且实盘走同一个 `exit_step`，两边不会漂。
- ✓ `starquant_alpha/validation/walk_forward.py:43-75` —— purge 实现正确；`:55-58` 论证了
  walk-forward 里 embargo 无效（训练窗永在测试块之前），是论证不是遗漏。
  **本轮新查的「标签 horizon 跨切分边界」在此判合法**：这条流水线不训练监督模型，
  每个参数集全样本回测一次、 fold 只切净收益序列，不存在训练块尾部的标签。
- ✓ `starquant_alpha/validation/ledger.py:137-146` `ledger_scope` —— `mined_<hash>` 同时从自己和
  `MINED_SEARCH_STRATEGY` 取记录，所以一个候选**承担找到它的那 514 次搜索**。
  ledger 里那 7 行 `mined_<hash>` 因此不是漏洞，DL-K2 已闭。
- ✓ **Newey-West 的滞后阶数：查过，不是缺陷，方向与直觉相反。** 自动规则给 15 个滞后（0.6 天），
  而平均持仓 **376 根 bar（15.6 天）**——看上去严重不足。实测把带宽推出去，t 反而**上升**：

  | 滞后 | 0 | 15（现行） | 168 | 720 | 1440 | 2160 |
  |---|---|---|---|---|---|---|
  | OOS t | 4.013 | 4.063 | 3.997 | 4.619 | 5.212 | 5.567 |

  自协方差的 Bartlett 加权和是净负的（ACF：lag 1 −0.0035、lag 24 −0.0211），
  所以现行取法是**保守**的。附带一个可复用的事实：t(lag=0) = 4.013 ≈ Sharpe × √年数 =
  1.7692 × √5.14 = 4.01，HAC 修正只动了 **1.2%**——即 D-020 的两条 PASS 条件在代数上是同一条。
  这一点仓库自己已披露（`RESEARCH_LOG:344`，`multiple_testing.py:245`），本轮给出了它的大小。
- ✓ `starquant_data/binance_public.py:51-55` `drop_unclosed` + `starquant_live/scheduler.py:21-31`
  `last_closed_bar_open_ms` / `wait_for_bar_close(grace 5s)` —— 未收盘 K 线从不入账；
  实测 `trades.jsonl` 的 `late_seconds` 中位 13.3s、最大 19.4s。
- ✓ `starquant_alpha/backtest.py:284-289` `benchmark_returns` 自我标注 "zero-cost comparator,
  not investable"；`ParticipationModel:53` 自我标注 "measured but never applied"。
- ✓ 115 笔实盘委托全部 `FILLED` —— 市价单，不存在限价挂单成交概率的建模缺口。

### 超出本清单、值得记录的良好实践

- `starquant_alpha/validation/multiple_testing.py` 比本 skill ② 类要求的整整高一层：
  BH-FDR、Holm、DSR、CSCV-PBO 之外，`max_sharpe_quantile:182` 用的是零假设最大值的**分位数**
  而不是**期望**（并在 docstring 里说明了为什么后者「a gate set there admits noise at about one half」）；
  `effective_trials:196` 算了 Li-Ji 有效试验数却**明确拒绝把它代进门里**，理由是那会**降低**门槛
  ——「Lowering a bar on an estimator that has never been validated against this ledger is the
  failure this round exists to prevent」。主动拒绝一个对自己有利的修正，这在审计里很少见。
- `starquant_alpha/backtest.py:118-125` —— 上一份报告要的 `min_margin_buffer` /
  `liquidation_touches` 已经落地并进了 `summary()`。本轮实测：`min_margin_buffer 99.10`，
  `liquidation_touches 0`。
- `starquant_live/engine.py:89-112` `breaker_stop` —— 只有在**告警确实被某个通道收下**时才干净退出；
  没人收就让原异常抛出去让 launchd 反复重启并留下噪声。「干净退出必须挣来」是个好设计。
- `starquant_live/risk_budget.py:176-181` —— 缺参照的成交**跳过并计数**，不回落到旧参照。
  一个报 `null` 的仪表比一个量错对象的精确数字诚实，这个取舍做对了。

---

## 偏差影响（方向判断，非收益预测）

无致命项，无未来函数，无幸存者偏差，无口径级的虚高。**本轮所有能定量的偏差都指向保守一侧**：

| 项 | OOS Sharpe 方向 | 幅度 |
|---|---|---|
| 引用证据缺三层（小书 / exit overlay / 护栏） | 低估 | −0.083（1.7662 对 1.8492） |
| `open_to_close` 丢弃跨 bar 缺口 | 高估 | +0.029（比 `close_to_close`） |
| 滑点模型 2.0 bps 对旧尺子实测 5.5 | 高估 | +0.090（点估计，见边界说明） |
| 无风险利率记为 0 | 高估 | ≈ +0.13（4% rf / 30% 波动） |

四项叠加后仍在 **1.6–1.7** 量级，仍越过 D-028 在任何试验口径下的门（最严 618 试验 → 1.6527），
NW t 仍 ≥ 3.7。**当前 OOS 指标可以继续作为讨论基础。**
具体幅度需按上面「修复」跑一次正式运行确认；本报告的数字全部不写 ledger，不构成证据。

---

## 第二遍 · 逻辑对抗审查（非代码证据）

> 本段结论来自对策略经济逻辑的质询，**不定位 文件:行**。
> 未获作者答复的项标「待作者答复」，不代入假设。

上一份报告的两条逻辑项（Ⅰ edge 归属、Ⅱ 容量）**已闭环**：
edge 陈述写进了 `signals/tsmom.py:1-38`（吃的是散户消化过慢的趋势风险，对手盘是后知后觉的杠杆多头，
**行为性而非结构性**，并附了 carry 的否证与 crowding 的逐 fold 表），
容量曲线由 `ParticipationModel` 测出（拐点在 10 万–100 万 USDT 之间）。本轮不重复。

### [🟠 高危·逻辑] 实盘 52% 的权益是非 USDT 抵押品，而每一个权重都是这个权益的分数

**维度**：Ⅲ.2 单一事件 / Ⅳ.3 集中度

**依据**（可核对，非代码缺陷）：
- `reports/daily/2026-09-07.json` → `collateral`：
  `{"collateral": 5695.77, "equity": 10887.72, "share": 0.5232, "usdt_equity": 5191.95}`
- `config/live.demo.yaml:10-16` 自述：`multi_assets_margin: true`，且
  「equity that floats with collateral prices is a different book from the one the backtest
  describes, and **the backtest models no collateral at all**」
- `starquant_alpha/portfolio.py:82-89`：`stage1 = target × vol_target / asset_vol`，权重是权益的分数；
  `starquant_live/engine.py:530-534`：throttle 除以 `snapshot.equity`，而 vol sizing 的权重本身就是它的分数
- `.starquant/live/cycles.jsonl`：`collateral` 字段只有 **2 个周期**有值（L1-10 是新加的）

**失效场景**（可证伪，条件式）：若 BTC 在一天内下跌 25%，则 (a) 这本书按构造是净多头
（09-07 周期 18 个目标里 14 个为正，gross/equity 0.577），书本身亏；
(b) 同一事件把 52% 的权益抵押品同步减记；(c) 权重是权益的分数，分母缩小使**已有仓位的实际权重被动放大**；
(d) 下一周期的 vol targeting 在缩小的权益上重算，向下再调一次仓，在最差的时点交易。
四步是同一个事件的四个后果，而回测的权益路径里**只有 (a)**。

**已排除的更坏解释**：不是保证金不足。实测 `margin_usage` 峰值 0.119（预算 0.5），
`min_liq_distance` 最近读数 271.6 个日波动单位、18 个持仓里 14 个根本没有可达强平价。
**这不是一个爆仓风险，是一个「回测的权益和实盘的权益不是同一个量」的口径风险。**

**为什么现有仪表看不见它**：`min_margin_buffer` 是在**无抵押品**的权益上算的，
而且它的下界由构造给定——`1/(max_gross × maintenance_margin_rate) = 1/(2.0 × 0.005) = 100`，
实测 99.10。也就是说这个仪表的答案是 `max_gross` 和 `mmr` 两个常数决定的，
**几乎与这本书的行为无关**；它能回答上一份报告问的那个问题，但它回答不了这一个。
（另注：`backtest.py:151` 的 `maintenance_margin_rate=0.005` 是常数，
币安的维持保证金率是按名义分档的，且多资产抵押有折扣率。）

**缓解**：
1. 把 `collateral.share` 补进日报的判据行（现在只在 `cycles.jsonl` 里躺着，2 个周期）；
2. 在回测里加一个**纯口径**的情景：把权益路径乘以一条 BTC 抵押品路径（`share × BTC 收益`），
   只看 vol targeting 与 throttle 的反馈，不动 book——这是把一段论证变成一个可回归的量，
   成本极低，与 P13 当初处理护栏的做法同形；
3. 或者，把抵押品份额降到接近 0（把 demo 账户换成纯 USDT），让回测和实盘描述同一个量。
   哪一条是操作者对实盘配置的决定，不在审计范围内。

### [🟡 中·逻辑] 2020-03 不在样本里；其余五段压力期已回放且**全部为正或接近零**

**维度**：Ⅲ.3 历史压力期

**依据**：1h 存档最早到 **2021-01-01**，扣掉 720 根 bar 的 `min_history` 与信号预热后，
被计分的第一根决策 bar 是 **2021-01-31 01:00Z**。所以
**2020-03 COVID 崩盘不在样本内**——那是加密史上最深的一次流动性抽干，
也是趋势跟随最典型的「缺口穿过止损、成交回不来」情景。本轮实测其余五段（含基准对照）：

| 窗口 | bar | 净收益 | Sharpe | 期内最大回撤 | 等权多头基准 |
|---|---|---|---|---|---|
| 2020-03 COVID 崩盘 | — | **不在样本** | — | — | — |
| 2021-05 杠杆挤兑 | 528 | +6.77% | 2.62 | −7.50% | −37.78% |
| 2022-05 LUNA/UST | 480 | **+23.25%** | 7.89 | −5.35% | −42.49% |
| 2022-06 3AC/Celsius | 600 | +3.88% | 1.56 | −10.86% | −17.47% |
| 2022-11 FTX | 480 | **−3.32%** | −1.58 | −6.51% | −30.43% |
| 2024-08 日元套息平仓 | 336 | +9.87% | 7.40 | −5.93% | −15.04% |

五段里四段为正、一段小负，且每一段都远好于基准。这是趋势跟随的**危机 alpha** 形状，
与 `signals/tsmom.py` 里那句 edge 陈述一致（对手盘是被迫出场的杠杆多头，崩盘正是他们被迫出场的时候）。
**这一项不是警告，是一次通过的检验**；记录下来的是那一个空白格。

**失效场景**：若出现一次 2020-03 形态的事件——所有资产同时被抛、交易所撮合与 API 同时降级——
则本书的三层保护（`daily_loss_pause` 只在下一个周期生效、`max_participation` 在流动性抽干时
把可执行量按同一条 volume 曲线一起压缩、 exit overlay 只在收盘评估）**都是逐 bar 的**，
而那类事件的时间尺度是分钟。回测无法回答这段，因为数据不存在。

**缓解**：不建议为此补数据（2020 的永续合约品种与今天的 universe 几乎不重叠，补了也不可比）。
建议把这句写进 registry 的 edge 段：**「本书的压力检验覆盖 2021-05 起的五段，不覆盖 2020-03」**，
让它是一个已声明的空白而不是一个未被问过的问题。

### [🟡 中·逻辑] 容量曲线是在 exit overlay 上线之前测的，而 exit overlay 把换手抬高了 10%

**维度**：Ⅱ.2 / Ⅱ.3 容量

**依据**：上一份报告的参与率表（1,000 / 1万 / 10万 / 100万 / 1000万 USDT）跑的是
`tsmom` 单独一臂、换手 225.6。今天这本书含小书与 exit overlay，实测换手 **472.9**——
是当时的 **2.1 倍**（其中 P13 的 vol_target 0.15→0.30 贡献大部分，exit overlay 贡献 +10.3%）。
参与率上限绑定的份额随目标换手近似线性上升，所以那张表的拐点（10 万–100 万之间）
今天应当更靠左，可能靠左一倍。

**这不是「表算错了」**——表是对它当时那本书算对的。是**它描述的书已经不在了**，
和上面 F5 那条 exit overlay 的情况是同一个形状。

**缓解**：用今天的构造（四层）重跑一次 `ParticipationModel` 的资金阶梯（不写 ledger，
`backtest.py:51-83` 的接口现成），并把 `live.demo.yaml:45` 那句
「k must be re-derived under an impact-aware cost model」的**触发点**从散文改成一个数字
（上一份报告建议 10 万 USDT 量级；按今天的换手大概要下调）。

### [✓ 已答，不再列为质询] Ⅳ.1 是不是伪装的卖波动率

**依据**（本轮实测，shipped 构造的净收益序列）：

| | n | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 | **偏度** | 峰度 | 最差 | 最好 |
|---|---|---|---|---|---|---|---|---|---|
| 小时 | 49,072 | 0.510 | +0.242% | −0.237% | 1.02 | **+1.08** | 27.2 | −4.40% | +7.74% |
| 日 | 2,045 | 0.531 | +1.387% | −1.193% | 1.16 | **+0.83** | 7.0 | −6.22% | +11.53% |

卖波动率的特征是「高胜率 + 小赢多次 + 偶尔巨亏 + **左**偏」。这里胜率 51/53%（不是 85%）、
盈亏比 1.02/1.16（不是 0.3）、偏度 **+1.08/+0.83**（**右**偏）。**假设被测量否证，不是被论证否证。**
最差 UTC 日 −6.22%（2022-05-04），越过 −5% 的 `daily_loss_pause`，护栏重放里共触发 51 根 bar。

### [🔵 低·逻辑] flow_short 小书与主书 91% 同向——已披露、已定为 REJECT、以 P&L 止损为控制

**维度**：Ⅳ.4 组合内相关

`alpha_registry.yaml` 的 flow 段已完整写下：组合层判定 REJECT、小书自身 FAIL/WEAK_PASS 之间反复、
91% 的仓位压在 tsmom 已经做空的名字上、P1-01 修正后表面 +0.126 的边际里约 0.048 是假象。
控制是 `probe.stop`（30 天归因 P&L ≤ −2% 权益自动关书），最近读数
`{"pnl": 2.71, "pnl_pct": 0.00025, "status": "OK"}`。**这一项披露得比多数系统的主书还完整**，
不再作为质询列出。

---

## 风险评级：🟡 中

**理由**：无致命工程项，无未来函数，五段压力期已回放且四正一负，Ⅳ.1 的卖波动率假设被实测否证，
Ⅴ 类（监控 / 熔断 / 对账 / 断线）在代码里逐条可指。
评为中而非低的唯一原因是那两条高危共有的形状——**四层构造与实测执行成本都没有被同一次运行计过分**，
以及「改尺子清零它自己的历史」在四天内出现了三次而尚未被当作一类风险处理。
两条都不阻断当前的 demo/testnet 运行；`live.demo.yaml` 与 `system-quality` 里
「真实资金 HOLD 且 DEFERRED」的判断，本报告完全同意。

## 上实盘资金前，作者必须回答的三个问题

1. **循环持有的那本书（四层）的 OOS 数是多少，出自哪一份 artefact？**
   今天的答案是 1.8492，出自会话 scratchpad 里一个不写 ledger 的脚本——不是证据。
   在这个数有一份带 sha256 的报告之前，启动门校验的是第一层。
2. **M-Q08 的新尺子会读出多少？** 旧尺子最后读 5.52 bps（判据 4.0）。
   新尺子从昨天 13:48Z 起 0 笔读数。在它积够 30 笔之前，demo 阶段两条判据之一没有读数，
   而日报显示 `status: OK`。
3. **回测的权益和实盘的权益是不是同一个量？** 今天不是：52% 是非 USDT 抵押品，
   而每一个权重都是这个权益的分数，回测建模的抵押品是零。

## 建议优先级

1. **让 `validate` 能描述循环持有的那本书**（`--guards` / `--exits`，报告落 `book_guards` / `exits`
   两个字段，启动门一并比对）——这一条同时关掉两条高危里的第一条，也让 F5 的过期数字不必靠人记得更新。
2. **把 `cost_stress` 的滑点一半拆出来**，按 {模型 / 实测 / CI 上界} 三档，并挂在 M-Q08 的读数上。
3. **给判据加 `ruler_version` + 让不可读的判据进 `reasons`**——这一条治的是那三次清零的共同病因，
   成本最低，收益最长。
4. 抵押品份额进日报判据行；用今天的构造重跑一次参与率资金阶梯。
5. 补两句 docstring：`sharpe` 的无风险利率约定；`backtest` 的 "conservative" 拆成入场与持有两句。

**第一遍两条高危关闭之前，不建议把这份 OOS 数字当作「循环会拿到的分数」引用给任何决策。**
demo/testnet 运行本身不受影响。

---

## 重要免责

本报告是**审查**，对回测与策略代码的**工程可信度**与策略**逻辑自洽性**做尽职调查，
目的是防自欺，不是评估盈利能力。

- **不构成投资建议**，不预测收益、不荐股、不给买卖点或仓位建议。
- 「偏差影响」与「失效场景」只给**方向与条件**，不承诺、不量化任何具体收益或亏损数字；
  其中引用的历史事件仅作情景参照，不代表会重演。
- 通过审查 ≠ 策略能赚钱；只代表未发现本清单覆盖的工程陷阱。
- 本报告的一切数字由 `scratchpad/audit20260908_*.py` 产出，这些脚本不写 ledger、不写报告，
  因此**不是证据，不进 registry**。
  要成为证据，必须按上面「建议优先级」跑一次正式运行并计入 trials ledger。
- 实盘滑点样本 n=101、来自 **demo/testnet**、跨 4.5 天，且参照价是已被 L1-04 退休的那一个；
  它是灵敏度的输入，不是主网的测量。
- 第二遍质询的目的是逼出尚未回答的问题，不是替作者给出结论；
  「待作者答复」既不等于有问题，也不等于没问题。
- 一切实盘交易决策与资金风险由使用者自行承担。

---

## 修复记录（2026-09-08，同日）

操作者要求「修复报告里的所有问题」。全部按 TDD 走：先写失败测试、看它以正确的理由红、
再写最小实现。`ruff format --check` / `ruff check` / `mypy` / `pytest -m "not network"` 全绿，
全套 838 条通过、48.9s（上限 120s）。新增测试 7 个文件、34 条。

**核对过的一件事**：启动门加的是**比对**，不是**拒绝**。当前被引用的两份证据都早于新字段，
按 `construction_problems` 一贯的「早于字段则跳过」约定被跳过，实测
`registry_evidence_problems(registry, profile)` 返回空——**正在跑的循环不受影响**，
门从下一次重跑证据起自动生效。

| 项 | 处置 | 落点 |
|---|---|---|
| 🟠 四层从未合并计分 | **已修**：`research validate` 新增 `--guards/--no-guards`、`--exits/--no-exits`（默认开），报告落 `book_guards` / `exits` 两个块，`full_sample.guards` 带上 `min_margin_buffer` 与 `liquidation_touches`；`--no-guards --no-exits` 复现旧报告 | `research_cmd.py`、`tests/cli/test_validate_scores_the_book_the_loop_holds.py` |
| ↳ 启动门 | **已修**：`construction_problems` 增加 `live_overlays`，逐键比对两个块；`null`（本次没跑这层）与「没有这个键」（早于字段）被区分对待；`live_overlay_blocks` 从 profile 供给实盘侧 | `registry.py`、`config.py`、`tests/alpha/test_overlay_gate.py`、`tests/live/test_overlay_gate_is_wired_to_the_profile.py` |
| ↳ ledger | **已修**：validate 的 `TrialRecord` 补 `overlay_digest`，同参数不同 overlay 栈是两次试验而不是一次重放；`current_context` 的 overlay 槽位从硬编码 `""` 改为真实摘要（否则排除集匹配不到自己写的行，会重复计费） | `research_cmd.py` |
| 🟠 未按实测执行成本重算 | **已修**：新增 `slippage_stress`（费率固定、只动滑点），档位与出处写进 `config/costs.yaml` 的 `slippage_stress_bps: [2.0, 5.5, 9.2]`。`cost_stress` **一行未动**——`verdict.decide` 读它的 `x2`，改它的含义等于不动阈值地移动一道门 | `stability.py`、`costs.yaml`、`tests/alpha/test_slippage_stress_holds_the_fee_fixed.py` |
| 🟡 `open_to_close` 的缺口 | **已修（口径不动，说明补上）**：docstring 把「conservative」拆成入场价（成立）与持有收益（不成立），带上实测的 2.36% 与 −0.029；validate 报告新增 `execution_comparison`，把另一口径作为对照一起记 | `backtest.py`、`research_cmd.py`、`tests/alpha/test_conventions_are_stated.py` |
| 🟡 门的身份不随数走 | **已修**：`oos_selection` 落 `gate` 字段；`decide` 对叫不出名字的门拒绝判定（与既有的 `oos_t_stat` 完整性拒绝同形）。归档回归测试改为「补上门名后判定必须复现」，并新增一条把本次发现钉成回归：**每一份归档报告在原样判定下都因门被拒**。这样那道 pre-registered 保证不会退化成空断言 | `multiple_testing.py`、`verdict.py`、`tests/alpha/test_gate_identity_travels_with_the_report.py` |
| 🟡 M-Q08 仪表失明 | **已修**：`risk_budget_status` 新增 `unreadable` 列表与第三种状态 `BLIND`——量不出来的判据不再报 OK。**不改告警路由**：它会随成交自愈，正是 `daily_alerts` 写来挡在寻呼路径外的「不可行动的常态事实」，所以走 notice | `risk_budget.py`、`reports.py`、`tests/live/test_unreadable_criteria_are_not_ok.py` |
| 🟡 夏普无无风险利率口径 | **已修（数不动，约定写下）**：`sharpe` docstring 声明分子是原始收益、无风险利率约定为 0，并写明为什么不动（动了要给所有归档报告与 `verdict.py` 的阈值重新定价） | `metrics.py` |
| 🟠·逻辑 抵押品 | **已修（报告口径）**：`drawdown_state` 输出 `collateral_share`，放在**阶梯读数旁边**而不是日报另一处——L1-10 量了也印了，只是印在离「除以同一个权益」的阶梯四个块之外。分母**不动**：那是构造决策，不是 bug 修复（沿用 L1-10 自己的裁定） | `risk_budget.py` |
| 🟡·逻辑 2020-03 不在样本 | **已修（声明而非填补）**：registry 的 tsmom 段写下压力覆盖——2021-05 / 2022-05 / 2022-06 / 2022-11 / 2024-08 五段（四正一负，均远好于基准），**不含 2020-03**，并说明为什么这个空格重要（三层保护都是逐 bar 的，而那类事件的尺度是分钟）。同时写下右偏 +1.08/+0.83 的实测，把「伪装的卖波动率」钉为已否证 | `alpha_registry.yaml` |
| 🟡·逻辑 容量曲线过期 | **已修**：`scratchpad/participation_capacity_sweep.py` 改为按 registry + 小书 + exit overlay 构建，重跑得 **10万 5.41% / 100万 33.07%**（旧读数 4.25% / 28.60%，绑定 bar 数约翻倍）；`live.demo.yaml` 把「k 需在冲击模型下重推」的触发点从一句话改成 **10 万 USDT** 这个数字 | `live.demo.yaml`、scratchpad |
| 🟡 exit overlay 证据停在 0.15 | **已修（数不动，纠正写下）**：`live.demo.yaml` 的 exits 段补上 P13 之后的重测——pit **+0.0746** / static **−0.0551**（旧记录 −0.0092 / −0.0892，差一个数量级且 pit 上反号）。D-017 的规则仍然成立，所以设置不变，但「免费」是 0.15 时代的说法 | `live.demo.yaml` |
| 🔵 universe 用今日交易所规则 | **已修（记录，不改行为）**：`data_cmd.py` 写下这处残余前视的边界——已退市标的无条件通过（幸存者偏差是干净的），仍在架标的按今日 `contract_type` / `min_notional` 过滤整段历史；没有时点 exchangeInfo 存档可修 | `data_cmd.py` |
| 🔵 重启后退出锚点 | **已撤回**：前提不成立，见上文该条 | — |

**行数闸门**：alpha +99 / live +60 / cli +103，`tests/architecture/test_source_budget.py` 的
`CEILING` 在同一次改动里抬高并写下理由。闸门三个包全抓到了，这是它在正常工作——这些行一行都没预算过。

**没做的事，明写。**
`research book` 与 `research overlay` **没有**加 guards/exits：overlay 的整个作用就是拿基线比叠加，
在它上面预先叠一层是循环论证；book 命令值得同样处理，但那是另一次改动，且 flow 的 book 报告
在启动门里因此仍走「早于字段则跳过」。**当前 registry 引用的两份证据都没有重跑**——
重跑要花试验额度、要写 ledger，是操作者对实盘配置的决定，不在修复范围内。
所以本报告第一条高危的**门已经装上，但还没有一份证据穿过它**。

---

*生成于 2026-09-08，对 main @ `3e5c44d`；修复记录同日追加。尺子是 `vendor/backtest-guard/`（MIT，两个第三方项目的合并版）。*
