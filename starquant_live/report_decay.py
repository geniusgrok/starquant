"""Is the edge still there: the readings that hold the live series against its evidence.

Checklist areas #1.10 (edge decay monitoring) and #4.10 (signal monitoring dashboard) of
`docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`, and the automatic part of D.3
(when to stop): equity and income drift (M-002 / M-010), the decay rule (G1), M-G06, the coverage of
the attribution series under them (O3), and the probe books' stop and review (D-019, M-014).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np

from starquant_alpha.validation.metrics import DECAY_WINDOW_DAYS, max_drawdown, newey_west_tstat, sharpe, window_sharpes
from starquant_live.probe import ProbeParams, probe_status
from starquant_live.report_common import _cycles, _fmt_num, _parsed, evidence_window, json_dumps, readable_state
from starquant_live.state import StateStore


def expectations_from_evidence(evidence_by_strategy: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What the validation reports promised: OOS Sharpe, full-sample Sharpe/MDD per strategy."""
    out: dict[str, Any] = {}
    for strategy, report in evidence_by_strategy.items():
        verdict = report.get("verdict")
        if str(report.get("kind", "")) == "book":  # a probe book (D-019): expectations are the sleeve's own numbers
            universes = report.get("universes", {}) or {}
            decision = universes.get(str(report.get("universe_mode", "")), {}) or {}
            standalone = decision.get("sleeve_standalone", {}) or {}
            wf = standalone.get("walk_forward", {}) or {}
            full = standalone.get("full_sample", {}) or {}
            verdict = f"{report.get('book_verdict')}/book (sleeve {standalone.get('verdict')})"
        else:
            wf = report.get("walk_forward", {}) or {}
            full = report.get("full_sample", {}) or {}
        out[strategy] = {
            "oos_sharpe": wf.get("oos_sharpe"),
            # The decay rule's comparison distribution, carried from the same evidence run as the Sharpe
            # above so the two can never describe different constructions (report 4.2 Ⅰ).  Absent from
            # every report written before 2026-09-07, which is why `decay_watch` reads INSUFFICIENT_DATA
            # until each strategy's evidence is next re-run.
            "oos_window_sharpe_q10": wf.get("oos_window_sharpe_q10"),
            "full_sample_sharpe": full.get("annualized_sharpe"),
            "full_sample_max_drawdown": full.get("max_drawdown"),
            "verdict": verdict,
        }
    return out


def probe_rows(
    store: StateStore, probes: Sequence[ProbeParams], *, equity: float | None, now_ms: int
) -> list[dict[str, Any]]:
    """Status of every probe book (D-019) from the attribution file and the persisted stop records."""
    if not probes:
        return []
    attributions = store.read_jsonl(store.attribution_path)
    cycles = store.read_jsonl(store.cycles_path)  # `book_weights` + `closes`, for the second caliber
    stopped = readable_state(store)[0].stopped_books
    rows: list[dict[str, Any]] = []
    for probe in probes:
        status = probe_status(probe, attributions, equity=equity, now_ms=now_ms, cycles=cycles)
        if probe.book in stopped:
            status = {**status, "status": "STOPPED", "stopped": stopped[probe.book]}
        rows.append(status)
    return rows


