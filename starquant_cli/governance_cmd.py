"""``starquant governance`` - replay the rules; the commands that RULE on something record that they did.

This line said "Phase 0 is read-only: replay the rules, write nothing" until 2026-09-14.  `gate`'s own
docstring was corrected the same day after a session ran it as a read-only check; this one is the same
sentence one level up, and a reader meets it first.  Four commands here write: `gate` and `recheck`
append to `governance/verdicts.jsonl`, `enable` writes its flag file, `replay --out` writes its
artefact.  The claim was true when Phase 0 only replayed and nothing updated it when commands that rule
were added beside the ones that only read.

Kept as a correction rather than a deletion because it was wrong about something worth keeping:
recording a ruling is not ACTING on one.  Nothing here retires, promotes, or touches the registry or
`governance_state.json` - `governance advance` does that.  "Write nothing" was the wrong way to say it.

The git reading lives here rather than in `starquant_governance` deliberately.  What the registry has
cited, and when, is a fact about this checkout's history; keeping it out of the package is what lets
the replay be tested against fixtures instead of against whatever `git log` says today, and it keeps
the package free of `subprocess`.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import click
import yaml

from starquant_alpha.registry import parse_registry
from starquant_alpha.validation.ledger import resolve_ledger_path
from starquant_cli import main
from starquant_governance.admission import WINDOW_ANCHOR, Admission, admit, rolled, window_start
from starquant_governance.assemble import assemble, conclude
from starquant_governance.budget import window_spend
from starquant_governance.canary import evaluate as evaluate_canary
from starquant_governance.family_gate import VERDICT_KIND, refusals
from starquant_governance.family_gate import failures as gate_failures
from starquant_governance.family_gate import recheck as recheck_gate
from starquant_governance.lifecycle import Book, Facts, State
from starquant_governance.lifecycle import apply as apply_event
from starquant_governance.policy import Policy
from starquant_governance.promote import apply as apply_transaction
from starquant_governance.promote import closed, read_log
from starquant_governance.promote import plan as plan_transaction
from starquant_governance.replay import load_jsonl, render, replay_adoptions, replay_live
from starquant_governance.scheduler import WAIT
from starquant_governance.state import read as read_state
from starquant_governance.state import write as write_state
from starquant_governance.tenure import Derived, books_in, tenure
from starquant_governance.verdicts import ALLOW, REFUSE, divergence
from starquant_governance.verdicts import LEDGER as VERDICTS
from starquant_governance.verdicts import read as read_verdicts
from starquant_governance.verdicts import record as record_verdict
from starquant_governance.verdicts import review as review_verdict
from starquant_governance.verdicts import since as verdicts_since
from starquant_live.config import registry_evidence_problems, store_directory
from starquant_live.construction import CONSTRUCTION_ALIASES
from starquant_shared.config import load_yaml

REGISTRY = "config/alpha_registry.yaml"
#: The autonomy switch.  One of the three human confirmation points the plan keeps (§0): single
#: promotions are the machine's from the first transaction (Q9), but whether the machine may write at
#: all is a person's decision, taken once, and it is OFF until somebody takes it.
SWITCH = "governance/ENABLED"
TRANSACTIONS = "governance/transactions.jsonl"
#: The lifecycle state R3/R4/R5/R7 are counted in.  Read by `status`, `tenure` and, since 2026-09-09,
#: by the admission gate `plan`/`apply` run before a write.
STATE = "governance/governance_state.json"


@main.group()
def governance() -> None:
    """Autonomous promotion/demotion rules.  Phase 0: replay only."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout


def _adoptions(root: Path) -> tuple[dict[str, str], set[str]]:
    """Every report the registry has ever cited, the date it first cited it, and which were acknowledged.

    A REJECT pointer only counts as acknowledged when the registry version that INTRODUCED it carried
    `accepted_despite` (D-029).  Checking today's registry instead would backdate an acknowledgement
    onto pointers that never had one, which is the stale-pointer failure this project keeps finding.
    """
    log = _git(root, "log", "--format=%H|%ad", "--date=short", "-p", "--", REGISTRY)
    adoptions: dict[str, str] = {}
    introduced: list[tuple[str, str]] = []
    commit = date = ""
    for line in log.splitlines():
        head, sep, rest = line.partition("|")
        if sep and len(head) == 40:
            commit, date = head, rest
        elif line.startswith("+") and "report:" in line:
            path = line.split("report:", 1)[1].strip()
            if path not in adoptions:
                adoptions[path] = date
                introduced.append((path, commit))
    acknowledged = set()
    for path, commit in introduced:
        name = path.rsplit("/", 1)[-1]
        if not name.startswith("book-"):
            continue
        if "accepted_despite" in _git(root, "show", f"{commit}:{REGISTRY}"):
            acknowledged.add(name)
    return adoptions, acknowledged


