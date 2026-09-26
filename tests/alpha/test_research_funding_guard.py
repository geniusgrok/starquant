"""E-040 / KILL-027 on the research path: a funding-consuming model refuses a funding-free panel.

``AlphaModel.targets`` has refused since D-023, so the *live* loop cannot run a signal on inputs it
did not have when it was judged.  ``strategy_targets`` - the seam every research command reaches,
through ``evaluate``, ``weights``, ``combined_targets`` or ``decompose_book`` - did not, and research
is where evidence is produced.  ``starquant research backtest --strategy tsmom --no-funding`` therefore
exited 0 with tsmom's crowding modifier consuming nothing, and wrote a report whose ``params`` block
cites ``crowding_window: 72`` for a configuration that never ran.

The guard sits on ``strategy_targets`` rather than on ``evaluate`` because ``decompose_book`` reaches
the signals through ``strategy_targets`` directly; a guard on ``evaluate`` would leave
``research decompose`` producing exactly the report this exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel
from starquant_alpha.model import AlphaModel, FundingUnavailable
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_alpha.validation.decompose import decompose_book
from starquant_alpha.validation.stability import parameter_neighborhood

HOURLY = {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5], "vol_window": 100}
CROWDING = {"crowding_window": 72, "crowding_cut": 0.7, "crowding_penalty": 0.5}


def _model(**params: object) -> AlphaModel:
    entry = StrategyEntry("tsmom", params={**TsmomParams().__dict__, **HOURLY, **params})
    return AlphaModel(
        entries=(entry,),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=0,
    )


def _funded(panel: Panel) -> Panel:
    """The same bars with a funding frame, as ``load_panel`` builds one under ``--funding``."""
    settlements = pd.DataFrame(
        np.tile(np.linspace(-1e-4, 1e-4, len(panel.symbols)), (len(panel.index), 1)),
        index=panel.index,
        columns=panel.symbols,
    )
    frames = {
        symbol: pd.DataFrame(
            {field: getattr(panel, field)[symbol] for field in ("open", "high", "low", "close", "volume")}
        )
        for symbol in panel.symbols
    }
    return Panel.from_frames(frames, interval="1h", funding=settlements)


def test_strategy_targets_refuses_a_funding_signal_on_a_funding_free_panel(august_panel: Panel) -> None:
    assert august_panel.funding is None
    with pytest.raises(ValueError, match="funding"):
        _model(**CROWDING).strategy_targets(august_panel)


@pytest.mark.parametrize("call", ["evaluate", "weights", "combined_targets"])
def test_every_research_entry_point_inherits_the_refusal(august_panel: Panel, call: str) -> None:
    model = _model(**CROWDING)
    with pytest.raises(ValueError, match="funding"):
        getattr(model, call)(august_panel)


def test_decompose_refuses_too_because_it_reaches_the_signals_without_evaluate(august_panel: Panel) -> None:
    """The reason the guard is not on ``evaluate``: D-024's decomposition never calls it."""
    with pytest.raises(ValueError, match="funding"):
        decompose_book(_model(**CROWDING), august_panel, CostModel(7.0, 0.0), folds=3, min_train=300, purge=5)


def test_the_control_arm_is_untouched(august_panel: Panel) -> None:
    """``crowding_window: 0`` reads no funding, so a funding-free panel is the configuration it was judged on."""
    weights, _combined, per = _model(crowding_window=0).evaluate(august_panel)
    assert per["tsmom"].notna().any().any() and weights.notna().any().any()


def test_an_inert_modifier_is_not_a_requirement(august_panel: Panel) -> None:
    """``crowding_penalty: 0`` cannot change a score, so refusing it would be ceremony, not a guard."""
    assert _model(**{**CROWDING, "crowding_penalty": 0.0}).evaluate(august_panel)[0].notna().any().any()


def test_the_same_model_runs_once_the_panel_carries_funding(august_panel: Panel) -> None:
    funded = _funded(august_panel)
    assert funded.funding is not None
    weights, _combined, per = _model(**CROWDING).evaluate(funded)
    assert per["tsmom"].notna().any().any() and weights.notna().any().any()


