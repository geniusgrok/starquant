"""DL-A1: five expression nodes that read only columns the panel already carries.

Phase A step 4.  P17 judged the bottleneck to be expressible space rather than proposers, and
KILL-R28 drew the line these five sit behind: a node that needs a *new* panel field re-opens the
"research panel superset of live panel" obligation (KILL-027 / P1-01) and belongs in Phase B with the
ingestion that feeds it.  These read ``close``, ``quote_volume`` and ``trades`` - all present, all
already flowing to the live loop.

What they add that the existing twelve cannot express:

* ``Abs`` - magnitude without direction, which is what turns a return into a "how much did it move"
  and lets a surprise be z-scored;
* ``Moment`` - rolling skewness and kurtosis, the two shapes a mean and a variance cannot see;
* ``Semi`` - downside semideviation, so "risk" can mean the half of the distribution that hurts;
* ``Residual`` - the part of a symbol's return the market did not explain (residual momentum);
* ``TradeSize`` - average trade size against its own trailing mean, the one thing ``trades`` says
  that ``quote_volume`` does not: whether the same volume arrived in few large prints or many small.

``Residual`` is cross-sectional, so it takes the market from ``panel.reference`` and not from
whichever columns the caller happened to load.  That is P1-01's contract, and a promoted candidate
that ignored it would re-open the defect the hand-written signals just closed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining.expr import Abs, Const, Dim, ExprError, Moment, Residual, Ret, Semi, TradeSize, Vol
from starquant_alpha.panel import Panel
from tests.alpha.test_causality import _bit_for_bit


def _panel(n: int = 400, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"), *, trades: bool = True) -> Panel:
    rng = np.random.default_rng(11)
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(n, len(symbols))), axis=0)),
        index=index,
        columns=list(symbols),
    )
    volume = pd.DataFrame(rng.lognormal(10, 0.5, size=(n, len(symbols))), index=index, columns=list(symbols))
    counts = pd.DataFrame(rng.integers(50, 5_000, size=(n, len(symbols))), index=index, columns=list(symbols)).astype(
        float
    )
    return Panel(
        interval="1h",
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=volume,
        quote_volume=volume,
        trades=counts if trades else None,
    )


# --- Abs ---------------------------------------------------------------------------------------


def test_abs_keeps_the_dimension_and_drops_the_sign() -> None:
    node = Abs(Ret(24))

    assert node.dim is Dim.RETURN
    values = node.evaluate(_panel())
    assert (values.dropna() >= 0).all().all()


def test_abs_of_a_price_is_refused() -> None:
    """A price is already non-negative; |price| is the price, so the node would be a no-op wearing a hat."""
    from starquant_alpha.mining.expr import RangePosition

    with pytest.raises(ExprError):
        Abs(_PriceNode())

    # and a legal one still constructs
    Abs(RangePosition(24))


def test_abs_of_abs_folds() -> None:
    """Canonicalisation: two trees that mean the same thing must hash the same."""
    once, twice = Abs(Ret(24)), Abs(Abs(Ret(24)))

    assert twice.canonical_hash() == once.canonical_hash()


def test_abs_reports_its_childs_lookback() -> None:
    assert Abs(Ret(24)).lookback() == Ret(24).lookback()


# --- Moment ------------------------------------------------------------------------------------


def test_moment_is_dimensionless_whatever_goes_in() -> None:
    """Standardised by construction: a skewness of returns and of a ratio are the same kind of number."""
    assert Moment(Ret(1), 3, 168).dim is Dim.RATIO
    assert Moment(Vol(24), 4, 168).dim is Dim.RATIO


def test_only_skewness_and_kurtosis_are_offered() -> None:
    with pytest.raises(ExprError):
        Moment(Ret(1), 2, 168)  # that is the variance, and Vol already says it
    with pytest.raises(ExprError):
        Moment(Ret(1), 5, 168)


def test_a_moment_window_must_hold_enough_points_to_mean_anything() -> None:
    with pytest.raises(ExprError):
        Moment(Ret(1), 3, 10)


def test_skewness_of_a_symmetric_series_is_near_zero() -> None:
    node = Moment(Ret(1), 3, 240)

    values = node.evaluate(_panel(n=600)).dropna()

    assert abs(float(values.to_numpy().mean())) < 0.5


def test_moment_declares_a_lookback_that_covers_its_child() -> None:
    node = Moment(Ret(24), 3, 168)

    assert node.lookback() >= 168 + Ret(24).lookback() - 1


# --- Semi --------------------------------------------------------------------------------------


def test_semi_is_a_downside_magnitude() -> None:
    node = Semi(Ret(1), 168)

    assert node.dim is Dim.RETURN
    values = node.evaluate(_panel()).dropna()
    assert (values >= 0).all().all()


def test_semi_of_a_series_that_never_falls_is_zero() -> None:
    """The definition, stated as a test: only the losing half counts."""
    index = pd.date_range("2024-01-01", periods=300, freq="1h", tz="UTC")
    rising = pd.DataFrame({"AAA": np.linspace(100.0, 200.0, 300)}, index=index)
    panel = Panel(interval="1h", open=rising, high=rising, low=rising, close=rising, volume=rising, quote_volume=rising)

    values = Semi(Ret(1), 168).evaluate(panel).dropna()

    assert float(values.to_numpy().max()) == pytest.approx(0.0, abs=1e-12)


def test_semi_refuses_a_dimensionless_score() -> None:
    """Semideviation of a bounded score is a number without a use; the type system should say so."""
    with pytest.raises(ExprError):
        Semi(Const(1.0), 168)


# --- Residual ----------------------------------------------------------------------------------


def test_residual_removes_the_market() -> None:
    """A panel whose symbols move together should leave almost nothing behind."""
    index = pd.date_range("2024-01-01", periods=500, freq="1h", tz="UTC")
    rng = np.random.default_rng(5)
    market = np.cumsum(rng.normal(0, 0.01, size=500))
    close = pd.DataFrame({name: 100.0 * np.exp(market) for name in ("AAA", "BBB", "CCC")}, index=index)
    panel = Panel(interval="1h", open=close, high=close, low=close, close=close, volume=close, quote_volume=close)

    values = Residual(Ret(1), 240).evaluate(panel).dropna()

    assert float(np.abs(values.to_numpy()).max()) < 1e-6


def test_residual_uses_the_reference_population_not_the_loaded_columns() -> None:
    """P1-01's contract.  A candidate that ignored it would re-open what the signals just closed."""
    panel = _panel(n=500, symbols=("AAA", "BBB", "CCC", "DDD"))
    reference = pd.DataFrame(True, index=panel.close.index, columns=panel.close.columns)
    reference["DDD"] = False

    full = Residual(Ret(1), 240).evaluate(panel)
    narrowed = Residual(Ret(1), 240).evaluate(panel.with_reference(reference))

    assert not np.allclose(full["AAA"].dropna().to_numpy(), narrowed["AAA"].dropna().to_numpy())


