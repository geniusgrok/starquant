"""DL-D5, block 2: the basis leaf, the family it heads, and the two refusals that make it safe to search.

Four claims, each with a specific defect behind it.

SAME BAR.  `Basis` is `log(perp_close / spot_close)` on one bar and reads nothing else, so truncating the
panel cannot change a value that survived the truncation.  The rival - "the latest spot bar available" -
is what `metrics.align_to_bars` does correctly for open interest and what would price XMRUSDT's halted
listing (spot 118.70 since 2024-02-20, perp 503.83) at +324% for two years.

MISSING IS MISSING.  166 of 528 perpetuals have no spot leg.  A NaN that becomes a 0.0 anywhere on the
way to a score is a symbol trading at parity with a spot market that does not exist.

LOUD WHEN UNWIRED.  A panel with no spot at all raises where the node is written.  `research mine`
enumerated the DL-D4 metrics leaves against a panel loaded without metrics for two whole rounds; the 90
`ExprError`s per round are the only reason that was findable at all.

RISK-G3 BINDS ON LIVE, NOT ON THE PANEL.  `starquant_live.composition.load_panel` builds the RESEARCH panel
too, so a refusal there would make this family unminable rather than untradeable.  The refusal is at
startup, on the strategies that declare `needs_spot`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining.expr import (
    Basis,
    Const,
    CrossSectional,
    Dim,
    ExprError,
    Funding,
    Mul,
    Ratio,
    Squash,
    Sum,
    Vol,
    ZScore,
)
from starquant_alpha.mining.search import _basis_family, enumerate_candidates, to_signal
from starquant_alpha.panel import Panel
from starquant_data.alignment import PASS, SPOT_BASIS_COLUMN, UNVERIFIABLE, Verification
from starquant_live.engine import spot_refusal
from tests.alpha.test_causality import _bit_for_bit

BARS = pd.date_range("2024-01-01", periods=64, freq="h", tz="UTC")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "FARTCOINUSDT")


def _panel(spot_close: pd.DataFrame | None = None) -> Panel:
    rng = np.random.default_rng(11)
    frames = {}
    for offset, symbol in enumerate(SYMBOLS):
        close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, len(BARS))) + offset)
        frames[symbol] = pd.DataFrame(
            {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1_000.0},
            index=BARS,
        )
    if spot_close is None:
        return Panel.from_frames(frames, "1h")
    return Panel.from_frames(frames, "1h", spot={"close": spot_close, "quote_volume": spot_close * 10.0})


def _spot_from(panel: Panel, ratio: float = 0.99) -> pd.DataFrame:
    """A spot leg a fixed ratio below the perpetual, so the expected basis is a known constant."""
    return panel.close * ratio


# --- the leaf ----------------------------------------------------------------------------------------


def test_the_basis_is_the_log_ratio_of_the_two_closes_on_the_same_bar() -> None:
    """The definition, asserted rather than described: nothing rolls, nothing shifts, nothing fills."""
    bare = _panel()
    panel = _panel(_spot_from(bare, 0.99))
    basis = Basis().evaluate(panel)

    assert basis.shape == panel.close.shape
    assert np.allclose(basis.to_numpy(), np.log(1 / 0.99))
    # Cell by cell against the arithmetic, so a future vectorisation cannot quietly change the meaning.
    expected = np.log(panel.close.to_numpy() / panel.spot_field("close").to_numpy())  # type: ignore[union-attr]
    assert np.allclose(basis.to_numpy(), expected, equal_nan=True)


def test_truncating_the_panel_leaves_every_surviving_basis_value_identical() -> None:
    """Causality, stated as the property that distinguishes a same-bar read from every other rule.

    A leaf that read the NEXT spot bar would answer differently once the next bar stopped existing, and
    a leaf that carried a trailing window would answer differently near the new left edge.  This one
    answers the same, which is the only shape that can be true of a value computed from bar t alone.
    """
    bare = _panel()
    panel = _panel(_spot_from(bare, 0.985))
    full = Basis().evaluate(panel)

    cut = len(BARS) // 2
    index = BARS[:cut]
    trimmed = Panel.from_frames(
        {
            symbol: pd.DataFrame(
                {
                    field: getattr(panel, field)[symbol].loc[index]
                    for field in ("open", "high", "low", "close", "volume")
                }
            )
            for symbol in panel.symbols
        },
        "1h",
        spot={name: frame.loc[index] for name, frame in (panel.spot or {}).items()},
    )
    short = Basis().evaluate(trimmed)

    # `full.loc[index]` takes the name of the unnamed index it was sliced with; `short` keeps `open_time`.
    _bit_for_bit(short, full.loc[index], check_names=False)


def test_a_halted_spot_listing_is_nan_on_every_later_bar_rather_than_its_last_price() -> None:
    """XMRUSDT's shape.  The forward fill is the helpful thing to add and it is worth +324% of nothing."""
    bare = _panel()
    spot = _spot_from(bare, 0.99)
    spot.iloc[32:, spot.columns.get_loc("ETHUSDT")] = np.nan
    basis = Basis().evaluate(_panel(spot))

    assert basis["ETHUSDT"].iloc[:32].notna().all()
    assert basis["ETHUSDT"].iloc[32:].isna().all(), "a halted listing may not be carried forward"
    assert (basis["ETHUSDT"].iloc[32:] == 0.0).sum() == 0, "and it may not become a zero either"
    assert basis["BTCUSDT"].notna().all(), "one symbol's hole is not another's"


