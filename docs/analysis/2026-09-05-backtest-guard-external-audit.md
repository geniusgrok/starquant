══════════════════════════════════════════
   策略体检报告 · backtest-guard
══════════════════════════════════════════
受检对象：StarQuant（Binance USDⓈ-M 永续，demo/testnet）
扫描：starquant_alpha / starquant_data / starquant_exchange / starquant_live  约 11k 行
（已排除 worktrees/ 下的分支副本，避免重复计数）

总评：🔴 致命 0 项 · 🟠 高危 1 项 · 🟡 中 1 项 · 🔵 低 1 项（含逻辑项 2 项）
判语：「工程纪律高于本清单覆盖的绝大多数检测点。
      仅剩的两处缺口有同一个形状——**系统已经知道，但没有让任何仪表说出来**，
      而这正是本仓库自己在 D-037 / P13 立下的标准。」

────── 第一遍 · 工程审查 ──────

[🟠 高危] 参与率上限在实盘生效，但不在回测里，且不在护栏重放中  ※ 作者已披露
  位置：starquant_live/rebalancer.py:23,154（max_participation，仅对加仓单）
        config/live.demo.yaml:24（max_participation: 0.02 —— 已启用）
        starquant_alpha/backtest.py:134（成本恒为 turnover_bps/10000，与下单量无关）
        starquant_alpha/backtest.py:151（_replay_book_guards 重放 3 个护栏）
  问题：D-004 建立 _replay_book_guards 的理由是"回测与实盘的护栏不能漂移"，
        它重放了 max_weight / max_gross / daily_loss_pause——**参与率上限是
        唯一没被重放的实盘约束**。回测据此按目标权重全额成交，实盘会对加仓单
        截断并记 PARTICIPATION_CAPPED。registry 记录的换手为 225.6，该差异不小。
  作者已披露，且已显式 scope out: config/live.demo.yaml:31-38 不只提到这件事，
        而是完整写下了后果——vol_target 的 k 在 {1,1.5,2,2.5,3,4,5} 上被实测为
        "net Sharpe EXACTLY unchanged"，并明确指出"That identity is an arithmetic
        property of the backtest ... proves nothing about a world with market impact
        ... k must be re-derived under an impact-aware cost model. **That is recorded
        as out of scope, not as done.**"
        因此本项不是"未覆盖的缺口"，而是**已识别、已定后果、已挂账的待办**。
        严重度按已披露规则不降级（回测分数仍不是实盘会拿到的分数），但性质从
        "作者不知道"改为"作者知道并已决定暂不做"。

  【2026-09-05 更正】本条初版写"该上限只截断加仓、不截断减仓，构成单向滞后"——
        **该判断有误**。rebalancer.py:128 的 `closing = abs(target_notional) < 1e-9
        and current_qty != 0.0`, 而 :154 的条件是 `not closing`，因此**部分减仓
        同样被截断**，豁免的只有*完全平仓*。据此，原先推出的"信号快速切换时的
        单向系统性滞后"不成立。
  实际仍成立的不对称：**全身而退永远做得到，任何部分调整都不保证。** 上限绑定时，
        书会滞留在它调不掉的仓位上，而唯一保证可执行的动作是决定走平。

  处置(2026-09-05): 按操作者决定，做成**诊断仪表**而非改动构造(M-017)。完整的
        冲击成本模型与 k 重推仍按 config 的记载留在 scope 外。

  【已测量】tsmom / pit universe / 49,024 bars / max_participation 0.02 / window 24。
        每一行都断言了 net Sharpe 1.7087 与基线逐位相同——仪表不动 book。

          资金 (USDT)    被拒绝的目标换手    绑定 bar 数    占全部 bar
          ----------------------------------------------------------------
             1,000            0.00%              0          0.00%
            10,000            0.24%             10          0.02%
           100,000            4.25%            107          0.22%
         1,000,000           28.60%            977          1.99%
        10,000,000           68.01%          2,662          5.43%

  读法：拐点在 10 万到 100 万之间。live.demo.yaml:37 自述"at demo notionals
        (40-800 USDT a clip) that is a good approximation"——**这一点被证实**，
        1,000 USDT 下上限一次都没绑定。约 10 万 USDT 时仍只有 4.25% 的目标换手
        做不掉; 到 100 万就是 28.6%，到 1000 万有三分之二的交易意图无法执行。
  边界（避免这条曲线被读出它没有的含义）：它只统计**参与率上限拒绝掉的部分**，
        不含成交部分所付的冲击成本。真实容量衰减比这条曲线更早开始，所以它是
        容量问题的**下界**，不是容量曲线本身。
  据此的建议：把"k 需要在冲击模型下重推"的触发点定在 10 万 USDT 量级并写进
        config，而不是留作没有数字的待办。

