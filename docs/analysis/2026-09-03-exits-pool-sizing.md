# 深度分析：止盈止损 / 活跃交易池 / 自适应下单量与杠杆（第五轮）

> 分析头部（deep-analysis V3.2）
> - Interaction Mode: **Green**。三个模块由用户明确点名；唯一的关键未知是"止盈止损对本系统是否有正贡献"，它不靠假设而靠回测证据解决。
> - S/M/L: **L**。命中：≥3 模块、触及实盘主链路（目标权重 → 再平衡 → 下单）与回测器、24h 自主决策。风险维度为中：只涉及 demo 虚拟资金，全部改动可由 git 回滚、由 registry/profile 开关关闭。
> - 当前 Gate 决策上限：**Weak GO → 受控执行**。G2 PARTIAL：三个模块的价值命题（C-008/C-011）在开工时是 UNKNOWN，本轮的交付契约就是把它们变成可证伪的证据。
> - 外部动作授权：**无新增**。改动只落在本地仓库与已在运行的 demo 账户；不碰 mainnet。
> - 独立性声明（Phase 7）：同一 Agent 执行，先冻结 §2–§6 再攻击；legacy 证据来自三份独立的代码审计（只读 tag `v2-governance-final`），不读取本轮作者解释。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **Weak GO（受控执行）**：三个模块全部实现为可开关的独立层；每一层的**启用**由回测证据决定，不由"模块存在"决定 |
| 止盈止损（DL-05） | 做成 `starquant_alpha` 里的纯函数 exit overlay（bar 收盘评估、波动率单位、冷却期），回测与实盘共用同一步函数。**交易所原生条件单明确不做**（D-012）。启用条件预先登记：在 tsmom+flow 组合上 OOS MDD 下降且 OOS Sharpe 不低于基线 −0.10；不满足则**随代码交付但默认关闭**并记录负结果 |
| 活跃交易池（DL-06） | 两件事：① 研究侧**时点（point-in-time）成员表**——用 2021 年以来全部 864 个有归档的 USDT 永续的日线成交量按月重建"当时的 top-15"，消除现有回测的幸存者偏差（D-013）；② 实盘侧**每日自动刷新**——30 日成交量 + 15/20 名滞回，被移出的币显式 reduce-only 平仓，退出侧永远遍历仓位而不是池子（D-014） |
| 自适应下单量与杠杆（DL-07） | 只保留一个风险预算（波动率目标），不再叠加乘数（D-015）。自适应的具体含义：(a) 交易所杠杆按 `max_gross / margin_cap` 与杠杆档位自动推导，让保证金占用在 gross 上限处 ≤ 40%，而不是固定 2x 在 gross 2.0 时占满 100%；(b) 下单量按可用保证金与流动性参与率自动缩放而不是被 −2019 拒单；(c) 回撤节流（等权益回撤超过阈值时线性降低 gross）——(c) 与止损一样是证据门控的 |
| 最大风险 | KILL-017：flow 的空头门是在看见失败之后才想到的（in-sample repair）；KILL-025：时点交易池可能揭示现有 tsmom/flow 证据被幸存者偏差抬高——这是本轮的**合法产出**而非事故 |
| 已交付的前置结论 | flow 负 fold 已查清并修复（§2 E-030/E-031）：OOS Sharpe 1.07 → 1.40，5 fold 全正，DSR p 0.007（分母 42 次试验） |

---

## 1. Phase 1 · Reality Check

输入类型：**方案型**（用户点名了三个模块）。剥离方案后的问题：

| 症状 | 还原出的真实问题 | Evidence |
| --- | --- | --- |
| "缺止盈止损" | 信号是周级的，仓位只在信号翻转或再平衡时变化；一笔仓位在两次信号更新之间可以承受无界的不利波动。2024-11 XRP 空头单月 −11% 权益就是实例 | E-030 |
| "缺活跃交易池" | universe 是 2026-09-03 05:50Z 一次性选出的静态快照：新上市币永远进不来，退市币（PUMPUSDT 已被标记不可交易）靠启动时剔除；研究侧用"今天的 top-15"回测 2021 年，是幸存者偏差 | E-036、E-037 |
| "缺自适应下单量/杠杆" | 交易所杠杆固定 2x，而 gross 上限 2.0 → 满仓时初始保证金 = 100% 权益，新单会被 −2019 拒绝；下单量不看可用保证金与流动性；权益回撤不影响敞口 | E-038 |

需求三问：谁承担损失 = 单一操作者（demo 信息损失 + 时间）；频率 = 每小时周期、每日刷新；现有方案能否满足 = 否（三者在此系统里都不存在；legacy 的对应物要么从未执行、要么从未验证，见 §2）。

