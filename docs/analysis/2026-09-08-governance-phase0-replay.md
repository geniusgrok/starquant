# 治理规则回放（Phase 0）

> 生成物，不要手改。重出：
> `starquant governance replay --since 2026-09-03 --out docs/analysis/2026-09-08-governance-phase0-replay.md`
> 每次 `POLICY_VERSION` 变更后重跑（§5 L2）。验收是 AC-G0：差异清单无未归因项。
> 本次数据：201 份 research 报告、registry 的 18 个历史指针、实盘 153 个周期（2026-09-03 → 09-08）。
> 构造改动已按 `starquant_live.health.CONSTRUCTION_ALIASES` 归一。

`policy_version=0.1.0` `policy_digest=5787506aecdf` 窗口 30 天；规则复现 10 项，差异 27 条，未归因 0 条。

## 一、规则复现的部分

- book-tsmom-flow-20260904T052732Z.json：规则同意采纳（book；凭 registry 的 D-029 书面承认）
- book-tsmom-flow-20260903T143621Z.json：规则同意采纳（book）
- book-tsmom-flow-20260906T094008Z.json：规则同意采纳（book；凭 registry 的 D-029 书面承认）
- tsmom-validation-20260908T105259Z.json：规则同意采纳（validate）
- book-tsmom-flow-20260908T105322Z.json：规则同意采纳（book；凭 registry 的 D-029 书面承认）
- no-decision 正确排除：ERROR 1、SKIPPED 4、重基 1；可判周期 149（KILL-AR-20）
- 探针 P&L stop 从未触发：R5 连败计数 0，晋级不冻结，与 `stopped_books` 一致
- 构造改动共 4 次（已按 CONSTRUCTION_ALIASES 归一），覆盖 149 个可判周期（≈6.2 天）——规则允许每 30 天一次
- probe->main 不可达：记录覆盖约 0.21 个窗口，规则要求 9 个
- R8 归因口径可算：27 行归因合计 -16.19 USDT（不读权益曲线）

## 二、被挂起的判据（artefact 不含该事实，本次回放不对它下结论）

| 判据 | 读什么 | 为什么读不到 | 修法 |
| --- | --- | --- | --- |
| DL-K3 预登记早于报告 | `Facts.prereg_before_report` | 早于 DL-G9 的报告不携带预登记指针；那时预登记只记在 RESEARCH_LOG 的散文和 git 提交里。**DL-G9 已交付**：`research validate --prereg <commit>` 把 commit 与它自己的提交时间写进报告，此后的报告按 artefact 判定，更早的仍挂起 | Phase 1 ✔ DL-G9：`--prereg` + 报告的 `preregistration` 块 |
| KILL-AR-07 证据构造 ≡ 实盘构造 | `Facts.evidence_construction_matches_live` | 早于 DL-G9 时两侧没有可比对的东西：`cycles.jsonl` 只存构造 digest 而 digest 不可反解，报告存 `portfolio`/`exits` 却算不出同一个数。**DL-G9 已交付**：两侧各落一个 `evidence_construction`（只覆盖 `construction_problems` 比对的那三块），字符串相等即可判定 | Phase 1 ✔ DL-G9：报告的 `evidence_construction` + 每周期落盘的同名字段 + 每进程一次的 `construction_full` |
| §3 滑点压力 5.5 档 | `Facts.slippage_stress_pass` | book 报告不含 `slippage_stress`（validation 报告含） | Phase 1：book 报告补 `slippage_stress` |
| §3 与在跑的书 corr < 0.5、换手 ≤ 3x | `Facts.max_correlation_with_running / turnover_ratio_to_main` | `research correlate` 的结果是独立报告，没有任何字段把它链回 book 报告 | Phase 1：book 报告内联相关系数与换手比 |
| M-011 面板平价义务 | `Facts.parity_met` | 平价义务随 DL-D4 才存在，本期没有任何一列数据受它约束 | Phase 3：DL-D4 落地后自然可读 |
| L4 Canary 浸泡 | `Facts.canary_healthy` | Canary 尚不存在 | Phase 2：DL-G5 |

## 三、例外清单（规则刻意不编码的裁定）

### D-019（2026-09-04）
- **裁定**：flow 空头腿以探针书上线：组合层 ACCEPT、信号级 FAIL（DSR p 0.81）、静态 universe 上为零，操作者仍让它跑——1/3 预算、30 天 P&L 自动止损、定期复审。它是为产出样本外证据的有界实验。
- **与规则的冲突**：§3 candidate->validated 要求 verdict PASS；flow 的信号级判定不是 PASS。
- **为什么不写成规则**：把「信号级 FAIL 也能上线」写成规则，等于取消 D-020 的判据。它是一次具名的、有预算上限和自动止损的例外，代价已由 R3 与 P&L stop 承接；§3 的 Grandfather 条款只记录它的既成状态。

