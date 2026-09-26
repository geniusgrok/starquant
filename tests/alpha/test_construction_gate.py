"""The evidence gate also compares the portfolio construction, not only the signal parameters."""

from __future__ import annotations

from starquant_alpha.registry import CONSTRUCTION_KEYS, StrategyEntry, construction_problems, evidence_problems

LIVE = {
    "vol_target": 0.15,
    "vol_halflife": 48,
    "covariance_halflife": 96,
    "min_asset_vol": 0.10,
    "max_weight": 0.15,
    "max_gross": 2.0,
    "max_scalar": 3.0,
    "no_trade_band": 0.005,
    "no_trade_rel_band": 0.40,
    # P30.  Non-zero in the fixture on purpose: the loop below proves each key is compared by doubling
    # it, and doubling the shipped 0.0 is still 0.0.  The shipped value gets its own test underneath.
    "sleeve_max_gross": 0.86,
    # D2, 2026-09-14.  The first BOOL in this table, and it broke the loop below rather than the gate:
    # `_same_param` folds bools with `bool(left) == bool(right)` on purpose (YAML `true` vs JSON `1`),
    # so doubling True gives 2 and compares EQUAL - the loop would have reported the key as covered
    # while perturbing nothing.  The loop negates bools instead.  The shipped value is False and gets
    # its own test underneath, the same way `sleeve_max_gross`'s shipped 0.0 does.
    "flat_inside_band": True,
    # D3, 2026-09-17.  Carries the shipped value, unlike the two above: doubling 2.0 gives 4.0 and the
    # gate sees it, so this key needs neither the non-zero dodge nor the bool negation.
    "band_entry_multiple": 2.0,
}
ENTRY = StrategyEntry("tsmom", params={"horizons": [168, 336, 720]})


def test_the_real_divergence_is_caught() -> None:
    """P10 cell B moved the live band to 0.40 while tsmom's evidence had been validated at 0.25."""
    report = {"kind": "validation", "portfolio": {**LIVE, "no_trade_rel_band": 0.25}}
    problems = construction_problems(ENTRY, report, LIVE)
    assert problems == ["tsmom: portfolio no_trade_rel_band is 0.4 live but 0.25 in the cited evidence"]


def test_a_matching_construction_is_silent_and_every_weight_bearing_key_is_covered() -> None:
    assert construction_problems(ENTRY, {"portfolio": dict(LIVE)}, LIVE) == []
    for key in CONSTRUCTION_KEYS:
        value = LIVE[key]
        # Bools first: `isinstance(True, int)` is True, so the numeric branch would silently claim to
        # perturb one and not (see the fixture note on `flat_inside_band`).
        perturbed = (not value) if isinstance(value, bool) else (value * 2 if isinstance(value, int | float) else value)
        drifted = {**LIVE, key: perturbed}
        assert construction_problems(ENTRY, {"portfolio": drifted}, LIVE), f"{key} must be compared"


def test_a_sleeve_cap_in_the_evidence_that_the_loop_does_not_run_is_caught() -> None:
    """The shipped value is 0.0, and 0.0 is the one value the doubling loop above cannot test.

    It is also the asymmetry that matters in practice: evidence produced under a cap describes a book
    whose sleeve was held smaller than the one the loop would trade, which is P10 cell B's shape one
    layer down - the direction that flatters the evidence.
    """
    off = {**LIVE, "sleeve_max_gross": 0.0}
    problems = construction_problems(ENTRY, {"portfolio": dict(LIVE)}, off)
    assert problems == ["tsmom: portfolio sleeve_max_gross is 0.0 live but 0.86 in the cited evidence"]
    assert construction_problems(ENTRY, {"portfolio": off}, off) == []


def test_evidence_that_never_held_a_sub_band_position_is_caught_against_a_loop_that_does() -> None:
    """D2's shipped value is False, the one value the doubling loop cannot test - same as the cap above.

    And the asymmetry runs the same way: evidence produced with ``flat_inside_band`` on describes a
    book that never carried a position it could not close, which is a cleaner book than the loop's.
    """
    off = {**LIVE, "flat_inside_band": False}
    problems = construction_problems(ENTRY, {"portfolio": dict(LIVE)}, off)
    assert problems == ["tsmom: portfolio flat_inside_band is False live but True in the cited evidence"]
    assert construction_problems(ENTRY, {"portfolio": off}, off) == []


def test_values_that_crossed_a_yaml_json_boundary_still_compare_equal() -> None:
    report = {"portfolio": {**LIVE, "no_trade_rel_band": 0.4000000000000001, "max_gross": 2}}
    assert construction_problems(ENTRY, report, LIVE) == []


def test_reports_without_the_block_are_skipped_rather_than_refused() -> None:
    """Every report in flight today predates the field; refusing them would stop the loop."""
    assert construction_problems(ENTRY, {"kind": "validation", "best_params": {}}, LIVE) == []
    assert construction_problems(ENTRY, {"portfolio": {}}, LIVE) == []
    assert construction_problems(ENTRY, {"portfolio": dict(LIVE)}, None) == []


def test_it_is_wired_into_the_startup_gate() -> None:
    entry = StrategyEntry(
        "tsmom",
        params={"horizons": [168, 336, 720]},
        evidence={"report": "r.json", "sha256": "a" * 64, "verdict": "PASS"},
    )
    report = {
        "kind": "validation",
        "strategy": "tsmom",
        "best_params": {"horizons": [168, 336, 720]},
        "portfolio": {**LIVE, "no_trade_rel_band": 0.25},
    }
    problems = evidence_problems(
        entry,
        exists=lambda _: True,
        sha256_of=lambda _: "a" * 64,
        read_report=lambda _: report,
        canonical_params=lambda _sid, params: dict(params),
        live_portfolio=LIVE,
    )
    assert any("no_trade_rel_band" in problem for problem in problems)
    # without the live construction the gate behaves exactly as before
    assert (
        evidence_problems(
            entry,
            exists=lambda _: True,
            sha256_of=lambda _: "a" * 64,
            read_report=lambda _: report,
            canonical_params=lambda _sid, params: dict(params),
        )
        == []
    )
