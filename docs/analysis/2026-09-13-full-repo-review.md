# 全仓审查 · backtest-guard + 工程优化清单（2026-09-13）

```
══════════════════════════════════════════
   策略体检报告 · backtest-guard
══════════════════════════════════════════
```

**受检对象**：StarQuant，`main @ 1db3e611`（工作树干净）
**扫描**：`starquant_shared` / `starquant_data` / `starquant_alpha` / `starquant_exchange` / `starquant_governance` /
`starquant_live` / `starquant_cli` = **31,632 行**（另 `scripts/` 414 行；`tests/` 34,057 行 / 181 个文件 /
1,650 个测试；已排除 `vendor/`、`.venv/`、`scratchpad/`）
**上两份**：`docs/analysis/2026-09-05-backtest-guard-external-audit.md`、
`docs/analysis/2026-09-08-backtest-guard-external-audit.md`（本报告不重复其已闭环项）

**本轮实测**：环境为 `.venv`（Python 3.12.14、pandas 3.0.5、numpy 2.5.2、mypy 2.3.1）。
`ruff check` 全过、`ruff format --check` 305 个文件全过、`pytest -m "not network"` **1,650 项全绿，98.9s**、
`mypy` **30 个错误、退出码 1**。量化结论由本会话临时脚本产出，不写 ledger、不写报告。

**总评**：🔴 致命 0 项 · 🟠 高危 3 项 · 🟡 中 9 项 · 🔵 低 10 项（含逻辑项 3 项）

**判语**：

> 「未来函数、幸存者偏差、成交乐观这三类，这一遍在**被交易的那条路径上**仍然找不到——
> 前两份报告已经把它们逐条关掉了，而关掉的方式是结构性的（`FundingUnavailable` 今天还会在我手里抛出来）。
> 这一遍最重的三项都不在策略里，而在**支撑判断的那套机械**上：
> 给所有结论背书的 CI 已经连续红了 4 天 23 次推送，类型门挡在测试门前面，于是「测试全绿」这句话
> 在 CI 上已经 4 天没有被验证过；唯一干净的样本外序列（M-010）挂在一个解析失败时会静默返回空对象的文件上；
> 四道硬门里的 CPCV，它的 embargo 只有 50 根而特征回看窗是 720 根。
> 都不是「回测骗了你」，而是「负责发现回测骗你的那几件东西，自己没人看着」。」

---

## 更正（2026-09-13 晚，修复过程中被推翻的四条）

本节在正文之前，因为下面四条改变了正文里对应条目的**事实**。正文原样保留——一条判断错在哪里，
本身就是这份报告最该留下的东西。

**① `flow` 的 warmup 填充，我指错了地方（🔵 那条）。**
正文说"`imbalance` 在 `window`=24 根后就有值，而 `volume_window`=48，于是第 25–48 根 bar 上……"。
那是 `FlowParams` 的**类默认值**。shipped registry 跑的是 `window: 168 > volume_window: 48`，
这个区间**根本不存在**——预热头部整段被 `imbalance` 的掩码盖住了。
真正触发 `fillna(1.0)` 的是 `volume_ratio` 的**另一个** NaN：`baseline.where(baseline > 0)`，
也就是**48 根滚动均量正好为 0** 的标的。实测时点面板（205 币 × 49,937 bar）命中 4,284 个 symbol-bar，
**全部**来自这一支，其中 238 个落在 eligible/pit 掩码内、涉及 36 个币。
所以被当作"成交量最大扩张"计分的，是一个**已经停止报价**的标的——比正文说的那条更糟，而且是另一扇门。
它与 ④ 的空槽是同一群标的，从不同的门进来。

**② `parse_registry` 早就拒绝重复的 strategy id 了（🔵 那条）。**
正文写"并在 `parse_registry` 里显式拒绝重复 strategy id"。那是 2026-09-03 起就有的
（`starquant_alpha/registry.py:84`）。真正缺的是**第二扇门**：`AlphaModel` 也可以由 `replace`、
由 miner、由测试直接构造，那条路上没有检查。已补在 `AlphaModel.__post_init__`。
教训与正文自己引用的 RESEARCH_LOG:2192 同形：引用一条"应该加上"之前，先 grep 它是不是已经在那儿了。

**③ 那 0.30% 的空槽是两件事，合成一个数字把它们盖住了（🔵 那条）。**
109 个空槽只来自 **7 个**标的，其中 **81 个**是 ALLOUSDT / BLESSUSDT / ENSOUSDT / REUSDT /
SKYAIUSDT / SYNUSDT——正是 `research --universe pit` 每次都会打印的那六个"成员但没有 1h 档案"。
也就是说 2026 年那 0.33/刷新**全部是没回填的档案**，一个下载就能解决，不是退市尾巴。
只有 LUNAUSDT 的 28 次是正文描述的那个现象（滚动成交量把一个不再报价的币留在池子里）。
`membership_summary` 的新读数因此按标的分列，不出单一合并值。

**④ 那个被 NaN 缺口吞掉的止损，在任何合理的界下都救不回来——而这不改变修复的必要性。**
正文用 BNXUSDT 2023-02-22 14:00 的 STOP_LOSS 作为"缺口重锚"的代价证据。修复实现成**有界 carry**
之后（连续 N 根不可判的 bar 之内保持原仓与原锚，超过则平掉并置 flat），实测扫描：

| N | ragged tail 带来的 symbol-bar | BNXUSDT 那条止损 |
|---|---|---|
| 2（采纳） | 296（= 150 币 × 2） | 否 |
| 24 / 72 / 240 | 3,552 / 10,440 / 30,422 | 否 |
| 517 | 30,976 | 否 |
| **518** | 30,978 | **是** |
| 无界 | 79,447 | 是 |

BNXUSDT 的 638 根缺口**不是零散的**，是 518 / 72 / 24 / 24 四段，而那条止损在 518 那段后面。
救回它要求持有一个**21.6 天**没人能定价的仓位。采纳 N=2，与 `guards.stale_bars_max: 2` 同源：
实盘本来就拒绝在比 2 根 interval 更旧的数据上交易，研究侧 carry 更久就是在描述实盘永远不会做的事。