def test_the_guard_refuses_a_funding_frame_that_carries_no_settlement(august_panel: Panel) -> None:
    """An all-zero frame is not funding.  `--funding` is the CLI default, and against a root whose klines
    are synced but whose funding never was, `FundingStore.load` returns an empty frame per symbol and
    `load_panel` builds a frame of zeros - not `None`.  A guard that only tests `is None` is satisfied by
    it, which is how the refusal and the docstring's claim to be "the guard that cannot be forgotten"
    came apart: the CLI learned this case and the library did not, leaving `research book`'s robustness
    panels and every direct library caller on the weaker test.
    """
    frames = {
        symbol: pd.DataFrame(
            {field: getattr(august_panel, field)[symbol] for field in ("open", "high", "low", "close", "volume")}
        )
        for symbol in august_panel.symbols
    }
    zeros = pd.DataFrame(0.0, index=august_panel.index, columns=list(august_panel.symbols))
    unsynced = Panel.from_frames(frames, interval="1h", funding=zeros)
    assert unsynced.funding is not None  # the frame exists; it just says nothing
    with pytest.raises(ValueError, match="funding"):
        _model(**CROWDING).strategy_targets(unsynced)


def test_the_crowding_modifier_actually_reads_the_funding_it_demanded(august_panel: Panel) -> None:
    """The conclusion, not just the precondition: a guard that admits a run proves nothing on its own.

    Every other test here asserts that funding was *present*.  None of them would notice
    `apply_crowding_modifier` being dropped from `tsmom.compute` altogether, which is the refactor most
    likely to reintroduce E-040 from the inside - the guard would keep passing and the report would keep
    citing `crowding_window: 72`.  This pins the difference the modifier makes, so unwiring it fails here.
    """
    funded = _funded(august_panel)
    on = _model(**CROWDING).strategy_targets(funded)["tsmom"]
    off = _model(crowding_window=0).strategy_targets(funded)["tsmom"]
    changed = int((on.fillna(-9.0) != off.fillna(-9.0)).to_numpy().sum())
    assert changed > 0, "the modifier consumed funding and changed nothing; this fixture cannot detect it"


def test_the_refusal_has_its_own_type_so_a_blanket_handler_can_let_it_through(august_panel: Panel) -> None:
    """It stays a ``ValueError`` for every existing caller, but is identifiable for the ones that catch.

    Two places score many things in a loop and treat a failure as a property of the ITEM: `research
    mine` drops a candidate that cannot be evaluated into an `error` row, and `parameter_neighborhood`
    records a perturbation that raises as `None`.  A missing funding archive is a property of the RUN,
    so under those handlers the guard degraded into a silently thinner shortlist or a missing neighbour.
    """
    with pytest.raises(FundingUnavailable):
        _model(**CROWDING).strategy_targets(august_panel)
    assert issubclass(FundingUnavailable, ValueError)  # nothing that catches ValueError today changes


def test_parameter_neighborhood_still_swallows_a_bad_perturbation_but_not_a_missing_archive() -> None:
    """D-020's neighbourhood exists to survive params that cannot be scored, not inputs that are absent."""
    base = {"window": 100}
    assert parameter_neighborhood(lambda p: None if p["window"] != 100 else 1.0, base)["base"] == 1.0

    def degenerate(params: Mapping[str, Any]) -> float | None:
        if params["window"] != 100:
            raise ValueError("this perturbation cannot be scored")
        return 1.0

    neighbours = parameter_neighborhood(degenerate, base)["neighbours"]["window"]
    assert neighbours == {"down": None, "up": None}  # unchanged: a bad perturbation is still recorded as None

    def unfunded(params: Mapping[str, Any]) -> float | None:
        if params["window"] != 100:
            raise FundingUnavailable("no settlement for any symbol")
        return 1.0

    with pytest.raises(FundingUnavailable):
        parameter_neighborhood(unfunded, base)
