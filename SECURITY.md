# 安全约定

许可见仓库根目录的 [`LICENSE`](LICENSE)：仅版权人本人可以使用。版权人可以先接自己的币安 USDⓈ-M Demo，再在本人写明的资金上限内做小资金验证。第三方没有复制、修改、二次创作或交易的权利。公开可见不构成使用许可。生产增仓默认关闭。

**密钥。** Demo 用 `STARQUANT_DEMO_API_KEY` / `STARQUANT_DEMO_API_SECRET`。生产用 `STARQUANT_PROD_API_KEY` / `STARQUANT_PROD_API_SECRET`。只从环境变量读取。不要写进仓库、SQLite、日志或异常文本。密钥不得开通提币和划转。本仓库没有提币或划转调用。Demo 失败不会改去生产域名。生产下单还要 `STARQUANT_ALLOW_PROD_ORDERS=yes`，并且 `config/limits.yaml` 里的资金、名义、单日损失和裸露时间都是正数。

研究回放不读密钥。旧的 `btc_perp.exchange.BinanceExchange` 不会发送订单。前向订单只走 `btc_perp.binance_client`。

## 不进仓库的东西

凭据一条都不行，测试里也不行，注释掉也不行。

- 交易所 API key / secret
- 任何云服务或模型服务的 key、token、密码
- SSH 私钥、`.pem`、`.env`、`env.sh`

研究回放不读密钥。不要在仓库里放一份“先跑通再换掉”的 key。写进过文件的密钥就当作废，去交易所重发。

## 怎么挡

1. 提交前：`.githooks/pre-commit` 用 `gitleaks` 扫暂存区。安装：`git config core.hooksPath .githooks`。
2. 推送前：`.githooks/pre-push` 扫将要进入远端的提交。
3. CI：`.github/workflows/ci.yml` 用钉死的 gitleaks 8.30.1 扫全部历史。密钥进了历史，删掉文件不会让它消失。

这三层都能被绕过或只能事后发现。`--no-verify` 不是日常开关。GitHub 自带的 push protection 认不出币安密钥：币安不在它的 partner pattern 列表里。不要指望那一层。

`tests/test_secret_scanning.py` 检查这份 `.gitleaks.toml` 仍然抓得住一个当场生成的假密钥。本机没装 gitleaks 时这条测试会跳过；CI 的 Secrets 门每次都会扫。

误报加进 `.gitleaks.toml` 的 allowlist 时，按“它是什么”写，不要按目录整片放行，并写一句它为什么不可能是密钥。

## 真漏了

先到交易所作废那个 key，再看调用记录。清理 git 历史不能代替作废：别人可能已经克隆过。不要开公开 issue 讨论密钥，走 GitHub 的私有漏洞报告。
