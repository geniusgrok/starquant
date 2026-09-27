# 用 backtest-expert 那把尺子量StarQuant（2026-09-14）

外部 skill `backtest-expert` 的方法论对现有证据做一次对照评分。**没有跑任何新回测**，
理由写在 §0；本文不改任何配置、不动 ledger，`reports/research/trials.jsonl` 跑前跑后未动。

## 0 · 这次跑了什么，以及为什么没跑参数扫描

跑了的：

| 动作 | 结果 |
| --- | --- |
| `pytest`（全量，无额外 `-q`） | **1962 passed**，exit 0，130.4s（上限 400s） |
| `starquant report daily` | 见 §4 |
| `starquant live soak` | **L3 判据 FAIL**（no-decision + 连段；ERROR 连段本身 PASS，最长 1 < 3） |
| 读 `reports/research/tsmom-validation-20260913T182325Z.json` | §2 全部数字的出处 |
| 读 `.starquant/live/{cycles,trades,attribution}.jsonl` | §4 全部数字的出处 |

**初版没跑参数扫描，这是有意的**（O-3 已按操作者「顺序执行」的裁定跑了，见文末）。
`starquant_cli/research_cmd.py:511` 里 `research backtest` 会调 `_record_trial`
（`research_cmd.py:2320`），只在签名已在 ledger 里时才不计费。

**更正（初版的理由是错的）：** 初版写「今天的数据指纹已经动过，所以任何重跑都是新签名」。
签名里**没有数据指纹**——`TrialRecord.signature`（`starquant_alpha/validation/ledger.py:127`）是
`(param_key, range_start, range_end, symbols, construction_digest, overlay_digest, symbol_set_hash,
search_space_version)` 八元组。让重跑变成新试验的是 **`range_end` 随数据增长而右移**，不是指纹。
结论（重跑要计费）不变，理由换掉。**把 `--to` 钉住就能免费重跑同一份证据**，这是初版漏掉的一条。

## 1 · skill 自己的评分：53/100 与 50/100，两次都是 Refine

`scripts/evaluate_backtest.py` 跑了两遍，只差回撤那一栏：

| 维度 | A（in-sample MDD 40.29%） | B（bootstrap q95 MDD 68.8%） | 满分 |
| --- | ---: | ---: | ---: |
| Sample Size | 20 | 20 | 20 |
| Expectancy | 5 | 5 | 20 |
| Risk Management | **3** | **0** | 20 |
| Robustness | 5 | 5 | 20 |
| Execution Realism | **20** | **20** | 20 |
| **合计** | **53 → Refine** | **50 → Refine** | 100 |

红旗：A 一条（`over_optimized`，中）；B 两条（多一条 `excessive_drawdown`，高）。

**入参的出处必须分清，因为有两个是推的不是量的。**

| 入参 | 值 | 出处 |
| --- | ---: | --- |
| `total_trades` | 49240 | `.range.bars`（bar 口径——报告里 Sharpe / hit_rate / MDD 全在这个口径上） |
| `win_rate` | 51.24 | `.full_sample.hit_rate = 0.512409` |
| `avg_win_pct` | 0.4870 | **推的**，见下 |
| `avg_loss_pct` | 0.4894 | **推的**，见下 |
| `max_drawdown_pct` | 40.29 / 68.8 | `.full_sample.max_drawdown = -0.402878` ／ `config/live.demo.yaml` P32 表 k=0.60 pit q95 |
| `years_tested` | 5 | `.range` 2021-01-31 → 2026-09-13 = 5.62 年（脚本取整） |
| `num_parameters` | 8 | 保守下界，真实计数见 §3.5 |
| `slippage_tested` | true | `.slippage_stress` / `.cost_stress` |

推 `avg_win/avg_loss` 的算法：由 `.full_sample.net_return = 85.6414`、`.full_sample.annualized_sharpe
= 1.6725`、`hit_rate = 0.5124` 三个量出来的数反解每 bar 的 μ 与 σ（μ ≈ μ_log + σ²/2，
μ/σ = Sharpe/√8760），再按半正态 E|r| = σ√(2/π) 拆成盈亏两侧。自检：反解出的年化波动 **57.26%**，
与 `.portfolio.vol_target = 0.6` 相合，所以反解没跑偏。但**这仍是推的**——报告不落盘逐 bar 收益序列，
要量真值就得重跑（§6）。Expectancy 那 5 分和 PF 1.05 都建在这两个推数上，**不要单独引用**。

**这把尺子的口径限制要一起说：** 脚本的 expectancy 档位（0.5% / 1.5% 每笔）是给离散摆动交易定的，
而StarQuant是连续权重的 vol-target 组合，每 bar 期望 0.011%。**Expectancy 的 5 分是口径不匹配，不是发现。**
真正有信息量的是另外三格：Risk Management 3 分 / 0 分、Robustness 5 分、Execution Realism 满分。

## 2 · 满分的那一格，值得单独说

`backtest-expert` 里"Execution Realism"和"Punish the strategy"是全文最强调的一节，而这一格StarQuant拿满分，
是真拿的，不是尺子松：

| 施加的摩擦 | 读数 | 出处 |
| --- | --- | --- |
| 成本 ×1 / ×1.5 / ×2 | 1.6725 / 1.6138 / **1.5550**（−7.0%） | `.cost_stress` |
| 滑点 2 / 5.5 / 9.2 bp | 1.6725 / 1.6138 / **1.5516** | `.slippage_stress` |
| 执行语义换成 close_to_close | **1.6560**（−1.0%） | `.execution_comparison.annualized_sharpe` |
| 组合守卫在回测里重放 | `gross_capped_bars` 4070、`daily_loss_pause_bars` 491、`liquidation_touches` 0 | `.full_sample.guards` |
| 时点 universe（每日重选） | `.universe_mode = "pit"`、205 币、`.dataset.membership.refreshes` | 幸存者偏差已处理 |
| CPCV 15 条路径 | q05 **1.1850**，`fraction_negative` **0.0** | `.cpcv` |

