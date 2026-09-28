# 安全约定

**这是一个公开仓库。** 推上去的每一行，全世界都能读，而且删掉也收不回来——GitHub 的
fork、克隆、第三方镜像和搜索引擎缓存都不受 `git push --force` 管辖。公开可见不构成使用许可，许可见仓库根目录的 `LICENSE`：仅版权人本人研究，禁止实盘，禁止他人复制或二次创作。

**禁止实盘。** 不要把本仓库接到真实账户的下单接口。BTCUSDT 账户的适配器会拒绝下单；`config/btc_account.yaml` 里的 `live_orders` 打不开这条路径。研究回放使用本地行情，不需要交易所密钥。

这份文件回答三个问题：什么绝对不能进仓库、机械上怎么挡、真漏了怎么办。

---

## 一、红线：这些东西永远不进仓库

**凭据。** 一条都不行，测试里也不行，注释掉也不行，"先跑通再换掉"也不行。

- Binance API key / secret（本仓库唯一真正怕丢的东西）
- 任何交易所、云服务、AI 服务的 key、token、密码
- SSH 私钥、`.pem`、`.p12`、证书私钥
- `.env`、`env.sh` 及任何含实际值的配置文件

**个人身份与财务信息。**

- 身份证、护照、银行卡号、支付账户
- 交易所 UID、账户 ID、子账户标识
- 真实资金账户的权益、持仓、成交明细

**为什么"测试里也不行"**：写进文件的密钥就当已经泄漏。哪怕它一次都没被 `git commit`——
本机可能有 Time Machine 备份，编辑器可能留了 swap 文件，跑过的 shell 有 history。
唯一安全的假设是：值离开了密码管理器，就该被作废重发。

### 凭据正确的存放位置

```
~/Library/Application Support/starquant/env.sh     # chmod 600
```

`deploy/run_live.sh` 从这里读；没有这个文件时回落到 `~/.zshrc` 里的 `export STARQUANT_*`。
两个位置都在仓库之外。`deploy/*.plist` 里**没有**任何凭据，也不要往里加——launchd 的
plist 会被 `launchctl print` 连内容一起打出来。

代码里拿凭据只有一种写法：从环境读，取不到就退出，**不带默认值**。

```python
key = os.environ["STARQUANT_BINANCE_API_KEY"]        # 对：缺了就炸
key = os.environ.get("STARQUANT_BINANCE_API_KEY", "")  # 错：缺了会带着空串往下跑
```

---

## 二、四层拦截，以及每层真实的覆盖范围

诚实地写清楚每层的边界，比说"我们有防护"有用。**尤其是这一条：GitHub 的 push
protection 认不出 Binance 的密钥。**

| 层 | 位置 | 什么时候响 | 对 Binance 密钥 | 怎么被绕过 |
|---|---|---|---|---|
| 1. pre-commit | 本机 | `git commit` 扫暂存区 | ✅ 有效 | `commit --no-verify` |
| 2. pre-push | 本机 | `git push` 扫将要推送的全部 commit | ✅ 有效 | `push --no-verify` |
| 3. GitHub push protection | 服务端 | `git push` 时 | ❌ **无效** | 绕不过，但也拦不住它 |
| 4. CI 的 Secrets 门 | Actions | PR 与 main push，扫**全历史** | ⚠️ **事后** | 改 workflow |

### 第 3 层为什么对 Binance 无效

2026-09-19 核实：**Binance 不在 GitHub secret scanning 的 partner pattern 列表里**。
能自己加模式的 custom patterns 要求仓库属于**组织**并启用付费的 Secret Protection
（$19/月/committer）。本仓库是个人账户下的公开仓库，两条都不满足。

所以第 3 层拦得住 GitHub token、AWS、OpenAI、Slack、Stripe 这些 partner pattern，
**拦不住本仓库唯一真正怕丢的那个东西**。它仍然有价值——它是唯一绕不过的一层——
但不要指望它接住 Binance 的 key。

**别被这个 API 骗了**：`secret_scanning_non_provider_patterns`（通用模式检测，能抓
认证头、连接串、私钥）看起来是个能补上缺口的开关，但它同样要付费的 Secret Protection。
实测把它 PATCH 成 `enabled`，**GitHub 返回 200，状态却仍然是 `disabled`**——它是静默
拒绝，不报错。只看 HTTP 状态码会以为开好了。要确认一个开关真的生效，读回它的值：

```bash
gh api repos/geniusgrok/starquant --jq '.security_and_analysis'
```

### 由此得到的实际结论

**Binance 密钥在"进入公开仓库之前"的拦截，只剩本机那两个 hook，而它们都能被
`--no-verify` 绕过。** 第 4 层是事后的：CI 在推送之后才跑，它红的时候密钥已经躺在
公开仓库里、已经可以被任何人读到了。

这不是设计缺陷，是可用工具的边界。它导出的要求很具体：**`--no-verify` 在这个仓库里
不是一个日常开关。** 用它之前先想清楚绕过的是哪一层，以及后面有没有网。

第 1 层与第 2 层的分工：pre-commit 只看这一次的暂存区；pre-push 看**将要进入远端的
全部 commit**——用 `--no-verify` 提交过的、从别处 cherry-pick 来的，pre-commit 都没
见过。

