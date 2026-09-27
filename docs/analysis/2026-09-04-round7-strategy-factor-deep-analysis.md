# 深度分析：策略与因子模块的有效性复检与重构（第七轮）

> 分析头部（deep-analysis V3.2）
> - Interaction Mode: **Green**。全部关键事实来自代码、数据、可复现的研究运行与实盘状态文件；唯一由操作者决定的事项（tsmom 证据门槛、是否继续实盘）不靠假设，而以选项形式提交。
> - S/M/L: **L**。命中：≥3 模块（`starquant_alpha` 信号/模型/验证、`starquant_cli` 研究工具、`starquant_live` 实盘路径）、24h 自主下单、demo 资金、且本轮发现同一工作树上有三个会话并行修改（§2 E-063）。
> - 当前 Gate 决策上限：**Weak GO**。G6 有一个 OPEN 的 P0 Kill（KILL-037：实盘唯一策略的 registry 证据 p=0.0002 是方差退化的产物，诚实重算后 FAIL），关闭前不得 GO。
> - 外部动作授权：**无**。本轮未下单、未重启实盘、未推送；只追加了 `reports/research/` 的研究报告与 ledger 行（R1、R2 两次 validate，共 18 行），代码改动全部在独立 worktree `~/starquant-round7`（分支 `refactor/alpha-round7`）。
> - 独立性声明（Phase 7）：同一 Agent 执行；§2–§6 先冻结再攻击；反方只引用 E-054 ～ E-066。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **GO（受控）**：操作者按 §6.1 Option B 预登记了 D-020（OOS 优先判定），tsmom 在新规则下重出证据（E-067：OOS 1.54、NW t 3.5、CPCV q05 1.26、成本 2× 1.43 → PASS），registry 参数与报告一致，KILL-037 关闭。实盘继续，但 tsmom 的 edge 仍是 **PARTIAL**（走前/CPCV/PBO 强、选择偏差意义上的显著性弱、实盘 OOS 0 天），M-010 的 30 天 income 归因是最终裁决 |
| 本轮最重要的发现 | **C-019 被证伪**：registry 引用的 tsmom 证据（`133239Z`，DSR p 0.0002）建立在近乎为零的试验方差上（ledger 里只有 5 条几乎相同的配置）。把选出这组参数的 16 点网格在时点 universe 上诚实跑一遍（E-054），走前 OOS 1.48、5/5 fold 选中同一 horizon、CPCV q05 1.09、PBO 0.001、成本 2× 1.35——但 DSR p **0.40**，判定 **FAIL**。实盘配置（拥挤度关）在合并后的 ledger 上 p 0.17～0.25（E-062）。按仓库预登记的规则，当前没有任何一份可引用的 PASS 报告 |
| 第二重要的发现 | 信号-构建分解（E-058）：tsmom 的 edge 在**周级动量的方向**，不在幅度、不在斜率/持续性分量，也不在组合构建单独（常数多头书 Sharpe 0.09、等名义信号 0.43、只取符号 1.68、完整 1.72）。多空两腿弱相关（多头 +66%/Sharpe 0.66，空头 +132%/0.97），书对等权多头基准的相关 −0.18：它不是 crypto beta |
| 预登记假设的裁决 | R2 拥挤度修正：**关闭**（时点走前 OOS 1.53 vs 对照 1.65，CPCV 12/15 路径选对照；E-055）——与 starquant-d6 已写入 registry 的 `crowding_window: 0` 一致。R3 更慢的波动率估计/更宽的带：**全部否定**（换手 −37% 但 OOS Sharpe 1.65 → 1.41～1.49；E-056），P10 关闭 |
| 最大风险 | KILL-037（P0，证据无效）与 KILL-038（P1：registry 参数 ≠ 报告参数，sha 校验查不出来）——后者已在分支上用启动门关闭；三会话并行改同一工作树（KILL-039）已通过 worktree 隔离缓解 |
| 交付 | 分支 `refactor/alpha-round7`（基于 `8bd2ef0`）：`research decompose` 命令与纯函数库、 ledger 去重（精确重放只计一次）、DSR 同时报告 pooled 与 noise-null 两种零假设、validate 报告记录 fold 数/min_train/purge/网格/每配置 Sharpe、registry 参数-报告一致性启动门；测试 +6，全套通过（§9）。实盘路径修正（P1/P3/P4/P8/P8b）由会话 starquant-88 在主树承担，本轮不重复 |
| 操作者必须决定的一件事 | §6 Option A/B/C：如何处理"实盘策略没有 PASS 报告"。在此之前**不重启** `com.starquant.live`（starquant-d6 已按此暂停） |

---

## 1. Phase 1 · Reality Check

输入类型：**执行/审查型 + 愿景型**（"持续盈利能力越高越好"）。剥离愿景后的真实问题：操作者在 demo 上无人值守地跑一个策略，他需要知道 (a) 这个策略的 edge 是否真实、来自哪个因子；(b) 还有哪些**有证据**的杠杆能提高净收益；(c) 实盘跑的东西是否就是被验证的东西。

需求三问：谁承担损失 = 单一操作者（错误的"已验证"信念 → 错误的加仓/扩展决策）；频率 = 每小时周期、每次研究轮次；现有方案能否满足 = 部分：验证工具链完整，但 DSR 的方差输入退化（E-049 已预警、本轮量化），且没有"信号 vs 构建"的归因工具。

