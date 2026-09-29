# BTCUSDT 账户

私人研究。只有版权人本人可以使用。版权人可以先跑自己的币安 USDⓈ-M Demo，再在本人写明的资金上限内做小资金验证。第三方没有复制、修改、二次创作或交易的权利。生产增仓默认关闭。许可见 [LICENSE](LICENSE)。

一个币安 BTCUSDT U 本位永续账户：起始 10,000 元人民币，中间不加钱，单向逐仓，保证金按 20 倍计算，多空都可以新开仓。历史测量从 2020-01-01 00:00 UTC 到 2026-09-20 00:00 UTC，结束日不含。`measure` 仍按每段 300 秒的研究会话回放，那不是一个月真实时间 Demo。真实时间前向运行见 [docs/forward.md](docs/forward.md)。

## 模型

1008 小时唐奇安突破，192 小时通道出场，沿有利方向最多加到 3 个单位。窗口没凑满之前没有信号。收盘权益低于收盘峰值的 82% 时，新开仓风险减半。路径权益落到路径峰值的一半时平仓。参数和费率在 [config/btc_account.yaml](config/btc_account.yaml)，口径在 [docs/btc_account.md](docs/btc_account.md)。

## 已记录结果

`python -m btc_perp --measure` 的正式结果在 [reports/btc_account_measure.json](reports/btc_account_measure.json)：

- 期末 2,029,866 元，年化 120.52%，最低权益/峰值 0.526（2021-05-19）
- 57 笔多头，35 笔空头，80 次止损，92 次平仓
- 代码里的通过线是年化 100% 且权益/峰值高于 0.5。按 150% 年化，同一起点大约是 4,716,653 元，这次没有到达
- 这是同根收盘成交。收盘后下一根开盘的对照在 [reports/btc_account_causal.json](reports/btc_account_causal.json)：期末 2,039,229 元，年化 120.67%，最低比值 0.528，笔数仍是 57/35/80。150% 仍然没有到达。2026-09-01 00:00 UTC 的资金费槽位没有官方结算价

同一条行情上的压力见 [docs/measure_protocol.md](docs/measure_protocol.md)。手续费 ×1.5、滑点 ×2、开仓深度 10% 和把分钟路径对调之后，年化仍在 115% 以上，最低比值仍高于 0.5。随机跳过 20% 的会话之后，期末 24,292 元，年化 14.12%，最低比值 0.467。关掉 82% 缩量之后，期末 146,483 元，年化 49.11%，最低比值 0.476。

这些压力没有动到止损成交和参数本身。`python -m btc_perp robustness`（[reports/btc_account_robustness.json](reports/btc_account_robustness.json)）补上了这两项，结论要保守：止损成交只多 0.1% 的不利滑点，账户就会跌破 0.5 线并被回撤锁永久停机，期末约 11 万元；54 个把参数移动 5% 到 10% 的邻居里有 13 个（24%）同样如此；去掉 2020 年，之后的年化约 54%。所以 120% 是这条行情上的一条路径，不是稳健估计，也不能用来推算小资金实盘的收益。

`python -m btc_perp generalization`（[reports/btc_account_generalization.json](reports/btc_account_generalization.json)）把同一套规则放到没调过的数据上：ETHUSDT、SOLUSDT 永续和 2017–2019 的 BTC 现货。基准原样运行，三条都以回撤锁结束，年化 +1.7%、−2.6%、−1.6%，只有 11 到 16 笔交易。也就是说 BTC 2020–2026 的 120% 没有跨资产、跨时期成立。研究用的候选模型（4 个通道长度的集成、波动率目标仓位、ATR 止损、平滑回撤缩仓、交易所杠杆 5 倍）在四条行情上年化都是正的，但很低：预先定好的一组参数在 BTC 2020–2026 是 +4.1%，最低比值 0.413；36 个网格点的中位数在 BTC/ETH/SOL/2017 分别是 +6.5%、+8.6%、+4.6%、+37.5%。候选模型只在研究里，没有接入前向循环，也没有换掉基准。BTC 2020–2026 已经用来选过基准，这段数据上没有干净的样本外。

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

`python -m btc_perp measure` 把全样本拆成一段一段的手动会话。不带参数只打印入口说明，不会下单，也不会启动会话。

```bash
python -m btc_perp causal
python -m btc_perp check --environment demo
python -m btc_perp run --environment demo --max-notional-usdt 200 --once
python -m btc_perp stop --environment demo
python -m btc_perp resolve --environment demo --client-id <编号> --yes   # 人工确认后关闭一张查不到的入场单
```

Demo 密钥用 `STARQUANT_DEMO_API_KEY` 和 `STARQUANT_DEMO_API_SECRET`。生产还要 `STARQUANT_ALLOW_PROD_ORDERS=yes`、`STARQUANT_ACCOUNT_UID`（账户 UID，启动时核对）和填好的 [config/limits.yaml](config/limits.yaml)。细则在 [docs/forward.md](docs/forward.md)，门槛结论在 [docs/forward_audit.md](docs/forward_audit.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `btc_perp/` | 配置、历史测量、前向循环、Demo/生产客户端 |
| `scripts/frontier.py` | 回放内核 |
| `scripts/assets.py` | 下载并合成 ETH、SOL 和 2017–2019 BTC 现货分钟行情（`data/assets/`，不入库） |
| `btc_perp/candidate.py` | 研究用候选模型，未接入前向循环 |
| `config/candidate.yaml` | 候选模型预先定好的设置 |
| `reports/btc_account_generalization.json` | 跨资产、前进验证、自助法和压力结果 |
| `config/btc_account.yaml` | 这一份账户配置 |
| `reports/btc_account_measure.json` | 同根收盘的正式全样本结果 |
| `reports/btc_account_causal.json` | 收盘后下一根开盘的对照 |
| `config/limits.yaml` | 生产资金上限，空着就拒绝增仓 |
| `docs/forward.md` | Demo 前向怎么启动和停 |
| `docs/forward_audit.md` | 前向门槛：DEMO_GO 与 SMALL_LIVE_GO |
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

专有软件，保留全部权利。只有版权人本人可以使用：先 Demo，再在写明的上限内做本人小资金验证。其他人不得复制、修改、二次创作或交易。能在网页上读到本仓库，不构成使用许可。生产增仓默认关闭。
