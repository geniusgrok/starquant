"""The deploy plists have to be valid XML, not merely acceptable to one lenient parser.

`deploy/com.starquant.paper-l3.plist` shipped on 2026-09-09 with `--paper` inside an XML comment.  Two
dashes in a row end a comment, so the file was not well-formed XML; `plistlib` refuses it outright.
launchd loaded it anyway - CFPropertyList is more forgiving than expat - so the soak ran and nothing
said a word.  That is the defect shape the 2026-09-09 audit found seventeen times over: something that
works because of what a particular reader tolerates rather than because it is correct.

What it would have cost: the L3 soak is a seven-day accumulating criterion, and a plist that stops
loading stops the soak silently.  The comment in that very file says a soak that is not running
accumulates nothing.

**This file checks the repo copies only.**  The file launchd actually reads lives under the operator's
real `~/Library/LaunchAgents`, and `test_tests_never_touch_the_real_app_support.py` forbids any test
from resolving the real home - categorically, because a static guard cannot tell a read from a write
and should not have to.  So the installed copies are checked by `deploy/run_check.sh`, which is the
thing that legitimately runs against this machine.  The division is: the suite guards the source, the
hourly check guards the deployment.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"

REPO_PLISTS = sorted(DEPLOY.glob("*.plist"))


def test_the_repo_ships_the_plists_the_deployment_needs() -> None:
    """A guard over an empty glob passes forever; name the files it is meant to cover."""
    assert {path.name for path in REPO_PLISTS} >= {
        "com.starquant.check.plist",
        "com.starquant.data.plist",
        "com.starquant.live.plist",
        "com.starquant.paper-l3.plist",
    }


@pytest.mark.parametrize("path", REPO_PLISTS, ids=lambda path: path.name)
def test_every_deploy_plist_parses_as_xml(path: Path) -> None:
    payload = plistlib.loads(path.read_bytes())
    # A plist that parses but names no program is loadable and useless, which is the same class of
    # quiet failure with a different symptom.
    assert payload.get("Label"), f"{path.name} carries no Label"
    assert payload.get("ProgramArguments"), f"{path.name} carries no ProgramArguments"