Early Kill：无 FATAL。K6（价值 < 复杂度）对止损与回撤节流为 WARNING → 用"证据门控启用 + LOC 预算"处理。**G0 PASS**。

---

## 2. Phase 2 · Evidence Ledger

### 2.1 本轮新证据（全部 E1，可复核）

| ID | 类型 | 来源 | 摘要 |
| --- | --- | --- | --- |
| E-030 | EXPERIMENT | scratchpad `flow_fold_diag2.py`，报告布局复现（`--from 2021-06-01`，45,365 bars） | flow 的亏损 fold = **2024-10-13 → 2025-09-23**（Sharpe −0.61，−9.8%），其中 **2024-11 单月 −8.6%**；多头腿 +21.2%（Sharpe 1.10），**空头腿 −28.0%（Sharpe −1.08）**；按币：XRP 空头 −11.0%、ADA −8.9%、SUI −8.5%。该 fold 内空头信号的条件 IC 在 72/168h 前瞻为 **+0.11/+0.15 且横截面前瞻收益为正**（+0.48%/+0.76%）——被做空的币随后跑赢，方向反了；其余四 fold 空头信号的前瞻收益均为负（方向对）。市场背景：BTC +80%，2024-11 大选后现货驱动的山寨币暴涨 |
| E-031 | EXPERIMENT | scratchpad `flow_fold_diag3.py` | 假设检验（每个配置都计入 flow trials ledger）：对称"趋势冲突门"（多空都门控）在 2022 熊市 fold 上恶化（0.63→0.30、1.40→0.77）；**只门控空头**（周级动量 ≥ 0.3 时空头信号置 0）：各 fold [1.27, 1.45, 1.98, 1.54, 2.39]，OOS 1.74，MDD −26% → −12%，2024-11 由 −8.6% 变 +3.6%，与 tsmom 相关 0.14 → 0.30，等权组合 Sharpe 1.82 → 2.06。诊断对照：空头减半 0.25、只做多 0.83——说明问题不是"空头没用"而是"逆强势趋势做空没用" |
| E-031b | EXPERIMENT | `reports/research/flow-validation-20260903T0927Z.json` | 正式验证，网格 {short_gate: 0/0.3/0.5}，申报先验试验 39（28 + 本轮诊断 11）：WFO OOS **1.40**，各 fold [0.48, 1.45, 1.98, 0.76, 2.39]，5 fold 样本内选择均未选中无门对照；CPCV 1.66 / q05 1.29 / 负比例 0；DSR p **0.007**（42 试验）；成本 2× 1.58；全样本 MDD −12%。PBO 0.57 在 N=3 下仅供参考 |
| E-032 | CODE | legacy `starquant_strategy/protection/adaptive.py:166-254`、`starquant_safety/protection/engine.py:190-384`、`starquant_core/engine.py:5668-5703, 8002-8250` | legacy 的止损/止盈是**交易所原生条件单**（`STOP_MARKET`/`TAKE_PROFIT_MARKET`，reduceOnly，`workingType=CONTRACT_PRICE`）：止损 = `atr_pct × 2.0 × 波动率档位因子 × 点差因子`，夹在 [币价档位最小值, 5%]；止盈 = 风险 × RR，RR = 2.0 × 趋势因子 × RSI 因子 × 波动率因子 ∈ [1, 5]，共 9 个手调常数。**没有任何回测证明它们有正贡献**；`02-risk-baseline.md:88`（R-M03-1，P0）记录这些阈值是在错误的 RSI/ATR 数学上校准的、从未重校 |
| E-033 | CODE+DATA | legacy `engine.py:1175-1338, 12748-12770`；`observability … escalation-design.md` | 软件侧 `TrailingExit`（实为从入场价而非高水位计算，名不副实）与 `TimeExit`（48/24/12h 阈值无依据，`entry_time` 存在未持久化的 dict 里，**每次重启归零**）**从未执行**，只写日志 "execution pending M12"。原生条件单的事故统计：仓位无止损保护的时长中位 60s、p99 1,329s、**最大 5,078s**；多腿入场留下半量止损、`position_generation` 过期使止损对门禁不可见、重复 clientOrderId |
| E-034 | CODE+DATA | legacy `starquant_data/trading_pool_lifecycle.py:30-36, 207-209, 531-600`；`engine.py:13830-13880`；`07-debugging-log.md` | legacy 交易池：5 维打分（点差 0.25 / 深度 0.25 / 成交量 0.20 / 稳定性 0.15 / 容量 0.15），晋级 ≥ 0.6、连续 3 次 < 0.3 降级、24h 观察期、上限 50；**三套互不一致的实现**（引擎 50bps 点差映射 vs 库 100bps vs dev 内联）。记录在案的缺陷：成交量分恒为 0 → 上限 < 0.6 → **任何币都无法激活**；重启时恢复 ACTIVE 绕过上限；事件表永远为空 → 每次重启观察期归零；**降级 = 冻结**：被隔离的币不再收到任何入场或退出信号，仓位靠交易所条件单裸奔。`PITUniverseSnapshot/UniverseHysteresis` 从未接进回测，且 `snapshot_for_backtest` 用当前可执行标志过滤历史——恰好制造它声称要消除的偏差 |
| E-035 | CODE+DATA | legacy `starquant_strategy/risk/adaptive_sizing_engine.py:189-326`；`engine.py:573-628, 12437-12455, 12945-12952`；`domain-execution-report.md:78-88` | legacy 有两条 sizing 路径：① "canonical" 引擎 = `可用保证金/权益 × 最大杠杆` × 八个标量（波动率、容量、流动性、regime、信号置信、资金费率、清算距离、回撤、止损距离）之积——**从未验证**（回撤输入被硬编码为 0；唯一一次 soak 在第 1 个 episode 3.21s 内因 `MIN_NOTIONAL_NOT_SATISFIED` 死亡，**零成交**）；② 实际交易路径 = 1% 单笔风险 × 2% 基础比例双重叠加 → 名义恒 ≈ 10 USDT（用户当时反馈"自适应未启用"）。**交易所杠杆从未同步**：风险模型按 3x 计算，交易所停在默认 20x。无杠杆档位、无保证金类型、无 Kelly。值得保留的只有：三个名义上限取 min、min-notional 拒绝而不放大 + ROUND_DOWN、原因向量、"风险恶化时不得放大"的单调钳 |
| E-036 | CODE | `.starquant/data/universe.json`（`selected_at_ms` 2026-09-03 05:50Z）、`starquant_live/engine.py:76-84`、`config/live.demo.yaml` | 现状：universe 只在 `starquant data sync` 时选一次；实盘启动时只做"不可交易剔除"；`leverage: 2` 固定；无 exit overlay；`plan_rebalance` 不看可用保证金 |
| E-037 | OFFICIAL | `s3 data.binance.vision …/futures/um/monthly/klines/` 目录列表（2026-09-03）；`fapi/v1/exchangeInfo` | 有归档的 USDT 交易对 **864** 个；当前 exchangeInfo 里 USDT 永续 656 个（TRADING 526、SETTLING 129），另有 187 个 `TRADIFI_PERPETUAL`；210 个有归档但已不是当前永续（含 LUNA、MATIC、EOS、SRM 等）。时点重建可行：在线币用 REST 日线（2 次请求覆盖 2021 至今），退市币用月度日线归档 |
| E-038 | INFERENCE(E1 算术) | Binance USDⓈ-M 保证金规则 | 杠杆 L、gross G 时初始保证金占用 = G/L。当前 L=2、G≤2.0 → 最坏 100%；L=5 → 40%。维持保证金率在小名义档位为 0.4%–1%（BTC 0.4%），全仓模式下 5x 的清算距离对整体账户是 >80% 的权益损失，远在 −5% 日亏软停之外。即：**提高交易所杠杆不改变敞口（敞口由波动率目标与 max_gross 决定），只改变保证金效率** |
| E-039 | RESEARCH(E3) | Kaminski & Lo (2014) "When do stop-loss rules stop losses?"；本仓库 `docs/RESEARCH_LOG.md` 第 2 轮 | 止损在收益正自相关（动量）的时间尺度上增值，在均值回归尺度上毁值。本系统自己的发现：1–24h 是反转，周级是动量。推论：**小时级/日内止损几乎必然毁值**（它在反转尺度上触发）；唯一与已知结构一致的设计是以日波动率为单位、在 bar 收盘评估的宽止损。这只是先验，必须回测 |

