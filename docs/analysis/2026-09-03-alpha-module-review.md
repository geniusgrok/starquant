# 深度分析：Alpha 模块有效性复查、三个自适应层的启用状态、止盈止损的实际形态（第六轮）

> 分析头部（deep-analysis V3.2）
> - Interaction Mode: **Green**（全部关键事实由代码、实盘状态文件与只读交易所查询取证；唯一未知是 14:04Z 的 demo 账户重置由谁触发，属 Yellow 项，不改变框架）。
> - S/M/L: **L**。命中：≥3 模块（alpha / live / exchange / research 工具）、24h 自主下单、涉及资金（demo 虚拟资金）。全部改动可由 git 与 profile/registry 开关回滚。
> - 当前 Gate 决策上限：**Weak GO**。G6 有一个 OPEN 的 P0 Kill（KILL-027：实盘运行的配置 ≠ registry 证据验证的配置），关闭前不得 GO。
> - 外部动作授权：**无**。本轮只做只读查询（demo 账户 GET 端点、mainnet 公共数据）与两次写到 scratchpad 的回测；未改代码、未下单、未改配置。
> - 独立性声明（Phase 7）：同一 Agent 执行；先冻结 §2–§6 再攻击；所有反方结论只引用 E-040 ～ E-053 的可复核证据。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **Weak GO**：继续 demo 实盘验证，但在 P1～P4 落地前，实盘天数不计入 M-005～M-008 的证据窗口 |
| 用户四问 | ① 活跃交易池：**已启用**（每日刷新，13:37Z 纳入 CYSUSDT）。② 自适应杠杆：**已启用**（15 币全部 5x）。自适应下单：**已启用但从不触发**（保证金需求 23 vs 预算 9,157 USDT；KILL-026 已接受）。③ 止盈止损：止盈 6σ **作为 bar 收盘软件规则生效**（15 币状态已跟踪、0 次触发），止损/移动止损按证据关闭，**交易所条件单按 D-012 设计不下**，所以"当前委托"里永远看不到止盈止损单。④ Alpha 有效性：历史证据强、跨 universe 稳健，**实盘 OOS 证据为零**（6 小时） |
| 本轮最重要的发现 | **C-014 被证伪**：实盘跑的不是 registry 证据验证的配置。(a) 实盘面板没有资金费率历史，拥挤度修正被静默跳过（E-040）；(b) warmup 用默认参数算出 817 根 bar 的请求窗口，D-005 的 hold 语义在实盘只能存活 96 根 bar（E-042，等效 Sharpe 1.477 → 1.398、换手 +8%） |
| 第二重要的发现 | 14:04:56Z demo 账户被**重置**：+5000 USDT TRANSFER、无任何平仓成交、15 个仓位消失、状态文件仍记着仓位（E-044）。实盘权益序列出现非交易性断点；15:00Z 循环会重新建仓 |
| 最大提升空间（按证据强度排序） | 修正两处实盘/验证偏差（确定性收益）；被动执行降成本（成本占毛收益 15%，估 +0.1～0.17 Sharpe，但 demo 无法验证）；更慢的波动率估计降换手；池子准入加上市时长/波动率门；**不建议现在加新信号**（7 个候选已诚实否定 6 个） |
| 开放 P0/P1 | KILL-027（P0，evidence/live 不一致）、KILL-028（P1，hold 窗口截断）、KILL-029（P1，账户重置污染证据） |

---

## 1. Phase 1 · Reality Check

输入类型：**执行/审查型**（用户点名四项检查 + 要求优化方案）。需求三问：谁承担损失 = 单一操作者（错误的实盘证据 → 错误的启用/停用决策）；频率 = 每小时周期；现有方案能否满足 = 部分（模块都在、都开着，但实盘与验证之间有两处静默偏差，且实盘证据流刚被重置打断）。

Early Kill：无 FATAL。K2（结论只有低等级推理）不成立：所有结论均有 E1 证据。**G0 PASS**。

---

## 2. Phase 2 · Evidence Ledger（全部 E1，可复核；日期 2026-09-03）

