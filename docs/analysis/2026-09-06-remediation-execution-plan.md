# 优化执行方案：StarQuant 质量体检报告的剩余问题（2026-09-06）

> 深度分析 V3.3 · **Checkpoint Resume**。本文件是 `docs/analysis/2026-09-05-system-quality-deep-analysis.md`（下称"报告"）的续篇：报告的 Phase 1–7 已 COMPLETE（含六角色独立复核，附录 C），Final Decision 为 GO（受控执行，操作者裁定，报告 §12.6）。本文件不重跑已完成的 Phase，只做三件事：(1) 复验已过期的 Evidence；(2) 对本方案引入的**新决策**做压缩的对抗审查；(3) 产出 Phase 8–10——Scope、Delivery Contract、Test/Acceptance、Learning Plan。**只生成方案，不执行**：本文件不改代码、不重启循环、不写 ledger、不推远端。
>
> - **Reading Check**：本次理解为「把报告复审后仍未处理的 8 条 Kill、§7.4 生产链路清单、Phase A 第 4 步、KILL-Q2/Q3 的五项欠账与 Phase B/C，编成一份可按批次交付、可测试、可验收、可回滚的执行方案；交付对象是单一操作者」。最高风险预设为 Pre-P1「剩余项应当全部做」——若不成立（操作者的 alpha 90% 目标与生产链路的非 alpha 行数冲突），方案从"全做"变为"Must 只保留无人值守最小集 + 尺子欠账 + 扩空间，其余按操作者裁定推迟"。本文件按后者写。
> - **Interaction Mode**：**Yellow**。事实全部可由仓库取证（E1）；三个未知项不改变框架方向：远端租约的介质、demo-fapi 对 `forceOrders` 的支持、B1 批次的 ratchet 处置。§8 的提问表一次问完。
> - **S/M/L**：**L**。命中：≥3 模块（live / cli / alpha / exchange / data）；触及资金链路（下单进程互斥、kill switch、平仓路径）；AI/策略/自动化维度为"自主决策 + 生产影响"（扩空间后的候选进入 ledger 即改变 DSR 分母）。
> - **当前 Gate 决策上限**：报告层 GO（受控执行）不变；**本方案自身**：B0/B1/B2 批次 GO（本地、可逆、无外部动作），B4 批次 **Weak GO**（远端介质与残余风险需操作者裁定），B5 的 KILL-Q11 部分 **Need Evidence**（三项核查先行）。
> - **外部动作授权**：**无**。执行时的两次实盘重启、任何 `trials.jsonl` 写入、任何远端介质的创建，都是执行阶段单独确认的动作，不由本文件授权。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision（本方案） | **GO（受控执行）**，分批：B0 尺子欠账 → B1 无人值守最小集（重启 #1）→ B2 扩空间 → B3 ledger 机械化 → B4 失联与强平可观测（重启 #2）→ B5 数据宽度。B0–B2 为 Must，B3–B4 为 Should，B5 为 Could；Phase C 不在本方案内契约化，等 §7.1.6 裁决。 |
| 最大价值 | B1 堵的是**当下**最真实的实盘风险：本机 7 个 worktree 里任一处 `starquant live run` 就是第二个交易同一账户的进程（KILL-R20，E-41 复验仍无锁）；B4 回答报告 §4.2 留给作者的第三个问题「循环失联后谁在多久内平仓」——今天的答案是**没有人**。 |
| 最大风险 | 两个：(a) 非 alpha 行数——B1 净增约 +210 行落在 live/cli，超过报告自己定的"≥100 行非 alpha 必须指名同量级删除"的规则（KILL-R12），同量级的删除不存在，只能由操作者裁定抬 ceiling 或砍项；(b) 熔断改为 exit 0 之后，书会静默停在那里直到操作者 reload——**告警去重与第二通道必须先于它落地**（KILL-P1）。 |
| Relative Value | 对每一项都比过 No-Build：B1 的替代是"继续靠运气"（重启后实测单进程是运气不是保证，报告 §12.1）；B4 的替代是"同机 `run_check.sh` + 第二告警通道、不做远端租约"——若操作者没有可用的远端介质，这就是 B4 的降级形态（Q1）。 |
| alpha 占比（诚实口径） | 按新增行数：B0+B1+B2 ≈ 55% alpha；全部六批 ≈ 32%。**低于 90% 目标**，原因与报告 §9 相同：先补生产链路。B3–B5 每一项都标为"非 alpha 但前置"，操作者可推迟 B4/B5 把占比拉回。 |
| 开放决策 | Q1 远端介质、Q2 B1 的 ratchet 处置、Q3 接受"主机死则仓位保持到操作者处理"的残余风险（§8 提问表）。 |
| G0–G7（本方案） | G0 PASS · G1 PASS（继承报告）· G2 PASS（E-41..E-45 复验）· G3 PASS · G4 PARTIAL（alpha 占比）· G5 PASS（B0–B3）/ PARTIAL（B4 介质未定）· G6 PASS（压缩审查，7 条 Kill 无 P0）· G7 **PASS**（本文件即测试矩阵，报告 G7 的缺口由此补上）。Quality Score 41/50。 |

---

## 1. Gate Summary

| Gate | 状态 | Evidence/Claim | 未通过项 | 决策上限 | 下一动作 | §6.4 的 13 条验收全部有结论（✔ 11 / N/A 1 / A-P3 带对照实验补证）；19 条 DL 与 4 条 A-P 假设逐条核过。**方案内无未完成项。** 门外仍是两件操作者裁定：P20 阳性候选的构造问题（回撤按敞口走不按预算走）、DL-D2 的摄入（Could，需先写 metrics 对齐契约） |
| --- | --- | --- | --- | --- | --- |
| G0 Interaction / Kill | PASS | §2 | 无 FATAL；K3（比较替代）与 K5（范围防火墙）命中已处理；K8（可转测试验收）由 §6 处理 | — | — |
| G1 Problem / Axiom | PASS（继承） | 报告 §5 | 问题在移除任何单一方案后仍成立：无锁、无失联平仓、尺子欠账、空间窄 | — | — |
| G2 Evidence / Reality | PASS | E-41..E-45 | 全部为 E1（代码与仓库状态复验）；两项 UNKNOWN 已登记为 A-P1 / A-P2 | — | Q1 |
| G3 Relative Value | PASS | §3 | 每批都比过 No-Build 与降级形态 | — | — |
| G4 Strategic / Economic | PARTIAL | C-P5 | alpha 占比低于操作者目标；机会成本已量化（§5.3） | 不得 Strong GO | 操作者裁定 B4/B5 是否推迟 |
| G5 System / Solution | PASS / PARTIAL | §4、§6 | B4 的远端介质与 `forceOrders` 在 demo 的可用性未核 | B4 Weak GO | Q1；15 分钟 demo 端点探测 |
| G6 Adversarial | PASS | §4 | 同一 Agent 压缩审查，锚定风险已声明；7 条 Kill，0 条 P0，2 条 P1 有明确关闭条件 | — | — |
| G7 Delivery / Learning | PASS | §6、§7 | 全部 P0/P1 DL 有 Source Trace、Test、Acceptance、Metric | — | 执行前操作者过一遍 §8 |

---

## 2. 证据复验、Claim、Assumption、Risk

### 2.1 复验证据（2026-09-06 22:00Z 后，主 checkout `2038bf4`）

