# 方案 v2.1 vs 代码：逐模块对账（2026-09-09）

方法：五个只读子代理各领一节（§2+§4 / §9+§10 / §5+§11+§12+§13 / §6 / §3+§8+§16+§19+§21），全部要求
「不信方案自己打的 ✔，每条给 `file:line`」。载荷最重的结论我逐条自核过一遍，下面标了「已自核」。
全量测试在改动前后各跑一次，改前 1,330 项绿 / 92.8 s。

---

## 0. 一句话

**方案说的都写了；写了的有相当一部分没接到能跑的东西上。** 今天找到的不是新缺陷种类，是同一种
缺陷的**上一层**：以前是「阈值没人读」，现在是「读它的那个模块没人调」。最重的一条已修。

---

## 1. 最重的一条：晋级路径不问任何治理规则（已修）

`starquant governance apply` 在写 `config/alpha_registry.yaml` 之前只问两件事：自治开关在不在、启动闸
认不认。启动闸是 `registry_evidence_problems`，**逐条目**校验证据指针、sha256 与产出构造。

逐条目的检查看不见**和、计数、日历、历史**——而 R3、R4、R5、R7、K-EX14 正好就是这四样。

于是 §3 给 `queued → probe` 列的全部前置条件，在唯一能改 registry 的那条路上一句都没被问过：

| §3 的前置 | 谁在 `apply` 里问它 |
| --- | --- |
| 批次窗口 | 无 |
| R3 probe 并发 ≤2 / 总分数 ≤1/3 | 无 |
| R4 每窗口 ≤1 次 | 无 |
| R5 未冻结 | 无 |
| R7 终身 ≤3 次 | 无 |
| 队首 | 无 |
| Canary 健康检查过 | 无 |
| K-EX14 M-010 满 30 天 | 无 |

`governance status` 打印的 `probes 1/2  fraction 0.333/0.333` 是 `click.echo` 读一个**手写的 JSON**。
`lifecycle.apply()` 与 `state.write()` 至今**零生产调用者**——`governance_state.json` 从来没有被任何
生产路径写过（`git log` 只有一次人手提交）。

这条直接落在 §0 对 AR-18 的裁定上：操作者裁定单次晋级不设人类确认点，理由是
「补偿控制是 R6 事务回滚 + Canary + R3 预算 + P&L stop」。**四条里 Canary 与 R3 没有执行体。**

### 已做的修复

- 新增 `starquant_governance/admission.py`：两层闸。
  - **registry 层**——probe 位数与预算份额，只读**提议的字节**，不看状态。因为 `state.load` 把缺失
    的状态文件读成**空 book**，而空 book 是 headroom 不是安全（那个 docstring 自己记着 09-09 的实测：无状态
    文件时第二本 1/3 的 probe 在 flow 之上被放行，2/3 对 1/3 的上限）。
  - **lifecycle 层**——对每个**暴露增加**的策略跑 `evaluate(..., PROMOTE, ...)`。只减仓的改动永不被拦，
    因为 §3 的快通道（stop、 family gate）必须不等窗口。
- `governance plan` / `governance apply` 都过这道闸；`apply` 不过就拒绝写。
- 算不出来的事实一律 False 并说出**缺哪个事实**，不是缺哪条规则。
- 新增 `starquant governance canary`：让 `canary.evaluate()` 第一次有生产调用者。
- `governance apply --actor`：`promote.py` 原先把 `actor` 硬编码默认成 `"machine"`，而它自己的
  docstring 写着「一份分不清机器写与人写的日志不是机器做过的证据」。**AC-L5 的判据此前不可证伪。**

实测（对今天的真 registry 提一份把 `flow_short.fraction` 改成 0.9 的候选）：

```
admission: REFUSED (promoting: flow)
  clean_days: 5.002   construction 0dcd044d0158 unbroken since 2026-09-04T15:02:41Z
  canary: L4: no shadow record; run deploy/run_shadow.sh first
  window: window 0, 0/1 used
  sleeve_share: 0.9
  REFUSED R3: sleeve budget share 0.9000 exceeds 0.3333 (flow=0.9000)
  REFUSED flow: §3: promote is not a legal event in probe
```

新测试 11 条，做过反向控制：把 R3 那两行检查摘掉，前三条立刻红。