def attribution_coverage(store: StateStore) -> dict[str, Any]:
    """O3: does `attribution.jsonl` still meet itself end to end, or has a stretch gone missing?

    M-010 is the only clean out-of-sample evidence KILL-006 recognises, and every number in it comes
    out of this one append-only file.  The file can lose a block with nothing saying so: `state.py`
    hands back an empty state when `state.json` fails to parse, `engine.py`'s
    ``since = self.state.last_income_ms or now`` then becomes *now*, and the income earned while the
    loop was away is never queried at all.  What `decay_watch` sees afterwards is a SHORTER window -
    which reads as "less evidence so far", not as "a hole in the middle".  Those are different
    claims and only one of them is true.

    Every row already carries the venue-clock window it ingested (``since_ms`` / ``until_ms``) and
    nothing had ever compared one row's end to the next row's start.  This does:

        covered_ms / span_ms   the union of those windows, over the span they lie in
        gap_count              how many times a row starts after the previous one ended

    **`coverage` is not a health score, and on the live record it reads 0.18.**  A row is written
    only by a cycle that HAD income, so an hour in which the book realised nothing, paid no
    commission and settled no funding leaves no row at all while its income window WAS queried.
    Measured 2026-09-13 over the live file: 42 rows, span 213.0 h, union 37.3 h, 31 gaps, the widest
    18.0 h - and not one of them lost a cent.

    The number built for the question is ``largest_gap_without_a_cycle_ms``.  A gap the loop ran
    through was ingested, because the cycle at its right edge queried across the whole of it; a gap
    with no completed cycle inside it was not.  That reads 1.00 h today, which is one cycle period:
    a single quiet hour leaves a gap with nothing strictly inside it, and at one period wide that
    shape cannot be told from an hour of downtime.  A wiped watermark over a real outage is many
    periods wide, and shows up here as exactly that.

    Reported, never enforced.  It carries no threshold and `report daily --check` must not learn to
    exit non-zero on it: the first version of this reading would have called 31 gaps a fault.  When
    it cannot be computed it says so and returns no number (D-035) - above all it never reads 1.0.
    """
    windows: list[tuple[int, int]] = []
    unreadable = 0
    for row in store.read_jsonl(store.attribution_path):
        since, until = row.get("since_ms"), row.get("until_ms")
        if not isinstance(since, int | float) or not isinstance(until, int | float) or until < since:
            unreadable += 1
            continue
        windows.append((int(since), int(until)))
    block: dict[str, Any] = {
        "enforced": False,
        "reason": None,
        "rows": len(windows),
        "unreadable_rows": unreadable,
        "first_since_ms": None,
        "last_until_ms": None,
        "span_ms": None,
        "covered_ms": None,
        "coverage": None,
        "gap_count": None,
        "gap_ms": None,
        "largest_gap_ms": None,
        "overlap_count": None,
        "gaps_without_a_cycle": None,
        "largest_gap_without_a_cycle_ms": None,
    }
    if len(windows) < 2:
        # One window covers itself, so `covered / span` would read exactly 1.0 - and a file reduced
        # to one row is what the failure this instrument watches for LOOKS like.  "Cannot tell" is
        # the honest answer; this is the one place where defaulting to 1.0 is worse than no number.
        return {**block, "reason": f"{len(windows)} readable attribution row(s); fewer than 2 cannot be met end to end"}
    windows.sort()
    gaps: list[tuple[int, int]] = []
    overlaps = covered = 0
    start, end = windows[0]
    for since, until in windows[1:]:
        if since > end:
            gaps.append((end, since))
            covered += end - start
            start, end = since, until
            continue
        # An overlap is not a gap but it is not nothing either: the same income rows were queried
        # twice, and `attribute` would have counted them twice.  Counted, not merged away.
        overlaps += 1 if since < end else 0
        end = max(end, until)
    covered += end - start
    span = end - windows[0][0]
    if span <= 0:
        return {**block, "reason": "every readable row carries the same instant; there is no span to cover"}
    # The loop's own wall clock, not `bar_open_ms`: across the 2026-09-04 restarts several cycles
    # carry the SAME bar minutes apart, so bar time cannot say whether the loop was alive inside a
    # gap - and with bar time this reading called a benign 21-minute restart gap unexplained.
    ran_at = sorted(
        int(moment.timestamp() * 1000) for row in _cycles(store) if (moment := _parsed(row.get("at"))) is not None
    )
    unexplained = [(a, b) for a, b in gaps if not any(a < moment < b for moment in ran_at)]
    return {
        **block,
        "enforced": True,
        "first_since_ms": windows[0][0],
        "last_until_ms": end,
        "span_ms": span,
        "covered_ms": covered,
        "coverage": covered / span,
        "gap_count": len(gaps),
        "gap_ms": span - covered,
        "largest_gap_ms": max((b - a for a, b in gaps), default=0),
        "overlap_count": overlaps,
        "gaps_without_a_cycle": len(unexplained),
        "largest_gap_without_a_cycle_ms": max((b - a for a, b in unexplained), default=0),
    }


