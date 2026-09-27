"""A digest of the data a result was computed from (the dataset manifest / PIT lineage).

Everything else in this system already names itself: a validation report carries a digest, the registry
carries a signal fingerprint, a live cycle carries a construction fingerprint.  The *data* did not, and on
2026-09-04 that gap bit: the point-in-time membership table was rebuilt from monthly to daily at 13:20
while `config/live.demo.yaml` still described it as monthly, and P12 was written against the stale
description.  Nothing was wrong with either the table or the comment on its own - what was missing was
anything that would notice they had stopped agreeing.

Deliberately cheap.  It reads sizes, row counts and boundary timestamps from the parquet footers and the
small JSON files; it does not hash bar contents, because a manifest nobody runs is worth nothing and
hashing a 435 KB membership table plus 879 symbol files on every report would make it optional in
practice.  That is a stated limit, not an oversight: this detects *replacement and drift*, not silent
in-place corruption of individual bars.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from starquant_data.store import FundingStore, KlineStore

MANIFEST_FIELDS = ("membership", "universe", "klines", "funding")

BLOCKING_FIELDS = ("membership", "universe")
"""The fields whose movement can change what the data *means* rather than how much of it there is.

``membership`` blocks unconditionally: it is the point-in-time table validation actually runs on, and a
rebuild at another cadence (P12) makes a cited result a statement about a different book.  ``universe``
blocks conditionally - see :func:`_universe_drift_blocks`.  ``klines`` and ``funding`` never block,
because the daily sync appends bars to both; refusing on that would refuse every start after a sync and
teach the operator to pass ``--allow-unvalidated`` permanently, which costs more than it buys.
"""

MANIFEST_VERSION = 2
"""1 -> 2 (D-040): under v1 the funding fact read ``{0, 0, _digest({})}`` whether the archive held 231
files or none, so a v1 zero is unreadable and a v2 zero is a measurement.  Stamped rather than inferred,
because without it every future empty archive would have to be called unknown to stay honest about the
old ones.  Outside :data:`MANIFEST_FIELDS` on purpose: adding it moves no existing digest.
"""


def _digest(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_BLIND_FUNDING: dict[str, Any] = {"symbols": 0, "bytes": 0, "fingerprint": _digest({})}
"""What a v1 manifest recorded for funding no matter what was on disk."""


def _file_fact(path: Path) -> dict[str, Any] | None:
    """Size only.  Modification time is deliberately excluded: a rewrite that produces identical data is
    not drift, and a digest that moved every time a job re-ran would be ignored within a week."""
    return {"bytes": path.stat().st_size} if path.exists() else None


def _membership_fact(root: Path) -> dict[str, Any] | None:
    path = root / "membership.parquet"
    if not path.exists():
        return None
    table = pd.read_parquet(path)
    index = pd.DatetimeIndex(table.index)
    members = table.astype(bool)
    return {
        "refreshes": len(table),
        "symbols": len(table.columns),
        "union": int((members.any(axis=0)).sum()),
        "mean_size": round(float(members.sum(axis=1).mean()), 4) if len(table) else 0.0,
        "first": str(index[0]) if len(index) else None,
        "last": str(index[-1]) if len(index) else None,
        # the cadence the table actually has, which is the fact the P12 drift turned on
        "median_gap_hours": (
            round(float(pd.Series(index).diff().dt.total_seconds().median() / 3600.0), 3) if len(index) > 1 else None
        ),
        "file": _file_fact(path),
    }


def _store_fact(directory: Path, paths: dict[str, Path]) -> dict[str, Any] | None:
    """Size per symbol for one parquet store, given the paths the store itself resolved.

    Takes resolved paths rather than a folder plus a naming rule because that version knew the layout a
    second time and was wrong about it for funding's whole life (D-040): klines nest as
    ``<SYMBOL>/<interval>.parquet``, funding is flat as ``<SYMBOL>.parquet``, and the shared walk skipped
    every non-directory.  A 231-file / 20 MB archive read ``{0, 0, ...}``, so both sides of
    ``manifest_problems`` were zero and funding could never raise a flag - including across D-034, which
    rewrote what that archive means.  The layout now lives only in ``starquant_data.store``.
    """
    if not directory.exists():
        return None
    symbols = {symbol: path.stat().st_size for symbol, path in paths.items() if path.exists()}
    return {"symbols": len(symbols), "bytes": sum(symbols.values()), "fingerprint": _digest(symbols)}


@dataclass(frozen=True)
class DatasetManifest:
    """What the data looked like when a result was produced."""

    root: str
    interval: str
    membership: dict[str, Any] | None
    universe: dict[str, Any] | None
    klines: dict[str, Any] | None
    funding: dict[str, Any] | None

    @property
    def digest(self) -> str:
        return _digest({field: getattr(self, field) for field in MANIFEST_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "dataset-manifest",
            "version": MANIFEST_VERSION,
            "root": self.root,
            "interval": self.interval,
            "digest": self.digest,
            **{field: getattr(self, field) for field in MANIFEST_FIELDS},
        }

    def differences(self, other: DatasetManifest, skip: Collection[str] = ()) -> list[str]:
        """Human-readable disagreements, so a stale pointer says *what* moved rather than only that it did.

        ``skip`` drops fields the recorded side never actually measured; reporting those as movement
        would assert a change that never happened.
        """
        out: list[str] = []
        for field in MANIFEST_FIELDS:
            if field in skip:
                continue
            mine, theirs = getattr(self, field), getattr(other, field)
            if mine == theirs:
                continue
            if mine is None or theirs is None:
                out.append(
                    f"{field}: {'absent' if mine is None else 'present'} then, {'absent' if theirs is None else 'present'} now"
                )
                continue
            for key in sorted(set(mine) | set(theirs)):
                if mine.get(key) != theirs.get(key):
                    out.append(f"{field}.{key}: {mine.get(key)} -> {theirs.get(key)}")
        return out


def build_manifest(root: str | Path, interval: str = "1h") -> DatasetManifest:
    """Read the cheap facts about a data root."""
    base = Path(root)
    universe_path = base / "universe.json"
    universe: dict[str, Any] | None = None
    if universe_path.exists():
        payload = json.loads(universe_path.read_text(encoding="utf-8"))
        symbols = [str(s) for s in payload.get("symbols", [])]
        universe = {
            "count": len(symbols),
            "fingerprint": _digest(sorted(symbols)),
            "source": payload.get("source"),
            "selected_at_ms": payload.get("selected_at_ms"),
        }
    klines, funding = KlineStore(base), FundingStore(base)
    return DatasetManifest(
        root=str(base),
        interval=interval,
        membership=_membership_fact(base),
        universe=universe,
        klines=_store_fact(klines.directory, {s: klines.path(s, interval) for s in klines.symbols(interval)}),
        funding=_store_fact(funding.directory, {s: funding.path(s) for s in funding.symbols()}),
    )


def _universe_drift_blocks(
    previous: dict[str, Any] | None, current: dict[str, Any] | None, universe_mode: str | None = None
) -> bool:
    """A changed symbol set blocks; a changed *selection mechanism* does not; a pit result is exempt.

    ``.starquant/data/universe.json`` is rewritten by the live loop's own universe refresh, so a
    ``pool-refresh -> live-refresh`` transition is the loop's bookkeeping and not evidence going stale.
    Measured 2026-09-04: tsmom's cited universe read ``pool-refresh``/15 against ``live-refresh``/16 on
    disk, so treating every universe move as drift would have the loop refuse to start because of
    something it did itself.  A symbol set that moves while the source holds still is the real thing -
    the book being traded is no longer the book the evidence describes.

    2026-09-15: ``universe_mode == "pit"`` exempts the field outright.  ``_resolve_symbols`` calls
    ``read_universe`` only under ``static``, so a pit VALIDATION or MINE result's population is the
    union of ``membership.parquet``, which blocks unconditionally one field over.  Blocking such a
    result here refuses a start over a file it never opened - and the fix shipped for that on
    2026-09-09 was to freeze the TRADED pool instead, which held the live universe at 16 names while
    the cited evidence re-ranked every 24 hours.  Only an EXPLICIT ``pit`` is exempt: a report that
    declares no mode keeps its block.

    Narrowed from "a pit result" to those two commands on 2026-09-15, because the first wording was
    not true of every pit report and this repository reads these paragraphs as fact.  ``research book
    --universe pit --robustness static`` DOES read ``universe.json`` (``research_cmd.py:2470``) to
    build its sensitivity arm, and the shipped registry cites exactly such a report -
    ``book-tsmom-flow-20260908T105322Z.json``, ``universe_mode: "pit"`` with
    ``robustness_universe: "static"``.  It is harmless today only because ``book`` writes no
    ``dataset`` block (only ``validate`` and ``mine`` write one into a report), so that
    report reaches ``manifest_check`` as ``None`` and never reaches this predicate at all.  Give
    ``book`` a manifest and this exemption starts waving through a report that did read the file.

    Corrected 2026-09-15: the parenthetical above read "``build_manifest`` is called by ``validate``
    and ``mine`` alone", and a review found that false - ``starquant_live.config.registry_dataset_problems``
    calls it too, to build the CURRENT manifest it compares cited reports against.  The conclusion it
    supported held, but the false half is the half a reader chasing this warning would grep for.
    """
    if universe_mode == "pit":
        return False
    if previous is None or current is None:
        return True  # only reached when the two disagree, i.e. the block appeared or vanished
    if previous.get("source") != current.get("source"):
        return False
    return previous.get("fingerprint") != current.get("fingerprint")


@dataclass(frozen=True)
class ManifestCheck:
    """A manifest comparison split by what the caller should do about it.

    ``blocking`` is drift in :data:`BLOCKING_FIELDS`.  ``advisory`` is everything else: store growth,
    and provenance that was never recorded at all.  Provenance is advisory on purpose and by
    precedent - ``construction_problems`` skips reports written before ``validate`` recorded a
    ``portfolio`` block, so that adding a gate dimension never stops what is already in flight.
    """

    blocking: list[str]
    advisory: list[str]

    @property
    def problems(self) -> list[str]:
        return [*self.blocking, *self.advisory]


def _unrecorded_fields(recorded: dict[str, Any]) -> tuple[str, ...]:
    """Fields the recorded manifest claims a value for but never actually measured (D-040).

    Only funding, only v1, only the exact zero the layout bug produced.  ``funding: null`` stays
    trustworthy - v1 could see an absent directory - and no v1 record holds any other funding value.
    """
    if int(recorded.get("version", 1)) >= MANIFEST_VERSION:
        return ()
    return ("funding",) if recorded.get("funding") == _BLIND_FUNDING else ()


def manifest_check(
    recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None
) -> ManifestCheck:
    """Compare a report's recorded manifest against the data on disk, split by severity.

    A report written before manifests existed has none; that is reported as unknown provenance rather
    than as agreement, because "no manifest" and "manifest matches" are different facts.
    """
    if not recorded:
        return ManifestCheck([], ["no dataset manifest recorded: this result's data provenance cannot be checked"])
    unrecorded = _unrecorded_fields(recorded)
    if not unrecorded and recorded.get("digest") == current.digest:
        return ManifestCheck([], [])
    previous = DatasetManifest(
        root=str(recorded.get("root", "")),
        interval=str(recorded.get("interval", current.interval)),
        membership=recorded.get("membership"),
        universe=recorded.get("universe"),
        klines=recorded.get("klines"),
        funding=recorded.get("funding"),
    )
    blocks: tuple[str, ...] = ("membership",)
    if previous.universe != current.universe and _universe_drift_blocks(
        previous.universe, current.universe, universe_mode
    ):
        blocks = (*blocks, "universe")
    advises = tuple(field for field in MANIFEST_FIELDS if field not in blocks)

    meaning_moved = previous.differences(current, skip=(*advises, *unrecorded))
    extent_moved = previous.differences(current, skip=(*blocks, *unrecorded))

    blocking = [f"dataset changed since this result was produced: {', '.join(meaning_moved)}"] if meaning_moved else []
    advisory = (
        [f"dataset store contents changed since this result was produced: {', '.join(extent_moved)}"]
        if extent_moved
        else []
    )
    version = recorded.get("version", 1)
    advisory.extend(
        f"{field} provenance was never recorded: manifest v{version} could not read the {field} store, "
        f"so this result's {field} data cannot be checked"
        for field in unrecorded
    )
    return ManifestCheck(blocking, advisory)


def manifest_problems(
    recorded: dict[str, Any] | None, current: DatasetManifest, *, universe_mode: str | None = None
) -> list[str]:
    """Every problem, blocking first.  Callers that act on severity want :func:`manifest_check`."""
    return manifest_check(recorded, current, universe_mode=universe_mode).problems
