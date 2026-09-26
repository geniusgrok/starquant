"""Checklist 3.9: what closing each held position would take, read off the book the last cycle left.

`starquant_live.report_risk.liquidity_to_close` answers "how long, and at what cost" position by position.
These tests pin the three places it could be quietly wrong:

* WHICH BOOK.  Cycle rows carry no `positions`; the reading takes each `skipped` / `orders` entry's
  `current_notional` and applies the cycle's own fills.  The first test runs on the record's row for the
  2026-09-24T17:00Z bar, fields copied verbatim, because that row closed AKEUSDT: a reading that forgot
  the fills would list it as a position still to close.
* WHICH RULERS.  The hourly volume is `LiveEngine._liquidity`'s and the impact is `impact_costs`', each
  checked against the owner's own code rather than against a second derivation of the same formula.
* WHAT A FULL CLOSE IS.  One order for the whole position, whatever the cap - so the bars column is about
  pure reductions only.  Pinned against `plan_rebalance` on the reading's own numbers, since that sentence
  is what the report prints.  Whether the band can hold a close back is a knob (`exempt_crossings`), so the
  sentence is written from the knob on record, and pinned against the planner both ways.

The 2026-09-25 review added the record's other shapes: a restart's "already submitted" order, which pairs
the new plan's side with the old order's fill (line 10 of the record), entries that carry no notional,
and the impact model built from `config/costs.yaml` through the entry research uses.
"""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from starquant_alpha.backtest import asset_returns, impact_costs
from starquant_alpha.panel import Panel
from starquant_data.store import KlineStore
from starquant_live.composition import impact_model
from starquant_live.engine import LiveEngine
from starquant_live.execution import execute_order
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_live.report_risk import (
    ALREADY_SUBMITTED,
    LIQUIDITY_WINDOW_BARS,
    _liquidity_to_close_lines,
    liquidity_to_close,
)
from starquant_live.reports import daily_alerts, daily_markdown, daily_payload
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml
from starquant_shared.types import Position
from tests.fakes.fake_venue import DEFAULT_RULES, FakeVenue
from tests.live.fakes import FakeClock

ROOT = Path(__file__).resolve().parents[2]
HOUR = 3_600_000

