"""The one config for the one research account.

``scripts.frontier.run`` reads the strategy fields (windows, stops, risk,
``dd_flat``, ``flatten_ratio``, entry scale, heat, ratchet, and cooldown).
Fee rates and those scale lines live in ``btc_perp.costs`` and are copied
into the YAML. A test rejects a drift between the two. ``take_profit_multiple`` is a disaster cap (long entry times the multiple,
short entry divided by it). The research exit is the trail, the channel, or
the half-peak flatten. The forward runner rests that cap on the exchange and
does not count it as the strategy exit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "btc_account.yaml"
MAX_CHANNEL_HOURS = 1400


@dataclass(frozen=True)
class AccountConfig:
    symbol: str
    margin_mode: str
    position_mode: str
    leverage: int
    start_cny: float
    session_seconds: int
    poll_seconds: int
    entry_hours: int
    exit_hours: int
    stop: float
    trail: float
    add_step: float
    max_units: int
    risk: float
    dd_flat: float
    flatten_ratio: float
    entry_scale_below: float
    entry_scale: float
    iso_frac: float
    cooldown_hours: int
    ratchet_gain: float
    ratchet_trail: float
    heat: float
    take_profit_multiple: float
    taker: float
    slip_base: float
    impact_y: float
    fx_fee: float


class ConfigError(ValueError):
    """The account file is missing a field or holds a value the strategy cannot use."""


def _real(
    raw: dict[str, object], key: str, low: float, high: float, *, low_open: bool = True, high_open: bool = True
) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{key} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{key} 必须是有限数字")
    below = number <= low if low_open else number < low
    above = number >= high if high_open else number > high
    if below or above:
        raise ConfigError(f"{key}={number} 超出允许范围")
    return number


def _whole(raw: dict[str, object], key: str, low: int, high: int) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} 必须是整数")
    if value < low or value > high:
        raise ConfigError(f"{key}={value} 超出允许范围 [{low}, {high}]")
    return value


def _text(raw: dict[str, object], key: str, allowed: set[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(f"{key} 必须是 {sorted(allowed)} 之一")
    return value


def load_config(path: Path | None = None) -> AccountConfig:
    loaded = yaml.safe_load((path or DEFAULT_PATH).read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("账户配置不是键值表")
    raw: dict[str, object] = loaded
    unknown = set(raw) - set(AccountConfig.__dataclass_fields__)
    if unknown:
        raise ConfigError("未知账户配置项：" + ", ".join(sorted(map(str, unknown))))
    cfg = AccountConfig(
        symbol=_text(raw, "symbol", {"BTCUSDT"}),
        margin_mode=_text(raw, "margin_mode", {"isolated"}),
        position_mode=_text(raw, "position_mode", {"one_way"}),
        leverage=_whole(raw, "leverage", 1, 125),
        start_cny=_real(raw, "start_cny", 0.0, math.inf),
        session_seconds=_whole(raw, "session_seconds", 1, 86_400),
        poll_seconds=_whole(raw, "poll_seconds", 1, 3_600),
        entry_hours=_whole(raw, "entry_hours", 2, MAX_CHANNEL_HOURS),
        exit_hours=_whole(raw, "exit_hours", 2, MAX_CHANNEL_HOURS),
        stop=_real(raw, "stop", 0.0, 1.0),
        trail=_real(raw, "trail", 0.0, 1.0),
        add_step=_real(raw, "add_step", 0.0, 1.0),
        max_units=_whole(raw, "max_units", 1, 10),
        risk=_real(raw, "risk", 0.0, 1.0),
        dd_flat=_real(raw, "dd_flat", 0.0, 1.0),
        flatten_ratio=_real(raw, "flatten_ratio", 0.0, 1.0, low_open=False),
        entry_scale_below=_real(raw, "entry_scale_below", 0.0, 1.0, high_open=False),
        entry_scale=_real(raw, "entry_scale", 0.0, 1.0, high_open=False),
        iso_frac=_real(raw, "iso_frac", 0.0, 1.0, high_open=False),
        cooldown_hours=_whole(raw, "cooldown_hours", 0, 24 * 30),
        ratchet_gain=_real(raw, "ratchet_gain", 0.0, math.inf, low_open=False),
        ratchet_trail=_real(raw, "ratchet_trail", 0.0, 1.0),
        heat=_real(raw, "heat", 0.0, math.inf, low_open=False),
        take_profit_multiple=_real(raw, "take_profit_multiple", 1.0, math.inf),
        taker=_real(raw, "taker", 0.0, 0.01, low_open=False),
        slip_base=_real(raw, "slip_base", 0.0, 0.05, low_open=False),
        impact_y=_real(raw, "impact_y", 0.0, 10.0, low_open=False),
        fx_fee=_real(raw, "fx_fee", 0.0, 0.05, low_open=False),
    )
    if cfg.stop * cfg.leverage >= 1.0:
        raise ConfigError("stop 乘杠杆必须小于 1，否则止损在强平价之外")
    from btc_perp import costs

    frozen = {
        "start_cny": costs.START_CNY,
        "leverage": costs.LEVERAGE,
        "taker": costs.TAKER,
        "slip_base": costs.SLIP_BASE,
        "impact_y": costs.IMPACT_Y,
        "fx_fee": costs.FX_FEE,
        "entry_scale_below": costs.ENTRY_SCALE_BELOW,
        "entry_scale": costs.ENTRY_SCALE,
        "flatten_ratio": costs.FLATTEN_RATIO,
    }
    for field, expected in frozen.items():
        if getattr(cfg, field) != expected:
            raise ConfigError(f"{field} 与冻结回放内核不一致：期望 {expected}")
    return cfg