Early Kill：无 FATAL。K2 不成立（全部 E1）。K6（价值 < 复杂度）对"加新信号"成立为 WARNING → 沿用 Scope Firewall（P13）。**G0 PASS。**

---

## 2. Phase 2 · Evidence Ledger（全部 E1/E2，日期 2026-09-03 UTC；可复核）

| ID | 类型 | 来源 | 摘要 |
| --- | --- | --- | --- |
| E-054 | EXPERIMENT | `reports/research/tsmom-validation-20260903T174552Z.json`（R1：16 点预登记网格 = `DEFAULT_GRIDS["tsmom"]`，`--universe pit --from 2021-01-01 --prior-trials 27`，146 币，共同索引 2021-03-02 → 2026-09-03，48,275 bars） | 走前 OOS Sharpe **1.48**，各 fold [1.14, 0.74, 1.68, 1.94, 1.94]，5/5 fold 在样本内选中 168/336/720（fold 2 选 entry 0.3），CPCV 1.58 / q05 1.09 / 负比例 0，**PBO 0.0008**，成本 2× 1.35。**DSR p 0.40 → FAIL**：候选（共同索引）1.58，49 次试验、pooled 年化标准差 0.65 → E[max SR] 1.48。16 个配置的全样本 Sharpe：小时级 5/20/50 为 −0.22/−0.10/0.23/0.44，24/72/168 为 0.49～0.54，168/336/720 为 1.58/1.48/1.15/0.93，336/720/1440 为 0.27～0.49 |
| E-055 | EXPERIMENT | `tsmom-validation-20260903T175236Z.json`（R2：`{crowding_penalty: [0, 0.5]}`，其余为 HEAD registry 参数，时点，全索引 48,995 bars）+ scratchpad `oos_compare.py` | 逐 fold 训练集选择 [0.5, 0.0, 0.5, 0.5, 0.0]；但单配置 OOS：penalty 0.5 = **1.53**（fold [1.22, 0.78, 2.04, 1.65, 1.94]）vs 0.0 = **1.65**（[1.47, 0.49, 2.24, 1.71, 2.31]）；CPCV 15 条路径中 12 条选 0.0；全样本 1.64 / MDD −12.6% vs **1.72 / −13.5%**，换手 367 vs 357。预登记规则 R2（≥3/5 fold AND OOS 不低于对照）→ **不保留拥挤度修正**。该配置的 DSR p 0.32（51 试验）→ FAIL |
| E-056 | EXPERIMENT | scratchpad `oos_compare.py`（R3：组合层 4 点预登记网格，不写 ledger，作为申报先验计入后续 validate） | 基线 (vol_halflife 48, cov 96, rel_band 0.25)：OOS 1.65 / OOS MDD −13.5% / 换手 357 / 成本占毛收益 14.6%。B1 (168, 336, 0.25)：1.47 / −15.0% / 302；B2 (168, 336, 0.40)：1.49 / −15.5% / **226 / 10.7%**；B3 (336, 336, 0.40)：1.41 / −15.9% / 228。规则 R3（OOS ≥ 基线 +0.05 且 MDD 恶化 ≤ 1pp 且换手更低）→ **无候选合格**。更慢的波动率估计省下的成本（约 4pp）小于它在波动率骤变时晚缩仓的损失 |
| E-057 | EXPERIMENT | scratchpad `diag/*.log`（R4：8 个 `research diagnose --universe pit` 消融，前瞻 24/72/168/336/720h，score 覆盖率 12% = 时点成员×历史门） | registry 配置横截面 IC：+0.010 / +0.020 / **+0.033 / +0.040 / +0.042**（NW t 2.0 / 2.4 / 2.7 / 2.6 / 1.9）；**时序 IC 全部为负**（−0.12 ～ −0.27）。消融：只留动量分量 IC 几乎不变（0.032/0.038/0.040）；去掉持续性分量 IC 略降、去掉斜率分量无变化（斜率项惰性，与 E-043 一致）；单 horizon：336h 最强（336h 前瞻 IC 0.049，t 3.1），168h 单独在 ≤168h 前瞻不显著，720h 单独最弱（t 1.2～2.1）；拥挤度关闭后 IC 略低（0.029/0.033/0.031）但 P&L 更高（E-055）。信号本身（等名义、零成本）Sharpe 0.31，换手 70 |
| E-058 | EXPERIMENT | `reports/research/decompose-tsmom-20260904T023330Z.json`（`starquant research decompose --strategy tsmom --universe pit --from 2021-01-01`，sha256 `994de580…`；信号 vs 构建分解，时点，实盘等效配置 = 拥挤度关；同一组合层 vol 15% / 单币 15% / gross 2 / 带 0.5%+25%；7 bps + 实际资金费） | **full 1.72**（+317%，MDD −13.5%，换手 357）；**constant_long（全体合格成员 +1，纯构建）0.09**（+1%，MDD −33%，与基准相关 0.91）；**sign_only 1.68**（+315%，**MDD −11.7%，换手 264，成本占比 11.7%**，与 full 相关 0.97）；long_only 0.60（+52%，MDD −32%）；short_only 0.64（+59%，MDD −18%）；eq_notional（信号无构建）0.43（+65%，MDD −36%，换手 642）。full 的两腿：多头 +66%（Sharpe 0.66）、空头 **+132%（0.97）**；多头币-bar 占 45%；full 与等权多头基准相关 **−0.18**。基准（等权多头、零成本）Sharpe 0.58、+94%、MDD **−83%** |
| E-059 | EXPERIMENT | scratchpad DSR 敏感性（候选 = E-054 的 1.58，n_obs 48,275） | 零假设方差 × 试验数 → p：pooled（ledger+网格，年化 std 0.65）：n=16/35/49/60 → 0.17/0.33/0.40/0.45；仅本轮网格（std 0.50）：0.05/0.11/0.15/0.17；单个 Sharpe 估计的抽样噪声（std 0.43，Bailey-LdP）：**0.03/0.06/0.07/0.09**。结论：6 年小时数据的一个年化 Sharpe 估计标准误约 0.43，49 次尝试下零假设的期望最大值约 1.0～1.5，候选 1.58 距其 0.2～1.4 个标准误 |
| E-060 | CODE | `starquant_alpha/validation/ledger.py:53-77`（HEAD）、`reports/research/trials.jsonl` | ledger 不去重：registry 配置在同一数据上重复出现 4 次（0846Z/1258Z/1321Z/133239Z 各一，其中 3 条同 universe 同区间），`validate` 每次运行都把每个网格点追加一行，`book` 却按 (param_key, range_start, range_end, symbols) 去重。当前 tsmom 40 行，签名去重后 37 条（静态 19 / 时点 18） |
| E-061 | CODE | `starquant_alpha/registry.py:96-128`（`8bd2ef0`） | KILL-015 启动门只校验报告存在、sha256 匹配、verdict ∈ {PASS, WEAK_PASS}；**不比较 registry 参数与报告的 `best_params`**。主树 registry 现为 `crowding_window: 0`、引用的 `133239Z` 报告为 `crowding_window: 72 / penalty 0.5`，sha 仍匹配，`starquant live run` 会正常启动（KILL-027 的另一种形态） |
| E-062 | EXPERIMENT | 分支代码在当前 ledger（40 行）上重算实盘配置（拥挤度关、全索引 1.7158，n_obs 48,995，申报先验 27） | 旧算法（全部行计入）：n 68、std 0.60、E[max] 1.43、**p 0.25**；去重后：n 64（3 条重复 + 1 条重放剔除）、std 0.56、E[max] 1.32、**p 0.17**；noise-null：E[max] 1.00、**p 0.05**。两种零假设下结论不同：pooled → FAIL，noise → WEAK_PASS 边缘 |
| E-063 | DATA | `git status`、文件 mtime、`ListAgents`、跨会话消息 | 本会话开始时（15:00Z）工作树干净；15:07Z 起 `starquant_alpha/model.py`、`registry.py`、`portfolio.py`、`starquant_live/*` 被会话 starquant-d6 修改（D-019 probe book），17:45Z 其把 `crowding_window: 0` 写入 registry，17:5xZ 提交 `383ad60`、`8bd2ef0`（**flow 以 probe book `flow_short` 1/3 预算启用**，带 30 天 −1% 权益的停止规则）；会话 starquant-88 在主树未提交地实现第六轮 P1/P3/P4/P8/P8b（warmup 按 registry 参数、TRANSFER 检测、hold 跨周期种子、止盈参考价、归因归一化）并追加了 16 行静态 universe ledger（`175314Z`）。实盘进程仍是 13:37Z 启动的 PID 6182（HEAD `d4e363b`，未受任何未提交改动影响）。操作者已选择：**在本文档出来前不重启** |
| E-064 | CODE+TEST | 分支 `refactor/alpha-round7`（基于 `8bd2ef0`） | `starquant_alpha/validation/decompose.py`（新）、`research decompose`、`ledger.unique_trials/dsr_inputs(current_range=…)`、`multiple_testing.sampling_variance` + 报告字段 `noise_null`、`registry.params_problems`（验证报告用 `best_params`、book 报告用 `sleeve.params`）、validate 报告新增 `grid/folds/min_train/purge/cpcv_groups/prior_trials_declared/trial_sharpes/ledger`。ruff / mypy / 全套 pytest 通过（§9）。用分支代码检查主树 registry：tsmom 报 `parameter crowding_window is 0 in the registry but 72 in …133239Z.json`，flow probe 通过 |
| E-065 | REPORT | `reports/research/tsmom-validation-20260903T175314Z.json`（starquant-88 的静态 15 币 16 网格复现，2021-08-30 起） | 走前 OOS 1.21，各 fold [−0.99, 2.33, 1.01, 1.75, 1.85]，DSR p 0.33，FAIL。第二轮当年在同一网格上的 PASS（p 0.045）不再复现：区间不同（第二轮 2021-07-31 起、min_train 8000）且 ledger 方差已改变。它把"静态 universe 上 tsmom 也过不了 DSR"钉住了 |
| E-068 | EXPERIMENT | `reports/research/tsmom-validation-20260904T020211Z.json`（2 点网格）与 `…T020459Z.json`（`sign` 单配置）；配对检验脚本见会话 scratchpad | H-001 按预登记规则执行。`sign` vs 基线：走前 OOS 1.6026 vs 1.6450（−0.0424，容忍 −0.05）、OOS MDD **−11.75% vs −13.53%**、换手 **263.8 vs 357.4（−26%）**、成本占比 11.69% vs 14.57% → 三条检查全过，**ADOPT**。配对检验才是重点：两条 OOS 净值相关 0.966，**逐 bar 收益差 NW t = −0.047、p = 0.963**，年化收益差 −0.0009；Sharpe 差的周块自助均值 −0.041、5–95% [−0.238, +0.151]。即**幅度不携带收益信息**，Sharpe 的微降在噪声内，且由敞口从 0.383 升到 0.445 解释。副产品：`validate` 的 `best_params` 按全样本 Sharpe 选，因此按规则胜出但全样本略低的候选必须另出单配置报告才能通过 D-024 的参数门；020459Z 的 `ledger` 段显示 `replayed_rows 1`，去重规则首次在真实 ledger 上生效 |
| E-067 | REPORT+EXPERIMENT | `reports/research/tsmom-validation-20260903T181803Z.json`（D-020 后 starquant-a1 重出的 tsmom 证据，registry 现引用）+ 本会话的算术复核 | 网格 {crowding_window: [0, 72]}，时点 146 币，全索引 48,995 bars。走前 OOS **1.5445**（fold [1.22, 0.49, 2.04, 1.65, 2.31]，一致性 1.0），**NW t 3.503**（15 阶滞后，OOS 44,995 bars）；CPCV 1.65 / q05 1.26 / 负比例 0；成本 2× 1.43；DSR p 0.257（69 试验，信息性）→ **PASS**。`best_params` = `crowding_window: 0`，与 registry 参数一致（本分支的参数门通过）。**两处复核发现**：(a) NW t 与 `Sharpe × √年数` 的比值为 **1.001**（3.5027 vs 3.5005）——HAC 修正在小时级净收益上几乎不起作用，所以"OOS Sharpe ≥ 1.0 且 t ≥ 2.0"在 5.14 年窗口上等价于"Sharpe ≥ 1.0"（t ≥ 2.0 只相当于 Sharpe ≥ 0.88），**第二个门在本样本上不约束**，只有当 OOS 窗口短于 4 年时才收紧；(b) 逐 fold 选择为 [72, 0, 72, 72, 0]，所以 1.5445 是**fold 内混合配置**的走前估计，而 registry 实际运行的 `crowding_window: 0` 单配置走前 OOS 是 **1.65**（E-055）——引用的头条数字比实际运行的配置保守 |
| E-066 | DATA | `.starquant/live/*`、`reports/daily/2026-09-03.md` | 实盘至 17:00Z 共 14 个周期、38 笔成交；权益 10,775（含 14:04Z 的 +5000 TRANSFER 重置断点，E-044）；drift 检查 `INSUFFICIENT_DATA`。**实盘 OOS 证据仍为 0 天** |