# `.starquant/live/cycles.jsonl`, the row for the 2026-09-24T17:00Z bar (line 574 of the copy taken at
# 2026-09-24T18:48Z), with the fields this reading reads copied verbatim.  It planned a single order -
# AKEUSDT, a full close - and held the other sixteen names inside the band.  Every `skipped` entry had reason
# NO_TRADE_BAND; its four numbers are listed in the row's order as (symbol, current_notional, delta_notional,
# threshold) and rebuilt under the row's own key names below.
BAND_HELD = (
    ("BTCUSDT", 1689.81946327836, 14.411307734314505, 675.927785311344),
    ("ETHUSDT", 1317.90918798396, 239.06763547081368, 527.163675193584),
    ("ZECUSDT", 591.11936838882, 3.970179301841199, 236.447747355528),
    ("SOLUSDT", 1261.4755747761, -44.06819644589541, 504.59022991044003),
    ("XRPUSDT", 857.4409340640001, -19.41861248008115, 342.97637362560005),
    ("HYPEUSDT", 1140.50482, -173.56223590824925, 456.20192800000007),
    ("DOGEUSDT", 837.2497500000001, -79.99418445039805, 334.89990000000006),
    ("BNBUSDT", 1424.8103289360001, 241.8861919889082, 569.9241315744001),
    ("NEARUSDT", 453.669, -86.24450000167752, 181.4676),
    ("UNIUSDT", 488.76599999999996, -91.92474012237074, 195.50639999999999),
    ("SUIUSDT", 484.3335, 135.22877111208794, 193.73340000000002),
    ("ENAUSDT", 337.39113936, 74.00637707577368, 134.956455744),
    ("LSKUSDT", 216.16685295000002, -8.715134265389793, 86.46674118000001),
    ("1000PEPEUSDT", 364.3229664, 95.78941535493209, 145.72918656),
    ("TRUMPUSDT", 628.3515, 14.83846456921242, 251.3406),
    ("ADAUSDT", 816.5598, -56.20553699838479, 326.62392),
)
RECORDED: dict[str, Any] = {
    "bar": "2026-09-24T17:00:00+00:00",
    "bar_open_ms": 1790269200000,
    "as_of_ms": 1790269200000,
    "at": "2026-09-24T18:00:30+00:00",
    "equity": 13084.90044379,
    "gross_before": 13025.38607271,
    "skip": False,
    "dry_run": False,
    "skipped": [
        {
            "current_notional": held,
            "delta_notional": delta,
            "reason": "NO_TRADE_BAND",
            "symbol": symbol,
            "threshold": band,
        }
        for symbol, held, delta, band in BAND_HELD
    ],
    "orders": [
        {
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
    ],
}

# The newest row before it that carries `construction_full` - the 2026-09-23T16:00Z bar, the restart that
# day - with its `rebalance` block verbatim.  The knobs come from here, not from the config file.
RECORDED_REBALANCE: dict[str, Any] = {
    "band_entry_multiple": 2.0,
    "exempt_crossings": True,
    "exempt_reductions": False,
    "flat_inside_band": True,
    "max_order_notional": None,
    "max_participation": 0.02,
    "no_trade_band": 0.005,
    "no_trade_rel_band": 0.4,
}
RESTART: dict[str, Any] = {
    "bar": "2026-09-23T16:00:00+00:00",
    "bar_open_ms": 1790179200000,
    "as_of_ms": 1790179200000,
    "equity": 12792.09564952,
    "gross_before": 10974.64239565,
    "skip": False,
    "dry_run": False,
    "construction_full": {"rebalance": RECORDED_REBALANCE},
}

# The same copy, line 221: the 2026-09-10T23:00Z bar, in the shape every row had before 2026-09-14T19:00Z -
# a band-held entry carries its delta and threshold but no `current_notional`.  Three of its eighteen
# entries, verbatim.
OLDER: dict[str, Any] = {
    "bar": "2026-09-10T23:00:00+00:00",
    "bar_open_ms": 1789081200000,
    "as_of_ms": 1789081200000,
    "equity": 10683.76934132,
    "gross_before": 6253.8046597,
    "skip": False,
    "dry_run": False,
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
        {
            "delta_notional": -14.395702158595725,
            "reason": "NO_TRADE_BAND",
            "symbol": "SOLUSDT",
            "threshold": 201.98995556352,
        },
    ],
}