def _payloads(directory: Path) -> dict[str, dict[str, Any]]:
    """Every JSON report in one directory, keyed on its file name.  Unreadable files are skipped."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(payload, dict):
            out[path.name] = payload
    return out


def _reports(root: Path) -> dict[str, dict]:
    """The same reports, keyed the way the registry cites them - which is what `replay` matches on."""
    return {f"reports/research/{name}": payload for name, payload in _payloads(root / "reports" / "research").items()}


@governance.command("replay")
@click.option("--since", default="", help="Only replay adoptions and cycles on or after this date (YYYY-MM-DD).")
@click.option("--state-dir", default=".starquant/live", help="Live state directory to read cycles/attribution from.")
@click.option("--out", default="", help="Write the artefact here instead of stdout.")
@click.option("--root", default=".", help="Checkout to read reports and registry history from.")
def replay_cmd(since: str, state_dir: str, out: str, root: str) -> None:
    """Replay the governance rules against the record and attribute every difference (AC-G0)."""
    checkout = Path(root).resolve()
    adoptions, acknowledged = _adoptions(checkout)
    if since:
        adoptions = {path: when for path, when in adoptions.items() if when >= since}
    live = Path(state_dir)
    cycles = load_jsonl((live / "cycles.jsonl").read_text(encoding="utf-8")) if (live / "cycles.jsonl").exists() else []
    attribution = (
        load_jsonl((live / "attribution.jsonl").read_text(encoding="utf-8"))
        if (live / "attribution.jsonl").exists()
        else []
    )
    if since:
        cycles = [row for row in cycles if str(row.get("at", "")) >= since]
        attribution = [row for row in attribution if str(row.get("at", "")) >= since]
    # DL-G9: the evidence-side construction digests the loop has actually recorded.  A report can now
    # be checked against them by string equality, which is what makes KILL-AR-07 readable after the fact.
    seen = sorted({str(row["evidence_construction"]) for row in cycles if row.get("evidence_construction")})
    adopted = replay_adoptions(
        _reports(checkout), adoptions, acknowledged_rejects=sorted(acknowledged), live_constructions=seen
    )
    lived = replay_live(cycles, attribution, construction_aliases=CONSTRUCTION_ALIASES)
    text = render(adopted, lived)
    unattributed = len(adopted.unattributed) + len(lived.unattributed)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        click.echo(f"wrote {out}")
    else:
        click.echo(text)
    click.echo(
        f"AC-G0: {len(adopted.reproduced) + len(lived.reproduced)} reproduced, "
        f"{len(adopted.differences) + len(lived.differences)} differences, {unattributed} unattributed",
        err=True,
    )
    if unattributed:
        raise SystemExit(1)


def _switch(root: Path) -> Path:
    return root / SWITCH


@governance.command("status")
@click.option("--root", default=".", help="Checkout to read state and transactions from.")
def status_cmd(root: str) -> None:
    """What rules this process would run under, and whether it is allowed to write."""
    checkout = Path(root).resolve()
    policy = Policy()
    book = read_state(checkout / STATE)
    enabled = _switch(checkout).exists()
    click.echo(f"policy   {policy.version} digest={policy.digest()} window={policy.window_days}d")
    click.echo(f"autonomy {'ENABLED' if enabled else 'DISABLED'}  ({_switch(checkout)})")
    click.echo(
        f"window   {book.window}  promotions {book.promotions_this_window}/{policy.max_queued_to_probe_per_window}"
    )
    click.echo(
        f"probes   {len(book.probes)}/{policy.max_concurrent_probes}  "
        f"fraction {book.probe_fraction:.3f}/{policy.probe_budget_share:.3f}"
        + (f"  FROZEN until window {book.frozen_until_window}" if book.frozen() else "")
    )
    for name, candidate in sorted(book.candidates.items()):
        click.echo(
            f"  {name:40s} {candidate.state.value:10s} entries={candidate.probe_entries} "
            f"windows={candidate.windows_survived}/{policy.windows_to_main}"
        )
    log = read_log(checkout / TRANSACTIONS)
    click.echo(f"transactions {len(log)} rows, chain {'closed' if closed(log) else 'BROKEN'}")


@governance.command("tenure")
@click.option("--root", default=".", help="Checkout to read governance state from.")
@click.option(
    "--cycles", default=".starquant/live/cycles.jsonl", show_default=True, help="The append-only live record."
)
@click.option(
    "--anchor",
    default="2026-09-03T00:00:00+00:00",
    show_default=True,
    help="When the batch calendar starts.  Global: every sleeve's windows are counted off this one clock.",
)
@click.option("--started", help="ISO start for one sleeve, as book=ISO; repeatable.", multiple=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable, for the report rather than the terminal.")
def tenure_cmd(root: str, cycles: str, anchor: str, started: tuple[str, ...], as_json: bool) -> None:
    """DL-G6': what the live record implies about the time rule.  Reports; promotes nothing.

    Split from `apply` for the same reason `plan` is: a probe reaching main is a registry transaction
    and a restart, and the operator should be able to read what the record says before either.
    """
    path = Path(cycles)
    if not path.exists():
        raise click.ClickException(f"no live record at {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    policy = Policy()
    book = read_state(Path(root).resolve() / STATE)
    starts = dict(pair.split("=", 1) for pair in started if "=" in pair)

    out = []
    for name in books_in(rows) or tuple(book.candidates):
        # The sleeve's own start, falling back to the calendar anchor: KILL-AR-06 grandfathered both
        # running sleeves to the registry's effective date, which is that same day.
        result = tenure(rows, book=name, started_at=starts.get(name, anchor), window_anchor=anchor, policy=policy)
        out.append(result)

    if as_json:
        click.echo(json.dumps([r.as_dict() for r in out], indent=2, sort_keys=True, ensure_ascii=False))
        return
    if not out:
        click.echo("the record names no probe; nothing to derive")
        return
    for result in out:
        # by STRATEGY, not by book: the record's probe rows are keyed on the book ("flow_short")
        # and `governance_state.json` on the registry entry id ("flow").  Keying on the book meant
        # this annotation silently never printed.
        state = book.candidates.get(result.strategy) or book.candidates.get(result.book)
        held = f" (state holds {state.windows_survived})" if state is not None else ""
        click.echo(
            f"{result.book:20s} windows {result.windows_survived}/{policy.windows_to_main}{held}  "
            f"cycles {result.cycles_read}" + (f"  STOPPED {result.stopped_at}" if result.stopped_at else "")
        )
        for event in result.events:
            click.echo(f"    {event.at}  {event.event.value:15s} {event.why}")
        for skip in result.skipped:
            click.echo(f"    {skip.at}  {'(not counted)':15s} {skip.why}")
        if result.windows_survived >= policy.windows_to_main and not result.stopped_at:
            click.echo("    -> the record supports probe -> main; that is a transaction and a restart")
    # By BOOK and by STRATEGY, because the two namespaces meet here: `books_in` reads the record's probe
    # rows (keyed on the book, "main") and `governance_state.json` keys on the registry entry id
    # ("tsmom").  Comparing one against the other is the same mismatch this file already fixed once a
    # few lines above, and it left the note below claiming main -> probe was unreachable for hours
    # AFTER the main book got a stop and started appearing in the record.
    named = set(books_in(rows)) | {result.strategy for result in out if result.strategy}
    silent = sorted(n for n, c in book.candidates.items() if c.state is State.MAIN and n not in named)
    if silent:
        # Only true while the main sleeve carries no stop: `probes_from_registry` includes MAIN_BOOK
        # only when its entry declares one (2026-09-09), so a main book without a stop reports nothing
        # and the main -> probe edge stays unreachable from the record - the same way probe -> main was
        # before this module existed.
        click.echo(
            f"note: {', '.join(silent)} {'sits' if len(silent) == 1 else 'sit'} in main with no stop in "
            "the registry, so the record reports nothing for it and main -> probe cannot fire from it"
        )


@governance.command("transactions")
@click.option("--root", default=".", help="Checkout to read the transaction log from.")
def transactions_cmd(root: str) -> None:
    """Every attempt to change the registry, whatever happened to it."""
    log = read_log(Path(root).resolve() / TRANSACTIONS)
    if not log:
        click.echo("no transactions")
        return
    for transaction in log:
        click.echo(
            f"{transaction.at}  {transaction.action:8s} actor={transaction.actor:8s} "
            f"{transaction.before_digest} -> {transaction.after_digest}  {transaction.candidate}"
            + (f"  {'; '.join(transaction.reasons)}" if transaction.reasons else "")
        )
    if not closed(log):
        raise SystemExit("the transaction chain is broken: something changed the registry outside a transaction")


def _gate(profile_path: str) -> Callable[[Path], list[str]]:
    profile = load_yaml(profile_path)

    def gate(path: Path) -> list[str]:
        registry = parse_registry(load_yaml(str(path)))
        return registry_evidence_problems(registry, profile)

    return gate


def _rows(path: Path) -> list[dict[str, Any]]:
    return load_jsonl(path.read_text(encoding="utf-8")) if path.exists() else []


def _shadow_rows(shadow_dir: str) -> list[dict[str, Any]]:
    """The canary soak's cycles, found where a dry run actually writes them.

    `run_shadow.sh` passes `--state-dir .starquant/live-shadow`; `build_store` appends `-dry-run` to it.
    Every reader here defaulted to the un-suffixed name, so on 2026-09-12 - the first time the soak was
    ever started - the record went to one directory and all three readers looked in another.  Resolved
    through the same function the store uses rather than by writing the suffix out a second time.  The
    un-suffixed directory is still accepted, because a record can also be handed over by hand.
    """
    suffixed = _rows(store_directory(Path(shadow_dir), dry_run=True) / "cycles.jsonl")
    return suffixed or _rows(Path(shadow_dir) / "cycles.jsonl")


def _admission(registry_path: str, proposed: str, root: Path, state_dir: str, shadow_dir: str) -> Admission:
    """R3/R4/R5/R7 and K-EX14, asked of the change before the bytes move.

    Added 2026-09-09.  Until then `apply` asked the startup gate and nothing else, so every constraint
    §3 lists as a precondition of `queued -> probe` was decorative on the only path that promotes:
    a proposal moving 0.9 of the book to an unproven sleeve was accepted against a cap of 1/3.
    """
    return admit(
        parse_registry(load_yaml(registry_path)),
        parse_registry(yaml.safe_load(proposed)),
        book=read_state(root / STATE),
        policy=Policy(),
        cycles=_rows(Path(state_dir) / "cycles.jsonl"),
        shadow=_shadow_rows(shadow_dir),
        # K-EX14's clock reads the canonical construction, not the raw digest: three of the raw
        # changes since 09-04 altered no behaviour and were declared equivalent here on the read side.
        aliases=CONSTRUCTION_ALIASES,
    )


def _log_admission(root: Path, admission: Admission, subject: str) -> None:
    """M-G05's numerator and denominator both start here, at the moment the machine rules.

    Recorded by the gate rather than by whoever remembers: a sample of remembered decisions is
    selected by how memorable they were, and the memorable ones are the surprising ones.

    **Called from `apply` only.**  `plan` asks the same question without making a ruling - its own
    docstring is "what `apply` would do, without doing it" - and it used to record one anyway.
    Measured 2026-09-12 during the DRILL-G1 production run: four `plan`/`apply` invocations left four
    rows, three of them rehearsals, and `governance divergence` went from 1 pending to 5.  Ten quiet
    rehearsals would carry Pre-A′'s only falsifier to its quorum of 10 without a decision being made -
    the same shape found on `family_gate` the same morning, on the other gate, one command away.
    """
    record_verdict(
        root / VERDICTS,
        kind="admission",
        subject=subject,
        ruling=ALLOW if admission.allowed else REFUSE,
        reasons=admission.reasons,
    )


def _report_admission(admission: Admission) -> None:
    for key, value in sorted(admission.measured.items()):
        click.echo(f"  {key}: {value}", err=True)
    for reason in admission.reasons:
        click.echo(f"  REFUSED {reason}", err=True)


@governance.command("plan")
@click.option("--proposed", required=True, help="Path to the candidate registry YAML.")
@click.option("--registry", "registry_path", default=REGISTRY, show_default=True)
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--candidate", default="", help="Which candidate this change is for; recorded in the log.")
@click.option("--root", default=".", help="Checkout holding the governance state and transaction log.")
@click.option("--state-dir", default=".starquant/live", show_default=True, help="The armed loop's record.")
@click.option("--shadow-dir", default=".starquant/live-shadow", show_default=True, help="The canary's record.")
def plan_cmd(
    proposed: str, registry_path: str, profile: str, candidate: str, root: str, state_dir: str, shadow_dir: str
) -> None:
    """What `apply` would do, asked of the same gate, without touching the file."""
    admission = _admission(
        registry_path, Path(proposed).read_text(encoding="utf-8"), Path(root).resolve(), state_dir, shadow_dir
    )
    click.echo(
        f"admission: {'ALLOWED' if admission.allowed else 'REFUSED'} "
        f"(promoting: {', '.join(admission.promoting) or 'nothing'})",
        err=True,
    )
    _report_admission(admission)
    # No `_log_admission` here: a dry run is not a ruling.  See that function's docstring.
    transaction = plan_transaction(
        Path(registry_path),
        Path(proposed).read_text(encoding="utf-8"),
        gate=_gate(profile),
        candidate=candidate or Path(proposed).name,
    )
    click.echo(json.dumps(json.loads(transaction.to_json()), indent=2, ensure_ascii=False))
    if transaction.reasons or not admission.allowed:
        raise SystemExit(1)


@governance.command("reopen")
@click.option("--root", default=".", help="Checkout holding the list, the live record and the data store.")
@click.option("--state-dir", default=".starquant/live", show_default=True, help="Live record, for the facts.")
@click.option("--data-root", default=".starquant/data", show_default=True, help="Data store, for the columns.")
@click.option("--all", "show_all", is_flag=True, help="Include RESOLVED entries.")
def reopen_cmd(root: str, state_dir: str, data_root: str, show_all: bool) -> None:
    """Which closed hypotheses could be looked at again - the thirteen 「重开条件」 with a reader.

    They were written carefully and read by nothing: a full-tree grep for `REFUTED` and `reopen` across
    the governance package returned zero before 2026-09-10.  So a hypothesis whose reopen condition had
    come true stayed closed by neglect rather than by evidence.

    Nine of the thirteen cannot be asked of a machine and are reported as NEEDS A PERSON, counted in the
    summary every time.  This command reopens nothing; reopening is a named ruling, and a command that
    could do it on its own would be the thing R10 forbids.
    """
    from starquant_governance.reopen import LIST, load, render, survey

    checkout = Path(root).resolve()
    entries = load(checkout / LIST)
    hidden = 0
    if not show_all:
        kept = [entry for entry in entries if entry.check != "resolved"]
        hidden = len(entries) - len(kept)
        entries = kept

    equity = None
    heartbeat = checkout / state_dir / "heartbeat.json"
    if heartbeat.exists():
        try:
            equity = json.loads(heartbeat.read_text(encoding="utf-8")).get("equity")
        except ValueError:
            equity = None
    if equity is None:
        # The heartbeat is overwritten by a SKIPPED restart row, which carries no equity.  Fall back to
        # the append-only record rather than reporting "no equity" an hour after every restart.
        cycles = checkout / state_dir / "cycles.jsonl"
        if cycles.exists():
            for line in reversed(cycles.read_text(encoding="utf-8").splitlines()):
                try:
                    value = json.loads(line).get("equity")
                except ValueError:
                    continue
                if isinstance(value, int | float):
                    equity = float(value)
                    break

    store = checkout / data_root
    columns = {
        name
        for name, probe in (
            ("oi", "metrics"),
            ("lsr", "metrics"),
            ("basis", "spot_klines"),
            # `index` / `onchain` / `macro` rows dropped 2026-09-16 with those feeds; no condition asked
            # for them.  `liquidations` stays though its ingest went too: this probe asks the DISK, and
            # regime-47's question is whether the data exists, not whether we can fetch it.
            ("liquidations", "liquidations"),
        )
        if (store / probe).is_dir() and any((store / probe).iterdir())
    }

    click.echo(render(survey(entries, {"equity": equity, "columns": columns, "now": datetime.now(UTC)}), hidden))


@governance.command("window")
@click.option("--root", default=".", help="Checkout holding the queue.")
def window_cmd(root: str) -> None:
    """Construction changes waiting for a batch window - §8's Phase 4a list, which never existed.

    "块 4 必改项一次改完" presumes a list of construction changes applied together in one window.  Each
    was decided in a log entry, the log has no reader, and so on the day a window opens nothing tells
    anybody what it was supposed to carry.  Same shape as the thirteen reopen conditions, pointed the
    other way: not a closed hypothesis nobody reopens, but an open decision nobody applies.

    Applies nothing.  A window is an operator running `governance apply` through a transaction, and a
    command that could apply its own queue on a date is the shape R10 forbids.
    """
    from starquant_governance.window_changes import LIST as WINDOW_LIST
    from starquant_governance.window_changes import load as load_window
    from starquant_governance.window_changes import render as render_window
    from starquant_governance.window_changes import survey as survey_window

    changes = load_window(Path(root).resolve() / WINDOW_LIST)
    click.echo(render_window(survey_window(changes, datetime.now(UTC))))


@governance.command("gate")
@click.option("--registry", "registry_path", default=REGISTRY, show_default=True)
@click.option("--root", default=".", help="Checkout to read the trials ledger and reports from.")
@click.option("--check", is_flag=True, help="Exit non-zero if any running strategy fails at today's N.")
def gate_cmd(registry_path: str, root: str, check: bool) -> None:
    """R0 recomputed at today's bucket size - §3's third condition on `probe -> main`.

    The gate is `max_sharpe_quantile(N, variance, alpha)` and N is the strategy's ledger bucket, which
    is append-only.  So the threshold a strategy was adopted against is not the one it faces today, and
    §3 says a probe may only reach main if it still clears the recomputed one.  That condition had no
    branch in the state machine and no producer anywhere until 2026-09-09.

    Everything except N is held at the values the evidence report recorded, including the annualisation
    scale, which is backed out of the report's own threshold/quantile pair.  Any movement here is
    therefore attributable to the denominator and to nothing else - which is the honest form of
    "searching more demotes your own incumbents".

    It changes no BOOK - it retires nothing, promotes nothing, and touches neither the registry nor the
    state machine - but it is not read-only, and the word used to say it was.  Every PASS/FAIL reading
    appends a `family_gate` row to `governance/verdicts.jsonl`, which is the point: a gate that decided
    and left no record is a gate nobody can audit.  Corrected 2026-09-14 after a session ran this as a
    "read-only check" on the strength of the old first line and appended a row it had not intended.
    Same shape as 2026-09-08's "a command that claims not to charge is charging" - a docstring that
    contradicts its own code is a defect whoever reads it next inherits.

    Before deleting the write to make the word true again: the duplicate problem it looks like was
    already solved on 2026-09-12, the other way round.  A ruling is `(gate, subject, call, reasons)`
    and re-reading an unchanged one collapses on read, so running this twice does not put two rows into
    M-G05's denominator; idempotence was keyed on the DATE until then, which left the hole one day wide.
    `tests/governance/test_a_reread_of_a_ruling_is_not_a_second_verdict.py` carries that history - and
    calls this command "a read-only command" in the course of fixing it, which is where the phrase in
    the two corrected sentences above came from.  The reasons carry the numbers, so a gate whose N moved
    IS a new ruling and correctly lands its own row; the row written on 2026-09-14 is one of those, not
    a stray.

    What it does not do stays true after the merge that gave `lifecycle.apply` a production caller.
    A FAIL is an event for the state machine, and `governance advance` is what folds events into
    `governance_state.json` - this command only writes the `refuse` row that `family_gate.refusals`
    turns into `FAMILY_GATE_FAILED`, and moves nothing itself.  Until 2026-09-23 this sentence said the
    event went `-> retired`; nothing produced it, so the 09-19 refusal of tsmom had no consequence, and
    the operator then ruled main -> probe instead.  Before that it said `lifecycle.apply` had no
    production caller at all; that was true in the branch this command was written in and false the
    moment `advance` landed beside it, which is why it is corrected rather than quietly deleted.
    """
    checkout = Path(root).resolve()
    registry = parse_registry(load_yaml(registry_path))
    ledger = resolve_ledger_path(root=checkout)
    lines = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []

    def read_report(path: str) -> dict[str, Any]:
        # The local is here for its annotation: `json.loads` hands back `Any` and `warn_return_any` will
        # not let that out of a `-> dict[str, Any]`.  No isinstance guard on purpose - unlike
        # `config.read_report` this one must not turn an unreadable report into `{}`; `recheck` renders
        # OSError/ValueError as UNREADABLE with the error text, and anything else should stay loud.
        payload: dict[str, Any] = json.loads((checkout / path).read_text(encoding="utf-8"))
        return payload

    readings = recheck_gate(
        registry, read_report, lines, range_end_granularity_days=Policy().trial_range_end_granularity_days
    )
    for reading in readings:
        click.echo(f"{reading.status:10s} {reading.strategy:22s} {reading.why}")
    for reading in readings:
        # UNREADABLE is not a ruling: the gate did not decide, it failed to ask.  Recording it as a
        # REFUSE would put "we could not read the evidence" into a denominator about judgement.
        if reading.status in ("PASS", "FAIL"):
            record_verdict(
                checkout / VERDICTS,
                kind=VERDICT_KIND,
                subject=reading.strategy,
                ruling=ALLOW if reading.passes else REFUSE,
                reasons=(reading.why,),
            )
    failed = gate_failures(readings)
    unreadable = [r for r in readings if r.status == "UNREADABLE"]
    click.echo(
        f"{len(readings)} strategies: {len(readings) - len(failed) - len(unreadable)} pass, "
        f"{len(failed)} fail, {len(unreadable)} unreadable (ledger {ledger})"
    )
    if check and failed:
        raise SystemExit(1)


@governance.command("verdicts")
@click.option("--root", default=".", help="Checkout holding the verdict ledger.")
@click.option("--since", "since_at", default="", help="Only verdicts at or after this ISO instant.")
@click.option("--pending", is_flag=True, help="Only the ones still waiting for a human review.")
def verdicts_cmd(root: str, since_at: str, pending: bool) -> None:
    """M-G05's raw material: every machine ruling, and whether a person has reviewed it."""
    rows = read_verdicts(Path(root).resolve() / VERDICTS)
    if since_at:
        rows = verdicts_since(rows, since_at)
    if pending:
        rows = [row for row in rows if row.pending]
    for row in sorted(rows, key=lambda r: r.at):
        mark = "PENDING " if row.pending else f"{row.review.upper():8s}"
        click.echo(f"{row.id}  {row.at[:19]}  {row.kind:12s} {row.ruling:7s} {mark} {row.subject}")
        for reason in row.reasons:
            click.echo(f"                              {reason}")
        if row.review_why:
            click.echo(f"                          why: {row.review_why}")
    click.echo(f"{len(rows)} verdicts, {sum(1 for r in rows if r.pending)} awaiting review")


