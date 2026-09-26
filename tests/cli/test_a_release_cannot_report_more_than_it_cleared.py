"""L1-07 again, aimed at the half that reports success: a release can clear less than it says.

`kill_switch_targets` is (configured path, account-scoped path), and the second is derived from the
API key - `account_kill_switches()` reads `venue.api_key_env` out of the environment and returns an
EMPTY tuple when it is not there.  That emptiness is right for a paper or offline run, which has no
account to scope to.  It is not right for `starquant live kill-switch`, where it makes the target list
silently shorter than the operator believes it is.

Measured 2026-09-13T20:44Z against the running demo loop, minutes after `live flatten` had engaged
both paths.  A `starquant live kill-switch --release` run from a shell without the `~/.zshrc` exports
printed exactly one line -

    kill switch released: /Users/.../starquant/.starquant/live/KILL_SWITCH

- exited 0, and left `~/Library/Application Support/starquant/<fingerprint>.KILL_SWITCH` in place.  The
guard reads `any(path.exists())`, so the book stayed stopped while the operator had been told it was
released.  `release_kill_switches`\' own docstring is "Release has to clear both or the operator
cannot get back in"; it does exactly that, faithfully, for every path it is handed.  The defect is
upstream of it, in what the command hands over.

The two directions are deliberately not symmetric:

    --release   refuses before touching anything.  A release that cannot be complete must not report
                a success it did not achieve, so nothing is cleared and the missing export is named.
    --engage    still writes what it can, and then exits non-zero.  A kill switch fails toward
                stopping, so refusing to engage because a shell lacks an export would be much the
                worse failure - but a stop weaker than the operator thinks has to say so out loud.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from starquant_cli.live_cmd import live

ENV = "STARQUANT_TEST_KEY_FOR_THE_SWITCH"
KEY = "Zq7XpLm3VtRw9KdN"


def _profile(tmp_path: Path) -> str:
    path = tmp_path / "profile.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "guards": {"kill_switch_path": str((tmp_path / "KILL_SWITCH").resolve())},
                "venue": {"api_key_env": ENV},
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _both_engaged(tmp_path: Path) -> tuple[Path, Path]:
    """Engage both paths the way `live flatten` does, and hand them back."""
    from starquant_live.lock import account_kill_switch_path

    configured = (tmp_path / "KILL_SWITCH").resolve()
    account = account_kill_switch_path(KEY)
    account.parent.mkdir(parents=True, exist_ok=True)
    for path in (configured, account):
        path.write_text("engaged\n", encoding="utf-8")
    return configured, account


def test_release_without_the_credential_refuses_instead_of_reporting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measured defect.  Nothing is cleared, and the operator is told which export is missing."""
    monkeypatch.setenv(ENV, KEY)
    configured, account = _both_engaged(tmp_path)
    monkeypatch.delenv(ENV)

    result = CliRunner().invoke(live, ["kill-switch", "--release", "--profile", _profile(tmp_path)])

    assert result.exit_code != 0, result.output
    assert ENV in result.output, result.output
    assert configured.exists(), "a refusal must not half-release"
    assert account.exists(), "the account-scoped switch is the one that stayed engaged in production"


def test_release_with_the_credential_clears_both_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path an operator actually wants, unchanged: both files gone, exit 0."""
    monkeypatch.setenv(ENV, KEY)
    configured, account = _both_engaged(tmp_path)

    result = CliRunner().invoke(live, ["kill-switch", "--release", "--profile", _profile(tmp_path)])

    assert result.exit_code == 0, result.output
    assert not configured.exists()
    assert not account.exists()


def test_engage_without_the_credential_still_stops_the_book_and_says_it_is_weaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail toward stopping.  Refusing to engage in an emergency would be the worse failure."""
    monkeypatch.delenv(ENV, raising=False)

    result = CliRunner().invoke(live, ["kill-switch", "--engage", "--profile", _profile(tmp_path)])

    assert (tmp_path / "KILL_SWITCH").resolve().exists(), "the switch must still be engaged"
    assert result.exit_code != 0, result.output
    assert ENV in result.output, result.output


def test_a_profile_with_no_account_to_scope_to_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A paper profile names no `api_key_env`; an empty target tuple is correct there and must pass."""
    monkeypatch.delenv(ENV, raising=False)
    path = tmp_path / "paper.yaml"
    path.write_text(
        yaml.safe_dump({"guards": {"kill_switch_path": str((tmp_path / "KILL_SWITCH").resolve())}}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(live, ["kill-switch", "--engage", "--profile", str(path)])

    assert result.exit_code == 0, result.output
