# 深度分析：alpha 模块整体审查——「简单」是 50 余条假设被否决后的幸存态，可写的是尺子、名额与操作者已选的方向（2026-09-17）

> 深度分析 V3.7 · 等级 L · 只分析不执行（操作者原话：「先分析，给出方案，不要执行」）。
>
> **Reading Check**：本次理解为「操作者要对 `starquant_alpha` 及其与研究流水线（`starquant_cli/research_cmd.py`）、实盘引擎（`starquant_live/engine.py`）的衔接做一次代码与设计层面的审查：子模块之间有没有异常、各子模块能不能优化、有没有更优的整体方案，并给出一份可决策的优化方案；交付对象是单一操作者；只分析不执行」。最高风险预设为 Pre-AM1（P0）「模块看起来简单 = 欠工作，优化空间在加东西」。若它不成立——简单是 7 条手写信号、缠论、配对、676 个挖掘表达式、3 族构造候选、6 档退出、3 格池子准入全部被诚实否决之后的幸存态——方案的重心就从「给信号层加东西、调参数」变为「统一研究尺子、守住在位者的 ledger 名额、把操作者已选的退出方向所需的代码做出来、以及长期的候选前向检验与新信息」。
>
> **Interaction**：Yellow（完整度 🟢用户 🟢场景 🟡损失 🟡成功标准 🟢约束 🟢可得证据）｜ 等级：**L**，命中「≥3 模块（signals / portfolio / overlays / validation / mining，外加 cli 与 live 两处衔接）」「资金链路（demo，规则将带进真实资金）」「AI/策略：自主决策、生产影响」；本档不覆盖：无默认省略；按操作者要求 Phase 9–10 只出契约不执行 ｜ 当前决策上限：**PIVOT**（H3：C-AM02「瓶颈在机制」UNKNOWN、C-AM08「前向板有价值」UNKNOWN；H5：层 0 各项作为「alpha 优化」的相对价值 Unproven，它们是研究工具卫生）｜ 输出状态：**DONE_WITH_CONCERNS**（四个带价钱的裁定交操作者，无默认）｜ 外部动作授权：无（只读：仓库、`reports/`、`.starquant/live/{state,heartbeat}.json`、日报 09-17；未跑 validate / mine / book / overlay、未写 ledger、未改配置、未重启、未下单）。
>
> **本文的冻结稿在 Phase 7 被独立子代理推翻了一条 P0、九条 P1**（§8）：冻结稿把「候选进不了 registry」归因于判定与合成的机制，而唯一支撑它的案例（`594a12f9`）在仓库里有三处相反裁定；冻结稿把 O-2 的 ledger 成本写成 0（今天的 construction digest 已因 `flat_inside_band` 变了）；把退出层「全部已判负」（k<3 止盈等档位从未进网格）；把 D-045 的重启写成未发生（09-16T18:50Z 已重启）。被推翻的段落不删，标 **[R 修订]**。**并行会话同日合入的六个 PR（#32–#37）又把冻结稿的两个 Option 做完了**：O-2（embargo 720 两臂）已跑并结案，O-6（等风险书门的独立推导）已写成 EXP-AE2；操作者当日裁定 Q-CRITICAL = D、reopen 条件 (2) 授权、重启纪律入 `docs/RUNBOOK.md`。这些以 **[并行]** 标出。
>
> **[R2 修订，2026-09-17 当日]** 操作者裁定「**Q-A 全做，Q-B 先 M6 后下沉，Q-D 是**」。层 0 六项当日全部合入 `main`（#40 / #41 / #42 / #44 / #45 / #48），逐项落点、读数与两条对下一个人有用的更正见 `docs/RESEARCH_LOG.md` 2026-09-17（续二）与本文 §14。**[R4 修订，当日]** 操作者随后裁定 **Q-C = 建**，前向板已实现并合入（§14.5）：C-AM08 仍是 UNKNOWN，但它第一次**可检验**了——那条 falsifier 的前半（「上板即计费的规则被绕过」）现在由测试守着，后半（「2 年后无一候选前向 z 过校正门」）要靠板自己攒年。执行中查出本文自己错了一处：「六条命令三本书」不全是缺陷，其中 `overlay` 的裸 ensemble 是写在 RESEARCH_LOG 2026-09-08 的**协议**，动它会打断与每一条 D-017 裁决的可比性；受影响的句子保留原文并标 **[R2 修订]**。
>
> ID 命名空间 `AM`（alpha module）。Constitution：仓库无 `deep-analysis-constitution.md`；硬约束取自 `tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py`（`FREEZE_ENDS 2026-10-13T19:00Z`、`FROZEN_CONSTRUCTION 46b8d731…`）、`docs/RUNBOOK.md` K-EX14、`docs/RUNBOOK.md`「重启实盘循环」、`governance/reopen.yaml`、`governance/window_changes.yaml`、`starquant_governance/policy.py`（0.3.5）、`tests/architecture/test_source_budget.py`（三个包全部零 headroom）。本文与同日的 `2026-09-17-alpha-efficiency-deep-analysis.md`（效率）、`2026-09-17-full-system-audit.md`（审计）并读：它们已裁定的证据不重跑，只引用并点名网格。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **PIVOT**（H3 + H5）。「模块简单」作为「欠工作」的诊断不成立；「机制在拦候选」在当前证据上不可判，与「没有 edge」同样成立；冻结期内 alpha 侧可写的不是新信号，是四件**工具与名额**的事和一件**操作者已选方向的前置代码**；真正能提高吞吐的机制（候选前向板）是年级别仪器，要不要建交操作者 |
| 一句话问题 | alpha 模块把候选变成可上线策略的吞吐两周为零：在跑的是 1 条 WEAK_PASS 的周级动量主书 + 1 条书级 REJECT 的探针 sleeve；候选史显示信号层与构造层每一格都已测过并否决；在位者的证据是一条全样本尾巴，真选择网格下 OOS 1.27–1.49 过不了 family gate，实测滑点 4.43 bps 下余量 −0.013；而每一笔 tsmom 试验都在抬这道门——今天一次误用默认 16 格网格就花掉了约 35% 的 headroom |
| 逐层审查结论（§2） | **无行为级 bug**（9,187 行读完；同日审计的 D-043/044/045 已修并已重启到位）。找到的是：三处口径/契约缺陷（六条研究命令量三本书；ensemble 层幅度重入与 D-024 不自洽；`validate` 默认 16 格网格是名额脚枪）、两处观测缺口（`max_weight` 截掉的风险份额；实盘不记 `symbols_settled`）、四处设计性质（合成器不重定标；截断不回填；`k×σ_entry` 单位在高 σ 名字上止损不可达——#37 已仪器化；挖掘候选按结构至多 WEAK_PASS 且 mined 桶门高于在位者） |
| 选定的框定 / 放弃的框定 | D-AM00：F4「衔接口径与名额」+ F5「新信息」+ 操作者已选的 F6「未测退出档位（Q-CRITICAL = D）」；F3「机制在拦候选」降为 UNKNOWN（KILL-AM-01）；F1「加复杂度」、F2「调参」被证据排除 |
| Success Definition | **M-AM04**（问题级，沿用 M-AE01 / M-010：候选对在跑构造的等风险 ΔSharpe / ΔMDD / 尾部共回撤；30 天归因 z）；**M-AM07**（领先，与任何方案无关：tsmom family gate 的 headroom 笔数，今天 ≈ 58–92）；M-AM05（护栏：`construction_fingerprint 46b8d731` 不变）；M-AM03 / M-AM06 降为描述 |
| 推荐（D-AM01） | 层 0（现在，零构造变更、零 ledger）：① `validate` 网格脚枪修复；② 统一研究尺子（形状交裁定：M6 或下沉）；③ 实现 EXP-AE3 的 `trailing_activate`（默认关、逐位不变）；④ 三件观测量；⑤ `best_params` 按预登记规则选；⑥ ensemble 幅度守卫。层 1（10-13 后，已预登记）：EXP-AE1（8 笔）、EXP-AE2（规则事务）、EXP-AE3（4 笔）、`flat_inside_band` 采纳裁定。层 2（长期）：候选前向板（Q-C）、新信息。Won't 明写（§7.1） |
| 最大价值 / 最大风险 | 价值：把「优化」从已判负的信号层与参数层移开，落到在位者名额、尺子、与操作者已选方向的前置代码上。风险：RISK-AM06——操作者第 7 次听到「等」；补偿是层 0 六项全是冻结期内**可写**的，其中 ① 直接保护 headroom |
| Strategic Fit / Relative Value / Economic | Medium（层 0 是研究工具卫生，不是 alpha 侧交付；搬家行数不计入 alpha 投入）/ 层 0 Strong（零计费、修尺子、护名额）；前向板 Unproven / N/A |
| 被接受的损失与补偿 | 操作者短期看不到收益变化；并行会话承担 `research_cmd.py` 冲突；补偿 = §12 四个带价钱的选项 + 一张逐子模块审查表（§2） |
| 开放 P0/P1 | C-AM02 UNKNOWN（10-13 后 EXP-AE1/AE2 是它的第一批检验）；C-AM08 UNKNOWN；GAP-AM02（截断风险份额）、GAP-AM03（前向板信噪比） |
| G0–G7 一行 | G0 PASS · G1 PASS（框定按 §8 改）· G2 PASS（12 处数字按审查更正）· G3 PASS（每个 Option 有 80% 方案对照）· G4 PASS · G5 PASS · **G6 FAIL → PASS**（P0 ×1 / P1 ×9 / P2 ×10 全部以撤方案、改状态、改范围或新证据关闭，§8.2）· G7 PASS（契约齐，无待执行项） |
| 下一动作 | 操作者答 §12 的 Q-A（层 0 授权）；Q-A 为是 → 先做 ①（< 60 行，保护 headroom），再按 Q-B 定 ② 的形状 |

---

## 1. Gate Summary

| Gate | 状态 | 依据 | 未通过项 / 备注 | 决策上限 |
| --- | --- | --- | --- | --- |
| G0 | PASS | 用户、场景、约束、证据齐；无 FATAL | 损失与成功标准只有方向 → K4 WARNING，§5.4 解除 | — |
| G1 | PASS | 移除「加东西」预设后问题仍成立（吞吐为零可观察） | F3 由「支持」降 UNKNOWN（KILL-AM-01） | — |
| G2 | PASS | 24 条证据全部 E1（E-AM17 为 E2）；审查抽样复核 14 处一致、12 处不一致，本版逐处更正 | C-AM02 / C-AM08 UNKNOWN → H3 | PIVOT |
| G3 | PASS | 每个 Option 对照了更简单的 80% 方案（含 09-13 的 M6、`run_shadow.sh`、继续用探针） | 层 0 相对价值 Strong 但性质是工具卫生 → H5 | — |
| G4 | PASS | Strategic Fit Medium（KILL-AM-10）；无经济角色 | — | — |
| G5 | PASS | 工程预检：三处 ratchet 抬顶逐项写理由；验收分层（KILL-AM-05） | — | — |
| G6 | FAIL → PASS | 独立子代理审查（§8）；20 条 Kill 全部以新证据或方案/范围变更关闭 | 审查者未复审本版 | — |
| G7 | PASS（分析交付物） | 本文 + 校准记录；无待执行代码 | — | — |

命中硬门禁：**H3**（C-AM02、C-AM08 UNKNOWN）、**H5**（层 0 作为 alpha 优化 Unproven；O-5 Unproven）。H1/H2/H7 在冻结稿命中，本版以状态变更与撤方案关闭。未命中 H4（P0/P1 主要靠 E1）、H8（demo 边界已知）。

---

## 2. 逐子模块审查读数（操作者点名要的那一份）

