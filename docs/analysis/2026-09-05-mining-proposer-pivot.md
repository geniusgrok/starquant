# 深度分析：把 LLM 提案者接进 mining——通道两端都是空的（PIVOT）

> 分析头部（deep-analysis V3.3）
> - Interaction Mode: **Yellow**。关键事实全部来自代码与已提交的研究报告；唯一的外部事实（RD-Agent `fin_factor_report` 的输入输出形态）取自其公开文档，标 E3。
> - S/M/L: **L**。命中两个维度：`reports/research/trials.jsonl` 是 D-020/D-028 判决的核心链路，改变它的计数语义即改变什么能上实盘；LLM 提案者进入 alpha 遴选路径，属难回滚（ledger 一旦被污染，此前 135 行的 DSR 数字全部不可比）。
> - 当前 Gate 决策上限：**Weak GO（对调整后方案 O-1）**。原方案 G3 FAIL（相对价值实测为 0）→ PIVOT；O-1 过 G6（§6.6，0 OPEN P0/P1）与 G7（§8.7）。G2 PASS：P0 Claim 由 E1 证据判为 REFUTED，不是 UNKNOWN。
> - 外部动作授权：**无**。本轮只读代码与既有报告，未跑 `research validate`，未写 `trials.jsonl`，未改实盘配置。
> - 缘起：与 microsoft/RD-Agent 的对照评分。建议是我给的，本轮结论是它被仓库里已有的证据推翻。

---

## 0. Decision Memo

| 项目 | 结论 |
| --- | --- |
| Final Decision | **PIVOT → Weak GO（O-1）**。原方案（接 `fin_factor_report`）不成立——提案者不是瓶颈。调整后方案 O-1（给 `Expr` 补读 `panel.funding` 的叶节点，一次预登记搜索裁决 C-003）过 G6 / G7，授权为**有边界的证伪实验，预期阴性**。契约见 §8，Firewall 两条互斥重开条件见 §7.2；提交、跑 validate、写 ledger 三件事由操作者执行 |
| 本轮最重要的发现 | **C-002 的「剪刀」由逻辑推演变为实测**：20 条加密因子里，**没有一条落进「能表达、但枚举想不到」那一格**——而那是 LLM 提案者唯一能占的位置 |
| 第二重要的发现 | `expr.py` 里 `funding` 出现 **0 次**。表达式语言读五个字段（`close` / `high` / `low` / `quote_volume` / `taker_buy_quote`），读不到 `panel.funding`、`open`、`volume`(base)、`trades` |
| 被推翻的 Claim | C-001「StarQuant的瓶颈是候选供给」——P14 的 225 个候选就是反例，且它当时就在仓库里 |
| 最大限定 | **P14 的 225 个候选是在 `vol_target 0.15` 上排序的，而实盘现在跑 0.30**（E-012/E-013）。0.30 处上限会 binding，排序不是尺度不变的——同一候选 1.0780 → 1.1207。「表达式空间已搜尽」这个结论测量于一个**本书不再持有的规模**上 |
| 交付状态 | O-1 已实现并交付，分支 `feat/mining-funding-node` 六个提交（§12）。交付**之后**做了一次独立对抗核验，查出一个真缺陷（防 KILL-027 的守卫自己就是 KILL-027）、四个变异下空过的测试、两条没被兑现的预登记规则——全部已修，记录见 §11。实验本身（AC-P17-02/03）仍未跑 |
| 一处自查纠正 | 本文件初稿把 `funding.symbols = 0` 读成运行事实，据此断言搜索跑在无资金费面板上。**错的**：那是 `_store_fact` 的布局假设缺陷（E-010），与该次运行无关。真实口径由 E-012 的四臂复算定出。撤回不删除，因为下一个人会犯同一个错 |

---

## 1. Evidence Ledger

| ID | 类型 | 来源 | 摘要 | 支持/反证 | 等级 |
| --- | --- | --- | --- | --- | --- |
| E-001 | CODE | `starquant_alpha/mining/search.py:236` | `to_signal()` 把候选编译成普通 `SignalSpec`，判决路径逐字不变。接口确实存在 | 支持 | E1 |
| E-002 | CODE | `starquant_alpha/mining/expr.py` | 12 个节点；`grep -oE 'panel\.[a-z_]+'` 与 `_required()` 的并集只有 `close` / `high` / `low` / `quote_volume` / `taker_buy_quote` | 反证 | E1 |
| E-003 | CODE | `reports/research/trials.jsonl` | 135 行：tsmom 87、meanrev 27、flow 12、breakout 9 | 中性 | E1 |
| E-004 | CODE | `pyproject.toml` | 零 LLM 依赖；CI 跑 `pytest -m "not network"` | 反证 | E1 |
| E-005 | OFFICIAL | RD-Agent 文档 | `fin_factor_report --report-folder=<…>`：输入 A 股卖方研报，extractor 分 growth / quality / sentiment / risk，输出落进 Alpha158DL 特征空间 | 反证 | E3 |
| E-007 | CODE | `reports/research/mine-shortlist-20260904T145150Z.json` | 7 个结构族、**225 个不同表达式**、时点面板；`declared_trials 225`，`rejected` 四项全 0 | 强反证 | E1 |
| E-008 | CODE | 同上 + `RESEARCH_LOG` P14 | 最好候选 `squash(rangepos(168), 2)` 全样本 Sharpe **1.0745**，在跑的 tsmom **1.6972** | 强反证 | E1 |
| E-009 | CODE | `reports/research/correlate-tsmom-mined_503368238d55d847-20260904T145150Z.json` | 与 tsmom 净收益相关 **0.4709**，边际 Sharpe **−0.0800**（等权混入 1.6972 → 1.6172） | 强反证 | E1 |
| E-010 | CODE | `starquant_data/manifest.py:63` + `store.py:105` | ~~搜索跑在无资金费的面板上~~ **该推断已撤回。** E-007 清单里的 `funding.symbols = 0` 不是运行事实而是清单缺陷：`_store_fact` 按 `funding/<SYMBOL>/funding.parquet` 查找，实际布局是 `funding/<SYMBOL>.parquet`，`if not child.is_dir(): continue` 跳过全部文件。诊断时 231 文件 / 20 MB 在盘而 `build_manifest` 报 0（`44136fa355b3678a` 经核为 `_digest({})`）。**已由同日 D-040（`bd7cd6e`）修复**，布局收回 `starquant_data.store` 一处 | 推断撤回 | E1 |
| E-012 | EXPERIMENT | `scratchpad/u3_attrib.py` | 四臂复算定出 P14 的真实口径：**`vol_target 0.15` + 资金费打开**，Sharpe 1.0780 对记录的 1.0745（Δ +0.0035）；另外三臂 +0.0462 ～ +0.0993。残差由 7 根 bar 差与 D-034 前的旧对齐解释 | 支持 | E1 |
| E-013 | EXPERIMENT | 同上 | 同一候选在 `vol_target 0.30` 上是 1.1207（资金费打开）。**排序不是尺度不变的**——D-036 在时点 universe 上量到 355 个 capped bar，`max_weight` 与 gross 上限在 0.30 处 binding，D-035 的「任意缩放后净 Sharpe 精确不变」不再适用 | 强限定 | E1 |
| E-011 | CODE | `expr.py` 量纲规则 | `Ratio` 拒绝跨量纲相除（`RETURN / VOLUME` → `ExprError`）；`Mul` 只接受无量纲两侧；无 `Abs`；横截面只有 rank / zscore / demean，没有回归 | 反证 | E1 |

