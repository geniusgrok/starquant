"""Exit overlay: stop-loss, trailing stop and take-profit in units of daily volatility.

Evaluated at bar close on closed bars only (never intra-bar; D-012).  Every
threshold is ``k`` daily standard deviations, where the unit is the symbol's
EWMA volatility scaled to one day - fixed at entry by default, or re-read
from the current bar under ``unit_mode="current"`` (EXP-EX3), which is the
only difference between the two modes - so the same ``k`` means the
same statistical distance on BTC and on a meme coin.  After an exit the same
direction is suppressed for ``cooldown_bars``; the opposite direction may
enter immediately.  Same-direction resizes keep the original entry.

``exit_step`` is the single source of truth for one symbol-bar, and the live
loop calls it per symbol with the venue's entry price as the reference.
``apply_exits`` runs the same machine over a whole weight frame for backtests,
through one of two engines: ``_run_stepwise`` calls ``exit_step`` per
symbol-bar and is the specification, ``_run_vectorised`` re-implements it over
numpy arrays (serial in bars, element-wise across symbols) and is what ships.
The second only exists because a test holds the two to bit-for-bit equality.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.features import apply_numpy, ewm_vol

STOP_LOSS = "STOP_LOSS"
TRAILING_STOP = "TRAILING_STOP"
TAKE_PROFIT = "TAKE_PROFIT"
COOLDOWN = "COOLDOWN"


@dataclass(frozen=True)
class ExitParams:
    stop_loss: float = 0.0  # k x sigma_1d adverse move from entry; 0 disables
    # EXP-SL1 (2026-09-17, operator ruling: 根治 `k_eff = min(k_sl, c/sigma)`).  A CEILING on the price
    # move `stop_loss` is allowed to ask for, as a fraction of the entry price; 0 - the shipped value -
    # disables it and is bit-identical, because the `> 0` guard skips the arithmetic entirely.
    #
    # **What it is, in one line.**  `k_eff = min(stop_loss, c / sigma)`, and that second term unfolds to
    # a plain percentage stop:
    #
    #     adverse >= c / sigma   <=>   (entry - price) * held / entry >= c
    #
    # So `c` says "however loud this symbol is, a move of `c` from entry stops it".  Below `c = 1` a
    # long's stop is therefore ALWAYS reachable, which is the whole point: `min_unit`'s comment derives
    # the bound `adverse <= 1/sigma` and this is the term that puts the threshold under it.
    #
    # **Measured before the number was chosen** (206 symbols x 5.7 years of 1h PIT bars, 6,315,054
    # symbol-bars with a finite sigma).  The unreachable set is `sigma > 1/6 = 0.1667`, which is
    # **138,386 symbol-bars = 2.191%** - not a corner case, and the same set is rescued by EVERY c < 1.
    # What the choice of c buys is therefore only how much EXTRA it tightens on positions whose stop was
    # already reachable:
    #     c=0.9  bites 2.801%  ->  0.61pp extra    c=0.6  bites  8.486%  ->  6.30pp extra
    #     c=0.8  bites 3.814%  ->  1.62pp extra    c=0.5  bites 14.084%  -> 11.89pp extra
    #     c=0.7  bites 5.517%  ->  3.33pp extra    c=0.3  bites 47.637%  -> 45.45pp extra
    # sigma's own distribution is why: p50 0.0486, p95 0.1209, p99 0.2505, p99.9 2.2050, max 2.4960.
    #
    # **Longs only** (operator ruling 2026-09-17).  A SHORT's `adverse` numerator is `(price - entry)`
    # and price has no ceiling, so a short never had an unreachable stop; a cap there would be pure
    # tightening for none of the rescue this rule is named for.  The first draft was symmetric and was
    # withdrawn on its own measurement: at c=0.9 the ONLY difference over 5.7 years was one KNCUSDT
    # short stopped 41 hours early - a behaviour change bought with zero benefit.  `_stop_threshold`
    # carries the predicate; both engines take it.
    stop_loss_price_cap: float = 0.0
    trailing_stop: float = 0.0  # k x sigma_1d retracement from the favourable extreme; 0 disables
    # EXP-AE3 (2026-09-17, operator ruling Q-CRITICAL = D).  How far a position must have gone in
    # PROFIT before `trailing_stop` is allowed to fire; 0 - the shipped value - arms it from entry,
    # which is what it has always done.  Off is bit-identical by construction rather than by argument:
    # `_armed` short-circuits on `<= 0` without reading the excursion at all, so the NaN-extreme path a
    # state read back from disk can take is untouched too.
    #
    # **This is the parameter the operator has been asking for, and the repository did not have it.**
    # `trailing_stop` alone measures the retracement from `extreme`, and `_enter` initialises `extreme`
    # to the ENTRY price, so `retrace >= adverse` holds on every bar: today's trailing stop fires while
    # a position is still losing, and does it EARLIER than `stop_loss`.  That is what makes
    # `k_tr <= k_sl` turn `stop_loss` into dead code - measured, `sl0/tr4/tp0` and `sl4/tr4/tp0` give an
    # identical 1.6132 over an identical 904 exits - and it is why `config/live.demo.yaml` says a future
    # trailing experiment must take `k_tr > 6`, and why EXP-AE1's third cell (`tr 2.0`) was withdrawn.
    # A rule that cannot tell a profit from a loss cannot protect a profit.
    #
    # An activation threshold changes exactly that one thing: with `trailing_activate > 0` the rule
    # cannot fire before the position has been that far ahead, so it no longer pre-empts `stop_loss` on
    # a position that never rallied, and `k_tr <= k_sl` stops being a way to switch the stop off.  What
    # it does NOT promise is that the exit is profitable - armed at +a and trailing by b > a still exits
    # below entry.  `docs/RESEARCH_LOG.md` 2026-09-08 recorded this shape as "仍未实现、未测"; it is now
    # implemented and still untested, which is EXP-AE3's job and not this field's.
    trailing_activate: float = 0.0
    take_profit: float = 0.0  # k x sigma_1d favourable move from entry; 0 disables
    cooldown_bars: int = 24
    vol_halflife: int = 48
    bars_per_day: int = 24
    # A FLOOR with no ceiling, and that asymmetry is the whole of what follows.  Every rule below
    # divides a price difference measured FROM the entry anchor by `sigma * entry_price`, and a long's
    # price cannot go below zero, so `adverse`'s numerator is bounded by the entry price itself:
    #
    #     adverse = (entry - price) * held / (sigma * entry),  price >= 0  =>  adverse <= 1 / sigma
    #
    # So a long's `stop_loss` is UNREACHABLE whenever `k_sl > 1/sigma`, however far the price falls -
    # the threshold is arithmetic, not protection.  The mirror holds for a short's `take_profit`; a
    # short's `stop_loss` and a long's `take_profit` have an unbounded numerator and no ceiling at all.
    # `min_unit` bounds sigma from BELOW so a dead-quiet series cannot make a one-tick stop.  Nothing
    # bounds it from above, so a loud enough symbol silently gets a threshold no price path can reach.
    #
    # This is not a new fact, it is the other half of a recorded one.  KILL-TL04 (2026-09-07,
    # `scratchpad/exit_reachability.py`; table in `docs/analysis/2026-09-07-exits-tail-endpoint.md`
    # 2.1) derived `retrace <= 1/sigma` on a long that never rallies and MEASURED what it costs:
    # trailing k=12 fires on 0 of 0 episodes book-wide, k=9 on 3 / 4.  `config/live.demo.yaml` states
    # the bridge between the two in the same block - "retrace >= adverse always holds", because
    # `_enter` initialises `extreme` to the entry price - so the `stop_loss` half follows from two
    # facts this repository already had, and was simply never written down on this side or read off
    # the live book.
    #
    # What it binds on today, over the 17 held positions in `.starquant/live/state.json`, 2026-09-17, at
    # the shipped `stop_loss` 6.0 (`unit_mode="entry"`, so these are the sigmas frozen at entry):
    #     LSKUSDT  sigma 0.4517  ceiling  2.21 sigma   <- below 6.0: no price path reaches this stop
    #     ZECUSDT  sigma 0.0603  ceiling 16.59 sigma      the next tightest, clearing 6.0 by 2.8x
    #     BTCUSDT  sigma 0.0156  ceiling 64.25 sigma      the loosest
    # One of seventeen, and it is the one whose sigma made inverse-vol sizing give it the smallest
    # weight in the book - the same input produces both, which is why a fix aimed at either alone
    # misses.  `starquant_live.reports.exit_reachability` takes this reading every day, so the next one
    # is found by the report rather than by an operator noticing a margin figure in a phone app.
    min_unit: float = 0.005  # floor on sigma_1d (fraction) so a dead-quiet series cannot make a 1-tick stop
    unit_mode: str = "entry"  # entry | current: which sigma_1d the k-units are measured in (EXP-EX3)
    regime_window: int = 0  # bars of Kaufman efficiency ratio; 0 disables the regime scaling (EXP-EX2)
    regime_er_cut: float = (
        0.05  # pre-registered constant: BTC's 7-day ER read 0.020 in the 2026-09 consolidation, 0.118 over 30 days
    )
    regime_tp_scale: float = 0.5  # take_profit multiplier inside the regime (6 -> 3)
    regime_side: str = "low"  # low: tighten when ER < cut (the operator's hypothesis); high: the mirror control arm
    # How many CONSECUTIVE bars with no usable close a held position is carried through before the
    # overlay gives it up.  A bounded wait, because the alternative is unbounded: a bar with no price
    # and a series that has ended are the same observation at the moment they happen, so "hold until
    # it comes back" holds a delisted symbol to the end of the panel (measured: 79,447 symbol-bars
    # across 150 ragged archive tails).  Telling the two apart needs `last_valid_index`, which reads
    # the future and would make a truncated panel disagree with a full one - T-X05 forbids exactly that.
    #
    # Why 2.  It is `guards.stale_bars_max` in `config/live.demo.yaml`, which is the loop's own
    # definition of "this data is too old to act on" (`pool.quarantine_after: 3` is the same shape one
    # level up).  Research and live disagreeing about when a symbol stops being tradable is KILL-027's
    # shape, so this reuses the loop's number rather than inventing a second one.  At 1h, two bars is a
    # data hiccup; three is a halt or a delisting.
    #
    # It still binds in research ONLY: `ExitOverlay.apply` skips a non-finite close before `exit_step`
    # is reached, so reusing the loop's number is an intent this file states and does not yet keep.  The
    # live half of the same question is `inputs.dropped_after`, and `construction.py`'s v6 note records
    # the operator's ruling that raising it is a priced decision rather than a side effect of a fix -
    # so the two are left disagreeing on purpose, and `starquant_live/staleness.py` is where all five
    # rules and which side each binds on are written down, with a test joining the table to the code.
    #
    # Corrected 2026-09-15: this comment said "not yet in `construction_fingerprint`" after v6 had put
    # it there.  Left as prose it went stale in two days, which is the argument for the table.
    #
    # What the bound costs, measured on the 1h PIT archive (scratchpad/
    # exit_gap_reanchor_blast_radius.py sweeps it).  The five gapped members' holes are runs of 518,
    # 72, 48, 24 and 7 bars, so the stop that the 2026-09-13 review reproduced - BNXUSDT at
    # 2023-02-22 14:00, swallowed by the 518-bar run - needs N >= 518 exactly (517 does not rescue it):
    #        N      ragged tail bars      in-span bars moved      that stop
    #        0                     0                       0      no
    #        2                   296                      20      no
    #       72                10,440                     552      no
    #      517                30,976                     997      no
    #      518                30,978                     998      YES
    #   unbounded              79,447                     998      YES
    # 518 bars at 1h is 21.6 days of holding a position nobody could price.  The operator gets to make
    # that trade; the default is the number the live guard already uses.
    stale_carry_bars: int = 2

    def __post_init__(self) -> None:
        if min(self.stop_loss, self.trailing_stop, self.take_profit) < 0:
            raise ValueError("exit thresholds must be >= 0")
        if self.trailing_activate < 0:
            raise ValueError("trailing_activate must be >= 0 (0 arms the trailing stop from entry)")
        if self.trailing_activate > 0 and self.trailing_stop <= 0:
            # The `turnover_penalty` precedent: a value that is parsed, hashed and read by nothing looks
            # adopted and is not.  Arming a rule that is switched off is that, so it is refused at the
            # door rather than left to be discovered in a report that says the setting was in force.
            raise ValueError(
                "trailing_activate arms `trailing_stop`, which is 0 here: the threshold would be parsed, "
                "hashed into the construction and read by nothing.  Set trailing_stop, or leave both at 0."
            )
        if self.cooldown_bars < 0 or self.vol_halflife <= 0 or self.bars_per_day <= 0 or self.min_unit <= 0:
            raise ValueError("invalid exit parameters")
        if self.stale_carry_bars < 0:
            raise ValueError("stale_carry_bars must be >= 0")
        if self.unit_mode not in {"entry", "current"}:
            raise ValueError("unit_mode must be 'entry' or 'current'")
        if self.regime_window < 0 or not 0 < self.regime_tp_scale <= 1 or not 0 <= self.regime_er_cut <= 1:
            raise ValueError("invalid regime parameters")
        if self.regime_side not in {"low", "high"}:
            raise ValueError("regime_side must be 'low' or 'high'")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExitParams:
        known = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        return cls(**known)

    @property
    def enabled(self) -> bool:
        return max(self.stop_loss, self.trailing_stop, self.take_profit) > 0


@dataclass(frozen=True)
class ExitState:
    """Per-symbol overlay state.  ``bar`` fields are opaque monotone integers (bar index or bar open ms)."""

    direction: int = 0  # sign of the held position; 0 = flat
    entry_price: float = math.nan
    extreme: float = math.nan  # best close since entry (max for longs, min for shorts)
    unit: float = math.nan  # sigma_1d (fraction) fixed at entry
    cooldown_until: int = -1  # exclusive
    cooldown_direction: int = 0
    stale_bars: int = 0  # consecutive unjudgable bars carried so far; reset by any bar with a price

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "entry_price": None if math.isnan(self.entry_price) else self.entry_price,
            "extreme": None if math.isnan(self.extreme) else self.extreme,
            "unit": None if math.isnan(self.unit) else self.unit,
            "cooldown_until": self.cooldown_until,
            "cooldown_direction": self.cooldown_direction,
            "stale_bars": self.stale_bars,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ExitState:
        def number(key: str) -> float:
            value = payload.get(key)
            return math.nan if value is None else float(value)

        return cls(
            direction=int(payload.get("direction", 0) or 0),
            entry_price=number("entry_price"),
            extreme=number("extreme"),
            unit=number("unit"),
            cooldown_until=int(payload.get("cooldown_until", -1)),
            cooldown_direction=int(payload.get("cooldown_direction", 0) or 0),
            stale_bars=int(payload.get("stale_bars", 0) or 0),
        )


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _unit_price(state: ExitState, sigma_1d: float, params: ExitParams) -> float:
    """The price distance one k-unit is worth on this bar.

    ``entry``: the sigma frozen when the position opened (D-012's definition - the same k is the same
    statistical distance, measured once).  ``current``: this bar's sigma, so the thresholds breathe with
    volatility - tighter when the market calms, wider when it wakes - which is what the Chandelier / ATR
    family does by default and what EXP-EX3 tests.  A missing current sigma falls back to the entry unit.

    Both modes multiply by ``state.entry_price``, never the current price: every comparison this feeds
    (``adverse``, ``favourable``, ``retrace``) has a numerator that is a price difference measured FROM
    the entry anchor, so dividing by ``sigma * entry_price`` yields "the move from entry, expressed in
    daily sigmas".  Using the current price in the denominator would silently mix two reference points -
    the numerator anchored at entry, the denominator anchored at now - and change what ``k`` means from
    bar to bar even under ``unit_mode="entry"``.
    """
    unit = state.unit
    if params.unit_mode == "current" and not math.isnan(sigma_1d) and sigma_1d > 0:
        unit = sigma_1d
    return max(unit, params.min_unit) * state.entry_price


def _armed(state: ExitState, extreme: float, unit_price: float, params: ExitParams) -> bool:
    """Has this position been far enough in PROFIT for the trailing stop to be live (EXP-AE3)?

    The excursion is measured from the entry anchor to the favourable extreme - the same two prices
    `retrace` is measured between, so the two thresholds speak one unit and `trailing_activate` reads
    as "arm at +a, then trail by b".

    ``<= 0`` returns True before the excursion is computed at all.  That is what makes the shipped
    value bit-identical rather than merely equivalent: a state whose `extreme` came back NaN from disk
    would otherwise compare NaN and silently switch the trailing stop off.
    """
    if params.trailing_activate <= 0.0:
        return True
    return (extreme - state.entry_price) * state.direction / unit_price >= params.trailing_activate


def exit_step(
    state: ExitState,
    target: float,
    price: float,
    sigma_1d: float,
    bar: int,
    params: ExitParams,
    *,
    bar_step: int = 1,
    tp_scale: float = 1.0,
) -> tuple[ExitState, float, str]:
    """One symbol, one closed bar: (new state, weight to hold from here, reason).

    ``target`` is the model's weight (already vol-targeted), ``price`` the bar
    close, ``sigma_1d`` the current daily vol (fraction).  ``bar_step`` is the
    increment of ``bar`` per bar (1 for indices, interval_ms for timestamps).
    ``tp_scale`` multiplies ``params.take_profit`` for this bar only (EXP-EX2's
    regime scaling); it defaults to 1.0, i.e. no scaling.

    A non-finite or non-positive ``price`` is a bar the overlay cannot judge.  For
    up to ``params.stale_carry_bars`` of them in a row it returns the state
    UNCHANGED (bar the counter) and a NaN weight, meaning "no decision - keep
    holding whatever you held"; callers translate that NaN.  Past the bound the
    position is given up: weight 0.0 and a flat state, never a new entry.
    """
    if not params.enabled:
        return replace(state, direction=_sign(target)), target, ""
    if not math.isfinite(price) or price <= 0:
        # A bar with no close carries no judgable information, so the overlay decides nothing here:
        # it does not exit, does not re-anchor, does not advance the trailing extreme, and does not
        # count the bar against a cooldown.  All it does is count how many of these have gone by.
        #
        # What it used to do, and what that cost (found 2026-09-13).  The only price guard was the
        # `price > 0` at the end of the `held != 0` condition just below, so a NaN close failed it,
        # fell PAST the whole exit block, and landed in `_enter` - which anchored a brand-new
        # ExitState at the NaN price, erasing the entry.  The next priced bar then found
        # `isnan(entry_price)`, missed the block for the same reason, and ran `_enter` a SECOND time,
        # putting the anchor on the far side of the gap.  Measured with stop_loss = take_profit = 6
        # and sigma_1d = 0.02, so one k-unit is 2.0 points off a 100.0 entry:
        #     no gap:      100, 100, 89, 87 -> 87 is 6.5 units adverse >= 6 -> STOP_LOSS, weight 0
        #     one NaN bar: 100, 100, nan, 89, 87 -> the nan bar re-anchors to nan, the 89 bar
        #                  re-anchors to 89, and 87 is only 1.0 unit adverse -> no stop, weight 0.1
        # So the stop was silently off for the whole segment after any internal gap.  Five PIT
        # members of the 1h archive carry internal gaps (1,005 symbol-bars); none is in the pinned
        # live universe, which is why this never reached the loop.
        if state.direction == 0:
            return state, math.nan, ""  # nothing held, so nothing to carry and nothing to give up
        if state.stale_bars < params.stale_carry_bars:
            return replace(state, stale_bars=state.stale_bars + 1), math.nan, ""
        # The wait ran out: treat the symbol as gone.  Flat, anchors dropped, cooldown left alone -
        # and deliberately NOT `_enter`, which is the bug this whole branch exists to prevent.  This
        # is a decision rather than an abstention, so it returns 0.0 instead of NaN.
        return ExitState(cooldown_until=state.cooldown_until, cooldown_direction=state.cooldown_direction), 0.0, ""
    if state.stale_bars:
        state = replace(state, stale_bars=0)  # a bar with a price ends the run, wherever it lands below
    if math.isnan(target):
        target = 0.0
    wanted = _sign(target)
    held = state.direction
    if held != 0 and not math.isnan(state.entry_price):
        extreme = max(state.extreme, price) if held > 0 else min(state.extreme, price)
        if math.isnan(extreme):
            extreme = price
        unit_price = _unit_price(state, sigma_1d, params)
        adverse = (state.entry_price - price) * held / unit_price
        favourable = -adverse
        retrace = (extreme - price) * held / unit_price
        reason = ""
        if params.stop_loss > 0 and adverse >= _stop_threshold(state.entry_price, unit_price, params, held):
            reason = STOP_LOSS
        elif (
            params.trailing_stop > 0 and retrace >= params.trailing_stop and _armed(state, extreme, unit_price, params)
        ):
            reason = TRAILING_STOP
        elif params.take_profit > 0 and favourable >= params.take_profit * tp_scale:
            reason = TAKE_PROFIT
        if reason:
            cooled = ExitState(
                direction=0, cooldown_until=bar + params.cooldown_bars * bar_step, cooldown_direction=held
            )
            return cooled, 0.0, reason
        if wanted == held:
            return replace(state, extreme=extreme), target, ""
        if wanted == 0:
            return ExitState(cooldown_until=state.cooldown_until, cooldown_direction=state.cooldown_direction), 0.0, ""
        # sign flip: a brand-new position in the other direction
        return _enter(state, wanted, price, sigma_1d, params), target, ""
    if wanted == 0:
        return replace(state, direction=0), 0.0, ""
    if bar < state.cooldown_until and wanted == state.cooldown_direction:
        return replace(state, direction=0), 0.0, COOLDOWN
    return _enter(state, wanted, price, sigma_1d, params), target, ""


def _stop_threshold(entry_price: float, unit_price: float, params: ExitParams, held: int) -> float:
    """`k_eff = min(stop_loss, c / sigma)` for a LONG; `stop_loss` untouched for a short.

    `unit_price` is `sigma_eff * entry_price` (the floored sigma the caller already resolved), so
    `c / sigma_eff` is `c * entry_price / unit_price` and no second sigma is read - the two engines
    divide by the same denominator or they stop agreeing.  `c <= 0` returns `stop_loss` untouched,
    which is what makes the shipped default bit-identical without a branch anywhere else.

    **Longs only, by operator ruling 2026-09-17, and the asymmetry is the point rather than an
    oversight.**  The bound this cap exists to get under is `adverse <= 1/sigma`, and it comes from a
    long's price floor of zero.  A short's `adverse` numerator is `(price - entry)` with no ceiling at
    all, so a short never had an unreachable stop and a cap there would be pure tightening for no
    rescue.  Measured on the symmetric draft before it was withdrawn: at c=0.9 the ONLY difference
    across 5.7 years was one KNCUSDT short, stopped 41 hours early - a change bought with none of the
    benefit the rule is named for.
    """
    if params.stop_loss_price_cap <= 0 or held <= 0:
        return params.stop_loss
    return min(params.stop_loss, params.stop_loss_price_cap * entry_price / unit_price)


def _enter(state: ExitState, direction: int, price: float, sigma_1d: float, params: ExitParams) -> ExitState:
    unit = sigma_1d if (not math.isnan(sigma_1d) and sigma_1d > 0) else params.min_unit
    return ExitState(
        direction=direction,
        entry_price=price,
        extreme=price,
        unit=max(unit, params.min_unit),
        cooldown_until=state.cooldown_until,
        cooldown_direction=state.cooldown_direction,
    )


def daily_vol(close: pd.DataFrame, params: ExitParams) -> pd.DataFrame:
    """EWMA per-bar vol scaled to one day (fraction), floored at ``min_unit``."""
    return (ewm_vol(close, halflife=params.vol_halflife) * math.sqrt(params.bars_per_day)).clip(lower=params.min_unit)


def efficiency_ratio(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """Kaufman's efficiency ratio over ``window`` bars: |net log move| / sum of |bar log moves|, in [0, 1]; NaN in the warmup."""
    logp = apply_numpy(close.astype(float), np.log)
    net = (logp - logp.shift(window)).abs()
    path = logp.diff().abs().rolling(window, min_periods=window).sum()
    return (net / path.where(path > 0)).clip(0.0, 1.0)


