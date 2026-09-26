"""When a symbol stops being tradable - all five rules, in one place, with which side each binds on.

There is no single rule.  There are five, they live in three packages, they carry three different
numbers, and two of them bind on only one side of the system:

    rule                     where                                   number              binds
    ------------------------ --------------------------------------- ------------------- --------------
    carry through gaps       starquant_alpha/overlays/exits.py          stale_carry_bars=2  research only
    skip the symbol          starquant_live/exits.py  (ExitOverlay)     unbounded           live
    hold, then flatten       starquant_live/engine.py (_hold_dropped)   dropped_after=1     live only
    skip the whole cycle     starquant_live/guards.py                   stale_bars_max=2    live only
    leave the pool           starquant_live/engine.py (_quarantine)     quarantine_after=3  live only

That spread is the finding.  On a bar a symbol cannot be priced on, research carries the position for
two bars with the stop live, and live zeroes the target - the model does not score an unpriced symbol,
`raw.setdefault(symbol, 0.0)` makes that a flat target, and the position is closed and re-opened next
cycle with the trailing anchor gone.  Two books.

**Why this module declares the rules instead of merging them.**

`starquant_alpha/overlays/exits.py` says, of `stale_carry_bars`: *"Research and live disagreeing about
when a symbol stops being tradable is KILL-027's shape, so this reuses the loop's number rather than
inventing a second one"* - and then, two lines later, that it binds in research only.  The intent was
right and the code did not keep it.  The repair is not to quietly make it bind: `dropped_after` is the
live half of the same question and `construction.py` records the operator's ruling on it in as many
words - it *"shipped at 3, which is a different book.  It ships at 1 instead ... raising it stays a
priced decision rather than a side effect of deploying a fix."*

So the values stay exactly where the operator put them, and what changes is that the disagreement is
now written down as data with a test behind it, rather than as prose that has already gone stale once:
the same comment still said `stale_carry_bars` was "not yet in `construction_fingerprint`" after v6
put it there.

**What the divergence costs today: nothing, and that is measured, not assumed.**  Over the 322 live
cycles on record, `inputs.dropped` is non-empty in 0 of them and `dropped_inputs` names a symbol in 0
of them.  The five PIT members of the 1h archive that carry internal gaps (1,005 symbol-bars) are none
of them in the pinned live universe, which is why the research side binds and the live side never has.
The divergence is latent, not active - which is the reason to price the flip rather than ship it.

**One correction to this table, 2026-09-17.**  `skip the whole cycle` was listed as binding on both
sides.  It does not and never has: `_replay_book_guards` carries no staleness branch, and D-036's
shared definition is `BookGuardParams`, which holds the caps and the daily-loss pause and not this.
The entry was wrong rather than the code - a backtest has no bar that arrived late - so the row now
reads `live only`, and `test_a_rule_that_claims_a_research_half_has_one` checks the claim against the
alpha-side parameter objects instead of only checking that the word is spelled correctly.  Worth its
own paragraph: a table written so that a wrong entry could be argued with carried a wrong entry for
as long as nothing read it back.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How many live cycles have been examined for the rule below, and how many of them it bound on.
#: Update both together; a frequency without its denominator is the kind of number this repo keeps
#: finding written down with nothing behind it.
LIVE_CYCLES_EXAMINED = 322
LIVE_CYCLES_WITH_DROPPED_INPUTS = 0


@dataclass(frozen=True)
class Rule:
    """One answer to "this symbol cannot be priced this bar"."""

    name: str
    #: What an operator sees.  Chinese, because `live status --check`'s output IS the hourly alert's
    #: body and `test_alerts_are_chinese` allows only three English tokens in it - the rule NAMES are
    #: code keys and stay English, so display needs its own field rather than reusing one.
    label: str
    module: str
    setting: str
    #: "research", "live", or "both".  The half of the system the rule actually changes.
    binds: str
    note: str


RULES: tuple[Rule, ...] = (
    Rule(
        name="carry through gaps",
        label="跨缺口保留",
        module="starquant_alpha.overlays.exits",
        setting="stale_carry_bars",
        binds="research",
        note=(
            "Hold the previous weight for N unjudgable bars with the stop still live, then give the "
            "position up flat.  `exit_step` implements it; the live adapter skips a non-finite close "
            "before `exit_step` is reached, so it does not run there."
        ),
    ),
    Rule(
        name="skip the symbol",
        label="跳过该标的",
        module="starquant_live.exits",
        setting="(none)",
        binds="live",
        note=(
            "`ExitOverlay.apply` continues past a symbol whose close is non-finite.  Unbounded and "
            "uncounted, and deliberately so in one respect: leaving the symbol out of `new_states` is "
            "what preserves the entry anchor, because the engine merges rather than replaces."
        ),
    ),
    Rule(
        name="hold, then flatten",
        label="保留后平仓",
        module="starquant_live.engine",
        setting="dropped_after",
        binds="live",
        note=(
            "Hold for `dropped_after - 1` cycles, flatten on the Nth.  At the shipped 1 the hold is "
            "zero cycles, which is the visible behaviour the operator chose; raising it is a priced "
            "decision (see CONSTRUCTION_ALIASES v6), not a side effect of a fix."
        ),
    ),
    Rule(
        name="skip the whole cycle",
        label="整周期跳过",
        module="starquant_live.guards",
        setting="stale_bars_max",
        binds="live",
        note=(
            "D-036 shares the two BOOK guards with the replay - the caps and the daily-loss pause - "
            "and this is not one of them.  It read `both` until 2026-09-17 on the strength of that "
            "neighbouring sentence; `_replay_book_guards` has never had a staleness branch and "
            "`BookGuardParams` has never carried this field.  The correction is the entry, not the "
            "code: there is no bar in a backtest that arrived too late.  This rule asks whether the "
            "newest CLOSED bar is more than N intervals behind the one the scheduler woke for - a "
            "question about a clock and a feed, and a panel is neither, since every row in it is "
            "present by construction.  So it binds live and has no research half to drift from, "
            "which is a different fact from a divergence and has to read as one."
        ),
    ),
    Rule(
        name="leave the pool",
        label="移出交易池",
        module="starquant_live.engine",
        setting="quarantine_after",
        binds="live",
        note=(
            "D-031: consecutive venue rejections, not missing data - the same shape one level up, and "
            "listed here so the five are counted together rather than found one at a time."
        ),
    ),
)


def rules_binding(side: str) -> tuple[Rule, ...]:
    """Every rule that changes what `side` ("research" / "live") does."""
    return tuple(rule for rule in RULES if rule.binds in {side, "both"})
