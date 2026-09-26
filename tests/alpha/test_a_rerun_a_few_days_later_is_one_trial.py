"""Caliber ④ (operator ruling, 2026-09-14): `range_end` folds to a policy-set granularity.

Q4c measured what the caliber question actually turned on.  After the Q2 rollback the `mined` bucket
held 2,073 rows over 676 expressions in four contexts, and two of the three axes were confounded -
`construction` moved only with `symbols`, and `range_end` spanned 2-3 days out of five years and eight
months.  Scoring the same 676 expressions on both universes gave a joint `N_exact` of 641 against a
single-universe 337, a ratio of 1.90: **the second universe is very nearly a full second look, so
cross-universe re-charges stay charged.**  Only the `range_end` axis collapses.

That half needs no simulation.  A signal's value at bar t depends on data up to t, so the same
expression, same symbols, same construction, evaluated over a range that ends a few days later
produces an **identical stream on the shared index** - the extra ~48 bars are the only difference.
Identical streams cannot be two independent looks; the added independence is exactly zero.  Arithmetic,
not an estimate.

**But the argument does not say "drop `range_end`".**  It holds for any difference, including two more
years - and two more years really is a second look, because the Sharpe it records is a different
number.  So the rule needs a granularity, a granularity is a threshold, and R10 says thresholds live in
`Policy`.  `starquant_alpha` is the lower layer and cannot import it, so the value is threaded through as
a REQUIRED keyword: a caller that forgets it fails to call rather than silently getting the old
behaviour, which is the invisible-default shape this repo has been bitten by twice.

The granularity is not load-bearing on this ledger - 7, 14 and 30 days all give `mined` 1,559,
`tsmom` 101, `flow` 43 - so 7 is chosen as the one that folds least among those that fold the case at
all.  Bucket boundaries mean two runs a day apart can straddle one and not fold; that is a known
imperfection and it errs toward charging MORE, which is the direction a denominator may be wrong in.
"""

from __future__ import annotations

import pytest

from starquant_alpha.validation.ledger import TrialRecord, dsr_inputs, unique_trials

GRANULARITY = 7


def _row(range_end: str, *, param_key: str = "a", symbols: int = 205, construction: str = "cafe") -> TrialRecord:
    return TrialRecord(
        strategy="mined",
        param_key=param_key,
        sharpe_annual=1.0,
        bars_per_year=8760.0,
        recorded_at=f"{range_end}T00:00:00+00:00",
        range_start="2021-01-01",
        range_end=range_end,
        symbols=symbols,
        run_id="r",
        construction_digest=construction,
    )


def test_two_runs_three_days_apart_are_one_trial() -> None:
    """The 2026-09-09 shape: 2026-09-06, -08 and -09 over a 2021-01-01 start."""
    rows = [_row("2026-09-06"), _row("2026-09-08"), _row("2026-09-09")]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 1


def test_the_same_runs_are_three_trials_when_the_rule_is_off() -> None:
    """Granularity 0 is the pre-ruling behaviour, and it has to stay reachable to be comparable."""
    rows = [_row("2026-09-06"), _row("2026-09-08"), _row("2026-09-09")]

    assert len(unique_trials(rows, range_end_granularity_days=0)) == 3


def test_a_different_construction_is_still_two_trials() -> None:
    """Q4c's stop sign: in the `tsmom` bucket construction is NOT confounded with symbols."""
    rows = [_row("2026-09-06", construction="cafe"), _row("2026-09-08", construction="beef")]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 2


def test_a_different_universe_is_still_two_trials() -> None:
    """The measured half: the second universe is worth 1.90x, so it stays charged."""
    rows = [_row("2026-09-08", symbols=205), _row("2026-09-08", symbols=17)]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 2


def test_a_different_range_start_is_still_two_trials() -> None:
    """The streams differ from the first bar, so the identical-prefix argument does not apply."""
    late = _row("2026-09-08")
    rows = [late, TrialRecord(**{**vars(late), "range_start": "2022-01-01"})]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 2


def test_two_years_later_is_still_two_trials() -> None:
    """The whole reason the rule needs a granularity instead of dropping the field."""
    rows = [_row("2024-09-08"), _row("2026-09-08")]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 2


def test_an_unparseable_range_end_is_never_folded() -> None:
    """A date this cannot read says nothing, and a denominator resolves its doubt by charging more."""
    rows = [_row("not-a-date"), _row("also-not-a-date")]

    assert len(unique_trials(rows, range_end_granularity_days=GRANULARITY)) == 2


def test_the_current_grid_is_excluded_under_the_same_fold_as_the_ledger() -> None:
    """The trap this ruling could have shipped: `exclude` is built to match, or a replay is charged twice.

    `dsr_inputs` drops ledger rows that ARE the current grid re-run on the same data.  It built that
    exclusion set by hand in the shape of `signature`; if the fold quantises `range_end` and the
    exclusion does not, every replay stops matching and is charged again - silently, and in the
    direction that looks rigorous.  Both now go through one key.
    """
    prior = [_row("2026-09-06"), _row("2026-09-08", param_key="b")]

    out = dsr_inputs(
        prior,
        {"a": 0.01},
        8760.0,
        current_range=("2021-01-01", "2026-09-09", 205),
        current_context=("cafe", "", "", ""),
        range_end_granularity_days=GRANULARITY,
    )

    assert out["replayed_rows"] == 1, "the 09-06 row is the current grid three days earlier"
    assert out["n_trials"] == 2, "one surviving ledger trial plus the current grid point"


def test_dsr_inputs_reports_the_granularity_it_used() -> None:
    """A fold nobody can see is a fold nobody can argue with."""
    out = dsr_inputs([_row("2026-09-06")], {}, 8760.0, range_end_granularity_days=GRANULARITY)

    assert out["range_end_granularity_days"] == GRANULARITY


def test_the_granularity_has_to_be_passed() -> None:
    """No default: a caller that forgets it must fail to call, not quietly get the old behaviour."""
    with pytest.raises(TypeError):
        unique_trials([_row("2026-09-06")])  # type: ignore[call-arg]
