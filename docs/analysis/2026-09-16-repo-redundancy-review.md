# 全仓冗余与错误文件审查（2026-09-16）

**受检对象**：`main @ 71863e9e`，工作树干净。
**四道门本地实测**（`.venv`，Python 3.12）：`ruff check` 全过；`ruff format --check` 366 个文件全过；
`mypy` 119 个源文件 0 错误；`pytest -m "not network"` **2,073 项全绿，117.8 s**（ratchet 上限 400 s）。
所以下面说的「错误」不是编译或测试意义上的：是说明与代码不符、配置的自述与内容不符、
脚本不可复现、引用指向仓库里不存在的东西。

**规模**：源码 35,050 行 / 7 包；`tests/` 44,526 行 / 254 个文件 / 1,834 个测试函数；
`reports/research/` 258 个文件 6.7 MB；`scratchpad/` 53 个；`docs/` 30 个（RESEARCH_LOG 10,969 行）。

**判「无用」的尺子**（每一条都量过，不是推的）：
- 源码模块：`tests/architecture/test_every_module_is_reachable_from_an_entry_point.py` 的可达性 + 我用 AST 数的符号引用（生产包 / tests / scripts+scratchpad 三个计数）。
- 报告：在 `config/`、`docs/`、`tests/`、`governance/`、`starquant_*`、`scripts/`、`scratchpad/` 里按文件名逐个 grep；再与 `trials.jsonl` 的 `run_id` 对账。
- 脚本：同上 grep，且读了每一份的 docstring。

本次**没有删除、移动或修改任何文件**；下面每一项都是操作者的决定。

> **后续（同日）**：操作者裁定「按照建议执行」，正文的建议已经执行，并且执行过程**推翻了正文的
> 三条判断**。正文以下全部保持原样，更正与实际做了什么见文末《执行后的更正》一节——先读那一节，
> 否则第三节的「80 个文件」和 E7 会把你带向一个实测会炸的方向。

---

## 总评

- 没有一个生产模块不可达（守卫测试 + 2 个具名豁免），四道门全绿。仓库不「坏」。
- **冗余集中在四处**：
  1. 明知不可用仍留在树里的 liquidation 数据层：源码 596 行 + 测试 641 行；
  2. 建成但没有任何面板或信号读取的三条数据源（macro / onchain / index）：源码 1,757 行 + 测试 2,092 行；
  3. `reports/research/` 顶层 **80 个无人引用的报告文件**（1.28 MB）；
  4. `scratchpad/` 53 个脚本里 **15 个无人引用**。
- **错误集中在说明层与一份配置**：README / ARCHITECTURE / RUNBOOK 与代码脱节；
  `config/alpha_registry.candidate.yaml` 的头注是假的，而且 launchd 正在用它跑 shadow soak；
  两处引用指向仓库里不存在的文件。
- 不在「文件」范围但顺带看到：`worktrees/` 下 4 个已合入、干净的 worktree 共 210 MB；70 个已合入 main 的本地分支。

---

## 一、错误的文件（内容与事实不符）

