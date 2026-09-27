"""`book-tsmom-residual-20260918T184016Z`, the one book report written with D2/D3 on, re-scored three ways.

The arms (2026-09-23): as banded before the fix (single arms no D2/D3, combined D2 only); `combine_books`
fixed alone; every arm fixed.  They are re-created by patching the two addresses the OLD code read the
band from - `research_book_eval.apply_no_trade_band`, which its local `banded()` called, and
`combine_books` as `research_book_eval` and `starquant_alpha.model` import it - with a call counter on each,
because a patch aimed at an address nobody reads passes silently.

So this runs against the code BEFORE the fix, 227a6348 - its parent e80b1335, or earlier.  After it, `banded` is one function in
`starquant_alpha.portfolio`, the first address no longer exists, and the script refuses rather than report
three identical arms.  To re-run: `git worktree add <dir> e80b1335` and run it there.

Not bit-reproducible against the archive, and the cause is measured rather than guessed: on today's store
the main-only arm reads OOS 1.542896 against the archive's 1.541097, and the code at the report's own
commit (89091239) reads 1.542896 on the same data.  The history in `.starquant/data` changed after
2026-09-18, the code did not.  The arms are compared with each other on one set of data, so their
differences stand.

Read-only: the ledger is a copy truncated to the rows before the archived run, and `_evaluate_book`
returns its trial record instead of writing it.

    .venv/bin/python scratchpad/d3_multibook_residual_book_replay.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p32e_ruler_divergence import DATA

import starquant_alpha.model as model_module
import starquant_alpha.portfolio as portfolio_module
import starquant_cli.research_book_eval as book_eval
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.book_limits import marginal_checks
from starquant_alpha.validation.ledger import resolve_ledger_path
from starquant_alpha.validation.stability import slippage_levels
from starquant_cli.research_book_eval import BOOK_RULE, _embargo_bars, _evaluate_book, _running_book_nets
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import cost_model, portfolio_params
from starquant_shared.config import load_yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scratchpad" / "d3_multibook_out"

REPORT = REPO / "reports/research/book-tsmom-residual-20260918T184016Z.json"
BEFORE_THE_RUN = "2026-09-18T18:40:11"
BAND = portfolio_module.apply_no_trade_band
COMBINE = portfolio_module.combine_books
CALLS = {"single_arms": 0, "combine": 0}
T0 = time.time()


def log(message: str) -> None:
    print(f"[{time.time() - T0:7.1f}s] {message}", flush=True)


def combine_with_every_knob(books: Any, params: Any) -> pd.DataFrame:
    CALLS["combine"] += 1
    total = COMBINE(books, replace(params, no_trade_band=0.0, no_trade_rel_band=0.0))  # sum and caps, no band
    return BAND(total, params.no_trade_band, params.no_trade_rel_band, params.flat_inside_band, params.band_entry_multiple)


def install(arm: str, portfolio: Any) -> None:
    book_eval.apply_no_trade_band = BAND
    book_eval.combine_books = model_module.combine_books = COMBINE
    if arm == "before":
        return
    book_eval.combine_books = model_module.combine_books = combine_with_every_knob
    if arm == "every arm":

        def single_arms(weights: pd.DataFrame, band: float, relative: float = 0.0, *_: Any) -> pd.DataFrame:
            CALLS["single_arms"] += 1
            return BAND(weights, band, relative, portfolio.flat_inside_band, portfolio.band_entry_multiple)

        book_eval.apply_no_trade_band = single_arms


def main() -> None:
    if not hasattr(book_eval, "apply_no_trade_band"):
        raise SystemExit("this is the code after the fix; run it on e80b1335 (see the module docstring)")
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / "trials-before-the-residual-run.jsonl"
    rows = (REPO / "reports/research/trials.jsonl").read_text(encoding="utf-8").splitlines()
    kept = [line for line in rows if line.strip() and json.loads(line)["recorded_at"][:19] < BEFORE_THE_RUN]
    ledger.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.environ["STARQUANT_TRIALS_LEDGER"] = str(ledger)

    archived = json.loads(REPORT.read_text(encoding="utf-8"))
    profile = load_yaml(str(REPO / "config/live.demo.yaml"))
    portfolio = portfolio_params(profile)
    main_entry = StrategyEntry(id="tsmom", params=archived["main"]["params"])
    sleeve_entry = StrategyEntry(id="residual", params=archived["sleeve"]["params"])
    fraction = archived["fraction"]
    costs = load_yaml(str(REPO / "config/costs.yaml"))
    cost = cost_model(costs, use_funding=True)
    end = pd.Timestamp(archived["universes"]["pit"]["range"]["end"])
    last_bar_kept = end + pd.Timedelta(hours=1)  # `Panel.slice` keeps open_time < end
    panel = _load(DATA, _resolve_symbols(DATA, "", "1h", "pit"), "1h", None, None, True).slice(None, last_bar_kept)
    assert panel.index[-1] == end and sorted(panel.symbols) == sorted(archived["universes"]["pit"]["symbols"])
    membership = _membership(DATA, "pit", panel)
    universes = [("pit", panel, membership), ("static", panel.select(archived["universes"]["static"]["symbols"]), None)]
    history = int(profile["portfolio"]["min_history_bars"])
    slippage = slippage_levels(
        taker_fee_bps=float(costs.get("taker_fee_bps", 5.0)),
        levels=[float(v) for v in costs.get("slippage_stress_bps", []) or []],
    )
    out: dict[str, Any] = {}
    for arm in ("before", "combine_books alone", "every arm"):
        install(arm, portfolio)
        CALLS.update(single_arms=0, combine=0)
        nets, notes = _running_book_nets(
            str(REPO / "config/alpha_registry.yaml"), profile, panel, membership, cost,
            interval="1h", min_history=history, exclude_strategy="residual",
        )  # fmt: skip
        evaluated = {}
        for position, (mode, mode_panel, mode_membership) in enumerate(universes):
            evaluated[mode], _record = _evaluate_book(
                mode, mode_panel, mode_membership, main_entry, sleeve_entry, portfolio,
                [fraction, *archived["sensitivity_fractions"]], cost,
                interval="1h", min_history=history, folds=archived["folds"], min_train=archived["min_train"],
                purge=archived["purge"], embargo=_embargo_bars(archived["purge"], archived["embargo"]),
                cpcv_groups=6, prior_trials=archived["prior_trials"], ledger_path=resolve_ledger_path(),
                with_limits=position == 0, running_nets=nets, running_notes=notes, slippage_totals=slippage,
            )  # fmt: skip
        if arm != "before":
            assert CALLS["combine"] > 0, f"{arm}: the combine_books patch was never called"
        if arm == "every arm":
            assert CALLS["single_arms"] > 0, f"{arm}: the single-arm patch was never called"
        decision, static = evaluated["pit"], evaluated["static"]
        marginal = decision["by_fraction"][f"{fraction:.4f}"]["marginal"]
        standalone = decision["sleeve_standalone"]
        checks = {
            **marginal_checks(marginal, BOOK_RULE),
            "cpcv_negative": standalone["cpcv"]["fraction_negative"] <= BOOK_RULE["max_cpcv_negative"],
            "cost_x2_sharpe": standalone["cost_stress"]["x2"] >= BOOK_RULE["min_cost_x2_sharpe"],
            "robustness_delta": static["by_fraction"][f"{fraction:.4f}"]["marginal"]["delta_oos_sharpe"]
            >= BOOK_RULE["min_robustness_delta"],
        }
        out[arm] = {"checks": checks, "calls": dict(CALLS), "evaluated": evaluated}
        log(f"{arm}: failing {[name for name, ok in checks.items() if not ok]}; calls {CALLS}")
        for mode, block in evaluated.items():
            m = block["by_fraction"][f"{fraction:.4f}"]["marginal"]
            log(f"  {mode}: main {block['main_only']['oos_sharpe']:.6f} delta {m['delta_oos_sharpe']:+.6f} "
                f"mdd_worse {m['oos_mdd_worsening']:+.6f} win {m['fold_win_rate']:.1f} "
                f"sleeve alone {block['sleeve_standalone']['walk_forward']['oos_sharpe']:.6f}")
    install("before", portfolio)
    log(f"archived: failing {archived['reasons']}")
    (OUT / "residual-book-replay.json").write_text(json.dumps(out, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