# The same record, line 10 (copy taken 2026-09-25T06:02Z): the SECOND pass over the 2026-09-03T12:00Z bar, a
# restart at 13:37Z.  Its 1000PEPEUSDT order found the first pass's SELL of 32,080 already at the venue, so
# `execute_order` wrote this plan's BUY, quantity and price beside that SELL's `executed_qty`.  Nothing traded
# for 1000PEPEUSDT in this pass.  Every field of the row's five orders, verbatim.
RESTARTED: dict[str, Any] = {
    "as_of_ms": 1788436800000,
    "at": "2026-09-03T13:37:37+00:00",
    "bar": "2026-09-03T12:00:00+00:00",
    "bar_open_ms": 1788436800000,
    "dry_run": False,
    "equity": 10767.60530602,
    "gross_before": 0.0,
    "skip": False,
    "skipped": [],
    "orders": [
        {
            "avg_price": 0.08333,
            "client_order_id": "bd-1788436800000-DOGEUSDT",
            "current_notional": 32.66721416,
            "error": "",
            "executed_qty": "1588",
            "note": "",
            "order_id": "2334556066",
            "price": 0.08333473,
            "quantity": "1588",
            "reduce_only": False,
            "side": "BUY",
            "status": "FILLED",
            "symbol": "DOGEUSDT",
            "target_notional": 165.01894276311947,
            "target_weight": 0.015325500710065956,
            "venue_status": "FILLED",
        },
        {
            "avg_price": 0.0035042,
            "client_order_id": "bd-1788436800000-1000PEPEUSDT",
            "current_notional": 40.073762949999995,
            "error": "already submitted for this bar",
            "executed_qty": "32080",
            "note": "",
            "order_id": "869468534",
            "price": 0.00349105,
            "quantity": "33010",
            "reduce_only": False,
            "side": "BUY",
            "status": "FILLED",
            "symbol": "1000PEPEUSDT",
            "target_notional": 155.3159221798189,
            "target_weight": 0.01442436992865853,
            "venue_status": "FILLED",
        },
        {
            "avg_price": 0.767,
            "client_order_id": "bd-1788436800000-SUIUSDT",
            "current_notional": 6.422936772,
            "error": "",
            "executed_qty": "172.9",
            "note": "",
            "order_id": "1064855123",
            "price": 0.76463533,
            "quantity": "172.9",
            "reduce_only": False,
            "side": "BUY",
            "status": "FILLED",
            "symbol": "SUIUSDT",
            "target_notional": 138.64315726063597,
            "target_weight": 0.012875950902762267,
            "venue_status": "FILLED",
        },
        {
            "avg_price": 0.2852,
            "client_order_id": "bd-1788436800000-CYSUSDT",
            "current_notional": 0.0,
            "error": "",
            "executed_qty": "292",
            "note": "",
            "order_id": "290142655",
            "price": 0.2853,
            "quantity": "292",
            "reduce_only": False,
            "side": "SELL",
            "status": "FILLED",
            "symbol": "CYSUSDT",
            "target_notional": -83.31554734338465,
            "target_weight": -0.00773761156501569,
            "venue_status": "FILLED",
        },
        {
            "avg_price": 0.01292,
            "client_order_id": "bd-1788436800000-AKEUSDT",
            "current_notional": 71.44371975,
            "error": "",
            "executed_qty": "4180",
            "note": "",
            "order_id": "312133471",
            "price": 0.01293099,
            "quantity": "4180",
            "reduce_only": True,
            "side": "SELL",
            "status": "FILLED",
            "symbol": "AKEUSDT",
            "target_notional": 17.38604549009987,
            "target_weight": 0.0016146622202412645,
            "venue_status": "FILLED",
        },
    ],
}

# The `rebalance` block the loop ran from 2026-09-14T19:00Z until 09-17T16:00Z, verbatim from the row that
# restart wrote (line 325 of the same copy): the band applied to closes, and nothing snapped flat.
BAND_HOLDS_CLOSES: dict[str, Any] = {
    "exempt_crossings": False,
    "exempt_reductions": False,
    "flat_inside_band": False,
    "max_order_notional": None,
    "max_participation": 0.02,
    "no_trade_band": 0.005,
    "no_trade_rel_band": 0.4,
}

DECISION = 1_790_269_200_000  # the recorded row's bar, reused for the synthetic books below


def _store(tmp_path: Path, rows: list[dict[str, Any]]) -> StateStore:
    store = StateStore(tmp_path / "live")
    for row in rows:
        store.append_cycle(row)
    return store


def _cycle(bar_ms: int, held: dict[str, float], **extra: Any) -> dict[str, Any]:
    """A traded cycle holding `held` inside the band, with the recorded row's field names."""
    return {
        "bar": pd.Timestamp(bar_ms, unit="ms", tz="UTC").isoformat(),
        "bar_open_ms": bar_ms,
        "as_of_ms": bar_ms,
        "equity": 10_000.0,
        "gross_before": sum(abs(value) for value in held.values()),
        "skip": False,
        "dry_run": False,
        "skipped": [
            {"current_notional": value, "delta_notional": 0.0, "reason": "NO_TRADE_BAND", "symbol": symbol}
            for symbol, value in held.items()
        ],
        "orders": [],
        **extra,
    }


def _klines(
    root: Path, symbol: str, *, last_ms: int, bars: int, quote: float, price: float = 100.0, seed: int | None = 7
) -> pd.DataFrame:
    """Hourly bars in the archive's own format, written through `KlineStore` - the store the reading loads.

    `seed=None` gives a flat tape: every bar trades exactly `quote`, so the hourly mean is known by hand.
    """
    rng = np.random.default_rng(seed)
    moves = np.zeros(bars) if seed is None else rng.normal(0.0, 0.01, bars)
    opens = price * np.exp(np.cumsum(moves))
    closes = opens * np.exp(np.zeros(bars) if seed is None else rng.normal(0.0, 0.01, bars))
    volumes = np.full(bars, quote) if seed is None else quote * (0.5 + rng.random(bars))
    open_time = last_ms - HOUR * np.arange(bars)[::-1]
    frame = pd.DataFrame(
        {
            "open_time": open_time.astype("int64"),
            "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes),
            "close": closes,
            "volume": volumes / closes,
            "close_time": (open_time + HOUR - 1).astype("int64"),
            "quote_volume": volumes,
            "trades": np.full(bars, 100, dtype="int64"),
            "taker_buy_base": volumes / closes / 2.0,
            "taker_buy_quote": volumes / 2.0,
        }
    )
    KlineStore(root).append(symbol, "1h", frame)
    return frame


