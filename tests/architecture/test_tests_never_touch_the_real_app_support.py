"""No test may write into the operator's real ``~/Library/Application Support/starquant``.

Measured, not hypothesised.  On 2026-09-07T19:20:11Z a suite run left
``682f6697fa93eca6.KILL_SWITCH`` containing ``engaged`` in the live state directory of a machine
that was trading.  It came from `test_kill_switch_is_per_account.py::test_flatten_engages_every_path`:
that test monkeypatches a FAKE env var name (`STARQUANT_TEST_KEY=some-key`) and points the profile's
`kill_switch_path` at `tmp_path`, so both halves an author would think to isolate were isolated -
and `account_kill_switches()` still reached `account_kill_switch_path(key)` with no `root=`, which
defaults to `APP_SUPPORT` under the real `Path.home()`.  `sha256("some-key")[:16]` is that filename.

Two facts about why it mattered, stated separately because they have different severities:

* What actually happened was harmless to trading.  The loop watches the fingerprint of the key it
  holds (`b9a2701b96f1ae68`), the file carried a foreign one, and `kill_switch_engaged` asks whether
  *its own* paths exist.  The book kept trading, correctly.
* What it left behind was a file named `*.KILL_SWITCH` reading `engaged`, sitting beside the live
  account's lock - the single most misreadable artifact this directory can hold during an incident.
  And the isolation it relied on was the env var NAME being fake.  A test written against the real
  profile's `api_key_env` (`config/live.demo.yaml` names `STARQUANT_BINANCE_API_KEY`, which is exported
  in the operator's interactive shell) would have written the LIVE fingerprint, and because a kill
  switch fails toward stopping, the book would have halted until somebody deleted the file by hand.

The guard is `isolated_app_support` in `tests/conftest.py`: `starquant_live.lock.APP_SUPPORT` is
redirected for every test, the way `isolated_trials_ledger` already redirects the trials ledger, and
for the same reason its docstring gives - the failure mode of forgetting is silent.

This file is what keeps that guard sufficient.  A single redirected constant only covers the package
while the package has exactly ONE anchor to the real home, and only covers the tests while no test
rebuilds the path behind it.  Both are checked below, statically, because a filesystem sweep of the
real directory would race the running loop that writes its logs there.

Stated limit: these rules catch `Path.home()`, `expanduser` and `HOME`.  A test that hardcodes an
absolute path string would not be caught, and nothing here pretends otherwise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    "starquant_shared",
    "starquant_data",
    "starquant_alpha",
    "starquant_exchange",
    "starquant_governance",
    "starquant_live",
    "starquant_cli",
)

# The one file allowed to know where the real home is.  It is the module whose entire subject is
# addressing an account rather than a working directory, so the anchor belongs there and nowhere else.
HOME_ANCHOR = "starquant_live/lock.py"


def _real_app_support() -> Path:
    """Recomputed here rather than imported: importing it is what the guard replaces."""
    return Path.home() / "Library" / "Application Support" / "starquant"


def _home_references(path: Path) -> list[str]:
    """Lines that resolve the user's home directory, by AST rather than by grepping for a word.

    Prose is not a violation: two of these test files discuss `Application Support` in their
    docstrings, and a substring scan would have to special-case them - which is how a rule starts
    being edited to fit its exceptions.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        # Path.home() / os.path.expanduser(...) / Path(...).expanduser()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"home", "expanduser"}:
                hits.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.attr}()")
        # os.environ["HOME"] / os.environ.get("HOME") / os.getenv("HOME")
        elif isinstance(node, ast.Constant) and node.value == "HOME":
            hits.append(f"{path.relative_to(ROOT)}:{node.lineno}: 'HOME'")
    return hits


def test_the_guard_redirects_app_support_away_from_the_real_home() -> None:
    """The fix itself: while a test runs, the constant does not point at the operator's directory."""
    from starquant_live import lock

    assert _real_app_support() != lock.APP_SUPPORT, (
        "starquant_live.lock.APP_SUPPORT still points at the operator's real Application Support "
        "directory during tests; the isolated_app_support guard in tests/conftest.py is not active"
    )


def test_both_account_paths_land_under_the_redirected_root() -> None:
    """Redirecting the constant is only worth anything if every caller reads it at call time."""
    from starquant_live.lock import account_kill_switch_path, account_lock_path

    real = _real_app_support()
    for resolved in (account_kill_switch_path("some-key"), account_lock_path("some-key")):
        assert resolved.parent != real, f"{resolved} is inside the operator's real directory"


@pytest.mark.parametrize("package", PACKAGES)
def test_the_packages_have_exactly_one_anchor_to_the_real_home(package: str) -> None:
    """What makes one redirected constant enough.

    A second `Path.home()` anywhere in `starquant_*` would be invisible to the guard, and the suite
    would go on passing while tests wrote to the real directory through the new path.
    """
    offenders = [
        hit
        for source in sorted((ROOT / package).rglob("*.py"))
        if source.relative_to(ROOT).as_posix() != HOME_ANCHOR
        for hit in _home_references(source)
    ]
    assert not offenders, (
        f"{package} resolves the real home outside {HOME_ANCHOR}, which the test guard cannot "
        "redirect:\n" + "\n".join(offenders)
    )


def test_no_test_rebuilds_the_path_behind_the_guard() -> None:
    """And what keeps it enough on the other side: no test may reach the real home itself.

    This file is exempt because checking that the guard moved the path is precisely its job.
    """
    offenders = [
        hit
        for source in sorted((ROOT / "tests").rglob("*.py"))
        if source != Path(__file__).resolve()
        for hit in _home_references(source)
    ]
    assert not offenders, "tests resolve the real home directly, bypassing the guard:\n" + "\n".join(offenders)
