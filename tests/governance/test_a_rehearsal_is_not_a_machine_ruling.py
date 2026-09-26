"""`governance plan` is a dry run and it was recording a machine ruling into M-G05's ledger.

`plan`'s own docstring: "What `apply` would do, without doing it - the gate is asked against a copy."
It then called `_log_admission`, so every rehearsal landed a `pending` row in
`governance/verdicts.jsonl` - the sample M-G05 divides by, and Pre-A′'s only falsifier.

Measured 2026-09-12, during the DRILL-G1 production run: four `plan`/`apply` invocations within four
minutes left four rows, three of them rehearsals, and `governance divergence` went from 1 pending to 5.
Ten quiet rehearsals reach the quorum of 10 with no decision having been made.

This is the SAME defect found the same morning on the other gate (`family_gate` keyed idempotence on
the date, so one `governance gate` a day was one sample a day).  Two gates, one command apart, the same
question - "is a re-asking a new answer?" - answered wrong both times.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_governance.verdicts import read


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "governance" / "verdicts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_plan_does_not_call_the_recorder_but_apply_does() -> None:
    """Held at the call sites, because the recorder cannot tell who called it.

    A behavioural test would need a full registry, a profile, the autonomy switch and a real gate;
    this asserts the one fact that decides it, and the docstring above carries the measurement.
    """
    import inspect

    from starquant_cli import governance_cmd

    # click wraps the function in a Command; `.callback` is the function itself
    plan_source = inspect.getsource(governance_cmd.plan_cmd.callback)
    apply_source = inspect.getsource(governance_cmd.apply_cmd.callback)
    # the CALL, not the name: `plan` carries a comment saying why it does not make one
    assert "_log_admission(" not in plan_source, "a dry run must not record a ruling"
    assert "_log_admission" in plan_source, "and it should say so where the call used to be"
    assert "_log_admission(" in apply_source, "the write must still record one"


def test_the_rehearsal_rows_already_in_the_ledger_stay_where_they_are(tmp_path: Path) -> None:
    """Append-only means the three rehearsal rows of 2026-09-12 are history, not a bug to erase.

    They are left readable and counted; what changed is that no more of them are made.  Reviewing
    them is a person's job - `governance review` is the human half of M-G05, and a machine that
    reviewed its own rulings would be measuring its agreement with itself.
    """
    path = _ledger(tmp_path)
    rows = [
        {
            "id": "a",
            "at": "2026-09-12T13:17:09+00:00",
            "kind": "admission",
            "subject": "alpha_registry.candidate.drill.yaml",
            "ruling": "allow",
            "reasons": [],
            "review": "",
            "review_why": "",
            "reviewed_at": "",
        },
        {
            "id": "b",
            "at": "2026-09-12T13:17:23+00:00",
            "kind": "admission",
            "subject": "DRILL-G1-20260912",
            "ruling": "allow",
            "reasons": [],
            "review": "",
            "review_why": "",
            "reviewed_at": "",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    loaded = read(path)
    assert len(loaded) == 2
    assert all(verdict.pending for verdict in loaded)
