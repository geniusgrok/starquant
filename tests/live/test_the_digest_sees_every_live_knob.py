"""The general form of KILL-Q15, mechanised: change a registry leaf, and ask whether a digest moves.

`registry_digest` exists because the loop builds its model once at startup, so an edit to the file
changes what the registry SAYS without changing what the loop TRADES.  `live status --check` compares
the recorded digest against the file's, which closes that gap only for the leaves the digest actually
covers.  On 2026-09-09 the probe stop turned out not to be one of them: the shipped registry, the same
registry with tsmom's stop deleted, and the same registry with `max_loss` tightened sixty-fold gave
identical digests in all three hashers, so a book's halt threshold could be changed and the check would
keep reporting "与正在运行的循环一致".

Reading the hasher does not find that; mutating the file does.  So this walks every leaf of the shipped
registry, changes it, and asserts a digest moves - except for the leaves named below, each of which has
to say why it is exempt.  A count would pass as the exempt set grew, so the set is named.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from starquant_alpha.registry import parse_registry
from starquant_live.composition import build_model
from starquant_live.engine import registry_digest
from starquant_shared.config import load_yaml

PROFILE = load_yaml("config/live.demo.yaml")
PAYLOAD = load_yaml(PROFILE["registry"])

# Leaves whose change may leave `registry_digest` alone, and the reason each one may.
EXEMPT: dict[str, str] = {
    "version": "a label on the file, not an input to the model",
    # Evidence pointers: deliberately outside the digest.  Swapping a pointer for re-derived evidence of
    # the SAME construction must not fork the loop or reset M-010's clock (the 2026-09-08 precedent);
    # what guards them instead is the startup gate, which verifies the sha256 before the loop trades.
    "strategies/0/evidence/report": "evidence pointer - held by the startup gate, not the digest",
    "strategies/0/evidence/sha256": "evidence pointer - held by the startup gate, not the digest",
    "strategies/0/evidence/verdict": "evidence pointer - held by the startup gate, not the digest",
    "strategies/5/evidence/report": "evidence pointer - held by the startup gate, not the digest",
    "strategies/5/evidence/sha256": "evidence pointer - held by the startup gate, not the digest",
    "strategies/5/evidence/verdict": "evidence pointer - held by the startup gate, not the digest",
    # Prose.  `ProbeParams` builds the digest's probe payload from the fields the loop ACTS on, and a
    # sentence explaining who accepted a sleeve is not one of them.
    "strategies/0/probe/accepted_by": "prose; the loop acts on `stop` and `accepted_on`, not on this",
    "strategies/0/probe/reason": "prose",
    "strategies/5/probe/accepted_by": "prose",
    "strategies/5/probe/accepted_despite": "prose (D-029's written acknowledgement; the startup gate reads it)",
    "strategies/5/probe/reason": "prose",
    # `ensemble.turnover_penalty` is implemented by nothing, and `parse_registry` now refuses any value
    # but 0.  It stays parseable at 0 so archived `registry_fingerprint`s still reproduce.
    "ensemble/turnover_penalty": "unimplemented; `parse_registry` refuses a non-zero value",
}


def _leaves(node: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        return [item for key, value in node.items() for item in _leaves(value, (*prefix, key))]
    if isinstance(node, list):
        return [item for i, value in enumerate(node) for item in _leaves(value, (*prefix, i))]
    return [("/".join(str(p) for p in prefix), node)]


def _with(path: str, value: Any) -> dict[str, Any]:
    payload = copy.deepcopy(PAYLOAD)
    node: Any = payload
    keys = [int(k) if k.isdigit() else k for k in path.split("/")]
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return payload


def _digest(payload: dict[str, Any]) -> str:
    return registry_digest(build_model(parse_registry(payload), PROFILE))


def _enabled_indices() -> set[int]:
    return {i for i, entry in enumerate(PAYLOAD["strategies"]) if entry.get("enabled")}


def _mutation(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value * 3 + 7
    if isinstance(value, str):
        return value + "_MUTATED"
    return None


def test_every_live_leaf_of_the_shipped_registry_moves_the_digest() -> None:
    base = _digest(copy.deepcopy(PAYLOAD))
    enabled = _enabled_indices()
    blind: dict[str, str] = {}
    checked = 0
    for path, value in _leaves(PAYLOAD):
        if path in EXEMPT:
            continue
        keys = path.split("/")
        # A disabled strategy's parameters are not what the loop trades, so the digest is right to
        # ignore them.  `enabled` itself is NOT skipped - flipping one on has to move the digest.
        if keys[0] == "strategies" and keys[1].isdigit() and int(keys[1]) not in enabled and keys[-1] != "enabled":
            continue
        mutated = _mutation(value)
        if mutated is None:
            continue
        checked += 1
        try:
            moved = _digest(_with(path, mutated)) != base
        except ValueError:
            continue  # the parser refuses the value: a validated field is guarded, just not by the digest
        if not moved:
            blind[path] = f"{value!r} -> {mutated!r} left the digest at {base}"
    assert checked > 20, f"the sweep only exercised {checked} leaves; it is not covering the file"
    assert not blind, (
        "these registry leaves change what the loop does and no digest sees it, which is exactly the "
        f"gap `live status --check` is supposed to close: {blind}"
    )


def test_the_stop_threshold_is_one_of_the_leaves_this_covers() -> None:
    """The finding that produced this file, kept as its own case so the sweep cannot silently stop covering it."""
    base = _digest(copy.deepcopy(PAYLOAD))
    tightened = copy.deepcopy(PAYLOAD)
    tightened["strategies"][0]["probe"]["stop"]["max_loss"] = 0.001
    assert _digest(tightened) != base
    without = copy.deepcopy(PAYLOAD)
    del without["strategies"][0]["probe"]["stop"]
    assert _digest(without) != base
    halting = copy.deepcopy(PAYLOAD)
    halting["strategies"][0]["probe"]["stop"]["halts"] = True
    assert _digest(halting) != base


@pytest.mark.parametrize("path", sorted(EXEMPT))
def test_every_exemption_names_a_leaf_that_exists_and_says_why(path: str) -> None:
    assert EXEMPT[path].strip(), f"{path} is exempt with no reason"
    assert path in {p for p, _ in _leaves(PAYLOAD)}, f"{path} is exempt and no longer in the registry"