读法：`starquant_alpha` 全部 38 个文件 9,187 行逐行读过（合入 #37 后；#37 前 9,149），加上两处衔接（`research_cmd.py` 全部命令入口、`engine.py` 的 `run_cycle`）。「异常」分三档：**缺陷**（行为或口径错）、**性质**（设计选择，有后果，已记录或已仪器化）、**缺口**（该有的仪器没有）。

| 子模块 | 读数 | 档 | 处置 |
| --- | --- | --- | --- |
| `panel.py` | funding 按 bar floor 对齐（D-034）；`reference` 显式；`_map` 带全 metrics/spot；无前视 | 干净 | — |
| `features.py` | 全部因果；`refit_boundaries` 锚 epoch（切片不变）；GARCH 手写网格 | 干净 | — |
| `model.py` | `warmup_bars` 按 registry 参数；实盘走 `band=False`（D-033）；`targets()` 重算 `book_weights`（每小时一次可忽略）。**ensemble 幅度重入**：`book_targets` 把各策略 ±1 目标加权平均后直接进 stage 1（`model.py:229–238` → `portfolio.py:293`），不再过 `scores_to_targets`；两策略 +1/−1 得 0（平仓，不是 hold），三策略得 0.33 并按 0.33 定尺寸——与 D-024「edge 在方向不在幅度」不自洽。今天不触发（主书只有 tsmom），主书一加第二条策略即静默激活 | 缺陷（潜伏） | 层 0 ⑥：守卫测试或明确禁止多策略主书（RISK-AM08） |
| `portfolio.py` | 三段式逆波动率 → EWMA 协方差标量 → clip/cap；**`max_weight` 截断不回填**：k=0.60 下 49/95 周期截 BTC/BNB（D-046），截掉的风险不分给别的名字，实现波动 < 目标且集中；**合成器不重定标**（`combine_books`）：主书 32.24% → 总书 35.66%（+10.6%），CONTEXT.md「只有一个风险预算」在多 sleeve 下不成立，但 P32 的 k 阶梯是在总书上量的，现行 0.60 已计入 | 性质 ×2 | 层 0 ④ 记「截掉的风险份额」与「总书 ex-ante vol」；回填/重定标开关只在 10-13 后作研究侧 A/B（Could） |
| `ensemble.py` | mean / `rolling_zscore` 两种；每书一策略 → 恒等；`rolling_zscore` 从未在任何报告出现；`turnover_penalty` 未实现（非零即拒） | 干净 | — |
| `signals/tsmom.py` | `return_scale` 恒为分母（E-043），`vol_window` 惰性（4,668,384 币-bar 0 翻转），`slope_weight` 置 0 翻 3.14%；sign 模式下拥挤修正 44.5% 被吸收（M-018）。手算 BTC score 0.203 与效率分析 0.204 一致 | 性质（已记录） | Won't：persistence/slope 消融是同族再试 |
| `signals/flow.py` | `volume_warmup_fill 1.0` 是上界不是中性（已记录未改，改是 live 变更）；`short_gate` 是事后规则拟合（审计 §6.3），实盘检验自 D-044 起计数，10-02 读 | 性质 | — |
| 其余 7 条信号 | 全部 REFUTED 维持（§4 E-AM04）；`pairs` 的 census 计费、`chanlun` 的 4h 网格钉住都对 | 干净 | — |
| `overlays/exits.py` | 状态机两套实现逐位相等（测试守着）；**`k×σ_entry` 单位有 `1/σ` 天花板**：多头止损在 `k_sl > 1/σ` 时不可达，LSKUSDT σ 0.4517 → 天花板 2.21σ < 6（#37 已写进 docstring 并每日读）；`retrace ≥ adverse` 恒成立故 `k_tr ≤ k_sl` 使止损成死代码（#33 据此撤了 EXP-AE1 的 tr 2.0 格）；**操作者要的「移动止盈」= activation threshold + trail，从未实现**（`ExitParams` 无该参数、`ExitState` 无 armed 标志） | 性质 ×2 + 缺口 ×1 | 层 0 ③：实现 `trailing_activate`（默认关、逐位不变、指纹别名 v8） |
| `overlays/exposure.py` / `ladder.py` | 护栏与阶梯各一份语义，live 与回测同调 | 干净 | — |
| `backtest.py` | `open_to_close` 默认；guards 因果重放（0.60 下 491 根暂停、8.3% gross-capped，#37 改了那句「no-op」）；impact 系数 E5；participation 只量不施加 | 干净 | — |
| `validation/verdict.py` + `walk_forward.py` | D-020/D-028/D-043 齐；**grid 1 或全 fold 同选 → `oos_is_full_sample_tail` → 至多 WEAK_PASS**——挖掘候选 `to_signal` 只有 `entry_threshold` 一个参数，按结构永远 grid 1 | 性质 | 记录：mined 候选要 PASS 必须带 ≥2 点网格（再计费） |
| `validation/cpcv.py` | embargo 50 vs 回看 720/1,442（自述 OPEN）。**[并行]** #35 两臂实测：grid 2 上 `fraction_negative` 0.0 → 0.0、q05 逐位不变——「在不做选择的网格上不可观测」，结案；默认值不动 | 已结案 | 要真检验须先有一个真选择的网格（与 D-043 同一出口） |
| `validation/ledger.py` + `multiple_testing.py` | 签名八元组 + 7 天折叠（口径 ④）；quantile gate；`effective_trials` 只报不用。**tsmom 桶 145 行 / 107 unique@7d，family gate N = unique + 本次网格 + 手工申报 152**；今天 N=259 门 1.5571、余量 +0.0283（09-13 是 +0.0426） | 干净（但名额在缩） | 层 0 ①（脚枪）+ M-AM07 |
| `validation/book_limits.py` | D-018 三检查；等风险口径只适用此后候选；**回撤条款是单路径极大值，P31 量到 f 邻域斜率 138.7pp/单位、static 同段符号为负** | 性质 | **[并行]** EXP-AE2 已写：门 = 预算 − 主书 q95，k=0.60 下 0.3pp（比 1pp 更紧） |
| `validation/decompose.py` / `stability.py` / `labels.py` | 纯函数，无 I/O，不计费 | 干净 | — |
| `mining/expr.py` + `search.py` | 量纲类型、canonical hash、20 个节点、11 族；`mine` 带 `--baseline` 时按边际排序（`ranked_by`）；`--measure` 已落盘相关矩阵。**mined 桶 2,073 行 / 1,559 unique@7d，门 ≈ 1.785 > 在跑书 OOS 1.5854** | 性质 | Won't：不加族、不改 N 口径（09-14 §7 第 1、2 项已裁并落地） |
| **衔接 · 研究**（`research_cmd.py`） | **六条命令量三本书**：`validate` = 带 + guards + exits（`:889/:899`）；`backtest` = 带 + guards、无 exits（`:469`，无 `--exits`）；`book`（`:2063–2075`，`bare` 建书后 `apply_no_trade_band`）、`overlay`（`:1580–1581`）、`correlate`（`:1463–1464`）、`mine` = 只带。同一 tsmom 书 `backtest` 1.6146 对 `validate` 1.6725。`_exit_params` 全文件只有 `validate` 一处调用。**`--grid` 默认 = `DEFAULT_GRIDS[strategy]`（tsmom 16 格）**：09-17 `flat_inside_band` A/B 按 2 笔定价、实计 32 笔（每臂 16），family gate N 259 → 293、门 1.5572 → 1.5715、headroom 92 → ≈58；对照臂因此不复现在架指针（1.2757 vs 1.5919）。`backtest/book/diagnose/correlate/overlay` 不传 metrics/spot（`_load` 自述），OI/LSR/basis 候选过了 validate 进不了 book。复现一份 validate 报告要从 CLI 导入私有函数 | 缺陷 ×2 + 缺口 ×2 | 层 0 ① ②；O-4 缩版 |
| **衔接 · 实盘**（`engine.py:716–935`、`live/exits.py`） | `targets(band=False, previous=…, reference_symbols=…)` → 阶梯 × 节流标量 → `exits.apply`（场地锚、D-045 已修）→ guards → `plan_rebalance`（带 + 参与率）；D-033 等价性有测试。**[R 修订]** 循环已于 09-16T18:50:38Z 重启到含 #27 的代码（PID 66666，`restarts` 51，源文件 mtime 18:47:58Z）。**缺口**：每周期只记 `inputs.funding_history` 布尔，不记多少个币的结算非零（研究侧有 `symbols_settled`） | 缺口 ×1 | 层 0 ④ |

---

## 3. Phase 1 · Reality Check

### 3.1 需求四问

| 问 | 答 | 证据 |
| --- | --- | --- |
| 谁的需求 | 单一操作者，同时是风险承担者与审批者。原话：「阿尔法模块看起来仍然比较简单，需要仔细深入地优化整个模块」 | — |
| 频率 / 规模 / 损失 | 14 天内第 6 次同形的「alpha 侧要更好」提问（09-03 复查、09-05 P17、09-14 挖掘、09-14 回测专家评估、09-17 效率、本次）。无已实现损失被定义；可观察的机会成本是 tsmom 的 family gate 名额（今天 ≈ 58–92 笔，见 E-AM06）与操作者注意力 | E-AM04、E-AM06 |
| 现在怎么绕过、付出什么代价 | 绕行 = 反复提问 + 两次手改构造（`vol_target` 0.15 → 0.30 → 0.60），每次清零 M-010 的 30 天窗口。上一次是同日早些时候的效率分析：Final PIVOT，操作者随后裁定 Q-CRITICAL = D（更早止盈止损）并授权 reopen 条件 (2) | E-AM16、E-AM21 |
| 现有方案能否满足大部分需求 | 流水线已把能测的都测了（E-AM04）；「简单」是筛出来的。**但**流水线自己有两处缺陷正在消耗在位者的名额与尺子的可信度（六条命令三本书；默认 16 格网格），而操作者选的方向（未测退出档位、activation trailing）需要一段还没写的代码 | E-AM12、E-AM22、E-AM23 |

方案型输入还原：操作者没有提出具体方案；「看起来简单」预设了「优化 = 变复杂」。移除该预设后，Problem 是：**候选变成可上线策略的吞吐为零，且在位者的证据在被自己的研究消耗；冻结期内能动的只有尺子、名额与操作者已选方向的前置代码。**

### 3.2 需求来源与偏差

| 项 | 内容 | 折减 |
| --- | --- | --- |
| 渠道 | 操作者读代码目录与近期报告的观感 | 陈述证据 E2 |
| 样本 | n=1 观感；同一观感 14 天内出现 6 次 | 观感一致不等于诊断正确：前 5 次分析里 4 次把原始框定判为不成立（校准记录） |
| 已知偏差 | 「代码量少 = 简单 = 差」的锚定；近因（09-15/16 回吐）；HiPPO | 本文只用候选史与代码事实 |

### 3.3 需求预设清单

| Pre | 提出者默认成立的前提 | P级 | 若不成立会改变什么 | 处理 |
| --- | --- | --- | --- | --- |
| Pre-AM1 | 模块简单 = 欠工作，优化空间在加东西 | **P0** | 方案从「加」变为「尺子、名额、前置代码」 | → C-AM01：**不成立**（E-AM04） |
| Pre-AM2 | 优化可以在冻结期内落地 | P1 | 构造类改动只能预登记到 10-13 后 | 不成立（E-AM15）；冻结期内只做零行为变更 |
| Pre-AM3 | 「衔接异常」= bug | P1 | 若是口径缺陷，修法是统一实现 | 部分成立：无行为级 bug；三处口径缺陷（§2） |
| Pre-AM4 | 子模块可逐个独立优化 | P1 | 构造参数每格已测过 | 不成立（E-AM04 构造段） |

### 3.4 Early Kill / G0

