# StarQuant

加密永续合约量化交易系统（Binance USDⓈ-M）。研究与信号只用 mainnet 公共数据，执行在 demo
场地；系统的全部产出是一条**每根闭合 bar 重算一次的目标权重**，以及一份能自我说明的证据记录。

本文件只是词汇表。实现决策在 `docs/ARCHITECTURE.md`，运行步骤在 `docs/RUNBOOK.md`。

## Language

### 标的与交易池

**Universe**：
选币的**规则**——资格条件与带滞回的排名口径（`config/universe.yaml`）。它是一条规则，不是一份名单。
_Avoid_: 标的池、symbol list

**Pool**（交易池）：
在某个时点由 Universe 规则选出的**那份名单**。研究侧是时点成员表，实盘侧是每日刷新的当前成员。
_Avoid_: watchlist、候选集

**Member**（成员）：
当前在 Pool 里的标的。被移出 Pool 但仍有仓位的标的不是成员，但仍在受管集合里直到平掉。

**Hysteresis**（滞回）：
进出 Pool 用不同的门槛（进入 ≤15 名、离开 >20 名），使排名在边界抖动时不产生换手。

**Point-in-time membership**（时点成员表）：
只用某个刷新日**之前**的数据重建的当日 Pool，逐日前推成一张布尔帧。消除幸存者偏差的唯一手段。
_Avoid_: 历史池、回溯池

**Pin**：
绕过排名强制进入 Pool 的标的。绕不过上市年龄过滤——研究与实盘在这一点上同口径。

**Quarantine**（隔离）：
某标的连续被交易所拒单、且同周期其他标的下单成功时，把它移出 Pool 并只走 reduce-only 退出。
「同周期他币成交」这条证据是定义的一部分：没有它，账户级故障就能经由这条路清空 Pool。

**Reference**（参照总体）：
横截面算子（秩、去均值、广度）所依据的标的全体。是**显式契约**，不是调用者恰好加载了哪些列。

### 信号与 sleeve

**Signal**（信号）：
一个把面板数据映射到每标的分数的纯函数。自己声明是否消费资金费率历史。
_Avoid_: 因子、alpha、indicator

**Strategy**（策略）：
Registry 里的一个条目：一个 Signal 加上一组参数、一个权重、一个证据指针、一个 sleeve 归属。
_Avoid_: model、策略实例

**Registry**：
声明哪些 Strategy 启用、各自什么参数、集成方法、有哪些非 main sleeve 的那份文件。引擎**只在启动时**读它。

**Sleeve**：
独立构建、独立做波动率目标的一组仓位。多个 sleeve 按 fraction 求和后再套 main sleeve 的上限与带。
_Avoid_: 分仓、袖子、子组合、sub-portfolio、book

**Main sleeve**：
承载全部风险预算的那个 sleeve。只有 main sleeve 时，构建路径与单 sleeve 时代逐位不变。

**Probe sleeve**：
组合层 ACCEPT 但信号级未 PASS，由操作者显式放行上线的小 sleeve。按 30 天归因 P&L 自动停掉。
组合层 REJECT 也能上，但 registry 要写明 `accepted_despite` 与理由（D-029）。
_Avoid_: 实验 sleeve、paper sleeve

**Fraction**：
一个非 main sleeve 占 main sleeve 风险预算的比例。

**Ensemble**（集成）：
把多个 Strategy 的目标合成一个 sleeve 的目标的方法。

**Target weights**（目标权重）：
一根 bar 上每个标的应持有的、以权益为单位的敞口。是 alpha 侧的唯一产出。
_Avoid_: 目标仓位（那是乘过权益之后的东西）

**Contribution**（贡献）：
单个 Strategy 对某根 bar 目标权重的分解份额。归因与 `NO_ACTION` 的持仓种子都读它。

**NO_ACTION**：
模型对某根 bar 不表态。语义是**保持上一仓位**——不是归零，也不是按原始分数建仓。

### 组合构建

**Risk budget**（风险预算）：
操作者声明的最大可接受回撤。`vol_target` 由它反推，而不是反过来。全系统只有一个风险预算。

