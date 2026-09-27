"""Signal registry.  Each signal exposes ``compute(panel, params) -> DataFrame[time x symbol]`` with scores in [-1, 1]."""

from __future__ import annotations

from dataclasses import asdict

from starquant_alpha.signals import breakout, carry, chanlun, flow, meanrev, pairs, residual, tsmom, xsmom
from starquant_alpha.signals.base import SignalSpec, scores_to_targets
from starquant_alpha.validation.ledger import PAIR_SEARCH_STRATEGY

SIGNALS: dict[str, SignalSpec] = {
    # The 51st strategy (DL-S51).  Its formalisation was pre-registered in §7 of the governance plan
    # before the module existed, because Chan theory is a family and "whichever variant scores better"
    # is the failure this pipeline exists to refuse.
    "chanlun": SignalSpec(
        "chanlun",
        chanlun.compute,
        asdict(chanlun.ChanlunParams()),
        "缠论 structure: merged bars -> fractals -> pens -> segments -> centres -> third-type points",
        chanlun.ChanlunParams().warmup_bars,
        warmup=lambda params: chanlun.ChanlunParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(chanlun.ChanlunParams.from_mapping(params)),
    ),
    # P28 (#6).  Vol-matched rather than OLS-beta because stage 1 sizes each leg on its own vol; the
    # formalisation was pre-registered before the module existed.  The only signal so far that SEARCHES
    # before it scores, so the only one that declares a census: choosing the partner out of every pair
    # the formation window can form is a selection, and `selection_bucket` is where it is charged.
    "pairs": SignalSpec(
        "pairs",
        pairs.compute,
        asdict(pairs.PairsParams()),
        "vol-matched pairs on mutually-nearest neighbours, refit on a prefix",
        pairs.PairsParams().warmup_bars,
        warmup=lambda params: pairs.PairsParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(pairs.PairsParams.from_mapping(params)),
        selection=pairs.search_census,
        selection_bucket=PAIR_SEARCH_STRATEGY,
    ),
    "tsmom": SignalSpec(
        "tsmom",
        tsmom.compute,
        asdict(tsmom.TsmomParams()),
        "multi-horizon time-series momentum (TrendAlpha port)",
        tsmom.TsmomParams().warmup_bars,
        warmup=lambda params: tsmom.TsmomParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(tsmom.TsmomParams.from_mapping(params)),
        uses_funding=lambda params: tsmom.TsmomParams.from_mapping(params).uses_funding,
    ),
    "xsmom": SignalSpec(
        "xsmom",
        xsmom.compute,
        asdict(xsmom.XsmomParams()),
        "cross-sectional momentum / relative strength, market-neutral",
        xsmom.XsmomParams().warmup_bars,
        warmup=lambda params: xsmom.XsmomParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(xsmom.XsmomParams.from_mapping(params)),
    ),
    "carry": SignalSpec(
        "carry",
        carry.compute,
        asdict(carry.CarryParams()),
        "funding-rate carry (short high funding, long low funding)",
        carry.CarryParams().warmup_bars,
        warmup=lambda params: carry.CarryParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(carry.CarryParams.from_mapping(params)),
        uses_funding=lambda params: True,
    ),
    "meanrev": SignalSpec(
        "meanrev",
        meanrev.compute,
        asdict(meanrev.MeanrevParams()),
        "robust z-score mean reversion with trend gate and explicit exits",
        meanrev.MeanrevParams().warmup_bars,
        warmup=lambda params: meanrev.MeanrevParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(meanrev.MeanrevParams.from_mapping(params)),
    ),
    "breakout": SignalSpec(
        "breakout",
        breakout.compute,
        asdict(breakout.BreakoutParams()),
        "ATR-normalised Donchian breakout with volume/breadth confirmation",
        breakout.BreakoutParams().warmup_bars,
        warmup=lambda params: breakout.BreakoutParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(breakout.BreakoutParams.from_mapping(params)),
    ),
    "flow": SignalSpec(
        "flow",
        flow.compute,
        asdict(flow.FlowParams()),
        "taker-buy order-flow imbalance scaled by volume expansion",
        flow.FlowParams().warmup_bars,
        warmup=lambda params: flow.FlowParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(flow.FlowParams.from_mapping(params)),
    ),
    "residual": SignalSpec(
        "residual",
        residual.compute,
        asdict(residual.ResidualParams()),
        "beta-neutral residual momentum vs BTC",
        residual.ResidualParams().warmup_bars,
        warmup=lambda params: residual.ResidualParams.from_mapping(params).warmup_bars,
        canonical=lambda params: asdict(residual.ResidualParams.from_mapping(params)),
    ),
}


def get_signal(signal_id: str) -> SignalSpec:
    try:
        return SIGNALS[signal_id]
    except KeyError as exc:
        raise KeyError(f"unknown signal {signal_id!r}; known: {sorted(SIGNALS)}") from exc


def register(spec: SignalSpec) -> SignalSpec:
    """Add a generated signal to this process's registry, so ``AlphaModel`` can resolve it like any other.

    Mined candidates are the only generated signals, and they are namespaced ``mined_<hash>``.  Anything
    outside that namespace is hand-written and evidence-backed, so overwriting it is refused rather than
    allowed to shadow a validated signal with a search result.
    """
    if not spec.id.startswith("mined_"):
        raise ValueError(f"only mined_* ids may be registered at runtime, not {spec.id!r}")
    SIGNALS[spec.id] = spec
    return spec


__all__ = ["SIGNALS", "SignalSpec", "get_signal", "register", "scores_to_targets"]
