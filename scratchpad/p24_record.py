"""P24: write the two declared diagnostic trials to the ledger, one row per (candidate x universe x entry).

Separate from `exit_paired_ruler.py` on purpose: the measurement must be repeatable without charging, and
a failed measurement must not half-charge the ledger.  Rows are built with the SAME helpers
`starquant research overlay` uses (`_construction_digest`, `_symbol_set_hash`, `_short_digest`,
`param_key`, `_record_trials`), so a P24 row is indistinguishable in kind from a row a real overlay run
would have written - which is the point: it IS the same kind of trial.

Charge, corrected before writing.  The pre-registration said "each arm once, tsmom +2 / flow +2".  That
was wrong about this repository's own convention: P22b wrote 8 rows for 2 candidates
(2 candidates x 2 universes x 2 entries) and its log records tsmom 100 -> 104, i.e. +4 per strategy.
P24 has the same shape, so the honest charge is tsmom +4 / flow +4 - which is what the operator had
already said they were willing to spend before the estimate was refined downward.  Under-charging is the
dangerous direction: it makes every later verdict look more significant than it is.

    python scratchpad/p24_record.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starquant_alpha.backtest import run_backtest
from starquant_alpha.overlays.exits import ExitParams, apply_exits
from starquant_alpha.panel import interval_seconds
from starquant_alpha.validation.ledger import TrialRecord
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_cmd import (
    _construction_digest,
    _record_trials,
    _short_digest,
    _symbol_set_hash,
)
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, cost_model, load_panel, load_registry
from starquant_shared.config import load_yaml

ROOT = ".starquant/data"
INTERVAL = "1h"
LEDGER = Path("reports/research/trials.jsonl")
ARMS = {"P24-arm1": {"take_profit": 8.0}, "P24-arm2": {"cooldown_bars": 6}}


def build(mode: str):
    profile = load_yaml("config/live.demo.yaml")
    costs = load_yaml("config/costs.yaml")
    table = pd.read_parquet(Path(ROOT) / MEMBERSHIP_FILE).astype(bool)
    idx = pd.DatetimeIndex(table.index)
    table.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    store = KlineStore(ROOT)
    stored = set(store.symbols(INTERVAL))
    symbols = [str(s) for s in table.columns[table.any(axis=0)] if s in stored]
    if mode == "static":
        keep = set(json.loads(Path(".starquant/live/state.json").read_text())["universe"]) & set(symbols)
        symbols = [s for s in symbols if s in keep]
        table = table[symbols]
        table.loc[:, :] = True
    panel = load_panel(store, symbols, INTERVAL, funding_store=FundingStore(ROOT))
    membership = membership_at_bars(table, panel.index)
    model = build_model(load_registry(Path("config/alpha_registry.yaml")), profile)
    cost = cost_model(costs, use_funding=True)
    weights, _c, _p = model.evaluate(panel, membership)
    return profile, panel, model, cost, weights


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Added 2026-09-16, after a repository review found this was the one committed script that writes
    # the REAL ledger and had already run.  Its 8 rows are in `trials.jsonl` under the two run_ids in
    # ARMS; a second run charges them twice, and the ledger is append-only by design, so a bad row
    # cannot be taken back out - it would raise the DSR denominator for tsmom and flow permanently.
    # `_record_trials` deduplicates on (param_key, range, symbols), NOT on run_id, and `recorded_at`
    # is stamped fresh every run, so nothing downstream was going to stop this.
    #
    # Checked BEFORE the backtests rather than beside the write: the measurement takes minutes, and a
    # refusal that arrives after them teaches people to reach for the flag that skips it.  Refuse
    # rather than silently write nothing - a script that no-ops is how someone concludes the charge
    # never happened.  Re-measuring stays free: that is what --dry-run is for, and it is why
    # `exit_paired_ruler.py` is a separate file.
    if not args.dry_run:
        charged_ids = {json.loads(line).get("run_id") for line in LEDGER.read_text().splitlines() if line.strip()}
        clash = sorted(set(ARMS) & charged_ids)
        if clash:
            raise SystemExit(
                f"refusing to write: {LEDGER} already carries rows for {clash}.  P24 was charged once "
                "(tsmom +4 / flow +4, 2026-09-08); charging it again would inflate the DSR denominator "
                "for good.  Re-measure with --dry-run."
            )

    stamp = datetime.now(UTC).isoformat()
    records: list[TrialRecord] = []
    for mode in ("pit", "static"):
        profile, panel, model, cost, weights = build(mode)
        bars_per_day = max(1, 86_400 // interval_seconds(INTERVAL))
        live_map = {**(profile.get("exits") or {}), "bars_per_day": bars_per_day}
        construction = _construction_digest(model.portfolio.__dict__, cost, execution="open_to_close")
        symbol_hash = _symbol_set_hash(panel.symbols)
        base_index = run_backtest(panel, weights, cost, execution="open_to_close").weights.index
        for run_id, override in ARMS.items():
            params = ExitParams.from_mapping({**live_map, **override})
            adjusted = apply_exits(weights, panel.close, params).weights
            result = run_backtest(panel, adjusted, cost, execution="open_to_close")
            full_sharpe = float(result.summary()["annualized_sharpe"])
            overlay_digest = _short_digest({"kind": "exits", "params": dict(vars(params))})
            print(
                f"{mode:<7} {run_id}  {override}  full_sharpe={full_sharpe:.6f}  "
                f"overlay={overlay_digest}  constr={construction}  symbols={len(panel.symbols)}"
            )
            for entry in model.entries:
                records.append(
                    TrialRecord(
                        strategy=entry.id,
                        param_key=param_key(dict(entry.params)),
                        sharpe_annual=full_sharpe,
                        bars_per_year=panel.bars_per_year,
                        recorded_at=stamp,
                        range_start=str(base_index[0]),
                        range_end=str(base_index[-1]),
                        symbols=len(panel.symbols),
                        run_id=run_id,
                        construction_digest=construction,
                        symbol_set_hash=symbol_hash,
                        overlay_digest=overlay_digest,
                    )
                )

    print(f"\n{len(records)} rows built ({sorted({r.strategy for r in records})})")
    if args.dry_run:
        print("--dry-run: nothing written")
        return
    charged = _record_trials(LEDGER, records)
    print(f"charged {charged} rows to {LEDGER}")


if __name__ == "__main__":
    main()