### 2.2 Claim Register

| ID | 命题 | P | Axiom | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-008 | 波动率单位的 bar 收盘 exit overlay 能在不降低 tsmom+flow 组合 OOS Sharpe（≥ 基线 −0.10）的前提下降低 OOS MDD | P1 | A2/A6 | 全部预登记设置都不满足 → exit overlay 默认关闭 | E-039（先验）、E-032/033（legacy 无证据） | UNKNOWN → 本轮验证 |
| C-009 | 时点交易池会实质改变 tsmom/flow 的验证结果 | P1 | A2 | \|ΔOOS Sharpe\| < 0.2 且判定不变 → 幸存者偏差可忽略 | E-037 | UNKNOWN → 本轮验证 |
| C-010 | 自动推导交易所杠杆能消除保证金拒单风险且不改变敞口 | P1 | A7 | demo 上出现 −2019 拒单，或 gross/单币权重与改前不同 | E-038 | SUPPORTED（算术）→ 实盘验证 |
| C-011 | 回撤节流降低 MDD 且 Sharpe 损失 ≤ 0.10 | P2 | A2 | 回测不满足 → 默认关闭 | — | UNKNOWN → 本轮验证 |
| C-012 | flow 空头门是机制而非拟合 | P1 | A6 | 42 试验下 DSR 不过；或实盘 30 天空头腿显著差于回测 | E-030/031/031b：5 fold 全升、单参数、机制可解释、样本内选择从不选无门对照 | PARTIAL（回测 SUPPORTED，实盘待证） |
| C-013 | legacy 的三个模块没有可直接移植的**数值**，只有可移植的**纪律** | P2 | A2 | 找到任一 legacy 阈值有回测证据 | E-032–E-035 | SUPPORTED |