---

## 2. Claim Register

| ID | 命题 | P级 | Falsifier | 证据 | 状态 |
| --- | --- | --- | --- | --- | --- |
| C-001 | StarQuant的瓶颈是候选供给 | P0 | 一个已有提案者产出大量候选而无一通过 | E-007/8/9 | **REFUTED** |
| C-002 | 研报因子能给出现有枚举搜不到的先验 | P0 | 可表达的研报因子恰好落在已搜空间内 | E-002, E-007, §3 | **REFUTED** |
| C-003 | 当前特征面板已被搜尽 | P1 | 加入新特征后同一搜索出现越过 tsmom 同口径基线的候选 | E-007, E-013, AC-P17-02/03 | **SUPPORTED**（2026-09-06） |

C-003 记 PARTIAL 的理由在 E-013 而不是原先写的 E-010：那 225 个候选排序于 `vol_target 0.15`，而 D-035/D-036 之后实盘跑 0.30、上限会 binding、排序不再尺度不变。所以「搜尽」这个结论测的是**另一个规模的书**。Falsifier 里的阈值因此不能写死 1.70——tsmom 自己的基线也得在同一口径下重取，否则又是一次不同口径的比较。

### C-001 为什么倒了

原判断的依据是「十余轮研究只启用 1 个策略」。同一份日志给出的是相反读数：`RESEARCH_LOG` 里 5 个被否决的信号各有明确的**机制性**死因——xsmom 的信号层与组合层双重风险归一化、carry 被资金费公平定价、flow 在时点 universe 下崩溃。这是**否决有效**的证据，不是**供给不足**的证据。

P14 更直接：枚举提案者已经产出 225 个候选，最好的一个比在跑的书低 0.62 Sharpe，混进去边际为负。日志当时的结论就是「在这个表达式空间里，当前信号库没有留下明显的钱」。

---

## 3. Pre-2 验证：20 条因子的逐条判定

表达式语言的实际读数面（E-002）与量纲规则（E-011）共同决定可表达性。

| # | 因子 | 判定 | 依据 |
| --- | --- | --- | --- |
| 1 | 时序动量 TSMOM | ✅ 已搜 | `squash(ret(h)/vol(w), s)` — momentum 族 |
| 2 | 横截面动量 XSMOM | ✅ 已搜 | `cs_rank(z(ret(h), w))` — normalised 族 |
| 3 | 短期反转 | ✅ 已搜 | reversal 族（负号靠 `Mul(Const(-1), …)`） |
| 4 | 通道位置 / 突破 | ✅ 已搜 | `rangepos(w)` — range 族 |
| 5 | 波动率 regime 门控 | ✅ 已搜 | regime 族（已排除代数抵消组合） |
| 6 | 成交量惊奇 | ✅ 已搜 | `squash(volratio(w), s)` |
| 7 | 主动买卖失衡 | ✅ 已搜 | `squash(takerbuy(w), s)` |
| 8 | 特质波动率 | ⚠️ 缺节点 | `features.rolling_beta` 已存在，`Expr` 无对应节点 |
| 9 | 残差动量 | ⚠️ 缺节点 | `features.residual_returns` 已存在，`Expr` 无对应节点 |
| 10 | 下行波动 / 半方差 | ⚠️ 缺节点 | 数据够，无条件聚合节点 |
| 11 | 收益偏度 | ⚠️ 缺节点 | 数据够，无高阶矩节点 |
| 12 | Amihud 非流动性 | ⚠️ 缺节点 | 缺 `Abs`，且 `RETURN / VOLUME` 被 E-011 的量纲规则拒绝 |
| 13 | 资金费 carry | ⚠️ **缺节点，数据在库** | 1,010,914 行，D-034 刚修好对齐；`Expr` 读不到 |
| 14 | 资金费横截面拥挤度 | ⚠️ **缺节点，数据在库** | `tsmom` 手写实现了它，挖掘搜不到 |
| 15 | 换手率 | ❌ 缺数据 | 无流通量 / 持仓量 |
| 16 | 基差（永续 − 现货） | ❌ 缺数据 | 无现货价格 |
| 17 | 持仓量变化 | ❌ 缺数据 | 面板无 OI |
| 18 | 多空账户比 | ❌ 缺数据 | 面板无 |
| 19 | 清算量 | ❌ 缺数据 | 面板无 |
| 20 | 订单簿深度 / 价差 | ❌ 缺数据 | 面板无 |

**7 已搜 · 7 缺节点 · 6 缺数据。**

### 判定

关键不是 35% 这个比例，是**这 20 条里没有一条落进「能表达、但枚举想不到」那一格**。

- 能表达的 7 条 → 枚举 225 个候选已覆盖同族，结果是 E-008/E-009 的阴性
- 不能表达的 13 条 → 缺的是 `Expr` 节点或 `starquant_data` 的列。**LLM 变不出面板里没有的列，也补不上 `expr.py` 里没有的类**

两端都是空的。`fin_factor_report` 通道的宽度实测为 0，Pre-2 与 C-002 一并 REFUTED。

---

## 4. 相对价值

| 替代路径 | 可用性 | 成本 | 真实增量 | 结论 |
| --- | --- | --- | --- | --- |
| 不行动 | 立即 | 0 | — | 对照 |
| 加 `Funding` 叶节点，重跑 225 + 资金费族 | 数小时 | 单文件；`research backtest` 不写 ledger | 打开第 13/14 条，同时验 C-003 | **最优先** |
| 加第 8–12 条那五个节点 | 数天 | 中；`features` 里已有两个现成函数 | 打开 5 条 | 次优先，各自独立提案 |
| 接新数据源（OI / 现货 / 订单簿） | 数周 | 高；新下载、校验、时点对齐 | 打开 6 条 | 待定 |
| **接 `fin_factor_report`** | 数周 | LLM 依赖（破坏 E-004 的离线 CI 与 D-024 的证据可复现）+ 语料（加密无对应生态）+ 自适应试验计数（开放统计问题） | **§3 实测为 0** | **否决** |

**Cost of Delay 低**：tsmom 在跑，没有正在流血的东西。这一条本身就否掉了「先上复杂方案再说」。

**Business Case 净值为负**：成本三项皆实，收益实测为 0。

---

## 5. 明确记为未做

