# 取消 universe 钉住，让每日重排重新被采纳；并把数据集闸的 universe 判据改对

日期：2026-09-15
分支：`feat/unpin-universe-daily-rerank`
操作者裁定：**方案 B**（取消钉住 + 修闸）；TRUMPUSDT / ENAUSDT **让它们回来，不加排除**

---

## 1. 为什么要改

### 1.1 触发

实盘持仓停在 16 个标的。TRUMPUSDT（2026-09-13T22:00Z 生效）与 ENAUSDT（2026-09-14T20:00Z 生效）两次按操作者指示移出后，**没有任何新标的进来**，而且在当前配置下**永远不会**。

原因不是缺陷：`config/alpha_registry.yaml` 的 `universe:` 非空 → `universe_pinned=True`
（`starquant_live/config.py:142`）→ `starquant_live/engine.py:1187` 那一支把每日重排的结果记成
`adopted: false` 后丢弃。池子在钉住下**只出不进**。

自 2026-09-09 钉住起，`cycles.jsonl` 里 universe 只变过两次，两次都是减：

| 生效周期 | 变化 | registry digest |
|---|---|---|
| 2026-09-13T22:00Z | −TRUMPUSDT | `9e1bf73c3691` |
| 2026-09-14T20:00Z | −ENAUSDT | `1db80a06f281` |

### 1.2 决定性的事实：引用中的证据本身就是每天重排的

循环此刻引用的 `reports/research/tsmom-validation-20260913T182325Z.json`（verdict PASS）记着：

```
universe_mode: "pit"
dataset.membership.median_gap_hours: 24.0
dataset.membership.refreshes: 2042
dataset.membership.mean_size: 17.58
dataset.membership.union: 211
symbols: 205
```

**让这本书上线的那个回测，交易的是一个每 24 小时按同一条 15/20 滞回规则重排的池子**，平均
17.58 个成员，五年样本里进出过 211 个币。它从来没有交易过一个冻结的名单。

所以钉住不是"保守版的证据"——**钉住是偏离证据的那一侧**，而且随时间单调变大。截至
2026-09-15T01:00Z 的重排提案与实持名单已差 7 个名字（剔掉操作者自己移除的两个，真实漂移
5/16）：

- 想进：NEARUSDT（自 09-12 连续 4 天）、LSKUSDT（09-15 新进）
- 想出：CYSUSDT（自 09-10）、TUTUSDT（自 09-11）、AKEUSDT（09-15 新增）

### 1.3 钉住当初为什么存在，以及那个理由为什么不成立

钉住是 2026-09-09「选 3」的产物（`docs/RESEARCH_LOG.md` 同日条目）。它要解决的问题是：
循环每天 01:00Z 重排会改写 `.starquant/data/universe.json`，而每份引用的证据都记着它被产出时的
universe 指纹，于是 `registry_dataset_problems` 阻塞，`live run --armed` **每天到期一次**。

这个问题是真的。但**处置选错了层**：被冻的应该是闸的判据，不是交易池。理由见 §2.1。

---

## 2. 改什么

### 2.1 改动 A — 数据集闸：pit 报告不看 universe.json

**判据（可从代码证明，非偏好）。** `starquant_cli/research_cmd.py:187-199` 把两种报告的总体来源
写得很死：

```python
def _resolve_symbols(root, symbols, interval, universe_mode="static"):
    if symbols:
        return [...]
    if universe_mode == "pit":
        table = _membership_table(root)          # ← 总体来自 membership.parquet
        union = [str(s) for s in table.columns[table.any(axis=0)]]
        ...
        return [s for s in union if s in stored]
    universe = read_universe(root)               # ← static 的总体就是 universe.json
    return universe or KlineStore(root).symbols(interval)
```

- **`universe_mode: "static"`** —— universe.json 的名单**就是**该报告的总体。那个文件漂移 =
  报告在描述另一本书 → 阻塞**是对的**，不动。
- **`universe_mode: "pit"`** —— 该报告**从不读 universe.json**；总体来自 `membership.parquet`，
  而 `membership` 已经在 `BLOCKING_FIELDS` 里**无条件阻塞**（`starquant_data/manifest.py:32`）。