**未修**：`lifecycle.apply` / `state.write` 仍无生产调用者——闸能**拒绝**，但一次成功的晋级仍不会
被记进状态。这是 Phase 4b 的前置，见 §9。

---

## 2. 模块级不可达（新的通用护栏）

从 `starquant` 的五个 CLI 入口做 import 闭包，改动前有 **1,846 行生产代码任何命令都到不了**：

| 模块 | 行 | 性质 |
| --- | ---: | --- |
| `starquant_governance/scheduler.py` | 115 | DL-G8 的全部，无命令无 plist |
| `starquant_governance/canary.py` | 110 | DL-G5 的判定半边（**已接**） |
| `starquant_governance/budget.py` | 112 | R1，只被 scheduler 引，随之不可达 |
| `starquant_data/onchain.py` | 606 | #31 有契约有验证，无 ingest 命令 |
| `starquant_data/index_price.py` | 307 | #29 同形 |
| `starquant_data/liquidations` + `_archive` | 596 | #19 判定不可用，与裁定一致 |

新增 `tests/architecture/test_every_module_is_reachable_from_an_entry_point.py`：每个生产模块必须能
从 CLI 入口经 import 到达，例外**按名字列、每条写清在等什么**。

### 为什么已有的两道护栏没抓到

`test_every_threshold_has_a_consumer.py` 判的是**子串出现**：字段名只要在七个生产包的任意 `.py`
文本里出现过就算「有读者」，而 `starquant_governance` 自己在 PACKAGES 里。于是
`max_ledger_rows_per_window` 因为在 `budget.py` 出现一次就过关——尽管 `budget → scheduler → 无人`。
R3/R4/R5/R7/K-EX14 的九个字段同理，唯一读者是 `lifecycle.evaluate`，而 evaluate 只被只读回放调用。

**Checkpoint 把这道护栏称作「本轮最值钱的产出」。它看的是名字有没有被提到，不是调用链末端有没有
人真的调——所以它不只是没抓到这一类，它是这一类能活下来的原因之一。** 新护栏改成可达性判定。

---

## 3. §9 DL 表逐行

方案说 15 行，**实际 14 行**（无独立 DL-G6，只有 DL-G6′）。

| DL | 实况 | 判 |
| --- | --- | --- |
| G0 回放 | 实现+CLI 齐；`governance replay --since 2026-09-03` 实跑 **13 复现 / 29 差异 / 0 未归因** | ✔ |
| G1 报告口径 | 两个口径都进报告；`verdict.decide` 只读桶口径 | ✔ |
| G2 同空间不重跑 | 打分前拒绝、`--reauthorize` 进报告 | ✔ |
| G3 状态机+预算 | 判定齐、属性测试齐，**写侧全断**（`apply`/`write`/`window_spend` 无生产调用者） | **半条** |
| G4 事务+回滚 | 实现+CLI 齐 | ✔ |
| G5 Canary | 判定函数今天才接上；**「过就 promote、不过回队列 + R5 计数」仍不存在** | **半条** |
| G6′ 时间规则 | 读侧齐；下游（把 tenure 事件折进状态机）不存在 | **半条** |
| G7 digest+快通道 | **唯一真正每周期跑在循环里的一条** | ✔ |
| G8 调度器 | **不可达**。方案写「研究机 plist 未做」，实际连命令都没有，AC-G8 无从跑 | **未接** |
| C1 冲击模型 | 模型、`capital=0` 退化、报告块齐；容量曲线只有 scratchpad 脚本 | ✔（曲线非产品代码） |
| G9 判据可读性 | 交付了，字段名是 `evidence_construction`，方案写的 `construction_digest` 无此物 | ✔ |
| S51 缠论 | REFUTED，corr 0.6426 有产物 | ✔ |
| D4 metrics→Panel | 已做且可达（经 `run_check.sh` 的 `report daily`） | ✔ |
| D5 现货 ingest | **§9 不打 ✔ 是对的，Checkpoint 打 ✔ 是错的** | **未通** |

**DL-D5 的四条证据**：`_load` 不建现货 store（所以 mine 枚举 0 个 basis）；无现货 `Verification`
对象（`engine.py` 自陈「gate below is shut」）；`.starquant/data/` 下无 `spot_klines/`、无 `spot_map.json`
——**一根现货 bar 都没摄入**；「362/528 有现货腿」是一次手跑的映射计数，不是落盘数据。

