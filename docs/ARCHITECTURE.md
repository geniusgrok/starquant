# StarQuant 架构

> 术语写法见 [`docs/GLOSSARY.md`](GLOSSARY.md)。

```
mainnet public data ──► starquant_data ──► starquant_alpha (features → signals → ensemble → books → portfolio → overlays) ──► target weights
        │                    │                                                                                       │
        │              pool (daily refresh / point-in-time membership)                                                │
demo venue (Binance USDⓈ-M) ◄── starquant_exchange ◄── starquant_live (scheduler → throttle → exits → guards → rebalancer → margin → execution → reconciler → reports)
```

| 包 | 职责 | 允许依赖 |
| --- | --- | --- |
| `starquant_shared` | 值类型（Side、InstrumentRules、Position、OrderRequest/Ack）、YAML/env 配置加载 | stdlib、pyyaml |
| `starquant_data` | 官方月度归档下载与校验、REST 补齐、parquet 存储、universe 排名滞回、**交易池**（`pool.py`：日线同步、时点成员表、实盘每日刷新）、实盘闭合 K 线、**缺口修补**（`repair.py`：K 线与资金费的缺口向日归档和 REST 各问一次，只合并缺口内的行；源头也没有的记进数据根目录的 `confirmed_gaps.json`，即 confirmed gap；不插值、不前向填充） | shared |
| `starquant_alpha` | 特征、信号、集成、组合构建、**overlays**（exit overlay、回撤节流、风险预算阶梯）、回测、验证、报告。**纯函数，零 I/O** | numpy、pandas |
| `starquant_exchange` | Binance USDⓈ-M REST：签名与时钟重同步、**限频错误的退避**（被动）、写入歧义语义（`OrderOutcomeUnknown`）、规则量化、下单/查单/仓位、杠杆档位、时间窗分页；host allowlist + kill-switch | shared、httpx |
| `starquant_live` | bar 驱动循环：目标权重 → 节流 → exit overlay → 护栏 → 与真实仓位求差 → 参与率/保证金缩放 → 幂等下单 → 对账 → 归因/心跳/日报（含 P13 风险预算监控）；每日池刷新与显式平仓 | alpha、data、exchange、shared |
| `starquant_cli` | `starquant data sync\|pool\|status\|spot\|metrics\|repair`、`research backtest\|validate\|diagnose\|correlate\|overlay\|book\|decompose\|mine\|list\|power\|forward`（`forward add\|status\|retire`）、`governance`（17 个子命令：`next\|advance\|plan\|gate\|apply\|canary\|replay\|status\|tenure\|transactions\|verdicts\|review\|divergence\|reopen\|window\|enable\|disable`）、`live run\|status\|verify\|soak\|flatten\|kill-switch\|alert-test`、`report daily\|weekly\|beta`；研究侧的 **feature store**（`research_feature_store.py`：signal 分数的落盘缓存，`STARQUANT_FEATURE_STORE` 打开，默认关，见下文） | 全部 |

上表 2026-09-13 更正过一处：`starquant_exchange` 原本写的是「限频、熔断」，而代码里从来没有主动配额管理，也没有断路器——只有被动的 429/418 + `Retry-After` 退避重试。`X-MBX-USED-WEIGHT-*` 被记进 `used_weight` 但没有任何读取方，`consecutive_transport_failures` 同样只写不读，所以一个正走向权重上限的客户端和一个闲着的客户端在日志里长得一模一样。现在两者各有一条**边沿触发的 warning**（`USED_WEIGHT_WARN` / `TRANSPORT_FAILURE_WARN`），**仍然不 sleep**：主动节流会改变实盘循环运行中的行为，那是一次要单独定价的改动，不是补文档的副产品。这个包里唯一的「熔断」是 kill-switch 文件加 host allowlist（`guard.py`），已单列。循环层另有一道连续失败熔断（`starquant_live/engine.py` 的 `breaker_stop`），不在这个包里。

2026-09-25 起，`starquant_live` 的监控层按外部清单的领域分模块。`reports.py` 原来 3,175 行，日报、周报与
beta 报告的读数全在里面，09-23 那批并行合并的冲突也集中在它身上。现在它只剩五个组装函数：
`daily_payload`、`daily_alerts`、`daily_markdown`、`weekly_payload`、`weekly_markdown`。读数按 09-23 清点
（`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`）的领域分住：

| 模块 | 清单领域 |
| --- | --- |
| `report_decay` | #1.10 衰减监控、#4.10 信号监控、D.3 里自动的那部分（probe 停书与复审） |
| `report_risk` | #3 风控看板：风险预算与阶梯、σ 尺子与回测 VaR / ES、保证金、抵押品、多空腿、M-015；持仓间相关（#3.4 / #8.9，#138）；平仓流动性（#3.9，#141） |
| `report_exits` | #1.5 / #3.2 exit overlay：退出与池子事件、够不着的阈值、反事实 |
| `report_execution` | #10 执行：重启代价与失败 bar（M-Q03）、无交易带的计划缺口、主机时钟；逐单 TCA（#10.9 / #10.10，#139）。M-Q08 本身在 `execution_fidelity.py` |
| `report_data` | #9 数据：研究归档覆盖、metrics 同源比对、数据集清单。bar sanity 在 `bar_sanity.py` |
| `report_events` | #8.10 事件风险：稳定币脱锚（币安现货 USDC/USDT）、交易所事故（循环自己写下的周期与成交记录，不联网）、极端行情（BTCUSDT 与 universe 等权篮子的小时收益对自身波动的倍数）。只报告，不告警 |
| `report_beta` | #6.4 / #6.9 归因：市场 beta（D-045）与多因子载荷（#140，计算在 `factor_loadings.py`），日报两节与 `report beta` 两页 |
| `report_governance` | 周报的 alpha 投入占比与预登记顺序 |
| `report_common` | 各领域共用的状态读取与格式化 |

调用方写死的 56 个地址照旧从 `starquant_live.reports` 取得到，而且是同一个对象。新读数放进所属领域的模块，
不放回 `reports.py`。各领域只依赖 `report_common`，互不 import。三条都由
`tests/live/test_the_report_layer_kept_its_addresses.py` 钉住。拆分只搬代码：81 个定义逐字相同，实盘状态
快照上 81 个报告产物逐字节相同（`scratchpad/reports_split_byte_identity.py`）。

2026-09-25 起，研究侧有一个 feature store（外部清单 #9.6）：`starquant_cli/research_feature_store.py`。它按内容
寻址、读穿透，缓存的单元是一个 signal 的分数帧，默认关。

**为什么在 signal 这一层**，是先量后定的（`scratchpad/feature_store_where_research_time_goes_20260925.py`）。
在时点面板上跑一次 validate 形状的运行：tsmom 默认网格 16 格加 flow sleeve，共 17 次评估。
`starquant_alpha.features` 的原语只占约 5%，signal 层约 13%。大头是依赖权重的递推：`ewma_portfolio_vol` 约
38%，exit overlay 约 20%。它们离了权重就算不出来，不是特征。一个原语 10–110 ms，从盘上核验着读一帧约
30 ms，缓存原语几乎省不下什么。一次 signal 计算要 0.3–33 s，chanlun 最贵。

