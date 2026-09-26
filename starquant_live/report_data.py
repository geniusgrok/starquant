"""Whether the data under the book is the data its evidence was measured on.

Checklist area #9 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`: the research
archive's coverage of what the loop traded, metrics same-source parity (DL-D4 / M-011) and dataset
provenance (D-041).  Bar sanity (G6) lives in `bar_sanity.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from starquant_data.metrics_snapshot import metrics_parity
from starquant_data.store import KlineStore, MetricsStore
from starquant_live.report_common import readable_state
from starquant_live.state import StateStore


def metrics_parity_status(symbols: Sequence[str], data_root: str | Path) -> dict[str, Any]:
    """M-011 across the managed universe: archive against snapshot, per symbol, folded to one number.

    Two refusals rather than one convenient number.  A symbol with no overlap contributes nothing and
    is counted separately - `metrics_parity` already returns `rate: None` for that case, because zero
    disagreements out of zero comparisons is not agreement, and a dead snapshot stream would otherwise
    look healthiest exactly while it stopped recording.  And the fold takes the WORST symbol, not the
    mean: a book trades a universe, so parity the thinnest symbol does not have is not parity.
    """
    archive, snapshot = MetricsStore(data_root), MetricsStore(data_root, kind="metrics_snapshot")
    compared: dict[str, float] = {}
    unmeasurable: list[str] = []
    for symbol in symbols:
        result = metrics_parity(snapshot.load(symbol), archive.load(symbol))
        if result["rate"] is None:
            unmeasurable.append(symbol)
        else:
            compared[symbol] = float(result["rate"])
    if not compared:
        return {
            "enforced": False,
            "reason": f"no overlapping buckets for any of {len(symbols)} symbols",
            "unmeasurable": unmeasurable,
        }
    worst = max(compared, key=lambda symbol: compared[symbol])
    return {
        "enforced": True,
        "symbols_compared": len(compared),
        "unmeasurable": unmeasurable,
        "worst_symbol": worst,
        "worst_differing_rate": compared[worst],
        "met": not unmeasurable and compared[worst] == 0.0,
    }


def data_coverage(store: StateStore, root: str | Path = ".starquant/data", interval: str = "1h") -> dict[str, Any]:
    """Live symbols whose research klines are missing, so a backtest would silently drop them.

    ``load_panel`` excludes a symbol with no stored klines and logs a warning nobody reads; CYSUSDT was
    traded live for sixteen hours while every research run quietly ran without it.
    """
    state, unreadable = readable_state(store)
    if unreadable:
        return {"live_symbols": None, "missing_klines": None, "reason": unreadable}
    symbols = list(dict.fromkeys([*state.universe, *state.leaving]))
    try:
        stored = set(KlineStore(str(root)).symbols(interval))
    except Exception:  # a missing store is a research problem, never a reporting failure
        return {"live_symbols": len(symbols), "missing_klines": None}
    missing = [symbol for symbol in symbols if symbol not in stored]
    return {"live_symbols": len(symbols), "missing_klines": missing, "missing_count": len(missing)}


def _dataset_block(dataset: Mapping[str, Any] | None) -> dict[str, Any]:
    """D-041: what the cited evidence's dataset manifest says about the data on disk.

    Empty lists rather than ``None`` when nothing was passed, so a reader never has to distinguish
    "not checked" from "checked and clean" by the shape of the value - the same mistake the manifest
    itself made about funding.
    """
    block = dict(dataset or {})
    return {"blocking": list(block.get("blocking", [])), "advisory": list(block.get("advisory", []))}
