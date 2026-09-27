# StarQuant · 自治治理 + 51 条策略 · 总体执行方案（v2.1，自洽版）

日期：2026-09-08 ｜ 等级：L ｜ 状态：**Phase 8–9 修订稿；Phase 7 已跑（独立子代理），G6 PARTIAL**
版本记录：v1（未提交）→ v2（Phase 7 之后，合并于 `07875aa`）→ **v2.1**：v2 有九处"同 v1"引用，而 v1 从未提交，读 main 的人看不到——本版把那些内容全部内联，并修正四处不一致（R7 措辞、悬空的 365 天时钟、AR-02 的状态词、全库 N 的数字）。操作者裁定（2026-09-08）：**选项 b**——全自动保持，probe→main 改为时间规则并诚实标注"不是证据裁决"；Q8 已裁（治理代码授权通过，90% 是希望不是硬要求）。

```text
Reading Check：本次理解为——把 51 条候选策略接进一套人不在运行时操作的治理机制：机器评测、机器晋级/降级、风控防死循环，以 Testnet（demo-fapi）为主验证；交付对象是操作者，交付物是可执行方案。最高风险预设为 Pre-A′「写死的规则能替代人在运行时的**决策**（不是观察）」；若不成立，机器会把假阳性合法化后送去下单——所以进 probe 的候选受 R3 的 1/3 预算与 P&L stop 兜底。
Interaction：Yellow（🟢🟢🟡🟡🟢🟢）｜等级：L｜当前决策上限：Weak GO（H3 真实资金 UNKNOWN）｜输出状态：DONE_WITH_CONCERNS｜外部动作授权：证据重出与重启 #6 已由操作者授权并执行（§17）
```

## 0. Decision Memo

| 项 | 结论 |
| --- | --- |
| Final Decision | **Weak GO（受控执行）**。Phase 0（回放）零风险立即开工；Phase 1–2 落治理骨架；机器写 registry 只在 Phase 4 之后。真实资金 HOLD & DEFERRED 不变。 |
| 操作者裁定 | ① 人退出运行时**决策**（观察与告警保留）；② 机器自动晋级/降级；③ 风控防死循环；④ 51 条作候选输入——实际进 Phase 1–3 的是 32 条，块 6 的 7 条有前置，块 0 的 12 条 Out（范围对账见 §1）；⑤ Testnet 为主；⑥ 选项 b；⑦ Q8：治理代码授权通过。 |
| Phase 7 结果 | 独立子代理：G6 FAIL，PIVOT；2 P0 / 10 P1 / 8 P2。P0-1 由 R0 的 N 口径 + 证据重出关闭；P0-2 由选项 b 改写（验证 AC-G6′ 待跑，记 MITIGATED）。处置见 §16。G6 现记 **PARTIAL**（AR-08、AR-11 均由操作者 ACCEPTED；AR-17 OPEN）。 |
| 三条核心设计判断 | (1) 评测模块已存在，缺的是"判定→registry"的写入主体；(2) 机器担任主体的前提：分位数门的 N 口径明确（R0）、只进 probe、批次窗口、降级即时；(3) Canary 是**部署健康检查，不是 alpha 过滤器**——假阳性由 R3 预算 + P&L stop 兜底。 |
| 人类确认点（D.8） | **只有三个**：治理规则版本合并（代码评审）；自治开关 `governance enable/disable`；真实资金。**单次晋级 / 降级不在其中——第一次事务起就由机器执行**（Q9，2026-09-08 操作者裁定）。这是对 KILL-AR-18 的**明示不采纳**：审查者要求把"写 registry + 自动重启 armed 循环"列为人类确认点，操作者裁定不列，理由是"人容易犯错"；D.8 要求把这类残余风险记为具名 ACCEPTED，故 AR-18 记 ACCEPTED（Owner：操作者），补偿控制是 R6 事务回滚 + Canary + R3 预算 + P&L stop，而不是人的一次点击。 |
| 预期结果 | 全库 unique 试验 **677**，该口径下分位数门 ≈ **1.67**；按策略桶（tsmom N=146）≈ 1.49。两臂协议的 tsmom 1.81 两者都过；诚实 16 点网格 1.485 只过按策略桶的门。**51 条全喂进去，正常结果是 0–2 条进 probe；probe→main 按时间规则，预期多数存活的 probe 会到 main——这是"没被停掉"的意思，不是"被证明有 alpha"。** |

## 1. 范围（含范围对账）

**In**：`starquant_governance` 包；R0 的 N 口径；时间规则晋级；验证阶梯 L1–L5；块 1–3 的 32 条候选；缠论第 51 条；块 6 的 7 条在块 5 完成后按 pit·0.30·D-034 后重测。
**范围对账（KILL-AR-16）**：操作者原话"51 条"→ Phase 1–3 实际推进 **32 条**；块 6 **7 条**设前置；块 0 **12 条** Out。合计 51。

| Out-of-Scope | 原因 | 重开条件 |
| --- | --- | --- |
| 真实资金 | **Q-CRITICAL 已裁（2026-09-08）：维持 Out，不设日期**；同时把 KILL-A 冲击模型提到 Phase 1 并行做（DL-C1） | 五道门全关 + 一次具名裁定，见 §19 |
| 块 0（做市/盘口/多场所/期权/深度学习/RL，12 条） | 另一套时间尺度与执行架构 | 另立项目 |
| LLM 提案者 | P17 PIVOT | A-004 |
| 窗口外改构造 | 每次清零 M-010 | 只在批次窗口 |
| 机器改自己的阈值 | R10 | 永不 |
| probe→main 的证据裁决 | KILL-AR-02：demo 噪声下不可达（SE≈1/√年；分开 Δ=1.7 需 2.1 年，"不劣于 q10"需 39 年） | mainnet 阶段有真实成本数据后重开 |

## 2. 架构

新增包 `starquant_governance`（自带源码上限；加进 `test_source_budget.py`、`test_import_rules.py`、`test_tests_never_touch_the_real_app_support.py` 的 PACKAGES——KILL-AR-11）：

| 模块 | 职责 | 关键接口 |
| --- | --- | --- |
| `policy.py` | 规则集 R0–R10 与全部阈值；`POLICY_VERSION` + `policy_digest()` | 纯函数，无 I/O；阈值只在此处 |
| `lifecycle.py` | 状态机（§3）；`governance_state.json` 持久化（同 `state.json.stopped_books` 的模式） | `transition(candidate, event) -> new_state, reasons` |
| `scheduler.py` | 研究循环：`search_space_version` 变化 → mine 一次 → 取边际前 k → validate → book → 平价检查 → 队列 | 跑在研究机；不碰 `.starquant/live` |
| `promote.py` | registry 事务：写 YAML + evidence sha256 → 请求重启 → 启动闸不过 → 回滚到上一 digest | 事务日志 `governance/transactions.jsonl` |
| `canary.py` | 影子循环：`live run --dry-run --state-dir .starquant/live-shadow`（**`--state-dir` 是新 flag**），浸泡 168 周期，健康检查 | 通过 → `promote.apply()`；否则回队列 + R5 计数 |
| `tenure.py` | probe → main 的时间规则（窗口存活计数、stop 事件读 `stopped_books` 与归因）；main 的回流 | 输入批次窗口日历 + 归因 |
| `replay.py` | 策略回放：对历史 ledger + 报告 + RESEARCH_LOG 裁定重放规则，输出结论 + 例外清单 + 差异归因 | Phase 0 与每次规则版本变更的验收 |
| `budget.py` | R1 预算、R3 并发、R4 每窗口上限、R5 连败冻结、R7 重入上限 | 被 scheduler / promote 调用 |

对既有包的改动（每处都在上限，需在同一提交抬上限并写理由）：

| 包 | 改动 |
| --- | --- |
| `starquant_alpha/validation/multiple_testing.py` | **报告**全库 N 与 N_eff（不作门；R0） |
| `starquant_alpha/validation/ledger.py` | `search_space_version` 由空串改为必填（R2） |
| `starquant_alpha/signals/chanlun.py` + `__init__.py` | 第 51 条（§7） |
| `starquant_live/engine.py` | 每周期落盘 `governance_digest`（R9）；回撤梯接 `throttle_scalar` 快通道，**归因口径 + 首次告警 + 2 周期宽限**（R8） |
| `starquant_cli` | `governance {status,enable,disable,replay,plan,apply,transactions}`；`live run --state-dir`；`live status --check` 加治理 digest 比对（**2026-09-10 更正**：原写 `live verify`，那条只做 M-011 复算） |
| `deploy/` | `com.starquant.research.plist` + `run_research.sh`（研究机）；`run_shadow.sh`（Canary） |

## 3. 生命周期状态机（选项 b，全部机器驱动）

| 转移 | 规则 | 时钟 | 通道 |
| --- | --- | --- | --- |
| candidate → validated | 预登记提交时间戳 < 报告（DL-K3）∧ verdict PASS ∧ 分位数门（N 口径按 R0）∧ **证据构造 ≡ 实盘构造（guards / exits / 小书，KILL-AR-07）** | 调度批次 | 研究机 |
| validated → booked | book 六项 ∧ `slippage_stress` 5.5 档过 ∧ 与每本在跑的书 corr < 0.5 ∧ 换手 ≤ 3× tsmom | 同上 | 研究机 |
| booked → queued | 面板平价义务满足（M-011；缺则卡在 `metrics_refusal` 同形闸） | 同上 | 研究机 |
| queued → probe | 批次窗口 ∧ R3/R4 未满 ∧ 队首 ∧ Canary 健康检查过 ∧ **M-010 在当前构造下已满 30 天**（K-EX14，见下） | **月度** | 慢：事务 + 重启，**机器执行（含第一次）**；失败由 R6 自动回滚 |
| **probe → main（时间规则）** | 连续 **9 个批次窗口**（= 9 个月）存活 ∧ 期间从未触发 P&L stop ∧ family gate 重算仍过。**main 保留 P&L stop 与 fraction 不变**——晋级只解除 R7 的重入计数，不加预算 | 窗口末 | 慢 |
| probe → retired | P&L stop（已有）∨ family gate 重算不过 | 即时 | 快：`stopped_books` |
| main → probe | 触发 P&L stop 一次 → 回 probe 重新计 3 窗口（不 retired） | 即时 | 快 |
| 任何 → retired | **第 3 次离开 probe 后**（R7：终身进 probe 上限 3 次） | — | — |

