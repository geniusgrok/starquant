"""D1：`weights_from` 说两个半边是同一条规则，它们不是。

`starquant_alpha/model.py` 的 D-033 把 no-trade band 从模型层搬到 rebalancer，理由逐字是：

    "In a backtest the model's own output is the position, so ``apply_no_trade_band`` is the position
    recursion and belongs here.  Live, the position is the venue's, and ``plan_rebalance`` applies the
    **identical rule** against it"

`apply_no_trade_band` 的 docstring 自己写着它豁免什么：

    "Exits to exactly zero, entries from zero and sign flips are always executed; only same-direction
    resizing is suppressed."

`plan_rebalance` 不豁免任何一样——绝对臂压在所有情形上，包括归零的平仓（`BAND_BLOCKS_EXIT`）和
从空仓建仓（`BAND_BLOCKS_ENTRY`）。于是被 `tsmom-validation-20260913T182325Z`（注册表钉的 PASS
证据，oos_sharpe 1.59）度量的那本账，和 armed 循环实际执行的那本账，在这一点上不是同一本。

实际后果不是学术的：退出层触发止损时只是把权重改成 0（`exits.py:72`），改完照样过 `plan_rebalance`
的带宽。所以一笔小于带宽的仓位，**止损打不出订单**——2026-09-14 的 ENAUSDT 在这个状态里待了 45 根周期。

`exempt_crossings` 是这条差异的开关，默认 False（= 今天在跑的那本账，不动构造）。True = 回测那本。
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from starquant_alpha.portfolio import apply_no_trade_band
from starquant_exchange.rules import InstrumentRules
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.types import Position

BAND, REL = 0.005, 0.40
EQUITY, PRICE = 10_000.0, 1.0
RULES = {"X": InstrumentRules("X", Decimal("0.0001"), Decimal("0.0001"), Decimal("0.0001"), Decimal("0"))}


def _live_path(path: list[float], *, exempt: bool) -> list[float]:
    """把一条权重路径喂给实盘规划器，返回每一步之后**实际持有**的权重。"""
    params = RebalanceParams(no_trade_band=BAND, no_trade_rel_band=REL, exempt_crossings=exempt)
    qty, held = 0.0, []
    for target in path:
        positions = (
            {"X": Position("X", qty=qty, entry_price=PRICE, mark_price=PRICE, unrealized_pnl=0.0)} if qty else {}
        )
        orders, _ = plan_rebalance(
            {"X": target},
            managed_symbols=["X"],
            equity=EQUITY,
            positions=positions,
            prices={"X": PRICE},
            rules=RULES,
            bar_open_ms=0,
            params=params,
        )
        for order in orders:
            qty += float(order.quantity) if order.side.value == "BUY" else -float(order.quantity)
        held.append(qty * PRICE / EQUITY)
    return held


def _backtest_path(path: list[float]) -> list[float]:
    return apply_no_trade_band(pd.DataFrame({"X": path}), BAND, REL)["X"].tolist()


#: 建仓 -> 衰减 -> 退出层把它打到恰好 0。最后一步是两个半边分道的地方。
DECAY_THEN_EXIT = [-0.0064, -0.0030, -0.0010, 0.0]


def test_the_shipped_default_is_todays_live_book_not_the_backtests() -> None:
    """默认关：这条测试存在的意义是让「差异」和「改动」分开记账。"""
    assert RebalanceParams().exempt_crossings is False
    live = _live_path(DECAY_THEN_EXIT, exempt=False)
    assert live[-1] != 0.0, "今天的实盘平不掉它——这正是要修的东西，不是笔误"
    assert live[-1] == live[-2], "带宽压住了归零的平仓"


def test_with_the_knob_on_the_two_halves_hold_the_same_book() -> None:
    """D-033 声称的等同性，作为一条会执行的检查。"""
    live = _live_path(DECAY_THEN_EXIT, exempt=True)
    backtest = _backtest_path(DECAY_THEN_EXIT)
    assert live == pytest_approx(backtest), f"实盘 {live} vs 回测 {backtest}"
    assert live[-1] == 0.0, "退出层把权重打到 0，两边都必须真的平掉"


def test_the_knob_does_not_touch_the_bands_actual_job() -> None:
    """豁免的是穿越，不是普通同向调仓——否则这就成了「把带宽关掉」。"""
    resize = [0.10, 0.1010, 0.1020]  # 同向、每步 10 USDT，远小于 50 USDT 的绝对臂
    assert _live_path(resize, exempt=True) == _live_path(resize, exempt=False)
    assert _live_path(resize, exempt=True)[1:] == [0.10, 0.10], "同向微调仍然被压住"


def test_an_entry_below_the_band_is_the_same_divergence_on_the_other_side() -> None:
    """TRUMPUSDT 2026-09-13 的情形：目标 4.25 USDT 对 54 USDT 的带宽，占着名额永远建不了仓。"""
    entry = [0.0, 0.002]  # 20 USDT 的目标，绝对臂 50 USDT
    assert _live_path(entry, exempt=False)[-1] == 0.0, "今天建不起来"
    assert _live_path(entry, exempt=True)[-1] == 0.002
    assert _backtest_path(entry)[-1] == 0.002, "回测一直是建得起来的那一边"


def pytest_approx(values: list[float]) -> list[float]:
    """权重经过 qty 量化后有 1e-12 量级的残差；逐位相等不是这条测试问的问题。"""
    from pytest import approx

    return approx(values, abs=1e-9)