def test_a_perpetual_with_no_spot_leg_scores_nan_and_never_zero() -> None:
    """The 166 of 528.  Zero is a real basis - it means "trading exactly at spot" - so it is the one
    wrong answer that cannot be told apart from a right one downstream."""
    bare = _panel()
    spot = _spot_from(bare, 0.99)
    spot["FARTCOINUSDT"] = np.nan
    basis = Basis().evaluate(_panel(spot))

    assert basis["FARTCOINUSDT"].isna().all()
    assert not (basis["FARTCOINUSDT"] == 0.0).any()
    # And it survives the normalisation every shape in the family applies.
    assert Ratio(Basis(), Vol(8)).evaluate(_panel(spot))["FARTCOINUSDT"].isna().all()


def test_a_non_positive_close_on_either_leg_is_nan_rather_than_an_infinite_score() -> None:
    """`np.log(0)` answers -inf without raising, and `tanh(-inf)` is a full-size -1.0 position on a
    symbol whose data is broken.  Both legs are masked, because either one can be the broken one."""
    bare = _panel()
    spot = _spot_from(bare, 0.99)
    spot.iloc[5, spot.columns.get_loc("BTCUSDT")] = 0.0
    spot.iloc[6, spot.columns.get_loc("BTCUSDT")] = -1.0
    basis = Basis().evaluate(_panel(spot))

    assert basis["BTCUSDT"].iloc[5:7].isna().all()
    assert np.isfinite(basis.to_numpy()[~np.isnan(basis.to_numpy())]).all()


def test_a_panel_that_carries_no_spot_raises_where_the_node_is_written() -> None:
    """DL-D4's lesson, applied before it can be repeated: silence here is a family that scores nothing
    and reports a count.  The message names both the node and the field it wanted."""
    with pytest.raises(ExprError, match=r"basis needs panel.spot\['close'\]"):
        Basis().evaluate(_panel())


# --- types, warmup, identity -------------------------------------------------------------------------


