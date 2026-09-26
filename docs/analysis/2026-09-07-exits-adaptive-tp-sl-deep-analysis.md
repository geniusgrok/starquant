# 深度分析：止盈止损是否应随市场状态自适应（2026-09-07）

> 深度分析 V3.7 · 等级 L · 只分析不执行（操作者原话："先进行分析，给出一个方案，我来决定是否执行"）。
>
> **Reading Check**：本次理解为「评估StarQuant实盘 exit overlay（止盈 / 止损 / 移动止损）是否应改为按市场状态自适应，以在震荡行情里少回吐浮盈、少亏损；交付对象是单一操作者；交付物是一份可决策的方案，不改任何配置」。最高风险预设为 Pre-EX1（P0）「300→200 U 的回吐说明 exit overlay 失职，改退出规则能把它留住」；若该预设不成立（回吐在 `vol_target 0.30` 的设计噪声之内，且历史上任何更紧的退出都毁值），结论从「改止盈止损」变为「不动 exit overlay；若要减少回吐，杠杆在风险预算或信号退出侧，且必须先写后跑」。
>
> **Interaction**：Yellow（完整度 🟢🟢🟢🟡🟢🟢，成功标准只有方向"增加盈利、减少亏损"没有指标） ｜ 等级：**L**，命中：exit overlay 在实盘目标权重主链路上（alpha overlay + live 适配 + CLI 证据 + 配置，≥3 模块）；触及资金链路（demo，但规则将带进真实资金）；AI/策略维度为"自主决策 + 生产影响"；两个维度落在 M/L 之间 → 向上取 L；本档不覆盖：无默认省略，但按操作者要求 Phase 9–10 只出契约不执行 ｜ 当前决策上限：**PIVOT**（H2：P0 Claim C-EX01 REFUTED；实验分支另受 H5：相对价值 Unproven → 只能以受控实验进入。**[C 修订]** 初稿此处误引 H3，H3 只对 P0 UNKNOWN 生效，本文的 UNKNOWN 都是 P1） ｜ 输出状态：**DONE_WITH_CONCERNS**（两个开放问题交操作者，见 §12） ｜ 外部动作授权：无（本次只做了只读证据收集：读仓库、读 `.starquant/live`、读 mainnet 公开 K 线、以操作者的 demo key 只读 `account`/`positionRisk`；没有下单、没有改配置、没有写 trials ledger）。
>
> ID 命名空间 `EX`（E-EX / C-EX / A-EX / D-EX / M-EX / RISK-EX / KILL-EX / DL-EX），避免与仓库已有的 E-068 / C-026 / D-043 / M-019 冲突。Constitution：仓库无 `deep-analysis-constitution.md`，战略与硬约束从 `config/live.demo.yaml` 注释、`docs/RESEARCH_LOG.md` 与既有分析中读取。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **PIVOT**（命中 H2；O-EX2 分支另受 H5）。**[C 修订]** 「把止盈止损改成随行情自适应」作为对本次回吐的诊断不成立；作为诉求成立但**尚未被测过的部分比作者最初写的多**：止损 / 移动止损收紧已被证据否定，**止盈 <6σ 从未测过**。现在**不改任何配置**；第一个实验是最便宜的那个——固定止盈 {3, 4}σ 扩格。 |
| 一句话问题 | 操作者看到 18 个持仓的浮盈从 ≈ +329 U 回到 +264 U（E-EX02b），exit overlay 一次没触发，于是认为止盈止损"写死了、不适用"。 |
| 对观察的解释（D-EX00 选定框定 F3） | 回吐 65 U = 0.6% 权益 = **0.4 个设计日 σ**。这本书按 `vol_target 0.30` 设计，权益每天的正常摆动是 ±172 U（实测早期 ±95 U）。一天内 100 U 的来回不是任何机制失效的信号。 |
| 为什么止盈止损没触发 | 按构造不会：阈值是 6 倍**入场时日波动**，换成价格是 BTC ±14.3%、BNB ±12.3%、AKE +154%；离最近的触发还有 2.6σ 以上（止盈侧最近 LINK 3.36/6，止损侧最近 UNI −0.51/−6）。回测里整本书平均 **每周 1.9 次**退出，实盘 60 bar 里 0 次的概率约 51%。 |
| 为什么不能"收紧止损"或"移动止损" | 5.6 年、两个 universe、预登记网格三次重分析（E-EX07）：止损 2.5σ / 4σ 的任何组合不通过 D-017；**移动止损 4σ 的任何组合都毁值**（OOS Sharpe −0.15～−0.22，MDD 恶化 0.9–2.8pp）。机制：本系统自测 1–24h 是反转、周级是动量（E-EX09）；任何在 1 个日 σ 量级触发的退出都落在反转尺度，是在替对手方止损。**[C 修订] 这句话只覆盖止损与移动止损：网格里止盈只有 {0, 6}，更紧的止盈没有证据，先验（趋势系统的利润在右尾，Kaufman）为负但必须测。** |
| 这本书真正的退出机制 | 信号翻转（`conviction_mode: sign`，中位 **17 次/币·年**），不是 exit overlay。 exit overlay 是"保费≈0、5.6 年没赔付过"的保险（P11 原话）。 |
| 对诉求的工作框定（F2） | 如果退出要"随市场状态自适应"，候选的状态变量有三个：**当前波动**（阈值用当前 σ 而非入场 σ，O-EX7）、**周级信号自身的衰减**（O-EX1）、**价格效率/regime**（O-EX2）。**[C 修订]** 三者都未测；作者最初给 O-EX1 的"中"先验被审查降为低–中（E-EX10 说幅度不携带收益信息，C-EX03 → UNKNOWN）。 |
| 推荐方案 D-EX01（**[C 修订]** 顺序按审查重排） | ① O-EX0：保持 6/6 不动，日报加"设计日 σ 与今日回吐/σ"一行；② 实装 M-005 反事实为**监测**（不是裁决者：≈2 次/周，30 天 n≈8，K-EX12）；③ **第一个实验 = 一次 `research overlay` 跑三个新候选**：固定止盈 3σ、4σ（O-EX1b，回答操作者的字面问题，兼作 regime 实验的对照）+ 当前波动单位 6/6（O-EX7，最便宜的"随波动自适应"），双 universe D-017，tsmom + flow 各 +6 行；④ 若固定 TP3 不通过而操作者仍要测"按行情切档"→ O-EX2 的 2×2（基线 / 固定 / regime / 镜像）；⑤ O-EX1 信号侧滞回在一项描述统计之后再决定是否花 validate 名额；⑥ 任何采纳都要：在 0.30 构造上通过预登记规则、操作者批准、M-010 满 30 天连续构造（K-EX14 建议规则）、重启并记构造变更。 |
| Won't | 更紧的止损与移动止损（已被证据否定）；滚动入场锚；组合层 regime 敞口标量；部分止盈；交易所原生条件单（已由 D-012 / KILL-R14 / KILL-R15 裁决）；用 3 天实盘重放（E-EX14）调参；在批准前跑任何计费实验。 |
| 最大价值 / 最大风险 | 价值：避免用一次盘整的观感去动一个经三轮验证"无害"的层，保住唯一的样本外记录。风险：RISK-EX06——E-EX14 的重放里 TP2/TP3 在这 3 天"多赚 20 U"，很诱人；它是 1–3 个事件，E5。 |
| Strategic Fit / Relative Value / Economic | High（O-EX1 是 alpha 侧工作，符合 90% alpha 投入）/ Adequate（No-Build 已拿到全部"保险"价值；实验的相对价值 Unproven，故只以实验形式进入）/ N/A（单人项目） |
| 被接受的损失与补偿 | 操作者"马上换一套自适应止盈止损"的即时诉求被延后为实验；补偿 = 日报噪声尺度行 + M-005 实装 + 两个实验的明确规则与命令。 |
| 开放项（全部是操作者的决定，见 §12） | **【结项】全部已回答，见 §12 与下方结项更新。** Q1 exit overlay 的角色：主动 P&L 机制还是灾难后备；Q2 想要的权益日波动是多少 U（决定的是 `vol_target`，不是 exit overlay）；Q3 是否花 tsmom + flow 各 6 个 ledger 名额跑第一个实验；Q4 E-EX14 的 7 个配置补记 ledger 还是书面豁免（K-EX07）；Q5 KILL-R12 ceiling（O-EX0 + M-005 ≈70 行 live）；Q6 是否接受"M-010 满 30 天前不采纳"的规则。~~GAP-EX01：M-EX01 基线需一次当前构造回测。~~ **已关闭，见 §4.4 M-EX01 与 `scratchpad/m_ex01_retention.py`。** |
| G0–G7 一行 | G0 PASS · G1 PASS · G2 PASS（C-EX02a-TP / 02b / 02c / 03 UNKNOWN → **【结项】全部 REFUTED**，见 §3.2）· G3 PASS · G4 PASS · G5 PASS · ~~**G6 PARTIAL**（P0 0 / P1 9，见 §8）~~ **【结项】G6 PASS**（P22/P22b/P23 关闭了需新证据的 5 条 P1；K-EX08 是唯一仍 OPEN 的一条，性质是 N/A-until-adoption，见 §8.2）· G7 PASS（契约齐，Delivery Gate 等操作者批准） |

> **【结项更新，2026-09-07，P22 + P22b + P23 之后】** 本文 §7.3/§11.2 预登记的四个假设已全部检验完毕并裁决：C-EX02a-TP（固定止盈 3σ/4σ）、C-EX02c（当前波动单位）——`docs/RESEARCH_LOG.md` "P22 裁决"节（2026-09-07，`d0ab2ae`/`2d905ba`）；C-EX02b（行情效率比切档止盈）——"P22b 裁决"节（`6a5688a`）；C-EX03（信号衰减退出）——"P23 裁决"节（commit `2f22ff9`）。**四个全部 REFUTED**。`config/live.demo.yaml` 的 `exits` 块一个字符未改，止损 6σ / 止盈 6σ / entry 单位仍是线上设置（新增的 `unit_mode` 键默认值使行为逐位不变，见 RESEARCH_LOG"记录：`unit_mode` 改了构造指纹，行为一个字节没变"一节）。分支实际交付的是：两个日报观测段（DL-EX0 噪声尺度、DL-EX0b M-005 反事实——降级为**监测**而非裁决者，K-EX12）；三条操作者裁定写入仓库（K-EX07 的短窗描述性重放豁免、K-EX14 的 30 天最短干净窗口规则、KILL-R12 ceiling 的抬升，均见 §8.2 与 §12）；M-EX01 基线首次测得（见 §4.4，GAP-EX01 关闭）。G6 由 PARTIAL 转 PASS（下表与 §8.2）。**Final Decision 一词不变，仍是 PIVOT**：诊断（"exit overlay 失职"）依旧不成立，但对操作者"是否要让止盈止损随行情自适应"这个诉求，现在的答案不再是"没测过"，而是四次独立预登记实验都说"不"。

---

## 1. Gate Summary

| Gate | 状态 | 依据 | 未通过项 / 备注 | 决策上限 |
| --- | --- | --- | --- | --- |
| G0 Interaction / Kill | PASS | 用户、场景、损失、约束、证据齐；无 FATAL | 成功标准只有方向 → K4 WARNING，在 Phase 3 写出 Success Definition 后解除 | — |
| G1 Problem / Axiom | PASS | 移除操作者原方案（自适应止盈止损）后，诉求"少回吐、多盈利"仍成立；但"exit overlay 失职"的**缺陷**框定不成立 | 区分了症状（回吐）、根因（设计噪声 + 信号持有）、可干预杠杆（信号退出侧 / 风险预算） | — |
| G2 Evidence | PASS | 19 条 E1/E2 证据，P0/P1 Claim 不依赖 E4/E5 | C-EX02a-TP / 02b / 02c / 03 UNKNOWN（止盈 <6σ、regime 切档、当前 σ 单位、信号衰减都从未测过）——**【结项】P22/P22b/P23 之后全部 REFUTED，见 §3.2** | 这些是 P1，不触发 H3；实验分支受 H5 |
| G3 Relative Value | PASS | 比较了 No-Build / 参数 / 信号侧 / 组合层标量 / 降 vol_target / 原生单 | 实验分支的相对价值 Unproven（H5）→ 只能以实验进入 | Weak GO（实验） |
| G4 Strategic / Economic | PASS | 90% alpha 投入；O-EX1 落在 alpha；单人项目经济性 N/A | ledger 名额是真实机会成本（RISK-EX03） | — |
| G5 System | PASS | 工程预检完成：O-EX1 落点 `scores_to_targets`；O-EX2 发现 live 请求窗口 ≤ 1,500 bar 的约束（§6） | — | — |
| G6 Adversarial | ~~**PARTIAL**~~ **【结项】PASS** | 独立子代理：P0 0 / P1 9 / P2 5，全部有关闭路径（§8.2） | K-EX01/02/03/07/12 需新证据才能关闭 → **已关闭**（P22/P22b/P23）；K-EX08 仍 OPEN（N/A-until-adoption，无价格路径候选被采纳） | PIVOT（H2 已定，内容不变） |
| G7 Delivery | PASS（分析交付物） | 四类契约与 Source Trace 齐；实验的 Delivery Gate 以操作者批准为人类确认点 | 不得在批准前运行计费实验；KILL-R12 捆绑记账（K-EX05） | — |

命中硬门禁：**H2**（P0 Claim C-EX01 REFUTED → PIVOT/KILL）、**H5**（实验分支相对价值 Unproven → 上限 Weak GO，只以受控实验进入）。**[C 修订]** 未命中 H3：UNKNOWN 的 C-EX02a-TP / 02b / 02c / 03 都是 P1，H3 只对 P0 生效——作者初稿误引了 H3。未命中 H1（无 OPEN P0）、H4（P0/P1 主要靠 E1）、H7（G6 PARTIAL 非 FAIL）、H8（demo 范围、mainnet out）。

---

## 2. Phase 1 · Reality Check

输入类型：**方案型 + 情绪型**（点名了方案"自适应止盈止损"，触发是刚发生的回吐）。剥离方案后的问题见 §4。

### 2.1 需求四问

| 问题 | 答案 | Evidence | 状态 |
| --- | --- | --- | --- |
| 谁的需求，谁承担损失 | 单一操作者。损失 = 浮盈回吐（≈65 U）+ 信息损失（不知道这算不算异常）+ 手动干预风险 | E-EX02/02b | 已确认 |
| 频率、规模、损失 | 每次盘整期都会出现；量级 0.3–0.9% 权益的浮盈回吐；本次 65 U = 0.6% | E-EX02/05 | 已确认 |
| 现在怎么绕过、代价 | **[C 修订，K-EX10]** 操作者随时具备手动平仓的绕行能力，本次没有使用而是先提问——说明 0.6% 的回吐还不够痛；09-04 的手动全平是"平掉后重启做检验"（RESEARCH_LOG:856），不是对浮盈的干预。绕不过去的是目标层面：没有一个旋钮能让 exit overlay 在盘整里"有用地"触发。若真用绕行，代价是污染唯一的样本外记录（KILL-006） | RESEARCH_LOG:856、KILL-006、E-EX06 | 已确认 |
| 现有方案能否满足 | exit overlay 已存在且"无害不有益"；信号翻转是实际退出机制；所缺的不是一层规则，是**噪声的尺度**和**exit overlay 价值的实盘裁决者**（M-005 未实装） | E-EX07/12/16 | 已确认 |

