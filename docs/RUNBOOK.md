# 运行手册（demo）

## 日常命令

| 目的 | 命令 |
| --- | --- |
| 拉取/刷新研究数据并选 universe | `starquant data sync` |
| 修补研究归档里的缺口（9.4）。默认干跑：列出每个缺口要取的日归档文件、REST 调用数和估计字节数，不联网、不写盘。`--apply` 才下载和合并，源头也没有的记进 `confirmed_gaps.json`（confirmed gap）。不要和每日 01:20 的数据任务同时跑，两者改写同一批 parquet | `starquant data repair [--symbols A,B] [--apply]` |
| 手动刷新实盘交易池（30 日成交量 + 滞回） | `starquant data pool refresh`（实盘循环每个 UTC 日也会自动做一次） |
| 重建时点成员表（研究用，先同步 878 个候选的日线；出日表：2026-09-04 起研究口径逐日重选，2026-09-23 起 `--refresh` 默认就是 `D`，传 `MS` 出的是月表）。**重建会挡住 armed 启动**，先读下面「成员表落后告警」 | `starquant data pool history --refresh D [--sync-members]` |
| 时点成员表落后几天（每小时巡检带 `--check` 跑它） | `starquant data pool lag [--check]` |
| 单策略回测 / 验证 | `starquant research backtest --strategy tsmom`；`starquant research validate --strategy tsmom --universe pit --prior-trials N`（`--min-tenure K` 只交易已入池 ≥K 次的老牌币） |
| exit overlay / 回撤节流证据 | `starquant research overlay --universe pit` |
| 信号 vs 构建归因（D-024，不计 ledger） | `starquant research decompose --strategy tsmom --universe pit --from 2021-01-01` |
| 独立小书证据（主书 + fraction × 小书，D-018） | `starquant research book --main tsmom --sleeve flow --sleeve-params '{"long_side": false}' --universe pit --robustness static --prior-trials N` |
| 探针书状态（D-019） | `starquant live status`（心跳 `probes`）、日报 `Probe books` 段；自动停书后 `state.json.stopped_books` 有记录；手动停书：registry 里该策略 `enabled: false` 后重启 |
| 启动实盘（launchd 已托管） | `launchctl load -w ~/Library/LaunchAgents/com.starquant.live.plist`；手动：`deploy/run_live.sh` |
| 状态 / 健康检查 | `starquant live status --check` |
| 核对实盘输出可复现（M-011） | `starquant live verify --check`（用公共数据 + `state.json` 离线重算上一周期的 contributions；差异必须为 0） |
| 检查唤醒时刻与 bar 边界的对齐 | `starquant live status --check`（对齐误差 > 60s 非零退出；整数个 bar 的偏移不算问题，D-025） |
| 因子挖掘（每轮记 514 行 ledger，先看 R1 预算） | `starquant research mine --strategy tsmom --universe pit --baseline tsmom`；只测量不计费：`--measure` |
| 定时刷新研究数据（每日 01:20，klines + 资金费率 + **现货** + 池刷新） | `cp deploy/com.starquant.data.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.starquant.data.plist` |
| 定时跑上面两项（每小时 :10） | `cp deploy/com.starquant.check.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.starquant.check.plist` |
| 一键平仓 | `starquant live flatten --yes` |
| 停止加仓（可逆） | `starquant live kill-switch --engage` / `--release` |
| 日报 / 周报 | `starquant report daily`；`starquant report weekly`（含 90% alpha 投入占比 `effort_share`） |

2026-09-16 补：上表此前漏掉整个 `governance` 组、三个 launchd 任务、`live soak`、`research mine`
与 `report weekly`。漏的不是边角——`governance` 是晋级线本身，而漏掉的三个任务里有两个正在这台
机器上跑。下面两节补上。

## 治理（`starquant governance`，17 个子命令）

自主开关是**每个工作副本**的运行期状态，不入库：`governance/ENABLED` 存在时这个 checkout 才允许
写 registry。没有它，`apply` 只会预演。