| ID | 类型 | 来源 | 摘要 | 等级 |
| --- | --- | --- | --- | --- |
| E-41 | CODE | `grep` 于 starquant_live / starquant_cli / starquant_exchange / starquant_data | 无 `flock` / `--armed`；无 `late_seconds`；`config.py:81` kill switch 默认相对路径 `.starquant/live/KILL_SWITCH`；`reconciler.py:104` 撤销**全部**陈旧挂单、不按前缀；无告警去重；无 SIGTERM；无 `liquidationPrice` / `forceOrders` / `INSURANCE_CLEAR`；无 `tradable` 掩码；无远端租约。**报告 §7.4 清单一项未做。** | E1 |
| E-42 | CODE | `starquant_alpha/validation/verdict.py:28-40,83`；`starquant_cli/research_cmd.py:735`；`tests/alpha/test_fwer_selection_gate.py` | `pass_oos_t 2.0 / weak_oos_t 1.5` 仍是 `strong` 的必要条件；`p_family` 只在 CLI 打印；7 个门测试全部用独立零假设，无块自举 | E1 |
| E-43 | DATA+CODE | `reports/research/trials.jsonl`（145 行，tsmom 89 行 / 去重 63）；`ledger.py:100` | `n_trials = 去重 ledger 行 + 本次网格点 + 申报先验`；093705Z = 63 + 2 + 60 = 125，**其中 60 = 30 + 14（D-039 带格）+ 16（E-36 的网格）——+16 已申报**（registry 证据块注释；报告 §12.7 更正了初稿的 N=141）。下次同区间重放约 127 | E1 |
| E-44 | CODE | `deploy/com.starquant.live.plist:24-32`；`deploy/run_live.sh:17,24-25` | `KeepAlive.SuccessfulExit=false`、`ThrottleInterval 60`、`ExitTimeOut 30`；退出码 0 不再拉起（脚本注释自述）；凭据仍由 `~/.zshrc` 的 `eval` 取得；`--immediate` 无条件 | E1 |
| E-45 | CODE | `starquant_alpha/mining/expr.py`（16 个类，只读 `close` ×4 / `low` ×1 / `funding` ×1）；`starquant_alpha/panel.py:114-124`（`open / high / low / close / volume / quote_volume / trades / taker_buy_base / taker_buy_quote / funding / reference`） | be963ad 的 `Funding` 叶已在；Abs / Moment / Semi / Beta-Residual / Trades 五个节点未做；`trades`、`taker_buy_base` 等列在 Panel 里、无节点读它 | E1 |
| E-46 | CODE | `git worktree list` = 7；`tests/architecture/test_source_budget.py:536-543` | 并发来源仍在（KILL-R20）；CEILING 现为 alpha 5,321 / live 4,378 / cli 2,924 / data 1,375 / exchange 539 / shared 280 | E1 |
| E-47 | CODE | `_resolve_mined` 已进 `research_cmd.py:189`（`_entry`）与 `:1853`（baseline） | F7 的"一行"由并行会话在 P19 期间完成；mined 候选可 validate；**持久身份**（registry 存表达式、实盘可解析）仍未做 | E1 |

沿用报告的 E-18（稳态迟到 0/8）、E-20（无锁）、E-31（撤全部挂单）、E-32（income 类型）、E-35（引擎只在启动时建模）、E-37（7/18 币 18 单位止损不可下单）、E-40（tsmom WEAK_PASS 的算术）。

### 2.2 Claim Register（本方案新增；报告的 C-1..C-6 不重复）

| ID | 命题 | P级 | Axiom | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-P1 | 当下对 demo 书最真实的威胁是**第二个交易进程**，不是 alpha：7 个 worktree、凭据全局 eval、无锁、无 `--armed` | P0 | A1 | 若 worktree 只剩主 checkout 且凭据不再从 `~/.zshrc` 取 → 降 P2 | E-46, E-44, E-20 | **SUPPORTED** |
| C-P2 | 循环失联（主机死 / IP 封禁 / 循环活但下不了单）后**没有任何自动动作**把仓位平掉或阻止重建 | P0 | A1 | 若 `run_check.sh` 之外存在任何远端停机路径 → REFUTED | E-41, 报告 KILL-R2 | **SUPPORTED** |
| C-P3 | 把 NW t 门降为 reported 不改变任何一份既有报告的判定（tsmom t 3.3–4.0 远高于 2.0；mined 死在 Sharpe 门上） | P1 | A2 | 对 11 份带 `oos_selection` 的报告重算，任一判定翻转 → 重开 D-P2 | E-42 + 报告 E-39 | **UNKNOWN**（B0 第一件事就是算它） |
| C-P4 | 只读 Panel 现有列的五个节点可按 ≈45 行/节点交付，不新增"研究面板 ⊃ 实盘面板"义务 | P1 | A5 | 若任一节点需要 Panel 新字段或实盘取数 → 该节点移到 Phase B | E-45, 报告 KILL-R28 | SUPPORTED |
| C-P5 | 本方案按新增行数的 alpha 占比 ≈ 32%（全做）/ ≈ 55%（B0–B2），低于操作者的 90% 目标，且无法靠口径挽回 | P1 | A4 | 若操作者接受"非 alpha 但前置"的显式记账 → 可执行；否则砍 B4/B5 | §5.3 | PARTIAL |
| C-P6 | KILL-Q5 的签名扩展只对**未来**的运行计费，不会追溯改变 093705Z 的 N=125 | P2 | A2 | 若实现时把历史 scratch 扫描也回填进 ledger → tsmom 阈值再抬，须重新裁定 | E-43 | SUPPORTED（设计约束，见 DL-K1） |

### 2.3 Assumption Register

| ID | 假设 | 依据 | 最小验证 | 未通过动作 | 决策上限 |
| --- | --- | --- | --- | --- | --- |
| A-P1 | 存在一个循环能 GET、操作者能从手机 PUT 的远端介质（对象存储 / 私有 GitHub 文件 / KV），凭据可与交易 key 分离 | 报告 KILL-R2 假定"异机或云端"，未指定 | Q1 一句话回答 | B4 降级为"同机 + 第二通道 + 只告警"，KILL-Q16 保持 OPEN | B4 Weak GO |
| A-P2 | demo-fapi 支持 `GET /fapi/v1/positionRisk`（含 `liquidationPrice`）与 `GET /fapi/v1/forceOrders` | 报告 E-21 只核了下单端点 | 15 分钟：只读 GET 各一次 | `forceOrders` 不可用 → 强平可观测只留 `liquidationPrice` 距离 + INSURANCE_CLEAR 桶 | DL-X1 范围缩小 |
| A-P3 | `KeepAlive.SuccessfulExit=false` 下退出码 0 不再拉起 | `run_live.sh:24` 自述；launchd 文档 | 重启 #1 后用 `--cycles 1` 退出验证一次 | 改为退出码非零 + 进程内退避 | DL-L2 实现形态 |
| A-P4 | 一次实盘重启的启动耗时（拉数据 + 建模 + 对账）在 3 分钟内 | 报告 KILL-R6 提到 143 s 补跑 | 从 `cycles.jsonl` 最近 5 次重启周期的 `at − bar_close` 取中位数 | 窗口公式的启动项按实测替换 | DL-L4 的窗口参数 |

### 2.4 Risk Register（本方案）

| ID | 风险 | 关联 | 概率 | 影响 | 预警 | 缓解 | 失败动作 | 人类确认点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RISK-P1 | 熔断 exit 0 后无人知道书停了 | DL-L2 | 中 | 高（仓位无人管理数小时） | 心跳缺失 | **DL-L3 先于 DL-L2 合并**；exit 前告警必须成功送达至少一个通道 | 回退到非零退出 + 退避 | 重启 #1 前操作者确认第二通道已收到演练告警 |
| RISK-P2 | 每次部署重启都是 `--immediate` 整本书重建 | 全部 live 改动 | 高 | 中（迟到成交、7 bps × gross） | `late_seconds` | DL-L4 与重启 #1 同批；两次重启之外不再为部署重启 | 计入 M-Q03，不重开 M-010 | 每次重启由操作者执行并记 RESEARCH_LOG |
| RISK-P3 | 远端租约取不到即 reduce-only，把远端故障变成交易停摆 | DL-X2 | 中 | 中 | 连续 N 周期 lease miss 计数 | N=3 周期宽限；演练含"封远端出口不得触发" | 调 N 或改为只告警 | 演练结果由操作者签字 |
| RISK-P4 | KILL-Q5 钩子把 scratch 扫描计入 ledger，tsmom 的 N 再抬 | DL-K1 | 中 | 中（裁定的 headroom 更负） | 下次 validate 的 `ledger_trials` | 只对钩子落地**之后**的运行计费；历史手工 `--prior-trials` 不变 | 出现追溯计费 → 回退钩子 | — |
| RISK-P5 | B1 抬 live ceiling 约 +200 行而无同量级删除 | KILL-P2 | 确定 | 治理成本 | ratchet 测试 | Q2 由操作者选：抬升并写理由 / 砍 DL-L6 与第二通道 | 移出 Must | Q2 |
| RISK-P6 | 并行会话同时改 `verdict.py` / `ledger.py` / `engine.py` | 全部 | 中 | 合并冲突、静默覆盖 | `git worktree list` | 每批一个 worktree，合并列车按批；共享文件（ledger、`cycles.jsonl`）只追加 | 冲突以 main 为准重做 | — |

---

## 3. 需要新决策的三处设计（Option Set，压缩）

报告 §6/§7 已做过全局 Option Set；下面只列本方案引入的三个新选择。

### 3.1 远端停机的形态（KILL-Q16 / DL-X2）

| Option | 做什么 | 成本 | 覆盖的失联情形 | 可逆 | 结论 |
| --- | --- | --- | --- | --- | --- |
| O-X0 No-Build | 维持 `run_check.sh` 同机检查 | 0 | 0 / 3（同机同死） | — | 对照 |
| O-X1 同机 + 第二告警通道 + 只告警 | DL-L3 的第二通道即可 | +30 行 | "主机死"由**外部**看不到——仍 0 / 3，但告警多一条路 | 高 | Q1 答 B 时的降级形态 |
| **O-X2 远端租约（推荐）** | 循环每周期 GET 远端 sentinel；`STOP` 或连续 N 周期取不到 → 本地 engage kill switch（reduce-only）+ 告警；循环每周期 PUT 心跳；异机看门狗只持只读 key、只告警 | +150 行 live/deploy | 2 / 3："循环活但失联"→ reduce-only；"主机死"→ 2 bar 内告警。**第三种（主机死后自动平仓）明确不覆盖** | 高（sentinel 删除即恢复） | **推荐**，前提 A-P1 |
| O-X3 交易所侧灾难止损 | 原生 `STOP_MARKET closePosition` | 高 | 3 / 3 名义上，但 7/18 币不可下单（E-37） | 中 | 维持 Won't（D-012、KILL-Q10） |

