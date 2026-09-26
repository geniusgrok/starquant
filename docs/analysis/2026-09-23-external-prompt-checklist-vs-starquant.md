# 外部量化 prompt 清单对照StarQuant

2026-09-23。一次清点，不是深度分析，也不是裁定请求。行号以 `b031c066` 为准。

## 它接的是哪个问题

2026-09-19，X 账号 @TechElyra 发了一条 thread：10 条 AI prompt。每条让模型扮演一家机构，
交付 10 项，一共 100 项。

原帖说这些 prompt 能取代年薪 50 万美元的 quant。这句不成立：清单产出的是检查项，不是 alpha。
但这 100 项覆盖了行业里该问的问题，可以当一张外部审查表用。这份文件拿它逐项问StarQuant：
这一项，仓库里有没有答案。

另有一份整理稿给每条 prompt 加了一条提醒，下文编号 `#n.R`；还有三条使用纪律，编号
`D.1`–`D.3`。这些一并判。prompt 原文和整理稿都不在仓库里。下文按「#prompt.项」编号，
项名照抄英文原标题。

## 判据

| 判定 | 意思 |
| --- | --- |
| 已有 | 仓库里有机制回答这个问题：代码、测试，或写明的决策 |
| 部分 | 有机制，但漏了这一项点名的某一块；或这一项要常设机制，仓库只有一次性测量 |
| 空白 | 问题适用于StarQuant，仓库里找不到答案 |
| 不适用 | 这一项预设了StarQuant没有的业务，比如做市报价 |

两条补充：

- 判「不适用」之前先找加密永续上的对应物。corporate action 对应合约下架、更名与重新计价，
  2008 崩盘对应加密自己的崩盘日。有对应物，就按对应物判。
- 仓库写明「决定不做」并给了理由的，判「已有」，备注写「决策：不做」。那也是一个答案。

「缺」是最容易判错的一类。这个仓库把十天前量过的东西写成过「从未跑过」
（`docs/analysis/analysis-calibration.md` 的 09-17 行）。所以下文每一处「缺」都做过反向搜索，
搜索词见文末。

## 结论

| | 已有 | 部分 | 空白 | 不适用 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 100 项 | 70 | 27 | 0 | 3 | 100 |
| 提醒 | 7 | 4 | 0 | 0 | 11 |
| 使用纪律 | 3 | 0 | 0 | 0 | 3 |

提醒是 11 行，因为 2.R 拆成了两行。数字由脚本从下文各表数出。

**没有一项是完全空白的。** 缺口都在「部分」里：机制在，漏了一块。漏掉的块集中在四处。

### 一、判据有，后果没有（1.10、1.R、D.3）

- **family gate 判了 `refuse`，没有后果。** 09-19 的重算对 tsmom 判 `refuse`：样本外夏普 1.2306，
  门 1.5238（`governance/verdicts.jsonl:19`）。退休分支只接 `Event.FAMILY_GATE_FAILED`
  （`starquant_governance/lifecycle.py:248`），全仓库没有代码产生这个事件。
  `family_gate_still_passes` 只在 probe 晋级 main 时读（`starquant_governance/lifecycle.py:233`），
  而 tsmom 已经是 main。
- **衰减规则没有读者。** 规则是「两个不重叠的 30 天窗口都低于回测 q10」
  （`starquant_live/reports.py:432`）。只有 `report weekly` 读它，`deploy/` 里没有排周报。
- **flow 的亏损上限打不响。** `probe.stop` 按已实现口径算，−2% 位于 14.6σ
  （`starquant_live/probe.py:128`）。改成盯市口径排在 10-03 的窗口（`governance/window_changes.yaml:28`）。
- **真正会生效的停手机制是 D-041 的到期放行。** `deploy/run_live.sh:47` 写死
  `BRIDGE_UNTIL="2026-10-13"`。到期之后 `--armed` 启动要过证据门，而 tsmom 的现行证据是 FAIL
  （`config/alpha_registry.yaml:351`）。它只在重启时生效，对正在跑的进程不起作用。

### 二、书的市场 beta 没有常设读数，也没有上限（1.7、3.8、5.2、5.6、6.4、6.9）

- 09-07 至 09-18 的 259 根 bar 上，「敞口 × 市场」解释了全部收益，残差为负，alpha 的 t 不显著
  （`docs/RESEARCH_LOG.md:13605`）。09-20 在一段下跌里复核：涨跌两端的隐含 beta 是 1.05 对 1.04
  （`docs/RESEARCH_LOG.md:14125`）。趋势跟踪在起作用时，上涨端应当明显更高。
- 这个读数来自 `starquant report beta`，只能手动跑，不进日报，也不告警。
- `PortfolioParams` 没有净敞口、beta 或板块上限的字段（`starquant_alpha/portfolio.py`）。
- 「做多 crypto beta」是 KILL-035 接受过的（`docs/analysis/2026-09-03-alpha-module-review.md:130`）。
  那时 k 还是 0.15（D-035），升到 0.60 之后没重裁。

### 三、尾部读数停在 k=0.30（3.5、3.6、4.8、8.3）

- 五段加密崩盘窗口的回放全在 k=0.30（`config/alpha_registry.yaml:214`）。k 在 09-14 升到 0.60，
  这些窗口没重跑。
- 没有 95% / 99% 的经验 VaR 或 ES。日报只有「正常一天多大」的 σ 尺子（`starquant_live/reports.py:924`）。
- 各信号分 regime 的表现没有读数。`regime_split_sharpes` 写好了，零调用者
  （`starquant_alpha/validation/stability.py:89`）。操作者 09-17 批过把它接进 validate
  （GAP-SF02，`docs/RESEARCH_LOG.md:11701`），还没做。

### 四、数据只查「有没有、新不新」，不查「像不像真的」（9.5、9.7、9.R）

- 常设检查问的是数据在不在、过没过期、对没对齐：过期整周期跳过（`starquant_live/guards.py:66`），
  归档校验和（`starquant_data/archive.py:84`），启动时核数据集清单（`tests/live/test_dataset_gate.py:1`）。
