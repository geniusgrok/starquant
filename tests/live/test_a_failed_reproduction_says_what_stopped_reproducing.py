"""KILL-027's monitor fired six times in 48 hours and left no recoverable evidence any of them.

`run_check.sh` pages with `"$(echo "$output" | tail -n 3 | tr '\\n' ' ')"`, and this command's output is
pretty-printed JSON sorted by key.  Its last three lines are `"tolerance": 1e-09`, `}` and the error,
so every one of the six alerts between 2026-09-10T18:10Z and 2026-09-12T09:10Z read:

    FAIL verify:   "tolerance": 1e-09 } Error: 模型已无法复现上一周期的 contributions（...）

By the time anyone looked, `state.json` had been overwritten by the next cycle and the diff was gone.
The cause was only found by replaying 56 cycles offline against freshly fetched klines, which
reproduced all six exactly - every one a single symbol in the `flow` book, 3.3e-8 to 8.5e-7 against a
1e-9 tolerance, on the four names whose `taker_buy_quote / quote_volume` the flow signal reads.

Two things follow.  The first: the payload must name the offenders, in the note itself, so the one
line that survives the pager says which strategy and which symbol moved.

The second is the cause, measured 2026-09-12 by two experiments that bracket it:

* re-fetching the bar that closed at 12:00Z at +15s, +60s, +300s and +600s over six symbols returned
  byte-identical values on every field - the kline is settled by +15s;
* of the 57 replayed cycles, **all six failures fetched within 14s of the close, and 0 of the 22 that
  fetched later than 14s failed**.

So the loop can read a bar the venue has not finished aggregating, and `flow` is the only book that
reads the two fields finalised last.  `SETTLE_SECONDS` says so in the alert.  It gates nothing and
widens no tolerance: a cycle inside the window still fails to reproduce, it just also says why.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from starquant_alpha.ensemble import TargetWeights
from starquant_live.state import LiveState, StateStore
from starquant_live.verify import compare_targets, fetch_lag_seconds, last_scored_cycle

BAR = pd.Timestamp("2026-09-12T09:00:00Z")


def _pair_with_lag(recorded: dict, computed: dict, lag: float) -> dict:
    state = LiveState(
        last_bar_ms=int(BAR.timestamp() * 1000), last_contributions=recorded, last_targets={"BTCUSDT": 0.03}
    )
    targets = TargetWeights(as_of=BAR, weights={"BTCUSDT": 0.03}, contributions=computed, combined={})
    return compare_targets(targets, state, fetch_lag=lag)


def _pair(recorded: dict, computed: dict) -> dict:
    state = LiveState(
        last_bar_ms=int(BAR.timestamp() * 1000), last_contributions=recorded, last_targets={"BTCUSDT": 0.03}
    )
    targets = TargetWeights(as_of=BAR, weights={"BTCUSDT": 0.03}, contributions=computed, combined={})
    return compare_targets(targets, state)


def test_the_note_names_the_strategy_and_the_symbol_that_moved() -> None:
    """The real 2026-09-12T09:00 shape: one flow symbol, 3.3e-8, everything else bit-identical."""
    recorded = {"tsmom": {"BTCUSDT": 1.0, "TUTUSDT": -1.0}, "flow": {"TUTUSDT": -0.2057259135942554}}
    computed = {"tsmom": {"BTCUSDT": 1.0, "TUTUSDT": -1.0}, "flow": {"TUTUSDT": -0.2057259465942554}}
    result = _pair(recorded, computed)
    assert result["ok"] is False and result["bar_matched"] is True
    assert "flow/TUTUSDT" in result["note"], "the line that survives `tail -n 3` must carry the offender"
    assert result["worst_contributions"][0]["strategy"] == "flow"
    assert result["worst_contributions"][0]["symbol"] == "TUTUSDT"
    assert result["worst_contributions"][0]["diff"] < 1e-6


def test_the_offenders_are_ranked_worst_first_and_capped() -> None:
    """A config change moves everything; the operator needs the top of the list, not all of it."""
    recorded = {"tsmom": {f"S{i}USDT": 1.0 for i in range(10)}}
    computed = {"tsmom": {f"S{i}USDT": 1.0 + i / 100.0 for i in range(10)}}
    result = _pair(recorded, computed)
    diffs = [row["diff"] for row in result["worst_contributions"]]
    assert len(diffs) == 5, "capped so the alert line stays readable"
    assert diffs == sorted(diffs, reverse=True)
    assert result["worst_contributions"][0]["symbol"] == "S9USDT"


def test_a_faithful_reproduction_names_nobody() -> None:
    same = {"tsmom": {"BTCUSDT": 1.0}, "flow": {"TUTUSDT": -0.2}}
    result = _pair(same, same)
    assert result["ok"] is True and result["worst_contributions"] == []


def test_a_cycle_that_read_the_bar_too_early_says_so_without_being_excused() -> None:
    """The sentence six identical alerts could not say.  `ok` is still False."""
    recorded = {"flow": {"TUTUSDT": -0.2057259135942554}}
    computed = {"flow": {"TUTUSDT": -0.2057259465942554}}
    inside = _pair_with_lag(recorded, computed, 12.0)
    assert inside["ok"] is False, "diagnosing it is not forgiving it"
    assert inside["fetched_before_the_bar_settled"] is True
    assert "收盘后 12 秒取数" in inside["note"]
    assert "flow/TUTUSDT" in inside["note"]


def test_a_cycle_that_waited_gets_no_such_sentence() -> None:
    """A 39s cycle that stopped reproducing is a different event and must not borrow this excuse."""
    recorded = {"tsmom": {"BTCUSDT": 1.0}}
    outside = _pair_with_lag(recorded, {"tsmom": {"BTCUSDT": 0.5}}, 39.0)
    assert outside["fetched_before_the_bar_settled"] is False
    assert "收盘后" not in outside["note"]


def test_an_unknown_lag_asserts_nothing() -> None:
    result = _pair({"tsmom": {"BTCUSDT": 1.0}}, {"tsmom": {"BTCUSDT": 0.5}})
    assert result["fetch_lag_seconds"] is None
    assert result["fetched_before_the_bar_settled"] is None
    assert "收盘后" not in result["note"]


def test_the_lag_is_read_off_the_cycle_that_ran_the_model_not_off_a_restart(tmp_path: Path) -> None:
    """A restart writes a SKIPPED row with no contributions; its lag measures the restart, not the fetch.

    Measured 2026-09-12: the 12:04:40Z restart row read 280s off a bar that the 12:00:20Z cycle had
    traded 20s after close.
    """
    store = StateStore(tmp_path / "live")
    bar = int(pd.Timestamp("2026-09-12T11:00:00Z").timestamp() * 1000)  # closes at 12:00:00Z
    store.append_cycle({"bar_open_ms": bar, "at": "2026-09-12T12:00:20+00:00", "contributions": {"tsmom": {}}})
    store.append_cycle({"bar_open_ms": bar, "at": "2026-09-12T12:04:40+00:00", "phase": "SKIPPED"})
    scored = last_scored_cycle(store)
    assert scored is not None and scored["at"] == "2026-09-12T12:00:20+00:00"
    assert fetch_lag_seconds(scored) == 20.0
    assert fetch_lag_seconds(None) is None
    assert fetch_lag_seconds({"bar_open_ms": bar}) is None, "a row with no `at` says nothing"
