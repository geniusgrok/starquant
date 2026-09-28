"""One manually started research session. It polls, then it exits.

``python -m btc_perp`` does not construct this object. ``--measure`` starts a
new session for each slice of the clock, waits until that session returns, and
only then starts the next one. Protections placed here live on the in-process
``SimExchange`` object and stay there after ``run`` returns. Nothing in this
module sends a live order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from btc_perp.exchange import AccountView, SimExchange


class Clock:
    def now(self) -> float:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class ManualClock(Clock):
    """Clock that moves only when the session sleeps. The measurement uses this."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class Intent:
    side: int
    qty: float
    stop: float
    take_profit: float


Decision = Intent | Sequence[Intent] | None


def _intents(raw: Decision) -> tuple[Intent, ...]:
    if raw is None:
        return ()
    if isinstance(raw, Intent):
        return (raw,)
    return tuple(raw)


class Session:
    def __init__(self, exchange: SimExchange, clock: Clock, duration_s: float = 300.0, poll_s: float = 5.0) -> None:
        self.exchange = exchange
        self.clock = clock
        self.duration_s = duration_s
        self.poll_s = poll_s
        self.halted = False
        self.polls = 0

    def run(self, decide: Callable[[AccountView], Decision]) -> AccountView:
        deadline = self.clock.now() + self.duration_s
        while self.clock.now() < deadline:
            self.polls += 1
            self._poll(decide)
            self.clock.sleep(self.poll_s)
        # Protections are exchange orders. Leaving the process does not cancel them.
        return self.exchange.view()

    def _poll(self, decide: Callable[[AccountView], Decision]) -> None:
        if not self.exchange.healthy():
            self.halted = True
            return
        self.exchange.deliver_late_fills()
        # A missing stop blocks a new entry. It does not block a reduce.
        if self.exchange.protection_covers_position():
            self.halted = False
        else:
            self.halted = True
        for intent in _intents(decide(self.exchange.view())):
            if not self.exchange.healthy():
                self.halted = True
                return
            self._act(intent)
            # A partial fill parks the rest. Do not send another order on top of it.
            if self.exchange.late:
                self.halted = True
                return

    def _act(self, intent: Intent) -> None:
        pos = self.exchange.position_qty
        # Side 0 flattens. An opposite side reduces, and never opens the other side.
        # This still runs while halted: an open position has to be closable.
        if abs(pos) >= 0.001 and (intent.side == 0 or intent.side * pos < 0):
            close_side = -1 if pos > 0 else 1
            qty = abs(pos) if intent.side == 0 else min(abs(intent.qty), abs(pos))
            if qty >= 0.001:
                self.exchange.submit_market(close_side, qty, intent.stop, intent.take_profit)
            return
        if abs(pos) >= 0.001:
            if intent.qty >= 0.001 and intent.side * pos > 0 and not self.halted:
                self.exchange.submit_market(intent.side, intent.qty, intent.stop, intent.take_profit)
                return
            self.exchange.update_protection(intent.stop, intent.take_profit)
            return
        if self.halted or intent.side == 0 or abs(intent.qty) < 0.001:
            return
        self.exchange.submit_market(intent.side, intent.qty, intent.stop, intent.take_profit)