skill 说 "Strategies that survive pessimistic assumptions often outperform in live trading"——成本翻倍只掉
7%、滑点 4.6 倍只掉 7.2%，**这条边不是成本假设撑起来的**。这是本次评估里最扎实的一条正面结论。

## 3 · 这把尺子挑出来的五条

### 3.1 判决取决于用哪个试验分母，而两个分母给相反的答案

同一份报告里并排放着两道同形状的门：

| 门 | n_trials | 阈值 | OOS 1.5919 | p_family | 判 |
| --- | ---: | ---: | ---: | ---: | --- |
| `.oos_selection`（策略域） | 242 | 1.5493 | **+0.0426** | 0.0348 | PASS |
| `.oos_selection_whole_library` | 2914 | 1.8184 | **−0.2265** | 0.3473 | FAIL |

242 = `ledger_trials` 88 + `prior_trials` 152 + `grid_trials` 2。 ledger 行数另报：
`.ledger.ledger_rows` **116** 行 / `ledger_trials` **88** 个不同签名 / `duplicate_rows` 28
（两个口径按 `analysis-calibration.md` 第三行的规矩分开报）。

PASS 那一侧的 headroom 是 **阈值的 2.7%**。同一份报告里 `.multiple_testing.dsr_p_value = 0.5788`，且
`expected_max_sharpe_annual 1.7562 > candidate 1.6725`——**在 242 次试验的零假设下，纯噪声的最好那个
预期比它还高。** D-020 已裁定 DSR 是 reported-not-veto、判决以样本外为主，这条裁决本身不在本文的
质疑范围；本文只报一件事：**在这把外部尺子上，"过拟合"这一格的证据是 mixed，而不是 clean。**

`.multiple_testing.pbo = 0.2082`、`degradation_slope = −0.9901`——两者都在 `grid_trials = 2` 上算出来，
按仓库自己的约定属 informational，**这里也照此处理，不当发现用**。

### 3.2 回撤：in-sample 40.3%，bootstrap q95 68.8%，P(击穿 −50%) ≈ 53%

`config/live.demo.yaml` 里 P32 自己的表（k 网格，registry book，两个 universe）：

| k | CAGR pit/static | q95 MDD pit/static | P(breach −50%) |
| ---: | --- | --- | --- |
| 0.30 | 77.3% / 56.7% | −44.1% / −50.3% | 1.2% / 5.3% |
| **0.60（在跑）** | **126.5% / 119.1%** | **−68.8% / −69.7%** | **53.4% / 58.6%** |

脚本对 ≥50% 的回撤直接把 Risk Management 判 0 并挂高危红旗，这是 §1 的 B 行。

**三条限定，仓库自己都已写下，本文只是把它们放在同一句话里：**

1. 「q95 −69.9% 距 −70% 预算还有 0.13pp」这个说法已被仓库自己撤回——同一条序列同 seed 重抽两次
   就差 1.03pp，headroom 比估计量自身的复现性小约 8 倍。已接受的措辞是「P(>50% 回撤) 大约是抛硬币，
   −70% 是声明的胃口，不是界」。
2. **P32 没有预登记。** 网格与读法写在会话转录里、未提交、无 RESEARCH_LOG 条目；而且
   **−70% 的预算是在 q95 那一列已经可见之后才声明的**。所以"取 q95 落在预算内的最大 k"
   **不是**一条预登记的选择规则，配置里已明写不得如此引用。
   按 `backtest-expert` 的说法，这正是 "Separate idea generation from validation" 那一节的形状。
3. 因此 §1 的 A 行（40.29%）是**乐观读数**：它是 in-sample 实现值。配置里自己写着
   「In-sample drawdown is NOT the number to size on」。**B 行才是该引用的那一行。**

### 3.3 刹车的盲区——**这一节初版是错的，缺陷已在同一天修掉，见 O-1**

> **更正。** 初版写「R8 的尺子是 `base + cumsum(已实现归因盈亏)`，对未实现盲，且尚未测量」，
> 依据是 `config/live.demo.yaml` 里那段 NOT YET MEASURED。**那段是同一天早些时候的历史记录，
> 两小时后就被 `221236d4` 取代了**：尺子已收进未实现盈亏（`risk_budget.py` 的
> `marked = path + carried`），档位也按 −70% 预算重标为 −49%→0.45 / −70%→0.30
> （`starquant_governance/policy.py:209` 是执行的那份，`risk_budget.py:38` 是报告副本，两者一致）。
> 我引用了一段配置注释而没有核对代码——正是 `analysis-calibration.md` 第三行记的那种读法错误。
> 下面保留初版的实盘数字（它们是量出来的、仍然成立），但**结论以 O-1 为准**。

初版据此给出的实盘量级（数字本身仍成立，见 §4）：

| | USDT | 占起始权益 |
| --- | ---: | ---: |
| 已实现归因盈亏（刹车看见的） | **−161.72** | −1.508% |
| 当前未实现（刹车看不见的） | +63.30 | +0.590% |
| 账户权益变化（操作者看见的） | **+122.09** | **+1.139%** |

三个数指向三个不同的方向。**这条缺陷已修**（见上方更正与 O-1）；本节剩下的价值只有实盘量级，
以及一条仍然成立的提醒：账户权益与书的盈亏在同一段窗口里可以反向。

