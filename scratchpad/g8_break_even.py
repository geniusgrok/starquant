"""G8: the break-even cost multiple m* - the readings behind `docs/RESEARCH_LOG.md` 2026-09-23 · G8.

m scales `turnover_bps` and `carry_bps_per_bar` together; m* is where the mean per-bar net return is
zero (`starquant_alpha.validation.stability.break_even_cost_multiple`).  Four subcommands, one per group of
readings in that section:

    linearity     per m: mean net (full sample, validate's OOS bars), daily-loss pause bars, distance
                  off the line through x1 and x2; then a bisection on the sign change per series
    acceptance    validate's break-even block on the book, an independent re-pricing at each m*, the
                  pause count there, and what holding funding (rather than scaling it) is worth
    fixture-pause August fixture: how far the x1-x2 line misses at tighter daily-loss pauses
    grid-index    August fixture: the two-cell grid the CLI test runs, and why it tells the two series apart

The book is validate's: the registry's tsmom params, the profile's exit overlay and book guards, one
configuration - so no trial is run and no ledger row is owed.  Read-only against the archive; nothing
is written.  Run from the checkout root:

    PYTHONPATH=. .venv/bin/python scratchpad/g8_break_even.py linearity  --to "2026-09-22 17:00"
    PYTHONPATH=. .venv/bin/python scratchpad/g8_break_even.py acceptance --to "2026-09-22 17:00"
    PYTHONPATH=. .venv/bin/python scratchpad/g8_break_even.py fixture-pause
    PYTHONPATH=. .venv/bin/python scratchpad/g8_break_even.py grid-index

`--to` is exclusive on bar open time, so the lines above end the real panel on the 2026-09-22 16:00 bar
the RESEARCH_LOG readings were taken on.  The archive grows daily, and a rebuilt membership table moves
the readings too.  `--panel fixture` runs the first two on the August fixture instead.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.backtest import BacktestResult, CostModel, ImpactModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.pipeline import score_book
from starquant_alpha.validation.stability import BREAK_EVEN_TOLERANCE, break_even_cost_multiple, cost_stress
from starquant_alpha.validation.walk_forward import walk_forward_folds
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_panel import _entry, _load, _membership, _model, _resolve_symbols
from starquant_live.composition import cost_model, impact_model
from starquant_shared.config import load_yaml

REPO = Path(__file__).resolve().parents[1]
DATA_ROOTS = (".starquant/data", "~/starquant/.starquant/data")
MULTIPLES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0, 16.0, 20.0, 30.0)
PAUSES = (-0.05, -0.02, -0.01, -0.005, -0.004, -0.003, -0.002, -0.0015, -0.001)
FIXTURE_PARAMS = '{"horizons": [5, 20, 50], "crowding_window": 0}'  # the shipped horizons need > 720 bars

Series = Callable[[pd.Series], pd.Series]


class Book:
    """validate's book: the post-overlay decision frame and everything it is re-priced with."""

    def __init__(self, panel: Panel, decisions: pd.DataFrame, cost: CostModel, guards: BookGuardParams | None) -> None:
        self.panel, self.decisions, self.cost, self.guards = panel, decisions, cost, guards
        self.impact: ImpactModel = impact_model(load_yaml(REPO / "config" / "costs.yaml"), capital=0.0)

    def price(self, m: float, guards: BookGuardParams | None = None) -> BacktestResult:
        scaled = CostModel(self.cost.turnover_bps * m, self.cost.carry_bps_per_bar * m, self.cost.use_funding)
        return run_backtest(self.panel, self.decisions, scaled, guards=guards or self.guards, impact=self.impact)


def _check_tree() -> None:
    """`python scratchpad/x.py` puts the script's directory on sys.path, not the working directory.

    In a git worktree `starquant_alpha` then resolves through the editable install to the main checkout,
    and this would measure that tree's code.  Run it with ``PYTHONPATH=.`` from the checkout root.
    """
    import starquant_alpha

    loaded = Path(starquant_alpha.__file__ or "").resolve()
    if REPO not in loaded.parents:
        raise SystemExit(f"starquant_alpha loaded from {loaded}, not from this tree ({REPO}); set PYTHONPATH=.")


def _data_root(given: str | None) -> str:
    for candidate in (given,) if given else DATA_ROOTS:
        if Path(candidate).is_dir():
            return candidate
    raise SystemExit(f"no kline store found in {given or DATA_ROOTS}")