- **没跑 `research validate`，没写 `trials.jsonl`。** 本轮零试验额度消耗，与 P14 同一条规矩。
- **没有验 C-003。** 「加了资金费节点之后是否出现越过同口径 tsmom 基线的候选」是下一步的实验，本文件只把它定义为 Falsifier，不预测结果。**重跑必须在 `vol_target 0.30` 上重建两边**（E-013）：候选与 tsmom 基线都要，P14 的 1.0745 与 1.6972 都是 0.15 口径，不能当作「之前」那一臂直接用。
- **`research mine` 的报告不能自我复现。** 它记 dataset / universe_mode / range / symbols / declared_trials / evaluated / rejected / candidates，但**不记 `--funding`、不记成本模型、不记 execution、不记 profile 的组合参数**。定 U-3 因此要靠四臂暴力复算去反推两个本该被写下来的参数。这与 D-024 对 validate 报告的要求（「fold 向量可从报告自身复现」）是同一条标准，`mine` 没有达到。**已在 O-1 里补上**（DL-P17-04，见 §12.3）。
- **`_store_fact` 的缺陷本轮只诊断不修**，理由是修它会让所有历史报告的 funding 事实开始不匹配，需要一个刻意的决定而不是一次顺手修改。**该决定已由同日 D-040（`bd7cd6e`）作出**：全仓带清单的报告只有 4 份，修复前 3 份本来就在告警，所以「淹掉一片告警」量出来是 1 份；v1 的零判为**「未记录」**而不是漂移，因为 `{0, 0, _digest({})}` 与空目录在记录里无法分辨，「未知」是它的准确读数。D-041 顺带给 `manifest_problems` 接上了第一个调用方——此前它没有生产调用者。
- **第 8–12 条的五个节点没有排期。** 它们各自是独立提案，不与资金费节点捆绑——捆绑会让一次搜索的 `declared_trials` 无谓膨胀，而那正是 `search.py` 文档字符串里那条规则要防的。
- **自适应提案的试验计数问题没有解决，只是绕开了。** 结论是不接 LLM 提案者，所以这个开放统计问题本轮不需要答案。若将来重开，A-004 仍然 OPEN：DSR 的零假设假定可交换抽样，而条件于前轮结果的提案不是。
- **RD-Agent 一侧的数字未经复现**，全部为其自报口径（E-005 标 E3）。本文件的否决不依赖它们成立——即使它们全部为真，§3 的判定不变。

---

## 6. Phase 7：Adversarial Review

### 6.1 独立性声明

| 项目 | 内容 |
| --- | --- |
| 冻结输入 | 本文件 §0–§5（E-010 撤回后的版本）、`RESEARCH_LOG` P17、Phase 5–6 的 O-1 + F-4 范围与六条预登记规则 |
| 审查者与原作者关系 | **同一 Agent**。锚定风险真实且已经兑现过一次：E-010 的错误推断是我写的，也是我读了两天后才发现的 |
| 可访问证据 | 只引用 E-001 ～ E-013 与仓库内已提交的报告 |
| 不得执行的外部动作 | 不跑 `validate`，不写 ledger，不改实盘 |

### 6.2 最强反方论点

> 资金费族可达的两个显然形状**各有结论了**：纯 carry 第四轮判死（「资金费率大致等于预期漂移，被公平定价」）；动量×资金费就是 tsmom 的 crowding modifier，09-05 刚重新启用（OOS 1.7647）。搜索能宣称的增量只剩「其他形状」——而 P14 已经证明，动量空间里的「其他形状」对同底纯动量 **+0.002**。所以最便宜的动作是：凭现有证据判 C-003 SUPPORTED，直接去做数据源，跳过 O-1。

**反驳**：现有证据在 0.15 口径、且没有任何一个读资金费的节点——C-003 在资金费方向上**真的没测过**。O-1 一天、约 50 次试验；一次假的 SUPPORTED 会把几周送进数据源工作，而问题还开着。保险便宜。但反方有一半是对的：**O-1 的预期结果是阴性，这要写进预登记**（D-P17-03），它的价值是干净关掉 C-003，不是找 alpha。

### 6.3 Kill Register

| ID | 攻击命题 | 关联 | 证据 | 严重度 | 状态 | 触发动作 |
| --- | --- | --- | --- | --- | --- | --- |
| **KILL-P17-01** | Falsifier 拿全样本 Sharpe 比基线。250 个噪声 Sharpe 的最大值天然偏高——`mine` 自己的文档字符串就写着 "ranking hundreds of expressions on the full sample *is* selection"。这条 Falsifier 会产出**假的 C-003 REFUTED** | Falsifier | `research_cmd.py:1667` | P1 | **MITIGATED** | D-P17-04：「越过」= 通过 `validate --prior-trials N`，不是全样本 |
| **KILL-P17-02** | §6.2 的最强反方 | C-003 / O-1 价值 | 第四轮；registry 注释；P14 | P1 | **ACCEPTED** | D-P17-03：预期阴性写进预登记；O-1 定性为证伪实验 |
| KILL-P17-03 | 更便宜的替代：手写 2–3 个资金费信号直接 validate，`--prior-trials 3`，不动 Expr——项目里所有其他信号都是这么来的 | 相对价值 | 全部既有信号的来路 | P1 | **CLOSED** | 那两个显然形状**已经**手写并跑完了（KILL-02 的证据）。手写路径不是没走，是走到头了；剩下的恰好是手写不会写的形状 |
| **KILL-P17-04** | 面板级能力检查若放进 `enumerate_candidates`，会破坏它「确定性、不碰数据」的性质——而 `_resolve_mined`（`research_cmd.py:157`）**依赖这一性质**重推导 hash | O-1 设计 / F-1 | `_resolve_mined` 文档字符串 | P1 | **MITIGATED** | D-P17-02：`include_funding` 是**搜索空间参数**，CLI 按 `panel.funding is not None` 传入，`evaluated` 因此天然诚实；`_resolve_mined` 默认 True 即可解析两类 hash |
| KILL-P17-05 | 「排序在 0.30 上会动」是推断不是证据：E-013 只测了一个候选的绝对值 | C-003 依据 | E-013 | P2 | **ACCEPTED** | 降格为「可能动」。重跑本来就要在 0.30 做，排序顺带回答，不单独立项 |
| **KILL-P17-06** | 「tsmom 同口径基线」没定义：registry 现在 crowding ON（09-05 重启），correlate 里的 1.6972 是哪个配置已不可考 | 规则 4 | registry 注释；E-012 | P1 | **MITIGATED** | DL-P17-05：基线 = registry 当前参数，**同一次运行**里重算并写进报告 |
| **KILL-P17-07** | `uses_funding` 从树派生没有测试守着；F-2 就是 KILL-027 | F-2 / 验收 | `search.py:242` | P1 | **MITIGATED** | T-P17-03：`to_signal(c).needs_funding({})` 当且仅当树含 `Funding` |
| KILL-P17-08 | mine **跨运行不记账**。P14「两轮搜索」：第一轮 255 个候选不在任何申报数里，只有第二轮的 225。按运行申报而非累计申报，是 p-hacking 的现成入口——机制存在，尚无实例造成伤害 | ledger 完整性 | `RESEARCH_LOG` P14 | P1 | **ACCEPTED（既有设计）** | 与手写策略的 `--prior-trials` 手工申报同一先例；不由 O-1 引入也不由 O-1 解决。**另立项**：mine 追加 search ledger（run_id + hash 集合），累计去重数可算。进 Scope Firewall |
| **KILL-P17-09** | 根因可能不是特征宽度，是**这个市场在这个频率上只有一个因子**。5 个信号的机制性死因全指向这里 | 问题定义 | 第一～五轮 | P1 | **UNKNOWN** | O-1 恰好是判别实验：资金费是唯一非价格信息源，它也阴性则该假设升为主要解释，下一步转**频率 / universe**，而不是数据源。进 Scope Firewall 的重开条件 |
| KILL-P17-10 | 约 280 候选 × 约 40 s ≈ 3 h；操作者等不及改回 0.15「求可比」 | 规则 4 | `u3_attrib.py` 计时 | P2 | **ACCEPTED** | 批处理，`--out` 进仓库 |

