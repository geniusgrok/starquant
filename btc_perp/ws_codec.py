"""A small WebSocket client. No third-party package.

The forward loop uses this only for the USDⓈ-M user stream. Text frames are
hints. The account book stays on the REST snapshot.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import urllib.parse
import weakref

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC5B504"
_MAX_PAYLOAD = 1_000_000
_PENDING: weakref.WeakKeyDictionary[socket.socket, bytes] = weakref.WeakKeyDictionary()


def accept_value(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + _GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def encode_frame(opcode: int, payload: bytes, *, masked: bool) -> bytes:
    if len(payload) > _MAX_PAYLOAD:
        raise ValueError("websocket 帧过大")
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    mask_bit = 0x80 if masked else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(mask_bit | 127)
        header.extend(length.to_bytes(8, "big"))
    if not masked:
        return bytes(header) + payload
    mask = os.urandom(4)
    masked_payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + mask + masked_payload


def connect_websocket(url: str, timeout: float) -> socket.socket:
    """Open one WebSocket. Errors do not include the URL, which carries the listenKey."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if host not in {"demo-fstream.binance.com", "fstream.binance.com", "127.0.0.1", "localhost"}:
        raise RuntimeError("用户流只允许官方域名或本机测试")
    if parsed.scheme not in {"ws", "wss"}:
        raise RuntimeError("用户流地址无效")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    raw = socket.create_connection((host, port), timeout)
    sock: socket.socket = raw
    try:
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host if parsed.port is None else f'{host}:{port}'}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())
        sock.settimeout(timeout)
        header, pending = _read_headers(sock)
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise RuntimeError("用户流握手失败")
        expected = accept_value(key).encode()
        if expected not in header:
            raise RuntimeError("用户流握手失败")
        if pending:
            _PENDING[sock] = pending
        sock.settimeout(1.0)
        return sock
    except Exception:
        sock.close()
        raise


def _read_headers(sock: socket.socket) -> tuple[bytes, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("用户流握手失败")
        data.extend(chunk)
        if len(data) > 8192 + _MAX_PAYLOAD:
            raise RuntimeError("用户流握手失败")
    marker = data.index(b"\r\n\r\n") + 4
    return bytes(data[:marker]), bytes(data[marker:])


class FrameReader:
    """Read server frames. A timeout with no complete frame returns None."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray(_PENDING.pop(sock, b""))

    def read_frame(self) -> tuple[int, bytes] | None:
        while True:
            parsed = _parse_frame(self._buf)
            if parsed is not None:
                opcode, payload, used = parsed
                del self._buf[:used]
                return opcode, payload
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                return None
            if not chunk:
                raise EOFError
            self._buf.extend(chunk)


def _parse_frame(buf: bytearray) -> tuple[int, bytes, int] | None:
    if len(buf) < 2:
        return None
    opcode = buf[0] & 0x0F
    masked = (buf[1] & 0x80) != 0
    length = buf[1] & 0x7F
    offset = 2
    if length == 126:
        if len(buf) < 4:
            return None
        length = int.from_bytes(buf[2:4], "big")
        offset = 4
    elif length == 127:
        if len(buf) < 10:
            return None
        length = int.from_bytes(buf[2:10], "big")
        offset = 10
    if length > _MAX_PAYLOAD:
        raise ValueError("websocket 帧过大")
    mask_len = 4 if masked else 0
    total = offset + mask_len + length
    if len(buf) < total:
        return None
    payload = bytes(buf[offset + mask_len : total])
    if masked:
        mask = bytes(buf[offset : offset + 4])
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload, total
