# 10-13 的准备

2026-09-25。一份分析，不是裁定，也不是预登记。行号以 `5fe1e6b3` 为准。

本文不改代码，不花 ledger。跑过的命令都在附录。跑前跑后，`reports/research/trials.jsonl` 的
sha256 都是 `09245c34…99d`（附录 A8）。实盘文件只读副本，副本放在会话的 scratchpad 里。

每条读数标来源。凡是由读数推出来、没有直接读到或测到的句子，标「推理」。

## 结论

- 2026-10-13T00:00:00Z，也就是北京时间 10-13 08:00，三个开关同时翻转：D-041 bridge、
  测试侧的 exemption、构造冻结。
- 正在跑的进程不受影响。受影响的是 10-13 之后的**下一次启动**。
- **下一次启动会先死在 bash 上，轮不到证据门。** launchd 用 `/bin/bash` 3.2.57 执行
  `deploy/run_live.sh`。到期后 `BRIDGE` 是空数组，`set -u` 下展开它报 `unbound variable`，
  退出码 1。这是在逐字复制的脚本片段上实测的。不修这一行，证据修好了也起不来。
- 修好 bash 之后，挡在证据门：`tsmom: evidence verdict FAIL does not allow live use`。
- 止盈止损从不在交易所挂单。循环起不来，持仓就没有退出检查。最早的呼叫来自每小时巡检，
  在最后一次心跳之后约两小时（推理）。
- 同一时刻，CI 有 9 条测试变红。其中 1 条不论证据修没修都会红。
- 动 k 就要在新 k 上重出证据。所以 k 的重裁与 D-041 是同一个决定。
- 要先定的事、最晚日期与默认结果在第 6 节。

**后续（同日）**：

- **F1 已做。** #137 把 `run_live.sh:60` 改成 `${BRIDGE[@]+"${BRIDGE[@]}"}`，合入 `1c47623b`。
  同一个 PR 加了 `tests/cli/test_the_bridge_expiry_survives_the_bash_launchd_runs.py`：文本检查在 CI 的
  bash 5 上也能抓住没加保护的展开；行为检查按 `BRIDGE_UNTIL` 的 −30、−1、0、+1 天跑脚本自己的那一段。
  把第 60 行改回旧写法时，本机 bash 3.2.57 上文本检查与 0、+1 天两条变红。
- **F1 还差一步才生效。** launchd 读的是主 checkout 里的脚本。写这一段时，主 checkout 停在
  `451c7783`（#134），不含 #137。要赶在 10-13T00:00Z 之前快进。这一步由操作者定。
- **F2 没动。** 10-13 起那 9 条测试怎么处理，跟着第 2 节选哪个选项走。
- **「顺带发现」第 2 条实测属实，已修。** 在主 checkout 上单跑那条测试，读到 `XPASS(strict)`，
  记为 FAILED。#143 删掉了那个 xfail 标记，断言一字未改。它只量数据集门，09-19 换指针之后就不挡了。
- **1.5 节的 9 条复现属实，但它是下界。** 用附录 A5 的同一个插件重跑，同样 9 条红，名单相同。那个插件
  只改了 `tests.shipped_evidence._today`，只跑三个文件。仓库里另有测试直接读当前日期，其中一条带着
  更早的到期日。
- **CI 在 10-03 就会先红一条，比 10-13 早 10 天。** `tests/governance/test_the_single_window_mine_opening_is_returned.py`
  在 `SINGLE_WINDOW_MINE_OPENING_ENDS`（`2026-10-03T00:00:00+00:00`）之后断言
  `max_mine_rounds_per_window` 已退回 `STANDING_MINE_ROUNDS`。今天前者是 5，后者是 4
  （`starquant_governance/policy.py:106`–`:107`、`:139`）。这是有意设的绊线：到点要么退回 4 并升
  `POLICY_VERSION`，要么宣布 5 常设并挪 `STANDING_MINE_ROUNDS`。两者都是治理裁定，本文不替操作者定。
  它补进第 6 节的裁定表，记为 #14，最晚 10-02。
- 本文其余部分保持写成时的样子，行号仍以 `5fe1e6b3` 为准。

## 1. 10-13 那一刻会发生什么

### 1.1 三个开关，同一个时刻

| 开关 | 判据 | 翻转 | 出处 | 来源 |
| --- | --- | --- | --- | --- |
| D-041 bridge | `[[ "$(date -u +%Y-%m-%d)" < "$BRIDGE_UNTIL" ]]` | UTC 10-12 是最后一个生效日；10-13T00:00Z 起的启动不带 `--allow-unvalidated` | `deploy/run_live.sh:47`、`:49`–`:54` | 读到；复制品实测四个日期，见 1.3 |
| exemption | `_today() >= EXEMPT_UNTIL`，取 UTC 日期 | 同一时刻 | `tests/shipped_evidence.py:43`、`:49`–`:50`、`:61` | 读到；模拟日期实测，见 1.5 |
| 构造冻结 | 到点后测试直接返回 | 同一时刻 | `tests/live/test_the_construction_is_frozen_until_the_holdout_matures.py:59`、`:79`–`:80` | 读到 |
| reopen 两条 | `date_after` | 同一时刻 | `governance/reopen.yaml:364`–`:366`、`:431`–`:433` | 读到 |

`[[ ]]` 里的 `<` 是字符串比较。ISO 日期等宽，字符串顺序就是日期顺序。`date -u` 取 UTC，
与本机时区无关。

10-13 **不**翻转的钟，列在这里免得混：

- M-010 的 30 天窗口满在 10-17T16:07Z（冻结测试 `:44`–`:45`）。
- K-EX14 管到 10-17T16:07Z（`governance/reopen.yaml:338`）。
- tsmom 与 flow 的 probe 块都是 09-03 接受、`review_after_days: 30`
  （`config/alpha_registry.yaml:373`、`:378`、`:495`、`:508`）。复审日在 10-02 到 10-03：
  `governance/window_changes.yaml:42` 写 10-02。
- `governance/window_changes.yaml` 两条写 `earliest_window: 2026-10-03`（`:19`、`:47`）。
  两条都是构造变更，实际要等 10-13，见「顺带发现」。

### 1.2 正在跑的进程：不受影响（读到）

- bridge 只决定启动器传哪面旗（`deploy/run_live.sh:49`–`:54`、`:60`）。
- 证据门只在 `live run` 启动时跑一次（`starquant_cli/live_cmd.py:301`–`:314`）。
- `starquant_live/engine.py` 里搜 `evidence_problems`、`dataset_problems`、`allow_unvalidated`、
  `bridge`，零命中。
- 所以重启 #56 起的进程，10-13 之后照常交易，直到它退出。`state.json` 的 `restarted_at`
  是 2026-09-23T16:41:39Z。

### 1.3 下一次启动：先死在 bash，再轮到证据门

#### 第一道：bash（实测于复制品）

读到三件事：

- launchd 用 `/bin/bash` 执行脚本（`deploy/com.starquant.live.plist:15`–`:18`）。
  `~/Library/LaunchAgents` 里装的那份与仓库逐字相同，`diff` 为空。
- 本机 `/bin/bash --version` 是 `3.2.57(1)-release`。
- 脚本开 `set -euo pipefail`（`:7`）。到期分支不往 `BRIDGE=()` 里放东西（`:48`、`:52`–`:53`）。
  最后一行展开 `"${BRIDGE[@]}"`（`:60`）。

复制品取脚本第 7 行与第 47–60 行，逐字，`diff` 核过。`date` 换成返回指定日期的桩，
`starquant` 换成打印参数的桩。`run_live.sh` 本身没有运行。步骤见附录 A1。

| 模拟日期 | stderr | 结果 |
| --- | --- | --- |
| 2026-09-25 | `bridge ACTIVE until 2026-10-13` | exit 0，参数带 `--allow-unvalidated` |
| 2026-10-12 | 同上 | exit 0，同上 |
| 2026-10-13 | `bridge EXPIRED on 2026-10-13`，接着 `line 17: BRIDGE[@]: unbound variable` | exit 1，桩没被调用 |
| 2026-10-14 | 同上 | exit 1 |

复制品的第 17 行就是脚本的第 60 行。

这个分支从没以真实形态跑过：

- `live.stderr.log` 里有 3 行 `bridge ACTIVE`，对应重启 #54、#55、#56；`bridge EXPIRED` 0 行。
- PR #76 的表列的是四个日期各追加哪面旗。推理：当时若在 `/bin/bash` 下执行过到期分支的
  `exec` 行，就会看到这个报错。重启 #54 只走了 ACTIVE。
- 没有测试执行 `run_live.sh`。提到它的测试只读文本，例如
  `tests/cli/test_arming_and_instance_lock.py:97`。`tests/` 里搜 `EXPIRED` 零命中。

推理：CI 跑在 Linux 上，bash 4.4 起 `set -u` 不再拦空数组。补一条执行脚本的测试，
CI 上也看不见这个缺陷。本机没有 4.4 以上的 bash，这一条没实测。

推理：退出码 1。plist 写 `KeepAlive.SuccessfulExit=false`、`ThrottleInterval 60`（`:24`–`:30`）。
所以 launchd 大约每 60 秒拉一次，每次失败，每次往 `live.stderr.log` 写两行。

