"""Can a wider trailing stop reach this book's tail at all, and what would tightening the take-profit cost?

Five descriptive measurements that the Phase 7 adversarial review of the 2026-09-07 exits pre-registration
demanded BEFORE any billed `research overlay` run.  None of them evaluates a candidate setting: they
measure the episodes the CURRENT live setting already produces, so nothing here is a trial and nothing
is charged to `reports/research/trials.jsonl`.

Why each one exists (the kill it answers):

  KILL-TL04  sigma reachability.  `retrace = (extreme - price) * held / (sigma_entry * entry_price)` and a
             long's price floor is 0, so on a long that never rallies the retrace CANNOT exceed 1/sigma.
             AKE's live sigma is 0.2564 -> a ceiling of 3.9 sigma, below even the tested k=4.  So the
             question "does a trailing stop at k in {6, 9, 12} ever fire on the episodes that carry the
             tail" has to be answered by measurement, not assumed.  Reported for ALL episodes and for the
             worst 1% separately, because those are the only ones the rule would need to catch.
  KILL-TL03  D-017 headroom on the static universe is 0.0109 Sharpe, and each take-profit trigger there
             costs about 2.2e-4.  Tightening 6 -> 4 -> 3 raises the trigger count monotonically (anything
             reaching 6 sigma passed 3 and 4 first), so the MFE distribution says directly how far over
             budget that goes.
  KILL-TL01  a trailing stop ends an episode, splitting one into two, which shrinks every per-episode
             drawdown and inflates the episode count - the endpoint improves mechanically, P&L unmoved.
             The truncation count per k is the size of that artifact and is read off the same distribution.
  KILL-TL06  the pool-admission gate was ruled REFUTED using the ranked "20 worst names" statistic that the
             same document had just rejected.  Stratifying the tail by entry volatility and listing age is
             what that judgement actually needs.

Limits, stated rather than discovered later: episodes are segmented on EXECUTED weights, which lag the
decision bar `apply_exits` anchors on by one bar; the entry reference here is the bar close, while the
live overlay adopts the venue VWAP (`starquant_live/exits.py:_reconcile`); listing age is measured from the
first bar in the loaded panel, so anything listed before the panel start is understated.

    python scratchpad/exit_reachability.py pit|static [--root .starquant/data] [--symbols-file F]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits, daily_vol
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.config import build_model_from_profile
from starquant_shared.config import load_yaml

# The setting that is live today.  Everything below describes the episodes THIS produces.
LIVE = {"stop_loss": 6.0, "trailing_stop": 0.0, "take_profit": 6.0}
K_RETRACE = (3.0, 4.0, 6.0, 9.0, 12.0)
K_MFE = (3.0, 4.0, 6.0)
WORST_FRACTION = 0.01


def episodes(
    held: pd.Series, net: pd.Series, close: pd.Series, sigma: pd.Series, first_bar: int
) -> list[dict[str, float]]:
    """One record per same-direction holding episode, carrying everything the four kills need.

    Also carries `mfe_pnl` (the cumulative net-P&L path's own running peak, return units) and
    `realised_pnl` (that path's value at episode close) unused by any KILL-TL check above but reused,
    unmodified, by `scratchpad/m_ex01_retention.py` (GAP-EX01 / M-EX01) for the retention ratio
    `realised_pnl / mfe_pnl` - so that script does not re-derive this same segmentation and cumulative
    P&L path a second time.
    """
    sign = np.sign(held.to_numpy(dtype=float))
    pnl = net.to_numpy(dtype=float)
    price = close.to_numpy(dtype=float)
    vol = sigma.to_numpy(dtype=float)
    out: list[dict[str, float]] = []
    start = 0
    while start < len(sign):
        if sign[start] == 0.0 or not np.isfinite(price[start]) or price[start] <= 0:
            start += 1
            continue
        stop = start + 1
        while stop < len(sign) and sign[stop] == sign[start]:
            stop += 1
        direction = sign[start]
        entry, unit = price[start], max(vol[start] if np.isfinite(vol[start]) else 0.005, 0.005)
        window = price[start:stop]
        # the overlay's own two quantities, in the unit it uses: entry-time daily sigma
        running = np.maximum.accumulate(window) if direction > 0 else np.minimum.accumulate(window)
        retrace = (running - window) * direction / (unit * entry)
        favourable = (window - entry) * direction / (unit * entry)
        cumulative = np.concatenate([[0.0], np.cumsum(pnl[start:stop])])
        out.append(
            {
                "loss": float((cumulative - np.maximum.accumulate(cumulative)).min()),
                "max_retrace": float(np.nanmax(retrace)) if len(retrace) else 0.0,
                "max_mfe": float(np.nanmax(favourable)) if len(favourable) else 0.0,
                "mfe_pnl": float(np.nanmax(cumulative)),
                "realised_pnl": float(cumulative[-1]),
                "entry_sigma": float(unit),
                "bars": float(stop - start),
                "age_days": float((start - first_bar) / 24.0),
                "direction": float(direction),
            }
        )
        start = stop
    return out


def _share(values: np.ndarray, threshold: float) -> str:
    return f"{float((values >= threshold).mean()) * 100:5.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pit", "static"))
    parser.add_argument("--root", default=".starquant/data")
    parser.add_argument("--profile", default="config/live.demo.yaml")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--symbols-file", default="")
    args = parser.parse_args()
    if args.symbols_file:
        raw = Path(args.symbols_file).read_text(encoding="utf-8")
        args.symbols = ",".join(part for part in raw.replace("\n", ",").split(",") if part.strip())

    profile = load_yaml(args.profile)
    model, _ = build_model_from_profile(profile)
    costs = load_yaml("config/costs.yaml")
    cost = CostModel(
        turnover_bps=float(costs["taker_fee_bps"]) + float(costs["slippage_bps"]),
        use_funding=bool(costs.get("use_actual_funding", True)),
    )
    chosen = _resolve_symbols(args.root, args.symbols, "1h", args.mode)
    panel = _load(args.root, chosen, "1h", None, None, True)
    membership = _membership(args.root, args.mode, panel, 0)
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
    frame = pd.DataFrame(records)
    worst = frame.nsmallest(max(1, int(len(frame) * WORST_FRACTION)), "loss")

    print(f"[{args.mode}] live setting {LIVE}  {len(panel.symbols)} symbols x {len(panel.index)} bars")
    print(f"{len(frame)} holding episodes; the worst {WORST_FRACTION:.0%} = {len(worst)} of them\n")

    print("(1) KILL-TL04 - max retrace reached inside an episode, in ENTRY-time daily sigma")
    for label, subset in (("all episodes", frame), (f"worst {len(worst)}", worst)):
        values = subset["max_retrace"].to_numpy()
        q = np.percentile(values, [50, 90, 99])
        reach = "  ".join(f">={k:g}s {_share(values, k)}" for k in K_RETRACE)
        print(f"  {label:16} median {q[0]:5.2f}  p90 {q[1]:5.2f}  p99 {q[2]:5.2f}   {reach}")

    print("\n(3) KILL-TL01 - episodes a trailing stop at k would TRUNCATE (the endpoint artifact's size)")
    base = len(frame)
    for k in K_RETRACE:
        hit = int((frame["max_retrace"] >= k).sum())
        print(f"  k={k:<5g} truncates {hit:5d} of {base} episodes -> episode count +{hit / base * 100:5.1f}%")

    print("\n(2) KILL-TL03 - max favourable excursion inside an episode, same unit (take-profit side)")
    values = frame["max_mfe"].to_numpy()
    q = np.percentile(values, [50, 90, 99])
    print(f"  all episodes     median {q[0]:5.2f}  p90 {q[1]:5.2f}  p99 {q[2]:5.2f}")
    at6 = int((values >= 6.0).sum())
    for k in K_MFE:
        hit = int((values >= k).sum())
        extra = "" if k >= 6.0 else f"   = {hit / max(at6, 1):.1f}x the trigger count of tp6"
        print(f"  tp={k:<5g} fires on {hit:5d} episodes{extra}")

    print("\n(4) KILL-TL06 - where the tail sits, by entry volatility and by listing age")
    for column, label, bins in (
        ("entry_sigma", "entry sigma", [0, 0.03, 0.05, 0.08, 1.0]),
        ("age_days", "listing age (days, from panel start)", [0, 90, 365, 730, 1e9]),
    ):
        frame["bucket"] = pd.cut(frame[column], bins=bins, right=False)
        print(f"  by {label}:")
        total_loss = frame["loss"].sum()
        for bucket, group in frame.groupby("bucket", observed=True):
            in_worst = int(((worst[column] >= bucket.left) & (worst[column] < bucket.right)).sum())
            share = group["loss"].sum() / total_loss * 100
            print(
                f"    {bucket!s:22} {len(group):5d} episodes  {share:5.1f}% of total loss  "
                f"{in_worst:4d} in the worst {len(worst)}"
            )


if __name__ == "__main__":
    main()
