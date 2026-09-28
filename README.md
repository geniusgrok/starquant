# BTCUSDT 账户

私人研究。许可见 [`LICENSE`](LICENSE)：只有版权人本人可以使用，禁止实盘，禁止他人复制或二次创作。

一个币安 BTCUSDT U 本位永续账户，起始 10,000 元人民币，中间不加钱，单向逐仓，保证金按 20 倍计算，可多可空。全样本复现：

```bash
PYTHONPATH=. python -m btc_perp --measure
```

口径、配置里没有写出的减半规则，以及实盘拒绝，写在 [`docs/btc_account.md`](docs/btc_account.md)。不带 `--measure` 的入口不下单。树里没有 API key。

## 仓库里有什么

- `btc_perp/`：配置、费率常量、拒绝下单的交易所接口、手动会话、全样本入口。
- `scripts/frontier.py`：测量用的回放内核。
- `config/btc_account.yaml`：这一份账户配置。
- `reports/btc_account_measure.json`：已记录的全样本结果。
- `data/`：本地行情，不进版本库。

## 检查

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
ruff format --check . && ruff check . && mypy && pytest -m "not network"
```

密钥扫描：`git config core.hooksPath .githooks`，并安装 `gitleaks`。CI 用同一份 `.gitleaks.toml` 扫全部历史。

## License

Proprietary — all rights reserved. Full terms in [`LICENSE`](LICENSE).

The copyright holder may use this repository only for private research.
Live trading is prohibited. No other person may copy, modify, or create
derivative works. Being able to read a public checkout is not a license.
