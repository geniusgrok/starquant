"""DL-G5 / DRILL-G4: six deployment-health checks, and the boundary the Phase 7 review drew.

The review's sharpest correction (KILL-AR-04) was that calling the canary a filter would do two kinds
of harm: let a bad candidate through on a technicality, and let a good one be blocked by an unrelated
venue hiccup - then be recorded as evidence against the candidate.  So the first test here is the
negative one: a shadow that is perfectly healthy and perfectly unprofitable must pass.

Every rate is measured against the ARMED loop's own cycles over the same window.  A constant would
fail the whole canary on a day the venue was slow, which is the false negative that teaches an
operator to ignore an instrument.
"""

from __future__ import annotations

from typing import Any

from starquant_governance.canary import SOAK_CYCLES, evaluate


def _cycles(
    n: int, *, construction: str = "aaa", guards: int = 0, phase: str | None = None, universe: tuple[str, ...] = ("A",)
) -> list[dict[str, Any]]:
    rows = []
    for i in range(n):
        row: dict[str, Any] = {
            "at": f"2026-01-01T{i:02d}:00:00+00:00",
            "construction": construction,
            "guard_reasons": ["MAX_GROSS"] if i < guards else [],
            "universe": list(universe),
            "targets": dict.fromkeys(universe, 0.1),
            "skipped": [],
        }
        if phase:
            row["phase"] = phase
        rows.append(row)
    return rows


def test_a_healthy_and_unprofitable_shadow_passes() -> None:
    """KILL-AR-04.  Nothing here reads P&L, and a canary that did would be an alpha filter."""
    shadow = _cycles(SOAK_CYCLES)
    for row in shadow:
        row["equity"] = 100.0 - row["at"].count("0")  # losing money, healthily
    assert evaluate(shadow, _cycles(SOAK_CYCLES)).healthy


def test_an_unfinished_soak_is_not_a_pass() -> None:
    result = evaluate(_cycles(SOAK_CYCLES - 1), _cycles(SOAK_CYCLES))
    assert not result.healthy
    assert [c.name for c in result.failures] == ["soak"]


def test_drill_g4_a_startup_gate_refusal_fails_the_canary(tmp_path: Any) -> None:
    """The candidate goes back to the queue; nothing here can touch the armed loop to begin with."""
    result = evaluate(_cycles(SOAK_CYCLES), _cycles(SOAK_CYCLES), gate_refusals=1)
    assert not result.healthy
    assert [c.name for c in result.failures] == ["startup_gate"]


def test_a_construction_that_moves_mid_soak_fails() -> None:
    shadow = _cycles(SOAK_CYCLES)
    shadow[100]["construction"] = "bbb"
    assert "construction_stable" in [c.name for c in evaluate(shadow, _cycles(SOAK_CYCLES)).failures]


def test_guards_firing_at_the_armed_books_own_rate_is_a_pass() -> None:
    """A canary that demands an improvement over the armed book is asking the wrong question."""
    shadow = _cycles(SOAK_CYCLES, guards=40)
    armed = _cycles(SOAK_CYCLES, guards=40)
    assert evaluate(shadow, armed).healthy
    # Materially worse is not.
    assert "guard_rate" in [c.name for c in evaluate(_cycles(SOAK_CYCLES, guards=120), armed).failures]


def test_an_error_streak_fails_but_a_single_error_does_not() -> None:
    """A 503 burst through the proxy is the venue, not the candidate; a sustained one is a deployment."""
    one = _cycles(SOAK_CYCLES)
    one[5]["phase"] = "ERROR"
    assert evaluate(one, _cycles(SOAK_CYCLES)).healthy

    many = _cycles(SOAK_CYCLES)
    for i in range(5, 12):
        many[i]["phase"] = "ERROR"
    assert "no_error_streak" in [c.name for c in evaluate(many, _cycles(SOAK_CYCLES)).failures]


def test_a_target_outside_the_managed_universe_fails() -> None:
    shadow = _cycles(SOAK_CYCLES)
    shadow[3]["targets"]["NOT_MANAGED"] = 0.2
    assert "targets_in_universe" in [c.name for c in evaluate(shadow, _cycles(SOAK_CYCLES)).failures]


def test_an_order_the_rebalancer_would_truncate_fails() -> None:
    shadow = _cycles(SOAK_CYCLES)
    shadow[7]["skipped"] = [{"symbol": "A", "reason": "PARTICIPATION_CAP"}]
    assert "participation" in [c.name for c in evaluate(shadow, _cycles(SOAK_CYCLES)).failures]


def test_an_empty_shadow_is_never_healthy() -> None:
    """Vacuous truth is the failure mode of every all() over an empty sequence."""
    assert not evaluate([], []).healthy