修法，本文不做：把 `"${BRIDGE[@]}"` 换成 `${BRIDGE[@]+"${BRIDGE[@]}"}`。这个写法在本机
`/bin/bash` 3.2.57 上试过两种状态。空数组时不展开，一项时展开成那一面旗。

改完要落到**主 checkout 的工作树**上才算数。launchd 读的是
`~/starquant/deploy/run_live.sh`，合入 origin 不等于生效。

#### 第二道：证据门（读到，今天的读数在副本上算过）

- `live_cmd.py:307` 是 `if problems or dataset.blocking:`。不带 `--allow-unvalidated`、
  又不是 dry-run 或 paper，`:310`–`:314` 就抛 `ClickException`。
- 报错原文：「enabled strategies lack validation evidence, or cite data that has since changed;
  run `starquant research validate` or pass --allow-unvalidated」。
- `--allow-unvalidated` 绕开的就是这一个 `raise`。证据与数据集两半进同一个 `if`，一起绕开。
  `evidence:` 与 `dataset:` 行照样打印（`:305`–`:309`）。
- 它不绕：`--armed` 的要求（`:280`–`:283`），`--state-dir` 与 `--registry` 的拒绝
  （`:293`–`:296`），账户锁（`:396`–`:407`），guards、kill switch 与风险预算。

今天的读数。代码取 worktree，数据取 scratchpad 里的 `membership.parquet` 与 `universe.json`
副本，见附录 A4：

- `registry_evidence_problems` 返回 `['tsmom: evidence verdict FAIL does not allow live use']`。
  这句出自 `starquant_alpha/registry.py:416`–`:417`。
- `registry_dataset_problems` 的 blocking 为空。日报 2026-09-24「Dataset provenance (D-041)」
  一节也写 `blocking none`。

所以修好 bash 之后，挡住启动的理由是 tsmom 的 FAIL（`config/alpha_registry.yaml:348`–`:351`）。

推理：`ClickException` 以 1 退出，launchd 照样每 60 秒拉一次。

读到：拒绝发生在建 `alerts` 之前（`:307`–`:314` 在 `:328`–`:337` 之前），循环自己不发 alert。
bash 那一道更早，Python 都没起来，更不会发。

还可能多一条理由：

- 成员表末行是 09-17（副本读数）。G10 的告警线是 14 天（`starquant_data/pool.py:226`），
  10-01 起每天推送。
- `membership` 是阻断字段（`starquant_data/manifest.py:32`）。10-13 前单独重建它，数据集门也会挡
  （`docs/RUNBOOK.md:89`–`:97`）。

手动的 `live run --armed` 从来不带 bridge，今天就起不来（`config/alpha_registry.yaml:333`–`:336`）。

#### 哪些启动会撞上（推理，按代码与 plist 列）

- 崩溃后 launchd 的拉起（`KeepAlive`）。
- 开机或重新登录（`RunAtLoad`，plist `:22`–`:23`）。
- 有意的 `launchctl kickstart`，例如上线一个改动。
- 连续失败熔断以 0 退出，launchd 不拉。恢复是一次重启（`docs/RUNBOOK.md:204`；`live_cmd.py:416` 印的是
  「run `starquant live run` to resume」），也撞上。

### 1.4 被挡住之后：持仓留在交易所，没有退出检查

读到：

- 全仓只有一处构造下单请求（`starquant_live/execution.py:43`）。它不改 `order_type`，
  默认值是 `"MARKET"`（`starquant_shared/types.py:118`）。
- `place_order` 只发 `type`、`quantity` 与 `reduceOnly`，没有 `stopPrice`
  （`starquant_exchange/binance_usdm/venue.py:182`–`:193`）。
- 全仓搜 `STOP_MARKET`、`stopPrice`、`closePosition`、`TAKE_PROFIT`：只命中 exit 规则的
  标签（`starquant_alpha/overlays/exits.py:34`–`:35`，`starquant_live/reports.py` 引用它们），
  与 guard 读 `closePosition` 的一行（`starquant_exchange/guard.py:48`）。
- exit overlay 在循环里改目标权重（`starquant_live/exits.py:15`–`:40`），bar 收盘时判定。

推理：

- 循环不在，就没有 6σ 止损与 6σ 止盈（`config/live.demo.yaml:393`、`:395`）。
- 也没有 `daily_loss_pause`（`:467`）、R8 的风险预算阶梯与 probe stop。
- 剩下的只有交易所自己的强平。账户是 demo（`config/live.demo.yaml:3`）。

交易所上留着什么（读到，截至 09-24）：

- 日报 2026-09-24 的 JSON，17:10Z 那次巡检写出：权益 13,142.3 U，可动用 USDT 7,395.6 U，
  抵押品占 43.73%。
- 现行构造从 09-17T16:00Z 起，共 169 根 bar。净敞口（目标权重之和，总权益口径）均值 0.975，
  最大 1.129。169 根的目标权重全部 ≥ 0。算法见附录 A6。
- 同一份日报的 G4 一节：回测 k=0.60 的一日 VaR99 与 ES99 是权益的 7.83% 与 9.25%，
  即 1,028 U 与 1,216 U。

最早谁会发现（推理，按代码读）：

- 每小时巡检在第 10 分钟跑（`deploy/com.starquant.check.plist:22`–`:26`）。
- `live status --check` 的心跳阈值是两个周期，即 7,200 秒（`live_cmd.py:515`、`:568`–`:569`）。
- 所以最后一次心跳之后约两小时，才有第一条呼叫。中间两根 bar 没有退出检查。

### 1.5 同一时刻，CI 变红（实测，模拟日期）

scratchpad 里写了一个 pytest 插件，只把 `tests.shipped_evidence._today` 固定成 2026-10-13。
跑三个测试文件，9 条失败，见附录 A5：

- `tests/alpha/test_evidence_gate.py`：`test_the_shipped_registry_runs_what_its_evidence_validated`、
  `test_the_shipped_registry_passes_the_new_check`。
- `tests/governance/test_the_registry_write_can_take_itself_back.py`：6 条演练。
  它们都经 `_shipped` 断言 `unexempted(problems) == []`。
- `tests/test_the_exemption_is_still_about_something_real.py::test_the_exemption_hides_one_string_and_not_a_shape`。

前 8 条红，是因为 registry 引着 FAIL 证据。最后一条是 `unexempted` 的单元测试，
只在 exemption 生效时成立（`:55`–`:59`）。**证据修好了，它照样红。**

推理：`verify` 是 required status check（docs/RUNBOOK.md「PR 流程」一节）。10-13T00:00Z 起，
auto-merge 不会触发，只能由操作者手动合并。

一个陷阱。docs/RUNBOOK.md 写「CI 红了——去修」。把 `EXEMPT_UNTIL` 往后挪就能变绿。但
`test_the_exemption_expires_with_the_bridge_it_belongs_to`（`:42`–`:52`）要求它等于
`BRIDGE_UNTIL`。挪一个就得挪另一个，那是延长 bridge，是治理裁定，不是修 bug。

### 1.6 近期重启频率（读到，只读副本）

`state.json`：`restarts` 56，`started_at` 2026-09-03T07:58:44Z，`restarted_at`
2026-09-23T16:41:39Z。到读副本的时刻 2026-09-24T17:59Z，共 21.42 天，平均 2.61 次/天。

最近五次。时刻取 `cycles.jsonl` 里理由为 `restart outside the rebalance window` 的 SKIPPED 行，
与 RESEARCH_LOG 的重启节一一对上：

| 编号 | 时刻（UTC） | RESEARCH_LOG 的节 |
| --- | --- | --- |
| #52 | 09-17 15:12 | 「重启 #52：把 ④ 的三个观测量放到循环上」 |
| #53 | 09-17 16:07 | 「重启 #53：D3 上线」 |
| #54 | 09-18 16:09 | 「D-041 桥上线，并用一次主动重启验证它真的起得来」 |
| #55 | 09-19 17:49 | 「重启 #55：把 typesafe-sdk 装进实盘 venv 后的一次主动重启」 |
| #56 | 09-23 16:41 | 「重启 #56：G6 的 bar sanity 进实盘」 |

- 五次都是会话有意做的，各节写明了。近 7 天 3 次。
- bridge 上线以来 6.08 天，`live.stderr.log` 只有 3 行 `bridge ACTIVE`，没有崩溃后的拉起。
- `cycles.jsonl` 共 9 个 ERROR 周期，09-18 之后 3 个，都在循环里处理掉，没有引起拉起。
- 推理：循环自己跑过 10-13 的可能性不小。最可能的触发是一次有意的重启，比如上线一个改动。

## 2. D-041 到期的应对选项

### 2.1 不管选哪个，都要做的两件

| 项 | 做什么 | 价钱 | 最晚 |
| --- | --- | --- | --- |
| F1 | `run_live.sh:60` 改成 `${BRIDGE[@]+"${BRIDGE[@]}"}`；主 checkout 快进到含这一行的提交；按附录 A1 在复制品上重跑四个日期 | 1 行代码，0 ledger。不需要重启，下一次启动读新脚本 | 10-12 合入并快进 |
| F2 | 按所选选项处理 `tests/shipped_evidence.py`：证据清门就删掉 exemption 与三处调用；延长 bridge 就一起挪日期 | 测试侧，量级 S | 10-12 |

