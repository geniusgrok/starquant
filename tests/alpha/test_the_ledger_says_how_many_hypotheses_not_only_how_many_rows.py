"""A bucket's row count is not its hypothesis count, and the report has to say both.

2026-09-14.  The `mined` bucket held 2,731 rows and 676 distinct `param_key`s - 4.04 rows per
hypothesis - because `signature` folds on `(param_key, range, symbols, construction, overlay,
symbol set, search space)` and a re-run under a moved `range_end` is deliberately a second trial
(KILL-Q5, conservative by design).  That is the rule and this file does not touch it: `n_trials`
is unchanged by everything here.

What went wrong is a READING.  An analysis read 2,731 as "2,731 candidates were tried", concluded
the space had been searched 2,731 ways, and judged the miner on it.  Nothing in any artefact
contradicted that reading, because no artefact carried the other number.  `dsr_inputs` already
reports `ledger_rows`, `ledger_trials`, `duplicate_rows` and `replayed_rows` - four ways of
counting the same rows - and not once how many distinct hypotheses those rows are about.

So this adds a fifth field that is reported and never gated, for the same reason `all_trials`
exists: a number nobody can see is a number nobody can argue with.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from starquant_alpha.validation.ledger import (
    LEDGER_ENV,
    MINED_SEARCH_STRATEGY,
    TrialRecord,
    dsr_inputs,
    hypothesis_key,
    ledger_redirection,
    ledger_scope,
    parse_ledger,
    resolve_ledger_path,
)

#: The real ledger, reached without `resolve_ledger_path` on purpose: `conftest.isolated_trials_ledger`
#: is autouse and points that at a throwaway file, so a test asking it for the archive gets an empty
#: one and passes while measuring nothing.
REAL_LEDGER = Path(__file__).resolve().parents[2] / "reports" / "research" / "trials.jsonl"

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it


def _row(param_key: str, *, range_end: str = "2026-09-06", construction: str = "aaaa") -> TrialRecord:
    return TrialRecord(
        strategy="mined",
        param_key=param_key,
        sharpe_annual=1.0,
        bars_per_year=8760.0,
        recorded_at="2026-09-09T08:29:15+00:00",
        range_start="2021-01-01",
        range_end=range_end,
        symbols=205,
        run_id="r1",
        construction_digest=construction,
    )


def test_one_hypothesis_charged_under_three_contexts_is_three_trials_but_one_hypothesis() -> None:
    """Same expression, three contexts, charged three times - one hypothesis.

    The contexts are three CONSTRUCTIONS, not three `range_end`s.  The first version of this test used
    2026-09-06 / -08 / -08, and caliber ④ (2026-09-14) folds the first two: a signal reads only data up
    to bar t, so two runs whose ranges end two days apart produce an identical stream on the shared
    index.  The fixture moved to the axis that still separates rows, which is what the test was always
    about - `ledger_trials` counts rows under the fold, `distinct_hypotheses` counts hypotheses, and
    they are different numbers.
    """
    prior = [
        _row("squash(rangepos(24), 0.5)"),
        _row("squash(rangepos(24), 0.5)", construction="bbbb"),
        _row("squash(rangepos(24), 0.5)", construction="cccc"),
    ]

    out = dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=FOLD_DAYS)

    assert out["ledger_trials"] == 3, "the gate's caliber is unchanged: three constructions, three trials"
    assert out["distinct_hypotheses"] == 1, "but they are one hypothesis, and the report must say so"


def test_two_runs_a_few_days_apart_no_longer_make_two_trials() -> None:
    """Caliber ④, stated where the old fixture used to assume the opposite."""
    prior = [_row("a"), _row("a", range_end="2026-09-08")]

    assert dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=FOLD_DAYS)["ledger_trials"] == 1
    assert dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=0)["ledger_trials"] == 2


def test_distinct_hypotheses_counts_param_keys_not_rows() -> None:
    prior = [_row("a"), _row("a", range_end="2026-09-08"), _row("b"), _row("c")]

    assert dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=FOLD_DAYS)["distinct_hypotheses"] == 3


def test_one_expression_spelled_two_ways_is_one_hypothesis() -> None:
    """The search row and the candidate's own validation row are the same expression.

    Measured on the real ledger 2026-09-20, before this: every one of the seven `mined_*` strategies
    reported 677, and for four of them the bucket holds 676 - their own hash is already in it.
    """
    prior = [
        _row("00f951c68c4d55fa"),
        _row("entry_threshold=0.2|expression=cs_rank(z(ret(720), 336))|hash=00f951c68c4d55fa"),
    ]

    out = dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=FOLD_DAYS)

    assert out["ledger_trials"] == 2, "two rows are still two trials: the gate's caliber is untouched"
    assert out["distinct_hypotheses"] == 1, "but they are one expression, and the companion count says so"


def test_a_hash_field_that_is_not_a_canonical_hash_does_not_fold() -> None:
    """The fold is keyed on the shape `to_signal` writes, not on the word `hash`."""
    assert hypothesis_key("hash=not-a-hash") == "hash=not-a-hash"
    assert hypothesis_key("hash=00f951c6") == "hash=00f951c6", "8 hex digits is not the 16 it writes"
    assert hypothesis_key("window=48|trailing_hash=00f951c68c4d55fa") == "window=48|trailing_hash=00f951c68c4d55fa"
    assert hypothesis_key("00f951c68c4d55fa") == "00f951c68c4d55fa", "a bare hash is already the identity"


def test_the_real_ledger_stops_counting_a_mined_candidate_twice() -> None:
    """Reads the archive this repo actually ships, not a fixture shaped like it.

    Asserted as a relationship rather than a literal, because the ledger is append-only and grows:
    a `mined_<hash>` whose hash is already a bare row in the search bucket must not add a hypothesis.
    """
    if not REAL_LEDGER.exists():  # pragma: no cover - the archive is tracked, so this is a safety net
        pytest.skip("the tracked ledger is missing")
    lines = REAL_LEDGER.read_text().splitlines()
    bare = {record.param_key for record in parse_ledger(lines, MINED_SEARCH_STRATEGY)}

    checked = 0
    for strategy in sorted(_mined_candidates(lines)):
        digest = strategy.removeprefix("mined_")
        if digest not in bare:
            continue  # its expression predates the current search space; it really is one more
        prior = parse_ledger(lines, ledger_scope(strategy))
        out = dsr_inputs(prior, {}, 8760.0, range_end_granularity_days=FOLD_DAYS)
        assert out["distinct_hypotheses"] == len(bare), (
            f"{strategy}'s own expression is already in the {MINED_SEARCH_STRATEGY} bucket, "
            f"so the bucket's {len(bare)} is the whole count"
        )
        checked += 1

    assert checked >= 4, f"only {checked} aliased candidates found; 2026-09-20 measured four"


def _mined_candidates(lines: list[str]) -> set[str]:
    """Every `mined_<hash>` strategy the ledger holds, read off the file rather than listed here."""
    records = (TrialRecord.from_json(line) for line in lines)
    return {r.strategy for r in records if r is not None and r.strategy.startswith(f"{MINED_SEARCH_STRATEGY}_")}


def test_an_empty_ledger_has_no_hypotheses() -> None:
    assert dsr_inputs([], {}, 8760.0, range_end_granularity_days=FOLD_DAYS)["distinct_hypotheses"] == 0


def test_the_new_field_does_not_move_the_gate() -> None:
    """`n_trials` is what `oos_selection_threshold` reads.  This round must not touch it."""
    prior = [_row("a"), _row("a", construction="bbbb"), _row("b")]

    out = dsr_inputs(prior, {"grid": 0.01}, 8760.0, range_end_granularity_days=FOLD_DAYS)

    assert out["n_trials"] == 4, "3 ledger signatures + 1 current grid point, exactly as before"


def test_a_redirected_ledger_says_where_it_went(monkeypatch: pytest.MonkeyPatch) -> None:
    """`STARQUANT_TRIALS_LEDGER` is the one way to not be charged, and it was invisible.

    `resolve_ledger_path`'s docstring calls the variable's "only possible purpose ... to not be
    charged", and then returns the path with nothing saying it was overridden.  A command that
    charges the shared ledger and a command that charges a scratch file printed the same thing.
    """
    monkeypatch.setenv(LEDGER_ENV, "/tmp/not-the-real-ledger.jsonl")

    assert resolve_ledger_path() == __import__("pathlib").Path("/tmp/not-the-real-ledger.jsonl")
    assert ledger_redirection() == "/tmp/not-the-real-ledger.jsonl"


def test_an_unredirected_ledger_reports_no_redirection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LEDGER_ENV, raising=False)

    assert ledger_redirection() == ""


def test_whitespace_only_is_not_a_redirection(monkeypatch: pytest.MonkeyPatch) -> None:
    """`resolve_ledger_path` strips before testing; this must agree with it or the two disagree."""
    monkeypatch.setenv(LEDGER_ENV, "   ")

    assert ledger_redirection() == ""
    assert os.environ[LEDGER_ENV] == "   "