**所以正文那条 🟡 的严重度不变，但它的证据换了**：缺陷是"一根缺口会抹掉入场锚、使该段的止损静默失效"，
这是复现出来的；而"它吞掉了一个真实的止损"不再是这条的论据——在有界修复下那个止损仍然不响，
因为那 518 根缺口本身就超出了任何应当持仓的窗口。无界 carry 能救回它，代价是 79,447 个
symbol-bar 上持有已退市标的，那是拿一个更大的失真换一个止损。

---

## 第一遍 · 工程审查：问题清单

> 每条定位到 `文件:行`。

### [🟠 高危] CI 连续 23 次推送失败、4 天；类型门挡在测试门前面

**位置**
- `.github/workflows/ci.yml`（步骤顺序 Format → Lint → **Types** → Tests）
- `starquant_governance/family_gate.py:100,103,118-146`（22 个 `arg-type`）
- `starquant_live/reports.py:1202,1306,1313`、`starquant_governance/reopen.py:122,124,128`、
  `starquant_live/risk_budget.py:384`、`starquant_live/verify.py:105`、`starquant_live/engine.py:1373`、
  `starquant_cli/governance_cmd.py:513`

**问题**

最后一次绿色是 `2026-09-09T13:57Z`。此后 **23 次推送全部 failure**，每次 35–45s——这个时长说明它挂在
`mypy` 上，`pytest` 那一步**一次都没跑过**。本地跑是全绿的，所以它没有藏住一个真实的测试失败；
藏住的是**「有人在看」这件事本身**。这个仓库的整条治理线（预登记 → 证据 → registry 启动门）都建立在
「改动被机械检查过」之上，而现在机械检查在改动落地之前就停了。

30 个错误里绝大多数是 mypy 2.x 收窄规则变严导致的（`all(isinstance(...) for ...)` 不再收窄），
但有三处是**真实的契约漏洞**，不是噪声：

- `engine.py:1373` `self.model.entries` —— `ports.SignalModel` 协议里没有 `entries`。引擎越过了自己声明的
  端口去读具体实现。同一模式还有 `getattr(targets, "asset_vol", {})`、`getattr(targets, "book_weights", None)`
  （`engine.py:731,746,1379`）。一个满足 `SignalModel` 协议的替身模型会在 `_finish_cycle` 里崩掉。
- `reports.py:1306/1313` —— `wakes` 被推断成 `list[float]` 却 append 了 `tuple[float, float|None]`，
  下一行再解包。runtime 能跑，类型上自相矛盾，说明这段被改过一次而没人重读。
- `risk_budget.py:384` —— `Mapping | None` 上直接 `.get`。

**修复方向**

1. 先让 CI 变绿（这是所有其它修复的前提）：`family_gate` 那 22 条用一次显式收窄
   （`if not isinstance(sharpe, int|float) or ...: return UNREADABLE` 逐个写开，或抽一个
   `def _number(v) -> float | None`）；`reports.py` 给 `wakes` 显式标注；`engine.py:1373` 在
   `ports.SignalModel` 上补 `entries` / `asset_vol` / `book_weights`（或改用一个专门的协议）。
2. `ci.yml` 里把 `Tests` 提到 `Types` 之前，或给两步都加 `if: always()`——类型问题不应该让测试门失明。
3. 锁定工具版本（见下一条）。

---

### [🟠 高危] 唯一干净的样本外序列（M-010）挂在一个解析失败会静默清零的文件上

**位置**
- `starquant_live/state.py:70-76`（`StateStore.load`：`except (ValueError, TypeError): return LiveState()`）
- `starquant_live/engine.py:1124`（`since = self.state.last_income_ms or now`）
- `starquant_live/state.py:129-133`（`_atomic_write`：tmp + `replace`，**没有 fsync**，而同文件
  `_append:117-127` 是 flush + `os.fsync`）

**问题**

`state.json` 里有四样东西是**跨周期的唯一副本**：`last_income_ms`（收入水位线）、`equity_hwm`
（回撤高水位）、`exit_states`（每币入场锚与冷却）、`last_contributions`（D-005 的 hold 种子）。
文件读不动时 `load` 返回一个全新的 `LiveState`，**不抛、不告警、不记录**。后果逐条：

- `last_income_ms` 变 `None` → `since = now` → 窗口是 `[now, now]` → **停机期间的全部 income 永久不进
  `attribution.jsonl`**。KILL-006 的全部理由是「实盘归因是唯一干净的样本外」，而这条序列可以无声缺一段；
  `decay_watch` 只会看到 `live_windows` 变短，看不出缺了一块。
- `equity_hwm` 重置为当前权益 → 回撤读 0 → D-015 节流与 R8 阶梯同时失明。
- `exit_states` 丢失 → 下一轮 `_reconcile`（`exits.py:97`）用交易所 `entryPrice` 重建，止损距离按新锚重算。
- `last_contributions` 丢失 → 所有次阈值持仓的 hold 种子归零一次（RUNBOOK 已经写了「不要手动删除」，
  但没有说「损坏等价于删除」）。

`_atomic_write` 少了 `fsync`：`replace` 保证的是**改名**原子，不保证 tmp 的内容已经落盘。
同一个文件里 `_append` 专门为这件事写了六行注释并 fsync 了，`_atomic_write` 没有——这是同一个仓库里
两个标准。

**修复方向**

1. `load` 区分「文件不存在」（正常首启）与「文件存在但读不动」（异常）：后者抛出，让 `live run` 拒绝启动，
   并在消息里说明可以 `mv state.json state.json.bad` 后显式重建。
2. `_atomic_write` 补 `os.fsync(tmp_fd)` 与目录 fsync，与 `_append` 同一标准。
3. `_ingest_income` 在 `last_income_ms is None` 而 `state.cycles > 0` 时告警（这是「水位线丢了」，
   不是「第一次启动」）。

---

### [🟠 高危] CPCV 的 embargo 是 50 根，而特征回看窗是 720 根——四道硬门里的一道被污染

**位置**
- `starquant_cli/research_cmd.py:604`（`--purge` 默认 **50**）
- `starquant_cli/research_cmd.py:754` 与 `:1735`（`cpcv_splits(..., purge=purge, embargo=purge)`）
- `starquant_alpha/validation/cpcv.py:37-38`（`blocked[start-purge:start]`、`blocked[end:end+embargo]`）
- `config/alpha_registry.yaml:79`（`horizons: [168, 336, 720]`）

