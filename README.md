# BTCUSDT 账户

私人研究。只有版权人本人可以使用，禁止实盘，禁止他人复制或二次创作。许可见 [LICENSE](LICENSE)。

一个币安 BTCUSDT U 本位永续账户：起始 10,000 元人民币，中间不加钱，单向逐仓，保证金按 20 倍计算，多空都可以新开仓。测量从 2020-01-01 00:00 UTC 到 2026-09-20 00:00 UTC，结束日不含。每次手动开一段有限会话，默认 300 秒、每 5 秒看一次，到点或中断就退出，没有后台进程。

## 模型

1008 小时唐奇安突破，192 小时通道出场，沿有利方向最多加到 3 个单位。窗口没凑满之前没有信号。收盘权益低于收盘峰值的 82% 时，新开仓风险减半。路径权益落到路径峰值的一半时平仓。参数和费率在 [config/btc_account.yaml](config/btc_account.yaml)，口径在 [docs/btc_account.md](docs/btc_account.md)。

## 已记录结果

`python -m btc_perp --measure` 的正式结果在 [reports/btc_account_measure.json](reports/btc_account_measure.json)：

- 期末 2,029,866 元，年化 120.52%，最低权益/峰值 0.526（2021-05-19）
- 57 笔多头，35 笔空头，80 次止损，92 次平仓
- 代码里的通过线是年化 100% 且权益/峰值高于 0.5。按 150% 年化，同一起点大约是 4,716,653 元，这次没有到达

同一条行情上的压力见 [docs/measure_protocol.md](docs/measure_protocol.md)。手续费 ×1.5、滑点 ×2、开仓深度 10% 和把分钟路径对调之后，年化仍在 115% 以上，最低比值仍高于 0.5。随机跳过 20% 的会话之后，期末 24,292 元，年化 14.12%，最低比值 0.467。关掉 82% 缩量之后，期末 146,483 元，年化 49.11%，最低比值 0.476。

当前状态和没做完的事见 [PROJECT_STATE.md](PROJECT_STATE.md)。

## 复现

行情放在仓库旁的 `data/`，不进版本库。`--measure` 读取 `data/btcusdt_1m.npz`、`data/funding.npz`、`data/usdcny_frankfurter.json` 和 `data/premium/*.zip`。文件名、时间和 SHA-256 见 [docs/btc_account.md](docs/btc_account.md)。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
python -m btc_perp --measure
```

`--measure` 把全样本拆成一段一段的手动会话：默认每段 300 秒、每 5 秒看一次，这一段返回之后才开始下一段。不带 `--measure` 只打印一句拒绝，然后退出。它不下单，也不启动会话。

## 目录

| 路径 | 内容 |
| --- | --- |
| `btc_perp/` | 配置、费率、手动会话、拒绝下单的接口、全样本入口 |
| `scripts/frontier.py` | 回放内核 |
| `config/btc_account.yaml` | 这一份账户配置 |
| `reports/btc_account_measure.json` | 正式全样本结果 |
| `reports/btc_account_stress.json` | 2026-09-28 的压力数字 |
| `docs/btc_account.md` | 模型、数据、账本和测量做不到的事 |
| `docs/measure_protocol.md` | 测量轮次和压力怎么做的 |
| `PROJECT_STATE.md` | 当前结果和未完成项 |

## 检查

```bash
ruff format --check . && ruff check . && mypy && pytest -m "not network"
```

提交前的密钥扫描需要本机的 gitleaks，并执行 `git config core.hooksPath .githooks`。CI 用同一份配置扫全部历史。约定见 [SECURITY.md](SECURITY.md)。全样本测试在 CI 里会跳过，因为行情不入库。

## 许可

专有软件，保留全部权利。版权人只能把它用于私人研究。禁止实盘。其他人不得复制、修改或二次创作。能在网页上读到本仓库，不构成使用许可。
