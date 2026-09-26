"""R0 / DL-G1 and KILL-Q2, in the artefact a reader actually opens.

Three notes already travel with the numbers they qualify (`_MARGIN_BUFFER_NOTE`, `_embargo_note`,
`_pbo_note`), written because "a caveat reachable only by reading the implementation is not a
disclosure to the person reading the artefact - it is a disclosure to the person who already knows".
Two more facts were in exactly that position, and this file holds their fix:

* **Both calibers.**  `oos_selection_whole_library` has been in the JSON since DL-G1, whose comment
  says an artefact carrying only the chosen caliber "cannot be used to re-open the choice".  The
  Markdown carried only the chosen one, so for a reader who does not open the JSON the artefact was
  precisely that.  On `tsmom-validation-20260913T182325Z.json` - the report the live registry cites -
  the gate at N=242 leaves +0.04 and the library at N=2,914 leaves -0.23.
* **What `oos_is_full_sample_tail: True` means.**  `validate` has said it on stdout since KILL-Q2,
  and stdout is not an artefact: the run scrolls away, and a bare boolean beside a Sharpe that reads
  like an out-of-sample estimate is what D-043 later had to cap at WEAK_PASS.

Neither changes a verdict: `verdict.decide` reads `oos_selection` and nothing else, which
`tests/alpha/test_the_other_caliber_is_reported_not_applied.py` holds from the other side.  Neither
touches the JSON payload either, so every archived sha256 stays comparable with the ones the registry
already cites - the same constraint the first three notes were written under.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starquant_cli.research_cmd import _caliber_note, _full_sample_tail_note

ROOT = Path(__file__).resolve().parents[2]
CITED = ROOT / "reports" / "research" / "tsmom-validation-20260913T182325Z.json"


def _cited() -> dict[str, Any]:
    return json.loads(CITED.read_text(encoding="utf-8"))


def test_the_note_prints_both_n_and_both_margins() -> None:
    gate = {"n_trials": 242, "threshold_annual": 1.5493, "oos_sharpe_annual": 1.5919}
    library = {"n_trials": 2914, "threshold_annual": 1.8184, "p_family": 0.3473}

    note = _caliber_note(gate, library)

    assert "N=242" in note and "N=2914" in note
    assert "1.55" in note and "1.82" in note  # both thresholds
    assert "+0.04" in note and "-0.23" in note  # the margin each one leaves
    assert "ENFORCED" in note and "never enforced" in note
    assert "R0 / KILL-AR-01" in note, "which N is the gate is a ruling, and the note must say so"


def test_the_note_is_anchored_to_the_report_the_registry_cites() -> None:
    """The numbers above are not a fixture: they are what the shipped evidence says."""
    report = _cited()
    gate, library = report["oos_selection"], report["oos_selection_whole_library"]

    assert gate["n_trials"] == 242 and library["n_trials"] == 2914
    # The gate clears; the other caliber does not.  Both facts, one artefact.
    assert gate["oos_sharpe_annual"] > gate["threshold_annual"]
    assert gate["oos_sharpe_annual"] < library["threshold_annual"]

    note = _caliber_note(gate, library)

    assert f"N={gate['n_trials']}" in note and f"N={library['n_trials']}" in note
    assert "p_family 0.3473" in note


def test_a_missing_or_unusable_library_block_does_not_break_the_note() -> None:
    """Reports written before DL-G1 carry no second block, and must still render."""
    gate = {"n_trials": 242, "threshold_annual": 1.5493, "oos_sharpe_annual": 1.5919}

    assert "not reported" in _caliber_note(gate, None)
    assert "not reported" in _caliber_note(gate, {})
    assert "not comparable" in _caliber_note({"n_trials": 1}, {"n_trials": 2})


def test_the_note_does_not_mutate_either_block() -> None:
    """It renders beside the payload; it never becomes part of it, or the sha256 would move."""
    gate = {"n_trials": 242, "threshold_annual": 1.5493, "oos_sharpe_annual": 1.5919}
    library = {"n_trials": 2914, "threshold_annual": 1.8184}
    before = (dict(gate), dict(library))

    _caliber_note(gate, library)

    assert (gate, library) == before


def test_the_tail_note_says_which_of_the_two_shapes_a_report_is() -> None:
    tail = _full_sample_tail_note(True)
    selected = _full_sample_tail_note(False)

    assert "TAIL OF ONE FULL-SAMPLE SERIES" in tail
    assert "WEAK_PASS" in tail, "D-043's cap is the consequence, and the reader needs it here"
    assert "selection procedure" in selected and "TAIL" not in selected
    # Absent is not False: a report predating the field must not be labelled as having selected.
    assert _full_sample_tail_note(None) == selected or "TAIL" not in _full_sample_tail_note(None)


def test_the_cited_report_is_the_shape_d043_caps() -> None:
    """Why the note exists at all: the shipped evidence is a tail, and said so only on stdout."""
    report = _cited()

    assert report["walk_forward"]["oos_is_full_sample_tail"] is True
    assert report["grid_size"] == 2
    assert "TAIL OF ONE FULL-SAMPLE SERIES" in _full_sample_tail_note(report["walk_forward"]["oos_is_full_sample_tail"])
