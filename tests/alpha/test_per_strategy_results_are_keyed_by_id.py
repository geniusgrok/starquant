"""Two entries sharing an id must fail loudly, and `strategy_targets` must pair by id rather than by position.

`strategy_targets` used to walk `zip(self.entries, strategy_scores(...).values(), strict=True)`.  The
order really does match - both come from one pass over `self.entries` - and `strict=True` really does
catch a length mismatch.  What it cannot do is say WHY: a dict keyed by id collapses by one when two
entries share an id, so the first symptom of a duplicated id is a zip complaining about lengths, and
every entry after the duplicate has meanwhile been paired with another strategy's scores.

So: pair by id, and refuse the duplicate at both doors it can come through - `parse_registry` for a
registry read from disk, `AlphaModel.__post_init__` for a model assembled any other way (a `replace`,
a miner, a test).  Both messages name the id, because "duplicate strategy id" without one sends the
reader back to the YAML to diff it by eye.
"""

from __future__ import annotations

import pandas as pd
import pytest

from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry, parse_registry
from starquant_alpha.signals.tsmom import TsmomParams

TSMOM = {**TsmomParams(vol_window=100).__dict__, "horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
BREAKOUT = {"window": 20, "atr_window": 8, "volume_window": 10, "entry_threshold": 0.05}


def _model(*entries: StrategyEntry) -> AlphaModel:
    return AlphaModel(
        entries=entries,
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24),
        interval="1h",
        min_history_bars=0,
    )


def test_each_entry_gets_its_own_strategys_scores(august_panel: Panel) -> None:
    """The pairing itself, checked against the per-strategy scores rather than assumed."""
    entries = (StrategyEntry("tsmom", params=TSMOM), StrategyEntry("breakout", params=BREAKOUT))
    model = _model(*entries)
    targets = model.strategy_targets(august_panel)
    assert list(targets) == ["tsmom", "breakout"]
    # A target is the held version of that id's own score, so the two ids must not be interchangeable.
    scores = model.strategy_scores(august_panel, model.eligible(august_panel))
    assert not scores["tsmom"].equals(scores["breakout"]), "the two signals must actually differ here"
    assert not targets["tsmom"].equals(targets["breakout"])
    solo = {entry.id: _model(entry).strategy_targets(august_panel)[entry.id] for entry in entries}
    for name, frame in solo.items():
        pd.testing.assert_frame_equal(targets[name], frame)


def test_a_duplicate_id_is_refused_by_name_at_both_doors() -> None:
    with pytest.raises(ValueError, match="tsmom"):
        parse_registry({"version": 1, "strategies": [{"id": "tsmom"}, {"id": "breakout"}, {"id": "tsmom"}]})
    with pytest.raises(ValueError, match="tsmom"):
        _model(StrategyEntry("tsmom", params=TSMOM), StrategyEntry("tsmom", params=TSMOM))
    # The control: distinct ids still construct, so a refusal that fired on everything would not pass here.
    assert len(_model(StrategyEntry("tsmom", params=TSMOM), StrategyEntry("breakout", params=BREAKOUT)).entries) == 2
