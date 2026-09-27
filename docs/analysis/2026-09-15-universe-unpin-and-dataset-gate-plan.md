# 取消 universe 钉住 + 修数据集闸 —— 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让实盘交易池按每日 15/20 滞回规则正常进出并被循环采用，同时把数据集闸对 `universe_mode: "pit"` 报告的错误阻塞改对。

**Architecture:** 两处改动。① `starquant_data/manifest.py` 的 `_universe_drift_blocks` 对显式声明 `pit` 的报告豁免 universe 字段（pit 报告的总体是 `membership.parquet`，那一项已无条件阻塞），并由 `starquant_live/config.py` 的 `registry_dataset_problems` 把报告里的 `universe_mode` 接线传下去。② `config/alpha_registry.yaml` 的 `universe:` 清空，`universe_pinned` 转 False，`starquant_live/engine.py:1201-1215` 那条**早已存在**的采纳支恢复工作。没有新子系统，没有新模块。

**Tech Stack:** Python 3.12、pytest（`asyncio_mode = "auto"`）、pandas/parquet、PyYAML；实盘进程由 launchd 托管（`com.starquant.live`）。

**Spec:** [docs/analysis/2026-09-15-universe-unpin-and-dataset-gate-design.md](2026-09-15-universe-unpin-and-dataset-gate-design.md)

## Global Constraints

- **工作区**：全部改动在 worktree `~/starquant/worktrees/unpin-universe`（分支 `feat/unpin-universe-daily-rerank`）内完成。**不要 `cd` 回主 checkout**——launchd 跑的是主 checkout。
- **Python 解释器**：worktree 没有自己的 `.venv`。一律用
  `PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest ...`
  否则加载的是主 checkout 的代码，改动会像"没生效"。
- **不要在命令行再加 `-q`**：`pyproject.toml` 的 `addopts` 里已经有一个 `-q`，再加一个变成 `-qq`，会吞掉 `N passed` 那一行。
- **不要把 pytest 管进 `| tail` / `| head`**：报出来的 exit code 是管道末端那个命令的，不是 pytest 的。
- **不碰这些文件**：`.starquant/live/state.json`、`.starquant/live/cycles.jsonl`、`.starquant/data/universe.json`——它们是运行中的循环持有/追加的共享文件。
- **source budget ratchet 零 headroom**：七个包全部卡在 ceiling 上。任何 `starquant_*/**.py` 的净增行都会让 `tests/architecture/test_source_budget.py` 变红，必须在**同一提交**抬 `CEILING` 并写理由。测试文件不计入。
- **只对显式 `pit` 放行**：报告没有声明 `universe_mode` 时，闸的行为必须与今天**逐字节一致**。这是本次改动唯一的安全性质，Task 1 的第三条测试就是钉它的。
- **不动的参数**：`enter_rank: 15` / `exit_rank: 20` / `top_n: 15` / `min_age_days: 30` / `min_history_bars: 720` / `quarantine_after: 3` / `refresh: daily` / `no_trade_band: 0.005` / `no_trade_rel_band: 0.40` / `vol_target: 0.60`，以及 exit overlay 全部参数。

---

### Task 1: 闸的判据 —— pit 报告豁免 universe 字段

**Files:**
- Modify: `starquant_data/manifest.py:177-190`（`_universe_drift_blocks`）、`:223-244`（`manifest_check`）、`:265-267`（`manifest_problems`）
- Test: `tests/data/test_manifest.py`（在 `test_the_live_loops_own_universe_refresh_is_advisory_not_blocking` 之后追加）

**Interfaces:**
- Consumes: 无（本计划的第一个任务）
- Produces:
  - `_universe_drift_blocks(previous: dict[str, Any] | None, current: dict[str, Any] | None, universe_mode: str | None = None) -> bool`（模块私有，第三参数位置传入）
  - `manifest_check(recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None) -> ManifestCheck`
  - `manifest_problems(recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None) -> list[str]`
  - Task 2 只用 `manifest_check` 的关键字参数 `universe_mode`。

- [ ] **Step 1: 写四条失败测试**

追加到 `tests/data/test_manifest.py` 末尾（文件已 `import json`、`import pandas as pd`、并从 `starquant_data.manifest` 导入 `build_manifest, manifest_check`，无需新增 import）：