### 2.2 需求来源与偏差

| 渠道 | 来源 | 样本量 | 已知偏差 | 折减 |
| --- | --- | --- | --- | --- |
| 操作者观察 UI | 09-07 上午一次读数 | n=1、3 天、一次盘整 | 近因；结果偏差（看到峰值才知道"该止盈"）；单例 | 「操作者感知到回吐」E2；推广到「exit overlay 有缺陷」E5 |

### 2.3 需求预设清单

| Pre ID | 提出者默认成立的前提 | P | 若不成立会改变什么 | 处理 |
| --- | --- | --- | --- | --- |
| Pre-EX1 | 回吐是 exit overlay 失职，改规则能把它留住 | **P0** | 方向从"改止盈止损"变为"不动 exit overlay" | 登记为 A-EX01/C-EX01；由 E-EX05/07 直接检验 → 不成立 |
| Pre-EX2 | "震荡行情"是可事前识别的状态，退出规则可据此切档 | P1 | 自适应规则退化为按噪声切档的移动止损 | O-EX2 的镜像控制臂 |
| Pre-EX3 | 止盈止损是"增加盈利、减少亏损"的正确杠杆 | P1 | 杠杆在信号退出侧或风险预算 | C-EX03、O-EX1/O-EX5 |
| Pre-EX4 | 300→200 U 是显著损失 | P1 | 它在设计噪声内，问题变成预期管理 | C-EX04、O-EX0 |

### 2.4 Early Kill / G0

K1 否（有真实用户、场景、可观察损失）；K2 否（核心结论全部 E1）；K3 否（本文强制比较了替代）；**K4 WARNING**（成功不可衡量 → §4.4 先写 Success Definition）；K5 否；**K6 WARNING**（"自适应退出"的价值 < 复杂度是先验，用证据门控 + 最小网格处理）；K7 否；K8 否。**G0 PASS**。

### 2.5 Context Intake

材料已覆盖绕行（KILL-006）、可得数据（`.starquant/live`、 ledger、K 线）、需求来源（操作者本人）、硬约束（demo、50% 回撤预算、D-017、KILL-R12 行数规则、 ledger 计费）。唯一未覆盖的是**决策边界**：操作者对权益日内摆动的容忍度是否与其 09-04 声明的 50% 回撤预算一致——这就是 Q-CRITICAL（§12）。按 3.2 规则 3，本文在该问题未答的情况下继续推进，把它作为决策边界写在结论里。

---

## 3. Phase 2 · Evidence Ledger

### 3.1 证据（全部可复核；来源类型 / 等级 / 位置）

| ID | 类型 / 等级 | 来源 | 摘要 |
| --- | --- | --- | --- |
| E-EX01 | CODE E1 | `starquant_alpha/overlays/exits.py:105-157`、`starquant_live/exits.py:72-97`、`config/live.demo.yaml:121-152` | exit overlay：bar 收盘评估（D-012）；阈值单位 = **入场时**日 EWMA 波动（半衰期 48h，下限 0.5%）；止损 6 / 止盈 6 / 移动止损 0 / 冷却 24 bar；入场锚 = 首次入场价，同向加减仓不重锚（E-047）；实盘方向以交易所仓位为准，重启时用交易所 VWAP |
| E-EX02 | DATA E1 | `.starquant/live/cycles.jsonl`（117 周期，09-03 07:58Z → 09-07 03:00Z）；`reports/daily/2026-09-0{5,6,7}.md` | 退出触发 **0 次**。上次账户重置（09-04 17:21Z，TRANSFER +5000.01）后权益 10,704.6 → 峰值 11,014.5（09-07 00:00Z，+309.9）→ 10,979.1（03:00Z，+274.6，峰值以来 −35.4）；24h 内最大峰值回吐 66.4 U |
| E-EX02b | DATA E1 | demo-fapi `/fapi/v2/account` + `/fapi/v2/positionRisk` 只读（09-07 04:06Z） | 钱包 10,685.25、权益 10,949.08、18 个持仓**未实现盈亏 +264.00 U**（LINK +48.1、TUT +46.4、ZEC +31.4、BNB +29.3；负的只有 UNI −6.7、BTC −0.1）。按峰值权益反推峰值未实现 ≈ +329 U。**操作者的"300 多 → 200 多"就是这个读数：≈ +329 → +264，回吐 ≈ 65 U ≈ 0.6% 权益** |
| E-EX03 | DATA E1 | `state.json` `exit_states` × mainnet 1h 收盘（09-07 03:00Z 闭合 bar） | 距止盈：LINK 3.36σ、ZEC 1.95、BNB 1.81、DOGE 1.35、SUI 1.29；距止损最近 UNI −0.51σ、BTC −0.08；平均 \|距离\| 0.88σ；自极值回撤最大 BNB 2.06σ。6σ 换成价格幅度：BTC 14.3%、BNB 12.3%、ETH 17.7%、SOL 20.1%、AKE 153.9%；**AKE 的 6σ 止损价为负数，不可能触发** |
| E-EX04 | DATA E1 | mainnet 1h 收盘（截至 09-06 16:00Z） | BTC 7d 净 +0.84% / 高低幅 7.76% / 效率比 0.020；ETH −0.85% / 7.66% / 0.016；SOL −0.28% / 9.42% / 0.004；XRP −0.46% / 12.36% / 0.006。30d：BTC +23%、ETH +30%、SOL +44%、XRP +39%。波动 EWMA48 / 90d：BTC 0.87、ETH 0.85、SOL 0.99、XRP 0.90、BNB 1.24。**即：强趋势后的低效率盘整，波动正常偏低**——操作者的"震荡"判断成立 |
| E-EX05 | DATA E1 | `cycles.jsonl` 59 个整点周期（09-04 18:00Z 起） | 实盘小时权益变化 std 19.5 U → 日 σ **95.5 U（0.87%）**；设计值 0.30/√365 = 1.57% = **172 U**。回吐 35–66 U = 0.4–0.7 个实测日 σ、0.2–0.4 个设计日 σ。（30 日实现波动带 [0.26, 0.38] 尚未可判：112 bar，需 240） |
| E-EX06 | DATA E1 | `.starquant/live/attribution.jsonl`（income 归因） | 重置后已实现（含费）**−38.2 U**（tsmom −38.5 / flow +0.3）；09-03 起累计 −17.1（tsmom −19.7 / flow +2.7）；单币最差 1000PEPE −26.8、最好 ZEC +27.4。重置后 62 周期里**目标方向翻转 8 次，全在 1000PEPE / TRUMP**（反复多空，这是真实的"震荡税"，发生在信号层）；15 个多头一次没翻 |
| E-EX07 | EXPERIMENT E1 | `reports/research/overlay-20260904T063333Z`（时点 205 币）/ `063348Z`（静态 15 币）/ `063855Z` / `063901Z`；`docs/RESEARCH_LOG.md:763-852`（P11 / P11-b） | 5.6 年、两个 universe、预登记网格。基线时点 1.7601/−12.21%，静态 1.5212/−13.64%。止盈 6σ：1.7543/−11.64%，1.4332/−12.79%（双通过）；止损 6 + 止盈 6：1.7509/−11.63%，1.4320/−12.79%（双通过，**现行**）；止损 4 + 止盈 6：1.7266/−12.32%，1.3832/−12.77%（两边否）；止损 2.5σ 任何组合全否；**移动止损 4σ 任何组合：时点 1.613–1.699 / −13.0～−15.0%，静态 1.299–1.375 / −14.5～−16.5%，全否，三轮同一结论**。触发频率：时点 TP 544 + SL 18 = 562 次 / 49,735 bar → 整本书 **≈1.9 次/周**；实盘 60 bar 期望 0.68 次，0 次的概率 ≈51%。口径：这批报告的构造是 `vol_target 0.15`；退出触发是价格路径决定的，不随权重缩放改变，判定可延续，数字不可横比；边界项（SL6+TP6 静态 Sharpe 损失 0.0892 vs 上限 0.10）对构造敏感，任何采纳前须在 0.30 上重跑（K-EX03）。**[C 修订] 网格 `stop_loss ∈ {0, 2.5, 4} × trailing_stop ∈ {0, 4} × take_profit ∈ {0, 6}`（`research_cmd.py:80-83`）：止盈只有 0 与 6 两档，6σ 以内的止盈从未测过（K-EX01）；"三轮一致"是同一 5.6 年数据的三次重分析，不是三次独立确认（K-EX11）** |
| E-EX08 | EXPERIMENT E1 | `docs/RESEARCH_LOG.md:833-846`（P11-b 尾部检验，`scratchpad/stop_tail.py`） | 单名最差持仓段亏损（时点 −2.125% TRUMP / 静态 −3.758% XRP 权益）在止损 4/6/8σ 与无止损下**三位小数完全相同**。原因：本书的损失是长期持有中的慢积累，不是相对入场的跳空；从入场起算的止损结构上管不到；能管到的是移动止损，而它恰好毁值 |
| E-EX09 | RESEARCH E3 + DATA E1 | Kaminski & Lo (2014)（既有 E-039）；`docs/RESEARCH_LOG.md:12`（第二轮 IC） | 止损只在收益正自相关的尺度增值、在均值回归尺度毁值。本系统自测：1–24h 前瞻 IC 显著为负（反转），周级为动量。任何在 ≈1 个日 σ 触发的退出都在反转尺度 |
| E-EX10 | EXPERIMENT E1 | `docs/RESEARCH_LOG.md:391-395`，registry H-001 注释 | `sign` vs `score`：逐 bar 收益差 NW t = −0.047（p 0.96），周块自助 Sharpe 差 [−0.238, +0.151]。**信号幅度不携带收益信息**——按"趋势强度"缩放敞口的先验为负 |
| E-EX11 | EXPERIMENT E1 | `config/live.demo.yaml:153-171`；`docs/RESEARCH_LOG.md:852` | 回撤节流（唯一已实现的"随 P&L 自适应"层）：时点通过、静态不通过（Sharpe 损失 0.117 > 0.10），复苏 fold 转负。对近期 P&L 做反应的机制在这本书上鞭打 |
| E-EX12 | CODE E1 | `starquant_alpha/signals/tsmom.py`（`apply_conviction_mode`）、`starquant_alpha/signals/base.py:72-118`（`scores_to_targets`）、`starquant_alpha/model.py:143-183` | 真正的退出机制：\|score\| ≥ 0.20 → ±1；\|score\| < 0.20 → NO_ACTION **保持上周期持仓**（D-005，E-022 教训）；精确 0 或方向翻转才平仓。**没有退出阈值 / 滞回 / 停留参数** |
| E-EX13 | DATA E1（信号统计，不含收益） | 18 个实盘币全历史 tsmom 原始分数（当前 registry 参数） | 持仓时间里 **26.8%** 处于次阈值持有；次阈值段长度中位 **3 bar**、p75 14、p90 44、最长 437；方向翻转中位 **17.1 次/币·年**（13.6–32.5）。09-06 16:00Z 时 1000PEPE 0.172、ADA 0.177 处于次阈值持有；到 09-07 03:00Z 闭合 bar 两者已回到 0.217 / 0.320，18 个持仓无一在次阈值——正是"次阈值段中位 3 bar"的样子。最接近阈值的 1000PEPE 0.217、TRUMP 0.219 净持仓为空头，因为 flow_short 探针书（3 个名字、独立波动率目标）在这两个币上的空头权重大于 tsmom 主书的多头权重；重置后的 8 次净方向翻转就来自这两本书的叠加，不来自 exit overlay。口径限制：用的是今天 18 个币的全历史（静态、含幸存者），只用于量级，不用于判定 |
| E-EX14 | DATA → **E5**（描述性，n=60 bar，**不得作为依据**；**[C 修订，K-EX07]** 这 7 个配置按仓库规则应计入 prior-trials，作者未擅自写共享 ledger，补记或书面豁免交操作者决定，见 §12 Q4） | 实盘目标权重 × mainnet 收盘的 scratch 重放（不写 ledger） | 重置后 60 bar：6/6 = 无叠加（0 次触发，毛 +194 U 模型口径）；TP3 +216（1 次）、TP2 +220（3 次）、TP1.5 +208（7 次）、TP1 +186（9 次）；trail1 +215（4 次）、trail2 +189（2 次）、trail4 0 次。这是操作者"看到的东西"：1–9 个事件、3 天，E5 |
| E-EX15 | DATA E1 | `.starquant/live/trades.jsonl` 74 笔成交 vs mainnet 决策 bar 收盘 | demo 成交价与 mainnet 收盘基差：中位 −0.4 bps，**\|中位\| 14.8 bps，p10/p90 −52/+37 bps**。任何 ≤1σ_1d（≈2–4% 价格）距离的退出规则，其距离的 5–10% 是 demo/mainnet 基差噪声，实盘触发率会系统性高于回测。**[C 修订，K-EX08] 尾部：\|基差\| p90 83 bps、p99 223 bps、最大 271 bps（ENAUSDT）**——对 σ_1d 4% 的币，TP3 的 12% 距离里最坏一笔就吃掉 2.3%；信号侧退出（O-EX1）对这一项免疫 |
| E-EX16 | CODE E1 | `starquant_live/reports.py:314-338` | M-005 在日报里只计数（次数、按规则）；RESEARCH_LOG 三处承诺的"触发后 24/72h 反事实收益"**没有实现**（`counterfactual` 在 live/cli 零命中） |
| E-EX17 | DOC E2 | `docs/analysis/2026-09-05-system-quality-deep-analysis.md:399-417,488,502`；`2026-09-06-remediation-execution-plan.md:102,153,192` | 已裁决 Won't：交易所原生止盈 / 移动止损 / 灾难止损（D-012；KILL-R14：18 币中 7 个 18 单位止损价 ≤ 0；KILL-R15）；"按 Sharpe 调止损参数"明确不做 |
| E-EX18 | DOC E2 | `config/live.demo.yaml:32-75`（P13） | `vol_target 0.30` 是 09-04 操作者声明"最大回撤预算 50%"后按自助 q95 回撤规则推出的（q95 −43.7% 时点 / −49.5% 静态）；降档阶梯 −35% → 0.225、−50% → 0.15 已预登记并每小时监测 |
| E-EX19 | DOC E2 | `reports/research/trials.jsonl`；`2026-09-06-remediation-execution-plan.md:249,391` | ledger tsmom 89 行、flow 14 行；DL-K1 起 `research overlay` 的每个候选计入书中每个策略的 ledger（`research_cmd.py:1101-1128`）；tsmom 下次复验更接近 WEAK_PASS（RISK-P4） |

