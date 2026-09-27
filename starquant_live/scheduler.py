"""Bar clock: align cycles to interval boundaries (UTC) with a small grace period after the close."""

from __future__ import annotations

import asyncio
import time


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


def bar_open_ms(now_ms: int, interval_ms: int) -> int:
    return (now_ms // interval_ms) * interval_ms


def last_closed_bar_open_ms(now_ms: int, interval_ms: int) -> int:
    """Open time of the most recent bar whose close is already in the past."""
    return bar_open_ms(now_ms, interval_ms) - interval_ms


def next_close_ms(now_ms: int, interval_ms: int) -> int:
    return bar_open_ms(now_ms, interval_ms) + interval_ms


async def wait_for_bar_close(clock: object, interval_ms: int, grace_seconds: float = 5.0) -> int:
    """Sleep until the current bar closes (+grace).  Returns that bar's open time (the bar that just closed)."""
    now = clock.now_ms()  # type: ignore[attr-defined]
    target = next_close_ms(now, interval_ms) + int(grace_seconds * 1000)
    while True:
        now = clock.now_ms()  # type: ignore[attr-defined]
        remaining = (target - now) / 1000.0
        if remaining <= 0:
            break
        await clock.sleep(min(remaining, 60.0))  # type: ignore[attr-defined]
    return target - int(grace_seconds * 1000) - interval_ms


# --- DL-L4: a restart always reconciles, and only rebalances if it is still on time -------------


def rebalance_window_seconds(*, grace_seconds: float, throttle_interval: float, startup_seconds: float) -> float:
    """How late a restart may be and still act on the bar it missed.

    Derived, not chosen.  The 09-05 draft picked 120s and KILL-R6 showed what a picked number does:
    a 143-second catch-up would have become a 57-minute stale book.  The parts are the grace period
    the scheduler already waits after the close, launchd's ThrottleInterval (how long a relaunch can
    sit in the queue), and how long this process actually took to start - measured, not assumed.
    """
    return max(0.0, float(grace_seconds)) + max(0.0, float(throttle_interval)) + max(0.0, float(startup_seconds))


def within_rebalance_window(*, seconds_since_close: float, window_seconds: float) -> bool:
    """Inclusive at the boundary.  A negative age is host/venue clock skew (D-030), not earliness."""
    return float(seconds_since_close) <= float(window_seconds)


def late_seconds(bar_open_ms: int, interval_ms: int, *, at_ms: int) -> float:
    """How long after its bar closed something happened.  Never negative: earliness is not lateness."""
    close_ms = int(bar_open_ms) + int(interval_ms)
    return round(max(0.0, (int(at_ms) - close_ms) / 1000.0), 3)


#: What a restart that woke outside the rebalance window actually did.  Two reasons, not one, because
#: the two are different events with the same symptom: on 2026-09-10 a proxy 503 killed `exchangeInfo`
#: at startup and the loop woke 3135s after a close whose rebalance never happened, while ninety minutes
#: later an operator restart woke 125s after a close that had already been rebalanced with 18 fills.
#: M-Q03 counted both, so its `查重启原因` fired on a restart with no reason to look into.
MISSED_REBALANCE_REASON = "restart outside the rebalance window"
ALREADY_REBALANCED_REASON = "restart outside the rebalance window; this bar was already rebalanced"

#: The third way a bar goes untraded, and the one that was invisible until 2026-09-13.  A failed cycle
#: backs off 60s doubling to a 3600s cap (`LiveEngine.backoff_seconds`), so from the seventh
#: consecutive failure each sleep is a whole 1h bar and the running total by then is about 7,380s -
#: two bars.  Those bars get no ERROR row (the error belongs to the bar before), no SKIPPED row, and
#: did not reach `missed_rebalances`, while `config/live.demo.yaml` sets `max_missed_rebalances: 0`
#: (M-Q03).  A threshold of zero that one whole path cannot move is not a threshold.
#: It sits beside the two above because `restart_cost` charges every SKIPPED row that is not
#: ALREADY_REBALANCED_REASON, so naming it here is all the wiring a miss needs.
BACKOFF_REASON = "failure backoff slept through this bar's close"


def restart_reason(*, bar_open_ms: int, last_traded_bar_ms: int | None) -> str:
    """Which of the two a late restart is, decided by the record rather than by the clock.

    Equality only.  `None` is a loop with no history - a first start, or a state file that lost its
    bar - and a later bar in state means the two disagree about which bar this is; neither is evidence
    that THIS bar was traded, and absent knowledge does not excuse a miss.
    """
    if last_traded_bar_ms is not None and int(last_traded_bar_ms) == int(bar_open_ms):
        return ALREADY_REBALANCED_REASON
    return MISSED_REBALANCE_REASON