| 目的 | 命令 |
| --- | --- |
| 下一步该做什么（读证据 + 状态，只决定不执行） | `starquant governance next` |
| 把记录里已经发生的事折进状态 | `starquant governance advance` |
| 晋级计划 / family gate 读数 | `starquant governance plan`；`starquant governance gate` |
| 事务化写 registry（需要 `governance/ENABLED`） | `starquant governance apply` |
| 部署健康金丝雀（读 shadow soak，不判 alpha） | `starquant governance canary` |
| 规则重放：每份报告都要能被解释（AC-G0 未归因项必须为 0） | `starquant governance replay` |
| 状态 / 在位时长 / 事务链 / 机器判定 / 人工复核 | `starquant governance status\|tenure\|transactions\|verdicts\|review` |
| 进程持有的 registry 与磁盘上的是否分岔 | `starquant governance divergence` |
| 重开条件 / 批次窗口 | `starquant governance reopen`；`starquant governance window` |

## 另外两个 launchd 任务

| 任务 | 干什么 | 装载 |
| --- | --- | --- |
| `com.starquant.shadow` | L4 金丝雀 soak：拿 `config/alpha_registry.candidate.yaml` 在 armed 循环旁边跑 168 个 dry-run 周期，写 `.starquant/live-shadow-dry-run`，不碰账户、不重排 universe。`KeepAlive` 只在崩溃时生效——soak 在 168 周期**正常结束**，那里重启等于静默开始第二次。读数：`starquant governance canary` | `cp deploy/com.starquant.shadow.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.starquant.shadow.plist` |
| `com.starquant.paper-l3` | §5 L3 的七天累积器：`--paper` 在 mainnet 价位上撮合，`--state-dir .starquant/paper-l3`，无凭据、结构上不可能变成交易进程。读数：`starquant live soak --check`（**报告而不闸**：前六天按构造必然为假，接进 `failed` 等于每小时误报一周） | `cp deploy/com.starquant.paper-l3.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.starquant.paper-l3.plist` |

`com.starquant.proxy-probe` 曾是第三个，2026-09-22 撤除：它是临时测量，判读做出来了就该收。
结论与读数在 `docs/RESEARCH_LOG.md`「2026-09-22 · 代理路径：对照臂的判读结清」一节；
要装回去（例如复核换节点的效果）：

```bash
git show 3a4bf6fa:deploy/run_proxy_probe.sh > deploy/run_proxy_probe.sh && chmod +x deploy/run_proxy_probe.sh
```

```bash
git show 3a4bf6fa:deploy/com.starquant.proxy-probe.plist > ~/Library/LaunchAgents/com.starquant.proxy-probe.plist && launchctl load -w ~/Library/LaunchAgents/com.starquant.proxy-probe.plist
```

改了候选 registry 之后 soak **必须重启**才会生效（引擎只在启动时建模），且原 `cycles.jsonl` 要移走
而不是追加——一份 soak 记录只能描述一个候选：

```bash
launchctl bootout gui/$(id -u)/com.starquant.shadow && mv .starquant/live-shadow-dry-run .starquant/live-shadow-dry-run.$(date -u +%Y%m%d) && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.starquant.shadow.plist
```

## 成员表落后告警（2026-09-23 起）

操作者 2026-09-23 裁定：时点成员表维持手动重建，不排定时任务。每小时巡检为此加了一行，报它落后几天
（`starquant data pool lag --check`）。

**含义。** 表末行之后的 bar，研究侧沿用末行的成员（`membership_at_bars` 前推）。落后 k 天，就是研究
最近 k 天用的是一个冻住的池子。刚重建完读数是 1，不是 0：末行是最后一根收盘日线，也就是昨天。
落后满 14 天告警。表不存在、读不了、是空的、不是日表，或末行晚于今天，也都告警。这些状态都说不出
表有多新。

**为什么是 14 天。** 在 09-18 重建的真实表上量过。取截止今天的 30 天窗口，最后 14 天前推时，
平均 3.42% 的成员位拿错了名字。13 天时是 2.98%。3% 是 P12 第 0 段用过的线：成员改动低于它，
不值得跑回测。量法与出处在 `starquant_data/pool.py` 的 `MEMBERSHIP_ALERT_DAYS`。
`tests/data/test_the_membership_table_says_how_far_it_trails.py` 在真实表上逐个重算这些数。