**实盘碰不到它。** 研究层用子类 `StoredScoresModel` 覆盖 `AlphaModel.strategy_scores`，实盘执行的文件一个
没改。`starquant_live` 按 import 规则不能 import `starquant_cli`。实盘的建模入口 `composition.build_model` 也不经过
`with_feature_store`。跑实盘的 `starquant` 进程会 import 这个模块，因为 `starquant_cli/__init__.py` 注册全部命令组，
但 import 只定义名字。研究侧设 `STARQUANT_FEATURE_STORE` 才打开：`1` 指 `<checkout>/.starquant/features`，其它非空
值是目录，不设、空或 `0` 就是关。先例是 `STARQUANT_TRIALS_LEDGER`：打开时命令会在 stderr 说一句，不静默。

**键与失效。** 键覆盖面板每个字段的值、索引、列、block 结构、内存序，以及哪些字段共用一个索引对象。键
还覆盖 `starquant_alpha` 的全部源码、这个模块本身、解释器与库的版本、signal id 与参数。代码或数据改一个字节，
旧条目就再也读不到。进程加载之后源码被改过，store 在这个进程里整个停用，照常现算。

**逐位，而且连布局一起。** 命中返回的帧，block 结构与内存序都与现算的相同。实测过只保证值不够：同一组
权重换成另一种内存序，`ewma_portfolio_vol` 在 50,225 根里有 6,467 根末位不同。写入前先读回核验，读不回原样
的帧不落盘。这用到 pandas 的私有 block 结构；它哪天变了，store 退回现算并在 stderr 说一句，不会读出错数。

**磁盘与清理。** 时点面板上一个条目约 86 MB。默认上限 8 GiB，超了按最近最少使用淘汰到八成。store 只删
自己写的文件名，过期一小时的临时文件也清掉。整个目录随时可以删，里面没有算不回来的东西。坏条目当未命中，
重算后原位重写。

冷热对比见 `scratchpad/feature_store_cold_warm_20260925.py`。定稿代码上连跑两个进程，第二个读第一个写下的
条目，352 项逐位比对全部相同。validate 形状的那 17 次评估：冷的一轮 store 自己多花约 2.2 s，写盘 1.46 GB；
热的一轮 evaluate 从 70.3 s 降到 56.9 s，约占整轮 102 s 的 13%。meanrev 加 chanlun 各一次，热的一轮 evaluate
从 42.7 s 降到 7.0 s。只改组合参数的扫描，冷的一轮就开始命中。

2026-09-16 操作者裁定**撤出三条数据源**：`starquant_data` 的 `index_price.py`(307) / `macro.py`(844) / `onchain.py`(606)，连同 `starquant data index|macro|onchain` 三个命令与五个测试文件，共 1,757 行源码 + 2,092 行测试。它们 2026-09-10 落地，**建成了、也一直可达**，但没有任何读取方：`research_cmd._load` 只 join `metrics` 与 `spot`，`starquant_alpha` 没有任何叶子或信号读它们的列，`deploy/run_data.sh` 从落地当天起就把三者排除在日程外并写明了理由，`.starquant/data/` 里从来没有过它们的 store。

**这件事对本文件的意义不是少了三行，而是一类缺陷没有仪器**：`test_every_module_is_reachable_from_an_entry_point` 问的是「每个模块能不能被跑到」，三者都能，所以它一路全绿；没有任何东西问过「有没有东西真的在跑它」。唯一判断对了的是 `run_data.sh` 里的一段注释，而注释不是任何守卫会去读的东西。撤出前后五条命令的输出**逐字节相同**（`governance reopen|replay|next`、`report weekly`、`live run --dry-run --cycles 0`），这也是它们确实没被读过的最后一道证明。要拉回来：`git show 71863e9e`。

同日第二次裁定**撤出 #19 的清算数据层**：`starquant_data/liquidations.py`(451) 与 `liquidation_archive.py`(145)，连同三个测试文件与归档 fixture。它们与上面三条的情形不同——不是「没人读」，是**数据源本身不存在**：Binance 根本不发布 USDⓈ-M 清算历史，唯一的币本位归档早于实盘期 23 个月停更，所以平价义务不可满足、RISK-G3 一直把该列挡在实盘外。它们此前是 `EXEMPT` 里仅有的两个条目，理由写的是「作为查过什么的记录而留下」；撤出的论据正是这句话本身——**记录属于日志和 git 历史，不属于 import 图**，在那里它按零 headroom 的 source budget ratchet 计费，并被每一个审计这个包的人重读一遍。`EXEMPT` 现在是空的，即**树里每个生产模块都能从某条命令走到**，这是那道守卫有史以来能报出的最强状态。

**没有撤的**：`starquant_live/liquidation.py`（DL-X1 的清算**距离**，每周期写进 `cycles.jsonl`）与它的测试。一个是为不存在的数据准备的 ingest，另一个是读交易所自己那个字段的仪器，两者只是名字像。`governance reopen` 的 `regime-47` 读数也一字未变（仍是 `3/4 present; missing liquidations`）：那个探针问的是**磁盘**上有没有 store，不是代码在不在——撤掉 ingest 没有让那条重开条件变得无法回答，因为那个 ingest 本来也回答不了它。

架构测试在 `tests/architecture/`，2026-09-16 更正——这里原本写的是「唯一的架构测试：
`test_import_rules.py`」，而那句话在第二个文件落地的那天就过期了，此后又过期了六次：

| 文件 | 守的是什么 |
| --- | --- |
| `test_import_rules.py` | 依赖方向 + import 时无副作用（原本的那一条） |
| `test_every_module_is_reachable_from_an_entry_point.py` | 每个生产模块都能从某个 CLI 入口按 import 走到；豁免具名不计数 |
| `test_source_budget.py` | M-003 source budget ratchet：每个包不得超过上次量到的 ceiling，抬表须在同一提交写理由 |
| `test_suite_duration.py` + `suite_duration.py` | M-003 的第二道阈值：测试套件墙钟时间 ratchet |
| `test_every_launchd_plist_is_valid_xml.py` | 仓库里的 plist 必须是良构 XML（launchd 比 expat 宽容，曾放过一个不良构的文件） |
| `test_alerts_are_chinese.py` | 告警文案是操作者读得懂的语言 |
| `test_tests_never_touch_the_real_app_support.py` | 测试不得写进真实的 Application Support（一次 kill switch 曾被测试留在那里） |

这张表本身也会过期。它过期的方式是可见的：新增一个 `tests/architecture/test_*.py` 而不在这里
添一行，下一个读架构文档的人就会再数错一次——这正是上面那句「唯一」活了六个文件的原因。

## 关键设计决策

编号说明（2026-09-23）：D-043 与 D-045 各被两件事用过，下面的条目分开写。不改号：代码标识符（如 `D043_CAPPED`）、测试与 `docs/RESEARCH_LOG.md` 都引用现号，改号会让代码与历史对不上。新决策接着 D-046 往后取号；取号前先 `git grep -nwF 'D-0NN'`，确认这个号没人用过。D-001、D-007 至 D-010 在仓库里没有任何引用，不补条目。

