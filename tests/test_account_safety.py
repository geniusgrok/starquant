"""Account parsing, read-only writes, and capital limits with fake transport."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from test_forward import FakeVenue, _bar, _run, _snap
from btc_perp.binance_client import UnknownExecution, UsdMClient, WriteRefused
from btc_perp.gates import assert_host_matches, notional_cap, rest_host, risk_equity
from btc_perp.model import Intent, Limits
from btc_perp.runner import _channel_table, _fit_qty, _levels_for_bar
from btc_perp.bars import MinuteBar
from btc_perp.store import Store
from btc_perp.permissions import prod_permission_block, prod_uid_block
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
        status, payload = answer
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
    return UsdMClient("demo", "key", "secret", transport, **kwargs), transport


@pytest.mark.parametrize("over", [
    {"/fapi/v2/account": (401, {"code": -2015, "msg": "Invalid API-key"})},
    {"/fapi/v2/account": (200, {**ACCOUNT, "positions": [None]})},
    {"/fapi/v2/account": (200, {**ACCOUNT, "assets": [{"asset": "USDT", "walletBalance": "NaN", "availableBalance": "1"}]})},
])
def test_a_bad_answer_never_becomes_an_empty_account(over: dict[str, object]) -> None:
    client, _t = _client(_routes(**over))
    snap = client.snapshot()
    assert not snap.known


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


def test_caps_take_the_smaller_positive_value() -> None:
    limits = Limits(capital_usdt=200.0, max_notional_usdt=500.0, max_daily_loss_usdt=None, max_unprotected_seconds=None)
    assert notional_cap(300.0, limits) == 300.0
    assert notional_cap(None, limits) == 500.0
    assert notional_cap(None, Limits(None, None, None, None)) is None
    assert risk_equity(10_000.0, limits) == 200.0
    assert risk_equity(50.0, limits) == 50.0


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


class _Transport:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.urls: list[str] = []

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        self.urls.append(url)
        assert headers["X-MBX-APIKEY"] == "prod-key"
        assert "prod-secret" not in url
        return self.status, self.body


def test_production_key_with_withdraw_permission_is_refused() -> None:
    body = json.dumps(
        {
            "enableFutures": True,
            "enableWithdrawals": True,
            "enableInternalTransfer": False,
            "permitsUniversalTransfer": False,
        }
    ).encode()
    transport = _Transport(200, body)
    reason = prod_permission_block("prod", "prod-key", "prod-secret", transport)
    assert "提币或划转" in reason
    assert transport.urls[0].startswith("https://api.binance.com/sapi/v1/account/apiRestrictions?")
    assert "fapi.binance.com" not in transport.urls[0]


def test_an_unreadable_permission_response_refuses_production() -> None:
    reason = prod_permission_block("prod", "prod-key", "prod-secret", _Transport(500, b""))
    assert "无法确认" in reason


def test_two_directories_cannot_drive_one_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    one = Store(tmp_path / "a", "demo")
    two = Store(tmp_path / "b", "demo")
    try:
        one.bind_credential("k", "1001")
        with pytest.raises(RuntimeError, match="同一账户"):
            two.bind_credential("k2", "1001")
    finally:
        one.close()
        two.close()


def test_the_production_uid_check() -> None:
    class Spot:
        def __init__(self, status: int, payload: dict[str, object]) -> None:
            self.answer = (status, json.dumps(payload).encode())

        def request(self, *_a: object) -> tuple[int, bytes]:
            return self.answer

    assert prod_uid_block("k", "s", Spot(200, {"uid": 1001}), "1001", now_ms=1) == ""
    assert "不一致" in prod_uid_block("k", "s", Spot(200, {"uid": 9}), "1001", now_ms=1)
    assert "必须设置" in prod_uid_block("k", "s", Spot(200, {"uid": 1001}), "", now_ms=1)
    assert "读不到" in prod_uid_block("k", "s", Spot(401, {"code": -2015}), "1001", now_ms=1)


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
    assert _levels_for_bar(first_minute, None, table)[:2] == (float("inf"), float("-inf"))
    two = _channel_table(rows, 2, 2)
    assert two[hour + 2 * 3_600_000][:2] == (101.0, 89.0)
    assert two[hour + 2 * 3_600_000][:4] == (101.0, 89.0, 101.0, 89.0)


def test_host_check_uses_real_url_parsing() -> None:
    for environment, other in (("demo", "prod"), ("prod", "demo")):
        assert_host_matches(environment, rest_host(environment))
        assert_host_matches(environment, "http://127.0.0.1:9000")
        with pytest.raises(RuntimeError):
            assert_host_matches(environment, rest_host(other))
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


def test_the_state_follows_the_uid_not_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    first = Store(tmp_path / "a", "demo")
    first.bind_credential("key-one", "1001")
    first.close()
    rotated = Store(tmp_path / "a", "demo")
    try:
        rotated.bind_credential("key-two", "1001")
        assert rotated.get_json("account")["id"] == "uid:1001"
        assert len(rotated.get_json("account")["keys"]) == 2
    finally:
        rotated.close()
    other = Store(tmp_path / "a", "demo")
    try:
        with pytest.raises(RuntimeError, match="另一个账户 UID"):
            other.bind_credential("key-two", "2002")
        with pytest.raises(RuntimeError, match="没有见过"):
            other.bind_credential("key-three", "")
    finally:
        other.close()