| # | 文件 | 错在哪 | 证据 |
|---|---|---|---|
| E1 | `config/alpha_registry.candidate.yaml` | 头注（第 3–4 行）声称「与 `alpha_registry.yaml` 只差这段注释块，其它逐字节相同」。实际：`universe` 仍钉着 **18 个币**（armed 已于 09-15 改为 `[]`），`evidence.report` 指向 `tsmom-validation-20260908T182204Z`（armed 是 `20260913T182325Z`）。文件自 09-12（`6e87e7ed`）起没再动过，armed registry 之后改了三次。**`com.starquant.shadow` 从 2026-09-15T04:24 起正在用它跑**（PID 802，`--cycles 168`，已 90 个周期，心跳 `universe_size: 18`）。正控制「一份应该通过的 registry 正在通过」的前提已不成立：它 soak 的不是 armed 的那本书。 | `diff` 去注释后 21 行不同；`.starquant/live-shadow-dry-run/heartbeat.json` |
| E2 | `README.md:6` | 「新系统只有五个包」，`pyproject.toml` 列了 7 个（多 `starquant_shared`、`starquant_governance`），架构图也只画了 5 个。 | `pyproject.toml:6-14` |
| E3 | `README.md:26-28` | 说 `vendor/backtest-guard/` 在仓库里且「是审查这个仓库时用的那把尺子」。该目录在 **`7a950806`（09-08，一个 research(P24) 提交）里被整个删掉**（1,941 行，提交信息一字未提），`git ls-files vendor` 现在是空的。 | `git show --stat 7a950806` |
| E4 | `.gitignore:39`、`pyproject.toml:67-70,82` | `!vendor/` 的再包含与 ruff 的 `vendor` 排除项，都指向 E3 那个已不存在的目录。死配置。 | 同上 |
| E5 | `docs/ARCHITECTURE.md` | ① 「唯一的架构测试：`test_import_rules.py`」——`tests/architecture/` 现有 8 个测试文件（source budget ratchet、时长 ratchet、可达性、plist XML、告警中文、不碰真实 App Support）。② `starquant_cli` 职责表少了**整个 `governance` 组（17 个子命令）**、`data metrics/spot/onchain/index/macro`、`research mine/book/decompose/list`、`live soak/verify/alert-test`、`report weekly`。③ D-035 写「产物：`scratchpad/p32d-pit.json`、`scratchpad/p32d-static.json`」——这两份被 `.gitignore` 的 `scratchpad/*.json` 忽略，**仓库里没有**；唯一副本在 `worktrees/deepen-live-loop/scratchpad/`，那是一个已合入、随时会被清掉的 worktree。 | `starquant <group> --help`；`find` |
| E6 | `docs/RUNBOOK.md` | 0 次提到 `governance`、shadow soak、paper-l3、proxy-probe、`live soak`、`research mine`、`report weekly`、`data spot`。6 个 launchd 任务只写了 3 个（live / data / check）；`run_data.sh` 已含 `data spot` 而表里写的仍是「klines + 资金费率 + 池刷新」。 | `grep -c` |
| E7 | `scripts/p12_stage1_compare.py` | 写死 `/private/tmp/p12/reports/...` 与 `/private/tmp/p12`（会话临时目录），无人引用，跑不了第二次。与 `.gitignore` 里「脚本入库是为了可复现采纳决定」的理由矛盾——而且 P12 在 stage 1 量出 inert，根本没被采纳。 | 文件第 13–16 行 |
| E8 | `scratchpad/p24_record.py` | 一次性往**真实 ledger** `reports/research/trials.jsonl` 追加 8 行的脚本（`LEDGER` 写死），已经跑过（ledger 里 `P24-arm1` / `P24-arm2` 各 4 行）。无人引用。再跑一次就是重复计费，而 ledger 按设计不可撤回。要么删，要么加「这两个 run_id 已在 ledger 则拒绝」的守卫。 | 第 43 行；`trials.jsonl` |
| E9 | `reports/research/trials.jsonl` | `run_id = mine-shortlist-20260907T043712Z` 的 **514 行（全 ledger 22%）** 指向一份仓库里从未存在过的报告（`git log --all` 无此文件）。RESEARCH_LOG:2505 解释了它是 DL-K2 之后「只记账不重搜」的补记账重跑，所以不是错账；但它是 ledger 里唯一一个机器核不到证据的 run，`replay` 与 family gate 都在数它。 | `git log --all -- 'reports/research/mine-shortlist-20260907T043712Z*'` 为空 |

---

## 二、对系统没有用处的源码

### A. 已判定不可用仍留在树里：liquidation 数据层（1,237 行 + 1 fixture）

可达性守卫里具名豁免（「#19 判定不可用：Binance 不发布 USDⓈ-M 强平历史，唯一的币本位档案早于实盘期 23 个月停更」）。留下的理由是「作为查过什么的记录」——那份记录在 RESEARCH_LOG 与 git 历史里都有，代码本身占的是非 alpha 行数（ratchet 已零 headroom）。

