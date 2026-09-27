"""Strategy registry contract (parsed from ``config/alpha_registry.yaml`` by the caller; no I/O here)."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

MAIN_BOOK = "main"
PROBE_VERDICT = "ACCEPT"  # a book-level finding from `research book` (D-018); never a signal-level PASS
# A probe book may also cite a REJECT, but only when the registry says so out loud (D-029): the alternative
# observed on 2026-09-04 was a probe running against a report whose universe no longer existed on disk.
PROBE_VERDICTS: frozenset[str] = frozenset({PROBE_VERDICT, "REJECT"})
# Signal-level verdicts, MOST PERMISSIVE FIRST.  `evidence_problems` admits the first two to live
# use (D-020), so a registry naming one of them makes a claim its cited report has to support.
SIGNAL_VERDICTS: tuple[str, ...] = ("PASS", "WEAK_PASS", "FAIL")


@dataclass(frozen=True)
class BookSpec:
    """An independent sleeve next to the main book, scaled to ``fraction`` of the main risk budget (D-019)."""

    name: str
    fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.name == MAIN_BOOK:
            raise ValueError("the main book is implicit and cannot be declared")
        if not 0 < self.fraction <= 1:
            raise ValueError(f"book {self.name}: fraction must be in (0, 1]")


@dataclass(frozen=True)
class StrategyEntry:
    id: str
    enabled: bool = True
    weight: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] | None = None
    book: str = MAIN_BOOK
    probe: dict[str, Any] | None = None  # explicit operator exception for a probe book (D-019)

    @property
    def entry_threshold(self) -> float:
        return float(self.params.get("entry_threshold", 0.0)) or 1e-9


@dataclass(frozen=True)
class Registry:
    version: int
    ensemble_method: str
    turnover_penalty: float
    strategies: tuple[StrategyEntry, ...]
    books: dict[str, BookSpec] = field(default_factory=dict)  # declared non-main books
    # The traded population, pinned.  Empty means "whatever the pool last ranked", which is what this
    # file meant before 2026-09-09 and what made restartability expire every day: the loop re-ranked at
    # about 01:00Z, `universe.fingerprint` moved, and every cited report - which records the universe it
    # was produced under - stopped describing the population being traded.  Pinning it here makes a
    # re-rank a governed transaction (`starquant governance apply`, logged, rollback-able) instead of a
    # daily side effect, which is what "构造改动进批次窗口" already means for every other such change.
    universe: tuple[str, ...] = ()

    @property
    def enabled(self) -> tuple[StrategyEntry, ...]:
        return tuple(entry for entry in self.strategies if entry.enabled)

    def fraction(self, book: str) -> float:
        return 1.0 if book == MAIN_BOOK else self.books[book].fraction


def parse_registry(payload: Mapping[str, Any]) -> Registry:
    ensemble = payload.get("ensemble", {}) or {}
    books: dict[str, BookSpec] = {}
    for name, raw in (payload.get("books", {}) or {}).items():
        spec = raw if isinstance(raw, Mapping) else {}
        books[str(name)] = BookSpec(name=str(name), fraction=float(spec.get("fraction", 1.0)))
    entries: list[StrategyEntry] = []
    seen: set[str] = set()
    for raw in payload.get("strategies", []) or []:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            raise ValueError("every strategy needs an id")
        identifier = str(raw["id"])
        if identifier in seen:
            raise ValueError(f"duplicate strategy id {identifier}")
        seen.add(identifier)
        evidence = raw.get("evidence")
        probe = raw.get("probe")
        book = str(raw.get("book", MAIN_BOOK) or MAIN_BOOK)
        if book != MAIN_BOOK and book not in books:
            raise ValueError(f"strategy {identifier} refers to undeclared book {book!r}")
        entries.append(
            StrategyEntry(
                id=identifier,
                enabled=bool(raw.get("enabled", True)),
                weight=float(raw.get("weight", 1.0)),
                params=dict(raw.get("params", {}) or {}),
                evidence=dict(evidence) if isinstance(evidence, Mapping) else None,
                book=book,
                probe=dict(probe) if isinstance(probe, Mapping) else None,
            )
        )
    return Registry(
        universe=tuple(str(symbol).upper() for symbol in (payload.get("universe") or [])),
        version=int(payload.get("version", 1)),
        ensemble_method=str(ensemble.get("method", "mean")),
        turnover_penalty=_unimplemented_turnover_penalty(ensemble),
        strategies=tuple(entries),
        books=books,
    )


def _unimplemented_turnover_penalty(ensemble: Mapping[str, Any]) -> float:
    """`ensemble.turnover_penalty` is parsed, hashed, and implemented by nothing.  Refuse a live value.

    Found 2026-09-09 by mutating every registry leaf and asking which ones move a digest: this one moves
    `registry_fingerprint` and reaches no model - `combine_targets` has no such parameter and
    `AlphaModel` does not carry it.  So setting it would move the research fingerprint, make the change
    look adopted, and leave the loop combining targets exactly as before.  KILL-Q15's shape with the
    digest on the wrong side: it moves when nothing else does.

    Zero is left parseable rather than the field deleted, because deleting it would change the
    fingerprint of every archived report.  Wiring it is a construction change and needs its own
    evidence; until then it may not be set.
    """
    value = float(ensemble.get("turnover_penalty", 0.0))
    if value != 0.0:
        raise ValueError(
            f"ensemble.turnover_penalty={value} is not implemented: `combine_targets` takes no such "
            "parameter, so setting it would move `registry_fingerprint` and change nothing the loop does.  "
            "Wire it with its own pre-registered evidence, or leave it at 0."
        )
    return value


def registry_fingerprint(
    registry: Registry, canonical: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """The configuration a report was produced under: what runs, not how the file happens to be written.

    A report that decides something about the *ensemble* (``research overlay``) is only valid for the
    registry it was computed against, and a registry can change under a long research run - that is how
    a take-profit conclusion once came to rest on evidence that had expired fifteen minutes earlier.
    Hashing the file cannot express this: editing a comment would change the digest, while a parameter
    edited inside an existing line looks like any other change.  The digest is taken over the enabled
    entries, with parameters canonicalised through each signal's own parameter object so an unwritten
    default and an explicit one agree, plus the ensemble method and the book fractions.  Pure: the
    caller supplies the canonicaliser and does the file I/O.
    """
    strategies = {
        entry.id: {
            "book": entry.book,
            "weight": entry.weight,
            "params": dict(canonical(entry.id, entry.params) if canonical is not None else entry.params),
        }
        for entry in registry.enabled
    }
    payload: dict[str, Any] = {
        "ensemble_method": registry.ensemble_method,
        "turnover_penalty": registry.turnover_penalty,
        "books": {name: spec.fraction for name, spec in sorted(registry.books.items())},
        "strategies": strategies,
    }
    if registry.universe:
        # Present only when it says something.  The traded population IS part of "what runs" - a pinned
        # universe that could be edited with no digest moving is one nobody can tell has moved - but
        # adding the KEY unconditionally moves the digest of every registry that pins nothing, and the
        # first draft of this did exactly that: the shipped registry went 16671c63a12e -> fa383fbe6a79
        # while not one byte of it had changed, which would have had `live verify` report the running
        # loop as diverged from a file identical to the one it loaded.
        #
        # That is the failure `CONSTRUCTION_PAYLOAD_VERSION` and `CONSTRUCTION_ALIASES` exist for one
        # fingerprint over, and this one has no such machinery - so the field is made conditional
        # instead, which needs none: the key appears exactly when a universe is pinned, and pinning one
        # SHOULD move the digest.
        payload["universe"] = list(registry.universe)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {"digest": digest, **payload}


def _same_param(left: Any, right: Any) -> bool:
    """Tolerant equality for values that crossed a YAML/JSON boundary (0.4 vs 0.40, list vs tuple)."""
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(_same_param(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, int | float) and isinstance(right, int | float):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-12)
    return bool(left == right)


CONSTRUCTION_KEYS: tuple[str, ...] = (
    "vol_target",
    "vol_halflife",
    "covariance_halflife",
    "min_asset_vol",
    "max_weight",
    "max_gross",
    "max_scalar",
    "no_trade_band",
    "no_trade_rel_band",
    # P30.  Reports record `model.portfolio.__dict__`, so this key appears from the first report run
    # under the new code; older reports simply do not carry it and are skipped, which is the same rule
    # that let the `portfolio` block be introduced at all.
    "sleeve_max_gross",
    # D2, 2026-09-14, on the same rule as `sleeve_max_gross`: reports record
    # `model.portfolio.__dict__`, so this key appears from the first report run under the new code and
    # older reports simply do not carry it.  `construction_problems` skips a key the report lacks, so
    # today's pinned evidence is unaffected and the check becomes real for every report produced from
    # here on.  Its live twin `exempt_crossings` is deliberately NOT here: it has no backtest
    # counterpart, because the backtest has always behaved the way its True means.
    "flat_inside_band",
    # D3, 2026-09-17, same rule again.  It is a FLOAT that changes weights only while `flat_inside_band`
    # is true, so a report carrying 2.0 with the flag off describes the same book as one carrying 1.0 -
    # the gate still compares it, because the alternative is a key whose meaning depends on another key
    # and a reader who has to know that to trust the digest.
    "band_entry_multiple",
)


OVERLAY_BLOCKS: tuple[str, ...] = ("book_guards", "exits")


def construction_problems(
    entry: StrategyEntry,
    report: Mapping[str, Any],
    live_portfolio: Mapping[str, Any] | None,
    live_overlays: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> list[str]:
    """The numbers in a strategy's evidence were produced by a construction; all of it must match.

    Adopting P10 cell B made the gap concrete: the live relative band moved 0.25 -> 0.40 while tsmom's
    cited report had been validated at 0.25, and the gate could not see it because it compares signal
    parameters only.  A report written before ``validate`` recorded its construction carries no
    ``portfolio`` block; those are skipped rather than refused, since otherwise nothing in flight today
    could start.  From the first report that carries the block, a silent divergence is refused.

    ``live_overlays`` extends the same contract to the two layers the loop applies after the model
    (2026-09-08 audit): the book guards and the exit overlay.  Until ``validate`` learned to replay
    them, the cited evidence scored a book without either while the loop traded both, and the gate had
    nothing to compare.  Absent blocks are skipped for the same reason as above; a block recorded as
    ``None`` is NOT absent - it says the run applied no such layer, and if the loop applies one that is
    the divergence this exists to catch.
    """
    problems: list[str] = []
    recorded = report.get("portfolio")
    if isinstance(recorded, Mapping) and recorded and live_portfolio is not None:
        problems += [
            f"{entry.id}: portfolio {key} is {live_portfolio.get(key)!r} live "
            f"but {recorded.get(key)!r} in the cited evidence"
            for key in CONSTRUCTION_KEYS
            if key in recorded and not _same_param(live_portfolio.get(key), recorded.get(key))
        ]
    for block in OVERLAY_BLOCKS:
        if live_overlays is None or block not in report:
            continue
        live, cited = live_overlays.get(block), report[block]
        if not isinstance(cited, Mapping) or not cited:
            if live:
                problems.append(
                    f"{entry.id}: the cited evidence applied none, but the loop runs {block} {dict(live)!r}"
                )
            continue
        if not live:
            problems.append(f"{entry.id}: the cited evidence applied {block} {dict(cited)!r}, but the loop runs none")
            continue
        problems += [
            f"{entry.id}: {block} {key} is {live.get(key)!r} live but {cited.get(key)!r} in the cited evidence"
            for key in sorted(cited)
            if not _same_param(live.get(key), cited.get(key))
        ]
    return problems


def evidence_construction_digest(
    portfolio: Mapping[str, Any] | None,
    book_guards: Mapping[str, Any] | None,
    exits: Mapping[str, Any] | None,
) -> str:
    """One string for exactly what ``construction_problems`` compares, so both sides can record it.

    DL-G9.  The comparison above needs the live config in hand, which makes it a *startup* check and
    nothing else: a governance replay reading a report from last month has no way to reconstruct the
    loop that adopted it, so KILL-AR-07's condition - "the evidence was produced under the construction
    the loop holds" - was unreadable for every artefact in the archive.  Phase 0 measured that and
    suspended the condition rather than pretending it held.

    A digest closes it in the one way that survives time: `validate` writes this over the blocks it
    recorded, the loop writes it over the config it is running, and afterwards the two are comparable
    as strings by anyone, forever, with no config to reconstruct.

    Deliberately NOT `construction_fingerprint`'s digest.  That one covers throttle, leverage and
    `strategy_weights` - things a backtest has no opinion about - so it could never match a report and
    a "matching digest" built from it would be a rule that always fails.  This covers the intersection:
    the ``CONSTRUCTION_KEYS`` a report records, plus the two overlay blocks, and nothing else.

    ``None`` for a block is preserved as a statement ("this ran no such layer") rather than folded into
    an absent key, for the same reason ``construction_problems`` distinguishes them.
    """
    payload = {
        "portfolio": (
            {key: portfolio[key] for key in CONSTRUCTION_KEYS if key in portfolio}
            if isinstance(portfolio, Mapping)
            else None
        ),
        "book_guards": dict(book_guards) if isinstance(book_guards, Mapping) else None,
        "exits": dict(exits) if isinstance(exits, Mapping) else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def evidence_params(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The parameter set a report actually validated: ``best_params``, or the sleeve's params in a book report."""
    if str(report.get("kind", "")) == "book":
        sleeve = report.get("sleeve")
        params = sleeve.get("params") if isinstance(sleeve, Mapping) else None
    else:
        params = report.get("best_params")
    return params if isinstance(params, Mapping) else None