- 没有一条检查价格本身。OHLC 矛盾、冻结 bar、异常跳变都不查。
- 合约原地重新计价会留下假跳变，BNX 那次是 55 倍
  （`docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md:255`）。
  这只扫过一次，脚本没入库；当天这些标的都不是成员，所以没进过回测。
- 按代码路径推，实盘碰上这种 bar 不会被拦下，会进入信号与波动率的计算。这是推理，没有重放过。

## 值得补的缺口

价钱是估计。「不新增配置」的几项按仓库规则不该计 ledger，跑之前仍按惯例核一遍计费口径。

| # | 缺口 | 对应项 | 价钱 | 买到什么 |
| --- | --- | --- | --- | --- |
| G1 | 衰减规则进每小时的 `report daily --check`，或给周报排定时任务 | 1.10 | 代码 S；0 ledger；不动构造 | q10 规则第一次有读者 |
| G2 | 定 family gate 失败的后果：退休、降回 probe，还是只告警 | 1.10、D.3 | 先由操作者裁；代码 S | 09-19 那次 `refuse` 有去处，或者把「会退休」的说法改掉 |
| G3 | `report beta` 的读数进日报 | 3.8、6.4、6.9 | 代码 S；0 ledger；不动构造 | beta 与残差每天可见 |
| G4 | 在 k=0.60 下重跑崩盘窗口；日报加经验 VaR / ES | 3.5、3.6 | 脚本现成（`scratchpad/audit20260908_stress_windows.py`）；不新增配置 | 尾部读数对上现行构造 |
| G5 | 把 `regime_split_sharpes` 接进 validate 报告 | 4.8、8.3 | 研究侧代码 S；冻结期内可写 | 每份报告带分 regime 的夏普 |
| G6 | 实盘用 bar 之前加数值合理性检查，先只告警 | 9.5、9.7、9.R | 代码 S–M；只告警就不动构造 | 坏价与重新计价第一次有人看见 |
| G7 | 组合层的「打乱未来」因果测试 | 2.4 | 测试 S | 覆盖护栏重放、参照总体与多 sleeve 求和 |
| G8 | validate 报告给出保本成本倍数 | 2.R(b) | 代码 S；不新增配置 | 上真钱之前最便宜的一个定量 |
| G9 | 给 M-Q08 的「换手 ±25%」配仪器，执行质量读趋势 | 10.8 | 代码 S；0 ledger | M-Q08 四项第一次都有读数 |
| G10 | 时点成员表定时重建，显式传 `--refresh D` | 9.9 | 一个 plist。但重建会让启动门判证据与数据不符（`config/alpha_registry.yaml:330`） | 成员表不再靠人往前推 |
| G11 | 净敞口或 beta 上限 | 1.7、3.8、5.2 | 构造变更：冻结期之后，要走 validate，花 ledger | 限住方向性敞口 |
| G12 | size 与低波的横截面信号 | 6.1 | 花 ledger；先跑 `research power` | 清单里两个没测过的经典方向 |

G1 与 G3–G9 不动构造，冻结期内能做。G2 要先裁。G10 要先定它和启动门怎么配合。
G11、G12 要等冻结结束。

**后续（同日）**：操作者裁定 G2——family gate 失败时 main 降回 probe，probe 停在 probe；冻结到期按
10-13。落地与代价见 `docs/RESEARCH_LOG.md` 同日「操作者两条裁定」一节。上面两张表保持清点当时的样子。

### 后续（二）：清点之后合入的 PR

同日，main 又合入 #102–#109。下表的现状逐项在 `eeb4031c` 上核过，行号也以它为准。「在途」指写这一节时
还开着的 PR。#105、#107 与 #108 的数字引自各自的 PR 描述，没有重跑。本文的表格都不改，仍是清点当时的样子。

| 本文的项 | 现状 |
| --- | --- |
| G2：family gate 失败的后果 | #102 已做。`family_gate.refusals` 把 `governance/verdicts.jsonl` 的 `refuse` 行变成 `FAMILY_GATE_FAILED`，`governance advance` 据此把 main 降回 probe。`advance` 没排进任何 job，要人跑 `--commit`（`deploy/run_governance_gate.sh:28`）。`governance/governance_state.json` 里 tsmom 仍是 main |
| G5：`regime_split_sharpes` 接进 validate | #104 已做，只报告、不判定。`reports/research/` 里还没有一份报告带这张表 |
| G7：组合层的「打乱未来」因果测试 | #105 已做。植入 14 处一根前视，抓到 11 处。扫全部 79 个 cutoff 能抓到另外 3 处，代价约 40 秒；这个测试文件现在约 1 秒。没做。#107 把信号层三处因果比较改成逐位。它的描述另列 26 处，操作者裁定照改，#108 已合入 |
| 「说法与行为不符」前 2 行 | #102 已做。`FAMILY_GATE_FAILED` 有了产生方，说法改成「降回 probe」；冻结到期改为 10-13 |
| 「说法与行为不符」后 3 行 | 没动。原文仍在 `starquant_live/reports.py:367`、`starquant_cli/research_backtest_cmd.py:139` 与 `starquant_data/store.py:109` |
| 「陈述过期」25 行 | #103 改了 21 行，跳过 4 行。跳过的 `config/costs.yaml:16` 那句带日期，同文件 `:20` 已就地更正。另 3 行交给操作者：决策清单与 `governance/reopen.yaml` 两处。清单外还有两处也交给操作者：`starquant_alpha/validation/forward_board.py:73` 的运行时字符串，`starquant_live/rebalancer.py:30` 的字段注释。操作者答「按建议处理」，#110 在途 |
| G1、G3、G4、G6、G8–G12 | 没有合入的 PR，也没有在途的 |

#103 重核时发现，「陈述过期」表有两行本文写错了：

- **`docs/PREREGISTRATION.md:11` 那一行写反了。** `:11` 的「八项」是对的，
  `tests/live/test_the_preregistration_template_keeps_its_items.py` 钉着它。过期的是同文件 `:122`
  的「七项」，#103 已改成「八项」。
- **`docs/ARCHITECTURE.md:54` 那一行只对一半。** T-A03 确实只断言平均净收益为负。但 T-A06 自标
  D-011，是显著性口径的阴性对照（`tests/alpha/test_validation.py:132`）。它的名义水平是 5%，断言
  拒绝率不超过 20%。本文写「不是显著性检验」，漏了它。按 `D-011` 搜一遍 `tests/` 就能看到。

