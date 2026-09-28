# 安全约定

许可见仓库根目录的 [`LICENSE`](LICENSE)：仅版权人本人研究，禁止实盘，禁止他人复制或二次创作。公开可见不构成使用许可。

**禁止实盘。** 不要把本仓库接到真实账户的下单接口。`btc_perp.exchange.BinanceExchange` 会拒绝下单。研究回放使用本地行情，不需要交易所密钥。

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