| 文件 | 行 |
|---|---|
| `starquant_data/liquidations.py` | 451 |
| `starquant_data/liquidation_archive.py` | 145 |
| `tests/data/test_liquidation_ingest.py` | 302 |
| `tests/data/test_liquidation_alignment.py` | 339 |
| `tests/fixtures/liquidations/BTCUSD_PERP-liquidationSnapshot-2024-10-01.head.csv` | 15 |

**不在此列**：`starquant_live/liquidation.py` 与 `tests/live/test_liquidation_*` / `helpers_liquidation.py` 是 DL-X1 的「强平距离」观测，在用。

### B. 建成但没有任何读者的三条数据源（源码 1,757 行 + 测试 2,092 行）

三者都能从 `starquant data onchain|index|macro` 到达，但：`research_cmd._load` 只 join `metrics` 与 `spot`；`starquant_alpha` 没有任何叶子或信号读它们的列；`deploy/run_data.sh` 明确把三者排除在日程外并写了理由（index：「NOTHING reads the store」；onchain：「exactly one column can reach live even on a PASS」；macro：「NO store by its author's scope call」）。09-10 由三个分支带入。这不是 bug，是搁置的功能；但在「alpha 投入 90%」与「source budget ratchet 零 headroom」两条约束下，它是仓库里最大的一块**今天没用**的非 alpha 源码。

| 源码 | 行 | 对应测试 | 行 |
|---|---|---|---|
| `starquant_data/macro.py` | 844 | `tests/data/test_macro_ingest.py` | 449 |
| | | `tests/data/test_a_revised_value_may_not_reach_a_bar_that_predates_the_revision.py` | 464 |
| `starquant_data/onchain.py` | 606 | `tests/data/test_onchain_ingest.py` | 427 |
| | | `tests/data/test_the_onchain_contract_refuses_a_backfilled_column.py` | 336 |
| `starquant_data/index_price.py` | 307 | `tests/data/test_the_index_contract_refuses_a_wrong_offset.py` | 416 |

（`tests/data/test_a_column_may_not_reach_live_without_a_declared_offset.py` 是通用的对齐契约，metrics 也靠它，保留。）

两种处置都成立：留作储备直到有叶子要读；或撤出直到那一天，git 里随时能拉回。决定权在操作者。

### C. 无人调用的符号（文件不能删，行可以删）

AST 扫描 + grep 双重确认（含 `getattr(..., "name")` 字符串派发；`leverage_brackets` 就是这样被用到的，已剔除）。

| 位置 | 符号 | 状态 |
|---|---|---|
| `starquant_alpha/signals/chanlun.py:120`、`:194` | `_fractals`、`_centres` | 定义了，模块内无人调 |
| `starquant_alpha/validation/multiple_testing.py:25`、`:40` | `benjamini_hochberg`、`holm` | 只有测试调；门用的是 `max_sharpe_quantile` |
| `starquant_alpha/validation/labels.py:15` | `execution_forward_returns` | 无人用 |
| `starquant_alpha/validation/stability.py:89` | `regime_split_sharpes` | 无人用（RESEARCH_LOG 提过名字） |
| `starquant_alpha/features.py:53`、`:339` | `annualize_vol`、`clip_unit` | 无人用 |
| `starquant_alpha/panel.py:342`、`:268` | `Panel.latest_bar`、`Panel.reference_mask` | 无人用 / 只有测试 |
| `starquant_alpha/backtest.py:192` | `BacktestResult.equity_curve` | 无人用 |
| `starquant_alpha/model.py:153` | `AlphaModel.reference_for` | 只有测试 |
| `starquant_alpha/report.py:15` | `report_digest` | 只有测试 |
| `starquant_shared/types.py:27`、`:84` | `Side.opposite`、`Position.is_flat` | 无人用 |
| `starquant_exchange/rules.py:23` | `quantize_price` | 无人用 |
| `starquant_exchange/guard.py:81` | `WriteGuard.engage_kill_switch` | 无人调；CLI 走 `live_cmd.engage_kill_switch` + `lock.engage_kill_switches`，同一件事两份实现 |
| `starquant_governance/replay.py:42` | `D026_CONSTRUCTION_DIGEST` | 无人读 |
| `starquant_live/staleness.py:48-49` | `LIVE_CYCLES_EXAMINED`、`LIVE_CYCLES_WITH_DROPPED_INPUTS` | 无人读 |
| `starquant_data/metrics_snapshot.py:33` | `METRICS_PATH` | 无人读 |
| `starquant_data/onchain.py:123`、`:387` | `AssetNotCovered`、`align_daily_to_bars` | 无人用 / 只有测试（随 B 走） |
| `starquant_data/macro.py:803`、`:457`、`:556` | `AlfredClient.family_ledgers`、`revision_history`、`align_family_to_bars` | 无人用 / 只有测试（随 B 走） |
| `starquant_data/index_price.py:94`、`:152` | `INDEX_DEGENERATE_FIELDS`、`index_archive_path` | 只有测试（随 B 走） |