### 3.4 "实盘期就是 holdout"——但这个 holdout 只有 19 小时，不是 11 天

`.holdout = null`，报告自己写「months 0；no tail reserved: every bar was available to this run」，
`.range.end` 是 2026-09-13，也就是**前一天**。KILL-006 的立场是实盘期即 holdout，这在逻辑上自洽。
问题在实盘期本身：

`.starquant/live/cycles.jsonl` 的 `construction` 字段，**11 天 armed 里换了 10 次**：

```
2026-09-04T04:21Z df6c7e329db0        2026-09-07T16:00Z c0e5c49c5a4a
2026-09-04T06:46Z a53eecccef38        2026-09-08T20:00Z dd32720d3faf   <- 最长的一段，4.7 天
2026-09-04T14:50Z 0dcd044d0158        2026-09-13T12:00Z 18b8b20fb627   gross 0.567
2026-09-04T15:00Z a53eecccef38        2026-09-13T19:00Z 46b8d731530a   gross 1.153  <- 在跑的
2026-09-04T15:02Z 0dcd044d0158
2026-09-07T15:00Z b441ea62d021
```

**当前构造从 2026-09-13T19:00:25Z 起才在跑，到测量时 19.0 小时。** 前 10.5 天的实盘记录是在
gross ≈ 0.53 的书上产生的，现在这本书 gross ≈ 1.19（BTCUSDT 权重精确卡在 `max_weight = 0.15`，
与配置里"k=0.60 下 max_weight 开始绑定、且只绑 BTCUSDT"的声明相符）。

按 `backtest-expert` 的样本量要求（最低 30 笔、偏好 100+），这个 holdout**不是小，是没有**。
而且它不会靠等变大——每次改构造都把它清零。

### 3.5 参数：`entry_threshold` 是峰不是台，而且 14 个信号参数里只有 3 个被扰动过

`.stability.parameter_neighborhood`：

| 参数 | down | base | up | 形状 |
| --- | ---: | ---: | ---: | --- |
| `entry_threshold` | 1.5680 | **1.6725** | 1.5585 | **峰**——两侧各低 0.10 / 0.11 |
| `return_scale` | 1.6345 | 1.6725 | 1.6748 | 台 |
| `vol_window` | 1.6725 | 1.6725 | 1.6725 | 平（E-043 已量为惰性） |

扰动幅度是 `perturb_pct = 0.10`（`starquant_alpha/validation/stability.py:22`），
所以 down/up 是 **0.18 / 0.22**，不是初版暗示的 ±0.05——峰比初版写的更尖。
`worst_degradation` 0.0681。**这一节的"峰"措辞已被 O-3 的五点扫描打折，见文末。** 覆盖率那条不变：
`.best_params` 有 14 项，这里只扰动了 3 项，其中 1 项已知惰性——**真正被检验过邻域的是 2 个参数**。

`num_parameters = 8` 是我填给脚本的保守下界。实际可调常数：信号层 14（`.best_params`）+
组合层 15（`.portfolio`）+ exit overlay 13（`.exits`）+ 守卫 3（`.book_guards`）。脚本对 ≥8 直接给 0 分
并挂 `over_optimized`。反方论证是成立的（多数是预登记/已裁定/已量惰性的），但**计数就是计数**，
而被扰动过的只有 2 个。

### 3.6 附带：回测不收市场冲击，所以它不含任何容量陈述

`.impact_model = {"capital": 0.0, "coefficient": 1.0, ...}` —— `capital = 0` 意味着冲击项恒等于零。
成本模型是 `.costs = {"turnover_bps": 7.0, "use_funding": true}` 的平坦费率加资金费。
在 10.8k USDT 上这是对的近似；**它同时意味着这份证据对"这条边能装多少钱"一个字都没说**。
（仓库另有 `scratchpad/participation_capacity_sweep.py`，不在本报告引用的这份证据里。）

## 4 · 实盘 11 天：三个方向不同的数

armed 区间 2026-09-03T07:59:36Z → 2026-09-14T14:00:18Z，**11.25 天 / 291 个 armed 周期 / 202 笔 FILLED**。

| 量 | 值 | 出处 |
| --- | ---: | --- |
| 权益 | 10721.77 → 10843.86 = **+1.139%** | `cycles.jsonl` `.equity` |
| 权益路径峰谷 | −4.254% | 同上 |
| **已实现归因盈亏累计** | **−161.72 USDT = −1.508%** | `attribution.jsonl` `.total` 累加 |
| 　按策略 | tsmom **−163.66** ／ flow +1.99 | `.by_strategy` |
| 当前未实现 | +63.30 | `cycles.jsonl` 末行 `.unrealized` |
| 抵押品 | 5688.14，**占权益 52.45%** | 末行 `.collateral` |
| 已实现事件 | 74 笔；胜率 **37.8%**；均盈 +5.53 / 均亏 −6.21 USDT | `attribution.jsonl` `REALIZED_PNL` |
| 佣金 / 资金费 | **−30.70** / −0.47 | 同上（全区间；按收入类型拆分见下） |

归因总额按收入类型闭合（`attribution.jsonl` 全部 48 行）：
`REALIZED_PNL −130.55` + `COMMISSION −30.70` + `FUNDING_FEE −0.47` = **−161.72**，`unattributed` −0.04。
**佣金占了已实现亏损的 19%**——在 11 天 202 笔成交上，这是成本，不是信号。