**收到告警怎么办：不要马上重建。** `membership` 是 dataset manifest 的阻断字段，重建会改动它。
armed 启动随即被数据集门挡住（`registry_dataset_problems`）。要等证据在新表上重出，才能再过这道门。
2026-09-18 那次单独重建，就是这样引出了 D-041 bridge。所以：

1. 重建和证据重出排进同一个安排，时间由操作者定。重出要花 ledger。
2. 重建要出日表。2026-09-23 起 `--refresh` 默认就是 `D`；传 `MS` 出的是月表，巡检会接着报「不是日表」。
3. 开跑前先确认没有别的会话在写 `.starquant/data`（RISK-LD05）。`--sync` 默认开，会给每个候选下载
   日线，走的是实盘循环那条代理，按 RESEARCH_LOG 里回填那条整点避让挑时间。
4. 表是原子写入的（2026-09-23 起）：巡检读到的要么是旧表，要么是新表。命令开跑时先印一行数据集门的提示。

告警每天推送一次，直到重建为止（操作者 2026-09-23 裁定）。巡检日志里仍每小时记一行 FAIL，变的只是推送。
这一条的去重用单独的状态文件 `alert-dedup-daily.json`：共用的 `alert-dedup.json` 会被每小时的检查写回时冲掉。

## 衰减与 bar sanity 两条告警（2026-09-23 起）

两条都由 `report daily --check` 发出，都只告警。机器不因它们改权重，也不降级、不退休。

### 衰减规则判 REVIEW（G1）

**含义。** 两个不重叠的 30 天窗口里，这条策略的归因夏普都低于它的证据报告里的回测 q10。
窗口从当前构造起算（`evidence_window`，与 M-010 同一起点）。构造一变，窗口重新起算。

**什么时候会出现。** 当前构造从 2026-09-17T16:00Z 起算，最早 2026-11-16T16:00Z 才有两个完整窗口。
在那之前，日报「Edge decay (M-010 vs backtest q10)」一节读 INSUFFICIENT_DATA，只印不告警。
10-13 若改构造，窗口从那天重新起算。

**读之前先看口径。** 实盘窗口是已实现归因，q10 是回测盯市（操作者 2026-09-23 裁定 A）。
两种口径的波动差得很远：flow 的 30 天 σ 在 09-12 读数，已实现 0.137%，盯市 3.239%。

**收到告警怎么办。** 复审这条策略，结论由操作者定。

1. 读日报「Edge decay (M-010 vs backtest q10)」一节：两个窗口的读数与 q10。
2. 对照同一份日报的「Drift vs expectation (attributed income, M-002/M-010)」与「Long-run attributed Sharpe (M-G06)」。
3. 结论与动作写进 `docs/RESEARCH_LOG.md`。生命周期里没有哪个事件读这条告警（`starquant_governance/lifecycle.py`
   的 `Event`），`governance advance` 不会因它降级。

### bar sanity（G6）

**含义。** 实盘循环每周期拿到闭合 bar 后查三项，结果写进 `cycles.jsonl` 的 `bar_sanity`。模型、护栏、
下单都读不到它，交易照常。

- OHLC 自相矛盾，或价格不是有限正数。全部归档 15,127,202 根里一根都没有，出现就是数据源的问题。
- frozen bar：连续 2 根以上 OHLC 全等且零成交。成员日上见过的是 LUNA 停牌，与 FTT、ALPACA 下架前的死尾巴。
- 跳变：收盘价对上一根收盘翻倍或减半（|ln| > ln 2）。flag 记两根之间有没有成交衔接。

**哪些推送。** 当天首次出现的 flag 才推。同一根 bar 在 1,442 根窗口里停留期间不会天天重报。
新进池的名字，历史里的旧异常在进池当天报一次。

- 告警：断档跳变（中间缺 bar，或一侧零成交；BNX 2023-02 的 ×1/55 就是这种）、OHLC 矛盾、frozen bar。
- 提示：有成交衔接的跳变。它像真实行情，成员日上约每年 2.6 次（操作者 2026-09-23 裁定）。
- 提示：检查本身有周期没读完。

