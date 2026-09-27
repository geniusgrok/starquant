"""The daily, weekly and beta reports: assembly only.

Until 2026-09-25 this one file held every reading the monitoring layer takes: 3,175 lines, and the
file where parallel sessions' daily-report changes collided (the 2026-09-23 batch resolved its
conflicts here and in the source budget table).  The readings now live by the checklist area they
answer in `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md`:

    report_decay       #1.10 edge decay, #4.10 signal monitoring, the automatic part of D.3
    report_risk        #3 the daily risk dashboard, with #3.4 / #8.9 holdings correlation and #3.9 liquidity
    report_exits       #1.5 / #3.2 the exit overlay
    report_execution   #10 execution, with #10.9 / #10.10 per-order TCA (M-Q08 itself is execution_fidelity.py)
    report_data        #9 data (bar sanity is bar_sanity.py)
    report_events      #8.10 event risk: the stablecoin peg, venue incidents and extreme moves, reported only
    report_beta        #6.4 / #6.9 attribution: market beta (D-045) and factor loadings (factor_loadings.py)
    report_governance  the weekly's effort share and pre-registration order
    report_common      what all of them read the state files with

What stays here is the assembly - `daily_payload`, `daily_alerts`, `daily_markdown`,
`weekly_payload`, `weekly_markdown` - and every name a caller already imports from this address,
re-exported as the same object.  A new reading goes in its area's module, not here:
`tests/live/test_the_report_layer_kept_its_addresses.py` fails if a definition other than the
assembly lands in this file.

Only that address contract is re-exported.  A library name kept here for convenience would let a
monkeypatch aimed at this module silently miss the reading that now calls it from another one -
the one failure this kind of split does not announce (M6, 2026-09-17).  `window_sharpes` is the one
name here that was never defined in this file; `tests/live/test_decay_detector.py` imports it from
this address, so it stays.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.report import render_markdown
from starquant_alpha.validation.metrics import (
    window_sharpes,  # noqa: F401  (historical address; see the module docstring)
)
from starquant_live.bar_sanity import sanity_findings, sanity_lines, sanity_status
from starquant_live.cycle_record import latest
from starquant_live.execution_fidelity import ReplayInputs, execution_fidelity, fidelity_lines, fidelity_notices
from starquant_live.probe import ProbeParams
from starquant_live.report_beta import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    _beta_regression_lines,
    _factor_loadings_lines,
    _market_beta_lines,
    beta_markdown,
    factor_loadings,
    market_beta,
)
from starquant_live.report_common import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    _cycles,
    _day_end_ms,
    _day_of,
    _fmt_num,
    _fmt_pct,
    _state_problem,
    _store_closes,
    evidence_window,
    json_dumps,
    readable_state,
)
from starquant_live.report_data import (
    _dataset_block,
    data_coverage,
    metrics_parity_status,
)
from starquant_live.report_decay import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    M_G06_WINDOW_MONTHS,
    _attribution_coverage_lines,
    _decay_alerts,
    _decay_lines,
    _long_run_sharpe_lines,
    _probe_correlation_note,
    _series_by_strategy,
    attribution_coverage,
    decay_verdict,
    decay_watch,
    drift_check,
    expectations_from_evidence,
    income_drift,
    long_run_sharpe,
    probe_correlation,
    probe_rows,
)
from starquant_live.report_events import _event_risk_lines, event_risk
from starquant_live.report_execution import (
    _restart_cost_lines,
    clock_health,
    per_order_tca,
    plan_gaps,
    restart_cost,
    tca_lines,
)
from starquant_live.report_exits import (
    exit_and_pool_events,
    exit_counterfactuals,
    exit_reachability,
)
from starquant_live.report_governance import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    ALPHA_EFFORT_TARGET,
    PREREGISTRATION_EFFECTIVE_FROM,
    effort_share,
    preregistration_problems,
    preregistration_skipped,
)
from starquant_live.report_risk import (  # noqa: F401  (re-exported at its historical address; see the module docstring)
    BACKTEST_DAILY_ES,
    BACKTEST_DAILY_VAR,
    BACKTEST_EXITS_PER_WEEK,
    RISK_COMPRESSION_LIMIT,
    TAIL_VOL_TARGET,
    _collateral_drift_lines,
    _holdings_correlation_lines,
    _liquidity_to_close_lines,
    _noise_scale_lines,
    _risk_adaptation_lines,
    _risk_budget_lines,
    _tail_readings_lines,
    _tradable_drawdown_line,
    _weight_cap_line,
    collateral_share,
    holdings_correlation,
    latest_risk_adaptation,
    leg_split,
    liquidity_to_close,
    margin_and_rejections,
    max_weight_of,
    noise_scale,
    risk_adaptation,
    risk_adaptation_headline,
    tail_readings,
    weight_cap_bindings,
)
from starquant_live.risk_budget import RiskBudgetParams, collateral_drift, one_row_per_order, risk_budget_status
from starquant_live.state import StateStore


def daily_payload(
    store: StateStore,
    day: str,
    expectations: dict[str, Any] | None = None,
    probes: Sequence[ProbeParams] = (),
    risk_budget: RiskBudgetParams | None = None,
    dataset: Mapping[str, Any] | None = None,
    *,
    vol_target: float | None = None,
    margin_cap: float | None = None,
    data_root: str | Path = ".starquant/data",
    closes: Callable[[str], pd.Series] | None = None,
    exits: ExitParams | None = None,
    fidelity: ReplayInputs | None = None,
) -> dict[str, Any]:
    cycles = [row for row in store.read_jsonl(store.cycles_path) if _day_of(row) == day]
    trades = [row for row in store.read_jsonl(store.trades_path) if _day_of(row) == day]
    attributions = [row for row in store.read_jsonl(store.attribution_path) if _day_of(row) == day]
    equities = [float(row["equity"]) for row in cycles if row.get("equity") is not None]
    by_strategy: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    commissions = funding = realized = 0.0
    foreign_total = 0.0
    foreign_rows = 0
    foreign_by_symbol: dict[str, float] = {}
    unreconciled = 0
    for row in attributions:
        for strategy, value in (row.get("by_strategy") or {}).items():
            by_strategy[strategy] = by_strategy.get(strategy, 0.0) + float(value)
        for symbol, bucket in (row.get("by_symbol") or {}).items():
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + float(bucket.get("total", 0.0))
            commissions += float(bucket.get("COMMISSION", 0.0))
            funding += float(bucket.get("FUNDING_FEE", 0.0))
            realized += float(bucket.get("REALIZED_PNL", 0.0))
        # D-032: P&L from fills the loop did not place is real money and stays in the report, but it is
        # not the strategy's and must not reach the series M-010 judges the strategy by.
        foreign = row.get("foreign") or {}
        foreign_total += float(foreign.get("total", 0.0) or 0.0)
        foreign_rows += int(foreign.get("rows", 0) or 0)
        for symbol, bucket in (foreign.get("by_symbol") or {}).items():
            foreign_by_symbol[symbol] = foreign_by_symbol.get(symbol, 0.0) + float(bucket.get("total", 0.0))
        if "foreign" in row and not foreign.get("reconciled"):
            unreconciled += 1
    statuses: dict[str, int] = {}
    traded = 0.0
    # Each venue order once: a restart's "already submitted" row repeats a fill the log already holds.
    for trade in one_row_per_order(trades):
        statuses[str(trade.get("status"))] = statuses.get(str(trade.get("status")), 0) + 1
        if trade.get("executed_qty") and trade.get("avg_price"):
            traded += float(trade["executed_qty"]) * float(trade["avg_price"])
    guard_events = [reason for row in cycles for reason in (row.get("guard_reasons") or [])]
    window = evidence_window(store)
    flows = [row.get("external_flows") or {} for row in cycles]
    return {
        "day": day,
        "cycles": len(cycles),
        "skipped_cycles": sum(1 for row in cycles if row.get("skip")),
        "external_flows": {
            "total": sum(float(flow.get("total", 0.0) or 0.0) for flow in flows),
            "rows": sum(int(flow.get("rows", 0) or 0) for flow in flows),
            "rebaselined_cycles": sum(1 for flow in flows if flow.get("rebaselined")),
        },
        "equity_start": equities[0] if equities else None,
        "equity_end": equities[-1] if equities else None,
        "equity_change_pct": (equities[-1] / equities[0] - 1.0) if len(equities) >= 2 and equities[0] else None,
        # L1-10: the last cycle's split of that equity into USDT and collateral.  Rows written before the
        # engine recorded it carry nothing, and nothing is what gets reported - not a zero.
        "collateral": latest(cycles, "collateral"),
        "orders": statuses,
        "traded_notional": traded,
        "realized_pnl": realized,
        "commissions": commissions,
        "funding": funding,
        "pnl_by_strategy": by_strategy,
        "pnl_by_symbol": by_symbol,
        "foreign_fills": {
            "total": foreign_total,
            "rows": foreign_rows,
            "by_symbol": foreign_by_symbol,
            "unreconciled_cycles": unreconciled,
        },
        "guard_events": {event: guard_events.count(event) for event in set(guard_events)},
        # M-Q03 / AC-L4 / RISK-P2: what the day's restarts cost, against the plan's own "<= 5% / 0".
        # DL-L4 wrote these into the cycle rows and nothing read them; a cost that only exists in a
        # JSONL is an assumption, not a measurement, and one nothing compares to a bar is not a metric.
        "restarts": restart_cost(cycles, trades, risk_budget or RiskBudgetParams()),
        # M-Q08's turnover clause (it had no instrument), its digest clause and slippage by week: see the module.
        "execution_fidelity": execution_fidelity(store, fidelity),
        # #10.9 / #10.10: each fill's pre-trade estimate, rebuilt offline, beside its post-trade cost.
        "tca": per_order_tca(store, risk_budget or RiskBudgetParams(), data_root=data_root),
        "last_targets": cycles[-1].get("targets") if cycles else {},
        "expectations": expectations or {},
        "risk_budget": risk_budget_status(
            _cycles(store),
            store.read_jsonl(store.trades_path),
            risk_budget or RiskBudgetParams(),
            store.read_jsonl(store.attribution_path),
        ),
        # DL-D4 / M-011: do the T+1 archive and what the loop could actually read agree on the buckets
        # they share?  The whole same-source contract is this one number, and until now `metrics_parity`
        # existed with nothing calling it - which is the shape this repository keeps finding, a
        # measurement that is written but never taken.
        "metrics_parity": metrics_parity_status(sorted(cycles[-1].get("universe") or []) if cycles else [], data_root),
        # The instrument the 2026-09-08 ruling owes: the denominator stays total equity, so the
        # pro-cyclical amplifier is an ACCEPTED risk - and an accepted risk with nothing measuring it is
        # a sentence.  Beside `risk_budget` rather than inside it on purpose: it is not a threshold and
        # it must never page.
        "collateral_drift": collateral_drift(_cycles(store), store.read_jsonl(store.attribution_path)),
        "drift": drift_check(store, expectations or {}),
        "evidence_window": window,
        # O3, beside the window rather than inside it: `evidence_window` says how long the current
        # construction has run, and this says whether the attribution series under it is unbroken.
        # A window that is merely SHORT and a window with a block missing read the same everywhere
        # else, and M-010 is the evidence KILL-006 rests on.  A reading, with no threshold.
        "attribution_coverage": attribution_coverage(store),
        "income_drift": income_drift(
            store, expectations or {}, equity=equities[-1] if equities else None, since_ms=window["since_ms"]
        ),
        # §12.9's decay rule, in the hourly check since 2026-09-23 (G1).  The weekly's own call, so the
        # two reports cannot read the rule differently; `daily_alerts` pages on REVIEW and nothing else.
        "decay": decay_watch(store, expectations or {}, equity=equities[-1] if equities else None),
        # M-G06 (§19 Q2's lagging half).  INSUFFICIENT_DATA for the next year and a half, on purpose:
        # the row that says how far off it is is the only honest thing it can say today.
        "long_run_sharpe": long_run_sharpe(store, equity=equities[-1] if equities else None),
        "legs": leg_split(store, since_ms=window["since_ms"], equity=equities[-1] if equities else None),
        # D-045 beside the legs, which split the same money by side: this splits it into the market's
        # part and the rest.  Over the whole USDT-equity record rather than the day, as `report beta`.
        "beta": market_beta(store, closes=closes, root=data_root),
        # #6.4 / #6.9 beside it: what the same book loaded on besides the market.  Reads the archive
        # itself rather than `closes`, because its sorts need volume and funding as well as prices.
        "factor_loadings": factor_loadings(store, root=data_root),
        "probe_correlation": probe_correlation(store, probes, since_ms=window["since_ms"]),
        # #3.4 / #8.9 beside M-014, which reads sleeves against each other: this reads the held names.
        "holdings_correlation": holdings_correlation(store, day, closes=closes, root=data_root),
        "events": exit_and_pool_events(store, day),
        # Beside the exit COUNT rather than inside it: that block says what the overlay did today,
        # and this says which thresholds it could not have reached whatever the price did.  A zero
        # count means both things at once until something separates them.
        "exit_reachability": exit_reachability(store, exits),
        "noise_scale": noise_scale(store, day, vol_target=vol_target),
        "tail": tail_readings(store, day, vol_target=vol_target),  # G4: the backtest tail beside the sigma ruler
        # #8.10, reported only: the stablecoin peg, what the loop recorded going wrong on its way to the venue,
        # and the market's newest moves in units of its own vol.  Beside the book's tail, which it is not.
        "event_risk": event_risk(store, day, closes=closes, root=data_root),
        "exit_counterfactual": exit_counterfactuals(store, closes=closes, root=data_root),
        "plan_gaps": plan_gaps(store, day),
        "clock": clock_health(store, day),
        # The file itself, before anything derived from it: a corrupt state.json makes several
        # blocks below quietly thinner (no universe, no leverage, no probe stop records), and
        # "thinner" and "nothing happened" look identical in a rendered report.
        "state_file": {"readable": not _state_problem(store), "reason": _state_problem(store)},
        "data_coverage": data_coverage(store, root=data_root),
        # G6: bars the loop fed its model that did not look like prices, split into first-seen-today and not.
        "bar_sanity": sanity_status(store.read_jsonl(store.cycles_path), day, day_of=_day_of),
        "margin": margin_and_rejections(store, since_ms=window["since_ms"], margin_cap=margin_cap),
        # 3.9, reported only: a full close is one market order, so what it costs is impact, not bars.
        "liquidity_to_close": liquidity_to_close(store, day, root=data_root),
        "risk_adaptation": risk_adaptation(store, day),
        "probes": probe_rows(store, probes, equity=equities[-1] if equities else None, now_ms=_day_end_ms(day)),
        "dataset": _dataset_block(dataset),
    }


def daily_alerts(payload: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Split a daily payload's findings into (alerts, notices): what pages, and what only gets read.

    An alert says the running book has moved and the operator can do something about it now.  A
    notice is true and worth seeing at review, but nothing can be done with it in the next hour -
    a construction-cadence count is the case that forced the distinction: two promotions landed on
    2026-09-04, a promotion cannot be un-done, and the hourly check paged on it for three days,
    twice an hour - two writers on one channel, and a dedup window that was then equal to the job's
    period and so suppressed neither of them reliably.  That is precisely the
    repeated alert `alerts.py` says buries the one that matters, so notices leave the paging path
    entirely; they stay in the report's Evidence window block.  Making a notice loud again is a
    matter of moving one append, not of finding a suppression to undo.
    """
    alerts: list[str] = []
    state_file = payload.get("state_file") or {}
    if state_file and not state_file.get("readable", True):
        # Loud rather than a notice: every block that reads the universe, the leverage or the probe
        # stop records is now answering from an empty state, and the watermark this file carries is
        # the one M-010 cannot reconstruct afterwards.
        alerts.append(f"state.json 读不动，日报的若干读数是从空状态算的：{state_file.get('reason')}")
    for name, key in (("权益", "drift"), ("策略收益", "income_drift")):
        block = payload.get(key) or {}
        if str(block.get("status")) == "ALERT":
            detail = block.get("reasons") or [
                f"{strategy}: z={row.get('z'):.1f}"
                for strategy, row in (block.get("by_strategy") or {}).items()
                if row.get("z") is not None and row["z"] < -2.0
            ]
            alerts.append(f"{name}漂移告警：{'；'.join(str(d) for d in detail)}")
    alerts.extend(_decay_alerts(payload.get("decay") or {}))
    budget = payload.get("risk_budget") or {}
    if str(budget.get("status")) == "ALERT":
        # P13's ladder: its thresholds were fixed before the change went live.  R8 applies the attributed
        # rung in the loop after two cycles of grace (`LiveEngine._risk_ladder`); the rest only report.
        alerts.append("风险预算告警：" + "；".join(str(r) for r in budget.get("reasons") or []))
    adaptation = payload.get("risk_adaptation") or {}
    if str(adaptation.get("status")) == "ALERT":
        # M-015: the weights stopped taking each symbol's volatility back out.  Loud rather than
        # quiet because this is the layer D-037 pointed at when it ruled the leverage layer inert.
        # The clause read "per-symbol sizing is no longer vol-scaled", and the Lark translation
        # carried it over faithfully as "不再按波动率缩放" - a conclusion the statistic cannot
        # support, and wrong the first time it fired: `compression` is measured AFTER
        # `combine_books` sums the books, so a second book disagreeing reads as stage 1 failing.
        # Since 2026-09-12 the number quoted is the reading the gate took, and the line says which one
        # and what the other reads.  The old text told the operator to "check the probe/main overlap"
        # and gave them nothing to check it with; now the overlap is measured and sits beside it.
        combined = (adaptation.get("combined") or {}).get("compression")
        alerts.append(
            f"风险自适应告警：压缩度 {adaptation.get('compression'):.2f} > {adaptation.get('limit'):.2f}"
            f"（{adaptation.get('judged', 'combined')} 读法）"
            + (f"；合并两本书读 {combined:.2f}" if combined is not None else "")
            + "；风险贡献相互拉开——查第一层"
        )
    notices: list[str] = []
    # G6: a suspicious bar pages on the day it is first seen; a check that could not run is read at review.
    sanity_alerts, sanity_notices = sanity_findings(payload.get("bar_sanity") or {})
    alerts += sanity_alerts
    notices += sanity_notices
    margin = payload.get("margin") or {}
    if margin.get("over_budget"):
        # M-007.  A notice rather than an alert, by the same test the other entries here use: realized
        # standing margin above the policy means gross/equity drifted past `max_gross` between
        # rebalances, and stage 3 re-clips it at the next one - there is nothing to do inside the hour.
        # It is here at all because until 2026-09-14 `over_budget` had no reader: it was computed, it
        # was rendered into the markdown, and no path carried it to either list.
        notices.append(
            f"M-007 保证金占用 {_fmt_pct(margin.get('peak_standing_usage'))} 超过 "
            f"{_fmt_pct(margin.get('budget'))}（margin_cap）：实际 gross/权益 在两次再平衡之间越过了 max_gross"
        )
    if margin.get("over_budget_tradable") and not margin.get("over_budget"):
        # Only when the two rulers disagree: that gap IS the finding, and printing it under the same
        # wording as the line above would read as a second breach rather than the same one measured
        # against the money that can open a position.
        notices.append(
            f"M-007 保证金占用对可动用 USDT 为 {_fmt_pct(margin.get('peak_standing_usage_tradable'))}，"
            f"超过 {_fmt_pct(margin.get('budget'))}（margin_cap 是在无抵押品的回测上定的）；"
            f"同一根 bar 对总权益只有 {_fmt_pct(margin.get('peak_standing_usage'))}，"
            "两把尺子差约 1.9 倍。约束侧未改（构造冻结到 2026-10-13）"
        )
    if str(budget.get("status")) == "BLIND":
        # A criterion with no reading is not a breach and cannot be acted on in the next hour - it
        # clears itself once the bars or fills arrive.  It is here rather than nowhere because the
        # 2026-09-07 report said OK while M-Q08's slippage instrument had zero usable fills.
        notices.append(
            "风险预算读不出数（BLIND）："
            + "；".join(f"{entry.get('metric')}（{entry.get('why')}）" for entry in budget.get("unreadable") or [])
        )
    window = payload.get("evidence_window") or {}
    if int(window.get("changes_7d") or 0) > 1:
        # the plan allowed one promotion per week and nothing ever counted them
        notices.append(f"最近 7 天有 {window['changes_7d']} 次构造变更；计划允许每周一次晋升")
    drift = payload.get("collateral_drift") or {}
    if drift.get("account_misleads"):
        # RISK-G11.  NOT an alert, and the reasoning is the same distinction this docstring draws.  The
        # amplifier itself is a standing fact the operator ACCEPTED on 2026-09-08 with the denominator
        # ruling, so there is nothing to do about it inside the hour and it must never page (its own
        # module says so); on the paging path it would re-announce itself every dedup window for as
        # long as the account holds BTC - the construction-cadence shape exactly, and one the window
        # cannot fix in either direction: shorter re-announces more often, longer buries the alert
        # that matters.  A standing fact has to leave the paging path, not be tuned on it.  What DID change is which side of 1.0 the share sits on,
        # and that is a fact a reader of the equity line needs at review: above 1 the account's equity
        # direction no longer tells them which way the book went.
        notices.append(
            f"抵押品重估占权益变化的 {drift['repricing_share']:.1%}（>100%）："
            f"权益 {drift['equity_change']:+.2f} 而书的归因 P&L 是 {drift['attributed_pnl']:+.2f}，"
            "本窗口权益方向与书的盈亏方向相反（RISK-G11，只报告不相减）"
        )
    restarts = payload.get("restarts") or {}
    if failed_bars := int(restarts.get("failed_bars") or 0):
        # The half of M-Q03 that pages, split out on the operator's decision 2026-09-16.  The argument
        # below is about a restart: it cannot be un-restarted, so the miss is already past and belongs
        # at review.  A bar whose CYCLE FAILED is a different animal.  The exit overlay rests no order
        # at the venue - stops are computed inside the cycle and sent as MARKET reduceOnly - so the
        # hour it lost had no stop check at all, and what to do about it is on the path to the venue
        # while that path is still broken.  `failed_bars` is absent from every report written before
        # this split, and reads as zero, which is the right answer for days nothing counted.
        notices_first = "；".join(str(r) for r in restarts.get("reasons") or [])
        alerts.append(
            f"M-Q03 周期失败丢掉 {failed_bars} 根 bar（这些小时没有再平衡，也没有退出检查）："
            f"{restarts.get('failed_bar_error') or notices_first}；失败动作：查到交易所的这条路径"
        )
    if str(restarts.get("status")) == "ALERT":
        # M-Q03.  A notice for the reason the plan itself gives: its registered failure action is
        # "查重启原因", an investigation at review.  The miss is already past by the time this renders,
        # `live status --check` already pages when the loop is actually down, and a single planned
        # deployment restart would otherwise hold the hourly check red until UTC midnight.  Kept as the
        # COMPLETE record even when the half above already paged: the alert is the actionable subset,
        # this is what a reader at review needs, and the two go to different places.
        notices.append("M-Q03 迟到成交：" + "；".join(str(r) for r in restarts.get("reasons") or []))
    notices.extend(fidelity_notices(payload))  # M-Q08 turnover: a review item, see `fidelity_notices`
    lagging = payload.get("long_run_sharpe") or {}
    if str(lagging.get("status")) == "FAIL":
        # M-G06.  INSUFFICIENT_DATA says nothing here on purpose - it will be the answer until
        # 2028-03-04 and a finding repeated for 542 days is not a finding.  A FAIL is real, and its
        # action ("该策略退出 main") is a governance transition taken through `lifecycle.apply` at
        # review rather than something to do inside the hour.
        notices.append(
            "M-G06 滞后判据不通过："
            + "；".join(
                f"{strategy} 归因年化 Sharpe {row.get('sharpe_so_far'):.2f} < 0 -> {row.get('action')}"
                for strategy, row in (lagging.get("by_strategy") or {}).items()
                if str(row.get("status")) == "FAIL"
            )
        )
    return alerts, notices


