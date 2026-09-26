"""The instrument behind `test_suite_duration.py`: measure the suite's wall clock, and say so.

Kept out of `starquant_*` on purpose.  This exists to watch a budget; charging its lines to the source
budget it watches would be its own small joke, and the packages are already at their ceilings.

See `test_suite_duration.py` for why the ceiling is loose and the measurement is always printed.
"""

from __future__ import annotations

import time
from typing import Any

# The refactor plan's M-003 threshold.  Kept, not redefined: measured 45.3 / 47.0 / 47.1 on 2026-09-07.
PLAN_SECONDS = 30

# The ratchet.  Raising it is allowed only in the commit that explains why - the rule
# `test_source_budget.py` already runs under.  This is that explanation.
#
# 2026-09-08: 120 was `~2.5x today's laptop reading`, with "a CI box two to three times slower" as an
# ASSUMPTION.  It was never true.  `ubuntu-latest` has now been measured on six consecutive runs of
# this suite - 106.1 / 118.5 / 128.3 / 143.2 / 148.5 / 153.2 seconds against 46-47 on the laptop, i.e.
# a ratio of 2.3x to 3.3x, not 2-3x - so THREE of the five runs since this file landed were already
# over 120.  Nobody saw them: `suite_verdict` refuses to promote a timing breach over a real failure,
# and there was a real failure in every one of those runs (an "offline" test that reached
# fapi.binance.com, red on GitHub's geo-blocked runners).  Fixing that test is what made this visible
# - the second gate standing behind the first, which is the shape this repository keeps finding.
#
# 240 is 1.6x the slowest CI run observed and ~5x the laptop's.  Loose on purpose, and honest about
# what that buys: this number is set by the slowest machine the suite runs on, so on the laptop it
# catches almost nothing.  What it still catches is a STEP change on either box - a sleep, a
# quadratic fixture, a fixture that rebuilds the panel per test - which on this suite is tens of
# seconds, not the 20 that separated 120 from the observed spread.  Drift is the printed line's job,
# not this one's; that split is the whole design and is unchanged.
#
# The alternative considered and NOT taken: parallelising CI (`pytest -n auto`).  No longer an estimate
# - measured 2026-09-13 on this laptop with `pytest-xdist` installed for the measurement and removed
# again: 1,873 green on every run, 52.4s and 52.7s on two workers against 97.4s serial (1.87x), and
# 22.1s on sixteen.  So the flaky-under-parallelism risk this note used to assume is not there at the
# interleavings sixteen workers produce, and on GitHub's two cores CI would read about 180s.
#
# Still not taken, and now for a reason rather than a deferral:
#
# * it buys 2.6 minutes a push, against a four-day blindness that was caused by the gates being CHAINED
#   - a red `Types` skipped `Tests` entirely - and not by any of them being slow.  It optimises the
#   number nobody was hurt by;
# * the wall clock under `-n` is not the quantity this file's 120 -> 240 -> 400 series is made of, so
#   adopting it means re-baselining the ratchet, days after the ratchet earned its keep;
# * a flaky red in a repository whose subject is the difference between "it ran" and "it passed" costs
#   more than a slow green: it teaches the reader to re-run, which is how a real red gets ignored.
#   Three clean runs lower that risk.  They do not retire it, and two cores interleave differently from
#   sixteen, so CI would be the one place the measurement above does not cover.
#
# What the measurement does settle is the laptop, where it needs no decision from anyone and no change
# here: `pip install pytest-xdist && pytest -m "not network" -n auto` reads 22.1s, the first time
# M-003's 30s has been met on any box since it was written.  Deliberately left out of `requirements.lock`
# - a tool one person runs by hand is not a dependency this repository has to carry into CI.
#
# 2026-09-13: 340.5s on CI, the first reading since 09-08 - the Types gate had been red for 23 pushes
# and the test step never ran once, so this ratchet went four days without a measurement, the same
# blindness the 240 note describes one gate further up.  Two things came out of the breach:
#
# 1. A sleep, exactly as advertised.  `MetricsArchiveClient` had no `backoff` seam, so the two tests
#    that exercise its 5xx path each really slept 1+2+4s.  Fixed rather than budgeted for; the seam is
#    the one `onchain.CommunityClient` already carried.  Worth 14.0s on BOTH boxes - a sleep does not
#    get shorter on a faster machine, which is the error the first draft of this note made by scaling
#    it to ~42s on CI, and it is also why a sleep distorts this ratchet out of proportion to its cost:
#    it is the one thing measured here that does not shrink when the hardware works faster.
# 2. The rest is VOLUME, not a slowdown, and the numbers say so in the only way that settles it:
#
#      laptop 2026-09-07   46.5s /  847 tests = 54.9ms     CI 2026-09-08 (slowest)   153.2s = 180.9ms
#      laptop 2026-09-13   97.4s / 1873 tests = 52.0ms     CI 2026-09-13 (mean of 2) 330.1s = 176.3ms
#
#    All four measured, the 09-13 row a mean over three laptop runs and the two green CI runs.  Per
#    test it got cheaper on both boxes - 5.3% on the laptop, 2.5% on CI, which is inside CI's own
#    run-to-run spread and therefore only a claim that it did not get WORSE.  That is the whole point:
#    the suite grew 2.21x in tests since the 240 was set and its CI wall clock grew 2.16x, so the wall
#    clock tracked the test count and nothing else.  A ceiling that fires on growth measures the
#    repository's size, not its speed, which is not what this instrument is for.
#
# 400 was set before those green runs, against an estimate 23s low, and deliberately high enough to
# clear the 340.5s actually observed so a wrong estimate could not become a second red.  Two green CI
# runs have read it since - 321.4s and 338.9s, a 17.5s spread on identical work - so the headroom is
# 61.1s to 78.6s rather than the single 78.6s first recorded here, against the 86.8s the 240 carried
# over its own slowest reading.  Left at 400: tightening towards the faster of two readings would set
# the bar by the luckier run, and that 17.5s of noise is already a fifth of the headroom it would be
# trimming.  Two CI readings stand behind this number where six stood behind 240.
#
# 2026-09-16: 400 was breached at 400.3s - 1,939 passed, 2 skipped, and nothing else in the run was red.
# The ratchet was the only gate that fired, on a suite where every single test passed, and it fired on
# three tenths of a second.
#
# Twenty-two CI readings now stand where two stood behind 400.  They do not describe a suite that got
# slower.  They describe a box whose speed is not a constant:
#
#      2026-09-15   2,064-2,071 tests    207.2s .. 393.7s     100.0 .. 190.1 ms/test
#      2026-09-16   1,924-1,939 tests    267.9s .. 400.3s     138.3 .. 207.3 ms/test
#
# The pair that settles it: 09-15 ran 2,071 tests in 207.2s; 09-16 ran 1,939 tests in 400.3s.  One
# hundred and thirty-two FEWER tests, and the wall clock doubled.  Per test the spread on this single
# platform is 2.07x, and 1,939 x 207.3ms = 401.9s - so the breach is not an anomaly needing an
# explanation.  It is what this suite reads on the slow end of `ubuntu-latest`, and it was always going
# to be reached; the only question was which commit would be standing there when it was.
#
# That same number retires what 400 was trusted to do.  The 240 note above claims this gate catches a
# step change of "tens of seconds".  Against 193s of spread in the noise it cannot, and it could not at
# 400 either - a sleep worth 50s is indistinguishable here from a runner having an average morning.
# What a snug ceiling buys is therefore not sensitivity; it is a red light wired to the runner's luck,
# on an instrument whose own docstring says a gate that cries wolf gets deleted, returning us to no
# instrument at all.  600 is not blunter than 400 was.  It is 400 with the illusion removed.
#
# 600 = 1.50x the slowest reading ever taken (400.3s), against the 1.6x the 240 was set at over its own
# slowest.  It clears the observed spread with 200s to spare, and it still sits inside the job's
# `timeout-minutes: 15` - which is the honest backstop for a suite that has genuinely stopped
# terminating, and always was.
#
# What this does NOT fix: drift is now entirely the printed line's job, and that line prints a wall
# clock the table above just showed to be 2x noise.  The quantity that held still across both days is
# ms/test.  Putting it on the printed line is the follow-up this commit owes and deliberately does not
# pay - it changes `measurement_line`'s signature and the test that pins it, and this commit is the
# ceiling.
CEILING_SECONDS = 600

