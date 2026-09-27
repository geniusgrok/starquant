"""D-020 arm split: what the crowding-off and crowding-on configurations each score, separately.

RESEARCH_LOG.md records the numbers this reproduces (off 1.6450 / t 3.7333, on 1.5291 / 3.4798,
per-fold-selected mixture 1.5445 / 3.5027) and points at `scratchpad/verify_d020.py`, which is not in
the repo - the same class of unresolvable pointer that commit 3a4d7fd went back and fixed for P14.
This is that script, restored by recomputation rather than by memory.

Why it matters: the headline in tsmom-validation-20260903T181803Z is the per-fold-selected MIXTURE
(`chosen_params` crowding_window [72, 0, 72, 72, 0]), so three of its five folds run a modifier the
registry does not.  Reading 1.5445 as the shipped configuration's score is wrong in both directions.

It does not touch reports/research/trials.jsonl: counting a verification re-run as new trials would
inflate the DSR denominator for every future report.  Pure computation, no side effects.

RESULT, 2026-09-05 - the recomputation disagrees with the log, and the cause is dated:

    arm                        RESEARCH_LOG:385      recomputed (146 syms, same cutoff)
    crowding off (registry)    1.6450 / t 3.7333     1.6745 / t 3.8321
    crowding on                1.5291 / t 3.4798     1.8027 / t 4.1177   <- sign of the comparison flips

Not symbols (146 vs today's 205), not the cutoff, not min_train (4000 and 8000 agree): all three were
held fixed and the on arm still wins.  The cause is that 181803Z ran 2026-09-03 18:18, and D-034
landed 2026-09-04 20:44 (b0cc08a).  Its own docstring says what it fixed:

    Binance stamps fundingTime one to forty-seven milliseconds past the hour, and does so unevenly
    over time (34% of BTCUSDT's 2021 settlements land exactly on the hour against 85% of its 2024
    ones).  Matching a settlement to a bar open by equality therefore dropped 43.7% of the
    441,678-row archive onto a silent zero ... and the share missing differed from fold to fold.

The crowding modifier's only input is the trailing CROSS-SECTIONAL rank of funding.  In 181803Z it was
ranking a panel missing 43.7% of its settlements, with the missing share drifting by year and by fold.
That explains all three symptoms at once: the on arm moves (its input was corrupted), the off arm
barely does (it pays funding as a cost but never reads it as a signal), and the per-fold picks were
[72, 0, 72, 72, 0] then against all-72 now, because the handicap varied fold to fold.

552ca9a re-ran tsmom's evidence under the corrected funding the same evening - but added exactly one
row to trials.jsonl, crowding_window=0.  Only the off arm was re-scored.  So config/alpha_registry.yaml
still gives "on this evidence the modifier is a small negative (OOS 1.53 with vs 1.65 without)" as the
standing reason for crowding_window: 0, and that evidence predates the fix to the data the modifier
reads.

This does not say the modifier should be re-enabled.  It says the comparison it was rejected on has
not been made since its input was corrected.  A registered change needs `starquant research validate`,
which registers its trials; this script deliberately does not.
"""

from __future__ import annotations

from starquant_alpha.backtest import run_backtest
from starquant_alpha.validation.walk_forward import walk_forward_evaluate, walk_forward_folds
from starquant_cli.research_cmd import _entry, _load, _membership, _model, _resolve_symbols
from starquant_live.composition import cost_model
from starquant_shared.config import load_yaml

FOLDS, MIN_TRAIN, PURGE = 5, 4_000, 50  # the registry's recorded protocol for tsmom
ARMS = {"crowding off (registry)": 0, "crowding on": 72}


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    cost = cost_model(load_yaml("config/costs.yaml"), use_funding=True)
    chosen = _resolve_symbols(".starquant/data", "", "1h", "pit")
    panel = _load(".starquant/data", chosen, "1h", None, None, True)
    membership = _membership(".starquant/data", "pit", panel, 0)
    bpy = panel.bars_per_year

    nets: dict[str, object] = {}
    for label, window in ARMS.items():
        entry = _entry("tsmom", "config/alpha_registry.yaml", f'{{"crowding_window": {window}}}')
        model = _model(entry, profile, "1h", None)
        weights, _c, _p = model.evaluate(panel, membership)
        nets[label] = run_backtest(panel, weights, cost).portfolio_net

    length = len(next(iter(nets.values())))
    folds = walk_forward_folds(length, FOLDS, min_train=MIN_TRAIN, purge=PURGE)
    print(f"pit universe  bars={length}  folds={FOLDS}  min_train={MIN_TRAIN}  purge={PURGE}\n")
    print(f"{'arm':<26} {'OOS Sharpe':>11} {'NW t':>8} {'consistency':>12}   folds")
    print("-" * 88)

    for label in ARMS:
        result = walk_forward_evaluate({label: nets[label]}, {label: {}}, folds, bpy)
        summary = result.summary(bpy)
        per_fold = [f"{s:.2f}" if s is not None else "  na" for s in summary["fold_sharpes"]]
        print(
            f"{label:<26} {summary['oos_sharpe']:>11.4f} {summary['oos_t_stat']:>8.4f} "
            f"{summary['fold_consistency']:>12.2f}   [{', '.join(per_fold)}]"
        )

    mixed = walk_forward_evaluate(nets, {k: {"crowding_window": v} for k, v in ARMS.items()}, folds, bpy)
    ms = mixed.summary(bpy)
    picked = [p.get("crowding_window") for p in ms["chosen_params"]]
    print(
        f"{'per-fold-selected mixture':<26} {ms['oos_sharpe']:>11.4f} {ms['oos_t_stat']:>8.4f} "
        f"{ms['fold_consistency']:>12.2f}   picked {picked}"
    )
    print("\nThe mixture is what the report headlines; neither arm is what it scores.")


if __name__ == "__main__":
    main()