def _series_by_strategy(store: StateStore, since_ms: int | None) -> dict[str, list[tuple[int, float]]]:
    """Attributed P&L per strategy, ON THE CYCLE GRID - one point per completed cycle, zero where
    that cycle attributed nothing to that strategy.

    An attribution row is written only by a cycle that had income, and both readers of this series
    (`income_drift` for M-002/M-010, `long_run_attribution` for M-G06) annualise it at 8760 bars a
    year and read its length as `size / 24` days.  Measured 2026-09-12 over the 214 cycles the
    attribution record spans: 41 rows for tsmom (19% of cycles) and 25 for flow (12%).  So the series
    was 5x shorter than the hours it covered and every gap - a true zero, since these rows carry only
    realised P&L, commission and funding - had been deleted from it:

        tsmom   days read 1.71 against 8.92 actual;  annualised Sharpe -15.84 against -6.78 (2.33x)
        flow    days read 1.04 against 8.92 actual;  annualised Sharpe  -2.38 against -0.77 (3.08x)

    The inflation is exactly sqrt(cycles/rows) (2.28 and 2.93 predicted): dropping the zeros leaves the
    sum alone and shrinks the count, so the mean rises faster than the standard deviation.  The sign is
    untouched, which is why M-G06 - a point estimate >= 0 and nothing else - would have ruled the same
    either way; M-010 compares against a FIXED expected Sharpe, and that comparison was not safe.

    The grid is bounded by the attribution record's own span.  Zero-filling back to the first cycle
    would assert "no income" over a period when nothing was writing income rows at all.
    """
    attributed: dict[str, dict[int, float]] = {}
    covered: list[int] = []
    for row in store.read_jsonl(store.attribution_path):
        bar = row.get("bar_open_ms")
        if not isinstance(bar, int | float):
            continue
        covered.append(int(bar))
        for strategy, value in (row.get("by_strategy") or {}).items():
            try:
                attributed.setdefault(str(strategy), {})[int(bar)] = float(value)
            except (TypeError, ValueError):
                continue
    if not attributed or not covered:
        return {}
    first, last = min(covered), max(covered)
    grid = sorted(
        {
            int(row["bar_open_ms"])
            for row in store.read_jsonl(store.cycles_path)
            if not row.get("dry_run")
            and isinstance(row.get("bar_open_ms"), int | float)
            and first <= int(row["bar_open_ms"]) <= last
            and (since_ms is None or int(row["bar_open_ms"]) >= since_ms)
        }
    )
    if not grid:  # a record with attribution but no readable cycle rows: report what there is
        grid = sorted({bar for bars in attributed.values() for bar in bars if since_ms is None or bar >= since_ms})
    return {strategy: [(bar, bars.get(bar, 0.0)) for bar in grid] for strategy, bars in sorted(attributed.items())}


def income_drift(
    store: StateStore,
    expectations: dict[str, Any],
    *,
    equity: float | None,
    since_ms: int | None,
    bars_per_year: float = 8760.0,
) -> dict[str, Any]:
    """M-002 / M-010: each strategy's realised Sharpe from *attributed income*, against its own expectation.

    The equity-based `drift_check` cannot do this.  Equity here is multi-asset collateral, so it moves
    with BTC even when the book is flat (KILL-033), and it is one number for a book that runs a main
    strategy plus a probe sleeve.  Income rows are per strategy and hold realised P&L, commission and
    funding only - NOT the backtest's caliber, which marks every bar to market (`w_{t-1} . r_t`).  On
    2026-09-12 flow's 30-day sigma read 0.137% of equity realised, 3.239% marked (`probe.py:128`).
    Operator ruling A, 2026-09-23: kept, labelled as two calibers; no computation or alert changed.
    """
    if not equity or equity <= 0:
        return {"status": "INSUFFICIENT_DATA", "reason": "no equity"}
    rows: dict[str, Any] = {}
    status = "OK"
    for strategy, points in sorted(_series_by_strategy(store, since_ms).items()):
        values = np.asarray([value / equity for _bar, value in points], dtype=float)
        expected = (expectations.get(strategy) or {}).get("oos_sharpe")
        realised = sharpe(values, bars_per_year) if _has_dispersion(values) else None
        days = values.size / 24.0
        z = None
        if realised is not None and expected is not None:
            z = (realised - expected) / math.sqrt(365.0 / max(days, 1.0))
            if z < -2.0:
                status = "ALERT"
        rows[strategy] = {
            "bars": int(values.size),
            "days": round(days, 2),
            "realised_sharpe": realised,
            "expected_sharpe": expected,
            "z": z,
            "pnl": float(values.sum() * equity),
        }
    if not rows or all(row["realised_sharpe"] is None for row in rows.values()):
        status = "INSUFFICIENT_DATA"
    return {"status": status, "by_strategy": rows}