**问题**

`2026-09-08` 那份审计在 `:309` 写过「CPCV / walk-forward 走的是净收益序列，不存在标签跨边界」，
并在 `:330` 认可了 walk-forward 里 embargo 无效的论证。**对 walk-forward 那一半是对的**——训练窗永在
测试块之前，训练 bar 的特征窗不可能读到测试期价格。

CPCV 不是这个形状。它的训练集**按组合取，可以包含测试块之后的组**。一根位于测试块之后的训练 bar，
它的净收益由一个最长 720 根的回看窗产生，而那个窗口**覆盖了测试期的价格**。embargo 只挡住了它后面 50 根，
于是每个「测试块之后」的训练组里，最靠前的约 670 根 bar 的收益都含有测试期信息——而选择正是在这些
训练 bar 上做的（`cpcv.py:59` `sharpe(values[split.train_index])`）。

这不是未来函数（收益本身是因果的），是**选择污染**：`fraction_negative ≤ 0.10` 是 D-020 的硬门之一，
污染让它更容易通过。方向明确，**幅度本轮未测**。

**修复方向**

1. `embargo` 与 `purge` 拆成两个 CLI 选项，`embargo` 默认取模型的最大回看窗
   （`model.warmup_bars`，当前 registry 下 1,442；至少 `max(horizons)` = 720）。
2. 重跑一次现行 registry 的 `validate`，只动 embargo，看 `cpcv.fraction_negative` / `q05` 是否移动。
   这是**一次预登记的重测**，ledger +1；若不动，本条降为 🔵 并记为「已核」。
3. `walk_forward_folds` 的 `purge=50` 保持不变有它自己的论证（`walk_forward.py:55-58`），
   但同样值得记一句：它挡的是标签重叠，而这条管线没有前视标签，所以 50 这个数字今天不承载任何东西。

---

### [🟡 中] 依赖没有锁，证据仓库没有版本锚

**位置**：`pyproject.toml:19-27`（`numpy>=1.26` / `pandas>=2.2`）、`:30-38`（`mypy>=1.10`）；仓库无 lockfile

**问题**

本机解析到 **pandas 3.0.5 / numpy 2.5.2 / mypy 2.3.1**；CI 每次也重新解析到最新。pandas 3.0 改了
copy-on-write 与默认字符串 dtype 等语义。这个仓库的核心资产是 `reports/research/` 里几十份
**逐位可复现**的证据，而它们的数值取决于当时解析到的 pandas/numpy——`pyproject.toml` 里没有任何东西
记录那是哪一版。上面那条 CI 事故就是这个缺口的第一次兑现（`mypy>=1.10` 解析到 2.x，收窄规则变严）。

**修复方向**

加 `requirements.lock`（`pip freeze` 或 `uv lock`），CI 用它安装；`pyproject` 的宽范围留给库使用者。
并在 validate 报告里记录 `pandas.__version__` / `numpy.__version__`——与 `registry` 指纹、
`construction_fingerprint` 同一条理由：一份报告要能自我说明它是在什么上面跑出来的。

---

### [🟡 中] `exit_step` 在价格为 NaN 的那根 bar 上重锚入场价，止损对该段静默失效

**位置**：`starquant_alpha/overlays/exits.py:166`（`price > 0` 对 NaN 为假）、`:192-196`、`:199-208`（`_enter`）

**问题**（本轮已复现）

```
入场 100.0，sigma_1d 0.02（一个 k 单位 = 2.0）
无缺口：89 → 无事；87 → adverse 6.5 ≥ 6 → STOP_LOSS，权重归 0     ✓
有一根 NaN bar：NaN → entry_price 变 nan，仓位保留
              89 → _enter 重锚到 89
              87 → adverse 仅 1.0，不触发，权重仍是 1.0           ✗
```

同一条价格路径，插一根缺失 bar 就让止损不响。在研究侧还附带一次幽灵往返：`run_backtest:250`
把缺失收益 `fillna(0.0)`，那根 bar 的目标是 0（`build_weights` 的 `aligned.fillna(0.0)`），
于是记一次满额换手成本、收益 0，下一根再开回来。

**今天的暴露面**（本轮实测，1h 存档，PIT 成员 211 个 / 有 1h 数据 205 个）：

| | 数量 |
|---|---|
| 有**内部**小时缺口的成员 | **5**（BNXUSDT 638 根、OCEANUSDT 120、OGNUSDT 120、RSRUSDT 120、PUMPUSDT 7） |
| 内部缺失 bar 合计 | **1,005** |
| 完全没有 1h 存档的成员 | 6（ALLOUSDT / BLESSUSDT / ENSOUSDT / REUSDT / SKYAIUSDT / SYNUSDT，`live.demo.yaml:120-123` 已披露） |

实盘侧同一条路径可达：`model_inputs` 返回的帧若少了中间某根，`Panel.from_frames` 的并集索引就会造出 NaN。

**修复方向**

`exit_step` 在 `price` 非有限时**保持状态不动并返回上一根的权重**（既不平仓也不重锚），
而不是掉进 `_enter`。加一条属性测试：同一价格路径插入任意 NaN，退出事件序列必须不变。

---

### [🟡 中] `inputs.dropped` 只被记录、从不被读——一轮拿不到 K 线就把那个币平掉再开回来

**位置**：`starquant_live/inputs.py:59-60`、`starquant_live/engine.py:646-648`（`raw.setdefault(symbol, 0.0)`）、
`starquant_live/rebalancer.py:128`（`closing`）

**问题**

`closed_bars` 对某个币返回空帧或 < 2 根（退市、公共端点抖动、限频后的空响应）时，该币进 `dropped`，
不进 `usable`；模型不会给它权重；`run_cycle` 随后 `raw.setdefault(symbol, 0.0)` 把它补成 0；
`plan_rebalance` 读成 `closing` → **reduce-only 市价全平**。下一轮数据回来，再按信号开回去。

代价是两次穿越价差 + 退出锚重置 + 一次冷却期。`record["inputs"]["dropped"]` 写进了 `cycles.jsonl`，
**但没有任何地方读它**——没有告警、没有 skip、不计入任何阈值。这正是 D-041 / DL-Q0 已经在别处关掉的
那个形状：「记下来了，没有读者」。

