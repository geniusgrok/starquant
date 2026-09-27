"""RISK-G3 / DL-D2: the event-time contract, and the reason a confirmation is not a check.

The measured case, 2026-09-07: the T+1 metrics archive's `create_time` equals the REST `timestamp`
minus five minutes on 166 of 166 buckets, and on 0 of 165 at an offset of 0 or +-10 minutes.  Joining
the two sources on their own stamps would therefore have been wrong for EVERY bucket, in the direction
that flatters - research reading a value five minutes before the loop could have.  Nothing reports
that, because it is a convention rather than a bug; the whole of `starquant_data.alignment` exists so the
convention is a statement a sample can be held against.

The tests below that carry the weight are the ones that must FAIL.  A declaration wrong by 0 or by one
bucket either way has to be refused, or the contract is decoration.  And a sample whose values do not
move refutes nothing at any offset, so it answers UNVERIFIABLE rather than PASS: "算不出来就说算不
出来", the same refusal `metrics_parity` makes when it returns `rate: None` instead of 1.0.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from starquant_data.alignment import (
    CONTRACTS,
    FAIL,
    METRICS,
    PASS,
    SPOT,
    SPOT_BASIS_COLUMN,
    SPOT_COLUMNS,
    UNVERIFIABLE,
    Stamp,
    UndeclaredColumn,
    Verification,
    admits_live_signal,
    contract_for,
    restamp,
    verify_stamp_offset,
)

# Each feed registers its columns in `alignment.CONTRACTS` when it is imported, so the union asserted
# in `test_every_foreign_column_that_can_reach_the_panel_is_declared` is only complete if every feed in
# it has been pulled in - the import below is load-bearing for that reason, not tidiness.  It used to
# name four feeds; `starquant_data.index_price`, `starquant_data.macro` and `starquant_data.onchain` were
# withdrawn on 2026-09-16 (built, reachable, read by nothing), so metrics and spot are the union now.
from starquant_data.metrics import (
    PERIOD_MS,
    VALUE_COLUMNS,
    align_to_bars,
    bucket_open_from_archive,
    bucket_open_from_rest,
    parse_archive_csv,
    parse_rest_rows,
    usable_from_ms,
)
from starquant_data.metrics_snapshot import metrics_parity
from starquant_data.spot import SPOT_PANEL_COLUMNS

FIVE_MIN_MS = PERIOD_MS["5m"]
HOUR_MS = PERIOD_MS["1h"]
START = pd.Timestamp("2026-09-05 00:00", tz="UTC").value // 1_000_000
ARCHIVE_HEADER = ",".join(("create_time", "symbol", *VALUE_COLUMNS))


def _opens(count: int) -> list[int]:
    return [START + i * FIVE_MIN_MS for i in range(count)]


def _walk(count: int) -> list[float]:
    """Open interest that MOVES bucket to bucket, which is what makes an offset refutable at all."""
    rng = np.random.default_rng(7)
    return [float(v) for v in 100_000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, count)))]


def _archive_sample(count: int = 60, *, values: list[float] | None = None) -> pd.DataFrame:
    """The archive as it is served: `create_time` as a UTC datetime, one row per bucket OPEN."""
    return pd.DataFrame(
        {
            "create_time": pd.to_datetime(_opens(count), unit="ms", utc=True),
            "symbol": "BTCUSDT",
            "sum_open_interest": values if values is not None else _walk(count),
        }
    )


def _rest_sample(
    count: int = 60, *, stamp_offset_ms: int = FIVE_MIN_MS, values: list[float] | None = None
) -> pd.DataFrame:
    """The same buckets as REST serves them: integer ms, stamped by the bucket CLOSE."""
    return pd.DataFrame(
        {
            "timestamp": [open_ms + stamp_offset_ms for open_ms in _opens(count)],
            "symbol": "BTCUSDT",
            "sum_open_interest": values if values is not None else _walk(count),
        }
    )


def test_the_contract_states_what_starquant_data_metrics_already_does() -> None:
    """The contract DESCRIBES the live conversion; it does not replace it.

    Held against it in both directions, so whichever one a later change moves, this fails.  That is the
    only thing keeping a description honest once the code it describes is somewhere else.
    """
    open_ms = _opens(1)[0]

    assert METRICS.period_ms == FIVE_MIN_MS
    assert METRICS.archive.event_time(open_ms) == bucket_open_from_archive(pd.Timestamp(open_ms, unit="ms", tz="UTC"))
    assert METRICS.rest.event_time(open_ms + FIVE_MIN_MS) == bucket_open_from_rest(open_ms + FIVE_MIN_MS, FIVE_MIN_MS)
    assert METRICS.available_from(open_ms) == usable_from_ms(open_ms, FIVE_MIN_MS)
    # The number the 2026-09-07 session measured, stated once: REST's stamp is one bucket ahead.
    assert METRICS.stamp_offset_ms == FIVE_MIN_MS


def test_the_declared_offset_verifies_and_its_rivals_are_refuted_by_the_same_sample() -> None:
    """The 166/166 half and the 0/165 half, on one sample.  Only the second one is evidence."""
    result = verify_stamp_offset(METRICS, _archive_sample(), _rest_sample())

    assert result.verdict == PASS, result.reason
    assert result.matched == result.compared == 60
    assert {rival.rest_offset_ms for rival in result.rivals} == {0, 2 * FIVE_MIN_MS}
    for rival in result.rivals:
        assert rival.compared > 0 and rival.matched == 0, rival


@pytest.mark.parametrize(
    ("wrong_offset_ms", "what"),
    [
        (0, "the naive join: both sources' stamps taken as equal, which is the historical defect"),
        (-FIVE_MIN_MS, "one bucket the wrong way"),
        (2 * FIVE_MIN_MS, "one bucket too far"),
    ],
)
def test_a_declared_offset_wrong_by_a_bucket_must_fail(wrong_offset_ms: int, what: str) -> None:
    """The entire reason this contract exists.  A check that cannot fail here buys nothing.

    Correct data, wrong declaration - the direction that matters, because the declaration is what a
    future column's author writes by hand and what nothing else will contradict.
    """
    wrong = replace(METRICS, rest=Stamp("timestamp", wrong_offset_ms, what))

    result = verify_stamp_offset(wrong, _archive_sample(), _rest_sample())

    assert result.verdict == FAIL, f"{what} was accepted: {result.reason}"
    assert result.matched == 0 and result.compared > 0
    assert admits_live_signal("sum_open_interest", result)[0] is False


def test_a_source_that_changes_its_own_convention_is_caught_by_the_declaration_that_stopped_matching() -> None:
    """The other direction: the contract is right and the venue moved.

    Written separately from the wrong-declaration case because the two are different events with the
    same symptom, and a venue changing a stamp is the failure this contract has to survive next.
    """
    restamped_venue = _rest_sample(stamp_offset_ms=0)  # REST starts stamping the bucket OPEN

    result = verify_stamp_offset(METRICS, _archive_sample(), restamped_venue)

    assert result.verdict == FAIL, result.reason
    assert result.matched == 0


def test_a_column_that_never_moves_cannot_verify_its_own_offset() -> None:
    """A confirmation is not a check.

    A constant column agrees with itself at every offset, so "the declared offset matched" is true and
    worthless.  The honest answer is that this sample cannot tell them apart - not PASS, and not FAIL
    either, because nothing here refutes the declaration.
    """
    flat = [1_500.0] * 60

    result = verify_stamp_offset(METRICS, _archive_sample(values=flat), _rest_sample(values=flat))

    assert result.verdict == UNVERIFIABLE, result.reason
    assert result.matched == result.compared == 60  # the declared offset "held" on every row
    assert "cannot tell the declared offset apart" in result.reason
    assert admits_live_signal("sum_open_interest", result)[0] is False


def test_too_few_overlapping_buckets_reports_unverifiable_rather_than_pass() -> None:
    """`0 == 0` is not agreement.  A thin sample says so instead of returning a number."""
    result = verify_stamp_offset(METRICS, _archive_sample(6), _rest_sample(6))

    assert result.verdict == UNVERIFIABLE
    assert "6 comparable overlapping rows" in result.reason
    assert result.matched == 6  # they DID all agree; six rows is simply not a measurement


def test_two_samples_that_do_not_overlap_at_all_are_unverifiable_rather_than_perfect() -> None:
    """Zero disagreements out of zero comparisons is how a dead feed looks healthiest."""
    away = _rest_sample()
    away["timestamp"] = away["timestamp"] + 30 * 86_400_000

    result = verify_stamp_offset(METRICS, _archive_sample(), away)

    assert result.verdict == UNVERIFIABLE and result.compared == 0


def test_a_pair_of_missing_values_is_not_a_comparison() -> None:
    """Two NaNs are the ABSENCE of a comparison, so they may not be counted toward the score.

    Found by mutation: counting them left every test here green while a column that is half empty
    reported twice the evidence it had, and an entirely empty one reported a perfect match on nothing.
    That is `metrics_parity`'s `rate: None` lesson in the denominator instead of the numerator.
    """
    half_empty = _archive_sample()
    half_empty.loc[30:, "sum_open_interest"] = float("nan")

    partial = verify_stamp_offset(METRICS, half_empty, _rest_sample())
    empty = verify_stamp_offset(METRICS, _archive_sample(values=[float("nan")] * 60), _rest_sample())

    assert partial.verdict == PASS and partial.compared == partial.matched == 30
    assert empty.verdict == UNVERIFIABLE and "0 comparable overlapping rows" in empty.reason


def test_one_float_ulp_past_the_scale_binance_already_trades_is_not_a_source_disagreement() -> None:
    """Why the tolerance is relative, measured rather than preferred.

    The largest disagreement the production stores actually show is exactly one float64 ULP - 29 of
    ADAUSDT's 155 shared buckets, 1.5e-8 absolute at a notional of 8.4e7 - which is the two sources
    spelling one number differently, not a difference in the number.  An absolute tolerance prices that
    by magnitude, and the boundary is close: `metrics_parity`'s 1e-6 covers a ULP up to 2^33 = 8.590e9
    and not beyond, while BTCUSDT's open-interest notional read 8.515e9 on 2026-09-09.  A 0.9% rise
    puts it over, and the absolute check would then report float spelling as a source disagreement.
    """
    over_the_boundary = 2.0**33
    big = [over_the_boundary * (1.0 + value / 1e7) for value in _walk(60)]
    nudged = [float(np.nextafter(value, np.inf)) for value in big]
    worst_absolute = max(abs(a - b) for a, b in zip(big, nudged, strict=True))

    result = verify_stamp_offset(METRICS, _archive_sample(values=big), _rest_sample(values=nudged))

    assert worst_absolute > 1e-6, "the premise: one ULP at this scale exceeds metrics_parity's tolerance"
    assert result.verdict == PASS, result.reason


def test_a_column_nobody_declared_is_refused_by_name() -> None:
    """RISK-G3's first refusal.  Silence about a column is not permission to trade it."""
    with pytest.raises(UndeclaredColumn, match="funding_rate"):
        contract_for("funding_rate")

    admitted, reason = admits_live_signal("funding_rate", None)

    assert admitted is False
    assert "RISK-G3" in reason and "declare one" in reason