| ID | 类型 | 来源 | 摘要 |
| --- | --- | --- | --- |
| E-040 | CODE+EXPERIMENT | `starquant_alpha/model.py:91-97`、`starquant_live/ports.py:31`、`starquant_alpha/signals/tsmom.py:107-109`；scratchpad `alpha_checks.py`（mainnet 公共数据，as-of 13:00Z） | `AlphaModel.targets()` 用 `Panel.from_frames(bars, interval)` 构面板，**不传 funding**；`MarketData` 端口只提供最新一期资金费率，而拥挤度修正需要 72 根 bar 的滚动和。`funding is None` 时修正函数原样返回。复现：无 funding 路径算出的 contributions / weights 与 `state.json` **完全相等（最大差 0.0）**；带 funding 时最新 bar 有 4/15 币会被缩仓（1000PEPE、SUI、CYS −0.703→−0.351、AKE +0.761→+0.380），817 根窗口内 2.5% 的币-bar 受影响。结论：**拥挤度修正在实盘从未生效** |
| E-041 | EXPERIMENT | scratchpad 两次 `research backtest --universe pit --from 2021-01-01` | 时点 universe 全样本：registry 配置（crowding 开）Sharpe **1.641** / 净 +291% / MDD −12.6%；实盘等效配置（crowding 关）Sharpe **1.716** / 净 +317% / MDD −13.5%。逐年均为正。第四轮在静态 15 币上是 1.553 → 1.587（开了更好）。**符号跨 universe 翻转**，效应量级 ≈ 噪声 |
| E-042 | CODE+EXPERIMENT | `starquant_alpha/model.py:51-54`、`starquant_live/engine.py:187-190`、日志 `limit=818`；scratchpad `hold_window.py` | `warmup_bars` 取 `SIGNALS["tsmom"].warmup_bars`，即**默认参数** 5/20/50 → 51，而非 registry 的 720 → 721；引擎因此只请求 **817** 根 bar（脚本复现 817）。后果：每周期面板里信号只在最后 96 根 bar 有效，D-005"NO_ACTION 保持上一仓位"在实盘最多存活 96 根 bar；回测里无上限。静态 14 币 2021-07→2026-09 回测：无界 hold Sharpe **1.477** / 净 +208% / 换手 318；实盘等效（hold ≤ 96）Sharpe **1.398** / 净 +190% / 换手 344；4.8% 的持仓币-bar 在实盘被误平。持仓期间低于阈值的连续段：中位 4、p90 53、最长 492 根，4.3% 超过 96 根。**窗口改为 1500（hold ≤ 779）时偏差恰为 0** |
| E-043 | CODE+EXPERIMENT | `tsmom.py:79-81, 89`；`alpha_checks.py` | 分母 `vol.clip(lower=return_scale=0.20)` 作用在**小时收益率标准差**（观测 0.005～0.038）上，窗口内 0.0% 的币-bar ≥ 0.20 → clip 永远生效，`vol_window` 是惰性参数（验证报告邻域测试对它的敏感度 = 0）。斜率分量均值 \|c\| 0.019 vs 动量 0.317、持续性 0.071（`slope_scale 0.01` 是为 5/20/50h 校准的）。有效信号 ≈ 0.533·tanh(加权 ret/0.2) + 0.133·persistence·direction |
| E-044 | DATA（只读，14:17Z） | `/fapi/v1/income`、`/fapi/v2/balance`、`/fapi/v1/allOrders`、`/fapi/v1/userTrades` | TRANSFER +0.01 与 **+5000 USDT**（14:04:56–57Z，tranId 0）；14:00:17Z 后**无 REALIZED_PNL**；循环 14:00:14Z 买入 1000PEPE 之后**无任何订单/成交**；余额 USDT 5000 / USDC 5000 / BTC 0.01（**多资产保证金模式**），totalMarginBalance 10,696.55；0 仓位、0 挂单。`state.json`（14:00Z）仍记 15 个仓位、权益 10,776.27。结论：**demo 账户重置**抹掉了仓位（无成交、无盈亏入账）。触发者 UNKNOWN（本会话 14:08Z 开始） |
| E-045 | CONFIG+LOG | `config/live.demo.yaml`、`state.json`、`cycles.jsonl`、`heartbeat.json`、`launchctl` | pool.refresh daily；leverage auto；exits take_profit 6.0 / stop_loss 0 / trailing 0；throttle 关。leverage_set 15 币 = 5；13:37Z `universe_update entered=[CYSUSDT]`；margin 块 `scaled: false, needed 23 / budget 9157`；exit_events 0；进程 PID 6182 由 launchd 于 13:37:02Z 从 HEAD d4e363b 启动，工作树干净 |
| E-046 | CODE | `starquant_live/reconciler.py:56-66`、`starquant_exchange/binance_usdm/venue.py:122-134`、`starquant_live/exits.py` | 启动时取消全部挂单；只发 MARKET 单；代码库里没有 STOP_MARKET / TAKE_PROFIT_MARKET。止盈在 bar 收盘由软件评估（D-012）。**交易所"当前委托"里按设计永远没有止盈止损单**；代价是最多 1 根 bar 的额外暴露 |
| E-047 | CODE | `starquant_live/exits.py:72-90` vs `starquant_alpha/overlays/exits.py:8, 147-148` | 实盘 `_reconcile` 每周期把 `entry_price` 重锚到交易所 VWAP（同向加减仓会改变），回测保留首次入场价。**止盈参考价在实盘会漂移**，D-012"回测与实盘同构"对加减仓后的仓位不成立 |
| E-048 | REPORT | `reports/research/overlay-20260903T1324Z.md`、`1258Z` | 止盈启用证据是在 **tsmom+flow 集成**上算的；flow 已停用，实盘只跑 tsmom。所有效应 Sharpe Δ ≤ 0.06、MDD Δ ≤ 0.4pp（噪声量级） |
| E-049 | REPORT | `tsmom-validation-20260903T133239Z.json`、`0619Z.json` | 时点报告 `sharpe_variance_period 0.0000`、`expected_max_sharpe 0.17`（ledger 里 5 个近乎相同的配置 + 43 个申报先验）→ DSR 方差被低估（日志已自述：按第二轮 16 配置的离散度 E[max] ≈ 0.8，候选 1.64 仍过）。时点报告 `grid_trials 1`：所谓 OOS 是固定配置在样本后 84% 上的表现，而该配置是第二轮在**同一时段**（静态 universe）选出的。**当前配置的真实样本外证据 = 0**；第二轮的真实逐 fold 选择（16 网格）OOS 1.38，5 fold 全部选中 168/336/720 |
| E-050 | CODE | `starquant_live/attribution.py:29-42` | 策略份额按贡献的**带符号和**归一化；两策略对冲时份额爆炸（11:00Z SUI：flow +7.06、tsmom −7.56，合计 −0.49）。单策略下无影响，重开第二策略时会失真 |
| E-051 | CODE/CONFIG | `starquant_cli/data_cmd.py:188-192`、`config/universe.yaml` | 研究时点表钉住 BTC/ETH、按月刷新；实盘钉住 BTC/ETH/BNB/SOL、按日刷新。池子准入只有"上市 ≥ 30 天 + 30 日成交量"：AKE σ_1d 29%、CYS 15.8% 进池后权重只有 0.16～0.8%，仍消耗订单与手续费；6σ 止盈对它们意味着 +174% 才触发 |
| E-052 | DATA | E-044 的余额 | 实盘权益 = totalMarginBalance，含 BTC 0.01（≈ 7% 权益）与 USDC 的折算 → **空仓时权益也随 BTC 波动**；drift 检查与日亏软停都在消费这个权益。基于 income 行的归因不受影响 |
| E-053 | LOG | `trades.jsonl`、`attribution.jsonl`、`reports/daily/2026-09-03.md` | 07:58Z 起 24 笔成交、交易性收入 −0.40 USDT（佣金 −1.5、资金费 −0.1、已实现 +1.3）；11 个周期；实盘有效时长 6 小时。M-005～M-008 需要 14～30 天 |

