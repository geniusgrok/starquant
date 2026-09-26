# 全系统审查 · 2026-09-17

两遍协议（工程 + 逻辑对抗，`backtest-guard`）跑一遍整个仓库：405 个 py 文件、79,903 行（核心
39,216 + 测试 40,687），深读 22 个算法文件。审查时 main 在 `c970dfed`，实盘 337 cycles、
vol_target 0.60、tsmom（main）与 flow（flow_short sleeve）两个策略在跑。

**总评**：经典陷阱基本都关掉了。没有负 shift 进特征、没有 bfill 行情列、年化用 365 不是 252、
point-in-time universe 含退市币且把 LUNA 的死亡尾巴量化到 0.30%、缠论在 i+1 确认结构、GARCH 与
HRP 的 refit 锚在 epoch 上做到了 slice 不变。

**真正的问题不在回测会不会看到未来，而在判定门与控制回路的把关强度弱于它们的外观。**
两条高危各自都是「已经算得出、已经写进产物、却没有任何判定代码读过」的量。

---

## 一、判定门读不到自己的免责声明（D-043，已修 #26）

`walk_forward.summary` 从 KILL-Q2 起就发 `oos_is_full_sample_tail`，`research validate` 把它打到
终端，`config/alpha_registry.yaml` 第 301 行三天前还用中文写了「两臂全折同选，这个 OOS 是一条全样本
序列的尾巴」。**只有 `verdict.decide` 看不见。**

上线的 tsmom 证据（`tsmom-validation-20260913T182325Z.json`）正是这个形状：

| 字段 | 值 |
|---|---|
| `grid_size` | 2 |
| `selection_consistent` | True（5 折全选同一参数） |
| `oos_is_full_sample_tail` | **True** |
| `oos_sharpe` | 1.5919 |
| `oos_selection.threshold_annual` | 1.5493 |
| `dsr_p_value` | 0.5788 |
| 判定 | **PASS** |

余量 0.0426（2.7%），而那个数并不是一次选择的样本外记录。同一条规则一并收掉 PBO 的静默豁免：
grid < 4 时 CSCV 确实排不出序，但那是「门没跑」不是「门过了」。

**封顶 WEAK_PASS 而不是判 FAIL**：`registry.py:369` 允许 WEAK_PASS 上线，所以规则能把话说清楚，
而不必停掉一个正持仓的循环。改判先量后改——60 份归档报告里 10 份 PASS → WEAK_PASS，全是 tsmom，
**无一变 FAIL**，逐个按文件名钉在 `D043_CAPPED`。预注册守卫 T-R1-3 保留原样，改成与「关掉 D-043
的规则」比对，这样它继续守它原本守的东西，而不是每来一条新规则就悄悄多一条豁免。

## 二、归因在方向分歧时符号反转（D-044，已修 #26）

E-050 当时用绝对值挡住了有符号分母爆炸，副作用没人注意到：**同一 symbol 内每个策略拿到的都是那个
symbol 盈亏的符号，跟它自己站哪边无关。**

不是边角情形。2026-09-17 量运行中的循环，flow 与 tsmom 重叠的三个标的**全部方向相反**：

```
ENAUSDT:   flow -0.0691 / tsmom +1.0000   净 +0.9309
           旧口径 flow +6.46%   新口径 flow -7.42%
LINKUSDT:  +6.9 vs -8.0        TRUMPUSDT: +6.4 vs -7.3
```

registry 里「91% 与 tsmom 空头重叠」是回测期统计，实盘当天是 **0% 同向**。

要紧的是谁在读：`probe.probe_status` 累加它判 30 天停机，而 flow sleeve 跑在操作者 D-029 放行的
book 级 REJECT 之上——这个停机是它唯一的自动控制。符号错了就是刹车符号错了。

E-050 的失效由**拒绝**而非**改写**来答：两腿抵消到 gross 的 `MIN_NET_SHARE`（0.10）以内时没有可
归属的主人，记入 `cancelled` 桶，与「根本没人持有」的 `unattributed` 分开。历史 55 行不重写，靠
`basis` 键区分；`probe` 的 30 天窗口只累加同口径的行并报出 `stale_basis_rows`。

> **与 10-03 窗口的关系**：`governance window` 里 `probe-stop-caliber` 计划把这个闸改读盯市口径
> （`marked_pnl`），那条路径不经过 `by_strategy`。所以 D-044 对 probe stop 的影响会在切换后变成
> moot，对 M-010 的策略归因仍然有效。切换前的这 16 天，刹车的符号是对的。

