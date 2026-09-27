"""Carry enters the search space (DL-P17-01/02/03), and the 225 that were there before do not move.

Three things are asserted here that the rest of the suite cannot assert.

``T-P17-01`` is the identity guard.  ``tests/fixtures/mining_baseline_hashes.json`` was generated from
unmodified ``db9efd9`` **before** a ``Funding`` node existed, which is the only moment it could be
generated honestly, and every edit in this delivery re-runs against it.  It is an ORDERED comparison:
the fixture's array is ``(complexity, hash)`` order, so a set comparison would silently stop testing the
invariant that P14's shortlist is still reproducible.

``T-P17-02`` onward pin the leaf's dimension contract.  ``Funding`` is ``Dim.RETURN``, which is what
forces every shape in ``_funding_family`` through ``Ratio(Funding, Vol)`` instead of squashing a rate
directly - the dimension system refuses the shortcut rather than merely discouraging it.

``T-P17-06`` is the one with a bug behind it.  ``to_signal`` hardcoded ``uses_funding=lambda params:
False`` at ``search.py:242``, so a mined candidate that read ``panel.funding`` would have told the live
loop it needed no funding history and then run on whatever it was handed.  That is the KILL-027 shape,
and D-023 exists to refuse it at startup rather than discover it in attribution.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starquant_alpha import features
from starquant_alpha.mining import (
    Const,
    CrossSectional,
    Dim,
    Expr,
    ExprError,
    Funding,
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
from starquant_alpha.signals import tsmom
from starquant_cli.research_cmd import research_mine
from tests.alpha.test_causality import _bit_for_bit

BARS = 900
SYMBOLS = ("A", "B", "C")


def _panel(*, with_funding: bool) -> Panel:
    """The suite's usual synthetic panel, optionally carrying settlements every eight bars."""
    index = pd.date_range("2024-01-01", periods=BARS, freq="h", tz="UTC")
    rng = np.random.default_rng(7)
    frames = {}
    for offset, symbol in enumerate(SYMBOLS):
        steps = rng.normal(0.0, 0.004, BARS).cumsum()
        close = pd.Series(100.0 * np.exp(steps), index=index) * (1 + offset * 0.1)
        volume = pd.Series(rng.lognormal(10.0, 0.3, BARS), index=index)
        frames[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": volume,
                "quote_volume": volume * close,
                "taker_buy_quote": volume * close * rng.uniform(0.4, 0.6, BARS),
            },
            index=index,
        )
    if not with_funding:
        return Panel.from_frames(frames, "1h")
    # Settlement stamps land a few milliseconds past the hour, as the venue's really do (D-034).
    stamps = index[::8] + pd.Timedelta(milliseconds=17)
    funding = pd.DataFrame(
        {symbol: rng.normal(0.0001, 0.0003, len(stamps)) for symbol in SYMBOLS},
        index=pd.DatetimeIndex(stamps),
    )
    return Panel.from_frames(frames, "1h", funding=funding)


@pytest.fixture(scope="module")
def funding_panel() -> Panel:
    return _panel(with_funding=True)