def regime_tp_scale(close: pd.DataFrame, params: ExitParams) -> pd.DataFrame | None:
    """Per symbol-bar multiplier on ``take_profit`` (EXP-EX2): ``regime_tp_scale`` inside the chosen regime, 1 elsewhere.

    ``regime_side="low"`` tightens the take-profit when the market is inefficient (the operator's "chop"
    hypothesis); ``"high"`` is the mirror control arm.  The cut is a pre-registered constant, never a rolling
    reference: the live loop only holds ~1,442 bars and a rolling median would make research and live
    disagree about the regime (KILL-027's shape).  Warmup bars scale nothing.
    """
    if params.regime_window <= 0:
        return None
    er = efficiency_ratio(close, params.regime_window)
    inside = (er < params.regime_er_cut) if params.regime_side == "low" else (er >= params.regime_er_cut)
    scale = pd.DataFrame(
        np.where(inside.to_numpy(), params.regime_tp_scale, 1.0), index=close.index, columns=close.columns
    )
    return scale.where(er.notna(), 1.0)


@dataclass
class ExitResult:
    weights: pd.DataFrame
    events: pd.DataFrame  # columns: time, symbol, rule, entry_price, price, units, direction

    def summary(self) -> dict[str, Any]:
        counts = self.events["rule"].value_counts().to_dict() if len(self.events) else {}
        return {"exits": len(self.events), "by_rule": {str(k): int(v) for k, v in counts.items()}}


