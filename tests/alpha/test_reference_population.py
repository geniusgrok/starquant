"""P1-01 / DL-Q1: the cross-sectional reference population is an explicit contract.

The defect this file exists to prevent: ``apply_crowding_modifier`` ranks over
``score.columns`` and ``flow`` demeans over every column, so the population a
cross-sectional operator sees is whatever happens to be in the panel.  Research
builds the panel from every symbol that was *ever* a member (205 on the
point-in-time universe) and applies the membership mask only *after* the scores
exist; the live loop builds it from the symbols it manages that day (15-18).  The
same registry parameters therefore describe two different signals - KILL-027's
shape, on the one modifier that is enabled and on the flow probe's demean.

The contract: ``Panel.reference`` is a boolean frame (bars x symbols) naming the
population.  It restricts ranking / demeaning / breadth ONLY - never the time
series a rolling window reads, because masking the panel itself would make a
symbol that re-enters the universe start its ``rolling(72)`` from NaN while the
live path (which always requests full history) would not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.mining import CrossSectional, Ret
from starquant_alpha.panel import Panel
from starquant_alpha.signals import SIGNALS, get_signal
from starquant_alpha.signals.carry import CarryParams, carry_scores
from starquant_alpha.signals.flow import FlowParams, flow_scores
from starquant_alpha.signals.tsmom import TsmomParams, apply_crowding_modifier, tsmom_scores
from tests.alpha.test_causality import _bit_for_bit
from tests.alpha.test_signal_suite import _synthetic_panel

# Params under which each signal actually consults the cross-section.  tsmom's shipped
# default has ``crowding_window`` 0 (the modifier off), so the registry value is used here:
# a signal that does not look at the population cannot demonstrate the contract.
CROSS_SECTIONAL_PARAMS: dict[str, dict[str, object]] = {
    "tsmom": {
        "horizons": [24, 48, 72],
        "horizon_weights": [0.2, 0.3, 0.5],
        "crowding_window": 72,
        "crowding_cut": 0.7,
        "crowding_penalty": 0.5,
    },
    "flow": {"cross_sectional": True, "short_gate": 0.0},
    "carry": {"mode": "rank", "window_bars": 72, "min_symbols": 3},
    "xsmom": {"horizons": [24, 48, 72], "horizon_weights": [0.2, 0.3, 0.5], "vol_window": 100, "min_symbols": 3},
    "breakout": {},
}
CROSS_SECTIONAL_SIGNALS = tuple(CROSS_SECTIONAL_PARAMS)


def _with_reference(panel: Panel, symbols: list[str]) -> Panel:
    mask = pd.DataFrame(False, index=panel.index, columns=panel.close.columns)
    mask[symbols] = True
    return panel.with_reference(mask)


def test_panel_reference_defaults_to_every_column() -> None:
    """No reference supplied = today's behaviour: the population is the panel."""
    panel = _synthetic_panel(seed=1, n_symbols=5, n_bars=400)
    assert panel.reference is None
    assert list(panel.reference_mask().columns) == panel.symbols
    assert panel.reference_mask().all().all()


def test_reference_survives_slice_tail_and_select() -> None:
    """A panel that carries a population must still carry it after the usual reshaping."""
    panel = _synthetic_panel(seed=2, n_symbols=6, n_bars=500)
    subset = panel.symbols[:3]
    referenced = _with_reference(panel, subset)
    for reshaped in (referenced.tail(100), referenced.slice(panel.index[10], panel.index[-1])):
        assert reshaped.reference is not None
        assert list(reshaped.reference.columns) == panel.symbols
        assert reshaped.reference[subset].all().all()
        assert not reshaped.reference[panel.symbols[3]].any()
    picked = referenced.select([*subset, panel.symbols[3]])
    assert picked.reference is not None and list(picked.reference.columns) == [*subset, panel.symbols[3]]


@pytest.mark.parametrize("signal_id", CROSS_SECTIONAL_SIGNALS)
def test_scores_depend_on_the_reference_not_on_extra_columns(signal_id: str) -> None:
    """The heart of P1-01.

    A 12-symbol panel whose reference names 5 symbols must score those 5 exactly
    as a panel built from only those 5 symbols does.  Today every one of these
    signals fails this: the extra 7 columns move the rank, the demeaned mean or
    the breadth share.
    """
    spec = get_signal(signal_id)
    params = {**spec.default_params, **CROSS_SECTIONAL_PARAMS[signal_id]}
    wide = _synthetic_panel(seed=7, n_symbols=12, n_bars=1600)
    members = wide.symbols[:5]
    narrow = wide.select(members)

    referenced = spec.compute(_with_reference(wide, members), params)
    isolated = spec.compute(narrow, params)

    _bit_for_bit(referenced[members], isolated, check_names=False)


@pytest.mark.parametrize("signal_id", CROSS_SECTIONAL_SIGNALS)
def test_scores_move_when_the_reference_moves(signal_id: str) -> None:
    """The mask must be load-bearing: a different population is a different signal.

    Without this, ``test_scores_depend_on_the_reference_not_on_extra_columns``
    could be satisfied by a signal that ignores the cross-section entirely.
    """
    spec = get_signal(signal_id)
    params = {**spec.default_params, **CROSS_SECTIONAL_PARAMS[signal_id]}
    wide = _synthetic_panel(seed=8, n_symbols=12, n_bars=1600)
    members = wide.symbols[:5]
    others = [wide.symbols[0], *wide.symbols[5:9]]

    first = spec.compute(_with_reference(wide, members), params)[wide.symbols[0]]
    second = spec.compute(_with_reference(wide, others), params)[wide.symbols[0]]

    assert not first.equals(second), f"{signal_id} ignored the reference population"


