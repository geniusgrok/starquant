"""R0-R10: every governance threshold, in one place, behind a version (R10).

Two properties this module exists to hold.

**Thresholds live in code, not in configuration.**  A YAML the machine can edit is a machine that
can move its own bar, and the whole argument for taking the human out of the runtime loop is that
the rules are fixed in advance.  Changing a number here changes `policy_digest()`, which changes
what the loop records every cycle (R9), which makes a silent drift impossible to hide.

**Every number says where it came from.**  `PROVENANCE` marks each rule 推导 (derived from a
mechanism), 先例 (an earlier operator decision this reuses) or E5 (a judgement call with no
evidence behind it).  Four of the eleven are E5 and saying so is the point: an unlabelled table
of constants reads as though somebody measured them.

The window is one month (Q3, operator ruling 2026-09-08).  Two of the numbers below are what they
are *because* of that ruling rather than independently: `windows_to_main` went 3 -> 9 and
`freeze_windows` 2 -> 6 to hold the pre-registered strength constant when the window shortened from
a quarter to a month.  `min_clean_days` equals the window exactly, which is why it is an admission
condition in `lifecycle` rather than a background assumption: `construction_fingerprint` includes
`strategy_weights` (`starquant_live/engine.py`, from `LiveConfig` over `registry.enabled`), so every
promotion resets M-010's 30-day clock, and a monthly window has zero slack against it.  A month is
an opportunity to promote, never an obligation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from starquant_alpha.overlays.ladder import rung_target

POLICY_VERSION = "0.3.5"
"""2026-09-25, no version change: the fifth mine round stands, by operator ruling.