**后续（三）（同日）**：G1、G3、G4、G6、G8、G9、G10 已落地。结果、操作者裁定与还没定的事，见
`docs/analysis/2026-09-23-optimization-plan-from-external-checklist.md` 末尾的「执行记录」。

**后续（四）（2026-09-25）**：第二轮落地。3.4、3.9、6.4、6.9、8.9、8.R、10.9、10.10 各有了读数，2.10 有了
「不做图」的决定（D-047），D.1 进了预登记模板。本文的判定表保持清点当时的样子。结果与要操作者定的事，见
`docs/analysis/2026-09-25-external-checklist-round-two.md`。

## 逐项

### #1 策略架构（Goldman Sachs）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 1.1 Strategy Thesis | 已有 | `starquant_alpha/signals/tsmom.py:7` | tsmom 写了谁付钱：减仓太慢的杠杆多头。flow 只写了机制，没写对手方 |
| 1.2 Universe Selection | 已有 | `config/universe.yaml:6` | 只做 USDⓈ-M 永续，30 日成交额前 15，带滞回与上市年龄门（D-013、D-014） |
| 1.3 Signal Generation Logic | 已有 | `starquant_alpha/signals/tsmom.py:40` | 公式写在各信号模块，参数在 registry |
| 1.4 Entry Rules | 已有 | `starquant_alpha/signals/base.py:134`；`config/live.demo.yaml:266` | 目标权重架构没有离散的开仓。对应物是入场阈值、无交易带与 `band_entry_multiple` |
| 1.5 Exit Rules | 已有 | `config/live.demo.yaml:393` | 止损、止盈都是 6σ，收盘判定。时间退出判负（O-EX1），决策：不做 |
| 1.6 Position Sizing Model | 已有 | `starquant_alpha/portfolio.py:3`；`config/alpha_registry.yaml:124` | 按风险定仓：逆波动率加组合波动率目标。按把握度定仓是决策：不做，幅度不带收益信息 |
| 1.7 Risk Parameters | 部分 | `starquant_governance/policy.py:219` | 有回撤预算、风险预算阶梯、单币与毛敞口上限、日亏软停。缺板块上限与净敞口上限 |
| 1.8 Backtesting Framework | 已有 | `starquant_alpha/validation/walk_forward.py:1` | 见 #2 |
| 1.9 Benchmark Selection | 已有 | `starquant_live/benchmark.py:8` | 实盘用时点等权篮子。研究侧对照取全体 `panel.symbols`，两侧口径不同 |
| 1.10 Edge Decay Monitoring | 部分 | `starquant_live/reports.py:432` | 判据很多，后果很少，见结论一 |
| 1.R 怎么知道它已经死了 | 部分 | `governance/verdicts.jsonl:19` | 同 1.10 |

### #2 回测框架（Renaissance）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 2.1 Data Requirements | 已有 | `starquant_data/archive.py:1`；`starquant_alpha/model.py:181` | 月度归档带 SHA-256 校验。标的满 `min_history_bars` 才能交易 |
| 2.2 Backtesting Engine Architecture | 已有 | `starquant_alpha/backtest.py:1`；`:244` | 向量化为主。路径依赖的护栏与退出逐 bar 重放，和实盘调同一个步函数 |
| 2.3 Transaction Cost Modeling | 已有 | `config/costs.yaml:2` | taker 5 bps、滑点 2 bps、实际资金费。冲击模型默认关，系数未校准。真钱的成本模型在范围外（KILL-A） |
| 2.4 Lookahead Bias Prevention | 已有 | `starquant_alpha/backtest.py:262`；`tests/alpha/test_signal_suite.py:91` | t 决策、t+1 成交；全部注册信号都有因果测试。组合层没有，见 G7 |
| 2.5 Survivorship Bias Handling | 已有 | `starquant_data/archive.py:122` | 对应物是下架的永续。时点成员表含退市币。退市冻结期量过，补结算价平仓是决策：不做（KILL-Q6） |
| 2.6 Walk-Forward Optimization | 已有 | `starquant_alpha/validation/walk_forward.py:4` | 默认扩张训练窗。没真做选择的证据封顶 WEAK_PASS（D-043） |
| 2.7 Out-of-Sample Testing Protocol | 已有 | `starquant_alpha/validation/verdict.py:3`；`docs/RESEARCH_LOG.md:750` | 判定以样本外为主，另有 CPCV、PBO 与预登记。历史 holdout 是决策：不做，实盘期就是 holdout |
| 2.8 Monte Carlo Simulation | 已有 | `scratchpad/vol_target_drawdown_bootstrap.py:37` | 按周分块对 bar 级净收益重抽样，不打乱逐笔交易。只在 scratchpad 脚本里 |
| 2.9 Statistical Significance Tests | 已有 | `starquant_alpha/validation/multiple_testing.py:181` | 门按 ledger 的试验数去偏，PBO 与 CPCV 是硬门，另有随机信号阴性对照 |
| 2.10 Runnable Python Code | 部分 | `starquant_cli/research_backtest_cmd.py:1` | 代码与样例数据都有。没有任何可视化，也没有「不做图」的决定 |
| 2.R(a) 当根收盘价算信号又成交 | 已有 | `starquant_alpha/backtest.py:262` | 在下一根开盘成交。实盘每笔记 `decision_close`，实测滑点约为回测假设的 2.2 倍，全是 demo 成交 |
| 2.R(b) 成本调到荒谬的高度 | 部分 | `starquant_cli/research_validate_cmd.py:412` | 只有成本 1 / 1.5 / 2 倍与滑点 2–9.2 bps 两套网格。没有保本成本倍数，见 G8 |