注意退市时平掉是**对的**，所以修法不是「不平」，而是「要能分辨」。

**修复方向**

`dropped` 非空时告警（沿用 `alerts.send` 的去重键），并在 `report daily` 里计数；
连续 N 轮 dropped 才当退市处理（与 D-031 的 `quarantine_after` 同一形状），
单轮 dropped 视为数据抖动、保持上一轮仓位。

---

### [🟡 中] `_paged` 的游标在整页边界上丢弃同一毫秒的剩余行

**位置**：`starquant_exchange/binance_usdm/venue.py:264-277`

```python
last = int(page[-1].get("time", cursor))
if len(page) < 1000 or last <= cursor:
    break
cursor = last + 1
```

**问题**

两个静默丢数：

1. 满页（1000 行）恰好在时间戳 `T` 上截断，而 `T` 上还有更多行 → `cursor = T+1` 把它们跳过。
   income 的同毫秒成组是**常态**，不是巧合：一次资金费结算会给账上每个持仓币各写一行，
   `fundingTime` 相同。
2. 若满页里所有行都落在 `cursor` 这一毫秒，`last <= cursor` 触发 `break`，直接截断。

今天这个账户一小时窗口不会有 1000 行，但 D-030 的「第一轮用一个更宽的窗口把缺口补回来」
和停机后的追赶窗口都会拉长窗口。丢的是钱的账，而且没有任何一行日志说丢了。

**修复方向**

按 `(time, id)` 翻页，或保留 `cursor = last` 并按行 id 去重（`_paged` 的两个调用方
`income` / `userTrades` 都带唯一 id）；满页时不 break 而是继续，直到返回空页。

---

### [🟡 中] 失败退避吞掉的周期不计入 `missed_rebalances`（M-Q03 阈值是 0）

**位置**：`starquant_live/engine.py:1323-1326`（`backoff_seconds`）、`:551-596`（`guarded_cycle` 的
`await self.clock.sleep(self.backoff_seconds())`）、`:522-546`（`_record_missed_rebalance` 是
`missed_rebalances` 的**唯一**加一点，只在 `immediate` 重启路径上调用）

**问题**

退避是 60s 起、每次翻倍、封顶 3600s，`max_consecutive_errors` 是 12。第 7 次失败起每次退避就是
整整一根 bar。累计到第 7 次失败时已经睡掉约 7,380s ≈ 2 根 1h bar。这些 bar：
`wait_for_bar_close` 醒来时它们已经过去，**不会有 ERROR 行，也不会有 SKIPPED 行，
`missed_rebalances` 也不加一**。`config/live.demo.yaml:295` 写的是 `max_missed_rebalances: 0`，
而这条路径上的漏掉对它是不可见的。

**修复方向**

退避结束后，把「睡过去的那些 bar」逐根写一行 `phase: SKIPPED, reason: BACKOFF` 并计入
`missed_rebalances`；或至少在 `report daily` 里按 `bar_open_ms` 的连续性反推缺口数。

---

### [🟡 中] 参与率上限会截断「纯减仓」单，与它自己的文档相反

**位置**：`starquant_live/rebalancer.py:154`（`... and not closing`，**没有** `and not reduce_only`）、
`:23`（`max_participation` 的注释写的是 "cap on a **risk-adding** order"）、
`starquant_alpha/backtest.py:350`（回测重放同样只豁免全平，所以两半一致——一致地错）

**问题**

`closing`（目标 0 且有仓）被豁免，`pure_reduction`（15% 降到 5%）**不被豁免**。
文档说它管的是加仓单，代码管的是「除全平外的一切」。

这在平时无害，在压力下方向不对：成交量枯竭时 `cap = max_participation × 近 24 根均量` 同步缩小，
于是**最需要减仓的那根 bar，减仓速度也按流动性打了折**；同一轮里
`scale_orders_to_margin`（`leverage.py:52`）还在按 `available_balance × (1-buffer)` 缩加仓单。
两件事都指向同一个方向。

**修复方向**

`not closing` 改成 `not reduce_only`，并在回测的 `ParticipationModel` 重放里同步
（`backtest.py:350` 的 `exempt` 加上 `pure_reduction`）。这是行为变更、会动构造指纹，
按 K-EX14 的窗口规则处理。

---

### [🟡 中] REST 客户端记了 `used_weight` 却从不据此节流

**位置**：`starquant_exchange/binance_usdm/rest_client.py:59`、`:195-201`（`_read_rate_headers` 是
`used_weight` 的唯一写入方，全仓无读取方）、`:28-29`（429/418 只走被动重试）

**问题**

`docs/ARCHITECTURE.md:15` 把 `starquant_exchange` 的职责写成「签名、**限频**、熔断」。实际只有被动的
429/418 + `Retry-After` 重试，没有任何主动配额管理。`consecutive_transport_failures` 同样只写不读。
`starquant data sync` 会对 878 个候选逐个拉档案与 REST 尾巴，是最容易撞上权重上限的路径。

**修复方向**

要么按 `used_weight` 做一个简单的令牌桶（超过阈值就先 sleep），要么把 ARCHITECTURE 里的「限频」
改成「限频错误的退避」——**两者都行，不能是现在这样：文档声称一个不存在的能力**。

---

### [🟡 中] `starquant_exchange` 是风险/覆盖比最差的一块

**位置**：`tests/exchange/` 只有 1 个文件 `test_rest_client_and_guard.py`（261 行、**11 个测试**），
对应 `starquant_exchange` 611 行 + 整条签名/重试/歧义/分页路径

**问题**

全仓 181 个测试文件里，`tests/live` 64 个、`tests/alpha` 47 个、`tests/governance` 28 个，
而唯一真正会向交易所写入的包只有 11 个测试。`venue.py:43-75` 的 `parse_position` 已经出过两次真实事故
（`unRealizedProfit` / `unrealizedProfit` 拼写、`totalInitialMargin` 的 int64 溢出），
`_paged` 的缺陷（上文）就在没有专门测试的那一段里。

**修复方向**

补 `_paged` 的边界用例（满页 + 同毫秒成组）、`OrderOutcomeUnknown` 的三条分支
（ConnectTimeout / ReadTimeout / 5xx）、`_sign` 与实际发出的 query string 逐字节一致
（现在签名串来自 `urlencode`，实际发送由 httpx 编码——今天的参数都是符号与整数所以相等，
但这是一条没有测试守着的隐含假设）。

