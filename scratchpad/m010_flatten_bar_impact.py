"""What the 2026-09-13 21:00Z flatten bar does to M-010, measured with M-010's own function.

Produces the comparison table the RESEARCH_LOG entry for that exclusion cites (`fe4c3446`): tsmom
-7.5220 -> -4.9744 and flow +2.8431 -> +0.5321 once the one row is hidden.  Committed because the
entry is an instruction to READERS of M-010 - "exclude this bar" - and an instruction whose arithmetic
cannot be re-run is an assertion.  `scratchpad/stop_tail.py` is the precedent: it was cited, never
committed, and the pit half of its finding is now structurally irreproducible.

The exclusion is a READ-side filter.  `attribution.jsonl` is append-only and shared with the running
loop; this subclasses the store to hide one row in memory and touches nothing on disk.  Point it at a
different bar (or a different store) to price any other manual intervention the same way.

    python scratchpad/m010_flatten_bar_impact.py [bar_open_ms]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from starquant_live.reports import income_drift
from starquant_live.state import StateStore

LIVE = Path(".starquant/live")
# 2026-09-13T20:00:00Z, the bar whose income window (20:00:09 -> 21:00:09Z) caught `live flatten`.
FLATTEN_BAR = 1_789_326_000_000


class WithoutOneBar(StateStore):
    """The same store with one attribution row hidden.  Nothing is written."""

    def __init__(self, directory: Path, bar_open_ms: int) -> None:
        super().__init__(directory)
        self._hidden = bar_open_ms

    def read_jsonl(self, path):  # type: ignore[no-untyped-def]
        rows = list(super().read_jsonl(path))
        if path == self.attribution_path:
            rows = [row for row in rows if row.get("bar_open_ms") != self._hidden]
        return rows


def _latest_equity(store: StateStore) -> float | None:
    equity = None
    for row in store.read_jsonl(store.cycles_path):
        if isinstance(row.get("equity"), int | float):
            equity = float(row["equity"])
    return equity


def main(bar_open_ms: int) -> None:
    base = StateStore(LIVE)
    equity = _latest_equity(base)
    out: dict[str, object] = {"bar_open_ms": bar_open_ms, "equity": equity}
    for label, store in (("with_bar", base), ("without_bar", WithoutOneBar(LIVE, bar_open_ms))):
        block = income_drift(store, {}, equity=equity, since_ms=None)
        out[label] = {
            strategy: {
                "bars": row["bars"],
                "realised_sharpe": round(float(row["realised_sharpe"]), 4),
                "pnl": round(float(row["pnl"]), 4),
            }
            for strategy, row in sorted((block.get("by_strategy") or {}).items())
        }
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else FLATTEN_BAR)