每个 probe 在 9 个窗口内必然到 main 或 retired，所以**没有单独的日历时钟**。

**窗口 = 一个月（Q3，2026-09-08 操作者裁定），三条连带后果**：

1. **K-EX14 与窗口长度正好相等，所以它是准入条件而不是背景约束。** `construction_fingerprint` 含 `strategy_weights`（`engine.py:1386` ← `config.py:102` 从 `registry.enabled` 构建），所以**每次晋级都改构造指纹、清零 M-010 的 30 天窗口**。月度窗口下这条零 headroom：晋级发生在第 0 天，下一次要等第 30 天。故 §3 把"M-010 已满 30 天"写进 queued→probe 的条件——**每月是一次晋级机会，不是每月必晋级**；时钟没到，窗口空过。
2. **时间规则的窗口数从 3 改为 9，为的是保持原强度不变。** 预登记"3 个窗口"是在窗口 = 季度时写的（= 9 个月）。按 D-019 的 −2σ 校准，单窗口 stop 概率对 Sharpe-0 的 sleeve ≈ 2.3%、对 Sharpe-1.7 ≈ 0.64%（E5，正态近似、窗口独立）：

   | 窗口数 | Sharpe-0 到 main | Sharpe-1.7 到 main | 鉴别比 |
   | ---: | ---: | ---: | ---: |
   | 3（= 3 个月） | 93.2% | 98.1% | 1.05 |
   | **9（= 9 个月）** | **81.0%** | **94.4%** | **1.17** |

   保持 9 个窗口 = 保持预登记时的鉴别力；改成 3 个窗口是**把晋级速度换成更弱的过滤**，一行可改，但要作为规则版本变更记一笔。两个数都很弱——这正是"区分的是炸没炸，不是有没有 alpha"那句话的量化形态。
3. **R1、R5 按窗口重新表述**：预算从"每季 500"改为"每窗口 170"（ledger 增速不变）；冻结从"2 窗口"改为"6 窗口"（仍是 6 个月，惩罚力度不变）。R3/R4/R7 不动——实际约束是 R3 的 2 个 probe 位，而 flow 已占 1。

**时间规则的诚实标注**：按 D-019 校准（−2% ≈ 探针 30 天 P&L 的 −2σ），Sharpe-0 的 sleeve 9 个月存活概率约 0.8，Sharpe-1.7 约 0.95（E5 估算，独立窗口近似）。**它区分的是"炸没炸"，不是"有没有 alpha"**；假阳性的代价由 fraction ≤ 1/3 与 stop 兜底。

**Grandfather（KILL-AR-06）**：tsmom 记为 main（起点 2026-09-03 registry 生效日）；flow 记为 probe，起点 2026-09-03，其 30 天复审（2026-10-03）按 D-029 的 P&L 规则；flow 占用 R3 的 1 个并发名额与 1/3 预算——**第二本 probe 要么等 flow 退，要么 fraction 1/6 并出新 book 报告**。

## 4. 规则集（每条标来源：推导 / 先例 / E5 拍定，KILL-AR-13）

| # | 规则 | 数值 | 来源 |
| --- | --- | --- | --- |
| **R0** | 分位数门的 N 口径：**保持按策略桶**（`ledger_scope`），mined 候选加共享 `mined` 桶；全库 N 与 N_eff **只报告**。理由：全库 N 会让诚实网格的 incumbent FAIL（KILL-AR-01），N_eff 只降门（`multiple_testing.py:207`）。家族级风险改由 R3/R4/R5 在暴露侧控制 | — | 推导 |
| R1 | **每窗口**新增 ledger 行 ≤ B，**不含共享 `mined` 桶**；mine 轮次单独计，每窗口 ≤ 1 | **B = 1,700；mine 4 轮/窗口（policy 0.3.0，操作者 2026-09-09 放开）**；原写 170 / 1 轮 | **E5**。**policy 0.2.0（2026-09-08）改**：原口径 170 行 = 一次 mine 的 1/3，而 `refusals` 整体拒绝不截断，于是 R1+R2+调度器让 mine **在任何窗口都跑不了**。R1 约束的是「这个窗口做了多少次**选择**」，而一次 mine 是**一次**选择（枚举全空间取边际前 k），这正是 `ledger_scope` 把它们归到一个共享桶的原因。**DSR 分母不变**——仍按全部 514 计 |
| R2 | mine 只在搜索空间变化时跑；同空间重跑拒绝；重开路径：`--reauthorize '<D-决策与理由>'`，理由写进 shortlist 报告 | 版本 = `SearchResult.space_digest`（**规范表达式哈希的集合**）。**修正**：v2.1 写的"`search_space_version` 由空串改为必填"是错的——那个字段在 `mined` 桶的行上刻意留空，改必填会为一个 514 的家族收 267 + 514（见 09-08 日志） | 先例（K-EX07 / Q7） |
| R3 | probe 并发 ≤ 2；probe 总分数 ≤ 1/3 主 ledger | — | 先例（D-018；flow 已占 1） |
| R4 | 每窗口 ≤ 1 queued→probe、≤ 1 probe→main | — | **E5** |
| R5 | 连续 2 个 probe 被 stop → 冻结 **6 窗口**（= 6 个月，与季度口径下的 2 季等长）；no-decision：stop 发生在 TRANSFER 重基或 ERROR 相的周期不计 | k=2, n=6 | **E5**（假停率进 EXP-G6′） |
| R6 | registry 事务 + 回滚 | — | 推导（KILL-Q15） |
| R7 | 终身进 probe 上限 3 次（第 3 次离开后 retired）；降级后冷却 ≥ 1 窗口 | 3 | **E5** |
| R8 | 回撤梯 −35% / −50% → 快通道缩 vol_target；**口径 = 归因 P&L 回撤（income 行），不用交易所权益**；首次触发告警 + 2 周期宽限；触发前后各落一行事务 | 0.225 / 0.15 | 先例（P13）+ 推导（KILL-AR-05） |
| R9 | `governance_digest` 每周期落盘 | — | 推导（KILL-Q15 同形） |
| R10 | 阈值只在代码里，改动带版本 + 测试 + 预登记 | — | 推导 |

## 5. 验证阶梯（六层，Testnet 为主）

| 层 | 环境 | 验什么 | 通过条件 |
| --- | --- | --- | --- |
| L1 代码层 | pytest（240 s 上限） | 每个 signal 自动三测（因果 / warmup / 有界，**面板随 warmup 伸缩**，KILL-AR-15）；治理属性测试（R0–R10 任意序列不可违反；事务回滚后 digest 相等）；状态机合法转移 | 全绿 + ratchet |
| L2 回放层 | 历史 ledger 702 行 + 199 份报告 + RESEARCH_LOG 裁定 | 规则对每个人工裁定的重放，**输出 = 规则结论 + 例外清单 + 差异归因**（KILL-AR-03） | 差异清单无"未归因"项 |
| L3 paper | `live run --paper`（进程内撮合、mainnet 标记、无凭证） | 状态机 + 调度器 + 事务在无场所下跑完整周期 | 7 天无 ERROR 相；事务日志闭合 |
| L4 Canary | `live run --dry-run --state-dir .starquant/live-shadow`，读候选 registry | **部署健康**：0 启动闸拒绝；digest 稳定；`guard_reasons` 率 ≤ 基线；无 ERROR 连败；计划订单 ⊆ participation cap；`targets ⊆ universe`。**不拦假阳性**（KILL-AR-04） | 六项全过（**更正**：`canary.py` 实建 **7** 项 Check，多一个 `soak`；`healthy` 要求全 7） |
| L5 Testnet armed | demo-fapi，`--armed`，probe 受 R3 限制 | 真实撮合下的执行保真 + 六项演练 | M-Q03 / M-Q08（≥30 笔）/ M-Q09 / M-Q10 = 100% / M-015 在界内；DRILL-G1..G6 全过 |
| L6 real money | — | — | Out；入口见 §1 |

**Testnet 特有事项**：demo 账户会重置，表现为 `TRANSFER` 行且无成交——回放与指标一律用 income 行，不用权益曲线；52% 权益是非 USDT 抵押品，回测建模抵押品为零——一切治理判据用归因 P&L，不用权益；到币安的路径经系统代理 1082，间歇 503——ERROR 相**不产生任何治理决定**；信号读 mainnet 公共数据、成交在 demo——Canary 与 armed 循环读同一份行情，只差写场所。**每条治理判据逐个写 no-decision 条件**（KILL-AR-20）：P&L stop 用归因不用 `pnl/equity`；M-015 日读数取当天最后一个非 ERROR 周期；R5 计数排除重基周期。

**演练（L5，每次规则版本变更后重跑）**

| DRILL | 注入 | 预期 |
| --- | --- | --- |
| G1 | 事务写入一份 sha256 不符的 evidence | 启动闸拒绝 → 自动回滚 → 重启成功 → 事务日志记 ROLLBACK |
| G2 | 连续两个 probe 触发 P&L stop（paper 注入）；另一组在 TRANSFER 重基周期触发 | 前者：晋级冻结 2 窗口、`governance status` 显示 FROZEN；后者：不计数 |
| G3 | 手改 `policy.py` 阈值不递增版本 | 架构测试红；`live status --check` 报治理 digest 不一致（更正 2026-09-10） |
| G4 | Canary 浸泡中注入启动闸拒绝 | 候选回队列，不触碰 armed 循环 |
| G5 | 批次窗口重启期间 `launchctl kickstart` | 单实例锁生效；事务幂等 |
| G6 | 代理 503 风暴（阻断出口 1 小时） | 无治理决定；R5 计数不变；告警去重 |

