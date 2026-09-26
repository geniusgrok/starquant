"""M-Q08 execution fidelity: the instrument its turnover clause never had, and slippage read week by week.

M-Q08 is one of the two criteria the demo phase is judged by (the learning-plan table of
`docs/analysis/2026-09-06-remediation-execution-plan.md`): turnover within ±25% of the backtest over the
same period, slippage at most twice the model, late cycles at most 5%, the registry digest consistent.
Slippage (`risk_budget.slippage_bps`) and lateness (`reports.restart_cost`) had readings, the digest is on
every cycle row; turnover had no instrument at all (G9 of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`), and nothing read slippage over time.

**One unit on both sides: notional traded over the equity it was sized from, keyed by the deciding bar.**
The backtest's turnover is `sum |Δw|` per bar, a weight being a fraction of the equity at the decision.
Live, `target_notional` is `target_weight` times the equity the cycle recorded - on all 202 trade rows with
a nonzero target and a priced cycle, 2026-09-23, to 1.8e-12 U - so a fill's notional over its own cycle's
equity is that symbol's `|Δw|`.  The backtest charges the weight decided on bar t at bar t+1, so its series
is moved back one bar the way `run_backtest` finds `decision_times`; a live fill carries the `bar_open_ms`
of the cycle that decided it.  What the unit does NOT make equal is what M-Q08 exists to see: the
backtest's held position is last bar's target, so drift is free, while live the band is judged against the
venue's drifted position; missed bars, the participation cap, the venue minimum and the exit anchors the
loop has carried since it first built the book are all execution.

**Same period, same construction.**  The backtest side is the model the registry on disk builds, priced by
`score_book` with the profile's guards and exits (`live_overlay_blocks`, what the startup gate compares),
over the newest run of cycles on one construction AND one registry digest, at most `WINDOW_DAYS`, and only
while the disk digest is the loop's.  Its universe is the one the loop recorded bar by bar, so the pool is
held equal; bars before the loop recorded any use the point-in-time table, as research's backtest does.

**Path dependence, measured on the 2026-09-23 record.**  The exit overlay anchors on the entry price and the
band on the previous position, so the replay's state at the window's first bar depends on where it starts.
Starting 1,442 bars before the window (what the loop requests) gave ratio 1.40; 30 days earlier, 2.0679;
60, 120 and 180 days earlier agreed with that to 1e-5.  Hence `WARMUP_DAYS`.  From the other side, the
loop's anchors date from when IT built the book: in that window it took ten take-profits and the replay
four, the same four among them, and the six only the loop took were all anchored at the 2026-09-13T20:00Z
closes - the bar that rebuilt the book after that evening's flatten.  Each costs an exit and a re-entry.

**Cells the archive cannot price.**  The data job syncs the current candidates, so a name the loop still
holds can stop updating: LSKUSDT's archive ends 2026-09-18T16:00Z while the loop held it on 09-23.  A
symbol-bar past its last archived close leaves BOTH sides, and what that took off the live side is printed.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.backtest import CostModel
from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exits import COOLDOWN, ExitParams, apply_exits
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel, interval_seconds
from starquant_alpha.registry import Registry
from starquant_alpha.validation.pipeline import score_book
from starquant_data.pool import MEMBERSHIP_FILE, membership_at_bars
from starquant_data.store import FundingStore, KlineStore
from starquant_live.composition import build_model, cost_model, load_panel
from starquant_live.construction import canonical_construction
from starquant_live.risk_budget import _weighted, books_by_bar, fill_grouper, one_row_per_order
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml

DAY_MS = 86_400_000
EPOCH = pd.Timestamp(0, tz="UTC")
WINDOW_DAYS = 30  # M-Q08's own window
TURNOVER_BAND = 0.25  # M-Q08's "±25%", transcribed rather than chosen
WARMUP_DAYS = 60  # on top of the loop's own history: 30 converged on 2026-09-23 and 0 did not
# The day is the pairing unit of the ratio's error bar.  Below fourteen pairs it has at most 12 degrees of
# freedom, where the two-sided 95% t quantile is above 2.18 (2.45 at 6) and "2 SE" understates it by more
# than 8%; and a take-profit is an exit plus a re-entry a day later, so a week holds only a handful of
# independent events.  Below it the ratio is printed with its error bar and judged by nothing.
MIN_COMPLETE_DAYS = 14
TREND_WEEKS = 5  # enough to cover M-Q08's 30 days


@dataclass(frozen=True)
class ReplayInputs:
    """What the backtest side needs, built by the caller that holds the profile and the registry."""

    model: AlphaModel | None
    cost: CostModel
    guards: BookGuardParams | None
    exits: ExitParams | None
    data_root: str
    registry_on_disk: str | None
    problem: str | None = None

    @classmethod
    def from_profile(cls, profile: Mapping[str, Any], registry: Registry, data_root: str | Path) -> ReplayInputs:
        """The construction the files on disk describe, built the way the loop and its startup gate build it.

        It runs in the hourly `report daily --check`, ahead of every other block, so it never raises: the
        catch is broad for `market_beta`'s reason, and a registry the loop could not start on is `live
        status`'s finding.  Here it only blinds this instrument, which says why.  `config` and `engine` are
        imported inside, not at the top: both import `reports`, which imports this module.
        """
        try:
            from starquant_live.config import live_overlay_blocks
            from starquant_live.engine import registry_digest

            blocks = live_overlay_blocks(profile)
            guards = BookGuardParams(**(blocks["book_guards"] or {}))
            exits = None if blocks["exits"] is None else ExitParams.from_mapping(blocks["exits"])
            model = build_model(registry, profile)
            cost = cost_model(load_yaml(str(profile.get("costs", "config/costs.yaml"))))
            return cls(model, cost, guards, exits, str(data_root), registry_digest(model))
        except Exception as error:
            return cls(None, CostModel(), None, None, str(data_root), None, f"{type(error).__name__}: {error}")


@dataclass(frozen=True)
class Replay:
    turnover: pd.DataFrame  # decision bars x symbols: the backtest's `|Δw|`
    priced_until: dict[str, int]  # symbol -> the last bar_open_ms the archive holds a close for
    exits: set[tuple[int, str]]  # (decision bar ms, symbol) of every exit the overlay took
    replay_from_ms: int


def _ms(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray((index - EPOCH) // pd.Timedelta(milliseconds=1), dtype=np.int64)


def _stamp(ms: int | None) -> str | None:
    return None if ms is None else pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def _bar(row: Mapping[str, Any]) -> bool:
    return isinstance(row.get("bar_open_ms"), int | float) and not isinstance(row.get("bar_open_ms"), bool)


def replay_turnover(
    panel: Panel, membership: pd.DataFrame, inputs: ReplayInputs
) -> tuple[pd.DataFrame, set[tuple[int, str]]]:
    """The backtest's own turnover split by symbol and keyed by the deciding bar, and the exits it took.

    `per_symbol.sum(axis=1)` is `BacktestResult.turnover` bit for bit - the same diff and the same first
    row - so this is the backtest's number, not a second definition of it.
    """
    if inputs.model is None:
        raise ValueError(f"no model to replay: {inputs.problem}")
    decided, _combined, _per_strategy = inputs.model.evaluate(panel, membership)
    result, _overlaid = score_book(panel, decided, inputs.cost, guards=inputs.guards, exits=inputs.exits)
    delta = result.weights.diff()
    delta.iloc[0] = result.weights.iloc[0]
    per_symbol = delta.abs()
    bars = panel.close.index
    per_symbol.index = pd.DatetimeIndex(bars[bars.get_indexer(per_symbol.index) - 1])
    exits: set[tuple[int, str]] = set()
    if inputs.exits is not None:
        # A second pass of the overlay for its event log only; it is deterministic, so it cannot differ
        # from the pass `score_book` priced.
        events = apply_exits(decided, panel.close, inputs.exits).events
        taken = events[events["rule"] != COOLDOWN]
        stamps = _ms(pd.DatetimeIndex(taken["time"]))
        exits = {(int(ms), str(name)) for ms, name in zip(stamps, taken["symbol"], strict=True)}
    return per_symbol, exits


def replay_membership(
    index: pd.DatetimeIndex,
    columns: Sequence[str],
    recorded: Sequence[tuple[int, frozenset[str]]],
    table: pd.DataFrame | None,
) -> pd.DataFrame:
    """The universe the loop recorded on each bar, forward-filled; the point-in-time table before its first."""
    before = (
        membership_at_bars(table, index).reindex(columns=list(columns), fill_value=False).astype(float)
        if table is not None
        else pd.DataFrame(0.0, index=index, columns=list(columns))
    )
    if not recorded:
        return before.astype(bool)
    stamps = pd.DatetimeIndex([pd.Timestamp(ms, unit="ms", tz="UTC") for ms, _ in recorded])
    frame = pd.DataFrame([[float(s in names) for s in columns] for _, names in recorded], stamps, list(columns))
    return frame.reindex(frame.index.union(index)).ffill().reindex(index).fillna(before).astype(bool)


def _membership_table(root: str | Path) -> pd.DataFrame | None:
    path = Path(root) / MEMBERSHIP_FILE
    if not path.exists():
        return None
    table = pd.read_parquet(path)
    index = pd.DatetimeIndex(table.index)
    table.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return table.astype(bool)


def backtest_turnover(inputs: ReplayInputs, rows: Sequence[Mapping[str, Any]], *, since_ms: int) -> Replay:
    """Load the archive and replay the construction from far enough back that the window's state converged."""
    model = inputs.model
    if model is None:
        raise ValueError(f"no model to replay: {inputs.problem}")
    bar_ms = interval_seconds(model.interval) * 1000
    start_ms = since_ms - (model.min_history_bars + model.warmup_bars) * bar_ms - WARMUP_DAYS * DAY_MS
    recorded = sorted(
        {int(r["bar_open_ms"]): frozenset(r["universe"]) for r in rows if _bar(r) and r.get("universe")}.items()
    )
    # Every name the membership can switch on: what the loop recorded from the start on, the universe
    # already in force at the start, and - only while the replay begins before the loop's record does - the
    # point-in-time members of the stretch the record does not cover.
    names = {s for bar, universe in recorded if bar >= start_ms for s in universe}
    names |= {s for universe in [u for bar, u in recorded if bar < start_ms][-1:] for s in universe}
    uncovered = not recorded or recorded[0][0] > start_ms
    table = _membership_table(inputs.data_root) if uncovered else None
    if table is not None:
        early = table.loc[pd.Timestamp(start_ms, unit="ms", tz="UTC") - pd.Timedelta(days=1) :]
        if recorded:
            early = early.loc[: pd.Timestamp(recorded[0][0], unit="ms", tz="UTC")]
        names |= {str(symbol) for symbol in early.columns[early.any(axis=0)]}
    root = inputs.data_root
    panel = load_panel(
        KlineStore(root), sorted(names), model.interval, funding_store=FundingStore(root), start=_stamp(start_ms)
    )
    per_symbol, exits = replay_turnover(panel, replay_membership(panel.index, panel.symbols, recorded, table), inputs)
    last = {s: panel.close[s].last_valid_index() for s in panel.close.columns}
    priced_until = {str(s): int(_ms(pd.DatetimeIndex([at]))[0]) for s, at in last.items() if at is not None}
    return Replay(per_symbol, priced_until, exits, int(_ms(panel.index[:1])[0]))


def comparison_window(rows: Sequence[Mapping[str, Any]], *, window_days: int = WINDOW_DAYS) -> dict[str, Any] | None:
    """The newest run of priced cycles on one construction and one registry digest, capped at M-Q08's window.

    Both keys, because either changing makes the replay describe a different book for part of the window:
    the construction fingerprint covers the portfolio layer and the registry digest the strategies.
    """
    priced = [row for row in rows if _bar(row) and row.get("equity") is not None and row.get("registry")]
    if not priced:
        return None
    key = (canonical_construction(priced[-1].get("construction")), priced[-1].get("registry"))
    first = priced[-1]
    for row in reversed(priced):
        if (canonical_construction(row.get("construction")), row.get("registry")) != key:
            break
        first = row
    latest_ms = int(priced[-1]["bar_open_ms"])
    return {
        "since_ms": max(int(first["bar_open_ms"]), latest_ms - window_days * DAY_MS),
        "latest_ms": latest_ms,
        "registry": str(key[1]),
        "construction": str(priced[-1].get("construction") or "")[:12],
    }


def _notional(trade: Mapping[str, Any]) -> float:
    try:
        return abs(float(trade.get("executed_qty") or 0.0) * float(trade.get("avg_price") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def live_turnover(
    rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    *,
    since_ms: int,
    until_ms: int,
    priced_until: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Each fill's notional over the equity its cycle sized it from, summed per deciding bar.

    The equity is the newest priced cycle at or before the fill's bar: its own cycle, unless that cycle
    failed after placing orders and recorded none.  Operator flattens (`flatten`, `bdflat-` ids) carry no
    bar and are not the construction trading; they are left out, and the ones whose wall clock falls in
    the window are counted, because the rebuild after one is loop trading and shows up as a spike.  A fill
    the backtest side cannot price (`priced_until`) goes to `excluded` by symbol.  Each venue order is
    counted once (`one_row_per_order`): a restart's "already submitted" row is the same fill again.
    """
    sized = sorted((int(row["bar_open_ms"]), float(row["equity"])) for row in rows if _bar(row) and row.get("equity"))
    bars = [bar for bar, _ in sized]
    by_bar: dict[int, float] = {}
    excluded: dict[str, float] = {}
    flattens = unsized = 0
    for trade in one_row_per_order(trades):
        if trade.get("flatten"):
            try:
                at_ms = int(pd.Timestamp(str(trade.get("at"))).timestamp() * 1000)
            except ValueError:
                continue
            flattens += 1 if since_ms <= at_ms <= until_ms else 0
            continue
        if not _bar(trade) or not since_ms <= int(trade["bar_open_ms"]) <= until_ms or _notional(trade) <= 0:
            continue
        bar, position = int(trade["bar_open_ms"]), bisect_right(bars, int(trade["bar_open_ms"])) - 1
        if position < 0 or sized[position][1] <= 0:
            unsized += 1
            continue
        share, symbol = _notional(trade) / sized[position][1], str(trade.get("symbol") or "")
        if priced_until is not None and bar > priced_until.get(symbol, -1):
            excluded[symbol] = excluded.get(symbol, 0.0) + share
        else:
            by_bar[bar] = by_bar.get(bar, 0.0) + share
    return {"by_bar": by_bar, "excluded": excluded, "flatten_fills": flattens, "unsized_fills": unsized}


def by_day(live: Mapping[int, float], backtest: Mapping[int, float]) -> list[dict[str, Any]]:
    """Both sides summed per UTC day of the deciding bar; `bars` counts the bars the backtest priced."""
    days: dict[str, dict[str, Any]] = {}
    for side, series in (("live", live), ("backtest", backtest)):
        for bar, value in series.items():
            day = days.setdefault(str(_stamp(bar))[:10], {"live": 0.0, "backtest": 0.0, "bars": 0})
            day[side] += value
            day["bars"] += 1 if side == "backtest" else 0
    return [{"day": day, **values} for day, values in sorted(days.items())]


def paired_ratio(days: Sequence[tuple[float, float]]) -> tuple[float | None, float | None]:
    """Sum-over-sum ratio with its linearised standard error, days as the pairs (Cochran's ratio estimator).

    Pairing by day is what "the same period" buys: both sides answer the same market, so the error is in
    how the two disagree day by day rather than in how much the market moved.
    """
    live, backtest = sum(pair[0] for pair in days), sum(pair[1] for pair in days)
    if backtest <= 0:
        return None, None
    ratio = live / backtest
    if len(days) < 2:
        return ratio, None
    spread = sum((a - ratio * b) ** 2 for a, b in days) / (len(days) * (len(days) - 1))
    return ratio, math.sqrt(spread) / (backtest / len(days))


def _exits_taken(rows: Sequence[Mapping[str, Any]]) -> set[tuple[int, str]]:
    """(deciding bar, symbol) of every exit the loop recorded; a cooldown bar is not an exit."""
    return {
        (int(row["bar_open_ms"]), str(event.get("symbol")))
        for row in rows
        if _bar(row)
        for event in row.get("exit_events") or []
        if isinstance(event, Mapping) and event.get("rule") not in (None, COOLDOWN)
    }


def turnover_fidelity(
    rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    inputs: ReplayInputs | None,
    *,
    min_complete_days: int = MIN_COMPLETE_DAYS,
) -> dict[str, Any]:
    """M-Q08's first clause: live turnover over the backtest's, same bars, same construction, ±25%."""
    band = [1.0 - TURNOVER_BAND, 1.0 + TURNOVER_BAND]
    window = comparison_window(rows)
    if inputs is None or inputs.model is None:
        missing = "这次报告没拿到 registry 与 profile" if inputs is None else str(inputs.problem)
        return {"enforced": False, "band": band, "why": f"重放的模型建不起来：{missing}"}
    if window is None:
        return {"enforced": False, "band": band, "why": "没有记下构造与 registry digest 的已成交周期"}
    if inputs.registry_on_disk != window["registry"]:
        return {
            "enforced": False,
            "band": band,
            "why": f"磁盘上的 registry（{inputs.registry_on_disk}）不是循环在跑的那份（{window['registry']}），"
            "重放描述的不是这本书",
        }
    since_ms = int(window["since_ms"])
    try:
        replay = backtest_turnover(inputs, rows, since_ms=since_ms)
    # Broad, and here as well as around the whole block: the replay reads the archive and runs the model,
    # the part most likely to break, and its failure should blind this clause and not the other readings.
    except Exception as error:
        return {"enforced": False, "band": band, "why": f"重放失败：{type(error).__name__}: {error}"}
    decision_ms = _ms(pd.DatetimeIndex(replay.turnover.index))
    until_ms = min(int(window["latest_ms"]), int(decision_ms.max()) if len(decision_ms) else since_ms - 1)
    if until_ms < since_ms:
        return {"enforced": False, "band": band, "why": f"归档还没有覆盖这个构造的第一根 bar（{_stamp(since_ms)}）"}
    inside_window = (decision_ms >= since_ms) & (decision_ms <= until_ms)
    cells, cell_ms = replay.turnover.loc[inside_window], decision_ms[inside_window]
    priced = pd.DataFrame({s: cell_ms <= replay.priced_until.get(str(s), -1) for s in cells.columns}, index=cells.index)
    backtest_by_bar = dict(zip(cell_ms.tolist(), cells.where(priced, 0.0).sum(axis=1).tolist(), strict=True))
    live = live_turnover(rows, trades, since_ms=since_ms, until_ms=until_ms, priced_until=replay.priced_until)
    days = by_day(live["by_bar"], backtest_by_bar)
    complete = sum(1 for row in days if row["bars"] >= DAY_MS // (interval_seconds(inputs.model.interval) * 1000))
    ratio, se = paired_ratio([(row["live"], row["backtest"]) for row in days])
    live_exits = {
        (bar, symbol)
        for bar, symbol in _exits_taken(rows)
        if since_ms <= bar <= min(until_ms, replay.priced_until.get(symbol, -1))
    }
    backtest_exits = {(bar, symbol) for bar, symbol in replay.exits if since_ms <= bar <= until_ms}
    edge = band[1] if ratio is not None and ratio >= 1.0 else band[0]
    enforced = ratio is not None and complete >= min_complete_days
    why = None
    if ratio is None:
        why = "回测在这段时间没有换手，比值无定义"
    elif not enforced:
        why = f"同一构造下只有 {complete} 个完整日，要 {min_complete_days} 个才判定"
    return {
        "enforced": enforced,
        "why": why,
        "ratio": ratio,
        "se": se,
        "band": band,
        "inside": None if ratio is None else band[0] <= ratio <= band[1],
        # Beside the verdict, as the slippage clause carries it: is the distance to the nearest edge of the
        # band larger than two of the ratio's own error bars?
        "decisive": None if ratio is None or se is None else abs(ratio - edge) > 2.0 * se,
        "live": sum(row["live"] for row in days),
        "backtest": sum(row["backtest"] for row in days),
        "since": _stamp(since_ms),
        "until": _stamp(until_ms),
        "construction": window["construction"],
        "registry": window["registry"],
        "complete_days": complete,
        "by_day": days,
        "exits": {"live": len(live_exits), "backtest": len(backtest_exits), "both": len(live_exits & backtest_exits)},
        "unpriced": {
            symbol: {"archive_ends": _stamp(replay.priced_until.get(symbol)), "live_turnover_excluded": share}
            for symbol, share in sorted(live["excluded"].items())
        },
        "flatten_fills": live["flatten_fills"],
        "unsized_fills": live["unsized_fills"],
        "replay_from": _stamp(replay.replay_from_ms),
    }


def registry_reading(rows: Sequence[Mapping[str, Any]], on_disk: str | None) -> dict[str, Any]:
    """M-Q08's fourth clause as a report can read it: the loop's digest against the file's, now.

    Whether the file matched the loop at a PAST hour was never recorded, so this is the comparison `live
    status --check` makes hourly, plus how many registries the loop held in the window.  A change is not
    an inconsistency: a restart, a quarantined symbol and a stopped book all move the digest.
    """
    stamped = [row for row in rows if _bar(row) and row.get("registry")]
    if not stamped:
        return {"loop": None, "on_disk": on_disk, "consistent": None, "why": "没有周期记录过 registry digest"}
    loop, latest_ms = str(stamped[-1]["registry"]), int(stamped[-1]["bar_open_ms"])
    since = stamped[-1]
    for row in reversed(stamped):
        if str(row["registry"]) != loop:
            break
        since = row
    recent = {str(row["registry"]) for row in stamped if int(row["bar_open_ms"]) >= latest_ms - WINDOW_DAYS * DAY_MS}
    return {
        "loop": loop,
        "on_disk": on_disk,
        "consistent": None if on_disk is None else on_disk == loop,
        "loop_digest_since": _stamp(int(since["bar_open_ms"])),
        "digests_in_window": len(recent),
    }


def slippage_by_week(
    rows: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]], *, weeks: int = TREND_WEEKS
) -> list[dict[str, Any]]:
    """Slippage against the decision close, by UTC week of the deciding bar: mean, standard error and n.

    `slippage_bps`'s arithmetic (`_weighted`: notional-weighted, Kish n_eff) and its split rule,
    `fill_grouper`: each fill by the books of its own cycle and the one before.  Until the operator's G9
    ruling (2026-09-23) the judged reading split all 30 days by the newest cycle's map instead, and this
    trend was the one reader that did not; now both read one rule.  A fill that cannot be attributed is
    counted in `unsplit` and stays in `combined`.  The fills are `slippage_bps`'s: each order once.
    """
    group_of = fill_grouper(books_by_bar(rows))
    buckets: dict[str, dict[str, Any]] = {}
    for trade in one_row_per_order(trades):
        try:
            reference, filled, quantity = (float(trade[k]) for k in ("decision_close", "avg_price", "executed_qty"))
        except (KeyError, TypeError, ValueError):
            continue
        if trade.get("flatten") or not _bar(trade) or min(reference, filled, quantity) <= 0:
            continue
        side = 1.0 if str(trade.get("side", "")).upper() == "BUY" else -1.0
        fill = (side * (filled - reference) / reference * 10_000.0, filled * quantity)
        bar = pd.Timestamp(int(trade["bar_open_ms"]), unit="ms", tz="UTC")
        week = str((bar - pd.Timedelta(days=bar.weekday())).date())
        bucket = buckets.setdefault(week, {"combined": ([], []), "main_only": ([], []), "unsplit": 0})
        group = group_of(int(trade["bar_open_ms"]), str(trade.get("symbol")))
        populations = ["combined"]
        if group == "unattributed":
            bucket["unsplit"] += 1
        elif group == "main_only":
            populations.append("main_only")
        for name in populations:
            bucket[name][0].append(fill[0])
            bucket[name][1].append(fill[1])
    return [
        {
            "week": week,
            "combined": _weighted(*bucket["combined"]),
            "main_only": _weighted(*bucket["main_only"]) if bucket["main_only"][0] else None,
            "unsplit": bucket["unsplit"],
        }
        for week, bucket in sorted(buckets.items())[-weeks:]
    ]


def execution_fidelity(store: StateStore, inputs: ReplayInputs | None) -> dict[str, Any]:
    """The daily report's M-Q08 block: the two clauses that had no reader, and slippage as a trend.

    The catch is broad for the reason `market_beta` gives.  This runs inside the hourly check, and a
    reading that judges nothing must not take the rest of the report down with it - nor every alert in
    it, which is what an uncaught exception here would silence.  The failure stays visible: the block
    carries its type and message, and `fidelity_lines` prints them.  The rows are those `reports._cycles`
    keeps (a failed or dry-run cycle is not a bar that traded), read here so the reads are inside it too.
    """
    try:
        cycles = store.read_jsonl(store.cycles_path)
        rows = [row for row in cycles if row.get("equity") is not None and not row.get("dry_run")]
        trades = store.read_jsonl(store.trades_path)
        return {
            "turnover": turnover_fidelity(rows, trades, inputs),
            "registry": registry_reading(rows, None if inputs is None else inputs.registry_on_disk),
            "slippage_by_week": slippage_by_week(rows, trades),
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _bps(block: Mapping[str, Any] | None) -> str:
    if not block or block.get("value") is None:
        return "无"
    se = "" if block.get("se") is None else f"±{block['se']:.1f}"
    return f"{block['value']:.1f}{se} bps（{block.get('fills')} 笔）"


def _registry_line(block: Mapping[str, Any]) -> str:
    if block.get("loop") is None:
        return f"读不出（{block.get('why')}）"
    agreement = {True: "一致", False: "不一致", None: "这次没拿到磁盘上的 digest"}[block.get("consistent")]
    return (
        f"{block['loop']} / {block.get('on_disk')}，{agreement}；近 {WINDOW_DAYS} 天循环跑过 "
        f"{block.get('digests_in_window')} 份，这份自 {block.get('loop_digest_since')}"
    )


def fidelity_lines(payload: Mapping[str, Any]) -> dict[str, Any]:
    """M-Q08's four clauses in one place: two read here, two quoted from the blocks that judge them."""
    block = payload.get("execution_fidelity") or {}
    if not block:
        return {"none": 0}
    if block.get("error"):
        return {"读不出，这一块整块失败": block["error"]}
    turnover, registry = block.get("turnover") or {}, block.get("registry") or {}
    slippage = (payload.get("risk_budget") or {}).get("slippage") or {}
    late = (payload.get("restarts") or {}).get("late_cycle_share")
    ratio, se, band = turnover.get("ratio"), turnover.get("se"), turnover.get("band") or [0.0, 0.0]
    if ratio is None:
        ratio_line = f"读不出（{turnover.get('why')}）"
    else:
        verdict = f"带{'内' if turnover.get('inside') else '外'}" if turnover.get("enforced") else "未判定"
        noise = "" if se is None else f"±{se:.2f}，{'可分辨' if turnover.get('decisive') else '与噪声不可分辨'}"
        ratio_line = (
            f"{ratio:.2f}（{noise}；带 {band[0]:.2f}–{band[1]:.2f}，{verdict}"
            + (f"：{turnover['why']}" if turnover.get("why") else "")
            + f"）；实盘 {turnover['live']:.3f} / 回测 {turnover['backtest']:.3f} 倍权益，"
            f"决策 bar {turnover.get('since')} 至 {turnover.get('until')}"
        )
    exits = turnover.get("exits") or {}
    lines: dict[str, Any] = {
        "换手 实盘/回测同期（±25%）": ratio_line,
        "换手分日 实盘/回测": "；".join(
            f"{row['day'][5:]} {row['live']:.3f}/{row['backtest']:.3f}" for row in turnover.get("by_day") or []
        )
        or "无",
        "窗口内退出 实盘/回测/两边都有": f"{exits.get('live')}/{exits.get('backtest')}/{exits.get('both')}"
        if exits
        else "无",
        "归档够不着、两边都剔除的": "；".join(
            f"{symbol} 归档止于 {row['archive_ends']}，剔除实盘 {row['live_turnover_excluded']:.3f}"
            for symbol, row in (turnover.get("unpriced") or {}).items()
        )
        or "无",
        # Quoted, not recomputed: the verdict on these two lives in the blocks that judge them.
        "滑点（判定读数，见 Risk budget）": f"{_bps(slippage)}，限 {slippage.get('limit')} bps，"
        + ("未判定" if not slippage.get("enforced") else f"带{'内' if slippage.get('inside') else '外'}"),
        "迟到周期（今日，见 Restart cost）": "无可判周期" if late is None else f"{late:.1%}（限 5%）",
        "registry digest 循环/磁盘": _registry_line(registry),
    }
    for week in block.get("slippage_by_week") or []:
        unsplit = f"；{week['unsplit']} 笔的周期没记 books，无法分书" if week.get("unsplit") else ""
        lines[f"滑点 {week['week']} 起一周"] = (
            f"全书 {_bps(week.get('combined'))}；主书独有 {_bps(week.get('main_only'))}{unsplit}"
        )
    return lines


def fidelity_notices(payload: Mapping[str, Any]) -> list[str]:
    """A notice, never a page: M-Q08's registered failure action is "复审执行层", a review, not an hour's work."""
    turnover = (payload.get("execution_fidelity") or {}).get("turnover") or {}
    if not turnover.get("enforced") or turnover.get("inside") is not False:
        return []
    exits, se = turnover.get("exits") or {}, turnover.get("se")
    noise = "" if se is None else f"（±{se:.2f}，{'可分辨' if turnover.get('decisive') else '与噪声不可分辨'}）"
    return [
        f"M-Q08 换手偏离：实盘/回测同期 {turnover['ratio']:.2f}{noise}，超出 {turnover['band'][0]:.2f}–"
        f"{turnover['band'][1]:.2f}；{turnover.get('complete_days')} 个完整日，退出 实盘 {exits.get('live')} / "
        f"回测 {exits.get('backtest')}；失败动作：复审执行层"
    ]


__all__ = ["ReplayInputs", "execution_fidelity", "fidelity_lines", "fidelity_notices"]
