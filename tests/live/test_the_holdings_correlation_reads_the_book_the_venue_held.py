"""#3.4 / #8.9: the correlation between holdings is read off the book the venue held, never off the targets.

`starquant_live.report_risk.holdings_correlation` rebuilds the held book - the loop's managed positions - from a
cycle row's order and skip rows (`current_notional`), checks the rebuild against `gross_before`, and reads the
archive's hourly closes over 7 and 30 days.  The first fixture is the live row of bar 2026-09-24T17:00Z (demo
account), its plan section copied field for field from `cycles.jsonl`: one order - D3 closing AKEUSDT while
`targets` still carried it - and a NO_TRADE_BAND skip row for each of the other sixteen names.  The restart
row after it copies the keys of the one written over bar 2026-09-19T16:00Z.  Those are the shapes a hand-made
row gets wrong: the held weight sits up to 40% of itself away from the target, and a SKIPPED row can follow a
traded one on its bar.

The numbers are checked on the real August 2026 closes against an independent pandas computation, and the
effective number of bets against the three cases where Meucci's definition has a closed form.

The 2026-09-25 review added the rest: the reconciliation's tolerance pinned from both sides (the widest gap
the record has shown reads, the 2026-09-24T17:00Z book without AKEUSDT does not, nor does a NaN), a guard skip
walked past, the whole reading inside the catch, and where the archive stopped.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_live.report_risk import (
    _holdings_correlation_lines,
    _risk_budget_lines,
    effective_bets,
    holdings_correlation,
)
from starquant_live.reports import daily_alerts, daily_markdown, daily_payload
from starquant_live.state import StateStore

HOUR = 3_600_000
DAY = 24 * HOUR
BAR = 1_790_269_200_000  # 2026-09-24T17:00Z
EQUITY = 13084.90044379
GROSS_BEFORE = 13025.38607271

#: `targets` of that row: what the planner was told to steer to.
TARGETS = {
    "1000PEPEUSDT": 0.03516361348956981,
    "ADAUSDT": 0.05810928912053541,
    "AKEUSDT": 0.00996191299770606,
    "BNBUSDT": 0.1273755599505467,
    "BTCUSDT": 0.13024407624144288,
    "DOGEUSDT": 0.05787247436865216,
    "ENAUSDT": 0.03144063022894607,
    "ETHUSDT": 0.1189903454094451,
    "HYPEUSDT": 0.07389758815862102,
    "LSKUSDT": 0.015854283307372454,
    "NEARUSDT": 0.028080037870880363,
    "SOLUSDT": 0.09303910133362746,
    "SUIUSDT": 0.047349406575433885,
    "TRUMPUSDT": 0.049155128641002827,
    "UNIUSDT": 0.03032818335778529,
    "XRPUSDT": 0.06404499026827815,
    "ZECUSDT": 0.04547910396774065,
}

#: `orders` of that row, whole.
ORDER = {
    "avg_price": 0.0392107,
    "client_order_id": "bd-1790269200000-AKEUSDT",
    "current_notional": 115.49588661,
    "error": "",
    "executed_qty": "2943",
    "note": "",
    "order_id": "322986694",
    "price": 0.03924427,
    "quantity": "2943",
    "reduce_only": True,
    "side": "SELL",
    "status": "FILLED",
    "symbol": "AKEUSDT",
    "target_notional": 0.0,
    "target_weight": 0.0,
    "venue_status": "FILLED",
}

#: `skipped` of that row: symbol -> (current_notional, delta_notional, threshold), every one NO_TRADE_BAND.
BAND_HELD = {
    "BTCUSDT": (1689.81946327836, 14.411307734314505, 675.927785311344),
    "ETHUSDT": (1317.90918798396, 239.06763547081368, 527.163675193584),
    "ZECUSDT": (591.11936838882, 3.970179301841199, 236.447747355528),
    "SOLUSDT": (1261.4755747761, -44.06819644589541, 504.59022991044003),
    "XRPUSDT": (857.4409340640001, -19.41861248008115, 342.97637362560005),
    "HYPEUSDT": (1140.50482, -173.56223590824925, 456.20192800000007),
    "DOGEUSDT": (837.2497500000001, -79.99418445039805, 334.89990000000006),
    "BNBUSDT": (1424.8103289360001, 241.8861919889082, 569.9241315744001),
    "NEARUSDT": (453.669, -86.24450000167752, 181.4676),
    "UNIUSDT": (488.76599999999996, -91.92474012237074, 195.50639999999999),
    "SUIUSDT": (484.3335, 135.22877111208794, 193.73340000000002),
    "ENAUSDT": (337.39113936, 74.00637707577368, 134.956455744),
    "LSKUSDT": (216.16685295000002, -8.715134265389793, 86.46674118000001),
    "1000PEPEUSDT": (364.3229664, 95.78941535493209, 145.72918656),
    "TRUMPUSDT": (628.3515, 14.83846456921242, 251.3406),
    "ADAUSDT": (816.5598, -56.20553699838479, 326.62392),
}


def _band_held() -> list[dict[str, Any]]:
    """The row's sixteen NO_TRADE_BAND skip rows, under the row's own key names."""
    return [
        {
            "current_notional": current,
            "delta_notional": delta,
            "reason": "NO_TRADE_BAND",
            "symbol": symbol,
            "threshold": threshold,
        }
        for symbol, (current, delta, threshold) in BAND_HELD.items()
    ]


def _live_row(**overrides: Any) -> dict[str, Any]:
    """The live row of bar 2026-09-24T17:00Z, with every field this reading, or the report around it, reads."""
    return {
        "as_of_ms": BAR,
        "at": "2026-09-24T18:00:30+00:00",
        "bar": "2026-09-24T17:00:00+00:00",
        "bar_open_ms": BAR,
        "book_vol": {"clipped_risk_share": 0.0, "ex_ante": 0.6, "target": 0.6},
        "book_weights": {"flow_short": {}, "main": dict(TARGETS)},
        "books": {"flow": "flow_short", "tsmom": "main"},
        "contributions": {"flow": {}, "tsmom": dict.fromkeys(TARGETS, 1.0)},
        "dry_run": False,
        "equity": EQUITY,
        "gross_before": GROSS_BEFORE,
        "orders": [dict(ORDER)],
        "skip": False,
        "skipped": _band_held(),
        "targets": dict(TARGETS),
        **overrides,
    }


def _guard_skip(bar_ms: int, as_of_ms: int) -> dict[str, Any]:
    """What `LiveEngine.run_cycle` writes when a guard skips the bar: the whole record, with no plan in it.

    `evaluate_guards` sets `skip_cycle` on STALE_MARKET_DATA alone, and `run_cycle` returns before
    `plan_rebalance`, so `orders` and `skipped` stay the empty lists the record was built with.  The record
    has held none so far (0 of the 539 traded rows to 2026-09-25T05:00Z), so the keys follow the engine.
    """
    return _live_row(
        at=pd.Timestamp(bar_ms + HOUR + 31_000, unit="ms", tz="UTC").isoformat(),
        bar=pd.Timestamp(bar_ms, unit="ms", tz="UTC").isoformat(),
        bar_open_ms=bar_ms,
        as_of_ms=as_of_ms,
        guard_reasons=["STALE_MARKET_DATA"],
        skip=True,
        orders=[],
        skipped=[],
    )


def _restart_row() -> dict[str, Any]:
    """What a restart's immediate cycle writes over a bar already traded (the keys of 09-19T16:00Z's row)."""
    return {
        "at": "2026-09-24T18:41:45+00:00",
        "bar": "2026-09-24T17:00:00+00:00",
        "bar_open_ms": BAR,
        "dry_run": False,
        "late_seconds": 2505.204,
        "missed_rebalances": 0,
        "orders": [],
        "phase": "SKIPPED",
        "reason": "restart outside the rebalance window; this bar was already rebalanced",
        "targets": dict(TARGETS),
        "window_seconds": 85.861,
    }


def _store(tmp_path: Path, rows: list[dict[str, Any]]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for row in rows:
        store.append_cycle(row)
    return store


def _walks(symbols: list[str], *, end: int = BAR, bars: int = 31 * 24, seed: int = 20260925) -> dict[str, pd.Series]:
    """Hourly closes for each symbol: a common factor plus noise, so the correlations are neither 0 nor 1."""
    rng = np.random.default_rng(seed)
    index = np.arange(end - (bars - 1) * HOUR, end + HOUR, HOUR)
    market = rng.normal(0.0, 0.01, bars)
    return {
        symbol: pd.Series(100.0 * np.exp(np.cumsum(market + rng.normal(0.0, 0.01, bars))), index=index)
        for symbol in symbols
    }


def _day(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")


def test_the_weights_are_the_venues_positions_not_the_targets(tmp_path: Path) -> None:
    """`current_notional` over equity, checked against `gross_before`; the SKIPPED row after it is not the book."""
    closes = _walks(sorted(TARGETS))
    store = _store(tmp_path, [_live_row(), _restart_row()])
    block = holdings_correlation(store, "2026-09-24", closes=closes.__getitem__)

    assert block["measured"] is True and block["bar"] == "2026-09-24T17:00:00+00:00"
    assert block["coverage"] == pytest.approx(1.0, abs=1e-9)
    held = {symbol: current / EQUITY for symbol, (current, _, _) in BAND_HELD.items()}
    held["AKEUSDT"] = ORDER["current_notional"] / EQUITY
    assert block["weights"] == pytest.approx(held, rel=1e-12)
    # The band held ETHUSDT 1.8 points of equity under its target; the reading carries the position.
    assert block["weights"]["ETHUSDT"] == pytest.approx(0.1007198, abs=1e-6)
    assert TARGETS["ETHUSDT"] - block["weights"]["ETHUSDT"] > 0.018
    # AKEUSDT is in the book this snapshot measured; the cycle's own order closed it afterwards.
    assert block["weights"]["AKEUSDT"] == pytest.approx(0.0088267, abs=1e-6)
    assert (block["long"], block["short"]) == (17, 0)
    assert block["gross"] == pytest.approx(GROSS_BEFORE / EQUITY, rel=1e-9)
    assert block["book_vol"] == {"clipped_risk_share": 0.0, "ex_ante": 0.6, "target": 0.6}
    for label, bars in (("7d", 168), ("30d", 720)):
        window = block["windows"][label]
        assert window["measured"] is True and window["bars"] == bars
        assert window["all_pairs"]["pairs"] == window["same_side"]["pairs"] == 136
        assert window["opposite_side"] == {"pairs": 0, "weighted_mean": None}
        assert window["all_pairs"]["weighted_mean"] == pytest.approx(window["same_side"]["weighted_mean"], abs=1e-15)
        assert 1.0 <= window["effective_bets"] <= 17.0
        assert window["vs_btc"]["BTCUSDT"] == pytest.approx(1.0, abs=1e-12)
        assert window["last_bar"] == "2026-09-24T17:00:00+00:00"
    # The rows only ever see managed positions, and the weights are fractions of TOTAL equity: say both.
    held = _holdings_correlation_lines(block, {})["held book"]
    assert "gross 1.00x total equity (collateral included): the loop's managed positions at bar 2026-09-24T17" in held
    assert "venue" not in held


def test_on_real_august_closes_every_number_is_the_independent_pandas_reading(tmp_path: Path, august_dir: Path) -> None:
    """Three longs and a short on the real August 2026 closes, recomputed by pandas and by an SVD."""
    frames = {
        symbol: pd.read_parquet(august_dir / symbol / "1h.parquet")
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    }
    closes = {
        symbol: pd.Series(frame["close"].astype(float).to_numpy(), index=frame["open_time"].astype(int).to_numpy())
        for symbol, frame in frames.items()
    }
    anchor = int(frames["BTCUSDT"]["open_time"].iloc[-1])  # 2026-08-30T23:00Z, the fixture's last bar
    notional = {"BNBUSDT": 600.0, "BTCUSDT": 1_500.0, "ETHUSDT": 1_200.0, "SOLUSDT": -900.0}
    row = _live_row(
        as_of_ms=anchor,
        bar_open_ms=anchor,
        bar="2026-08-30T23:00:00+00:00",
        equity=10_000.0,
        gross_before=sum(abs(value) for value in notional.values()),
        orders=[],
        skipped=[
            {
                "current_notional": value,
                "delta_notional": 0.0,
                "reason": "NO_TRADE_BAND",
                "symbol": symbol,
                "threshold": 1.0,
            }
            for symbol, value in notional.items()
        ],
    )
    block = holdings_correlation(_store(tmp_path, [row]), _day(anchor), closes=closes.__getitem__)
    assert block["measured"] is True and (block["long"], block["short"]) == (3, 1)

    symbols = sorted(notional)
    weights = {symbol: notional[symbol] / 10_000.0 for symbol in symbols}
    returns = pd.DataFrame(closes).pct_change()
    for label, days in (("7d", 7), ("30d", 30)):
        window = returns[(returns.index > anchor - days * DAY) & (returns.index <= anchor)].dropna()
        reading = block["windows"][label]
        assert reading["bars"] == len(window) == (168 if days == 7 else 719)
        corr = window.corr()
        sums: dict[str, list[float]] = {"all": [0.0, 0.0], "same": [0.0, 0.0], "opposite": [0.0, 0.0]}
        for i, a in enumerate(symbols):
            for b in symbols[i + 1 :]:
                size = abs(weights[a]) * abs(weights[b])
                side = "same" if (weights[a] > 0) == (weights[b] > 0) else "opposite"
                for key in ("all", side):
                    sums[key][0] += size * float(corr.loc[a, b])
                    sums[key][1] += size
        assert reading["all_pairs"]["weighted_mean"] == pytest.approx(sums["all"][0] / sums["all"][1], rel=1e-9)
        assert reading["same_side"] == {
            "pairs": 3,
            "weighted_mean": pytest.approx(sums["same"][0] / sums["same"][1], rel=1e-9),
        }
        assert reading["opposite_side"] == {
            "pairs": 3,
            "weighted_mean": pytest.approx(sums["opposite"][0] / sums["opposite"][1], rel=1e-9),
        }
        for symbol in symbols:
            assert reading["vs_btc"][symbol] == pytest.approx(window[symbol].corr(window["BTCUSDT"]), rel=1e-9)
        # Meucci by another road: the principal components from an SVD of the centred returns, not `eigh`.
        centred = window[symbols].to_numpy() - window[symbols].to_numpy().mean(axis=0)
        _, singular, components = np.linalg.svd(centred, full_matrices=False)
        variance = singular**2 / (len(centred) - 1) * (components @ np.array([weights[s] for s in symbols])) ** 2
        shares = variance / variance.sum()
        assert reading["effective_bets"] == pytest.approx(math.exp(-(shares * np.log(shares)).sum()), rel=1e-9)
    # The fixture has to discriminate: a hedge reads well below the longs among themselves.
    assert (
        block["windows"]["30d"]["opposite_side"]["weighted_mean"]
        < block["windows"]["30d"]["same_side"]["weighted_mean"]
    )


def test_effective_bets_takes_its_closed_forms() -> None:
    """N equal uncorrelated bets read N, one factor reads 1, and 80/20 reads the exponential of its entropy."""
    sigma = np.array([0.5, 1.0, 2.0, 4.0])
    assert effective_bets(1.0 / sigma, np.diag(sigma**2)) == pytest.approx(4.0, rel=1e-12)
    loadings = np.array([1.0, 2.0, -0.5, 3.0])
    assert effective_bets(np.array([0.3, -0.1, 0.2, 0.25]), np.outer(loadings, loadings)) == pytest.approx(
        1.0, abs=1e-9
    )
    shares = np.array([0.8, 0.2])
    expected = math.exp(-(shares * np.log(shares)).sum())
    assert effective_bets(np.array([1.0, 0.5]), np.eye(2)) == pytest.approx(expected, rel=1e-12)
    assert effective_bets(np.array([1.0, 1.0]), np.zeros((2, 2))) is None


def _never(symbol: str) -> pd.Series:
    raise AssertionError(f"a refused book must not reach the archive ({symbol})")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        # 2026-09-10T23:00Z: skip rows written before they carried `current_notional`.
        (
            {
                "equity": 10683.76934132,
                "gross_before": 6253.8046597,
                "orders": [],
                "skipped": [
                    {
                        "delta_notional": -16.650476488857294,
                        "reason": "NO_TRADE_BAND",
                        "symbol": "BTCUSDT",
                        "threshold": 331.1607347217216,
                    },
                    {
                        "delta_notional": -57.99035104795837,
                        "reason": "NO_TRADE_BAND",
                        "symbol": "ETHUSDT",
                        "threshold": 261.2474720000001,
                    },
                ],
            },
            "0.00% of gross_before",
        ),
        # 2026-09-03: `gross_before` read 0.0 on an invested book - the zero `Position.notional`'s docstring records.
        ({"gross_before": 0.0}, "gross_before 0.0"),
        ({"gross_before": ORDER["current_notional"], "skipped": []}, "a correlation needs two"),
        # The same row with AKEUSDT (0.89% of gross) skipped for a reason that records no notional, under
        # `plan_rebalance`'s own keys for it.  The old 1% tolerance read this as sixteen names and 1.72
        # effective bets over 7 days, against seventeen and 2.10.
        (
            {
                "orders": [],
                "skipped": [
                    *_band_held(),
                    {"symbol": "AKEUSDT", "reason": "QUANTITY_ROUNDS_TO_ZERO", "delta_notional": -115.49588661},
                ],
            },
            "99.11% of gross_before",
        ),
        # A NaN passed `abs(nan - 1) > 0.01`, and its weights made `effective_bets` read 1.0.
        ({"skipped": [{**_band_held()[0], "current_notional": math.nan}, *_band_held()[1:]]}, "nan% of gross_before"),
        ({"gross_before": math.nan}, "gross_before nan"),
    ],
)
def test_a_book_the_rows_cannot_account_for_is_refused_not_read_short(
    tmp_path: Path, overrides: dict[str, Any], reason: str
) -> None:
    block = holdings_correlation(_store(tmp_path, [_live_row(**overrides)]), "2026-09-24", closes=_never)
    assert block["measured"] is False and reason in block["reason"]
    lines = _holdings_correlation_lines(block, {})
    # The engine's own statement comes off the row, not the archive, so it prints either way.
    assert (
        lines["measured"] == "no"
        and lines["book_vol ex_ante / target / clipped_risk_share"] == "60.00% / 60.00% / 0.00%"
    )


def test_the_widest_gap_the_record_has_shown_still_reads(tmp_path: Path) -> None:
    """0.055% (bar 2026-09-20T02:00Z) is two marks read a moment apart, not a missing name: the tolerance's floor."""
    row = _live_row(gross_before=GROSS_BEFORE * 1.00055)
    block = holdings_correlation(_store(tmp_path, [row]), "2026-09-24", closes=_walks(sorted(TARGETS)).__getitem__)
    assert block["measured"] is True and block["coverage"] == pytest.approx(1.0 / 1.00055, rel=1e-9)
    assert len(block["weights"]) == 17