### 3.2 Claim Register

| ID | 命题 | P | Axiom | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-EX01 | 当前 exit overlay 在盘整中未保护浮盈是需修复的缺陷 | **P0** | A1/A2 | 若回吐在设计噪声内且更紧的退出历史上都毁值，则不是缺陷 | E-EX02/02b/05（噪声内）、E-EX07/08（更紧毁值） | **REFUTED** |
| C-EX02a-SL | 更紧的**固定止损 / 移动止损**能在 Sharpe 损失 ≤ 0.10 下改善 OOS MDD | P1 | A2/A6 | 网格里任一更紧的止损 / 移动止损双通过 D-017 | E-EX07（止损 2.5/4σ、移动止损 4σ 全否） | **REFUTED**（在 0.15 构造上；方向对 vol_target 稳健，K-EX03） |
| C-EX02a-TP **[C 修订]** | 更紧的**固定止盈**（3σ / 4σ）能双通过 D-017 | P1 | A2/A6 | EXP-EX1b 两格双通过 | ~~**从未测过**（网格 TP ∈ {0, 6}）；先验为负（趋势系统利润在右尾；E-EX09 对止盈侧方向模糊）~~ **【结项，P22】** 现已测：TP3-entry 静态 Sharpe 损失 0.1736 > 0.10 门槛（不通过 D-017）；TP4-entry 静态 MDD 未改善（−0.3024 差于基线 −0.3011，不通过 D-017）；两档双 universe Sharpe 也都够不到 TP6-entry−0.02 的门槛。`docs/RESEARCH_LOG.md`"P22 裁决"节 | **REFUTED** |
| C-EX02b | **按行情状态切档**的止盈 / 止损能双通过 D-017 且优于同档固定止盈 | P1 | A2/A6 | EXP-EX2 的 2×2：regime 臂双通过、优于固定臂、镜像臂不过 | ~~从未测；先验 E-EX09/11 为负~~ **【结项，P22b】** 现已测：2×2 里哪个臂通过 D-017 本身跨 universe 不稳定——低 ER（chop）臂在静态通过、时点不通过（MDD 未改善约 0.09pp）；镜像（trend 收紧）臂正好相反，时点通过、静态不通过（Sharpe 损失 0.173）。两臂从未同时双通过，落在预登记规则的"其余情况"分支。`docs/RESEARCH_LOG.md`"P22b 裁决"节 | **REFUTED** |
| C-EX02c **[冻结后追加]** | 以**当前** σ 为单位的退出优于以入场 σ 为单位 | P1 | A2 | EXP-EX3 双通过且 MDD 不差于现行 | ~~从未测；方向不确定~~ **【结项，P22】** 现已测：TP6-current 双 universe MDD 均未改善（时点 −0.2537 vs 基线 −0.2534；静态 −0.3013 vs 基线 −0.3011），均差于 TP6-entry，不通过 D-017。`docs/RESEARCH_LOG.md`"P22 裁决"节 | **REFUTED** |
| C-EX03 | 对本书，退出应响应的"市场状态"是周级信号自身的衰减，不是价格相对入场 / 极值的路径 | P1 | A2/A5 | 描述统计 + EXP-EX1 | E-EX09/12 结构一致；**E-EX10（幅度不携带收益信息）反向**；E-EX13 不含收益。**【结项，P23 第 0 步】** 现已测（描述统计，`scratchpad/p23_subthreshold_forward.py`）：次阈值持有段的前瞻收益不显著低于可执行段，h=72 时 diff t=+0.92（两段同号同向为正，次阈值段更小但不显著），< 预登记停止门槛 t<2.0。停止条件触发，`exit_threshold`/`exit_dwell_bars` 未实现。`docs/RESEARCH_LOG.md`"P23 裁决"节 | 曾 PARTIAL →（**[C 修订，K-EX02]**）降级 UNKNOWN → **【结项】REFUTED** |
| C-EX04 | 本次观察到的回吐在设计噪声之内 | P1 | A1 | 回吐 > 2 个设计日 σ（≈350 U/日）或触及 P13 阶梯 | E-EX05 | **SUPPORTED** |
| C-EX05 | exit overlay 价值的实盘裁决者（M-005 反事实）不存在 | P2 | A7 | 代码里已有 | E-EX16。**【结项】** 反事实已实装于 `starquant_live/reports.py`（`exit_counterfactuals`），但形态是**监测**而非裁决者（K-EX12：事件率≈2/周，30 天 n≈8 不足以裁决），携带自己的 `n_needed_for_decision`；裁决权仍留在 D-017 双 universe 回测 | 曾 SUPPORTED（缺口存在）→ **【结项】CLOSED**（缺口已补，以监测形态） |

### 3.3 Assumption Register

| ID | 假设 | 影响 × 风险 | 最小验证 | 通过阈值 | 未通过动作 | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| A-EX01 | 操作者对回吐的不适与其 50% 回撤预算一致 | **高 × 高** | 一问（Q-CRITICAL） | 回答"接受 ±1% 日内摆动" | 议题改为回撤预算 → `vol_target`（O-EX5） | GAP-EX00 |
| A-EX02 | "震荡"可事前识别且切档能改善 | 高 × 高 | O-EX2 预登记三臂 | 低 ER 臂双通过且优于无条件臂且镜像臂不过 | O-EX2 记负结果，C-EX02b REFUTED | GAP-EX02 → **【结项】已发生（P22b），见 §3.2** |
| A-EX03 | 信号衰减早于翻转的退出能改善持仓段留存 | 高 × 高 | O-EX1 预登记两格 | §7 采纳规则 | 记负结果；C-EX03 降 REFUTED | GAP-EX01 → **【结项】已发生（P23 第 0 步，未到两格网格就停），见 §3.2** |
| A-EX04 | exit overlay 的 P11 判定在 0.30 构造下仍成立 | 中 × 低 | 触发是价格路径决定的（E-EX07 口径注） | — | 任何新实验都在 0.30 上跑，自动覆盖 | — |

### 3.4 Gap Plan

| Gap | 影响 | 不确定性 × 决策影响 | 最小方法 | 成本 | 未完成时上限 |
| --- | --- | --- | --- | --- | --- |
| GAP-EX00 | A-EX01 / 整体方向 | 高 × 高 | 操作者回答 Q-CRITICAL | 0 | ~~本文结论以"接受"为假设成立~~ **【结项】已回答**：Q1/Q2（§12）——权益日摆动 ≈±170 U（`vol_target 0.30`）被接受，exit overlay 角色见 §12 讨论 |
| GAP-EX01 | C-EX03 / O-EX1；M-EX01 基线 | 高 × 高 | `starquant research validate --strategy tsmom --universe pit --grid '{"exit_threshold":[0.10],"exit_dwell_bars":[24,72]}' ...`（需先实现参数）+ 一次当前构造回测取 M-EX01 基线 | tsmom ledger +2～3 | ~~Need Evidence~~ **【结项】已关闭**——C-EX03 侧：P23 第 0 步在描述统计门停止，两格网格从未跑（不计入上面"成本"列的 tsmom +2～3）；M-EX01 基线侧：`scratchpad/m_ex01_retention.py`（不计费，见 §4.4）已测得两个 universe 的数字 |
| GAP-EX02 | C-EX02b / O-EX2 | 高 × 高 | `starquant research overlay --universe pit/static --exits-grid <三臂>`（需先实现 `k_scale`） | tsmom + flow 各约 +6 | ~~Need Evidence~~ **【结项】已关闭**——P22b 2×2 已跑（tsmom/flow 各 +4，实际成本低于预估的各 +6），C-EX02b REFUTED |
| GAP-EX03 | C-EX05 / M-005 | 低 × 中 | 实装反事实（DL-EX0） | live ≈40 行 | ~~—~~ **【结项】已关闭**——`exit_counterfactuals` 已实装（DL-EX0b，实测 live ≈50 行，与 DL-EX0 合计 ≈149 行，见 K-EX05），以监测形态交付 |

---

## 4. Phase 3 · Problem Research

### 4.1 Problem Statement

对于在 Binance USDⓈ-M demo 上无人值守运行周级 tsmom 主书（`conviction_mode: sign`、`vol_target 0.30`）的单一操作者，当市场进入 7–14 天的低效率盘整（E-EX04）时，18 个持仓的未实现盈亏从 ≈ +329 U 回到 +264 U（E-EX02b），而 exit overlay 距最近触发仍有 2.6σ 以上（E-EX03），操作者于是感到"止盈止损不适用、应随行情自适应"。如果不解释、不给尺度，最可能的后果是手动干预（操作者随时具备这一能力；09-04 的全平是重启检验而非对浮盈的干预，K-EX10）或按 3 天数据调参——两者都会污染唯一的样本外记录（实盘期即 holdout，KILL-006），并把一个经三轮验证"无害"的层换成一个已三次被证明"有害"的层。

### 4.2 Causal Chain

| 层级 | 内容 | Evidence | 可干预性 |
| --- | --- | --- | --- |
| 表层现象 | 浮盈 +329 → +264 U，exit overlay 零触发 | E-EX02b/03 | — |
| 直接原因 | 主流币 7 日效率比 0.004–0.02（净变动 ≈0、高低幅 8–12%）；15 个多头的周级信号仍为正（09-07 03:00Z：BTC 0.395、ETH 0.423、SOL 0.506、最低 SUI 0.261），书按设计持有 | E-EX04/13 | 不可干预（这是行情） |
| 深层原因 | ① `vol_target 0.30` 使权益日 σ ≈ 172 U，65 U 回吐是 0.4σ；② exit overlay 阈值 6σ_1d 按构造对盘整免疫；③ 次阈值分数 NO_ACTION 保持持仓，只有翻转才平仓 | E-EX05/01/12 | ① 风险预算可改（代价：与 50% 预算矛盾）；② 已三轮证明不该改；③ **可测**（O-EX1） |
| 系统性原因 | 操作者没有"什么算噪声"的尺度；exit overlay 的实盘裁决者 M-005 只是计数器 | E-EX05/16 | 可干预（O-EX0、DL-EX0） |
| 可干预杠杆 | (a) 给噪声尺度；(b) 信号侧退出滞回（先写后跑）；(c) 若真不接受摆动 → 风险预算 | — | — |

### 4.3 Problem Reframing（D-EX00）

| 框定 | 一句话 | 若为真的方向 | 区分证据 | 支持度 |
| --- | --- | --- | --- | --- |
| F1 参数问题 | 止盈止损太宽 / 写死 | 调参、按行情切档 | 更紧或切档设置双通过 D-017 | **固定更紧：被 E-EX07 排除（证据，非推理）**；切档：未测 |
| F2 工具错位 | 退出决策属于信号，不属于价格路径 overlay | 改信号退出侧 | O-EX1 通过而 O-EX2 不通过 | E-EX09/10/12 结构支持，未作为退出规则验证 |
| F3 尺度 / 预期问题 | 回吐是 0.30 目标下的设计噪声 | 不动；给尺度 | E-EX05 | 支持 |

**D-EX00**：F3 解释本次观察；F2 是对"增加盈利、减少亏损"诉求的工作框定；F1 只保留"按行情切档"这一未测分支作为可证伪实验（O-EX2）。放弃 F1 固定调参的理由是三轮证据；重开条件：O-EX2 双通过且优于无条件收紧臂。

### 4.4 Success Definition（写在方案之前）

| Metric | 类型 | 指标 | 基线来源 | 关联 | 为什么量的是问题而不是方案 |
| --- | --- | --- | --- | --- | --- |
| M-EX01 | 领先（问题级） | 每个已平仓持仓段的**留存比** = 平仓 P&L / 段内最大浮盈（MFE）；同时报告 MFE 中位数与段长 | 回测按持仓段计算（~~GAP-EX01~~ **【结项】已关闭**）；实盘 `trades.jsonl` 配对 | Pre-EX1、C-EX03 | 直接量"浮盈回吐了多少"，与用什么规则退出无关 |
| **M-EX01 基线（结项测得）** | 描述性，不计费（见脚本 docstring，理由同 `exit_reachability.py`——评估零候选、不做筛选） | pit（205 币）留存比 p25 **−1.929**、中位 **−0.104**、p75 **+0.933**（MFE 中位 0.39%、p75 1.03%；段长中位 195 bar；3406 段中 529 段 MFE≤0 未转正、不计入比值）；static（18 币）留存比 p25 **−1.806**、中位 **−0.196**、p75 **+1.000**（MFE 中位 0.70%、p75 1.42%；段长中位 271 bar；1953 段中 249 段未转正） | `scratchpad/m_ex01_retention.py`，在**现行 shipped 构造**（sl6/tp6/entry 单位，`vol_target 0.30`）上复用 `exit_reachability.episodes()` 的分段/MFE 机制测得 | C-EX03、Pre-EX1 | **中位留存比为负**：典型的"曾经转正过"的持仓段，到平仓时已经不只是把浮盈吐完，还倒亏超过浮盈峰值本身——操作者原始抱怨第一次被直接量出来，与用哪条退出规则无关（GAP-EX01 关闭）。**读这个数之前先读下面一段** |

> **M-EX01 怎么读，以及它为什么不与那四个 REFUTED 矛盾。** 中位留存比为负听起来像是在支持"该收紧止盈"，而同一天四次预登记实验都说不该。两者都对，原因在**同一张表的 MFE 那一列**：中位持仓段的浮盈峰值只有 **0.39%（时点）/ 0.70%（静态）**。那不是一个可收割的量——demo 与 mainnet 的成交基差中位就有 14.8 bps、p99 有 223 bps（E-EX15），来回一趟的换手成本按成本模型是 14 bps，而要在 0.39% 的峰值上择时退出，规则必须先把它与噪声分开。所以中位段的"回吐"不是被浪费的利润，是**从来就不存在的利润**。
>
> 这本书的收益在**右尾**：p75 的 MFE 是中位的 2.6～3 倍，段长中位 195～271 bar（8～11 天，与周级信号一致）。任何按固定或按 regime 收紧的止盈，在砍掉右尾的同时并不能救回中位段——这正是 P22 量到的形状：静态 universe 上 TP3 把回撤改善了 6.34pp（真实且很大），代价是 0.1736 的 Sharpe，两个数是同一件事的两面。
>
> 因此 M-EX01 的正确用途是**基线**，不是行动依据：它是任何未来退出侧改动必须超过的那条线，而且必须与 M-EX03 联读（留存比升而 Sharpe 降 = 砍赢家，不采纳）。本轮没有任何候选达到"可与基线比较"的阶段——O-EX1 停在描述统计门，其余三个被 D-017 挡下。
| M-EX02 | 滞后 | M-010：30 天 income 归因 Sharpe vs 预期（已存在） | 日报 | 全部 | 盈利本身 |
| M-EX03 | 护栏 | D-017：OOS Sharpe 损失 ≤ 0.10 且 OOS MDD 改善，时点 + 静态双通过；信号侧改动用 H-001 式配对规则（OOS ≥ 基线 −0.05、MDD 改善、逐 bar 差 NW t 不显著为负、静态方向一致）。**[C 修订，K-EX06]** 换手条款：任何退出规则按构造增换手，所以这里**不**沿用 H-001 的"换手必须下降"，改为"换手上升 ≤ 25% 且成本占毛利 ≤ 15%（现 9.7%）" | overlay / validate 报告 | C-EX02a-TP/02b/02c/03 | 防止"留存比"靠砍掉赢家来改善 |
| M-005 | 领先（层级，已有 ID） | 退出触发/周 + 触发后 24/72h 反事实收益（~~**需实装**~~ **【结项】已实装**，`starquant_live/reports.py` `exit_counterfactuals`，K-EX12：监测而非裁决，携带 `n_needed_for_decision`） | `cycles.jsonl` | C-EX05 | exit overlay"有没有帮到"的唯一实盘证据 |

