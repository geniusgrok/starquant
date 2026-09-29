"""Regression tests for the 34-item account audit. Everything here is offline."""

from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path

import pytest
from test_forward import FakeVenue, _bar, _clock, _run, _snap

from btc_perp.bars import MinuteBar
from btc_perp.binance_client import (
    MAX_BODY_BYTES,
    UnknownExecution,
    UsdMClient,
    WriteRefused,
    _capped,
    _snapshot_from,
)
from btc_perp.gates import assert_host_matches, load_limits, notional_cap, risk_equity
from btc_perp.model import AlgoOrder, Intent, Limits
from btc_perp.runner import _channel_table, _fit_qty, _levels_for_bar
from btc_perp.store import Store

INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "contractType": "PERPETUAL",
            "quoteAsset": "USDT",
            "status": "TRADING",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "120"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.1", "minPrice": "1", "maxPrice": "1000000"},
                {"filterType": "MIN_NOTIONAL", "notional": "100"},
            ],
        }
    ]
}
ACCOUNT = {
    "canTrade": True,
    "multiAssetsMargin": False,
    "assets": [{"asset": "USDT", "walletBalance": "1000", "availableBalance": "1000"}],
    "positions": [],
}
POSITION = [
    {
        "symbol": "BTCUSDT",
        "positionSide": "BOTH",
        "positionAmt": "0",
        "entryPrice": "0",
        "markPrice": "100",
        "liquidationPrice": "0",
        "marginType": "isolated",
        "leverage": "20",
    }
]