[🟡 中] 回测无强平建模，且全系统无任何强平统计
  位置：starquant_alpha/backtest.py:195 (`equity *= 1.0 + (realised - charge)`)
        全仓库 `liquidat*` 命中 = 0（starquant_alpha / starquant_live / docs 全零）
  问题：max_gross 2.0 是带杠杆的书，但权益路径可以无下界地下滑，没有维持保证金
        触发清零。回测里一条"深度回撤后涨回来"的路径，实盘可能在中途就结束了。
  为何判中而非致命：本系统的结构性缓解是真实的——margin_cap 0.40 (gross 顶格时
        初始保证金 ≤ 权益 40%, D-016)、max_weight 0.15（单币击穿只吃 15% 权益）、
        daily_loss_pause -0.05 远早于强平触发。按此估算，触及强平需在满 gross 下
        损失约 6 成权益。机械套用"无强平即致命"在这里会是假阳性。
  但仍然是缺口：上述是一段**论证**，不是一个**测量**。系统没有任何报告字段统计
        "强平触及次数 / 最小保证金 headroom"，因此"强平不可达"这个结论目前无法被
        任何仪表证伪。这恰好是本仓库自己写下的标准——
        RESEARCH_LOG.md:1280「正确但无人陈述的事实，和未经证明的断言，
        在操作者那里长得一模一样」。
  修复：在 _replay_book_guards 的逐 bar 循环里加一行维持保证金 headroom，报告里出
        `min_margin_buffer` 与 `liquidation_touches`（期望恒为 0）。成本极低，
        且把一段论证变成一个可回归的量。

[🔵 低] 收益缺失的标的仍计提换手成本
  位置：starquant_alpha/backtest.py:120 (`rets ... .fillna(0.0)`)
  问题：某标的当根收益为 NaN 时 gross 记 0，但 delta 仍产生换手、仍扣 7bps。
  影响很小：时点 universe + 新币 720 根 bar 过滤已让这类行数量极少，且方向偏
        保守（多扣成本）。记录备查，不建议为此改动。

────────── 已排除（命中可疑模式，读上下文后判为合法用法）──────────
  ✓ validation/labels.py:12,19 `shift(-horizon)` —— 显式标签构造，且仅供
    research_cmd.py:684,699 的 IC 诊断消费; CPCV/walk-forward 走的是**净收益
    序列**而非监督标签，不存在标签跨边界问题。本轮新增检测点"标签 horizon 跨过
    切分边界"在此命中后读上下文判**合法**——walk_forward.py:3-5 的 docstring
    已明确"signals are causal, folds then slice the resulting net-return series"。
  ✓ walk_forward.py:48-51 —— 正确论证了 walk-forward 中 embargo 无效
    （训练窗永远在测试块之前，其后没有训练样本），而非遗漏。
  ✓ backtest.py:117 `decided.shift(1)` + 默认 open_to_close —— 决策在 t、
    成交在 t+1 开盘，是比 close_to_close 更保守的口径，**不是同 bar 偷价**。
  ✓ panel.py:47 `365.0*86400.0/interval_seconds()` —— crypto 7×24 年化因子
    正确，且由 bar 间隔推导而非硬编码 252/365。
  ✓ backtest.py:35 `turnover_bps=7.0` 默认非零 + :136 按实际结算资金费率
    `executed * funding` 计提 —— 成本与 funding 都已建模，非零成本假设。
  ✓ benchmark_returns:204 自我标注 "zero-cost comparator, not investable"。
  ✓ 全仓库无 bfill / interpolate / center=True / 全样本 scaler fit / shuffle 切分。
  ✓ walk_forward_evaluate:135 对每个参数都记录了 test_score —— 看似有事后
    挑选 OOS 的风险，但 ledger.py 的跨运行追加式 trials ledger（当前 91 次）充当 DSR
    分母、verdict.py:63 强制 OOS Sharpe 越过 deflated 阈值(D-028)，事后挑选
    会被 ledger 计价。判为诊断数据，非缺陷。

────────── 超出本清单、值得记录的良好实践 ──────────
  · ledger.py —— 追加式 trials ledger，按（参数，数据区间，标的数）签名去重并直接
    作为 DSR 的 n_trials。本 skill ② 类只要求"披露试验次数"，这里做成了
    跨运行不可绕过的账。是我在三轮试跑里见过最硬的 p-hacking 防线。
  · verdict.py —— PASS/WEAK_PASS/FAIL 为纯规则函数，阈值是显式入参;
    Newey-West t 统计(D-020)处理自相关; 成本 1×/1.5×/2× 压力。
  · D-023 —— 信号自己声明 needs_funding，拿不到历史时**拒绝启动**而不是
    静默跳过。把一类静默失效变成了启动期的硬失败。