def test_the_book_is_what_the_recorded_cycle_left_after_its_own_fills(tmp_path: Path) -> None:
    """Sixteen names held, AKEUSDT gone: the order that closed it is applied at the price the planner used."""
    store = _store(tmp_path, [RESTART, RECORDED])
    result = liquidity_to_close(store, "2026-09-24", root=tmp_path / "data")
    held = {entry["symbol"]: entry["current_notional"] for entry in RECORDED["skipped"]}

    assert result["enforced"] is True and result["bar"] == "2026-09-24T17:00:00+00:00"
    assert result["positions"] == 16 and "AKEUSDT" not in result["unpriced"]
    assert math.isclose(result["gross_u"], sum(held.values()), rel_tol=1e-12)
    # The row accounts for its whole book: its per-symbol notionals add up to its own `gross_before`.
    assert math.isclose(result["accounted_before_u"], RECORDED["gross_before"], rel_tol=1e-9)
    assert result["book_complete"] is True
    assert result["max_participation"] == 0.02 and result["exempt_reductions"] is False
    # No archive under this root: every position says why it has no reading, and nothing reads as free.
    assert result["rows"] == [] and set(result["unpriced"]) == set(held)
    assert result["impact_u"] is None and result["impact_bps"] is None and result["hardest"] == []


def test_the_hourly_volume_is_the_loops_and_the_impact_is_the_backtests(tmp_path: Path) -> None:
    """Each ruler against its owner's code, on one tape: `LiveEngine._liquidity` and `impact_costs`."""
    root = tmp_path / "data"
    # 800 bars ending one bar AFTER the decision, so the backtest has an execution bar to charge on and
    # the reading has to leave it out.
    frame = _klines(root, "ETHUSDT", last_ms=DECISION + HOUR, bars=800, quote=2.0e6)
    notional = -250_000.0  # a short: closing it is a buy, and the size is what the rulers see
    store = _store(
        tmp_path, [_cycle(DECISION, {"ETHUSDT": notional}, construction_full={"rebalance": RECORDED_REBALANCE})]
    )
    [row] = liquidity_to_close(store, "2026-09-24", root=root)["rows"]

    decided = frame[frame["open_time"] <= DECISION]
    engine = SimpleNamespace(config=SimpleNamespace(liquidity_window=LIQUIDITY_WINDOW_BARS))
    live = LiveEngine._liquidity(engine, {"ETHUSDT": decided})["ETHUSDT"]
    assert math.isclose(row["hourly_quote_volume_u"], live, rel_tol=1e-12)
    assert math.isclose(row["participation"], abs(notional) / live, rel_tol=1e-12)

    panel = Panel.from_frames({"ETHUSDT": frame}, interval="1h")
    execution = pd.Timestamp(DECISION + HOUR, unit="ms", tz="UTC")
    turnover = pd.DataFrame({"ETHUSDT": [1.0]}, index=pd.DatetimeIndex([execution]))
    rets = asset_returns(panel, "open_to_close")
    shipped = impact_model(load_yaml(ROOT / "config" / "costs.yaml"), capital=abs(notional))
    charged = impact_costs(turnover, rets, panel, ["ETHUSDT"], shipped)
    assert math.isclose(row["impact_bps"], 1e4 * float(charged.loc[execution, "ETHUSDT"]), rel_tol=1e-9)
    assert math.isclose(row["impact_u"], abs(notional) * float(charged.loc[execution, "ETHUSDT"]), rel_tol=1e-9)
    assert row["volume_through_ms"] == DECISION and row["impact_bps"] > 0.0


