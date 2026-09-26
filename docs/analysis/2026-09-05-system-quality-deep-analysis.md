# 深度分析：StarQuant 全系统质量体检、开源对标与提升方案（2026-09-05；2026-09-06 按独立复核修订）

> **修订记录（2026-09-06）**：附录 C 的六角色独立对抗复核完成后，本文件按其 29 条 Kill 修订。被推翻并已改写的结论：头号 P0 的对象（实盘循环仍在跑 crowding 0，registry 已指向 crowding 72——一条 KILL-027 形状的分叉，比横截面总体问题更紧急）、F1 处方里的"holdout 必选"（与操作者裁决 KILL-006 冲突，撤回）、L1-01 的归因（73% 是开发期 flatten→重启的产物，稳态 0/8）、外部看门狗的可交付性（心跳为本机文件、崩溃循环刷新心跳、无 reduce-only 作用域 key）、原生灾难止损的可下单性（18 币中 7 个在 18 日波动单位处价格 ≤ 0）、mainnet 前提项混入 12 周路线图、alpha 占比未按仓库仪表口径计算。新增一次 scratch 网格验证（E-36）：在当前构造下诚实的 16 点网格走前 OOS 为 1.485，5% FWER 阈值（N=93…110）为 1.445…1.466，tsmom 以 0.02–0.04 的 headroom 通过。修订处均以「**[C 修订]**」标出；未标记的段落保持 09-05 原文。
>
> 分析头部（deep-analysis V3.3 + backtest-guard 两遍审查）
> - Reading Check：本次理解为「对 StarQuant 做一次全系统质量体检并给出提升方案：与开源同类系统对照评分；重点回答 alpha 供给（策略/因子稀少、挖掘能否自动化或交给 LLM）、三个自适应层（杠杆 / 下单量 / 止盈止损）的优化空间，以及止盈止损应走交易所条件单还是保持 bar 收盘软件层；交付对象是单一操作者，目标是把系统从"能跑的 demo"推到"可托付真实资金"」。最高风险预设为 Pre-1「因子挖掘没有实现、alpha 的瓶颈是候选供给」；若该预设不成立（仓库已有挖掘器、225 个候选全部阴性、P17 已把瓶颈改判为"可表达空间与数据宽度"），方案方向从"造一个挖掘器 / 接 LLM"变为"扩叶节点与数据源，再让现有挖掘器与 ledger 去审"。
> - Interaction Mode：**Yellow**。关键事实全部可由代码、配置、研究日志、实盘状态文件取证（E1）；外部事实（同类系统、币安 API、文献）由网络取证（E3/E4）。操作者的三条前提与仓库记录有出入，但不改变框架方向，不需要提问。
> - S/M/L：**L**。命中：≥3 模块（alpha / data / live / exchange / cli）；触及资金链路（下单、止损、杠杆）；AI/策略/自动化维度为"自主决策 + 生产影响 + 难回滚"（挖掘结果一旦进入 ledger 即改变后续 DSR 分母）。
> - 当前 Gate 决策上限：**Weak GO（受控执行）**——demo 继续运行；**真实资金：HOLD**（且按操作者现行范围为 DEFERRED，不在 12 周路线图内）。**[C 修订]** Weak GO 授权的具体动作重新绑定到修订后的 §9：Phase A 的第 0 步是"任何重启之前使 registry、循环、证据三者一致"，在此之前不得重启循环。理由见 §1 与 §8。 **[执行 2026-09-06]** 现为 **GO（受控执行）**，依据是操作者对 tsmom WEAK_PASS 的裁定（§12.6），不是更好的数字；真实资金仍 HOLD。
> - **[执行 2026-09-06]** 操作者选择路径 (b)（先修 P1-01 再有意重启）。**两条 P0 均已 CLOSED**；KILL-Q2/Q3 代码已交付但 C-2 的 falsifier 触发（tsmom WEAK_PASS），操作者裁定后判定升为 GO（§12.5–12.6）；执行记录见 §12；本文件此后的 OPEN/CLOSED 状态以 §12 与 §8 的状态列为准，正文其余段落保持 09-05/09-06 复核时的原文，不回填。
> - 外部动作授权：**无**。本轮只读仓库与网络；两次研究运行都输出到 scratchpad：`starquant research backtest --universe pit`（E-09..E-11）与 **[C 修订]** `starquant research validate --universe pit`（16 点默认网格，E-36；写入的是 scratch 目录下的 ledger，仓库 `trials.jsonl` 未动——按 D-039 的先例，下次对 tsmom 跑 validate 时应把这 16 个格子作为"手工补的坑"申报进 `--prior-trials`）。不改 registry/profile、不重启循环、不提交任何文件。
> - 独立性声明：第一遍工程审查由 4 个独立子代理各限定文件范围执行（§4）；致命/高危项由主分析者亲自复核（§4.3）。**[C 修订]** Phase 7 已由六个独立反方角色（Skeptical PM、User Reality Auditor、Evidence Prosecutor、Complexity Accountant、Delivery Saboteur、Risk & Abuse Red Team）在冻结的 09-05 版本上执行，各角色只读仓库、互不读取对方输出、不读取作者会话；合并结果见附录 C；其中 KILL-R1、R4、R6、R14 的事实链由主分析者再次独立核实（附录 C.0）。六角色对"demo 继续"与"真实资金 HOLD"两个上限无一反对；四个维持 Weak GO，一个要求 PIVOT（第一动作），一个要求 Need Evidence（FWER 门的数字，已由 E-36 补上）。
> - 同伴会话通报：**[C 修订]** `main` 在 304e549（bd7cd6e 的 D-040 manifest 资金费修复、D-041 启动数据集门，再加一条 `fix(cli): research overlay dropped the books when --min-history rebuilt the model`）；`refactor/alpha-first` 与实盘循环未动；main 的 ratchet 上限比本分支高 +199 行非 alpha。worktree 分支 `feat/mining-funding-node`（be963ad，+1,166 行）已实现 `Funding` 叶节点与 42 条 carry 族，且其提交说明指出 P14 是在读不到 funding、`vol_target 0.15` 下测的。本文件不改 `docs/RESEARCH_LOG.md`。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **Weak GO（受控执行）**：demo 继续；按修订后的 §9 执行——Phase A 第 0 步先使 registry、循环、证据一致（在此之前不重启），再修尺子（P1-01 契约、F1/F2/F3、 ledger 签名），再扩因子表达空间；Phase B 做数据宽度与退市建模。**真实资金 HOLD 且 DEFERRED**（操作者现行范围为"demo 是测试环境、mainnet 不在范围内"，所有 mainnet 前提项移入附录 D 的 pre-flight backlog，不占 12 周路线图）。解除条件写在 §11。 **[执行 2026-09-06]** 维持 **Weak GO**，但理由已第三次改写：P0 已清零、尺子已修完，现在挡住 GO 的是尺子量出来的**第一个数**——tsmom 自己（§11 新升级条件，§12.5）。 **[操作者裁定 2026-09-06]** 判定升为 **GO（受控执行）**——但升级依据是操作者对 tsmom WEAK_PASS 的一次**显式裁定**（附录 B / §12.6），不是一个更好的数字。**真实资金仍 HOLD 且 DEFERRED，不受影响。** |
| 对操作者五个问题的直接回答 | ① **[C 修订] 用两个硬数字回答"是不是玩具"**：当前构造（指纹 0dcd044d0158）只有 38 根干净 bar，88 个周期跑过 4 个构造指纹，归因合计 tsmom −13.4 / flow +3.1 USDT（≈ −0.1% 权益）——**尚无任何实盘盈利证据，而且按功效计算一年内也不可能有**（30 天窗口的年化 Sharpe 标准误 ≈ √(365/30) ≈ 3.5；在 t=2 下把 1.7 与 0 分开需要约 (2/1.7)² ≈ 1.4 年**构造不变**的干净数据）。demo 真正能证明的是**执行保真**（换手、滑点、迟到成交、registry≡循环）与**无人值守存活**，这两件事本轮为它定义了指标（M-Q03/M-Q08/M-Q09）。按维度：验证 / 证据 / 回测口径三个维度在同类开源系统之上（但见 F1/F2/F6，验证维度本轮自评从 8 下调为 6，修完可回到 8）；alpha 供给、因子挖掘、执行层、数据宽度在生产线以下；§6.1 的联赛表是作者判断（E4/E5），总分区间 4.95–5.25，名次对权重敏感，只作附录参考。② **因子挖掘"没有实现"不成立**：`starquant_alpha/mining` 已有类型化表达式枚举器并跑过 225 个候选，全部阴性；真瓶颈是表达式语言只读 5 个字段、12 个节点，且面板缺 OI / 基差 / 多空比 / 清算 / 盘口。**[C 修订]** 补一条限定：P14 的 225 个候选是在读不到 funding、`vol_target 0.15` 下测的（be963ad 提交说明），worktree 分支已实现 `Funding` 叶与 42 条 carry 族，Phase A 的第一步是合并它而不是重写它。③ **自动化挖掘：做，但按"扩空间 → 枚举 + GP → ledger 计费"的顺序，不接 LLM 提案者**（维持 P17 的 PIVOT）。**[C 修订]** "LLM 可做什么"改写为与提案者无关的机械规则：到达 validate 的每个候选必被计费、预登记必须是早于报告时间戳的 git 提交、晋级节奏由 ledger 层强制——因为仓库最近 200 次提交里 129 次由 LLM 共同署名，"LLM 不进 ledger 路径"没有执行主体。④ **自适应杠杆：维持 D-037 的 KILL**，补一项 `notionalCap` 档位校验；自适应下单量的真实缺口是冲击成本模型（KILL-A，mainnet 前提）与稳态之外的迟到成交（重启后整本书重建），不是新的比例。⑤ **止盈止损：作为 alpha 改进项维持软件层 + 维持"不调参"。[C 修订] 作为灾难保险，09-05 版建议的"异机心跳 → 只读+平仓 key → flatten"看门狗按现有代码不可交付**（心跳是本机文件、崩溃循环每 60 s 刷新心跳、`flatten` 不停循环、币安 key 无 reduce-only 作用域），改为三步：先做**远端可挂起的 kill switch（dead-man lease）+ 循环主动推送心跳 + 告警去重**（demo 范围内）；原生灾难止损降为 Won't（D-012 的预登记重开条件"进入 mainnet 且信号进入日内"两条都不满足，且 18 日波动单位的距离在当前 18 币中 7 个上根本不可下单）。 |
| 本轮最重要的发现 | **[C 修订] KILL-Q15（P0）：registry 与运行中的循环已经分叉，且没有任何仪表看得见。** 实盘进程启动于 2026-09-04T17:21:22Z（`state.json.restarted_at`，restarts 12），把 `crowding_window` 从 0 改为 72 并把 evidence 指向 193707Z 的提交 3ac8d49 在 2026-09-04T20:03:32Z——晚 2 小时 42 分，此后未重启；引擎只在启动时构建模型，88 个周期的 `inputs.funding_history` 全为 False/None（`starquant_live/inputs.py:65-68` 只在 `model.needs_funding` 为真时取资金费）。所以循环里的 tsmom 是 crowding OFF（对应 145321Z），磁盘 registry 说的是 crowding ON（193707Z）。后果：`live status --check`、`live verify`（M-011 按磁盘 registry 建模，而它此刻碰巧与进程一致，是因为两边都没读到 funding）和日报都看不见这条分叉；D-026 构造指纹不含信号参数，下一次 launchd KeepAlive 重启会把信号静默切到 crowding ON，M-010 证据窗口不清零，两种信号的收益混进同一窗口；若启动时资金费历史取不到，则进入 60 s 重试循环、书无人管理。**KILL-Q1（横截面参照总体）据此拆成两半**：tsmom 半边是**潜伏的**（下次重启起生效），flow 探针的去均值半边**当下在跑**（降 P2，并入 D-029 复审）。最便宜的关闭动作是把 registry 回退到 crowding 0 + 145321Z（`git revert 3ac8d49`，零研究成本、不清零 M-010），或在重启前完成 P1-01 修复并由操作者明示有意切换；09-05 版 §11 恰好禁止前者，已改写。 |
| 第二重要的发现 | **验证管线对下一个更弱的候选几乎没有区分力**：(F1) 2026-09-04 之后所有 tsmom 证据都是单配置或全 fold 同 key 的 validate（精确：自 09-04T05:22Z 起的五份；凌晨四份的五 fold 选择仍有变化，D-043 §五），"walk-forward OOS 1.76"实为全样本序列的后 91.8%；(F2) D-028 的选择敏感门槛用的是零假设最大值的**期望**而非**分位数**，纯噪声通过率 43.5%；(F6) ledger 签名不含构造 / 覆盖层参数，P10/P13/D-039 三轮扫描对 DSR 分母隐身。**[C 修订]** 复核指出 09-05 版把 F1 与 F2 分开论证——"tsmom 在 FWER 门下仍过"引用的是伪 OOS 1.76。本轮补做了那次计算（E-36）：在**当前构造**（0.30 / 0.40 / pit 205 / crowding 72 / D-034 后）跑 16 点默认网格，诚实的走前 OOS 是 **1.485**（fold [1.19, 0.06, 2.30, 1.25, 2.57]，NW t 3.34，CPCV q05 1.25，PBO 0.007，成本 ×2 1.68），5% FWER 阈值在 N=93 时 1.445、N=110 时 1.466——**tsmom 以 0.02–0.04 的 headroom 通过**，第 2 fold（2022-07→2023-07）几乎为零。结论从"现行结论不倒"改为"现行结论以极薄 headroom 成立，任何 +20 次试验或一次不利的构造变更都可能翻转"，这正是先修尺子再扩空间的理由。同时撤回 F1 处方里的"holdout 必选"（与 KILL-006 冲突）。 **[执行 2026-09-06]** 尺子已修（§12.5：分位数门 + `p_family` + 伪 OOS 标注）。重算全部 11 份历史报告，判定无一改变；但**用它量 tsmom 自己，C-2 的 falsifier 触发**——诚实网格 OOS 1.485 对申报 +16 后 N=141 的阈值 1.483–1.497（取决于用哪一次运行的零假设 SD），**headroom 已小于阈值的估计误差**，按预登记记 WEAK_PASS。 **[更正 §12.7]** 那个 141 是错的：+16 早在 093705Z 就申报了，当前 N 就是 125，两个 σ 下阈值 1.469 / 1.482 **都低于 1.485**——tsmom 仍 **PASS**，headroom 0.003–0.017。不变的是 headroom 已小于两个 σ 之差 0.014。 |
| 第三重要的发现 | **[C 修订] 迟到成交是开发期现象，不是稳态。** 09-05 版写"holdout 期四分之三成交不在回测口径内"；按周期复算，88 个周期里 22 个 `--immediate` 周期承载了 119 笔中的 90 笔，全部对应操作者动作（首次建仓、flatten 事故恢复、重配置、账户重置后整本书重建）；最后一次重启（09-04 17:21Z）之后，8 笔常规周期成交全部在收盘后 0.1–0.3 分钟内。机制（`deploy/run_live.sh:25` 无条件 `--immediate`）成立、修法一行，但它降为运维项：不重开 M-010 计数，改为 trade 行打 `late_seconds` 标签并在 M-010 里剔除。真正挤占 holdout 期的是**每次改构造都清零证据窗口**——88 个周期已经历 4 个指纹——所以修订后的路线图把所有改变实盘构造 / 信号的变更捆绑成 Phase A 内的**一次**重启，此后冻结到 Phase C 末。 |
| 被推翻 / 修正的操作者前提 | Pre-1（挖掘未实现）REFUTED；Pre-2（瓶颈是候选供给）REFUTED（P17 已判）；Pre-3（自适应杠杆可优化）REFUTED（D-037 已判，本轮补逐仓 / 名义档位分析后维持）；Pre-4（条件单）**[C 修订]** REFUTED——作为 alpha 否，作为保险也不是当前正确形态（远端 kill switch 先于原生单，原生单降 Won't）；Pre-5（玩具）PARTIAL——按维度判断，且盈利证据一年内不可裁决；Pre-7（LLM 处理因子模块）PARTIAL——不区分 LLM 与人，只区分是否进 ledger。 |
| 开放 P0 / P1 | **[执行 2026-09-06]** P0 现为 **0**：KILL-Q15 与 KILL-Q1-tsmom 均已关闭（§12）。以下为复核当时的清单，保留原文：P0：KILL-Q15（registry ≠ 运行进程，重启前必须一致化）、KILL-Q1-tsmom（潜伏，与 Q15 同一动作关闭）。P1：KILL-Q2（伪 OOS 标注，处方已去掉 holdout）、Q3（FWER 分位数门，N_eff 待定）、Q5（ledger 签名）、Q6（退市幽灵 bar 与冻结仓位）、Q7（单实例锁，升 P1）、Q8/Q9（改回 OPEN，直到机械计费与时间戳规则落地）、Q16（远端 kill switch 设计）、Q17（构造冻结点与证据窗口）。DEFERRED（范围）：KILL-Q12（冲击成本模型）、Q10（原生单）、Q13、Q14。 **[执行 2026-09-06 补]** P1 中 Q2/Q3 代码已交付（欠账四项见 §12.5）、Q18 已关闭；其余 P1 不变。 |
| G0–G7 / Quality Score | **[C 修订]** G0 PASS · G1 PASS · G2 PASS（C-2 的数字由 E-36 升为 E1；对标评分仍 E4/E5 但已降为参考）· G3 PASS · G4 PASS（Cost of Delay 改"高"：每一天都是一次崩溃即静默换信号的风险）· G5 PARTIAL · G6 **PARTIAL（已独立复核；OPEN P0 = 2，均有一步可关闭的动作）** · G7 PARTIAL（DL-Q8 已按复核重写；测试矩阵仍未写）。Quality Score 37/50（对抗生存 3 → 4，执行可交付性 3 → 2，证据 4 → 4，范围收敛 4 → 3）；硬门禁 OPEN P0 > 0 → Weak GO。 **[执行 2026-09-06]** G6 已 PASS（OPEN P0 = 0）；分数不变，判定升为 GO 的依据是 §12.6 的裁定而非分数。 |

---

## 1. Gate Summary

| Gate | 状态 | Evidence/Claim | 未通过项 | 决策上限 | 下一动作 |
| --- | --- | --- | --- | --- | --- |
| G0 Interaction/Kill | PASS | §2 | 无 FATAL；K3/K5 命中已处理（Option Set、Scope Firewall） | — | — |
| G1 Problem/Axiom | PASS | C-1..C-6 | 问题在移除"LLM / 条件单"方案后仍独立成立（alpha 供给窄、验证区分力弱、执行口径漂移、生产缺口） | — | — |
| G2 Evidence/Reality | PASS **[C 修订]** | E-01..E-40 | 对标评分为 E4/E5 判断，已降为附录参考；P1-01 的 1.8× 触发率仍为代理复算（E2），但机制 E1 且六角色全部确认；C-2 的关键数字由 E-36 升为 E1。**[执行]** E-12 已实测升 E1（10.60% 对 17.28%、重合 52%，§12.2） | Weak GO → GO（裁定，§12.6） | 已完成（§12.2） |
| G3 Relative Value | PASS | §6 | 已比较 No-Build / Small / Full / System；20% 成本方案存在（Phase A 前四项） | — | — |
| G4 Strategic/Economic | PASS **[C 修订]** | §5 | 单操作者、无外部经济角色；**Cost of Delay 高**：KILL-Q15 使每一次无人值守崩溃都可能静默换信号 | — | Phase A 第 0 步 |
| G5 System/Solution | PARTIAL | §4 §7 | 工程未知项：metrics 归档发布时刻 / REST 桶可得时延 / 两者同桶值差（KILL-Q11 三项核查）；币安 key 权限粒度（E4）；mined 哈希在新增节点后是否稳定 | 不进入数据摄入与原生条件单的交付契约 | §7.1 的三项 15 分钟核查 |
| G6 Adversarial | **PASS**（2026-09-06 执行后；复核时为 PARTIAL） | §8 §12 附录 C | 六角色独立复核已完成：29 条 Kill，3 条 P0（R1/R2/R3），R3 由 E-36 关闭，R1/R2 转为 KILL-Q15/Q16；**Q15 与 Q1-tsmom 已于 2026-09-06 关闭（§12），OPEN P0 = 0** | 硬门禁解除 | **[执行]** Q2/Q3 代码已交付；用它量 tsmom 自己：**PASS，headroom 0.003–0.017**（E-40，§12.7 更正；初稿误记 WEAK_PASS）。操作者已就更差的那种情形作出裁定，GO 因此有两重依据（§12.6）；B0 已关掉四项欠账中的四项 |
| G7 Delivery/Learning | PARTIAL **[C 修订]** | §10 | DL-Q8 已按复核重写为可交付规格；DL-Q2 去掉 holdout 条件；DL-Q3 拆两步；DL-Q4 改 `fcntl` + key 指纹锁 + `--armed`；测试矩阵仍未写 | 不进入正式 PRD | Phase A 开工前按 C.3/C.4 补 |

---

## 2. Phase 1 · Reality Check

输入类型：方案型 + 愿景型 + 情绪型混合。按 B.2 规则剥离方案还原 Problem、拆愿景为 Claim、把"玩具"还原为缺口清单。

### 2.1 需求预设清单

| Pre ID | 提出者默认成立的前提 | P级 | 依据 | 若不成立会改变什么 | 判定 |
| --- | --- | --- | --- | --- | --- |
| Pre-1 | 因子挖掘"没有实现" | P0 | `starquant_alpha/mining/expr.py`（538 行）、`search.py`（244 行）、`tests/alpha/test_mining.py`（231 行）；P14 跑了 7 族 225 候选，最优 1.0745 vs tsmom 1.6972、相关 0.47、边际 −0.08 | 方案从"造挖掘器 / 接 LLM"变为"扩叶节点 + 扩数据源" | **REFUTED**（A-01） |
| Pre-2 | 策略 / 因子"非常少"是主要瓶颈 | P0 | 7 个手写信号、1 主书 + 1 探针；5 个被否决者各有机制性死因；P17 C-001 REFUTED | 加信号的期望值低于修口径 / 扩空间的确定性收益 | **REFUTED**（A-02） |
| Pre-3 | 自适应杠杆"还有优化空间" | P1 | D-037：仓位 = 权重 × 权益，MMR 按名义档位索引，L≥3 保证金从不绑定；P15 复核 5x 是规格值 | 只有新目标函数才可重开 | **REFUTED**，见 §7.3 的逐仓 / 名义档位分析 |
| Pre-4 | 止盈止损"应考虑交易所条件单" | P1 | D-012 不做原生单（legacy E-033 事故、demo 日内路径合成、bar 驱动）；P11 止损 6σ 被记录为"不保护任何可测量的东西" | 问题拆成"灾难保险"与"alpha 改进"两件事 | **PARTIAL**，见 §7.2 |
| Pre-5 | "能用但只是玩具，不能交付生产" | P0 | 两份既有审计致命 0；实盘仅 2.4 天 / 58 周期 / 归因 −2.92 USDT；成本模型平 7 bps、REST 轮询、单交易所 | "生产"需按"无人值守单操作者小时级书"逐维度定义 | **PARTIAL**，见 §6.4 |
| Pre-6 | 与 GitHub 系统对比评分能指导优化 | P1 | 主流开源系统多为 A 股日频 / 做市 / 事件驱动引擎 | 评分必须按用途加权，否则把执行引擎 / 社区差距误读为优先级 | 已按用途加权（§6） |
| Pre-7 | "用大模型处理因子模块"可行 | P1 | P17 PIVOT：LLM 变不出面板里没有的列、补不上 `expr.py` 没有的类；自适应提案破坏 DSR 的可交换抽样（A-004 OPEN） | LLM 可离线提案 / 批评，不得进入 ledger 路径 | **PARTIAL**，见 §7.1.5 |

### 2.2 需求三问

| 问题 | 答案 | Evidence |
| --- | --- | --- |
| 谁的需求，谁承担损失？ | 单一操作者；demo 阶段损失 = 时间与证据窗口，真实资金阶段 = 本金 | E-01 |
| 频率、规模、损失多大？ | 每小时 1 周期、15 币、demo 权益 ≈ 10.7k USDT；实盘 OOS 记录自 2026-09-03T07:58Z 起 58 周期、12 次重启、归因 14 行合计 −2.92 USDT（tsmom −5.28 / flow +2.41）、 exit overlay 与护栏零触发 | E-02 |
| 现有方案能否满足大部分需求？ | 验证纪律已达标；alpha 供给、成本 / 容量模型、执行层、数据宽度是短板 | §4–§7 |

Early Kill：K1/K2/K7 不成立；K3（必须比较替代）与 K5（范围需防火墙）命中并已处理；K8 待 §10。**G0 PASS（Yellow）。**

---

## 3. Phase 2 · Evidence Ledger 与 Claim Register

### 3.1 Evidence Ledger（本文件内编号；E1 除非注明）