### 2.1 Claim Register

| ID | 命题 | P | Axiom | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-019 | registry 引用的 tsmom 证据（PASS，DSR p 0.0002）是有效的多重检验结论 | **P0** | A2/A6 | 用选出该参数的网格重算 DSR 时 p > 0.10 | E-054、E-059、E-062、E-065 | **REFUTED** |
| C-020 | 周级 tsmom 在扣费后有真实 edge | P0 | A1/A2 | 走前 OOS < 1 或 CPCV 负比例 > 10% 或 PBO > 0.3；实盘 30 天 income-Sharpe 低于期望 2 s.e. | E-054（OOS 1.48、CPCV q05 1.09、PBO 0.001）、E-058（不是 beta）、E-057（IC t 2～3） | **PARTIAL**：过拟合意义上的证据强，选择偏差意义上的显著性弱（p 0.05～0.40 取决于零假设），实盘 0 天 |
| C-021 | edge 来自动量方向；幅度、斜率、持续性分量与拥挤度修正不贡献 | P1 | A2 | 任一分量的消融使 OOS 下降 > 0.1 | E-057、E-058（sign_only 1.68 vs 1.72；constant_long 0.09） | SUPPORTED |
| C-022 | 更慢的波动率估计/更宽的带能通过降成本提高净 Sharpe（P10） | P1 | A2 | 预登记规则 R3 无候选合格 | E-056 | **REFUTED** |
| C-023 | 拥挤度修正在时点 universe 上有正贡献（第四轮结论） | P1 | A2 | 走前 OOS 低于对照 | E-055 | **REFUTED**（关闭正确） |
| C-024 | 实盘跑的就是 registry 证据验证的配置 | P0 | A7 | 参数与报告 `best_params` 不一致 | E-061、E-063 | **REFUTED**（当前主树；分支启动门可检出） |
| C-026 | 打分幅度携带收益信息 | P1 | A2 | 两臂逐 bar 收益差的 NW t 不显著 | E-068 | **REFUTED**（t −0.047、p 0.96）；去掉幅度换来 −26% 换手与 +1.78pp 的 MDD 改善，Sharpe 变化在噪声内 |
| C-025 | 组合构建层（波动率目标+上限）本身就能赚钱 | P2 | A2 | 常数多头书 Sharpe < 0.5 | E-058 | REFUTED（0.09）；构建是**放大器**而非来源 |