### 3.2 KILL-Q8 的"7 天一次晋级"规则

报告 §7.1.4 第 5 条要求"ledger 层强制，否则从协议删除并把 Q8 记回 OPEN"。复验（E-43/E-47）：**validate 不写 registry 指针**，指针是人手改 YAML——这条规则没有可以拒绝写入的主体。

| Option | 结论 |
| --- | --- |
| 在 `live` 启动门比对两次 evidence 变更间隔 < 7 天则拒绝启动 | 否：会拒绝 P1-01 这类合法重出，且把研究纪律塞进实盘启动路径 |
| 架构测试读 `git log` 检查 registry evidence 变更间隔 | 否：同上，且测试依赖 git 历史 |
| **按规则自己的 else 分支：删除该条，Q8 靠第 1、2、7 条（时间戳校验 + 一本 ledger + 到达 validate 必计费）机械化，落地后记 MITIGATED** | **推荐**（D-P3），需操作者确认 |

### 3.3 B1 的 ratchet 处置

| Option | 结论 |
| --- | --- |
| 找 ≈200 行 live/cli 删除 | 不存在不削能力的候选：`paper.py` 与 `FakeVenue` 合并（≈100 行）会动 10 个测试文件，风险大于收益 |
| 砍 DL-L6（SIGTERM/原子写 −30）与第二通道（−15）把净增压到 ≈ +160 | 仍超 100；且 L6 是 L1-14 的既有发现 |
| **抬 ceiling 并在同一提交写理由，把"无人值守最小集"记为一次性的治理豁免** | **推荐**（D-P5），需操作者裁定（Q2）。 ratchet 的机制本来允许这样做；报告的"同量级删除"规则是复核角色加的，对这一批不可满足 |

---

## 4. 压缩的对抗审查（Phase 7，本方案层面）

独立性声明：同一 Agent；冻结输入为报告（`2038bf4` 版）与 §2 的复验证据；审查者读取了自己的方案草稿（锚定风险已声明）。角色：Delivery Saboteur、Complexity Accountant。

| Kill | 角色 | 攻击命题 | 关联 | 严重度 | 状态 | 关闭条件 / 触发动作 |
| --- | --- | --- | --- | --- | --- | --- |
| KILL-P1 | DS | 熔断改 exit 0 而第二通道未通 → 书静默停数小时，比现在的 60 s 热循环更坏 | DL-L2, DL-L3, RISK-P1 | **P1** | MITIGATED（排序约束） | DL-L3 合并且演练告警送达 → 才允许 DL-L2 上线；AC-L2 |
| KILL-P2 | CA | B1 净增 ≈ +210 非 alpha 行、零删除，违反报告 KILL-R12 的规则 | D-P5 | **P1** | **CLOSED 2026-09-06**（Q2 = A） | 操作者裁定抬 ceiling 并在同一提交写理由。规矩此后一直照办：2026-09-07 一天抬了五次，每次都带一句说明增长来自哪里；`PLAN_BUDGET` 一次未动 |
| KILL-P3 | DS | 远端租约"取不到即 reduce-only"：远端一次 10 分钟抖动就把书打成只减仓 | DL-X2, RISK-P3 | P1 | MITIGATED | N=3 周期宽限；演练路径 B（封远端出口）**不得触发**；M-P4 |
| KILL-P4 | DS | 两次重启各自 `--immediate` 重建整本书；DL-L4 若不在重启 #1 同批，第二次重启还要付一次 | DL-L4, RISK-P2 | P2 | MITIGATED | DL-L4 进 B1；重启 #2 是第一次享受两步启动的重启 |
| KILL-P5 | CA | KILL-Q5 签名扩展改变 `unique_trials` 的去重语义，旧行缺新字段 | DL-K1, C-P6 | P2 | MITIGATED | 旧行按"legacy"digest 去重（缺失字段 = 空串），新旧不互相折叠；测试 T-K1-3 |
| KILL-P6 | DS | 五个节点的预登记漏掉 validate 默认值与 `--grids`——P19 在同一件事上绊了五次 | DL-A1 | P2 | MITIGATED | 预登记模板强制列出 `min_train / purge / grids / prior-trials` 四项（§6.3） |
| KILL-P7 | CA | 方案把 Phase C 留白等于默认它会发生；GP/组合器/LLM 助理各 +数百行 alpha | D-P6 | P2 | ACCEPTED | Phase C 只在 §7.1.6 裁决后另开方案；本文件不为它写契约 |

Pre-Mortem（若 8 周后失败）：最可能的原因是**B1 之后再没有第二次重启**——B4 的介质决定悬而未决，失联问题继续靠运气；反向控制 = Q1 在 B1 合并前答复。第二可能是 B2 的五个族跑出一个 Sharpe 1.2 的候选，而 B3 的一本 ledger 还没落地，它的搜索费又靠手抄。反向控制 = DL-K2 与 DL-A1 同一周。

Final Kill Decision：最强反方 = KILL-P2（治理规则与最小集冲突）；未关闭 P0 = 0，P1 = 2（P1 有排序约束、P2 待 Q2）；无 P0 Claim 被推翻；必须改变的 Scope = Phase C 出契约。**本方案：GO（受控执行）**，B4 Weak GO。

---

## 5. Phase 8 · Scope 与顺序

### 5.1 MoSCoW

| 分类 | 批次 / 项 | 理由 |
| --- | --- | --- |
| **Must** | **B0** 尺子欠账（DL-R1..R4）· **B1** 无人值守最小集（DL-L1..L6，重启 #1）· **B2** 扩空间（DL-A1） | B0 是报告 §12.5 承认的欠账；B1 是 C-P1；B2 是操作者的 alpha 目标本身 |
| **Should** | **B3** ledger 机械化（DL-K1..K3）· **B4** 失联与强平可观测（DL-X1..X2，重启 #2） | B3 让 B2 的候选被诚实计费；B4 回答 §4.2 第三问，但依赖 Q1/Q3 |
| **Could** | **B5** 数据宽度（DL-D1 退市、DL-D2 metrics 三核查→吞吐实验→摄入、DL-D3 新叶节点）· mined 持久身份 | 只在 B2 阴性且需要新数据、或某 mined 候选 PASS 时启动 |
| **Won't** | 与报告 §9 一致：LLM 提案者、RL、逐仓、原生止盈/移动止损/原生灾难止损、用户数据流、第二本 ledger、随机表达式对照、TRIPPED 标记、多交易所、mainnet、 holdout；**新增**：Phase C 在本方案内契约化、KILL-Q8 的 7 天晋级上限（D-P3） | — |

### 5.2 顺序与两次重启

```text
B0 尺子欠账 ──┐（worktree，2 天，无重启）
B1 最小集   ──┴─► 合并列车 ─► 重启 #1（构造不变，M-010 窗口不清零；记 RESEARCH_LOG）
B2 扩空间（预登记提交 → 跑 → §7.1.6 裁决，1 周，无重启）
B3 ledger 机械化（3 天，无重启；DL-K2 与 B2 同周）
B4 失联 + 强平可观测 ──► 重启 #2（前提：Q1、Q3、A-P2 已答）
B5 数据（Phase B，2–3 周；KILL-Q11 三核查先于一切摄入代码）
Phase C：另开方案，前提是 §7.1.6 有裁决
```

硬约束：
- **KILL-Q17 构造冻结**：两次重启都不改 `construction_fingerprint` 与 registry digest；启动时 `live status --check` 与 `live verify` 必须一致（M-Q10 = 100%）。凡改构造的想法一律推到 Phase C 末。
- **并行会话**：每批一个 worktree、一个分支；共享文件只追加；合并前跑四步 CI；合并后由主 checkout 快进。
- **每批的 ratchet 记账**写在 DL 表的最后一列，抬升理由随提交。

### 5.3 alpha 占比（两种口径并列，与报告 §9 同法）

| 批次 | alpha 行 | 非 alpha 行 | 仪表口径（validation/mining 计 alpha） |
| --- | ---: | ---: | ---: |
| B0 | ≈ 60 | ≈ 10 | 86% |
| B1 | 0 | ≈ 220 | 0% |
| B2 | ≈ 225 + 预登记 | 0 | 100% |
| B3 | ≈ 40 | ≈ 80 | 33% |
| B4 | 0 | ≈ 190 | 0% |
| B5 | ≈ 60 | ≈ 300 | 17% |
| **B0–B2** | **≈ 285** | **≈ 230** | **≈ 55%** |
| **全部** | **≈ 385** | **≈ 800** | **≈ 32%** |