---

### [🟡 中] 引擎越过自己声明的端口读具体实现

**位置**：`starquant_live/ports.py:114-140`（`SignalModel` 协议）、`starquant_live/engine.py:1373`
（`self.model.entries`）、`:731,746,1379`（`getattr(targets, "asset_vol"/"book_weights", ...)`）

**问题**

`ports.py` 的开篇写着「`starquant_live` 只与这些接口对话」。`entries` 不在 `SignalModel` 里，
`asset_vol` / `book_weights` 不在 `TargetSet` 里。`getattr` 默认值让它在 runtime 不炸，
代价是**协议不再描述真实契约**——这也正是 mypy 报 `engine.py:1373` 的那一条。

**修复方向**

把这三样加进协议（`asset_vol` / `book_weights` 可以是 `@property` 返回空 Mapping 的默认），
`getattr` 随之删掉。

---

### [🔵 低] `garch` 与 `hrp` 的重拟合边界按数组位置排布，切片起点一变读数就变

**位置**：`starquant_alpha/features.py:118`（`boundaries = list(range(max(refit_bars, min_obs), n_bars, refit_bars))`）、
`starquant_alpha/portfolio.py:208`（`t % params.hrp_refit_bars == 0`）

**问题**

两者的重拟合时点都是**面板起点的函数**，不是日历的函数。同一根日历 bar，在 `panel.slice(...)` 出来的
不同窗口上会拿到不同的 GARCH 参数 / 不同的 HRP tilt。这与 D-033 记的那个教训同形
（「实盘那份递推是在每周期滑动一根的请求窗口上从头重建的，锁存点因此是窗口起点的产物」）。

两者今天都默认关闭（`vol_model: "ewma"` / `budget_mode: "inverse_vol"`），#35 与 #48 都已 REFUTED，
所以**今天不影响任何数字**。记在这里是因为：若哪天重开，实盘的滑动窗口会让它每小时换一次边界。

**修复方向**

边界按时间戳定位（例如「每月 1 日 00:00Z 重拟合」），而不是按 `t % refit_bars`。

---

### [🔵 低] chanlun `level: 4h` 重采样出的不是交易所的 4h K 线

**位置**：`starquant_alpha/signals/chanlun.py:367-369`（`resample(rule, label="right", closed="right")`）

**问题**

面板按 **bar 开盘时间**索引。`closed="right"` 把开盘时间落在 `(00:00, 04:00]` 的四根归成一组、
标在 `04:00`——也就是 01/02/03/04 这四根，真实时间 01:00–05:00。**因果上正确**（标在 04:00 的值
需要 04:00 那根的收盘即 05:00，而决策 bar 04:00 的信息集正好到 05:00），这也正是作者选 `closed="right"`
的原因；代价是它落在 01–05、05–09 的网格上，**不是币安的 4h K 线**（00–04、04–08）。

chanlun 今天未启用。若启用并与 4h 图表对照，结构会对不上，而对不上的原因不在算法里。

**修复方向**

改用 `closed="left", label="left"` 得到交易所网格，再整体 `.shift(1)` 对齐可用时点；
或在文档里写明「4h 级别用的是错开一小时的网格，且这是刻意的」。

---

### [🔵 低] `flow` 的 `expansion` warmup 用最激进的一端填充

**位置**：`starquant_alpha/signals/flow.py:93`（`volume_ratio(...).clip(upper=1.0).fillna(1.0)`）

**问题**

`expansion ∈ (0, 1]`，`fillna(1.0)` 是**上界**，不是中性值。`imbalance` 在 `window`=24 根后就有值，
而 `volume_window`=48，于是第 25–48 根 bar 上信号按「成交量最大扩张」计分。
方向上偏激进而不是偏保守。实盘请求窗口远长于 48 根，所以只影响短窗口回测的头部。

**修复方向**

`fillna(1.0)` 改为不填（让 `score` 在 `expansion` 未预热时保持 NaN），`warmup_bars` 已经是
`max(window, volume_window)+1`，改完与它一致。

---

### [🔵 低] 退市那根 bar 的真实损失不计；PIT 表里有 0.30% 的「有名额没数据」槽位

**位置**：`starquant_alpha/backtest.py:250`（`rets = ...fillna(0.0)`）、
`starquant_data/pool.py:131-132`（`window = before.iloc[-volume_lookback_days:]`，`fillna(0.0).sum()`）

**问题**

两件相关的小事，本轮都量过：

1. `run_backtest` 把缺失收益填 0，所以一个在成员期内停止报价的币，它最后那根 bar 的真实损失是 0。
   **今天不构成幸存者偏差**：LUNAUSDT 的崩盘完整在数据里（最后 72 小时 −99.98%，收盘到 0.008），
   所以那笔钱是亏到了的。
2. 但 30 日滚动成交量会把一个已经不报价的币留在池子里最多 30 天——LUNA 的最后一根 1h bar 是
   `2022-05-13`，而 membership 一直 True 到 `2022-06-10`，**28 次 refresh**。
   那些天它占着 top-15 的一个名额而没有数据。

全表量化（2,042 次 refresh、35,899 个「成员-刷新」槽位）：

| | |
|---|---|
| 至少有一个空槽的刷新日 | 104（**5.1%**） |
| 空槽总数 | 109 / 35,899（**0.30%**） |
| 最差 | 2026-07-18~22，18–20 个名额里空 2 个 |
| 按年 | 2021 0.00 / 2022 0.08 / 2023 0.00 / 2024 0.00 / 2025 0.00 / 2026 0.33（每刷新均值） |

0.30% 不改变任何结论。记下来是因为「N 选 K 在某些期退化」这类问题，**量过的 0.30% 与没量过的
未知量不是一回事**。

**修复方向**

`point_in_time_membership` 排名前先要求该币在窗口末尾仍有数据（例如最近 2 天有日线）；
或在 `membership_summary` 里报一个 `dead_slot_share`，让它在报告里可见。

---

### [🔵 低] `_atomic_write` 没有 fsync（同一文件里 `_append` 有）

