"""``starquant live ...`` and ``starquant report ...`` commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import httpx

from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.panel import interval_seconds
from starquant_alpha.registry import Registry
from starquant_alpha.validation.ledger import MINED_SEARCH_STRATEGY, parse_ledger, resolve_ledger_path
from starquant_cli import live, report
from starquant_data.alignment import read_spot_verification
from starquant_data.binance_public import DEFAULT_BASE_URL, PublicClient
from starquant_data.store import MetricsStore, interval_ms
from starquant_governance.policy import policy_digest
from starquant_live.alerts import HOURLY_CALLER_WINDOW_SECONDS, WebhookAlerts
from starquant_live.benchmark import beta_reading
from starquant_live.composition import build_model, load_registry, portfolio_params
from starquant_live.config import (
    account_kill_switches,
    build_market_data,
    build_model_from_profile,
    build_pool,
    build_store,
    build_venue,
    live_config,
    load_profile,
    registry_dataset_problems,
    registry_evidence_problems,
    resolve_universe,
    universe_sink,
)
from starquant_live.engine import (
    BreakerTripped,
    LiveEngine,
    StopRequested,
    engage_kill_switches,
    registry_digest,
    release_kill_switches,
)
from starquant_live.execution_fidelity import ReplayInputs
from starquant_live.factor_loadings import archive_funding, archive_history, factor_reading
from starquant_live.health import STUCK_IN_ERROR_STREAK, cycle_health
from starquant_live.inputs import required_history
from starquant_live.lock import APP_SUPPORT, LockBusy, SingleInstanceLock, account_lock_path
from starquant_live.paper import PaperVenue
from starquant_live.probe import probes_from_registry
from starquant_live.report_beta import factor_markdown
from starquant_live.reports import (
    PREREGISTRATION_EFFECTIVE_FROM,
    _store_closes,
    beta_markdown,
    daily_alerts,
    daily_markdown,
    daily_payload,
    expectations_from_evidence,
    latest_risk_adaptation,
    preregistration_problems,
    preregistration_skipped,
    risk_adaptation_headline,
    weekly_markdown,
    weekly_payload,
)
from starquant_live.risk_budget import RiskBudgetParams
from starquant_live.scheduler import SystemClock
from starquant_live.staleness import RULES, rules_binding
from starquant_live.state import LiveState, StateStore, StateUnreadable
from starquant_live.verify import (
    cycle_clock,
    fetch_lag_seconds,
    last_cycle,
    last_recorded_as_of_ms,
    last_recorded_governance_digest,
    last_recorded_registry_digest,
    last_scored_cycle,
    verify_live_targets,
)
from starquant_shared.config import env_secret


def _paper_state_dir(payload: Mapping[str, Any], state_dir: str) -> Path:
    """`--state-dir` verbatim when given, the profile's sibling `paper` directory when not.

    The second branch is the historical behaviour and `with_name` is what makes the paper directory a
    SIBLING of the live one rather than a child.  Applied to an explicit `--state-dir` it silently
    threw the flag away - `--paper --state-dir .starquant/live-shadow` wrote to `.starquant/paper` - so a
    flag whose entire purpose is isolation delivered none, and two paper canaries would have collided
    on one `state.json` without either of them saying so.
    """
    if state_dir:
        return Path(state_dir)
    return Path((payload.get("paths", {}) or {}).get("state_dir", ".starquant/live")).with_name("paper")


def clock_skew_seconds(rest_url: str) -> float | None:
    """Venue server time minus this host's clock, in seconds; ``None`` when the venue cannot be reached.

    A drifting host clock does not stop the loop (the REST client measures its own offset for signing, and
    the staleness guard is one-directional), but every timestamp the loop writes - the cycle `bar`, the
    heartbeat `at`, the UTC-day boundary that triggers the pool refresh - comes from this clock.
    """
    try:
        with PublicClient(rest_url, timeout=10.0, max_retries=1) as public:
            before = time.time()
            server = public.server_time_ms()
            after = time.time()
    except Exception:
        return None
    return (server - (before + after) / 2 * 1000) / 1000.0


def _paper_venue(market_url: str, balance: float, state_path: Path) -> PaperVenue:
    """Paper venue with mainnet trading rules (public exchangeInfo) and persistent simulated positions."""
    with PublicClient(market_url) as public:
        payload = public.exchange_info()
    return PaperVenue.from_exchange_info(payload, balance=balance, state_path=state_path)


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not verbose:
        # one line per request (14 kline pulls a cycle) is noise in an unattended log; errors still surface
        logging.getLogger("httpx").setLevel(logging.WARNING)


def trades_the_account(*, dry_run: bool, paper: bool, state_dir: str, registry_override: str | None) -> bool:
    """DL-G5: is this the process trading the account?  Only that one may write the shared records.

    Two of them, found one at a time and the same shape both times.

    `universe.json` lives under the DATA root, which neither `--state-dir` nor `--paper` isolates, and
    every enabled strategy's cited evidence records the universe fingerprint it was produced under.
    Refreshing it therefore invalidates the ARMED loop's evidence, and `registry_dataset_problems`
    then refuses its next start.

    Measured on 2026-09-08: a shadow started at 18:00Z re-ranked the pool, the fingerprint moved
    d47dbc7c -> 788ade10, and an armed restart went from clean to blocked.  The armed loop refreshes
    daily at about 01:00Z on its own, so restartability was going to expire that night anyway - the
    shadow brought it forward by seven hours, which is the whole harm and is also exactly enough to
    matter during an incident.

    The first version of this guard named `--state-dir` and `--registry`, because a canary was what
    had just done it.  A bare `--paper` was not covered and did it again at 18:00Z the same day,
    swapping CYSUSDT -> PUMPUSDT in the shared file; the universe pin proposed the next morning was
    built from that file and named a symbol the armed loop had never held.  The condition was never
    the flag - it is whether this process is the one trading the account.

    A shadow wants the universe the armed loop is holding, not a fresh opinion about it, so this is
    what the check is FOR rather than a limitation of it.  `--symbols` is how a person says otherwise,
    deliberately and in the shell history.

    The SECOND record is `metrics_snapshot`, found 2026-09-09 while about to start the L3 paper soak.
    `MetricsStore.append` is read-modify-write through one `.parquet.tmp` per symbol, so two writers
    do not merely lose rows - they can publish a file one of them was still writing.  And DL-Q6 says
    that store is "the metrics the loop could read", meaning the ARMED loop: a paper process adding
    rows to it makes the parity check (M-011) compare the live decision against data no live decision
    was made on.  A shadow still READS it - coverage gating needs that the moment a metrics-using
    strategy is enabled - it just does not write.
    """
    return not (dry_run or paper or state_dir or registry_override)


def kill_switch_path(payload: dict[str, Any]) -> Path:
    """The configured kill switch, resolved.

    One helper so this module and ``live_config`` cannot disagree inside one process.  It does NOT
    make the path stable across working directories - `.resolve()` anchors a relative path to
    `os.getcwd()` - which is what `kill_switch_targets` is for.
    """
    guards = payload.get("guards", {}) or {}
    return Path(str(guards.get("kill_switch_path", ".starquant/live/KILL_SWITCH"))).resolve()


def kill_switch_targets(payload: dict[str, Any]) -> tuple[Path, ...]:
    """Every file that means "stop" for this account (L1-07).

    The configured path AND the account-scoped one.  Measured against the running loop on 2026-09-07:
    engaging from a worktree wrote `<worktree>/.starquant/live/KILL_SWITCH` while the loop read
    `<repo>/.starquant/live/KILL_SWITCH`, printed success and stopped nothing.  Both are written and both
    are cleared, so an operator's existing habit keeps working and there is no window in which the
    emergency stop is weaker than it was.
    """
    return (kill_switch_path(payload), *account_kill_switches(payload))


def engage_kill_switch(payload: dict[str, Any], reason: str) -> Path:
    """Engage EVERY path that means stop for this account, and return the configured one.

    `live flatten` engages the switch through here, and flatten is the one command whose entire
    purpose is to stop - so it writing a file two of the three readers cannot see would be the L1-07
    defect at its least funny.
    """
    written = engage_kill_switches(kill_switch_targets(payload), reason)
    return written[0] if written else kill_switch_path(payload)


def refuse_second_instance(busy: LockBusy) -> tuple[int, str]:
    """Exit code and message for an instance that lost the lock.

    Zero, deliberately: launchd is configured with ``KeepAlive.SuccessfulExit=false``, so a
    non-zero exit here would relaunch the loser every ThrottleInterval and alert every time -
    an alert storm about the guard working correctly (KILL-R20(d)).
    """
    return 0, f"已有另一个StarQuant实例持有这个账户的锁：{busy}"


@live.command("run")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--dry-run", is_flag=True, help="compute targets and planned orders; never write to the venue")
@click.option(
    "--paper", is_flag=True, help="simulate fills in-process at mainnet marks; no credentials or exchange writes"
)
@click.option("--paper-balance", default=10_000.0, show_default=True)
@click.option("--cycles", default=None, type=int, help="stop after N bar cycles (default: run forever)")
@click.option(
    "--immediate", is_flag=True, help="run one cycle on the last closed bar right away, then follow the schedule"
)
@click.option("--symbols", default="", help="comma-separated universe override")
@click.option("--allow-unvalidated", is_flag=True, help="start even if enabled strategies lack validation evidence")
@click.option(
    "--armed",
    is_flag=True,
    help="required for a non-dry-run, non-paper loop: this sends real orders to the configured account",
)
@click.option("--data-root", default=".starquant/data", show_default=True)
@click.option(
    "--registry",
    "registry_override",
    default="",
    help=(
        "DL-G5: read a CANDIDATE registry instead of the profile's, so a canary can soak one.  "
        "Refused without --dry-run or --paper: an armed loop is promoted by writing the registry file "
        "(a transaction that can roll back), never by pointing at a different one."
    ),
)
@click.option(
    "--state-dir",
    default="",
    help=(
        "DL-G5: write this run's state somewhere other than the profile's `paths.state_dir`, so a "
        "canary can soak a candidate registry beside the armed loop without touching its record.  "
        "Refused without --dry-run or --paper: an armed loop with a forked state.json is two books."
    ),
)
@click.option("--verbose", is_flag=True)
def live_run(
    registry_override: str,
    state_dir: str,
    profile: str,
    dry_run: bool,
    paper: bool,
    paper_balance: float,
    cycles: int | None,
    immediate: bool,
    symbols: str,
    allow_unvalidated: bool,
    armed: bool,
    data_root: str,
    verbose: bool,
) -> None:
    """Run the bar-driven live loop against the configured (demo) venue."""
    _logging(verbose)
    # DL-L1: sending real orders is opt-in.  Before this, the only thing between a worktree
    # experiment and the live account was remembering to type --dry-run (KILL-R20).
    if not dry_run and not paper and not armed:
        raise click.ClickException(
            "this would send real orders to the configured account; pass --armed to confirm, or --dry-run / --paper"
        )
    # Beside --armed's own refusal, and before anything reads the profile or the data archive.  A
    # safety check that runs after the dataset gate is one that can be bypassed by deleting data, and
    # both of these are about what this process may touch rather than about whether it has evidence.
    #
    # `state.json` carries the day's equity mark, the leaving set, the exit anchors and
    # `stopped_books`; an armed loop reading a different copy is a second book trading the same
    # account, and the account lock would not stop it - that lock is keyed on the API key, not the
    # directory.  And an armed loop is promoted by WRITING the registry as a transaction that can roll
    # back, never by pointing at another file: that would be a running book no file on disk describes.
    if not (dry_run or paper):
        for flag, value in (("--state-dir", state_dir), ("--registry", registry_override)):
            if value:
                raise click.ClickException(f"{flag} requires --dry-run or --paper")
    payload = load_profile(profile)
    if registry_override:
        payload["registry"] = registry_override
    model, registry = build_model_from_profile(payload)
    problems = registry_evidence_problems(registry, payload)
    # D-041: the dataset manifest, read rather than only written.  Advisory lines are printed and do not
    # stop anything - the daily sync moves klines/funding, and the loop rewrites universe.json itself.
    dataset = registry_dataset_problems(registry, data_root, _interval(payload))
    for message in (*dataset.blocking, *dataset.advisory):
        click.echo(f"dataset: {message}")
    if problems or dataset.blocking:
        for problem in problems:
            click.echo(f"evidence: {problem}")
        if not allow_unvalidated and not dry_run and not paper:
            raise click.ClickException(
                "enabled strategies lack validation evidence, or cite data that has since changed; "
                "run `starquant research validate` or pass --allow-unvalidated"
            )
    if state_dir:
        payload.setdefault("paths", {})["state_dir"] = state_dir
    universe = resolve_universe(
        payload, [s for s in symbols.split(",") if s.strip()] or None, data_root, registry=registry
    )
    config = live_config(payload, universe, registry, dry_run=dry_run)
    store = StateStore(_paper_state_dir(payload, state_dir)) if paper else build_store(payload, dry_run=dry_run)
    market = build_market_data(payload)
    venue: Any
    if paper:
        venue = _paper_venue(market.base_url, paper_balance, store.directory / "paper_venue.json")
    else:
        venue = build_venue(payload, (config.kill_switch_path, *config.kill_switch_paths))
    alert_config = payload.get("alerts", {}) or {}
    alerts = WebhookAlerts(
        str(alert_config.get("webhook_url", "")),
        secondary_url=str(alert_config.get("webhook_url_2", "")),
        dedup_window_seconds=float(alert_config.get("dedup_window_seconds", HOURLY_CALLER_WINDOW_SECONDS)),
        # One dedup window across every process that can alert (DL-L3): the loop, `report daily` and
        # `run_check.sh` share the file, so a standing problem announces itself once an hour rather
        # than once per process per hour.
        state_path=ALERT_DEDUP_STATE,
    )
    pool = build_pool(payload, market)
    if not trades_the_account(dry_run=dry_run, paper=paper, state_dir=state_dir, registry_override=registry_override):
        pool = None
    engine = LiveEngine(
        config,
        model=model,
        market=market,
        venue=venue,
        clock=SystemClock(),
        store=store,
        alerts=alerts,
        pool=pool,
        universe_sink=universe_sink(data_root) if pool is not None else None,
        # DL-Q6: the loop records the metrics it could read, which is what makes research and live one
        # source rather than two (KILL-Q11).
        metrics_store=MetricsStore(data_root, kind="metrics_snapshot"),
        # DL-D5 / RISK-G3: the spot stamp measurement `starquant data spot` last wrote to THIS root, with
        # its verdict re-derived from its own counts.  Read here rather than in the engine because the
        # engine must not learn where data lives - and read from the data root rather than from the
        # profile, so the loop is authorised by the same ingest that produced the bars it trades on.
        # `None` when no measurement was ever taken here, which is the refusal `spot_refusal` prints.
        spot_verification=read_spot_verification(data_root),
        # Read always, write only from the account's own process; see `trades_the_account`.
        record_metrics=trades_the_account(
            dry_run=dry_run, paper=paper, state_dir=state_dir, registry_override=registry_override
        ),
    )
    leverage = "auto" if config.leverage_mode == "auto" else str(config.leverage)
    click.echo(
        f"universe={engine.universe} interval={config.interval} leverage={leverage} pool_refresh={pool is not None} "
        f"exits={config.exits.enabled} throttle={config.throttle.enabled} dry_run={dry_run} paper={paper} "
        f"kill_switch={','.join(str(p) for p in (config.kill_switch_path, *config.kill_switch_paths))} "
        f"state={store.directory}"
    )

    # DL-L6: `launchctl unload` sends SIGTERM and SIGKILLs after ExitTimeOut (30s in the plist).
    # Without this the loop dies wherever it is, which during a cycle means orders sent and not yet
    # recorded.  Installed here rather than in the engine: signal handlers are process-global.
    stop = StopRequested()

    def _stop(signum: int, _frame: object) -> None:
        stop.request(signal.Signals(signum).name)
        click.echo(f"{signal.Signals(signum).name} received; finishing this cycle then stopping")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    async def main() -> int:
        try:
            return await engine.run(cycles, immediate=immediate, stop=stop)
        finally:
            close = getattr(venue, "aclose", None)
            if callable(close):
                await close()
            await market.aclose()

    # DL-L1: hold the account's lock for the life of the loop.  Keyed to the API key rather than to
    # the state directory, because every worktree has a different directory and they all trade the
    # same account.  dry-run and paper touch nothing, so they do not contend.
    lock_holder: SingleInstanceLock | None = None
    if not dry_run and not paper:
        venue_cfg = payload.get("venue", {}) or {}
        api_key = env_secret(str(venue_cfg.get("api_key_env", "STARQUANT_DEMO_API_KEY")))
        try:
            lock_holder = SingleInstanceLock(account_lock_path(api_key)).__enter__()
        except LockBusy as busy:
            code, message = refuse_second_instance(busy)
            click.echo(message)
            asyncio.run(alerts.send(f"StarQuant 循环：{message}", key="second-instance"))
            raise SystemExit(code) from None

    try:
        done = asyncio.run(main())
    except BreakerTripped as tripped:
        # DL-L2: the breaker already said this out loud on a channel that accepted it, so exit 0 and
        # let launchd leave the process down (KeepAlive.SuccessfulExit=false).  A non-zero exit here
        # would be relaunched into the same wall every ThrottleInterval seconds, which is L1-03.
        click.echo(f"breaker tripped: {tripped}")
        click.echo("exiting 0 so launchd does not relaunch; run `starquant live run` to resume")
        return
    finally:
        if lock_holder is not None:
            lock_holder.__exit__(None, None, None)
    click.echo(f"completed {done} cycle(s) without error")
    if cycles is not None and done < cycles:
        raise click.ClickException(f"{cycles - done} of {cycles} cycle(s) failed; see {store.heartbeat_path}")


@live.command("soak")
@click.option("--state-dir", default=".starquant/paper-l3", show_default=True, help="Which soak to score.")
@click.option("--days", default=7.0, show_default=True, help="§5 L3's window.")
@click.option("--root", default=".", help="Checkout to read the transaction log from.")
@click.option("--check", is_flag=True, help="Exit non-zero when L3 as ruled fails.")
def live_soak(state_dir: str, days: float, root: str, check: bool) -> None:
    """L3's criterion, computed - and computed three ways, because §5 states it two that disagree.

    "7 天无 ERROR 相" counts ERROR cycles; "ERROR 相不产生任何治理决定" is a claim about their
    consequences.  On the armed record the second holds and the first cannot: 0.318 ERROR/day gives a
    10.8% chance of seven consecutive clean days, and the cause is the proxy §5 names itself.  Nothing
    computed either reading until 2026-09-09, so the soak ran for a criterion that lived in prose.

    **Ruled 2026-09-10**: `--check` gates on the no-decision reading AND a bar on the longest ERROR
    streak.  The no-decision sentence is the one with a mechanism behind it - `no_decision_phases` is
    enforced and falsifiable per cycle - while the literal count tallies a phase that means the loop
    declined to act on bad data.  The streak bar closes what neither reading covered: six hours of 503s
    decide nothing either.  It is `STUCK_IN_ERROR_STREAK`, the same 3 this file's `status --check`
    already pages on, so the two cannot disagree about what "stuck" means.

    The literal reading is still computed and printed.  Ruling it out of the gate is not deleting it.
    """
    from starquant_governance.policy import Policy
    from starquant_governance.promote import closed, read_log
    from starquant_live.soak import render, score

    path = Path(state_dir) / "cycles.jsonl"
    if not path.exists():
        raise click.ClickException(f"no soak record at {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    log = read_log(Path(root).resolve() / "governance" / "transactions.jsonl")
    # R10: the phase list is the policy's, not this call site's.  `score`'s default happens to match it
    # today, which is exactly how a threshold stops having one home - KILL-AR-20 put it in `Policy` and
    # nothing read it from there.
    reading = score(
        rows,
        required_days=days,
        transactions_closed=closed(log) if log else None,
        no_decision_phases=Policy().no_decision_phases,
    )
    click.echo(render(reading))
    if check and not reading.passes:
        raise SystemExit(1)


@live.command("status")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--paper", is_flag=True, help="inspect the paper-mode state directory instead")
@click.option(
    "--check",
    is_flag=True,
    help="exit non-zero when the heartbeat is stale or the loop is erroring (cron/launchd alerts)",
)
@click.option("--max-age-seconds", default=None, type=float, help="staleness threshold (default: 2 x interval)")
@click.option(
    "--max-skew-seconds",
    default=60.0,
    show_default=True,
    help="tolerated distance between the wake-up and a real bar boundary (a whole-bar offset is fine)",
)
@click.option(
    "--min-success-rate",
    default=0.95,
    show_default=True,
    help="M-001: fail the check when fewer than this share of recent cycles completed",
)
@click.option("--min-success-window", default=24, show_default=True, help="hours of cycles the rate covers")
def live_status(
    profile: str,
    paper: bool,
    check: bool,
    max_age_seconds: float | None,
    max_skew_seconds: float,
    min_success_rate: float,
    min_success_window: int,
) -> None:
    """Show heartbeat and state written by the running loop."""
    payload = load_profile(profile)
    store = _store_for(payload, paper)
    heartbeat = store.read_heartbeat()
    state = store.load()
    click.echo(json.dumps({"heartbeat": heartbeat, "state": state.to_dict()}, indent=2, sort_keys=True, default=str))
    # Beside the dump rather than inside it: the dump is what `live status | jq` reads, and the number
    # this line explains - `state.leverage_set`, eighteen identical 5s - is in there.  Unconditional,
    # above the `--check` return, because the reader who needs it is the one running this by hand.
    click.echo(risk_adaptation_headline(latest_risk_adaptation(store)))
    if not check:
        return
    interval = str((payload.get("market_data", {}) or {}).get("interval", "1h"))
    threshold = max_age_seconds if max_age_seconds is not None else 2.0 * interval_seconds(interval)
    problems: list[str] = []
    skew = clock_skew_seconds(str((payload.get("market_data", {}) or {}).get("rest_url", DEFAULT_BASE_URL)))
    if skew is None:
        click.echo("时钟：取不到交易所时间（本项跳过）")
    else:
        span = float(interval_seconds(interval))
        alignment = ((skew + span / 2) % span) - span / 2
        click.echo(f"时钟：交易所与本机相差 {skew:+.1f}s（距 K 线边界 {alignment:+.1f}s）")
        # D-025: the host clock is the reference, so a whole-bar offset is accepted; the remainder is what
        # decides whether the loop wakes on a bar the venue has already closed.
        if abs(alignment) > max_skew_seconds:
            problems.append(
                f"唤醒时点距 K 线边界 {alignment:+.1f}s（> {max_skew_seconds:.0f}s）："
                "循环可能在交易所尚未收线的 K 线上动作"
            )
    # DL-Q0 / KILL-Q15: the loop loads the registry once at startup and never reloads it, so an edit
    # to the file changes what it SAYS without changing what the loop TRADES.  Comparing the digest the
    # last cycle recorded against the file's own digest is the only thing that can see that gap - the
    # construction fingerprint covers the portfolio layer, the evidence gate runs before the edit, and
    # `live verify` rebuilds its model from the same file it would be checking.
    recorded = last_recorded_registry_digest(store, state.restarted_at)
    if recorded is None:
        click.echo("registry：还没有任何周期记录过 digest")
    else:
        on_disk = registry_digest(build_model(load_registry(payload["registry"]), payload))
        if recorded == on_disk:
            click.echo(f"registry：与正在运行的循环一致（{recorded}）")
        else:
            problems.append(
                f"磁盘上的 registry（{on_disk}）不是循环正在跑的那份（{recorded}）；"
                "下次重启会静默改变交易内容 —— 要么有意识地重启，要么把文件改回去"
            )
    # R9 / RISK-G8, same shape one layer up: the loop imports `policy.py` once, so a rule edit changes
    # the repository and not the process.  The digest was already in every cycle row; this is the
    # comparison that turns it into an instrument.
    recorded_policy = last_recorded_governance_digest(store, state.restarted_at)
    if recorded_policy is None:
        click.echo("治理规则：还没有任何周期记录过 digest")
    elif recorded_policy == policy_digest():
        click.echo(f"治理规则：与正在运行的循环一致（{recorded_policy}）")
    else:
        problems.append(
            f"磁盘上的治理规则（{policy_digest()}）不是循环正在跑的那份（{recorded_policy}）；"
            "阈值改了但进程还按旧的判 —— 要么重启，要么把 policy.py 改回去"
        )
    if heartbeat is None:
        problems.append("没有心跳")
    else:
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(str(heartbeat.get("at")))).total_seconds()
        except ValueError:
            age = float("inf")
        if age > threshold:
            problems.append(f"心跳已过期 {age:.0f}s（> {threshold:.0f}s）")
        if heartbeat.get("phase") == "ERROR" and (int(heartbeat.get("consecutive_errors", 0)) >= STUCK_IN_ERROR_STREAK):
            problems.append(f"循环处于报错状态：{heartbeat.get('error')}")
    # M-001: what share of the loop's own cycles completed, from the append-only log rather than the heartbeat
    health = cycle_health(
        store.read_jsonl(store.cycles_path),
        now=datetime.now(UTC),
        window_hours=float(min_success_window),
        restarted_at=state.restarted_at,
    )
    if health.success_rate is None:
        click.echo(f"周期：最近 {health.window_hours:.0f} 小时内没有任何周期")
    else:
        click.echo(
            f"周期：最近 {health.window_hours:.0f} 小时共 {health.attempts} 次，完成 "
            f"{health.success_rate:.1%}（失败 {health.failures} 次）；连续无故障无重启 {health.clean_days} 天；"
            f"{health.restarts_note()}"
        )
        if health.success_rate < min_success_rate:
            problems.append(
                f"周期成功率 {health.success_rate:.1%} < {min_success_rate:.0%}"
                f"（{health.attempts} 次中失败 {health.failures} 次，最近一次在 {health.last_failure}）"
            )
    # "Why did that symbol flatten?" is asked at this prompt, and the answer was spread over five
    # settings in three packages with two of them binding on only one side of the system.  Printed as
    # the live half plus the count of what research does differently, so the divergence is visible to
    # the operator who would have to price closing it (see `starquant_live/staleness.py`).
    live_rules = rules_binding("live")
    research_only = [rule for rule in RULES if rule.binds == "research"]
    click.echo(
        f"不可交易判定：实盘 {len(live_rules)} 条（"
        + "、".join(rule.label for rule in live_rules)
        + "）"
        + (f"；研究侧另有 {len(research_only)} 条实盘不绑（{research_only[0].label}）" if research_only else "")
    )
    if problems:
        raise click.ClickException("; ".join(problems))


def _store_for(payload: dict[str, Any], paper: bool) -> StateStore:
    if paper:
        return StateStore(Path((payload.get("paths", {}) or {}).get("state_dir", ".starquant/live")).with_name("paper"))
    return build_store(payload, dry_run=False)  # status/report read what the LIVE loop wrote


@live.command("verify")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--paper", is_flag=True, help="verify the paper-mode state directory instead")
@click.option("--tolerance", default=1e-9, show_default=True, help="max |difference| per contribution")
@click.option("--check", is_flag=True, help="exit non-zero when the last cycle's contributions do not reproduce")
@click.option("--data-root", default=".starquant/data", show_default=True)
def live_verify(profile: str, paper: bool, tolerance: float, check: bool, data_root: str) -> None:
    """M-011: recompute the last cycle's model output from public data + state.json and diff it (KILL-027 monitor).

    Reads only.  Contributions must reproduce to the tolerance; a target difference is informational
    because state.json holds the post-throttle / post-exit / post-guard targets.
    """
    _logging(False)
    payload = load_profile(profile)
    model, registry = build_model_from_profile(payload)
    store = _store_for(payload, paper)
    state = store.load()
    if state.last_bar_ms is None:
        raise click.ClickException("state.json 里还没有任何已完成的周期")
    if state.stopped_books:
        model = model.without_books(list(state.stopped_books))
    universe = list(dict.fromkeys([*state.universe, *state.leaving])) or resolve_universe(payload, None, data_root)
    config = live_config(payload, universe, registry, dry_run=True)
    market = build_market_data(payload)

    async def main() -> dict[str, Any]:
        try:
            return await verify_live_targets(
                model,
                market,
                universe,
                config.interval,
                required_history(model, config.history_bars),
                state,
                tolerance,
                recorded_as_of_ms=last_recorded_as_of_ms(store),
                # How long after the bar closed the cycle being checked actually read it.  Six
                # KILL-027 failures in 48h all came from cycles that fetched inside the venue's
                # settle window; without this the alert could only say "it no longer reproduces".
                fetch_lag=fetch_lag_seconds(last_scored_cycle(store)),
                # P1-01: rank against the names the cycle itself declared (state.universe), not
                # against `universe`, which adds the `leaving` symbols this reproduction fetches.
                reference_symbols=list(state.universe) or universe,
            )
        finally:
            await market.aclose()

    result = asyncio.run(main())
    result["last_cycle_clock"] = cycle_clock(last_cycle(store))
    click.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
    if check and not result.get("ok"):
        # Keep the evidence before raising.  Six of these fired between 2026-09-10 and 2026-09-12 and
        # every one of them was unrecoverable an hour later: the check job pages with the last three
        # lines of this JSON, stdout rolls, and the state the diff describes is overwritten by the next
        # cycle.  Append-only, beside the other cross-process state; a failure that leaves no trace is
        # indistinguishable from one that never happened.
        try:
            APP_SUPPORT.mkdir(parents=True, exist_ok=True)
            with (APP_SUPPORT / "verify-failures.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": datetime.now(UTC).isoformat(), **result}, default=str) + "\n")
        except OSError as error:  # never let the record-keeping swallow the failure it is recording
            click.echo(f"（写不下 verify-failures.jsonl：{error}）", err=True)
        raise click.ClickException(str(result.get("note")))


@live.command("flatten")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--yes", is_flag=True, help="confirm closing every position with reduce-only market orders")
@click.option("--data-root", default=".starquant/data", show_default=True)
def live_flatten(profile: str, yes: bool, data_root: str) -> None:
    """Close all positions now (reduce-only market orders); works while the kill switch is engaged."""
    if not yes:
        raise click.ClickException("pass --yes to confirm flattening every position")
    _logging(False)
    payload = load_profile(profile)
    model, registry = build_model_from_profile(payload)
    universe = resolve_universe(payload, None, data_root)
    config = live_config(payload, universe, registry, dry_run=False)
    venue = build_venue(payload, (config.kill_switch_path, *config.kill_switch_paths))
    # L1-06: take the trading rights away BEFORE closing anything.  `flatten` used to leave the loop
    # running, so the next cycle rebuilt every position it had just closed - the 2026-09-04 incident
    # path, and the root KILL-R2 identified under the watchdog problem.  The switch is durable, so
    # this also survives a restart: resuming is an explicit `starquant live kill-switch --release`.
    engaged = engage_kill_switch(
        payload, f"engaged by `starquant live flatten` {datetime.now(UTC).isoformat()}; release to resume\n"
    )
    click.echo(f"kill switch engaged: {engaged}")
    store = build_store(payload, dry_run=False)  # flatten is a real action, never a rehearsal
    # `StateStore.load` refuses a corrupt state.json, and `live run` inherits that refusal on purpose.
    # This command must not.  Flatten reads the venue's positions and the instrument rules; the state
    # file contributes nothing it needs.  An emergency exit that a half-written file can block is a
    # worse failure than the one the refusal exists to prevent - and the file is most likely to be
    # half-written exactly when the process died mid-cycle, which is when someone reaches for flatten.
    try:
        state = store.load()
    except StateUnreadable as exc:
        click.echo(f"state.json 读不动，用空状态继续平仓（平仓只需要交易所仓位）：{exc}", err=True)
        state = LiveState()
    engine = LiveEngine(
        config,
        model=model,
        market=build_market_data(payload),
        venue=venue,
        clock=SystemClock(),
        store=store,
        state=state,
    )

    async def main() -> None:
        try:
            for item in await engine.flatten():
                click.echo(json.dumps(item.to_dict(), default=str))
        finally:
            await venue.aclose()

    asyncio.run(main())


# DL-L3: shared by every process that can alert, beside the lock and the kill switch.
ALERT_DEDUP_STATE = APP_SUPPORT / "alert-dedup.json"


def alert_transport() -> httpx.AsyncBaseTransport | None:
    """Seam for the drill's tests; None means a real network client."""
    return None