def test_the_cap_stretches_a_reduction_over_bars_and_a_full_close_goes_out_whole(tmp_path: Path) -> None:
    """The report's two sentences, checked against `plan_rebalance` on the reading's own numbers.

    1,500 USDT of BTCUSDT against a flat 30,000 USDT hourly tape: participation 5%, 2.5 caps, so 3 bars for a
    reduction of the whole position.  The planner sends the full close as one order anyway.
    """
    root = tmp_path / "data"
    _klines(root, "BTCUSDT", last_ms=DECISION, bars=800, quote=30_000.0, price=60_000.0, seed=None)
    store = _store(
        tmp_path, [_cycle(DECISION, {"BTCUSDT": 1_500.0}, construction_full={"rebalance": RECORDED_REBALANCE})]
    )
    result = liquidity_to_close(store, "2026-09-24", root=root)
    [row] = result["rows"]
    assert math.isclose(row["participation"], 0.05, rel_tol=1e-12)
    assert row["bars_under_cap"] == 3 == result["slowest_bars_under_cap"]

    def plan(target: float) -> list[Any]:
        orders, _skipped = plan_rebalance(
            {"BTCUSDT": target},
            managed_symbols=["BTCUSDT"],
            equity=10_000.0,
            positions={"BTCUSDT": Position("BTCUSDT", 0.025, 60_000.0, 60_000.0)},
            prices={"BTCUSDT": 60_000.0},
            rules=DEFAULT_RULES,
            bar_open_ms=DECISION,
            params=RebalanceParams(max_participation=result["max_participation"]),
            liquidity={"BTCUSDT": row["hourly_quote_volume_u"]},
        )
        return orders

    [close] = plan(0.0)
    assert close.quantity == Decimal("0.025") and close.note == "", "a full close is one order for all of it"
    [cut] = plan(0.0001)
    assert cut.reduce_only and cut.note == "PARTICIPATION_CAPPED"
    assert cut.notional <= 0.02 * row["hourly_quote_volume_u"] + 1e-9, "a pure reduction is held to the cap"
    lines = _liquidity_to_close_lines(result)
    assert "只对纯减仓成立" in lines["纯减仓限速"] and "豁免完全平仓" in lines["完全平仓"]


def test_a_skip_is_walked_past_and_a_later_day_is_never_read(tmp_path: Path) -> None:
    """A guard skip places no order, so the book is the one before it; a past report never sees tomorrow."""
    day = DECISION - 17 * HOUR  # 2026-09-24T00:00Z
    rows = [
        _cycle(day + HOUR, {"BTCUSDT": 1_500.0}),
        {**_cycle(day + 2 * HOUR, {}), "skip": True, "gross_before": 1_510.0},
        _cycle(day + 25 * HOUR, {"BTCUSDT": 3_000.0}),
    ]
    store = _store(tmp_path, rows)
    today = liquidity_to_close(store, "2026-09-24", root=tmp_path / "data")
    assert today["bar"] == rows[0]["bar"] and math.isclose(today["gross_u"], 1_500.0)
    assert liquidity_to_close(store, "2026-09-25", root=tmp_path / "data")["bar"] == rows[2]["bar"]
    before = liquidity_to_close(store, "2026-09-23", root=tmp_path / "data")
    assert before["enforced"] is False and "2026-09-23" in before["why"]
    assert _liquidity_to_close_lines(before)["status"] == "n/a"


def test_a_row_that_names_positions_without_their_notional_is_not_read_as_flat(tmp_path: Path) -> None:
    """Zero positions counted is "not recorded" on an older row, and the page has to say which - by name."""
    result = liquidity_to_close(_store(tmp_path, [OLDER]), "2026-09-10", root=tmp_path / "data")
    assert result["positions"] == 0 and result["accounted_before_u"] == 0.0 and result["book_complete"] is False
    assert result["unrecorded"] == dict.fromkeys(("BTCUSDT", "ETHUSDT", "SOLUSDT"), "NO_TRADE_BAND")
    lines = _liquidity_to_close_lines(result)
    assert lines["按币记录不全"].startswith("按币合计与 gross_before 差 6,253.80 U，超过 0.2%。")
    assert lines["没记名义额的条目"] == "NO_TRADE_BAND：BTCUSDT、ETHUSDT、SOLUSDT。条目本身分不出持仓还是空仓。"
    assert lines["最难平的三个（按完全平仓的参与率）"] == "读不出：这一行没有按币记下名义额" == lines["成交额截至"]