**+1.139% 不是这本书赚的。** 书（已实现 −161.72 + 未实现 +63.30 ≈ −98）是亏的，账户是赚的，
差额来自 BTC 抵押品重定价。`starquant report daily` 的 RISK-G11 监控在它自己的 166 周期窗口上读
`account_misleads: no`（那段窗口里两者同向）；**在整个 armed 区间上两者反向**——
这是窗口依赖的读数，不是监控报错，但操作者看权益曲线时要知道这一点。

**统计功效：** 这 11 天绝大部分跑在 k=0.30 上（实测权益路径年化波动 **24.81%**，与 k≈0.30 相合；
k=0.60 只占最后 19 小时）。按 Sharpe 1.67、波动 24.8%，11.25 天（0.0308 年）的期望收益是 **+1.28%**，
1σ 带宽 **±4.35%**。**实测的任何数——权益 +1.1% 也好、归因 −1.5% 也好——都落在 ±1σ 里，
一条都不构成证据。** 再叠加 §3.4 的构造 19 小时，这个 holdout 对任何判断都不可用。

胜率 37.8% 那个数**不要直接读成"这策略胜率低"**：动量书靠止损兑现亏损、让盈利以未实现挂着，
已实现事件是一个有偏子样本。它能说明的只有一件事——`avg_win 5.53 < avg_loss 6.21` 且胜率 37.8%，
这个组合在已实现侧是负期望（−130.55 USDT），而这正是刹车读到的那一侧（§3.3）。

## 5 · 判决

**Refine，不是 Deploy，也远不是 Abandon。**

`backtest-expert` 的判据是"在悲观假设下还活着吗"。分三段答：

* **成本与执行假设：活着，而且 headroom 很大。** §2。这一格StarQuant做得比这把尺子要求的更多。
* **多重检验与参数：mixed。** §3.1 的两个分母给相反答案，headroom 2.7%；§3.5 有 2 个参数被检验过邻域，
  其中一个是峰形。这不是"发现了过拟合"，是"排除不了"。
* **风险预算：这是当前最该看的一格，而且它 19 小时前才变过。** §3.2 的 P(击穿 −50%) ≈ 53%
  是仓库自己算的、操作者自己接受的措辞；本文唯一的补充是 §3.3 —— **刹车量的那个量，
  在这本书上与操作者看的权益曲线可以差 2.6pp，且它对未实现亏损盲。**
  「刹车比胃口紧」这条设计是对的；它成立的前提是刹车真会响，而那个前提未测。

**最该修的一条，也是唯一一条我认为在跑新实验之前就该修的：**
§3.3 的 `attributed_drawdown_state` 对未实现盈亏盲——配置里已标 NOT YET MEASURED，
而 §4 给出了它在实盘上的量级（2.6pp / 11 天）。在 k=0.60 下，刹车晚响的代价按 §3.2 的表是几十个百分点。

## 6 · 定价（带价钱的选项，不是开放问题）

| 选项 | 机时 | ledger 代价 | 买到什么 |
| --- | --- | --- | --- |
| **O-1** 量 R8 尺子的盲区：同一实盘窗口上并排跑 income-row attributed drawdown 与 mark-to-market，给出两者的差与滞后 bar 数 | ~10 分钟（纯重放，不建模） | **0**（描述性实盘重放，`starquant_governance/replay.py:87` 的裁决：窗口 ≤100 bar、不用于选择参数的不计入） | §3.3 / §5 那条"未测的前提"变成量出来的数。**推荐先做这条** |
| **O-2** 落盘逐 bar 净收益序列，把 §1 的 `avg_win/avg_loss` 从推的换成量的 | ~45 分钟 | **0**（只加落盘，不新增配置签名） | §1 的 Expectancy 那一格与 PF 1.05 变成可引用的数 |
| **O-3** `entry_threshold` 的台/峰：在 0.2 附近做 5 点扫描 | ~45 分钟 × 5 | **+5 笔试验** → `oos_selection.n_trials` 242 → 247，阈值 1.5493 → 约 1.554，而当前 headroom 只有 0.0426 | 把 §3.5 的峰形定性。**代价方向对被测者不利，建议不做，或与 O-4 一起做** |
| **O-4** 把 holdout 重新买回来：冻结构造 N 天不动 | 0 机时 | 0 | §3.4。**唯一能把 holdout 变大的办法，且它只要求不做事** |

O-1 与 O-2 都是零 ledger，可以直接做。O-3 建议不做——它抬高的正是 §3.1 里 headroom 只有 2.7% 的那道门。
O-4 不需要机时，只需要一条裁定：**当前构造 `46b8d731530a` 冻结到哪天。**

## 附

评分脚本产物（未入库，在 scratchpad）：`eval_A/backtest_eval_2026-09-14_222316.{json,md}`、
`eval_B/backtest_eval_2026-09-14_222324.{json,md}`。

---

# 顺序执行 O-1 … O-4（2026-09-14，操作者裁定「顺序执行」）

## O-3 预登记（写在跑之前）

`.stability.parameter_neighborhood` 用的是 `perturb_pct = 0.10`
（`starquant_alpha/validation/stability.py:22`），所以既有的 down/up 是 **0.18 / 0.22**，不是 ±0.05。
本次扫描取 **0.16 / 0.18 / 0.20 / 0.22 / 0.24**，把 0.18 与 0.22 包进网格当自检：
它们必须复现 1.5680 / 1.5585，否则本节读数作废。

**C-O3**：`entry_threshold = 0.20` 是窄峰——在最近的网格步上，两侧全样本 Sharpe 各跌 > 0.05。

**Falsifier**：5 个点里有 ≥3 个连续点落在基准 ±0.05 内，则是台不是峰，C-O3 **REFUTED**。

**判读表（写死在跑之前）**

