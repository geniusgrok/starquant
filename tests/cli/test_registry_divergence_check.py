"""DL-Q0 / KILL-Q15: ``live status --check`` compares the registry on disk with the one running.

The loop builds its model once at startup.  Editing ``config/alpha_registry.yaml``
afterwards changes what the file says without changing what the process trades,
and until now nothing could see the difference - not the construction fingerprint
(portfolio layer only), not the startup evidence gate (it runs before the edit),
not ``live verify`` (it rebuilds from the same file it is meant to be checking).

The check is deliberately one comparison of two digests: the one the last cycle
recorded, and the one the current file produces.  Different digests mean the next
restart will silently change what is traded - which is the thing to be warned
about, before it happens rather than after.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from starquant_cli import main
from starquant_live.composition import build_model, load_registry
from starquant_live.engine import registry_digest
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]


def _profile(tmp_path: Path, registry_path: Path) -> Path:
    payload = load_yaml(ROOT / "config/live.demo.yaml")
    payload["registry"] = str(registry_path)
    payload["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _state(tmp_path: Path, digest: str) -> None:
    directory = tmp_path / "live"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cycles.jsonl").write_text(
        json.dumps({"bar_open_ms": 1, "registry": digest, "dry_run": False}) + "\n", encoding="utf-8"
    )


def _registry_copy(tmp_path: Path, **params: object) -> Path:
    payload = load_yaml(ROOT / "config/alpha_registry.yaml")
    for strategy in payload["strategies"]:
        if strategy["id"] == "tsmom":
            strategy["params"].update(params)
    path = tmp_path / "alpha_registry.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_check_passes_when_the_file_matches_the_running_process(tmp_path: Path) -> None:
    registry_path = _registry_copy(tmp_path)
    profile = _profile(tmp_path, registry_path)
    running = registry_digest(build_model(load_registry(registry_path), load_yaml(profile)))
    _state(tmp_path, running)

    result = CliRunner().invoke(main, ["live", "status", "--profile", str(profile), "--check"])

    assert "registry：与正在运行的循环一致" in result.output


def test_check_fails_when_the_file_has_moved_ahead_of_the_running_process(tmp_path: Path) -> None:
    """The 2026-09-04 situation: ``crowding_window`` 0 -> 72 on disk, 0 still in the process."""
    registry_path = _registry_copy(tmp_path, crowding_window=72)
    profile = _profile(tmp_path, registry_path)
    stale = registry_digest(
        build_model(load_registry(_registry_copy(tmp_path / "old", crowding_window=0)), load_yaml(profile))
    )
    _state(tmp_path, stale)

    result = CliRunner().invoke(main, ["live", "status", "--profile", str(profile), "--check"])

    assert result.exit_code != 0
    assert "磁盘上的 registry" in result.output and "重启" in result.output


def test_check_is_silent_when_no_cycle_recorded_a_digest(tmp_path: Path) -> None:
    """Cycles written before this field existed must not be read as a divergence."""
    registry_path = _registry_copy(tmp_path)
    profile = _profile(tmp_path, registry_path)
    directory = tmp_path / "live"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cycles.jsonl").write_text(json.dumps({"bar_open_ms": 1, "dry_run": False}) + "\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["live", "status", "--profile", str(profile), "--check"])

    assert "registry：还没有任何周期记录过 digest" in result.output


@pytest.fixture(autouse=True)
def _tmp_subdir(tmp_path: Path) -> None:
    (tmp_path / "old").mkdir(exist_ok=True)
