"""`research backtest` 与 `research decompose` 的 benchmark 块：pit 下取当期成员，并在报告里说出篮子。

操作者 2026-09-23 裁定「对齐」：这两处此前在 pit 下仍取全部面板符号，与 `validate` 的 regime 分档
（GAP-SF02）不是同一个篮子。对齐之后 `benchmark` 这个键在 pit 报告里换了内容，归档里却有 5 份 pit 报告
（3 份 backtest、2 份 decompose）用的是旧篮子——所以新报告带 `basket`，没有这个键就是旧口径。

端到端跑命令（真实的 2026-08 币安 1h K 线，经 `KlineStore` 落盘再读回），再从面板独立重算对账，
并先证明两种篮子在这份 fixture 上确实给出不同的数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from click.testing import CliRunner

from starquant_alpha.backtest import benchmark_returns
from starquant_alpha.validation.metrics import sharpe
from starquant_cli import main
from starquant_cli.research_panel import _load, _membership
from starquant_data.store import KlineStore

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
PARAMS = '{"vol_window": 100, "horizons": [5, 20, 50], "crowding_window": 0}'


def _store_from_fixtures(august_dir: Path, root: Path) -> None:
    store = KlineStore(root)
    for symbol in SYMBOLS:
        frame = pd.read_parquet(august_dir / symbol / "1h.parquet")
        frame["close_time"] = frame["open_time"] + 3_600_000 - 1
        store.append(symbol, "1h", frame)


def _write_membership(august_dir: Path, root: Path) -> None:
    """三个成员、月中换一个：BNB 出、SOL 进。成员从来不是全部四个，两种篮子才分得开。"""
    stamps = pd.to_datetime(pd.read_parquet(august_dir / "BTCUSDT" / "1h.parquet")["open_time"], unit="ms", utc=True)
    membership = pd.DataFrame(
        [[True, True, True, False], [True, True, False, True]],
        index=pd.DatetimeIndex([stamps.iloc[0], stamps.iloc[len(stamps) // 2]]),
        columns=list(SYMBOLS),
    )
    membership.to_parquet(root / "membership.parquet")


def _run(command: str, root: Path, out: Path, *extra: str) -> tuple[dict[str, Any], str]:
    result = CliRunner().invoke(
        main,
        [
            "research", command,
            "--strategy", "tsmom",
            "--root", str(root),
            "--symbols", ",".join(SYMBOLS),
            "--out", str(out),
            "--no-funding",
            "--params", PARAMS,
            "--min-history", "0",
            *extra,
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    newest = max(out.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8")), newest.with_suffix(".md").read_text(encoding="utf-8")


def _expected_sharpe(root: Path, report: dict[str, Any], membership: pd.DataFrame | None) -> float | None:
    """`research backtest` 在策略的执行 bar 上算基准：报告的 `range` 就是那一段，而且是连续的。"""
    panel = _load(str(root), list(SYMBOLS), "1h", None, None, False)
    start, end = pd.Timestamp(report["range"]["start"]), pd.Timestamp(report["range"]["end"])
    bench = benchmark_returns(panel, "open_to_close", panel.symbols, membership).loc[start:end]
    assert len(bench) == report["range"]["bars"]
    return sharpe(bench, panel.bars_per_year)


def test_a_pit_backtest_benchmarks_against_the_members_and_says_so(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _write_membership(august_dir, root)

    report, markdown = _run("backtest", root, tmp_path / "out", "--universe", "pit")

    panel = _load(str(root), list(SYMBOLS), "1h", None, None, False)
    members = _membership(str(root), "pit", panel, 0)
    expected = _expected_sharpe(root, report, members)
    assert expected != _expected_sharpe(root, report, None), "两种篮子读数相同，下一条分不出用的是哪个"
    assert report["benchmark"]["sharpe"] == expected
    assert report["benchmark"]["basket"] == "pit members at each bar"
    assert "| basket | pit members at each bar |" in markdown, "Markdown 是一年后有人真会打开的那一份"


def test_a_static_backtest_keeps_every_panel_symbol(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)

    report, _ = _run("backtest", root, tmp_path / "out")

    assert report["benchmark"]["sharpe"] == _expected_sharpe(root, report, None)
    assert report["benchmark"]["basket"] == "every panel symbol"


def test_a_pit_decomposition_names_the_same_basket(
    tmp_path: Path, august_dir: Path, isolated_trials_ledger: Path
) -> None:
    """`decompose` 的 CLI 一直把 membership 传给 `decompose_book`；这里钉住它也到了基准那一行。"""
    root = tmp_path / "data"
    _store_from_fixtures(august_dir, root)
    _write_membership(august_dir, root)

    report, markdown = _run(
        "decompose", root, tmp_path / "out", "--universe", "pit", "--folds", "3", "--min-train", "300", "--purge", "5"
    )

    assert report["benchmark"]["basket"] == "pit members at each bar"
    assert "| basket | pit members at each bar |" in markdown