### 2.1 Claim Register

| ID | 命题 | P | Axiom | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C-014 | 实盘运行的配置就是 registry 证据验证的配置 | **P0** | A7 | 任一参数在实盘路径被静默跳过或截断 | E-040、E-042 | **REFUTED**（两处偏差；方向都偏保守/偏小，见 §7） |
| C-015 | 周级 tsmom 有真实、跨 universe 稳健的 edge | P1 | A2/A6 | 30 天实盘 Sharpe 低于期望 2 个标准误；或 2026-09 之后数据的时点重跑转负 | E-041、E-049、RESEARCH_LOG 第二/五轮 | SUPPORTED（回测），置信度 Medium：实盘 OOS = 0 天 |
| C-016 | 止盈止损"在生效" | P1 | A7 | 状态未跟踪、或触发后不产生 reduce-only 单 | E-045、E-046、tests T-X01～T-X04 | PARTIAL：止盈软件规则生效（0 次触发）；止损按证据关闭；交易所条件单按设计不存在 |
| C-017 | 交易池 / 自适应杠杆 / 自适应下单已启用 | P2 | A7 | 配置开着但状态文件无痕迹 | E-045 | SUPPORTED；下单缩放在 1 万权益下永不触发（KILL-026 已接受） |
| C-018 | 实盘权益与归因流可以作为 M-005～M-008 的证据 | P1 | A2 | 权益出现非交易性跳变 | E-044、E-052 | **PARTIAL**：income 归因可用；权益曲线含重置断点与抵押品估值噪声 |