K1 否；K2 否（全部 E1）；K3 否；**K4 WARNING**（成功只有方向）→ §5.4 解除；K5 否；K6 部分（前向板复杂度对价值，§7 定价）；K7 否；K8 否。**G0 PASS**。

---

## 4. Phase 2 · Evidence Ledger

全部 E1（代码、已提交报告、可复现复算），E-AM17 为 E2。复算用 `.venv/bin/python`。**[R 修订]** 标出的是审查后更正的数字。

**E-AM01（E1）代码规模。** `starquant_alpha` **38** 个文件 **9,187** 行（#37 后；#37 前 9,149）：核心 2,415（panel 343、features 340、model 363、portfolio 389、backtest 390、registry 435、ensemble 90、report 59、init 6）、signals 1,822（9 条）、overlays 874、validation 2,124、mining 1,914（expr 1,080 + search 787 + init 47）。`tests/alpha` **8,938** 行 / 59 个文件（#37 前）。研究流水线不在包内：`starquant_cli/research_cmd.py` 3,396 行（4068ba15；#35 又加约 60 行）；实盘衔接 `starquant_live/engine.py` 2,221 行。`test_source_budget.py`：alpha 9,187 / cli 6,011 / live 9,784，三者都等于当前行数——**零 headroom**。

**E-AM02（E1）在架信号的有效形式。** 见 §2 `signals/tsmom.py` 行；出处 `tsmom.py:51–53`、`RESEARCH_LOG.md:499`（3.14%）、`:1817`（44.5%）。

**E-AM03（E1）信号-构建分解（第七轮，`RESEARCH_LOG.md:379`）。** full 1.72 / constant_long 0.09 / sign_only 1.68 / equal_notional 0.43 / long_only 0.60 / short_only 0.64；`magnitude_over_direction` = 0.0；空头腿 Sharpe 0.97 > 多头 0.66；与等权多头基准相关 −0.18。已采纳为 D-024 与 H-001。

**E-AM04（E1）候选史——已判否清单，按网格点名。**

| 层 | 已测且否决/维持 | 出处 |
| --- | --- | --- |
| 手写信号 | xsmom（边际 −0.2985，前置闸）、carry（OOS 0.54 < 门 0.99）、residual（1.08 < 1.0935）、meanrev / breakout（死因不随条件变）、chanlun（P27）、pairs（P28；19,578 对里挑，无 edge） | `RESEARCH_LOG.md:5865–6382`、`:4020`、`:4266`、`:6716` |
| tsmom 变体 | H-002 权重倾向 336h（−0.2521）、H-003 `vol_scaled`（−0.2387）、拥挤修正开/关两次重出（开保留） | `:595–596`、registry 注释 |
| 构造层 | R3 三格 / P10 A、C（168/336 半衰期，−0.21 / −0.12）；P29 GARCH（−0.2732，t −7.09）、HRP（−0.2285；死因是 inverse-variance 不是聚类）；ewma-168 单臂 +0.0294（t 0.44）；P12 池子准入三格（−0.4352 / −0.2252 / −0.4894）；D-039 带宽 0.40 驼峰顶 | `:361–540`、`:5618–5765`、`:1316` |
| 退出层 | **已测网格**：SL {2.5, 4, 6, 8}σ、TR {0, 4}σ、TP {0, 3, 4, 6, 8}σ、cooldown {24, 6}、`unit_mode current`、regime 2×2、信号衰减退出（P23）→ 只有 6/0/6/24 存活。**[R 修订，KILL-AM-07] 未进网格**：TP < 3σ、SL < 2.5σ、TR < 4σ、保本、部分止盈、activation trailing——操作者已裁定测其中两格（EXP-AE1：TP 2.0 / SL 2.0）并另立 EXP-AE3 | `live.demo.yaml` exits 注释、P22/P22b/P23/P24、效率分析 E-AE08、`RESEARCH_LOG.md` 2026-09-17 |
| 挖掘 | 1h 空间 676 个表达式：standalone 越过在跑书 0/676（最好 1.7144 对 1.8184）；边际为正 24/676；进 validate 7 个：1 PASS（`594a12f9`，D-043 前；grid 1、tail True）/ 6 FAIL；该候选 `book` 五份报告全 REJECT，全挂 D-018（pit +2.55pp；static 面 **−1.74pp，符号跨 universe 翻转**；等风险后 +1.87pp） | 09-14 挖掘分析 E-010/011/012；`book-…-20260912T185333Z.json` |
| 数据宽度 | OI 叶 0/54 REFUTED；LS 叶 4/36 未晋级（10-03 后可答方向问题）；basis 0/18 REFUTED；macro/onchain/index 撤出（无读者）；清算不可得；社交/解锁不可得；15m 移出 | `reopen.yaml`、ARCHITECTURE 09-16 段 |

**E-AM05（E1）在架证据 `tsmom-validation-20260913T182325Z.json`（复算）。** `grid_size 2`、`oos_is_full_sample_tail True`（artefact 里的 `verdict` 字段是 `PASS`；今天的 `decide()` 与 registry 字符串是 **WEAK_PASS**——D-043）；OOS 1.5919 对门 1.5493（N=242）余量 0.0426；fold [1.77, 0.03, 2.58, 1.22, 2.24]；CPCV `fraction_negative 0.0`、q05 1.185；`embargo 50 = purge 50`；全样本 MDD −40.3%、换手 539.8、平均 |w| 1.345；成本 ×2 1.555；`portfolio` 0.60 / 48 / 96 / 0.15 / 2.0 / 0.005 / 0.40；exits 6/0/6/24；guards −5% / 2.0 / 0.15。

**E-AM06（E1）ledger 与 family gate（口径 ④，合入 #35 后）。** `trials.jsonl` 2,326 行：tsmom 145 行 / **107** unique@7d；mined 2,073 行 / **1,559** unique@7d（676 个表达式）；flow 46 / 43。family gate 的 N = unique + 本次网格 + 手工申报 152（`family_gate.py:161`）：#35 两臂时 N=259、门 1.5571、余量 **+0.0283**（09-13 +0.0426）。**[并行]** `research/flat-inside-band-ab` 分支（未合）误按默认 16 格网格跑了两臂，+32 笔：合入后 N=293、门 1.5715、余量 +0.0204，按翻转点 N≈351 算 headroom **≈ 58 笔**（原 92）。**[并行]** `research/slippage-gate-at-measured-bps` 分支（未合）：实测滑点 4.43 bps 那一格 OOS 1.5437、对门余量 **−0.0134**（95% CI 覆盖两侧；`verdict.decide` 读的是 `cost_stress.x2`，仍 WEAK_PASS）。

**E-AM07（E1）`max_weight` 绑定。** k=0.60 下截断 49/95 个带 `book_weights` 的周期（BTC 49、BNB 27；`live.demo.yaml` D-046 段），截断不回填；「k 不携带 alpha」的恒等式只在 cap 不绑定时成立（审计 §6.2 待裁定）。

**E-AM08（E1）合成器不重定标。** `portfolio.combine_books` / `model.book_weights`：各 sleeve 分别 vol-target 后按 fraction 求和；主书 32.24% → 总书 35.66%（`RESEARCH_LOG.md:2811–2830`）；缩回主书波动率后 Sharpe +0.288 保住、回撤 +1.87pp 仍 > 1pp，该节 §五 裁定「它不能用来救这个候选」。

**E-AM09（E1）判定门结构。** `verdict.decide`：D-020 + D-028 quantile gate + 硬门（fold 一致 ≥ 0.6、CPCV 负比例 ≤ 0.10、PBO ≤ 0.30 当 grid ≥ 4、成本 ×2 ≥ 0）+ D-043 封顶。书门 D-018：ΔOOS Sharpe、`oos_mdd_worsening ≤ 0.01`（Q3 起等风险口径，只适用此后候选）、fold 胜率。P31：该统计量在 f∈[0.200, 0.209] 上斜率 138.7pp/单位、static 同段为负（`:8669`）。

**E-AM10（E1）挖掘的判定链。[R 修订，KILL-AM-11/15]** `mine` 带 `--baseline` 时按 `baseline_marginal_sharpe` 排序（`research_cmd.py` `ranked_by`，09-10 那轮即如此），`--measure` 已落盘相关矩阵；`validate` 对 mined id 的 grid 只有 `entry_threshold` 一轴 → `oos_is_full_sample_tail = consistent or len(param_keys) <= 1`（`walk_forward.py:152`）→ `verdict.py:167–168` 封顶 WEAK_PASS（封顶不挡上线，`registry.py:369`）。09-14 挖掘分析 §7 的五项裁定：第 1 项（N 口径）已裁 ④ 并落地（`04c2cb0b`）、第 2 项（回退 658 行）已执行（`f406faaa`）。C-002「供给是瓶颈」两次 REFUTED；C-003「空间已搜尽」SUPPORTED。

**E-AM11（E1）CPCV embargo。[并行，结案]** `cpcv.py:23–58` 自述 OPEN；#35（prereg `37a6546c`）两臂：embargo 50 → 720，`fraction_negative` 0.0 → 0.0，q05 1.18906 逐位不变，min 逐位不变，只有 mean +0.034。结论：在 `grid_size 2`、`fold_consistency 1.0` 的网格上「根本没有在选」，embargo 不可观测；默认值不动；要真检验须先有一个真选择的网格。**[R 修订，KILL-AM-02]** 两臂 ledger +4 行（对照臂新 2 行；处理臂 2 行 replay）——冻结稿写的「零计费」是错的，原因是今天的 `_construction_digest`（`ac2f7d736725`）因 `flat_inside_band`（`ad70e81a`，09-15）已不等于 182325Z 的 `b9e5bacaf416`。同一份报告首次给出「Cost stress against that gate」：x1 +0.03 过、x1.5 −0.03 不过、x2 −0.09 不过。

**E-AM12（E1）研究衔接：六条命令三本书。[R 修订，KILL-AM-13]** 见 §2 衔接·研究行（行号为 #35 后）。

**E-AM13（E1）实盘衔接。[R 修订，KILL-AM-12]** `run_cycle` 顺序见 §2；循环已于 2026-09-16T18:50:38Z 重启到含 #26/#27/#30 的代码（`state.json.restarted_at`；PID 66666；主 checkout 源文件 mtime 18:47:58Z）；两个构造测试 13 passed，心跳 `ccd7bb9764b5` 经别名归一到 `46b8d731`，M-010 窗口不清零。心跳 `registry` 今天是 `7f8adb754962`。日报 09-17：evidence window 80 根 bar。

**E-AM14（E1）ensemble 幅度重入。** 见 §2 `model.py` 行；`rolling_zscore` 在 RESEARCH_LOG 0 次；研究侧 `validate` 一次只验一条策略的单入口模型（`_model`），多策略主书没有验证路径。

**E-AM15（E1）冻结与预算。** `FREEZE_ENDS 2026-10-13T19:00Z`；K-EX14；`window_changes.yaml` 10-03 两条；policy 0.3.5：`max_concurrent_probes 2`、`max_queued_to_probe_per_window 1`、`max_mine_rounds_per_window 5`、`max_ledger_rows_per_window 1,700`、`trial_range_end_granularity_days 7`、`min_clean_days_before_promotion 30`。

**E-AM16（E1）09-17 效率分析。** Final PIVOT；Scope Firewall；O-AE5 运维 Must。

**E-AM17（E2）操作者陈述。** 「模块看起来仍然比较简单」。

**E-AM18（E1）`validate` 的 `best_params` 按全样本 Sharpe 选**（`research_cmd.py:921`；第七轮副产品 1）。

**E-AM19（E1）P29 明写未跑的格子。** inverse-vol × HRP tilt（`:5715–5720`，需独立预登记计费）。

**E-AM20（E1）09-14 回测专家评估。** 实盘 Sharpe 判到 t=2 需构造连续不动 3.58 年；单个年化 Sharpe 估计 SE ≈ 0.43。

