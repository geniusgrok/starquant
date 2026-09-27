"""What a row of `cycles.jsonl` contains, declared in one place.

The cycle record is the widest interface in this package and it had no declaration anywhere.  About
forty-two keys, written by three methods of `LiveEngine` - the literal in `run_cycle`, four more added
after execution, five more in `_finish_cycle`, two conditional - and read by six modules
(`reports`, `risk_budget`, `verify`, `health`, `probe`, `soak`) under 192 distinct `.get("…")` names.

**This is deliberately not a typed row, and that is not laziness.**  `cycles.jsonl` is an append-only
ledger years deep: a field's absence in an old row means "written before this field existed", and every
reader's `.get()` plus `isinstance` check is the correct handling for that.  A dataclass with required
fields would refuse to read the history the file exists to keep.

What was missing is not types.  It is a place where the writer and the reader can be compared, because
the failures this record produces are always the same shape - one writer and one reader disagreeing
about a key - and there was nowhere for that disagreement to show up:

* `startup` filtered the universe and did not write it back, so `verify` ranked over a different
  population than the cycle scored.
* the ERROR path wrote none of L3's five decision keys, so `soak`'s gate could not fail.
* `_decided` tested `risk_ladder` for emptiness while `_risk_ladder` never returns `{}`.

All three are one key, one writer, one reader.  `KEYS` below is the declaration, and
`tests/live/test_the_cycle_record_is_declared.py` compares it against what the engine actually writes,
in both directions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Every key a cycle row may carry, with a one-line note on what it is for.  Grouped by the phase that
#: writes it, because "which writer owns this key" is the question a reader most often needs answered.
KEYS: dict[str, str] = {
    # --- identity and timing -------------------------------------------------------------------
    "at": "when the row was appended (added by `StateStore._append`, not by the engine)",
    "bar_open_ms": "the closed bar this cycle decided on",
    "bar": "the same instant as an ISO string, for reading",
    "as_of_ms": "the newest closed bar the feed actually supplied",
    "phase": "OK / SKIPPED / ERROR - written by `_finish_cycle` or by `guarded_cycle`",
    "window_seconds": "how long after the bar close the rebalance window stays open",
    "clock": "D-025: skew / alignment / whole_bars / jumped against the feed's own clock",
    # --- account state -------------------------------------------------------------------------
    "equity": "venue equity at the snapshot",
    "collateral": "L1-10: how much of that equity is collateral rather than USDT",
    "unrealized": "open P&L of the managed positions, for R8's ruler",
    "gross_before": "sum of |notional| already held",
    "margin_usage": "M-007: initial margin the standing book consumes",
    "margin_fields_reliable": "whether the account payload carried usable margin fields",
    "margin": "how risk-adding orders were scaled to available margin",
    "min_liq_distance": "M-Q06: nearest reachable liquidation, in daily-vol units",
    # --- the book ------------------------------------------------------------------------------
    "targets": "target weights per symbol",
    "contributions": "per strategy, the share of each target it accounts for",
    "books": "which book each strategy belongs to",
    "book_weights": "per-book weights, for the probe stop's mark-to-market caliber",
    "closes": "the closes the decision was taken on",
    "asset_vol": "M-015: the stage-1 sizing divisor per symbol",
    "book_vol": "what the book asks for, what it leaves the model at, and what max_weight clipped off",
    "crowding": "M-018: what the crowding modifier DID this bar, not merely that its input arrived",
    "metrics_snapshot": "DL-Q6: what this loop could read at the instant it decided",
    "throttle": "D-015's drawdown throttle: scalar / drawdown / equity_hwm",
    "risk_ladder": "R8's block; `acting` is the only field that means the ladder DECIDED",
    "exit_events": "D-012: what the exit overlay did this bar",
    "probes": "D-019: each probe book's stop evaluation",
    # --- the pool ------------------------------------------------------------------------------
    "universe": "the managed set this cycle scored (post-filter)",
    "leaving": "symbols out of the pool but still held",
    "quarantined": "D-031: symbols removed for consecutive venue rejections",
    "universe_update": "D-014: the daily refresh, adopted or merely recorded",
    "inputs": "what the feed supplied, including `dropped`",
    "dropped_inputs": "what the loop DID about `inputs.dropped`",
    "bar_sanity": "G6: OHLC contradictions, frozen runs and jumps in those bars - alert only, never traded on",
    # --- execution -----------------------------------------------------------------------------
    "orders": "the orders this cycle placed",
    "skipped": "orders planned and not sent, with the reason",
    "summary": "per-symbol outcome of the execution pass",
    "guard_reasons": "which guards fired",
    "skip": "whether the guards stopped the cycle before planning",
    "dry_run": "whether the venue was written to at all",
    "external_flows": "D-021: TRANSFER rows that reset the day and the high-water mark",
    # --- identity of the configuration ---------------------------------------------------------
    "construction": "D-026: digest of the construction this cycle ran",
    "construction_full": "the full fingerprint, written once per process on the first cycle",
    "evidence_construction": "DL-G9: the same construction restricted to what a report can describe",
    "governance": "R9: the policy digest, so a threshold change cannot be silent",
    "registry": "DL-Q0: the registry digest the PROCESS holds, which the file may have moved past",
    # --- the ERROR path ------------------------------------------------------------------------
    "error": "the exception that ended the cycle",
    "consecutive_errors": "how many cycles have failed in a row",
}


def latest(rows: Sequence[Mapping[str, Any]], field: str) -> Any:
    """The newest row's value for `field`, skipping rows written before the field existed.

    Deliberately narrow.  The review this module came out of counted seven "scan backwards until
    something carries X" loops and called them near-identical; reading them, they are not.
    `verify.last_cycle`, `last_scored_cycle` and `last_recorded_as_of_ms` each carry a DIFFERENT
    predicate, and `last_scored_cycle` spends a paragraph on why it cannot be `last_cycle` - a restart
    writes a SKIPPED row with no contributions, and reading the lag off that one measures a different
    event.  Collapsing those into a general helper would delete the explanation, which is the opposite
    of concentrating anything.  `reports.evidence_window`'s loop is not a lookup at all: it walks back
    while the construction still matches, to find where the current run began.

    What IS duplicated is this one question, asked in two modules: the newest row that carries a field.
    Two callers, so the seam is real; a third predicate belongs in its own named function with its own
    reason, the way `verify`'s three are.
    """
    for row in reversed(rows):
        if field in row and row[field] is not None:
            return row[field]
    return None


def undeclared(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Keys in `row` that `KEYS` does not describe.  The join, as a function so tests and tools share it."""
    return tuple(sorted(key for key in row if key not in KEYS))