```python
def test_a_pit_report_does_not_block_on_the_universe_file(tmp_path: Path) -> None:
    """A ``universe_mode: "pit"`` result's population is ``membership.parquet``; it never opens this file.

    ``research_cmd._resolve_symbols`` takes the membership union under ``pit`` and calls
    ``read_universe`` only under ``static``.  So blocking a pit result here refuses an armed start over
    a file that result never read.  The 2026-09-09 workaround for that was to freeze the TRADED pool
    instead, which left the live universe at 16 names from 09-09 to 09-15 while the cited evidence
    re-ranked every 24 hours (``median_gap_hours: 24.0``, ``union: 211``, ``mean_size: 17.58``).
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root), universe_mode="pit")
    assert not check.blocking, "a pit result's population is the membership table, not this file"
    assert check.advisory and "universe.fingerprint" in check.advisory[0]


def test_a_static_report_still_blocks_on_the_universe_file(tmp_path: Path) -> None:
    """``universe.json`` IS a static result's population, so its drift stays the real thing."""
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root), universe_mode="static")
    assert check.blocking and "universe.fingerprint" in check.blocking[0]


def test_a_report_declaring_no_universe_mode_still_blocks(tmp_path: Path) -> None:
    """Only an explicit ``pit`` is exempt.  A report that did not say keeps the block it has.

    The opposite of the ``construction_problems`` precedent one field over, and deliberately so: that
    one skips a dimension a report predates, this one refuses to loosen an existing block because a
    report is silent.
    """
    root = _root(tmp_path, refreshes=30, freq="D")
    recorded = build_manifest(root).to_dict()
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )
    check = manifest_check(recorded, build_manifest(root))
    assert check.blocking and "universe.fingerprint" in check.blocking[0]


def test_a_pit_report_still_blocks_on_the_membership_table(tmp_path: Path) -> None:
    """The exemption moves ONE field.  A pit result's real gate is the table it actually ran on."""
    root = _root(tmp_path, refreshes=6, freq="MS")
    recorded = build_manifest(root).to_dict()
    index = pd.date_range("2024-01-01", periods=180, freq="D", tz="UTC")
    pd.DataFrame(True, index=index, columns=["BTCUSDT", "ETHUSDT"]).to_parquet(root / "membership.parquet")

    check = manifest_check(recorded, build_manifest(root), universe_mode="pit")
    assert check.blocking and "membership.refreshes: 6 -> 180" in check.blocking[0]
```

- [ ] **Step 2: 跑测试，确认前两条以 TypeError 失败**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/data/test_manifest.py -k "universe_mode or pit_report or static_report" -v
```

Expected: `test_a_pit_report_does_not_block_on_the_universe_file`、`test_a_static_report_still_blocks_on_the_universe_file`、`test_a_pit_report_still_blocks_on_the_membership_table` 三条 **FAIL**，错误是 `TypeError: manifest_check() got an unexpected keyword argument 'universe_mode'`。
`test_a_report_declaring_no_universe_mode_still_blocks` 这一条 **PASS**——它描述的是今天就有的行为，它在这里是为了在后面几步里保证那行为没被改掉。

- [ ] **Step 3: 改 `_universe_drift_blocks`**

`starquant_data/manifest.py`，把函数签名与文档补上第三参数，并在最前面加豁免分支（其余四行原样保留）：

```python
def _universe_drift_blocks(
    previous: dict[str, Any] | None, current: dict[str, Any] | None, universe_mode: str | None = None
) -> bool:
    """A changed symbol set blocks; a changed *selection mechanism* does not; a pit result is exempt.

    ``.starquant/data/universe.json`` is rewritten by the live loop's own universe refresh, so a
    ``pool-refresh -> live-refresh`` transition is the loop's bookkeeping and not evidence going stale.
    Measured 2026-09-04: tsmom's cited universe read ``pool-refresh``/15 against ``live-refresh``/16 on
    disk, so treating every universe move as drift would have the loop refuse to start because of
    something it did itself.  A symbol set that moves while the source holds still is the real thing -
    the book being traded is no longer the book the evidence describes.

    2026-09-15: ``universe_mode == "pit"`` exempts the field outright.  ``research_cmd._resolve_symbols``
    calls ``read_universe`` only under ``static``; a pit result's population is the union of
    ``membership.parquet``, which blocks unconditionally.  Blocking a pit result here refuses a start
    over a file it never opened - and the fix shipped for that on 2026-09-09 was to freeze the TRADED
    pool instead, which held the live universe at 16 names while the cited evidence re-ranked every 24
    hours.  Only an EXPLICIT ``pit`` is exempt: a report that declares no mode keeps its block.
    """
    if universe_mode == "pit":
        return False
    if previous is None or current is None:
        return True  # only reached when the two disagree, i.e. the block appeared or vanished
    if previous.get("source") != current.get("source"):
        return False
    return previous.get("fingerprint") != current.get("fingerprint")
