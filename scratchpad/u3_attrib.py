"""U-3, second cut: attribute the gap between today's reproduction and the recorded 1.0745.

Two suspects changed under the 2026-09-04 13:56 mine run: the ``--funding`` arm
(unrecorded in the report) and ``vol_target`` (P13 pushed 0.15 -> 0.30 the same
day).  D-035 says net Sharpe is exactly invariant to vol_target *when nothing
binds* - but D-036 measured 355 capped bars on the point-in-time universe at
0.30, so max_weight and the gross cap do bind there and the invariance breaks.
Cross the two.
"""

from dataclasses import replace

from starquant_alpha.backtest import run_backtest
from starquant_alpha.mining import enumerate_candidates, to_signal
from starquant_alpha.model import AlphaModel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import register as register_signal
from starquant_alpha.validation.metrics import sharpe
from starquant_cli.research_cmd import (
    _load,
    _membership,
    _resolve_symbols,
    cost_model,
    portfolio_params,
)
from starquant_shared.config import load_yaml

WANTED, RECORDED = "503368238d55d847", 1.0745
ROOT, INTERVAL, START, END = ".starquant/data", "1h", "2021-01-01", "2026-09-04"

candidate = next(c for c in enumerate_candidates().candidates if c.hash == WANTED)
spec = register_signal(to_signal(candidate))
profile = load_yaml("config/live.demo.yaml")
costs = load_yaml("config/costs.yaml")
history = int((profile.get("portfolio", {}) or {}).get("min_history_bars", 720))
base = portfolio_params(profile)
chosen = _resolve_symbols(ROOT, "", INTERVAL, "pit")
membership_cache: dict[bool, object] = {}

print(f"candidate {candidate.expr}   recorded 1.0745   base vol_target={base.vol_target}")
print(f"{'vol_target':>10} {'funding':>8} {'sharpe':>9} {'delta':>9}")
for use_funding in (False, True):
    panel = _load(ROOT, chosen, INTERVAL, START, END, use_funding)
    membership = _membership(ROOT, "pit", panel, 0)
    cost = cost_model(costs, use_funding=use_funding)
    for vol_target in (0.15, 0.30):
        model = AlphaModel(
            entries=(StrategyEntry(id=spec.id, params=dict(spec.default_params)),),
            portfolio=replace(base, vol_target=vol_target),
            interval=INTERVAL,
            min_history_bars=history,
        )
        weights, _c, _p = model.evaluate(panel, membership)
        s = sharpe(run_backtest(panel, weights, cost).portfolio_net, panel.bars_per_year)
        print(f"{vol_target:>10.2f} {use_funding!s:>8} {s:>9.4f} {s - RECORDED:>+9.4f}")
