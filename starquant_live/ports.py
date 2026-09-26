"""Protocols that decouple the live loop from concrete data/venue/alpha implementations.

``starquant_live`` only ever talks to these interfaces.  ``starquant_exchange``
implements :class:`Venue`, ``starquant_data`` implements :class:`MarketData`,
and ``starquant_alpha`` provides the model behind :class:`SignalModel`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import pandas as pd

from starquant_shared.types import AccountState, InstrumentRules, OrderAck, OrderRequest, Position


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep(self, seconds: float) -> None: ...


class MarketData(Protocol):
    """Closed-bar market data for signal computation (mainnet public data)."""

    async def closed_bars(self, symbols: Sequence[str], interval: str, limit: int) -> dict[str, pd.DataFrame]:
        """Return, per symbol, a frame of *closed* bars indexed by UTC open time."""
        ...

    async def funding_rates(self, symbols: Sequence[str]) -> dict[str, float]:
        """Latest settled funding rate per symbol (fraction per 8h)."""
        ...

    async def funding_history(self, symbols: Sequence[str], start_ms: int) -> dict[str, pd.Series]:
        """Settled funding rates per symbol since ``start_ms``, indexed by UTC settlement time.

        Aligned onto bar open times by ``Panel.from_frames`` exactly as the
        research store does, so a funding-consuming signal sees the same panel
        live as in validation (KILL-027).
        """
        ...


class Venue(Protocol):
    """The exchange account we trade on (demo/testnet)."""

    async def rules(self) -> dict[str, InstrumentRules]: ...

    async def account(self) -> AccountState: ...

    async def positions(self) -> dict[str, Position]: ...

    async def mark_prices(self, symbols: Sequence[str]) -> dict[str, float]: ...

    async def set_leverage(self, symbol: str, leverage: int) -> int: ...

    async def place_order(self, request: OrderRequest) -> OrderAck: ...

    async def query_order(self, symbol: str, client_order_id: str) -> OrderAck | None: ...

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderAck | None: ...

    async def open_orders(self, symbol: str | None = None) -> list[OrderAck]: ...

    async def income(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]: ...


class VenueProbes(Protocol):
    """What the engine reads off a venue with ``getattr``, declared.

    Seven members used to be missing from this file entirely and two more (``venue_time_ms``,
    ``user_trades``) were declared REQUIRED on :class:`Venue` while every call site probed them and
    fell back.  The port was wrong in both directions at once, and the lesson is already written two
    protocols down: *a protocol that omits what the caller actually reads has stopped describing the
    contract*.

    They are genuinely optional - the paper venue has no leverage brackets, the fake market feed has no
    REST client - so they live here rather than on :class:`Venue`, and the engine still probes.  What
    changes is that the probe now has something to check itself against: an adapter that means to
    supply one of these can be type-checked against this protocol, and
    ``tests/live/test_the_ports_describe_what_the_engine_reads.py`` fails if a call site starts reading
    a tenth member that nobody declared.

    The one to be careful with is ``venue_time_ms``.  D-030 is the hour of attribution that went to the
    wrong cycle because the income window was asked for on the host clock; the fallback when this is
    absent is that same host clock, which is why its absence is worth seeing in a type rather than
    discovering in a reconciliation.
    """

    def venue_time_ms(self) -> int:
        """Now on the venue's clock.  ``income`` bounds are venue timestamps, not host ones (D-030)."""
        ...

    async def user_trades(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Fills in the window, carrying both the trade id and the order id (D-032)."""
        ...

    async def sync_clock(self) -> int:
        """Establish the venue offset up front rather than on the first ``-1021``."""
        ...

    async def hedge_mode(self) -> bool:
        """True when the account is in dual-side mode, which the loop refuses to start against."""
        ...

    async def margin_mode(self) -> Mapping[str, Any]:
        """Account margin shape, for KILL-R19's refusal."""
        ...

    async def leverage_brackets(self) -> Mapping[str, int]:
        """Per-symbol venue leverage caps, for D-016's derivation."""
        ...

    def mark(self, closes: Mapping[str, float]) -> None:
        """Paper venue only: move marks onto the newest closed bar."""
        ...


class MarketDataProbes(Protocol):
    """The same, for the market data port."""

    def server_time_ms(self) -> Any:
        """The feed's own clock, for D-025's skew/alignment/jump instrumentation.

        Awaited by the caller.  A feed without it makes `_clock_skew` return all-None, which is a
        reading the daily report can show as absent - not a zero it would show as healthy.
        """
        ...

    @property
    def client(self) -> Any:
        """The underlying REST client, for DL-Q6's metrics snapshot."""
        ...


class UniverseUpdate(Protocol):
    """Result of a universe refresh (structural; see ``starquant_data.pool.UniverseUpdate``)."""

    @property
    def symbols(self) -> tuple[str, ...]: ...

    @property
    def entered(self) -> tuple[str, ...]: ...

    @property
    def left(self) -> tuple[str, ...]: ...

    @property
    def at_ms(self) -> int: ...

    def to_dict(self) -> dict[str, Any]: ...


class UniverseProvider(Protocol):
    """Re-ranks the tradable universe (daily); the engine flattens what leaves (D-014)."""

    async def select(self, previous: Sequence[str], rules: Mapping[str, InstrumentRules]) -> UniverseUpdate: ...


class TargetSet(Protocol):
    """Output contract of a signal model (structural; see ``starquant_alpha.ensemble.TargetWeights``)."""

    @property
    def weights(self) -> dict[str, float]: ...

    @property
    def contributions(self) -> dict[str, dict[str, float]]: ...

    @property
    def as_of(self) -> pd.Timestamp: ...

    # Observability, not part of the trading decision - but declared here all the same, because the
    # engine reads both every cycle and writes them into `cycles.jsonl` (`asset_vol` for M-015's
    # compression, `book_weights` for the per-book mark-to-market the probe stop is calibrated on).
    # It reads them through `getattr(..., default)` so that a model which cannot supply them still
    # trades; what that `getattr` also did was keep them out of this file, and a protocol that omits
    # what the caller actually reads has stopped describing the contract.  That is not theory: it is
    # why mypy could only see `engine.py:1373` (`self.model.entries`, the one access written without
    # a `getattr`) and said nothing about the other three.  Mapping rather than dict, and read-only,
    # so an implementation is free to hand back something narrower.
    @property
    def asset_vol(self) -> Mapping[str, float]: ...

    @property
    def book_weights(self) -> Mapping[str, Mapping[str, float]]: ...

    # The two the model can say about the construction rather than about a symbol, declared here for
    # the reason the four above are: the engine reads them every cycle and writes them into
    # `cycles.jsonl`, and a protocol that omits what the caller reads has stopped describing the
    # contract.  Optional, so a model that cannot compute them still trades.
    @property
    def portfolio_vol(self) -> float | None: ...

    @property
    def clipped_risk_share(self) -> float | None: ...


class StrategyEntryLike(Protocol):
    """One enabled strategy, as the live loop reads it (structural; see ``starquant_alpha.registry.StrategyEntry``).

    Two attributes, because two is what ``starquant_live`` actually touches on a typed path: the id and
    the book it belongs to, which together are the line `engine.py` writes into every cycle record as
    ``books`` - the fact that let M-015's compression and M-Q08's slippage stop answering a
    one-book question on the sum of two.  The rest of the entry (``params``, ``weight``, ``probe``)
    is read only through ``getattr``/``Any`` paths (``registry_digest``, ``_crowding_effect``), which
    is deliberate there: those walk a model that may hold a ``mined_*`` id this process cannot
    resolve.  Declaring only what is read keeps this file free of ``starquant_alpha`` - a port that
    imports the implementation it exists to hide is not a port.
    """

    @property
    def id(self) -> str: ...

    @property
    def book(self) -> str: ...


class SignalModel(Protocol):
    """Turns closed bars plus funding into target weights with per-strategy attribution.

    ``previous`` carries the last cycle's per-strategy targets so NO_ACTION can
    hold a position across cycles (D-005) independently of the request window.
    ``reference_symbols`` declares the cross-sectional population the signals rank
    and demean over (P1-01 / DL-Q1) - the universe the caller manages, rather than
    whichever frames happen to be in ``bars``.
    """

    @property
    def warmup_bars(self) -> int: ...

    @property
    def min_history_bars(self) -> int: ...

    @property
    def needs_funding(self) -> bool: ...

    # The enabled strategies behind the weights.  `engine.py:1373` has read this off the concrete
    # model since 2026-09-12 while the protocol said no such attribute existed; mypy reported it,
    # CI went red for 23 pushes on 2026-09-09..13, and the pytest step behind it never ran once in
    # those four days.  So the cost of a protocol that lies is not "a type error" - it is every test
    # that stops being run while somebody argues about one.
    @property
    def entries(self) -> tuple[StrategyEntryLike, ...]: ...

    def targets(
        self,
        bars: Mapping[str, pd.DataFrame],
        funding: Mapping[str, float],
        previous: Mapping[str, Mapping[str, float]] | None = None,
        funding_history: Mapping[str, pd.Series] | pd.DataFrame | None = None,
        reference_symbols: Sequence[str] | None = None,
    ) -> TargetSet: ...
