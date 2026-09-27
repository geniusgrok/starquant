"""P28 更正的复算：`pairs` 的 partner 是从哪个总体里挑的，以及被验证的那本书是不是配对。

只读。不写 `.starquant/`、不写 `reports/`、不碰账本、不跑 `research validate`。

复算的是 `reports/research/pairs-validation-20260908T172303Z.json` 那次运行的面板。**面板要钉住**：
kline store 自那次运行以来已经长了 24 根 bar，不钉的话 `pair_bars` 会差 72、`exactly_one` 会差 24,
四个数没有一个对得上——第一次跑就是这么发现要钉的。钉法是切到报告自己的 `range.end`。

产出四组数：

1. **复核** ——「块 5 的「配对选择计费」」§「顺手撞出来的两条」② 记的四个数；
2. **持仓口径的裸腿** —— 62.3% 是掩码口径（eligible），这里按 `strategy_targets` 真正持有的腿再算一遍；
3. **两种「曾经同时可交易」** —— 全样本任一 bar（= 那条记的 80），与**该对被持有期间**任一 bar（= 25）；
4. **限回 reference 之后的搜索空间** —— 重开这条要预登记的 N。

`_examined` / `_mutual_pairs` / `_normalised` / `_refits` 直接从信号里 import 而不是抄一份：抄一份就会
在下一次那边改规则时静默分叉，而分叉的方向总是把 N 算小——这正是 `search_census` 自己写明的理由。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import combinations

import numpy as np
import pandas as pd

from starquant_alpha.model import AlphaModel, StrategyEntry
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.signals.pairs import PairsParams, _examined, _mutual_pairs, _normalised, _refits
from starquant_alpha.validation.multiple_testing import expected_max_sharpe, max_sharpe_quantile
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars, tenure_mask
from starquant_data.store import KlineStore
from starquant_live.composition import load_panel

ROOT = "~/starquant/.starquant/data"
REPORT = "reports/research/pairs-validation-20260908T172303Z.json"
INTERVAL = "1h"
MIN_HISTORY_BARS = 720  # config/live.demo.yaml portfolio.min_history_bars, the validate default
MIN_TENURE = 0  # the run's --min-tenure
# `best_params` from the report; `grid` was entry_z [1.5, 2.0] x z_window [168, 336].
BEST = {
    "formation_bars": 720,
    "refit_bars": 720,
    "z_window": 168,
    "entry_z": 2.0,
    "exit_z": 0.5,
    "z_scale": 3.0,
    "min_corr": 0.5,
    "entry_threshold": 0.2,
}
GRID_Z_WINDOWS = (168, 336)  # entry_z touches neither `_normalised` nor `_mutual_pairs`; checked, not assumed


def read_membership() -> pd.DataFrame:
    table = pd.read_parquet(f"{ROOT}/{MEMBERSHIP_FILE}")
    index = pd.DatetimeIndex(table.index)
    table.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return table.astype(bool)


def pit_symbols() -> list[str]:
    """`research_cmd._resolve_symbols(..., universe_mode="pit")`, so this imports no CLI."""
    table = read_membership()
    stored = set(KlineStore(ROOT).symbols(INTERVAL))
    return [s for s in (str(c) for c in table.columns[table.any(axis=0)]) if s in stored]


def main() -> None:
    with open(REPORT) as handle:
        report = json.load(handle)
    run_end = pd.Timestamp(report["range"]["end"]) + pd.Timedelta(hours=1)  # slice is half-open
    panel = load_panel(KlineStore(ROOT), pit_symbols(), INTERVAL).slice(end=run_end)
    # funding is not loaded: `pairs` reads none, and funding is reindexed ONTO the kline index, so it
    # can move neither the bars nor the eligible mask.  Loading it would only cost time.
    membership = membership_at_bars(tenure_mask(read_membership(), MIN_TENURE), panel.index)
    model = AlphaModel(
        entries=(StrategyEntry(id="pairs", params=dict(BEST)),),
        portfolio=PortfolioParams(),
        interval=INTERVAL,
        min_history_bars=MIN_HISTORY_BARS,
    )
    eligible = model.eligible(panel, membership)
    elig = eligible.to_numpy(dtype=bool)
    # a leg the book actually held: a target that is neither NaN (never scored) nor 0.0 (flat/exited)
    held = np.nan_to_num(model.strategy_targets(panel, membership)["pairs"].to_numpy(dtype=float), nan=0.0) != 0.0

    p = PairsParams.from_mapping(BEST)
    normalised = _normalised(panel.close, p)
    values = normalised.to_numpy(dtype=float)
    n = len(panel.close)

    selected: set[tuple[int, int]] = set()
    e_both = e_one = e_none = 0  # pair-bars by ELIGIBILITY, inside the window the pair was traded
    h_both = h_one = h_none = 0  # the same bars by what was actually HELD
    overlap_held: set[tuple[int, int]] = set()
    for refit in _refits(n, p):
        window = normalised.iloc[refit - p.formation_bars : refit]
        _columns, pairs = _mutual_pairs(window, p.min_corr)
        stop = min(n, refit + p.refit_bars)
        for left, right in pairs:
            formation = values[refit - p.formation_bars : refit, [left, right]]
            spread = np.nancumsum(formation[:, 0] - formation[:, 1])
            scale = float(np.nanstd(spread[-p.z_window :]))
            if not np.isfinite(scale) or scale <= 0:
                continue  # the gate `pairs_scores` applies before it writes anything
            selected.add((left, right) if left < right else (right, left))
            lhs, rhs = elig[refit:stop, left], elig[refit:stop, right]
            n_both, n_any = int(np.count_nonzero(lhs & rhs)), int(np.count_nonzero(lhs | rhs))
            e_both, e_one, e_none = e_both + n_both, e_one + (n_any - n_both), e_none + (stop - refit) - n_any
            if n_both:
                overlap_held.add((left, right) if left < right else (right, left))
            lhs, rhs = held[refit:stop, left], held[refit:stop, right]
            n_both, n_any = int(np.count_nonzero(lhs & rhs)), int(np.count_nonzero(lhs | rhs))
            h_both, h_one, h_none = h_both + n_both, h_one + (n_any - n_both), h_none + (stop - refit) - n_any

    overlap_panel = {k for k in selected if bool(np.any(elig[:, k[0]] & elig[:, k[1]]))}

    # The search space, unrestricted and restricted, as a UNION over the grid - which is what the
    # ledger charges and what the docstring's 19,578 already is (19,576 at 168, 19,563 at 336).
    names = [str(c) for c in panel.close.columns]
    unrestricted: set[tuple[str, str]] = set()
    restricted: set[tuple[str, str]] = set()
    for z_window in GRID_Z_WINDOWS:
        q = PairsParams.from_mapping({**BEST, "z_window": z_window})
        frame = _normalised(panel.close, q)
        for refit in _refits(n, q):
            window = frame.iloc[refit - q.formation_bars : refit]
            columns = [int(c) for c in _examined(window)]
            unrestricted.update(tuple(sorted((names[i], names[j]))) for i, j in combinations(sorted(columns), 2))
            # the population as of the last bar STRICTLY BEFORE the refit - point-in-time at the
            # moment the partner is chosen, which is the bar the rest of this loop already respects
            reference = elig[refit - 1]
            kept = sorted(c for c in columns if reference[c])
            restricted.update(tuple(sorted((names[i], names[j]))) for i, j in combinations(kept, 2))

    # The D-028 gate at a different N.  A PROJECTION, not new evidence: it re-uses the archived
    # report's own `variance` and re-runs the repo's own gate.  Nothing is re-backtested.  The two
    # published points below are printed as a check on the method, not as a result.
    sel = report["oos_selection"]
    scale = math.sqrt(365.0 * 24.0)
    gates = {
        n_trials: round(max_sharpe_quantile(n_trials, sel["variance"], sel["alpha"]) * scale, 4)
        for n_trials in (4, len(restricted) + 4, len(unrestricted) + 4, 20_255)
    }
    e_any, h_any = e_both + e_one, h_both + h_one
    json.dump(
        {
            "panel": {"symbols": len(panel.symbols), "bars": n, "end": str(panel.index[-1])},
            "pit_members_per_bar": {
                "median": float(eligible.sum(axis=1).median()),
                "mean": round(float(eligible.sum(axis=1).mean()), 4),
                "max": int(eligible.sum(axis=1).max()),
            },
            "selected_pairs": len(selected),
            "overlap": {
                "both_legs_eligible_while_held": len(overlap_held),
                "both_legs_eligible_anywhere_in_panel": len(overlap_panel),
            },
            "pair_bars_by_eligibility": {
                "both": e_both,
                "exactly_one": e_one,
                "neither": e_none,
                "at_least_one": e_any,
                "share_exactly_one": round(e_one / e_any, 6),
            },
            "pair_bars_by_held_target": {
                "both": h_both,
                "exactly_one": h_one,
                "neither": h_none,
                "at_least_one": h_any,
                "share_exactly_one": round(h_one / h_any, 6),
            },
            "search_space_union_over_grid": {
                "unrestricted": len(unrestricted),
                "reference_restricted": len(restricted),
            },
            "projected_gate_annual": gates,
            "oos_sharpe_annual": round(sel["oos_sharpe_annual"], 4),
            "method_check": {
                "gate_at_4_should_be": round(sel["threshold_annual"], 4),
                "expected_max_at_4_should_be": round(sel["expected_max_annual"], 4),
                "expected_max_at_4_recomputed": round(expected_max_sharpe(4, sel["variance"]) * scale, 4),
            },
        },
        sys.stdout,
        indent=2,
    )
    print()


if __name__ == "__main__":
    main()