---

## 三、`reports/research/` 里无人引用的报告（80 个文件，1,276 KB）

不被 `config/alpha_registry*.yaml`、`config/live.demo.yaml`、`docs/`、`tests/`、`governance/`、任何源码或脚本引用。
分两组，处置不同：

**第 1 组：连 ledger 行都没有的纯输出（27 个 stem，54 个文件）。** 这些运行没有计费，删掉不动任何 N。
其中 7 份 `tsmom-backtest-*`：`research backtest` 不过 exit overlay，仓库现行口径下不是证据（`b30a9c3d`）。
`research decompose` 按 D-024 明确不计 ledger。4 份 `correlate-tsmom-flow-20260903T*` 是同一天同一小时反复跑的。

```
book-tsmom-mined_594a12f9307a15d9-20260912T181708Z
correlate-tsmom-flow-20260903T0631Z
correlate-tsmom-flow-20260903T1258Z
correlate-tsmom-flow-20260903T1321Z
correlate-tsmom-flow-20260903T1322Z
decompose-tsmom-20260904T024055Z
decompose-tsmom-20260904T052958Z
flow-validation-20260903T0619Z
overlay-20260903T1247Z
overlay-20260903T1258Z
overlay-20260903T1322Z
overlay-20260904T024318Z
overlay-20260904T024516Z
overlay-20260904T024717Z
overlay-20260904T024916Z
overlay-20260904T030758Z
overlay-20260904T030813Z
overlay-20260913T201539Z
tsmom-backtest-20260903T0605Z
tsmom-backtest-20260903T0622Z
tsmom-backtest-20260904T134831Z
tsmom-backtest-20260904T134847Z
tsmom-backtest-20260904T134849Z
tsmom-backtest-20260904T134851Z
tsmom-backtest-20260904T181749Z
tsmom-validation-20260903T0605Z
tsmom-validation-20260903T0839Z
```
（每个 stem 各有 `.json` 与 `.md`。）

**第 2 组：有 ledger 行但无人引用（13 个 stem，26 个文件）。** 它们是 ledger 行的证据，全部是 FAIL / REJECT 或已被后续指针取代。
建议**归档到子目录**（如 `reports/research/archive/`）而不是删：治理回放只扫顶层 `*.json` 且不递归（`diagnostics/README.md` 写明），移走不影响 AC-G0，ledger 行照旧。

```
book-tsmom-flow-20260904T052533Z                        ACCEPT（被 20260908T105322Z 取代）
book-tsmom-mined_594a12f9307a15d9-20260912T181636Z      REJECT
carry-validation-20260909T102314Z                       FAIL
flow-validation-20260903T1322Z                          FAIL
flow-validation-20260903T1328Z                          FAIL
flow-validation-20260903T1329Z                          FAIL
mine-shortlist-20260909T082915Z                         （284 KB）
mined_00f951c68c4d55fa-validation-20260906T083728Z      FAIL
mined_9fd2e600e16c6f9a-validation-20260906T083703Z      FAIL
mined_e89799cab0dbc5cf-validation-20260906T083627Z      FAIL
residual-validation-20260909T102836Z                    FAIL
tsmom-validation-20260904T035907Z                       WEAK_PASS
tsmom-validation-20260909T055023Z                       PASS（被 055957Z 及之后的指针取代）
```

