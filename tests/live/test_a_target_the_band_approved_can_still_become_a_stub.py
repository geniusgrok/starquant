"""D3：D2 判的是目标落在哪，而仓位是**之后**靠价格漂进带宽的，那时这条规则再不过问。

2026-09-14 那节（`docs/RESEARCH_LOG.md`）记了两条造零头的路径，减仓落进带宽与翻向落进带宽，
两条问的都是「目标落在哪」。LSKUSDT 是第三条，它问的是「仓位漂到哪」：

    09-16T21:00Z  BUY 74 @0.7287，目标 54.08 对 band 53.92——清线 0.3%，D2 放行
    09-16T22:00Z  价格 −8%，|current| 49.53 < band 53.74  →  BAND_BLOCKS_EXIT
    09-17T14:00Z  |current| 35.45，14 根周期全是 BAND_BLOCKS_EXIT，止损 6σ 对天花板 2.21σ

一小时。入口那一刻 D2 对它没有意见，因为那一刻它是对的。

**为什么判目标而不判 `|current|`。** 「当前小于带宽就平掉」会震荡：LSKUSDT 的目标是权益的
0.53%，带宽 0.50%，小时 σ 9.2%，于是平掉、按未变的目标重建、下一根再平。判目标是稳的，因为
目标是模型握住不动的那个数——58.66 每根周期都小于 2×55.33，所以它保持平仓而不是每小时闪一次。
它同时清掉**存量**，因为被判为平的目标就是恰好 0 的目标，而那正是 D1 唯一放行穿过带宽的情形。
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from starquant_alpha.portfolio import PortfolioParams, apply_no_trade_band
from starquant_exchange.rules import InstrumentRules
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.types import Position

BAND = 0.005
RULES = {"LSKUSDT": InstrumentRules("LSKUSDT", Decimal("0.0001"), Decimal("1"), Decimal("1"), Decimal("5"))}

#: 2026-09-16T21:00:27Z，造出这笔仓位的那一根。`.starquant/live/cycles.jsonl` 的读数。
ENTRY_EQUITY, ENTRY_PRICE, ENTRY_TARGET_W = 10_783.0, 0.72855, 0.005015560271158057

#: 2026-09-17T14:00:29Z，它卡了 17 小时之后。band 55.33，持仓 35.45，目标 58.66。
NOW_EQUITY, NOW_PRICE, NOW_TARGET_W = 11_065.24401561, 0.4824, 0.005300948692790333
NOW_QTY = 74.0

SHIPPED = {"exempt_crossings": True, "flat_inside_band": True, "band_entry_multiple": 2.0}


def _plan(equity: float, price: float, target_w: float, qty: float, **knobs: object):
    positions = (
        {"LSKUSDT": Position("LSKUSDT", qty=qty, entry_price=ENTRY_PRICE, mark_price=price, unrealized_pnl=0.0)}
        if qty
        else {}
    )
    return plan_rebalance(
        {"LSKUSDT": target_w},
        managed_symbols=["LSKUSDT"],
        equity=equity,
        positions=positions,
        prices={"LSKUSDT": price},
        rules=RULES,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=BAND, no_trade_rel_band=0.40, **knobs),  # type: ignore[arg-type]
    )


def test_the_entry_that_made_the_stub_clears_the_band_by_a_third_of_a_percent() -> None:
    """先把前提钉住：D2 放行它不是 D2 的缺陷，那一刻这个目标确实在带宽之外。"""
    band_notional = BAND * ENTRY_EQUITY
    target_notional = ENTRY_TARGET_W * ENTRY_EQUITY
    assert target_notional > band_notional
    assert target_notional / band_notional < 1.01, "清线不到 1%——这就是 D3 要求的那点余量"


def test_without_d3_the_entry_is_planned_and_the_position_it_leaves_cannot_be_closed() -> None:
    """09-16T21:00Z 那一笔，在 D1+D2 全开的世界里仍然照下不误。"""
    orders, _ = _plan(ENTRY_EQUITY, ENTRY_PRICE, ENTRY_TARGET_W, 0.0, exempt_crossings=True, flat_inside_band=True)
    assert len(orders) == 1 and orders[0].side == "BUY"
    # 下一根：价格 −8%，仓位掉进带宽，此后目标归零也打不动。
    left = float(orders[0].quantity) * ENTRY_PRICE * 0.92
    assert left < BAND * ENTRY_EQUITY, "建出来的仓位一根 bar 之后就在带宽以内"


def test_with_d3_that_same_entry_is_never_planned_and_says_so() -> None:
    orders, skipped = _plan(ENTRY_EQUITY, ENTRY_PRICE, ENTRY_TARGET_W, 0.0, **SHIPPED)
    assert orders == []
    assert [s["reason"] for s in skipped] == ["BAND_BLOCKS_ENTRY"]
    # 归零之后 delta 与 current 都是 0，所以解释这次拒绝的那个量必须单独记下来。
    assert skipped[0]["snapped_from_notional"] == ENTRY_TARGET_W * ENTRY_EQUITY
    assert skipped[0]["threshold"] == BAND * ENTRY_EQUITY


def test_d1_and_d2_together_still_cannot_close_the_stub_that_exists() -> None:
    """09-14 那节的结论到这条路径就不成立了，所以钉在这里。

    那一节量的是 ENAUSDT：目标 −0.05% 落在带宽**以内**，D2 把它归零，D1 让归零的平仓穿过带宽。
    LSKUSDT 的目标 58.66 在带宽**以外**，D2 对它没有意见，于是缺口 23.21 仍然小于带宽 55.33。
    """
    for knobs in (
        {},
        {"exempt_crossings": True},
        {"flat_inside_band": True},
        {"exempt_crossings": True, "flat_inside_band": True},
    ):
        orders, skipped = _plan(NOW_EQUITY, NOW_PRICE, NOW_TARGET_W, NOW_QTY, **knobs)
        assert orders == [], f"{knobs} 不该平得掉"
        assert [s["reason"] for s in skipped] == ["BAND_BLOCKS_EXIT"]


def test_d3_closes_the_stub_that_exists() -> None:
    orders, _ = _plan(NOW_EQUITY, NOW_PRICE, NOW_TARGET_W, NOW_QTY, **SHIPPED)
    assert len(orders) == 1
    assert orders[0].side == "SELL" and orders[0].reduce_only
    assert float(orders[0].quantity) == NOW_QTY, "留下的任何一张都是平不掉的"
    assert orders[0].target_notional == 0.0


def test_it_does_not_oscillate_once_closed_and_stays_visible() -> None:
    """平掉之后目标没变，所以它必须保持平仓——这是判目标而不判 `|current|` 买到的那半边。

    但「不重建」不等于「不出现」：模型每根周期仍然要这个名字，是规则在拒绝，所以每根周期都要
    记一行。静默留给 `leaving`——那种名字是模型自己不要了。
    """
    orders, skipped = _plan(NOW_EQUITY, NOW_PRICE, NOW_TARGET_W, 0.0, **SHIPPED)
    assert orders == [], "不重建"
    assert [s["reason"] for s in skipped] == ["BAND_BLOCKS_ENTRY"], "但仍然可见"
    assert skipped[0]["snapped_from_notional"] == NOW_TARGET_W * NOW_EQUITY


def test_a_leaving_name_stays_silent() -> None:
    """对照：目标本来就是 0 的名字不该被 D3 拉进日志，否则 `leaving` 会每周期刷屏。"""
    orders, skipped = _plan(NOW_EQUITY, NOW_PRICE, 0.0, 0.0, **SHIPPED)
    assert (orders, skipped) == ([], [])


def test_a_target_well_clear_of_the_band_is_untouched() -> None:
    """D3 只管带宽附近。BTCUSDT 那一档（1600 对 55.33）照常按模型目标走。"""
    orders, skipped = _plan(NOW_EQUITY, NOW_PRICE, 1547.48 / NOW_EQUITY, 1600.49 / NOW_PRICE, **SHIPPED)
    assert orders == []
    assert [s["reason"] for s in skipped] == ["NO_TRADE_BAND"], "被相对臂压住，与 D3 无关"


def test_one_point_zero_is_d2_exactly() -> None:
    """出厂默认，以及回滚的形状：`band_entry_multiple` 1.0 与只开 D1+D2 逐位相同。"""
    assert RebalanceParams().band_entry_multiple == 1.0
    assert PortfolioParams().band_entry_multiple == 1.0
    both = _plan(NOW_EQUITY, NOW_PRICE, NOW_TARGET_W, NOW_QTY, exempt_crossings=True, flat_inside_band=True)
    at_one = _plan(
        NOW_EQUITY,
        NOW_PRICE,
        NOW_TARGET_W,
        NOW_QTY,
        exempt_crossings=True,
        flat_inside_band=True,
        band_entry_multiple=1.0,
    )
    assert both == at_one


def test_the_backtest_half_carries_the_same_rule_under_the_same_name() -> None:
    """`exempt_reductions` 与 `flat_inside_band` 的先例：两个半边必须一起翻。"""
    path = [0.0060]  # 带宽 0.005 之外，1×band 放行；2×band 不放行
    assert apply_no_trade_band(pd.DataFrame({"X": path}), BAND, 0.0, True)["X"].tolist() == [0.0060]
    snapped = apply_no_trade_band(pd.DataFrame({"X": path}), BAND, 0.0, True, 2.0)["X"].tolist()
    assert snapped == [0.0], "回测那半边也不能建一个实盘一根 bar 后就平不掉的仓位"


def test_a_multiple_below_one_is_refused() -> None:
    """低于 1.0 会把判据缩成带宽的子集——那仍然是平不掉的仓位，正好是本字段的反面。"""
    import pytest

    with pytest.raises(ValueError, match="band_entry_multiple"):
        PortfolioParams(band_entry_multiple=0.5)