**位置**：`starquant_live/state.py:129-133` vs `:117-127`；`starquant_data/store.py:64-67`（parquet 同样 tmp+replace 无 fsync）

见上文高危第二条。这里单列，是因为 `store.py` 也是同一模式，而它写的是 4.1 GB 的行情档案。

---

### [🔵 低] 一轮里的 REST 调用与下单都是串行的

**位置**：`starquant_live/reconciler.py:86-88`（`account` → `positions` → `mark_prices` 三次顺序 await）、
`starquant_live/engine.py:791-820`（订单 `for` 循环里逐个 `await execute_order`）

**问题**

`take_snapshot` 的三次可以 `asyncio.gather`（互不依赖）。下单串行影响更实在：`execute_order`
在非终态时会 `clock.sleep(1.0)` 最多 5 次，于是**同一根 bar 的最后一单可能比第一单晚几十秒**，
成交价离 `decision_close` 更远——而 `decision_close` 正是 M-Q08 滑点的基准
（`engine.py:812-818` 每笔都记）。也就是说：串行下单会直接抬高它自己被测出来的滑点。

**修复方向**

快照三次 `gather`；订单用一个有并发上限的 `gather`（比如 4），或直接用 `/fapi/v1/batchOrders`。
注意 `client_order_id` 已经保证幂等，并发不会重复下单。

---

### [🔵 低] 翻向单按全额名义计保证金需求

**位置**：`starquant_live/leverage.py:50-51`

`adds` 里包含「多翻空」这种穿越零点的单，它的 `notional` 是 `|current| + |target|`，
但其中 `|current|` 那一半是**释放**保证金的。`needed` 因此高估，可能触发不必要的按比例缩单。

**修复方向**：`needed` 里对翻向单只计 `|target_notional| / leverage`。

---

### [🔵 低] `strategy_targets` 用 `zip(entries, dict.values())` 而不是按 id 取

**位置**：`starquant_alpha/model.py:193`

依赖 `strategy_scores` 返回的 dict 插入序与 `self.entries` 一致。真的一致（同一次遍历构建），
`strict=True` 也会在长度不等时抛——但**两个同 id 的 entry 会让 dict 塌掉一格**，届时抛出的
是一个和病因无关的 `zip` 错误。

**修复方向**：改成 `scores[entry.id]`；并在 `parse_registry` 里显式拒绝重复 id。

---

### [🔵 低] 三个文件过大，且都是改动最频繁的那三个

| 文件 | 行数 |
|---|---|
| `starquant_cli/research_cmd.py` | 3,080 |
| `starquant_live/reports.py` | 2,087 |
| `starquant_live/engine.py` | 1,856 |
| `starquant_alpha/mining/expr.py` | 1,080 |

`reports.py` 里那三个 mypy 错误（类型自相矛盾的 `wakes`）正是「文件大到没人重读一整段」的征兆。
`engine.py` 的 `run_cycle` 单函数 218 行、`_finish_cycle` 77 行。

**修复方向**

不建议为了行数而拆。建议只拆两处有自然边界的：`reports.py` 里的 M-0xx / M-Qxx 各指标计算
（纯函数、已经彼此独立）拆成 `reports/` 包；`research_cmd.py` 里每个子命令拆成一个模块，
`research_cmd.py` 只留 click 装配。

---

### [🔵 低] 没有覆盖率工具

`pyproject.toml:30-38` 的 dev 依赖里没有 `pytest-cov`。1,650 个测试、101 个源模块**每一个都被某个
测试文件提到过**（本轮核过），但「提到」不是「覆盖」。加一个 `--cov` 门槛（哪怕只是报告不设阈值）
能让上面那条「exchange 只有 11 个测试」这类失衡自己浮出来，而不是靠人去数文件。

---

## 已排除（命中可疑模式，读上下文后判为合法用法）

这一节是可信度的证明：下面每条都命中了陷阱清单里的模式，读完上下文判为正确。

- ✓ `starquant_alpha/validation/labels.py:12,19` —— 唯一的两处负数 `shift`，在显式的 label 构造里，
  全仓没有任何地方把它喂进 X。
- ✓ 全仓 **零处** `bfill` / `backfill` / `interpolate(` 作用在时变行情列上（命中的全是注释与文件名）。
- ✓ 全仓 **零处** `center=True`。
- ✓ `starquant_data/pool.py:152` `ffill` —— 成员表前向填充，因果。
- ✓ `starquant_alpha/signals/chanlun.py:380` `reindex(..., method="ffill")` —— 4h 分数向前铺到 1h 网格，
  `label="right"` 保证不会落在早于它自己输入的 bar 上。
- ✓ `starquant_alpha/backtest.py:247` `decided.shift(1)` —— 决策在 t、执行在 t+1，`open_to_close`
  还额外放弃了隔夜跳空（`:6-18` 量过：那部分对本书是**不利**的 −0.029 OOS Sharpe，不是有利的）。
- ✓ `starquant_alpha/backtest.py:120-121` —— 冲击成本的 ADV 与 sigma 都 `.shift(1)`。
- ✓ `starquant_alpha/portfolio.py:85-88` —— EWMA 协方差在 t 用到 `r[t]`，而 `r[t] = close[t]/close[t-1]-1`
  在 t 收盘时已知，因果。
- ✓ `starquant_alpha/features.py:177-179` `donchian` 显式 `shift(1)` 排除当根。
- ✓ `starquant_alpha/signals/chanlun.py:250-320` —— 单次前向扫描，缠论最常见的 repaint 形状在这里结构性不可达；
  `test_truncating_the_panel_does_not_change_the_scores_that_survive` 守着。
- ✓ `starquant_alpha/validation/metrics.py:25-43` —— 年化因子来自 `panel.bars_per_year`
  （`365×86400/interval_seconds`，crypto 7×24，**不是 252**）；无风险利率取 0 是显式选择并写明了它值多少
  （约 0.13 Sharpe）。
- ✓ `starquant_alpha/validation/metrics.py:15-22` —— 总收益走 `np.prod(1+r)-1`，不是 `cumsum`。
- ✓ `starquant_exchange/guard.py:16,25-40` —— mainnet 主机在本地被硬拒；`https` / 端口 / 路径 / URL 内凭据
  逐条检查。
- ✓ `starquant_live/lock.py` —— 账户级 flock + 账户级 kill switch 路径，解决了「七个 worktree 各有一个
  看不见的开关」。