## 6. 51 条候选按块 → Phase

| 块 | 条目 | 进入 Phase | 备注 |
| --- | --- | --- | --- |
| 块 5 验证/ledger 扩展 | R0 报告口径、`search_space_version` 必填、时间规则、事件时间对齐契约、配对选择计费 | **Phase 1** | 没它们，后面做了也不算数 |
| 块 1 数据管线（**12 条**，13 是重复计数） | #16 OI ✔ / #17 多空比 ✔（**实盘闸对它关着**：四列在 snapshot 全 NaN）、现货 ingest（解锁的**只有 #11 基差**——~~#14 资金费套利~~ ~~#39 期现~~ **2026-09-10 判「不可执行」**：两者都要现货腿，而 `guard.py` 的 `ORDER_PATHS` 只有 `/fapi/v1/order` 与 `batchOrders`）、~~#19 公共清算流~~ **不可用**、~~#28 解锁~~ **不可得**、#29 指数 ✔（无 store/sync/CLI）、~~#30 社交~~ **不可得**、#31 链上 ✔、#32 宏观 ✔（2026-09-09 落地） | Phase 3 | 每列进实盘前过平价义务；外部 API 每个一份对齐契约 |
| 块 2 挖掘节点（6 条） | hod #8 ✔（54 个，已打分）、**OI/LS 叶 ✔ 但 90 个候选从未打过分**（`metrics=True` 缺失，`f4ea9de` 已修，见 2026-09-10 预登记）、basis 叶 ✔（18 形状，`_load` 不建现货 store 故枚举 0）、~~liquidation 叶~~ **永久阻塞（无数据）**、regime 叶 ✔（边际全负） | Phase 3 | 每节点：量纲 + 因果 + 哈希稳定 + 预登记提交早于第一份报告 |
| 块 3 手写信号（6 条） | 配对/协整（#6）、上新（#27）、~~缠论（#51）~~ **REFUTED 2026-09-08（corr 0.64、边际 −0.63）→ retired**、regime（#47）、岭回归（#22，≥3 因子后）、meta-label（#24，与 P24 结项冲突，Won't） | Phase 3 | 各自预登记网格先提交 |
| 块 4 构造/执行层（7 条） | **冲击模型（#43）移到 Phase 1（DL-C1，Q-CRITICAL 裁定）**；~~GARCH（#35）~~ **REFUTED 2026-09-09（P29：预报更准但配对 −0.27 / t −7.09，零成本下仍 −0.20）→ retired**、~~HRP（#48）~~ **REFUTED 2026-09-09（P29：−0.23；控制行显示损失来自 inverse-variance 分配而非聚类）→ retired**、~~VWAP（#42）~~ **REFUTED 2026-09-09**、回撤节流（#20，已判否）、动态杠杆（#49，已有）、抵押品分母 | 其余仍在批次窗口 #1（Phase 4a） | 每条 = 重启 + 清零 M-010。**成本模型是例外**：它不在 `construction_fingerprint` 里，所以建它不清零 M-010——但采纳它要按 D-033/D-034 先例重出证据（加 ledger 行，计入 R1） |
| 块 6 已判否 7 条 | **✔ 已收口（2026-09-09）**：xsmom（零 ledger 前置闸，`validate` 未跑）/ carry FAIL / residual FAIL（差 0.0135）/ meanrev、breakout 按「改变的条件动不了死因」不跑 / 节流 09-07 已重测 / regime 已结项。**七条无一进 probe，共花 12 行 ledger**（按字面跑七条要 56 行换 0 个新结论） | 已完成 | 写明产生旧否决的网格（校准记录的教训） |
| 块 0 换系统级 12 条 | 做市 / 盘口 / 清算-盘口侧 / 路由 / 跨所 / 三角 / 跨期 / ETF / 期权 ×3 / LSTM / RL | Out | 另立项目 |

## 7. 第 51 条：缠论（`chanlun`）规格

**形式化选择（预登记，先写后跑；只选一族，不做"哪族好选哪族"）**：
- 包含关系处理：从左到右迭代合并（趋势向上取高高/高低，向下取低低/低高），只用 ≤ t 的 K 线。
- 分型：顶分型在 bar i 成立需要 bar i+1，故**在 i+1 收盘确认**；所有结构以确认 bar 打戳，不以形成 bar 打戳。
- 笔：相邻反向已确认分型之间 ≥ `min_bars` 根（含合并后）；下一反向分型确认时本笔确认。
- 线段：≥ 3 笔且有重叠；用特征序列分型确认（滞后可达多根）。
- 中枢：连续 ≥ 3 段的重叠区间，ZG = min(高点)、ZD = max(低点)。
- 买卖点：三类买点（离开中枢后回抽不回中枢）→ +1；三类卖点 → −1；一类（背驰：MACD 面积比 < `div_ratio`）作为**平仓**触发（显式 0.0），不作为反向开仓；其余 → 次阈值（NO_ACTION 持有）。
- 级别：基础 1h；`level` 参数决定 resample 到 4h 后再做结构。

**因果性设计**：单次前向遍历，每个 t 只从"截至 t 的状态"发分数；未确认的末端结构不参与打分；**绝不**在事后重画后回填历史分数。`test_signals_are_causal_and_bounded` 把 cutoff 之后的数据整段替换并逐位比对——但它的合成面板必须比 warmup 长（T-S51-1：`n_bars ≥ warmup + 600`），否则对 warmup 720 的信号它是空转的（KILL-AR-15，已另开任务修测试本身）。

**参数与网格（≤ 6 格，先验砍）**：`level ∈ {1h, 4h}` × `min_bars ∈ {4, 5}` × `div_ratio ∈ {0.8}`，`entry_threshold 0.2`；warmup 上界 **720**（4h 级别形成中枢 + 三类买点的保守估计，且在 1,500 根请求上限内）。

**预登记判据与 falsifier**：
- 过策略级 PASS + 分位数门（R0 口径）；
- **与 tsmom 的 corr < 0.5**，否则判"tsmom 换了写法"（预期这是最可能的死因：缠论在 1h 加密永续上本质是带结构的趋势跟随）；
- `decompose` 的 `sign_only` 臂不劣于 `full` 臂 0.05 以上（幅度无信息则改 sign 模式）；
- 换手 ≤ 3× tsmom；
- 三类买点触发数：最低可判定样本 = 走前 5 fold 每 fold ≥ 60 次事件 ≈ 5 年 × 205 币 × 4h 级别下每币每年 ≥ 0.3 次 ≈ **≥ 300 次**（E5 推导）。

**预期**：阴性或"与 tsmom 高相关"为基准预期；阳性需在 Canary 后按 §3 走 probe，不例外。

## 8. Phase 与顺序（拆开首次晋级与构造改动，KILL-AR-12）

```text
Phase 0 回放 ✔（2026-09-08 完成）：A + B + D 已跑，AC-G0 通过（29 差异 / 0 未归因）；产物见 §18
Phase 1 尺子（2–4 周，无重启）：**先做 DL-G9（两条判据可读）**，再 R0 报告口径、search_space_version 必填、budget / lifecycle / governance_digest、L1 属性测试；**并行 DL-C1 冲击成本模型**（不碰构造，不清零 M-010）
Phase 2 ✔（2026-09-08）调度器 + 事务 + Canary，无重启。DRILL-G1/G4/G5 已作单元测试跑通（G1 用真闸 + 实盘 registry），G2/G3/G6 由属性测试与钉死的 policy digest 覆盖；DRILL-G2/G6 ✔ 2026-09-09（走 `cycles.jsonl`→`tenure`→`lifecycle` 真缝，不是属性测试代跑）；**paper 端到端串跑 ✔ 2026-09-09**（`--paper --state-dir .starquant/paper-l3`，完整周期 18 targets / 18 orders、`guard_reasons` 空、无 error，持钉住的 registry `1ad760a55e8f`；`pool_refresh=False`、共享 metrics 未写。**L3 的 7 天软泡仍未跑**——串跑 ≠ 通过判据）
Phase 3 数据宽度 + 节点 + 手写含缠论（4–8 周，并行，无重启）
Phase 4a 批次窗口 #1（构造）：块 4 必改项一次改完 → 重启 → 攒 30 天干净窗口（K-EX14）
Phase 4b 批次窗口 #2（晋级）：队首候选 → Canary → 事务（机器 apply）→ 重启 → probe
Phase 5 稳态：月度窗口（每月一次晋级机会，非每月必晋级）；每规则版本变更后重跑 L2 + DRILL
```

硬约束：**构造冻结**——窗口之间不改 `construction_fingerprint`、registry digest、`governance_digest`；**并行会话**——每批一个 worktree、共享文件只追加；**ratchet 记账**——每包抬上限随提交写理由。

## 9. Delivery Contracts（DL 表）

