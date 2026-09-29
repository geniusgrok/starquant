# 前向账户

版权人本人的币安 BTCUSDT U 本位永续账户。单向、逐仓、多空、交易所杠杆保持 20 倍。生产增仓默认关闭。第三方没有复制、修改、二次创作或交易的权利。

这里的前向循环使用真实时钟和交易所订单接口。`measure`、`causal` 和内存里的 `SimExchange` 都是历史或本地故障对照，不是一个月真实时间 Demo。

## 交易对象和信号

只做 BTCUSDT。信号只用已经收盘的分钟。通道只用已经收盘的小时。未完成的分钟、行情滞后超过 15 秒、与交易所时间相差超过 2 秒，或者账户快照读失败，都停止新增风险。

研究出场仍是移动止损、192 小时通道，以及路径权益落到峰值一半时平仓。`take_profit_multiple: 10` 是挂在交易所上的灾备止盈：多头用入场价乘 10，空头用入场价除以 10。历史回放不按这个价格算出场利润。进程停着的时候，通道和一半峰值平仓不会运行，只留下交易所上已经确认的止损和这张灾备止盈。

## 环境

| | Demo | 生产 |
| --- | --- | --- |
| REST | `https://demo-fapi.binance.com` | `https://fapi.binance.com` |
| 用户流 | `wss://demo-fstream.binance.com/private/ws` | `wss://fstream.binance.com/private/ws` |
| 密钥 | `STARQUANT_DEMO_API_KEY` / `STARQUANT_DEMO_API_SECRET` | `STARQUANT_PROD_API_KEY` / `STARQUANT_PROD_API_SECRET` |
| 账户 UID | 不需要 | `STARQUANT_ACCOUNT_UID`（必填） |
| 状态 | `state/demo/` | `state/prod/` |

密钥只从环境变量读取，不进仓库、SQLite、日志或异常文本。密钥不得开通提币和划转。本仓库没有提币或划转调用。Demo 失败不会改去生产域名，也不会改去 `testnet.binancefuture.com`。状态目录带环境戳，两个环境不能共用一个目录。

启动时读取并核对这些项：能否交易、单向、逐仓、杠杆 20、BTCUSDT 为 `TRADING`、余额、仓位、普通未成交单、Algo 条件单、近期成交、资金费、手续费、杠杆档和过滤器。程序不会为了通过检查去改杠杆、保证金模式或持仓方向。不一致，或存在本程序不认识的订单时，冻结新增风险。

## 怎么跑

先做只读核对。核对不会发单。

```bash
python -m btc_perp check --environment demo
```

`run` 是一个连续循环：每 `--poll-seconds` 秒一轮，直到收到中断信号、请求文件或不可恢复的错误；`--once` 只走一轮。`session_seconds` 只属于历史测量（`measure`），前向 `run` 不用它。同一账户同时只允许一个进程。

```bash
python -m btc_perp run --environment demo --max-notional-usdt 200
```

只走一轮：

```bash
python -m btc_perp run --environment demo --max-notional-usdt 200 --once
```

不发单、只打印本轮会做什么：

```bash
python -m btc_perp run --environment demo --max-notional-usdt 200 --dry-run --once
```

安全停止会撤销并确认那些还能增加仓位的普通挂单。已有实仓保留交易所上的保护，不把保护撤掉。只有当没有未完成的入场或减仓意图、没有本程序的入场挂单、有仓位时保护完整时，才报告“已停稳”；否则列出还剩什么。交易所上有不是本程序下的订单，永远不会报成干净账户。`stop` 和 `flatten` 不先读策略 K 线，只读账户快照。

```bash
python -m btc_perp stop --environment demo
```

只减仓退出：

```bash
python -m btc_perp flatten --environment demo --once
```

手工改过仓之后，程序冻结新增风险。接管只按实仓对齐内存，并继续冻结加仓，不会自动开新方向。

```bash
python -m btc_perp takeover --environment demo --once
```