- ✓ `starquant_exchange/binance_usdm/rest_client.py:110-121` —— 读重试 / 写歧义的划分正确
  （ConnectError/ConnectTimeout 未发出可重试；其余 TransportError 在 mutating 上抛 `OrderOutcomeUnknown`）。
- ✓ `starquant_live/execution.py:40-42` —— 先查后下，`clientOrderId` 按 bar 派生。
- ✓ `starquant_alpha/model.py:186-190` —— `FundingUnavailable` 本轮**在我手里真的抛出来了**
  （无资金费面板 + `crowding_window: 72`），KILL-027 的结构性关闭是活的，不是注释。
- ✓ `starquant_live/guards.py:78-83` 与 `starquant_alpha/backtest.py:335-339` —— 护栏语义只有一份
  （`clamp_book` / `hold_or_reduce`），实盘与回测重放调同一个函数、同一个顺序。
- ✓ `starquant_alpha/panel.py:55-73` —— 资金费按 bar 网格 floor 后求和（D-034），非 DatetimeIndex 直接拒绝。
- ✓ `starquant_alpha/panel.py:183-195` —— metrics / spot 不在 bar 索引上时**拒绝**而不是 reindex。
- ✓ 1h 存档的成员币里，**只有 5 个**有内部缺口（见上文），没有大面积空洞。

---

## 偏差影响（方向判断，非收益预测）

本轮**没有发现让回测虚高的新路径**。上面三条 🟠 里，两条（CI、state.json）不改变任何已发表的数字，
第三条（CPCV embargo）只影响四道硬门之一的**通过难度**，方向是「今天比应有的更容易通过」，
**幅度未测**，修法与测法都写在该条里了。

🟡 里唯一会动回测数字的是「参与率上限截断纯减仓」——修了之后回测与实盘都会**多拒绝一些减仓单**，
方向上让结果更差而不是更好。

---

## 第二遍 · 逻辑对抗审查（非代码证据）

> 本段不定位 `文件:行`（Ⅴ 类除外，那里有实现可指）。未获答复的一律标「待作者答复」。

### [🟠 高危·逻辑] 唯一的样本外证据链是单点故障，而它的断裂无法被事后发现

**维度**：Ⅴ.2 对账 / Ⅴ.4 复盘

**依据**：KILL-006 决定不做历史 holdout，全部理由是「实盘归因是唯一干净的样本外」；M-010 的 30 天窗口
是整条治理线在等的时钟（`config/alpha_registry.yaml:10-11`）。那条序列的连续性完全由
`state.json.last_income_ms` 决定，而 `state.py:73-76` 在解析失败时静默返回空对象，
`engine.py:1124` 于是从「现在」重新起算。

**失效场景**：若一次断电或一次手工编辑让 `state.json` 变成半截 JSON，下一次重启后
`attribution.jsonl` 会缺一段，`decay_watch` 读到的 `live_windows` 只是**变短**——
而「变短」和「本来就没跑那么久」在读数上完全一样。等到 M-010 满 30 天做采纳决定时，
没有任何东西能说出这 30 天里有没有缺口。

**缓解**：除上文的工程修法外，建议在 `attribution.jsonl` 里记 `since_ms` 与上一行 `until_ms` 的
衔接检查（已经两个字段都在写，只差一句比对），并在 `report daily` 的 evidence-window 一节里
报「窗口内的覆盖率」而不只是 `bars`。

---

### [🟡 中·逻辑] 退出通道在压力下与流动性同向收缩，三处叠加

**维度**：Ⅲ.2 单一事件 / Ⅴ.1 熔断

**依据**：三件事今天各自都是有意设计，方向相同——
(a) `rebalancer.py:154` 的参与率上限只豁免**全平**，纯减仓照常按 `2% × 近 24 根均量` 截断；
(b) `leverage.py:52` 的 `margin_buffer` 在保证金紧张时缩单（只缩加仓，这条没问题）；
(c) `engine.py:791` 订单串行下发，最后一单可能晚几十秒。

**失效场景**：若某个持仓币在一根 bar 内成交量掉到平时的 1/20（闪崩、交易所局部故障、
稳定币脱锚时的单边流动性），`cap` 同步掉到 1/20，模型想把 15% 的仓位降到 5% 的那一单会被截成
十几轮才走完；同一轮里 `daily_loss_pause` 已经把 `allow_increase` 关掉，所以不会加仓——
但**减仓也在被限速**。这与 D-004「护栏只保护实验有效性、从不加风险」的意图一致，与它的效果不一致。

**缓解**：`not closing` 改 `not reduce_only`（见第一遍）；并考虑给「减仓」单独一条更宽的参与率
（例如 4×）。回测侧同步改，否则两半又分叉。

---

### [🟡 中·逻辑] 构造层的搜索仍靠手工申报进入 DSR 的分母 —— 待作者答复

**维度**：Ⅱ 过拟合计费 / Ⅰ.1 假设

**依据**：D-039 明写「构造参数不进 `param_key`，按『手工补的坑』申报：时点新格子 14 个，
下次 `validate` 的 `--prior-trials` 30 → 44」。而 `starquant_governance/family_gate.py:110-137`
在重算 N 时只能移动**ledger 那一项**——`grid` 与 `declared` 是那次运行的属性，事后不可动。
也就是说：一次忘记申报的构造扫描，会让 N 永久偏小，而没有任何机器检查能发现。
`SignalSpec.selection` / `selection_bucket`（`signals/base.py:74-81`）已经为**信号自己的搜索**
解决了同一个问题（pairs 那次 `n_trials: 4` 对 19,578 个候选）。

**失效场景**：若 `no_trade_rel_band` / `vol_target` / `sleeve_max_gross` 这类扫描里有一次漏报，
D-028 的阈值就在一个偏小的 N 上计算，PASS 会比应有的容易——而这恰恰是 D-039 自己举报的
那种「证据分层」问题的量化版本。

**缓解 / 待答**：构造扫描能不能像 `SearchCensus` 一样落进 ledger（哪怕只是一个
`construction` 桶）？如果答案是「不行，因为构造扫描不产生 `param_key`」，
那么至少让 `validate` 在报告里记一个 `declared_construction_trials` 字段，
使「申报了多少」与「实际扫了多少」能被后来的人对上。

