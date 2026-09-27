"""M-EX01 baseline (GAP-EX01): the retention ratio of each closed holding episode, on the shipped exit
construction, for both universes.

Not charged to `reports/research/trials.jsonl`, on the same basis `exit_reachability.py` was not charged
(its own docstring, and the Phase 7 adversarial review of the 2026-09-07 exits pre-registration that
demanded it): this measures the episodes the CURRENT live setting already produces, evaluates no candidate,
and selects among nothing, so nothing here is a trial.

Retention ratio, per closed same-direction holding episode: realised P&L (the episode's cumulative net
return, entry to close) divided by the episode's maximum favourable excursion (MFE) - the highest that
same cumulative-return path ever reached, including the close itself, so the ratio is bounded above by
1.0 (closing exactly at the peak) and unbounded below (giving back the whole gain and then some). An
episode whose path never went positive (MFE <= 0) has nothing to retain and is counted separately rather
than folded into the ratio.

This is M-EX01, the deep-analysis's leading Success Definition metric (`docs/analysis/2026-09-07-exits-
adaptive-tp-sl-deep-analysis.md` S4.4): it was defined before any solution was chosen so it measures the
*problem* (how much of a paper gain does this book's construction typically give back before a position
closes) independent of which exit rule, if any, is responsible - which is also why it is computed once
here on the shipped construction rather than swept over a grid.

Reuses `episodes()` from `exit_reachability.py` unmodified in its segmentation logic (same same-direction
run detection, same cumulative-P&L path); the only change made there was two additional fields read off a
quantity that function already computes (`mfe_pnl`, `realised_pnl` from its `cumulative` array), so this
script does not re-derive the segmentation.

    python scratchpad/m_ex01_retention.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exit_reachability import LIVE, episodes

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits, daily_vol
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

# Absolute: this worktree (feat/exits-p23) has no .starquant/data of its own (same as p23_subthreshold_forward.py).
ROOT = "~/starquant/.starquant/data"
PROFILE = "config/live.demo.yaml"
QUANTILES = (0.25, 0.5, 0.75)


def _episode_frame(mode: str) -> pd.DataFrame:
    """The shipped construction's holding episodes for one universe - same pipeline as
    `exit_reachability.main()`, not a new one, up to the point where that function starts printing."""
    profile = load_yaml(PROFILE)
    model, _ = build_model_from_profile(profile)
    costs = load_yaml("config/costs.yaml")
    cost = CostModel(
        turnover_bps=float(costs["taker_fee_bps"]) + float(costs["slippage_bps"]),
        use_funding=bool(costs.get("use_actual_funding", True)),
    )
    chosen = _resolve_symbols(ROOT, "", "1h", mode)
    panel = _load(ROOT, chosen, "1h", None, None, True)
    membership = _membership(ROOT, mode, panel, 0)
    weights, _combined, _per = model.evaluate(panel, membership)
    params = ExitParams.from_mapping({**LIVE, "bars_per_day": 24})
    result = run_backtest(panel, apply_exits(weights, panel.close, params).weights, cost)

    held, net = result.weights, result.net
    close = panel.close.reindex(index=held.index, columns=held.columns)
    sigma = daily_vol(panel.close, params).reindex(index=held.index, columns=held.columns)
    listed = {symbol: int(np.argmax(panel.close[symbol].notna().to_numpy())) for symbol in held.columns}

    records: list[dict[str, float]] = []
    for symbol in held.columns:
        if symbol not in net.columns:
            continue
        for row in episodes(held[symbol], net[symbol], close[symbol], sigma[symbol], listed.get(symbol, 0)):
            records.append({**row, "symbol": symbol})
    return pd.DataFrame(records)


def _summarise(mode: str, frame: pd.DataFrame) -> None:
    total = len(frame)
    scored = frame[frame["mfe_pnl"] > 0].copy()
    scored["retention"] = scored["realised_pnl"] / scored["mfe_pnl"]
    excluded = total - len(scored)

    ret_q = scored["retention"].quantile(list(QUANTILES))
    mfe_q = scored["mfe_pnl"].quantile(list(QUANTILES))
    med_bars = scored["bars"].median()

    print(f"[{mode}] {total} holding episodes; {excluded} never went ahead (MFE<=0, excluded from the ratio)")
    print(f"  scored episodes: {len(scored)}")
    print(
        "  retention ratio (realised / MFE)   "
        f"p25 {ret_q[0.25]:+.3f}  median {ret_q[0.5]:+.3f}  p75 {ret_q[0.75]:+.3f}"
    )
    print(
        "  MFE (cumulative net return, scored episodes)   "
        f"p25 {mfe_q[0.25] * 100:.2f}%  median {mfe_q[0.5] * 100:.2f}%  p75 {mfe_q[0.75] * 100:.2f}%"
    )
    print(f"  episode length (bars, scored episodes)   median {med_bars:.1f}")


def main() -> None:
    for mode in ("pit", "static"):
        _summarise(mode, _episode_frame(mode))


if __name__ == "__main__":
    main()