**E-AM21（E1）[并行] 操作者三条裁定（`RESEARCH_LOG.md` 2026-09-17，PR #32/#33）。** Q-CRITICAL = **D**（更早止盈止损）→ EXP-AE1：两格（TP 2.0 / SL 2.0，各只动一条腿），主判据配对 ΔSharpe ≥ 0 两 universe，ledger **8 笔**，最早 10-13T19:00Z；初稿第三格 TR 2.0 已撤（`k_tr ≤ k_sl` 使止损成死代码）；明写排除 TR 1.0σ。**EXP-AE3**：activation threshold + trail 从未实现，需先加 `trailing_activate`（默认关、行为逐位不变），单格 (a=1.5, b=2.0)，4 笔。Q2 = **是**（reopen 条件 (2) 授权）→ EXP-AE2：门 = 声明预算 − 主书自助 q95（两 universe 取更紧）；k=0.60 下 **0.3pp**（比现行 1pp 更紧）、0.45 下 6.9pp、0.30 下 19.7pp——「条件 (2) 与重开 P32 是同一个决定的两半」；`policy.py` 常量未改。Q3 = 是（重启已发生；重启纪律入 `docs/RUNBOOK.md`）。

**E-AM22（E1）[并行] `validate` 默认网格脚枪。** `--grid` 默认 `DEFAULT_GRIDS[strategy]`（tsmom：horizons 4 × entry_threshold 2 × return_scale 2 × vol_window 1 = **16 格**，`research_cmd.py:100/:595`）；在架指针跑的是 `{"crowding_window": [0, 72]}`（2 格）。`flat_inside_band` A/B 没传 `--grid`，两臂各计 16 笔；提交说明自记「按 2 笔定价并据此得到批准，实际计入 32 笔」「headroom 从 92 笔降到 60 笔——一次花掉 35%」。副产物：真选择网格下两臂 OOS 1.2757 / 1.2746，都 FAIL（门 1.57/1.58）——「fold 真的选了，OOS 就掉到 1.27–1.28」。

**E-AM23（E1）[并行] `flat_inside_band` 的价钱。** 同一分支：Δ OOS −0.0011、Δ MDD −0.006pp——对书基本无成本；但它不触发 LSKUSDT 那个仓位（目标 55.11 在带 54.49 之上）。采纳仍是 live 行为变更，10-13 后。

**E-AM24（E1）[并行] 退出单位天花板（#37）。** `adverse ≤ 1/σ`：多头止损在 `k_sl > 1/σ` 时不可达；在册 17 个仓位里 LSKUSDT σ_entry 0.4517 → 天花板 2.21σ < 6.0，唯一一个；`starquant_live/reports.py:822` `exit_reachability` 每日读。

### 4.2 Claim Register

| Claim | 命题 | P级 | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- |
| C-AM01 | 信号层的「简单」是幸存态，不是欠工作 | **P0** | 存在一条有机制先验、在仓库从未测过的手写信号或构造格子 | E-AM04、E-AM19 | **SUPPORTED**；falsifier 部分触发：只剩「同族再试」的付费格子与操作者已选的退出档位（后者由 EXP-AE1/AE3 承接） |
| C-AM02 | 候选进不了 registry 的瓶颈在判定与合成的机制，不在候选供给 | **P0** | 10-13 后 EXP-AE1/AE2 落地 6 个月仍无候选可裁定；或某候选在等风险门下过而在 1pp 门下不过 | E-AM09、E-AM10、E-AM22 | **[R 修订，KILL-AM-01] UNKNOWN**。供给半边成立（C-002 两次 REFUTED）；机制半边只有一个案例（`594a12f9`），而仓库三处裁定其失败是「信号的性质」（`RESEARCH_LOG.md:2850`；09-14 C-005a REFUTED、C-005b PARTIAL 含 static 面 −1.74pp；效率分析 O-AE2 No-Build）；C-003「空间已搜尽」给出第三种解释「没有 edge」，与之同样成立。真选择网格下在位者自己也过不了门（E-AM22），说明机器在按设计工作 |
| C-AM03 | D-018 回撤条款是单路径极大值，在 fraction 邻域是刀刃 | P1 | 换成 bootstrap 尾部统计量后斜率仍与 SE 同量级 | E-AM09 | SUPPORTED（P31）；**[并行]** EXP-AE2 的独立推导在 k=0.60 下更紧（0.3pp），所以「刀刃」不等于「门太严」 |
| C-AM04 | CPCV embargo 污染使 D-020 一道硬门偏松 | P1 | `--embargo 720` 后 `fraction_negative` / q05 不动 | E-AM11 | **[并行] Falsifier 命中**：在 grid 2 上不可观测，结案 |
| C-AM05 | k=0.60 下 `max_weight` 绑定使构造偏离 vol-target 语义 | P1 | 记录截掉的风险份额后读数 < 5% | E-AM07 | 方向 SUPPORTED、幅度 UNKNOWN（GAP-AM02） |
| C-AM06 | 研究流水线住在 CLI 是「三本书」与不可复现的根因 | P1 | 统一 evaluate 后六条命令仍量出不同的书 | E-AM12 | SUPPORTED |
| C-AM07 | 冻结期内 alpha 侧只能做逐位不变的重构与研究工具修正 | P1 | 任一改动移动 `construction_fingerprint` | E-AM15 | SUPPORTED |
| C-AM08 | 离线候选前向板能把「可观察」的候选数从 2 提到数十、零 venue 成本，且能被防住不成为窥视通道 | P1 | 上板即计费的规则被绕过；或 2 年后无一候选前向 z 过 Bonferroni 校正门 | E-AM15、E-AM20 | **UNKNOWN**。**[R 修订，KILL-AM-03]** 它提高的是「可观察」不是「可裁定」：30 个候选 6 个月零假设下 P(max z > 1) ≈ 0.994；单候选判到 z=2 要 (2/1.5)² ≈ 1.8 年，Bonferroni 5%/30 要 z≈2.9 即 ≈ 3.8 年 |
| C-AM09 | 多 sleeve 合成不重定标使「一个风险预算」不成立，但现行 k 已把它计入 | P2 | 等风险重定标后 P32 阶梯读数不变 | E-AM08 | SUPPORTED |
| C-AM10 | 在位者的证据是全样本尾巴，真选择网格下过不了 family gate，实测滑点下余量为负；每笔 tsmom 试验都在退休它 | P1 | 一个 ≥ 4 点、fold 真选的网格给出 OOS ≥ 门 | E-AM05/06/22 | SUPPORTED（030942Z 1.485；fib-ab 1.27–1.28；slip 4.43 −0.013） |

### 4.3 Assumption Register

| A | 假设 | Impact × Risk | 最小验证 | 决策上限影响 |
| --- | --- | --- | --- | --- |
| A-AM01 **[R 修订，KILL-AM-09]** | ~~操作者说的「优化」包含研究工具与判定机制~~ → 改为 §12 Q-A，不再是假设 | — | 操作者回答 | Q-A 为否 → 层 0 只做 ①（脚枪修复，保护名额），其余 PIVOT 到 10-13 |
| A-AM02 | 维持冻结到 10-13、维持 0.60 | 高 × 低 | 冻结测试仍绿 | 不成立 → 三时钟清零 |
| A-AM03 | 操作者接受三处 ratchet 抬顶（各写理由） | 中 × 中 | Q-A | 不接受 → 层 0 ② 只做「不增行」版 |
| ~~A-AM04~~ | ~~09-14 §7 五项裁定未作出~~ | — | **[R 修订，KILL-AM-11]** 已裁并落地（④、回退 658 行） | 关闭 |

### 4.4 Gap Plan

| Gap | 缺什么 | 不确定性 × 影响 | 获取路径 | Owner |
| --- | --- | --- | --- | --- |
| ~~GAP-AM01~~ | ~~embargo 720 读数~~ | — | **[并行]** #35 已答：不可观测 | 关闭 |
| GAP-AM02 | `max_weight` 截掉的风险份额 | 中 × 中 | 层 0 ④：0 笔可观测量 | 研究/live |
| GAP-AM03 | 前向板的信噪比与滥用风险 | 高 × 中 | 建板前先算：板上 N 个候选、T 年后可判的最小 Sharpe | 操作者（Q-C） |
| GAP-AM04 | 等风险书门在 k=0.60 下的 headroom | — | **[并行]** EXP-AE2 已算：0.3pp | 关闭 |
| GAP-AM05 | 实测滑点 4.43 下在位者过不过门的置信区间 | 中 × 高 | `research/slippage-gate-at-measured-bps` 合入后读；不重跑 | 并行会话 |

---

## 5. Phase 3 · Problem Research

### 5.1 Problem Statement

对单一操作者而言，alpha 模块把候选变成可上线策略的吞吐两周为零：在跑的是 1 条 WEAK_PASS 的周级动量主书 + 1 条书级 REJECT 的探针 sleeve；候选史显示信号层与构造层每一格都已测过并否决；在位者的证据是一条全样本尾巴，真选择网格下 OOS 1.27–1.49 过不了 family gate，实测滑点下余量为负；而它的名额正在被自己的研究消耗（今天一次误用默认网格花掉约 35%）。六条研究命令量三本不同的书，使任何跨命令比较都不可信；操作者已选的退出方向（EXP-AE1/AE3）有一半需要一段还没写的代码。不解决的后果：操作者第 7 次得到「等」，或在位者在 10-13 之前被自己的 ledger 退休。

### 5.2 Causal Chain

信号层 sign 模式（幅度无信息）→ 单一策略主书 → 分散化只能靠 sleeve → sleeve 判定走 D-018 单路径 MDD 差 → 唯一 PASS 的候选四次 REJECT（仓库裁定：信号性质，尾部同向）→ 挖掘继续按边际排序、grid 1 → D-043 封顶 + mined 门 1.785 > 在跑书 1.585 → 0 候选进 registry。旁路一：`validate` 默认 16 格网格 → 一次对照实验 +32 笔 → family gate 门抬 0.014 → 在位者余量 0.0426 → 0.0204。旁路二：六条命令三本书 → 「哪个更好」的比较本身失真。旁路三：操作者要的 activation trailing 从未实现 → EXP-AE3 排在代码之后。

### 5.3 Problem Reframing（D-AM00）**[R 修订]**

| 框定 | 一句话 | 区分证据 | 支持度 |
| --- | --- | --- | --- |
| F1 加复杂度 | 模块简单所以要加 | E-AM04 | **证据排除** |
| F2 调参 | 半衰期/带/退出/horizon 还能调 | R3/P10/P29/H-002/H-003/P12/已测退出网格 | **证据排除（已测网格内）** |
| F3 机制在拦候选 | 门与合成器的形状拦了好候选 | 只有 `594a12f9` 一例，且仓库裁定为信号性质；EXP-AE2 推导在 0.60 下更紧 | **UNKNOWN**（KILL-AM-01）；10-13 后 EXP-AE1/AE2 是第一批检验 |
| F4 衔接口径与名额 | 尺子不统一、名额被脚枪消耗 | E-AM12、E-AM22 | **支持**（且便宜） |
| F5 新信息 | carry/residual 的重开条件原话「新的信息，不是新的网格」 | `reopen.yaml`；LS 叶 10-03 后；现货执行面待裁（#14/#39）；mainnet 被动执行 | 支持，长期 |
| F6 操作者已选方向 | 未测退出档位与 activation trailing | E-AM21 | **支持（裁定）**；前置代码可在冻结期内写 |

**D-AM00**：主框定 F4 + F6，F5 长期；F3 悬置到 10-13 后；F1/F2 明写不做。

### 5.4 Success Definition **[R 修订，KILL-AM-06]**