---

**风险评级**：🟡 中

（沿用 09-08 那份的量纲：策略工程侧没有新的致命项，本轮最重的问题在**支撑判断的机械**上，
而那些机械修起来不需要动任何一条实盘配置。）

**上实盘更大资金前，这一轮新增的三个必答问题**：

1. CPCV 在 embargo = 720 下，`fraction_negative` 与 `q05` 动不动？（这是唯一会改变已发表判定的一条。）
2. `state.json` 损坏后，怎么证明 M-010 的窗口没有缺口？
3. 构造层扫描的试验计数，谁来核？

---

## 工程与性能优化清单

> 与上面的缺陷清单分开：这一节里的每一条都**不改变任何数字**，只改变速度、可维护性或可观测性。
> 「实测」列的数字来自本会话，面板为 PIT 全量 **49,937 bar × 205 symbol**。

### 性能

| # | 位置 | 实测 | 优化 | 预期 |
|---|---|---|---|---|
| P1 | `starquant_alpha/overlays/exits.py:275-298` | **15.22 s / 遍**（1,020 万次 `exit_step`） | 把 symbol 维向量化：`direction` / `entry_price` / `extreme` / `unit` / `cooldown_until` 各存一个 numpy 数组，每根 bar 做一次逐元素运算。状态机本身逐 bar 串行，但跨 symbol 完全独立 | **20–50×**。默认 overlay 网格 11 格 ≈ 165 s 只花在这一个函数里；历史上扫过 194 个 exits 候选 |
| P2 | `starquant_live/reconciler.py:86-88` | 3 次顺序 REST | `asyncio.gather(account(), positions())`，`mark_prices` 依赖前者结果所以留在后面 | 每周期省 1 个 RTT；走代理时更明显 |
| P3 | `starquant_live/engine.py:791-820` | 串行下单 | 有并发上限的 `gather`，或 `/fapi/v1/batchOrders` | 缩短同一 bar 内首末单的时间差，**直接改善 M-Q08 的滑点读数** |
| P4 | `starquant_alpha/panel.py:147-210` | **2.9 s** 建面板 | `pd.concat` 改为先对齐到一个共同 `DatetimeIndex` 再 `np.column_stack`；或把 `Panel` 缓存到 parquet | 单次 validate 里建多次面板时才显著 |
| P5 | `starquant_alpha/portfolio.py:75-89` | **2.26 s**（49,937 根 × 205×205 外积） | 对角占优时可只维护 `w'Σw` 的递推而不是整个 Σ；或按 `max_weight` 非零列裁剪 | 2–5× |
| P6 | `starquant_data/store.py:53-67` | 每次 `append` 读回整份 parquet 再重写 | 按月分片（`1h/2026-09.parquet`），只重写最后一片 | `data sync` 的尾部追加从 O(总行数) 变 O(当月) |
| P7 | `starquant_alpha/signals/chanlun.py:250-320` | 5 币 0.58 s → 205 币 ≈ **24 s** | 上市前的全 NaN bar 目前也会各生成一个 `_Merged` 对象；从首个非 NaN bar 开始扫描 | 取决于上市时间分布，粗估 1.5–3× |

（核过但**不是**热点，不改：`features.true_range` 0.08 s——那个 `concat + groupby(level=1).max()`
的写法看着重，实测比手写 numpy 只慢 0.05 s，而它换来的列序正确性是 `breakout` 那次事故的修法，
**不要为了 50 毫秒把它改回去**。）

### 可维护性

| # | 内容 |
|---|---|
| M1 | 加 `requirements.lock`，CI 用它安装；validate 报告记 pandas / numpy 版本 |
| M2 | `ci.yml` 的 Tests 与 Types 互不阻塞（`if: always()`），或把 Tests 提前 |
| M3 | 加 `pytest-cov`（先只出报告，不设阈值） |
| M4 | `ports.py` 的 `SignalModel` / `TargetSet` 补齐 `entries` / `asset_vol` / `book_weights`，删掉三处 `getattr` |
| M5 | `reports.py` 拆成 `starquant_live/reports/` 包（各 M-0xx 指标已经是彼此独立的纯函数） |
| M6 | `research_cmd.py` 每个子命令一个模块，主文件只留 click 装配 |
| M7 | `parse_registry` 显式拒绝重复的 strategy id；`model.py:193` 改按 id 取 |
| M8 | `leverage.py:63` 的 `order.quantity * 0` 写成 `Decimal(0)` |
| M9 | `ARCHITECTURE.md:15` 的「限频」与代码对齐（见 🟡 那条） |

### 可观测性

| # | 内容 |
|---|---|
| O1 | `inputs.dropped` 非空时告警并计数（现在只写进 `cycles.jsonl` 没有读者） |
| O2 | 退避吞掉的 bar 写 `phase: SKIPPED, reason: BACKOFF` 并计入 `missed_rebalances` |
| O3 | `attribution.jsonl` 的 `since_ms` / `until_ms` 首尾衔接检查，进 `report daily` 的 evidence-window |
| O4 | `membership_summary` 增 `dead_slot_share`（本轮实测 0.30%） |
| O5 | `used_weight` 要么用起来，要么从架构文档里去掉 |

---

## 建议优先级

```
第 0 步   让 CI 变绿  —— 在此之前所有其它修复都没有机械背书
          （mypy 30 项；其中 3 项是真实契约漏洞，27 项是收窄规则变严）
第 1 步   加 lockfile  —— 否则下一次工具升级会以同样的方式再来一次
第 2 步   state.json 的三件事：load 区分损坏/不存在、_atomic_write 补 fsync、
          水位线丢失时告警
第 3 步   CPCV embargo 重测（预登记、 ledger +1）—— 唯一可能改变已发表判定的一条
第 4 步   exit_step 的 NaN 保护 + 属性测试；inputs.dropped 的读者；_paged 的翻页
第 5 步   参与率上限改 not reduce_only —— 这是行为变更，按 K-EX14 走窗口
第 6 步   P1（apply_exits 向量化）—— 单条收益最大的性能项
```

**第 0 步没做完之前，不建议采纳任何新的实盘配置**——不是因为代码有问题，
而是因为「改动被检查过」这句话现在还不成立。
