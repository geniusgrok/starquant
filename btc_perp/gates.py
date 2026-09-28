"""Environment choice and the production risk gate.

Demo and production do not share a host, a key, or a state directory. A missing
capital cap refuses production entries. Nothing in this module sends an order.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from btc_perp.config import ROOT
from btc_perp.model import Limits

DEMO = "demo"
PROD = "prod"
DEMO_REST = "https://demo-fapi.binance.com"
PROD_REST = "https://fapi.binance.com"
# Host only. Since 2026-04-23 the user stream is /private/ws?listenKey=...&events=...
DEMO_WS = "wss://demo-fstream.binance.com"
PROD_WS = "wss://fstream.binance.com"
PROD_ORDER_ENV = "STARQUANT_ALLOW_PROD_ORDERS"


def hosts(environment: str) -> tuple[str, str]:
    if environment == DEMO:
        return DEMO_REST, DEMO_WS
    if environment == PROD:
        return PROD_REST, PROD_WS
    raise ValueError(f"environment must be {DEMO} or {PROD}")


def assert_host_matches(environment: str, base_url: str) -> None:
    """Refuse a client that would send one environment's orders to the other."""
    demo, _ws_demo = hosts(DEMO)
    prod, _ws_prod = hosts(PROD)
    if environment == DEMO and base_url.rstrip("/") == prod:
        raise RuntimeError("demo 客户端不能使用生产域名")
    if environment == PROD and base_url.rstrip("/") == demo:
        raise RuntimeError("生产客户端不能使用 demo 域名")
    official, _ws = hosts(environment)
    if base_url.rstrip("/") == official:
        return
    parts = urlsplit(base_url)
    loopback = {"127.0.0.1", "localhost", "::1"}
    if parts.scheme == "http" and parts.hostname in loopback and parts.username is None and parts.password is None:
        return
    raise RuntimeError("只允许官方域名或本机回环测试桩")


def load_limits(path: Path | None = None) -> Limits:
    file = path or (ROOT / "config" / "limits.yaml")
    if not file.exists():
        return Limits(None, None, None, None)
    raw = yaml.safe_load(file.read_text()) or {}

    def num(key: str) -> float | None:
        value = raw.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"{key} 必须是数字")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{key} 必须是有限的非负数")
        return number

    seconds = raw.get("max_unprotected_seconds")
    if isinstance(seconds, bool) or (seconds not in (None, "") and int(seconds) < 0):
        raise ValueError("max_unprotected_seconds 必须是非负整数")
    return Limits(
        capital_usdt=num("capital_usdt"),
        max_notional_usdt=num("max_notional_usdt"),
        max_daily_loss_usdt=num("max_daily_loss_usdt"),
        max_unprotected_seconds=None if seconds in (None, "") else int(seconds),
    )


def prod_orders_allowed(environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(PROD_ORDER_ENV) == "yes"


def entry_block_reason(
    environment: str,
    limits: Limits,
    max_notional_usdt: float | None,
    *,
    prod_enabled: bool,
) -> str:
    """Empty string means a new risk-increasing order is allowed."""
    if environment == PROD:
        if not prod_enabled:
            return f"生产增仓已关闭：未设置 {PROD_ORDER_ENV}=yes"
        if limits.capital_usdt is None or limits.capital_usdt <= 0:
            return "生产增仓已关闭：config/limits.yaml 的 capital_usdt 还是空的"
        if limits.max_notional_usdt is None or limits.max_notional_usdt <= 0:
            return "生产增仓已关闭：config/limits.yaml 的 max_notional_usdt 还是空的"
        if limits.max_daily_loss_usdt is None or limits.max_daily_loss_usdt <= 0:
            return "生产增仓已关闭：config/limits.yaml 的 max_daily_loss_usdt 还是空的"
        if limits.max_unprotected_seconds is None or limits.max_unprotected_seconds <= 0:
            return "生产增仓已关闭：config/limits.yaml 的 max_unprotected_seconds 还是空的"
        if max_notional_usdt is None or max_notional_usdt <= 0:
            return "生产增仓已关闭：命令行没有给出 --max-notional-usdt"
        if max_notional_usdt > limits.max_notional_usdt:
            return "命令行名义上限高于 config/limits.yaml"
        return ""
    if environment == DEMO:
        if max_notional_usdt is None or max_notional_usdt <= 0:
            return "demo 增仓需要 --max-notional-usdt，例如 python -m btc_perp run --environment demo --max-notional-usdt 200"
        return ""
    return "未知环境"


def reducing_block_reason(environment: str, *, prod_enabled: bool) -> str:
    """A reduce-only flatten still sends an order, so production stays gated."""
    if environment == PROD and not prod_enabled:
        return f"生产订单已关闭：未设置 {PROD_ORDER_ENV}=yes"
    if environment not in {DEMO, PROD}:
        return "未知环境"
    return ""


def notional_cap(cli: float | None, limits: Limits) -> float | None:
    """The smaller positive of the command-line cap and the file cap."""
    caps = [value for value in (cli, limits.max_notional_usdt) if value is not None and value > 0]
    return min(caps) if caps else None


def risk_equity(equity_usdt: float, limits: Limits) -> float:
    """Sizing never uses more than the owner's stated capital."""
    if limits.capital_usdt is not None and limits.capital_usdt > 0:
        return min(equity_usdt, limits.capital_usdt)
    return equity_usdt
