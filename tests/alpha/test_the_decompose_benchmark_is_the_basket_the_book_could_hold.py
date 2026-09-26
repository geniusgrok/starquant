"""`decompose` 的基准取书在每根 bar 能持有的那些符号（操作者 2026-09-23 裁定「对齐」）。

`decompose_book` 一直把 `membership` 传给模型，却没传给基准：同一份报告里，书在当期成员里选仓，
`benchmark` 与每个变体的 `correlation_with_benchmark` 却对着全部有价符号的等权篮子算。在真实 pit 面板上
那个篮子每根 bar 纳入的符号数从 2021 年中位 69 涨到 2026 年 203，成员始终 15–20 个（GAP-SF02 那一节）。

对齐之后，同一个 `benchmark` 键在 pit 报告里换了篮子，所以报告要自己说出是哪一个：`basket`。
没有这个键的归档报告是旧口径。

输入是 2026-08 的四个币安 1h K 线（`august_panel`），不是手写序列。
"""

from __future__ import annotations

import pandas as pd

from starquant_alpha.backtest import CostModel, benchmark_basket, benchmark_returns
from starquant_alpha.model import AlphaModel
from starquant_alpha.panel import Panel
from starquant_alpha.portfolio import PortfolioParams
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.signals.tsmom import TsmomParams
from starquant_alpha.validation.decompose import decompose_book
from starquant_alpha.validation.metrics import sharpe


def _model() -> AlphaModel:
    params = TsmomParams(vol_window=100).__dict__ | {"horizons": [5, 20, 50], "horizon_weights": [0.2, 0.3, 0.5]}
    return AlphaModel(
        entries=(StrategyEntry("tsmom", params=params),),
        portfolio=PortfolioParams(covariance_halflife=48, vol_halflife=24, no_trade_rel_band=0.25),
        interval="1h",
        min_history_bars=0,
    )


def _members(panel: Panel) -> pd.DataFrame:
    """三个成员、月中换一个：BNB 出、SOL 进。成员从来不是全部四个，两种篮子才分得开。"""
    mask = pd.DataFrame(False, index=panel.index, columns=panel.symbols)
    half = len(panel.index) // 2
    mask.iloc[:half, [mask.columns.get_loc(s) for s in ("BTCUSDT", "ETHUSDT", "BNBUSDT")]] = True
    mask.iloc[half:, [mask.columns.get_loc(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]] = True
    return mask


def _benchmark_sharpe(panel: Panel, payload: dict, membership: pd.DataFrame | None) -> float | None:
    """独立重算：变体的公共索引是从第一次决策起连续到面板末尾，所以就是 `range` 那一段。"""
    start, end = pd.Timestamp(payload["range"]["start"]), pd.Timestamp(payload["range"]["end"])
    bench = benchmark_returns(panel, "open_to_close", panel.symbols, membership).loc[start:end].fillna(0.0)
    assert len(bench) == payload["range"]["bars"], "公共索引不是连续的一段，重算的前提不成立"
    return sharpe(bench, panel.bars_per_year)


def test_a_pit_decomposition_benchmarks_against_the_members(august_panel: Panel) -> None:
    members = _members(august_panel)

    payload = decompose_book(
        _model(), august_panel, CostModel(turnover_bps=7.0), membership=members, folds=3, min_train=300, purge=5
    )

    everyone = _benchmark_sharpe(august_panel, payload, None)
    expected = _benchmark_sharpe(august_panel, payload, members)
    assert expected != everyone, "两种篮子在这份 fixture 上 Sharpe 相同，下一条就分不出用的是哪个"
    assert payload["benchmark"]["full_sharpe"] == expected
    assert payload["benchmark"]["basket"] == "pit members at each bar"


def test_without_membership_the_benchmark_is_what_it_always_was(august_panel: Panel) -> None:
    """static 路径一位不动：还是全部面板符号，只多一个说出这件事的键。"""
    payload = decompose_book(_model(), august_panel, CostModel(turnover_bps=7.0), folds=3, min_train=300, purge=5)

    assert payload["benchmark"]["full_sharpe"] == _benchmark_sharpe(august_panel, payload, None)
    assert payload["benchmark"]["basket"] == "every panel symbol"


def test_the_basket_label_has_one_wording_for_both_answers() -> None:
    """backtest 与 decompose 两份报告共用这一个措辞；各写各的字符串，迟早有一份写成第三种说法。"""
    assert benchmark_basket(None) == "every panel symbol"
    assert benchmark_basket(pd.DataFrame()) == "pit members at each bar"