| ID | 类型 | 来源 | 摘要 | 等级 |
| --- | --- | --- | --- | --- |
| E-01 | CODE | `README.md`、`pyproject.toml`、包行数 | 五包 13,733 行 + 测试 7,548 行；纯 numpy/pandas alpha；CI 离线（ruff / mypy strict / pytest） | E1 |
| E-02 | DATA | `.starquant/live/state.json`、`cycles.jsonl`、`trades.jsonl`、`attribution.jsonl` | started 2026-09-03T07:58:44Z、restarts 12、cycles 58、成交 99 行、归因 14 行 −2.92 USDT、exit_events 0、guard 0、PARTICIPATION_CAPPED 0。**[C 修订] 2026-09-06 02:00Z 读数**：cycles 88（构造指纹分布 None 28 / df6c 7 / a53e 15 / 0dcd 38）、成交 107 行、归因 19 行合计 tsmom −13.4 / flow +3.1 USDT、universe 18 币（09-05 进 LINK，09-06 进 TUT/UNI）、权益 10,924 USDT | E1 |
| E-03 | DATA | `.starquant/data` | 877 币 1h/1d K 线（11 列，含 open/volume/trades/taker_buy_base）、231 币资金费（含 mark_price）、2,042 天时点成员表 | E1 |
| E-04 | CODE | `starquant_alpha/mining/expr.py`、`search.py` | 12 个 Expr 节点、读 5 个字段（close/high/low/quote_volume/taker_buy_quote）；7 族；`register()` 只接受 `mined_*` | E1 |
| E-05 | CODE | `reports/research/mine-shortlist-20260904T145150Z.json`、RESEARCH_LOG P14 | 225 候选全阴性；最优 `squash(rangepos(168),2)` 1.0745；边际 −0.08 | E1 |
| E-06 | CODE | `docs/analysis/2026-09-05-mining-proposer-pivot.md` | 20 条加密因子：7 已搜 · 7 缺节点 · 6 缺数据；C-001/C-002 REFUTED | E1 |
| E-07 | CODE | `reports/research/tsmom-validation-20260904T193707Z.json` | OOS 1.7647 / NW t 4.03 / CPCV 1.795 q05 1.338 / PBO 0.136 / DSR p 0.2155（noise-null 0.033）/ D-028 阈值 1.098 @ 93 trials / 全样本 1.826 / MDD −22.2% / grid_size 2、五 fold 全选 72 | E1 |
| E-08 | CODE | `config/alpha_registry.yaml:100-103` | 16 点网格 040252Z：OOS 1.376、t 3.13、PBO 0.015 | E1 |
| E-09 | EXPERIMENT | 本轮 `research backtest --universe pit`（scratchpad，不入账） | 全样本 Sharpe 1.83、MDD −22.1%、与等权多头相关 −0.12、69.6% 月份为正、最差月 −9.2%（2024-01）、最差日 −6.87%（2021-09-07）、最差小时 −6.24%、7 小时 < −3%、4 天 < −5%、偏度 +0.72、峰度 26；gross 均值 0.86 / p95 1.80；多 0.425 / 空 0.434；持仓均 17.5 币；guards 重放：暂停 37 bar、capped 460 bar、`liquidation_touches` 0、`min_margin_buffer` 99.2 | E1 |
| E-10 | EXPERIMENT | 同上，压力窗口 | 2022-05 LUNA +21.4%（等权多头 −45.2%）、2022-06 3AC +8.7%、2022-11 FTX −5.3%（−29.4%）、2023-03 SVB −3.1%（+13.4%）、2024-08 日元套息 +8.7%（−21.1%）、2025-02 关税 +9.3%、2025-04 +2.4%、2025-10-10 清算潮 +4.2%（−12.7%）。**[C 修订]** 2021-05 在样本内（首个决策 bar 2021-01-31，KILL-R23）：**2021-05-10→05-23 书 +2.4%（等权多头 −41.1%），05-19 当日 +4.2%（−22.8%）**，当日多 0.46 / 空 0.51，最坏小时 −2.2%；2020-03 不在样本内。九个窗口七正两负 | E1 |
| E-11 | EXPERIMENT | 同上，回撤（**[C 修订]** 按"新高之间的谷底"重新提取，两种方法结果一致；小时级净收益序列已存为 scratchpad `bt/tsmom_pit_net_hourly.csv`，未入库） | −22.1%（2022-01-22→04-19，107 天恢复）、−22.1%（2023-03-10→04-29，91 天）、−15.8%（2024-07-05→08-01）、−15.8%（2021-09-06→10-12）、−15.6%（2025-05-23→07-03，112 天）、−14.4%（2024-10-21→11-07）。两对深度在 0.1% 精度上重合经复核为真实巧合，非提取缺陷 | E1 |
| E-12 | CODE+DATA | 审计 alpha-signals P1-01 + `tsmom.py:185-191`、`flow.py:87-88`、`model.py:121-130`、`research_cmd.py:135-154`、`engine.py:277-296` | 横截面参照总体不一致（机制由主分析者读码确认，六个反方角色全部确认；1.8× 触发率、49.6% 重合为代理读盘复算，未被独立复现）。**[C 修订]** 实盘参照不是固定 15 币：`refresh: daily`，09-06 已是 18 币，等价契约必须按逐日成员而非固定 n 写（KILL-R5） | E1（机制）/ E2（数字）→ **[执行]** 数字已实测升 E1：10.60% 对 17.28%、重合 52%（§12.2） |
| E-13 | CODE | 审计 backtest-validation F1 + `walk_forward.py:134-154`、`verdict.py:57-83`、`research_cmd.py:453-463` | 单配置 / 全 fold 同 key 时 OOS = 序列后 91.8%；`best_key = max(full_sharpes)` | E1 |
| E-14 | CODE+MATH | 审计 F2 + `multiple_testing.py:182-210` | `threshold = expected_max_sharpe(...)` 即 E[max]，非分位数；由 193707Z 反算噪声通过率 0.435、5% FWER 阈值 1.43、tsmom p 0.0026 | E1 |
| E-15 | CODE | 审计 F6 + `ledger.py:46-48` | `signature = (param_key, range_start, range_end, symbols)`，构造参数不在签名；`scratchpad/no_trade_band_sweep.py:26`、`vol_target_drawdown_bootstrap.py:12` 自述不入账 | E1 |
| E-16 | CODE | 审计 F7 + `research_cmd.py:157-172,406,751` | `_resolve_mined` 仅在 correlate 调用；validate 对 `mined_*` 抛 KeyError | E1 |
| E-17 | CODE+DATA | 审计 data DATA-01 / backtest F8 | 退市币零量幽灵 bar（FTT 619 根、ALPACA 614 根）、LUNA 成员资格延续到 2022-06-10（27 天）、冻结仓位 758 币-bar；内存重放三事件合计约 +3.8% 权益（代理复算） | E1 / E2 |
| E-18 | DATA | 本轮由 `trades.jsonl` 复算 | 86 笔带 bar 标签成交：晚于收盘中位 21.6 分钟、73% > 1 分钟、最长 59.6 分钟；`deploy/run_live.sh:25` 无条件 `--immediate`。**[C 修订] 按周期口径**：88 个周期里 22 个 `--immediate` 周期承载 119 笔中的 90 笔，全部对应操作者动作；最后一次重启（09-04 17:21Z）后 23 笔成交中 15 笔来自那一个重启周期（整本书重建，迟到 21.6 分钟），其后 8 笔常规周期成交全部 ≤ 0.3 分钟——**稳态迟到率 0/8** | E1 |
| E-19 | DATA | 审计 live L1-04 由 `trades.jsonl` 复算 | 85 笔可定价成交：滑点均值 +5.0 bps、中位 +1.3、名义加权 +4.3（模型假设 2 bps）、极值 −81/+53 bps | E1 |
| E-20 | CODE | `execution.py:40-47`、`rebalancer.py:59-63`、grep flock/pidfile 零命中 | 无单实例锁；query-before-submit 存在 | E1 |
| E-21 | OFFICIAL | 币安 USDⓈ-M 文档（New Order / New Algo Order） | 2025-12-09 起 STOP_MARKET/TAKE_PROFIT_MARKET/STOP/TAKE_PROFIT/TRAILING_STOP_MARKET 只能走 `POST /fapi/v1/algoOrder`，旧端点返 −4120；`closePosition=true` 不能带 quantity/reduceOnly、平掉整个方向；`workingType` 默认 CONTRACT_PRICE；`priceProtect`；`newClientOrderId` "unique among open orders" | E1 |
| E-22 | OFFICIAL | data.binance.vision S3 列表 | `futures/um/daily/`：aggTrades、bookDepth、bookTicker、indexPriceKlines、klines、markPriceKlines、**metrics**、premiumIndexKlines、trades；`monthly/` 多 fundingRate、无 metrics/bookDepth；`metrics/BTCUSDT` 自 **2020-09-01** 起；本轮查询下 `liquidationSnapshot` 前缀为空 | E1 |
| E-23 | MARKET | 搜索结果 | metrics 列：create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio（粒度与发布延迟未核，标 UNKNOWN） | E4 |
| E-24 | OFFICIAL/MEMORY | 币安 Query Order 文档（本轮未能抓取，凭已知条文） | 已成交订单可按 `origClientOrderId` 查询 90 天；仅"已取消 / 过期且无成交超 3 天"与"超 90 天"查不到 | E4 |
| E-25 | MARKET | GitHub / 文档抓取 | RD-Agent 14.5k★（R&D-Agent(Q) NeurIPS 2025，主指标 ARR，README 无多重检验控制）；freqtrade 54k★（`stoploss_on_exchange`：入场成交后立即挂止损限价单、60 s 刷新、被撤即重挂、失败回退 `emergency_exit` 市价）；nautilus 28.4k★（Rust 核心、回测实盘同引擎、L2 撮合 / 延迟模拟、TWAP、OCO/OTO）；hummingbot 19.8k★（50+ 连接器、V2 controllers/executors）；passivbot 2.1k★（Rust 回测 + 进化优化器，无 walk-forward 声明） | E3/E4 |
| E-26 | MARKET | 搜索结果 | backtrader 21k★、zipline-reloaded 20k★、Lean 18k★、jesse 7.6k★、OctoBot 5.5k★；Qlib / vnpy 未抓取 | E4 |
| E-27 | RESEARCH | arXiv | AlphaGen（KDD 2023, 2306.12964）：RL 生成表达式 alpha、以组合模型表现为奖励；AlphaAgent（KDD 2025, 2502.16789）：LLM 提案 + AST 原创性 / 复杂度正则以抗衰减，S&P500 2021–2024 报 IR 1.05；R&D-Agent(Q)（2505.15155）：因子-模型协同进化，报 2× ARR / 70% 更少因子；QuantaAlpha（2602.07085）：进化式 LLM 挖掘；AlphaLogics（2603.20247）；"From Hypotheses to Factors: Constrained LLM Agents in Cryptocurrency Markets"（2604.26747）：2020–2022 训练、2024–2026 OOS 报 Sharpe 1.55 | E3 |
| E-28 | CODE | `docs/analysis/2026-09-05-backtest-guard-external-audit.md` | 前次外审：参与率不进回测（拐点 10 万–100 万 USDT：4.25% → 28.6% 目标换手做不掉）、无强平仪表（已由 M-016/M-017 补：`min_margin_buffer` / `liquidation_touches`）、edge 陈述已闭环 | E1 |
| E-29 | CODE | `starquant_live/leverage.py:25-33`、`rebalancer.py:70-190`、`portfolio.py` | 杠杆 = `ceil(max_gross/margin_cap)` 截断到 bracket 与 max；再平衡带 / reduce-only / 参与率 / min_notional 全在 `plan_rebalance`；三段构造 + EWMA 协方差 | E1 |
| E-30 | CODE | `starquant_alpha/overlays/exits.py`、`starquant_live/exits.py` | `exit_step` 单一真值：bar 收盘、入场时日波动单位、冷却期；实盘方向以交易所为准、入场价首入锚定（E-047） | E1 |
| E-31 | CODE | 审计 live L1-09 + `reconciler.py:97-107` | 启动撤销账户**全部**未完成订单，不按 tag 过滤 | E1 |
| E-32 | CODE | 审计 live L1-05 + `attribution.py:8-30` | INCOME_TYPES 只有三种；INSURANCE_CLEAR 等静默丢弃；运行时无 liquidationPrice / forceOrders 读取 | E1 |
| E-33 | USER+CODE | 同伴会话消息（2026-09-05）+ **[C 修订]** 复核角色 `git show main` | `main` 在 304e549：D-040 manifest 资金费修复、D-041 启动数据集门、以及 `fix(cli): research overlay dropped the books when --min-history rebuilt the model`；`git diff db9efd9 main` 只触及 live_cmd / research_cmd / live/config / live/reports，**本轮四条核心发现在 main 上均未修**；main 的 ratchet 上限比本分支高 +64 live / +18 cli / +117 data | E1 |
| E-34 | CODE | `tests/` 清单 | 架构比率 / 依赖方向 / 因果性 / 护栏惰性 / 资金费对齐 / 启动门等测试存在；无"研究面板 ⊃ 实盘面板"的等价测试 | E1 |
| E-35 **[C]** | DATA+CODE | `.starquant/live/state.json`（restarted_at 2026-09-04T17:21:22Z，restarts 12）；`git log -1 --format=%ci 3ac8d49` = 2026-09-04T20:03:32Z；`cycles.jsonl` 88 行 `inputs.funding_history` ∈ {False, None}；`starquant_live/inputs.py:65-68`；`starquant_live/engine.py:849-899`（构造指纹 payload 无信号参数）；`docs/RUNBOOK.md:46` | **循环在跑 crowding 0（145321Z），磁盘 registry 是 crowding 72（193707Z）**；进程启动早于该提交 2h42m 且此后未重启；构造指纹看不见信号参数，下次重启静默切换且证据窗口不清零。主分析者独立核实 | E1 |
| E-36 **[C]** | EXPERIMENT | 本轮 `research validate --strategy tsmom --universe pit --prior-trials 30`（16 点默认网格，输出到 scratchpad `val/`，仓库 ledger 未动；报告 `tsmom-validation-20260906T030942Z`） | 当前构造（0.30 / 0.40 / pit 205 / crowding 72 / D-034 后）下诚实的网格走前 OOS Sharpe **1.485**，NW t 3.34，fold [1.19, 0.06, 2.30, 1.25, 2.57]，一致性 1.0，逐 fold 选择 [24/72/168 h, 阈值 0.3, 基线, 基线, 基线]，全样本 argmax = registry 参数，CPCV 1.79 / q05 1.25 / 0% 负，PBO 0.007，成本 ×2 1.68；零假设年化 SD 0.443；5% FWER 阈值：N=16 → 1.207、46 → 1.354、**93 → 1.445、110 → 1.466**。tsmom 通过，headroom 0.02–0.04。~~待申报：下次 validate 的 `--prior-trials` +16~~ **[更正 §12.7]：已由 093705Z 申报**——`--prior-trials` 30 → 60 的分解是 30 + 14（D-039 带格）+ **16（本次网格）**，写在 registry 注释里。**[执行 复审]** 报告已入库 `reports/research/scratch/tsmom-validation-20260906T030942Z.{json,md}`（未记账、不在任何 registry 证据路径上；入库前从 scratchpad 复核：OOS 1.4852、σ 0.4428、五 fold 选出 3 种配置） | E1 |
| E-37 **[C]** | DATA | `.starquant/live/state.json` `exit_states.*.unit`（2026-09-06T02:00Z） | 18 币中 7 个的入场时日波动单位 > 1/18（AKE 0.256、CYS 0.149、TUT 0.140、ENA 0.081、UNI 0.080、ZEC 0.078、TRUMP 0.072）：18 单位的多头止损价 ≤ 0、空头止损在 +130%…+461% | E1 |
| E-38 **[C]** | CODE | `docs/RESEARCH_LOG.md:732-760`（KILL-006 §二）、`starquant_cli/research_cmd.py:374-378` | 操作者 2026-09-04 裁决：六个月 holdout**不启用、刻意不使用**；CLI 帮助文本写 `unused by choice`；:740 的"建议（待操作者确认）"未被采纳 | E1 |
| E-39 **[执行]** | EXPERIMENT+CODE | `starquant_alpha/validation/multiple_testing.py`（`max_sharpe_quantile` / `family_p_value`）；仓库内 11 份带 `oos_selection` 的报告 | 旧门槛 = σ·E[max of N]，**放进纯噪声的概率 43.4%–43.5%，十一份全一样而 N 从 90 到 268**——它没有 α，收再多搜索费也不会降。新门槛 = σ·Φ⁻¹((1−α)^(1/N))。重算全部 11 份：**无一判定改变，无一候选被救活**。新代码在 N=93/110 上复现了 E-36 手算的 1.445/1.466 | E1 |
| E-40 **[执行；数字已由 §12.7 更正]** | EXPERIMENT | 同上，作用在 E-36 的诚实网格 OOS 1.485 上 | 阈值随 N 单调上升，**达到 1.485 的 N 是 128（σ=0.4430，E-36）或 144（σ=0.4389，093705Z）**——这两个数没变。变的是当前的 N：**125 就是含 +16 的最终值**（63 去重 + 2 网格 + 60 申报，而 60 = 30 + 14 + 16），初稿误以为 +16 仍欠着而推出 141。在 N=125 上阈值 1.4685（σ 0.4389）/ 1.4822（σ 0.4430），**两个 σ 下都 PASS**，headroom 0.003–0.017——而两个 σ 给出的阈值本身相差 0.014。下一次 validate 约 N=127（ledger 吸收 093705Z 的 2 行），阈值 1.4704 / 1.4841，仍 PASS；跑一次 16 点网格则约 N=143，1.4848 / 1.4986，一个 σ 下转 WEAK_PASS | E1 |

### 3.2 Claim Register

| ID | 命题 | P级 | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- |
| C-1 **[C 修订]** | 当前实盘的证据不描述实盘在跑的信号——分两层：(a) registry ≠ 运行进程（crowding 72 vs 0）；(b) 横截面参照总体研究 ≠ 实盘（tsmom 潜伏、flow 当下） | P0 | (a) 重启前一致化后 `live verify` 与 registry 指纹逐周期一致；(b) 修正参照总体后两臂重跑与 193707Z 的逐日触发集重合率 ≥ 95%（按日重合，容忍非零残差，预登记） | E-35, E-12 | **SUPPORTED** |
| C-2 **[C 修订]** | 现行验证门对 Sharpe 1.0–1.4 的候选无区分力；tsmom 自身在诚实网格 + 5% FWER 门下仍 PASS 但 headroom ≤ 0.04 | P0 | 若 N_eff 估计使阈值 ≥ 1.485 → tsmom 转 WEAK_PASS，§11 升级条件与 §0 改写；若相关噪声仿真通过率 > 5% → 重查公式 | E-13, E-14, **E-36**, **E-40** | **SUPPORTED（E1）；falsifier ~~已触发~~ 未触发（§12.7 更正）：当前 N=125 下阈值 1.469–1.482 < 1.485，两个 σ 都 PASS，headroom 0.003–0.017** |
| C-3 | alpha 供给的瓶颈是可表达空间与数据宽度，不是提案者 | P0 | 合并 be963ad（Funding 叶 + 42 carry 族）并扩 5 个只读现有列的节点后，同一枚举器在 0.30 口径下仍无候选越过 tsmom 边际 +0.05（以 267 为基数） | E-04..E-06, E-33 | PARTIAL（P17 之 C-003；**[C 修订]** E-05 需注明 P14 未含 funding、在 0.15 下测） |
| C-4 **[C 修订]** | tsmom 的 edge 在崩盘期呈凸性，在急反转期亏损，不是伪装的卖波动 | P1 | 若某压力窗口书亏损 > 等权多头亏损，或收益左偏 | E-09, E-10（含 2021-05） | SUPPORTED（偏度 +0.72，9 个窗口 7 正；两负均为急反转） |
| C-5 **[C 修订]** | 交易所原生条件单作为 alpha 改进为负；作为保险，在当前书上不是正确形态 | P1 | 若远端 kill switch + 心跳外推落地后仍出现"循环存活但无法平仓"的失联情形 ≥ 1 次 → 重开原生单，且距离按符号分层 | E-09, E-21, E-30, E-31, **E-37** | **REFUTED（保险半边）** |
| C-6 **[C 修订]** | 真实资金前的必要条件是冲击成本模型 + 单实例 + 远端停机 + 强平可观测 + 上线断言（CROSSED / 全新 state_dir / 空仓空挂单 / 告警演练） | P0（范围 DEFERRED） | 若 10 万 USDT 以下容量拐点不成立（前审表）则冲击模型可后置 | E-28, E-20, E-32, 附录 C KILL-R19 | SUPPORTED；不在 12 周路线图内 |

---

## 4. 策略体检报告 · backtest-guard（两遍）

```
══════════════════════════════════════════
   策略体检报告 · backtest-guard
══════════════════════════════════════════
受检对象: StarQuant（分支 refactor/alpha-first @ db9efd9）
扫描: starquant_alpha / starquant_data / starquant_exchange / starquant_live / starquant_cli / config / deploy  ≈ 13.7k 行 + 测试 7.5k 行
审计方式: 4 个独立子代理各限定范围（第一遍）；主分析者复核致命/高危项并执行第二遍

总评: 🔴 致命 0 项 · 🟠 高危 4 项（复核后 3 项 + 1 项降运维）· 🟡 中 12 项 · 🔵 低 24 项  (逻辑项 6 项)
      [C 修订] 复核新增 1 项高危: registry ≠ 运行进程（KILL-Q15，E-35）
判语: 「回测的算术是干净的；不干净的是证据的口径——磁盘上的 registry 说的不是循环在跑的信号，
      验证时的横截面总体不是实盘的那个，"OOS" 有九成是样本内，tsmom 在诚实的尺子下只剩
      0.02–0.04 的 headroom。这些都能修，而且修完之前，扩 alpha 空间是在给一把不准的尺子喂更多候选。」
```

### 4.1 第一遍 · 工程审查（均带 文件:行；※ = 作者已披露）

**[🟠 高危] [C 新增] KILL-Q15 磁盘 registry 与运行中的循环已分叉，无仪表可见**
位置：`.starquant/live/state.json`（restarted_at 2026-09-04T17:21:22Z）、提交 3ac8d49（2026-09-04T20:03:32Z，`crowding_window` 0 → 72、evidence → 193707Z）、`starquant_live/inputs.py:65-68`、`starquant_live/config.py:170-172`、`starquant_cli/live_cmd.py:114`、`starquant_live/engine.py:849-899`
问题：引擎只在启动时构建模型；进程启动早于 registry 变更 2h42m 且此后未重启；88 个周期 `inputs.funding_history` 全为 False/None，即进程里的 tsmom 是 crowding OFF（145321Z 的配置），而磁盘 registry、`docs/RUNBOOK.md:46` 之外的全部文档与本报告 09-05 版都以为 crowding ON 在跑。D-026 构造指纹不含信号参数，`live status --check` 与日报都比不出这条分叉；下一次 launchd KeepAlive 重启（两天里已 12 次）会静默切到 crowding ON（带着下面 P1-01 的总体错配），M-010 窗口不清零；若启动时资金费历史取不到则进入 60 s 重试循环。
复核（主分析者，E-35）：三条事实链独立核实。**成立，未披露，是 KILL-027 的形状。**
修复（两条路径，操作者二选一，都必须在任何重启之前完成）：(a) `git revert 3ac8d49`，registry 回到 crowding 0 + 145321Z——零研究成本、不清零 M-010；(b) 先完成 P1-01 的参照总体修复并重跑两臂，再有意重启并把这次重启记为构造变更。两条之后都要：每周期记录 registry 参数 digest（进 `cycles.jsonl` 与心跳），`live status --check` 比对磁盘 registry 与已加载模型（< 50 行）；D-026 指纹或日报纳入信号参数 digest，使信号变化也清零证据窗口。

**[🟠 高危] P1-01 横截面参照总体：研究 ~123 个名字，实盘 15–18 个（tsmom 半边潜伏，flow 半边当下在跑）**
位置：`starquant_alpha/signals/tsmom.py:185-191`、`starquant_alpha/signals/flow.py:87-88`、`starquant_alpha/model.py:121-130`、`starquant_cli/research_cmd.py:135-154`、`starquant_live/engine.py:277-296`
问题：`apply_crowding_modifier` 在 `score.columns` 全体上做 `cross_sectional_rank`，flow 在全体上去均值；时点成员表只在算完分数之后作用（`scores.where(eligible)`）。研究面板 = 曾入选过的 205 币，实盘面板 = `managed_symbols()`（universe ∪ leaving，**[C 修订]** 逐日刷新，09-05 读 15、09-06 读 18）。n=15 时 `rank >= 0.7` 恒标 3 个名字（20%），n≥100 时 15%。现有等价测试对两条路径喂同一个 6 币面板，结构上发现不了。
复核：机制由主分析者逐行确认，六个反方角色全部确认；触发率数字为代理读盘复算（E2）。**成立，未披露，影响 OOS 数字**——但 **[C 修订]** 按 E-35，tsmom 的 crowding 半边此刻并未在跑，它在下次重启时生效；当下受影响的只有 flow 探针的去均值（降 P2，并入 D-029 的 30 天复审）。
修复（**[C 修订]** 契约按 KILL-R5 重写）：横截面算子的**参照集合是显式参数，只作用于秩 / 去均值步骤，不作用于面板**——实盘传 universe（并写明 leaving 是否计入），研究传当 bar 的时点成员；不采用"研究侧先裁面板"（会让重新入选的币在 `rolling(72, min_periods=72)` 上得 NaN → `fillna(0)` → 72 根 bar 内永不判拥挤，制造新的口径漂移）。测试拆两条：同一参照 → 逐位相等；参照 ≠ 面板列 → 结果随参照变而不随多余列变；并对真实逐日 universe 序列做等价。M-Q01 改为按日重合率并预登记非零残差容忍度。修后重跑 193707Z 两臂与 book 报告并更新 registry（记 ledger 行）。

**[🟠 高危] F1 单配置 validate 的"walk-forward OOS"是同一条全样本序列的后 91.8%**
位置：`starquant_cli/research_cmd.py:453-455,463`、`starquant_alpha/validation/walk_forward.py:134-143,154`、`starquant_alpha/validation/verdict.py:57-60,83`
问题：fold 只是切片；grid_size 1 或全 fold 同 key 时，`chosen = best_key or keys[0]` 无选择自由度，`oos_returns` = 序列从第 4000 根起的 45,024/49,024。2026-09-04 后所有 tsmom 重跑（052215Z / 131421Z / 145321Z / 193707Z）都属此情形；16 点网格的真实走前 OOS 是 1.376（E-08）。
复核：代码确认。部分披露（registry 注释自述 "single-configuration report (grid 1)"；KILL-036 已接受"没有一天真正的 OOS"），但报告与 registry 把这个数标为 OOS，而 verdict 据此给 PASS。**成立，标注类高危。**
修复（**[C 修订]**）：报告加 `oos_is_full_sample_tail`；registry evidence 块并列记录**当前构造下**的网格走前 OOS（E-36：1.485，不再引用 0.15 时代的 040252Z 1.376——那是跨四项构造变更的比较，KILL-R22）。**撤回**09-05 版的"必须带 `--holdout-months ≥ 1` 且单独报告 holdout 段"：它与操作者裁决 KILL-006 §二"holdout 不启用、刻意不使用"直接冲突（E-38），且与 Phase A 的"像对像"重跑不能同时成立（holdout 会改 fold 边界、所有 OOS 数字重出）；若将来重开 KILL-006，须作为独立的操作者决定写进附录 B 并接受全部数字重出的代价。

**[🟠 高危] F2 D-028 门槛是 E[max]，不是分位数：纯噪声通过率 43.5%**
位置：`starquant_alpha/validation/multiple_testing.py:182-210`（:203）、`verdict.py:61-66`
问题：`threshold = expected_max_sharpe(n_trials, variance)`，即零假设下 N 次尝试最大 Sharpe 的期望；一条噪声曲线有近一半概率越过期望。由 193707Z 反算：年化零假设 SD 0.438、阈值 1.098、P(max of 93 nulls > 1.098) = 0.435；5% FWER 阈值应为 1.43；tsmom 1.765 对应 p 0.0026 仍过。
复核：代码与数学确认。**成立。对下一个弱候选（flow 0.92、mined 1.07）几乎无区分力。** **[C 修订]** 09-05 版写"tsmom 在 5% FWER 下仍以 p 0.0026 通过"用的是伪 OOS 1.76（F1），两条发现从未合并；E-36 补做了合并后的计算——诚实网格 OOS 1.485 对 N=93…110 的阈值 1.445…1.466，**通过，headroom 0.02–0.04**，第 2 fold 0.06。 **[执行]** 该 headroom 在 093705Z 的 N=125 上已降为 0.003（σ 0.4430）/ 0.017（σ 0.4389）——仍在 PASS 一侧，但已小于两个 σ 给出的阈值之差 0.014。见 E-40 与 §12.7。
修复（**[C 修订]** 按 KILL-R25 细化）：只改 `oos_selection_threshold`（解 Φ(x)^N = 1−α，α 预登记 0.05），不动 `expected_max_sharpe`（DSR 仍用它）；N 取 ledger N_eff（用 CSCV 已有的 T×N 收益矩阵估相关结构；85 行 ledger 里 24 行重复、大量近似重复，N_eff ≪ 93，N_eff≈10 时阈值 ≈ 1.13），并在 verdict reasons 输出 `p_family` 与 N_eff；预登记 N=1 的处理（保留 `test_selection_gate.py:28`"单试验不算选择"）；DL-Q2 的验收改为"相关噪声（同一面板块自举）下通过率 ≤ 5% 且 tsmom 仍 PASS"，而不是 93 个独立噪声。

**[🟡 中，原判高危] [C 修订] L1-01 每次重启都 `--immediate`：机制成立，"73%"是开发期比率**
位置：`deploy/run_live.sh:25`、`starquant_live/engine.py:211-217`、`starquant_live/scheduler.py:21-23`、`starquant_alpha/backtest.py:139-141,168`、`starquant_live/risk_budget.py:148-159`
问题：回测口径是决策 bar 的下一根开盘成交；重启周期在收盘后 161–3,576 秒成交，滑点仪表以快照 mark 为参照按构造看不见。
复核：数字三方独立复现（n 86–87、中位 21.6 分钟、72–73% > 1 分钟）。**但归因被复核推翻**（E-18）：迟到集中在 22 个 `--immediate` 周期，全部对应操作者动作（首次建仓、flatten 事故恢复、重配置、账户重置后整本书重建）；最后一次重启后 8 笔常规周期成交全部 ≤ 0.3 分钟。这些 bar 都有准点 cycle 行，说明迟到的是整本书重建，不是同 bar 重复下单。**降为运维项。**
修复（**[C 修订]** 按 KILL-R6）：不用"`now − last_close < 120 s` 才 immediate"（它会把 143 s 的补跑变成 57 分钟陈旧持仓、崩溃后最长 59 分钟无人对账）；改为两步——启动**始终**做只读对账 + 保护单核对（不下 rebalance 单），rebalance 部分才受窗口约束，窗口长度从 grace + ThrottleInterval + 启动耗时推导并写进 config；定义"补跑 vs 跳过"策略与漏掉 bar 计数器；trade 行打 `late_seconds`，M-010 剔除迟到入场的仓位（不重开计数）；M-Q03 口径改为"迟到入场仓位的 bar 小时占比"，基线取稳态 0/8。

**[🟡 中，原判高危] L1-02 无单实例锁；`newClientOrderId` 只在未完成订单间唯一**
位置：`starquant_live/execution.py:40-47`、`rebalancer.py:59-63`、`state.py:53-61`、`tests/fakes/fake_venue.py:126-127`
问题：MARKET 单成交后同 id 可再次被接受；两进程同 bar 并发会把仓位翻倍；fake venue 以 −4116 为不存在的保护背书。
复核：无锁属实（E-20）；`execute_order` 先 `query_order` 再下单，币安已成交订单可查 90 天（E-24），串行重复（重启后重跑同 bar）已被挡住。**[C 修订] 但"只剩竞态窗口"的概率论证不成立**（KILL-R20）：真实并发来源是本机 7–8 个 worktree——凭据由 `run_live.sh` 从 `~/.zshrc` 全局 eval、state_dir 与 kill switch 都是相对路径、`live run` 无 `--armed` 门、默认非 dry-run——在任一 worktree 里跑 `starquant live run --allow-unvalidated` 就是第二个交易同一账户的进程，锁文件各自独立、universe 回落到 `always_include`、非重叠仓位对主循环是 foreign；两进程由同一 scheduler 在 close+5 s 锁步唤醒，碰撞不是随机到达。且 Darwin 没有 `flock(1)`。**维持中危但升 P1 进 Phase A。** 修法：`fcntl.flock`，锁键绑定到 API key 指纹（`~/Library/Application Support/starquant/<sha256(api_key)[:16]>.lock`）而非目录，路径绝对化（与 L1-07 同修）；非 dry-run 的 `live run` 必须显式 `--armed` 且校验 `REPO` 与 plist WorkingDirectory 一致；`live flatten` 走同一把锁（先置 kill switch 再抢占）；被拒实例以退出码 0 退出并告警（避免 KeepAlive 每 60 s 重启）。

**[🟡 中] 影响 OOS 数字的其余项**
- F3 `best_params` 按全样本 argmax 入 registry，verdict 判的是逐 fold 混合序列（`research_cmd.py:459-463,544`）；报告应加 `best_key_oos_sharpe` 与 `selection_consistent`。
- F5 ※ validate/book 不重放 guards、不施加 exits，实盘两者都跑；影响已被 config 量化为很小（guards +0.005、stop −0.009），但启动门只比对信号参数（`research_cmd.py:443` vs `:265-274`）。
- F6 ledger 签名只含信号参数：band / vol_target / halflife / exits / fraction 的每一次扫描都不在 n_trials（`ledger.py:46-48`）；`--out` 可换出一本空账；P10 / P13 / D-039 三轮扫描靠手工 30→44 补。
- F8 + DATA-01 退市：REST 为退市币持续返回零量平价幽灵 bar（FTT 619 根、ALPACA 614 根）；成员表按 30 日成交额衰减 + exit_rank 20 滞回让退市币再当 26–28 天成员；LUNA 无价数据仍被 ffill 持有 27 天 / 690 币-bar；退出按 0 收益无结算价。代理内存重放三事件合计约 +3.8% 权益（E2）。实盘由交易所结算 + D-031 隔离自愈，回测无对等机制。
- DATA-03 资金费结算 t+1~47 ms 早于实盘 t+5 s 的成交，回测记给换仓后的 `executed[t]`，实盘由换仓前仓位承担（`backtest.py:194`）。周级信号下差异极小，但是 M-010 对账的残差来源。
- P1-02 离开 universe 的显式退出不进入 ffill 链：重新入选那根 bar 若分数 < 阈值，旧仓位原样复活（`model.py:125-129`；10 行数值复现）。方向未知。
- L1-04 滑点仪表参照 mark 而非 bar close，阈值 10 bps 拿含手续费的 7 bps 做比较；实测名义加权 +4.3 bps 是模型 2 bps 的两倍（E-19）。

**[🟡 中] 生产链路项**
- L1-03 熔断被 launchd KeepAlive + 持久化 `consecutive_errors` 抵消：跳闸后 60 s 重启即再跳，无退避；startup 失败不告警；`used_weight` 有写无读。
- L1-05 INSURANCE_CLEAR 等 income 类型静默丢弃；强平成交会被 D-032 归为 foreign（方向相反）；运行时零处强平可观测量（`attribution.py:8-30`）。
- L1-06 `live flatten` 不是停机：不启用 kill switch、不停循环，下一根循环原样重建仓位（2026-09-04 事故路径）。
- DATA-02 ※ manifest 对资金费归档失明（E-010）——**`main` 的 D-040 已修，实盘分支未合**（E-33）。
- P1-03 `entry_threshold` 从原始参数读并回落 1e-9，证据门比较规范化参数：漏写阈值时门看到 0.20、交易用 1e-9（E-022 语义静默回归；当前未触发）。

**[🔵 低] 24 项**（全文见审计原始输出，此处按主题合并）：warmup 漏 `crowding_window`（P1-04）；EWMA 协方差一个半衰期即输出、权重质量 50%（P1-05）；`pandas>=2.2` 的 `pct_change` 填充口径随版本变（P1-06）；sign 模式下 crowding 只抬高入场阈值 ※（P1-07）；flow `short_gate` 的事后设计 ※（P1-08）；换仓根资金费归属（P1-09）；book 的 sleeve 缺 `oos_selection` 块（F9）；回测入场价 = 决策 close、实盘 = venue VWAP ※（F10）；实盘 `lastFundingRate` 是前视预测值但未被消费（DATA-04）；研究 / 实盘池子四处小口径差（DATA-05）；6 币 14 处 1h 缺口不回填、重上市跳变连成一条序列（DATA-06）；D-013 文档仍写"按月"（DATA-07）；kill switch 路径相对 cwd（L1-07）；串行下单让账户级 −2019 推进单币隔离计数（L1-08）；启动撤销账户全部挂单（L1-09，**与条件单问题直接相关**）；抵押品权益进护栏 ※（L1-10）；告警无去重（L1-11）；主机时钟倒跳改写幂等键（L1-12）；dry-run 写实盘目录 ※（L1-13）；无 SIGTERM，归因追加与水位线保存非原子（L1-14）。

**已排除（命中可疑模式、读上下文后判合法）**：`labels.py:12,19` 的 `shift(-horizon)` 只供 IC 诊断；`walk_forward.py:48-51` 对 embargo 无效的论证正确；`backtest.py:117` `decided.shift(1)` + `open_to_close` 是保守口径；`panel.py:47` 年化因子由 bar 间隔推导；`backtest.py:35` 7 bps 非零成本 + 实际资金费；全仓库无 bfill / interpolate / center=True / 全样本 scaler / shuffle 切分；`drop_unclosed` 四处统一；成员表严格用刷新日之前的数据；`guard.py` host 白名单 + kill-switch reduce-only 直通；`execution.py` 的 OrderOutcomeUnknown 先查后发。共 60 条排除记录。