**核过、不是孤儿**：`tsmom-validation-20260914T174319Z` / `174503Z` 在 09-15 被 `404a752b` 撤出、又被同日 `4cc254e1`（操作者裁定，第五类归因）有意加回，不是误加。

---

## 四、`scratchpad/` 里无人引用的脚本（15 / 53）

`.gitignore` 说脚本入库是「为了可复现采纳决定」。下面 15 个没有任何文档、配置、测试或源码按名字引用它们（按文件名与去掉 `.py` 的 stem 各 grep 一遍）。分三类：

**过程工具，不是研究记录（2）**
- `resolve_log_append.py`：09-09 那批并行 agent 合并 RESEARCH_LOG 时的冲突处理助手。
- `alert_dedup_clock.py`：一次性排障（「每小时 FAIL 的巡检，操作者收到了吗」）。

**有副作用的一次性脚本（1）**
- `p24_record.py`：见 E8。

**审计 / 复核脚本，数字进了文档但文档没有点名（12）**
- `audit20260908_composed_book.py`、`audit20260908_gap_return.py`、`audit20260908_live_cost_rescore.py`、`audit20260908_nw_lag_sensitivity.py`（09-08 外部审计的四个复核；同批的 `guards_in_validate` / `stress_windows` 有引用，这四个没有）
- `exit_overlay_timing.py`（P1 向量化前的计时）
- `exp_g6prime_false_stop_rate.py`（EXP-G6′，预登记于 6e87e7ed）
- `flow_warmup_and_keying_are_bit_identical.py`
- `membership_dead_slots.py`（O4 的 0.30% 空槽）
- `p32f_embargo_and_decay.py`
- `participation_exempt_reductions_identity.py`
- `probe_stop_recalibration.py`（预登记于 b883d01e）
- `refit_boundary_slice_invariance.py`

如果规则是「每个 scratchpad 脚本都是记录」，那第三类要么补引用，要么它们就是没人会再读的记录。

另：`scratchpad/k-ladder-frozen.md` 是放在脚本目录里的 Markdown，被 ladder audit 引用——位置不对，内容有用。

---

## 五、测试树

- 全绿。但约 **2,733 行**测试守着第二节 A / B 两块没人用的代码，随它们一起走。
- **死 fixture（5 个文件，无任何读者）**：`tests/fixtures/august_2026/dataset-index.json` 与 4 份 `*/1h.manifest.json`——旧 dataset manifest 格式；`starquant_data/manifest.py` 自己从 parquet 页脚算摘要，不读它们。同目录的 `baseline-report.json`（`trend-alpha-v3-policy-v1` 的平价锚）被 `test_tsmom_parity.py` 用着，保留。
- `tests/architecture/test_source_budget.py`：2,898 行 / 256 KB，其中 103 条「第 N 次抬表」注记，两个测试函数。按设计如此，不是删除对象；但它已是仓库第 7 大文件，比任何一个生产模块都长。
- 8 个跨文件重名的测试函数（如 `test_a_5xx_is_retried_and_a_4xx_is_not` 同时在 onchain 与 macro 的 ingest 测试里）：复制粘贴的痕迹，与第二节 B 同源，不是错误。

---

## 六、本地、不入库的垃圾

不在 git 里，但占着盘、且 E5 ③ 那两份产物就藏在其中一个里。

- `worktrees/`：4 个 worktree，**全部干净、全部已合入 main（ahead 0）**，共 210 MB：
  `caliber`（50 MB，`feat/caliber-four`）、`deepen-live-loop`（51 MB）、`hopeful-gates-6e17c5`（61 MB，detached）、`unruffled-wilbur-994182`（48 MB，detached）；另有一条指向 `/private/tmp/.../fp-before` 的 prunable 记录。
