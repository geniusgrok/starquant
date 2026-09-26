"""The miner's four load-bearing ideas, each asserted rather than described."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining import (
    Const,
    CrossSectional,
    Dim,
    ExprError,
    Mul,
    RangePosition,
    Ratio,
    Ret,
    Squash,
    Sum,
    TakerBuy,
    Vol,
    VolumeRatio,
    ZScore,
    enumerate_candidates,
    to_signal,
)
from starquant_alpha.mining.search import Candidate
from starquant_alpha.panel import Panel


def _panel(bars: int = 900, symbols: tuple[str, ...] = ("A", "B", "C")) -> Panel:
    index = pd.date_range("2024-01-01", periods=bars, freq="h", tz="UTC")
    rng = np.random.default_rng(7)
    frames = {}
    for offset, symbol in enumerate(symbols):
        steps = rng.normal(0.0, 0.004, bars).cumsum()
        close = pd.Series(100.0 * np.exp(steps), index=index) * (1 + offset * 0.1)
        volume = pd.Series(rng.lognormal(10.0, 0.3, bars), index=index)
        frames[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": volume,
                "quote_volume": volume * close,
                "taker_buy_quote": volume * close * rng.uniform(0.4, 0.6, bars),
            },
            index=index,
        )
    return Panel.from_frames(frames, "1h")


# --- 1. dimensions are types ------------------------------------------------------------------------


def test_illegal_dimensions_are_refused_when_the_tree_is_built() -> None:
    """A price times a price, or a return over a volume, is nothing anyone trades."""
    with pytest.raises(ExprError, match="cannot divide"):
        Ratio(Ret(24), VolumeRatio(24))  # RETURN / RATIO
    with pytest.raises(ExprError, match="dimensionless ratio"):
        Squash(Ret(24))  # squash needs the units already cancelled
    with pytest.raises(ExprError, match="cannot add"):
        Sum(((1.0, Ret(24)), (1.0, VolumeRatio(24))))
    assert Ratio(Ret(24), Vol(48)).dim is Dim.RATIO  # ... and the legal one cancels to a ratio
    assert Squash(Ratio(Ret(24), Vol(48))).dim is Dim.SCORE


def test_a_node_refuses_a_panel_that_lacks_its_input() -> None:
    """KILL-027's shape: a signal must not quietly run on inputs it did not have when it was judged."""
    bare = _panel(120)
    stripped = Panel(interval="1h", open=bare.open, high=bare.high, low=bare.low, close=bare.close, volume=bare.volume)
    with pytest.raises(ExprError, match=r"panel\.quote_volume"):
        VolumeRatio(24).evaluate(stripped)
    with pytest.raises(ExprError, match=r"panel\.taker_buy_quote"):
        TakerBuy(4).evaluate(stripped)


# --- 2 & 3. canonicalisation and the deterministic hash ----------------------------------------------


def test_equivalent_trees_canonicalise_to_the_same_hash() -> None:
    """Commutative reordering, the x+x fold, and the /1 identity all collapse."""
    a = Sum(((1.0, Ret(24)), (1.0, Ret(72))))
    b = Sum(((1.0, Ret(72)), (1.0, Ret(24))))
    assert a.canonical_hash() == b.canonical_hash(), "term order must not create a new candidate"

    folded = Sum(((1.0, Ret(24)), (1.0, Ret(24)))).canonical()
    assert isinstance(folded, Sum) and folded.terms == ((2.0, Ret(24)),)

    # /1 folds away.  Note the operands must share a dimension: `Ret / Const` is RETURN / RATIO and is
    # refused, so dividing a return by a bare number is not expressible - scaling is `Squash`'s job.
    assert Ratio(VolumeRatio(24), Const(1.0)).canonical() == VolumeRatio(24)
    with pytest.raises(ExprError, match="cannot divide"):
        Ratio(Ret(24), Const(1.0))
    assert Sum(((1.0, Ret(24)), (0.0, Ret(72)))).canonical() == Ret(24)
    assert Sum(((1.0, Ret(24)), (-1.0, Ret(24)))).canonical() == Const(0.0)

    assert Ret(24).canonical_hash() != Ret(72).canonical_hash()  # ... and different means different


# --- 4. derived complexity and lookback ---------------------------------------------------------------


def test_lookback_accumulates_through_the_tree() -> None:
    """A signal that understates its warmup is E-042; here it is derived, not declared by hand."""
    assert Ret(720).lookback() == 721
    nested = ZScore(Ret(168), 336)
    assert nested.lookback() == 169 + 336
    robust = ZScore(Ret(168), 336, robust=True)
    assert robust.lookback() > nested.lookback()
    assert Squash(Ratio(Ret(24), Vol(48))).complexity() == 4


# --- the search and its trial accounting ---------------------------------------------------------------


def test_search_deduplicates_and_reports_the_trials_it_must_declare() -> None:
    result = enumerate_candidates(
        horizons=(24, 72), vol_windows=(48,), scales=(1.0,), z_windows=(72,), flow_windows=(4,)
    )
    hashes = [candidate.hash for candidate in result.candidates]
    assert len(hashes) == len(set(hashes)), "a search must not offer the same expression twice"
    assert result.evaluated >= len(result.candidates)
    assert result.declared_trials == result.evaluated
    assert all(candidate.lookback > 0 for candidate in result.candidates)


