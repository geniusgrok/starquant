# `reports/research/diagnostics/` — 诊断跑，不是晋级候选

治理回放（`starquant_governance/replay.py`，`tests/governance/test_replay_attributes_every_difference.py`）
用 `glob("*.json")` 扫 `reports/research/`，**不递归**。所以放在这一层的每一份报告都必须能被解释成
「被采纳」「被拒绝」或「被后续指针取代」——AC-G0 要求未归因项为 0，而那是检查在工作，不是误报。

一次**诊断跑**不属于上面三种里的任何一种：它重跑的是**已经被采纳的那套配置**，目的是补一个报告
字段或回答一个问题，既没有预登记、也不申请晋级。把它放在上一层会让它被当成一个无法解释的晋级
候选（2026-09-14 就发生过一次，见 `40531ba4`）。所以它放在这里。

**规则**：

- 这里的报告**不能**被 `config/alpha_registry.yaml` 的 `evidence` 引用。要引用它，就把它移回上一层
  并在 `ADOPTIONS` 里补一行——采纳是两半，移指针只是其中一半。
- 账本照charge：跑一套配置就是一次 trial，`reports/research/trials.jsonl` 的行数与它在不在这一层无关。
  （2026-09-14 实测：重跑同一套配置时 D-024 的 context 排除生效，磁盘上 +2 行而门的 N 不变。）
- 每一份都要在这里或在引用它的 `docs/analysis/` 文档里说清楚它回答的是哪个问题。

## 现有

- `tsmom-validation-20260913T201638Z.json` / `.md`（2026-09-14）——与被采纳的
  `tsmom-validation-20260913T182325Z` 同配置重跑，为了拿到新的 `cost_stress_gate` 字段：
  「成本翻倍之后这份证据还过不过 D-028 的门」。答案是**不过，而且 1.5 倍就已经不过**。
  除 `cost_stress_gate` / `dataset` / `generated_at` / `ledger` / `oos_selection_whole_library` /
  `preregistration` 外与被采纳的那份逐位相同。它**没有**预登记，这是它留在这里而不是取代指针的
  第二个理由。见 `docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md`。