### 4.5 Stakeholder（含受损方）

| 角色 | 身份 | 诉求 | 反对点 |
| --- | --- | --- | --- |
| 操作者 | 用户 / 付款 / 审批 / 风险承担 | 少回吐、多盈利、少操心 | 不想再等实验 |
| 实盘记录（KILL-006） | 受损方候选 | 不被构造变更重置 | 任何 live 改动都重置 M-010 窗口 |
| flow_short 探针书 | **受损方** | ledger 不被无关实验膨胀 | O-EX2 会往 flow ledger 记约 6 行（DL-K1），压低它未来复验的 FWER headroom |
| 未来维护者 | 受损方 | 参数少 | O-EX1 +2 参数、O-EX2 +1 输入 |

### 4.6 Edge Cases（进入 Test Contract）

| Edge | 场景 | 预期 |
| --- | --- | --- |
| X-EX1 | `exit_threshold = entry_threshold`、`exit_dwell_bars = 0` | 与现行 `scores_to_targets` 逐位相同（默认不改变任何行为） |
| X-EX2 | 次阈值持续 dwell 后平仓，随后分数回到 ≥ 0.20 同向 | 立即重新入场（不是冷却；冷却属于 exit overlay，不属于信号） |
| X-EX3 | 次阈值期间方向翻转 | 翻转立即生效，dwell 计数清零 |
| X-EX4 | 实盘请求窗口（1,442 bar）内 dwell 计数需重建 | dwell ≤ 72 ≪ 1,442，从窗口内分数重建；不新增持久状态 |
| X-EX5 | O-EX2 的 ER 需 168 bar，参考需 ≤ 1,300 bar | 用预登记的固定阈值而不是 90 日中位（见 §6.3） |
| X-EX6 | AKE 类高波动币的 6σ 止损价 ≤ 0 | 现状即如此（E-EX03）；任何 `k_scale < 1` 才可能使其可触发，需在报告里单独计数 |

---

## 5. Phase 4 · Relative Value / Strategic / Economic

| 替代路径 | 当前可用性 | 核心结果比例 | 成本 | 风险 | 本方案真实增量 |
| --- | --- | --- | --- | --- | --- |
| 现状（6/6 + 信号翻转） | 在跑 | 已拿到全部"保险"价值；三轮证据说无更好固定设置 | 0 | 0 | — |
| 操作者绕行（手动平仓） | 随时 | 一次性锁定，但重置 holdout、且历史上手动介入平均为负期望 | 污染样本外 | 高 | 本方案避免它 |
| 固定收紧 / 移动止损 | 一行配置 | **负**（E-EX07） | 0 | 确定毁值 | — |
| O-EX1 信号侧滞回 | 从未写完整实现——第 0 步描述统计（0 行 alpha）即停 | ~~未知；先验中~~ **【结项】REFUTED（P23 第 0 步，先验降为低–中后仍不显著，t=0.92<2.0）** | tsmom ledger +1（诊断，非 +2～3——两格网格从未跑） | 鞭打税（E-EX13） | 未通过：`exit_threshold`/`exit_dwell_bars` 未实现 |
| O-EX2 行情切档（原意） | 需 ≈170 行 + 预登记（实测 alpha+47/live+16） | ~~未知；先验低~~ **【结项】REFUTED（P22b 2×2，哪个臂过 D-017 跨 universe 不稳定）** | tsmom + flow 各 +4（实际，预估各 +6） | 移动止损的翻版 | 未通过：C-EX02b REFUTED，F1 不重开 |
| O-EX5 降 vol_target | 一行 | 确定平滑权益，但等价于改 50% 预算 | 0 | 与 P13 决策矛盾 | 只在 A-EX01 不成立时正确 |
| 不行动 | — | 与现状同 | 0 | 操作者继续不安 → 手动干预 | O-EX0 的日报行就是"不行动 + 给尺度" |

80% 结果的廉价方案：**有**——O-EX0（保持不动 + 日报噪声尺度行）拿到操作者真正需要的大部分东西（知道这算不算异常）。技术先进性 → 可感知价值：自适应退出在这本书上没有可感知价值的证据。相对价值结论：**Adequate**（No-Build 已是最优的已验证方案；实验分支 Unproven，故只以实验进入，H5）。

Strategic Fit **High**：操作者的标准是 ≥90% 投入在 alpha；O-EX1 落在 `starquant_alpha`，O-EX0 的 ≈60 行非 alpha 在 KILL-R12 的 100 行阈值内。Economic：单人项目 N/A；真实的机会成本是 ledger 名额（RISK-EX03）与一次重启（重置 M-010 窗口）。Cost of Delay：1 周 / 1 月不做的损失 ≈ 0（现状经验证无害）；唯一有时间价值的是 M-005 实装——每晚一天，未来触发的反事实就少一条。

---

## 6. Phase 5 · System Analysis

### 6.1 As-Is / To-Be

| 维度 | As-Is | To-Be（若 D-EX01 全部执行） |
| --- | --- | --- |
| exit overlay `exits.py` | 6/6/0，入场锚，σ 冻结于入场 | 不变（O-EX2 未通过前） |
| 信号 → 目标 `scores_to_targets` | entry 0.20；次阈值 hold；翻转/0 退出 | + `exit_threshold`、`exit_dwell_bars`（默认 = 现状，逐位相同） |
| registry | `entry_threshold` 属性 | + `exit_threshold` / `exit_dwell_bars` 读取；参数门自动覆盖新参数 |
| 日报 | M-005 计数 | + 反事实 24/72h；+ 设计日 σ（U）与今日峰值回吐/σ |
| 研究 CLI | validate 网格任意参数 | 无需改；overlay 需 `k_scale`（仅 O-EX2） |

### 6.2 Impact Radius

R0 信号→目标函数（纯函数，+2 参数）；R1 实盘每周期同一函数（dwell 从窗口重建，无新持久状态）；R2 无（不碰下单/风控）；R3 日报 +2 段；R4 ledger +2～3（O-EX1）/ +12（O-EX2）；R5 无；R6 认知复杂度：+2 参数并写明默认等价于现状。

### 6.3 Engineering Pre-check

| 维度 | 已知事实 | 未知 / 实验 | 风险 / 失败动作 |
| --- | --- | --- | --- |
| O-EX1 落点 | `starquant_alpha/signals/base.py:72` `scores_to_targets(scores, entry_threshold, hold, zero_is_exit, initial)`；`registry.py:44` `StrategyEntry.entry_threshold`；`model.py:175-178` 调用处 | dwell 计数在向量化 ffill 里的实现（连续次阈值计数 ≥ dwell → 0） | T-EX1-1 逐位等价测试失败 → 不合并 |
| O-EX1 live | 请求窗口 1,442 bar ≫ dwell 72；`previous` 种子只影响窗口前的持有 | 窗口起点处 dwell 计数从 0 起算（偏保守：晚退出不早退出） | 记录为已知偏差 |
| O-EX2 落点 | `exit_step` 阈值为常量；`apply_exits` 逐 bar 循环可接受 `k_scale` 帧；`ExitOverlay.apply` 每币有 `frame`（≥1,442 bar）可算 ER_168 | **live 拿不到 90 日参考**（E-042：请求上限 1,500 bar），regime 阈值必须是预登记的固定值（如 ER_7d < 0.05） | 若用滚动参考 → 研究/实盘算出不同 regime（KILL-027 形状）；禁止 |
| 非 alpha 行数 | O-EX0 ≈60（reports.py）；O-EX2 ≈90（live 60 + cli 30） | O-EX0 + O-EX2 合计 ≈150 > KILL-R12 的 100 行规则 | 需操作者裁定 ceiling 或分批 |
| ledger | DL-K1：overlay 每候选计入书中每策略；validate 每配置计入该策略 | 同配置基线是否去重（dedup 键含 symbols/range） | 按最坏情况计：O-EX1 +3、O-EX2 +6/策略 |
| 参数门 | 新 registry 参数 → 必须重跑 validate 并更新证据指针，否则 `run_live.sh` 60s 重试循环（记忆 lesson 4） | — | 采纳流程写死："改 registry = 重验 + 指针 + 重启" |
| 数据 | O-EX2 的 ER 只需 `close`；O-EX1 只需分数 | — | — |

### 6.4 Risk Register

| Risk | 事件 | 概率 / 影响 | 预警 | 缓解 / 失败动作 |
| --- | --- | --- | --- | --- |
| RISK-EX01 | 更多退出 → 鞭打税（次阈值段中位 3 bar） | 高 / 中 | 换手、成本占比 > 15% | dwell 参数；采纳规则含成本占比 |
| RISK-EX02 | demo/mainnet 基差吞掉紧退出距离：中位 14.8 bps，**尾部 p99 223 / 最大 271 bps**（[C 修订] 按尾部而非中位评估，K-EX08） | 高 / 中 | 实盘触发率 ≫ 回测 1.9/周 | 任何 ≤1σ 距离的价格路径规则不进 demo；价格路径实验（O-EX1b/O-EX7/O-EX2）的实盘触发率与回测对比列为 falsifier；信号侧 O-EX1 免疫。**【结项】falsifier 从未被挂上**：TP3/4/current/regime 全部在回测阶段（D-017）就被 REFUTED，没有价格路径候选进入 live，K-EX08 因此维持 OPEN（N/A-until-adoption） |
| RISK-EX03 | ledger 膨胀逼近 WEAK_PASS（tsmom 89 → ≤98） | 中 / 中 | FWER headroom 0.02–0.04 | 网格最小化；O-EX2 需操作者明确同意 | **【结项】实际落点**（`reports/research/trials.jsonl` 实测）：tsmom 89 → 99（P22，+10）→ 100（P23 第 0 步，+1 诊断）→ **104**（P22b，+4）；flow 14 → 24（P22）→ 28（P22b）。104 已超过本行写下时的"≤98"上限，是已知、已记录的代价（RISK-P4：下次 tsmom 复验更接近 WEAK_PASS），未触发额外裁定 |
| RISK-EX04 | 非 alpha 行数超规则。**[C 修订，K-EX05]** 六个包全部顶在 CEILING；捆绑 O-EX0 ≈20 + M-005 ≈50 + O-EX2 live/cli ≈90 = 160 ≥ 100 | 高 / 中 | `tests/architecture/test_source_budget.py` | 分批记账：O-EX0 + M-005 ≈70 行先行并请操作者裁定 ceiling；O-EX2 的 live 接线只在研究通过后再记 | **【结项】已按分批记账执行**：DL-EX0/0b 先行（Q5=A，抬 ceiling，实测 +149 live）；O-EX2 的 live/cli 接线在 P22b（研究）通过 ledger 记账后才写（Task 7 提交单独抬 ceiling，+47 alpha/+16 live），两次抬升都带各自的理由句，见 K-EX05 终态 |
| RISK-EX05 | 改 registry 不重启 → 分叉（D-042） | 低 / 高 | `live status --check` | 采纳即重启并记构造变更 |
| RISK-EX06 | E-EX14 的 "+20 U" 诱使直接采纳 TP2/TP3 | 中 / 高 | — | 本文写明 n=1–3、E5；采纳只走 D-017 |
| RISK-EX07 | 操作者在实验期间手动干预 | 中 / 高 | 外部成交（D-032 foreign fills） | 日报噪声尺度行 + 本文 §12 的"什么才算异常" |
| RISK-EX08 **[C 修订，K-EX14]** | 任何采纳 = 构造变更 = M-010 证据窗口清零（当前只有 4.6 天） | 高 / 中 | `construction_changes_last_7d` | 建议规则：M-010 未满 30 天连续构造前不采纳任何退出 / 信号改动，除非 P13 阶梯触发；由操作者确认（§12 Q6） |

---

## 7. Phase 6 · Solution Reasoning

### 7.1 Option Set

