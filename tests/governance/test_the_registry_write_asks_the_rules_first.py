"""`governance apply` wrote the registry without asking a single governance rule (2026-09-09 audit).

The largest instance of this repository's recurring defect, and the one with the machine's hand on it.
`apply` asked two questions: is the autonomy switch on, and does the startup gate accept the result.
That gate - `registry_evidence_problems` - checks evidence pointers, their sha256 and the construction
each was produced under.  It is a per-ENTRY check, so it cannot see a sum, a count, a calendar or a
history, which is precisely what R3, R4, R5, R7 and K-EX14 are.

So §3's whole precondition list for `queued -> probe` was decorative on the one code path that
promotes, and §0's acceptance of AR-18 - no human confirmation point, because "R6 回滚 + Canary + R3
预算 + P&L stop" carries the risk - was resting on two controls that had no caller anywhere in the
tree.  `lifecycle.apply` and `state.write` still have none; this closes the half that decides.

The first test below is the one that matters: two sleeves, each matching its own evidence exactly, so
the startup gate passes every entry it looks at while the book hands 2/3 of itself to unproven code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from starquant_alpha.registry import parse_registry
from starquant_governance.admission import WINDOW_ANCHOR, admit, clean_days, exposure, registry_refusals, window_index
from starquant_governance.lifecycle import Book, Candidate, State
from starquant_governance.policy import Policy

POLICY = Policy()
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _registry(sleeves: dict[str, float], *, main: str = "tsmom") -> Any:
    payload: dict[str, Any] = {
        "version": 1,
        "ensemble": {"method": "mean", "turnover_penalty": 0.0},
        "books": {name: {"fraction": fraction} for name, fraction in sleeves.items()},
        "strategies": [{"id": main, "enabled": True, "weight": 1.0}],
    }
    for index, (name, _fraction) in enumerate(sorted(sleeves.items())):
        payload["strategies"].append(
            {"id": ("flow", "xsmom", "carry")[index], "enabled": True, "weight": 1.0, "book": name}
        )
    return parse_registry(payload)


def _cycles(days: float, *, digest: str = "aaaa", now: datetime = NOW) -> list[dict[str, Any]]:
    start = now - timedelta(days=days)
    return [
        {"at": (start + timedelta(hours=hour)).isoformat(), "construction": digest}
        for hour in range(int(days * 24) + 1)
    ]


def _healthy_shadow(cycles: int = 200) -> list[dict[str, Any]]:
    return [
        {"at": f"2026-10-{1 + i // 24:02d}T{i % 24:02d}:00:00+00:00", "construction": "aaaa", "phase": "OK"}
        for i in range(cycles)
    ]


def _book(**kwargs: Any) -> Book:
    base = {"window": window_index(POLICY, now=NOW), "candidates": {}}
    return Book(**{**base, **kwargs})


# --- the hole, stated as the thing the per-entry gate cannot see ------------------------------


def test_two_sleeves_each_matching_their_own_evidence_still_break_the_budget() -> None:
    """R3 is a SUM.  Every per-entry check in the tree passes this registry; the book is 2/3 unproven."""
    proposed = _registry({"flow_short": 1 / 3, "xsmom_probe": 1 / 3})
    problems = registry_refusals(proposed, POLICY)
    assert problems, "two sleeves at 1/3 each is 2/3 of the book against a 1/3 cap"
    assert any("0.6667" in problem and "0.3333" in problem for problem in problems), problems
    # and the same file read entry by entry looks fine: each sleeve is inside its own bounds
    assert all(0.0 < share <= 1.0 for _book, share in exposure(proposed).values())


def test_the_budget_check_does_not_need_the_state_to_be_right() -> None:
    """`state.load` reads a missing file as an EMPTY book, and an empty book is headroom, not safety.

    Measured on the trading machine 2026-09-09 with no state file: a second 1/3 probe was ALLOWED on
    top of the flow probe already running.  So the R3 sum is computed from the proposed BYTES, which
    are what the loop will hold after the restart, and it holds with the state absent or wrong.
    """
    proposed = _registry({"flow_short": 1 / 3, "xsmom_probe": 1 / 3})
    admission = admit(_registry({"flow_short": 1 / 3}), proposed, book=Book(), policy=POLICY, now=NOW)
    assert not admission.allowed
    assert any("R3" in reason for reason in admission.reasons), admission.reasons


def test_three_sleeves_break_the_count_as_well_as_the_share() -> None:
    proposed = _registry({"a": 0.1, "b": 0.1, "c": 0.1})
    problems = registry_refusals(proposed, POLICY)
    assert any("3 sleeves" in problem for problem in problems), problems
    assert not any("budget share" in problem for problem in problems), "0.3 is inside the 1/3 cap"


# --- the facts that must be measured, and must fail closed when they cannot be ----------------


def test_the_canary_that_never_ran_is_not_a_canary_that_passed() -> None:
    """ "Could not be computed" is not "passed" - the rule the drawdown ladder already follows."""
    before = _registry({})
    after = _registry({"flow_short": 1 / 3})
    book = _book(candidates={"flow": Candidate("flow", State.QUEUED, fraction=1 / 3)})
    admission = admit(before, after, book=book, policy=POLICY, cycles=_cycles(45), shadow=[], now=NOW)
    assert not admission.allowed
    assert any("canary" in reason for reason in admission.reasons), admission.reasons
    assert "no shadow record" in str(admission.measured["canary"])


def test_a_promotion_inside_the_thirty_day_clock_is_refused(caplog: pytest.LogCaptureFixture) -> None:
    """K-EX14: the window a promotion resets has to have run out before the next one starts."""
    before, after = _registry({}), _registry({"flow_short": 1 / 3})
    book = _book(candidates={"flow": Candidate("flow", State.QUEUED, fraction=1 / 3)})
    admission = admit(before, after, book=book, policy=POLICY, cycles=_cycles(11), shadow=_healthy_shadow(), now=NOW)
    assert not admission.allowed
    assert any("K-EX14" in reason for reason in admission.reasons), admission.reasons
    assert admission.measured["clean_days"] == pytest.approx(11.0, abs=0.1)


def test_the_clock_reads_the_canonical_construction_not_the_raw_digest() -> None:
    """Without the aliases a renamed field resets M-010 and costs the operator thirty days for nothing.

    Measured on the live record 2026-09-09: raw 0.79 days, canonical 5.00.  Same file, same moment.
    """
    rows = _cycles(30, digest="old") + _cycles(1, digest="new")
    raw, _why = clean_days(rows, now=NOW)
    canonical, why = clean_days(rows, aliases={"new": "old"}, now=NOW)
    assert raw < 1.5 and canonical > 29.0, (raw, canonical)
    assert "old" in why


def test_a_queue_with_no_recorded_order_refuses_rather_than_picking_one() -> None:
    before, after = _registry({}), _registry({"flow_short": 1 / 3})
    book = _book(
        candidates={
            "flow": Candidate("flow", State.QUEUED, fraction=1 / 3),
            "carry": Candidate("carry", State.QUEUED, fraction=1 / 3),
        }
    )
    admission = admit(before, after, book=book, policy=POLICY, cycles=_cycles(45), shadow=_healthy_shadow(), now=NOW)
    assert any("head of the queue" in reason for reason in admission.reasons), admission.reasons
    assert "carry" in str(admission.measured["flow_queue"])


# --- and what it must NOT block ---------------------------------------------------------------


def test_a_change_that_only_reduces_exposure_is_never_held_for_a_window() -> None:
    """§3's fast paths go the other way: a stop is immediate, and must not wait for a batch window."""
    before, after = _registry({"flow_short": 1 / 3}), _registry({})
    admission = admit(before, after, book=Book(), policy=POLICY, cycles=[], shadow=[], now=NOW)
    assert admission.allowed and admission.promoting == (), admission.reasons