Assumption：A-006 demo 上 `/fapi/v1/leverageBracket` 可用（否则退化为配置上限）；A-007 退市币的归档日线足以复原其在世时的成交量排名（若归档缺月则该币在缺月视为不在池中，偏差方向为"少几个死币"，记录而不修正）。

**G2：PARTIAL**（C-008/C-009/C-011 UNKNOWN，均在本轮的交付契约里有证伪实验）。

---

## 3. Phase 3 · Problem Research

**Problem Statement**：对于在 demo 上无人值守运行周级 alpha 的单一操作者，当仓位在两次信号更新之间遭遇趋势外的剧烈不利波动、当 universe 与市场活跃度脱节、当保证金占用逼近上限时，由于系统没有 exit overlay、没有池刷新、没有保证金感知的下单量，会出现"单币单月 −11%"、"新币永远不进池 / 死币靠人工剔除"、"满仓时新单被拒"这三类损失；研究侧还会因为用今天的 universe 回测过去而高估策略。

**Causal Chain**：表层 = 三个缺失模块；直接原因 = 本系统按"最小护栏 + alpha 优先"刻意省略；深层原因 = legacy 的对应模块要么从未执行（E-033）、要么从未验证（E-032/035）、要么内部自相矛盾（E-034），所以重建时没有可信的起点；可干预杠杆 = 把三者都做成**证据门控的独立层**，让"开不开"由数据决定。

**JTBD**：当一根 1h bar 闭合时，我想要系统在 alpha 目标之外自动处理"仓位失控、池子过时、保证金不够"三件事，以便我每天只看一份报告。

**Scenarios / Edge Cases（进入 Test Contract）**：
- X-1 仓位从入场价不利移动 k×日波动率 → 下一根 bar 开盘 reduce-only 平仓，冷却 N 根 bar 内同向信号不再入场；反向信号立即允许。
- X-2 进程重启：入场价来自交易所 `positionRisk.entryPrice`（真值），高水位从状态文件恢复，恢复不到则以当前价重置（保守：只可能晚触发止盈/移动止损，不会误触发止损）。
- X-3 数据过期（护栏 STALE_MARKET_DATA）时 exit overlay 不评估。
- P-1 币被移出池：目标置 0 → 正常再平衡产生 reduce-only 平仓单；平仓前它仍在"受管集合"里（受管 = 池 ∪ 有仓位的币）。
- P-2 币进入 `SETTLING`/不可交易：交易所拒绝新开仓；退出侧仍尝试 reduce-only；连续失败进日报。
- P-3 新上市币进池但历史 < 720 bars：在池中但不可交易（沿用 `min_history_bars`）。
- P-4 排名在 15/20 边界抖动：滞回；每日刷新最多换入/换出的币数量也受滞回约束。
- S-1 可用保证金不足以下全部计划单：按比例缩小**加仓**单，reduce-only 单不缩；记录 `MARGIN_SCALED`。
- S-2 杠杆档位允许的最大杠杆低于推导值：取 min；名义超过档位上限时（demo 10k 权益不会发生）按档位降杠杆。
- S-3 单笔加仓名义 > 参与率上限（p × 近 24 根 bar 平均报价成交量）：截断，剩余留给下一 bar（自然切片）。

**G1：PASS**。

---

## 4. Phase 4 · 相对价值

| 模块 | No-Build | 20% 成本方案 | 推荐 | Won't |
| --- | --- | --- | --- | --- |
| exit overlay | 周级信号本身会翻转；2024-11 案例已被 flow 空头门覆盖 | — | bar 收盘、波动率单位、冷却期的纯函数层，回测/实盘共用；**证据门控启用** | 交易所原生条件单（E-033 的全部事故类型都来自它；demo 的日内价格路径本身是合成的，E-013） |
| 交易池 | 静态快照（现状） | 每周手动 `starquant data sync`（约 60% 价值，零代码） | 实盘每日自动刷新 + 显式平仓；研究侧时点成员表（唯一能验证"池子有没有用"的方法） | 5 维打分/观察期/隔离状态机（点差与深度在 demo 上是合成的，在 mainnet 数据管线里不存在；E-034 证明它一次都没成功激活过） |
| 自适应 sizing | 固定 2x（现状） | 把 `leverage` 改成 5（一行配置，解决 80% 的保证金问题） | 杠杆自动推导 + 保证金/流动性感知的下单量 + 证据门控的回撤节流 | 八标量乘积（E-035）、Kelly、ML sizing |