def test_the_basis_is_a_return_so_the_type_system_forces_the_normalisation() -> None:
    """A log price ratio is dimensionally a log return, so nothing may squash or multiply it raw.

    Not ceremony: the basis has a zero that no-arbitrage fixes in the same place for every symbol, but
    not a common SCALE, so a cross-sectional rank of the un-normalised level would mostly rank symbols
    by their volatility.
    """
    assert Basis().dim is Dim.RETURN
    with pytest.raises(ExprError, match="squash needs a dimensionless ratio"):
        Squash(Basis(), 1.0)  # type: ignore[arg-type]
    with pytest.raises(ExprError, match="mul needs dimensionless operands"):
        Mul(Basis(), Basis())  # type: ignore[arg-type]
    assert Ratio(Basis(), Vol(48)).dim is Dim.RATIO
    # Same dimension as the carry leaf, which is what lets a residual be WRITTEN even though the family
    # deliberately does not ship one - see `_basis_family` on `Sum`'s fill_value.
    assert Sum(((1.0, Basis()), (-1.0, Funding(24)))).dim is Dim.RETURN


def test_the_basis_reserves_exactly_one_bar_because_it_reads_exactly_one() -> None:
    """E-042 punishes understating a warmup; there is no warmup here to understate."""
    assert Basis().lookback() == 1
    assert Ratio(Basis(), Vol(48)).lookback() == 25  # the vol leg is the whole of it
    assert ZScore(Basis(), 72).lookback() == 73


def test_reads_spot_recurses_through_every_composite_and_stays_out_of_the_hash() -> None:
    """Mirrors the `reads_funding` test one source over, including the half that matters: a METHOD, so
    `signature()` cannot see it and no existing candidate's id moves."""
    carry = Ratio(Basis(), Vol(48))
    assert Basis().reads_spot() is True
    assert Squash(carry, 1.0).reads_spot() is True
    assert CrossSectional(carry, "rank").reads_spot() is True
    assert Mul(Const(-1.0), carry).reads_spot() is True
    assert Squash(Sum(((0.5, Ratio(Funding(24), Vol(48))), (0.5, carry))), 1.0).reads_spot() is True
    assert ZScore(Basis(), 72).reads_spot() is True

    assert Ratio(Funding(24), Vol(48)).reads_spot() is False
    assert Funding(24).reads_spot() is False
    assert Vol(48).reads_spot() is False

    assert "reads_spot" not in str(Basis().signature())
    assert Basis().canonical_hash() == Basis().canonical_hash()
    assert Basis().canonical_hash() != Funding(1).canonical_hash()


# --- the family ---------------------------------------------------------------------------------------


def test_the_family_is_eighteen_shapes_that_all_fit_under_both_caps() -> None:
    """`hod(60)` reserved 1464 bars and lost all eighteen of its shapes to `too_long` while the grid
    still claimed three windows.  A rejection count is not a failure, so the arithmetic is asserted."""
    shapes = list(_basis_family(48, (0.5, 1.0, 2.0), (24, 72, 168, 336, 720), 1.0))

    assert len(shapes) == 18
    assert max(shape.lookback() for shape in shapes) == 721, "ret(720) + 1, and Vol(48)'s 25 under it"
    assert max(shape.lookback() for shape in shapes) < 1_400
    assert max(shape.complexity() for shape in shapes) == 10, "the negated interaction; the sign costs two"
    assert all(shape.dim is Dim.SCORE for shape in shapes)
    assert all(shape.reads_spot() for shape in shapes)
    # Both signs, exactly paired: every shape's mirror is in the family, which is what makes "a basis
    # candidate ranked first" uninformative and its MARGIN the only readable number.
    assert len({shape.canonical_hash() for shape in shapes}) == 18


def test_the_switch_adds_exactly_the_basis_shapes_and_moves_nothing_else() -> None:
    """`include_basis` is a search-space parameter of the same kind as `include_funding`: deterministic,
    data-free, and off-able, because a frozen space stops being one the moment growth cannot be."""
    off = enumerate_candidates(include_basis=False)
    on = enumerate_candidates(include_basis=True)

    off_hashes = [candidate.hash for candidate in off.candidates]
    added = [candidate for candidate in on.candidates if candidate.hash not in set(off_hashes)]

    assert len(added) == 18
    assert all(candidate.expr.reads_spot() for candidate in added)
    assert not any(candidate.expr.reads_spot() for candidate in off.candidates)
    assert len(on.candidates) == len(off.candidates) + 18
    # Nothing was silently dropped on the way in.  A `too_long` or `too_complex` count would mean the
    # declared grid and the searched grid are different objects.
    assert on.rejected == off.rejected == {"malformed": 0, "duplicate": 0, "too_complex": 0, "too_long": 0}
    assert off_hashes == [candidate.hash for candidate in enumerate_candidates(include_basis=False).candidates]