F1 有一个已知阻力。09-18 那次，会话的自动模式分类器把「改 `run_live.sh`」判成 Safety Bypass
Flag 拒绝了（RESEARCH_LOG「重出的结果是 FAIL，两条指针都挡住启动」第六小节）。F1 不加任何绕过，
只让到期分支按设计执行。仍可能要操作者手动提交。

### 2.2 选项一览

「N」指 tsmom 桶在那次运行时的试验数。公式是去重后的 ledger 行数，加这次的网格格数，
加手工申报的 `--prior-trials`（`starquant_alpha/validation/ledger.py:360`）。今天去重后是 167 行，
申报的是 152 笔（`reports/research/tsmom-validation-20260918T154025Z.json` 的
`multiple_testing.prior_trials`）。功效数全部由 `research power` 跑出，见附录 A2，都是上界。

| 选项 | 做什么 | ledger | 10-13 后能否 armed 启动 | 谁裁 | 最晚裁 |
| --- | --- | --- | --- | --- | --- |
| A | 什么都不做（默认） | 0 | 不能 | — | — |
| B1 | k 不变，按 09-18 协议重出（2 格） | +2 | 看结果；过门概率 21–48% | 操作者，且要破 09-18 预登记 §6 | 10-08 |
| B2 | k 不变，按 09-19 协议重出（16 格） | +16 | 同一协议 09-19 读 1.2306，预期 FAIL | 操作者 | 不建议 |
| C | 延长 bridge | 0 | 能，继续在 FAIL 证据上交易 | 操作者（治理） | 10-11 |
| D | G2：`governance advance --commit` | 0 | 不能：registry 不变 | 操作者 | 无期限 |
| E | 停 tsmom，只留 flow | 0 | 能；副本上启动门为空 | 操作者 | 10-12 |
| F | 有计划地平仓 | 0 | 不需要启动 | 操作者 | 10-12 |
| G | 改 k，在新 k 上重出（与第 3 节同一个决定） | +2 或 +16，另有申报 | 看结果 | 操作者 | 10-08 |

#### A：什么都不做

- 进程跑到下一次启动为止。下一次启动死在 bash，之后每 60 秒重试一次（1.3）。
- 持仓没有退出检查，约两小时后才有呼叫（1.4）。
- CI 从 10-13T00:00Z 起 9 条红（1.5）。
- 代价是一个无界的风险敞口，时长取决于谁先发现。

#### B1：k 不变，按 09-18 的 2 格协议重出

- 协议照抄「预登记：tsmom 证据重出」一节：`--grid '{"crowding_window": [0, 72]}'`、
  `--prior-trials 152`、`--charge 2`。
- N = 167 + 2 + 152 = 321，门 1.5799。
- 功效：真 Sharpe 1.2306 时 21.3%，1.5 时 42.8%，1.5628 时 48.4%。1.2306 是 09-19 的 16 格读数，
  1.5628 是 09-18 的 2 格读数。
- 冲突：09-18 预登记 §6 写死「若 verdict 为 FAIL，不重跑、不换网格、不申诉门」。
  只有操作者裁定「G10 的成员表重建算新信息」时才站得住（`docs/RUNBOOK.md:89`–`:97`
  本来就要求重建与重出排在一起）。
- 两臂全折同选，样本外是全样本尾巴。D-043 封顶 WEAK_PASS，WEAK_PASS 仍可上线。
- registry 会从 09-19 的诚实指针退回一份「没做过选择」的证据。09-19 换指针就是为了记账记准
  （`config/alpha_registry.yaml:338`–`:340`）。
- 买到：约二到五成的机会，在 k=0.60 下不延长 bridge 就能重启。

#### B2：k 不变，按 09-19 的 16 格协议重出

- 带上 152 笔申报：N = 167 + 16 + 152 = 335，门 1.5945。不带（09-19 那次的做法）：N = 167 + 16 = 183，门 1.5238。
- 功效，真 Sharpe 1.2306：20.5%（N=335）、25.3%（N=183）。真 1.5292：44.1%、50.5%。
- 09-19 这个协议读出 1.2306。registry 自己的注释写：差的不是 0.01，是 0.28（`:342`–`:344`）。
- 买到的东西几乎没有。不建议。

#### C：延长 bridge

- 改 `BRIDGE_UNTIL`（`deploy/run_live.sh:47`）与 `EXEMPT_UNTIL`（`tests/shipped_evidence.py:43`），
  两处由测试钉成相等。再加 F1。代码量 S，0 ledger。
- 本文给的新到期日：2026-10-20T00:00Z。理由：G 要在冻结结束后才能合入新 k，留一周做
  重出、合入、快进与一次按纪律的重启。
- 风险：armed 循环继续在不清门的证据上交易。tsmom 的诚实读数是 1.2306，门 1.5238（N=183）；
  带上 152 笔申报是 1.5945（N=335）。
- 另一个代价：证据不清门期间，`governance apply` 一律回滚（`tests/shipped_evidence.py` 模块说明）。
- 新日期仍是字符串比较，F1 仍然要做；不做，bash 的缺陷只是推迟到新日期。
- 最晚 10-11 裁：PR 要在 10-13T00:00Z 前合入，CI 还是绿的。

#### D：G2 那条路（读代码回答）

- `governance advance` 只写 `governance/governance_state.json`，从不碰 registry
  （`starquant_cli/governance_cmd.py:895`–`:897`、`:981`–`:985`）。
- 实盘代码不读这个文件：`starquant_live/`、`starquant_alpha/` 与 `starquant_cli/live_cmd.py`
  搜 `governance_state`，零命中。
- 在副本上干跑（不带 `--commit`，附录 A3）：它会在 2026-09-19T18:30:06Z 那一刻折进
  `family_gate_failed -> probe`，把 tsmom 从 main 降为 probe。
- 降完之后 registry 一字不变，tsmom 仍在主书、仍引 FAIL 证据。启动门的结果不变，照样拒绝。
- 副作用：tsmom 与 flow 占满 `max_concurrent_probes` 的两个名额（`starquant_governance/policy.py:159`），
  别的候选进不了 probe（RESEARCH_LOG「操作者两条裁定：family gate 失败降回 probe」）。
- 买到：治理记录追上 09-19 的那次 refuse。它不回答 D-041。

顺带核了一条变体：把 registry 改写成「tsmom 作为 probe 书」。`_probe_problems` 要一份书级报告，
sleeve 是 tsmom，判定为 ACCEPT 或 REJECT（`starquant_alpha/registry.py:414`–`:415`、`:473`–`:477`）。
`research book` 要一个主书策略（`starquant_cli/research_book_cmd.py:69`–`:70`），而别的族都已
REFUTED。推理：这条走不通。

#### E：停 tsmom，只留 flow

- 在 scratchpad 的 registry 副本上把 tsmom 设成 `enabled: false`，实测（附录 A4）：
  证据问题为空，数据集 blocking 为空，可以建模。
- 构造指纹从 `0c555e1c837e` 变成 `523472306577`。这是构造变更，10-13T00:00Z 之前合入会被冻结测试挡住。
- 推理：重启后主书没有策略，循环按自己的再平衡把 tsmom 的仓位降到 0。flow 照常跑，退出检查照常做。
- 要 F1、F2 与一次按纪律的重启。0 ledger。
- 代价：tsmom 的实盘记录停止，而实盘期就是它的 holdout。M-010、M-G06 与 `realised_vol` 清零。
- 书只剩 flow：日报 2026-09-24「Probe books (D-019)」读 `pnl_30d` 0.01 U，stop 在 −2%。
- 拿不准：flow 的证据是「tsmom 主书加 flow sleeve」那本书（`book-tsmom-flow-20260908T105322Z`）。
  只剩 flow 时门放行，但证据描述的不是在跑的书（推理）。

#### F：到期前有计划地平仓

- `live flatten --yes` 先挂 kill switch，再用 reduce-only 市价单平掉全部仓位（`live_cmd.py:693`–`:700`）。
- 它不调证据门（`live_cmd.py:683`–`:729` 里没有 `registry_evidence_problems`）。推理：10-13 之后也能跑。
- 成本（推理）：名义额约 0.975 × 13,142 U。按 taker 5 bps（`config/costs.yaml:2`）加日报实测主书
  滑点 5.1 bps，约 13 U。
- 代价：kill switch 持久，循环停止交易。tsmom 与 flow 的实盘记录都停。
  恢复要 `kill-switch --release` 加一次重启，那时仍要过证据门。
- 买到：不论启动器出什么事，交易所上都没有裸奔的仓位。
- 只能由操作者执行。

#### G：改 k，在新 k 上重出

- `vol_target` 在 `CONSTRUCTION_KEYS` 里（`starquant_alpha/registry.py:195`）。改了它，
  `construction_problems` 报「portfolio vol_target is X live but Y in the cited evidence」
  （`:249`–`:255`），启动门拒绝。所以改 k 必须同时换证据。
- 推理：重出可以在 10-13 前在 worktree 里跑。profile 只在那个 worktree 里改，报告与 ledger 行可以
  先合入，不动 shipped 构造。改 k 与换指针的 PR 在 10-13T00:00Z 之后合入。
- 2 格：N 321，门 1.5799。16 格带申报：N 335，门 1.5945。
- p32g 与 p32h 看过 8 个 k、两个 universe。按 P32 的先例（RESEARCH_LOG「ledger 申报：`--prior-trials`
  95 → 152」）可能要申报约 16 笔，2 格的 N 变成 337，门 1.5855。
