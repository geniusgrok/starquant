"""Calibrate the probe stop on the caliber its evidence is in.  Pre-registered 2026-09-12 at b883d01e.

The live stop reads a realised-income series whose 30-day sigma is 0.137% of equity, while the sleeve's
evidence is a mark-to-market P&L whose 30-day sigma is about 2.34% - so `-2%` sits at 14.6 sigma of the
series it reads and 0.85 sigma of the series it was calibrated against.  Neither is the "-2 sigma"
D-019 claimed.

This recomputes, over the panel the book report was validated on, each book's own 30-day rolling
mark-to-market P&L as a share of equity, and takes the EMPIRICAL 2.28% quantile (= Phi(-2)) - not
2 x sigma, because a 30-day rolling sum is fat-tailed and autocorrelated and the normal assumption is
where this rule went wrong in the first place.

Measures the configuration already in force.  No grid, no selection, no comparison: not a trial, so no
ledger row (stated in the pre-registration).
"""

from __future__ import annotations

import json

import numpy as np

from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import load_panel
from starquant_live.config import build_model_from_profile, load_profile
from starquant_live.probe import probes_from_registry

ROOT = ".starquant/data"
WINDOW = 720  # 30 days of hourly bars, the probe stop's own window
QUANTILE = 0.0228  # Phi(-2): the same tail probability D-019 claimed for -2%
REPORT = "reports/research/book-tsmom-flow-20260908T105322Z.json"


def main() -> None:
    payload = load_profile("config/live.demo.yaml")
    model, registry = build_model_from_profile(payload)
    with open(REPORT) as handle:
        book = json.load(handle)
    window = book["universes"]["pit"]["range"]
    print(f"validated range {window['start']} .. {window['end']}  ({window['bars']} bars)")

    store = KlineStore(ROOT)
    symbols = sorted(store.symbols("1h"))
    panel = load_panel(
        store,
        symbols,
        "1h",
        funding_store=FundingStore(ROOT),
        start=str(window["start"])[:10],
        end=str(window["end"])[:10],
    )
    print(f"panel {panel.close.shape[0]} bars x {panel.close.shape[1]} symbols")

    per_strategy = model.strategy_targets(panel, None)
    books = model.book_weights(per_strategy, panel.close, panel.bars_per_year)
    returns = panel.close.pct_change(fill_method=None)

    print(f"\n{'book':12s} {'ann sigma':>10s} {'30d sigma':>10s} {'2.28% quantile':>15s} "
          f"{'-2 x sigma':>11s} {'现行 max_loss':>13s} {'现行位于':>10s}")
    current = {p.book: p.max_loss for p in probes_from_registry(registry)}
    out = {}
    for name, weights in books.items():
        aligned = weights.shift(1).reindex(columns=returns.columns).fillna(0.0)
        pnl = (aligned * returns.fillna(0.0)).sum(axis=1)       # book P&L per bar, share of equity
        rolling = pnl.rolling(WINDOW).sum().dropna()
        sigma_h = pnl.std(ddof=1)
        sigma_30 = rolling.std(ddof=1)
        q = float(rolling.quantile(QUANTILE))
        have = current.get(name)
        where = "-" if not have else f"{have / sigma_30:.2f}σ"
        out[name] = {"sigma_30d": float(sigma_30), "quantile": q, "n": int(rolling.size)}
        print(f"{name:12s} {sigma_h * np.sqrt(8760):10.2%} {sigma_30:10.3%} {q:15.3%} "
              f"{-2 * sigma_30:11.3%} {(have or 0):13.2%} {where:>10s}")
    print("\nrolling windows per book:", {k: v["n"] for k, v in out.items()})
    with open("scratchpad/probe_stop_recalibration.json", "w") as handle:
        json.dump(out, handle, indent=2)


main()


def falsifier_three() -> None:
    """F3: would the NEW threshold have fired on the most recent data available?

    The live record cannot answer yet - `book_weights` starts today - so the closest reading is the
    tail of the validated panel, which ends 2026-09-07, five days before the change.
    """
    payload = load_profile("config/live.demo.yaml")
    model, _registry = build_model_from_profile(payload)
    store = KlineStore(ROOT)
    panel = load_panel(store, sorted(store.symbols("1h")), "1h", funding_store=FundingStore(ROOT), start="2021-01-31")
    per_strategy = model.strategy_targets(panel, None)
    books = model.book_weights(per_strategy, panel.close, panel.bars_per_year)
    returns = panel.close.pct_change(fill_method=None)
    with open("scratchpad/probe_stop_recalibration.json") as handle:
        cal = json.load(handle)
    print(f"\n{'book':12s} {'新阈值':>9s} {'最近 30 天读数':>15s} {'最差的最近 90 天':>17s}  F3")
    for name, weights in books.items():
        aligned = weights.shift(1).reindex(columns=returns.columns).fillna(0.0)
        rolling = (aligned * returns.fillna(0.0)).sum(axis=1).rolling(WINDOW).sum().dropna()
        threshold = round(-cal[name]["quantile"], 3)
        latest = float(rolling.iloc[-1])
        worst90 = float(rolling.tail(90 * 24).min())
        fired = latest <= -threshold
        print(f"{name:12s} {-threshold:9.1%} {latest:15.3%} {worst90:17.3%}  {'触发 → 不发布' if fired else '未触发'}")


falsifier_three()