def test_a_guard_skip_is_walked_past_and_a_later_day_is_never_read(tmp_path: Path) -> None:
    """A guard skip plans nothing, so its rows account for 0% of `gross_before`: the cycle before it is read.

    `liquidity_to_close`'s rule, day boundary included: a day whose only cycle was skipped reads the last one
    that planned before it, and a past day's report never sees a row written after it.
    """
    later = _live_row(as_of_ms=BAR + 2 * DAY, bar_open_ms=BAR + 2 * DAY, bar="2026-09-26T17:00:00+00:00")
    rows = [_live_row(), _guard_skip(BAR + HOUR, BAR), _guard_skip(BAR + DAY, BAR + DAY - HOUR), later]
    store = _store(tmp_path, rows)
    closes = _walks(sorted(TARGETS)).__getitem__
    for day in ("2026-09-24", "2026-09-25"):
        block = holdings_correlation(store, day, closes=closes)
        assert block["measured"] is True and block["bar"] == "2026-09-24T17:00:00+00:00", day
        assert block["coverage"] == pytest.approx(1.0, abs=1e-9)
    before = holdings_correlation(store, "2026-09-23", closes=_never)
    assert before["measured"] is False and before["reason"] == "no traded cycle on or before 2026-09-23"


@pytest.mark.parametrize(
    ("overrides", "error"),
    [({"skipped": ["not an entry"]}, "AttributeError"), ({"equity": "n/a"}, "ValueError")],
)
def test_a_garbled_row_costs_the_block_and_not_the_report(
    tmp_path: Path, overrides: dict[str, Any], error: str
) -> None:
    """The catch covers the rebuild too, not only the archive: it runs inside the hourly check."""
    block = holdings_correlation(_store(tmp_path, [_live_row(**overrides)]), "2026-09-24", closes=_never)
    assert block["measured"] is False and block["reason"].startswith(f"{error}: ")
    assert _holdings_correlation_lines(block, {})["measured"] == "no"