def redacted(url: str) -> str:
    """A webhook URL is a credential - whoever holds it can post as the bot.  Show the host only."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/...({len(url)} chars)" if parsed.netloc else "(unparseable)"


@live.command("alert-test")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--repeat", default=1, show_default=True, help="trigger N times; AC-L3 wants 10 -> 1 message")
def live_alert_test(profile: str, repeat: int) -> None:
    """Send one drill alert and say honestly whether it landed (AC-L3).

    Before this the only path to the alert channel was a real failure, so the one signal the breaker's
    clean exit depends on could not be exercised without first breaking something - which is why it
    never had been.  With a single channel (operator ruling 2026-09-07) this is the whole verification
    instrument, so it exits non-zero whenever nothing was delivered, including the case the hardened
    `accepted()` exists for: HTTP 200 and the message quietly gone.

    Deliberately NOT joined to the shared dedup file the loop and the check job use: a drill run twice
    in an hour must send twice, or the instrument would report a failure the second time and teach the
    operator to distrust it.  `--repeat` still demonstrates the window, in this process.
    """
    payload = load_profile(profile)
    config = payload.get("alerts", {}) or {}
    alerts = WebhookAlerts(
        str(config.get("webhook_url", "")),
        secondary_url=str(config.get("webhook_url_2", "")),
        dedup_window_seconds=float(config.get("dedup_window_seconds", HOURLY_CALLER_WINDOW_SECONDS)),
        transport=alert_transport(),
    )
    if not alerts.enabled:
        click.echo("没有配置告警通道：请在 profile 里设置 alerts.webhook_url")
        raise SystemExit(1)
    for url in alerts.urls:
        click.echo(f"通道：{redacted(url)}")
    stamp = datetime.now(UTC).isoformat()
    text = f"StarQuant告警演练 {stamp}：这是一条告警通道测试消息，无需处理"
    delivered = suppressed = 0
    for _ in range(max(1, repeat)):
        if asyncio.run(alerts.send(text, key="alert-drill")):
            delivered += 1
        else:
            suppressed += 1
    if delivered:
        click.echo(f"已送达 {delivered} 条；{suppressed} 条因去重窗口被抑制")
        return
    click.echo("未送达：没有任何通道接收这次演练 —— 熔断时将无法对外报出停机")
    raise SystemExit(1)


@live.command("kill-switch")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--engage/--release", default=True, help="engage (default) or release the durable kill switch")
def live_kill_switch(profile: str, engage: bool) -> None:
    """Engage/release the kill-switch file: while engaged, only risk-reducing orders are sent."""
    payload = load_profile(profile)
    targets = kill_switch_targets(payload)
    # L1-07 once more.  `account_kill_switches` returns an empty tuple in two different situations - a
    # paper run with no account to scope to, and an operator whose shell lacks the export - and this
    # command must not treat the second like the first.  Measured 2026-09-13T20:44Z on the running demo
    # loop: a `--release` without the credential printed one success line, exited 0, and left the
    # account-scoped file engaged, so the book stayed stopped while the operator had been told it was
    # released.  Release therefore refuses before touching anything; engage still writes what it can,
    # because a kill switch fails toward stopping, and only then says the stop is weaker than it looks.
    name = str((payload.get("venue", {}) or {}).get("api_key_env", ""))
    blind = bool(name) and not os.environ.get(name)
    if blind and not engage:
        raise click.ClickException(
            f"{name} 不在环境里：账户级 kill switch 的路径由 API key 派生，这次只会清掉配置路径，"
            "循环仍然被挡住。先载入凭据再跑 --release。"
        )
    if engage:
        for written in engage_kill_switches(targets, f"engaged {datetime.now(UTC).isoformat()}\n"):
            click.echo(f"kill switch engaged: {written}")
        if blind:
            raise click.ClickException(f"{name} 不在环境里：只写了配置路径，账户级开关没有落下——这个停止比看上去弱。")
    else:
        removed = release_kill_switches(targets)
        for cleared in removed:
            click.echo(f"kill switch released: {cleared}")
        if not removed:
            click.echo(f"kill switch was not engaged (checked {len(targets)} path(s))")


def _interval(profile: dict[str, Any]) -> str:
    return str((profile.get("market_data", {}) or {}).get("interval", "1h"))


def _evidence_reports(registry: Registry) -> dict[str, Any]:
    """The reports the enabled strategies cite.  `report daily` and `report weekly` had byte-identical
    copies of this loop; one copy is what let the dataset check be added to both at once."""
    evidence: dict[str, Any] = {}
    for entry in registry.enabled:
        report_path = Path(str((entry.evidence or {}).get("report", "")))
        if report_path.exists():
            evidence[entry.id] = json.loads(report_path.read_text(encoding="utf-8"))
    return evidence


@report.command("daily")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--paper", is_flag=True, help="report on the paper-mode state directory")
@click.option("--date", "day", default=None, help="YYYY-MM-DD (default: today UTC)")
@click.option(
    "--out", default=None, help="directory for the markdown/json report (default: profile paths.reports_dir/daily)"
)
@click.option("--check", is_flag=True, help="exit non-zero when the report is in ALERT (for the hourly monitor)")
@click.option("--data-root", default=".starquant/data", show_default=True)
def report_daily(profile: str, paper: bool, day: str | None, out: str | None, check: bool, data_root: str) -> None:
    """Render the daily attribution report (with drift vs validation expectations) from the live state files."""
    payload = load_profile(profile)
    store = _store_for(payload, paper)
    chosen = day or datetime.now(UTC).strftime("%Y-%m-%d")
    registry = load_registry(payload.get("registry", "config/alpha_registry.yaml"))
    data = daily_payload(
        store,
        chosen,
        expectations_from_evidence(_evidence_reports(registry)),
        probes_from_registry(registry),
        RiskBudgetParams.from_mapping(payload.get("risk_budget", {}) or {}),
        dataset=asdict(registry_dataset_problems(registry, data_root, _interval(payload))),
        vol_target=portfolio_params(payload).vol_target,
        # The policy, not `PortfolioParams` - `margin_cap` is a live-config field (D-016) and does not
        # exist on the research dataclass.  Absent from a profile, M-007 falls back to the plan's 50%.
        margin_cap=float((payload.get("portfolio", {}) or {}).get("margin_cap", 0.0)) or None,
        data_root=data_root,
        exits=ExitParams.from_mapping(payload.get("exits", {}) or {}),
        fidelity=ReplayInputs.from_profile(payload, registry, data_root),
    )
    markdown = daily_markdown(data)
    directory = Path(out or Path((payload.get("paths", {}) or {}).get("reports_dir", "reports")) / "daily")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{chosen}.md").write_text(markdown, encoding="utf-8")
    (directory / f"{chosen}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    click.echo(markdown)
    click.echo(f"已写入 {directory / f'{chosen}.md'}")
    # The drift status was computed and then thrown away: nothing ever sent it anywhere.  Which
    # findings page and which are only read is `daily_alerts`' decision and its docstring carries the
    # reasoning; this function does the routing.  Notices go to stdout beside the report and touch
    # neither the webhook nor the exit code, so an unactionable standing fact cannot hold the hourly
    # health check red - which is what a construction-cadence count did for three days.
    alerts, notices = daily_alerts(data)
    for notice in notices:
        click.echo(f"提示 {chosen}：{notice}")
    if alerts:
        message = f"StarQuant日报 {chosen}：" + " | ".join(alerts)
        click.echo(message, err=True)
        # Every configured channel, not just the first: this path used to read `webhook_url` alone,
        # so a channel added for redundancy would have covered the loop and not the daily check.
        alert_config = payload.get("alerts", {}) or {}
        daily = WebhookAlerts(
            str(alert_config.get("webhook_url", "")),
            secondary_url=str(alert_config.get("webhook_url_2", "")),
            state_path=ALERT_DEDUP_STATE,
        )
        if daily.enabled and not asyncio.run(daily.send(message)):
            click.echo(f"提示 {chosen}：上面这条告警没有送达任何通道", err=True)
    if check and alerts:
        raise SystemExit(1)


def _changed_lines(commits: int) -> dict[str, int] | None:
    """Lines added plus removed per path over the last N commits, or None outside a git checkout."""
    try:
        raw = subprocess.run(
            ["git", "log", "--numstat", "--format=", f"-{max(1, commits)}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    totals: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        count = (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
        totals[path] = totals.get(path, 0) + count
    return totals or None


def _log_first_mentions(strategies: Iterable[str]) -> dict[str, str | None]:
    """The earliest commit that introduced a mention of each strategy into `docs/RESEARCH_LOG.md`.

    `-S` matches commits where the number of occurrences of the string CHANGED, which is what "first
    mentioned" means; `git log` walks newest first, so the last line is the earliest such commit.
    """
    out: dict[str, str | None] = {}
    for strategy in strategies:
        try:
            raw = subprocess.run(
                ["git", "log", "--format=%aI", f"-S{strategy}", "--", "docs/RESEARCH_LOG.md"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            out[strategy] = None
            continue
        stamps = [line.strip() for line in raw.splitlines() if line.strip()]
        out[strategy] = stamps[-1] if stamps else None
    return out


def _search_charged() -> dict[str, str]:
    """When each mined candidate was first charged to the one ledger (DL-K2)."""
    path = resolve_ledger_path()
    if not path.exists():
        return {}
    charged: dict[str, str] = {}
    for record in parse_ledger(path.read_text(encoding="utf-8").splitlines(), MINED_SEARCH_STRATEGY):
        seen = charged.get(record.param_key)
        if seen is None or record.recorded_at < seen:
            charged[record.param_key] = record.recorded_at
    return charged


def _validations_since(directory: Path, since_ms: int) -> list[dict[str, str]]:
    """Every report inside the window that can promote something, as {path, strategy, generated_at}.

    Both kinds, because both promote.  Globbing `*-validation-*.json` alone let a candidate taken
    through `research book` skip the ordering check - the same shape as `ledger_scope` reaching
    `validate` and not `book`, and a protocol whose coverage depends on which command an operator
    happened to run is not a protocol.  For a book it is the SLEEVE that is being promoted, so the
    sleeve is the strategy the ordering is checked against.
    """
    reports: list[dict[str, str]] = []
    for candidate in sorted([*directory.glob("*-validation-*.json"), *directory.glob("book-*.json")]):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stamp = str(payload.get("generated_at", ""))
        try:
            produced = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if produced.timestamp() * 1000 < since_ms:
            continue
        if payload.get("kind") == "book":
            strategy = str((payload.get("sleeve") or {}).get("strategy", ""))
        else:
            strategy = str(payload.get("strategy", ""))
        reports.append({"path": str(candidate), "strategy": strategy, "generated_at": stamp})
    return reports


@report.command("weekly")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--paper", is_flag=True, help="report on the paper-mode state directory")
@click.option("--date", "day", default=None, help="YYYY-MM-DD, the last day of the week (default: today UTC)")
@click.option("--out", default=None, help="directory for the report (default: profile paths.reports_dir/weekly)")
@click.option("--commits", default=40, show_default=True, help="commits to measure the alpha effort share over")
@click.option("--data-root", default=".starquant/data", show_default=True)
@click.option("--research-dir", "research_dir", default="reports/research", show_default=True)
def report_weekly(
    profile: str, paper: bool, day: str | None, out: str | None, commits: int, data_root: str, research_dir: str
) -> None:
    """The plan's weekly research report: the week's decisions next to the week's evidence."""
    payload = load_profile(profile)
    store = _store_for(payload, paper)
    chosen = day or datetime.now(UTC).strftime("%Y-%m-%d")
    registry = load_registry(payload.get("registry", "config/alpha_registry.yaml"))
    data = weekly_payload(
        store,
        chosen,
        expectations=expectations_from_evidence(_evidence_reports(registry)),
        changed_lines=_changed_lines(commits),
        dataset=asdict(registry_dataset_problems(registry, data_root, _interval(payload))),
    )
    # DL-K3: the week's validations, checked for the one ordering the protocol depends on and nothing
    # verified - that the hypothesis was written down before the result was seen (KILL-R9).
    validations = _validations_since(Path(research_dir), int(data["since_ms"]))
    skipped = preregistration_skipped(validations, effective_from=PREREGISTRATION_EFFECTIVE_FROM)
    data["preregistration"] = {
        "checked": len(validations) - skipped,
        "skipped_as_predating_the_check": skipped,
        "effective_from": PREREGISTRATION_EFFECTIVE_FROM,
        "problems": preregistration_problems(
            validations,
            first_mentioned=_log_first_mentions({row["strategy"] for row in validations}),
            search_charged=_search_charged(),
            effective_from=PREREGISTRATION_EFFECTIVE_FROM,
        ),
    }
    markdown = weekly_markdown(data)
    directory = Path(out or Path((payload.get("paths", {}) or {}).get("reports_dir", "reports")) / "weekly")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{chosen}.md").write_text(markdown, encoding="utf-8")
    (directory / f"{chosen}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    click.echo(markdown)
    click.echo(f"已写入 {directory / f'{chosen}.md'}")


@report.command("beta")
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--paper", is_flag=True, help="report on the paper-mode state directory")
@click.option("--strategy", default="tsmom", show_default=True, help="whose contributions to read")
@click.option("--data-root", default=".starquant/data", show_default=True)
@click.option("--out", default=None, help="write the markdown/json here (default: stdout only)")
def report_beta(profile: str, paper: bool, strategy: str, data_root: str, out: str | None) -> None:
    """D-045: how much of the live book's return was the market's, and how much was the signal's."""
    payload = load_profile(profile)
    store = _store_for(payload, paper)
    # The daily report's `beta` block is this same call, so the page and the block cannot disagree.
    data = beta_reading(
        store.read_jsonl(store.cycles_path),
        store.read_jsonl(store.attribution_path),
        _store_closes(data_root, _interval(payload)),
        strategy,
    )
    if "reason" in data:
        raise click.ClickException(str(data["reason"]))
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    def show(name: str, page: str, body: dict[str, Any]) -> None:
        click.echo(page)
        if out:
            directory = Path(out)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{name}-{today}.md").write_text(page, encoding="utf-8")
            (directory / f"{name}-{today}.json").write_text(
                json.dumps(body, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
            )
            click.echo(f"已写入 {directory / f'{name}-{today}.md'}")

    # D-045's page is written before the factor page is read, as it was before that page existed: a
    # failure over there must not take this one down with it.
    show("beta", beta_markdown(data), data)
    # #6.4 / #6.9's second page, the daily report's `factor_loadings` block by the same call.  Its own
    # files, so `beta-*.json` stays the daily `beta` block to the bit.  When it fails, its files say why
    # and the exception still ends the command, whole, with a non-zero exit.
    try:
        factors = factor_reading(
            store.read_jsonl(store.cycles_path),
            store.read_jsonl(store.attribution_path),
            archive_history(data_root, _interval(payload)),
            archive_funding(data_root),
            strategy,
            step_ms=interval_ms(_interval(payload)),
        )
    except Exception as exc:
        refusal: dict[str, Any] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
        show("factors", factor_markdown(refusal), refusal)
        raise
    show("factors", factor_markdown(factors), factors)


__all__ = [
    "live_alert_test",
    "live_flatten",
    "live_kill_switch",
    "live_run",
    "live_status",
    "live_verify",
    "report_beta",
    "report_daily",
    "report_weekly",
]
