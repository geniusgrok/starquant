# StarQuant · ledger 分母与四目标排序 Checkpoint

> 深度分析 V3.8 · 等级 L。恢复时先处理 HOLD / BLOCKER / P0，不重复 COMPLETE Phase。

- **更新时间 / 段次**：2026-09-18 · **第 4 段**（操作者裁定「过」= 上线口径；K-LD02 关闭；§13 优化方案已执行 OPT-1/OPT-2）
- **等级 / Interaction（六灯）**：**L** / **Yellow**（🟢用户 🟢场景 🟡损失 🟢成功标准 🟢约束 🟢可得证据）
- **当前 Phase 与状态**：Phase 1 COMPLETE（上一轮对话，**未并入本文件**，自检表已改 N/A）· Phase 2–6 COMPLETE（已按 Kill 修订）· **Phase 7 COMPLETE**（独立子代理，22 条 Kill）· Phase 8–13 COMPLETE（已修订）。**审查者未复审修订版**
- **已冻结结论**：
  - **D-LD01** — 框定选 F2「目标排序问题」。**[按 K-LD02 修订]** F1「门槛校准」**不再是被放弃的**——它转 UNKNOWN，等操作者一句定义；F3 的语法内支由 REFUTED 降为 PARTIAL（K-LD11）
  - **D-LD02** — 推荐 O-LD1「四目标排序表」，零 ledger、零代码、完全可逆
  - **D-LD03** — 本轮不跑任何计费实验（16 格默认网格吃掉 31% 剩余 headroom，换 0.5 个百分点功效损失）
- **Gate 状态**：G0–G5 PASS · **G6 PASS**（两条 P0 全部关闭）· G7 PARTIAL。命中 **H2** → **PIVOT**（H1 / H3 / H7 已随 K-LD02 关闭而解除）
- **开放 Claims / Kills / Assumptions**：
  - `C-LD01` 由 UNKNOWN 改判 **PARTIAL**：门对 2/9 是唯一死因，对 6/9 不是
  - `C-LD04` 语法外支（离散门控）**UNKNOWN** — Owner 操作者，走 GAP-LD02
  - `C-LD07` 实盘 15.6 天判不了 alpha — 只能等 M-010 满 30 天（2026-10-13 起可判）
  - `A-LD02` 四个目标在未来数月不变（高影响 / 中风险）— 最小验证 = AC-LD01
  - **K-LD02 · P0 · CLOSED（2026-09-18 操作者裁定）** — 「过」= **上线口径**（含 WEAK_PASS）。重数结果：门归零后能过的已判负族是 **flow 与 residual 两个**，Falsifier（≥2）**满足**。由 `tests/alpha/test_which_families_the_selection_gate_alone_is_holding_back.py` 钉住（5 条，吃真实归档，做过变异验证）
  - K-LD01 · P0 · 已以改写关闭（§2.6 分母论证删除，换逐族 N 表）
  - P1 ×11、P2 ×9 — 全部已在正文以修订、降级或补产物关闭
- **证据缺口**：
  - `GAP-LD01`（不确定性 M × 决策影响 **H**）— 排序表交操作者确认 — Owner 操作者
  - `GAP-LD02`（**H** × M）— 离散门控的零 ledger 枚举，阈值 ≤500 个新表达式 — Owner 操作者
  - `GAP-LD03`（L × M）— 等 M-010 30 天 — Owner 时间
- **待决问题**：`AC-LD01` 排序表态 · `AC-LD02` pit 成员表重建（**人类确认点**，`--sync` 默认开、写共享 root） · `AC-LD03` GAP-LD02 枚举是否开工（**人类确认点**）
- **取证预算已用 / 剩余**：L 级 ≤12 次/段。第 1 段约 12 次；第 2 段约 11 次；第 3 段（核审查的两条 P0）4 次。**ledger 消耗：0 笔**，`trials.jsonl` 全程 22,179 行（审查者亲跑 8 次 `research power` 后 md5 逐位未变）
- **下一动作**：① **OPT-3（10-13 裁定包候选）**：residual 进第二个 probe 名额（`max_concurrent_probes=2`，当前 1 个 flow，有空位）——**冻结期内不可做**，加 sleeve 会清零 M-010；② §8.3 的排序表交操作者表态（AC-LD01）；③ AC-LD02 / AC-LD03 两个人类确认点等裁定
- **关联文件**：
  - 正文 / 冻结稿：`docs/analysis/2026-09-18-ledger-denominator-and-four-objectives-deep-analysis.md`
  - 同日另一条线索的分析（**不复用其结论**）：`docs/analysis/2026-09-18-system-optimization-and-factor-module-deep-analysis.md`
  - 校准记录：`docs/analysis/analysis-calibration.md`
  - Constitution：**不存在**（仓库无 `deep-analysis-constitution.md`）