| 结果 | 判读 | 动作 |
| --- | --- | --- |
| 两侧单调下跌，且 0.16 / 0.24 比 0.18 / 0.22 更低 | 真峰，`backtest-expert` 的 "narrow optima" 形状成立 | 记录；**不改参数** |
| 两侧下跌但外侧回升（脊/噪声） | 邻域读数是局部噪声，不是峰 | 记录；邻域检查的信息量要打折 |
| ≥3 个连续点在 ±0.05 内 | **REFUTED**，是台 | 撤回本报告 §3.5 的"峰"措辞 |

**三条先声明**

1. **本次测量不授权改 `entry_threshold`。** 采纳是另一次裁定，且会带选择污染。
2. **ledger 代价已先算**：n_trials 242 → 247，D-028 门 1.549343 → 1.551723，对 OOS 1.5919 的 headroom
   +0.042575 → **+0.040195**。门要到 **n = 351** 才首次越过 OOS（还有 108 笔 headroom），
   所以这 5 笔吃掉的是 headroom 的 5.6%，不是"用光"。**本报告初版说"headroom 只有 0.0426 所以建议不做"，
   那句话把 headroom 和翻转点混为一谈，是错的。**
3. 跑的是 `research validate`（不是 `research backtest`）：只有前者过 exit overlay
   （`research_cmd.py:846` 的 `_overlaid`），而既有的 1.6725 / 1.5680 / 1.5585 是过了 exit overlay 的数。
   走 `research backtest` 会量到另一本书。

## O-1 结果 · 刹车的盲区已经修掉了，而且尺子换了方向；剩下的问题是覆盖率

**ledger 代价 0**（纯读盘）。脚本 `scratchpad/o1_r8_ruler_vs_mtm.py`，调的是仓库自己的
`attributed_drawdown_state` / `drawdown_state`，不是重新实现。

### 三把尺子在同一段实盘记录上的读数

| 尺子 | 当前（峰下距离） | 该路径上的最深 |
| --- | ---: | ---: |
| R8 在跑的那把（`attributed_pnl+unrealized`） | **−0.958%** | **−3.069%** |
| 同函数、把 `unrealized` 抹掉（旧尺子） | −1.549% | −1.549% |
| 账户权益（`drawdown_state`） | — | −4.254% |

`enforced: true`，`action: None`，`base` 10704.55，`baseline_at` 2026-09-04T17:21:43Z（那一根
`rebaselined`），`bars` 239 / 291，`equity_over_peak` **1.0123**（分母漂移 1.23%，鸣响比书自身的
移动早 1.2%；代码只报不用）。

### 两条读数，方向相反，都要一起说

1. **当前值上，新尺子读得更浅**（−0.958% vs −1.549%）：这 17 小时里未实现是 +63.30，把已实现亏损抵掉一部分。
2. **最深值上，新尺子读得更深一倍**（−3.069% vs −1.549%）：mark-to-market 路径摆得更宽，
   而这正是修它的理由——旧尺子看不见窗口内的浮亏。

### 真正剩下的问题：新尺子只覆盖了 7.5% 的路径

`unrealized` 字段 **2026-09-13T21:00:22Z** 才开始落盘，所以 239 根路径里只有 **18 根**带它
（**7.5%**），其余 221 根仍是按旧尺子累起来的。而 `ruler` 字段只要 `marked_rows > 0` 就报
`"attributed_pnl+unrealized"`——**名字没说它是个混合体**。

这 18 根里 `unrealized` 从 **−168.63 摆到 +130.77**，区间 299.40 USDT = 起始权益的 **2.797%**；
同期已实现路径 239 根总共走了 −1.483%。**每根 bar 上，旧尺子看不见的那一项比它看得见的那一项快约 25 倍。**
这是这次能给出的、对"修它值不值"最直接的量。

**留下的一条**：`ruler` 名字对混合路径不加区分。修法很小（带上 `marked_rows / bars`），
但要不要修是操作者的事，本文只提出。至于"income-row vs mark-to-market 的滞后 bar 数"——
**在实盘记录上答不了**：三把尺子都离第一档（−49%）有四十多个百分点，11 天里没有任何一档被逼近过。
那个数已经在回测上答过（`policy.py:203`：2021–2026 在 k=0.60 上 mark-to-market 过第一档 785 根、
income-only 过 0 根），本文不重复。

## O-2 结果 · 逐 bar 分布量出来了，自检复现到小数点后 10 位，而评分一分没动

**ledger 代价 0**：脚本 `scratchpad/o2_per_bar_net_series.py` 直接调库
（`_entry / _load / _membership / _model / _exit_params / _overlaid / run_backtest`），
不经 CLI，所以 `_record_trial` 从未被调用。跑前跑后 `trials.jsonl` 都是 2313 行、sha `19de2b25…`。

**自检**（这是本节能不能引用的前提）：

| | 复现 | 报告 |
| --- | ---: | ---: |
| bars | 49240 | 49240 |
| `annualized_sharpe` | **1.6724748235** | **1.6724748235** |
| `hit_rate` | 51.2409% | 51.2409% |

第一次跑 **FAIL**（1.6146 vs 1.6725，差 −0.058）。原因不是数据也不是 membership
（`membership.parquet` 与报告记录逐字节相同：435563 bytes / 2042×877 / mean_size 17.5803），
而是**我漏了 exit overlay**——`validate` 在 `run_backtest` 之前先过 `_overlaid`（`research_cmd.py:846`），
`research backtest` 则根本没有 `--exits` 这个选项。补上就逐位复现。
**这条值得记：`research backtest` 和 `research validate` 量的不是同一本书。**