def test_a_declared_column_with_no_verification_on_record_is_also_refused() -> None:
    """The middle answer, and the one that does the work.

    Not-yet-shown and shown-false are both "no": the obligation is to have SHOWN the offset, not to
    have failed to disprove it.  Same three-answer shape as `parity_satisfied` one level up.
    """
    seen = ("sum_open_interest",)
    assert admits_live_signal("sum_open_interest", None)[0] is False
    assert admits_live_signal("sum_open_interest", Verification(FAIL, "x", 60, 0, (), seen))[0] is False
    assert admits_live_signal("sum_open_interest", Verification(UNVERIFIABLE, "x", 0, 0, (), seen))[0] is False

    admitted, reason = admits_live_signal("sum_open_interest", Verification(PASS, "60/60", 60, 60, (), seen))

    assert admitted is True and "60/60" in reason


def test_a_column_the_verification_never_compared_is_not_admitted_by_its_neighbours() -> None:
    """The refusal found by pointing this module at the production stores on 2026-09-09.

    `snapshot_metrics` polls `/futures/data/openInterestHist`, which returns open interest and nothing
    else, while `REST_TO_ARCHIVE` maps three ratio fields that only other endpoints serve.  So four of
    the six columns are NaN in every snapshot row - and `metrics_parity`, which folds columns into a
    row verdict and skips NaN pairs, reads `differing: 0, rate: 0.0` and the M-011 gate calls that
    parity met.  A row-level score cannot express "this column was never compared"; the column list can.
    """
    archive = _archive_sample()
    archive["count_long_short_ratio"] = 2.0  # the archive carries the ratio
    rest = _rest_sample()
    rest["count_long_short_ratio"] = float("nan")  # openInterestHist never returns it

    result = verify_stamp_offset(METRICS, archive, rest)

    assert result.verdict == PASS
    assert result.compared_columns == ("sum_open_interest",)
    assert result.uncompared_columns == ("count_long_short_ratio",)
    assert "no rows on both sides" in result.reason
    assert admits_live_signal("sum_open_interest", result)[0] is True
    admitted, reason = admits_live_signal("count_long_short_ratio", result)
    assert admitted is False and "never compared count_long_short_ratio" in reason


