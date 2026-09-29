"""User stream and production key permissions. The socket here is local."""

from __future__ import annotations

import json
import socket
import threading
import time

from btc_perp.binance_client import UsdMClient
from btc_perp.permissions import prod_permission_block
from btc_perp.stream import parse_stream_event
from btc_perp.user_stream import UserStream, user_stream_url
from btc_perp.ws_codec import accept_value, connect_websocket, encode_frame


class _Keys:
    def __init__(self, listen_key: str = "listen-key-test") -> None:
        self.listen_key = listen_key
        self.closed = 0
        self.kept = 0

    def create_listen_key(self) -> str:
        return self.listen_key

    def keepalive_listen_key(self) -> None:
        self.kept += 1

    def close_listen_key(self) -> None:
        self.closed += 1


def _serve(payload: bytes | None) -> int:
    ready = threading.Event()
    holder: dict[str, int] = {}

    def run() -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        holder["port"] = server.getsockname()[1]
        ready.set()
        conn, _addr = server.accept()
        try:
            data = b""
            conn.settimeout(2)
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            header = data.split(b"\r\n\r\n", 1)[0].decode()
            key = ""
            for line in header.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = accept_value(key)
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            if payload is not None:
                conn.sendall(encode_frame(1, payload, masked=False))
            time.sleep(0.1)
        finally:
            conn.close()
            server.close()

    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(2)
    return holder["port"]


def test_private_stream_url_stays_on_the_official_demo_host() -> None:
    url = user_stream_url("demo", "listen-key-test")
    assert url.startswith("wss://demo-fstream.binance.com/private/ws?listenKey=listen-key-test&events=")
    assert "/private/ws/listen-key-test" not in url
    assert "ALGO_UPDATE" in url
    assert "ORDER_TRADE_UPDATE" in url
    assert "binancefuture" not in url
    assert "/ws/listen-key-test" not in url
    prod = user_stream_url("prod", "listen-key-test")
    assert prod.startswith("wss://fstream.binance.com/private/ws?")
    assert "demo-fstream" not in prod


def test_disallowed_host_does_not_echo_the_listen_key() -> None:
    secret = "listen-key-should-stay-out"
    try:
        connect_websocket(f"wss://fstream.binancefuture.com/private/ws?listenKey={secret}", 1)
    except RuntimeError as exc:
        assert secret not in str(exc)
        assert "官方域名" in str(exc)
    else:
        raise AssertionError("testnet host was accepted")


def test_algo_update_fields_from_the_published_payload() -> None:
    payload = {
        "e": "ALGO_UPDATE",
        "o": {
            "caid": "st-finished",
            "o": "STOP_MARKET",
            "X": "FINISHED",
            "wt": "CONTRACT_PRICE",
            "q": "5",
        },
    }
    hint = parse_stream_event(payload)
    assert hint.kind == "algo"
    assert hint.client_id == "st-finished"
    assert hint.status == "FINISHED"
    alias = parse_stream_event({"e": "ALGO_ORDER_UPDATE", "ao": {"clientAlgoId": "tp1", "X": "NEW"}})
    assert alias.kind == "algo"
    assert alias.client_id == "tp1"
    assert parse_stream_event({"e": "ORDER_TRADE_UPDATE", "o": {"c": "en1", "X": "PARTIALLY_FILLED"}}).status == (
        "PARTIALLY_FILLED"
    )


def test_local_socket_delivers_a_finished_algo_hint() -> None:
    body = json.dumps({"e": "ALGO_UPDATE", "o": {"caid": "st1", "X": "FINISHED"}}).encode()
    port = _serve(body)
    seen: list[str] = []

    def opener(url: str) -> socket.socket:
        seen.append(url)
        return connect_websocket(f"ws://127.0.0.1:{port}/private/ws?listenKey=listen-key-test", 2)

    keys = _Keys()
    stream = UserStream(keys, "demo")
    stream.start(opener)
    found = ()
    for _ in range(50):
        found, _expired = stream.poll()
        if found:
            break
        time.sleep(0.02)
    stream.stop()
    assert seen and seen[0].startswith("wss://demo-fstream.binance.com/private/ws?listenKey=listen-key-test&")
    assert found[0].client_id == "st1"
    assert found[0].status == "FINISHED"
    assert keys.closed == 1


def test_a_dropped_socket_is_marked_disconnected() -> None:
    port = _serve(None)
    stream = UserStream(_Keys(), "demo")
    stream.start(lambda _url: connect_websocket(f"ws://127.0.0.1:{port}/private/ws?listenKey=listen-key-test", 2))
    expired = False
    for _ in range(50):
        _hints, expired = stream.poll()
        if expired:
            break
        time.sleep(0.02)
    stream.stop()
    assert expired


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


def test_listen_key_is_unsigned_and_stays_on_the_client_host() -> None:
    class Transport:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            assert method == "POST"
            assert url == "http://127.0.0.1/fapi/v1/listenKey"
            assert "signature" not in url
            assert headers["X-MBX-APIKEY"] == "demo-key"
            return 200, b'{"listenKey":"abc"}'

    client = UsdMClient("demo", "demo-key", "demo-secret", Transport(), base_url="http://127.0.0.1")
    assert client.create_listen_key() == "abc"


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


def test_production_key_without_transfer_permission_is_allowed() -> None:
    body = json.dumps(
        {
            "enableFutures": True,
            "enableWithdrawals": False,
            "enableInternalTransfer": False,
            "permitsUniversalTransfer": False,
        }
    ).encode()
    reason = prod_permission_block("prod", "prod-key", "prod-secret", _Transport(200, body))
    assert reason == ""


def test_demo_permission_check_does_not_call_the_spot_api() -> None:
    class Boom:
        def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
            raise AssertionError(url)

    assert prod_permission_block("demo", "demo-key", "demo-secret", Boom()) == ""


def test_an_unreadable_permission_response_refuses_production() -> None:
    reason = prod_permission_block("prod", "prod-key", "prod-secret", _Transport(500, b""))
    assert "无法确认" in reason
