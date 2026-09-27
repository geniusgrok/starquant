"""R1 and the state file: the two things `lifecycle`'s pure functions deliberately do not know.

R3/R4/R5/R7 are properties of the book's state, so they live in the state machine.  R1 is a property
of the trials ledger, which is append-only and shared between parallel sessions - a counter held in
memory would already be wrong by the time a second session's `research validate` returned, and the
2026-09-08 incident was exactly that shape: a search charging 514 rows with nothing saying so.

The state file's job is narrower than it looks.  It does not decide anything; it lets the deciding
survive a restart, which matters because a restart is the ONLY moment the construction can change and
therefore the moment the machine is most likely to be asked a question it half-remembers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from starquant_governance.budget import mine_refusals, refusals, window_spend
from starquant_governance.lifecycle import Book, Candidate, State
from starquant_governance.policy import Policy
from starquant_governance.state import VERSION, dump, load, read, write

FOLD_DAYS = 7  # caliber 4's granularity; production reads Policy, tests pin it

WINDOW_START = datetime(2026, 9, 1, tzinfo=UTC)


def _row(recorded_at: datetime, param_key: str) -> str:
    return json.dumps(
        {
            "strategy": "tsmom",
            "param_key": param_key,
            "sharpe_annual": 1.0,
            "bars_per_year": 8760.0,
            "recorded_at": recorded_at.isoformat(),
            "range_start": "a",
            "range_end": "b",
            "symbols": 15,
            "run_id": "r",
        }
    )


def _mine_row(recorded_at: datetime, param_key: str, run_id: str) -> str:
    payload = json.loads(_row(recorded_at, param_key))
    return json.dumps({**payload, "strategy": "mined", "run_id": run_id})


def test_r1_charges_a_mine_round_as_one_event_not_as_its_row_count() -> None:
    """Policy 0.2.0.  A 514-row search made a 170-row monthly budget structurally unrunnable.

    R1 bounds how many SELECTIONS a window makes, and one mine round is one selection - enumerate the
    space, take the top k - however wide the space was.  Charging by row count penalised searching more
    thoroughly as though it were choosing more often, which is the wrong direction, and `refusals`
    refuses whole rather than truncating (a truncated search reports a `declared_trials` counting
    candidates nobody scored).  Together those made `research mine` impossible in any window, forever.
    """
    lines = [_mine_row(WINDOW_START, f"c{i}", "mine-shortlist-20260907T000000Z") for i in range(514)]
    budget = window_spend(lines, window_start=WINDOW_START)
    assert budget.spent == 0, "a mine round must not consume the row budget"
    assert budget.mined_rows == 514, "...but it is still reported, because it IS the DSR denominator"
    assert budget.mine_rounds == 1
    assert not refusals(budget, Policy().max_ledger_rows_per_window), (
        "a full row budget is still available after a mine round"
    )
    # ...and the round itself is what a LATER mine is refused on.  Read off the policy rather than
    # written as a number: the allowance moved 1 -> 4 in 0.3.0 and this test is about the mechanism,
    # not the value.  The value is pinned once, by the policy digest.
    exhausted = window_spend(
        [
            _mine_row(WINDOW_START, f"r{r}", f"mine-shortlist-2026090{r}T000000Z")
            for r in range(Policy().max_mine_rounds_per_window)
        ],
        window_start=WINDOW_START,
    )
    assert mine_refusals(exhausted)


def test_one_more_mine_round_than_the_window_allows_is_refused() -> None:
    """Counted as ROUNDS - distinct `run_id`s - however many rows each one wrote."""
    allowed = Policy().max_mine_rounds_per_window
    lines = [_mine_row(WINDOW_START, f"c{r}", f"mine-shortlist-round-{r}") for r in range(allowed + 1)]
    budget = window_spend(lines, window_start=WINDOW_START)
    assert budget.mine_rounds == allowed + 1
    assert f"already run {allowed + 1} mine round(s) of {allowed}" in mine_refusals(budget)[0]


def test_a_window_below_the_allowance_still_admits_another_mine() -> None:
    """The half the old test could not express while the allowance was one."""
    budget = window_spend([_mine_row(WINDOW_START, "a", "one-round")], window_start=WINDOW_START)
    assert budget.mine_rounds == 1
    assert not mine_refusals(budget), "0.3.0 allows four rounds a window; one used is not exhausted"


def test_the_dsr_denominator_is_not_what_changed() -> None:
    """The deflation question really is "best of how many", and that number really is 514.

    `ledger_scope` still files every mined candidate into one shared bucket and
    `oos_selection_threshold` still counts all of them.  R1 stopped charging them to a BUDGET; nothing
    stopped counting them as trials, and conflating the two would be the actual danger here.
    """
    from starquant_alpha.validation.ledger import ledger_scope, parse_ledger, unique_trials

    lines = [_mine_row(WINDOW_START, f"c{i}", "one-round") for i in range(514)]
    assert (
        len(unique_trials(parse_ledger(lines, ledger_scope("mined_abc")), range_end_granularity_days=FOLD_DAYS)) == 514
    )


def test_only_this_windows_rows_are_charged_to_this_window() -> None:
    lines = [_row(WINDOW_START - timedelta(days=5), "old"), _row(WINDOW_START + timedelta(days=1), "new")]
    assert window_spend(lines, window_start=WINDOW_START).spent == 1


def test_a_replay_is_one_trial_not_two() -> None:
    """Folded on the signature, the way the DSR denominator reads it - counting lines would over-charge."""
    same = _row(WINDOW_START + timedelta(days=1), "k")
    assert window_spend([same, same], window_start=WINDOW_START).spent == 1


def test_a_row_whose_time_cannot_be_read_is_charged_to_this_window() -> None:
    """The conservative direction: a budget that resolves its own doubt in favour of spending is not one."""
    broken = json.loads(_row(WINDOW_START, "k"))
    broken["recorded_at"] = "not a timestamp"
    assert window_spend([json.dumps(broken)], window_start=WINDOW_START).spent == 1


def test_a_run_that_would_cross_the_line_is_refused_whole() -> None:
    """Truncating a search produces a `declared_trials` that counts candidates nobody scored."""
    policy = Policy()
    lines = [_row(WINDOW_START, f"k{i}") for i in range(policy.max_ledger_rows_per_window - 10)]
    budget = window_spend(lines, window_start=WINDOW_START, policy=policy)
    assert budget.remaining == 10
    assert not refusals(budget, 10)
    assert refusals(budget, 11)
    assert "11 trials wanted, 10 left" in refusals(budget, 11)[0]


def test_the_state_round_trips_through_the_file(tmp_path: Path) -> None:
    book = Book(
        window=4,
        candidates={
            "a": Candidate("a", State.PROBE, probe_entries=2, windows_survived=3, fraction=1 / 3),
            "b": Candidate("b", State.RETIRED),
        },
        promotions_this_window=1,
        consecutive_probe_stops=1,
        frozen_until_window=9,
    )
    path = tmp_path / "governance_state.json"
    write(path, book)
    assert read(path) == book
    assert json.loads(path.read_text())["version"] == VERSION


def test_an_unreadable_state_is_an_empty_book_rather_than_an_exception(tmp_path: Path) -> None:
    """An empty book has no probes, so every rule refuses for want of a candidate instead of guessing."""
    path = tmp_path / "governance_state.json"
    path.write_text("{ this is not json")
    assert read(path) == Book()
    assert read(tmp_path / "missing.json") == Book()
    assert load(["not", "a", "dict"]) == Book()


def test_an_unknown_field_is_dropped_and_a_missing_one_takes_its_default() -> None:
    """DL-K1's compatibility rule, applied here for the same reason it exists there."""
    payload = dump(Book(window=2, candidates={"a": Candidate("a", State.MAIN)}))
    payload["candidates"]["a"]["invented_later"] = 7
    del payload["candidates"]["a"]["fraction"]
    del payload["consecutive_probe_stops"]
    restored = load(payload)
    assert restored.candidates["a"].state is State.MAIN
    assert restored.candidates["a"].fraction == 0.0
    assert restored.consecutive_probe_stops == 0


def test_a_candidate_in_a_state_this_version_does_not_know_is_skipped() -> None:
    payload = dump(Book(candidates={"a": Candidate("a", State.PROBE)}))
    payload["candidates"]["a"]["state"] = "a-state-from-the-future"
    assert load(payload).candidates == {}
