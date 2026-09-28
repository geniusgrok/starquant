"""USDⓈ-M REST client. Demo and production hosts are fixed and never swapped.

Conditional orders go to ``/fapi/v1/algoOrder``. A ``-4120`` from the plain
order route freezes the caller; it does not retry on the other environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from btc_perp.gates import assert_host_matches, hosts
from btc_perp.machine import check_algo_shape
from btc_perp.model import AlgoOrder, Filters, RestingOrder, Snapshot


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        """Return the status code and the body."""


class UrllibTransport:
    def request(self, method: str, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        req = urllib.request.Request(url, method=method, headers=dict(headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()


class UnknownExecution(RuntimeError):
    """The write may have reached the exchange. Query the original id."""


class AlgoEndpointRequired(RuntimeError):
    """Plain /order refused a conditional type. Do not change host."""


def redact(text: str, secrets: tuple[str, ...]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


@dataclass
class UsdMClient:
    environment: str
    api_key: str
    api_secret: str
    transport: Transport
    base_url: str | None = None
    timeout: float = 10.0

    def __post_init__(self) -> None:
        official, self.ws_base = hosts(self.environment)
        self.base_url = (self.base_url or official).rstrip("/")
        assert_host_matches(self.environment, self.base_url)
        self._offset_ms = 0

    def _signed(self, path: str, params: dict[str, str], method: str) -> tuple[int, dict[str, object]]:
        query = dict(params)
        query["timestamp"] = str(int(time.time() * 1000) + self._offset_ms)
        query["recvWindow"] = "5000"
        payload = urllib.parse.urlencode(query)
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base_url}{path}?{payload}&signature={signature}"
        try:
            status, body = self.transport.request(
                method,
                url,
                {"X-MBX-APIKEY": self.api_key},
                self.timeout,
            )
        except (TimeoutError, OSError) as exc:
            if method in {"POST", "DELETE"}:
                raise UnknownExecution(redact(str(exc), (self.api_key, self.api_secret))) from exc
            raise
        text = redact(body.decode("utf-8", "replace"), (self.api_key, self.api_secret))
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            if method in {"POST", "DELETE"}:
                raise UnknownExecution("交易所返回无法解析") from exc
            raise RuntimeError("交易所返回无法解析") from exc
        if not isinstance(parsed, dict):
            return status, {"raw": parsed}
        if parsed.get("code") == -4120:
            raise AlgoEndpointRequired("条件单必须走 /fapi/v1/algoOrder，不会改域名重试")
        return status, parsed

    def _public(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        status, body = self.transport.request("GET", url, {}, self.timeout)
        parsed = json.loads(body.decode("utf-8", "replace") or "{}")
        if status >= 400:
            raise RuntimeError(f"{path} -> {status}")
        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}

    def sync_time(self) -> int:
        payload = self._public("/fapi/v1/time")
        server = int(_f(payload.get("serverTime")))
        self._offset_ms = server - int(time.time() * 1000)
        return server

    def _write(self, path: str, params: dict[str, str], method: str) -> dict[str, object]:
        status, parsed = self._signed(path, params, method)
        if status >= 500 or status == 429 or status == 0:
            raise UnknownExecution(f"{path} -> {status}")
        if status >= 400 and "code" not in parsed:
            raise UnknownExecution(f"{path} -> {status}")
        return parsed

    def place_market(self, *, client_id: str, side: str, qty: str, reduce_only: bool) -> dict[str, object]:
        if not client_id or not qty or qty == "0":
            raise ValueError("市价单需要客户端身份和数量")
        return self._write(
            "/fapi/v1/order",
            {
                "symbol": "BTCUSDT",
                "side": side,
                "type": "MARKET",
                "quantity": qty,
                "reduceOnly": "true" if reduce_only else "false",
                "newClientOrderId": client_id,
                "positionSide": "BOTH",
                "newOrderRespType": "RESULT",
            },
            "POST",
        )

    def place_algo(
        self,
        *,
        client_id: str,
        side: str,
        order_type: str,
        trigger_price: str,
        close_position: bool,
        qty: str = "",
        reduce_only: bool = False,
    ) -> dict[str, object]:
        if order_type not in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
            raise ValueError("只通过 Algo 接口发送止损和止盈市价单")
        check_algo_shape(close_position=close_position, qty=qty, reduce_only=reduce_only)
        params = {
            "algoType": "CONDITIONAL",
            "symbol": "BTCUSDT",
            "side": side,
            "type": order_type,
            "triggerPrice": trigger_price,
            "workingType": "CONTRACT_PRICE",
            "clientAlgoId": client_id,
            "positionSide": "BOTH",
        }
        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = qty
            params["reduceOnly"] = "true"
        return self._write("/fapi/v1/algoOrder", params, "POST")

    def cancel_order(self, client_id: str) -> dict[str, object]:
        return self._write("/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": client_id}, "DELETE")

    def cancel_algo(self, client_id: str) -> dict[str, object]:
        return self._write("/fapi/v1/algoOrder", {"clientAlgoId": client_id}, "DELETE")

    def query_order(self, client_id: str) -> dict[str, object]:
        return self._signed("/fapi/v1/order", {"symbol": "BTCUSDT", "origClientOrderId": client_id}, "GET")[1]

    def query_algo(self, client_id: str) -> dict[str, object]:
        return self._signed("/fapi/v1/algoOrder", {"clientAlgoId": client_id}, "GET")[1]

    def create_listen_key(self) -> str:
        parsed = self._listen("POST")
        key = parsed.get("listenKey")
        if not isinstance(key, str) or not key:
            raise RuntimeError("listenKey 缺失")
        return key

    def keepalive_listen_key(self) -> None:
        self._listen("PUT")

    def close_listen_key(self) -> None:
        self._listen("DELETE")

    def _listen(self, method: str) -> dict[str, object]:
        url = f"{self.base_url}/fapi/v1/listenKey"
        try:
            status, body = self.transport.request(method, url, {"X-MBX-APIKEY": self.api_key}, self.timeout)
        except (TimeoutError, OSError) as exc:
            raise RuntimeError(redact(str(exc), (self.api_key, self.api_secret))) from exc
        text = redact(body.decode("utf-8", "replace"), (self.api_key, self.api_secret))
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError("listenKey 响应无法解析") from exc
        if not isinstance(parsed, dict) or status >= 400 or parsed.get("code") not in (None, 0):
            raise RuntimeError("listenKey 请求失败")
        return parsed

    def klines(self, interval: str, limit: int) -> list[object]:
        payload = self._public("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": interval, "limit": str(limit)})
        raw = payload.get("raw")
        if isinstance(raw, list):
            return raw
        return []

    def snapshot(self) -> Snapshot:
        try:
            server = self.sync_time()
            info = self._public("/fapi/v1/exchangeInfo", {"symbol": "BTCUSDT"})
            account = self._signed("/fapi/v2/account", {}, "GET")[1]
            dual = self._signed("/fapi/v1/positionSide/dual", {}, "GET")[1]
            orders = self._signed("/fapi/v1/openOrders", {"symbol": "BTCUSDT"}, "GET")[1]
            algos = self._signed("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"}, "GET")[1]
            positions = self._signed("/fapi/v2/positionRisk", {"symbol": "BTCUSDT"}, "GET")[1]
        except UnknownExecution:
            return _unknown("签名请求超时，结果未知")
        except (OSError, TimeoutError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            return _unknown(redact(str(exc), (self.api_key, self.api_secret))[:300])
        built = _snapshot_from(server, info, account, dual, orders, algos, positions)
        if not built.known:
            return built
        last, fee, brackets, trades, funding = self._extras()
        return Snapshot(
            known=built.known,
            reason=built.reason,
            position_qty=built.position_qty,
            entry_price=built.entry_price,
            wallet_usdt=built.wallet_usdt,
            available_usdt=built.available_usdt,
            mark_price=built.mark_price,
            last_price=last if last > 0 else 0.0,
            liquidation_price=built.liquidation_price,
            one_way=built.one_way,
            isolated=built.isolated,
            leverage=built.leverage,
            symbol_status=built.symbol_status,
            server_time_ms=built.server_time_ms,
            orders=built.orders,
            algos=built.algos,
            can_trade=built.can_trade,
            fee_taker=fee,
            filters=built.filters,
            brackets_ok=brackets,
            recent_trades_ok=trades,
            funding_ok=funding,
        )

    def _extras(self) -> tuple[float, float | None, bool, bool, bool]:
        last = 0.0
        fee: float | None = None
        brackets = False
        trades = False
        funding = False
        try:
            ticker = self._public("/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
            last = _f(ticker.get("price", 0) or 0)
        except (OSError, TimeoutError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, ValueError):
            last = 0.0
        fee = self._optional_fee()
        brackets = self._optional_ok("/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"})
        trades = self._optional_ok("/fapi/v1/userTrades", {"symbol": "BTCUSDT", "limit": "5"})
        funding = self._optional_ok("/fapi/v1/income", {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE", "limit": "5"})
        return last, fee, brackets, trades, funding

    def _optional_fee(self) -> float | None:
        try:
            body = self._signed("/fapi/v1/commissionRate", {"symbol": "BTCUSDT"}, "GET")[1]
        except (UnknownExecution, OSError, TimeoutError, RuntimeError, json.JSONDecodeError):
            return None
        raw = body.get("takerCommissionRate")
        if raw is None or body.get("code") not in (None, 0):
            return None
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _optional_ok(self, path: str, params: dict[str, str]) -> bool:
        try:
            body = self._signed(path, params, "GET")[1]
        except (UnknownExecution, OSError, TimeoutError, RuntimeError, json.JSONDecodeError):
            return False
        code = body.get("code")
        return code in (None, 0)


def _unknown(reason: str) -> Snapshot:
    return Snapshot(
        known=False,
        reason=reason,
        position_qty=0.0,
        entry_price=0.0,
        wallet_usdt=0.0,
        available_usdt=0.0,
        mark_price=0.0,
        last_price=0.0,
        liquidation_price=0.0,
        one_way=False,
        isolated=False,
        leverage=0,
        symbol_status="",
        server_time_ms=0,
    )


def _as_dicts(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict) and isinstance(payload.get("raw"), list):
        return [item for item in payload["raw"] if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("orders"), list):
        return [item for item in payload["orders"] if isinstance(item, dict)]
    return []


def _snapshot_from(
    server: int,
    info: dict[str, object],
    account: dict[str, object],
    dual: dict[str, object],
    orders: dict[str, object],
    algos: dict[str, object],
    positions: dict[str, object],
) -> Snapshot:
    symbols = info.get("symbols")
    if not isinstance(symbols, list) or not symbols or not isinstance(symbols[0], dict):
        return _unknown("exchangeInfo 没有 BTCUSDT")
    symbol = symbols[0]
    filters = {str(item.get("filterType")): item for item in symbol.get("filters", []) if isinstance(item, dict)}
    lot = filters.get("LOT_SIZE", {})
    price = filters.get("PRICE_FILTER", {})
    notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
    if not isinstance(lot, dict) or not isinstance(price, dict) or not isinstance(notional, dict):
        return _unknown("过滤器缺失")
    parsed_filters = Filters(
        tick_size=_f(price.get("tickSize", 0) or 0),
        step_size=_f(lot.get("stepSize", 0) or 0),
        min_qty=_f(lot.get("minQty", 0) or 0),
        min_notional=_f(notional.get("notional", 0) or 0),
        min_price=_f(price.get("minPrice", 0) or 0),
        max_price=_f(price.get("maxPrice", 0) or 0),
    )
    pos_rows = _as_dicts(positions)
    row = pos_rows[0] if pos_rows else {}
    qty = _f(row.get("positionAmt", 0) or 0)
    resting = tuple(
        RestingOrder(
            client_id=str(item.get("clientOrderId", "")),
            side=str(item.get("side", "")),
            order_type=str(item.get("type", "")),
            qty=_f(item.get("origQty", 0) or 0),
            filled=_f(item.get("executedQty", 0) or 0),
            reduce_only=str(item.get("reduceOnly", "")).lower() == "true",
            status=str(item.get("status", "")),
            price=_f(item.get("price", 0) or 0),
        )
        for item in _as_dicts(orders)
    )
    algo_rows = tuple(
        AlgoOrder(
            client_algo_id=str(item.get("clientAlgoId", "")),
            order_type=str(item.get("orderType", item.get("type", ""))),
            side=str(item.get("side", "")),
            trigger_price=_f(item.get("triggerPrice", 0) or 0),
            close_position=str(item.get("closePosition", "")).lower() == "true",
            reduce_only=str(item.get("reduceOnly", "")).lower() == "true",
            qty=_f(item.get("quantity", 0) or 0),
            status=str(item.get("algoStatus", item.get("status", ""))),
            working_type=str(item.get("workingType", "")),
        )
        for item in _as_dicts(algos)
    )
    assets = account.get("assets")
    wallet = 0.0
    available = 0.0
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("asset") == "USDT":
                wallet = _f(asset.get("walletBalance", 0) or 0)
                available = _f(asset.get("availableBalance", 0) or 0)
    return Snapshot(
        known=True,
        reason="",
        position_qty=qty,
        entry_price=_f(row.get("entryPrice", 0) or 0),
        wallet_usdt=wallet,
        available_usdt=available,
        mark_price=_f(row.get("markPrice", 0) or 0),
        last_price=0.0,
        liquidation_price=_f(row.get("liquidationPrice", 0) or 0),
        one_way=not bool(dual.get("dualSidePosition")),
        isolated=str(row.get("marginType", "")).lower() == "isolated",
        leverage=int(_f(row.get("leverage", 0) or 0)),
        symbol_status=str(symbol.get("status", "")),
        server_time_ms=server,
        orders=resting,
        algos=algo_rows,
        can_trade=bool(account.get("canTrade")),
        fee_taker=None,
        filters=parsed_filters,
    )


def _f(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def account_problems(snapshot: Snapshot, filters_ok: bool) -> str:
    if not snapshot.known:
        return snapshot.reason or "账户未知"
    if snapshot.symbol_status != "TRADING":
        return "BTCUSDT 不在交易状态"
    if not snapshot.one_way:
        return "账户不是单向持仓"
    if not snapshot.isolated:
        return "BTCUSDT 不是逐仓"
    if snapshot.leverage != 20:
        return f"杠杆是 {snapshot.leverage}，配置是 20，不会自动修改"
    if not snapshot.can_trade:
        return "API 没有交易权限"
    if not filters_ok:
        return "交易所过滤器不可用"
    return ""