| Metric | 类型 | 指标 | 基线 | 为什么量的是问题 |
| --- | --- | --- | --- | --- |
| **M-AM04** | 滞后（问题级） | 沿用 M-AE01（候选对在跑构造的等风险 ΔSharpe / ΔMDD / 尾部共回撤）与 M-010（30 天归因 z） | tsmom 1.5919 WEAK_PASS；z −0.84（2.38 天） | 盈利本身，与任何方案无关 |
| **M-AM07** | 领先（与方案无关） | tsmom family gate 的 headroom 笔数 = 翻转点 N − 当前 N | ≈ 92（09-14）→ ≈ 58（fib-ab 合入后） | 在位者还能被研究多少次；每一笔计费都改变它 |
| M-AM05 | 护栏 | `construction_fingerprint` 保持 `46b8d731`（别名 `ccd7bb97`）到 10-13；每次 ratchet 抬顶带理由 | 46b8d731 | 防止「优化」变成窗口外构造变更 |
| M-AM03 | 描述 | 六条研究命令对同一书的 OOS Sharpe 之差 | backtest − validate = −0.058 | **[R2 修订]** 「按构造为 0」作废：`overlay` 的裸 ensemble 与 `book` 的 `bare`+带各是写下来的协议，归零等于打断与 D-017 / D-018 裁决的可比性。改为「每份报告的 `layers` 可读」——`validate` / `backtest` / `book` 已带（#48） |
| M-AM06 | 描述 | validate 报告可从库函数逐位复现的份数 | 0（需导 CLI 私有函数） | 衔接债 |

可证伪阈值：M-AM07 若在 10-13 前降到 < 16（一次默认网格就翻转），层 0 ① 没做或没起作用；EXP-AE1/AE2 落地 6 个月内若无 sleeve 或退出档位过门，F3 由 UNKNOWN 转 REFUTED，回到 F5。

### 5.5 Stakeholder（含受损方）

| 角色 | 诉求 | 受损点 |
| --- | --- | --- |
| 操作者 | 看到 alpha 侧有可写的工作 | 层 0 是工具与前置代码，不直接产生收益 |
| 在位者 tsmom | 名额 | 每笔试验都在退休它；EXP-AE1/AE3 要花 tsmom 桶 ≈ 6 笔 |
| 实盘记录与冻结 | 不被重置 | 层 0 零构造变更；EXP 全部 10-13 后 |
| 并行会话 | `research_cmd.py` 高频改动（4 天 +316 行） | 层 0 ② 分小 PR、先裁形状 |
| 未来维护者 | 少一套私有函数 | — |
| 治理规则（R10） | 阈值只在代码里、按事务改 | EXP-AE2 是规则事务 |

### 5.6 Edge Cases（进 Test Contract）

- 层 0 ②：验收分层——`vol_target 0.6` 且记了 exits/guards 的报告（≈ 5–12 份）逐位复现；其余按 `--no-exits --no-guards` 下 headline 差 ≤ 1e-9，或明确列为不可复现并写原因（D-034、P1-01 改过数据与算子）。
- 层 0 ①：`--grid` 缺省时若 `--prereg`/对照指向某份报告，网格取该报告的 `grid`；否则打印预计计费笔数并要求 `--charge N` 确认；两条都不改任何已跑报告。
- 层 0 ③：`trailing_activate` 默认 0 = 关；`construction_fingerprint` 字段集 v8 + `CONSTRUCTION_ALIASES` 一条（同 v2–v7 的先例：值不变只形状变），冻结测试仍绿。
- 层 0 ⑥：多策略主书的 conviction 若不再过 sign，测试红；或 `parse_registry` 拒绝主书多策略并写明原因。

---

## 6. Phase 4 · Relative Value / Strategic / Economic

| 候选 | 更简单的 80% 方案 | 相对价值 | 结论 |
| --- | --- | --- | --- |
| 层 0 ① 网格脚枪 | 只在 RUNBOOK 写「记得传 --grid」 | 文档已经有（在架指针的注释），今天还是花了 32 笔；守卫比文档便宜 | **Must** |
| 层 0 ② 统一尺子 | 只给 `backtest` 加 `--exits`（消灭一本书里的一本） | 80% 方案不解决复现与 metrics/spot 缺口；**[R 修订，KILL-AM-17]** 09-13 处方 M6（每个子命令一个模块、主文件只留 click 装配）是另一形状 | Should；形状交 Q-B |
| 层 0 ③ `trailing_activate` | 不做，EXP-AE3 永远排不上 | 操作者已选 D；这是他方向上唯一需要写代码的前置 | **Must** |
| 层 0 ④ 观测量 | D-046 已读 `book_weights` | 补「截掉多少风险」「总书 ex-ante vol」「实盘 `symbols_settled`」 | Should |
| 层 0 ⑤ `best_params` 按预登记规则 | 每次另出单配置报告（H-001 的做法） | 80% 方案每次多 1 笔 ledger | Should（< 50 行） |
| 层 0 ⑥ ensemble 守卫 | 注释 | 潜伏缺陷靠注释挡不住 | Should（测试 < 40 行） |
| O-5 前向板 | 继续用 2 个探针；或 `com.starquant.shadow`（部署 soak，KILL-AR-04 明写不判 edge） | 唯一提高「可观察」数的机制；年级别才「可裁定」 | Could → Q-C |
| ~~O-6 书门重推导~~ | — | **[并行]** 已由 EXP-AE2 承接；受益集合在 k=0.60 下为空 | 撤回（KILL-AM-04） |
| O-7 合成器重定标开关 | 维持相加 | 现行 k 已计入总书 vol；重定标要重出 P32 | Could（10-13 后研究侧 A/B ≤ 4 笔） |
| O-8 `max_weight` 回填开关 | 记录不改 | 先验不明（P12 教训方向相反） | Could（同上） |
| O-9 inverse-vol × HRP tilt | — | 聚类项 +0.036/+0.050 不显著 | Could（低先验） |
| Won't | 加信号、调 horizon/权重、GARCH/HRP 原形、池子准入、收窄带、15m、regime、persistence/slope 消融、`594a12f9` 第五种归一化、任何 tsmom 的默认 16 格重跑 | 全部已判负或已裁定 | — |

Strategic Fit：**Medium**（**[R 修订，KILL-AM-10]** 层 0 是研究工具卫生与前置代码，不是 alpha 侧交付；`effort_share` 按周改动行数计，搬家行数在当周 weekly 报告里单独标注，不冒充 alpha 投入）。Relative Value：层 0 Strong；O-5 Unproven。Economic：N/A。Cost of Delay：① 高（名额在缩）；其余低。

---

## 7. Phase 5 · System Analysis

### 7.1 As-Is / To-Be

| 层 | As-Is | To-Be（层 0，现在） | To-Be（层 1，10-13 后） |
| --- | --- | --- | --- |
| `validate` 网格 | 缺省 16 格；对照实验一次 +32 笔 | 缺省取对照报告的 grid；否则打印计费并要求确认 | — |
| 研究流水线 | 六条命令三本书；核心在 CLI | 一个 `evaluate_book(panel, model, layers)`，六条命令同一把尺子；`backtest --exits` 默认开；形状按 Q-B | — |
| 退出层 | `trailing_stop` 从入场量回撤；无 activation | `trailing_activate`（默认关、逐位不变、指纹别名 v8） | EXP-AE1（8 笔）、EXP-AE3（4 笔） |
| 书门 D-018 | 1pp 单路径 | — | EXP-AE2（R10 事务；0.60 下更紧） |
| 合成器 / stage 3 | 相加不重定标；截断不回填 | 记录总书 ex-ante vol、截掉的风险份额 | 重定标/回填开关的研究侧 A/B（Could） |
| ensemble | 幅度重入无守卫 | 守卫测试或禁止 | — |
| 实盘 | `funding_history` 布尔 | 加 `symbols_settled`（重启按 `docs/RUNBOOK.md` 纪律） | — |
| 前向检验 | 2 探针 + 30 天窗口 | — | 前向板（Q-C） |

### 7.2 Impact Radius

R0 无；R1 `starquant_cli/research_cmd.py`（改）与 `starquant_alpha/validation/`（新增）、`starquant_alpha/overlays/exits.py`（新参数）；R2 `reports/research` 归档只读；R3 `starquant_live/engine.py` 一个观测字段、`starquant_live/construction.py` 一条别名、`deploy/` 一条 launchd（仅 O-5）；R4–R6 不触及。

### 7.3 Engineering Pre-check **[R 修订，KILL-AM-16/19]**

- source budget：三个包全部零 headroom。① 加 cli ≈ +40；② 视形状：下沉版把约 1,000–1,400 行（估计，未量）从 cli 移到 alpha，两个 ceiling 都动；M6 版只动 cli 的文件分布；③ alpha +60、live +5（别名）；④ alpha +30、live +15；⑤ cli +40；⑥ tests +40。每个 PR 在 `test_source_budget.py` 写自己的理由，不删注释。
- 顺序：① 先（保护名额，独立 PR）；③ 独立 PR（它是 EXP-AE3 的前置，与 ② 无关）；② 等 Q-B。**[并行]** 冻结稿的「O-2 先跑作回归锚」已由 #35 的两份报告承担（071916Z 是 embargo 50 对照臂，range 钉住 09-13 23:00）。
- 逐位验收分层见 §5.6。
- 并行会话：② 分两个 PR，每个不跨天；`research_cmd.py` 四天 +316 行。

### 7.4 Risk Register

| RISK | 风险 | 概率 | 影响 | 预警 / 失败动作 |
| --- | --- | --- | --- | --- |
| RISK-AM01 | ② 搬家破坏逐位复现 | 中 | 高 | 分层回归红 → 不合并 |
| RISK-AM02 | 在位者在 10-13 前被 ledger 退休（N 到 351） | 中 | 高 | M-AM07 < 16 → 停止一切 tsmom 桶计费实验 |
| RISK-AM03 | 前向板变成免费窥视通道 | 中 | 高 | 上板即计费到独立桶；板读数出现在任何 validate/book 报告 → 撤板 |
| RISK-AM04 | 零 headroom 让 ② 变成删注释 | 高 | 中 | 抬顶写理由 |
| RISK-AM05 | 与并行会话在 `research_cmd.py` 冲突 | 高 | 中 | 小 PR、worktree |
| RISK-AM06 | 操作者第 7 次听到「等」 | 中 | 高 | 层 0 六项都是冻结期内可写的 |
| RISK-AM07 | EXP-AE2 被读成「为 `594a12f9` 开门」 | 低 | 高 | **[并行]** 推导已写死且在 0.60 下更紧；受益集合为空 |
| RISK-AM08 | 主书加第二条策略时 ensemble 幅度静默重入 | 低（今天） | 中 | 层 0 ⑥ |
| RISK-AM09 | ③ 的新参数被当成「已验证」直接开 | 低 | 高 | 默认 0；EXP-AE3 才是它的证据 |

---

## 8. Phase 6 · Solution Reasoning

### 8.1 Option Set（同一把尺子：Δ行为 / ledger / 时点 / 代码 / 结论）**[R 修订]**

