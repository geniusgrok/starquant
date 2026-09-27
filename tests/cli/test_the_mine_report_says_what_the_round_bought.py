"""`research mine` reported four ways of counting rows and nothing about what the round bought.

Three numbers were missing from the artefact, and each one is a question an operator has had to
answer by hand at least once:

* **how many distinct hypotheses** the family's denominator is about.  The `ledger` block carried
  `charged`, `candidates`, `declared_remainder` and `family_prior` - all counts of rows - so the
  2026-09-14 analysis read `family_prior.after = 2731` as "2,731 candidates were tried" and judged
  the miner on it.  The bucket holds 676 distinct `param_key`s.  Nothing in the artefact could have
  contradicted the reading.
* **whether the round reproduced its predecessor.**  2026-09-09 09:50Z charged 658 rows under a
  `--reauthorize` whose stated reason was "3b49af8 fixed the 90 errors, re-run them"; all 658
  Sharpes came back identical to 08:29Z and the same 90 still errored, because the real fix
  (`f4ea9de`) had not landed.  The artefact records the authorisation and never whether it came true.
* **whether the ledger was redirected.**  `STARQUANT_TRIALS_LEDGER` is, in `resolve_ledger_path`'s own
  words, a variable "whose only possible purpose is to not be charged" - and a redirected run printed
  exactly what a charging run printed.

These are source assertions, which prove a rule is wired and never that it is right (that is
2026-09-09's own lesson, in the file next door).  The correctness half lives in
`tests/alpha/test_the_ledger_says_how_many_hypotheses_not_only_how_many_rows.py` and
`tests/alpha/test_a_rerun_that_reproduces_its_predecessor_says_so.py`, where the two functions are
exercised against real inputs.  They are here because the failure mode is OMISSION - a field absent
from a payload, not wrong in it - and an omission is invisible to any test that does not name it.
"""

from __future__ import annotations

import inspect

from starquant_cli import research_cmd


def _source_of(command: str) -> str:
    function = getattr(research_cmd, command)
    return inspect.getsource(getattr(function, "callback", function))


def test_the_mine_report_states_how_many_hypotheses_the_family_is_about() -> None:
    source = _source_of("research_mine")
    assert "distinct_hypotheses" in source, (
        "the `ledger` block counts rows four ways and hypotheses none; `family_prior.after` was read "
        "as a candidate count on 2026-09-14 and nothing in the report said otherwise"
    )


def test_the_mine_report_says_whether_a_reauthorised_round_reproduced_its_predecessor() -> None:
    """Asserted on the payload key, not on an internal name: the key is what reaches the artefact."""
    source = _source_of("research_mine")
    assert '"reproduction"' in source, (
        "R2 records the reason a re-run was authorised and never whether it came true; 2026-09-09 "
        "09:50Z charged 658 rows for 658 identical Sharpes"
    )


def test_the_reproduction_field_is_computed_by_the_function_that_has_tests() -> None:
    """The wiring's other end: the payload key must come from the tested comparison, not a reimplementation."""
    helper = inspect.getsource(research_cmd._reproduction_of)
    assert "scoring_reproduction" in helper


def test_a_reproduced_round_is_announced_and_not_only_filed() -> None:
    """The 2026-09-08 lesson: 514 rows were charged "with nothing on the terminal saying so"."""
    source = _source_of("research_mine")
    assert "bought_nothing" in source and "click.echo" in source, (
        "a round that bought nothing must say so where the operator is looking, not only in the JSON"
    )


def test_a_redirected_ledger_is_announced_by_the_command_that_charges_it() -> None:
    source = _source_of("research_mine")
    assert "ledger_redirection" in source, (
        "STARQUANT_TRIALS_LEDGER is the one documented way to not be charged, and a redirected run "
        "printed and recorded exactly what a charging run did"
    )
