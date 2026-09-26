"""M-003's second threshold, which had no instrument (refactor plan §11).

The plan set three numbers under M-003: non-alpha lines <= 6,000, the suite under **30 seconds**, and
zero non-alpha files touched to change one signal.  Only the first was ever measured, by
`test_source_budget.py` - whose own docstring records what happens to the other kind:

    "Nothing ever measured it, so the budget was breached without anyone noticing."

That is exactly what happened here.  Measured 2026-09-07: **45.3 / 47.0 / 47.1 seconds** over three
consecutive idle runs, against a threshold of 30.  Breached by half, silently, for some unknown span.

**Why this ratchet is loose where the line ratchet is exact, and what makes up the difference.**  Lines
are deterministic; wall clock is not.  The three runs above spread 1.8s (~4%) on an idle Apple-silicon
laptop, and CI is `ubuntu-latest`, commonly two to three times slower for this numpy-bound suite.  A
ceiling set snugly at 47 would fail runs that changed nothing, and a gate that cries wolf gets deleted -
returning us to no instrument at all, the state this file exists to leave.  So the ceiling catches a
**step change**, not a drift: a sleep, a network call, an accidental O(n^2) fixture.

Drift is real too, and a loose gate cannot see it - so the measurement is **printed on every full run**
whether it passes or not.  The gate answers "did something break"; the printed line is what lets a human
notice 47 becoming 60 over a month.  Splitting the two is the point: neither number pretends to be the
other.

The plan's 30 seconds is kept in `PLAN_SECONDS` and reported as breached rather than quietly redefined,
the same way `PLAN_BUDGET` keeps the 6,000.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.architecture.suite_duration import (
    CEILING_SECONDS,
    FULL_SUITE_MIN,
    PLAN_SECONDS,
    measurement_line,
    suite_verdict,
)


def test_a_full_run_inside_the_ceiling_changes_nothing() -> None:
    status, message = suite_verdict(duration=CEILING_SECONDS - 1, exitstatus=0, collected=FULL_SUITE_MIN)
    assert status == 0
    assert message is None


def test_a_full_run_over_the_ceiling_fails_a_session_that_would_have_passed() -> None:
    status, message = suite_verdict(duration=CEILING_SECONDS + 1, exitstatus=0, collected=FULL_SUITE_MIN)
    assert status != 0
    assert message is not None


def test_the_message_names_the_measurement_the_ceiling_and_the_plans_threshold() -> None:
    # Relative to the ceiling, not a literal 123.4: that literal was a breach at 120 and stopped being
    # one the moment the ceiling was recalibrated, so the test measured the constant rather than the
    # message.  This one is a breach at any ceiling.
    duration = CEILING_SECONDS + 3.4
    _, message = suite_verdict(duration=duration, exitstatus=0, collected=FULL_SUITE_MIN)
    assert message is not None
    # A gate that only says "too slow" gets raised without thought; one that shows all three numbers
    # makes the choice - speed it up, or raise the ceiling in the commit that says why - an informed one.
    assert f"{duration:.1f}" in message
    assert str(CEILING_SECONDS) in message
    assert str(PLAN_SECONDS) in message


def test_the_measurement_is_printed_even_when_the_run_passes() -> None:
    """Drift is invisible to a ceiling this loose, so the number itself is always shown."""
    line = measurement_line(46.2)
    assert "46.2" in line
    assert str(PLAN_SECONDS) in line


def test_a_filtered_run_is_not_measured() -> None:
    """`pytest tests/live` is not the thing the plan put a number on, so it is not judged by it."""
    status, message = suite_verdict(duration=CEILING_SECONDS * 10, exitstatus=0, collected=FULL_SUITE_MIN - 1)
    assert status == 0
    assert message is None


def test_an_already_failing_run_keeps_its_own_exit_status() -> None:
    """A slow suite must never overwrite the status of a suite that also has a real failure in it.

    The operator reads the exit code first and the log second; turning a test failure into a timing
    failure would hide the thing that actually needs fixing.
    """
    status, message = suite_verdict(duration=CEILING_SECONDS * 2, exitstatus=2, collected=FULL_SUITE_MIN)
    assert status == 2
    assert message is not None  # still SAID, just not promoted over the real failure


def test_the_plans_thirty_seconds_is_recorded_as_breached_rather_than_redefined() -> None:
    """The plan's number stays visible next to the number we actually hold ourselves to."""
    assert PLAN_SECONDS == 30
    assert CEILING_SECONDS > PLAN_SECONDS


def test_the_hook_actually_fails_a_slow_session() -> None:
    """The wiring, not the arithmetic: a real pytest session must come back non-zero.

    Everything above tests a pure function, which would keep passing if `pytest_sessionfinish` were
    never called - the shape of failure this repository keeps finding (a correct algorithm with zero
    call sites).  So run a real session, in a temp rootdir, with the limits set to catch anything.
    """
    root = Path(__file__).resolve().parents[2]
    scratch = root / ".pytest-duration-wiring"
    scratch.mkdir(exist_ok=True)
    try:
        (scratch / "conftest.py").write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            "from tests.architecture.suite_duration import (  # noqa: F401\n"
            "    pytest_configure,\n"
            "    pytest_sessionfinish,\n"
            "    set_limits,\n"
            ")\n"
            "set_limits(ceiling=0.0, full_suite_min=1)\n",
            encoding="utf-8",
        )
        (scratch / "test_trivial.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(scratch)],
            cwd=scratch,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, result.stdout + result.stderr
        assert str(PLAN_SECONDS) in result.stdout, result.stdout
    finally:
        for path in sorted(scratch.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        scratch.rmdir()
