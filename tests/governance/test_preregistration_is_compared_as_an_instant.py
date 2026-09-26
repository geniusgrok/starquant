"""DL-K3 compared two ISO timestamps as STRINGS, and that is not the rule it was meant to be.

`git` writes `preregistration.committed_at` with the COMMITTER's local offset; a report writes
`generated_at` in UTC.  The two are routinely in different zones, so `a < b` on the text was
answering a question about spelling.

It failed both ways.  Measured 2026-09-09 on the pointer the live registry cites, it REFUSED valid
evidence.  Turn the offset around and it ACCEPTS a forgery - and that is the direction that matters,
because DL-K3 exists to stop a result being registered after it is already known.
"""

from __future__ import annotations

from typing import Any

import pytest

from starquant_governance.replay import _instant


def _report(committed_at: str | None, generated_at: str | None) -> dict[str, Any]:
    report: dict[str, Any] = {"verdict": "PASS", "generated_at": generated_at}
    if committed_at is not None:
        report["preregistration"] = {"commit": "deadbeef", "committed_at": committed_at}
    return report


def _prereg_ok(report: dict[str, Any]) -> bool | None:
    """The decision the replay makes, or None when it suspends the condition."""
    prereg = report.get("preregistration")
    committed = _instant(prereg.get("committed_at")) if isinstance(prereg, dict) else None
    generated = _instant(report.get("generated_at"))
    return None if committed is None or generated is None else committed < generated


def test_the_live_pointer_is_earlier_and_the_string_compare_said_it_was_later() -> None:
    """The real numbers, kept executable.  211 seconds earlier; text ordering says the opposite."""
    committed, generated = "2026-09-09T02:18:34+08:00", "2026-09-08T18:22:04.619948+00:00"
    assert str(committed) > str(generated), "if this flips, the regression this test pins is gone"
    assert _prereg_ok(_report(committed, generated)) is True


def test_a_preregistration_committed_after_the_report_is_refused_however_it_is_spelled() -> None:
    """The direction that matters: a forgery that sorts before the report as text.

    `2026-09-08T20:00:00-05:00` is `2026-09-09T01:00Z` - thirty minutes AFTER a report generated at
    `2026-09-09T00:30Z` - and it sorts first as a string.
    """
    committed, generated = "2026-09-08T20:00:00-05:00", "2026-09-09T00:30:00+00:00"
    assert str(committed) < str(generated), "the string compare would have let this through"
    assert _prereg_ok(_report(committed, generated)) is False


@pytest.mark.parametrize(
    ("committed", "generated"),
    [
        (None, "2026-09-09T00:30:00+00:00"),
        ("2026-09-09T02:18:34+08:00", None),
        ("not a date", "2026-09-09T00:30:00+00:00"),
    ],
)
def test_an_unreadable_stamp_suspends_the_condition_rather_than_deciding_it(
    committed: str | None, generated: str | None
) -> None:
    """An artefact that cannot answer is not an artefact that answers "no"."""
    assert _prereg_ok(_report(committed, generated)) is None


def test_a_naive_stamp_is_read_as_utc_rather_than_refused() -> None:
    """Reports older than the tz-aware writer exist; reading them as UTC is what they meant."""
    naive = _instant("2026-09-08T18:22:04")
    aware = _instant("2026-09-08T18:22:04+00:00")
    assert naive is not None and aware is not None and naive == aware
