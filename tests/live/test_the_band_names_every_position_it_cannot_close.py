"""E：`BAND_BLOCKS_EXIT` 量的东西，和 `plan_gaps` 自己声称它量的东西，不是一回事。

`reports.plan_gaps` 的 docstring 写着「a position smaller than the band can never be closed to
zero, so those symbols are stuck for as long as the target stays that size」——那是一条关于**仓位**
的陈述：`|current| < threshold` 时，目标归零产生的缺口最大也只有 `|current|`，永远过不了带。

但 `rebalancer` 只在**目标恰为 0** 时才贴这个标签，而一个正在衰减的模型目标几乎不会恰好落在 0 上。
2026-09-14 的 ENAUSDT 就是这样：−79 张（−11.19 USDT，5x 下保证金 2.24 USDT）对着 −5.43 USDT 的目标，
带宽 54.32 USDT，从 11:00Z 起每根周期都被压住，全部记成普通的 `NO_TRADE_BAND`。当天的
`report daily` 因此显示 `blocked_exit: []`、`by_reason: {"NO_TRADE_BAND": 270}`——那个专门为这种
情况写的字段，在它唯一一次该出声的时候是空的，操作者是从币安界面上用肉眼发现这笔仓位的。

这条测试把标签钉到那个结构性事实上（仓位小于带宽 = 平不掉），而不是钉到「这一根的目标恰好是 0」
这个偶然上。不改任何订单：三种结果都仍然是「无单」，变的只是哪一种被叫作什么。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from starquant_exchange.rules import InstrumentRules
from starquant_live.rebalancer import RebalanceParams, plan_rebalance
from starquant_live.reports import plan_gaps
from starquant_live.state import StateStore
from starquant_shared.types import Position

#: 2026-09-14T16:00:27Z 那根周期的实盘读数。
EQUITY = 10_863.91920325
PRICE = 0.14165
QTY = -79.0
RULES = {"ENAUSDT": InstrumentRules("ENAUSDT", Decimal("0.00001"), Decimal("1"), Decimal("1"), Decimal("5"))}


def _plan(target_weight: float, qty: float) -> list[dict[str, object]]:
    positions = (
        {"ENAUSDT": Position("ENAUSDT", qty=qty, entry_price=0.14007, mark_price=PRICE, unrealized_pnl=0.0)}
        if qty
        else {}
    )
    orders, skipped = plan_rebalance(
        {"ENAUSDT": target_weight},
        managed_symbols=["ENAUSDT"],
        equity=EQUITY,
        positions=positions,
        prices={"ENAUSDT": PRICE},
        rules=RULES,
        bar_open_ms=0,
        params=RebalanceParams(no_trade_band=0.005, no_trade_rel_band=0.40),
    )
    assert orders == [], "这些情形一笔单都不该下；这条测试只管标签"
    return skipped


def test_a_position_below_the_band_is_named_blocked_exit_whatever_the_target_reads() -> None:
    """平不掉是仓位的性质，不是这一根目标读数的性质。"""
    # 实盘当时的读数：目标 −0.05% 权益，不是 0。
    live = _plan(-0.000499986076520173, QTY)
    assert live[0]["reason"] == "BAND_BLOCKS_EXIT", (
        f"−11.19 USDT 的仓位对 54.32 USDT 的带宽，目标归零也只有 11.19 的缺口——它平不掉。"
        f"标签却是 {live[0]['reason']}，于是 report daily 的 blocked_exit 是空的。"
    )
    # 目标恰为 0（退出层触发 / 移出 universe）本来就该是这个标签，不能回归。
    assert _plan(0.0, QTY)[0]["reason"] == "BAND_BLOCKS_EXIT"


def test_the_row_carries_the_position_that_makes_it_unclosable() -> None:
    """报告要能复核这个判断，而不是相信标签。"""
    row = _plan(-0.000499986076520173, QTY)[0]
    assert row["current_notional"] == QTY * PRICE
    assert abs(float(row["current_notional"])) < float(row["threshold"])


def test_an_ordinary_resize_above_the_band_keeps_its_own_name() -> None:
    """仓位大于带宽时压住的是一次普通调仓，它平得掉，不该混进 blocked_exit。"""
    row = _plan(-0.1010, QTY * 100)[0]  # −1119 USDT 的仓位，远大于带宽，目标只小了 22 USDT
    assert row["reason"] == "NO_TRADE_BAND"
    assert abs(float(row["current_notional"])) > float(row["threshold"])


def test_flat_and_wanting_a_sub_band_position_is_still_blocked_entry() -> None:
    """另一侧不动：空仓想建一个小于带宽的仓位，永远建不起来。"""
    assert _plan(-0.000499986076520173, 0.0)[0]["reason"] == "BAND_BLOCKS_ENTRY"


def test_the_daily_report_names_the_stranded_symbol(tmp_path: Path) -> None:
    """E 的落点：操作者读的是这张表，不是 cycles.jsonl。"""
    store = StateStore(tmp_path / "live")
    store.append_cycle(
        {
            "bar": "2026-09-14T16:00:00+00:00",
            "bar_open_ms": 1_789_398_000_000,
            "equity": EQUITY,
            "skipped": [
                {
                    "symbol": "ENAUSDT",
                    "reason": "BAND_BLOCKS_EXIT",
                    "delta_notional": 5.77008277193487,
                    "current_notional": QTY * PRICE,
                    "threshold": 54.319596016249996,
                }
            ],
        }
    )
    gaps = plan_gaps(store, "2026-09-14")
    assert gaps["blocked_exit"] == ["ENAUSDT"], "这个字段存在的唯一理由就是这种情况"