这就是 C-P5 与 G4 PARTIAL 的全部内容。操作者若坚持 90%，可做的选择只有推迟 B4/B5——不是改口径。

### 5.4 Scope Firewall

| Out-of-Scope | 原因 | 重开条件 |
| --- | --- | --- |
| Phase C（GP / 组合器 / LLM 离线助理） | 依赖 §7.1.6 裁决 | B2 跑完且裁决写入 RESEARCH_LOG |
| 原生灾难止损 | D-012、KILL-Q10、E-37 | Q3 答 B，且先记录重开条件变更决策 |
| mined 候选持久身份（registry 存表达式） | 无候选接近 PASS（P19 REFUTED） | 任一 mined 候选 PASS/WEAK_PASS |
| 用户数据流 / ws | 架构规则（KILL-R18） | 登记依赖白名单变更决策 |
| mainnet pre-flight（报告附录 D） | 操作者范围 | 操作者显式重开 |

### 5.5 Decision Log

| ID | 决策 | 备选 | 理由 | 可逆 | 重开条件 |
| --- | --- | --- | --- | --- | --- |
| D-P1 | 批次顺序 B0→B1→B2→B3→B4→B5，两次重启 | 按 Kill 优先级逐项、随做随重启 | 每次重启都是整本书重建（E-18）；批次化把重启压到两次 | 高 | 出现 P0 事故 |
| D-P2 | NW t 门降为 reported-not-enforced（改 D-020 语义） | 保留；或改阈值 | docstring 与操作者记忆都写明它 ≈ Sharpe×√年、不构成第二条件（KILL-R17）；**预登记：11 份报告零翻转（C-P3）** | 高（一行） | 任一翻转 |
| D-P3 | 删除 Q8 的"7 天一次晋级"条，Q8/Q9 靠时间戳校验 + 一本 ledger + 必计费机械化 | 启动门 / 架构测试强制 | 没有写指针的主体（§3.2） | 高 | 出现自动写指针的路径 |
| D-P4 | ~~远端停机取 O-X2~~ → **Q1 答 B，取 O-X1**：同机 + 第二通道 + 只告警；主机死后**不**自动平仓，残余风险由操作者 ACCEPTED（Q3 答 A，2026-09-06） | O-X2 / O-X3 | §3.1、§8 | 高 | 出现远端介质 → 重开 O-X2 |
| D-P5 | B1 抬 live/cli ceiling 并写理由，记为一次性治理豁免（**Q2 答 A，2026-09-06 生效**） | 砍项 | §3.3 | 中 | — |
| D-P6 | Phase C 不在本方案契约化 | 一并写 | KILL-P7 | 高 | §7.1.6 裁决 |
| D-P7 | 两次重启不清零 M-010 窗口（构造与信号不变） | 清零 | 报告 §12.4 的约定；D-026 指纹不变 | — | 任一重启改了构造 |

---

## 6. Phase 9 · Delivery Contracts

责任模型：Business/Product、Engineering、Test、Runtime、Learning Owner 均为操作者；**Approval Owner** 为操作者本人，涉及的人类确认点：两次实盘重启、任何 ledger 写入、远端介质的创建与凭据。Agent 不能替代 Approval Owner。

### 6.1 DL 表（来源链 → 实现 → 测试 → 验收 → 指标 → ratchet）

**B0 · 尺子欠账**（worktree `fix/ruler-debts`）

| DL | 来源链 | 实现（文件） | 测试 | 验收 | Metric | 行数 / ratchet |
| --- | --- | --- | --- | --- | --- | --- |
| DL-R1 NW t 降 reported | KILL-Q3 欠账 ← DL-Q2 ← KILL-R17 ← D-P2 | `verdict.py:83` 的 `strong` 去掉 `oos_t` 条件，`oos_t_stat` 进 reasons 文案；`VerdictThresholds.pass_oos_t/weak_oos_t` 改名为 `reported_oos_t_*` 或保留但不参与判定；docstring 写明 D-020 语义变更 | T-R1-1 独立零假设下判定不变；T-R1-2 `oos_t < 1.5` 不再单独致 FAIL；**T-R1-3（预登记）对 11 份既有报告重算 verdict，翻转数 = 0** | AC-R1 | M-P2 | alpha ±5 |
| DL-R2 `p_family` 进 reasons | KILL-Q3 欠账 | `verdict.py` reasons 追加 `p_family=…`；CLI 已有 | T-R2-1 reasons 含 `p_family` | AC-R1 | — | alpha +3 |
| DL-R3 相关噪声验收 + N_eff reported | DL-Q2 验收 ← KILL-R25 | `starquant_alpha/validation/multiple_testing.py` 加 `effective_trials(returns_matrix)`（Li–Ji 特征值法，**只报告不作门**）；`scripts/` 或 `tests/alpha/test_correlated_null_gate.py`（标 `slow`）：对真实面板做块自举生成 N=125 条噪声曲线，量分位数门通过率 | T-R3-1 通过率 ≤ 5%；T-R3-2 N_eff ≤ N 且对完全相关矩阵 = 1 | AC-R3 | M-Q04 | alpha +≈50 |
| DL-R4 registry 并列记录 | KILL-Q2 触发动作 ← §4.1 F1 | `config/alpha_registry.yaml` tsmom evidence 注释块加一段：诚实网格 OOS 1.485（`reports/research/scratch/…030942Z`，未记账）、分位数门下 WEAK_PASS 的裁定指针（报告 §12.6） | 无代码；`live status --check` 不受注释影响（T-R4-1 启动门 sha256 仍匹配——注释不在 sha256 范围内需确认，若在则同提交重出 sha） | AC-R4 | — | 0 |

**B1 · 无人值守最小集**（worktree `feat/unattended-minimum`，重启 #1）

| DL | 来源链 | 实现（文件） | 测试 | 验收 | Metric | 行数 / ratchet |
| --- | --- | --- | --- | --- | --- | --- |
| DL-L1 单实例锁 + `--armed` | KILL-Q7 ← KILL-R20 ← C-P1 | `starquant_live/lock.py`（新，`fcntl.flock`，锁文件 `~/Library/Application Support/starquant/<sha256(api_key)[:16]>.lock`，绝对路径）；`live_cmd.py` 非 dry-run 必须 `--armed` 且校验 `REPO == plist WorkingDirectory`；`live flatten` 抢同一把锁前先置 kill switch；被拒实例告警后 **exit 0**；`deploy/run_live.sh:25` 加 `--armed` | T-L1-1 第二进程（另一 worktree、另一 state_dir）被拒；T-L1-2 无 `--armed` 的非 dry-run 拒绝启动；T-L1-3 dry-run 不需要锁；T-L1-4 flatten 在循环存活时先 engage kill switch 再抢锁 | AC-L1 | M-P1 | live +≈70，cli +≈30 |
| DL-L2 熔断 → 告警 → exit 0 | L1-03 ← KILL-R29 ← A-P3 | `engine.py:261` 分支：告警（DL-L3 的去重通道）→ `SystemExit(0)`；`state.py:37` `consecutive_errors` 改为进程内、不持久化（**删除**）；不新增 TRIPPED | T-L2-1 达到上限后进程以 0 退出且告警已发；T-L2-2 重启后 `consecutive_errors` 从 0 开始 | AC-L2（**前置：AC-L3 通过**） | M-Q09 | live −8 / +10 |
| DL-L3 告警去重 + 第二通道 | L1-11 ← RISK-P1 ← KILL-P1 | `alerts.py`：按指纹（种类 + 符号 + 状态）边沿触发，同一指纹在 `dedup_window` 内只发一次；config 加 `alert_webhook_2`；`run_check.sh` 同源去重 | T-L3-1 同一告警连续 10 周期只发 1 次；T-L3-2 状态恢复后再触发再发；T-L3-3 第二通道空时不报错 | AC-L3 | — | live +≈30 |
| DL-L4 启动两步 + `late_seconds` | KILL-Q4 ← KILL-R6 ← E-18 | 启动**始终**只读对账 + 保护单核对（不下 rebalance 单）；rebalance 只在 `now − bar_close ≤ startup_window` 时执行，`startup_window = grace + ThrottleInterval(60) + startup_p50（A-P4 实测）` 写进 `config/live.demo.yaml`；窗口外 → 跳过本 bar 的再平衡，`missed_rebalances += 1`；trade 行加 `late_seconds`；日报加两列 | T-L4-1 窗口内重启 → 对账 + 再平衡；T-L4-2 窗口外重启 → 只对账，计数 +1，不下单；T-L4-3 `late_seconds = at − bar_close` 精确到秒 | AC-L4 | M-Q03 | live +≈40 |
| DL-L5 kill switch 绝对路径 + 按前缀撤单 + flatten 先 kill switch | L1-06 / L1-07 / L1-09 ← E-31 | `config.py:81` 默认改为 `state_dir` 下的绝对路径；`reconciler.py:104` 只撤 `bd-` / `bdflat-` 前缀；`engine.py` flatten 路径先 engage kill switch；启动时 `foreign_positions` 非空 → 告警而非静默 | T-L5-1 非本循环挂单不被撤；T-L5-2 从别的 cwd 运行 CLI kill switch 路径一致；T-L5-3 flatten 后下一周期不重建仓位 | AC-L5 | — | live +≈20 |
| DL-L6 SIGTERM + 原子追加 | L1-14 | `engine.py` 装 SIGTERM handler：完成当前周期的写盘后退出；`attribution.jsonl` 追加与水位线保存用 tmp + rename | T-L6-1 周期中途 SIGTERM → 记录完整、无半行；T-L6-2 水位线与归因一致 | AC-L6 | — | live +≈30 |