| Option | 方案 | 先验 | 成本 | 可逆 | 结论 |
| --- | --- | --- | --- | --- | --- |
| O-EX0 No-Build + 尺度 | 保持 6/6；日报加"设计日 σ（U）、今日峰值回吐及其 σ 倍数、退出触发期望 vs 实际" | — | ≈20 行 live | 高 | **Must** |
| O-EX0b M-005 实装 | 每次退出事件记 +24/+72 bar 的反事实收益（若不退出该仓位会赚/亏多少，含省下的成本） | — | ≈40 行 live | 高 | **Must** |
| O-EX1b 固定止盈扩格 **[C 修订，K-EX01]** | 预登记网格加 `take_profit ∈ {3, 4}`（止损 6 不变）；纯 CLI 网格参数，**零新代码路径** | 低（趋势系统利润在右尾），但这是操作者字面问题里唯一从未测过的档，且是 O-EX2 的必要对照 | 0 行代码；tsmom + flow 各 +4（两档 × 两 universe） | 高 | ~~**Should，第一个实验**~~ **【结项】已跑（P22），TP3/TP4 均 REFUTED，见 §3.2** |
| O-EX1 信号侧退出滞回 | `exit_threshold`（默认 **None = 关闭**）、`exit_dwell_bars`（默认 **0 = 关闭**）：\|score\| < exit_threshold 连续 ≥ dwell bar → 平仓；翻转仍即时。**[C 修订，K-EX04]** 现状是次阈值**无限期**持有，任何有限 dwell 都不是现状，所以默认必须 off，并配位同测试 | 低–中（**[C 修订，K-EX02]** E-EX10 说幅度不携带收益信息，先验下调）；优点：对 demo/mainnet 基差**免疫**（K-EX08）；E-EX13：无 dwell 必鞭打 | alpha ≈60 行 + 重验 + 指针 + 重启；先做 1 项描述统计（计 1 trial），再决定是否花 validate 名额 +2 | 高（参数关闭即现状） | ~~**Could（描述统计之后再定）**~~ **【结项】描述统计已做（P23 第 0 步），不显著（t=0.92），未花 validate 名额，`exit_threshold`/`exit_dwell_bars` 未实现** |
| O-EX2 行情切档退出（原意） | `exit_step` 接受 `k_scale`；regime = ER_168（\|净变动\| / 路径长度）与**预登记固定阈值 0.05** 比较（不用滚动中位，K-EX13）；**2×2 判定**：基线 6/6、固定 TP3（来自 O-EX1b）、低 ER 才 TP3、高 ER 才 TP3（镜像） | 低（65–75% 不通过）：低 ER 收紧 ≈ 盘整中的移动止损 | alpha ≈80 + live ≈60 + cli ≈30（live/cli 部分只在研究通过后再写，K-EX05）；tsmom + flow 各 +4（两个 regime 臂 × 两 universe；固定臂已在 O-EX1b 计过） | 高 | ~~**Could（O-EX1b 之后、操作者点头才跑）**~~ **【结项】已跑（P22b），2×2 里哪个臂过 D-017 本身跨 universe 不稳定，C-EX02b REFUTED** |
| O-EX3 组合层 regime 敞口标量 | 一个标量乘整行（D-015 形状） | 低（E-EX10/11；mining 里 vol-regime 门 +0.002） | 中 | 高 | Won't（重开条件：O-EX2 显示 regime 效应） |
| O-EX4 滚动入场锚 | 同向加减仓重锚 / 每 N bar 重锚 | 低（= 慢速移动止损） | 低 | 高 | Won't |
| O-EX5 降 vol_target | 更平滑的权益曲线 | 确定有效但不是退出问题；等于改 50% 预算 | 一行 | 高 | 只在 A-EX01 不成立时 |
| O-EX6 交易所原生条件单 | — | — | — | — | Won't（E-EX17） |
| O-EX7 当前波动单位（**冻结后追加**，见附录 A） | `ExitParams.unit_mode: entry \| current`：阈值距离用**当前** σ_1d 而不是入场时的 σ_1d；锚仍是入场价与极值。即 Chandelier/ATR 类退出的"随波动伸缩"，不需要任何 regime 探测器 | 中低；方向不确定：波动回落时阈值收紧（操作者想要的"盘整中收紧"），波动上升时放宽 | alpha ≈10 行；tsmom + flow 各 +2 | 高 | **Should（预登记实验 EXP-EX3，最便宜的"自适应"检验）** |
| O-EX8 部分止盈（scale-out） | `take_profit_fraction < 1`：到 +kσ 只平一半 | 低：TP6 本身中性（E-EX07），趋势跟随的利润在右尾 | alpha ≈15 行 | 高 | Won't（重开条件：EXP-EX3 显示波动自适应有效） |

### 7.2 Failure Modes

| Failure | Option | 模式 | 预警 | 失败动作 |
| --- | --- | --- | --- | --- |
| FM-EX1 | O-EX1 | 早退出后信号回升，重新入场，付双份成本 | 换手 ↑、成本占比 > 15% | 不采纳；记负结果 |
| FM-EX2 | O-EX1 | dwell 太长 → 与翻转几乎同时，效应为零 | 与基线逐 bar 差 t ≈ 0 | 记"无效"，不再扩网格 |
| FM-EX3 | O-EX2 | 低 ER 臂通过但镜像臂也通过 | 两臂同过 | 判噪声，C-EX02b REFUTED |
| FM-EX4 | O-EX2 | 研究与实盘 regime 不一致（参考窗口不同） | 实盘切档率 ≠ 回测 | 固定阈值（§6.3）；否则不进 live |
| FM-EX5 | 全部 | 采纳后不重启 / 不更新指针 | `live status --check` 报分叉 | 按 RUNBOOK 重启 |

### 7.3 Recommendation Decision（D-EX01）

| 字段 | 内容 |
| --- | --- |
| 推荐（**[C 修订]**） | **PIVOT**：O-EX0 + O-EX0b 现在做；第一个实验 = 一次 overlay 运行含 O-EX1b（固定 TP 3/4）+ O-EX7（当前 σ 单位）；之后视结果与操作者意愿：O-EX2 的 2×2、O-EX1 的描述统计→validate；更紧止损 / 移动止损 / 滚动锚 / 组合层标量 / 部分止盈 / 原生单 Won't。**【结项】全部已执行**：O-EX0/O-EX0b 已交付（DL-EX0/0b）；第一个实验已跑（P22，TP3/4/current 全 REFUTED）；O-EX2 的 2×2 已跑（P22b，REFUTED）；O-EX1 的描述统计已做（P23 第 0 步，未到 validate 就停）。四个假设全部 REFUTED，Won't 列表原样维持 |
| 胜出理由 | 唯一同时满足"不推翻三轮证据、不污染 holdout、回应诉求、可证伪"的组合 |
| 放弃 | 直接改配置（无证据）；按 E-EX14 调参（n=1–3）；O-EX5（前提是 A-EX01 不成立，尚未知） |
| 关键成立条件 | A-EX01 成立（操作者接受设计内摆动）；ledger 名额可接受 |
| Falsifier | O-EX2 低 ER 臂双通过、优于无条件臂、镜像臂不过 → 本文的 F2/F3 框定错了，exit overlay 应改成切档 |
| 灰度 / 降级 / 回滚 | 任何采纳先 `--dry-run` 于 scratch state_dir；上线 = registry/profile 一行 + 重启；回滚 = 还原该行 + 重启 |
| 接受的损失 | 操作者即时诉求延后；flow ledger 承担 O-EX2 的名额（若跑）；补偿见 Memo |
| 最可能的偏差与对策 | **锚定既有研究结论**（三轮否定移动止损）而低估未测分支。**[C 修订] 审查证实这个偏差确实在起作用，只是位置不在作者预料的地方**：作者把"未测"留给了 regime 分支，却把同样未测的固定止盈 <6σ 写成了"已被证据排除"（K-EX01）。对策：C-EX02a 拆分；固定 TP 扩格作为第一个实验；E-EX14 如实列出并交 ledger 处置 |

---

## 8. Phase 7 · Adversarial Review（独立子代理）

> 冻结产物：`scratchpad/exits-adaptive-frozen.md`（Phase 1–6 冻结版，115 行）。审查者为独立子代理（同一模型、不同上下文，**部分独立**），只读冻结文件与原始证据路径，未读作者推理；耗时 18 分钟、51 次只读工具调用；未写入、未跑回测、未碰 ledger。审查者独立复算了 E-EX02/05/06/03/07/15/16/19，复算值与冻结文件一致（小时 std 18.9 vs 19.5 U；基差 p10/p90 −53.1/+37.7 vs −52.3/+37.4 bps）。附录 A 与 O-EX7/O-EX8/EXP-EX3 是冻结后追加的，**不在本次审查范围内**。

### 8.1 最强反方论点（审查者在读推荐方案之前写定）

> C-EX01 被标 REFUTED 靠的只是"固定更紧退出毁值"（C-EX02a）那一条腿，而操作者要的是"随行情自适应"，对应的 C-EX02b 是 UNKNOWN；分析在还没测操作者真正问的东西之前，就把问题降级成"感知"。读完方案后的修正：论点方向成立、严重度 P1。"这次回吐不是缺陷"对操作者的具体抱怨是稳的（C-EX04 独立成立）；**不稳的是它被推广成"F1 固定调参已被三轮证据排除"——预登记网格 `take_profit ∈ {0, 6}`，6σ 以内的止盈从未测过，而止盈侧恰是操作者抱怨的一侧，也是全网格里唯一"有益"（MDD +0.58 / +0.85pp）的方向。**

作者回应：**接受。** §0 Memo、§3.2 Claim、§7 Option Set、§11.2 实验与 §12 已按此改写（改动处标 **[C 修订]**）。

### 8.2 Kill Register（14 条：P0 0 / P1 9 / P2 5；写下时全部 OPEN，逐条给出关闭路径——**【结项，2026-09-07】13/14 已关闭或缓解，终态见末列**）

| Kill | 攻击命题（压缩） | P | 作者回应与关闭路径 | **终态（结项）** |
| --- | --- | --- | --- | --- |
| K-EX01 | C-EX02a 的 REFUTED 覆盖了从未测过的止盈 <6σ；Option Set 缺最便宜的实验（固定 TP 扩格）；O-EX2 用 TP3 却无固定 TP3 对照 | P1 | 接受。C-EX02a 拆为 02a-SL/trail（REFUTED）与 02a-TP（UNKNOWN）；新增 O-EX1b「固定 TP ∈ {3, 4} 预登记扩格」为**第一个实验**兼 O-EX2 的对照臂。关闭需新证据：EXP-EX1b 运行 | **CLOSED — 新证据**：P22 跑了 TP3/TP4-entry（`docs/RESEARCH_LOG.md`"P22 裁决"节），C-EX02a-TP → REFUTED |
| K-EX02 | C-EX03 PARTIAL 与 O-EX1 先验"中"无证据；E-EX10（幅度不携带收益信息）反向 | P1 | 接受。C-EX03 → UNKNOWN；O-EX1 先验降为低–中；花 validate 名额前先做一项描述统计（次阈值持有段 vs 可执行段的前瞻收益，计 1 个 prior trial）；O-EX1 不再排在扩格之前 | **CLOSED — 新证据**：P23 第 0 步测了这项描述统计（`scratchpad/p23_subthreshold_forward.py`），h=72 diff t=+0.92<2.0，C-EX03 → REFUTED |
| K-EX03 | E-EX07/E-EX11 在 `vol_target 0.15` 上算、实盘 0.30，冻结文件未披露；边界项（SL6+TP6 静态 0.0892 vs 0.10；节流）敏感 | P1 | 接受。触发事件对 vol_target 不变（价格路径），否定项裕度 0.03–0.20，REFUTED 方向不翻；任何采纳前在 0.30 上重跑 D-017；E-EX11 降为 E3 先验 | **CLOSED — 新证据**：P22 把现行 TP6-entry 与节流都在 0.30 上重跑（"控制行的意外"节 + 节流一行），方向不翻；TP6-entry 双通过 D-017 |
| K-EX04 | O-EX1"默认 = entry 0.20 即现状"错误：现状是次阈值**无限期**持有，有限 dwell 不是现状；"一个参数、高可逆"失真 | P1 | 接受。默认必须 off（`exit_dwell_bars=0` 或 `exit_threshold=None`）；位同测试；成本列改写（两参数 + dwell 逻辑 + 重验 + 指针 + 重启） | **CLOSED — 已成过去式（moot）**：P23 在描述统计门停止，`exit_threshold`/`exit_dwell_bars` 从未写进 `scores_to_targets`，默认值该是什么不再是需要裁定的问题 |
| K-EX05 | KILL-R12 对**捆绑**生效：O-EX0 ≈20 + M-005 反事实（未估行）+ O-EX2 live/cli ≈90 → 非 alpha ≥ 100；六个包全部顶在 CEILING（`test_source_budget.py:704-711`） | P1 | 接受。每个 DL 标包别行数；M-005 估 live ≈50 行；O-EX0 + M-005 ≈70 行先行，O-EX2 的 live 接线只在研究通过后再记账；ceiling 抬升由操作者裁定 | **MITIGATED**：Q5=A，ceiling 逐笔抬升且每次都带"规则要求的句子"（`test_source_budget.py` CEILING 注释历史，含 DL-EX0/0b 的 +77/+149、Task 7 的 +47/+16）；两条并行分支合并时**重新测量整棵树**而非相加（"Merged 2026-09-07: 两分支并行抬升本表…是重新测量的合并树"），防止 ceiling 被复制而非实测 |
| K-EX06 | M-EX03 信号侧规则删掉 H-001 的"换手下降"腿而 RISK-EX01 说"含换手"；M-EX01 无基线无失败动作、机械偏向早退出 | P2 | 接受。M-EX03 明写"换手允许上升 ≤ 25%、成本占毛利 ≤ 15%"并说明偏离 H-001 的理由（退出规则按构造增换手）；M-EX01 基线 = GAP-EX01，失败动作 = 留存比升而 Sharpe 降 → 不采纳 | **CLOSED — 已成过去式（moot）+ 另一半已交付**：换手条款是为 O-EX1 的 dwell 参数写的，该参数从未实现，条款无对象可用；M-EX01 基线那一半已在本次结项测得（§4.4），GAP-EX01 关闭 |
| K-EX07 | E-EX14 的 7 个配置在实盘 60 bar 上重放**未入 ledger**，违反"每个诊断配置计入 prior-trials"；分析自己做了它警告的事的第一步 | P1 | 接受为治理问题。作者不擅自写共享 ledger：交操作者二选一——补记（tsmom + flow 各 7 行，param_key 含 exits 设置，range = 实盘窗）或书面豁免"≤ N bar 的描述性实盘重放不计费"写入 RESEARCH_LOG。E-EX14 已改 E5 | **CLOSED — 操作者裁定**：Q4=B，`docs/RESEARCH_LOG.md`"规则：短窗描述性实盘重放不计费"一节写入豁免条款（窗口 ≤100 bar、标 E5、不得用于选参数） |
| K-EX08 | 基差风险应看尾部而非中位；O-EX1 对基差免疫未作为优点写入 | P2 | 接受。RISK-EX02 改用 p99/最大值；O-EX1 加"免基差" | **仍 OPEN — N/A-until-adoption**：\|基差\| p99 223bps / 最大 271bps 是给"被采纳的价格路径候选"用的实盘触发率 falsifier；P22/P22b 里没有任何价格路径候选被采纳（TP3/4/current/regime 全 REFUTED），falsifier 没有对象可挂，留 OPEN 到下次有候选被采纳为止 |
| K-EX09 | 受损方补偿不对症（操作者三天内两次要求保护性退出，两次被"证据"顶回）；Q-CRITICAL 诱导且与 50% 预算重复；输出缺明确否定句 | P1 | 接受。§12 加 (a) 明确否定句与原因；(b) 结构事实；(c) 中性二选一（exit overlay 是主动 P&L 机制还是灾难后备）；(d) 风险偏好问题改为不预设答案的表述 | **CLOSED — 文档已改**：§12 现有明确否定句（"这次不上线"段）与中性 Q1 措辞，写下时即已生效 |
| K-EX10 | §3 把 09-04 全平记为"绕行"；RESEARCH_LOG:856 记录为"手动平掉全部仓位后重启做检验" | P2 | 接受，已核对原文。改写为"操作者具备随时手动平仓的绕行能力，本次未使用" | **CLOSED — 文档已改**：§2.1 现文本即为改写后版本，写下时即已生效 |
| K-EX11 | E-EX13 幸存者 18 币标 E1；"三轮一致"是同一数据三次重分析；E-EX02 与 E-EX02b 快照不一致（−35 vs −65 U） | P2 | 接受。标注修正；两个快照并列并注明时间 | **CLOSED — 文档已改**：§3.1 E-EX02/E-EX02b 并列且各标时间戳，写下时即已生效 |
| K-EX12 | M-005 反事实作为"实盘裁决者"不可用：事件率 ≈ 2/周，30 天 n≈8；三次承诺未实现 | P1 | 接受。M-005 降为**监测**；裁决权留在 D-017 双 universe 回测；实装时写明预期事件率与 time-to-decision（0.5σ 效应、t=2 需 n≈16 ≈ 2 个月） | **CLOSED — 已交付**：`exit_counterfactuals`（`starquant_live/reports.py`）以监测形态实装，携带 `n_needed_for_decision`；日报段 "Exit counterfactuals (M-005, monitoring only)" |
| K-EX13 | O-EX2 用 90 日中位切 regime → 按构造约一半时间"低 ER"；"两臂都过即噪声"混淆"regime 无关"与"TP3 处处有效"；ER 参数无先验 | P1 | 接受。固定 ER 阈值（§6.3 已改）；加固定 TP3 臂；判定改 2×2（基线 / 固定 / regime 臂 / 镜像臂） | **CLOSED — 新证据**：P22b 用固定常数（168 bar、0.05）执行了 2×2（低 ER 臂 + 镜像臂 + 已有的固定 TP3 臂），C-EX02b → REFUTED |
| K-EX14 | 任何采纳 = 构造变更 = M-010 清零（当前 4.6 天）；无"最短干净窗口"规则 | P2 → 人类确认点 | 接受为建议规则：M-010 未满 30 天连续构造前不采纳任何退出/信号改动，除非 P13 阶梯触发；由操作者确认 | **CLOSED — 操作者裁定**：Q6=A，`docs/RUNBOOK.md`"采纳 exit overlay/信号改动的最短干净窗口"一节写入该规则 |