def test_a_held_name_skipped_without_its_notional_is_named_and_the_book_is_not_complete(tmp_path: Path) -> None:
    """NOT_TRADABLE records no notional, and a name on its way off the venue is the hardest one to close.

    The recorded row with AKEUSDT's closing order swapped for that skip, under `plan_rebalance`'s own keys for
    it: 115.50 U, 0.89% of `gross_before`, which the old 1% tolerance called a complete book.
    """
    swapped = {
        **RECORDED,
        "orders": [],
        "skipped": [*RECORDED["skipped"], {"symbol": "AKEUSDT", "reason": "NOT_TRADABLE"}],
    }
    result = liquidity_to_close(_store(tmp_path, [RESTART, swapped]), "2026-09-24", root=tmp_path / "data")
    assert result["book_complete"] is False and result["positions"] == 16
    assert result["unrecorded"] == {"AKEUSDT": "NOT_TRADABLE"}
    lines = _liquidity_to_close_lines(result)
    assert lines["按币记录不全"].startswith("按币合计与 gross_before 差 115.50 U，超过 0.2%。")
    assert lines["没记名义额的条目"] == "NOT_TRADABLE：AKEUSDT。条目本身分不出持仓还是空仓。"
    # The widest gap the record has shown - 0.055%, two marks a moment apart - is still a whole book.
    marks = {**RECORDED, "gross_before": RECORDED["gross_before"] * 1.00055}
    assert liquidity_to_close(_store(tmp_path / "marks", [marks]), "2026-09-24", root=tmp_path)["book_complete"] is True


def test_an_order_already_submitted_for_the_bar_is_not_a_second_fill(tmp_path: Path) -> None:
    """Line 10 of the record: 1000PEPEUSDT held +40.07 U after this pass, and read +152.07 U before the fix."""
    root = tmp_path / "data"
    _klines(root, "1000PEPEUSDT", last_ms=RESTARTED["bar_open_ms"], bars=200, quote=5.0e6, price=0.0035)
    result = liquidity_to_close(_store(tmp_path, [RESTARTED]), "2026-09-03", root=root)
    [pepe] = result["rows"]
    assert pepe["symbol"] == "1000PEPEUSDT" and pepe["notional_u"] == 40.073762949999995
    # Every other order's fill is applied as before, at the price the planner used.
    after = {
        order["symbol"]: order["current_notional"]
        + (1.0 if order["side"] == "BUY" else -1.0) * float(order["executed_qty"]) * order["price"]
        for order in RESTARTED["orders"]
        if order["error"] != ALREADY_SUBMITTED
    }
    assert math.isclose(result["gross_u"], 40.073762949999995 + sum(abs(value) for value in after.values()))
    assert set(result["unpriced"]) == set(after)


async def test_the_marker_is_the_string_execute_order_writes() -> None:
    """The reading matches the error text, so the text is pinned to the code that writes it."""
    orders, _ = plan_rebalance(
        {"BTCUSDT": 0.05},
        managed_symbols=["BTCUSDT"],
        equity=100_000.0,
        positions={},
        prices={"BTCUSDT": 60_000.0},
        rules=DEFAULT_RULES,
        bar_open_ms=DECISION,
        params=RebalanceParams(no_trade_band=0.0),
    )
    venue, clock = FakeVenue(), FakeClock(0)
    first = (await execute_order(venue, orders[0], clock)).to_dict()
    again = (await execute_order(venue, orders[0], clock)).to_dict()
    assert first["error"] == "" and again["error"] == ALREADY_SUBMITTED
    assert again["executed_qty"] == first["executed_qty"], "the old order's fill, beside the new plan's fields"


