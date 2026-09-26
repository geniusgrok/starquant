"""R8 sizes off CURRENT equity but divides by a path anchored at the baseline.  Which way does that bias?

The ladder's reading is `marked / peak - 1`, where `peak` is the running max of `base + book P&L`.  The
positions whose loss lands in that numerator are sized as `weight x CURRENT equity`.  So the same
percentage move of the book produces a reading scaled by `equity / peak`:

    reading  =  (x% * gross)  / peak      and      gross = weight_sum * equity
    so        reading / (x% * weight_sum)  =  equity / peak

`equity / peak > 1` means the reading OVERSTATES the book's own percentage drawdown - the rung fires
EARLIER than the book's own move would suggest; `< 1` means later.  The gap moves whenever equity moves
for a reason the book did not earn, which on this account is mostly BTC collateral repricing (52.65%)
and external flows.

Uses `attributed_drawdown_state` itself on growing prefixes rather than reimplementing the path: a
second implementation of the quantity under test is how two rulers end up in one repository.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from starquant_live.risk_budget import RiskBudgetParams, attributed_drawdown_state
from starquant_live.state import StateStore

LIVE = Path("~/starquant/.starquant/live")


def main() -> None:
    store = StateStore(LIVE)
    cycles = list(store.read_jsonl(store.cycles_path))
    attribution = list(store.read_jsonl(store.attribution_path))
    priced = [i for i, row in enumerate(cycles) if isinstance(row.get("equity"), int | float) and row["equity"] > 0]

    rows = []
    for i in priced:
        block = attributed_drawdown_state(cycles[: i + 1], attribution, RiskBudgetParams())
        if not block.get("enforced"):
            continue
        peak = float(block["peak"])
        equity = float(cycles[i]["equity"])
        rows.append(
            {
                "at": str(cycles[i].get("at"))[:19],
                "equity": round(equity, 2),
                "peak": round(peak, 2),
                "ratio": round(equity / peak, 6) if peak > 0 else None,
                "reading": round(float(block["value"]), 6),
                "ruler": block["ruler"],
            }
        )

    ratios = [r["ratio"] for r in rows if r["ratio"] is not None]
    print(
        json.dumps(
            {
                "cycles_with_a_reading": len(rows),
                "baseline_at": attributed_drawdown_state(cycles, attribution, RiskBudgetParams())["baseline_at"],
                "equity_over_peak": {
                    "first": ratios[0],
                    "last": ratios[-1],
                    "min": round(min(ratios), 6),
                    "median": round(statistics.median(ratios), 6),
                    "max": round(max(ratios), 6),
                    "bars_above_1": sum(1 for x in ratios if x > 1.0),
                    "bars_below_1": sum(1 for x in ratios if x < 1.0),
                },
                "first_row": rows[0],
                "last_row": rows[-1],
            },
            indent=1,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
