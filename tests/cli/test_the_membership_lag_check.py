"""G10's hourly line: `starquant data pool lag --check`, as `deploy/run_check.sh` consumes it.

The job pages with `tail -n 3` of the output, so the command prints ONE line and that line is the page.
Over the line it has to say three things at once - how far behind the table is, that a rebuild needs
`--refresh D`, and that a rebuild blocks the armed start until the evidence is re-issued - or the alert
talks the operator into repeating 2026-09-18, whose bare rebuild is what the D-041 bridge exists for.

A table that is missing, unreadable, empty or monthly cannot vouch for its own freshness, so each of
those is an alert with its own reason, never a quiet pass.  Runs on the real table (see
`tests/data/test_the_membership_table_says_how_far_it_trails.py` for its provenance).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner, Result

from starquant_cli import main

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "tests" / "fixtures" / "pit_membership_2026_09_17"
# Machine tokens the page may carry in English: click's prefix, the rebuild command and its flag, the
# manifest field and the gate's function name.  Any other word of four letters or more is prose that
# should have been Chinese - the rule `test_alerts_are_chinese.py` holds `live status --check` to.
TOKENS = {"Error", "starquant", "data", "pool", "history", "refresh", "manifest", "membership", "armed"}
TOKENS |= {"registry_dataset_problems"}


def _run(*args: str) -> Result:
    return CliRunner().invoke(main, ["data", "pool", "lag", *args])


def _english(line: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_]{4,}", line))


def test_under_the_line_the_check_passes_with_one_line() -> None:
    result = _run("--check", "--root", str(REAL), "--date", "2026-09-23")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["时点成员表落后 6 天（告警线 14 天；末行 2026-09-17，今天 2026-09-23 UTC）"]


def test_over_the_line_the_one_line_says_the_lag_the_flag_and_the_gate() -> None:
    result = _run("--check", "--root", str(REAL), "--date", "2026-10-01")
    assert result.exit_code == 1, result.output
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, lines  # `tail -n 3` pastes it whole
    page = lines[0]
    assert "落后 14 天" in page and "告警线 14 天" in page  # how far
    assert "starquant data pool history --refresh D" in page and "MS 是 09-04 弃用的月表" in page  # the flag
    assert "armed 启动随即被数据集门挡住" in page and "registry_dataset_problems" in page  # the gate
    assert "要和证据重出排在一起" in page  # and what a rebuild has to be scheduled with
    assert _english(page) <= TOKENS, _english(page) - TOKENS  # the Lark channel is read in Chinese


def test_without_check_the_same_reading_prints_and_exits_zero() -> None:
    result = _run("--root", str(REAL), "--date", "2026-10-01")
    assert result.exit_code == 0, result.output
    assert "落后 14 天" in result.output and "Error" not in result.output


def test_a_missing_table_is_an_alert_and_not_a_pass(tmp_path: Path) -> None:
    result = _run("--check", "--root", str(tmp_path))
    assert result.exit_code == 1, result.output
    assert "时点成员表不存在" in result.output and "不能当作新鲜" in result.output
    assert "--refresh D" in result.output and "数据集门" in result.output


def test_an_unreadable_table_is_an_alert_and_not_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A half-written file is what a check used to see while `pool history` rewrote the table in place.

    The write is atomic since 2026-09-23, so that source is gone; any other damage still reads the same way.
    """
    real = (REAL / "membership.parquet").read_bytes()
    (tmp_path / "membership.parquet").write_bytes(real[: len(real) // 2])
    result = _run("--check", "--root", str(tmp_path))
    assert result.exit_code == 1, result.output
    assert "时点成员表读不了" in result.output and "不能当作新鲜" in result.output

    def unreadable(*_args: object, **_kwargs: object) -> pd.DataFrame:
        raise OSError("first line\nsecond line")

    monkeypatch.setattr(pd, "read_parquet", unreadable)
    result = _run("--check", "--root", str(tmp_path))
    assert result.exit_code == 1, result.output
    assert len(result.output.strip().splitlines()) == 1, result.output  # still one line for `tail -n 3`
    assert "OSError: first line second line" in result.output


def test_an_empty_or_monthly_table_is_an_alert_even_when_its_last_row_is_recent(tmp_path: Path) -> None:
    monthly = pd.DataFrame({"BTCUSDT": [True] * 3}, index=pd.date_range("2026-07-01", periods=3, freq="MS", tz="UTC"))
    monthly.to_parquet(tmp_path / "membership.parquet")
    result = _run("--check", "--root", str(tmp_path), "--date", "2026-09-04")
    assert result.exit_code == 1, result.output
    assert "不是日表" in result.output and "--refresh D" in result.output

    monthly.iloc[:0].to_parquet(tmp_path / "membership.parquet")
    result = _run("--check", "--root", str(tmp_path), "--date", "2026-09-04")
    assert result.exit_code == 1, result.output
    assert "时点成员表是空的" in result.output


def test_the_hourly_check_gates_and_pages_on_it_like_its_other_lines() -> None:
    """The wiring, read from the script: run with `--check`; on failure, `report daily`'s exact path.

    One difference, on purpose (operator ruling 2026-09-23): this line pages once a day, so its `notify`
    carries a daily window and a state file of its own - why the file has to be its own is
    `tests/live/test_the_membership_page_is_once_a_day.py`.  Everything else is `report daily`'s path.
    """
    script = (ROOT / "deploy" / "run_check.sh").read_text(encoding="utf-8").splitlines()
    runs = [n for n, line in enumerate(script) if "data pool lag --check" in line]
    assert len(runs) == 1, runs
    assert script[runs[0]] == 'if output="$("$REPO/.venv/bin/starquant" data pool lag --check 2>&1)"; then'
    report = script.index('if output="$("$REPO/.venv/bin/starquant" report daily --check 2>&1)"; then')
    failure = [line.replace('"report"', '"membership"') for line in script[report + 2 : report + 6]]
    assert failure[:3] == [
        "else",
        "  failed=1",
        '  notify "membership" "$(echo "$output" | tail -n 3 | tr \'\\n\' \' \')"',
    ]
    daily = failure[2] + ' 86340 "$SUPPORT/alert-dedup-daily.json"'
    assert script[runs[0] + 2 : runs[0] + 6] == [failure[0], failure[1], daily, failure[3]]
