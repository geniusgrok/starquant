"""The D-041 bridge has to survive its own expiry on the bash launchd actually runs.

launchd starts the loop as `/bin/bash deploy/run_live.sh` (deploy/com.starquant.live.plist), and /bin/bash
on macOS is 3.2.57.  Before bash 4.4, expanding an EMPTY array under `set -u` is an "unbound variable"
error.  The bridge (2026-09-18) starts from `BRIDGE=()` and appends `--allow-unvalidated` only before
`BRIDGE_UNTIL`, so from that date the array is empty - and the launcher's last line, `"${BRIDGE[@]}"`,
exited 1 before `starquant` ran.  The strict evidence gate the bridge hands back to would never have been
reached, and every relaunch would have died on the same line.

Found 2026-09-25 while preparing for 10-13 (docs/analysis/2026-09-25-october-13-readiness.md): the block
copied out and the date stubbed, 09-25 and 10-12 exit 0, 10-13 and 10-14 exit 1.  That branch had never
executed - the loop's stderr has no `bridge EXPIRED` line - and no test ran the script.

Two checks, because CI cannot reproduce the failure: its bash is 5.x, where the same expansion is legal.

- The text check runs everywhere.  Every `"${NAME[@]}"` in `deploy/*.sh` has to be the guarded form
  `${NAME[@]+"${NAME[@]}"}`, which every bash expands to nothing when the array is empty.
- The behaviour check runs the launcher's own bridge block, date and `exec` stubbed, on this machine's
  /bin/bash.  On the operator's Mac that is the bash that failed.  On CI it still checks the bridge's
  logic: on before the date, off on and after it, the loop's own arguments passed through.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "deploy" / "run_live.sh"
BASH = Path("/bin/bash")

#: `"${NAME[@]}"` not directly inside a `${NAME[@]+...}` guard.
UNGUARDED = re.compile(r'(?<!\+)"\$\{\w+\[@\]\}"')


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Every line that is not a comment: the launcher's own comment quotes the form it replaced."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(number, line) for number, line in enumerate(lines, 1) if not line.lstrip().startswith("#")]


def test_the_text_check_catches_the_form_that_failed() -> None:
    assert UNGUARDED.search('exec starquant live run --armed "${BRIDGE[@]}" "$@"')
    assert not UNGUARDED.search('exec starquant live run --armed ${BRIDGE[@]+"${BRIDGE[@]}"} "$@"')


def test_no_deploy_script_expands_an_array_bash_32_cannot() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for path in sorted((ROOT / "deploy").glob("*.sh"))
        for number, line in _code_lines(path)
        if UNGUARDED.search(line)
    ]
    assert not offenders, (
        f"{offenders}: launchd runs these with macOS /bin/bash 3.2.57, where an empty array under `set -u` "
        'is an unbound variable.  Write ${NAME[@]+"${NAME[@]}"} instead.'
    )


def _bridge_until() -> date:
    match = re.search(r'^BRIDGE_UNTIL="(\d{4}-\d{2}-\d{2})"', LAUNCHER.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "run_live.sh no longer sets BRIDGE_UNTIL; this test has nothing to check"
    return date.fromisoformat(match.group(1))


def _bridge_script() -> str:
    """The launcher's options, then its block from `BRIDGE_UNTIL=` through the `exec`, date and exec stubbed."""
    text = LAUNCHER.read_text(encoding="utf-8")
    options = "set -euo pipefail"
    assert f"\n{options}\n" in text, "the launcher's shell options changed; run the block under the new ones"
    start = text.index("BRIDGE_UNTIL=")
    end = text.index("\n", text.index('exec "$REPO/.venv/bin/starquant"'))
    block = text[start:end]
    for real, stub in (
        ('"$(date -u +%Y-%m-%d)"', '"$TODAY"'),
        ('exec "$REPO/.venv/bin/starquant"', "printf '%s\\n'"),
    ):
        assert real in block, f"run_live.sh no longer contains {real!r}; move this test's stub with it"
        block = block.replace(real, stub)
    return f'{options}\nTODAY="$1"\nshift\n{block}\n'


@pytest.mark.skipif(not BASH.exists(), reason="no /bin/bash on this machine")
@pytest.mark.parametrize(("offset_days", "bridged"), [(-30, True), (-1, True), (0, False), (1, False)])
def test_the_bridge_block_runs_on_both_sides_of_its_date(tmp_path: Path, offset_days: int, bridged: bool) -> None:
    today = (_bridge_until() + timedelta(days=offset_days)).isoformat()
    script = tmp_path / "bridge.sh"
    script.write_text(_bridge_script(), encoding="utf-8")

    run = subprocess.run([str(BASH), str(script), today, "--cycles", "1"], capture_output=True, text=True, check=False)

    assert run.returncode == 0, f"{today}: the launcher would exit before the loop ran: {run.stderr.strip()}"
    arguments = run.stdout.split()
    assert arguments[:2] == ["live", "run"] and "--armed" in arguments
    assert ("--allow-unvalidated" in arguments) is bridged, f"{today}: the bridge is on exactly before its date"
    assert arguments[-2:] == ["--cycles", "1"], "the loop's own arguments still reach it"
    assert ("ACTIVE" if bridged else "EXPIRED") in run.stderr, "every start says which side of the date it is on"