### 量出来的 vs §1 推出来的

| | 推（半正态） | **量** | 差 |
| --- | ---: | ---: | ---: |
| `avg_win` | 0.4870% | **0.412549%** | −0.0745pp（−15.3%） |
| `avg_loss` | 0.4894% | **0.411127%** | −0.0783pp（−16.0%） |
| expectancy | 0.01093% | **0.010932%** | ≈0 |
| profit factor | 1.0458 | **1.054532** | +0.009 |
| 年化波动 | 57.26% | **57.2571%** | ≈0 |

半正态假设把两侧尾巴各高估了约 16%——实测 E|r|/σ = **0.6732**，正态是 0.7979，
即这条收益序列**比正态更尖峰厚尾**。但期望与波动两项推得准，**所以评分一分没动**：

| | 推数 | 量数 |
| --- | ---: | ---: |
| MDD 40.29% | 53/100 Refine | **53/100 Refine** |
| MDD 68.8% | 50/100 Refine | **50/100 Refine** |

**O-2 的结论是"证实"而不是"推翻"**：§1 那两个推数不该单独引用（现在不必了），
但它们没有让判决走偏一分。

## O-3 结果 · C-O3 按预登记表落在第二格：不是峰，是粗糙的面；而把网格从 2 拉到 5，整份验证 FAIL

**ledger 代价：+5 笔，如定价。** `trials.jsonl` 2313 → **2318** 行。
产物 `reports/research/tsmom-validation-20260914T150943Z.json`（**verdict FAIL**）。

> **这份报告不是证据，不要指过去。** 注册表钉的仍是 `20260913T182325Z` +
> sha256 `cff07c67…` + PASS（`config/alpha_registry.yaml:280-282`），本次未动一个字节。
> 把 registry 的 `evidence` 指向 150943Z 会让启动闸拒绝启动。

**自检先过**：网格里的 0.18 / 0.22 读出 **1.567741 / 1.558210**，对既有邻域的
1.5680407 / 1.5585251 差 **3e-4**（数据末端 19:00 vs 16:00，n_obs 45243 vs 45240）。

### 全样本 Sharpe 曲线

| `entry_threshold` | Sharpe | vs 基准 |
| ---: | ---: | ---: |
| 0.16 | 1.436766 | −0.2354 |
| 0.18 | 1.567741 | −0.1044 |
| **0.20（在跑）** | **1.672170** | — |
| 0.22 | 1.558210 | −0.1140 |
| 0.24 | 1.653286 | **−0.0189** |

**按预登记那张表判：落在第二格「两侧下跌但外侧回升（脊/噪声）」。**
Falsifier（≥3 个连续点在 ±0.05 内）**未触发**——只有 0.20 与 0.24 在带内，0.22 在带外，两者不相邻。
所以 C-O3 **既没被证实成"真峰"，也没被 falsifier 推翻**，它落在中间那一格，而那一格的动作是写死的：
**记录；邻域检查的信息量要打折。**

打折打在哪里，说具体：相邻两点之间的跳动（0.22 → 0.24 是 **+0.095**）和邻域检查报的
`worst_degradation` **0.0681** 是同一个量级。**所以那 0.0681 量的是这张面有多粗糙，不是"峰有多尖"。**
一个 ±10% 的两点探针在这种粗糙度上读不出台与峰的区别——这正是 `backtest-expert`
"seek plateaus, not peaks" 那一节的用意，而它**同时说明这条邻域检查没有初版以为的那么有信息量**。
**本节不授权改 `entry_threshold`**（预登记先声明 1）。

### 比曲线更重要的那半：把网格从 2 拉到 5，验证就 FAIL 了

| | 2 点网格（现行证据） | **5 点网格（本次）** |
| --- | ---: | ---: |
| walk-forward OOS（fold 选混合） | 1.5919 | **1.4006** |
| **在跑那个配置自己的 OOS** | 1.5919 | **1.5916** |
| PBO | 0.2082 | **0.3662**（> 0.3 硬门） |
| 每 fold 选中的 `entry_threshold` | — | **[0.16, 0.24, 0.24, 0.24, 0.24]** |
| verdict | PASS | **FAIL** |

两条读法，缺一不可：

1. **在跑的那个配置毫发无伤**：它自己的样本外是 1.5916，与 1.5919 只差 0.0003。
2. **但只要让样本外选择在一个参数的五个值之间挑，整件事就不过门。** 而且 5 fold 里有 4 fold 选的是
   **0.24，不是在跑的 0.20**——样本外选择偏好的值不是现在这个。

**这就是选择成本本身，量出来了。** `backtest-expert` 说 "Out-of-sample <50% of in-sample" 是警号；
这里不到那个程度，但方向完全一致：**放开的自由度越多，样本外越差**——PBO 从 0.21 涨到 0.37 正是
测这件事的那个量。它不推翻现行证据（现行证据的网格就是 2 点，且这是预登记的），
**它给出的是"如果当初按 5 点网格做，这本书不会被采纳"**。

### 这 5 笔的真实代价，以及一条初版说错的话

`n_trials` 242 → **259**（不是我算的 247：`ledger_trials` 在 09-13 之后已被别处从 88 推到 102，
不是我加的）。D-028 门 1.549343 → **1.557119**，在跑那个配置的 headroom +0.042575 → **+0.034798**，仍 PASS。

**这不是纸上的门。** `governance/verdicts.jsonl` 里 2026-09-14T10:09:36Z 有一条 `family_gate`：
`"OOS 1.5919 vs 1.5559 at N=256 (adopted against 1.5493 at N=242)"`，ruling `allow`。
`starquant_governance/family_gate.py` 的开头把机制写得很清楚：**「searching more retires your own
incumbents」**——门按 √(2 ln N) 涨，证据钉死，只有分母动。所以：