- 功效：若新 k 下真 Sharpe 是 1.8087，2 格过门 69.9%（N=321）或 69.4%（N=337），16 格 68.6%（N=335）。
  1.8087 是 09-13 数据上 k=0.30 的 2 格读数（`config/alpha_registry.yaml:287`）。
- 推理：降 k 很可能抬高 2 格的样本外。同一份数据上 k 从 0.30 升到 0.60，样本外从 1.8087
  降到 1.5919，封顶 bar 从 390 变成 4,070（`:287`–`:292`）。重建后的成员表上没在 k<0.60 下量过。
- 选择污染要先声明：k=0.30 下的 1.8087 已经看过（P31 的先例）。
- D-043：2 格仍封顶 WEAK_PASS。构造清零 M-010、M-G06 与 `realised_vol`。
- 重出 FAIL 时，退到 C、E 或 F，要在 10-13T00:00Z 前选好。

#### 一条可走的顺序（本文的倾向，不是裁定）

1. 现在做 F1。
2. 10-08 前裁 k（第 3 节），并决定是否走 G。
3. 在 RESEARCH_LOG 写预登记，然后在 worktree 里按新 k 重出。
4. 过门（PASS 或 WEAK_PASS）：改 k、换指针、删 exemption 放进同一个 PR，10-13T00:00Z 之后合入，
   主 checkout 快进，在安全窗口重启一次。
5. 不过门：10-12 前在 C、E、F 里选一个。

## 3. k 的重裁

### 3.1 #112 与 #116 说了什么

- #112（合入于 `e80b1335`）新增 `scratchpad/p32h_k_sweep_at_the_base_in_force.py`。
  缺陷是 p32g 把梯的 base 写死成 0.60，而实盘传的是在跑的 k。k<0.60 时刹车重了 0.60/k 倍。
- #116（合入于 `500f3214`）按操作者裁定落更正：RESEARCH_LOG 加更正节与 5 处指回标记，
  `governance/reopen.yaml` 的 `drawdown-budget-denominator` 在 `note` 里加补注，`condition` 不动。
- 结论三条，出自 RESEARCH_LOG「k 扫描的更正：梯按实盘的 base 重跑」§4：
  - 守住 −70% 可动用预算的 k，从 0.30–0.35 变成约 0.25–0.27。插值 pit 0.271、static 0.255。
  - 代价从约 45pp 变成 pit 约 61pp、static 约 66pp，约丢一半预期收益。
  - 梯在预算线上只多赚 +5.6pp（pit）与 +3.5pp（static）。
- 补上 D3 后重放，守住线的 k 是 pit 0.2730、static 0.2557，答案不变
  （「多书研究路径的再平衡带少一条规则」§三）。
- 误差方向三条都指向更差的尾部：周块 bootstrap 抹掉多月 regime；换算假设亏损全落在 USDT；
  CAGR 的绝对水平是 bootstrap 的产物，只有差值有意义（「k 扫描」§4）。

### 3.2 选项与价钱

每格是 q95(USDT) / P(USDT>70%) / CAGR 中位。2000 draws，同一组 block 起点（配对）。
K-1 到 K-3 假设档位同时换成可动用口径，即 p32g 的 −28% / −40% 总权益触发线。
K-0 是现行配置，即 p32h 的 `running` 臂。

| 选项 | pit | static | 相对 K-0 的 CAGR（pit / static） | 守得住 −70% | 前置 |
| --- | --- | --- | --- | --- | --- |
| K-0 维持 0.60 与现行档位 | −118.9% / — / 123.2% | −115.8% / — / 121.5% | 0 | 否 | 无 |
| K-0' 0.60，档位换成可动用口径 | −102.7% / 89.5% / 111.8% | −100.1% / 87.3% / 110.4% | −11.4 / −11.1pp | 否 | 改 `Policy.drawdown_ladder` |
| K-1 0.30（`rollback_to`） | −74.3% / 8.8% / 76.6% | −76.2% / 13.9% / 67.7% | −46.6 / −53.8pp | 否 | 新 k 上重出证据，并改档位 |
| K-2 0.25 | −67.0% / 3.0% / 62.3% | −69.3% / 4.3% / 55.6% | −60.9 / −65.9pp | 是，static 只余 0.66pp | 同上 |
| K-3 0.20 | −57.7% / 0.4% / 48.8% | −59.5% / 0.7% / 46.3% | −74.4 / −75.2pp | 是 | 同上 |
| K-4 k 不动，把 BTC 抵押品换成 USDT | 推理：约 −67.7% / 3.1% / 同 K-0 | 推理：约 −66.3% / 2.5% / 同 K-0 | 约 0 | 推理：是 | 操作者在交易所的动作 |

出处：K-0 到 K-3 取自 RESEARCH_LOG「k 扫描的更正」§3 的两张表与 `running` 行；「—」表示那一行没印。
差值由附录 A9 的一行脚本算出。补 D3 后 K-2 读 −66.2% / 2.9% / 61.5% 与 −69.2% / 4.4% / 55.9%，
K-1 读 −74.5% / 9.3% / 74.9% 与 −76.2% / 13.0% / 68.9%（「多书研究路径的再平衡带少一条规则」§三）。

K-4 的来历与限定：

- `governance/reopen.yaml` 的 `risk-g11-denominator` 把它写成两条路之一：「把 BTC 抵押品换成 USDT，
  不动构造、不清零任何时钟，但那是操作者在交易所的动作」（`:350`–`:355`）。
- 推理：换完之后可动用等于总权益，可动用口径的 q95 就是总权益口径的 q95。表里的数借自
  p32f 的总权益列（RESEARCH_LOG「回撤按可动用 USDT 重新定价」§2），那是另一组 draws，
  不与 p32h 配对。
- 它改的是分母，不是书。书的大小与绝对盈亏不变，BTC 抵押品的价格风险没了。
- 它回答预算，不回答 D-041：k=0.60 下 tsmom 的证据仍是 FAIL。
- 本文不评价这笔交易本身。它是操作者的决定。

### 3.3 前置条件与耦合

- K-1 到 K-3 都是构造变更，都要在新 k 上重出证据，见 2.2 的 G。
- K-1 到 K-3 都会清零 M-010、M-G06 与 `realised_vol`。`governance/window_changes.yaml:34`–`:35`
  说这笔钱应当与同一窗口的其他构造变更一起付。那两条（probe stop 口径、`vol_target` 重推）
  正好也在等这个窗口。
- 表里 K-0' 到 K-3 的档位都是可动用口径的，要改 `Policy.drawdown_ladder`，走 R10 的规则事务。
  档位不在构造指纹里：`starquant_live/engine.py:2058` 起的 `construction_fingerprint` 搜 `ladder`，零命中。
  所以只做 K-0' 不清零上面三个钟（推理）。
- 换算因子在漂。09-20 是 1.861 倍，09-22 是 1.769 倍。日报 2026-09-24 的
  `risk_budget.usdt_drawdown.vs_total_equity` 读 1.748。p32h 钉在 09-22 的值上。
  裁定前要按当天的因子重测（`governance/reopen.yaml` 的 `measured` 末段）。
- 10-13 的清单补一条：`config/alpha_registry.yaml:212`–`:222` 那段仍引 k=0.30 的崩盘窗口
  （FTX −3.3%）。k 裁完之后一起更新（优化方案「10-13 的清单补一条」）。

## 4. G11 预登记草稿：净敞口上限

**这是草稿，不是预登记。** 正式的预登记要等操作者在冻结结束后批准，再写进 RESEARCH_LOG。
一个要知道的机械事实：`preregistration_problems` 按策略名在 RESEARCH_LOG 的历史里找首次提及
（`starquant_cli/live_cmd.py:926`–`:946`）。G11 跑的策略名是 `tsmom`，首次提及早就有了，
这条检查对 G11 会空转放行。登记与运行的先后，只能靠报告里的 `--prereg <commit>` 证明。

### 基线：G3 进日报以来的读数

两份日报的 `beta` 段（`reports/daily/` 下的 JSON，副本读取）：

| 读数 | 2026-09-23 | 2026-09-24（17:10Z 写出） |
| --- | --- | --- |
| 窗口 | 09-07T14:00Z → 09-23T22:00Z | 09-07T14:00Z → 09-24T16:00Z |
| 回归样本 | 378 根 bar | 396 根 bar |
| 策略 / PIT 基准收益 | +35.56% / +13.66% | +41.15% / +17.82% |
| 净敞口均值 / 峰值（可动用 USDT 口径） | 1.504x / 2.145x | 1.519x / 2.145x |
| constant beta（t） | 1.052（7.58） | 1.068（8.18） |
| constant alpha 的 t | 1.31 | 1.29 |
| conditional beta（t） | 0.685（29.38） | 0.684（32.30） |
| conditional 残差部分 | +5.46% | +4.86% |
| conditional alpha 的 t | 0.50 | 0.45 |
| 信号全多头的 bar 占比 | 48.6% | 50.9% |
| 最后一根 bar 的空头数 | 0 | 0 |

从 `cycles.jsonl` 副本另算的总权益口径净敞口（附录 A6）：