**G2：PASS**（证据齐全且互相印证）。**G1：PASS**。

---

## 3. Phase 3–5 · 问题、相对价值、系统影响（COMPRESSED）

Problem Statement：对于在 demo 上无人值守运行周级 tsmom 的单一操作者，当他想用实盘归因去裁决"策略是否有效、 exit overlay/拥挤度修正是否值得"时，由于实盘路径与验证路径有两处静默偏差（E-040/E-042）、实盘权益又被账户重置与抵押品估值污染（E-044/E-052），得到的实盘证据既不对应被验证的配置、也不是干净的 P&L；不解决则 14～30 天后的"策略有效性报告"会得出错误结论。

Causal Chain：表层 = 拥挤度修正无效果 / 换手偏高 / 权益跳变；直接原因 = `targets()` 不传 funding、`warmup_bars` 取默认参数、无 TRANSFER 检测；深层原因 = 第四轮加拥挤度修正与第五轮加 hold/pool 时，没有一条"实盘 == 回测"的同构测试覆盖 registry 参数（现有 live 测试用 5/20/50 默认参数，E-042 因此不可见）；可干预杠杆 = 一条参数同构测试 + 一条实盘/回测 target 复现测试。

相对价值（G3/G4）：P1～P4 是纠错，不存在"不做"的选项；P9～P12 是有先验的假设，每个都需要预登记、计入 ledger；"加新信号"的相对价值最低（已否定 6/7）。系统影响（G5）：全部改动落在 `starquant_live`（≤ 120 LOC）与 `starquant_alpha/model.py`（≤ 20 LOC）；不触及交易所写路径。**G3/G4/G5 PASS。**

---

## 6. Phase 6 · Option Set 与推荐（即用户要的"方案清单"）

### Tier 0 · 完整性修正（先做；不做则实盘天数不算证据）

| ID | 方案 | 证据 | 预期效果 | 成本 | 验证 |
| --- | --- | --- | --- | --- | --- |
| **P1** | 请求窗口按 registry 参数算：`warmup = max(horizons)+1`（或直接 `history_bars: 1500`，引擎上限）；加测试断言 `engine.history_bars ≥ min_history + max(horizons) + covariance_halflife + 1` | E-042 | 等效 Sharpe 1.398 → 1.477、换手 −8%、消除 4.8% 误平 | ~20 LOC | 回放 `hold_window.py`：窗口 1500 时偏差 = 0 |
| **P2** | 拥挤度修正二选一：(a) 给 `MarketData` 加 `funding_history()`，实盘面板带 funding，并加"实盘 target == 回测 target"同构测试；(b) registry 置 `crowding_penalty: 0`，用 `validate --universe pit` 重新出证据与 sha。**推荐 (b)**：E-041 显示时点 universe 下关掉更好（1.716 vs 1.641），效应本就是噪声；除非预登记的时点 walk-forward 对照证明相反 | E-040、E-041 | 消除 KILL-015 意义上的证据/运行不一致 | (a) ~60 LOC；(b) 1 次 validate | 启动时 `registry_evidence_problems` 通过且报告参数 == 运行参数 |
| **P3** | 重置检测：每周期读 income `TRANSFER`，记入 `cycles.jsonl` 的 `external_transfer`，重置 `day_start_equity` / `equity_hwm`，drift 检查排除该 bar，webhook 告警 | E-044 | 实盘证据不再被重置污染；KILL-029 关闭 | ~40 LOC | 用 14:04Z 的两行 TRANSFER 回放 |
| **P4** | 把 D-005 做对：NO_ACTION 的回退值取 `state.last_targets`（跨周期持久），不再依赖面板窗口 | E-042 | 彻底消除窗口依赖（horizon 再长也不受 1500 上限约束） | ~30 LOC + 测试 | 断言：窗口 300 与 1500 得到同样的 hold 结果 |

### Tier 1 · 证据卫生（便宜，只跑研究）