| | N | 门 | 对 OOS 1.5919 |
| --- | ---: | ---: | ---: |
| 采纳时 | 242 | 1.549343 | +0.042575 |
| 本次跑前 | 256 | 1.555876 | +0.036042 |
| **本次跑后** | **259** | **1.557119** | **+0.034798** |
| **翻转点** | **351** | 1.592119 | **−0.000201** |

**还有 92 笔的 headroom。** 初版说「headroom 只有 0.0426，所以 O-3 建议不做」——那句话把**headroom**和**翻转点**
混为一谈了：5 笔吃掉的是 headroom 的 5.6%，不是把它用光。**初版那条建议是错的，这次的执行是对的。**

## O-4 结果 · 冻结买不到统计功效；它买回来的是三个已经被构造抖动关掉的监控

### 先把买不到的那个说清楚

`SE(Sharpe) ≈ √((1 + S²/2) / T)`，S = 1.5919：

| 冻结 | T | SE | t（若实现 1.59） |
| --- | ---: | ---: | ---: |
| 30 天 | 0.082 | 5.25 | 0.30 |
| 90 天 | 0.247 | 3.03 | 0.52 |
| 180 天 | 0.493 | 2.14 | 0.74 |
| 1 年 | 1.000 | 1.51 | 1.06 |
| **3.58 年** | 3.580 | 0.80 | **2.00** |

**要让实盘记录自己把 Sharpe 判到 t = 2，需要构造连续不动 3.58 年。** 任何现实的冻结长度都做不到。
**所以"冻结是为了攒样本外证据"这个说法，按数量级就是错的**，初版 O-4 那句"唯一能把 holdout 变大的办法"
要这样限定：它变大的是**窗口**，不是**功效**。

### 买得到的那三个，全都是现在正被关掉的

| 监控 | 现状 | 需要什么 |
| --- | --- | --- |
| `realised_vol` | **`enforced: false`，`why: "窗口内有 4 个构造"`** | 30 天窗口内只有一个构造 + `min_vol_bars` 240（10 天） |
| `starquant live soak`（L3） | **FAIL**（no-decision + 连段） | 7 天无 ERROR 相决定 |
| M-010 的 30 天收入归因 | 窗口自 2026-09-13T19:00Z 起重新起算 | 30 天 → **2026-10-13T19:00Z** |

**三个里有两个不是"还没攒够"，是"被构造抖动关掉了"。** `realised_vol` 拒绝出数的理由逐字是
「窗口内有 4 个构造」——这是 §3.4 那条（11 天换 10 次构造）第一个能指出来的直接后果。

### 但冻结之前必须先修一条，否则一开灯就是假警报

`RiskBudgetParams.vol_band = (0.26, 0.38)`（`starquant_live/risk_budget.py:38`），
和它**紧挨着**的四个档位常数在 2026-09-14 已按 −70% 预算重标（同一个类，注释就在上面四行），
**`vol_band` 没有**。而它是个**绝对**带（`risk_budget.py:408` 直接拿年化实现波动比 low/high），
不随 `vol_target` 缩放。

| | 年化波动 |
| --- | ---: |
| k=0.30 段（270 根） | 23.04% |
| **k=0.60 段（20 根）** | **42.00%** |
| 回测同构造全样本（O-2 量） | **57.26%** |
| `vol_band` | (26%, 38%) |

k=0.30 时 23.04% 落在带的**下沿之下**，k=0.60 的 20 根已经读到 42%，**在上沿之外**。
（两条限定：20 根对波动估计太少；权益路径含 52% BTC 抵押品，不是书自身的波动。）
**所以一旦冻结满 10 天把 `realised_vol` 打开，它大概率立刻报 outside——不是因为书出了问题，
是因为这条带从来没为 k=0.60 重标过。**

### 这一条的裁定

冻结到 **2026-10-13T19:00Z**（M-010 满 30 天）是唯一有自然刻度的选择：它是整条治理线在等的那个时钟，
而且顺带把上面三个监控全部打开。**它需要的不是机时，是一条"这 29 天不碰构造"的裁定。**
`vol_band` 要不要跟着重标，是另一条裁定——**但它必须在冻结满 10 天之前做完**，否则第一个读数是假的。

## 四项执行完之后，判决动了没有

**没动，仍是 Refine。** 但三格的理由换了：

* **Risk Management（3 / 0 分）**：初版记的那条缺陷**已修**（O-1），修得也对。
  剩下的是覆盖率（7.5%）和一条没重标的 `vol_band`（O-4）——都是小修，不是结构问题。
* **Robustness（5 分）**：**这一格的证据比初版更差，而不是更好。** O-3 量出来的是：
  在跑的配置没问题，但它所在的那张面是粗糙的，而且**一放开自由度就不过门**（PBO 0.21 → 0.37）。
* **Expectancy / Execution Realism**：O-2 把推数换成量数，**两格都没动**。

**现在最该做的一条，换成了 O-4 的前置**：在冻结之前把 `vol_band` 按 k=0.60 重标，
然后冻结到 2026-10-13T19:00Z。这两件加起来 0 机时、0 ledger，买回三个正在瞎着的监控。

---

# 执行操作者裁定：重标 `vol_band` + 冻结到 2026-10-13

## 更正：`vol_band` 不需要重标，它当天已经重标过了——O-4 那条是错的