def weekly_payload(
    store: StateStore,
    day: str,
    *,
    expectations: dict[str, Any] | None = None,
    changed_lines: Mapping[str, int] | None = None,
    dataset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The plan's weekly research report, which was listed as a deliverable and never built.

    Its job is not to add numbers but to put the week's decisions next to the week's evidence: how many
    days the current construction has actually run, what each strategy earned by attributed income, how
    many configurations were charged to the ledger, and whether the promotion cadence was respected.  A
    week is the unit because that is the cadence the plan set for promotions.
    """
    end = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)
    since_ms = int((end - timedelta(days=7)).timestamp() * 1000)
    cycles = [row for row in _cycles(store) if int(row.get("bar_open_ms") or 0) >= since_ms]
    window = evidence_window(store)
    equities = [float(row["equity"]) for row in cycles if row.get("equity") is not None]
    income = income_drift(store, expectations or {}, equity=equities[-1] if equities else None, since_ms=since_ms)
    decay = decay_watch(store, expectations or {}, equity=equities[-1] if equities else None)
    constructions = sorted({str(row.get("construction")) for row in cycles if row.get("construction")})
    return {
        "week_ending": day,
        "since_ms": since_ms,
        "cycles": len(cycles),
        "skipped_cycles": sum(1 for row in cycles if row.get("skip")),
        "equity_start": equities[0] if equities else None,
        "equity_end": equities[-1] if equities else None,
        "constructions_seen": constructions,
        "promotions": max(0, len(constructions) - 1),
        "promotion_budget": 1,
        "evidence_window": window,
        "income": income,
        # The adopted decay rule (report 4.2 Ⅰ, ruling 12.9).  Weekly-only was a choice - the rule is
        # about the live period, not one day - but no job runs this report, so since 2026-09-23 the
        # daily report makes this same call and the hourly check pages on its REVIEW (G1).
        "decay": decay,
        "legs": leg_split(store, since_ms=since_ms, equity=equities[-1] if equities else None),
        "margin": margin_and_rejections(store, since_ms=since_ms),
        "effort": effort_share(changed_lines) if changed_lines is not None else None,
        "dataset": _dataset_block(dataset),
    }


def weekly_markdown(payload: dict[str, Any]) -> str:
    income_rows = (payload.get("income") or {}).get("by_strategy") or {}
    return render_markdown(
        f"Weekly report, week ending {payload['week_ending']}",
        [
            (
                "Cycles",
                {key: payload.get(key) for key in ("cycles", "skipped_cycles", "equity_start", "equity_end")},
            ),
            (
                # The adopted decay rule.  It cannot fire before roughly 2026-11-05 - the construction
                # froze 2026-09-06 and two whole non-overlapping 30-day windows have to follow it - and
                # it needs a q10 nobody has computed yet.  Both facts are printed rather than hidden,
                # because a rule that is silently unable to fire is the same as no rule.
                "Edge decay (M-010 vs backtest q10)",
                {
                    name: f"{row['status']}"
                    + (f" - {row['why']}" if row.get("why") else f" ({row['below']}/2 below q10)")
                    for name, row in sorted((payload.get("decay") or {}).items())
                }
                or {"none": "no attributed income yet"},
            ),
            (
                # D-041: the manifest was written into every report and read by nothing.  It is read now,
                # and this is where a human sees the answer after startup has scrolled away.
                "Dataset provenance (D-041)",
                {
                    key: json_dumps(value) if value else "none"
                    for key, value in (payload.get("dataset") or {"blocking": [], "advisory": []}).items()
                },
            ),
            (
                "Promotions this week (the plan allows one)",
                {
                    "constructions_seen": len(payload.get("constructions_seen") or []),
                    "promotions": payload.get("promotions"),
                    "within_budget": int(payload.get("promotions") or 0) <= int(payload.get("promotion_budget") or 1),
                    "current_construction": (payload.get("evidence_window") or {}).get("construction"),
                    "bars_under_it": (payload.get("evidence_window") or {}).get("bars"),
                },
            ),
            (
                "Income by strategy (M-002/M-010)",
                {
                    strategy: (
                        f"pnl={_fmt_num(row.get('pnl'))} sharpe={_fmt_num(row.get('realised_sharpe'))} "
                        f"vs {_fmt_num(row.get('expected_sharpe'))} over {_fmt_num(row.get('days'))}d"
                    )
                    for strategy, row in income_rows.items()
                }
                or {"none": 0},
            ),
            (
                # DL-K3.  A pass here says the week's validations were each preceded by the thing that
                # registered them; it does not say the registration was any good.
                "Pre-registration order (DL-K3 / KILL-R9)",
                (
                    {
                        "checked": (payload.get("preregistration") or {}).get("checked", 0),
                        "not judged (predate the check)": (payload.get("preregistration") or {}).get(
                            "skipped_as_predating_the_check", 0
                        ),
                        "verdict": "PASS",
                    }
                    if not ((payload.get("preregistration") or {}).get("problems") or [])
                    else {f"FAIL {i + 1}": line for i, line in enumerate(payload["preregistration"]["problems"])}
                ),
            ),
            ("Legs (M-008)", (payload.get("legs") or {}).get("pnl") or {"none": 0}),
            (
                "Effort share (target 90% on alpha)",
                {
                    "alpha_share": _fmt_pct((payload.get("effort") or {}).get("alpha_share")),
                    "target": _fmt_pct((payload.get("effort") or {}).get("target")),
                    "on_target": (payload.get("effort") or {}).get("on_target"),
                    "lines": json_dumps((payload.get("effort") or {}).get("lines") or {}),
                }
                if payload.get("effort")
                else {"none": 0},
            ),
            (
                "Margin (M-007)",
                {
                    "peak_standing_usage": _fmt_pct((payload.get("margin") or {}).get("peak_standing_usage")),
                    "peak_order_demand": _fmt_pct((payload.get("margin") or {}).get("peak_margin_usage")),
                    "insufficient_margin_rejections": (payload.get("margin") or {}).get("insufficient_margin"),
                },
            ),
        ],
    )


def daily_markdown(payload: dict[str, Any]) -> str:
    return render_markdown(
        f"Daily report {payload['day']}",
        [
            (
                "Equity",
                {
                    k: payload[k]
                    for k in ("equity_start", "equity_end", "equity_change_pct", "cycles", "skipped_cycles")
                },
            ),
            (
                # L1-10: the ladder and the vol sizing divide by the line above, and on multi-assets
                # margin that line carries BTC.  Printing the split is what lets a reader tell a
                # drawdown the strategy caused from one the collateral did.  Reported, never enforced.
                "Collateral in equity (L1-10)",
                dict(payload.get("collateral") or {"share": None, "why": "no cycle recorded it yet"}),
            ),
            (
                # L1-10's other half, and the instrument the 2026-09-08 ruling owes (RISK-G11).  It
                # reached `reports/daily/*.json` and stopped there until 2026-09-09; the line a reader
                # of the equity number above actually needs is `account_misleads`.
                "Collateral repricing (RISK-G11)",
                _collateral_drift_lines(payload.get("collateral_drift") or {}),
            ),
            (
                # AC-L4: the same sentence as the line below it, one restart over.  RISK-P2 assumed a
                # deployment restart costs late fills and a rebalance; this is where that stops being
                # an assumption - and, since 2026-09-09, where it is compared to M-Q03's own bar.
                "Restart cost (M-Q03 / DL-L4 / RISK-P2)",
                _restart_cost_lines(payload.get("restarts") or {}),
            ),
            ("Execution fidelity (M-Q08, four clauses)", fidelity_lines(payload)),
            ("Per-order TCA (#10.9 / #10.10, reported only)", tca_lines(payload.get("tca") or {})),
            (
                # D-041: the manifest was written into every report and read by nothing.  It is read now,
                # and this is where a human sees the answer after startup has scrolled away.
                "Dataset provenance (D-041)",
                {
                    key: json_dumps(value) if value else "none"
                    for key, value in (payload.get("dataset") or {"blocking": [], "advisory": []}).items()
                },
            ),
            ("Orders", payload["orders"] or {"none": 0}),
            ("External cash flows (not P&L)", payload.get("external_flows") or {"none": 0}),
            (
                "Costs",
                {
                    "traded_notional": payload["traded_notional"],
                    "commissions": payload["commissions"],
                    "funding": payload["funding"],
                    "realized_pnl": payload["realized_pnl"],
                },
            ),
            ("PnL by strategy", payload["pnl_by_strategy"] or {"none": 0}),
            ("PnL by symbol", payload["pnl_by_symbol"] or {"none": 0}),
            (
                # D-032: fills nobody in this loop placed - an operator flatten, a manual hedge
                "Foreign fills, excluded from the strategy series (D-032)",
                {
                    "total": payload["foreign_fills"]["total"],
                    "rows": payload["foreign_fills"]["rows"],
                    "by_symbol": json_dumps(payload["foreign_fills"]["by_symbol"]),
                    "cycles_that_could_not_reconcile": payload["foreign_fills"]["unreconciled_cycles"],
                }
                if payload["foreign_fills"]["rows"] or payload["foreign_fills"]["unreconciled_cycles"]
                else {"none": 0},
            ),
            ("Guard events", payload["guard_events"] or {"none": 0}),
            (
                # A planner that acts on nothing must still say what it looked at (P10 cell B's falsifier)
                "Plan gaps (no-trade band)",
                {
                    "band_held_symbol_cycles": payload["plan_gaps"]["band_held"],
                    "blocked_entry": json_dumps(payload["plan_gaps"]["blocked_entry"]),
                    "blocked_exit": json_dumps(payload["plan_gaps"]["blocked_exit"]),
                    "by_reason": json_dumps(payload["plan_gaps"]["by_reason"]),
                },
            ),
            (
                "Expectations (validation reports)",
                {
                    k: f"oos_sharpe={_fmt_num(v.get('oos_sharpe'))} full={_fmt_num(v.get('full_sample_sharpe'))} mdd={_fmt_num(v.get('full_sample_max_drawdown'))} {v.get('verdict')}"
                    for k, v in (payload.get("expectations") or {}).items()
                }
                or {"none": 0},
            ),
            ("Risk budget (P13)", _risk_budget_lines(payload.get("risk_budget") or {})),
            ("Drift vs expectation (equity)", payload.get("drift") or {"none": 0}),
            (
                "Evidence window (D-026 construction)",
                {
                    "construction": (payload.get("evidence_window") or {}).get("construction"),
                    "bars_under_it": (payload.get("evidence_window") or {}).get("bars"),
                    "construction_changes_last_7d": (payload.get("evidence_window") or {}).get("changes_7d"),
                    # O3: the window says how long; these say whether it is whole.
                    **_attribution_coverage_lines(payload.get("attribution_coverage") or {}),
                },
            ),
            (
                "Drift vs expectation (attributed income, M-002/M-010)",
                {
                    "status": (payload.get("income_drift") or {}).get("status"),
                    **{
                        strategy: (
                            f"sharpe={_fmt_num(row.get('realised_sharpe'))} vs {_fmt_num(row.get('expected_sharpe'))} "
                            f"z={_fmt_num(row.get('z'))} pnl={_fmt_num(row.get('pnl'))} days={_fmt_num(row.get('days'))}"
                        )
                        for strategy, row in ((payload.get("income_drift") or {}).get("by_strategy") or {}).items()
                    },
                },
            ),
            ("Edge decay (M-010 vs backtest q10)", _decay_lines(payload)),
            (
                # §19 Q2's lagging criterion.  Rendered while it is still INSUFFICIENT_DATA because the
                # countdown IS the reading: a criterion nobody can see the distance to is a criterion
                # nobody waits for.
                "Long-run attributed Sharpe (M-G06)",
                _long_run_sharpe_lines(payload.get("long_run_sharpe") or {}),
            ),
            (
                "Legs (M-008)",
                {
                    f"{side} pnl": f"{_fmt_num(value)} over {(payload.get('legs') or {}).get('symbol_bars', {}).get(side)} symbol-bars"
                    for side, value in ((payload.get("legs") or {}).get("pnl") or {}).items()
                }
                or {"none": 0},
            ),
            ("Market beta (D-045, reported only)", _market_beta_lines(payload.get("beta") or {})),
            (
                "Factor loadings (#6.4 / #6.9, reported only)",
                _factor_loadings_lines(payload.get("factor_loadings") or {}),
            ),
            (
                "Probe correlation (M-014)",
                {
                    pair: f"{_fmt_num(row.get('correlation'))} over {row.get('bars')} bars"
                    for pair, row in (payload.get("probe_correlation") or {}).items()
                }
                or {"none": 0},
            ),
            (
                "Holdings correlation (#3.4 / #8.9, reported only)",
                _holdings_correlation_lines(
                    payload.get("holdings_correlation") or {}, payload.get("risk_budget") or {}
                ),
            ),
            (
                # D-025: not an alert, but every timestamp above is the host's, so say how far off it is
                "Clock (D-025)",
                payload.get("clock") or {"none": 0},
            ),
            (
                "Research data coverage",
                payload.get("data_coverage") or {"none": 0},
            ),
            # G6, beside the archive's coverage: whether the bars the LOOP read looked like prices at all.
            ("Bar sanity (G6, alert only)", sanity_lines(payload.get("bar_sanity") or {})),
            (
                "Margin and rejections (M-007)",
                {
                    # standing = margin the held book consumes; order_demand = what new orders asked for
                    "peak_standing_usage": _fmt_pct((payload.get("margin") or {}).get("peak_standing_usage")),
                    "last_standing_usage": _fmt_pct((payload.get("margin") or {}).get("last_standing_usage")),
                    "peak_order_demand": _fmt_pct((payload.get("margin") or {}).get("peak_margin_usage")),
                    "budget": _fmt_pct((payload.get("margin") or {}).get("budget")),
                    "over_budget": (payload.get("margin") or {}).get("over_budget"),
                    # The same numbers against the USDT that can actually open a position.  These are
                    # the ones `margin_cap` was calibrated for; the two lines above are kept because a
                    # corrected ruler's old reading is what tells a later reader what it was wrong about.
                    "peak_standing 对可动用 USDT": _fmt_pct(
                        (payload.get("margin") or {}).get("peak_standing_usage_tradable")
                    ),
                    "last_standing 对可动用 USDT": _fmt_pct(
                        (payload.get("margin") or {}).get("last_standing_usage_tradable")
                    ),
                    "over_budget（可动用口径，判定）": (payload.get("margin") or {}).get("over_budget_tradable"),
                    "gross 对可动用 USDT 峰值/最近": (
                        f"{_fmt_num((payload.get('margin') or {}).get('peak_gross_over_tradable'))}x / "
                        f"{_fmt_num((payload.get('margin') or {}).get('last_gross_over_tradable'))}x"
                        "（max_gross 仍按总权益裁剪，构造冻结中）"
                    ),
                    "insufficient_margin_rejections": (payload.get("margin") or {}).get("insufficient_margin"),
                    "rejections_by_code": json_dumps((payload.get("margin") or {}).get("rejections") or {}),
                },
            ),
            (
                "Liquidity to close (#3.9, reported only)",
                _liquidity_to_close_lines(payload.get("liquidity_to_close") or {}),
            ),
            (
                "Exits and pool (M-005 / M-006)",
                {
                    "exits": (payload.get("events") or {}).get("exit_count"),
                    "by_rule": json_dumps((payload.get("events") or {}).get("by_rule") or {}),
                    "pool_entered": json_dumps((payload.get("events") or {}).get("pool_entered") or []),
                    "pool_left": json_dumps((payload.get("events") or {}).get("pool_left") or []),
                    "pool_quarantined": json_dumps((payload.get("events") or {}).get("pool_quarantined") or []),
                    "unreachable_thresholds": json_dumps(
                        [
                            f"{row['symbol']} {row['rule']} k={row['k']:g} > {row['ceiling']:.2f}"
                            for row in (payload.get("exit_reachability") or {}).get("unreachable") or []
                        ]
                    ),
                },
            ),
            ("Noise scale (DL-EX0)", _noise_scale_lines(payload.get("noise_scale") or {})),
            ("Tail beside the sigma ruler (G4)", _tail_readings_lines(payload.get("tail") or {})),
            ("Event risk (#8.10, reported only)", _event_risk_lines(payload.get("event_risk") or {})),
            (
                "Exit counterfactuals (M-005, monitoring only)",
                {
                    "events": (payload.get("exit_counterfactual") or {}).get("events"),
                    "pending": (payload.get("exit_counterfactual") or {}).get("pending"),
                    "mean_24h_u": _fmt_num(
                        ((payload.get("exit_counterfactual") or {}).get("by_horizon") or {})
                        .get("24", {})
                        .get("mean_counterfactual_u")
                    ),
                    "mean_72h_u": _fmt_num(
                        ((payload.get("exit_counterfactual") or {}).get("by_horizon") or {})
                        .get("72", {})
                        .get("mean_counterfactual_u")
                    ),
                    "cost_saved_u": _fmt_num((payload.get("exit_counterfactual") or {}).get("cost_saved_u")),
                    "n_needed_for_decision": (payload.get("exit_counterfactual") or {}).get("n_needed_for_decision"),
                },
            ),
            (
                "Probe books (D-019)",
                {
                    str(row.get("book")): (
                        f"{row.get('status')} strategy={row.get('strategy')} "
                        f"pnl_{row.get('window_days')}d={_fmt_num(row.get('pnl'))} "
                        f"({_fmt_pct(row.get('pnl_pct'))} of equity, stop at -{_fmt_pct(row.get('max_loss'))}) "
                        f"days={_fmt_num(row.get('days_running'))}/{row.get('review_after_days')}"
                        # M-014 beside the countdown it belongs to.  The correlation was computed
                        # every day and read by nothing, and the one moment it decides anything is
                        # this review - `probe_correlation`'s own docstring says a sleeve that
                        # correlates closely with the main book is a tilt whose separate risk budget
                        # is a fiction.  2026-09-12: tsmom~flow 0.80 over 148 bars, review due 10-02.
                        + _probe_correlation_note(payload, str(row.get("strategy") or ""))
                        # The caliber the stop will read from the next batch window on, printed beside
                        # the one it reads today.  They differ by 17x in sigma, so the gap between the
                        # two numbers is the finding rather than a rounding detail.
                        + (
                            f" | 盯市 {row['marked_pnl_pct']:+.2%}/{row.get('marked_bars')} bars"
                            + ("（该口径下已越线）" if row.get("marked_would_stop") else "")
                            if row.get("marked_pnl_pct") is not None
                            else f" | 盯市读不出（{row.get('marked_why')}）"
                        )
                    )
                    for row in (payload.get("probes") or [])
                }
                or {"none": 0},
            ),
            (
                # Where per-symbol adaptation actually lives (D-037): the weight, not the leverage
                "Risk adaptation per symbol (M-015)",
                _risk_adaptation_lines(payload.get("risk_adaptation") or {}),
            ),
            ("Last targets", payload["last_targets"] or {"none": 0}),
        ],
    )


# What production code imports from this address: the assembly, and nine names `live_cmd` (and, for
# `collateral_share`, the engine) take from the area modules through here.  mypy's strict mode does
# not follow an implicit re-export, so these are declared; tests and scratchpad reach the rest of
# the contract through the imports at the top.
__all__ = [
    "PREREGISTRATION_EFFECTIVE_FROM",
    "_store_closes",
    "beta_markdown",
    "collateral_share",
    "daily_alerts",
    "daily_markdown",
    "daily_payload",
    "expectations_from_evidence",
    "latest_risk_adaptation",
    "preregistration_problems",
    "preregistration_skipped",
    "risk_adaptation_headline",
    "weekly_markdown",
    "weekly_payload",
]