**G2：PASS**（证据齐全、互相印证、全部可复核）。**G1：PASS**（问题在移除"加信号/调参"这类方案后仍成立：证据有效性与实盘一致性）。

---

## 3. Phase 3 · Problem Research（COMPRESSED）

Problem Statement：对于在 demo 上无人值守运行单策略并打算据此扩展的操作者，当他依据 registry 的 PASS 报告判断"tsmom 已验证"时，由于 DSR 的方差输入来自 5 条近似配置（E-049）、 ledger 不去重（E-060）、启动门不比参数（E-061），他得到的是**一个在真实试验分布下 p 0.2～0.4 的策略被标成 p 0.0002**，且实盘运行的参数已经不是报告里的参数；不解决，则 14～30 天后的实盘对照会拿一个错误的期望值当基准，并可能在错误的置信度上加杠杆或加书。

Causal Chain：表层 = registry PASS；直接原因 = 第五轮在时点 universe 上只跑了单配置（grid_trials 1）、方差来自 ledger 里几条相同配置；深层原因 = ledger 设计只在"网格变小"这一种作弊上做了防护，没有对"网格退化到 1 且 ledger 同质"做防护，且工具从未同时报告一个不依赖 ledger 的零假设；可干预杠杆 = (i) 把真实网格跑进 ledger（已做，E-054），(ii) 两种零假设并列报告（分支），(iii) 参数-报告一致性门（分支），(iv) 操作者对门槛的明确决定（§6）。