def test_reference_does_not_truncate_the_time_series() -> None:
    """DS-2's objection: masking the panel would restart a re-entering symbol's rolling windows.

    A symbol outside the reference for the first half of the sample must still
    carry its own full history when it enters, so its trailing funding sum is
    defined on the first bar of membership rather than NaN for 72 bars.
    """
    panel = _synthetic_panel(seed=9, n_symbols=6, n_bars=900)
    late = panel.symbols[-1]
    mask = pd.DataFrame(True, index=panel.index, columns=panel.close.columns)
    mask.loc[mask.index[:600], late] = False
    params = TsmomParams(horizons=(24, 48, 72), horizon_weights=(0.2, 0.3, 0.5), crowding_window=72)
    referenced = panel.with_reference(mask)

    scores = apply_crowding_modifier(
        tsmom_scores(referenced.close, params), referenced.funding, params, referenced.reference
    )

    assert np.isfinite(scores[late].iloc[601]), "a re-entering symbol lost its own history"


def test_crowding_flags_the_same_share_regardless_of_panel_width() -> None:
    """The measured symptom: n=15 vs n=123 changes how often ``rank >= 0.7`` fires."""
    wide = _synthetic_panel(seed=11, n_symbols=20, n_bars=1200)
    members = wide.symbols[:6]
    params = TsmomParams(horizons=(24, 48, 72), horizon_weights=(0.2, 0.3, 0.5), crowding_window=72)

    def crowded(panel: Panel) -> pd.DataFrame:
        return apply_crowding_modifier(tsmom_scores(panel.close, params), panel.funding, params, panel.reference)

    referenced = crowded(_with_reference(wide, members))[members]
    isolated = crowded(wide.select(members))

    pd.testing.assert_frame_equal(referenced, isolated, check_names=False)


def test_flow_demean_uses_the_reference() -> None:
    """The flow probe's ``cross_sectional`` demean is the half of P1-01 that is live today."""
    wide = _synthetic_panel(seed=12, n_symbols=10, n_bars=800)
    members = wide.symbols[:4]
    params = FlowParams(short_gate=0.0)

    referenced = flow_scores(_with_reference(wide, members), params)[members]
    isolated = flow_scores(wide.select(members), params)

    pd.testing.assert_frame_equal(referenced, isolated, check_names=False)


def test_carry_rank_uses_the_reference() -> None:
    """carry is disabled, but it ranks funding cross-sectionally and would inherit the same defect."""
    wide = _synthetic_panel(seed=13, n_symbols=10, n_bars=800)
    members = wide.symbols[:6]
    params = CarryParams(min_symbols=3)
    assert wide.funding is not None

    referenced = carry_scores(
        wide.funding, wide.index, wide.close.columns, params, reference=_with_reference(wide, members).reference_mask()
    )[members]
    isolated = carry_scores(wide.funding[members], wide.index, pd.Index(members), params)

    pd.testing.assert_frame_equal(referenced, isolated, check_names=False)


def test_mining_cross_sectional_node_uses_the_reference() -> None:
    """The miner's ``cs_rank`` must obey the same contract, or a promoted candidate re-opens P1-01."""
    wide = _synthetic_panel(seed=14, n_symbols=10, n_bars=600)
    members = wide.symbols[:4]
    node = CrossSectional(Ret(24), "rank")

    referenced = node.evaluate(_with_reference(wide, members))[members]
    isolated = node.evaluate(wide.select(members))

    pd.testing.assert_frame_equal(referenced, isolated, check_names=False)


@pytest.mark.parametrize("signal_id", sorted(SIGNALS))
def test_every_signal_still_causal_under_a_reference(signal_id: str) -> None:
    """The reference must not become a channel for future information."""
    spec = get_signal(signal_id)
    panel = _synthetic_panel(seed=15, n_symbols=6, n_bars=900)
    members = panel.symbols[:4]
    cutoff = 700
    scores = spec.compute(_with_reference(panel, members), spec.default_params)

    shuffled = _synthetic_panel(seed=99, n_symbols=6, n_bars=900)
    mixed_close = pd.concat([panel.close.iloc[:cutoff], shuffled.close.iloc[cutoff:]])
    mixed = _with_reference(panel, members)
    later = spec.compute(
        Panel(
            interval=mixed.interval,
            open=mixed.open,
            high=mixed.high,
            low=mixed.low,
            close=mixed_close,
            volume=mixed.volume,
            quote_volume=mixed.quote_volume,
            trades=mixed.trades,
            taker_buy_base=mixed.taker_buy_base,
            taker_buy_quote=mixed.taker_buy_quote,
            funding=mixed.funding,
            reference=mixed.reference,
        ),
        spec.default_params,
    )

    _bit_for_bit(scores.iloc[: cutoff - 1], later.iloc[: cutoff - 1])