| ID | 方案 | 证据 |
| --- | --- | --- |
| P5 | 用当前 registry（只有 tsmom）在时点 universe 重跑 `research overlay`，按 D-017 重新决定止盈 6σ 开/关（预期仍是噪声，两种结果都可接受） | E-048 |
| P6 | 把第二轮 16 网格的全样本 Sharpe 补进 `trials.jsonl`，让 DSR 方差诚实 | E-049 |
| P7 | 研究/实盘的池子口径对齐（钉住集合、刷新频率），并用 M-006 度量日刷新 vs 月刷新的成员换手 | E-051 |
| P8 | 止盈参考价：`exit_states` 已存首次入场价，`_reconcile` 只在方向改变时才从交易所重锚，同向加减仓不改 `entry_price` | E-047 |
| P8b | 归因份额改为按 \|贡献\| 归一化（或按各策略独立回测的边际），避免对冲时爆炸 | E-050 |

### Tier 2 · Alpha 提升假设（预登记、计入 ledger、时点 universe 上带对照）

| ID | 假设 | 先验 / 证据 | 估计 | Falsifier |
| --- | --- | --- | --- | --- |
| **P9 被动执行** | 非紧急调仓用 post-only 限价挂 1 根 bar，未成交回退市价 | 成本占毛收益 15%（E1）；成本压力 ×1/×1.5/×2 → Sharpe 1.64/1.49/1.35，≈ 每 7 bps 0.3 Sharpe；省 3～4 bps ≈ **+0.1～0.17 Sharpe** | 最大且最确定的单项 | demo 成交是合成的，**无法在 demo 验证**；只能在 paper 上用 mainnet 报价度量成交率，mainnet 后才是真证据 |
| P10 更慢的波动率估计 | `vol_halflife 48 → 168/336`、`covariance_halflife 96 → 336`、`no_trade_rel_band 0.25 → 0.4`（4 点预登记网格） | 周级信号 + 小时级波动率缩放 = 换手主要来源（第一轮结论） | 换手 367 → ~250 单位，成本占比 15% → ~10% | 波动率骤升时缩仓变慢，MDD 变差 > 2pp 即否 |
| P11 信号重规格 | (i) 清理惰性参数（`vol_window`、周级下的斜率项），纯整理、不声称收益；(ii) 假设：动量用 t 统计量形式 tanh(ret_h / (σ_1h·√h·k))，k 两点网格 | E-043；第四轮教训"信号层与组合层只能有一处做风险归一化"是明确的 falsifier | 不确定；主要价值是让参数邻域测试有意义 | 时点 walk-forward 对照不优于现配置即弃 |
| P12 池子准入 | 上市 ≥ 90 天（现 30）、或 σ_1d > 10% 的币不进池；`--min-tenure 3` 先跑一次 validate | E-051；flow 的短 tenure 名字贡献几乎全在空头，tsmom 上未知 | 减少 AKE/CYS 类的碎单与手续费 | 时点 OOS 下降 > 0.05 即弃 |
| P13 分散化 | **暂不加信号**。7 个候选已诚实否定 6 个；flow 空头小书（时点 OOS 1.09、DSR 不过、敞口 9%）等 ≥ 14 天 tsmom 实盘证据后再议 | RESEARCH_LOG 第五轮 | 现书 14 多 / 1 空 = 长 beta，分散化是最大的 Sharpe 杠杆，但边际研究回报低 | — |
| P14 波动率目标 | 现 gross 0.28、保证金占用 6%，远低于上限；`vol_target` 0.15 → 0.20/0.25 只线性放大 P&L，不改 Sharpe | E-045 | 这是 sizing 决策不是 alpha 杠杆 | 实盘 Sharpe 确认前不动 |

### Won't（Scope Firewall，沿用 D-012/D-017）

交易所原生止盈止损（只在 mainnet + 日内信号时重开）；止损/移动止损（证据为负）；回撤节流（边界案例，复苏 fold 转负）；Kelly / ML sizing；5 维打分池。

---

## 7. Phase 7 · Adversarial Review

> 编号冲突说明（2026-09-04 审计）：本文档的 KILL-030 / KILL-031 与 `2026-09-03-exits-pool-sizing.md` 的同号条目是**不同命题**。此后本文档的两条记作 **KILL-030b / KILL-031b**。同样地，本文档把 `starquant live verify` 的复现指标从 M-009 改号为 M-011，而 `2026-09-03-exits-pool-sizing.md` 的 M-009 指的是探针书的 30 天归因——两者不同，代码里已统一用 M-011（`starquant_live/verify.py`），2026-09-04 复核时无残留的 M-009 字样。

