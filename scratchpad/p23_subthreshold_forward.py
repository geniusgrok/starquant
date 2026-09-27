"""P23 step 0 (K-EX02): do sub-threshold holds earn less than actionable holds?  One diagnostic trial, charged.

For every held symbol-bar of the shipped tsmom on the point-in-time universe, split by whether the raw
score was actionable (|score| >= 0.20) or sub-threshold (held on NO_ACTION), and compare the sign-adjusted
forward return at 24 and 72 bars.  If the sub-threshold bars are not significantly worse, O-EX1 stops here.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np

from starquant_alpha.signals.tsmom import TsmomParams, tsmom_scores
from starquant_alpha.validation.labels import forward_returns
from starquant_alpha.validation.ledger import TrialRecord, resolve_ledger_path
from starquant_alpha.validation.walk_forward import param_key
from starquant_cli.research_cmd import (
    _load,
    _membership,
    _record_trial,
    _resolve_symbols,
    _short_digest,
    _symbol_set_hash,
)
from starquant_live.composition import build_model, load_registry
from starquant_shared.config import load_yaml

# ROOT is the absolute main-checkout data store: this worktree (feat/exits-p23) has no .starquant/data of its own.
ROOT, INTERVAL, UNIVERSE = "~/starquant/.starquant/data", "1h", "pit"


def main() -> None:
    profile = load_yaml("config/live.demo.yaml")
    registry = load_registry("config/alpha_registry.yaml")
    model = build_model(registry, profile)
    symbols = _resolve_symbols(ROOT, "", INTERVAL, UNIVERSE)
    panel = _load(ROOT, symbols, INTERVAL, None, None, True)
    membership = _membership(ROOT, UNIVERSE, panel)
    entry = next(e for e in registry.enabled if e.id == "tsmom")
    params = TsmomParams.from_mapping(entry.params)
    raw = tsmom_scores(panel.close, params)
    held = model.strategy_targets(panel, membership)["tsmom"]
    direction = np.sign(held.fillna(0.0))
    lines = []
    for horizon in (24, 72):
        fwd = forward_returns(panel.close, horizon) * direction
        active = direction != 0
        sub = active & (raw.abs() < params.entry_threshold)
        act = active & (raw.abs() >= params.entry_threshold)
        a, s = fwd.where(act).stack().dropna(), fwd.where(sub).stack().dropna()
        # overlapping labels: shrink the effective n by the horizon (a conservative, not exact, correction)
        se = math.sqrt(a.var() / (len(a) / horizon) + s.var() / (len(s) / horizon))
        t = (a.mean() - s.mean()) / se if se > 0 else float("nan")
        lines.append(f"h={horizon}: actionable mean {a.mean()*1e4:+.1f} bps (n {len(a)}), sub-threshold mean {s.mean()*1e4:+.1f} bps (n {len(s)}), diff t {t:+.2f}")
    print("\n".join(lines))
    ledger = resolve_ledger_path()
    charged = _record_trial(ledger, TrialRecord(
        strategy="tsmom", param_key=param_key(dict(entry.params)), sharpe_annual=None, bars_per_year=float(panel.bars_per_year),
        recorded_at=datetime.now(UTC).isoformat(), range_start=str(panel.index[0]), range_end=str(panel.index[-1]),
        symbols=len(panel.symbols), run_id="P23-step0", symbol_set_hash=_symbol_set_hash(panel.symbols),
        overlay_digest=_short_digest({"kind": "diagnostic", "what": "subthreshold_forward_returns"}),
    ))
    print(f"charged {int(charged)} row to {ledger}")


if __name__ == "__main__":
    main()