## 三、没执行成的止损被当作新入场（D-045，已修 #27）

`exit_step` 触发规则时丢掉锚点。回测里这是对的：weight 0 下一根 bar 就是 flat。实盘不是——平仓单
可能落不下去（`BAND_BLOCKS_EXIT`、`minNotional`、场地拒单）。下一周期 `_reconcile` 走「方向变了」
分支重新入场，`entry_price` 从场地 VWAP 取回（真实成本还在），但 **`unit` 拿当根 bar 的 sigma 重建**。

100 入场、87 标记的多头：

| 重锚时 sigma | 6σ 止损线 | 结果 |
|---|---|---|
| 0.01 | 6 点外 | 触发 |
| 0.08 | 48 点外 | **止损没了** |

波动率上行正是平仓单最容易落不下去的时候——偏的方向恰好是在最需要止损的那根 bar 上把它松掉。

修法不加字段：`cooldown_direction` 记着规则在哪一侧触发，`cooldown_until` 记着这个决定管多久。

## 四、其余已处理项（#27、#28）

| 项 | 处理 |
|---|---|
| `max_drawdown` 在单 bar 亏穿 100% 时报 -1.5253，而 `compound` 说 -1.0 | 补 -1.0 地板；普通路径逐位不变 |
| `staleness.RULES` 把 `skip the whole cycle` 标成 `binds="both"`，说回测会重放 | 更正为 `live`；`_replay_book_guards` 从来没有 staleness 分支。新测试拿 alpha 侧参数对象核对声明，旧测试只检查拼写 |
| `ewma_portfolio_vol` 的 `fillna(0.0)` 把档案缺口读成平盘 bar | **写明不改**：递推按 `outer(row,row)` 更新整个矩阵，跳过单个标的要么丢整根 bar 要么改用 pairwise 协方差（不保证半正定）。带的量：1,005 symbol-bars，约 0.02% 的格子，五个标的都不在钉住的实盘 universe 里 |
| `newey_west_tstat` 默认带宽对重叠标签偏短 | **写明不改**：D-P2 之后这个 t 不 gate 任何东西，调它等于改写归档字段却不改变判定 |
| `equity_hwm` 被抵押品价格污染 | **加警告不改**：throttle 关着所以今天不咬人，但高水位一直在累积，谁打开就继承一个由抵押品定出的旧峰值。R8 的 ladder 用 attributed drawdown 正是为了去掉这一项——同一问题两把尺子，只有一把干净 |

## 五、滑点：M-Q08 的尺子第一次有读数（#28）

`costs.yaml` 自己写着「M-Q08's own ruler (`decision_close`) had no readings yet on 2026-09-08」。
`trades.jsonl` 从那以后一直在记，只是没人读回去。

```
n = 81（demo 成交），32,019 USDT
  名义加权 +4.43 bps    均值 +4.89    中位数 +2.96
  p10/p90  -4.32 / +29.40     均值 95% CI [-1.09, +10.87]

参照点对齐后（同批成交的 close_t -> open_{t+1} 跳空，n=68，名义加权 -0.02）：
  回测，从决策收盘价看  ≈ +1.98 bps
  实测，从决策收盘价看    +4.43 bps      —— 约 2.2 倍
```

**不改 `slippage_bps`**：区间仍包含 2.0；`slippage_stress_bps` 已覆盖 2.0/5.5/9.2 且
`verdict.decide` 读的就是 x2 那一格；**而且全部是 demo 成交**，KILL-Q12 正是为这一类理由把真钱挡在
范围外。p90 +29.4 对 p10 -4.3 说明少数单子付了大部分成本——那恰恰是 demo 盘口与真实盘口差别最大
的地方。复现：`scratchpad/decision_close_slippage_measurement.py --with-gap`。

---

## 六、待操作者裁定（不在本轮 PR 内）

三条都需要花掉 research 预算或动构造，所以是预算决定而不是代码决定。价钱按 ledger trials 计。

### 6.1 回测的止损必然成交，实盘可被 no-trade band 挡住