B1 合计 live ≈ +190 / cli ≈ +30，删除 ≈ −8。**KILL-P2 / Q2。**

**B2 · 扩空间**（worktree `feat/expr-nodes-panel-columns`；alpha）

| DL | 来源链 | 实现 | 测试 | 验收 | Metric | 行数 |
| --- | --- | --- | --- | --- | --- | --- |
| DL-A1 五个节点 + 预登记 + 运行 | C-3 ← §7.1.2/§7.1.6 ← KILL-R28 ← C-P4 | `expr.py`：`Abs(x)`、`Moment(x, k∈{3,4}, w)`、`Semi(x, w)`（下半方差）、`Residual(x, w)`（对等权市场收益回归的残差动量）、`Trades(w)`（读 `panel.trades`，成交笔数 / 均单大小）；量纲规则各自声明；`search.py` 各加一族；**预登记提交**（§6.3 模板）早于第一份报告；在 0.30 口径跑 267 + 五族，幸存者按 DL-K2 计费后 validate | T-A1-1 量纲规则拒绝跨量纲；T-A1-2 因果性（cutoff 后数据变、之前不变）；T-A1-3 规范化哈希稳定（新增节点不改旧候选 id——若不稳定则 KILL-R16 的"搜索空间版本"进签名）；T-A1-4 `Trades` 在 `panel.trades is None` 时拒绝而非填 0 | AC-A1 | M-Q02 / M-P3 | alpha +≈225 |

**B3 · ledger 机械化**（worktree `feat/one-ledger`）

| DL | 来源链 | 实现 | 测试 | 验收 | Metric | 行数 |
| --- | --- | --- | --- | --- | --- | --- |
| DL-K1 签名扩展 + `record_trial` 钩子 | KILL-Q5 ← E-15 ← C-P6 | `ledger.py` `TrialRecord` 加 `construction_digest / overlay_digest / symbol_set_hash / search_space_version`（可选字段，旧行为空串）；`signature` 含新字段；`research backtest / overlay / book` 与 scratch 入口经 `_record_trial` 追加；ledger 路径固定（`--out` 只改报告目录，不改 ledger） | T-K1-1 旧行与新行不互相折叠；T-K1-2 backtest 扫描 band 一次 → ledger +1；T-K1-3 `--out` 不能换出空 ledger；**T-K1-4 钩子落地前的历史不回填**（C-P6） | AC-K1 | M-Q05 | alpha +≈40 |
| DL-K2 mine → 一本 ledger | KILL-Q8/Q9 ← KILL-R16 | `mine` 每轮把 `declared_trials` 作为 TrialRecord（strategy = 族名，param_key = 候选 hash，sharpe = 全样本）经 `_record_trial` 追加；validate 对 `mined_*` 的先验从同一 ledger 按族聚合，`--prior-trials` 只补 ledger 外的手工坑 | T-K2-1 mine 一轮 238 候选 → ledger +238；T-K2-2 validate mined 候选的 `n_trials` 不再依赖手抄 | AC-K2 | M-Q05 | cli +≈50 |
| DL-K3 预登记时间戳校验 | KILL-Q8/Q9 第 1 条 ← KILL-R9 | `report weekly`：对每份新 validation 报告，在 `docs/RESEARCH_LOG.md` 的 git 历史里找到提及该 strategy/族的最早提交，其时间戳须早于报告时间戳；否则日报 FAIL 一行 | T-K3-1 报告早于预登记提交 → FAIL；T-K3-2 正常顺序 → PASS | AC-K3 | — | cli +≈30 |

**B4 · 失联与强平可观测**（worktree `feat/remote-lease`，重启 #2；前提 Q1/Q3/A-P2）

| DL | 来源链 | 实现 | 测试 | 验收 | Metric | 行数 |
| --- | --- | --- | --- | --- | --- | --- |
| DL-X1 强平可观测 + 保证金模式断言 | L1-05 ← KILL-R18/R19 ← E-32 | `starquant_exchange`：`position_risk()` 读 `liquidationPrice`；`force_orders()` 一次 GET（A-P2）；`attribution.py` INCOME_TYPES 加 `INSURANCE_CLEAR` 桶；启动断言 `marginType == CROSSED` 且 `multiAssetsMargin` 与验证口径一致（不一致 → 拒绝启动，不自动改）；每周期落盘 `min_liq_distance`（日波动单位） | T-X1-1 距离计算对多空方向正确；T-X1-2 断言失败拒绝启动；T-X1-3 INSURANCE_CLEAR 不再静默丢弃 | AC-X1 | M-Q06 | exchange +≈40，live +≈40 |
| DL-X2 远端租约 + 心跳推送 + 维护 sentinel + 演练 | KILL-Q16 ← DL-Q8 ← KILL-R2 ← C-P2 ← D-P4 | `starquant_live/lease.py`（新）：每周期 GET 远端 sentinel `{state: RUN|STOP|MAINT, expires_at}`；`STOP` 或连续 N=3 周期取不到/过期 → 本地 engage kill switch（reduce-only）+ 告警；每周期 PUT 心跳 `{cycle, phase, consecutive_errors, registry_digest, construction}`；`MAINT` 只抑制告警；`starquant live lease --renew 24h / --stop` 从任意机器执行；`deploy/watchdog.sh`（只读 key，只告警）；`deploy/drill.sh` 两条路径 | T-X2-1 STOP → 下一周期 reduce-only；T-X2-2 取不到 2 周期不触发、3 周期触发；T-X2-3 MAINT 不告警不停；T-X2-4 sentinel 删除后恢复 RUN；**演练** A：`launchctl unload` → 2 bar 内看门狗告警；B：封远端出口 → **不得**触发 | AC-X2 | M-Q07 / M-P4 | live +≈110，deploy 脚本 |

**B5 · 数据宽度**（Phase B；Could；只写入口条件，不写全契约）

| DL | 入口条件 | 第一步 | 停止条件 |
| --- | --- | --- | --- |
| DL-D1 退市日历 + 结算 + `Panel.tradable` | B2 阴性或任一候选依赖退市期数据 | 从 exchangeInfo 状态快照或零量连续段推导日历；LUNA / FTT / ALPACA 三事件重放 | `frozen_symbol_bars > 0` |
| DL-D2 metrics 三核查 → 吞吐实验 → 摄入 | **Need Evidence**：归档发布时刻、REST 桶可得时延、同桶值差三项 15 分钟核查 | 20 币 × 1 年吞吐实验（> 3 天 → 缩到池内 45 币） | 任一核查不可核 → 只做研究诊断，不进实盘信号 |
| DL-D3 MarkGap 等新叶节点 | DL-D2 落地 | 与 `markPriceKlines` 摄入同提交 | 新叶重新制造"研究面板 ⊃ 实盘面板"义务 → 先补 M-011 平价 |

### 6.2 测试矩阵（C.4 最低覆盖对照）