def test_where_the_archive_stopped_is_printed_and_both_windows_lose_those_bars(tmp_path: Path) -> None:
    """The archive syncs once a day, so it can stop a day short of the decision bar: the page has to say where.

    Seven bars is the lag the 2026-09-24 report carried when rendered on 09-25: its last cycle decided on
    23:00Z and the archive stopped at the 16:00Z bar of the 17:20Z sync.
    """
    short = _walks(sorted(TARGETS), end=BAR - 7 * HOUR)
    block = holdings_correlation(_store(tmp_path / "a", [_live_row()]), "2026-09-24", closes=short.__getitem__)
    assert block["closes_through_ms"] == BAR - 7 * HOUR and block["closes_lag_bars"] == 7
    assert (block["windows"]["7d"]["bars"], block["windows"]["30d"]["bars"]) == (168 - 7, 720 - 7)
    assert block["windows"]["7d"]["last_bar"] == block["windows"]["30d"]["last_bar"] == "2026-09-24T10:00:00+00:00"
    assert _holdings_correlation_lines(block, {})["收盘价截至"].startswith(
        "归档最后一根 2026-09-24T10:00:00+00:00，比决策 bar 早 7 根。"
    )
    level = holdings_correlation(
        _store(tmp_path / "b", [_live_row()]), "2026-09-24", closes=_walks(sorted(TARGETS)).__getitem__
    )
    assert level["closes_through_ms"] == BAR and level["closes_lag_bars"] == 0
    assert "，就是决策 bar。" in _holdings_correlation_lines(level, {})["收盘价截至"]