**生效要等重启。** 检查在实盘循环里，要等下一次按纪律重启才开始记录。在那之前，
日报「Bar sanity (G6, alert only)」一节读 `cycles_checked 0`，并写明原因。

**收到告警怎么办。**

1. 告警正文逐条列出标的、时刻、哪一项，跳变还带倍数与有没有成交衔接。
2. 断档跳变：先查是不是同名重新计价或换了合约，看币安公告。本地归档的缺口用 `starquant data status` 看，
   修补用 `starquant data repair`（见上面日常命令表）。
   同名下两段序列的例子见 `starquant_data/store.py` 的 `gaps`：BNXUSDT 2023-02-22、PUMPUSDT 2025-07-10。
3. frozen bar：多半是停牌或下架前的死尾巴。先用 `starquant live status` 看循环是否持有它。
4. OHLC 矛盾：拿交易所网页上同一根 bar 比对。
5. 这条告警不拦 bar，也不改目标。要不要对这个标的动手，由操作者定。

## D-041 bridge 到期（2026-10-13）

2026-10-13T00:00Z（北京 08:00）起，`deploy/run_live.sh` 不再给 armed 启动传 `--allow-unvalidated`，严格的
证据门回来。同一刻，`tests/shipped_evidence.py` 的 exemption 与构造冻结也到期。分析、选项与裁定表在
`docs/analysis/2026-09-25-october-13-readiness.md`；操作者 09-25 的裁定记在 RESEARCH_LOG「操作者四条裁定」一节。

- 在跑的进程不受影响。受影响的是 10-13 之后的下一次启动。
- bash 3.2 展开空数组的缺陷已由 #137 修掉，09-25 已快进主 checkout。launchd 读的就是主 checkout 里这份脚本。
- 证据还没清门时，下一次 armed 启动会以 `tsmom: evidence verdict FAIL does not allow live use` 失败，launchd
  每 60 秒重试一次。循环不在，持仓就没有退出检查：止盈止损从不在交易所挂单。
- 10-13 起 CI 至少 9 条测试红，都跟 exemption 到期有关。那不是代码坏了，处理方式跟着 D-041 的裁定走。

**10-12 之前**：

- 确认主 checkout 含 #137：`grep -n 'BRIDGE\[@\]+' deploy/run_live.sh` 能找到一行。
- 用 `ps -eo pid,lstart,command | grep "live run"` 确认在跑的进程是 10-13 之前起的。
- 证据修好之前，不做有意重启。

**10-13 之后循环起不来时**：

- 症状：`~/Library/Application Support/starquant/live.stderr.log` 里先有 `bridge EXPIRED`，接着是证据门的拒绝；
  每小时巡检报「心跳已过期」，阈值 4,000 秒（2026-09-25 起；循环停在某根 bar 之后，下一次 :10 就会报）。
- 先平仓：`starquant live flatten --yes`。它不经过证据门，会挂上持久的 kill switch。恢复要先
  `starquant live kill-switch --release`，再启动，那时仍要过证据门。
- 不要为了让循环起来去改 `BRIDGE_UNTIL` 或 `EXEMPT_UNTIL`。两者由测试钉成相等，挪日期就是延长 bridge，
  是治理裁定。

## 改了 registry / profile 之后

实盘进程在启动时加载 registry、profile 与 universe；改动后必须重启：

```bash
launchctl kickstart -k gui/$(id -u)/com.starquant.live
```

重启是幂等的（clientOrderId 按 bar 派生，先查后下），但**要挑周期之间的窗口**：exit overlay 在 bar 收盘判定，一根没跑的周期就是那根 bar 没有退出检查，而且不会补。安全窗口是整点后 5 分钟到下一个整点前 10 分钟；重启前先跑 `tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py` 与 `test_construction_identity.py`确认这次重启不改构造（纪律与理由见下文「重启实盘循环」一节）。重启后看 `.starquant/live/heartbeat.json` 的 `phase`、`universe_size`、`leverage`。

### 采纳 exit overlay / 信号改动的最短干净窗口（K-EX14，2026-09-07 操作者裁定）

