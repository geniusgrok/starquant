"""P12 stage 1: collect the baseline and screened backtests into one comparison record.

PROVENANCE, added 2026-09-16.  A repository review first proposed DELETING this file - it is cited by
nothing and its inputs are hard-coded to `/private/tmp/p12`, a session temp directory that has not
existed since the day it ran, so it cannot be re-run.  That was wrong, and the reason is worth keeping
because it generalises: **this file is the only record of how a committed report was produced.**
`reports/research/p12-stage1-20260904T073645Z.json` is cited from `docs/RESEARCH_LOG.md`, and it is
this script's output - `FIELDS` below is exactly that report's `runs.*` key set, and `LABELS` is
exactly its `baseline / m=2 / m=4 / m=8`.  Deleting the script would have left a cited number in the
repository with nothing in the repository saying how it was computed.

The hard-coded temp paths are therefore NOT a defect to fix; they are a fact about a run that already
happened, and editing them would make this file describe a run nobody did.  What is true and worth
stating plainly: this comparison is **not reproducible from the repository** - re-running P12 stage 1
means re-running `p12_stage1_membership.py` to rebuild the screened roots first.  P12 was measured
INERT at stage 1 and was never adopted, so nothing downstream depends on reproducing it.

The general rule this is an instance of: "nothing references it by name" is not the same as "nothing
depends on it".  A script can be the sole provenance of an artefact that IS referenced, and grep does
not see that edge.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPORTS = sorted(glob.glob("/private/tmp/p12/reports/tsmom-backtest-*.json"), key=os.path.getmtime)
LABELS = ["baseline", "m=2", "m=4", "m=8"]
BASE = Path("/private/tmp/p12")
OUT = Path("reports/research")


FIELDS = (
    "annualized_sharpe",
    "annualized_sharpe_gross",
    "net_return",
    "gross_return",
    "max_drawdown",
    "turnover_units",
    "cost_share_of_gross",
    "hit_rate",
)


def summarise(path: str) -> dict[str, float]:
    summary = json.loads(Path(path).read_text(encoding="utf-8"))["summary"]
    return {key: summary[key] for key in FIELDS if key in summary}


def membership_delta(name: str) -> dict[str, int]:
    base = pd.read_parquet(BASE / "base" / "membership.parquet").astype(bool)
    other = pd.read_parquet(BASE / name / "membership.parquet").astype(bool)
    aligned = other.reindex(index=base.index, columns=base.columns).fillna(False)
    return {
        "member_cells": int(base.to_numpy().sum()),
        "differing_cells": int((aligned != base).to_numpy().sum()),
        "removed": int((base & ~aligned).to_numpy().sum()),
        "added": int((~base & aligned).to_numpy().sum()),
        "refreshes_touched": int((aligned != base).any(axis=1).sum()),
    }


runs = {label: summarise(path) for label, path in zip(LABELS, REPORTS, strict=True)}
deltas = {label: membership_delta(label.replace("=", "").replace("m", "m")) for label in LABELS[1:]}
baseline = runs["baseline"]
report = {
    "kind": "p12-stage1-liquidity-screen",
    "generated_at": datetime.now(UTC).isoformat(),
    "universe_mode": "pit",
    "rule_as_pre_registered": "exclude a candidate whose 30d Amihud ILLIQ > m x the MEDIAN OF THE CANDIDATE SET",
    "runs": runs,
    "membership_delta_vs_baseline": deltas,
    "delta_sharpe": {
        label: round(runs[label]["annualized_sharpe"] - baseline["annualized_sharpe"], 4) for label in LABELS[1:]
    },
    "delta_net": {label: round(runs[label]["net_return"] - baseline["net_return"], 4) for label in LABELS[1:]},
    "verdict": "INERT - the pre-registered screen does not bind; no ledger trial spent",
    "why": (
        "The candidate pool is ~700 mostly tiny perpetuals, so its median ILLIQ sits about 81x above the median "
        "of the selected members.  Being top-15 by quote volume already places every member far below the "
        "candidate median - the worst member measures 0.18x it - so a 2x-of-candidate-median threshold can "
        "never reach them.  The volume ranking is itself an implicit liquidity screen relative to the pool "
        "it selects from, which is the pre-registration's original prior, now with a mechanism."
    ),
    "stage0_correction": (
        "scripts/p12_stage0.py normalised by the median of the SELECTED MEMBERS, not of the candidate set, so its "
        "20.16%/7.55%/3.39% describe a different and much tighter screen than the one pre-registered.  Its "
        "PROCEED verdict does not apply to the pre-registered rule.  The member-relative screen has never been "
        "pre-registered and would need its own registration to be run."
    ),
    "no_ledger_entries": "research backtest does not write trials.jsonl; validate was never run, so 0 trials spent",
}
OUT.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
path = OUT / f"p12-stage1-{stamp}.json"
path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2, sort_keys=True))
print(f"\nwritten {path}")
