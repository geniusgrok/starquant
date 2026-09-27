"""P28: the two properties that decide whether this is pairs trading or a look-ahead with two legs.

**Chosen on a prefix.**  Selecting pairs on the full sample is the classic way this family reads the
future, and it is not subtle: picking, in 2026, the pair that co-moved best over 2021-2026 and then
"trading" it in 2021 is a look-ahead by construction.  Partner, correlation and spread scale are all
frozen at the refit bar.

**Matched on vol, not on beta.**  Stage 1 of the portfolio is `w1 = target * vol_target / asset_vol`,
so a signal emitting `+1` and `-beta` has its beta divided away by the two legs' own volatilities.
The spread is defined on vol-normalised returns instead, which makes that division the correct
normalisation - the pair's hedge comes free from the construction rather than fighting it.  What this
file can assert about that is the shape it depends on: the two legs are always exact opposites.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_alpha.signals import SIGNALS
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.pairs import HOLD, PairsParams, pairs_scores
from tests.alpha.test_causality import _bit_for_bit

SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")


def _panel(n_bars: int = 2_400, seed: int = 5, coupling: float = 0.9) -> Panel:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    common = rng.normal(0, 0.01, n_bars)
    steps = rng.normal(0, 0.01, size=(n_bars, len(SYMBOLS)))
    steps[:, 0] = coupling * common + (1 - coupling) * steps[:, 0]
    steps[:, 1] = coupling * common + (1 - coupling) * steps[:, 1]
    frames = {}
    for j, symbol in enumerate(SYMBOLS):
        close = 100.0 * np.exp(np.cumsum(steps[:, j]))
        frames[symbol] = pd.DataFrame(
            {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1_000.0},
            index=index,
        )
    return Panel.from_frames(frames, "1h")


def test_the_two_legs_are_always_exact_opposites() -> None:
    """The shape the vol-matching depends on: equal and opposite scores, equal risk after stage 1."""
    scores = pairs_scores(_panel())
    rows = scores.dropna(how="all")
    assert not rows.empty
    for _, row in rows.iterrows():
        traded = row.dropna()
        assert len(traded) % 2 == 0
        assert np.isclose(traded.sum(), 0.0), "a pair whose legs do not cancel is not a pair"


def test_a_pair_is_chosen_from_a_prefix_and_truncating_the_future_changes_nothing() -> None:
    """The sharpest check for this family: the partner cannot be chosen with the answer in hand."""
    panel = _panel()
    whole = pairs_scores(panel)
    cut = 1_800
    prefix = Panel.from_frames(
        {
            symbol: pd.DataFrame(
                {
                    field: getattr(panel, field)[symbol].to_numpy()[:cut]
                    for field in ("open", "high", "low", "close", "volume")
                },
                index=panel.index[:cut],
            )
            for symbol in panel.symbols
        },
        "1h",
    )
    _bit_for_bit(pairs_scores(prefix), whole.iloc[:cut], check_freq=False)


def test_an_uncorrelated_panel_produces_no_pair_at_all() -> None:
    """`min_corr` has to bind, or "pairs" is just two symbols that happened to be adjacent."""
    assert pairs_scores(_panel(coupling=0.0)).notna().to_numpy().sum() == 0


def test_the_vocabulary_is_the_same_three_items() -> None:
    values = pairs_scores(_panel()).to_numpy()
    finite = values[~np.isnan(values)]
    assert finite.size
    assert np.all(np.abs(finite) <= 1.0)
    assert 0.0 in set(np.round(finite, 10)), "a closed spread must be an explicit exit, not a hold"
    holds = np.isclose(np.abs(finite), HOLD)
    assert holds.any() and np.all(np.abs(finite[holds]) < PairsParams().entry_threshold)


def test_a_closed_spread_flattens_and_a_hold_carries() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC")
    frame = pd.DataFrame({"A": [0.9, HOLD, 0.0, -HOLD]}, index=index)
    assert list(scores_to_targets(frame, PairsParams().entry_threshold)["A"]) == [0.9, 0.9, 0.0, 0.0]


def test_a_wider_entry_band_trades_strictly_less() -> None:
    """The parameter has to mean what it says, or the grid is searching noise."""
    panel = _panel()
    tight = pairs_scores(panel, PairsParams(entry_z=1.5))
    wide = pairs_scores(panel, PairsParams(entry_z=2.5))
    assert (tight.abs() >= PairsParams().entry_threshold).to_numpy().sum() > (
        wide.abs() >= PairsParams().entry_threshold
    ).to_numpy().sum()


@pytest.mark.parametrize("bad", [{"exit_z": 3.0}, {"z_scale": 0.0}, {"min_corr": 2.0}, {"z_window": 2}])
def test_the_pre_registered_parameter_space_is_the_only_one_accepted(bad: dict) -> None:
    with pytest.raises(ValueError):
        PairsParams.from_mapping({**PairsParams().__dict__, **bad})


def test_it_is_registered_under_its_pre_registered_defaults() -> None:
    spec = SIGNALS["pairs"]
    assert spec.default_params["formation_bars"] == 720
    assert spec.default_params["entry_z"] == 2.0
    assert spec.warmup_for(spec.default_params) == 720 + 168 + 1
    assert not spec.needs_funding(spec.default_params)