**Gross**：
权重绝对值之和。上限以权益倍数表示。

**No-trade band**（无交易带）：
「变化不够大就保持原样」的规则，绝对臂以权益为单位、相对臂以当前仓位为单位。
**每条路径只算一层**：回测里它是仓位递推，实盘里参照的是交易所真实仓位。

**Overlay**（覆盖层）：
作用在已构建好的 sleeve 之上的一层调整。实盘上能动权重的有两个：exit overlay 与风险预算阶梯（R8，`starquant_alpha/overlays/ladder.py`）。
回撤节流也是 overlay，但在 `config/live.demo.yaml` 里关着（`drawdown_throttle.enabled: false`）。

**Exit overlay**：
bar 收盘评估的止损／移动止损／止盈加冷却期，阈值以**入场时**的日波动率为单位。
参考价固定为首次入场价，同向加减仓不重锚。交易所原生条件单明确不做。

**Drawdown throttle**（回撤节流）：
按距权益高水位的回撤，乘在整个 sleeve 上的一个标量。

**Margin cap**：
在 gross 上限处初始保证金占权益的比例上限。交易所杠杆由它反推，只改变保证金效率，不改变敞口。

**Participation**（参与率）：
单笔委托相对该标的近期成交额的比例上限。只豁免完全平仓：`exempt_reductions` 默认关，纯减仓单也会被截。
只在实盘存在，回测的成本模型里没有它。

**Compression**（压缩比）：
风险贡献离散度 ÷ 市场波动离散度。用来证伪「每标的自适应发生在组合层而不是交易所杠杆层」。

### 实盘循环

**Bar**：
一根闭合 K 线。系统的时间单位——所有决策都发生在 bar 收盘之后。未收盘的 bar 不参与任何计算。

**Confirmed gap**：
研究归档里的一段缺口，日归档和 REST 都问过，源头也没有。记在数据根目录的 `confirmed_gaps.json`，
写明问了谁、答了什么。它说的是**源头没有**，不是市场一定没成交：下架后重新上架、同名重新计价、
场地停机，都会在源头留下这种缺口。缺口永远不填——不插值，不前向填充。
_Avoid_: 已确认缺口、真缺口

**Cycle**（周期）：
实盘循环的一次完整执行：摄入 income → 目标权重 → 节流 → 退出 → 护栏 → 求差 → 缩放 → 下单 → 对账 → 报告。

**Target position architecture**（目标仓位架构）：
每根 bar 算出目标、与交易所真实仓位求差、只下差额。交易所仓位是唯一真值，循环重启幂等。

**Rebalance**（再平衡）：
把真实仓位推向目标仓位的那批委托。同一根 bar 内幂等，靠 `clientOrderId` 保证。

**Reconcile**（对账）：
下单之后核对交易所实际状态与本轮意图是否一致。

**Attribution**（归因）：
把一个周期的已实现盈亏按上一周期的 contribution 份额分给各 Strategy。

**Foreign**（外来盈亏）：
不是本循环下的单产生的盈亏。留在 ledger 里（那是真金白银），但不进 `by_strategy` / `by_symbol` / `total`。
对账做不了时退回全额归因——一个跑不起来的监控不可以反过来把整轮盈亏静默判给别人。

**External flow**（外部现金流）：
入金、demo 重置、抵押品兑换这类 TRANSFER。重置日起点与高水位，日报跳过该 bar 的 drift。

**Guards**（护栏）：
只保护实验有效性的那组硬约束：波动率目标、gross 上限、单币上限、日亏软停、数据过期禁交易、
kill-switch、flatten。**语义只有一份**，回测重放实盘真正会做的事。

**Kill-switch**：
一个文件。存在即拒绝一切**加风险**的写入，只放行降风险的那些：撤单、reduce-only 与 closePosition
下单、杠杆与 session 控制（`starquant_exchange/guard.py` 的 `is_risk_reducing`）。与 host allowlist
一起，是写入场地这一侧的「熔断」。它不是唯一的一道：循环另有连续失败熔断，连续 12 个周期失败就告警并
停止循环（`starquant_live/engine.py` 的 `breaker_stop`）。
本条曾写作「拒绝一切写入场地的操作」。照那句读，踩下开关就等于把仓位冻在原地、平不掉——词表比实现
更严，而且严在危险的一侧：真要平仓的人会以为自己先得把开关撤掉。