`stop` 或 `flatten` 之后会留下请求文件（内容带环境名，别的环境的请求会被忽略），`run` 看到它就按停机处理；`python -m btc_perp resume --environment demo` 只清除这两个请求文件，不解除冻结、回撤锁或接管。`--dry-run` 不改变控制状态。任何退出路径（正常、中断、初始化失败）都会走同一个收尾，把 `run_state.json` 写成“已停稳 / 尚未核验 / 未启动”之一，并列出剩余订单或仓位。`check`、`takeover` 和 `--dry-run` 使用只读客户端，任何写请求都会被拒绝。状态目录绑定账户：生产按 `STARQUANT_ACCOUNT_UID`（启动时用现货 `/api/v3/account` 的 `uid` 核对，不一致就拒绝），Demo 按密钥指纹（只存哈希）。换密钥保留历史；绑定的账户变了则拒绝。账户级文件锁按账户标识生成（`STARQUANT_LOCK_DIR`，默认系统临时目录），所以两个状态目录不能同时驱动同一账户；锁依赖 `fcntl`，只支持 Linux/macOS 单机。

启动时还要核对：单向、逐仓、杠杆 20、自动追加保证金为关（读不到也算不通过）。配置（`config/btc_account.yaml`）在加载时校验：有限数、真整数和布尔、取值范围。配置的摘要写进状态；有未完成意图时摘要变了，`run` 拒绝启动。有不是本程序下的普通单或条件单，也拒绝。

状态目录可以用 `--state-dir`，或环境变量 `STARQUANT_STATE_DIR`。默认是仓库下的 `state/<环境>/`，这个目录不进版本库。

## 订单和保护

决策可以给出目标数量。实际仓位、均价和下一笔风险预算以交易所确认的成交和账户快照为准。下单前先把唯一的 `clientOrderId` 或 `clientAlgoId` 写入 SQLite，再发送。超时、断网或执行结果未知时，用原来的身份查询，不换一个新身份重发。入场单和加仓单永远不重发，未回应就一直查。“查不到（-2013）”只是一个事实，不等于过期：入场单一直保持未知并阻塞新增风险，不按时间放行。人工确认交易所确实没有这张单之后，用 `python -m btc_perp resolve --environment demo --client-id <编号> --yes` 解决；它先重新查询，只有交易所再次明确回答“不存在”才关闭。所有会碰网络的写入，先在一个事务里落下不可变的请求、尝试状态和策略记忆，再发送；崩溃后只按原身份查询。减仓、平仓和保护单最多用同一身份重发一次。仓位变化按成交归因：读 `userTrades`，用 orderId（含条件单触发后的 actualOrderId）和成交游标区分本程序与外来成交。本程序的止损触发不算手工操作；无法解释的部分冻结账户。自家成交用 `absorbed` 标记是否已计入账本，账本只在与账户对上之后才标记。

普通市价单走 `/fapi/v1/order`。`STOP_MARKET` 和 `TAKE_PROFIT_MARKET` 走 `/fapi/v1/algoOrder`。保护单使用 `closePosition=true`，不再同时带数量和 `reduceOnly`。触发价源是 `CONTRACT_PRICE`。一张保护成交之后，核验并撤销另一张。平仓使用交易所的只减仓语义。反手要先确认旧仓归零、旧订单清掉，再开新方向。

开仓和加仓前先对止损、止盈两侧预检（价格、方向、与强平价的距离）。保护按“先止损、后止盈”放置；止损没有确认就不放止盈。别人的保护单不接管，本程序的保护要止损和止盈各至少一张才算覆盖，几张有效保护可以并存。替换止损时，先确认新止损已经挂上，再撤旧止损。保护被拒、过期、触发后执行失败或数量盖不住实仓时，停止加仓。实仓仍能读到时，补保护；裸露超过允许时间后只减仓退出。Demo 在限额文件没写裸露时间时，默认 120 秒。账户或网络状态未知时不反向开仓。

`run`、`stop` 和 `flatten` 会申请 listenKey，并连接 `wss://<官方主机>/private/ws?listenKey=...&events=...`。这是 2026-04-23 之后的私有用户流路径，不再使用已经撤掉的 `/ws/<listenKey>`。Demo 主机是 `demo-fstream.binance.com`，不会改去 `fstream.binancefuture.com`。`ALGO_UPDATE` 读 `o.caid` 和状态 `X`，同时接受 `ao` 与 `ALGO_ORDER_UPDATE`。这些事件只写入流水并触发下一轮 REST 对账，不直接改仓位。断线、过期或握手失败时，本轮只信 REST 快照，并在 30 秒后再尝试连接。listenKey 不进日志。