### #3 风控系统（Two Sigma）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 3.1 Kelly Criterion | 已有 | `docs/analysis/2026-09-03-exits-pool-sizing.md:180` | 决策：不做，Kelly 列在 Won't 里，没单独写理由。仓位用波动率目标，k 由回撤预算反推（D-035） |
| 3.2 Stop-loss framework | 已有 | `starquant_alpha/overlays/exits.py:1` | 波动率单位的止损在跑。移动止损实现了但关着，时间止损判负 |
| 3.3 Maximum drawdown controls | 已有 | `starquant_governance/policy.py:219`；`starquant_live/engine.py:772` | 风险预算阶梯按归因回撤自动降 k，日亏 −5% 当日停加仓。09-22 的 k 扫描：按可动用 USDT 计，要 k≈0.30–0.35 才守得住 70%，10-13 重裁 |
| 3.4 Correlation monitoring | 部分 | `starquant_live/reports.py:691` | 只有 sleeve 之间的 M-014。持仓之间没有读数；`book_vol.ex_ante` 每周期落盘，没有读取方 |
| 3.5 Value at Risk | 部分 | `starquant_live/reports.py:924` | 日报有「正常一天多大」的 σ 尺子。没有经验 VaR 或 ES，见 G4 |
| 3.6 Stress testing scenarios | 部分 | `config/alpha_registry.yaml:214` | 一次性。五段加密崩盘窗口在 k=0.30 下回放过，k=0.60 之后没重跑 |
| 3.7 Leverage limits | 已有 | `starquant_live/leverage.py:27`；`:64` | 杠杆由 `margin_cap` 反推，加仓单按可用保证金缩小 |
| 3.8 Sector and factor exposure caps | 部分 | `config/live.demo.yaml:214` | 有毛敞口与单币上限。没有板块、净敞口或 beta 上限，见结论二 |
| 3.9 Liquidity risk assessment | 部分 | `config/live.demo.yaml:31` | 有成交额选池、2% 参与率与容量表。没有持仓级「平掉要多久、花多少」的读数 |
| 3.10 Daily risk dashboard | 已有 | `starquant_live/reports.py:1958`；`deploy/run_check.sh:123` | 24/7 市场没有开盘。对应物是 UTC 日报加每小时巡检 |
| 3.R Kelly 的估计误差 | 已有 | `config/live.demo.yaml:96` | 对应物是 k 的敏感度：各档 k 下的 CAGR、q95 回撤与破 50% 概率都量过 |

### #4 signal 研究（Citadel）

prompt 里的 factor / alpha signal，在StarQuant叫「信号」。

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 4.1 Signal idea generation | 已有 | `docs/analysis/2026-09-05-mining-proposer-pivot.md:63` | 一份 20 条的加密方向清单，逐条判了已搜、缺节点、缺数据，后扩到 51 条 |
| 4.2 Data sources inventory | 已有 | `docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md:321` | 在用 K 线、资金费、metrics 与现货。链上与宏观数据因无读取方撤出。历史深度有一处说错，见「顺带发现」 |
| 4.3 Feature engineering pipeline | 已有 | `starquant_alpha/mining/expr.py:16` | 挖掘表达式编译成与手写信号相同的 `SignalSpec`，过同一套门 |
| 4.4 Signal strength testing | 已有 | `starquant_cli/research_diagnose_cmd.py:1` | IC-by-horizon、`hit_rate` 与夏普都有。仓库的结论是 IC 显著与书赚钱几乎无关（`docs/RESEARCH_LOG.md:11794`） |
| 4.5 Decay analysis | 已有 | `starquant_cli/research_diagnose_cmd.py:51` | 按前瞻期看 IC。日历衰减测过一次，区间宽到两个方向都容得下 |
| 4.6 Correlation verification | 已有 | `starquant_governance/lifecycle.py:185` | 与在跑的书相关 ≥ 0.5 不能晋级。比对的是仓库自己的机制，不是外部因子库 |
| 4.7 Signal combination | 已有 | `starquant_alpha/ensemble.py:48`；`docs/ARCHITECTURE.md:62` | 决策：不做学习式合成。新信号作独立 sleeve 按 fraction 相加 |
| 4.8 Regime detection | 部分 | `starquant_alpha/validation/stability.py:89` | regime 门控判负。各信号分 regime 的表现没有读数，见 G5 |
| 4.9 Turnover analysis | 已有 | `starquant_cli/research_report.py:47` | 每份报告带零成本与全成本两套数。成本超过毛收益 40% 判不可投 |
| 4.10 Signal monitoring dashboard | 已有 | `starquant_live/reports.py:363` | M-010 每小时比对归因夏普与证据预期。比对口径有问题，见「顺带发现」 |
| 4.R 哪些方向还没被做透 | 已有 | `governance/reopen.yaml:1` | 已证伪清单带重开条件，另有「哪里还没搜」的地图。只有 tsmom 写了 edge 从哪来 |

### #5 做市引擎（Jane Street）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 5.1 Spread calculation model | 不适用 | `starquant_shared/types.py:118` | 全部是市价单，不报价 |
| 5.2 Inventory management | 部分 | `config/live.demo.yaml:214` | 对应物是方向性敞口。只有毛敞口上限间接限住它，净敞口峰值 2.09x（`docs/RESEARCH_LOG.md:13603`） |
| 5.3 Quote adjustment logic | 不适用 | `starquant_shared/types.py:118` | 同 5.1 |
| 5.4 Adverse selection detection | 不适用 | `docs/analysis/2026-09-08-backtest-guard-external-audit.md:352` | 没有挂单，也就没有被挑单 |
| 5.5 Speed and latency | 已有 | `starquant_live/scheduler.py:46` | 对应物是 bar 收盘后的执行时效，由 M-Q03 管 |
| 5.6 Hedging strategy | 已有 | `docs/analysis/2026-09-03-alpha-module-review.md:130` | 决策：接受，不对冲（KILL-035）。那是 k=0.15 时的裁定 |
| 5.7 Market microstructure | 部分 | `starquant_exchange/rules.py:31` | 价格与数量精度、最小名义额都处理了。盘口深度没读过；选池不做深度打分是写明的决定 |
| 5.8 PnL decomposition | 已有 | `starquant_live/reports.py:1988`；`docs/ARCHITECTURE.md:68` | 对应物：手续费、资金费、已实现盈亏按币累计，`research decompose` 拆信号与构造 |
| 5.9 Risk limits | 已有 | `starquant_live/guards.py:73`；`config/alpha_registry.yaml:505` | 日亏软停、probe sleeve 自动停、连续失败熔断 |
| 5.10 Performance metrics | 已有 | `starquant_live/risk_budget.py:577` | 对应物：市价单成交率约 100%，滑点按 sleeve 拆开读 |
| 5.R 限价单被人挑选 | 已有 | `starquant_shared/types.py:118` | 单型只有 MARKET。maker 路径列为 Should，`maker_fee_bps` 至今没有读取方 |

