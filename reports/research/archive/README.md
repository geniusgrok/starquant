# `reports/research/archive/` — 跑过、没人读、也没有仪器扫到的产物

这一层放**纯输出**：既不被 `config/alpha_registry.yaml` 的 `evidence` 引用，不被 `docs/` 或测试按
文件名引用，也**不被任何按目录扫描的仪器读到**。它们仍然是记录，所以是移进来而不是删掉。

## 为什么是这三类，以及为什么不是别的

2026-09-16 的全仓审查先按「有没有人按文件名引用」挑出 40 份孤儿报告，把其中 39 份移了进来。
**那一版是错的**，`starquant governance next` 当场炸出来：`shortlist_candidates` 从 9 变 12、
「minus 3 already validated」变成「minus 0」——`assemble()` 判断一个候选「已经验过」靠的是扫
`reports/research/*.json`，而被移走的三份 `mined_*-validation-*.json` 正是那三个候选的验证证据。
再跑一次挖掘就会在已经做过的工作上重新花账本行。

教训写在这里而不是提交信息里，因为它决定了这个目录今后能收什么：

> **「没有人按名字引用它」不等于「没有人读它」。** 仓库里有五处按 glob 读报告目录的代码，
> 它们看的是**文件名模式**，不是引用关系。grep 看不见这条边。

审查当时清点的五处（`starquant_*` 全仓 `.glob(`）：

| 位置 | 扫什么 | 用途 |
| --- | --- | --- |
| `starquant_cli/governance_cmd.py:117` (`_payloads`) | `*.json` | `replay` 的归因表、`next` 的「已验过」判断 |
| `starquant_cli/governance_cmd.py:776` | `mine-shortlist-*.json` | 取最新一轮挖掘的候选名单 |
| `starquant_cli/research_cmd.py:1827` | `mine-shortlist-*.json` | 搜索空间是否被枚举过（R2 去重） |
| `starquant_cli/live_cmd.py:965` (`_validations_since`) | `*-validation-*.json` + `book-*.json` | `report weekly` 的预登记顺序检查 |
| `starquant_cli/governance_cmd.py:781` | `reports/daily/*.json` | M-011 读数（不在本目录范围内） |

**因此能进本目录的只有四种名字**，它们不匹配上面任何一条模式：

- `overlay-*`（10 组）
- `tsmom-backtest-*`（7 组）
- `correlate-*`（4 组）
- `decompose-*`（2 组）

共 23 组 46 个文件。`*-validation-*`、`book-*`、`mine-shortlist-*` **一律留在上一层**，哪怕
没有任何文档引用它们——留下的理由不是引用，是有仪器在扫。

## 移进来之前必须跑的四件事

四条命令的输出在移动前后必须**逐字节相同**（2026-09-16 实测四条全部相同）：

```bash
starquant governance replay    # AC-G0 未归因项必须仍为 0（当时 15 reproduced / 31 differences / 0）
starquant governance next      # shortlist_candidates 与 scheduler 决定不得变
starquant report weekly        # 预登记顺序检查的窗口内报告集不得变
starquant live run --profile config/live.demo.yaml --dry-run --cycles 0   # 启动证据门/数据集门读数不得变
```

## 其它两个子目录不是一回事

- `scratch/` —— 跑在 scratch 账本上（`ledger_trials` 为 0），**不是证据**。
- `diagnostics/` —— 重跑已采纳配置以补字段，不申请晋级；放在上一层会被当成无法解释的晋级候选。

本目录与它们的区别：这里的报告**曾经是**正常产物，只是没有任何读者；不是账本状态特殊，也不是
晋级身份特殊。要把某一份移回上一层，直接 `git mv` 回去即可，然后重跑上面四条确认没有变化。