**超出清单的良好实践**：追加式 ledger 直接作 DSR 分母；D-023 信号自声明资金费依赖、拿不到即拒绝启动；D-026 构造指纹每周期落盘；M-011 每小时离线复算上一周期输出；`risk_budget.py` 算不出即 `enforced: false` 而非报 0；D-032 三段 join 剔除外来成交且对账失败时退回全额归因；exit overlay 与护栏单点定义、回测实盘共用；registry 注释把每次证据更替的原因写在参数旁边。

**偏差影响（方向判断，非收益预测）**：无致命项，当前 OOS 指标可作讨论基础。P1-01 使实盘 crowding 更频繁触发，方向未知；F1/F2 使"PASS"的证据强度被高估但 tsmom 本身在严格门下仍过；退市幽灵 bar 使 pit 证据略偏乐观（约 +3.8%，集中在三个事件）；迟到成交与 4.3 bps 滑点使**实盘低于回测**；参与率与冲击（前审）在 10 万 USDT 以上才开始绑定。

### 4.2 第二遍 · 逻辑对抗审查（非代码证据）

**[🟡 中·逻辑] Ⅰ edge 来源：已陈述，尚未被实盘检验**
依据：`tsmom.py` docstring（2026-09-05）——承担散户消化过慢的趋势风险，对手盘是后知后觉的杠杆多头，行为性、预期衰减；carry rank 模式 5 年毛收益 −6% 排除了"伪装的资金费套利"。本轮加一条测量：书与等权多头相关 −0.12，多空各 0.43，不是 crypto beta（E-09）。
未答：衰减半衰期没有估计。走前五 fold [1.45, 0.50, 2.51, 1.10, 2.66]（crowding off）没有单调下降，但五个观测不足以说"没有衰减"。**待作者答复**：用什么统计在实盘期检测衰减（建议：M-010 的 30 天滚动 Sharpe 对回测同期分布的分位数，预登记"连续两个 30 天窗口 < 回测 q10 即复审"）。

**[🟡 中·逻辑] Ⅱ 容量：下界已测，上界未测**
依据：前审参与率表（E-28）——10 万 USDT 时 4.25% 目标换手做不掉，100 万时 28.6%；这是被拒绝部分的下界，不含成交部分的冲击。成本模型平 7 bps 与任何下单量无关。
失效场景：若真实资金进入 10 万 USDT 量级而 `vol_target` 仍按平成本模型推导的 0.30 运行，实际净 Sharpe 会低于回测且方向可预判（换手 385/年 × 名义）。
缓解：KILL-A 的冲击模型（平方根法则 `σ·(Q/ADV)^0.5` 起步）作为真实资金前置，把 10 万 USDT 写成 config 硬门槛（前审已建议，本轮升为 KILL-Q12）。

**[🔵 低·逻辑] Ⅲ 失效 regime：已回放，结论明确**
依据：E-10 **[C 修订]** 九个压力窗口七正两负（补入 2021-05-10→05-23：书 +2.4%、05-19 当日 +4.2%，当日多空各半——KILL-R23 指出该窗口在样本内而 09-05 版误写为不在）；两个负窗口（FTX −5.3%、SVB −3.1%）都是"急反转"而非"崩盘"；最差单小时 −6.24%（2021-09-07 萨尔瓦多日闪崩），7 小时 < −3%；最长回撤 112 天、最深 −22.1%（两次，E-11 已按新高之间的谷底重提取并复核）。样本不含 2020-03。
可证伪的失效场景：若出现"多币同时 V 形反转 + 资金费急变"（2023-03 形态放大），书会连亏数周而止损不会触发（止损量的是从入场的 6σ，本书的损失是慢积累，P11 已测）。
缓解：不是加止损，是 `daily_loss_pause`（已在）与 P13 阶梯（−35% → 0.225）——两者都在，且已回放。本项闭合。

**[🟡 中·逻辑] Ⅳ 隐藏风险：集中度与探针书**
依据：单交易所（Binance）、单数据源（mainnet 公共数据）、单时间框架（1h）、单主机（launchd）；flow 探针 91% 币-bar 与 tsmom 同向（KILL-030），本轮 P1-01 又指出它的去均值参照也不是验证时的那个。
失效场景：若币安 API 封禁 IP 或主机宕机，`run_check.sh` 与循环同机同用户，两者一起沉默；仓位无人管理直到操作者发现。**[C 修订]** 更具体：IP 封禁 / venue 故障时循环走 ERROR 分支，每次重写心跳且退避上限 3,600 s < 2 根 bar，`live status --check` 只在 `consecutive_errors ≥ 3` 才报 ERROR——循环可以连续 12 小时下不了单而心跳始终"新鲜"（KILL-R2）。
缓解：远端可挂起的 kill switch + 循环主动推送心跳（§7.2，**[C 修订]** 替代 09-05 版的"异机读心跳文件 → flatten"设计）。探针书：P1-01 修后重跑 book 报告，若仍 REJECT 则按 D-029 的 30 天复审停书。

**[🟡 中·逻辑] Ⅴ 流程与运维（按第一遍规则给 文件:行）**
已实现：kill-switch 文件（`guard.py:55-58`）、`flatten`（`live_cmd.py:314-344`）、对账（`reconciler.py`、`verify.py` M-011）、心跳 + 小时检查（`run_check.sh`）、边沿触发告警（`engine.py:777-795`）、hedge-mode 断言（`engine.py:172-174`）。
未见实现：单实例锁；远端停机；强平距离监控；SIGTERM 优雅停机；告警去重与第二通道；`flatten` 与 kill-switch 的顺序契约；**[C 修订]** registry 参数 digest 逐周期落盘（KILL-Q15 的仪表）；保证金模式（CROSSED / multiAssetsMargin）断言；`~/Library/Application Support/starquant/env.sh` 并不存在，密钥实际由 `run_live.sh:18` 对 `~/.zshrc` 的 eval 取得。**待作者确认**：密钥轮换与 IP 白名单是否在仓库之外有流程。

风险评级：🟡 中（demo 阶段）/ 🟠 高（若以现状直接进入真实资金）

上真实资金前，作者必须回答的三个问题：
1. 修正横截面参照总体后，crowding 修饰器与 flow 探针在同口径下还剩多少证据？（**[C 修订]** 前置：先让 registry 与循环一致——此刻两者不一致。）
2. 冲击成本模型下，0.30 的 `vol_target` 与 10 万 USDT 的容量拐点各是多少？
3. 循环失联（进程死 / 主机死 / IP 封禁 / 循环存活但下不了单）后，谁在多久内把仓位平掉、又由谁阻止循环在下一根 bar 原样重建？

建议优先级（**[C 修订]**）：重启前使 registry / 循环 / 证据一致 → 合并 be963ad 与 main → 修 P1-01 契约并重跑证据 → 修 F1/F2/F3/F6 让尺子准 → 一次性重启并冻结构造 → 再扩因子空间。

### 4.3 高危项复核记录（同一 Agent，锚定风险已声明）

| 发现 | 复核方式 | 结论 |
| --- | --- | --- |
| P1-01 | 逐行读 `tsmom.py`、`flow.py`、`model.py`、`research_cmd.py`、`engine.py`；核对 universe.json 15 币 | 机制成立；数字为代理复算（E2）；维持高危 |
| F1 | 读 `walk_forward_evaluate`、`decide`、validate 命令 | 成立；部分披露；维持高危（标注类） |
| F2 | 读 `oos_selection_threshold`、`expected_max_sharpe`；反算 | 成立；维持高危 |
| L1-01 | 由 `trades.jsonl` 独立复算 | 成立且数字一致；维持高危 → **[C 修订]** 归因被 KILL-R6 推翻（稳态 0/8），降为运维项 |
| L1-02 | 读 `execute_order`、grep 锁；核对币安 id 语义 | 成立但 query-before-submit 覆盖串行情形；降为中危 → **[C 修订]** 并发来源是 worktree 而非竞态，升 P1 进 Phase A |
| **[C]** KILL-R1 / Q15 | `state.json.restarted_at` vs `git log 3ac8d49`；`cycles.jsonl` 88 行 `funding_history`；`inputs.py:65-68`；`engine.py:849-899` | **成立**（E-35）；升为本轮头号 P0 |
| **[C]** KILL-R3 | 在当前构造跑 16 点网格 validate（scratch） | tsmom 诚实网格 OOS 1.485 > FWER 阈值 1.445–1.466；**关闭**，headroom 0.02–0.04 写进 §0（E-36） → **[执行]** 关闭依据仍成立但 headroom 比当时窄得多：E-40 在 N=125 上 headroom 0.003 / 0.017（§12.7）；处置见 §12.5–12.7 |
| **[C]** KILL-R4 | 读 `RESEARCH_LOG:732-760`、`research_cmd.py:374-378` | **成立**：holdout 不启用是操作者裁决；F1 处方撤回 holdout 必选（E-38） |
| **[C]** KILL-R6 | 按周期重算 `trades.jsonl`（重启后 23 笔：15 笔来自 17:21 重启周期，8 笔常规 ≤ 0.3 分钟） | **成立**：73% 是开发期比率（E-18） |
| **[C]** KILL-R14 | 读 `state.json.exit_states.*.unit` | **成立**：7/18 个名字 18 单位止损不可下单（E-37） |
| **[C]** KILL-R24 | 用"新高之间的谷底"重提取回撤 | **不成立**：两对重合深度为真实巧合，E-11 保留并加注 |

---

## 5. Phase 3 · Problem Research

**Problem Statement**：对于单一操作者，当他试图把一本小时级、周尺度动量的加密永续书从 demo 推到真实资金时，由于 (a) 验证管线的"OOS"与"选择门"对 Sharpe 1.0–1.4 的候选没有区分力、(b) 信号 / 挖掘可读的数据只有 5 个字段且面板缺 6 类永续特有数据、(c) 实盘与验证之间仍有三处口径漂移（横截面总体、迟到成交、退市结算）、(d) 生产链路缺单实例 / 看门狗 / 强平可观测量，会遇到"加候选也筛不出、筛出也不敢信、信了也不敢放钱"的困境；如果不解决，将造成 alpha 投入的 90% 花在一把不准的尺子上。

**Causal Chain**：表层现象"策略太少、是玩具" → 直接原因：5 个信号被诚实否决、挖掘阴性 → 深层原因：可表达空间窄 + 数据窄 + 验证门弱 → 系统性原因：证据纪律先于产能建设（正确的顺序，但产能一侧欠账） → 可干预杠杆：先修尺子（F1/F2/F3/F6/P1-01），再扩空间（节点 + 数据），再自动化（GP + ledger）。

**JTBD**：当我在 demo 上看到 tsmom 连续盈利时，我想要一个能可信地告诉我"下一个候选该不该上、放多少钱"的系统，以便把真实资金放进去而不必自己再当一遍 Evidence Prosecutor。

**Edge Cases**（进入 §10 契约）：横截面算子在 n<20 时的分位数粒度；退市 / 改名（RNDR→RENDER）；demo 账户重置（E-044）；重启落在 bar 中间；LLM 提案与 ledger 的边界。

---

## 6. Phase 4 · 对标评分与相对价值

### 6.1 评分矩阵（1–10；用途：加密永续、小时级、单操作者、无人值守；评分为本轮判断，E4/E5）

权重：alpha_research 0.15 · factor_mining 0.10 · validation 0.15 · backtest_realism 0.15 · execution 0.12 · risk 0.10 · data 0.08 · ops 0.06 · testing 0.05 · docs/community 0.04

| 系统 | ★ | 数据 | alpha 研究 | 因子挖掘 | 验证严谨 | 回测真实 | 执行 | 风控 | 运维可观测 | 测试工程 | 文档社区 | **加权** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **StarQuant** | — | 4 | 4 | 3 | **6（修 F1/F2/F6 后 8）** | 6 | 4 | 6 | 5 | 7 | 5 | **4.95–5.25** |
| QuantConnect Lean | 18k | 9 | 6 | 3 | 4 | 8 | 8 | 7 | 8 | 8 | 9 | 6.62 |
| nautilus_trader | 28.4k | 8 | 4 | 2 | 3 | 9 | 10 | 8 | 7 | 9 | 7 | 6.39 |
| freqtrade (+FreqAI) | 54k | 7 | 5 | 4 | 4 | 6 | 8 | 6 | 9 | 8 | 10 | 6.11 |
| Qlib | 未核 | 8 | 9 | 7 | 5 | 5 | 3 | 4 | 5 | 7 | 9 | 5.96 |
| hummingbot | 19.8k | 7 | 3 | 2 | 2 | 5 | 9 | 6 | 8 | 7 | 8 | 5.09 |
| vnpy | 未核 | 6 | 4 | 2 | 3 | 5 | 8 | 6 | 7 | 5 | 7 | 4.99 |
| jesse | 7.6k | 6 | 4 | 2 | 3 | 5 | 6 | 5 | 6 | 6 | 7 | 4.64 |
| passivbot | 2.1k | 5 | 3 | 2 | 2 | 6 | 7 | 5 | 6 | 5 | 5 | 4.40 |
| RD-Agent (quant) | 14.5k | 3 | 7 | 9 | 3 | 4 | 1 | 1 | 4 | 5 | 7 | 4.23 |
| zipline-reloaded (+alphalens) | 20k | 5 | 6 | 3 | 4 | 5 | 2 | 3 | 2 | 6 | 7 | 4.19 |
| OctoBot | 5.5k | 6 | 3 | 2 | 2 | 4 | 6 | 4 | 7 | 5 | 6 | 4.06 |
| backtrader | 21k | 5 | 4 | 1 | 2 | 5 | 4 | 3 | 3 | 5 | 7 | 3.64 |
| mlfinlab / AFML（参考工具集） | — | — | — | 4 | 9 | — | — | — | — | — | — | 参考 |

**[C 修订]** 本表为作者判断（E4/E5）：Qlib / vnpy 未抓取、每格无引用证据、名次对权重敏感（把 0.05 权重从验证移到执行，StarQuant 5.05 落到 vnpy 5.24 之后；等权下StarQuant 5.20 vs hummingbot 5.70）。它是附录级参考，不是 Decision Memo 的依据；"是不是玩具"用 §0 答案①的硬数字回答。StarQuant验证维度从 8 下调为 6：同一份报告不能一边给验证维度全表最高分，一边判定该管线"噪声通过率 43.5%、OOS 九成是样本内、 ledger 对三轮扫描失明"。

StarQuant各维度评分依据：数据 4（1h OHLCV + 资金费 + 时点成员表；无 OI / 基差 / 多空比 / 清算 / 盘口，E-03）；alpha 4（7 信号 1 主书；分解 / 相关 / book 工具完备，库小）；挖掘 3（类型化枚举、阴性结果、mined 候选进不了 validate，E-16）；验证 6（WF / CPCV / PBO / DSR / NW / ledger / 启动门的骨架完整，扣 F1/F2/F6 与 KILL-Q15；修后 8）；回测真实 6（t/t+1、成本 + 实际资金费、护栏与强平仪表重放；扣参与率、冲击、退市结算、幽灵 bar）；执行 4（REST 轮询、只 MARKET、无 WS、无锁、迟到成交）；风控 6（波动目标 + 上限 + 护栏 + 风险预算阶梯 + 隔离；无强平监控与保险）；运维 5（launchd / 心跳 / 小时检查 / 日报 / webhook；无去重、外部看门狗、单实例）；测试 7（7.5k 行、架构比率、因果测试、mypy strict）；文档社区 5（内部文档极强、社区为零）。

### 6.2 StarQuant vs 同类：强项与弱项

强项（同类中少见）：
1. 追加式 trials ledger 直接作 DSR 分母，跨运行不可绕过（无一对标项目有）。
2. 启动证据门：registry 参数 + 构造参数 + sha256 对报告（KILL-027 的结构性关闭）。
3. 时点成员表消除幸存者偏差（freqtrade 的 pairlist 只在实盘做，回测不做）。
4. 资金费按包含结算的 bar 对齐并写下 43.7% 漏计的后果（D-034）。
5. 回测重放实盘护栏与强平 headroom（D-036 / M-016）。
6. 每小时离线复算上一周期输出（M-011）——nautilus 靠同引擎做到，StarQuant靠复算做到。
7. 归因剔除非本循环成交（D-032）。
8. 决策日志把"被否决的假设"与"证据的口径变更"写在参数旁。

弱项（对标项目做得更好）：
1. 执行层：nautilus / hummingbot / freqtrade 都有用户数据流、订单状态机、限价 / post-only、条件单生命周期；StarQuant只有整点 REST 轮询 + MARKET。
2. 数据宽度：freqtrade / nautilus / Lean 接 OI、盘口、成交流；StarQuant只有 K 线 + 资金费。
3. 因子库与挖掘：Qlib Alpha158/360 + RD-Agent 循环；AlphaGen 的 RL 搜索；StarQuant 12 节点枚举。
4. 前视检测工具：freqtrade 的 `lookahead-analysis` / `recursive-analysis` 子命令把因果性测试产品化；StarQuant有因果测试但只到信号层（审计建议扩到 targets / build_weights）。
5. 退市 / 改名：Lean 与 nautilus 有合约生命周期；StarQuant回测在幽灵 bar 上持仓。
6. 运维：freqtrade 的 Telegram / FreqUI / docker、hummingbot 的 dashboard；StarQuant只有 webhook 与 markdown 日报。
7. 止损：freqtrade `stoploss_on_exchange`（入场即挂、60 s 刷新、被撤重挂、失败回退市价）是完整的原生单生命周期参考实现。
8. 社区：零。

### 6.3 可借鉴项（去重后按价值 / 成本排序）

| 借鉴 | 来源 | 工作量 | 价值 | 触及决策 |
| --- | --- | --- | --- | --- |
| 因果性测试扩到 `strategy_targets` / `build_weights`（替换 cutoff 之后数据，断言之前不变） | freqtrade lookahead-analysis 思路 | S | 高（P1-02 类问题在类型层被拒） | — |
| 原生止损生命周期（挂 / 刷新 / 被撤重挂 / 失败回退市价） | freqtrade stoploss_on_exchange | M | 中（仅作保险） | D-012 |
| 合约生命周期（退市日历 + 结算价） | Lean / nautilus | M | 高（F8 / DATA-01） | D-013 |
| 用户数据流（listenKey + ws）替代整点轮询 | nautilus / hummingbot | M–L | 高（真实资金前） | D-003 |
| 因子 tearsheet（IC / ICIR / 分位收益 / 换手） | alphalens / Qlib | M | 中（挖掘候选筛选前置） | — |
| 表达式空间的 RL/GP 搜索以"组合边际"为奖励 | AlphaGen | L | 中（需先扩空间） | P17 |
| LLM 提案 + AST 原创性正则 | AlphaAgent | L | 低（ledger 外可用） | P17 |
| 评估指标从单 ARR 改为 IC + 组合边际 + FWER | 对 RD-Agent 的反面教训 | S | 高 | D-020/D-028 |

### 6.4 "是不是玩具"的诚实回答

**[C 修订]** 先给硬数字：当前构造 38 根干净 bar、归因 ≈ −10 USDT（−0.1% 权益）——**尚无任何盈利证据，且按功效计算一年内不可能有**（30 天窗口年化 Sharpe SE ≈ 3.5，t=2 下把 1.7 与 0 分开需约 1.4 年构造不变的数据；而 88 个周期已经历 4 个构造）。所以"demo 持续盈利证据"这个目标必须改写为 demo 真正能证明的两件事：**执行保真**（换手 vs 回测、滑点 vs 模型、迟到成交、registry ≡ 循环）与**无人值守存活**（连续无人干预天数、失联后自动停机）。

再按维度：对"无人值守、单操作者、小时级、demo 资金"这个用途，**证据纪律 / 回测口径的骨架在生产线以上**（追加式 ledger、启动门、时点成员表、资金费对齐、护栏重放——多数开源系统从未做到），但本轮发现它的三处口径漂移（KILL-Q15、P1-01、F1/F2）说明骨架有、仪表不全；**执行、数据、生产链路三个维度在生产线以下**；社区 / 文档 / 多交易所对本用途**不相关**。真实资金的门槛见 §11 与附录 D。

### 6.5 Relative Value 与 Option Set（G3/G4）

| Option | 内容 | 成本 | 风险 | 可逆 | 结论 |
| --- | --- | --- | --- | --- | --- |
| No-Build | 只跑 demo 攒 M-010 样本 | 0 | 尺子不准、 holdout 期不可比 | — | 对照 |
| Small-Build（推荐 Phase A） | 第 0 步 registry/循环一致化 + 合并列车（be963ad、main）+ 修 P1-01 契约 / F1 / F2 / F3 / F6 / L1-01 / L1-02 + 5 个只读现有列的 Expr 节点 + mined 进 validate（一本 ledger） | **[C 修订]** 3 周；alpha 占比按仪表口径约 60%、按"信号/因子"口径约 50%（原因是先修尺子） | 低，全部可逆 | 高 | **推荐** |
| Full-Build（Phase B） | metrics / premiumIndex / markPrice 数据摄入（含同源契约）+ 退市日历 + 远端 kill switch + 心跳外推 + 强平可观测（REST） | 4 周 | 中 | 高 | 推荐（A 之后） |
| System-Build | GP 搜索、线性组合器、LLM 离线助理 | 6+ 周 | 中高 | 中 | Phase C，按证据决定；**[C 修订]** 用户数据流与原生条件单移入 Won't / 附录 D |
| LLM 提案者进 ledger 路径 | — | 高 | 破坏可交换抽样与离线 CI | 低 | **KILL（维持 P17）** |

20% 成本拿 80% 结果的方案存在：Phase A 的前四项（P1-01、F1/F2、`--immediate`、锁）合计不到一周，却把证据的可信度从"部分自证"推到"可自证"。

---

## 7. Phase 5/6 · 模块分析与方案

### 7.1 Alpha 供给与挖掘自动化

**7.1.1 现状（E-04..E-06）**：7 个信号；`Expr` 12 节点（Const/Ret/Vol/VolumeRatio/TakerBuy/Ratio/ZScore/CrossSectional/Squash/Sum/Mul/RangePosition），量纲规则拒绝跨量纲相除；7 族 225 候选；`to_signal` 桥接存在但 validate 寻址不到 `mined_*`（F7）；mine 报告不记 costs / funding / execution / profile，跨运行不累计申报（KILL-P17-08）。库里有而任何信号 / 节点读不到的列：open、volume(base)、trades、taker_buy_base、mark_price。

**7.1.2 因子空间缺口（在 P17 的 20 条上扩展）**

| 类别 | 例子 | 状态 | 打开方式 |
| --- | --- | --- | --- |
| 已可表达 | tsmom / xsmom / 反转 / 通道 / regime / 成交量惊奇 / 主动买卖 | 已搜（阴性） | — |
| 缺节点、数据在库 | 资金费 carry、资金费横截面拥挤、资金费动量 / 期限结构、特质波动、残差动量、半方差、偏度、Amihud、成交笔数 / 均单大小（trades 列）、mark−close 基差代理（mark_price 列） | 10 条 | `Funding`（Dim.RETURN）、`Abs`、`Moment(k)`、`Semi`、`Beta/Residual`、`Trades`、`MarkGap` 六个叶 / 算子节点 |
| 缺数据、公共归档可得 | OI 水平 / 变化、多空账户比、大户持仓比、taker 多空量比、永续溢价指数、mark/index 价格、盘口深度快照 | 7 条 | data.binance.vision `metrics`（BTCUSDT 自 2020-09-01）、`premiumIndexKlines`、`markPriceKlines`、`bookDepth`（E-22） |
| 缺数据、需第三方 / 不可得 | 清算量（`liquidationSnapshot` 本轮查询为空）、现货基差（需 spot 归档）、流通量换手 | 3 条 | 现货 K 线归档可得；清算量待查 |
| 需新信号类型 | 事件驱动（上市 / 退市 / 资金费结算窗口）、日内季节性（时点、星期、结算前后） | 4 条 | 不在表达式语言内，独立提案 |

**7.1.3 自动化 Option Set**

| 方案 | 做什么 | 依赖 / LoC | 候选吞吐 | 试验计数 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A 扩枚举 | 6 节点 + 数据源，同一枚举器 | 纯 numpy，~600 行 | 数百 / 轮 | 按族预登记、`declared_trials` 跨运行累计 | **先做** |
| B GP / 符号回归 | 在类型化 `Expr` 上做变异 / 交叉，适应度 = 组合边际 Sharpe（成本 ×2） | 纯 numpy，~800 行 | 数千 / 轮 | 固定评估预算（如 2,000 次 / 轮）计为 N；预注册族 | Phase C，A 阴性后 |
| C RL（AlphaGen 式） | 策略网络生成表达式 | 需 torch，破坏纯 numpy 与离线 CI | 高 | 与 B 同 | 不做（成本 / 收益不成比） |
| D ML 组合器 | 对已通过的因子做岭回归 / 线性组合 | numpy，~200 行 | — | 组合参数进 ledger | Phase C |
| E LLM 提案者进 ledger 路径 | — | LLM 依赖 | — | 自适应提案破坏可交换性 | **KILL（P17）** |
| F LLM 离线助理 | 读日志 / 报告写假设、生成节点候选、扮演 Evidence Prosecutor 审报告；输出进 `proposals.jsonl`，人工挑选后按 A 走 | 无运行时依赖 | — | 提案不计费，被选中的族按 A 计费 | **可做** |

**7.1.4 试验计数协议（扩空间的前提，KILL-Q8 的缓解）** **[C 修订]** 按 KILL-R8 / R16 / R17 / R4 重写——规则净变化 ≤ 0，且每条都有执行主体：
1. 每个族在跑之前写进 RESEARCH_LOG（节点、参数网格、预期、falsifier），且该提交的时间戳必须早于第一份报告；`report weekly` 校验时间顺序。
2. **一本 ledger**：`mine` 每轮把 `declared_trials` 作为 `TrialRecord`（strategy 取族名、param_key 取候选 hash、sharpe 取全样本值）经现有 `_record_trial` 追加到 `trials.jsonl`；validate 对 `mined_*` 的先验计数从同一 ledger 按族聚合。不建第二本 `mining_ledger.jsonl`。"搜索空间版本"进 ledger 签名（新增节点后旧候选的哈希与计数按版本隔离）。mined 候选的持久身份 = registry 存表达式字符串、按表达式解析，实盘 / verify / report 共用解析入口（否则 registry 一旦指向 `mined_<hash>`，`live run` 建模即 KeyError）。
3. 阴性对照用**已有的** `noise_null`（`multiple_testing.py:93,268`），不新增"每轮 20 个随机表达式"这第五个零假设。
4. holdout：**不启用**（KILL-006 §二，操作者裁决，E-38）；实盘期是唯一 holdout。
5. 晋级节奏做成机械规则：7 天内已有一次 PASS 晋级则 validate 拒绝写 registry 指针（ledger 层强制），validate 本身不限次；否则该条从协议删除并把 KILL-Q8 记回 OPEN。
6. FWER 门（F2 修法）取 α = 0.05、N 用 N_eff；同一提交把 `pass_oos_t` / `weak_oos_t` 降为 reported-not-enforced（docstring 与操作者记忆已写明它不构成第二条件）。
7. 计费与提案者无关：到达 validate 的每个候选必被计费；不区分 LLM 与人。

**7.1.5 LLM 的位置** **[C 修订]**：09-05 版写"允许离线助理、禁止评估候选 / 写 ledger / 进入 CI"。复核指出这条规则没有执行主体——仓库最近 200 次提交里 129 次由 LLM 共同署名，P11–P17 的预登记、validate、registry 重指、RESEARCH_LOG 条目都出自 LLM 会话，本报告本身也是。因此改写为**与提案者无关的机械规则**（7.1.4 的第 1、2、5、7 条）：谁提案不重要，进 ledger 才重要。LLM 可以做的事不变（读日志写假设、节点草稿进 PR、扮演反方、写 docstring），但"可以"不再是控制手段，ledger 与时间戳才是。A-004（自适应提案破坏可交换性）对现在的"人 + LLM"循环同样适用——P17、D-039 都是条件于上轮结果的提案——所以第 1 条的时间顺序校验是它的最小缓解，不是对 LLM 的特别限制。

**7.1.6 预登记 falsifier（Phase A 结束时裁决）**：在 `vol_target 0.30`、pit universe、成本 ×2 下重跑 225 + 六个新族；成功 = 至少一个候选对 tsmom 的边际 Sharpe ≥ +0.05 且与 tsmom 相关 < 0.5 且通过 FWER 门；失败 = 记阴性、转 Phase B 的数据宽度。

### 7.2 止盈止损：交易所条件单 vs 软件层

**现状（E-30）**：`exit_step` 在 bar 收盘评估，阈值以入场时日波动为单位，止损 6 / 止盈 6 / 冷却 24；实盘方向以交易所为准、入场价首入锚定；实盘 2.4 天零触发；回测 49,735 bar 触发 18 次止损 + 544 次止盈；止损"不保护任何可测量的东西"（P11）；每一档移动止损都损失 0.15–0.22 OOS Sharpe。

**币安事实（E-21）**：2025-12-09 起条件单只能走 `POST /fapi/v1/algoOrder`；`closePosition=true` 平掉整个方向、不能带 quantity/reduceOnly；`workingType` 默认 CONTRACT_PRICE，可选 MARK_PRICE；`priceProtect` 限制标记价与合约价偏离；demo-fapi 是否支持 algoOrder **UNKNOWN**（15 分钟可测）。

**本书的 bar 间风险（E-09）**：整本书最坏单小时 −6.24%，7 小时 < −3%；单币 `max_weight 0.15` 下一个币 −30% 的小时 ≤ 4.5% 权益；`daily_loss_pause −5%` 与 P13 阶梯在护栏一侧已回放。

**2×2**

| | 作为 alpha 改进（更高 Sharpe / 更浅回撤） | 作为灾难保险（loop 失联 / 单币跳空） |
| --- | --- | --- |
| 软件 bar 收盘 | 证据为负或为零（D-017 三轮）；**维持现状、不调参** | 只覆盖循环活着的情形；最坏单小时 −6.24% 可承受 |
| 交易所原生 | **否**：demo 日内路径合成无法调参；1h bar 回测无法模拟 bar 内触发；与每小时再平衡的撤 / 重挂 churn 与竞态；legacy E-033 事故 | **有条件是**：远端 STOP_MARKET `closePosition=true`、MARK_PRICE、`priceProtect`，距离 = 3× 软件止损（≈18 日波动单位，回测中理应零触发）；只在循环失联时有价值 |