独立性：同一 Agent；冻结输入 = E-040～E-053 与 §6 的方案表；反方只引用证据 ID。

| Kill | 攻击命题 | 关联 | 严重度 | 状态 / 关闭条件 |
| --- | --- | --- | --- | --- |
| **KILL-027** | 实盘跑的配置不是 registry 证据验证的配置；KILL-015 的 sha 校验只保证"报告没被改"，保证不了"跑的就是报告里的东西"（Evidence Prosecutor / Delivery Saboteur） | C-014、P2 | **P0** | **OPEN**。关闭：P2(a) 或 P2(b) 落地，并加"实盘 target == 回测 target"同构测试。缓解事实：偏差方向偏保守（不缩仓 = 拥挤名字风险略高但仍受 max_weight 约束；hold 截断 = 敞口略小），时点全样本下实盘等效配置本身 Sharpe 1.72 |
| **KILL-028** | 817 根窗口让 hold 只活 96 根 bar，实盘比回测多 8% 换手、少 18pp 累计收益（Delivery Saboteur） | C-014、P1/P4 | P1 | OPEN → P1 关闭；P4 根治 |
| **KILL-029** | demo 账户可被重置（用户或平台），每次重置抹掉仓位与未实现盈亏、循环下一小时重新建仓付费；若反复发生，14 天实盘证据永远攒不齐（Risk Red Team） | C-018、P3 | P1 | OPEN → 确认触发者 + P3。若是平台周期性重置，需改为按 income 行而非权益做全部实盘指标 |
| KILL-030 | 拥挤度修正的收益符号跨 universe 翻转，第四轮的 PASS 是静态 universe 上的样本内改进（Evidence Prosecutor） | C-015、P2 | P2 | MITIGATED：P2(b) 把它从 registry 拿掉，或 P2(a) 后在时点上带对照重验 |
| KILL-031 | 止盈证据算在 tsmom+flow 上，实盘只有 tsmom（Evidence Prosecutor） | C-016、P5 | P2 | MITIGATED：效应本是噪声；P5 重算 |
| KILL-032 | 实盘止盈参考价随 VWAP 漂移，回测不漂移（Delivery Saboteur） | C-016、P8 | P2 | MITIGATED → P8 |
| KILL-033 | 权益含 BTC/USDC 抵押品估值，空仓也波动；日亏软停与 drift 用的是这个权益（Risk Red Team） | C-018 | P2 | ACCEPTED（记录）；可选：在 demo UI 把抵押品换成 USDT，或实盘指标改用 USDT 余额 + uPnL |
| KILL-034 | `vol_window` 惰性、斜率项近零，参数邻域测试对惰性参数报告"稳健"是误导；信号文档与实现不符（Complexity Accountant） | C-015、P11 | P2 | MITIGATED → P11(i) 清理；不构成收益缺陷 |
| KILL-035 | 单策略、14 多 1 空 = 做多 crypto beta；"加信号"是最大杠杆却已多次失败（Skeptical PM） | P13 | P2 | ACCEPTED：先把成本与换手的确定性杠杆用掉 |
| KILL-036 | 当前配置没有一天真正的样本外数据：所有历史都参与过某轮选择（Evidence Prosecutor） | C-015 | P1 | ACCEPTED（合法状态）：实盘就是 OOS；因此 P1～P3 必须先做，否则 OOS 数据本身不干净 |

Pre-Mortem（30 天后失败的最可能原因）：① 实盘 Sharpe 显著低于 1.5，但无法区分是策略失效还是 E-042 的换手/误平（→ P1 先做）；② 账户再次被重置，权益序列断成几段（→ P3）；③ 拥挤度修正修好后实盘反而变差，因为它在时点 universe 上本就是负贡献（→ P2 选 (b)）。

Inversion：要让这次复查白做，只需"把两处偏差当作噪声不修、继续攒实盘天数"。反向控制 = P1～P3 是实盘天数计入证据的前提。

**G6：PARTIAL**（1 个 OPEN P0，有明确关闭路径与可验证的测试）。

---

## 8. Phase 8 · Scope

**Must（本轮）**：P1、P2(b)、P3、同构测试。**Should**：P4、P5、P6、P8、P8b。**Could（预登记后）**：P10、P12、P11(ii)。**Won't**：见 §6 防火墙；P9 要等 mainnet 才能出证据，先在 paper 上度量成交率；P13/P14 明确推迟。

