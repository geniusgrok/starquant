"""H-001: ``conviction_mode: sign`` trades direction only, without changing when the book acts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.panel import Panel
from starquant_alpha.signals.base import scores_to_targets
from starquant_alpha.signals.tsmom import TsmomParams, apply_conviction_mode, compute


def _scores() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=7, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "A": [np.nan, 0.63, 0.11, -0.45, 0.0, 0.25, np.nan],  # actionable, hold, flip, exit, actionable, hold
            "B": [np.nan, -0.90, -0.19, 0.19, 0.31, 0.0, 0.05],
        },
        index=index,
    )


def test_sign_mode_rewrites_only_actionable_scores() -> None:
    params = TsmomParams(entry_threshold=0.20, conviction_mode="sign")
    out = apply_conviction_mode(_scores(), params)
    assert out["A"].tolist()[1:6] == [1.0, 0.11, -1.0, 0.0, 1.0]  # 0.11 is sub-threshold and untouched
    assert out["B"].tolist()[1:] == [-1.0, -0.19, 0.19, 1.0, 0.0, 0.05]  # |0.19| < 0.20 stays, 0.0 stays an exit
    assert np.isnan(out["A"].iloc[0]) and np.isnan(out["A"].iloc[6])
    assert apply_conviction_mode(_scores(), TsmomParams(entry_threshold=0.20)).equals(_scores())


def test_sign_mode_targets_equal_the_sign_of_the_validated_targets() -> None:
    """The whole point of H-001: same decisions, magnitude removed."""
    scores = _scores()
    threshold = 0.20
    base = scores_to_targets(scores, threshold)
    signed = scores_to_targets(apply_conviction_mode(scores, TsmomParams(conviction_mode="sign")), threshold)
    expected = pd.DataFrame(np.sign(base.to_numpy(dtype=float)), index=base.index, columns=base.columns)
    pd.testing.assert_frame_equal(signed, expected)
    # the hold structure survives: A holds its long through the sub-threshold bar, then flips and exits
    assert signed["A"].tolist()[1:6] == [1.0, 1.0, -1.0, 0.0, 1.0]
    assert signed.isna().equals(base.isna())


def test_sign_mode_is_wired_through_compute_and_validated(august_panel: Panel) -> None:
    params = TsmomParams(vol_window=100).__dict__ | {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
    plain = compute(august_panel, params)
    signed = compute(august_panel, {**params, "conviction_mode": "sign"})
    actionable = plain.abs() >= params["entry_threshold"]
    rewritten = signed.where(actionable).stack().dropna()
    assert len(rewritten) > 100 and (rewritten.abs() == 1.0).all()
    pd.testing.assert_frame_equal(signed.where(~actionable), plain.where(~actionable))
    with pytest.raises(ValueError):
        TsmomParams(conviction_mode="binary")


def test_sign_mode_keeps_the_crowding_threshold_effect_but_drops_its_magnitude_effect() -> None:
    """A shrunk score can still fall below the entry threshold; above it, the shrink no longer shows."""
    index = pd.date_range("2024-01-01", periods=80, freq="h", tz="UTC")
    columns = pd.Index(["A", "B", "C", "D", "E"])
    score = pd.DataFrame(0.5, index=index, columns=columns)
    score["B"] = 0.30  # crowded: 0.30 * 0.5 = 0.15 < 0.20 -> falls out of the actionable set
    funding = pd.DataFrame(0.0, index=index, columns=columns)
    funding.loc[funding.index[::8], :] = [[0.001, 0.001, 0.0001, -0.00005, -0.001]] * len(funding.index[::8])
    params = TsmomParams(crowding_window=72, crowding_cut=0.7, crowding_penalty=0.5, conviction_mode="sign")
    from starquant_alpha.signals.tsmom import apply_crowding_modifier

    out = apply_conviction_mode(apply_crowding_modifier(score, funding, params), params)
    last = out.iloc[-1]
    assert last["A"] == 1.0  # crowded but still actionable after the shrink: magnitude gone, direction kept
    assert last["B"] == 0.15  # shrunk below the threshold: still NO_ACTION, exactly as in "score" mode
    assert last["C"] == 1.0 and last["D"] == 1.0