# One exit, as the engines hand it back: (bar, column, rule, entry_price, price, units, direction).
# Both engines emit this and `_apply_exits` builds every event row from it in one place, so the two
# cannot disagree about a dtype or a cast - which is half of what "bit for bit" has to mean here.
_Event = tuple[int, int, str, float, float, float, int]
_Engine = Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray, ExitParams], tuple[np.ndarray, list[_Event]]]


def apply_exits(
    weights: pd.DataFrame, close: pd.DataFrame, params: ExitParams, *, sigma_1d: pd.DataFrame | None = None
) -> ExitResult:
    """Run the exit state machine over a decision-time weight frame (index = decision bars, columns = symbols)."""
    return _apply_exits(weights, close, params, sigma_1d, _run_vectorised)


def _apply_exits(
    weights: pd.DataFrame,
    close: pd.DataFrame,
    params: ExitParams,
    sigma_1d: pd.DataFrame | None,
    run: _Engine,
) -> ExitResult:
    """Align the frames, run one engine over them, and dress the result.

    Two engines, one definition of correct.  ``_run_stepwise`` calls ``exit_step`` once per symbol-bar
    and IS the specification - the live loop calls the same function per symbol, which is D-012's
    "the backtest loop and the live loop call the same exit_step".  ``_run_vectorised`` is a second
    implementation of that state machine over numpy arrays, and it is only allowed to exist because
    ``tests/alpha/test_the_vectorised_exit_engine_is_the_same_machine.py`` holds the two to bit-for-bit
    equality, events included.  Everything that turns arrays into frames lives here rather than in
    either engine, so the only thing the test has to compare is the state machine itself.
    """
    empty_events = pd.DataFrame(columns=["time", "symbol", "rule", "entry_price", "price", "units", "direction"])
    if not params.enabled:
        return ExitResult(weights.copy(), empty_events)
    aligned_close = close.reindex(index=weights.index, columns=weights.columns)
    vol = (sigma_1d if sigma_1d is not None else daily_vol(close, params)).reindex(
        index=weights.index, columns=weights.columns
    )
    values = weights.to_numpy(dtype=float)
    prices = aligned_close.to_numpy(dtype=float)
    vols = vol.to_numpy(dtype=float)
    scale_frame = regime_tp_scale(close, params)
    scales = (
        scale_frame.reindex(index=weights.index, columns=weights.columns).fillna(1.0).to_numpy(dtype=float)
        if scale_frame is not None
        else np.ones_like(values)
    )
    out, raw = run(values, prices, vols, scales, params)
    events = [
        {
            "time": weights.index[t],
            "symbol": weights.columns[j],
            "rule": rule,
            "entry_price": entry_price,
            "price": price,
            "units": units,
            "direction": direction,
        }
        for t, j, rule, entry_price, price, units, direction in raw
    ]
    frame = pd.DataFrame(out, index=weights.index, columns=weights.columns)
    return ExitResult(frame, pd.DataFrame(events) if events else empty_events)