| Test ID | DL | 类型 | 覆盖 | 前置 | 操作 | 预期 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-R1-3 | DL-R1 | 回归（预登记） | 历史兼容 | 11 份带 `oos_selection` 的报告 | 用新 verdict 重算 | 翻转 = 0；否则 D-P2 重开 | 脚本输出表进 RESEARCH_LOG |
| T-R3-1 | DL-R3 | 实验（slow） | 数据正确性 | 真实面板 | 块自举 N=125 噪声 × 200 次 | 分位数门通过率 ≤ 5% | 测试日志 |
| T-L1-1 | DL-L1 | 集成 | 并发 / 幂等 | 主进程持锁 | 从另一 worktree 启动第二实例 | 被拒、告警一条、exit 0 | 两个进程日志 |
| T-L1-2 | DL-L1 | 单元 | 权限 | — | 非 dry-run 缺 `--armed` | 拒绝启动，退出码非零、不告警 | pytest |
| T-L2-1 | DL-L2 | 单元 | 异常路径 | fake venue 连续失败 12 次 | 跑周期 | 告警已发（去重通道）→ `SystemExit(0)` | pytest |
| T-L3-1 | DL-L3 | 单元 | 告警 | 同一故障持续 | 10 个周期 | 1 条告警；恢复后再故障 → 第 2 条 | pytest |
| T-L4-2 | DL-L4 | 单元 | 边界 | 时钟置于 bar_close + window + 1 s | 启动 | 只对账、`missed_rebalances = 1`、零订单 | pytest |
| T-L5-1 | DL-L5 | 单元 | 安全 | 账户有非 `bd-` 挂单 | 启动对账 | 该单未被撤；`foreign_positions` 告警 | pytest |
| T-L6-1 | DL-L6 | 集成 | 降级 | 周期中途 | 发 SIGTERM | 归因文件行数完整、可 JSON 解析 | pytest |
| T-A1-2 | DL-A1 | 因果 | 数据泄漏 | 合成面板 | cutoff 后数据置换 | cutoff 前输出逐位不变 | pytest |
| T-A1-3 | DL-A1 | 回归 | 历史兼容 | P17/P19 shortlist | 新增节点后重枚举 | 旧候选 id 不变（否则签名加版本） | pytest |
| T-K1-1 | DL-K1 | 单元 | 迁移 / 兼容 | 旧格式 ledger 行 | 读入 + 去重 | 旧行不与新行折叠，`n_trials` 不变 | pytest |
| T-K1-4 | DL-K1 | 单元 | 迁移 | 钩子落地 | 跑一次 backtest | ledger 只 +1，无回填 | pytest + ledger diff |
| T-K2-1 | DL-K2 | 集成 | 数据正确性 | mine 一轮 | 完成 | ledger + `evaluated` 行，族名正确 | ledger diff |
| T-K3-1 | DL-K3 | 单元 | 流程 | 报告时间戳早于预登记提交 | `report weekly` | FAIL 行 | pytest |
| T-X1-2 | DL-X1 | 单元 | 安全 | fake venue 返回 ISOLATED | 启动 | 拒绝启动，不改模式 | pytest |
| T-X2-2 | DL-X2 | 单元 | 依赖失败 | 远端不可达 | 2 周期 / 3 周期 | 不触发 / 触发 reduce-only + 告警 | pytest |
| T-X2-4 | DL-X2 | 单元 | 回滚 | STOP 后删除 sentinel | 下一周期 | 恢复 RUN，kill switch 需操作者显式解除（不自动） | pytest |
| DRILL-A | DL-X2 | 演练 | 运维 | demo 循环运行中 | `launchctl unload` | ≤ 2 bar 看门狗告警；仓位不动（D-P4 残余） | 演练记录 |
| DRILL-B | DL-X2 | 演练 | 误报 | 循环运行中 | 封远端出口 10 分钟 | 不触发；恢复后无告警风暴 | 演练记录 |
| CI-ALL | 每批 | 回归 | 全部 | worktree | ruff format / ruff check / mypy / pytest -m "not network" | 全绿；ratchet 抬升带理由 | CI 输出 |

### 6.3 预登记模板（DL-A1 每族一条，先提交后跑；P19 §六的五层教训）

```text
族：<名>  节点：<Expr>  参数网格：<…>  基线：tsmom-1h（registry 当前参数）
口径：vol_target 0.30 / --universe pit / 成本 ×2 / interval 1h
判定工具默认值（显式写出，不依赖默认）：--min-train 4000 --purge 50 --folds 5 --cpcv-groups 6 --grids <与 mine 相同的网格串>
计费：mine 的 evaluated 经 DL-K2 入 ledger；validate 时 --prior-trials 只补 ledger 外的手工坑（当前 tsmom 为 60 + 16）
预期：<阴性 / 阳性>；falsifier：边际 Sharpe ≥ +0.05 且相关 < 0.5 且过分位数门（p_family 报出）
```

### 6.4 Acceptance（三层）

| AC | DL | 层级 | 前置 | 操作 / 观察 | 客观预期 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| AC-R1 | R1/R2 | Functional | B0 合并 | 对 093705Z 与 P19 三份重跑 verdict（不写 ledger，`--out` scratch） | 判定不变；reasons 含 `oos_t_stat`（reported）与 `p_family` | 回退 D-P2 |
| AC-R3 | R3 | Hypothesis | 面板可用 | 跑 slow 测试 | 通过率 ≤ 5%；N_eff 报出且 < N | 重查公式 |
| AC-R4 | R4 | Functional | 注释提交 | `live status --check` | `registry: matches the running loop` | 重出 sha |
| AC-L1 | L1 | Scenario | 重启 #1 后 | 从另一 worktree `starquant live run --allow-unvalidated --armed` | 被拒 + 一条告警 + exit 0；主循环无异常 | 修锁 |
| AC-L2 | L2 | Scenario | **AC-L3 已过** | 在 dry-run 副本注入 12 次连续失败 | 退出码 0、两通道各一条告警、launchd 不拉起 | 回退到非零退出 |
| AC-L3 | L3 | Scenario | 第二通道配置 | 触发一次演练告警 | 两通道各收到 1 条；重复触发 10 次仍 1 条 | 修去重 |
| AC-L4 | L4 | Scenario | 重启 #1 | 观察重启周期 | 只对账 + 保护单核对；再平衡受窗口约束；日报有 `late_seconds` 与 `missed_rebalances` 列 | 修窗口 |
| AC-L5 | L5 | Functional | 重启 #1 | 手工挂一张非 `bd-` 单再重启 | 该单仍在；日志告警 foreign | 修过滤 |
| AC-L6 | L6 | Functional | 重启 #1 | `launchctl unload`（SIGTERM） | 归因与水位线完整 | 修 handler |
| AC-A1 | A1 | Hypothesis | 预登记提交在先 | 跑 267 + 五族 | §7.1.6 裁决写入 RESEARCH_LOG（正负都算成功） | 转数据宽度 |
| AC-K1/K2 | K1/K2 | Functional | B3 合并 | 各跑一次 backtest 扫描与 mine | ledger 行数按预期增加；无回填 | 回退钩子 |
| AC-X1 | X1 | Functional | 重启 #2 | 看 `cycles.jsonl` | 每周期有 `min_liq_distance`；启动断言通过 | 修 |
| AC-X2 | X2 | Scenario | 远端介质就绪 | DRILL-A / DRILL-B | A：≤ 2 bar 告警；B：不触发 | 调 N / 回退 O-X1 |

### 6.5 Source Trace Matrix（P0/P1）

| DL | Problem/JTBD | Evidence | Claim | Decision | Gate/Kill | Scope | Test/AC | Metric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DL-R1..R4 | 报告 §5「筛出也不敢信」 | E-42, E-39, E-40 | C-2, C-P3 | D-P2 | KILL-Q2/Q3 欠账 | Must B0 | T-R*, AC-R* | M-P2, M-Q04 |
| DL-L1 | 「无人值守单操作者」 | E-46, E-44, E-20 | C-P1 | D-P1, D-P5 | KILL-Q7, KILL-P2 | Must B1 | T-L1-*, AC-L1 | M-P1 |
| DL-L2/L3 | 同上 | E-44 | — | D-P1 | L1-03, L1-11, KILL-P1 | Must B1 | T-L2/L3, AC-L2/L3 | M-Q09 |
| DL-L4 | 报告 §4.1 L1-01 | E-18 | — | D-P7 | KILL-Q4 | Must B1 | T-L4, AC-L4 | M-Q03 |
| DL-L5/L6 | 报告 §4.1 生产链路 | E-31, E-41 | — | D-P1 | L1-06/07/09/14 | Must B1 | T-L5/L6 | — |
| DL-A1 | 报告 §7.1 alpha 供给 | E-45, E-05 | C-3, C-P4 | D-P1 | KILL-R28, KILL-P6 | Must B2 | T-A1-*, AC-A1 | M-Q02, M-P3 |
| DL-K1..K3 | 报告 §7.1.4 计费协议 | E-43, E-15 | C-P6 | D-P3 | KILL-Q5/Q8/Q9, KILL-P5 | Should B3 | T-K*, AC-K* | M-Q05 |
| DL-X1 | 报告 §4.2 Ⅴ | E-32, E-37 | C-6 | D-P1 | L1-05, KILL-R18/R19 | Should B4 | T-X1, AC-X1 | M-Q06 |
| DL-X2 | 报告 §4.2 第三问 | E-41, KILL-R2 | C-P2 | D-P4 | KILL-Q16, KILL-P3 | Should B4（Weak GO） | T-X2, DRILL-*, AC-X2 | M-Q07, M-P4 |

---

## 7. Phase 10 · Learning Plan