结论：对 pit 报告，现在这道 universe 闸核的是**一个该报告没有读过的文件**。它拦下的不是证据
陈旧，是循环自己的簿记。

**改法。** `starquant_data/manifest.py`：

```python
def _universe_drift_blocks(previous, current, universe_mode=None) -> bool:
    if universe_mode == "pit":
        return False    # 这份报告的总体是 membership.parquet，那一项无条件阻塞
    ...                 # 其余判据原样保留（含 source 错配豁免）
```

`manifest_check(recorded, current, *, universe_mode: str | None = None)`；
`starquant_live/config.py` 的 `registry_dataset_problems` 把 `payload.get("universe_mode")` 传下去
——它手里已经有整份报告 payload（`starquant_live/config.py:262-266`）。

同文件的便利函数 `manifest_problems`（`starquant_data/manifest.py:266-267`）也转调 `manifest_check`，
新参数一并透传，避免两个入口判据不一致。

**安全性质：没有声明 `universe_mode` 的报告照旧阻塞。** 只对明说 `pit` 的放行，绝不因为"报告
没说"而放松。这条与 `construction_problems` 跳过未记录 `portfolio` 块的先例方向相反，是故意
的：那条是"新增维度不拦住在飞的东西"，这条是"不因缺失而放松既有的拦截"。

**为什么不靠现状活着。** 实测当前读数：

| | count | fingerprint | source |
|---|---|---|---|
| 证据记的 | 17 | `98651738a4fd6e8a` | `pool-refresh` |
| 磁盘现在 | 17 | `98651738a4fd6e8a` | `pool-refresh` |

`blocking: []`。而循环自己重排写的是 `source: "live-refresh"`（`starquant_live/config.py:173`），
与证据的 `pool-refresh` 不同源，按现判据**不阻塞**。也就是说取消钉住后的第一次重排本来就拦不住
启动——但那是**靠 source 错配**活着。只要下一次 `validate` 恰好在 `live-refresh` 状态下跑，证据
就记 `live-refresh`，此后两边同源，每天 01:00Z 都会让下一次 armed 启动被拒。修闸买的是"理由
是对的"，不是"这一次能过"。

### 2.2 改动 B — 取消钉住

`config/alpha_registry.yaml`：`universe:` 清空 → `universe_pinned=False` →
`starquant_live/engine.py:1201-1215` 的采纳支恢复：

- `self.universe = fresh`，`state.universe` 跟着更新
- 出池的进 `state.leaving` → 走 reduce-only 平掉（D-014）——**但不是无条件的，见下面副作用第 4 条**
- 进池的自动 `_ensure_leverage`，当周期即进 `managed_symbols()` 参与模型
- `universe_sink` 写回 `universe.json`（`source: "live-refresh"`）
- 发一条换手告警

注释块**保留** TRUMPUSDT / ENAUSDT 两次移除的完整记录（那是审计线），在其后追写取消钉住的
理由与本文件的指针。

**副作用（已知、可接受）：**

1. `registry_digest` 里的 `universe` 键是条件化的（`starquant_live/engine.py:2007-2020`），不钉即
   消失。digest 会变一次，重启后心跳应读到新值。代价是 `live status --check` 不再核对"循环在
   交易哪些币"——但它也不再**声称**，所以不是假话。
