"""M-011: reproduce the last live cycle's model output offline and diff it against ``state.json`` (KILL-027 monitor).

The reproduction builds its inputs through ``starquant_live.inputs`` (the same code the
engine uses), seeds the hold with the state's own contributions and compares:

* contributions - the pure model output per strategy; these must match to the tolerance;
* targets - ``state.last_targets`` are the post-throttle / post-exit / post-guard targets, so a
  difference there is informational unless the cycle record shows none of those acted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from starquant_live.inputs import model_inputs
from starquant_live.ports import MarketData, SignalModel, TargetSet
from starquant_live.state import LiveState, StateStore

#: Seconds after a bar closes within which the venue was still aggregating it, measured rather than
#: assumed.  Six KILL-027 failures between 2026-09-10T18:10Z and 2026-09-12T09:10Z were reproduced
#: exactly by replaying 56 cycles offline against freshly fetched klines: every one a single symbol in
#: the `flow` book (3.3e-8 to 8.5e-7 against a 1e-9 tolerance), and `flow` is the only book that reads
#: `taker_buy_quote` / `quote_volume` - the two kline fields the exchange finalises last.
#:
#: Two measurements bracket the window.  Re-fetching the bar that closed at 2026-09-12T12:00Z at +15s,
#: +60s, +300s and +600s over six symbols returned byte-identical values on every field: the kline is
#: settled by +15s.  And of the 57 replayed cycles, all six failures fetched within 14s of the close,
#: while 0 of the 22 that fetched later than 14s failed.  So the loop can read a bar the venue has not
#: finished aggregating, and the window is roughly the first fifteen seconds.
#:
#: This number DIAGNOSES; it gates nothing and widens no tolerance.  A cycle inside the window still
#: fails to reproduce, and still says so - it just also says why.
SETTLE_SECONDS = 15.0


def fetch_lag_seconds(cycle: Mapping[str, Any] | None) -> float | None:
    """Seconds between a bar closing and the cycle that traded it writing its row (``at``)."""
    if not cycle:
        return None
    bar, at = cycle.get("bar_open_ms"), cycle.get("at")
    if not isinstance(bar, int | float) or not isinstance(at, str):
        return None
    try:
        stamp = datetime.fromisoformat(at)
    except ValueError:
        return None
    return stamp.timestamp() - (float(bar) + 3_600_000.0) / 1000.0


def _diff(
    reference: Mapping[str, float], candidate: Mapping[str, float], population: set[str] | None = None
) -> dict[str, float]:
    keys = set(reference) | set(candidate)
    return {
        key: abs(float(reference.get(key, 0.0)) - float(candidate.get(key, 0.0)))
        for key in sorted(keys if population is None else keys & population)
    }


def _scored_population(state: LiveState) -> set[str] | None:
    """The names the last cycle declared it would score, or None when it declared none.

    `state.last_contributions` is a MEMORY, not a record of that cycle's output: the engine merges
    each cycle into the previous ones on purpose, because D-005's hold seed needs a departed symbol's
    last contribution the way the backtest's forward-fill does.  The reproduction scores only the
    names the cycle declared, so diffing the two over the union of their keys reports every departure
    as an unreproducible contribution - once an hour, with no way back.  Measured: TRUMPUSDT left the
    pinned universe at 2026-09-13T21:13Z and `live verify --check` was red for the next 16 runs with
    `max_target_diff` 0.0 throughout.

    `leaving` is a member here and not in the ranking population (P1-01): the engine passes
    universe+leaving to the model and withholds the exits only from the cross-section, so an exiting
    symbol IS scored - and those are the cycles where a silent divergence would matter most.

    None rather than an empty set when the state declares nothing, so the caller compares everything:
    an undeclared population is not a licence to check less.
    """
    population = {*state.universe, *state.leaving}
    return population or None


def compare_targets(
    targets: TargetSet,
    state: LiveState,
    tolerance: float = 1e-9,
    recorded_as_of_ms: int | None = None,
    fetch_lag: float | None = None,
) -> dict[str, Any]:
    """Diff a freshly computed ``TargetSet`` against the persisted state of the last cycle.

    ``recorded_as_of_ms`` is the last cycle's ``as_of_ms`` — the bar the *data* was
    stamped with.  Prefer it over ``state.last_bar_ms``, which is the bar the loop
    *labelled* the cycle with from the host clock: when the two disagree the host
    clock has drifted away from the venue's, and comparing against the label would
    report a spurious mismatch for a cycle that in fact reproduces.
    """
    as_of_ms = int(targets.as_of.timestamp() * 1000)
    reference = recorded_as_of_ms if recorded_as_of_ms is not None else state.last_bar_ms
    matched = reference is not None and as_of_ms == int(reference)
    label_skew = (
        None
        if recorded_as_of_ms is None or state.last_bar_ms is None
        else int(recorded_as_of_ms) - int(state.last_bar_ms)
    )
    contributions: dict[str, dict[str, float]] = {}
    worst_contribution = 0.0
    population = _scored_population(state)
    for strategy, recorded in state.last_contributions.items():
        computed = targets.contributions.get(strategy)
        if computed is None:
            contributions[strategy] = {"<missing>": float("inf")}
            worst_contribution = float("inf")
            continue
        diffs = _diff(recorded, computed, population)
        contributions[strategy] = {symbol: value for symbol, value in diffs.items() if value > tolerance}
        worst_contribution = max(worst_contribution, max(diffs.values(), default=0.0))
    missing = sorted(set(targets.contributions) - set(state.last_contributions))
    weight_diffs = _diff(state.last_targets, targets.weights)
    worst_weight = max(weight_diffs.values(), default=0.0)
    ok = matched and worst_contribution <= tolerance and not missing
    # The offenders, ranked, in a field the alert path can quote in one line.  Six of these fired
    # between 2026-09-10 and 2026-09-12 and not one left a recoverable diff: `run_check.sh` pages with
    # `tail -n 3` of pretty-printed sorted JSON, whose last three lines are `"tolerance": 1e-09` and
    # the closing brace.  A monitor that cannot say WHAT stopped reproducing has not reported anything.
    # Annotated because the rows mix `str` and `float`, so the key function was sorting on `object`.
    ranked: list[dict[str, Any]] = [
        {"strategy": strategy, "symbol": symbol, "diff": value}
        for strategy, diffs in contributions.items()
        for symbol, value in diffs.items()
    ]
    offenders = sorted(ranked, key=lambda row: -float(row["diff"]))[:5]
    return {
        "as_of_ms": as_of_ms,
        "state_bar_ms": state.last_bar_ms,
        "recorded_as_of_ms": recorded_as_of_ms,
        "bar_label_skew_ms": label_skew,
        "bar_matched": matched,
        "max_contribution_diff": worst_contribution,
        "contribution_diffs": contributions,
        "strategies_not_in_state": missing,
        "max_target_diff": worst_weight,
        "target_diffs": {symbol: value for symbol, value in weight_diffs.items() if value > tolerance},
        "worst_contributions": offenders,
        "fetch_lag_seconds": fetch_lag,
        "fetched_before_the_bar_settled": None if fetch_lag is None else fetch_lag < SETTLE_SECONDS,
        "tolerance": tolerance,
        "ok": ok,
        "note": (
            "复算结果与上一周期的 contributions 一致"
            if ok
            else "state.json 属于另一根 K 线；请等下一个周期完成后重跑"
            if not matched
            else "模型已无法复现上一周期的 contributions（配置、代码或数据发生了变化）："
            + "，".join(f"{row['strategy']}/{row['symbol']} 差 {row['diff']:.3e}" for row in offenders[:3])
            + (
                # Not an excuse and not a tolerance: the cycle still failed to reproduce.  It is the
                # sentence six identical alerts could not say, and it points at the wake time rather
                # than at the model.
                f"；该周期在收盘后 {fetch_lag:.0f} 秒取数，落在场所仍在聚合该 K 线的 "
                f"{SETTLE_SECONDS:.0f} 秒内（2026-09-12 实测）"
                if fetch_lag is not None and fetch_lag < SETTLE_SECONDS
                else ""
            )
        ),
        "clock_note": (
            None
            if not label_skew
            else f"该周期被打上的标签与它自己的数据相差 {label_skew / 3_600_000:+.2f} 小时：本机时钟已偏离交易所，"
            "因此 cycles.jsonl 的 `bar` 与心跳的 `at` 是错的（成交本身没错）"
        ),
    }


def last_cycle(store: StateStore) -> Mapping[str, Any] | None:
    """The newest non-dry-run cycle record, or ``None`` when the loop has not completed one."""
    for record in reversed(store.read_jsonl(store.cycles_path)):
        if not record.get("dry_run"):
            return record
    return None


def last_scored_cycle(store: StateStore) -> Mapping[str, Any] | None:
    """The newest cycle that actually ran the model - the one whose contributions ``state.json`` holds.

    Not ``last_cycle``: a restart writes a SKIPPED row with no contributions, and reading the lag off
    that one measures how long after the bar somebody restarted the process, which is a different
    number about a different event (the 12:04:40Z restart on 2026-09-12 read 280s).
    """
    for record in reversed(store.read_jsonl(store.cycles_path)):
        if not record.get("dry_run") and record.get("contributions"):
            return record
    return None


def last_recorded_as_of_ms(store: StateStore) -> int | None:
    """``as_of_ms`` of the newest non-dry-run cycle: the bar the data carried, independent of the host clock."""
    for record in reversed(store.read_jsonl(store.cycles_path)):
        if record.get("dry_run"):
            continue
        value = record.get("as_of_ms")
        if isinstance(value, int | float):
            return int(value)
    return None


def _process_boundary(restarted_at: str | None) -> datetime | None:
    """When the running process took over, or ``None`` when nothing marks a takeover.

    `LiveEngine.startup` persists `restarted_at` through `store.save` BEFORE it writes its first
    heartbeat, so this boundary is already on disk during the whole window in which no cycle of this
    process has completed yet - which is the only window where it is needed.
    """
    try:
        return datetime.fromisoformat(restarted_at) if restarted_at else None
    except ValueError:
        return None


def _this_process_wrote(row: Mapping[str, Any], boundary: datetime | None) -> bool:
    """A live reading the RUNNING process wrote.  An unstamped or unparseable row is not proof, so it is not accepted."""
    if row.get("dry_run"):
        return False
    if boundary is None:  # a first start, or a state file from before the field existed: no takeover to be after
        return True
    try:
        return datetime.fromisoformat(str(row.get("at"))) >= boundary
    except (TypeError, ValueError):
        return False


def _digest_this_process_recorded(store: StateStore, field: str, restarted_at: str | None) -> str | None:
    """The digest the running PROCESS holds - from the heartbeat it overwrites, else the rows it appended.

    `cycles.jsonl` is append-only and carries no process identity, so its newest digest row belongs to
    whichever process last completed a cycle - after a restart, the dead one.  Reading that back as
    "what the loop is running" compares the previous process's answer against the current file and
    reports a divergence the restart just resolved.  Measured 2026-09-14: the loop came up at 19:10:55Z
    already holding the `policy.py` edited at 17:50Z, the 19:11:19Z bar was SKIPPED and recorded no
    digest, and for the rest of the hour the check quoted the dead process's 18:00:29Z `75764f646ca6`
    against a file that said `d62ac59fa95c`.  `com.starquant.check` fires at :10, inside that window every
    time, and `state.restarts` is past 43 - so this fired as often as the loop was restarted.

    The heartbeat is consulted first because it is the one file the current process overwrites BEFORE
    any cycle completes: bc986ec3 put the digests there for exactly this window and changed no reader,
    so the write has been dead since it landed and the window it was meant to close stayed open.  The
    ledger answers once a cycle of this process has landed.  ``None`` - this process has recorded
    nothing yet, or the rows predate the field - is not a divergence and must not be reported as one.
    """
    boundary = _process_boundary(restarted_at)
    for row in [store.read_heartbeat() or {}, *reversed(store.read_jsonl(store.cycles_path))]:
        value = row.get(field)
        if isinstance(value, str) and value and _this_process_wrote(row, boundary):
            return value
    return None


def last_recorded_registry_digest(store: StateStore, restarted_at: str | None = None) -> str | None:
    """Which registry the running process holds (DL-Q0), not which one is on disk (KILL-Q15)."""
    return _digest_this_process_recorded(store, "registry", restarted_at)


def last_recorded_governance_digest(store: StateStore, restarted_at: str | None = None) -> str | None:
    """Which governance RULES the running process holds (R9).

    A running process holds the `starquant_governance.policy` module it imported at startup, so editing a
    threshold changes what the repository says without changing what the loop would enforce.  R9 put the
    digest in every cycle row to make that visible; until this reader existed nothing read it back.
    Measured 2026-09-09: policy 0.3.0 landed at 04:48Z, the loop kept reporting 0.2.0's `753638a519ac`,
    and the 05:08Z restart that closed the gap was for an unrelated reason.
    """
    return _digest_this_process_recorded(store, "governance", restarted_at)


def cycle_clock(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the last cycle knew about the host clock: its measured skew, and whether income ingestion was skipped."""
    if record is None:
        return {"skew_ms": None, "beyond_tolerance": False, "income_skipped_ms": None}
    clock = record.get("clock") or {}
    flows = record.get("external_flows") or {}
    return {
        "skew_ms": clock.get("skew_ms"),
        "beyond_tolerance": bool(clock.get("beyond_tolerance")),
        # set when the income watermark was ahead of the clock, so that cycle attributed nothing (not a fault)
        "income_skipped_ms": flows.get("clock_skew_ms"),
    }