def test_every_foreign_column_that_can_reach_the_panel_is_declared() -> None:
    """The columns `Panel` can carry are exactly the ones a contract must cover; no gaps, no strays.

    Both halves matter and they fail differently.  A MISSING key is refused by `contract_for`, so a gap
    fails safe but invisibly - the column simply never reaches live and nobody is told which one.  A
    STRAY key is worse: `CONTRACTS` is what answers "which contract governs this column", so a key
    nothing carries is a contract nothing is held to, and the dangerous version of it is a new feed
    registering a bare name like "close" and inheriting another feed's offset.

    Two feeds now, and the equality is stated over their union rather than as a subset.  Two rewrites
    of this test arrived on the same day from different directions - one made it a subset to survive new
    feeds, one kept the equality and enumerated two of the three - and both were right about their own
    half: the equality has to stay exact, AND it has to name every feed, which is precisely the edit a
    new feed is forced to make here.  That forcing is the feature, and it has now been paid in both
    directions: #32 turned this test red until `starquant_data.macro`'s columns were named on both sides,
    and withdrawing macro/index on 2026-09-16 turned it red again until they were taken off both.

    **The four-feed version and what withdrawing two of them changed here (2026-09-16).**  The operator
    withdrew `starquant_data.macro`, `starquant_data.index_price` and `starquant_data.onchain`: built, reachable
    from `starquant data macro|index|onchain`, and read by no panel and no signal.  `CONTRACTS` is
    populated by each feed at IMPORT time, so this union shrank to the two feeds anything actually
    reads.  The mechanism is unchanged and is the whole point of the equality: a feed nobody imported
    is a feed this test cannot see, and it would pass by being blind rather than by being satisfied.

    What is LOST with them, stated rather than discovered later: `starquant_data.onchain` kept its own
    registry instead of joining `CONTRACTS`, and the assertion that its columns stayed OUT of this
    union was the record that the separation was a decision.  Both the registry and that assertion are
    gone with the feed.  A future on-chain feed does not inherit the split - it starts from this
    equality like metrics and spot do, which is the simpler shape and the one #32's note already argued
    the reason for the split had expired into.
    """
    declared = set(VALUE_COLUMNS) | set(SPOT_COLUMNS)
    assert set(CONTRACTS) == declared, "every column a feed can put on the panel, and nothing else"
    assert all(contract_for(column) is METRICS for column in VALUE_COLUMNS)
    assert all(contract_for(column) is SPOT for column in SPOT_COLUMNS)
    # Derived, not listed: a sixth spot field would otherwise be carried by `Panel` and unknown to
    # `CONTRACTS` - which fails safe, and invisibly.
    assert tuple(f"spot_{field}" for field in SPOT_PANEL_COLUMNS) == SPOT_COLUMNS
    assert SPOT_BASIS_COLUMN == "spot_close"