def decay_watch(
    store: StateStore,
    expectations: dict[str, Any],
    *,
    equity: float | None,
    window_days: int = DECAY_WINDOW_DAYS,
    bars_per_year: float = 8760.0,
) -> dict[str, Any]:
    """Per strategy, the adopted decay rule against the live record of the CURRENT construction.

    The windows are `window_days` of hourly bars and they start where M-010's does: `evidence_window`,
    so an aliased digest (`CONSTRUCTION_ALIASES`) carries them on and a real construction change starts
    them over.  §12.9 ruled exactly that - "构造一变，q10 必须重算，与 M-010 的清零语义一致" - because q10
    describes the construction its evidence run measured, and a live window from another construction
    has nothing to be compared against.  Until 2026-09-23 this read from bar zero instead.  On the live
    record that day the first window would have opened 2026-09-03T06:00Z, two weeks before the current
    construction, and its 478 bars so far spanned five canonical constructions (vol_target 0.30 and
    0.60, D3's band knobs off and on) plus 27 cycles from before any fingerprint.  Nobody saw it only
    because no whole window existed yet under either reading.

    `q10` is looked up on the strategy's own evidence block.  Reports written before 2026-09-07 lack
    it; both reports the registry cites carry it (checked 2026-09-23), so the half that can still be
    missing is the live one - two whole windows are needed - and the row says which half it is.  That
    reading must stay visible either way: a blank row would be read as "fine".  q10 is marked to market
    and the live windows are realised, the two calibers `income_drift` names; ruling A keeps it, labelled.
    """
    bars = int(window_days * 24)
    rows: dict[str, Any] = {}
    since_ms = evidence_window(store)["since_ms"]
    for strategy, points in sorted(_series_by_strategy(store, since_ms).items()):
        if not equity or equity <= 0:
            rows[strategy] = {"status": "INSUFFICIENT_DATA", "why": "no equity", "below": 0}
            continue
        returns = [value / equity for _bar, value in points]
        windows = window_sharpes(returns, bars_per_window=bars, bars_per_year=bars_per_year)
        q10 = (expectations.get(strategy) or {}).get("oos_window_sharpe_q10")
        verdict = decay_verdict(live_windows=windows, q10=q10)
        rows[strategy] = verdict | {"whole_windows": len(windows), "window_days": window_days, "bars": len(points)}
    return rows


def decay_verdict(*, live_windows: Sequence[float | None], q10: float | None, consecutive: int = 2) -> dict[str, Any]:
    """The edge-decay rule adopted 2026-09-07 (report 4.2 Ⅰ; ruling in 12.9).

    Two consecutive non-overlapping 30-day windows whose live Sharpe sits below the backtest's q10 for
    windows of the same length -> REVIEW.  The comparison is to an EMPIRICAL distribution, not to
    ``oos_sharpe`` with a normal standard error: a 1.7-Sharpe strategy has enormous 30-day dispersion, so
    its q10 is likely well below zero, and the point-estimate test is much weaker.  That weaker test still
    exists as `drift_vs_expectation`; the two coexist and answer different questions.

    A missing ``q10`` is INSUFFICIENT_DATA and never OK.  The quantile must come from the same
    construction, so it dies with every construction change exactly as M-010's window does; reporting OK
    while there is nothing to compare against is how a detector that has never worked looks healthiest.
    """
    usable = [value for value in live_windows if value is not None]
    if q10 is None:
        return {"status": "INSUFFICIENT_DATA", "why": "no q10 for this construction yet", "below": 0}
    if len(usable) < consecutive:
        return {
            "status": "INSUFFICIENT_DATA",
            "why": f"{len(usable)} whole windows, needs {consecutive}",
            "below": 0,
        }
    tail = usable[-consecutive:]
    below = sum(1 for value in tail if value < q10)
    status = "REVIEW" if below == consecutive else "OK"
    return {"status": status, "below": below, "q10": q10, "windows": tail}


def _decay_alerts(block: Mapping[str, Any]) -> list[str]:
    """The paging half of §12.9, and the reason the rule reached the hourly check at all (G1, 2026-09-23).

    Until then the rule's one reader was `report weekly`, which no job runs, so a REVIEW would have been
    computed and read by nobody.  Only REVIEW pages.  INSUFFICIENT_DATA is what the rule reads for its
    first sixty days under EVERY construction - two whole windows are its minimum - so it is rendered
    and never routed, not even as a notice: M-G06's reason, a finding repeated hourly for two months
    is not a finding.  OK needs no line.
    """
    return [
        f"衰减规则判 REVIEW（§12.9）：{strategy} 最近两个不重叠的 {row.get('window_days')} 天窗口，"
        f"归因夏普 {'、'.join(f'{float(value):.2f}' for value in row.get('windows') or [])} "
        f"都低于回测 q10 {float(row['q10']):.2f}（已实现对盯市，口径不同）；窗口从当前构造起算；动作：复审这条策略"
        for strategy, row in sorted(block.items())
        if str(row.get("status")) == "REVIEW"
    ]