@governance.command("review")
@click.argument("identifier")
@click.option("--agree/--disagree", "agrees", required=True, help="Does the reviewer back the ruling?")
@click.option("--why", required=True, help="Why.  A review without one is not a review.")
@click.option("--root", default=".", help="Checkout holding the verdict ledger.")
def review_cmd(identifier: str, agrees: bool, why: str, root: str) -> None:
    """The human half of M-G05.  Append-only: the original ruling stays on the record."""
    from starquant_governance.verdicts import AGREE, DISAGREE

    try:
        updated = review_verdict(Path(root).resolve() / VERDICTS, identifier, AGREE if agrees else DISAGREE, why)
    except (KeyError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"{updated.id}  {updated.kind} {updated.ruling} -> {updated.review}: {updated.review_why}")


@governance.command("divergence")
@click.option("--root", default=".", help="Checkout holding the verdict ledger.")
@click.option("--since", "since_at", default="", help="Period start (ISO).  §11 asks for a quarter.")
@click.option("--check", is_flag=True, help="Exit non-zero when M-G05 asks for a rule-version review.")
def divergence_cmd(root: str, since_at: str, check: bool) -> None:
    """M-G05 - and Pre-A′'s only falsifier, which had no instrument of any kind until 2026-09-10.

    Not a substitute for `governance replay`.  Replay asks whether the rules reproduce decisions people
    already took (M-G02, backward, against a fixed record).  This asks whether people agree with the
    rulings the machine is making now.  A rule set fitted to a history can reproduce all of it and still
    be wrong about the next one.
    """
    rows = read_verdicts(Path(root).resolve() / VERDICTS)
    if since_at:
        rows = verdicts_since(rows, since_at)
    result = divergence(rows)
    click.echo(f"M-G05  {result.why()}")
    click.echo(f"       {result.pending} pending review")
    for kind, (seen, disagreed) in sorted(result.by_kind.items()):
        click.echo(f"       {kind:14s} {disagreed}/{seen} disagreed")
    if result.triggers_review:
        click.echo("       -> §11: rule version review", err=True)
    if check and result.triggers_review:
        raise SystemExit(1)