**方案自身的错**：DL-G2 / D4 / D5 的验收列指向 **AC-G2 / AC-D4 / AC-D5，§10 里没有这三行**。
方案点名的 T-xxx 测试 ID 多数在 `tests/` 里不存在（等价测试在，名字不同）。

---

## 4. §10 AC 表：四条没打 ✔ 的

方案说 14 行，**实际 12 行**。

| AC | 缺什么 |
| --- | --- |
| **AC-G4** | DRILL-G1 今天是单元测试（用真闸+实盘 registry 副本），`transactions.jsonl` **4 行全 APPLY、零 ROLLBACK**。要跑：造一份 sha256 改坏一位的候选 → `plan` → `apply` → 期望多一行 ROLLBACK。会往共享事务日志追加。 |
| **AC-G5** | 三样都缺：`config/alpha_registry.candidate.yaml` 不存在、`.starquant/live-shadow` 不存在、判定链此前不存在（今天补了 `governance canary`）。浸泡本身要 168 小时且**需要交易凭据**（`--dry-run` 也走 `build_venue`）。失败分支的「回队列 + R5 计数」仍无 writer。 |
| **AC-G8** | 缺的是**命令**，不是 plist。要先写一个从 ledger+shortlist 报告拼 `scheduler.Context` 的入口。 |
| **AC-L5** | 依赖 4a→4b，且链上还有四处断口（见 §9）。判据里的 `actor = machine` 今天已可证伪（加了 `--actor`）。 |

另：**AC-G1 引的「146 / 677」这一对数字磁盘上不存在**。tsmom 的真实双口径是 148/683 与 183/681；
`146` 只在一份**没有 whole_library 块**的旧报告里。

---

## 5. §3 状态机：三条判据代码里根本没有

| 转移 | 条件 | 实况 |
| --- | --- | --- |
| c→v | 预登记 < 报告 | 已可判，但**缺失时 fail-open**（`replay.py` 缺字段判 True），与 `lifecycle.py` 自己写的「Absent knowledge is False」相反 |
| c→v | 证据构造 ≡ 实盘构造 | 已可判；报告侧 6/112 份有字段，循环侧 09-08T20:00Z 起才有 |
| v→b | `slippage_stress` 5.5 档 | **0/6 份 book 报告有这个字段**，回放里硬编码 True |
| v→b | corr < 0.5 | **0/6**，硬编码 0.0 |
| v→b | 换手 ≤ 3× | **0/6**，硬编码 0.0 |
| b→q | M-011 平价 | 判据函数在，**无生产调用者** |
| q→p | Canary / M-010 30 天 / 窗口 / 队首 | 今天接上前三个；**队列这个数据结构不存在** |
| **p→m** | **family gate 重算仍过** | **代码里没有这个条件分支。** `Event.FAMILY_GATE_FAILED` 有定义有处理，**零生产者**——没有任何东西会重算 family gate |
| main→probe | — | 那条「不可达的边」**确已修**：main 声明 stop 后进 `probes_from_registry`，实盘记录里可见 |

`probe → main` 的三个条件里，「连续 9 窗口」与「从未 stop」有实现，**「family gate 重算」完全没有**。
这条要么实现，要么按选项 b 的诚实标注从 §3 删掉——不能像现在这样文档有、代码没有。

---

## 6. §6 51 条：真正没开始的只有两条

- **#39 期现（cash-and-carry）**——全仓零代码、RESEARCH_LOG **零裁定**。32 条里唯一既无实现也无
  任何裁定的一条。
- **#14 资金费套利**——只有 basis 这「第一条腿」，无套利信号、无节点、无裁定。

其余「文件不存在」的都是**已处置**，不是待办。

### Checkpoint 与实况不符的八处

1. **#32 宏观「挂起」已过期两层**：挂起今天已解除，且另一个 agent 正在写 `starquant_data/macro.py`（进行中）。
2. **「现货 ingest ✔」**——代码 ✔，数据零摄入（见 §3 的 DL-D5）。
3. **「`vol_target` 重推仍未做」是错的**——P26 于 2026-09-08 跑完（`scratchpad/p26_vol_target_under_impact.py`），
   RESEARCH_LOG 两处状态表都写「已跑（未采纳）」。真实状态是**已跑、未采纳**。