### #6 多 factor 模型（AQR）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 6.1 Factor Selection | 部分 | `docs/analysis/2026-09-05-mining-proposer-pivot.md:63` | 动量在跑；value 的对应物 carry 与 basis 判负；quality 没有对应物。size 与低波没当横截面信号测过，见 G12 |
| 6.2 Factor Definitions | 已有 | `starquant_alpha/signals/residual.py:3` | 公式写在各模块 docstring 与 Params 里 |
| 6.3 Factor Portfolio Construction | 已有 | `starquant_alpha/validation/decompose.py:10` | 每个信号单独走同一套构建与 validate，decompose 拆多空腿 |
| 6.4 Factor Exposure Measurement | 部分 | `starquant_live/reports.py:658` | 对在架信号与多空腿每周期有记录。书对 BTC、规模、低波、资金费的载荷没人算 |
| 6.5 Factor Correlation Matrix | 已有 | `starquant_cli/research_correlate_cmd.py:76` | 策略收益相关加边际夏普，相关 < 0.5 是晋级门。没有滚动相关 |
| 6.6 Multifactor Combination | 已有 | `starquant_alpha/ensemble.py:48` | 同 4.7 |
| 6.7 Rebalancing Methodology | 已有 | `docs/ARCHITECTURE.md:80` | 每根 bar 重算、只下差额，两道无交易带压换手（D-039） |
| 6.8 Factor Timing Analysis | 已有 | `config/alpha_registry.yaml:241`；`governance/reopen.yaml:85` | 资金费拥挤修饰是唯一在架的正例。regime 门、趋势门、throttle、GARCH 都判负 |
| 6.9 Performance Attribution | 部分 | `starquant_live/benchmark.py:1` | 按策略、币、多空腿、「市场 × 敞口」都能拆。没有多因子归因：两个回归各只有一个回归元 |
| 6.10 Full Python Implementation | 已有 | `docs/ARCHITECTURE.md:6` | 数据到目标权重全在仓库里 |
| 6.R 择时的正反证据；alpha 是不是 beta | 已有 | `docs/RESEARCH_LOG.md:13605` | 择时正反两面都有记录。`report beta` 回答了第二问：是 beta，见结论二 |

### #7 统计套利（D.E. Shaw）

pairs 09-09 判 REFUTED、转 retired（`governance/reopen.yaml:263`），09-17 重跑仍是 FAIL
（`reports/research/pairs-validation-20260917T091104Z.md:1`）。所以前十项都判「已有」，
理由是「决策：不做」；备注只写可迁移的部分。

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 7.1 Pair selection | 已有 | `starquant_alpha/signals/pairs.py:1` | 波动率匹配、互为最近邻，只看前缀窗口 |
| 7.2 Cointegration test | 已有 | `docs/RESEARCH_LOG.md:5414` | 只测过相关性配对，协整从没实现。它的搜索成本已预先归进 `pairs_search` 桶 |
| 7.3 Spread calculation | 已有 | `starquant_alpha/signals/pairs.py:147` | |
| 7.4 Z-score signal generation | 已有 | `starquant_alpha/signals/pairs.py:155` | |
| 7.5 Entry and exit thresholds | 已有 | `starquant_alpha/signals/pairs.py:49` | 开仓 2.0、平仓 0.5 |
| 7.6 Hedge ratio calculation | 已有 | `docs/RESEARCH_LOG.md:4227` | 用波动率匹配，OLS β 会被逆波动率定价抵消 |
| 7.7 Mean reversion speed | 已有 | `governance/reopen.yaml:263` | 半衰期从没估过，窗口是预登记的固定值 |
| 7.8 Regime change detection | 已有 | `governance/reopen.yaml:263` | 可迁移的是策略级失效检测，那一项是「部分」，见 1.10 |
| 7.9 Pairs portfolio | 已有 | `docs/RESEARCH_LOG.md:4280` | 可迁移的是 sleeve 加 fraction |
| 7.10 Complete Python code | 已有 | `starquant_alpha/signals/pairs.py:241` | 代码仍注册在信号表里，没进 registry |
| 7.R 多重检验校正 | 已有 | `starquant_alpha/validation/multiple_testing.py:181`；`starquant_alpha/validation/ledger.py:252` | 门取 N 个零假设最大值的 95% 分位，N 按策略桶算，覆盖挖掘、网格、构造参数与配对搜索。漏算有记录（`docs/RESEARCH_LOG.md:5388`） |

### #8 宏观策略（Bridgewater）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 8.1 Economic Indicators Dashboard | 已有 | `docs/ARCHITECTURE.md:23` | 决策：不做。宏观数据建过，因无读取方撤出。加密对应物 OI、多空比、基差当信号测过 |
| 8.2 Regime Classification | 已有 | `governance/reopen.yaml:85` | 决策：不做。对应物是趋势、震荡、高波动，两种形式都判负 |
| 8.3 Asset Class Behavior Map | 部分 | `config/alpha_registry.yaml:216` | 一次性。危机窗口回放与逐年夏普做过一次；分 regime 的夏普零调用者 |
| 8.4 Signal Construction | 已有 | `config/alpha_registry.yaml:72` | 对应物：多策略均值集成，各 sleeve 按 fraction 求和 |
| 8.5 All-Weather Inspired Allocation | 部分 | `docs/analysis/2026-09-17-alpha-efficiency-deep-analysis.md:220` | 对应物是一本低相关的底仓。评估规则在（D-018），这本书本身不存在 |
| 8.6 Tactical Overlay Rules | 已有 | `docs/RESEARCH_LOG.md:3113` | 按 regime 切档的 overlay 判负。在动权重的是风险预算阶梯 |
| 8.7 Instrument Selection | 已有 | `governance/reopen.yaml:163` | 只交易 USDⓈ-M 永续，现货路径不可执行 |
| 8.8 Rebalancing Triggers | 已有 | `docs/ARCHITECTURE.md:50` | 日历、阈值、信号三种触发都有 |
| 8.9 Correlation Regime Monitoring | 部分 | `starquant_alpha/portfolio.py:114` | EWMA 协方差在相关上升时被动缩书。币与币、币与 BTC 的相关没有常设读数 |
| 8.10 Geopolitical Risk Framework | 部分 | `docs/ARCHITECTURE.md:58` | 对应物是交易所事故、监管与稳定币脱锚。有拒单隔离与熔断，没有按事件调仓的规则 |
| 8.R regime 的确认延迟 | 部分 | `starquant_alpha/signals/flow.py:148` | 在跑的状态规则（flow 的空头门、阶梯的两周期宽限）确认延迟都没量过 |