| Metric | Claim | 指标 | 基线 | 阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| M-P1 | C-P1 | 第二实例被拒演练 | 无锁 | 被拒且告警 1 条 | 重启 #1 后一次 + 每月 | 修锁 |
| M-P2 | C-P3 | NW t 降级后既有报告判定翻转数 | — | 0 | B0 合并前 | D-P2 重开 |
| M-P3 | C-3 | 五族最优边际 Sharpe（以 267 为基数，0.30 口径） | −0.08（P14）/ P17 四臂 | ≥ +0.05 且相关 < 0.5 且过分位数门 | B2 末 | 转 B5 |
| M-P4 | C-P2 | 租约演练：路径 A 告警时延 / 路径 B 误触发 | 无 | ≤ 2 bar / 0 次 | 重启 #2 后 + 每月 | 调 N / 回退 O-X1 |
| M-Q03 | KILL-Q4 | 迟到入场仓位的 bar 小时占比 + `missed_rebalances` | 稳态 0/8 | ≤ 5% / 0 | 重启 #1 后 7 天 | 查重启原因 |
| M-Q04 | C-2 | 相关噪声（块自举）下门的通过率 | 未测 | ≤ 5% | B0 | 重查公式 |
| M-Q05 | KILL-Q5 | 评分入口写 ledger 覆盖率 | ~50% | 100% | B3 | 补钩子 |
| M-Q06 | C-6 | `min_liq_distance`（日波动单位） | 未测 | ≥ 10 | 每周期 | 告警 |
| M-Q08 | Pre-5 | 执行保真四项 | — | 换手 ±25%、滑点 ≤ 2× 模型、迟到 ≤ 5%、digest 一致 100% | 冻结后 30 天（自 09-06 10:19Z） | 复审执行层 |
| M-Q09 | Pre-5 | 连续无人干预天数、未处理失联次数 | 12 次重启 / 2 天 | ≥ 30 天 / 0 | 同上 | 复审运维 |
| M-Q10 | C-1(a) | registry digest 与已加载模型一致周期占比 | 100%（周期 98 起） | 100% | 每周期 | 拒绝启动 |
| M-010 | edge | 30 天 income Sharpe | — | 长期指标；两次重启不清零（D-P7） | 30 天滚动 | 仅记录 |

Post-Launch Review 触发点：重启 #1 + 7 天、B2 裁决、重启 #2 + 演练、B5 三核查。

---

## 8. 提问表（§3.2；一次问完，可只答 Q-CRITICAL）

| Q ID | 问题 | 关联 | 若 A | 若 B | 决策影响 |
| --- | --- | --- | --- | --- | --- |
| **Q-CRITICAL / Q1** | 有没有一个循环能 GET、你能从手机 PUT 的远端介质（对象存储桶 / 私有 GitHub 文件 / KV / 其他），凭据可与交易 key 分离？ | A-P1, DL-X2, KILL-Q16 | A 有 → B4 按 O-X2 交付，重启 #2 有内容 | B 没有 → B4 降级为 O-X1（同机 + 第二通道 + 只告警），KILL-Q16 保持 OPEN，§4.2 第三问的答案是"没有自动动作" | 决定 B4 是 Should 还是被砍 |
| Q2 | B1 净增 ≈ +210 行 live/cli 且无同量级删除：抬 ceiling 并写理由（D-P5），还是砍 DL-L6 与第二通道？ | KILL-P2, RISK-P5 | A 抬 → B1 全量 | B 砍 → L1-14 保持 OPEN，第二通道靠 `run_check.sh` | B1 范围 |
| Q3 | 接受"主机死后仓位保持到你处理，告警 ≤ 2 bar"作为 ACCEPTED 残余风险？ | D-P4, C-P2 | A 接受 → KILL-Q16 在演练后 MITIGATED | B 不接受 → 重开 D-012 原生灾难止损为保险（报告 Won't，需先记录重开条件变更决策，且 7/18 币不可下单的问题要先解） | B4 设计 |

**操作者裁定（2026-09-06）**：Q1 = **B**（没有远端介质）；Q2 = **A**（抬 ceiling 并写理由）；Q3 = **A**（接受残余风险）。后果：

- B4 按 O-X1 降级：**DL-X2 取消**；「循环活但下不了单」由 DL-L2（熔断 → 告警 → exit 0）+ DL-L3（去重 + 第二通道）覆盖，「主机死 / 网络分区」无自动动作，**KILL-Q16 记 ACCEPTED（残余，操作者具名接受）**，报告 §4.2 第三问的答案是：告警 ≤ 12 个周期（熔断上限）内到达，平仓由操作者手工执行。B4 只剩 DL-X1，前提 A-P2；若 A-P2 的探测在 B1 合并前完成，DL-X1 并入 B1，**两次重启合为一次**。
- D-P5 生效：B1 抬 live/cli ceiling，理由随提交。
- D-P4 的残余风险由操作者 ACCEPTED，写入报告附录 B 由执行 B1 时一并补记。

---

## 9. Final Decision 与 Quality Score

**Final Decision（本方案）：GO（受控执行）。** B0–B2 可直接开工（本地、可逆、无外部动作，每批一个 worktree）；B3 随 B2；B4 **Weak GO**，前提 Q1/Q3/A-P2；B5 的 DL-D2 **Need Evidence**（三核查）。两次实盘重启与任何 ledger 写入是执行阶段的操作者动作。**本方案的产出到此为止，不执行。**

Quality Score（1–5）：问题真实性 5 · 证据充分度 5（全部 E1 复验）· 根因清晰度 4 · 战略一致性 3（alpha 占比）· 相对价值与经济 4 · 方案可行性 4 · 范围收敛度 4 · 执行可交付性 4（测试矩阵已写，B4 待介质）· 上线可验证性 4 · 对抗生存 4 = **41/50**（映射 GO，与硬门禁一致：未关闭 P0 = 0）。

### Checkpoint