```

- [ ] **Step 4: 改 `manifest_check` 的签名与调用点**

签名（`starquant_data/manifest.py:223`）：

```python
def manifest_check(
    recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None
) -> ManifestCheck:
```

调用点（原第 243 行那一句）：

```python
    if previous.universe != current.universe and _universe_drift_blocks(
        previous.universe, current.universe, universe_mode
    ):
        blocks = (*blocks, "universe")
```

- [ ] **Step 5: 改 `manifest_problems` 一并透传**

```python
def manifest_problems(
    recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None
) -> list[str]:
    """Every problem, blocking first.  Callers that act on severity want :func:`manifest_check`."""
    return manifest_check(recorded, current, universe_mode=universe_mode).problems
```

理由：两个入口判据不一致，正是这个仓库反复找到的那类缺陷（一个生产者一个消费者各自都对）。

- [ ] **Step 6: 跑本文件全部测试**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/data/test_manifest.py -v
```

Expected: 全部 PASS。特别确认既有的 `test_a_changed_symbol_set_under_the_same_source_blocks` 与
`test_the_live_loops_own_universe_refresh_is_advisory_not_blocking` 仍然 PASS——它们不传
`universe_mode`，走的正是"没声明就照旧"那条路。

- [ ] **Step 7: 提交**

```bash
git add starquant_data/manifest.py tests/data/test_manifest.py
git diff --cached --name-only
git commit -m "$(cat <<'EOF'
fix(gate): pit 报告的总体是 membership.parquet，不是 universe.json

research_cmd._resolve_symbols 只在 static 下读 universe.json；pit 下总体
是 membership.parquet 的并集，而 membership 已在 BLOCKING_FIELDS 里无条件
阻塞。所以对 pit 报告，universe 这道闸核的是一份该报告没打开过的文件。

只对显式 universe_mode: "pit" 豁免。没有声明的报告行为逐字节不变，
test_a_report_declaring_no_universe_mode_still_blocks 钉住这一条。

EOF
)"
```

提交前务必核对 `git diff --cached --name-only` 的输出确实是这两个文件——这个仓库出过新测试文件静默没进提交、CI 全绿却跑的是旧测试的事。

---

### Task 2: 接线 —— 启动闸把报告的 `universe_mode` 传下去

**Files:**
- Modify: `starquant_live/config.py:265-266`（`registry_dataset_problems` 循环体内）
- Test: `tests/live/test_dataset_gate.py`（修改 `_report` 辅助函数，并在文件末尾追加两条测试）

**Interfaces:**
- Consumes: Task 1 的 `manifest_check(..., *, universe_mode: str | None = None)`
- Produces: 无新签名。`registry_dataset_problems(registry, data_root=..., interval=...) -> ManifestCheck` 保持不变。

- [ ] **Step 1: 给测试辅助函数加一个参数**

`tests/live/test_dataset_gate.py` 里把现有的 `_report` 换成：

```python
def _report(
    tmp_path: Path, data_root: Path, *, with_manifest: bool = True, universe_mode: str | None = None
) -> Path:
    payload: dict[str, object] = {"kind": "validation", "verdict": "PASS"}
    if with_manifest:
        payload["dataset"] = build_manifest(data_root).to_dict()
    if universe_mode is not None:
        payload["universe_mode"] = universe_mode
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
```

默认值 `None` 表示"报告不声明"，既有调用点一个都不用改。

- [ ] **Step 2: 写两条失败测试**

追加到 `tests/live/test_dataset_gate.py` 末尾：

