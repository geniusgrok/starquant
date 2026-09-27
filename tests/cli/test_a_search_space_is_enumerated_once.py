"""R2: re-running a search space charges the family twice for one hypothesis.

It happened.  On 2026-09-08 a P20 recovery re-ran the same 514-wide space over 24 more bars; every
signature was new because the data range moved, so 514 rows were appended and the family's prior went
514 -> 1,028 with nothing on the terminal saying so.  Ruling Q7 reverted the rows on K-EX07's
precedent - but a ruling after the fact is not a rule, and the next session would have done the same.

A note on what is NOT done here, because the plan asked for it and it would have been wrong.  R2 was
written as "`search_space_version` 由空串改为必填".  That field is deliberately EMPTY on the `mined`
bucket's rows, and the reason is recorded beside them: a candidate examined in a 267-wide search and
again in a 514-wide one is one hypothesis looked at twice, so stamping the width on would charge
267 + 514 for a family of 514 - inflating N in the direction that looks rigorous and is simply wrong.
Making it mandatory would re-introduce exactly that.  The rule's INTENT - refuse a second enumeration -
needs the space recorded where the next run can read it, not on every row, so it goes in the shortlist
report and the refusal happens before the expensive scoring starts.
"""

from __future__ import annotations

import json
from pathlib import Path

from starquant_alpha.mining import enumerate_candidates
from starquant_cli.research_cmd import _prior_search


def _small() -> object:
    return enumerate_candidates(horizons=(24,), vol_windows=(48,), scales=(1.0,), include_panel_nodes=False)


def test_the_space_identity_is_the_set_of_expressions_not_the_count() -> None:
    """Two parameterisations that enumerate the same set are the same space; a wider one is not."""
    same = enumerate_candidates(horizons=(24, 72), vol_windows=(48,), scales=(1.0,), include_panel_nodes=False)
    reordered = enumerate_candidates(horizons=(72, 24), vol_windows=(48,), scales=(1.0,), include_panel_nodes=False)
    wider = enumerate_candidates(horizons=(24, 72, 168), vol_windows=(48,), scales=(1.0,), include_panel_nodes=False)
    assert same.space_digest == reordered.space_digest
    assert same.space_digest != wider.space_digest


def test_a_space_already_enumerated_is_found(tmp_path: Path) -> None:
    search = _small()
    (tmp_path / "mine-shortlist-20260101T000000Z.json").write_text(
        json.dumps({"kind": "mine-shortlist", "search_space_digest": search.space_digest, "evaluated": 1})
    )
    assert _prior_search(search, tmp_path) == "mine-shortlist-20260101T000000Z.json"


def test_a_different_space_is_not_found(tmp_path: Path) -> None:
    search = _small()
    (tmp_path / "mine-shortlist-20260101T000000Z.json").write_text(
        json.dumps({"kind": "mine-shortlist", "search_space_digest": "0" * 16, "evaluated": 99_999})
    )
    assert _prior_search(search, tmp_path) is None


def test_a_report_predating_the_field_falls_back_to_the_count_and_says_so(tmp_path: Path) -> None:
    """The weaker check, labelled.  It is the case the rule was written for, and it ages out on its own."""
    search = _small()
    (tmp_path / "mine-shortlist-20260101T000000Z.json").write_text(
        json.dumps({"kind": "mine-shortlist", "evaluated": search.evaluated})
    )
    found = _prior_search(search, tmp_path)
    assert found is not None and "matched on `evaluated` only" in found


def test_an_unreadable_report_does_not_stop_the_scan(tmp_path: Path) -> None:
    search = _small()
    (tmp_path / "mine-shortlist-20250101T000000Z.json").write_text("{ not json")
    (tmp_path / "mine-shortlist-20260101T000000Z.json").write_text(
        json.dumps({"kind": "mine-shortlist", "search_space_digest": search.space_digest})
    )
    assert _prior_search(search, tmp_path) is not None
    assert _prior_search(search, tmp_path / "does-not-exist") is None
