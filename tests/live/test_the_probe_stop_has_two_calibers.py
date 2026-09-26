"""The probe stop reads a quantity 17x quieter than the one it was calibrated against.

Operator ruling 2026-09-12 (option C of the EXP-G6′ close-out).  Measured, both of them:

    realised attributed income (what it reads)   30-day sigma 0.137% of equity -> -2% is 14.6 sigma
    mark-to-market (what its evidence is in)     30-day sigma 3.239%           -> -2% is  0.62 sigma

Neither is the "-2 sigma" D-019 claimed, and they miss in opposite directions.  Realised income only
moves when a position closes, and the no-trade band held 197 symbol-cycles on the day this was
measured - a sleeve can bleed on the mark for a month while that series barely moves.

The GATE is deliberately not moved here, and the reason is the plan's own rule: `max_loss` is inside
`construction_fingerprint` (`stop_of`), so changing it clears M-010's 30-day window (7.96/30 today) and
restarts M-G06's eighteen months.  §1 puts "changing the construction outside a window" out of scope.
The replacement is measured and waiting for 2026-10-03: the empirical 2.28% quantile of each book's own
30-day mark-to-market P&L, **-7.5%** for flow_short and **-11.2%** for main.
"""

from __future__ import annotations

from starquant_live.probe import ProbeParams, marked_pnl, probe_status

HOUR = 3_600_000
BASE = 1_789_000_000_000


def _cycle(index: int, weights: dict[str, float] | None, closes: dict[str, float] | None) -> dict:
    row: dict = {"bar_open_ms": BASE + index * HOUR}
    if weights is not None:
        row["book_weights"] = {"flow_short": weights, "main": {"BTCUSDT": 1.0}}
    if closes is not None:
        row["closes"] = closes
    return row


def _now(index: int) -> int:
    return BASE + index * HOUR


def test_the_marked_pnl_is_last_bars_weight_times_this_bars_return() -> None:
    """w_{t-1} . r_t, which is what the backtest measures and what the evidence is in."""
    cycles = [
        _cycle(0, {"BTCUSDT": 0.5}, {"BTCUSDT": 100.0}),
        _cycle(1, {"BTCUSDT": 0.5}, {"BTCUSDT": 110.0}),  # +10% on a 0.5 weight -> +5%
    ]
    out = marked_pnl(cycles, "flow_short", window_days=30, now_ms=_now(1))
    assert abs(out["value"] - 0.05) < 1e-12
    assert out["bars"] == 1


def test_a_short_window_understates_the_loss_rather_than_refusing() -> None:
    """For a STOP that is the safe direction - it can delay a stop, never cause one."""
    cycles = [
        _cycle(0, {"BTCUSDT": 1.0}, {"BTCUSDT": 100.0}),
        _cycle(1, {"BTCUSDT": 1.0}, {"BTCUSDT": 90.0}),
    ]
    out = marked_pnl(cycles, "flow_short", window_days=30, now_ms=_now(1))
    assert out["value"] < 0 and out["bars"] == 1, "one bar of a thirty-day window is still a reading"


def test_a_record_without_the_two_fields_reads_as_unreadable_not_as_zero() -> None:
    """Every cycle written before 2026-09-12 is this case, and zero would be a quiet false OK."""
    out = marked_pnl([_cycle(0, None, None), _cycle(1, None, None)], "flow_short", window_days=30, now_ms=_now(1))
    assert out["value"] is None and out["bars"] == 0
    assert "book_weights" in out["why"]


def test_a_symbol_priced_on_only_one_side_makes_no_claim() -> None:
    """A missing price is not a zero return; it is no statement about that symbol."""
    cycles = [
        _cycle(0, {"BTCUSDT": 1.0, "GONEUSDT": 1.0}, {"BTCUSDT": 100.0, "GONEUSDT": 5.0}),
        _cycle(1, {"BTCUSDT": 1.0}, {"BTCUSDT": 101.0}),  # GONEUSDT delisted mid-window
    ]
    out = marked_pnl(cycles, "flow_short", window_days=30, now_ms=_now(1))
    assert abs(out["value"] - 0.01) < 1e-12, "only BTC's return may be counted"


def test_bars_outside_the_window_are_not_counted() -> None:
    cycles = [_cycle(i, {"BTCUSDT": 1.0}, {"BTCUSDT": 100.0 + i}) for i in range(5)]
    inside = marked_pnl(cycles, "flow_short", window_days=30, now_ms=_now(4))
    narrow = marked_pnl(cycles, "flow_short", window_days=30, now_ms=_now(4) - 2 * HOUR)
    assert inside["bars"] == 4 and narrow["bars"] == 2


def test_the_gate_still_reads_the_realised_caliber_and_says_what_the_other_would_say() -> None:
    """The two disagreeing IS the finding, so both are reported and only one gates - for now."""
    params = ProbeParams(book="flow_short", strategy="flow", window_days=30, max_loss=0.02)
    attribution = [
        {"bar_open_ms": BASE + HOUR, "basis": "net_exposure", "by_strategy": {"flow": -1.0}}
    ]  # -0.01% of equity
    cycles = [
        _cycle(0, {"BTCUSDT": 1.0}, {"BTCUSDT": 100.0}),
        _cycle(1, {"BTCUSDT": 1.0}, {"BTCUSDT": 96.0}),  # -4% marked, past the -2% threshold
    ]
    status = probe_status(params, attribution, equity=10_000.0, now_ms=_now(1), cycles=cycles)
    assert status["stop"] is False, "the gate is the realised caliber until the batch window"
    assert status["marked_would_stop"] is True, "and it says the other caliber has crossed"
    assert status["marked_pnl_pct"] < -0.02
    assert status["status"] == "OK"


def test_a_real_realised_breach_still_stops_the_book() -> None:
    """The falsifier: adding a second reading must not disarm the gate that exists."""
    params = ProbeParams(book="flow_short", strategy="flow", window_days=30, max_loss=0.02)
    attribution = [
        {"bar_open_ms": BASE + HOUR, "basis": "net_exposure", "by_strategy": {"flow": -500.0}}
    ]  # -5% of equity
    status = probe_status(params, attribution, equity=10_000.0, now_ms=_now(1), cycles=[])
    assert status["stop"] is True and status["status"] == "STOP"