| DL | 来源链 | 实现 | 测试 | 验收 | 指标 | ratchet |
| --- | --- | --- | --- | --- | --- | --- |
| **DL-G0 回放 ✔** | Pre-A′ ← Phase 7 AR-03/AR-10 | `replay.py`：读 ledger / 报告 / 日志裁定，重放 §3/§4，输出结论 + 例外清单 + 差异归因 | T-G0-1 例外清单含 D-019 / D-029 / K-EX07 / Q7 / P10 cell B / P11 / P13；T-G0-2 每条差异带规则 ID | AC-G0 | M-G02 | gov +≈300 |
| **DL-G1 报告口径 ✔** | R0 ← KILL-AR-01 | `multiple_testing.py` 报告全库 N 与 N_eff（不作门） | T-G1-1 现有报告重算判定不变；T-G1-2 报告含两个口径 | AC-G1 | M-Q04 | alpha +≈40 |
| **DL-G2 同空间不重跑 ✔** | R2 ← 09-08 ledger 事故 | `SearchResult.space_digest` 进 shortlist 报告；`research mine` 在打分前拒绝已枚举过的空间；`--reauthorize` 记进报告 | T-G2-1 同空间被拒 ✔；T-G2-2 更宽的空间放行 ✔；T-G2-3 早于字段的报告按 `evaluated` 退化并标注 ✔ | AC-G2 | M-G04 | alpha +≈15，cli +≈64 |
| **DL-G3 状态机 + 预算 ✔** | §3 / §4 | `lifecycle.py`（Phase 0）、`budget.py`（R1 从 ledger 读）、`state.py`/`governance_state.json` | T-G3-1 非法转移拒绝；T-G3-2 R1/R3/R4/R5/R7 属性测试（hypothesis）；T-G3-3 重启后状态持久 | AC-G3 | M-G01 | gov +≈500 |
| **DL-G4 事务 + 回滚 ✔** | R6 | `promote.py` | T-G4-1 闸拒绝 → 回滚 → digest 等于回滚前；T-G4-2 幂等 | AC-G4 / DRILL-G1 | M-Q10 | gov +≈250 |
| **DL-G5 Canary ✔** | §5 L4 | `canary.py` + `run_shadow.sh` + `.starquant/live-shadow` + `live run --state-dir` | T-G5-1 健康指标计算；T-G5-2 失败 → 回队列 + R5 计数 | AC-G5 / DRILL-G4 | M-G03 | gov +≈300，cli +≈20，deploy |
| **DL-G6′ 时间规则 ✔** | §3 ← 选项 b | `tenure.py`（从 `cycles.jsonl` 推出事件）+ `governance tenure`；判定仍全在 `lifecycle.py`。**未关的那条边：`probes_from_registry` 排除 main book，所以 main→probe 从记录里不可达**，命令自己会说 | T-G6′-1 ✔；T-G6′-2 ✔；T-G6′-3 ✔（跳过丢不掉真 stop，有测试）；另加两条：窗口内无周期不算存活、中途进场不拿那个窗口 | AC-G6′ | M-G01 | gov +≈150 |
| **DL-G7 治理 digest + 快通道 ✔（2026-09-09）** | R8 / R9 | `engine.py` 每周期落盘；回撤梯接 `throttle_scalar`（归因口径 + 告警 + 宽限） | T-G7-1 digest 变 → `live status --check` 报（更正 2026-09-10）；T-G7-2 −35% 注入 → 告警，2 周期后 scalar 0.75；T-G7-3 权益回撤（抵押品）不触发 | AC-G7 / DRILL-G3 | M-Q10, M-015 | live +≈100 |
| **DL-G8 调度器 ✔（研究机 plist 未做）** | §2 | `scheduler.py`；跨机契约见 §21（默认单机，且 canary 需要交易凭据） | T-G8-1 空间未变不 mine；T-G8-2 预算耗尽停止 validate | AC-G8 | M-G04 | gov +≈300，deploy |
| **DL-C1 冲击成本模型 ✔（含 P26 重推）** | KILL-A / KILL-Q12 ← Q-CRITICAL 裁定 | 平方根法则 `σ·(Q/ADV)^0.5` 起步，参数由参与率表与 E-19 的 4.3 bps 校准；`costs.yaml` 加一档；`vol_target` 在该模型下重推 | T-C1-1 平模型是新模型的特例（Q→0 时收敛到 7 bps）；T-C1-2 容量曲线在 10 万 / 100 万上可算；T-C1-3 `cost_stress` 的口径变更进 `ruler_version` | AC-C1 | M-Q08 | alpha +≈180 |
| **DL-G9 判据可读性 ✔** | Phase 0 §18 ← 回放发现 | validate 报告写预登记 commit + `construction_digest`；构造变化时落全量构造（今天只有启动心跳有且每次启动被覆盖） | T-G9-1 新报告含预登记指针；T-G9-2 构造变化落全量；T-G9-3 回放中这两条判据不再被挂起 | AC-G9 | M-G02 | alpha +≈40，live +≈60 |
| **DL-S51 缠论 ✔ REFUTED** | §7 | `signals/chanlun.py` + SignalSpec + 预登记提交 | 自动三测 + T-S51-1（面板 ≥ warmup + 600）+ T-S51-2 warmup ≥ 首个可评分 bar + T-S51-3 三类买点 ≥ 300 | AC-S51 | — | alpha +≈350 |
| **DL-D4 metrics→Panel ✔** | 块 1 | `Panel.metrics` + 叶节点 + M-011 平价接日报 | T-D4-1 5 分钟桶对齐 166/166；T-D4-2 无平价证据 → queued 卡住 | AC-D4 | M-011 | alpha/data +≈150 |
| DL-D5 现货 ingest | 块 1 | 同源 REST + 月归档 + basis 叶 | T-D5-1 对齐契约；T-D5-2 因果 | AC-D5 | M-011 | data +≈250 |

## 10. Acceptance（三层）

| AC | DL | 层级 | 前置 | 操作 / 观察 | 客观预期 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| AC-G0 ✔（2026-09-09 重新为真） | G0 | Hypothesis | ledger / 报告在案 | `governance replay --since 2026-09-03` | 输出规则结论 + 例外清单 + 差异归因；**无"未归因"项** | 规则第一版不定稿 |
| **AC-C1 ✔（2026-09-09）** | C1 | Functional | Phase 1 | 用新成本模型重跑 tsmom validate | 报告落 `impact_model` 块；10 万 USDT 的参与率与容量曲线可算；判定变化（若有）写进 RESEARCH_LOG | 模型不采纳，平 7 bps 维持并记为已知债 |
| **AC-G9 ✔（能满足的唯一形式）** | G9 | Functional | Phase 1 | 重跑 `governance replay` | ~~两条消失~~ **改判（2026-09-09）：两条各有 1 份指针「已可判定」，14 份早于 DL-G9 的仍挂起。字面写法不可能满足——预登记指针没法事后补进旧报告；能满足的形式是「DL-G9 之后的报告按 artefact 判定」，回放已如此输出** | 状态机仍不可通电 |
| **AC-G1 ✔** | G1 | Functional | Phase 1 | 重算历史报告 | 判定不变；tsmom 的两个口径（146 / 677）都写进报告 | 口径重查 |
| **AC-G3 ✔（2026-09-09）** | G3 | Functional | Phase 1 | hypothesis 跑 1,000 序列 | R0–R10 零违反 | 修状态机 |
| AC-G4 | G4 | Scenario | paper | DRILL-G1 | ROLLBACK 行 + 重启成功 + digest 等于回滚前 | 事务不上线 |
| AC-G5 | G5 | Scenario | dry-run 影子 | 一次真实候选浸泡 168 周期 | 六项全过；失败时 armed 循环零改动 | Canary 不上线 |
| **AC-G6′ ✔（2026-09-09）** | G6′ | Hypothesis | paper 注入 | 三种序列（无 stop / 一次 stop / TRANSFER 周期 stop） | 状态转移与 §3 一致 | 修 tenure |
| **AC-G7 ✔（2026-09-09，T-G7-1/2/3）** | G7 | Scenario | 重启 | DRILL-G3；−35% 归因回撤注入；同幅权益回撤注入 | verify 报警；前者告警 + 2 周期后 scalar 0.75；后者不触发；不改 config | 修快通道 |
| AC-G8 | G8 | Functional | 研究机就绪 | 连跑 3 轮 | 空间未变零 mine；预算耗尽零 validate；队列有序 | 修调度 |
| AC-S51 ✔ | S51 | Hypothesis | 预登记提交在先（`4577d07`） | corr 检查 | **已达成**：corr **0.6426** ≥ 0.5 → 记「tsmom 换写法」；边际 **−0.6340**；判定写入 RESEARCH_LOG | 已转 retired |
| AC-L5 | 全部 | Scenario | Phase 4b | 第一次全自动窗口，**全程无人工动作** | Canary → 事务 → 重启 → probe 生效 → 下单；M-Q10 = 100%；M-010 窗口只清零一次（4a 那次）；事务日志含 APPLY 行且 actor = machine | 回滚，冻结晋级 |

## 11. Learning Contract

| Metric | 指标 | 基线 | 成功阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- |
| M-010 | 各策略实盘归因 Sharpe vs 回测 q10 | tsmom 当前窗口 | 不劣于 q10 = **−1.52**（62 个滚动 OOS 窗口的 q10） | 30 天滚动 / 180 天月检 | 快通道缩 vol_target |
| M-Q03 / M-Q08 / M-Q09 / M-Q10 | 迟到成交 / 滑点 / 熔断 / registry≡循环 | 已在跑 | 现行阈值；M-Q10 = 100% | 每周期 | 现行 |
| M-015 | 风险压缩 | 0.76 界 | 在界内 | 每日 | 换判据不抬数 |
| M-G01 | probe 被 P&L stop 关掉的比例 | 无（flow 1/1 存活） | ≤ 50%（连续 2 次触发 R5） | 每窗口 | R5 冻结 |
| M-G02 | 回放：未归因差异数 | — | 0 | 每规则版本 | 版本不发布 |
| M-G03 | Canary 浸泡通过率 | 无 | 首次 ≥ 1/1；长期 ≥ 80% | 每次晋级 | 查候选或 Canary 判据 |
| M-G04 | 试验预算使用率 | 702 行 | **≤ 1,700 / 窗口（30 天）** | **每窗口** | 停 validate（**2026-09-10 更正**：原写 ≤500/季·每季，三个字段都停在 policy 0.2.0 之前；实测 181/1700、mine 3/4） |
| **M-G05** | 机器裁决与事后人工复核的分歧率（方向分开记） | — | 季度复核 ≥ 10 条；分歧 > 20% 或系统性偏一侧 → 规则版本复审 | 每季 | 这是 Pre-A′ 的 falsifier |
| **M-G06** | 构造不变 ≥ **18 个月**的实盘归因年化 Sharpe（**按策略**，与 M-010 同口径） | — | **点估计 ≥ 0**；NW t 只报告不作门（与 D-P2 对 t 的处置同形） | 18 个月，按 `canonical_construction` 计时 | 该策略退出 main |