4. **「OI/LS 叶 ✔」缺一半**——90 个候选（54 OI + 36 LSR）在今天两轮 mine 里**一次都没被打过分**
   （两份 shortlist 均 `errored=90`）。这正是 `metrics=True` 那个修复要解的，**还欠一次运行**。
5. **「xsmom 重测完毕 FAIL」措辞不准**——它是被零 ledger 前置闸拦下的，`validate` 从未跑。
6. **#17 多空比「✔」缺实盘闸这一句**——四列在实盘 snapshot 全 NaN，按列被拒。研究可用、实盘不可用。
7. **#29 指数「✔」缺一半**——有契约有验证，无 store、无 sync、无 CLI。
8. **预算格已过时**——实测本窗口 **181/1700 行、mine 3/4 轮**，全库 unique **2011**（Checkpoint 写 169 / 1,999）。

另：§1 的 `51 = 32 + 7 + 12` 把 regime(#47) 与节流(#20) 各数了两遍，**不重复的候选是 49 条**。

---

## 7. §19 五道门：实测

| 门 | 方案写 | 今天实测 |
| --- | --- | --- |
| ① 四层书 OOS 出自哪份 artefact | 已关 | 已关。**但方案引的指针已过期**（现为 `tsmom-validation-20260908T182204Z`，sha `da400f4d…`） |
| ② M-Q08 ≥30 笔 | 6/30 | **7/30**。按 3.4 笔/天约还需 7 天（比方案说的 2–4 周乐观） |
| ③ 回测权益 ≠ 实盘权益 | 已关 | 已关，代码侧一致 |
| ④ 冲击成本模型 | 已关 | 已关。`vol_target` 重推**已跑未采纳**（不是「未做」） |
| ⑤ M-010 干净窗口 | 4.66/30 | **5.00/30**，canonical `0dcd044d0158` 自 2026-09-04T15:02:41Z 未断，最早 2026-10-04T15:02Z |

---

## 8. 度量层：算了没人读

| 指标 | 有计算 | 有读者/动作 |
| --- | --- | --- |
| M-015 风险压缩 | ✔ | ✔ **全表唯一完整闭环**（实测 0.2678 / 0.76） |
| M-Q08 / M-Q09 / M-Q10 | ✔ | ✔ 经 `run_check.sh` |
| M-010 q10 判据 | ✔ | **无动作读者**——只进周报，而周报无 `--check`、无定时任务 |
| M-Q03 迟到成交 | ✔ | 无 |
| M-G01 probe 被 stop 比例 | 分子接线，**比例无代码** | 无 |
| M-G02 未归因差异 | ✔ | 退出码有，「版本不发布」无绑定（CI 不跑 replay，policy 已升版三次） |
| M-G03 Canary 通过率 | ✔ | 0 次浸泡，无定义 |
| M-G04 预算使用率 | ✔ | **无读者**。`research mine` / `validate` 从不查预算 |
| **M-G05 机器 vs 人工分歧率** | **零代码** | **零** |
| **M-G06 18 个月归因 Sharpe** | **零代码** | **零** |

**M-G05 是 Pre-A′ 的唯一 falsifier**（「写死的规则能替代人在运行时的决策」）。方案自认的头号风险，
今天没有任何可被触发的仪器。

### RISK-G11：方案引的 73% 是测试 fixture 里的历史值

`collateral_drift` 今天实测：

```
cycles 47   equity_change +36.41   attributed_pnl −2.48
collateral_repricing +38.89   repricing_share 1.0682   collateral_share 0.5179
```

**repricing_share 106.8%，不是 73%。** 权益涨的部分**多于全部**是抵押品重估——账户看起来在赚钱，
书在亏钱。73% 那个数钉在 `risk_budget.py` 的 docstring 与一条 `assert 0.72 < share < 0.74` 里。
而这个量算出来只进 `reports/daily/*.json`，**日报 markdown 里不渲染、不告警、无消费者**。

---

## 9. 剩下的事，按性质分三类

### A. 能靠干活关掉的

1. **让一次成功晋级被记下来**：`lifecycle.apply` + `state.write` 的生产调用者。今天闸能拒绝，不能记录。
2. **`governance next`**：给 `scheduler` 一个装配器，AC-G8 才有可能跑。顺带让 R1 第一次有人问。
3. **book 报告补三个字段**（`slippage_stress` / corr / 换手），否则 `validated→booked` 四条里三条永远是硬编码 True。
4. **family gate 重算**：实现，或从 §3 删掉。
5. **现货 store 接进 `_load` + 一次现货 `Verification`**：DL-D5 与 basis 叶两端都靠它。
6. **`starquant data onchain` / `starquant data index`**：#31 与 #29 的 ingest 命令。
7. **`collateral_drift` 进日报渲染**，并把那条 `assert 0.72 < share < 0.74` 从钉死历史值改成钉方向。
8. **M-G05 / M-G06 的落盘格式**：不做就把 Pre-A′ 的 falsifier 从 §13 划掉，两者择一。
9. **那一轮 mine**：OI/LS 两族 90 个候选**从未被打过分**，窗口 10-03 关，还剩 1 轮。

### B. 只能等的

- M-Q08 **7/30 笔**，约 7 天
- M-010 **5.00/30 天**，最早 2026-10-04
- probe→main **0/9 窗口**，首窗 10-03
- L3 软泡 **0.44/7 天**
- M-G06 构造不变 18 个月，若不再改构造 2028-03-05

### C. 要操作者裁定的

1. **L3 的 ERROR 口径**。§5 L3 写「7 天无 ERROR 相」，同节 Testnet 事项写「ERROR 相不产生任何治理
   决定」。armed 循环 6.25 天里 2 个 ERROR，**最长无 ERROR 段 4.92 天，从未到 7**；按 0.32/天的率，
   连续 7 天干净约 11% 的机会。**环境保证会出 ERROR，判据要求一个都没有——两句互斥。**
2. **上一轮浪费掉的 658 行怎么记**（KILL-Q5 严格折叠 vs K-EX07 先例）。两条路都写出来了，没替你选。
3. **§3「family gate 重算」是实现还是删除。**
4. 一批文档更正（命令名 `live verify` → `live status --check`；§4 R1 与 §11 M-G04 的数值已被
   policy 0.3.0 放开；§13 C-G2′ 的 OPEN 与 §10/§16 的 ✔ 矛盾；§16 AR-15 已可改 CLOSED；
   六项 vs 七项；「R0–R10 零违反」实为六条）。

---

## 附：本次改动

| 文件 | 变更 |
| --- | --- |
| `starquant_governance/admission.py` | 新增，准入闸两层 |
| `starquant_cli/governance_cmd.py` | `plan`/`apply` 过闸；新增 `governance canary`；`apply --actor` |
| `tests/governance/test_the_registry_write_asks_the_rules_first.py` | 新增 11 条，含反向控制 |
| `tests/architecture/test_every_module_is_reachable_from_an_entry_point.py` | 新增第三道通用护栏 |
| `tests/alpha/test_signal_suite.py` | 因果/warmup/有界三测**加跑 registry 实参** |
| `tests/architecture/test_source_budget.py` | ratchet cli 4,492→4,588、governance 2,092→2,373，附理由 |

**`test_signal_suite.py` 那一条单独说**：KILL-AR-15 的修复把合成面板改成随 warmup 伸缩，是对的，
但它读的是 `spec.default_params` 的 warmup。实测 tsmom 默认 warmup **101**、registry 实参 **721**；
flow 是 **49** 对 **721**。**因果性、有界性、非空转三条检查一直在检验一个这个系统在第 6 轮就否掉的
配置，而实际在交易的那组从未被检验过。** 现在两组都跑，实参那组通过。

---

## 10. 收口（2026-09-10）

操作者要求「将方案审查文档里出现的问题全部处理」。逐条对回 §9。

### A. 能靠干活关掉的 —— 9/9 关闭

| # | 事项 | 关闭方式 | 现在能验的东西 |
| --- | --- | --- | --- |
| 1 | `lifecycle.apply` + `state.write` 的生产调用者 | `governance advance`：从 `cycles.jsonl` 派生事件、过 `lifecycle.apply`、落 `governance_state.json`，带水位线幂等 | `governance advance --dry-run` |
| 2 | `governance next` 的装配器 | 已装 | `governance next` → `scheduler VALIDATE  8 shortlisted candidates are unvalidated` |
| 3 | book 报告补三个字段 | `slippage_stress` / `baseline_correlation` / `turnover_ratio_to_main`（门 3.0×）都进了报告 | 门一有字段就抓到了 `book-tsmom-mined_594a12f9307a15d9` 的 **4.35× 换手** |
| 4 | family gate 重算 | `starquant_governance/family_gate.py`，`Facts.family_gate_still_passes` 进状态机，`advance` 喂给它 | `governance gate` → tsmom PASS 1.8087 vs 1.5149 at N=185 |
| 5 | 现货 store 接进 `_load` + 现货 `Verification` | `_load(..., metrics=True, spot=True)`；`starquant data spot` 进 `run_data.sh` | 153 个 spot parquet；`spot_alignment.json` **PASS**（744/744，±1 小时各 0/744） |
| 6 | `data onchain` / `data index` | 连同 `data macro`、`data spot` 一起落地 | `starquant data --help` |
| 7 | `collateral_drift` 进日报 + assert 改钉方向 | 日报有 RISK-G11 段；断言钉的是 `direction`，不是那个一天内漂 0.24 的水平值 | 今日 `repricing_share 26.3% / direction same_direction` |
| 8 | M-G05 / M-G06 的落盘格式 | `starquant_governance/verdicts.py`（append-only，未复核记 `pending` 不记缺席，未到 quorum 报 `None` 不报 0%）；M-G06 进日报 | `governance divergence` → 2 待复核；M-G06 `5.71/547 天，最早可判 2028-03-04` |
| 9 | 那一轮 mine | 已跑，`errored=0`，90/90 第一次被打分 | **OI 叶 54 个形状 0 个边际为正 → REFUTED**；LS 叶 4/36 为正但全在 squash 臂、水平低于自己的门。见 RESEARCH_LOG 2026-09-10 |

### B. 只能等的 —— 按定义没动，只更新读数

| 项 | 09-09 | 09-10 |
| --- | --- | --- |
| M-Q08 滑点 | 7/30 笔 | **27/30 笔**（06:00 那次全书重建一口气加了 18 笔，见下） |
| M-010 / M-G06 构造不变 | 5.00/30 天 | **5.71/547 天**（canonical `0dcd044d0158`，未因本次重启断掉） |
| probe→main | 0/9 窗口 | 0/9 |
| L3 软泡 | 0.44/7 天 | 1.06/7 天 |
| P13 已实现波动 | — | 185/240 根 bar，仍 BLIND |

### C. 要操作者裁定的 —— 4/4 已裁（2026-09-12 更正：本节定稿时第 1 条尚未落地）

| # | 事项 | 状态 |
| --- | --- | --- |
| 2 | 那 658 行怎么记 | **已裁：留**（K-EX07 先例；理由记在 RESEARCH_LOG） |
| 3 | family gate 实现还是删 | **已裁：实现**（见 A4） |
| 4 | 一批文档更正 | **已改**，每条带「2026-09-10 更正」标注，含 AR-15 → CLOSED、C-G2′ → MITIGATED |
| 1 | **L3 的 ERROR 口径** | **已裁（同日稍晚，`6a79f2e4`）：no-decision 读法 + ERROR 连段设门，字面读法照报不作门。** 连段的门不是新挑的——`STUCK_IN_ERROR_STREAK = 3`，与 `live status --check` 同一个常量，移进 `starquant_live/health.py` 供两个读者取。理由与今天的读数见 RESEARCH_LOG「2026-09-10 · 操作者裁定四条」。<br>**2026-09-12 更正**：本行原写「仍未裁」，是本表定稿早于裁定落地的时序错位；四条裁定当天晚些时候一并交回并落成判据。 |

### 本次收口新查出的两条（不在 09-09 那份清单里）

1. **`deploy/com.starquant.paper-l3.plist` 不是合法 XML**——`--paper` 写在 XML 注释里。launchd 收，
   plistlib 拒。L3 是七天累积判据，plist 哪天不再被接受，soak 就静默停摆。已修，两侧都盖。
2. **M-Q03 把「已经再平衡过的 bar 上的重启」也算成漏掉再平衡**——于是它分不出今早那两次重启
   （一次真漏 3135 秒，一次什么也没漏）。已修，且明写不动 `late_cycle_share` 那一半的口径。

两条都是同一个形状的第 18、19 次：**看起来在管事、实际管的不是那件事。**