def test_the_existing_search_space_is_bit_for_bit_what_p14_recorded(fixtures_dir: Path) -> None:
    """T-P17-01: the 225 do not move, in value or in order, however the miner grows around them."""
    baseline = json.loads((fixtures_dir / "mining_baseline_hashes.json").read_text(encoding="utf-8"))

    # Both caps, because the delivery raised one of them: at the recorded cap of 8 and at today's 10, the
    # pre-funding space must be the same 225.  That is what makes the raise provably inert rather than
    # merely believed to be.
    # DL-A1 added five more families behind their own switch, for the same reason `include_funding`
    # exists: growth has to be a dimension that can be turned off, or a frozen space stops being one.
    # DL-D4 added the positioning family behind `include_metrics` and this test is what made it add a
    # switch at all - it went red on the first run, which is the guard doing precisely its job.
    # #8 added `_seasonality_family` behind `include_seasonality` on 2026-09-09, and it went red the
    # same way.  The candidate list is sorted BY HASH, so a new expression sorting into the middle
    # shifts every position after it - the frozen hashes had not changed, only their indices.  The
    # same run also showed `too_long: 18`, which is how the grid's third arm turned out to be
    # unsearchable; see `_seasonality_family`.
    # DL-D5 added `_basis_family` behind `include_basis` on 2026-09-09 and it went red here the same
    # way, which is the fifth time this guard has caught its own delivery.  Its 18 shapes sort into the
    # middle by hash like every other family's, so the frozen hashes were unmoved and their positions
    # were not.  `rejected` stayed all-zero: at the declared grid the deepest basis shape reserves 721
    # bars against `max_lookback` 1400 and the widest is complexity 10 against a cap of 10, so nothing
    # was dropped - which is what `hod(60)` could not say.
    for result in (
        enumerate_candidates(
            include_funding=False,
            include_panel_nodes=False,
            include_metrics=False,
            include_seasonality=False,
            include_basis=False,
        ),
        enumerate_candidates(
            include_funding=False,
            include_panel_nodes=False,
            include_metrics=False,
            include_seasonality=False,
            include_basis=False,
            max_complexity=8,
        ),
    ):
        assert [candidate.hash for candidate in result.candidates] == baseline["hashes"]
        assert {candidate.hash: str(candidate.expr) for candidate in result.candidates} == baseline["expressions"]
        assert result.evaluated == baseline["evaluated"]
        assert result.rejected == baseline["rejected"]

    # The grids are part of the recorded search space: widening one silently would move the 225 without
    # touching a line of expr.py.  Iterating the FIXTURE's keys tolerates parameters added later.
    parameters = inspect.signature(enumerate_candidates).parameters
    pinned = {name: value for name, value in baseline["defaults"].items() if name != "max_complexity"}
    declared = {
        name: list(parameter.default) if isinstance(parameter.default, tuple) else parameter.default
        for name, parameter in parameters.items()
        if name in pinned
    }
    assert declared == pinned

    # max_complexity is the one recorded default this delivery deliberately moves, so it is asserted
    # explicitly rather than pinned to the fixture.  The baseline records rejected["too_complex"] == 0,
    # so nothing that existed sat near the cap; the loop above proves the raise moves nothing.
    assert baseline["defaults"]["max_complexity"] == 8
    assert parameters["max_complexity"].default == 10


# --- the cost of the new family ---------------------------------------------------------------------


def test_the_funding_family_is_on_by_default_and_costs_what_was_pre_registered() -> None:
    """T-P17-08: the delta IS the trial charge, and an equal `rejected` is what catches a truncation."""
    without = enumerate_candidates(include_funding=False)
    full = enumerate_candidates()

    assert full.evaluated > without.evaluated  # on by default: _resolve_mined enumerates bare
    assert full.evaluated - without.evaluated <= 60  # the pre-registered budget
    assert {c.hash for c in without.candidates} <= {c.hash for c in full.candidates}
    # One ExprError closes a generator and silently discards the rest of the family while counting a
    # single `malformed`, so an unchanged rejected dict is the assertion that the family ran to the end.
    assert full.rejected == without.rejected
    assert full.declared_trials == full.evaluated


def _nodes(expr: Expr) -> list[Expr]:
    return [expr, *(node for child in expr.children() for node in _nodes(child))]


def _shape_and_sign(expr: Expr) -> tuple[str, str]:
    """Classify from the TREE, never from ``str(expr)``.

    ``Mul.canonical`` sorts operands by hash, so ``-1 * x`` and ``x * -1`` are the same tree rendered two
    ways: one of the six negated interactions prints with the constant on the RIGHT.  A string predicate
    keyed on a leading ``-1 *`` therefore reads that tree as the positive arm - which is how the first
    version of this test kept passing with one whole advertised shape deleted from the family.
    """
    nodes = _nodes(expr)
    sign = "short" if any(isinstance(n, Const) and n.value < 0 for n in nodes) else "long"
    if not any(isinstance(n, Funding) for n in nodes):
        return "not_carry", sign
    if isinstance(expr, CrossSectional):
        return "cs_ranked_carry", sign
    if any(isinstance(n, Sum) for n in nodes):
        return "momentum_plus_carry", sign
    if any(isinstance(n, Ret) for n in nodes):
        return "momentum_times_carry", sign
    return "squashed_carry", sign


