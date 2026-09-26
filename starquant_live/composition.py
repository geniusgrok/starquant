"""Composition helpers shared by the CLI and the live loop: stores -> Panel, config -> model/costs."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_alpha.backtest import CostModel, ImpactModel
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel, interval_seconds
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import Registry, parse_registry
from starquant_data.metrics import PERIOD_MS, align_to_bars
from starquant_data.spot import SPOT_PANEL_COLUMNS, SpotMapping, align_spot_to_perp_bars, read_spot_map
from starquant_data.store import FundingStore, KlineStore, MetricsStore, funding_per_bar
from starquant_shared.config import load_yaml

UNIVERSE_STATE = "universe.json"
logger = logging.getLogger(__name__)


def _metrics_columns(store: MetricsStore, panel: Panel, interval: str) -> dict[str, pd.DataFrame] | None:
    """DL-D4: one wide frame per metrics column, aligned HERE and not in `Panel`.

    This is the only place the five minutes can be got wrong, which is why it is the only place that
    knows the rule.  `align_to_bars` gives each bar the latest bucket that had CLOSED by the bar's own
    close; `Panel.from_frames` then refuses anything not already on the bar index, so the alignment
    cannot be skipped by a caller who builds a panel some other way.

    A symbol with no stored metrics is left out rather than zero-filled, and the column is then NaN for
    it.  `_required_metric` lets a node evaluate on that - a NaN score is no score - while zero-filling
    would make a node read "no open interest change" where the truth is "nobody ingested it".
    """
    step_ms = interval_seconds(interval) * 1000
    per_symbol: dict[str, pd.DataFrame] = {}
    for symbol in panel.symbols:
        frame = store.load(symbol)
        if not frame.empty:
            per_symbol[symbol] = align_to_bars(frame, panel.index, interval_ms=step_ms, period_ms=PERIOD_MS["5m"])
    if not per_symbol:
        return None
    names = sorted({column for frame in per_symbol.values() for column in frame.columns})
    return {
        name: pd.DataFrame(
            {symbol: frame[name] for symbol, frame in per_symbol.items() if name in frame}, index=panel.index
        ).reindex(columns=panel.symbols)
        for name in names
    }


def _spot_columns(
    store: KlineStore, panel: Panel, mappings: Mapping[str, SpotMapping]
) -> dict[str, pd.DataFrame] | None:
    """DL-D5: one wide frame per spot field, keyed by the PERPETUAL symbol, aligned HERE and not in `Panel`.

    Every perpetual in the panel gets a column, including the ones with no spot leg, and that is the
    point: 166 of 528 perpetuals have none, so "this symbol has no spot" is an answer the panel has to
    be able to give.  It gives it as NaN, never as zero and never as the last price that existed - the
    two failures `align_spot_to_perp_bars` was written to make unrepresentable.

    The mapping comes from the file the sync wrote, not from the store's directory listing.  A listing
    says which spot symbols were downloaded; it cannot say which perpetual each one belongs to, and
    re-deriving that from the names is the string rule that gets 1000SATSUSDT wrong.
    """
    per_symbol: dict[str, pd.DataFrame] = {}
    for symbol in panel.symbols:
        mapping = mappings.get(symbol)
        if mapping is None or mapping.spot is None:
            continue
        try:
            frame = store.load(mapping.spot, panel.interval)
        except FileNotFoundError:
            continue
        per_symbol[symbol] = align_spot_to_perp_bars(frame, panel.index, multiplier=mapping.multiplier)
    if not per_symbol:
        return None
    return {
        field: pd.DataFrame({symbol: frame[field] for symbol, frame in per_symbol.items()}, index=panel.index).reindex(
            columns=panel.symbols
        )
        for field in SPOT_PANEL_COLUMNS
    }


def load_panel(
    store: KlineStore,
    symbols: Sequence[str],
    interval: str,
    *,
    funding_store: FundingStore | None = None,
    metrics_store: MetricsStore | None = None,
    spot_store: KlineStore | None = None,
    spot_map: Mapping[str, SpotMapping] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> Panel:
    """Wide panel from the parquet store; symbols without stored klines are excluded (and logged), not fatal.

    The live pool can admit a symbol (e.g. a fresh listing) before ``starquant data
    sync`` has ever downloaded it; research on ``universe.json`` must not crash
    on such a name.
    """
    start_ms = None if start is None else int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = None if end is None else int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for symbol in symbols:
        try:
            frame = store.load(symbol, interval, start_ms, end_ms)
        except FileNotFoundError:
            missing.append(symbol)
            continue
        if not frame.empty:
            frames[symbol] = frame
    if missing:
        logger.warning("no %s klines stored for %s; excluded from the panel", interval, missing)
    if not frames:
        raise ValueError("no kline data for the requested symbols/range")
    panel = Panel.from_frames(frames, interval=interval)
    if funding_store is None and metrics_store is None and spot_store is None:
        return panel
    funding = (
        {symbol: funding_per_bar(funding_store.load(symbol), panel.index) for symbol in panel.symbols}
        if funding_store is not None
        else None
    )
    metrics = _metrics_columns(metrics_store, panel, interval) if metrics_store is not None else None
    spot = _spot_columns(spot_store, panel, spot_map or read_spot_map(spot_store.root)) if spot_store else None
    return Panel.from_frames(frames, interval=interval, funding=funding, metrics=metrics, spot=spot)


def load_registry(path: str | Path) -> Registry:
    return parse_registry(load_yaml(path))


def portfolio_params(profile: Mapping[str, Any]) -> PortfolioParams:
    return PortfolioParams.from_mapping(profile.get("portfolio", {}) or {})


def cost_model(costs: Mapping[str, Any], *, use_funding: bool | None = None) -> CostModel:
    turnover = float(costs.get("taker_fee_bps", 5.0)) + float(costs.get("slippage_bps", 2.0))
    funding = bool(costs.get("use_actual_funding", True)) if use_funding is None else use_funding
    return CostModel(turnover_bps=turnover, carry_bps_per_bar=0.0, use_funding=funding)


def impact_model(costs: Mapping[str, Any], *, capital: float = 0.0) -> ImpactModel:
    """DL-C1.  ``capital`` of 0 keeps the flat, scale-free model, which is this model's own limit."""
    block = costs.get("impact") or {}
    return ImpactModel(
        capital=float(capital),
        coefficient=float(block.get("coefficient", 1.0)),
        adv_window=int(block.get("adv_window_bars", 720)),
        vol_window=int(block.get("vol_window_bars", 720)),
    )


def build_model(registry: Registry, profile: Mapping[str, Any]) -> AlphaModel:
    interval = str((profile.get("market_data", {}) or {}).get("interval", "1h"))
    min_history = int((profile.get("portfolio", {}) or {}).get("min_history_bars", 720))
    return AlphaModel.from_registry(registry, portfolio_params(profile), interval, min_history_bars=min_history)


def read_universe(root: str | Path) -> list[str]:
    path = Path(root) / UNIVERSE_STATE
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(symbol) for symbol in payload.get("symbols", [])]


def write_universe(root: str | Path, symbols: Sequence[str], meta: Mapping[str, Any] | None = None) -> Path:
    path = Path(root) / UNIVERSE_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"symbols": list(symbols), **dict(meta or {})}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