@governance.command("canary")
@click.option("--shadow-dir", default=".starquant/live-shadow", show_default=True, help="The soak's state directory.")
@click.option("--state-dir", default=".starquant/live", show_default=True, help="The armed loop, as the baseline.")
@click.option("--gate-refusals", default=0, show_default=True, help="Startup-gate refusals the soak itself saw.")
def canary_cmd(shadow_dir: str, state_dir: str, gate_refusals: int) -> None:
    """L4 / DL-G5: score a finished shadow soak against the armed loop over the same window.

    The soak is `deploy/run_shadow.sh`; this is the half that reads it.  Until 2026-09-09 there was no
    such half: the module computing the checks had no caller outside its own tests, so §3's
    `Canary 健康检查过` was a precondition nothing could ever satisfy or refuse.

    Deployment health only (KILL-AR-04).  A candidate that passes has been shown to deploy, not to
    have edge; a candidate that fails has hit a wiring or venue problem, and reading that as evidence
    against the sleeve is the mistake this command's own docstring exists to prevent.
    """
    shadow = _shadow_rows(shadow_dir)
    baseline = _rows(Path(state_dir) / "cycles.jsonl")
    if not shadow:
        looked = store_directory(Path(shadow_dir), dry_run=True)
        raise click.ClickException(f"no shadow record at {looked}/cycles.jsonl; run deploy/run_shadow.sh first")
    result = evaluate_canary(shadow, baseline, gate_refusals=gate_refusals, aliases=CONSTRUCTION_ALIASES)
    for check in result.checks:
        click.echo(f"{'PASS' if check.passed else 'FAIL'}  {check.name:22s} {check.detail}")
    click.echo(f"{'HEALTHY' if result.healthy else 'UNHEALTHY'}  {result.soaked} cycles soaked")
    if not result.healthy:
        raise SystemExit(1)