| 窗口 | bar | 均值 | 中位 | p90 | 最大 | 权重全 ≥ 0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 09-07T14Z 起 | 411 | 0.770 | 0.914 | 1.065 | 1.129 | 41.8% |
| 09-14T15Z 起（k=0.60） | 242 | 0.967 | 0.978 | 1.097 | 1.129 | 71.1% |
| 09-17T16Z 起（现行构造） | 169 | 0.975 | 1.013 | 1.107 | 1.129 | 100.0% |

读法：

- 书的收益几乎就是「市场 × 敞口」。conditional 的残差小、alpha 的 t 不到 1，与 F4 的测量同形
  （RESEARCH_LOG「F4 的结构命题第一次有了测量」）。
- 现行构造下，书每一根都是全多头。那样的 bar 上，净敞口上限与降 k 是一回事。
- 上限与 k 的差别，只在书持有空头时出现。这就是 G11 要测的全部内容。
- `max_gross` 2.0 在实盘上一次没绑定过：日报 `risk_budget.guards` 读 90 天内 capped 0 根。

### 8. 本次服务四个目标里的哪一个

服务：G-B（同收益下更小回撤）。不服务 G-A。

### 1. 假设

在两个 universe 上，都沿 k 插值到 q95(USDT) = −70% 这条预算线。「k 高一点加净敞口上限」的
CAGR 中位，比「k 低一点、无上限」高出至少 2pp。

为什么可能成立：上限只在书单边时咬，降 k 在每一根 bar 上都付钱。

若不成立会看到：预算线上两者之差小于 2pp，或者为负。那说明上限只是一个更贵的降 k。

### 2. 这是「新信息」还是「新网格」

新信息。仓库没有测过净敞口上限：清点的反向搜索 `max_net`、`net_cap`、`beta_cap`、`max_beta`
等零命中（`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md:407`）。

选择污染，先声明：

- 已经看过 17 天的实盘 beta 与净敞口（上面两张表）。
- 已经看过 p32h 的 k 扫描。
- 上限值 c 不按实盘均值去挑。本草稿预先写死 c ∈ {1.0, 0.75}，总权益口径。
  1.0 是「不加杠杆的单边」；0.75 与 R8 第一档同比（`deescalate_to` 是 k 的 75%）。两个都不看收益。

单位取总权益，与 `max_gross` 同一口径。理由：有一条测试断言 `clamp_book` 的签名里没有地方
传抵押品份额（RESEARCH_LOG「F4 的结构命题第一次有了测量」末段）。可动用口径的上限要等
RISK-G11 的裁定。

### 3. 协议

阶段 1，零 ledger 行，但按先例申报格子：

- 代码：`PortfolioParams` 加 `max_net`；`clamp_book` 加第三个参数（`starquant_alpha/overlays/exposure.py:103`）；
  `CONSTRUCTION_KEYS` 加一项（`starquant_alpha/registry.py:194`）。回测与实盘走同一份实现（D-036）。
- 重放用 p32h 的机器：2000 draws，SEED 20260904，BLOCK 168，mtm ruler。换算因子取重放当天的日报读数，
  不用 0.5652。static 按 p32h 的做法钉名单。
- 臂：c ∈ {无上限, 1.0, 0.75} × k ∈ {0.25, 0.30, 0.35, 0.40} × {pit, static}。
- 比法：沿 k 插值到 q95(USDT) = −70%，读插值点的 CAGR 中位。插值用 p32h 的 `crossing`。

重放之前先做一件事：把 `cycles.jsonl` 副本按 `plan_rebalance` 重放一遍。要数两个数：
上限在实盘路径上绑定多少根，被再平衡带挡掉多少笔。理由见第 9 项的第 1 种失效。

阶段 2，花 ledger：阶段 1 判过，才在采纳的 (k, c) 上重出 tsmom 证据，协议同 2.2 的 G。

### 4. 计费与桶

- 桶是 `tsmom`（`ledger_scope`，`starquant_alpha/validation/ledger.py:237`–`:253`）。
- 阶段 1：构造参数不进 `param_key`，按 D-039 与 P32 的先例手工申报。取 P32 那种两个 universe
  都计的保守算法：2 个 c × 4 个 k × 2 个 universe = 16 笔。只计 pit 是 D-039 的算法，8 笔。
- 今天的 N：2 格口径是 167 + 2 + 152 = 321。加阶段 1 的 16 笔，是 337。
- 阶段 2 花 2 笔（2 格）或 16 笔（16 格）。

### 5. 功效读数

阶段 2 的门，`research power` 实测（附录 A2）：

| N | 门 | 真 Sharpe 1.2306 | 1.5 | 1.5628 | 1.8087 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 321 | 1.5799 | 21.3% | 42.8% | 48.4% | 69.9% |
| 337 | 1.5855 | 20.9% | 42.3% | 47.9% | 69.4% |

方差借自 `tsmom-validation-20260918T154025Z.json`，se 0.4390。这是上界，不含 CPCV 负路径、PBO、
fold 一致性与成本 ×2。

阶段 1 没有现成的标准误。p32h 在预算线上分出的梯效应是 +3.5 到 +5.6pp，那是点估计。
本草稿把容差定在 2pp。这是草稿值，由操作者定。

### 6. 判定规则（数字出来之后一个字不改）

| 判据 | 要求 | 容差 |
| --- | --- | --- |
| 阶段 1，两个 universe 都要 | 插值点 CAGR 中位（上限臂）减同一预算线上的无上限臂 ≥ 2.0pp | 恰好 2.0pp 算过；插值用 `crossing` |
| 阶段 1 | 采纳的 (k, c) 的 q95(USDT) ≥ −70.0% | 离线 0.5pp 以内读作「在线上」，不采纳 |
| 阶段 2 | 重出证据的 `verdict` ∈ {PASS, WEAK_PASS} | 直接读报告，不手算 |
| 阶段 2 | `construction_problems` 为空 | 由启动门判 |

判负之后：不重跑，不加 c 值，不换 k 网格。`governance/reopen.yaml` 加一条，重开条件写「新信息」。

### 7. 预期

最可能挂的是阶段 1 的第一条。理由：现行构造下 169 根全多头。推理：尾部路径上书多半也是单边，
在最要紧的那些 bar 上，上限就等于降 k。

两种结果的价钱：

- 过：预算线上多留至少 2pp 年化。代价是 16 笔申报加 2 笔重出，外加一次构造清零，可以与改 k 同一次付。
- 不过：用 16 笔申报买到一句话——「k 就是那根杠杆」。G11 关掉。

### 9. 实盘失效方式（How this fails）

| 失效方式 | 最早的症状（现有仪器） | 盯的读数与阈值 | 亏钱前怎么抓 |
| --- | --- | --- | --- |
| 1. 上限在实盘上执行不到。回测是先带后截：带在 `build_weights` 里（D-033，`docs/ARCHITECTURE.md:78`），`clamp_book` 在 `run_backtest(guards=)` 里（`starquant_alpha/backtest.py:242`–`:243`）。实盘是先截后带：`starquant_live/guards.py:78` 先截，`starquant_live/engine.py:927` 的 `plan_rebalance` 再过带。削减小于现仓 40% 的同向缩仓会被 `no_trade_rel_band` 跳过（`config/live.demo.yaml:236`）。推理，没有重放过。 | 日报「Plan gaps (no-trade band)」一节出现上限引起的跳过；「Margin and rejections (M-007)」的 gross 对可动用 USDT 不降。**「Market beta (D-045, reported only)」看不见它**：它的净敞口读的是目标权重（`starquant_live/benchmark.py:258`–`:260`），上限生效后按定义 ≤ c。 | 持仓净敞口（总权益口径）> c + 0.02 的 bar 数。阈值：上线后任何一根。 | 上线前按第 3 项重放 `cycles.jsonl` 副本；日报先加一行持仓净敞口（`gross_before` 的净额版）。没有这一行，就没有仪器看得见这条失效。 |
| 2. 口径错位。上限按总权益写，操作者按可动用 USDT 读。09-24 抵押品占 43.73%，总权益口径的 1.0 在可动用口径上约是 1.75（推理）。BTC 一动，倍数就漂：09-20 到 09-24 已从 1.861 漂到 1.748。 | 「Market beta (D-045)」的净敞口峰值，它按可动用 USDT 印；「Risk budget (P13)」可动用口径那一行的「总权益口径的 X 倍」。 | 可动用口径的净敞口峰值 > c × 采纳当日的倍数 × 1.05。 | 预登记写死单位；采纳当日把倍数写进注释；日报两种口径并印，越线告警，照 M-007 的先例（PR #78）。 |
| 3. 尺子没跟着换。G4 的 VaR / ES 常数取自「回测 k=0.60、无上限」（`starquant_live/reports.py:1136`–`:1137`）。M-002 的波动带 [0.52, 0.76] 按 k=0.60 誊写（`config/live.demo.yaml:435`）。上限常咬时，实现波动会系统性偏低。 | 「Risk budget (P13)」的 realised vol 一旦 enforced 就落在带下沿之下，M-002 误报；「Tail beside the sigma ruler (G4)」的越线天数长期为 0，尾部仪器变瞎。 | realised vol < 0.52；越线天数对期望的比。 | 采纳的同一个提交里重推这两组常数，并更新钉住它们的测试。不重推，就不采纳。 |

## 5. G12 预登记草稿：size 与低波的横截面信号

同样是草稿，不写进 RESEARCH_LOG。

### 5.1 `research power` 的读数

