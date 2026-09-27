"""§3's third condition on `probe -> main`, which had no branch and no producer until 2026-09-09.

`Event.FAMILY_GATE_FAILED` was defined in `lifecycle`, handled in `lifecycle`, and emitted by nothing
anywhere in the tree; the `WINDOW_SURVIVED` branch checked R4 and stopped.  So a probe reached main on
two of the three conditions §3 names, and the missing one is the only one that can turn against a
sleeve while the sleeve does nothing at all.

The mechanism, because it is the point: the D-028 gate is `max_sharpe_quantile(N, variance, alpha)`,
and N is the strategy's ledger bucket plus that run's grid plus its declared pre-ledger trials.  The
ledger term is append-only and grows whenever anybody searches in the family.  Searching more retires
your own incumbents - the gate rises as sqrt(2 ln N), so it saturates and an incumbent with margin
survives, but one adopted on a thin margin does not get to keep it by standing still.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from starquant_alpha.registry import parse_registry
from starquant_alpha.validation.multiple_testing import SELECTION_GATE, max_sharpe_quantile
from starquant_governance.family_gate import FAIL, PASS, UNREADABLE, failures, read_gate, recheck

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

VARIANCE = 2.1972757178172574e-05
SCALE = math.sqrt(24 * 365)


def _report(*, sharpe: float, n_trials: int, ledger_trials: int, gate: str = SELECTION_GATE) -> dict[str, Any]:
    return {
        "oos_selection": {
            "alpha": 0.05,
            "gate": gate,
            "n_trials": n_trials,
            "variance": VARIANCE,
            "oos_sharpe_annual": sharpe,
            "threshold_annual": max_sharpe_quantile(n_trials, VARIANCE, 0.05) * SCALE,
        },
        "ledger": {"ledger_trials": ledger_trials},
    }


def _ledger(strategy: str, rows: int) -> list[str]:
    return [
        json.dumps(
            {
                "strategy": strategy,
                "param_key": f"i={i}",
                "sharpe_annual": 0.1,
                "bars_per_year": 8760.0,
                "recorded_at": "2026-09-09T00:00:00+00:00",
                "range_start": "2021-07-01 01:00:00+00:00",
                "range_end": "2026-09-01 01:00:00+00:00",
                "symbols": 15,
                "run_id": f"fixture-{i}",
            }
        )
        for i in range(rows)
    ]


def test_a_gate_recomputed_on_an_unchanged_ledger_reproduces_the_adoption_threshold() -> None:
    """The identity that makes every other reading attributable to N alone."""
    report = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
    reading = read_gate("tsmom", report, _ledger("tsmom", 86), range_end_granularity_days=FOLD_DAYS)
    assert reading.status == PASS
    assert reading.n_today == 183
    assert reading.threshold_today == pytest.approx(reading.threshold_at_adoption, rel=1e-12)


def test_more_search_in_the_family_raises_the_bar_the_incumbent_faces() -> None:
    """Nothing about the strategy changed.  Ninety-seven more trials in its bucket did."""
    report = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
    later = read_gate("tsmom", report, _ledger("tsmom", 183), range_end_granularity_days=FOLD_DAYS)
    assert later.n_today == 280
    assert later.threshold_today > later.threshold_at_adoption
    assert later.status == PASS, "the incumbent has margin; sqrt(2 ln N) saturates"


def test_a_thin_margin_does_not_survive_the_growth_that_a_wide_one_does() -> None:
    """The rule has to be able to say FAIL, or it is a formality rather than a gate."""
    thin = _report(sharpe=1.5140, n_trials=183, ledger_trials=86)
    assert read_gate("tsmom", thin, _ledger("tsmom", 86), range_end_granularity_days=FOLD_DAYS).status == PASS
    grown = read_gate("tsmom", thin, _ledger("tsmom", 400), range_end_granularity_days=FOLD_DAYS)
    assert grown.status == FAIL
    assert grown.margin is not None and grown.margin < 0
    assert failures([grown]) == (grown,)


def test_evidence_that_cannot_be_read_is_unreadable_rather_than_passed() -> None:
    """Four ways the question cannot be asked, and none of them answers it yes."""
    assert read_gate("x", {}, [], range_end_granularity_days=FOLD_DAYS).status == UNREADABLE
    assert (
        read_gate(
            "x",
            _report(sharpe=1.0, n_trials=10, ledger_trials=5, gate="expected_max"),
            [],
            range_end_granularity_days=FOLD_DAYS,
        ).status
        == UNREADABLE
    )
    no_ledger = _report(sharpe=1.0, n_trials=10, ledger_trials=5)
    del no_ledger["ledger"]
    assert read_gate("x", no_ledger, [], range_end_granularity_days=FOLD_DAYS).status == UNREADABLE
    # a bucket smaller than the report's is impossible on an append-only ledger: refuse, do not decide
    shrunk = read_gate(
        "tsmom",
        _report(sharpe=1.8, n_trials=183, ledger_trials=86),
        _ledger("tsmom", 3),
        range_end_granularity_days=FOLD_DAYS,
    )
    assert shrunk.status == UNREADABLE and "append-only" in shrunk.why


def test_the_bucket_count_is_not_n(tmp_path: Any) -> None:
    """The first version of this module read N off the bucket and called the live record impossible.

    Measured 2026-09-09: tsmom's report says N=183 while `ledger_scope('tsmom')` holds 88 rows, because
    183 is 86 ledger + 2 grid + 95 declared.  Only the first term can move after the fact.
    """
    report = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
    reading = read_gate("tsmom", report, _ledger("tsmom", 88), range_end_granularity_days=FOLD_DAYS)
    assert reading.n_today == 185, "183 + (88 - 86), not 88"


def test_a_probe_adopted_on_a_book_report_cannot_be_asked_this_question_at_all() -> None:
    """The finding this module produced on its first real run, pinned so it cannot be forgotten.

    `flow` is the only probe running.  Its registry evidence is a BOOK report (D-019: the sleeve's own
    validation verdict is FAIL, and it runs as a bounded experiment on the book verdict instead), and a
    book report carries no `oos_selection`.  So §3's third condition on `probe -> main` is not merely
    unimplemented for the sleeve that would be the first to use it - it is not computable, and the
    honest reading is UNREADABLE, which under `Facts.family_gate_still_passes = False` keeps flow in
    probe at window nine rather than promoting it on an unasked question.
    """
    registry = parse_registry(
        {
            "version": 1,
            "ensemble": {"method": "mean", "turnover_penalty": 0.0},
            "books": {"flow_short": {"fraction": 1 / 3}},
            "strategies": [
                {
                    "id": "flow",
                    "enabled": True,
                    "weight": 1.0,
                    "book": "flow_short",
                    "evidence": {"report": "reports/research/book-tsmom-flow.json"},
                },
            ],
        }
    )
    readings = recheck(
        registry, lambda _path: {"verdict": "REJECT", "sleeve": {}}, [], range_end_granularity_days=FOLD_DAYS
    )
    assert [r.status for r in readings] == [UNREADABLE]
    assert "oos_selection" in readings[0].why
    assert failures(readings) == (), "UNREADABLE is a failure to ask the question, not a failed gate"


def test_a_selection_block_missing_any_one_number_is_unreadable() -> None:
    """The four-way numeric check, pinned one field at a time.

    It read `all(isinstance(v, int | float) for v in (...))` until 2026-09-13.  That spelling narrows
    nothing for a type checker - every `float(sharpe)` and `int(n_then)` after it stayed `Any | None`,
    and mypy 2.x failed the file on 22 arg-type errors ahead of the test step, so the suite did not run
    for four days.  It was rewritten as an explicit chain, which is only a rewrite if every field still
    refuses on its own and refuses with the same sentence: the operator tells UNREADABLE from FAIL by
    that text, and a field that silently stopped being checked would reach `float()` as None instead.
    """
    message = "the selection block is missing sharpe/variance/threshold/n"
    for field in ("oos_sharpe_annual", "variance", "threshold_annual", "n_trials"):
        absent = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
        del absent["oos_selection"][field]
        reading = read_gate("tsmom", absent, _ledger("tsmom", 88), range_end_granularity_days=FOLD_DAYS)
        assert (reading.status, reading.why) == (UNREADABLE, message), f"absent {field}"

        not_a_number = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
        not_a_number["oos_selection"][field] = "1.8087"
        reading = read_gate("tsmom", not_a_number, _ledger("tsmom", 88), range_end_granularity_days=FOLD_DAYS)
        assert (reading.status, reading.why) == (UNREADABLE, message), f"{field} as a string"


def test_an_unreadable_reading_still_carries_the_numbers_it_could_read() -> None:
    """Field order on the partial `GateReading`, which two UNREADABLE returns fill positionally.

    `read_gate` hands the `ledger_trials`-missing and append-only-violation returns three bare
    positionals - sharpe, N at adoption, threshold at adoption - so a reordered dataclass would relabel
    an operator's numbers rather than fail, and the today columns must stay empty because nothing was
    recomputed.
    """
    no_ledger = _report(sharpe=1.8087, n_trials=183, ledger_trials=86)
    del no_ledger["ledger"]
    reading = read_gate("tsmom", no_ledger, _ledger("tsmom", 88), range_end_granularity_days=FOLD_DAYS)
    assert reading.status == UNREADABLE
    assert reading.oos_sharpe == 1.8087
    assert reading.n_at_adoption == 183
    assert reading.threshold_at_adoption == pytest.approx(max_sharpe_quantile(183, VARIANCE, 0.05) * SCALE)
    assert (reading.n_today, reading.threshold_today) == (None, None)
    assert reading.margin is None, "no threshold today means no margin today"