JTBD：当一轮研究结束时，我想要一份**自己能复现、别人不能靠缩小网格美化**的证据，以便决定实盘跑什么、加多少。

---

## 4. Phase 4 · 相对价值与经济性（COMPRESSED）

| 杠杆 | 证据 | 结论 |
| --- | --- | --- |
| 修正证据链（本轮） | E-054～E-062 | 纠错，无"不做"选项；不改变实盘 P&L，改变的是决策的置信度 |
| 拥挤度关闭 | E-055 | 已由 starquant-d6 落地；时点全样本 1.64 → 1.72（噪声量级，但方向一致，且消除了一处实盘/验证不一致） |
| 组合层平滑（P10） | E-056 | **否定**；成本占比 14.6% 不是免费午餐 |
| 只取符号（sign_only） | E-058 | **观察到的、未预登记的**候选：MDD −13.5% → −11.7%、换手 −26%、Sharpe −0.04（噪声）。它是本轮唯一"看起来免费"的改进，但它是看结果后发现的，只能作为下一轮的预登记假设（H-001），不能现在采用 |
| 加新信号 / 第二本书 | 第四、五轮 + E-063 | flow probe 已由操作者按 D-019 例外启用；本分析对它的判断不变（信号级 FAIL、91% 与 tsmom 空头同向、静态 universe 上为零），它的价值只能由停止规则与实盘归因裁决 |
| 波动率目标 | E-058（full 年化波动 ≈ 16%，MDD −13.5%） | 线性放大 P&L、不改 Sharpe；在实盘 Sharpe 确认前不动（P14 不变） |

**G3 PASS、G4 PASS**（单人项目；本轮的经济性 = 决策质量）。

---

## 5. Phase 5 · System Analysis（COMPRESSED）

| 层 | As-Is（`8bd2ef0` + 主树未提交） | To-Be（分支） |
| --- | --- | --- |
| `starquant_alpha/validation` | DSR 只有 pooled 零假设；ledger 不去重；无信号/构建归因 | `sampling_variance` + `noise_null` 字段；`unique_trials` + `current_range` 去重；`decompose.py` |
| `starquant_alpha/registry.py` | sha + verdict 门 | + `params_problems`（validation 报告 `best_params` / book 报告 `sleeve.params`，只比 registry 显式设置的键；registry 有而报告没有的键也报错） |
| `starquant_cli/research_cmd.py` | validate 报告缺 `min_train/purge/grid`（fold 向量不可复现，E-049 教训） | + 复现字段 + `trial_sharpes` + `ledger` 统计；`research decompose` |
| `starquant_live` | starquant-88 的 P1/P3/P4/P8/P8b（未提交） | 本轮不触碰 |

Impact Radius：R0 研究命令（纯增量）；R2 `registry_evidence_problems` 已把 `read_report` 传入，合并后 `starquant live run` 在参数不一致时**拒绝启动**（这是想要的行为，KILL-027），逃生口是既有的 `--allow-unvalidated`；R4 报告 JSON 多字段（sha 会变，但旧报告不受影响）；R6 +~330 行（含测试）。Engineering Pre-check：ledger 去重改变 n_trials（E-062：68 → 64），不改变任何判定方向。**G5 PASS。**

---

## 6. Phase 6 · Option Set 与推荐

### 6.1 操作者必须决定：tsmom 证据与实盘状态（KILL-037 的关闭路径）

