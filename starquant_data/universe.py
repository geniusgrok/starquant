"""Universe selection: top-N liquid USDT perpetuals with rank hysteresis (pure; shared by research and live)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starquant_shared.types import InstrumentRules


@dataclass(frozen=True)
class UniverseConfig:
    quote_asset: str = "USDT"
    top_n: int = 15
    always_include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    max_min_notional_usdt: float = 20.0
    enter_rank: int = 15
    exit_rank: int = 20
    volume_lookback_days: int = 30
    interval: str = "1h"
    history_start: str = "2021-01"
    refresh: str = "daily"  # live refresh cadence: daily | never
    min_age_days: int = 30  # a symbol needs this much daily history before it can be ranked (D-013)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> UniverseConfig:
        hysteresis = payload.get("hysteresis", {}) or {}
        return cls(
            quote_asset=str(payload.get("quote_asset", "USDT")),
            top_n=int(payload.get("top_n", 15)),
            always_include=tuple(str(s) for s in payload.get("always_include", []) or []),
            exclude=tuple(str(s) for s in payload.get("exclude", []) or []),
            max_min_notional_usdt=float(payload.get("max_min_notional_usdt", 20.0)),
            enter_rank=int(hysteresis.get("enter_rank", payload.get("top_n", 15))),
            exit_rank=int(hysteresis.get("exit_rank", int(payload.get("top_n", 15)) + 5)),
            volume_lookback_days=int(payload.get("volume_lookback_days", 30)),
            interval=str(payload.get("interval", "1h")),
            history_start=str(payload.get("history_start", "2021-01")),
            refresh=str(payload.get("refresh", "daily")),
            min_age_days=int(payload.get("min_age_days", 30)),
        )


def eligible_symbols(rules: Mapping[str, InstrumentRules], config: UniverseConfig) -> list[str]:
    chosen: list[str] = []
    for symbol, rule in rules.items():
        if symbol in config.exclude:
            continue
        if not rule.tradable or rule.quote_asset != config.quote_asset:
            continue
        if float(rule.min_notional) > config.max_min_notional_usdt and symbol not in config.always_include:
            continue
        chosen.append(symbol)
    return sorted(chosen)


def rank_with_hysteresis(
    volume_by_symbol: Mapping[str, float],
    eligible: Iterable[str],
    previous: Iterable[str],
    *,
    enter_rank: int,
    exit_rank: int,
    top_n: int,
    always_include: Iterable[str] = (),
) -> list[str]:
    """Rank ``eligible`` symbols by volume; enter at ``enter_rank``, leave only beyond ``exit_rank``.

    ``always_include`` symbols are kept whenever they are eligible.  The result
    is ordered by rank and capped at ``max(top_n, exit_rank) + len(always_include)``.
    """
    eligible_set = set(eligible)
    ranked = sorted((s for s in eligible_set if s in volume_by_symbol), key=lambda s: -float(volume_by_symbol[s]))
    rank = {symbol: position + 1 for position, symbol in enumerate(ranked)}
    pinned = [s for s in always_include if s in eligible_set]
    keep: set[str] = set(pinned)
    previous_set = set(previous)
    for symbol, position in rank.items():
        if position <= enter_rank or (symbol in previous_set and position <= exit_rank):
            keep.add(symbol)
    ordered = sorted(keep, key=lambda s: rank.get(s, 10**6))
    limit = max(top_n, exit_rank) + len(pinned)
    return ordered[:limit]