### 6.4 Pre-Mortem

| 失败原因 | 触发机制 | 预警 | 预防 |
| --- | --- | --- | --- |
| 「找到的候选」是 280 个里的幸运最大值，validate 一跑就死 | 全样本比基线 | validate FAIL | KILL-01 / D-P17-04 |
| 阴性之后「窗口选错了」，改网格再跑 | 事后调整搜索空间 | `declared_trials` 跳变 | 规则 3 + KILL-08 的 search ledger |
| 阴性被读成「数据源也没用」 | 过度外推 | — | KILL-09 写清：阴性支持的是「单因子市场」假设，**不是**「数据源无用」 |

### 6.5 Inversion

| 要让它失败就 | 当前是否存在 | 反向控制 |
| --- | --- | --- |
| 只申报最后一次 mine | **是**（机制存在） | KILL-08 |
| 0.30 的候选比 0.15 的基线 | **已发生过**（本文件初稿） | 规则 4 |
| `uses_funding` 留 False | **是**（当前代码） | KILL-07 / T-P17-03 |
| 能力检查读面板 | 尚未 | KILL-04 / D-P17-02 |

### 6.6 Final Kill Decision

| 问题 | 结论 |
| --- | --- |
| 最强反方 | KILL-02：资金费空间的显然角落已探明，搜索的边际主张薄 |
| 未关闭 P0 / P1 | **P0：0。P1 OPEN：0**（4 MITIGATED 改契约、3 ACCEPTED、1 CLOSED、1 UNKNOWN 由实验裁决） |
| 被推翻或 UNKNOWN 的 P0 Claim | 无（C-001/C-002 REFUTED 是对**原方案**的，O-1 不依赖它们） |
| 必须改变的 Contract | 五处：Falsifier 改走 validate（01）；预期阴性入预登记（02）；能力检查改为搜索空间参数（04）；基线同次运行重算（06）；`needs_funding` 派生加测试（07） |
| 最终建议 | **Weak GO** — O-1 作为有边界的证伪实验：一次运行，预登记停止条件，结果决定下一步是数据源还是频率/universe |

**G6：PASS**（对带五处契约变更的 O-1）。

---

## 7. Phase 8：Scope & Priority

### 7.1 MoSCoW

| 分类 | 内容 | 理由 |
| --- | --- | --- |
| **Must** | `Funding` 叶节点（`Dim.RETURN`）；`Expr.reads_funding()` 派生 `to_signal` 的 `uses_funding`；`include_funding` 搜索空间参数；资金费族，预算 ≤ 60 个新表达式；mine 报告记全运行参数；`--baseline` 同次运行；恒等性测试 | 缺任何一项，实验产出的证据就带着本轮刚纠正过的缺陷之一 |
| **Should** | `--baseline` 顺带记每候选对基线的相关与边际 Sharpe | 问题是「第二本**不相关**的书」，边际 Sharpe 才是目标量；基线已在同次运行里算出，增量约十行 |
| Could | — | — |
| **Won't** | 第 8–12 条五个节点；search ledger（KILL-08）；`_store_fact` 修复（另一会话在做）；任何 LLM 提案者；新数据源；频率 / universe 变更 | 见 Firewall |

### 7.2 Scope Firewall

| Out-of-Scope 项 | 原因 | 重开条件 | 加入后挤出 |
| --- | --- | --- | --- |
| 新数据源（OI / 现货 / 订单簿） | O-1 结果未出 | **C-003 REFUTED**（O-1 找到了东西 → 特征宽度确实是瓶颈 → 加更多特征） | O-1 本身 |
| 频率 / universe 变更 | KILL-09 未判 | **C-003 SUPPORTED**（O-1 也阴性 → 「单因子市场」升为主要解释） | 数据源工作 |
| 第 8–12 条节点 | 各自独立提案 | 每个单独预登记，各自的 `declared_trials` 各自申报 | — |
| search ledger | 既有设计缺口，非 O-1 引入 | 独立提案 | — |
| LLM 提案者 | C-002 REFUTED | A-004 有答案（自适应提案的试验计数） | — |
| `_store_fact` 修复 | 另一会话 | — | — |

两条重开条件互斥，由同一个实验裁决。这是 O-1 的全部价值所在。

### 7.3 Decision Log

| ID | 决策 | 备选 | 选择理由 | 放弃理由 | 可逆性 |
| --- | --- | --- | --- | --- | --- |
| D-P17-01 | `Funding` 取 `Dim.RETURN` | `RATIO` | 与收益同量纲：`Ratio(Funding, Vol)` 合法即风险调整 carry，`Sum(Ret, Funding)` 合法即含 carry 的总收益 | RATIO 会让 `Squash(Funding)` 直接合法，把有量纲的量当无量纲压 | 一行 |
| D-P17-02 | `include_funding` 是搜索空间参数，默认 `True`，CLI 按面板收窄 | 在 `enumerate_candidates` 里读面板 | 保住「枚举确定、不碰数据」，`_resolve_mined` 不变 | KILL-04 | 一行 |
| D-P17-03 | 预期结果阴性，写进预登记 | 不写 | KILL-02；不写就会在阴性之后「再试一个网格」 | — | — |
| D-P17-04 | Falsifier 经 `validate` 不经全样本 | 全样本比基线 | KILL-01 | — | — |
| D-P17-05 | top-k 按对基线的**边际 Sharpe**选，k = 3，预先声明 | 按全样本 Sharpe | 目标量是分散化，不是绝对水平 | — | — |
| D-P17-06 | 资金费族三个形状假设，预算 ≤ 60 | 更大的网格 | 控制 `declared_trials`；每个形状说一件其他形状说不了的事 | — | — |

D-P17-06 的三个形状（**族的定义是这三条，网格只是参数**）：