def _run_stepwise(
    values: np.ndarray, prices: np.ndarray, vols: np.ndarray, scales: np.ndarray, params: ExitParams
) -> tuple[np.ndarray, list[_Event]]:
    """``exit_step`` once per symbol-bar.  Slow, obvious, and the reference the vectorised engine is held to."""
    out = np.full_like(values, np.nan)
    states = [ExitState() for _ in range(values.shape[1])]
    # The weight this overlay last emitted per symbol, which is what a gap bar keeps holding.
    # `out[t - 1, j]` would be the obvious source and is wrong in one case: an all-NaN row is skipped
    # below and leaves NaN in `out`, so a gap immediately after one would propagate that NaN into a
    # row where the other symbols carry real weights.  Carrying the last EMITTED weight instead is
    # the same value everywhere else and never invents a NaN.  It is always 0.0 while flat and
    # non-zero while held, so `direction != 0` below only makes that invariant explicit.
    #
    # Carrying rather than passing the model's target through is the whole point: on a gap bar the
    # target is 0 because `build_weights` filled a missing signal with 0, not because the model asked
    # to be flat, and obeying it would sell at the gap and buy back after it - turnover the live loop,
    # which cannot trade a bar it has no price for, would never have paid.  The carry is BOUNDED by
    # `params.stale_carry_bars`; the field's comment says why it has to be, and what the unbounded
    # version cost when it was measured (79,447 symbol-bars held to the end of the panel).
    carry = np.zeros(values.shape[1])
    events: list[_Event] = []
    for t in range(values.shape[0]):
        row = values[t]
        if np.all(np.isnan(row)):
            continue
        for j, state in enumerate(states):
            before = state
            new_state, weight, reason = exit_step(
                state, row[j], prices[t, j], vols[t, j], t, params, tp_scale=float(scales[t, j])
            )
            states[j] = new_state
            if math.isnan(weight):  # gap bar: `exit_step` had nothing to judge, so hold, do not trade
                weight = carry[j] if new_state.direction != 0 else 0.0
            out[t, j] = weight
            carry[j] = weight
            if reason and reason != COOLDOWN:
                unit_price = _unit_price(before, vols[t, j], params)
                units = float((prices[t, j] - before.entry_price) * before.direction / unit_price)
                events.append((t, j, reason, before.entry_price, float(prices[t, j]), units, before.direction))
    return out, events


