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
| 用户流 | `wss://demo-fstream.binance.com/ws` | `wss://fstream.binance.com/ws` |
| 密钥 | `STARQUANT_DEMO_API_KEY` / `STARQUANT_DEMO_API_SECRET` | `STARQUANT_PROD_API_KEY` / `STARQUANT_PROD_API_SECRET` |
| 状态 | `state/demo/` | `state/prod/` |

密钥只从环境变量读取，不进仓库、SQLite、日志或异常文本。密钥不得开通提币和划转。本仓库没有提币或划转调用。Demo 失败不会改去生产域名，也不会改去 `testnet.binancefuture.com`。状态目录带环境戳，两个环境不能共用一个目录。

启动时读取并核对这些项：能否交易、单向、逐仓、杠杆 20、BTCUSDT 为 `TRADING`、余额、仓位、普通未成交单、Algo 条件单、近期成交、资金费、手续费、杠杆档和过滤器。程序不会为了通过检查去改杠杆、保证金模式或持仓方向。不一致，或存在本程序不认识的订单时，冻结新增风险。

## 怎么跑

先做只读核对。核对不会发单。

```bash
python -m btc_perp check --environment demo
```

连续运行需要名义上限。同一状态目录同时只允许一个进程。

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

安全停止会撤销并确认那些还能增加仓位的普通挂单。已有实仓保留交易所上的保护，不把保护撤掉。

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

状态目录可以用 `--state-dir`，或环境变量 `STARQUANT_STATE_DIR`。默认是仓库下的 `state/<环境>/`，这个目录不进版本库。

## 订单和保护

决策可以给出目标数量。实际仓位、均价和下一笔风险预算以交易所确认的成交和账户快照为准。下单前先把唯一的 `clientOrderId` 或 `clientAlgoId` 写入 SQLite，再发送。超时、断网或执行结果未知时，用原来的身份查询，不换一个新身份重发。

普通市价单走 `/fapi/v1/order`。`STOP_MARKET` 和 `TAKE_PROFIT_MARKET` 走 `/fapi/v1/algoOrder`。保护单使用 `closePosition=true`，不再同时带数量和 `reduceOnly`。触发价源是 `CONTRACT_PRICE`。一张保护成交之后，核验并撤销另一张。平仓使用交易所的只减仓语义。反手要先确认旧仓归零、旧订单清掉，再开新方向。

替换止损时，先确认新止损已经挂上，再撤旧止损。保护被拒、过期、触发后执行失败或数量盖不住实仓时，停止加仓。实仓仍能读到时，补保护；裸露超过允许时间后只减仓退出。Demo 在限额文件没写裸露时间时，默认 120 秒。账户或网络状态未知时不反向开仓。

用户流事件只当提示。断线、过期或漏事件之后，用 REST 快照对账。仓位不以内存里的两张单为准。

## 限额

`config/limits.yaml` 里的 `capital_usdt`、`max_notional_usdt`、`max_daily_loss_usdt`、`max_unprotected_seconds` 现在都是空的。空着时，生产入口拒绝增仓。研究里的 4.8% 单位风险、最多三档、约 3.75 倍名义，以及强平前 0.1% 的止损间距，不是生产安全保证。

生产下单还要环境变量 `STARQUANT_ALLOW_PROD_ORDERS=yes`，并且命令行 `--max-notional-usdt` 为正、且不超过文件里的名义上限。本轮实施和验证不发送真实资金订单。

## 记录

每一轮在状态目录追加一行 `journal.jsonl`：时间、运行或停机模式、是否冻结、原因、实仓、均价、余额、标记价、最新价、保护是否覆盖、普通单和条件单身份、手续费读取结果、资金费读取是否成功、游标和对账提示。发送订单时另记一行客户端身份、阶段和本次传输耗时。文件不进版本库，也不写密钥。

满 30 个自然日之后，用这份流水核对运行和停机窗口、信号、实仓、保护、成交、费用、资金费、断线和对账差异。某一种订单在这 30 天里没有自然出现，不能当成那条路径已经通过。一个月盈利也不说明以后还能盈利。

## 还不能当作完成

本机在 2026-09-28 访问 `demo-fapi.binance.com` 和 `fapi.binance.com` 的 `/fapi/v1/time` 返回地区限制。`testnet.binancefuture.com` 能打开，但那不是官方 Demo，代码不会改去那里。没有 Demo 密钥，就没有远端回读。连续 30 个自然日也还没有开始。门槛结论在 [forward_audit.md](forward_audit.md)。