def test_the_lookback_ceiling_keeps_out_candidates_the_live_loop_could_never_fetch() -> None:
    """The venue serves at most 1,500 bars; a candidate needing more is a restart-time failure (E-042)."""
    result = enumerate_candidates(
        horizons=(720,), vol_windows=(48,), scales=(1.0,), z_windows=(336,), flow_windows=(4,), max_lookback=800
    )
    assert result.rejected["too_long"] > 0
    assert all(candidate.lookback <= 800 for candidate in result.candidates)


def test_a_candidate_compiles_to_the_ordinary_signal_contract() -> None:
    """The point of the rebuild: the existing judge applies to a mined candidate unchanged."""
    panel = _panel()
    candidate = Candidate.of(Squash(Ratio(Ret(72), Vol(48)), 1.0))
    spec = to_signal(candidate)
    assert spec.id == f"mined_{candidate.hash}"
    assert spec.warmup_for({}) == candidate.lookback
    assert spec.needs_funding({}) is False
    targets = spec.compute(panel, spec.default_params)
    assert list(targets.columns) == list(panel.close.columns)
    assert targets.abs().max().max() <= 1.0
    assert targets.notna().any().any()


def test_cross_sectional_rank_candidate_is_bounded_and_centred() -> None:
    panel = _panel()
    scores = CrossSectional(ZScore(Ret(72), 168), "rank").evaluate(panel)
    settled = scores.dropna(how="all")
    assert settled.abs().max().max() <= 1.0
    assert abs(float(settled.mean(axis=1).mean())) < 0.2


# --- the second search: shapes the first one could not express ----------------------------------------


def test_mul_keeps_the_dimension_rule_and_folds_its_identities() -> None:
    """RATIO x RATIO only: a product of dimensioned quantities is the term nobody can read."""
    with pytest.raises(ExprError, match="dimensionless operands"):
        Mul(Ret(24), VolumeRatio(24))  # RETURN x RATIO
    inner = ZScore(Ret(72), 168)
    assert Mul(Const(1.0), inner).canonical() == inner
    assert Mul(Const(0.0), inner).canonical() == Const(0.0)
    assert Mul(Const(2.0), Const(3.0)).canonical() == Const(6.0)
    # commutative: operand order must not mint a new candidate
    assert Mul(Const(-1.0), inner).canonical_hash() == Mul(inner, Const(-1.0)).canonical_hash()


def test_reversal_is_expressible_only_now_and_is_the_negation_of_momentum() -> None:
    """The first search had no product node, so it could not write a minus sign and offered only momentum."""
    panel = _panel()
    forward = ZScore(Ret(72), 168)
    reversed_ = Mul(Const(-1.0), forward)
    a, b = forward.evaluate(panel), reversed_.evaluate(panel)
    pd.testing.assert_frame_equal(a, -b)
    assert forward.canonical_hash() != reversed_.canonical_hash()


def test_range_position_is_causal_and_therefore_unbounded_which_is_why_it_is_a_ratio() -> None:
    """The extremes come from the *previous* window, so a breakout close legitimately exceeds +/-1.

    That is the whole event the family exists to see, and it is also why this node is RATIO rather than
    SCORE: only `Squash` or a cross-sectional rank may bound it, and the type system enforces that a
    candidate cannot emit it as a position directly.
    """
    panel = _panel()
    node = RangePosition(72)
    assert node.dim is Dim.RATIO
    scores = node.evaluate(panel).dropna(how="all")
    assert scores.max().max() > 1.0, "a close above the prior window's high must read above +1"
    assert node.lookback() == 73
    with pytest.raises(ExprError, match="dimensionless ratio"):
        Squash(CrossSectional(node, "rank"))  # already a bounded score: squashing it says nothing new
    bounded = Squash(node, 1.0).evaluate(panel).dropna(how="all")
    assert bounded.abs().max().max() <= 1.0


def test_the_expanded_search_adds_shapes_rather_than_parameter_values() -> None:
    """Every new family must contribute an expression the old three could not produce."""
    old = enumerate_candidates(range_windows=(), regime_long_windows=(), horizons=(24, 72, 168, 336, 720))
    new = enumerate_candidates()
    assert new.evaluated > old.evaluated
    kinds = {str(candidate.expr) for candidate in new.candidates}
    assert any("rangepos" in text for text in kinds), "range family missing"
    assert any("-1 *" in text or "* -1" in text for text in kinds), "reversal family missing"
    assert any(text.count("vol(") >= 2 for text in kinds), "regime family missing"
    assert any("+" in text for text in kinds), "multi-horizon family missing"
    hashes = [candidate.hash for candidate in new.candidates]
    assert len(hashes) == len(set(hashes))


def test_the_regime_family_never_emits_an_interaction_that_cancels_to_plain_momentum() -> None:
    """``(ret/vol_a) * (vol_a/vol_b)`` is ``ret/vol_b``: an interaction only in appearance.

    The first expanded run shipped 75 of these and they scored 0.817/0.817/0.818, differing only in
    where their warmup NaNs fell.  Canonicalisation cannot catch it - it folds structural identities,
    not algebra over division - so the family has to exclude the combination and this has to be asserted.
    """
    pattern = re.compile(r"ret\(\d+\) / vol\((\d+)\)\) \* \(vol\((\d+)\) / vol\(\d+\)")
    for candidate in enumerate_candidates().candidates:
        found = pattern.search(str(candidate.expr))
        if found:
            assert found.group(1) != found.group(2), f"cancels to plain momentum: {candidate.expr}"