def _run_vectorised(
    values: np.ndarray, prices: np.ndarray, vols: np.ndarray, scales: np.ndarray, params: ExitParams
) -> tuple[np.ndarray, list[_Event]]:
    """The same machine with the symbol loop replaced by element-wise numpy (P1).

    The state machine is serial in BARS - bar t reads the state bar t-1 left - but the symbols never
    touch each other: no branch reads another column, and the only cross-symbol object in sight,
    ``regime_tp_scale``, is computed per symbol-bar before the loop starts.  So the six ExitState
    fields become six arrays and each bar is one pass of element-wise work instead of one Python call
    per symbol.  On the 1h PIT panel (49,937 bars x 205 symbols, 10.2M symbol-bars) that is the
    difference between 15 s and about a second, and ``research overlay`` runs eleven of these.

    Every arithmetic expression below is written in the SAME order as its scalar twin, because "bit
    for bit" is the acceptance criterion and float addition is not associative.  The NaN conventions
    were checked rather than assumed: `max(nan, x)` in Python returns nan when nan is the FIRST
    argument (it keeps the left operand unless the right compares greater), which is what
    `np.maximum` does unconditionally, and `_unit_price` happens to put the possibly-NaN unit first.
    Every comparison against a NaN is False on both sides, which is what makes the `>=` thresholds
    agree without a mask.
    """
    n = values.shape[1]
    direction = np.zeros(n, dtype=np.int64)
    entry_price = np.full(n, np.nan)
    extreme = np.full(n, np.nan)
    unit = np.full(n, np.nan)
    cooldown_until = np.full(n, -1, dtype=np.int64)
    cooldown_direction = np.zeros(n, dtype=np.int64)
    stale = np.zeros(n, dtype=np.int64)
    carry = np.zeros(n)
    never = np.zeros(n, dtype=bool)
    out = np.full_like(values, np.nan)
    events: list[_Event] = []
    # `extreme` exists only to feed `retrace`, so with the trailing stop off nothing can read it and
    # the four operations that maintain it are dead weight - which matters, because the shipped
    # configuration IS trailing-off (stop_loss 6 / take_profit 6).  Skipping them leaves `extreme`
    # all-NaN, and that is unobservable: the engines are compared on weights and events, not on state.
    trailing = params.trailing_stop > 0
    moved = extreme
    # `_enter`'s unit, for every symbol-bar at once.  It reads nothing but this bar's sigma, so it does
    # not have to be recomputed inside the loop; one pass here costs one more array the size of `vols`
    # and takes five element-wise operations off every bar.
    entering = np.maximum(np.where(~np.isnan(vols) & (vols > 0), vols, params.min_unit), params.min_unit)
    # One errstate for the whole run rather than one per bar.  Entering the context is a pair of
    # `seterr` calls, which at 50k bars was about a fifth of the loop.  What it silences: the flat
    # symbols divide a NaN numerator by a NaN `unit_price`, and a +-inf price subtracts to NaN - both
    # are masked out below, and both would otherwise print a RuntimeWarning per bar.
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        for t in range(values.shape[0]):
            row = values[t]
            absent = np.isnan(row)
            if absent.all():
                continue
            price, sigma = prices[t], vols[t]
            target = np.where(absent, 0.0, row)  # `exit_step`'s `if isnan(target): target = 0.0`
            wanted = np.sign(target).astype(np.int64)
            held = direction
            # `exit_step`'s three gates, as masks: a bar it can judge, a position it is tracking, and
            # the rest.  `~np.isnan(entry_price)` can only matter for a state read back from disk, but
            # it is in the scalar condition so it is in this one.
            judgable = np.isfinite(price) & (price > 0)
            managed = judgable & (held != 0) & ~np.isnan(entry_price)
            idle = judgable & ~managed

            current = params.unit_mode == "current"
            measured = np.where(~np.isnan(sigma) & (sigma > 0), sigma, unit) if current else unit
            unit_price = np.maximum(measured, params.min_unit) * entry_price
            adverse = (entry_price - price) * held / unit_price
            favourable = -adverse
            # The scalar version is an if/elif/elif chain, so each rule only fires when the ones above
            # it did not.  The masks below are deliberately written that way even though `fired` is
            # their union either way, because the rule NAME is picked from them further down.
            # `_stop_threshold`, element-wise.  Guarded by the same `<= 0` short circuit for the same
            # reason `trailing_activate` is: at the shipped value the array is never built, so the two
            # engines agree bit for bit without this expression ever meeting a NaN entry price.
            k_stop: Any = params.stop_loss
            if params.stop_loss_price_cap > 0:
                capped = np.minimum(params.stop_loss, params.stop_loss_price_cap * entry_price / unit_price)
                k_stop = np.where(held > 0, capped, params.stop_loss)
            hit_stop = (adverse >= k_stop) if params.stop_loss > 0 else never
            hit_take = (favourable >= params.take_profit * scales[t]) if params.take_profit > 0 else never
            if trailing:
                moved = np.where(held > 0, np.maximum(extreme, price), np.minimum(extreme, price))
                moved = np.where(np.isnan(moved), price, moved)
                hit_trail = (moved - price) * held / unit_price >= params.trailing_stop
                # `_armed`, element-wise, and guarded by the same `<= 0` short circuit for the same
                # reason: at the shipped value the array is not touched, so the engines agree bit for
                # bit without the comparison ever meeting a NaN.
                if params.trailing_activate > 0.0:
                    hit_trail = hit_trail & ((moved - entry_price) * held / unit_price >= params.trailing_activate)
            else:
                hit_trail = never
            stopped = managed & hit_stop
            trailed = managed & ~hit_stop & hit_trail
            fired = stopped | trailed | (managed & ~hit_stop & ~hit_trail & hit_take)

            # What the bar does, as groups that cover every symbol.
            alive = managed & ~fired
            flat = wanted == 0
            holding = alive & (wanted == held)  # resize or stay: only the extreme moves
            closing = alive & flat  # the model went flat: drop the anchor, keep the cooldown
            blocked = idle & ~flat & (t < cooldown_until) & (wanted == cooldown_direction)
            # `idle & flat` and `blocked` both take `replace(state, direction=0)`, which leaves
            # entry_price / extreme / unit ALONE - unlike `fired` and `closing`, which clear them.
            # That asymmetry is in the scalar code and is preserved here rather than tidied away.
            opened = (alive & ~holding & ~flat) | (idle & ~flat & ~blocked)  # sign flip, or a fresh entry
            # The bounded wait, as two masks over the bars nothing can be judged on.  `giving_up` joins
            # the groups that clear the anchors and zero the direction, but NOT the ones that touch the
            # cooldown - running out of data is not an exit rule firing.
            stranded = ~judgable & (held != 0)
            carrying = stranded & (stale < params.stale_carry_bars)
            giving_up = stranded & ~carrying
            cleared = fired | closing | giving_up
            zeroed = cleared | blocked | (idle & flat)

            weight = np.where(holding | opened, target, 0.0)
            weight = np.where(carrying, carry, weight)  # inside the bound: hold, do not trade
            out[t] = weight
            carry = weight

            if fired.any():
                units = (price - entry_price) * held / unit_price
                for j in np.flatnonzero(fired):  # ascending, which is the scalar loop's column order
                    rule = STOP_LOSS if stopped[j] else (TRAILING_STOP if trailed[j] else TAKE_PROFIT)
                    events.append(
                        (t, int(j), rule, float(entry_price[j]), float(price[j]), float(units[j]), int(held[j]))
                    )

            cooldown_until = np.where(fired, t + params.cooldown_bars, cooldown_until)
            cooldown_direction = np.where(fired, held, cooldown_direction)
            stale = np.where(carrying, stale + 1, 0)  # any bar with a price ends the run
            direction = np.where(zeroed, 0, np.where(opened, wanted, held))
            entry_price = np.where(cleared, np.nan, np.where(opened, price, entry_price))
            unit = np.where(cleared, np.nan, np.where(opened, entering[t], unit))
            if trailing:
                extreme = np.where(cleared, np.nan, np.where(opened, price, np.where(holding, moved, extreme)))
    return out, events
