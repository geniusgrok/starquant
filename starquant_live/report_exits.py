"""What the exit overlay did, what it could not have done, and what not doing it would have cost.

Checklist items #1.5 (exit rules) and #3.2 (stop-loss framework) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`: exit and pool events
(M-005 / M-006), thresholds no price path can reach, and the exit counterfactuals.  The overlay is
`starquant_alpha/overlays/exits.py`; the loop's half is `starquant_live/exits.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.overlays.exits import COOLDOWN, STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, ExitParams
from starquant_alpha.panel import interval_seconds
from starquant_live.report_common import _day_of, _store_closes, readable_state
from starquant_live.state import StateStore


def exit_and_pool_events(store: StateStore, day: str) -> dict[str, Any]:
    """M-005 and M-006: the two things that change the book without a signal changing its mind."""
    # a dry run submits no order (engine.py: DRY_RUN), so its exits and its pool moves never reached the
    # venue; left in, they pad the same M-005 exit list `exit_counterfactuals` excludes them from below
    rows = [row for row in store.read_jsonl(store.cycles_path) if _day_of(row) == day and not row.get("dry_run")]
    exits = [
        {"symbol": event.get("symbol"), "rule": event.get("rule"), "bar": row.get("bar")}
        for row in rows
        for event in (row.get("exit_events") or [])
    ]
    entered: list[str] = []
    left: list[str] = []
    quarantined: list[str] = []
    for row in rows:
        update = row.get("universe_update") or {}
        entered.extend(str(s) for s in (update.get("entered") or []))
        left.extend(str(s) for s in (update.get("left") or []))
        quarantined.extend(str(s) for s in (row.get("quarantined") or []))
    return {
        "exits": exits,
        "exit_count": len(exits),
        "by_rule": {rule: sum(1 for e in exits if e["rule"] == rule) for rule in {str(e["rule"]) for e in exits}},
        "pool_entered": entered,
        "pool_left": left,
        "pool_quarantined": quarantined,  # D-031: the falsifier is counted here, not asserted in a docstring
        "pool_changes": len(entered) + len(left),
    }


def exit_reachability(store: StateStore, params: ExitParams | None) -> dict[str, Any]:
    """Held positions carrying an exit threshold that no price path can reach.

    `ExitParams.min_unit`'s comment carries the derivation and the live table; the short form is that a
    long's price floor is zero, so `adverse <= 1/sigma` and a `stop_loss` at `k > 1/sigma` is arithmetic
    rather than protection.  The same bound lands on a short's `take_profit`, and on a long's trailing
    stop through `extreme`, which starts at the entry price and opens the ceiling up only as the
    position rallies.  A short's stop and a long's take-profit have unbounded numerators and are
    omitted rather than reported as safe, because "no ceiling" and "a ceiling nothing has crossed" are
    different facts and only the first is theirs.

    A reading, deliberately with no threshold and no alert.  A ceiling under the shipped `k` is not a
    fault: it is what inverse-vol sizing leaves behind on a symbol too loud to hold much of, and the
    position it describes is small for the same reason it is unreachable - one input, both effects.
    What it replaces is the way the first one was found, which was an operator reading a margin figure
    off a phone app.  Nothing here can be acted on inside the hour, so it must not page.
    """
    if params is None or not params.enabled:
        return {"checked": 0, "unreachable": [], "enabled": False}
    state, _ = readable_state(store)
    unreachable: list[dict[str, Any]] = []
    checked = 0
    for symbol, raw in sorted((state.exit_states or {}).items()):
        held = int(raw.get("direction") or 0)
        entry, unit = raw.get("entry_price"), raw.get("unit")
        if held == 0 or not entry or unit is None:
            continue
        sigma = max(float(unit), params.min_unit)  # `_unit_price`'s own floor, or the ceiling is a fiction
        ceiling = 1.0 / sigma
        limits: list[tuple[str, float, float]] = []
        # EXP-SL1: with a price cap on, the effective k is `min(stop_loss, c / sigma)`, and that second
        # term is below `1/sigma` for every `c < 1` - so the long stop this function exists to flag
        # stops being unreachable by construction and reporting it would be false.  The cap is read
        # rather than assumed: `c >= 1` puts the threshold back at or above the ceiling, which is
        # exactly the case still worth naming.
        k_stop = params.stop_loss
        if params.stop_loss_price_cap > 0:
            k_stop = min(k_stop, params.stop_loss_price_cap / sigma)
        if params.stop_loss > 0 and held > 0:
            limits.append((STOP_LOSS, k_stop, ceiling))
        if params.take_profit > 0 and held < 0:
            limits.append((TAKE_PROFIT, params.take_profit, ceiling))
        if params.trailing_stop > 0 and held > 0:
            top = float(raw.get("extreme") or entry)
            limits.append((TRAILING_STOP, params.trailing_stop, top / (sigma * float(entry))))
        for rule, k, cap in limits:
            checked += 1
            if k > cap:
                unreachable.append(
                    {"symbol": symbol, "rule": rule, "k": k, "ceiling": cap, "sigma": sigma, "direction": held}
                )
    return {"checked": checked, "unreachable": unreachable, "enabled": True}


COUNTERFACTUAL_N_FOR_DECISION = 16  # a half-sigma per-event effect at t = 2; about two months at the rate above


TURNOVER_BPS = 7.0


def exit_counterfactuals(
    store: StateStore,
    *,
    closes: Callable[[str], pd.Series] | None = None,
    root: str | Path = ".starquant/data",
    interval: str = "1h",
    horizons: Sequence[int] = (24, 72),
) -> dict[str, Any]:
    """M-005 as monitoring (K-EX12): for every exit the loop ever made, what the position would have earned had it stayed.

    Counterfactual P&L at horizon h = target x equity x (close_{t+h} / close_t - 1), with close_t the price the
    event recorded and close_{t+h} the mainnet close h bars later; the cost the exit paid is 2 x 7 bps x
    |target| x equity (out and back in).  Events younger than the longest horizon are ``pending``.  About 16
    priced events are needed before the mean says anything (a half-sigma effect at t = 2), which at the
    backtest's 1.9 exits per week is roughly two months - the reason this monitors and D-017 keeps the verdict.
    """
    loader = closes or _store_closes(root, interval)
    span_ms = int(interval_seconds(interval) * 1000)
    rows: list[dict[str, Any]] = []
    pending = 0
    cost_saved = 0.0
    cache: dict[str, pd.Series] = {}
    for record in store.read_jsonl(store.cycles_path):
        events = record.get("exit_events") or []
        # a dry run never submits an order (engine.py: DRY_RUN) and so never pays the exit's fee; kept in,
        # it would fabricate a cost and a counterfactual into this permanent, append-only, full-history scan
        if not events or record.get("equity") is None or record.get("dry_run"):
            continue
        equity = float(record["equity"])
        # the horizon is walked from the bar the *price* came from.  `event["price"]` is the close of the bar
        # at `as_of_ms` (engine.py, via `ExitOverlay.apply`), while `bar_open_ms` is the host clock's, and
        # D-025 has the host a whole bar from the venue's - on 2026-09-04 a full hour behind.  Anchoring on
        # the host would price a 23-bar hold as a 24-bar one; `_day_of` prefers `as_of_ms` for this reason.
        anchor = int(record.get("as_of_ms") or record.get("bar_open_ms") or 0)
        for event in events:
            if event.get("rule") == COOLDOWN or not event.get("price"):
                continue
            symbol = str(event.get("symbol"))
            notional = float(event.get("target") or 0.0) * equity
            cost_saved += 2.0 * TURNOVER_BPS / 10_000.0 * abs(notional)
            if symbol not in cache:
                try:
                    cache[symbol] = loader(symbol)
                # `data_coverage` below catches broad for the same reason: a store that cannot be read is a
                # research problem, never a reporting failure.  A zero-byte or half-written parquet raises
                # `ArrowInvalid`, not `FileNotFoundError`, and one of those must not stop `report daily` -
                # this monitor runs unattended, so the report is how a broken archive gets noticed at all.
                except Exception:
                    cache[symbol] = pd.Series(dtype=float)
            series = cache[symbol]
            row = {"symbol": symbol, "rule": event.get("rule"), "as_of_ms": anchor, "price": float(event["price"])}
            complete = True
            for horizon in horizons:
                future = anchor + horizon * span_ms
                if future in series.index:
                    row[str(horizon)] = notional * (float(series.loc[future]) / float(event["price"]) - 1.0)
                else:
                    row[str(horizon)] = None
                    complete = False
            pending += 0 if complete else 1
            rows.append(row)
    by_horizon: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        values = [float(row[str(horizon)]) for row in rows if row.get(str(horizon)) is not None]
        by_horizon[str(horizon)] = {
            "n": len(values),
            "mean_counterfactual_u": float(np.mean(values)) if values else None,
            "share_where_staying_paid": float(np.mean([v > 0 for v in values])) if values else None,
        }
    return {
        "events": len(rows),
        "pending": pending,
        "cost_saved_u": cost_saved,
        "by_horizon": by_horizon,
        "n_needed_for_decision": COUNTERFACTUAL_N_FOR_DECISION,
        "rows": rows[-20:],
    }