**建议** **[C 修订]**（09-05 版的两条建议都被复核推翻：外部看门狗按现有代码不可交付——心跳是本机文件、ERROR 分支每 60 s 刷新心跳、`flatten` 不停循环、kill switch 只能本地挂起、币安 key 无 reduce-only 作用域（E4）、任何 > 2 小时的维护窗口都会把健康的书平掉；原生灾难止损在 18 币中 7 个上不可下单（E-37），且违反 D-012 自己预登记的重开条件"进入 mainnet 且信号进入日内"）：
1. **远端停机（demo 范围内，Phase B）**，规格见 DL-Q8：① 循环每周期**主动推送**"本周期 OK"（含 phase / consecutive_errors / registry digest）到异机或云端；② 触发 = 连续 N bar 无 OK 推送，或 phase == ERROR ∧ consecutive_errors ≥ N——不是文件年龄；③ 远端可挂起的 kill switch（循环轮询远端 sentinel / dead-man lease，取不到即本地 engage 进 reduce-only），动作顺序固定为**先停交易权再平仓**；④ 不依赖 model / universe / store 的 `flatten --raw`（`positionRisk` → 全部 reduce-only MARKET），只平 `bd-` 前缀对得上的仓位，不碰 `foreign_positions`；⑤ 看门狗主机只持只读 key、只做告警；失联平仓交给交易所侧机制或本机 kill switch；⑥ 陈旧判定以场地时间为准（D-030）；⑦ 维护模式 sentinel 与演练脚本（`launchctl unload` → 计时 → 验证 → reload），falsifier 含"循环存活但心跳迟到不得触发"与"flatten 后 3 bar 内零新增仓位"，演练加封 venue 出口与两机断网两条路径。
2. 原生"灾难止损"**降为 Won't**（D-012 防火墙原样维持，KILL-Q10 CLOSED-范围外）。将来重开须先记录"重开条件由 mainnet + 日内 改为 X"的决策，且距离必须按符号分层：`min(k·unit, 固定价格百分比上限)`，多头做 price > 0 可下单性断言；同时 `guard.py` 的 `ORDER_PATHS` 必须先加入 `/fapi/v1/algoOrder`（现在对该路径一律视为降风险，kill switch 下会放行风险增加型 algo 单）。
3. **明确不做**：用原生单替代软件层的止盈、移动止损、或任何以"提高 Sharpe"为目标的参数。

### 7.3 自适应下单量与杠杆

**下单量（E-29）**：现有——参与率上限 2%（仅加仓与部分减仓）、保证金按可用余额缩放、min_notional、量化到 step。缺口按证据强度排序：
1. **冲击成本模型（KILL-A / KILL-Q12）**：真实资金前提；平方根法则起步，参数由前审的参与率表与 E-19 的 4.3 bps 校准；`vol_target` 在该模型下重推。
2. **`--immediate` 迟到成交（L1-01）**：一行修复，先于一切执行优化。
3. **滑点仪表参照与阈值（L1-04）**：对 bar close 计算、阈值用 2 bps 及 1.5×/2× 压力档。
4. **名义档位**：`leverage_brackets()` 只读首档，不读 `notionalCap`（P15 §3）；真实资金 + 薄币可触及；加启动校验。
5. **被动执行 / TWAP**：成本占毛利 7–10%，理论空间 +0.1 Sharpe 量级，但 demo 成交量合成**无法测量**（KILL-Q14 ACCEPTED）；推迟到小额真实资金阶段，且只对超过参与率上限的单拆分。

**杠杆（D-037，维持 KILL）**：仓位 = 权重 × 权益；MMR 按名义档位；L≥3 时保证金不绑定。本轮补两条分析：(a) **逐仓作为爆炸半径控制**——5x 逐仓下每仓保证金 3% 权益，20% 不利即被强平，而 tsmom 常规持仓穿越 20% 回撤（E-11 单币尾部 −2.1%…−3.8% 是权益口径，价格口径远大于 20%），逐仓会制造策略不想要的强平 → 否；(b) **名义档位上限**——唯一新的目标函数，做成校验不做成"自适应"。多资产抵押品下权益随 BTC 漂移（KILL-033 ACCEPTED）不改变以上结论。

### 7.4 生产就绪清单 **[C 修订]**：拆成"demo 无人值守最小集"（进 12 周路线图）与"mainnet pre-flight backlog"（附录 D，只在操作者重开 mainnet 时启动）

demo 无人值守最小集（按 ratchet 记账：每行给出落点包与预计行数 / 对应删除项）：

| 优先 | 项 | 来源 | 落点 / 行数 / 删除项 |
| --- | --- | --- | --- |
| P0 | registry 参数 digest 逐周期落盘 + `live status --check` 比对磁盘 vs 已加载模型 | KILL-Q15 | live +≈50；删：无（抬 ceiling 并记理由） |
| P0 | 单实例锁（`fcntl.flock`，键 = API key 指纹，绝对路径）+ `--armed` 门 + `flatten` 同锁 | L1-02 / KILL-R20 | live/cli +≈80；删：`state.consecutive_errors` 持久化（−） |
| P0 | 熔断跳闸 → 告警 → `sys.exit(0)`（KeepAlive 的 SuccessfulExit=false 已保证不重启） | L1-03 / KILL-R29 | live ±0；**删除** 09-05 版的 TRIPPED 标记 / 退避计数器交付项 |
| P0 | 启动始终只读对账 + 保护单核对；rebalance 受推导窗口约束；`late_seconds` 标签 | L1-01 / KILL-R6 | live +≈40 |
| P1 | 告警去重（按指纹、边沿触发）+ 第二通道 | L1-11 | live +≈30 |
| P1 | 远端停机（DL-Q8 七点）+ 心跳外推 | KILL-Q16 | live/deploy +≈150；先于任何看门狗 |
| P1 | 强平可观测：`positionRisk.liquidationPrice` 距离 + `/fapi/v1/forceOrders` 一次 GET + INSURANCE_CLEAR 桶 + 保证金模式（CROSSED / multiAssets）断言 | L1-05 / KILL-R18 | exchange/live +≈60；**用户数据流（ws）删除**：httpx 无 ws 客户端、依赖白名单不含 ws 库、与"交易所仓位是唯一真值"冲突 |
| P1 | 启动只撤本循环挂单（`bd-`/`bdflat-` 前缀）；kill-switch 路径绝对化；`flatten` 先 kill-switch | L1-06 / L1-07 / L1-09 | live +≈20 |
| P1 | SIGTERM 优雅停机；归因追加与水位线原子化 | L1-14 | live +≈30 |
| P1 | 合并 `main`（D-040 / D-041 / 304e549）与 `feat/mining-funding-node`（be963ad）——合并列车先于一切代码改动 | E-33 | +199 非 alpha 已在 main 抬升；alpha +≈1,100（be963ad） |
| P1 | 退市日历 + 回测结算 + 幽灵 bar 掩码 | DATA-01 / F8 | data/alpha +≈200 |
| P2 | 请求权重预算、418 冷却；ledger 轮转；exchangeInfo 逐日快照 | 审计 | S |

每一项都以 `tests/architecture/test_source_budget.py` 的 CEILING 记账为 DoD 的一部分：六个包此刻全部恰好顶在上限（alpha 4876 / live 4198 / cli 2582 / data 1258 / exchange 539 / shared 280），任何净增 1 行都要在提交里写抬升理由；凡新增非 alpha ≥ 100 行的项必须指名同量级删除，否则移出 Must/Should。

---

## 8. Phase 7 · Kill Register **[C 修订]**（09-05 版由同一 Agent 产出；2026-09-06 经附录 C 六角色独立复核后重排，KILL-R 编号见附录 C.2）

> **下表的「状态」列停在 2026-09-06。九条已经过期——现状见 §12.8 与 §12.10。**
> 表格本身不改写：它记录的是当时的判断，删掉就看不出状态是怎么变的。

| Kill ID | 攻击命题 | 关联 | 证据 | 严重度 | 状态 | 触发动作 |
| --- | --- | --- | --- | --- | --- | --- |
| **KILL-Q15**（新，= R1） | **磁盘 registry（crowding 72 → 193707Z）≠ 运行进程（crowding 0 → 145321Z）**；构造指纹看不见信号参数，下次重启静默切换且 M-010 不清零 | C-1(a), D-026, KILL-027 | **E-35** | **P0** | **CLOSED 2026-09-06**（§12） | 操作者选路径 (b)：先修 P1-01，再有意重启；registry digest 已逐周期落盘，`status --check` 报两侧一致 |
| KILL-Q1（拆两半） | 横截面参照总体研究 ≠ 实盘：(a) tsmom crowding——**潜伏**，下次重启起生效；(b) flow 探针去均值——**当下在跑** | C-1(b), D-023 | E-12 | (a) **P0** / (b) P2 | (a) **CLOSED 2026-09-06** / (b) 代码已修，判定仍 REJECT，留在 D-029 复审 | 契约按 KILL-R5：参照集合为显式参数、只作用于秩 / 去均值；逐日等价测试；修后重跑两臂与 book、更新指针 |
| KILL-Q2 | 单配置 validate 的 OOS 是全样本尾段 | C-2, D-020 | E-13, E-36 | P1 | **代码 CLOSED 2026-09-06**（§12.5）；**欠**：registry 并列记录 1.485 未做 | 报告标注 `oos_is_full_sample_tail` + 当前构造的网格走前 OOS 并列（E-36）；**不**加 holdout（KILL-R4） |
| KILL-Q3 | D-028 门槛噪声通过率 43.5% | C-2, D-028 | E-14, E-36, E-39, E-40 | P1 | **代码 CLOSED 2026-09-06**（§12.5）；**CLOSED 2026-09-06 B0**（NW t 降 reported、`p_family` 进 reasons、相关噪声验收、`effective_trials` 只报告；提交 5502d91） | FWER 分位数 + `p_family`；tsmom 在诚实网格上以 0.02–0.04 headroom 通过（KILL-R3 CLOSED） → **[执行]** 在当前 N=125 上 headroom 收窄为 0.003–0.017，仍 PASS（E-40，§12.7） |
| KILL-Q4 | 迟到成交（`--immediate`） | — | E-18 | **P2**（原 P1） | OPEN | 两步修法（KILL-R6）；`late_seconds` 标签；不重开 M-010 计数 |
| KILL-Q5 | ledger 签名不含构造 / 覆盖层参数 | D-024 | E-15 | P1 | OPEN | 签名扩展（signal + construction + overlay digest + symbol-set hash）+ `record_trial()` 钩子接入 backtest / overlay / book / scratch + 固定 ledger 路径 |
| KILL-Q6 | 退市幽灵 bar 与冻结仓位使 pit 证据偏乐观 | D-013 | E-17 | P1 | OPEN | 退市日历 + 结算 + 掩码；重跑 pit |
| KILL-Q7 | 无单实例锁；并发来源是 worktree 而非竞态 | D-003 | E-20, KILL-R20 | **P1**（原 P2） | OPEN → Phase A | `fcntl` + key 指纹锁 + 绝对路径 + `--armed` |
| KILL-Q8 | 扩空间后的自适应提案破坏 DSR 可交换性 | A-004 | §7.1.4 | P1 | **OPEN**（原 MITIGATED；散文不算缓解） | 7.1.4 的机械规则（一本 ledger、时间戳校验、晋级由 ledger 层强制）落地后关闭 |
| KILL-Q9 | "LLM 不进 ledger 路径"无执行主体 | E-004(P17) | KILL-R9 | P1 | **OPEN**（原 MITIGATED） | 与 Q8 同一组机械规则关闭 |
| KILL-Q10 | 原生条件单：与启动撤单冲突、无生命周期、7/18 币不可下单、违反 D-012 重开条件、`guard.py` 对 algoOrder 盲 | D-012 | E-31, E-21, E-37 | P1 | **CLOSED（范围外，Won't）** | 将来重开先记录重开条件变更决策 |
| KILL-Q11 | metrics 数据：研究吃 T+1 归档、实盘只能走 REST（30 天、时延未核）→ 不同源且实盘源不可回放 | C-3 | E-23, KILL-R21 | P1 | UNKNOWN | 三项核查（归档发布时刻 / REST 桶可得时延 / 同桶值差）+ 同源契约（自建 5 分钟 REST 快照流作为共同真源）+ `needs_metrics` 自声明 |
| KILL-Q12 | 无冲击成本模型时真实资金的 `vol_target` 不成立 | C-6 | E-28 | P0（资金前） | **DEFERRED（范围）** | 附录 D；真实资金 HOLD |
| KILL-Q13 | 单交易所 / 单主机 / 单数据源集中 | Ⅳ | — | P2 | ACCEPTED（范围） | 远端停机缓解"循环失联"一半，不缓解"交易所失联" |
| KILL-Q14 | demo 成交量合成，被动执行无法在 demo 证明 | 7.3 | D-002 | P2 | ACCEPTED | 推迟到小额真实资金 |
| **KILL-Q16**（新，= R2） | 09-05 版的外部看门狗设计不可交付且自带攻击面（第二把全权交易 key、误触发平掉手工仓、维护窗口平掉健康书） | C-6, §7.2 | KILL-R2 | P1（demo 范围内为设计项） | OPEN | DL-Q8 按七点重写；看门狗只持只读 key |
| **KILL-Q17**（新，= R7） | 证据窗口每改构造清零，12 周路线图与"30 天干净窗口"叠不起来；demo 盈利证据一年内不可裁决 | M-010, §9 | E-02, KILL-R7 | P1 | OPEN | 所有改构造 / 信号的变更捆绑成 Phase A 内一次重启，此后冻结到 Phase C 末；demo 目标改写为执行保真 + 无人值守存活（M-Q08/M-Q09） |
| **KILL-Q18**（新，= R10/R12） | 合并列车缺失（be963ad +1,166 行、main +731 行、4 条领先分支）；六个包全部顶在 ratchet 上限而方案零删除项 | §9 | KILL-R10, R12 | P1 | **CLOSED 2026-09-06**（D-040 / D-041 / 304e549 / be963ad 均已在 main，§11） | Phase A 第 1 步合并列车；每条 DL 带行数与删除项 |

Pre-Mortem（若 12 周后失败）**[C 修订]**：最可能的原因不再是"先扩空间再修尺子"，而是**一次无人值守的崩溃重启把信号静默切换**——registry 与循环的分叉在没人看的时候合上，M-010 把两种信号混在一起，之后每一个数字都不知道在描述谁。反向控制 = Phase A 第 0 步（重启前一致化 + registry digest 仪表）。第二可能的原因是"每次部署都清零证据窗口"——反向控制 = 构造冻结点（KILL-Q17）。

Inversion：要让本轮白做，只需"继续用 193707Z 的指针不重启、等下一次崩溃、把 P1-01 当作小事、并直接接 LLM 提案者"。

Final Kill Decision **[C 修订]**：最强反方 = KILL-Q15（PM 与 EP 独立到达同一事实链，仅严重度分歧，取 P0）；未关闭 P0 = 2（Q15、Q1-tsmom，同一动作可关闭）；无 P0 Claim 被推翻（C-1 加强、C-2 由 E-36 升 E1、C-5 保险半边 REFUTED 为 P1 Claim）；需要的新证据 = 修正总体后的两臂重跑（在一致化之后）；必须改变的 Scope = Phase A 第 0 步与顺序、mainnet 项出路线图、构造冻结点。**结论：Weak GO（两个上限成立；授权动作重新绑定到修订后的 §9）。** **[执行 2026-09-06]** 两条 P0 已关闭；Q2/Q3 交付后 C-2 的 falsifier 触发，操作者裁定后判定为 GO（受控执行），见 §12.5–12.6。

---

## 9. Phase 8 · Scope 与路线图

**[C 修订]** 本节按附录 C 的 KILL-R1/R2/R3/R6/R7/R8/R10/R11/R12/R13/R16/R17/R18/R27/R28 重写。

**MoSCoW**：Must = Phase A 全部；Should = Phase B；Could = Phase C 的 GP / 组合器 / LLM 离线助理；Won't = LLM 提案者、RL、逐仓、原生止盈 / 移动止损 / 原生灾难止损、用户数据流（ws）、第二本 ledger、随机表达式对照、TRIPPED 持久标记、多交易所、mainnet、 holdout。

**Scope Firewall**：mainnet 与其全部前提项（附录 D；重开条件：操作者显式重开 + 附录 D 的 P0 全部关闭 + 构造冻结后 30 天干净 M-010 窗口）；新信号手写（重开条件：某族阴性且机制上不可表达）；被动执行（重开条件：真实小额资金）；holdout（重开条件：操作者撤回 KILL-006 §二并接受全部 OOS 数字重出）。

**alpha 占比的口径**：仓库仪表 `effort_share`（`starquant_live/reports.py:678-709`）把 `starquant_alpha/`（含 validation/、mining/）+ `tests/alpha/` 记为 alpha、`docs/RESEARCH_LOG` + `docs/analysis/` 记为 research、cli/live/data 一律 infrastructure；操作者原话是"alpha（信号 / 因子）"。下表两个口径并列，诚实写出 Phase A 按操作者口径只有约一半是信号 / 因子工作，原因是先修尺子。

| Phase | 交付（按顺序） | alpha 占比（仪表 / 操作者口径） | 成功判据（预登记） | 停止条件 |
| --- | --- | --- | --- | --- |
| **A（第 1–3 周）** | **第 0 步（任何重启之前，≤ 1 天）**：使 registry、循环、证据一致——操作者二选一：回退 3ac8d49（crowding 0 + 145321Z），或先做完第 2 步再有意重启；registry digest 逐周期落盘 + `status --check` 比对（KILL-Q15）。**第 1 步 合并列车**：main（D-040 / D-041 / 304e549）与 be963ad（Funding 叶 + 42 carry 族），列冲突文件与顺序（KILL-Q18）。**第 2 步 修尺子**：P1-01 参照总体契约 + 逐日等价测试；F1 标注 + 当前构造网格 OOS 并列（E-36 已算）+ F2 分位数 / N_eff / `p_family` + F3 `best_key_oos` + NW t 降为 reported；F6 ledger 签名扩展 + `record_trial` 钩子；F7 `_resolve_mined` 一行 + mined 持久身份；`fcntl` 锁 + `--armed`；启动只读对账两步 + `late_seconds`；熔断 exit 0。**第 3 步 一次性重启并冻结构造**（此后到 Phase C 末不再改实盘构造 / 信号）。**第 4 步 扩空间**：只读 Panel 现有列的 5 个节点（Abs / Moment / Semi / Beta-Residual / Trades），各自预登记；在 0.30 口径重跑 267 + 新族 | 仪表 ≈ 60% / 操作者口径 ≈ 50% | (i) `live status --check` 报 registry ≡ 已加载模型；(ii) 两臂重跑（修正总体后）的 crowding 臂在 eligible 总体上仍被逐 fold 选中，且 FWER 门作用在**当前构造的网格走前 OOS**上仍 PASS（基线 E-36：1.485 对 1.445–1.466）；(iii) §7.1.6 的 falsifier 有裁决（正或负都算成功） **[执行 2026-09-06]** (i) 达成（§12.1）；(ii) 前半达成（093705Z 五 fold 全选修饰器），后半 **PASS 但 headroom 0.003–0.017**（E-40，§12.7 更正）；(iii) 六个新族未跑，未裁决。第 0–3 步已做，第 4 步未做 | 若 crowding 臂在 eligible 总体上不再被选中 → **维持 / 回到 crowding 0，不停书**；只有 FWER 门下**基础** tsmom（crowding 0）FAIL 才复审书；若 N_eff 估计使阈值 ≥ 1.485 → tsmom 记 WEAK_PASS，§11 改写 **[执行]** 此条**未触发**（§12.7 更正：当前 N=125 下阈值 1.469–1.482 < 1.485）；§11 与裁定（§12.6）保留，因为它接受的是比现实更差的情形 |
| **B（第 4–7 周）** | ① `metrics` / `premiumIndexKlines` / `markPriceKlines` 摄入：先做 20 币 × 1 年吞吐实验定工作量；同源契约（自建 5 分钟 REST 快照流为研究与实盘共同真源，逐日与归档 diff）；`needs_metrics` 自声明 + 启动门；KILL-Q11 三项核查；② 对应叶节点（含 MarkGap，与 markPriceKlines 同提交）与新族；③ 退市日历 + 结算 + 幽灵 bar 掩码，重跑 pit；④ 远端停机（DL-Q8）+ 心跳外推 + 告警去重 + 强平可观测（REST）；⑤ SIGTERM / 原子提交 / 撤单按前缀 | 仪表 ≈ 45% / 操作者口径 ≈ 35%（①③④⑤在 data/live，显式记为"非 alpha 但前置"） | 至少一个新族候选进入 validate 且 ledger 计费完整；pit 证据在退市建模后的变化写入 registry；远端停机演练两条路径通过 | 若 metrics 三项核查任一不可核 → 该数据不进实盘信号，只做研究诊断；若吞吐实验 > 3 天 → 缩到池内 45 币 |
| **C（第 8–12 周）** | ① GP 搜索（固定评估预算计为 N，进同一 ledger）；② 线性组合器；③ LLM 离线助理（proposals.jsonl，按 7.1.4 计费） | 仪表 ≈ 90% / 操作者口径 ≈ 85% | 组合边际 Sharpe ≥ +0.10 的候选进入探针书 | 若 GP 两轮的 `noise_null` 上限 > 最优候选 → 停 GP |

**证据窗口与日期**（KILL-Q17）：构造冻结点 = Phase A 第 3 步的那次重启（约第 3 周末）；30 天干净 M-010 窗口最早从第 4 周开始、第 8 周结束；真实资金即便重开也最早在第 16 周之后（附录 D 的 P0 关闭 + 冲击模型下 `vol_target` 重推）。demo 的成功判据不再是 M-010，而是 M-Q08（执行保真）与 M-Q09（无人值守存活）。

明确不做（每一条都有理由在正文或附录 C）：LLM 提案者、RL、逐仓、原生止盈 / 移动止损 / 原生灾难止损、按 Sharpe 调止损参数、用户数据流、第二本 ledger、随机表达式对照、TRIPPED 标记、多交易所、mainnet、 holdout。

---

## 10. Phase 9/10 · 交付契约与学习计划（精简）

**[C 修订]** 契约按 KILL-R5/R6/R16/R20/R25/R2 重写；每行附落点包与行数量级（ratchet 记账）。

| DL | 来源链 | 实现 | 测试 | 验收 | Metric |
| --- | --- | --- | --- | --- | --- |
| DL-Q0 registry ≡ 循环 | C-1(a) ← E-35 ← KILL-Q15 | 每周期把 registry 规范化参数 digest 写进 `cycles.jsonl` 与心跳；`live status --check` 比对磁盘 registry 与已加载模型（live +≈50） | 单元：改 registry 不重启 → `status --check` 非零退出 | 一致化后首个周期 digest 一致；D-026 或日报把信号参数纳入证据窗口的清零条件 | M-Q10 |
| DL-Q1 横截面参照总体契约 | C-1(b) ← E-12 ← KILL-Q1 | 参照集合为显式参数（只作用于 rank / demean 步骤，不裁面板）；实盘传 universe（写明 leaving 是否计入），研究传当 bar 时点成员；逐日成员日志（alpha +≈60，live +≈20） | 两条：同一参照 → 逐位相等；参照 ≠ 面板列 → 结果随参照变而不随多余列变；对真实逐日 universe 序列做等价；重写 `test_shipped_registry_live_path_matches_research_path` | 两臂重跑与 book 报告更新；registry 指针变更记账 | M-Q01 |
| DL-Q2 验证门修正 | C-2 ← E-13/14/36 ← KILL-Q2/Q3 | `oos_is_full_sample_tail`、`best_key_oos_sharpe`、`selection_consistent`；只改 `oos_selection_threshold` 为分位数（N_eff 由 CSCV 收益矩阵估）、输出 `p_family`；`pass_oos_t` 降 reported；**无 holdout 条件**（alpha +≈80） | 相关噪声（同一面板块自举）下通过率 ≤ 5% 且 tsmom PASS；`test_selection_gate.py:28` 的 N=1 语义保留 | 报告字段可见、verdict reasons 输出 `p_family` 与 N_eff **[执行]** 已做：三个标注字段、分位数门、CLI 输出 `p_family`；未做：N_eff、NW t 降 reported、相关噪声验收、verdict reasons 内的 `p_family`（§12.5 欠账） | M-Q04 |
| DL-Q3 启动两步 + 迟到标签 | KILL-Q4 ← KILL-R6 | 启动始终只读对账 + 保护单核对；rebalance 受推导窗口（grace + ThrottleInterval + 启动耗时，写进 config）约束；补跑 / 跳过策略 + 漏掉 bar 计数器；trade 行 `late_seconds`（live +≈40） | 单元：重启落在窗口外不下 rebalance 单但完成对账；漏掉 bar 被计数 | 日报"迟到入场仓位的 bar 小时占比"与"漏掉的再平衡数" | M-Q03 |
| DL-Q4 单实例 + 武装门 | KILL-Q7 ← KILL-R20 | `fcntl.flock`，锁键 = API key 指纹，绝对路径；非 dry-run 必须 `--armed` 且校验 REPO == plist WorkingDirectory；`flatten` 同锁；被拒实例 exit 0 + 告警（去重）（live/cli +≈80；删 `consecutive_errors` 持久化） | 第二实例（含另一 worktree）启动被拒并告警；`flatten` 在循环存活时先置 kill switch | — | M-Q07 |
| DL-Q5 Expr 节点 ×5 + mined 通道（一本 ledger） | C-3 ← KILL-Q8/Q9 | Abs / Moment / Semi / Beta-Residual / Trades（各 ≈45 行，alpha）；`_resolve_mined` 进 validate（1 行）；mined 持久身份 = 表达式字符串；`mine` 的 `declared_trials` 经 `_record_trial` 进 `trials.jsonl`（含搜索空间版本）；预登记时间戳校验进 `report weekly` | 量纲规则、因果性、规范化哈希、哈希在新增节点后的稳定性（UNVERIFIED → 测试） | §7.1.6 裁决 | M-Q02 |
| DL-Q6 数据摄入（metrics / premium / mark） | C-3 ← KILL-Q11 ← KILL-R21 | 先 20 币 × 1 年吞吐实验；daily 归档下载器 + 断点续传 + 校验；同源契约（5 分钟 REST 快照流 + 逐日与归档 diff）；`needs_metrics` 自声明 + 启动门；M-011 对 metrics 信号比对本地快照（data +≈300） | KILL-Q11 三项核查；时点对齐测试；快照连续性测试 | 新族候选可跑；差异率写进日报 | M-Q05 |
| DL-Q7 退市建模 | KILL-Q6 | 日历（exchangeInfo 状态快照或零量连续段推导）、结算价平仓、`Panel.tradable` 掩码（data/alpha +≈200） | `frozen_symbol_bars == 0`；LUNA / FTT / ALPACA 三事件重放 | pit 重跑差异记入 registry | — |
| DL-Q8 远端停机 + 心跳外推 + 强平可观测 | C-6 ← KILL-Q16 ← KILL-R2 | §7.2 的七点：主动推送 OK（含 registry digest）；触发 = 连续 N bar 无 OK 或 ERROR∧errors≥N；远端 dead-man lease，取不到即本地 reduce-only；`flatten --raw` 只平 `bd-` 仓；看门狗只持只读 key；场地时间；维护 sentinel + 演练脚本。强平：`liquidationPrice` 距离 + `forceOrders` GET + INSURANCE_CLEAR 桶 + CROSSED / multiAssets 断言（live/deploy +≈150，exchange +≈60） | 演练两条：`launchctl unload` → 2 bar 内停交易权再平仓 → 3 bar 内零新增仓位；封 venue 出口 / 两机断网 → **不得**误触发（循环存活但心跳迟到） | 演练记录；`min_liq_distance` 每周期落盘 | M-Q06/Q07 |

Learning Plan（**[C 修订]** M-010 保留为长期指标，不再作 Phase 判据；新增 M-Q08/09/10）：

| Metric | Claim | 指标 | 基线 | 阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| M-Q01 | C-1(b) | 实盘 vs 研究 crowding 触发集**按日**重合率（预登记非零残差容忍度） | 49.6%（E2）→ 实测 52%（E1） | ≥ 95% → **[执行]** 阈值判为预登记失当（§12.2）；裁决量改为判定与逐 fold 选择的稳定性，两者均不变 | 修后首次重跑 | 继续查参照差异 |
| M-Q02 | C-3 | 新族候选对 tsmom 的最优边际 Sharpe（以 267 为基数） | −0.08 | ≥ +0.05 | Phase A 末 | 转数据宽度 |
| M-Q03 | KILL-Q4 | 迟到入场仓位的 bar 小时占比 + 漏掉的再平衡数 | 稳态 0/8（开发期 73% 按笔） | ≤ 5% / 0 | 修后 7 天 | 查重启原因 |
| M-Q04 | C-2 | 门的噪声通过率（相关噪声仿真） | 43.5% | ≤ 5% **[执行]** 门已改分位数（独立零假设下按构造为 5%）；相关噪声仿真未跑，本项仍 OPEN | 修后 | 重查公式 / N_eff |
| M-Q05 | KILL-Q5 | 评分入口写 ledger 覆盖率 | ~50% | 100% | Phase A | 补钩子 |
| M-Q06 | C-6 | 最小强平距离（日波动单位） | 未测 | ≥ 10 | 每周期 | 告警 |
| M-Q07 | KILL-Q16 | 远端停机演练（两条路径） | 无 | 2 bar 停权 + 平仓；误报路径不触发 | Phase B | 修 |
| **M-Q08** | Pre-5 | 执行保真：换手 vs 回测同期、滑点 vs 模型 2 bps、`late_seconds`、registry ≡ 循环 | — | 换手 ±25%、滑点 ≤ 2×模型、迟到 ≤ 5%、一致性 100% | 冻结后 30 天 | 复审执行层 |
| **M-Q09** | Pre-5 | 无人值守存活：连续无人干预天数、失联自动停机次数 | 12 次重启 / 2 天 | ≥ 30 天、0 次未处理失联 | 冻结后 30 天 | 复审运维 |
| **M-Q10** | C-1(a) | registry digest 与已加载模型一致的周期占比 | 0%（当前分叉）→ **[执行]** 周期 98 起 100% | 100% | 每周期 | 拒绝启动 / 告警 |
| M-010 | edge | 30 天 income Sharpe（构造固定、迟到入场剔除） | — | 长期指标；**功效不足以在 1 年内裁决 alpha** | 30 天滚动 | 仅记录，不触发决策 |

---

## 11. Final Decision 与 Quality Score