不以"第一版"为理由删掉的项：P3（资金/证据完整性）。

---

## 9–10. Delivery Contract 与 Learning Plan（草案，等用户确认方案后展开）

| DL | 内容 | 测试 | 验收 |
| --- | --- | --- | --- |
| DL-08 | P1 + P4：窗口与 hold 持久化 | T-L01 `history_bars ≥ 需要值`；T-L02 窗口 300 vs 1500 的 hold 结果相同；T-L03 实盘 target 复现回测 target（registry 参数） | `hold_window.py` 三条曲线重合 |
| DL-09 | P2(b)：registry 去拥挤度 + 时点 validate 证据 | KILL-015 校验通过 | 报告参数 == `state.json` 复现参数 |
| DL-10 | P3：TRANSFER 检测 | T-L04 回放 14:04Z 两行 → `external_transfer` 记录、hwm/day_start 重置、drift 排除 | 日报显示重置事件 |

| Metric | Claim | 指标 | 阈值 | 窗口 | 失败动作 |
| --- | --- | --- | --- | --- | --- |
| M-010 | C-015 | 基于 income 的 30 天策略 Sharpe vs 时点 OOS（±2 s.e.） | z < −2 | 30 天（从 2026-09-04 02:27Z 重启起算） | 复查 / 停用 |
| M-011 | C-014 | 上一周期的 contributions 与离线复现的最大差（`starquant live verify`） | > 1e-9 | 每小时（`com.starquant.check`） | 告警、停止计入证据 |
| M-012 | C-018 | 非交易性现金流与时钟偏差（`cycles.jsonl` 的 `external_flows` / `clock`） | 任一非零 | 持续 | 该 bar 不计入 M-010 |

编号说明：初稿把复现指标写作 M-009、现金流指标写作 M-011，与并行会话的探针止损 M-009、以及后来实现的 `live verify` 撞号。上表是最终编号，正文其余处提到的 M-009 一律指探针止损（`docs/analysis/2026-09-03-exits-pool-sizing.md`）。

---

## 11. Final Decision

**Weak GO**。硬门禁复核：OPEN P0 = 1（KILL-027，有可执行关闭路径），因此不得 GO；P0 Claim C-014 REFUTED 但偏差方向偏保守、实盘等效配置在时点 universe 上仍 PASS 量级，因此不 KILL；问题成立且方案明确，不 HOLD。Quality Score：真实性 5、证据 5、根因 5、战略一致 4、相对价值 4、可行性 5、范围收敛 4、可交付 4、可验证 4、对抗生存 4 = **44/50**，受 OPEN P0 压至 Weak GO。

附：本轮产生的可复核脚本与报告位于会话 scratchpad（`alpha_checks.py`、`hold_window.py`、`venue_probe.py`、`venue_forensics.py`、`venue_transfers.py`、两份 `tsmom-backtest-*.json`）；未写入 `reports/research/`，未追加 `trials.jsonl`（回测不计入 DSR 分母；若后续按 P11/P12 做 validate，须计入）。

---

## 12. 执行记录（2026-09-04，操作者确认账户重置为手动操作后按顺序执行）