### 8.3 Pre-Mortem 与 Inversion（审查者产出，压缩）

最可能的失败：① 操作者按 E-EX14 的 +20 U 把 TP 调到 2–3σ 并重启（3 天噪声调参）；② O-EX1 以"默认即现状"上线，实际 dwell 有限，重启后书开始按次阈值平仓（D-042 形态）；③ O-EX2 镜像臂双通过被判"噪声"，实际是 TP3 处处有效，把 F1 的真发现记成 Won't；④ **受损方**操作者两次要求被顶回、失去对 exit overlay 信任 → 手动干预；⑤ M-005 实装后 n≈8 无法裁决，"实盘会裁决"成为永久挡箭牌；⑥ 在 0.15 证据上采纳 0.30 的书的改动；⑦ 非 alpha 行数捆绑越线。Inversion 里"当前已部分存在"的三项：E-EX14 已算未入账；O-EX1 默认值规格错误；缺固定 TP 臂。全部已进入上表的关闭路径。

### 8.4 G6 与 Final Kill Decision

**G6：**~~PARTIAL~~（无 OPEN P0；9 个 P1 各有明确触发动作，其中 K-EX04/05/09/13 与全部 P2 可通过改写产物关闭——本文已改写；K-EX01/02/03/07/12 需要新证据——运行扩格、描述统计、0.30 重跑、 ledger 处置、事件率估算）。**【结项】PASS**——P22（K-EX01/03）、P23 第 0 步（K-EX02）、P22b（K-EX13）、DL-EX0b（K-EX12）四条需新证据的 P1 均已关闭（§8.2 终态列）；K-EX07/K-EX14 由操作者裁定关闭；K-EX04/K-EX06 因 O-EX1 的信号侧参数从未实现而成过去式；K-EX05 缓解；K-EX09/10/11 的文档改写写下时即已生效。**唯一仍 OPEN 的是 K-EX08**（P2，N/A-until-adoption：无价格路径候选被采纳，尾部 falsifier 没有对象可挂）——不构成 P0/P1 OPEN，G6 判 PASS。

**Final Kill Decision：PIVOT**，与作者用词一致但内容不同：作者的 PIVOT 是"转向信号侧优先"；审查后的 PIVOT 是"**先用最少名额把操作者的字面问题（止盈 <6σ 固定档）测掉并作为 regime 实验的对照，再决定信号侧**"。KILL 不适用（目标与感知→干预风险真实存在）；Need Evidence 不适用（UNKNOWN 的是 P1 Claim，H2 先于 H3）。命中 H2；未命中 H1/H3/H4/H7/H8。**【结项】这条 PIVOT 已执行完毕**：字面问题测掉了（P22，REFUTED），regime 实验的对照也用上了（P22b，REFUTED），信号侧也测了（P23 第 0 步，REFUTED）。三侧都测完之后，落点不是"转向某一侧"，而是三侧都不动、 exit overlay 维持现状——PIVOT 一词的最终含义收敛为"诊断被推翻、诉求被验证性地否定"。

人类确认点（D.8）：① 每个实验的 ledger 名额；② 任何进 live 的改动（registry/config + 重启 + M-010 清零；启动演练必须换 `state_dir`）；③ E-EX14 补记或豁免；④ KILL-R12 ceiling；⑤ 风险偏好（按 K-EX09 中性表述）。**【结项】五项均已过**：①③④⑤见 §12 对应 Q3/Q4/Q5/Q1 的回答；②本分支未采纳任何退出/信号候选，故没有"采纳"意义上的 live 改动——只有 `unit_mode` 这一只读参数的默认值上线，逐位不变行为，但按 D-026 规则构造指纹仍记录了变化（见 RESEARCH_LOG"记录：`unit_mode` 改了构造指纹"一节），M-010 窗口按规则清零。

---

## 9. Phase 8 · Scope & Priority

| 分类 | 内容 | 理由 |
| --- | --- | --- |
| Must | O-EX0（日报噪声尺度行）、O-EX0b（M-005 反事实）；本文入库 | 零交易影响；补上裁决者 |
| Should | O-EX1 预登记 + 实现 + 一次 validate | 先验最高、成本最低、在 alpha 侧 →**【结项】预登记 + 描述统计已做（P23 第 0 步），不显著，停在此步，"实现 + validate" 从未发生** |
| Could | O-EX2 三臂（操作者点头） | 回应原意；先验低 →**【结项】已跑（P22b），REFUTED**。**来源更正**：不是 Q1 改判为 A——操作者对 Q1 的回答始终是 B（灾难后备）。本项与 O-EX1 是在其后一条独立指令下解锁的：「与执行优化方案进行对比……完善所有的任务，不要有遗漏」。即在 Q1=B 的前提下仍把两个条件任务跑完，以消除「没测过」这个状态本身 |
| Won't | 固定收紧 / 移动止损；滚动锚；组合层 regime 标量；原生单；按 E-EX14 调参；在批准前跑任何计费实验 | 见 D-EX00/D-EX01 与 E-EX17 |

Scope Firewall：Out-of-Scope 项加入后挤出的是 ledgerheadroom 与实盘证据窗口——两者都是不可再生的。

Decision Compression：一句话问题 = "盘整期浮盈回吐、 exit overlay 零触发，是否该让止盈止损随行情自适应"；核心用户 = 单一操作者；推荐 = 不动 exit overlay + 给尺度 + 两个先写后跑的实验；In = 上表 Must/Should；Out = Won't；关键 Claim = ~~C-EX01 REFUTED、C-EX02b UNKNOWN、C-EX03 PARTIAL~~ **【结项】C-EX01 REFUTED（不变）、C-EX02a-TP/02b/02c/03 全部 REFUTED（见 §3.2）**；关键 Risk = RISK-EX06；成功 Metric = M-EX01/M-EX03/M-005。

---

## 10. Phase 9 · Delivery Contract 与 Source Trace

责任模型（单人项目）：操作者 = Business / Approval / Runtime / Learning Owner；Agent = Engineering / Test 执行者，**只在操作者批准后动手**；任何 live 改动、任何计费实验都是人类确认点。

### 10.1 Delivery Items

| DL | 内容 | 文件 | 测试 | 验收 | Metric |
| --- | --- | --- | --- | --- | --- |
| DL-EX0 | 日报新增 "Noise scale" 段：设计日 σ = `vol_target/√365 × equity`（U）；今日峰值回吐（U）及 /σ；退出触发期望（1.9/周 × 天数）vs 实际 | `starquant_live/reports.py` | T-EX0-1 用 cycles 夹具算出 σ 与回吐；T-EX0-2 无周期时不崩 | AC-EX0：日报出现该段，数字与手算一致 | M-EX04（观测项，无阈值） **【结项：已交付】** |
| DL-EX0b | M-005 反事实（**监测**，非裁决，K-EX12）：对每个 `exit_events`，在 +24/+72 bar 读 mainnet 收盘，算 `sign × 权重 × 权益 × 收益` 与省下成本；日报汇总均值、n 与"距可裁决所需 n"（0.5σ 效应、t=2 需 n≈16 ≈ 2 个月） | `starquant_live/reports.py`（**live ≈50 行**，与 DL-EX0 合计 ≈70，K-EX05） | T-EX0b-1 合成一次退出事件 → 反事实数值正确；T-EX0b-2 未满 72 bar 标 pending | AC-EX0b：首个真实退出事件后 72h 日报有数 | M-005 **【结项：已交付**（实测合计 ≈149 行 live，非估计的 ≈70，见 K-EX05）**】** |
| DL-EX1b **[C 修订]** | 固定止盈扩格：预登记提交（网格与规则）早于运行；`research overlay --universe pit` 与 `static`，`--exits-grid '{"stop_loss":[6],"trailing_stop":[0],"take_profit":[3,4,6],"unit_mode":["entry","current"]}'` 中只跑新候选（TP3-entry、TP4-entry、TP6-current）；判定按 §11.2 | `docs/RESEARCH_LOG.md`（预登记）；`overlays/exits.py` 加 `unit_mode`（alpha ≈10 行，为 O-EX7） | T-EX7-1 `unit_mode=entry` 逐位等价现状 | AC-EX1b：两份报告落盘，ledger tsmom + flow 各 +6，判定写入 RESEARCH_LOG | M-EX03 **【结项：已交付并裁决**（P22，三个新候选全 REFUTED，ledger 实际各 +10 含节流重跑，见 RESEARCH_LOG）**】** |
| DL-EX1（条件） | 先做描述统计（次阈值持有段 vs 可执行段的前瞻收益，计 1 个 prior trial，K-EX02）；若方向支持，再实现 `scores_to_targets` + `exit_threshold` / `exit_dwell_bars`（**默认 None / 0 = 关闭**，K-EX04）；registry 读取；**预登记提交先于运行**；`research validate` 两格；按 §11 规则裁决 | `starquant_alpha/signals/base.py`、`registry.py`、`model.py`、`docs/RESEARCH_LOG.md` | T-EX1-1 默认参数逐位等价现状（X-EX1）；T-EX1-2 dwell 语义（X-EX2/3）；T-EX1-3 live 窗口重建（X-EX4）；T-EX1-4 因果性 | AC-EX1：报告落盘、 ledger +1（描述统计）+2（网格）、判定按预登记规则写入 RESEARCH_LOG | M-EX01/M-EX03 **【结项：条件不成立，停在描述统计**（P23 第 0 步，方向不支持，t=0.92<2.0）**；"再实现" 那半句从未发生，`scores_to_targets` 的两个新参数、registry 读取、validate 网格均未写，ledger 只记了 +1 诊断行**】** |
| DL-EX2（条件） | `exit_step` 加 `k_scale`；`ExitOverlay` 算 ER_168 与固定阈值；overlay 网格三臂；预登记先于运行 | `overlays/exits.py`、`starquant_live/exits.py`、`research_cmd.py` | T-EX2-1 `k_scale=1` 逐位等价；T-EX2-2 研究/实盘同 regime（固定阈值）；T-EX2-3 不可触发币-bar 单独计数（X-EX6） | AC-EX2：四份报告（三臂 × 双 universe 中的时点/静态各一）+ 判定 | M-EX03 **【结项：已交付并裁决**（P22b，`regime_tp_scale`/`efficiency_ratio` 已实现，2×2 跑了两个新臂 + 复用已有的固定 TP3 臂，C-EX02b REFUTED）**】** |

### 10.2 Source Trace

| DL | Problem | Evidence | Claim | Decision | Gate/Kill | Scope | Test/AC | Metric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DL-EX0 | §4.1 缺尺度 | E-EX05/07 | C-EX04 | D-EX01 | G5 PASS | Must | T-EX0-*/AC-EX0 | M-EX04 |
| DL-EX0b | §4.1 缺裁决者 | E-EX16 | C-EX05 | D-EX01 | G5 PASS | Must | T-EX0b-*/AC-EX0b | M-005 |
| DL-EX1b **[C 修订]** | Pre-EX1（操作者字面问题）、K-EX01 | E-EX07（网格 TP ∈ {0, 6}）、E-EX09、E-EX15 | C-EX02a-TP、C-EX02c | D-EX01 | H5 → 受控实验；G6 K-EX01/K-EX03 的关闭条件 | Should（第一个实验） | T-EX7-1 / AC-EX1b | M-EX03 |
| DL-EX1 | §4.2 杠杆 (b) | E-EX09/10/12/13 | C-EX03 | D-EX00/01 | H5 → 受控实验；K-EX02/K-EX04 | Could（描述统计之后） | T-EX1-*/AC-EX1 | M-EX01/03 |
| DL-EX2 | Pre-EX2 | E-EX07/09/11/15 | C-EX02b | D-EX01 | H5 → 受控实验；K-EX13 | Could（DL-EX1b 之后） | T-EX2-*/AC-EX2 | M-EX03 |

Delivery Gate：DL-EX0/0b 无交易与 ledger 影响，但合计 ≈70 行 live 触及 KILL-R12 的 ceiling，需操作者裁定（§12 Q5）后实现；DL-EX1b 需操作者确认 ledger 名额（Q3）；DL-EX1/DL-EX2 需各自的前置结果与再次确认。每一步都是人类确认点。**【结项】全部五项均已走完各自的人类确认点**：Q5 抬了 ceiling（DL-EX0/0b 实装）；Q3=是（DL-EX1b 跑了）；DL-EX1 的前置结果（描述统计）不支持，条件款未打开；DL-EX2 的前置（DL-EX1b 出结果 + 操作者点头）成立，跑了且 REFUTED——**点头的形式是「完善所有的任务，不要有遗漏」这条指令，不是 Q1 改判**，Q1 的回答仍是 B。没有任何一步跳过确认直接执行。

---

## 11. Phase 10 · Learning Plan

### 11.1 Validation Plan

