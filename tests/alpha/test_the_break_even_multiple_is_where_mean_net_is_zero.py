"""保本成本倍数 m*：成本乘到 m* 倍，净收益均值归零；而这个数碰不到任何 verdict（G8，2026-09-23）。

validate 的成本压力只有 1 / 1.5 / 2 倍三格，报告里没有「成本涨到几倍净收益归零」这个数。
`break_even_cost_multiple` 补上它。本文件钉住五件事：

1. **它就是零点**。在 m* 处独立重跑一次 `run_backtest`，净收益均值在容差内为 0。book 按 validate 的
   办法建：tsmom 的决策权重套上 profile 的 exit overlay，再回放 book guards。
2. **线性的前提**。book 固定时（不回放 guards），每根 bar 的净收益对 m 严格线性。随 m 变的只有换手与
   carry 两项；资金费与冲击成本照收，但不随 m 变，只落在截距里。所以这时第一次猜测就是答案。
3. **路径依赖**。日内亏损暂停读的是扣完成本的权益：成本越高，暂停越多，book 就不是同一本。只拿 x1
   与 x2 连线会差出去，要在猜测处重新定价才找得回来。收紧暂停线让它在这份 fixture 上真的发生，并先
   断言它发生了。
4. **找不到时如实说**。零点之下就亏、成本涨了均值不降、零点正落在一个跳变上，三种情况都不许报成一个
   收敛的 m*。
5. **只报告，不判定**。遍历 `reports/research/` 下全部归档的 validation 报告（递归，子目录里也有），
   注入敌意值，verdict 与 reasons 一个字都不能动。

输入取自真实数据：`august_panel` 是 2026-08 的四个币安 1h K 线。手写的只有三处：第 2 条的资金费
（August 没有资金费数据），第 4 条的「均值不降」与「跨过零的跳变」（这两种形状真实数据给不了）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from starquant_alpha.backtest import CostModel, ImpactModel, run_backtest
from starquant_alpha.overlays.exposure import BookGuardParams
from starquant_alpha.panel import Panel
from starquant_alpha.registry import StrategyEntry
from starquant_alpha.validation.pipeline import score_book
from starquant_alpha.validation.stability import BREAK_EVEN_TOLERANCE, break_even_cost_multiple
from starquant_alpha.validation.verdict import decide
from starquant_cli.research_book_eval import _book_guards, _exit_params
from starquant_cli.research_panel import _entry, _model
from starquant_shared.config import load_yaml

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "research"
PROFILE = load_yaml(ROOT / "config" / "live.demo.yaml")
# The horizons every validate test runs on this fixture: the shipped [168, 336, 720] need more than
# August's 720 bars.
PARAMS = '{"horizons": [5, 20, 50], "crowding_window": 0}'


def _validate_book(panel: Panel) -> tuple[pd.DataFrame, BookGuardParams]:
    """The post-overlay decision frame validate re-prices at every cost level, and the guards it replays."""
    entry = _entry("tsmom", str(ROOT / "config" / "alpha_registry.yaml"), PARAMS)
    weights, _c, _p = _model(StrategyEntry(id="tsmom", params=entry.params), PROFILE, "1h", 0).evaluate(panel, None)
    guards = _book_guards(PROFILE, True)
    assert guards is not None
    _result, decisions = score_book(panel, weights, CostModel(), guards=guards, exits=_exit_params(PROFILE, True, "1h"))
    return decisions, guards


def _pricer(panel: Panel, decisions: pd.DataFrame, guards: BookGuardParams | None) -> Callable[[float], pd.Series]:
    """validate's `_priced`: the same book at `turnover_bps` x m, guards replayed."""
    return lambda m: run_backtest(panel, decisions, CostModel(7.0 * m, 0.0, False), guards=guards).portfolio_net


def _pauses(panel: Panel, decisions: pd.DataFrame, guards: BookGuardParams, m: float) -> int:
    events = run_backtest(panel, decisions, CostModel(7.0 * m, 0.0, False), guards=guards).guard_events
    assert events is not None
    return int(events["daily_loss_pause"].sum())