────────────── 偏差影响（方向判断，非收益预测）──────────────
无致命项，当前 OOS 指标可作为讨论基础。两处缺口的方向：
参与率不对称使**实盘表现低于回测**，且偏离集中在信号快速切换时;
强平未建模使**极端路径的尾部风险被低估**——幅度大概率很小（护栏在前），
但目前无任何测量可以确认这一点。具体幅度需重跑确认。

────── 第二遍 · 逻辑对抗审查（非代码证据）──────
[🟠 高危·逻辑] tsmom 的 edge 归属未陈述 —— 但质疑的一半已被本仓库自己否证

  【2026-09-05 更新一】原失效场景"若 tsmom 实为承接杠杆需求，则与 carry 同源"
  **已被 RESEARCH_LOG:86 否证**：carry rank 模式纯信号 5 年毛收益 −6% ≈ 0,
  结论是"资金费率大致等于预期漂移，carry 在这个 universe 里被公平定价"。
  若 tsmom 收的是杠杆需求的钱，carry 应当能赚; 它不赚。这是测量不是论证，
  该分支关闭。edge 归属仍待陈述，但候选空间已显著收窄。

  【2026-09-05 更新二 · 已证实】crowding 停用所依据的证据，早于修复其输入的补丁。

  时序（全部可由 git 核对）：
    09-03 18:18  tsmom-validation-20260903T181803Z 跑出两臂 1.5291（开）/ 1.6450（关）
    09-04 09:47  68f151c 把"重开 crowding"定为**证据问题**
    09-04 10:25  41c2f21 采纳 conviction_mode sign（改 tsmom 构造）
    09-04 20:44  b0cc08a  D-034 —— "half the funding was never charged"
    09-04 21:26  552ca9a  在修正后的 funding 下重跑证据，trials.jsonl **只 +1 条**
                          （param_key 里 crowding_window=0 —— **只重跑了关闭臂**）

  D-034 修的是什么（其 docstring 原文）：Binance 的 fundingTime 落在整点后 1-47 毫秒且
  随年份不均匀（BTCUSDT 2021 年 34% 落整点 vs 2024 年 85%），按等值匹配 bar open
  **把 441,678 行档案的 43.7% 丢进静默的零**，"the share missing differed from fold to fold"。

  为什么这恰好作废两臂比较：crowding 修正的**唯一输入**是趋势资金费率的
  **横截面排名**(signals/tsmom.py:145)。181803Z 里它排的是一张缺了 43.7%、
  且缺失比例逐年逐 fold 漂移的面板。

  复算（scratchpad/verify_crowding_arms.py，固定 146 标的 + 同截止，不写 ledger）:
        crowding off  1.6450（记录）→ 1.6745      关闭臂几乎不动
        crowding on   1.5291（记录）→ **1.8027**   开启臂反转
  三个症状一次解释：开启臂动（输入被污染）、关闭臂几乎不动（它付资金费但不读它做信号）、
  逐 fold 选择当时是 [72,0,72,72,0] 而今天全 72（"缺失比例逐 fold 不同"）。
  已排除的其他解释：标的数(146 vs 205)、截止日、min_train（4000 与 8000 一致）。

  现状：config/alpha_registry.yaml:41 仍以
        "on this evidence the modifier is a small negative (OOS 1.53 with vs 1.65 without)"
        作为 crowding_window: 0 的成文理由，而该证据早于修复其输入的补丁。
  本项**不主张**重开 crowding，只主张：**它被否决所依据的那次比较，在其输入被修正后
  从未重做过。**

  【2026-09-05 已重做 · 操作者授权】`starquant research validate --strategy tsmom --universe pit
  --grid '{"crowding_window": [0, 72]}' --folds 5 --min-train 4000 --purge 50 --cpcv-groups 6
  --prior-trials 30` → 报告 tsmom-validation-20260904T193707Z.json, ledger +2 条（现 61 + 30 申报）。

    逐 fold 选择    [72, 72, 72, 72, 72]   —— 五 fold 全选开启臂（181803Z 当时是 [72,0,72,72,0]）
    OOS Sharpe  1.7647   NW t 4.0266   consistency 1.00
    CPCV        mean 1.795  q05 1.338  负路径 0.00
    PBO         0.136（181803Z 为 0.5484 —— 按 D-020 硬门本会 FAIL）
    成本压力    x1 1.83 / x1.5 1.75 / x2 1.68
    D-028       阈值 1.098 @ 93 次试验;  DSR p 0.2155（报告不否决）
    VERDICT     PASS,  best_params.crowding_window = 72

  与本报告 scratchpad 复算逐位一致(1.7647 / 4.0266)，互为交叉验证。
  PBO 0.55 → 0.14 与"输入被污染"的解释一致：被污染的臂使逐 fold 选择不稳定，而 PBO 正度量此。

  **仍未改动 registry**，且有一处耦合必须先说清：alpha_registry.yaml 当前是
  `crowding_window: 0`，而新证据的 best_params 是 72。KILL-027 的启动门比较 registry 参数
  与报告参数，因此**只重指 evidence 而不改参数会让实盘拒绝启动**——两者必须同一次改动。
  改不改是操作者对实盘配置的决定，不在审计范围内。

  【2026-09-05 已闭环】edge 陈述已写入 starquant_alpha/signals/tsmom.py 的 docstring:
  付的是什么钱 —— 承担散户消化过慢的趋势风险; 对手盘 —— 后知后觉的杠杆多头，
  行情走出后才加仓、反转时被迫出场; 性质 —— **行为性而非结构性**，因此预期会随
  参与者适应而衰减，由走前重验监控而不是假定其持久。
  连同两项证据一并写入：(a) 已测的**否定** —— carry rank 模式 5 年毛收益 −6%,
  故不是伪装的资金费率套利; (b) crowding 修正的逐 fold 表 —— 基线最弱的第 2 fold
  (2022-07→2023-07) 改善最大 +0.40，基线最强的第 5 fold 反而 −0.10，是**尾部缓解**
  的形状而非收益增强。文中明确标注为假设而非发现(逐 fold 规律是事后读出的，5 fold 即
  5 个观测)，实盘裁决交给 M-010 归因。
  本项关闭。