M-010（30 天 income 归因）在当前构造指纹下不满 30 天连续记录之前，不采纳任何 exit overlay 或信号改动——研究可以跑、结论可以写，但 `config/live.demo.yaml` 的 `exits` 与 registry 的信号参数不动。唯一例外：风险预算阶梯（P13）触发，那是预登记的降档，不是采纳。档位以 `starquant_governance/policy.py` 的 `drawdown_ladder` 为准。2026-09-14 随预算重标，现为回撤 −49% / −70%（D-035）；此前的 −35% / −50% 已作废。

窗口起点**不写在这里**：它随每一次构造变更移动，写死在正文里的日期只会过期（这一段最初写的 2026-09-06T10:19Z / 最早采纳日 2026-10-06 就是如此，`unit_mode` 进指纹后一次重启即作废）。要当前答案，读这两处之一——`starquant report daily` 的 evidence-window 一节（`since_ms` 是起点、`bars` 是已积累的周期数），或 `cycles.jsonl` 里 `construction` 最后一次变化的那根 bar。最早采纳日 = 该起点 + 30 天。

每次采纳都是构造变更，窗口重新计数；**只加指纹字段、不改行为也算**——2026-09-07 的 `unit_mode` 就是一例（`0dcd044d0158` → `b441ea62d021`，配置一个字符没改，见 RESEARCH_LOG 同日条目）。

## Profile 关键字段（`config/live.demo.yaml`）

- `portfolio.leverage: auto` —— 每个币的交易所杠杆按 `max_gross / margin_cap` 与档位上限推导（当前 5x）；写死整数则固定。
- `portfolio.max_participation` —— 除完全平仓外，每一单 ≤ 该比例 × 近 24 根 bar 平均报价成交量。纯减仓单也会被截：`exempt_reductions` 默认关，要开就得与回测的 `ParticipationModel` 一起翻（`starquant_live/rebalancer.py` 的注释）。`margin_buffer` —— 保证金不足时按比例缩小加仓单，保留这部分可用余额。
- `pool.refresh: daily|never` —— 每日自动重排 universe；被移出的币会被 reduce-only 平掉，`cycles.jsonl` 的 `universe_update` 记录进出。
- `exits` —— 止损 / 移动止损 / 止盈（单位 = 入场时日波动率），0 关闭；`cooldown_bars` 冷却期。
- `drawdown_throttle` —— 权益回撤在 `start`→`stop` 之间把整本书线性缩到 `floor`。

## Registry 里的书（`config/alpha_registry.yaml`）

- `books.<name>.fraction` —— 独立小书的风险预算比例；策略用 `book: <name>` 归属，未写的属于主书。
- **资金费率**：round 6b（D-023）之后行情端口提供 `funding_history`，实盘面板与研究面板由同一份结算费率构成，消费资金费率的设置（tsmom 的 `crowding_window > 0`、`carry` 信号）**不再会被静默跳过**——信号自己声明需求，拿不到历史时 `AlphaModel.targets` 报错、`starquant live run` 拒绝启动（第六轮 KILL-027 的结构性关闭）。tsmom 现在跑 `crowding_window: 72`，修饰器已重新打开。打开它是**证据问题**而不是管线问题：按 D-013/D-020 在时点 universe 上重验，再更新 evidence 指针。经过见 `config/alpha_registry.yaml` tsmom 条目 `params` 之上的「2026-09-05 RE-ENABLED」一段。
- 探针书（D-019）：`evidence.verdict: ACCEPT`（来自 `starquant research book`）+ `probe` 块（`accepted_by`、`accepted_on`、`stop: {window_days, max_loss}`、`review_after_days`）。书级判定是 REJECT 也能跑，但 `probe` 块还要写明 `accepted_despite: REJECT` 与 `reason`（D-029）。启动时核对报告种类、对象与 fraction；缺任何一项 `starquant live run` 拒绝启动。当前：`flow_short`（flow 只做空，1/3 预算）。它引用的书级报告判 REJECT，靠 `accepted_despite` 运行。止损是 30 天归因 P&L ≤ −2% 权益（`max_loss: 0.02`）。复审期 30 天，自 `accepted_on` 起算，到期时日报标 REVIEW_DUE。