@governance.command("enable")
@click.option("--root", default=".", help="Checkout to write the switch into.")
@click.confirmation_option(prompt="Allow the machine to write config/alpha_registry.yaml on its own?")
def enable_cmd(root: str) -> None:
    """Turn on autonomous registry writes.  A human confirmation point, taken once (§0)."""
    path = _switch(Path(root).resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"enabled {datetime.now(UTC).isoformat()}\n", encoding="utf-8")
    click.echo(f"autonomy ENABLED ({path})")


@governance.command("disable")
@click.option("--root", default=".", help="Checkout to remove the switch from.")
def disable_cmd(root: str) -> None:
    """Turn off autonomous registry writes.  Never confirmed: stopping is always allowed."""
    path = _switch(Path(root).resolve())
    path.unlink(missing_ok=True)
    click.echo(f"autonomy DISABLED ({path})")


@governance.command("apply")
@click.option("--proposed", required=True, help="Path to the candidate registry YAML.")
@click.option("--registry", "registry_path", default=REGISTRY, show_default=True)
@click.option("--profile", default="config/live.demo.yaml", show_default=True)
@click.option("--candidate", default="", help="Which candidate this change is for; recorded in the log.")
@click.option("--root", default=".", help="Checkout holding the switch and the transaction log.")
@click.option("--state-dir", default=".starquant/live", show_default=True, help="The armed loop's record.")
@click.option("--shadow-dir", default=".starquant/live-shadow", show_default=True, help="The canary's record.")
@click.option("--actor", default="machine", show_default=True, help="Who initiated this; recorded in the log.")
def apply_cmd(
    proposed: str,
    registry_path: str,
    profile: str,
    candidate: str,
    root: str,
    state_dir: str,
    shadow_dir: str,
    actor: str,
) -> None:
    """Write the registry as a transaction, rolling back if the startup gate refuses.

    Refused while the autonomy switch is off.  Q9 removed the confirmation point from a SINGLE
    promotion, not from the decision to let the machine write at all - that one is taken once, by a
    person, and `governance disable` takes it back without confirmation because stopping always may.
    """
    checkout = Path(root).resolve()
    if not _switch(checkout).exists():
        raise click.ClickException(
            f"autonomy is disabled ({_switch(checkout)} does not exist).  `starquant governance enable` "
            "turns it on; `governance plan` shows what this would do without it."
        )
    text = Path(proposed).read_text(encoding="utf-8")
    admission = _admission(registry_path, text, checkout, state_dir, shadow_dir)
    _log_admission(checkout, admission, candidate or Path(proposed).name)
    if not admission.allowed:
        _report_admission(admission)
        raise click.ClickException(
            "the governance rules refuse this change; `governance plan` shows the same reasons without "
            "writing.  Loosening a rule to admit a change is R10's whole subject - the thresholds live "
            "in policy.py and move with a version, a test and a pre-registration."
        )
    transaction = apply_transaction(
        Path(registry_path),
        text,
        gate=_gate(profile),
        log_path=checkout / TRANSACTIONS,
        candidate=candidate or Path(proposed).name,
        actor=actor,
    )
    click.echo(json.dumps(json.loads(transaction.to_json()), indent=2, ensure_ascii=False))
    if transaction.action == "ROLLBACK":
        raise SystemExit(1)
    if transaction.restart_required:
        click.echo("restart required: the engine builds its model at startup (KILL-Q15)", err=True)