两条路的算子顺序不同：回测是 `build_weights`(含 band) → `apply_exits` → 直接成为下一 bar 权重，
**没有东西能挡**；实盘是 `exits.apply` → guards → `plan_rebalance`(band) → `abs(delta) < threshold`
就 `continue`。`rebalancer.py` 自己记着 ENAUSDT 在 -11.19 USDT 对 54.32 USDT 的绝对 band 下挂了
多天。回测从不为这段路径计价。

`flat_inside_band` 就是为这件事准备的开关，两边默认都是 False，翻转是 live 行为变更。

**价钱**：一次 A/B validate，约 2 笔 trials（新 construction 下的 2 个 grid 点）。
**要点**：它同时会修掉 D-045 的触发条件本身——止损落不下去的主因就是这个 band。

### 6.2 vol_target 0.60 下 `max_weight` 绑定，P13 的论证基础不完整

配置注释自己记着：k=0.60 下 111/293 个实盘周期（37.9%）至少截断一个名字，**且只截 BTCUSDT**
（σ 0.304 对全书中位 0.736——逆波动率定价必然把最大权重给最平静的名字）。

P13 把 k 从 0.15 提到 0.30 的核心论证是「按任意 k 缩放权重，净 Sharpe 逐位不变，所以这个旋钮只承载
风险偏好、不携带 alpha」。**那个恒等式只在 cap 不绑定时成立。** 注释承认了「错的是先前把它描述成
「不会截断」」，但没有回头重审「k 不携带 alpha」这个结论是否还站得住。

**失效场景**：若 BTC 相对全书的波动率排序改变，被截的名字就会变，组合形状随之改变——而这个变化
不会被任何 construction fingerprint 捕捉到，因为参数没动。

**价钱**：7 档 k × 2 universes = 14 笔（P32 的先例）。
**更便宜的一半**：把「哪些名字被 `max_weight` 截断」做成每周期记录的可观测量，0 笔 trials。

### 6.3 flow 的 `short_gate` 是事后规则拟合

registry 自述的时序：round 5 先定位「2024-10 → 2025-09 亏损，2024-11 单月 -8.6%」，判断成因是
「上涨行情里的空头被挤」，**然后**引入 `short_gate` 并在同一段数据上测 {0, 0.3, 0.5}。

DSR 惩罚的是被计数的试验次数。**它无法惩罚「规则的形式本身是从这段数据里读出来的」**——39 笔
pre-ledger trials 记上了，但「发明一个专门排除某段暴露的条件」这个动作不占任何一格。

**这条不能靠重跑历史解决**，只能靠 2026-09-03 之后的实盘 P&L。而检验它的归因，正是 D-044 修的
那个会反号的数——现在符号对了，所以这个检验从今天起才真正开始计数。

**下一个读数点**：2026-10-02 的 probe 30 天复核（窗口前一天）。

---

## 七、顺带发现的两处陈述过时

- `governance/window_changes.yaml:49`（`vol-target-repricing`）写着「`portfolio.vol_target`
  现为 0.30」，实际是 0.60（2026-09-14 改，ARCHITECTURE.md 的 D-035 已记录）。这条条目还指向
  P26 的重推结果，而 D-035 记着 P26 的「argmax k = 0.15」**已被撤回**（脚本把 universe 写死了）。
  16 天后要用这条做决策。
- `config/live.demo.yaml:187-188` 写着「the loop keeps running whatever it loaded at startup
  (0.30)」。实测不是：`cycles.jsonl` 最近一次 `construction_full` 是 `vol_target: 0.6`，
  digest `ccd7bb9764b5` 与心跳一致，2026-09-15 重启后循环就在 0.60 上。

两处都是同一个陈旧信息的残留，都只改文档。

---

## 附：这次审查没有发现的（读过上下文、判为合法）

```
✓ backtest.py    executed = decided.shift(1)      —— t 决策 t+1 执行
✓ labels.py      shift(-horizon)                   —— 只构造 label，不进任何 X
✓ backtest.py    impact 的 adv / sigma 都 .shift(1)
✓ features.py    donchian 用 high.shift(1).rolling()
✓ 全树           center=True 零命中
✓ panel.py       funding 按「包含它的 bar」向下取整对齐（D-034）
✓ pool.py        membership 只读 date-1ns 之前；退市币无条件保留
✓ chanlun.py     分型在 i+1 确认，一次前向遍历，不 repaint
✓ features.py    refit 边界锚 epoch 而非面板首行，slice 不变（D-033）
✓ metrics.py     rf=0 是明示选择，且所有门槛都在同一口径下测
```
