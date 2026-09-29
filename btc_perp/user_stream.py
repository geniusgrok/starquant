"""USDⓈ-M user stream. Events are hints; the REST snapshot is the position.

The connection is ``/private/ws?listenKey=...&events=...`` on the official
host. Binance's 2026-03-06 websocket notice gives that query form for private
streams, and the path form ``/private/ws/<listenKey>`` was later withdrawn on
the production host. This module does not try the path form, and it does not
fall back to another environment. A failed socket leaves the caller on REST.
The live socket itself has not been verified from this machine.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from typing import Protocol

from btc_perp.gates import DEMO, PROD
from btc_perp.stream import StreamHint, parse_stream_event
from btc_perp.ws_codec import FrameReader, connect_websocket, encode_frame

_EVENTS = (
    "ORDER_TRADE_UPDATE/ALGO_UPDATE/ALGO_ORDER_UPDATE/ACCOUNT_UPDATE/listenKeyExpired/CONDITIONAL_ORDER_TRIGGER_REJECT"
)
_KEEPALIVE_MS = 30 * 60 * 1000
_RECONNECT_MS = 30_000


class ListenKeys(Protocol):
    def create_listen_key(self) -> str:
        """POST /fapi/v1/listenKey."""

    def keepalive_listen_key(self) -> None:
        """PUT /fapi/v1/listenKey."""

    def close_listen_key(self) -> None:
        """DELETE /fapi/v1/listenKey."""


def user_stream_url(environment: str, listen_key: str) -> str:
    if environment == DEMO:
        base = "wss://demo-fstream.binance.com"
    elif environment == PROD:
        base = "wss://fstream.binance.com"
    else:
        raise ValueError("environment must be demo or prod")
    if not listen_key or any(char in listen_key for char in "/?#& "):
        raise ValueError("listenKey 无效")
    quoted = urllib.parse.quote(listen_key, safe="")
    return f"{base}/private/ws?listenKey={quoted}&events={_EVENTS}"


class UserStream:
    """One listenKey socket. A failed start leaves the caller on REST."""

    def __init__(self, client: ListenKeys, environment: str) -> None:
        self._client = client
        self._environment = environment
        self._lock = threading.Lock()
        self._hints: list[StreamHint] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self.disconnected = False
        self._opened_ms = 0
        self._next_reconnect_ms = 0
        self._listen_key = ""

    def start(self, opener: Callable[[str], socket.socket] | None = None) -> None:
        self._stop.clear()
        listen_key = ""
        try:
            listen_key = self._client.create_listen_key()
            url = user_stream_url(self._environment, listen_key)
            sock = connect_websocket(url, 10.0) if opener is None else opener(url)
            sock.settimeout(1.0)
        except (OSError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError):
            self.disconnected = True
            if listen_key:
                with contextlib.suppress(OSError, TimeoutError, RuntimeError, ValueError):
                    self._client.close_listen_key()
            return
        self._listen_key = listen_key
        self._sock = sock
        self.disconnected = False
        self._opened_ms = int(time.time() * 1000)
        self._thread = threading.Thread(target=self._read, name="starquant-user-stream", daemon=True)
        self._thread.start()

    def poll(self) -> tuple[tuple[StreamHint, ...], bool]:
        with self._lock:
            found = tuple(self._hints)
            self._hints.clear()
            expired = self.disconnected or any(item.kind == "expired" for item in found)
            if expired:
                self.disconnected = True
            return found, expired

    def keepalive(self, now_ms: int) -> None:
        if self.disconnected or self._opened_ms <= 0:
            return
        if now_ms - self._opened_ms < _KEEPALIVE_MS:
            return
        try:
            self._client.keepalive_listen_key()
        except (OSError, TimeoutError, RuntimeError, ValueError):
            self.disconnected = True
            return
        self._opened_ms = now_ms

    def reconnect_if_due(self, now_ms: int, opener: Callable[[str], socket.socket] | None = None) -> None:
        if not self.disconnected or now_ms < self._next_reconnect_ms:
            return
        self._next_reconnect_ms = now_ms + _RECONNECT_MS
        self._stop.set()
        self._close_socket()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self.start(opener)

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        if self._listen_key:
            with contextlib.suppress(OSError, TimeoutError, RuntimeError, ValueError):
                self._client.close_listen_key()
            self._listen_key = ""

    def _close_socket(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    def _read(self) -> None:
        sock = self._sock
        if sock is None:
            self.disconnected = True
            return
        reader = FrameReader(sock)
        try:
            while not self._stop.is_set():
                frame = reader.read_frame()
                if frame is None:
                    continue
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    try:
                        sock.sendall(encode_frame(0xA, payload, masked=True))
                    except OSError:
                        break
                    continue
                if opcode != 0x1:
                    continue
                self._on_text(payload)
        except (OSError, TimeoutError, EOFError, ValueError, json.JSONDecodeError, UnicodeError):
            pass
        self.disconnected = True

    def _on_text(self, payload: bytes) -> None:
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            return
        hint = parse_stream_event(parsed)
        if hint.kind == "ignore":
            return
        with self._lock:
            self._hints.append(hint)
            if hint.kind == "expired":
                self.disconnected = True
