"""The research loop had no reason to ever stop mining, and by 2026-09-09 it should have.

`next_action` returns MINE whenever R2's condition holds (the space digest moved) and R1 still has a
round.  Nothing in it looks at whether another round could produce an admissible candidate.  It could
not, and had not been able to for days: the `mined` bucket's D-028 threshold rises monotonically with
N, and by 2026-09-09 it had risen past the out-of-sample Sharpe of the best candidate the space has
ever produced.  Two more rounds ran after that.

The condition here is DERIVED, not chosen - which is the only reason it may live in a scheduler that
otherwise holds no thresholds of its own (`test_policy_is_the_only_place_a_threshold_lives`).  Both
sides of it are measurements already on disk:

* the best mined candidate's own `oos_selection` block, from its validation report;
* the ledger today.

The recomputation itself is `family_gate.read_gate` and deliberately not a second implementation of
it.  The first version of this file asserted against one, and it was wrong exactly where that module's
comment says a second implementation goes wrong: it read N as the bucket count, while `dsr_inputs`
builds N as `ledger_trials + grid + declared prior`.  `mined_594a12f9307a15d9` was signed at
575 = 0 + 1 + 574, so its N today is 575 plus the bucket's growth - understating the gate by 0.02 and
stopping later than it should.

It refuses SPENDING, never promotion.  Nothing here touches a verdict, `n_trials`, or what may reach
the book; an append-only ledger makes not-spending the reversible direction, and mining resumes by
itself the moment a wider space or a better candidate moves either number.
"""

from __future__ import annotations

import json

from starquant_alpha.validation.multiple_testing import SELECTION_GATE
from starquant_governance.assemble import gate_has_passed_the_space
from starquant_governance.policy import Policy
from starquant_governance.scheduler import MINE, WAIT, Context, next_action

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it


def _mineable(**overrides: object) -> Context:
    """A context whose only available action is MINE, so a WAIT can only come from the new condition."""
    return Context(search_space_digest="new", last_mined_space_digest="old", **overrides)  # type: ignore[arg-type]


def test_the_loop_still_mines_while_the_gate_is_below_the_spaces_best() -> None:
    assert next_action(_mineable(mined_gate_passed_best=0)).kind == MINE


def test_the_loop_stops_mining_once_the_gate_passes_the_spaces_best() -> None:
    action = next_action(_mineable(mined_gate_passed_best=1))

    assert action.kind == WAIT
    assert action.reasons, "scheduler's own rule: a WAIT always carries its reason"
    assert "gate" in " ".join(action.reasons).lower()


def test_the_stop_can_be_turned_off_by_policy() -> None:
    """A threshold-free rule is still a rule, and every rule here has to be switchable from `Policy`."""
    off = Policy(mine_requires_gate_below_best=False)

    assert next_action(_mineable(mined_gate_passed_best=1), off).kind == MINE


def test_the_stop_does_not_block_the_work_already_in_hand() -> None:
    """VALIDATE/BOOK/PARITY/QUEUE rank above MINE; a candidate already found must not be stranded."""
    stranded = _mineable(mined_gate_passed_best=1, validated_unbooked=1)

    assert next_action(stranded).kind == "book"


def _report(oos: float) -> dict[str, object]:
    """The shape `read_gate` requires: the selection block plus the ledger term it separates out."""
    return {
        "oos_selection": {
            "gate": SELECTION_GATE,
            "oos_sharpe_annual": oos,
            "variance": 2.200184145624143e-05,
            "threshold_annual": 1.645341936067292,
            "n_trials": 575,
            "alpha": 0.05,
        },
        "ledger": {"ledger_trials": 0},
    }


def _ledger(mined_rows: int) -> list[str]:
    return [
        json.dumps(
            {
                "strategy": "mined",
                "param_key": f"e{i}",
                "sharpe_annual": 1.0,
                "bars_per_year": 8760.0,
                "recorded_at": "2026-09-09T08:29:15+00:00",
                "range_start": "2021-01-01",
                "range_end": "2026-09-08",
                "symbols": 205,
                "run_id": "r",
            }
        )
        for i in range(mined_rows)
    ]


def test_a_space_with_no_validated_candidate_yet_is_not_stopped() -> None:
    """Nothing to compare against is not the same fact as "the bar has passed it"."""
    passed, why = gate_has_passed_the_space({}, _ledger(2731), range_end_granularity_days=FOLD_DAYS)

    assert passed is False
    assert "no" in why.lower()


def test_the_best_candidate_of_2026_09_06_would_not_clear_todays_ledger() -> None:
    """`mined_594a12f9307a15d9` was signed at N=575 with an empty bucket; the bucket is now 2,731."""
    reports = {"mined_594a12f9307a15d9": _report(1.786223252863809)}

    passed_then, _ = gate_has_passed_the_space(reports, _ledger(0), range_end_granularity_days=FOLD_DAYS)
    passed_now, why = gate_has_passed_the_space(reports, _ledger(2731), range_end_granularity_days=FOLD_DAYS)

    assert passed_then is False, "it cleared its own gate on the day it was validated"
    assert passed_now is True, "and would not clear the same gate against today's ledger"
    assert "1.7862" in why, f"the reason has to carry the Sharpe it is about: {why}"
    assert "3306" in why, f"N today is 575 + the bucket's growth, not the bucket: {why}"


def test_the_comparison_uses_the_best_candidate_not_the_newest() -> None:
    """A later, worse candidate must not make the space look exhausted."""
    reports = {"mined_poor": _report(0.4), "mined_good": _report(2.5)}

    passed, why = gate_has_passed_the_space(reports, _ledger(2731), range_end_granularity_days=FOLD_DAYS)

    assert passed is False, f"2.5 still clears the bar; the space is not exhausted: {why}"
    assert "mined_good" in why


def test_a_report_without_the_block_is_skipped_not_guessed() -> None:
    """Reports written before `oos_selection` existed carry no opinion about this."""
    passed, why = gate_has_passed_the_space(
        {"mined_old": {"verdict": "PASS"}}, _ledger(2731), range_end_granularity_days=FOLD_DAYS
    )

    assert passed is False
    assert "no" in why.lower()