```python
def test_a_pit_report_is_not_blocked_by_the_universe_file_at_startup(tmp_path: Path) -> None:
    """The WIRING, not just the predicate: the gate has to read ``universe_mode`` off the report.

    A correct predicate nobody passes the mode to is this repository's most frequent defect - a
    producer and a consumer that are each right on their own.  So the join is tested, not assumed.
    """
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root, universe_mode="pit"))
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )

    check = registry_dataset_problems(registry, data_root=root)
    assert not check.blocking, "a pit result's population is the membership table, not this file"
    assert check.advisory and "universe.fingerprint" in check.advisory[0]


def test_a_static_report_is_still_blocked_by_the_universe_file_at_startup(tmp_path: Path) -> None:
    """The other half of the join: static keeps the block, so the exemption cannot be a blanket one."""
    root = _data_root(tmp_path)
    registry = _registry_citing(_report(tmp_path, root, universe_mode="static"))
    (root / "universe.json").write_text(
        json.dumps({"symbols": ["BTCUSDT", "SOLUSDT"], "source": "pool-refresh", "selected_at_ms": 2}),
        encoding="utf-8",
    )

    check = registry_dataset_problems(registry, data_root=root)
    assert check.blocking and check.blocking[0].startswith("tsmom: ")
    assert "universe.fingerprint" in check.blocking[0]
```

- [ ] **Step 3: 跑测试，确认第一条失败**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/live/test_dataset_gate.py -k "at_startup" -v
```

Expected: `test_a_pit_report_is_not_blocked_by_the_universe_file_at_startup` **FAIL**（`assert not check.blocking` 失败，因为 `universe_mode` 还没被传下去）；`test_a_static_report_is_still_blocked_by_the_universe_file_at_startup` PASS。

- [ ] **Step 4: 接线**

`starquant_live/config.py`，把 `registry_dataset_problems` 里读 `recorded` 的那两行换成：

```python
        recorded = payload.get("dataset") if isinstance(payload, dict) else None
        mode = payload.get("universe_mode") if isinstance(payload, dict) else None
        check = manifest_check(
            recorded if isinstance(recorded, dict) else None,
            current,
            # D-041 + 2026-09-15: the report says which population it ran on, and only a `pit` one is
            # exempt from the universe field.  Read here rather than inside `manifest_check` because
            # this is the only caller that holds the whole report payload.
            universe_mode=mode if isinstance(mode, str) else None,
        )
```

- [ ] **Step 5: 跑两个测试文件**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/live/test_dataset_gate.py tests/data/test_manifest.py -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 用真实的实盘证据实测一次**

这不是单元测试能替代的一步——真正要放行的是磁盘上那份报告。

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python - <<'PY'
import json
from starquant_data.manifest import build_manifest, manifest_check
report = json.load(open("~/starquant/reports/research/tsmom-validation-20260913T182325Z.json"))
cur = build_manifest("~/starquant/.starquant/data", "1h")
print("universe_mode:", report.get("universe_mode"))
chk = manifest_check(report.get("dataset"), cur, universe_mode=report.get("universe_mode"))
print("blocking:", chk.blocking)
print("advisory:", chk.advisory)
PY
```

Expected: `universe_mode: pit`，`blocking: []`。（`advisory` 里会有 `selected_at_ms` / klines / funding 的增长行，那些本来就是 advisory。）

- [ ] **Step 7: 提交**

```bash
git add starquant_live/config.py tests/live/test_dataset_gate.py
git diff --cached --name-only
git commit -m "$(cat <<'EOF'
fix(gate): 启动闸把报告的 universe_mode 传给 manifest_check

判据对了而没人把 mode 传下去，就是这个仓库最常见的那种缺陷：
一个生产者一个消费者各自都对。两条测试钉住 join 的两侧
（pit 放行 / static 仍阻塞），不是只测谓词。

EOF
)"
```

---

### Task 3: 抬 source budget ratchet

**Files:**
- Modify: `tests/architecture/test_source_budget.py` 的 `CEILING` 字典（约 `:1954`）

**Interfaces:**
- Consumes: Task 1、Task 2 落地后的 `starquant_data` / `starquant_live` 实际行数
- Produces: 无

- [ ] **Step 1: 跑 ratchet，看它红在哪**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/architecture/test_source_budget.py::test_no_package_grows_past_its_measured_ceiling -v
```

Expected: FAIL，报错里带 `{'starquant_data': (实测值, 5439), 'starquant_live': (实测值, 9438)}` 这样的字典。**把实测值抄下来**——下一步要用，不要凭增量心算。

- [ ] **Step 2: 量出准确数字**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("sb", "tests/architecture/test_source_budget.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for p in sorted(m.PACKAGES):
    print(f"{p:20s} {m._lines(p):6d} / {m.CEILING[p]:6d}   delta {m._lines(p)-m.CEILING[p]:+d}")
PY
```