| Option | 内容 | 后果 | 判断 |
| --- | --- | --- | --- |
| **A（推荐）** | 保留预登记的 pooled-variance 规则；为实盘参数（`crowding_window: 0`）生成一份**如实的 FAIL 报告**并引用它；tsmom 以**主书显式例外**继续 demo（复用 D-019 的 `probe` 块语义：`accepted_by / accepted_on / stop{window_days 30, max_loss …} / review_after_days`，需要把 `_probe_problems` 对主书的限制放开一档，或用 `--allow-unvalidated` + 在 registry 注释里写下决定 D-024）；30～60 天后用 income 归因（M-010）裁决 | 诚实；实盘继续产生唯一还缺的证据；启动门语义保持严格 | 把"未验证"写在脸上，而不是改门槛 |
| B | 预登记**未来**的规则变更：verdict 的 DSR 门改用 noise-null p（或按 horizon 家族分池），同时保留 pooled p 报告，并要求 PBO ≤ 0.1 与 fold_consistency = 1 作为并列硬条件；只从下一份报告起生效 | 今天的候选会得到 WEAK_PASS（p 0.05）；但这是**看到 FAIL 之后改规则**，与仓库原则（D-017/D-018：规则先于结果）冲突 | 只有当操作者认可"异质试验池高估零假设"这一方法论理由、且愿意把它写进 RESEARCH_LOG 时才可取；否则是 KILL |
| C | 停止 tsmom 实盘直到有新证据 | 唯一能产生新证据的来源恰是实盘（demo）；走前/CPCV/PBO 证据并不弱 | 不推荐 |

无论 A/B：`config/alpha_registry.yaml` 的 tsmom `evidence` 块必须改；按 starquant-d6 的要求，**改之前先通知它**，由它重跑启动门与测试后再重启（连同 flow probe）。**结果：操作者选 B**（D-020，由 starquant-d6 在主树预登记并实施；本分支的 D-024 工具与之独立、可叠加）。B 的两个必要条件本分析坚持：(i) 规则文本先进 RESEARCH_LOG 再出报告；(ii) 每份报告继续同时给出 pooled 与 noise-null DSR（M-012），实盘 income 归因是最终裁决（M-010）。

### 6.2 已裁决的预登记假设

| ID | 假设 | 结果 | 处置 |
| --- | --- | --- | --- |
| R1 | 时点 universe 上 16 点网格是否仍选中 168/336/720 | 是（5/5 fold） | horizons 不变；网格记入 ledger |
| R2 | 拥挤度修正 | 否定（E-055） | `crowding_window: 0`（已在主树） |
| R3 | 组合层平滑 | 否定（E-056） | P10 关闭；3 个候选作为申报先验计入下一次 validate |
| R4 | 因子消融 | 见 C-021 | 文档化；`vol_window`/斜率项保持惰性、不改数值（starquant-88 已把 `momentum_mode` 作为可选项加入，默认不变） |

### 6.3 下一轮的预登记假设（不在本轮采用）

| ID | 假设 | 先验 | 规则（先写后跑） | 结果 |
| --- | --- | --- | --- | --- |
| H-001 | `sign_only`：目标 = sign(score)（\|score\| ≥ threshold），即去掉幅度 | E-058：Sharpe −0.04（噪声）、MDD −1.8pp、换手 −26%、成本 −3pp；E-057 时序 IC 为负说明幅度反向 | 时点走前对照：OOS ≥ 基线 −0.05 且 MDD 改善 且换手更低 → 采用；计 1 次试验 | **已执行（2026-09-04，见 RESEARCH_LOG 第七轮补充与 E-068）：规则判 ADOPT**；实现为 `conviction_mode: sign`，证据 `020459Z`。是否写入 registry 由操作者决定 |
| H-002 | horizon 权重向 336h 倾斜（如 0.2/0.5/0.3） | E-057：336h IC 最强、720h 最弱 | 单点对照，计 1 次试验；OOS ≥ 基线 +0.05 才采用 | **已执行 2026-09-04：否决**（OOS 1.4619 vs 基线 1.7140，5/5 fold 选对照） |
| H-003 | `momentum_mode: vol_scaled`（P11 ii，starquant-88 已实现） | E-043 | 2 点网格；同上 | **已执行 2026-09-04：否决**（OOS 1.4753，4/5 fold 选 fixed） |

### 6.4 Won't（Scope Firewall）

加新信号；Kelly/ML sizing；提高 vol_target；交易所条件单；本轮不重跑 `data pool history`（starquant-88 要求共享数据根保持不变）。

---

## 7. Phase 7 · Adversarial Review

独立性：同一 Agent；冻结 §2–§6；反方只引用证据 ID。六角色中最相关的三个（Evidence Prosecutor、Delivery Saboteur、Risk Red Team）。