- **70 个已合入 main 的本地分支**：33 个 `worktree-agent-*`、9 个 `session/*`、其余 `feat/` `research/` `fix/` `docs/`。未合入的只有 4 个（`archive/head-wt-warmup-draft-20260904`、`session/context-md-and-d035`、`session/practical-khayyam-66764b`、`session/sharp-dijkstra-0b7feb`）。
- `.starquant/live-dry-run/`（空目录，09-07）、`.starquant/paper/`（09-09 的旧 paper 状态，现行是 `paper-l3`）。
- `scratchpad/` 下被忽略的输出：`da-report/`、`paper-state/`、`paper-state2/`、13 个 `*.json` / `*.log`。
- `.superpowers/sdd/2026-09-07-exits-optimization-execution-plan`（插件残留，09-07）。

---

## 七、读上去像冗余、其实是记录（不建议动）

- `docs/analysis/` 27 份分析与计划文档、`docs/RESEARCH_LOG.md`、`reports/research/scratch/` 与 `diagnostics/`（各有 README 说明规则）。
- 5 个 `enabled: false` 的信号模块（xsmom / carry / meanrev / breakout / residual）与从未启用的 chanlun / pairs：证据 FAIL，但它们是 alpha 库存，正是 90% 目标要养的那一侧。
- `reports/research/` 顶层的 `p10-* / p12-* / q4c-* / paired-*` 产物：被 RESEARCH_LOG 或 `live.demo.yaml` 引用。
- `config/alpha_registry.candidate.yaml` 这个文件本身：shadow soak 需要一份候选。错的是它的内容（E1），不是它的存在。

---

## 建议的处理顺序（都是操作者的决定）

1. **先修错误（E1–E9）**。E1 最急：重新生成候选（或干脆从当前 armed registry 复制 + 注释块）并 `launchctl kickstart -k gui/$(id -u)/com.starquant.shadow`。E3/E4 二选一：恢复目录（`git checkout 7a950806^ -- vendor`）或删掉三处引用。E5 ③ 二选一：把 p32d 两份 JSON 提交到 `reports/research/`（p10 / p12 / q4c 的先例），或改引用。
2. **清纯输出**：第三节第 1 组 54 个文件、E7、五个死 fixture、两个过程脚本。这些没有任何东西依赖。
3. **归档**：第三节第 2 组 26 个文件移到 `reports/research/archive/`。
4. **定夺第二节 A / B**（约 5,000 行源码 + 测试）：唯一需要操作者裁定的大项。
5. **本地清理**：`git worktree remove` ×4、`git worktree prune`、`git branch -d` ×70。

每一步做完都要重跑四道门；第三节任何移动之后跑一次 `starquant governance replay`，AC-G0 必须仍是 0。

---

# 执行后的更正（2026-09-16 晚）

操作者裁定「按照建议执行」。执行过程推翻了上面正文的**三条**判断。正文原样保留——一条判断错在
哪里，本身就是这份报告最该留下的东西。三条错的是同一个东西：**我用「有没有人按文件名引用」
当作「有没有用」的判据，而这个仓库里有五处按目录 glob 读文件的代码，grep 看不见那条边。**

## ① 第三节「80 个无人引用的报告」——按名字引用是错的判据，实测炸了一次

正文建议删 54 个、归档 26 个。改为**全部归档不删**（更安全且效果相同）之后，第一版把 39 组移进
`reports/research/archive/`，`starquant governance next` 当场变了：

```
-    shortlist_candidates     9    ... minus 3 already validated
+    shortlist_candidates    12    ... minus 0 already validated
-scheduler VALIDATE  9 shortlisted candidates are unvalidated
+scheduler VALIDATE 12 shortlisted candidates are unvalidated
```

`assemble()` 判断一个候选「已经验过」靠扫 `reports/research/*.json`，被移走的三份
`mined_*-validation-*.json` 正是那三个候选的验证证据。**照这一版做下去，下一轮挖掘会在已经做完
的工作上重新花 ledger 行**，而 ledger 只追加、拿不回来。