2. 被 quarantine 的币会在下一次重排回来。这**不是回归**：`starquant_live/engine.py:1064` 的文档
   明写 "Recovery is the pool's decision alone: a quarantined symbol returns only when the daily
   refresh selects it again."，钉住才是打断这条恢复路径的东西（`engine.py:1090` 的告警正是为此
   而写）。`reject_streak` 在隔离时被清空，所以回来的币要重新累计 `quarantine_after: 3` 次拒单
   才会再被隔离——震荡有界。
   **更正（2026-09-15 终审）：原句写的是"震荡有界，且每次都告警"，后半句是错的。**
   `engine.py:1090` 那条告警整段在 `if self.config.universe_pinned:` 里面，取消钉住后
   `universe_pinned` 为 False，隔离事件**不再发告警**，只剩 `logger.warning` 一行。同时
   `model.universe` 变空后 `AlphaModel.without_symbols`（`starquant_alpha/model.py:121`）成为
   no-op，`registry_digest` 也不再随隔离移动——后者在本文件副作用第 1 条里已被当作"不再声称
   所以不是假话"接受，但两件事合起来意味着隔离此后**既不告警也不动 digest**。剩下的可观测
   路径是 `cycles.jsonl` 的 `quarantined` 字段与 `starquant report daily` 的 `pool_quarantined`。
   不在本次一并修：把告警提出 `if` 之外要新增中文文案行，会再动零 headroom 的 `starquant_live` ceiling，
   且要过 `test_alerts_are_chinese`，不该搭这趟车。
3. 中途进池的币要等下次重启才过启动过滤（`docs/RESEARCH_LOG.md:2359` 记的既有残余，本次不
   引入也不修复）。
4. **出池不等于一定平得掉。** `rebalancer.py:39` 的 `exempt_crossings` 默认 `False`，且
   `config/live.demo.yaml` 没有设过这个键。出池标的目标被压 0 后 `same_direction_resize` 为
   False，相对带宽不适用，阈值停在 `no_trade_band * equity` = 0.5% 权益（当前约 54 U）。所以
   **持仓名义小于约 54 U 的出池标的会记 `BAND_BLOCKS_EXIT`，留在 `leaving` 里每周期被扫描却
   永不平掉**。这不是本次引入的（`rebalancer.py` 自己的注释就记着 ENAUSDT 2026-09-14T11:00Z
   起 −11.19 U 对 54.32 U 带宽的实例），但取消钉住把它从"操作者手工移除时偶发"变成"每日重排
   都可能发生"——低权重名字正是既容易被排名换掉、又容易把持仓衰减到带宽以下的那一类。
   **这是 §2.3 那条 `BAND_BLOCKS_ENTRY` 判据的出口侧孪生**，所以给它一条对称的可证伪判据：
   若某标的出池后连续 5 天记 `BAND_BLOCKS_EXIT` 仍未平掉，带宽的两侧就都需要重议。
   §6 的首日估算不受影响：TUTUSDT 713 U / CYSUSDT 570 U / AKEUSDT ≈146 U 都远高于 54 U，
   "书会变成纯多"那句仍然成立。

### 2.3 TRUMPUSDT / ENAUSDT（操作者已裁定：让它们回来）

两个币当初被移除，是因为模型目标缩到权益的 0.044% / 0.016%，撞不动 `no_trade_band: 0.005`
（0.5% 权益），于是每周期记 `BAND_BLOCKS_ENTRY`：占名额、永远建不了仓。

**那个"永久占名额"的性质本身是钉住造成的。** 池子每天重排时名额一直在换手，低权重的币会随
排名自然出池；只有在冻结的名单里，一个建不了仓的币才会无限期占着一个 slot。

裁定：**不加排除**，让它们随重排回来。

**可证伪判据（写下来，到期再议）：** 若任一标的连续 **5 天**记 `BAND_BLOCKS_ENTRY` 且没有被
重排踢出池子，则"重排会自然换掉低权重名额"这条说法被证伪，届时回到下面两条被否的路：

- 写进 `config/universe.yaml` 的 `exclude:` —— 手工黑名单，目标变大也不会自己回来；且回测的
  总体里没有这两个洞，本身又是一道偏离证据的口子。
- 让首次建仓豁免带宽 —— 这是 construction 改动（动 `no_trade_band` 的语义），会移
  `construction_fingerprint`、需要自己的回测证据，不该搭这趟车。

---

## 3. 不改什么（划界）

| 项 | 取值 | 状态 |
|---|---|---|
| 滞回 | `enter_rank: 15` / `exit_rank: 20` | 不动 |
| 池子规模 | `top_n: 15` | 不动 |
| 上市年龄 | `min_age_days: 30` | 不动 |
| 模型历史门槛 | `min_history_bars: 720` | 不动 |
| 隔离阈值 | `quarantine_after: 3` | 不动 |
| 刷新节奏 | `refresh: daily` | 不动 |
| `membership` 闸 | 无条件阻塞 | 不动 |
| static 报告的 universe 闸 | 阻塞 | 不动 |
| exit overlay / 带宽 / `vol_target` | —— | 不动 |
| `.starquant/live/state.json` | —— | **不碰**（共享文件，循环在内存里持有它） |

