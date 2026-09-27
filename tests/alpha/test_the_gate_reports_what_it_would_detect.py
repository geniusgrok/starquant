"""D-028 的另一半：门挡得住噪声，那它拦得住多少真东西？（Q-SY1，2026-09-18）

操作者到 2026-09-18 已经四次问「判定条件是不是太严」。前三次的回答都是「不是门」，而且都**没有给数**
——所以问题每次都回来。数一直在手边：每份报告自己存着样本外 Sharpe 估计的抽样方差
（`oos_selection.variance`），而「真 Sharpe 是 s 的策略过得了这道门的概率」是一次正态尾概率。

这个文件钉住三件事：

**一、算出来的数与 2026-09-18 分析 §5.2.1 那张表逐格一致**，而那张表是用仓库自己的证据报告
（`tsmom-validation-20260913T182325Z.json`，registry 引用的那一份）与仓库自己的年化常量（8760，
`panel.py:46`——冻结稿一度用 8766，被独立审查抓出）算的。表进了代码之后，它不能悄悄漂走。

**二、PASS 线只有一个定义。** `PASS_LINE_ANNUAL` 是 `multiple_testing` 里的常量，因为 `verdict`
导入这个模块、箭头不能反着指。重复的代价由下面那条测试付：两个数必须相等。

**三、功效表是上界，不是估计。** 它只含 D-028 的选择门与 D-020 的 PASS 线，不含 CPCV 负路径、PBO、
fold 一致性与成本 ×2 —— 四道真候选同样要过的门。artefact 自己要把这句话带上。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from starquant_alpha.panel import bars_per_year
from starquant_alpha.validation.multiple_testing import (
    PASS_LINE_ANNUAL,
    POWER_SHARPES,
    oos_selection_threshold,
    selection_power,
)
from starquant_alpha.validation.verdict import VerdictThresholds

ROOT = Path(__file__).resolve().parents[2]
CITED = ROOT / "reports" / "research" / "tsmom-validation-20260913T182325Z.json"


def _cited() -> dict[str, Any]:
    return json.loads(CITED.read_text(encoding="utf-8"))


def _power_at(n_trials: int) -> dict[float, float]:
    block = _cited()["oos_selection"]
    table = selection_power(sharpe_variance=block["variance"], bars_per_year=bars_per_year("1h"), n_trials=n_trials)
    assert table is not None
    return {row["true_sharpe_annual"]: row["power"] for row in table["detects"]}


def test_the_power_table_reads_the_same_pass_line_the_verdict_does() -> None:
    """一个常量两处写，只有在有人核对时才不算漂移。"""
    assert VerdictThresholds().pass_oos_sharpe == PASS_LINE_ANNUAL


def test_an_empty_bucket_detects_a_true_sharpe_of_one_the_way_a_coin_does() -> None:
    """操作者那个问题的答案，一行：**50%**，而且与 D-028 无关。

    N=1 时选择门是 0，门就是 D-020 的 1.0 那条线。一个真年化 Sharpe 恰好 1.0 的策略，估计量围绕
    1.0 对称，所以它过线的概率是一半——这是五年样本外的抽样噪声，不是任何人的设计。
    """
    assert _power_at(1)[1.0] == 0.5


def test_the_five_rows_of_the_analysis_table_are_reproduced_to_the_tenth_of_a_point() -> None:
    """§5.2.1 那张表，逐格。年化常量错一点（8766 对 8760）这条就红。"""
    expected = {
        1: (0.500, 0.675, 0.872, 0.989),
        16: (0.326, 0.501, 0.754, 0.966),
        100: (0.157, 0.290, 0.551, 0.897),
        299: (0.096, 0.198, 0.433, 0.834),
        351: (0.089, 0.186, 0.417, 0.823),
    }
    for n_trials, row in expected.items():
        got = _power_at(n_trials)
        for sharpe, want in zip(POWER_SHARPES, row, strict=True):
            assert abs(got[sharpe] - want) < 0.001, f"N={n_trials} 真 Sharpe {sharpe}：{got[sharpe]:.4f} 对 {want}"


def test_the_standard_error_of_a_five_year_out_of_sample_sharpe_is_about_0_44() -> None:
    """整张表都挂在这一个数上，所以它单独有一条测试。"""
    block = _cited()["oos_selection"]
    table = selection_power(sharpe_variance=block["variance"], bars_per_year=bars_per_year("1h"), n_trials=242)
    assert table is not None
    assert abs(table["se_annual"] - 0.4396) < 0.0001
    # 5.16 年：45,240 根 1h bar。样本翻倍才把标准误降到 0.31——这是唯一能动它的东西。
    assert abs(block["n_obs"] / bars_per_year("1h") - 5.164) < 0.001


def test_the_gate_is_the_higher_of_the_two_halves_and_says_which_one_binds() -> None:
    """看见门是 1.0 的人要能分清「桶是空的」与「D-028 恰好落在那儿」。"""
    block = _cited()["oos_selection"]
    empty = selection_power(sharpe_variance=block["variance"], bars_per_year=bars_per_year("1h"), n_trials=1)
    crowded = selection_power(sharpe_variance=block["variance"], bars_per_year=bars_per_year("1h"), n_trials=299)
    assert empty is not None and crowded is not None
    assert empty["binding"] == "pass_line" and empty["gate_annual"] == PASS_LINE_ANNUAL
    assert crowded["binding"] == "selection" and crowded["gate_annual"] > PASS_LINE_ANNUAL


def test_power_only_falls_as_the_bucket_fills_which_is_what_a_trial_costs() -> None:
    """每多花一笔，同桶**所有**候选的功效一起降。这是 ledger 计费的功效版本。"""
    curve = [_power_at(n)[1.5] for n in (1, 16, 100, 242, 299, 315, 351)]
    assert curve == sorted(curve, reverse=True)
    assert curve[0] > curve[-1]


def test_a_sixteen_cell_grid_costs_about_half_a_point_not_two() -> None:
    """2026-09-18 分析 §5.2.1 第 2 点把这个差写成「约 2 个百分点」，实测是 0.49。

    更正记在 `docs/analysis/analysis-calibration.md`。留一条测试而不只是改一句话，是因为这正是
    这条命令存在的理由：手算的表会写错，跑出来的表不会。
    """
    before, after = _power_at(299)[1.5], _power_at(315)[1.5]
    assert abs((before - after) - 0.0049) < 0.0005


def test_the_report_carries_the_bound_rather_than_leaving_it_in_a_docstring() -> None:
    """功效表是上界：四道门不在里面，所以真实联合功效只会更低。artefact 自己要这么说。"""
    rng = np.random.default_rng(7)
    returns = rng.normal(loc=0.0002, scale=0.01, size=20_000)
    block = oos_selection_threshold(returns, n_trials=40, bars_per_year=bars_per_year("1h"))
    power = block["power"]
    assert power is not None
    assert set(power["excludes"]) == {"cpcv_fraction_negative", "pbo", "fold_consistency", "cost_stress_x2"}
    # 门与标准误都是从同一个块里的数派生的，不是第二份估计
    assert power["selection_threshold_annual"] == block["threshold_annual"]
    assert abs(power["se_annual"] - math.sqrt(block["variance"] * bars_per_year("1h"))) < 1e-12


def test_a_series_too_short_to_give_a_sharpe_gives_no_power_either() -> None:
    """「没算」与「算了、什么都发现不了」是两件事，所以是 None 不是空表。"""
    assert oos_selection_threshold(np.array([0.01, -0.01]), n_trials=4, bars_per_year=8760.0)["power"] is None
    assert selection_power(sharpe_variance=0.0, bars_per_year=8760.0, n_trials=4) is None
