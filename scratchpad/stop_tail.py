"""The loss a per-symbol stop is FOR: the worst drawdown of cumulative P&L inside one holding episode.

P11-b (2026-09-04) adopted `stop_loss: 6.0` on the operator's instruction while recording that its own
second criterion had FAILED: the worst single-name episode loss was identical to three decimals with and
without the stop, at every distance in the grid.  That table is `docs/RESEARCH_LOG.md`'s, and it is the
reason the config comment says the stop "protects nothing measurable".  The script that produced it was
called `scratchpad/stop_tail.py` and was never committed - `.gitignore` says scratchpad scripts ARE
committed precisely because they reproduce adoption decisions, so this is the rule being repaired, not
an exception being made.  This file rebuilds the measurement from the definition the log states.

Portfolio OOS MDD cannot see this quantity: it is a portfolio statistic and averages a single name's
slow bleed away.  D-017 is scored on it anyway, which is why widening a from-entry stop from 4 to 8
moves OOS Sharpe and MDD while leaving the per-episode tail bit-identical.

DEFINITION (from the log, restated so a reader need not trust this file's arithmetic):
  episode  = a maximal run of bars on which one symbol's HELD weight keeps the same non-zero sign
  loss     = min over the episode of (cumulative net P&L - its running maximum, floor 0 at entry)
  unit     = fraction of equity, because `BacktestResult.net` is already per-bar equity fraction

"20 worst" is ambiguous in the log's table header, so BOTH readings are printed; whichever reproduces
-32.59% (pit) / -38.04% (static) at vol_target 0.15 is the log's, and the other is labelled as not it.

The exit settings below are exactly the four P11-b reported.  Trailing distances are deliberately NOT
here: they are the subject of a pre-registration that has to be written before it is run, and adding
them to this file would be running first.  Backtest call matches `research overlay` (no book guards).

    python scratchpad/stop_tail.py pit|static [--vol-target 0.15] [--root .starquant/data]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

# The four settings P11-b tabulated.  `stop_loss: 0` is the overlay that was live before P11.
SETTINGS: tuple[tuple[str, dict[str, float]], ...] = (
    ("take_profit 6 (pre-P11 live)", {"take_profit": 6.0}),
    ("stop_loss 4 + take_profit 6", {"stop_loss": 4.0, "take_profit": 6.0}),
    ("stop_loss 6 + take_profit 6", {"stop_loss": 6.0, "take_profit": 6.0}),
    ("stop_loss 8 + take_profit 6", {"stop_loss": 8.0, "take_profit": 6.0}),
)
WORST_N = 20


def episode_losses(held: pd.Series, net: pd.Series) -> list[float]:
    """Worst within-episode drawdown of cumulative P&L, one entry per same-direction holding episode."""
    sign = np.sign(held.to_numpy(dtype=float))
    pnl = net.to_numpy(dtype=float)
    out: list[float] = []
    start = 0
    while start < len(sign):
        if sign[start] == 0.0:
            start += 1
            continue
        stop = start + 1
        while stop < len(sign) and sign[stop] == sign[start]:
            stop += 1
        # cumulative P&L from a flat start, so the running peak begins at 0: an episode that only
        # ever loses must report its full loss, not zero.
        cumulative = np.concatenate([[0.0], np.cumsum(pnl[start:stop])])
        out.append(float((cumulative - np.maximum.accumulate(cumulative)).min()))
        start = stop
    return out


def tail(held: pd.DataFrame, net: pd.DataFrame) -> dict[str, object]:
    per_symbol: dict[str, list[float]] = {
        symbol: episode_losses(held[symbol], net[symbol]) for symbol in held.columns if symbol in net.columns
    }
    worst_by_name = {symbol: min(losses) for symbol, losses in per_symbol.items() if losses}
    if not worst_by_name:
        raise SystemExit("no holding episodes: the weights are empty")
    every_episode = sorted(loss for losses in per_symbol.values() for loss in losses)
    ranked_names = sorted(worst_by_name.items(), key=lambda item: item[1])
    return {
        "worst_name": ranked_names[0][0],
        "worst_value": ranked_names[0][1],
        "sum20_episodes": float(sum(every_episode[:WORST_N])),
        "sum20_names": float(sum(value for _, value in ranked_names[:WORST_N])),
        "episodes": len(every_episode),
        "names": len(worst_by_name),
        "ranked": ranked_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pit", "static"))
    parser.add_argument("--root", default=".starquant/data")
    parser.add_argument("--profile", default="config/live.demo.yaml")
    # Every one of these pins an axis that has MOVED since P11-b ran, and comparing two reports without
    # first counting the moved axes is how a data-vintage difference gets attributed to a parameter.
    # Defaults reproduce nothing on purpose: they measure today.
    parser.add_argument(
        "--vol-target",
        type=float,
        default=None,
        help="override the profile; P11-b ran at 0.15, the profile has said 0.30 since P13",
    )
    parser.add_argument(
        "--crowding-window",
        type=int,
        default=None,
        help="override tsmom's; P11-b ran at 0, the registry has said 72 since 2026-09-05",
    )
    parser.add_argument("--symbols", default="", help="comma-separated; P11-b's static run was 15 names, today 18")
    parser.add_argument(
        "--symbols-file",
        default="",
        help="file holding the comma- or newline-separated list; the pit run pins 205 names, "
        "which is past what a command line should carry",
    )
    parser.add_argument("--from", dest="start", default=None, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD exclusive")
    args = parser.parse_args()
    if args.symbols_file:
        raw = Path(args.symbols_file).read_text(encoding="utf-8")
        args.symbols = ",".join(part for part in raw.replace("\n", ",").split(",") if part.strip())

    profile = load_yaml(args.profile)
    model, _ = build_model_from_profile(profile)
    if args.vol_target is not None:
        model = replace(model, portfolio=replace(model.portfolio, vol_target=args.vol_target))
    if args.crowding_window is not None:
        model = replace(
            model,
            entries=tuple(
                replace(entry, params={**entry.params, "crowding_window": args.crowding_window})
                if entry.id == "tsmom"
                else entry
                for entry in model.entries
            ),
        )
    costs = load_yaml("config/costs.yaml")
    cost = CostModel(
        turnover_bps=float(costs["taker_fee_bps"]) + float(costs["slippage_bps"]),
        use_funding=bool(costs.get("use_actual_funding", True)),
    )
    chosen = _resolve_symbols(args.root, args.symbols, "1h", args.mode)
    panel = _load(args.root, chosen, "1h", args.start, args.end, True)
    membership = _membership(args.root, args.mode, panel, 0)
    weights, _combined, _per = model.evaluate(panel, membership)
    bars_per_day = 24

    print(
        f"[{args.mode}] vol_target={model.portfolio.vol_target}  "
        f"{len(panel.symbols)} symbols x {len(panel.index)} bars  ({panel.index[0]} -> {panel.index[-1]})"
    )
    print(f"{'setting':30}{'worst name':>22}{'sum20 episodes':>16}{'sum20 names':>14}{'episodes':>10}")
    baseline: list[tuple[str, float]] = []
    for label, combo in SETTINGS:
        params = ExitParams.from_mapping({**combo, "bars_per_day": bars_per_day})
        adjusted = apply_exits(weights, panel.close, params).weights
        result = run_backtest(panel, adjusted, cost)
        row = tail(result.weights, result.net)
        baseline = baseline or list(row["ranked"])  # type: ignore[arg-type]
        name = f"{row['worst_value'] * 100:.3f}% ({row['worst_name']})"
        print(
            f"{label:30}{name:>22}{row['sum20_episodes'] * 100:>15.2f}%"
            f"{row['sum20_names'] * 100:>13.2f}%{row['episodes']:>10}"
        )
    # WHICH names carry the tail, for the first (baseline) setting only.  This is descriptive of the
    # problem, not a comparison of candidates: it says whether the loss is spread across the book -
    # where an exit rule is the only instrument - or concentrated in a few names, where a pool
    # admission gate would be, and that has to be decided BEFORE a grid is registered, not after.
    total = sum(value for _, value in baseline[:WORST_N])
    print(f"\nwhere the {WORST_N}-worst-names tail sits, at the baseline setting (share of {total * 100:.2f}%):")
    for rank, (symbol, value) in enumerate(baseline[:WORST_N], start=1):
        print(f"  {rank:>3}. {symbol:14}{value * 100:>8.3f}%{value / total * 100:>8.1f}%")


if __name__ == "__main__":
    main()