## 主机时钟漂移（2026-09-04 实测到 −3,612 秒）

检测：

```bash
python3 -c "import time,json,urllib.request;s=json.load(urllib.request.urlopen('https://fapi.binance.com/fapi/v1/time'))['serverTime'];print('drift %.1f s' % (time.time()*1000-s)/1000)"
```

影响与不影响：

- **不影响下单**：REST 客户端会自己测出偏移并写进 `clock_offset_ms`（实测 3,611,691），签名请求照常成功。
- **不影响过期护栏**：`expected_bar_ms - latest_bar_ms > stale_bars_max × interval` 是单向判断，慢钟只会让差值为负。
- **不影响唤醒时刻**（当偏移接近整数个 interval 时）：本地 bar 边界与真实 bar 边界落在同一批真实时刻，循环仍在每个真实整点后不久运行，用的是刚收盘的那根真实 bar。
- **影响记录**：`cycles.jsonl` 的 `bar` / `bar_open_ms` 与 `heartbeat.at` 会整体偏移，`bar` 与 `as_of_ms` 不再一致（`as_of_ms` 是真实的最新闭合 bar，可用它交叉核对）；日报的 UTC 日切也跟着偏移。
- 校正主机时钟需要操作者本人（系统设置 / 需要密码），Agent 不做这件事。校正后重启循环即可，重启是幂等的。

## PR 流程

改完代码走 PR，不直推 main。

1. 从最新的 `origin/main` 开分支
2. 本地先过四道门（Format / Lint / Types / Tests），全绿再推：
   ```bash
   .venv/bin/ruff format --check . && .venv/bin/ruff check .
   .venv/bin/mypy && .venv/bin/pytest -m "not network"
   ```
3. 开 PR，等 CI
4. **先看 CI 跑没跑起来，再看它绿不绿**

## 重启实盘循环（纪律）

2026-09-17 写死。当时 13.4 天里 `state.restarts` 已经到 **51**（约 3.8 次/天），而 M-010 要
30 天连续记录、`realised_vol` 要单构造窗口、L3 要 7 天无 ERROR。

**重启不清构造指纹，但每次都可能吃掉一根 bar 的退出检查。** exit overlay 在 bar 收盘判定
（`starquant_live/exits.py`），一根没跑的周期就是那根 bar 没有退出检查，而且不会补——判据不看
`extreme`。2026-09-15 量到命中概率约 1.16%，AKEUSDT 逼近 6σ 时它第一次有价钱。

三条，顺序不能反：

1. **选周期之间的窗口**。循环在每根 1h bar 收盘后约 20–35s 跑完。安全窗口是**整点后 5 分钟到下一个
   整点前 10 分钟**。不要在整点前几分钟重启。
2. **重启前跑两个构造测试**，确认这次重启不改构造：
   ```bash
   .venv/bin/python -m pytest tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py tests/live/test_construction_identity.py -q
   ```
   红了就不是「重启」，是构造变更，要按 K-EX14 与冻结裁定走。
3. **重启后把「谁、为什么」记进 `docs/RESEARCH_LOG.md`**，只写可观测事实（PID、`restarted_at`、
   `restarts`、源文件 mtime 对进程启动时刻、两个测试的结果）。**不按时间相关性给实盘动作归因**。

重启命令与幂等性见「改了 registry / profile 之后」一节（`launchctl kickstart -k gui/$(id -u)/com.starquant.live`；clientOrderId 按
bar 派生，先查后下）。要确认循环此刻跑的是哪份代码，比较源文件 mtime 与进程启动时刻
（`ps -eo pid,lstart,command | grep "live run"`），不要读 `cycles.jsonl` 的最后一行——重启后
那是已死进程的。

## 排障