- [ ] **Step 3: 在 `CEILING` 顶部插入条目，并把值改成实测值**

条目加在字典内**最上面**（紧接 "Thirty-first raise OF THIS TABLE" 那一段之前），把 `<N>` 换成上一步量到的增量：

```python
    # Thirty-second raise OF THIS TABLE, 2026-09-15: +<N> starquant_data, +<N> starquant_live - the dataset
    # gate stopped checking pit reports against a file they never open.
    #
    # `research_cmd._resolve_symbols` calls `read_universe` only under `static`; a `universe_mode: "pit"`
    # report's population is the union of `membership.parquet`, which blocks unconditionally one field
    # over.  So the universe block was refusing armed starts over `universe.json` for reports that never
    # read it - and the 2026-09-09 fix for THAT was to freeze the traded pool, which held the live
    # universe at 16 names from 09-09 to 09-15 while the cited evidence re-ranked every 24 hours
    # (`median_gap_hours: 24.0`, `union: 211`).  The pin is being removed in the same branch.
    #
    # Most of the added lines are the two docstrings: the exemption is a one-line predicate, and what
    # costs lines is writing down WHY only an explicit `pit` is exempt.  That paragraph is the thing a
    # future reader needs, because the obvious "simplification" - exempt anything that is not `static` -
    # would silently loosen the gate for every report written before `universe_mode` was recorded.
    #
    # Design: docs/analysis/2026-09-15-universe-unpin-and-dataset-gate-design.md
```

然后把 `CEILING` 里 `starquant_data` 与 `starquant_live` 的值改成 Step 2 量到的实测行数。**只改这两个**——其余五个包本次未动，改它们等于白送 headroom。

- [ ] **Step 4: 跑 ratchet 确认转绿**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/architecture/test_source_budget.py -v
```

Expected: 全部 PASS（含 `test_the_plans_budget_is_recorded_as_breached_rather_than_quietly_redefined`）。

- [ ] **Step 5: 提交**

```bash
git add tests/architecture/test_source_budget.py
git diff --cached --name-only
git commit -m "$(cat <<'EOF'
test(budget): 第三十二次抬表——pit 报告豁免 universe 闸的两段理由

增行主要是两处 docstring。豁免本身是一行谓词，花行数的是写清楚
"为什么只有显式 pit 豁免"——因为那个显而易见的"简化"（凡不是
static 就豁免）会悄悄放松所有在 universe_mode 被记录之前写的报告。

EOF
)"
```

---

### Task 4: 取消 registry 的 universe 钉住

**Files:**
- Modify: `config/alpha_registry.yaml:48-64`（`universe:` 列表）与其上方的注释块

**Interfaces:**
- Consumes: 无（与 Task 1-3 正交，但按顺序放在后面，这样"闸已修对"先于"池子开始动"）
- Produces: `parse_registry(...).universe == ()` → `live_config(...).universe_pinned is False`

- [ ] **Step 1: 确认三种写法都解析为未钉住（一次性核实，不是新测试）**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -c "
from starquant_alpha.registry import parse_registry
base = {'version': 1, 'strategies': [{'id': 'tsmom', 'enabled': True, 'params': {}}]}
print('omitted:', parse_registry(base).universe)
print('empty  :', parse_registry({**base, 'universe': []}).universe)
"
```

Expected: 两行都是 `()`。采用 `universe: []` 而不是删掉这个键——键留着，上方那段注释块（TRUMPUSDT / ENAUSDT 两次移除的审计线）才有依附的地方。

- [ ] **Step 2: 把 16 个条目换成空列表**

`config/alpha_registry.yaml`，把

```yaml
universe:
  - BTCUSDT
  - ETHUSDT
  - SOLUSDT
  - ZECUSDT
  - XRPUSDT
  - HYPEUSDT
  - DOGEUSDT
  - BNBUSDT
  - TUTUSDT
  - 1000PEPEUSDT
  - SUIUSDT
  - AKEUSDT
  - UNIUSDT
  - LINKUSDT
  - ADAUSDT
  - CYSUSDT
```

换成

