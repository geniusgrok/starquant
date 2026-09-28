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

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "btc_account.yaml"


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


def load_config(path: Path | None = None) -> AccountConfig:
    raw = yaml.safe_load((path or DEFAULT_PATH).read_text())
    return AccountConfig(
        symbol=str(raw["symbol"]),
        margin_mode=str(raw["margin_mode"]),
        position_mode=str(raw["position_mode"]),
        leverage=int(raw["leverage"]),
        start_cny=float(raw["start_cny"]),
        session_seconds=int(raw["session_seconds"]),
        poll_seconds=int(raw["poll_seconds"]),
        entry_hours=int(raw["entry_hours"]),
        exit_hours=int(raw["exit_hours"]),
        stop=float(raw["stop"]),
        trail=float(raw["trail"]),
        add_step=float(raw["add_step"]),
        max_units=int(raw["max_units"]),
        risk=float(raw["risk"]),
        dd_flat=float(raw["dd_flat"]),
        flatten_ratio=float(raw["flatten_ratio"]),
        entry_scale_below=float(raw["entry_scale_below"]),
        entry_scale=float(raw["entry_scale"]),
        iso_frac=float(raw["iso_frac"]),
        cooldown_hours=int(raw["cooldown_hours"]),
        ratchet_gain=float(raw["ratchet_gain"]),
        ratchet_trail=float(raw["ratchet_trail"]),
        heat=float(raw["heat"]),
        take_profit_multiple=float(raw["take_profit_multiple"]),
        taker=float(raw["taker"]),
        slip_base=float(raw["slip_base"]),
        impact_y=float(raw["impact_y"]),
        fx_fee=float(raw["fx_fee"]),
    )