# Below this many selected tests the run was filtered (`pytest tests/live`, `-k`, `-m`), and a filtered
# run is not the thing the plan put a number on.  847 selected as of 2026-09-08 and 1,873 as of
# 2026-09-13, network markers: 0.  Left at 700: it is a floor under "was this the whole suite", not a
# second ratchet, and raising it with the count would make deleting tests fail the run.
FULL_SUITE_MIN = 700

_STARTED_AT: float | None = None


def set_limits(*, ceiling: float | None = None, full_suite_min: int | None = None) -> None:
    """Override the limits.  For the wiring test; the real conftest imports the hooks and nothing else."""
    global CEILING_SECONDS, FULL_SUITE_MIN
    if ceiling is not None:
        CEILING_SECONDS = ceiling
    if full_suite_min is not None:
        FULL_SUITE_MIN = full_suite_min


def measurement_line(duration: float) -> str:
    return f"suite: {duration:.1f}s (ceiling {CEILING_SECONDS}s; the plan's M-003 asked for {PLAN_SECONDS}s)"


def suite_verdict(*, duration: float, exitstatus: int, collected: int) -> tuple[int, str | None]:
    """`(exit status, message)`.  The message is the breach; `None` means there was nothing to say."""
    if collected < FULL_SUITE_MIN:
        return exitstatus, None
    if duration <= CEILING_SECONDS:
        return exitstatus, None
    message = (
        f"suite took {duration:.1f}s, over its {CEILING_SECONDS}s ceiling "
        f"(the plan's M-003 asked for {PLAN_SECONDS}s, breached since before it was measured). "
        "Make it faster, or raise CEILING_SECONDS in the commit that says why."
    )
    # Never promote a timing breach over a real failure: the operator reads the exit code first.
    return (exitstatus if exitstatus != 0 else 1), message


def pytest_configure(config: Any) -> None:  # the arg is unused; pytest matches hooks by name and signature
    global _STARTED_AT
    _STARTED_AT = time.monotonic()


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    if _STARTED_AT is None:
        return
    duration = time.monotonic() - _STARTED_AT
    collected = int(getattr(session, "testscollected", 0) or 0)
    status, message = suite_verdict(duration=duration, exitstatus=exitstatus, collected=collected)
    if collected >= FULL_SUITE_MIN:
        print("\n" + measurement_line(duration))
    if message:
        print(message)
    session.exitstatus = status