def test_the_carry_family_emits_exactly_the_census_its_grids_declare() -> None:
    """T-P17-09: a full census, because 'at least one of each' is what let a deleted shape through.

    The counts are derived from the declared grids rather than hardcoded, so widening a grid flows
    through - but deleting or adding a ``yield`` does not.  That distinction matters because the family's
    size IS its charge against ``declared_trials``.
    """
    parameters = inspect.signature(enumerate_candidates).parameters
    windows = len(parameters["funding_windows"].default)
    horizons = len(parameters["funding_horizons"].default)
    scales = len(parameters["scales"].default)

    census: dict[tuple[str, str], int] = {}
    carry = []
    for candidate in enumerate_candidates().candidates:
        shape, sign = _shape_and_sign(candidate.expr)
        if shape == "not_carry":
            continue
        carry.append(candidate)
        census[shape, sign] = census.get((shape, sign), 0) + 1

    assert census == {
        ("squashed_carry", "long"): windows * scales,
        ("squashed_carry", "short"): windows * scales,
        ("cs_ranked_carry", "long"): windows,
        ("cs_ranked_carry", "short"): windows,
        # Both signs of the product, and the SHORT one is the ten-node tree: at max_complexity=8 it
        # vanishes into rejected["too_complex"] after being charged, which this census refuses silently.
        ("momentum_times_carry", "long"): windows * horizons,
        ("momentum_times_carry", "short"): windows * horizons,
        # The mix carries a positive carry weight only; its negation is reachable through shape one.
        ("momentum_plus_carry", "long"): windows * horizons,
    }

    # Every carry candidate declares the input it reads - the property `to_signal` derives `uses_funding`
    # from, asserted here on the ENUMERATED delta rather than only on hand-built trees.
    assert all(candidate.expr.reads_funding() for candidate in carry)

    # Funding never reaches the top of a tree un-normalised.  Only the cross-sectional half of this is a
    # live guard: `Squash(Funding(w))` cannot be constructed at all, since Dim.RETURN is not a ratio.
    assert not any(
        isinstance(candidate.expr, CrossSectional) and isinstance(candidate.expr.inner, Funding) for candidate in carry
    )


def test_the_two_max_complexity_defaults_agree() -> None:
    """The cap lives in two places, and nothing made them agree until this test.

    `enumerate_candidates(max_complexity=...)` and `research mine --max-complexity` are independent
    constants.  Mutating the library default alone left the CLI's recorded value at 10, so a report could
    claim a cap the search did not run under.
    """
    library = inspect.signature(enumerate_candidates).parameters["max_complexity"].default
    option = next(p for p in research_mine.params if p.name == "max_complexity")
    assert option.default == library


def test_every_funding_window_is_a_whole_number_of_settlements() -> None:
    """T-P17-10: funding settles every eight hours; a straddling window averages a fraction of one."""
    windows = [
        int(match)
        for candidate in enumerate_candidates().candidates
        for match in re.findall(r"funding\((\d+)\)", str(candidate.expr))
    ]
    assert windows
    assert all(window % 8 == 0 for window in windows)


def test_enumeration_is_deterministic_and_keyword_only() -> None:
    """T-P17-11: the property `_resolve_mined` relies on to re-derive an id without persisting one."""
    first, second = enumerate_candidates(), enumerate_candidates()
    assert [c.hash for c in first.candidates] == [c.hash for c in second.candidates]
    assert first.evaluated == second.evaluated
    assert first.rejected == second.rejected
    parameters = inspect.signature(enumerate_candidates).parameters
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())


# --- the leaf ---------------------------------------------------------------------------------------


def test_funding_is_a_return_so_every_shape_must_divide_it_by_volatility() -> None:
    """T-P17-02: the dimension system refuses the shortcut rather than discouraging it."""
    assert Funding(24).dim is Dim.RETURN
    assert Funding(24).lookback() == 24
    assert str(Funding(24)) == "funding(24)"

    carry = Ratio(Funding(24), Vol(48))
    assert carry.dim is Dim.RATIO
    assert carry.lookback() == 25  # Vol(48) needs 25; the funding window is shorter
    assert Ratio(Funding(168), Vol(48)).lookback() == 168

    with pytest.raises(ExprError, match="dimensionless ratio"):
        Squash(Funding(24), 1.0)  # a rate is not a score
    with pytest.raises(ExprError, match="dimensionless operands"):
        Mul(Const(-1.0), Funding(24))
    with pytest.raises(ExprError, match="cannot divide"):
        Ratio(Funding(24), VolumeRatio(24))
    with pytest.raises(ExprError, match="at least one bar"):
        Funding(0)