**Final Decision：GO（受控执行）。** **[操作者裁定 2026-09-06，见 §12.6 与附录 B]** 四条升级条件中前两条与第四条已达成；第三条（KILL-Q2/Q3）的代码已交付，量 tsmom 自己得到的是 **PASS，headroom 0.003–0.017**（§12.7 更正；初稿误记 WEAK_PASS 并据此请了裁定）。**操作者已裁定即使是 WEAK_PASS 也足以支撑受控执行**，所以 GO 有两重依据：条件按其字面成立，且在它不成立的情形下也已被裁定接受。 headroom 小于测量误差这件事没有变，不含糊过去。**真实资金仍为 HOLD 且 DEFERRED，本次升级不触及它。** 以下为 09-06 之前的原文：**Weak GO（受控执行）。** **[C 修订]** 六角色复核后两个上限不变（demo 继续、真实资金 HOLD），授权的动作重新绑定到修订后的 §9。
- 允许：demo 继续；Phase A 按 §9 顺序执行，**第 0 步先于一切**；Phase B 在 A 裁决后执行。
- 不允许：在完成第 0 步（registry / 循环 / 证据一致）之前重启循环——除非那次重启本身就是第 0 步的有意切换并被记为构造变更；在 KILL-Q15 关闭前启用任何新信号；接 LLM 提案者；用原生条件单做 alpha；把 mainnet 前提项排进 12 周路线图。**撤回**09-05 版"不允许改 registry 的 tsmom 参数"这一条：回退 3ac8d49 恰是最便宜的关闭动作。
- **升级为 GO：已发生（2026-09-06，操作者裁定）。** 原四条条件的实际结局：KILL-Q15 **CLOSED**、KILL-Q1-tsmom **CLOSED**、KILL-Q18 合并列车 **完成**；第三条 KILL-Q2/Q3 **代码 CLOSED（B0 补齐四项欠账，5502d91）；判据按其字面成立**——诚实网格 OOS 1.485 对当前 N=125 的阈值 1.469（σ 0.4389）/ 1.482（σ 0.4430），两个 σ 都 PASS（§12.7 更正了初稿的 N≈141 与 WEAK_PASS）。曾列出的两条出路是 (i) 重测取可读 headroom、(ii) 操作者裁定 WEAK_PASS 足够；**操作者选 (ii)**（附录 B），该裁定保留为第二重依据。**作废条件**：基础 tsmom（crowding 0）在门下 FAIL，或新的诚实网格 OOS 低于当时阈值达 0.05 以上 → 判定退回 Weak GO 并走 §9 第 2 步复审。
- 真实资金：**HOLD 且 DEFERRED**。解除条件（只在操作者显式重开 mainnet 后适用）：附录 D 的 P0 全部关闭 + KILL-Q12 的冲击模型下 `vol_target` 重推 + 构造冻结后 30 天干净窗口（M-Q08 四项达标、M-Q09 ≥ 30 天、构造不变）+ 上线断言四项（CROSSED / multiAssets 与验证口径一致、全新 `state_dir`、账户空仓空挂单、告警端到端演练）。按 §9 的日期推算，最早在第 16 周之后。

Quality Score（1–5）**[C 修订]**：问题真实性 5 · 证据充分度 4 · 根因清晰度 4 · 战略一致性 4 · 相对价值与经济 4 · 方案可行性 4 · 范围收敛度 3 · 执行可交付性 2 · 上线可验证性 3 · 对抗生存 4 = **37/50**（映射 Weak GO / Need Evidence 档，与硬门禁一致：OPEN P0 = 2 → Weak GO）。 **[执行 2026-09-06]** 分数不变，仍对应 Weak GO 档；判定为 GO 的依据是 §12.6 的操作者裁定，不是分数——这个不一致是有意保留的。执行可交付性从 3 降到 2 的理由：路线图有五处在 09-05 版里不能按写的那样执行（holdout 必选、周上限无工具、看门狗不可交付、合并列车缺失、证据窗口叠不起来），本次修订改正了它们，但 Phase A 的交付契约仍未写到测试矩阵级别。

---

## 12. 执行记录（2026-09-06）：两条 P0 的关闭

操作者在 §11 的两条路径中选择 (b)——先修 P1-01，再有意重启。完整过程见 `docs/RESEARCH_LOG.md` 的 P18 与 `docs/ARCHITECTURE.md` 的 D-042；这里只记状态与本报告需要更正的地方。

### 12.1 状态变更

| Kill | 修订版状态 | 现状 | 关闭依据 |
| --- | --- | --- | --- |
| **KILL-Q15**（registry ≠ 运行进程） | OPEN P0 | **CLOSED** | 每周期与心跳记录进程持有的 registry digest；`live status --check` 与磁盘比对。重启后首个周期 digest `16671c63a12e` 两侧一致，`--check` 报 `registry: matches the running loop` |
| **KILL-Q1-tsmom**（横截面参照总体，潜伏半边） | OPEN P0 | **CLOSED** | `Panel.reference` 契约 + 研究/实盘两侧接线 + 逐日等价测试；证据重出为 `tsmom-validation-20260906T093705Z`（PASS，五 fold 全选修饰器），registry 指针已换 |
| **KILL-Q1-flow**（去均值，当下在跑的半边） | P2 | **CLOSED（代码）/ 保留在 D-029 复审** | 同一契约；`book-tsmom-flow-20260906T094008Z` 重出，判定仍 REJECT，探针安排不变 |
| **KILL-Q2/Q3**（伪 OOS 标注 + FWER 分位数门） | OPEN（升级条件） | **代码 CLOSED / 判据未达成** | 门槛改为解 Φ(x)^N = 1−α 的分位数，并报 `p_family`；报告带 `oos_is_full_sample_tail` 与 `selection_consistent`，`best_key_oos_sharpe` 给上线构造自己的走前数。**但**用它量 tsmom 自己，C-2 的 falsifier 触发（§12.5）——所以这一条不能作为 GO 的支撑；欠账四项见 §12.5，裁定见 §12.6 |
| KILL-Q7（单实例锁） | P1 | 仍 OPEN | 本轮未做；重启后实测确为单进程，但那是运气不是保证 |
| 其余 P1 / DEFERRED | — | 不变 | — |

**Gate**：G6 由 PARTIAL 升为 **PASS**（OPEN P0 = 0）。G7 仍 PARTIAL（测试矩阵未写）。硬门禁不再压制判定。尺子修完后量到的第一个数是 tsmom 自己：**PASS，headroom 0.003–0.017**（§12.7 更正了初稿的 WEAK_PASS）。**操作者于 2026-09-06 裁定即使是 WEAK_PASS 也足以支撑受控执行**（§12.6、附录 B），判定升为 **GO（受控执行）**，真实资金的 HOLD 不变。

### 12.2 本报告需要更正的两处

1. **E-12 的等级由 E2 升为 E1，数字更正。** 09-05 版记的是审计代理复算的"1.8× 触发率、49.6% 重合"，附录 A 也明写"无人独立复现"。本轮在成员币-bar 上实测：全 panel 总体 **10.60%** 对成员总体 **17.28%**（1.63×），触发 bar 重合 **52%**，每 bar 参与排名的名字数 118.8 对 17.1。方向与量级与代理一致，具体数字以本轮为准。
2. **C-1 的 falsifier 已裁决。** 预登记的是"修正参照总体后两臂重跑与 193707Z 的逐日触发集重合率 ≥ 95%"。实际重合 52%，**低于阈值**——但这不是 falsifier 触发，而是阈值写错了：它假定修正只影响边缘名字，而实测表明修正改变的主要是"标了谁"。真正的裁决量是**判定与逐 fold 选择是否不变**，两者都不变（PASS，五 fold 全选修饰器，OOS 1.7647 → 1.7662）。**记为阈值预登记失当，不记为通过**；下一次给这类契约写 falsifier 时，量的应当是判定的稳定性而不是触发集的重合。

### 12.3 顺带发现（不在原计划内）

`true_range` 的 `groupby(level=1)` 按字母序返回列，而 `breakout` 用 `np.where` 按位置拼回 `panel.close.columns`——面板里 `S10USDT` 排在 `S1USDT` 前面时，广度被贴到错的币上。由本轮新测试撞出，不是找出来的。breakout 处于关闭状态，不影响任何已发布证据。

### 12.4 证据窗口（含一处对本节初稿的更正）

**先更正。** 本节初稿写「crowding 0 → 72 首次真正生效于 10:19 这次重启，此前 96 个周期 `funding_history` 全为 false」。**两个数字都不对**，由并行会话指出、本会话逐周期复核确认：

```
周期 95  2026-09-06T09:00:10Z  funding_history = False
周期 96  2026-09-06T09:52:31Z  funding_history = True   ← 翻转发生在这里，不是 10:19
周期 98  2026-09-06T10:19:09Z  funding_history = True   ← 本轮的重启（第一个带 registry digest 的周期）
```

为 false 的是 **95** 个周期，不是 96；翻转由 **09:52 那次重启**造成（不是本会话做的），本轮 10:19 的重启是第三个 true 的周期。机制正是 KILL-Q15 本身：引擎只在启动时读一次 registry，所以 09-04 20:03 的那次 `crowding_window: 0 → 72` 要等到**任何一次**重启才生效——09:52 那次就够了。真实的分叉窗口因此是 **2026-09-04 20:03Z → 2026-09-06 09:52Z，37.8 小时 / 37 个周期**，比初稿写的更精确。

**由此多出一个事实**：周期 96–97 用**修复前**的代码跑了 `crowding_window: 72`，也就是在错误参照总体下运行了两个周期。两个周期，无订单产生，但要记下来而不是含糊过去。

初稿把翻转归给自己的重启，是"看到自己想看到的因果"的标准形状；留在这里不删，因为下一个人会犯同一个错。**更正不改变 §12.1 的任何关闭判定**：Q15 的关闭依据是 digest 仪表（周期 98 起落盘），Q1-tsmom 的关闭依据是契约与重出的证据，两者都与翻转发生在哪一次重启无关。

**证据窗口**：本轮重启同时改变了**代码口径**（参照总体）与**信号**（修正器在正确总体下运行），因此 M-010 此前累计的归因描述的是另一本书。**窗口自 2026-09-06T10:19Z 重新开始**。按 §9 的约定，到 Phase C 末不再改实盘构造 / 信号。

---

### 12.5 KILL-Q2/Q3：尺子修好了，量出来的第一个数是自己

完整过程见 `docs/RESEARCH_LOG.md` 的 **D-043 / M-019**。代码已并入 main（`b218f1c`；分支随后删除），四步 CI 全绿。

**做了什么**

- **Q3（门槛）**：D-028 用 `expected_max_sharpe` = σ·E[max of N nulls] 当门槛。E[max] 是个平均数，单条纯噪声曲线越过它的概率约 43%。改为解 Φ(x)^N = 1−α 的分位数（α=0.05），并报 `p_family` = 1 − Φ(S/σ)^N。`expected_max_sharpe` **原样保留**——DSR 要的就是这个期望，错的是拿它当门槛。
- **Q2（形状）**：报告带 `oos_is_full_sample_tail` 与 `selection_consistent`；`best_key_oos_sharpe` 给上线构造自己的走前数。原处方的另一半 `--holdout-months` **维持撤回**（与 KILL-006 冲突，KILL-R4）。
- **没有装的**：N 仍是 ledger 原始行数，不是 N_eff。 ledger 里有大量近邻重复，所以现在这条是保守的；没有相关性结构就编一个 N_eff 估计量只是猜，记为欠账写进 docstring。
- **欠账（复审 2026-09-06 补记）**——处方里写了、本轮没做、本节初稿没披露的四项：① `pass_oos_t` / `weak_oos_t` 仍在 `verdict.py:83` 强制（DL-Q2、§7.1.4 第 6 条、附录 B 都写"降为 reported"）；② registry evidence 块未并列记录当前构造的诚实网格 OOS 1.485（§4.1 F1 修复、KILL-Q2 触发动作）；③ DL-Q2 / M-Q04 的验收"相关噪声块自举下通过率 ≤ 5%"未跑，新测试全用独立零假设；④ `p_family` 只在 CLI 输出，不在 verdict reasons 里。另：E-36 的报告原本只在 scratchpad，复审时已入库 `reports/research/scratch/`（未记账，见该目录 README）。

**对已有结论的影响：一份也没翻**（E-39）。11 份报告，旧门槛的噪声通过率 43.4%–43.5%，新门槛下 5 份 tsmom 仍 PASS、6 份 mined 仍 FAIL，没有任何候选被救活。registry 引用的那份报告早于本次修改，**不用重跑，一次额度也没花**。

**顺带修正 P19 的措辞**：P19 判定写候选 2「只差 0.14 没够到通缩门槛」。按新门槛差的是 **0.45**，`p_family` = 0.78——纯噪声下 78% 的同规模搜索都会挖出至少这么好的东西。C-004 REFUTED 因此更稳。

**然后是不好的那一半（E-40）**

C-2 预登记过：**阈值 ≥ 1.485 → tsmom 转 WEAK_PASS，§11 与 §0 改写**。1.485 是 E-36 在当前构造下的**诚实**网格走前 OOS（不是 registry 报告的 1.766——那份五 fold 同 key，正是 Q2 现在会标出来的形状）。

| σ_null 取自 | 阈值达到 1.485 的 N | **@N=125（当前，已含 +16）** | @N=143（若再跑一次 16 点网格） |
| --- | ---: | ---: | ---: |
| E-36（0.4430） | 128 | **1.482 → PASS，headroom 0.003** | 1.499 → WEAK_PASS |
| 093705Z（0.4389） | 144 | **1.469 → PASS，headroom 0.017** | 1.485 → 边界 |

**[本小节的判定已由 §12.7 更正为 PASS]** 初稿误以为 E-36 的 16 个格子仍欠 ledger，据此推 N=141 并读作 WEAK_PASS；实际 +16 已在 093705Z 申报，当前 N=125 下**两个 σ 都 PASS**。不变的是这句：**两个同样合理的 σ 给出的阈值相差 0.014，而 headroom 是 0.003**——headroom 小于阈值本身的估计误差，这一点在 PASS 一侧同样成立。

**N 的来源**（§12.7 更正后）：`n_trials` = ledger 去重行数 63 + 本次网格点数 2 + 申报先验 60，而 **60 = 30 + 14（D-039 带格）+ 16（E-36 的网格）**——+16 已经在里面。下一次同区间重放约 N=127（1.4704 / 1.4841，仍 PASS）；再跑一次 16 点网格约 N=143（1.4848 / 1.4986，一个 σ 下转 WEAK_PASS）。路径 (i) 要给出 ≥ 0.05 的可读 headroom，仍需新的诚实 OOS 自己升到 ≈ 1.53 以上。

边界，逐条说清：

1. **书不停。**§9 第 2 步的复审触发条件是「FWER 门下**基础** tsmom（crowding 0）FAIL」；那一条没有触发，也**没有被测**——测它要花一次真实的 ledger 额度。
2. **没有重跑 validate 去"确认"，是有意的。**跑一次就往共享 ledger 再加一行，把阈值又推高一点；用一个会让结论更坏的观测去确认结论，只会让下一轮更难归因。上面的算术是精确的，σ 与 OOS 都是已落盘的实测值。
3. **这不是新的坏消息。**§0 早就写着「现行结论以极薄 headroom 成立，任何 +20 次试验或一次不利的构造变更都可能翻转」。修尺子之前，这句话没法变成一个可判定的数；现在可以了——答案是「还没翻，但 headroom 已经小于测量误差」（§12.7）。

**结论（当时）**：Final Decision 维持 Weak GO——四条升级条件里第三条按其本身的判据不成立，出路两条且都要操作者的一次显式决定。**操作者当天作出了裁定，见 §12.6。**

---

### 12.6 操作者裁定（2026-09-06）：WEAK_PASS 足以支撑受控执行

§12.5 把两条出路交给操作者：**(i)** 重跑一次诚实网格 validate、争取一个 ≥ 0.05 的可读 headroom；**(ii)** 裁定 WEAK_PASS 足以支撑受控执行并写进附录 B。**操作者选 (ii)。**

**裁定内容**（附录 B 有正式条目）：分位数门下 tsmom 的诚实网格 OOS 1.485 对 N≈141 的阈值 1.483–1.497，headroom 小于阈值本身的估计误差，记 **WEAK_PASS**；该 WEAK_PASS 足以支撑 demo 的受控执行。Final Decision 因此升为 **GO（受控执行）**。**真实资金仍 HOLD 且 DEFERRED，本裁定不触及它**，其解除条件仍为 §11 原文（附录 D 的 P0 全关 + 冲击模型重推 `vol_target` + 30 天干净窗口 + 上线断言四项）。

**为什么 (i) 被放弃**——分析者的建议，操作者采纳：

1. 跑一次就往共享 ledger 追加一行，而阈值随 N **单调上升**。用一个**会让结论变差的观测**去确认结论，得到的"确认"没有信息量。
2. (i) 要回答的问题是「1.485 究竟比 1.49 大还是小」。两个同样合理的零假设 SD（0.4430 与 0.4389）给出的阈值分别是 1.497 与 1.483——**这个精度本来就不在这套证据的分辨能力之内**。再跑一次不会把分辨率变高，只会换一组同样在噪声里的数字。
3. 把"headroom 已经薄到不可读"直接记下来，比再花一次不可逆的额度去证明它薄更诚实，也更便宜。
4. （复审补记，裁定时没有算出来）按 (i) 跑 16 点网格，N ≈ 157，阈值 1.496–1.510——**两个 σ 下都是 WEAK_PASS**；(i) 能给出 ≥ 0.05 headroom 的唯一方式是新 OOS 自己 ≥ 1.55。算出来只让 (ii) 更明显。

**这次升级依据的是一次裁定，不是一个更好的数字。**这句话写进 §0、§11 与附录 B 三处，是为了让任何后来读这份报告的人不会把 GO 误读成"证据变强了"。

**作废条件**（写死，不由后来的解释调整）：

- 基础 tsmom（`crowding_window: 0`）在分位数门下 **FAIL** —— 这是 §9 第 2 步原本就写着的复审触发条件，**至今没有被测**；或
- 任何一次新的诚实网格 OOS **低于当时阈值达 0.05 以上**。

任一条成立，本裁定作废，判定退回 Weak GO 并走 §9 第 2 步的复审。

---

### 12.7 更正（2026-09-06 二次复审）：那 16 个格子早就申报过了

§12.5 的 E-40 建立在一个错误前提上：「E-36 的 16 个网格点仍欠 ledger，下次 validate 申报 +16 后 N=141」。**+16 已经在 093705Z 里申报过了。**`config/alpha_registry.yaml` 的证据块自己写着 `--prior-trials` 30 → 60 的分解——「30 as before, +14 for D-039's hand-declared band cells, **+16 for the 2026-09-06 grid run**」——而报告 JSON 的 `prior_trials_declared` 就是 60。E-36 写于 03:09Z，093705Z 跑于 09:37Z，后者执行了前者留下的那句"待申报"；我在写 §12.5 时读了 E-36 那句话，没有去核 093705Z 是否已经照做。

**更正后的数字**（`n_trials` = ledger 去重 63 + 网格 2 + 申报先验 60，60 = 30 + 14 + 16）：

| | N | 阈值 σ=0.4430 | 阈值 σ=0.4389 | 对 OOS 1.485 |
| --- | ---: | ---: | ---: | --- |
| **当前（093705Z，含 +16）** | **125** | **1.4822** | **1.4685** | **两个 σ 都 PASS**，headroom 0.003 / 0.017 |
| 下次同区间重放 | ≈127 | 1.4841 | 1.4704 | 仍 PASS |
| 再跑一次 16 点网格 | ≈143 | 1.4986 | 1.4848 | 一个 σ 下转 WEAK_PASS |
| 阈值首次达到 1.485 | 128 / 144 | — | — | 这两个数没变 |

**结论怎么变**：

1. **C-2 的 falsifier 没有触发。**§12.5 写"触发 → WEAK_PASS"是错的。tsmom 的诚实网格数在当前 ledger 下 **PASS**。
2. **§11 升级为 GO 的第三个条件按其字面成立**，不再只靠裁定支撑。加上阈值随 N 单调上升、任何 N_eff ≤ N，「N_eff 下仍 PASS」也随之成立（在更小的 N 上门槛更低）。
3. **操作者的裁定保留，且是更稳的那一重。**它接受的是「即使只有 WEAK_PASS 也继续受控执行」——比现实更差的情形。现实更好，裁定不受影响；反过来，如果下一次运行把 N 推过 128，判定滑到 WEAK_PASS 时也已经有了处置，不需要再问一次。
4. **唯一没变、也最重要的一句**：headroom 0.003 **小于两个同样合理的 σ 估计给出的阈值之差 0.014**。"PASS 还是 WEAK_PASS"取决于你用哪一次运行的零假设 SD——这不是一个证据能分辨的精度。§12.6 放弃路径 (i) 的三条理由因此一条不改，反而更成立：再跑一次会把 N 推到 ≈143，把一个本来 PASS 的数推到边界。

**这个错误为什么发生**：E-36 的"待申报"是一句**当时为真、之后被执行掉**的备注，而我把它当成了持续状态。同一形状的错误在 §12.4 已经犯过一次（把 crowding 翻转归给自己的重启）。两次的共同点是：读了一句写在过去的话，没有去核它描述的世界后来变了没有。registry 的注释里有答案，一次 grep 就能看到。

**处置**：正文中所有依赖 N=141 的表述已就地更正并标注指向本节；E-36 与附录 A 的"待申报"改为"已申报"；§8 的 KILL-Q3 状态改为 CLOSED（B0 提交 5502d91 补齐四项欠账）。§12.5 的分析结构与 §12.6 的裁定原文保留，因为它们记录的是当时的推理，删掉就看不出这个错误发生过。

---

### 12.8 状态清点（2026-09-07）：§8 的九条已过期

关窗前对着代码逐条核了 §8 的 Kill Register 与 §10 的 DL 表。**没有新缺陷**，但 §8 与 §12.1 的状态列
有九条停在 09-06，而它们描述的世界已经变了——与 remediation 方案 checkpoint 那处
「写着未做、实际在跑」是同一类漂移，所以就地记清。

| Kill | §8 记的 | 现状（2026-09-07，逐条核过代码） |
| --- | --- | --- |
| KILL-Q2 | 代码 CLOSED；**欠 registry 并列记录 1.485** | **欠账已还**：`config/alpha_registry.yaml:169-175` 并列记录诚实走前 OOS 1.4852、指针 `scratch/tsmom-validation-20260906T030942Z.json`、以及它在 N=125 分位数门下 0.003 的 headroom |
| KILL-Q4 | OPEN | **CLOSED**：`within_rebalance_window`（窗口由 grace + ThrottleInterval + 实测启动耗时推导，非硬编码）、`late_seconds`、`missed_rebalances` 逐周期落盘；日报有 Restart cost 一节 |
| KILL-Q5 | OPEN | **CLOSED**：`TrialRecord` 签名 +4 字段（construction / overlay digest、symbol-set hash、搜索空间版本），`backtest`/`overlay`/`validate`/`book`/`mine` 五个入口全部计费，ledger 地址锚定 checkout（`--out` 换不出空 ledger） |
| KILL-Q6 | OPEN | **不开工，入口条件实测不成立**：pit 成员期只有 0.70% 的 bar 冻结（全 panel 6.92%，集中在 FTT 83% / ALPACA 91%）；「持有穿过」的诚实代价 −0.021 Sharpe（1.7301 → 1.7094）。DL-D1 的入口条件是「B2 阴性或候选依赖退市期数据」，两条都不成立 |
| KILL-Q7 | **仍 OPEN，本轮未做**（§12.1） | **CLOSED**：`starquant_live/lock.py` 的 `fcntl.flock`，锁键 = `sha256(api_key)[:16]`（绑账户不绑目录），绝对路径；非 dry-run 必须 `--armed` 且校验 REPO ≡ plist WorkingDirectory；被拒实例告警后 exit 0。**AC-L1 实跑过**：从另一 worktree 启动被拒 + 一条告警 + 主循环无异常 |
| KILL-Q8 / Q9 | OPEN（散文不算缓解） | **CLOSED**：`mine` 每轮把保留候选经 `_record_trial` 记进同一本 ledger（`--prior-trials` 不再手抄）；`report weekly` 校验预登记提交时间戳早于报告时间戳。P20 的 `n_trials` 575 = ledger 514 + 申报 60 + 网格 1，**是算出来的** |
| KILL-Q11 | **UNKNOWN** | **CLOSED**：三项核查全部可核——归档 T+1 约 06:45–07:00 UTC；REST 时延约 2 分钟；**同桶数值一致但时间戳差整整一个 5m 桶**（−5min 偏移下 166/166 精确，其余偏移 0/165）。同源契约两半都在：`starquant_data/metrics.py` 的对齐契约（规范戳 `open_time`，一根 bar 能读哪些桶由桶的**收**决定）+ 循环每周期记录它自己能读到的桶。`needs_metrics` 自声明 + `metrics_refusal` 启动门已上线，实盘覆盖度从 1 根 bar 起算、门要求 720 |
| KILL-Q16 | OPEN | **ACCEPTED（残余，操作者具名接受）**：操作者裁定 Q1 = B（没有远端介质），DL-X2 取消，B4 降级为 O-X1。「循环活但下不了单」由熔断 → 告警 → exit 0 覆盖；「主机死 / 网络分区」无自动动作，告警在 12 个周期内到达，平仓由操作者手工执行 |
| KILL-Q17 | OPEN | **构造已冻结**（`0dcd044d0158`；五次重启，值一次没变——第五次 digest 因指纹**定义**变了两次而移动，已按 §12.11 归一），M-Q08/M-Q09 的钟在跑。`clean_days` 今天 = 0，因为今天有四次操作者授权的重启——数诚实，读法是「钟从今天起算」而不是「坏了」 |

### 12.9 §4.2 两个「待作者」问题的裁定（操作者，2026-09-07）

**(1) edge 衰减用什么统计检测 → 按报告建议处理。** 规则**在此预登记**，早于任何实盘窗口存在：
M-010 的 **30 天滚动 Sharpe** 对**回测同期分布**的分位数，**连续两个 30 天窗口 < 回测 q10 即复审**。
三处必须写死，否则规则会在事后被读松：

- **窗口不重叠**。「连续两个」若允许重叠 29 天，两个观测几乎是一个，误报率远高于设计意图。
  两个不重叠的 30 天窗口 = 60 天证据。
- **q10 来自同一构造的回测同长度窗口的经验分布**，不是对点估计做正态近似。
  一个年化 1.7 的策略在 30 天窗口上的离散度极大，q10 多半远在零以下；
  拿点估计加标准误去比，是另一个（更弱的）检验。现有 `drift_vs_expectation` 的
  `z = (realised − expected)/√(365/days)` 就是那个更弱的检验，两者并存、不互相替代。
- **构造一变，q10 必须重算**，与 M-010 的清零语义一致。

**当下状态**：构造 2026-09-06 冻结，到今天连**一个**完整的 30 天窗口都不存在，
所以这条规则最早在 **60 天后**才可能触发。这正是预登记它的时机——先写后跑。
**未做的下一步**：从当前构造的证据跑算出 q10 并写进 registry 的 evidence 块。
在 q10 落地之前，日报对本项只能报 INSUFFICIENT_DATA 并写明缺的是什么，
**不得报 OK**（`metrics_parity` 的 `rate: None` 是同一个教训：零分之零不是一致）。

**(2) 密钥轮换与 IP 白名单的仓外流程 → 没有流程。**
记为**已知残余风险**，不是待办，除非操作者要求。当前形态与它的后果：
交易凭据以明文存于 `~/.zshrc`，`deploy/run_live.sh:18` 对其全局 `eval`；
本机任一 worktree 里的进程都能取到同一把全权交易 key；无轮换周期、无 IP 白名单。
`fcntl` 锁（DL-L1）挡住的是**同一账户被两个循环同时交易**，
它不挡任何**读取或使用该 key 的其他用途**——两件事不要混为一谈。
范围限定：这是 demo 账户；附录 D 的 mainnet 前置里，密钥管理是必须先关闭的一项，
**真实资金的 HOLD 不变**。

**§4.2 里两个「待作者」的问题在此裁定，此前一直没有答案**，它们是给操作者的，不是给实现的：
(1) 用什么统计在实盘期检测 edge 衰减（报告建议 M-010 的 30 天滚动 Sharpe 对回测同期分布的分位数，
预登记「连续两个 30 天窗口 < 回测 q10 即复审」，但从未被裁定）；
(2) 密钥轮换与 IP 白名单在仓库之外是否有流程。

**🔵 低 24 项**从未获得 DL 契约（§9 的 Phase A/B/C 只契约化了 DL-Q0..Q8），所以它们是**记录在案的发现**
而不是待办。其中被后续工作顺带关掉的有 L1-06 / L1-07 / L1-09 / L1-11 / L1-14（DL-L3/L5/L6）与 P1-02
（`held.mask(~eligible & held.notna(), 0.0)`，离开 universe 是显式退出而非持有）。其余仍是原样，
包括 L1-04（滑点仪表参照 mark、阈值 10 bps 对含手续费的实测 4.3 bps）、L1-08、L1-10、L1-12、L1-13、
F9、F10、DATA-03/04/06/07、P1-04..P1-09——**它们没有被修，也没有被承诺修**。

---

### 12.10 24 条 🔵 低项里三条有当下后果，已修（2026-09-07）

操作者要求「完成其他的任务」。先核后修，三条各有当下后果，其余 21 条核过没有：

| 项 | 当下后果（不是理论上的） | 处置 |
| --- | --- | --- |
| **L1-04** | **M-Q08 是 demo 阶段两条判据之一**，而量它的仪表参照 `venue.mark_prices()`——周期醒来那一刻采样的指数价——不是回测入场的那个价；门是 10 bps，而 M-Q08 说「≤ 2× 模型」= 4 bps，且 10 是拿含手续费的 7 bps 定的、仪表量的却是不含佣金的纯滑点。两条合起来让这道门**结构上不可能失败**：实测 +4.3 bps 在 4 之外、10 之内，于是一直报绿 | 参照改为决策 bar 收盘（逐笔落 `decision_close`）；门改为 `model_slippage_bps × slippage_multiple` = 4.0；缺参照的行**跳过并计数**、不回落到 mark；退休的 `max_slippage_bps` 键**拒绝**而非静默忽略 |
| **L1-13** | `--dry-run` 与实盘共用 `state_dir`：排练会追加实盘 `cycles.jsonl`、重写 `heartbeat.json`，而 `live status --check` 正是读那个心跳判断死活——**一次排练能让死掉的循环看起来新鲜** | 目录改为派生 `<state_dir>-dry-run`；`build_store` 的 `dry_run` 改为必填（原有默认值，而三个调用点里恰好有一个忘了传） |
| **L1-10** | 账户是多资产保证金，护栏与 vol sizing 除的 `equity` 含按 mark 计价的 BTC；触发阶梯的 −35% 读数可能属于 BTC 而非策略 | **只量不改**：`/fapi/v2/account` 的 `assets` 明细逐周期落盘、日报出一节。**不动 sizing**——改那个分母是构造变更、会清零 M-010，按它自身的道理由操作者裁定 |

**衰减规则（§12.9 裁定）已实现**：`decay_verdict` + `window_sharpes`，周报一节。
窗口不重叠、比经验分布、缺 q10 报 INSUFFICIENT_DATA 三条都在测试里钉死。
q10 由 `walk_forward.summary()` **吐出来**而不是贴在 registry 旁边——
手贴的数会在下次构造变更时静默过期（D-026 的失败，已犯过两次），
从证据跑吐出来的则不可能描述别的构造。
**现状每个策略都报 `INSUFFICIENT_DATA - no q10 for this construction yet`**，
要等各自证据下次重跑才有数；规则最早 2026-11-05 前后才可能触发。

仍未修、也未承诺修的 🔵 低项：L1-08、L1-12、F9、F10、DATA-03/04/06/07、P1-04..P1-09。

---

### 12.11 重启 #5（2026-09-07 15:00Z）：尺子自己变了，被读成书变了

四件改动装进一次重启（L1-04 / L1-13 / L1-10 / 衰减规则）。PID 19006 → 30504，
SIGTERM 优雅停机 15:00:05Z、新进程 15:00:09Z、周期落盘 15:00:33Z，
`skip: False`（落在窗口内未漏再平衡）、`guard_reasons: []`、metrics 快照 18×12。

**两处必须记下来。**

**(1) 构造 digest 变了，而书逐位没变。** 我在重启前核过 registry 未被今天的改动碰过，
并据此预告 digest 不会变。**这个预告是错的**，但原因不是书变了：
P22 的合并给 `construction_fingerprint` 的 payload **加了第 23 个字段** `exits.unit_mode`。
往被哈希的 payload 里加一个键，即使每个值都不变，哈希也会变。用同一份当前配置复算：

