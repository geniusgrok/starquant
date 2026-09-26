"""第五类归因出路（操作者裁定 2026-09-14）：成对的构造对照臂不是晋级候选。

Phase 0 的回放对「未被采纳的 PASS」原有四条出路——链条停在 book 侧、被同策略后续指针取代、
`capital > 0` 的容量臂、`universe_mode: static` 的稳健性臂。2026-09-14 量 `flat_inside_band`
（D2）代价时产出的两份报告一条都不符合（`pit`、`capital: 0`、比在位指针更晚），AC-G0 0 -> 2。

**这条规则最危险的地方是它赦免的正是提出它的人自己的产物。** 所以它的价值不在「让那两份变绿」，
而在三个条件能不能挡住任意产物：把两份新构造配成一对就想双双脱罪、把两个旋钮一起翻、
或者随手拿两份不同跑法的报告凑数——这个文件里的四条反例测试就是为此而写，
它们比那条正例测试重要。

判据（全部读自 artefact，不读意图）：同策略、**运行设置逐项相同**（range/symbols/interval/
universe_mode/min_tenure/execution/folds/min_train/purge/embargo/grid）、`portfolio` **恰好差一个键**，
且**两臂中至少有一臂在与在位指针的共有键上完全一致**。最后一条是锚：它要求这对测量是拿今天这本账
当对照跑的，于是「配两份新构造双双脱罪」这条路走不通。

共有键比对沿用 `starquant_alpha.registry.construction_problems` 的规矩（`if key in recorded`）：
早于某个字段的在位报告不带那个键，跳过该键而不是判为不一致——否则每加一个构造键都会让锚失效。
"""

from __future__ import annotations

from typing import Any

from starquant_governance.replay import paired_construction_arm

ADOPTED = "tsmom-validation-20260913T182325Z.json"

#: 在位指针的构造。不带 `flat_inside_band`——它是那份报告产出之后才有的键。
ADOPTED_PORTFOLIO = {"vol_target": 0.6, "no_trade_band": 0.005, "no_trade_rel_band": 0.4, "sleeve_max_gross": 0.0}

RUN = {
    "strategy": "tsmom",
    "range": {"bars": 49_968, "start": "2021-01-31 01:00:00+00:00", "end": "2026-09-13 23:00:00+00:00"},
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "interval": "1h",
    "universe_mode": "pit",
    "min_tenure": 0,
    "execution": "open_to_close",
    "folds": 5,
    "min_train": 4000,
    "purge": 50,
    "embargo": 50,
    "grid": {"crowding_window": [0, 72]},
}


def _report(**portfolio: Any) -> dict[str, Any]:
    return {**RUN, "kind": "validation", "verdict": "PASS", "portfolio": {**ADOPTED_PORTFOLIO, **portfolio}}


CONTROL = _report(flat_inside_band=False)
TREATMENT = _report(flat_inside_band=True)
ADOPTED_REPORT = {**RUN, "kind": "validation", "verdict": "PASS", "portfolio": dict(ADOPTED_PORTFOLIO)}


def _reports(**extra: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"reports/research/{name}": report for name, report in extra.items()}


def test_both_arms_of_a_real_pair_are_attributed() -> None:
    """正例：2026-09-14 的那对。控制臂是锚，处理臂只翻了 `flat_inside_band`。"""
    reports = _reports(**{"a-control.json": CONTROL, "b-treatment.json": TREATMENT, ADOPTED: ADOPTED_REPORT})
    for name in ("a-control.json", "b-treatment.json"):
        assert paired_construction_arm(name, reports[f"reports/research/{name}"], reports, {ADOPTED}), (
            f"{name} 是成对测量的一臂，不是晋级候选"
        )


def test_a_lone_report_with_a_novel_construction_is_not_excused() -> None:
    """反例一：没有对臂就没有「成对测量」，它只是一个候选。"""
    reports = _reports(**{"b-treatment.json": TREATMENT, ADOPTED: ADOPTED_REPORT})
    assert not paired_construction_arm("b-treatment.json", TREATMENT, reports, {ADOPTED})


def test_two_novel_constructions_paired_with_each_other_are_not_excused() -> None:
    """反例二，这条是规则的锚：把两份新构造配成一对不能让它们双双脱罪。

    两臂相差恰好一个键、运行设置也相同——前两个条件都满足；缺的是任何一臂等于今天这本账。
    没有这一条，这条出路就是一张任填的空白支票。
    """
    left = _report(flat_inside_band=True, vol_target=0.75)
    right = _report(flat_inside_band=False, vol_target=0.75)
    reports = _reports(**{"a.json": left, "b.json": right, ADOPTED: ADOPTED_REPORT})
    assert not paired_construction_arm("a.json", left, reports, {ADOPTED})
    assert not paired_construction_arm("b.json", right, reports, {ADOPTED})


def test_a_pair_that_moves_two_knobs_at_once_is_not_excused() -> None:
    """反例三：两个旋钮一起翻的不是「一次测量」，它是一本新账。"""
    both = _report(flat_inside_band=True, no_trade_band=0.01)
    reports = _reports(**{"a-control.json": CONTROL, "b-both.json": both, ADOPTED: ADOPTED_REPORT})
    assert not paired_construction_arm("b-both.json", both, reports, {ADOPTED})


def test_two_reports_from_different_runs_do_not_count_as_a_pair() -> None:
    """反例四：随手拿两份跑法不同的报告凑对——差一个构造键是巧合，不是设计。"""
    elsewhere = {**TREATMENT, "range": {**RUN["range"], "end": "2026-09-01 00:00:00+00:00"}}
    reports = _reports(**{"a-control.json": CONTROL, "b-elsewhere.json": elsewhere, ADOPTED: ADOPTED_REPORT})
    assert not paired_construction_arm("b-elsewhere.json", elsewhere, reports, {ADOPTED})


def test_the_anchor_skips_keys_the_adopted_pointer_predates() -> None:
    """锚按共有键比对，否则每新增一个构造键都会让在位指针失去锚的资格。

    这正是 2026-09-14 的实情：在位的 20260913T182325Z 产出于 `flat_inside_band` 存在之前。
    """
    assert "flat_inside_band" not in ADOPTED_PORTFOLIO
    reports = _reports(**{"a-control.json": CONTROL, "b-treatment.json": TREATMENT, ADOPTED: ADOPTED_REPORT})
    assert paired_construction_arm("a-control.json", CONTROL, reports, {ADOPTED})


def test_an_unadopted_pointer_cannot_serve_as_the_anchor() -> None:
    """锚必须是**被采纳的**那份。拿一份自己产出的报告当锚等于自己给自己发许可证。"""
    reports = _reports(**{"a-control.json": CONTROL, "b-treatment.json": TREATMENT, ADOPTED: ADOPTED_REPORT})
    assert not paired_construction_arm("a-control.json", CONTROL, reports, set()), "没有任何被采纳的指针时不能归因"