0.3.1 opened a fifth round for the window 2026-09-03..2026-10-03 only, and wired a test to fail on
the day it expired unless somebody acted.  Asked before that day, the operator ruled the fifth round
standing ("5 轮常设").  So `STANDING_MINE_ROUNDS` moves 4 -> 5 and `max_mine_rounds_per_window` stays
5: the reversion test holds because the standing value moved, which is the path its own message
offers ("say so at POLICY_VERSION and move STANDING_MINE_ROUNDS, which is a decision rather than a
lapse").

Why the version does not move.  `version` is a `Policy` field, so it is inside `policy_digest()`, and
the live loop records that digest every cycle for `live status --check` to compare with this file.
No rule the machine enforces changed here - every `Policy` field keeps its value - so a new version
would move the digest and make the hourly check report, every hour until a restart, that the loop
runs stale rules.  That report would be false.  The ruling is written here instead, at POLICY_VERSION,
as the test asks.

What it costs is 0.3.0's argument unchanged: R1 is a rate limit, not the multiple-testing control.
A round is one selection event; every row it scores still enters the ledger and the family's N, and
the gate rises with N.  One more round per 30-day window buys search and spends power and compute.
R2 still refuses a round on an unchanged space, so five rounds cannot be one round five times.

0.3.3 (2026-09-14): R8's rungs re-derived for the -70% budget, and its ruler given the book's
unrealised P&L.  One decision in two halves - see `drawdown_ladder` for why they cannot ship apart.
The short version: measured over 2021-2026 at k=0.60 the ladder as it stood NEVER FIRED, because the
ruler counted only realised P&L while a momentum book holds its losers; and the rungs it would have
fired at were calibrated for a 50% budget the operator replaced with 70% when k doubled.  Fixing
either alone gives the wrong book - the ruler alone silently buys a 20.5pp/yr brake nobody chose, the
rungs alone re-tune something inert.  Evidence and the priced alternatives:
docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md.

0.3.1 (2026-09-10): ONE extra mine round, for the window 2026-09-03..2026-10-03 only.

4 -> 5 rounds.  Not a standing increase, and the difference is enforced rather than promised: the
reversion has a date and a test that fails on it (`test_the_single_window_mine_opening_is_returned`).
A "just this once" with no executing check is the thing the 2026-09-09 audit spent a day counting.

Why the round: the 09-09 round enumerated 658 shapes with `include_basis=False`, not by choice but
because `com.starquant.data` started writing `spot_klines` at 17:20:15Z and `research mine` loaded its
panel about a minute later - so `searched_basis = panel.spot_symbols > 0` read False, and the 18 basis
shapes were never enumerated.  The first of the run's own 18 universe symbols got its spot parquet at
17:25:50Z, nine seconds after the shortlist was written.  The two jobs raced; the mine won.

What it costs, priced before the ruling rather than after: 243 candidates (the space with `metrics`,
`funding`, `seasonality` and `panel_nodes` off, which is the narrowest space the enumerator can make
that still holds all 18 basis shapes), so the `mined` bucket goes 2,488 -> 2,731 and the D-028 gate at
that bucket goes 1.7990 -> 1.8085.  225 of the 243 were scored on 09-09 and are charged again; the
enumerator has no single-family mode, and pretending 18 rows were spent when 243 hypotheses were
enumerated would be the ledger lying in the direction that flatters us.

R1 also became a real gate the same day.  `research mine` had never asked it - `mine_refusals` existed,
`governance next` printed the number, and the only command that can spend a round imported neither.
So this opening is what authorises the run, rather than a gap being what permits it.

0.3.0 (2026-09-09): R1's budget opened, by operator ruling.  0.2.0's note follows below.

The ruling ("放开限制") is legitimate on R1's own terms and it is worth saying why, because the
first thing I told the operator about it was wrong.  I called loosening R1 "relaxing a threshold to
accommodate one's own change - the thing this whole apparatus exists to prevent."  Two facts say
otherwise:

* **R1's provenance is E5** - a judgement call, anchored on "one mine round cost 514 rows" and then
  set to ~500 a quarter.  It was never derived from evidence, so an operator setting it differently
  is not overruling a measurement.
* **R1 is a rate limit, not the multiple-testing control.**  R0's quantile gate is that, every trial
  still enters the ledger and the per-strategy N, and the gate rises MONOTONICALLY with N - measured
  at a fixed Sharpe variance: N=146 -> 0.1072, N=677 -> 0.1198, N=3000 -> 0.1310.  Searching more
  therefore makes the bar higher, automatically, with no rule needing to notice.  What opening R1
  costs is statistical power and compute.  It does not open a hole.

170 -> 1700 rows and 1 -> 4 mine rounds per 30-day window.  Finite on purpose rather than removed:
AC-G8 asks that an exhausted budget stops `validate`, and a cap of "none" would delete that check
along with the limit.  R2 (a mine needs a changed space) and R3/R4/R5 (exposure) are untouched -
they are what actually bound what reaches the book.

0.2.0 (2026-09-08): R1 charges a mine ROUND as one event rather than as its row count.

Why it moved.  R1's budget was anchored on "one mine round cost 514 rows" and then set to 500 a
quarter - so under Q3's monthly window it became 170, which is a THIRD of a single round, and
`refusals` refuses whole rather than truncating (a truncated search reports a `declared_trials`
counting candidates nobody scored).  R1 + R2 + the scheduler therefore made `research mine`
impossible to run at all, in any window, forever.

The fix is not a bigger number.  R1 exists to bound how many SELECTIONS a window makes, and one mine
round is one selection - enumerate the whole space, take the top k by marginal - not 514 independent
ones.  That is exactly why `ledger_scope` files them into one shared `mined` bucket.  Charging by row
count penalises searching MORE THOROUGHLY as though it were choosing more often, which is backwards.

The DSR denominator is untouched: it still counts every row in the mined bucket, because the deflation
question really is "best of how many", and that number really is 514.
"""


#: The standing number of mine rounds per window, and when 0.3.1's one-window opening was due to close.
#: 4 from 0.3.0; 5 from 2026-09-25, when the operator made the opened round standing (no version change;
#: see POLICY_VERSION).
STANDING_MINE_ROUNDS = 5
SINGLE_WINDOW_MINE_OPENING_ENDS = "2026-10-03T00:00:00+00:00"


@dataclass(frozen=True)
class Policy:
    """R0-R10.  Frozen: a rule set that can be mutated after a decision is not a rule set."""

    # --- the calendar every other rule counts in (Q3) ---
    window_days: int = 30

    # R0: which trials the D-028 quantile gate counts.  Not a number - a caliber.  The per-strategy
    # bucket (`ledger_scope`) stays the gate; the whole-library N and N_eff are reported beside it.
    # Deriving the gate from the whole library would FAIL the incumbent on an honest grid (KILL-AR-01),
    # and N_eff can only lower the bar (`multiple_testing.effective_trials` is documented as reported,
    # never substituted).  Family-level risk is controlled on the exposure side by R3/R4/R5 instead.
    gate_scope: str = "per_strategy_bucket"
    report_whole_library_n: bool = True

    # R1: new ledger rows per window, EXCLUDING the shared `mined` bucket.  E5 throughout: ~500 a
    # quarter, anchored on one `research mine` round costing 514 rows - which is also why that round
    # is no longer charged here (0.2.0).  Opened 170 -> 1700 by operator ruling (0.3.0); the reason
    # it is a rate limit rather than the integrity control is written at POLICY_VERSION.
    max_ledger_rows_per_window: int = 1_700
    # ...and the mine rounds themselves, counted as events: enumerating the whole space and taking
    # the top k by marginal is ONE choice, however wide the space was.  One per window until 0.3.0,
    # four after it - roughly weekly inside a monthly window.  R2 still refuses a space that has not
    # changed, so four rounds cannot become the same round four times.
    #
    # 5 was opened for the window ending `SINGLE_WINDOW_MINE_OPENING_ENDS` only (0.3.1), with a test that
    # fails from that date until the number and `STANDING_MINE_ROUNDS` agree - because "just this once"
    # without an executing check is a promise.  On 2026-09-25 the operator made it standing, so
    # they agree by `STANDING_MINE_ROUNDS` moving to 5, not by this going back to 4.
    max_mine_rounds_per_window: int = 5

    # R2: `research mine` runs only when the search space changed.  Re-running the same space and
    # keeping the rows charges the family twice for one hypothesis (the 2026-09-08 incident).
    mine_requires_new_search_space: bool = True
    # R2b: `research mine` also stops when another round could not produce an admissible candidate.
    # Not a threshold - both sides are measurements (`gate_has_passed_the_space`), which is why the
    # rule may sit in `scheduler` at all.  Switchable here because a rule with no off switch is one
    # nobody can price; turning it off resumes exactly the 2026-09-09 behaviour, which is the point.
    mine_requires_gate_below_best: bool = True
    # R0, caliber ④ (operator ruling 2026-09-14, on Q4c): `range_end` folds to this many days before
    # two rows are compared.  A signal reads only data up to bar t, so the same expression over the
    # same start, symbols and construction gives an IDENTICAL stream on the shared index when the range
    # ends a few days later - zero added independence, by arithmetic.  Not a reason to drop the field:
    # the same holds for two years later, and that is a second look.  7 because it folds least among
    # the granularities that fold the observed case at all - and the choice is not load-bearing here,
    # 7 / 14 / 30 all give `mined` 1,559, `tsmom` 101, `flow` 43.  0 restores the pre-ruling rule.
    trial_range_end_granularity_days: int = 7

    # R3: how much of the book unproven sleeves may move.  D-018/D-019's shape, unchanged.
    max_concurrent_probes: int = 2
    probe_budget_share: float = 1.0 / 3.0

    # R4: promotions per window.  One in, one up: the binding constraint is R3's two probe slots.
    max_queued_to_probe_per_window: int = 1
    #: How §3's "队首" is decided.  FIFO by the instant a candidate entered QUEUED, which is the
    #: definitional reading of a queue and the only one that needs no further judgement: ordering by
    #: marginal Sharpe, by evidence date or by fraction is a SELECTION rule, would need its own
    #: pre-registration, and would let a candidate improve its place by being re-scored.  Recorded
    #: here rather than left implicit in `Book.queue` so that changing it is a rule version change
    #: (R10) with a moved digest, not an edit.  Until 2026-09-12 no order was stored at all and the
    #: gate refused outright whenever two candidates were queued.
    queue_order: str = "fifo"
    max_probe_to_main_per_window: int = 1

    # R5: consecutive stopped probes that freeze promotion, and for how long.  Six windows is the
    # same six months two quarters used to be.
    freeze_after_consecutive_stops: int = 2
    freeze_windows: int = 6

    # R7: a candidate gets three lives.  After leaving probe the third time it is retired for good.
    max_probe_entries_lifetime: int = 3
    demotion_cooldown_windows: int = 1

    # probe -> main: nine consecutive surviving windows.  The pre-registered number was three, when a
    # window was a quarter; nine months of survival is the same filter.  Calibrated against D-019's
    # -2 sigma stop (E5, normal approximation, windows treated as independent): a Sharpe-0 sleeve
    # reaches main 81.0% of the time, a Sharpe-1.7 sleeve 94.4%.  Both numbers are weak, and that is
    # the honest description of the rule: it separates blown-up from not-blown-up, not alpha from noise.
    windows_to_main: int = 9

    # The clean-record requirement a promotion must find already satisfied, and which it then resets.
    min_clean_days_before_promotion: int = 30

    # R8: the drawdown ladder, on the BOOK's P&L rather than venue equity - 52% of this account's
    # equity is non-USDT collateral, so an equity drawdown can be bitcoin moving and nothing else.
    # The first crossing alerts and waits two cycles before acting, so one bad print cannot halve
    # the risk budget.
    #
    # 2026-09-14, and both halves of this change are one decision (operator, options priced):
    #
    # (a) the RUNGS are re-derived for the -70% budget the operator declared when k went to 0.60.
    #     They are the shipped rule transcribed, not a new rule: `deescalate_at` = 70% of budget,
    #     `rollback_at` = budget, `deescalate_to` = 75% of k, `rollback_to` = 50% of k.  At k=0.60 and
    #     budget 70% that is ((-0.49, 0.45), (-0.70, 0.30)).  The old numbers were calibrated at
    #     k=0.30 against a 50% budget and, left alone, would have de-risked at -35% - far inside the
    #     budget the operator chose in order to buy return, at a measured median cost of 20.5pp of
    #     CAGR (`p32d`, both universes).  The rescaled ladder costs 0.4pp and lands q95 at -66.5%,
    #     inside the declared -70%.
    #
    # (b) the RULER now includes the book's unrealised P&L (`risk_budget.attributed_drawdown_state`),
    #     because excluding collateral repricing - which is what KILL-AR-05 asked for and is still
    #     true - never required excluding the book's own open positions, and excluding them made this
    #     ladder INERT: measured over 2021-2026 at k=0.60, the mark-to-market ruler spends 785 bars
    #     past the first rung and the income-only ruler spends 0.  Five years and seven months, zero
    #     firings.  See docs/analysis/2026-09-14-backtest-guard-k060-ladder-audit.md.
    #
    # They move together on purpose.  Fixing the ruler alone would have made the OLD rungs bite for
    # the first time, i.e. silently adopted the 20.5pp arm the operator did not choose; re-scaling the
    # rungs alone would have re-tuned a ladder that never fires.
    drawdown_ladder: tuple[tuple[float, float], ...] = ((-0.49, 0.45), (-0.70, 0.30))
    drawdown_grace_cycles: int = 2

    # R9 / R10: the digest is recorded every cycle, and it is what makes an edit here visible.
    record_digest_every_cycle: bool = True

    # Cycles that produce no governance decision at all (KILL-AR-20).  A demo account reset arrives
    # as a TRANSFER row with no fills; the path to the venue crosses a proxy that returns 503 in
    # bursts.  Counting either as evidence would let the venue's plumbing retire a strategy.
    no_decision_phases: tuple[str, ...] = ("ERROR",)
    no_decision_on_rebaseline: bool = True

    version: str = field(default=POLICY_VERSION)

    def digest(self) -> str:
        """R9's number: what the live loop records so a threshold change cannot be silent."""
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]

    def throttle_scalar(self, drawdown: float) -> float | None:
        """The vol target the ladder asks for at this drawdown, or None above the first rung.

        The NUMBERS are this table's (R10: a threshold the machine can edit is not a threshold).  The
        RULE is `starquant_alpha.overlays.ladder`'s, because the backtest has to be able to replay it and
        cannot import this package - the same division D-036 already makes for `clamp_book`.  Four
        hand-written replays in `scratchpad/` existed because there was nothing to call.
        """
        return rung_target(drawdown, self.drawdown_ladder)