| 口径 | digest |
| --- | --- |
| 22 字段（重启前的定义） | `0dcd044d0158c6ae` ← **与重启前记录的逐位相同** |
| 23 字段（P22 加 `unit_mode` 后） | `b441ea62d02184bf` ← **与重启后记录的逐位相同** |

**后果是实的**：`evidence_window` 现在报 `bars = 1`、`changes_7d = 3`——
自 2026-09-04 15:02Z 累积的 M-010 窗口被清零，**而清零它的是尺子的定义，不是它量的东西**。
这正是这份报告反复在写的那类错误的又一例，只不过这次发生在观测器自己身上。

`unit_mode` **本该在指纹里**（它真的改变 exit overlay 的行为，KILL-R14 的 7/18 币不可下单就是它）。
所以问题不是这个字段该不该加，而是**加它默默清零了证据窗口，没有任何记录说明为什么**。
未决：是否给 payload 加一个版本号，让「定义变了」与「书变了」在读取端可分；
以及 15:00Z 之前的行要不要按同一构造对待。**两者都是操作者的决定**，
而且历史不回填——不能事后改写那些行。

**(2) L1-10 的第一份实测数字：`share = 0.5198`。**
权益 10,964 USDT 里 **5,699 是抵押品、5,265 才是 USDT**——
**护栏与 vol sizing 除的那个分母，一半以上不是这本书的钱**。
回撤阶梯的 −35%/−50% 台阶量的是这个数。这不是新缺陷，是 L1-10 一直在说的事第一次有了数字。

`decision_close`（L1-04）本周期无法验证：18 个符号全部落在无交易带内，0 笔成交。
测试里已锁死，实盘要等下一笔成交。

**(3) 15:20:26Z 一次非计划重启（本节初稿写在它发生之前）。**
`launchctl` 的上次退出状态是 **-9（SIGKILL）**，没有 SIGTERM 日志、没有 traceback。
**没有造成损害，这是核过的**：两个急停开关文件都不存在、`orders: 0`、仓位未动。
那一行记的是 `phase SKIPPED · reason "restart outside the rebalance window"`——
**DL-L4 在一次真实的非计划重启下做了该做的事**：只对账、不再平衡、把漏掉的记下来。
这比排练出来的 AC-L4 有说服力，因为没人安排它。

**原因无法确定，不写成结论。** 查过的：系统日志里没有 jetsam/memorystatus 记录、
当时内存 94% 空闲、没有 traceback。时间上落在反复跑全量测试套件的窗口内，
但那是相关不是因果。

**能确定的一个隐患，无论这次是不是它**：`git push . HEAD:main` 走 `receive.denyCurrentBranch=updateInstead`，
会**改写主 checkout 的工作树，而 launchd 跑的正是那个目录**。
已导入的模块不受影响，但任何延迟导入会把新代码加载进旧进程。
这一整场会话推了十几次。**未处置**——处置方式（实盘切到只读部署副本，或约定循环运行时不推 main）
是操作者的决定，不是可以顺手改掉的东西。

---

## 附录 A · 本轮未做与限制 **[C 修订]**

- 外部对标代理因会话额度中断；对标评分为主分析者判断（E4/E5）并已降为附录参考，Qlib / vnpy 未抓取。
- 币安 Query Order 与 openInterestHist 文档本轮被网络策略拦截，E-24 凭已知条文，标 E4；币安 API key 无 reduce-only 作用域为三个复核角色的 E4 判断，未核。
- metrics 的粒度与发布延迟未核（KILL-Q11 UNKNOWN）；REST 30 天窗口与时延、住宅网络吞吐未核。
- E-12 的"1.8× 触发率、49.6% 重合"为审计代理复算（E2），无人独立复现；修 P1-01 后重跑即得 E1。 → **[执行]** 已实测，E1（§12.2）。
- 两次研究运行均输出到 scratchpad：`research backtest`（E-09..E-11）与 `research validate` 16 点网格（E-36）；仓库 `trials.jsonl` 未动；~~E-36 的 16 个格子待下次 validate 申报~~ **[更正 §12.7]：已由 093705Z 申报**（`--prior-trials` 30 → 60 含 +16）。小时级净收益序列存于 scratchpad，未入库。 **[执行 复审]** E-36 报告已入库 `reports/research/scratch/`（未记账）；E-09..E-11 的回测序列仍未入库。
- （复核时）未改 registry/profile、未重启循环、未提交任何文件。**KILL-Q15 的关闭动作（回退或有意重启）是操作者的实盘决定，本文件只给出两条路径。** → **[执行]** 09-06 起三者都已发生（路径 (b)），见 §12。
- 本文件不修改 `docs/RESEARCH_LOG.md`（同伴会话的 D-040/D-041 待合并）；E-010 行的"已由 D-040 修复"由拥有该文件的会话补记。 → D-040/D-041 已在 main（KILL-Q18）；执行期的记录写在 RESEARCH_LOG 的 P18 / D-042 / D-043。
- 审计代理的原始结构化输出（40 条发现、60 条排除、39 条生产缺口）与六个复核角色的原始输出保存在会话 scratchpad，未入库；若需入库，建议作为 `reports/audit/2026-09-05-*.json` 提交。
- Phase A 的交付契约未写到 C.3/C.4 的测试矩阵级别（G7 PARTIAL）。

## 附录 B · 对既有决策的处置 **[C 修订]**

| 决策 | 处置 | 依据 |
| --- | --- | --- |
| D-012 不做原生条件单 | **维持**（alpha 与保险两个半边都维持）；预登记重开条件"进入 mainnet 且信号进入日内"不变；将来重开先记录条件变更决策 | E-09, E-21, E-31, E-37 |
| D-013 时点成员表 | 修订：加"最近 N 日有成交"与退市日历 | E-17 |
| D-017 覆盖层证据门控 | 维持 | — |
| D-020 / D-028 判定 | **重开**：FWER 分位数（N_eff）、`oos_is_full_sample_tail`、`best_key_oos`、NW t 降 reported；**不加 holdout** **[执行]** 已做：分位数门、`p_family`、三个标注字段；未做：N_eff、NW t 降 reported（§12.5 欠账） | E-13, E-14, E-36 |
| D-023 信号自声明输入 | 扩展：声明横截面参照总体；`needs_metrics` | E-12 |
| D-024 ledger / 可复现 | 扩展：签名含构造与覆盖层 digest 与搜索空间版本；mine 报告自复现；一本 ledger | E-15, E-16 |
| D-026 构造指纹 | **扩展**：信号参数 digest 进指纹或日报，使信号变化也清零证据窗口 | E-35 |
| D-035 `vol_target 0.30` | 维持（demo）；真实资金前在冲击模型下重推（附录 D） | E-28 |
| D-037 自适应杠杆 KILL | **维持**；加 `notionalCap` 校验 | §7.3 |
| KILL-006 holdout 不启用 | **维持**（09-05 版的"holdout 必选"撤回） | E-38 |
| KILL-036 / 记忆"实盘就是 holdout" | 维持，但补功效计算：demo P&L 一年内不可裁决 alpha；demo 目标改为执行保真 + 无人值守存活 | §6.4, KILL-Q17 |
| P17 不接 LLM 提案者 | **维持**；控制手段从"谁提案"改为 ledger 与时间戳的机械规则 | §7.1.5 |
| **[新] 操作者裁定 2026-09-06：tsmom 的 WEAK_PASS 足以支撑受控执行** | 记为一次**显式的操作者决定**，不是分析者的推断。裁定内容（**前提数字已由 §12.7 更正，裁定本身有效且更稳**）：请求裁定时呈报的是「N≈141、阈值 1.483–1.497 → WEAK_PASS」；实际 N=125、阈值 1.469–1.482 → **PASS，headroom 0.003–0.017**。裁定接受的是比现实**更差**的情形，因此照旧成立：该 WEAK_PASS **足以支撑 demo 的受控执行**，Final Decision 因此升为 **GO（受控执行）**。**真实资金的 HOLD 不受本裁定影响**，解除条件仍为 §11 原文。被放弃的另一条路是「重跑一次诚实网格 validate 取一个可读 headroom」，放弃理由见 §12.6。**推翻条件**：若基础 tsmom（crowding 0）在分位数门下 FAIL，或任一次新的诚实网格 OOS 低于当时阈值达 0.05 以上，本裁定作废，回到 §9 第 2 步的复审 | §12.6, E-40 |
| 操作者范围"mainnet 不在范围内" | **遵守**：全部 mainnet 前提项移入附录 D | 记忆文件；KILL-R13 |

## 附录 C · 独立对抗复核（Phase 7，2026-09-06）

### C.0 主分析者前言与核验记录

本附录是六个独立反方角色对本文件 **2026-09-05 冻结版**的复核合并稿，由合并代理去重排序，主分析者**未改动其内容**（含它对 09-05 版的全部指控），只在下面记录自己对其中可核验事实链的独立核验，以及据此对正文所做修订的索引。

| Kill | 主分析者核验 | 结果 | 正文修订处 |
| --- | --- | --- | --- |
| KILL-R1（registry ≠ 运行进程） | `state.json.restarted_at` 2026-09-04T17:21:22Z vs `git log 3ac8d49` 2026-09-04T20:03:32Z；`cycles.jsonl` 88 行 `funding_history` ∈ {False, None}；`inputs.py:65-68`；`engine.py:849-899` | **成立**，升为 P0 KILL-Q15 | §0、§4.1、§8、§9 第 0 步、§11 |
| KILL-R3（FWER 门作用在诚实网格 OOS 上） | 在当前构造跑 16 点网格 validate（scratch）：OOS 1.485，阈值 1.445（N=93）/ 1.466（N=110） | **关闭**：通过，headroom 0.02–0.04 → **[执行]** E-40 后为 WEAK_PASS，见 §12.5 | §0、§4.1 F2、E-36、E-40 |
| KILL-R4（holdout 必选与 KILL-006 冲突） | `RESEARCH_LOG:732-760`、`research_cmd.py:374-378` | **成立**，撤回 holdout 必选 | §4.1 F1、§7.1.4、附录 B |
| KILL-R6（73% 为开发期比率） | 按周期重算 `trades.jsonl`：最后一次重启后 8 笔常规周期成交全部 ≤ 0.3 分钟 | **成立**，L1-01 降运维项 | §0、§4.1、E-18、M-Q03 |
| KILL-R14（18 单位止损不可下单） | `state.json.exit_states.*.unit`：7/18 > 1/18 | **成立** | §7.2、C-5、E-37 |
| KILL-R23（2021-05 在样本内） | 首个决策 bar 2021-01-31；补算 05-10→05-23 窗口 | **成立**，窗口已补 | E-10、§4.2 Ⅲ |
| KILL-R24（回撤分段疑似提取缺陷） | 用"新高之间的谷底"重提取 | **不成立**：两对重合深度为真实巧合 | E-11 加注 |
| KILL-R2 / R5 / R7 / R8 / R9 / R10 / R11 / R12 / R13 / R15 / R16 / R17 / R18 / R19 / R20 / R21 / R22 / R25 / R26 / R27 / R28 / R29 | 逐条读证据引用（文件:行、`git show`、仪表口径）；未再独立重跑数字 | 采纳（其中 R2 的币安 key 权限粒度、R21 的 REST 时延、R25 的 N_eff 阈值保持 UNVERIFIED） | §6.1、§6.4、§7.1.4、§7.1.5、§7.2、§7.4、§8、§9、§10、§11、附录 B/D |

以下为合并稿原文。

> 本附录合并六个独立反方角色对冻结报告（`docs/analysis/2026-09-05-system-quality-deep-analysis.md`，扫描基线 db9efd9 / HEAD 6014a50）的复核结果。合并规则：同一实质的 kill 跨角色合并为一条，严重度取各角色中最高者，证据保留最强的一份；任何角色标为 UNVERIFIED / E4 的事实在此保持 UNVERIFIED。本附录不软化任何 kill，也不在角色返回之外新增分析；唯一的核对动作是读取 `starquant_live/reports.py:678-709` 以调和角色间对 `effort_share` 口径的不同描述（见 KILL-R11）。

### C.1 独立性声明

| 角色 | 视角 | 独立性 |
|---|---|---|
| Skeptical PM | 优先级 / 范围 / 操作者目标 | 只读；未运行 starquant 命令、未写文件；实盘数字用 python 从 `.starquant/live/*.jsonl` 重算，不沿用报告 E2；操作者目标以记忆文件为准而非报告转述；已核对 main（304e549/bd7cd6e） |
| User Reality Auditor | 单操作者可执行性 / 预登记负担 / 工具缺口 / LLM 限制 / 运维方式 | 只读；未采用作者四个审计子代理的输出；数字自行从 deploy/、starquant_live/、starquant_cli/、RESEARCH_LOG、launchd 日志、`.starquant/live/*.json` 复核；利益声明：本角色亦为 LLM 会话，K-7 结论同样适用于自身 |
| Evidence Prosecutor | 证据链 / 数字复现 | 未读取报告引用的 4 个审计子代理原始输出；全部数字从 `reports/research/*.json`、`.starquant/live/*` 与 HEAD 代码重推；main 用 `git show`/`git diff` 只读核对；E-09..E-11 的 scratchpad 回测不在仓库，只能对 193707Z 做一致性核对 |
| Complexity Accountant | 复杂度 / 状态与规则净增 / ratchet 记账 | 只读（未运行 pytest 以免写 `__pycache__`）；main 内容经 `git show main:<path>`；行数为本轮自测（与 ratchet 同口径）；未参考作者 scratchpad 或会话记录 |
| Delivery Saboteur | 交付契约可写性 / 验收条件可达性 | 独立子代理；只读；`trades.jsonl`/`cycles.jsonl` 只读重算；无法核实的数字标 UNVERIFIED 并降级 |
| Risk & Abuse Red Team | 运维 / 资金链路 / 并发 / 数据源滥用面 | 独立 Agent；只读；实盘状态取自 `state.json`/`heartbeat.json`/`universe.json`、`git worktree list`、`launchctl list`；仓库外事实（币安 key 权限粒度、priceProtect 语义、metrics REST 时延）标 E4/UNVERIFIED |

六个角色均声明与报告作者不是同一会话，均未执行 git 写操作，均未读取彼此的输出。

### C.2 去重后的 Kill 表（P0 优先）