"是否有 20% 成本方案"：交易池的手动周刷新与 sizing 的"改成 5x"都能拿到大部分价值，但都不满足"24h 无人值守、少操作"这一主目标；exit overlay 没有廉价替代——它要么有证据要么不做。**G3 PASS、G4 PASS**（单人项目，经济性 N/A；Cost of Delay = 每拖一天少一天带 exit overlay/新池子的实盘归因样本）。

---

## 5. Phase 5 · System Analysis

| 层 | As-Is | To-Be |
| --- | --- | --- |
| `starquant_alpha` | signals → ensemble → portfolio → weights | 新增 `overlays/exits.py`（exit overlay，纯）、`overlays/exposure.py`（回撤节流，纯）；`model.evaluate(panel, membership=None)` 接受时点成员掩码 |
| `starquant_data` | `universe.py` 一次性选择 | 新增 `pool.py`：日线同步（REST/归档）、`point_in_time_membership()`（纯）、`refresh_live_universe()`；`universe.py` 抽出纯排名滞回函数供两侧共用 |
| `starquant_live` | engine → guards → plan → execute | engine 增加：exit overlay 步进（状态持久化到 `state.json.exits`）、日切时刷新池、受管集合 = 池 ∪ 仓位；`rebalancer` 增加保证金/参与率缩放；`leverage.py` 推导每币杠杆 |
| `starquant_exchange` | `set_leverage` | 新增 `leverage_brackets()`（可选，失败退化） |
| `starquant_cli` | — | `starquant data pool refresh|history`；`research validate/backtest --universe pit`；`research overlay`（exit overlay/节流的证据报告） |
| 配置 | — | `exits:`、`universe.refresh`、`portfolio.leverage: auto`、`margin_cap`、`max_leverage`、`max_participation`、`drawdown_throttle:` |

Impact Radius：R0 实盘每周期多一步退出评估（纯计算，< 10ms）；R1 数据多一套日线（约 900 个小 parquet）；R2 交易所多一个只读端点；R3 运营多一个每日刷新日志与日报字段；R6 非 alpha 代码预算 +≤ 800 行（exit overlay ≤ 250、池 ≤ 350、sizing ≤ 200），仍在 6k 预算内。

Engineering Pre-check：exit overlay 的 Python 逐 bar 循环（45k bars × 15 币，向量化到币维度）实测 < 2s；日线 REST 权重 656 币 × 10 = 6,560，按 5 req/s 分摊在 3,000/min 以内；归档 210 币 × 68 月 ≤ 15k 请求，6 线程约 10 分钟。**G5 PASS**。

---

## 6. Phase 6 · Solution Reasoning（Decision Log）