据此清点了全仓五处 glob 读报告目录的代码（见 `reports/research/archive/README.md` 的表），
把可归档的名字收窄到不匹配任何 glob 模式的四种：`overlay-*`(10 组) / `tsmom-backtest-*`(7) /
`correlate-*`(4) / `decompose-*`(2)，**23 组 46 个文件**。`*-validation-*`、`book-*`、
`mine-shortlist-*` 全部留在上一层，哪怕没有任何文档引用它们。

四条命令移动前后输出**逐字节相同**：`governance replay`（AC-G0 仍 15/31/0）、`governance next`、
`report weekly`、`live run --dry-run --cycles 0`。

**正文那个「80 个文件、1,276 KB」的数字因此不再是可清理量**：真正可归档的是 46 个文件。

## ② E7「删 `scripts/p12_stage1_compare.py`」——它是一份被引用报告的唯一出处

正文的事实描述没错（无人引用、写死 `/private/tmp/p12`、跑不了第二次），结论错了。它是
`reports/research/p12-stage1-20260904T073645Z.json` 的产出脚本——`FIELDS` 正是该报告 `runs.*`
的键集，`LABELS` 正是它的 `baseline / m=2 / m=4 / m=8`——而那份报告被 `docs/RESEARCH_LOG.md`
引用。删掉它，仓库里会留下一个被引用的数字而没有任何东西说得出它怎么算的。

**改为保留 + 在 docstring 里记下出处**，并明说「这份比较不能从仓库复现」。写死的临时路径不是
要修的缺陷，是一次已经发生过的运行的事实。

## ③ 第四节「删两个过程脚本」——改为一个不删

正文建议删 `resolve_log_append.py` 与 `alert_dedup_clock.py`。**两个都不删。** 前者是仍在用的
并行会话合并工具（RESEARCH_LOG 仍然是 append-only，多会话仍在追加）；后者与那 12 个审计脚本
同形，单独删它没有一致的理由。`scratchpad/` 是记录目录，53 个脚本每个带一段说明自己测了什么的
docstring，删 134 行换不来什么，而误删一份记录换不回来。

**唯一在 `scratchpad/` 做的改动是给 `p24_record.py` 加守卫**（E8）：它是唯一写真实 ledger 且已经
跑过的入库脚本，守卫在回测之前拒绝，实测 0.33s 退出、 ledger sha256 不变。

---

## 实际执行了什么（四次提交，均在 `chore/repo-redundancy-2026-09-16`）

| 提交 | 内容 |
| --- | --- |
| `67fd14e0` | E1：候选 registry 按 armed 重新生成 + soak 重启 + 条件式身份守卫（负控制已跑） |
| `1ba355f0` | E2–E6：README 七个包、ARCHITECTURE 架构测试表与 CLI 表、D-035 的 p32d 产物入库、RUNBOOK 补 governance 与三个 launchd 任务；并恢复 `7a950806` 误删的 `vendor/backtest-guard/` |
| `79fc16c3` | 23 组报告归档、5 个死 fixture 删除、`reports/weekly/` 进 .gitignore |
| `dfe24f0d` | E8 守卫 + E7 的出处注记 |

**E9 未动 ledger，且不应动**：那 514 行按 `docs/RESEARCH_LOG.md:2505` 是 DL-K2 之后「只记账不重搜」
的补记账重跑，不是错账；ledger 只追加是 DSR 分母可信的前提，删行需要一次带署名的裁定（Q7 先例）。
本轮只把它记在这里。

**审查期间顺带发现并修掉的一条**（不在正文里）：`starquant report weekly` 写
`reports/weekly/<date>.{json,md}`，而 `.gitignore` 只忽略 `reports/daily/`，于是生成的报告躺在
`git status` 里像未完成的改动。已按同一条理由加进 .gitignore。

## 第二节 A 与 B 都已执行（`e616cdb3`、本节末的清算那一笔）

> **再更正**：下面「A 仍未执行」那句话在写下之后不久就不成立了——操作者同日裁定把 A 也撤出。
> A 的执行结果与它漏掉的一个文件记在本节最后。整节保持原样，这样两次裁定之间那个状态还在。

