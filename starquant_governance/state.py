"""`governance_state.json`: the book's lifecycle state, written the way `stopped_books` is written.

Separate from `lifecycle` on purpose.  Everything in that module is a pure function of the state and
one event, which is what lets the same code decide live and replay history; the moment it also knew
how to load itself, the replay would be reading whatever is on disk today rather than the state it was
handed.  So the state machine decides and this module remembers, and the two are testable apart.

The format is a plain dict of primitives with a `version`.  It is not a pickle and not a dataclass
dump: this file has to be readable by a person during an incident, and by a future version of this
code that has since added a field.  An unknown field is dropped rather than refused, and a missing one
takes the dataclass default - the same compatibility rule `TrialRecord.from_json` follows, and for the
same reason: a record that cannot read its own history is not a record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starquant_governance.lifecycle import Book, Candidate, State

VERSION = 1


def dump(book: Book) -> dict[str, Any]:
    return {
        "version": VERSION,
        "window": book.window,
        "promotions_this_window": book.promotions_this_window,
        "to_main_this_window": book.to_main_this_window,
        "consecutive_probe_stops": book.consecutive_probe_stops,
        "frozen_until_window": book.frozen_until_window,
        "candidates": {
            name: {
                "state": candidate.state.value,
                "probe_entries": candidate.probe_entries,
                "windows_survived": candidate.windows_survived,
                "fraction": candidate.fraction,
                "cooldown_until_window": candidate.cooldown_until_window,
                "folded_through": candidate.folded_through,
                "queued_at": candidate.queued_at,
            }
            for name, candidate in sorted(book.candidates.items())
        },
    }


def load(payload: Any) -> Book:
    """Rebuild a book, refusing nothing that a person could plausibly have hand-edited into it.

    An unreadable state is an empty book rather than an exception, the same direction the live loop's
    own state store takes.

    This used to claim that was SAFE, because "an empty book has no probes, so every rule that could
    act on it refuses for want of a candidate".  That is true only of the candidate being evaluated,
    which the caller supplies.  Every rule that reads the book for CONSTRAINTS reads an empty one as
    headroom: `len(book.probes)` is 0 against R3's two slots and `probe_fraction` is 0.0 against the
    1/3 cap.  Measured 2026-09-09 with no state file on the trading machine - a second 1/3 probe was
    ALLOWED on top of the flow probe already running live, 2/3 of the book against a 1/3 cap.

    So an empty book is permissive, not conservative, and the sleeves that are actually running have
    to be IN it: see `governance/governance_state.json` and the test that holds it to KILL-AR-06.
    Falling back to empty is still the right behaviour for a TORN file - deciding on half a book is
    worse - but it is a fallback with teeth, not a safe default.
    """
    if not isinstance(payload, dict):
        return Book()
    candidates: dict[str, Candidate] = {}
    for name, raw in (payload.get("candidates") or {}).items():
        if not isinstance(raw, dict):
            continue
        try:
            state = State(str(raw.get("state", "candidate")))
        except ValueError:
            continue
        candidates[str(name)] = Candidate(
            id=str(name),
            state=state,
            probe_entries=int(raw.get("probe_entries", 0)),
            windows_survived=int(raw.get("windows_survived", 0)),
            fraction=float(raw.get("fraction", 0.0)),
            cooldown_until_window=int(raw.get("cooldown_until_window", -1)),
            # A state written before `governance advance` existed carries no watermark, and an empty
            # one means "nothing folded yet", so the first run folds the whole record.  That is safe
            # HERE rather than in general: measured 2026-09-10, all 184 cycles of the armed record
            # carry `stop: false` and no batch window has closed, so there is nothing to fold and no
            # life to spend twice.  It stops being safe the moment a stop lands before a first
            # `advance`; `--dry-run` is the default for exactly that reading, and the command prints
            # each candidate's watermark as `(never folded)` so the operator sees it before writing.
            folded_through=str(raw.get("folded_through", "")),
            # Absent in every state written before 2026-09-12, and an empty stamp sorts LAST in
            # `Book.queue` - an unknown arrival is not a claim to the front.
            queued_at=str(raw.get("queued_at", "")),
        )
    return Book(
        window=int(payload.get("window", 0)),
        candidates=candidates,
        promotions_this_window=int(payload.get("promotions_this_window", 0)),
        to_main_this_window=int(payload.get("to_main_this_window", 0)),
        consecutive_probe_stops=int(payload.get("consecutive_probe_stops", 0)),
        frozen_until_window=int(payload.get("frozen_until_window", -1)),
    )


def read(path: Path) -> Book:
    if not path.exists():
        return Book()
    try:
        return load(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return Book()


def write(path: Path, book: Book) -> None:
    """Atomic replace, because a torn governance state read during a restart decides on half a book."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dump(book), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