async def verify_live_targets(
    model: SignalModel,
    market: MarketData,
    symbols: Sequence[str],
    interval: str,
    history_bars: int,
    state: LiveState,
    tolerance: float = 1e-9,
    recorded_as_of_ms: int | None = None,
    reference_symbols: Sequence[str] | None = None,
    fetch_lag: float | None = None,
) -> dict[str, Any]:
    """``reference_symbols``: the cross-sectional population the cycle declared (P1-01 / DL-Q1).

    The reproduction has to rank against the same names the cycle did, or it reports a
    mismatch that only exists because the two runs disagreed about the population - which
    would make this monitor's own output the noisiest thing about it.  ``state.universe``
    is that set; ``leaving`` names are held for exit and are not members.
    """
    inputs = await model_inputs(market, model, symbols, interval, history_bars)
    targets = model.targets(
        inputs.bars,
        inputs.funding,
        previous=state.last_contributions,
        funding_history=inputs.funding_history,
        reference_symbols=reference_symbols,
    )
    return {
        "inputs": inputs.to_dict(),
        **compare_targets(targets, state, tolerance, recorded_as_of_ms, fetch_lag=fetch_lag),
    }


__all__ = [
    "SETTLE_SECONDS",
    "compare_targets",
    "cycle_clock",
    "fetch_lag_seconds",
    "last_cycle",
    "last_recorded_as_of_ms",
    "last_recorded_governance_digest",
    "last_recorded_registry_digest",
    "last_scored_cycle",
    "verify_live_targets",
]
