"""Whether each bar was traded on time and as planned, and what each fill cost against its estimate.

Checklist area #10 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`, the part
`execution_fidelity.py` (M-Q08) does not hold: restart cost and failed bars (M-Q03), the no-trade
band's plan gaps, the host clock (D-025), and per-order TCA (#10.9 / #10.10).
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_data.store import KlineStore
from starquant_data.store import interval_ms as bar_ms_of  # `interval_ms` is a parameter name in this module
from starquant_live.composition import impact_model
from starquant_live.report_common import DAY_MS, LIQUIDITY_WINDOW_BARS, _cycles, _day_of, _fmt_num, _parsed
from starquant_live.risk_budget import (
    RiskBudgetParams,
    _weighted,
    books_by_bar,
    fill_grouper,
    one_row_per_order,
    slippage_bps,
)
from starquant_live.scheduler import ALREADY_REBALANCED_REASON, BACKOFF_REASON, MISSED_REBALANCE_REASON
from starquant_live.soak import _decided
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml


def plan_gaps(store: StateStore, day: str) -> dict[str, Any]:
    """Symbols the planner could not act on, and why - including the band's own live falsifier.

    ``blocked_entry`` and ``blocked_exit`` are the structural cases: a target smaller than the absolute
    band can never open from flat, and a position smaller than the band can never be closed to zero, so
    those symbols are stuck for as long as the target stays that size.  They are worth naming because
    they look identical, in every other instrument, to a symbol that simply did not need trading.
    ``band_held`` counts the ordinary suppressed resize, which is what P10 cell B registered as its live
    falsifier when it widened ``no_trade_rel_band`` to 0.40 and predicted roughly 12% less turnover.
    """
    rows = [row for row in store.read_jsonl(store.cycles_path) if _day_of(row) == day]
    gaps = [gap for row in rows for gap in (row.get("skipped") or [])]
    counted: dict[str, int] = {}
    for gap in gaps:
        counted[str(gap.get("reason"))] = counted.get(str(gap.get("reason")), 0) + 1
    return {
        "by_reason": counted,
        "band_held": counted.get("NO_TRADE_BAND", 0),
        "blocked_entry": sorted({str(g.get("symbol")) for g in gaps if g.get("reason") == "BAND_BLOCKS_ENTRY"}),
        "blocked_exit": sorted({str(g.get("symbol")) for g in gaps if g.get("reason") == "BAND_BLOCKS_EXIT"}),
    }


def clock_health(store: StateStore, day: str, *, interval_ms: int = 3_600_000) -> dict[str, Any]:
    """D-025: how far this day's cycles sat from the venue clock, and whether the report's own labels are wrong.

    The host clock is the trading reference and a whole-interval offset is an accepted state, so this is
    not an alert.  It is here because every timestamp in this report - including ``day`` itself - is the
    host's, and on 2026-09-04 the host was a full hour behind the venue while the report said nothing.
    ``label_skew_hours`` is how much to add to a label in this file to get venue time.
    """
    rows = [row for row in store.read_jsonl(store.cycles_path) if _day_of(row) == day]
    skews = [
        float(c["skew_ms"]) for row in rows if isinstance((c := row.get("clock") or {}).get("skew_ms"), int | float)
    ]
    if not skews:
        return {"cycles_probed": 0, "labels_reliable": None}
    last = skews[-1]
    alignments = [((s + interval_ms / 2) % interval_ms) - interval_ms / 2 for s in skews]
    worst = max(alignments, key=abs)
    return {
        "cycles_probed": len(skews),
        "venue_minus_host_seconds": round(last / 1000.0, 1),
        "label_skew_hours": round(last / interval_ms) * (interval_ms / 3_600_000.0),
        "worst_distance_from_bar_boundary_seconds": round(worst / 1000.0, 1),
        "jumped_cycles": sum(1 for row in rows if (row.get("clock") or {}).get("jumped")),
        # a whole-bar offset does not endanger trading; it does make every timestamp written here wrong
        "labels_reliable": abs(last) < interval_ms / 2,
        "trading_reference": "host clock (D-025); the offset is accepted, the remainder is what is guarded",
    }


def _restart_cost_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """M-Q03 against its own bar.  Before 2026-09-09 these numbers were rendered and judged by nothing."""
    if not block:
        return {"missed_rebalances": 0}
    limits = block.get("limits") or {}
    share = block.get("late_cycle_share")
    return {
        "status": block.get("status"),
        "missed_rebalances": f"{block.get('missed_rebalances')} (M-Q03 阈值 {limits.get('missed_rebalances')})",
        # Split out from 2026-09-16, because the two halves send a reader to different places: a skip is
        # a restart or a backoff and is read in the deploy log, a failed bar is a request that did not
        # come back and is read on the path to the venue.
        "of_which_cycles_failed": block.get("failed_bars", 0),
        "late_cycle_share": (
            "无可判周期（没有周期记下它当时的窗口）"
            if share is None
            else f"{share:.1%} of {block.get('scheduled_cycles_measurable')} 个已排定周期 "
            f"(M-Q03 阈值 {float(limits.get('late_cycle_share', 0.0)):.0%}；重启不计)"
        ),
        "worst_late_seconds": _fmt_num(block.get("worst_late_seconds")),
        # Restarts are reported under their own name rather than inside the lateness they used to be
        # the whole of.  Both facts stay visible; only the arithmetic stopped mixing them.
        "restarts": block.get("restarts"),
        "worst_restart_late_seconds": _fmt_num(block.get("worst_restart_late_seconds")),
        "unreadable_wakes": block.get("unreadable_wakes"),
        "widest_rebalance_window_seconds": _fmt_num(block.get("widest_window_seconds")),
        # the half M-Q03 is named for, reported without a bar - see `restart_cost`
        "worst_late_fill_seconds": _fmt_num(block.get("worst_late_fill_seconds")),
        "fills_measured": block.get("fills_measured"),
        "reasons": block.get("reasons") or [],
    }


def _woke_seconds_after_close(row: Mapping[str, Any], interval_ms: int) -> float | None:
    """How late a scheduled cycle woke, from what the row already carries.

    No new field was needed for this: every cycle row has written `at` and `bar_open_ms` from the
    beginning (202 of 202 on the live record).  The lateness of every cycle was recorded and only the
    reader was missing, which is this repository's most-repeated defect in its most literal form.

    `None` when the row cannot say - a torn write, or a row from before these fields existed.  An
    unreadable row is a cycle whose punctuality is unknown, not a punctual cycle, so it is counted
    apart rather than folded into either side.
    """
    bar = row.get("bar_open_ms")
    at = row.get("at")
    if not isinstance(bar, int | float) or not isinstance(at, str):
        return None
    try:
        woke_ms = datetime.fromisoformat(at).timestamp() * 1000.0
    except ValueError:
        return None
    return max(0.0, (woke_ms - (float(bar) + interval_ms)) / 1000.0)


def restart_cost(
    rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]] = (),
    params: RiskBudgetParams | None = None,
    *,
    interval_ms: int = 3_600_000,
) -> dict[str, Any]:
    """M-Q03 / AC-L4 / RISK-P2: what the day's restarts cost, counted AND judged rather than assumed.

    DL-L4 wrote both facts into every cycle row - how late the wake-up was relative to the bar close,
    and whether that lateness cost a rebalance - and nothing read them.  The plan assumed every
    deployment restart costs late fills and 7bps of gross; this is the number that would show whether
    the assumption is generous or mean.

    The thresholds are M-Q03's own, from the 2026-09-06 remediation plan ("<= 5% / 0", baseline
    "稳态 0/8"), transcribed into ``risk_budget`` in the profile so they have a reader.  Until
    2026-09-09 they were compared to nothing: the four numbers below were rendered and left there.

    Two things a reader should not have to discover.  First, ``missed_rebalances``, ``skipped_bars`` and
    ``late_bars`` are the SAME rows today, not three facts that happen to agree: the engine writes
    ``late_seconds`` into a cycle row only in ``_record_missed_rebalance``, which also sets the phase and
    the reason.  They are kept apart because they are different questions and a future engine could
    separate them, but nobody should read agreement between them as corroboration.

    Second, this counts miss ROWS and no longer reconstructs the engine's running total.  That counter
    is reset by every restart, so three consecutive processes that each missed once write 1, 1, 1 and a
    drop-detector reports one miss - which is exactly what happened on 2026-09-09, where the record
    holds three miss rows.  It was also wrong the other way, charging a process that spanned midnight
    with yesterday's misses.  Every miss appends exactly one row, so the rows are the count.

    The FILL half is reported and deliberately not judged.  M-Q03 is named for late fills, the fills
    carry their own ``late_seconds``, and the worst one ever written is 26.3s against the 72-98s
    rebalance windows the engine actually used - so this half has never been the binding one, and
    picking a seconds bar for it would be the invented number KILL-R6 refuted.  The plan's preferred
    bar-hour weighting is not computable either: nothing records how long a late-entered position was
    held.  KILL-R6 named the per-cycle share as the acceptable reading and that is what is judged.
    Each venue order is measured once (`one_row_per_order`): a restart's "already submitted" row
    carries the lateness of the re-run that wrote it, not of the fill.
    """
    params = params or RiskBudgetParams()
    restarts = unreadable = 0
    # The bar a cycle FAILED on, charged here from 2026-09-16.  The 2026-09-13 work charged the bars
    # the backoff SLEPT THROUGH and left this one open in its own docstring; four bars since
    # 2026-09-08 have no successful cycle and M-Q03 read zero on every one of those days.  Charged by
    # BAR rather than by row, because a bar is what a rebalance belongs to: `lost` collects the bars
    # that failed deciding nothing, `reached` the bars that got there anyway (a later retry, or a
    # restart that found the book already set), and the difference is what is owed.
    lost: set[int] = set()
    reached: set[int] = set()
    # The bar each charging skip row names, settled against the failed bars at the end.  Until
    # 2026-09-24 a skip row's bar went into `reached` as it was read, so a restart that found a bar a
    # failed cycle had already lost took the charge over: restart #56 turned the 16:01Z proxy 503 on
    # 2026-09-23's 15:00 bar into "查重启原因" and withdrew the failed-bar page.  The miss was one bar
    # either way; which row owns it is what sends the reader somewhere.
    skip_charges: list[object] = []
    failures: list[str] = []
    windows: list[float] = []
    # How late each SCHEDULED cycle woke, from its own row, paired with the bar that row allowed it.
    # The annotation is the fix for a contradiction, not decoration: this was `list[float]` while the
    # append below put a `(woke, window)` pair in it and the line under `widest` unpacked one back
    # out.  It ran correctly - the tuple went in and came out - which is exactly why nobody reread it
    # when the pairing was added.  A declared element type is what makes the next such edit fail loudly.
    wakes: list[tuple[float, float | None]] = []
    restart_late: list[float] = []
    for row in rows:
        reason = row.get("reason")
        skipped = row.get("phase") == "SKIPPED" or reason == MISSED_REBALANCE_REASON
        if skipped:
            # A backoff is not a restart.  These rows arrived on 2026-09-13, when the failure backoff
            # began writing one SKIPPED row per bar it slept through - without which M-Q03's threshold
            # of zero could not see them at all (the loop stayed up, so nothing else recorded the gap).
            # They are genuine MISSES and are charged below; counting them as restarts too would make a
            # single six-hour outage read as six process restarts and inflate `worst_restart_late`,
            # which is the number the failure action "查重启原因" sends someone to look at.
            if reason != BACKOFF_REASON:
                restarts += 1
            # A bar that was already rebalanced cannot have had its rebalance missed.  The row still
            # carries the window the engine allowed, so `widest_window_seconds` keeps it; only the miss
            # COUNT declines to charge it, and a failure on the same bar is excused: the book did get set.
            if reason != ALREADY_REBALANCED_REASON:
                skip_charges.append(row.get("bar_open_ms"))
            elif isinstance(bar := row.get("bar_open_ms"), int):
                reached.add(bar)
            if isinstance(window := row.get("window_seconds"), int | float):
                windows.append(float(window))
            if reason != BACKOFF_REASON and isinstance(value := row.get("late_seconds"), int | float):
                restart_late.append(float(value))
            continue
        # The bar is per row when the row carries it (every completed cycle does, from 2026-09-10) and
        # falls back to the widest the engine allowed that day, for rows written before it did.
        if isinstance(window := row.get("window_seconds"), int | float):
            windows.append(float(window))
        # A cycle can fail AFTER placing orders - `run_cycle` places them and only then quarantines,
        # summarizes and finishes - and that bar WAS rebalanced.  The five keys that answer it are
        # already written onto the ERROR row for L3, and are read here through the same function, so a
        # sixth cannot be added to one side alone.  Failed rows go on to the lateness accounting below
        # unchanged: the cycle did wake, and it is only the rebalance that was lost.
        if isinstance(bar := row.get("bar_open_ms"), int):
            if row.get("phase") == "ERROR" and not _decided(row):
                lost.add(bar)
                failures.append(str(row.get("error") or "未记录"))
            else:
                reached.add(bar)
        woke = _woke_seconds_after_close(row, interval_ms)
        if woke is None:
            unreadable += 1
        else:
            wakes.append((woke, float(window) if isinstance(window, int | float) else None))
    fills = [
        float(t["late_seconds"]) for t in one_row_per_order(trades) if isinstance(t.get("late_seconds"), int | float)
    ]
    # The bar is the window the ENGINE allowed, read off the rows rather than recomputed here - the
    # same refusal `widest_window_seconds` already makes.  With no window in the record there is
    # nothing to measure against, and `None` says so; a day with nothing to compare is not a day
    # nothing was late on, and a zero here would read as a pass.
    widest = max(windows) if windows else None
    judged = [(value, bar if bar is not None else widest) for value, bar in wakes]
    late = [value for value, bar in judged if bar is not None and value > bar]
    measurable = [value for value, bar in judged if bar is not None]
    share = (len(late) / len(measurable)) if measurable else None
    failed = lost - reached
    # A skip row on a failed bar is the restart finding that bar already lost: not a second miss.
    skips = sum(1 for bar in skip_charges if bar not in failed)
    failed_bars = len(failed)
    missed = skips + failed_bars
    reasons: list[str] = []
    if missed > params.max_missed_rebalances:
        # The failure action names what actually happened.  "查重启原因" was the only one offered, and
        # on the four bars this reporter could not see until 2026-09-16 there was no restart to read:
        # the loop stayed up and a request to the venue failed.
        worst_restart = max(restart_late) if restart_late else 0.0
        where = (
            f"其中 {failed_bars} 根是周期失败（{failures[-1]}）；失败动作：查这条路径，不是重启"
            if failed_bars
            else f"最迟的一次在 bar 收盘后 {worst_restart:.0f} 秒；失败动作：查重启原因"
        )
        reasons.append(f"漏掉 {missed} 次再平衡（M-Q03 阈值 {params.max_missed_rebalances}）；{where}")
    if share is not None and share > params.max_late_cycle_share:
        reasons.append(
            f"迟到周期占比 {share:.1%} 高于 M-Q03 的 {params.max_late_cycle_share:.0%}"
            f"（{len(late)}/{len(measurable)} 个已排定周期在再平衡窗口外醒来；重启不计）"
        )
    return {
        "cycles": len(rows),
        "missed_rebalances": missed,
        # Kept apart from 2026-09-16.  These were the same rows and the docstring above said a future
        # engine could separate them; a failed bar is a miss and is not a skip, so they now differ.
        "skipped_bars": skips,
        "failed_bars": failed_bars,
        # Named separately from the reason line because `daily_alerts` pages on this half and an alert
        # that says only "1 根 bar" sends the reader to open the report to find out what broke.
        "failed_bar_error": failures[-1] if failures else None,
        # Restarts are counted and named rather than folded into the lateness they used to inflate.
        "restarts": restarts,
        "worst_restart_late_seconds": max(restart_late) if restart_late else None,
        "unreadable_wakes": unreadable,
        "scheduled_cycles": len(wakes),
        "scheduled_cycles_measurable": len(measurable),
        "worst_late_seconds": max(late) if late else None,
        "late_bars": len(late),
        "late_cycle_share": share,
        # What the engine ACTUALLY allowed, read off the rows rather than re-derived here: the window is
        # grace + launchd's ThrottleInterval + this process's measured startup, so it differs per restart
        # and a copy of the formula in the reporter would drift away from the one that decided.
        "widest_window_seconds": max(windows) if windows else None,
        "worst_late_fill_seconds": max(fills) if fills else None,
        "fills_measured": len(fills),
        "limits": {
            "late_cycle_share": params.max_late_cycle_share,
            "missed_rebalances": params.max_missed_rebalances,
        },
        "status": "ALERT" if reasons else "OK",
        "reasons": reasons,
    }


# --- per-order TCA: #10.9 pre-trade and #10.10 post-trade ---------------------------------------------

#: The cost model the estimate is rebuilt from when the caller passes none: the file
#: `ReplayInputs.from_profile` reads for a profile that names no other, and the one the shipped profile names.
COSTS_PATH = "config/costs.yaml"
#: Decade edges of participation for the error's buckets.  Fixed rather than quantiles, so a bucket
#: means the same thing next month; the window to 2026-09-25T05:00Z put 38 / 68 / 16 / 2 fills in them.
TCA_PARTICIPATION_EDGES = (1e-5, 1e-4, 1e-3)
#: How far `decision_close` may sit from the archive's close of the decision bar and still be that bar's.
#: Both are the venue's kline close read into a float, and on 2026-09-25 all 124 archived fills agreed
#: bit for bit.  Another bar's close differs by at least a tick unless the price did not move, and the
#: smallest tick relative to price among the names traded is 1.3e-6 (BTCUSDT, 0.1 on about 78,000).
#: 1e-9 sits three orders under a tick and seven over the noise of reading a price into a float.
DECISION_CLOSE_RTOL = 1e-9
MISMATCHED_BAR = "决策 bar 对不上归档"


def per_order_tca(
    store: StateStore,
    params: RiskBudgetParams | None = None,
    *,
    data_root: str | Path = ".starquant/data",
    costs: Mapping[str, Any] | None = None,
    interval: str = "1h",
) -> dict[str, Any]:
    """#10.9 / #10.10: each fill's pre-trade cost estimate beside what it cost.  Reported, never judged.

    **Pre-trade, rebuilt offline.**  The loop records no estimate, and recording one would cost a
    restart for a reading.  Everything the estimate needs is already on the trade row or in the archive,
    so rebuilding it here gives the number the loop would have written.  It is the cost model: taker
    fee, `slippage_bps`, and the square-root impact term the way `backtest.impact_costs` prices it -
    coefficient x sigma_daily x sqrt(notional / ADV), sigma over the open-to-close returns `run_backtest`
    hands it by default, both windows from `impact_model` (research's entry point) - on the PLANNED
    notional (`quantity` x `price`, both fixed before the order was sent).  Participation is that
    notional over the mean quote volume of the last `LIQUIDITY_WINDOW_BARS` bars: `LiveEngine._liquidity`'s
    hour, the one `max_participation` is a fraction of.  The coefficient is E5 and has never been
    calibrated (demo fills are too small to measure it, `config/costs.yaml`), so the error below measures
    the model, not execution.

    **Every input is the decision bar or older**, and the decision bar is the one the cycle row that
    recorded the order names in `as_of_ms` - the klines' own bar - not the fill's `bar_open_ms`, which is
    the host clock's label.  D-025 accepts a whole-bar offset between the two (21 rows on 2026-09-04 sat
    3,600,000 ms apart), and a host one bar ahead would label an order with a bar that had not closed
    when it went out.  The row's `decision_close` must also be the archive's close of that bar
    (`DECISION_CLOSE_RTOL`); where it is not, the fill is counted as `MISMATCHED_BAR`, neither split nor
    estimated.  The window, the book and the fee stay keyed by `bar_open_ms`, as M-Q08 and attribution are.

    **Post-trade, against `decision_close`**, signed so a cost is positive, over M-Q08's population
    (its window, no flattens, a reference on the row, each venue order once) with its arithmetic
    (`_weighted`: notional-weighted, Kish SE) and its split by book (`fill_grouper`) - which is what lets
    the mean reconcile to both of M-Q08's readings, the whole book and the main book it judges, and the
    block checks that it does.  Split at the next bar's archived open into the gap (decision close ->
    open) and the fill (open -> average price), both in bps of the decision close so the two add up.
    The fill part carries the order's delay past the open, the spread, any impact, and the difference
    between mainnet's price and demo's: the open is mainnet's archive and the fill is demo's.  1h bars
    cannot tell those apart.  **The prediction is compared with the fill part alone**: `slippage_bps` is
    an adverse fill against the next open (`config/costs.yaml`), so the gap is no part of what the model
    predicts, and it keeps its own line.

    **The spread is not split out, for two reasons checked 2026-09-24.**  The fills trade on the demo
    book, and it does not behave like mainnet's: from 19:14 to 19:15Z demo BTCUSDT held its best bid /
    ask at 84457.9 / 84462.5 while mainnet's moved between 84580 and 84545, three demo AKEUSDT ask levels
    each held 6,537,999, and demo's hourly quote volume on BTCUSDT ran 6-22x mainnet's on the four bars
    sampled.  That its depth is synthetic is an inference from those samples; the venue does not say so.
    And the one archived top of book, data.binance.vision's `bookTicker`, stops in 2024-04 (BTCUSDT daily
    2023-05-16 to 2024-03-30; none at all for AKEUSDT or ENAUSDT).  `bookDepth` runs to date, but it is
    mainnet's book.

    **The fee is listed apart**, as booked: the commission over the fill's notional.  An attribution
    row carries `state.last_bar_ms` - the bar of the cycle BEFORE the one that read the income, which
    is the cycle that placed the fills the commission came from - so (bar, symbol) keys a fill to its
    commission, and only a key with one row on each side is read.  A `live flatten` fill has no bar, so
    that count cannot see it, and a key whose income window also held one is not read either
    (`_booked_fees`).  On 2026-09-24 that booked 4.0 bps on thirteen names and 5.0 on seven, against the
    model's flat 5.0.

    The catch is broad for `execution_fidelity`'s reason: this runs in the hourly check and judges
    nothing, so it must not take the report or its alerts down.  The block carries the reason instead,
    and an archive that cannot be read costs only its own symbol the split and the estimate.
    """
    try:
        return _tca(store, params or RiskBudgetParams(), Path(data_root), costs, interval)
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _tca(
    store: StateStore, params: RiskBudgetParams, root: Path, costs: Mapping[str, Any] | None, interval: str
) -> dict[str, Any]:
    costs = load_yaml(COSTS_PATH) if costs is None else costs
    impact = impact_model(costs)
    model: dict[str, Any] = {
        "taker_fee_bps": float(costs.get("taker_fee_bps", 5.0)),
        "slippage_bps": float(costs.get("slippage_bps", 2.0)),
        "impact_coefficient": impact.coefficient,
        "adv_window_bars": impact.adv_window,
        "vol_window_bars": impact.vol_window,
    }
    # The report's own rows, the ones `risk_budget_status` is handed.  Read from every row, a restart's
    # SKIPPED row would end the window on a bar that never traded; on 2026-09-23 such rows also took
    # over their bars' books and re-split 67 main-book fills as 52 (`books_by_bar` now skips them).
    rows, trades = _cycles(store), one_row_per_order(store.read_jsonl(store.trades_path))
    books = books_by_bar(rows)
    book_of = fill_grouper(books)
    decided = _decision_bars(rows)
    latest = int(rows[-1].get("bar_open_ms") or 0) if rows else 0
    since = latest - params.slippage_window_days * DAY_MS
    fees, mixed = _booked_fees(store.read_jsonl(store.attribution_path), trades)
    placed = Counter((row.get("bar_open_ms"), str(row.get("symbol") or "")) for row in trades)
    bar_ms = bar_ms_of(interval)
    archive: dict[str, dict[str, np.ndarray] | str] = {}
    fills: list[dict[str, Any]] = []
    without_reference = 0
    for trade in trades:
        # `slippage_bps`'s filter, test for test: the population is what makes the two means reconcile.
        if int(trade.get("bar_open_ms") or 0) < since or trade.get("flatten"):
            continue
        reference, filled, quantity = trade.get("decision_close"), trade.get("avg_price"), trade.get("executed_qty")
        if reference is None and filled and quantity:
            without_reference += 1
            continue
        if not reference or not filled or not quantity:
            continue
        try:
            reference, filled, quantity = float(reference), float(filled), float(quantity)
        except (TypeError, ValueError):
            continue
        if reference <= 0 or filled <= 0 or quantity <= 0:
            continue
        side = 1.0 if str(trade.get("side", "")).upper() == "BUY" else -1.0
        bar, symbol = int(trade.get("bar_open_ms") or 0), str(trade.get("symbol") or "")
        reading: dict[str, Any] = {
            "symbol": symbol,
            "bar": bar,
            "book": book_of(bar, symbol),
            "notional": filled * quantity,
            "slippage": side * (filled - reference) / reference * 10_000.0,
            "late_seconds": trade.get("late_seconds"),
        }
        paid_rows = fees.get((bar, symbol), [])
        if len(paid_rows) == 1 and placed[(bar, symbol)] == 1 and (bar, symbol) not in mixed:
            reading["fee"] = -paid_rows[0] / reading["notional"] * 10_000.0
        if symbol not in archive:
            archive[symbol] = _archived_bars(root, symbol, interval)
        # An order no traded cycle recorded - one placed by a cycle that then raised - keeps its own
        # label, and the close check below is what stands between that guess and a wrong bar.
        decision = decided.get((symbol, str(trade.get("order_id"))), bar)
        reading.update(_against_the_archive(trade, archive[symbol], decision, bar_ms, side, reference, model))
        fills.append(reading)
    split = [reading for reading in fills if "gap" in reading]
    for reading in split:
        reading["fill"] = reading["slippage"] - reading["gap"]  # in bps of the decision close, so they add up
    estimated = [reading for reading in fills if "predicted" in reading]
    # The model's `slippage_bps` is against the next open, so what it predicts is the fill part.
    compared = [reading for reading in estimated if "fill" in reading]
    for reading in compared:
        reading["error"] = reading["predicted"] - reading["fill"]
    late = [float(r["late_seconds"]) for r in split if isinstance(r.get("late_seconds"), int | float)]
    # The newest bar's commission is read by the NEXT cycle's income window, so it is not missing yet.
    booked_until = max((bar for bar, _symbol in fees), default=0)
    unbooked = [reading for reading in fills if "fee" not in reading and reading["bar"] <= booked_until]
    with_flatten = sum(1 for reading in unbooked if (reading["bar"], reading["symbol"]) in mixed)
    participation = sorted(float(reading["participation"]) for reading in estimated)
    measured = _tca_mean(fills, "slippage")
    mq08 = slippage_bps(trades, params, latest_ms=latest, books_at=books)
    return {
        "window": {
            "since": _iso(since),
            "until": _iso(latest),
            "days": params.slippage_window_days,
            "interval": interval,
        },
        "fills": len(fills),
        "without_reference": without_reference,
        "post_trade": {
            "slippage": measured,
            "gap": _tca_mean(split, "gap"),
            "fill": _tca_mean(split, "fill"),
            "split_slippage": _tca_mean(split, "slippage"),
            "late_seconds_median": statistics.median(late) if late else None,
            "unsplit": dict(Counter(f"{r['symbol']} {r['unsplit']}" for r in fills if "unsplit" in r)),
            "fee": {
                "model_bps": model["taker_fee_bps"],
                "booked": _tca_mean(fills, "fee"),
                "not_yet_read": sum(1 for reading in fills if "fee" not in reading and reading["bar"] > booked_until),
                "unmatched": len(unbooked) - with_flatten,
                "flatten_in_window": with_flatten,
            },
        },
        # Against both of M-Q08's readings: the whole book, and the one it judges (G9's split, per fill).
        "reconciliation": {
            "combined": _reconciled(measured, mq08["combined"]),
            "main_only": _reconciled(
                _tca_mean([r for r in fills if r["book"] == "main_only"], "slippage"),
                mq08["by_group"].get("main_only") or _weighted([], []),
            ),
            "judged": mq08["judged"],
        },
        "pre_trade": {
            "model": model,
            "predicted": _tca_mean(estimated, "predicted"),
            "impact": _tca_mean(estimated, "impact"),
            "participation": {"median": statistics.median(participation), "max": participation[-1]}
            if participation
            else None,
            "liquidity_window_bars": LIQUIDITY_WINDOW_BARS,
            "unestimated": dict(Counter(f"{r['symbol']} {r['unestimated']}" for r in fills if "unestimated" in r)),
        },
        "predicted_minus_actual": _tca_mean(compared, "error"),
        "by_participation": _by_participation(compared),
    }


def _decision_bars(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], int]:
    """(symbol, order_id) -> the bar the order was decided on: `as_of_ms` of the first cycle row listing it.

    The first row is the cycle that placed it; a restart that re-runs the bar lists it again.  A row
    without `as_of_ms` gives its `bar_open_ms`, `liquidity_to_close`'s rule for the same field.
    """
    decided: dict[tuple[str, str], int] = {}
    for row in rows:
        bar = row.get("as_of_ms") or row.get("bar_open_ms")
        if not isinstance(bar, int | float) or isinstance(bar, bool):
            continue
        for order in row.get("orders") or []:
            if isinstance(order, Mapping) and order.get("order_id") not in (None, ""):
                decided.setdefault((str(order.get("symbol") or ""), str(order["order_id"])), int(bar))
    return decided


def _booked_fees(
    attribution: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]]
) -> tuple[dict[tuple[int, str], list[float]], set[tuple[int, str]]]:
    """Each (bar, symbol)'s booked commissions, and the keys whose income window also held a flatten fill.

    A `live flatten` fill carries no bar, and its commission goes into the first attribution row written
    after it, whatever bar that row is keyed by.  Both `at` stamps are the host clock's
    (`StateStore._append`), so their order needs no conversion; the row's own `since_ms` / `until_ms` are
    the venue's (D-030) and would need the offset D-025 accepts.  A commission that reached the venue's
    income feed only after the next row was written would land one row later, and nothing recorded can
    tell that apart.
    """
    fees: dict[tuple[int, str], list[float]] = {}
    written: list[tuple[datetime, int]] = []
    for row in attribution:
        if not isinstance(bar := row.get("bar_open_ms"), int):
            continue
        for symbol, bucket in (row.get("by_symbol") or {}).items():
            if paid := float(bucket.get("COMMISSION") or 0.0):
                fees.setdefault((bar, str(symbol)), []).append(paid)
        if (stamp := _parsed(row.get("at"))) is not None:
            written.append((stamp, bar))
    written.sort()
    stamps = [stamp for stamp, _bar in written]
    mixed: set[tuple[int, str]] = set()
    for trade in trades:
        stamp = _parsed(trade.get("at")) if trade.get("flatten") else None
        if stamp is not None and (after := bisect_right(stamps, stamp)) < len(written):
            mixed.add((written[after][1], str(trade.get("symbol") or "")))
    return fees, mixed


def _archived_bars(root: Path, symbol: str, interval: str) -> dict[str, np.ndarray] | str:
    """One symbol's archived bars as arrays, or the reason they cannot be read.

    Read whole, because D-025's offset can put a decision bar before the window, and a slice cut at the
    window would shorten its sigma and ADV without saying so.  A file that will not open is its own
    symbol's problem (a half-written parquet raises ArrowInvalid, not FileNotFoundError): the reason goes
    on that symbol's fills and the others are still priced, `liquidity_to_close`'s rule.
    """
    try:
        frame = KlineStore(root).load(symbol, interval)
        columns = {name: frame[name].to_numpy(dtype=float) for name in ("open", "close", "quote_volume")}
        return {"open_time": frame["open_time"].to_numpy(dtype=np.int64), **columns}
    except FileNotFoundError:
        return "归档没有这个标的"
    except Exception as error:
        return f"归档读不出：{type(error).__name__}: {error}"


def _against_the_archive(
    trade: Mapping[str, Any],
    bars: Mapping[str, np.ndarray] | str,
    decision: int,
    bar_ms: int,
    side: float,
    reference: float,
    model: Mapping[str, Any],
) -> dict[str, Any]:
    """What the archive adds to one fill: the gap to the next open, and the estimate made before it was sent.

    `decision` is the bar the order was decided on (`_decision_bars`).  The estimate reads it and the
    bars before it; the split reads the next bar's open as well, which is the gap's other end.  Each is
    there or replaced by the reason it is not, and the block counts the reasons: a fill the archive
    cannot price is not a fill that cost nothing.
    """
    if isinstance(bars, str):
        return {"unsplit": bars, "unestimated": bars}
    times = bars["open_time"]
    at = int(np.searchsorted(times, decision))
    if at >= len(times) or int(times[at]) != decision:
        # Past the archive's last bar is the daily sync not having caught up; inside it is a hole.
        why = "归档还没到决策 bar" if at >= len(times) else "归档缺决策 bar"
        return {"unsplit": why, "unestimated": why}
    if not math.isclose(reference, float(bars["close"][at]), rel_tol=DECISION_CLOSE_RTOL):
        return {"unsplit": MISMATCHED_BAR, "unestimated": MISMATCHED_BAR}
    out: dict[str, Any] = {}
    if at + 1 < len(times) and int(times[at + 1]) == decision + bar_ms:
        out["gap"] = side * (float(bars["open"][at + 1]) - reference) / reference * 10_000.0
    else:
        out["unsplit"] = "归档还没到下一根 bar" if at + 1 >= len(times) else "归档缺下一根 bar"
    bars_per_day = DAY_MS / bar_ms
    planned = float(trade.get("quantity") or 0.0) * float(trade.get("price") or 0.0)
    # `LiveEngine._liquidity`, computed the way it computes it, on the archive's copy of the bars it held.
    hourly = float(pd.Series(bars["quote_volume"][max(0, at - LIQUIDITY_WINDOW_BARS + 1) : at + 1]).mean())
    adv = float(np.mean(bars["quote_volume"][max(0, at - model["adv_window_bars"] + 1) : at + 1])) * bars_per_day
    first = max(0, at - model["vol_window_bars"] + 1)
    returns = bars["close"][first : at + 1] / bars["open"][first : at + 1] - 1.0  # `run_backtest`'s default
    fewest = model["vol_window_bars"] // 4  # `impact_costs`' own min_periods
    if len(returns) < fewest:
        out["unestimated"] = f"决策 bar 之前不足 {fewest} 根收益"
        return out
    sigma_daily = float(np.std(returns, ddof=1)) * math.sqrt(bars_per_day)
    if not (planned > 0 and hourly > 0 and adv > 0 and math.isfinite(sigma_daily)):
        out["unestimated"] = "计划名义额、成交额或波动率读不出"
        return out
    impact = model["impact_coefficient"] * sigma_daily * math.sqrt(planned / adv) * 10_000.0
    out.update(participation=planned / hourly, impact=impact, predicted=model["slippage_bps"] + impact)
    return out


def _tca_mean(readings: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    """M-Q08's arithmetic (`_weighted`) over the readings that have `key`."""
    chosen = [reading for reading in readings if reading.get(key) is not None]
    return _weighted([float(r[key]) for r in chosen], [float(r["notional"]) for r in chosen])