#: Where each rule comes from, so nobody reads the table above as measurement (KILL-AR-13).
PROVENANCE: dict[str, str] = {
    "R0": "推导 - whole-library N fails the incumbent on an honest grid; N_eff only lowers the bar",
    "R1": "E5 - anchored on one mine round costing 514 rows, no evidence that 170 is the right ceiling",
    "R2": (
        "先例 - K-EX07's shape: whether a replay's rows stay is a ruling, not the command's choice.  "
        "R2b (`mine_requires_gate_below_best`) is filed here rather than as an eleventh rule because it "
        "is the same question - may this round be enumerated - answered from a second measurement: 推导, "
        "the D-028 gate rises monotonically in N, so once it passes the space's best OOS Sharpe another "
        "round can only raise it further.  No threshold of its own; both sides are read off artefacts"
    ),
    "R3": "先例 - D-018/D-019, and flow already holds one of the two slots",
    "R4": "E5 - one promotion a window is a pace, not a measurement",
    "R5": "E5 - k=2/n=6; the false-stop rate is what EXP-G6' is for",
    "R6": "推导 - KILL-Q15: the engine builds its model once at startup, so a write needs a rollback",
    "R7": "E5 - three lives is a judgement call",
    "R8": "先例 (P13's ladder) + 推导 (KILL-AR-05: attributed P&L, not equity)",
    "R9": "推导 - the registry-digest instrument that closed KILL-Q15, applied to the policy",
    "R10": "推导 - a machine that can edit its own thresholds has no thresholds",
}


def policy_digest(policy: Policy | None = None) -> str:
    return (policy or Policy()).digest()