def test_the_spot_contract_declares_a_zero_offset_and_still_names_two_rivals_to_refute() -> None:
    """DL-D5.  A declared offset of zero is the case where "no offset" and "one bucket" look alike.

    So the rivals matter more here, not less: with `archive` and `rest` both at 0 the naive-join rival
    IS the declared offset and drops out, and what is left must still be the one bar either way that
    `starquant_data.spot` note 4 refuted (744/744 at lag 0, 0/743 shifted).  A contract that ended up with
    no rivals would report PASS on any sample at all, which is `verify_stamp_offset`'s UNVERIFIABLE
    branch existing for nothing.
    """
    assert SPOT.stamp_offset_ms == 0
    assert SPOT.rival_rest_offsets() == (-PERIOD_MS["1h"], PERIOD_MS["1h"])
    # One bar, and it is the arithmetic boundary rather than an observed latency: the perp bar and the
    # spot bar opening at t close at the same instant, so a same-bar read is available one bar on.
    assert SPOT.available_from(0) == PERIOD_MS["1h"]


def test_the_contract_and_metrics_parity_reach_the_same_verdict_on_the_same_buckets() -> None:
    """The consistency proof: the contract describes what the shipped parsers and M-011 already do.

    Both mechanisms are run on one pair of samples, twice - once under the correct convention and once
    under the naive one.  `metrics_parity` reports 100% of shared buckets disagreeing under the naive
    parse, which is the "100% 的桶错位" the 2026-09-07 entry recorded; the contract reports FAIL and
    names the offset.  Neither is rewritten in terms of the other: they are two readings of one fact.
    """
    opens, values = _opens(60), _walk(60)
    csv = (
        ARCHIVE_HEADER
        + "\n"
        + "".join(
            f"{pd.Timestamp(open_ms, unit='ms', tz='UTC'):%Y-%m-%d %H:%M:%S},BTCUSDT,{value},1.0,2.0,3.0,4.0,5.0\n"
            for open_ms, value in zip(opens, values, strict=True)
        )
    )
    rest_rows = [
        {"symbol": "BTCUSDT", "sumOpenInterest": value, "timestamp": open_ms + FIVE_MIN_MS}
        for open_ms, value in zip(opens, values, strict=True)
    ]
    archive = parse_archive_csv(csv)

    correct = metrics_parity(parse_rest_rows(rest_rows, FIVE_MIN_MS), archive)
    naive = metrics_parity(parse_rest_rows(rest_rows, 0), archive)

    assert correct == {"overlapping": 60, "differing": 0, "rate": 0.0}
    assert naive["rate"] == 1.0 and naive["differing"] == naive["overlapping"] == 59
    assert verify_stamp_offset(METRICS, _archive_sample(), _rest_sample()).verdict == PASS
    assert (
        verify_stamp_offset(
            replace(METRICS, rest=Stamp("timestamp", 0, "naive")), _archive_sample(), _rest_sample()
        ).verdict
        == FAIL
    )