```yaml
universe: []
```

- [ ] **Step 3: 在注释块末尾追写取消的理由**

紧接在现有注释块最后一行（`# 这条移除要到下次重启才生效。`）之后、`universe: []` 之前插入：

```yaml
# 2026-09-15（操作者裁定）：钉住取消，`universe: []`。上面整段保留不删——那是 TRUMPUSDT 与
# ENAUSDT 两次移除的审计线，且它记录的机制仍然成立，只是不再被使用。
#
# 取消的理由不是"钉住太麻烦"，是钉住偏离了证据。循环引用的那份报告
# （reports/research/tsmom-validation-20260913T182325Z.json，verdict PASS）记着
# `universe_mode: "pit"`，其 dataset.membership 是 refreshes 2042 / median_gap_hours 24.0 /
# mean_size 17.58 / union 211：**让这本书上线的回测交易的就是一个每 24 小时按同一条 15/20
# 滞回重排的池子**，五年里进出过 211 个币，从来不是一份冻结的名单。所以冻结的 16 币池子才是
# 证据没有描述过的那本书，而且漂移单调变大——2026-09-15T01:00Z 的重排提案与实持已差 7 个名字。
#
# 钉住当初要挡的那件事（每日重排改写 universe.json → 数据集闸阻塞 → 可干净重启每天到期）是
# 真的，但处置选错了层：`research_cmd._resolve_symbols` 只在 static 下读 universe.json，pit
# 报告的总体是 membership.parquet（那一项无条件阻塞）。该冻的是闸的判据，不是交易池。闸已在
# 同一分支改对。
#
# TRUMPUSDT / ENAUSDT 会随第一次重排回来，操作者裁定不加排除：它们"永久占名额"的性质本身是
# 钉住造成的，池子每天换手时低权重的币会随排名自然出池。可证伪判据：若任一标的连续 5 天记
# BAND_BLOCKS_ENTRY 且没被重排踢出池子，这条说法即被证伪，届时重议。
#
# 生效同样要重启——引擎只在启动时建模。取消后 registry_digest 不再含 universe 键（条件化的），
# 所以 digest 会变一次；重启后心跳应读到新值。
# 设计：docs/analysis/2026-09-15-universe-unpin-and-dataset-gate-design.md
```

- [ ] **Step 4: 确认 `universe_pinned` 已关，且既有测试仍绿**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -c "
import yaml
from starquant_alpha.registry import parse_registry, registry_fingerprint
from starquant_live.config import live_config
reg = parse_registry(yaml.safe_load(open('config/alpha_registry.yaml')))
profile = yaml.safe_load(open('config/live.demo.yaml'))
print('registry.universe:', reg.universe)
print('universe_pinned  :', live_config(profile, ['BTCUSDT'], reg, dry_run=True).universe_pinned)
print('fingerprint has universe key:', 'universe' in registry_fingerprint(reg))
"
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest tests/live/test_the_universe_is_pinned_by_the_registry.py -v
```

Expected: `registry.universe: ()`、`universe_pinned: False`、`fingerprint has universe key: False`；测试文件全部 PASS。

该文件里的 `test_the_engine_only_stops_adopting_when_the_registry_pins`（parametrize True/False）与
`test_pinning_a_universe_moves_the_registry_digest` **已经覆盖了设计文档 §4 的第 6 条**，不要再写重复的新测试。

- [ ] **Step 5: 提交**

```bash
git add config/alpha_registry.yaml
git diff --cached --name-only
git commit -m "$(cat <<'EOF'
feat(universe): 取消钉住，每日 15/20 重排恢复被采纳

引用中的证据是 universe_mode: "pit"——membership 2042 次重排、
median_gap 24h、mean_size 17.58、union 211。让这本书上线的回测交易的
就是一个每天重排的池子，所以冻结的 16 币名单才是偏离证据的那一侧。

钉住要挡的"可干净重启每天到期"是真问题，但该冻的是闸的判据不是交易池；
闸已在本分支改对。注释块整段保留，那是 TRUMP/ENA 两次移除的审计线。

生效要重启：引擎只在启动时建模。