1. **风险调整 carry ±**：`Squash(±Ratio(Funding(w), Vol(v)), s)` 与 `cs_rank(±Ratio(Funding(w), Vol(v)))`。这是对照角——第四轮的 carry 用 rank 模式跑过，预期死
2. **动量 × carry ±**：`Squash(±Mul(Ratio(Ret(h), Vol(v)), Ratio(Funding(w), Vol(v))), s)`，h ∈ 周级。负号那一侧是连续版的 crowding；正号是「顺着资金费的动量」，没人写过
3. **动量 + carry**：`Squash(Sum([(½, Ratio(Ret(h), Vol(v))), (½, Ratio(Funding(w), Vol(v)))]), s)`。含 carry 的总收益动量——只有 `Dim.RETURN` 让它合法

窗口取资金费结算的整数倍（1h bar 上 8 的倍数）：24 / 72 / 168。精确网格在实现时定，由 T-P17-07 的预算守着，并按 F-4 写进报告。

### 7.4 Decision Compression

| 字段 | 冻结内容 |
| --- | --- |
| 一句话问题 | 当前面板上的每个候选都与 tsmom 同源，第二本书找不到 |
| 核心用户与场景 | 操作者；研究工具，离线 |
| 推荐方案及相对优势 | O-1：一个叶节点打开资金费方向，一次预登记搜索裁决 C-003；比数据源便宜两个量级，比「凭现有证据判 SUPPORTED」多一次真实测量 |
| In / Out | §7.1 |
| 关键 Claim / Kill / Risk | C-003；KILL-01 / 02 / 04 / 06 / 07 / 09 |
| 成功 Metric | M-P17-01 |

---

## 8. Phase 9：Delivery Contract

### 8.1 预登记规则（冻结，先写后跑）

1. **恒等性**：`enumerate_candidates(include_funding=False)` 的 hash 集合 == 变更前 HEAD 生成的 225 个 hash 固定文件，逐位
2. **分母诚实**：报告 `scored == evaluated`；`errored` 单列且必须为 0
3. **提升门槛**：任何资金费候选 `validate --prior-trials <evaluated>`，不是 225
4. **口径对齐**：`vol_target 0.30`，funding 开，tsmom 基线同次运行、registry 当前参数
5. **报告自足**：只读 JSON 可重建命令行
6. **预期阴性**；top-k = 3 按边际 Sharpe，预先声明；k 用完即停，不从同一次搜索再提

### 8.2 PRD Contract（研究工具，压缩）

| 区块 | 内容 |
| --- | --- |
| 背景与目标 | E-007/8/9：候选同源。目标：打开资金费方向，一次搜索裁决 C-003。**非目标**：找到 alpha（D-P17-03） |
| 需求范围 | §7.1 |
| 用户故事 | US-P17-01：作为操作者，我在 0.30 上跑一次带资金费族与 tsmom 基线的 mine，得到一份能自我复现的报告，从中按边际 Sharpe 选 top-3 去 validate |
| 规则与流程 | §8.1 |
| 异常与边界 | 面板无 funding → 搜索空间自动收窄到 225，报告记 `include_funding: false`，零 error 行；funding 候选被提升 → D-023 门生效（实盘已有 `funding_history`，tsmom crowding 依赖它） |
| 成功指标 | M-P17-01 / 02 |
| 风险依赖 | 另一会话的 `_store_fact` 修复**不阻塞**：mine 报告用自己的 `run` 块，不依赖 manifest 的 funding 事实；但修好之前报告的 `dataset.funding` 仍是 0，报告里注明 |
| 待决 | 无 P0 |

### 8.3 Development Contract

| 分类 | 说明 |
| --- | --- |
| Ownership | Engineering / Test / Approval / Runtime / Learning Owner 均为操作者（单人）。Agent 写代码与测试；**不提交、不跑 validate、不写 ledger** |
| 边界 | **改**：`starquant_alpha/mining/expr.py`、`starquant_alpha/mining/search.py`、`starquant_cli/research_cmd.py`（仅 `research_mine` 与 `_resolve_mined`）、`tests/alpha/`。**不改**：`features.py`、`panel.py`、`signals/`、`validation/`、`starquant_live/`、`manifest.py` |
| 不可破坏规则 | 架构导入方向；`enumerate_candidates` 不碰数据；现有 225 hash 逐位不变；`trials.jsonl` 零写入；`to_signal` 产出仍是普通 `SignalSpec` |
| 数据 | 读 `panel.funding`（已有）；无新存储、无迁移 |
| API | `Funding(window)`：`Dim.RETURN`，`lookback() == window`（U-2：`min_periods=1` 会提前出数，报 `window` 是保守方向），`evaluate` = `features.funding_per_bar_to_8h(_required(panel, "funding", "funding"), window)`；`Expr.reads_funding() -> bool`（基类按子节点递归，`Funding` 返回 True）；`enumerate_candidates(*, include_funding: bool = True, funding_windows=(24, 72, 168), ...)`；`research mine --baseline <id>`；payload 新增 `run` 块（funding / execution / cost / portfolio / min_history_bars / include_funding / universe_mode / profile / costs 路径）与 `baseline` 块（strategy / params / sharpe / net / mdd） |
| 状态机 / 权限 / 安全 / 迁移 | N/A（离线研究 CLI，无外部写入） |
| 性能与容量 | 约 40 s/候选 × 约 280 ≈ 3 h；批处理；`--out` 默认进仓库 |
| 依赖与降级 | 面板无 funding → `include_funding=False`，不报错、不静默丢候选（F-1） |
| 可观测性 | stdout 打印 `include_funding` 与 `evaluated`；报告 `scored` / `errored` 计数 |
| 发布 | 无 flag；合并即生效 |
| 回滚 | 删 `Funding` 类与族生成器；T-P17-01 保证回滚后 225 逐位不变 |
| 验收 | §8.5 |

### 8.4 Test Contract

| Test ID | 类型 | 前置 | 断言 |
| --- | --- | --- | --- |
| T-P17-01 | 恒等性 | fixture：**变更前 HEAD** 生成的 225 个 hash（先生成再动代码） | `enumerate_candidates(include_funding=False)` 的排序 hash 列表 == fixture |
| T-P17-02 | 量纲 | — | `Funding(24).dim == Dim.RETURN`；`Ratio(Funding(24), Vol(48))` 合法；`Ratio(Funding(24), VolumeRatio(12))` 抛 `ExprError`；`Squash(Funding(24), 1)` 抛（RETURN 不是 RATIO）；`Funding(0)` 抛 |
| T-P17-03 | `uses_funding` 派生 | — | 含 `Funding` 的树 → `to_signal(c).needs_funding({}) is True`；不含 → `False` |
| T-P17-04 | lookback | — | `Funding(w).lookback() == w` |
| T-P17-05 | 缺字段 | `funding=None` 的面板 | `Funding(24).evaluate(panel)` 抛 `ExprError`，消息含 `"funding"` |
| T-P17-06 | 语义 | 合成面板 | `Funding(w).evaluate(p)` 与 `features.funding_per_bar_to_8h(p.funding, w)` 逐位相等 |
| T-P17-07 | 族预算 | — | `evaluated(True) − evaluated(False) ≤ 60`；每个新增候选 `expr.reads_funding()` 为 True |
| T-P17-08 | F-1 守卫 | 无 funding 面板 | `research mine` 走 `include_funding=False`：`evaluated == 225`，`errored == 0` |
| T-P17-09 | 解析 | — | `_resolve_mined("mined_<某 funding hash>")` 成功注册 |
| T-P17-10 | 报告自足 | — | payload `run` 含全部列出的键；`baseline` 含 strategy / params / sharpe |
| T-P17-11 | 边际 | `--baseline` | 每候选行含 `corr_to_baseline` 与 `marginal_sharpe` |