def test_repricing_the_book_at_m_star_leaves_a_zero_mean(august_panel: Panel) -> None:
    """验收那一条：m* 处重跑，净收益均值在容差内为 0——全样本一次，只取后半段再一次（`view` 真的被用上）。

    这里的后半段不是 validate 的样本外。那一条由 CLI 测试按报告自己的 fold 重切来核。
    """
    decisions, guards = _validate_book(august_panel)
    price = _pricer(august_panel, decisions, guards)
    priced = {m: price(m) for m in (1.0, 1.5, 2.0)}

    for view in (lambda net: net, lambda net: net.iloc[len(net) // 2 :]):
        found = break_even_cost_multiple(price, priced, view)

        assert found["converged"] and found["multiple"] > 2.0
        again = float(view(price(found["multiple"])).mean())
        assert abs(again) <= BREAK_EVEN_TOLERANCE * found["cost_per_multiple"]
        assert found["mean_net_at_multiple"] == again, "报告里的残差要是在 m* 处真重跑出来的那个数"
        # the Sharpe's zero is the mean's: the x1 cell is positive, and one step past m* is not
        assert float(view(price(found["multiple"] * 1.01)).mean()) < 0.0 < float(view(priced[1.0]).mean())


def test_a_fixed_book_is_affine_in_m_and_funding_and_impact_sit_in_the_intercept(august_panel: Panel) -> None:
    """不回放 guards 时，每根 bar 上 net(m) - net(1) 恰好是 -(m-1) 乘以换手与 carry 的成本。

    资金费用手写的 8 小时结算（August 没有资金费数据），冲击成本开在 1e7 USDT 上：两者都真的在收，
    而且都不出现在斜率里。carry 设成非零，让「两项一起乘」的两项都被乘到。
    """
    decisions, _guards = _validate_book(august_panel)
    rng = np.random.default_rng(7)
    funding = pd.DataFrame(0.0, index=august_panel.index, columns=august_panel.symbols)
    settles = august_panel.index.hour % 8 == 0
    funding.loc[settles] = rng.normal(1e-4, 2e-4, size=(int(settles.sum()), len(august_panel.symbols)))
    panel = replace(august_panel, funding=funding)
    impact = ImpactModel(capital=1e7)

    def run(m: float) -> Any:
        return run_backtest(panel, decisions, CostModel(7.0 * m, 0.5 * m, True), impact=impact)

    base = run(1.0)
    scaled = base.turnover * (7.0 / 1e4) + base.weights.abs().sum(axis=1) * (0.5 / 1e4)
    paid_funding = (base.weights * funding.reindex(base.weights.index)).sum(axis=1)
    paid_impact = base.costs.sum(axis=1) - scaled - paid_funding
    # impact is charged only on bars that trade, and the band keeps most bars still: 19 of 519 here
    assert (paid_funding != 0).sum() >= 50 and (paid_impact.abs() > 1e-12).sum() >= 10, "两项没在收，下面就是空转"
    for m in (0.0, 0.5, 2.0, 7.3):
        moved = run(m).portfolio_net - base.portfolio_net
        np.testing.assert_allclose(moved.to_numpy(), (-(m - 1.0) * scaled).to_numpy(), rtol=0.0, atol=1e-15)

    price = lambda m: run(m).portfolio_net  # noqa: E731
    found = break_even_cost_multiple(price, {1.0: price(1.0), 2.0: price(2.0)})
    assert found["converged"] and found["repricings"] == 1, "线性时 x1、x2 连线的零点就是答案"
    assert found["multiple"] == found["linear_estimate"]


def test_the_pause_bends_the_line_and_repricing_finds_the_zero_anyway(august_panel: Panel) -> None:
    """暂停线收到 -1%：成本越高暂停越多，x1-x2 连线差出去 1.8 倍，而重新定价仍落在零点上。

    出厂的 -5% 在这个 August 从不触发（`test_shuffling_the_future_moves_no_weight_before_it.py` 记过），
    线性就是精确的，上一条测试说的正是那种情形。这里先证明 book 真的随 m 变了，否则这条测试在空转。
    """
    decisions, shipped = _validate_book(august_panel)
    guards = replace(shipped, daily_loss_pause=-0.01)
    price = _pricer(august_panel, decisions, guards)

    found = break_even_cost_multiple(price, {1.0: price(1.0), 2.0: price(2.0)})

    assert _pauses(august_panel, decisions, guards, found["multiple"]) > _pauses(august_panel, decisions, guards, 1.0)
    assert abs(found["multiple"] - found["linear_estimate"]) > 0.5, "连线本身没差出去，路径依赖没被测到"
    assert found["converged"] and found["repricings"] > 1
    tolerance = BREAK_EVEN_TOLERANCE * found["cost_per_multiple"]
    assert abs(float(price(found["multiple"]).mean())) <= tolerance
    assert abs(float(price(found["linear_estimate"]).mean())) > 1000 * tolerance, "连线的零点不是零点"


def test_no_break_even_is_reported_as_none_and_prices_nothing(august_panel: Panel) -> None:
    """零点在 m < 0，或成本涨了均值不降：都报 None 和原因，而且一次都不重新定价（负的 bps 本来也定不了价）。

    前一种是真实数据：同一本书，从第 300 根起的后三周不计成本也在亏。validate 的 fold 在这份 fixture
    上切不到这一段：`min_train` 被截在 n // 2 = 259，样本外从第 259 根起，那一段的 m* 是正的。
    """
    decisions, guards = _validate_book(august_panel)
    price = _pricer(august_panel, decisions, guards)
    priced = {m: price(m) for m in (1.0, 2.0)}

    def refuse(m: float) -> pd.Series:
        raise AssertionError(f"priced at m={m}")

    late = break_even_cost_multiple(refuse, priced, lambda net: net.iloc[300:])
    index = pd.RangeIndex(24)
    flat = break_even_cost_multiple(refuse, {1.0: pd.Series(1e-5, index), 2.0: pd.Series(1e-5, index)})

    assert float(price(0.0).iloc[300:].mean()) < 0.0, "前提：这一段不计成本也亏"
    assert late["multiple"] is None and not late["converged"] and "below zero" in late["why"]
    assert late["linear_estimate"] < 0.0 and late["repricings"] == 0
    assert flat["multiple"] is None and flat["linear_estimate"] is None and "does not fall" in flat["why"]


def test_a_jump_across_zero_is_reported_unsettled_not_as_a_zero() -> None:
    """均值在 m=9 处从 +1e-6 跳到 -1e-6，哪儿都不为零。上限用完就停，报最后一个点和它的残差，不报收敛。"""

    def mean_at(m: float) -> float:
        return 1e-5 - 1e-6 * m - (2e-6 if m >= 9.0 else 0.0)

    def price(m: float) -> pd.Series:
        return pd.Series(mean_at(m), index=pd.RangeIndex(24))

    found = break_even_cost_multiple(price, {1.0: price(1.0), 2.0: price(2.0)}, max_repricings=5)

    assert not found["converged"] and found["repricings"] == 5
    assert 8.0 < found["multiple"] < 10.0
    assert found["mean_net_at_multiple"] == pytest.approx(mean_at(found["multiple"]), rel=1e-12)
    assert abs(found["mean_net_at_multiple"]) >= 1e-6 * (1 - 1e-9)


def _archived_validations() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for path in sorted(REPORTS.rglob("*validation*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "validation":
            out.append((str(path.relative_to(REPORTS)), payload))
    return out


@pytest.mark.parametrize("multiple", [-99.0, 99.0])
def test_the_break_even_multiple_cannot_move_any_archived_verdict(multiple: float) -> None:
    """两个方向的敌意值：「m* 低于 2 就 FAIL」会被 -99 抓到，「m* 够高就放行」会被 +99 抓到。

    `verdict.decide` 今天读的成本压力只有 `cost_stress.x2`，所以这条测试防的是以后：有人把 m* 「顺手」
    接进一道门。它与 #104 那条（`test_the_regime_table_cannot_move_any_archived_verdict`）同一个形状。
    """
    archived = _archived_validations()
    assert len(archived) >= 80, f"归档的 validation 报告只剩 {len(archived)} 份——这条测试读的就是它们"
    assert any("/" in name for name, _ in archived), "子目录里的报告没被扫到：glob 不是递归的"
    row = {
        "multiple": multiple,
        "converged": multiple > 0,
        "linear_estimate": multiple,
        "cost_per_multiple": 1.0,
        "mean_net_at_multiple": 0.0,
        "repricings": 1,
    }
    hostile = {"full_sample": row, "oos": row, "basis": {}}
    for name, report in archived:
        assert decide({**report, "cost_break_even": hostile}) == decide(report), f"{name}：m* 进了 verdict"