def test_a_clean_promotion_passes_every_layer() -> None:
    """The gate has to be able to say yes, or it is a stop sign rather than a rule."""
    before, after = _registry({}), _registry({"flow_short": 1 / 3})
    book = _book(candidates={"flow": Candidate("flow", State.QUEUED, fraction=1 / 3)})
    admission = admit(before, after, book=book, policy=POLICY, cycles=_cycles(45), shadow=_healthy_shadow(), now=NOW)
    assert admission.allowed, admission.reasons
    assert admission.promoting == ("flow",)


# --- the calendar, because the counter never ticked --------------------------------------------


def test_the_window_rolls_on_the_calendar_rather_than_on_a_counter_nobody_increments() -> None:
    """`Book.open_next_window()` has never had a production caller, so the counter has read 0 forever.

    Derived from the clock instead: a state that stopped being maintained in September cannot make a
    promotion in November look like the second one this window.
    """
    stale = Book(
        window=0, promotions_this_window=1, candidates={"flow": Candidate("flow", State.QUEUED, fraction=1 / 3)}
    )
    later = datetime.fromisoformat(WINDOW_ANCHOR) + timedelta(days=95)
    admission = admit(
        _registry({}),
        _registry({"flow_short": 1 / 3}),
        book=stale,
        policy=POLICY,
        cycles=_cycles(45, now=later),
        shadow=_healthy_shadow(),
        now=later,
    )
    assert admission.allowed, admission.reasons
    assert "counters reset by the calendar" in str(admission.measured["window"])


