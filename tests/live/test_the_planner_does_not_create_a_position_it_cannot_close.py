"""D2：不变式——永远不持有小于绝对臂的仓位。

D1 恢复的是**退出通道**（目标恰为 0 时能真的平掉）。它不阻止零头产生：一个衰减中的模型目标几乎
不会落在恰好 0 上，所以 2026-09-14 的 ENAUSDT 在 D1 打开的情况下仍然会被造出来，只是止损从此打得动。

零头是**规划器自己造的**：减仓单的大小按模型目标算，而没有任何规则禁止那个目标落在带宽里面。
一旦落进去，`|current| < threshold` 就永久成立——目标归零能要求的最大缺口就是 `|current|` 本身。
实盘日志里 170 笔成交有 7 笔（4%）把仓位留在了带宽内；两次持续超过一天的都是 ENAUSDT。

两条真实路径，两种造法，一条规则要同时管住：

* 2026-09-14T10:00Z  −68.92 -> 目标 −11.20（**减仓**落进带宽）
* 2026-09-10T13:00Z  +212.56 -> 目标 −51.10（**翻向**落进带宽）

所以规则不是「减仓时归零」，是「落进带宽就当作平」。它同时管住减仓、翻向和从空仓建小仓——
最后一项正是 `BAND_BLOCKS_ENTRY` 今天已经在做的事，于是 D1+D2 同开时小额建仓仍然不会发生，
而平仓永远打得动。`flat_inside_band` 默认 False。
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from starquant_alpha.portfolio import apply_no_trade_band
from starquant_exchange.rules import InstrumentRules
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_shared.types import Position

#: 2026-09-14T10:00:17Z 的实盘读数。
EQUITY, PRICE, BAND = 10_913.0, 0.14217, 0.005
RULES = {"ENAUSDT": InstrumentRules("ENAUSDT", Decimal("0.00001"), Decimal("1"), Decimal("1"), Decimal("5"))}


def _plan(target_weight: float, qty: float, **knobs: bool):
    positions = {"ENAUSDT": Position("ENAUSDT", qty=qty, entry_price=PRICE, mark_price=PRICE, unrealized_pnl=0.0)}
    return plan_rebalance(
        {"ENAUSDT": target_weight},
        managed_symbols=["ENAUSDT"],
        equity=EQUITY,
        positions=positions,
        prices={"ENAUSDT": PRICE},
        rules=RULES,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=BAND, no_trade_rel_band=0.40, **knobs),
    )


def test_the_shipped_default_still_creates_the_stub() -> None:
    """默认关。这条记的是 2026-09-14 真正发生的事，不是一个假想。"""
    assert RebalanceParams().flat_inside_band is False
    orders, _ = _plan(-11.198673245798089 / EQUITY, -484.0)
    assert len(orders) == 1 and orders[0].reduce_only
    left = -484.0 + float(orders[0].quantity)
    assert abs(left * PRICE) < BAND * EQUITY, "留下 −11.2 USDT，对着 54.6 USDT 的带宽：从此平不掉"


def test_a_reduction_that_would_land_inside_the_band_closes_instead() -> None:
    """09-14 10:00Z 这一笔：应当平掉全部 484，而不是留 79。"""
    orders, _ = _plan(-11.198673245798089 / EQUITY, -484.0, flat_inside_band=True)
    assert len(orders) == 1 and orders[0].reduce_only
    assert float(orders[0].quantity) == 484.0, "留下的任何一张都是平不掉的"
    assert orders[0].target_notional == 0.0


def test_a_flip_that_would_land_inside_the_band_closes_instead() -> None:
    """09-10 13:00Z 这一笔：+212.56 翻到 −51.10 造出了第一个零头，减仓规则抓不到它。"""
    qty = 212.56 / PRICE
    orders, _ = _plan(-51.10 / EQUITY, qty, flat_inside_band=True)
    assert len(orders) == 1
    assert orders[0].target_notional == 0.0, "不翻到一个平不掉的空头，先回到平"
    assert float(orders[0].quantity) * PRICE == pytest_close(212.56)


def test_a_target_above_the_band_is_untouched() -> None:
    """带宽之外的仓位照常按模型目标走——这条不变式只管带宽以内。"""
    orders, _ = _plan(-200.0 / EQUITY, -484.0, flat_inside_band=True)
    assert orders[0].target_notional == pytest_close(-200.0)


def test_the_backtest_half_carries_the_same_rule_under_the_same_name() -> None:
    """`exempt_reductions` 的先例：两个半边必须一起翻，否则回测评的是实盘执行不了的一本账。"""
    from dataclasses import replace

    from starquant_alpha.portfolio import PortfolioParams

    assert PortfolioParams().flat_inside_band is False
    path = [-0.0200, -0.0010]  # 减仓落进 0.005 的带宽
    assert apply_no_trade_band(pd.DataFrame({"X": path}), BAND, 0.0)["X"].tolist()[-1] == -0.0010
    snapped = apply_no_trade_band(pd.DataFrame({"X": path}), BAND, 0.0, flat_inside=True)["X"].tolist()
    assert snapped[-1] == 0.0, "回测那半边也不能持有一个实盘平不掉的仓位"
    assert replace(PortfolioParams(), flat_inside_band=True).flat_inside_band is True


def test_only_both_knobs_together_clear_a_stub_that_already_exists() -> None:
    """不显然，所以钉在这里：清掉**既有**零头需要两个旋钮，单开任何一个都不行。

    D2 把目标改成 0，但 `|current|` 本来就小于带宽，所以缺口仍然过不了带——除非 D1 让归零的平仓
    豁免带宽。反过来 D1 单开也不够：模型目标是 −0.05% 而不是恰好 0，够不着 D1 的豁免条件。
    这就是 2026-09-14T16:00Z 那根周期的 ENAUSDT，−79 张对 54.32 USDT 的带宽。
    """
    equity, price, qty, target = 10_863.92, 0.14165, -79.0, -0.000499986076520173
    rules = {"ENAUSDT": InstrumentRules("ENAUSDT", Decimal("0.00001"), Decimal("1"), Decimal("1"), Decimal("5"))}
    positions = {"ENAUSDT": Position("ENAUSDT", qty=qty, entry_price=0.14007, mark_price=price, unrealized_pnl=0.0)}

    def plan(**knobs: bool) -> list[object]:
        orders, _ = plan_rebalance(
            {"ENAUSDT": target},
            managed_symbols=["ENAUSDT"],
            equity=equity,
            positions=positions,
            prices={"ENAUSDT": price},
            rules=rules,
            bar_open_ms=0,
            params=RebalanceParams(no_trade_band=0.005, no_trade_rel_band=0.40, **knobs),
        )
        return orders

    assert plan() == [], "今天：平不掉"
    assert plan(exempt_crossings=True) == [], "D1 单开不够——目标不是恰好 0"
    assert plan(flat_inside_band=True) == [], "D2 单开不够——归零后的缺口仍然小于带宽"
    both = plan(exempt_crossings=True, flat_inside_band=True)
    assert len(both) == 1 and float(both[0].quantity) == 79.0 and both[0].reduce_only


def pytest_close(value: float) -> float:
    from pytest import approx

    return approx(value, rel=1e-3)