| 项 | 状态 | 证据 / 位置 |
| --- | --- | --- |
| P1 请求窗口按 registry 参数 | **完成** | `SignalSpec.warmup_for`、`LiveEngine.history_bars`（无上限截断，超 1,500 启动拒绝）；测试 `test_history_bars_derive_from_registry_params_and_refuse_overflow` |
| P2 拥挤度修正 | **部分**：registry 已置 `crowding_window: 0`（随提交 383ad60 入库）；证据指针未能更新 | 并行会话在时点 universe 跑 16 网格后 DSR p 0.40（FAIL），ledger 诚实化之后 tsmom 拿不到 PASS 指针；(a)/(b) 二选一由操作者决定（见 RESEARCH_LOG 第六轮） |
| P3 TRANSFER 检测与重置 | **完成** | `LiveEngine._ingest_income`、`attribution.external_flows`、`reports.drift_check` 跳过；测试 `test_external_transfer_rebaselines_and_is_recorded`、`test_drift_check_skips_rebaselined_bars_and_daily_report_lists_flows` |
| P4 hold 跨周期持久 | **完成** | `scores_to_targets(initial=…)`、`AlphaModel.targets(previous=…)`、`_finish_cycle` 合并；测试 `test_previous_targets_seed_the_hold_across_cycles`、`test_live_targets_hold_previous_strategy_targets` |
| 同构测试（KILL-027 的防复发） | **完成** | `test_shipped_registry_live_path_matches_research_path`：实盘路径（无 funding）与研究路径（带 funding）在 shipped registry 上 targets / weights 逐位相等 |
| P5 止盈证据重跑 | **推迟** | 实盘书构成随探针书（D-019）变化，重启决定后再跑 |
| P6 ledger 补录 | **完成** | run `tsmom-validation-20260903T175314Z`（16 行）；并行会话另有时点 16 网格（`174552Z`） |
| P7 池子口径对齐 | **完成（钉住集合）/ 推迟（刷新频率）** | `universe.yaml` 钉住 BTC/ETH；日 vs 月换手 11.8 vs 7.3 次/月；共享 membership 表未重建 |
| P8 止盈参考价 | **完成** | `ExitOverlay._reconcile`；测试 `test_live_exit_reference_keeps_first_entry_across_same_direction_resizes` |
| P8b 归因份额 | **完成** | `strategy_shares` 按 \|贡献\| 归一化；测试 `test_attribution_shares_are_magnitudes_and_flows_are_separated` |
| P9 被动执行 | **不做（等 mainnet）** | — |
| P10 波动率估计 / 相对带 | **移交第七轮会话** | 与其 smoothing candidates 重叠 |
| P11 信号重规格 | **代码就绪、实验未跑** | `momentum_mode: vol_scaled`（默认 fixed，逐位不变）；测试 `test_tsmom_vol_scaled_mode_penalises_the_noisier_path_with_the_same_return` |
| P12 池子准入 | **未跑** | 需先决定 membership 表口径 |
| 实盘重启 | **待定（操作者决定）** | 在 tsmom 证据指针问题解决前不重启；13:37Z 的旧进程继续运行 |

KILL 状态更新：KILL-027 仍 OPEN（证据指针），但"实盘 ≠ 验证"的两处代码偏差已修并有同构测试守护；KILL-028 CLOSED（P1/P4）；KILL-029 CLOSED（P3；操作者确认为手动重置）；KILL-032 CLOSED（P8）；KILL-034 MITIGATED（文档 + vol_scaled 备选）；KILL-030/031 仍 MITIGATED。Final Decision 不变：**Weak GO**，重启与证据指针由操作者裁决。

---

## 13. 方案对照复查（2026-09-04）与后续交付

对 §6 的方案表逐项复查,发现四项遗漏,按建议顺序处理。**KILL-027 于本次正式关闭**:参数一致(现在由测试守护而非人工核对)、资金费率管线落地、同构测试就位、证据指针已更新。剩余 OPEN 项:无 P0。

| 复查发现 | 处理 |
| --- | --- |
| 证据门只校验报告身份,不校验参数——KILL-027 高一层的同类失败 | **已修**(82d898d):`SignalSpec.canonical_params` 补齐默认值后逐键比对,`registry.param_problems` 报出每个不一致的键与两边的值;validation 报告读 `best_params`,book 报告读 `sleeve.params`;`tests/alpha/test_evidence_gate.py` 用在架 registry 做守护 |
| M-011 是手动命令,没人跑 | **已修**(389fbea):循环每周期用行情端口已有的服务器时间调用测一次时钟偏差,写进 `cycles.jsonl.clock` 与心跳,超阈值边沿告警;`deploy/run_check.sh` + `com.starquant.check.plist` 每小时跑 `live status --check` 与 `live verify --check` 并推送失败。装载 launchd 是操作者动作 |
| P10(波动率估计/相对带)掉在两个会话之间,无人认领 | 本会话认领,见下 |
| §10 指标编号与并行会话撞号、§12 执行记录过期 | 本节修订;M-011 = 复现检查,M-012 = 现金流/时钟 |

**P5 的一次教训(如实记录)。** 首次重跑(02:08–02:10Z)结论是"按 D-017 双通过规则关闭止盈 6σ",静态 universe 上差 0.01 Sharpe 未过。随后发现并行会话在 02:25:58Z 合入了 `conviction_mode: sign`,而该次重跑用的是改动前的 score 模式 ledger——**证据比结论早了 15 分钟就过期了**。该结论已作废,未据此改动任何实盘配置;正在用当前 registry 重跑。方法论上的收获:overlay 这类"在集成上做决策"的证据必须记录它所依据的 registry 摘要,否则无法判断是否过期。
