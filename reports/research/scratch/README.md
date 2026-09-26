# reports/research/scratch/

这里的报告**不记账、不被 registry 引用、不是证据**。入库只有一个目的：让分析文档里引用过的数字有一份仓库内可复现的来源（深度分析报告附录 C.5 第 19 条对 scratchpad 输出的要求）。

不要把这里的文件当作 `reports/research/` 顶层报告的同类：它们跑在 scratch 账本上（`ledger_trials` 为 0），`n_trials` 只含申报先验与本次网格；registry 的证据门不会也不应指向这里。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `tsmom-validation-20260906T030942Z.{json,md}` | 深度分析报告 E-36（2026-09-06 03:09Z，六角色复核期间） | `research validate --strategy tsmom --universe pit --prior-trials 30`，16 点默认网格，当前构造（0.30 / 0.40 / pit / crowding 72 / D-034 后）。诚实走前 OOS 1.4852，折 [1.19, 0.06, 2.30, 1.25, 2.57]，零假设年化 SD 0.4428。**它的 16 个格子已经记过账**：093705Z 的 `--prior-trials` 30 → 60 里就含这 +16（registry 证据块的注释写明了分解）。不欠。 |