### 8.5 Acceptance Contract

| ID | 层级 | 前置 | 操作 / 观察 | 客观预期 | 证据 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- |
| AC-P17-01 | Functional | 分支 | `pytest -m "not network"`、`ruff format --check`、`ruff check`、`mypy` | 全绿，T-P17-01 ～ 11 在内 | CI 输出 | 不合并 |
| AC-P17-02 | Scenario | 主 checkout，0.30 profile，funding 数据在盘 | `starquant research mine --universe pit --baseline tsmom --from 2021-01-01` | 报告落 `reports/research/`；从 JSON 重建命令行；`scored == evaluated`；`errored == 0`；`baseline.sharpe` 存在 | 报告 JSON + sha256 | 报告不合格则不进入 AC-03 |
| AC-P17-03 | Hypothesis | AC-02 通过 | 按 D-P17-05 选 top-3，各跑 `validate --prior-trials <evaluated> --universe pit` | 按 M-P17-01 裁决 C-003；三份 validate 报告与 ledger 行 | `reports/research/` + `trials.jsonl` | 结果无所谓成败，**裁决本身就是产物** |

### 8.6 Source Trace Matrix

| Delivery ID | Problem / Evidence | Claim | Decision | Gate / Kill | Scope | Test | Metric |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DL-P17-01 `Funding` 节点 | §3 第 13/14 条；E-002 | C-003 | D-P17-01 | KILL-04/07 MITIGATED | Must | T-02/04/05/06 | M-P17-01 |
| DL-P17-02 `reads_funding` → `uses_funding` | E-001；F-2 | — | — | KILL-07 | Must | T-03 | M-P17-02 |
| DL-P17-03 `include_funding` + 资金费族 | E-007；F-1 | C-003 | D-P17-02/06 | KILL-04 | Must | T-01/07/08/09 | M-P17-02 |
| DL-P17-04 报告 `run` 块 | F-4；E-012 | — | — | — | Must | T-10 | — |
| DL-P17-05 `--baseline` + 边际 | KILL-06；§3 Problem 重述 | — | D-P17-05 | KILL-06 | Must / Should | T-11 | M-P17-01 |

### 8.7 Delivery Gate（G7）

- [x] G0–G6 无阻塞当前范围的 FAIL / UNKNOWN（G3 的 FAIL 是对原方案；O-1 的相对价值 Adequate）
- [x] 未关闭 P0 Kill = 0
- [x] User Story、Scenario、Acceptance Input 已产出（§8.2、§8.5）
- [x] In / Out Scope 与 Firewall 明确（§7.1–7.2）
- [x] 数据、API、状态、依赖明确（§8.3）；权限 / 安全 / 迁移 N/A 有理由
- [x] 主路径、异常、降级、回滚明确
- [x] 四类契约一致
- [x] P0/P1 Delivery Item 均有 Source Trace
- [x] Owner 与人类确认点明确：提交、跑 validate、写 ledger 三件事由操作者执行
- [x] 敏感数据 N/A
- [x] Learning Contract 有基线、阈值、窗口、失败动作（§9）

**G7：PASS。**

---

## 9. Phase 10：Learning Loop

### 9.1 Validation Plan

| Metric ID | Claim | 指标 | 基线 | 成功阈值 | 窗口 | 停止条件 | 失败动作 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M-P17-01 | C-003 | top-3（按边际 Sharpe）各自的 `validate` 判定 | 0 / 225 PASS | ≥ 1 个 PASS 或 WEAK_PASS → **C-003 REFUTED** | 一次 mine + 三次 validate | k 用完即停 | 0 个 → **C-003 SUPPORTED** → 按 Firewall 重开「频率 / universe」，不重开数据源 |
| M-P17-02 | F-1 | 报告 `scored == evaluated` | — | 相等 | 每次 mine | 不等即阻塞 | 修，不跑 AC-03 |

### 9.2 Experiment Design

| Experiment ID | 要证伪的 Claim | 最小方法 | 对象 | 变量 / 对照 | 指标 | 通过阈值 | 停止 | 局限 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EX-P17-01 | C-003 | 一次预登记搜索 | 时点 205 币，0.30，funding 开 | 变量：资金费族（≤ 60）；对照：225 非资金费 + tsmom 基线同次运行 | 边际 Sharpe → top-3 → validate | ≥ 1 过 | k = 3 | 单次搜索的最大值偏差由 validate 的 `--prior-trials` 处理；**不能区分 KILL-09 的两个解释**——阴性只说明资金费方向没有，「单因子市场」的判定靠 Firewall 里的下一个实验 |

### 9.3 Post-Launch Review（待填）

| 原 Claim | 实际结果 / Evidence | 支持 / 推翻 | 偏差原因 | Decision / Scope 更新 | Pattern |
| --- | --- | --- | --- | --- | --- |
| C-003 当前特征面板已被搜尽 | AC-P17-02：carry 42 个候选 **0 个正边际**（最好 −0.1128）。AC-P17-03：边际前三各跑 `validate --prior-trials 267`，**3/3 FAIL**，ledger +3 行 | **支持** | — | **C-003 SUPPORTED**；§7.2 Firewall 打开「频率 / universe」，数据源仍关 | 最好那个候选（OOS 0.86）过了每一道硬门，只死在 D-028 的选择缩减上——而阈值 1.27 **几乎全部是那 267 次搜索的代价**（n=1 时阈值为 0）。`search.py` 那条规则第一次在真实候选上咬合 |
| D-P17-03 预期阴性 | **兑现。** carry 轴 0/42 正边际，中位 −0.7416 | 支持 | — | — | 预登记预期为阴性的实验，兑现时不需要重新解释 |
| KILL-09 单因子市场 | 仍 UNKNOWN。carry 阴性把它往「主要解释」推了一步，但 267 个里仍有 3 个正边际（全是动量、全在原有 225 里），所以「只有一个因子」并未被这次实验确立 | 未判 | — | — | — |
| （计划外）P14 结论的第二条限定 | 按全样本 Sharpe 的第 1 名与 tsmom 相关 **0.461**、第 3 名相关 **0.915**；按边际的第 2 名在 Sharpe 排序里只排第 13 | 新增 | P14 按全样本 Sharpe 排序，而问题问的是「第二本**不相关**的书」 | E-013 之外新增一条同量级限定 | **排序键和 `vol_target` 一样，是结论的一部分**——KILL-P17-01 的机制在这份数据上被直接看见 |

---

## 10. Final Decision 与质量评分

**Final Decision：Weak GO**——O-1 作为有边界的证伪实验。授权范围：写 DL-P17-01 ～ 05 的代码与测试；**提交、跑 validate、写 ledger 由操作者执行**。

