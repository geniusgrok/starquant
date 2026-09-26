"""M-Q08's block runs inside the hourly `report daily --check`, and it judges nothing.

So nothing it raises may reach the rest of the report.  An exception that escapes it fails the whole
command: the hourly check reports "report" as failed, and every alert the report would have carried -
equity drift, the risk budget, a failed bar - goes down with it.  Each case below makes one part of the
block raise a type the first version's narrow catches did not list, and requires the report to come out
whole: the same sections, the same alerts and notices, and the reason printed in the block.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner, Result

from starquant_cli import main
from starquant_live import execution_fidelity as fidelity
from starquant_live.composition import build_model, load_registry
from starquant_live.engine import registry_digest
from starquant_live.reports import daily_alerts
from starquant_live.state import StateStore
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
DAY = "2026-09-01"
T0 = 1_788_220_800_000  # 2026-09-01T00:00Z
HOUR = 3_600_000


def _raise(error: Exception) -> Any:
    def raiser(*_args: object, **_kwargs: object) -> Any:
        raise error

    return raiser


def _command(tmp_path: Path) -> list[str]:
    """A profile on a scratch state whose cycles recorded the shipped registry's own digest.

    The digest has to match, or the block never reaches the replay: a registry the loop is not running is
    refused before anything is loaded.  The archive is empty, so the replay fails even without help.
    """
    profile = load_yaml(ROOT / "config/live.demo.yaml")
    profile["paths"] = {"state_dir": str(tmp_path / "live"), "reports_dir": str(tmp_path / "reports")}
    profile["alerts"] = {}  # a test never pages
    profile["costs"] = str(ROOT / "config/costs.yaml")
    profile["registry"] = str(ROOT / "config/alpha_registry.yaml")
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump(profile), encoding="utf-8")
    digest = registry_digest(build_model(load_registry(ROOT / "config/alpha_registry.yaml"), profile))
    store = StateStore(tmp_path / "live")
    store.save(store.load())
    for i in range(24):
        bar = T0 + i * HOUR
        at = datetime.fromtimestamp((bar + HOUR) / 1000 + 25, tz=UTC).isoformat()
        store.append_cycle(
            {
                "bar_open_ms": bar,
                "at": at,
                "equity": 10_000.0 * (1.0 - 0.002 * i),
                "registry": digest,
                "construction": "c",
                "universe": ["BTCUSDT"],
                "skip": False,
                "guard_reasons": [],
                "targets": {},
                "orders": [],
            }
        )
    store.append_trade(
        {
            "bar_open_ms": T0 + 3 * HOUR,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "avg_price": 100.02,
            "executed_qty": "1",
            "decision_close": 100.0,
        }
    )
    (tmp_path / "archive" / "klines").mkdir(parents=True)
    profile_path = str(tmp_path / "profile.yaml")
    return ["report", "daily", "--profile", profile_path, "--date", DAY, "--data-root", str(tmp_path / "archive")]


def _run(command: list[str], out: Path) -> tuple[Result, dict[str, Any], str]:
    result = CliRunner().invoke(main, [*command, "--check", "--out", str(out)])
    # `--check` exits 1 on an alert, which is a verdict and not a crash; anything else escaping is a crash.
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    payload = json.loads((out / f"{DAY}.json").read_text(encoding="utf-8"))
    return result, payload, (out / f"{DAY}.md").read_text(encoding="utf-8")


def _sections(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("## ")]


def _mq08(markdown: str) -> str:
    return markdown.split("## Execution fidelity (M-Q08, four clauses)")[1].split("\n## ")[0]


CASES = {
    "the replay": ("backtest_turnover", RuntimeError("injected by the test")),
    "building the replay's inputs": ("build_model", IndexError("injected by the test")),
    "a reading outside the replay": ("slippage_by_week", ZeroDivisionError("injected by the test")),
}


@pytest.mark.parametrize("case", list(CASES))
def test_an_exception_in_the_mq08_block_leaves_the_report_whole(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = _command(tmp_path)
    clean, clean_payload, clean_markdown = _run(command, tmp_path / "clean")

    name, error = CASES[case]
    monkeypatch.setattr(fidelity, name, _raise(error))
    broken, payload, markdown = _run(command, tmp_path / "broken")

    assert broken.exit_code == clean.exit_code
    assert _sections(markdown) == _sections(clean_markdown), "every other section still renders"
    assert daily_alerts(payload) == daily_alerts(clean_payload), "the same alerts and notices, nothing lost"
    reason = f"{type(error).__name__}: {error}"
    assert reason in _mq08(markdown), "the block says what broke it"
    block = payload["execution_fidelity"]
    if case == "a reading outside the replay":
        assert block == {"error": reason}
    else:
        # The replay and its inputs fail inside the block, and blind the turnover clause alone.
        assert reason in block["turnover"]["why"]
        assert block["registry"]["loop"] == clean_payload["execution_fidelity"]["registry"]["loop"]
        assert block["slippage_by_week"] == clean_payload["execution_fidelity"]["slippage_by_week"]