### #9 数据管道（Bloomberg）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 9.1 Data Sources Architecture | 已有 | `starquant_data/binance_public.py:1`；`governance/reopen.yaml:153` | 价格、资金费、metrics、现货走币安免费公共源。情绪、解锁、宏观、链上逐条按「能否核时点」裁过 |
| 9.2 Real-Time Data Feed | 已有 | `starquant_data/live_feed.py:1`；`starquant_live/engine.py:1630` | 对应物：bar 收盘后用 REST 拉闭合 K 线，不用 WebSocket。请求重试、周期退避、过期整周期跳过 |
| 9.3 Historical Data Storage | 部分 | `starquant_data/store.py:30` | 按「标的 × 周期」存 parquet，原子写入。分钟级是决策：不做（`docs/RESEARCH_LOG.md:709`）。逐笔与盘口没有，对 1h 系统价值低 |
| 9.4 Data Cleaning Pipeline | 部分 | `starquant_live/staleness.py:6`；`starquant_data/store.py:110` | 去重、丢未收盘 bar、资金费按 bar 求和都有。缺口只检测不修 |
| 9.5 Corporate Actions Adjustment | 部分 | `docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md:255` | 一次性。对应物是合约重新计价、更名与 1000x 面值。只扫描过一次，没有常设的跳变探测 |
| 9.6 Feature Store | 部分 | `starquant_alpha/features.py:1`；`starquant_live/inputs.py:4` | 特征每周期按窗口现算，研究与实盘走同一份代码。没有预计算落盘；按 1h 节奏未必需要 |
| 9.7 Data Validation Rules | 部分 | `starquant_live/guards.py:66`；`starquant_data/archive.py:84` | 过期、未收盘、校验和、数据集清单都查。价格本身不查，见结论四 |
| 9.8 API Layer | 已有 | `starquant_live/ports.py:3` | 对应物：进程内端口加 Panel，不是 HTTP 服务。信号声明要什么数据，端口给不了就拒绝启动（D-023） |
| 9.9 Scheduling System | 部分 | `deploy/com.starquant.data.plist:12`；`starquant_live/engine.py:1202` | 每天同步数据、每小时巡检、每天重排交易池。时点成员表靠手敲命令重建，曾停在 09-03 靠前向填充（E-SY14） |
| 9.10 Complete Python Code | 已有 | `starquant_data/sync.py:1` | parquet 文件加进程内端口，不是数据库与 API 服务 |
| 9.R 免费数据的退市与合约变更 | 部分 | `starquant_data/archive.py:122`；`starquant_live/engine.py:166` | 退市两侧都处理了：候选集含退市币，实盘拿不到 bar 就按退市平仓。合约变更没有机制，见 9.5 |

### #10 执行算法（Virtu）

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| 10.1 TWAP Algorithm | 已有 | `tests/live/test_overlays_pool_sizing.py:138` | 循环本身就是一个按成交量限速、跨多根 bar 的执行计划（`docs/RESEARCH_LOG.md:5346`） |
| 10.2 VWAP Algorithm | 已有 | `docs/RESEARCH_LOG.md:5352`；`governance/reopen.yaml:68` | 决策：不做。权益达到 100 万 USDT 时由机器提醒重判 |
| 10.3 Implementation Shortfall Optimizer | 已有 | `docs/RESEARCH_LOG.md:5354` | 决策：不实现执行层。紧迫性由市价单与推导出的再平衡窗口承担 |
| 10.4 Iceberg Order Logic | 已有 | `docs/RESEARCH_LOG.md:5354` | 决策：不实现执行层，只下市价单。「隐藏规模」这个动机没单独论证过 |
| 10.5 Intelligent Order Routing | 已有 | `docs/analysis/2026-09-05-system-quality-deep-analysis.md:505` | 决策：不做多交易所。dark pool 没有对应物 |
| 10.6 Slippage Measurement | 已有 | `starquant_live/engine.py:999`；`starquant_live/risk_budget.py:577` | 每笔成交记决策收盘价，滑点按它量 |
| 10.7 Market Impact Model | 已有 | `starquant_alpha/backtest.py:75` | 平方根律，系数是假设不是测量，默认关。输出当容量曲线读 |
| 10.8 Execution Quality Analytics | 部分 | `starquant_live/risk_budget.py:673` | 滑点带标准误、分 sleeve 读，迟到与拒单计数。没有趋势；M-Q08 的「换手 ±25%」没有仪器 |
| 10.9 Pre-Trade Cost Estimation | 部分 | `starquant_live/composition.py:146` | 事前成本是平的 7 bps。逐单的事前估计不产出也不记录，没法逐单比预测与实际 |
| 10.10 Post-Trade TCA | 部分 | `scratchpad/decision_close_slippage_measurement.py:41` | 日报有成本段与分 sleeve 滑点。把滑点拆成跳空、延迟、价差、冲击只做过一次 |
| 10.R 记下信号价与成交价的差 | 已有 | `starquant_live/risk_budget.py:779`；`config/costs.yaml:29` | 记了，每小时读，超过 2 倍模型就告警。和回测假设比过：实测约 2.2 倍，`slippage_bps` 写明不改 |

## 三条使用纪律