def test_a_window_short_of_half_its_bars_or_on_a_frozen_price_says_so(tmp_path: Path) -> None:
    three_days = _walks(sorted(TARGETS), bars=72)
    block = holdings_correlation(_store(tmp_path / "a", [_live_row()]), "2026-09-24", closes=three_days.__getitem__)
    for label, window in block["windows"].items():
        assert window["measured"] is False and "under half the window" in window["why"], label
    frozen = _walks(sorted(TARGETS))
    frozen["LSKUSDT"] = pd.Series(0.4, index=frozen["LSKUSDT"].index)
    block = holdings_correlation(_store(tmp_path / "b", [_live_row()]), "2026-09-24", closes=frozen.__getitem__)
    assert all(window["why"] == "no price movement in LSKUSDT" for window in block["windows"].values())
    assert "not measured (no price movement in LSKUSDT)" in _holdings_correlation_lines(block, {}).values()


def test_the_daily_report_prints_it_after_m014_and_pages_on_nothing(tmp_path: Path) -> None:
    closes = _walks(sorted(TARGETS))
    store = _store(tmp_path, [_live_row(), _restart_row()])
    payload = daily_payload(store, "2026-09-24", closes=closes.__getitem__, data_root=tmp_path / "data")
    keys = list(payload)
    assert keys.index("holdings_correlation") == keys.index("probe_correlation") + 1
    assert payload["holdings_correlation"]["measured"] is True

    markdown = daily_markdown(payload)
    m014 = markdown.index("## Probe correlation (M-014)")
    ours = markdown.index("## Holdings correlation (#3.4 / #8.9, reported only)")
    assert m014 < ours < markdown.index("## Clock (D-025)") and markdown.count("\n## ", m014, ours) == 0
    # Quoted, not recomputed: the realised line is the Risk budget (P13) section's own text.
    assert f"| realised vol (P13, quoted) | {_risk_budget_lines(payload['risk_budget'])['realised vol']} |" in markdown
    # One cycle, two snapshots: each section says which one it took and points at the other.
    assert payload["liquidity_to_close"]["bar"] == payload["holdings_correlation"]["bar"]
    assert "| 与 #3.9 的快照不同 | 这里是本周期下单前的持仓" in markdown[ours:]

    without = {key: value for key, value in payload.items() if key != "holdings_correlation"}
    assert daily_alerts(payload) == daily_alerts(without)