@governance.command("next")
@click.option("--root", default=".", help="Checkout holding the reports, the ledger and the state.")
@click.option("--reports", "reports_dir", default="reports/research", show_default=True)
@click.option("--daily", "daily_dir", default="reports/daily", show_default=True, help="Where M-011's parity lands.")
@click.option("--anchor", default=WINDOW_ANCHOR, show_default=True, help="The batch calendar R1 counts a window on.")
@click.option("--wanted", default=1, show_default=True, help="Trials the next `research validate` would charge.")
@click.option("--check", is_flag=True, help="Exit non-zero when there is something to do (for a `deploy/` timer).")
def next_cmd(root: str, reports_dir: str, daily_dir: str, anchor: str, wanted: int, check: bool) -> None:
    """DL-G8: what the research loop does next, assembled from the artefacts.  Decides; does nothing.

    `scheduler.next_action` has been a pure function with no caller since it was written, which is why
    it and `budget` were both in the reachability guard's EXEMPT list.  This is the assembler, and its
    real work is the fields it CANNOT read: every one of them is a count whose branch is `> 0`, so a
    default of 0 does not error, it answers - one step further down the pipeline than the evidence
    supports.  Each field prints its source, an unreadable one prints why, and `conclude` asks whether
    the answer would have differed had it read the other way.  If it would, the answer is WAIT.

    Read-only, and it touches `.starquant/live` nowhere: `scheduler`'s own docstring forbids that, because
    a research run whose timing depends on what the book is doing is not a schedule.  The one live
    artefact it will read is `reports/daily/*.json`, which is a written report rather than live state.
    """
    checkout = Path(root).resolve()
    policy = Policy()
    ledger = resolve_ledger_path(root=checkout)
    if not ledger.exists():
        raise click.ClickException(
            f"no trials ledger at {ledger}: R1 cannot be asked.  A budget that reads an absent ledger "
            "as 'nothing spent' is the empty-book failure again - permissive, not conservative."
        )
    opened = window_start(policy, anchor=anchor)
    ledger_lines = ledger.read_text(encoding="utf-8").splitlines()
    budget = window_spend(ledger_lines, window_start=opened, policy=policy)

    directory = checkout / reports_dir
    shortlists = sorted(directory.glob("mine-shortlist-*.json"))
    shortlist = json.loads(shortlists[-1].read_text(encoding="utf-8")) if shortlists else None
    # M-011's status is not a research artefact: `starquant report daily` computes it against the live
    # universe and the data root, and a research machine has neither.  Read where it lands rather than
    # recomputed, so this command keeps its promise not to touch live state.
    daily = sorted((checkout / daily_dir).glob("*.json"))
    parity = json.loads(daily[-1].read_text(encoding="utf-8")).get("metrics_parity") if daily else None
    if not daily:
        parity_source = f"no daily report under {daily_dir}; `starquant report daily` is what writes M-011"
    elif not isinstance(parity, dict):
        parity_source = f"{daily[-1].name} carries no `metrics_parity` block"
    else:
        parity_source = f"{daily[-1].name}.metrics_parity"

    assembly = assemble(
        shortlist=shortlist,
        shortlist_name=shortlists[-1].name if shortlists else "(none)",
        reports=_payloads(directory),
        book=read_state(checkout / STATE),
        budget=budget,
        budget_source=f"{ledger.name} since {opened.isoformat()}",
        parity=parity if isinstance(parity, dict) else None,
        parity_source=parity_source,
        wanted_trials=wanted,
        # R2b reads the WHOLE file, not the window's share of it: the D-028 denominator is the family's
        # lifetime count, and `budget.mined_rows` is deliberately window-scoped.  Handed as lines rather
        # than a count because `family_gate.read_gate` derives N per strategy through `ledger_scope`.
        ledger_lines=ledger_lines,
        ledger_source=f"{ledger.name} whole file",
    )
    said, action = conclude(assembly, policy)

    click.echo(f"policy   {policy.version} digest={policy.digest()} window={policy.window_days}d anchor={anchor}")
    click.echo(
        f"budget   R1 {budget.spent}/{budget.allowed} rows, {budget.mine_rounds}/{budget.allowed_mine_rounds} "
        f"mine rounds ({budget.mined_rows} mined rows reported, never charged)"
    )
    for field in assembly.fields:
        if field.name == "budget":
            continue
        click.echo(f"  {'?' if not field.known else ' '} {field.name:24s} {field.value!s:20s} {field.source}")
    click.echo(f"scheduler {said.kind.upper()}  {'; '.join(said.reasons)}")
    if action != said:
        click.echo(f"next      {action.kind.upper()}  {'; '.join(action.reasons)}")
    if check and action.kind != WAIT:
        raise SystemExit(1)