def test_a_second_promotion_inside_one_window_is_still_refused() -> None:
    """R4 has to survive the calendar fix, or the fix traded one dead rule for another."""
    index = window_index(POLICY, now=NOW)
    used = Book(
        window=index,
        promotions_this_window=1,
        candidates={"flow": Candidate("flow", State.QUEUED, fraction=1 / 3)},
    )
    admission = admit(
        _registry({}),
        _registry({"flow_short": 1 / 3}),
        book=used,
        policy=POLICY,
        cycles=_cycles(45),
        shadow=_healthy_shadow(),
        now=NOW,
    )
    assert not admission.allowed
    assert any("R4" in reason for reason in admission.reasons), admission.reasons


# --- the command, because a command nothing exercises is the defect this file is about ----------


def test_the_canary_command_reads_a_soak_and_says_pass_or_fail(tmp_path: Any) -> None:
    """`governance canary` shipped broken on its first run: `load_jsonl` takes text, not a Path.

    Nothing caught it, because adding a command to make a module reachable and then not exercising
    the command is the same defect one level out.  So the command has a test, and the test drives it
    the way the operator does - through the CLI, on files.
    """
    import json

    from click.testing import CliRunner

    from starquant_cli.governance_cmd import canary_cmd

    shadow, live = tmp_path / "shadow", tmp_path / "live"
    for directory in (shadow, live):
        directory.mkdir()
    rows = [
        {"at": f"2026-10-01T{hour:02d}:00:00+00:00", "phase": "OK", "construction": "aaaa", "universe": ["BTCUSDT"]}
        for hour in range(24)
    ]
    (live / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    missing = CliRunner().invoke(canary_cmd, ["--shadow-dir", str(shadow), "--state-dir", str(live)])
    assert missing.exit_code != 0 and "no shadow record" in missing.output + str(missing.exception)

    # a short soak: every deployment check passes, and `soak` fails on the count alone
    (shadow / "cycles.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    short = CliRunner().invoke(canary_cmd, ["--shadow-dir", str(shadow), "--state-dir", str(live)])
    assert "FAIL  soak" in short.output and "24/168" in short.output
    assert "UNHEALTHY" in short.output and short.exit_code == 1
    assert short.output.count("PASS") == 6, short.output


def test_a_renamed_field_does_not_fail_the_canary_for_a_deployment_that_did_not_change() -> None:
    """`construction_stable` counted RAW digests, and a no-op rename moves the hash.

    Measured 2026-09-09 against the armed loop's own record: 6 distinct digests raw, 3 canonical.
    A canary that fails a candidate for `unit_mode` being renamed is the false negative KILL-AR-04
    warns about, arriving from the other direction.
    """
    from starquant_governance.canary import evaluate as evaluate_canary

    rows = [
        {"at": f"2026-10-01T{hour:02d}:00:00+00:00", "phase": "OK", "construction": "old" if hour < 12 else "new"}
        for hour in range(200)
    ]
    raw = {check.name: check.passed for check in evaluate_canary(rows, rows).checks}
    aliased = {check.name: check.passed for check in evaluate_canary(rows, rows, aliases={"new": "old"}).checks}
    assert not raw["construction_stable"] and aliased["construction_stable"]