跑之前先读了代码。`starquant_cli/research_power_cmd.py` 只读一份 JSON（`:36`–`:40`），算正态分位数，
再打印（`:98`–`:124`）。模块说明写明不写 `trials.jsonl`（`:13`–`:14`）。
`tests/cli/test_the_gate_prints_what_it_would_detect.py:89` 那条测试钉住「落盘为零」。
跑前跑后 sha256 相同（附录 A8）。

方差借自最近的横截面族报告 `reports/research/xsmom-validation-20260917T092142Z.json`
（sha256 `5cc40533…e0ca`），se 0.4398。空桶里，N 就是网格格数。

| 桶的 N | 门 | 挡路的一半 | 0.5 | 0.8 | 1.0 | 1.2 | 1.5 | 2.0 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.0000 | PASS 线 | 12.8% | 32.5% | 50.0% | 67.5% | 87.2% | 98.9% |
| 2 | 1.0000 | PASS 线 | 12.8% | 32.5% | 50.0% | 67.5% | 87.2% | 98.9% |
| 4 | 1.0000 | PASS 线 | 12.8% | 32.5% | 50.0% | 67.5% | 87.2% | 98.9% |
| 8 | 1.0949 | 选择门 | 8.8% | 25.1% | 41.5% | 59.4% | 82.1% | 98.0% |
| 16 | 1.1990 | 选择门 | 5.6% | 18.2% | 32.5% | 50.1% | 75.3% | 96.6% |
| 32 | 1.2963 | 选择门 | 3.5% | 13.0% | 25.0% | 41.3% | 67.8% | 94.5% |

列头是真年化 Sharpe。对照：用 F4 盘点借的那份方差（`tsmom-validation-20260918T154025Z`）
跑 N=16，得门 1.1969，真 1.0 时 32.7%，真 1.5 时 75.5%，与 F4 盘点那张表逐格相同。

读法：

- N ≤ 4 时挡路的是 PASS 线，门与单点一样。4 格是门上不多付钱的最大网格。
- 4 格也正好让 PBO 跑起来。不到 4 格时 PBO 被豁免，D-043 会封顶 WEAK_PASS。
- 从 4 格到 8 格，真 Sharpe 1.0 的功效从 50.0% 掉到 41.5%。

### 5.2 正面回应 F4 盘点

F4 盘点的结论：「没有第四条是『再找一个候选』」。空桶里用 16 格去测一本真 Sharpe 1.0 的书，
过门只有 32.7%。失败之后留下的记录，与今天一模一样。

G12 就是「再找一个候选」。上表不推翻那个结论。它能改的只有两件：

- 网格从 16 缩到 4，同一个真 Sharpe 1.0 的功效从 32.5% 升到 50.0%，仍是上界。
- 清单 6.1 那一行（size 与低波没当横截面信号测过）有了答案，PASS 或 FAIL 都算。

它改不了的：FAIL 仍然分不清「没有」与「没找到」。

本文的判断：只做低波一族，排在 10-13 之后，4 格。size 一族在拿到时点市值数据之前不做。理由三条：

1. 仓库没有市值数据。`starquant_*` 与 `config/` 搜 `market_cap`、`circulating`、`coingecko`，零命中。
   能用的代理只有 30 日成交额与 OI 名义额（`starquant_data/metrics.py:41`）。而 universe 本身就按
   30 日成交额选（`config/universe.yaml:6`–`:7`）。在这个池子里按成交额排序，量的是「谁快被踢出去」，
   不是规模溢价。
2. 低波是真的新假设。`reports/research/mine*.json` 里出现过 914 个不同表达式，没有一个对波动水平本身做横截面排序
   （附录 A7）。`volratio` 是时序的，`oi(w)` 是 OI 的对数变化（`starquant_alpha/mining/expr.py:441`–`:445`）。
3. probe 名额可能是满的。G2 一旦执行，tsmom 与 flow 占满两个位子。G12 即使组合层 ACCEPT，也要等位子。

做的话：低波一族，一个新桶，4 格，4 笔。先过零 ledger 的 correlate 前置闸。

### 5.3 九项

低波一族写全。size 一族同形，差别写在第 2、7、9 项。

#### 8. 本次服务四个目标里的哪一个

服务：G-B（同收益下更小回撤：一本低相关的书，接 F4），其次 G-A。

#### 1. 假设

在 pit universe 的时点成员里，按过去 w 根 bar 的已实现波动排序。做多低波，做空高波（`xs_lowvol`）。
经逆波动率定价之后，样本外 Sharpe 过门，而且与 tsmom 的收益相关 < 0.5。

size 一族（`xs_size`）：按 30 日成交额排序，做多小、做空大。

若不成立会看到：FAIL，或者 correlate 前置闸先挡住。

#### 2. 这是「新信息」还是「新网格」

新信息。清点的反向搜索 `low vol factor`、`size factor`、`market cap` 等零命中
（`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md:415`）。挖掘空间里也没有（附录 A7）。

先声明一条看过的信息：flow 的 edge 来自后来离池的名字（`config/alpha_registry.yaml:457`–`:461`）。
这与「高波」「小」两端都重叠。

#### 3. 协议

- 新 id 用 `xs_lowvol` 与 `xs_size`，不要叫 `size`。`preregistration_problems` 用
  `git log -S<id>` 找 RESEARCH_LOG 里的首次提及（`starquant_cli/live_cmd.py:926`–`:946`）。
  `size` 这个子串已在 12 个提交里变过数目，检查会空转放行。`xs_lowvol` 与 `xs_size` 今天零命中。
- 参照总体：研究侧用 `eligible`，实盘侧用当周期管理的 universe（D-042 的 `Panel.reference`）。
- 网格 4 格，例如 `window {168, 720}` × `entry_threshold {0.2, 0.3}`。`--charge 4`、`--prior-trials 0`、
  `--universe pit`，fold、`min_train`、purge 等取默认，`--prereg <commit>`。
- 阶段 0，零 ledger：`research correlate` 对 tsmom。相关 ≥ 0.5 就停。这是晋级门的同一条线
  （`starquant_governance/lifecycle.py:185`），xsmom 走过同样的路（`governance/reopen.yaml:310`–`:317`）。
- 代码：信号模块、注册、因果测试（每个注册信号都要有，`tests/alpha/test_signal_suite.py`）、
  `starquant_alpha` 的 source budget 抬顶。量级 M。

#### 4. 计费与桶

- 各自一个新桶。手写策略的 `ledger_scope` 只返回自己（`starquant_alpha/validation/ledger.py:237`–`:253`）。
- 今天 N=0，跑完 N=4。两族都做是 8 笔。
- 不动 tsmom 的门。

#### 5. 功效读数

见 5.1 的 N=4 一行：真 Sharpe 0.8 时 32.5%，1.0 时 50.0%，1.5 时 87.2%。都是上界。

#### 6. 判定规则（数字出来之后一个字不改）

| 判据 | 要求 | 容差 |
| --- | --- | --- |
| 阶段 0 | 与 tsmom 的相关 < 0.50 | 恰好 0.50 算挡住 |
| 阶段 1 | `verdict` ∈ {PASS, WEAK_PASS} | 读 `verdict.decide` 的输出，不手算 |
| 阶段 1 | `oos_is_full_sample_tail` 为 False | 布尔值，无容差 |

判负之后：不重跑，不换网格，不换 id 重来。`governance/reopen.yaml` 加一条，重开条件写
「时点市值数据」或「新信息」。

#### 7. 预期

- 低波最可能挂在阶段 0。推理：逆波动率定价（D-038 的 stage 1，`vol_target / asset_vol`，`docs/ARCHITECTURE.md:83`）
  放大低波多头腿、缩小高波空头腿。排序信号到了书里变成净多头，与 tsmom 同向。
- size 最可能挂在阶段 1，理由见 5.2 第 1 条。定价后大币空头更重，它会是一本负 beta 的书（推理）。
- 过：第一个低相关候选，花 4 笔。
- 不过：清单一行关掉，花 4 笔。记录与 F4 盘点同形。

#### 9. 实盘失效方式（How this fails）

假设它以 probe 上线之后：

| 失效方式 | 最早的症状（现有仪器） | 盯的读数与阈值 | 亏钱前怎么抓 |
| --- | --- | --- | --- |
| 1. 低波一族变成第二本多头书。逆波动率定价后是净多头，与 tsmom 同向。 | 日报「Probe correlation (M-014)」里新 sleeve 与 tsmom 的相关；「Market beta (D-045)」的净敞口均值上升。 | M-014 ≥ 0.5（168 根 bar）；净敞口均值高于上线前（09-24 为可动用口径 1.519x）。 | 阶段 0 的 correlate；上线后第一个 168 根读 M-014，≥ 0.5 就按 D-019 停书，不等 P&L stop。 |
| 2. size 一族是负 beta 的对冲，涨市流血。 | 「Probe books (D-019)」里它的 `pnl_30d` 与 tsmom 反向；M-014 ≤ −0.5。 | M-014 ≤ −0.5 且 `pnl_30d` < 0。 | 组合层 D-018 的判据会先显示总书 ΔSharpe ≤ 0；实盘按上面的阈值复审，不等 −2σ 的 stop。 |
| 3. 研究与实盘不是同一个信号：参照总体不同（D-042），或选池同变量带来换手。 | 「Execution fidelity (M-Q08, four clauses)」的换手 实盘/回测；「Exits and pool (M-005 / M-006)」的 `pool_left` 与本 sleeve 的持仓重叠。 | 满 14 个完整日后，换手比落在 0.75–1.25 之外。 | 合入前跑参照总体的契约测试；上线前在 `cycles.jsonl` 副本上按实盘 universe 重算排序，对照研究侧。flow 的先例：0.126 的边际里约 0.048 是参照总体的假象（`config/alpha_registry.yaml:467`–`:480`）。 |