def test_what_cannot_be_read_says_why_instead_of_reading_zero(tmp_path: Path) -> None:
    """Too few bars for sigma, no archive at all, an archive that stops short, and no knobs on record."""
    root = tmp_path / "data"
    _klines(root, "ETHUSDT", last_ms=DECISION - 2 * HOUR, bars=100, quote=1.0e6)
    store = _store(tmp_path, [_cycle(DECISION, {"ETHUSDT": 5_000.0, "SOLUSDT": -800.0})])
    result = liquidity_to_close(store, "2026-09-24", root=root)
    [row] = result["rows"]
    assert row["participation"] is not None and row["sigma_daily"] is None and row["impact_bps"] is None
    assert result["unpriced"] == {"SOLUSDT": "no 1h archive"}
    assert result["volume_lag_bars"] == 2 and result["max_participation"] is None and row["bars_under_cap"] is None
    lines = _liquidity_to_close_lines(result)
    assert lines["SOLUSDT"] == "读不出：no 1h archive" and "冲击读不出" in lines["ETHUSDT"]
    assert "早 2 根" in lines["成交额截至"] and lines["纯减仓限速"].startswith("读不出")


def test_nothing_it_raises_reaches_the_rest_of_the_report(tmp_path: Path) -> None:
    """It gates nothing: a broken parquet costs one symbol its reading, and a broken row costs the block."""
    root = tmp_path / "data"
    _klines(root, "BTCUSDT", last_ms=DECISION, bars=800, quote=30_000.0, price=60_000.0, seed=None)
    broken = KlineStore(root).path("ETHUSDT", "1h")
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"")  # a zero-byte parquet raises ArrowInvalid, not FileNotFoundError
    store = _store(tmp_path, [_cycle(DECISION, {"BTCUSDT": 1_500.0, "ETHUSDT": 900.0})])
    result = liquidity_to_close(store, "2026-09-24", root=root)
    assert [row["symbol"] for row in result["rows"]] == ["BTCUSDT"]
    assert result["unpriced"]["ETHUSDT"].startswith("archive unreadable: ")

    garbled = _store(tmp_path / "garbled", [{**_cycle(DECISION, {}), "skipped": ["not an entry"]}])
    block = liquidity_to_close(garbled, "2026-09-24", root=root)
    assert block["enforced"] is False and block["why"].startswith("AttributeError")
    assert _liquidity_to_close_lines(block) == {"status": "n/a", "why": block["why"]}


def test_exempt_reductions_on_record_turns_the_bars_column_into_no_path(tmp_path: Path) -> None:
    """The knob is read off the record: flipped there, the report stops calling the column a reduction's."""
    root = tmp_path / "data"
    _klines(root, "BTCUSDT", last_ms=DECISION, bars=800, quote=30_000.0, price=60_000.0, seed=None)
    flipped = {**RECORDED_REBALANCE, "exempt_reductions": True}
    store = _store(tmp_path, [_cycle(DECISION, {"BTCUSDT": 1_500.0}, construction_full={"rebalance": flipped})])
    lines = _liquidity_to_close_lines(liquidity_to_close(store, "2026-09-24", root=root))
    assert lines["纯减仓限速"].startswith("exempt_reductions 开着")