| Metric | Claim | 基线 | 成功阈值 | 护栏 | 窗口 | 停止条件 / 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| M-EX01 留存比 | C-EX03 | ~~**待测**（GAP-EX01：当前构造回测按持仓段计算）~~ **【结项】已测**：`scratchpad/m_ex01_retention.py`，见 §4.4 的数字（两 universe 中位留存比均为负） | O-EX1 候选中位留存比 > 基线 | M-EX03 | 回测即得；实盘按已平仓段累计 | 若留存比升而 Sharpe 降 → 砍赢家，不采纳。**【结项】此阈值从未被检验**：O-EX1 在 P23 第 0 步就停，没有产生候选可与基线比较；本次测得的是基线本身，供以后任何退出侧改动比较用 |
| M-EX03 护栏 | C-EX02b/03 | 当前构造 OOS Sharpe / MDD（validate 与 overlay 的各自基线） | 见 11.2 规则 | — | 回测 | 不通过 → 记负结果，不扩网格。**【结项】已发生**：P22（C-EX02a-TP/02c）与 P22b（C-EX02b）均不通过，均记负结果，均未扩网格 |
| M-005 | C-EX05 | 回测期望 1.9 次/周；实盘 0 | 反事实均值 ≤ 0（退出后 24/72h 若持有会更差或持平） | — | 滚动累计；**[C 修订，K-EX12]** 30 天只有 n≈8，不足以裁决；0.5σ 效应、t=2 需 n≈16 ≈ 2 个月 | 只做监测与告警；exit overlay 的裁决权留在 D-017 双 universe 回测；n 达标且反事实均值 > 0 且 > 成本 → 触发一次 D-017 重跑，而不是直接关规则 |
| M-EX02 = M-010 | 全部 | 日报 | 不变 | — | 30 天 | 不变 |

### 11.2 Experiment Design（先写后跑；规则写在这里，数字出来后不改）

| Experiment | 要证伪的 Claim | 方法 | 变量 / 对照 | 通过阈值 | 停止 / 局限 |
| --- | --- | --- | --- | --- | --- |
| EXP-EX1（条件：描述统计先行） | C-EX03（信号衰减退出有益） | **第 0 步（计 1 个 prior trial，K-EX02）**：在当前构造回测上按持仓 bar 分组——可执行段（\|score\| ≥ 0.20）vs 次阈值持有段（< 0.20）——比较前瞻 24/72h 收益的均值与 t；若次阈值段前瞻收益不显著低于可执行段，**停止，不实现 O-EX1**。第 1 步：`starquant research validate --strategy tsmom --universe pit --grid '{"exit_threshold":[0.10],"exit_dwell_bars":[24,72]}'`，其余参数 = 当前 registry；申报先验试验 = ledger 当前 tsmom 行数；再在静态 universe 复核方向 | 基线 = 当前配置（exit_threshold None / dwell 0，即次阈值无限期持有） | 采纳当且仅当（时点）：OOS Sharpe ≥ 基线 −0.05 **且** OOS MDD 改善 ≥ 0.5pp **且** 逐 bar 净收益差的 NW t ≥ −1.0 **且** M-EX01 中位留存比改善 **且** 换手上升 ≤ 25% 且成本占毛利 ≤ 15%；（静态）ΔOOS Sharpe ≥ 0。两格都不满足 → C-EX03 REFUTED，不再扩网格 | 5 fold purged WFO，min_train 4000；效应可能在噪声量级（单个 Sharpe 年化标准误 ≈0.43）；优点：对 demo/mainnet 基差免疫。**【结项】第 0 步已跑**（`scratchpad/p23_subthreshold_forward.py`）：h=72 diff t=+0.92，**停止条件触发**，第 1 步（validate 两格）从未运行，C-EX03 REFUTED |
| EXP-EX2（条件：EXP-EX1b 之后、操作者点头） | C-EX02b（行情切档有益） | 实现 `k_scale`；`research overlay --universe pit` 与 `static`，**2×2**：基线 6/6、固定 TP3（取 EXP-EX1b 结果，不重跑）、低 ER（ER_168 < 0.05）才 TP3、高 ER（≥ 0.05）才 TP3（镜像） | 基线 = 无叠加；对照 = 固定 TP3 | 采纳当且仅当：低 ER 臂双 universe 通过 D-017 **且** 双 universe OOS Sharpe 都高于固定 TP3 臂 **且** 镜像臂至少一个 universe 不通过。**[C 修订，K-EX13]** 若低 ER 臂与镜像臂都通过且都不优于固定臂 → 结论是"TP3 处处有效"（属 C-EX02a-TP，非 regime 效应）；都不通过 → C-EX02b REFUTED | 两个 regime 臂 × 两 universe → tsmom + flow 各 +4；ER 阈值 0.05 与窗口 168 是预登记常数（BTC 7d 当前 0.020，30d 0.118），只允许这一组，不按结果调。**【结项】已跑（P22b）**：低 ER 臂静态通过/时点不通过，镜像臂时点通过/静态不通过，两臂从未同时双通过——落在预登记规则"其余情况"分支，C-EX02b REFUTED |
| **EXP-EX1b + EXP-EX3（合并为第一个实验，[C 修订]）** | C-EX02a-TP「固定止盈 3σ / 4σ 双通过 D-017」；C-EX02c「以当前波动为单位的退出优于以入场波动为单位」 | 实现 `unit_mode`（≈10 行）；预登记提交后一次运行：`research overlay --universe pit` 与 `--universe static`，网格 `stop_loss [6] × trailing_stop [0] × take_profit [3, 4, 6] × unit_mode [entry, current]`，只对三个新候选（TP3-entry、TP4-entry、TP6-current）做判定；TP6-entry = 现行，作为对照重算 | 基线 = 无叠加（D-017 口径）；对照 = 现行 6/6-entry | **固定 TP**：采纳当且仅当该档双 universe 通过 D-017 **且** 双 universe 的 OOS Sharpe 都不低于现行 6/6-entry −0.02 **且** 触发次数 ≤ 现行的 3 倍。**current 单位**：采纳当且仅当双通过 D-017 **且** 双 universe 的 OOS MDD 不差于现行 **且** 触发次数 ≤ 3 倍。任何不满足 → 对应 Claim REFUTED，记负结果，不扩网格 | 三个新候选 × 两 universe → tsmom + flow 各 +6；现行 6/6 在 0.30 构造上顺带重跑（关闭 K-EX03 的采纳前提）；先验：TP3/4 为负、current 不确定；这是回答操作者字面问题最便宜的一次运行。**【结项】已跑（P22）**：TP3-entry 静态 Sharpe 损失 0.1736>0.10；TP4-entry 静态 MDD 未改善；TP6-current 双 universe MDD 均未改善。三者均不满足采纳条件，C-EX02a-TP 与 C-EX02c 均 REFUTED；TP6-entry 在 0.30 上重跑双通过，关闭 K-EX03 |

### 11.3 Post-Launch Review 与分析校准

Post-Launch：每个实验出结果后在 `docs/RESEARCH_LOG.md` 记一节（与 P11 同格式），无论正负。**【结项】已按此执行**：P22、P22b、P23 各有一节，均含裁决。分析校准：本文的可证伪判断有三条——① "回吐在噪声内"（若 30 日实现波动落在 [0.26, 0.38] 带内则成立，本次结项未复核，需 240 bar，见 E-EX05，留给该窗口满足时核对）；② "信号侧退出比价格侧更有希望"（EXP-EX1 vs EXP-EX2 的结果——**结项复核**：信号侧（O-EX1/EXP-EX1）在最便宜的第 0 步就停，价格侧（O-EX2/EXP-EX2）跑到完整 2×2 才被拒，"更有希望"没有体现在两者实际测到的深度上，此条不算获得支持）；③ "regime 切档会退化为移动止损"（EXP-EX2 (ii) 与 (iii) 同过或同不过——**结项复核**：预设的触发条件未按字面发生，P22b 的两臂不是同过或同不过，而是各自只在一个 universe 通过；C-EX02b 落在判定规则的"其余情况"分支而非"两臂同结果"分支，结论方向仍一致（REFUTED）但字面条件没对上）。三条中两条（②③）字面上都不算"确认"，这类"方向对、字面条件没触发"本身就是下面 `analysis-calibration.md` 要记的一类教训。该文件**已创建**（见 `docs/analysis/analysis-calibration.md`）。同时建议操作者用本文 §2.5 的答案生成一份 `deep-analysis-constitution.md`：战略（demo 上持续盈利证据优先、≥90% alpha）、硬约束（50% 回撤预算、D-017/D-020、KILL-R12 行数、 ledger 计费、 holdout = 实盘期）、决策人（操作者）——这些每次分析都在重问。**【结项】此建议未在本次执行**：不在本次结项任务范围内，留给操作者或下次分析。

---

## 12. Final Decision

**PIVOT**（命中 H2；实验分支另受 H5；G6 ~~PARTIAL，P0 0 / P1 9，全部有关闭路径~~ **【结项】PASS**，见 §1/§8.4）。

**【结项，2026-09-07，P22 + P22b + P23 之后】** 下面 Q1–Q6 六个问题已全部回答，答案与证据见本节后段的表；四个此前 UNKNOWN 的 Claim 已全部 REFUTED（§3.2）；`config/live.demo.yaml` 未改一个字符。

**[C 修订，K-EX09] 先把不做的事说清楚**：你要的"随行情自适应的止盈止损"**这次不上线**，原因有三：(1) 这次回吐是设计内噪声，不是任何规则失效（+329 → +264 U = 0.4 个设计日 σ）；(2) 已测过的收紧方向——止损 2.5/4σ、移动止损 4σ——在 5.6 年两个 universe 上全部毁值；(3) 没测过的方向（止盈 3/4σ、当前波动单位、行情切档、信号衰减）没有任何一条可以在"没跑过回测"的情况下进 live——这是 D-017 的规则，也是本书至今所有改动的规则。三条结构事实一起看：BTC 的 6σ 止盈在 +14.3%、AKE 的 6σ 止损价是负数、整本书回测里 exit overlay 每周才触发 1.9 次——**现行 exit overlay 按构造就是一个几乎不触发的灾难后备，而不是主动的 P&L 机制**，它被装上去的理由是"操作者要求带止损、且这一档免费"（P11 原话），从来不是"它保护了什么"。

- **对观察**：+329 → +264 U 的回吐是 `vol_target 0.30` 下的设计噪声；exit overlay 零触发是按构造；两者都不是故障。
- **对命题**：作为诊断不成立；作为诉求，**[C 修订]** 未测的部分比初稿写的多——止盈 <6σ 从未进过网格。**【结项】现在这句话要再往前一步：未测的部分已经测完，四个此前未测的方向（止盈 <6σ、当前波动单位、行情切档、信号衰减）全部 REFUTED，不再有"未测"的分支剩下——诉求不但当时不成立，测完之后仍然不成立。**
- **现在做什么**：不改配置；实装日报噪声尺度行与 M-005 监测（≈70 行 live，需 Q5）。**【结项】已实装**（DL-EX0/DL-EX0b，实测 ≈149 行 live，见 K-EX05）。
- **第一个实验（需 Q3）**：一次 `research overlay` 跑三个新候选——固定止盈 3σ、4σ、当前波动单位 6/6——双 universe D-017，顺带把现行 6/6 在 0.30 构造上重跑。它同时回答你的字面问题、给 regime 实验提供对照、关闭 K-EX03。**【结项】已跑（P22）**：三个新候选全部 REFUTED；TP6-entry 在 0.30 上双通过 D-017，K-EX03 关闭。
- **之后**：按结果与你的意愿决定 O-EX2 的 2×2 与 O-EX1 的描述统计→validate。任何采纳都要：0.30 上双 universe 通过 + 你批准 + M-010 满 30 天（若接受 Q6）+ 重启并记构造变更。**【结项】两者都已发生**：O-EX2 的 2×2 已跑（P22b，REFUTED）；O-EX1 的描述统计已跑（P23 第 0 步，不显著，未进入 validate）。没有候选通过 D-017，因此"任何采纳都要…"这一串条件从未被触发——不是被跳过，是没有对象需要它们。

**什么才算"异常"（给操作者的尺度，替代凭感觉）**：

| 信号 | 阈值 | 现状 |
| --- | --- | --- |
| 单日权益回吐 | > 2 个设计日 σ ≈ 350 U | 66 U（24h 最大） |
| 自 HWM 回撤 | 触及 P13 阶梯 −35% | 日报读数 1.23%，风险预算状态 OK（03:00Z 权益对 HWM 为 −0.32%） |
| 退出触发频率 | ≫ 1.9 次/周（如一周 > 8 次） | 0 |
| 30 日归因 Sharpe（M-010） | z 显著低于预期 | INSUFFICIENT_DATA（需 30 天） |
| 目标方向翻转 | 一周内同一币 ≥ 4 次翻转（震荡税） | 1000PEPE 3 次、TRUMP 5 次（重置后 3 天）——这才是本次真实的"震荡成本"，发生在信号层 |

**需要你决定的六件事（一次问完，3.2 格式；[C 修订] Q1/Q2 按 K-EX09 改为不预设答案的表述）**：

