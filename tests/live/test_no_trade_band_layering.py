"""D-033: exactly one no-trade band per path, and live's reference is the venue's real position.

The band's rule is "keep what you have unless the change is big enough".  In a backtest the model's
own output *is* the position, so ``apply_no_trade_band`` is the position recursion.  Live, the
position belongs to the venue and ``plan_rebalance`` applies the same rule against it, so the model
applying it too suppressed the change twice - against a reference that was not the book, and rebuilt
each cycle over a request window that slides by one bar.

The claim these tests hold to account: with the band left to the rebalancer, the live position path
is the *same recursion* the backtest's banded weights describe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.portfolio import apply_no_trade_band
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.types import Position
from tests.fakes.fake_venue import DEFAULT_RULES

EQUITY = 100_000.0
PRICE = 50_000.0
BAND = 0.005
REL_BAND = 0.40


def _position(weight: float) -> dict[str, Position]:
    if weight == 0.0:
        return {}
    qty = weight * EQUITY / PRICE
    return {"BTCUSDT": Position(symbol="BTCUSDT", qty=qty, entry_price=PRICE, mark_price=PRICE)}


def _live_position_path(desired: list[float]) -> list[float]:
    """Replay the loop: unbanded target each bar, rebalancer decides whether the position moves."""
    held = 0.0
    path: list[float] = []
    for bar, target in enumerate(desired):
        orders, _skipped = plan_rebalance(
            {"BTCUSDT": target},
            managed_symbols=["BTCUSDT"],
            equity=EQUITY,
            positions=_position(held),
            prices={"BTCUSDT": PRICE},
            rules={"BTCUSDT": DEFAULT_RULES["BTCUSDT"]},
            bar_open_ms=bar * 3_600_000,
            params=RebalanceParams(no_trade_band=BAND, no_trade_rel_band=REL_BAND),
        )
        if orders:
            held = orders[0].target_notional / EQUITY
        path.append(held)
    return path


def test_the_rebalancer_band_reproduces_the_backtest_band_when_the_model_does_not_apply_it() -> None:
    rng = np.random.default_rng(4)
    desired = list(np.round(0.02 + 0.01 * np.cumsum(rng.normal(0.0, 0.25, 60)), 6))
    frame = pd.DataFrame({"BTCUSDT": desired})
    backtest = apply_no_trade_band(frame, BAND, REL_BAND)["BTCUSDT"].to_list()
    assert _live_position_path(desired) == pytest.approx(backtest, abs=1e-6)
    assert len(set(np.round(backtest, 6))) < len(desired), "pick a path where the band actually latches"


def test_a_pre_banded_target_carries_the_origin_of_the_window_it_was_computed_over() -> None:
    """Why the second band is not merely redundant: its reference is a path, and live restarts that path.

    Banding the target first only agrees with the rebalancer while both look at the same history.  The
    loop rebuilds the model's recursion over a request window that drops its oldest bar every cycle, so
    the latch it hands down is a function of where that window happens to begin - and downstream nothing
    can distinguish it from a real change of view.  Unbanded, the target for a bar is the same number
    whichever origin it was computed from.
    """
    rng = np.random.default_rng(9)
    desired = list(np.round(0.03 + 0.01 * np.cumsum(rng.normal(0.0, 0.25, 80)), 6))
    banded_last = {
        origin: float(
            apply_no_trade_band(pd.DataFrame({"BTCUSDT": desired[origin:]}), BAND, REL_BAND)["BTCUSDT"].iloc[-1]
        )
        for origin in (0, 1, 20)
    }
    assert len(set(np.round(list(banded_last.values()), 9))) > 1, "pick a path where the model band latches"
    # The position path is path dependent too, and must be: it is the one recursion the rule describes,
    # and the venue carries it across cycles without ever restarting.  What must not also be path
    # dependent is the *target* handed to it, which is now the same number from every origin.
    assert max(abs(value - desired[-1]) for value in banded_last.values()) > BAND / 5