class Routes:
    """A scripted exchange. A route maps a path to ``(status, payload)`` or a list of them."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []
        self.last_retry_after = 0.0

    def request(self, method: str, url: str, headers: object, timeout: float) -> tuple[int, bytes]:
        path = url.split("?")[0].split(".com")[1]
        self.calls.append((method, path))
        answer = self.routes.get(path, (200, {}))
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, Exception):
            raise answer
        status, payload = answer  # type: ignore[misc]
        return status, json.dumps(payload).encode()


def _routes(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "/fapi/v1/time": (200, {"serverTime": 1_700_000_000_000}),
        "/fapi/v1/exchangeInfo": (200, INFO),
        "/fapi/v1/positionSide/dual": (200, {"dualSidePosition": False}),
        "/fapi/v2/account": (200, ACCOUNT),
        "/fapi/v1/openOrders": (200, []),
        "/fapi/v1/openAlgoOrders": (200, []),
        "/fapi/v2/positionRisk": (200, POSITION),
        "/fapi/v1/ticker/price": (200, {"price": "100"}),
    }
    base.update(over)
    return base


def _client(routes: dict[str, object], **kwargs: object) -> tuple[UsdMClient, Routes]:
    transport = Routes(routes)
    return UsdMClient("demo", "key", "secret", transport, **kwargs), transport  # type: ignore[arg-type]


def test_a_clean_account_reads_as_known() -> None:
    client, _t = _client(_routes())
    snap = client.snapshot()
    assert snap.known, snap.reason
    assert snap.filters is not None and snap.filters.max_qty == 120.0


@pytest.mark.parametrize(
    "over",
    [
        {"/fapi/v2/account": (401, {"code": -2015, "msg": "Invalid API-key"})},
        {"/fapi/v2/account": (200, {"code": -1022, "msg": "bad signature"})},
        {"/fapi/v1/openOrders": (500, {"msg": "boom"})},
        {"/fapi/v1/openAlgoOrders": (403, {"code": -2015, "msg": "no"})},
        {"/fapi/v2/positionRisk": (200, POSITION + POSITION)},
        {"/fapi/v2/positionRisk": (200, [])},
        {"/fapi/v2/account": (200, {**ACCOUNT, "assets": []})},
        {
            "/fapi/v2/account": (
                200,
                {**ACCOUNT, "assets": [{"asset": "USDT", "walletBalance": "NaN", "availableBalance": "1"}]},
            )
        },
        {"/fapi/v1/exchangeInfo": (200, {"symbols": INFO["symbols"] * 2})},
    ],
)
def test_a_bad_answer_never_becomes_an_empty_account(over: dict[str, object]) -> None:
    client, _t = _client(_routes(**over))
    snap = client.snapshot()
    assert not snap.known


def test_btcusdt_row_is_found_wherever_it_sits() -> None:
    other = {**POSITION[0], "symbol": "ETHUSDT", "positionAmt": "0"}
    client, _t = _client(_routes(**{"/fapi/v2/positionRisk": (200, [other, POSITION[0]])}))
    assert client.snapshot().known


def test_a_position_on_another_contract_is_reported() -> None:
    account = {**ACCOUNT, "positions": [{"symbol": "ETHUSDT", "positionAmt": "1"}]}
    dual = {"dualSidePosition": False}
    snap = _snapshot_from(1, INFO, account, dual, {"raw": []}, {"raw": []}, {"raw": POSITION})  # type: ignore[arg-type]
    assert snap.known and snap.other_exposure == "ETHUSDT"


def test_a_read_only_client_refuses_every_write() -> None:
    client, transport = _client(_routes(), read_only=True)
    with pytest.raises(WriteRefused):
        client.place_market(client_id="en1", side="BUY", qty="0.001", reduce_only=False)
    with pytest.raises(WriteRefused):
        client.cancel_order("en1")
    assert all(method == "GET" for method, _path in transport.calls)


def test_rate_limit_cooldown_cannot_be_bypassed_by_a_reducing_write_or_a_public_read() -> None:
    client, transport = _client(_routes(**{"/fapi/v1/order": (429, {"msg": "slow down"})}))
    with pytest.raises(UnknownExecution):
        client.place_market(client_id="en1", side="BUY", qty="0.001", reduce_only=False)
    before = len(transport.calls)
    with pytest.raises(WriteRefused):
        client.place_market(client_id="en2", side="BUY", qty="0.001", reduce_only=False)
    with pytest.raises(WriteRefused):
        client.place_market(client_id="rd1", side="SELL", qty="0.001", reduce_only=True)
    with pytest.raises(WriteRefused):
        client.cancel_order("en1")
    with pytest.raises(WriteRefused):
        client.sync_time()
    assert len(transport.calls) == before


def test_retry_after_sets_the_cooldown_length() -> None:
    client, transport = _client(_routes(**{"/fapi/v1/order": (418, {"msg": "banned"})}))
    transport.last_retry_after = 300.0
    with pytest.raises(UnknownExecution):
        client.place_market(client_id="en1", side="BUY", qty="0.001", reduce_only=False)
    with pytest.raises(WriteRefused, match=r"还有 (29|30)\d 秒"):
        client.place_market(client_id="rd1", side="SELL", qty="0.001", reduce_only=True)


def test_an_oversized_body_is_refused() -> None:
    with pytest.raises(OSError):
        _capped(io.BytesIO(b"x" * (MAX_BODY_BYTES + 1)))
    assert _capped(io.BytesIO(b"{}")) == b"{}"


def test_host_check_uses_real_url_parsing() -> None:
    assert_host_matches("demo", "http://127.0.0.1:9000")
    assert_host_matches("demo", "http://localhost:9000")
    for bad in (
        "http://localhost.example.invalid",
        "http://127.0.0.1@evil.example",
        "http://user:pw@127.0.0.1:9",
        "https://fapi.binance.com.evil.example",
        "http://fapi.binance.com",
    ):
        with pytest.raises(RuntimeError):
            assert_host_matches("demo", bad)


def test_limits_reject_nonsense(tmp_path: Path) -> None:
    for text in ("capital_usdt: .nan", "capital_usdt: -5", "capital_usdt: true", "max_unprotected_seconds: -1"):
        file = tmp_path / "limits.yaml"
        file.write_text(text)
        with pytest.raises(ValueError):
            load_limits(file)


def test_caps_take_the_smaller_positive_value() -> None:
    limits = Limits(capital_usdt=200.0, max_notional_usdt=500.0, max_daily_loss_usdt=None, max_unprotected_seconds=None)
    assert notional_cap(300.0, limits) == 300.0
    assert notional_cap(None, limits) == 500.0
    assert notional_cap(None, Limits(None, None, None, None)) is None
    assert risk_equity(10_000.0, limits) == 200.0
    assert risk_equity(50.0, limits) == 50.0


def test_the_credential_is_bound_to_the_state_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARQUANT_LOCK_DIR", str(tmp_path / "locks"))
    first = Store(tmp_path / "a", "demo")
    first.bind_credential("key-one")
    first.close()
    again = Store(tmp_path / "a", "demo")
    with pytest.raises(RuntimeError, match="另一组凭据"):
        again.bind_credential("key-two")
    again.close()


def test_two_state_directories_cannot_drive_one_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARQUANT_LOCK_DIR", str(tmp_path / "locks"))
    first = Store(tmp_path / "a", "demo")
    second = Store(tmp_path / "b", "demo")
    try:
        first.bind_credential("same-key")
        with pytest.raises(RuntimeError, match="同一账户"):
            second.bind_credential("same-key")
    finally:
        first.close()
        second.close()
    third = Store(tmp_path / "c", "demo")
    try:
        third.bind_credential("same-key")
    finally:
        third.close()


def test_a_corrupt_book_is_not_replaced_by_a_fresh_one(tmp_path: Path) -> None:
    store = Store(tmp_path, "demo")
    store.put_json("book", ["nonsense"])
    try:
        with pytest.raises((RuntimeError, ValueError, TypeError, KeyError)):
            store.load_book()
    finally:
        store.close()


def test_levels_never_include_the_forming_hour() -> None:
    hour = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000
    rows = tuple((hour + i * 3_600_000, 100.0 + i, 90.0 - i) for i in range(30))
    table = _channel_table(rows, 5, 3)
    minute_in_hour_10 = MinuteBar(hour + 10 * 3_600_000 + 60_000, 1.0, 1.0, 1.0, 1.0, 1.0, True)
    hh, ll, _xh, _xl = _levels_for_bar(minute_in_hour_10, None, table)
    assert hh == 100.0 + 9
    assert ll == 90.0 - 9
    first_minute = MinuteBar(hour + 60_000, 1.0, 1.0, 1.0, 1.0, 1.0, True)
    assert _levels_for_bar(first_minute, None, table)[0] == float("inf")


def test_levels_match_the_research_kernel() -> None:
    import numpy as np

    from scripts.frontier import rolling_max

    hour = 1_700_000_000_000 - 1_700_000_000_000 % 3_600_000
    rng = np.random.default_rng(3)
    high = 100.0 + rng.random(60).cumsum()
    low = high - 5.0
    rows = tuple((hour + i * 3_600_000, float(high[i]), float(low[i])) for i in range(60))
    table = _channel_table(rows, 24, 12)
    expected = rolling_max(high, 24)
    for i in (30, 40, 59):
        stamp = hour + (i + 1) * 3_600_000
        assert table[stamp][0] == pytest.approx(expected[i])


def test_quantity_survives_a_missing_or_bad_max_qty() -> None:
    snap = _snap()
    assert float(_fit_qty(1.0, snap, 100.0, False, 0.0) or 0) == 1.0
    assert _fit_qty(float("nan"), snap, 100.0, False, 0.0) is None
    assert _fit_qty(float("inf"), snap, 100.0, False, 0.0) is None
    limited = dataclasses.replace(snap, filters=dataclasses.replace(snap.filters, max_qty=1.5))  # type: ignore[type-var]
    assert float(_fit_qty(2.0, limited, 100.0, False, 0.0) or 0) == 1.5


def test_the_margin_check_includes_fees() -> None:
    snap = _snap(available_usdt=5.01)
    assert _fit_qty(1.0, snap, 100.0, False, 0.0) is None
    snap = _snap(available_usdt=6.0)
    assert float(_fit_qty(1.0, snap, 100.0, False, 0.0) or 0) == 1.0


def test_check_mode_sends_nothing_even_with_a_planned_intent(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now))
    store = Store(tmp_path, "demo")
    store.insert_intent(Intent("en" + "0" * 20, "enter", "planned", "BUY", "2.000", False, False, "", "demo", now, ""))
    try:
        for mode in ("check", "takeover"):
            _run(store, venue, bar, now, mode=mode, dry_run=True)
        assert venue.market_ids == [] and venue.algo_ids == [] and venue.cancels == []
    finally:
        store.close()


def test_the_capital_limit_caps_the_position(tmp_path: Path) -> None:
    bar, now = _bar(100.0)
    venue = FakeVenue(_snap(server_time_ms=now, wallet_usdt=100_000.0, available_usdt=100_000.0))
    store = Store(tmp_path, "demo")
    try:
        _run(store, venue, bar, now, max_notional=1_000_000.0, limits=Limits(50.0, None, None, None))
        # 50 USDT of capital at 100 USDT/BTC and the strategy leverage stays far below the account size
        assert abs(venue.snap.position_qty) * 100.0 <= 50.0 * 20 * 1.05
    finally:
        store.close()


def test_a_crossed_stop_flattens_instead_of_waiting(tmp_path: Path) -> None:
    bar, now = _bar(90.0)
    stop = AlgoOrder("st" + "0" * 20, "STOP_MARKET", "SELL", 96.0, True, False, 0.0, "NEW", "CONTRACT_PRICE")
    venue = FakeVenue(
        _snap(server_time_ms=now, position_qty=2.0, entry_price=100.0, mark_price=90.0, last_price=90.0, algos=(stop,))
    )
    store = Store(tmp_path, "demo")
    store.insert_intent(Intent(stop.client_algo_id, "stop", "acked", "SELL", "", False, True, "96.0", "demo", now, ""))
    book = store.load_book()
    book.side = 1
    book.qty = 2.0
    book.entry = 100.0
    book.units = 1
    book.extreme = 100.0
    book.last_add = 100.0
    book.stop = 96.0
    store.save_book(book)
    try:
        _run(store, venue, bar, now)
        assert venue.snap.position_qty == 0
    finally:
        store.close()


def test_a_stale_bar_backlog_is_not_replayed(tmp_path: Path) -> None:
    old, _now = _bar(100.0, index=0)
    late = old.open_ms + 600_000
    venue = FakeVenue(_snap(server_time_ms=late))
    store = Store(tmp_path, "demo")
    try:
        _run(store, venue, old, late)
        assert venue.market_ids == []
    finally:
        store.close()


def test_an_unknown_snapshot_keeps_the_naked_timer(tmp_path: Path) -> None:
    _bar_unused, now = _bar(100.0)
    naked = _snap(server_time_ms=now, position_qty=2.0, entry_price=100.0)
    venue = FakeVenue(dataclasses.replace(naked, known=False, reason="down"))
    store = Store(tmp_path, "demo")
    try:
        _run(store, venue, _bar(100.0)[0], now, bars=(), channels=None)
        assert venue.market_ids == []
    finally:
        store.close()


def test_clock_helpers_are_stable() -> None:
    first, second = _clock(0), _clock(1)
    assert second[0] - first[0] == 60_000