- **D-002** 研究与信号只用 mainnet 公共数据；执行在 demo。demo 成交量是合成的、价格有偏差。
- **D-003** 目标仓位架构：每根闭合 bar 计算目标权重，与交易所真实仓位求差后再平衡；`clientOrderId = bd-<bar_open_ms>-<symbol>` 保证同一 bar 幂等。
- **D-004** 最小护栏只保护实验有效性：波动率目标、gross ≤ 2x、单币 ≤ 15%、日亏 −5% 软停、数据过期禁交易、kill-switch 文件、`starquant live flatten`。
- **D-005** `NO_ACTION` 保持上一仓位（不是归零，更不是按 raw score 建仓）。
- **D-006** 循环重启幂等，交易所仓位是唯一真值；允许 launchd KeepAlive + 退避。
- **D-011** 显著性检验对重叠标签做非重叠采样或 Newey-West 修正；随机信号阴性对照必须不显著。落在两条测试上：`tests/alpha/test_validation.py` 的 T-A06 用持续噪声分数对 4-bar 重叠标签，断言 30 个种子里 Newey-West 与非重叠采样的拒绝率都 ≤ 20%（名义水平 5%，容差比字面宽）。`tests/alpha/test_causality.py` 的 T-A03 抽 50 组随机权重、按 7 bps 回测，只断言平均净收益为负。
- **D-012** exit overlay（`starquant_alpha/overlays/exits.py`）在 bar 收盘评估，阈值以入场时日波动率为单位（止损 / 移动止损 / 止盈 + 冷却期），回测循环与实盘调用同一个 `exit_step`；实盘以交易所的 `entryPrice` 为参考并把状态持久化到 `state.json`。交易所原生条件单明确不做（见 `docs/analysis/2026-09-03-exits-pool-sizing.md`）。
- **D-013** 研究用时点成员表：`starquant data pool history` 用 2021 年以来所有有归档的 USDT 永续的日线成交量重建"当时的 top-15"（`--universe pit`），消除幸存者偏差。重选最初按月；2026-09-04 操作者决定改为按日，与实盘每日刷新对齐（`--refresh D`）。命令默认原是 `--refresh MS`，不传就会重建出月表；2026-09-23 起默认 `D`。**两半必须同口径**：研究侧要求 `min_age_days` 根日线才参与排名，实盘 `LivePool.select` 原本完全没有年龄过滤，于是上市九天的新币可以占掉 15 个名额之一、再被 `min_history_bars` 拒绝交易——实盘跑的币数少于为它背书的每一次回测，且无处可见（2026-09-04 修复，`_volume` 顺带返回已收日线根数；pin 也不能绕过，与研究侧一致）。`universe.json` 只有一个写入方：`data pool refresh` 与实盘 sink 走同一条排序规则，`data sync` 只负责下载（此前它按本地 1h 成交额另排一次并写同一个文件，文件含义取决于谁最后跑）。
- **D-014** 实盘每日刷新交易池（同一滞回：进入 ≤15 名、离开 >20 名）；被移出的币目标置 0 并 reduce-only 平仓，直到平掉前仍在受管集合里——**退出侧遍历仓位，进入侧遍历池子**。新进入的币沿用 `min_history_bars` 等待历史。进入侧原本读的是 `leaving`，而 `leaving` 每周期会被过滤成「还有仓位的币」，于是被移出并平掉之后的那一个周期里它仍在 `managed`（该列表在过滤之前就建好了）、模型照常给它权重、没有任何地方归零——实盘会在**已离开池子的币上重新开仓**（复现值 952 USDT）。2026-09-04 修复并加测试；实盘 `cycles.jsonl` 中当时尚无 `left` 记录，因此未曾触发。
- **D-031** 场地健康隔离：某个币在连续 `pool.quarantine_after` 个周期被交易所拒单——且**同一周期内其他币的下单是成功的**——则移出池子并只走 reduce-only 退出，只有下一次每日刷新重新选中它才回来。要求「同周期他币成交」这一条证据，是为了让账户级故障（保证金、时钟、封 IP）永远无法经由这条路清空池子：那属于 guards 的职责。代价是一个盲区：整周期只有一笔单且被拒时不构成对该币的证据，不计数。预登记证伪线：30 天内在没有交易所事故的情况下触发超过两次，说明阈值错了而不是币错了；`starquant report daily` 的 `pool_quarantined` 计数。
- **D-015** 只有一个风险预算（波动率目标 + gross/单币上限）；自适应项只做乘在整本书上的标量（回撤节流）或下单层的约束（保证金、参与率），绝不叠加多个"比例"。
- **D-016** 交易所杠杆 = `min(max_leverage, 档位上限, ceil(max_gross / margin_cap))`（默认 5x），只改变保证金效率，不改变敞口；下单前按可用保证金按比例缩小加仓单。
- **D-017** exit overlay 与回撤节流的启用由预先登记的验收规则决定（`starquant research overlay`：OOS MDD 改善且 OOS Sharpe 损失 ≤ 0.10），不满足则默认关闭。
- **D-018** 新策略作为独立小书加入（各书独立构建、按 fraction 求和、总书套主书上限）的验收由预登记规则决定（`starquant research book`）；组合层 ACCEPT 不替代信号级 PASS。首个用例 flow 空头小书：组合层 ACCEPT / 信号级 FAIL；操作者按 D-019 把它作为探针书上线。
- **D-019** 探针书：registry 的 `books:` 声明独立小书（`fraction` = 主书风险预算的比例），策略用 `book` 归属；模型按书独立构建、求和后套主书上限与带（`combine_books`），只有主书时路径逐位不变。`verdict: ACCEPT` 只在非主书且带显式 `probe` 块时被启动检查放行。D-029 起书级 REJECT 也能放行，条件是 `probe` 块写明 `accepted_despite: REJECT`、`reason` 与 `review_after_days`；`starquant_live/probe.py` 按 `attribution.jsonl` 的 30 天归因 P&L 自动停书并持久化，日报在复审日标 REVIEW_DUE。
- **D-020** 验证判定以样本外为主（2026-09-04 操作者决定）：PASS = 走前 OOS Sharpe ≥ 1.0 且 OOS 净收益的 Newey-West t ≥ 2.0，WEAK_PASS = 0.5 / 1.5；fold 一致性、CPCV 负路径比例、PBO（网格 ≥ 4）、成本 2× 为硬门；DSR 照常报告但不再一票否决（`starquant_alpha/validation/verdict.py`）。**2026-09-06 起 t 只报告、不判定**（D-P2）：PASS / WEAK_PASS 的 Sharpe 线仍是 1.0 / 0.5，t 的 2.0 / 1.5 已撤。`decide` 读 `oos_t_stat` 只查它在不在：没有这个字段的报告早于 D-020，不能通过。
- **D-022** 实盘请求窗口 = `max(profile.history_bars, min_history_bars + 模型在 registry 参数下的 warmup)`（周级 tsmom 为 1,442），超过 1,500 启动即拒绝；`NO_ACTION` 的 hold 以上一周期的 `state.last_contributions` 为种子跨周期持久（D-005 的完整实现），与全历史回测的 forward-fill 同义（E-042）。
- **D-021** 每周期开始先摄入 income：交易性收入按上一周期的贡献归因。2026-09-17 起份额是带符号的净敞口份额（D-044，`starquant_live/attribution.py` 的 `strategy_shares`）；此前按 \|贡献\| 归一化，反向持仓的策略会跟着该币的盈亏同号记账。两腿几乎抵消（净敞口不到毛敞口的 10%）时，该币的收入记进 `unattributed`，并按币单列在 `cancelled` 里，不归任何策略。TRANSFER 类现金流（入金、demo 重置、抵押品兑换）重置日起点与高水位、写入 `cycles.jsonl.external_flows`，日报 drift 跳过该 bar（E-044）。 exit overlay 参考价固定为首次入场价，同向加减仓不重锚（E-047）。
- **D-023** 信号自己声明是否消费资金费率历史（`SignalSpec.needs_funding`）；声明为真时 `AlphaModel.targets` 没拿到历史就报错、`LiveEngine.startup` 在行情端口不提供 `funding_history` 时拒绝启动，实盘面板与研究面板由同一份结算费率构成（KILL-027 的结构性关闭）。`starquant live verify`（M-011）用公共数据 + `state.json` 离线重算上一周期的 contributions 并逐币比对；`cycles.jsonl` 的 `gross_before` 改用 `positionRisk` 的仓位求和（账户报文不带 positions 数组时旧口径恒为 0）。
- **D-024** 证据的可复现与可归因：每份 validate 报告记录网格 / fold 数 / min_train / purge / 每个配置的全样本 Sharpe，fold 向量可从报告自身复现（E-049 的教训）；ledger 按 `TrialRecord.fold_key` 去重，精确重放只计一次（与 `research book` 一致）。键最初是 `param_key`、`range_start`、`range_end`、`symbols` 四项（旧文简写作 (param_key, range, symbols)）；KILL-Q5 补上 `construction_digest`、`overlay_digest`、`symbol_set_hash`、`search_space_version`，成了八项。2026-09-14 起 `range_end` 按 7 天分桶（`Policy.trial_range_end_granularity_days`）；DSR 同时报告 pooled（ledger + 网格离散度）与 noise-null（单个 Sharpe 估计的抽样方差）两个零假设，均为信息性，判定归 D-020；在集成上做决策的报告（`research overlay`）记录 `registry` 指纹——按启用条目经各信号自己的参数对象规范化后的摘要，外加 ensemble 方法与各书 fraction，所以改注释不会变、改参数一定变（P5 那次「证据比结论早过期 15 分钟」靠时间戳才发现）；`research decompose` 把一本书拆成 full / constant_long / sign_only / long_only / short_only / equal_notional，以区分信号与组合构建的贡献（不计入 trials ledger）。见 `docs/analysis/2026-09-04-round7-strategy-factor-deep-analysis.md`。
- **D-025** 主机时钟是基准（2026-09-04 操作者决定，不校准系统时钟）。因此**恒定的整数个 bar 的偏移是可接受状态而不是故障**：偏移接近整数根 bar 时，循环仍在真实 bar 收盘后不久醒来、交易刚收盘的那根。守的是两件真正有害的事：**对齐误差**（偏移对 interval 取余，决定唤醒时刻是否落在未收盘的 bar 里，超过 `guards.max_bar_alignment_seconds` 告警）与**跳变**（两周期间偏移变化超过半根 bar，会重映射全部标签并可能让 income 水位线倒退——2026-09-04 的 -1023）。`cycles.jsonl.clock` 记录 `skew_ms` / `alignment_ms` / `whole_bars` / `jumped`；日报按 `as_of_ms`（数据自带的 bar）分桶，使一天的报告描述的是真正被交易的那一天。
- **D-026** 构建指纹：`construction_fingerprint` 把组合构建（波动率目标、单币/gross 上限、绝对与相对再平衡带、 exit overlay、回撤节流、杠杆策略、各策略权重）摘要成一个 digest，启动心跳记全量、每周期记 digest。registry 指纹标识*信号*、启动门比对*策略参数*，两者都看不见构建层；2026-09-04 采纳 P10 cell B 时实盘的相对带走到 0.40 而 tsmom 的证据是在 0.25 下验证的，运行记录里没有任何东西说明这一点。它**不拦截**任何配置——构建层与证据分层是否可接受属于操作者决定——只保证一条实盘记录能自我说明。
- **D-027** 场地的保证金算术坏掉时，循环不能因此静默变成只减仓（2026-09-04，`08231af1`）。demo-fapi 曾把 `totalInitialMargin` 报成 int64 溢出值，再据此算出 `availableBalance` 为 0；照信它，保证金缩放会把每一笔加风险单削成零，而账户其实 95% 空闲。账户报文自相矛盾时，`Snapshot.available_margin` 改用 `positionRisk`，按循环设定的杠杆自己算占用（`starquant_live/reconciler.py`，`tests/live/test_margin_headroom.py`）。
- **D-028** 判定的第二条件对**选择**敏感（2026-09-04）：PASS 还要求走前 OOS Sharpe ≥ 该策略 ledger 去重后配置数下的期望最大值，零假设取单个 OOS Sharpe 估计的抽样分布而非 ledger 合并离散度（后者两个方向都退化过）。**2026-09-06 起门改为零假设下最大值的 95% 分位**（KILL-Q3，`max_sharpe_quantile`，α = 0.05）：一条纯噪声曲线约有一半机会越过期望最大值，在上线报告自己的零假设上实测 43.5%。报告的 `oos_selection.gate` 记下阈值出自哪条规则，旧门算出的阈值 `decide` 不认，要求重算。`oos_t_stat` 保留但降格为短样本保护——小时级净收益上它就是 `Sharpe × √年数`（比值 1.001），四年以上不约束；同一天 D-P2 再降一级，只报告、不判定（见 D-020）。启动门同时比对**组合构建**（`construction_problems`）：无 `portfolio` 段的旧报告跳过，从第一份带该段的报告起，band/半衰期的静默漂移会被拒绝启动。
- **D-029** 探针书可以引用书级判定为 REJECT 的报告，但 registry 必须把这个例外写出来（2026-09-04，`1038ef4d`）：`probe.accepted_despite` 要与判定一致，并带 `reason` 与 `review_after_days`，缺一项启动门就拒绝（`starquant_alpha/registry.py` 的 `_probe_problems`）。背景是 flow 小书的书级判定当天转为 REJECT。另外两条路都更坏：继续引用一份 universe 已不在盘上的旧 ACCEPT，或改指 REJECT、由 KILL-015 拒绝启动整个循环，而不只是停掉这本小书（`1038ef4d` 的提交说明）。`governance replay` 把它列为具名例外（`starquant_governance/replay.py` 的 `EXCEPTIONS`）。
- **D-030** income 查询窗口用**场地时钟**。签名请求对错误的主机时钟免疫——`-1021` 会让 REST 客户端 resync 再重试，`timestamp` 永远是场地时间——但 `/fapi/v1/income` 的 `startTime`/`endTime` 是普通查询参数，不走那条路径。主机慢 3,612 s 时循环一直在问一个一小时前的窗口：2026-09-04 操作者手动平仓后，96 行、净 +23.98 USDT 停在场地时间 07:51–07:53，而循环在查 `[06:53, 06:58]`，一行也没取到。收入没丢，是**迟到一小时**并被归到一小时之后那一轮的 `last_contributions` 上——这正是 M-010 不能容忍的错位，而 KILL-006 决定不做历史 holdout 的全部理由就是"实盘归因是唯一干净的样本外"。`venue_time_ms()` 读 `-1021` 路径已经在维护的 offset，`startup` 显式同步一次（那里 offset 为 0 不会报错，只会安静地少一小时归因）；水位线不动，因此修完第一轮是一个更宽的窗口把缺口补回来，此后场地基准、首尾相接。没有场地时钟的 venue 回落到主机时钟，时钟抛异常也不会让一轮失败。与 D-025 不冲突：**主机时钟仍是调度基准**，改的只是问交易所要数据时用谁的钟。
- **D-032** 不是本循环下的单，其盈亏不进策略序列。2026-09-04 操作者手动平掉整本书，+26.30 已实现盈亏被归给 tsmom——**经济意义上没错**（仓位是 tsmom 选的、拿的），错的是时间分布：整段持有期的浮盈被压进一根 bar，而 M-010 用逐 bar income 序列算 Sharpe，均值和方差都被带偏。`external_flows` 抓不到它：那只认 TRANSFER 行，人工平仓走的是 REALIZED_PNL。income 行只带 `tradeId` 不带任何来源信息，因此归因走一次 `/fapi/v1/userTrades` 连接：`income.tradeId → userTrades.orderId → trades.jsonl 里本循环自己的委托 id`（该端点接受不带 `symbol` 的时间窗，2026-09-04 实测一小时 68 笔全返回）。外来行进 `foreign` 段——**留在 ledger 里，因为那是真金白银**——但不进 `by_strategy` / `by_symbol` / `total`，日报单列一节。没有 `tradeId` 的行（资金费）留给本书：资金费按持仓计提，与谁开的仓无关，这里分的是"谁交易了"不是"谁在敞口里"。**对账做不了时（端点缺失或调用失败）退回原样全额归因**：一个跑不起来的监控不可以反过来把整轮盈亏静默判给别人。
- **D-033** no-trade band 每条路径只算一层，实盘那一层的参照是交易所的真实仓位。带的规则是「变化不够大就保持原样」，两半系统对「原样」的定义不同：回测里模型自己的输出**就是**仓位，所以 `apply_no_trade_band` 是仓位递推，属于 `build_weights`；实盘里仓位是交易所的，`plan_rebalance` 用同一条规则对着它再判一次——于是模型再算一遍，等于**对着一个不是本书的参照压制了两次**。更糟的是实盘那份递推是在**每周期滑动一根的请求窗口**上从头重建的，锁存点因此是窗口起点的产物：实测同一根 bar，1,442 根 vs 1,443 根让某个币的权重差 9.69e-4（占它自身 14%），200 根 bar 上模型层换手比连续路径高 20%，而证据是在连续路径上测的。`AlphaModel.targets`（实盘唯一入口）现在走 `band=False`，回测路径逐位不变；等价性有测试守着——把未加带的目标逐根喂给 `plan_rebalance`，得到的仓位路径与 `apply_no_trade_band` 逐位相同。修复后同一检验：多给一根 bar 的历史，权重变化 3.0e-9（纯 EWMA 预热残留）。D-026 的构建指纹不变，因为带确实还在跑，只是只剩一层。**这是实盘行为变化，需重启循环才生效。**
- **D-034** 一笔结算属于**包含它的那根 bar**，不属于开盘时刻与它相等的 bar。Binance 的 `fundingTime` 常落在整点后 1–47 ms，且逐年不同（BTCUSDT 2021 年 34% 正好在整点，2024 年 85%）。`funding_per_bar` 与 `Panel.from_frames` 原本按精确时间戳 reindex，于是全库 1,010,914 行结算里 **441,678 行（43.7%）被静默填成 0**：`use_actual_funding: true` 的回测少收了约一半资金费（shipped tsmom book 全样本 Sharpe 1.5809 → **1.5477**，净收益 3.5064 → 3.3575，成本占毛利 10.68% → 12.56%），而且各 fold 丢失比例不同，fold 间比较本身就不同口径；carry 与 tsmom 的 crowding modifier 则在「看起来完全正常」的情况下只拿到一半输入——这正是 KILL-027 的形状，只是低了一层。现在两处都按 bar 网格 floor 后求和（同一根 bar 内的多笔结算相加），`Panel.from_frames` 还会拒绝非 DatetimeIndex 的 funding 而不是把它填成 0。实盘路径是同一个 bug，此前因 `needs_funding=False` 未触发；旧测试全部用整点合成时间戳，所以谁都没抓到。**后果是操作者决定**：所有引用 `use_actual_funding` 的历史报告数字偏乐观，重跑证据还是逐份标注，不在本次修复范围内。
- **D-035** 风险预算是显式决策，`vol_target`（下称 k）由它反推——原则不变，两侧的数 2026-09-14 全部换过，而档位那一半的证据 2026-09-15 用上线代码重出过一次。**最初（2026-09-04，操作者声明最大回撤 50%）**：此前 0.15 是 `PortfolioParams` 的默认值，不在任何决策、预登记或 trials ledger 里，而构造实际跑在约 12% 的预算上——错配约四倍，且会原封不动带进真实资金。取值规则先写后跑：**取自助 q95 回撤仍在声明预算内的最大 k，两个 universe 都要满足** → 0.30（q95 −43.7% 时点 / −49.5% 静态，击穿概率 1.2% / 4.8%）；0.375 两边都否决。**样本内回撤不是用来定档的数**：0.15 时它读 −11.9%，而自助中位数 −16.5%，历史值落在自己分布的约第 25 百分位。**现行（2026-09-14，操作者裁定）**：判据从 Sharpe 换成**绝对收益**，回撤预算 **−70%**，k **0.60**（`96d659ae`）。P32 在 registry 实书上量了两个 universe 的 k 阶梯：CAGR 单调递增且跨 universe 同向。**这次的证据比常规弱，写在记录里而不是藏着**：P32 没有预登记，−70% 是在看到 q95 那一列之后裁定的，因此 2026-09-04 那条「取最大的、q95 在预算内的 k」**不能**用来为 0.60 背书——它只解释 0.30 是怎么来的；ledger 欠账 `--prior-trials` 95 → 152。同时撤回两件事：P26 的「argmax k = 0.15，在每个资金档」只在 pit 上成立（脚本把 universe 写死了），只撤回不替换，因为 static 那条曲线跨度只有 0.106、没有误差棒；以及「合并书有 84.2% 的免费 headroom」——事前比属实，但不转化为回撤折扣，合并书的 q95 比主书略差。**`liquidation_touches = 0` 不再是安全证据**：`starquant_alpha/backtest.py` 的 `buffer = (1 + realised − charge) / (gross × mmr)` 在 `gross ≤ 2.0`、`mmr = 0.005` 下即 `buffer ≥ 100 × (1 + r − c)`，要触到 1.0 需要单根 1h bar 亏掉约 99%——**那是一条算术，不是复核过的证据**。结论（限制的是回撤不是爆仓）不变，但它的等级是 E5 推导而非 E1 测量。真正的爆仓通道是 **RISK-2**：账户权益 52.65% 是 BTC 抵押品、回测建模的抵押品为零、且它随 k 同步放大，这套仪器看不见。k 在回测里**不含 alpha** 这一点照旧，而且那是算术性质不是发现——毛盈亏、换手成本、资金费三项全部线性于权重，所以任意缩放后净 Sharpe 精确不变。**因此它仍然只在 demo 名义下成立**：成本模型对任何下单量都收固定 7 bps，`max_participation` 根本不在回测里，真实资金前必须在含冲击的成本模型下重新推导（KILL-A）。**降档阶梯随预算重标，并与尺子一同改动（R8，`Policy.drawdown_ladder`，policy 0.3.3）**：规则本身未变（`deescalate_at` = 70% 预算、`rollback_at` = 预算、`deescalate_to` = 75% k、`rollback_to` = 50% k），在 k=0.60 / 预算 70% 下即 `((−0.49, 0.45), (−0.70, 0.30))`，取代 k=0.30 / 预算 50% 下的 −35% → 0.225、−50% → 0.15；`risk_budget:` 块是它的报告副本，两者不得分歧。**尺子同时改为计入本书未实现盈亏**（`risk_budget.attributed_drawdown_state`）：只认已实现的那把尺子让这条梯子**惰性**——2021–2026 在 k=0.60 上，盯市尺子越过旧梯第一档（−35%）785 根 bar，已实现尺子 0 根；三种浮盈入账约定（eager 785 / proportional 0 / on_close 0）夹住区间，结论不依赖约定。两半必须同时改：只修尺子等于静默采纳操作者没选的那条刹车，只重标档位等于给一把从不触发的梯子调音。排除抵押品重定价（KILL-AR-05，仍然成立）从不要求排除本书自己的持仓。**2026-09-15 用上线代码重出档位证据（`ladder_step`，两个 universe × 2000 draws）**，以下数字取代此前由 `scratchpad/p32*` 手抄重放产生的那一组：① **换成上线实现不动任何数**——`p32d` 改调 `starquant_alpha/overlays/ladder.ladder_step` 后，与旧手抄实现在历史路径上的标量**逐位相同**（`max|Δscalar| = 0`，六个臂全部）。此前记下的「那几个数出自可证明不是在跑的代码」**措辞过头**：代码确实不同（缺 `min(1.0, raw)` 钳位、除模块常量而非运行中的 base、不重放 blind-hold），但这三处在 k=0.60 的上线档位下**都不绑**（0.45/0.60 与 0.30/0.60 均 < 1；base 恰等于那个常量；回测读数永不失效），所以它们没有移动任何结论。**证据等级恢复。**② **重标代价 0.4pp、q95 −66.5% 成立**：时点 +0.41pp / −66.56%，静态 +0.43pp / −66.36%，两边都在 −70% 内。③ **「旧档位原封不动」的 20.5pp 成立并略高**：时点 **21.2pp**、静态 **20.1pp**（k=0.30/50% 预算的档位放在 k=0.60 下，盯市尺子）。④ **C-006 撤回后那笔交换重新量到**：P(破 50%) 时点 12.6% → 54.7%、静态 13.7% → 55.2%，换中位 CAGR 时点 +21.7pp、静态 +20.9pp。⑤ **两处此前没人说过的事**。其一，`rescaled` 臂已经退化：policy 0.3.3 把上线档位按 −70% 重标之后，`rescaled(0.60)` 与 `Policy().drawdown_ladder` 是同一把梯子（只差浮点噪声），所以那条臂不再携带信息，而「重标本身的代价」是一次**已经做完**的改动的代价。其二，**上线档位在历史路径上一次都没触发过**：两个 universe 的 `historical_throttled_share` 均为 0（第一档 −49%，历史盯市回撤够不到；旧档位在时点上是 7.52%）。上面所有 q95 与代价因此**全部来自比历史更深的重抽路径**，A-003 的周块 bootstrap 偏乐观照旧继承。产物：`reports/research/p32d-ladder-bootstrap-pit-20260915.json`、`reports/research/p32d-ladder-bootstrap-static-20260915.json`（各 6 行，含 `unrescaled` 臂与 `scalar_drift_vs_legacy` 列）；审查与复现：`docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md`。**这两个路径 2026-09-16 更正过**：原文写的是 `scratchpad/p32d-{pit,static}.json`，而 `.gitignore` 的 `scratchpad/*.json` 把它们挡在仓库外，于是这一整条 D-035 的档位证据在**仓库里根本不存在**，唯一副本躺在一个已合入、随时会被 `git worktree remove` 清掉的工作树里。按 `p10-portfolio-smoothing-20260904.json` 的先例入库到 `reports/research/`（治理回放只读 dict 形状的 JSON，这两份是 list，不进归因表）。**监控本身只告警不交易**：「自动、不进入复审」指的是阈值不再商量，而不是让 cron 去改实盘仓位大小。动手的是循环里的 R8（2026-09-09 起）：归因回撤越档后宽限两个周期，再把档位乘进整本书（`LiveEngine._risk_ladder`）。含抵押品重估的权益回撤只报告，不据此动作。算不出的指标一律返回 `enforced: false` 加原因，绝不读成 0。
- **D-036** 组合层护栏只有一份语义，回测重放实盘真正会做的事。`daily_loss_pause` 与 `GROSS_CAPPED` 从来不在回测里，而这在 `vol_target 0.15` 下**看不出来**：5.6 年最差 UTC 日 −3.5%，gross 从未越过 2.0，两者都不可达。0.30 让它们都可达（时点 355 个 capped bar、36 个 paused bar），不补就是在给一本实盘不会持有的书打分——KILL-027 的形状。语义因此下沉到 `starquant_alpha/overlays/exposure.py`（`clamp_book` / `hold_or_reduce`），`starquant_live/guards.py` 调同一份，`run_backtest(..., guards=)` 做因果重放：日界滚在**决策 bar** 而不是执行 bar（实盘 `_roll_day(bar_open_ms)` 如此，小时级下两者每天跨一次 UTC 午夜），且**不能向量化**，因为暂停读的是它自己正在产生的权益路径。验收是恒等性：0.15 下重放与既有权重逐位一致、护栏触发 0 次；0.30 下 OOS Sharpe 反而 +0.005。同时补上 D-026 自己漏的一半——`LiveConfig` 此前不携带 `vol_target`，改书的大小不会改变构造 digest。
- **D-037** 交易所每标的杠杆不参与本书的收益与风险，「自适应杠杆」明确**不做**；`margin_cap` 改为启动时校验的不变量。仓位由 `weight × equity` 决定；`maintMarginRatio` 按**名义档位**索引（BTCUSDT 首档 `notionalFloor 0 / cap 50000 / MMR 0.004`），与所选杠杆无关，全仓强平由维持保证金决定；L≥3 时可用保证金对 gross ≤ 2.0 从不绑定。三条合起来意味着它没有可优化的目标函数——而 legacy 的同一模块（八个标量相乘、从未验证、交易所杠杆停在 20x）正是审计判为不可移植的那个。真实缺陷在别处：`derive_leverage` 按最坏情况取值是**正确设计**（按实际 gross 推导会推出 L=1 并锁死整本书），但 `max_leverage` 的截断会静默破坏 `margin_cap`——`max_gross 3.0 / cap 0.40 / max 5` 实得 5x、初始保证金 60%、无告警。今天不可达只因 `2.0 = 5 × 0.40` 恰好相等，而 P13 把保证金峰值从 33% 推到 40%，headroom 归零。`auto` 模式下启动即校验并拒绝；`fixed` 豁免，因为那里 `margin_cap` 根本不参与（profile 自己的「was 100% at a fixed 2x」就是那个状态）。
- **D-038** D-037 是对的，但它只写在这份文档里，日报答不出它——于是同一个问题在 09-03、09-04、09-05 被问了三次：**为什么每一单都是 5x**。缺陷是可读性，不是算法：`derive_leverage` 的输出 `ceil(2.0 / 0.40) = 5` 是规格值而非上限（把 `max_leverage` 抬到 125 仍得 5），而真正按标的自适应的是 stage 1 的 `vol_target / asset_vol`，日报却只印 `last_targets`，没有任何可以对照读的量，全系统唯一可见的每标的数字就是交易所那个统一的 5x。**一个没有仪器陈述的正确事实，与未经证明无法区分**。M-015 因此不是展示而是证伪器：`compression = 风险贡献离散度 / 市场波动离散度`，实盘 2026-09-05 读 0.13（波动 12.2x 被压成风险 1.6x，即 stage 1 吸收了 87% 的离散度），而**删掉 stage 1 它收敛到 1.00**——权重不再依赖 σ，两个离散度相等。0.50 是放在这两者之间的宽界，不是推导出的阈值：无交易带会攥着一个陈旧权重而 σ 在其下漂移、`max_weight` 会在最平静的名字上绑定、带幅度的信号会把 conviction 放回分子，这三件事都会合法地把它推高。`asset_vol` 从 `starquant_alpha/portfolio.py` 提出为具名函数并经 `TargetWeights` 逐周期落盘，**因为在日报里用行情档案重算 σ 更短但回答的是另一个问题**（另一根 bar，且与构造用的半衰期无绑定）——那正是提取要防的漂移。算不出时（该周期早于 `asset_vol` 落盘、当日无周期、持仓不足 3 个）返回 `enforced: false` 加原因，与 D-035 同一条规矩：绝不读成一个看起来像通过的数。
- **D-039** `no_trade_rel_band` 保持 **0.40**，依据从 P10 索引换成当前构造下的重测；**收窄它是策略变更，不是效率调整**。P10 cell B 采纳 0.40 时，它的每一个数字都产生于 D-033（带算两层、模型层那份递推每周期滑一根从头重建，换手偏高 20%）、D-034（43.7% 的资金费结算被静默填 0）、D-035（`vol_target` 0.15）、D-036（两个组合层护栏不进回测）**四项之前**，而这四项每一项都动了这条曲线所依赖的东西——本文件当时记下的「`no_trade_rel_band 0.40` 的依据是 P10 索引，tsmom 的 `181803Z` 仍是 0.25 下的验证」因此一直开着。重测（`scratchpad/no_trade_band_sweep.py`，时点 205 币 / 49,745 bar / 5.68 年，绝对臂固定在 0.005，只动相对臂）逐项复现 0.40 对 0.25：走前 OOS Δ **+0.151**（原 +0.1418）、静态 **+0.112**（原 +0.1023）、配对 NW t **4.49**（原 4.18）、换手 **−11.3%**（原 −11.8%）——**绝对水平动了，差异没动**，因为那四项改的是这本书的收益水平而不是带的机制。D-033 同时是这次能问的前提：它证明未加带的目标逐根喂给 `plan_rebalance` 得到的仓位路径与 `apply_no_trade_band` 逐位相同，所以回测里加带的权重帧**就是**实盘仓位路径，数出来的订单就是循环会下的订单。新信息是 P10 与 R3 都只测过 0.25 / 0.40 两点、因而分辨不了的那件事：**0.50 在两个 universe 上都变差**（时点净 1.9181 → 1.8060、OOS 1.863 → 1.739；静态 MDD −22.9% → −25.4%），「继续放宽」被排除；0.02 步长加密显示 0.40 是**平滑驼峰的顶而不是尖峰**（毛 Sharpe 0.32 的 1.9556 单调升到 0.40 的 2.0556，再单调降到 0.46 的 2.0042）。收窄的代价是可买到的频率：0.40 → 0.20 让订单 4.6/天 → 8.8/天、中位持仓 57h → 27h，年化 −8.45%（时点）/ −7.50%（静态），**其中只有 6.7%–9.8% 是省下的手续费**，其余在毛收益路径上——与 D-024「edge 在方向不在幅度」同源：更宽的相对带是在组合层做同一件事，不追随波动率目标带来的幅度微调，所以收窄等于把已被否决过的幅度追随放回来。**这不构成独立验证**：0.40 本就选自这份数据，一次找到现行值最优的重跑是确认性的，驼峰平滑与两个 universe 同向只是让它更可信。证据分层**未消除**——`181803Z` 依旧是 0.25 下跑的，结掉它要在 0.40 下重跑 `validate` 并更新 registry 指针（新增 ledger 行），本条没做。成本模型仍是平的 7 bps，不含冲击与 `max_participation`，收窄同时抬高总换手与缩小单笔尺寸，**平模型下修正的符号不可预判**（与 KILL-A 同一笔债）。P10 cell B 的实盘证伪线在 P13 作废后仍然空缺，本次是事后扫描、无预登记规则，**因此不在这里补**。构造参数不进 `param_key`，按「手工补的坑」申报：时点新格子 14 个，下次 `validate` 的 `--prior-trials` 30 → 44。
- **D-040** 数据清单对资金费归档是瞎的，修法是让存储布局只写一份（2026-09-05）。`manifest.py` 按 klines 的「一符号一目录」去走资金费归档，而资金费是一符号一文件的平铺布局，于是资金费那一格恒为零，`manifest_problems` 对它永远不会告警。现在路径由 store 自己交出（`FundingStore.symbols()`、`directory`），清单不再持有布局知识。清单加印 `MANIFEST_VERSION = 2`：v1 报告里资金费的零读作「从未记录」，不读作「归档为空」。经过见 `docs/RESEARCH_LOG.md`「2026-09-05 · D-040」一节。
- **D-041** 数据清单的比对接上第一个生产调用方，严重度分级是这条的主体（2026-09-05）。`starquant_live/config.py` 的 `registry_dataset_problems` 调 `manifest_check`（`manifest_problems` 是它的不分级包装，只有测试在调），在 `live run` 启动时与日报 / 周报里，核对每条启用策略所引证据的 dataset 清单：`membership` 变了就阻断；`klines` / `funding` 只提示，因为日任务每天追加；`universe` 只在特定漂移下阻断（`_universe_drift_blocks`）；没有清单或 v1 未记录的一律只提示。2026-09-18 起 `deploy/run_live.sh` 的「D-041 bridge」给 armed 启动传 `--allow-unvalidated`，只绕开 `live_cmd.py` 的启动拒绝，2026-10-13 当天到期、自动失效。
- **D-042** 横截面算子的**参照总体是显式契约**，而不是「调用者恰好加载了哪些列」。`Panel.reference`（bars × symbols 布尔帧）只约束秩 / 去均值 / 广度这一步，**不裁面板**——裁面板更短，但会让重新入选的币在 `rolling` 上从 NaN 重新开始，而实盘总请求满历史、不会，那是用一种口径分歧换另一种。研究侧传 `eligible`（时点成员 ∩ 上市时长），实盘侧由 `AlphaModel.targets(reference_symbols=...)` 传当周期管理的 universe（不含 `leaving`：它们只被减仓，不参与排名）。此前 `apply_crowding_modifier` 在 `score.columns` 上排名、`flow` 在全部列上去均值，于是研究拿一个币对约 119 个名字排、实盘对 15–18 个排，同一份 registry 参数是两个信号（KILL-027 的形状）。实测：成员币-bar 上多头拥挤触发率 10.60%（全 panel 总体）对 17.28%（成员总体），且只有 52% 的触发 bar 重合——变的主要是「标了谁」。两份指针据此重出：tsmom `093705Z` 仍 PASS、五 fold 全选修饰器；flow `094008Z` 的四臂归因显示小书表面 +0.126 的边际里约 0.048 是这个假象（组合层判定前后都是 REJECT，D-029 不变）。
- **D-041 之后补上的一半 / DL-Q0** 每个周期与心跳记录**进程持有的** registry digest，`live status --check` 拿它与磁盘上的文件比对。引擎只在启动时建模、不热重载，所以改 registry 改的是文件说什么而不是循环跑什么——这个缺口开了 93 个周期（循环 2026-09-04T17:21Z 启动，`crowding_window` 0→72 的提交 20:03Z，进程一直跑 0，96 个周期的 `inputs.funding_history` 全 false），而 D-026 的构造指纹只覆盖组合层、启动证据门在改动之前就跑完、`live verify` 用的是它本该检查的那份文件。现在文件领先于进程时 `--check` 非零退出并说明「下一次重启会静默改变所交易的东西」。2026-09-06T10:19Z 的有意重启是这两条的落地点，证据窗口从那里重新开始。
- **D-043** 从未做过选择的证据封顶 WEAK_PASS，不判 FAIL（2026-09-17，`86a9f673`）。两种形状：`oos_is_full_sample_tail` 为真，即没有哪个 fold 有得选，样本外只是一条全样本序列的尾巴；或网格不到 4 格时 PBO 被豁免，那是门没跑，不是门过了。封顶而不判 FAIL，是因为 WEAK_PASS 仍可上线（`starquant_alpha/registry.py`），规则能把话说清楚，又不必停掉正在持仓的循环。落地前在 60 份归档报告上量过：10 份 PASS → WEAK_PASS，全是 tsmom，无一变 FAIL，逐个钉在 `D043_CAPPED`。**撞号**：`docs/RESEARCH_LOG.md` 2026-09-06「D-043 / M-019」一节的 D-043 指选择门从期望最大值改为分位（KILL-Q3，见 D-028），不是本条；代码与测试里的 D-043 都指本条。
- **D-044** 归因按带符号的净敞口份额分（2026-09-17，`86a9f673`）。E-050 当初用 \|贡献\| 挡住有符号分母趋零，副作用是同一个币里每个策略都拿到该币盈亏的符号，与自己站哪边无关。2026-09-17 实测 flow 与 tsmom 重叠的三个币方向全部相反，而 flow 的 30 天 P&L 止损读的正是这个数。现在 `strategy_shares` 以净敞口作分母、分子保留符号。净敞口不到毛敞口的 `MIN_NET_SHARE`（0.10）时该币无主：收入记进 `unattributed`，并按币单列在 `cancelled` 里。新行带 `basis: net_exposure`，改口径之前写下的旧行不改写；探针的 30 天窗口只累加同口径的行，并报出 `stale_basis_rows`。见 D-021。
- **D-045** 这个号用过两次，两件事都在代码里：
  - **退出侧**（2026-09-17，`c884f4d5`，`starquant_live/exits.py`）：场地没执行成的退出不再被当成新入场。回测里规则一触发就丢锚是对的，weight 0 的下一根就是空仓；实盘的平仓单可能落不下去（`BAND_BLOCKS_EXIT`、`minNotional`、场地拒单）。此前下一周期会按当根 bar 的 σ 重建 `unit`，波动一升，止损就被放松。现在靠 `cooldown_direction` / `cooldown_until` 记住规则在哪一侧触发、管多久，不加字段。
  - **基准侧**（2026-09-19，`ffd81df1`，`starquant_live/benchmark.py`、`starquant report beta`）：把实盘收益拆成市场与信号两部分。四条规矩各来自一次读错：基准必须是时点篮子；t 用 Newey-West；β 按每根 bar 实际带的敞口条件化，不当常数；信号全同向的区间不谈 alpha（`signal_state`）。只测量，不判定、不改任何东西。