def test_the_leaf_is_exactly_the_shared_feature(funding_panel: Panel) -> None:
    """T-P17-03: values, not structure - and the declared lookback is deliberately not NaN-backed."""
    assert funding_panel.funding is not None
    _bit_for_bit(
        Funding(24).evaluate(funding_panel),
        features.funding_per_bar_to_8h(funding_panel.funding, 24),
    )
    # min_periods=1, so the first bar already carries a number.  Pinned so a change to the feature shows
    # up here as a visible test change rather than a silent shift in every mined carry candidate.
    assert bool(Funding(168).evaluate(funding_panel).iloc[0].notna().all())


def test_a_candidate_refuses_a_panel_that_carries_no_funding() -> None:
    """T-P17-04: KILL-027 at the leaf - refuse the input rather than evaluate something else."""
    panel = _panel(with_funding=False)
    assert panel.funding is None
    with pytest.raises(ExprError, match=r"panel\.funding"):
        Funding(24).evaluate(panel)


def test_reads_funding_recurses_through_every_composite() -> None:
    """T-P17-05: the predicate is a property of the tree, not of the node it happens to start at."""
    carry = Ratio(Funding(24), Vol(48))
    momentum = Ratio(Ret(72), Vol(48))
    assert Funding(24).reads_funding() is True
    assert Squash(carry, 1.0).reads_funding() is True
    assert CrossSectional(carry, "rank").reads_funding() is True
    assert Mul(Const(-1.0), carry).reads_funding() is True
    assert Squash(Sum(((0.5, momentum), (0.5, carry))), 1.0).reads_funding() is True
    assert ZScore(Funding(24), 72).reads_funding() is True

    assert Squash(momentum, 1.0).reads_funding() is False
    for leaf in (Const(1.0), Ret(24), Vol(48), VolumeRatio(12), TakerBuy(4), RangePosition(24)):
        assert leaf.reads_funding() is False


# --- the signal contract ----------------------------------------------------------------------------


def test_the_compiled_spec_declares_the_funding_it_actually_reads() -> None:
    """T-P17-06: ``to_signal`` hardcoded False, so a carry candidate lied to the D-023 startup gate."""
    carry = Candidate.of(Squash(Ratio(Funding(24), Vol(48)), 1.0))
    momentum = Candidate.of(Squash(Ratio(Ret(72), Vol(48)), 1.0))
    assert to_signal(carry).needs_funding({}) is True
    assert to_signal(momentum).needs_funding({}) is False


def test_a_carry_candidate_compiles_to_the_ordinary_signal_contract(funding_panel: Panel) -> None:
    """T-P17-07: the judge applies to a carry candidate unchanged, exactly as to a momentum one."""
    candidate = Candidate.of(Squash(Ratio(Funding(72), Vol(48)), 1.0))
    spec = to_signal(candidate)
    assert spec.id == f"mined_{candidate.hash}"
    assert spec.warmup_for({}) == candidate.lookback
    targets = spec.compute(funding_panel, spec.default_params)
    assert list(targets.columns) == list(funding_panel.close.columns)
    assert targets.abs().max().max() <= 1.0
    assert targets.notna().any().any()


# --- M-018: what the crowding modifier did, not merely that its input arrived ------------------------


def _tsmom_panel() -> Panel:
    """A panel whose trailing funding is monotone across symbols, so the rank is decisive not noise."""
    index = pd.date_range("2024-01-01", periods=1200, freq="h", tz="UTC")
    rng = np.random.default_rng(11)
    frames, funding = {}, {}
    stamps = index[::8]
    for offset, symbol in enumerate(("A", "B", "C", "D", "E")):
        close = pd.Series(100.0 * np.exp(rng.normal(0.0003, 0.004, len(index)).cumsum()), index=index)
        volume = pd.Series(rng.lognormal(10.0, 0.3, len(index)), index=index)
        frames[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.002,
                "low": close * 0.998,
                "close": close,
                "volume": volume,
                "quote_volume": volume * close,
            },
            index=index,
        )
        funding[symbol] = pd.Series((offset - 2) * 1e-4, index=stamps)
    return Panel.from_frames(frames, "1h", funding=pd.DataFrame(funding))


_CROWD = {"horizons": [168, 336, 720], "crowding_window": 72, "crowding_cut": 0.5, "crowding_penalty": 0.5}


