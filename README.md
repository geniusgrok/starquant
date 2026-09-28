# BTCUSDT 账户

私人研究。只有版权人本人可以使用，禁止实盘，禁止他人复制或二次创作。许可见 [LICENSE](LICENSE)。

## 账户

一个币安 BTCUSDT U 本位永续账户：

- 起始 10,000 元人民币，中间不加钱
- 单向逐仓，保证金按 20 倍计算
- 可以做多，也可以做空
- 测量从 2020-01-01 到 2026-09-20，结束日不含

已记录结果：期末 1,416,356 元，年化 109.0%，最低权益除以峰值 0.527。口径和配置里没有写出的规则见 [docs/btc_account.md](docs/btc_account.md)。

## 复现

行情放在仓库旁的 `data/`，不进版本库。至少要有 `data/btcusdt_1m.npz`，以及同目录的资金费和人民币汇率。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
python -m btc_perp --measure
```

不带 `--measure` 只打印拒绝，然后退出。它不下单，也不启动会话。

## 目录

| 路径 | 内容 |
| --- | --- |
| `btc_perp/` | 配置、费率、拒绝下单的接口、全样本入口 |
| `scripts/frontier.py` | 回放内核 |
| `config/btc_account.yaml` | 这一份账户配置 |
| `reports/btc_account_measure.json` | 已记录的全样本结果 |
| `docs/btc_account.md` | 测量口径 |

## 检查

```bash
ruff format --check . && ruff check . && mypy && pytest -m "not network"
```

提交前的密钥扫描需要本机的 gitleaks，并执行 `git config core.hooksPath .githooks`。CI 用同一份配置扫全部历史。约定见 [SECURITY.md](SECURITY.md)。

## 许可

专有软件，保留全部权利。版权人只能把它用于私人研究。禁止实盘。其他人不得复制、修改或二次创作。能在网页上读到本仓库，不构成使用许可。
