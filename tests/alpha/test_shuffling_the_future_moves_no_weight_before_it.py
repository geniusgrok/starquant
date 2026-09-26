"""Shuffle every bar after a cutoff, and no weight before it may move - one layer above the signals.

The signals already have this test (`test_signal_suite.py::test_signals_are_causal_and_bounded`,
`test_causality.py::test_tsmom_is_causal`).  Nothing had it for what sits on top of them: the stage-1
divisor and the EWMA covariance scalar, both caps and the no-trade band's recursion (`build_weights`),
the sleeve sum (`combine_books`), the cross-sectional reference population (`AlphaModel`), and the
guard replay inside `run_backtest`.  That is the most path-dependent code in the package - three
recursions (covariance, band, equity) and one population chosen bar by bar - and it was on the list
twice: the 2026-09-05 audit priced it at S
(`docs/analysis/2026-09-05-system-quality-deep-analysis.md` §6.3), and the 2026-09-23 checklist
carries it as G7 (`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`).

What every test here holds fixed, and why none of it is a look-ahead:

* The START of every frame.  Each recursion is anchored on the frame's first row: the covariance
  starts from zero, `ewm_vol` waits `vol_halflife` bars, the band starts flat, the replay's equity
  starts at 1.0.  Moving the start moves the warm-up, which is D-033's question and already has its
  own tests (`test_round6_hold_and_warmup.py`, `test_refit_boundaries_are_a_calendar_not_an_offset.py`).
  Only the future is perturbed here, so a difference can only have come from the future.
* The INDEX.  `refit_boundaries` puts HRP's re-clusters on a calendar anchored at the epoch, and
  measures the bar width as the modal gap of the WHOLE index - it reads future timestamps, by design:
  the grid is the calendar, not the data.  `_shuffle_future` perturbs values and never a timestamp.
* The execution lag.  `run_backtest` executes at t+1 what was decided at t, so the guarded book is
  compared THROUGH the cutoff bar, and the per-bar outcomes, which read the bar's own return, only
  before it.  The last test in this file shows what the inclusive bound catches that the other misses.
* `summary()`.  A Sharpe, a count of capped bars and `min_margin_buffer` are full-sample aggregates by
  definition, so nothing here compares a summary.  Every comparison is bar by bar.

Bit for bit, not "close".  pandas 3's `assert_frame_equal` defaults to rtol 1e-5, under which a leak
worth 1e-9 of a weight passes; `_bit_for_bit` asks for `check_exact` and then for the same 64 bits.

The construction is the live profile's with two numbers moved, not the live profile itself - see
`_construction` for the measurement that forces it.

What one cutoff cannot see, measured.  A leak that reaches one bar ahead touches exactly one compared
bar, the last before the cutoff, and shows only if that bar is sensitive to it.
`scratchpad/g7_planted_leaks.py` plants fourteen such leaks, one at a time, in a copy of the package,
and eleven turn this file red.  The three that pass each need something this cutoff's last bar lacks:

* the gross cap read through a centred window needs a bar under the 0.6 that four capped weights
  reach, and the bars around the cutoff all sit on it (caught at 30 of 79 cutoffs);
* the participation instrument read at the execution bar needs an order on the cutoff bar, and the
  pause holds every weight there (2 of 79);
* a scoring population one bar ahead needs a breakout that clears the entry threshold on the last bar.
  The one there scores 0.018 against 0.05, so the hold keeps the previous target whatever the
  population says (10 of 79).

A leak that reaches k bars ahead has k compared bars to show on.  Sweeping all 79 cutoffs would buy
these three, and costs about 40 s against this file's one second - a price to decide, not a default.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import BacktestResult, CostModel, ParticipationModel, run_backtest
from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams, asset_vol, build_weights, vol_targeted
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.breakout import BreakoutParams
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_live.composition import portfolio_params
from starquant_shared.config import load_yaml
from tests.alpha.test_causality import _bit_for_bit, _shuffle_future

ROOT = Path(__file__).resolve().parents[2]

#: 2026-08-17 19:00Z.  Not midnight, on purpose: the daily-loss pause keys on the UTC day, and a cutoff
#: that never splits a day cannot catch a replay that reads later in the same day.  This one falls in
#: the middle of a paused day (see the guard replay test), and the hour after an HRP re-cluster.
CUTOFF = 403

# The shipped tsmom needs 721 bars and August has 720; these are the hourly horizons `test_books.py` runs
# on this fixture, with the shipped `conviction_mode`.  The funding modifier stays off: August has none.
TSMOM = {
    **asdict(TsmomParams(vol_window=100)),
    "horizons": [5, 20, 50],
    "horizon_weights": [0.2, 0.3, 0.5],
    "conviction_mode": "sign",
}
# Breakout, because it is the registered signal that reads the reference population from OHLCV alone
# (its breadth).  The live sleeve, flow, needs taker-buy columns that August does not carry.
BREAKOUT = {**asdict(BreakoutParams()), "entry_threshold": 0.05}
MAIN = StrategyEntry("tsmom", params=TSMOM)
SLEEVE = StrategyEntry("breakout", params=BREAKOUT, book="sleeve")
SLEEVE_FRACTION = 0.333333  # the live `flow_short` book's

# Tighter than the construction's own caps, or the replay is the identity: neither guard can bind on a
# book that `build_weights` has already capped, and the shipped -5% pause never fires in this August.
# The identity cannot be caught reading anything.  Before the cutoff: 308 bars capped, 24 paused.
GUARDS = BookGuardParams(max_weight=0.15, max_gross=0.25, daily_loss_pause=-0.002)
COST = CostModel(turnover_bps=7.0)
# M-017's instrument runs inside the replay loop, so it is replayed too.  At 1e8 it refuses notional on
# 7 bars before the cutoff; at demo capital it would refuse none and prove nothing.
PARTICIPATION = ParticipationModel(capital=1e8, max_participation=0.02)


def _construction(**changes: Any) -> PortfolioParams:
    """The live profile's construction with two numbers moved, each because the rule it governs cannot bind here.

    `vol_target` 0.60 -> 0.10.  At 0.60 all four August symbols sit on `max_weight` 0.15 from their
    first decision - 2,468 of the 2,468 non-zero cells.  A weight pinned to the cap changes only by
    flipping sign, which the band always executes, so the band would never bind and a test of it would
    pass on any implementation.  `max_gross` 2.0 -> 0.5, because four weights capped at 0.15 are 0.6
    gross at most.  Before the cutoff the band now holds 1,054 weights (544 by its relative arm) and the
    gross cap moves 666.  Everything else - both half-lives, the band 0.005 / 0.40, flat-inside at 2.0,
    `max_weight` - is what the loop holds, read from the profile rather than copied.

    Not reached, and said so: flat-inside (D2/D3) is on, as shipped, and never binds before the cutoff.
    Its threshold is at most 1% of equity, and before the cutoff no single-book weight is below 6.9% and
    no two-book total below 1.6%.  It is a test on the current row alone, so it has nothing to read the
    future with - but that is an argument, and this file does not claim to have measured it.
    """
    live = portfolio_params(load_yaml(ROOT / "config" / "live.demo.yaml"))
    return replace(live, vol_target=0.10, max_gross=0.5, **changes)


def _perturb_after(frame: pd.DataFrame, cutoff: int, seed: int) -> pd.DataFrame:
    """`_shuffle_future`'s rule for a frame that is not a panel field: every row from `cutoff` on changes.

    Numeric rows are shuffled and scaled by U(0.5, 1.5), exactly as the panel's are.  A boolean table
    is redrawn instead, because shuffling the rows of a membership that is mostly all-true moves nothing.
    """
    rng = np.random.default_rng(seed)
    out = frame.copy()
    if all(pd.api.types.is_bool_dtype(dtype) for dtype in frame.dtypes):
        out.iloc[cutoff:] = rng.random(out.iloc[cutoff:].shape) < 0.5
        return out
    future = out.iloc[cutoff:].to_numpy(dtype=float).copy()
    rng.shuffle(future, axis=0)
    out.iloc[cutoff:] = future * rng.uniform(0.5, 1.5, size=future.shape)
    return out


def _moved_before(left: pd.DataFrame, right: pd.DataFrame) -> int:
    """Cells before the cutoff where two runs on the SAME data differ: how often the rule switched off binds."""
    return int((left.iloc[:CUTOFF].fillna(0.0) != right.iloc[:CUTOFF].fillna(0.0)).sum().sum())


def _trading_rows(weights: pd.DataFrame) -> int:
    return int(weights.iloc[:CUTOFF].fillna(0.0).abs().sum(axis=1).gt(0.0).sum())


def _main_targets(panel: Panel, params: PortfolioParams) -> pd.DataFrame:
    model = AlphaModel(entries=(MAIN,), portfolio=params, interval="1h", min_history_bars=0)
    return model.strategy_targets(panel)["tsmom"]


def _two_books(params: PortfolioParams) -> AlphaModel:
    return AlphaModel(
        entries=(MAIN, SLEEVE), portfolio=params, interval="1h", min_history_bars=0, books={"sleeve": SLEEVE_FRACTION}
    )


def _replay(panel: Panel, weights: pd.DataFrame) -> BacktestResult:
    return run_backtest(panel, weights, COST, guards=GUARDS, participation=PARTICIPATION)


@pytest.mark.parametrize("budget_mode", ["inverse_vol", "hrp"])
def test_no_stage_of_build_weights_moves_before_the_cutoff(august_panel: Panel, budget_mode: str) -> None:
    """Every stage, not only the output: the caps and the band are exactly the operations that hide a leak.

    A weight pinned at `max_weight`, or held by the band, reads the same whatever the scalar under it
    did, and a leak that reaches one bar ahead touches exactly one compared bar - the last before the
    cutoff.  The sleeve test below measured the consequence: a total that added the sleeve one bar
    ahead passed the banded comparison and failed the one before the band.  So `asset_vol` (stage 1's
    divisor), `vol_targeted` (stages 1-2) and the capped weights before the band are compared too.  Each
    is the public reader of the one implementation `build_weights` calls, so this is not a second copy
    of the construction.

    `hrp` is the arm that reads the calendar.  Its re-clusters sit on `refit_boundaries`, anchored at
    the epoch, here every 6 bars - 00:00, 06:00, 12:00, 18:00 UTC - so one of them is the last bar before
    the cutoff, and a re-cluster that read one bar past itself would read a shuffled one.  At a daily
    cadence the last re-cluster before the cutoff is 19 bars back, and the same leak passed.  GARCH,
    the other re-fitting option, is not an arm, because on this fixture it is empty: its first re-fit
    cannot come before row `min_obs` = 720 and August has 720 rows, so every forecast is NaN and every
    weight zero on both sides.  Its shuffled-future test runs on 12,000 bars in
    `test_construction_options_are_off_by_default.py`.
    """
    params = _construction(budget_mode=budget_mode, hrp_refit_bars=6)
    unbanded = replace(params, no_trade_band=0.0, no_trade_rel_band=0.0)
    bars_per_year = august_panel.bars_per_year
    targets = _main_targets(august_panel, params)
    shuffled_targets = _perturb_after(targets, CUTOFF, seed=1)
    shuffled_close = _shuffle_future(august_panel, CUTOFF).close

    stages = {
        "asset_vol": lambda conviction, close: asset_vol(close, params, bars_per_year),
        "vol_targeted": lambda conviction, close: vol_targeted(conviction, close, bars_per_year, params),
        "capped": lambda conviction, close: build_weights(conviction, close, bars_per_year, unbanded),
        "build_weights": lambda conviction, close: build_weights(conviction, close, bars_per_year, params),
    }
    for name, stage in stages.items():
        before, after = stage(targets, august_panel.close), stage(shuffled_targets, shuffled_close)
        _bit_for_bit(before.iloc[:CUTOFF], after.iloc[:CUTOFF])
        assert not before.iloc[CUTOFF:].equals(after.iloc[CUTOFF:]), f"{name}: the shuffle never reached it"

    # Non-vacuity, on the unshuffled data: switch each rule off and count what moves before the cutoff.
    def weights(switched: PortfolioParams) -> pd.DataFrame:
        return build_weights(targets, august_panel.close, bars_per_year, switched)

    shipped = weights(params)
    assert _trading_rows(shipped) > 250, "the comparison must be about positions, not about zeros"
    assert _moved_before(shipped, weights(unbanded)) > 500
    assert _moved_before(shipped, weights(replace(params, max_gross=100.0))) > 300
    if budget_mode == "hrp":  # the control arm is HRP with its tilt held at exactly 1
        assert _moved_before(shipped, weights(replace(params, budget_mode="inverse_variance"))) > 400


def test_summing_capping_and_banding_the_sleeves_moves_nothing_before_the_cutoff(august_panel: Panel) -> None:
    """D-018/D-019's path: each book sized alone, the sleeve gross-capped and scaled, the sum capped and banded.

    Compared per book (`book_weights`), on the capped total before the band (`band=False`) and on the
    banded total, for the reason the stages are compared above: `combine_books` clips the SUM at
    `max_weight` - 247 cells before the cutoff sit there - and the band holds most of the rest.  A total
    that added the sleeve one bar ahead passed the banded comparison alone (measured).
    `sleeve_max_gross` is P30's cap, off in the live profile and set to 0.3 here so that it binds.

    Only the conviction and the prices are shuffled; the signals are not in this test.  Their causality
    is the signal suite's, and keeping them out means a failure here can only be the book layer's.
    """
    params = _construction(sleeve_max_gross=0.3)
    bars_per_year = august_panel.bars_per_year
    model = _two_books(params)
    per_strategy = model.strategy_targets(august_panel)
    shuffled = {name: _perturb_after(frame, CUTOFF, seed) for seed, (name, frame) in enumerate(per_strategy.items(), 2)}
    shuffled_close = _shuffle_future(august_panel, CUTOFF).close

    books = model.book_weights(per_strategy, august_panel.close, bars_per_year)
    shuffled_books = model.book_weights(shuffled, shuffled_close, bars_per_year)
    assert set(books) == {"main", "sleeve"}
    for name, frame in books.items():
        _bit_for_bit(frame.iloc[:CUTOFF], shuffled_books[name].iloc[:CUTOFF])
    totals = {
        band: model.weights_from(per_strategy, august_panel.close, bars_per_year, band=band) for band in (False, True)
    }
    for band, total in totals.items():
        shuffled_total = model.weights_from(shuffled, shuffled_close, bars_per_year, band=band)
        _bit_for_bit(total.iloc[:CUTOFF], shuffled_total.iloc[:CUTOFF])
        assert not total.iloc[CUTOFF:].equals(shuffled_total.iloc[CUTOFF:]), "the shuffle never reached the total"

    # Non-vacuity: both books trade, their sum crosses the cap, and the sleeve cap, the total's gross cap
    # and the band each move weights before the cutoff.
    assert min(_trading_rows(frame) for frame in books.values()) > 250
    summed = books["main"].fillna(0.0) + books["sleeve"].fillna(0.0)
    assert int((summed.iloc[:CUTOFF].abs() > params.max_weight).sum().sum()) > 100

    def switched(**off: float) -> pd.DataFrame:
        return replace(model, portfolio=replace(params, **off)).weights_from(
            per_strategy, august_panel.close, bars_per_year
        )

    banded = totals[True]
    assert _moved_before(banded, switched(sleeve_max_gross=0.0)) > 500
    assert _moved_before(banded, switched(max_gross=100.0)) > 300
    assert _moved_before(banded, totals[False]) > 500


def test_the_guard_replay_decides_every_bar_through_the_cutoff_from_what_came_before_it(august_panel: Panel) -> None:
    """Three recursions - the held row, the equity, the UTC day's starting equity - across a cutoff inside a pause.

    The ranges are the substance.  The row executed at bar t was decided at t-1, and the equity the
    replay carries into t has seen returns through t-1, so the executed weights and every guard
    decision (`gross_capped`, `daily_loss_pause`, the participation instrument's notionals) are
    compared THROUGH the cutoff bar, and so are turnover and costs.  The per-bar outcomes read the bar's
    own return and are compared before it.

    Why the cutoff sits inside a pause.  The pause keys on the UTC day of the DECISION bar and on the
    equity that day started with.  On 08-17 it first fires at 07:00 and is still firing after the
    cutoff, so its bars through 19:00 are compared and 20:00-23:00 and 00:00 (decided at 23:00, the same
    day) are not.  A replay that set the day's threshold from anywhere later in that day would move the
    compared half; a cutoff at midnight would never see it.
    """
    params = _construction()
    weights = build_weights(_main_targets(august_panel, params), august_panel.close, august_panel.bars_per_year, params)
    before = _replay(august_panel, weights)
    after = _replay(_shuffle_future(august_panel, CUTOFF), _perturb_after(weights, CUTOFF, seed=5))
    assert before.guard_events is not None and after.guard_events is not None
    through = august_panel.index[CUTOFF]

    decisions = ["gross_capped", "daily_loss_pause", "desired_notional", "refused_notional"]
    _bit_for_bit(before.weights.loc[:through], after.weights.loc[:through])
    _bit_for_bit(before.guard_events.loc[:through, decisions], after.guard_events.loc[:through, decisions])
    _bit_for_bit(before.turnover.loc[:through], after.turnover.loc[:through])
    _bit_for_bit(before.costs.loc[:through], after.costs.loc[:through])
    for outcome in ("asset_returns", "gross", "net"):
        _bit_for_bit(getattr(before, outcome).loc[:through].iloc[:-1], getattr(after, outcome).loc[:through].iloc[:-1])
    margin = before.guard_events["margin_buffer"]
    _bit_for_bit(margin.loc[:through].iloc[:-1], after.guard_events["margin_buffer"].loc[:through].iloc[:-1])
    assert not before.weights.loc[through:].iloc[1:].equals(after.weights.loc[through:].iloc[1:])

    # Non-vacuity: both guards and the instrument bind before the cutoff, and the cutoff splits a pause.
    events = before.guard_events.loc[:through]
    assert events["gross_capped"].sum() > 250 and events["daily_loss_pause"].sum() >= 20
    assert (events["refused_notional"] > 0).sum() >= 5
    paused = before.guard_events.index[before.guard_events["daily_loss_pause"]]
    decided_on = (paused - pd.Timedelta(hours=1)).normalize()
    same_day = paused[decided_on == (through - pd.Timedelta(hours=1)).normalize()]
    assert same_day.min() < through < same_day.max(), "the cutoff has to fall inside a paused UTC day"


def _membership(panel: Panel) -> pd.DataFrame:
    """A point-in-time membership that moves before the cutoff: SOLUSDT joins at bar 150, BNBUSDT is out 250-329."""
    table = pd.DataFrame(True, index=panel.index, columns=panel.close.columns)
    table.iloc[:150, table.columns.get_loc("SOLUSDT")] = False
    table.iloc[250:330, table.columns.get_loc("BNBUSDT")] = False
    return table


def test_the_whole_book_with_a_moving_reference_population_cannot_see_past_the_cutoff(august_panel: Panel) -> None:
    """Panel and membership -> reference population -> targets -> books -> band -> guard replay, in one pass.

    The tests above shuffle what each layer is handed; this one shuffles only the raw inputs and lets
    every layer derive its own, the way a backtest does.  The input they do not cover is the reference
    population (P1-01 / DL-Q1): `eligible` intersects the listing-age filter with the point-in-time
    membership, and every cross-sectional operator ranks or averages over it bar by bar - breakout's
    breadth here.  Who is a member on 08-25 is as much a fact about the future as a price on 08-25, so
    the membership rows after the cutoff are redrawn along with the prices.
    """
    model = _two_books(_construction(sleeve_max_gross=0.3))
    membership = _membership(august_panel)
    shuffled_panel = _shuffle_future(august_panel, CUTOFF)
    weights, combined, per_strategy = model.evaluate(august_panel, membership)
    after, after_combined, after_per_strategy = model.evaluate(shuffled_panel, _perturb_after(membership, CUTOFF, 7))

    for name, frame in per_strategy.items():
        _bit_for_bit(frame.iloc[:CUTOFF], after_per_strategy[name].iloc[:CUTOFF])
    _bit_for_bit(combined.iloc[:CUTOFF], after_combined.iloc[:CUTOFF])
    _bit_for_bit(weights.iloc[:CUTOFF], after.iloc[:CUTOFF])
    through = august_panel.index[CUTOFF]
    guarded, after_guarded = _replay(august_panel, weights), _replay(shuffled_panel, after)
    _bit_for_bit(guarded.weights.loc[:through], after_guarded.weights.loc[:through])
    assert not per_strategy["breakout"].iloc[CUTOFF:].equals(after_per_strategy["breakout"].iloc[CUTOFF:])

    # Non-vacuity: the population is live before the cutoff.  Without the membership, breakout's targets
    # differ for the two symbols that were members all along - the breadth they are scored by changed.
    _weights, _combined, unreferenced = model.evaluate(august_panel)
    stayed = ["BTCUSDT", "ETHUSDT"]
    assert _moved_before(per_strategy["breakout"][stayed], unreferenced["breakout"][stayed]) > 0
    assert (per_strategy["breakout"]["SOLUSDT"].iloc[:150].fillna(0.0) == 0.0).all(), "a non-member holds nothing"


def test_a_one_bar_look_ahead_in_the_construction_is_caught_on_the_last_bar_before_the_cutoff(
    august_panel: Panel,
) -> None:
    """The harness has to be able to fail, and at the boundary - not only for a leak that reaches far.

    A construction sized on the NEXT bar's close is the smallest look-ahead there is.  It passes every
    comparison that stops one bar short and fails the one the tests above make, on bar CUTOFF-1: the
    first bar whose "next close" is a shuffled one.
    """
    params = _construction()
    bars_per_year = august_panel.bars_per_year
    targets = _main_targets(august_panel, params)
    shuffled_close = _shuffle_future(august_panel, CUTOFF).close

    def leaky(conviction: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
        return vol_targeted(conviction, close.shift(-1), bars_per_year, params)

    before = leaky(targets, august_panel.close)
    after = leaky(_perturb_after(targets, CUTOFF, seed=1), shuffled_close)
    _bit_for_bit(before.iloc[: CUTOFF - 1], after.iloc[: CUTOFF - 1])
    with pytest.raises(AssertionError):
        _bit_for_bit(before.iloc[:CUTOFF], after.iloc[:CUTOFF])


def test_a_book_executed_a_bar_early_passes_an_exclusive_bound_and_fails_the_inclusive_one(
    august_panel: Panel,
) -> None:
    """Why the guard replay is compared THROUGH the cutoff bar and not before it.

    Hand `run_backtest` its decisions one bar early and every bar executes the weight decided on its
    own close - trading on information the bar has not yet produced.  The one bar that leak reaches is
    the cutoff bar itself, so a comparison that stops before it passes, and the guard replay's own test
    would have passed with it.  The pause is on at the cutoff bar and the leak still shows.
    """
    params = _construction()
    weights = build_weights(_main_targets(august_panel, params), august_panel.close, august_panel.bars_per_year, params)
    before = _replay(august_panel, weights.shift(-1))
    after = _replay(_shuffle_future(august_panel, CUTOFF), _perturb_after(weights, CUTOFF, seed=5).shift(-1))
    through = august_panel.index[CUTOFF]
    assert before.guard_events is not None and before.guard_events.loc[through, "daily_loss_pause"]
    _bit_for_bit(before.weights.loc[:through].iloc[:-1], after.weights.loc[:through].iloc[:-1])
    with pytest.raises(AssertionError):
        _bit_for_bit(before.weights.loc[:through], after.weights.loc[:through])