| ID | 决策 | 备选 | 理由 | 可逆 |
| --- | --- | --- | --- | --- |
| D-012 | exit overlay = bar 收盘评估的软件层，规则以**入场时日波动率**为单位：止损 `k_sl`、移动止损 `k_trail`（从高水位）、止盈 `k_tp`；触发后冷却 `cooldown_bars`；同一步函数 `exit_step()` 同时驱动回测循环与实盘 | 交易所条件单 | E-033 全部事故 + demo 日内路径合成 + 与 bar 驱动架构一致；代价是最多 1 根 bar 的额外暴露，在日波动率单位的宽止损下可忽略 | 高（`exits.enabled: false`） |
| D-013 | 研究侧时点成员表：每月 1 日按前 30 天报价成交量重排，`enter ≤ 15 / exit > 20`，上市 ≥ 30 天，`always_include` 只含 BTC/ETH（不把今天的偏好带回 2021） | 沿用静态 universe | 幸存者偏差是当前证据里最大的未量化项 | 高 |
| D-014 | 实盘每日刷新，同一滞回；被移出 → 目标 0 → reduce-only；受管集合 = 池 ∪ 仓位；进入 → 沿用 `min_history_bars` | legacy 的隔离/冻结 | E-034："降级 = 冻结"孤儿仓位是 legacy 最贵的教训 | 高 |
| D-015 | 一个风险预算：波动率目标 + gross/单币上限。自适应项只做**乘在最终权重上的标量**（回撤节流）或**下单量层的约束**（保证金、参与率），绝不叠加多个"比例" | 八标量乘积 | E-035：叠加乘数是"自适应不自适应"的根因 | 高 |
| D-016 | 交易所杠杆 = `min(max_leverage, bracket_max, ceil(max_gross / margin_cap))`，默认 `margin_cap 0.4 → 5x`；敞口仍由组合层决定 | 固定 2x | E-038 | 高 |
| D-017 | exit overlay 与回撤节流的启用都由**预先登记的验收标准**决定（§10 T-X06/T-S05）；不满足则随代码交付、默认关闭、写负结果 | 直接启用 | 用户原则："先经济改进、再诚实验证；不通过就报负结果" | 高 |
| D-018 | 新策略作为**独立小书**加入（各书独立波动率目标与上限，按 fraction 求和，总书套主书上限与再平衡带）的验收由预登记规则决定（`starquant research book`：ΔOOS Sharpe ≥ 0.10、OOS MDD 恶化 ≤ 1pp、≥ 3/5 fold 胜出、第二 universe ΔOOS ≥ 0、小书单独 CPCV 负比例 ≤ 10% 且成本 2× ≥ 0.5）；组合层 ACCEPT 不产生 registry 判定，信号级仍须 PASS / WEAK_PASS（KILL-015） | 按相关性 / 边际 Sharpe 直接启用 | 用户原则同 D-017；首个用例 flow 空头小书（2026-09-03 14:36Z）：组合层 ACCEPT、信号级 FAIL → 不启用 | 高 |
| D-019 | **探针书**：操作者可把组合层 ACCEPT 的 sleeve 作为有界实验上线——registry 必须写明 `book` + `probe`（接受人、日期、止损规则、复审天数），启动检查核对报告种类/对象/fraction；引擎按归因 P&L 自动停书并持久化；日报标复审 | 等实盘归因 ≥ 30 天再决定（路径 a） | 操作者 2026-09-04 明确选择路径 (b)；demo 资金、3% 平均敞口、自动止损让错误的代价有界，而样本外证据只有运行才能产生 | 高（`enabled: false` 或 `probe.stop`） |

灰度/回滚：每个层有独立开关；`--dry-run` 先看 exit overlay 的"本应平仓"记录一天；`git revert` 单 commit 可回滚。

---

## 7. Phase 7 · Adversarial Review

> 编号冲突说明（2026-09-04 审计）：本文档的 KILL-030 / KILL-031 与 `2026-09-03-alpha-module-review.md` 的同号条目是**不同命题**，两份文档在同一天由并行会话写成。本文档的两条改称 **KILL-030a / KILL-031a**，另一份的改称 **KILL-030b / KILL-031b**；正文编号保留原样以免破坏既有引用，此后一律使用带后缀的形式。KILL-030a（「独立小书只是主书的空头倾斜」，结论「不启用」）已被 D-019 的探针书取代，残余风险由 KILL-040 承接。

六角色 × 十类攻击后保留的 Kill：

| Kill | 攻击命题 | 关联 | 严重度 | 缓解/关闭条件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| KILL-016 | 止损在趋势跟随上砍掉赢家的回撤，净效果为负（Complexity Accountant / Evidence Prosecutor） | C-008、D-012 | P1 | 证据门控（D-017）；只测 8 个预登记设置；不通过则默认关闭 | MITIGATED |
| KILL-017 | flow 空头门是看见 2024-11 亏损后的样本内修补（Evidence Prosecutor） | C-012 | P1 | 单参数、机制可解释、5 fold 全升而非只修坏 fold、样本内选择从不选无门对照、42 试验 DSR p 0.007；实盘 M-008 监控空头腿 | MITIGATED（实盘裁决） |
| KILL-018 | 时点重建不完整：退市币归档缺月、状态历史未知、`TRADIFI_PERPETUAL` 等新类别 → 残余幸存者偏差（Evidence Prosecutor） | C-009、D-013 | P2 | 报告覆盖率（多少币-月有数据）；偏差方向已知（少死币 → 仍偏乐观）；写入 RESEARCH_LOG | ACCEPTED（记录） |
| KILL-019 | 每日刷新让边界币来回进出，换手吃掉 edge（Skeptical PM） | D-014 | P2 | 15/20 滞回；回测里用同一滞回按月刷新度量成员换手；日报输出成员变更 | MITIGATED |
| KILL-020 | 5x 杠杆放大清算风险（Risk Red Team） | D-016 | P2 | 敞口不变（波动率目标 + max_gross）；5x 全仓清算需 >80% 权益损失；−5% 日亏软停在其之前 | CLOSED（E-038） |
| KILL-021 | 冷却期与 `hold` 语义冲突：止损后信号仍为多，下一 bar 立刻重新入场（Delivery Saboteur） | D-012 | P2 | 冷却期内同向目标置 0；反向允许；T-X03 | MITIGATED |
| KILL-022 | 新状态（入场价、高水位、冷却、池成员）在重启后丢失或错位——legacy `TimeExit` 每次重启归零的翻版（Delivery Saboteur） | D-012/014 | P1 | 入场价以交易所为真值；高水位持久化，恢复不到则保守重置；T-X04 | MITIGATED |
| KILL-023 | 三个模块把"alpha ≥ 90%"的系统重新变成风控工程（Skeptical PM） | 全部 | P1 | LOC 预算（§5）；全部为纯函数 + 薄适配；exit overlay 与节流默认由证据决定 | MITIGATED |
| KILL-024 | 新币进池即被交易，上市首月的异常路径污染信号（Risk Red Team） | D-014 | P2 | `min_history_bars=720` 对池成员同样生效 | CLOSED |
| KILL-025 | 时点 universe 下 tsmom/flow 的证据显著下降（Evidence Prosecutor） | C-009 | P1 | 这是本轮的目的：若下降则更新 registry 证据；若某策略 FAIL 则停用 | ACCEPTED（合法产出） |
| KILL-026 | 参与率上限在 10k 权益下永不触发，是死代码（Complexity Accountant） | D-015 | P2 | 保留但用测试证明其在大权益下生效；不在实盘证据里宣称价值 | ACCEPTED |
| KILL-030 | "独立小书"只是主书的空头倾斜：flow 空头小书 91% 币-bar 与 tsmom 同向、净收益相关 0.29，静态 universe 上贡献为零（Evidence Prosecutor） | D-018 | P1 | 不启用；若重开，作为 tsmom 的修饰项预登记验证而不是第二本书 | ACCEPTED（不启用） |
| KILL-031 | 探针书的止损校准不当：字面"亏了就停"把噪声当证据（Sharpe-1 的 sleeve 首月 ~37% 误停），阈值太松则把伤害当噪声（Risk Red Team） | D-019 | P2 | 30 天 −1% 权益 ≈ −2σ；90 天强制复审；阈值与理由写进 registry 注释 | MITIGATED |

