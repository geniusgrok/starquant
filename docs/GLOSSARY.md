# 术语表

这份词表定的是**怎么写**，不是概念本身是什么意思。概念的定义在 `CONTEXT.md`，实现决策在 `docs/ARCHITECTURE.md`，判定过程在 `docs/RESEARCH_LOG.md`。

## 判据

1. 这个概念在仓库里有对应标识符（`grep` 得到 `ledger`、`overlay`、`holdout`……），且现有中文写法是临时译的 → **写英文原形**。
2. 中文量化写作里本来就这么说（回撤、夏普、敞口、再平衡） → **写中文**。
3. 两条都不沾 → 写英文，并把结果补进本表。

不要为了避免中英混排而发明新中文词。混排可以接受，两套写法并存不行。

## 写英文

| 写这个 | 不要再写 | 代码里的标识符 |
| --- | --- | --- |
| holdout | 留出、留出集、留出期 | `holdout` |
| fold | 折、折号、折级、逐折、负折 | `n_folds`、`min_train` |
| ledger | 账本 | `ledger` |
| trials ledger | 试验账本 | `ledger` |
| ratchet | 棘轮 | `ratchet` |
| source budget ratchet | 行数棘轮 | `ratchet` |
| incumbent | 在位者 | `incumbent` |
| headroom | 余量 | `headroom` |
| exit overlay | 退出层、退出叠加层 | `overlay` |
| overlay | 叠加层 | `overlay` |
| sleeve | 分仓、袖子 | `sleeve` |
| universe | 标的池、宇宙 | `universe` |
| throttle | 节流阀 | `drawdown_throttle` |
| family gate | 家族门 | `family_gate` |
| ceiling | 天花板 | `ceiling` |
| alert | 呼叫（名词用法） | `alerts` |
| regime | 行情状态 | `regime_split_sharpes`、`regime_window` |
| beta | 贝塔 | `rolling_beta`、`starquant report beta` |
| VaR、ES | 在险价值、预期损失 | `BACKTEST_DAILY_VAR`、`BACKTEST_DAILY_ES`、`tail_readings`（2026-09-23 起） |
| effective number of bets、effective bets | 有效押注数、有效赌注数 | `report_risk.effective_bets`（2026-09-25 起） |
| cutoff | 截断点 | `_shuffle_future` 的 `cutoff` |
| bar sanity | 数值合理性检查、价格合理性检查 | `starquant_live/bar_sanity.py`、`cycles.jsonl` 的 `bar_sanity` |
| frozen bar | 冻结 bar（与「构造冻结」撞词）、死 bar | `bar_sanity` 的 `frozen` |
| probe | 探针、探针书 | `probe`、`PROBE_VERDICT`、`max_concurrent_probes`（2026-09-25 起） |
| bridge（D-041 bridge） | 桥 | `deploy/run_live.sh` 的 `BRIDGE_UNTIL`（2026-09-25 起） |
| exemption（`tests/shipped_evidence.py` 那一条） | 豁免（指这条机制时） | `EXEMPTED`、`EXEMPT_UNTIL`（2026-09-25 起） |
| confirmed gap | 已确认缺口、真缺口 | `confirmed_gaps.json`、`starquant_data/repair.py`（2026-09-25 起） |
| feature store | 特征库、特征存储、特征缓存 | `starquant_cli/research_feature_store.py`、`STARQUANT_FEATURE_STORE`（2026-09-25 起） |

## 保留中文的近形词

这些字面上像术语，其实是正常中文，不要替换：折算、折扣、打折、折现、折减、折叠、折成、折进。`exempt_crossings`、`exempt_reductions` 说明里的「豁免」是动词，照写中文——只有指 `tests/shipped_evidence.py` 那条机制时才写 `exemption`。「呼叫操作者」「BLIND 不呼叫」里的`呼叫`是动词，也保留——只有指 `alerts` 里那条记录时才写 `alert`。