| 维度 | 分 | 说明 |
| --- | --- | --- |
| 问题真实性 | 5 | 候选同源有 E1 读数（相关 0.47、边际 −0.08） |
| 证据充分度 | 4 | E1 为主；C-003 按设计未测 |
| 根因清晰度 | 3 | KILL-09 未判：特征窄 vs 单因子市场 |
| 战略一致性 | 4 | alpha 投入目标 90%，这是 alpha |
| 相对价值与经济 | 4 | 比数据源便宜两个量级；预期阴性已计入 |
| 方案可行性 | 5 | 单文件叶节点 + 两个现成函数 |
| 范围收敛度 | 5 | Firewall 两条互斥重开条件 |
| 执行可交付性 | 4 | 11 项测试可写；3 h 批处理 |
| 上线可验证性 | 4 | M-P17-01 由 validate 裁决，不由全样本 |
| 对抗生存 | 4 | 10 Kill，0 OPEN P0/P1；1 UNKNOWN 由实验裁决 |
| **合计** | **42** | 映射到 GO 档；取 **Weak GO** 因为授权的是一次实验而非一个功能 |

---

## 11. 交付后的对抗核验：契约修正与偏离

§8 的契约冻结之后交付了一次，然后对**已交付的东西**做了一次独立核验（五路并行，含变异测试：改坏生产代码看套件红不红）。结果是首轮交付有一个真缺陷、四个空过的测试、两条没被兑现的预登记规则。本节是修正记录——一条冻结后发现不可满足的规则要在记录上被替换，不能默默绕过。

### 11.1 一个真缺陷：防 KILL-027 的守卫自己就是 KILL-027

首版 F-1 守卫写的是 `if include_funding and not funding`——判 **CLI 旗标**。`--funding` 打开而数据根没有资金费归档时，`_load` 返回全零框而不是 `None`：旗标说「要了」，`panel.funding is not None` 说「到了」，两个都不是要问的那个问题。

August fixture 上实测（`--funding`，归档不存在）：**evaluated 267、42 个 carry 候选全部保留、其中 36 个从不交易、全部计入 `declared_trials`，而报告记录 `run.include_funding: true`**——一份断言 carry 家族被搜过、而它跑在常数上的证据。踩到它的是默认路径：`--funding` 与 `--include-funding` 都默认打开。

后果具体：AC-P17-02 若在资金费覆盖不全的数据根上跑，会得到**假的 C-003 SUPPORTED**，把工作送进 Firewall 错误的那一支。

**首版还把契约语义换掉了。**§8.2 与 D-P17-02 要的是「面板无 funding → 搜索空间自动收窄到 225，**不报错**」，首版实现成了 `raise`。收窄已恢复，谓词改为数真有结算的币数，`run` 块同时记录搜了什么 / 要了什么 / 依据是什么。修复见 `692e499`。

### 11.2 两条预登记规则的修正

| 规则 | 冻结原文 | 判定 | 处置 |
| --- | --- | --- | --- |
| 2 | 报告 `scored == evaluated`；`errored` 单列且必须为 0 | **不可满足** | **修正**（见下） |
| 6 | top-k = 3 按边际 Sharpe，预先声明 | 未实现（仍按全样本 Sharpe 排序） | **实现**，`caaa923` |

**规则 2 为什么不可满足**：`enumerate_candidates` 里 `evaluated += 1` 在 complexity 与 lookback 两道 cap **之前**自增，所以被 cap 丢掉的候选必然计入 `evaluated` 而永远不进 `scored`。任何设了 cap 的运行都违反它——这是冻结时没想到的，不是实现的偷懒。

**修正后的形式**（保住原意「没有候选无声消失」，且可达）：

```
evaluated == too_complex + too_long + scored + errored + never_traded
```

现在算出来、记进 `outcomes`、并在不成立时**拒绝写报告**——一份自己的算术都不闭合的证据不该落盘，而 `--prior-trials` 正是整个提升门用来定标的那个数。这给了 M-P17-02 一个此前只有陈述没有机制的强制点。

**规则 6 为什么重要**：KILL-P17-01 说的正是按全样本 Sharpe 挑会产出假的 C-003 REFUTED——几百个候选里的最大值既是噪声极大值，又通常来自与在跑的书最相关的那个。现在 `--baseline` 在场时排序键换成 `baseline_marginal_sharpe`，`run.ranked_by` 记录用了哪个键。

### 11.3 四个空过的测试

变异测试证明：改坏生产代码，351 项套件照样全绿。四处，按危害排序。

| 变异 | 首轮 | 现在 | 修法 |
| --- | --- | --- | --- |
| 删掉 `yield Squash(interaction, …)`——42 个里的 6 个，**一个宣称形状的整条长臂** | 全绿 | 红 | 走树的完整人口普查，计数由网格推导 |
| `never_traded` 硬编码成 0 | 全绿 | 红 | 合成 store 让 `takerbuy` 恒为 0，把第三个桶跑成非零 |
| 删掉 `--baseline` 资金费守卫 | 全绿 | 红 | 用 tsmom（registry 带 `crowding_window`）的拒绝测试 |
| 库 `max_complexity` 改回 8 而 CLI 仍是 10 | 全绿 | 红 | 断言两个常量相等 |

第一条为什么漏得最深：断言用 `"-1 *" not in t` 区分正负臂，而 `Mul.canonical` 按 hash 排序操作数，六棵负号树里有一棵把 `-1` 排到了右边，于是它满足「正臂」谓词。**字符串前缀从来就不是树的性质。**修复见 `af5027d`。

### 11.4 记录在案的其余偏离（不改，只登记）

| 偏离 | 说明 |
| --- | --- |
| 测试 ID 被静默重编号 | 交付文件里 11 个标签中 9 个与 §8.4 含义不同；对照表见 §12.4。不重编号，因为 grep 契约 ID 找到错测试的危害已由 §11.3 补齐覆盖消除 |
| 逐候选字段改名 | 契约写 `corr_to_baseline` / `marginal_sharpe`，实现是 `baseline_correlation` / `baseline_marginal_sharpe`，另加未承诺的 `baseline_bars`。实质已交付；改名让它们与 `baseline_*` 前缀成组 |
| `max_complexity` 8 → 10 | 契约全文未提这个 cap。必要（负号 momentum×carry 是十节点树）且证明惰性，但读契约的人会意外 |
| 编辑边界超出 | §8.3 的「改」清单外还动了 4 个文件：`mining/__init__.py`、`test_source_budget.py`、`test_cli_offline.py`、`tests/fixtures/mining_baseline_hashes.json`。各自都站得住（固定文件是 T-P17-01 的前提，行数守卫是强制的），但都不在冻结清单里 |
| 七项未请求的新增 | `outcomes` 块与其 stdout 提示、带 stamp 的文件名、两条拒绝路径、两个额外枚举参数（`funding_horizons` / `funding_scale`）、markdown 表新增两列、逐行 `baseline_bars` |
| 交互 horizon 半数低于声明尺度 | D-P17-06 写「h ∈ 周级」，实现取 (72, 168)；168h 是一周，72h 是三天 |

