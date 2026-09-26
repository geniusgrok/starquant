"""M-015: re-derive RISK_COMPRESSION_LIMIT with the flow probe in the book.  Written before it ran.

WHY THIS IS BEING RE-DERIVED
The limit's own comment says what it is: "a wide bound placed between those two, not a derived
threshold", the two being 0.13 ("measured on the live book 2026-09-05") and 1.0 ("delete stage 1").
The 0.13 anchor was measured on a book where the probe reached the extremes of nothing: on 2026-09-05
`flow` carried a contribution on ONE of sixteen names and the risk spread was 1.0x.  It now carries
four of eighteen and the spread is 9.4x.  So the lower anchor describes a book that no longer exists,
and 0.50 inherited from it is crossed by behaviour the operator registered on purpose (D-019).
This is the same shape as the suite-duration ceiling that was "calibrated on a guess": re-derive
against measurement, and raise the number only in the commit that says why.

THE ARITHMETIC THAT MAKES THIS MEASURABLE (not an assumption - it is `build_weights`)
    stage 1   w1_i = c_i * vol_target / sigma_i        <- the only place sigma enters per symbol
    stage 2   scalar, identical across symbols          <- cancels from every ratio below
    combine   w_i  = (vol_target / sigma_i) * (c_tsmom_i * a + c_flow_i * b)
So with stage 1 WORKING, risk_i = |w_i| * sigma_i = vol_target * |c_i|: sigma cancels exactly, and
the residual spread is the spread of the COMBINED CONVICTION, not of the market.  That is why the
fourteen names the probe does not touch all read exactly 2.42% and only the four it does deviate.

    c_working  = [max(|w|sigma) / min(|w|sigma)] / vol_spread        (what the report computes)
    c_deleted  = [max(|w|sigma^2) / min(|w|sigma^2)] / vol_spread    (same book, stage 1 removed)

`c_deleted` follows from the same identity: delete stage 1 and w_i is proportional to c_i itself, so
risk_i is proportional to |w_i| * sigma_i^2 on the record we already have.  No re-simulation, no
model.  Stated limit: it inherits the caps and the no-trade band from the recorded weights, and
deleting stage 1 for real would change WHICH names hit `max_weight` - so `c_deleted` is the
counterfactual on this weight path, not on the path a stage-1-less loop would have walked.

PRE-REGISTERED RULE - fixed here before any number was computed
R1  Population: every cycle in .starquant/live/cycles.jsonl carrying both `asset_vol` and `targets`.
    Reported over two windows: ALL cycles, and cycles at or after 2026-09-06T10:19Z (the D-042
    restart - the lineage the loop is actually on, and the first cycle whose registry is recorded).
R2  Per cycle, over names with |w| > 0 and sigma > 0, requiring >= 3 held names (the same refusal
    the shipped code makes).  Compute c_working and c_deleted.
R3  SEPARABILITY GATE, decided before looking:  min(c_deleted) / max(c_working) >= 1.5.
    If it fails, the verdict is REFUTED - the instrument cannot tell "stage 1 deleted" from "the two
    books disagree", no number is proposed, and the recommendation reverts to measuring the main
    book separately.  A threshold that cannot separate the two states is not a threshold.
R4  If R3 passes, new limit = geometric mean of max(c_working) and min(c_deleted), 2 decimal places.
    Geometric because the instrument is a ratio of ratios.
R5  Report the margin on both sides of the chosen limit, and the observed max under the OLD limit,
    so the size of what is being given up is visible rather than implied.

Run:  python scratchpad/m015_recalibrate_with_probe.py [path/to/cycles.jsonl]
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

CUTOVER = "2026-09-06T10:19"  # D-042 restart; the construction lineage the loop is on
SEPARABILITY_MIN = 1.5  # R3, fixed before running
OLD_LIMIT = 0.50


def spreads(cycle: dict[str, Any]) -> tuple[float, float, float] | None:
    """``(vol_spread, c_working, c_deleted)`` for one cycle, or ``None`` when it refuses."""
    vols = cycle.get("asset_vol") or {}
    targets = cycle.get("targets") or {}
    held = {
        symbol: (abs(float(weight)), float(vols[symbol]))
        for symbol, weight in targets.items()
        if symbol in vols and float(vols[symbol]) > 0 and abs(float(weight)) > 0
    }
    if len(held) < 3:
        return None
    sigmas = [sigma for _, sigma in held.values()]
    vol_spread = max(sigmas) / min(sigmas)
    working = [w * sigma for w, sigma in held.values()]
    deleted = [w * sigma * sigma for w, sigma in held.values()]
    return (
        vol_spread,
        (max(working) / min(working)) / vol_spread,
        (max(deleted) / min(deleted)) / vol_spread,
    )


def report(label: str, rows: list[tuple[str, float, float, float]]) -> tuple[float, float] | None:
    if not rows:
        print(f"\n{label}: no cycles")
        return None
    working = [row[2] for row in rows]
    deleted = [row[3] for row in rows]
    print(f"\n{label}  ({len(rows)} cycles, {rows[0][0]} -> {rows[-1][0]})")
    print(f"  vol_spread   min {min(r[1] for r in rows):6.2f}  max {max(r[1] for r in rows):6.2f}")
    print(
        f"  c_working    min {min(working):6.3f}  median {statistics.median(working):6.3f}  "
        f"max {max(working):6.3f}   (cycles over the old {OLD_LIMIT:.2f}: "
        f"{sum(1 for c in working if c > OLD_LIMIT)})"
    )
    print(f"  c_deleted    min {min(deleted):6.3f}  median {statistics.median(deleted):6.3f}  max {max(deleted):6.3f}")
    return max(working), min(deleted)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / ".starquant" / "live" / "cycles.jsonl"
    rows: list[tuple[str, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cycle = json.loads(line)
        measured = spreads(cycle)
        if measured is not None:
            rows.append((str(cycle.get("at")), *measured))

    print(f"source: {path}")
    print(f"pre-registered separability gate: min(c_deleted) / max(c_working) >= {SEPARABILITY_MIN}")
    all_window = report("ALL cycles", rows)
    current = report(f"SINCE {CUTOVER}Z (D-042 lineage)", [row for row in rows if row[0] >= CUTOVER])

    for label, measured in (("ALL cycles", all_window), (f"since {CUTOVER}Z", current)):
        if measured is None:
            continue
        worst_working, best_deleted = measured
        ratio = best_deleted / worst_working
        verdict = "SEPARABLE" if ratio >= SEPARABILITY_MIN else "REFUTED"
        print(f"\n--- {label}: {verdict} ---")
        print(
            f"  max(c_working) {worst_working:.3f}   min(c_deleted) {best_deleted:.3f}   "
            f"ratio {ratio:.2f} vs the {SEPARABILITY_MIN} gate"
        )
        if verdict == "REFUTED":
            print("  R3 says: propose no number.  The instrument cannot separate the two states here.")
            continue
        limit = round(math.sqrt(worst_working * best_deleted), 2)
        print(f"  R4 limit = geometric mean = {limit:.2f}")
        print(f"  R5 margin: {limit / worst_working:.2f}x above the worst working cycle, {best_deleted / limit:.2f}x below the best deleted one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
