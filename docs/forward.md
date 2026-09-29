# 前向账户操作与恢复

仅供版权人本人的 BTCUSDT U 本位永续账户：单向、逐仓、20 倍保证金设置。生产增仓默认关闭。`run` 是真实时钟连续轮询，历史 `measure` 的 300 秒手动会话不是它的运行时长。离线测试不构成交易所协议验收；当前门槛见 [forward_audit.md](forward_audit.md)。

## 身份、状态和限额

| 项 | Demo | 生产 |
| --- | --- | --- |
| REST | `https://demo-fapi.binance.com` | `https://fapi.binance.com` |
| 密钥变量 | `STARQUANT_DEMO_API_KEY` / `STARQUANT_DEMO_API_SECRET` | `STARQUANT_PROD_API_KEY` / `STARQUANT_PROD_API_SECRET` |
| 账户身份 | 密钥指纹绑定；换密钥须核验旧状态 | `STARQUANT_ACCOUNT_UID` 必填，现货账户 UID 回读一致才运行 |
| 默认状态 | `~/.local/state/starquant/demo/` | `~/.local/state/starquant/prod/` |

`--state-dir` 必须是绝对路径，直接指向环境状态目录；`STARQUANT_STATE_DIR` 必须是绝对路径，程序在其下加环境名。启动打印环境、已核验 UID（Demo 显示 key-bound）和最终路径。旧仓库内 `state/<环境>/` 不会自动迁移；先核对账户、意图、峰值和最近备份，再把完整旧状态移到固定位置。绝不靠删除 SQLite 新建账户恢复交易。

状态目录锁和账户级 `flock` 锁限于同机同系统用户，后者固定在 `~/.local/state/starquant/locks/`，不能通过另一工作目录或 `STARQUANT_LOCK_DIR` 改写。跨机器或不同项目没有共同锁；**一个账户只能由一个项目管理**，从别的程序交接前须确认旧仓位和 close-all 保护。支持 Linux/macOS 的 `fcntl`；本次离线验证环境为 Linux/Python 3.12/锁定依赖。

密钥只读环境变量，不存库和报告。生产 `run` 新增风险要求 `STARQUANT_ALLOW_PROD_ORDERS=yes`、正的命令行上限、填好的 [limits.yaml](../config/limits.yaml) 以及权限元数据明确表明能做合约、不能提币或划转。缺失、null 或错误类型的危险权限字段不放行。`stop`、`flatten` 可在账户 UID 已确认时继续处理自有风险，即使辅助权限元数据不可读；UID 不明时拒绝账户写入。程序不自动更改杠杆、持仓模式或逐仓模式。

`capital_usdt` 限制用于计算仓位的权益，名义上限取文件和命令行较小者；`max_daily_loss_usdt` 按 UTC 日首次有效权益观测冻结新增风险，**不会自动平仓或保证累计最大亏损**。止损可能跳空、滑点或执行失败。账户回撤锁、资金划转冻结和人工接管是各自独立的状态，不能用资金上限代替。生产研究参数（4.8% 单档风险、最多三档、20 倍逐仓）不构成安全保证。

## 运行与停止

```bash
python -m btc_perp check --environment demo
python -m btc_perp run --environment demo --max-notional-usdt 200 --dry-run --once
python -m btc_perp run --environment demo --max-notional-usdt 200
python -m btc_perp stop --environment demo
python -m btc_perp flatten --environment demo --once
python -m btc_perp resume --environment demo
```

`check` 与 `--dry-run` 不向交易所写入。`run --once` 做一轮后安全收尾；正常周期且最后停机核验完成返回 0。业务周期异常冻结、收尾未完成、快照未知或中断返回非零。`run_state.json` 记录 `phase`、`exit_code`、收尾的剩余项目；第二次 SIGINT/SIGTERM 在有界收尾期间不提前打断最终状态写入。强杀、断电无法保证收尾，重启要重新对账。