def test_a_basis_candidate_compiles_into_a_spec_that_declares_it_reads_spot() -> None:
    """The inherited WIP defined `Expr.reads_spot` and never called it.  A declaration nothing declares
    to is the shape this repository keeps finding - `uses_funding` hardcoded to False was the same bug
    (T-P17-06), and it reached live."""
    on = enumerate_candidates(include_basis=True)
    basis_candidate = next(c for c in on.candidates if c.expr.reads_spot())
    plain = next(c for c in on.candidates if not c.expr.reads_spot())

    assert to_signal(basis_candidate).needs_spot is not None
    assert to_signal(basis_candidate).needs_spot({}) is True  # type: ignore[misc]
    assert to_signal(plain).needs_spot({}) is False  # type: ignore[misc]
    # And the other two declarations still answer for themselves on the same candidate.
    assert to_signal(basis_candidate).needs_funding({}) is False


def test_a_panel_counts_the_symbols_that_actually_have_a_spot_leg() -> None:
    """`spot is not None` says spot was REQUESTED.  `mine` narrows its space on this instead, which is
    what keeps 18 unscoreable shapes out of `declared_trials`."""
    bare = _panel()
    spot = _spot_from(bare, 0.99)
    spot["FARTCOINUSDT"] = np.nan

    assert _panel().spot_symbols == 0
    assert _panel(spot).spot_symbols == 2
    assert _panel(_spot_from(bare, 0.99)).spot_symbols == 3


# --- RISK-G3 at the live boundary ----------------------------------------------------------------------


def test_a_spot_reading_strategy_is_refused_at_startup_until_the_offset_has_been_shown() -> None:
    """Fail-closed on a root nobody measured, which was every root until `starquant data spot` took the
    measurement (see `tests/data/test_the_spot_stamp_measurement_is_taken_and_recorded.py`).

    "Nobody has shown the offset" and "the offset is wrong" are the same answer to "may this trade".
    """
    assert spot_refusal(needs_spot=[], verification=None) is None, "it costs nothing to anything else"

    refusal = spot_refusal(needs_spot=["mined_abc"], verification=None)
    assert refusal is not None
    assert "mined_abc" in refusal and "no verification on record" in refusal


def test_a_failed_or_unverifiable_spot_verification_refuses_exactly_like_a_missing_one() -> None:
    """The rivals are the evidence.  A sample that cannot tell the declared offset from its neighbours
    answers UNVERIFIABLE, and UNVERIFIABLE is a refusal - not-yet-shown and shown-false are both "no"."""
    unverifiable = Verification(UNVERIFIABLE, "the values do not move enough", 100, 100)
    refusal = spot_refusal(needs_spot=["mined_abc"], verification=unverifiable)
    assert refusal is not None and UNVERIFIABLE in refusal


def test_a_spot_verification_that_never_compared_the_close_does_not_admit_the_close() -> None:
    """The column-blind hole, closed one feed over.  On 2026-09-09 four of the six metrics columns had
    no live counterpart at all while M-011 read `rate: 0.0` over data it never compared."""
    neighbours = Verification(PASS, "744/744", 744, 744, (), ("spot_open", "spot_high"), ("spot_close",))
    refusal = spot_refusal(needs_spot=["mined_abc"], verification=neighbours)
    assert refusal is not None and "never compared spot_close" in refusal

    compared = Verification(PASS, "744/744", 744, 744, (), (SPOT_BASIS_COLUMN,), ())
    assert spot_refusal(needs_spot=["mined_abc"], verification=compared) is None
