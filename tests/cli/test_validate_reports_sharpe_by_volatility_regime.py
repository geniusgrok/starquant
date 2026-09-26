"""`validate` 的报告第一次带「非日历状态」的条件夏普（GAP-SF02，2026-09-23）。

在此之前报告对收益的每一种切分都按日历：fold、`time_split_sharpes`、窗口 q10。本文件端到端地跑
`research validate`（真实的 2026-08 币安 1h K 线，经 `KlineStore` 落盘再读回，走的是生产那条面板路径），
钉住四件事：

1. JSON、Markdown 两处都有这张表，Markdown 是平铺的行，不是一格 Python dict。
2. **每一根 OOS bar 都拿到了标签**。`regime_split_sharpes` 按索引做 inner join，索引对不上时它不报错，
   只会静默地少几根——所以断言三档 bar 数之和等于 `walk_forward.oos_bars`。
3. **基准是书当时能持有的那些符号**：pit 下只算成员，static 下算全部面板符号。测试从面板独立重算
   两种基准的标签区间，断言报告对上的是该对上的那一个，并先证明两者在这份 fixture 上确实不同。
4. verdict 的 reasons 里没有它。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from click.testing import CliRunner

from starquant_alpha.backtest import benchmark_returns
from starquant_alpha.validation.stability import trailing_benchmark_vol
from starquant_cli import main
from starquant_cli.research_panel import _load, _membership
from starquant_cli.research_report import _regime_rows
from starquant_data.store import KlineStore

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
SECTION = "## Sharpe by benchmark-volatility regime (reported, never enforced)"


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _write_membership(august_dir: Path, root: Path) -> None:
    """三个成员、月中换一个：BNB 出、SOL 进。成员从来不是全部四个，基准才分得出两种口径。"""
    stamps = pd.to_datetime(pd.read_parquet(august_dir / "BTCUSDT" / "1h.parquet")["open_time"], unit="ms", utc=True)
    membership = pd.DataFrame(
        [[True, True, True, False], [True, True, False, True]],
        index=pd.DatetimeIndex([stamps.iloc[0], stamps.iloc[len(stamps) // 2]]),
        columns=list(SYMBOLS),
    )
    membership.to_parquet(root / "membership.parquet")


def _validate(root: Path, out: Path, *extra: str) -> tuple[dict[str, Any], str]:
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
            *extra,
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob("tsmom-validation-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8")), newest.with_suffix(".md").read_text(encoding="utf-8")


def _label_span(root: Path, oos_bars: int, membership: pd.DataFrame | None) -> tuple[float, float]:
    """面板上独立重算：OOS 是 walk-forward 铺满的序列尾部，所以就是最后 `oos_bars` 根。"""
    panel = _load(str(root), list(SYMBOLS), "1h", None, None, False)
    bench = benchmark_returns(panel, "open_to_close", panel.symbols, membership)
    vol = trailing_benchmark_vol(bench, panel.bars_per_year).iloc[-oos_bars:]
    return float(vol.min()), float(vol.max())


def test_a_pit_run_labels_every_oos_bar_from_the_members_benchmark(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _write_membership(august_dir, root)

    report, markdown = _validate(root, tmp_path / "out", "--universe", "pit")

    split = report["stability"]["regime_split_sharpes"]
    oos_bars = report["walk_forward"]["oos_bars"]
    assert set(split) == {"low", "mid", "high"}
    assert sum(row["bars"] for row in split.values()) == oos_bars, "有 OOS bar 没拿到标签"
    panel = _load(str(root), list(SYMBOLS), "1h", None, None, False)
    members = _membership(str(root), "pit", panel, 0)
    expected = _label_span(root, oos_bars, members)
    everyone = _label_span(root, oos_bars, None)
    assert everyone != pytest.approx(expected), "两种口径在这份 fixture 上读数相同，下一条分不出用的是哪个"
    assert (split["low"]["vol_from"], split["high"]["vol_to"]) == pytest.approx(expected, rel=1e-12)
    assert report["stability"]["regime_split_basis"]["vol_window_days"] == 30
    assert "t-1" in report["stability"]["regime_split_basis"]["label_on_bar_t_reads"]
    assert not any("regime" in reason for reason in report["reasons"])

    section = markdown.split(SECTION, 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if "annualised vol" in line]
    assert [row.split(" (", 1)[0] for row in rows] == ["| low", "| mid", "| high"]
    assert all("sharpe=" in row and "bars=" in row for row in rows)
    assert "| regime_split_sharpes | " not in markdown, "表被印成了一格 dict"
    assert "t-1" in section, "因果那句要跟着数走，不能只在 JSON 里"


def test_a_static_run_takes_every_panel_symbol(tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _validate(root, tmp_path / "out")

    split = report["stability"]["regime_split_sharpes"]
    oos_bars = report["walk_forward"]["oos_bars"]
    assert sum(row["bars"] for row in split.values()) == oos_bars
    expected = _label_span(root, oos_bars, None)
    assert (split["low"]["vol_from"], split["high"]["vol_to"]) == pytest.approx(expected, rel=1e-12)


def test_an_empty_table_says_why_and_keeps_its_basis() -> None:
    """样本太短时空表要印成一句话，而基准说明照样印——「n/a」本身也要说清是什么东西的 n/a。"""
    rows = _regime_rows({}, {"vol_window_days": 30, "label_on_bar_t_reads": "benchmark bars through t-1"})

    assert rows["regime split"].startswith("n/a")
    assert rows["basis: vol_window_days"] == "30"
    assert rows["basis: label_on_bar_t_reads"] == "benchmark bars through t-1"
