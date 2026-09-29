# 当前状态（2026-09-29）

## 可复现的研究结果

冻结窗口 2020-01-01 至 2026-09-20 UTC（右端不含），人民币 10,000 元起，不追加资金。参数仍为 1008/192 小时通道、3 档、20 倍逐仓保证金设置。原止损在分钟内有效，新移动止损从下一分钟有效。当前三份正式报告由本版代码和输入重新生成；泛化命令已重跑但未通过输入校验，旧同分钟收紧模型的数字只留在 Git 历史。

| 命令 / 报告 | 期末人民币 | 年化 | 最低权益/峰值 | 150% 目标 |
| --- | ---: | ---: | ---: | --- |
| `measure` / `reports/btc_account_measure.json` | 1,830,998 | 117.16% | 0.526 | 未达 |
| `causal` / `reports/btc_account_causal.json` | 1,839,663 | 117.31% | 0.528 | 未达 |

57 多、35 空、80 次止损。代码的诊断通过线是年化 100% 且最低比值高于 0.5；150% 目标对应约 4,716,653 元。回放完成和真实成交闭环是不同事实。成本/参数扰动与资金费未知槽位的固定情景见 [稳健性报告](reports/btc_account_robustness.json)。[泛化校验记录](reports/btc_account_generalization.unverified.json)标记 `verified=false`、`data_validated=false`、`path_complete=false`；2018-02-08 00:29 UTC 起早期 BTC 现货源行情连续缺失 2,011 分钟，旧跨行情收益数字不可沿用。结论与证据范围见 [研究说明](docs/btc_account.md)。

BTC 资金费 7,305 官方、56 溢价代理、1 缺失补零。数据结构验证成功不等于这些估算获得官方验证；原始三份输入哈希在 [数据说明](docs/btc_account.md#数据)。USDT/USD 平价、固定维持保证金档位、成交 OHLC 代理标记价及分钟内路径仍是模型边界。收益对止损成本和 2020 年高度敏感，没有干净的 BTC 样本外。

## 前向状态与支持范围

生产增仓默认关闭。当前环境没有账户密钥，也没有币安 Demo 远端开仓、保护触发、故障演练或连续 30 个自然日流水；**DEMO_GO = NO_GO，SMALL_LIVE_GO = NO_GO**。离线假交易所和本地套接字检查不能代替远端协议确认。同方向新旧 close-all 条件单并存、条件单父子回包仍需以实际交易所响应核对。门槛见 [forward_audit.md](docs/forward_audit.md)。

`run` 是连续循环，不是 300 秒真实 Demo。停机时只剩已确认的交易所止损与灾备止盈；本地移动止损、通道和权益出场不继续计算。状态默认 `~/.local/state/starquant/<demo|prod>/`，账户锁在 `~/.local/state/starquant/locks/`，仅同机同用户有效。不同项目不可共管一个账户。每轮生成 journal，跨 UTC 日用 SQLite 在线备份生成每日副本；备份不自动跨磁盘。历史窗口不可证明覆盖时冻结新增风险，不通过删除状态、接管或重置峰值绕过。恢复步骤见 [forward.md](docs/forward.md)。

`config/limits.yaml` 仍为空，生产不允许新增风险。日损和资金上限主要阻断新增风险，并非最大累计亏损保证；必要的已确认归属减仓与保护继续走保守路径。没有权限或账户身份时不会把降险假报完成。

## 当前输入和验证

BTC 正式回放的三份输入与上一版源文件哈希一致：

| 文件 | SHA-256 |
| --- | --- |
| `data/btcusdt_1m.npz` | `259ceaae3bbc7fc7d11f128b3b7ff0658651e56ef0fdd57cf0d4e9c95d197c0a` |
| `data/funding.npz` | `0682df98242a6fccfe86da66a1da871c2af1d0b955fac6d38734b0059b94cb7a` |
| `data/usdcny_frankfurter.json` | `67606315ea34c0301e0129ac8fc27056099986d9fbd58a552a07f140cdd05bb5` |

泛化用 ETH/SOL/早期 BTC 现货行情已重新构建；SOL 用官方日档补齐五个整日（2022-02-26 至 28 日、2022-04-01 至 02 日），并按实际结算小时纳入此前漏记的 75 次两小时资金费。ETH/SOL 的 2026-09 各 57 个非官方八小时结算槽位仍按零占位；早期 BTC 现货经 31 个官方日档补齐后仍留上述连续缺口。重新构建的五份资产文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `data/assets/eth_1m.npz` | `d91a2ed6db95d646f986991a84cbd6d5dbb259cd63b61adcb6c683c90f263c68` |
| `data/assets/sol_1m.npz` | `de510bdd5a87ffee18ab94b093cbc22d8b1766a6afda1167956f9bbbda9ba664` |
| `data/assets/btc_spot_2017_1m.npz` | `f411df53426234a2ae0f55d3b88606f831c32011502de9b05677c96891b3c61f` |
| `data/assets/eth_funding.npz` | `b5b1bb5aa048a39bc343e25297458a58833c44867611134d9c2b3590b3353483` |
| `data/assets/sol_funding.npz` | `26ce7761075e99abd2a9eff6925c44b739ece384249b71913251a1e5915cca64` |

当前可用结论以三份已验证报告、泛化未验证记录及离线测试为准；各报告的 `provenance` 列出运行源码提交和文件哈希。操作系统目标是 Linux、Python 3.12、锁定依赖。同一账户多机器并发、原生 Windows 和真实连续运行尚无支持证明。