def _reconciled(measured: Mapping[str, Any], judged: Mapping[str, Any]) -> dict[str, Any]:
    """This block's mean slippage against one of M-Q08's readings: the same fills must give the same number."""
    value, reference = measured.get("value"), judged.get("value")
    difference = None if value is None or reference is None else float(value) - float(reference)
    same_fills = measured.get("fills") == judged.get("fills")
    agrees = same_fills and (difference is None or abs(difference) <= 1e-9)
    why = None
    if not same_fills:
        why = f"成交笔数不同（TCA {measured.get('fills')}，M-Q08 {judged.get('fills')}）：两边取的不是同一批成交"
    elif not agrees:
        why = "同一批成交而均值不同：两边的算术分叉了"
    return {
        "value": value,
        "fills": measured.get("fills"),
        "m_q08": reference,
        "m_q08_fills": judged.get("fills"),
        "difference": difference,
        "agrees": agrees,
        "why": why,
    }


def _by_participation(readings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The prediction error per participation bucket, beside the two means it is the difference of."""
    out: list[dict[str, Any]] = []
    for low, high in pairwise((0.0, *TCA_PARTICIPATION_EDGES, math.inf)):
        chosen = [reading for reading in readings if low <= float(reading["participation"]) < high]
        if not chosen:
            continue
        label = f"<{high:.0e}" if low == 0.0 else (f"≥{low:.0e}" if math.isinf(high) else f"{low:.0e}–{high:.0e}")
        out.append(
            {
                "bucket": label,
                "predicted_minus_actual": _tca_mean(chosen, "error"),
                "fill": _tca_mean(chosen, "fill")["value"],
                "predicted": _tca_mean(chosen, "predicted")["value"],
            }
        )
    return out


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _tca_bps(block: Mapping[str, Any] | None) -> str:
    if not block or block.get("value") is None:
        return "无"
    se = "" if block.get("se") is None else f"±{block['se']:.2f}"
    return f"{block['value']:+.2f}{se} bps（{block.get('fills')} 笔）"


def _signed(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):+.2f}"


def _reconciled_line(row: Mapping[str, Any]) -> str:
    verdict = "对得上" if row.get("agrees") else f"对不上：{row.get('why')}"
    return (
        f"TCA {_signed(row.get('value'))} / M-Q08 {_signed(row.get('m_q08'))} bps"
        f"（{row.get('m_q08_fills')} 笔），差 {_signed(row.get('difference'))}，{verdict}"
    )


def tca_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """#10.9 / #10.10 on the page, with the estimate's caveats as lines of their own.  Readings only."""
    if not block:
        return {"none": 0}
    if block.get("error"):
        return {"读不出，这一块整块失败": block["error"]}
    window = block.get("window") or {}
    if not block.get("fills"):
        return {"窗口内成交": f"0 笔（决策 bar {window.get('since')} 起）"}
    post, pre = block.get("post_trade") or {}, block.get("pre_trade") or {}
    fee, model, recon = post.get("fee") or {}, pre.get("model") or {}, block.get("reconciliation") or {}
    booked = fee.get("booked") or {}
    participation, late = pre.get("participation") or {}, post.get("late_seconds_median")
    lines: dict[str, Any] = {
        "窗口": f"决策 bar {window.get('since')} 至 {window.get('until')}，与 M-Q08 同一个 {window.get('days')} 天",
        "实际滑点（对 decision_close，对我不利为正）": f"{_tca_bps(post.get('slippage'))}，名义额加权",
        "对账：M-Q08 全书合并读数": _reconciled_line(recon.get("combined") or {}),
        "对账：M-Q08 主书独有读数" + ("（判定读数）" if recon.get("judged") == "main_only" else ""): (
            _reconciled_line(recon.get("main_only") or {})
        ),
        "跳空（decision_close → 下一根开盘价）": _tca_bps(post.get("gap")),
        "成交（开盘价 → 成交均价）": (
            f"{_tca_bps(post.get('fill'))}；两段之和 {_signed((post.get('split_slippage') or {}).get('value'))} bps"
        ),
        "成交段里有什么": (
            ("下单延迟" if late is None else f"下单延迟（中位 {late:.0f} 秒）")
            + "、价差、冲击，以及主网与 demo 的价格差：开盘价取主网归档，成交在 demo 上。"
            + f"归档只有 {window.get('interval')} bar，拆不开"
        ),
        "价差为什么不单拆": (
            "成交打在 demo 盘口上。demo 的深度像是合成的，这是推断：2026-09-24 抽查时，"
            "一分钟里 demo 的买一卖一没动，主网在动。主网 bookTicker 归档止于 2024-04"
        ),
        "手续费（另列，不在滑点里）": (
            f"入账 {_tca_bps(booked)}；成本模型 taker {_fmt_num(fee.get('model_bps'))} bps"
            + (f"；{fee['not_yet_read']} 笔下个周期才读到手续费" if fee.get("not_yet_read") else "")
            + (f"；{fee['unmatched']} 笔在 attribution 里对不上唯一一行" if fee.get("unmatched") else "")
            + (
                f"；{fee['flatten_in_window']} 笔的入账窗口里有 live flatten 的成交，不读"
                if fee.get("flatten_in_window")
                else ""
            )
        ),
        "事前估计（离线重建，循环没有记录）": (
            f"{_tca_bps(pre.get('predicted'))} = slippage_bps {_fmt_num(model.get('slippage_bps'))}"
            f" + 冲击 {_fmt_num((pre.get('impact') or {}).get('value'))}；taker 另计"
        ),
        "事前估计的输入": "只用决策时刻已收盘的 bar。决策 bar 取周期行的 as_of_ms，不取主机时钟的 bar_open_ms",
        "参与率的口径": (
            f"计划名义额 ÷ 近 {pre.get('liquidity_window_bars')} 根 bar 的平均小时成交额，与 max_participation 同一口径"
        ),
        "冲击系数": f"{model.get('impact_coefficient')}，没校准（costs.yaml 标 E5）",
        "参与率 中位 / 最大": (
            f"{participation['median']:.1e} / {participation['max']:.1e}" if participation else "无"
        ),
        "预测比的是哪一段": "成交段。slippage_bps 按下一根开盘价定义，跳空不在预测里",
        "预测 − 成交段（名义额加权）": _tca_bps(block.get("predicted_minus_actual")),
    }
    for row in block.get("by_participation") or []:
        lines[f"预测 − 成交段，参与率 {row['bucket']}"] = (
            f"{_tca_bps(row.get('predicted_minus_actual'))}；成交段 {_signed(row.get('fill'))}，"
            f"预测 {_signed(row.get('predicted'))}"
        )
    for key, label in (("unestimated", "没有事前估计的"), ("unsplit", "没拆两段的")):
        counted = (pre if key == "unestimated" else post).get(key) or {}
        if counted:
            lines[label] = "；".join(f"{why} {n} 笔" for why, n in sorted(counted.items()))
    if block.get("without_reference"):
        lines["没有 decision_close 的"] = f"{block['without_reference']} 笔，不计入（与 M-Q08 同）"
    return lines
