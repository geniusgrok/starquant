# 安全约定

使用权见 [LICENSE](LICENSE)。仅供版权人本人账户，生产新增风险默认关闭，当前 Demo 与小资金实盘均为 **NO_GO**。账户操作与恢复见 [docs/forward.md](docs/forward.md)。

## 凭据与权限

Demo 使用 `STARQUANT_DEMO_API_KEY` / `STARQUANT_DEMO_API_SECRET`；生产使用 `STARQUANT_PROD_API_KEY` / `STARQUANT_PROD_API_SECRET`。密钥只从环境变量读取。不得把密钥、token、密码、SSH 私钥、`.pem`、`.env` 或带凭据的脚本放进仓库、测试、SQLite、日志或异常文本。

密钥不得开通提币或划转。本程序没有提币或划转调用，Demo 失败不会转用生产域名。生产要求 `STARQUANT_ACCOUNT_UID` 与远端回读一致；新增风险还要求 `STARQUANT_ALLOW_PROD_ORDERS=yes`、完整的正数限额，以及权限元数据明确允许合约、禁止提币和划转。权限字段缺失或含糊时拒绝新增风险。不要用新的状态目录规避账户绑定、冻结或未决订单。

## 密钥扫描

安装 gitleaks 后启用仓库 hooks：

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-commit` 扫暂存区，`.githooks/pre-push` 扫将进入远端的提交，CI 使用固定版本 gitleaks 扫完整历史。本地缺少 gitleaks 时 hook 只提示并放行；`--no-verify` 也能绕过本地检查。CI 在推送后运行，不能依靠服务端保护识别所有交易所密钥。

`tests/test_secret_scanning.py` 用运行时生成的假密钥检查自定义规则，本机缺少 gitleaks 时跳过。误报 allowlist 必须限定具体值或形态，说明为什么不可能是密钥，不按整个目录放行。

## 泄漏处理

先在服务提供方作废并重发凭据，核对账户调用记录，再清理文件和 Git 历史。删除文件或改写历史不能撤回已有克隆与备份。不要在公开 issue 贴凭据，使用 GitHub 私有漏洞报告。