def param_problems(
    entry: StrategyEntry, report: Mapping[str, Any], canonical: Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
) -> list[str]:
    """The configuration that runs must be the configuration the cited report validated.

    The digest check proves the report has not been edited; it says nothing about the params next to
    it in the registry.  Without this, editing a parameter silently detaches the live book from its
    evidence - the same failure as KILL-027, one level up.
    """
    validated = evidence_params(report)
    if validated is None:
        return [f"{entry.id}: evidence report records no parameters to check against"]
    live = canonical(entry.id, entry.params)
    cited = canonical(entry.id, validated)
    differing = sorted(key for key in set(live) | set(cited) if live.get(key) != cited.get(key))
    if not differing:
        return []
    detail = ", ".join(f"{key}: registry {live.get(key)!r} vs evidence {cited.get(key)!r}" for key in differing)
    return [f"{entry.id}: registry params differ from the cited evidence ({detail})"]


def verdict_problems(entry: StrategyEntry, report: Mapping[str, Any], declared: str) -> list[str]:
    """The registry may be STRICTER than the report it cites, never more permissive.

    This branch is the one field the startup gate actually refuses on, and it was the only one in
    this file nothing compared.  `_probe_problems` has checked the declared verdict against the
    report's `book_verdict` since D-029; the signal-level path read `entry.evidence["verdict"]` - a
    string a human types - and never opened the report beside it.  The digest proves the report was
    not edited and `construction_problems` proves the construction still matches, which is exactly
    what makes the gap easy to miss: everything around the verdict is checked.

    Measured 2026-09-19 against real artefacts rather than a fixture, because a fixture here would
    have tested the contract this function is adding.  Pointing tsmom's entry at
    `reports/research/tsmom-validation-20260918T154025Z.json` (`verdict: FAIL` on disk) while the
    registry said `WEAK_PASS` returned no problems at all: digest matched, params matched,
    construction matched, and `FAIL` never got read.  Declaring `FAIL` honestly was the only way to
    get the refusal that verdict is there to produce.

    Why an ordering and not equality.  D-043 (2026-09-17) caps evidence in which no selection was
    ever exercised at WEAK_PASS, and the ten reports it flipped were already written and
    digest-anchored - `tsmom-validation-20260913T182325Z.json` among them, the one the live registry
    cites, which says PASS on disk while the registry correctly says WEAK_PASS.  Equality would
    refuse the shipped pair for being more honest than its own evidence.  An ordering admits that
    correction and refuses its inverse, which is the asymmetry D-043 already relies on.

    Absent is skipped, the same way `construction_problems` skips a report with no `portfolio` block:
    a report with no `verdict`, or one whose verdict this tuple does not know (a book report's
    `book_verdict` lives on the probe path), is left to the checks that can read it.
    """
    reported = str(report.get("verdict", "")).upper()
    if declared not in SIGNAL_VERDICTS or reported not in SIGNAL_VERDICTS:
        return []
    if SIGNAL_VERDICTS.index(declared) >= SIGNAL_VERDICTS.index(reported):
        return []
    return [
        f"{entry.id}: registry declares verdict {declared} but the cited evidence records {reported}; "
        f"a registry may only be stricter than the report it cites ({SIGNAL_VERDICTS} worst-last)"
    ]