| ID | 角色 | 报告对象 | 命题 | 证据（最强一份） | 严重度 | 推翻报告 | 必须改什么 |
|---|---|---|---|---|---|---|---|
| **KILL-R1** | PM（K1）、EP（K-01） | KILL-Q1 / C-1 / E-12 / E-02 / P1-01 / §0「本轮最重要的发现」/ Phase A ① / §11「不允许在 KILL-Q1 关闭前改 registry 的 tsmom 参数」/ G4「Cost of Delay 低」 | 报告的头号 P0 描述的是一个**没有在跑**的信号。实盘进程启动于 2026-09-04T17:21Z，重启用 crowding 的提交 3ac8d49 在 09-04T20:03Z（晚 2h40m），此后未重启；引擎只在启动时 `build_model_from_profile`，不热重载；88 个周期 `inputs.funding_history` 全为 false/None，而 `inputs.py:65-68` 只在 `model.needs_funding` 为真时取资金费——进程里 tsmom 是 crowding OFF，指针对应 145321Z。后果：(a) 「1.8× 触发率、49.6% 重合」量的是尚未上线的修饰器，当下受 P1-01 影响的只有 flow 探针去均值；(b) 报告漏掉一条它自己定义为 KILL-027 形状的问题——**磁盘 registry（crowding 72 → 193707Z）≠ 循环（crowding 0 → 145321Z）**，`live status --check` 与日报都看不见；(c) D-026 构造指纹（`engine.py:849-899`）不含信号参数，下一次 launchd KeepAlive 重启会把 tsmom 静默切到 crowding ON，M-010 窗口不清零，两种信号的收益混入同一证据窗口；若启动时资金费历史取不到则进入 60 s 重试循环；(d) 关闭 KILL-Q1 tsmom 半边最便宜的动作是 `git revert 3ac8d49`（零研究成本、零 M-010 清零），而 §11 恰好禁止它；Phase A 最大的 alpha 项花在修一个记录边际仅 +0.11 OOS、无配对检验、单 Sharpe SE≈0.43 的修饰器上。 | `.starquant/live/state.json` restarted_at 2026-09-04T17:21:22Z（restarts 12）；`ps -o lstart` 一致；`git log -1 --format=%ci 3ac8d49` = 2026-09-05 04:03:32 +0800；cycles.jsonl 末行 `{'bars':1442,'funding_history':False,'symbols':18}`；`git show fe85101:config/alpha_registry.yaml:36` crowding_window 0；starquant_live/inputs.py:65-68；starquant_live/config.py:170-172、starquant_cli/live_cmd.py:114；starquant_live/engine.py:849-899；docs/RUNBOOK.md:46 仍写「当前 tsmom 仍跑 crowding_window: 0」；tests/alpha/test_round6_hold_and_warmup.py:115 docstring；config/alpha_registry.yaml:17-38（round 6 无配对检验） | **P0**（PM P0 / EP P1，取高） | **是** | 任何重启之前使 registry、循环、证据三者一致（PM：回退到 crowding 0 + 145321Z；EP：KILL-Q1 修法在重启前完成并由操作者明示是否有意切换）；KILL-Q1 拆成两半：tsmom 半边由回退/重启前修复关闭，flow 去均值半边降 P2 并入 D-029 复审；新增 OPEN 发现「registry 与运行进程分叉、无检查可见」；Phase A 加入「每周期记录 registry 指纹，`live status --check` 比对磁盘 vs 已加载」（<50 行）；D-026 指纹或日报加入 registry 参数 digest；§0/E-12 改写为「flow 当下受影响；tsmom crowding 在下次重启起受影响」；G4 Cost of Delay 改「高」；Phase A ① 降为可选研究，再启用须带配对检验。 |
| **KILL-R2** | URA（K-3 P0、K-10）、RK（RK-1/2/3）、CA（CA-07） | §0 回答⑤ / §7.2 建议 1「外部看门狗」/ §7.4 P0 第 3 项 / DL-Q8 / M-Q07 / KILL-Q13「看门狗缓解一半」/ C-6 | 「异机心跳陈旧 > 2 bar → 用只读+平仓 key 调 flatten」在现有代码与运维方式下不可交付，且在它声称唯一覆盖的场景不触发：(a) 心跳是本机文件 `.starquant/live/heartbeat.json`，无推送通道（run_check.sh 只发失败 webhook），异机读不到，拉取式分不清主机死与网络分区；(b) ERROR 分支每次重写心跳，退避上限 3600 s < 2×interval 7200 s，KeepAlive+ThrottleInterval 60 的崩溃循环每 60 s 刷新心跳——IP 封禁/venue 故障下循环可 12 小时下不了单而心跳「新鲜」；`live status --check` 也要 consecutive_errors≥3 才报 ERROR；(c) `live flatten` 需完整 repo+venv+数据+状态目录，成交写进第二台机器 ledger，主机 D-032 视为 foreign；(d) flatten 不停循环、不挂 kill switch（L1-06），kill switch 是本机相对路径文件，异机写不到——「心跳陈旧但循环仍活」时每小时 flatten→rebuild，每次付 7 bps×gross（p95 1.80）；DL-Q8 演练只测「杀进程」，测不到误报；(e) 币安 API key 无 reduce-only 作用域（**UNVERIFIED，E4**），看门狗实为第二台机器上的第二把全权交易 key，云函数出口 IP 不固定还会迫使关闭白名单；flatten 连 `foreign_positions` 一起平；(f) launchd 下「杀进程」60 s 即被拉起，演练实为 `launchctl unload`，且任何 >2 小时人工维护窗口都会把健康的书平掉（两天 12 次重启、TRANSFER 重置行），无维护模式 sentinel；(g) 报告没有把看门狗自身的攻击面登记进 Kill Register。 | starquant_live/state.py:61,63,75-76；starquant_live/engine.py:188,229-238,259-263,329,418-436,423-425,773-775；starquant_cli/live_cmd.py:176-178,210,235,314-344；deploy/com.starquant.live.plist KeepAlive/ThrottleInterval 60；deploy/run_check.sh:4-24；starquant_live/config.py:80；starquant_exchange/guard.py:55-58；`.starquant/live/state.json` restarts=12；live.stderr.log TRANSFER +5000.01；(e) UNVERIFIED | **P0** | **是** | DL-Q8 重写为可交付规格：① 循环每周期主动推送「本周期 OK」（含 phase/consecutive_errors）到异机/云端；② 触发 = 连续 N bar 无 OK 推送或 phase==ERROR∧consecutive_errors≥N，不是文件年龄；③ 远端可挂起的 kill switch（循环轮询远端 sentinel / dead-man lease，取不到即本地 engage 进 reduce-only），动作顺序固定为先停交易权再 flatten；④ 不依赖 model/universe/store 的 `flatten --raw`（positionRisk → 全部 reduce-only MARKET）且只平 `bd-` 前缀对得上的仓位；⑤ 回答 key 权限问题，看门狗持只读 key 只做告警、失联平仓交给交易所侧 `closePosition` 单；⑥ 陈旧判定以 venue 时间为准（D-030）；⑦ 维护模式信号与演练脚本（unload→计时→验证→reload），falsifier 含「循环存活但心跳迟到不得触发」「flatten 后 3 bar 内零新增仓位」，演练加 `iptables` 封 venue 出口与两机断网。做不到之前：§7.4 工作量 S–M 改 M–L，回答⑤改为「先做远端 kill switch + 心跳外推」，Kill Register 新增「看门狗 key 泄露 → 任意开仓」；或把看门狗降为同机 run_check.sh + 第二告警通道并推迟到 mainnet 前。 |
| **KILL-R3** | DS（DS-1） | §9 Phase A 成功判据与停止条件 / C-2 / KILL-Q3 / §0「tsmom 在 5% FWER 下仍以 p=0.0026 通过」/ §11 升级条件 | 报告把 F1 与 F2 分开论证从未合并：「FWER 门下 tsmom 仍 PASS」用的是 1.7647，而 F1 自己认定该数是全样本序列后 91.8%（伪 OOS）。两条修法同时落地后，FWER 分位数门须作用在诚实的走前 OOS 上——16 点网格走前 OOS 是 1.376（E-08，registry 注释「040252Z, n=87, OOS 1.376」）；按 E-14 的零假设年化 SD 0.438，5% FWER 在 87–110 次试验下阈值 ≈ 1.42–1.45，`verdict.py:57-60` 判 `oos < threshold → FAIL`。因此 Phase A 预登记判据「tsmom 在修正总体 + FWER 门下仍 PASS」要么只能靠 F1 指出的人为高估数通过，要么按 F1 修法（单配置最多 WEAK_PASS）字面上永远达不到 PASS；停止条件「tsmom FAIL → 停书复审」会被尺子的修复本身触发，与 P1-01 无关。**交叉提示**：EP K-02（KILL-R22）指出 1.376 与 1.76 属跨构造比较（grid 16 / pit 146 / 0.15 / D-034 前），当前构造下 16 点网格不存在——两条 kill 共同指向同一动作：先算。 | verdict.py:57-60；multiple_testing.py:203；config/alpha_registry.yaml:107-109；报告 E-08、E-14、§4.1 F1/F2、§9 Phase A 行。阈值数字为 E2 推算（**UNVERIFIED**，须 scratchpad 计算），机制 E1。 | **P0** | **是** | Phase A 开工前先在 scratchpad 对当前构造跑一次网格走前 OOS 并算 FWER 5% 阈值；判据必须写明 FWER 门作用在哪一个 OOS 数（单配置尾段还是网格走前）、成功是 PASS 还是 WEAK_PASS；若诚实答案是 WEAK_PASS 或 FAIL，§11 升级条件与 §0「tsmom 现行结论不倒」都要改写；停止条件改为不被尺子修复本身触发（另见 KILL-R27）。 |
| KILL-R4 | PM（K4）、URA（K-1）、DS（DS-3） | §4.1 F1 修复「必须带 `--holdout-months ≥ 1` 且单独报告 holdout 段」/ §7.1.4 第 4 条 / DL-Q2 / KILL-Q2 / Phase A ② / 附录 B（漏列 KILL-006） | 「holdout 必选」直接推翻操作者 2026-09-04 的书面裁决 KILL-006 §二「六个月 holdout：不启用……刻意不使用」（RESEARCH_LOG:750-760）；报告继承的是同日更早的一条「建议（待操作者确认）」（:740），CLI 帮助文本也写 `unused by choice`；附录 B 未列 KILL-006 被重开。且与 Phase A ① 自相矛盾：① 要求与 193707Z「像对像」比较（M-Q01 重合 ≥95%），而 RESEARCH_LOG:736 明确 holdout 会改 fold 边界、registry 每个 OOS 数字重出。实现层面：代码里 `--holdout-months` 只扣除不评估（`held` 仅计 bars_reserved），「单独报告 holdout 段」需新代码；一旦每次 validate 都评估尾段，这一个月就被 225 个 mined 候选逐个看过，不再是 holdout；对 tsmom，最近一个月已被 ledger 91–93 个配置看过；1 个月 ≈ 720 根小时 bar，年化 Sharpe SE≈3.5，「holdout 段 Sharpe > 0 且 ≥ 走前 OOS 一半」无区分力。 | docs/RESEARCH_LOG.md:732-760；starquant_cli/research_cmd.py:374-378（help）、:412-429,516,569（holdout 仅记录）；报告 §4.1 F1、§7.1.4 第 4 条、§10 DL-Q2、§3.2 C-1 falsifier、附录 B | P1 | 是 | F1 修复只保留 `oos_is_full_sample_tail` 标注 + 网格走前 OOS 并列；删掉 holdout 必选；DL-Q2 验收不得以 holdout 段为条件。若要重开 KILL-006，必须作为独立操作者决定写进附录 B 并接受全部 OOS 数字重出的代价；若保留 holdout 评估，须做成一次性、单独记账的门（每评估一次算一笔家族试验，评估过的尾段对后续候选作废），tsmom 重跑不适用。 |
| KILL-R5 | URA（K-4）、DS（DS-2）；RK 在 upheld 中补证 | KILL-Q1 数字 / P1-01「实盘 15 币」/ DL-Q1「研究面板 30 币 ⊃ 实盘 6 币」/ M-Q01 / §4.1 P1-01「修法明确」 | (a) 实盘参照总体不是固定 15 币：`refresh: daily`，09-05 进 LINK、09-06 进 TUT/UNI，当前 universe.json 18 币、heartbeat universe_size 18；报告的 n=15 算术与固定面板等价测试描述的是过期快照，真正的契约是逐日变化的等价关系。(b) 修复契约欠定：`cross_sectional_rank` 按 (rank−1)/(count−1) 归一，n=30 与 n=6 的名次贡献按构造不相等，「⊃ 且贡献逐位相等」对秩算子不可满足；方案一（研究侧 compute 前裁面板）会把时间序列输入一起掩掉——币退出再入选时 `rolling(72, min_periods=72)` 得 NaN→`fillna(0)`，72 根 bar 内永不判拥挤，而实盘对新入选币拉满 1,442 根历史立刻能算，这是新口径漂移；方案二（eligible 传入 compute）要改 `SignalFunction` 契约，波及 7 个信号、`to_signal`、`strategy_scores`、`verify.py` M-011 与 KILL-027 守卫测试；(c) 即使修完，实盘参照 = `managed_symbols()`（universe ∪ leaving，实时成交额+滞回），研究参照 = 当日时点成员（均值 17.58），同规则不同实现，M-Q01 ≥95% 是期望不是规格。 | config/live.demo.yaml:93-103；live.stderr.log 09-05/09-06 `universe refreshed: entered=…`；`.starquant/data/universe.json` symbols=18；starquant_alpha/features.py:97-102；tsmom.py:185-191；flow.py:87-88；model.py:114-130；signals/base.py:14；mining/search.py:219-244；engine.py:121-123,277-280；inputs.py:54-63；verify.py:128-135；test_round6_hold_and_warmup.py:115-140 | P1 | 是 | 契约定义为「横截面算子的参照集合是显式参数，只作用于秩/去均值步骤，不作用于面板」；实盘传 universe（并决定 leaving 是否计入），研究传当 bar 时点成员；加逐日成员日志；测试拆两条（同一参照 → 逐位相等；参照 ≠ 面板列 → 结果随参照变而不随多余列变）并对真实逐日 universe 序列做等价；M-Q01 改按日重合率并预登记非零残差容忍度；重写 `test_shipped_registry_live_path_matches_research_path`；P1-01 段落里 15/3 的数字标注日期。 |
| KILL-R6 | DS（DS-4 P1）、PM（K5）、EP（K-03）、RK（RK-9） | L1-01 / KILL-Q4 / §0「第三重要的发现」/ E-18「四分之三成交」/ DL-Q3 / M-Q03 基线 73% / §4.1 修法「now − last_close < 120 s 才 immediate」 | 数字可复现（n 87、中位 21.6 分钟、72.4% > 60 s），但「73% 迟到」是按成交笔数加权、被 3–4 个操作者事件主导的开发期比率，不是稳态：迟到集中在 09-03 06:00（首次建仓 14 笔）、09-04 05:00（flatten 事故恢复 14 笔）、09-04 14:00/16:00（重配置/账户重置后整本书重建）；按周期看 88 个周期里 22 个 `--immediate` 周期承载 119 笔中 90 笔；最后一次重启后 8 笔常规周期成交全部准时（0/8）。这些 bar 都有准点 cycle 行，说明迟到的是整本书重建或补跑，不是同 bar 重复下单（id 按 (tag,symbol,bar) 派生 + query-before-submit 已挡）。修法「120 s 窗口」自身开新窗口：会把 143 s 的补跑变成 57 分钟陈旧持仓、flatten 后重启变一小时空仓、崩溃后最长 59 分钟无人对账；`startup_reconcile` 仍无条件撤全部挂单，Phase C 一旦挂原生止损，每次重启先撤保护单再等最长一小时；M-Q03 会读到 0% 而口径偏差搬到无仪表计数的「漏掉的再平衡」；120 s 不是推导出来的（ThrottleInterval 60 + ExitTimeOut 30 + 启动拉数据已接近）。为此把 M-010 计数「从修复后重开」对「持续证据」目标是不成比例的代价。 | trades.jsonl / cycles.jsonl 三个角色独立重算；starquant_live/rebalancer.py:59,180；execution.py:40-42；scheduler.py:21-23,33-43；engine.py:207-223；reconciler.py:98-107；deploy/run_live.sh:25；com.starquant.live.plist；docs/RESEARCH_LOG.md:1302 | P1 | 是（机制成立，归因与修法被推翻） | E-18 并列给出按周期（22/88、6/16 交易 bar）与按 bar 小时持仓口径；M-Q03 改为「迟到入场仓位的 bar 小时占比」或至少按周期计，同时计漏掉的再平衡，基线改为稳态数字；DL-Q3 拆两步：启动始终做只读对账 + 保护单核对/重挂（不下 rebalance 单），rebalance 部分才受窗口约束；定义「补跑 vs 跳过」策略与漏掉 bar 计数器；窗口长度从 grace+throttle+启动耗时推导并写进 config；与 L1-06 绑定处理；L1-09 按前缀撤单先于 DL-Q3；不重开 M-010 计数，改为 trade 行打 `late_seconds` 标签并在 M-010 里剔除（报告 M-010 已写「迟到成交排除后」，两处应一致）；从「第三重要」降为运维项。 |
| KILL-R7 | PM（K3）、URA（K-6） | §0 答案① / §9 路线图与三个 Phase 成功判据 / §10 M-010 / KILL-Q4「M-010 计数从修复后重开」/ §11 真实资金解除条件「修复后 30 天干净 M-010 窗口」/ G4 | (a) 操作者第一目标「持续的 demo 盈利证据」在报告时间尺度上统计不可达而报告没说：30 天窗口年化 Sharpe SE≈3.5，t=2 下把 1.7 与 0 分开需约 1.4 年构造不变的干净数据；88 个周期已跑过 4 个构造指纹（None:28 / df6c:7 / a53e:15 / 0dcd:38），当前构造仅 38 根 bar、归因 tsmom −13.43 / flow +3.06 USDT（≈ −0.1% 权益），信息量为零。(b) 证据窗口钉在 `construction_fingerprint` 上每次改构造清零，而 12 周路线图持续在改：Phase A ① 更新指针要重启、P1-01 修复、KILL-Q4「计数重开」、Phase B ③ pit 重跑后改 registry、Phase C ⑤ `vol_target` 重推——30 天干净窗口最早从第 12 周之后开始，真实资金最早约第 16 周，报告没写这个日期。(c) Phase A ③ 落地前每次部署重启都是 `--immediate`（run_live.sh:25，main 同样），部署本身制造报告要求 ≤5% 的迟到成交；`report daily --check` 已因 changes_7d>1 连续 36 小时同文 FAIL 且无去重（L1-11）。(d) demo 真正能证明的是执行保真与无人值守存活，报告在 M-010 之外没为此定义任何 demo 成功判据。 | memory: starquant-alpha-first-rebuild、starquant-holdout-is-the-live-period；cycles.jsonl 构造分布；attribution.jsonl 19 行合计；engine.py:849-874；docs/RESEARCH_LOG.md:738；deploy/run_live.sh:25 与 `git show main:deploy/run_live.sh`:25；check.stdout.log 40 条 FAIL 其中 36 条同文；报告 §10 M-010（无功效计算）、§9/§11 无日期 | P1 | 是 | Decision Memo 答案①写出功效计算（demo P&L 一年内不可能裁决 alpha）；demo 目标改写为「执行保真 + 无人值守存活」并给指标（迟到成交占比、换手 vs 回测、滑点 vs 模型、连续无人干预天数、registry≡循环一致性检查）；所有改变实盘构造/信号的变更捆绑成一次重启（Phase A 内），此后冻结到 Phase C 末；③（`--immediate` 条件化）提到 Phase A 第 0 步独立部署；路线图按「构造冻结点」画出 30 天窗口最早开始日与真实资金最早日期；L1-11 告警去重提到看门狗之前；M-010 保留为长期指标但不再作 Phase 判据；「每次改构造清零」写进 §11 解除条件的显式假设。 |
| KILL-R8 | URA（K-2） | §7.1.4 第 5 条「每周最多一次 validate」/ KILL-Q8 MITIGATED / §9 Phase A 2 周 | 该上限没有任何工具执行，且与实际节奏差两个数量级：reports/research 在 09-03/09-04 两天生成 156 份报告（78 份 validation），09-04 02Z 一小时内 22 份；RESEARCH_LOG:740 自己写「每周一次晋级从未实现」；唯一计数器 `changes_7d` 已连续 36 小时报同一 FAIL 无人处理。协议与 Phase A 自相矛盾：① 要重跑两臂 + book，⑦ 要重跑 225+新族并把幸存者送 validate，光 ① 在周上限下就要两周。KILL-Q8 标 MITIGATED 的依据只是散文。 | reports/research 文件名统计（76 份 20260903、80 份 20260904）；docs/RESEARCH_LOG.md:740；starquant_cli/live_cmd.py:424-427；check.stdout.log 最近 36 行同文 FAIL | P1 | 是 | 上限做成机械规则（`_record_trial`/`trials.jsonl` 层面：7 天内已有 1 次 PASS 晋级则 validate 拒绝写 registry 指针，或至少拒绝 `--prior-trials` 缺省），否则从协议删除并把 KILL-Q8 改回 OPEN；Phase A 时间表按「validate 不限次、晋级限一次」重写。 |
| KILL-R9 | URA（K-7） | §7.1.5「LLM 的位置」/ KILL-Q9 MITIGATED / §0 回答③ / 附录 B「P17 维持」 | 「LLM 禁止评估候选、选择进 validate 的对象、写 ledger、进入 CI」无执行主体：最近 200 次提交 129 次带 Co-Authored-By: AI，09-04/05 两天 60 次；P11–P17 的预登记、validate、registry 重指、RESEARCH_LOG 条目都出自 AI 会话；本报告本身由 LLM 产出且已在 Phase A ⑦ 里选定要 validate 的对象并跑了 `research backtest`。「离线助理 vs 提案者」的边界在助理同时是敲 validate、写 trials.jsonl 的那双手时不存在；A-004 的可交换性论证已适用于现在的人+LLM 循环（P17、D-039 都是条件于上轮结果的自适应提案）。 | `git log -200 --format=%b \| grep -c 'Co-Authored-By: AI'` = 129/200；09-04/09-05 共 60 次提交；be963ad 等研究提交署名 AI；报告 §8 KILL-Q9 证据列为「—」；报告头部「一次 research backtest 输出到 scratchpad」 | P1 | 是 | 「谁提案」规则换成「与提案者无关的机械规则」：(1) 到达 validate 的每个候选必被计费（mine 的 `declared_trials` 跨运行入 ledger 即 F7 修法），(2) 预登记必须是早于报告时间戳的 git 提交，由 `report weekly` 或 CI 校验时间顺序，(3) KILL-Q9 改 OPEN 直到 (1)(2) 落地；§0 回答③改为「不区分 LLM 与人，只区分是否进 ledger」。 |
| KILL-R10 | URA（K-5）、EP（K-08） | 分析头部「同伴会话通报」/ E-05 / C-3 / §7.1.1 / §9 Phase A ⑤⑥ / E-33 / §7.4 P1「合并 D-040/D-041」 | (a) 报告只通报 main 的 D-040/D-041，漏掉与 Phase A 直接重叠的在途工作：worktree 分支 `feat/mining-funding-node`（be963ad，09-05 13:50，8 文件 +1166 行）已实现 `Funding(window)` 叶节点、42 条 carry 族（225→267）、`Expr.reads_funding`、mine 的 `run` 自描述块与 `--baseline`，且提交说明指出 P14 的「干净阴性」是在读不到 funding、vol_target 0.15 下测的——直接削弱 E-05「225 候选全阴性」。仓库有 8 个 worktree、4 条各自领先的分支（`session/vibrant-turing-bfe5a6` +1114 行 13 文件、`session/overlay-books`、main +731 行）、一条 stash、未提交的 +156 行 RESEARCH_LOG（D-039）；单操作者动 `tsmom.py`/`model.py`/`research_cmd.py` 前必须先跑合并列车，2 周 Phase A 没有这一步。(b) main 不在 bd7cd6e 而在 304e549（多一条 `fix(cli): research overlay dropped the books when --min-history rebuilt the model`，改 research_cmd.py:860-870），合并清单少一项。 | `git worktree list`（8 条）；`git log refactor/alpha-first..feat/mining-funding-node` = be963ad，`git diff --stat` 8 files +1166；be963ad 提交正文；`git diff --stat refactor/alpha-first...session/vibrant-turing-bfe5a6` 13 files +1114；`git status`；`git stash list`；`git log main -3` | P1 | 是 | Phase A 前置「合并列车」步骤，列出四条分支的合并顺序与冲突文件；Phase A ⑤ 改为「合并 be963ad 后剩余 5 个节点」，⑥ 的 mine 自描述部分标为已在途；E-05 补注「P14 未含 funding、在 0.15 下测」，C-3 falsifier 以 267 为基数；头部与 §7.4 合并项改为 D-040/D-041/304e549 三项。 |
| KILL-R11 | CA（CA-02 P1）、PM（K6）、URA（K-8）、DS（DS-7） | §9 Phase A「≥ 90% alpha（①②⑤⑥⑦为 alpha）」/ Phase B「≈ 75%」/ Phase C「70%」/ §6.5 Small-Build / 记忆 starquant-alpha-effort-target-90 | 报告的 alpha 占比不是用仓库自己的尺子算的。合并者核对 `reports.py:678-709`：alpha 桶 = `starquant_alpha/` + `tests/alpha/`（含 validation/、mining/）；research 桶 = `docs/RESEARCH_LOG` + `docs/analysis/`；`alpha_share = (alpha + research)/total`；`starquant_cli/`、`starquant_live/`、`starquant_data/` 一律 infrastructure；`reports/` 不计。两个方向都对报告不利：(i) 按仪表，Phase A ①的实盘侧修复在 `engine.py`、研究侧与 F1/F3 字段（research_cmd.py:453-463）、⑥ 的 `_resolve_mined` 通道与 mining_ledger 文件 I/O（ledger.py 首行「the CLI does the file I/O」）都在 CLI/live → infrastructure；Phase B ①③ 数据摄入在 starquant_data → infrastructure；`starquant report weekly` 会明显低于 90%。(ii) 按操作者原话「alpha (signals/factors)」，Phase A ①②③④ 是度量/管线修复，真正的信号/因子工作只有 ⑤⑥⑦，按此口径约 50%；仪表把本报告这份 528 行分析文档也算进 share，「≥90%」是仪表口径的产物。 | starquant_live/reports.py:678-709（合并者核对）；memory: starquant-alpha-effort-target-90；ledger.py:1-11；research_cmd.py:453-463；报告 §9 表「alpha 占比」列与注释 | P1 | 是 | 用 `effort_share` 桶规则重算三个 Phase 的占比并写入 §9，同时注明操作者「信号/因子」口径的差异（诚实写「本两周按操作者口径约 50%，原因是先修尺子」）；若 Phase B 真实占比 < 50%，要么显式记为「非 alpha 但前置」，要么先在 `effort_share` 里登记「数据宽度是 alpha 供给」的规则变更（这是决策不是标签）；或把 `starquant_alpha/validation`、`starquant_alpha/mining` 与 `docs/analysis/` 拆成 research 桶单独报告。 |
| KILL-R12 | CA（CA-01 P1、CA-10）、DS（DS-7）、URA（K-8） | §9 路线图 Phase A/B/C / §6.5 Option Set / §7.4 生产就绪清单 / §10 全部 DL / E-33 / Phase B ⑥ | 整份方案没有一处对照 `tests/architecture/test_source_budget.py` 的 ratchet 记账。实测六个包全部恰好顶在 CEILING 上（alpha 4876/4876、live 4198/4198、cli 2582/2582、data 1258/1258、exchange 539/539、shared 280/280）：任何包净增 1 行都让 `test_no_package_grows_past_its_measured_ceiling` 失败，每个提交都要写抬上限理由（该文件已记 19 次抬升，15 次是非 alpha 仪表化）。Phase B ①③⑤、Phase C ④⑤⑥ 全部落在 data/live/exchange，按已有密度类推非 alpha 新增 ≥ 2,000 行，而 starquant_live 已超计划 1,171 行；报告通篇没有一条「删除什么」。合并 main（D-040/D-041）被记为 'S' 且不计行数，但 main 的 CEILING 已比本分支高 +64 live / +18 cli / +117 data = +199 非 alpha，并带一道新的启动数据集门。 | tests/architecture/test_source_budget.py CEILING 块（:273-297）与本轮 wc 实测；同文件 docstring「19 raises」；`git show main:tests/architecture/test_source_budget.py`（live 4262 / cli 2600 / data 1375）；报告 §9/§7.4 grep 'test_source_budget\|ratchet\|删除' 零命中 | P1 | 否 | §10 每一行 DL 增加「按包行数估计 + 对应删除项或显式 ceiling raise N」；Phase B/C 中凡新增非 alpha ≥ 100 行的项必须指名同量级删除（候选见 KILL-R16/R17/R29），否则移出 Must/Should；ratchet 抬升列入每个 Phase A 交付项的 DoD；Phase B ⑥ 标注「+199 非 alpha（已在 main 抬升）」纳入占比重算。 |
| KILL-R13 | PM（K2） | KILL-Q12 / C-6 / §7.4 / Phase B ⑤ / Phase C ④⑤⑥ / §6.5 Scope Firewall | 操作者现行范围是「demo 是测试环境，真实资金推迟，production/mainnet 明确不在范围内」。报告却把两个 P0 之一（Q12）、一个 P0 Claim（C-6）、§7.4 的 5 个 P0 + 6 个 P1、Phase B ⑤、Phase C ④⑤⑥ 全挂在「真实资金前」这个被推迟的目标上，并据此把 Phase B/C 的 alpha 占比拉到 75%/70%，对着 90% 的目标——Won't 列表写了 mainnet，正文却为 mainnet 排了 6 周以上非 alpha 工作。真正服务「24h 无人值守 demo」的只有单实例锁、熔断退避、告警去重和一个只需告警的看门狗。 | memory: starquant-alpha-first-rebuild；报告 §7.4 全表、§8 KILL-Q12、§9 Phase B/C 行、§6.5；deploy/run_check.sh:4-24 | P1 | 否 | 所有「真实资金前提」项移出 12 周路线图，单列「mainnet pre-flight backlog」，只在操作者重开 mainnet 时启动；KILL-Q12 改 DEFERRED（范围）而非 OPEN P0；Phase B/C 只保留服务 demo 无人值守的最小集（锁、退避、告警去重、异机告警），alpha 占比据此回到 ≥ 85%。 |
| KILL-R14 | RK（RK-4） | §7.2 建议 2「距离 = 3× 软件止损 ≈ 18 日波动单位」/ KILL-Q10 / C-5 | 原生灾难止损对当前实盘 18 币里 7 个多头方向根本下不了单：`unit` > 1/18 时止损价 = entry × (1 − 18·unit) ≤ 0。state.json：AKEUSDT 0.256、CYSUSDT 0.149、TUTUSDT 0.140、ENAUSDT 0.081、UNIUSDT 0.080、ZECUSDT 0.078、TRUMPUSDT 0.072；空头方向对应止损在 +130%…+461%，等于不存在。恰恰是跳空风险最大的名字保险覆盖为零；C-5「作为保险有条件为正」的「有条件」在这些名字上是空集；「回测中理应零触发」是因为它在这些名字上不可能触发。 | `.starquant/live/state.json` `exit_states.*.unit`（2026-09-06T02:00Z）；starquant_alpha/overlays/exits.py:131-136；报告 §7.2 建议 2 | P1 | 是 | 距离改为 min(k·unit, 固定价格百分比上限如 40%)，多头做 price > 0 可下单性断言；用 MARK_PRICE 语义在 1h bar 重放触发次数时，「不可下单」的币-bar 单独计数写进 falsifier；C-5 证据块按符号分层。 |
| KILL-R15 | CA（CA-06）、RK（RK-5） | §7.2 建议 2 及 2(b) 生命周期 / KILL-Q10 / C-5 / 附录 B「D-012 收窄式重开」/ Phase C ⑥ / §7.4 | (a) 重开违反 D-012 自己预登记的重开条件：`docs/analysis/2026-09-03-exits-pool-sizing.md:181` 写明重开条件是「进入 mainnet 且信号尺度进入日内」，两条都不满足，报告以「灾难保险」为新理由重开而没把条件变更记为决策。(b) 成本：Venue 协议 16 方法三份并行实现（binance 16 / PaperVenue 10 / FakeVenue 10，10 个测试文件依赖），algoOrder 至少 4 新方法 × 4 处；clientOrderId 三级分类 + reconciler 过滤 + state 新字段 + 重启对账；demo 是否支持 UNKNOWN；报告自己的 2×2 说看门狗覆盖 3/3 失联情形、原生单只覆盖 2/3。(c) 本地写守卫对 `/fapi/v1/algoOrder` 一无所知：`is_risk_reducing` 对不在 ORDER_PATHS 的路径一律返回 True，kill switch 下一张不带 closePosition 的风险增加型 algo 单会被放行；DELETE 永远放行，撤保护单也算「降风险」；rest_client 对 −4120 无处理。(d) `priceProtect` 触发时若 mark/last 偏离过大会把单取消（**UNVERIFIED，E4**），之后仓位裸奔；报告引用的 freqtrade 参考有 60 s 刷新与被撤重挂，§7.2 2(b) 的四步只有挂/翻转/平仓/重启。 | docs/analysis/2026-09-03-exits-pool-sizing.md:180-181；starquant_live/ports.py；tests/fakes/fake_venue.py、starquant_live/paper.py；`grep -rl FakeVenue tests` = 10；starquant_exchange/guard.py:18,43-49；grep algoOrder/priceProtect/workingType 零命中；reconciler.py:97-107；报告 §7.2 2×2 表、E-25 | P1 | 是 | CA：从 Phase C ⑥ 与 §7.4 删除原生止损；D-012 防火墙原样维持；KILL-Q10 改 CLOSED（范围外）；将来重开先记录「重开条件由 mainnet+日内 改为 X」的决策。RK（若仍保留）：ORDER_PATHS 加入 `/fapi/v1/algoOrder`（及 batch），`is_risk_reducing` 对 algo 单要求 closePosition/reduceOnly，DELETE 保护单在 kill switch 下需显式豁免记录；生命周期加「每周期对账：应有而无 → 重挂，priceProtect/触发事件送 alerts」；falsifier 加「循环存活期间触发要先排除 mark 异常」。守卫盲区先于生命周期修。 |
| KILL-R16 | CA（CA-03 P1）、DS（DS-8） | §7.1.4 第 2 条 / DL-Q5 / KILL-Q5 / F7 修法 / Phase C 判据「进入探针书」/ KILL-Q8 | mining_ledger.jsonl 是第二本 ledger：第二套 schema、去重规则、「validate 对 mined_* 强制读取」的门；同时 KILL-Q5 又在扩展 trials.jsonl 签名——一个 DSR 分母两个真值来源，且 mine 报告已被 P17 判「不能自我复现」（RESEARCH_LOG:1421）。F7 真实修法是一行：validate 入口调 `_resolve_mined(strategy)`，与 correlate（research_cmd.py:751）同。此外「mined 进 validate 通道」只打通研究进程：`mined_<hash>` 解析按 `enumerate_candidates()` 进程内重推且只在 research_cmd；`live/config.py:150` 与 `model.py:114` 直接 `get_signal` → registry 一旦指向 `mined_<hash>`，`live run`/`verify`/`report` 建模时 KeyError，Phase A ⑥ 的 PASS 报告无法被探针书引用；Phase A ⑤ 扩空间改变枚举结果，旧候选指针会断，新空间累计 `declared_trials` 追溯计到旧候选；mining_ledger 与 `--prior-trials` 并存则重复计费，报告没写谁替代谁；哈希在新增节点后是否稳定 **UNVERIFIED**。 | research_cmd.py:157-172,597-609,751,1233-1243,1666-1669,1720-1746；ledger.py:1-11,46-48；mining/search.py:78,159-215,219-244；signals/__init__.py:79-96；starquant_live/config.py:150；model.py:105-114 | P1 | 否 | 砍掉 mining_ledger.jsonl：mine 每轮把 `declared_trials` 作为 TrialRecord（strategy 取族名，param_key 取候选 hash，sharpe 取全样本值）经现有 `_record_trial` 追加到 trials.jsonl；validate 对 mined_* 先验计数从同一 ledger 按族聚合——一本 ledger、一条去重规则；定义 mined 候选的持久身份（registry 存表达式字符串，按表达式解析），给实盘/verify/report 共用解析入口；写明与 `--prior-trials` 的算术关系（替代，跨轮累计只对同一搜索空间版本有效），「搜索空间版本」进 ledger 签名。 |
| KILL-R17 | CA（CA-04） | §7.1.4 第 3/4/5 条 / DL-Q2 / KILL-Q3 修法 / C-2 | 报告只加门不减门。现有 verdict 已有 7 道（verdict.py:30-39），报告再加：holdout 段门、每轮 20 个随机表达式阴性对照、每周最多一次 validate、mining_ledger 强制读取、`p_family`。「随机表达式零假设」与已存在的 `noise_null`（multiple_testing.py:93、:268；E-07 已引用 noise-null 0.033）功能重叠，是第 5 个零假设；代码 docstring（multiple_testing.py:186-188）与操作者记忆都写明 NW t 门在小时级 ≈ Sharpe×√年、不构成第二个条件，报告却留着它。F2 本身是原地替换（:203 一行），净复杂度为零——这是唯一该做的。 | verdict.py:30-39,57-83；multiple_testing.py:186-188,203,268；报告 §7.1.4、DL-Q2 | P1 | 否 | F2 原地替换保留；删除「20 个随机表达式对照」（用现有 noise_null）；同一提交删除 `pass_oos_t`/`weak_oos_t` 或降为 reported-not-enforced；「每周一次 validate」写进 RESEARCH_LOG 作为流程而非代码规则（与 KILL-R8 的机械化要求二选一，须明示）；规则净变化 ≤ 0。 |
| KILL-R18 | CA（CA-05） | §7.4 P1「用户数据流（listenKey + ws）」/ §6.3 借鉴表 / Phase C ④ / §6.2 弱项 1 | 用户数据流在当前架构规则下不可能「M 工作量」落地：`test_import_rules.py` 的 ALLOWED_THIRD_PARTY 把 starquant_exchange 限为 {httpx}、starquant_live 限为 {numpy,pandas,httpx,yaml}；httpx 无 WebSocket 客户端；pyproject 六个运行时依赖无 ws 库；仓库对 websocket/listenKey 零命中。落地必须新增运行时依赖 + 修改架构规则测试 + listenKey 30 分钟 keepalive + 断线重连状态机 + 事件解析，并制造第二个仓位真值来源，与 reconciler.py:100「Exchange positions are the only truth」冲突。报告一字未提。 | tests/architecture/test_import_rules.py ALLOWED_THIRD_PARTY；pyproject.toml dependencies；grep 零命中；reconciler.py:96-107 | P1 | 是 | 从 §7.4/§6.3/Phase C 删除用户数据流；MARGIN_CALL/强平可观测改用现有周期内 REST（positionRisk 的 liquidationPrice 距离 + `/fapi/v1/forceOrders` 一次 GET）——零新依赖、不改架构规则；若坚持 ws，先登记 D-xxx「修改依赖白名单」并给出行数。 |
| KILL-R19 | RK（RK-6）、URA（K-11） | §7.4「切换 mainnet」行 / §11 真实资金解除条件 / §4.2 Ⅴ | 上线清单至少缺四项且把 env.sh 写成已存在：(a) 全仓/逐仓与多资产模式既不设置也不断言（marginType/multiAssetsMargin 零命中，`_ensure_leverage` 只 POST leverage）；mainnet 账户残留 ISOLATED 或 multi-asset 会让 `scale_orders_to_margin` 与 `daily_loss_pause` 口径失真——报告 §7.3 自己论证逐仓会制造强平却没写「断言 CROSSED」。(b) state.json 不能沿用而清单没说：`equity_hwm` 只增不减、`day_start_equity`、`exit_states` 的 demo 入场锚点、`last_income_ms`、`leverage_set` 全部会带进 mainnet；demo HWM 10,924 对 5k 真实账户意味着首周期 drawdown 54% → risk_budget rollback ALERT。(c) 启动撤销账户全部挂单、flatten 连 foreign 仓一起平——mainnet 账户若有手工仓/挂单，第一次启动即被清；L1-09 放在 P1 而非 arming 前置。(d) 告警通道非必需：webhook 为空时 run_check.sh 只写日志。(e) `~/Library/Application Support/starquant/` 下没有 env.sh，循环靠 run_live.sh:18 对 ~/.zshrc `grep '^export STARQUANT_'` 再 eval 取密钥（demo key 与 webhook 同在 zshrc）；§7.4「S」的估计没含把密钥迁出 zshrc 的一步。 | grep marginType/multiAssets/ISOLATED/CROSSED 零命中；engine.py:188,520-548；state.py:17-40；reconciler.py:104-107；engine.py:423-425；deploy/run_check.sh:19-27；deploy/run_live.sh:12-19；`ls ~/Library/Application Support/starquant/` 无 env.sh | P1 | 是 | arming 清单加：启动断言每个 managed 符号 marginType==CROSSED（或显式设置）且 multiAssetsMargin 与验证口径一致；`state_dir` 必须全新，启动拒绝 `started_at` 早于 arming 时刻或 `equity_hwm` 存在的 state；账户空仓空挂单断言（否则拒绝启动而不是撤单）；webhook 已配置并完成一次端到端告警演练；「先迁 env.sh（600）并移除 zshrc 回退」；看门狗契约写明密钥存放方式。这些进 §11 真实资金解除条件。 |
| KILL-R20 | RK（RK-7 P1）、DS（DS-5） | KILL-Q7 / DL-Q4 / §4.1 L1-02「降为中危」「修法便宜（flock + 心跳 pid）」 | (a) Darwin 上没有 `flock(1)`（`which flock` → not found），run_live.sh 的 shell 层包 flock 不可交付，只能在 `live run` 里用 `fcntl.flock`。(b) `flock` 挡不住真实并发来源：本机 7–8 个 git worktree，state_dir、kill switch、将来的锁都是相对路径，凭据由 run_live.sh 从 ~/.zshrc 全局 eval，worktree 里没有 .starquant——在任一 worktree 里跑 `starquant live run --allow-unvalidated`（无 `--armed` 门，默认非 dry-run）就是第二个交易同一账户的进程：锁文件各自独立、kill switch 互不可见、universe 回落到 config/universe.yaml 的 always_include，非重叠符号仓位对主循环是 foreign，进程一退出成孤儿仓——这正是记忆里「多会话并行走 worktree」的日常方式。(c) `live flatten` 自建 LiveEngine 直接下单与循环零协调（09-04 事故路径）；锁只罩 run 则 flatten 裸奔，锁罩 flatten 则循环存活时应急平仓被拒。(d) 退出码与 `KeepAlive.SuccessfulExit=false` 交互：第二实例 exit 0 则 launchd 不再拉起该 label 直到手动 reload，非零则每 60 s 重启并每次告警（L1-11 无去重）。(e) 两进程由同一 scheduler 在 close+5 s 锁步唤醒，竞态碰撞不是随机到达，「只剩竞态窗口」的概率论证不成立。 | 本机 `which flock`；`git worktree list`；starquant_live/config.py:39-47,74,234-236；deploy/run_live.sh:14-18,25；starquant_cli/live_cmd.py:88-100,314-344；scheduler.py:30-41；execution.py:40-43；com.starquant.live.plist；`worktrees/*` 均无 .starquant | P1 | 是 | KILL-Q7 升 P1 并进 Phase A；锁的实现为 `fcntl.flock`、键绑定到账户/key 指纹（如 `~/Library/Application Support/starquant/<sha256(api_key)[:16]>.lock`）而不是目录，路径绝对化（与 L1-07 同修）；非 dry-run 的 `live run` 必须显式 `--armed` 且校验 `REPO` 与 plist WorkingDirectory 一致；`live flatten` 与看门狗走同一把锁（flatten 先置 kill-switch 再抢占）或在交易所侧按 client id 前缀对账后再下单；启动时 foreign_positions 非空当作告警而非静默；DL-Q4 写明被拒实例的退出码与 launchd 行为、告警去重。 |
| KILL-R21 | RK（RK-8 P1）、URA（K-9） | KILL-Q11 / DL-Q6 / Phase B ①「metrics / premiumIndexKlines / markPriceKlines 摄入」工作量 M / Phase B 停止条件「只用于 t−1 日」 | (a) 真实风险不是「时点对齐前视」而是研究与实盘不同源且实盘源不可回放：研究面板吃 data.binance.vision 的 metrics 日归档（T+1），实盘每小时只能走 `/futures/data/openInterestHist` 等 REST（约 30 天、5 m 桶、时延未核）。若桶 t 在 t+5 s 尚未可得，实盘用 t−5 m 桶而研究用 t 桶——KILL-Q1 的同形复制；M-011 `live verify` 与 D-024「证据可复现」假设公共数据可重取，30 天之外 REST 取不到、归档 T+1，验证器对 metrics 信号结构上失明；「只用于 t−1 日」在实盘侧不可执行（当天没有 t−1 归档）；报告的 15 分钟核查核的是归档，核不到 REST 与归档是否同值同延迟。(b) 工作量：`starquant_data/archive.py` 只支持 monthly klines zip，E-22 自述 metrics 无 monthly 只有 daily，摄入是新路径：231–877 币 × 约 1,500–2,190 个日文件（各带 CHECKSUM）≈ 35 万–190 万次小下载，加 manifest 扩展（D-040 尚在 main）、run_data.sh 日作业扩展与时点对齐；当前 sync 只刷新池内币，池外币停在 09-03，metrics 会继承同样陈旧模式；住宅网络吞吐 **UNVERIFIED**；REST 30 天窗口与发布时延 **UNVERIFIED（E4）**。 | 报告 E-22/E-23/KILL-Q11、§9 Phase B 停止条件；deploy/run_check.sh:29-37；starquant_data/binance_public.py 与 live_feed.py 无 openInterest/metrics 端点；starquant_data/archive.py:1,64,114；deploy/run_data.sh；data.stdout.log 尾部 `last=2026-09-03 11:00` | P1 | 否 | DL-Q6 加「同源契约」：自建每 5 m 落盘的 REST 快照流作为实盘与研究共同真源，逐日与归档 diff 并记录差异率；信号自声明 `needs_metrics`，启动门检查快照连续性（D-023 形状）；M-011 对 metrics 信号改为比对本地快照；KILL-Q11 的核查改为三项：归档发布时刻、REST 桶可得时延、REST 与归档同桶值差；DL-Q6 拆「daily 归档下载器 + 断点续传 + 校验」与「对齐」两步，先做 20 币 × 1 年吞吐实验再定工作量；D-040 合并列为 Phase B ① 前置。 |
| KILL-R22 | EP（K-02） | KILL-Q2 / E-08 / F1 / §0「第二重要的发现」中的「headline 高估 ~0.4」 | 「16 点网格走前 OOS 1.376 因此 headline 1.76 高估约 0.4」是跨口径比较：040252Z 是 grid 16、pit 146 币（月度成员表）、vol_target 0.15、五 fold 全选 crowding 0、D-034 之前、range 起点 2021-03-02；193707Z 是 205 币日度成员表、crowding ON（全样本 1.8261 vs OFF 1.7035，修饰器本身贡献 +0.12）、D-034 之后；registry 注释自己写明 0.15 时代报告「不再横向可比」。0.4 里多少来自 F1 选择自由度、多少来自四项构造变更，报告没有分离；当前构造下 16 点网格不存在。F1 机制本身成立。 | reports/research/tsmom-validation-20260904T040252Z.json（grid_size 16, symbols 146, vol_target 0.15, chosen_params 全 cw 0, range.start 2021-03-02）；193707Z（symbols 205, trial_sharpes cw0 1.7035 / cw72 1.8261）；config/alpha_registry.yaml:128-140 | P2 | 否 | KILL-Q2 的「~0.4」标 UNVERIFIED；Phase A ② 增加「在当前构造跑一次 16 点网格并记账」作为 `oos_is_full_sample_tail` 标注的量化依据，而不是引用 040252Z（与 KILL-R3 的先决计算合并为同一动作）。 |
| KILL-R23 | EP（K-04） | E-10 / C-4 / §4.2 Ⅲ「2020-03 与 2021-05 不在样本内」 | 2021-05 在样本内：193707Z range.start 2021-01-31（BTCUSDT 1h 自 2021-01-01，成员表自 2021-01-31），首个决策约 2021-03-02；E-09 的全样本 Sharpe 1.83 / MDD −22.1% 与 193707Z 一致，说明 scratchpad 回测用同一区间。2021-05-19 崩盘在全样本回测之内却不在压力窗口表里；山寨币 05-10..12 处于历史新高，周尺度 tsmom 在 05-19 大概率做多山寨（方向 **UNVERIFIED**），C-4「崩盘期凸性、8 窗口 6 正」缺了最关键的一个崩盘。 | 193707Z range.start 2021-01-31 01:00；040252Z range.start 2021-03-02；`.starquant/data/klines/BTCUSDT/1h.parquet` 首根 2021-01-01；membership.parquet 首行 2021-01-31 | P2 | 是 | E-10 补 2021-05-10→05-23 窗口（书 vs 等权多头）；C-4 在补完前降 PARTIAL；若该窗口为大额亏损，§4.2 Ⅲ「失效 regime 已回放、结论明确」重写为「急反转 + 山寨新高后的崩盘」两类。 |
| KILL-R24 | EP（K-05） | E-11 / §7.3(a) 逐仓分析 / §4.2 Ⅲ「最长回撤 111 天」 | 回撤分段列表内部不自洽：五段里两段深度同为 −22.1%（2022-01→04 与 2023-03→06）、两段同为 −15.8%（2024-07→09 与 2021-09→11），精确到 0.1% 的两次重合更像分段提取 bug（例如把运行中的全局最大回撤当成分段深度）。193707Z 只报告一个 max_drawdown −0.2219，scratchpad 输出不在仓库，无法交叉核对。 | 报告 E-11 原文；193707Z full_sample.max_drawdown −0.2219 与 walk_forward.oos_max_drawdown −0.2219 相同；仓库内无该回测输出 → **UNVERIFIED** | P2 | 否 | 把 scratchpad 权益曲线存入 reports/research 并重新提取分段（按新高之间的谷底），或删除 E-11 分段表；§7.3(a) 改用 193707Z 单一 MDD 与单币尾部数支撑。 |
| KILL-R25 | EP（K-06）、DS（DS-6） | KILL-Q3 / F2 修复「解 Φ(x)^N = 1−α，只用现有字段」/ E-14 / DL-Q2 测试 / M-Q04 / §7.1.4 第 6 条 | 数字复现无误（43.5%、1.43、p≈0.0027）且 43.5% 对试验相关性稳健，但修法细节欠定且会打破现有语义：(a) 「1.43」与 DL-Q2「93 个纯噪声通过率 ≤ 5%」假设 93 次独立，ledger 85 行里 24 行重复、大量近似重复配置，N_eff ≪ 93；N_eff≈10 时阈值 ≈ 1.13 与现行几乎相同；取 N=93 会以与证据无关的理由把「下一个弱候选」全部挡在门外；DL-Q2 的独立噪声仿真按构造必过。(b) `test_selection_gate.py:28` 断言 `thresholds[0] == 0.0`（单试验不算选择），而 Φ(x)^1 = 0.95 给 1.645σ ≈ 0.72 年化，与 docstring「penalises exactly the cross-round family selection and nothing else」矛盾；报告没说 N 取试验数还是 N−1、N=1 是否保留 0 阈值；`expected_max_sharpe` 同时供 DSR 使用，不能整体替换。 | multiple_testing.py:46-60,88-98,182-210；verdict.py:61-66；193707Z oos_selection.variance / n_trials / ledger.duplicate_rows 24 / ledger_rows 85；tests/alpha/test_selection_gate.py:23-30 | P2 | 否 | 保留分位数修法，只改 `oos_selection_threshold` 不动 `expected_max_sharpe`；N 用 ledger 收益矩阵相关结构估 N_eff（CSCV 已有 T×N 矩阵），或按 D-020 精神把 `p_family` 与 N_eff 一起输出而不设硬门；预登记公式细节（N 或 N−1、N=1 处理、α），同步改写该测试并保留「单试验不算选择」或明确放弃；DL-Q2 验收改为「相关噪声（块自举同一面板）下通过率 ≤ 5% 且 tsmom PASS」。 |
| KILL-R26 | EP（K-07）、PM（K7） | §6.1 评分矩阵 / §0 答案①「加权总分 5.25，位于 LEAN 6.62…之后、hummingbot 5.09 之前」「不是玩具」的依据 / E-25、E-26 / G2 PARTIAL | 算术可复现（13 行加权和全部对到 0.01），但结论不受支持：Qlib、vnpy 标「未核」却给到小数点后两位；每格无证据条目，全部 E4/E5；排序对作者自选权重敏感——把 0.05 从 validation（StarQuant最高分维度）移到 execution（最低分），StarQuant 5.05 落到 vnpy 5.24 之后；等权下StarQuant 5.20 vs hummingbot 5.70。同一份报告一边给验证维度打 8/10（全表最高），一边判定该管线「纯噪声通过率 43.5%」「OOS 九成是样本内」「ledger 对三轮扫描失明」。「玩具」问题该用硬数字回答：当前构造 38 根干净 bar、归因 −10.4 USDT——尚无任何盈利证据（见 KILL-R7）。 | 按报告权重重算；替代权重 [validation 0.10, execution 0.17] 排序：Lean 6.82, nautilus 6.74, freqtrade 6.31, Qlib 5.86, hummingbot 5.44, vnpy 5.24, starquant 5.05；附录 A 自述 Qlib/vnpy 未抓取；报告 §4.1 F1/F2/F6 | P2 | 否 | 总分去掉两位小数、以「作者判断（E4/E5）」呈现，或为StarQuant与前四名各补每格一条可引用证据；Decision Memo ① 名次改为区间，第一句改为硬数字，联赛表降为附录参考；验证维度下调至 ≤ 6 或标注「修 F1/F2/F6 后可达 8」。 |
| KILL-R27 | PM（K8） | §9 Phase A 停止条件「若 tsmom 在修正总体下 FAIL → 停书复审」 | 停止条件形式上不成立、触发时动作错误：基础 tsmom 分数逐币计算（tsmom.py:170-178）无横截面算子，总体修正只可能让 **crowding 臂** 失败，而 crowding-off 的 tsmom 已独立 PASS（145321Z，OOS 1.66）。正确动作是回到 crowding 0（KILL-R1 的回退），不是停书——停书直接摧毁「持续 demo 证据」。触发概率 **UNVERIFIED**。 | starquant_alpha/signals/tsmom.py:170-191；config/alpha_registry.yaml:120-144；报告 §9 Phase A 停止条件 | P2 | 否 | 停止条件改为「若 crowding 臂在 eligible 总体上不再被选中 → 维持/回到 crowding 0，不停书」；只有 FWER 门下基础 tsmom FAIL 才复审书（与 KILL-R3 合读：先算清 FWER 门作用在哪个 OOS 数）。 |
| KILL-R28 | CA（CA-08） | §7.1.2「缺节点、数据在库」的 MarkGap 与 Funding 叶 / §7.1.3 方案 A「纯 numpy，~600 行」 | 「~600 行纯 numpy」漏算新叶节点的连锁义务：Panel（panel.py:98-108）无 mark_price 字段，库里唯一 mark_price 在资金费归档且只有 8h 结算粒度，1h 的 MarkGap 需 markPriceKlines 摄入（Phase B）+ Panel 字段 + from_frames + 实盘取数 + M-011 平价 + manifest——每读一个新列就重新制造一次「研究面板 ⊃ 实盘面板」等价义务（KILL-027/KILL-Q1 的形状）。Funding 叶重新表达的是已被否决的 carry 假设（tsmom.py 边缘声明：rank 模式 carry 五年毛 −6%；§2.1 Pre-2 五个被否决者）。Trades/taker_buy_base 已在 Panel，Abs/Moment/Semi/Beta 只读 close——这些才便宜。 | starquant_alpha/panel.py:98-108,147-150；starquant_data/store.py:11；binance_public.py:60-65；mining/expr.py（12 节点 538 行 ≈ 45 行/节点）；tests/alpha/test_mining.py | P2 | 否 | Phase A 节点限于 Panel 现有列（Abs、Moment、Semi、Beta/Residual、Trades）；MarkGap 移到 Phase B 与 markPriceKlines 摄入同提交；Funding 叶必须预登记「与已否决 carry 有何不同」否则不进枚举（注意 KILL-R10：be963ad 已实现 Funding 叶，两者须由操作者裁决）。 |
| KILL-R29 | CA（CA-09） | §7.4 P0「熔断 TRIPPED 持久标记 + 进程级退避 + startup 失败告警」/ L1-03 | 「能删却选择加」的典型：plist `KeepAlive.SuccessfulExit=false` 且 run_live.sh:24 已写明「Exit code 0 (clean stop) is not relaunched」。熔断跳闸后以退出码 0 退出（一行）就消除了 60 秒热循环，不需要新的持久 TRIPPED 状态、退避计数器或对它们的测试；state.py 已有 21 个字段，`consecutive_errors` 持久化本身就是 L1-03 的病因。 | deploy/com.starquant.live.plist:24-30；deploy/run_live.sh:24-25；starquant_live/state.py:18-42（:37） | P2 | 否 | L1-03 修法改为：跳闸 → 告警 → `sys.exit(0)`；删除 TRIPPED 标记与退避交付项；`consecutive_errors` 改为进程内不持久化。净状态 −1 而不是 +2。（与 KILL-R20(d) 合读：exit 0 后需操作者 reload，告警须到位。） |

