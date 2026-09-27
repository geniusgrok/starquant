"""Profile YAML -> LiveConfig + runtime objects (the only place that knows about concrete classes)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from starquant_alpha.model import AlphaModel
from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.overlays.exposure import DrawdownThrottleParams
from starquant_alpha.panel import interval_seconds
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import Registry, evidence_problems
from starquant_alpha.signals import get_signal
from starquant_data.live_feed import PublicMarketData
from starquant_data.manifest import ManifestCheck, build_manifest, manifest_check
from starquant_data.pool import LivePool
from starquant_data.universe import UniverseConfig
from starquant_exchange.binance_usdm.rest_client import BinanceRestClient
from starquant_exchange.binance_usdm.venue import BinanceUsdmVenue
from starquant_exchange.guard import WriteGuard
from starquant_live.composition import build_model, load_registry, portfolio_params, read_universe, write_universe
from starquant_live.engine import LiveConfig
from starquant_live.guards import GuardParams
from starquant_live.lock import account_kill_switch_path
from starquant_live.ports import UniverseUpdate
from starquant_live.probe import probes_from_registry
from starquant_live.rebalancer import RebalanceParams
from starquant_live.state import StateStore
from starquant_shared.config import env_secret, load_yaml


def load_profile(path: str | Path) -> dict[str, Any]:
    return load_yaml(path)


def resolve_universe(
    profile: dict[str, Any],
    override: Sequence[str] | None = None,
    data_root: str | Path = ".starquant/data",
    registry: Registry | None = None,
) -> list[str]:
    """`--symbols`, then the registry's pinned universe, then whatever the pool last ranked.

    The registry comes SECOND, above `universe.json`, because a pinned universe is a decision and the
    file is an observation.  Before 2026-09-09 the file was the decision, and that is what made a
    cited report stop describing the traded population every day at about 01:00Z.
    """
    if override:
        return [symbol.upper() for symbol in override]
    if registry is not None and registry.universe:
        return list(registry.universe)
    selected = read_universe(data_root)
    if selected:
        return selected
    universe_cfg = load_yaml(profile.get("universe", "config/universe.yaml"))
    return [str(symbol) for symbol in universe_cfg.get("always_include", [])]


def account_kill_switches(profile: dict[str, Any]) -> tuple[Path, ...]:
    """The account-scoped kill switch, when the profile names an API key env var (L1-07).

    Empty when the credential is not available - paper and offline runs have no account to scope to,
    and an absent switch is correctly "not engaged" rather than an error.
    """
    venue = profile.get("venue", {}) or {}
    name = str(venue.get("api_key_env", ""))
    key = os.environ.get(name, "") if name else ""
    return (account_kill_switch_path(key),) if key else ()


def live_config(profile: dict[str, Any], universe: Sequence[str], registry: Registry, *, dry_run: bool) -> LiveConfig:
    portfolio = profile.get("portfolio", {}) or {}
    guards = profile.get("guards", {}) or {}
    market = profile.get("market_data", {}) or {}
    pool = profile.get("pool", {}) or {}
    interval = str(market.get("interval", "1h"))
    leverage_raw = portfolio.get("leverage", 2)
    leverage_mode = "auto" if str(leverage_raw).lower() == "auto" else "fixed"
    bars_per_day = max(1, 86_400 // interval_seconds(interval))
    exits = ExitParams.from_mapping({**(profile.get("exits", {}) or {}), "bars_per_day": bars_per_day})
    throttle = DrawdownThrottleParams.from_mapping(profile.get("drawdown_throttle", {}) or {})
    return LiveConfig(
        interval=interval,
        history_bars=int(market.get("history_bars", 400)),
        universe=tuple(universe),
        leverage=2 if leverage_mode == "auto" else int(leverage_raw),
        rebalance=RebalanceParams(
            no_trade_band=float(portfolio.get("no_trade_band", 0.005)),
            no_trade_rel_band=float(portfolio.get("no_trade_rel_band", 0.0)),
            max_order_notional=(
                float(portfolio["max_order_notional"]) if portfolio.get("max_order_notional") else None
            ),
            max_participation=float(portfolio.get("max_participation", 0.0)),
            # T-S03's cap was documented as being about a RISK-ADDING order, and it exempted only a
            # full close - so a 15% position being cut to 5% was throttled by the same liquidity that
            # was drying up.  Off by default, which is today's behaviour bit for bit; the backtest
            # replay carries the same field and the two have to be flipped together (KILL-027).
            exempt_reductions=bool(portfolio.get("exempt_reductions", False)),
            # Both read the same `portfolio` block the backtest's `PortfolioParams.from_mapping` reads,
            # so `flat_inside_band` and `band_entry_multiple` reach the two halves from one key each and
            # cannot be half-flipped.
            exempt_crossings=bool(portfolio.get("exempt_crossings", False)),
            flat_inside_band=bool(portfolio.get("flat_inside_band", False)),
            band_entry_multiple=float(portfolio.get("band_entry_multiple", 1.0)),
        ),
        guards=GuardParams(
            daily_loss_pause=float(guards.get("daily_loss_pause", -0.05)),
            stale_bars_max=int(guards.get("stale_bars_max", 2)),
            max_gross=float(portfolio.get("max_gross", 2.0)),
            max_weight=float(portfolio.get("max_weight", 0.15)),
        ),
        # L1-07: absolute, always.  A relative default resolves against the working directory, so a
        # CLI run from a worktree engaged a switch the loop could not see - the same two-processes,
        # two-directories, one-account shape as DL-L1.
        kill_switch_path=Path(guards.get("kill_switch_path", ".starquant/live/KILL_SWITCH")).resolve(),
        # L1-07: and the one that does not move when the working directory does.
        kill_switch_paths=account_kill_switches(profile),
        # a book's fraction enters attribution here; contributions stay unscaled targets (D-019)
        strategy_weights={entry.id: entry.weight * registry.fraction(entry.book) for entry in registry.enabled},
        dry_run=dry_run,
        exits=exits,
        throttle=throttle,
        leverage_mode=leverage_mode,
        margin_cap=float(portfolio.get("margin_cap", 0.40)),
        max_leverage=int(portfolio.get("max_leverage", 5)),
        dropped_after=int(pool.get("dropped_after", 1)),
        margin_buffer=float(portfolio.get("margin_buffer", 0.10)),
        universe_refresh=str(pool.get("refresh", "never")).lower() != "never",
        liquidity_window=int(pool.get("liquidity_window", 24)),
        quarantine_after=int(pool.get("quarantine_after", 0)),
        probes=probes_from_registry(registry),
        max_bar_alignment_ms=int(float(guards.get("max_bar_alignment_seconds", 60.0)) * 1000),
        # the same mapping the model reads, so the digest describes the book that actually ran
        portfolio=PortfolioParams.from_mapping(portfolio),
        # The same key `composition.build_model` reads, so the fingerprint cannot describe a different
        # eligibility rule from the one the model applies; a test holds the two together.
        min_history_bars=int(portfolio.get("min_history_bars", 720)),
        # A pinned universe turns the daily re-rank into an observation; see `_refresh_universe`.
        universe_pinned=bool(registry.universe),
        # DL-X1: the collateral mode the live record was produced under, asserted at startup.  Not part
        # of `construction_fingerprint` on purpose - it describes the ACCOUNT, not the construction, so
        # adding it must not reset M-010's evidence window the way a weight change would.
        expect_multi_assets=bool((profile.get("venue", {}) or {}).get("multi_assets_margin", True)),
        min_liq_distance=float((profile.get("risk_budget", {}) or {}).get("min_liq_distance", 10.0)),
    )


def build_pool(profile: dict[str, Any], market: PublicMarketData) -> LivePool | None:
    """Daily universe refresh over the same public client as the market data feed (None when disabled)."""
    pool = profile.get("pool", {}) or {}
    if str(pool.get("refresh", "never")).lower() == "never":
        return None
    config = UniverseConfig.from_mapping(load_yaml(profile.get("universe", "config/universe.yaml")))
    return LivePool(market.client, config, candidates=int(pool.get("candidates", 0)))


def universe_sink(data_root: str | Path) -> Callable[[UniverseUpdate], None]:
    """Persist a refreshed selection to ``universe.json`` so restarts and research see the same pool."""

    def write(update: UniverseUpdate) -> None:
        payload = update.to_dict()
        write_universe(
            data_root,
            list(update.symbols),
            {
                "selected_at_ms": update.at_ms,
                "entered": list(update.entered),
                "left": list(update.left),
                "volume_30d": dict(payload.get("volumes", {}) or {}),
                "source": "live-refresh",
            },
        )

    return write


def live_overlay_blocks(profile: Mapping[str, Any]) -> dict[str, dict[str, Any] | None]:
    """The two post-model layers as the report records them, so the gate compares like with like.

    ``None`` means the loop applies no such layer, which is a different statement from "the report does
    not say" - `construction_problems` treats them differently and this is where the distinction is made.
    """
    bars_per_day = max(1, 86_400 // interval_seconds(str((profile.get("market_data") or {}).get("interval", "1h"))))
    exits = ExitParams.from_mapping({**(profile.get("exits") or {}), "bars_per_day": bars_per_day})
    portfolio = profile.get("portfolio") or {}
    return {
        "book_guards": {
            "max_weight": float(portfolio.get("max_weight", 0.15)),
            "max_gross": float(portfolio.get("max_gross", 2.0)),
            "daily_loss_pause": float((profile.get("guards") or {}).get("daily_loss_pause", -0.05)),
        },
        "exits": dict(vars(exits)) if exits.enabled else None,
    }


def registry_evidence_problems(registry: Registry, profile: dict[str, Any] | None = None) -> list[str]:
    """KILL-015 at startup: report exists, digest matches, params match, and the construction matches too.

    ``profile`` supplies the live portfolio construction so a band or half-life change cannot detach the
    book from its evidence unnoticed (D-026 records it; this refuses it).  Reports written before
    ``validate`` recorded its construction have no ``portfolio`` block and are skipped, so nothing in
    flight today is blocked.  A probe book (D-019) must also cite an ACCEPTed book report at the
    registry's fraction.
    """

    def sha256_of(path: str) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def read_report(path: str) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def canonical(strategy_id: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        return get_signal(strategy_id).canonical_params(params)

    live_portfolio = portfolio_params(profile).__dict__ if profile is not None else None
    live_overlays = live_overlay_blocks(profile) if profile is not None else None
    problems: list[str] = []
    for entry in registry.enabled:
        fraction = registry.books[entry.book].fraction if entry.book in registry.books else None
        problems.extend(
            evidence_problems(
                entry,
                exists=lambda p: Path(p).exists(),
                sha256_of=sha256_of,
                read_report=read_report,
                book_fraction=fraction,
                canonical_params=canonical,
                live_portfolio=live_portfolio,
                live_overlays=live_overlays,
            )
        )
    return problems


def registry_dataset_problems(
    registry: Registry, data_root: str | Path = ".starquant/data", interval: str = "1h"
) -> ManifestCheck:
    """D-041: check each enabled strategy's cited dataset manifest against the data on disk.

    ``validate`` has written a manifest into every report since D-024 and nothing ever read one back,
    so the stale-evidence pointer it exists to catch could not be caught.  This is the reader; the
    severity split it relies on is documented in :data:`starquant_data.manifest.BLOCKING_FIELDS`.

    A missing or unreadable report is left alone - ``registry_evidence_problems`` already reports it,
    and one fault should be named once.
    """
    current = build_manifest(data_root, interval)
    blocking: list[str] = []
    advisory: list[str] = []
    for entry in registry.enabled:
        path = Path(str((entry.evidence or {}).get("report", "")))
        if not str(path) or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        recorded = payload.get("dataset") if isinstance(payload, dict) else None
        mode = payload.get("universe_mode") if isinstance(payload, dict) else None
        check = manifest_check(
            recorded if isinstance(recorded, dict) else None,
            current,
            # D-041 + 2026-09-15: the report says which population it ran on, and only a `pit` one is
            # exempt from the universe field.  Read here rather than inside `manifest_check` because
            # this is the only caller that holds the whole report payload.
            universe_mode=mode if isinstance(mode, str) else None,
        )
        blocking.extend(f"{entry.id}: {message}" for message in check.blocking)
        advisory.extend(f"{entry.id}: {message}" for message in check.advisory)
    return ManifestCheck(blocking, advisory)


def build_model_from_profile(profile: dict[str, Any]) -> tuple[AlphaModel, Registry]:
    registry = load_registry(profile.get("registry", "config/alpha_registry.yaml"))
    return build_model(registry, profile), registry


def build_market_data(profile: dict[str, Any]) -> PublicMarketData:
    market = profile.get("market_data", {}) or {}
    return PublicMarketData(str(market.get("rest_url", "https://fapi.binance.com")))


def build_venue(profile: dict[str, Any], kill_switch_path: Path | Sequence[Path]) -> BinanceUsdmVenue:
    venue_cfg = profile.get("venue", {}) or {}
    rest_url = str(venue_cfg.get("rest_url", "https://demo-fapi.binance.com"))
    guard = WriteGuard(rest_url, kill_switch_path)
    client = BinanceRestClient(
        rest_url,
        env_secret(str(venue_cfg.get("api_key_env", "STARQUANT_DEMO_API_KEY"))),
        env_secret(str(venue_cfg.get("api_secret_env", "STARQUANT_DEMO_API_SECRET"))),
        guard=guard,
        recv_window_ms=int(venue_cfg.get("recv_window_ms", 10_000)),
    )
    return BinanceUsdmVenue(client)


def build_store(profile: dict[str, Any], *, dry_run: bool) -> StateStore:
    """The loop's state directory, with rehearsals sent somewhere else (L1-13).

    A dry run used to share `paths.state_dir` with the real loop, so rehearsing appended to the live
    `cycles.jsonl` and rewrote `heartbeat.json` and `state.json`.  `live status --check` reads that
    heartbeat to decide whether the loop is alive and the daily report counts those cycle rows, so a
    rehearsal could make a dead loop look fresh, or put bars into a metric meant to describe what the
    book actually did.

    The suffix is derived rather than configured: a separate key would have to be remembered exactly
    when someone is in a hurry, which is when rehearsals happen, and the live profile sets `state_dir`
    explicitly - so honouring an explicit setting would have kept the bug for the one profile anybody
    actually rehearses.
    """
    paths = profile.get("paths", {}) or {}
    return StateStore(store_directory(Path(paths.get("state_dir", ".starquant/live")), dry_run=dry_run))


def store_directory(directory: Path, *, dry_run: bool) -> Path:
    """Where a run with this flag actually writes, for everyone who has to find it afterwards.

    The suffix used to live only inside `build_store`, so every READER of a dry run's record had to
    know the rule by heart - and the canary's readers did not.  Measured 2026-09-12 when the L4 soak
    was started for the first time: `run_shadow.sh` passes `--state-dir .starquant/live-shadow`, the loop
    wrote `.starquant/live-shadow-dry-run`, and `governance canary` / `plan` / `apply` all default to
    `.starquant/live-shadow`.  The soak would have run its full 168 hours and every reader would have
    said "L4: no shadow record" the whole time - and AC-G5 would then have failed for a reason with
    nothing to do with the candidate.

    One definition, both sides.  A producer and a consumer that each name the same directory correctly
    on their own is this repository's most frequent defect; this is the 27th time it has been found.
    """
    return directory.with_name(directory.name + "-dry-run") if dry_run else directory
