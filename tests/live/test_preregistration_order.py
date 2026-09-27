"""DL-K3: a pre-registration written after the result is not a pre-registration.

KILL-R9's shape, mechanised.  The protocol says the hypothesis goes into `docs/RESEARCH_LOG.md`
before the run, and the only thing that made that true so far was somebody remembering to do it - the
ordering was never checked by anything, and P19 already showed what happens when a rule is written
correctly and its coverage is not (five separate misses in one round).

Two orderings, because the strategies come in two kinds:

* a hand-written strategy is registered by name, so the earliest commit to the log mentioning it must
  predate the report;
* a mined candidate cannot be registered by name - its hash is DERIVED from the search, so the hash
  provably cannot exist before the run that produced it.  What must precede it is the search: the
  mine that enumerated the candidate and charged it to the ledger (DL-K2).  Checking the hash against
  the log would be checking that somebody wrote the verdict down, which is not the same claim.
"""

from __future__ import annotations

from starquant_live.reports import preregistration_problems, preregistration_skipped


def _report(strategy: str, generated_at: str) -> dict[str, str]:
    return {
        "path": f"reports/research/{strategy}-validation-x.json",
        "strategy": strategy,
        "generated_at": generated_at,
    }


def test_a_report_that_predates_its_own_preregistration_fails() -> None:  # T-K3-1
    problems = preregistration_problems(
        [_report("tsmom", "2026-09-05T00:00:00+00:00")],
        first_mentioned={"tsmom": "2026-09-06T00:00:00+00:00"},
        search_charged={},
    )

    assert len(problems) == 1
    assert "tsmom" in problems[0]
    assert "2026-09-06" in problems[0] and "2026-09-05" in problems[0]


def test_the_normal_order_passes() -> None:  # T-K3-2
    problems = preregistration_problems(
        [_report("tsmom", "2026-09-06T00:00:00+00:00")],
        first_mentioned={"tsmom": "2026-09-05T00:00:00+00:00"},
        search_charged={},
    )

    assert problems == []


def test_a_strategy_the_log_never_mentions_fails() -> None:
    """Not "unknown, assume fine": an unregistered hypothesis is the thing this exists to catch."""
    problems = preregistration_problems(
        [_report("meanrev", "2026-09-06T00:00:00+00:00")],
        first_mentioned={"meanrev": None},
        search_charged={},
    )

    assert len(problems) == 1
    assert "never mentioned" in problems[0]


def test_a_mined_candidate_is_checked_against_its_search_not_against_the_log() -> None:
    """The hash is derived from the search, so it cannot appear in a commit that predates the search."""
    problems = preregistration_problems(
        [_report("mined_594a12f9307a15d9", "2026-09-06T17:55:00+00:00")],
        first_mentioned={"mined_594a12f9307a15d9": None},  # and it never will be
        search_charged={"594a12f9307a15d9": "2026-09-06T17:51:00+00:00"},
    )

    assert problems == []


def test_a_mined_candidate_validated_before_its_search_fails() -> None:
    problems = preregistration_problems(
        [_report("mined_abc", "2026-09-06T10:00:00+00:00")],
        first_mentioned={},
        search_charged={"abc": "2026-09-06T12:00:00+00:00"},
    )

    assert len(problems) == 1
    assert "abc" in problems[0]


def test_a_mined_candidate_no_search_ever_charged_fails() -> None:
    """DL-K2 makes this checkable: a candidate the ledger never saw was validated out of nowhere."""
    problems = preregistration_problems(
        [_report("mined_abc", "2026-09-06T10:00:00+00:00")],
        first_mentioned={},
        search_charged={},
    )

    assert len(problems) == 1
    assert "no search" in problems[0]


def test_every_report_is_judged_not_just_the_first() -> None:
    problems = preregistration_problems(
        [
            _report("tsmom", "2026-09-06T00:00:00+00:00"),
            _report("flow", "2026-09-01T00:00:00+00:00"),
            _report("meanrev", "2026-09-06T00:00:00+00:00"),
        ],
        first_mentioned={
            "tsmom": "2026-09-05T00:00:00+00:00",
            "flow": "2026-09-04T00:00:00+00:00",
            "meanrev": None,
        },
        search_charged={},
    )

    assert len(problems) == 2  # flow predates its mention, meanrev has none


def test_an_unparseable_timestamp_is_a_problem_rather_than_a_pass() -> None:
    """A check that silently skips what it cannot read reports success it did not verify."""
    problems = preregistration_problems(
        [_report("tsmom", "not a date")],
        first_mentioned={"tsmom": "2026-09-05T00:00:00+00:00"},
        search_charged={},
    )

    assert len(problems) == 1
    assert "could not be read" in problems[0]


def test_reports_that_predate_the_check_are_not_judged_by_it() -> None:
    """C-P6 again, one item over: a mechanism that lands today prices tomorrow's runs.

    Run against the real repository the first time, this check produced nine FAILs and not one of them
    was a finding.  Seven were mined validations with no `mined` ledger rows behind them - because
    DL-K2 landed the same day, so no mine had ever charged one.  The other two were reports whose log
    commit lands about an hour later, which is a batch commit at the end of a session and not evidence
    that anything was written in the wrong order: a commit timestamp is when the text was SAVED, not
    when it was written, and this check cannot tell those apart.  Nine lines of noise train an operator
    to skip the section, which is worse than not having it.
    """
    problems = preregistration_problems(
        [_report("mined_abc", "2026-09-05T00:00:00+00:00"), _report("meanrev", "2026-09-05T00:00:00+00:00")],
        first_mentioned={"meanrev": None},
        search_charged={},
        effective_from="2026-09-07T00:00:00+00:00",
    )

    assert problems == []


def test_a_report_produced_after_the_check_landed_is_judged() -> None:
    problems = preregistration_problems(
        [_report("meanrev", "2026-09-08T00:00:00+00:00")],
        first_mentioned={"meanrev": None},
        search_charged={},
        effective_from="2026-09-07T00:00:00+00:00",
    )

    assert len(problems) == 1


def test_the_boundary_is_stated_rather_than_silent() -> None:
    """Skipping quietly is how a check comes to cover nothing without anybody noticing."""
    skipped = preregistration_skipped(
        [_report("meanrev", "2026-09-05T00:00:00+00:00")], effective_from="2026-09-07T00:00:00+00:00"
    )

    assert skipped == 1


def test_a_sleeve_promoted_through_book_is_checked_too() -> None:
    """`research book` scores a sleeve exactly as `validate` does, and can promote one.

    DL-K3 first globbed `*-validation-*.json` only, so a candidate taken through `book` skipped the
    ordering check entirely - the same shape as `ledger_scope` reaching `validate` and not `book`.
    A protocol whose coverage depends on which command an operator happened to run is not a protocol.
    """
    problems = preregistration_problems(
        [
            {
                "path": "reports/research/book-tsmom-mined_abc-x.json",
                "strategy": "mined_abc",
                "generated_at": "2026-09-08T00:00:00+00:00",
            }
        ],
        first_mentioned={},
        search_charged={},
        effective_from="2026-09-07T00:00:00+00:00",
    )

    assert len(problems) == 1
    assert "no search" in problems[0]
