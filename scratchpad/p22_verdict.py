"""P22 verdict: read the four overlay reports and print the pre-registered decision table.

Usage: python scratchpad/p22_verdict.py PIT_ENTRY.json PIT_CURRENT.json STATIC_ENTRY.json STATIC_CURRENT.json
Rules are the ones written in RESEARCH_LOG's P22 pre-registration; this script does not decide anything new.
"""

from __future__ import annotations

import json
import sys
from typing import Any

MAX_SHARPE_LOSS = 0.10
TP_MARGIN_VS_CURRENT = 0.02
MAX_EXIT_RATIO = 3.0


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def exits_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in report["candidates"]:
        if row["kind"] != "exits":
            continue
        p = row["params"]
        key = f"TP{p['take_profit']:g}-{p.get('unit_mode', 'entry')}"
        rows[key] = row
    return rows


def d017(row: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return row["oos_mdd"] > baseline["oos_mdd"] and row["oos_sharpe"] >= baseline["oos_sharpe"] - MAX_SHARPE_LOSS


def main(paths: list[str]) -> None:
    pit = {**exits_rows(load(paths[0])), **exits_rows(load(paths[1]))}
    static = {**exits_rows(load(paths[2])), **exits_rows(load(paths[3]))}
    base_pit, base_static = load(paths[0])["baseline"], load(paths[2])["baseline"]
    ref_pit, ref_static = pit["TP6-entry"], static["TP6-entry"]
    print(f"{'candidate':14s} {'pit OOS/MDD':>18s} {'static OOS/MDD':>18s} {'D-017':>6s} {'vs TP6':>8s} {'exits x':>8s}  verdict")
    for key in sorted(set(pit) & set(static)):
        a, b = pit[key], static[key]
        passes = d017(a, base_pit) and d017(b, base_static)
        exits_ratio = max(a["events"]["exits"] / max(ref_pit["events"]["exits"], 1), b["events"]["exits"] / max(ref_static["events"]["exits"], 1))
        if key.endswith("-current"):
            extra = a["oos_mdd"] >= ref_pit["oos_mdd"] and b["oos_mdd"] >= ref_static["oos_mdd"]
            rule = "MDD not worse than TP6-entry"
        else:
            extra = (a["oos_sharpe"] >= ref_pit["oos_sharpe"] - TP_MARGIN_VS_CURRENT
                     and b["oos_sharpe"] >= ref_static["oos_sharpe"] - TP_MARGIN_VS_CURRENT)
            rule = "Sharpe >= TP6-entry - 0.02"
        adopt = passes and extra and exits_ratio <= MAX_EXIT_RATIO
        print(
            f"{key:14s} {a['oos_sharpe']:7.4f}/{a['oos_mdd']:8.4f} {b['oos_sharpe']:7.4f}/{b['oos_mdd']:8.4f} "
            f"{'yes' if passes else 'no':>6s} {'ok' if extra else 'fail':>8s} {exits_ratio:8.2f}  "
            f"{'ADOPT-CANDIDATE' if adopt else 'REFUTED'}  ({rule})"
        )
    for name, report in (("pit", load(paths[0])), ("static", load(paths[2]))):
        thr = [r for r in report["candidates"] if r["kind"] == "throttle"]
        if thr:
            r = thr[0]
            print(f"throttle@0.30 {name}: {r['oos_sharpe']:.4f}/{r['oos_mdd']:.4f} vs baseline "
                  f"{report['baseline']['oos_sharpe']:.4f}/{report['baseline']['oos_mdd']:.4f} -> "
                  f"{'passes' if d017(r, report['baseline']) else 'fails'} D-017 (informational, stays off)")


if __name__ == "__main__":
    main(sys.argv[1:5])