### D-029（2026-09-06）
- **裁定**：探针书可以引用 verdict REJECT 的组合层报告，但 registry 必须写明 `probe.accepted_despite: REJECT`。
- **与规则的冲突**：§3 validated->booked 要求组合层六项通过；三份被采纳的 book 报告是 REJECT。
- **为什么不写成规则**：这条已经**部分成为规则**：`starquant_alpha/registry.py` 强制那句书面承认，启动闸拒绝没有它的 REJECT 指针。剩下的例外部分是「谁来写那句话」——今天是人，Phase 2 之后是事务，但承认的内容仍需一次具名裁定，不能由机器自己给自己出具。

### K-EX07（2026-09-07）
- **裁定**：窗口 ≤ 100 bar、不用于选择任何参数的描述性实盘重放不计入 `trials.jsonl`；条件是报告标 E5 并写明 n，且不得据此改配置。
- **与规则的冲突**：R1 按窗口计 ledger 行数，R2 按 search_space_version 决定是否允许 mine；两者都只会计费，没有「不计费」这一档。
- **为什么不写成规则**：不计费的判据是「有没有用于选择」，那是意图，不是可从 artefact 读出的事实。机器能读的是 bar 数和是否改了配置；意图必须由人一次性裁定并留痕。

### Q7（2026-09-08）
- **裁定**：P20 重跑追加的 514 行 ledger 按 K-EX07 先例回退——同一搜索空间的第二次枚举不再向家族收费。
- **与规则的冲突**：R2 会**拒绝**这次重跑；历史是先跑了、写了 514 行、再由裁定把行删掉。
- **为什么不写成规则**：R2 只能防住下一次；它没有、也不该有回溯删除 ledger 行的能力——ledger 只追加是 DSR 分母可信的前提。删行是一次带署名的例外，不是一条规则。

### P10-cellB（2026-09-04）
- **裁定**：`no_trade_rel_band` 0.25 → 0.40 采纳（OOS Sharpe +0.14、配对 t 4.18），并预登记一条实盘证伪线「换手应下降约 12%」。
- **与规则的冲突**：§8 的构造冻结：窗口之间不改 construction_fingerprint。这次改动发生在任何批次窗口之外。
- **为什么不写成规则**：构造改动的证据是配对回测，不是实盘窗口；把它塞进晋级流水线会让每次参数调整都消耗一个晋级名额并清零 M-010。方案把它单列为 Phase 4a「批次窗口 #1（构造）」，与晋级（4b）拆开——即：这条例外的处置是改流程，不是改规则。

### P11（2026-09-04）
- **裁定**：预登记网格里没有一格带止损的通过 D-017，按预登记应「不启用止损并交回操作者」；操作者改为加宽网格重跑（P11-b），6σ 在**未经修改的 D-017 规则**下双通过并上线。
- **与规则的冲突**：R2 会把加宽后的网格当作新的 search_space_version 允许重跑，但没有任何规则允许在预登记结论已经出来之后改网格——那正是选择性报告的形状。
- **为什么不写成规则**：「加宽网格」与「换个网格直到过关」在 artefact 上完全同形，区别只在于加宽的理由是否在看到结果之前就成立。P11-b 把理由写在跑之前，这是人能做而规则读不出的动作。机器侧的对应控制是 R1 的预算与 ledger 收费，不是禁止。

### P13（2026-09-04）
- **裁定**：`vol_target` 0.15 → 0.30；同时把探针 `max_loss` 0.01 → 0.02「按比例调整以保持预登记规则的原意」；并明确作废 P10 cell B 的实盘证伪线（换手反升 74.8%）。
- **与规则的冲突**：R10：阈值只在代码里、改动带版本与预登记；机器不得改自己的阈值。这次一次动了构造、动了一条预登记阈值、作废了一条证伪线。
- **为什么不写成规则**：按比例保持原意需要知道「原意」，机器只有数值。作废一条证伪线更是如此：它要求判断证伪线的前提是否还成立。两者都必须是人的一次具名裁定；R10 的作用是让机器不能悄悄做同样的事。

## 四、差异归因

