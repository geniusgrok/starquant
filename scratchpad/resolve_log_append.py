"""Resolve an append/append conflict in an append-only log by keeping BOTH sides, ours first.

Every agent in the 2026-09-09 batch appends its own entry to `docs/RESEARCH_LOG.md`, so merging
them conflicts at the tail every time.  Keeping both is the only correct resolution for an
append-only record - dropping either side would delete a result somebody measured - and doing it by
hand eight times is how one of them quietly goes missing.

Refuses anything that is not a pure append/append at the tail: if either side deleted or edited
existing lines, that is a real conflict and a person has to look at it.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resolve(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    marks = [i for i, line in enumerate(lines) if line.startswith(("<<<<<<<", "=======", ">>>>>>>"))]
    if len(marks) != 3:
        raise SystemExit(f"{path}: expected exactly one conflict hunk, found {len(marks) // 3}")
    start, mid, end = marks
    ours, theirs = lines[start + 1 : mid], lines[mid + 1 : end]
    if lines[end + 1 :]:
        raise SystemExit(f"{path}: the conflict is not at the tail - this is not an append/append")
    path.write_text("".join(lines[:start] + ours + theirs), encoding="utf-8")
    return len(ours), len(theirs)


if __name__ == "__main__":
    for name in sys.argv[1:] or ["docs/RESEARCH_LOG.md"]:
        a, b = resolve(Path(name))
        print(f"{name}: kept both appends, {a} + {b} lines")