### C.3 被攻击而站住的报告结论

| 报告结论 | 尝试推翻的角色 | 站住的理由（角色原话摘要） |
|---|---|---|
| P1-01 / KILL-Q1 机制：`apply_crowding_modifier` 在 `score.columns` 全体排名（tsmom.py:185-191）、flow 全列去均值（flow.py:87-88）、`eligible` 在 compute 之后才作用（model.py:121-130）、研究符号集是时点并集（research_cmd.py:135-154，205 币）、实盘只传 managed symbols；现有等价测试同喂 6 币合成面板、membership=None，结构上抓不到 | PM、URA、EP、CA、DS、RK | 六个角色全部确认；RK 试图证明它被夸大，结果相反（参照总体每天在变）；PM 试图论证修法无法同口径实现，失败。只是对 tsmom 目前是潜在而非在跑（KILL-R1），修法契约须按 KILL-R5 重写 |
| KILL-Q1 修法方向（显式参照总体契约 + 重跑两臂 + 指针）正确；研究侧裁面板（research_cmd.py 一处）不改 SignalSpec 签名、不波及 7 个信号与 mining 桥 | PM、EP、CA | 契约可写、等价测试可写；CA 指出报告给了两个选项未指定，应指定裁面板路径（DS-2 则指出裁面板会带来新的 rolling 漂移，见 KILL-R5） |
| F1 机制：walk_forward.py:134-154 `chosen = best_key or keys[0]`，grid 1 时无 fold 内选择，OOS = 序列尾段；193707Z oos_bars 45,024 / 49,024 = 91.84%；052215Z/131421Z/145321Z 均为 grid 1；registry:82 只部分披露；`--holdout-months` 能力确实存在 | PM、EP、URA | 数字与代码逐项复现；作为「标注类」判定正确。处方里的 holdout 部分被 KILL-R4 推翻 |
| F2 数字与机制：`oos_selection_threshold` 用 `expected_max_sharpe`（multiple_testing.py:203）即 E[max]，verdict.py:61-66 据此判 FAIL；噪声通过率 0.435、5% FWER 阈值 1.43、tsmom p ≈ 0.0027；43.5% 对试验相关性稳健；原地替换净复杂度为零；不会打破 registry/启动门（`decide()` 未被重算，WEAK_PASS 允许上线） | PM、EP、CA、DS | 全部反算到位；CA 试图证明它引入新状态，失败。修法细节欠定见 KILL-R25 |
| L1-01 / KILL-Q4 事实：deploy/run_live.sh:25 无条件 `--immediate`，engine.py:211-217 立即跑上一根已收盘 bar；n 87 / 中位 21.6 分钟 / 72.4% > 60 s / 最长 59.6 分钟；main 同样未修；去掉/条件化 `--immediate` 不会打破任何测试（`immediate=` 只在 live_cmd.py:157）；DL-Q3 仪表部分便宜（`late_seconds` 可从 `bar_open_ms` 与 `at` 派生） | URA、EP、DS、CA | 数字三方独立复现。归因与修法被 KILL-R6 推翻 |
| L1-02 降为中危：订单 id 按 (tag, symbol, bar) 派生、下单前 query（rebalancer.py:59；execution.py:40-42），串行重放被挡；trades.jsonl 未见同 bar 同币重复成交 | EP、DS、RK | 三方确认；RK 补充它对不同目录/不同 universe 的第二进程无效（KILL-R20） |
| L1-03 对熔断与 launchd 的描述：engine.py:259-263 达到 max_consecutive_errors 即 raise，KeepAlive + ThrottleInterval 60，consecutive_errors 持久化且启动不清零 | RK、DS | 与 plist、engine.guarded_cycle 一致；state.json 当前 restarts=12、consecutive_errors=0。修法被 KILL-R29 简化 |
| L1-06「flatten 不是停机」：engine.py:418-436 不碰 state、不 engage kill switch；live_cmd.py:314-344 独立引擎 | URA、RK | 成立，且是 KILL-R2 的根 |
| L1-07 kill switch 相对路径：config.py:80 默认 `.starquant/live/KILL_SWITCH`，launchd 有 WorkingDirectory 所以循环稳定，别处运行 CLI 不稳定 | URA | 成立 |
| L1-09 / E-31：reconciler.py:97-107 撤销账户全部未完成订单、不按 tag 过滤；原生条件单不能在修这之前挂 | URA、EP、RK | 三方确认 |
| E-07 全部字段与 193707Z json 逐项一致；E-09 全样本数字（Sharpe 1.83、MDD −22.1%、换手 ≈385）与 193707Z 一致 | EP | 逐项核对 |
| E-19 滑点：均值 +4.9 bps、中位 +1.2、名义加权 +4.1、极值 −81/+53（n 88） | EP | 与报告 +5.0/+1.3/+4.3 一致 |
| E-15 ledger 签名（ledger.py:46-48）、E-16 `_resolve_mined` 仅 correlate 调用（:751）、E-20 无 flock/pidfile、E-32 INCOME_TYPES 仅三种 | EP | 全部核实 |
| E-17 幽灵 bar 量级：FTTUSDT 零量 ≈600 h、LUNAUSDT 成员资格超出 K 线 28 天 | EP | 可信 |
| F7 / KILL-Q8 机制：`declared_trials` 只在 mine 累计并要求人工抄 `--prior-trials`（search.py:78, research_cmd.py:1720-1746）；validate 对 `mined_*` 抛 KeyError；修法本体一行（`_resolve_mined(strategy)`） | URA、CA、DS | 描述准确、修法便宜；mining_ledger 部分被 KILL-R16 砍掉 |
| Pre-1 / Pre-2 REFUTED 与 P17 PIVOT 维持：挖掘器存在、225 候选阴性、瓶颈在可表达空间与数据宽度；LLM 提案者破坏可交换抽样的论证成立（RESEARCH_LOG:1377-1430）；RL 不做（需 torch，与 ALLOWED_THIRD_PARTY 一致） | PM、CA | 成立；E-05 需补注 be963ad 的 funding/0.15 说明（KILL-R10） |
| Phase A ⑦「在 0.30 口径重跑 225」有理由 | PM | PM 试图以「vol_target 是标量、重跑无信息」推翻，P17 §四 四臂表（1.0780 → 1.1207，355 个 capped bar 说明上限在 0.30 处 binding）证明重跑有理由 |
| D-037 自适应杠杆 KILL 维持、仅加 notionalCap 校验；逐仓分析（5x 逐仓 20% 不利即强平 vs 常规持仓穿越 20% 回撤） | PM、CA | 不新增状态，只加启动断言 |
| 原生条件单作为 alpha 否、看门狗先于原生单；单机单用户的失效场景描述正确 | PM | 顺序判断成立，只是应提前为「告警级」并放在 demo 范围内（KILL-R13） |
| 六个 Expr 节点在 starquant_alpha 内、只依赖 numpy/pandas、测试落 tests/alpha；读 Panel 现有列的节点边际 ≈ 45 行/节点，「~600 行」对这一子集合理 | CA | 成立；MarkGap/Funding 子集被 KILL-R28 拆出 |
| `--immediate` 条件化 + 单实例锁「③④ 共 < 100 行」（不计测试）；flock + pid 属 stdlib、不进架构规则 | CA | 成本核算成立；锁的范围与实现被 KILL-R20 重写 |
| 「先修尺子再扩空间」的顺序约束 | CA、PM | 减少喂给验证门的无效候选数与 ledger 行数增长 |
| §4.2 Ⅴ 运维清单：check 作业与循环同机同用户，每小时 status/verify/report --check 并对失败发 webhook；launchctl list 三个作业在载 | URA | 清单准确（env.sh 部分见 KILL-R19） |
| E-33 / §7.4「合并 D-040/D-041」工作量 S：main 只领先 2 个提交（11 文件 +731 −60） | URA | 估计合理；但 EP 指出漏 304e549、CA 指出 +199 非 alpha 未入账（KILL-R10、R12） |
| hedge-mode 断言存在（engine.py:172-174，venue.py:101-103），清单不列它是对的 | RK | RK 想加「position mode」为缺项，未成立 |
| kill switch 的 reduce-only 直通对当前 MARKET-only 路径正确（guard.py:43-49） | RK | 只在 algoOrder 上失效（KILL-R15） |
| 现有数据（K 线 + 资金费）无发布延迟型前视：`align_funding_to_bars` 把结算记入包含它的 bar（panel.py:55-66），实盘取已结算行，`lastFundingRate` 读取但未消费（DATA-04 已披露）；D-023 启动门（engine.py:132-138）与 KILL-027 形状一致 | RK | 未能构造绕过配置；前视风险只在尚未接入的 metrics（KILL-R21） |
| main 分支没有提前修掉任何 Phase A 项 | PM、URA、EP、DS | 四方独立核对（详见 C.5） |
| Final Decision 的「demo 继续」与「真实资金 HOLD」 | URA、EP、CA、RK（PM、DS 亦未反对这两点） | 没有任何发现要求停 demo 或解除 HOLD |

### C.4 六个角色对 Final Decision 的裁决与调和

| 角色 | 裁决 | 一句话理由 |
|---|---|---|
| Skeptical PM | **should_be_pivot** | 决策上限没问题，但计划的第一动作（头号 P0 描述的是没在跑的信号，最便宜的关闭动作被 §11 禁止）、范围（mainnet 前提项压低 alpha 占比）与 demo 目标定义（盈利证据一年内不可裁决）必须转向 |
| User Reality Auditor | agree_weak_go | Weak GO 经得起攻击；但按单操作者可执行性，路线图有五处不能按写的那样执行（holdout 必选、周上限无工具、看门狗不可交付、合并列车缺失、证据窗口与 12 周叠不起来）；G7 应从 PARTIAL 降 FAIL 直到 DL-Q8 重写、Phase A 加合并列车与 `--immediate` 第 0 步、§11 写出真实资金最早日期 |
| Evidence Prosecutor | agree_weak_go | 四条核心发现机制全部成立且 main 未修，三条数字复现到位；被推翻的是两处事实前提（crowding 在跑、2021-05 不在样本）；Phase A 顺序需插入「重启前完成 KILL-Q1 修复 + registry 指纹入周期记录」 |
| Complexity Accountant | agree_weak_go | 攻不破决定，攻得破账目：六个包顶在 ratchet 上限零提及、alpha 占比未按仪表算、三项可删却选择加的状态、两项撞架构硬规则、看门狗缺远端停机半个设计；建议把 Phase C ④⑥、mining_ledger、随机表达式对照、TRIPPED 标记移到 Won't |
| Delivery Saboteur | **should_be_need_evidence** | Phase A 的预登记成功判据在报告自己的数字下不可达（F1+F2 合并后 FWER 门作用在 1.376 上，阈值 ≈1.42–1.45）；在算出该阈值之前「tsmom 现行结论不倒」未经检验；补一次 scratchpad 计算 + 重写 DL-Q1/Q2/Q3/Q4 契约，再给 Phase A 的 Weak GO |
| Risk & Abuse Red Team | agree_weak_go | 五个攻击面都属真实资金前提或 Phase B/C 设计，不改变 demo 阶段档位；但看门狗须从「S–M 的 P0」改为需重设计的 Kill 条目，KILL-Q7 升 P1 进 Phase A，原生止损按符号分层重写，§11 追加 RK-6 四项断言；若作者不接受 RK-7 升级与看门狗重设计，则 G6 不应从 PARTIAL 变 PASS |

**调和。** 六个角色中四个维持 Weak GO，一个要求 PIVOT，一个要求 Need Evidence；六个角色对「demo 继续」与「真实资金 HOLD」两个上限没有任何反证，所以 **Weak GO 的两个上限成立，但报告写下的 Weak GO 所授权的具体动作——「按 §9 执行 Phase A」——目前不能原样授权**，因为三条 P0 分别打在 Phase A 的第一动作、Phase A 的验收条件与 §7.4 的头号 P0 上。若 KILL-R1 确认（PM 与 EP 已各自独立确认事实链，仅严重度分歧）：§8 必须把 KILL-Q1 拆成「tsmom（潜伏，重启起生效）」与「flow 去均值（当下在跑）」两半，并新增一条 OPEN 的「registry ≠ 运行进程、构造指纹看不见信号参数」的 KILL-027 形状条目；§9 Phase A 的第一动作改为「任何重启之前使 registry、循环、证据三者一致」（回退 3ac8d49 或重启前完成修复并记录 registry 指纹），Phase A ① 降为可选研究；§11 中「不允许在 KILL-Q1 关闭前改 registry 的 tsmom 参数」这一条必须删除或改写为允许回退，G4 的 Cost of Delay 改「高」。若 KILL-R2 确认（URA、RK、CA 三方独立从不同路径到达同一结论，仅币安 key 权限粒度一项 UNVERIFIED）：§7.4 P0 第 3 项与 DL-Q8 按 C.2 的七点重写，§0 回答⑤改为「先做远端 kill switch + 心跳外推」，§8 的 KILL-Q13 与 C-6 不能再引用看门狗作为缓解，G7 按 URA 降为 FAIL，§11 的真实资金解除条件追加 KILL-R19 的四项断言并写出最早日期（URA：约第 16 周）。若 KILL-R3 确认（需先做 KILL-R3/R22 共同要求的那一次 scratchpad 计算，这正是 DS 的 Need Evidence）：§9 Phase A 的成功判据与停止条件必须改写为指明 FWER 门作用在哪一个 OOS 数、成功是 PASS 还是 WEAK_PASS，§11 的升级条件与 §0「tsmom 现行结论不倒」在计算结果出来之前标为未经检验；若诚实答案是 WEAK_PASS 或 FAIL，则 §8 KILL-Q3 的状态与 C-2 的证据块一并重写。此外 KILL-R4、R7、R13 共同要求 §9 与附录 B 明示对 KILL-006 与 mainnet 范围的处置，KILL-R11/R12 要求 §9 的 alpha 占比按 `effort_share` 口径重算并为每条 DL 补 ratchet 记账。综合六方：Weak GO 作为档位可以保留，但它必须重新绑定到修订后的 §9，而修订的最小前置是三件事——重启前的 registry/循环一致化、一次网格走前 OOS 对 FWER 阈值的计算、DL-Q8 的重写——在这三件事完成前，PM 的 PIVOT 与 DS 的 Need Evidence 对 Phase A 的授权部分是成立的。

### C.5 报告中已在 main 修复或仓库内已披露/已被否定的陈述（供修正）

**关于 main 分支（四个角色独立核对：PM、URA、EP、DS）**

1. 本轮四条核心发现（KILL-Q1/P1-01、F1、F2、L1-01）以及 L1-02 在 main 上**均未修复**：`git diff db9efd9 main` 只触及 `starquant_cli/live_cmd.py`、`starquant_cli/research_cmd.py`、`starquant_live/config.py`、`starquant_live/reports.py`；tsmom.py / flow.py / model.py / validation/* / deploy/run_live.sh / engine.py / execution.py 无差异。报告这一点站得住，无需改动。
2. 报告写 main 在 bd7cd6e，实际 main 在 **304e549**（多一条 `fix(cli): research overlay dropped the books when --min-history rebuilt the model`，改 research_cmd.py:860-870）；头部「同伴会话通报」与 §7.4「合并 D-040/D-041」应改为 D-040/D-041/304e549 三项。
3. main 的 ratchet CEILING 已比本分支高 +64 live / +18 cli / +117 data = +199 非 alpha 行，且 D-041 带一道新的启动数据集门（`registry_dataset_problems`）；报告把合并记为 'S' 且未入账。

**报告陈述与仓库内已有记录相矛盾（应据仓库修正）**

4. 报告隐含「crowding 修饰器已在实盘跑」——`docs/RUNBOOK.md:46` 仍写「当前 tsmom 仍跑 crowding_window: 0」，cycles.jsonl `funding_history: false`，state.json restarted_at 早于 3ac8d49。仓库文档与实盘状态均与报告前提相反（KILL-R1）。
5. 报告 §7.1.4 第 4 条把 `--holdout-months ≥ 1` 写成「记忆中的决定」——仓库内的裁决是 `docs/RESEARCH_LOG.md:750-760` KILL-006 §二「不启用……刻意不使用」，报告继承的是 :740 的「建议（待操作者确认）」；`starquant_cli/research_cmd.py:374-378` 帮助文本写 `unused by choice, see docs/RESEARCH_LOG.md`（KILL-R4）。
6. 报告 §7.1.4 第 5 条「每周最多一次 validate」作为 KILL-Q8 缓解——`docs/RESEARCH_LOG.md:740` 已自述「每周一次晋级从未实现」（KILL-R8）。
7. 报告 §7.2 / 附录 B「D-012 收窄式重开」——`docs/analysis/2026-09-03-exits-pool-sizing.md:181` 已预登记重开条件为「进入 mainnet 且信号尺度进入日内」，两条都不满足（KILL-R15）。
8. 报告 §4.2 Ⅲ「2020-03 与 2021-05 不在样本内」——仓库内 193707Z json 的 range.start 为 2021-01-31，2021-05 在样本内（KILL-R23）。
9. 报告 P1-01「实盘 15 币」「n=15」——`config/live.demo.yaml:103` `refresh: daily`，`.starquant/data/universe.json` 与 heartbeat 已是 18 币（KILL-R5）。
10. 报告 §7.4「env.sh 600」把 env.sh 写成已存在的优选路径——`~/Library/Application Support/starquant/` 下无 env.sh，实际取密走 run_live.sh:18 对 ~/.zshrc 的 eval（KILL-R19）。
11. 报告 §4.1 L1-02 修法「flock」——Darwin 上无 `flock(1)`（KILL-R20）。
12. 报告 KILL-Q2「headline 高估 ~0.4」引用 040252Z——`config/alpha_registry.yaml:128-140` 注释已写明 0.15 时代报告「不再横向可比」（KILL-R22）。
13. 报告 §7.1.4 保留 NW t 门并新增「随机表达式零假设」——`multiple_testing.py:186-188` docstring 与操作者记忆已写明 NW t ≈ Sharpe×√年不构成第二条件；`noise_null`（multiple_testing.py:93,268）已存在且 E-07 已引用（KILL-R17）。
14. 报告 §7.4 P0「熔断 TRIPPED 持久标记 + 退避」——`deploy/run_live.sh:24` 已注明「Exit code 0 (clean stop) is not relaunched」，plist `KeepAlive.SuccessfulExit=false`，退出码 0 即可消除热循环（KILL-R29）。
15. 报告 §7.2 看门狗「心跳陈旧」检测作为新能力——`starquant_cli/live_cmd.py:176-178` 的 `live status --check` 与 run_check.sh 已检测心跳陈旧，增量只是「动作 + 异机」（KILL-R2）。
16. 报告 E-05「225 候选全阴性」未注明条件——worktree 分支 `feat/mining-funding-node`（be963ad）提交说明已指出 P14 是在读不到 funding、vol_target 0.15 下测的，且 Funding 叶节点与 42 条 carry 族已在该分支实现（KILL-R10）。
17. 报告 §4.1 F1 说 registry 未披露——EP 核对 `config/alpha_registry.yaml:82` 为**部分披露**（应改为「部分披露」而非「未披露」）。
18. 报告 §4.2 对 `lastFundingRate` 的前视担忧——DATA-04 已在仓库披露该字段读取但未消费（RK upheld，报告若在此处标 ※ 则无需改）。
19. 报告 E-11 回撤分段表——仓库内无对应 scratchpad 输出，193707Z 只有单一 MDD −0.2219；两对精确重合的深度无法核对，应标 UNVERIFIED 或删除（KILL-R24）。

**角色标为 UNVERIFIED、报告不得写成事实的项**

- 币安期货 API key 无 reduce-only 作用域（URA、RK、CA 三方均标 E4）。
- `priceProtect` 触发时的取消语义（RK）。
- `/futures/data/*` REST 的 30 天窗口与发布时延（RK）；住宅网络下 daily 归档吞吐（URA）。
- KILL-R3 的 FWER 阈值 1.42–1.45 为 E2 推算，须 scratchpad 计算（DS）。
- 报告 E-12 的「1.8× 触发率、49.6% 重合」为 E2，无人复现（EP）。
- 2021-05-19 窗口的书方向（EP）；KILL-R27 停止条件的触发概率（PM）；mined 哈希在新增节点后是否稳定（DS）。

## 附录 D · mainnet pre-flight backlog（不在 12 周路线图内；只在操作者显式重开 mainnet 时启动）**[C 新增]**

| 优先 | 项 | 来源 |
| --- | --- | --- |
| P0 | 冲击成本模型（平方根法则起步，由前审参与率表与 E-19 校准）+ `vol_target` 重推 + 10 万 USDT 容量门槛写进 config | KILL-A / Q12 |
| P0 | 保证金模式断言：每个 managed 符号 `marginType == CROSSED`（或显式设置）且 `multiAssetsMargin` 与验证口径一致 | KILL-R19 |
| P0 | 全新 `state_dir`：启动拒绝 `started_at` 早于武装时刻或已有 `equity_hwm` 的 state（demo HWM 10,924 对 5k 真实账户意味着首周期 −54% 回撤 → 阶梯误报） | KILL-R19 |
| P0 | 账户空仓空挂单断言（否则拒绝启动，而不是撤单 / 平仓） | KILL-R19 / L1-09 |
| P0 | 告警 webhook 已配置并完成一次端到端演练；第二通道 | KILL-R19 / L1-11 |
| P0 | 密钥：先建 `~/Library/Application Support/starquant/env.sh`（600）并移除 `run_live.sh:18` 对 `~/.zshrc` 的 eval 回退；分权 API key（只读 / 交易，无提现）；IP 白名单 | KILL-R19 |
| P0 | `--armed` + `max_equity_usdt` 双重确认；host 白名单改码 | 审计 |
| P1 | 原生灾难止损（若远端停机演练暴露"循环存活但无法平仓"情形）：先改重开条件决策、`guard.py` 加 algoOrder 路径、距离按符号分层 | KILL-Q10 |
| P1 | 被动执行 / TWAP（demo 无法测量，需真实小额资金） | KILL-Q14 |
| P2 | 名义档位 `notionalCap` 校验；请求权重预算；exchangeInfo 逐日快照 | P15 §3 / 审计 |