| 对象 | 历史 | 规则说 | 类型 | 归因 | 修法 |
| --- | --- | --- | --- | --- | --- |
| tsmom-validation-20260903T133239Z.json | 2026-09-03 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| flow-validation-20260903T0927Z.json | 2026-09-03 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260903T0846Z.json | 2026-09-03 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| flow-validation-20260903T0627Z.json | 2026-09-03 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260903T0619Z.json | 2026-09-03 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260904T145321Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | `oos_selection.gate` 缺失：KILL-Q3 2026-09-06 才把门写进 artefact，此前存的阈值（1.10）出自 E[max]，比现行门低约 0.32 | — |
| tsmom-validation-20260904T131421Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | `oos_selection.gate` 缺失：KILL-Q3 2026-09-06 才把门写进 artefact，此前存的阈值（1.10）出自 E[max]，比现行门低约 0.32 | — |
| tsmom-validation-20260904T052215Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | `oos_selection.gate` 缺失：KILL-Q3 2026-09-06 才把门写进 artefact，此前存的阈值（1.10）出自 E[max]，比现行门低约 0.32 | — |
| tsmom-validation-20260904T041838Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260904T020459Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260903T181803Z.json | 2026-09-04 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | 报告无 `oos_selection` 块：D-028 的门 2026-09-04 才存在 | — |
| tsmom-validation-20260904T193707Z.json | 2026-09-05 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | `oos_selection.gate` 缺失：KILL-Q3 2026-09-06 才把门写进 artefact，此前存的阈值（1.10）出自 E[max]，比现行门低约 0.32 | — |
| tsmom-validation-20260906T093705Z.json | 2026-09-06 写进 registry | R0: OOS Sharpe below the quantile gate on the strategy bucket | rule_version | `oos_selection.gate` 缺失：KILL-Q3 2026-09-06 才把门写进 artefact，此前存的阈值（1.14）出自 E[max]，比现行门低约 0.32 | — |
| flow-validation-20260903T1258Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 链条不停在证据侧：`book-tsmom-flow-20260904T052732Z.json` 判 REJECT（robustness_delta），规则在 validated->booked 同样拒绝——历史与规则一致，只是停在下一步 | — |
| flow-validation-20260903T1321Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 链条不停在证据侧：`book-tsmom-flow-20260904T052732Z.json` 判 REJECT（robustness_delta），规则在 validated->booked 同样拒绝——历史与规则一致，只是停在下一步 | — |
| mined_594a12f9307a15d9-validation-20260906T175515Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 链条不停在证据侧：`book-tsmom-mined_594a12f9307a15d9-20260907T043802Z.json` 判 REJECT（oos_mdd_worsening），规则在 validated->booked 同样拒绝——历史与规则一致，只是停在下一步 | — |
| tsmom-validation-20260903T1258Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260903T133239Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| tsmom-validation-20260903T1321Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260903T133239Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| tsmom-validation-20260904T020211Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260904T020459Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| tsmom-validation-20260904T040252Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260904T041838Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| tsmom-validation-20260904T041441Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260904T041838Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| tsmom-validation-20260904T041517Z.json | 从未写进 registry | §3：证据侧无拒绝理由，机器会让它进入 validated | rule_version | 被同策略的后续指针取代：`tsmom-validation-20260904T041838Z.json` 更晚且被采纳——旧报告不是被拒绝，是被超越 | — |
| construction a53eecccef38 @ 2026-09-04T06:46:06+00:00 | 构造在实盘运行中改变 | §8 构造冻结：窗口之间不改 construction_fingerprint（窗口 = 30 天） | evidence_gap | 记录只存 12 字符 digest，不存构造输入，因此这次改动**改了什么**无法从 artefact 读出，也就无法归因到某一条具名裁定 | Phase 1：构造变化时落全量构造（今天只有启动心跳有，且每次启动被覆盖） |
| construction 0dcd044d0158 @ 2026-09-04T14:50:07+00:00 | 构造在实盘运行中改变 | §8 构造冻结：窗口之间不改 construction_fingerprint（窗口 = 30 天） | evidence_gap | 记录只存 12 字符 digest，不存构造输入，因此这次改动**改了什么**无法从 artefact 读出，也就无法归因到某一条具名裁定 | Phase 1：构造变化时落全量构造（今天只有启动心跳有，且每次启动被覆盖） |
| construction a53eecccef38 @ 2026-09-04T15:00:28+00:00 | 构造回到一个此前出现过的指纹（回滚） | §8 构造冻结：窗口之间不改 construction_fingerprint（窗口 = 30 天） | evidence_gap | 记录只存 12 字符 digest，不存构造输入，因此这次改动**改了什么**无法从 artefact 读出，也就无法归因到某一条具名裁定 | Phase 1：构造变化时落全量构造（今天只有启动心跳有，且每次启动被覆盖） |
| construction 0dcd044d0158 @ 2026-09-04T15:02:41+00:00 | 构造回到一个此前出现过的指纹（回滚） | §8 构造冻结：窗口之间不改 construction_fingerprint（窗口 = 30 天） | evidence_gap | 记录只存 12 字符 digest，不存构造输入，因此这次改动**改了什么**无法从 artefact 读出，也就无法归因到某一条具名裁定 | Phase 1：构造变化时落全量构造（今天只有启动心跳有，且每次启动被覆盖） |
| probe max_loss | 探针止损阈值在运行中取过 [0.01, 0.02] | R10：阈值只在代码里，改动带版本 + 测试 + 预登记；机器不得改自己的阈值 | exception | P13（2026-09-04）：`max_loss` 0.01 -> 0.02 是为保持 D-019 预登记规则的**原意**（书翻倍则同比例放宽），操作者当场记录。机器没有「原意」可读 | — |

**AC-G0：未归因项 0 条** — 通过
