"""`reports.py` 只剩组装，读数按清单领域住进 `report_*` 模块，而调用方写死的地址一个不断。

2026-09-25 拆分。拆之前这一个文件 3,175 行，装着监控层的全部读数；09-23 那批并行合并的冲突集中在
它和 source budget 表上。拆分的依据是 09-23 的外部清单清点
（`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`）：衰减 #1.10、风控 #3、退出
#1.5 / #3.2、执行 #10、数据 #9、归因 #6.9 各一个模块，周报的治理读数一个，共用的读取与格式化一个。
拆的时候每个定义连同紧贴其上的注释块整段切走，一个字符不重打；拆前拆后在实盘状态快照上出 22 天
日报、4 份周报、2 份 beta 报告，81 个产物逐字节相同。

这个文件守四件会静默坏掉的事，写法照 M6（`test_each_research_command_has_its_own_module.py`）：

**一、地址不变。** 生产代码、tests 与 `scratchpad/` 按 `from starquant_live.reports import ...` 或
`reports.<名字>` 写死了五十多个名字。搬家不改别人的 import 行，所以每个名字都还要能取到，
**而且是同一个对象**，不是同名的第二份拷贝。

**二、打补丁要打在读它的地方。** 这类拆分唯一静默失效的地方：`monkeypatch.setattr(reports, name, ...)`
改的是再导出，读它的代码却在另一个模块里。拆分时 `beta_reading` 那一处正是这样暴露的；它响亮地
AttributeError 而不是静默通过，是因为 `reports` 不顺带提供库名。下面把这个性质钉住。

**三、`reports.py` 只剩组装。** 再出现一个组装之外的定义，就是有人把新读数放回了这里。

**四、各领域只依赖 `report_common`。** 领域之间互相 import，拆分换来的「改风控不碰衰减」就没了。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from starquant_live import reports

ROOT = Path(__file__).resolve().parents[2]

ASSEMBLY = {"daily_payload", "daily_alerts", "daily_markdown", "weekly_payload", "weekly_markdown"}

AREAS = (
    "report_decay",
    "report_risk",
    "report_exits",
    "report_execution",
    "report_data",
    "report_events",
    "report_beta",
    "report_governance",
)

#: 从来不是 `reports.py` 自己定义的名字，却有调用方从这个地址取。只留确实有人在用的。
HISTORICAL = {"window_sharpes": "tests/live/test_decay_detector.py"}


def _addresses_callers_use() -> dict[str, list[str]]:
    """今天实际写下的 `from starquant_live.reports import X` 与 `reports.X`。"""
    wanted: dict[str, list[str]] = {}
    for base in (
        "starquant_alpha",
        "starquant_cli",
        "starquant_data",
        "starquant_governance",
        "starquant_live",
        "tests",
        "scratchpad",
    ):
        for path in (ROOT / base).rglob("*.py"):
            if path == ROOT / "starquant_live" / "reports.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # scratchpad 是记录，不保证今天还能解析
                continue
            aliases: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "starquant_live.reports":
                    for alias in node.names:
                        wanted.setdefault(alias.name, []).append(str(path.relative_to(ROOT)))
                elif isinstance(node, ast.ImportFrom) and node.module == "starquant_live":
                    aliases.update(a.asname or a.name for a in node.names if a.name == "reports")
                elif isinstance(node, ast.Import):
                    aliases.update(a.asname or a.name for a in node.names if a.name == "starquant_live.reports")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                    if node.attr.startswith("__"):
                        continue  # `reports.__file__` is module machinery, not an address anyone relies on
                    wanted.setdefault(node.attr, []).append(str(path.relative_to(ROOT)))
    return wanted


def _reports_tree() -> ast.Module:
    return ast.parse((ROOT / "starquant_live" / "reports.py").read_text(encoding="utf-8"))


def test_every_address_callers_use_still_resolves() -> None:
    missing = {name: users for name, users in _addresses_callers_use().items() if not hasattr(reports, name)}
    assert not missing, f"这些地址断了：{missing}"


def test_the_addresses_are_the_same_object_not_a_second_copy() -> None:
    defined = {m: _defined_in(m) for m in ("report_common", *AREAS)}
    checked = 0
    for name in _addresses_callers_use():
        if name in ASSEMBLY or name in HISTORICAL:
            continue
        owners = [m for m, names in defined.items() if name in names]
        assert len(owners) == 1, f"{name} 应当恰好定义在一个 report_* 模块里，实际是 {owners}"
        home = importlib.import_module(f"starquant_live.{owners[0]}")
        assert getattr(reports, name) is getattr(home, name), f"{name}：`reports` 上的不是 {owners[0]} 里那一个"
        checked += 1
    assert checked >= 45, f"只核到 {checked} 个名字，契约不该缩到这么小"


def _defined_in(module: str) -> set[str]:
    """定义在这个模块里的名字，不含从别处 import 进来的。"""
    tree = ast.parse((ROOT / "starquant_live" / f"{module}.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_reports_py_holds_the_assembly_and_nothing_else() -> None:
    """新读数放进它所属领域的 `report_*` 模块。放回这里，拆分就被悄悄撤回了一部分。"""
    defined = set()
    for node in _reports_tree().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            # `__all__` declares what production code imports from here; it is not a reading.
            defined.update(t.id for t in targets if isinstance(t, ast.Name) and t.id != "__all__")
    assert defined == ASSEMBLY, (
        f"reports.py 多了 {sorted(defined - ASSEMBLY)}、少了 {sorted(ASSEMBLY - defined)}。"
        "读数按清单领域放进 report_decay / report_risk / report_exits / report_execution / report_data / "
        "report_beta / report_governance，共用的读取放 report_common；这里只组装。"
    )


def test_reports_re_exports_only_the_contract_so_a_stale_patch_fails_loudly() -> None:
    """从 `report_*` 以外 import 进来的名字，必须是组装自己在用的。

    顺带提供一个库名，就会让一个打在 `reports` 上的 monkeypatch 改到再导出、却碰不到真正调用它的
    读数——测试照绿，补丁没生效。唯一的例外是 `HISTORICAL` 里有调用方在用的那个。
    """
    tree = _reports_tree()
    used = {
        node.id
        for top in tree.body
        if isinstance(top, ast.FunctionDef)
        for node in ast.walk(top)
        if isinstance(node, ast.Name)
    }
    stray = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and not (node.module or "").startswith("starquant_live.report_"):
            for alias in node.names:
                bound = alias.asname or alias.name
                if node.module != "__future__" and bound not in used and bound not in HISTORICAL:
                    stray.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound not in used:
                    stray.append(alias.name)
    assert not stray, f"reports.py 顺带提供了组装不用的名字：{stray}"
    assert not hasattr(reports, "beta_reading"), "拆分前被 patch 过的库名又回到了 reports 上"


def test_each_area_leans_only_on_report_common() -> None:
    for module in ("report_common", *AREAS):
        tree = ast.parse((ROOT / "starquant_live" / f"{module}.py").read_text(encoding="utf-8"))
        leans = sorted(
            {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith(("starquant_live.report_", "starquant_live.reports"))
            }
        )
        allowed = [] if module == "report_common" else ["starquant_live.report_common"]
        assert set(leans) <= set(allowed), f"{module} 依赖了 {leans}：领域之间不互相 import，只依赖 report_common"
