"""Where `scheduler.Context` comes from, field by field, with "I could not read this" as an answer.

`scheduler.next_action` is a pure function of a `Context` and it had no assembler, which is why
`scheduler` and `budget` were both sitting in the reachability guard's EXEMPT list: 227 lines of R1
and DL-G8 that no command could run.  This module is the missing half.

The whole difficulty is in the fields that cannot be read.  Every one of them is a COUNT whose branch
in the scheduler is `> 0`, so an unreadable field defaulted to 0 does not produce an error - it
produces a confident answer, one step further down the pipeline than the evidence supports.  That is
the same defect as an empty `governance_state.json` reading as headroom, and it is the reason this
module returns `Field`s rather than a bare `Context`: the value the scheduler is handed, and the
sentence saying where it came from, travel together.

An unknown field is placed at its conservative value (0 for a count, "unchanged" for the space
digest) AND named.  `load_bearing` then asks the only question that matters about it: with the same
context and this one field moved to its other reading, does the scheduler still say the same thing?
The scheduler's branches are four `> 0` tests and one equality, so "the other reading" is a finite
set and the question has an exact answer rather than a heuristic one.  A field that could not change
the answer is reported and ignored; a field that could turns the answer into WAIT, carrying the
reason - which is what `scheduler`'s own docstring promises WAIT always does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from starquant_alpha.mining import enumerate_candidates
from starquant_governance.budget import LedgerBudget
from starquant_governance.family_gate import FAIL as GATE_FAIL
from starquant_governance.family_gate import PASS as GATE_PASS
from starquant_governance.family_gate import read_gate
from starquant_governance.lifecycle import Book, State
from starquant_governance.policy import Policy
from starquant_governance.scheduler import WAIT, Action, Context, next_action, parity_satisfied

#: How far along §3's pipeline each state already is.  Used only to subtract: a candidate the state
#: already carries at `booked` is not work the scheduler should schedule again, and `retired` ranks
#: highest because R7 makes it absorbing.
#: The `ledger_source` a caller that did not pass one leaves behind, so `known` can tell "the bucket is
#: empty" (a reading) from "nobody told me" (not one).  A sentinel rather than `None` because the field
#: is a SENTENCE that gets printed either way.
NOT_SUPPLIED = "not supplied"

RANK: dict[State, int] = {
    State.CANDIDATE: 0,
    State.VALIDATED: 1,
    State.BOOKED: 2,
    State.QUEUED: 3,
    State.PROBE: 4,
    State.MAIN: 5,
    State.RETIRED: 6,
}

#: The `enumerate_candidates` arguments a shortlist report records, and which therefore have to be
#: replayed to compare today's space against the one that round enumerated.  `grids` is handled
#: separately because it is a mapping of further arguments rather than one of them.
KNOBS = ("max_complexity", "max_lookback", "include_funding", "include_basis")


@dataclass(frozen=True)
class Field:
    """One `Context` field, the value handed to the scheduler, and where that value came from.

    `known` is not `value is not None`: a count that could not be read is still handed over as 0,
    because `Context` has no third state and inventing one would put "unknown" inside the rules.
    """

    name: str
    value: Any
    source: str
    known: bool = True


@dataclass(frozen=True)
class Assembly:
    context: Context
    fields: tuple[Field, ...]

    @property
    def unknown(self) -> tuple[Field, ...]:
        return tuple(field for field in self.fields if not field.known)

    def source(self, name: str) -> str:
        return next((field.source for field in self.fields if field.name == name), "")


def newest(reports: Mapping[str, Mapping[str, Any]], kind: str, key: str) -> dict[str, Mapping[str, Any]]:
    """The newest report of one kind per strategy, keyed on `key` read out of the payload.

    Newest by `generated_at` rather than by filename, falling back to the name.  It matters that this
    is newest-wins rather than ever-passed: `tsmom` carries FAIL, WEAK_PASS and PASS reports, and a
    rule that took the best of them would let a superseded verdict decide.
    """
    best: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for name, payload in sorted(reports.items()):
        if str(payload.get("kind", "")) != kind:
            continue
        target = payload
        for part in key.split("."):
            target = target.get(part) if isinstance(target, Mapping) else None  # type: ignore[assignment]
            if target is None:
                break
        strategy = str(target or "")
        if not strategy:
            continue
        stamp = str(payload.get("generated_at") or name)
        if strategy not in best or stamp > best[strategy][0]:
            best[strategy] = (stamp, payload)
    return {strategy: payload for strategy, (_stamp, payload) in best.items()}


def shortlisted(payload: Mapping[str, Any]) -> tuple[tuple[str, ...], str]:
    """The ids one mine round actually put forward, or the reason they cannot be named.

    A shortlist report holds EVERY candidate the search scored, not the shortlist: the shortlist is
    the top `run.top` of them by `run.ranked_by`, and both live in the run block.  Rows carrying an
    `error` are excluded before ranking - 90 of the last round's 658 errored, and ranking them by a
    score they do not have would silently seat nine of them at the top.
    """
    run = payload.get("run")
    if not isinstance(run, Mapping):
        return (), "the report carries no `run` block, so `top` and `ranked_by` are unknown"
    ranked_by, top = run.get("ranked_by"), run.get("top")
    if not isinstance(ranked_by, str) or not isinstance(top, int):
        return (), f"the run block records ranked_by={ranked_by!r} top={top!r}"
    rows = [row for row in (payload.get("candidates") or []) if isinstance(row, Mapping) and "error" not in row]
    scored = [row for row in rows if isinstance(row.get(ranked_by), int | float)]
    best = sorted(scored, key=lambda row: float(row[ranked_by]), reverse=True)[:top]
    return tuple(f"mined_{row['hash']}" for row in best if row.get("hash")), f"top {top} by {ranked_by}"


def reconstruct_space(shortlist: Mapping[str, Any] | None, name: str) -> tuple[str | None, str]:
    """Today's space at the knobs the last round recorded - or None, and why it cannot be compared.

    R2 asks whether the space CHANGED, so both digests have to be taken at the same knobs.  Reading
    today's at the bare defaults would answer "changed" every time the last round narrowed the space,
    and `research mine` narrows it routinely: `include_basis` is `panel.spot_symbols > 0`, which is
    False on every panel this repository can build today.

    A knob the report does not record is taken at the function's own default and SAID.  If the digest
    then disagrees with the recorded one, the field is unknown rather than "changed": with a knob
    guessed, "the space widened" and "the guess was wrong" produce the same disagreement, and telling
    a research machine to spend a mine round on that is exactly the confident wrong answer this
    module exists to refuse.  Measured 2026-09-10 - every shortlist in the repo predates
    `run.include_basis`, so today this reads UNKNOWN and R2 cannot be asked at all.
    """
    if not isinstance(shortlist, Mapping):
        return None, "no `mine-shortlist-*.json` to take the knobs from"
    run = shortlist.get("run")
    kwargs: dict[str, Any] = {}
    defaulted: list[str] = []
    if isinstance(run, Mapping):
        for knob in KNOBS:
            if knob in run:
                kwargs[knob] = run[knob]
            else:
                defaulted.append(knob)
        grids = run.get("grids")
        if isinstance(grids, Mapping):
            kwargs.update(grids)
        else:
            defaulted.append("grids")
    else:
        defaulted = [*KNOBS, "grids"]
    try:
        digest = enumerate_candidates(**kwargs).space_digest
    except TypeError as error:  # a recorded grid key this version of the enumerator no longer has
        return None, f"{name} records a search this enumerator cannot replay: {error}"
    recorded = str(shortlist.get("search_space_digest") or "")
    where = f"enumerate_candidates at {name}'s knobs"
    if not defaulted:
        return digest, where
    missing = ", ".join(defaulted)
    if digest == recorded:
        return digest, f"{where}; {missing} not recorded, defaulted, and the digest still matches"
    return None, (
        f"{name} records no {missing}; at the enumerator's default the space reads {digest} against "
        f"the recorded {recorded or 'nothing'}, so a widened space and a guessed knob are the same "
        "disagreement"
    )


def assemble(
    *,
    shortlist: Mapping[str, Any] | None,
    shortlist_name: str,
    reports: Mapping[str, Mapping[str, Any]],
    book: Book,
    budget: LedgerBudget,
    budget_source: str,
    parity: Mapping[str, Any] | None,
    parity_source: str,
    wanted_trials: int,
    ledger_lines: Sequence[str] = (),
    ledger_source: str = NOT_SUPPLIED,
) -> Assembly:
    """Build the context out of `reports/research/` and `governance_state.json`, saying what came from where."""
    at_least = {name: RANK[candidate.state] for name, candidate in book.candidates.items()}
    digest, digest_source = reconstruct_space(shortlist, shortlist_name)
    last = str(shortlist.get("search_space_digest") or "") if isinstance(shortlist, Mapping) else ""

    fields: list[Field] = [
        # Unknown means "unchanged", not "changed": the scheduler's mine branch fires on inequality,
        # so the placeholder that does NOT spend a round is the one that matches `last`.
        Field("search_space_digest", digest if digest is not None else last, digest_source, digest is not None),
        Field(
            "last_mined_space_digest",
            last,
            f"{shortlist_name}.search_space_digest" if last else f"{shortlist_name} records no digest",
            bool(last),
        ),
    ]

    # R2b.  Both halves come from artefacts: every mined validation on disk, and the bucket's N today.
    # `known` is false when either half is missing, so `load_bearing` gets to ask whether the missing
    # half could have changed the answer instead of this module deciding that it could not.
    mined_validations = {
        name: payload
        for name, payload in newest(reports, "validation", "strategy").items()
        if name.startswith("mined_")
    }
    passed, why = gate_has_passed_the_space(
        mined_validations, ledger_lines, range_end_granularity_days=Policy().trial_range_end_granularity_days
    )
    fields.append(
        Field(
            "mined_gate_passed_best",
            1 if passed else 0,
            f"{why} [{ledger_source}]",
            # Known iff a caller actually supplied the ledger.  NOT "the ledger has mined rows": an
            # empty bucket is a real reading (nothing searched yet, so nothing to be exhausted), while a
            # caller that forgot the argument would read as one - the invisible-default shape, failing
            # PERMISSIVE, letting a round be spent on the strength of an argument nobody passed.
            ledger_source != NOT_SUPPLIED,
        )
    )

    validated = {
        name: str(payload.get("verdict", "")) for name, payload in newest(reports, "validation", "strategy").items()
    }
    booked = {
        name: str(payload.get("book_verdict", ""))
        for name, payload in newest(reports, "book", "sleeve.strategy").items()
    }

    if shortlist is None:
        fields.append(Field("shortlist_candidates", 0, "no `mine-shortlist-*.json` under the reports directory", False))
    else:
        ids, how = shortlisted(shortlist)
        waiting = [i for i in ids if i not in validated and at_least.get(i, 0) < RANK[State.VALIDATED]]
        fields.append(
            Field(
                "shortlist_candidates",
                len(waiting),
                f"{shortlist_name}, {how}, minus {len(ids) - len(waiting)} already validated"
                if ids
                else f"{shortlist_name}: {how}",
                bool(ids),
            )
        )

    unbooked = sorted(
        name
        for name, verdict in validated.items()
        if verdict == "PASS" and name not in booked and at_least.get(name, 0) < RANK[State.BOOKED]
    )
    fields.append(
        Field(
            "validated_unbooked",
            len(unbooked),
            f"PASS validation, no book report, not already booked in the state: {', '.join(unbooked) or 'none'}",
        )
    )

    # `booked` in §3's sense is an ACCEPT book report the candidate has not already left; a REJECT is
    # a candidate that was measured beside the book and refused, which is not a queue it is waiting in.
    accepted = sorted(
        name for name, verdict in booked.items() if verdict == "ACCEPT" and at_least.get(name, 0) < RANK[State.QUEUED]
    )
    if not accepted:
        why = "no ACCEPT book report outside the state's own candidates"
        fields.append(Field("booked_without_parity", 0, why))
        fields.append(Field("parity_met_unqueued", 0, why))
    elif parity is None:
        fields.append(Field("booked_without_parity", 0, parity_source, False))
        fields.append(Field("parity_met_unqueued", 0, parity_source, False))
    else:
        met, why = parity_satisfied(parity)
        fields.append(Field("booked_without_parity", 0 if met else len(accepted), f"{parity_source}: {why}"))
        fields.append(Field("parity_met_unqueued", len(accepted) if met else 0, f"{parity_source}: {why}"))

    fields.append(Field("budget", budget, budget_source))
    fields.append(Field("wanted_trials", wanted_trials, "--wanted; a mined candidate's validation grid is 1"))

    values = {field.name: field.value for field in fields}
    return Assembly(Context(**values), tuple(fields))


def gate_has_passed_the_space(
    validations: Mapping[str, Mapping[str, Any]],
    ledger_lines: Sequence[str],
    *,
    range_end_granularity_days: int,
) -> tuple[bool, str]:
    """Would the best candidate this space ever produced still clear its own gate today?

    R2b's whole content, and it is a MEASUREMENT rather than a threshold: the D-028 gate rises
    monotonically in N, so once it has passed the best out-of-sample Sharpe the space has ever
    produced, a further round cannot produce an admissible candidate - it can only raise the bar.  On
    2026-09-09 that crossing happened and two more rounds ran after it.

    The recomputation is `family_gate.read_gate`, not a second implementation of it.  The first version
    of this function was one, and it was wrong in the way that module's own comment predicts: it read N
    as the bucket count, while `dsr_inputs` builds N as `ledger_trials + grid + declared prior`.  For
    `mined_594a12f9307a15d9` that is 575 = 0 + 1 + 574, so its N today is 575 + the bucket's growth,
    not the bucket - understating the gate by 0.02 and stopping later than it should.  Reusing the
    module that already isolates this variable is also what keeps the annualisation single-sourced.

    "Best" is by out-of-sample Sharpe across every mined validation on disk, not the newest: a later,
    worse candidate must not make the space look exhausted.  UNREADABLE readings hold no opinion and
    are skipped rather than guessed at, the same rule the rest of this module applies to what it cannot
    read.
    """
    readings = [
        read_gate(name, payload, ledger_lines, range_end_granularity_days=range_end_granularity_days)
        for name, payload in validations.items()
    ]
    scored = [r for r in readings if r.status in (GATE_PASS, GATE_FAIL) and r.oos_sharpe is not None]
    if not scored:
        return False, "no mined validation report carries a readable selection block to compare against"
    best = max(scored, key=lambda r: r.oos_sharpe or 0.0)
    verb = "has passed" if best.status == GATE_FAIL else "is still below"
    return best.status == GATE_FAIL, f"the gate {verb} this space's best, {best.strategy}: {best.why}"


def load_bearing(context: Context, policy: Policy, unknown: Sequence[str]) -> tuple[str, ...]:
    """Which of the unreadable fields could have changed the answer, asked rather than assumed.

    Exact rather than approximate, because the scheduler's branches are finite: four `> 0` tests on
    counts and one equality on the space digest.  So each field has exactly two readings, and moving
    it to the other one either changes the action or cannot.  A field that cannot is reported and
    otherwise ignored - most of them, most of the time, which is what keeps the command usable.
    """
    kind = next_action(context, policy).kind
    blind: list[str] = []
    for name in unknown:
        if name == "search_space_digest":
            alternatives: tuple[Any, ...] = (f"not-{context.last_mined_space_digest}",)
        elif name == "last_mined_space_digest":
            alternatives = (f"not-{context.search_space_digest}",)
        else:
            alternatives = (1,) if getattr(context, name) == 0 else (0,)
        if any(next_action(replace(context, **{name: alt}), policy).kind != kind for alt in alternatives):
            blind.append(name)
    return tuple(blind)


def conclude(assembly: Assembly, policy: Policy | None = None) -> tuple[Action, Action]:
    """(what the scheduler said, what may be acted on).  They differ only when a blind field decides.

    The scheduler is a pure function of what it is told, so it is the assembler's job - not its - to
    refuse to act on a fact nobody could read.  Both are returned because the difference between them
    is the interesting part of the output: "VALIDATE, if the thing I could not read is what I guessed".
    """
    policy = policy or Policy()
    said = next_action(assembly.context, policy)
    blind = load_bearing(assembly.context, policy, [field.name for field in assembly.unknown])
    if not blind:
        return said, said
    reasons = tuple(f"{name}: {assembly.source(name)}" for name in blind)
    tail = said.reasons if said.kind == WAIT else (f"the scheduler said {said.kind.upper()} on the placeholder",)
    return said, Action(WAIT, reasons + tail)