def test_the_crowding_instrument_separates_a_shrink_from_a_decision() -> None:
    """M-018: under `sign` a shrink counts only when it drops the score under `entry_threshold`.

    The two numbers must be able to differ, or the instrument measures the proxy it was built to
    replace.  `shrunk` is what the modifier touched; `decisive` is what it changed.  Conflating them is
    how "the modifier is running" came to mean "its input arrived", which held for 37 live cycles while
    the modifier was inert (D-042's correction).
    """
    panel = _tsmom_panel()
    off = tsmom.crowding_effect(panel, {**_CROWD, "crowding_window": 0})
    assert off["enabled"] is False and off["shrunk"] == 0 and off["decisive"] == 0

    signed = tsmom.crowding_effect(panel, {**_CROWD, "conviction_mode": "sign"})
    scored = tsmom.crowding_effect(panel, {**_CROWD, "conviction_mode": "score"})
    assert signed["enabled"] is True
    assert signed["shrunk"] > 0, "the fixture no longer makes the modifier bite, so nothing below is tested"
    assert scored["decisive"] == scored["shrunk"]  # every shrink changes a score-mode book
    assert signed["eligible"] >= signed["shrunk"]
    # The whole point of two counts: on this fixture sign mode absorbs the shrink entirely.  Asserted as
    # a STRICT inequality - `decisive <= shrunk` is satisfied by an instrument that simply reports the
    # shrink twice, which is the degenerate form this measurement exists to replace.
    assert signed["decisive"] < signed["shrunk"], (
        "the fixture no longer separates a shrink from a decision, so this test proves nothing"
    )


def test_the_crowding_mask_is_the_one_the_modifier_applies() -> None:
    """The instrument reads the same mask the shrink does, not a re-derivation that could drift."""
    panel = _tsmom_panel()
    p = tsmom.TsmomParams.from_mapping(_CROWD)
    raw = tsmom.tsmom_scores(panel.close, p)
    mask = tsmom.crowding_mask(raw, panel.funding, p, panel.reference)
    assert mask is not None and bool(mask.to_numpy().any())
    pd.testing.assert_frame_equal(
        tsmom.apply_crowding_modifier(raw, panel.funding, p, panel.reference),
        raw.mask(mask, raw * (1.0 - p.crowding_penalty)),
    )
    disabled = tsmom.TsmomParams.from_mapping({**_CROWD, "crowding_window": 0})
    assert tsmom.crowding_mask(raw, panel.funding, disabled, None) is None


def test_the_positioning_family_is_on_by_default_and_costs_what_was_pre_registered() -> None:
    """DL-D4, in the shape T-P17-08 established: the delta IS the trial charge.

    Ninety candidates - three open-interest windows and two long/short windows, each with two ranked
    arms, three scales in both signs, and five momentum interactions in both signs.  Pre-registered as
    a budget rather than discovered: a family that costs whatever it happens to cost is a family whose
    price is set after its results are known.

    It was 60 for as long as the interaction's momentum leg took `funding_horizons` (two values).  That
    was a mistake rather than a choice - a return over a horizon belongs to `horizons`, the dimension an
    operator rescales when the interval changes - and T-P19's rescale test found it by reading `ret(72)`
    out of a search whose horizons had been overridden to {1, 3, 7}.  Corrected before anything was run,
    which is the only time a pre-registered budget may move.

    The subset assertion is the one that matters most.  Every hash of the smaller space must survive
    into the larger one, because `_resolve_mined` re-derives an id by enumerating, and an id in the
    ledger that no longer enumerates is a candidate this system can no longer name.
    """
    without = enumerate_candidates(include_metrics=False)
    full = enumerate_candidates()

    assert full.evaluated - without.evaluated == 90
    assert {c.hash for c in without.candidates} <= {c.hash for c in full.candidates}
    assert full.rejected == without.rejected, "a growing family must not start rejecting the old one"
    # And the space's identity moved, which is what R2 reads to decide a re-run is a NEW search.
    assert full.space_digest != without.space_digest


def test_only_the_positioning_family_reads_the_metrics_columns() -> None:
    """A node that reads a column without declaring it is KILL-027 one column over."""
    reading = {c.hash for c in enumerate_candidates().candidates if c.expr.reads_metrics()}
    without = {c.hash for c in enumerate_candidates(include_metrics=False).candidates}
    assert reading and not (reading & without)
    assert len(reading) == 90