**B 撤出了**（操作者同日裁定）：`index_price.py` / `macro.py` / `onchain.py` 加三个命令、五个测试
文件与 `scratchpad/verify_live.py`，**1,757 行源码 + 2,092 行测试**。判据是五条命令的输出撤出前后
**逐字节相同**（`governance reopen|replay|next`、`report weekly`、`live run --dry-run --cycles 0`），
外加两条独立证据：`research_cmd._load` 只 join `metrics` 与 `spot`，`.starquant/data/` 里从来没有过
这三条的 store。 source budget ratchet 同步降表（`starquant_data` 5,472 → 3,718、`starquant_cli` 6,178 → 5,943），
七个包回到零 headroom。细节见 `docs/RESEARCH_LOG.md` 同日第二条。

那一轮还补上了正文没说的一条：这三条之所以能活六天没被任何守卫拦住，是因为
`test_every_module_is_reachable_from_an_entry_point` 问的是「模块**能不能**被跑到」而不是
「有没有东西真的在跑它」——与本节开头那条 glob/grep 的教训是一对。

**A 仍未执行，也不建议由我执行**——删它等于替操作者决定一块功能的去留。价钱如下：

| | 源码 | 测试 | 今天的状态 |
| --- | --- | --- | --- |
| A. liquidation 数据层 | 596 行 | 641 行 + 1 fixture | 可达性守卫里**具名豁免**：Binance 不发布 USDⓈ-M 强平历史，唯一的币本位档案早于实盘期 23 个月停更。判定不可用，留作「查过什么」的记录 |
| B. macro / onchain / index | 1,757 行 | 2,092 行 | 能从 CLI 到达，但 `research_cmd._load` 只 join `metrics` 与 `spot`，`starquant_alpha` 没有任何叶子读它们的列，`run_data.sh` 明确把三者排除在日程外并写了理由 |

两块都**不影响**四道门，也不影响实盘。它们的成本是占非 alpha 行数（ratchet 零 headroom）与占读代码的人的
注意力。三种处置都成立：留作储备直到有叶子要读；撤出直到那一天（git 里随时拉回）；或只撤 A 留 B。

删之前要注意的一条：`starquant_live/liquidation.py`（强平距离观测，DL-X1）与
`tests/live/test_liquidation_*` **在用**，不属于 A，别一起带走。

### A 的执行结果（2026-09-16 同日第二次裁定）

撤出 `starquant_data/liquidations.py`(451) 与 `liquidation_archive.py`(145)、**三个**测试文件与归档
fixture，共 **596 行源码 + 748 行测试**。五条命令输出撤出前后逐字节相同，其中 `governance reopen`
的 `regime-47` 仍读 `3/4 present; missing liquidations`——那个探针问的是**磁盘**上有没有 store，
不是代码在不在，所以撤掉 ingest 没有让那条重开条件变得无法回答（它本来也回答不了）。
`EXEMPT` 因此**空了**：树里每个生产模块都能从某条命令走到。

**本报告在这里漏了一个文件。** 上表列了 5 个，实际是 6 个——
`tests/alpha/test_liquidations_reach_the_panel_as_missing_when_missing.py`(107) 不在其中，因为我
按 `tests/data/` 找的，而它住在 `tests/alpha/`。全量跑时它红了三项。**「按目录找文件」是这份报告里
第三个会漏的判据**，前两个是「按文件名 grep」和「模块可达性」。三次都是同一形状：一个看起来能回答
问题的判据，实际只覆盖了问题的一部分。真正的判据只有一个——把四道门全量跑一遍。

（该文件四个测试里三个用 `to_panel_columns`；第四个是 Panel 的通用保证，它自己的 docstring 就写着
继承自 metrics 那一份，而那份在另外两个文件里各有一份，所以整文件删掉不丢保证。）

**没有撤的**：`starquant_live/liquidation.py` 与 `tests/live/test_liquidation_*`、
`helpers_liquidation.py`（DL-X1 清算距离，35 项全绿），正如上表的注所说。