def test_the_full_close_line_is_written_from_the_knobs_on_record(tmp_path: Path) -> None:
    """`exempt_crossings` decides whether the band can hold a close back; each sentence is pinned to the planner.

    Three records: the construction running since 2026-09-17T16:00Z, the one before it (band on closes, nothing
    snapped flat), and a row from before either knob was recorded.  The planner is then asked to close 400 U of
    BTCUSDT against 100,000 U of equity: 0.4%, inside the 0.5% band.
    """

    def line(name: str, rebalance: dict[str, Any] | None) -> str:
        extra = {} if rebalance is None else {"construction_full": {"rebalance": rebalance}}
        store = _store(tmp_path / name, [_cycle(DECISION, {"BTCUSDT": 400.0}, **extra)])
        return str(_liquidity_to_close_lines(liquidity_to_close(store, "2026-09-24", root=tmp_path))["完全平仓"])

    running, before = line("running", RECORDED_REBALANCE), line("before", BAND_HOLDS_CLOSES)
    assert running.startswith("一笔市价单，一根 bar 内发完。") and "exempt_crossings 开着，绝对带也不拦" in running
    assert "flat_inside_band 开着" in running
    assert before.startswith("参与率上限豁免完全平仓，绝对带不豁免：exempt_crossings 关着。")
    assert "名义额不到权益 0.5% 的仓平不掉（BAND_BLOCKS_EXIT）" in before and "flat_inside_band 关着" in before
    assert line("unrecorded", None) == "读不出：没有周期记下 exempt_crossings。"

    def plan(exempt_crossings: bool) -> tuple[list[Any], list[dict[str, Any]]]:
        return plan_rebalance(
            {"BTCUSDT": 0.0},
            managed_symbols=["BTCUSDT"],
            equity=100_000.0,
            positions={"BTCUSDT": Position("BTCUSDT", 0.004, 100_000.0, 100_000.0)},
            prices={"BTCUSDT": 100_000.0},
            rules=DEFAULT_RULES,
            bar_open_ms=DECISION,
            params=RebalanceParams(no_trade_band=0.005, max_participation=0.02, exempt_crossings=exempt_crossings),
        )

    held, [blocked] = plan(False)
    assert held == [] and blocked["reason"] == "BAND_BLOCKS_EXIT", "off: the band holds the close back"
    [close], skipped = plan(True)
    assert skipped == [] and close.reduce_only and close.quantity == Decimal("0.004"), "on: one order, all of it"


def test_the_impact_model_is_the_cost_files_through_the_entry_research_uses(tmp_path: Path) -> None:
    """`composition.impact_model` over `config/costs.yaml`, or over the `costs` handed in: not `ImpactModel()`."""
    profile = load_yaml(ROOT / "config" / "live.demo.yaml")
    assert int(profile["pool"]["liquidity_window"]) == LIQUIDITY_WINDOW_BARS
    root = tmp_path / "data"
    _klines(root, "ETHUSDT", last_ms=DECISION, bars=800, quote=2.0e6)
    store = _store(tmp_path, [_cycle(DECISION, {"ETHUSDT": 25_000.0})])
    shipped = impact_model(load_yaml(ROOT / "config" / "costs.yaml"))
    reading = liquidity_to_close(store, "2026-09-24", root=root)
    assert reading["impact_model"] == {
        "coefficient": shipped.coefficient,
        "adv_window_bars": shipped.adv_window,
        "vol_window_bars": shipped.vol_window,
    }
    doubled = {
        "impact": {
            "coefficient": 2.0 * shipped.coefficient,
            "adv_window_bars": shipped.adv_window,
            "vol_window_bars": shipped.vol_window,
        }
    }
    twice = liquidity_to_close(store, "2026-09-24", root=root, costs=doubled)
    assert twice["impact_model"]["coefficient"] == 2.0 * shipped.coefficient
    assert math.isclose(twice["impact_u"], 2.0 * reading["impact_u"], rel_tol=1e-12)


def test_the_daily_report_prints_it_under_margin_and_never_pages_on_it(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _klines(root, "BTCUSDT", last_ms=DECISION, bars=800, quote=30_000.0, price=60_000.0, seed=None)
    store = _store(
        tmp_path, [_cycle(DECISION, {"BTCUSDT": 1_500.0}, construction_full={"rebalance": RECORDED_REBALANCE})]
    )
    payload = daily_payload(store, "2026-09-24", data_root=root)
    assert payload["liquidity_to_close"]["enforced"] is True
    keys = list(payload)
    assert keys.index("liquidity_to_close") == keys.index("margin") + 1
    markdown = daily_markdown(payload)
    margin = markdown.index("## Margin and rejections (M-007)")
    here = markdown.index("## Liquidity to close (#3.9, reported only)")
    assert margin < here < markdown.index("## Exits and pool (M-005 / M-006)")
    assert "| BTCUSDT | +1,500.00 U；参与率 5.0000%" in markdown
    # One cycle, two snapshots: this section says it took the one after the fills, and points at the other.
    assert "| 与 #3.4 的快照不同 | 这里是本周期成交后的持仓" in markdown[here:]
    without = {key: value for key, value in payload.items() if key != "liquidity_to_close"}
    assert daily_alerts(payload) == daily_alerts(without), "reported only: it must not reach alerts or notices"