## 入场门禁

开仓、加仓、反手后的新仓和恢复路径都走同一个函数 `_entry_gate`。任何一项不成立，本轮不增加风险：人工接管、冻结、回撤锁、资金划转冻结、冷却、生产授权与额度、快照未知或超过 30 秒、时钟漂移、决策已过期、日损上限、离强平价太近、停机请求、外来订单、无法解释的成交、未完成的开仓意图、保护不完整。还没发出的旧入场计划会被撤销并重新决策。追赶历史分钟只用来重建指标，不下单；成交所在的那一分钟不再被当成持仓；过期的反向信号不开仓。

## 回撤锁和重置

收盘权益/峰值降到 `1 - dd_flat`（0.53）或更低时，`run` 不再开新仓、不再加仓，仍按规则离场。空仓时它不会自己解除，因为空仓的权益不会回升。这时每轮都会在提示里说明，流水里有 `dd_locked`。

要继续交易，先确认愿意把此前的亏损当作新起点，再在空仓、没有未完成订单时运行：

```bash
python -m btc_perp rearm --environment demo --yes
```

它只把回撤峰值换成当前权益，并写一条 `rearm` 事件。累计绩效峰值（`perf_peak`）不重置，所以重置不会把新的起点缝成一段新绩效。它不发任何订单，不改止损、保护和 `limits.yaml` 的限额。有持仓、有未完成意图或交易所上有任何活动订单时拒绝；不带 `--yes` 只打印说明。

运行中若账户出现充值、提现或划转（读 `income` 的 TRANSFER 等），新增风险冻结，同样要 `rearm --yes` 才解除。

## 限额

`config/limits.yaml` 里的 `capital_usdt`、`max_notional_usdt`、`max_daily_loss_usdt`、`max_unprotected_seconds` 现在都是空的。空着时，生产入口拒绝增仓。填了 `capital_usdt` 之后，仓位权益取 `min(账户权益, capital_usdt)`，名义上限取命令行和文件的较小值。`capital_usdt` 只用于仓位大小，不参与回撤和日损的计算，账户权益才是回撤基准。`max_daily_loss_usdt` 的基准是 UTC 日内第一次有效观测的权益，只冻结新增风险，不会自动平仓。收到 418/429 后进入冷却，没有任何绕过（包括减仓和只读公共行情），冷却时长取 `Retry-After`。研究里的 4.8% 单位风险、最多三档、约 3.75 倍名义，以及强平前 0.1% 的止损间距，不是生产安全保证。

生产下单还要环境变量 `STARQUANT_ALLOW_PROD_ORDERS=yes`，并且命令行 `--max-notional-usdt` 为正、且不超过文件里的名义上限。生产在发单前还会读 `https://api.binance.com/sapi/v1/account/apiRestrictions`。密钥开通了提币、内部划转或万向划转，或者这次读取失败，就拒绝下单。Demo 密钥不拿去打这个现货接口。本轮实施和验证不发送真实资金订单。

## 记录

每一轮在状态目录追加一行 `journal.jsonl`：时间、运行或停机模式、是否冻结、原因、实仓、均价、余额、标记价、最新价、保护是否覆盖、普通单和条件单身份、手续费读取结果、资金费读取是否成功、游标和对账提示。发送订单时另记一行客户端身份、阶段和本次传输耗时。文件不进版本库，也不写密钥。

满 30 个自然日之后，用这份流水核对运行和停机窗口、信号、实仓、保护、成交、费用、资金费、断线和对账差异。某一种订单在这 30 天里没有自然出现，不能当成那条路径已经通过。一个月盈利也不说明以后还能盈利。

## 还不能当作完成

本机在 2026-09-28 访问 `demo-fapi.binance.com` 和 `fapi.binance.com` 的 `/fapi/v1/time` 返回地区限制。`testnet.binancefuture.com` 能打开，但那不是官方 Demo，代码不会改去那里。没有 Demo 密钥，就没有远端回读。连续 30 个自然日也还没有开始。门槛结论在 [forward_audit.md](forward_audit.md)。
