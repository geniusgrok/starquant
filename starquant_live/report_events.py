"""#8.10 event risk: the stablecoin peg, the loop's incidents on its path to the venue, and extreme moves.

Checklist item 8.10 of `docs/analysis/2026-09-23-external-prompt-checklist-vs-starquant.md` asks for a geopolitical
risk framework.  In a USDⓈ-M book its counterparts are a venue incident, a regulatory action and a stablecoin
leaving its peg.  The 2026-09-23 inventory found reactions (D-031's quarantine, the loop's breaker) and no
reading.  These are the readings.  A rule that trades on them is a construction change: its draft
pre-registration is `docs/analysis/2026-09-25-event-risk-rule-prereg-draft.md`, and nothing here acts.

Reported, never alerted.  No threshold was registered before these went live, and one picked after reading the
number is not a threshold, so `daily_alerts` never reads this block.  Three readings, each behind its own catch:
one that cannot be read costs its own block, not the report.

  stablecoin  Binance spot USDC/USDT, off the archive (`stablecoin_peg`)
  venue       what the loop recorded going wrong on its path to the exchange (`venue_incidents`); no network
  market      BTCUSDT and an equal-weight basket of the managed universe, the newest hourly moves in units of
              their own volatility (`market_extremes`)

Two of the three read the archive, and the archive is not the loop's feed.  `deploy/com.starquant.data.plist` syncs
it once a day at 01:20 host time (17:20Z on this +08:00 host) and keeps closed bars only, so its newest bar is
that day's 16:00Z.  In the hourly check it runs 1 to 24 bars behind the decision bar - the sawtooth
`holdings_correlation` documents.  These windows end at the archive's newest bar rather than at the decision bar,
so they never read short, and `lag_bars` says how far behind that bar is.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starquant_data.store import SPOT_KLINE_KIND, KlineStore
from starquant_live.report_common import DAY_MS, _cycles, _day_end_ms, _day_of, _store_closes
from starquant_live.risk_budget import one_row_per_order
from starquant_live.scheduler import BACKOFF_REASON
from starquant_live.state import StateStore

HOUR_MS = DAY_MS // 24

# Binance spot, the price of one USDC in USDT: the only stablecoin pair the archive holds.  The daily `starquant data
# spot` maps it whatever the kline store holds - `starquant_data.spot.ALWAYS_MAPPED` pins it, and a test keeps this
# name in that tuple - so pruning `klines/USDCUSDT/` no longer stops it; an explicit `--symbols` run still skips
# it that day, and `lag_bars` is what would show it.  The series has a 3,996-hour hole, from
# 2022-09-26T02:00Z to 2023-03-11T14:00Z, so it holds nothing for FTX (2022-11) and picks USDC's own depeg up at
# its first bar back, whose low was already 0.882.
PEG_PAIR = "USDCUSDT"


# The peg's windows as (label, bars): hourly bars ending at the archive's newest one.
PEG_WINDOWS = (("24h", 24), ("30d", 720))


# The market reading scores the newest `MARKET_RECENT_BARS` hourly log returns against the standard deviation of
# the `MARKET_BASELINE_BARS` before them.  The scored stretch stays out of its own baseline: a crash inside the
# window it is measured against would widen the ruler it is read with.
MARKET_BENCHMARK = "BTCUSDT"


MARKET_RECENT_BARS = 24


MARKET_BASELINE_BARS = 720


# How far behind the report day's last bar the archive may stop and still be read: about a week of missed syncs.
# Further back and the block says where the archive stopped instead of reading a window that is mostly the past.
ARCHIVE_SLACK_BARS = 168


# The venue reading's windows, in UTC days ending with the report's own day.
INCIDENT_DAYS = (1, 7, 30)


# What the loop writes when something on its path to the venue goes wrong, in the order the page prints them.
# Each is a row the loop already writes; none of them asks the venue anything.
#   failed_cycles        phase ERROR: M-001's failure, the rows `live status --check` counts
#   backoff_missed_bars  a SKIPPED row the failure backoff wrote for a bar it slept through
#   stale_data_skips     guard STALE_MARKET_DATA: the klines fetched were too old to trade on
#   inputs_dropped       symbols whose klines the cycle could not use (a delisting lands here too)
#   orders_not_filled    a trades row with an error and a status other than FILLED: M-007's predicate
#   quarantines          D-031: a symbol the venue kept rejecting while other symbols filled
#   pool_refresh_errors  the daily re-rank failed and the loop kept the previous universe
SIGNALS = (
    "failed_cycles",
    "backoff_missed_bars",
    "stale_data_skips",
    "inputs_dropped",
    "orders_not_filled",
    "quarantines",
    "pool_refresh_errors",
)


SIGNAL_ZH = {
    "failed_cycles": "周期失败",
    "backoff_missed_bars": "退避吃掉的 bar",
    "stale_data_skips": "行情陈旧跳过",
    "inputs_dropped": "K 线拿不到",
    "orders_not_filled": "没成交的订单",
    "quarantines": "隔离",
    "pool_refresh_errors": "池子重排失败",
}


_HTTP_503 = re.compile(r"\b503\b")


def event_risk(
    store: StateStore,
    day: str,
    *,
    closes: Callable[[str], pd.Series] | None = None,
    root: str | Path = ".starquant/data",
) -> dict[str, Any]:
    """#8.10 in the daily report: the three readings, and the decision bar the archive's lag is counted from.

    The archive windows end at the newest bar the archive holds on or before the day's last bar, so a report for a
    past day never reads a bar that day had not seen.  They do not end at the decision bar - the newest bar the
    loop traded on or before `day` - because a loop that is down is exactly when the market reading must not stop
    with it.  The decision bar only dates the lag: behind it the archive reads `lag_bars` > 0, and ahead of it
    (the loop has not traded since) below zero.
    """
    decision = _isolated(lambda: {"ms": _decision_bar(store, day)})
    decision_ms = decision.get("ms")
    anchor = _day_end_ms(day) - HOUR_MS
    return {
        "decision_bar": _iso(decision_ms) if decision_ms is not None else None,
        "stablecoin": _isolated(lambda: stablecoin_peg(anchor, root=root, decision_ms=decision_ms)),
        "venue": _isolated(lambda: venue_incidents(store, day)),
        "market": _isolated(
            lambda: market_extremes(store, day, anchor, closes=closes, root=root, decision_ms=decision_ms)
        ),
    }


def _isolated(reading: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    # Broad on purpose, for `holdings_correlation`'s reason: this runs inside the hourly check, and a reading
    # that gates nothing must not take the report down with it.
    try:
        return reading()
    except Exception as exc:
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _decision_bar(store: StateStore, day: str) -> int | None:
    rows = [row for row in _cycles(store) if (_day_of(row) or "") <= day]
    stamp = (rows[-1].get("as_of_ms") or rows[-1].get("bar_open_ms")) if rows else None
    return int(stamp) if stamp else None


def _iso(ms: int | float) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).isoformat()


def _lag(decision_ms: int | None, through: int) -> int | None:
    return (decision_ms - through) // HOUR_MS if decision_ms is not None else None


def _too_stale(what: str, through: int, anchor_ms: int) -> str:
    behind = (anchor_ms - through) // HOUR_MS
    return f"{what}归档停在 {_iso(through)}，比这一天最后一根 bar 早 {behind} 根，超过 {ARCHIVE_SLACK_BARS} 根不读"


def stablecoin_peg(anchor_ms: int, *, root: str | Path, decision_ms: int | None) -> dict[str, Any]:
    """USDC/USDT on Binance spot: the newest close, and the widest deviation from 1 in each window, in bps.

    The deviation is the pair's price minus one, so its sign says which coin is cheap.  Above zero USDT is cheaper
    than USDC, the side a USDT depeg moves it to.  Below zero USDC is cheaper, the side 2023-03 moved it to.  Two
    coins leaving the dollar together do not move it, and the archive holds no fiat pair that would.  The widest
    deviation reads each bar's high and low rather than its close, so a one-bar wick counts: on 2025-10-10 the
    21:00Z bar printed a low of 0.985 while no close that day was more than 44 bps from 1.  `median_abs_close_bps`
    is the window's ordinary level beside it.
    """
    store = KlineStore(root, kind=SPOT_KLINE_KIND)
    widest = max(bars for _, bars in PEG_WINDOWS)
    start = anchor_ms - (ARCHIVE_SLACK_BARS + widest) * HOUR_MS
    frame = store.load(PEG_PAIR, "1h", start_ms=start, end_ms=anchor_ms + HOUR_MS)
    frame = frame.dropna(subset=["high", "low", "close"])
    if frame.empty:
        newest = store.last_open_time(PEG_PAIR, "1h")
        where = _iso(newest) if newest is not None else "没有"
        return {
            "measured": False,
            "reason": f"这一天最后一根 bar 之前 {ARCHIVE_SLACK_BARS + widest} 根里没有 {PEG_PAIR} 现货 bar（归档最新一根：{where}）",
        }
    through = int(frame["open_time"].iloc[-1])
    if anchor_ms - through > ARCHIVE_SLACK_BARS * HOUR_MS:
        return {"measured": False, "reason": _too_stale(PEG_PAIR + " 现货", through, anchor_ms)}
    close = float(frame["close"].iloc[-1])
    return {
        "measured": True,
        "reason": None,
        "pair": PEG_PAIR,
        "market": "spot",
        "last_bar": _iso(through),
        "last_close": close,
        "last_deviation_bps": (close - 1.0) * 1e4,
        "windows": {label: _peg_window(frame, through, bars) for label, bars in PEG_WINDOWS},
        "through_ms": through,
        "lag_bars": _lag(decision_ms, through),
    }


def _peg_window(frame: pd.DataFrame, through: int, bars: int) -> dict[str, Any]:
    window = frame[frame["open_time"] > through - bars * HOUR_MS]
    opens = window["open_time"].to_numpy(dtype="int64")
    high = (window["high"].to_numpy(dtype=float) - 1.0) * 1e4
    low = (window["low"].to_numpy(dtype=float) - 1.0) * 1e4
    up, down = int(high.argmax()), int(low.argmin())
    # The side that strayed further; a tie goes to the high, which only matters for a window that never moved.
    deviation, at = (float(high[up]), opens[up]) if high[up] >= -low[down] else (float(low[down]), opens[down])
    return {
        "bars": len(window),
        "of": bars,
        "max_deviation_bps": deviation,
        "max_deviation_bar": _iso(int(at)),
        "median_abs_close_bps": float(np.median(np.abs(window["close"].to_numpy(dtype=float) - 1.0)) * 1e4),
    }


def venue_incidents(store: StateStore, day: str) -> dict[str, Any]:
    """What the loop itself recorded going wrong on its way to the exchange, over 1, 7 and 30 UTC days.

    Read off `cycles.jsonl` and `trades.jsonl` and nothing else: no request is made, so this reading cannot fail
    for the reason it measures.  Rows are dated by `_day_of`, the rule the rest of the report buckets them by; a
    dry run is not the loop doing its job and is skipped, as M-001 skips it.

    `bars` counts the distinct bars the loop wrote any row for, and `incident_bars` those on which at least one
    signal in `SIGNALS` fired, so a bar that failed and was then re-run by a restart counts once.  A failed
    cycle's text is kept whole in `last_incident` and split two ways in the windows: by its exception type (the
    text before the first colon) and by whether it names an HTTP 503.  Neither says whether the proxy, the
    network or Binance produced it - `docs/RESEARCH_LOG.md`'s sections on the 1082 proxy are where that was
    argued - and a failure a retry absorbed inside the bar leaves no row at all.  With the proxy probe removed
    on 2026-09-22 nothing in the record sees the minute-scale 503 clusters (median 67 s in its last reading);
    one point per bar is the resolution here.
    """
    rows = [row for row in store.read_jsonl(store.cycles_path) if not row.get("dry_run")]
    trades = [dict(row) for row in one_row_per_order(store.read_jsonl(store.trades_path))]
    end = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    windows: dict[str, Any] = {}
    newest: tuple[int, str, str, str] | None = None
    for days in INCIDENT_DAYS:
        first = (end - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        inside = [row for row in rows if first <= (_day_of(row) or "") <= day]
        events = _incident_events(inside, [row for row in trades if first <= (_day_of(row) or "") <= day])
        windows[f"{days}d"] = _incident_window(inside, events)
        if days == max(INCIDENT_DAYS) and events:
            # The newest by bar, then by when it was written; a row with no bar sorts before every bar.
            newest = max(((bar if bar is not None else -1), at, signal, detail) for bar, signal, detail, at in events)
    last = None
    if newest is not None:
        bar, at, signal, detail = newest
        last = {"bar": _iso(bar) if bar >= 0 else None, "at": at, "signal": signal, "detail": detail}
    return {"measured": True, "reason": None, "windows": windows, "last_incident": last}


def _incident_events(
    rows: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]]
) -> list[tuple[int | None, str, str, str]]:
    """Every signal in the rows as (bar, signal, detail, at)."""
    events: list[tuple[int | None, str, str, str]] = []
    for row in rows:
        bar, at = _bar_of(row), str(row.get("at") or "")
        if row.get("phase") == "ERROR":
            events.append((bar, "failed_cycles", str(row.get("error") or "未记录"), at))
        if row.get("phase") == "SKIPPED" and row.get("reason") == BACKOFF_REASON:
            events.append((bar, "backoff_missed_bars", BACKOFF_REASON, at))
        if "STALE_MARKET_DATA" in (row.get("guard_reasons") or []):
            events.append((bar, "stale_data_skips", "STALE_MARKET_DATA", at))
        if dropped := (row.get("dropped_inputs") or {}).get("symbols"):
            events.append((bar, "inputs_dropped", ", ".join(str(symbol) for symbol in dropped), at))
        if quarantined := row.get("quarantined"):
            events.append((bar, "quarantines", ", ".join(str(symbol) for symbol in quarantined), at))
        update = row.get("universe_update")
        if isinstance(update, Mapping) and update.get("error"):
            events.append((bar, "pool_refresh_errors", str(update["error"]), at))
    for trade in trades:
        if trade.get("error") and str(trade.get("status")) != "FILLED":
            detail = f"{trade.get('symbol')} {trade.get('status')}: {trade.get('error')}"
            events.append((_bar_of(trade), "orders_not_filled", detail, str(trade.get("at") or "")))
    return events


def _bar_of(row: Mapping[str, Any]) -> int | None:
    bar = row.get("bar_open_ms")
    return int(bar) if isinstance(bar, int | float) else None


def _incident_window(
    rows: Sequence[Mapping[str, Any]], events: Sequence[tuple[int | None, str, str, str]]
) -> dict[str, Any]:
    failed = [detail for _, signal, detail, _ in events if signal == "failed_cycles"]
    failed_bars = sorted({bar for bar, signal, _, _ in events if signal == "failed_cycles" and bar is not None})
    longest = run = 0
    for previous, bar in zip([None, *failed_bars], failed_bars, strict=False):
        run = run + 1 if previous is not None and bar - previous == HOUR_MS else 1
        longest = max(longest, run)
    return {
        "bars": len({bar for bar in (_bar_of(row) for row in rows) if bar is not None}),
        "incident_bars": len({bar for bar, _, _, _ in events if bar is not None}),
        "counts": {signal: sum(1 for event in events if event[1] == signal) for signal in SIGNALS},
        "failed_by_type": dict(
            sorted(Counter(detail.split(":", 1)[0].strip() or "未记录" for detail in failed).items())
        ),
        "failed_with_503": sum(1 for detail in failed if _HTTP_503.search(detail)),
        "longest_failure_run_bars": longest,
    }


def market_extremes(
    store: StateStore,
    day: str,
    anchor_ms: int,
    *,
    closes: Callable[[str], pd.Series] | None,
    root: str | Path,
    decision_ms: int | None,
) -> dict[str, Any]:
    """BTCUSDT and the managed universe's equal-weight basket: the newest hourly moves in units of their own vol.

    Per series, `z` is an hourly log return over the standard deviation of the 720 hourly log returns before the
    newest 24 (30 days, `ddof=1`), and the 24-hour move is the sum of those 24 over that deviation times the root
    of their count.  The basket's return is the plain mean of its members' log returns on the bar, over the
    members that printed both closes; its members are the universe of the last traded cycle on or before `day`,
    today's names read back over 30 days.  A member the archive does not hold is named in `missing`, not fatal.

    Every series ends at the benchmark's newest bar in the archive, so the basket and BTCUSDT read the same hours.
    The archive's closes are mainnet's, the same prices research and the loop's model read.
    """
    loader = closes or _store_closes(root, "1h")
    span = ARCHIVE_SLACK_BARS + MARKET_BASELINE_BARS + MARKET_RECENT_BARS + 1
    grid = range(anchor_ms - span * HOUR_MS, anchor_ms + HOUR_MS, HOUR_MS)
    prices = {MARKET_BENCHMARK: loader(MARKET_BENCHMARK).reindex(grid).astype(float)}
    printed = prices[MARKET_BENCHMARK].dropna()
    if printed.empty:
        return {"measured": False, "reason": f"这一天最后一根 bar 之前 {span} 根里归档没有 {MARKET_BENCHMARK} 的收盘价"}
    through = int(printed.index[-1])
    if anchor_ms - through > ARCHIVE_SLACK_BARS * HOUR_MS:
        return {"measured": False, "reason": _too_stale(MARKET_BENCHMARK + " ", through, anchor_ms)}
    members = _managed_universe(store, day)
    missing: list[str] = []
    for symbol in members:
        try:
            prices.setdefault(symbol, loader(symbol).reindex(grid).astype(float))
        except FileNotFoundError:
            missing.append(symbol)
    frame = pd.DataFrame(prices)
    returns = pd.DataFrame(np.log(frame.to_numpy(dtype=float)), index=frame.index, columns=frame.columns).diff()
    held = [symbol for symbol in members if symbol not in missing]
    series: dict[str, Any] = {MARKET_BENCHMARK: _scored(returns[MARKET_BENCHMARK], through)}
    if held:
        series["basket"] = {
            **_scored(returns[held].mean(axis=1), through),
            "members": len(held),
            "printed_last_bar": int(returns[held].loc[through].notna().to_numpy().sum()),
        }
    else:
        series["basket"] = {"measured": False, "why": "没有 universe 成员可读" if not members else "成员都不在归档里"}
    return {
        "measured": True,
        "reason": None,
        "series": series,
        "universe": len(members),
        "missing": missing,
        "through_ms": through,
        "lag_bars": _lag(decision_ms, through),
    }


def _managed_universe(store: StateStore, day: str) -> list[str]:
    rows = [row for row in _cycles(store) if row.get("universe") and (_day_of(row) or "") <= day]
    return [str(symbol) for symbol in rows[-1]["universe"]] if rows else []


def _scored(returns: pd.Series, through: int) -> dict[str, Any]:
    opens = returns.index.to_numpy(dtype="int64")
    cut = through - MARKET_RECENT_BARS * HOUR_MS
    recent = returns[(opens > cut) & (opens <= through)]
    baseline = returns[(opens > cut - MARKET_BASELINE_BARS * HOUR_MS) & (opens <= cut)].dropna()
    if len(baseline) < MARKET_BASELINE_BARS // 2:
        return {"measured": False, "why": f"基线只有 {len(baseline)} 根，不到 {MARKET_BASELINE_BARS} 根的一半"}
    sigma = float(baseline.std(ddof=1))
    scored = recent.dropna()
    if not sigma > 0.0 or scored.empty:
        return {"measured": False, "why": "基线里价格没动过" if not sigma > 0.0 else "最近 24 根没有一根读得出收益"}
    worst = int(scored.abs().idxmax())
    last = float(recent.loc[through])
    total = float(scored.sum())
    return {
        "measured": True,
        "sigma_1h": sigma,
        "baseline_bars": len(baseline),
        "last_z": last / sigma if math.isfinite(last) else None,
        "last_return": math.expm1(last) if math.isfinite(last) else None,
        "max_z": float(scored.loc[worst]) / sigma,
        "max_z_bar": _iso(worst),
        "max_z_return": math.expm1(float(scored.loc[worst])),
        "recent_bars": len(scored),
        "return_24h": math.expm1(total),
        "z_24h": total / (sigma * math.sqrt(len(scored))),
    }


def _event_risk_lines(block: Mapping[str, Any]) -> dict[str, Any]:
    """#8.10 on the page: the peg, the venue path, the market, and what each of them cannot see."""
    lines: dict[str, Any] = {}
    peg = block.get("stablecoin") or {}
    if peg.get("measured"):
        lines["USDC/USDT 现货，最新"] = (
            f"{peg['last_close']:.5f}（{peg['last_deviation_bps']:+.1f} bps），bar {peg['last_bar']}"
        )
        for window in (peg.get("windows") or {}).values():
            lines[f"USDC/USDT 近 {window['of']} 根"] = (
                f"最大偏离 {window['max_deviation_bps']:+.1f} bps（bar {window['max_deviation_bar']}）；"
                f"收盘偏离的中位 {window['median_abs_close_bps']:.1f} bps；有数据 {window['bars']}/{window['of']} 根"
            )
        lines["USDC/USDT 归档截至"] = _lag_line(peg)
    else:
        lines["USDC/USDT 现货"] = f"读不出：{peg.get('reason') or '没有算'}"
    lines["脱锚读法"] = (
        "偏离 = USDC/USDT − 1。为正：USDT 比 USDC 便宜，USDT 脱锚往这边走。为负：USDC 比 USDT 便宜，2023-03 往这边走。"
        "两个币一起离开美元时它不动：归档里没有法币交易对。最大偏离读每根 bar 的最高价与最低价，插针也算。"
        "这条序列 2022-09-26 至 2023-03-11 有一段 3,996 小时的缺口，FTX 那段没有数据。"
    )
    venue = block.get("venue") or {}
    if venue.get("measured"):
        for key, label in (("1d", "当日"), ("7d", "近 7 天"), ("30d", "近 30 天")):
            lines[f"交易所事故，{label}"] = _incident_line((venue.get("windows") or {}).get(key) or {})
        last = venue.get("last_incident")
        lines["交易所事故，最近一次"] = (
            f"bar {last['bar']}，{SIGNAL_ZH.get(str(last['signal']), last['signal'])}：{last['detail']}"
            if last
            else "近 30 天没有"
        )
    else:
        lines["交易所事故"] = f"读不出：{venue.get('reason') or '没有算'}"
    lines["交易所事故读法"] = (
        "只读循环自己写下的 cycles.jsonl 与 trades.jsonl，不联网。周期失败与 M-001（live status --check）同一口径，"
        "那边按 24 小时成功率告警，M-Q03 按失败 bar 告警，这里不告警。一根 bar 内重试成功的失败不留行。"
        "分钟级的代理 503 簇在这里看不见：代理探针 2026-09-22 已撤，这里每根 bar 只有一个点。"
        "失败文本分不出是代理、网络还是币安，见 RESEARCH_LOG 里 1082 代理那几节。"
    )
    market = block.get("market") or {}
    if market.get("measured"):
        series = market.get("series") or {}
        basket = series.get("basket") or {}
        lines[MARKET_BENCHMARK] = _market_line(series.get(MARKET_BENCHMARK) or {})
        lines[f"universe 等权篮子（{basket.get('members', 0)}/{market.get('universe')} 个）"] = _market_line(basket)
        if market.get("missing"):
            lines["归档里没有的成员"] = "、".join(str(symbol) for symbol in market["missing"])
        lines["行情归档截至"] = _lag_line(market)
    else:
        lines["极端行情"] = f"读不出：{market.get('reason') or '没有算'}"
    lines["极端行情读法"] = (
        f"z = 小时对数收益 ÷ 基线标准差。基线是最近 {MARKET_RECENT_BARS} 根之前的 {MARKET_BASELINE_BARS} 根，"
        "不含被打分的那几根，行情本身不抬高分母。24h 的 z 按根数开方放大。"
        "篮子是 universe 成员小时对数收益的等权平均。只报告，不告警：没有预登记的阈值。"
    )
    return lines