def test_align_to_bars_never_hands_a_bar_a_bucket_the_contract_calls_unavailable() -> None:
    """The contract's availability rule, checked against the join the live loop actually runs.

    `align_to_bars` predates the contract and is not rewritten by it, so this asserts the two agree
    where it matters: the bucket a bar receives is available by the bar's close, and the next one is
    not.  If either side moves, this is what notices.
    """
    opens = _opens(40)
    metrics = pd.DataFrame({"open_time": opens, "sum_open_interest": [float(i) for i in range(len(opens))]})
    bars = pd.DatetimeIndex([pd.Timestamp(START + i * HOUR_MS, unit="ms", tz="UTC") for i in range(3)])

    aligned = align_to_bars(metrics, bars, interval_ms=HOUR_MS, period_ms=FIVE_MIN_MS)

    for bar in bars:
        chosen = int(aligned.loc[bar, "sum_open_interest"])
        bar_close = bar.value // 1_000_000 + HOUR_MS
        assert METRICS.available_from(opens[chosen]) <= bar_close
        assert METRICS.available_from(opens[chosen + 1]) > bar_close


def test_a_restamped_check_cannot_refute_the_arithmetic_and_the_limit_is_pinned_here() -> None:
    """`restamp` recovers the source stamps from canonical frames, and that is exactly as far as it goes.

    The offsets go back in as declared, so a wrong contract restamped under itself PASSES.  Asserted
    rather than only written down, because the tempting misuse is real: both stores hold `open_time`,
    so this is the only route to a check on production data, and somebody will want to cite its PASS
    as venue evidence.  What restamping still tests is the VALUES - two independent downloads of the
    same buckets - which is the half that can disagree.
    """
    canonical = pd.DataFrame({"open_time": _opens(60), "sum_open_interest": _walk(60)})
    wrong = replace(METRICS, rest=Stamp("timestamp", 0, "REST stamps the bucket open"))

    assert list(restamp(canonical, METRICS.rest)["timestamp"]) == [ms + FIVE_MIN_MS for ms in _opens(60)]
    honest = verify_stamp_offset(METRICS, restamp(canonical, METRICS.archive), restamp(canonical, METRICS.rest))
    circular = verify_stamp_offset(wrong, restamp(canonical, wrong.archive), restamp(canonical, wrong.rest))

    assert honest.verdict == PASS
    assert circular.verdict == PASS, "the stated limit: restamping cannot contradict its own declaration"


def test_a_repeated_event_time_is_refused_rather_than_deduped() -> None:
    """A duplicate fans the merge out and inflates every count, including the rivals' refutations.

    Dropping the row would make the check runnable and meaningless - the same trade this file exists
    to refuse one level up.
    """
    doubled = pd.concat([_archive_sample(), _archive_sample(1)], ignore_index=True)

    result = verify_stamp_offset(METRICS, doubled, _rest_sample())

    assert result.verdict == UNVERIFIABLE and "repeats an event time" in result.reason