**Experiment**：EXP-G0 策略回放（零 ledger）；EXP-G6′ 时间规则的假停率模拟（R5 的 k=2 是否会被噪声触发）；EXP-S51 缠论预登记验证。

## 12. Risk Register

| RISK | 风险 | 概率 / 影响 | 预警 | 缓解 | 失败动作 |
| --- | --- | --- | --- | --- | --- |
| RISK-G1 | 规则 bug 放行垃圾候选 | 中 / 高 | M-G01、R5 | 回放验收 + 只进 probe + R3 限额 | 冻结晋级，回滚事务 |
| RISK-G2 | 自动晋级清零证据窗口 | 高 / 中 | M-010 窗口重置次数 | 批次窗口 + R4 + Phase 4a/4b 拆开 | 延长窗口 |
| RISK-G3 | 新数据列前视（事件时间对齐） | 中 / 高 | 对齐契约测试 | DL-D2 模式：先契约后下载器 | 该列不进实盘 |
| RISK-G4 | 分位数门把一切拦在门外（0 晋级） | 高 / 低 | M-G04 | 这是正确行为；转数据宽度而非放松门 | 不放松门 |
| RISK-G5 | 时间规则把 Sharpe-0 的 probe 送进 main（概率约 0.8） | 高 / 中 | M-G01 | main 不加预算、stop 保留 | 设计时降预算 |
| RISK-G6 | Testnet 伪像被当信号（重置、抵押品、503） | 中 / 中 | income 行、no-decision | §5 Testnet 事项 | 修判据 |
| RISK-G7 | 源码 / 测试时长上限被撑破 | 高 / 低 | ratchet | 新包自带上限；slow 标记 | 抬上限并写理由 |
| RISK-G8 | 治理规则版本漂移无人知 | 中 / 高 | M-Q10 扩展 | R9 每周期 digest | verify 报警 |
| RISK-G9 | flow 占满 R3 → 第二本 probe 等待 | 高 / 低 | `governance status` | Grandfather 条款 | fraction 1/6 + 新 book 报告 |
| RISK-G10 | 跨机研究缺契约（AR-17） | 中 / 中 | — | 默认单机 | 写契约后再上研究机 |
| **RISK-G11** | **抵押品顺周期放大器**：权重是权益的分数，权益 52.2% 是非 USDT 抵押品，抵押品涨 10% → 每张目标名义涨 5.2%；回测建模的抵押品为零 | 高 / 中 | `collateral_drift`（实测：23 周期里权益变化的 **73%** 是重估不是交易） | 全部判据（R8 梯、M-010、M-G06）已走**归因 P&L** 口径，只有仓位尺寸受影响；仪表只报告不相减 | **ACCEPTED**（操作者，2026-09-08 审计三问③）；真实资金前按 §19 重新评估 |

## 13. Claim Register（KILL-AR-19）

| Claim | 命题 | 等级 | Falsifier | 状态 |
| --- | --- | --- | --- | --- |
| C-G1 | 分位数门按策略桶 + 暴露侧 R3/R5，能把假阳性的**代价**控制在 1/3 预算内 | E1（D-018/D-019 机制）+ E5（R 值） | 一个 probe 在 stop 前造成 > 2% 权益损失 | OPEN |
| C-G2′ | 时间规则在 demo 阶段是可执行的晋级依据，且被诚实标注为非证据 | E5 | 机器把连续被 stop 的 sleeve 送进 main（规则 bug） | **MITIGATED（2026-09-10 更正**：AC-G6′ 已于 09-09 跑过，见 §10、§16；本行的 OPEN 是漏改） |
| A-G1 | registry 事务 + 闸 + 回滚能防"自动写入把循环写死" | E1（KILL-Q15 仪表）| 回滚目标与事务目标同病（两份证据都 FAIL）——已由证据重出关闭（§17） | MITIGATED |
| Pre-A′ | 写死的规则能替代人在运行时的**决策** | E3 | M-G05 分歧率 > 20% | OPEN |
| A-S51 | 缠论与 tsmom 高相关，预期阴性 | E5 | corr < 0.5 且 PASS | **SUPPORTED**（2026-09-08：corr 0.6426，边际 −0.6340；被证伪的是 §7 那一族形式化，不是「缠论」这个方向） |

## 14. Assumptions & Open Questions

| Q | 问题 | 状态 / 未答时假设 |
| --- | --- | --- |
| ~~Q-CRITICAL~~ | 真实资金进不进范围、何时 | **已裁定（2026-09-08）：维持 Out，不设日期；冲击模型现在就建（DL-C1）**。五道门与状态见 §19 |
| ~~Q2~~ | "持续盈利"判据（实盘年化 Sharpe 阈值 + 窗口） | **已裁定（2026-09-08）：双层 + 诚实标注**。领先 M-010 不劣于 q10 = −1.52（"没炸"判据）；滞后 M-G06 构造不变 ≥ 18 个月、按策略、点估计 ≥ 0、t 只报告。见 §19 |
| ~~Q3~~ | 批次窗口长度 | **已裁定（2026-09-08）：一个月**。连带调整见 §3 注、R1、R5 |
| ~~Q4~~ | 新数据源进范围 | **已裁（2026-09-09）：按默认「进」** |
| ~~Q5~~ | 研究机 | **已裁定（2026-09-12）：只用本机，不增加能下单的机器。** 于是 §21 的第 3 条代价消失——canary 的交易凭据就在本机，L4 不再无处安放，浸泡已于 13:21Z 启动（`com.starquant.shadow`）。`com.starquant.research.plist` / `run_research.sh` 随之判**明写不做**。原文：默认单机。**跨机契约已写（§21）**，并核出了它的代价：canary 走 `--dry-run` → `build_venue`，**需要交易凭据**，所以研究机跑不了 §5 的 L4。要拆机，先裁「多一台能下单的机器」 |
| ~~Q6~~ | 缠论形式化 | 按 §7，不改 |
| ~~Q7~~ | 09-08 重跑的 514 行 ledger | 已裁定回退（K-EX07 先例） |
| ~~Q8~~ | 治理代码 vs 90% alpha 目标 | 已裁定：授权通过，90% 是希望不是硬要求（AR-11 ACCEPTED） |
| ~~Q9~~ | Phase 4b 前两次事务是否由人 `apply` | **已裁定（2026-09-08）：不用人 apply，第一次就机器执行**；AR-18 转 ACCEPTED |

## 15. 明确未做
块 0；User Story Draft（单操作者，压缩为 §3）；真实资金 pre-flight。~~跨机契约（AR-17）~~ → §21。

## 21. AR-17 跨机契约（2026-09-09）

Q5 默认单机。这一节写的是**如果**拆成两台，什么东西跨过那条边界、朝哪个方向、以及冲突时谁赢——
以及今天核出来的那条让"研究机跑全流程"不成立的事实。

### 谁写什么

| 制品 | 写 | 读 | 传递 | 并发 |
| --- | --- | --- | --- | --- |
| `reports/research/*`、验证 ledger | 研究机 | 两边 | git | 只追加，文件名带时间戳，天然不冲突 |
| `config/alpha_registry.yaml` | **只有交易机**（事务） | 两边 | git | 单写者 |
| `governance/transactions.jsonl` | **只有交易机** | 两边 | git | 只追加；`closed()` 验链，断链即"有人绕过事务改了 registry" |
| `governance/governance_state.json` | **只有交易机** | 两边 | git | **必须单写者**：`probe_entries` 是 R7 的终身计数，两边各加一次就等于白送一条命 |
| `.starquant/live/*` | 交易机 | **只有交易机** | 不跨机 | — |
| `.starquant/data/universe.json` | **只有在拿账户交易的那个进程** | 两边 | 不跨机 | 见下第 4 条 |

### 四条规则，每条都有今天的证据

1. **晋级只发生在交易机上。** 研究机产出候选与报告；晋级是一次 registry 事务加一次重启，两者都只在
   交易机上发生。研究机对 registry 只有读权限。
2. **调度器不读 `.starquant/live`，tenure 只在交易机上跑。** 前者是 `scheduler.py` 自己 docstring 里写死的
   （否则一次研究跑的时机会变成"书此刻在做什么"的函数）；后者理由相反而对称——时间规则是一句**关于**
   实盘记录的陈述，所以它跑在交易机上、紧挨着会据此发起的那次事务。
3. **canary 需要交易凭据——这是 Q5 的真正代价，2026-09-09 核出来的。** `run_shadow.sh` 用 `--dry-run`，
   而 `--dry-run` 走 `build_venue`，读 `STARQUANT_BINANCE_API_KEY/SECRET`（`config.py:272`）；引擎启动就要
   `venue.rules()` 和持仓快照。所以 §5 的 **L4 层不能放在一台只有数据权限的研究机上**。两条路，都要付：
   要么研究机也持有交易凭据（多一个存密钥的地方，多一台机器能下单），要么 canary 留在交易机上——那研究机
   就不是"全流程"的，§2 的两机图要改。**不写这条的跨机契约会在第一次 canary 上失败。**
4. **`universe.json` 是共享观察，只有拿账户交易的那个进程可以重排它**（`may_rerank_shared_pool`）。
   研究机的任何跑法都不许写它：每一份被引用的证据都记着它产出时的 universe 指纹，改了那个文件就让
   armed 循环的证据失效、数据集闸拒绝它下一次启动。09-08 一天里被触发了两次（一次 canary、一次裸
   `--paper`），两次都是在同一台机器上——跨机只会让它更难看见。