- 心跳超时：`starquant live status --check`；看 `~/Library/Application Support/starquant/live.err.log`。
- 连续 12 个周期失败触发熔断（`starquant_live/engine.py` 的 `breaker_stop`）。告警送达就以 0 退出，launchd **不会**再拉起（`KeepAlive.SuccessfulExit=false`）；恢复是一次重启，按上文「改了 registry / profile 之后」的窗口与纪律做。没有任何通道收下告警时才非零退出，launchd 60s 后拉起。失败之间循环自己按指数退避，上限 1 小时。根因通常是网络或 -1021 时钟漂移（客户端自动重同步）。
- `cycles.jsonl` 每周期一行：`targets`、`orders`（含 `note`：`PARTICIPATION_CAPPED` / `MARGIN_SCALED`）、`exit_events`、`throttle`、`universe_update`、`skipped`。
- `state.json` 的 `exit_states`（入场价/极值/冷却）、`equity_hwm`、`universe`、`leaving` 在重启后恢复；入场价以交易所为准。
- `heartbeat.json` 的 `history_bars`（当前 1,442）与 `external_flows`；`cycles.jsonl` 的 `external_flows`（`rebaselined: true` = 该周期发生了非交易性现金流，日起点 / 高水位已重置，日报 drift 跳过该 bar）。
- 账户在 demo UI 里被重置后不需要任何操作：下一周期自动重建仓位；`starquant report daily` 的 External cash flows 段显示金额。
- `state.json.last_contributions` 是 NO_ACTION 的 hold 种子（D-022），不要手动删除；删除等于把所有未触发信号的仓位归零一次。
- `starquant live verify`：contributions 必须逐币复现（`ok: true`）；`target_diffs` 非零只是提示——exit overlay / 节流 / 护栏在模型之后动作。`bar_matched: false` 说明 `state.json` 来自另一根 bar，等下一周期再跑。2026-09-04 01:00Z 的实测：两本书差异均为 0.0。
- `cycles.jsonl` 的 `gross_before` 自 D-023 起按 `positionRisk` 的仓位求和；此前恒为 0（账户报文不带 positions 数组），满仓也显示为空仓。
- 时钟漂移下的两个工具（见上文《主机时钟漂移》）：`starquant live status --check` 会探测交易所服务器时间并在偏差超过 `--max-skew-seconds`（默认 60s）时非零退出；`starquant live verify` 以 `as_of_ms`（数据自带的 bar）而不是 `state.last_bar_ms`（本机时钟写的标签）为准比对，并在 `bar_label_skew_ms` / `clock_note` 里给出两者的差。
- **每周期的时钟测量**（D-023 / D-025）：循环每周期用行情端口已有的服务器时间调用测一次偏差，写进 `cycles.jsonl.clock` （`skew_ms` / `alignment_ms` / `whole_bars` / `jumped`）与心跳。**主机时钟是基准**，所以恒定的整数 bar 偏移不告警；只有对齐误差超过 `guards.max_bar_alignment_seconds`（默认 60）或发生跳变才告警，且是边沿触发。探测失败不影响周期。
- 当前实测：偏移 −3,612 s ≈ 整 1 根 bar，对齐误差 12 s，属于可接受状态；循环交易的始终是刚收盘的真实 bar，`cycles.jsonl` 的 `bar` 标注会比 `as_of_ms` 早 1 小时（前者出自本机时钟，后者出自数据），日报按 `as_of_ms` 分桶因而不受影响。
- **定时数据刷新**：`deploy/run_data.sh` 跑 `data sync` + `data spot` + `data pool refresh`（`data spot` 2026-09-09 加入；每日 01:20，`com.starquant.data.plist`）。`data sync` 同步三类名字：24h 成交额前 2N、`universe.json` 里的池子、上次刷新刚移出的名字。后两类 2026-09-23 加入：此前只看 24h 排名，LSKUSDT 还在池里，K 线却停在 09-18。在此之前研究数据没有任何定时刷新，审计时落后 16 小时且有池成员完全没有本地数据——验证因此跑在「比被验证的书更早结束」的数据上。只读，不碰账户。
- **定时健康检查**：`deploy/run_check.sh` 跑 `live status --check`、`live verify --check`、`report daily --check` 与 `data pool lag --check`（成员表落后，见上文「成员表落后告警」），失败推送到告警 webhook；`deploy/com.starquant.check.plist` 每小时 :10 触发。**装载它是操作者的动作**（上表命令）；只读，不写交易所。