def _book(panel_kind: str, data_root: str | None, end: str | None, params: str = FIXTURE_PARAMS) -> Book:
    profile = load_yaml(REPO / "config" / "live.demo.yaml")
    if panel_kind == "fixture":
        from tests.conftest import load_august_panel

        panel = load_august_panel(REPO / "tests" / "fixtures" / "august_2026")
        membership, funding, min_history = None, False, 0
    else:
        root = _data_root(data_root)
        panel = _load(root, _resolve_symbols(root, "", "1h", "pit"), "1h", None, end, True)
        membership, funding, params, min_history = _membership(root, "pit", panel, 0), True, "", None
    entry = _entry("tsmom", str(REPO / "config" / "alpha_registry.yaml"), params)
    weights, _c, _p = _model(entry, profile, "1h", min_history).evaluate(panel, membership)
    cost = cost_model(load_yaml(REPO / "config" / "costs.yaml"), use_funding=funding)
    guards = _book_guards(profile, True)
    _base, decisions = score_book(panel, weights, cost, guards=guards, exits=_exit_params(profile, True, "1h"))
    print(f"panel {len(panel.symbols)} x {len(panel.index)} ({panel.index[0]} .. {panel.index[-1]})")
    return Book(panel, decisions, cost, guards)


def _views(book: Book) -> dict[str, Series]:
    """The two series validate takes m* on.  One configuration, so common_index is the book's own index."""
    index = book.price(1.0).portfolio_net.index
    folds = walk_forward_folds(len(index), 5, min_train=min(4000, max(len(index) // 2, 2)), purge=50)
    print(f"book {len(index)} bars ({index[0]} .. {index[-1]}); OOS = {len(folds)} fold test slices")

    def full(net: pd.Series) -> pd.Series:
        return net

    def oos(net: pd.Series) -> pd.Series:
        aligned = net.reindex(index).fillna(0.0)
        return pd.concat([aligned.iloc[fold.test_slice] for fold in folds])

    return {"full_sample": full, "oos": oos}


def _pauses(result: BacktestResult) -> int:
    return 0 if result.guard_events is None else int(result.guard_events["daily_loss_pause"].sum())


def _digest(frame: pd.DataFrame) -> str:
    return hashlib.sha256(np.ascontiguousarray(frame.to_numpy(dtype=float)).tobytes()).hexdigest()[:12]


def linearity(book: Book) -> None:
    views = _views(book)
    rows: dict[float, tuple[dict[str, float], int, str]] = {}
    seconds = []
    for m in MULTIPLES:
        clock = time.time()
        result = book.price(m)
        seconds.append(time.time() - clock)
        means = {label: float(view(result.portfolio_net).mean()) for label, view in views.items()}
        rows[m] = (means, _pauses(result), _digest(result.weights))
    print(f"one re-pricing takes {np.mean(seconds):.2f} s on average")
    for label, view in views.items():
        at1, at2 = rows[1.0][0][label], rows[2.0][0][label]
        slope = at2 - at1
        print(f"\n{label}: the line through x1 and x2 has slope {slope:+.6e} per multiple")
        for m, (means, pauses, digest) in rows.items():
            off = (means[label] - (at1 + (m - 1.0) * slope)) / -slope
            book_note = "the x1 book" if digest == rows[1.0][2] else "another book"
            print(f"  m={m:5.1f}  mean {means[label]:+.6e}  pauses {pauses:4d}  {off:+.5f} multiples off the line  ({book_note})")
        lo, hi = 0.0, max(4.0, 2.0 * (1.0 - at1 / slope))
        f_lo, f_hi = (float(view(book.price(m).portfolio_net).mean()) for m in (lo, hi))
        if not f_lo > 0.0 > f_hi:
            print(f"  no sign change on [{lo}, {hi:.3f}]: {f_lo:+.3e} .. {f_hi:+.3e}")
            continue
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            f_mid = float(view(book.price(mid).portfolio_net).mean())
            lo, f_lo, hi, f_hi = (mid, f_mid, hi, f_hi) if f_mid > 0.0 else (lo, f_lo, mid, f_mid)
        step = (f_lo - f_hi) / -slope
        # The bracket is ~3e-11 multiples wide, so a continuous mean steps across it by about that much.
        found = "no jump sits on the zero" if step < 1e-9 else "a jump sits on the zero"
        print(f"  bisection: the sign changes in [{lo:.9f}, {hi:.9f}]; the step across it is {step:.1e} multiples: {found}")


def acceptance(book: Book) -> None:
    views = _views(book)
    calls: list[float] = []

    def priced(m: float) -> pd.Series:
        calls.append(m)
        return book.price(m).portfolio_net

    stressed = {m: priced(m) for m in (1.0, 1.5, 2.0)}
    print("cost_stress", {key: round(value, 4) for key, value in cost_stress(stressed, book.panel.bars_per_year).items() if value is not None})
    x1 = book.price(1.0)
    print(f"daily-loss pause bars at x1: {_pauses(x1)}")
    for label, view in views.items():
        calls.clear()
        clock = time.time()
        found = break_even_cost_multiple(priced, stressed, view)
        print(f"\n{label}: {found}  ({len(calls)} re-pricings, {time.time() - clock:.1f} s)")
        if found["multiple"] is None:
            continue
        again = book.price(found["multiple"])
        mean = float(view(again.portfolio_net).mean())
        tolerance = BREAK_EVEN_TOLERANCE * found["cost_per_multiple"]
        print(
            f"  m* {found['multiple']:.4f} (the x1-x2 line said {found['linear_estimate']:.4f}, "
            f"{found['multiple'] - found['linear_estimate']:+.4f}); independent re-pricing there: mean {mean:+.2e}, "
            f"{abs(mean) / tolerance:.2f} of the tolerance; pause bars {_pauses(again)}"
        )
        print(f"  as bps per unit of turnover: {book.cost.turnover_bps * found['multiple']:.1f} in total")
        if book.panel.funding is None:
            continue
        # Held rather than scaled: what that choice is worth, on the x1 book (so before any path effect).
        scaled = x1.turnover * (book.cost.turnover_bps / 1e4) + x1.weights.abs().sum(axis=1) * (book.cost.carry_bps_per_bar / 1e4)
        funding = (x1.weights * book.panel.funding[x1.weights.columns].reindex(x1.weights.index).fillna(0.0)).sum(axis=1)
        gross, cost, paid = (float(view(series).mean()) for series in (x1.portfolio_gross, scaled, funding))
        print(
            f"  per bar at x1: gross {gross:+.4e}, scaled cost {cost:.4e}, funding paid {paid:+.4e}; "
            f"m* with funding held {(gross - paid) / cost:.4f}, with funding scaled too {gross / (cost + paid):.4f}"
        )


def fixture_pause() -> None:
    """How far the x1-x2 line misses when the daily-loss pause binds, and whether re-pricing settles."""
    book = _book("fixture", None, None)
    for pause in PAUSES:
        guards = replace(book.guards, daily_loss_pause=pause) if book.guards is not None else None

        def priced(m: float, guards: BookGuardParams | None = guards) -> pd.Series:
            return book.price(m, guards).portfolio_net

        found = break_even_cost_multiple(priced, {1.0: priced(1.0), 2.0: priced(2.0)})
        if found["multiple"] is None:
            print(f"pause {pause:+.4f}: {found['why']}")
            continue
        print(
            f"pause {pause:+.4f}: line {found['linear_estimate']:.6f} -> m* {found['multiple']:.6f} "
            f"(missed by {found['multiple'] - found['linear_estimate']:+.4f}); converged={found['converged']} after "
            f"{found['repricings']}; pause bars {_pauses(book.price(1.0, guards))} at x1, "
            f"{_pauses(book.price(found['multiple'], guards))} at m*"
        )


def grid_index() -> None:
    """The CLI test's two-cell grid: the best cell's own series is longer than common_index."""
    profile = load_yaml(REPO / "config" / "live.demo.yaml")
    from tests.conftest import load_august_panel

    panel = load_august_panel(REPO / "tests" / "fixtures" / "august_2026")
    base = _entry("tsmom", str(REPO / "config" / "alpha_registry.yaml"), FIXTURE_PARAMS).params
    cost = CostModel(7.0, 0.0, False)
    guards = _book_guards(profile, True)
    books: dict[int, Book] = {}
    nets: dict[int, pd.Series] = {}
    for window in (100, 200):
        entry = StrategyEntry(id="tsmom", params={**base, "vol_window": window})
        weights, _c, _p = _model(entry, profile, "1h", 0).evaluate(panel, None)
        result, decisions = score_book(panel, weights, cost, guards=guards, exits=_exit_params(profile, True, "1h"))
        books[window], nets[window] = Book(panel, decisions, cost, guards), result.portfolio_net
        print(f"vol_window {window}: {len(result.portfolio_net)} bars from {result.portfolio_net.index[0]}, sharpe {result.summary()['annualized_sharpe']:.4f}")
    common = nets[100].index.intersection(nets[200].index)
    best = max(nets, key=lambda window: float(nets[window].mean() / nets[window].std()))
    print(f"common_index: {len(common)} bars from {common[0]}; best cell: vol_window {best}")

    def priced(m: float) -> pd.Series:
        return books[best].price(m).portfolio_net

    stressed = {1.0: priced(1.0), 2.0: priced(2.0)}
    own = break_even_cost_multiple(priced, stressed)
    on_common = break_even_cost_multiple(priced, stressed, lambda net: net.reindex(common).fillna(0.0))
    print(f"full-sample m* on the cell's own series {own['multiple']:.4f}; on common_index {on_common['multiple']:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="G8: the break-even cost multiple, measured")
    parser.add_argument("what", choices=("linearity", "acceptance", "fixture-pause", "grid-index"))
    parser.add_argument("--panel", choices=("real", "fixture"), default="real", help="linearity / acceptance only")
    parser.add_argument("--data-root", default=None, help=f"kline store; default the first of {DATA_ROOTS}")
    parser.add_argument("--to", default=None, help="exclusive panel end on bar open time, e.g. '2026-09-22 17:00'")
    args = parser.parse_args()
    _check_tree()
    started = time.time()
    if args.what == "fixture-pause":
        fixture_pause()
    elif args.what == "grid-index":
        grid_index()
    else:
        book = _book(args.panel, args.data_root, args.to)
        (linearity if args.what == "linearity" else acceptance)(book)
    print(f"\n{time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