### 已裁（2026-09-12）

**操作者裁定：只用本机，不增加能下单的机器。** 于是第 3 条那个代价不必付——canary 需要的交易凭据就在
这台机器上，L4 不再没有归处。当天 13:21Z 启动首次浸泡（`deploy/com.starquant.shadow.plist`，168 周期，
约 2026-09-19 完成）。`com.starquant.research.plist` / `run_research.sh` 判**明写不做**，不是欠账。

本节其余四条规则在单机下不产生动作，保留原样：它们是拆机那天要读的东西，而拆机现在是一个被回答过的
问题。要重开，需要一次新的具名裁定。

## 16. Phase 7 Kill 处置表

| Kill | 处置 | 落点 |
| --- | --- | --- |
| AR-01 P0 | **CLOSED**：R0 保持按策略桶；证据已在现行门下重出（PASS 1.81 / 门 1.49） | §4 R0、§17 |
| AR-02 P0 | **CLOSED（2026-09-09）**：选项 b 改写为时间规则并标注非证据；AC-G6′ 已跑——三条序列都由**真引擎写记录、真 tenure 读回来**，两半此前各自有测试而从不相接，而这条缝正是本项目缺陷所在（`probes_from_registry` 漏掉主 ledger、记录按 ledger 名而状态按策略 id、stop 阈值不进 digest）| §3、§10 |
| AR-03 | CLOSED：AC-G0 改例外清单 | §9–10 |
| AR-04 | CLOSED：Canary 改标签；补 `--state-dir` | §5 |
| AR-05 | MITIGATED：R8 改归因口径 + 告警 + 宽限 | §4 |
| AR-06 | CLOSED：Grandfather 条款 | §3 |
| AR-07 | CLOSED：证据构造 ≡ 实盘构造进转移条件 | §3 |
| AR-08 | **ACCEPTED（操作者）**：选 L3 不选 L2 | §0 |
| AR-09 | CLOSED：M-G05 | §11 |
| AR-10 | MITIGATED：Pre-A 收窄为 Pre-A′（决策 vs 观察） | 头部 |
| AR-11 | **ACCEPTED（操作者，Q8）**：90% 是希望不是硬要求 | §14 |
| AR-12 | CLOSED：Phase 4a/4b 拆开 | §8 |
| AR-13 | CLOSED：R 表标来源 | §4 |
| AR-14 | CLOSED：R2 加重开路径 | §4 |
| AR-15 | **CLOSED（2026-09-10）**：面板随 warmup 伸缩已修；且 09-09 发现修复只覆盖 `default_params`（tsmom warmup 101 / 实盘 721），现已同时跑 registry 实参 | §5、§7 |
| AR-16 | CLOSED：范围对账 | §1 |
| AR-17 | **CLOSED（2026-09-12 操作者裁定：只用本机）** | §14 Q5、§21 |
| AR-18 | **ACCEPTED（操作者，Q9）**：单次晋级/降级不设人类确认点；残余风险由 R6 回滚 + Canary + R3 + P&L stop 承接；R8 宽限保留 | §0、§14 |
| AR-19 | CLOSED：Claim Register | §13 |
| AR-20 | CLOSED：逐判据 no-decision | §5 |

## 17. 证据重出与重启 #6（2026-09-08，操作者授权）

| 项 | tsmom | flow |
| --- | --- | --- |
| 协议 | 两臂 {crowding_window:[0,72]}、pit、5 fold、4000/50/6、`--prior-trials 60`，**guards + exits 默认开** | `--main tsmom --sleeve flow`、1/3、pit + static、5 fold、4000/50/6、`--prior-trials 39` |
| 结果 | **PASS**：OOS 1.81（093705Z 1.77）、门 1.49 @ N=146、p_family 0.00、CPCV 1.86/q05 1.36、成本×2 1.69、DSR p 0.31（只报）、PBO 0.09；DL-R4 标注仍在 | **REJECT**（同四项）：delta 0.00（原 +0.0046）、sleeve WEAK_PASS 0.59、static −0.08 |
| 报告 | `tsmom-validation-20260908T105259Z` sha256 `11f91787…` | `book-tsmom-flow-20260908T105322Z` sha256 `385b2239…` |
| ledger | +2 | +2（pit / static 各一）；全库 unique 试验 673 → **677** |
| registry | 指针已换；`registry_evidence_problems` = []；`registry_digest` 不变（16671c63a12e）→ 无分叉、M-010 窗口不清零 | 同左 |
| 重启 #6 | 11:00:02Z kickstart；PID 66596 → 83421；首周期 11:00:31Z（收盘后 29 s，DL-L4 窗口内）；18 币全 NO_TRADE_BAND；`live status --check` 通过 | — |

## 18. Phase 0 执行结果（2026-09-08）

`starquant_governance`（`policy` / `lifecycle` / `replay`，1,036 行）+ `starquant governance replay`。
产物 `docs/analysis/2026-09-08-governance-phase0-replay.md`（生成物，规则版本变更后重跑）；
完整记录见 RESEARCH_LOG 同日条目。

| 项 | 结果 |
| --- | --- |
| AC-G0 | **通过**：规则复现 10 项、差异 29 条、未归因 **0** 条 |
| A 描述性回放 | 18 个历史指针中规则认得 4 份 book（3 份凭 D-029 书面承认）+ 1 份 validation；其余 13 份归因到规则版本（8 份无 `oos_selection`、5 份 gate 无名）。**反方向更有力**：9 份从未采纳的 PASS，规则也都不采纳且理由与历史一致，其中 `mined_594a12f9307a15d9` 走完整链条（PASS → book REJECT `oos_mdd_worsening`） |
| B 属性测试 | R3 / R4 / R7 / RETIRED 吸收态 / no-decision 零变更 / 拒绝必具名，各 200 组随机序列零违反 |
| D 时间回放 | 148 个可判周期（ERROR 1、SKIPPED 4、重基 1 已排除）。**探针 P&L stop 从未触发**，故 R5 / R7 未被真实事件走过；probe→main 覆盖 0.21 个窗口（需 9） |
| **新发现（改 Phase 1 顺序）** | `candidate → validated` 的四条判据里两条读的字段没人写：DL-K3 预登记指针、KILL-AR-07 构造比对（digest 不可反解）。**状态机今天一个候选也放不进去**，故 Phase 1 先做 DL-G9 |
| 被挂起的判据 | 共 6 条（上述 2 条 + book 报告无 `slippage_stress`、corr/换手无字段链回 book、M-011 随 DL-D4、Canary 尚不存在），每条带修法与所属 Phase |
| 例外清单 | 七条（D-019 / D-029 / K-EX07 / Q7 / P10 cell B / P11 / P13），每条记「为什么不该写成规则」。D-029 是唯一已部分成为规则的一条 |
| 未能归因的形状 | 6.2 天内构造改了 **4** 次（首版数成 6 次——它按原始 digest 数，漏了 `CONSTRUCTION_ALIASES`：`unit_mode` 与四个 `regime_*` 改了指纹但行为一字未变，已在别名表里声明。已修并加回归测试）。规则允许每 30 天一次；归 `evidence_gap`：digest 不可反解，改了什么读不出来。其中 2 次可读为**回滚**（digest 回到旧值），正是 R6 要处理的形状 |
| 实盘影响 | 无：零重启、零 registry 改动、零 ledger 行 |

## 19. Q-CRITICAL 与 Q2 裁定（2026-09-08）

### Q-CRITICAL：维持 Out，冲击模型现在就建

真实资金的五道门与今天的状态——**三道是时间/数据约束，一道要一次裁定，只有一道能靠干活关掉**：

| 门 | 状态 | 性质 |
| --- | --- | --- |
| 审计三问① 四层书的 OOS 出自哪份 artefact | **已关闭**（09-08 重出，`tsmom-validation-20260908T182204Z` OOS 1.8087 PASS，sha256 `da400f4d…` 钉在 registry（**2026-09-10 更正**：原写 105259Z / `11f91787…`，已被取代）） | — |
| 审计三问② M-Q08 新尺子 ≥ 30 笔 | **开着**：新尺子 2026-09-07T13:48Z 起，2026-09-09 实测 6 笔、**2026-09-10 实测 7 笔 / 30**（旧尺子的 86 笔没有 `decision_close`，不可用）。按当前速率约 2–4 周 | 数据 |
| 审计三问③ 回测权益 ≠ 实盘权益 | **已裁定（2026-09-08）：分母保持总权益**（场所自己的保证金基准；交叉保证金下抵押品确实吸收亏损）。顺周期放大器转 **ACCEPTED**（Owner：操作者）。**2026-09-09 复裁：本节正文曾写“仍然开着”，与本行矛盾；操作者裁定以本行为准**（见下第 3 条） | 已关 |
| KILL-A / KILL-Q12 冲击成本模型 | **已关（2026-09-09）**：平方根律已建、`capital=0` 精确退化为平模型、容量曲线可算，AC-C1 通过——impact 定价下 tsmom 走前 OOS **1.7629**，桶门 1.4884 @ N=148、**全库门 1.6632 @ N=683 也过**（首次）。系数 1.0 出自股票文献，对本场所记 E5。**`vol_target` 的重推仍未做**，属构造改动（Phase 4a）：以 10 万上真钱前必须先做那一次 | 已关（唯一靠干活关掉的那道） |
| M-010 30 天干净窗口 | canonical 构造 `0dcd044d0158` 自 2026-09-04T15:02Z 未断，2026-09-09 实测 4.66 天、**2026-09-10 实测 5.0+ 天**（今天四次重启与全部改动都没动它），最早 **2026-10-04** | 时间 |

**裁定：维持 Out-of-Scope，不设日期；同时把冲击模型提到 Phase 1 并行做。** 理由是它是五道里唯一能靠干活
关掉的，做完之后剩下的全是时间与一次裁定，不再有"等我先建个模型"这句话可说。