def _decay_lines(payload: Mapping[str, Any]) -> dict[str, Any]:
    """§12.9 in the daily report: the weekly's reading verbatim, its two calibers, what it still waits for.

    Beside each strategy go its q10 and a countdown in bars, because INSUFFICIENT_DATA is the reading
    for sixty days after every construction change and "0 whole windows" alone cannot tell a rule that
    is filling from one that is stuck.  The date is a floor: a missed bar only pushes it later.
    """
    block = payload.get("decay") or {}
    if not block:
        return {"none": "no attributed income yet"}
    window = payload.get("evidence_window") or {}
    since = window.get("since_ms")
    lines: dict[str, Any] = {
        "windows_start": f"{_utc_minute(since)}（构造 {window.get('construction')}，与 M-010 同一起点）"
        if since is not None
        else "没有构造指纹，窗口从第一根记录起算",
        "口径": "实盘窗口是已实现归因，q10 是回测盯市。口径不同，比较保留（2026-09-23 操作者裁定 A）。"
        "flow 的 30 天 σ 在 09-12 读数：已实现 0.137%，盯市 3.239%",
    }
    for strategy, row in sorted(block.items()):
        needed = 2 * int(row.get("window_days") or DECAY_WINDOW_DAYS) * 24  # §12.9's "连续两个"
        q10 = ((payload.get("expectations") or {}).get(strategy) or {}).get("oos_window_sharpe_q10")
        lines[str(strategy)] = (
            str(row.get("status"))
            + (f" - {row['why']}" if row.get("why") else f" ({row.get('below')}/2 below q10)")
            + f"；q10={_fmt_num(q10)}；bars {row.get('bars')}/{needed}"
            + (f"；windows {json_dumps(row['windows'])}" if row.get("windows") else "")
            + (
                f"；不早于 {_utc_minute(since + needed * 3_600_000)}"
                if since is not None and int(row.get("bars") or 0) < needed
                else ""
            )
        )
    return lines


