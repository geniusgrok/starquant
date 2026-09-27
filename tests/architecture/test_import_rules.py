"""The only architecture rule: package dependency direction and import-time purity.

alpha      -> numpy, pandas, stdlib only (no starquant_* at all)
shared     -> stdlib + pyyaml
data       -> shared
exchange   -> shared
governance -> alpha, shared
live       -> alpha, data, exchange, governance, shared
cli        -> anything

`governance` sits above `alpha` and below `live` on purpose.  It reads what the validation pipeline
produced (verdicts, the selection gate, the trials ledger) to decide what may run, and R9 will have
the engine record its digest every cycle - so live must be free to import governance later without a
cycle.  It reads live artefacts as JSON off a path, never through `starquant_live`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    "starquant_shared",
    "starquant_data",
    "starquant_alpha",
    "starquant_exchange",
    "starquant_governance",
    "starquant_live",
    "starquant_cli",
)
ALLOWED_INTERNAL: dict[str, set[str]] = {
    "starquant_shared": set(),
    "starquant_alpha": set(),
    "starquant_data": {"starquant_shared"},
    "starquant_exchange": {"starquant_shared"},
    "starquant_governance": {"starquant_alpha", "starquant_shared"},
    "starquant_live": {
        "starquant_alpha",
        "starquant_data",
        "starquant_exchange",
        "starquant_governance",
        "starquant_shared",
    },
    "starquant_cli": set(PACKAGES),
}
ALLOWED_THIRD_PARTY: dict[str, set[str]] = {
    "starquant_shared": {"yaml"},
    "starquant_alpha": {"numpy", "pandas"},
    "starquant_data": {"numpy", "pandas", "pyarrow", "httpx", "yaml"},
    "starquant_exchange": {"httpx"},
    "starquant_governance": set(),
    "starquant_live": {"numpy", "pandas", "httpx", "yaml"},
    "starquant_cli": {"numpy", "pandas", "httpx", "yaml", "click"},
}
STDLIB = set(sys.stdlib_module_names)


def _source_files(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("package", PACKAGES)
def test_package_dependency_direction(package: str) -> None:
    files = _source_files(package)
    assert files, f"{package} has no source files"
    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imports(tree):
            if name == package or name in STDLIB:
                continue
            if name.startswith("starquant_"):
                if name not in ALLOWED_INTERNAL[package]:
                    violations.append(f"{path.relative_to(ROOT)} imports {name}")
            elif name not in ALLOWED_THIRD_PARTY[package]:
                violations.append(f"{path.relative_to(ROOT)} imports third-party {name}")
    assert not violations, "\n".join(violations)


_FORBIDDEN_TOP_LEVEL_CALLS = {"open", "print", "urlopen", "get", "post", "connect", "run", "load_yaml"}


@pytest.mark.parametrize("package", PACKAGES)
def test_no_import_time_side_effects(package: str) -> None:
    """Module top level may define things; it may not open files, sockets or run work."""
    offenders: list[str] = []
    for path in _source_files(package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            for call in (sub for sub in ast.walk(node) if isinstance(sub, ast.Call)):
                func = call.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if name in _FORBIDDEN_TOP_LEVEL_CALLS:
                    offenders.append(f"{path.relative_to(ROOT)}:{call.lineno} calls {name}() at import time")
    assert not offenders, "\n".join(offenders)


def test_no_dynamic_imports_in_alpha() -> None:
    """The alpha lab must be statically analysable; no importlib tricks."""
    for path in _source_files("starquant_alpha"):
        source = path.read_text(encoding="utf-8")
        assert "importlib" not in source and "__import__" not in source, path
