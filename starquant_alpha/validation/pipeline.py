"""One machine applies the layers between a weight frame and a priced book, and every report says which.

The live book is four layers - signal, sleeve, exit overlay, book guards - and six research commands
score some subset of it.  Until now each command spelled its own subset inline, which produced two
different problems that are worth keeping apart, because only one of them is a defect.

**Not a defect: the commands disagree on purpose.**  `research overlay` scores the BARE ensemble, and
that is a written protocol - `docs/RESEARCH_LOG.md` (2026-09-08) states it in as many words, "判据评的
是不带 shipped exits 的裸 ensemble（`research overlay` 的既有协议，原 D-017 证据同样如此），所以它与
历史裁决可比".  Making it apply the shipped exits would break comparability with every D-017 ruling.
`research book` prices a sleeve's marginal contribution on `bare` weights plus the band, which is what
D-018 was pre-registered on.  `correlate` wants net-return streams without path-dependent layers.
Three books, three reasons.

**The defect is that the artefact could not tell them apart.**  Of the five report kinds, only
`validation` recorded `book_guards` and `exits`; `overlay`, `book`, `correlate` and `mine` recorded
`costs` and nothing else.  So a reader holding an overlay report's 1.85 and a validation report's 1.59
had nothing in either file saying they are not the same book - and the two ARE quoted against each
other, which is the mistake `_MARGIN_BUFFER_NOTE` and `_caliber_note` were written to stop one level up.

**The second defect is `research backtest`, which had no way to apply the overlay at all.**  Not a
protocol: no `--exits` flag existed, so the command could not score the book the loop holds even when
asked, and its Sharpe sat 0.058 below `validate`'s on identical inputs for that reason alone.

So: `score_book` is the one implementation of "apply the overlay, then price", and `layers_applied` is
what puts the answer in the file.  Neither changes what any command CHOOSES to measure.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from starquant_alpha.backtest import BacktestResult, CostModel, ImpactModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel

#: How the no-trade band reached the weights this run is pricing.  A declaration rather than an
#: action: the band is path dependent and belongs to whoever built the weights - `build_weights`
#: applies it inside the model (D-033's backtest half), `research book` applies it to `bare` weights
#: after the fact, and a bare run applies none.  Recording WHICH is what lets two reports be compared;
#: applying it here would be a third recursion over a reference that is not the book.
BandConvention = Literal["model", "after_bare", "none"]


def score_book(
    panel: Panel,
    decision_weights: pd.DataFrame,
    cost: CostModel,
    *,
    execution: str = "open_to_close",
    guards: BookGuardParams | None = None,
    exits: ExitParams | None = None,
    impact: ImpactModel | None = None,
) -> tuple[BacktestResult, pd.DataFrame]:
    """Apply the exit overlay to decision-time weights, then price them - the loop's own order.

    Returns the result and the post-overlay decision frame, because the caller needs the second one:
    it is what a re-run at a different cost has to be priced on, and re-deriving it from
    ``result.weights`` would invert a frame the guards have already trimmed (`validate` records that
    trap beside its own stress re-runs).

    ``exits=None`` means "this protocol applies no overlay", which is a statement and not an absence -
    the same distinction `registry.construction_problems` draws between a report that recorded
    ``exits: null`` and one written before the field existed.
    """
    overlaid = decision_weights if exits is None else apply_exits(decision_weights, panel.close, exits).weights
    result = run_backtest(
        panel,
        overlaid,
        cost,
        execution=execution,  # type: ignore[arg-type]
        guards=guards,
        impact=impact,
    )
    return result, overlaid


def layers_applied(*, band: BandConvention, guards: BookGuardParams | None, exits: ExitParams | None) -> dict[str, Any]:
    """Which of the live book's four layers this report priced, in the file rather than in the source.

    ``None`` for a layer says the run applied none; a report written before this block existed carries
    no ``layers`` key at all, and those two have to stay distinguishable for the same reason
    `book_guards: null` and an absent `book_guards` do.
    """
    return {
        "band": band,
        "book_guards": None if guards is None else dict(vars(guards)),
        "exits": None if exits is None else dict(vars(exits)),
    }


__all__ = ["BandConvention", "layers_applied", "score_book"]
