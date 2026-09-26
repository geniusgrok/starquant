"""`research mine` enumerated the DL-D4 leaves and loaded a panel without them.

Every `oi` and `lsr` candidate has raised `ExprError` in every round since DL-D4 shipped.  Measured
2026-09-09 over two consecutive rounds: `outcomes.errored = 90` both times, and the 90 are exactly the
54 `oi` plus 36 `lsr` candidates.  Not one metrics candidate has ever been scored.

The reason is one missing keyword.  `research decompose` loads `metrics=True` with a comment saying why
it must be unconditional - enumeration happens after the panel exists, so the panel cannot be
conditioned on what will be enumerated - and `research mine`, the command that actually enumerates
them, was written without it.  `research validate` asks `_wants_metrics(strategy)`, which is right
there because a strategy id is known in advance; the miner has no strategy, which is the whole point.

Two things made it survive:

* the per-row `error` field records the real reason, and only `outcomes.errored` reaches the summary
  the reader sees - so a family that could not run read as a family that ran and lost;
* the count is stable and plausible.  90 of 658 looks like a search rejecting malformed combinations,
  which is a thing this search legitimately does.

So the assertion below is not "the command works".  It is that the panel the miner scores on carries
every column the candidates it just enumerated declare they read - the two halves joined, because each
half was individually correct.
"""

from __future__ import annotations

import inspect

from starquant_alpha.mining import enumerate_candidates
from starquant_cli import research_cmd


def _source_of(command: str) -> str:
    function = getattr(research_cmd, command)
    return inspect.getsource(getattr(function, "callback", function))


def test_the_miner_loads_the_metrics_its_own_candidates_declare() -> None:
    """The regression, stated where it is cheap: the miner's `_load` must ask for metrics.

    A source assertion proves a rule is wired, never that it is right (2026-09-09's own lesson), so it
    is paired with the behavioural test below.  It is here because the failure mode is a DEFAULT - the
    keyword absent, not wrong - and a default is invisible to a test that only exercises the happy path
    with metrics present.
    """
    source = _source_of("research_mine")
    loads = [line for line in source.splitlines() if "_load(" in line and "panel" in line]
    assert loads, "research mine no longer loads a panel the way this test expects"
    assert all("metrics=True" in line for line in loads), (
        "research mine enumerates the DL-D4 leaves; a panel without metrics makes every one of them "
        f"raise ExprError and land in `outcomes.errored`: {loads}"
    )


def test_the_family_that_could_not_be_scored_is_enumerated_at_all() -> None:
    """If the leaves ever stop being enumerated, the test above passes while nothing is searched."""
    expressions = [str(c.expr) for c in enumerate_candidates(max_lookback=1400).candidates]
    reading_metrics = [e for e in expressions if "oi(" in e or "lsr(" in e]
    assert len(reading_metrics) >= 50, (
        f"only {len(reading_metrics)} metrics candidates are enumerated; the 2026-09-09 space had 90 "
        "(54 oi + 36 lsr), and a shrinking family would hide the bug this file exists for"
    )


def test_a_metrics_candidate_scores_on_the_panel_the_miner_builds() -> None:
    """The behavioural half: the same leaf, through the same steps the miner takes, on a synthetic panel."""
    import numpy as np
    import pandas as pd

    from starquant_alpha.backtest import CostModel, run_backtest
    from starquant_alpha.mining import to_signal
    from starquant_alpha.model import AlphaModel
    from starquant_alpha.panel import Panel
    from starquant_alpha.portfolio import PortfolioParams
    from starquant_alpha.registry import StrategyEntry
    from starquant_alpha.signals import register as register_signal

    bars, symbols = 900, ("AAA", "BBB", "CCC")
    index = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    rng = np.random.default_rng(11)
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0, 0.004, size=(bars, len(symbols))), axis=0)),
        index=index,
        columns=list(symbols),
    )
    ratio = pd.DataFrame(1.0 + rng.normal(0, 0.1, size=(bars, len(symbols))), index=index, columns=list(symbols))
    panel = Panel(
        interval="1h",
        open=close.shift(1).bfill(),
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=close * 1_000.0,
        quote_volume=close * 1_000.0,
        metrics={"count_long_short_ratio": ratio, "sum_open_interest": ratio * 1e6},
    )
    candidate = next(c for c in enumerate_candidates(max_lookback=400).candidates if "lsr(" in str(c.expr))
    spec = register_signal(to_signal(candidate))
    model = AlphaModel(
        entries=(StrategyEntry(id=spec.id, params=dict(spec.default_params)),),
        portfolio=PortfolioParams(),
        interval="1h",
        min_history_bars=0,
    )
    weights, _combined, _per = model.evaluate(panel, None)
    net = run_backtest(panel, weights, CostModel(7.0)).portfolio_net
    assert net.notna().any(), "the leaf produced no priced series on a panel that carries its column"
