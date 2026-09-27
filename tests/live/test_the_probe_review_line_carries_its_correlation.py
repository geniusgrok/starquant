"""M-014 was computed every day and read by nothing, and the review it decides is 30 days long.

`probe_correlation`'s own docstring states the criterion: "If the live income series correlate
closely, the sleeve is a tilt and its separate risk budget is a fiction, whatever its own P&L says."
The daily report printed the number in its own section and printed the probe's `days=10.00/30`
countdown in another, and nothing put them on the same line - so the one moment the correlation
decides something (the 30-day review, due 2026-10-02) would arrive with the P&L in front of the
operator and the correlation two sections away.

2026-09-12 reading: tsmom~flow +0.82 over 182 bars.
"""

from __future__ import annotations

from starquant_live.reports import _probe_correlation_note


def _payload(pairs: dict) -> dict:
    return {"probe_correlation": pairs}


def test_the_pair_for_this_probe_lands_on_its_line() -> None:
    note = _probe_correlation_note(_payload({"tsmom~flow": {"correlation": 0.8234, "bars": 182}}), "flow")
    assert note == " corr(tsmom~flow)=+0.82 over 182 bars"


def test_an_unreadable_correlation_adds_nothing_rather_than_a_zero() -> None:
    """The house rule: a criterion with no reading is not a reading of zero."""
    assert _probe_correlation_note(_payload({"tsmom~flow": {"correlation": None, "bars": 3}}), "flow") == ""
    assert _probe_correlation_note(_payload({}), "flow") == ""
    assert _probe_correlation_note(_payload({"tsmom~flow": {"correlation": 0.8, "bars": 9}}), "") == ""


def test_the_strongest_pair_wins_when_a_probe_faces_more_than_one_book() -> None:
    """With a third strategy the review needs the worst number, not whichever sorted first."""
    note = _probe_correlation_note(
        _payload(
            {
                "tsmom~flow": {"correlation": 0.31, "bars": 182},
                "xsmom~flow": {"correlation": -0.94, "bars": 182},
            }
        ),
        "flow",
    )
    assert note == " corr(xsmom~flow)=-0.94 over 182 bars"


def test_a_pair_naming_another_probe_is_not_borrowed() -> None:
    assert _probe_correlation_note(_payload({"tsmom~carry": {"correlation": 0.9, "bars": 99}}), "flow") == ""