| 项 | 值 |
| --- | --- |
| 项目 / 等级 / Interaction | StarQuant 剩余问题执行方案 / L / Yellow |
| 当前 Phase | 8–10 COMPLETE（本文件）；Phase 1–7 继承报告；**执行中：B0 ✔ B1 ✔ B2 ✔ B3 ✔ B4 ✔（DL-X2 由 Q1=B 取消），重启 #1 ✔（2026-09-07 01:16 本地）；剩 B5** |
| 已完成结论 | D-P1..D-P7；G7 由报告的 PARTIAL 补为 PASS（测试矩阵在 §6.2） |
| 待决 | ~~Q1、Q2、Q3~~ 已答（B / A / A）；~~A-P2~~ 已探（`liquidationPrice` 0 = 不可达，14/14 多头为 0、4/4 空头非 0）；~~A-P4~~ 已测（DL-L4 窗口 71.8 s）；**B2 合并 main 待操作者**；**DL-X1 余下四件待裁（见下）** |
| 开放 Kill | KILL-P2（P1）已由 Q2 裁定（抬 ceiling 并写理由，随 B1 提交）；报告层 KILL-Q4/Q5/Q6/Q7/Q8/Q9/Q11/Q16 状态不变，各自绑定到本文件的 DL |
| 证据缺口 | 远端介质（Q1=B，DL-X2 取消）；demo `forceOrders`（未探，DL-X1 余项）；实盘真实成交成本（P20 阳性候选的 ×2 压力靠它才从假设变测量） |
| **P21 裁决** | **REJECT**，只卡 `oos_mdd_worsening`：整本书 OOS Sharpe 1.77 → 2.01（+0.2366）、OOS 回撤 −23.7% → −28.7%（+4.98pp，阈值 1pp，超标 5 倍）。其余五项全过，含 `fold_win_rate` 0.80 与 static 上 +0.27。候选留在册子外。`n_trials` 575 = ledger 514 + 申报 60 + 网格 1，**算出来的，不是抄的** |
| **DL-D2 摄入 ✔（研究侧，2026-09-07）** | 按证据定的顺序：先 `starquant_data/metrics.py` 的对齐契约（一个规范戳 `open_time`；`create_time` 不许活着离开解析器；**一根 bar 能读哪些桶由桶的「收」决定**，没有桶收在 bar 之前时给 NaN 不给最近值）。补测了「哪个戳是哪个」：六分钟内两次读 REST，三个重叠桶逐字节相同 → **REST 是已完成的桶、戳是收**，无半成品桶隐患。再是 `MetricsStore` + 可续传、带 checksum 的下载器（端到端实测 BTCUSDT 一天 288 行、1.0 秒），`starquant data metrics` CLI。**吞吐实验**：0.69 s/符号-日 → 20 币×1 年 1.4 h、45 币×完整 5.6 年 **17.7 h**，**远在「> 3 天就缩到 45 币」的门槛内，缩不需要**。**门**：`metrics_refusal` 让声明 `needs_metrics` 的策略在实盘源覆盖足够 bar 前拒绝启动——否则摄入本身就是 KILL-027 最纯粹的形态。~~**未做且明写**：5 分钟 REST 快照流~~ → **已做（同日 `e825c1d`，重启 #4 上线）**，但**不是**当初设想的形态：常驻 5 分钟守护进程被否掉了。需要的粒度属于**桶**（5m）而不属于**轮询**——REST 窗口 30 天深，每小时一轮就能无遗漏取回过去一小时全部 12 个桶；而在 bar 收盘轮询还多做一件守护进程做不到的事：它记录的正是循环做决策时**已收盘**的那批桶，也正是 `align_to_bars` 会选中的那批。守护进程换来的是同样数据的超集，记录在没有任何决策发生的时刻，代价是第二个进程、第二种失败模式、第二样要重启的东西 |
| **B5 入口证据** | **DL-D1 入口条件不成立**：B2 阳性，且候选不依赖退市数据——冻结 bar 上的净收益 −0.08%，「持有穿过」的诚实代价 −0.021 Sharpe（1.7301 → 1.7094）。pit 成员期只有 0.70% 的 bar 冻结（全 panel 6.92%），集中在 FTT 83% / ALPACA 91%。**DL-D2 三项核查全部可核**（归档 T+1 约 06:45–07:00 UTC；REST 时延约 2 分钟；同桶数值一致但**时间戳差整整一个 5m 桶**，−5min 偏移下 166/166 精确、其余偏移 0/165）——停止条件不触发，但对齐规则必须写成带测试的契约：写错它不报错，只让每份 metrics 证据带 5 分钟前视 |
| **验收清扫（§6.4）** | 13 条逐条跑过：**✔ 9**（R1/R3/R4/L1/L4/L6/A1/K1K2/X1）、**未跑 1**（AC-L2 需注入 12 次连续失败）、**不可跑 1**（AC-L5 需手工下非 `bd-` 单，未获授权）、**阻塞 1**（AC-L3）、N/A 1（X2）。跑的过程中撞出两个缺陷并已修：**L1-07 从未修好**（急停开关按 cwd 解析，从 worktree 挂等于没挂；已改为按账户寻址，engage 写两个、release 清两个、守卫读并集）；**AC-L4 只做了一半**（两个数落进 `cycles.jsonl`，日报从来没读；已补 Restart cost 一节） |
| **AC-L3 ✔（实跑，2026-09-07）** | 操作者裁定只做飞书一条通道。这条裁定把 `send()` 的返回值从 RISK-P1 的一半变成全部，于是查了——**实测：这条通道从配置那天起就是哑的**。旧的扁平 `{"text":...}` 得到 HTTP **200** + `{"code":19002,"msg":"params error, msg_type need"}`；连无效 token 也回 200。旧判定 `status_code<300` 之下 payload 写错是成功、token 写错也是成功，于是熔断会拿到 `True`、exit 0、launchd 不拉起——**书停了、仓位在场、没人被告知**（KILL-P1/RISK-P1 的原型，一直是活的）。同一个 bug 有两份拷贝，第二份在 `run_check.sh` 的 `notify()`，而那才是「循环死了」时唯一的通知路径（`curl -f` 在 200 下成功，连它自己的失败提示都不打）。三处已修（`payload_for` / `accepted` / `starquant live alert-test`），`run_check.sh` 改为复用同一份实现。**验收实跑**：`alert-test --repeat 10` → 1 送达 / 9 去重 / exit 0。人类确认点带证据补上 |
| **AC-L2 / AC-L5 ✔（实跑，2026-09-07）** | 操作者分别授权后补完。**AC-L2**：熔断的计数器真的数到 12、CLI 退出码 0、**成功一次清零**（第三条不在方案原文里，而一个只会往上数的熔断迟早会无理由触发）。**AC-L5**：09:59:35Z 手工挂 `manual-acl5-…` 非 `bd-` 限价单，10:00:03Z 重启（落在窗口内，未漏再平衡）——单子**挺过重启**，日志 `open orders this loop did not place are left alone`，随后撤净。过滤本来就对；「告诉操作者」那一半是这次补的。**顺带**：共享去重文件从 `(none)` 变成 `{"foreign-orders": …}`，而它只在**送达**时才记——这是这套系统上线以来第一条因真实事件触发并真的到达操作者的告警 |
| **DL 表逐条核对（2026-09-07）** | 19 条 DL + 4 条 A-P 假设逐条对着代码读，**三处对不上，均已补**：**DL-L3 的「`run_check.sh` 同源去重」**（B1 的去重是进程内的，而 KILL-R7 那 36 条重复恰恰来自每小时新起进程的检查任务——去重瞄准的方向正好避开了产生该发现的场景；现有一份共用去重状态文件）；**DL-L5 最后一句「`foreign_positions` 非空 → 告警而非静默」**（只 log 不告警）；**A-P3 从未验证**，而 DL-L2 整个压在它上面——用带对照的一次性 LaunchAgent 实验：`exit 0` 55 秒内跑 **1** 次、`exit 3` 跑 **6** 次，同机同配置只差退出码，**机制成立**。其余 16 条 DL 与 A-P1/P2/P4 全部对得上 |
| **B3 实际交付** | ✔ DL-K1（签名 +4 字段、旧行不折叠、 ledger 地址固定并锚定 checkout、`backtest`/`overlay` 开始计费）、DL-K2（mine 每轮把保留候选记进同一本 ledger，`--prior-trials` 不再手抄）、DL-K3（预登记顺序检查，带 C-P6 边界）。**代价明写**：N 从此涨得更快，下次 tsmom 复验更接近 WEAK_PASS（RISK-P4 预登记过）。历史 146 行未动 |
| **DL-X1 实际交付** | ✔ **已补齐（2026-09-07）**。B1 只交付了算法（三个函数 + 单测），生产代码里**零调用点**。本次补上四个调用点：引擎每周期落盘 `min_liq_distance`（含 foreign 持仓）、`startup()` 里紧挨 hedge-mode 的保证金模式拒绝、`force_orders()`、`attribution.py` 的 `INSURANCE_CLEAR` 桶；另加 M-Q06 的告警。接线过程发现三件算法测不出来的事：`marginType` 是小写 `cross`（`== "CROSSED"` 会一个都不匹配）、「没有波动率估计」曾被算成「没有可达强平价」（新增 `unmeasurable` 桶）、positionRisk 回 736 行而universe 只有 18（拒绝须按可交易符号收窄）。构造 digest 未变（`0dcd044d0158`），**重启 #2 不会清零 M-010 窗口** |
| P20 / DL-A1 裁决 | **阳性**（预登记预期为阴性）。`cs_rank(ret(336)/semi(ret(1),168))` OOS 1.7862 vs 门槛 1.6453 @ N=575，`p_family` 0.0135，VERDICT PASS。五个新族里三个干净阴性。**建议记阳性、不晋级**：成本 ×2 时跌到 1.011（tsmom 1.682）。详见 `docs/RESEARCH_LOG.md` 2026-09-06 P20 裁决节 |
| 下一动作 | (a) ~~重启 #2~~ ✔ 已执行（2026-09-07 12:00 本地 = **04:00Z**，PID 90505）：`min_liq_distance` 已落盘（4 可测 / 14 不可达 / 0 无估计），构造 digest 未变，落在窗口内未漏再平衡，旧进程 SIGTERM 优雅停机；(b) ~~P20 阳性候选跑 `research book`~~ 已跑，P21 裁决 REJECT（回撤，见 RESEARCH_LOG）；(c) ~~B5 入口证据~~ 已量：DL-D1 不开工（入口不成立）、DL-D2 三核查通过；真要做 DL-Q6 时第一步改为「先写 metrics 对齐契约与测试」，不是吞吐实验；(d) ~~快照流上线~~ ✔ **重启 #4**（2026-09-07 **12:00Z**，PID 19006；kickstart 排在 12:00:03Z、旧进程 SIGTERM 12:00:05Z、新进程起 12:00:08Z、本周期落盘 12:00:39Z——整个重启走完 8 秒，71.8 s 窗口未漏再平衡；构造 digest `0dcd044d0158` 未变 → M-010 窗口未清零）：`metrics_snapshot` 每周期 18 符号 × 12 桶落盘，`live_coverage_bars` 从 1 起算、门要求 720，即任何声明 `needs_metrics` 的策略要等约 30 天才够启动条件——**这道门今天是活的，不是摆设** |
| **明写的两件缓办**（非遗漏，各有理由） | (1) **`metrics_parity` 接进日报**：函数与测试都在，接线是一行，但快照现在只有 12 个桶、尚未跨过一个归档日，此刻接上日报只会报 `rate: None`，而没人分得清那是「还没开始」还是「坏了」——**等它跑够一天再接**。(2) **D-018 的回撤条款是否改为同波动率比较**：被它收掉的回撤里约一半只是「总书更大」而非「更差」，这是真发现，但**要按它自身的道理裁定、且只适用于此后的候选**；它救不了 P20 那个候选（同波动率下仍 +1.87pp 超标），拿改后的规则重测是一次**新试验**，照付 ledger |
