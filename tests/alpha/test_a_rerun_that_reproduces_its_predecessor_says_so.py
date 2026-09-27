"""A re-authorised round that reproduces its predecessor bit-for-bit bought nothing, and must say so.

2026-09-09 09:50Z.  `research mine` ran the same space as 08:29Z under `--reauthorize`, and the
reason recorded in the artefact was specific and checkable: 90 candidates (oi 54 + lsr 36) had
`errored` because `Panel._map` dropped the metrics columns, "已在 3b49af8 修复" - so re-run them.

The run charged 658 rows.  It scored the same 568 candidates, errored on the same 90, against the
same `dataset.digest` and the same baseline, and every one of the 658 Sharpes came out identical.
The fix it invoked had not reached this path; the real one (`f4ea9de`) landed that evening and the
17:25Z round is what collected the 90.  So the middle round is a replay that its own authorisation
says should not have been one, and nothing in the artefact says it failed to achieve its purpose.

That is measurable at the moment the run ends, from two files already on disk, and it is the
difference between "we paid 658 rows for 90 scores" and "we paid 658 rows for nothing".  Q7's
precedent ("复原一份已经付过费的搜索……没有产生任何新的选择自由度") turns on exactly this
distinction, and today an operator can only reach it by diffing two reports by hand.

Reported, never refused: whether a reproduced round stays charged is a governance ruling, not this
function's call.  It only has to be impossible to miss.
"""

from __future__ import annotations

from starquant_alpha.mining.search import scoring_reproduction


def _scored(hash_: str, sharpe: float | None) -> dict[str, object]:
    return {"hash": hash_, "expression": f"expr({hash_})", "sharpe": sharpe}


def _errored(hash_: str) -> dict[str, object]:
    return {"hash": hash_, "expression": f"expr({hash_})", "error": "KeyError: metrics"}


def test_an_identical_rerun_is_reported_as_having_bought_nothing() -> None:
    previous = [_scored("a", 1.5), _scored("b", -0.25), _errored("c")]
    current = [_scored("a", 1.5), _scored("b", -0.25), _errored("c")]

    out = scoring_reproduction(previous, current)

    assert out["bought_nothing"] is True
    assert out["compared"] == 3
    assert out["identical"] == 3


def test_a_candidate_that_finally_scores_means_the_round_bought_something() -> None:
    """The 17:25Z round: same 658 expressions, but the 90 errors became scores."""
    previous = [_scored("a", 1.5), _errored("c")]
    current = [_scored("a", 1.5), _scored("c", 0.8)]

    out = scoring_reproduction(previous, current)

    assert out["bought_nothing"] is False
    assert out["identical"] == 1
    assert out["newly_scored"] == 1


def test_a_moved_sharpe_means_the_round_bought_something() -> None:
    previous = [_scored("a", 1.5)]
    current = [_scored("a", 1.5000001)]

    assert scoring_reproduction(previous, current)["bought_nothing"] is False


def test_a_candidate_the_predecessor_never_had_means_the_round_bought_something() -> None:
    previous = [_scored("a", 1.5)]
    current = [_scored("a", 1.5), _scored("z", 0.1)]

    out = scoring_reproduction(previous, current)

    assert out["bought_nothing"] is False
    assert out["unseen"] == 1


def test_a_candidate_that_stopped_being_scored_is_not_reproduction() -> None:
    """A round that LOSES a score is not a replay either - it is a regression, and must not read clean."""
    previous = [_scored("a", 1.5), _scored("c", 0.8)]
    current = [_scored("a", 1.5), _errored("c")]

    assert scoring_reproduction(previous, current)["bought_nothing"] is False


def test_no_predecessor_is_not_a_reproduction() -> None:
    """A first run of a space has nothing to reproduce; `bought_nothing` must not be true by vacuity."""
    out = scoring_reproduction([], [_scored("a", 1.5)])

    assert out["bought_nothing"] is False
    assert out["compared"] == 0


def test_two_empty_runs_are_not_a_reproduction_either() -> None:
    assert scoring_reproduction([], [])["bought_nothing"] is False


def test_a_none_sharpe_reproduced_is_still_a_reproduction() -> None:
    """`never_traded` rows carry `sharpe: None` and no `error`; two of them are the same reading."""
    previous = [_scored("a", None)]
    current = [_scored("a", None)]

    assert scoring_reproduction(previous, current)["bought_nothing"] is True