第 4 层扫全历史而不是只扫这次改动，因为**密钥进了历史，把文件删掉不会让它消失**。
只扫工作树的检查会对着一个仍然公开可读的密钥报平安。

### 新 clone 的第一件事

```bash
brew install gitleaks && bash deploy/install-hooks.sh
```

脚本末尾会自检：造一个伪造的凭据形态，确认它真的被拦下。**看到 `✓` 才算装好**——
配置崩掉时 gitleaks 是 panic 而不是报错，安静地什么都不扫。

`git worktree` 不用再跑，`core.hooksPath` 是仓库级配置，worktree 自动继承。

### 手动全量审计

```bash
gitleaks detect --source . --config .gitleaks.toml --redact
```

约 6 秒扫完全部历史。**基线是零**——看到任何命中都要当真。

---

## 三、误报怎么处理

2026-09-19 第一次跑时报了 117 处，逐个核实后**没有一处是真的密钥**：100 处是 trial
ledger 的 `param_key`，9 处是 sha256 文件摘要，2 处是 SSH 公钥指纹，2 处是 Binance 的
响应头名，其余是测试里写死的假值。它们已经写进 `.gitleaks.toml` 的 allowlist。

再遇到误报，往那个文件加一条，两条规矩：

1. **按"它是什么"写，不按"它在哪个目录"写。** 整片放行 `tests/` 很省事，代价是往测试
   文件里贴一个真密钥从此无人拦截——而那恰恰是最容易发生的泄漏。
2. **写一句它为什么不可能是密钥。** 没写理由的放行，下一个人无法判断该不该收回，
   于是它永远留着。

`tests/architecture/test_secret_scanning_is_alive.py` 是这件事的刹车：allowlist 再怎么
加，一个随机生成的 Binance 形态必须还能被抓出来。那个测试红了，说明口子开得太大了。

这条刹车在这个仓库里比一般项目重要：上面第二节说清楚了，GitHub 那层接不住 Binance 的
密钥，所以 allowlist 放宽的代价没有别的东西替你兜。

---

## 四、真漏了怎么办

**顺序不能反。先作废，再清理。** 清理历史要几十分钟，而密钥在这几十分钟里仍然有效。

1. **立刻去交易所作废那个 key**，重发一对新的。这一步不能等，也不需要任何人批准。
   Binance：API Management → 删除该 key。
2. **确认损失**：`starquant live status` 看仓位，交易所网页看 API 调用记录与提现记录。
   本仓库的 demo key 无提现权限，但这一步要自己核实而不是假设。
3. 新 key 写进 `~/Library/Application Support/starquant/env.sh`（`chmod 600`），
   重启循环（窗口与步骤见 `docs/RUNBOOK.md`「重启实盘循环」）。
4. **然后**才考虑清理 git 历史。清理不能替代作废：任何人都可能已经克隆过。
   工具是 `git filter-repo`，会重写全部 commit hash，所有 worktree 与 clone 都要重建。
5. 把经过记进 `docs/RESEARCH_LOG.md`，只写可观测事实。

### 报告漏洞

仓库开了 GitHub 的私有漏洞报告通道（Security → Report a vulnerability）。
请走那里，**不要开公开 issue**。

---

## 五、已经公开的东西

诚实的清单比"我们很安全"有用。2026-09-19 全历史扫描（1,637 个 commit、72 MB）的结论：

**凭据：零泄漏。** Binance key/secret 形态、AWS、GitHub token、Slack、OpenAI、私钥、
Telegram、Google、GitLab——所有形态零命中。两套独立扫描（手写 + gitleaks）结论一致。

**以下是公开的，是权衡后接受的，不是疏漏：**

| 内容 | 范围 | 为什么不清理 |
|---|---|---|
| demo 账户的权益与持仓 | `docs/RESEARCH_LOG.md` 多处 | **demo/testnet 账户，不是真实资金**。这些数字是研究账本的主体，删掉等于毁掉记录本身 |
| 运维细节（launchd label、代理端口、重启命令） | `docs/RUNBOOK.md` 等 | 是攻击面情报，但不含凭据。本机 SSH 未对外开放，这些路径在没有本机访问权时无从利用 |

**策略逻辑、参数与治理规则也是公开的。** 这是仓库公开的直接后果，不是可以靠配置解决的
问题。[`LICENSE`](LICENSE) 把权利说清楚了：**公开可见不等于授予许可**——它是专有软件，
公开只是为了作者本人查阅与协作。法律效果上，有没有这份文件都是保留全部版权；写出来是
为了减少「没写许可证就是开源」这个误会。第三方的 MIT 组件在 LICENSE 里单列，不受它约束。

---

## 六、提交前的自查

```bash
git diff --cached --name-only    # 这次到底要提交哪些文件
git diff --cached                # 逐行看，尤其是新增的配置与测试
```

第一条不是形式：本仓库有过一次新测试文件静默没进提交，CI 全绿，因为它跑的是当时在那儿
的测试。`.gitignore` 已经覆盖 `.env*`、`.starquant/`、`reports/daily/`、`reports/weekly/`、
`*.log`，但 `.gitignore` 只挡它认识的名字。