| Kill | 攻击命题 | 关联 | 严重度 | 状态 / 关闭条件 |
| --- | --- | --- | --- | --- |
| **KILL-037** | 实盘唯一策略的"PASS"是方差退化的产物；诚实重算 FAIL；当前没有可引用的 PASS 报告（Evidence Prosecutor） | C-019、C-020 | **P0** | **CLOSED**：四个关闭条件全部满足——D-020 规则先写入 RESEARCH_LOG 再重跑（`a4ee852`）；新报告 E-067 的 `best_params` 与 registry 参数逐项一致；DSR 仍在报告中（p 0.257）；M-010 实盘裁决保留。残余风险记录在 KILL-045：这是看到 FAIL 之后改的规则，跨轮的家族级选择从此只剩 ledger 计数可见 |
| **KILL-045** | D-020 的两个 PASS 条件不独立：NW t 与 `Sharpe × √年数` 的比值是 1.001（E-067），所以在 5.14 年的 OOS 窗口上"t ≥ 2.0"等价于"Sharpe ≥ 0.88"，比并列的"Sharpe ≥ 1.0"更松——看起来是两道门，实际只有一道（Evidence Prosecutor） | D-020 | P1 | **CLOSED（2026-09-04，D-028）**：补门已实现并前置登记；不改变 tsmom 的判定（1.54 与 3.50 都远超门槛），但规则的保护力弱于表面。建议下一轮把第二个门改成对**选择**敏感的量（例如按 horizon 家族分池的 DSR、或 fold 间 Sharpe 的最小值），并在 RESEARCH_LOG 里记下本条；在此之前不要把"两道独立门"当作 D-020 的辩护理由 |
| KILL-046 | 引用报告的头条 OOS 1.5445 是逐 fold 混合配置（fold 选择 [72, 0, 72, 72, 0]）的估计，而 registry 运行的是单一 `crowding_window: 0`；两者不是同一条净值序列（Delivery Saboteur） | E-067、C-024 | P2 | ACCEPTED：偏差方向保守（单配置自身 OOS 1.65 > 混合 1.54），且 `best_params` 与 registry 一致因而参数门成立。建议在 registry 注释里写明"头条 OOS 属于走前混合，运行配置的单独 OOS 为 1.65（175236Z）" |
| KILL-038 | sha 校验保证不了"跑的就是验证的"：registry 参数与报告不一致却能启动（Delivery Saboteur） | C-024 | P1 | MITIGATED（分支 `params_problems` + 测试；合并后 CLOSED） |
| KILL-039 | 三个会话同时改一棵树：一个会话的提交无意捕获了另一个会话的 registry 改动（E-063），ledger 被三方追加（Delivery Saboteur） | 全部 | P1 | MITIGATED：本会话只在 worktree 改代码；ledger 追加行是原子的；starquant-88 声明不再跑 tsmom validate / pool history；剩余风险 = 合并时 `model.py/engine.py` 冲突，由操作者按顺序合并（先 starquant-88，后本分支） |
| KILL-040 | flow probe 以 FAIL 级信号证据进入实盘，实际是 tsmom 空头侧倾斜（91% 同向），其历史收益来自后来退市的币（KILL-018 残余）；停止规则 −1% 权益 / 30 天在 3% 平均敞口下约等于小书自身 −33% 的回撤（Risk Red Team） | E-063 | P1 | ACCEPTED（操作者决定 D-019）；本分析要求：日报里小书的 income 归因与 tsmom 分开看；若 30 天 Sharpe < 0 即按规则停 |
| KILL-041 | `sign_only` 是看结果后发现的（Evidence Prosecutor） | H-001 | P2 | CLOSED：不采用，只预登记 |
| KILL-042 | 时序 IC 显著为负而策略赚钱，可能是 IC 计算受成员窗口截断或 hold 语义影响的伪象（Evidence Prosecutor） | C-021 | P2 | **CLOSED（2026-09-04）**：`sign_bucketed_ic` 用非重叠标签按符号分桶复核。负 IC 是重叠标签的伪象（非重叠后 −0.01 ～ +0.05）；符号在每个前瞻期都对（多头桶 +0.25% ～ +3.40%，空头桶除 336h 外皆负）；桶内幅度与收益弱负相关（−0.02 ～ −0.09）。独立复现了 H-001 的结论 |
| KILL-043 | noise-null 的 p 0.05 会被误读为"通过"（Skeptical PM） | E-062 | P2 | MITIGATED：报告字段命名 `noise_null`、文档明确"信息性、不进 verdict" |
| KILL-044 | ledger 去重改变了 n_trials（68→64），有"改规则以求通过"之嫌（Evidence Prosecutor） | E-062 | P2 | CLOSED：去重前后判定相同（FAIL/FAIL），且与 `book` 既有的签名去重一致（D-018 已采用同一规则） |

Pre-Mortem（30 天后失败的最可能原因）：① 实盘 Sharpe 低于 1 → 事后看 D-020 会像"改门槛救策略"（→ 规则已先写进 RESEARCH_LOG、DSR 仍在报告里，但 KILL-045 削弱了辩护；M-010 必须真的执行）；② 三方合并时 `model.targets` 签名冲突导致实盘启动失败或 hold 种子失效（→ 合并后跑 T-L03 同构测试）；③ flow probe 在下一次山寨币暴涨中被挤压、停止规则触发得太晚（→ 观察 M-008）。

Inversion：要让本轮白做，只需"把 133239Z 继续挂在 registry 上、把 p 0.40 当噪声、重启实盘"。反向控制 = KILL-037 OPEN + 参数一致性门 + 操作者已暂停重启。

**G6：PASS**（P0 已关闭；剩余 OPEN 为 KILL-045/042 两条信息性 P1/P2，各有下一轮的动作）。

---

## 8. Phase 8 · Scope