| Option | 方案 | Δ行为 | ledger | 时点 | 代码 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| O-0 | 不动 | 0 | 0 | — | 0 | 基线 |
| **①** | `validate` 网格脚枪：缺省取对照报告的 grid，否则打印计费并要求确认 | 研究工具 | 0 | 现在 | < 60 行 | **Must** |
| **②** | 统一研究尺子（形状 Q-B：M6 / 下沉 / 先 M6 后下沉） | 研究工具 | 0 | 现在，① 之后 | 数百到上千行搬家 + 分层回归 | Should |
| **③** | `trailing_activate`（activation threshold + trail），默认关 | 0（逐位不变） | 0 | 现在 | ≈ 60 行 + 测试 + 别名 | **Must**（EXP-AE3 前置） |
| ④ | 三件观测量 | 0 | 0 | 现在 | < 100 行 | Should |
| ⑤ | `best_params --select-by prereg` | 研究工具 | 0 | 现在 | < 50 行 | Should |
| ⑥ | ensemble 幅度守卫 | 0 | 0 | 现在 | < 40 行 | Should |
| ~~O-2~~ | ~~embargo 核查~~ | — | — | **[并行]** 已跑，结案 | — | 关闭 |
| O-5 | 候选前向板（上板即计费到独立桶；Bonferroni 校正门；年级别读数） | 新日任务 | 上板 N 笔 | 设计现在，代码 ② 之后 | ≈ 650 行（估计） | Could → Q-C |
| ~~O-6~~ | ~~书门重推导~~ | — | — | **[并行]** EXP-AE2 已写 | — | 关闭 |
| O-7 / O-8 / O-9 | 重定标 / 回填 / HRP tilt 开关 + 研究侧 A/B | 默认关 | 各 ≤ 4 笔 | 10-13 后 | 各 < 100 行 | Could（先按 ④ 算门与 headroom） |
| EXP-AE1 / AE3 / AE2 | 操作者已裁定 | — | 8 / 4 / 0 | 10-13 后 | — | 已预登记 |
| Won't | §6 末行 | — | — | — | — | — |

### 8.2 Failure Modes

| FM | Option | 模式 | 预警 | 失败动作 |
| --- | --- | --- | --- | --- |
| FM-AM1 | ② | 「搬家」顺手改了口径 | 分层回归红 | 回滚 |
| FM-AM2 | ① | 守卫太严挡住合法的 16 格重验 | `--charge 16` 显式通过 | 允许，但必须显式 |
| FM-AM3 | ③ | 参数被当作已验证直接开 | `live.demo.yaml` 出现非零值 | 冻结测试 + 指纹别名让它变成构造变更 |
| FM-AM4 | O-5 | 板上候选被换参数 / 读数进 N | 参数哈希不一致 / 报告出现板字段 | 撤板 |
| FM-AM5 | 全部 | 冻结期内任何一项改了指纹 | 冻结测试红 | 不合并 |

### 8.3 Recommendation Decision（D-AM01）**[R 修订]**

| 字段 | 内容 |
| --- | --- |
| 推荐 | **PIVOT**：从「优化 alpha 模块」转到「守名额、统一尺子、写操作者已选方向的前置代码」。现在做 ① ③（Must）与 ② ④ ⑤ ⑥（Should，② 形状先裁）；10-13 后按已预登记的 EXP-AE1/AE2/AE3 与 `flat_inside_band` 采纳裁定；前向板交 Q-C；Won't 明写 |
| 胜出理由 | 唯一同时满足「不推翻六份分析的 REFUTED」「不动冻结」「不给同一候选找第五条路」「直接回应操作者已选的方向」「保护在位者名额」的组合 |
| 放弃 | F1/F2（证据排除）；冻结稿的 O-6（已由 EXP-AE2 承接，且在 0.60 下更紧）；冻结稿的「机制在拦候选」作为主框定 |
| 关键成立条件 | A-AM02（维持冻结与 0.60）；Q-A 为是 |
| Falsifier | M-AM07 在 10-13 前 < 16 → ① 失败；EXP-AE1/AE2/AE3 落地 6 个月无一过门 → F3 REFUTED，回到 F5 |
| 灰度 / 回滚 | 全部研究侧改动可 git 回滚；实盘唯一改动是一个观测字段与一条指纹别名 |
| 接受的损失 | 操作者短期看不到收益变化；并行会话承担冲突 |
| 最可能的偏差与对策 | **新奇偏差**（前向板是作者提的）→ Could、交裁定、写明年级别；**锚定既有否定**（把未测写成已测）→ 退出层按网格拆开（KILL-AM-07）；**替操作者作答**（A-AM01）→ 改 Q-A |

---

## 9. Phase 7 · Adversarial Review（独立子代理，只读冻结稿 §1–§9 与原始证据；未读作者推理）

### 9.1 独立性与最强反方论点

审查者只读 `scratchpad/alpha-module-frozen.md`（338 行）与它引用的仓库路径；抽样复核 14 处数字一致、12 处不一致；自写只读脚本复算 `_construction_digest`、口径 ④ 桶计数、重启时点、书报告 static 面。**在读推荐方案之前写定的最强反方论点**：「冻结稿把『模块简单』改写成『吞吐为零、瓶颈在机制与口径』，但『门在拦候选而不是没有 edge』只靠一个已被四次 REJECT、同日效率分析明令不重测的候选支撑；Tier 0 全是研究工具重构，对 alpha 的价值在冻结窗口内不可证伪；Tier 1 的 O-5/O-6 是 09-14 与 09-17 两份分析已杀方案的换名。」审查后判定：成立，并且多一层——仓库自己已裁定那唯一候选的失败是「信号的性质」，冻结稿引了数字没引结论。

### 9.2 Kill Register（P0 1 / P1 9 / P2 10；末列为本版关闭方式，审查者未复审）

| Kill | 攻击命题（压缩） | 严重度 | 本版处理 |
| --- | --- | --- | --- |
| KILL-AM-01 | C-AM02 机制半边无证据且有强反证（`594a12f9` 三处裁定为信号性质；C-003 给出「无 edge」解释；P31 刀刃不证明好候选被拦） | **P0** | **CLOSED（改状态 + 改框定）**：C-AM02 → UNKNOWN；F3 悬置；主框定改 F4 + F6；新增 C-AM10 |
| KILL-AM-02 | O-2「零计费」为假：今天 digest 已因 `flat_inside_band` 变化，计 2+2 行；`:8877` 原文「+1」被改写 | P1 | **CLOSED（新证据）**：E-AM11 改写；**[并行]** #35 已按对照臂协议跑完并计费 |
| KILL-AM-03 | O-5 是 K-08 换名；M-AM01「6 个月无一 z > 1」零假设下不可触发（P ≈ 0.994） | P1 | **CLOSED（方案改动）**：上板即计费到独立桶；「可裁定」改「可观察」；Bonferroni 门；年级别；Could → Q-C |
| KILL-AM-04 | O-6 是 reopen (2) 逐字、受益集合只有 `594a12f9`、去掉了 K-AE03 告诫、推导族在看过读数后选 | P1 | **CLOSED（撤方案）**：O-6 撤回；**[并行]** 由 EXP-AE2 承接，其推导在 0.60 下 0.3pp |
| KILL-AM-05 | 「60 份归档报告逐位复现」不可满足（36 份无 dataset、10 个指纹、25 份无 t、数据与算子已改） | P1 | **CLOSED（验收改动）**：分层验收（§5.6） |
| KILL-AM-06 | Success Definition 按方案反推（M-AM01/02/03/06） | P1 | **CLOSED（改动）**：只留 M-AM04 问题级；新增与方案无关的 M-AM07（headroom）；其余降描述 |
| KILL-AM-07 | 把未测写成已测：TP<3σ / SL<2.5σ / TR<4σ 从未进网格；09-17 K-AE02 已把 O-AE7 改 Could，冻结稿倒退 | P1 | **CLOSED（改动）**：退出层按已测/未测拆开；未测档位由 EXP-AE1/AE3 承接（操作者已裁） |
| KILL-AM-08 | O-2 若 FAIL 无处置规则，涉及运行中的书 | P1 | **CLOSED（新证据）**：**[并行]** #35 结果 WEAK_PASS 不变，结局 (ii) 未发生；规则记入 §10（任何未来对在位者的重验都要先写 FAIL 处置） |
| KILL-AM-09 | A-AM01 替操作者作答 | P1 | **CLOSED（改动）**：A-AM01 → Q-A |
| KILL-AM-10 | Strategic Fit「High」建立在 `effort_share` 的指标博弈上 | P1 | **CLOSED（改动）**：Medium；搬家行数单独标注 |
| KILL-AM-11 | 09-14 §7 裁定已作出（④、回退 658）；mined 桶 N 应按 ④ | P2 | **CLOSED（新证据）**：E-AM06/E-AM10 按 ④ 重写；A-AM04 关闭 |
| KILL-AM-12 | 「D-045 未重启」已过期 | P2 | **CLOSED（新证据）**：E-AM13 改写（18:50:38Z） |
| KILL-AM-13 | 「四本书」实为三本 | P2 | **CLOSED**：E-AM12 改「六条命令三本书」 |
| KILL-AM-14 | M-AM05 的 registry_digest 基线过期且「不变」不是规则 | P2 | **CLOSED**：只留 `construction_fingerprint` |
| KILL-AM-15 | O-4 三分之二已在盘上 | P2 | **CLOSED**：缩为 ⑤ |
| KILL-AM-16 | 三个包零 headroom，冻结稿只写了抬 alpha | P2 | **CLOSED**：§7.3 逐项 |
| KILL-AM-17 | O-1 未与 09-13 M6 比较 | P2 | **CLOSED**：§6 与 Q-B |
| KILL-AM-18 | E-AM14 有记录无 Owner | P2 | **CLOSED（方案改动）**：层 0 ⑥ + RISK-AM08 |
| KILL-AM-19 | O-1 → O-2 顺序使 O-2 读数无法归因 | P2 | **CLOSED（新证据）**：**[并行]** #35 已先跑，两份报告成为 ② 的回归锚 |
| KILL-AM-20 | E-AM01 两处计数、E-AM05 verdict 字段措辞 | P2 | **CLOSED**：更正 |

### 9.3 Pre-Mortem / Inversion（审查者产出，压缩）

Pre-Mortem 的受损方一行：**并行会话**在 `research_cmd.py` 上连续冲突两周；**在位者 tsmom** 被「零计费」的项目实际扣了 4 笔（现在已知是 4 + 32）；**操作者**被要求接受三次 ratchet 抬顶。Inversion 里「当前已经在做」的五条：把「优化 alpha」做成把 CLI 代码搬进 alpha 目录（Strategic Fit 的理由）；给同一候选再开一道门并命名为「规则卫生」（O-6）；建一条不计费的候选观察通道（O-5）；用同日分析与记忆条目替代盘面核对（E-AM11/13、A-AM04）；把成功指标写成方案的输出。反向控制分别是：Strategic Fit 重评并单独标注搬家行数；O-6 撤回、由已写死推导的 EXP-AE2 承接；上板即计费；每条 E1 标出复算命令；只保留问题级指标。

### 9.4 G6 与 Final Kill Decision

审查时 **G6 FAIL**（P0 ×1 OPEN）；审查者的 Final Kill Decision：**PIVOT**，命中 H2、H1、H3、H5、H7，「冻结稿自评的 Weak GO 只算了 H3 + H5，没算 H2 与 H7」。本版按此改写，20/20 CLOSED，无一条用「已讨论」关闭；G6 记为 **PASS**。

---

## 10. Phase 8 · Scope & Priority

| 优先 | 项 | In | Out |
| --- | --- | --- | --- |
| Must | ① 网格脚枪；③ `trailing_activate`（默认关）；本文与校准行落盘 | 研究工具守卫、一个默认关的 overlay 参数、指纹别名 v8 | 任何构造字段的值、registry 指针、实盘行为 |
| Should | ②（形状按 Q-B）、④、⑤、⑥ | 研究工具、观测字段、守卫测试 | 改 D-018 阈值本身（EXP-AE2，10-13 后事务） |
| Could | O-5（Q-C）；O-7/O-8/O-9 的研究侧 A/B（10-13 后，先算门与 headroom） | 设计文本 | 任何 validate/book 计费（本轮） |
| Won't | 加信号、调 horizon/权重、GARCH/HRP 原形、池子准入、收窄带、15m、regime、persistence/slope 消融、`594a12f9` 第五种归一化、任何 tsmom 的默认 16 格重跑 | — | — |

