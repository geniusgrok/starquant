"""每条 `research` 子命令住自己的模块，而 `research_cmd` 只剩注册与地址。

本来叫「九个命令九个模块」。2026-09-17 加 `research forward`（Q-C 前向板）时这条测试红了——
它抓到的正是它该抓的，但「九」本来就不是不变量，住自己的模块才是。所以改了名：下一条命令
加进来时，该红的是「有没有自己的模块」，不是「是不是还九条」。

第一步（`test_the_panel_layer_kept_its_addresses.py`）搬的是 panel 层，接缝是量出来的：29 个
`scratchpad/` 脚本从 `research_cmd` 导入三个私有函数。这一步搬的是命令本身，接缝同样是量出来的——
43 个顶层 helper 里 **25 个只被一个命令用**，只有 10 个真正共享。所以共用件按**概念**落成五层
（panel / options / grids / report / ledger_io / book_eval），九个命令各自带走自己的那份。

这个文件守三件会静默坏掉的事：

**一、导入即注册。** 九个命令靠 `@research.command(...)` 在导入时挂上 click group。`starquant_cli/
__init__.py` 导入的是 `research_cmd`，所以 `research_cmd` 必须导入那九个模块。漏掉一个，
`starquant research --help` 就少一条命令，而没有任何别的测试会注意到。

**二、地址不变。** 35 个名字被 `scratchpad/` 与 tests 按 `from starquant_cli.research_cmd import ...`
写死。搬家不改别人的 import 行，所以这里断言每个名字都还在，**而且是同一个对象**——不是同名的
第二份拷贝。

**三、打补丁要打在读它的地方。** 这是这类拆分唯一会**静默**失效的地方：`monkeypatch.setattr(
research_cmd, name, ...)` 改的是再导出，而真正的调用点在另一个模块里，于是补丁一声不响地不生效、
测试照绿。本次拆分时三处测试正是这样暴露的（`ledger_redirection` / `cpcv_splits` /
`enumerate_candidates`），它们之所以响亮报错而不是静默通过，是因为 `research_cmd` 只再导出契约里的
名字，其余库名一个不留。下面那条测试把这个性质钉住。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from starquant_cli import research, research_cmd

ROOT = Path(__file__).resolve().parents[2]

#: 九条子命令，以及它现在住的模块。
COMMANDS = {
    "research_list": "research_list_cmd",
    "research_backtest": "research_backtest_cmd",
    "research_validate": "research_validate_cmd",
    "research_diagnose": "research_diagnose_cmd",
    "research_correlate": "research_correlate_cmd",
    "research_overlay": "research_overlay_cmd",
    "research_book": "research_book_cmd",
    "research_decompose": "research_decompose_cmd",
    "research_mine": "research_mine_cmd",
    # Q-SY1 (2026-09-18): the gate's power table, computable before a run so a pre-registration
    # can quote it.  Its own module because it shares nothing with `validate` except a renderer.
    "research_power": "research_power_cmd",
    # `forward` 是一个 group 不是命令：`add` 花钱、`status` 不花钱，做成同一条命令的两个开关
    # 迟早会有人读一次板就花掉一笔（见 `research_forward_cmd` 的模块 docstring）。
    "research_forward": "research_forward_cmd",
}

#: 共用件按概念分的五层（panel 层由第一步的测试守着）。
SHARED = (
    "research_options",
    "research_grids",
    "research_report",
    "research_ledger_io",
    "research_book_eval",
)


def _imported_from_research_cmd() -> dict[str, list[str]]:
    """`scratchpad/` 与 tests 今天实际写下的 `from starquant_cli.research_cmd import ...`。"""
    wanted: dict[str, list[str]] = {}
    for base in ("scratchpad", "tests"):
        for path in (ROOT / base).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # scratchpad 是记录，不保证今天还能解析
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "starquant_cli.research_cmd":
                    for alias in node.names:
                        wanted.setdefault(alias.name, []).append(str(path.relative_to(ROOT)))
    return wanted


def test_every_command_is_registered() -> None:
    """导入 `research_cmd` 必须让每条命令都挂到 group 上——少一条没有别的测试会发现。"""
    registered = set(research.commands)
    expected = {
        "list",
        "backtest",
        "validate",
        "diagnose",
        "correlate",
        "overlay",
        "book",
        "decompose",
        "mine",
        "power",
        "forward",
    }
    assert registered == expected, f"注册的命令与预期不符：多 {registered - expected}，少 {expected - registered}"


@pytest.mark.parametrize(("command", "module"), sorted(COMMANDS.items()))
def test_each_command_lives_in_its_own_module(command: str, module: str) -> None:
    """命令的定义在它自己的模块里，而 `research_cmd` 上那个名字是同一个对象。"""
    home = importlib.import_module(f"starquant_cli.{module}")
    assert hasattr(home, command), f"{command} 不在 {module} 里"
    assert getattr(research_cmd, command) is getattr(home, command), f"{command} 在两处不是同一个对象"


def test_research_cmd_defines_nothing_of_its_own() -> None:
    """主文件只剩注册与地址：再出现一个 `def`，就是这次拆分被悄悄撤回了一部分。"""
    body = (ROOT / "starquant_cli" / "research_cmd.py").read_text(encoding="utf-8")
    tree = ast.parse(body)
    defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert not defs, f"research_cmd.py 又有了自己的定义：{defs}"


def test_there_is_no_research_package_to_shadow_the_group() -> None:
    """平级模块不是风格选择：`research` 是 `starquant_cli/__init__.py` 里的 click group。

    建 `starquant_cli/research/` 包会遮住它。第一步就踩过，写在这里省得第二个人再踩。
    """
    assert not (ROOT / "starquant_cli" / "research").exists(), "`starquant_cli/research/` 会遮住 click group"


def test_every_address_callers_use_still_resolves() -> None:
    """35 个名字被脚本与测试写死。搬家不改别人的 import 行。"""
    missing = {name: users for name, users in _imported_from_research_cmd().items() if not hasattr(research_cmd, name)}
    assert not missing, f"这些地址断了：{missing}"


def test_the_addresses_are_the_same_object_not_a_second_copy() -> None:
    """同名不够——必须是同一个对象，否则两份拷贝会各自漂移。"""
    homes = [importlib.import_module(f"starquant_cli.{m}") for m in (*SHARED, *COMMANDS.values(), "research_panel")]
    checked = 0
    for name in _imported_from_research_cmd():
        here = getattr(research_cmd, name, None)
        for home in homes:
            if hasattr(home, name):
                assert here is getattr(home, name), f"{name}：`research_cmd` 上的不是 {home.__name__} 里那一个"
                checked += 1
                break
    assert checked >= 30, f"只核到 {checked} 个名字，契约不该缩到这么小"


def test_research_cmd_re_exports_only_the_contract_so_a_stale_patch_fails_loudly() -> None:
    """这条守的是唯一会**静默**坏掉的事。

    `monkeypatch.setattr(research_cmd, "cpcv_splits", ...)` 在拆分前有效，拆分后改的是再导出，
    而读它的代码在 `research_validate_cmd` 里——补丁不生效，测试却照样绿。让它响亮报错的唯一办法，
    是 `research_cmd` **不**顺带提供那些库名：`getattr` 直接 AttributeError。

    所以这里断言几个曾被 patch 过的库名确实不在 `research_cmd` 上。它们不在契约里（没有任何
    `from starquant_cli.research_cmd import` 写过它们），所以拿掉不欠谁。
    """
    for name in ("cpcv_splits", "enumerate_candidates", "ledger_redirection", "run_backtest", "pd", "np"):
        assert not hasattr(research_cmd, name), (
            f"`{name}` 又出现在 research_cmd 上了。它不在任何调用者的 import 行里，"
            "而它在这里会让一个打错地方的 monkeypatch 静默通过——那正是这次拆分最容易埋下的坑。"
        )