**Must（本轮已交付）**：E-054～E-062 的证据；分支上的五项工具改动与测试；本文档；RESEARCH_LOG 第七轮；ARCHITECTURE D-024。
**Must（操作者）**：§6.1 决定；通知 starquant-d6 后改 registry；合并顺序：starquant-88（实盘路径）→ `refactor/alpha-round7`（工具）；合并后跑全套测试与 `starquant live run --dry-run --cycles 1`；再重启。
**Should（下一轮）**：H-001～H-003 预登记验证；KILL-042 复核；KILL-045 的补门（对选择敏感的第二条件：按 horizon 家族分池的 DSR，或 fold 间 Sharpe 最小值）；`validate` 输出该分池 DSR。
**Won't**：见 §6.4。

不以"第一版"为理由删掉的项：参数一致性启动门（资金/证据完整性）。

---

## 9. Phase 9 · Delivery Contract（分支 `refactor/alpha-round7`，基于 `8bd2ef0`）

| DL | 内容 | 文件 | 测试 | 验收 |
| --- | --- | --- | --- | --- |
| DL-11 | 信号 vs 构建分解 | `starquant_alpha/validation/decompose.py`（新）、`research decompose` | `tests/alpha/test_decompose.py`（受控 conviction 的数值；full 与 `model.evaluate` 逐位一致）、`test_cli_offline` 的命令用例 | `starquant research decompose --strategy tsmom --universe pit --from 2021-01-01` 复现 E-058 |
| DL-12 | ledger 去重 + noise-null | `ledger.py`、`multiple_testing.py`、`research_cmd.py` | `test_dsr_inputs_count_exact_replays_once`、`test_noise_null_is_reported_next_to_the_pooled_dsr`、CLI 重放用例（同网格再跑一次 n_trials 不变） | validate 输出 `ledger.duplicate_rows/replayed_rows`、`multiple_testing.noise_null` |
| DL-13 | 参数一致性启动门 | `registry.py` | `test_evidence_gate_compares_registry_params_with_the_cited_report` | 主树 registry 报 `crowding_window is 0 … but 72`；flow probe 通过 |
| DL-14 | 报告可复现字段 | `research_cmd.py` | CLI 用例断言 `folds/min_train/purge/grid/trial_sharpes` | 任何 fold 向量可从报告自身复现 |

Source Trace：DL-11 ← E-057/E-058, C-021/C-025 ← M-013；DL-12 ← E-049/E-059/E-060/E-062, C-019, KILL-037/043/044 ← M-012；DL-13 ← E-061/E-063, C-024, KILL-038 ← M-009；DL-14 ← E-049（fold 向量不可复现）。

验证结果（2026-09-03 18:0xZ，worktree）：`ruff check .` 通过；`ruff format --check` 通过；`mypy` 通过；`pytest` 全套通过（见本文档末尾的运行记录）。

Owner：操作者本人（Approval Owner 对 §6.1 与 registry 改动拥有决定权）；Agent 只交付分支与证据。

---

## 10. Phase 10 · Learning Plan

| Metric | Claim | 指标 | 阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- |
| M-010（沿用） | C-020 | 基于 income 的 30 天 tsmom Sharpe vs 时点走前 OOS 1.48（±2 s.e. ≈ ±1.4） | z < −2 | 30 天（P1～P3 落地后起算） | 复查 / 停用 |
| M-012 | C-019 | 每份 validate 报告同时含 pooled 与 noise-null p，且 `ledger.duplicate_rows` 被报告 | 缺失 | 持续 | 报告无效 |
| M-013 | C-021 | 每轮对实盘配置跑一次 `research decompose`：sign_only 与 full 的 Sharpe 差、constant_long 的 Sharpe | constant_long > 0.5 或 full − sign_only < −0.2 | 每轮 | 重审信号定义 |
| M-014 | KILL-040 | flow_short 30 天 income Sharpe 与 tsmom 空头腿的相关 | Sharpe < 0 或相关 > 0.8 | 30 天 | 按 D-019 停止规则处理 |

---

## 11. Final Decision

**GO（受控）**。硬门禁复核：OPEN P0 = 0（KILL-037 已按四个预设条件关闭）；P0 Claim C-019 REFUTED——它推翻的是**旧证据的置信度**而不是策略本身，新证据（E-067）在预登记的新规则下成立；C-024 由本分支的参数门修复；相对价值与经济性可接受。因此 GO，但受控：tsmom 的 edge 仍是 C-020 PARTIAL，实盘 OOS 仍是 0 天，M-010 的 30 天 income 归因是最终裁决；KILL-045 说明新规则的第二道门在当前样本上不约束，下一轮必须补一个对选择敏感的门。

Quality Score：真实性 5、证据 5、根因 5、战略一致 4、相对价值 4、可行性 5、范围收敛 4、可交付 4（三会话并行，合并顺序有依赖）、可验证 4、对抗生存 4 = **44/50**。

附：本轮可复核脚本在会话 scratchpad（`oos_compare.py`、`decompose.py`、`diag/run.sh`）；它们的逻辑已分别进入分支的 `research decompose` 与本文档的预登记规则。分解结论的正式报告是 `reports/research/decompose-tsmom-20260904T023330Z.json`（随本分支提交，不计入 trials ledger）。研究报告：`tsmom-validation-20260903T174552Z`（R1）、`175236Z`（R2）；两次运行共向 `trials.jsonl` 追加 18 行。
