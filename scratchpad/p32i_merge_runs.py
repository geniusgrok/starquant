"""Merge `p32i` runs into one table per (band, store, factor, universe), and run `p32h.crossing` on the merged rows.

The 2026-09-25 sweep was split into runs - by `k` for the 0.15 extension point, by arm for the proportional
sensitivity - so no cell already measured was re-bought.  Split runs are one computation: every `k` draws
its own block starts from `SEED` and `n`, and every arm is a pure function of (series, starts).  What could
differ between two runs is the panel build, so the merge refuses unless the settings agree and every `k`
two runs share carries the same drift reading (c, full-sample Sharpe, Sharpe after, block-start hash where
recorded) to the last bit, and every row two runs share is identical.

Read-only: the JSONs `p32i_k_sweep_at_honest_drift.py` wrote, archived at `reports/research/p32i-20260925/`.

    python scratchpad/p32i_merge_runs.py [--dir reports/research/p32i-20260925]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p32h_k_sweep_at_the_base_in_force as p32h

SETTINGS = ("mode", "band", "store", "draws", "seed", "block", "bars", "honest_sharpe_target", "end_exclusive")
READING = ("c_per_bar", "full_sample_sharpe", "sharpe_after")
DRIFTS = ("orig", "honest", "prop")


def cell(row: dict[str, Any]) -> str:
    return f"{row['q95_usdt']:.1%} / {row['p_past_70_usdt']:.1%} / {row['cagr_median']:.1%}"


def merge(paths: list[Path]) -> tuple[dict[str, Any], dict[tuple[float, str, str], dict[str, Any]], dict[str, dict]]:
    rows: dict[tuple[float, str, str], dict[str, Any]] = {}
    drift: dict[str, dict] = {}
    first: dict[str, Any] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        first = first or payload
        for key in SETTINGS:
            if payload[key] != first[key]:
                raise SystemExit(f"{path.name}: {key} {payload[key]!r} != {first[key]!r}")
        for k, reading in payload["drift"].items():
            if k in drift:
                for field in READING:
                    if reading[field] != drift[k][field]:
                        raise SystemExit(f"{path.name}: k={k} {field} {reading[field]!r} != {drift[k][field]!r}")
                ours, theirs = reading.get("starts_sha256_16"), drift[k].get("starts_sha256_16")
                if ours and theirs and ours != theirs:
                    raise SystemExit(f"{path.name}: k={k} block starts differ")
                drift[k].update({f: v for f, v in reading.items() if f not in drift[k]})
            else:
                drift[k] = dict(reading)
        for row in payload["rows"]:
            key = (round(row["k"], 4), row["arm"], row["drift"])
            if key in rows and rows[key] != row:
                raise SystemExit(f"{path.name}: row {key} differs between runs")
            rows[key] = row
    return first, rows, drift


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="reports/research/p32i-20260925")
    folder = Path(parser.parse_args().dir)
    groups: dict[tuple, list[Path]] = {}
    for path in sorted(folder.glob("p32i-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = (payload["band"], payload["store"], payload["usdt_factor"], payload["usdt_factor_date"], payload["mode"])
        groups.setdefault(key, []).append(path)
    for (band, store, factor, factor_date, mode), paths in groups.items():
        first, rows, drift = merge(paths)
        drifts = [d for d in DRIFTS if any(key[2] == d for key in rows)]
        print(f"\n## {mode} {band}, store {store}, factor {factor:.4f} ({factor_date}), draws {first['draws']}, {len(paths)} runs")
        print("| k | " + " | ".join(drifts) + " |")
        for k in sorted({key[0] for key in rows}, reverse=True):
            for arm in ("running", "ladder@k"):
                got = [rows.get((k, arm, d)) for d in drifts]
                if any(got):
                    name = f"{k:.2f}" + (" running" if arm == "running" else "")
                    print(f"| {name} | " + " | ".join(cell(r) if r else "-" for r in got) + " |")
        for d in drifts:
            family = [row for (_, arm, dd), row in rows.items() if arm == "ladder@k" and dd == d]
            cross = p32h.crossing(family, -0.70)
            holds = [row["k"] for row in sorted(family, key=lambda row: -row["k"]) if row["holds_the_usdt_budget"]]
            where = "not within the grid" if cross is None else f"k {cross[0]:.4f}, CAGR {cross[1]:.1%}"
            print(f"  crossing {d}: {where}; first grid k that holds: {holds[0] if holds else '-'}")
        print("  full-sample Sharpe by k: " + "; ".join(f"{k} {v['full_sample_sharpe']:.4f}" for k, v in sorted(drift.items(), reverse=True)))


if __name__ == "__main__":
    main()
