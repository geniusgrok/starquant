"""Common signal contract and target semantics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.panel import Panel

SignalFunction = Callable[[Panel, Mapping[str, Any]], pd.DataFrame]
WarmupFunction = Callable[[Mapping[str, Any]], int]
FundingPredicate = Callable[[Mapping[str, Any]], bool]
CanonicalFunction = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class SearchCensus:
    """What a signal's own search examined, in ids the trials ledger can charge one row each.

    ``research mine`` met this problem first and DL-K2 settled it there: a search that costs nothing is
    a DSR denominator wrong in the one direction that flatters it.  The same hole was open one level
    down, inside the signals - ``pairs`` chooses which SYMBOL PAIRS to trade out of every pair its
    formation window can form, and the report that shipped on 2026-09-08 recorded ``n_trials: 4`` for a
    run that had looked at 19,578 of them.

    ``candidates`` is one id per hypothesis EXAMINED and is already deduplicated: re-examining a
    candidate at the next refit is one hypothesis looked at twice, not two hypotheses.  ``selected`` is
    the subset the signal actually traded, reported rather than charged - the ratio between the two is
    what a reader needs in order to judge whether the charge is the right size.
    """

    candidates: tuple[str, ...]
    selected: tuple[str, ...]
    facts: dict[str, Any]


SelectionCensus = Callable[[Panel, Mapping[str, Any]], SearchCensus]


def jsonable(value: Any) -> Any:
    """Tuples to lists, recursively, so params that came from YAML and from JSON compare equal."""
    if isinstance(value, tuple | list):
        return [jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class SignalSpec:
    id: str
    compute: SignalFunction
    default_params: dict[str, Any]
    description: str = ""
    warmup_bars: int = 0  # under the default params
    warmup: WarmupFunction | None = None  # under arbitrary (registry) params
    uses_funding: FundingPredicate | None = None  # does the signal read ``panel.funding`` under these params?
    # DL-Q6 / KILL-Q11, and the same question one source over: research can read the T+1 metrics
    # archive and live can read only the 30-day REST window, so a signal that needs metrics must
    # say so and be refused at startup until the LIVE recording covers it (`metrics_refusal`).
    needs_metrics: FundingPredicate | None = None
    # DL-D5 / RISK-G3, and the same question a third source over.  A signal that reads `panel.spot`
    # is trading a cross-market price relation, and the two markets' bars are only comparable if the
    # event-time contract between them has been MEASURED - `starquant_data.alignment` exists because the
    # metrics stamp was one bucket out for every bucket while nothing raised.  Declared here rather
    # than inferred at startup because the engine sees a compiled `SignalSpec` and cannot look inside
    # the expression tree; `starquant_alpha.mining.search.to_signal` derives it from `Expr.reads_spot`.
    needs_spot: FundingPredicate | None = None
    canonical: CanonicalFunction | None = None  # params with this signal's defaults applied
    # DL-K2 one level down.  A signal that picks WHICH combinations of the data to trade has made a
    # selection, and the DSR denominator has to be able to read it back.  A spec that declares the
    # census must also name the shared ledger bucket its candidates are charged to, and `ledger_scope`
    # must actually route the strategy there; `tests/alpha/test_a_signals_own_search_is_charged.py`
    # holds the three together, so the next pair-type formalisation cannot be registered with a free
    # denominator - which is the whole point of a shared bucket rather than a per-strategy one.
    selection: SelectionCensus | None = None
    selection_bucket: str = ""

    def warmup_for(self, params: Mapping[str, Any]) -> int:
        """Bars of history the signal needs under *these* params, not under the defaults.

        The live loop sizes its request window from this number; deriving it
        from the defaults made a 720-bar horizon run on an 817-bar window (E-042).
        """
        if self.warmup is None:
            return self.warmup_bars
        return int(self.warmup(params))

    def needs_funding(self, params: Mapping[str, Any]) -> bool:
        """Whether the signal consumes funding-rate history under these params.

        The live loop must then fetch that history into the panel; a signal
        that silently gets ``funding=None`` trades a different configuration
        from the one that was validated (KILL-027).
        """
        return bool(self.uses_funding(params)) if self.uses_funding is not None else False

    def search_census(self, panel: Panel, params: Mapping[str, Any]) -> SearchCensus | None:
        """The candidates this signal's own search examined here, or None when it searches nothing.

        Most signals score every symbol they are handed and select nothing, so None is the honest
        answer rather than an empty census: "this signal ran no search" and "this run's search found
        nothing" are different facts, and a report that cannot tell them apart cannot be audited.
        """
        return None if self.selection is None else self.selection(panel, params)

    def canonical_params(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Params with the signal's defaults filled in, in a form two sources can be compared in.

        A registry entry lists only what the operator chose to write; a validation report records
        the full parameter set.  Comparing them raw makes an identical configuration look different,
        which is why the comparison goes through the signal's own parameter object.
        """
        filled = self.canonical(params) if self.canonical is not None else params
        result = jsonable(filled)
        assert isinstance(result, dict)
        return result


def scores_to_targets(
    scores: pd.DataFrame,
    entry_threshold: float,
    *,
    hold: bool = True,
    zero_is_exit: bool = True,
    initial: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Turn raw scores into positions.

    ``|score| >= entry_threshold`` is an actionable forecast and becomes the
    target.  A sub-threshold non-zero score (or NaN) is *no action*: with
    ``hold=True`` (the correct semantics, D-005) the previous target is
    preserved; with ``hold=False`` the position is flattened.  An exact
    ``0.0`` is an explicit exit when ``zero_is_exit`` (mean-reversion style
    signals use it to leave a trade once the dislocation has closed).
    Trading the raw sub-threshold score was the E-022 turnover bug and is
    deliberately not offered.

    ``initial`` seeds the hold with the target held *before* the first row:
    the live loop passes the previous cycle's per-strategy targets so that a
    position survives a sub-threshold stretch longer than the request window,
    exactly as it does in a backtest over the full history (E-042).  Symbols
    without any score in the frame stay NaN (not tradable) whatever the seed.
    """
    if not 0 < entry_threshold <= 1:
        raise ValueError("entry_threshold must be in (0, 1]")
    actionable = scores.where(scores.abs() >= entry_threshold)
    if zero_is_exit:
        actionable = actionable.mask(scores == 0.0, 0.0)
    seen = scores.notna().cummax()  # warmup rows stay NaN so backtests start at the first real decision
    if not hold:
        return actionable.fillna(0.0).where(seen)
    if initial:
        seed = np.array([_seed_value(initial, str(column)) for column in actionable.columns], dtype=float)
        stacked = np.vstack([seed, actionable.to_numpy(dtype=float)])
        values = pd.DataFrame(stacked, columns=actionable.columns).ffill().to_numpy()[1:]
        filled = pd.DataFrame(values, index=actionable.index, columns=actionable.columns)
    else:
        filled = actionable.ffill()
    return filled.fillna(0.0).where(seen)


def _seed_value(initial: Mapping[str, float], symbol: str) -> float:
    value = initial.get(symbol)
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
