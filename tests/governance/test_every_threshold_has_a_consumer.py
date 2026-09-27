"""The general form of the defect this repository found five times on 2026-09-09.

Each one was the same shape: a rule written down, versioned, hashed into a digest, recorded every
cycle - and consulted by nothing.  The shared universe, the shared metrics file, the inert registry
pin, DL-K3's string compare, the probe stop that was in no digest, and then `Policy.throttle_scalar`
and `drawdown_grace_cycles` with no caller anywhere in the tree.

`policy_digest()` hashes every field of `Policy`, which is a promise: change one and the change is
visible in the record.  For a field nothing reads, that promise is worse than absent - the digest
moves, the operator sees a rule version bump, and the machine's behaviour is identical.  A threshold
that looks live and is dead.

So: every field of `Policy` must be reachable from production code, either by name or through a method
of `Policy` that production calls.  Making a field unreachable is still allowed - the fix is to delete
it, because a constant nothing reads belongs in prose, not in a hashed policy.
"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from starquant_governance.policy import Policy

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = ROOT / "starquant_governance" / "policy.py"
PACKAGES = (
    "starquant_alpha",
    "starquant_cli",
    "starquant_data",
    "starquant_exchange",
    "starquant_governance",
    "starquant_live",
    "starquant_shared",
)

# `version` is the label on the rest, and `digest()` is what reads it.
EXEMPT: dict[str, str] = {
    "version": "the label the digest carries; `digest()` hashes it and `governance status` prints it",
}


def _methods_reading(field: str) -> set[str]:
    """Methods of `Policy` that mention `self.<field>` - the indirect way a field stays live."""
    tree = ast.parse(POLICY_FILE.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Policy":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            for inner in ast.walk(item):
                if (
                    isinstance(inner, ast.Attribute)
                    and inner.attr == field
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "self"
                ):
                    out.add(item.name)
    return out


def _production_sources() -> list[str]:
    out = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts or path == POLICY_FILE:
                continue
            out.append(path.read_text(encoding="utf-8"))
    return out


def test_no_policy_field_is_a_constant_nobody_reads() -> None:
    sources = _production_sources()
    dead: dict[str, str] = {}
    for field in fields(Policy):
        name = field.name
        if name in EXEMPT:
            continue
        names = {name, *(f"{method}(" for method in _methods_reading(name))}
        if not any(any(needle in source for needle in names) for source in sources):
            dead[name] = f"no production reader; searched for {sorted(names)}"
    assert not dead, (
        "these policy fields are hashed into `policy_digest()` and consulted by nothing, so changing "
        f"one moves the digest and changes no behaviour: {dead}.  Wire it or delete it."
    )


def test_the_exemptions_are_named_rather_than_counted() -> None:
    """A count would pass as new exemptions were added; the names have to be argued for one at a time."""
    assert set(EXEMPT) == {"version"}, f"the exemption list changed: {sorted(EXEMPT)}"
    assert all(reason.strip() for reason in EXEMPT.values())


def test_the_guard_itself_can_fail() -> None:
    """A guard that cannot go red is the thing it is guarding against.  This is its own negative control."""
    sources = ["nothing here mentions any policy field at all"]
    assert not any("windows_to_main" in source for source in sources)
    assert _methods_reading("drawdown_ladder") == {"throttle_scalar"}, (
        "the indirect path this test relies on - a field read only inside a Policy method - moved"
    )