- **D-046** 单币上限 `max_weight` 是否绑定，从「列为原因」改为「读出来」（2026-09-17，`58e12cd2`）。`report daily` 直接读 `cycles.jsonl` 的 `book_weights`（2026-09-12 起就在记），数有多少周期至少一个名字被截在上限、各是谁。出现过 `GROSS_CAPPED` 的窗口里这个数是下界，日报会自己标明。它同时更正了 2026-09-14 的「只截 BTCUSDT」：BNBUSDT 也被截过（`config/live.demo.yaml` 的 `vol_target` 注释）。
- **D-047** 报告与证据不出图（2026-09-25，操作者裁定）。外部清单 2.10 要回测代码「附示例数据和可视化」。09-23 的清点判「部分」：代码与样例数据都有，没有图，也没有「不做图」的决定。现在有了。理由三条：
  - 仓库的证据标准是每个数字带出处，能 grep、能 diff、能逐位复算，图做不到这三样。#107 与 #108 把 29 处「打乱未来」的比较改成逐位，起因就是默认容差放过了 1e-9 的前视；这种差在图上看不出来。
  - 仓库是公开的。图片进了 git 就收不回，还会和生成它的代码漂移，每次更正都要改两遍。
  - 操作者读日报、收告警，走的都是文字：Markdown 日报与 webhook。
  管的范围是进 `reports/` 与 `docs/` 的产物，以及被当作证据引用的东西。研究时在 scratchpad 里临时画图照常可以，只是图不入库、不当证据引用。`matplotlib` 留在可选的 `research` extra 里（`pyproject.toml`），CI 不装，没有模块 import 它。