EOF
)"
```

---

### Task 5: 全量验收，然后停下来交给操作者

**Files:** 无改动。

**Interfaces:**
- Consumes: Task 1-4 全部提交
- Produces: 一份可供操作者裁定的验收读数

- [ ] **Step 1: 跑全量测试**

```bash
PYTHONPATH=~/starquant/worktrees/unpin-universe ~/starquant/.venv/bin/python -m pytest -m "not network"
```

Expected: 全绿，最后一行形如 `NNNN passed, NN deselected in XXs`。**这一行必须真的出现在输出里**——没有它就不算跑过，不要凭"没看到报错"下结论。

- [ ] **Step 2: 确认 lint / 类型**

```bash
cd ~/starquant/worktrees/unpin-universe && ~/starquant/.venv/bin/ruff check . && ~/starquant/.venv/bin/ruff format --check . && ~/starquant/.venv/bin/mypy starquant_data starquant_live
```

Expected: 三条都通过。

- [ ] **Step 3: 把四次提交整理成一份交接读数**

```bash
git log --oneline main..feat/unpin-universe-daily-rerank
git diff main...feat/unpin-universe-daily-rerank --stat
```

- [ ] **Step 4: 停下。合入与重启是操作者的决定**

**不要自行合入 main，不要自行重启实盘循环。** 向操作者报告以下四项，由他裁定：

1. 全量测试与 lint 的实际输出行；
2. `git diff --stat` 的改动面（应只有 `starquant_data/manifest.py`、`starquant_live/config.py`、`config/alpha_registry.yaml`、三个测试文件、两份 docs）；
3. 真实证据的闸读数（Task 2 Step 6 那次实测，`blocking: []`）；
4. **重启的时机与后果**：重启命令是

   ```bash
   launchctl kickstart -k gui/$(id -u)/com.starquant.live
   ```

   重启是幂等的（clientOrderId 按 bar 派生，先查后下）。重启后 `state.universe_day` 仍是重启当天，
   所以**当天不会再重排**；第一次采纳在下一个 UTC 日约 01:00Z。按 2026-09-15T01:00Z 那份提案估
   首日换手约占毛敞口 12.5%（出 TUTUSDT −713 U、CYSUSDT −570 U、AKEUSDT ≈146 U）加进场侧，
   合计约 25% 毛换手、7 bps 下成本约 2 U；**TUTUSDT 与 CYSUSDT 是这本书仅有的两个空头，出池
   即平掉，书会变成纯多**。09-16 的提案会重算，名单不一定相同。

- [ ] **Step 5: 重启后的核对清单（操作者同意重启后才执行）**

```bash
cd ~/starquant && .venv/bin/starquant live status --check
```

逐项确认：

- `heartbeat.registry` 是**新的** digest（不再是 `1db80a06f281`），且 `live status --check` 报
  "registry：与正在运行的循环一致"；
- `heartbeat.phase` 为 `OK`，`universe_size` 仍是 16（当天不重排，这是对的）；
- 启动没有被数据集闸拒绝（进程起来了就说明没有）。

第二天 01:00Z 之后再看一次：`cycles.jsonl` 最新一条的 `universe_update` 应当是
`"adopted": true` 且带 `entered` / `left`，而不是 `"adopted": false`。

---

## 自审

**Spec 覆盖：** 设计文档 §2.1 → Task 1 + Task 2；§2.2 → Task 4；§2.3（TRUMP/ENA 裁定与可证伪判据）→ Task 4 Step 3 的注释；§3（不改什么）→ Global Constraints 的最后一条；§4 测试 1-5 → Task 1 Step 1 四条 + 既有的 source 错配测试保持不变（Task 1 Step 6 显式核对），测试 6 → 已有覆盖（Task 4 Step 4 注明不要重复写），测试 7 → Task 2 Step 2；§5 → Task 3；§6 → Task 5；§7 回滚 → 见下。

**回滚：** 闸的改动可独立回滚（`git revert` 前两个提交），它只放松 pit 报告的一个判据，不影响交易。钉住要回滚，是把 `universe:` 填回**当时 `.starquant/live/state.json` 里循环持有的那套**（读 state.json，**不读** universe.json——后者是观察，且不止一个进程在写它；2026-09-09 第一次钉住就是因为读错文件而钉了一个循环从未持有的币），然后重启。

**类型一致性：** `universe_mode` 在三处签名里统一为 `str | None`，在 `manifest_check` / `manifest_problems` 上是关键字参数，在 `_universe_drift_blocks` 上是第三位置参数（模块私有，与既有两参数的调用形态一致）。
