"""DL-L1 at the command line: arming the loop, and losing the race politely.

Two things the lock alone cannot do.

*Arming.*  ``live run`` sends real orders by default; the only thing between a worktree experiment
and the live account was remembering to type ``--dry-run``.  Non-dry-run now requires ``--armed``,
which is a sentence the operator has to write, not one they have to remember not to omit.

*Losing.*  A refused instance exits **0**.  Under ``KeepAlive.SuccessfulExit=false`` a non-zero exit
would be relaunched every ThrottleInterval and would alert every time, so the failure mode of the
guard would be an alert storm about the guard working correctly (KILL-R20(d)).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

import starquant_cli.live_cmd as live_cmd
from starquant_cli import main
from starquant_live.lock import LockBusy, SingleInstanceLock
from tests.live.fakes import UNREACHABLE, paper_venue_from

ROOT = Path(__file__).resolve().parents[2]
PROFILE = str(ROOT / "config/live.demo.yaml")


def test_a_non_dry_run_without_arming_is_refused() -> None:
    result = CliRunner().invoke(main, ["live", "run", "--profile", PROFILE, "--cycles", "1"])

    assert result.exit_code != 0
    assert "--armed" in result.output


def test_dry_run_needs_no_arming() -> None:
    """The safe mode must stay one word, or people will stop using it."""
    result = CliRunner().invoke(
        main, ["live", "run", "--profile", PROFILE, "--dry-run", "--cycles", "0", "--symbols", "BTCUSDT"]
    )

    assert "--armed" not in result.output


def test_paper_needs_no_arming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Asserting the exit code, not only the absence of a word: a command that died on the network
    also has no "--armed" in its output, so the old assertion held whether or not paper mode worked.

    That is how this test came to make a real `exchangeInfo` request on every offline run (0.55s to a
    host GitHub's runners are geo-blocked from) without anyone noticing - the same fetch that made
    `test_breaker_reaches_the_limit` red in CI for five consecutive runs.  The host is a dead port
    here so the request cannot happen, and the venue is the real `PaperVenue` over a canned payload.
    """
    profile = yaml.safe_load(Path(PROFILE).read_text(encoding="utf-8"))
    profile["market_data"]["rest_url"] = UNREACHABLE
    profile["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    monkeypatch.setattr(live_cmd, "_paper_venue", paper_venue_from())

    result = CliRunner().invoke(
        main,
        ["live", "run", "--profile", str(profile_path), "--paper", "--cycles", "0", "--symbols", "BTCUSDT"],
    )

    assert result.exit_code == 0, result.output
    assert "--armed" not in result.output


def test_the_armed_flag_is_documented_as_the_live_money_switch() -> None:
    result = CliRunner().invoke(main, ["live", "run", "--help"])

    assert "--armed" in result.output
    assert result.exit_code == 0


def test_a_refused_instance_exits_zero_and_names_the_winner(tmp_path: Path) -> None:
    """The whole point: launchd must not relaunch the loser every 60 seconds."""
    from starquant_cli.live_cmd import refuse_second_instance

    lock_path = tmp_path / "acct.lock"
    with SingleInstanceLock(lock_path, holder="pid=42 repo=/Users/x/starquant"):
        try:
            with SingleInstanceLock(lock_path, holder="pid=43 repo=/worktree"):
                raise AssertionError("the second lock must not be granted")  # pragma: no cover
        except LockBusy as busy:
            code, message = refuse_second_instance(busy)

    assert code == 0
    assert "pid=42" in message


def test_the_launcher_arms_the_loop() -> None:
    """run_live.sh is the only caller that should be armed, and it has to say so explicitly."""
    launcher = (ROOT / "deploy/run_live.sh").read_text(encoding="utf-8")

    assert "--armed" in launcher