新币进场仍有两道过滤把着：池子侧 `min_age_days: 30`（30 根日线才可排名），模型侧
`min_history_bars: 720`（30 天小时线才可交易）。

---

## 4. 测试（TDD，先红后绿）

`tests/data/test_manifest.py`：

1. pit 报告 + universe 指纹同源变动 → 落在 `advisory`，不在 `blocking`
2. static 报告 + 同样变动 → 仍在 `blocking`
3. **无 `universe_mode`** 的报告 + 同样变动 → 仍在 `blocking`
4. pit 报告 + `membership` 变动 → 仍在 `blocking`（pit 报告真正的那道闸还在）
5. 既有的 `pool-refresh → live-refresh` source 错配豁免 → 行为不变

`tests/live/test_the_universe_is_pinned_by_the_registry.py`（或同级新文件）：

6. registry 无 `universe` → `universe_pinned is False`，且 `registry_digest` 的 payload 不含
   `universe` 键
7. `registry_dataset_problems` 把报告的 `universe_mode` 传到了 `manifest_check`（接线本身钉住，
   否则改对了判据却没接上）

---

## 5. source budget ratchet

实测（2026-09-15，`tests/architecture/test_source_budget.py`）**七个包全部零 headroom**：

```
starquant_alpha        9011 / 9011    starquant_live        9438 / 9438
starquant_cli          6178 / 6178    starquant_data        5439 / 5439
starquant_exchange      714 /  714    starquant_governance  3940 / 3940
starquant_shared        289 /  289
```

改动落在 `starquant_data/manifest.py` 与 `starquant_live/config.py`，必然触顶。`CEILING` 在**同一提交**
抬高，理由写进条目（本文件的指针 + 行数增量）。测试文件不计入。

---

## 6. 落地顺序

1. 在 worktree `feat/unpin-universe-daily-rerank` 里写测试（红）→ 改 `manifest.py` / `config.py`
   （绿）→ 抬 `CEILING` → 全量测试
2. 改 `config/alpha_registry.yaml`（清空 `universe:`，追写理由）
3. 合入 main
4. **重启循环**——引擎只在启动时建模，改 registry 不等于改循环
5. 重启后核对：`live status --check` 的 `registry` 与心跳一致，`universe_pinned` 已关

### 首次采纳的时间与规模

`state.universe_day` 已是 `2026-09-15`，所以**今天不会再重排**；第一次采纳在 **2026-09-16 约
01:00Z**。

按 2026-09-15T01:00Z 那份提案估首日换手（09-16 会重算，名单不一定相同）：

| 动作 | 标的 | 当前名义 |
|---|---|---|
| 出 | TUTUSDT | −713 U |
| 出 | CYSUSDT | −570 U |
| 出 | AKEUSDT | ≈146 U（13:00Z 减仓后） |
| 进 | TRUMPUSDT / ENAUSDT / NEARUSDT / LSKUSDT | 由 inverse-vol 预算决定 |

出池侧约 1,429 U，占毛敞口 11,395 U 的 12.5%；加进场侧，合计约 25% 毛换手。按成本模型 7 bps
约 2 U，**钱上可忽略**。

**要点名的一条：TUTUSDT 与 CYSUSDT 是这本书仅有的两个空头，出池即平掉，书会变成纯多。**

---

## 7. 回滚

任何一步出问题，回滚都是把 `config/alpha_registry.yaml` 的 `universe:` 填回当时 `state.json`
里循环持有的那套（**读 state.json，不读 universe.json**——后者是观察，且不止一个进程在写它；
2026-09-09 第一次钉住就是因为读错文件而钉了一个循环从未持有的币），然后重启。

闸的改动可独立回滚：它只放松 pit 报告的一个判据，回滚不影响交易。
