# Starquant

版本 **0.1.0**。版权人本人的 BTCUSDT U 本位永续账户程序，使用单向持仓、逐仓和 20 倍保证金设置。20 倍不是账户恒定敞口。使用权见 [LICENSE](LICENSE)。

生产新增风险默认关闭；**DEMO_GO = NO_GO，SMALL_LIVE_GO = NO_GO**。原生前向执行尚未通过本人 Demo 账户的开仓、保护实际触发、故障恢复和连续 30 天验证。离线测试不能代替远端验收。

## 安装

当前验证环境为 Linux、Python 3.12，依赖按 [requirements.lock](requirements.lock) 安装。在仓库根目录运行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
git config core.hooksPath .githooks
python -m btc_perp --help
```

## 使用与配置

每个账户命令必须显式选择 `--environment demo` 或 `prod`。密钥只从环境变量读取，设置方式与权限要求见 [SECURITY.md](SECURITY.md)。先核对账户：

```bash
python -m btc_perp check --environment demo
python -m btc_perp run --environment demo --max-notional-usdt 200 --dry-run --once
```

`check` 和 `--dry-run` 不向交易所写入，但会读取真实账户并维护本地状态。**没有 `--dry-run` 的 `run --once` 会执行一轮真实前向操作，再尝试安全停机；它不是模拟。** `run` 默认持续轮询，`config/btc_account.yaml` 的 `session_seconds` 不会让它在 300 秒后结束。

策略配置在 [config/btc_account.yaml](config/btc_account.yaml)，资金与裸露时间限额在 [config/limits.yaml](config/limits.yaml)。当前限额为空，生产不能新增风险。生产还要求已核验的账户 UID、`STARQUANT_ALLOW_PROD_ORDERS=yes`、正的命令行名义上限及明确的密钥权限。默认开仓通道须预热 **1008 个完整连续小时（42 天）**；不足时没有对应通道信号，但存量保护、减仓及梯度加仓仍可能执行。`check` 不验证行情预热。

默认状态为 `~/.local/state/starquant/<demo|prod>/`，切换源码目录不会新建账本。一个账户只能由一个项目管理；本地锁只覆盖同机同系统用户。不要删除状态、重置峰值或接管来跳过未知历史。

`stop`、`flatten`、`takeover`、`rearm`、`resolve`、`resume` 的操作、退出状态和恢复步骤见 [docs/forward.md](docs/forward.md)。停止进程后，本地移动止损、通道与权益出场不再运行，只剩最后确认的交易所保护。入场与保护建立不是原子操作，日损及资金上限不保证最大累计亏损。

## 本地检查

```bash
python -m compileall -q btc_perp tests
python -m pytest -m "not network"
```

历史研究和改造记录保存在 [archive/pre-slim-20261008](https://github.com/geniusgrok/starquant/tree/archive/pre-slim-20261008)。