Pre-Mortem（30 天后失败的最可能原因）：① exit overlay 通过了回测门槛却在实盘频繁触发（demo 价格偏差 E-013 让"入场价"与 mainnet 收盘价不一致）→ M-005 监控触发频率与触发后 24/72h 的反事实收益；② 池刷新在某天把 5 个币换掉，换手激增 → M-006；③ 时点 universe 让 flow 失去空头对象（早年 universe 更小）→ 记录为负结果。

Inversion（怎样保证失败）：把止损做成 2% 固定百分比并在小时级触发；把池子做成 5 维打分且不做时点重建；把 sizing 做成八个乘数。以上均已反向控制。

**G6：PARTIAL**（无 OPEN P0；P1 全部 MITIGATED 且各有测试或实盘指标）。

---

## 8. Phase 8 · Scope

**Must**：exit overlay（纯 + 实盘 + 证据报告）；时点成员表 + 实盘每日刷新 + 显式平仓；杠杆推导 + 保证金/参与率缩放；回撤节流（证据门控）；tsmom/flow 在时点 universe 下重新验证；文档与日报字段。
**Should**：`research overlay` 命令输出 exit overlay/节流的对照报告；日报里的池成员变更与退出事件。
**Won't（Scope Firewall）**：交易所原生条件单；日内止损；Kelly/ML sizing；订单簿深度/点差打分；观察期/隔离状态机；mainnet。
重开条件：进入 mainnet 且信号尺度进入日内时，重评交易所原生条件单（参考 legacy `protection/engine.py` 的不变量与 "only ACK makes protection real"）。

---

## 9. Phase 9 · Delivery Contract

