"""「先套退出层再定价」在这个包里只有一处表达，邻域探针也走它。

2026-09-17 的 alpha 模块深度分析把「六条命令量三本书」列为口径缺陷，PR #48 下沉了 `score_book`
并给报告加了 `layers`。收尾核对时发现它只做到一半：`validate` 的**邻域探针**
（`parameter_neighborhood` 喂进去的 `evaluate_params`）走的仍是 `_overlaid` + `run_backtest` 的
两步写法。

**那时它不是一个读数错。** `score_book` 的套层那行与 `_overlaid` 字符级相同，而探针不传 `impact`、
`score_book` 的默认也是 `None`，所以两边算的是同一件事——下面第一条测试把这句话本身钉住，而不是
让它停在注释里。

**它是一条会漂的缝。** `score_book` 一旦改套层顺序或再加一层，探针不会自己跟上，于是同一份
validate 报告里「最优那一格」和「它周围的格子」按两种口径算，而没有任何东西会说出来。第二条测试
守的就是这个：包里不许再出现第二处 `_overlaid(` 调用。

`_overlaid` 本身留着，因为 `scratchpad/p32f_embargo_and_decay.py` 从 `starquant_cli.research_cmd`
导入它，而那些脚本是记录——`pyproject.toml` 把它们排除出格式化，理由逐字是「Reformatting either
edits a record of what happened」。所以这里既断言它还在那个地址上，也断言包里没人再调它。
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from starquant_alpha.backtest import CostModel, run_backtest
from starquant_alpha.overlays.exits import ExitParams
from starquant_alpha.panel import Panel
from starquant_alpha.validation.pipeline import score_book
from starquant_cli import research_cmd
from starquant_cli.research_book_eval import _overlaid

ROOT = Path(__file__).resolve().parents[2]


def _panel() -> tuple[Panel, pd.DataFrame]:
    """一段有走势也有回撤的价格，好让退出层真的触发而不是空转。"""
    index = pd.date_range("2026-01-01", periods=240, freq="h", tz="UTC")
    rng = np.random.default_rng(20260917)
    frames = {}
    for symbol in ("AAAUSDT", "BBBUSDT"):
        steps = rng.normal(0.0, 0.02, len(index))
        steps[60:80] -= 0.05  # 一段明确的回撤，止损才有机会响
        frames[symbol] = 100.0 * np.exp(np.cumsum(steps))
    close = pd.DataFrame(frames, index=index)
    panel = Panel(
        interval="1h",
        open=close.shift(1).bfill(),
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=close * 0.0 + 1e6,
    )
    weights = pd.DataFrame(0.5, index=index, columns=close.columns)
    return panel, weights


def test_score_book_is_the_two_step_expression_it_replaced() -> None:
    """替换掉的那两步与 `score_book` 逐位相等——这是「拆的是缝不是读数」的全部依据。

    不是「差不多」：`pd.testing` 的默认容差会放过一个真实的口径差，所以这里要逐位。
    """
    panel, weights = _panel()
    cost = CostModel(turnover_bps=7.0)
    exits = ExitParams(stop_loss=2.0, take_profit=4.0, bars_per_day=24)

    priced, overlaid = score_book(panel, weights, cost, execution="open_to_close", exits=exits)
    old_overlaid = _overlaid(weights, panel.close, exits)
    old_priced = run_backtest(panel, old_overlaid, cost, execution="open_to_close")

    # 先证明这条测试不是空转：退出层如果一次都没触发，下面比的就是两个原样的 frame，
    # 而价格 fixture 一变它会**静默**退化成那样。实测改动 144/480 个格子（30%）。
    changed = int((old_overlaid != weights).sum().sum())
    assert changed > weights.size // 10, f"退出层只改了 {changed} 个格子，这条等价断言等于没测"

    pd.testing.assert_frame_equal(overlaid, old_overlaid, check_exact=True)
    pd.testing.assert_series_equal(priced.portfolio_net, old_priced.portfolio_net, check_exact=True)


def test_exits_none_also_agrees() -> None:
    """`exits=None` 是「这条协议不套层」的陈述，两边对它的处理也必须一样。"""
    panel, weights = _panel()
    cost = CostModel(turnover_bps=7.0)
    priced, overlaid = score_book(panel, weights, cost, execution="open_to_close", exits=None)
    old = run_backtest(panel, _overlaid(weights, panel.close, None), cost, execution="open_to_close")
    pd.testing.assert_frame_equal(overlaid, weights, check_exact=True)
    pd.testing.assert_series_equal(priced.portfolio_net, old.portfolio_net, check_exact=True)


def test_nothing_in_the_package_calls_the_two_step_form_any_more() -> None:
    """包里只许有一处「先套层再定价」。多出第二处，这条缝就又开了。"""
    callers = []
    for path in sorted((ROOT / "starquant_cli").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_overlaid":
                callers.append(f"{path.name}:{node.lineno}")
    assert not callers, (
        f"这些地方又在用 `_overlaid` 的两步写法：{callers}。用 "
        "`starquant_alpha.validation.pipeline.score_book`——它是「先套层再定价」的唯一实现。"
    )


def test_the_address_scratchpad_uses_is_still_there() -> None:
    """`scratchpad/p32f_embargo_and_decay.py` 按这个地址导入它，而那个脚本是记录，不改。"""
    assert hasattr(research_cmd, "_overlaid")
    assert research_cmd._overlaid is _overlaid
    script = ROOT / "scratchpad" / "p32f_embargo_and_decay.py"
    assert "_overlaid" in script.read_text(encoding="utf-8"), "脚本不再用它时，这个地址才可以撤"