def _utc_minute(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%MZ")


M_G06_WINDOW_MONTHS = 18  # §19 Q2's lagging criterion; not a dial, and shortening it is not an option


def _plus_months(stamp: datetime, months: int) -> datetime:
    """Calendar months, clamped to the shorter month (there is no 31st of February)."""
    total = stamp.month - 1 + months
    year, month = stamp.year + total // 12, total % 12 + 1
    last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return stamp.replace(year=year, month=month, day=min(stamp.day, last[month - 1]))


def long_run_sharpe(
    store: StateStore,
    *,
    equity: float | None,
    now: datetime | None = None,
    window_months: int = M_G06_WINDOW_MONTHS,
    bars_per_year: float = 8760.0,
) -> dict[str, Any]:
    """M-G06: per strategy, the attributed annualised Sharpe over an unbroken 18-month construction.

    §19 Q2 (2026-09-08) split "持续盈利" in two.  M-010 is the leading half and `income_drift` is where
    it lives; this is the lagging half, and until 2026-09-09 it was the one row of the metrics table
    with no code at all.  Every clause below is quoted from that ruling rather than chosen here:

    * **Per strategy, in M-010's units.**  Attributed P&L from the income rows over the day's equity -
      literally `income_drift`'s own series - because §19 says the two must be comparable, and equity
      cannot do it: this account is multi-asset collateral, so equity moves with BTC while the book is
      flat (KILL-033), and it is one number for a main sleeve plus a probe sleeve.  A single equity
      denominator across eighteen months is an approximation, and it is M-010's approximation; using a
      better one here would buy accuracy at the cost of the only thing the ruling asked for.
    * **Timed by `canonical_construction`.**  `evidence_window` already answers this, aliases included,
      so a renamed fingerprint field cannot restart the clock (it moved three times in one day).
    * **Point estimate >= 0, and nothing else.**  `nw_t` is computed and reported and decides nothing,
      which is the disposition D-P2 gave t.  Eighteen months buys a Sharpe standard error of about
      0.82, so a passing sleeve with |t| < 2 is the EXPECTED outcome; gating on t would make M-G06
      unreachable, i.e. would turn the lagging criterion off while appearing to strengthen it.
    * **Failure action "该策略退出 main"**, carried on the row rather than left in the plan.

    Elapsed time is counted in BARS UNDER THE CONSTRUCTION (`bars / 24`), the same reading the audit
    quotes for M-010 as "5.00/30 天".  A wall clock would let eighteen months pass while the loop was
    down and call that evidence.  The calendar is still reported beside it - `calendar_days` and the
    `downtime_days` between them - because `judgeable_from` is a DATE and the countdown is in bars, and
    a reader given only one of those two units would be entitled to assume they are the same thing.
    They are equal only while the loop misses nothing; every hour it is down pushes the date right.

    One asymmetry a reader will notice and should not have to work out: the window's `elapsed_days`
    counts CYCLE rows while each strategy's `days` counts its own ATTRIBUTION rows, and an attribution
    row is written only when that strategy had income - so on 2026-09-09 the window reads 5.17 days
    while tsmom reads 0.83.  That is M-010's series verbatim (`income_drift` divides the same way), and
    matching it is the one thing §19 Q2 asked of this metric; a denser series with the flat bars filled
    in would be a better estimator and would make the two criteria incomparable, which is the trade the
    ruling already decided.  It is named here rather than smoothed over.

    **Today this returns INSUFFICIENT_DATA and that is the answer, not a gap.**  The construction
    running now began 2026-09-04T14:00Z, so the window closes 2028-03-04 - about 542 days away as of
    2026-09-09.  `sharpe_so_far` is reported beside `sharpe_standard_error` precisely so the early
    number cannot be mistaken for a verdict: at five days that error is 8.5.
    """
    window = evidence_window(store)
    since_ms = window["since_ms"]
    block: dict[str, Any] = {
        "status": "INSUFFICIENT_DATA",
        "window_months": window_months,
        "construction": window["construction"],
        "since": None,
        "judgeable_from": None,
        "bars": window["bars"],
        "elapsed_days": round(window["bars"] / 24.0, 4),
        "required_days": None,
        "days_remaining": None,
        "by_strategy": {},
    }
    if since_ms is None:
        return {**block, "why": "no cycle has recorded a construction, so there is nothing to time"}
    since = datetime.fromtimestamp(since_ms / 1000, tz=UTC)
    closes = _plus_months(since, window_months)
    required = (closes - since).days
    elapsed = block["elapsed_days"]
    calendar = max(0.0, ((now or datetime.now(UTC)) - since).total_seconds() / 86_400.0)
    block |= {
        "since": since.isoformat(),
        # The earliest this could close, i.e. assuming the loop misses nothing from here on.
        "judgeable_from": closes.isoformat(),
        "required_days": required,
        "days_remaining": round(max(0.0, required - elapsed), 4),
        "calendar_days": round(calendar, 4),
        # Calendar the record does not cover.  Not an error: the countdown simply did not advance.
        "downtime_days": round(max(0.0, calendar - elapsed), 4),
    }
    if not equity or equity <= 0:
        return {**block, "why": "no equity to express attributed P&L against (M-010's denominator)"}
    open_yet = elapsed < required
    why = (
        f"构造不变 {elapsed:.2f}/{required} 天（{window_months} 个月），最早可判 {closes.date()}" if open_yet else None
    )
    rows: dict[str, Any] = {}
    worst = "OK"
    for strategy, points in sorted(_series_by_strategy(store, since_ms).items()):
        values = np.asarray([value / equity for _bar, value in points], dtype=float)
        days = values.size / 24.0
        point = sharpe(values, bars_per_year) if _has_dispersion(values) else None
        hac = newey_west_tstat(values) if values.size >= 3 else {"t_stat": None}
        if open_yet or point is None:
            status, action = "INSUFFICIENT_DATA", None
        elif point >= 0.0:
            status, action = "OK", None
        else:
            status, action = "FAIL", "该策略退出 main（§19 Q2 滞后判据 M-G06）"
        if status == "FAIL":
            worst = "FAIL"
        elif status == "INSUFFICIENT_DATA" and worst == "OK":
            worst = "INSUFFICIENT_DATA"
        rows[strategy] = {
            "bars": int(values.size),
            "days": round(days, 2),
            # Named for what it is.  It is not the criterion until `judgeable_from`, and a key called
            # `sharpe` would be read as one on the first day the report renders it.
            "sharpe_so_far": point,
            "sharpe_standard_error": math.sqrt(365.0 / days) if days > 0 else None,
            "nw_t": hac["t_stat"],  # reported, never a gate (D-P2)
            "status": status,
            "action": action,
            "why": why if open_yet else ("点估计 < 0" if status == "FAIL" else None),
        }
    if not rows:
        return {**block, "why": why or "no attribution row lands inside this construction"}
    return {**block, "status": "INSUFFICIENT_DATA" if open_yet else worst, "why": why, "by_strategy": rows}


def _has_dispersion(values: np.ndarray, *, minimum: int = 48) -> bool:
    """Enough bars, and a spread wider than floating-point noise.

    A strategy that only pays funding produces a constant income series; ``np.std`` of identical floats
    is not exactly zero once the mean has been summed and divided, so a naive Sharpe on it came out at
    3e17.  A ratio to a dispersion that is not there is not a measurement.
    """
    if values.size < minimum:
        return False
    spread = float(np.std(values, ddof=1))
    return spread > 1e-9 * max(abs(float(values.mean())), 1e-12)


def probe_correlation(store: StateStore, probes: Sequence[ProbeParams], *, since_ms: int | None) -> dict[str, Any]:
    """M-014: is a probe sleeve a second return stream, or a tilt on the main book?

    The round-5 finding was that 91% of the short-only flow sleeve's positions stacked on tsmom's shorts.
    If the live income series correlate closely, the sleeve is a tilt and its separate risk budget is a
    fiction, whatever its own P&L says.
    """
    series = _series_by_strategy(store, since_ms)
    out: dict[str, Any] = {}
    for probe in probes:
        sleeve = dict(series.get(probe.strategy) or [])
        others = {name: dict(points) for name, points in series.items() if name != probe.strategy}
        for name, main in others.items():
            shared = sorted(set(sleeve) & set(main))
            if len(shared) < 8:
                out[f"{probe.strategy}~{name}"] = {"bars": len(shared), "correlation": None}
                continue
            a = np.asarray([sleeve[bar] for bar in shared], dtype=float)
            b = np.asarray([main[bar] for bar in shared], dtype=float)
            value = None if a.std() == 0 or b.std() == 0 else float(np.corrcoef(a, b)[0, 1])
            out[f"{probe.strategy}~{name}"] = {"bars": len(shared), "correlation": value}
    return out


def drift_check(
    store: StateStore, expectations: dict[str, Any], *, window_days: int = 30, bars_per_year: float = 8760.0
) -> dict[str, Any]:
    """Realised trailing Sharpe/drawdown from cycle equity versus the validation expectation."""
    cycles = [
        row for row in store.read_jsonl(store.cycles_path) if row.get("equity") is not None and not row.get("dry_run")
    ][-(window_days * 24) :]
    if len(cycles) < 48:
        return {"status": "INSUFFICIENT_DATA", "bars": len(cycles)}
    # a bar that absorbed an external cash flow (deposit, demo reset; E-044) is not a return and is skipped
    returns = np.asarray(
        [
            float(current["equity"]) / float(previous["equity"]) - 1.0
            for previous, current in pairwise(cycles)
            if float(previous["equity"]) > 0
            and not (current.get("external_flows") or {}).get("rebaselined")
            # M-012: a bar whose host clock jumped re-maps every label, so neither the return into it
            # nor the one out of it is a return between two comparable timestamps
            and not (current.get("clock") or {}).get("jumped")
            and not (previous.get("clock") or {}).get("jumped")
        ]
    )
    if len(returns) < 47:
        return {"status": "INSUFFICIENT_DATA", "bars": len(returns) + 1}
    realised = sharpe(returns, bars_per_year)
    drawdown = max_drawdown(returns)
    expected = [v["oos_sharpe"] for v in expectations.values() if v.get("oos_sharpe") is not None]
    expected_sharpe = sum(expected) / len(expected) if expected else None
    mdds = [
        v["full_sample_max_drawdown"] for v in expectations.values() if v.get("full_sample_max_drawdown") is not None
    ]
    worst_expected_mdd = min(mdds) if mdds else None
    days = len(returns) / 24.0
    status = "OK"
    reasons: list[str] = []
    if expected_sharpe is not None and realised is not None:
        # standard error of an annualised Sharpe estimate over `days` days is roughly sqrt(365/days)
        z = (realised - expected_sharpe) / math.sqrt(365.0 / max(days, 1.0))
        if z < -2.0:
            status = "ALERT"
            reasons.append(f"实现 Sharpe {realised:.2f} 比预期的 {expected_sharpe:.2f} 低 {abs(z):.1f} 个标准误")
    if worst_expected_mdd is not None and drawdown < 1.5 * worst_expected_mdd:
        status = "ALERT"
        reasons.append(f"滚动回撤 {drawdown:.3f} 已超过验证期回撤 {worst_expected_mdd:.3f} 的 1.5 倍")
    return {
        "status": status,
        "window_days": round(days, 1),
        "realised_sharpe": realised,
        "expected_sharpe": expected_sharpe,
        "trailing_drawdown": drawdown,
        "validated_drawdown": worst_expected_mdd,
        "reasons": reasons,
    }


def _long_run_sharpe_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """M-G06.  The countdown is the reading until 2028-03-04, so the countdown is what is rendered."""
    if not block:
        return {"none": 0}
    remaining = block.get("days_remaining")
    lines: dict[str, Any] = {
        "status": block.get("status"),
        "construction": str(block.get("construction")),
        "unbroken_since": str(block.get("since"))[:16],
        "window": f"{float(block.get('elapsed_days') or 0.0):.2f}/{block.get('required_days')} 天"
        f"（{block.get('window_months')} 个月，按 canonical_construction 计时）",
        "judgeable_from": f"{str(block.get('judgeable_from'))[:10]}"
        + (f"（还差 {float(remaining):.1f} 个记录日，前提是循环不再缺）" if remaining is not None else ""),
        "calendar_vs_record": f"日历 {float(block.get('calendar_days') or 0.0):.2f} 天，"
        f"其中 {float(block.get('downtime_days') or 0.0):.2f} 天记录没有覆盖",
    }
    if block.get("why"):
        lines["why"] = str(block["why"])
    for strategy, row in (block.get("by_strategy") or {}).items():
        lines[str(strategy)] = (
            f"{row.get('status')} sharpe_so_far={_fmt_num(row.get('sharpe_so_far'))} "
            f"+-{_fmt_num(row.get('sharpe_standard_error'))} nw_t={_fmt_num(row.get('nw_t'))} (报告，不作门) "
            f"over {row.get('days')}d" + (f" -> {row['action']}" if row.get("action") else "")
        )
    return lines


def _attribution_coverage_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """O3 in the markdown, worded so the 0.18 cannot be misread as four fifths of the evidence lost.

    The share is rendered next to what produces it - rows against the hours they span - and the gap
    count is rendered next to the only half of it that means anything on its own.
    """
    if not block:
        return {"none": 0}
    if not block.get("enforced"):
        return {"not measured": str(block.get("reason") or "no reason recorded")}
    hours = float(block.get("span_ms") or 0) / 3_600_000
    covered_hours = float(block.get("covered_ms") or 0) / 3_600_000
    unexplained = int(block.get("gaps_without_a_cycle") or 0)
    return {
        "attribution_rows": f"{block.get('rows')}（无法读出窗口的行：{block.get('unreadable_rows')}）",
        "span_hours": f"{hours:.1f}",
        "attributed_hours": f"{covered_hours:.1f}（占 {float(block.get('coverage') or 0.0):.1%}；"
        "只有产生了收入的周期才写行，所以这个比例天生远小于 1，不是证据缺失）",
        "gaps": f"{block.get('gap_count')} 处，最宽 {float(block.get('largest_gap_ms') or 0) / 3_600_000:.2f}h",
        # The one that would mean something: a gap the loop did not run through was never ingested.
        "gaps_without_a_cycle": (
            f"{unexplained} 处，最长 {float(block.get('largest_gap_without_a_cycle_ms') or 0) / 3_600_000:.2f}h"
            + ("（一个周期宽度以内的都可能只是一小时没有收入；报告，不作门）" if unexplained else "")
        ),
        "double_ingested_windows": block.get("overlap_count"),
    }


def _probe_correlation_note(payload: Mapping[str, Any], strategy: str) -> str:
    """The M-014 pair involving this probe, rendered onto its review line (empty when unreadable)."""
    pairs = [
        (pair, row)
        for pair, row in (payload.get("probe_correlation") or {}).items()
        if strategy and pair.endswith(f"~{strategy}") and row.get("correlation") is not None
    ]
    if not pairs:
        return ""
    pair, row = max(pairs, key=lambda item: abs(float(item[1]["correlation"])))
    return f" corr({pair})={float(row['correlation']):+.2f} over {row.get('bars')} bars"
