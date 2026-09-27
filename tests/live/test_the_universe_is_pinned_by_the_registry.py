"""2026-09-09: the traded population is a decision, so it lives in the registry and moves by transaction.

Before this, `universe.json` was the decision and the loop rewrote it every day at about 01:00Z.  Every
cited report records the universe fingerprint it was produced under, so each daily re-rank made the
evidence stop describing the traded population and `registry_dataset_problems` refused the next armed
start.  Measured: restartability expired daily, and nothing anywhere said so until a canary triggered
it seven hours early on 2026-09-08.

So the re-rank keeps happening and keeps being recorded, and stops deciding - the same split the
governance plan applies to every other construction change, applied to the population.  What a batch
window acts on is the recorded proposal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from starquant_alpha.registry import parse_registry, registry_fingerprint
from starquant_live.config import resolve_universe
from starquant_live.engine import LiveEngine

PINNED = {
    "version": 1,
    "universe": ["btcusdt", "ETHUSDT"],
    "strategies": [{"id": "tsmom", "enabled": True, "params": {}}],
}
UNPINNED = {"version": 1, "strategies": [{"id": "tsmom", "enabled": True, "params": {}}]}


def test_a_pinned_universe_is_normalised_and_ordered_as_written() -> None:
    assert parse_registry(PINNED).universe == ("BTCUSDT", "ETHUSDT")
    assert parse_registry(UNPINNED).universe == ()


def test_the_registry_outranks_the_file_but_not_an_explicit_override(tmp_path: Any) -> None:
    """The file is an observation; the registry is a decision; `--symbols` is a person saying otherwise."""
    profile = {"universe": str(tmp_path / "absent.yaml")}
    pinned = parse_registry(PINNED)
    assert resolve_universe(profile, None, tmp_path, registry=pinned) == ["BTCUSDT", "ETHUSDT"]
    assert resolve_universe(profile, ["solusdt"], tmp_path, registry=pinned) == ["SOLUSDT"]


def test_an_unpinned_registry_changes_nothing(tmp_path: Any) -> None:
    """Every registry written before 2026-09-09 has to keep behaving exactly as it did."""
    profile = {"universe": str(tmp_path / "u.yaml")}
    (tmp_path / "u.yaml").write_text(yaml.safe_dump({"always_include": ["ADAUSDT"]}), encoding="utf-8")
    assert resolve_universe(profile, None, tmp_path, registry=parse_registry(UNPINNED)) == ["ADAUSDT"]
    assert resolve_universe(profile, None, tmp_path) == ["ADAUSDT"]


def test_pinning_a_universe_moves_the_registry_digest() -> None:
    """A pinned population that could be edited with no digest moving is one nobody can tell has moved.

    It is the REGISTRY fingerprint rather than the construction one on purpose: M-010's 30-day window
    keys on the construction, and re-ranking the pool must not silently restart the clock the whole
    governance line is waiting on.
    """
    assert (
        registry_fingerprint(parse_registry(PINNED))["digest"]
        != registry_fingerprint(parse_registry(UNPINNED))["digest"]
    )
    # ...and a registry that pins nothing must carry no such key at all.  Adding it unconditionally
    # moves the digest of every registry that pins nothing, and `live verify` would then report the
    # running loop as diverged from a file identical to the one it loaded.
    assert "universe" not in registry_fingerprint(parse_registry(UNPINNED))


@pytest.mark.parametrize("pinned", [True, False])
def test_the_engine_only_stops_adopting_when_the_registry_pins(pinned: bool) -> None:
    """`universe_pinned` follows the registry, so an unpinned deployment is untouched."""
    from starquant_live.config import live_config

    profile = yaml.safe_load(Path("config/live.demo.yaml").read_text(encoding="utf-8"))
    registry = parse_registry(PINNED if pinned else UNPINNED)
    config = live_config(profile, ["BTCUSDT"], registry, dry_run=True)
    assert config.universe_pinned is pinned


def test_the_digest_the_LOOP_reports_is_the_one_that_must_see_the_universe() -> None:
    """The near-miss worth pinning, because it cost a wrong statement to the operator.

    `registry_fingerprint` (what a research report records) and `registry_digest` (what the loop
    reports every cycle, and what `live verify` / M-Q10 compare) are two DIFFERENT payloads.  Putting
    the pinned universe only in the first would have left the running record unable to tell a loop
    holding one universe from a file naming another - which is KILL-Q15's exact shape, and the failure
    `registry_digest` exists for.

    Both conditional, both for the reason the `CONSTRUCTION_PAYLOAD_VERSION` apparatus exists one
    fingerprint over: adding the KEY unconditionally moves the digest of every registry that pins
    nothing.  The frozen hash is a SYNTHETIC unpinned registry, not the shipped one: keying it on the
    shipped file made an intentional `governance apply` fail a unit test, which teaches whoever hits it
    to update the constant reflexively - the exact reflex a frozen hash exists to prevent.  Whether the
    shipped file agrees with the running loop is a runtime fact, and `live status --check` compares
    them every inspection.
    """
    from starquant_live.composition import build_model
    from starquant_live.engine import registry_digest

    profile = yaml.safe_load(Path("config/live.demo.yaml").read_text(encoding="utf-8"))
    unpinned = registry_digest(build_model(parse_registry({**UNPINNED, "books": {}}), profile))
    pinned = registry_digest(build_model(parse_registry({**PINNED, "books": {}}), profile))

    assert unpinned == "d900d4c2ee3b", "the loop digest of a registry that pins NOTHING moved"
    assert pinned != unpinned, "pinning a universe must be visible in the digest the loop reports"


def test_a_pinned_universe_outranks_the_one_the_last_process_persisted(tmp_path: Any) -> None:
    """The defect that made the first `governance apply` of a pin inert (2026-09-09).

    `state.universe` held the last daily re-rank and won at startup, so pinning moved
    `registry_digest` without moving a single symbol the loop held.  Measured against the live state:
    the registry pinned 18 names, the process would have reported them, and it would have traded the
    persisted ones - a digest describing a universe nobody was trading, which is worse than no digest
    because it reads as agreement.
    """
    from starquant_live.state import LiveState, StateStore
    from tests.live.test_live_loop import _config, _model

    store = StateStore(tmp_path / "live")
    store.save(LiveState(cycles=7, universe=["BTCUSDT", "CYSUSDT"], universe_day="2026-09-08"))

    config = _config(tmp_path, universe=("BTCUSDT", "ETHUSDT"), universe_refresh=True, universe_pinned=True)
    engine = LiveEngine(config, model=_model(), market=None, venue=None, clock=None, store=store)

    assert engine.universe == ["BTCUSDT", "ETHUSDT"], "the pin lost to the persisted universe"
    assert engine.state.universe == ["BTCUSDT", "ETHUSDT"]
    # CYSUSDT may still hold a position; it leaves the way a re-rank's leavers do, not by being dropped
    assert engine.state.leaving == ["CYSUSDT"]


def test_an_unpinned_loop_still_prefers_what_it_persisted(tmp_path: Any) -> None:
    """The daily re-rank is the decision when nothing is pinned; that must not change."""
    from starquant_live.state import LiveState, StateStore
    from tests.live.test_live_loop import _config, _model

    store = StateStore(tmp_path / "live")
    store.save(LiveState(cycles=7, universe=["BTCUSDT", "CYSUSDT"], universe_day="2026-09-08"))

    config = _config(tmp_path, universe=("BTCUSDT", "ETHUSDT"), universe_refresh=True, universe_pinned=False)
    engine = LiveEngine(config, model=_model(), market=None, venue=None, clock=None, store=store)

    assert engine.universe == ["BTCUSDT", "CYSUSDT"]
    assert engine.state.leaving == []


@pytest.mark.parametrize(
    ("kwargs", "may"),
    [
        ({"dry_run": False, "paper": False, "state_dir": "", "registry_override": None}, True),
        ({"dry_run": False, "paper": True, "state_dir": "", "registry_override": None}, False),
        ({"dry_run": True, "paper": False, "state_dir": "", "registry_override": None}, False),
        ({"dry_run": False, "paper": True, "state_dir": "/tmp/canary", "registry_override": None}, False),
        ({"dry_run": False, "paper": True, "state_dir": "", "registry_override": "r.yaml"}, False),
    ],
)
def test_only_the_process_trading_the_account_may_rerank_the_shared_pool(kwargs: Any, may: bool) -> None:
    """The bare `--paper` row is the one that was missing, and it is how the wrong pin got proposed."""
    from starquant_cli.live_cmd import trades_the_account

    assert trades_the_account(**kwargs) is may