**2026-09-09 状态更新：那句话现在真的说不出来了。** 五道门里 ①③④ 已关——④ 是干活关掉的，③ 是那次裁定，
① 在 09-08 重出时关的。**剩下的两道纯粹是等**：② 成交笔数 **6/30**，⑤ 干净窗口 **4.66/30 天**（最早 10-04）。
真实资金仍 Out，且**不因为门少了就改**：门关完之后还要一次具名裁定，那是 §1 写的入口。

三条连带后果，写下来而不是让它以后咬人：

1. **成本模型不在 `construction_fingerprint` 里，所以建它不清零 M-010。** 指纹含 portfolio / exits /
   guards / leverage / strategy_weights，不含成本。DL-C1 可以在 10-04 的 M-010 窗口内并行推进而不花掉它。
2. **但采纳它要重出证据。** `verdict.decide` 读 `cost_stress.x2`，换成本模型等于不动阈值地移动一道门——
   这正是 D-033/D-034（资金费修正）走过的路，先例是**重跑而不是加注释**。所以 DL-C1 的落地包含一次
   tsmom 重出，加 ledger 行、计入 R1 的每窗口 170 行预算。
3. **审计三问③已关。** 这一段原本写着"仍然开着，且不是本次裁定的一部分"，与同节第 381 行的表格
   直接矛盾——表格记的是操作者当天的裁定，正文是裁定之前的稿子留下的。**操作者 2026-09-09 复裁：
   以表格为准，③ 已关。** 它要的本来就是"权重的分母该不该是含抵押品的权益"这一次构造裁定而不是更多
   数据，而那次裁定已经做了：**分母保持总权益**（场所自己的保证金基准；交叉保证金下抵押品确实吸收亏损），
   顺周期放大器随之转 RISK-G11 的 **ACCEPTED**（Owner：操作者）。
   代码侧与这条一致：`collateral_drift` 的文档、`engine.py` 记录 `collateral` 那一行的注释都写着
   "记录而不相减，换分母是一次构造裁定"，量表只报告不改判据。真实资金重开时这道门读**已关**。
   *（写下这段矛盾本身值一笔：一份文件的表格与它自己的正文对同一道真实资金的门给出相反状态，
   而两处都是当天写的。今天扫代码扫出的是"声明与实现脱节"，这是同一形状发生在文档里。）*

### Q2：双层判据 + 诚实标注

| 层 | 指标 | 判据 | 窗口 | 诚实标注 |
| --- | --- | --- | --- | --- |
| 领先 | M-010 各策略实盘归因 Sharpe | 不劣于回测滚动窗口 q10 = **−1.52** | 30 天滚动 | **这是"没炸"判据，不是"在赚"判据**——与时间规则同一形状 |
| 滞后 | **M-G06** 归因年化 Sharpe | **点估计 ≥ 0**；NW t 只报告不作门 | **构造不变 ≥ 18 个月**，按 `canonical_construction` 计时 | 18 个月 SE = 0.82，仍然弱；这是现有数据密度下最强的可评判命题 |

为什么阈值是 0 而不是 0.5 或 1.7：**年化 Sharpe 的标准误 ≈ 1/√年**。当前记录 6.4 天 → SE 7.6；30 天 → 3.49；
12 个月 → 1.00；18 个月 → 0.82。在 t = 2 下把 1.7 与 0 分开需要 **1.38 年构造不变的干净数据**。任何正阈值在
12 个月上都会被噪声决定，所以取点估计 ≥ 0，并按 D-P2 对 Newey-West t 的处置——**报告，不执行**。

**为什么按策略而不是按整本书，以及它的代价。** M-010 已经是按策略的，M-G06 与它同口径才能比较。代价是可量化的：
另一本小书在 fraction 1/3 上会通过上限绑定改变主书的实现权重——实测（`book-tsmom-flow-20260908T105322Z`）
时点 universe 上 gross cap 绑定 **3.37%** 的 bar、symbol cap 绑定 **11.58%** 的 symbol-bar（静态 3.10% / 22.22%）。
**这不是零，按已知污染披露而不清零。** 取严格读法（按整本书、任何晋级都清零）的后果是：M-G06 只在一个
"18 个月零晋级"的世界里可评判——本方案自己的预期是全程 0–2 条进 probe，所以那个世界并非不可能，但
把它设成前提等于让治理线与盈利判据互斥。

**第一个可评判日期**：当前 canonical 构造自 2026-09-04T15:02Z 起未断，若不再改动，M-G06 的 18 个月落在
**2028-03-05**。每一次改构造（含每一次晋级）把这个日期整体推后 18 个月——这是"月度窗口"这个选择的
长期价格，写在这里以便下次有人想加快晋级节奏时能读到。

## 20. Phase 1 首两项交付（2026-09-08）

| DL | 结果 |
| --- | --- |
| **DL-G9 ✔** | `research validate --prereg <commit>` 写 `preregistration`（记 commit **自己的**提交时间）；新增 `evidence_construction_digest`，覆盖恰好 `construction_problems` 比对的三块，两侧各记一份同名字段；循环每进程落一次 `construction_full`（= 每次可能的构造改动一次）。治理侧改为按 artefact 年龄判定：字段在场就判，不在场才挂起 |
| **DL-C1 ✔（模型与曲线）** | 平方根律，`capital=0` 精确退化为现行平模型，归档报告逐位可复现。系数 1.0 出自股票文献，对本场所记 **E5**，本系统无法校准（唯一成交是 demo 的 40–800 USDT） |

**容量曲线**（系数 1.0，四层书 / 时点 universe，`scratchpad/impact_capacity_curve.py`）：

| 资金 | 净 Sharpe | 对平模型的差 | 成本/毛利 | 冲击占成本 |
| ---: | ---: | ---: | ---: | ---: |
| 0（平） | 1.9161 | — | 7.95% | 0% |
| 100,000 | 1.8670 | **−0.0491** | 10.30% | **22.8%** |
| 1,000,000 | 1.7609 | −0.1552 | 15.39% | 48.4% |
| 10,000,000 | 1.4251 | −0.4910 | 31.48% | 74.8% |

`live.demo.yaml` 早就把 **10 万 USDT** 写成"k 需在冲击模型下重推"的触发点；曲线证实那个点没选错。
**读拐点不读水平**——整条曲线随系数只按 √ 移动。

**DL-C1 明写未做**：`vol_target` 的重推。那是一次产生证据、消耗 ledger 行的研究运行，采纳它还是一次构造改动、
属批次窗口（Phase 4a）。DL-C1 交付的是让那次重推**可以做**。另一条近似：组合层护栏回放用平费率给自己的权益
路径定价，冲击下日内止损档会比重放的略早触发；移进回放会让它路径依赖于自己正在产生的量，故记录不修。

## Checkpoint（2026-09-09 三次更新）