def _incident_line(window: Mapping[str, Any]) -> str:
    counts = window.get("counts") or {}
    parts: list[str] = []
    if failed := int(counts.get("failed_cycles") or 0):
        types = "，".join(f"{name} {count}" for name, count in (window.get("failed_by_type") or {}).items())
        parts.append(
            f"周期失败 {failed}（{types}；含 503 的 {window.get('failed_with_503')}；"
            f"最长连续 {window.get('longest_failure_run_bars')} 根）"
        )
    parts += [f"{SIGNAL_ZH[signal]} {counts[signal]}" for signal in SIGNALS[1:] if counts.get(signal)]
    return f"有事故的 bar {window.get('incident_bars', 0)}/{window.get('bars', 0)}" + (
        "：" + "；".join(parts) if parts else ""
    )


def _market_line(series: Mapping[str, Any]) -> str:
    if not series.get("measured"):
        return f"读不出：{series.get('why') or '没有算'}"
    last = (
        f"最新一根 z {series['last_z']:+.2f}（{series['last_return']:+.2%}）"
        if series.get("last_z") is not None
        else "最新一根读不出收益"
    )
    return (
        f"{last}；近 {series['recent_bars']} 根里绝对值最大的 z {series['max_z']:+.2f}"
        f"（{series['max_z_return']:+.2%}，bar {series['max_z_bar']}）；"
        f"24h {series['return_24h']:+.2%}，z {series['z_24h']:+.2f}；"
        f"σ_1h {series['sigma_1h']:.3%}（{series['baseline_bars']} 根）"
    )


def _lag_line(block: Mapping[str, Any]) -> str:
    lag = block.get("lag_bars")
    where = f"归档最后一根 {_iso(block['through_ms'])}"
    if lag is None:
        where += "；到这一天为止循环还没有成交周期，没有决策 bar 可比"
    elif lag < 0:
        where += f"，比决策 bar 晚 {-lag} 根：循环在那之后没有成交过"
    else:
        where += f"，比决策 bar 早 {lag} 根" if lag else "，就是决策 bar"
    return where + "。归档每天同步一次（本机 01:20，即 17:20Z），最新一根是当天 16:00Z。"