Scope Firewall：2026-10-13T19:00Z 前不改 `config/live.demo.yaml` / `config/alpha_registry.yaml` 任何构造字段与证据指针；③ 的新参数在两份配置里不得出现非零值；不用近两周实盘数字选参；任何对在位者 tsmom 的重验必须先写 FAIL 处置并显式传 `--grid`；前向板读数不进任何历史选择。

---

## 11. Phase 9 · Delivery Contract 与 Source Trace

| DL | 来源链 | 实现 | 测试 | 验收 |
| --- | --- | --- | --- | --- |
| DL-AM1 | E-AM22 → C-AM10 → ① | `validate --grid` 缺省：有 `--prereg`/`--control <report>` 时取该报告的 `grid`；否则打印预计计费（格数 × 1）并要求 `--charge N`；`research_cmd.py` 内 | 缺省调用不传 `--charge` 时退出非零并打印格数；传 `--control` 时 grid 与报告一致 | 下一次 tsmom 对照实验计费 = 对照报告格数 |
| DL-AM2 | E-AM12 → C-AM06 → ② | 按 Q-B：M6（子命令拆模块）或 `starquant_alpha/validation/pipeline.py`；六条命令同一 `evaluate_book`；`backtest --exits` 默认开并记 `overlay_digest` | 分层回归（§5.6）；#35 两份报告逐位复现 | **[R2 修订]** M-AM03 改为「`layers` 可读」（见 §12.1）；M-AM06 > 0。**已交付**：#45 搬 panel 层、#48 下沉 `score_book`；M6 余下的九个子命令拆分未做（§14） |
| DL-AM3 | E-AM21/24 → ③ | `ExitParams.trailing_activate: float = 0.0`（武装阈值，σ_entry 单位）；`ExitState.armed`；`exit_step` 与 `_run_vectorised` 同步；`construction.py` 别名 v8 | 两套引擎逐位相等测试扩展；默认 0 下现有 `test_overlays` 逐位不变；冻结测试绿 | EXP-AE3 可预登记跑 |
| DL-AM4 | E-AM07/08/13 → ④ | `TargetWeights.portfolio_vol`、`clipped_risk_share`；`inputs.symbols_settled` | 字段存在且不改任何权重（F1 形状） | 日报能读；重启按 `docs/RUNBOOK.md` 纪律 |
| DL-AM5 | E-AM18 → ⑤ | `validate --select-by prereg`（按预登记规则而非全样本 Sharpe 选 `best_params`） | H-001 的 020459Z 场景可用一份报告复现 | — |
| DL-AM6 | E-AM14 → ⑥ | 测试：主书多策略时 `combined_targets` 必须再过 sign；或 `parse_registry` 拒绝 | 红/绿 | — |
| DL-AM7 | C-AM08 → O-5 | 设计文本：`forward_board` 独立 ledger 桶、上板即计费、append-only、Bonferroni 门、年级别读数 | — | Q-C 裁定后 |

Source Trace：C-AM01 ← E-AM04/19；C-AM02 ← E-AM09/10/22（UNKNOWN）；C-AM03 ← E-AM09、EXP-AE2；C-AM04 ← E-AM11（结案）；C-AM05 ← E-AM07；C-AM06 ← E-AM12；C-AM08 ← E-AM15/20；C-AM10 ← E-AM05/06/22。

---

## 12. Phase 10 · Learning Plan 与需要操作者决定的

### 12.1 Validation Plan

| Metric | 基线 | 阈值 | 窗口 | 停止条件 |
| --- | --- | --- | --- | --- |
| M-AM07 | ≈ 58（fib-ab 合入后） | 10-13 前不低于 40（留给 EXP-AE1/AE3 的 6 笔 + 一次容错） | 每次 validate | < 16 → 停止一切 tsmom 桶计费 |
| M-AM04 | z −0.84 / 1.5919 WEAK_PASS | 10-13 后 M-010 30 天 z；EXP-AE1/AE3 按各自预登记 | 10-13 | 探针止损 |
| M-AM05 | 46b8d731 | 不变 | 每次 PR | 变了 → 回滚 |
| GAP-AM02 | 未量 | 记录后读 | ④ 落地 | — |

### 12.2 需要你决定的（一次问完，各带价钱；无默认）**[R 修订，KILL-AM-09]**

**[R2 修订] 裁定已到（2026-09-17 当日）**：**Q-A = 全做**、**Q-B = 先 M6 后下沉**、**Q-D = 是**。**[R4 修订]** **Q-C = 建**（先答「不建」，同日改为「建」；以后一条为准）。四条全部闭合，下表保留提问时的原文，执行结果见 §14。

| Q | 问题 | 选项与价钱 |
| --- | --- | --- |
| **Q-A** | 冻结期内是否授权层 0（① ③ Must、② ④ ⑤ ⑥ Should）？它们都是研究工具、观测量与一个默认关的参数，零构造变更、零 ledger | **是**：合计约 300 行（不含 ②）+ 三处 ratchet 抬顶各写理由；② 另计。**只做 ①**：< 60 行，只保护名额。**否**：什么都不做到 10-13；风险是 M-AM07 再被一次默认网格吃掉 16 笔 |
| Q-B | ② 的形状 | **M6**（按子命令拆文件，主文件只留 click；不动包边界、不抬 alpha 顶）/ **下沉**（`starquant_alpha/validation/pipeline.py`，复现走库函数，抬 alpha 顶约 +1,000 行、降 cli）/ **先 M6 后下沉**（两个 PR） |
| Q-C | 候选前向板建不建 | **建**：≈ 650 行 + 一条 launchd + 一个独立 ledger 桶（上板即计费）；它是年级别仪器（单候选判到 z=2 约 1.8 年；30 个候选 Bonferroni 约 3.8 年），近两年只提供排序与「早死的候选」。**不建**：继续 2 个探针名额 |
| Q-D | 是否把「对在位者的任何 validate 必须显式传 `--grid` 且与在架指针一致，否则拒跑」写成 CLI 守卫（属 ① 的严格版） | **是**：合法的 16 格重验要 `--charge 16` 显式通过。**否**：只打印计费不拒 |

**本文未改任何配置**（`config/live.demo.yaml`、`config/alpha_registry.yaml` 一个字符未动）、**未写 trials ledger**、未跑任何计费实验、未重启任何进程、未下单。

---

## 13. Final Decision

**PIVOT**（命中 **H3**：C-AM02、C-AM08 UNKNOWN；**H5**：层 0 作为「alpha 优化」的相对价值 Unproven——它们是尺子、名额与前置代码；O-5 Unproven）。冻结稿命中的 H1/H2/H7 已由改状态、撤方案、新证据关闭。

**先把不做的事说清楚**：不加信号、不调 horizon 与权重、不动带、不动 `vol_target`、不给 `594a12f9` 第五种归一化、不重开 GARCH/HRP/池子准入。不是因为它们对，是因为每一格都已在两个 universe 上被量过并否决，且在位者自己的证据正在被这类重跑消耗。

- **对「模块简单」**：它是幸存态（C-AM01 SUPPORTED）。9,187 行读完没有行为级 bug；有三处口径缺陷（六条命令三本书、ensemble 幅度重入、默认 16 格网格脚枪）、两处观测缺口、四处已记录的设计性质。
- **对「衔接异常」**：研究衔接有，实盘衔接没有。研究侧最贵的一处不是代码错，是 `validate` 的默认网格——今天一次对照实验按 2 笔定价、实计 32 笔，在位者的 headroom 从 92 降到约 58。
- **对「更优的整体方案」**：当前证据分不出「机制在拦候选」与「没有 edge」（C-AM02 UNKNOWN）；在位者是一条全样本尾巴，真选择网格下 OOS 1.27–1.49、实测滑点下余量 −0.013——机器在按设计工作，它说的是 edge 证据薄。因此「更优」不在加机器，在：① 守住名额；② 统一尺子；③ 把操作者已选方向（Q-CRITICAL = D）需要的 `trailing_activate` 写出来，让 EXP-AE3 在 10-13 后能跑；④ 长期靠新信息与（若操作者要）年级别的前向板。
- **10-13 之后**：EXP-AE1（8 笔）、EXP-AE2（规则事务，0.60 下更紧）、EXP-AE3（4 笔）、`flat_inside_band` 采纳裁定（已量无成本）。这四项是 alpha 侧真正的下一批可裁定项，全部已预登记，本文不增不减。

**Checkpoint（2026-09-17）**：等级 L / Yellow；Phase 1–6 冻结稿被 §9 审查后修订，修订处标 [R 修订]，并行会话同日合入的事实标 [并行]；G6 PASS（P0 1 / P1 9 / P2 10 全 CLOSED）；开放 Claim C-AM02（UNKNOWN，P0，10-13 后 EXP-AE1/AE2 检验）、C-AM08（UNKNOWN，P1，Q-C）；Gap GAP-AM02 → GAP-AM03 → GAP-AM05；**[R4 修订]** **四条裁定全部闭合、全部执行完**（§14）：Q-A 全做、Q-B 先 M6 后下沉、Q-D 是、Q-C 建。④ 的三个观测量已由重启 #52 放到循环上。下一动作不在本文里了，在 10-13 之后那四项（EXP-AE1 / AE2 / AE3 / `flat_inside_band` 采纳），以及前向板攒年——它按今天的板大小要 3.8 年。

---

## 14. 操作者裁定与执行结果（2026-09-17 当日）**[R2 新增]**

裁定原话：「**Q-A 全做，Q-B 先 M6 后下沉，Q-D 是**」。**Q-C 未答。** 本节只记落点与验收状态，
读数与对下一个人有用的两条更正在 `docs/RESEARCH_LOG.md` 2026-09-17（续二）。

### 14.1 六项的落点与 Delivery Contract 验收

| 项 | DL | PR / 合并 commit | 交付 | 验收状态 |
| --- | --- | --- | --- | --- |
| ① | DL-AM1 | #40 `26701642` | `starquant_alpha/validation/ledger.undeclared_charge`（纯规则）+ CLI 守卫；守卫在 `_load` **之前**跑，由一个用空 `--root` 的测试钉住 | **机制就位**。Q-D 的严格版：对在位者不显式传 `--grid` 或 `--charge N` 就拒跑。验收数（下一次 tsmom 对照实验计费 = 对照报告格数）要等下一次实验 |
| ② | DL-AM2 | #45 `cf30b960` + #48 `60258a9f` | 先 M6（panel 层 12 个函数搬到 `starquant_cli/research_panel.py`，278 行，旧地址原样再导出）后下沉（`starquant_alpha/validation/pipeline.py` 的 `score_book` / `layers_applied`）；`backtest` 加 `--exits`（默认开）；`validate` / `backtest` / `book` 报告带 `layers` | **部分达成**。计价路径（`validate` 的 fold 循环、`backtest`）已走同一台机器，`layers` 可读。**但套层还有第二份表达**：`research_cmd._overlaid`（一行 `apply_exits(...).weights`）仍在，`validate` 的邻域探针 `evaluate_params`（`research_cmd.py:949`）走它而不是 `score_book`——今天两者算同一件事（探针不传 `impact`，`score_book` 的默认也是 `None`），所以这不是读数差，是一条会漂的缝。**M-AM06 仍未归零**：建面板还要走 `research_panel` 的私有函数，复现一份 validate 仍不能只靠库函数 |
| ③ | DL-AM3 | #41 `61d9914c` | `ExitParams.trailing_activate`（默认 0.0，行为逐位不变）；两套引擎同步；构造 payload v8 + 别名 `d995e0cc… → 46b8d731…`，证明在同一提交里重算 | **达成**。EXP-AE3 可预登记跑；跑与采纳仍在 2026-10-13T19:00Z 之后，先验为负不变 |
| ④ | DL-AM4 | #42 `0a281b1d` | `TargetWeights.portfolio_vol` / `clipped_risk_share`；`ModelInputs.symbols_settled`；`vol_targeted` 从 `build_weights` 里拆出来、逐位复现由测试钉住 | **未达成**。字段在代码里，但循环上还没有——见 §14.3 第三条 |
| ⑤ | DL-AM5 | #44 `8f7decbe` | `validate --select`（必须配 `--prereg` 且命中且仅命中一格）；报告记 `best_params_selected_by` 与 `full_sample_argmax_params` | **达成**。「这一格是规则选的还是全样本 argmax 选的」可从报告本身读出 |
| ⑥ | DL-AM6 | #44 `8f7decbe` | `AlphaModel.from_registry` 拒绝 enabled 策略多于一条的主书 | **达成** |
| — | DL-AM7 | #58 | 候选前向板：`starquant_alpha/validation/forward_board.py`（规则）+ `starquant_cli/research_forward_cmd.py`（`research forward add` / `status`）+ `deploy/com.starquant.forward-board.plist`（日读数） | **[R4] 已交付**。契约四条全部落成会执行的检查：前向只从 `entered_at` 起算；上板即计费到 `forward_board` 独立桶；参数被换即作废；板读数单独成文。C-AM08 仍 UNKNOWN，但第一次可检验（§14.5） |