| DL | 内容 | 文件 | 测试 | 验收 |
| --- | --- | --- | --- | --- |
| DL-05 exit overlay | `exit_step()` 纯步函数 + `apply_exits()` 向量化回测应用 + 实盘步进与状态持久化 + 证据报告 | `starquant_alpha/overlays/exits.py`、`starquant_live/exits.py`、`starquant_live/engine.py`、`starquant_cli/research_cmd.py` | T-X01 止损/止盈/移动止损各自在合成路径上恰好触发一次且在下一 bar 执行；T-X02 冷却期内同向不入场、反向入场；T-X03 hold 语义下不重复入场；T-X04 重启后入场价来自交易所、高水位恢复；T-X05 无前视（未来行打乱不改变过去决策）；T-X06 证据报告：8 个预登记设置在 tsmom+flow 组合 WFO 上的 OOS Sharpe/MDD 对照，启用规则按 D-017 | 实盘 `cycles.jsonl` 每次退出可追溯到 (symbol, rule, entry, price, vol) |
| DL-06 交易池 | 日线同步；`point_in_time_membership()`；`refresh_live_universe()`；engine 日切刷新 + 受管集合；`--universe pit` | `starquant_data/pool.py`、`starquant_data/universe.py`、`starquant_live/engine.py`、`starquant_cli/data_cmd.py`、`research_cmd.py` | T-P01 滞回：排名 16–20 的老成员保留、21 退出、≤15 进入；T-P02 时点表因果：t 月成员只用 t 月前数据；T-P03 退出侧遍历仓位：被移出币有仓位时产生 reduce-only 单；T-P04 新币历史不足不交易；T-P05 刷新失败保留上一池；T-P06 覆盖率报告 | `universe.json` 含 `changed_at`、`entered`、`left`；`membership.parquet` 可复现 |
| DL-07 sizing | `derive_leverage()`；`scale_orders_to_margin()`；`participation_cap()`；`drawdown_scalar()` | `starquant_live/leverage.py`、`starquant_live/rebalancer.py`、`starquant_alpha/overlays/exposure.py`、`starquant_exchange/binance_usdm/venue.py` | T-S01 杠杆 = min(max, bracket, ceil(gross/cap))；T-S02 保证金不足时只缩加仓单且按比例；T-S03 参与率截断；T-S04 节流标量单调、有下限、无前视；T-S05 节流证据报告（同 T-X06 的验收规则） | demo 上 `positionRisk.leverage` 全部等于推导值；30 天内 −2019 拒单 = 0 |
| DL-08 探针书 | registry `books` / `book` / `probe`；`AlphaModel` 按书构建 + `combine_books`；`starquant_live/probe.py` 止损规则；引擎停书与持久化；日报探针段；`research book` 证据 | `starquant_alpha/registry.py`、`starquant_alpha/model.py`、`starquant_alpha/portfolio.py`、`starquant_live/probe.py`、`starquant_live/engine.py`、`starquant_live/reports.py`、`starquant_cli/research_cmd.py` | T-B01 单主书逐位不变；T-B02 两书求和后套上限与带、contributions 带 fraction；T-B03 ACCEPT 只在非主书 + probe 块放行且核对报告；T-B04 引擎按 30 天归因止损、重启仍停；T-B05 日报探针段 | `heartbeat.json.probes`、`cycles.jsonl.probes`、日报 `Probe books` |

Source Trace：DL-05 ← E-030/032/033/039, C-008, D-012/017, KILL-016/021/022 ← M-005；DL-06 ← E-034/036/037, C-009, D-013/014, KILL-018/019/024/025 ← M-006；DL-07 ← E-035/038, C-010/011, D-015/016, KILL-020/026 ← M-007。

Owner（单人项目，全部为操作者本人；Agent 只交付代码与证据）：Approval Owner 对"启用 exit overlay/节流"的最终决定拥有否决权——本轮按 D-017 的登记规则执行，并在 RESEARCH_LOG 里写明。

**G7：PASS**（本文件即四类契约的合一版本）。

---

## 10. Phase 10 · Learning Plan

| Metric | Claim | 指标 | 阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- |
| M-005 | C-008 | 退出触发次数/周；触发后 24h/72h 的反事实收益（不退出会怎样） | 反事实收益均值 > 0 且 > 成本 → exit overlay 在毁值 | 30 天 | 关闭 exit overlay |
| M-006 | C-009 | 每月成员变更数；新进入币 vs 老成员的归因 P&L | 变更 > 5 币/月或换手成本 > 毛收益 20% | 60 天 | 加大滞回或改为周刷新 |
| M-007 | C-010 | 保证金占用峰值；−2019 拒单数 | 占用 ≤ 50%；拒单 0 | 30 天 | 调整 margin_cap |
| M-008 | C-012 | flow 空头腿实盘 Sharpe vs 多头腿 | 空头腿 30 天 Sharpe < −1 | 30 天 | 复查门槛或停用 flow 空头 |
| M-009 | C-012 | flow 探针书 30 天归因净 P&L（% 权益）；90 天实盘 Sharpe vs 小书单独 OOS 1.09 | 30 天 ≤ −1% → 自动停书；90 天 Sharpe < 0 → 停用并写负结果 | 90 天（2026-12-02 复审） | 停用探针书；结果计入 flow ledger |

Post-Launch Review：M2+14 天的《策略有效性报告》增加"exit overlay/池刷新/杠杆推导"三节。

---

## 11. Final Decision

**Weak GO（受控执行）**。硬门禁复核：无 OPEN P0；P0 Claim 无 REFUTED；三个 UNKNOWN Claim 各有本轮内可完成的证伪实验。Quality Score：真实性 5、证据 4、根因 5、战略一致 4（这三个模块本身不是 alpha，但 KILL-023 有预算约束）、相对价值 4、可行性 5、范围收敛 4、可交付 4、可验证 5、对抗生存 4 = **44/50**（受 G2 PARTIAL 压至 Weak GO）。
