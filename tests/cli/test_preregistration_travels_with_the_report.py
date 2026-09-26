"""DL-G9 / T-G9-1: the pre-registration is a field in the artefact, not a paragraph in a log.

DL-K3 asks that a pre-registration commit be earlier than the report it registers.  Until now the only
record of that was a RESEARCH_LOG paragraph plus a reader willing to run `git show`, so the Phase 0
governance replay had to suspend the condition for all 48 archived reports - the rule could never fire,
for any artefact, ever.

The commit's OWN timestamp is what is recorded, not the moment `--prereg` was typed.  Recording the
latter would make the ordering trivially true and the check worthless.
"""

from __future__ import annotations

import subprocess

import click
import pytest

from starquant_cli.research_cmd import _preregistration


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def test_a_declared_commit_is_recorded_with_its_own_commit_time() -> None:
    recorded = _preregistration("HEAD")
    assert recorded is not None
    assert recorded["commit"] == _head()
    # The commit time, not now: an ISO string that git produced, ending in an offset.
    assert recorded["committed_at"][:4] == "20" + recorded["committed_at"][2:4]
    assert "T" in recorded["committed_at"]


def test_declaring_none_is_null_rather_than_a_guess() -> None:
    """A run with no pre-registration says so; the replay then suspends the condition for it explicitly."""
    assert _preregistration("") is None
    assert _preregistration("   ") is None


def test_a_commit_that_does_not_exist_is_refused_rather_than_silently_dropped() -> None:
    """A run claiming a pre-registration it cannot name is worse than one claiming none."""
    with pytest.raises(click.BadParameter):
        _preregistration("this-is-not-a-commit-ish-that-resolves")