#: How many times `advance` re-derives one book's tenure.  `tenure` stops at the first counted stop
#: and its docstring hands the continuation back to the caller, because what follows a stop is a
#: different tenure - a stopped main returns to probe and keeps counting windows.  Bounded rather than
#: `while True` so a record that somehow reports a stop at the same instant forever cannot hang a job.
MAX_TENURES = 8


def _after(at: str, watermark: str) -> bool:
    """Is this event later than what the candidate has already absorbed?

    Parsed rather than compared as text: `tenure` stamps a survived window with the window's CLOSE
    (`datetime.isoformat()`) and a stop with the cycle's own `at`, and two ISO strings that mean the
    same instant can differ as text.  An unparseable pair falls back to string order, which is the
    only remaining option and is at least deterministic.
    """
    if not watermark:
        return True
    try:
        return datetime.fromisoformat(at) > datetime.fromisoformat(watermark)
    except ValueError:
        return at > watermark


def _fold(book: Book, strategy: str, event: Derived, passes: bool, policy: Policy) -> tuple[Book, str]:
    """One derived event through `lifecycle.apply`, then the watermark, whatever the rules answered.

    The watermark moves on a REFUSED event too.  That is the point of it being a watermark rather than
    a to-do list: the record produced the event once, the rules answered once, and replaying a refusal
    every run would eventually apply it against a state that has since moved.
    """
    candidate = book.candidates[strategy]
    if not _after(event.at, candidate.folded_through):
        return book, f"already folded (watermark {candidate.folded_through})"
    book, decision = apply_event(book, strategy, event.event, Facts(family_gate_still_passes=passes), policy)
    updated = replace(book.candidates[strategy], folded_through=event.at)
    book = replace(book, candidates={**book.candidates, strategy: updated})
    return book, f"{'->' if decision.allowed else 'x '} {decision.state.value}  {'; '.join(decision.reasons)}"


