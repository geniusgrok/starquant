"""The evidence gate compares the overlays too, not only the signal params and the portfolio (2026-09-08 audit).

The live book is four layers - signal, sleeve, exit overlay, book guards - and the report the registry
cites described the first one.  `guards=` reached exactly one of sixteen `run_backtest` call sites and
`apply_exits` exactly one, neither of them in `research validate`, so the gate had nothing to compare:
`stop_loss 6 / take_profit 6` and `daily_loss_pause -0.05` ran live against evidence that never saw them.

Same contract as `construction_problems`, for the same reason: a report that predates the field is
skipped rather than refused, or nothing in flight today could start.  What is NOT skipped is a report
that says the layer was off while the loop runs it - that is a divergence, not an absence.
"""

from __future__ import annotations

from starquant_alpha.registry import StrategyEntry, construction_problems, evidence_problems

LIVE = {
    "vol_target": 0.30,
    "vol_halflife": 48,
    "covariance_halflife": 96,
    "min_asset_vol": 0.10,
    "max_weight": 0.15,
    "max_gross": 2.0,
    "max_scalar": 3.0,
    "no_trade_band": 0.005,
    "no_trade_rel_band": 0.40,
}
GUARDS = {"max_weight": 0.15, "max_gross": 2.0, "daily_loss_pause": -0.05}
EXITS = {"stop_loss": 6.0, "trailing_stop": 0.0, "take_profit": 6.0, "cooldown_bars": 24, "vol_halflife": 48}
OVERLAYS = {"book_guards": GUARDS, "exits": EXITS}
ENTRY = StrategyEntry("tsmom", params={"horizons": [168, 336, 720]})


def _report(**blocks: object) -> dict[str, object]:
    return {"kind": "validation", "portfolio": dict(LIVE), **blocks}


def test_a_matching_pair_of_overlays_is_silent() -> None:
    report = _report(book_guards=dict(GUARDS), exits=dict(EXITS))
    assert construction_problems(ENTRY, report, LIVE, OVERLAYS) == []


def test_a_guard_threshold_that_drifted_is_caught() -> None:
    report = _report(book_guards={**GUARDS, "daily_loss_pause": -0.10}, exits=dict(EXITS))
    problems = construction_problems(ENTRY, report, LIVE, OVERLAYS)
    assert problems == ["tsmom: book_guards daily_loss_pause is -0.05 live but -0.1 in the cited evidence"]


def test_an_exit_distance_that_drifted_is_caught() -> None:
    report = _report(book_guards=dict(GUARDS), exits={**EXITS, "take_profit": 4.0})
    problems = construction_problems(ENTRY, report, LIVE, OVERLAYS)
    assert problems == ["tsmom: exits take_profit is 6.0 live but 4.0 in the cited evidence"]


def test_evidence_that_ran_the_layer_off_while_the_loop_runs_it_is_a_divergence() -> None:
    """The 2026-09-08 shape, once the field exists: the report says `null`, the loop trades the overlay."""
    report = _report(book_guards=None, exits=None)
    problems = construction_problems(ENTRY, report, LIVE, OVERLAYS)
    assert len(problems) == 2
    assert any("book_guards" in p and "applied none" in p for p in problems)
    assert any("exits" in p and "applied none" in p for p in problems)


def test_a_layer_that_is_off_on_both_sides_is_silent() -> None:
    report = _report(book_guards=dict(GUARDS), exits=None)
    assert construction_problems(ENTRY, report, LIVE, {"book_guards": GUARDS, "exits": None}) == []


def test_reports_without_the_blocks_are_skipped_rather_than_refused() -> None:
    """Every report in flight on 2026-09-08 predates these fields; refusing them would stop the loop."""
    assert construction_problems(ENTRY, _report(), LIVE, OVERLAYS) == []


def test_the_portfolio_comparison_is_untouched() -> None:
    report = _report(book_guards=dict(GUARDS), exits=dict(EXITS))
    report["portfolio"] = {**LIVE, "no_trade_rel_band": 0.25}
    problems = construction_problems(ENTRY, report, LIVE, OVERLAYS)
    assert problems == ["tsmom: portfolio no_trade_rel_band is 0.4 live but 0.25 in the cited evidence"]


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
        "portfolio": dict(LIVE),
        "book_guards": {**GUARDS, "daily_loss_pause": -0.10},
        "exits": dict(EXITS),
    }
    problems = evidence_problems(
        entry,
        exists=lambda _p: True,
        sha256_of=lambda _p: "a" * 64,
        read_report=lambda _p: report,
        canonical_params=lambda _s, params: params,
        live_portfolio=LIVE,
        live_overlays=OVERLAYS,
    )
    assert any("book_guards daily_loss_pause" in problem for problem in problems)
