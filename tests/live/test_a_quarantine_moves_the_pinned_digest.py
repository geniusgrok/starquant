"""D-031 under a pinned universe: the one path that could shrink the traded set behind the digest.

Found on 2026-09-09 by the sweep in `test_the_digest_sees_every_live_knob.py` - not by that test, but
by the question it asks, pointed at the profile instead of the registry.  `pool.quarantine_after` is a
live knob outside `construction_fingerprint`, which led to reading what it does: `_quarantine` removed
a symbol from `self.universe` and left `self.model` alone, so `registry_digest` - which reads the
model's pinned universe - stayed byte-identical while the loop traded 17 of 18 symbols.  Measured, not
reasoned: the same digest `abe21f7a8edf` before and after.

The pin, shipped the same day, is what made this matter.  Before it the digest carried no universe at
all; after it the digest's claim is "this is the population this process manages", and D-031 was the
one path that could falsify that claim silently.  Under a pin it also does not heal: the daily re-rank
records a proposal and adopts nothing, so a quarantined symbol stays gone until a restart.
"""

from __future__ import annotations

from typing import Any

from starquant_alpha.registry import parse_registry
from starquant_live.composition import build_model
from starquant_live.engine import LiveEngine, registry_digest
from starquant_live.state import LiveState
from starquant_shared.config import load_yaml

PROFILE = load_yaml("config/live.demo.yaml")
SHIPPED = load_yaml(PROFILE["registry"])

# The population is this file's own, not the shipped registry's (2026-09-15).  It used to read
# `SHIPPED["universe"]`, so emptying that key - an operator decision about which symbols to trade -
# made two of these tests fail and the other two pass VACUOUSLY: `"CYSUSDT" not in engine.universe`
# and `hit == []` are both trivially true against an empty pool, so they would have stayed green
# while testing nothing.  The sibling file `test_the_universe_is_pinned_by_the_registry.py` already
# records this lesson for its frozen digest ("a SYNTHETIC unpinned registry, not the shipped one");
# this file had not caught up.  What is under test is D-031's behaviour under A pin, not WHICH
# symbols the operator pins today.
SYMBOLS = ("BTCUSDT", "ETHUSDT", "CYSUSDT")


def _registry(*, pinned: bool) -> Any:
    return parse_registry({**SHIPPED, "universe": list(SYMBOLS) if pinned else []})


class _Alerts:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


def _report(symbol: str, status: str) -> Any:
    return type("R", (), {"order": type("O", (), {"symbol": symbol})(), "status": status})()


def _engine(*, pinned: bool, after: int = 1) -> LiveEngine:
    engine = LiveEngine.__new__(LiveEngine)
    engine.config = type("C", (), {"quarantine_after": after, "universe_pinned": pinned})()
    engine.state = LiveState()
    engine.universe = list(SYMBOLS)
    engine.model = build_model(_registry(pinned=pinned), PROFILE)
    engine.alerts = _Alerts()
    return engine


async def test_a_quarantined_symbol_moves_the_digest_it_used_to_leave_alone() -> None:
    engine = _engine(pinned=True)
    before = registry_digest(engine.model)
    assert "CYSUSDT" in engine.model.universe

    hit = await LiveEngine._quarantine(engine, [_report("CYSUSDT", "REJECTED"), _report("BTCUSDT", "FILLED")])

    assert hit == ["CYSUSDT"]
    assert "CYSUSDT" not in engine.universe, "the loop stopped trading it"
    assert "CYSUSDT" not in engine.model.universe, "and the model has to say so"
    assert registry_digest(engine.model) != before, (
        "the digest's claim is what this process manages; a quarantine that leaves it identical is "
        "KILL-Q15 with the pin's own name on it"
    )
    assert engine.state.leaving == ["CYSUSDT"], "it leaves reduce-only, it is not simply forgotten"


async def test_the_operator_is_told_that_a_pinned_symbol_does_not_come_back() -> None:
    engine = _engine(pinned=True)
    await LiveEngine._quarantine(engine, [_report("CYSUSDT", "REJECTED"), _report("BTCUSDT", "FILLED")])
    assert engine.alerts.sent, "a machine departing from a governed decision cannot do it quietly"
    message = engine.alerts.sent[0]
    assert "不重启就不会回来" in message and "CYSUSDT" in message


async def test_an_unpinned_universe_keeps_the_old_shape() -> None:
    """Without a pin the daily re-rank can put the symbol back, so this is a normal rotation, not a divergence."""
    engine = _engine(pinned=False)
    assert "CYSUSDT" in engine.universe, "an empty pool would make every assertion below vacuous"
    await LiveEngine._quarantine(engine, [_report("CYSUSDT", "REJECTED"), _report("BTCUSDT", "FILLED")])
    assert "CYSUSDT" not in engine.universe
    assert engine.alerts.sent == []


async def test_an_account_wide_rejection_still_cannot_empty_the_pool() -> None:
    """D-031's own guard, re-asserted here because this file now also decides what the digest says."""
    engine = _engine(pinned=True)
    before = registry_digest(engine.model)
    assert "CYSUSDT" in engine.universe, "an empty pool would make `hit == []` vacuous"
    hit = await LiveEngine._quarantine(engine, [_report("CYSUSDT", "REJECTED"), _report("BTCUSDT", "REJECTED")])
    assert hit == [], "every order rejected proves nothing about any one symbol"
    assert registry_digest(engine.model) == before
    assert engine.alerts.sent == []