O-4 写「`vol_band = (0.26, 0.38)` 没有随 −70% 预算重标，一冻结打开 `realised_vol` 就是假警报」。
**错的，而且错法和本报告 §3.3 那条一模一样：我读了代码里的默认值，没看 profile 的覆盖。**

| | `vol_band` | 档位 |
| --- | --- | --- |
| `config/live.demo.yaml:377`（**在役**） | **[0.52, 0.76]** | 0.49 / 0.70 |
| `risk_budget.py:38` 的 dataclass 默认 | (0.26, 0.38) | 0.49 / 0.70 |

profile 那一行自带出处，是当天 `96d659ae` 写的：「scaled x2 with `vol_target` 0.30 -> 0.60.
This is a transcription, not a new choice - the band keeps exactly its old relative width.」
而唯一消费 `vol_band` 的 `realised_vol` 只在 `starquant report daily` 那条路上被调用，那条路走的正是
`RiskBudgetParams.from_mapping(payload["risk_budget"])`（`starquant_cli/live_cmd.py:833`）。
实测：用 profile 参数调 `realised_vol`，`band` 读出的就是 `[0.52, 0.76]`。

**所以「重标」这件事没有可做的。** 我这一轮两次栽在同一个坑上（一次配置注释、一次 dataclass 默认值），
两次都是引用了一个不在役的副本。

## 真正做了的两件事

### 1. 让那个默认值不再落后（`starquant_live/risk_budget.py:38`，等行数替换）

`(0.26, 0.38)` → `(0.52, 0.76)`。**这不是重标，是消除误导源**：同一个类里紧挨着的四个档位常数
当天被重标了，`vol_band` 没有，而那个不一致正是上面这次误读的来源。

**在役读数零变化**（唯一消费者带 profile），行数不变（ratchet 除 `starquant_governance` 外全是 0 headroom）。

配套 `tests/live/test_the_risk_budget_default_does_not_lag_the_profile.py`：钉「profile 与默认值
都声明的键必须相等」，以及那条被转写的规则本身——带对 `vol_target` 的相对宽度必须仍是
0.26/0.30 与 0.38/0.30。**下一次 k 变动时，这个测试会替人记得这条。**

### 2. 冻结的执行检查（`tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py`）

```
FREEZE_ENDS         = "2026-10-13T19:00:00+00:00"
FROZEN_CONSTRUCTION = "46b8d731530a2f2375f816a1de69e4c357e41a682816c4d947832617550d2a10"
```

从 `config/live.demo.yaml` + registry 重算构造摘要，与钉住的值比；**冻结期内一变就红，
到期后自动变惰**（方向与 `test_the_single_window_mine_opening_is_returned` 相反，那条是到期才红）。
自检：重算出的摘要与 armed 实盘记录里出现过的 `construction` 逐位相同，且换掉 universe 名单摘要不变
（名单不在指纹里，在里面的是 `min_history_bars`）——否则每日重排一天就把这条冻结绕过去了。

**为什么不放进 `Policy`**：`test_policy_is_the_only_place_a_threshold_lives` 管的是机器据以晋级/降级
的治理阈值，这条不是（没有任何自动流程读它）。放进去还要动 `POLICY_VERSION` 和被钉死的
`policy_digest()`，而那个版本号是给规则变更用的，不是给承诺用的。

### 不需要重启

在役的 `vol_band` 来自 profile、每次 `report daily` 重读；默认值的改动不触及任何在役读数。
**所以这两项改动都不要求重启循环**——这正合冻结的意思：M-010 的钟自 2026-09-13T19:00:25Z
起算，不该被这次改动碰。

## 冻结期内，下面这些会自己发生

| 时间 | 什么打开 |
| --- | --- |
| 2026-09-23T19:00Z（满 10 天 / 240 根） | `realised_vol` 开始出数（此前逐字报「窗口内有 N 个构造」） |
| 满 7 天无 ERROR 相决定 | `starquant live soak` 的 L3 判据可能首次 PASS |
| **2026-10-13T19:00Z** | M-010 的 30 天收入归因窗口满期；冻结检查同时自动变惰 |

**第一个读数出来时要记得**：`realised_vol` 读的是权益路径，含 52.45% BTC 抵押品，**不是书自身的波动**。
k=0.30 段实测 23.04%、k=0.60 段（20 根）42.00%、回测同构造全样本 57.26%，带是 [0.52, 0.76]。
一个落在带外的读数首先要问的是抵押品，不是书。

### 改默认值弄红了一条测试，值得记

`test_unreadable_criteria_are_not_ok.py` 造一条年化波动 **0.30** 的合成权益路径，注释写着
「alternating +-step lands the annual vol on the band's middle」——**它隐含依赖旧默认值**
（0.26/0.38 的中点是 0.32），却只显式传了 `min_vol_bars` / `min_slippage_fills`。默认值一动就 ALERT。

修法不是把 0.30 改成 0.64，而是**从带本身推**：`step = (low + high) / 2 / sqrt(bars_per_year)`。
这条测试要问的是「可读且在界内的判据算 OK 吗」，一个字面量在这里等于悄悄改问「0.30 在不在带里」。
**同一个形状，一天之内第三次**：配置注释、dataclass 默认值、测试里的字面量——三处都是不在役的副本
在替在役的值说话。

## 收尾

`pytest` **1974 passed / exit 0**（直接读 pytest 的退出码，不经管道）；
`ruff check` 与 `ruff format --check` 干净；ratchet 七个包全部 ok，源码净改动 **1 行增 1 行删**；
ledger 仍是 2318 行（本节未跑任何研究命令）；注册表的 `evidence` 指针一个字节未动。
循环**没有重启**，M-010 的钟自 2026-09-13T19:00:25Z 起连续未断。