## 写中文

这些词有现成的中文说法，不要改成英文：回撤、最大回撤、夏普、杠杆、敞口、毛敞口、净敞口、再平衡、再平衡带、止盈、止损、移动止损、样本外、样本内、置信区间、风险预算、风险预算阶梯、换手、滑点、成交、权益、波动率、逆波动率定价、基准、三分位、前视、逐位、阴性对照、跳变、重新计价、保本成本倍数。

执行成本这一族也写中文：跳空、价差、冲击、参与率、手续费（2026-09-25，日报的 per-order TCA 一节）。
`TCA` 写英文，它在代码里是 `per_order_tca`。`价差`只指买卖价差。demo 成交价与主网价格之间的差写
**主网与 demo 的价格差**，不写价差：两者同在 TCA 的成交段里（2026-09-25）。

`载荷`（因子载荷）、`低波`、`共线性`写中文，出处是 `starquant_live/factor_loadings.py`（2026-09-25）。
旧文里「载荷」还指 digest 的 payload，那是另一个意思，旧文不改。因子名 `size` 写英文：它按 30 天
成交额排名，不是市值，写成「规模」「市值因子」会被读成市值。

`重放`（replay，把一段历史重新跑一遍）写中文，不写「回放」。两种写法在仓库里并存，前者多：2026-09-23
在 `docs/RESEARCH_LOG.md` 里数到 61 对 21。旧文不改。

`完全平仓`、`纯减仓`写中文。「每个币分别」写**按币**，不写「逐仓」：币安中文界面里「逐仓」指逐仓保证金，
与全仓相对。2026-09-25 加日报的平仓流动性一节时定下。`参与率` 在代码里是 `max_participation`，`冲击`
是 `ImpactModel`，两个词的写法见上面执行成本那一行。

`事件风险`、`脱锚`、`交易所事故`、`极端行情`、`插针`写中文（2026-09-25，日报的 #8.10 一节）。代码里是
`report_events.event_risk`、`stablecoin_peg`、`venue_incidents`、`market_extremes`。`CONTEXT.md` 把 venue
写作「场地」，指下单去的 demo 端点；这一节读的是循环去两个 host 的整条路径（行情走 fapi，下单走 demo-fapi），
分不出是哪一边，所以写**交易所事故**，不写场地事故。`插针`指一根 bar 的最高价或最低价远离收盘价。

`书级` / `仓位级`这对说法改成**组合层** / **仓位层**——两个都是通用中文，不必用 `book-level`。

`预期书`是自造词，`expectation book` 也是自造的英文，两个都不用。写**预期说明**。

`实盘失效方式`（How this fails，预登记模板第 9 项，2026-09-25 起）写中文。英文原名只在第 9 项的标题里当出处注，
正文不写。审查报告里的`失效场景`照旧写：它是 backtest-guard 的字段，不拿来称呼第 9 项。

`诚实漂移`、`原漂移`写中文（2026-09-25，k 的重测）。诚实漂移：回测净收益序列的每根 bar 减同一个常数，
使年化 Sharpe 等于诚实的选择程序交付的样本外读数（当天是 1.2306），波动与自相关不动。原漂移是不减的
那条。出处是 #146 体检的「诚实 OOS」；代码里是 `drift` 字段的 `"honest"` / `"orig"`
（`scratchpad/k_remeasure_honest_drift_20260925.py`）。

`缺口`写中文，指存储里两根相邻 bar（或两次相邻结算）之间少掉的那段，代码里是 `KlineStore.gaps`。
向源头问过、源头也没有、记进 `confirmed_gaps.json` 的那种写 **confirmed gap**，不写「已确认缺口」
「真缺口」（2026-09-25，`starquant data repair`）。旧文里的「真缺口」不改。

## 没定的怎么办

写英文原形，然后在同一个提交里把它加进上面的表。不要留着两种写法等以后统一。
