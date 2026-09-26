"""DL-L5: the loop stops reaching for things that are not its own.

Three findings that share a shape - the loop assumed it was alone on the account and alone on the
filesystem - and one ordering bug.

* **L1-09 / E-31**: ``startup_reconcile`` cancelled *every* open order on the account.  Today that
  is harmless because the loop only sends market orders and there is nothing else on demo; on any
  account with a manual order it silently removes it, and it is also what would delete a protective
  order the moment a restart happened.  Orders are now filtered by the client-id prefixes the loop
  itself issues (``bd-`` for rebalances, ``bdflat-`` for flattens).
* **L1-07**: the kill switch defaulted to a path relative to the working directory, so a CLI run
  from a worktree wrote a file the loop could not see.  Same class as DL-L1: two processes, two
  different working directories, one account.
* **L1-06**: ``live flatten`` closed the book without engaging the kill switch or stopping the
  loop, so the next cycle rebuilt every position it had just closed.  That is the 2026-09-04
  incident path, and the fix is an ordering contract: take the trading rights away first, then
  close.  KILL-R2 named it as the root of the watchdog problem.
"""

from __future__ import annotations

from pathlib import Path

from starquant_live.reconciler import is_own_order


def test_only_the_loops_own_prefixes_are_recognised() -> None:
    assert is_own_order("bd-1757145600000-BTCUSDT") is True
    assert is_own_order("bdflat-1757145600000-BTCUSDT") is True


def test_a_manual_order_is_not_the_loops_to_cancel() -> None:
    """The concrete hazard: a hand-placed order on the account disappearing at the next restart."""
    assert is_own_order("web_abc123") is False
    assert is_own_order("") is False
    assert is_own_order("android_9f8e7d") is False


def test_a_lookalike_prefix_is_not_enough() -> None:
    """`bdx-` is not `bd-`: the separator is part of the prefix, or every id starting with bd matches."""
    assert is_own_order("bdx-1-BTCUSDT") is False
    assert is_own_order("bd") is False


async def test_startup_cancels_its_own_and_leaves_the_rest(tmp_path: Path) -> None:
    from starquant_live.reconciler import startup_reconcile

    class _Order:
        def __init__(self, symbol: str, cid: str) -> None:
            self.symbol = symbol
            self.client_order_id = cid

    class _Venue:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        async def account(self) -> dict[str, float]:
            return {"equity": 10_000.0, "available": 10_000.0}

        async def positions(self) -> dict[str, object]:
            return {}

        async def mark_prices(self, symbols: object) -> dict[str, float]:
            return {}

        async def open_orders(self) -> list[_Order]:
            return [
                _Order("BTCUSDT", "bd-1-BTCUSDT"),
                _Order("ETHUSDT", "web_manual_hedge"),
                _Order("SOLUSDT", "bdflat-2-SOLUSDT"),
            ]

        async def cancel_order(self, symbol: str, client_order_id: str) -> None:
            self.cancelled.append(client_order_id)

    venue = _Venue()
    await startup_reconcile(venue, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    assert venue.cancelled == ["bd-1-BTCUSDT", "bdflat-2-SOLUSDT"]
    assert "web_manual_hedge" not in venue.cancelled


def test_the_kill_switch_defaults_to_an_absolute_path() -> None:
    """L1-07: a relative default means the CLI and the loop can engage different switches."""
    from starquant_live.config import live_config

    config = live_config({}, ["BTCUSDT"], _registry(), dry_run=True)

    assert config.kill_switch_path.is_absolute()


def test_an_explicit_relative_kill_switch_is_still_resolved() -> None:
    from starquant_live.config import live_config

    config = live_config(
        {"guards": {"kill_switch_path": ".starquant/live/KILL_SWITCH"}}, ["BTCUSDT"], _registry(), dry_run=True
    )

    assert config.kill_switch_path.is_absolute()
    assert config.kill_switch_path.name == "KILL_SWITCH"


def test_flatten_engages_the_kill_switch_before_it_closes_anything() -> None:
    """L1-06: closing the book while the loop still has trading rights just re-opens it next bar."""
    import inspect

    from starquant_cli import live_cmd

    # click wraps the function in a Command; the body is on .callback
    source = inspect.getsource(live_cmd.live_flatten.callback)
    engage = source.index("engage_kill_switch")
    close = source.index("engine.flatten()")
    assert engage < close, "the kill switch must be engaged before the first reduce-only order"


def _registry() -> object:
    from starquant_live.composition import parse_registry

    return parse_registry({"strategies": []})