---

## 12. 实际交付

分支 `feat/mining-funding-node`，从 `db9efd9` 分出，六个提交：

| 提交 | 内容 |
| --- | --- |
| `be963ad` | `Funding` 叶节点、`Expr.reads_funding`、`_funding_family`、`run` 块、`--baseline` |
| `692e499` | F-1 守卫：判面板不判旗标；恢复契约要的收窄语义 |
| `af5027d` | 四个变异证明为空过的测试洞 |
| `caaa923` | 预登记规则 2（修正后）与规则 6 |
| `af104bc` | cap 抬升的理由写反了——结论对，原因是实测的反面 |
| `04e4c02` | baseline 块补上 KILL-P17-06 要的 `params` / `net_return` / `max_drawdown` |

`pytest -m "not network"` 357 项通过，`ruff format --check`、`ruff check`、`mypy`（81 文件）全绿。

### 12.1 搜索空间：225 → 267

D-P17-06 写的是「精确网格在实现时定」，定成：

| 参数 | 取值 |
| --- | --- |
| `funding_windows` | (24, 72, 168) —— 全是 8 的倍数，无窗口跨半个结算 |
| `funding_horizons` | (72, 168) |
| `funding_scale` | 1.0（交互与求和两形状共用的标量） |
| 复用 | `vol_windows[0] = 48`（两条腿同一个）、`scales = (0.5, 1.0, 2.0)`（仅 squash carry 用） |

**42 个表达式，42 个不同 hash，与既有 225 零重叠**，预算 ≤ 60 达标。完整人口普查（由测试逐格断言，不是描述）：

| 形状 | 长臂 | 短臂 | 小计 |
| --- | ---: | ---: | ---: |
| squash 风险调整 carry | 9 | 9 | 18 |
| cs_rank 风险调整 carry | 3 | 3 | 6 |
| 动量 × carry | 6 | 6 | 12 |
| 动量 + carry | 6 | 0 | 6 |
| **合计** | **24** | **18** | **42** |

动量 + carry **没有短臂**——那条腿的负版通过形状一的短臂可达。复杂度分布 `{4: 12, 6: 12, 8: 12, 10: 6}`，最大回溯期 169 根 bar。

### 12.2 `max_complexity` 8 → 10

十节点的那 6 棵是负号 momentum×carry——负号本身要两个节点。抬升是惰性的，理由是**单调性**：放宽上界只会放进树，不会丢掉树，而既有的没有一个超过 8。

**headroom 恰恰是没有的**：pre-carry 那 225 个的复杂度分布是 `{2: 30, 3: 30, 4: 45, 5: 45, 8: 75}`——三分之一恰好坐在旧 cap 上，8 是最大的一档。首版 docstring 写「nothing existing sits near the cap」是实测的反面，已改（`af104bc`）。

留在 8 的代价实测：`evaluated 267 / kept 261 / too_complex 6`——**六棵被计入 `declared_trials` 然后丢弃**，最差的两头都占。

恒等性由 T-P17-01 在**两个 cap 下各枚举一次**守着，要求同样 225 个 hash、同样顺序。

### 12.3 报告现在能自我复现

P14 那份 shortlist 记了数据集清单却没记自己的 `--funding`、成本模型、execution、组合参数，所以「那次到底什么口径」要靠四臂暴力复算才反推得出（E-012）。现在 `run` 块记 20 个键，`outcomes` 记五个计数并强制闭合，`baseline` 记策略 / 参数 / sharpe / 净收益 / 回撤，文件名带 stamp。

### 12.4 测试 ID 对照表

交付文件的标签与 §8.4 的契约 ID 不是同一套，对照如下（避免 grep 契约 ID 找到错的测试）：

| 契约 §8.4 | 交付文件里的名字 |
| --- | --- |
| T-01 恒等性 | `test_the_existing_search_space_is_bit_for_bit_what_p14_recorded` |
| T-02 量纲 | `test_funding_is_a_return_so_every_shape_must_divide_it_by_volatility` |
| T-03 `uses_funding` 派生 | `test_the_compiled_spec_declares_the_funding_it_actually_reads` |
| T-04 lookback | 并入 T-02 的断言，无独立测试 |
| T-05 缺字段 | `test_a_candidate_refuses_a_panel_that_carries_no_funding` |
| T-06 语义等于共享 feature | `test_the_leaf_is_exactly_the_shared_feature` |
| T-07 族预算 | `test_the_funding_family_is_on_by_default_and_costs_what_was_pre_registered` |
| T-08 F-1 守卫 | `test_mine_narrows_the_space_instead_of_searching_a_family_the_panel_cannot_answer` |
| T-09 解析 mined 资金费 hash | `test_a_mined_carry_id_still_resolves_to_a_signal` |
| T-10 报告自足 | `test_mine_records_the_parameters_of_its_own_run` |
| T-11 逐候选边际 | `test_mine_compares_every_candidate_against_a_named_baseline` |
| （契约外新增） | 人口普查、8 的倍数窗口、枚举确定性、两个 cap 常量相等、`never_traded` 非零、baseline 资金费拒绝、记账不闭合即拒写 |

### 12.5 仍然没做

- **AC-P17-02 与 AC-P17-03 均已跑完**（2026-09-06）。裁决取到：**C-003 SUPPORTED**，ledger 135 → 138。详见 `RESEARCH_LOG` P17 §七、§八。
- **§7.2 Firewall：「频率 / universe」已打开，「数据源」仍关。** 这是两条互斥重开条件里的后一条被选中。
- **KILL-09（单因子市场）仍 UNKNOWN**：carry 阴性加这三个 FAIL 把它往主要解释推了一步，但重开条件只授权换频率 / universe 去测它，没有确立它。
  - 后记（2026-09-06）：频率那一臂已跑，**P19 / C-004 REFUTED**（日线 238 个候选，top-3 全 FAIL），ledger 142 → 145。KILL-09 仍 UNKNOWN——只是又往主要解释推了一步，universe 宽度与数据源两条仍未测。详见 `RESEARCH_LOG` P19 判定节。本节其余部分是 P17 当时的记录，不回改。
- **研究路径的 `needs_funding` 未强制**：`AlphaModel.targets` 有检查，`evaluate` 没有，所以 `research backtest --strategy tsmom --no-funding` 仍会静默跑一个 crowding 修正器失效的 tsmom。本轮只关掉了 `--baseline` 这一条路径，另七个 research 命令仍敞着，已另立任务。
- **提交正文里三个不可从提交本身核验的数**：「5 of 267 never traded」是窗口相关的（四个窗口读到 5/5/6/9，5 恰是交集即下界）；「vanished with no trace」过了（改动前那行在 `candidates` 里带 `sharpe: null`，缺的是计数与 stdout）；P14 那份 committed 报告里 never-traded 是 0，所以正文对照的那个现象在仓库证据里不存在。**这三条不应被当作已确立的事实引用。**
