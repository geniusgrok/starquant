"""The exemption must keep describing the world, and must expire with the bridge it belongs to.

An exemption that outlives its reason is worse than no exemption: it reads like a considered decision
while doing nothing but hiding a string nobody has checked in months.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from starquant_live.composition import load_registry
from starquant_live.config import registry_evidence_problems
from starquant_shared.config import load_yaml
from tests.shipped_evidence import EXEMPT_UNTIL, EXEMPTED, unexempted

ROOT = Path(__file__).resolve().parents[1]


def test_every_exempted_problem_is_one_the_shipped_pair_actually_has() -> None:
    """No hiding a string the gate does not produce.

    The failure this catches: the pointer moves back to something that clears, the exemption is
    forgotten, and the next real FAIL is silently covered by a line left over from today.
    """
    if date.today() >= EXEMPT_UNTIL:
        pytest.skip("the bridge has expired; `unexempted` is the identity function and exempts nothing")
    problems = registry_evidence_problems(
        load_registry(ROOT / "config" / "alpha_registry.yaml"),
        load_yaml(ROOT / "config" / "live.demo.yaml"),
    )
    for exempted in EXEMPTED:
        assert exempted in problems, (
            f"{exempted!r} is exempted but the shipped pair does not produce it - "
            "delete the exemption instead of carrying a line that hides nothing"
        )


def test_the_exemption_expires_with_the_bridge_it_belongs_to() -> None:
    """`EXEMPT_UNTIL` and `run_live.sh`'s `BRIDGE_UNTIL` are the same date, checked rather than promised.

    They are two files in two languages and the date is written twice.  This is the thing that keeps
    the copies together - without it, moving one is a silent way to arm the loop while the test suite
    still pretends the gate holds, or the reverse.
    """
    script = (ROOT / "deploy" / "run_live.sh").read_text(encoding="utf-8")
    match = re.search(r'^BRIDGE_UNTIL="(\d{4}-\d{2}-\d{2})"', script, re.MULTILINE)
    assert match, "run_live.sh no longer declares BRIDGE_UNTIL where this test can read it"
    assert date.fromisoformat(match.group(1)) == EXEMPT_UNTIL


def test_the_exemption_hides_one_string_and_not_a_shape() -> None:
    """Anything else the gate says still comes through, including another strategy's FAIL."""
    other = "flow: evidence verdict FAIL does not allow live use"
    drift = "tsmom: registry params differ from the cited evidence (entry_threshold: ...)"
    assert unexempted([*EXEMPTED, other, drift]) == [other, drift]
