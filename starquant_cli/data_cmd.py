"""``starquant data ...`` commands."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import click
import pandas as pd

from starquant_cli import data
from starquant_data.alignment import verify_spot_contract, write_spot_verification
from starquant_data.archive import ArchiveClient, Month
from starquant_data.binance_public import AsyncPublicClient, PublicClient
from starquant_data.metrics_archive import MetricsArchiveClient, sync_metrics
from starquant_data.pool import (
    MEMBERSHIP_ALERT_DAYS,
    MEMBERSHIP_FILE,
    LivePool,
    daily_quote_volume,
    membership_lag,
    membership_summary,
    point_in_time_membership,
    sync_daily,
)
from starquant_data.repair import (
    CONFIRMED_GAPS_FILE,
    FUNDING,
    Gap,
    find_gaps,
    plan,
    read_confirmed,
    record_confirmed,
    repair,
    utc,
    venue_sources,
)
from starquant_data.spot import (
    ALWAYS_MAPPED,
    SPOT_MARKET,
    SpotClient,
    SpotMapping,
    map_universe,
    measure_alignment,
    write_spot_map,
)
from starquant_data.store import (
    SPOT_KLINE_KIND,
    FundingStore,
    KlineStore,
    MetricsStore,
    interval_ms,
    write_parquet_atomically,
)
from starquant_data.sync import sync_funding, sync_klines
from starquant_data.universe import UniverseConfig, eligible_symbols
from starquant_live.composition import UNIVERSE_STATE, read_universe, write_universe
from starquant_shared.binance_rules import parse_exchange_info
from starquant_shared.config import load_yaml


def _pool_and_leavers(root: str) -> list[str]:
    """The pool in `universe.json`, and the names its last refresh dropped (2026-09-23).

    The 24h top 2N alone missed names the loop was trading.  The pool ranks 30-day volume with
    hysteresis, so a member can sit below that cut for weeks; `LivePool.select` keeps `previous` among
    its candidates for exactly this.  LSKUSDT's bars stopped at 2026-09-18T16:00Z while it was still
    in the pool.  CYSUSDT and TUTUSDT lost twelve days before they left on 09-16.  All three fell out
    of `report beta`'s basket and M-Q08's turnover replay.  The leavers ride along one more day so the
    bars of their exit are stored too.  An unreadable file costs only this addition: `pool refresh`
    reads the same file next in `run_data.sh` and fails loudly there.
    """
    try:
        payload = json.loads((Path(root) / UNIVERSE_STATE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        click.echo(f"    ! {UNIVERSE_STATE} unreadable, pool names not added: {error}")
        return []
    return list(dict.fromkeys(str(s) for s in [*payload.get("symbols", []), *payload.get("left", [])]))


@data.command("sync")
@click.option("--universe", "universe_path", default="config/universe.yaml", show_default=True)
@click.option("--root", default=".starquant/data", show_default=True, help="parquet store root")
@click.option("--symbols", default="", help="comma-separated override of the candidate set")
@click.option("--start", default=None, help="first archive month YYYY-MM (default from universe.yaml)")
@click.option("--market-url", default="https://fapi.binance.com", show_default=True)
@click.option("--funding/--no-funding", default=True, show_default=True)
@click.option("--candidates", default=0, help="number of volume-ranked candidates to download (default 2*top_n)")
def data_sync(
    universe_path: str, root: str, symbols: str, start: str | None, market_url: str, funding: bool, candidates: int
) -> None:
    """Download/refresh mainnet public klines + funding for the universe candidates, then select the universe."""
    config = UniverseConfig.from_mapping(load_yaml(universe_path))
    history_start = Month.parse(start or config.history_start)
    store = KlineStore(root)
    funding_store = FundingStore(root)
    with PublicClient(market_url) as public, ArchiveClient() as archive:
        now_ms = public.server_time_ms()
        rules = parse_exchange_info(public.exchange_info())
        eligible = set(eligible_symbols(rules, config))
        volume_24h = {str(row["symbol"]): float(row.get("quoteVolume", 0.0)) for row in public.ticker_24h()}
        if symbols:
            candidate_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            ranked = sorted((s for s in eligible if s in volume_24h), key=lambda s: -volume_24h[s])
            limit = candidates or 2 * config.top_n
            pool = _pool_and_leavers(root)
            candidate_list = list(dict.fromkeys([*config.always_include, *pool, *ranked[:limit]]))
            outside = [s for s in pool if s not in ranked[:limit] and s not in config.always_include]
            click.echo(f"pool names outside the 24h top {limit}: {', '.join(outside) or '-'}")
        click.echo(f"candidates: {len(candidate_list)} symbols from {history_start} (root={root})")
        reports = []
        for index, symbol in enumerate(candidate_list, start=1):
            started = time.monotonic()
            report = sync_klines(
                symbol,
                config.interval,
                history_start=history_start,
                store=store,
                archive=archive,
                public=public,
                now_ms=now_ms,
            )
            if funding:
                sync_funding(
                    symbol,
                    history_start=history_start,
                    store=funding_store,
                    public=public,
                    now_ms=now_ms,
                    report=report,
                )
            reports.append(report)
            status = "OK" if not report.errors else f"ERRORS={len(report.errors)}"
            click.echo(
                f"[{index}/{len(candidate_list)}] {symbol}: rows={report.total_rows} archive_months={report.archive_months} "
                f"rest_rows={report.rest_rows} funding={report.funding_rows} {status} ({time.monotonic() - started:.1f}s)"
            )
            for error in report.errors:
                click.echo(f"    ! {error}")
    # Downloading is this command's whole job.  It used to rank the store's 1h volume and write
    # `universe.json` as well, which gave the file two meanings depending on which command ran last:
    # on 2026-09-04 it held PUMPUSDT from a manual sync while the loop traded CYSUSDT from its own
    # daily refresh, and research reads this file as "the universe".  One writer, one ranking rule.
    click.echo("selection unchanged: `starquant data pool refresh` re-ranks and writes universe.json (D-014)")


@data.command("metrics")
@click.option("--root", default=".starquant/data", show_default=True, help="parquet store root")
@click.option("--symbols", required=True, help="comma-separated symbols to ingest")
@click.option("--from", "start", required=True, help="first day YYYY-MM-DD")
@click.option("--to", "end", required=True, help="last day YYYY-MM-DD, exclusive")
@click.option(
    "--workers",
    default=8,
    show_default=True,
    help=(
        "Fetch this many SYMBOLS at once.  Measured per symbol-day: 0.06s of CPU against 0.58s of "
        "waiting, so this is the axis with the headroom.  Writes stay on one thread."
    ),
)
def data_metrics(root: str, symbols: str, start: str, end: str, workers: int) -> None:
    """Ingest the daily futures-metrics archive (DL-D2), resuming from what the store already holds.

    Research-side only, and deliberately so: live can read metrics from the 30-day REST window and
    nothing else, so a strategy that declares `needs_metrics` is refused at startup until a live
    source can answer for it (`metrics_refusal`).  Ingesting without that gate would be KILL-027 in
    its purest form - a research panel strictly larger than the live one, arriving silently.

    Measured 2026-09-07: 0.69s per symbol-day sequentially.  That number is a LOWER BOUND and was
    measured on a nearly empty store: until 2026-09-09 this function appended once per day, and
    ``MetricsStore.append`` rewrites the symbol's whole parquet, so the real cost grew with the days
    already held - a 2,077-day symbol wrote about 621 million rows to store 598 thousand.  It now
    gathers a symbol's days and appends once, and ``--workers`` fetches several symbols at a time.
    """
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    store = MetricsStore(root)
    before = {s: store.last_open_time(s) for s in wanted}

    def progress(symbol: str, done: int, total: int) -> None:
        click.echo(f"[{done}/{total}] {symbol}", err=True)

    with MetricsArchiveClient() as client:
        totals = sync_metrics(client, store, wanted, start=start, end=end, workers=workers, progress=progress)
    for symbol in wanted:
        after = store.last_open_time(symbol)
        rows = totals.get(symbol)
        if after is None:
            click.echo(f"{symbol}: nothing stored (the archive published no day in [{start}, {end}))")
            continue
        stamp = datetime.fromtimestamp(after / 1000, tz=UTC).isoformat()
        moved = "unchanged" if before[symbol] == after else f"advanced to {stamp}"
        click.echo(f"{symbol}: {rows if rows is not None else store.load(symbol).shape[0]} rows stored, {moved}")


def _record_spot_contract(
    mappings: Mapping[str, SpotMapping],
    *,
    root: str,
    interval: str,
    now_ms: int,
    archive: ArchiveClient,
    public: SpotClient,
) -> None:
    """RISK-G3's measurement for the spot feed, written where the live loop looks for it (DL-D5).

    ONE symbol and one complete month, not every symbol: the stamp convention is a property of the
    FEED, and 362 pairs of downloads would say the same thing 362 times at 362 times the cost.  Which
    symbol was measured goes into the file rather than being left to be guessed, and BTCUSDT is
    preferred when it is mapped for the reason `verify_stamp_offset` answers UNVERIFIABLE on a flat
    sample: the rival offsets have to be REFUTED, which takes a series that moves every bar, and the
    deepest book is the one that always does.

    The last COMPLETE month, because the current month's file does not exist yet - the archive is
    published monthly, so sampling `Month.of_ms(now)` would 404 on every run and the record would never
    be written at all.

    A failure here is reported and never raises.  The ingest above has already been paid for, and a run
    whose measurement could not be taken must leave the previous record alone rather than overwrite a
    real measurement with a network error.  That cannot open anything it should not: fail-closed lives
    at the READ side, where a root with no record refuses, so silence here only ever keeps a gate shut.
    """
    listed = sorted({mapping.spot for mapping in mappings.values() if mapping.spot is not None})
    if not listed:
        return
    symbol = "BTCUSDT" if "BTCUSDT" in listed else listed[0]
    month = Month.of_ms(Month.of_ms(now_ms).start_ms() - 1)
    try:
        archived = archive.fetch_month(symbol, interval, month, SPOT_MARKET)
        if archived is None or archived.empty:
            click.echo(f"spot contract: NOT MEASURED - the archive has no {symbol} {interval} for {month}")
            return
        sampled = public.klines_range(symbol, interval, month.start_ms(), month.end_ms())
        verification = verify_spot_contract(archived, sampled)
    except Exception as exc:
        click.echo(f"spot contract: NOT MEASURED - {type(exc).__name__}: {exc}")
        return
    path = write_spot_verification(
        root,
        verification,
        {
            "symbol": symbol,
            "interval": interval,
            "sample": str(month),
            "measured_at": datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat(),
            "measured_at_ms": now_ms,
        },
    )
    click.echo(f"spot contract: {verification.verdict} - {verification.reason} ({symbol} {month}) -> {path}")


@data.command("spot")
@click.option("--universe", "universe_path", default="config/universe.yaml", show_default=True)
@click.option("--root", default=".starquant/data", show_default=True, help="parquet store root")
@click.option("--symbols", default="", help="comma-separated perpetuals (default: every symbol the kline store holds)")
@click.option("--interval", default="1h", show_default=True)
@click.option("--start", default=None, help="first archive month YYYY-MM (default from universe.yaml)")
@click.option("--spot-url", default="https://api.binance.com", show_default=True)
def data_spot(universe_path: str, root: str, symbols: str, interval: str, start: str | None, spot_url: str) -> None:
    """Ingest SPOT klines for the perpetuals' spot legs and print the alignment contract (DL-D5).

    The mapping is resolved against the spot venue's own listing and written to ``spot_map.json``, so
    research and the live loop resolve a perpetual to the same spot symbol instead of each re-deriving
    it from the name - which gets 1000SATSUSDT and three others wrong, silently and by a factor of 1000.

    The alignment check runs every time rather than behind a flag.  T-D5-1 is a claim about two live
    series ("same grid, no offset, right multiplier"), and a claim that is only tested against fixtures
    is a claim about the fixtures; this is the one place both real series are on disk together.

    So is the OTHER check, and the two answer different questions about the same pair of markets.
    ``measure_alignment`` asks whether this perpetual is paired with the right spot symbol at the right
    unit - a per-symbol question about the mapping.  ``verify_spot_contract`` asks whether the spot
    feed's own two sources agree about what their timestamps MEAN - one question about the feed, which
    is RISK-G3's, and the one `starquant_live.engine.spot_refusal` holds a basis strategy to.  Both run
    here because this command is the only place that has the archive and REST open at once; the second
    lands in ``spot_alignment.json``, which is what turns a measurement into something the live loop
    can read.  Without it that gate is shut, correctly, and no candidate reading spot can ever trade.
    """
    config = UniverseConfig.from_mapping(load_yaml(universe_path))
    history_start = Month.parse(start or config.history_start)
    perp_store = KlineStore(root)
    spot_store = KlineStore(root, kind=SPOT_KLINE_KIND)
    held = perp_store.symbols(interval)
    # An explicit --symbols is taken as asked.  The default run is the daily job's, and it also maps the legs a
    # reading needs whatever the store holds (`ALWAYS_MAPPED`); an empty store still has nothing to map.
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()] or (
        sorted({*held, *ALWAYS_MAPPED}) if held else []
    )
    if not wanted:
        raise click.ClickException(f"no perpetuals to map: {perp_store.directory} holds no {interval} klines")
    with SpotClient(spot_url) as client, ArchiveClient() as archive:
        now_ms = client.server_time_ms()
        mappings = map_universe(wanted, client.listed_symbols())
        write_spot_map(root, mappings, {"measured_at_ms": now_ms, "interval": interval})
        absent = sorted(perp for perp, mapping in mappings.items() if not mapping.exists)
        click.echo(f"spot legs: {len(wanted) - len(absent)}/{len(wanted)} mapped, {len(absent)} with no spot listing")
        if absent:
            click.echo(f"  no spot leg: {', '.join(absent)}")
        for perp, mapping in sorted(mappings.items()):
            if mapping.spot is None:
                continue
            report = sync_klines(
                mapping.spot,
                interval,
                history_start=history_start,
                store=spot_store,
                archive=archive,
                public=client,
                now_ms=now_ms,
                market=SPOT_MARKET,
            )
            note = " NOT LISTED" if report.not_listed else ""
            scale = "" if mapping.multiplier == 1.0 else f" x{mapping.multiplier:g}"
            click.echo(f"{perp} -> {mapping.spot}{scale}: {report.total_rows} rows{note} {'; '.join(report.errors)}")
        _record_spot_contract(mappings, root=root, interval=interval, now_ms=now_ms, archive=archive, public=client)
    for perp, mapping in sorted(mappings.items()):
        if mapping.spot is None:
            continue
        try:
            # Either leg can be absent - a perpetual outside this root, or a spot symbol whose archive
            # published nothing and whose tail failed.  Saying which is missing beats ending the run on
            # a FileNotFoundError after every download has already been paid for.
            frames = (perp_store.load(perp, interval), spot_store.load(mapping.spot, interval))
        except FileNotFoundError as exc:
            click.echo(f"{perp}/{mapping.spot}: alignment not measured ({exc})")
            continue
        evidence = measure_alignment(*frames, mapping=mapping, interval_ms=interval_ms(interval))
        verdict = "OK" if evidence.aligned else f"REFUSED ({evidence.reason})"
        click.echo(
            f"{perp}/{mapping.spot}: overlap={evidence.overlap_bars} lag={evidence.best_lag_bars:+d} "
            f"median|log ratio|={evidence.median_abs_log_ratio:.5f} p95={evidence.p95_abs_log_ratio:.5f} {verdict}"
        )


@data.command("status")
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--interval", default="1h", show_default=True)
def data_status(root: str, interval: str) -> None:
    """Show stored symbols, row counts and last bar."""
    store = KlineStore(root)
    universe = read_universe(root)
    confirmed = read_confirmed(root)
    holes = known = 0
    for symbol in store.symbols(interval):
        last = store.last_open_time(symbol, interval)
        stamp = "" if last is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(last / 1000))
        flag = "*" if symbol in universe else " "
        # T-D01: a monthly archive plus a REST tail can leave a hole that a backtest reads as a jump.
        # One the sources were asked for and do not hold is a confirmed gap, counted once below.
        found = store.gaps(symbol, interval)
        gaps = [(a, b) for a, b in found if (f"klines/{interval}", symbol, a, b) not in confirmed]
        holes, known = holes + len(gaps), known + len(found) - len(gaps)
        note = (
            "" if not gaps else f"  GAPS={len(gaps)} first={time.strftime('%Y-%m-%d', time.gmtime(gaps[0][0] / 1000))}"
        )
        click.echo(f"{flag} {symbol:<12} rows={store.count(symbol, interval):>7} last={stamp} UTC{note}")
    click.echo(f"universe: {', '.join(universe) if universe else '<not selected>'}")
    click.echo(
        f"gaps: {holes} missing stretch(es) across {len(store.symbols(interval))} symbols; "
        f"{known} confirmed absent upstream ({CONFIRMED_GAPS_FILE}), not counted"
    )


def _hole(gap: Gap) -> str:
    """First and last missing bar for klines; the two settlements around the hole for funding."""
    if gap.dataset == FUNDING:
        return f"{utc(gap.after)} -> {utc(gap.before)}  ~{gap.missing} settlement(s)"
    step = interval_ms(gap.dataset.split("/", 1)[1])
    return f"{utc(gap.after + step)} .. {utc(gap.before - step)}  {gap.missing} bar(s)"


@data.command("repair")
@click.option("--root", default=".starquant/data", show_default=True, help="parquet store root")
@click.option("--interval", default="1h", show_default=True)
@click.option("--symbols", default="", help="comma-separated (default: every symbol either store holds)")
@click.option("--klines/--no-klines", default=True, show_default=True)
@click.option("--funding/--no-funding", default=True, show_default=True)
@click.option("--market-url", default="https://fapi.binance.com", show_default=True)
@click.option("--apply", "apply_", is_flag=True, help="fetch and write; without it nothing is fetched or written")
def data_repair(
    root: str, interval: str, symbols: str, klines: bool, funding: bool, market_url: str, apply_: bool
) -> None:
    """Ask the sources once for every hole in the stored klines and funding (9.4).

    A dry run unless --apply: it lists each hole with the daily archive files and REST calls it would
    make and an estimate of the bytes, and opens neither the network nor anything for writing.  --apply
    merges what the sources hold, only strictly inside a hole, and records what they do not hold in
    confirmed_gaps.json; holes recorded there are not asked for again.  Nothing is interpolated or
    filled.  Not while `data sync` runs (17:20Z): both rewrite the same parquet files.
    """
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None
    confirmed = read_confirmed(root)
    found = find_gaps(root, interval, wanted, klines=klines, funding=funding)
    todo = [gap for gap in found if gap.key not in confirmed]
    plans = [plan(gap) for gap in todo]
    for fetch in plans:
        rest = f"{fetch.rest_calls} REST call(s)"
        cost = f"{len(fetch.days)} archive day file(s), {rest}" if fetch.days else rest
        click.echo(f"{fetch.gap.dataset:<9} {fetch.gap.symbol:<14} {_hole(fetch.gap)}: {cost}")
    for dataset in sorted({gap.dataset for gap in found}):
        mine = [gap for gap in todo if gap.dataset == dataset]
        click.echo(
            f"{dataset}: {len(mine)} hole(s), {sum(g.missing for g in mine)} missing, "
            f"{len({g.symbol for g in mine})} symbol(s); already confirmed, not asked: "
            f"{sum(1 for gap in found if gap.dataset == dataset) - len(mine)}"
        )
    days = sum(len(fetch.days) for fetch in plans)
    click.echo(
        f"fetch: {days} archive day file(s) (+{days} CHECKSUM), up to {sum(f.rest_calls for f in plans)} REST "
        f"call(s), about {sum(f.est_bytes for f in plans) / 1e6:.2f} MB"
    )
    if not apply_ or not todo:
        click.echo("dry run: nothing fetched, nothing written (--apply does both)" if todo else "nothing to ask for")
        return
    with PublicClient(market_url) as public, ArchiveClient() as archive:
        now_ms = public.server_time_ms()
        sources = venue_sources(archive, public)
        outcomes = []
        for gap in todo:
            outcome = repair(gap, root=root, sources=sources, now_ms=now_ms)
            outcomes.append(outcome)
            answers = "; ".join(f"{source}: {answer}" for source, answer in outcome.answers.items())
            status = (
                f"ERRORS: {' | '.join(outcome.errors)}" if outcome.errors else f"confirmed {len(outcome.confirmed)}"
            )
            click.echo(f"{gap.dataset:<9} {gap.symbol:<14} +{outcome.added} row(s), {status} ({answers})")
    path, new = record_confirmed(root, outcomes, now_ms)
    failed = sum(1 for outcome in outcomes if outcome.errors)
    click.echo(
        f"repaired {sum(o.added for o in outcomes)} row(s); {new} newly confirmed -> {path}; "
        f"{failed} hole(s) with errors, not recorded (run again)"
    )


@data.group("pool")
def data_pool() -> None:
    """Trading pool: live refresh with hysteresis, and the point-in-time membership table for research."""


@data_pool.command("refresh")
@click.option("--universe", "universe_path", default="config/universe.yaml", show_default=True)
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--market-url", default="https://fapi.binance.com", show_default=True, help="volumes (mainnet)")
@click.option(
    "--venue-url", default="https://demo-fapi.binance.com", show_default=True, help="exchangeInfo for tradability"
)
@click.option("--candidates", default=45, show_default=True)
def pool_refresh(universe_path: str, root: str, market_url: str, venue_url: str, candidates: int) -> None:
    """Re-rank the live universe (30-day mainnet quote volume, enter/exit hysteresis) and write universe.json."""
    config = UniverseConfig.from_mapping(load_yaml(universe_path))
    with PublicClient(venue_url) as venue_public:
        rules = parse_exchange_info(venue_public.exchange_info())
    previous = read_universe(root)

    async def run() -> object:
        client = AsyncPublicClient(market_url)
        try:
            return await LivePool(client, config, candidates=candidates).select(previous, rules)
        finally:
            await client.aclose()

    update = asyncio.run(run())
    payload = update.to_dict()  # type: ignore[attr-defined]
    path = write_universe(
        root,
        payload["symbols"],
        {
            "selected_at_ms": payload["at_ms"],
            "entered": payload["entered"],
            "left": payload["left"],
            "volume_30d": payload["volumes"],
            "source": "pool-refresh",
        },
    )
    click.echo(f"universe ({len(payload['symbols'])}): {', '.join(payload['symbols'])}")
    click.echo(f"entered: {payload['entered'] or '-'}  left: {payload['left'] or '-'}")
    click.echo(f"written {path}")


@data_pool.command("history")
@click.option("--universe", "universe_path", default="config/universe.yaml", show_default=True)
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--market-url", default="https://fapi.binance.com", show_default=True)
@click.option("--start", default=None, help="first month YYYY-MM (default from universe.yaml)")
@click.option(
    "--refresh",
    default="D",
    show_default=True,
    # D since 2026-09-23: research adopted the daily table on 2026-09-04, and `pool lag` flags a monthly one.
    help="pandas offset alias of the re-selection dates (MS = the monthly table research dropped)",
)
@click.option("--sync/--no-sync", default=True, show_default=True, help="refresh daily klines for every candidate")
@click.option(
    "--sync-members/--no-sync-members",
    default=False,
    show_default=True,
    help="also download hourly klines + funding for every symbol that was ever a member",
)
@click.option(
    "--always-include",
    default="BTCUSDT,ETHUSDT",
    show_default=True,
    help="pins for the historical selection (never import today's preferences into 2021)",
)
def pool_history(
    universe_path: str,
    root: str,
    market_url: str,
    start: str | None,
    refresh: str,
    sync: bool,
    sync_members: bool,
    always_include: str,
) -> None:
    """Rebuild point-in-time membership from daily quote volume of every USDT perpetual that ever had an archive."""
    click.echo(f"注意：{_REBUILD_BLOCKS}")  # before the long sync, while Ctrl-C still costs nothing
    base = UniverseConfig.from_mapping(load_yaml(universe_path))
    pins = tuple(s.strip().upper() for s in always_include.split(",") if s.strip())
    config = replace(base, always_include=pins)
    history_start = Month.parse(start or config.history_start)
    store = KlineStore(root)
    with PublicClient(market_url) as public, ArchiveClient() as archive:
        now_ms = public.server_time_ms()
        rules = parse_exchange_info(public.exchange_info())
        listed = {symbol for symbol, rule in rules.items() if rule.quote_asset == config.quote_asset}
        archived = {s for s in archive.list_symbols() if s.endswith(config.quote_asset)}
        candidates = sorted(listed | archived)
        click.echo(f"candidates: {len(candidates)} ({len(listed)} listed, {len(archived - listed)} archive-only)")
        if sync:
            started = time.monotonic()
            errors = 0
            for index, symbol in enumerate(candidates, start=1):
                report = sync_daily(
                    symbol,
                    store=store,
                    public=public,
                    archive=archive,
                    now_ms=now_ms,
                    start_ms=history_start.start_ms(),
                    listed=symbol in listed,
                )
                if report.error:
                    errors += 1
                    click.echo(f"    ! {symbol}: {report.error}")
                if index % 50 == 0:
                    click.echo(f"  daily sync {index}/{len(candidates)} ({time.monotonic() - started:.0f}s)")
            click.echo(f"daily sync done: {len(candidates)} symbols, {errors} errors")
        # Delisted names pass unconditionally (`s not in rules`), which is what keeps the point-in-time
        # universe survivorship-free.  The residual look-ahead, named because it is small rather than
        # absent (2026-09-08 audit): a symbol the venue still lists is filtered by TODAY's contract type
        # and min-notional over its WHOLE history, so one whose min-notional was raised recently is
        # excluded from years in which it qualified.  Binance changes these rarely and the direction is
        # not systematic; recorded rather than fixed, since a point-in-time exchangeInfo archive does
        # not exist to fix it with.
        eligible = {
            s
            for s in candidates
            if s not in rules
            or (
                rules[s].contract_type == "PERPETUAL"
                and rules[s].quote_asset == config.quote_asset
                and (float(rules[s].min_notional) <= config.max_min_notional_usdt or s in pins)
            )
        }
        eligible -= set(config.exclude)
        volume = daily_quote_volume(store, candidates)
        if volume.empty:
            raise click.ClickException("no daily klines stored; run with --sync")
        volume = volume.loc[pd.Timestamp(history_start.start_ms(), unit="ms", tz="UTC") :]
        membership = point_in_time_membership(volume, config, eligible=eligible, refresh=refresh)
        table_path = Path(root) / MEMBERSHIP_FILE
        # Atomic since 2026-09-23: the hourly `pool lag --check` reads this file, and an in-place write
        # let it catch half a table.  `index=None` keeps the dates exactly as the plain `to_parquet` did.
        write_parquet_atomically(membership, table_path, index=None)
        summary = membership_summary(membership)
        summary["coverage"] = {
            "symbols_with_daily_data": int(volume.notna().any(axis=0).sum()),
            "symbol_days": int(volume.notna().sum().sum()),
            "eligible": len(eligible),
        }
        summary_tmp = Path(root) / "membership.json.tmp"
        summary_tmp.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")
        summary_tmp.replace(Path(root) / "membership.json")
        click.echo(
            f"membership: {summary['refreshes']} refreshes {summary['first']} -> {summary['last']}, "
            f"mean size {summary['mean_size']:.1f}, {summary['changes_per_refresh']:.2f} changes/refresh, "
            f"union {len(summary['union'])} symbols"
        )
        by_year = membership.groupby(pd.DatetimeIndex(membership.index).year).apply(
            lambda block: sorted(block.columns[block.any()])
        )
        for year, members in by_year.items():
            click.echo(f"  {year}: {len(members)} distinct members")
        click.echo(f"written {table_path}")
        if sync_members:
            funding_store = FundingStore(root)
            members = list(summary["union"])
            for index, symbol in enumerate(members, start=1):
                member = sync_klines(
                    symbol,
                    config.interval,
                    history_start=history_start,
                    store=store,
                    archive=archive,
                    public=public,
                    now_ms=now_ms,
                )
                sync_funding(
                    symbol,
                    history_start=history_start,
                    store=funding_store,
                    public=public,
                    now_ms=now_ms,
                    report=member,
                )
                status = "OK" if not member.errors else f"ERRORS={len(member.errors)}"
                click.echo(
                    f"[{index}/{len(members)}] {symbol}: rows={member.total_rows} funding={member.funding_rows} {status}"
                )


# Every reason whose fix is a rebuild carries this, or the alert talks the operator into 2026-09-18
# again: that rebuild moved a blocking manifest field and the armed start was saved only by D-041.
# `pool history` prints the gate half itself before it starts (2026-09-23).
_REBUILD_BLOCKS = (
    "重建会改动 manifest 的 membership 字段，armed 启动随即被数据集门挡住（registry_dataset_problems）。"
    "所以重建要和证据重出排在一起，不要单独重建。"
)
_REBUILD = f"重建命令：starquant data pool history --refresh D（日表；MS 是 09-04 弃用的月表）。{_REBUILD_BLOCKS}"


def _lag_line(path: Path, today: pd.Timestamp, alert_days: int) -> tuple[bool, str]:
    """(fresh, one line for the operator).  Missing, unreadable, empty, monthly and future all read NOT fresh."""
    if not path.exists():
        return False, f"时点成员表不存在（{path}），说不出落后多少天，不能当作新鲜。{_REBUILD}"
    try:
        lag = membership_lag(pd.read_parquet(path), today, alert_days=alert_days)
    except Exception as exc:  # a table nobody can read is a finding, never a pass
        error = " ".join(f"{type(exc).__name__}: {exc}".split())  # one line: the page is `tail -n 3`
        return False, f"时点成员表读不了（{error}），不能当作新鲜。{_REBUILD}"
    last = "-" if lag.last is None else lag.last.strftime("%Y-%m-%d")
    where = f"末行 {last}，今天 {today.strftime('%Y-%m-%d')} UTC"
    if lag.status == "OK":
        return True, f"时点成员表落后 {lag.lag_days} 天（告警线 {alert_days} 天；{where}）"
    if lag.status == "STALE":
        return False, f"时点成员表落后 {lag.lag_days} 天（告警线 {alert_days} 天；{where}）。{_REBUILD}"
    if lag.status == "NOT_DAILY":
        return False, f"时点成员表不是日表：相邻两行中位相隔 {lag.gap_days:g} 天（{where}）。{_REBUILD}"
    if lag.status == "AHEAD":
        return False, f"时点成员表的末行晚于今天（{where}）：本机时钟或这张表有一个不对，落后天数不可信。"
    return False, f"时点成员表是空的（{path}），说不出落后多少天，不能当作新鲜。{_REBUILD}"


@data_pool.command("lag")
@click.option("--root", default=".starquant/data", show_default=True)
@click.option("--date", "day", default=None, help="YYYY-MM-DD to measure against (default: today UTC)")
@click.option("--alert-days", default=MEMBERSHIP_ALERT_DAYS, show_default=True, help="days of lag that alert")
@click.option("--check", is_flag=True, help="exit non-zero unless the table is readable, daily and under the line")
def pool_lag(root: str, day: str | None, alert_days: int, check: bool) -> None:
    """How many days the point-in-time table trails today (G10: it is rebuilt by hand, never on a schedule).

    One line either way, so the hourly check can paste it.  Why 14 days, and why the base is the
    calendar rather than the archive, is written at ``MEMBERSHIP_ALERT_DAYS``.
    """
    today = pd.Timestamp(day, tz="UTC") if day else pd.Timestamp.now(tz="UTC")
    fresh, line = _lag_line(Path(root) / MEMBERSHIP_FILE, today, alert_days)
    if check and not fresh:
        raise click.ClickException(line)
    click.echo(line)


__all__ = ["data_repair", "data_status", "data_sync", "pool_history", "pool_lag", "pool_refresh"]
