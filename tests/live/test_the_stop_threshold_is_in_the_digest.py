"""2026-09-09: the number that STOPS A BOOK was in no digest at all.

Measured before the fix - the shipped registry, the same registry with tsmom's stop deleted, and the
same registry with `max_loss` tightened sixty-fold produced three IDENTICAL digests, in all three
places that hash a registry: `registry_digest` (what the loop reports every cycle), the construction
fingerprint, and `registry_fingerprint` (what a research report records).

So a probe's stop could be relaxed, tightened until it fired daily, or removed outright, and
`live status --check` would keep saying "registry：与正在运行的循环一致".  That is KILL-Q15's shape
on a risk control, and worse than on the universe: the universe decides WHAT is traded, this decides
whether a book gets halted at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from starquant_alpha.registry import parse_registry
from starquant_live.composition import build_model
from starquant_live.config import load_profile
from starquant_live.engine import registry_digest

SHIPPED = Path("config/alpha_registry.yaml")


def _digest(payload: dict[str, Any]) -> str:
    return registry_digest(build_model(parse_registry(payload), load_profile("config/live.demo.yaml")))


def _shipped() -> dict[str, Any]:
    return yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))


def _tsmom(payload: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in payload["strategies"] if s["id"] == "tsmom")


@pytest.mark.parametrize(
    ("what", "mutate"),
    [
        ("the stop is deleted", lambda e: e.pop("probe", None)),
        ("max_loss tightened 60x", lambda e: e["probe"]["stop"].__setitem__("max_loss", 0.001)),
        ("the window moves", lambda e: e["probe"]["stop"].__setitem__("window_days", 7)),
        ("it becomes a HALT", lambda e: e["probe"]["stop"].__setitem__("halts", True)),
        ("the window's start moves", lambda e: e["probe"].__setitem__("accepted_on", "2026-01-01")),
    ],
)
def test_every_change_to_the_stop_rule_moves_the_digest_the_loop_reports(what: str, mutate: Any) -> None:
    before = _digest(_shipped())
    payload = _shipped()
    mutate(_tsmom(payload))
    assert _digest(payload) != before, f"{what} left the running record unable to tell"


def test_prose_beside_the_rule_does_not_move_it() -> None:
    """The digest covers what the loop ACTS on.  A digest that moved when someone improved a comment
    would be one people learn to ignore, which is how a frozen hash stops working."""
    before = _digest(_shipped())
    payload = _shipped()
    entry = _tsmom(payload)
    entry["probe"]["reason"] = "rewritten prose that changes nothing the loop does"
    entry["probe"]["accepted_by"] = "somebody else"
    assert _digest(payload) == before


def test_a_registry_that_declares_no_probe_keeps_the_digest_it_had() -> None:
    """Conditional for the reason the pinned universe is: adding the key unconditionally would move
    the digest of every registry that declares no probe, and `live verify` would then report a
    running loop as diverged from the file it loaded."""
    unprobed = {"version": 1, "strategies": [{"id": "tsmom", "enabled": True, "params": {}}], "books": {}}
    assert _digest(unprobed) == "d900d4c2ee3b"


def test_the_shipped_registry_still_declares_the_main_book_stop() -> None:
    entry = _tsmom(_shipped())
    assert entry["probe"]["stop"]["max_loss"] == 0.06
    assert entry["probe"]["stop"]["halts"] is False


def test_removing_one_probe_of_two_is_visible() -> None:
    """The flow probe's stop is the one that can actually halt a book; deleting it must be loud."""
    before = _digest(_shipped())
    payload = _shipped()
    flow = next(s for s in payload["strategies"] if s["id"] == "flow")
    flow.pop("probe", None)
    assert _digest(payload) != before


def test_the_construction_fingerprint_is_deliberately_not_where_this_lives() -> None:
    """M-010's 30-day window keys on the construction, and a stop rule is not the construction.

    Putting it there would reset the evidence clock the whole governance line waits on every time a
    threshold was reviewed - which is the same reason the pinned universe is not there either.
    """
    from starquant_live.config import live_config, resolve_universe
    from starquant_live.engine import construction_fingerprint

    profile = load_profile("config/live.demo.yaml")
    payload = _shipped()
    _tsmom(payload)["probe"]["stop"]["max_loss"] = 0.001
    digests = []
    for candidate in (_shipped(), payload):
        registry = parse_registry(candidate)
        cfg = live_config(
            profile, resolve_universe(profile, None, ".starquant/data", registry=registry), registry, dry_run=True
        )
        digests.append(construction_fingerprint(cfg)["digest"])
    assert digests[0] == digests[1], "a stop review must not reset M-010"
