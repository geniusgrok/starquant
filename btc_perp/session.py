"""One manually started research session. It polls, then it exits.

``python -m btc_perp`` does not construct this object, and ``--measure`` does
not call it. The measurement is ``scripts.frontier.run``. Protections placed
here live on the in-process ``SimExchange`` object. Nothing in this module
sends a live order.
"""

from __future__ import annotations

from dataclasses import dataclass

from btc_perp.exchange import AccountView, SimExchange


class Clock:
    def now(self) -> float:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class ManualClock(Clock):
    """Test clock. Production sessions use wall time; the replay uses the bar engine."""

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


class Session:
    def __init__(self, exchange: SimExchange, clock: Clock, duration_s: float = 300.0, poll_s: float = 5.0) -> None:
        self.exchange = exchange
        self.clock = clock
        self.duration_s = duration_s
        self.poll_s = poll_s
        self.halted = False
        self.polls = 0

    def run(self, decide) -> AccountView:
        deadline = self.clock.now() + self.duration_s
        while self.clock.now() < deadline:
            self.polls += 1
            self._poll(decide)
            self.clock.sleep(self.poll_s)
        # Protections are exchange orders. Leaving the process does not cancel them.
        return self.exchange.view()

    def _poll(self, decide) -> None:
        if not self.exchange.healthy():
            self.halted = True
            return
        self.exchange.deliver_late_fills()
        if not self.exchange.protection_covers_position():
            self.halted = True
            return
        intent = decide(self.exchange.view())
        if intent is None:
            return
        if not self.exchange.healthy() or self.halted:
            return
        if abs(self.exchange.position_qty) >= 0.001:
            self.exchange.update_protection(intent.stop, intent.take_profit)
            return
        self.exchange.submit_market(intent.side, intent.qty, intent.stop, intent.take_profit)