| 项 | 判定 | 证据 | 备注 |
| --- | --- | --- | --- |
| D.1 How this fails | 已有 | `docs/analysis/2026-09-15-what-060-looks-like.md:65` | 现行构造有操作者签字的五条异常线，多个决定带预登记证伪线。预登记模板里没有「实盘失效方式」一项 |
| D.2 对抗式审查 | 已有 | `docs/analysis/analysis-calibration.md:3` | 四份外审；深度分析的 Phase 7 由独立子代理做；校准表记每次错在哪。它是约定，没有代码门 |
| D.3 什么时候该停手 | 已有 | `CONTEXT.md:188`；`deploy/run_live.sh:47` | KILL、`retired` 吸收态、probe sleeve 自动停、阶梯降档、kill-switch 都在。主策略没有自动停，见结论一 |

## 顺带发现

### 说法与行为不符：要先定哪边对

| 位置 | 写的是 | 实际 |
| --- | --- | --- |
| `starquant_cli/governance_cmd.py:529`、`deploy/run_governance_gate.sh:27` | family gate 失败经 `governance advance` 退休 | 没有代码产生 `FAMILY_GATE_FAILED`，见结论一 |
| `tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py:48` | 冻结到 2026-10-17T16:07 | `deploy/run_live.sh:47` 与 reopen 条件写 10-13。同一测试第 16 行说窗口从 09-13T19:00Z 起算，满 30 天是 10-13 |
| `starquant_live/reports.py:367` | 收入行就是回测夏普的口径 | 回测按盯市（`starquant_alpha/backtest.py:282`）。已实现与盯市的 30 天 σ 差约 24 倍（`starquant_live/probe.py:128`） |
| `starquant_cli/research_backtest_cmd.py:139` | 研究侧对照取全体 `panel.symbols` | 实盘用时点篮子（`starquant_live/benchmark.py:8`）。`docs/RESEARCH_LOG.md:13616` 把两侧读数之差归给书，基准口径的影响没量 |
| `starquant_data/store.py:109`、`docs/RESEARCH_LOG.md:565` | BNX 是退市 | 09-18 的分析记成 55 倍重新计价（`docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md:255`） |

### 陈述过期：改文档即可

| 位置 | 写的是 | 实际 |
| --- | --- | --- |
| `docs/RUNBOOK.md:85` | 阶梯 −35% / −50% | −49% / −70%（`starquant_governance/policy.py:219`） |
| `docs/RUNBOOK.md:102` | tsmom 跑 `crowding_window: 0` | 72（`config/alpha_registry.yaml:125`） |
| `docs/RUNBOOK.md:103` | flow −1%、`verdict: ACCEPT`、12-02 复审 | `max_loss 0.02`、`REJECT` 加 `accepted_despite`、30 天复审（`config/alpha_registry.yaml:490`–`506`） |
| `docs/RUNBOOK.md:135` | 日任务跑 `data sync` 与 `data pool refresh` | 还跑 `data spot`（`deploy/run_data.sh:37`） |
| `docs/ARCHITECTURE.md:64`、`:71` | PASS 要 NW t ≥ 2.0；门是「期望最大值」 | t 只报告（`starquant_alpha/validation/verdict.py:44`）；门是 95% 分位（`starquant_alpha/validation/multiple_testing.py:390`） |
| `docs/ARCHITECTURE.md:66` | 归因份额按 \|贡献\| 归一化 | 带符号的净敞口份额（`starquant_live/attribution.py:74`，D-044） |
| `CONTEXT.md:172`、`docs/ARCHITECTURE.md:68` | trial 去重键是 (param_key, range, symbols) | 8 元组（`starquant_alpha/validation/ledger.py:156`） |
| `docs/ARCHITECTURE.md:19` | CLI 清单 | 缺 `research power`、`research forward`、`report beta` |
| `docs/ARCHITECTURE.md` 决策清单 | 停在 D-042 | 代码引用 D-043 到 D-045。D-045 一号两用（`starquant_live/exits.py:107` 与 `starquant_live/benchmark.py:1`），D-043 也两用（`docs/RESEARCH_LOG.md:1999` 与 `starquant_alpha/validation/verdict.py:52`） |
| `docs/ARCHITECTURE.md:56`、`docs/RUNBOOK.md:9` | 时点成员表按月重建；重建命令不带 `--refresh` | 采用的是逐日表（`docs/RESEARCH_LOG.md:638`）。命令默认 `--refresh MS`（`starquant_cli/data_cmd.py:364`），照 RUNBOOK 重建会得到月表 |
| `CONTEXT.md:93` | overlay 有两个：exit overlay 与回撤节流 | throttle 关着（`config/live.demo.yaml:413`），在动权重的是风险预算阶梯 |
| `CONTEXT.md:106`、`docs/RUNBOOK.md:94` | 参与率上限只管加仓单 | 默认只豁免完全平仓，纯减仓也被截（`starquant_live/rebalancer.py:266`、`starquant_live/config.py:103`）。代码注释已承认（`starquant_live/rebalancer.py:259`） |
| `CONTEXT.md:145` | kill-switch 与 host allowlist 是「唯一的熔断」 | 另有连续失败熔断（`starquant_live/engine.py:109`） |
| `starquant_live/reports.py:410` | q10 还没有任何策略算过 | 两份现行证据都带 `oos_window_sharpe_q10` |
| `starquant_live/reports.py:2128` | 阶梯只告警，由人执行 | 引擎自动乘档位（`starquant_live/engine.py:772`），告警写「已执行」（`starquant_live/risk_budget.py:758`） |
| `starquant_live/risk_budget.py:3` | vol_target 0.30、50% 预算 | 现行 0.60、70% |
| `docs/analysis/2026-09-17-full-system-audit.md:98`、`config/costs.yaml:16` | `trades.jsonl` 没人读回去；M-Q08 的尺子还没有读数 | `starquant_live/risk_budget.py:570` 在读，日报据此告警 |
| `deploy/run_data.sh:62` | 注释说 `data spot` 不在日任务里 | 同文件第 37 行就在跑 |
| `governance/reopen.yaml:85` | 「相关按构造过不了 0.5」 | 这条推理 09-17 撤回（`docs/RESEARCH_LOG.md:12012`），经验裁定不变 |
| `governance/reopen.yaml:261` | KILL 名「配对/协整」 | 只测过相关性配对；`statsmodels` 声明了，全库零 import |
| `starquant_alpha/validation/stability.py:1`、`starquant_alpha/validation/multiple_testing.py:1` | 列出 regime split、BH-FDR、Holm | 前者零调用者，后两者只有测试调用 |
| `docs/PREREGISTRATION.md:11` | 必写八项 | 同文件 `:122` 与 `starquant_alpha/validation/forward_board.py:73` 写七项 |
| `config/alpha_registry.yaml:410` | flow 91% 与 tsmom 的空头重叠 | 回测期统计；09-17 实测当天 0%（`starquant_live/attribution.py:93`） |
| `starquant_alpha/validation/cpcv.py:51` | 调用方是 `research_cmd.py` | 已拆到 `research_validate_cmd.py` 与 `research_book_cmd.py` |
| `docs/ARCHITECTURE.md:54` | 随机信号阴性对照「必须不显著」 | 测试只断言 50 次随机信号的平均净收益为负（`tests/alpha/test_causality.py:46`），不是显著性检验 |