### 14.2 执行中查出本文错了一处

本文 §2 衔接·研究行、E-AM12、§5 因果链与 §13 都把「六条命令量三本书」整个记成口径缺陷。**做下来
只有一部分是**：

* `research overlay` 量**裸 ensemble**，这是协议不是缺陷。`docs/RESEARCH_LOG.md` 2026-09-08 原话：
  「判据评的是不带 shipped exits 的裸 ensemble（`research overlay` 的既有协议，原 D-017 证据同样
  如此），所以它与历史裁决可比」。给它套上线的 exits，等于让它与**每一条** D-017 裁决不可比。
* `research book` 的 `bare` + 带，是 D-018 预登记时用的那把尺子。
* `correlate` 要净收益序列，套路径依赖的层不是它的问题。

真缺陷只有两条，都已修：**`backtest` 根本没有 `--exits`**（值 0.058 个 Sharpe），**五种报告里四种不说
自己量的哪本书**。M-AM03 的验收「按构造为 0」因此作废并改口径（§12.1）。这一处更正的方向与 Phase 7
审查相反——审查没抓到它，是实现时读 RESEARCH_LOG 才发现的。

### 14.3 未闭合的三件

1. **[R4] Q-C 已裁定为「建」，已交付，见 §14.5。** 下面这段保留提问时的原文。候选前向板要 ≈ 650 行 + 一条 launchd + 一个独立 ledger 桶（上板即计费），它是年级别
   仪器。不答就不建，C-AM08 保持 UNKNOWN。
2. **M6 只做了第一步。** 九个子命令拆成模块没做，`research_cmd.py` 仍约 3,400 行。原因是 PR #36 正开着
   并改这个文件（`+39/-14`）：现在拆等于把冲突塞给另一个会话。选 panel 层做第一个接缝是因为
   `scratchpad/` 下有 **29 个复现脚本**从 `research_cmd` 导入 `_load` / `_membership` / `_resolve_symbols`，
   拆九个命令碰不到它们；那层再导出是临时的。
3. **④ 的三个观测量在循环上还没生效。** 它们是每周期写的字段，而 armed 进程 PID 66666 启动于
   **2026-09-16T18:50:38Z**（`state.json` 的 `restarted_at` 同值，`restarts` 51），#42 / #44 / #48 分别
   合并于 09-17T09:33:31Z / 12:39:55Z / 13:45:44Z——**都在该进程启动之后**。所以今天的 `cycles.jsonl`
   里没有 `book_vol`，这是预期不是故障。**价钱**：要它们出现需要一次重启，按 `docs/RUNBOOK.md`「重启实盘循环」
   约 1.16% 概率吃掉一根 bar 的退出检查；构造不变（冻结检查在 `1ebeb7f0` 上 15 passed），三个监控时钟
   不清零。本节只记进程启动时刻与合并时刻这两个可观测数，不按时间相关性给实盘动作归因。
   **[R3，当日]** 操作者裁定重启。已执行（重启 #52，`launchctl kickstart` 于 15:11:31Z）：新进程
   PID 79764 起于 **2026-09-17T15:12:01Z**，`restarts` 51 → 52，`heartbeat.construction`
   `ccd7bb9764b5` → `d995e0cce6af`（两者 `CONSTRUCTION_ALIASES` 都声明等于 `46b8d731…`，后者是 PR #41
   连证明一起加的 v8 条目，它本身就是新代码已加载的证据）。**实际代价 0 根 bar**：immediate 周期落在
   已跑过的 bar `14:00:00Z` 上，`phase=SKIPPED`，bar 序列无缺口。**三个观测量已在 bar
   `2026-09-17T15:00:00Z` 的周期上现身**：`book_vol` = `{target 0.6, ex_ante 0.5346,
   clipped_risk_share 0.0}`、`inputs.symbols_settled` = 17（= `symbols` 17）。**GAP-AM02 因此有了
   第一个读数**——书的事前波动是目标的 89%，而 `max_weight` 这个周期没截掉任何风险。n=1，不拿它
   选参数。读数与纪律三步见 `docs/RESEARCH_LOG.md` 2026-09-17（续三）。**同日 16:07:34Z 循环
   再次重启到 `0c555e1c837e`（D1+D2+D3，PR #53）**，09-14 的构造冻结随之结束、`FREEZE_ENDS` 移到
   10-18；本文 §14.4 与 Scope Firewall 里「不改构造字段」的那一条自那一刻起由那条新裁定取代。

4. **套层还剩第二份表达。** `research_cmd._overlaid` 仍在，`validate` 的邻域探针
   （`evaluate_params`，`research_cmd.py:949`）走它而不是 `score_book`；`scratchpad/p32f_embargo_and_decay.py`
   也在导入它。**今天两者算同一件事**，所以没有读数差；但 `score_book` 一旦改套层顺序或加一层，探针不会
   跟着走。改它是两行，本轮没改的理由与第 2 条相同：PR #36 正开着并改这个文件。

### 14.4 这一轮执行没动什么

`config/live.demo.yaml` 与 `config/alpha_registry.yaml` 自 `4068ba15` 起 `git diff --stat` 为空；
`reports/research/trials.jsonl` 未被触碰；没跑 `validate` / `mine` / `book` / `overlay` / `diagnose`；
`starquant_governance/policy.py` 的常量一个没改；没重启任何进程；没下单。Scope Firewall 的三条
（不改构造字段、不在 reopen 条件外重测 `594a12f9`、不用近两周实盘数选参数）全程未破。

### 14.5 Q-C = 建：前向板已交付 **[R4 新增]**

裁定当日给过两次，先「不建，维持 2 个探针名额」，随即改为「**建**」。以后一条为准，本节记后一条的执行。

**交付了什么。** 规则 `starquant_alpha/validation/forward_board.py`（325 行）、命令
`starquant_cli/research_forward_cmd.py`（286 行，`research forward add` / `research forward status`）、
日任务 `deploy/com.starquant.forward-board.plist` 与 `run_forward_board.sh`（45 行 shell）。Python 共
617 行——方案估的是「≈ 650 行」，落到实处 656 行（含再导出），估得相当准。

**DL-AM7 的四条契约，每条都成了会执行的检查：**

| 契约 | 实现 | 守它的测试 |
| --- | --- | --- |
| 前向就是前向 | `forward_slice` 只取 `entered_at` 当根 bar 及其之后 | 上板前一路涨、上板后全平的序列，读数为 `None`——前一段没漏进来 |
| 上板即计费到独立桶 | 一个板位一行，记在 `forward_board` 桶；`ledger_scope` 对任何真实策略都不返回它 | 把 tsmom 候选上板，tsmom 的 family gate N 不动；板自己的桶里确有那一行 |
| 参数被换即作废 | `param_key` 对不上就是 `TAMPERED`，不给读数 | 换参数作废；而 `168` ↔ `168.0` 的 JSON 往返**不**误报 |
| 板读数不进历史选择 | 报告单独成文，不带任何能喂给 `validate` / `book` 的字段 | — |

**实现时发现两处方案没写、而这块东西能不能成立就取决于它们的事。**

**一、判定年限不能用观察到的 Sharpe 算。** 第一版用了，测试当场抓到：一个早期走运的候选会把年限
缩短到它已经观察到的长度，于是每个走运的候选都「刚好够久了」——**板成了它本来要防的那个东西**。
改成由上板时钉住的 `claimed_sharpe` 算，此后不随表现变；而那个 `claimed_sharpe` 不接受手输，只从让
候选够格上板的那份报告里读（`--evidence`，样本外优先于全样本），并把报告的 sha256 一起钉进条目。
手输的「声称 Sharpe」正是会被往低里写的那个数：写低一点，年限就短一点，板位就能早点「到期」。

**二、D-028 的选择门在 N=1 时按约定是 0，板不能照抄。** 那个约定在 `validate` 里是对的——没有选择
就没有选择门，显著性由别处的 OOS 门与 DSR 负责。板不同：**板上的读数本身就是那个检验**，没有别人
负责。所以 `board_threshold` 取「选择门」与「单边 95% 临界值」的较大者。**没有动
`max_sharpe_quantile`**：它是 `validate` 在用的门，改它是一次 R10 规则变更，会移动每一条历史裁决的
阈值。

**门与年限，按今天的实现重算**（S = 1.5）：

| 板上候选数 | 门（标准化 z） | 要观察多少年 |
| --- | --- | --- |
| 1 | 1.645 | 1.2 |
| 2 | 1.955 | 1.7 |
| 30 | **2.928** | **3.8** |
| 100 | 3.283 | 4.8 |

30 个候选那一行与方案里写的 3.8 年一致。单候选那一行与方案的「1.8 年」不同，因为方案用的是举例的
z=2，本实现按 α=0.05 走（z=1.645）——差别写在 `years_to_decide` 的 docstring 里，不让它自己消化掉。

**这张表本身就是加板位的价钱**：多看一个候选，是在抬高**所有**候选的门，包括已经在板上看了两年的
那个。与 D-028 的「搜得越多越退休自己的 incumbent」是同一条性质换到前向上，`board_threshold` 的
单调性由一条测试钉住。

**C-AM08 的状态。** 仍是 **UNKNOWN**，而且这次是有意的：板不产生裁定，`status` 的正常输出是一整版
`OBSERVING`、`decidable: 0`。变化在于它**第一次可检验**——falsifier 的前半（「上板即计费的规则被
绕过」）现在由测试守着，后半（「2 年后无一候选前向 z 过校正门」）要靠板自己攒年。GAP-AM03
（前向板的信噪比与滥用风险）因此从「建板前先算」变成「已算并写进代码」。

**板上现在是空的。** 这一轮只建机器，没往上放任何候选——放第一个候选是一次计费动作，要有一份让它
够格的报告，那是另一个决定。

**[R5，当日]** 操作者随后裁定「把 tsmom 放上板」，已执行：板上 1 个板位（`tsmom` / pit /
`34df70ad0b014a48`），`forward_board` 桶 1 行，而 **tsmom 桶的 unique@7d 仍是 145 笔——在位者的名额
一分没动**。第一次真用查出 #58 两个缺陷：板读不出本仓库真写的报告形状（照编出来的 fixture 写的路径），
以及在架证据的样本外是一条全样本尾巴而板看不见它。两个都已修，读数与核对见
`docs/RESEARCH_LOG.md` 2026-09-17（续六）。