| 项 | 值 |
| --- | --- |
| Phase | Phase 0 ✔ · Phase 1 **✔（2026-09-09 收口）**——DL 表六项全交付，块 5 的五条全部落地（`事件时间对齐契约` `6f6f21a`、`配对选择计费` `8ca081f`）· Phase 2 ✔ · **Phase 3 走了大半** · **Phase 4a / 4b / 5 未开始**。重启 #6/#7/#8/#9 ✔ |
| 块 5 收口的连带后果 | 「没它们，后面做了也不算数」这句解除了：**块 6 的 7 条重测不再被卡**（按 pit·0.30·D-034 重测，是下一个可开工的整块） |
| 32 条候选的实际进度 | **块 1（13 条）**：metrics→Panel 的 #16/#17 ✔、现货 ingest ✔（362/528 有现货腿，解锁 #11 基差 / #14 资金费套利 / #39 期现）、公共清算流 #19 **判定不可用**（币安 USDⓈ-M 无清算历史，唯一存在的币本位归档在实盘期前 23 个月停更 → 平价**不可能满足** → RISK-G3 该列不进实盘）；外部 API 五条中**两条已处置（2026-09-09）**——**#28 解锁判「不可得」**（唯一免费源是一份持续覆写的单版本文档，无 as-of；Wayback 仅存的两份带日期快照上，`aave` **已过去**的 14,140 个点有 409 个变了、最大 5.75 倍 → 时点表无法重建 → RISK-G3 该列不进实盘，**未写下载器**）、**#31 链上 ✔**（Coin Metrics Community 免费无 key，覆盖 **49/528 = 9.3%**；流量两列因逐格 `-status-time` 最长晚写 **769 天**被拒，计数三列收；契约由 blockchain.info 独立见证证伪，**355/355 vs 97/354、97/355**）、**#29 指数 ✔**（归档对 REST 偏移 **0** 时 24/24、前后各一桶 0/23——与 metrics 的 −1 桶正相反，这条对照就是「每源各自声明偏移」的理由）、**#30 社交判「不可得」**（付费源要 key；唯一免费的 Fear & Greed 有 3,139 条日频但**是全市场标量不是每币一列**、且无 vintage 接口所以 PIT 不可核）、**#32 宏观挂起**等一次操作者动作（ALFRED 是唯一能给修订史的，需一个免费注册的 key，本会话不注册账户）。**五条全部有裁定：两条落地、两条不可得、一条挂起。**<br>**块 2（6 条）**：hod #8 ✔、OI/LS 叶 ✔、regime 叶 ✔、**basis 叶 ✔（2026-09-09）**——18 个形状，与 `_funding_family` 的横截面相关**实测 +0.048、R² 0.064，不共线**（与预期相反）；**但今天不可挖也不可交易**：`_load` 不建现货 store 所以 mine 枚举 0 个，且现货没有 `Verification` 对象所以实盘闸关着。liquidation 叶**永久阻塞**（无数据可喂）。<br>**块 3（6 条）：6/6 已处置**——缠论 REFUTED、配对 #6 REFUTED、regime #47 结项不实现、上新 #27 阻塞（两道门，且样本 24 次）、岭回归 #22 阻塞（需 ≥3 因子）、meta-label #24 Won't。<br>**块 4（7 条）：7/7 已处置**——冲击模型 #43 ✔（`vol_target` 重推属 Phase 4a）、动态杠杆 #49 已有、回撤节流 #20 判否、**GARCH #35 / HRP #48 / VWAP #42 三条 REFUTED**、抵押品分母已裁定。<br>**块 6（7 条）：✔ 收口（2026-09-09）**——xsmom / carry / residual 三条重测完毕**全部 FAIL**；meanrev（gross Sharpe −1.73，成本出现之前就是错的）与 breakout（成本是毛利的 1606%、换手 17× tsmom）按「改变的条件动不了死因」**不跑**；节流 09-07 已重测（0.30 下两个 universe 都不过，代价是 D-017 限额的 4–5 倍）；regime 已结项。**七条无一进 probe，全部维持 REFUTED**，共花 **12 行**ledger（按字面跑七条要 56 行换 0 个新结论） |
| 前一版 Checkpoint 说错的两处 | ① 写「Phase 1 全部 DL 交付完」——对 DL 表是真的，但读起来像 Phase 1 完成了，而块 5 还差两条。② 写「Phase 3 块 3 结项」——块 3 只有 2/6 有结论，另外 3 条**根本没建**，「结项」是错词 |
| 操作者裁定（2026-09-09） | ① 主 ledger 必须有 stop → 已装并**在运行记录里可见**（06:00:14Z `probes={'main','flow_short'}`）；② probe→main 维持 9 个月；③ 维持单机；R1 预算放开（policy 0.3.0）；#8 现在写 → 已交付；Q4 按默认进 |
| G0–G7 | G0 PASS · G1 PASS · G2 PASS · G3 ACCEPTED · G4 PASS · G5 PARTIAL（AC-G5 要一次真浸泡） · G6 PARTIAL（AR-17 OPEN） · G7 **PARTIAL**（AC-G7 已跑、DL-G7 已交付，但 §9 的 DL-D5 现货 ingest 仍无实现，AC-G5 的真浸泡与 AC-L5 的首个全自动窗口都没跑过——按 H9 的字面条件这三条各自足以让它不是 PASS） |
| 治理线 | 自治 ENABLED；policy **0.3.0** digest `35e749f7fc0c`，**循环报的与磁盘一致**（新增比对）；事务 4 行、链闭合；`flow_short` 0/9 窗口 |
| 预算（2026-09-09 实测更正） | R1 行预算 **169 / 1700**（此前这一格误填 683——那是**全库 unique 试验数**，与分母不是同一个量；分子换了量分母没换）。全库 unique 现为 **1,999**（今天两轮 mine 各 +658）。**mine 轮次 3/4——本窗口只剩一轮**（窗口 2026-10-03 关） |
| 本轮找到并修的缺陷 | 共 **17** 条，同一形状：看起来在管事、实际什么都没管。<br>**不生效**：共享 universe、共享 metrics、钉住不生效、R8 梯子无调用者、`ensemble.turnover_penalty` 无实现。<br>**看不见**：DL-K3 比字符串、stop 阈值不进 digest、治理 digest 无读者、隔离在钉住背后缩小交易集、冲击模型不进试验签名、归因落在无定价 bar 上被丢。<br>**声明与实现脱节**：`gate_scope` / `report_whole_library_n` / `record_digest_every_cycle` / `no_decision_on_rebaseline` 无读者、`cost_stress` 未按标签计价、tenure 的「main→probe 不可达」已过期。 |
| 两道通用护栏 | ① 每个 policy 字段必须有生产读者（`test_every_threshold_has_a_consumer.py`）；② 改一片 registry 叶子必须动某个 digest，例外按名字列（`test_the_digest_sees_every_live_knob.py`）。**它们会抓到 R8 那条梯子和 stop 阈值那个洞，也会抓到下一条**——这是本轮最值钱的产出，不是任何单条修复 |
| 下一动作 | (a) metrics ingest 收尾（188/205，扫尾已挂）；(b) 用 OI/LS + hod 叶跑这一轮 mine（预算 169/1700、1/4 轮）；(c) L3 的 7 天软泡；(d) AC-G5 一次真候选浸泡 168 周期 |
| 仍未定（操作者） | ① 主 ledger stop 阈值 6% 是路线 B，`review_after_days: 30` 到期后按 30 天已实现归因重新按 −2σ 定；要变硬停是 `stop.halts: true` 一个字段。② **R8 梯子现在会自己缩仓**——这是全系统第一条不经人就改变仓位尺寸的控制。理由：它读的是归因不是权益（那两句「刻意不自动化」针对的是权益口径），补偿控制是 2 周期宽限 + 首次告警 + 两档都写在 `policy_digest()` 里。今天不改变任何行为（归因回撤 −0.23%，第一档 −35%）。要改成只告警不动作，是 `_risk_ladder` 里一处判断。③ DL-C1 的 `vol_target` 重推仍未做，属批次窗口（Phase 4a） |
| 时间约束，干不完的 | L3 7 天软泡；M-Q08 ≥30 笔；probe→main 9 个窗口（首个 2026-10-03 关）；M-G06 构造不变 18 个月（若不再改构造，2028-03-05） |


## 22. 2026-09-10 逐模块对账后的更正与新裁定

对账全文见 `docs/analysis/2026-09-09-plan-vs-code-audit.md`。本节只记**改变了本文件内容**的部分。

### 22.1 §1 的范围算术：51 = 32 + 7 + 12 重复计数

regime(#47) 与节流(#20) 各被数了两遍（一次在块 3/块 4，一次在块 6）。**不重复的候选是 49 条。**
§6 块 1 行按字面也只列得出 12 条而不是 13。范围对账（KILL-AR-16）的结论不变——块 0 的 12 条 Out、
块 6 的 7 条有前置——变的只是「51」这个总数，它是重复计数的产物。

### 22.2 §3 新增一条已实现的判据，和一条不可计算的发现

`probe → main` 的第三个条件「family gate 重算仍过」现已实现（`starquant_governance/family_gate.py`，
`starquant governance gate`），并接进 `lifecycle.evaluate` 的 `WINDOW_SURVIVED` 分支。

**新发现，需操作者在 2027-06 之前裁一次**：flow 的 registry 证据是一份 **book 报告**，book 报告不带
`oos_selection`，所以这条判据**对当前唯一在跑的 probe 不可计算**（读数 UNREADABLE）。默认 False 意味着
flow 会在第九个窗口停在 probe 而不是被晋级——不裁不会出错，但到时候要么给 flow 一份带 `oos_selection`
的证据，要么 §3 对「靠 book 报告进来的 probe」另写一条。

### 22.3 §5 L3 的判据互斥，已两算

见 RESEARCH_LOG 2026-09-10。字面口径在本场所**基本不可达**（0.318 ERROR/天 → 连续 7 天零 ERROR 10.8%），
而不可达的原因正是 §5 自己两段之后写的那个代理。`starquant live soak` 两种口径都算都打印，
`--check` 门在 no-decision 那条。**判据本身的裁定仍在操作者手上。**

### 22.4 §9 / §10 的行数与交叉引用

- §9 是 **14 行**不是 15（无独立 DL-G6，只有 DL-G6′）；§10 是 **12 行**不是 14。
- §9 的 DL-G2 / DL-D4 / DL-D5 三行的「验收」列指向 **AC-G2 / AC-D4 / AC-D5，§10 里没有这三行**。
- 方案点名的 T-xxx 测试 ID 多数在 `tests/` 里**不作为测试名存在**（等价测试在，名字不同）。这不是缺陷，
  但按 ID 去 grep 会一无所获。
- **AC-G1 引的「146 / 677」这一对数字磁盘上不存在**：tsmom 的真实双口径是 148/683 与 183/681；
  `146` 只出现在一份**没有 whole_library 块**的旧报告里。
- **DL-D5 不打 ✔ 是对的**，文末 Checkpoint 的「现货 ingest ✔」是错的——`.starquant/data/` 下一根现货
  bar 都没有。

### 22.5 §11 M-G05 / M-G06 仍是纯文档

两条都零代码。M-G05 是 Pre-A′（本方案自认的头号风险）的**唯一 falsifier**，今天没有任何可被触发的仪器。
M-G06 已于 2026-09-10 实现计算侧（当前构造仅 5 天，必然报 INSUFFICIENT_DATA，那正是它该说的话）。
**M-G05 要么实现落盘格式，要么把 §13 里 Pre-A′ 的 falsifier 划掉——二选一，不能像现在这样写着而没有。**

### 22.6 §12 RISK-G11 引的 73% 是测试 fixture 里的历史值

`collateral_drift` 今天实测 `repricing_share` **1.068**（equity_change +36.41、attributed_pnl −2.48、
collateral_repricing +38.89）。**106.8%——权益涨的部分多于全部是抵押品重估，书本身在亏钱。**
方向比 73% 更极端。原文引的 73% 钉在 `risk_budget.py` 的 docstring 和一条 `assert 0.72 < share < 0.74` 里。

### 22.7 §19 与 §20：`vol_target` 重推**已跑未采纳**，不是「仍未做」

P26 于 2026-09-08 跑完（`scratchpad/p26_vol_target_under_impact.py`，7 档 vol_target × 5 档 capital），
RESEARCH_LOG 两处状态表都记着「已跑（未采纳）」。§20 的「DL-C1 明写未做：`vol_target` 的重推」
应读作**未采纳**。采纳它仍是一次构造改动，属 Phase 4a，这一点不变。

### 22.8 §21 第 3 条的行号

「canary 需要交易凭据」结论成立，但引的 `config.py:272` 是函数定义行；**凭据实读在 `config.py:278-279`**。
另：跳过建 venue 的路径是 `--paper`，**不是 `--dry-run`**。