## 6. 给操作者的裁定表

| # | 要定的事 | 选项 | 最晚 | 什么都不定时的默认结果 |
| --- | --- | --- | --- | --- |
| 1 | `run_live.sh` 的空数组（F1） | 修，或不修 | 10-12 合入，并快进主 checkout | 10-13 后第一次启动死在 bash，每 60 秒重试；持仓无退出检查，约两小时后才有呼叫 |
| 2 | D-041 的去向 | B1、C、E、F、G（2.2） | 要重出的 B1、G 在 10-08；C 在 10-11；E、F 在 10-12 | 选项 A：进程跑到下一次启动为止 |
| 3 | k | K-0 到 K-4（3.2） | 走 G 就是 10-08；否则与 #2 同一天 | 维持 0.60；可动用口径 q95 约 −119%（pit） |
| 4 | exemption（F2） | 随 #2 | 10-12 | 10-13T00:00Z 起 9 条测试红，合并只能靠管理员 |
| 5 | 成员表重建（G10） | 与重出排在一起，或继续等 | 10-01 起每天推送 | 研究用前向填充的成员表，到 10-13 落后 26 天 |
| 6 | p32g、p32h 看过的 k 格子要不要申报 | 申报约 16 笔，或不申报 | 任何一次 tsmom 重出之前 | 门偏松约 0.006（1.5799 对 1.5855） |
| 7 | 09-19 那次 16 格少传 `--prior-trials 152` 的更正 | 另开 docs 提交，或不改 | 任何一次 16 格重出之前 | family gate 每天读 N=183、门 1.5238；带上 152 是 N=335、门 1.5945 |
| 8 | `governance advance --commit`（G2） | 跑，或不跑 | 无期限；G12 要 probe 位之前 | tsmom 在治理记录里仍是 main |
| 9 | window_changes 两条（probe stop 口径、`vol_target` 重推） | 与 k 同一次付，或另开窗口 | 与 #3 同一天 | 文件从 10-03 起报 DUE，而冻结到 10-13 |
| 10 | RISK-G11 与回撤预算分母（reopen 两条） | 与 #3 一起裁；K-4 同时回答这两条 | 10-13 到点 | 维持总权益口径 |
| 11 | flow 与 main 的 probe 复审 | 按 D-019 复审 | 10-02 到 10-03 | 日报标 REVIEW_DUE |
| 12 | G11、G12 的预登记 | 批，或不批 | 冻结结束后，无期限 | 不跑 |
| 13 | registry 里 k=0.30 的崩盘窗口注释 | 随 #3 更新 | #3 之后 | 注释继续引旧读数 |
| 14 | 挖掘窗口的第五轮（`max_mine_rounds_per_window` 5，10-03 到期）——本行由「后续」补入 | 退回 4 并升 `POLICY_VERSION`，或宣布 5 常设 | 10-02 | 10-03T00:00Z 起 `test_the_single_window_mine_opening_is_returned` 红，比 10-13 那 9 条早 10 天 |

#6 与 #7 的数出自 `research power`（附录 A2）与 `governance-gate.stdout.log` 的每日读数。

## 7. 10-13 这次过渡本身的 How this fails

| 失效方式 | 最早的症状（现有仪器） | 盯的读数与阈值 | 亏钱前怎么抓 |
| --- | --- | --- | --- |
| 1. 10-13 之后循环被拉起，起不来，持仓没有退出检查。 | `live.stderr.log` 出现 `BRIDGE[@]: unbound variable`，或「enabled strategies lack validation evidence」。循环自己不发 alert（1.3）。每小时巡检的 `live status --check` 报「心跳已过期」。日报「Restart cost (M-Q03 / DL-L4 / RISK-P2)」的 `missed_rebalances` 是滞后读数：循环回来之后才补记漏掉的 bar。 | 心跳年龄 > 7,200 秒。 | F1 在 10-12 前合入并快进主 checkout，复制品四个日期重跑。10-12 用 `ps -eo pid,lstart,command \| grep "live run"` 确认在跑的进程是 10-13 前起的。证据修好之前不做有意重启。一旦起不来，操作者执行 `live flatten --yes`，它不经过证据门。 |
| 2. CI 红被当成代码坏了去修，顺手延长了 bridge。 | 10-13T00:00Z 之后第一次 CI 的 `verify` 红，失败名单就是 1.5 节那 9 条。 | 任何改动 `EXEMPT_UNTIL` 或 `BRIDGE_UNTIL` 的 diff。 | 裁定表 #2、#4 在 10-12 前定好。耦合测试保证挪一个就要挪另一个，`run_live.sh` 一定出现在 diff 里。PR 描述引裁定出处。 |
| 3. 改了构造（k、probe stop、G11），证据没跟上，或者进程没换。 | 启动门报「portfolio vol_target is X live but Y in the cited evidence」；`live status --check` 报磁盘上的 registry 不是循环正在跑的那份；日报 M-Q08 一节的「registry digest 循环/磁盘」一行；「Evidence window (D-026 construction)」的构造摘要没变。 | 任何一处不一致。 | 合入前，CI 上的 `test_the_shipped_registry_runs_what_its_evidence_validated` 比对 registry 与 profile。重启前跑两个构造测试，在整点后 5 分到下一个整点前 10 分之间重启（docs/RUNBOOK.md「重启实盘循环」）。 |

## 顺带发现

1. **09-19 的 16 格少传了 `--prior-trials 152`。** 报告字段 `multiple_testing.prior_trials` 是 0，
   09-18 那份是 152。`ledger_trials` 是 151 对 149，几乎相同。N 的公式在
   `starquant_alpha/validation/ledger.py:360`：去重 ledger 行数加网格格数加申报。所以 167 对 303 的差，
   来自申报，不是 ledger scope。RESEARCH_LOG「结果:16 格重跑」§3 把它归给「换 grid 就换了
   ledger scope」，与报告字段不符。判定不变：1.2306 对门 1.5945（N=335）。更正是另一个 docs 提交，
   由操作者定（裁定表 #7）。
2. **主 checkout 上有一条测试多半在红。** `test_the_shipped_registry_is_not_blocked_on_the_machine_that_runs_the_loop`
   是 `xfail(strict=True)`（`tests/live/test_dataset_gate.py:108`–`:147`）。09-19 指针换到新报告之后，
   数据集门的 blocking 为空（1.3 的读数）。推理：它在主 checkout 上会 XPASS，strict 下记为失败。
   worktree 与 CI 没有 `.starquant/data`，跳过它。本文没在主 checkout 上跑。它的 reason 写的是
   「tsmom 重新合格那天」，而现在只解开了数据集那一半。
3. **window_changes 两条写 10-03，冻结到 10-13。** `governance window` 从 10-03 起会报 DUE
   （`tests/governance/test_the_batch_window_has_a_list.py:45`）。照 DUE 去改构造，会撞冻结测试。
4. **`docs/PREREGISTRATION.md:85` 的 G-A 护栏已过期。** 它还写「今天 +0.0181，剩 52 笔」，
   而 09-19 起 tsmom 的 family gate 是 FAIL。那份模板今天另有改动在加第九项，留给那边。
5. **`research power` 的显示会撞键。** 它把真 Sharpe 显示到一位小数，并用显示值当字典键
   （`starquant_cli/research_report.py:170`–`:171`）。1.5 与 1.5292 同时传，后一个会覆盖前一个。
   本文的表都用不撞键的值重跑过。

## 拿不准的地方

- bash 4.4 以上的行为没实测；「CI 看不见这个缺陷」是推理。
- 冻结期内能不能先在 worktree 里按新 k 跑 validate。冻结的裁定说构造不动，没说研究不能先跑。
  要操作者确认。
- p32g、p32h 的格子要不要申报、申报多少。P32 的先例两个 universe 都算，D-039 只算 pit。
- G11 第 1 种失效里的「回测先带后截、实盘先截后带」，是读代码顺序得出的，没重放。
- K-4 的尾部借自 p32f，那是另一组 draws。前提是换完之后可动用等于总权益。
- 选项 E 里，flow 的证据描述的不是只剩 flow 的那本书。
- 各选项的最晚日期，是按「重出、合入、快进、按纪律重启」倒推的。一次 validate 要多久，本文没量。

## 附录：命令与复现

`<S>` 指会话 scratchpad 里的 `oct13/` 目录，不在仓库里。`<WT>` 指本文所在的 worktree。
worktree 里验证 CLI 一律用 `PYTHONPATH=<WT> ~/starquant/.venv/bin/python -m starquant_cli`。

### A1. bridge 的复制品