`stop` 撤销本程序会增仓的挂单，保留实仓上已确认的止损和灾备止盈；空仓时清理本程序的保护。保护意图/子单结果未知、活动外来订单、裸仓或账户读数未知均不能报 `settled`。`flatten` 是用户明确发起的只减仓清仓；它也必须确认没有未决订单与实仓才报告完成。停机/平仓请求文件带环境标识，`run` 会响应；`resume` 只删除请求文件，不解除其他风险冻结。

交易事实以 REST 快照与原生订单身份为准。原程序的用户流模块保留作离线研究，但不在主循环建连或重连，避免保护与减仓被 keepalive 阻塞。每轮写 `journal.jsonl`，轮转日志；跨 UTC 日首次轮次用 SQLite online backup 留一份一致性副本，保留最近七份。备份失败会出现在本轮提示，仍须人工保存完整状态到另一磁盘。控制状态文件、日志和备份均不入库。

## 订单保护和归属

程序先持久化不可变订单身份，再发送，结果未知只查原身份；入场/加仓不会换 ID 重下。条件保护单使用 `/fapi/v1/algoOrder`、`closePosition=true`、`CONTRACT_PRICE`，普通市价单使用 `/fapi/v1/order`。先预检两侧价格，先确认止损才发灾备止盈；替换旧止损先确认新保护再撤旧保护。交易所未确认的新旧 close-all 并存及子单响应格式尚无真实账户验证，拒单或 ACK 丢失时保留原身份并报告未完成，不能假报覆盖。

普通成交靠原生 `orderId` 归因，条件单父单 `FINISHED` 后查 `actualOrderId` 子单；开放普通子单若本地 client ID 不同，仍可凭已核验原生 ID 归属。方向和时间相同不足以认领。保护成交阶段、数量、子 ID 和“尚未吸收”标志一次提交；账本、成交游标和吸收确认一起提交。已有健康的活动止损/止盈不阻塞正常加仓，但**未知保护、撤销或子单**阻断所有新增风险，并阻止停机声称完成。

行情分钟和小时必须完整且新鲜；新风险用本轮最新快照和不超过 30 秒的信号。仓位归属不明时暂停自动策略出口、反手及策略记忆更新，不能用旧记忆平掉外来仓位；用户明确 `flatten` 仍可处理实际仓位。已核验归属的仓位可补保护，裸露超过预算则只减仓。进程停止后不会执行本地动态移动止损、通道或一半峰值出场，只剩最后确认的交易所保护；入场与保护建立不是原子操作。

## 人工恢复

```bash
python -m btc_perp takeover --environment demo --once
python -m btc_perp resolve --environment demo --client-id <编号> --yes
python -m btc_perp rearm --environment demo --yes
```

`takeover` 明确接管当前实仓并持续冻结新增风险；之后部分减仓、全平仍同步真实仓位。空仓、无任何活动订单或未决保护，且历史覆盖已证明后，`rearm --yes` 可解除人工接管，**不会同时重置亏损峰值**。普通回撤锁要在同样的空仓/无未决条件下显式 `rearm --yes`，此时把回撤基准设为当前权益；累计绩效峰值不归零。资金划转冻结也要核对后按该命令解除。`resolve` 只针对操作员核对过且交易所再次明确回答“不存在”的原身份；查询失败不放行。

最近成交和资金流水默认最多各 1000 条、近七日。上次确认时间超过窗口、旧副本无法覆盖期间、或 1000 条已经截断时，冻结新增风险并指出缺口。`takeover` 可以管理已明确接管的当前仓位，**不会填造旧成交/资金流水**；覆盖不足时 `rearm` 仍拒绝。应离线核对交易所完整对账单与最近有效备份，恢复原有峰值、资金锁、未决意图和成交游标，重新只读检查。无法证明旧事实时保持冻结，手动在交易所处理风险；当前版本没有任意历史导入或强制跳过命令。

## 研究与远端边界

本仓库只在本地假交易所验证了故障恢复与订单状态。还没有本人 Demo 的实际开仓、条件单触发、断线恢复和连续 30 天记录。本机对币安期货域名受地区限制。`DEMO_GO = NO_GO`，`SMALL_LIVE_GO = NO_GO`；不要把历史 [研究结果](btc_account.md) 当成前向执行或实际利润验证。
