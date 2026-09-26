"""The one human confirmation point Q9 did NOT remove.

Q9 (operator ruling, 2026-09-08) took the confirmation point off a SINGLE promotion: the machine
writes the registry from the first transaction, because "人容易犯错".  It did not take off the
decision to let the machine write at all - the plan keeps exactly three human points, and this is one
of them (governance enable/disable).

The asymmetry is deliberate and is what these tests hold: enabling asks, disabling never does.
Stopping is always allowed, and a stop that needs a confirmation is a stop that arrives late.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from starquant_cli import main


def _run(*args: str) -> object:
    return CliRunner().invoke(main, ["governance", *args])


def test_apply_is_refused_while_the_switch_is_off(tmp_path: Path) -> None:
    registry = tmp_path / "alpha_registry.yaml"
    registry.write_text("version: 1\n", encoding="utf-8")
    proposed = tmp_path / "proposed.yaml"
    proposed.write_text("version: 1\n# changed\n", encoding="utf-8")

    result = _run("apply", "--proposed", str(proposed), "--registry", str(registry), "--root", str(tmp_path))

    assert result.exit_code != 0
    assert "autonomy is disabled" in result.output
    assert registry.read_text(encoding="utf-8") == "version: 1\n", "a refused apply must not have written"
    assert not (tmp_path / "governance" / "transactions.jsonl").exists()


def test_enabling_asks_and_disabling_does_not(tmp_path: Path) -> None:
    runner = CliRunner()
    switch = tmp_path / "governance" / "ENABLED"

    refused = runner.invoke(main, ["governance", "enable", "--root", str(tmp_path)], input="n\n")
    assert refused.exit_code != 0 and not switch.exists()

    accepted = runner.invoke(main, ["governance", "enable", "--root", str(tmp_path)], input="y\n")
    assert accepted.exit_code == 0 and switch.exists()

    # No prompt, no input: stopping always may.
    stopped = runner.invoke(main, ["governance", "disable", "--root", str(tmp_path)])
    assert stopped.exit_code == 0 and not switch.exists()


def test_disabling_something_already_off_is_not_an_error(tmp_path: Path) -> None:
    """An operator reaching for the off switch twice must not be told they did it wrong."""
    assert CliRunner().invoke(main, ["governance", "disable", "--root", str(tmp_path)]).exit_code == 0


def test_status_says_which_rules_and_whether_it_may_write(tmp_path: Path) -> None:
    result = _run("status", "--root", str(tmp_path))
    assert result.exit_code == 0
    assert "autonomy DISABLED" in result.output
    assert "policy" in result.output and "digest=" in result.output