@governance.command("advance")
@click.option("--root", default=".", help="Checkout holding the governance state, the registry and the ledger.")
@click.option("--cycles", default=".starquant/live/cycles.jsonl", show_default=True, help="The append-only record.")
@click.option("--registry", "registry_path", default=REGISTRY, show_default=True)
@click.option("--anchor", default=WINDOW_ANCHOR, show_default=True, help="The batch calendar, global to all sleeves.")
@click.option("--started", help="ISO start for one sleeve, as book=ISO; repeatable.", multiple=True)
@click.option("--commit/--dry-run", default=False, help="Write the state.  A dry run is the default.")
def advance_cmd(
    root: str, cycles: str, registry_path: str, anchor: str, started: tuple[str, ...], commit: bool
) -> None:
    """Fold what the record already did into `governance_state.json` - the write side of §3.

    `lifecycle.apply` and `state.write` had no production caller, so `governance_state.json` was
    maintained by hand (`git log` shows one commit) and R4's `promotions_this_window`, R5's
    `consecutive_probe_stops` and R7's `probe_entries` were typed numbers.  `governance tenure`
    already derived the events from `cycles.jsonl`; nothing folded them anywhere.

    **Idempotence is the whole difficulty**, and worth naming precisely, because the counter usually
    cited is not the one at risk here.  R7's `probe_entries` moves on `queued -> probe`, and no event
    this command derives produces that edge - it is `governance apply`'s.  What a second fold of the
    same record moves is `windows_survived`, which would reach main in four and a half windows instead
    of §3's nine, and `consecutive_probe_stops`, where one stop counted twice is R5's two and freezes
    promotion for six windows.  R7 is then reachable at one remove: a probe demoted by a stop it only
    took once spends a life when it is promoted back.  It is held by a per-candidate watermark
    (`folded_through`) that
    stores the instant of the last event absorbed - state, not derivation, because the derivation is
    deliberately stateless and re-reads the whole record every run.  Note which half is which: the
    events are re-derived every time, including the ones already folded, and only the FOLD is skipped.
    That is why a stop still ends a tenure on a second run even though it is not applied again.

    This never touches the registry, so it never changes what the loop trades.  A `probe -> main` here
    records that §3's conditions were met; moving the exposure is `governance apply`, past `admission`,
    and a restart.  The same holds the other way: a main sent back to probe keeps trading as it did.

    `FAMILY_GATE_FAILED` is the one event not read off `cycles.jsonl`: `governance gate` writes a
    `refuse` row, `family_gate.refusals` turns it into an event at the ruling's instant, and it folds
    in time order with the tenure's own events (operator ruling 2026-09-23: main -> probe).
    """
    checkout = Path(root).resolve()
    policy = Policy()
    record = Path(cycles)
    if not record.exists():
        raise click.ClickException(f"no live record at {record}")
    rows = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line.strip()]

    state_path = checkout / STATE
    before = read_state(state_path)
    if not before.candidates:
        raise click.ClickException(
            f"{state_path} carries no candidates.  An empty book is HEADROOM, not safety (see "
            "`state.load`), and folding a record into one would invent the sleeves it names.  Seed the "
            "running sleeves first - KILL-AR-06 is why they are in the file."
        )
    book, window_why = rolled(before, policy, anchor=anchor)
    click.echo(f"window   {window_why}")

    ledger = resolve_ledger_path(root=checkout)
    lines = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    readings = {
        reading.strategy: reading
        for reading in recheck_gate(
            parse_registry(load_yaml(registry_path)),
            lambda path: json.loads((checkout / path).read_text(encoding="utf-8")),
            lines,
            range_end_granularity_days=Policy().trial_range_end_granularity_days,
        )
    }
    for reading in readings.values():
        click.echo(f"gate     {reading.status:10s} {reading.strategy:20s} {reading.why}")

    verdicts = read_verdicts(checkout / VERDICTS)
    starts = dict(pair.split("=", 1) for pair in started if "=" in pair)
    for name in books_in(rows):
        at = starts.get(name, anchor)
        announced = False
        pending: list[Derived] | None = None
        for _round in range(MAX_TENURES):
            result = tenure(rows, book=name, started_at=at, window_anchor=anchor, policy=policy)
            strategy = result.strategy or name
            if not announced:
                held = book.candidates.get(strategy)
                click.echo(
                    f"{name:16s} -> {strategy:16s} "
                    + (
                        f"{held.state.value:10s} folded through {held.folded_through or '(never)'}"
                        if held is not None
                        else "NOT IN THE STATE: refusing to invent a candidate the file does not carry"
                    )
                )
                announced = True
            if strategy not in book.candidates:
                break
            if pending is None:
                pending = list(refusals(verdicts, strategy))
            # A refusal folds in the tenure whose span holds its instant, sorted in among that tenure's
            # events: folded after a later window instead, the watermark would already be past it.
            end = datetime.fromisoformat(result.stopped_at) if result.stopped_at else None
            due = [e for e in pending if end is None or datetime.fromisoformat(e.at) <= end]
            pending = pending[len(due) :]
            for event in sorted([*result.events, *due], key=lambda e: datetime.fromisoformat(e.at)):
                # UNREADABLE and FAIL are both False here, and they are different operator actions -
                # which is why the gate's own line is printed above rather than folded into this one.
                passes = strategy in readings and readings[strategy].passes
                book, said = _fold(book, strategy, event, passes, policy)
                click.echo(f"    {event.at}  {event.event.value:15s} {said}")
            for skip in result.skipped:
                click.echo(f"    {skip.at}  {'(not counted)':15s} {skip.why}")
            if result.stopped_at is None:
                break
            # A stop ends one tenure and starts another (`tenure`'s docstring).  Advanced past the
            # stop's own instant rather than to it, or the next pass derives the same stop forever.
            at = (datetime.fromisoformat(result.stopped_at) + timedelta(microseconds=1)).isoformat()

    if book == before:
        click.echo("the state already matches the record; nothing to write")
        return
    if not commit:
        click.echo(f"dry run: nothing written.  `--commit` writes {state_path}")
        return
    write_state(state_path, book)
    click.echo(f"wrote {state_path}")
