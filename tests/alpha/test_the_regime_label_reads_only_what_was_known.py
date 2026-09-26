"""分 regime 的夏普：标签只读当时已知的东西，而这张表碰不到任何 verdict（GAP-SF02，2026-09-23）。

`regime_split_sharpes` 从写好到 2026-09-23 零调用者，于是没有任何一份报告带过「非日历状态」的条件
夏普。2026-09-17 的策略因子分析因此把「没有报告」读成了「所有状态下都 ≤ 0」（`analysis-calibration.md`
那一行）。接进 `validate` 之后，这张表要守住三件事，本文件各钉一条：

1. **因果**。`net` 的第 t 根是第 t-1 根收盘时决定的仓位在第 t 根赚到的（`run_backtest` 执行
   ``weights.shift(1)``），所以第 t 根的标签只能读到第 t-1 根为止的基准。不移这一位，一根暴跌的 bar
   会把自己标成高波动，表就有一部分是按结果分的。前提（执行滞后一根）与结论（标签滞后一根）都钉住，
   任何一边改了都会红。
2. **算术**。等数量三分位、按波动率有序、覆盖每一根有标签的 bar，每一行就是它那些 bar 的 Sharpe。
3. **只报告，不判定**。遍历 `reports/research/` 下全部真实归档的 validation 报告，塞进一张敌意的表，
   verdict 与 reasons 一个字都不能动。

输入取自真实数据：`august_panel` 是 2026-08 的四个币安 1h K 线，不是手写的序列。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import asset_returns, benchmark_returns, run_backtest
from starquant_alpha.panel import Panel
from starquant_alpha.validation.metrics import sharpe
from starquant_alpha.validation.stability import REGIME_VOL_WINDOW_DAYS, regime_split_sharpes, trailing_benchmark_vol
from starquant_alpha.validation.verdict import decide
from tests.alpha.test_causality import _bit_for_bit

REPORTS = Path(__file__).resolve().parents[2] / "reports" / "research"


def _benchmark(panel: Panel) -> pd.Series:
    return benchmark_returns(panel, "open_to_close", panel.symbols)


def test_a_shock_from_bar_k_on_moves_no_label_at_or_before_k(august_panel: Panel) -> None:
    """从第 k 根起把基准改得面目全非：第 k 根及之前的标签一位不动，第 k+1 根的动了。

    第 k 根是那根「暴跌的 bar」本身——它的标签不含它自己。最后一条断言是反证：不移位的滚动标准差在
    第 k 根**会**动，所以守住这条性质的是 ``shift(1)``，不是碰巧。
    """
    bpy = august_panel.bars_per_year
    bench = _benchmark(august_panel)
    k = 400
    shocked = bench.copy()
    shocked.iloc[k:] = shocked.iloc[k:] * 50.0 + 0.1

    before, after = trailing_benchmark_vol(bench, bpy), trailing_benchmark_vol(shocked, bpy)

    _bit_for_bit(before.iloc[: k + 1], after.iloc[: k + 1])
    assert not np.isclose(before.iloc[k + 1], after.iloc[k + 1]), "扰动到不了后面的标签，上一条就是空转"
    window = round(REGIME_VOL_WINDOW_DAYS * bpy / 365.0)
    unshifted = bench.rolling(window, min_periods=window // 4).std()
    unshifted_shocked = shocked.rolling(window, min_periods=window // 4).std()
    assert not np.isclose(unshifted.iloc[k], unshifted_shocked.iloc[k]), "不移位时暴跌那根会给自己贴标签"


def test_the_backtest_earns_bar_t_on_the_position_decided_at_t_minus_1(august_panel: Panel) -> None:
    """上一条的前提：只在第 d 根决定持仓，毛收益只出现在第 d+1 根。

    `trailing_benchmark_vol` 的 docstring 把因果论证建在这一位滞后上。执行滞后哪天改了（比如改成
    同 bar 成交），标签就该跟着改，而这条测试是会先红的那一个。
    """
    weights = pd.DataFrame(0.0, index=august_panel.index, columns=august_panel.symbols)
    d = 200
    weights.iloc[d, weights.columns.get_loc("BTCUSDT")] = 1.0

    gross = run_backtest(august_panel, weights).gross.sum(axis=1)

    earned = gross[gross != 0.0]
    assert list(earned.index) == [august_panel.index[d + 1]]


def test_terciles_are_equal_count_ordered_and_cover_every_labelled_bar(august_panel: Panel) -> None:
    bpy = august_panel.bars_per_year
    vol = trailing_benchmark_vol(_benchmark(august_panel), bpy)
    net = asset_returns(august_panel, "open_to_close")["BTCUSDT"]

    table = regime_split_sharpes(net, vol, bpy)

    labelled = int(pd.concat([net, vol], axis=1, join="inner").dropna().shape[0])
    assert list(table) == ["low", "mid", "high"]
    assert sum(row["bars"] for row in table.values()) == labelled
    assert max(row["bars"] for row in table.values()) - min(row["bars"] for row in table.values()) <= 1
    assert table["low"]["vol_to"] <= table["mid"]["vol_from"] <= table["mid"]["vol_to"] <= table["high"]["vol_from"]


def test_each_row_is_the_sharpe_of_exactly_its_bars(august_panel: Panel) -> None:
    """独立重算：按波动率稳定排序后依次切 bars 根，每一段的 Sharpe 就是那一行。"""
    bpy = august_panel.bars_per_year
    vol = trailing_benchmark_vol(_benchmark(august_panel), bpy)
    net = asset_returns(august_panel, "open_to_close")["ETHUSDT"]
    table = regime_split_sharpes(net, vol, bpy)

    aligned = pd.concat([net, vol], axis=1, join="inner").dropna()
    order = np.argsort(aligned.iloc[:, 1].to_numpy(), kind="stable")
    ranked = aligned.iloc[:, 0].to_numpy()[order]
    start = 0
    for label in ("low", "mid", "high"):
        stop = start + table[label]["bars"]
        assert table[label]["sharpe"] == pytest.approx(sharpe(ranked[start:stop], bpy), rel=1e-9)
        start = stop
    assert start == len(aligned)


def test_too_few_labelled_bars_is_an_empty_table_not_a_guess(august_panel: Panel) -> None:
    """不足 30 根有标签的 bar 时返回空表，Markdown 印 n/a——而不是拿三五根 bar 算出一个 Sharpe。"""
    bpy = august_panel.bars_per_year
    vol = trailing_benchmark_vol(_benchmark(august_panel), bpy)
    net = asset_returns(august_panel, "open_to_close")["BTCUSDT"]

    assert regime_split_sharpes(net.iloc[-29:], vol, bpy) == {}
    assert regime_split_sharpes(net.iloc[-30:], vol, bpy) != {}


def test_the_benchmark_keeps_each_bar_to_the_symbols_the_book_could_hold(august_panel: Panel) -> None:
    """`membership` 给了就只算当根的成员；不给则与改动前逐位相同。

    缺列按「不是成员」算，多出来的列（面板里没有的符号）被忽略——真实 pit 表两种情况都有：成员表比
    K 线库多 5 个还没有 1h K 线的符号，而面板里每个符号并非每天都在成员里。
    """
    returns = asset_returns(august_panel, "open_to_close")
    half = len(august_panel.index) // 2
    mask = pd.DataFrame(False, index=august_panel.index, columns=["BTCUSDT", "ETHUSDT", "BNBUSDT", "NOTLISTEDUSDT"])
    mask.iloc[:half, [0, 1]] = True  # 前半段：BTC、ETH
    mask.iloc[half:, [0, 1, 2]] = True  # 后半段：再加 BNB；SOL 没有列，始终不是成员

    bench = benchmark_returns(august_panel, "open_to_close", august_panel.symbols, mask)

    first = returns[["BTCUSDT", "ETHUSDT"]].iloc[:half].mean(axis=1)
    second = returns[["BTCUSDT", "ETHUSDT", "BNBUSDT"]].iloc[half:].mean(axis=1)
    _bit_for_bit(bench, pd.concat([first, second]), check_names=False)
    _bit_for_bit(_benchmark(august_panel), returns[august_panel.symbols].mean(axis=1), check_names=False)


def _archived_validations() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path in sorted(REPORTS.rglob("*validation*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "validation":
            out.append((path.name, payload))
    return out


@pytest.mark.parametrize("sharpe_everywhere", [-99.0, 99.0])
def test_the_regime_table_cannot_move_any_archived_verdict(sharpe_everywhere: float) -> None:
    """两个方向的敌意值：一条「高波动档为负就 FAIL」的规则会被 -99 抓到，一条「某档为正就放行」的会被 +99 抓到。

    `verdict.decide` 今天根本不读 `stability`，所以这条测试防的是以后：有人把这张表「顺手」接进一道门。
    它和 R0 那条（`test_the_other_caliber_is_reported_not_applied.py`）是同一个形状。
    """
    archived = _archived_validations()
    assert len(archived) >= 60, f"归档的 validation 报告只剩 {len(archived)} 份——这条测试读的就是它们"
    hostile = {
        label: {"sharpe": sharpe_everywhere, "bars": 1, "vol_from": 0.0, "vol_to": 9.9}
        for label in ("low", "mid", "high")
    }
    for name, report in archived:
        stability = {**(report.get("stability") or {}), "regime_split_sharpes": hostile}
        assert decide({**report, "stability": stability}) == decide(report), f"{name}：分 regime 的表进了 verdict"