| Q | 问题 | 关联 | 若 A | 若 B | **回答（结项）** |
| --- | --- | --- | --- | --- | --- |
| **Q1（CRITICAL）** | 你希望 exit overlay 扮演哪个角色？A：**主动的 P&L 机制**（更紧的止盈 / 移动止损，代价是历史上每档移动止损 −0.15～−0.22 OOS Sharpe，且任何新档都要先在 0.30 上过 D-017）；B：**灾难后备**（现状：几乎不触发，保费≈0） | Pre-EX3 / C-EX02a / D-EX00 | A → 第一个实验（Q3）成为必做项，并把 O-EX2 排进队列 | B → exit overlay 不动，只做 DL-EX0/0b；实验按 Q3 可选 | **B（灾难后备）**，且现在有证据支持而不只是偏好：见下方"更正"引用的尺度不变性——exit overlay 在两个风险目标（0.15、0.30）上都稳定削掉基线回撤的 4.5–6.3%，而 Sharpe 效应跨 universe 翻号（`docs/RESEARCH_LOG.md` P22"更正"节）。**核对说明（写下来而不是抹掉）**：`.superpowers/sdd/2026-09-07-exits-optimization-execution-plan/task-7-brief.md:3` 与 `task-8-brief.md:3` 记的前置条件是"Q1 = A"——这是解锁 Task 7（regime 2×2）与 Task 8（信号侧描述统计）时用的操作性许可（"去测测看能不能做成主动机制"），不是这里的最终定性。三个方向（固定止盈、regime 切档、信号衰减）测完后全部 REFUTED，没有一个"主动 P&L 机制"候选存活，本节记的是收尾时的最终答案：B。这两处记录是同一决策在两个时间点的状态，不是自相矛盾 |
| **Q2** | 你希望这本书的权益**每天**正常摆动多少 U？现在的设计是约 ±170 U（`vol_target 0.30`，对应 50% 回撤预算，自助 q95 −44%～−50%）；如果你想要的是约 ±85 U，那是 `vol_target 0.15`（预算约 25%） | A-EX01 / E-EX18 / O-EX5 | ±170 U → 本文结论成立 | 更小 → 议题是重开 P13 的预算声明并降 `vol_target`，与 exit overlay 无关 | **A（≈±170 U 被接受）**：`config/live.demo.yaml` 的 `vol_target` 结项时仍是 **0.30**，未降为 0.15，P13 预算声明未重开 |
| Q3 | 是否用 tsmom + flow 各 6 个 ledger 名额跑第一个实验（固定 TP 3/4 + 当前 σ 单位，双 universe）？ | C-EX02a-TP / C-EX02c / RISK-EX03 | 是 → DL-EX1b 预登记后运行 | 否 → 三个 Claim 保持 UNKNOWN 并记录；exit overlay 维持现状 | **是**——`docs/RESEARCH_LOG.md`"P22 预登记"节原话："操作者对 Q3 的回答：是。"ledger 实际各 +10（含节流重跑去重，高于预估的各 +6，见 P22 裁决节） |
| Q4 | E-EX14 的 7 个实盘重放配置：A 补记 ledger（tsmom + flow 各 7 行）；B 书面豁免"≤ 100 bar 的描述性实盘重放不计费"写入 RESEARCH_LOG | K-EX07 / KILL-006 | A → 作者补记 | B → 作者写入豁免条款 | **B（豁免）**——`docs/RESEARCH_LOG.md`"规则：短窗描述性实盘重放不计费"一节：窗口 ≤100 bar、必须标 E5 并写明 n、不得据此改配置，超限即按诊断试验计费 |
| Q5 | DL-EX0 + DL-EX0b ≈70 行 live 顶在 KILL-R12 的 ceiling 上：抬 ceiling，还是指名同量级删除，还是不做？ | K-EX05 / RISK-EX04 | 抬或删 → 实现 | 不做 → 噪声尺度只留在本文 §12 的表里 | **A（抬 ceiling）**——`tests/architecture/test_source_budget.py` 的 CEILING 抬升历史：DL-EX0/0b 一条 "+77 in starquant_live and +2 in starquant_cli for two observations the exits analysis found missing"（实测 +149，非估计的 +77，差额已在同一文件下一条注释里说明原因），带规则要求的理由句 |
| Q6 | 是否接受规则"M-010 未满 30 天连续构造前，不采纳任何退出 / 信号改动，除非 P13 阶梯触发"？ | K-EX14 / RISK-EX08 / KILL-006 | 接受 → 写入 RUNBOOK | 不接受 → 每次采纳单独裁定，本文记录残余风险 | **A（接受）**——`docs/RUNBOOK.md`"采纳 exit overlay / 信号改动的最短干净窗口（K-EX14，2026-09-07 操作者裁定）"一节，规则原文已写入 |

Checkpoint（写下时，先于结项）：等级 L / Yellow；Phase 1–6 冻结于 `scratchpad/exits-adaptive-frozen.md`（冻结版保留原样，含被审查推翻的表述，用于复核）；Phase 7 = §8，G6 PARTIAL（P0 0 / P1 9 / P2 5，全部 OPEN 并有关闭路径）；D-EX00、D-EX01 按 **[C 修订]** 标记处改写；**冻结后追加**：O-EX7/O-EX8、EXP-EX3、附录 A（回应操作者"量化领域在用哪些止盈止损方法"的追问，不在子代理审查范围内）；开放 Claim C-EX02a-TP / C-EX02b / C-EX02c / C-EX03（均 UNKNOWN）；开放 Gap GAP-EX00/01/02 + E-EX14 ledger 处置；待决 Q1–Q6；下一动作 = 操作者回答后：Q5 通过 → DL-EX0/0b；Q3 通过 → DL-EX1b 预登记提交 → 一次 overlay 运行 → 判定写入 RESEARCH_LOG → 再议 O-EX2 / O-EX1。本文与冻结文件均未提交到 git，未改任何配置，未写 trials ledger。

**Checkpoint（【结项】，2026-09-07，P22 + P22b + P23 之后）**：等级 L / Yellow；G6 由 PARTIAL 转 **PASS**（P0 0 / P1 9，8 条 CLOSED + 1 条 MITIGATED；P2 5 条全 CLOSED；K-EX08 P2 仍 OPEN，N/A-until-adoption，见 §8.2/§8.4）；此前开放的 Claim C-EX02a-TP / C-EX02b / C-EX02c / C-EX03 **全部 REFUTED**（§3.2）；GAP-EX00/01/02/03 全部关闭（§3.4）；E-EX14 ledger 处置由操作者裁定为豁免（Q4=B）；Q1–Q6 全部已答（本节表）。下一动作：**没有**——四个假设测完全 REFUTED，没有候选通过 D-017，因此没有"采纳"这一步可走；`config/live.demo.yaml` 的 `exits` 块未改一个字符；`unit_mode` 这一只读参数已上线（默认值使行为逐位不变），M-EX01 基线已测得（`scratchpad/m_ex01_retention.py`，见 §4.4）。本次结项改动的文件只有四个：本文档、`docs/analysis/analysis-calibration.md`（新建）、`scratchpad/m_ex01_retention.py`（新建）与 `scratchpad/exit_reachability.py`（新增两个字段）；未改任何配置，未写除 M-EX01 描述性测量（不计费）以外的 trials ledger。

---

## 附录 A · 量化领域在用的退出方法，以及它们在这本书上的适用性（冻结后追加，回应操作者追问）

> 文献部分为作者记忆中的公开研究与实务书籍（E3/E4），本次未逐篇重新核对原文；StarQuant侧的数字全部是本文正文的 E1 证据。

### A.1 一个统一的判据：退出规则在哪个时间尺度上触发，那个尺度的收益自相关是正还是负

Kaminski & Lo (2014, *When do stop-loss rules stop losses?*) 与 Lo & Remorov (2017) 的结论可以一句话概括：**止损/移动止损的"止损溢价"在收益正自相关（趋势延续）的尺度上为正，在负自相关（均值回归）的尺度上为负，在随机游走下等于放弃在场外期间的风险溢价再扣成本。** 因此"该不该用移动止损"没有通用答案，答案取决于两件事：规则在什么尺度上触发；那个尺度上标的的自相关是什么符号。

StarQuant自己测过这两件事（E-EX09）：本 universe 1–24h 前瞻 IC 显著为负（反转），周级为动量。于是任何在 ≈1 个日 σ 距离、逐小时评估的价格路径退出，都在替对手方止损；而周级尺度的退出，就是信号翻转本身。P11 三轮的结果（止损 2.5/4σ 与移动止损 4σ 全部毁值，6–8σ 近似免费）与这个判据完全一致，不是巧合。

### A.2 方法清单与适用性矩阵

| 方法 | 做法 | 自适应到什么 | 文献/实务的结论 | 在本书上的状态 |
| --- | --- | --- | --- | --- |
| 固定百分比止损/止盈 | 距入场 ±x% | 不自适应 | 在高低波动资产间不可比，基本已被 ATR/σ 单位取代 | Won't（KILL-R14 也说明了固定距离在 7/18 个币上根本不可下单） |
| ATR/σ 单位止损（Turtle 2N、Carver 的 vol 单位） | 距入场 k × σ | 波动率 | 标准做法；Carver 指出 k 应随**持仓周期**放大：粗略地 σ_1d × √(持仓天数)，慢信号必须用宽止损 | **已有**（6σ_1d ≈ 1–2 周的自然波幅，与周级持仓一致；更紧的档位已被否） |
| 移动止损（Chandelier = 极值 − k×ATR；Parabolic SAR；Donchian 10/20 日低点） | 从有利极值回撤 k 个单位 | 波动率 | Clenow 的分散化期货趋势系统用 3×ATR 日线移动止损；Kaufman 的多数测试显示移动止损**降低**趋势系统收益但降低回撤；效果强烈依赖评估频率（日线 vs 小时） | **已实现、三轮测负**（4σ 逐小时评估，Sharpe −0.15～−0.22 且 MDD 更差）。未测：日线评估、更宽倍数；但 Donchian 20 日低点式退出在周级上与信号翻转几乎等价 |
| 保本止损（浮盈 +kσ 后止损移到入场价） | 混合 | 波动率 | 实务常见；本质是一次性的移动止损 | 未测；先验同移动止损 |
| 固定止盈 / R 倍数止盈 | 距入场 +k × 风险 | 波动率 | Kaufman：止盈**帮助均值回归系统、伤害趋势系统**（趋势利润在右尾） | **已有** TP6，中性（E-EX07）；更紧的 TP 未在 5.6 年上测过，3 天重放（E-EX14）不算证据 |
| 部分止盈（scale-out） | 到 +kσ 平一半 | 波动率 | 降低单笔方差与回撤，通常降低 CAGR | 未测（O-EX8，Won't，重开条件见 §7.1） |
| 时间止损 | 持仓超过 N bar 平仓 | 时间 | 均值回归系统的必需品（Chan）；趋势系统里对应"信号衰减退出" | 均值回归书没有上线；趋势书的对应物是 **O-EX1** |
| 信号衰减/滞回退出 | \|预测\| 跌破退出阈值且停留 N bar | 信号自身 | 连续预测框架（Carver/AHL 式）里"退出"就是预测→0；滞回是常见的降换手手段 | **未测**（O-EX1 / EXP-EX1）。本书现在只在翻转时退出，26.8% 的持仓时间在次阈值持有 |
| 连续预测缩放（forecast-scaled position） | 仓位 ∝ 预测强度 / σ | 信号强度 + 波动 | AHL/Carver 主流；Baltas & Kosowski 用趋势 t 统计量做信号，换手更低 | **测过并否定**（H-001：幅度不携带收益信息，本书按 sign 交易） |
| 波动率目标（vol targeting） | 仓位 ∝ 1/σ，组合 σ 锚定目标 | 波动率 | Moskowitz-Ooi-Pedersen (2012) TSMOM 的内置部件；Harvey et al. (2018)、Moreira & Muir (2017)：对有杠杆效应的风险资产提高 Sharpe、削左尾 | **已有**（半衰期 48h 的 EWMA，波动一升仓位下一轮就缩）。这是文献里证据最强的"随波动自适应"，而且它已经在跑 |
| 动量崩盘保护（Barroso & Santa-Clara 2015；Daniel & Moskowitz 2016） | 用近期已实现波动/熊市指标缩放动量仓位 | 波动 + 市场状态 | 对横截面股票动量大幅降低崩盘 | 波动缩放已有；"熊市状态"缩放未测，属于信号/组合层研究而非 exit overlay |
| 动量组合上的止损（Han, Zhou & Zhu 2016） | 月度动量组合中单股跌破入场 −10% 即出 | 不自适应 | 提高 Sharpe、消掉大部分崩盘月——**触发尺度（日线监测、月度持仓）恰好落在股票动量的正自相关区** | 对本书的换算：BTC σ_1d ≈ 2.4%，−10～15% ≈ 4–6σ_1d，正是现行 6σ 的量级；再紧就掉进反转区 |
| 回撤节流 / CPPI 式去杠杆 | 权益回撤越深 gross 越小 | 自身 P&L | 降低尾部但在复苏期鞭打；是否有益取决于回撤后收益的自相关 | **已实现、按 D-017 关闭**（静态 universe 不通过，复苏 fold 转负） |
| 日内亏损暂停 / 风险预算阶梯 | 单日 −x% 停止加仓；回撤触阶梯降 vol_target | 自身 P&L | 运维护栏，不是 alpha | **已有**（−5% 日暂停；−35%/−50% 阶梯） |
| 趋势效率/强度门（Kaufman ER、ADX、Hurst） | 低效率时收紧退出或缩仓 | 市场状态 | 实务常用，学术证据薄弱且对参数敏感；本书 mining 里 vol-regime 门 +0.002 | **未测**（O-EX2 / EXP-EX2，带镜像控制臂） |
| 当前波动单位 vs 入场波动单位 | 阈值距离用当前 σ | 波动率（双向） | Chandelier/ATR 类默认用当前 ATR；没有系统比较 | **未测**（O-EX7 / EXP-EX3，最便宜的自适应检验） |
| 拥挤度/资金费退出 | 同向资金费极端时缩仓或退出 | 市场状态（永续特有） | 加密特有；本书 crowding modifier 在 sign 下 9.87% 的格子改变持仓 | **已有**（tsmom 的 crowding_window 72） |
| 交易所原生条件单（STOP_MARKET、TAKE_PROFIT_MARKET、TRAILING_STOP_MARKET 按回调比例） | 服务端挂单 | 波动率（若按 ATR 设距） | 保险价值在于循环失联时仍生效；代价是按盘中最高/最低价触发（插针）、与每小时再平衡的撤挂竞态、demo 日内路径合成无法校准 | **Won't**（D-012；KILL-R14/R15）。灾难保险这一用途已改由远端 kill switch + 心跳 + 告警承担 |
| 期权/凸性对冲 | 买入看跌锁定利润 | 波动率 | 趋势跟随者偶用；成本高 | 不适用（demo 无期权；范围外） |

### A.3 对"锁定利润、减少亏损、适应不同波动"这三个目标的直接回答

1. **适应不同波动**：本书已经做了两次——仓位按 1/σ（48h 半衰期）缩放，退出阈值按 σ 单位。文献里证据最强的"自适应"就是这两件。唯一没做的是让退出阈值随**当前**而非入场时的 σ 伸缩（EXP-EX3），代码十行，值得测。
2. **锁定利润**：所有能"锁定"某一笔利润的机制（移动止损、部分止盈、保本止损）都在截断趋势跟随的右尾；文献与本书自己的三轮证据都指向同一方向——单笔更平滑，组合更差。组合层面"锁定"利润的正确机制是 vol targeting（涨得多的名字权重相对膨胀后被再平衡修剪回目标）——但现行 40% 相对带让这个修剪很少发生，那是 P10 cell B 用证据换来的（更低换手、更高 Sharpe）。
3. **减少亏损**：本书最坏的单名损失是持有中的慢积累（E-EX08），从入场起算的止损结构上管不到，移动止损能管到但毁值；文献里对趋势系统真正有效的减亏机制是波动缩放与分散（更多低相关的 sleeve），后者正是 ≥90% alpha 投入要解决的事。

### A.4 结合当下行情

BTC/ETH/SOL 的 7 日效率比 0.004–0.020、高低幅 8–12%、波动率处于 90 日均值的 0.85–1.0 倍，30 日仍是 +23%～+44% 的强趋势之后（E-EX04）。这是教科书式的"趋势后盘整"：周级信号仍全部为正（最低 SUI 0.261），价格路径型的紧退出在这 3 天里会在 18 个名字里触发 4–9 次（E-EX14），每次付双向成本再等 24 bar 冷却。盘整会以突破延续或趋势终结收场，两种结局里只有第二种让紧退出事后看起来正确，而在事前没有任何价格路径规则能区分它们——能区分的是周级信号自己翻不翻。这就是 D-EX00 选 F2/F3 而不选 F1 的行情侧理由。