**Flatten**（平仓）：
把全部仓位显式清零的人工操作。

**Venue**（场地）：
下单去的那个交易所端点。与行情来源分开——行情读 mainnet 公共接口，下单走 demo。
_Avoid_: exchange（那是适配器包的名字）、broker

**Venue time**（场地时钟）：
交易所自己的时间。问交易所要**数据窗口**时用它；调度什么时候醒来仍以主机时钟为基准。

**Skew / Alignment / Jump**（偏移／对齐／跳变）：
主机与场地的时差、该时差对 bar 周期取余、以及它在两周期间的变化。
**恒定的整数个 bar 的偏移是可接受状态**；有害的只有对齐误差与跳变。

**Profile**：
一套完整的运行环境声明（demo / paper / …），决定用哪个场地、哪份 registry、哪些护栏参数。

### 证据与治理

**Evidence**（证据）：
支撑某个 Strategy 上线的那份验证报告。Registry 条目用指针引用它，启动门比对指针与实际参数。

**Trial**（试验）：
一次被评估过的配置。**去重口径是 `TrialRecord.fold_key` 的八项**：`param_key`、`range_start`、`range_end`、
`symbols`、`construction_digest`、`overlay_digest`、`symbol_set_hash`、`search_space_version`。
八项全同才是同一笔，精确重放只算一次。`range_end` 按 7 天分桶（`Policy.trial_range_end_granularity_days`）。

**Ledger**：
只追加的全部 Trial 记录。全仓库只有一份，是多重检验校正的分母。

**Verdict**（判定）：
一份验证报告的结论：PASS / WEAK_PASS / REJECT。以样本外为主，若干硬门一票否决。
_Avoid_: 结果、评分

**Pre-registration**（预登记）：
先写下验收规则再跑数。事后扫描出来的结论不构成验证。

**Falsifier**（证伪线）：
上线前写下的、一旦成真就说明这个决定错了的那个可观测量。

**KILL**：
一条已被证伪并关闭的假设。关闭是结构性的——写进代码让它无法再次发生，而不只是记一笔。

**Reopen condition**（重开条件）：
一条 KILL 要被重新审视所必须成真的事。有编号、有读取方，不是散在日志里的一段话。

**Policy**：
全部治理阈值的唯一存放处，**在代码里而不是配置里**——机器能改的 YAML 等于机器能移动自己的及格线。

**Lifecycle**（生命周期）：
一个 sleeve 的状态机：candidate → validated → booked → queued → probe → main，以及回退路径。
每一次拒绝都必须指名是哪条规则拒的。

**Canary**（金丝雀）：
对一次影子运行做的部署健康检查。**它不筛 alpha**——它只回答「这份 registry 部署下去像不像一个能工作的部署」。

**Transaction**（事务）：
一次可撤回的 registry 写入。机器自己执行写入，替代人工确认点的是它撤销自己的能力。

**Window**（窗口）：
一段可以花掉固定试验预算的研究期。预算读 ledger，不靠记。

**Replay**（重放）：
拿规则跑历史产物，列出每一处机器会与人做出不同决定的地方。目的不是「规则复现历史」。

**Fingerprint / Digest**（指纹）：
让一条运行记录能自我说明的摘要。三个互不覆盖：registry 指纹标识*信号与参数*，
construction 指纹标识*组合构建层*，policy digest 标识*治理阈值*。指纹**不拦截**任何配置。

**编号前缀**：
`D-` 架构决策，`E-` 证据条目，`M-` 度量指标，`KILL-` 已证伪假设，`R0`–`R10` 治理规则，
`DL-` 决策日志，`P` 研究轮次，`T-` 任务，`Q` 操作者裁决，`AC-` 验收条件。