def test_residual_keeps_the_return_dimension() -> None:
    assert Residual(Ret(24), 240).dim is Dim.RETURN


def test_residual_refuses_a_price() -> None:
    with pytest.raises(ExprError):
        Residual(_PriceNode(), 240)


# --- TradeSize ---------------------------------------------------------------------------------


def test_trade_size_is_a_ratio_to_its_own_trailing_mean() -> None:
    node = TradeSize(168)

    assert node.dim is Dim.RATIO
    values = node.evaluate(_panel(n=500)).dropna()
    assert float(values.to_numpy().mean()) == pytest.approx(1.0, abs=0.4)


def test_trade_size_refuses_a_panel_without_trade_counts() -> None:
    """KILL-027: a signal must refuse to run on inputs it did not have when it was judged."""
    with pytest.raises(ExprError, match="trades"):
        TradeSize(168).evaluate(_panel(trades=False))


def test_trade_size_survives_a_bar_with_no_trades() -> None:
    """Zero prints is a real bar on a thin symbol, not a division to crash on."""
    panel = _panel(n=300)
    assert panel.trades is not None
    counts = panel.trades.copy()
    counts.iloc[100, 0] = 0.0

    values = TradeSize(168).evaluate(Panel(**{**vars(panel), "trades": counts}))

    assert np.isfinite(values.to_numpy()[~np.isnan(values.to_numpy())]).all()