[原始条目] tsmom 的 edge 归属未陈述 —— 待作者答复
  维度：1.2 谁在对手盘
  依据：RESEARCH_LOG 对**被否决**的信号有优秀的机制论证(:130 解释 flow 为何
        结构性失效、:887 解释为何用 Amihud)，说明这个习惯是存在的。但在产的
        tsmom, signals/tsmom.py:1-12 的 docstring 是纯公式，未见"谁在对手盘、
        为什么持续亏给你"的陈述。**未发现 ≠ 不存在**。
  失效场景：时序动量在永续上通常被归为"承接杠杆需求 / 趋势跟随的风险溢价"，
            若实际是前者，则 edge 与资金费率同源，tsmom + carry 的分散是
            表面的; 无陈述则无法判断二者是否在压力期同向失效。
  缓解：补一句 edge 归属并标结构性/行为性，与 crowding_window 的重开决策
        （RUNBOOK.md:46 已列为证据问题）一并处理。

[🟡 中·逻辑] vol_target 0.15 → 0.30 使两个护栏首次可达，但风险预算的验证
  维度：3.1 什么 regime 杀死它
  依据：BookGuardParams docstring 自述——0.15 时"两个护栏都不可达，5.6 年最差
        UTC 日 -3.5% 对 -5% 暂停，gross 从未越过 2.0", 0.30 时变为"约每年一次
        暂停、0.72% 的 bar 被 cap"。即**回测与实盘的护栏分歧在 0.15 时不可见**，
        现在才第一次真正生效。
  失效场景：护栏从"装饰"变为"活跃约束"后，它们的路径依赖(daily_loss_pause 读
            自身重放产生的权益)首次进入有效区间，而这条路径的正确性此前无法
            通过实测被证伪。
  缓解：这一项系统似乎已经意识到（P13 提高目标前先移动了护栏定义），建议确认
        0.30 下的护栏重放已用真实数据回归过，而非仅靠单元测试。

风险评级：🟡 中
  理由：1.2（对手盘）未陈述 → 按规则至少高危; 但 3.1 有明确且已量化的失效
        形态（护栏可达性已测），未同时失明，故整体评为中。无致命工程项。

上实盘资金前，作者必须回答的三个问题：
  1. tsmom 的对手盘是谁? 它与 carry 是否同源（都在收杠杆需求的钱）?
  2. 参与率上限绑定时，换手 225.6 里有多少实际做不掉? 对 OOS Sharpe 的影响?
  3. 满 gross 下的最小保证金 headroom 是多少? 用哪个仪表看?

────────────── 建议优先级 ──────────────
先把参与率上限纳入 _replay_book_guards（唯一影响 OOS 数字的一项）
→ 再加 min_margin_buffer / liquidation_touches 两个字段(成本极低，把论证
   变成测量) → 最后补 tsmom 的 edge 归属陈述。
三项都不阻断当前的 demo/testnet 运行。
══════════════════════════════════════════
