"""功效表要到达**读 artefact 的那个人**，而不是只留在函数里（Q-SY1，2026-09-18）。

这是 `_MARGIN_BUFFER_NOTE` / `_caliber_note` / `_full_sample_tail_note` 三条 note 同一条规矩的第四个
实例：**一条只能靠读实现才拿得到的判读，不是对读报告的人的披露，是对已经知道的人的披露。**
`oos_selection` 里有 `variance` 已经很久了，从它到「这道门拦得住多少真东西」只有三行算术——而四轮
问答里没有一次给出过这个数。

所以三处都要有：JSON 载荷里、Markdown 里、stdout 上。另外一条命令 `research power` 让它能在**跑之前**
算出来，因为预登记是写在跑之前的。那条命令必须一个字节都不写。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from starquant_cli import main
from starquant_data.store import KlineStore

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
CITED = Path(__file__).resolve().parents[2] / "reports" / "research" / "tsmom-validation-20260913T182325Z.json"


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _validate(root: Path, out: Path) -> tuple[dict, str, str]:
    result = CliRunner().invoke(
        main,
        [
            "research", "validate",
            "--strategy", "tsmom",
            "--root", str(root),
            "--symbols", ",".join(SYMBOLS),
            "--out", str(out),
            "--no-funding",
            "--params", '{"horizons": [5, 20, 50], "crowding_window": 0}',
            "--grid", "{}",
            "--folds", "3",
            "--min-train", "300",
            "--purge", "5",
            "--cpcv-groups", "4",
            "--min-history", "0",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob("tsmom-validation-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text()), newest.with_suffix(".md").read_text(encoding="utf-8"), result.output


def test_the_report_the_markdown_and_the_stdout_all_carry_it(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, markdown, output = _validate(root, tmp_path / "out")

    power = report["oos_selection"]["power"]
    assert power is not None, "载荷里没有功效块——读 JSON 的人就只剩一个门的数字"
    assert [row["true_sharpe_annual"] for row in power["detects"]] == [1.0, 1.2, 1.5, 2.0]
    assert "Power of that gate" in markdown, "Markdown 是一年后有人真会打开的那一份"
    assert "true annual Sharpe = 1.5" in markdown
    assert "power of that gate" in output, "跑完就滚走的 stdout 也要有，它是当场那个人看见的"
    # 上界这句话三处都要在：功效表不含 CPCV / PBO / fold / 成本 ×2
    assert "joint power is LOWER" in markdown and "joint power LOWER" in output


def test_the_markdown_does_not_render_the_power_block_as_one_python_dict_cell(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """`render_markdown` 把嵌套 dict 印成一行——那等于没印。所以它自己一节。"""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    _, markdown, _ = _validate(root, tmp_path / "out")

    assert "| power | {" not in markdown
    assert markdown.count("P(clear | true annual Sharpe") == 4


def test_research_power_writes_nothing_at_all(tmp_path: Path, isolated_trials_ledger: Path) -> None:
    """预登记阶段的工具必须免费。它读一份 JSON，算一次正态分位数，落盘为零。"""
    before = sorted(p.name for p in tmp_path.iterdir())
    ledger_before = isolated_trials_ledger.read_bytes() if isolated_trials_ledger.exists() else b""

    result = CliRunner().invoke(
        main, ["research", "power", "--evidence", str(CITED), "--trials", "299", "--charge", "16"]
    )

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    ledger_after = isolated_trials_ledger.read_bytes() if isolated_trials_ledger.exists() else b""
    assert ledger_after == ledger_before, "功效表花掉了一笔——那就没人会在预登记阶段跑它了"


def test_research_power_answers_the_question_that_has_been_asked_four_times(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """N=1、真 Sharpe 1.0 → 50.0%。这是「门是不是太严」的那个数。"""
    result = CliRunner().invoke(main, ["research", "power", "--evidence", str(CITED), "--trials", "1"])

    assert result.exit_code == 0, result.output
    assert "P(clear | true annual Sharpe = 1.0): 50.0%" in result.output
    assert "pass_line binds" in result.output, "空桶里挡路的是 D-020 不是 D-028，输出要说清是哪一半"
    assert "零 ledger" in result.output


def test_the_charge_flag_prices_the_run_that_has_not_happened_yet(tmp_path: Path, isolated_trials_ledger: Path) -> None:
    """预登记要写的是**跑完之后**那个 N 的功效，不是今天的。"""
    result = CliRunner().invoke(
        main, ["research", "power", "--evidence", str(CITED), "--trials", "299", "--charge", "16"]
    )

    assert result.exit_code == 0, result.output
    assert "## N=299" in result.output and "## N=315" in result.output
    assert "这次跑完的 N" in result.output


def test_a_report_without_a_variance_is_refused_rather_than_guessed(
    tmp_path: Path, isolated_trials_ledger: Path
) -> None:
    """手输方差是这条命令唯一能被做假的地方，所以它没有那个开关。"""
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"interval": "1h", "oos_selection": {"n_trials": 8}}), encoding="utf-8")

    result = CliRunner().invoke(main, ["research", "power", "--evidence", str(stale)])

    assert result.exit_code != 0
    assert "oos_selection.variance" in result.output
