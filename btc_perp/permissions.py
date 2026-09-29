"""Read-only check that a production key cannot withdraw or transfer.

Demo keys are not sent to the spot API. A failed or incomplete read refuses
production orders. This module does not place an order.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from collections.abc import Mapping
from typing import Protocol

_SPOT = "https://api.binance.com"
_PATH = "/sapi/v1/account/apiRestrictions"
_ACCOUNT_PATH = "/api/v3/account"


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        """Return the status code and the body."""


def prod_permission_block(
    environment: str,
    api_key: str,
    api_secret: str,
    transport: Transport,
    *,
    now_ms: int | None = None,
) -> str:
    """Empty string means production may send. Demo returns empty without a request."""
    if environment != "prod":
        return ""
    stamp = int(time.time() * 1000) if now_ms is None else now_ms
    query = urllib.parse.urlencode({"timestamp": str(stamp), "recvWindow": "5000"})
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{_SPOT}{_PATH}?{query}&signature={signature}"
    try:
        status, body = transport.request("GET", url, {"X-MBX-APIKEY": api_key}, 10.0)
        parsed = json.loads(body.decode("utf-8", "replace") or "{}")
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
        return "无法确认密钥没有提币或划转权限，生产拒绝下单"
    if status >= 400 or not isinstance(parsed, dict) or parsed.get("code") not in (None, 0):
        return "无法确认密钥没有提币或划转权限，生产拒绝下单"
    if parsed.get("enableFutures") is not True:
        return "密钥没有合约权限，生产拒绝下单"
    if parsed.get("enableWithdrawals") is True or parsed.get("enableInternalTransfer") is True:
        return "密钥开通了提币或划转，生产拒绝下单"
    if parsed.get("permitsUniversalTransfer") is True:
        return "密钥开通了提币或划转，生产拒绝下单"
    return ""


def prod_uid_block(
    api_key: str,
    api_secret: str,
    transport: Transport,
    expected_uid: str,
    *,
    now_ms: int | None = None,
) -> str:
    """Empty string means the key belongs to the account whose UID the operator declared.

    The state directory follows this UID, so an unread or different UID
    refuses to run rather than starting a second history for the same money.
    """
    if not expected_uid:
        return "生产必须设置 STARQUANT_ACCOUNT_UID（账户 UID），状态目录按它绑定"
    stamp = int(time.time() * 1000) if now_ms is None else now_ms
    query = urllib.parse.urlencode({"timestamp": str(stamp), "recvWindow": "5000", "omitZeroBalances": "true"})
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{_SPOT}{_ACCOUNT_PATH}?{query}&signature={signature}"
    try:
        status, body = transport.request("GET", url, {"X-MBX-APIKEY": api_key}, 10.0)
        parsed = json.loads(body.decode("utf-8", "replace") or "{}")
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeError, ValueError):
        return "读不到账户 UID，无法确认密钥属于哪个账户，生产拒绝运行"
    if status >= 400 or not isinstance(parsed, dict) or parsed.get("code") not in (None, 0):
        return "读不到账户 UID，无法确认密钥属于哪个账户，生产拒绝运行"
    found = parsed.get("uid")
    if isinstance(found, bool) or not isinstance(found, int | str) or str(found) != expected_uid:
        return "密钥所属账户的 UID 和 STARQUANT_ACCOUNT_UID 不一致，生产拒绝运行"
    return ""