这份文件不改这两张表里的任何一处。它们会动 RUNBOOK、ARCHITECTURE、CONTEXT 与代码注释，另开一次。

**后续（同日）**：#102 与 #103 已处理这两张表，结果见上文「后续（二）」。「陈述过期」表有两行写错了，
更正也在那一节。

### 一处事实更正：币安发布历史深度归档

`docs/RESEARCH_LOG.md:905` 写「币安不发布历史 orderbook 归档」；09-18 的分析写「不可回溯——
Binance 不发布历史深度」（`docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md:326`）。
两处都不成立。

2026-09-23 读 data.binance.vision 的 S3 列表，`data/futures/um/daily/` 下有 `bookDepth` 与 `bookTicker`：

- `bookDepth/BTCUSDT/` 从 2023-01-01 起，到 2026-09-21 仍在更新。
- `bookTicker/BTCUSDT/` 止于 2024-03-30。

09-05 的分析（E-22，`docs/analysis/2026-09-05-system-quality-deep-analysis.md:102`）列对了。

这不推翻「选池不做深度打分」的决定。那条的理由还剩两条：归档比研究样本晚两年起步；demo 的深度是
合成的。归档的字段格式这次没核。它影响的是 2.3（价差能不能用历史数据估）、4.2 与 5.7。

**后续（同日）**：两处原文各加了一处更正标记，原文不动：`docs/RESEARCH_LOG.md` 那一段之后，与 09-18 分析
那张表之后。重核 S3 列表：`bookDepth/BTCUSDT/` 到 2026-09-22 仍在更新；`bookTicker/BTCUSDT/` 从 2023-05-16 起。

## 局限

- 判定来自读代码与文档，没有运行任何命令。「在跑」指代码路径与定时任务存在，不指此刻的实盘输出。
- 五个只读子代理分头清点。它们引用的证据逐行核过，每一处「缺」的反向搜索也独立重跑过。
- 「不适用」与「对应物」是判断，不是测量。换一个人判，#5 与 #8 的几项可能落在别的格里。
  10.4 子代理判「不确定」，这里按「不实现执行层」那条上位裁定归「已有」。
- 清点期间 origin/main 合入了 #97–#100。行号按合入后的 `b031c066` 重新核过。

## 反向搜索记录

每条都在 `starquant_*`、`tests/`、`docs/`（不含整理稿）、`governance/`、`config/`、`deploy/` 与
`reports/research/` 上搜过。

| 缺的是什么 | 搜索词 | 结果 |
| --- | --- | --- |
| `FAMILY_GATE_FAILED` 的产生方 | `FAMILY_GATE_FAILED` | 只有定义、处理分支与 docstring |
| 周报与成员表的定时任务 | `report weekly`、`governance advance`、`report beta`、`pool history`、`weekly`、`monthly`（`deploy/`） | 只有注释 |
| `book_vol.ex_ante` 的读取方 | `ex_ante` | 只有写入处 |
| VaR / ES | `VaR`、`CVaR`、`expected_shortfall`、`value_at_risk`、`在险价值` | 只命中方差函数 |
| 板块、净敞口、beta 上限 | `max_net`、`net_cap`、`beta_cap`、`beta_target`、`max_beta`、`market_neutral`、`sector` | 零命中；`PortfolioParams` 无此类字段 |
| 持仓级平仓时间 | `time to exit`、`liquidation horizon`、`exit capacity`、`平仓时间`、`退出时间` | 零命中 |
| 持仓之间的相关 | `correlation`、`corrcoef`（`starquant_live`） | 只有 M-014 的 sleeve 相关 |
| 分 regime 的夏普 | `regime_split_sharpes` | 只有定义 |
| 组合层因果测试 | `shuffl`、`permut`、`cutoff`、`truncat`，并与 `build_weights`、`AlphaModel`、`combine_books` 交叉 | 只有信号级、GARCH 与 exit overlay 的测试 |
| 超过 2 倍的成本压力、保本倍数 | `break even`、`保本`、`盈亏平衡`、`multiplier in` | 最高 2.0 倍 |
| 可视化 | `matplotlib`、`plotly`、`seaborn`、`savefig`、`pyplot`；`git ls-files` 里的图片 | 零命中；`matplotlib` 只在可选依赖里声明 |
| 协整检验 | `engle`、`johansen`、`adfuller`、`coint`、`statsmodels` 的 import | 只有计费注释与测试名 |
| size、低波信号 | `low vol factor`、`size factor`、`market cap`、`低波因子`、`规模因子`、`市值因子` | 零命中 |
| 价格合理性检查 | `outlier`、`price_jump`、`jump_filter`、`max_bar_move`、`sanity`、`winsor`、`异常值`、`离群` | 只有 carry 信号自己的 winsorize |
| 合约更名与重新计价 | `renam`、`改名`、`更名`、`symbol change`、`redenominat`、`corporate action`、`复权` | 只有文件与字段的改名 |
| 预计算特征 | `feature store`、`precompute`、`预计算`、`materializ`、`feature cache` | 一处无关注释 |
| 逐单事前成本 | `pre-trade`、`expected_cost`、`estimated_cost`、`predicted_cost`、`expected_slippage`、`预估成本`、`事前成本` | 零命中 |
| M-Q08 的换手仪器 | `M-FQ0`、`orders_per_day`、`订单/天`、`单/天` | 零命中 |