```bash
mkdir -p <S>/bridge_replica/shim <S>/bridge_replica/repo/.venv/bin
printf '#!/bin/sh\necho "$FAKE_DATE"\n' > <S>/bridge_replica/shim/date
printf '#!/bin/sh\necho "STUB starquant argv: $*"\n' > <S>/bridge_replica/repo/.venv/bin/starquant
chmod +x <S>/bridge_replica/shim/date <S>/bridge_replica/repo/.venv/bin/starquant
{ echo '#!/bin/bash'; sed -n 7p deploy/run_live.sh; echo "REPO=<S>/bridge_replica/repo";
  sed -n 47,60p deploy/run_live.sh; } > <S>/bridge_replica/replica.sh
for d in 2026-09-25 2026-10-12 2026-10-13 2026-10-14; do
  FAKE_DATE=$d PATH="<S>/bridge_replica/shim:/usr/bin:/bin" /bin/bash <S>/bridge_replica/replica.sh; echo "exit=$?"
done
```

2026-10-13 那一次的原样输出：

```
run_live.sh: D-041 bridge EXPIRED on 2026-10-13 - the strict evidence gate is back
<S>/bridge_replica/replica.sh: line 17: BRIDGE[@]: unbound variable
exit=1
```

修法的验证：`/bin/bash -c 'set -euo pipefail; B=(); printf "[%s]\n" ${B[@]+"${B[@]}"}; B+=(--x); printf "[%s]\n" ${B[@]+"${B[@]}"}'`
依次打印 `[]` 与 `[--x]`，不报错。

### A2. `research power`

全部在 `<WT>` 里跑，零 ledger：

```bash
research power --evidence reports/research/tsmom-validation-20260918T154025Z.json --trials 16
research power --evidence reports/research/xsmom-validation-20260917T092142Z.json --trials N \
  --sharpe 0.5 --sharpe 0.8 --sharpe 1.0 --sharpe 1.2 --sharpe 1.5 --sharpe 2.0   # N = 1 2 4 8 16 32
research power --evidence reports/research/tsmom-validation-20260918T154025Z.json --trials 305 --charge 2
research power --evidence reports/research/tsmom-validation-20260918T154025Z.json --trials 319 --charge 2
research power --evidence reports/research/tsmom-validation-20260918T154025Z.json --trials 321 --charge 16 \
  --sharpe 1.2306 --sharpe 1.5 --sharpe 1.5628 --sharpe 1.8087
research power --evidence reports/research/tsmom-validation-20260919T081914Z.json --trials 183 --charge 16
research power --evidence reports/research/tsmom-validation-20260919T081914Z.json --trials 319 --charge 16
research power --evidence reports/research/tsmom-validation-20260919T081914Z.json --trials 183 \
  --sharpe 1.2306 --sharpe 1.5292 --sharpe 1.8087
research power --evidence reports/research/tsmom-validation-20260919T081914Z.json --trials 335 \
  --sharpe 1.2306 --sharpe 1.5292 --sharpe 1.8087
```

N=183 那次读出门 1.5238，与 `governance-gate.stdout.log` 每天的读数逐位相同，可以当作核对。

一次的原样输出（xsmom 方差，N=4）：

```
evidence: reports/research/xsmom-validation-20260917T092142Z.json sha256=5cc40533bd71dc6b36b306ffca0b7d26dafc85c685a69ac18e6c36036023e0ca
  interval=1h bars_per_year=8760 n_obs=45288 variance=2.20781e-05 (这份报告自己量的样本外方差)
  N 由 --trials 指定为 4，证据报告自己的是 9

## N=4
    standard error of the OOS Sharpe (annual): 0.4398
    gate (max of the two halves): 1.0000  [pass_line binds]
      D-028 selection threshold: 0.9825 at N=4, alpha=0.05
      D-020 pass line: 1.0000
    P(clear | true annual Sharpe = 0.5): 12.8%
    P(clear | true annual Sharpe = 0.8): 32.5%
    P(clear | true annual Sharpe = 1.0): 50.0%
    P(clear | true annual Sharpe = 1.2): 67.5%
    P(clear | true annual Sharpe = 1.5): 87.2%
    P(clear | true annual Sharpe = 2.0): 98.9%
```

### A3. `governance advance` 干跑

```bash
PYTHONPATH=<WT> .venv/bin/python -m starquant_cli governance advance --root <WT> --cycles <S>/live/cycles.jsonl
```

不带 `--commit`。原样输出：

```
window   window 0, 0/1 used
gate     FAIL       tsmom                OOS 1.2306 vs 1.5238 at N=183 (adopted against 1.5129 at N=167)
gate     UNREADABLE flow                 the report carries no `oos_selection` block
flow_short       -> flow             probe      folded through (never)
main             -> tsmom            main       folded through (never)
    2026-09-19T18:30:06.089745+00:00  family_gate_failed -> probe  R0: the quantile gate no longer passes on recomputation, back to probe
dry run: nothing written.  `--commit` writes <WT>/governance/governance_state.json
```

`governance_state.json` 与 `verdicts.jsonl` 前后 sha256 不变（A8）。

### A4. 启动门在副本上的读数

```python
from starquant_live.config import load_profile, build_model_from_profile, registry_evidence_problems, registry_dataset_problems
payload = load_profile("config/live.demo.yaml")          # 选项 E：payload["registry"] 换成 <S> 里改过的副本
model, registry = build_model_from_profile(payload)
registry_evidence_problems(registry, payload)            # ['tsmom: evidence verdict FAIL does not allow live use']
registry_dataset_problems(registry, "<S>/data", "1h").blocking   # []
```

`<S>/data` 只放了 `membership.parquet` 与 `universe.json` 的副本。阻断字段只有这两个
（`starquant_data/manifest.py:32`），所以 blocking 是准的；advisory 里 klines、funding 的行不作数。
选项 E 那次把副本里 tsmom 的 `enabled` 设成 false：证据问题 `[]`，blocking `[]`，
构造指纹 `0c555e1c837e` → `523472306577`（`canonical_construction(construction_fingerprint(...))`）。

### A5. 模拟 10-13 的 pytest 插件

```python
# <S>/plugin/fake_oct13_plugin.py
import datetime


def pytest_configure(config):
    import tests.shipped_evidence as se

    se._today = lambda: datetime.date(2026, 10, 13)
```

```bash
PYTHONPATH=<WT>:<S>/plugin .venv/bin/python -m pytest -p fake_oct13_plugin -p no:cacheprovider -q \
  tests/alpha/test_evidence_gate.py tests/governance/test_the_registry_write_can_take_itself_back.py \
  tests/test_the_exemption_is_still_about_something_real.py
```

结果：9 failed，名单见 1.5。

### A6. 净敞口分布

```python
import json
rows = [json.loads(l) for l in open("<S>/live/cycles.jsonl") if l.strip()]
keep = {int(r["bar_open_ms"]): r for r in rows if r.get("targets") and r.get("bar_open_ms") and not r.get("dry_run")}
# 每根 bar：net = sum(targets)（总权益口径）；net × equity / usdt_equity（可动用口径）；
# 「全 ≥ 0」= 该 bar 所有目标权重 ≥ 0。按 bar_open_ms ≥ 窗口起点筛。重启重写同一根 bar 时保留后一条。
```

### A7. 挖掘空间里有没有低波与 size

```python
import glob, json, re
exprs = set()
for p in glob.glob("reports/research/mine*.json"):
    exprs |= set(re.findall(r'"expression": "([^"]*)"', json.dumps(json.load(open(p)))))
# 914 个不同表达式。按叶子粗筛（只留 vol / semi / volratio / skew / kurt），剩 17 个：
# volratio 的 9 个时序 squash，与带 basis 的 8 个。没有对波动水平或成交额水平做横截面排序的表达式。
```

### A8. `trials.jsonl` 与治理文件的 sha256

跑命令前（2026-09-24T18:09:25Z）与跑完最后一条 `research power` 之后，逐字相同：

```
09245c344b922ddc2cf31258d7f85111bf3f6d46f7afd68e9f97f97ecd85599d  ~/starquant/reports/research/trials.jsonl
09245c344b922ddc2cf31258d7f85111bf3f6d46f7afd68e9f97f97ecd85599d  <WT>/reports/research/trials.jsonl
395828548f2b46d15f8deeddda3fc884908afe2ad16d41346fd5ec61964dbf65  <WT>/governance/governance_state.json
c9e4b8cf0d8e047f3e6f3f8bae7d1968e530ed6e74fcad932342b6c089d5d642  <WT>/governance/verdicts.jsonl
```

### A9. k 选项的差值

```python
base = {"pit": 123.2, "static": 121.5}   # p32h 的 running 臂
rows = {"0.30": (76.6, 67.7), "0.25": (62.3, 55.6), "0.20": (48.8, 46.3), "0.60 可动用档位": (111.8, 110.4)}
# 差值 = CAGR − base；例：0.25 → −60.9 / −65.9pp，丢 49.4% / 54.2%
```

### A10. tsmom 桶今天的去重行数

```python
from starquant_alpha.validation.ledger import parse_ledger, unique_trials, ledger_scope
from starquant_governance.policy import Policy
lines = open("reports/research/trials.jsonl", encoding="utf-8").read().splitlines()
recs = parse_ledger(lines, ledger_scope("tsmom"))
unique_trials(recs, range_end_granularity_days=Policy().trial_range_end_granularity_days)
# 210 行，去重后 167 条；粒度 7 天。新运行的键与已有的不重合时（数据末端晚 7 天以上，或构造变了），
# 它的 N = 167 + 网格格数 + 申报笔数（ledger.py:360）。
```