def evidence_problems(
    entry: StrategyEntry,
    exists: Callable[[str], bool],
    sha256_of: Callable[[str], str],
    *,
    read_report: Callable[[str], Mapping[str, Any]] | None = None,
    book_fraction: float | None = None,
    canonical_params: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    live_portfolio: Mapping[str, Any] | None = None,
    live_overlays: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> list[str]:
    """KILL-015: an enabled strategy must cite a validation report that exists and matches its digest.

    A ``verdict: ACCEPT`` is a *book-level* finding (D-018).  It may only run as a non-main probe book
    with an explicit ``probe`` block (D-019), and when ``read_report`` is supplied the cited report must
    be an ACCEPTed book report about this strategy at the registry's book fraction.
    """
    if not entry.enabled:
        return []
    if not entry.evidence:
        return [f"{entry.id}: enabled without evidence"]
    path = str(entry.evidence.get("report", ""))
    digest = str(entry.evidence.get("sha256", "")).lower()
    problems: list[str] = []
    if not path or not exists(path):
        problems.append(f"{entry.id}: evidence report missing: {path or '<none>'}")
    elif len(digest) != 64 or sha256_of(path) != digest:
        problems.append(f"{entry.id}: evidence digest mismatch for {path}")
    verdict = str(entry.evidence.get("verdict", "")).upper()
    report_ok = not problems
    if verdict in PROBE_VERDICTS:
        problems.extend(_probe_problems(entry, path, read_report, book_fraction, verdict, report_ok=report_ok))
    elif verdict and verdict not in {"PASS", "WEAK_PASS"}:
        problems.append(f"{entry.id}: evidence verdict {verdict} does not allow live use")
    if read_report is not None and report_ok:
        report = read_report(path)
        problems.extend(verdict_problems(entry, report, verdict))
        if canonical_params is not None:
            problems.extend(param_problems(entry, report, canonical_params))
        problems.extend(construction_problems(entry, report, live_portfolio, live_overlays))
    return problems


def _probe_problems(
    entry: StrategyEntry,
    path: str,
    read_report: Callable[[str], Mapping[str, Any]] | None,
    book_fraction: float | None,
    verdict: str = PROBE_VERDICT,
    *,
    report_ok: bool,
) -> list[str]:
    """A book-level finding may run as a probe, and a REJECT may too when the registry acknowledges it (D-029).

    The alternative is worse than it looks.  When the flow sleeve's book verdict turned REJECT on
    2026-09-04, the choices were to point the registry at a report whose universe no longer existed on
    disk, or to cite the REJECT and have the gate refuse to start the whole loop, not just the sleeve.  Requiring
    ``accepted_despite`` plus a reason and a review date keeps the running configuration attached to
    current, reproducible evidence and puts the exception in the file rather than in a commit message.
    """
    problems: list[str] = []
    probe = entry.probe or {}
    if entry.book == MAIN_BOOK:
        problems.append(f"{entry.id}: a book-level {verdict} can only run as a non-main probe book (D-019)")
    if verdict != PROBE_VERDICT:
        acknowledged = str(probe.get("accepted_despite", "")).upper()
        if acknowledged != verdict:
            problems.append(
                f"{entry.id}: evidence verdict {verdict} needs probe.accepted_despite: {verdict} in the registry (D-029)"
            )
        if not str(probe.get("reason", "")).strip():
            problems.append(f"{entry.id}: a probe running against a {verdict} needs probe.reason to say why")
        if not probe.get("review_after_days"):
            problems.append(f"{entry.id}: a probe running against a {verdict} needs probe.review_after_days")
    stop = probe.get("stop") if isinstance(probe.get("stop"), Mapping) else None
    if not probe.get("accepted_by") or not probe.get("accepted_on") or stop is None:
        problems.append(
            f"{entry.id}: a probe book needs an explicit probe block (accepted_by, accepted_on, stop) in the registry"
        )
    else:
        try:
            window = int(stop.get("window_days", 0))
            loss = float(stop.get("max_loss", -1.0))
        except (TypeError, ValueError):
            window, loss = 0, -1.0
        if window <= 0 or loss < 0:
            problems.append(f"{entry.id}: probe stop needs window_days > 0 and max_loss >= 0")
    if read_report is not None and report_ok:
        report = read_report(path)
        if str(report.get("kind", "")) != "book" or str(report.get("book_verdict", "")).upper() != verdict:
            problems.append(f"{entry.id}: evidence {path} is not a book report with verdict {verdict}")
        sleeve = str((report.get("sleeve") or {}).get("strategy", ""))
        if sleeve != entry.id:
            problems.append(f"{entry.id}: book report {path} is about {sleeve or '<none>'}")
        fraction = report.get("fraction")
        if book_fraction is None or fraction is None or abs(float(fraction) - float(book_fraction)) > 1e-4:
            problems.append(
                f"{entry.id}: registry book fraction {book_fraction} does not match the evidence fraction {fraction}"
            )
    return problems
