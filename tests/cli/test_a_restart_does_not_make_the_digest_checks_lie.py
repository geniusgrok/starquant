"""A restart must not make DL-Q0 / R9 report a divergence the restart just resolved.

``cycles.jsonl`` is append-only and carries no process identity, so its newest digest row belongs to
whichever process last completed a cycle - after a restart, the dead one.  Reading that back as "what
the loop is running" compares the previous process's answer against the current file.

Measured 2026-09-14 on the real loop: the host came back at 19:00:14Z, the loop at 19:10:55Z, the
19:11:19Z bar was SKIPPED (679s late) and wrote no governance digest, so the newest one was still
18:00:29Z's ``75764f646ca6`` from the dead process.  ``policy.py`` had been edited at 17:50Z - eighty
minutes BEFORE that process started - so the running process held ``d62ac59fa95c``, exactly what the
file said.  The check reported them as different.  ``com.starquant.check`` fires at :10, inside that
window every time, and ``state.restarts`` is past 43.

bc986ec3 found this for the registry and put the digests on the restart heartbeat - but changed no
reader, so the fix never took effect and its test asserted the write half by source inspection.  These
tests assert the READ half, for both instruments, through the CLI.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_governance.policy import policy_digest
from starquant_live.composition import build_model, load_registry
from starquant_live.engine import registry_digest
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]

DEAD_PROCESS_GOVERNANCE = "75764f646ca6"  # the 18:00:29Z reading, written by a process that is gone
# Synthetic on purpose.  The real 2026-09-14 reading was `9e1bf73c3691` - which was this repository's
# OWN digest when this test was written, so using it would have made the test pass for the wrong
# reason; f4c86054 has since moved the tree to `1db80a06f281` by dropping ENAUSDT, which is exactly
# the kind of move that must not be able to decide whether this test means anything.
DEAD_PROCESS_REGISTRY = "dead0badc0de"


def _stamp(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _profile(tmp_path: Path) -> Path:
    payload = load_yaml(ROOT / "config/live.demo.yaml")
    payload["registry"] = str(ROOT / "config/alpha_registry.yaml")
    payload["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _running_registry_digest(profile: Path) -> str:
    payload = load_yaml(profile)
    return registry_digest(build_model(load_registry(payload["registry"]), payload))


def _restarted_loop(tmp_path: Path, *, dead_row: dict[str, object], heartbeat: dict[str, object]) -> None:
    """A loop that restarted 60s ago: one cycle row from the dead process, one heartbeat from this one."""
    directory = tmp_path / "live"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cycles.jsonl").write_text(
        json.dumps({"at": _stamp(4_800), "bar_open_ms": 1, "dry_run": False, **dead_row}) + "\n", encoding="utf-8"
    )
    (directory / "state.json").write_text(
        json.dumps({"restarts": 43, "restarted_at": _stamp(60), "cycles": 300}), encoding="utf-8"
    )
    (directory / "heartbeat.json").write_text(
        json.dumps({"at": _stamp(5), "phase": "SKIPPED", "dry_run": False, **heartbeat}), encoding="utf-8"
    )


def _check(profile: Path) -> str:
    return CliRunner().invoke(main, ["live", "status", "--profile", str(profile), "--check"]).output


def test_the_governance_check_reads_the_restart_heartbeat_not_the_dead_process(tmp_path: Path) -> None:
    """The 2026-09-14 false alarm: the file and the running process agreed, the dead row did not."""
    profile = _profile(tmp_path)
    _restarted_loop(
        tmp_path,
        dead_row={"governance": DEAD_PROCESS_GOVERNANCE, "registry": _running_registry_digest(profile)},
        heartbeat={"governance": policy_digest(), "registry": _running_registry_digest(profile)},
    )

    output = _check(profile)

    assert "磁盘上的治理规则" not in output, "a resolved divergence was reported as a live one"
    assert f"治理规则：与正在运行的循环一致（{policy_digest()}）" in output


def test_without_a_heartbeat_reading_a_restart_reports_no_reading_rather_than_the_old_one(tmp_path: Path) -> None:
    """A process started before the heartbeat carried the digest: silence, not the dead process's answer.

    Saying nothing is the honest reading - nothing this process wrote has been seen yet - and it is
    what the `None` branch already existed to say.
    """
    profile = _profile(tmp_path)
    _restarted_loop(
        tmp_path,
        dead_row={"governance": DEAD_PROCESS_GOVERNANCE, "registry": DEAD_PROCESS_REGISTRY},
        heartbeat={"phase": "SKIPPED"},
    )

    output = _check(profile)

    assert "治理规则：还没有任何周期记录过 digest" in output
    assert "registry：还没有任何周期记录过 digest" in output
    assert DEAD_PROCESS_GOVERNANCE not in output and DEAD_PROCESS_REGISTRY not in output


def test_the_registry_check_stays_loud_when_the_file_moved_while_this_process_runs(tmp_path: Path) -> None:
    """The true positive this must not go deaf on: a registry edited on disk under a running loop.

    2026-09-14, ENAUSDT removed from the registry while the loop held the 17-name model: the removal
    takes effect at the next restart, and that is exactly what the check exists to say beforehand.
    """
    profile = _profile(tmp_path)
    _restarted_loop(
        tmp_path,
        dead_row={"registry": DEAD_PROCESS_REGISTRY, "governance": policy_digest()},
        heartbeat={"registry": DEAD_PROCESS_REGISTRY, "governance": policy_digest()},
    )

    output = _check(profile)

    assert "磁盘上的 registry" in output and "下次重启会静默改变交易内容" in output


def test_a_dry_run_process_may_not_answer_for_the_live_one(tmp_path: Path) -> None:
    """The cycle readers skip dry-run rows for a reason; the heartbeat is one file, overwritten by whoever writes it."""
    profile = _profile(tmp_path)
    _restarted_loop(
        tmp_path,
        dead_row={"governance": DEAD_PROCESS_GOVERNANCE, "registry": DEAD_PROCESS_REGISTRY},
        heartbeat={"governance": policy_digest(), "registry": _running_registry_digest(profile), "dry_run": True},
    )

    output = _check(profile)

    assert "治理规则：还没有任何周期记录过 digest" in output
    assert "registry：还没有任何周期记录过 digest" in output


def test_a_failing_first_bar_does_not_take_both_instruments_out_with_it(tmp_path: Path) -> None:
    """2026-09-15 09:00Z: the first cycle after a restart died on a proxy 503.

    An outage is a reason to want the answer, not a reason to lose it - and `consecutive_errors` well
    below the streak bar means the check is otherwise still reporting a healthy loop.
    """
    profile = _profile(tmp_path)
    _restarted_loop(
        tmp_path,
        dead_row={"governance": DEAD_PROCESS_GOVERNANCE, "registry": DEAD_PROCESS_REGISTRY},
        heartbeat={
            "phase": "ERROR",
            "error": "ProxyError: 503 Service Unavailable",
            "consecutive_errors": 1,
            "governance": policy_digest(),
            "registry": _running_registry_digest(profile),
        },
    )

    output = _check(profile)

    assert f"registry：与正在运行的循环一致（{_running_registry_digest(profile)}）" in output
    assert f"治理规则：与正在运行的循环一致（{policy_digest()}）" in output
