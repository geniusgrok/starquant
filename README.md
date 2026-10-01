# Starquant：BTCUSDT 账户研究

第三轮完成共同历史模型下795次有限会话：默认−3.68% CAGR / 51.75% MDD，
半风险−1.27% / 38.21%；Coin默认119.23% / 44.11%。完整现金核账通过，
保留Coin合约、Spot现货为日常开发方向，Star仅作研究对照；没有原生晋升
或正式退休。方法、输入/源码身份及简化snapshot的限制见
[第三轮说明](docs/third_round.md)。原连续因果账户的117.31%不属于这个场景。

2026-10-01 首轮：`python -m scripts.restore_btc` 按原始 SHA 恢复 BTC 输入；
`python -m btc_perp first-round` 复现风险、加仓和空头的 25 个因果对照。
候选未通过登记的晋升门槛，默认配置保留，详见 [首轮结果](reports/first_round.md)。

私人研究，使用范围见 [LICENSE](LICENSE)。生产新增仓位默认关闭。历史研究账户从人民币 10,000 元起，单向逐仓、可多可空，20 倍是保证金设置，不等于账户恒定 20 倍敞口。冻结窗口为 2020-01-01 00:00 至 2026-09-20 00:00 UTC（右端不含）。

## 当前结果

| 可复现命令 | 成交假设 | 期末人民币 | 年化 | 最低权益/峰值 | 多 / 空 / 止损 |
| --- | --- | ---: | ---: | ---: | ---: |
| `python -m btc_perp measure` | 同根收盘；连续衔接的 300 秒手动会话 | 1,830,998 | 117.16% | 0.526 | 57 / 35 / 80 |
| `python -m btc_perp causal` | 收盘获知信号，下一分钟开盘成交 | 1,839,663 | 117.31% | 0.528 | 57 / 35 / 80 |

两种回放都让本分钟内**此前已挂的止损**生效；用这分钟高低价收紧的移动止损从下一分钟起生效。旧模型允许新止损在同一分钟触发，其 2026-09-28 数字不能与本版混用。代码中的 `passed` 是年化至少 100% 且最低比值高于 0.5 等诊断门槛；150% 经济目标（期末约 4,716,653 元）**未达到**。报告中的 `path_complete` 只表示走完回放数组，`execution_closed=false`，不表示交易所撮合已验证。

[正式测量](reports/btc_account_measure.json)、[因果对照](reports/btc_account_causal.json)和[稳健性](reports/btc_account_robustness.json)已由当前代码及冻结输入重跑并通过各自的数据与路径校验。止损额外不利滑点 0.1% 会触发回撤锁，54 个邻近参数中 14 个跌破一半峰值或以锁结束。[泛化校验](reports/btc_account_generalization.unverified.json)因 2018-02-08 00:29 UTC 起的早期 BTC 现货源行情连续缺失 2,011 分钟而失败，旧 ETH/SOL/现货收益及候选网格结果均不再作为本版结论。详细口径见 [docs/btc_account.md](docs/btc_account.md) 与 [docs/measure_protocol.md](docs/measure_protocol.md)。

资金费 7,362 个槽位中 7,305 个来自官方文件、56 个是溢价指数估算、2026-09-01 00:00 UTC 的 1 个缺失并按零计。USDT 按 USD 平价，用前一已公布的 Frankfurter USD/CNY 中间价估值并计假设兑换费；成交价代理标记价，分钟内四点路径和保证金档位均属研究假设。回放不等于 Demo 或实盘收益。

## 复现

使用 Python 3.12 和 [requirements.lock](requirements.lock)。`data/` 不入库；下载与校验范围、源文件和哈希见 [数据说明](docs/btc_account.md#数据)。仓库根目录运行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
python -m btc_perp measure
python -m btc_perp causal
python -m btc_perp robustness
python scripts/assets.py
python -m btc_perp generalization
```

当前官方归档尚有上述现货缺口，`scripts/assets.py` 检出长缺口时返回 2；`generalization` 返回未验证并写 `.unverified.json`，不能用旧报告充当成功复现。运行 `python -m btc_perp` 只打印帮助，不启动会话、不下单。研究参数在 [config/btc_account.yaml](config/btc_account.yaml)；已冻结的起始资金、杠杆和成本必须与 `btc_perp/costs.py` 一致，不一致直接拒绝运行。

## 前向账户

只有本人账户，先核对后运行。前向 `run` 是连续真实时钟循环；历史测量中的 300 秒切片没有停机保护的现实含义。`check` 是只读；`run --once` 会在一轮后尝试安全收尾。Demo 与生产密钥从各自环境变量读取，生产还需要账户 UID、显式开关和填好的资金限额。状态默认固定在 `~/.local/state/starquant/<环境>/`；切换源码目录不会新建账本。详见 [操作与恢复](docs/forward.md) 和 [当前门槛](docs/forward_audit.md)。

```bash
python -m btc_perp check --environment demo
python -m btc_perp run --environment demo --max-notional-usdt 200 --once
python -m btc_perp stop --environment demo
```

没有本人的 Demo 远端回读、实际保护触发和连续 30 天记录。当前 **DEMO_GO = NO_GO，SMALL_LIVE_GO = NO_GO**，见 [PROJECT_STATE.md](PROJECT_STATE.md)。同一账户不要由 Starquant 和其他项目同时管理；本地账户锁只保护本程序在同一机器、同一系统用户的实例。

## 检查与许可

```bash
python -m ruff format --check . && python -m ruff check . && python -m mypy && python -m pytest -m "not network"
```

CI 和密钥检查见 [SECURITY.md](SECURITY.md)。专有软件，第三方没有复制、修改、二次创作或交易权利；网页可见不构成许可。
第二轮：[统一合约比较门槛与本机验收](docs/second_round.md)。
七类故障案例通过并保存于 `reports/local-execution-20261001.json`；与
Coinquant 的九项口径差异尚待消除，默认及半风险继续作为固定研究对照。
