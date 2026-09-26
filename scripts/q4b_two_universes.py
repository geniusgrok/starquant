"""Q4c: how much selection freedom does the SECOND universe add?

Pre-registered in docs/RESEARCH_LOG.md before this ran (2026-09-14, "Q4c 预登记").

After the Q2 rollback the `mined` bucket is 2,073 rows over 676 distinct expressions, spread across
four contexts - and two of the three axes are confounded.  `construction` moves only when `symbols`
does (f47ecb32 always with 205, 79707046 always with 17/18), and `range_end` spans 2-3 days out of
five years and eight months.  So the caliber question reduces to one thing: scoring the same
expression on the 205-symbol pit pool and again on the 17-symbol pinned universe - how much is the
second look worth?

"One selection" has an operational meaning here: **how far it moves the distribution of the family's
maximum.**  That is exactly what the Q4b harness measures, so this scores the same 676 expressions on
both universes, joins them into 1,352 streams on a shared index, and asks for the joint `N_exact` -
the n at which the gate's empirical FWER is alpha.  Against the single-universe `N_exact`, the ratio
is the answer.

Li & Ji is not used.  Q4b measured it as too permissive by 1.75x on this ledger, so every count here
is the empirical `N_exact`.

**No ledger row.**  This never opens `trials.jsonl`; it scores and counts, it does not select.

Usage:

    .venv/bin/python scripts/q4b_two_universes.py [--out reports/research]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from q4b_liji_fwer import ALPHA, DRAWS, SEED, _fwer, _n_for_rate, _sample_max

from starquant_alpha.backtest import run_backtest
from starquant_alpha.mining import enumerate_candidates, to_signal
from starquant_alpha.model import AlphaModel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals import register as register_signal
from starquant_cli.research_cmd import _load, _membership, _resolve_symbols
from starquant_live.composition import cost_model, portfolio_params
from starquant_shared.config import load_yaml

UNIVERSES = ("pit", "static")


def _score(universe: str, root: str, interval: str, start: str, profile: str, costs: str) -> pd.DataFrame:
    """Every candidate's net stream on one universe, as a frame the join can align."""
    symbols = _resolve_symbols(root, "", interval, universe)
    panel = _load(root, symbols, interval, start, None, True, metrics=True, spot=True)
    membership = _membership(root, universe, panel, 0)
    payload = load_yaml(profile)
    portfolio = portfolio_params(payload)
    history = int((payload.get("portfolio", {}) or {}).get("min_history_bars", 720))
    cost = cost_model(load_yaml(costs), use_funding=True)

    search = enumerate_candidates(
        max_complexity=10,
        max_lookback=1400,
        include_funding=panel.settled_symbols > 0,
        include_basis=panel.spot_symbols > 0,
    )
    print(f"[{universe}] {len(symbols)} symbols x {len(panel.index)} bars, {search.evaluated} expressions", flush=True)

    streams: dict[str, pd.Series] = {}
    for candidate in search.candidates:
        spec = register_signal(to_signal(candidate))
        entry = StrategyEntry(id=spec.id, params=dict(spec.default_params))
        model = AlphaModel(entries=(entry,), portfolio=portfolio, interval=interval, min_history_bars=history)
        try:
            weights, _combined, _per = model.evaluate(panel, membership)
            streams[candidate.hash] = run_backtest(panel, weights, cost, execution="open_to_close").portfolio_net
        except Exception as exc:  # a candidate that cannot be scored here contributes no column
            print(f"[{universe}] {candidate.hash} unscoreable: {type(exc).__name__}: {exc}", flush=True)
    print(f"[{universe}] scored {len(streams)}", flush=True)
    return pd.DataFrame(streams)


def _n_exact(frame: pd.DataFrame, label: str) -> tuple[int, float, int]:
    """(N_exact, control FWER at the raw column count, columns) for one joined frame."""
    values = frame.to_numpy(dtype=float)
    live = values.std(axis=0, ddof=1) > 0
    correlation = np.corrcoef(values[:, live], rowvar=False)
    maxima, clipped = _sample_max(np.atleast_2d(correlation), DRAWS, SEED)
    columns = int(values.shape[1])
    control = _fwer(maxima, columns)
    exact = _n_for_rate(maxima)
    print(
        f"{label:<28} columns {columns:<6} live {int(live.sum()):<6} clip {clipped:.2e}  "
        f"control FWER(n={columns}) {control:.4f}  N_exact {exact}",
        flush=True,
    )
    return exact, control, columns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".starquant/data")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--from", dest="start", default="2021-01-01")
    parser.add_argument("--profile", default="config/live.demo.yaml")
    parser.add_argument("--costs", default="config/costs.yaml")
    parser.add_argument("--out", default="reports/research")
    args = parser.parse_args()

    frames = {u: _score(u, args.root, args.interval, args.start, args.profile, args.costs) for u in UNIVERSES}
    shared = frames[UNIVERSES[0]].index
    for universe in UNIVERSES[1:]:
        shared = shared.intersection(frames[universe].index)
    print(f"shared index: {len(shared)} bars", flush=True)

    singles = {}
    for universe, frame in frames.items():
        singles[universe] = _n_exact(frame.reindex(shared).fillna(0.0), f"single [{universe}]")

    joined = pd.concat(
        [frames[u].reindex(shared).fillna(0.0).add_prefix(f"{u}:") for u in UNIVERSES],
        axis=1,
    )
    joint_exact, joint_control, joint_columns = _n_exact(joined, "joint [both universes]")

    baseline = max(singles[u][0] for u in UNIVERSES)
    ratio = joint_exact / baseline if baseline else float("nan")
    verdict = (
        "③ per expression (bucket 683)"
        if ratio <= 1.25
        else (
            "② per expression x universe (bucket 1342)"
            if ratio >= 1.75
            else "neither prior - operator rules on the number"
        )
    )
    if joint_exact < baseline:
        verdict = "INVALID - adding columns cannot lower the maximum; the sampler is wrong"

    payload = {
        "kind": "q4c-two-universes",
        "generated_at": datetime.now(UTC).isoformat(),
        "alpha": ALPHA,
        "draws": DRAWS,
        "seed": SEED,
        "singles": {
            u: {"n_exact": singles[u][0], "control_fwer": singles[u][1], "columns": singles[u][2]} for u in UNIVERSES
        },
        "joint": {"n_exact": joint_exact, "control_fwer": joint_control, "columns": joint_columns},
        "shared_bars": len(shared),
        "ratio": ratio,
        "verdict": verdict,
        "note": "No ledger row was written; this scores and counts, it does not select.  Li & Ji is not used (Q4b).",
    }
    path = Path(args.out) / f"q4c-two-universes-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nratio {ratio:.4f}  ({joint_exact} / {baseline})\nVERDICT: {verdict}\n{path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
