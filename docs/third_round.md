# 共同有限会话的项目选择 — 2026-10-01

固定默认与半风险完成 Coinquant 的 795 次有限手动会话，使用实际
`btc_perp.runner.run_cycle`，按真实 stop 路径收尾，进程关闭期间不运行模型。
每个账户独立从 CNY 10,000 起，无追加，原窗口和 150%/<50% 目标不变。

| 共同历史模型 | 期末 CNY | CAGR | 连续 MDD | 成交记录 |
| --- | ---: | ---: | ---: | ---: |
| Coinquant 默认 | 1,951,753.81 | 119.23% | 44.11% | 1,561 |
| Star 默认 | 7,772.36 | −3.68% | 51.75% | 49 |
| Star 半风险 | 9,174.88 | −1.27% | 38.21% | 41 |

三个现金账户独立重建成交、手续费、资金费和已实现盈亏，审计均通过，
未决会话均为0。两个 Star 候选各39,734个周期、12个观察变化冻结周期。
这支持日常开发方向为 Coinquant 合约 + Spotquant 现货，Star 留作固定
研究对照；半风险降低回撤但仍亏损，不迁移或替换默认合约模型。原连续
因果117.31%属于不同运行/费用/资金费/估值假设，不能与本表混作同一账户。

原件由共同测量入口托管，不在本仓复制巨大 JSON：

- [协议与限制](https://github.com/geniusgrok/coinquant/blob/codex/btc-first-round-20261001/research/third-round-PROTOCOL.md)
- [完整账户及核账结果](https://github.com/geniusgrok/coinquant/blob/codex/btc-first-round-20261001/evidence/third-round-20261001/RESULT.md)

经济来源是 Coin 00a6849 / Star 882b521。读取200ms、写入1000ms、手续费
0.00075、兑换各0.001、官方 trade/mark、资金费和逐笔数量上界共享；模型
保持已有 IOC/MARKET 及 MARK_PRICE/CONTRACT_PRICE 行为。共享预热来自
2019-12，各自等待窗口完整。snapshot历史桥接简化了原生请求图，数量
上界不是历史订单簿，部分市场单终态、保证金档位和初始化峰值是研究代理。
缺失 mark 采用原已接受的事后边界。原生读写时延与完整交易协议尚未验证。
不能把这个表当作原生预期或把会话数当作实机性能数据。

本轮仅把已完成小时的通道查找改为直接索引；原 fallback、策略和经济
内核保留。完整离线检查323项通过/10项跳过，经济报告只发生提交/run_id
刷新而经济字段与输入不变；原件保留记录来源。七类本机故障入口重新通过，
记录见 [local-execution-third-round-20261001.json](../reports/local-execution-third-round-20261001.json)。
ruff format/lint、mypy均通过。

没有账户请求、交易或真实观察日。Demo/Live仍NO_GO。没有新选参或共同
压力晋升，运行器暂不正式退休；Native Demo闭环、状态恢复和实际操作负担
达到门槛后，才能进行剩余迁移和归档。不要为了研究比较启动三个日常服务，
也不要让两个合约项目共管同一账户。