# --- shared contracts --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node",
    [Abs(Ret(24)), Moment(Ret(1), 3, 168), Semi(Ret(1), 168), Residual(Ret(1), 240), TradeSize(168)],
)
def test_no_node_reads_the_future(node: object) -> None:
    """The causality contract: replacing data after a cutoff must not move anything before it."""
    panel = _panel(n=500)
    cutoff = 400
    rng = np.random.default_rng(99)
    tampered_close = panel.close.copy()
    tampered_close.iloc[cutoff:] *= 1.0 + rng.normal(0, 0.2, size=tampered_close.iloc[cutoff:].shape)
    tampered_volume = panel.quote_volume.copy() if panel.quote_volume is not None else None
    if tampered_volume is not None:
        tampered_volume.iloc[cutoff:] *= 3.0
    tampered_trades = panel.trades.copy() if panel.trades is not None else None
    if tampered_trades is not None:
        tampered_trades.iloc[cutoff:] *= 7.0

    before = node.evaluate(panel).iloc[:cutoff]  # type: ignore[attr-defined]
    after = node.evaluate(  # type: ignore[attr-defined]
        Panel(
            **{
                **vars(panel),
                "close": tampered_close,
                "open": tampered_close,
                "high": tampered_close,
                "low": tampered_close,
                "quote_volume": tampered_volume,
                "trades": tampered_trades,
            }
        )
    ).iloc[:cutoff]

    _bit_for_bit(before, after)


@pytest.mark.parametrize(
    "node",
    [Abs(Ret(24)), Moment(Ret(1), 3, 168), Semi(Ret(1), 168), Residual(Ret(1), 240), TradeSize(168)],
)
def test_every_node_declares_a_lookback_it_actually_needs(node: object) -> None:
    """E-042: understating a warmup is the failure mode; a node must never claim to need nothing."""
    assert node.lookback() >= 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "node",
    [Abs(Ret(24)), Moment(Ret(1), 3, 168), Semi(Ret(1), 168), Residual(Ret(1), 240), TradeSize(168)],
)
def test_hashes_are_stable_across_construction(node: object) -> None:
    assert node.canonical_hash() == node.canonical_hash()  # type: ignore[attr-defined]


# Captured on main at 56dc5dc, before these five nodes existed.  `1ce07bec1af7a710` is P19's first
# candidate, so these are live identities in reports/research/trials.jsonl, not synthetic ones.
FROZEN_HASHES = {
    "ret(24)": "63e9f1f6bb020eac",
    "vol(168)": "4865b62b74f2f925",
    "cs_rank(z(ret(7),7))": "1ce07bec1af7a710",
    "squash(rangepos(168),2)": "503368238d55d847",
    "volratio(24)": "d25da494be1c4346",
    "takerbuy(24)": "8525bd9dd92cdabb",
    "funding(72)": "6f1e3135d7d4388f",
    "ratio(ret(24),vol(24))": "56e6952bd11edea0",
    "sum(ret(24),ret(168))": "1945cf3a86f0885f",
    "mul(volratio(24),const(2))": "301cacc675d09385",
}


def test_adding_these_nodes_does_not_rename_the_existing_candidates() -> None:
    """T-A1-3: an id that moves when the language grows orphans every ledger row that cites it.

    KILL-R16 asked whether the hash is stable under new nodes.  It is - the signature is built from
    the node's own KIND and fields, so a sibling class cannot reach it - and this is the assertion
    that keeps it that way.  If a future change does have to move ids, the ledger needs a search
    space version before it lands, not after.
    """
    from starquant_alpha.mining.expr import (
        Const,
        CrossSectional,
        Mul,
        RangePosition,
        Squash,
        Sum,
        TakerBuy,
        VolumeRatio,
        ZScore,
    )
    from starquant_alpha.mining.expr import Funding as F
    from starquant_alpha.mining.expr import Ratio as R

    now = {
        "ret(24)": Ret(24),
        "vol(168)": Vol(168),
        "cs_rank(z(ret(7),7))": CrossSectional(ZScore(Ret(7), 7), "rank"),
        "squash(rangepos(168),2)": Squash(RangePosition(168), 2.0),
        "volratio(24)": VolumeRatio(24),
        "takerbuy(24)": TakerBuy(24),
        "funding(72)": F(72),
        "ratio(ret(24),vol(24))": R(Ret(24), Vol(24)),
        "sum(ret(24),ret(168))": Sum(((1.0, Ret(24)), (1.0, Ret(168)))),
        "mul(volratio(24),const(2))": Mul(VolumeRatio(24), Const(2.0)),
    }

    assert {name: node.canonical_hash() for name, node in now.items()} == FROZEN_HASHES


def _PriceNode() -> object:
    from dataclasses import dataclass
    from typing import ClassVar

    from starquant_alpha.mining.expr import Expr

    @dataclass(frozen=True)
    class _Price(Expr):
        KIND: ClassVar[str] = "_price"

        @property
        def dim(self) -> Dim:
            return Dim.PRICE

        def evaluate(self, panel: Panel) -> pd.DataFrame:
            return panel.close

        def describe(self) -> str:
            return "price"

    return _Price()
