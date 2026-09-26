"""O4: `membership_summary` reports dead slots when it can measure them, and says nothing when it cannot.

A 30-day trailing quote volume keeps ranking a symbol that has already stopped quoting, so it can hold
one of `top_n` slots with no data behind it for up to a month.  Measured on the real point-in-time
table: LUNAUSDT's last 1h bar is 2022-05-13 and it stayed a member until 2022-06-10 - 28 refreshes -
and across 2,042 refreshes / 35,899 member-refresh slots there are 109 such slots (0.30%), on 104
refresh days (5.1%), worst 2 of 18-20 over 2026-07-18..22.

0.30% changes nothing.  The point is D-035's: for a family of defect like "N-choose-K degenerates in
some periods", a measured 0.30% and an unmeasured unknown are different answers, and only one of them
can be argued with.  Which is also why the keys are ABSENT rather than 0.0 when no `available` frame is
supplied - a metric that could not be computed must never read as one that passed.
"""

from __future__ import annotations

import pandas as pd

from starquant_data.pool import membership_summary

DEAD_KEYS = ("dead_slots", "dead_slot_share", "worst_refresh")


def _tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2022-05-01", periods=4, freq="MS", tz="UTC")
    membership = pd.DataFrame(
        {"BTCUSDT": [True] * 4, "ETHUSDT": [True] * 4, "LUNAUSDT": [True, True, False, False]}, index=index
    )
    available = pd.DataFrame(
        {"BTCUSDT": [True] * 4, "ETHUSDT": [True] * 4, "LUNAUSDT": [True, False, False, False]}, index=index
    )
    return membership, available


def test_without_an_available_frame_the_keys_are_absent_and_not_zero() -> None:
    membership, _ = _tables()
    summary = membership_summary(membership)
    assert not any(key in summary for key in DEAD_KEYS), "an unmeasured share must not read as 0.0"
    assert summary["refreshes"] == 4  # the rest of the summary is unchanged


def test_a_member_refresh_slot_with_no_data_is_counted_and_located() -> None:
    membership, available = _tables()
    summary = membership_summary(membership, available=available)
    assert summary["dead_slots"] == 1  # LUNAUSDT is still a member on 2022-06-01 with no bars behind it
    assert summary["dead_slot_share"] == 1 / 10  # 10 member-refresh slots in this table
    assert summary["worst_refresh"] == {"at": str(membership.index[1]), "dead": 1, "members": 3}
    # A symbol that is NOT a member cannot occupy a slot, so its missing data is not a dead slot.
    assert (
        membership_summary(membership, available=available.assign(BTCUSDT=[True, True, True, True]))["dead_slots"] == 1
    )


def test_a_slot_the_caller_cannot_speak_for_counts_as_dead() -> None:
    """The reindex fills False, not True: an unknown slot is the slot in question, not a passing one."""
    membership, available = _tables()
    summary = membership_summary(membership, available=available.drop(columns=["LUNAUSDT"]))
    assert summary["dead_slots"] == 2  # both of LUNAUSDT's memberships, now unattested rather than one
    assert summary["dead_slot_share"] == 2 / 10


def test_a_table_with_no_member_slots_reports_no_share_at_all() -> None:
    index = pd.date_range("2024-01-01", periods=2, freq="MS", tz="UTC")
    empty = pd.DataFrame({"A": [False, False]}, index=index)
    summary = membership_summary(empty, available=pd.DataFrame({"A": [True, True]}, index=index))
    assert not any(key in summary for key in DEAD_KEYS), "0/0 is not 0.0"
    assert membership_summary(pd.DataFrame())["refreshes"] == 0
